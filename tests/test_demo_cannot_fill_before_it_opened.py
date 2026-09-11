"""A demo trade may only fill on price that printed AFTER its order existed.

Operator, `Sep 11, 2026`: *"how come trade id 7WZMH7EN lose in live and in demo
its still 100% winrate?"*

The receipt, from their own ledger and MEXC's own candles:

* `Sep 10, 2026 10:00pm` — the 9:00pm hourly bar closed, bb20 fired on
  CHYMSTOCK, and BOTH books opened LONG at 33.02, target 33.8455, stop 32.1945.
  Live is `7WZMH7EN`, demo is `ZXS6ETX5`, three seconds apart.
* `Sep 10, 2026 10:01pm` — the demo copy booked a WIN at 33.8455, 69 seconds
  after opening. CHYMSTOCK's high that minute was 33.02 and it kept falling:
  32.85, 32.80, 32.79.
* The prices that filled it printed `9:01pm`-`9:29pm`, up to 34.02 — 31 to 59
  minutes BEFORE the order existed.
* `Sep 11, 2026 9:00am` — the live twin hit its real stop at 32.19, -0.53.

ROOT CAUSE: a position stores ``entry_ts`` = the SIGNAL CANDLE's start, and
the paper exit check walked one-minute bars with ``t > pos["entry_ts"]``. On a
1h strategy that replays the hour before the entry; on 4h, four hours. The
live book is immune because its bracket rests at MEXC and can only fill on
prints that come after it is placed.

Measured over the whole demo book: 8 of 39 closed demo trades were decided
this way, worth +12.81 USDT of PnL that never happened, and the demo win rate
read 64% where the truth is 56%.

THE RULE NOW, one expression in one helper (``_bars_exposed_to``): a bar
counts when it was STILL RUNNING at the moment the order went out, or started
after it — ``t + bar_seconds > opened_at``. That is exactly the backtest's own
convention (enter at a bar's open, test that same bar's range), so the demo
book and the grid answer the same question, and neither can reach back into a
bar that had already closed before the trade existed.
"""
from __future__ import annotations

import time

import pandas as pd
import pytest

from tradingagents import auto_trader as at


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """The state `conftest` already isolates, plus the module caches — a
    barrier walk reading another test's candles proves nothing."""
    for name in ("_BAR_CACHE", "_GATE_CACHE", "_GATE_LOGGED",
                 "_CYCLE_PRICES", "_CYCLE_GATES"):
        cache = getattr(at, name, None)
        if hasattr(cache, "clear"):
            cache.clear()
    # These candles sit hours in the past on purpose; the staleness guard is
    # exercised by its own test.
    monkeypatch.setattr(at, "MAX_SIGNAL_AGE_FRACTION", float("inf"))
    return tmp_path

COIN = "CHYMSTOCK_USDT"
KEY_1H = "bb20_1h_sl25tp25"
KEY_4H = "macddiv_4h_sl25tp3"

# The operator's own numbers.
ENTRY = 33.02
TP = 33.8455
SL = 32.1945
PRE_ENTRY_HIGH = 34.02      # what printed at 9:10pm, before the order
POST_ENTRY_HIGH = 33.02     # what printed at 10:00pm, after it
POST_ENTRY_LOW = 32.79

HOUR = 3600
NOW = int(time.time())
SIG_BAR = NOW - 3 * HOUR            # the 9:00pm candle
OPENED_AT = SIG_BAR + HOUR + 11     # the order, 11s into the 10:00pm bar


def _pos(*, strategy=KEY_1H, opened_at=OPENED_AT, entry_ts=SIG_BAR,
         drop_opened_at=False):
    pos = {"side": 1, "vol": 6, "entry": ENTRY, "tp": TP, "sl": SL,
           "margin": 1.0, "strategy": strategy, "entry_ts": entry_ts,
           "opened_at": opened_at, "dry": True, "bracket": True, "step": 0,
           "rt_cost": 0.0, "trade_id": "ZXS6ETX5"}
    if drop_opened_at:
        pos.pop("opened_at")
    return pos


