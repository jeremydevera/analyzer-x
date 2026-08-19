"""Backtesting at leverage other than 20x — and modelling liquidation.

Raising leverage in a backtest that does NOT model liquidation just multiplies
every result, which makes 100x look like five times the profit of 20x with
five times the loss. That is fiction. Past a certain leverage the venue closes
the position before the stop can fire, and the trade loses the WHOLE margin
rather than the stop's slice. These tests pin that boundary, because the
number it protects is the operator's account.
"""
import pandas as pd
import pytest

import tradingagents.auto_trader as at


def _bars(moves, start=100.0):
    """One bar per move. Each bar's range reaches exactly `move` from open."""
    rows, px = [], start
    for i, m in enumerate(moves):
        hi = px * (1 + max(m, 0)) if m >= 0 else px
        lo = px * (1 + m) if m < 0 else px
        rows.append({"Date": pd.Timestamp("2026-01-01") + pd.Timedelta(hours=4 * i),
                     "Open": px, "High": max(px, hi), "Low": min(px, lo),
                     "Close": px})
    return pd.DataFrame(rows)


KEY = "trend50_4h"


def test_leverage_defaults_to_the_live_constant():
    df = _bars([0.0] * 300)
    a = at.backtest_strategy(KEY, df, 5.0)
    b = at.backtest_strategy(KEY, df, 5.0, leverage=at.LEVERAGE)
    assert a["profit"] == pytest.approx(b["profit"])
    assert a["trades"] == b["trades"]


def test_the_log_reports_the_leverage_actually_used():
    df = _bars([0.01, -0.01] * 150)
    r = at.backtest_strategy(KEY, df, 5.0, leverage=50)
    if r["log"]:
        assert r["log"][0]["leverage"] == "50x"
        assert r["log"][0]["notional $"] == pytest.approx(
            r["log"][0]["margin $"] * 50)


def test_liquidation_caps_the_loss_at_the_whole_margin():
    """A liquidated trade cannot lose more than the margin staked. Without
    this the engine reports a 2% move at 100x as -200% of margin."""
    r = at.backtest_strategy(KEY, _bars([0.005, -0.05] * 120), 5.0,
                             leverage=100, sl=0.30, tp=0.30,
                             liq_move_pct=0.5)
    for t in r["log"]:
        assert t["pnl $"] >= -t["margin $"] - 1e-6, t


def test_a_liquidation_is_never_recorded_as_a_win():
    r = at.backtest_strategy(KEY, _bars([0.005, -0.05] * 120), 5.0,
                             leverage=100, sl=0.30, tp=0.30,
                             liq_move_pct=0.5)
    for t in r["log"]:
        if t["why"] == "LIQ":
            assert t["WIN/LOSE"] == "LOSE"
            assert t["pnl $"] < 0


def test_liquidation_fires_before_a_stop_that_sits_beyond_it():
    """The whole point: at 100x on this contract the stop is unreachable."""
    df = _bars([0.005, -0.03] * 120)
    # stop at 1.5%, liquidation at 0.5% — liquidation must win
    r = at.backtest_strategy(KEY, df, 5.0, leverage=100, sl=0.015, tp=0.045,
                             liq_move_pct=0.5)
    whys = {t["why"] for t in r["log"]}
    assert "LIQ" in whys, whys
    assert "SL" not in whys, "a stop beyond the liquidation price cannot fire"


def test_no_liquidation_when_the_stop_is_nearer():
    """At 20x the 4.5% liquidation is far beyond the 1.5% stop, so the stop
    always wins and behaviour is unchanged."""
    df = _bars([0.005, -0.03] * 120)
    r = at.backtest_strategy(KEY, df, 5.0, leverage=20, sl=0.015, tp=0.045,
                             liq_move_pct=4.5)
    assert "LIQ" not in {t["why"] for t in r["log"]}


def test_omitting_liq_move_pct_disables_liquidation():
    """Callers that do not supply the venue's real figure must not get a
    guessed one — better no model than an invented boundary."""
    df = _bars([0.005, -0.09] * 120)
    r = at.backtest_strategy(KEY, df, 5.0, leverage=100, sl=0.015, tp=0.045)
    assert "LIQ" not in {t["why"] for t in r["log"]}


def test_profit_scales_with_leverage_when_nothing_liquidates():
    df = _bars([0.01, -0.005] * 150)
    lo = at.backtest_strategy(KEY, df, 5.0, leverage=10, sl=0.30, tp=0.005)
    hi = at.backtest_strategy(KEY, df, 5.0, leverage=20, sl=0.30, tp=0.005)
    if lo["trades"] and lo["profit"]:
        assert hi["profit"] == pytest.approx(lo["profit"] * 2, rel=1e-6)
