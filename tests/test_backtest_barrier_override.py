"""Backtesting a strategy at barriers OTHER than its live ones.

The TP/SL sweep needs to re-run one strategy at many barrier pairs. The old
way to do that was to assign into ``STRATEGY_SPECS`` before each run — but the
webapp reads that same dict to render each row's SL/TP, and the live runner
reads it to place brackets. A sweep that mutates it is editing the live
configuration to draw a table. These tests pin the override as a PARAMETER and
assert the global spec is untouched.
"""
import pandas as pd
import pytest

import tradingagents.auto_trader as at


def _bars(n=400, start=100.0, step=0.4):
    """A gently trending series with real intrabar range, so both barriers
    are reachable."""
    rows = []
    px = start
    for i in range(n):
        px += step if (i // 25) % 2 == 0 else -step
        rows.append({"Date": pd.Timestamp("2026-01-01") + pd.Timedelta(hours=4 * i),
                     "Open": px, "High": px * 1.02,
                     "Low": px * 0.98, "Close": px})
    return pd.DataFrame(rows)


KEY = "trend50_4h"


def test_override_changes_the_result():
    df = _bars()
    tight = at.backtest_strategy(KEY, df, 5.0, tp=0.01, sl=0.01)
    wide = at.backtest_strategy(KEY, df, 5.0, tp=0.08, sl=0.02)
    # different barriers cannot produce an identical trade list
    assert (tight["trades"], tight["profit"]) != (wide["trades"], wide["profit"])


def test_override_is_actually_used_not_ignored():
    """A 1% TP must be hit more often than an 8% TP on the same candles."""
    df = _bars()
    tight = at.backtest_strategy(KEY, df, 5.0, tp=0.01, sl=0.05)
    wide = at.backtest_strategy(KEY, df, 5.0, tp=0.08, sl=0.05)
    assert tight["wins"] >= wide["wins"]


def test_the_global_spec_is_never_mutated():
    """The webapp renders SL/TP from this dict and the runner places brackets
    from it. A sweep must not leave a strategy configured differently."""
    before = dict(at.STRATEGY_SPECS[KEY])
    at.backtest_strategy(_bars() is not None and KEY, _bars(), 5.0,
                         tp=0.123, sl=0.456)
    assert at.STRATEGY_SPECS[KEY] == before
    assert at.STRATEGY_SPECS[KEY]["tp"] == before["tp"]
    assert at.STRATEGY_SPECS[KEY]["sl"] == before["sl"]


def test_omitting_the_override_uses_the_live_spec():
    df = _bars()
    spec = at.STRATEGY_SPECS[KEY]
    a = at.backtest_strategy(KEY, df, 5.0)
    b = at.backtest_strategy(KEY, df, 5.0, tp=spec["tp"], sl=spec["sl"])
    assert a["trades"] == b["trades"]
    assert a["profit"] == pytest.approx(b["profit"])


def test_partial_override_keeps_the_other_barrier():
    df = _bars()
    spec = at.STRATEGY_SPECS[KEY]
    only_tp = at.backtest_strategy(KEY, df, 5.0, tp=0.09)
    both = at.backtest_strategy(KEY, df, 5.0, tp=0.09, sl=spec["sl"])
    assert only_tp["trades"] == both["trades"]
    assert only_tp["profit"] == pytest.approx(both["profit"])


def test_the_log_reports_the_overridden_barriers():
    """The trade log's TP/SL prices must describe the barriers actually used,
    or the table says one thing and the rows another."""
    df = _bars()
    r = at.backtest_strategy(KEY, df, 5.0, tp=0.10, sl=0.02)
    if not r["log"]:
        pytest.skip("no trades on this synthetic series")
    t = r["log"][0]
    entry, side = t["entry"], t["side"]
    want_tp = entry * (1 + 0.10) if side == "LONG" else entry * (1 - 0.10)
    want_sl = entry * (1 - 0.02) if side == "LONG" else entry * (1 + 0.02)
    assert t["TP px"] == pytest.approx(want_tp, rel=1e-6)
    assert t["SL px"] == pytest.approx(want_sl, rel=1e-6)
