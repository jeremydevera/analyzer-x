"""A practice exit pays the order book of the moment it closes, not the one
it opened on (Oct 15, 2026, RCA-2026-10-15-F).

QNTX 15m, #55D32617, Oct 12, 2026: both practice trades (A3H5UHQH and
PZTXYRL8) bought at 12:45:04pm and were stopped at 1:02pm. The closing side's
cost was read at 12:45:04pm, when the bids were thin: 0.520% of the trade.
The book at the exit, 1:02pm, asked 0.071%. Practice booked -1.47 each while
the backtest, which pays the book of the exit minute, booked -0.98.

Over the 52 practice trades closed by their own target or stop since the move
to Gate, the cost charged at entry sat 0.058% (mean, either way) from the
book the backtest pays at the exit minute; the book at the exit second sat
0.035% from it.

The position opened ten minutes before the cycle and its ticks are seconds
old: ONE timeline, the one a running runner sees (CLAUDE.md, "A test of
anything time-dependent must place its candles and its position on ONE
timeline"). The ticks are stamped when each test RUNS, not when the module
was collected: in a six-minute suite a tick stamped at collection is minutes
old by the time it is read, and an exit that old is not happening now.
"""
from __future__ import annotations

import json
import time

import pandas as pd
import pytest

from tradingagents import auto_trader as at, live_price as lp

COIN = "QNTX_USDT"
KEY = "ultosc_1h_sl3tp3"          # a key every test build has: SL 3%, TP 3%
ENTRY = 39.87
SL = round(ENTRY * (1 - 0.03), 5)
TP = round(ENTRY * (1 + 0.03), 5)
FEE = 0.00075
ENTRY_SIDE = 0.001689             # the asks at 12:45:04pm (the fill holds it)
EXIT_AT_ENTRY = 0.005198          # the bids at 12:45:04pm
EXIT_NOW = 0.000707               # the bids at the exit
HOUR = 3600
NOW = int(time.time())
OPENED_AT = NOW - 600
SIG_BAR = OPENED_AT - HOUR - 11


def _pos(side=1, **kw):
    p = {"side": side, "vol": 25, "entry": ENTRY,
         "tp": TP if side > 0 else round(ENTRY * 0.97, 5),
         "sl": SL if side > 0 else round(ENTRY * 1.03, 5),
         "margin": 5.0, "strategy": KEY, "entry_ts": SIG_BAR,
         "opened_at": OPENED_AT, "dry": True, "bracket": True, "step": 0,
         "trade_id": "PZTXYRL8",
         # what the gate read at entry: rt = 2 * (entry side + fee) + funding
         "rt_cost": 2 * (ENTRY_SIDE + FEE), "book_slippage": ENTRY_SIDE,
         "exit_slippage": EXIT_AT_ENTRY}
    p.update(kw)
    return p


def _frame(n, step, *, low=ENTRY, high=ENTRY, start=None):
    start = SIG_BAR - (n - 3) * step if start is None else start
    ts = [start + i * step for i in range(n)]
    return pd.DataFrame({"Date": pd.to_datetime(ts, unit="s"),
                         "Open": [ENTRY] * n, "High": [high] * n,
                         "Low": [low] * n, "Close": [ENTRY] * n,
                         "Volume": [1.0] * n})


class Fx:
    SIDE_OPEN_LONG, SIDE_CLOSE_SHORT = 1, 2
    SIDE_OPEN_SHORT, SIDE_CLOSE_LONG = 3, 4

    def __init__(self, *, minutes=None, book=None, book_raises=False):
        self.minutes = (_frame(120, 60, start=SIG_BAR) if minutes is None
                        else minutes)
        self.hours = _frame(240, HOUR)
        self.book = book
        self.book_raises = book_raises
        self.book_reads = 0

    def klines(self, symbol, interval, limit):
        return (self.minutes if interval == "Min1" else self.hours).copy()

    def contract_spec(self, symbol):
        return {"priceScale": 5, "maxVol": 0, "takerFeeRate": FEE,
                "contractSize": 0.1}

    def contracts_for(self, symbol, notional, price=None):
        return 25

    def book_cost(self, symbol, notional_usd=200.0, **kw):
        self.book_reads += 1
        if self.book_raises:
            raise RuntimeError("book unreadable")
        return dict(self.book)

    def position_history(self, symbol=None, page_size=20):
        return []

    def open_positions(self, symbol=None):
        return []

    def last_price(self, symbol):
        return ENTRY

    def submit(self, *a, **kw):
        return {"dry_run": True}


