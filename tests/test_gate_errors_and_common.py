"""The pieces both exchanges share: error names, the book walk, the chase
guard and the funding summary (spec D3, Oct 10, 2026).

`book_cost_from` must answer exactly what `mexc_futures.book_cost` answered
before it was moved — the numbers below were produced by the pre-move code
on the same book."""
import pytest

from tradingagents.dataflows import exchange_common as xc
from tradingagents.dataflows import exchange_errors as xe


def test_every_venue_error_shares_one_family():
    from tradingagents.dataflows import mexc_futures as mf

    assert issubclass(mf.MexcFuturesError, xe.VenueError)
    assert issubclass(mf.MexcFuturesThrottled, xe.VenueThrottled)
    assert issubclass(mf.MexcFuturesAuthFailed, xe.VenueAuthFailed)
    assert issubclass(mf.MexcFuturesEdgeBlocked, xe.VenueEdgeBlocked)
    assert issubclass(mf.MexcFuturesForbidden, xe.VenueForbidden)
    # the neutral names travel through each adapter, so `fx.VenueError` works
    assert mf.VenueError is xe.VenueError
    # an auth failure and an edge block are never "a missing scope"
    assert not issubclass(xe.VenueAuthFailed, xe.VenueForbidden)
    assert not issubclass(xe.VenueEdgeBlocked, xe.VenueForbidden)


BOOK = {"asks": [[100.0, 3.0], [100.5, 4.0], [101.0, 10.0]],
        "bids": [[99.5, 5.0], [99.0, 8.0]]}


def test_the_walk_is_the_one_mexc_used():
    # contract size 0.1 at mid 99.75: $100 wants 100 / 9.975 = 10.0251 contracts
    got = xc.book_cost_from(BOOK, contract_size=0.1, notional_usd=100.0,
                            symbol="X_USDT")
    assert got["mid"] == pytest.approx(99.75)
    assert got["spread"] == pytest.approx(0.5 / 99.75)
    want = 100.0 / (0.1 * 99.75)
    # 3 @ 100 + 4 @ 100.5 + the rest @ 101
    cost = 3 * 100 + 4 * 100.5 + (want - 7) * 101
    assert got["slippage"] == pytest.approx(cost / want / 99.75 - 1)
    assert got["book_exhausted"] is False
    assert got["notional_tested"] == 100.0 and got["symbol"] == "X_USDT"


def test_a_book_that_cannot_fill_says_so_and_charges_its_far_end():
    got = xc.book_cost_from(BOOK, contract_size=1.0, notional_usd=10_000.0,
                            symbol="X_USDT")
    assert got["book_exhausted"] is True
    assert got["slippage"] >= 101.0 / 99.75 - 1


def test_an_empty_or_one_sided_book_is_an_error_not_a_zero_cost():
    with pytest.raises(xe.VenueError, match="X_USDT"):
        xc.book_cost_from({"asks": [], "bids": [[1.0, 1.0]]}, contract_size=1,
                          notional_usd=100, symbol="X_USDT")
    with pytest.raises(xe.VenueError, match="cannot measure"):
        xc.book_cost_from(BOOK, contract_size=0.0, notional_usd=100,
                          symbol="X_USDT")


def test_the_sell_side_walks_the_bids():
    got = xc.book_cost_from(BOOK, contract_size=1.0, notional_usd=99.75 * 6,
                            symbol="X_USDT", side="sell")
    # 5 @ 99.5 + 1 @ 99.0 = 596.5 over 6: mid / avg - 1
    assert got["slippage"] == pytest.approx(99.75 / (596.5 / 6) - 1)


def test_chase_guard_is_shared_and_unchanged():
    from tradingagents.dataflows import mexc_futures as mf

    assert mf.chase_guard is xc.chase_guard
    ok, why = xc.chase_guard(100.0, 100.4, 0.5)
    assert ok and "within" in why
    ok, why = xc.chase_guard(100.0, 101.0, 0.5)
    assert not ok and "ran +1.00%" in why
    assert xc.chase_guard(0, 1, 1) == (False, "no reference price")


def test_funding_summary_from_a_history():
    hist = [{"settle_ms": 0, "rate": 0.0001, "cycle_h": 8},
            {"settle_ms": 86_400_000, "rate": -0.0003, "cycle_h": 8}]
    s = xc.funding_summary_from(hist, "X_USDT")
    assert s["settlements"] == 2 and s["available"]
    assert s["long_total"] == pytest.approx(0.0002)
    assert s["long_daily"] == pytest.approx(0.0002)
    assert xc.funding_summary_from([], "X_USDT") == {
        "symbol": "X_USDT", "settlements": 0, "available": False}
