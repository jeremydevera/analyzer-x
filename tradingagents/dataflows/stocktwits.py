"""StockTwits public symbol-stream fetcher.

StockTwits exposes a per-symbol message stream at
``api.stocktwits.com/api/2/streams/symbol/{ticker}.json`` that requires no
API key, no OAuth, and no registration. Each message includes a
user-labeled sentiment field (``Bullish``/``Bearish``/null), the message
body, timestamp, and posting user.

The function is deliberately self-contained: short timeout, graceful
degradation on any HTTP or parse failure, and a string return type so
the calling agent gets a uniform interface regardless of whether the
network call succeeded.
"""

from __future__ import annotations

import http.client
import json
import logging
from datetime import datetime, timezone
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_API = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
_UA = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"


DEFAULT_WINDOW_DAYS = 7


def _message_age_days(message: dict, now: datetime) -> int | None:
    """Whole days since a message was posted, or None if the stamp is unusable."""
    stamp = message.get("created_at")
    if not isinstance(stamp, str):
        return None
    try:
        posted = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None
    return (now - posted).days


def _within_window(messages: list, window_days: int | None):
    """Split messages by recency. Returns ``(kept, newest_age_in_days)``.

    A stream can be entirely historical: the ticker of a coin listed last week
    may have belonged to a different asset years ago, and StockTwits serves those
    old messages as the "most recent" ones. Ages come back with the result so the
    caller can say how stale the stream is instead of implying it is live.
    """
    now = datetime.now(timezone.utc)
    ages = [(m, _message_age_days(m, now)) for m in messages]
    dated = [(m, age) for m, age in ages if age is not None]
    newest_age = min((age for _, age in dated), default=None)
    if window_days is None:
        return [m for m, _ in dated], newest_age
    return [m for m, age in dated if age <= window_days], newest_age


def fetch_stocktwits_messages(ticker: str, limit: int = 30, timeout: float = 10.0,
                              window_days: int | None = DEFAULT_WINDOW_DAYS) -> str:
    """Fetch recent StockTwits messages for ``ticker`` and return them as a
    formatted plaintext block ready for prompt injection.

    Only messages posted within ``window_days`` are kept, because the endpoint
    returns the 30 most-recent messages regardless of age — for a newly listed
    coin that inherited its ticker from an older asset, those can be years old
    (AEON.X's newest is 878 days old). Pass ``window_days=None`` to keep them all.

    Returns a placeholder string when the endpoint is unreachable, the
    symbol has no messages, or the response shape is unexpected — the
    caller never has to special-case None or exceptions.
    """
    url = _API.format(ticker=ticker.upper())
    req = Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
        # OSError covers URLError/TimeoutError/connection resets; HTTPException
        # covers chunked-transfer errors (IncompleteRead/BadStatusLine, #1024).
        logger.warning("StockTwits fetch failed for %s: %s", ticker, exc)
        return f"<stocktwits unavailable: {type(exc).__name__}>"

    messages = data.get("messages", []) if isinstance(data, dict) else []
    if not messages:
        return f"<no StockTwits messages found for ${ticker.upper()}>"

    fresh, newest_age = _within_window(messages, window_days)
    if not fresh:
        detail = (f", newest was {newest_age} days old" if newest_age is not None
                  else "")
        return (f"<no StockTwits messages for ${ticker.upper()} in the last "
                f"{window_days} days: {len(messages)} older messages ignored"
                f"{detail}>")

    lines = []
    bullish = bearish = unlabeled = 0
    for m in fresh[:limit]:
        created = m.get("created_at", "")
        user = (m.get("user") or {}).get("username", "?")
        entities = m.get("entities") or {}
        sentiment_obj = entities.get("sentiment") or {}
        sentiment = sentiment_obj.get("basic") if isinstance(sentiment_obj, dict) else None
        body = (m.get("body") or "").replace("\n", " ").strip()
        if len(body) > 280:
            body = body[:280] + "…"

        if sentiment == "Bullish":
            bullish += 1
            tag = "Bullish"
        elif sentiment == "Bearish":
            bearish += 1
            tag = "Bearish"
        else:
            unlabeled += 1
            tag = "no-label"
        lines.append(f"[{created} · @{user} · {tag}] {body}")

    total = bullish + bearish + unlabeled
    bull_pct = round(100 * bullish / total) if total else 0
    bear_pct = round(100 * bearish / total) if total else 0
    window_note = (f" within the last {window_days} days"
                   if window_days is not None else "")
    age_note = f" · newest {newest_age}d old" if newest_age is not None else ""
    dropped = len(messages) - len(fresh)
    drop_note = f" · {dropped} older messages excluded" if dropped else ""
    summary = (
        f"Bullish: {bullish} ({bull_pct}%) · "
        f"Bearish: {bearish} ({bear_pct}%) · "
        f"Unlabeled: {unlabeled} · "
        f"Total: {total} messages{window_note}{age_note}{drop_note}"
    )
    return summary + "\n\n" + "\n".join(lines)
