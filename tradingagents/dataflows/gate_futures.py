"""Gate USDT perpetual futures — the adapter behind the exchange door.

The app moved from MEXC to Gate on the operator's word, Oct 10, 2026:
*"okay switch to gate from now on, this means every logic in my app will be
gate instead of mexc"*. Spec: docs/superpowers/specs/2026-10-10-switch-to-gate-design.md.

Every caller reaches this through `tradingagents.dataflows.exchange` (the
door), never by importing it, and it answers in the SHAPES the app already
reads from `mexc_futures` (spec D4): a contract spec carries `contractSize`,
`minVol`, `priceScale`, `maintenanceMarginRate`, `takerFeeRate`...; candles
come back as the `Date/Open/High/Low/Close/Volume` frame; intervals keep
MEXC's names (`Min1`..`Day1`) at the door.

Measured on Oct 10, 2026, and leaned on below:

* 1,027 contracts; `contract_type` says what each one IS — "" (crypto),
  stocks, indices, metals, forex, commodities. Stocks are named by ticker
  (`AAPL_USDT`), so the NAME never says what a coin is (spec D5).
* Taker 0.075%, maker -0.01%, on every contract.
* Keyless calls: 200 per 10 seconds PER ENDPOINT, counted per IP; a 429
  with label TOO_MANY_REQUESTS when exceeded.
* Errors come back as HTTP 4xx with a JSON `{"label", "message"}`.

ALL HTTP goes through `_fetch(url) -> (status, bytes)`, so a test stubs one
function and the retry, pause and error paths all still run for real.
"""
from __future__ import annotations

import decimal
import http.client
import json
import logging
import os
import pathlib as _pathlib
import random as _random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from tradingagents.dataflows.exchange_common import (  # noqa: F401  (re-exported)
    book_cost_from, chase_guard, funding_summary_from)
from tradingagents.dataflows.exchange_errors import (  # noqa: F401  (re-exported)
    VenueAuthFailed, VenueEdgeBlocked, VenueError, VenueForbidden,
    VenueThrottled)

logger = logging.getLogger(__name__)

NAME = "Gate"
HOST = "api.gateio.ws"
BASE = f"https://{HOST}/api/v4"
FUT = f"{BASE}/futures/usdt"
ARCHIVE = "https://download.gatedata.org"
_TIMEOUT = 20.0
_UA = "tradingagents/0.3"

# The order-side codes the runner already speaks (MEXC's numbering). The
# private half (phase 6) translates them to Gate's signed sizes.
SIDE_OPEN_LONG = 1
SIDE_CLOSE_SHORT = 2
SIDE_OPEN_SHORT = 3
SIDE_CLOSE_LONG = 4
TYPE_LIMIT = 1
TYPE_MARKET = 5


class GateFuturesError(VenueError):
    """A Gate request could not be made or was rejected."""


class GateFuturesThrottled(GateFuturesError, VenueThrottled):
    """Gate answered 429 TOO_MANY_REQUESTS."""


class GateFuturesAuthFailed(GateFuturesError, VenueAuthFailed):
    """Gate rejected the key, the signature or the clock."""


class GateFuturesForbidden(GateFuturesError, VenueForbidden):
    """The key authenticated but lacks a permission."""


