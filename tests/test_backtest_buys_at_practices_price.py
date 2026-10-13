"""The backtest buys at the price practice pays (operator, Oct 13, 2026:
"Yes fix it", after "Theres still difference and not matched why?").

Practice buys at the best ask (sells at the best bid) a few seconds after the
candle closes (`auto_trader.tradable_price`) and charges no separate entry
cost on top: the best price already holds the half-spread
(`paper_round_trip`: `rt - 2*slip + exit_slip`). The backtest bought at the
next candle's OPEN and then charged the entry minute's whole walk cost.

Measured on room #55D32617, CLANKER 15m choch:
* Oct 11, 2026 1:30am: the backtest bought at 13.21 (the open), practice at
  13.18, and Gate's recorded ask for that minute was 13.18.
* Oct 11, 2026 7:15pm: 13.20 against 13.19, with a recorded ask of 13.19.

Practice reached its targets (+0.93, +0.90). The backtest's targets, a cent
higher, were missed: the 10:39pm high was 13.35, against practice's target of
13.348 and the backtest's 13.358. Both backtest trades ended at the stop
(-1.40, -1.35).

Candles and readings share ONE clock. Hour bars start at T0, the entry minute
is the entry bar's open, and the book is read there.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents import auto_trader as at

T0 = 1791504000           # Oct 09, 2026 00:00 UTC
H = 3600
KEY = next(iter(at.STRATEGY_SPECS))
ROOT = Path(__file__).resolve().parents[1]


def frame(side=1):
    """Signal on bar 5 (close 100). The entry bar 6 OPENS 0.10 away from the
    recorded best price of 100.00 (100.10 for a long, 99.90 for a short).
    Bar 8 reaches a 1% target from 100.00 but not one from the open; bar 12
    then reaches the open's 1% stop but not the best price's."""
    n = 30
    o = [100.0] * n
    hi = [100.2] * n
    lo = [99.8] * n
    if side == 1:
        o[6], hi[8], lo[12] = 100.10, 101.05, 99.05
    else:
        o[6], lo[8], hi[12] = 99.90, 98.95, 100.95
    return pd.DataFrame({"Date": pd.to_datetime([T0 + H * k for k in range(n)], unit="s"),
                         "Open": o, "High": hi, "Low": lo, "Close": [100.0] * n,
                         "Volume": [1.0] * n})


def book(*readings):
    """Readings as (t, bid, ask, buy, sell), packed like cost_store's."""
    return {"t": np.asarray([r[0] for r in readings], dtype="int64"),
            "bid": np.asarray([r[1] for r in readings], dtype="float64"),
            "ask": np.asarray([r[2] for r in readings], dtype="float64"),
            "spread": np.asarray([(r[2] - r[1]) / ((r[2] + r[1]) / 2) for r in readings],
                                 dtype="float32"),
            "buy": np.asarray([r[3] for r in readings], dtype="float32"),
            "sell": np.asarray([r[4] for r in readings], dtype="float32"),
            "exhausted": np.zeros(len(readings), dtype="bool"),
            "source": np.ones(len(readings), dtype="int8")}


def run(side=1, **kw):
    dirs = [0] * 30
    dirs[5] = side
    return at.backtest_strategy(KEY, frame(side), 5.0, fee=0.00075, slippage=0.0003,
                                sizing="flat", dirs=dirs, tp=0.01, sl=0.01,
                                keep_log=True, **kw)


ENTRY = T0 + 6 * H


def test_a_long_buys_at_the_recorded_ask_and_reaches_its_target():
    r = run(book=book((ENTRY, 99.99, 100.00, 0.0001, 0.0001)))
    t = r["log"][0]
    assert t["entry"] == 100.00, t
    assert t["why"] == "TP" and t["TP px"] == 101.0, t


def test_a_short_sells_at_the_recorded_bid():
    r = run(side=-1, book=book((ENTRY, 100.00, 100.01, 0.0001, 0.0001)))
    t = r["log"][0]
    assert t["entry"] == 100.00, t
    assert t["why"] == "TP" and t["TP px"] == 99.0, t


def test_without_the_minutes_own_book_it_buys_at_the_open_as_before():
    """A reading from the minute BEFORE the close is inside the signal candle,
    and no book at all is the engine of before: the open, then the stop."""
    for b in (book((ENTRY - 60, 99.99, 100.00, 0.0001, 0.0001)), None):
        t = run(book=b)["log"][0]
        assert t["entry"] == 100.10 and t["why"] == "SL", t


def test_a_snapshot_hours_later_minute_does_not_price_the_entry():
    """An hour Gate kept only one snapshot of stamps it on every minute
    (book_history.book_age_s): at :15 that book is 15 minutes old."""
    snap = book((ENTRY, 99.99, 100.00, 0.0001, 0.0001))
    snap["source"] = np.asarray([2], dtype="int8")
    t = run(book=snap)["log"][0]
    assert t["entry"] == 100.00, "the hour's own first minute IS its snapshot"
    later = book((ENTRY + 900, 99.99, 100.00, 0.0001, 0.0001))
    later["source"] = np.asarray([2], dtype="int8")
    assert at.book_fill_price({"t": ENTRY + 900, "age_s": 0, "bid": 99.99, "ask": 100.0,
                               "source": 2}, 1) is None


