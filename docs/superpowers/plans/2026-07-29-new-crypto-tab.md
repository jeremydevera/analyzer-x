# New Crypto Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "New Crypto" tab to the Streamlit UI that tables MEXC spot coins first traded within the last 30 days and, per row, runs the multi-agent pipeline over Twitter/Reddit/news to return BUY / SELL / HOLD.

**Architecture:** Two new keyless-or-keyed dataflow modules (`mexc.py`, `twitter.py`) following the existing fetcher contract — return a string or typed error, never raise into the agent. MEXC registers as a first-class vendor for `get_stock_data` / `get_indicators` in the existing `VENDOR_METHODS` registry, so the market analyst's tools work unchanged for coins Yahoo has never heard of. Twitter becomes a config-gated fourth block in the shared sentiment analyst. The tab UI lives in a new `crypto_screener.py`; `app.py` only gains a two-tab shell.

**Tech Stack:** Python 3.12, Streamlit 1.58, LangGraph, pandas, stockstats, pytest (markers: `unit`, `integration`, `smoke`), stdlib `urllib` for HTTP (matching `reddit.py` / `stocktwits.py`).

**Environment note:** Run everything with the project venv — `.venv/bin/python`, `.venv/bin/pytest`. The system Python is 3.9 and will fail on `X | None` syntax.

---

## Verified facts this plan depends on

These were confirmed by live probing on 2026-07-29. Do not re-litigate them; do re-verify if a task fails.

1. `api.mexc.com` is ISP-blocked on this network — TLS verification fails because the block page is MITM'd. `api.mexc.fm` and `api.mexc.co` serve the real v3 API over **valid** TLS. Never disable certificate verification; a TLS failure is the signal that a host is blocked.
2. `GET /api/v3/exchangeInfo` → 2126 symbols, 1741 with `quoteAsset == "USDT"`. Per-symbol fields include `symbol`, `baseAsset`, `quoteAsset`, `fullName`, `contractAddress`, `isSpotTradingAllowed`, `status` (always `"1"`).
3. `GET /api/v3/ticker/24hr` → one array of 2126 objects with `lastPrice`, `quoteVolume`, `priceChangePercent`. **`priceChangePercent` is a fraction**: BTCUSDT returned `0.0196` for +1.96%. Multiply by 100.
4. `GET /api/v3/klines` rows are 8-element arrays: `[openTime, open, high, low, close, volume, closeTime, quoteVolume]`.
5. `startTime=0` is **ignored** — MEXC returns the most recent candles. Listing age must come from row counts of a bounded request: `interval=1M&limit=3` returns 3 rows for an old coin, 1–2 rows for a coin listed within ~2 months. `interval=1d&limit=500` then gives the exact first-trade date for survivors.
6. Rate limit: 8 concurrent workers sustained ~31 req/s and produced 12 HTTP 429s out of 200 requests. Stay near 15–16 req/s.
7. yfinance returns **zero rows** for `CATE-USD` and `CUPSEY-USD`, which is why the MEXC vendor is required.

---

## File Structure

**Create:**
- `tradingagents/dataflows/mexc.py` — MEXC HTTP client, host fallback, new-listing screener, and the two vendor functions. One responsibility: everything MEXC-shaped.
- `tradingagents/dataflows/twitter.py` — twitterapi.io adapter producing a prompt-ready block.
- `crypto_screener.py` — the New Crypto tab: table rendering, filters, per-row analyze runner. Kept out of `app.py`, which is already 879 lines.
- `tests/test_mexc_dataflow.py`, `tests/test_twitter_dataflow.py`, `tests/test_crypto_screener.py`, `tests/fixtures/twitterapi_search.json`

**Modify:**
- `tradingagents/dataflows/symbol_utils.py` — add `to_mexc_symbol` / `from_mexc_symbol`
- `tradingagents/dataflows/stockstats_utils.py` — hoist indicator descriptions to a module constant so two vendors can share them
- `tradingagents/dataflows/y_finance.py` — consume that constant instead of its local dict
- `tradingagents/dataflows/interface.py` — register the `mexc` vendor
- `tradingagents/default_config.py` — document the `mexc` option, add `include_twitter`
- `tradingagents/agents/analysts/sentiment_analyst.py` — gated Twitter block
- `app.py` — extract the existing screen into `render_run_analysis_tab()`, add the tab shell

---

## Task 1: MEXC host resolution

**Files:**
- Create: `tradingagents/dataflows/mexc.py`
- Test: `tests/test_mexc_dataflow.py`

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for the MEXC dataflow (no network — every HTTP call is patched)."""

import json
import ssl
from unittest.mock import patch

import pytest

from tradingagents.dataflows import mexc

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_host_cache():
    mexc.reset_host_cache()
    yield
    mexc.reset_host_cache()


def test_resolve_host_prefers_first_reachable():
    with patch.object(mexc, "_raw_get", return_value={}) as raw:
        assert mexc.resolve_host() == "api.mexc.fm"
    assert raw.call_count == 1


def test_resolve_host_falls_through_tls_block_to_next_host():
    """A blocked host fails TLS verification; the next candidate must be tried."""
    def fake(host, path, params=None, timeout=None):
        if host == "api.mexc.fm":
            raise mexc.MexcHostUnavailable("TLS: CERTIFICATE_VERIFY_FAILED")
        return {}

    with patch.object(mexc, "_raw_get", side_effect=fake):
        assert mexc.resolve_host() == "api.mexc.co"


def test_resolve_host_raises_when_all_hosts_blocked():
    with patch.object(mexc, "_raw_get", side_effect=mexc.MexcHostUnavailable("blocked")):
        with pytest.raises(mexc.MexcUnavailable) as exc:
            mexc.resolve_host()
    assert "MEXC_API_HOST" in str(exc.value)


def test_env_override_is_the_only_candidate(monkeypatch):
    monkeypatch.setenv("MEXC_API_HOST", "mexc.internal")
    with patch.object(mexc, "_raw_get", return_value={}) as raw:
        assert mexc.resolve_host() == "mexc.internal"
    assert raw.call_args[0][0] == "mexc.internal"


def test_resolved_host_is_cached_across_calls():
    with patch.object(mexc, "_raw_get", return_value={}) as raw:
        mexc.resolve_host()
        mexc.resolve_host()
    assert raw.call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tradingagents.dataflows.mexc'`

- [ ] **Step 3: Write minimal implementation**

Create `tradingagents/dataflows/mexc.py`:

```python
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

logger = logging.getLogger(__name__)

DEFAULT_HOSTS = ("api.mexc.fm", "api.mexc.co", "api.mexc.com")
_UA = "tradingagents/0.3 (+https://github.com/TauricResearch/TradingAgents)"
_TIMEOUT = 15.0

_host_cache: str | None = None


class MexcHostUnavailable(RuntimeError):
    """One host could not serve the API (network error, TLS block, bad shape)."""


class MexcUnavailable(RuntimeError):
    """No candidate host could serve the API."""


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
            if not final_host.endswith(("mexc.fm", "mexc.co", "mexc.com")) and final_host != host:
                raise MexcHostUnavailable(f"{host} redirected to {final_host}")
            body = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise MexcRateLimited(exc.headers.get("Retry-After")) from exc
        raise MexcHostUnavailable(f"{host} HTTP {exc.code}") from exc
    except (OSError, urllib.error.URLError) as exc:
        # OSError covers URLError, timeouts, and ssl.SSLCertVerificationError.
        raise MexcHostUnavailable(f"{host}: {type(exc).__name__}: {exc}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise MexcHostUnavailable(f"{host}: non-JSON response") from exc


class MexcRateLimited(RuntimeError):
    """MEXC returned HTTP 429. Carries the Retry-After header when present."""

    def __init__(self, retry_after: str | None = None):
        self.retry_after = float(retry_after) if retry_after else None
        super().__init__(f"MEXC rate limited (retry_after={self.retry_after})")


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
```

Note: `MexcRateLimited` is referenced inside `_raw_get` before its `class` statement executes at import time, which is fine because the name is only looked up when the function runs. Keep the definition order as written, or move the class above `_raw_get` if you prefer.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/mexc.py tests/test_mexc_dataflow.py
git commit -m "feat(mexc): add host-fallback JSON client for the MEXC v3 API"
```

---

## Task 2: Symbol mapping between the app's convention and MEXC pairs

**Files:**
- Modify: `tradingagents/dataflows/symbol_utils.py`
- Test: `tests/test_mexc_dataflow.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mexc_dataflow.py`:

```python
from tradingagents.dataflows.symbol_utils import from_mexc_symbol, to_mexc_symbol


@pytest.mark.parametrize("raw,expected", [
    ("CATE-USD", "CATEUSDT"),
    ("CATE-USDT", "CATEUSDT"),
    ("CATEUSDT", "CATEUSDT"),
    ("cate-usd", "CATEUSDT"),
    ("CATE", "CATEUSDT"),
    ("CATE-USDC", "CATEUSDC"),
])
def test_to_mexc_symbol(raw, expected):
    assert to_mexc_symbol(raw) == expected


@pytest.mark.parametrize("pair,expected", [
    ("CATEUSDT", "CATE-USD"),
    ("BTCUSDT", "BTC-USD"),
    ("WEIRD", "WEIRD"),
])
def test_from_mexc_symbol(pair, expected):
    assert from_mexc_symbol(pair) == expected


def test_mexc_symbol_round_trip():
    assert to_mexc_symbol(from_mexc_symbol("CATEUSDT")) == "CATEUSDT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -k mexc_symbol -v`
Expected: FAIL — `ImportError: cannot import name 'to_mexc_symbol'`

- [ ] **Step 3: Write minimal implementation**

Append to `tradingagents/dataflows/symbol_utils.py`:

```python
# MEXC spot pairs are unseparated and quoted in a stablecoin (``CATEUSDT``),
# while the rest of the app uses Yahoo's dash form (``CATE-USD``). USD has no
# MEXC market, so it maps to USDT — the deepest quote book on the exchange.
_MEXC_QUOTES = ("USDT", "USDC")


def to_mexc_symbol(symbol: str) -> str:
    """Convert an app-style symbol to a MEXC spot pair (``CATE-USD`` -> ``CATEUSDT``)."""
    s = symbol.strip().upper().replace("_", "-")
    if "-" in s:
        base, _, quote = s.partition("-")
    else:
        for q in _MEXC_QUOTES:
            if s.endswith(q) and len(s) > len(q):
                return s
        base, quote = s, "USDT"
    if quote not in _MEXC_QUOTES:
        quote = "USDT"          # USD / blank / anything exotic -> the USDT book
    return f"{base}{quote}"


def from_mexc_symbol(pair: str) -> str:
    """Convert a MEXC spot pair back to the app's dash form (``CATEUSDT`` -> ``CATE-USD``)."""
    p = pair.strip().upper()
    for q in _MEXC_QUOTES:
        if p.endswith(q) and len(p) > len(q):
            return f"{p[: -len(q)]}-USD"
    return p
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -k mexc_symbol -v`
Expected: PASS — 10 passed

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/symbol_utils.py tests/test_mexc_dataflow.py
git commit -m "feat(mexc): map app symbols to MEXC spot pairs"
```

