"""Gate's public answers, in the shapes the app reads (spec D4, Oct 10, 2026).

Every body below is the real shape Gate returned on Oct 10, 2026 (trimmed).
The adapter's HTTP goes through ONE function, `_fetch(url) -> (status,
bytes)`, so a test stubs that and nothing else."""
import json
import urllib.parse

import pytest

from tradingagents.dataflows import exchange_errors as xe
from tradingagents.dataflows import gate_futures as gf

BTC = {"name": "BTC_USDT", "contract_type": "", "quanto_multiplier": "0.0001",
       "order_price_round": "0.1", "order_size_min": 1, "order_size_max": 1000000,
       "maintenance_rate": "0.004", "taker_fee_rate": "0.00075",
       "maker_fee_rate": "-0.0001", "leverage_max": "125", "leverage_min": "1",
       "funding_rate": "0.00002", "funding_interval": 28800,
       "funding_next_apply": 1791619200, "in_delisting": False,
       "status": "trading", "last_price": "82739.8", "is_pre_market": False,
       "create_time": 1600000000}
AAPL = {**BTC, "name": "AAPL_USDT", "contract_type": "stocks",
        "quanto_multiplier": "0.01", "order_price_round": "0.01",
        "maintenance_rate": "0.01", "leverage_max": "20",
        "funding_interval": 14400, "last_price": "251.3"}
GONE = {**BTC, "name": "OLD_USDT", "in_delisting": True}


class FakeGate:
    """Routes a URL to a canned answer; records every URL asked."""

    def __init__(self, routes):
        self.routes = routes
        self.asked = []

    def __call__(self, url):
        self.asked.append(url)
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        ans = self.routes(u.path, q)
        if isinstance(ans, tuple):
            return ans
        return 200, json.dumps(ans).encode()


@pytest.fixture
def gate(monkeypatch, tmp_path):
    monkeypatch.setenv("TA_VENUE", "gate")
    gf.clear_spec_cache()
    gf._PRICES.update(at=0.0, px={})
    monkeypatch.setattr(gf, "PUBLIC_PAUSE_PATH", tmp_path / "public_pause_gate.json")
    monkeypatch.setattr(gf, "CONTRACTS_FILE", tmp_path / "gate_contracts.json")
    monkeypatch.setattr(gf, "_retry_sleep", lambda s: None)
    monkeypatch.setattr(gf, "_pause_sleep", lambda s: None)

    def install(routes):
        fake = FakeGate(routes)
        monkeypatch.setattr(gf, "_fetch", fake)
        return fake
    return install


def contracts_route(path, q):
    if path.endswith("/futures/usdt/contracts"):
        return [BTC, AAPL, GONE]
    for c in (BTC, AAPL, GONE):
        if path.endswith("/futures/usdt/contracts/" + c["name"]):
            return c
    if "/futures/usdt/contracts/" in path:
        return 400, b'{"label":"CONTRACT_NOT_FOUND"}'
    raise AssertionError(path)


def test_a_spec_answers_in_the_names_the_runner_reads(gate):
    gate(contracts_route)
    s = gf.contract_spec("BTC_USDT")
    assert s["symbol"] == "BTC_USDT"
    assert s["contractSize"] == pytest.approx(0.0001)
    assert s["priceUnit"] == pytest.approx(0.1) and s["priceScale"] == 1
    assert s["minVol"] == 1 and s["maxVol"] == 1000000 and s["volUnit"] == 1
    assert s["maintenanceMarginRate"] == pytest.approx(0.004)
    assert s["takerFeeRate"] == pytest.approx(0.00075)
    assert s["makerFeeRate"] == pytest.approx(-0.0001)
    assert s["maxLeverage"] == 125
    assert s["contract_type"] == "crypto" and s["funding_interval_h"] == 8


def test_one_list_fills_every_spec_for_an_hour(gate):
    fake = gate(contracts_route)
    gf.contract_spec("BTC_USDT")
    gf.contract_spec("AAPL_USDT")
    assert len(fake.asked) == 1, "one contract list answers every coin"


def test_a_coin_gate_does_not_list_is_an_error_naming_it(gate):
    gate(contracts_route)
    with pytest.raises(xe.VenueError, match="GPNSTOCK_USDT"):
        gf.contract_spec("GPNSTOCK_USDT")