def test_the_best_price_is_not_charged_again_and_the_exit_pays_its_side():
    """Practice: the fill at the ask holds the entry's half-spread, so no entry
    walk is charged; the exit pays the other side of its own minute's book.
    1% target, 0.075% fee each way, 0.02% to sell at the exit minute, $100."""
    r = run(book=book((ENTRY, 99.99, 100.00, 0.0009, 0.0001),
                      (T0 + 8 * H, 100.99, 101.00, 0.0001, 0.0002)))
    t = r["log"][0]
    assert t["cost in %"] == 0.0 and t["cost out %"] == pytest.approx(0.02, abs=1e-6), t
    assert t["pnl $"] == round((0.01 - 2 * 0.00075 - 0.0002) * 100, 2), t


def test_no_exit_reading_pays_what_practice_charges_the_exit():
    """With no reading at the exit minute, the exit pays the entry minute's
    other side, the `exit_slippage` practice carries from its entry. Never
    the entry's zero."""
    r = run(book=book((ENTRY, 99.99, 100.00, 0.0009, 0.0003)))
    t = r["log"][0]
    assert t["cost out %"] == pytest.approx(0.03, abs=1e-6), t
    assert t["pnl $"] == round((0.01 - 2 * 0.00075 - 0.0003) * 100, 2), t


def test_one_rule_for_the_price():
    """at.book_fill_price: the entry minute's own book gives the trade side's
    best price (ask to buy, bid to sell); anything else gives None, and the
    caller keeps the candle's open."""
    fresh = {"t": ENTRY, "age_s": 0, "bid": 99.99, "ask": 100.0, "source": 1}
    assert at.book_fill_price(fresh, 1) == 100.0
    assert at.book_fill_price(fresh, -1) == 99.99
    assert at.book_fill_price({**fresh, "age_s": 60}, 1) is None
    assert at.book_fill_price({**fresh, "ask": 0.0}, 1) is None
    assert at.book_fill_price(None, 1) is None


def test_the_fast_walk_takes_the_same_price():
    from tradingagents import fast_grid as fg
    df = frame()
    o, h, lo, c = (df[k].tolist() for k in ("Open", "High", "Low", "Close"))
    dirs = [0] * 30
    dirs[5] = 1
    plain = fg.walk([5], dirs, o, h, lo, c, tp=0.01, sl=0.01, liq=None)
    priced = fg.walk([5], dirs, o, h, lo, c, tp=0.01, sl=0.01, liq=None,
                     entry_px=lambda i, s: 100.0)
    assert plain[0][5] == fg.WHY_SL and priced[0][5] == fg.WHY_TP
    assert fg.walk([5], dirs, o, h, lo, c, tp=0.01, sl=0.01, liq=None,
                   entry_px=lambda i, s: None) == plain, "None keeps the open"


@pytest.fixture
def rs(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / ".github" / "scripts"))
    spec = importlib.util.spec_from_file_location("replay_shard_px",
                                                  ROOT / ".github/scripts/replay_shard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("replay_shard_px", None)


def test_the_replay_charges_like_the_engine(rs):
    """replay_shard.trade_fee is one SIDE (fg.trade_pnl charges it twice):
    fee + (entry walk + exit walk) / 2 before; with the entry priced at the
    best price only the exit half stays: fee + exit walk / 2."""
    cost = {"fee": 0.00075, "slip": 0.0003}
    b = book((ENTRY, 99.99, 100.00, 0.0009, 0.0001), (T0 + 8 * H, 100.99, 101.0, 0.0001, 0.0002))
    got = rs.trade_fee(b, cost, 1, ENTRY * 1000, (T0 + 8 * H) * 1000, {})
    assert got == pytest.approx(0.00075 + 0.0002 / 2)
    stale = book((ENTRY - 120, 99.99, 100.00, 0.0009, 0.0001), (T0 + 8 * H, 100.99, 101.0, 0.0001, 0.0002))
    got = rs.trade_fee(stale, cost, 1, ENTRY * 1000, (T0 + 8 * H) * 1000, {})
    assert got == pytest.approx(0.00075 + (0.0009 + 0.0002) / 2), "no fresh book: as before"


def test_the_replay_walk_is_priced_by_the_one_rule():
    src = " ".join((ROOT / ".github/scripts/replay_shard.py").read_text(encoding="utf-8").split())
    call = src[src.index("walked = fg.walk("):]
    call = call[:call.index(")", call.index("refuse=refuse")) + 1]
    assert "entry_px=" in call, call
    assert "at.book_fill_price(" in src
