"""Signed MEXC futures (perpetual) client.

Separate from ``mexc_trade.py`` because the futures venue is a different host, a
different signing scheme, and carries leverage — a mistake here is amplified by
whatever multiple the position uses. Everything that can spend money takes an
explicit ``dry_run`` argument and defaults to refusing to trade.

Credentials come from ``MEXC_API_KEY`` / ``MEXC_API_SECRET`` in the environment
and are never accepted as function arguments, so a key cannot end up in a
traceback, a log line, or shell history. Create the key with futures trading
enabled, withdrawals DISABLED, and an IP allowlist.

Signing (futures v1, different from spot): the signed payload is
``accessKey + requestTime + parameterString`` where parameterString is the
sorted query string for GET/DELETE, or the exact JSON body for POST. The result
is HMAC-SHA256 hex, sent in the ``Signature`` header alongside ``ApiKey`` and
``Request-Time``.

NOTE ON ACCESS: MEXC has historically gated futures API order placement behind a
per-account permission. A key without it authenticates fine and then fails on
order submission. :func:`preflight` probes this explicitly so a bot discovers it
before it thinks it has a position.
"""

from __future__ import annotations

import gzip as _gzip
import hashlib
import hmac
import http.client
import json
import json as _json
import logging
import os
import pathlib as _pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

BASE = "https://contract.mexc.com"
_TIMEOUT = 20.0
_RECV_WINDOW_MS = 10_000
_UA = "tradingagents/0.3"

# Order sides on MEXC futures: 1 open-long, 2 close-short, 3 open-short, 4 close-long
SIDE_OPEN_LONG = 1
SIDE_CLOSE_SHORT = 2
SIDE_OPEN_SHORT = 3
SIDE_CLOSE_LONG = 4
# Order types: 1 limit, 5 market, 6 convert-to-market
TYPE_LIMIT = 1
TYPE_MARKET = 5
# Margin mode: 1 isolated, 2 cross
OPEN_ISOLATED = 1
OPEN_CROSS = 2

# Trigger-price basis for a resting stop. The backtest measures against MEXC's
# own last-trade candles, so TRIGGER_LAST is the only basis that reproduces it —
# fair and index price are manipulation-resistant but track a different series,
# which makes them a different strategy rather than a safer version of this one.
TRIGGER_LAST = 1
TRIGGER_FAIR = 2
TRIGGER_INDEX = 3
# What the resting stop becomes once triggered.
SL_MARKET = 0        # always exits; pays the spread
SL_LIMIT = 1         # exits at exactly the price, or not at all
# Whether the stop covers part of the position or all of it.
VOL_PARTIAL = 1
VOL_POSITION = 2


# MEXC answers permission problems with HTTP 200 and a code in the body, so a
# transport-level check never sees them. Each code maps to a specific checkbox
# on the exchange's API-key page; a generic "forbidden" message sends people
# hunting for the wrong setting.
PERMISSION_CODES = {
    701: ("read access",
          "On MEXC: API Management -> edit this key -> enable **Read** access."),
    703: ("trading information read",
          "On MEXC: API Management -> edit this key -> enable "
          "**Trading information / Read** (needed for positions and orders)."),
    704: ("trading information write",
          "On MEXC: API Management -> edit this key -> enable "
          "**Trading information / Write** (needed to place orders)."),
    705: ("withdrawal", "This key is being asked for a withdrawal scope — do "
                        "NOT enable it; trading does not require withdrawals."),
}
# Codes that mean the credentials or signature are wrong, not the scopes.
AUTH_CODES = {401, 402, 403, 1004, 2011}

# MEXC fronts the futures API with an edge proxy that refuses the ORDER paths
# outright for requests whose User-Agent looks like a scripted client — bare
# ``Python-urllib/*`` and ``python-requests/*`` both get an HTML "Access Denied"
# with HTTP 403, before the API (and therefore before any key check) sees them.
# Reads are unaffected, which makes the failure look exactly like a missing
# trade permission. It is not: the same request with this module's own
# User-Agent is accepted. Detect it explicitly so nobody re-diagnoses this as a
# key-scope problem and goes hunting on the wrong settings page.
EDGE_BLOCK_REMEDY = (
    "MEXC's edge proxy rejected the request before it reached the API. This "
    "happens when the User-Agent identifies a scripted HTTP client. Send "
    f"requests through this module (User-Agent {_UA!r}) rather than a bare "
    "urllib/requests default, and check no proxy is rewriting the header.")



class MexcFuturesError(RuntimeError):
    """A futures request could not be made or was rejected by the exchange."""


class MexcFuturesAuthFailed(MexcFuturesError):
    """The key, the secret, the clock or the source IP is wrong.

    Deliberately NOT a :class:`MexcFuturesForbidden` subclass, for the same
    reason as :class:`MexcFuturesEdgeBlocked`: no checkbox on MEXC's API-key page
    fixes a bad signature. Reporting these as a missing scope sent people to the
    wrong settings screen — and it printed "missing scope: code None", because
    there was no scope to name.
    """

    REMEDY = (
        "MEXC rejected the credentials themselves, not their permissions. Check, "
        "in this order: the secret was pasted in full (editing a key's scopes can "
        "issue a NEW secret); this machine's clock is accurate to within a few "
        "seconds; and the key's IP allowlist includes this machine's current "
        "public IP. No permission setting will change this.")

    def __init__(self, message: str, *, code=None):
        super().__init__(message)
        self.code = code
        self.remedy = self.REMEDY


class MexcFuturesEdgeBlocked(MexcFuturesError):
    """Blocked by MEXC's edge proxy, never reaching the API.

    Deliberately NOT a subclass of :class:`MexcFuturesForbidden`: this is not a
    key-permission failure, and conflating the two is what sent an earlier
    version of this code looking for a checkbox that was already ticked.
    """

    def __init__(self, path: str):
        super().__init__(f"edge proxy denied {path} — {EDGE_BLOCK_REMEDY}")
        self.path = path
        self.remedy = EDGE_BLOCK_REMEDY


class MexcFuturesForbidden(MexcFuturesError):
    """Authenticated fine, but this key lacks a permission the call needs.

    Carries the MEXC code, the missing scope, and the exact remedy so a caller
    can tell the user which setting to change rather than "permission denied".
    """

    def __init__(self, message: str, code: int | None = None,
                 scope: str | None = None, remedy: str | None = None):
        super().__init__(message)
        self.code = code
        self.scope = scope
        self.remedy = remedy


def credentials() -> tuple[str | None, str | None]:
    key = os.getenv("MEXC_API_KEY", "").strip() or None
    secret = os.getenv("MEXC_API_SECRET", "").strip() or None
    return key, secret


def has_credentials() -> bool:
    return all(credentials())