---

## Task 3: Symbol universe and 24h ticker snapshot

**Files:**
- Modify: `tradingagents/dataflows/mexc.py`
- Test: `tests/test_mexc_dataflow.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mexc_dataflow.py`:

```python
_EXCHANGE_INFO = {
    "symbols": [
        {"symbol": "CATEUSDT", "baseAsset": "CATE", "quoteAsset": "USDT",
         "isSpotTradingAllowed": True, "fullName": "Catestein",
         "contractAddress": "0xabc"},
        {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT",
         "isSpotTradingAllowed": True, "fullName": "Bitcoin", "contractAddress": ""},
        {"symbol": "ETHBTC", "baseAsset": "ETH", "quoteAsset": "BTC",
         "isSpotTradingAllowed": True, "fullName": "Ethereum", "contractAddress": ""},
        {"symbol": "HALTEDUSDT", "baseAsset": "HALTED", "quoteAsset": "USDT",
         "isSpotTradingAllowed": False, "fullName": "Halted", "contractAddress": ""},
    ]
}

_TICKER_24H = [
    {"symbol": "CATEUSDT", "lastPrice": "0.003782",
     "quoteVolume": "140981.74", "priceChangePercent": "-0.2379"},
    {"symbol": "BTCUSDT", "lastPrice": "64666.01",
     "quoteVolume": "409920994.69", "priceChangePercent": "0.0196"},
]


def test_fetch_usdt_symbols_keeps_only_tradable_usdt_pairs():
    with patch.object(mexc, "_get", return_value=_EXCHANGE_INFO):
        rows = mexc.fetch_usdt_symbols()
    assert [r["symbol"] for r in rows] == ["CATEUSDT", "BTCUSDT"]
    assert rows[0] == {"symbol": "CATEUSDT", "base": "CATE",
                       "name": "Catestein", "contract": "0xabc"}


def test_fetch_24h_tickers_converts_fraction_to_percent():
    """MEXC reports priceChangePercent as a fraction: 0.0196 means +1.96%."""
    with patch.object(mexc, "_get", return_value=_TICKER_24H):
        snap = mexc.fetch_24h_tickers()
    assert snap["BTCUSDT"]["change_pct"] == pytest.approx(1.96)
    assert snap["CATEUSDT"]["change_pct"] == pytest.approx(-23.79)
    assert snap["CATEUSDT"]["quote_volume"] == pytest.approx(140981.74)
    assert snap["CATEUSDT"]["price"] == pytest.approx(0.003782)


def test_fetch_24h_tickers_tolerates_missing_fields():
    with patch.object(mexc, "_get", return_value=[{"symbol": "XUSDT"}]):
        snap = mexc.fetch_24h_tickers()
    assert snap["XUSDT"] == {"price": 0.0, "quote_volume": 0.0, "change_pct": 0.0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -k "usdt_symbols or 24h_tickers" -v`
Expected: FAIL — `AttributeError: module 'tradingagents.dataflows.mexc' has no attribute '_get'`

- [ ] **Step 3: Write minimal implementation**

Append to `tradingagents/dataflows/mexc.py`:

```python
def _get(path: str, params: dict | None = None, timeout: float | None = None):
    """GET from the resolved host, re-resolving once if that host has gone bad."""
    host = resolve_host()
    try:
        return _raw_get(host, path, params, timeout)
    except MexcHostUnavailable:
        logger.warning("MEXC host %s failed mid-session; re-resolving.", host)
        reset_host_cache()
        return _raw_get(resolve_host(), path, params, timeout)


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


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def fetch_24h_tickers() -> dict[str, dict]:
    """Price / 24h quote volume / 24h change for every symbol, in one request.

    ``priceChangePercent`` arrives as a fraction (0.0196 == +1.96%), so it is
    scaled to whole percent here — the UI and the prompt both want percent.
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -k "usdt_symbols or 24h_tickers" -v`
Expected: PASS — 3 passed

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/mexc.py tests/test_mexc_dataflow.py
git commit -m "feat(mexc): fetch the USDT symbol universe and 24h ticker snapshot"
```

---

## Task 4: Listing-age detection

**Files:**
- Modify: `tradingagents/dataflows/mexc.py`
- Test: `tests/test_mexc_dataflow.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mexc_dataflow.py`:

```python
def _kline(open_ms):
    """One MEXC kline row: [openTime, o, h, l, c, vol, closeTime, quoteVol]."""
    return [open_ms, "1.0", "2.0", "0.5", "1.5", "100.0", open_ms + 86_400_000, "150.0"]


def test_monthly_candle_count_reports_row_count():
    with patch.object(mexc, "_get", return_value=[_kline(1), _kline(2)]):
        assert mexc.monthly_candle_count("CATEUSDT") == 2


def test_is_recent_listing_accepts_fewer_than_three_monthly_candles():
    assert mexc.is_recent_listing_candidate(1) is True
    assert mexc.is_recent_listing_candidate(2) is True
    assert mexc.is_recent_listing_candidate(3) is False


def test_first_trade_date_uses_the_earliest_daily_candle():
    # 2026-07-12T00:00:00Z
    with patch.object(mexc, "_get", return_value=[_kline(1783036800000), _kline(1783123200000)]):
        assert mexc.first_trade_date("CATEUSDT") == "2026-07-12"


def test_first_trade_date_returns_none_when_history_is_saturated():
    """500 daily rows means the true first trade is older than the window."""
    rows = [_kline(1783036800000 + i * 86_400_000) for i in range(500)]
    with patch.object(mexc, "_get", return_value=rows):
        assert mexc.first_trade_date("BTCUSDT") is None


def test_first_trade_date_returns_none_when_no_candles():
    with patch.object(mexc, "_get", return_value=[]):
        assert mexc.first_trade_date("GHOSTUSDT") is None