# ---------------------------------------------------------------- the wire
def _fetch(url: str) -> tuple[int, bytes]:
    """ONE keyless GET: (HTTP status, body). A 4xx/5xx is an answer and
    comes back as its status; only a failure of the wire raises."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read() or b""


# A keyless GET is idempotent, so a failure of the WIRE is tried again —
# the same budget `mexc_futures` earned on Aug 25, 2026 (an IncompleteRead
# lost a pair for good): three attempts, never past 30 s of wall-clock.
_PUBLIC_RETRIES = 3
_PUBLIC_BACKOFF = (1.0, 2.0)
_PUBLIC_RETRY_BUDGET_S = 30.0
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_retry_sleep = time.sleep
_clock = time.monotonic

# ONE PAUSE FOR EVERY PROCESS ON THIS PC — the lesson of Oct 02, 2026 (six
# rooms, one internet line, 64 "too many requests" in a day). Gate counts
# per IP too. Its own file: a pause MEXC earned never holds Gate's calls.
PUBLIC_PAUSE_PATH = (_pathlib.Path.home() / ".tradingagents" / "shared"
                     / "public_pause_gate.json")
PUBLIC_PAUSE_S = 2.0
PUBLIC_PAUSE_MAX_WAIT_S = 3.0
PUBLIC_PAUSE_JITTER_S = 0.5
_pause_sleep = time.sleep


def _note_rate_limit() -> None:
    """Tell every other process on this PC to hold its keyless calls."""
    try:
        now = time.time()
        PUBLIC_PAUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PUBLIC_PAUSE_PATH.with_name(
            f"{PUBLIC_PAUSE_PATH.name}.{os.getpid()}."
            f"{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"until": now + PUBLIC_PAUSE_S,
                                   "pid": os.getpid(), "at": now}),
                       encoding="utf-8")
        for _ in range(20):
            try:
                os.replace(tmp, PUBLIC_PAUSE_PATH)
                return
            except PermissionError:       # a reader has it open (Windows)
                time.sleep(0.01)
        tmp.unlink()
    except Exception as exc:                                    # noqa: BLE001
        logger.debug("could not write the shared pause: %s", exc)


def _honour_shared_pause() -> float:
    """Wait out another process's rate-limit pause. Returns seconds waited."""
    try:
        with open(PUBLIC_PAUSE_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
        if int(d.get("pid") or 0) == os.getpid():
            return 0.0
        left = float(d.get("until") or 0.0) - time.time()
    except Exception:                                           # noqa: BLE001
        return 0.0
    if left <= 0:
        return 0.0
    wait = min(left + _random.uniform(0.0, PUBLIC_PAUSE_JITTER_S),
               PUBLIC_PAUSE_MAX_WAIT_S)
    _pause_sleep(wait)
    return wait


def _no_more_tries(attempt: int, t0: float) -> bool:
    return attempt >= _PUBLIC_RETRIES or _clock() - t0 >= _PUBLIC_RETRY_BUDGET_S


def _label(raw: bytes) -> str:
    """Gate's `label: message` out of an error body, or its first bytes."""
    try:
        d = json.loads(raw or b"{}")
        if isinstance(d, dict) and (d.get("label") or d.get("message")):
            return f"{d.get('label') or ''}: {d.get('message') or ''}".strip(": ")
    except ValueError:
        pass
    return (raw or b"")[:200].decode("utf-8", "replace")


def _get_public(url: str):
    """Keyless GET → parsed JSON. Retries a failed wire, a 5xx and a 429
    (writing the shared pause on a 429); a 4xx is an answer and raises at
    once, naming Gate's label. Never used for a signed call."""
    t0 = _clock()
    for attempt in range(1, _PUBLIC_RETRIES + 1):
        _honour_shared_pause()
        try:
            status, raw = _fetch(url)
        except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
            if _no_more_tries(attempt, t0):
                raise GateFuturesError(
                    f"transport failure: {exc} after {attempt} attempts "
                    f"({url})") from exc
        else:
            if status == 200:
                try:
                    return json.loads(raw)
                except ValueError as exc:
                    raise GateFuturesError(f"malformed response from {url}") from exc
            if status == 429:
                _note_rate_limit()
                if _no_more_tries(attempt, t0):
                    err = GateFuturesThrottled(f"429 {_label(raw)} ({url})")
                    err.code = 429
                    raise err
            elif status in _RETRY_STATUSES:
                if _no_more_tries(attempt, t0):
                    raise GateFuturesError(f"{status} {_label(raw)} ({url})")
            else:
                raise GateFuturesError(f"{status} {_label(raw)} ({url})")
        _retry_sleep(_PUBLIC_BACKOFF[min(attempt - 1, len(_PUBLIC_BACKOFF) - 1)])
    raise GateFuturesError(f"no answer from {url} after {_PUBLIC_RETRIES} tries")


def _q(**params) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items()
                                   if v is not None})


# ------------------------------------------------------------- contracts
# The contract list is STATIC within a session (size, tick, leverage, what
# the coin is) and ONE call answers all 1,027, so it is kept an hour in
# memory and on disk. The disk copy is what keeps `kind()` answering while
# Gate is unreachable: the crypto/stocks filter and the daytime rule must not
# turn every stock into "unlisted" on a blip.
CONTRACTS_FILE = (_pathlib.Path.home() / ".tradingagents" / "shared"
                  / "gate_contracts.json")
_SPEC_TTL = 3600
_CONTRACTS: dict = {"at": 0.0, "rows": {}}
_CONTRACTS_LOCK = threading.Lock()


def clear_spec_cache() -> None:
    _CONTRACTS.update(at=0.0, rows={})


def _save_contracts(rows: dict) -> None:
    try:
        CONTRACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONTRACTS_FILE.with_name(f"{CONTRACTS_FILE.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"at": time.time(), "rows": rows}),
                       encoding="utf-8")
        os.replace(tmp, CONTRACTS_FILE)
    except Exception as exc:                                    # noqa: BLE001
        logger.debug("could not keep Gate's contract list: %s", exc)


def _contracts() -> dict:
    """{name: Gate's raw contract} — memory for an hour, then one call, then
    (Gate unreachable) the last list kept on disk, then an error."""
    now = time.time()
    with _CONTRACTS_LOCK:
        if _CONTRACTS["rows"] and now - _CONTRACTS["at"] < _SPEC_TTL:
            return _CONTRACTS["rows"]
        try:
            listed = _get_public(f"{FUT}/contracts")
            rows = {c["name"]: c for c in listed
                    if isinstance(c, dict) and c.get("name")}
            if not rows:
                raise GateFuturesError("Gate's contract list came back empty")
        except VenueError as exc:
            try:
                kept = json.loads(CONTRACTS_FILE.read_text(encoding="utf-8"))
                rows = kept["rows"]
            except Exception:                                   # noqa: BLE001
                raise exc from None
            logger.warning("Gate's contract list is unreachable (%s); using "
                           "the copy kept on disk", exc)
            _CONTRACTS.update(at=now, rows=rows)
            return rows
        _CONTRACTS.update(at=now, rows=rows)
        _save_contracts(rows)
        return rows