BOOK_NOW = {"spread": 0.00127, "slippage": 0.00064, "slippage_buy": 0.00064,
            "slippage_sell": EXIT_NOW, "book_exhausted": False,
            "book_exhausted_any": False}


def _feed(ticks):
    f = lp.PriceFeed()
    f._connected = True
    f._last_msg_at = time.time()
    for ts, px in ticks:
        f._on_message({"channel": "push.deal", "symbol": COIN,
                       "data": [{"p": px, "v": 1, "t": int(ts * 1000)}]})
    return f


@pytest.fixture
def sandbox(monkeypatch):
    for name in ("_BAR_CACHE", "_GATE_CACHE", "_GATE_LOGGED",
                 "_CYCLE_PRICES", "_CYCLE_GATES"):
        cache = getattr(at, name, None)
        if hasattr(cache, "clear"):
            cache.clear()
    monkeypatch.setattr(at, "MAX_SIGNAL_AGE_FRACTION", float("inf"))


def _close(fx, pos, ticks, monkeypatch):
    monkeypatch.setattr(lp, "FEED", _feed(ticks))
    slot = at.state_key(COIN, True, KEY)
    state = {slot: {"step": 0, "last_ts": {}, "position": pos}}
    at.process_symbol(COIN, {"strategies": [KEY], "coins": [COIN],
                             "margin": 5.0},
                      state, fx=fx, dry=True, tripped=frozenset({KEY}))
    assert state[slot]["position"] is None, "the stop was crossed"
    rows = [json.loads(x) for x in
            at.LEDGER_PATH.read_text(encoding="utf-8").strip().splitlines()]
    return [r for r in rows if r.get("action") == "exit"][-1]


def _pnl(pos, exit_side):
    """practice's own charge (`paper_round_trip`): the round trip read at
    entry, less the entry side twice (the fill holds one), plus the side the
    exit pays"""
    move = (pos["sl"] / pos["entry"] - 1) * pos["side"]
    cost = pos["rt_cost"] - 2 * pos["book_slippage"] + exit_side
    return round((move - cost) * pos["margin"] * at.LEVERAGE, 2)


def test_a_stop_crossed_now_pays_the_book_of_now(sandbox, monkeypatch):
    """The QNTX case: the stop prints on the live feed seconds ago."""
    fx = Fx(book=BOOK_NOW)
    pos = _pos()
    row = _close(fx, pos, [(time.time() - 5, SL - 0.03)], monkeypatch)
    assert row["why"] == "SL"
    assert row["pnl_est"] == _pnl(pos, EXIT_NOW), (
        "the closing side is paid at the book of the exit, not the 0.520% "
        "read at entry")
    assert row["exit_slippage"] == pytest.approx(EXIT_NOW)
    assert row["exit_cost_from"] == "the book when it closed"


def test_a_short_closes_by_buying_the_asks(sandbox, monkeypatch):
    """The exit pays the OTHER side: a short buys back from the asks."""
    fx = Fx(book=BOOK_NOW)
    pos = _pos(side=-1)
    row = _close(fx, pos, [(time.time() - 5, pos["sl"] + 0.03)], monkeypatch)
    assert row["exit_slippage"] == pytest.approx(BOOK_NOW["slippage_buy"])
    assert row["pnl_est"] == _pnl(pos, BOOK_NOW["slippage_buy"])


def test_an_exit_found_late_keeps_the_entry_reading(sandbox, monkeypatch):
    """A stop crossed ten minutes ago and found on the closed minutes (an
    outage, a reconnect): the book of NOW is not the book of that exit, so
    the reading taken at entry stays."""
    fx = Fx(book=BOOK_NOW, minutes=_frame(120, 60, start=SIG_BAR,
                                          low=SL - 0.05))
    pos = _pos()
    row = _close(fx, pos, [], monkeypatch)
    assert row["pnl_est"] == _pnl(pos, EXIT_AT_ENTRY)
    assert row["exit_cost_from"] == "the book when it opened"


