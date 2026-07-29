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

import dataclasses
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pandas as pd

from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.symbol_utils import to_mexc_symbol

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
# 500 hourly candles ≈ 20.8 days, which is where hour-precise ages come from.
# Beyond that the daily probe supplies day precision, which is all an "older than
# three weeks" filter needs.
_HOURLY_PROBE_LIMIT = 500
_HOUR_MS = 3_600_000
# The sweep collects a superset; the UI filters an age range inside it. 60 days
# covers an 8-week maximum, and the monthly prefilter already admits ~2 months,
# so widening the window costs no extra requests.
WINDOW_DAYS = 60


def _now_ms() -> int:
    return int(time.time() * 1000)


def _ms_to_date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def age_hours(listed_at_ms: int, now_ms: int | None = None) -> float:
    """Hours between a listing instant and now. Never negative."""
    now = now_ms if now_ms is not None else _now_ms()
    return max(0.0, (now - listed_at_ms) / _HOUR_MS)


def _klines(symbol: str, interval: str, limit: int) -> list:
    rows = _get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    return rows if isinstance(rows, list) else []


def monthly_candle_count(symbol: str) -> int:
    """How many monthly candles MEXC has for ``symbol``, capped at the probe limit."""
    return len(_klines(symbol, "1M", _MONTHLY_PROBE_LIMIT))


def is_recent_listing_candidate(monthly_count: int) -> bool:
    """True when the monthly-candle count implies a listing inside the probe window."""
    return 0 < monthly_count < _MONTHLY_PROBE_LIMIT


def first_trade_ms(symbol: str) -> int | None:
    """First-trade instant in epoch ms, or None when it predates both probes.

    Tries hourly candles first so a coin listed this morning reports an age in
    hours rather than rounding to a whole day — an "under 24h old" filter is
    meaningless at day resolution. Falls back to daily candles (midnight
    precision) for coins older than the hourly window.
    """
    hourly = _klines(symbol, "60m", _HOURLY_PROBE_LIMIT)
    if hourly and len(hourly) < _HOURLY_PROBE_LIMIT:
        return hourly[0][0]

    daily = _klines(symbol, "1d", _DAILY_PROBE_LIMIT)
    if not daily or len(daily) >= _DAILY_PROBE_LIMIT:
        return None            # saturated history == older than the window
    return daily[0][0]


def first_trade_date(symbol: str) -> str | None:
    """Exact first-trade date (YYYY-MM-DD), or None when it is older than the probe."""
    ms = first_trade_ms(symbol)
    return _ms_to_date(ms) if ms is not None else None


def age_days(listed_date: str, today: str) -> int:
    """Whole days between a listing date and ``today``, both YYYY-MM-DD."""
    d0 = datetime.strptime(listed_date, "%Y-%m-%d")
    d1 = datetime.strptime(today, "%Y-%m-%d")
    return (d1 - d0).days


# Throttling. A measured 8-worker sweep sustained ~31 req/s and drew 429s on 6%
# of requests, so each worker pauses before its call to hold the aggregate near
# 16 req/s. A full ~1700-symbol sweep therefore takes ~2 minutes, which is why
# results are cached rather than re-swept on every tab render.
_MAX_WORKERS = 5
_THROTTLE_SLEEP = 0.3
_CACHE_TTL_SECONDS = 6 * 60 * 60
DEFAULT_MIN_QUOTE_VOLUME = 50_000.0