@pytest.mark.parametrize("listed,today,expected_age,within", [
    ("2026-07-29", "2026-07-29", 0, True),
    ("2026-06-29", "2026-07-29", 30, True),    # exactly 30 days -> inside
    ("2026-06-28", "2026-07-29", 31, False),   # 31 days -> outside
])
def test_age_days_and_window_boundary(listed, today, expected_age, within):
    age = mexc.age_days(listed, today)
    assert age == expected_age
    assert (age <= 30) is within
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -k "candle or first_trade or age_days" -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'monthly_candle_count'`

- [ ] **Step 3: Write minimal implementation**

Add to `tradingagents/dataflows/mexc.py` (imports first: `from datetime import datetime, timezone`):

```python
# The age prefilter. MEXC ignores ``startTime=0`` and always serves the most
# recent candles, so listing age is inferred from how many candles come back
# for a bounded request: a coin with fewer than 3 monthly candles first traded
# within roughly two months and is worth an exact-date lookup.
_MONTHLY_PROBE_LIMIT = 3
_DAILY_PROBE_LIMIT = 500


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -k "candle or first_trade or age_days" -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/mexc.py tests/test_mexc_dataflow.py
git commit -m "feat(mexc): derive listing age from bounded kline probes"
```

---

## Task 5: The screener — sweep, throttle, filter, cache

**Files:**
- Modify: `tradingagents/dataflows/mexc.py`
- Test: `tests/test_mexc_dataflow.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mexc_dataflow.py`:

```python
import time


def _screen_patches(monkeypatch, tmp_path, *, ages, first_dates):
    """Patch the three network stages of the sweep and point the cache at tmp_path."""
    monkeypatch.setattr(mexc, "fetch_usdt_symbols", lambda: [
        {"symbol": s, "base": s[:-4], "name": f"{s[:-4]} Coin", "contract": ""}
        for s in ages
    ])
    monkeypatch.setattr(mexc, "fetch_24h_tickers", lambda: {
        "NEWUSDT": {"price": 1.0, "quote_volume": 200_000.0, "change_pct": 12.0},
        "DUSTUSDT": {"price": 0.1, "quote_volume": 1_000.0, "change_pct": 5.0},
        "OLDUSDT": {"price": 9.0, "quote_volume": 900_000.0, "change_pct": 1.0},
    })
    monkeypatch.setattr(mexc, "monthly_candle_count", lambda s: ages[s])
    monkeypatch.setattr(mexc, "first_trade_date", lambda s: first_dates.get(s))
    monkeypatch.setattr(mexc, "_cache_dir", lambda: str(tmp_path))


def test_screen_returns_only_recent_liquid_coins(monkeypatch, tmp_path):
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
        first_dates={"NEWUSDT": "2026-07-20", "DUSTUSDT": "2026-07-21"},
    )
    result = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=50_000.0)

    assert [c.symbol for c in result.coins] == ["NEWUSDT"]
    coin = result.coins[0]
    assert coin.listed_date == "2026-07-20"
    assert coin.age_days == 9
    assert coin.quote_volume == pytest.approx(200_000.0)
    assert coin.change_pct == pytest.approx(12.0)
    assert result.scanned == 3
    assert result.hidden_by_volume == 1


def test_screen_include_all_keeps_dust(monkeypatch, tmp_path):
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
        first_dates={"NEWUSDT": "2026-07-20", "DUSTUSDT": "2026-07-21"},
    )
    result = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=50_000.0,
                                      include_all=True)
    assert {c.symbol for c in result.coins} == {"NEWUSDT", "DUSTUSDT"}


def test_screen_sorts_newest_first(monkeypatch, tmp_path):
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
        first_dates={"NEWUSDT": "2026-07-10", "DUSTUSDT": "2026-07-25"},
    )
    result = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0)
    assert [c.symbol for c in result.coins] == ["DUSTUSDT", "NEWUSDT"]


def test_screen_excludes_coins_outside_the_window(monkeypatch, tmp_path):
    _screen_patches(
        monkeypatch, tmp_path,
        ages={"NEWUSDT": 2, "DUSTUSDT": 1, "OLDUSDT": 3},
        first_dates={"NEWUSDT": "2026-05-01", "DUSTUSDT": "2026-07-25"},
    )
    result = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0)
    assert [c.symbol for c in result.coins] == ["DUSTUSDT"]


def test_screen_counts_unresolved_symbols(monkeypatch, tmp_path):
    """A symbol whose probe keeps failing is reported, never silently dropped."""
    def boom(symbol):
        if symbol == "DUSTUSDT":
            raise mexc.MexcRateLimited("1")
        return {"NEWUSDT": 1, "OLDUSDT": 3}[symbol]

    _screen_patches(monkeypatch, tmp_path,
                    ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
                    first_dates={"NEWUSDT": "2026-07-20"})
    monkeypatch.setattr(mexc, "monthly_candle_count", boom)

    result = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0)
    assert result.unresolved == 1
    assert [c.symbol for c in result.coins] == ["NEWUSDT"]


def test_screen_reads_fresh_cache_without_network(monkeypatch, tmp_path):
    _screen_patches(monkeypatch, tmp_path,
                    ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
                    first_dates={"NEWUSDT": "2026-07-20", "DUSTUSDT": "2026-07-21"})
    first = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0)
    assert first.from_cache is False

    def explode():
        raise AssertionError("cache hit must not hit the network")

    monkeypatch.setattr(mexc, "fetch_usdt_symbols", explode)
    second = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0)
    assert second.from_cache is True
    assert [c.symbol for c in second.coins] == [c.symbol for c in first.coins]


def test_screen_force_refresh_bypasses_cache(monkeypatch, tmp_path):
    _screen_patches(monkeypatch, tmp_path,
                    ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
                    first_dates={"NEWUSDT": "2026-07-20", "DUSTUSDT": "2026-07-21"})
    mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0)
    result = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0,
                                      force_refresh=True)
    assert result.from_cache is False


def test_screen_serves_expired_cache_when_refresh_fails(monkeypatch, tmp_path):
    _screen_patches(monkeypatch, tmp_path,
                    ages={"NEWUSDT": 1, "DUSTUSDT": 1, "OLDUSDT": 3},
                    first_dates={"NEWUSDT": "2026-07-20", "DUSTUSDT": "2026-07-21"})
    mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0)

    def dead():
        raise mexc.MexcUnavailable("all hosts blocked")

    monkeypatch.setattr(mexc, "fetch_usdt_symbols", dead)
    result = mexc.screen_new_listings(today="2026-07-29", min_quote_volume=0.0,
                                      force_refresh=True)
    assert result.from_cache is True
    assert result.stale is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -k screen -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'screen_new_listings'`

- [ ] **Step 3: Write minimal implementation**

Add to `tradingagents/dataflows/mexc.py` (add imports `os`, `time`, `dataclasses`, `ThreadPoolExecutor`):

```python
# Throttling. A measured 8-worker sweep sustained ~31 req/s and drew 429s on
# 6% of requests, so each worker pauses before its call to hold the aggregate
# near 16 req/s. A full 1741-symbol sweep therefore takes ~2 minutes, which is
# why results are cached rather than re-swept on every tab render.
_MAX_WORKERS = 5
_THROTTLE_SLEEP = 0.3
_CACHE_TTL_SECONDS = 6 * 60 * 60
WINDOW_DAYS = 30
DEFAULT_MIN_QUOTE_VOLUME = 50_000.0


@dataclasses.dataclass(frozen=True)
class NewCoin:
    """One newly listed MEXC spot coin, as shown in a screener row."""

    symbol: str          # MEXC pair, e.g. "CATEUSDT"
    base: str            # "CATE"
    name: str            # human name from exchangeInfo.fullName
    contract: str        # on-chain contract address, "" when MEXC has none
    listed_date: str     # first-trade date, YYYY-MM-DD
    age_days: int
    price: float
    change_pct: float    # 24h change in whole percent
    quote_volume: float  # 24h quote volume in USDT


@dataclasses.dataclass(frozen=True)
class ScreenResult:
    """Outcome of one screener sweep, including what it could not resolve."""

    coins: list
    scanned: int              # symbols considered
    unresolved: int           # symbols whose age probe failed
    hidden_by_volume: int     # in-window coins below the volume floor
    fetched_at: float         # epoch seconds of the underlying sweep
    from_cache: bool
    stale: bool = False       # served past its TTL because a refresh failed


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
    os.makedirs(_cache_dir(), exist_ok=True)
    try:
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
        time.sleep(exc.retry_after or 2.0)
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

    coins = []
    for row in universe:
        if row["symbol"] not in candidates:
            continue
        try:
            listed = first_trade_date(row["symbol"])
        except (MexcRateLimited, MexcHostUnavailable) as exc:
            logger.warning("MEXC first-trade probe failed for %s: %s", row["symbol"], exc)
            unresolved += 1
            continue
        if not listed:
            continue
        age = age_days(listed, today)
        if age > WINDOW_DAYS or age < 0:
            continue
        tick = tickers.get(row["symbol"], {})
        coins.append(NewCoin(
            symbol=row["symbol"], base=row["base"], name=row["name"],
            contract=row["contract"], listed_date=listed, age_days=age,
            price=tick.get("price", 0.0), change_pct=tick.get("change_pct", 0.0),
            quote_volume=tick.get("quote_volume", 0.0),
        ))

    coins.sort(key=lambda c: (c.listed_date, c.quote_volume), reverse=True)
    return coins, len(universe), unresolved