def test_the_coin_list_and_kinds(gate):
    gate(contracts_route)
    assert gf.trading_symbols() == ["AAPL_USDT", "BTC_USDT"], \
        "a contract being delisted is not offered"
    kinds = gf.contract_types()
    assert kinds["AAPL_USDT"] == "stocks" and kinds["BTC_USDT"] == "crypto"
    rows = gf.list_contracts()
    assert [r["symbol"] for r in rows] == ["AAPL_USDT", "BTC_USDT"]
    assert rows[1]["contract_size"] == pytest.approx(0.0001)
    assert rows[1]["max_leverage"] == 125 and rows[0]["kind"] == "stocks"


def test_the_kinds_survive_gate_being_unreachable(gate):
    """The crypto/stocks filter and the daytime rule ask `kind()` all the
    time; a blip must not turn every stock into "unlisted"."""
    gate(contracts_route)
    assert gf.contract_types()["AAPL_USDT"] == "stocks"
    gf._CONTRACTS.update(at=0.0, rows={})       # memory cold, file warm
    gate(lambda p, q: (503, b"down"))
    assert gf.contract_types()["AAPL_USDT"] == "stocks"


def test_prices_from_one_ticker_call(gate):
    fake = gate(lambda p, q: [
        {"contract": "BTC_USDT", "last": "82739.8"},
        {"contract": "DEAD_USDT", "last": "0"},
        {"contract": "AAPL_USDT", "last": "251.3"}])
    px = gf.last_prices()
    assert px == {"BTC_USDT": 82739.8, "AAPL_USDT": 251.3}
    assert gf.last_prices() == px and len(fake.asked) == 1


def test_one_price_never_reads_zero(gate):
    gate(lambda p, q: [{"contract": q["contract"], "last": "0"}])
    with pytest.raises(xe.VenueError, match="BTC_USDT"):
        gf.last_price("BTC_USDT")
    gate(lambda p, q: (400, b'{"label":"CONTRACT_NOT_FOUND"}'))
    with pytest.raises(xe.VenueError, match="CONTRACT_NOT_FOUND"):
        gf.last_price("NOPE_USDT")


def book_route(path, q):
    if path.endswith("/order_book"):
        return {"asks": [{"s": 3, "p": "100"}, {"s": 4, "p": "100.5"}],
                "bids": [{"s": 5, "p": "99.5"}, {"s": 8, "p": "99"}]}
    return contracts_route(path, q)


def test_the_book_in_contracts_and_its_cost(gate):
    gate(book_route)
    assert gf.order_book("BTC_USDT") == {
        "asks": [[100.0, 3.0], [100.5, 4.0]], "bids": [[99.5, 5.0], [99.0, 8.0]]}
    # BTC's contract is 0.0001 coin: $0.0598 fills 6 contracts at mid 99.75
    got = gf.book_cost("BTC_USDT", 99.75 * 0.0001 * 6)
    assert got["slippage"] == pytest.approx((3 * 100 + 3 * 100.5) / 6 / 99.75 - 1)
    assert got["spread"] == pytest.approx(0.5 / 99.75)


def test_contracts_for_and_round_vol(gate):
    gate(contracts_route)
    # $100 at 82,739.8 with 0.0001 BTC a contract = 12.08 -> 12, rounded DOWN
    assert gf.contracts_for("BTC_USDT", 100.0, price=82739.8) == 12
    assert gf.round_vol("BTC_USDT", 12.9) == 12
    assert gf.round_vol("BTC_USDT", 0.5) == 0


def test_liquidation_distance_uses_gates_maintenance_rate(gate):
    gate(contracts_route)
    # 1/20 - 0.01 = 4.0% for the stock contract
    assert gf.liquidation_move_pct("AAPL_USDT", 20) == pytest.approx(4.0)


