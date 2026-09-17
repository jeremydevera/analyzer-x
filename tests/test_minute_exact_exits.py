"""An hour candle cannot say which of two prices it touched first.

#LG9NSU4B (XPIN 1h, TP 1% / SL 3%) stopped out in the practice account at
Sep 16, 2026 7:28am; the stored backtest said 7:00am, and a bar that held
both prices was booked as a loss by rule. With `fine=` the engine walks the
minutes inside the bar and books what happened first.

The clocks here are ONE timeline: the 1m bars sit inside the hour bars they
belong to. A fixture with two clocks is how RCA-2026-09-12-A hid.
"""
import numpy as np
import pandas as pd
import pytest

from tradingagents import auto_trader as at

KEY = "t_fine_1h"
H0 = 1_789_516_800_000            # Sep 16, 2026 00:00 UTC, on the hour


def _hours(closes, highs, lows, opens=None):
    n = len(closes)
    opens = opens or [closes[i - 1] if i else closes[0] for i in range(n)]
    return pd.DataFrame({
        "Date": pd.to_datetime([H0 + i * 3_600_000 for i in range(n)], unit="ms"),
        "Open": opens, "High": highs, "Low": lows, "Close": closes,
        "Volume": [1000.0] * n})


def _minutes(hour_idx, path):
    """`path` is 60 (high, low) pairs for the minutes of hour `hour_idx`."""
    t = np.array([H0 + hour_idx * 3_600_000 + k * 60_000 for k in range(60)], dtype="int64")
    h = np.array([p[0] for p in path], dtype="float64")
    l = np.array([p[1] for p in path], dtype="float64")
    return t, h, l


def _flat_minutes(hour_idx, px):
    return _minutes(hour_idx, [(px, px)] * 60)


def _fine(*parts):
    t = np.concatenate([p[0] for p in parts])
    h = np.concatenate([p[1] for p in parts])
    l = np.concatenate([p[2] for p in parts])
    o = np.argsort(t, kind="stable")
    return t[o], h[o], l[o]


@pytest.fixture(autouse=True)
def _spec():
    at.STRATEGY_SPECS[KEY] = {"interval": "Min60", "bar_seconds": 3600,
                              "tp": .01, "sl": .03, "threshold": .003}
    yield
    at.STRATEGY_SPECS.pop(KEY, None)


# signal on bar 0, entry at bar 1's open (100.0), TP 101.0, SL 97.0.
# Bar 1 touches BOTH: high 101.5, low 96.5.
BOTH = _hours(closes=[100.0, 100.0, 100.0], highs=[100.2, 101.5, 100.2],
              lows=[99.8, 96.5, 99.8], opens=[100.0, 100.0, 100.0])
DIRS = [1, 0, 0]


def _run(df, dirs, **kw):
    return at.backtest_strategy(KEY, df, 5.0, dirs=dirs, sizing="flat",
                                keep_log=True, **kw)


def test_without_fine_the_result_is_todays_result_plus_a_zero():
    a = _run(BOTH, DIRS)
    assert a["unclear"] == 0
    assert a["trades"] == 1 and a["losses"] == 1, \
        "one bar holding both prices is a LOSS by rule"
    assert a["log"][0]["why"] == "SL" and a["log"][0]["exit_minute_ms"] is None


def test_minute_order_decides_when_the_minutes_are_known():
    # minutes 0-9 rise to 101.5 (TP touched first), minutes 10-59 crash to 96.5
    path = [(101.5 if k < 10 else 100.0, 100.0 if k < 10 else 96.5) for k in range(60)]
    fine = _fine(_flat_minutes(0, 100.0), _minutes(1, path), _flat_minutes(2, 100.0))
    a = _run(BOTH, DIRS, fine=fine)
    assert a["wins"] == 1 and a["log"][0]["why"] == "TP", "TP came first, so it is a WIN"
    assert a["unclear"] == 0
    assert a["log"][0]["exit_minute_ms"] == H0 + 3_600_000


def test_the_stop_first_is_still_a_stop():
    path = [(100.0 if k < 10 else 101.5, 96.5 if k < 10 else 100.0) for k in range(60)]
    fine = _fine(_flat_minutes(0, 100.0), _minutes(1, path), _flat_minutes(2, 100.0))
    a = _run(BOTH, DIRS, fine=fine)
    assert a["losses"] == 1 and a["log"][0]["why"] == "SL"


def test_both_in_the_same_minute_books_the_loss_and_is_counted_unclear():
    path = [(100.0, 100.0)] * 27 + [(101.5, 96.5)] + [(100.0, 100.0)] * 32
    fine = _fine(_flat_minutes(0, 100.0), _minutes(1, path), _flat_minutes(2, 100.0))
    a = _run(BOTH, DIRS, fine=fine)
    assert a["log"][0]["why"] == "SL" and a["unclear"] == 1
    assert a["state"]["unclear"] == 1, "the count must survive a resume"