def screen_new_listings(
    *,
    today: str | None = None,
    min_quote_volume: float = DEFAULT_MIN_QUOTE_VOLUME,
    include_all: bool = False,
    force_refresh: bool = False,
) -> ScreenResult:
    """Coins first traded on MEXC within the last ``WINDOW_DAYS`` days.

    Results are cached for 6h because a full sweep costs ~1700 requests. When a
    forced refresh fails (blocked host, rate limits), a cached sweep is served
    and flagged stale rather than showing an empty table, which would read as
    "no new coins" instead of "could not check".
    """
    today = today or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    cached = _read_cache()
    fresh_enough = (
        cached is not None
        and cached.get("today") == today
        and (time.time() - cached.get("fetched_at", 0)) < _CACHE_TTL_SECONDS
    )

    if fresh_enough and not force_refresh:
        payload, from_cache, stale = cached, True, False
    else:
        try:
            coins, scanned, unresolved = _sweep(today)
            payload = {
                "today": today, "fetched_at": time.time(), "scanned": scanned,
                "unresolved": unresolved,
                "coins": [dataclasses.asdict(c) for c in coins],
            }
            _write_cache(payload)
            from_cache, stale = False, False
        except (MexcUnavailable, MexcHostUnavailable, MexcRateLimited):
            if cached is None:
                raise
            logger.warning("MEXC sweep failed; serving cached listings.")
            payload, from_cache, stale = cached, True, True

    coins = [NewCoin(**c) for c in payload["coins"]]
    kept = coins if include_all else [c for c in coins if c.quote_volume >= min_quote_volume]
    return ScreenResult(
        coins=kept,
        scanned=payload.get("scanned", len(coins)),
        unresolved=payload.get("unresolved", 0),
        hidden_by_volume=len(coins) - len(kept),
        fetched_at=payload.get("fetched_at", 0.0),
        from_cache=from_cache,
        stale=stale,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -k screen -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/mexc.py tests/test_mexc_dataflow.py
git commit -m "feat(mexc): screen new USDT listings with throttling and a 6h cache"
```

---

## Task 6: OHLCV frame and the `get_stock_data` vendor function

**Files:**
- Modify: `tradingagents/dataflows/mexc.py`
- Test: `tests/test_mexc_dataflow.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mexc_dataflow.py`:

```python
from tradingagents.dataflows.errors import NoMarketDataError

_DAILY = [
    # 2026-07-20 .. 2026-07-22
    [1783641600000, "0.0015", "0.0160", "0.0015", "0.0044", "45918439.28", 1783728000000, "269034.26"],
    [1783728000000, "0.0044", "0.0068", "0.0027", "0.0033", "38783978.54", 1783814400000, "160393.56"],
    [1783814400000, "0.0033", "0.0046", "0.0032", "0.0040", "11649426.35", 1783900800000, "45362.14"],
]


def test_get_mexc_ohlcv_builds_a_typed_frame():
    with patch.object(mexc, "_klines", return_value=_DAILY):
        df = mexc.get_mexc_ohlcv("CATE-USD", "2026-07-20", "2026-07-22")
    assert list(df.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 3
    assert df["Close"].iloc[-1] == pytest.approx(0.0040)
    assert str(df["Date"].iloc[0].date()) == "2026-07-20"


def test_get_mexc_ohlcv_filters_to_the_requested_range():
    with patch.object(mexc, "_klines", return_value=_DAILY):
        df = mexc.get_mexc_ohlcv("CATE-USD", "2026-07-21", "2026-07-21")
    assert len(df) == 1
    assert str(df["Date"].iloc[0].date()) == "2026-07-21"


def test_get_mexc_ohlcv_raises_no_market_data_when_empty():
    with patch.object(mexc, "_klines", return_value=[]):
        with pytest.raises(NoMarketDataError) as exc:
            mexc.get_mexc_ohlcv("GHOST-USD", "2026-07-01", "2026-07-29")
    assert exc.value.canonical == "GHOSTUSDT"


def test_get_mexc_ohlcv_raises_when_range_excludes_all_rows():
    with patch.object(mexc, "_klines", return_value=_DAILY):
        with pytest.raises(NoMarketDataError):
            mexc.get_mexc_ohlcv("CATE-USD", "2026-01-01", "2026-01-31")


def test_get_mexc_stock_data_returns_annotated_csv():
    with patch.object(mexc, "_klines", return_value=_DAILY):
        out = mexc.get_mexc_stock_data("CATE-USD", "2026-07-20", "2026-07-22")
    lines = out.splitlines()
    assert lines[0].startswith("# MEXC spot data for CATEUSDT (from CATE-USD)")
    assert "# Total records: 3" in out
    header = next(ln for ln in lines if ln.startswith("Date,"))
    assert header == "Date,Open,High,Low,Close,Volume"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -k ohlcv -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'get_mexc_ohlcv'`

- [ ] **Step 3: Write minimal implementation**

Add to `tradingagents/dataflows/mexc.py` (add `import pandas as pd` and
`from tradingagents.dataflows.errors import NoMarketDataError`,
`from tradingagents.dataflows.symbol_utils import to_mexc_symbol`):

```python
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
    """Vendor entry point for ``get_stock_data`` — annotated CSV, same shape as yfinance's."""
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -k ohlcv -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/mexc.py tests/test_mexc_dataflow.py
git commit -m "feat(mexc): serve OHLCV CSV as a get_stock_data vendor"
```

---

## Task 7: Shared indicator descriptions, then MEXC indicators

**Files:**
- Modify: `tradingagents/dataflows/stockstats_utils.py`, `tradingagents/dataflows/y_finance.py`, `tradingagents/dataflows/mexc.py`
- Test: `tests/test_mexc_dataflow.py`

The indicator description text currently lives in a local dict inside
`get_stock_stats_indicators_window`. A second vendor needs the same text, so
hoist it to a module constant rather than copying it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mexc_dataflow.py`:

```python
from tradingagents.dataflows.stockstats_utils import INDICATOR_DESCRIPTIONS


def test_indicator_descriptions_are_shared_and_populated():
    for key in ("close_50_sma", "rsi", "macd", "atr", "vwma", "boll_ub"):
        assert key in INDICATOR_DESCRIPTIONS
        assert len(INDICATOR_DESCRIPTIONS[key]) > 20


def test_get_mexc_indicators_reports_values_per_date():
    rows = [
        [1783641600000 + i * 86_400_000, "1.0", "1.2", "0.9",
         str(1.0 + i / 100), "1000.0", 0, "0"]
        for i in range(80)
    ]
    with patch.object(mexc, "_klines", return_value=rows):
        out = mexc.get_mexc_indicators("CATE-USD", "rsi", "2026-10-07", 3)
    assert "## rsi values" in out
    assert out.count("2026-10-") >= 3
    assert INDICATOR_DESCRIPTIONS["rsi"] in out


def test_get_mexc_indicators_rejects_unknown_indicator():
    with pytest.raises(ValueError, match="not supported"):
        mexc.get_mexc_indicators("CATE-USD", "not_an_indicator", "2026-07-29", 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -k "indicator" -v`
Expected: FAIL — `ImportError: cannot import name 'INDICATOR_DESCRIPTIONS'`

- [ ] **Step 3: Write minimal implementation**

3a. In `tradingagents/dataflows/y_finance.py`, cut the entire `best_ind_params = {...}` literal out of `get_stock_stats_indicators_window` and paste it into `tradingagents/dataflows/stockstats_utils.py` at module level, renamed:

```python
# Indicator reference text shared by every vendor that reports indicators, so
# the agent sees identical guidance whether the candles came from Yahoo or MEXC.
INDICATOR_DESCRIPTIONS = {
    # ... the exact dict body previously inlined in get_stock_stats_indicators_window ...
}
```

3b. In `y_finance.py`, import it and keep the old local name as an alias so the
rest of that function is untouched:

```python
from .stockstats_utils import INDICATOR_DESCRIPTIONS
...
def get_stock_stats_indicators_window(symbol, indicator, curr_date, look_back_days) -> str:
    best_ind_params = INDICATOR_DESCRIPTIONS
```

3c. Append to `tradingagents/dataflows/mexc.py`:

```python
def get_mexc_indicators(
    symbol: str, indicator: str, curr_date: str, look_back_days: int
) -> str:
    """Vendor entry point for ``get_indicators``, computed off MEXC candles.

    Dates are captured before ``stockstats.wrap`` runs, because wrap normalises
    column names and the date column's identity is not guaranteed to survive.
    Indexing by a positional list keeps this correct either way.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -k indicator -v && .venv/bin/pytest tests/ -k "stockstats or indicator" -q`
Expected: PASS — new tests pass and no existing indicator test regresses

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/stockstats_utils.py tradingagents/dataflows/y_finance.py tradingagents/dataflows/mexc.py tests/test_mexc_dataflow.py
git commit -m "feat(mexc): compute indicators from MEXC candles via shared descriptions"
```

---

## Task 8: Register MEXC in the vendor registry

**Files:**
- Modify: `tradingagents/dataflows/interface.py`, `tradingagents/default_config.py`
- Test: `tests/test_mexc_dataflow.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mexc_dataflow.py`:

```python
from tradingagents.dataflows import interface
from tradingagents.dataflows.config import get_config, set_config


def test_mexc_is_registered_for_price_and_indicator_methods():
    assert "mexc" in interface.VENDOR_METHODS["get_stock_data"]
    assert "mexc" in interface.VENDOR_METHODS["get_indicators"]
    assert "mexc" in interface.VENDOR_LIST


def test_route_to_vendor_uses_mexc_when_configured():
    set_config({"data_vendors": {"core_stock_apis": "mexc"}})
    try:
        with patch.object(mexc, "_klines", return_value=_DAILY):
            out = interface.route_to_vendor(
                "get_stock_data", "CATE-USD", "2026-07-20", "2026-07-22")
        assert "MEXC spot data" in out
    finally:
        set_config({"data_vendors": {"core_stock_apis": "yfinance"}})


def test_default_config_still_prefers_yfinance():
    """Stock runs must not be re-routed by this feature."""
    assert get_config()["data_vendors"]["core_stock_apis"] == "yfinance"
    assert get_config()["data_vendors"]["technical_indicators"] == "yfinance"


def test_include_twitter_defaults_off():
    assert get_config().get("include_twitter") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -k "registered or route_to_vendor or default_config or include_twitter" -v`
Expected: FAIL — `KeyError: 'mexc'`

- [ ] **Step 3: Write minimal implementation**

3a. In `tradingagents/dataflows/interface.py`, add the import beside the other vendor imports:

```python
from .mexc import get_mexc_indicators, get_mexc_stock_data
```

Add `"mexc"` to `VENDOR_LIST`, then extend the two method maps:

```python
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
        "mexc": get_mexc_stock_data,
    },
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
        "mexc": get_mexc_indicators,
    },
