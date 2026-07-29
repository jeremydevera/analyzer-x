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

logger = logging.getLogger(__name__)

_API = "https://api.twitterapi.io/twitter/tweet/advanced_search"
_ACCOUNT_API = "https://api.twitterapi.io/oapi/my/info"
# Published rates (twitterapi.io/pricing): 1 USD = 100,000 credits, 15 credits per
# returned tweet, 15-credit minimum per call. A search page returns 20 tweets, so
# one sentiment fetch costs ~300 credits ≈ $0.003.
CREDITS_PER_USD = 100_000
CREDITS_PER_TWEET = 15
TWEETS_PER_PAGE = 20
CREDITS_PER_RUN = CREDITS_PER_TWEET * TWEETS_PER_PAGE
_UA = "tradingagents/0.3 (+https://github.com/TauricResearch/TradingAgents)"
_TIMEOUT = 15.0
DEFAULT_LIMIT = 30
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


def _build_query(terms: str, start_date: str | None, end_date: str | None) -> str:
    """Assemble the X search string.

    ``-filter:retweets`` is deliberately absent: this reseller returns zero
    results for any query containing it (verified live — the same query scored
    0/0 with it and 20/20 without, while parentheses, OR, ``lang:en``, ``since``
    and ``until`` all work). Retweets are dropped in ``_is_retweet`` instead.
    """
    parts = [f"({terms})", "lang:en"]
    if start_date:
        parts.append(f"since:{start_date}")
    if end_date:
        parts.append(f"until:{end_date}")
    return " ".join(parts)


def _is_retweet(tweet: dict, body: str) -> bool:
    """True for retweets, which carry no sentiment of their own."""
    return bool(tweet.get("retweeted_tweet")) or body.startswith("RT @")


def fetch_twitter_posts(
    terms: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = DEFAULT_LIMIT,
    timeout: float = _TIMEOUT,
) -> str:
    """Recent X posts matching ``terms``, formatted for prompt injection.

    ``terms`` is an X search fragment — a cashtag, a coin name, or an OR of
    both. Engagement counts are included so the model can weight a 400-like
    post above a zero-engagement shill.
    """
    key = os.getenv("TWITTERAPI_IO_KEY", "").strip()
    if not key:
        return "<twitter unavailable: TWITTERAPI_IO_KEY not set>"

    params = {
        "query": _build_query(terms, start_date, end_date),
        "queryType": "Top",
    }
    try:
        data = _request(params, key, timeout)
        tweets = _tweets_of(data)
        if not tweets:
            logger.info("Twitter returned no posts for %r; retrying once.", terms)
            time.sleep(_RETRY_SLEEP)
            data = _request(params, key, timeout)
            tweets = _tweets_of(data)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        # OSError covers URLError, HTTPError, and socket timeouts.
        logger.warning("Twitter fetch failed for %r: %s", terms, exc)
        return f"<twitter unavailable: {type(exc).__name__}: {exc}>"

    if not tweets:
        return f"<no X/Twitter posts found for {terms}>"

    lines = []
    for tw in tweets[:limit]:
        if not isinstance(tw, dict):
            continue
        author = tw.get("author") or {}
        user = _first(author, _USER_ALIASES, "?") if isinstance(author, dict) else "?"
        body = str(_first(tw, _FIELD_ALIASES["text"])).replace("\n", " ").strip()
        if _is_retweet(tw, body):
            continue
        if len(body) > _MAX_BODY_CHARS:
            body = body[:_MAX_BODY_CHARS] + "…"
        lines.append(
            f"[{_first(tw, _FIELD_ALIASES['created'], '?')}] @{user} "
            f"({_first(tw, _FIELD_ALIASES['likes'], 0)} likes, "
            f"{_first(tw, _FIELD_ALIASES['retweets'], 0)} RT): {body}"
        )

    if not lines:
        return f"<no X/Twitter posts found for {terms}>"

    window = f" from {start_date} to {end_date}" if start_date and end_date else ""
    return (
        f"## X/Twitter posts for {terms}{window} "
        f"({len(lines)} posts, ranked by engagement)\n\n" + "\n".join(lines)
    )