def _param_string(params: dict | None, body: dict | list | None) -> str:
    """The exact string that gets signed — sorted query, or verbatim JSON body."""
    if body is not None:
        # A list body (order/cancel takes an array of ids) has no keys to sort;
        # sort_keys applies only to the dict case.
        return json.dumps(body, separators=(",", ":"),
                          sort_keys=isinstance(body, dict))
    if not params:
        return ""
    return urllib.parse.urlencode(sorted(params.items()))


def sign(key: str, secret: str, ts_ms: str,
         params: dict | None = None,
         body: dict | list | None = None) -> str:
    """HMAC-SHA256 hex of ``key + timestamp + parameterString``."""
    target = f"{key}{ts_ms}{_param_string(params, body)}"
    return hmac.new(secret.encode(), target.encode(), hashlib.sha256).hexdigest()


def _classify(code, msg: str, http_status: int | None = None):
    """Turn an exchange code into the right exception, or None to pass through.

    Both failure branches route through here. They used to classify
    independently, and the HTTP branch discarded the code one line after reading
    it, so every 401/403 became ``MexcFuturesForbidden`` with code, scope and
    remedy all None — which ``preflight`` then rendered as the missing scope
    "code None".
    """
    if code in PERMISSION_CODES:
        scope, remedy = PERMISSION_CODES[code]
        return MexcFuturesForbidden(
            f"{msg} (code {code}) — missing scope: {scope}",
            code=code, scope=scope, remedy=remedy)
    if code in AUTH_CODES or "signature" in msg.lower() or "sign " in msg.lower():
        return MexcFuturesAuthFailed(f"code {code or http_status}: {msg}",
                                     code=code or http_status)
    return None