```

3b. In `tradingagents/default_config.py`, update the two option comments and add the flag:

```python
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance, mexc
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance, mexc
```

and near the other feature flags:

```python
    # Include Twitter/X posts as a sentiment source. Off by default: the fetcher
    # calls a metered third-party API, so stock runs should not spend credits
    # unless the user asks. The New Crypto tab turns it on for its own runs.
    "include_twitter": False,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -v`
Expected: PASS — whole file green

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/interface.py tradingagents/default_config.py tests/test_mexc_dataflow.py
git commit -m "feat(mexc): register mexc as a price and indicator vendor"
```

---

## Task 9: Twitter/X fetcher

**Files:**
- Create: `tradingagents/dataflows/twitter.py`, `tests/fixtures/twitterapi_search.json`
- Test: `tests/test_twitter_dataflow.py`

**Blocking prerequisite:** this task needs `TWITTERAPI_IO_KEY` in `.env`. The
response schema below follows twitterapi.io's documented advanced-search shape,
but it is unverified against a live call. Step 0 pins it down.

- [ ] **Step 0: Probe the live API and record the fixture**

```bash
curl -s "https://api.twitterapi.io/twitter/tweet/advanced_search?query=%24BTC%20lang%3Aen&queryType=Top" \
  -H "X-API-Key: $TWITTERAPI_IO_KEY" | tee tests/fixtures/twitterapi_search.json | head -c 800
```

Compare the real field names against the fixture assumptions below
(`tweets[]`, `text`, `createdAt`, `likeCount`, `retweetCount`,
`author.userName`). If they differ, update `_FIELD_ALIASES` in step 3 and the
fixture-based assertions in step 1 to match reality. Trim the recorded fixture
to 3 tweets so the test stays readable.

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for the Twitter/X sentiment fetcher (no network)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tradingagents.dataflows import twitter

pytestmark = pytest.mark.unit

_FIXTURE = Path(__file__).parent / "fixtures" / "twitterapi_search.json"


@pytest.fixture
def payload():
    return json.loads(_FIXTURE.read_text())


def test_returns_placeholder_without_key(monkeypatch):
    monkeypatch.delenv("TWITTERAPI_IO_KEY", raising=False)
    out = twitter.fetch_twitter_posts("$CATE")
    assert out == "<twitter unavailable: TWITTERAPI_IO_KEY not set>"


def test_formats_posts_from_payload(monkeypatch, payload):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    with patch.object(twitter, "_request", return_value=payload):
        out = twitter.fetch_twitter_posts("$CATE", start_date="2026-07-22",
                                          end_date="2026-07-29")
    assert "X/Twitter posts" in out
    assert "likes" in out
    assert "<twitter unavailable" not in out