def _minutes(*, breach_after_entry=False):
    """One-minute bars: the hour BEFORE the order breaches the target, the
    minutes after it do not. This is CHYMSTOCK's real shape that night."""
    rows = []
    for i in range(0, 120):                       # SIG_BAR .. SIG_BAR+2h
        t = SIG_BAR + i * 60
        before = t < OPENED_AT - 11               # the pre-entry hour
        hi = PRE_ENTRY_HIGH if before else POST_ENTRY_HIGH
        lo = 32.91 if before else POST_ENTRY_LOW
        if breach_after_entry and t == OPENED_AT + 10 * 60 - 11:
            hi = PRE_ENTRY_HIGH                   # a REAL touch, 10 min in
        rows.append((t, hi, lo))
    return pd.DataFrame({
        "Date": pd.to_datetime([r[0] for r in rows], unit="s"),
        "Open": [ENTRY] * len(rows),
        "High": [r[1] for r in rows],
        "Low": [r[2] for r in rows],
        "Close": [ENTRY] * len(rows),
        "Volume": [1.0] * len(rows)})


def _hours(bar_seconds=HOUR, n=240):
    """Benign hourly history: nothing here may breach either barrier, so the
    fine-grained walk is the only thing that can decide these tests."""
    start = SIG_BAR - (n - 3) * bar_seconds
    ts = [start + i * bar_seconds for i in range(n)]
    return pd.DataFrame({
        "Date": pd.to_datetime(ts, unit="s"),
        "Open": [ENTRY] * n,
        "High": [POST_ENTRY_HIGH] * n,
        "Low": [POST_ENTRY_LOW] * n,
        "Close": [ENTRY] * n,
        "Volume": [1.0] * n})


class Fx:
    """Answers each interval with its own frame — the Min1 pull is the one
    that carried the bug, so a double that returns one frame for everything
    cannot see it."""

    SIDE_OPEN_LONG, SIDE_CLOSE_SHORT = 1, 2
    SIDE_OPEN_SHORT, SIDE_CLOSE_LONG = 3, 4
    max_vol = 0

    def __init__(self, minutes, hours, last=ENTRY):
        self.minutes, self.hours, self._last = minutes, hours, last
        self.orders: list = []
        self.stops: list = []

    def klines(self, symbol, interval, limit):
        return (self.minutes if interval == "Min1" else self.hours).copy()

    def contracts_for(self, symbol, notional, price=None):
        return int(notional)

    def contract_spec(self, symbol):
        return {"priceScale": 4, "maxVol": 0}

    def book_cost(self, symbol, notional_usd=200.0):
        return {"spread": 0.0002, "slippage": 0.0002, "book_exhausted": False}

    def position_history(self, symbol=None, page_size=20):
        return []

    def open_positions(self, symbol=None):
        return []

    def last_price(self, symbol):
        return float(self._last)

    def submit(self, symbol, side, vol, *, leverage, dry_run=True):
        self.orders.append((symbol, side, vol))
        return {"dry_run": dry_run}

    def place_position_stop(self, *a, **kw):
        self.stops.append(kw)
        return {"dry_run": True}

    def verify_position_stop(self, symbol, position_id):
        return {"protected": True}


def _cycle(fx, pos, *, strategy=KEY_1H):
    """Drive the RUNNER's own entry point, not a layer below it."""
    slot = at.state_key(COIN, True, strategy)
    state = {slot: {"step": 0, "last_ts": {}, "position": pos}}
    at.process_symbol(COIN,
                      {"strategies": [strategy], "coins": [COIN],
                       "margin": 1.0},
                      state, fx=fx, dry=True,
                      tripped=frozenset({strategy}))   # exits only, no entries
    return state[slot]


# ----------------------------------------------------------------- the bug
def test_the_hour_before_the_order_cannot_close_the_demo_trade(sandbox):
    """ZXS6ETX5 itself: 34.02 printed at 9:10pm, the order went out at
    10:00:11pm, and nothing after that reached 33.8455."""
    fx = Fx(_minutes(), _hours())
    slot = _cycle(fx, _pos())
    assert slot["position"] is not None, (
        "the demo book filled on price from before the order existed — "
        "this is exactly how ZXS6ETX5 booked +0.41 while the live twin "
        "7WZMH7EN lost 0.53")


def test_the_old_floor_is_what_filled_it(sandbox):
    """The defect, pinned as arithmetic so it can never come back quietly:
    the same bars, the same position, the two floors, opposite answers."""
    fine = at._closed_bars(_minutes(), 60)
    pos = _pos()

    old_hi, old_lo = [], []          # `if t > pos["entry_ts"]` — what shipped
    for h, lo, t in zip(fine["High"], fine["Low"],
                        (int(d.timestamp()) for d in fine["Date"]),
                        strict=False):
        if t > pos["entry_ts"]:
            old_hi.append(float(h))
            old_lo.append(float(lo))
    assert at._dry_fill(pos, old_hi, old_lo) == "TP", \
        "the old floor must reproduce the invented win, or this guard is blind"

    new_hi, new_lo = at._bars_exposed_to(fine, at._order_live_from(pos), 60)
    assert at._dry_fill(pos, new_hi, new_lo) is None
    assert len(new_hi) < len(old_hi), "the pre-entry hour must be gone"