def _request(method: str, path: str, *, params: dict | None = None,
             body: dict | list | None = None):
    key, secret = credentials()
    if not (key and secret):
        raise MexcFuturesError(
            "MEXC_API_KEY / MEXC_API_SECRET are not set in the environment.")
    ts = str(int(time.time() * 1000))
    sig = sign(key, secret, ts, params, body)
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(sorted(params.items()))
    data = None
    headers = {
        "ApiKey": key,
        "Request-Time": ts,
        "Signature": sig,
        "Recv-Window": str(_RECV_WINDOW_MS),
        "User-Agent": _UA,
    }
    if body is not None:
        data = _param_string(None, body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        text = (raw or b"").decode("utf-8", "replace")
        if exc.code == 403 and ("Access Denied" in text or "<HTML" in text.upper()):
            raise MexcFuturesEdgeBlocked(path) from exc
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            payload = {"message": text[:200]}
        msg = str(payload.get("message") or payload.get("msg") or exc)
        # The body carries the real code; exc.code is only the HTTP status.
        code = payload.get("code")
        if code is None and exc.code in AUTH_CODES:
            code = exc.code
        err = _classify(code, msg, http_status=exc.code)
        if err is not None:
            raise err from exc
        if "permission" in msg.lower():
            raise MexcFuturesForbidden(f"{exc.code}: {msg}") from exc
        raise MexcFuturesError(f"{exc.code}: {msg}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise MexcFuturesError(f"transport failure: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MexcFuturesError("malformed response from MEXC") from exc
    if not payload.get("success", False):
        code = payload.get("code")
        msg = payload.get("message") or payload.get("msg") or "rejected"
        err = _classify(code, str(msg))
        if err is not None:
            raise err
        raise MexcFuturesError(f"code {code}: {msg}")
    return payload.get("data")


def server_time_ms() -> int:
    """MEXC's clock, from the keyless ping endpoint."""
    return int(_get_public(f"{BASE}/api/v1/contract/ping").get("data") or 0)


def clock_skew_ms() -> int:
    """How far this machine's clock is from MEXC's, in milliseconds.

    Every signed request carries Request-Time and is validated against a receive
    window. A laptop that has been asleep, or whose NTP has drifted, gets every
    request rejected — and MEXC reports that as an auth failure, which reads
    exactly like a wrong secret. Measuring it turns an afternoon of debugging
    into one line of output.
    """
    return int(time.time() * 1000) - server_time_ms()


# A keyless GET is idempotent, so a failure of the WIRE is simply tried again.
# 2026-08-25: MEXC closed one connection after 183,452 bytes of a CHILLGUY_USDT
# Min15 kline page. That is http.client.IncompleteRead — an HTTPException the
# except clauses below did not even name — and a 4,985-pair download lost the
# pair for good while the same endpoint served the other 4,983. Three attempts
# with a breath between them; the budget stays small because the live runner
# walks through here every cycle (3 x _TIMEOUT + backoff, under 90 s).
_PUBLIC_RETRIES = 3
_PUBLIC_BACKOFF = (1.0, 2.0)                  # seconds before attempt 2, 3, ...
# No redo starts after this much wall-clock has gone: a cut connection fails
# in milliseconds and gets all three attempts, a dead network burns _TIMEOUT
# per attempt and gets one redo, so the runner's cycle is held for at most
# _PUBLIC_RETRY_BUDGET_S + _TIMEOUT + backoff (~53 s), not 3 x _TIMEOUT per coin.
_PUBLIC_RETRY_BUDGET_S = 30.0
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_retry_sleep = time.sleep
_clock = time.monotonic


def _no_more_tries(attempt: int, t0: float) -> bool:
    """Was that the last attempt — by count, or by wall-clock spent?"""
    return attempt >= _PUBLIC_RETRIES or _clock() - t0 >= _PUBLIC_RETRY_BUDGET_S


def _get_public(url: str):
    """Keyless GET that raises this module's exceptions, not urllib's, and
    retries a failed WIRE — cut connection, timeout, 5xx, 429 — up to
    _PUBLIC_RETRIES times. A 4xx is an answer and is not retried. Never used
    for signed calls: a second order submit is a second order.

    The keyless helpers used to call ``urlopen`` bare, so they raised
    ``urllib.error.HTTPError``. ``spx_bot.step()`` calls two of them outside any
    handler, so a single transient 503 fell through to the catch-all, halted the
    process, and left a levered position with no stop being monitored.
    """
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    t0 = _clock()
    for attempt in range(1, _PUBLIC_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                raw = resp.read()
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code == 403 and ("Access Denied" in body or "<HTML" in body.upper()):
                raise MexcFuturesEdgeBlocked(url) from exc
            if exc.code not in _RETRY_STATUSES or _no_more_tries(attempt, t0):
                raise MexcFuturesError(f"{exc.code}: {body[:200]}") from exc
        except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
            if _no_more_tries(attempt, t0):
                raise MexcFuturesError(
                    f"transport failure: {exc} after {attempt} attempts") from exc
        _retry_sleep(_PUBLIC_BACKOFF[min(attempt - 1, len(_PUBLIC_BACKOFF) - 1)])
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MexcFuturesError(f"malformed response from {url}") from exc


def assets() -> dict:
    """Futures wallet balances keyed by currency."""
    data = _request("GET", "/api/v1/private/account/assets") or []
    return {a.get("currency"): a for a in data if isinstance(a, dict)}


def usdt_equity() -> float:
    a = assets().get("USDT") or {}
    return float(a.get("equity") or a.get("availableBalance") or 0.0)


def open_positions(symbol: str | None = None) -> list:
    params = {"symbol": symbol} if symbol else None
    return _request("GET", "/api/v1/private/position/open_positions",
                    params=params) or []


def position_history(symbol: str | None = None, page_size: int = 20) -> list:
    """Recently closed positions, newest first — the exchange's own realized
    PnL per position. The auto-trader reads this when a position vanished
    without its bracket being crossed (e.g. the operator closed it by hand),
    so the ledger records the REAL result instead of an estimate."""
    params: dict = {"page_num": 1, "page_size": int(page_size)}
    if symbol:
        params["symbol"] = symbol
    return _request("GET", "/api/v1/private/position/list/history_positions",
                    params=params) or []


# Contract metadata is STATIC — size, tick and leverage bounds do not move
# during a session — so it is cached for an hour. Before this it was re-read on
# every entry, every bracket and every fee lookup, which is a large share of
# the request budget for a number that never changes.
_SPEC_CACHE: dict = {}
_SPEC_TTL = 3600


def clear_spec_cache() -> None:
    _SPEC_CACHE.clear()


def contract_spec(symbol: str) -> dict:
    """Keyless contract metadata — contract size, tick, leverage bounds.

    NEVER returns an empty dict as if it were an answer. MEXC replies to a rate
    limit (code 510) and to a maintenance window with HTTP 200 and no ``data``
    key, and the old ``payload.get("data") or {}`` handed that back as a spec.
    Callers then read ``contractSize`` as 0.0 — which is not a contract size,
    it is a missing reply. Cost, measured: on 2026-08-18 at 19:00 an ALICE
    entry signal died with ``cannot size ALICE_USDT: contractSize=0.0`` in both
    books while the real contract size is 0.1, and because the candle had
    already been marked seen the signal was never retried. Same failure and the
    same fix as ``last_price`` (see its docstring): an unreadable value is an
    ERROR, not a number.

    Served from a 1-hour cache, so a rate limit cannot empty a spec that was
    already read successfully.
    """
    now = time.time()
    hit = _SPEC_CACHE.get(symbol)
    if hit and now - hit[0] < _SPEC_TTL:
        return hit[1]
    url = f"{BASE}/api/v1/contract/detail?symbol={urllib.parse.quote(symbol)}"
    payload = _get_public(url)
    d = payload.get("data") or {}
    if isinstance(d, list):
        d = d[0] if d else {}
    if not isinstance(d, dict) or not d.get("symbol"):
        raise MexcFuturesError(
            f"contract detail for {symbol} carried no data "
            f"(code={payload.get('code')} msg={payload.get('message')!r}) — "
            f"refusing to report a contract with no size")
    _SPEC_CACHE[symbol] = (now, d)
    return d


def last_price(symbol: str) -> float:
    """The last traded price. NEVER returns 0.0 as if it were a price.

    MEXC answers a rate limit (code 510) or a maintenance window with HTTP
    200 and no ``data`` key, so the old ``float(d.get("lastPrice") or 0.0)``
    handed callers a silent 0.0. A price of zero is below every short's
    take-profit and below every long's stop, so the paper book booked
    fabricated wins on shorts and fabricated losses on longs — PROVE_USDT was
    recorded as three take-profit wins (+$13.50) on 2026-08-12/13 while the
    market never traded within 4% of the target. An unreadable price is an
    ERROR, not a number.
    """
    url = f"{BASE}/api/v1/contract/ticker?symbol={urllib.parse.quote(symbol)}"
    payload = _get_public(url)
    d = payload.get("data") or {}
    if isinstance(d, list):
        d = d[0] if d else {}
    raw = d.get("lastPrice")
    if raw is None:
        raise MexcFuturesError(
            f"ticker for {symbol} carried no lastPrice "
            f"(code={payload.get('code')} msg={payload.get('message')!r})")
    px = float(raw)
    if not px > 0:
        raise MexcFuturesError(f"ticker for {symbol} reported price {px!r}")
    return px


def contracts_for(symbol: str, notional_usd: float,
                  price: float | None = None) -> int:
    """How many contracts approximate ``notional_usd`` of exposure.

    Rounded DOWN so a sizing error can never overshoot the intended exposure.
    """
    spec = contract_spec(symbol)
    size = float(spec.get("contractSize") or 0.0)
    px = price if price is not None else last_price(symbol)
    if size <= 0 or px <= 0:
        raise MexcFuturesError(f"cannot size {symbol}: contractSize={size} px={px}")
    per_contract = size * px
    return int(notional_usd // per_contract)


def order_book(symbol: str) -> dict:
    """Live depth for a contract: {"bids": [[price, contracts], ...], "asks": ...}."""
    url = f"{BASE}/api/v1/contract/depth/{urllib.parse.quote(symbol)}"
    d = _get_public(url).get("data") or {}
    return {
        "bids": [[float(x[0]), float(x[1])] for x in (d.get("bids") or [])],
        "asks": [[float(x[0]), float(x[1])] for x in (d.get("asks") or [])],
    }


def book_cost(symbol: str, notional_usd: float = 200.0) -> dict:
    """What it ACTUALLY costs to trade this contract, measured from the book.

    Walks the live asks to fill ``notional_usd`` and reports the average fill
    price versus mid. This is the number a backtest silently assumes is zero —
    on 2026-08-12 a strategy targeting 0.36% was run on a contract whose
    spread alone was 1.56%, which no edge can survive.

    Returns slippage/spread as FRACTIONS (0.0156 == 1.56%).
    """
    book = order_book(symbol)
    asks, bids = book["asks"], book["bids"]
    if not asks or not bids:
        raise MexcFuturesError(f"no order book for {symbol}")
    mid = (asks[0][0] + bids[0][0]) / 2.0
    size = float(contract_spec(symbol).get("contractSize") or 0.0)
    if size <= 0 or mid <= 0:
        raise MexcFuturesError(f"cannot measure {symbol}: size={size} mid={mid}")
    want = notional_usd / (size * mid)
    need, cost, got = want, 0.0, 0.0
    for px, vol in asks:
        take = min(need, vol)
        cost += take * px
        got += take
        need -= take
        if need <= 0:
            break
    if got <= 0:
        raise MexcFuturesError(f"empty book for {symbol}")
    slippage = cost / got / mid - 1.0
    exhausted = need > 0
    if exhausted:
        # The whole visible book cannot fill this order; the true cost is
        # worse than anything measurable here.
        slippage = max(slippage, asks[-1][0] / mid - 1.0)
    return {
        "symbol": symbol,
        "mid": mid,
        "spread": (asks[0][0] - bids[0][0]) / mid,
        "slippage": slippage,
        "book_exhausted": exhausted,
        "notional_tested": notional_usd,
    }


# ---------------------------------------------------------------- preflight
def write_probe() -> dict:
    """Prove the key may write to the order endpoint WITHOUT risking a trade.

    Cancels order id 1, which cannot exist (MEXC ids are 18-digit snowflakes).
    The endpoint is the same permission-gated order path a real trade uses, so
    reaching it proves both the ``trading information write`` scope and that the
    edge proxy let the request through — but the request describes no
    instrument, no size and no side, so there is no reachable code path in which
    it opens a position.

    This replaced a probe that submitted a real order with ``vol=0`` and relied
    on MEXC to reject it. That probe was one validation-rule change away from
    opening a position on someone's account, which is not a risk a *connection
    test* is allowed to take.
    """
    data = _request("POST", "/api/v1/private/order/cancel", body=[1])
    return {"reached": True, "response": data}


def preflight(symbol: str) -> dict:
    """Check what this key can actually do, before any bot trusts it.

    Returns a report rather than raising, so a caller can print it and stop.
    """
    report = {"credentials": has_credentials(), "read_assets": False,
              "read_positions": False, "order_permission": None,
              "equity_usdt": None, "notes": [], "missing_scopes": [],
              "remedies": [], "edge_blocked": False,
              "auth_failed": False, "can_rest_stop": None,
              "clock_ok": None, "clock_skew_ms": None, "ready": False}
    if not report["credentials"]:
        report["notes"].append("MEXC_API_KEY / MEXC_API_SECRET not set")
        return report
    try:
        skew = clock_skew_ms()
        report["clock_skew_ms"] = skew
        if abs(skew) > _RECV_WINDOW_MS / 2:
            report["clock_ok"] = False
            report["remedies"].append(
                f"This machine's clock is {skew / 1000:+.1f}s away from MEXC's. "
                f"Signed requests are validated against a "
                f"{_RECV_WINDOW_MS / 1000:.0f}s window, so they will be rejected "
                f"as auth failures. Fix the system clock (macOS: System "
                f"Settings -> General -> Date & Time -> Set automatically).")
            report["notes"].append(f"clock skew {skew}ms — too large")
        else:
            report["clock_ok"] = True
    except MexcFuturesError as exc:
        report["notes"].append(f"could not check the clock: {exc}")
    try:
        report["equity_usdt"] = usdt_equity()
        report["read_assets"] = True
    except MexcFuturesAuthFailed as exc:
        report["auth_failed"] = True
        report["remedies"].append(exc.remedy)
    except MexcFuturesForbidden as exc:
        # Only name a scope MEXC actually named. Synthesising one from a status
        # code produced the message "missing scope: code None".
        if exc.scope:
            report["missing_scopes"].append(exc.scope)
            report["remedies"].append(exc.remedy or str(exc))
        report["notes"].append(f"cannot read balance: {exc}")
    except MexcFuturesError as exc:
        report["notes"].append(f"assets failed: {exc}")
    try:
        open_positions(symbol)
        report["read_positions"] = True
    except MexcFuturesAuthFailed as exc:
        report["auth_failed"] = True
        report["remedies"].append(exc.remedy)
    except MexcFuturesForbidden as exc:
        # Only name a scope MEXC actually named. Synthesising one from a status
        # code produced the message "missing scope: code None".
        if exc.scope:
            report["missing_scopes"].append(exc.scope)
            report["remedies"].append(exc.remedy or str(exc))
        report["notes"].append(f"cannot read positions: {exc}")
    except MexcFuturesError as exc:
        report["notes"].append(f"positions failed: {exc}")
    # Order permission is probed by cancelling an id that cannot exist — see
    # write_probe(). 704 must NOT be read as success: an earlier version treated
    # it as "endpoint reachable" and reported the permission as granted when the
    # key could not trade at all.
    try:
        write_probe()
        report["order_permission"] = True
        report["notes"].append("order endpoint accepts writes from this key")
    except MexcFuturesEdgeBlocked as exc:
        report["order_permission"] = False
        report["edge_blocked"] = True
        report["remedies"].append(exc.remedy)
        report["notes"].append(f"cannot place orders: {exc}")
    except MexcFuturesAuthFailed as exc:
        report["order_permission"] = False
        report["auth_failed"] = True
        report["remedies"].append(exc.remedy)
        report["notes"].append(f"cannot place orders: {exc}")
    except MexcFuturesForbidden as exc:
        report["order_permission"] = False
        if exc.scope:
            report["missing_scopes"].append(exc.scope)
            report["remedies"].append(exc.remedy or str(exc))
        report["notes"].append(f"cannot place orders: {exc}")
    except MexcFuturesError as exc:
        report["order_permission"] = False
        report["notes"].append(f"order write probe failed: {exc}")
    # The write probe above tests order/cancel. Resting a stop is a DIFFERENT
    # endpoint, and a key can pass one and fail the other — which would only be
    # discovered at the moment a stop was needed.
    if report["order_permission"]:
        st = stop_probe()
        report["can_rest_stop"] = bool(st.get("permitted"))
        if st.get("permitted"):
            report["notes"].append(f"can rest a stop on MEXC ({st['reason']})")
        else:
            report["notes"].append(
                f"cannot rest a stop ({st.get('blocked_by')}): {st.get('reason')}")
            if st.get("remedy"):
                report["remedies"].append(st["remedy"])
    report["missing_scopes"] = sorted(set(report["missing_scopes"]))
    report["remedies"] = list(dict.fromkeys(report["remedies"]))
    report["ready"] = bool(report["read_assets"] and report["read_positions"]
                           and report["order_permission"]
                           and report["can_rest_stop"]
                           and report["clock_ok"] is not False)
    return report


# ---------------------------------------------------------------- trading
def submit(symbol: str, side: int, vol: int, *, leverage: int,
           order_type: int = TYPE_MARKET, price: float | None = None,
           open_type: int = OPEN_ISOLATED, dry_run: bool = True) -> dict:
    """Place one futures order. ``dry_run=True`` returns the payload unsent.

    Nothing here is retried: a timed-out order may or may not have reached the
    exchange, and blindly resending it is how a bot ends up with double the
    intended position. The caller must reconcile against open_positions().
    """
    if vol <= 0:
        raise MexcFuturesError(f"refusing to submit vol={vol}")
    body = {"symbol": symbol, "vol": int(vol), "side": int(side),
            "type": int(order_type), "openType": int(open_type),
            "leverage": int(leverage)}
    if order_type == TYPE_LIMIT:
        if not price:
            raise MexcFuturesError("a limit order needs a price")
        body["price"] = float(price)
    if dry_run:
        logger.info("DRY RUN futures order: %s", body)
        return {"dry_run": True, "request": body}
    logger.warning("LIVE futures order: %s", body)
    data = _request("POST", "/api/v1/private/order/submit", body=body)
    return {"dry_run": False, "request": body, "response": data}


def open_long(symbol: str, vol: int, *, leverage: int,
              dry_run: bool = True) -> dict:
    return submit(symbol, SIDE_OPEN_LONG, vol, leverage=leverage,
                  dry_run=dry_run)


def close_long(symbol: str, vol: int, *, leverage: int,
               dry_run: bool = True) -> dict:
    return submit(symbol, SIDE_CLOSE_LONG, vol, leverage=leverage,
                  dry_run=dry_run)


def limit_close_long(symbol: str, vol: int, price: float, *, leverage: int,
                     dry_run: bool = True) -> dict:
    """Take-profit as a LIMIT order — the backtested edge depends on it.

    A market exit gives back roughly 25bp per trade, which is the entire
    measured advantage of the barriers, so the target must rest as a maker.
    """
    return submit(symbol, SIDE_CLOSE_LONG, vol, leverage=leverage,
                  order_type=TYPE_LIMIT, price=price, dry_run=dry_run)


# --------------------------------------------------- exchange-resting stops
# Why this endpoint and not the alternatives, all three of which MEXC documents:
#
# * ``order/create`` takes stopLossPrice at entry, but MEXC only materialises the
#   stop AFTER the parent order fully fills, and binds it to that one order. Scale
#   into a position and the added size carries no stop at all.
# * ``planorder/place/v2`` requires ``executeCycle``, documented only as 24 hours
#   or 7 days. A stop that silently expires is worse than no stop, because you
#   believe you have one.
# * ``stoporder/place`` attaches to the POSITION, never expires, and is the only
#   path exposing stopLossType — i.e. the only one where market-vs-limit is a
#   choice rather than an undocumented default.
def place_position_stop(symbol: str, position_id: int, vol: int, *,
                        stop_loss_price: float,
                        take_profit_price: float | None = None,
                        stop_loss_type: int = SL_MARKET,
                        stop_loss_order_price: float | None = None,
                        take_profit_type: int = SL_MARKET,
                        take_profit_order_price: float | None = None,
                        trend: int = TRIGGER_LAST,
                        vol_type: int = VOL_POSITION,
                        dry_run: bool = True) -> dict:
    """Rest a stop (and optionally a take-profit) on MEXC's servers.

    This is the whole point of the exercise: once placed, the exit no longer
    depends on this process, this machine, or this internet connection. A stop
    enforced by a polling loop protects nothing while the laptop is asleep.

    ``stop_loss_type=SL_LIMIT`` reproduces the backtest exactly, which assumes a
    fill at the stop price — but a limit that cannot fill leaves the position
    open in a falling market, so SL_MARKET is the default. Measured cost of that
    choice on 188 days of SPX500 data: $0.33.
    """
    if vol <= 0:
        raise MexcFuturesError(f"refusing to place a stop for vol={vol}")
    if stop_loss_price <= 0:
        raise MexcFuturesError("stop_loss_price must be positive")
    if stop_loss_type == SL_LIMIT and not stop_loss_order_price:
        raise MexcFuturesError(
            "a limit stop needs stop_loss_order_price — without it MEXC has no "
            "price to rest the exit order at")
    # MEXC's field rules here are asymmetric between the two barriers and are
    # not stated in the docs. Established by probing every combination against a
    # position id that cannot exist, so an invalid payload answers 600/5001 while
    # a valid one answers 2009 "position is nonexistent":
    #
    #   limit  take-profit -> takeProfitOrderPrice ONLY. Sending takeProfitPrice
    #                         as well is rejected live with
    #                         "code 600: takeProfitPrice and takeProfitOrderPrice
    #                         cannot be set at the same time", and sending only
    #                         takeProfitPrice with type=1 answers 5001, i.e. the
    #                         field is ignored entirely for the limit type.
    #   market take-profit -> takeProfitPrice ONLY.
    #   limit  stop        -> stopLossPrice (the trigger) AND stopLossOrderPrice
    #                         (where the exit rests). Either alone answers 5001.
    #   market stop        -> stopLossPrice ONLY.
    body: dict = {
        "symbol": symbol,
        "positionId": int(position_id),
        "vol": int(vol),
        "lossTrend": int(trend),
        "profitTrend": int(trend),
        "stopLossPrice": float(stop_loss_price),
        "stopLossType": int(stop_loss_type),
        "volType": int(vol_type),
    }
    if stop_loss_type == SL_LIMIT:
        body["stopLossOrderPrice"] = float(stop_loss_order_price)
    if take_profit_price:
        if take_profit_type == SL_LIMIT:
            # MEXC ACCEPTS this and attaches nothing. Verified against a real
            # position: the payload returned success and the resulting record
            # read back "tp=None tpType=None" with only the stop attached. A
            # take-profit that silently does not exist is the worst possible
            # failure here, so refuse it and make the caller use a resting limit
            # close order instead (see limit_close_long).
            raise MexcFuturesError(
                "MEXC silently ignores a LIMIT take-profit on a position TP/SL "
                "record — it returns success and attaches only the stop. Place "
                "the target as a resting limit close order instead.")
        body["takeProfitType"] = int(take_profit_type)
        body["takeProfitPrice"] = float(take_profit_price)
    if dry_run:
        logger.info("DRY RUN resting stop: %s", body)
        return {"dry_run": True, "request": body}
    logger.warning("LIVE resting stop: %s", body)
    data = _request("POST", "/api/v1/private/stoporder/place", body=body)
    return {"dry_run": False, "request": body, "response": data}


def stop_probe() -> dict:
    """Can this key rest a stop on the exchange? Answered without a position.

    Sends a well-formed request against position id 1, which cannot exist (MEXC
    ids are 18-digit snowflakes). A JSON rejection means the endpoint and the
    key's permissions are both fine and only the position was missing; a
    permission code or an edge block means the whole exchange-side-stop plan is
    unavailable on this key and must be discovered NOW rather than at the moment
    a stop is needed.

    ``preflight``'s existing write probe tests order/cancel, which is a
    different permission surface — passing it does not prove a stop can be
    placed.
    """
    try:
        data = _request("POST", "/api/v1/private/stoporder/place", body={
            "symbol": "SPX500_USDT", "positionId": 1, "vol": 1,
            "lossTrend": TRIGGER_LAST, "profitTrend": TRIGGER_LAST,
            "stopLossPrice": 1.0, "stopLossType": SL_MARKET,
            "volType": VOL_POSITION})
        return {"permitted": True, "reason": "accepted (no position to attach to)",
                "response": data}
    except MexcFuturesEdgeBlocked as exc:
        return {"permitted": False, "blocked_by": "edge proxy",
                "reason": str(exc), "remedy": exc.remedy}
    except MexcFuturesForbidden as exc:
        return {"permitted": False, "blocked_by": "key scope",
                "reason": str(exc), "remedy": exc.remedy}
    except MexcFuturesAuthFailed as exc:
        return {"permitted": False, "blocked_by": "credentials",
                "reason": str(exc), "remedy": exc.remedy}
    except MexcFuturesError as exc:
        # A validation rejection is the SUCCESS case: MEXC read the request,
        # authorised it, and only then found position 1 missing.
        return {"permitted": True, "reason": f"validation rejection: {exc}"}


# Observed on this account: two of three historical TP/SL records finished with
# errorCode 8912 and vol 0, i.e. MEXC accepted the request and the stop still
# never became active. A bot that treats a 200 OK as protection is wrong.
STOP_STATE_ACTIVE = {1, 2}          # 1 uninformed, 2 uncompleted/working


def stop_is_active(record: dict) -> bool:
    """Is this TP/SL record actually protecting the position right now?"""
    if int(record.get("errorCode") or 0) != 0:
        return False
    if int(record.get("isFinished") or 0) == 1:
        return False
    return int(record.get("state") or 0) in STOP_STATE_ACTIVE


def verify_position_stop(symbol: str, position_id: int) -> dict:
    """Read back what the exchange actually holds for this position.

    Called after every placement. Without it, ``place_position_stop`` returning
    success is only evidence that the request was accepted — see errorCode 8912
    above.
    """
    records = [r for r in list_position_stops(symbol)
               if str(r.get("positionId")) == str(position_id)]
    active = [r for r in records if stop_is_active(r)]
    failed = [r for r in records if int(r.get("errorCode") or 0) != 0]
    return {"protected": bool(active), "active": active, "failed": failed,
            "error_codes": sorted({int(r.get("errorCode") or 0)
                                   for r in failed})}


def open_orders(symbol: str | None = None) -> list:
    """Resting (unfilled) orders — this is where the take-profit lives."""
    params = {"symbol": symbol} if symbol else None
    return _request("GET", "/api/v1/private/order/list/open_orders",
                    params=params) or []


def cancel_all_orders(symbol: str) -> dict:
    """Cancel every resting order on a symbol.

    Needed after the exchange closes a position: the take-profit rests as its own
    order, so when the STOP fires the target can be left behind. It is a
    close-long order and therefore cannot open a short, but a stale order on the
    books is still a surprise waiting to happen.
    """
    return {"response": _request("POST", "/api/v1/private/order/cancel_all",
                                 body={"symbol": symbol})}


def verify_bracket(symbol: str, position_id: int, take_profit_price=None) -> dict:
    """Is this position ACTUALLY protected on both sides right now?

    The two barriers live in different places — the stop on the position TP/SL
    record, the target as a resting limit close order — so both have to be read
    back separately. Neither placement returning success is evidence: MEXC has
    accepted stop records that finished with errorCode 8912 and never activated,
    and it accepts limit take-profits on the position record while attaching
    nothing at all.
    """
    stop = verify_position_stop(symbol, position_id)
    target = None
    if take_profit_price:
        for o in open_orders(symbol):
            if int(o.get("side") or 0) == SIDE_CLOSE_LONG and \
                    abs(float(o.get("price") or 0) - float(take_profit_price)) < 1e-6:
                target = o
                break
    return {"stop_active": stop["protected"],
            "target_resting": target is not None,
            "protected": stop["protected"] and (target is not None
                                                if take_profit_price else True),
            "stop_error_codes": stop["error_codes"],
            "target_order_id": (target or {}).get("orderId")}


def list_position_stops(symbol: str | None = None) -> list:
    """Resting TP/SL records, so a bot can verify its stop is really there."""
    params = {"symbol": symbol} if symbol else None
    return _request("GET", "/api/v1/private/stoporder/list/orders",
                    params=params) or []


# ---------------------------------------------------------------- discovery
def list_contracts(quote: str = "USDT") -> list[dict]:
    """All tradeable perpetuals, newest-liquid first. Keyless.

    Only contracts whose API flag is set are returned — a contract the key
    cannot trade has no business appearing in a picker.
    """
    url = f"{BASE}/api/v1/contract/detail"
    payload = _get_public(url)
    out = []
    for c in payload.get("data") or []:
        sym = c.get("symbol") or ""
        if quote and not sym.endswith(f"_{quote}"):
            continue
        if c.get("apiAllowed") is False:
            continue
        out.append({
            "symbol": sym,
            "display": c.get("displayNameEn") or c.get("displayName") or sym,
            "contract_size": float(c.get("contractSize") or 0.0),
            "max_leverage": int(c.get("maxLeverage") or 1),
            "vol_unit": float(c.get("volUnit") or 1),
            "min_vol": float(c.get("minVol") or 1),
            "price_unit": float(c.get("priceUnit") or 0.0001),
        })
    out.sort(key=lambda c: c["symbol"])
    return out


# Candles cannot change meaningfully inside half a bar, so re-fetching them
# faster than that is pure waste. A bot racing 7 lanes was issuing 480 kline
# requests an hour, each for 400 candles, and the order endpoints on this account
# have already answered "code 510: Requests are too frequent".
# Capped at 5 minutes even for coarse intervals: the UI charts share this
# function, and a 12-hour TTL on Day1 bars would show a chart half a day stale
# while the caption claimed it was the last price.
_KLINE_CACHE: dict = {}

KLINE_DISK_DIR = (_pathlib.Path.home() / ".tradingagents" / "kline_cache")
_KLINE_TTL_CAP = 300
_KLINE_PAGE = 2000            # MEXC's per-request ceiling is 2001; stay under it
_KLINE_TTL = {"Min1": 30, "Min5": 150, "Min15": 300, "Min30": 300,
              "Min60": 300, "Hour4": 300, "Day1": 300}


def clear_kline_cache(disk: bool = True) -> None:
    """Forget cached candles — in memory and, by default, on disk.

    The disk cache made a unit test read real candles saved by an earlier run
    (5,000 bars where the test served 500), and the same leak would let a stale
    file answer a backtest. Anything that clears the cache must clear both, or
    "cleared" is not true.
    """
    _KLINE_CACHE.clear()
    if not disk:
        return
    try:
        for f in KLINE_DISK_DIR.glob("*.json"):
            f.unlink()
    except OSError:
        pass


def _klines_page(symbol: str, interval: str, limit: int, end: int):
    """One page of candles ending at ``end`` (unix seconds). No caching."""
    import pandas as pd

    per = {"Min1": 60, "Min5": 300, "Min15": 900, "Min30": 1800,
           "Min60": 3600, "Hour4": 14400, "Day1": 86400}.get(interval, 300)
    url = (f"{BASE}/api/v1/contract/kline/{urllib.parse.quote(symbol)}?"
           + urllib.parse.urlencode({"interval": interval,
                                     "start": end - per * limit, "end": end}))
    d = (_get_public(url).get("data") or {})
    if not d.get("time"):
        return None
    return pd.DataFrame({
        "Date": pd.to_datetime(d["time"], unit="s", utc=True).tz_localize(None),
        "Open": [float(x) for x in d["open"]],
        "High": [float(x) for x in d["high"]],
        "Low": [float(x) for x in d["low"]],
        "Close": [float(x) for x in d["close"]],
        "Volume": [float(x) for x in d.get("vol", [0] * len(d["time"]))],
    })


# Closed candles never change, so the long histories the sweeps page down are
# kept on disk and only the tail is refetched. JSON+gzip of plain columns —
# no parquet dependency — capped so a file never grows past ~40k bars.

_KLINE_DISK_MAX = 40_000


def _kline_disk_path(symbol: str, interval: str) -> _pathlib.Path:
    safe = "".join(c for c in f"{symbol}_{interval}"
                   if c.isalnum() or c in "_-")
    return KLINE_DISK_DIR / f"{safe}.json.gz"


def _kline_disk_load(symbol: str, interval: str):
    import pandas as pd

    try:
        p = _kline_disk_path(symbol, interval)
        if not p.exists():
            return None
        with _gzip.open(p, "rt", encoding="utf-8") as fh:
            d = _json.load(fh)
        if not d.get("t"):
            return None
        return pd.DataFrame({
            "Date": pd.to_datetime(d["t"], unit="s", utc=True)
                      .tz_localize(None),
            "Open": d["o"], "High": d["h"], "Low": d["l"],
            "Close": d["c"], "Volume": d["v"],
        })
    except Exception:
        return None          # a corrupt cache must never break a fetch


def _kline_disk_save(symbol: str, interval: str, frame) -> None:
    try:
        KLINE_DISK_DIR.mkdir(parents=True, exist_ok=True)
        f = frame.tail(_KLINE_DISK_MAX)
        d = {"t": [int(x.timestamp()) for x in f["Date"]],
             "o": [float(x) for x in f["Open"]],
             "h": [float(x) for x in f["High"]],
             "l": [float(x) for x in f["Low"]],
             "c": [float(x) for x in f["Close"]],
             "v": [float(x) for x in f["Volume"]]}
        tmp = _kline_disk_path(symbol, interval).with_suffix(".tmp")
        with _gzip.open(tmp, "wt", encoding="utf-8") as fh:
            _json.dump(d, fh, separators=(",", ":"))
        tmp.replace(_kline_disk_path(symbol, interval))
    except Exception:
        pass                 # caching is best-effort, never fatal


def _kline_db_seed(symbol: str, interval: str):
    """Long history from the permanent database when the local disk cache is
    cold (new machine, cleared cache) — saves re-paging the whole venue."""
    try:
        from tradingagents.dataflows import market_db  # noqa: PLC0415
        return market_db.candles_df(symbol, interval)
    except Exception:
        return None


def _kline_db_store(symbol: str, interval: str, frame) -> None:
    """Archive closed bars to the permanent database, best-effort. Only the
    tail past what it already holds is sent; the newest stored bar is re-sent
    in case it was still forming when first archived."""
    try:
        import pandas as pd  # noqa: PLC0415

        from tradingagents.dataflows import market_db  # noqa: PLC0415
        if not market_db.available():
            return
        per = {"Min1": 60, "Min5": 300, "Min15": 900, "Min30": 1800,
               "Min60": 3600, "Hour4": 14400, "Day1": 86400}.get(interval, 300)
        closed = frame[frame["Date"]
                       <= pd.Timestamp(time.time() - per, unit="s")]
        prev = market_db.last_ts(symbol, interval)
        if prev is not None:
            closed = closed[closed["Date"] >= pd.Timestamp(prev, unit="s")]
        market_db.upsert_candles(symbol, interval, closed)
    except Exception:
        pass                 # the archive must never break a fetch


def klines(symbol: str, interval: str = "Min5", limit: int = 300):
    """Recent futures candles as a DataFrame, for charting. Keyless.

    Column names match the spot helpers (Date/Open/High/Low/Close/Volume) so the
    existing candlestick chart can render them unchanged.
    """
    import pandas as pd

    key = (symbol, interval, limit)
    hit = _KLINE_CACHE.get(key)
    now = time.time()
    if hit and now - hit[0] < min(_KLINE_TTL.get(interval, 150),
                                 _KLINE_TTL_CAP):
        return hit[1].copy()

    # MEXC returns at most 2001 candles per request, silently — asking for 5000
    # gave 2001 and a backtest that quietly covered a quarter of the requested
    # history. Page backwards through time when more than that is wanted.
    if limit > _KLINE_PAGE:
        # Candles are immutable once their bar closes, so a year of them is
        # cached ON DISK and only the missing tail is fetched. A daily sweep
        # needs ~100 new bars, not 18 paged requests; measured 2026-08-20 the
        # 15m fetch fell from minutes to one request. The last two cached bars
        # are refetched and overwritten in case the newest was still forming
        # when it was saved. Delete ~/.tradingagents/kline_cache to reset.
        cached = _kline_disk_load(symbol, interval)
        if cached is None or not len(cached):
            cached = _kline_db_seed(symbol, interval)
        if cached is not None and len(cached):
            per = {"Min1": 60, "Min5": 300, "Min15": 900, "Min30": 1800,
                   "Min60": 3600, "Hour4": 14400, "Day1": 86400}.get(
                       interval, 300)
            last_s = int(cached["Date"].iloc[-1].timestamp())
            frames = [cached]
            cursor_end = int(time.time())
            fetch_from = last_s - 2 * per
            while cursor_end > fetch_from:
                part = _klines_page(symbol, interval, _KLINE_PAGE, cursor_end)
                if part is None or part.empty:
                    break
                frames.append(part)
                oldest = int(part["Date"].iloc[0].timestamp())
                if oldest >= cursor_end or oldest <= fetch_from:
                    break
                cursor_end = oldest - 1
            out = pd.concat(frames, ignore_index=True)
            # keep="last": the freshly fetched copy of an overlapping bar wins
            out = (out.sort_values("Date")
                      .drop_duplicates(subset="Date", keep="last")
                      .reset_index(drop=True))
            _kline_disk_save(symbol, interval, out)
            _kline_db_store(symbol, interval, out)
            out = out.tail(limit).reset_index(drop=True)
            _KLINE_CACHE[key] = (now, out)
            return out.copy()
        frames, cursor_end = [], int(time.time())
        remaining = limit
        while remaining > 0:
            chunk = min(_KLINE_PAGE, remaining)
            part = _klines_page(symbol, interval, chunk, cursor_end)
            if part is None or part.empty:
                break
            frames.append(part)
            oldest = int(part["Date"].iloc[0].timestamp())
            if oldest >= cursor_end:
                break                       # no progress: the history ends here
            cursor_end = oldest - 1
            remaining -= len(part)
            if len(part) < chunk:
                break                       # exchange has no more history
        if not frames:
            raise MexcFuturesError(f"no {interval} candles for {symbol}")
        out = pd.concat(reversed(frames), ignore_index=True)
        out = out.drop_duplicates(subset="Date").sort_values("Date")
        out = out.tail(limit).reset_index(drop=True)
        _kline_disk_save(symbol, interval, out)
        _kline_db_store(symbol, interval, out)
        _KLINE_CACHE[key] = (now, out)
        return out.copy()

    end = int(time.time())
    per = {"Min1": 60, "Min5": 300, "Min15": 900, "Min30": 1800,
           "Min60": 3600, "Hour4": 14400, "Day1": 86400}.get(interval, 300)
    url = (f"{BASE}/api/v1/contract/kline/{urllib.parse.quote(symbol)}?"
           + urllib.parse.urlencode({"interval": interval,
                                     "start": end - per * limit, "end": end}))
    payload = _get_public(url)
    d = payload.get("data") or {}
    if not d.get("time"):
        raise MexcFuturesError(f"no {interval} candles for {symbol}")
    frame = pd.DataFrame({
        "Date": pd.to_datetime(d["time"], unit="s", utc=True).tz_localize(None),
        "Open": [float(x) for x in d["open"]],
        "High": [float(x) for x in d["high"]],
        "Low": [float(x) for x in d["low"]],
        "Close": [float(x) for x in d["close"]],
        "Volume": [float(x) for x in d.get("vol", [0] * len(d["time"]))],
    })
    # Hand out copies so a caller mutating the frame cannot poison the cache.
    _KLINE_CACHE[key] = (now, frame)
    return frame.copy()


def liquidation_move_pct(symbol: str, leverage: float) -> float:
    """How far price may move against a long before the venue liquidates it, in %.

    ``1/leverage - maintenance_margin_rate``, which is the formula OctoBot uses and
    which MEXC's own contract detail supports: it publishes maintenanceMarginRate
    directly. Using 100/leverage instead — as this project did — overstates the
    survivable move fivefold at 200x, because it ignores the maintenance margin the
    venue keeps back: 0.50% claimed against 0.10% actual.

    Falls back to the naive figure when the rate cannot be read, and clamps at zero
    for leverage so high that the maintenance margin alone exhausts the position.
    """
    if leverage <= 0:
        return 100.0
    try:
        mmr = float(contract_spec(symbol).get("maintenanceMarginRate") or 0.0)
    except (MexcFuturesError, TypeError, ValueError):
        mmr = 0.0
    return max(0.0, (1.0 / leverage - mmr) * 100.0)


def round_vol(symbol: str, vol: float) -> int:
    """Snap a contract count DOWN to the exchange's volUnit step.

    Borrowed from the Crypto-Predictor-Web approach: submitting a size the venue
    cannot represent gets the whole order rejected, so round rather than hope.
    """
    spec = contract_spec(symbol)
    step = float(spec.get("volUnit") or 1)
    min_vol = float(spec.get("minVol") or 1)
    snapped = int((vol // step) * step) if step > 0 else int(vol)
    return snapped if snapped >= min_vol else 0


def chase_guard(entry_ref: float, live: float, max_chase_pct: float) -> tuple[bool, str]:
    """Refuse an entry that has already run away from the reference price.

    Also from the reference project: a signal computed a minute ago is not a
    licence to buy at any price. Returns (ok_to_enter, reason).
    """
    if entry_ref <= 0 or live <= 0:
        return False, "no reference price"
    drift = (live / entry_ref - 1) * 100
    if drift > max_chase_pct:
        return False, (f"price ran {drift:+.2f}% past the reference "
                       f"(limit {max_chase_pct:.2f}%)")
    return True, f"drift {drift:+.2f}% within {max_chase_pct:.2f}%"


# ---------------------------------------------------------------- funding
def funding_history(symbol: str, max_pages: int = 200) -> list:
    """Every published funding settlement, oldest last. Keyless.

    ``max_pages`` is a runaway backstop, NOT a limit on real history. It was 20,
    which silently truncated any longer history until 2026-08-26 and then --
    once truncation became an error -- started REJECTING those coins outright.
    Measured live: BTC settles every 8 hours and fills 17 pages; FLUX_USDT
    settles every 4 hours and has 33. At 100 rows a page, 200 pages is about
    nine years of 4-hourly settlements.

    Returned as ``[{"settle_ms": int, "rate": float, "cycle_h": int}, ...]``.
    Sign convention is MEXC's: a POSITIVE rate means longs pay shorts, so a
    long position's funding PnL is ``-rate * notional`` per settlement.
    """
    out, pg = [], 1
    while pg <= max_pages:
        url = (f"{BASE}/api/v1/contract/funding_rate/history?"
               + urllib.parse.urlencode({"symbol": symbol, "page_num": pg,
                                         "page_size": 100}))
        # _get_public, never a bare urlopen: this was the last keyless fetch in
        # the module without the retry, and on 2026-08-26 it died with
        # IncompleteRead(8984 bytes read) mid-study.
        try:
            payload = _get_public(url)
        except Exception as exc:
            # RAISE, never `break`. Breaking returned the pages already read,
            # so an unreadable page silently shortened the history -- and
            # funding is a mandatory cost, so a short history makes every trade
            # in the missing window cheaper than it really was, in the
            # direction that flatters the strategy, with no column to say so.
            raise MexcFuturesError(
                f"funding history for {symbol} is incomplete: page {pg} of "
                f"{'?' if pg == 1 else total} failed ({exc})") from exc
        data = payload.get("data") or {}
        rows = data.get("resultList") or []
        try:
            for r in rows:
                out.append({"settle_ms": int(r["settleTime"]),
                            "rate": float(r["fundingRate"]),
                            "cycle_h": int(r.get("collectCycle") or 8)})
        except (TypeError, ValueError, KeyError) as exc:
            raise MexcFuturesError(
                f"funding history for {symbol}: page {pg} is malformed "
                f"({exc})") from exc
        total = int(data.get("totalPage") or 1)
        if pg >= total or not rows:
            break
        pg += 1
        time.sleep(0.15)
    else:
        # ran out of page budget with pages still unread: also short
        raise MexcFuturesError(
            f"funding history for {symbol} is incomplete: stopped at the "
            f"{max_pages}-page budget")
    out.sort(key=lambda d: d["settle_ms"])
    return out


def funding_summary(symbol: str) -> dict:
    """Headline funding numbers for a contract, from the long side."""
    hist = funding_history(symbol)
    if not hist:
        return {"symbol": symbol, "settlements": 0, "available": False}
    rates = [h["rate"] for h in hist]
    span_days = (hist[-1]["settle_ms"] - hist[0]["settle_ms"]) / 86400_000
    cycle = hist[0]["cycle_h"] or 8
    mean = sum(rates) / len(rates)
    return {
        "symbol": symbol, "available": True, "settlements": len(rates),
        "span_days": span_days, "cycle_h": cycle,
        "mean_rate": mean,
        "pct_positive": sum(1 for r in rates if r > 0) / len(rates) * 100,
        # A long's cumulative funding as a fraction of notional. Derived from
        # the actual settlement sum and elapsed span rather than the recorded
        # cycle: MEXC changed this contract from a 24h to an 8h cycle mid-life,
        # so any single cycle value misstates the daily rate.
        "long_total": -sum(rates),
        "long_daily": (-sum(rates) / span_days) if span_days > 0 else 0.0,
        "long_annual": ((-sum(rates) / span_days) * 365) if span_days > 0 else 0.0,
    }

