"""Twitter/X post fetcher for ticker and coin sentiment.

No free X read path exists: ``api.twitter.com`` requires a paid bearer token,
the ``cdn.syndication.twimg.com`` search endpoint returns an empty body, and
public nitter instances return 0 bytes or 503. This module therefore talks to
twitterapi.io, a metered reseller of X search (per-request pricing, no monthly
floor), keyed by ``TWITTERAPI_IO_KEY``.

Contract matches ``reddit.py`` / ``stocktwits.py``: always returns a string,
never raises, and returns a clearly marked placeholder when the source is
unavailable — so the sentiment analyst reports "no data" instead of inventing
posts, which is the failure mode the analyst redesign in #557 existed to
prevent.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

logger = logging.getLogger(__name__)

_API = "https://api.twitterapi.io/twitter/tweet/advanced_search"
_ACCOUNT_API = "https://api.twitterapi.io/oapi/my/info"
_REPLIES_API = "https://api.twitterapi.io/twitter/tweet/replies"
# Reply threads fetched per run, busiest first. Each page is billed, and beyond
# the top few posts a new-listing feed is mostly airdrop spam with no conversation.
REPLY_THREADS = 3
# Published rates (twitterapi.io/pricing): 1 USD = 100,000 credits, 15 credits per
# returned tweet, 15-credit minimum per call. A search page returns 20 tweets, so
# one sentiment fetch costs ~300 credits ≈ $0.003.
CREDITS_PER_USD = 100_000
CREDITS_PER_TWEET = 15
TWEETS_PER_PAGE = 20
CREDITS_PER_RUN = CREDITS_PER_TWEET * TWEETS_PER_PAGE
_UA = "tradingagents/0.3 (+https://github.com/TauricResearch/TradingAgents)"
# Raised from 15s: the endpoint occasionally stalls well past its ~2s norm, and a
# single stall used to cost the whole source.
_TIMEOUT = 45.0
DEFAULT_LIMIT = 30
# A page returns at most 20 posts; two pages cover the default limit. Each page is
# billed, so this also bounds spend when a cursor never reports exhaustion.
MAX_PAGES = 2
_MAX_BODY_CHARS = 280
# The endpoint intermittently answers a working query with an empty list —
# verified live: the same query returned 20 posts, then 0, then 20 again. One
# retry converts most of those into data. The pause also respects the free
# tier's documented limit of one request every 5 seconds, so the retry itself
# cannot trip a 429.
_RETRY_SLEEP = 5.0

# Response field names are read through aliases: the reseller's schema is not
# contractual, and a renamed field should degrade one column rather than break
# the whole block.
_FIELD_ALIASES = {
    "text": ("text", "full_text", "content"),
    "created": ("createdAt", "created_at", "date"),
    "likes": ("likeCount", "favorite_count", "likes"),
    "retweets": ("retweetCount", "retweet_count", "retweets"),
}
_USER_ALIASES = ("userName", "screen_name", "username")


def _first(obj: dict, names: tuple[str, ...], default=""):
    for name in names:
        if obj.get(name) not in (None, ""):
            return obj[name]
    return default


def _tweets_of(data) -> list:
    tweets = data.get("tweets") if isinstance(data, dict) else None
    return tweets if isinstance(tweets, list) else []


def _get_json(url: str, key: str, timeout: float):
    req = urllib.request.Request(
        url, headers={"X-API-Key": key, "User-Agent": _UA, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _request(params: dict, key: str, timeout: float):
    return _get_json(f"{_API}?{urllib.parse.urlencode(params)}", key, timeout)


def fetch_credit_balance(timeout: float = 10.0) -> dict:
    """Remaining twitterapi.io credits, split by bucket.

    Account lookups are not billed (verified: a balance check left the credit
    total unchanged), but they do count against the free tier's one-request-per-
    five-seconds limit, so callers should cache the result rather than polling.

    Always returns a dict — ``ok`` False with a populated ``error`` when the
    balance could not be read, so a UI can show "unknown" instead of breaking.
    """
    key = os.getenv("TWITTERAPI_IO_KEY", "").strip()
    if not key:
        return {"ok": False, "recharge": 0, "bonus": 0, "total": 0,
                "error": "TWITTERAPI_IO_KEY not set"}
    try:
        data = _get_json(_ACCOUNT_API, key, timeout)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        logger.warning("Twitter credit lookup failed: %s", exc)
        return {"ok": False, "recharge": 0, "bonus": 0, "total": 0,
                "error": f"{type(exc).__name__}: {exc}"}

    if not isinstance(data, dict):
        return {"ok": False, "recharge": 0, "bonus": 0, "total": 0,
                "error": "unexpected response shape"}

    def _int(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    recharge = _int(data.get("recharge_credits"))
    bonus = _int(data.get("total_bonus_credits"))
    return {"ok": True, "recharge": recharge, "bonus": bonus,
            "total": recharge + bonus, "error": ""}


def _build_query(terms: str, start_date: str | None, end_date: str | None,
                 lang: str | None = None) -> str:
    """Assemble the X search string.

    ``-filter:retweets`` is deliberately absent: this reseller returns zero
    results for any query containing it (verified live — the same query scored
    0/0 with it and 20/20 without, while parentheses, OR, ``lang:en``, ``since``
    and ``until`` all work). Retweets are dropped in ``_is_retweet`` instead.

    No language filter by default: the crowd trading a fresh listing tweets in
    Turkish, Chinese, Indonesian and Vietnamese as much as English, and the models
    reading this block handle all of them.
    """
    parts = [f"({terms})"]
    if lang:
        parts.append(f"lang:{lang}")
    if start_date:
        parts.append(f"since:{start_date}")
    if end_date:
        parts.append(f"until:{end_date}")
    return " ".join(parts)


def search_terms(symbol: str, display_name: str | None = None,
                 extra_terms: list[str] | None = None) -> str:
    """Search fragment for a coin: its cashtag, plus its name when that adds reach.

    Measured on $XPLK: the cashtag alone returned 4 posts, while adding the
    project name returned 17 — people write "xPayLink", not "$XPLK". The name is
    quoted so it matches as a phrase, and it is skipped when it merely repeats or
    extends the symbol ("PIPEDOG"/"pipedog", "XPLK Token"), where it would add no
    reach and would reintroduce the bare-symbol noise the cashtag avoids.

    ``extra_terms`` are user-supplied keywords, OR'd in after the automatic
    terms. Multi-word terms are quoted so they match as phrases; a term that
    duplicates an automatic one is dropped.
    """
    cashtag = f"${symbol.strip().upper()}"
    parts = [cashtag]
    name = (display_name or "").strip()
    if name:
        words = name.upper().split()
        if words and words[0] != symbol.strip().upper():
            parts.append(f'"{name}"')
    for term in extra_terms or []:
        term = term.strip()
        if not term:
            continue
        rendered = f'"{term}"' if " " in term else term
        if rendered.upper() not in (p.upper() for p in parts):
            parts.append(rendered)
    return " OR ".join(parts)


def _is_retweet(tweet: dict, body: str) -> bool:
    """True for retweets, which carry no sentiment of their own."""
    return bool(tweet.get("retweeted_tweet")) or body.startswith("RT @")


def fetch_replies(tweet_id: str, key: str, timeout: float,
                  limit: int = TWEETS_PER_PAGE) -> list:
    """Replies to one post, from the dedicated replies endpoint.

    Term search cannot find these: a reply saying "Another scam coin obviously"
    never names the coin, so it matches no query built from the ticker. This
    endpoint returns them by parent id — 20 per page, cursored.
    """
    replies: list = []
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        params = {"tweetId": tweet_id}
        if cursor:
            params["cursor"] = cursor
        payload = _get_json(f"{_REPLIES_API}?{urllib.parse.urlencode(params)}",
                            key, timeout)
        batch = _tweets_of(payload)
        if not batch:
            break
        replies.extend(batch)
        cursor = payload.get("next_cursor") if payload.get("has_next_page") else None
        if not cursor or len(replies) >= limit:
            break
    return replies[:limit]


def collect_thread_replies(posts: list, key: str, timeout: float, *,
                           threads: int = REPLY_THREADS,
                           limit: int = TWEETS_PER_PAGE) -> list:
    """Replies for the busiest posts, reparented to the post they were fetched for.

    Only posts that report replies are fetched, busiest first, capped at
    ``threads`` — every page is billed, and the tail of a post list is mostly
    airdrop spam with no conversation. The endpoint returns nested replies whose
    inReplyToId points mid-thread, so each is reparented to the post it came from;
    otherwise the grouping would file it as an orphan.
    """
    candidates = [p for p in posts if p.get("id") and _as_int(p.get("replyCount")) > 0]
    candidates.sort(key=lambda p: _as_int(p.get("replyCount")), reverse=True)

    collected: list = []
    for post in candidates[:threads]:
        try:
            batch = fetch_replies(post["id"], key, timeout, limit)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            # One stalled thread must not cost the others.
            logger.warning("Twitter reply thread %s failed: %s", post["id"], exc)
            continue
        for reply in batch:
            if isinstance(reply, dict) and reply.get("id") != post["id"]:
                collected.append({**reply, "inReplyToId": post["id"]})
    return collected


def _search_pages(query: str, key: str, timeout: float, limit: int,
                  label: str, sort: str = "Top") -> tuple[list, Exception | None]:
    """Walk result pages for ``query`` until ``limit`` or the cursor runs out.

    A page holds at most 20 posts, so reaching a limit of 30 needs the cursor.
    Pages are billed per returned tweet, so the walk is bounded by MAX_PAGES as
    well as by the limit — a cursor that never reports exhaustion must not spend
    without end.
    """
    tweets: list = []
    last_error: Exception | None = None
    cursor: str | None = None

    for page in range(1, MAX_PAGES + 1):
        params = {"query": query, "queryType": sort}
        if cursor:
            params["cursor"] = cursor

        payload = None
        # Up to three attempts per first page. The endpoint intermittently
        # answers a working query with no results, and it stalls past the
        # timeout more often on broad queries (user keywords with common
        # phrases return big pages) — measured latency is 1.5-1.9s normally,
        # so a stall is worth retrying twice before dropping the source.
        for attempt in (1, 2, 3):
            try:
                payload = _request(params, key, timeout)
                last_error = None
            except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                # OSError covers URLError, HTTPError, and socket timeouts.
                last_error = exc
                logger.warning("Twitter %s page %d attempt %d failed: %s",
                               label, page, attempt, exc)
                payload = None
                if page == 1 and attempt < 3:
                    time.sleep(_RETRY_SLEEP)
                    continue
                break
            if _tweets_of(payload):
                break
            if page == 1 and attempt == 1:
                # Only the first page is worth retrying for emptiness — once; a
                # later page coming back empty means the results ran out.
                time.sleep(_RETRY_SLEEP)
            else:
                break

        if payload is None:
            break
        batch = _tweets_of(payload)
        if not batch:
            break
        tweets.extend(batch)
        cursor = payload.get("next_cursor") if payload.get("has_next_page") else None
        if not cursor or len(tweets) >= limit:
            break

    return tweets[:limit], last_error


def _author(tweet: dict) -> str:
    author = tweet.get("author") or {}
    return _first(author, _USER_ALIASES, "?") if isinstance(author, dict) else "?"


def _credibility(tweet: dict) -> str:
    """Follower count and verification, so a shill is distinguishable from a whale.

    New listings draw giveaway spam from throwaway accounts; both fields come free
    in the response and were previously discarded, leaving the model no way to
    weight a 9-follower account against a 48k one.
    """
    author = tweet.get("author") or {}
    if not isinstance(author, dict):
        return ""
    parts = []
    followers = author.get("followers")
    if isinstance(followers, (int, float)):
        parts.append(f"{followers / 1000:.1f}k followers" if followers >= 1000
                     else f"{int(followers)} followers")
    if author.get("isBlueVerified"):
        parts.append("✓")
    return " · ".join(parts)


def _body(tweet: dict) -> str:
    """One-line, length-capped post text. Newlines would break the layout."""
    text = str(_first(tweet, _FIELD_ALIASES["text"])).replace("\n", " ").strip()
    return text[:_MAX_BODY_CHARS] + "…" if len(text) > _MAX_BODY_CHARS else text


def _short_time(tweet: dict) -> str:
    """"Jul 29 08:25" from X's "Wed Jul 29 08:25:57 +0000 2026" stamp."""
    raw = str(_first(tweet, _FIELD_ALIASES["created"], ""))
    try:
        # THE format, like everywhere else — this used to drop the year
        from tradingagents.positions_view import fmt_when

        return fmt_when(
            datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y").timestamp())
    except ValueError:
        return raw[:16] or "?"


def group_replies(posts: list, replies: list) -> tuple[list, list]:
    """Attach each reply to the post it belongs to.

    Returns ``(threads, orphans)`` where a thread is ``{"post", "replies"}``.
    Replies whose thread was not among the fetched posts are kept as orphans
    rather than dropped — they are engagement on the same coin, just on a post
    the search did not return.
    """
    # One pool, deduplicated: the term search returns replies as results too (they
    # name the coin), so the same tweet can arrive from both searches.
    pool: list = []
    seen_ids = set()
    for tweet in list(posts) + list(replies):
        tid = tweet.get("id")
        if tid and tid in seen_ids:
            continue
        if tid:
            seen_ids.add(tid)
        pool.append(tweet)

    # Classified by what the tweet is, not by what happened to be fetched: a
    # tweet with inReplyToId is a reply even when its parent was not returned,
    # so it renders as one instead of masquerading as an original post.
    def _is_reply(tweet):
        parent = tweet.get("inReplyToId")
        return bool(parent) and parent != tweet.get("id")

    def _parent_id(tweet):
        parent = tweet.get("inReplyToId")
        return parent if parent and parent in seen_ids else None

    tops = [t for t in pool if not _is_reply(t)]
    # Indexed by position, not by id: tweets missing an id would otherwise share
    # a single None key and collapse into one thread, silently dropping posts.
    threads = [{"post": post, "replies": []} for post in tops]
    index_by_id = {p.get("id"): i for i, p in enumerate(tops) if p.get("id")}
    index_by_conversation: dict = {}
    for i, post in enumerate(tops):
        conversation = post.get("conversationId") or post.get("id")
        if conversation:
            index_by_conversation.setdefault(conversation, i)

    orphans = []
    for tweet in pool:
        if not _is_reply(tweet):
            continue                    # already a thread head
        parent = index_by_id.get(_parent_id(tweet))
        if parent is None:
            parent = index_by_conversation.get(tweet.get("conversationId"))
        if parent is None:
            orphans.append(tweet)
        else:
            threads[parent]["replies"].append(tweet)
    return threads, orphans


def format_thread_block(terms: str, start_date: str | None, end_date: str | None,
                        posts: list, replies: list, retweets: int) -> str:
    """Render posts with their replies nested underneath.

    Ordered by engagement so the loudest thread reads first, and led by a counts
    line: for a two-day-old coin, "3 posts · 41 replies · 22 authors" is the
    signal, more than any individual post.
    """
    threads, orphans = group_replies(posts, replies)
    threads.sort(key=lambda t: (_likes(t["post"]) + _retweets_of(t["post"])
                                + len(t["replies"])), reverse=True)

    # Counted from the grouping, not the raw lists: a reply that also arrived in
    # the post search must not inflate either number.
    rendered_posts = [t["post"] for t in threads]
    rendered_replies = [r for t in threads for r in t["replies"]] + orphans
    authors = {_author(t) for t in rendered_posts} | {_author(r) for r in rendered_replies}
    window = f"  ·  {start_date} → {end_date}" if start_date and end_date else ""
    counts = [f"{len(rendered_posts)} post{'s' if len(rendered_posts) != 1 else ''}",
              f"{len(rendered_replies)} repl{'ies' if len(rendered_replies) != 1 else 'y'}",
              f"{len(authors)} author{'s' if len(authors) != 1 else ''}"]
    if retweets:
        counts.append(f"{retweets} retweet{'s' if retweets != 1 else ''} excluded")

    out = [f"## X/Twitter — {terms}{window}", "  ·  ".join(counts), ""]
    for thread in threads:
        post = thread["post"]
        meta = [f"{_likes(post)} likes", f"{_retweets_of(post)} RT"]
        reply_count = _as_int(post.get("replyCount"))
        if reply_count:
            meta.append(f"{reply_count} replies")
        cred = _credibility(post)
        header = f"POST · @{_author(post)}"
        if cred:
            header += f" ({cred})"
        out.append(f"{header} · {_short_time(post)} · " + " · ".join(meta))
        out.append(f"    {_body(post)}")
        for reply in thread["replies"]:
            cred = _credibility(reply)
            who = f"@{_author(reply)}" + (f" ({cred})" if cred else "")
            out.append(f"    ↳ {who} ({_likes(reply)} likes): {_body(reply)}")
        out.append("")

    if orphans:
        out.append(f"OTHER REPLIES mentioning {terms} ({len(orphans)})")
        for reply in orphans:
            cred = _credibility(reply)
            who = f"@{_author(reply)}" + (f" ({cred})" if cred else "")
            out.append(f"    ↳ {who} · {_short_time(reply)} "
                       f"({_likes(reply)} likes): {_body(reply)}")
    return "\n".join(out).rstrip() + "\n"


def _likes(tweet: dict) -> int:
    return _as_int(_first(tweet, _FIELD_ALIASES["likes"], 0))


def _retweets_of(tweet: dict) -> int:
    return _as_int(_first(tweet, _FIELD_ALIASES["retweets"], 0))


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def fetch_twitter_posts(
    terms: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = DEFAULT_LIMIT,
    timeout: float = _TIMEOUT,
    include_replies: bool = True,
    sort: str = "Top",
    lang: str | None = None,
) -> str:
    """Recent X posts matching ``terms``, with their replies, for prompt injection.

    ``terms`` is an X search fragment — a cashtag, a coin name, or an OR of both.
    Replies come from a second search with ``filter:replies``, because the search
    endpoint returns top-level posts only and the dedicated replies endpoint
    returned 1 of a post's 98 replies. Reply volume is the clearest evidence that
    people are actually engaging with a new listing, so it is worth the extra
    page: roughly 300 more credits, about a third of a cent.
    """
    key = os.getenv("TWITTERAPI_IO_KEY", "").strip()
    if not key:
        return "<twitter unavailable: TWITTERAPI_IO_KEY not set>"

    query = _build_query(terms, start_date, end_date, lang=lang)
    tweets, last_error = _search_pages(query, key, timeout, limit, "search", sort)

    if not tweets and last_error is not None:
        return f"<twitter unavailable: {type(last_error).__name__}: {last_error}>"
    if not tweets:
        return f"<no X/Twitter posts found for {terms}>"

    posts, retweets = [], 0
    for tw in tweets:
        if not isinstance(tw, dict):
            continue
        if _is_retweet(tw, _body(tw)):
            retweets += 1              # counted, not shown: no original opinion
            continue
        posts.append(tw)

    if not posts:
        return f"<no X/Twitter posts found for {terms}>"

    replies: list = []
    if include_replies:
        # Replies to the posts themselves, which term search cannot reach.
        replies.extend(collect_thread_replies(posts, key, timeout))
        # A failed reply search must not blank the source; the posts already
        # fetched are worth reporting on their own.
        found, reply_error = _search_pages(f"{query} filter:replies", key, timeout,
                                           limit, "replies", sort)
        if reply_error is not None:
            logger.warning("Twitter reply search failed for %r: %s", terms, reply_error)
        replies.extend(r for r in found
                       if isinstance(r, dict) and not _is_retweet(r, _body(r)))

    return format_thread_block(terms, start_date, end_date, posts, replies, retweets)