def _kind_of(raw: dict) -> str:
    return str(raw.get("contract_type") or "") or "crypto"


def _decimals(step) -> int:
    try:
        return max(0, -decimal.Decimal(str(step)).normalize().as_tuple().exponent)
    except (decimal.InvalidOperation, TypeError, ValueError):
        return 6


def _trading(raw: dict) -> bool:
    return raw.get("status", "trading") == "trading" and not raw.get("in_delisting")


def _spec_from(raw: dict) -> dict:
    """Gate's contract in the field names the runner reads (spec D4)."""
    name = raw["name"]
    step = raw.get("order_price_round") or "0.0001"
    return {
        "symbol": name,
        "displayNameEn": name.replace("_", "/"),
        "contractSize": float(raw.get("quanto_multiplier") or 0.0),
        "volUnit": 1,
        "minVol": int(float(raw.get("order_size_min") or 1)),
        "maxVol": int(float(raw.get("order_size_max") or 0)),
        "priceUnit": float(step),
        "priceScale": _decimals(step),
        "maintenanceMarginRate": float(raw.get("maintenance_rate") or 0.0),
        "takerFeeRate": float(raw.get("taker_fee_rate") or 0.0),
        "makerFeeRate": float(raw.get("maker_fee_rate") or 0.0),
        "maxLeverage": int(float(raw.get("leverage_max") or 1)),
        "minLeverage": int(float(raw.get("leverage_min") or 1)),
        "state": 0 if _trading(raw) else 1,
        "createTime": int(float(raw.get("create_time") or 0)) * 1000,
        "contract_type": _kind_of(raw),
        "funding_interval_h": int(raw.get("funding_interval") or 28800) // 3600,
        "fundingRate": float(raw.get("funding_rate") or 0.0),
        "nextSettleTime": int(float(raw.get("funding_next_apply") or 0)) * 1000,
        "pre_market": bool(raw.get("is_pre_market")),
    }


def contract_spec(symbol: str) -> dict:
    """Keyless contract metadata. NEVER an empty dict as if it were an
    answer: a coin Gate does not list is an error that names it."""
    rows = _contracts()
    raw = rows.get(symbol)
    if raw is None:
        try:
            raw = _get_public(f"{FUT}/contracts/{urllib.parse.quote(symbol)}")
        except GateFuturesError as exc:
            raise GateFuturesError(f"Gate does not list {symbol}: {exc}") from exc
        if not isinstance(raw, dict) or not raw.get("name"):
            raise GateFuturesError(f"contract detail for {symbol} carried no data")
    return _spec_from(raw)


def trading_symbols() -> list[str]:
    """Every contract Gate is trading now and not delisting, sorted — the
    market a sweep or a replay measures."""
    return sorted(n for n, r in _contracts().items() if _trading(r))


def contract_types() -> dict:
    """{symbol: kind} for every listed contract — what a coin IS (D5)."""
    return {n: _kind_of(r) for n, r in _contracts().items()}


def list_contracts(quote: str = "USDT") -> list[dict]:
    """All tradeable perpetuals for a picker, sorted by name."""
    out = []
    for n, r in _contracts().items():
        if not _trading(r) or (quote and not n.endswith(f"_{quote}")):
            continue
        s = _spec_from(r)
        out.append({"symbol": n, "display": s["displayNameEn"],
                    "contract_size": s["contractSize"],
                    "max_leverage": s["maxLeverage"], "vol_unit": 1.0,
                    "min_vol": float(s["minVol"]), "price_unit": s["priceUnit"],
                    "kind": s["contract_type"]})
    out.sort(key=lambda c: c["symbol"])
    return out


# ---------------------------------------------------------------- prices
_PRICES: dict = {"at": 0.0, "px": {}}
_PRICES_TTL = 3.0
_PRICES_LOCK = threading.Lock()


def last_prices(max_age: float = _PRICES_TTL) -> dict:
    """{symbol: last traded price} for EVERY contract from ONE ticker call,
    shared for `max_age` seconds. Only prices above zero; an unreadable list
    is {} and the caller falls back to last_price()."""
    now = time.time()
    with _PRICES_LOCK:
        if now - _PRICES["at"] < max_age:
            return _PRICES["px"]
        try:
            rows = _get_public(f"{FUT}/tickers")
        except Exception:                                      # noqa: BLE001
            return {}
        px = {}
        for d in rows if isinstance(rows, list) else []:
            try:
                v = float(d.get("last"))
            except (TypeError, ValueError, AttributeError):
                continue
            if v > 0 and d.get("contract"):
                px[d["contract"]] = v
        if px:
            _PRICES.update(at=now, px=px)
        return px