def test_the_exit_time_is_the_minute_not_the_hour():
    from tradingagents.positions_view import fmt_when

    path = [(100.0, 100.0)] * 28 + [(100.0, 96.5)] + [(100.0, 100.0)] * 31   # SL at minute 28
    fine = _fine(_flat_minutes(0, 100.0), _minutes(1, path), _flat_minutes(2, 100.0))
    a = _run(BOTH, DIRS, fine=fine)
    m = H0 + 3_600_000 + 28 * 60_000
    assert a["log"][0]["exit_minute_ms"] == m
    assert a["log"][0]["exit time"] == fmt_when(m / 1000), "printed through the ONE formatter"


def test_an_hour_with_no_minutes_falls_back_to_the_bar_rule():
    """The 1m store may be younger than the hour store. A bar with no minutes
    under it is settled the old way — never skipped, never guessed finer."""
    fine = _fine(_flat_minutes(0, 100.0))          # nothing for bar 1
    a = _run(BOTH, DIRS, fine=fine)
    assert a["log"][0]["why"] == "SL" and a["unclear"] == 0
    assert a["log"][0]["exit_minute_ms"] is None


def test_the_minutes_disagreeing_with_their_own_bar_fall_back_too():
    """Bar 1's high/low say both prices were touched; its minutes touch
    neither. A rebuilt bar and its minutes cannot disagree, so this is a
    corrupt input — settle by the bar rule rather than pretend nothing hit."""
    fine = _fine(_flat_minutes(0, 100.0), _flat_minutes(1, 100.0), _flat_minutes(2, 100.0))
    a = _run(BOTH, DIRS, fine=fine)
    assert a["log"][0]["why"] == "SL" and a["log"][0]["exit_minute_ms"] is None


def test_funding_is_charged_to_the_minute_the_trade_actually_closed():
    """The hour rule stamps an exit at its bar's OPEN, so a settlement at :30
    inside the exit hour is never charged — even when the stop fired at :45
    and the position was open at :30. The minute rule charges it. (The first
    draft of this test assumed the hour rule OVER-charged; it under-charges.
    Read the emitter: `_b = bisect_right(_f_ms, _bar_ms[j])`.)"""
    path = [(100.0, 100.0)] * 45 + [(100.0, 96.5)] + [(100.0, 100.0)] * 14   # SL at :45
    fine = _fine(_flat_minutes(0, 100.0), _minutes(1, path), _flat_minutes(2, 100.0))
    settle = H0 + 3_600_000 + 30 * 60_000                      # 01:30, before the :45 stop
    funding = [{"settle_ms": settle, "rate": 0.01}]           # longs pay 1% — huge, on purpose
    with_min = _run(BOTH, DIRS, fine=fine, funding=funding)
    by_bar = _run(BOTH, DIRS, funding=funding)
    assert with_min["funding_total"] < 0.0, "open at :30, closed at :45 — the settlement was paid"
    assert by_bar["funding_total"] == 0.0, "the hour rule misses it — the inaccuracy v2 removes"
    # and a stop at :28 does NOT pay the :30 settlement
    early = [(100.0, 100.0)] * 28 + [(100.0, 96.5)] + [(100.0, 100.0)] * 31
    fine2 = _fine(_flat_minutes(0, 100.0), _minutes(1, early), _flat_minutes(2, 100.0))
    assert _run(BOTH, DIRS, fine=fine2, funding=funding)["funding_total"] == 0.0


def test_fine_never_changes_a_bar_that_touched_one_price_only():
    """Parity on the common case: 200 random hours, every exit bar touching at
    most one barrier — with and without minutes the answers are identical to
    the cent, because the minutes can only re-order what one bar held."""
    import random

    rng = random.Random(3)
    n = 200
    closes, highs, lows = [], [], []
    px = 100.0
    for _ in range(n):
        px *= 1 + rng.gauss(0, 0.004)
        closes.append(px)
        highs.append(px * 1.002)
        lows.append(px * 0.998)
    df = _hours(closes, highs, lows)
    dirs = [rng.choice([1, -1, 0, 0, 0]) for _ in range(n)]
    parts = [_minutes(i, [(highs[i], lows[i])] * 60) for i in range(n)]
    fine = _fine(*parts)
    a = _run(df, dirs, tp=.05, sl=.05)
    b = _run(df, dirs, tp=.05, sl=.05, fine=fine)
    for k in ("trades", "wins", "profit", "worst_trade", "max_dd", "monthly"):
        assert a[k] == b[k], k


def test_slices_with_fine_is_refused_not_half_done():
    with pytest.raises(ValueError, match="slices with fine"):
        _run(BOTH, DIRS, fine=_fine(_flat_minutes(0, 100.0)),
             slices=[(1.0, .01, .03)])