def test_caps_post_count(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    many = {"tweets": [
        {"text": f"post {i}", "createdAt": "2026-07-28T00:00:00Z",
         "likeCount": i, "retweetCount": 0, "author": {"userName": f"u{i}"}}
        for i in range(100)
    ]}
    with patch.object(twitter, "_request", return_value=many):
        out = twitter.fetch_twitter_posts("$CATE", limit=5)
    assert out.count("@u") == 5


def test_placeholder_on_http_error(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    with patch.object(twitter, "_request", side_effect=OSError("timed out")):
        out = twitter.fetch_twitter_posts("$CATE")
    assert out.startswith("<twitter unavailable: OSError")


def test_placeholder_on_malformed_json(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    with patch.object(twitter, "_request", return_value={"unexpected": True}):
        out = twitter.fetch_twitter_posts("$CATE")
    assert out.startswith("<no X/Twitter posts found")


def test_query_includes_cashtag_dates_and_excludes_retweets(monkeypatch):
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    seen = {}

    def capture(params, key, timeout):
        seen.update(params)
        return {"tweets": []}

    with patch.object(twitter, "_request", side_effect=capture):
        twitter.fetch_twitter_posts("$CATE OR Catestein",
                                    start_date="2026-07-22", end_date="2026-07-29")
    assert "$CATE" in seen["query"]
    assert "since:2026-07-22" in seen["query"]
    assert "until:2026-07-29" in seen["query"]
    assert "-filter:retweets" in seen["query"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_twitter_dataflow.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tradingagents.dataflows.twitter'`

- [ ] **Step 3: Write minimal implementation**

Create `tradingagents/dataflows/twitter.py`:

```python
"""Twitter/X post fetcher for ticker and coin sentiment.

No free X read path exists: ``api.twitter.com`` requires a paid bearer token,
the syndication search endpoint returns an empty body, and public nitter
instances are dead. This module therefore talks to twitterapi.io, a metered
reseller of X search (per-request pricing, no monthly floor), keyed by
``TWITTERAPI_IO_KEY``.

Contract matches ``reddit.py`` / ``stocktwits.py``: always returns a string,
never raises, and returns a clearly marked placeholder when the source is
unavailable — so the sentiment analyst reports "no data" instead of inventing
posts, the failure mode the analyst redesign in #557 existed to prevent.
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

# Response field names are read through aliases: the reseller's schema is not
# contractually stable, and a renamed field should degrade one column rather
# than break the whole block.
_FIELD_ALIASES = {
    "text": ("text", "full_text", "content"),
    "created": ("createdAt", "created_at", "date"),
    "likes": ("likeCount", "favorite_count", "likes"),
    "retweets": ("retweetCount", "retweet_count", "retweets"),
}


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
    both. Engagement counts are included so the model can weight a 900-like
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
        logger.warning("Twitter fetch failed for %r: %s", terms, exc)
        return f"<twitter unavailable: {type(exc).__name__}: {exc}>"

    tweets = data.get("tweets") if isinstance(data, dict) else None
    if not isinstance(tweets, list) or not tweets:
        return f"<no X/Twitter posts found for {terms}>"

    lines = []
    for tw in tweets[:limit]:
        if not isinstance(tw, dict):
            continue
        author = (tw.get("author") or {})
        user = author.get("userName") or author.get("screen_name") or "?"
        body = str(_first(tw, _FIELD_ALIASES["text"])).replace("\n", " ").strip()
        if len(body) > 280:
            body = body[:280] + "…"
        lines.append(
            f"[{_first(tw, _FIELD_ALIASES['created'], '?')}] @{user} "
            f"({_first(tw, _FIELD_ALIASES['likes'], 0)} likes, "
            f"{_first(tw, _FIELD_ALIASES['retweets'], 0)} RT): {body}"
        )

    if not lines:
        return f"<no X/Twitter posts found for {terms}>"

    window = f" from {start_date} to {end_date}" if start_date and end_date else ""
    return (
        f"## X/Twitter posts for {terms}{window} ({len(lines)} posts, "
        f"ranked by engagement)\n\n" + "\n".join(lines)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_twitter_dataflow.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/twitter.py tests/test_twitter_dataflow.py tests/fixtures/twitterapi_search.json
git commit -m "feat(twitter): add a twitterapi.io-backed X post fetcher"
```

---

## Task 10: Wire Twitter into the sentiment analyst

**Files:**
- Modify: `tradingagents/agents/analysts/sentiment_analyst.py`
- Test: `tests/test_sentiment_twitter_block.py`

- [ ] **Step 1: Write the failing test**

```python
"""The Twitter block reaches the sentiment prompt only when configured on."""

import pytest

from tradingagents.agents.analysts import sentiment_analyst as sa

pytestmark = pytest.mark.unit


def _kwargs(**over):
    base = dict(ticker="CATE-USD", start_date="2026-07-22", end_date="2026-07-29",
                news_block="NEWS", stocktwits_block="TWITS", reddit_block="REDDIT")
    base.update(over)
    return base


def test_prompt_omits_twitter_section_when_block_is_empty():
    msg = sa._build_system_message(**_kwargs(twitter_block=""))
    assert "start_of_twitter" not in msg
    assert "three complementary data sources" in msg
    assert "REDDIT" in msg


def test_prompt_includes_twitter_section_when_block_present():
    msg = sa._build_system_message(**_kwargs(twitter_block="TWEETS"))
    assert "<start_of_twitter>" in msg
    assert "TWEETS" in msg
    assert "four complementary data sources" in msg


def test_fetch_is_skipped_when_include_twitter_is_off(monkeypatch):
    called = []
    monkeypatch.setattr(sa, "fetch_twitter_posts",
                        lambda *a, **k: called.append(1) or "TWEETS")
    monkeypatch.setattr(sa, "get_config", lambda: {"include_twitter": False})
    assert sa._maybe_twitter_block("CATE-USD", "2026-07-22", "2026-07-29") == ""
    assert called == []


def test_fetch_runs_when_include_twitter_is_on(monkeypatch):
    monkeypatch.setattr(sa, "fetch_twitter_posts", lambda *a, **k: "TWEETS")
    monkeypatch.setattr(sa, "get_config", lambda: {"include_twitter": True})
    assert sa._maybe_twitter_block("CATE-USD", "2026-07-22", "2026-07-29") == "TWEETS"


def test_block_is_empty_when_fetcher_reports_unavailable(monkeypatch):
    """An unavailable source must not add an empty section header to the prompt."""
    monkeypatch.setattr(sa, "fetch_twitter_posts",
                        lambda *a, **k: "<twitter unavailable: TWITTERAPI_IO_KEY not set>")
    monkeypatch.setattr(sa, "get_config", lambda: {"include_twitter": True})
    out = sa._maybe_twitter_block("CATE-USD", "2026-07-22", "2026-07-29")
    assert out.startswith("<twitter unavailable")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_sentiment_twitter_block.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_maybe_twitter_block'`

- [ ] **Step 3: Write minimal implementation**

3a. Add imports to `sentiment_analyst.py`:

```python
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.twitter import fetch_twitter_posts
```

3b. Add the gate helper next to `_seven_days_back`:

```python
def _maybe_twitter_block(ticker: str, start_date: str, end_date: str) -> str:
    """Fetch X posts when enabled, else return "" so the prompt omits the section.

    Gated on config rather than on key presence because the fetch is metered:
    a stock run should not spend X credits unless the user opted in.
    """
    if not get_config().get("include_twitter"):
        return ""
    base = ticker.split("-")[0].upper()
    return fetch_twitter_posts(
        f"${base} OR {base}", start_date=start_date, end_date=end_date
    )
```

3c. In `sentiment_analyst_node`, after the existing three fetches:

```python
        twitter_block = _maybe_twitter_block(ticker, start_date, end_date)
```

and pass `twitter_block=twitter_block` into the `_build_system_message(...)` call.

3d. Change `_build_system_message` to accept the block and vary the source count and section:

```python
def _build_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
    twitter_block: str = "",
) -> str:
    """Assemble the sentiment-analyst system message with structured data blocks."""
    source_count = "four" if twitter_block else "three"
    twitter_section = ""
    if twitter_block:
        twitter_section = f"""
### X/Twitter posts — public timeline search, ranked by engagement
Fastest-moving retail signal, and the most promotion-heavy. Weight posts by their like/retweet counts and discount coordinated shilling.

<start_of_twitter>
{twitter_block}
<end_of_twitter>
"""
```

Then, in the returned f-string, replace `three complementary data sources` with
`{source_count} complementary data sources` and insert `{twitter_section}` after
the Reddit block's `<end_of_reddit>` line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sentiment_twitter_block.py -v && .venv/bin/pytest tests/ -k sentiment -q`
Expected: PASS — 5 new tests pass, existing sentiment tests unchanged

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/analysts/sentiment_analyst.py tests/test_sentiment_twitter_block.py
git commit -m "feat(sentiment): add a config-gated X/Twitter source block"
```

---

## Task 11: Crypto analyze configuration

**Files:**
- Create: `crypto_screener.py`
- Test: `tests/test_crypto_screener.py`

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for the New Crypto tab's pure helpers (no Streamlit runtime)."""

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "crypto_screener.py"

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def screener():
    spec = importlib.util.spec_from_file_location("ta_crypto_screener", _PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ta_crypto_screener"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_crypto_analysts_exclude_fundamentals(screener):
    assert screener.CRYPTO_ANALYSTS == ("market", "social", "news")


def test_build_crypto_config_routes_prices_to_mexc(screener):
    base = {"data_vendors": {"core_stock_apis": "yfinance",
                             "technical_indicators": "yfinance",
                             "news_data": "yfinance"},
            "llm_provider": "openai", "deep_think_llm": "x", "quick_think_llm": "y",
            "max_debate_rounds": 9, "max_risk_discuss_rounds": 9}
    cfg = screener.build_crypto_config(
        base, provider="google", deep_model="gemini-3.1-flash-lite",
        quick_model="gemini-3.1-flash-lite", debate_rounds=1, risk_rounds=2)

    assert cfg["data_vendors"]["core_stock_apis"] == "mexc"
    assert cfg["data_vendors"]["technical_indicators"] == "mexc"
    assert cfg["data_vendors"]["news_data"] == "yfinance"   # news still Yahoo
    assert cfg["include_twitter"] is True
    assert cfg["llm_provider"] == "google"
    assert cfg["max_debate_rounds"] == 1
    assert cfg["max_risk_discuss_rounds"] == 2
    # the caller's dict must not be mutated
    assert base["data_vendors"]["core_stock_apis"] == "yfinance"
    assert base.get("include_twitter") is None


def test_instrument_context_uses_mexc_metadata(screener):
    from tradingagents.dataflows.mexc import NewCoin
    coin = NewCoin(symbol="CATEUSDT", base="CATE", name="Catestein",
                   contract="0xabc", listed_date="2026-07-20", age_days=9,
                   price=0.0037, change_pct=12.0, quote_volume=200_000.0)
    ctx = screener.coin_instrument_context(coin)
    assert "CATE" in ctx and "Catestein" in ctx
    assert "0xabc" in ctx
    assert "2026-07-20" in ctx
    assert "crypto" in ctx.lower()


def test_verdict_key_is_symbol_and_date_scoped(screener):
    assert screener.verdict_key("CATEUSDT", "2026-07-29") == "verdict:CATEUSDT:2026-07-29"


@pytest.mark.parametrize("signal,expected", [
    ("BUY", "▲ BUY"), ("SELL", "▼ SELL"), ("HOLD", "■ HOLD"), ("", "—"),
])
def test_verdict_label(screener, signal, expected):
    assert screener.verdict_label(signal) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_crypto_screener.py -v`
Expected: FAIL — `FileNotFoundError: crypto_screener.py`

- [ ] **Step 3: Write minimal implementation**

Create `crypto_screener.py` with the pure helpers only (UI comes in Task 12):

```python
"""New Crypto tab — MEXC new-listing screener with per-coin agent analysis.

Kept out of app.py, which already carries the whole single-run screen. The pure
helpers here (config building, instrument context, verdict formatting) are unit
tested without a Streamlit runtime; render_new_crypto_tab() is the only part
that touches st.*.
"""

from __future__ import annotations

from copy import deepcopy

# Fundamentals is omitted rather than disabled: a three-week-old memecoin has no
# filings, and giving the analyst nothing to read only feeds placeholders into
# the debate. This mirrors how the CLI filters analysts for crypto.
CRYPTO_ANALYSTS = ("market", "social", "news")


def build_crypto_config(base: dict, *, provider: str, deep_model: str,
                        quick_model: str, debate_rounds: int,
                        risk_rounds: int) -> dict:
    """Config for a new-coin run: MEXC prices, Yahoo news, Twitter on.

    Returns a copy — the caller's DEFAULT_CONFIG must stay untouched so a later
    stock run in the same process still routes prices to yfinance.
    """
    cfg = deepcopy(base)
    cfg["llm_provider"] = provider
    cfg["deep_think_llm"] = deep_model
    cfg["quick_think_llm"] = quick_model
    cfg["max_debate_rounds"] = debate_rounds
    cfg["max_risk_discuss_rounds"] = risk_rounds
    vendors = dict(cfg.get("data_vendors", {}))
    vendors["core_stock_apis"] = "mexc"
    vendors["technical_indicators"] = "mexc"
    cfg["data_vendors"] = vendors
    cfg["include_twitter"] = True
    return cfg


def coin_instrument_context(coin) -> str:
    """Instrument identity for a coin Yahoo has never heard of.

    resolve_instrument_context() looks the ticker up on yfinance, which returns
    nothing for a brand-new MEXC listing. MEXC's own metadata is strictly better
    here, so it is passed to the graph directly.
    """
    contract = f" Contract address: {coin.contract}." if coin.contract else ""
    return (
        f"The ticker {coin.base} refers to {coin.name}, a crypto asset trading on "
        f"MEXC as the spot pair {coin.symbol}. It was first traded on MEXC on "
        f"{coin.listed_date} ({coin.age_days} days ago), so it has almost no price "
        f"history and no company fundamentals.{contract} Treat it as a newly listed "
        f"crypto asset rather than a company, and do not infer a business, revenue, "
        f"or filings for it."
    )


def verdict_key(symbol: str, date: str) -> str:
    """Session-state key so each coin/date verdict survives analyzing another coin."""
    return f"verdict:{symbol}:{date}"


def verdict_label(signal: str) -> str:
    """Render a signal as its table chip."""
    return {"BUY": "▲ BUY", "SELL": "▼ SELL", "HOLD": "■ HOLD"}.get(
        (signal or "").strip().upper(), "—"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_crypto_screener.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add crypto_screener.py tests/test_crypto_screener.py
git commit -m "feat(webapp): add crypto-run config and verdict helpers"
```

---

## Task 12: The tab UI and per-row analyze runner

**Files:**
- Modify: `crypto_screener.py`, `app.py`
- Test: `tests/test_crypto_screener.py`, `tests/test_webapp.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_crypto_screener.py`:

```python
def test_row_cells_formats_price_volume_and_change(screener):
    from tradingagents.dataflows.mexc import NewCoin
    coin = NewCoin(symbol="CATEUSDT", base="CATE", name="Catestein", contract="",
                   listed_date="2026-07-20", age_days=9, price=0.0037841,
                   change_pct=12.4321, quote_volume=140_981.74)
    cells = screener.row_cells(coin)
    assert cells["symbol"] == "CATE"
    assert cells["name"] == "Catestein"
    assert cells["listed"] == "2026-07-20"
    assert cells["age"] == "9d"
    assert cells["price"] == "0.0037841"
    assert cells["change"] == "+12.43%"
    assert cells["volume"] == "$141.0k"


def test_row_cells_marks_negative_change(screener):
    from tradingagents.dataflows.mexc import NewCoin
    coin = NewCoin(symbol="XUSDT", base="X", name="X", contract="",
                   listed_date="2026-07-20", age_days=9, price=1.5,
                   change_pct=-6.1, quote_volume=2_400_000.0)
    cells = screener.row_cells(coin)
    assert cells["change"] == "-6.10%"
    assert cells["volume"] == "$2.4M"


def test_status_caption_reports_cache_and_gaps(screener):
    from tradingagents.dataflows.mexc import ScreenResult
    res = ScreenResult(coins=[], scanned=1741, unresolved=12, hidden_by_volume=5,
                       fetched_at=0.0, from_cache=True, stale=True)
    caption = screener.status_caption(res)
    assert "1741" in caption
    assert "12" in caption          # unresolved symbols surfaced, not hidden
    assert "5" in caption           # volume-filtered count surfaced
    assert "stale" in caption.lower()
```

Append to `tests/test_webapp.py`:

```python
def test_app_exposes_the_run_analysis_tab_renderer(app):
    """main() must delegate, so a `return` in the run screen cannot skip tab 2."""
    assert callable(app.render_run_analysis_tab)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_crypto_screener.py tests/test_webapp.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'row_cells'` and `... has no attribute 'render_run_analysis_tab'`

- [ ] **Step 3: Write minimal implementation**

3a. Append formatting helpers to `crypto_screener.py`:

```python
def _fmt_volume(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}k"
    return f"${value:.0f}"


def row_cells(coin) -> dict:
    """Pre-formatted display strings for one table row."""
    price = f"{coin.price:.8f}".rstrip("0") or "0"
    return {
        "symbol": coin.base,
        "name": coin.name,
        "listed": coin.listed_date,
        "age": f"{coin.age_days}d",
        "price": price,
        "change": f"{coin.change_pct:+.2f}%",
        "volume": _fmt_volume(coin.quote_volume),
    }


def status_caption(result) -> str:
    """One line describing sweep coverage. Never hides what could not be checked."""
    import time

    parts = [f"{result.scanned} MEXC USDT pairs scanned"]
    if result.unresolved:
        parts.append(f"{result.unresolved} could not be checked (rate-limited)")
    if result.hidden_by_volume:
        parts.append(f"{result.hidden_by_volume} hidden by the volume floor")
    if result.fetched_at:
        age_min = max(0, int((time.time() - result.fetched_at) / 60))
        parts.append(f"data {age_min} min old" + (" — STALE, refresh failed" if result.stale else ""))
    elif result.stale:
        parts.append("STALE, refresh failed")
    return " · ".join(parts)
```

3b. Append the UI to `crypto_screener.py`:

```python
def render_new_crypto_tab(*, model: str, provider: str, trade_date: str,
                          base_config: dict, debate_rounds: int, risk_rounds: int,
                          configure_cfg, streaming_runner) -> None:
    """Render the screener table and run one coin's analysis on demand.

    ``configure_cfg`` and ``streaming_runner`` are injected from app.py so this
    module never imports app.py (which would re-execute its Streamlit setup).
    """
    import streamlit as st

    from tradingagents.dataflows import mexc

    st.markdown(
        '<div style="font-family:var(--font-display);font-size:13px;letter-spacing:.08em;'
        'text-transform:uppercase;color:var(--muted);margin-bottom:4px">'
        f'New crypto · MEXC · first traded within {mexc.WINDOW_DAYS} days</div>',
        unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1, 1, 1])
    min_vol = c1.number_input("Min 24h volume (USDT)", min_value=0.0,
                              value=mexc.DEFAULT_MIN_QUOTE_VOLUME, step=10_000.0)
    include_all = c2.checkbox("Show all (including dust)", value=False)
    refresh = c3.button("↻ Refresh scan", help="Re-sweep MEXC now (~2 minutes)")

    try:
        with st.spinner("Scanning MEXC listings…"):
            result = mexc.screen_new_listings(
                min_quote_volume=min_vol, include_all=include_all,
                force_refresh=refresh)
    except mexc.MexcUnavailable as exc:
        st.error(f"Cannot reach MEXC: {exc}")
        return

    st.caption(status_caption(result))
    if not result.coins:
        st.info("No MEXC coins matched the window and volume floor.")
        return

    head = ("SYMBOL", "NAME", "LISTED", "AGE", "PRICE", "24H", "VOLUME", "VERDICT", "")
    widths = [1.1, 2.2, 1.2, 0.6, 1.2, 0.9, 1.0, 1.1, 0.9]
    hdr = st.columns(widths)
    for col, label in zip(hdr, head):
        col.markdown(
            f"<div style='font-family:var(--font-mono);font-size:11px;"
            f"letter-spacing:.08em;color:var(--faint)'>{label}</div>",
            unsafe_allow_html=True)

    to_run = None
    for coin in result.coins:
        cells = row_cells(coin)
        cols = st.columns(widths)
        cols[0].markdown(f"**{cells['symbol']}**")
        cols[1].write(cells["name"])
        cols[2].write(cells["listed"])
        cols[3].write(cells["age"])
        cols[4].write(cells["price"])
        colour = "#22C55E" if coin.change_pct >= 0 else "#EF4444"
        cols[5].markdown(
            f"<span style='color:{colour}'>{cells['change']}</span>",
            unsafe_allow_html=True)
        cols[6].write(cells["volume"])

        stored = st.session_state.get(verdict_key(coin.symbol, trade_date), "")
        cols[7].markdown(f"**{verdict_label(stored)}**")
        if cols[8].button("Analyze", key=f"analyze_{coin.symbol}"):
            to_run = coin

    if to_run is None:
        return

    cfg = build_crypto_config(
        base_config, provider=provider, deep_model=model, quick_model=model,
        debate_rounds=debate_rounds, risk_rounds=risk_rounds)
    configure_cfg(cfg, model)
    signal = streaming_runner(
        ticker=to_run.symbol, trade_date=trade_date,
        selected=list(CRYPTO_ANALYSTS), cfg=cfg, provider=provider, model=model,
        asset_type="crypto", instrument_context=coin_instrument_context(to_run))
    st.session_state[verdict_key(to_run.symbol, trade_date)] = signal or ""
```

3c. In `app.py`, generalise `run_single_streaming` so the crypto tab can reuse it
verbatim. Change its signature and the two lines that hard-code stock behavior,
and return the signal:

```python
def run_single_streaming(ticker, trade_date, selected, cfg, provider, model,
                         asset_type: str = "stock",
                         instrument_context: str | None = None) -> str:
    """One model, with live streaming progress + reports. Returns the final signal."""
```

Inside, replace the identity/init block with:

```python
        ta = TradingAgentsGraph(selected_analysts=tuple(selected), debug=False, config=cfg)
        past = ta.memory_log.get_past_context(ticker)
        inst = instrument_context or ta.resolve_instrument_context(ticker, asset_type)
        init_state = ta.propagator.create_initial_state(
            ticker, trade_date, asset_type=asset_type, past_context=past,
            instrument_context=inst)
```

Change the error path's `return` to `return ""`, and at the end return the signal:
after `render_decision(...)` and the download button, `return signal`; in the
no-decision branch, `return ""`.

3d. In `app.py`, extract the body of `main()` after the sidebar into a new
function and add the tab shell. `main()` becomes:

```python
def main() -> None:
    st.set_page_config(page_title="TradingAgents", page_icon="◈", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(header_html(), unsafe_allow_html=True)
    with st.sidebar:
        # ... unchanged sidebar body, ending with:
        run = st.button("▶  Run analysis", type="primary", use_container_width=True)

    tab_run, tab_new = st.tabs(["Run analysis", "New Crypto"])
    with tab_run:
        # A plain `with` block cannot host the early `return`s of the run screen —
        # they would exit main() and skip the second tab — so it is a function.
        render_run_analysis_tab(ticker, trade_date, selected, debate_rounds,
                               risk_rounds, run)
    with tab_new:
        default_model = DEFAULT_CONFIG["deep_think_llm"]
        opts = model_options(default_model)
        model = st.selectbox("Model", opts, index=0, key="crypto_model")
        render_new_crypto_tab(
            model=model, provider=provider_for(model), trade_date=trade_date,
            base_config=DEFAULT_CONFIG, debate_rounds=debate_rounds,
            risk_rounds=risk_rounds, configure_cfg=configure_cfg,
            streaming_runner=lambda **kw: run_single_streaming(**kw))
```

with `render_run_analysis_tab` holding the previous body verbatim (the
`render_run_mode` call, the Ready card, the validation `return`s, the Stop
button, and the single/parallel dispatch), and this import at the top of
`app.py`:

```python
from crypto_screener import render_new_crypto_tab
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_crypto_screener.py tests/test_webapp.py -v`
Expected: PASS — 11 crypto-screener tests and the existing webapp tests pass

- [ ] **Step 5: Commit**

```bash
git add crypto_screener.py app.py tests/test_crypto_screener.py tests/test_webapp.py
git commit -m "feat(webapp): add the New Crypto screener tab with per-row analysis"
```

---

## Task 13: Full regression run

**Files:** none modified

- [ ] **Step 1: Run the whole unit suite**

Run: `.venv/bin/pytest tests/ -m unit -q`
Expected: PASS — every test green, no collection errors

- [ ] **Step 2: Confirm stock runs still route to yfinance**

Run: `.venv/bin/pytest tests/ -k "vendor or interface or symbol" -q`
Expected: PASS — default routing untouched

- [ ] **Step 3: Lint**

Run: `.venv/bin/python -m ruff check tradingagents/dataflows/mexc.py tradingagents/dataflows/twitter.py crypto_screener.py app.py`
Expected: no errors (line-length limit is 100)

- [ ] **Step 4: Commit any fixes**

```bash
git add -A && git commit -m "test: fix regressions found by the full suite"
```

---

## Task 14: Live integration checks

**Files:**
- Modify: `tests/test_mexc_dataflow.py`

- [ ] **Step 1: Add network-marked tests**

```python
@pytest.mark.integration
def test_live_screen_returns_plausible_new_coins():
    result = mexc.screen_new_listings(force_refresh=False)
    assert result.scanned > 500
    for coin in result.coins:
        assert 0 <= coin.age_days <= mexc.WINDOW_DAYS
        assert coin.symbol.endswith("USDT")


@pytest.mark.integration
def test_live_mexc_stock_data_parses_for_a_known_pair():
    out = mexc.get_mexc_stock_data("BTC-USD", "2026-07-01", "2026-07-29")
    assert "# MEXC spot data for BTCUSDT" in out
    assert "Date,Open,High,Low,Close,Volume" in out
```

- [ ] **Step 2: Run them explicitly**

Run: `.venv/bin/pytest tests/test_mexc_dataflow.py -m integration -v`
Expected: PASS (needs network; the first call may take ~2 minutes on a cold cache)

- [ ] **Step 3: Commit**

```bash
git add tests/test_mexc_dataflow.py
git commit -m "test(mexc): add network-marked live sweep and OHLCV checks"
```

---

## Task 15: Manual end-to-end verification

**Files:** none modified

- [ ] **Step 1: Launch the app**

```bash
.venv/bin/streamlit run app.py --server.port 8503
```

Wait for `http://localhost:8503/_stcore/health` to return 200.

- [ ] **Step 2: Screenshot the tab and read the screenshot**

Drive a headless browser to `http://localhost:8503`, click the "New Crypto"
tab, and capture a full screenshot. Confirm visually: rows are present, dates
are within 30 days, prices and 24h percentages are populated, and the caption
reports the scan coverage. A blank or empty table is a failure, not a pass.

- [ ] **Step 3: Analyze one real coin**

Click Analyze on the highest-volume row. Confirm the stage progress advances,
the sentiment report names X/Twitter as a source (or explicitly reports it
unavailable if no key is set), and a BUY / SELL / HOLD verdict lands in the row's
Verdict cell.

- [ ] **Step 4: Confirm the stock tab is unaffected**

Switch to "Run analysis", run NVDA with the default settings, and confirm it
still completes with a verdict — proving the vendor override did not leak.

- [ ] **Step 5: Commit any fixes found**

```bash
git add -A && git commit -m "fix: address issues found in manual verification"
```

---

## Plan self-review

**Spec coverage:** Section 1 (MEXC data layer) → Tasks 1–8. Section 2 (Twitter)
→ Task 9. Section 3 (analyze wiring) → Tasks 11–12. Section 4 (tab UI) → Task
12. Section 5 (error handling) → covered by tests in Tasks 1, 5, 6, 9, 12
(blocked host, stale cache, unresolved symbols, missing key, no-data). Section 6
(testing) → Tasks 13–15.

**Known gap, deliberately deferred:** the twitterapi.io response schema is
unverified. Task 9 Step 0 pins it against a live key before the fetcher is
trusted, and the alias table plus placeholder tests mean a schema mismatch
degrades one column rather than breaking a run.

**Type consistency:** `NewCoin` and `ScreenResult` field names are used
identically in Tasks 5, 6, 11, and 12. `screen_new_listings` keyword arguments
match between definition (Task 5) and both call sites (Tasks 12, 14).
`run_single_streaming` gains `asset_type` and `instrument_context` in Task 12
and the screener passes exactly those names. `_klines` is defined in Task 4 and
patched by name in Tasks 6 and 7.
