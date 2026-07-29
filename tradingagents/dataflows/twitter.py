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
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_API = "https://api.twitterapi.io/twitter/tweet/advanced_search"
_UA = "tradingagents/0.3 (+https://github.com/TauricResearch/TradingAgents)"
_TIMEOUT = 15.0
DEFAULT_LIMIT = 30
_MAX_BODY_CHARS = 280

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


def _request(params: dict, key: str, timeout: float):
    url = f"{_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url, headers={"X-API-Key": key, "User-Agent": _UA, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _build_query(terms: str, start_date: str | None, end_date: str | None) -> str:
    parts = [f"({terms})", "lang:en", "-filter:retweets"]
    if start_date:
        parts.append(f"since:{start_date}")
    if end_date:
        parts.append(f"until:{end_date}")
    return " ".join(parts)


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
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        # OSError covers URLError, HTTPError, and socket timeouts.
        logger.warning("Twitter fetch failed for %r: %s", terms, exc)
        return f"<twitter unavailable: {type(exc).__name__}: {exc}>"

    tweets = data.get("tweets") if isinstance(data, dict) else None
    if not isinstance(tweets, list) or not tweets:
        return f"<no X/Twitter posts found for {terms}>"

    lines = []
    for tw in tweets[:limit]:
        if not isinstance(tw, dict):
            continue
        author = tw.get("author") or {}
        user = _first(author, _USER_ALIASES, "?") if isinstance(author, dict) else "?"
        body = str(_first(tw, _FIELD_ALIASES["text"])).replace("\n", " ").strip()
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
