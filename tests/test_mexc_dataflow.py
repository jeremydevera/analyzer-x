"""Unit tests for the MEXC dataflow (no network — every HTTP call is patched).

The spot host resolver (`mexc.resolve_host`, still used by `mexc_trade`) and
the futures client (`mexc_futures`). The new-listing screener and the
analysts' price/indicator vendor tests went with that code on Oct 02, 2026
(New Crypto, Analysis and LLM Models removed).
"""

from unittest.mock import patch

import pytest

from tradingagents.dataflows import mexc

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _offline_clock(monkeypatch):
    """preflight() checks the clock, which reached MEXC over the real network in
    every preflight test. They passed only because a failed check is treated as
    inconclusive — passing for the wrong reason, and flaky offline."""
    from tradingagents.dataflows import mexc_futures as _fx
    monkeypatch.setattr(_fx, "clock_skew_ms", lambda: 0)


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


# ===================== edge-proxy block vs missing key scope =================
# MEXC's edge proxy refuses the futures ORDER paths for requests whose
# User-Agent identifies a scripted client, answering with an HTML "Access
# Denied" and HTTP 403 before the API sees the request. That is indistinguishable
# from a permission failure unless it is detected explicitly, and it cost a long
# debugging session spent looking at key settings that were already correct.
import io
import json as _json
import urllib.error

import pytest

from tradingagents.dataflows import mexc_futures as fx

AKAMAI_DENY = (
    b"<HTML><HEAD>\n<TITLE>Access Denied</TITLE>\n</HEAD><BODY>\n"
    b"<H1>Access Denied</H1>\nYou don't have permission to access "
    b'"http://contract.mexc.com/api/v1/private/order/submit" on this server.'
)


def _keys(monkeypatch):
    monkeypatch.setenv("MEXC_API_KEY", "k" * 18)
    monkeypatch.setenv("MEXC_API_SECRET", "s" * 32)


def _http_error(code, body):
    def raiser(*a, **k):
        raise urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(body))
    return raiser


def _ok(payload):
    class R:
        def read(self): return _json.dumps(payload).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False
    return lambda *a, **k: R()