def test_funding_history_pages_back_until_an_empty_page(gate):
    pages = {None: [{"r": "0.0001", "t": 1791590400 - 28800 * i} for i in range(90)]}
    oldest = 1791590400 - 28800 * 89
    pages[str(oldest - 1)] = [{"r": "-0.0002", "t": oldest - 28800 * (i + 1)}
                              for i in range(10)]

    def route(path, q):
        if path.endswith("/funding_rate"):
            return pages.get(q.get("to"), [])
        return contracts_route(path, q)
    gate(route)
    h = gf.funding_history("BTC_USDT")
    assert len(h) == 100
    assert h == sorted(h, key=lambda d: d["settle_ms"]), "oldest first"
    assert h[0]["rate"] == pytest.approx(-0.0002) and h[0]["cycle_h"] == 8
    assert h[-1]["settle_ms"] == 1791590400 * 1000


def test_a_funding_page_that_fails_is_an_error_never_a_short_history(gate):
    calls = []

    def route(path, q):
        if path.endswith("/funding_rate"):
            calls.append(q)
            if len(calls) == 1:
                return [{"r": "0.0001", "t": 1791590400 - 28800 * i} for i in range(90)]
            return 500, b"oops"
        return contracts_route(path, q)
    gate(route)
    with pytest.raises(xe.VenueError, match="incomplete"):
        gf.funding_history("BTC_USDT")


def test_funding_now_is_one_call_per_day_rate(gate):
    gate(contracts_route)
    f = gf.funding_now("AAPL_USDT")
    assert f["cycle_h"] == 4 and f["rate"] == pytest.approx(0.00002)
    assert f["per_day"] == pytest.approx(0.00002 * 6)
    assert f["next_settle_ms"] == 1791619200 * 1000


def test_a_rate_limit_is_retried_and_pauses_every_other_process(gate):
    n = []

    def route(path, q):
        n.append(1)
        if len(n) < 3:
            return 429, b'{"label":"TOO_MANY_REQUESTS","message":"slow down"}'
        return [{"contract": "BTC_USDT", "last": "1"}]
    gate(route)
    assert gf.last_price("BTC_USDT") == 1.0
    assert len(n) == 3
    assert json.loads(gf.PUBLIC_PAUSE_PATH.read_text())["until"] > 0


def test_a_rate_limit_that_never_lifts_is_named_throttled(gate):
    gate(lambda p, q: (429, b'{"label":"TOO_MANY_REQUESTS"}'))
    with pytest.raises(xe.VenueThrottled):
        gf.last_price("BTC_USDT")


def test_an_answer_on_the_merits_is_not_retried(gate):
    fake = gate(lambda p, q: (400, b'{"label":"INVALID_PARAM_VALUE","message":"bad"}'))
    with pytest.raises(xe.VenueError, match="INVALID_PARAM_VALUE"):
        gf.last_price("BTC_USDT")
    assert len(fake.asked) == 1


def test_funding_history_stops_once_it_reaches_the_window(gate):
    """A backtest needs its own window, not since 2019: Gate serves about 30
    days a page, so BTC's whole history is ~85 calls."""
    asked = []

    def route(path, q):
        if path.endswith("/funding_rate"):
            asked.append(q.get("to"))
            top = int(q.get("to") or 1791590400)
            return [{"r": "0.0001", "t": top - 28800 * i} for i in range(90)]
        return contracts_route(path, q)
    gate(route)
    since = (1791590400 - 28800 * 100) * 1000
    h = gf.funding_history("BTC_USDT", since_ms=since)
    assert len(asked) == 2, "stopped at the page that reached the window"
    assert h[0]["settle_ms"] <= since


def test_the_archive_retries_a_busy_host_and_returns_a_404_at_once(monkeypatch):
    """Final review, Oct 10, 2026 (RCA-2026-10-10-F): a 503 from the archive
    was returned as it was, and the costs job dropped that hour as if Gate
    had never published it."""
    from tradingagents.dataflows import gate_futures as gf

    seen = []

    def fetch(u):
        seen.append(u)
        return (503, b"") if len(seen) < 3 else (200, b"gz")
    monkeypatch.setattr(gf, "_fetch", fetch)
    monkeypatch.setattr(gf, "_retry_sleep", lambda s: None)
    assert gf._fetch_archive("u") == (200, b"gz") and len(seen) == 3
    seen.clear()
    monkeypatch.setattr(gf, "_fetch", lambda u: seen.append(u) or (404, b""))
    assert gf._fetch_archive("u") == (404, b"") and len(seen) == 1
