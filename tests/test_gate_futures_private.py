"""Gate's real-money half (phase 6, spec D12, Oct 10, 2026).

Built so the runner's real-money code runs unchanged on Gate: positions,
orders, the resting stop, closed-position history and the wallet answer in
the shapes it already reads from MEXC. NO Gate key exists on this PC, so none
of this has met the real exchange: every test here is against a fake Gate
that checks each request's signature, and real-money trading stays shut until
a key passes `preflight` (the TEST CONNECT button).

Signature (Gate's own example, gateio/gateapi-python issue 15): HMAC-SHA512
of "METHOD\\n/api/v4/PATH\\nQUERY\\nsha512(BODY)\\nTIMESTAMP", headers KEY,
Timestamp, SIGN.
"""
import hashlib
import hmac
import json
import urllib.parse

import pytest

from tradingagents.dataflows import exchange_errors as xe
from tradingagents.dataflows import gate_futures as gf

KEY, SECRET = "k-test", "s-test"


class FakePrivate:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlparse(url)
        payload = body.decode() if body else ""
        want = hmac.new(SECRET.encode(), "\n".join([
            method, u.path, u.query, hashlib.sha512(payload.encode()).hexdigest(),
            headers["Timestamp"]]).encode(), hashlib.sha512).hexdigest()
        assert headers["KEY"] == KEY and headers["SIGN"] == want, "bad signature"
        self.calls.append((method, u.path, dict(urllib.parse.parse_qsl(u.query)),
                           json.loads(payload) if payload else None))
        ans = self.routes(method, u.path, dict(urllib.parse.parse_qsl(u.query)),
                          json.loads(payload) if payload else None)
        if isinstance(ans, tuple):
            return ans
        return 200, json.dumps(ans).encode()


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.setenv("GATE_API_KEY", KEY)
    monkeypatch.setenv("GATE_API_SECRET", SECRET)
    monkeypatch.setattr(gf, "contract_spec", lambda s: {"contractSize": 0.0001})

    def install(routes):
        fake = FakePrivate(routes)
        monkeypatch.setattr(gf, "_send", fake)
        return fake
    return install


POS_LONG = {"contract": "BTC_USDT", "size": 12, "leverage": "20", "entry_price": "100.5",
            "liq_price": "95", "margin": "5.1", "realised_pnl": "-0.1",
            "open_time": 1791600000, "mode": "single", "value": "0.1206"}
POS_SHORT = {**POS_LONG, "contract": "ETH_USDT", "size": -3, "open_time": 1791600100}


def test_no_key_means_no_credentials(monkeypatch):
    monkeypatch.delenv("GATE_API_KEY", raising=False)
    monkeypatch.delenv("GATE_API_SECRET", raising=False)
    assert gf.has_credentials() is False
    with pytest.raises(xe.VenueError, match="GATE_API_KEY"):
        gf.open_positions()


def test_positions_answer_in_the_runners_shape(gate):
    gate(lambda m, p, q, b: [POS_LONG, POS_SHORT, {**POS_LONG, "contract": "X_USDT", "size": 0}])
    got = gf.open_positions()
    assert [g["symbol"] for g in got] == ["BTC_USDT", "ETH_USDT"], "a flat contract is no position"
    lo, sh = got
    assert (lo["positionType"], lo["holdVol"], lo["holdAvgPrice"]) == (1, 12, 100.5)
    assert (sh["positionType"], sh["holdVol"]) == (2, 3)
    assert lo["positionId"] == 1791600000 and lo["liquidatePrice"] == 95.0
    assert lo["im"] == 5.1 and lo["leverage"] == 20 and lo["realised"] == -0.1


def test_one_symbols_positions(gate):
    fake = gate(lambda m, p, q, b: POS_LONG)
    (got,) = gf.open_positions("BTC_USDT")
    assert fake.calls[0][1] == "/api/v4/futures/usdt/positions/BTC_USDT"
    assert got["symbol"] == "BTC_USDT"
    gate(lambda m, p, q, b: {**POS_LONG, "size": 0})
    assert gf.open_positions("BTC_USDT") == []


def test_a_dry_run_sends_nothing(gate):
    fake = gate(lambda *a: pytest.fail("a dry run must not reach Gate"))
    got = gf.submit("BTC_USDT", gf.SIDE_OPEN_LONG, 12, leverage=20, dry_run=True)
    assert got["dry_run"] is True and got["request"]["size"] == 12
    assert not fake.calls


def test_an_entry_sets_the_leverage_then_sends_a_market_order(gate):
    def routes(m, p, q, b):
        if p.endswith("/leverage"):
            return {"leverage": "20"}
        return {"id": 9001, "status": "finished", "finish_as": "filled",
                "fill_price": "100.6", "size": -5, "left": 0}
    fake = gate(routes)
    got = gf.submit("BTC_USDT", gf.SIDE_OPEN_SHORT, 5, leverage=20, dry_run=False)
    lev, order = fake.calls
    assert lev[0] == "POST" and lev[1] == "/api/v4/futures/usdt/positions/BTC_USDT/leverage"
    assert lev[2] == {"leverage": "20"}
    assert order[3] == {"contract": "BTC_USDT", "size": -5, "price": "0", "tif": "ioc",
                        "text": order[3]["text"]}
    assert order[3]["text"].startswith("t-")
    assert got["response"]["orderId"] == 9001


def test_a_close_is_reduce_only_and_sets_no_leverage(gate):
    fake = gate(lambda m, p, q, b: {"id": 2, "status": "finished", "finish_as": "filled"})
    gf.submit("BTC_USDT", gf.SIDE_CLOSE_LONG, 12, leverage=20, dry_run=False)
    ((method, path, query, body),) = fake.calls
    assert path == "/api/v4/futures/usdt/orders"
    assert body["size"] == -12 and body["reduce_only"] is True