def test_html_403_is_an_edge_block_not_a_permission_error(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setattr(fx.urllib.request, "urlopen",
                        _http_error(403, AKAMAI_DENY))
    with pytest.raises(fx.MexcFuturesEdgeBlocked) as exc:
        fx._request("POST", "/api/v1/private/order/submit", body={"vol": 1})
    assert "User-Agent" in exc.value.remedy
    # It must NOT be catchable as a key-scope problem: that conflation is the
    # bug this test exists to prevent.
    assert not isinstance(exc.value, fx.MexcFuturesForbidden)


def test_a_real_json_403_is_an_auth_failure_not_a_missing_scope(monkeypatch):
    """The edge-block branch must not swallow genuine 403 JSON — but a 403 is a
    CREDENTIAL problem, not a scope problem.

    This assertion was originally MexcFuturesForbidden. That was wrong: MEXC
    returns 403 for a bad signature, a stale clock, or a source IP outside the
    allowlist, none of which any permission checkbox fixes. Because preflight
    derived a scope name from the code, the UI printed "missing permission
    scopes: code None" and the branch naming the real cause was unreachable.
    """
    _keys(monkeypatch)
    monkeypatch.setattr(fx.urllib.request, "urlopen", _http_error(
        403, b'{"success":false,"code":403,"message":"no permission"}'))
    with pytest.raises(fx.MexcFuturesAuthFailed) as exc:
        fx._request("GET", "/api/v1/private/account/assets")
    assert "allowlist" in exc.value.remedy and "clock" in exc.value.remedy
    assert not isinstance(exc.value, fx.MexcFuturesForbidden)


def test_only_a_named_scope_reaches_missing_scopes(monkeypatch):
    """preflight must never invent a scope name out of a status code."""
    _keys(monkeypatch)
    monkeypatch.setattr(fx, "open_positions", lambda s=None: [])
    monkeypatch.setattr(fx, "write_probe", lambda: {"reached": True})

    def bad_sig():
        raise fx.MexcFuturesAuthFailed("code 2011: signature error", code=2011)

    monkeypatch.setattr(fx, "usdt_equity", bad_sig)
    # order_permission is True here, so preflight goes on to probe the stop
    # endpoint — a live call unless stubbed.
    monkeypatch.setattr(fx, "stop_probe", lambda: {"permitted": True,
                                                   "reason": "stubbed"})
    rep = fx.preflight("SPX500_USDT")
    assert rep["missing_scopes"] == [], "a signature error is not a scope"
    assert rep["auth_failed"] is True
    assert rep["ready"] is False
    assert any("allowlist" in r for r in rep["remedies"])


def test_a_scope_code_still_names_its_scope(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setattr(fx.urllib.request, "urlopen", _ok(
        {"success": False, "code": 704, "message": "enable write"}))
    with pytest.raises(fx.MexcFuturesForbidden) as exc:
        fx._request("POST", "/api/v1/private/order/cancel", body=[1])
    assert exc.value.scope == "trading information write"
    assert not isinstance(exc.value, fx.MexcFuturesAuthFailed)


def test_requests_always_carry_a_user_agent_the_edge_accepts(monkeypatch):
    """A bare urllib/requests UA is refused by MEXC — assert we never send one."""
    _keys(monkeypatch)
    seen = {}

    def capture(req, *a, **k):
        seen["ua"] = req.get_header("User-agent")
        class R:
            def read(self): return b'{"success":true,"code":0,"data":[]}'
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()

    monkeypatch.setattr(fx.urllib.request, "urlopen", capture)
    fx._request("GET", "/api/v1/private/position/open_positions")
    ua = (seen["ua"] or "").lower()
    assert ua, "no User-Agent sent — the edge proxy blocks the order paths"
    assert "urllib" not in ua and "python-requests" not in ua


# ============================ the write probe ===============================
def test_write_probe_cancels_and_never_submits_an_order(monkeypatch):
    """The order-permission probe must not be able to open a position.

    The probe it replaced submitted a real order with vol=0 and trusted MEXC to
    reject it; during diagnosis an equivalent probe DID open four real long
    positions. This test pins the contract: cancel-only, no instrument, no size.
    """
    _keys(monkeypatch)
    calls = []

    def capture(req, *a, **k):
        calls.append((req.get_method(), req.full_url,
                      (req.data or b"").decode()))
        class R:
            def read(self):
                return (b'{"success":true,"code":0,"data":[{"orderId":1,'
                        b'"errorCode":2040,"errorMsg":"order not exist"}]}')
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()

    monkeypatch.setattr(fx.urllib.request, "urlopen", capture)
    assert fx.write_probe()["reached"] is True
    assert len(calls) == 1
    method, url, body = calls[0]
    assert method == "POST"
    assert url.endswith("/api/v1/private/order/cancel")
    assert "submit" not in url
    assert body == "[1]"
    for forbidden in ("symbol", "vol", "side", "leverage", "openType"):
        assert forbidden not in body, f"probe body describes a trade: {body}"


def test_preflight_all_pass_shape(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setattr(fx, "usdt_equity", lambda: 163.2)
    monkeypatch.setattr(fx, "open_positions", lambda s=None: [])
    monkeypatch.setattr(fx, "write_probe", lambda: {"reached": True})
    monkeypatch.setattr(fx, "stop_probe",
                        lambda: {"permitted": True, "reason": "ok"})
    rep = fx.preflight("SPX500_USDT")
    assert rep["ready"] is True
    assert rep["can_rest_stop"] is True
    assert rep["order_permission"] is True
    assert rep["edge_blocked"] is False
    assert rep["missing_scopes"] == []


def test_preflight_reports_edge_block_separately_from_scopes(monkeypatch):
    """An edge block must not be rendered as "your key lacks a scope"."""
    _keys(monkeypatch)
    monkeypatch.setattr(fx, "usdt_equity", lambda: 163.2)
    monkeypatch.setattr(fx, "open_positions", lambda s=None: [])

    def blocked():
        raise fx.MexcFuturesEdgeBlocked("/api/v1/private/order/cancel")

    monkeypatch.setattr(fx, "write_probe", blocked)
    rep = fx.preflight("SPX500_USDT")
    assert rep["ready"] is False
    assert rep["order_permission"] is False
    assert rep["edge_blocked"] is True
    assert rep["missing_scopes"] == [], "edge block is not a missing scope"
    assert any("User-Agent" in r for r in rep["remedies"])


# ======================= signing with a list body ===========================
def test_list_body_signs_the_exact_bytes_that_are_sent(monkeypatch):
    """order/cancel takes a JSON array; the signed string and the wire bytes
    must be identical or MEXC answers with a signature failure that looks like a
    permission problem."""
    _keys(monkeypatch)
    seen = {}

    def capture(req, *a, **k):
        seen["body"] = (req.data or b"").decode()
        seen["sig"] = req.get_header("Signature")
        seen["ts"] = req.get_header("Request-time")
        class R:
            def read(self): return b'{"success":true,"code":0,"data":[]}'
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()

    monkeypatch.setattr(fx.urllib.request, "urlopen", capture)
    fx._request("POST", "/api/v1/private/order/cancel", body=[1])
    expected = fx.sign("k" * 18, "s" * 32, seen["ts"], None, [1])
    assert seen["sig"] == expected
    assert seen["body"] == "[1]"


def test_dict_body_signing_is_unchanged_by_the_list_support():
    """sort_keys must still apply to dict bodies — the whole signature depends
    on it."""
    body = {"vol": 1, "symbol": "SPX500_USDT", "side": 1}
    assert fx._param_string(None, body) == \
        '{"side":1,"symbol":"SPX500_USDT","vol":1}'
    assert fx._param_string(None, [1, 2]) == "[1,2]"


# ============ exchange-resting stops (the point of the whole exercise) ======
def test_a_limit_take_profit_on_the_position_record_is_refused():
    """MEXC accepts it and attaches NOTHING.

    Verified against a real position: the request returned success and the
    resulting record read back `tp=None tpType=None`, with only the stop
    attached. A take-profit that silently does not exist is the worst failure
    available here, so this path refuses rather than lying. The target belongs in
    a resting limit close order.
    """
    with pytest.raises(fx.MexcFuturesError) as exc:
        fx.place_position_stop("SPX500_USDT", 1, 4, stop_loss_price=6944.0,
                               take_profit_price=7870.0,
                               take_profit_type=fx.SL_LIMIT)
    assert "silently ignores" in str(exc.value)
    assert "limit close order" in str(exc.value)


def test_a_market_take_profit_sends_only_the_trigger_price():
    b = fx.place_position_stop("SPX500_USDT", 1, 4, stop_loss_price=6944.0,
                               take_profit_price=7870.0,
                               take_profit_type=fx.SL_MARKET)["request"]
    assert b["takeProfitPrice"] == 7870.0
    assert "takeProfitOrderPrice" not in b


def test_a_market_stop_omits_the_order_price():
    b = fx.place_position_stop("SPX500_USDT", 1, 4,
                               stop_loss_price=6944.0)["request"]
    assert b["stopLossPrice"] == 6944.0
    assert b["stopLossType"] == fx.SL_MARKET
    assert "stopLossOrderPrice" not in b


def test_a_limit_stop_needs_both_prices():
    """Unlike the take-profit, a limit STOP requires the trigger AND the resting
    price — either alone answers 5001."""
    b = fx.place_position_stop("SPX500_USDT", 1, 4, stop_loss_price=6944.0,
                               stop_loss_type=fx.SL_LIMIT,
                               stop_loss_order_price=6940.0)["request"]
    assert b["stopLossPrice"] == 6944.0
    assert b["stopLossOrderPrice"] == 6940.0
    assert b["stopLossType"] == fx.SL_LIMIT


def test_the_position_record_carries_the_stop_at_market():
    """Default is a MARKET stop: getting out matters more than the price, and it
    is the only stop type MEXC actually attaches without a second price."""
    r = fx.place_position_stop("SPX500_USDT", 123, 4, stop_loss_price=6960.0)
    b = r["request"]
    assert r["dry_run"] is True, "must not reach the exchange by default"
    assert b["stopLossType"] == fx.SL_MARKET
    assert b["stopLossPrice"] == 6960.0
    assert "takeProfitPrice" not in b, "the target is a separate resting order"
    assert b["lossTrend"] == fx.TRIGGER_LAST, \
        "last price is the only basis that matches the backtest's candles"
    assert b["volType"] == fx.VOL_POSITION, "must cover the whole position"


def test_verify_bracket_requires_both_halves(monkeypatch):
    """The stop and the target live in different places, so both are read back.
    Either one missing means the position is not protected as intended."""
    monkeypatch.setattr(fx, "list_position_stops", lambda symbol=None: [
        {"positionId": "55", "errorCode": 0, "isFinished": 0, "state": 2}])
    monkeypatch.setattr(fx, "open_orders", lambda symbol=None: [
        {"orderId": "9", "side": fx.SIDE_CLOSE_LONG, "price": 7870.0}])
    v = fx.verify_bracket("SPX500_USDT", 55, 7870.0)
    assert v["stop_active"] and v["target_resting"] and v["protected"]
    assert v["target_order_id"] == "9"

    # target missing -> not protected, even though the stop is fine
    monkeypatch.setattr(fx, "open_orders", lambda symbol=None: [])
    v = fx.verify_bracket("SPX500_USDT", 55, 7870.0)
    assert v["stop_active"] is True and v["protected"] is False

    # a strategy with no target (buy and hold) needs only the stop
    assert fx.verify_bracket("SPX500_USDT", 55, None)["protected"] is True


def test_a_limit_stop_without_a_price_is_refused():
    with pytest.raises(fx.MexcFuturesError) as exc:
        fx.place_position_stop("SPX500_USDT", 1, 1, stop_loss_price=100.0,
                               stop_loss_type=fx.SL_LIMIT)
    assert "stop_loss_order_price" in str(exc.value)


def test_nonsense_sizes_and_prices_are_refused():
    for kw in ({"vol": 0}, {"vol": -3}):
        with pytest.raises(fx.MexcFuturesError):
            fx.place_position_stop("SPX500_USDT", 1, stop_loss_price=100.0, **kw)
    with pytest.raises(fx.MexcFuturesError):
        fx.place_position_stop("SPX500_USDT", 1, 1, stop_loss_price=0.0)


def test_a_stop_that_errored_is_not_protection():
    """Observed live: two of three real records on this account finished with
    errorCode 8912 and vol 0. MEXC accepting the request is not protection."""
    assert fx.stop_is_active({"errorCode": 0, "isFinished": 0, "state": 2})
    assert not fx.stop_is_active({"errorCode": 8912, "isFinished": 1, "state": 2})
    assert not fx.stop_is_active({"errorCode": 0, "isFinished": 1, "state": 3}), \
        "already triggered and finished is not still protecting"


def test_verify_reports_unprotected_when_every_record_failed(monkeypatch):
    monkeypatch.setattr(fx, "list_position_stops", lambda symbol=None: [
        {"positionId": "999", "errorCode": 8912, "isFinished": 1, "state": 2},
        {"positionId": "111", "errorCode": 0, "isFinished": 0, "state": 2},
    ])
    v = fx.verify_position_stop("SPX500_USDT", 999)
    assert v["protected"] is False
    assert v["error_codes"] == [8912]
    assert fx.verify_position_stop("SPX500_USDT", 111)["protected"] is True


def test_stop_probe_reads_a_validation_error_as_permitted(monkeypatch):
    """Rejecting a fake position id proves the endpoint authorised the key."""
    def boom(*a, **k):
        raise fx.MexcFuturesError("code 2009: Position is nonexistent or closed")
    monkeypatch.setattr(fx, "_request", boom)
    rep = fx.stop_probe()
    assert rep["permitted"] is True
    assert "2009" in rep["reason"]


def test_stop_probe_distinguishes_the_three_ways_it_can_be_blocked(monkeypatch):
    cases = [
        (fx.MexcFuturesEdgeBlocked("/api/v1/private/stoporder/place"), "edge proxy"),
        (fx.MexcFuturesForbidden("no", code=704, scope="trading information write",
                                 remedy="enable write"), "key scope"),
        (fx.MexcFuturesAuthFailed("code 2011: signature", code=2011), "credentials"),
    ]
    for err, expect in cases:
        def boom(*a, _e=err, **k):
            raise _e
        monkeypatch.setattr(fx, "_request", boom)
        rep = fx.stop_probe()
        assert rep["permitted"] is False
        assert rep["blocked_by"] == expect
        assert rep["remedy"], "a blocked probe must say what to do about it"


def test_stop_probe_never_names_an_instrument_it_could_open(monkeypatch):
    """The probe must not be able to create a position: no side, no order type,
    and a position id that cannot exist."""
    seen = {}
    monkeypatch.setattr(fx, "_request",
                        lambda m, p, **k: seen.update(method=m, path=p,
                                                      body=k.get("body")) or {})
    fx.stop_probe()
    assert seen["path"].endswith("/stoporder/place")
    assert seen["body"]["positionId"] == 1, "an id that cannot exist"
    for forbidden in ("side", "type", "openType", "leverage"):
        assert forbidden not in seen["body"]


def test_ready_requires_being_able_to_rest_a_stop(monkeypatch):
    """A key that can place orders but cannot rest a stop is not ready: the
    whole point of the exchange-side stop is that it survives this process
    dying, and discovering it is unavailable mid-trade is too late."""
    _keys(monkeypatch)
    monkeypatch.setattr(fx, "usdt_equity", lambda: 163.2)
    monkeypatch.setattr(fx, "open_positions", lambda s=None: [])
    monkeypatch.setattr(fx, "write_probe", lambda: {"reached": True})
    monkeypatch.setattr(fx, "stop_probe", lambda: {
        "permitted": False, "blocked_by": "key scope",
        "reason": "code 704", "remedy": "enable Trading information / Write"})
    rep = fx.preflight("SPX500_USDT")
    assert rep["order_permission"] is True, "orders are fine"
    assert rep["can_rest_stop"] is False
    assert rep["ready"] is False, "but it is not ready to trade"
    assert any("Write" in r for r in rep["remedies"])


# ============ kline cache ===================================================
def test_klines_are_cached_for_half_a_bar(monkeypatch):
    """A bot racing 7 lanes issued 480 kline requests an hour, each for 400
    candles, and this account has already been told "code 510: Requests are too
    frequent". Candles cannot change inside half a bar, so re-fetching faster is
    pure waste."""
    fx.clear_kline_cache()
    calls = []
    payload = {"data": {"time": [1, 2, 3], "open": [1, 1, 1], "high": [2, 2, 2],
                        "low": [0.5, 0.5, 0.5], "close": [1.5, 1.5, 1.5],
                        "vol": [1, 1, 1]}}
    monkeypatch.setattr(fx, "_get_public",
                        lambda url: calls.append(url) or payload)
    a = fx.klines("SPX500_USDT", "Min60", 10)
    b = fx.klines("SPX500_USDT", "Min60", 10)
    assert len(calls) == 1, "the second call must be served from the cache"
    assert list(a["Close"]) == list(b["Close"])

    # a different interval or limit is a different series
    fx.klines("SPX500_USDT", "Min5", 10)
    fx.klines("SPX500_USDT", "Min60", 20)
    assert len(calls) == 3


def test_a_cached_frame_cannot_be_poisoned_by_its_caller(monkeypatch):
    """Handing out the cached object would let one caller's edit corrupt every
    later read."""
    fx.clear_kline_cache()
    payload = {"data": {"time": [1, 2], "open": [1, 1], "high": [2, 2],
                        "low": [0.5, 0.5], "close": [1.5, 1.5], "vol": [1, 1]}}
    monkeypatch.setattr(fx, "_get_public", lambda url: payload)
    first = fx.klines("SPX500_USDT", "Min60", 10)
    first.loc[0, "Close"] = 999.0
    assert fx.klines("SPX500_USDT", "Min60", 10)["Close"].iloc[0] == 1.5


def test_the_cache_expires(monkeypatch):
    fx.clear_kline_cache()
    calls = []
    payload = {"data": {"time": [1], "open": [1], "high": [2], "low": [0.5],
                        "close": [1.5], "vol": [1]}}
    monkeypatch.setattr(fx, "_get_public",
                        lambda url: calls.append(url) or payload)
    monkeypatch.setattr(fx.time, "time", lambda: 1000.0)
    fx.klines("SPX500_USDT", "Min1", 10)
    monkeypatch.setattr(fx.time, "time", lambda: 1000.0 + 31)   # TTL is 30s
    fx.klines("SPX500_USDT", "Min1", 10)
    assert len(calls) == 2


def test_the_cache_never_holds_a_chart_stale_for_long():
    """The UI charts share klines(). A 12-hour TTL on Day1 bars would render a
    chart half a day old under a caption claiming it was the last price."""
    assert fx._KLINE_TTL_CAP == 300
    for interval, ttl in fx._KLINE_TTL.items():
        assert ttl <= fx._KLINE_TTL_CAP, interval


# ============ kline paging ==================================================
def test_klines_pages_past_the_exchange_ceiling(monkeypatch):
    """MEXC serves at most 2001 candles per request, silently. Asking for 5000 gave
    2001 and a backtest that quietly covered a quarter of the requested history."""
    import pandas as pd

    fx.clear_kline_cache()
    calls = []

    def fake_page(symbol, interval, limit, end):
        calls.append((limit, end))
        # 2000 candles ending at `end`, one per minute
        times = [end - 60 * i for i in range(limit)][::-1]
        return pd.DataFrame({
            "Date": pd.to_datetime(times, unit="s", utc=True).tz_localize(None),
            "Open": [1.0] * limit, "High": [1.0] * limit, "Low": [1.0] * limit,
            "Close": [1.0] * limit, "Volume": [0.0] * limit})

    monkeypatch.setattr(fx, "_klines_page", fake_page)
    out = fx.klines("SPX500_USDT", "Min1", 5000)
    assert len(calls) == 3, f"5000 needs three pages, made {len(calls)}"
    assert len(out) == 5000
    assert out["Date"].is_monotonic_increasing, "pages must be stitched in order"
    assert out["Date"].duplicated().sum() == 0, "overlaps must be dropped"


def test_paging_stops_when_the_history_runs_out(monkeypatch):
    """A young contract has less history than the window; the loop must end rather
    than request the same page forever."""
    import pandas as pd

    fx.clear_kline_cache()
    calls = []

    def short_page(symbol, interval, limit, end):
        calls.append(end)
        if len(calls) > 1:
            return None                      # nothing older exists
        times = [end - 60 * i for i in range(500)][::-1]
        return pd.DataFrame({
            "Date": pd.to_datetime(times, unit="s", utc=True).tz_localize(None),
            "Open": [1.0] * 500, "High": [1.0] * 500, "Low": [1.0] * 500,
            "Close": [1.0] * 500, "Volume": [0.0] * 500})

    monkeypatch.setattr(fx, "_klines_page", short_page)
    out = fx.klines("SPX500_USDT", "Min1", 5000)
    assert len(out) == 500
    assert len(calls) <= 2, "must not spin on an exhausted history"


def test_a_small_request_does_not_page(monkeypatch):
    fx.clear_kline_cache()
    pages = []
    monkeypatch.setattr(fx, "_klines_page",
                        lambda *a, **k: pages.append(1) or None)
    payload = {"data": {"time": [1, 2], "open": [1, 1], "high": [2, 2],
                        "low": [0.5, 0.5], "close": [1.5, 1.5], "vol": [1, 1]}}
    monkeypatch.setattr(fx, "_get_public", lambda url: payload)
    fx.klines("SPX500_USDT", "Min5", 300)
    assert pages == [], "300 bars is one plain request, no paging"



def test_contract_spec_refuses_an_empty_payload(monkeypatch):
    """MEXC answers a rate limit with HTTP 200 and no `data` key. The old code
    returned {} and callers read contractSize as 0.0 — which is not a size, it
    is a missing reply. Cost: on 2026-08-18 19:00 an ALICE entry died with
    `cannot size ALICE_USDT: contractSize=0.0` in both books, while ALICE's
    real contract size is 0.1."""
    fx.clear_spec_cache()
    monkeypatch.setattr(fx, "_get_public", lambda url, **kw: {
        "code": 510, "message": "Requests are too frequent, please try again later"})
    with pytest.raises(fx.MexcFuturesError) as e:
        fx.contract_spec("ALICE_USDT")
    assert "carried no data" in str(e.value)
    assert "510" in str(e.value), "say WHY it was empty"
    fx.clear_spec_cache()


def test_contract_spec_is_cached_so_a_rate_limit_cannot_empty_it(monkeypatch):
    """Contract size and tick never move during a session. One read per hour
    keeps a 510 from erasing a spec that was already read successfully."""
    fx.clear_spec_cache()
    calls = []

    def _one(url, **kw):
        calls.append(url)
        return {"code": 0, "data": {"symbol": "ALICE_USDT",
                                    "contractSize": 0.1}}

    monkeypatch.setattr(fx, "_get_public", _one)
    assert fx.contract_spec("ALICE_USDT")["contractSize"] == 0.1
    assert fx.contract_spec("ALICE_USDT")["contractSize"] == 0.1
    assert len(calls) == 1, "the second read should come from the cache"
    fx.clear_spec_cache()


def test_a_spec_with_no_symbol_is_not_a_spec(monkeypatch):
    """A partial payload is the same failure wearing different clothes."""
    fx.clear_spec_cache()
    monkeypatch.setattr(fx, "_get_public",
                        lambda url, **kw: {"code": 0, "data": {"contractSize": 0}})
    with pytest.raises(fx.MexcFuturesError):
        fx.contract_spec("ALICE_USDT")
    fx.clear_spec_cache()