@dataclasses.dataclass(frozen=True)
class NewCoin:
    """One newly listed MEXC spot coin, as shown in a screener row.

    ``age_hours`` is computed when a sweep is read, not when it is written, so a
    cached sweep never reports a frozen age.
    """

    symbol: str          # MEXC pair, e.g. "CATEUSDT"
    base: str            # "CATE"
    name: str            # human name from exchangeInfo.fullName
    contract: str        # on-chain contract address, "" when MEXC has none
    listed_at_ms: int    # first-trade instant, epoch ms
    listed_date: str     # first-trade date, YYYY-MM-DD
    age_hours: float
    price: float
    change_pct: float    # 24h change in whole percent
    quote_volume: float  # 24h quote volume in USDT

    @property
    def age_days(self) -> int:
        """Whole days since listing, for compact display."""
        return int(self.age_hours // 24)


@dataclasses.dataclass(frozen=True)
class ScreenResult:
    """Outcome of one screener sweep, including what it could not resolve."""

    coins: list
    scanned: int              # symbols considered
    unresolved: int           # symbols whose age probe failed
    hidden_by_volume: int     # in-window coins below the volume floor
    hidden_by_age: int        # in-window coins outside the requested age range
    fetched_at: float         # epoch seconds of the underlying sweep
    from_cache: bool
    stale: bool = False       # served past its TTL because a refresh failed


def _today() -> str:
    """Today's UTC date, derived from the same clock as ages so tests stay coherent."""
    return _ms_to_date(_now_ms())


def _cache_dir() -> str:
    from tradingagents.dataflows.config import get_config
    return get_config()["data_cache_dir"]


def _cache_path() -> str:
    return os.path.join(_cache_dir(), f"mexc-new-listings-{WINDOW_DAYS}d.json")


def _read_cache() -> dict | None:
    try:
        with open(_cache_path(), encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and "coins" in payload else None


def _write_cache(payload: dict) -> None:
    try:
        os.makedirs(_cache_dir(), exist_ok=True)
        with open(_cache_path(), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except OSError as exc:
        logger.warning("Could not write MEXC screener cache: %s", exc)


def _throttled_age(symbol: str) -> tuple[str, int | None]:
    """Monthly-candle count for one symbol, with one Retry-After-aware retry."""
    time.sleep(_THROTTLE_SLEEP)
    try:
        return symbol, monthly_candle_count(symbol)
    except MexcRateLimited as exc:
        # ``or`` would swallow a legitimate "Retry-After: 0" and stall 2s for nothing.
        time.sleep(exc.retry_after if exc.retry_after is not None else 2.0)
        try:
            return symbol, monthly_candle_count(symbol)
        except (MexcRateLimited, MexcHostUnavailable) as retry_exc:
            logger.warning("MEXC age probe gave up on %s: %s", symbol, retry_exc)
            return symbol, None
    except MexcHostUnavailable as exc:
        logger.warning("MEXC age probe failed for %s: %s", symbol, exc)
        return symbol, None


def _sweep(today: str) -> tuple[list, int, int]:
    """Run the full three-stage sweep. Returns (in-window coins, scanned, unresolved)."""
    universe = fetch_usdt_symbols()
    tickers = fetch_24h_tickers()

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        counts = list(pool.map(_throttled_age, [row["symbol"] for row in universe]))

    unresolved = sum(1 for _, n in counts if n is None)
    candidates = {s for s, n in counts if n is not None and is_recent_listing_candidate(n)}

    now = _now_ms()
    records = []
    for row in universe:
        if row["symbol"] not in candidates:
            continue
        try:
            listed_at = first_trade_ms(row["symbol"])
        except (MexcRateLimited, MexcHostUnavailable) as exc:
            logger.warning("MEXC first-trade probe failed for %s: %s", row["symbol"], exc)
            unresolved += 1
            continue
        if listed_at is None:
            continue
        if age_hours(listed_at, now) > WINDOW_DAYS * 24:
            continue
        tick = tickers.get(row["symbol"], {})
        records.append({
            "symbol": row["symbol"], "base": row["base"], "name": row["name"],
            "contract": row["contract"], "listed_at_ms": listed_at,
            "listed_date": _ms_to_date(listed_at),
            "price": tick.get("price", 0.0),
            "change_pct": tick.get("change_pct", 0.0),
            "quote_volume": tick.get("quote_volume", 0.0),
        })

    records.sort(key=lambda r: (r["listed_at_ms"], r["quote_volume"]), reverse=True)
    return records, len(universe), unresolved


def _filtered(payload: dict, *, min_quote_volume: float, include_all: bool,
              from_cache: bool, stale: bool,
              min_age_hours: float = 0.0,
              max_age_hours: float | None = None) -> ScreenResult:
    """Apply the age range and volume floor to a sweep payload.

    Ages are derived here rather than read from the payload so a cached sweep
    reports how old each coin is *now*, not how old it was when swept. Both range
    bounds are inclusive.
    """
    now = _now_ms()
    ceiling = WINDOW_DAYS * 24 if max_age_hours is None else max_age_hours
    coins = [
        NewCoin(**record, age_hours=age_hours(record["listed_at_ms"], now))
        for record in payload["coins"]
    ]

    in_range = [c for c in coins if min_age_hours <= c.age_hours <= ceiling]
    kept = (in_range if include_all
            else [c for c in in_range if c.quote_volume >= min_quote_volume])
    return ScreenResult(
        coins=kept,
        scanned=payload.get("scanned", len(coins)),
        unresolved=payload.get("unresolved", 0),
        hidden_by_volume=len(in_range) - len(kept),
        hidden_by_age=len(coins) - len(in_range),
        fetched_at=payload.get("fetched_at", 0.0),
        from_cache=from_cache,
        stale=stale,
    )


def cached_listings(
    *,
    today: str | None = None,
    min_quote_volume: float = DEFAULT_MIN_QUOTE_VOLUME,
    include_all: bool = False,
    min_age_hours: float = 0.0,
    max_age_hours: float | None = None,
) -> ScreenResult | None:
    """Return a cached sweep without touching the network, or None if there is none.

    A UI needs this to stay responsive: Streamlit re-runs every tab body on every
    interaction, so a screen that swept on render would spend ~2 minutes of
    requests even for a user who never opened the tab. The tab shows cached rows
    instantly and leaves the sweep to an explicit button.
    """
    today = today or _today()
    cached = _read_cache()
    if cached is None:
        return None
    stale = (
        cached.get("today") != today
        or (_now_ms() / 1000 - cached.get("fetched_at", 0)) >= _CACHE_TTL_SECONDS
    )
    return _filtered(cached, min_quote_volume=min_quote_volume,
                     include_all=include_all, from_cache=True, stale=stale,
                     min_age_hours=min_age_hours, max_age_hours=max_age_hours)


def screen_new_listings(
    *,
    today: str | None = None,
    min_quote_volume: float = DEFAULT_MIN_QUOTE_VOLUME,
    include_all: bool = False,
    force_refresh: bool = False,
    min_age_hours: float = 0.0,
    max_age_hours: float | None = None,
) -> ScreenResult:
    """Coins first traded on MEXC within the last ``WINDOW_DAYS`` days.

    Results are cached for 6h because a full sweep costs ~1700 requests. When a
    forced refresh fails (blocked host, rate limits), a cached sweep is served
    and flagged stale rather than showing an empty table, which would read as
    "no new coins" instead of "could not check".
    """
    today = today or _today()
    cached = _read_cache()
    fresh_enough = (
        cached is not None
        and cached.get("today") == today
        and (_now_ms() / 1000 - cached.get("fetched_at", 0)) < _CACHE_TTL_SECONDS
    )

    if fresh_enough and not force_refresh:
        payload, from_cache, stale = cached, True, False
    else:
        try:
            records, scanned, unresolved = _sweep(today)
            payload = {
                "today": today, "fetched_at": _now_ms() / 1000, "scanned": scanned,
                "unresolved": unresolved, "coins": records,
            }
            _write_cache(payload)
            from_cache, stale = False, False
        except (MexcUnavailable, MexcHostUnavailable, MexcRateLimited):
            if cached is None:
                raise
            logger.warning("MEXC sweep failed; serving cached listings.")
            payload, from_cache, stale = cached, True, True

    return _filtered(payload, min_quote_volume=min_quote_volume,
                     include_all=include_all, from_cache=from_cache, stale=stale,
                     min_age_hours=min_age_hours, max_age_hours=max_age_hours)


_KLINE_COLUMNS = ["openTime", "Open", "High", "Low", "Close", "Volume",
                  "closeTime", "quoteVolume"]


def get_mexc_ohlcv(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Daily OHLCV for ``symbol`` as a Date/Open/High/Low/Close/Volume frame.

    Raises NoMarketDataError when MEXC has no candles in range, so the vendor
    router emits its single "unavailable" sentinel instead of letting an agent
    invent a price.
    """
    pair = to_mexc_symbol(symbol)
    rows = _klines(pair, "1d", _DAILY_PROBE_LIMIT)
    if not rows:
        raise NoMarketDataError(symbol, pair, "MEXC returned no candles")

    df = pd.DataFrame(rows, columns=_KLINE_COLUMNS)
    df["Date"] = pd.to_datetime(df["openTime"], unit="ms", utc=True).dt.tz_localize(None)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]].dropna()

    lo = pd.to_datetime(start_date)
    hi = pd.to_datetime(end_date) + pd.Timedelta(days=1)
    df = df[(df["Date"] >= lo) & (df["Date"] < hi)].reset_index(drop=True)
    if df.empty:
        raise NoMarketDataError(
            symbol, pair, f"no candles between {start_date} and {end_date}"
        )
    return df


def get_mexc_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """Vendor entry point for ``get_stock_data`` — annotated CSV, like yfinance's."""
    df = get_mexc_ohlcv(symbol, start_date, end_date)
    pair = to_mexc_symbol(symbol)
    label = pair if pair == symbol.upper() else f"{pair} (from {symbol})"
    out = df.copy()
    out["Date"] = out["Date"].dt.strftime("%Y-%m-%d")
    header = (
        f"# MEXC spot data for {label} from {start_date} to {end_date}\n"
        f"# Total records: {len(out)}\n"
        f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    return header + out.to_csv(index=False)


def get_mexc_indicators(
    symbol: str, indicator: str, curr_date: str, look_back_days: int
) -> str:
    """Vendor entry point for ``get_indicators``, computed off MEXC candles.

    Dates are captured before ``stockstats.wrap`` runs, because wrap normalises
    column names and the date column's identity is not guaranteed to survive.
    Zipping two positional lists keeps this correct either way.
    """
    from stockstats import wrap

    from tradingagents.dataflows.stockstats_utils import INDICATOR_DESCRIPTIONS

    if indicator not in INDICATOR_DESCRIPTIONS:
        raise ValueError(
            f"Indicator {indicator!r} is not supported. "
            f"Supported: {', '.join(sorted(INDICATOR_DESCRIPTIONS))}"
        )

    end = datetime.strptime(curr_date, "%Y-%m-%d")
    # 260 extra calendar days of warm-up so slow indicators (200 SMA) have input.
    start = end - timedelta(days=look_back_days + 260)
    df = get_mexc_ohlcv(symbol, start.strftime("%Y-%m-%d"), curr_date)

    dates = df["Date"].dt.strftime("%Y-%m-%d").tolist()
    values = wrap(df.copy())[indicator].tolist()

    window_start = (end - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
    lines = [
        f"{d}: {v}" for d, v in zip(dates, values) if window_start <= d <= curr_date
    ]
    if not lines:
        lines = [f"{curr_date}: N/A: no candles in the requested window"]

    return (
        f"## {indicator} values from {window_start} to {curr_date}:\n\n"
        + "\n".join(lines)
        + "\n\n"
        + INDICATOR_DESCRIPTIONS[indicator]
    )
