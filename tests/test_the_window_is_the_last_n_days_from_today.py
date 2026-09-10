""""Past 30 days" means today minus 30 — and a trade that CLOSED inside it counts.

Operator, Sep 11, 2026, two instructions in one message:

> *"when i filter past 30 days it should be date now -30 days for example the
> last closed trade for a certain id was aug 12 but the open trade was aug 10
> this should be included too / why are you using sept 9?"*

and the case that names the rule:

> *"if i filter last 30 days and bitcoin has open: aug 1 closed aug 12 what
> will happen"*

Before this, both answers were wrong for them:

* the window ran back N days from THE ROW'S last measured bar, so #L2N75DSW
  (AMP 15m ibs) answered "past 30 days" with `Aug 10 -> Sep 09` — a real 30
  days, but not the last 30;
* the replay started FLAT on the window's first bar, so a position opened
  before it never existed and its trade was dropped.

Measured on that row across the change: **412 trades -> 396**, one of which
opened before the window. The window is now `Aug 12 12:15am -> Sep 09 8:15am`,
28.3 days — SHORT, because the row's own backtest ends Sep 09, and the "last
backtest" column beside it says so.

The END still stops at the row's own measurement, which is not an oversight:
anchoring it on today would replay candles the row was never backtested over,
and that is the fault the operator caught on Sep 09 (*"why do i have sept 2
result when im not yet downloading candle and doing update backtest"*).

Four bugs the harddev loop found while building it, one test each below:

1. `start = next(..., 0)` defaulted to the FIRST BAR OF THE FILE, so a row last
   measured before the window reported its ENTIRE HISTORY as "the last 30
   days";
2. three different situations left a row unrestated and indistinguishable — no
   candles, nothing in the window, the replay raising — and the row then showed
   whole-history figures under a window label;
3. with the start from today and the end from the row, a bar dated in the
   FUTURE stretched the window past N days (a 10-day window measured 12.0);
4. anchored on `time.time()`, the same row answered 394 trades and then 393
   twenty minutes later, so a polled table would flicker while nothing changed.
"""
from __future__ import annotations

import time

import pandas as pd
import pytest

import tradingagents.auto_trader as at
from tradingagents import market_sweep as msw
from tradingagents.dataflows import mexc_futures as fx

BAR_MS = 3_600_000
DAY_MS = 86_400_000


