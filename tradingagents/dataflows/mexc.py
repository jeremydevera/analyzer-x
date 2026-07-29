"""MEXC spot-market data: keyless OHLCV/vendor functions plus a new-listing screener.

MEXC's public v3 API needs no key, but the primary host is not reachable
everywhere: some ISPs (observed: PLDT/Smart PH) intercept ``api.mexc.com`` and
serve a block page, which surfaces as a TLS verification failure rather than a
clean HTTP error. The mirrors ``api.mexc.fm`` and ``api.mexc.co`` serve the same
API over valid TLS, so the client probes hosts in order and caches the first one
that answers ``/api/v3/ping``.

Certificate verification is never disabled — a TLS failure is precisely how an
intercepted host announces itself, and turning verification off would make the
client parse a block page as market data.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEFAULT_HOSTS = ("api.mexc.fm", "api.mexc.co", "api.mexc.com")
_MEXC_DOMAINS = ("mexc.fm", "mexc.co", "mexc.com")
_UA = "tradingagents/0.3 (+https://github.com/TauricResearch/TradingAgents)"
_TIMEOUT = 15.0

_host_cache: str | None = None


class MexcHostUnavailable(RuntimeError):
    """One host could not serve the API (network error, TLS block, bad shape)."""


class MexcUnavailable(RuntimeError):
    """No candidate host could serve the API."""


class MexcRateLimited(RuntimeError):
    """MEXC returned HTTP 429. Carries the Retry-After header when present."""

    def __init__(self, retry_after: str | None = None):
        try:
            self.retry_after = float(retry_after) if retry_after else None
        except (TypeError, ValueError):
            self.retry_after = None
        super().__init__(f"MEXC rate limited (retry_after={self.retry_after})")


def reset_host_cache() -> None:
    """Forget the resolved host. Used by tests and by an explicit UI refresh."""
    global _host_cache
    _host_cache = None


def _candidate_hosts() -> tuple[str, ...]:
    override = os.getenv("MEXC_API_HOST", "").strip()
    return (override,) if override else DEFAULT_HOSTS


def _raw_get(host: str, path: str, params: dict | None = None, timeout: float | None = None):
    """GET one JSON document from ``host``. Raises MexcHostUnavailable on any failure."""
    qs = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"https://{host}{path}{qs}"
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or _TIMEOUT) as resp:
            final_host = urllib.parse.urlparse(resp.geturl()).hostname or ""
            # A redirect off the MEXC domain means an interception page, not data.
            if final_host != host and not final_host.endswith(_MEXC_DOMAINS):
                raise MexcHostUnavailable(f"{host} redirected to {final_host}")
            body = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise MexcRateLimited(exc.headers.get("Retry-After")) from exc
        raise MexcHostUnavailable(f"{host} HTTP {exc.code}") from exc
    except OSError as exc:
        # OSError covers URLError, timeouts, and ssl.SSLCertVerificationError.
        raise MexcHostUnavailable(f"{host}: {type(exc).__name__}: {exc}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise MexcHostUnavailable(f"{host}: non-JSON response") from exc


def resolve_host(force: bool = False) -> str:
    """Return a working MEXC API host, probing candidates in order."""
    global _host_cache
    if _host_cache and not force:
        return _host_cache

    failures = []
    for host in _candidate_hosts():
        try:
            _raw_get(host, "/api/v3/ping", timeout=8.0)
        except (MexcHostUnavailable, MexcRateLimited) as exc:
            logger.warning("MEXC host %s unavailable: %s", host, exc)
            failures.append(f"{host} ({exc})")
            continue
        _host_cache = host
        return host

    raise MexcUnavailable(
        "No reachable MEXC API host. Tried: "
        + "; ".join(failures)
        + ". If your network blocks MEXC, set MEXC_API_HOST to a reachable mirror."
    )


def _get(path: str, params: dict | None = None, timeout: float | None = None):
    """GET from the resolved host, re-resolving once if that host has gone bad."""
    host = resolve_host()
    try:
        return _raw_get(host, path, params, timeout)
    except MexcHostUnavailable:
        logger.warning("MEXC host %s failed mid-session; re-resolving.", host)
        reset_host_cache()
        return _raw_get(resolve_host(), path, params, timeout)


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def fetch_usdt_symbols() -> list[dict]:
    """Every spot-tradable USDT pair, with its display name and contract address."""
    data = _get("/api/v3/exchangeInfo")
    symbols = data.get("symbols", []) if isinstance(data, dict) else []
    out = []
    for s in symbols:
        if s.get("quoteAsset") != "USDT" or not s.get("isSpotTradingAllowed"):
            continue
        base = s.get("baseAsset", "")
        out.append({
            "symbol": s.get("symbol", ""),
            "base": base,
            "name": s.get("fullName") or base,
            "contract": s.get("contractAddress") or "",
        })
    return out


def fetch_24h_tickers() -> dict[str, dict]:
    """Price / 24h quote volume / 24h change for every symbol, in one request.

    ``priceChangePercent`` arrives as a fraction (0.0196 == +1.96%), so it is
    scaled to whole percent here — the table and the prompt both want percent.
    """
    rows = _get("/api/v3/ticker/24hr")
    snap: dict[str, dict] = {}
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not r.get("symbol"):
            continue
        snap[r["symbol"]] = {
            "price": _as_float(r.get("lastPrice")),
            "quote_volume": _as_float(r.get("quoteVolume")),
            "change_pct": _as_float(r.get("priceChangePercent")) * 100.0,
        }
    return snap


# The age prefilter. MEXC ignores ``startTime=0`` and always serves the most
# recent candles, so listing age is inferred from how many candles come back for
# a bounded request: a coin with fewer than 3 monthly candles first traded within
# roughly two months and is worth an exact-date lookup.
_MONTHLY_PROBE_LIMIT = 3
_DAILY_PROBE_LIMIT = 500
WINDOW_DAYS = 30


def _ms_to_date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _klines(symbol: str, interval: str, limit: int) -> list:
    rows = _get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    return rows if isinstance(rows, list) else []


def monthly_candle_count(symbol: str) -> int:
    """How many monthly candles MEXC has for ``symbol``, capped at the probe limit."""
    return len(_klines(symbol, "1M", _MONTHLY_PROBE_LIMIT))


def is_recent_listing_candidate(monthly_count: int) -> bool:
    """True when the monthly-candle count implies a listing inside the probe window."""
    return 0 < monthly_count < _MONTHLY_PROBE_LIMIT


def first_trade_date(symbol: str) -> str | None:
    """Exact first-trade date (YYYY-MM-DD), or None when it is older than the probe."""
    rows = _klines(symbol, "1d", _DAILY_PROBE_LIMIT)
    if not rows or len(rows) >= _DAILY_PROBE_LIMIT:
        return None            # saturated history == older than the window
    return _ms_to_date(rows[0][0])


def age_days(listed_date: str, today: str) -> int:
    """Whole days between a listing date and ``today``, both YYYY-MM-DD."""
    d0 = datetime.strptime(listed_date, "%Y-%m-%d")
    d1 = datetime.strptime(today, "%Y-%m-%d")
    return (d1 - d0).days
