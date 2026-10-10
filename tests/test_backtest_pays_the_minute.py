"""The backtest pays the order book of each trade's own minute, and refuses
what the runner would refuse (phase 4, spec D11, Oct 10, 2026).

`backtest_strategy(book=...)` takes Gate's recorded readings (book_history):
at an entry it reads the book at the entry bar's open, asks the runner's own
`cost_verdict`, and either refuses (counted in `gate_blocked`) or enters,
paying that minute's fill on its side; the exit pays the exit minute's fill.
A minute with no reading pays the flat cost of before and is counted in
`cost_unmeasured`. With `book=None` nothing changes, byte for byte.
"""
import numpy as np
import pandas as pd
import pytest

from tradingagents import auto_trader as at

T0 = 1791504000           # Oct 09, 2026 00:00 UTC
H = 3600


def frame():
    n = 30
    o = [100.0] * n
    hi = [100.2] * n
    lo = [99.8] * n
    hi[8] = 101.5          # the long's 1% target is touched in bar 8
    return pd.DataFrame({"Date": pd.to_datetime([T0 + H * k for k in range(n)], unit="s"),
                         "Open": o, "High": hi, "Low": lo, "Close": o,
                         "Volume": [1.0] * n})


DIRS = [0] * 30
DIRS[5] = 1                # signal on bar 5 -> entry at bar 6's open
KEY = next(iter(at.STRATEGY_SPECS))


def run(**kw):
    return at.backtest_strategy(KEY, frame(), 5.0, fee=0.00075, slippage=0.0003,
                                sizing="flat", dirs=list(DIRS), tp=0.01, sl=0.01,
                                keep_log=True, **kw)


def book(entries):
    """Packed readings: [(t, spread, buy, sell, exhausted)]."""
    t = np.asarray([e[0] for e in entries], dtype="int64")
    return {"t": t, "bid": np.full(len(t), 99.99), "ask": np.full(len(t), 100.01),
            "spread": np.asarray([e[1] for e in entries], dtype="float32"),
            "buy": np.asarray([e[2] for e in entries], dtype="float32"),
            "sell": np.asarray([e[3] for e in entries], dtype="float32"),
            "exhausted": np.asarray([e[4] for e in entries], dtype="bool"),
            "source": np.ones(len(t), dtype="int8")}


def test_no_book_is_the_engine_of_before():
    a, b = run(), run(book=None)
    assert a["profit"] == b["profit"] and a["trades"] == b["trades"] == 1
    assert "gate_blocked" not in a, "an old caller's result keeps its shape"


def test_a_cheap_minute_lets_the_trade_in_and_charges_its_own_fills():
    bk = book([(T0 + 6 * H, 0.0002, 0.0001, 0.0001, False),     # the entry minute
               (T0 + 8 * H, 0.0004, 0.0002, 0.0005, False)])    # the exit bar
    r = run(book=bk)
    assert r["trades"] == 1 and r["gate_blocked"] == 0 and r["cost_unmeasured"] == 0
    # +1% move, minus two fees, the entry's buy fill and the exit's SELL fill
    want = (0.01 - 2 * 0.00075 - 0.0001 - 0.0005) * 5.0 * at.LEVERAGE
    assert r["profit"] == pytest.approx(want, abs=0.01)
    assert r["log"][0]["cost in %"] == pytest.approx(0.01, abs=1e-6)
    assert r["log"][0]["cost out %"] == pytest.approx(0.05, abs=1e-6)


def test_a_minute_the_runner_would_refuse_is_refused_and_counted():
    # 0.8% to get in against a 1% target: the round trip is over half of it
    bk = book([(T0 + 6 * H, 0.016, 0.008, 0.008, False)])
    r = run(book=bk)
    assert r["trades"] == 0 and r["gate_blocked"] == 1
    assert r["profit"] == 0


def test_a_stop_inside_the_gap_is_refused_like_the_runner_refuses_it():
    bk = book([(T0 + 6 * H, 0.011, 0.0001, 0.0001, False)])     # gap 1.1% > SL 1%
    assert run(book=bk)["gate_blocked"] == 1


def test_a_minute_with_no_reading_pays_the_flat_cost_and_is_counted():
    bk = book([(T0, 0.0002, 0.0001, 0.0001, False)])             # hours too old
    r = run(book=bk)
    assert r["trades"] == 1 and r["cost_unmeasured"] == 1
    assert r["profit"] == pytest.approx(run()["profit"], abs=0.01), \
        "unmeasured means the flat cost of before, never free"


def test_a_coin_with_no_readings_at_all_counts_every_trade_unmeasured():
    r = run(book=book([]))
    assert r["trades"] == 1 and r["cost_unmeasured"] == 1 and r["gate_blocked"] == 0


def test_a_minute_with_no_reading_still_refuses_what_needs_no_book():
    """Final review, Oct 10, 2026 (RCA-2026-10-10-H): with no reading the
    whole check was skipped, so a stop past 80% of liquidation, or funding
    that eats the target, traded — the runner refuses both whatever the book
    says. Reproduced: SL 4% against liquidation at 4.5% -> blocked with a
    reading, +$4.79 without one. The book-free checks run on the coin's flat
    cost; only the checks that need the book (the gap, an exhausted book)
    wait for a reading."""
    r = at.backtest_strategy(KEY, frame(), 5.0, fee=0.00075, slippage=0.0003,
                             sizing="flat", dirs=list(DIRS), tp=0.05, sl=0.04,
                             liq_move_pct=4.5, book=book([]))
    assert r["trades"] == 0 and r["gate_blocked"] == 1 and r["cost_unmeasured"] == 0
    v = at.minute_verdict(None, side=1, tp=0.005, sl=0.004, fee=0.00075,
                          hold_s=3 * 3600, liq=None, fund_day=0.003, flat_slip=0.0003)
    assert v["verdict"] == "block" and v["funding_eats"]
    ok = at.minute_verdict(None, side=1, tp=0.01, sl=0.01, fee=0.00075,
                           hold_s=3 * 3600, liq=0.045, fund_day=0.0, flat_slip=0.0003)
    assert ok["verdict"] != "block" and ok["slippage"] == pytest.approx(0.0003)