def test_an_unreadable_book_keeps_the_entry_reading(sandbox, monkeypatch):
    """A book that cannot be read never stops the exit: the reading taken at
    entry is charged, as before, and the row says so."""
    fx = Fx(book_raises=True)
    pos = _pos()
    row = _close(fx, pos, [(time.time() - 5, SL - 0.03)], monkeypatch)
    assert row["pnl_est"] == _pnl(pos, EXIT_AT_ENTRY)
    assert row["exit_cost_from"] == "the book when it opened"


def test_a_position_without_an_entry_reading_is_charged_as_before(
        sandbox, monkeypatch):
    """A position opened before the gate kept the entry side
    (`book_slippage`) is charged by its old rule; the exit book is not
    read for it."""
    fx = Fx(book=BOOK_NOW)
    pos = _pos()
    del pos["book_slippage"], pos["exit_slippage"]
    row = _close(fx, pos, [(time.time() - 5, SL - 0.03)], monkeypatch)
    move = pos["sl"] / pos["entry"] - 1
    assert row["pnl_est"] == round((move - pos["rt_cost"]) * 5.0 * at.LEVERAGE, 2)
    assert fx.book_reads == 0


def test_a_cross_time_from_the_future_is_not_now(monkeypatch):
    """Harddev round 1: the freshness test was one-sided. A cross stamped in
    the future (a millisecond stamp read as seconds, a venue clock gone
    wrong) is not an exit happening now; it keeps the entry reading."""
    fx = Fx(book=BOOK_NOW)
    now = time.time()
    assert at.exit_book_slippage(COIN, _pos(), now - 5, fx=fx) == pytest.approx(EXIT_NOW)
    assert at.exit_book_slippage(COIN, _pos(), now * 1000, fx=fx) is None
    assert at.exit_book_slippage(COIN, _pos(), now + 3600, fx=fx) is None
    assert at.exit_book_slippage(COIN, _pos(), now - at.EXIT_BOOK_FRESH_S - 1,
                                 fx=fx) is None
    assert at.exit_book_slippage(COIN, _pos(), None, fx=fx) is None


def test_an_entry_reading_of_none_still_books_the_exit(sandbox, monkeypatch):
    """Harddev round 1: the exit row prints the reading it charged; a
    position whose stored reading is None must still close and say 0."""
    fx = Fx(book_raises=True)
    pos = _pos(exit_slippage=None)
    row = _close(fx, pos, [(time.time() - 5, SL - 0.03)], monkeypatch)
    assert row["exit_slippage"] == 0.0
    assert row["exit_cost_from"] == "the book when it opened"


def test_a_stop_found_in_the_minute_that_just_closed_pays_the_book_of_now(
        sandbox, monkeypatch):
    """Harddev round 3: the "found late" test passes whatever clock the
    minutes are read in, so this one pins the other side — a stop the live
    feed missed (a reconnect) and the minute walk finds in the minute that
    has just closed is an exit happening now, read in true epoch seconds."""
    now = int(time.time())
    last = now - now % 60 - 60                      # the newest closed minute
    ts = list(range(OPENED_AT - OPENED_AT % 60, last + 60, 60))
    lows = [SL - 0.05 if t == last else ENTRY for t in ts]
    minutes = pd.DataFrame({"Date": pd.to_datetime(ts, unit="s"),
                            "Open": [ENTRY] * len(ts), "High": [ENTRY] * len(ts),
                            "Low": lows, "Close": [ENTRY] * len(ts),
                            "Volume": [1.0] * len(ts)})
    fx = Fx(book=BOOK_NOW, minutes=minutes)
    pos = _pos()
    row = _close(fx, pos, [], monkeypatch)
    assert row["exit_cost_from"] == "the book when it closed"
    assert row["pnl_est"] == _pnl(pos, EXIT_NOW)