def test_a_limit_close_rests_at_its_price(gate):
    fake = gate(lambda m, p, q, b: {"id": 3, "status": "open"})
    gf.limit_close_long("BTC_USDT", 12, 101.25, leverage=20, dry_run=False)
    body = fake.calls[-1][3]
    assert body["price"] == "101.25" and body["tif"] == "gtc" and body["size"] == -12
    assert body["reduce_only"] is True


def test_the_stop_rests_on_gates_servers_for_the_whole_position(gate):
    def routes(m, p, q, b):
        if m == "GET" and "/positions/" in p:
            return POS_LONG
        return {"id": 77}
    fake = gate(routes)
    got = gf.place_position_stop("BTC_USDT", 1791600000, 12, stop_loss_price=95.5,
                                 take_profit_price=104.0, dry_run=False)
    posts = [c for c in fake.calls if c[0] == "POST"]
    sl, tp = posts
    assert sl[1] == "/api/v4/futures/usdt/price_orders"
    assert sl[3]["order_type"] == "close-long-position"
    assert sl[3]["trigger"] == {"strategy_type": 0, "price_type": 0, "price": "95.5",
                                "rule": 2, "expiration": 0}
    assert sl[3]["initial"]["size"] == 0 and sl[3]["initial"]["close"] is True
    assert tp[3]["trigger"]["rule"] == 1 and tp[3]["trigger"]["price"] == "104.0"
    assert got["response"]["stop_id"] == 77


def test_a_short_stop_triggers_upward(gate):
    def routes(m, p, q, b):
        if m == "GET" and "/positions/" in p:
            return POS_SHORT
        return {"id": 78}
    fake = gate(routes)
    gf.place_position_stop("ETH_USDT", 1791600100, 3, stop_loss_price=110.0, dry_run=False)
    (sl,) = [c for c in fake.calls if c[0] == "POST"]
    assert sl[3]["order_type"] == "close-short-position" and sl[3]["trigger"]["rule"] == 1


def test_a_stop_is_verified_by_reading_it_back(gate):
    gate(lambda m, p, q, b: [{"id": 77, "status": "open", "order_type": "close-long-position",
                              "initial": {"contract": "BTC_USDT"}, "trigger": {"price": "95.5", "rule": 2}},
                             {"id": 70, "status": "finished", "finish_as": "failed",
                              "reason": "position not exists", "order_type": "close-long-position",
                              "initial": {"contract": "BTC_USDT"}, "trigger": {"price": "90", "rule": 2}}])
    got = gf.verify_position_stop("BTC_USDT", 1791600000)
    assert got["protected"] is True and len(got["active"]) == 1


def test_no_open_stop_is_not_protected(gate):
    gate(lambda m, p, q, b: [])
    assert gf.verify_position_stop("BTC_USDT", 1)["protected"] is False


def test_closed_positions_carry_the_exchanges_own_result(gate):
    gate(lambda m, p, q, b: [{"time": 1791610000, "contract": "BTC_USDT", "side": "long",
                              "pnl": "-0.53", "first_open_time": 1791600000,
                              "long_price": "100.5", "short_price": "99.9",
                              "accum_size": "12"}])
    (h,) = gf.position_history("BTC_USDT", 10)
    assert h["positionId"] == 1791600000 and h["realised"] == -0.53
    assert h["closeAvgPrice"] == 99.9 and h["positionType"] == 1
    assert h["updateTime"] == 1791610000 * 1000


def test_the_wallet_in_the_runners_names(gate):
    gate(lambda m, p, q, b: {"total": "60.5", "unrealised_pnl": "1.5", "available": "40",
                             "position_margin": "20.5", "order_margin": "0", "currency": "USDT"})
    u = gf.assets()["USDT"]
    assert u["equity"] == 62.0 and u["availableOpen"] == 40.0 and u["positionMargin"] == 20.5
    assert gf.usdt_equity() == 62.0


def test_a_bad_key_is_an_auth_failure_not_a_missing_permission(gate):
    gate(lambda m, p, q, b: (401, b'{"label":"INVALID_SIGNATURE","message":"Signature mismatch"}'))
    with pytest.raises(xe.VenueAuthFailed):
        gf.usdt_equity()


def test_preflight_with_a_working_key_is_ready(gate):
    def routes(m, p, q, b):
        if p.endswith("/accounts"):
            return {"total": "10", "unrealised_pnl": "0", "available": "10",
                    "position_margin": "0", "currency": "USDT"}
        if p.endswith("/positions"):
            return []
        if m == "DELETE":
            return 404, b'{"label":"ORDER_NOT_FOUND","message":"Order not found"}'
        return {}
    gate(routes)
    r = gf.preflight("BTC_USDT")
    assert r["read_assets"] and r["read_positions"]
    assert r["order_permission"] is True and r["can_rest_stop"] is True
    assert r["ready"] is True and r["equity_usdt"] == 10.0


def test_preflight_names_a_key_without_trading_permission(gate):
    def routes(m, p, q, b):
        if p.endswith("/accounts"):
            return {"total": "10", "unrealised_pnl": "0", "available": "10",
                    "position_margin": "0", "currency": "USDT"}
        if p.endswith("/positions"):
            return []
        return 403, b'{"label":"FORBIDDEN","message":"Your key has no permission"}'
    gate(routes)
    r = gf.preflight("BTC_USDT")
    assert r["order_permission"] is False and r["ready"] is False
    assert r["missing_scopes"]