def last_price(symbol: str) -> float:
    """The last traded price. NEVER 0.0 as if it were a price — a zero is
    below every short's target and every long's stop (PROVE_USDT, Aug 2026)."""
    rows = _get_public(f"{FUT}/tickers?{_q(contract=symbol)}")
    d = rows[0] if isinstance(rows, list) and rows else {}
    raw = d.get("last") if isinstance(d, dict) else None
    if raw is None:
        raise GateFuturesError(f"ticker for {symbol} carried no last price")
    px = float(raw)
    if not px > 0:
        raise GateFuturesError(f"ticker for {symbol} reported price {px!r}")
    return px


def contracts_for(symbol: str, notional_usd: float,
                  price: float | None = None) -> int:
    """How many contracts approximate `notional_usd`, rounded DOWN."""
    size = float(contract_spec(symbol).get("contractSize") or 0.0)
    px = price if price is not None else last_price(symbol)
    if size <= 0 or px <= 0:
        raise GateFuturesError(f"cannot size {symbol}: contractSize={size} px={px}")
    return int(notional_usd // (size * px))


def round_vol(symbol: str, vol: float) -> int:
    """Snap a contract count DOWN to a whole contract; below the minimum is 0."""
    spec = contract_spec(symbol)
    snapped = int(vol // 1)
    return snapped if snapped >= int(spec.get("minVol") or 1) else 0


def liquidation_move_pct(symbol: str, leverage: float) -> float:
    """How far price may move against a position before Gate liquidates it,
    in %: `1/leverage - maintenance_rate` (MEXC's formula, Gate's rate)."""
    if leverage <= 0:
        return 100.0
    try:
        mmr = float(contract_spec(symbol).get("maintenanceMarginRate") or 0.0)
    except (VenueError, TypeError, ValueError):
        mmr = 0.0
    return max(0.0, (1.0 / leverage - mmr) * 100.0)


# ------------------------------------------------------------------ books
def order_book(symbol: str) -> dict:
    """Live depth: {"bids": [[price, contracts], ...], "asks": [...]}."""
    d = _get_public(f"{FUT}/order_book?{_q(contract=symbol, limit=50)}") or {}
    return {
        "bids": [[float(x["p"]), float(x["s"])] for x in (d.get("bids") or [])],
        "asks": [[float(x["p"]), float(x["s"])] for x in (d.get("asks") or [])],
    }


def book_cost(symbol: str, notional_usd: float = 200.0, *,
              side: str = "buy") -> dict:
    """What it ACTUALLY costs to trade this contract, walked from the live
    book at the size that will trade (exchange_common.book_cost_from)."""
    book = order_book(symbol)
    if not book["asks"] or not book["bids"]:
        # one more look before believing an empty book (MEXC's lesson of
        # Sep 05, 2026: a burst of checks met empty books that read fine
        # one by one)
        time.sleep(0.5)
        book = order_book(symbol)
    size = float(contract_spec(symbol).get("contractSize") or 0.0)
    return book_cost_from(book, contract_size=size, notional_usd=notional_usd,
                          symbol=symbol, side=side)


# ---------------------------------------------------------------- funding
# Gate serves ~30 days of settlements a page. A read that names no window is
# not "since 2019": it covers FUNDING_DEFAULT_DAYS — the longest backtest
# window offered is 180 days — and one coin's read is kept for half an hour,
# because a shard measures five timeframes of one coin back to back and ~20
# callers across the app ask for "all of it" (Oct 10, 2026).
FUNDING_DEFAULT_DAYS = 200
_FUND_TTL_S = 1800
_FUND_CACHE: dict = {}


def funding_history(symbol: str, max_pages: int = 200, *,
                    since_ms: int | None = None) -> list:
    """See `_funding_read`; this keeps one read per coin for half an hour and
    answers any NARROWER ask from it."""
    now = time.time()
    if since_ms is None:
        since_ms = int((now - FUNDING_DEFAULT_DAYS * 86400) * 1000)
    hit = _FUND_CACHE.get(symbol)
    if hit and now - hit[0] < _FUND_TTL_S and hit[1] <= since_ms:
        return list(hit[2])
    rows = _funding_read(symbol, max_pages, since_ms=since_ms)
    _FUND_CACHE[symbol] = (now, since_ms, rows)
    return list(rows)


def _funding_read(symbol: str, max_pages: int = 200, *,
                  since_ms: int | None = None) -> list:
    """Published funding settlements, oldest first:
    ``[{"settle_ms", "rate", "cycle_h"}, ...]``. Keyless.

    Gate serves about 30 days a page (90 rows of an 8-hour contract,
    measured Oct 10, 2026) and pages back with `to=`. `since_ms` stops once
    a page reaches that time — a backtest needs its window, not since 2019.
    A page that FAILS raises: a short funding history makes every trade in
    the missing stretch cheaper than it was (mexc_futures, Aug 26, 2026).

    Sign: a POSITIVE rate means longs pay shorts, as on MEXC.
    """
    try:
        cycle = int(contract_spec(symbol).get("funding_interval_h") or 8) or 8
    except VenueError:
        cycle = 8
    out: dict[int, dict] = {}
    to = None
    for pg in range(1, max_pages + 1):
        url = f"{FUT}/funding_rate?{_q(contract=symbol, limit=1000, to=to)}"
        try:
            rows = _get_public(url)
        except Exception as exc:                               # noqa: BLE001
            raise GateFuturesError(
                f"funding history for {symbol} is incomplete: page {pg} "
                f"failed ({exc})") from exc
        if not rows:
            break
        try:
            ts = [int(r["t"]) for r in rows]
            for r in rows:
                out[int(r["t"]) * 1000] = {"settle_ms": int(r["t"]) * 1000,
                                           "rate": float(r["r"]),
                                           "cycle_h": cycle}
        except (TypeError, ValueError, KeyError) as exc:
            raise GateFuturesError(
                f"funding history for {symbol}: page {pg} is malformed "
                f"({exc})") from exc
        oldest = min(ts)
        if since_ms is not None and oldest * 1000 <= since_ms:
            break
        if to is not None and oldest >= to:
            break                       # no progress: the history ends here
        to = oldest - 1
        time.sleep(0.05)
    else:
        raise GateFuturesError(f"funding history for {symbol} is incomplete: "
                               f"stopped at the {max_pages}-page budget")
    return [out[k] for k in sorted(out)]


def funding_now(symbol: str) -> dict:
    """This contract's CURRENT funding rate, in ONE call. Keyless.
    ``{"rate", "cycle_h", "next_settle_ms", "per_day"}``; `per_day` is what a
    LONG pays over 24 hours at the current cycle (negative: it receives)."""
    raw = _get_public(f"{FUT}/contracts/{urllib.parse.quote(symbol)}") or {}
    rate = float(raw.get("funding_rate") or 0.0)
    cycle = int(raw.get("funding_interval") or 28800) // 3600 or 8
    return {"symbol": symbol, "rate": rate, "cycle_h": cycle,
            "next_settle_ms": int(float(raw.get("funding_next_apply") or 0)) * 1000,
            "per_day": rate * (24.0 / cycle)}


def funding_summary(symbol: str) -> dict:
    """Headline funding numbers for a contract, from the long side."""
    return funding_summary_from(funding_history(symbol), symbol)


# ------------------------------------------------------- the private half
# Orders, the resting stop, positions and the wallet need a Gate API key
# (spec D12, phase 6). Until a key exists every one of them refuses BY NAME —
# a practice room needs none of them, and a real-money path that answered
# "no positions" without asking would be the most dangerous lie here.
def credentials() -> tuple[str | None, str | None]:
    key = os.getenv("GATE_API_KEY", "").strip() or None
    secret = os.getenv("GATE_API_SECRET", "").strip() or None
    return key, secret


def has_credentials() -> bool:
    return False


def _no_key(what: str):
    raise GateFuturesError(
        f"{what} needs a Gate API key, and real-money trading on Gate is not "
        f"switched on yet — the practice account trades without one")


def assets() -> dict:
    _no_key("reading the Gate wallet")


def usdt_equity() -> float:
    _no_key("reading the Gate wallet")


def open_positions(symbol: str | None = None) -> list:
    _no_key("reading Gate positions")


def position_history(symbol: str | None = None, page_size: int = 20) -> list:
    _no_key("reading Gate's closed positions")


def submit(symbol: str, side: int, vol: int, *, leverage: int, **_kw) -> dict:
    _no_key("placing a Gate order")


def place_position_stop(symbol: str, position_id: int, vol: int, **_kw) -> dict:
    _no_key("resting a stop on Gate")


def verify_position_stop(symbol: str, position_id: int) -> dict:
    _no_key("reading a Gate stop")


def open_orders(symbol: str | None = None) -> list:
    _no_key("reading Gate orders")


def cancel_all_orders(symbol: str) -> dict:
    _no_key("cancelling Gate orders")


def preflight(symbol: str) -> dict:
    """What a key can do. With none on this PC: nothing, and it says so."""
    return {"credentials": False, "read_assets": False, "read_positions": False,
            "order_permission": None, "equity_usdt": None,
            "notes": ["no Gate API key on this PC — the practice account "
                      "trades without one"],
            "missing_scopes": [], "remedies": [], "edge_blocked": False,
            "auth_failed": False, "can_rest_stop": None, "clock_ok": None,
            "clock_skew_ms": None, "ready": False, "venue": NAME}


# ---------------------------------------------------------------- candles
# REST serves only the newest 10,000 points of each bar size and answers a
# page that reaches past that with 400 "Candlestick too long ago" — even a
# page mostly inside (measured Oct 10, 2026). So every page is CLIPPED to the
# edge before it is asked, and anything older comes from the monthly archive,
# which holds completed months only (Sep 2026 appeared Oct 01 2:08am UTC).
# The archive has 1m, 5m, 1h, 4h and 1d files; 15m and 30m are built from 5m
# (open first, high max, low min, close last, volume summed). A month nobody
# has published yet is a GAP — never filled with invented bars.
INTERVALS = {"Min1": "1m", "Min5": "5m", "Min15": "15m", "Min30": "30m",
             "Min60": "1h", "Hour4": "4h", "Hour8": "8h", "Day1": "1d"}
PER_S = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600,
         "4h": 14400, "8h": 28800, "1d": 86400}
_ARCHIVE_SOURCE = {"1m": "1m", "5m": "5m", "15m": "5m", "30m": "5m",
                   "1h": "1h", "4h": "4h", "8h": "1h", "1d": "1d"}
REST_POINTS = 10_000
_REST_SAFETY = 5                 # bars kept clear of the edge (clock drift)
_KLINE_PAGE = 2000
_KLINE_CACHE: dict = {}
KLINE_DISK_DIR = (_pathlib.Path.home() / ".tradingagents" / "kline_cache"
                  / "gate")
_KLINE_TTL = {"1m": 30, "5m": 150, "15m": 300, "30m": 300, "1h": 300,
              "4h": 300, "8h": 300, "1d": 300}
_KLINE_DISK_MAX = 44_000
_now = time.time


def _iv(interval: str) -> str:
    """MEXC's interval name (the door's vocabulary) or Gate's -> Gate's."""
    iv = INTERVALS.get(interval, interval)
    if iv not in PER_S:
        raise GateFuturesError(f"unknown interval {interval!r}")
    return iv


def _frame(rows: list):
    """[{t,o,h,l,c,v}] -> the Date/Open/High/Low/Close/Volume frame."""
    import pandas as pd

    rows = sorted(rows, key=lambda r: int(r["t"]))
    return pd.DataFrame({
        "Date": pd.to_datetime([int(r["t"]) for r in rows], unit="s"),
        "Open": [float(r["o"]) for r in rows],
        "High": [float(r["h"]) for r in rows],
        "Low": [float(r["l"]) for r in rows],
        "Close": [float(r["c"]) for r in rows],
        "Volume": [float(r["v"]) for r in rows],
    })


def _empty():
    return _frame([])


def _secs(df):
    """Bar opens in unix seconds, whatever unit the frame keeps its times in
    (pandas 3 keeps `to_datetime(unit="s")` in SECONDS, so `// 10**9` on the
    raw int64 read every time as 1 — the trap CLAUDE.md names for PROVE)."""
    import pandas as pd

    return pd.Series(df["Date"].to_numpy().astype("datetime64[s]").astype("int64"),
                     index=df.index)


def _join(*frames):
    """Concatenate, the LAST copy of an instant wins, sorted."""
    import pandas as pd

    parts = [f for f in frames if f is not None and len(f)]
    if not parts:
        return _empty()
    return (pd.concat(parts, ignore_index=True)
              .drop_duplicates(subset="Date", keep="last")
              .sort_values("Date").reset_index(drop=True))


def rest_edge(interval: str, now: float | None = None) -> int:
    """The oldest bar open (unix s) REST will still serve, kept a few bars
    inside Gate's 10,000-point wall."""
    iv = _iv(interval)
    per = PER_S[iv]
    now = int(_now() if now is None else now)
    newest = now - now % per
    return newest - (REST_POINTS - 1 - _REST_SAFETY) * per


def _rest_range(symbol: str, iv: str, lo: int, hi: int):
    """Bars opening in [lo, hi] from REST, paged back 2,000 at a time and
    never past the edge."""
    per = PER_S[iv]
    lo = max(lo, rest_edge(iv))
    hi = hi - hi % per
    rows: dict[int, dict] = {}
    end = hi
    while end >= lo:
        n = min(_KLINE_PAGE, (end - lo) // per + 1)
        got = _get_public(f"{FUT}/candlesticks?"
                          + _q(contract=symbol, interval=iv, to=end, limit=n))
        if not got:
            break
        for r in got:
            t = int(r["t"])
            if lo <= t <= hi:
                rows[t] = r
        first = min(int(r["t"]) for r in got)
        if first >= end:
            break
        end = first - per
    return _frame(list(rows.values()))


def _month_key(t: int) -> str:
    g = time.gmtime(t)
    return f"{g.tm_year:04d}{g.tm_mon:02d}"


def _months_back(lo: int, hi: int) -> list:
    """Every YYYYMM from hi's month back to lo's, newest first."""
    out = []
    y, m = time.gmtime(hi).tm_year, time.gmtime(hi).tm_mon
    stop = _month_key(lo)
    while True:
        key = f"{y:04d}{m:02d}"
        out.append(key)
        if key <= stop:
            return out
        m -= 1
        if m == 0:
            y, m = y - 1, 12


def _unpublished(ym: str) -> bool:
    """Can this month's archive file simply not exist YET? The current
    month always; the previous one during the first 6 hours of a month."""
    now = int(_now())
    if ym >= _month_key(now):
        return True
    g = time.gmtime(now)
    prev = _month_key(now - g.tm_mday * 86400)
    return ym == prev and g.tm_mday == 1 and g.tm_hour < 6


def _fetch_archive(url: str) -> tuple:
    """The archive is a plain file host: one GET, retried on a cut wire."""
    for attempt in range(1, _PUBLIC_RETRIES + 1):
        try:
            return _fetch(url)
        except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
            if attempt >= _PUBLIC_RETRIES:
                raise GateFuturesError(f"archive unreachable: {exc} ({url})") from exc
            _retry_sleep(_PUBLIC_BACKOFF[min(attempt - 1, len(_PUBLIC_BACKOFF) - 1)])
    raise GateFuturesError(f"archive unreachable ({url})")


def archive_month(symbol: str, kind: str, ym: str):
    """One completed month of `kind` candles from Gate's archive, kept on
    disk (a published month never changes). None when the file does not
    exist; a month that could not exist yet is never remembered as missing."""
    import gzip as _gz

    folder = KLINE_DISK_DIR / "archive" / kind
    hit = folder / f"{symbol}-{ym}.csv.gz"
    miss = folder / f"{symbol}-{ym}.missing"
    if hit.exists():
        raw = hit.read_bytes()
    elif miss.exists():
        return None
    else:
        url = (f"{ARCHIVE}/futures_usdt/candlesticks_{kind}/{ym}/"
               f"{urllib.parse.quote(symbol)}-{ym}.csv.gz")
        status, raw = _fetch_archive(url)
        if status in (403, 404):
            if not _unpublished(ym):
                folder.mkdir(parents=True, exist_ok=True)
                miss.write_text("")
            return None
        if status != 200:
            raise GateFuturesError(f"{status} from the archive for {url}")
        folder.mkdir(parents=True, exist_ok=True)
        tmp = hit.with_name(f"{hit.name}.{os.getpid()}.tmp")
        tmp.write_bytes(raw)
        os.replace(tmp, hit)
    rows = []
    for line in _gz.decompress(raw).decode("utf-8", "replace").splitlines():
        p = line.split(",")
        if len(p) < 6:
            continue
        try:   # columns t,v,c,h,l,o — checked against REST, Oct 10, 2026
            rows.append({"t": int(float(p[0])), "v": float(p[1]),
                         "c": float(p[2]), "h": float(p[3]), "l": float(p[4]),
                         "o": float(p[5])})
        except ValueError:
            continue
    return _frame(rows)


def _resample(df, per: int):
    """Coarser bars from finer ones: open first, high max, low min, close
    last, volume summed. Bars align to the epoch, as Gate's own do."""
    import pandas as pd

    if df is None or not len(df):
        return _empty()
    t = _secs(df)
    g = df.assign(_b=(t - t % per)).groupby("_b", sort=True)
    return pd.DataFrame({
        "Date": pd.to_datetime(g["Open"].first().index, unit="s"),
        "Open": g["Open"].first().to_numpy(),
        "High": g["High"].max().to_numpy(),
        "Low": g["Low"].min().to_numpy(),
        "Close": g["Close"].last().to_numpy(),
        "Volume": g["Volume"].sum().to_numpy(),
    }).reset_index(drop=True)


def _archive_range(symbol: str, iv: str, lo: int, hi: int):
    """Bars opening in [lo, hi] from the archive, walking months back from
    hi's: a month not published yet is skipped, and the first missing or
    empty month after that is where the coin's history begins."""
    src = _ARCHIVE_SOURCE[iv]
    frames = []
    for ym in _months_back(lo, hi):
        f = archive_month(symbol, src, ym)
        if f is None or not len(f):
            if _unpublished(ym):
                continue
            break
        frames.append(f)
    if not frames:
        return _empty()
    df = _join(*frames)
    if src != iv:
        df = _resample(df, PER_S[iv])
    t = _secs(df)
    return df[(t >= lo) & (t <= hi)].reset_index(drop=True)


def _range(symbol: str, interval: str, lo: int, hi: int):
    """Every bar of `interval` opening in [lo, hi]: REST for what it still
    serves, the archive for what it does not. REST wins on an overlap."""
    iv = _iv(interval)
    edge = rest_edge(iv)
    rest = _rest_range(symbol, iv, max(lo, edge), hi) if hi >= edge else None
    old = (_archive_range(symbol, iv, lo, min(hi, edge - PER_S[iv]))
           if lo < edge else None)
    return _join(old, rest)


def _disk_path(symbol: str, iv: str):
    safe = "".join(c for c in f"{symbol}_{iv}" if c.isalnum() or c in "_-")
    return KLINE_DISK_DIR / f"{safe}.json.gz"


def _disk_load(symbol: str, iv: str):
    import gzip as _gz

    import pandas as pd

    try:
        p = _disk_path(symbol, iv)
        if not p.exists():
            return None
        with _gz.open(p, "rt", encoding="utf-8") as fh:
            d = json.load(fh)
        if not d.get("t"):
            return None
        return pd.DataFrame({"Date": pd.to_datetime(d["t"], unit="s"),
                             "Open": d["o"], "High": d["h"], "Low": d["l"],
                             "Close": d["c"], "Volume": d["v"]})
    except Exception:                                          # noqa: BLE001
        return None          # a corrupt cache must never break a fetch


def _disk_save(symbol: str, iv: str, frame) -> None:
    import gzip as _gz

    try:
        KLINE_DISK_DIR.mkdir(parents=True, exist_ok=True)
        f = frame.tail(_KLINE_DISK_MAX)
        d = {"t": [int(x.timestamp()) for x in f["Date"]],
             "o": [float(x) for x in f["Open"]], "h": [float(x) for x in f["High"]],
             "l": [float(x) for x in f["Low"]], "c": [float(x) for x in f["Close"]],
             "v": [float(x) for x in f["Volume"]]}
        p = _disk_path(symbol, iv)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        with _gz.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(d, fh, separators=(",", ":"))
        os.replace(tmp, p)
    except Exception:                                          # noqa: BLE001
        pass                 # caching is best-effort, never fatal


def clear_kline_cache(disk: bool = True) -> None:
    """Forget cached candles — in memory and, by default, on disk (the
    archive months too: "cleared" must be true)."""
    _KLINE_CACHE.clear()
    if not disk:
        return
    try:
        for f in KLINE_DISK_DIR.rglob("*"):
            if f.is_file():
                f.unlink()
    except OSError:
        pass


def klines(symbol: str, interval: str = "Min5", limit: int = 300):
    """The newest `limit` candles as a Date/Open/High/Low/Close/Volume frame.
    Keyless. Fewer come back when the coin is younger, or when part of the
    stretch exists neither on REST nor in a published archive month."""
    iv = _iv(interval)
    per = PER_S[iv]
    key = (symbol, iv, int(limit))
    now = _now()
    hit = _KLINE_CACHE.get(key)
    if hit and now - hit[0] < _KLINE_TTL.get(iv, 150):
        return hit[1].copy()
    hi = int(now)
    lo = (hi - hi % per) - (int(limit) - 1) * per
    if limit <= _KLINE_PAGE:
        out = _rest_range(symbol, iv, lo, hi)
    else:
        cached = _disk_load(symbol, iv)
        if cached is not None and len(cached) >= limit:
            last = int(cached["Date"].iloc[-1].timestamp())
            out = _join(cached, _range(symbol, iv, last - 2 * per, hi))
        else:
            out = _join(cached, _range(symbol, iv, lo, hi))
        if len(out):
            _disk_save(symbol, iv, out)
        out = out.tail(int(limit)).reset_index(drop=True)
    if not len(out):
        raise GateFuturesError(f"no {interval} candles for {symbol}")
    _KLINE_CACHE[key] = (now, out)
    return out.copy()


def klines_page(symbol: str, interval: str, limit: int, end: int):
    """One page of up to `limit` bars opening at or before `end` (unix s),
    from REST or the archive. None when there is nothing."""
    iv = _iv(interval)
    per = PER_S[iv]
    lo = (int(end) - int(end) % per) - (int(limit) - 1) * per
    f = _range(symbol, iv, lo, int(end))
    return f if len(f) else None


def klines_backfill(symbol: str, interval: str, want: int):
    """At least `want` bars where they exist: the deep fetch `klines` already
    does (front from the archive), kept on disk."""
    return klines(symbol, interval, max(int(want), _KLINE_PAGE + 1))


def minutes(symbol: str, start_s: int, end_s: int):
    """The finest bars there are between two instants, for a v2 exit
    (spec D10): 1-minute bars from the archive and REST, and 5-minute bars
    ONLY over stretches where no minute exists (the current month before
    REST's last 6.9 days). No two bars share an instant. A `Seconds` column
    says which each bar is, so a row can count exits decided in a 5-minute
    bar."""
    import pandas as pd

    start_s, end_s = int(start_s), int(end_s)
    ones = _range(symbol, "1m", start_s, end_s)
    have = set(int(x) for x in _secs(ones)) if len(ones) else set()
    lo5 = start_s - start_s % 300
    holes = [t for t in range(lo5, end_s + 1, 300)
             if not any((t + 60 * k) in have for k in range(5))]
    parts = [ones.assign(Seconds=60)] if len(ones) else []
    if holes:
        f5 = _range(symbol, "5m", holes[0], holes[-1])
        if len(f5):
            t5 = _secs(f5)
            keep = f5[t5.isin(set(holes))].reset_index(drop=True)
            if len(keep):
                parts.append(keep.assign(Seconds=300))
    if not parts:
        return _empty().assign(Seconds=pd.Series(dtype="int64"))
    return (pd.concat(parts, ignore_index=True).sort_values("Date")
              .reset_index(drop=True))