def test_a_four_hour_strategy_replayed_four_hours(sandbox):
    """The worst case in the operator's book: three STBL macddiv 4h trades
    booked +2.76 each on `Sep 09, 2026 8:01pm`, 67 seconds after opening, off
    price from 4:00pm-8:00pm. Their true outcome was the STOP at 10:04pm."""
    fx = Fx(_minutes(), _hours(bar_seconds=4 * HOUR, n=60))
    slot = _cycle(fx, _pos(strategy=KEY_4H,
                           entry_ts=OPENED_AT - 4 * HOUR - 11),
                  strategy=KEY_4H)
    assert slot["position"] is not None


# ------------------------------------------------------- no regression
def test_a_real_touch_after_the_order_still_closes_the_trade(sandbox):
    """The fix must not make the demo book blind. Same bars, except the
    target is genuinely touched ten minutes AFTER the order."""
    fx = Fx(_minutes(breach_after_entry=True), _hours())
    slot = _cycle(fx, _pos())
    assert slot["position"] is None, \
        "a barrier touched after the order must still fill the demo trade"


def test_the_bar_the_order_opened_in_still_counts(sandbox):
    """`_bars_exposed_to` keeps the bar that was STILL RUNNING when the order
    went out — the backtest's own convention, and what keeps the live
    safety net able to see the entry bar."""
    fine = at._closed_bars(_minutes(), 60)
    hi, _lo = at._bars_exposed_to(fine, OPENED_AT, 60)
    # the minute that CONTAINS opened_at starts 11s before it and is kept
    kept = at._bars_exposed_to(fine, OPENED_AT, 60)[0]
    assert len(kept) == len(hi) > 0
    # ...while a bar that had already CLOSED before it is not
    one_bar_earlier = at._bars_exposed_to(fine, OPENED_AT + 49, 60)[0]
    assert len(one_bar_earlier) == len(hi) - 1


# ------------------------------------------------------- degenerate state
def test_a_position_without_opened_at_falls_back_to_the_candle(sandbox):
    """State files written before `opened_at` existed must still be managed —
    the fallback is the old floor, never a crash and never nothing."""
    pos = _pos(drop_opened_at=True)
    assert at._order_live_from(pos) == SIG_BAR
    fx = Fx(_minutes(), _hours())
    _cycle(fx, pos)          # must not raise


def test_a_position_that_cannot_say_when_it_opened_fills_on_nothing(sandbox):
    """No floor at all means NO barrier walk. An invented fill is worse than
    a late one, and the live-price check still guards the position."""
    assert at._order_live_from({}) == 0
    fine = at._closed_bars(_minutes(), 60)
    assert at._bars_exposed_to(fine, 0, 60) == ([], [])


# ------------------------------------------------------------- the guard
def test_every_barrier_walk_gets_its_bars_from_the_one_helper():
    """`widen the guard, not just the fix` (CLAUDE.md).

    A grep for the two broken lines would pass the moment somebody writes a
    THIRD walk, so this reads the code's SHAPE instead: every `_dry_fill`
    call must be handed bars that came out of `_bars_exposed_to`, never a
    comprehension built on the spot. Reading `entry_ts` elsewhere is fine and
    necessary — the ledger records it, and `_order_live_from` falls back to
    it; what may never happen again is a bar filter keyed on it.
    """
    import ast

    body = open(at.__file__, encoding="utf-8").read()
    assert 'if t > pos["entry_ts"]' not in body, \
        "this is the expression that invented 8 demo trades"

    tree = ast.parse(body)
    exposed: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and getattr(node.value.func, "id", "") == "_bars_exposed_to"):
            for tgt in node.targets:
                for name in ast.walk(tgt):
                    if isinstance(name, ast.Name):
                        exposed.add(name.id)
    assert exposed, "nothing sources its bars from the helper any more"

    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_dry_fill"]
    assert len(calls) >= 2, "the coarse walk and the one-minute walk"
    for call in calls:
        for arg in call.args[1:3]:
            assert isinstance(arg, ast.Name), (
                f"line {call.lineno}: bars built inline instead of by "
                "_bars_exposed_to — that is how the pre-entry hour got in")
            assert arg.id in exposed, (
                f"line {call.lineno}: {arg.id} did not come from "
                "_bars_exposed_to")
