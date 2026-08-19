"""An open position must keep being managed after its strategy leaves the book.

Moving a strategy to DEMO-only excludes it from the live book's ENTRIES. It
must not also abandon a real position that strategy already has open — that
position still has real money in it and still needs its exit tracked.

Measured on 2026-08-18: XAUT_USDT was moved to demo-only while a real short
was open. `process_symbol` then returned before the exit check on every live
cycle, the exchange stopped the position out at 01:22 on the 17th, and the bot
never booked it. The local book claimed an open position for over a day and
the -0.85 never reached the ledger.

The same rule already exists for tripped strategies — "excluded from ENTRIES
only" — and this is the identical failure one filter later.
"""
import pytest

import tradingagents.auto_trader as at


class FX:
    """Records what the cycle asked for."""

    def __init__(self):
        self.klines_called = []

    def klines(self, symbol, interval, n):
        # Record the attempt, then stop the cycle. Reaching this call IS the
        # thing under test: it means the exit path was not skipped.
        self.klines_called.append(interval)
        raise _Reached()


class _Reached(Exception):
    """Raised once the cycle gets as far as fetching candles."""


def _settings(book):
    return {"strategies": ["mom15_1h_g"],
            "strategy_coins": {"mom15_1h_g": ["XAUT_USDT"]},
            "strategy_books": {"mom15_1h_g": book}}


def _state_with_open_real():
    return {"XAUT_USDT": {"step": 0, "last_ts": {},
                          "position": {"side": -1, "entry": 4353.0,
                                       "tp": 4248.5, "sl": 4387.8,
                                       "margin": 5.0, "vol": 22,
                                       "strategy": "mom15_1h_g",
                                       "entry_ts": 1785000000,
                                       "opened_at": 1785000000,
                                       "dry": False}}}


def test_demo_only_strategy_with_an_open_real_position_still_runs_its_exit():
    """The bug. Book is paper-only, a REAL position is open, and the live
    cycle must still reach the exit path rather than returning early."""
    fx, state = FX(), _state_with_open_real()
    with pytest.raises(_Reached):
        at.process_symbol("XAUT_USDT", _settings(["paper"]), state, fx=fx,
                          dry=False)
    assert fx.klines_called, (
        "live cycle returned before fetching candles — an open real position "
        "was left unmanaged because its strategy is demo-only")


def test_demo_only_strategy_with_no_open_position_still_skips_the_live_book():
    """The feature must survive the fix: with nothing open, a paper-only
    strategy places no live orders and does no live work."""
    fx = FX()
    state = {"XAUT_USDT": {"step": 0, "last_ts": {}, "position": None}}
    at.process_symbol("XAUT_USDT", _settings(["paper"]), state, fx=fx, dry=False)
    assert fx.klines_called == [], (
        "a demo-only strategy with no open position must not touch the live "
        "book at all")


def test_a_paper_position_does_not_drag_in_the_live_book():
    """An open PAPER position is not a reason to run the live cycle."""
    fx = FX()
    state = {"XAUT_USDT#paper": {"step": 0, "last_ts": {},
                                 "position": {"side": 1, "entry": 4377.2,
                                              "tp": 4482.0, "sl": 4342.0,
                                              "margin": 5.0, "vol": 22,
                                              "strategy": "mom15_1h_g",
                                              "dry": True}}}
    at.process_symbol("XAUT_USDT", _settings(["paper"]), state, fx=fx, dry=False)
    assert fx.klines_called == []


def test_off_strategy_with_an_open_real_position_is_also_managed():
    """Unticking a strategy entirely must not abandon its open money either."""
    fx, state = FX(), _state_with_open_real()
    s = {"strategies": [], "strategy_coins": {"mom15_1h_g": ["XAUT_USDT"]},
         "strategy_books": {"mom15_1h_g": []}}
    with pytest.raises(_Reached):
        at.process_symbol("XAUT_USDT", s, state, fx=fx, dry=False)
    assert fx.klines_called, (
        "an unticked strategy's open real position was left unmanaged")


class FXOrders(FX):
    """Lets the cycle run far enough to prove no ORDER is placed."""

    def __init__(self, df):
        super().__init__()
        self.df = df
        self.submitted = []

    def klines(self, symbol, interval, n):
        self.klines_called.append(interval)
        return self.df

    def submit(self, *a, **k):
        self.submitted.append((a, k))
        raise AssertionError(
            "a REAL order was placed for a strategy that is not in this book")

    def contract_spec(self, symbol):
        return {"priceScale": 2, "contractSize": 0.001, "volUnit": 1,
                "minVol": 1, "maxVol": 25000, "maintenanceMarginRate": 0.005}

    def last_price(self, symbol):
        return 4404.0

    def open_positions(self, symbol=None):
        return []


def test_the_rescue_never_places_a_new_order():
    """The regression that cost real money: rescuing an open position must
    track its exit and NOTHING else. On 2026-08-18 it exited a stopped-out
    XAUT short and opened a fresh real long one second later."""
    import pandas as pd
    rows = [{"Date": pd.Timestamp("2026-08-01") + pd.Timedelta(hours=i),
             "Open": 4400.0 + i, "High": 4410.0 + i,
             "Low": 4390.0 + i, "Close": 4400.0 + i} for i in range(400)]
    fx = FXOrders(pd.DataFrame(rows))
    state = _state_with_open_real()
    # position already closed on the venue, so the cycle books the exit and
    # would be free to re-enter — it must not.
    at.process_symbol("XAUT_USDT", _settings(["paper"]), state, fx=fx,
                      dry=False)
    assert fx.submitted == [], fx.submitted