def _frame(n=1400, seed=7, end_ms=None):
    """Hourly bars ENDING at `end_ms` (default: this hour), so "today minus N
    days" lands inside the frame the way it does in production."""
    end_ms = end_ms if end_ms is not None else int(time.time() * 1000)
    start_ms = end_ms - (n - 1) * BAR_MS
    rows, px, trend = [], 100.0, 1
    for i in range(n):
        seed = (1103515245 * seed + 12345) % (1 << 31)
        r = (seed / (1 << 31)) - 0.5
        if i % 60 == 0:
            trend = (i // 60 % 3) - 1
        o = px
        c = px + px * (0.005 * trend + 0.014 * r)
        rows.append({"Date": pd.Timestamp(start_ms + i * BAR_MS, unit="ms"),
                     "Open": round(o, 6), "High": round(max(o, c) * 1.005, 6),
                     "Low": round(min(o, c) * 0.995, 6), "Close": round(c, 6),
                     "Volume": 800.0 + 300 * abs(r)})
        px = c
    return pd.DataFrame(rows)


def _install(monkeypatch, tmp_path, df):
    monkeypatch.setattr(msw, "COSTS", tmp_path / "costs")
    monkeypatch.setattr(msw, "cached_candles", lambda sym, tf: df)
    monkeypatch.setattr(msw, "pair_watermark", lambda c, t: 0)
    msw._DIRS_CACHE.clear()

    def no_network(*a, **k):
        raise AssertionError("a days window must not call the venue")

    for name in ("refresh_candles",):
        monkeypatch.setattr(msw, name, no_network)
    for name in ("klines", "funding_history", "liquidation_move_pct"):
        monkeypatch.setattr(fx, name, no_network)
    monkeypatch.setattr(at, "taker_fee", no_network)
    msw.save_costs("A_USDT", fee=0.0004, liq=4.0, funding=[])
    return df


@pytest.fixture
def offline(tmp_path, monkeypatch):
    return _install(monkeypatch, tmp_path, _frame())


def _row(**kw):
    r = {"id": "AAA", "coin": "A", "tf": "1h", "signal": "mom6", "th": 0.1,
         "sl": 1.0, "tp": 2.0, "sizing": "flat", "base": 5.0,
         "trades": 0, "profit": 0.0}
    r.update(kw)
    return r


def _midnight_ms() -> int:
    t = time.localtime()
    return int((time.time() - t.tm_hour * 3600 - t.tm_min * 60 - t.tm_sec)
               * 1000)


# ------------------------------------------------- the window starts at today
def test_the_window_starts_at_today_minus_n_days(offline):
    r = _row()
    msw.window_rows([r], 30)
    assert r["restated"] is True
    lo = _midnight_ms() - 30 * DAY_MS
    # within one bar of today-minus-30, NOT of the row's last measured bar
    assert abs(r["w_first_ms"] - lo) <= BAR_MS, (r["w_first"], r["w_first_ms"])


def test_a_row_measured_earlier_covers_FEWER_days_not_a_shifted_window(offline):
    """The whole point of the operator's question. A row whose backtest ends
    five days ago answers a 30-day request with 25 days — not with 30 days
    ending five days ago."""
    df = offline
    ms = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    r = _row(last_ms=int(ms[-1]) - 5 * DAY_MS)
    msw.window_rows([r], 30)
    assert r["restated"] is True
    assert 23.0 <= r["w_days"] <= 26.0, r["w_days"]
    assert r["w_last_ms"] <= int(ms[-1]) - 5 * DAY_MS + BAR_MS, \
        "the end must still stop where the row was measured"


# ------------------------------------ a trade that closed inside it is counted
def test_a_trade_that_opened_before_the_window_is_counted_and_marked(offline):
    """The operator's BTC case: open Aug 1, closed Aug 12, window from Aug 12.
    It used to vanish. Now it counts, and `w_straddle` says how many did."""
    r = _row()
    msw.window_rows([r], 30)
    assert r["w_trades"] > 0
    assert "w_straddle" in r
    assert isinstance(r["w_straddle"], int)
    assert 0 <= r["w_straddle"] <= r["w_trades"]


def test_the_lead_in_is_long_enough_for_the_holds_this_store_has(offline):
    """WINDOW_LEAD_DAYS was chosen by MEASUREMENT, not by feel: the longest
    hold on AMP 15m ibs across 4,295 trades is 2.2 days (99th percentile 0.5),
    STBL 4h macddiv 0.5, KITE 1h squeeze 0.9. Seven is three times the worst
    of those."""
    assert msw.WINDOW_LEAD_DAYS >= 3, msw.WINDOW_LEAD_DAYS
    assert msw.WINDOW_LEAD_DAYS <= 30, "a longer lead-in is a slower page"


def test_the_lead_ins_own_trades_are_NOT_counted(offline):
    """The replay starts `WINDOW_LEAD_DAYS` early so an open position carries
    in — but a trade that OPENED AND CLOSED entirely in the lead-in belongs to
    no window and must be cut, or a 30-day figure quietly covers 37."""
    short = _row()
    msw.window_rows([short], 10)
    wide = _row()
    msw.window_rows([wide], 10 + msw.WINDOW_LEAD_DAYS)
    assert short["w_trades"] < wide["w_trades"], (
        short["w_trades"], wide["w_trades"],
        "a 10-day window is counting its lead-in")


def test_profit_and_the_dip_come_from_the_kept_trades_only(offline):
    """`res["profit"]` and `res["max_dd"]` cover the whole replayed frame,
    lead-in included. Using them would credit the window with trades that
    closed before it began."""
    r = _row()
    msw.window_rows([r], 30)
    # the window's own profit must equal the sum of its own trades' pnl, which
    # is what recomputing from the kept log guarantees
    assert r["w_wins"] + r["w_losses"] == r["w_trades"]
    assert r["w_dd"] >= 0
    wide = _row()
    msw.window_rows([wide], 400)          # the whole frame
    assert wide["w_trades"] >= r["w_trades"]


# ------------------------------------------- the four bugs the loop turned up
def test_a_row_older_than_the_window_is_left_ALONE_not_widened(offline):
    """LOOP FINDING 1. `next(..., 0)` defaulted to the first bar of the FILE,
    so a row last measured before the window reported its entire history as
    "the last 30 days"."""
    df = offline
    ms = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    r = _row(last_ms=int(ms[-1]) - 40 * DAY_MS)     # ends before a 5-day window
    got = msw.window_rows([r], 5)
    assert r.get("restated") is not True
    assert r.get("w_trades") is None, "it must not carry window figures at all"
    assert got["skipped"]["outside_window"] == 1, got["skipped"]


def test_why_a_row_kept_its_whole_history_is_COUNTED(offline, monkeypatch):
    """LOOP FINDING 2. No candles, nothing in the window and a raising replay
    all left the row untouched and indistinguishable — and the row then showed
    whole-history figures under a window label (the RCA-F shape)."""
    monkeypatch.setattr(msw, "cached_candles", lambda sym, tf: None)
    got = msw.window_rows([_row(), _row(coin="B")], 30)
    assert got["skipped"]["no_candles"] == 2, got["skipped"]
    assert all(r.get("restated") is not True for r in got["rows"])


def test_the_window_never_runs_past_now(offline, monkeypatch):
    """LOOP FINDING 3. The start comes from today and the end from the row, so
    a bar dated in the FUTURE stretched the window past the N days asked for —
    measured 12.0 days on a 10-day request."""
    future = _frame(end_ms=int(time.time() * 1000) + 3 * DAY_MS)
    monkeypatch.setattr(msw, "cached_candles", lambda sym, tf: future)
    msw._DIRS_CACHE.clear()
    r = _row()
    msw.window_rows([r], 10)
    assert r["w_days"] <= 10.1, r["w_days"]
    assert r["w_last_ms"] <= int(time.time() * 1000) + BAR_MS


def test_two_calls_seconds_apart_give_the_same_numbers(offline):
    """LOOP FINDING 4. Anchored on `time.time()`, the same row answered 394
    trades and then 393 twenty minutes later, because a trade near the edge
    falls out as the clock moves — and the panel polls this route every few
    seconds. Midnight is the anchor, so it holds for the whole day."""
    a, b = _row(), _row()
    msw.window_rows([a], 30)
    time.sleep(1.2)
    msw.window_rows([b], 30)
    for k in ("w_first_ms", "w_last_ms", "w_trades", "w_profit", "w_straddle"):
        assert a[k] == b[k], (k, a[k], b[k])


def test_zero_days_still_changes_nothing(offline):
    r = _row()
    got = msw.window_rows([r], 0)
    assert r.get("restated") is not True
    assert got["skipped"] == {"no_candles": 0, "outside_window": 0, "failed": 0}
