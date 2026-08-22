"""Tests for the bracket backtester — exit precedence, fees, drawdown, sweeps."""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from tradingagents import futures_backtest as bt

pytestmark = pytest.mark.unit


def frame(rows):
    """rows = [(open, high, low, close), ...] on a 5-minute clock."""
    t0 = datetime(2026, 1, 1)
    return pd.DataFrame({
        "Date": [t0 + timedelta(minutes=5 * i) for i in range(len(rows))],
        "Open": [r[0] for r in rows], "High": [r[1] for r in rows],
        "Low": [r[2] for r in rows], "Close": [r[3] for r in rows],
    })


def test_take_profit_fills_at_the_target_not_the_high():
    # entry at bar1 open = 100; bar2 spikes to 110 but the target is +2%
    df = frame([(100, 100, 100, 100), (100, 101, 100, 100), (100, 110, 100, 109)])
    r = bt.run(df, take_profit_pct=2, stop_loss_pct=10, margin=100, leverage=1,
               fee_per_side=0)
    assert r.trades[0].reason == "take-profit"
    assert r.trades[0].exit_px == pytest.approx(102.0)
    assert r.trades[0].net_return == pytest.approx(0.02)


def test_stop_wins_when_one_bar_touches_both():
    """Pessimistic tie-break: a bar spanning both levels books the loss."""
    df = frame([(100, 100, 100, 100), (100, 100, 100, 100),
                (100, 130, 80, 100)])
    r = bt.run(df, take_profit_pct=2, stop_loss_pct=10, margin=100, leverage=1,
               fee_per_side=0)
    assert r.trades[0].reason == "stop-loss"
    assert r.trades[0].exit_px == pytest.approx(90.0)


def test_fees_are_charged_on_both_sides():
    df = frame([(100, 100, 100, 100), (100, 100, 100, 100), (100, 103, 100, 102)])
    r = bt.run(df, take_profit_pct=2, stop_loss_pct=10, margin=100, leverage=1,
               fee_per_side=0.001)
    # +2% gross, minus 0.1% twice
    assert r.trades[0].net_return == pytest.approx(0.02 - 0.002)


def test_leverage_scales_pnl_but_not_return_fraction():
    df = frame([(100, 100, 100, 100), (100, 100, 100, 100), (100, 103, 100, 102)])
    a = bt.run(df, take_profit_pct=2, stop_loss_pct=10, margin=100, leverage=1,
               fee_per_side=0)
    b = bt.run(df, take_profit_pct=2, stop_loss_pct=10, margin=100, leverage=3,
               fee_per_side=0)
    assert b.pnl == pytest.approx(a.pnl * 3)
    assert b.trades[0].net_return == pytest.approx(a.trades[0].net_return)


def test_positions_do_not_overlap():
    rows = [(100, 100, 100, 100)]
    for _ in range(6):                     # repeated +2% pops
        rows.append((100, 103, 100, 102))
    r = bt.run(frame(rows), take_profit_pct=2, stop_loss_pct=10, margin=100,
               leverage=1, fee_per_side=0)
    for a, b in zip(r.trades, r.trades[1:], strict=False):
        assert b.entry_at > a.exit_at, "a new entry must follow the prior exit"


def test_open_position_at_the_end_is_reported():
    df = frame([(100, 100, 100, 100)] * 6)          # never hits either barrier
    r = bt.run(df, take_profit_pct=5, stop_loss_pct=5, margin=100, leverage=1,
               fee_per_side=0)
    assert r.n_open == 1 and r.trades[-1].reason == "open at end"


def test_drawdown_is_mark_to_market_not_realised_only():
    """A dip that recovers before the stop must still show in the drawdown."""
    df = frame([(100, 100, 100, 100), (100, 100, 100, 100),
                (100, 100, 95, 100),                 # -5% unrealised
                (100, 103, 100, 102)])               # then take-profit
    r = bt.run(df, take_profit_pct=2, stop_loss_pct=10, margin=100, leverage=1,
               fee_per_side=0)
    assert r.trades[0].reason == "take-profit"
    assert r.max_drawdown < 0, "the -5% dip must be recorded"
    assert r.worst_equity < r.margin


def test_liquidation_flag_trips_when_equity_hits_zero():
    # 10x leverage and a 12% dip wipes the margin before any stop at 20%
    df = frame([(100, 100, 100, 100), (100, 100, 100, 100),
                (100, 100, 88, 90)])
    r = bt.run(df, take_profit_pct=50, stop_loss_pct=20, margin=100,
               leverage=10, fee_per_side=0)
    assert r.liquidated is True and r.worst_equity <= 0


def test_buy_hold_benchmark_uses_the_same_notional():
    df = frame([(100, 100, 100, 100), (100, 100, 100, 100),
                (100, 121, 100, 120)])
    r = bt.run(df, take_profit_pct=2, stop_loss_pct=10, margin=100, leverage=2,
               fee_per_side=0)
    # buy&hold: enter bar1 open 100, exit last close 120 = +20% on 2x notional
    assert r.buy_hold_pnl == pytest.approx(0.20 * 200)
    assert r.beats_buy_hold is False, "a +2% target cannot beat a +20% hold"


def test_max_hold_forces_a_time_exit():
    df = frame([(100, 100, 100, 100)] * 10)
    r = bt.run(df, take_profit_pct=50, stop_loss_pct=50, margin=100,
               leverage=1, fee_per_side=0, max_hold_bars=2)
    assert len(r.trades) > 1, "a time exit must free the engine to re-enter"


def test_rejects_bad_parameters():
    df = frame([(100, 100, 100, 100)] * 5)
    with pytest.raises(ValueError):
        bt.run(df, take_profit_pct=0, stop_loss_pct=10)
    with pytest.raises(ValueError):
        bt.run(df.head(2), take_profit_pct=2, stop_loss_pct=10)


def test_equity_curve_tracks_cumulative_pnl():
    rows = [(100, 100, 100, 100)] + [(100, 103, 100, 102)] * 3
    r = bt.run(frame(rows), take_profit_pct=2, stop_loss_pct=10, margin=100,
               leverage=1, fee_per_side=0)
    assert len(r.equity_curve) == len(r.trades)
    assert r.equity_curve[-1][1] == pytest.approx(r.margin + r.pnl)


def test_sweep_orders_by_pnl_and_flags_the_benchmark():
    rows = [(100, 100, 100, 100)] + [(100, 103, 99, 102)] * 8
    s = bt.sweep(frame(rows), [1, 2, 3], [5, 10], margin=100, leverage=1)
    assert len(s) == 6
    assert s == sorted(s, key=lambda d: -d["pnl"])
    assert all("beats_buy_hold" in d for d in s)


# ============ liquidation must end the simulation ===========================
# Reported by the operator after setting 200x: a single stop-loss showed -$200.80
# against a $10 margin — 20x the whole account — and the run then booked twelve
# more trades on money that no longer existed, finishing +$239.30 when the truth
# was -$10 on day one.
def _falling(n=60, start=100.0, step=-1.0):
    import pandas as pd
    rows = []
    for i in range(n):
        px = start + step * i
        rows.append({"Date": datetime(2026, 1, 1) + timedelta(hours=4 * i),
                     "Open": px, "High": px + 0.1, "Low": px - 0.1, "Close": px})
    return pd.DataFrame(rows)


def test_a_loss_can_never_exceed_the_margin():
    """Isolated margin caps the loss at what you posted. Anything larger is a
    number the exchange could not produce."""
    for lev in (1, 3, 20, 50, 200):
        r = bt.run(_falling(), take_profit_pct=2.0, stop_loss_pct=10.0,
                    margin=10.0, leverage=lev)
        assert r.pnl >= -10.0 - 1e-9, f"{lev}x lost more than the margin: {r.pnl}"


def test_liquidation_stops_the_run():
    r = bt.run(_falling(), take_profit_pct=2.0, stop_loss_pct=10.0,
                margin=10.0, leverage=200)
    assert r.liquidated is True
    assert len(r.trades) == 1, "there is no money left for a second trade"
    assert r.trades[0].reason == "liquidated"
    assert r.pnl == pytest.approx(-10.0)
    assert r.worst_equity == 0.0, "the account ends at zero, not negative"


def test_the_liquidation_price_is_where_equity_hit_zero():
    """Not the bar's low: the venue closes you at the point the margin is gone."""
    r = bt.run(_falling(), take_profit_pct=2.0, stop_loss_pct=50.0,
                margin=10.0, leverage=10)
    t = r.trades[0]
    assert t.reason == "liquidated"
    # 10x: equity is gone after roughly a 10% adverse move
    assert t.exit_px == pytest.approx(t.entry_px * 0.9, rel=1e-6)


def test_low_leverage_is_untouched_by_the_rule():
    """The stop must still be what ends a trade when the margin can absorb it.

    A shallow fall: the earlier version of this test used a 59% decline, where a
    3x account genuinely IS liquidated by repeated stops — the rule was right and
    the test's premise was wrong.
    """
    r = bt.run(_falling(30, step=-0.4), take_profit_pct=2.0, stop_loss_pct=10.0,
               margin=10.0, leverage=3)
    assert r.liquidated is False
    assert r.trades[0].reason == "stop-loss"
    assert r.pnl > -10.0


def test_the_exposure_engine_also_stops_at_zero():
    candles = _falling(80)
    positions = [1.0] * len(candles)
    r = bt.run_positions(candles, positions, margin=10.0, leverage=200)
    assert r.liquidated is True
    assert r.pnl == pytest.approx(-10.0)
    assert r.worst_equity == 0.0


def test_liquidated_is_a_fact_not_an_inference():
    """It used to be derived from worst_equity, so a run could report liquidated
    while still handing back profits earned afterwards."""
    r = bt.run(_falling(), take_profit_pct=2.0, stop_loss_pct=10.0,
                margin=10.0, leverage=200)
    assert r.liquidated and r.pnl == pytest.approx(-10.0)
    r2 = bt.run(_falling(), take_profit_pct=2.0, stop_loss_pct=10.0,
                 margin=10_000.0, leverage=1)
    assert r2.liquidated is False


def test_the_benchmark_can_be_liquidated_too():
    """Buy and hold at 200x is a real leveraged long facing the same path. It was
    reported as the raw price change times notional: +$228.92 against a $10
    margin, a number no account could hold."""
    candles = _falling(60)
    r = bt.run(candles, take_profit_pct=2.0, stop_loss_pct=10.0,
               margin=10.0, leverage=200)
    assert r.buy_hold_pnl == pytest.approx(-10.0), \
        "a 200x long cannot lose more, nor survive, this path"
    # unlevered, the same fall is survivable and the benchmark is a real number
    r2 = bt.run(candles, take_profit_pct=2.0, stop_loss_pct=10.0,
                margin=10_000.0, leverage=1)
    assert r2.buy_hold_pnl < 0 and r2.buy_hold_pnl > -10_000.0


def test_a_rising_path_leaves_the_benchmark_alone():
    import pandas as pd
    rows = [{"Date": datetime(2026, 1, 1) + timedelta(hours=4 * i),
             "Open": 100 + i * 0.5, "High": 100 + i * 0.5 + 0.2,
             "Low": 100 + i * 0.5 - 0.05, "Close": 100 + i * 0.5}
            for i in range(60)]
    r = bt.run(pd.DataFrame(rows), take_profit_pct=2.0, stop_loss_pct=10.0,
               margin=100.0, leverage=3)
    assert r.buy_hold_pnl > 0, "a 3x long through a steady rise is not liquidated"


# ============ the backtest must simulate THIS bot ===========================
# The operator asked whether the backtest reflects the settings panel. It did not:
# it used margin x leverage with no cap and no breakers, so at $10 margin, 200x and
# a $400 cap it traded $2,000 — five times the bot's size — and kept going through
# conditions that stop the real runner.
def test_the_notional_cap_is_applied():
    c = _falling(40, step=0.2)
    r = bt.run(c, take_profit_pct=2.0, stop_loss_pct=10.0,
               margin=10.0, leverage=200, max_notional=400.0)
    assert r.notional == 400.0, "the bot sizes with min(margin*lev, cap)"
    uncapped = bt.run(c, take_profit_pct=2.0, stop_loss_pct=10.0,
                      margin=10.0, leverage=200)
    assert uncapped.notional == 2000.0


def test_the_loss_limit_stops_the_run():
    r = bt.run(_falling(200, step=-0.3), take_profit_pct=2.0, stop_loss_pct=5.0,
               margin=1000.0, leverage=1, max_losses=2)
    assert sum(1 for t in r.trades if t.pnl < 0) == 2
    assert "loss limit" in r.halted_reason


def test_zero_disables_each_breaker():
    c = _falling(200, step=-0.3)
    a = bt.run(c, take_profit_pct=2.0, stop_loss_pct=5.0, margin=1000.0,
               leverage=1, max_losses=0, daily_loss_limit=0.0, min_equity=0.0)
    assert a.halted_reason == ""
    assert len([t for t in a.trades if t.pnl < 0]) > 2


def test_the_equity_floor_measures_the_wallet_not_the_margin():
    """This fired instantly on a $10-margin run against a $20 floor even with
    $163 in the wallet — it was comparing the wrong quantity."""
    c = _falling(60, step=0.2)
    r = bt.run(c, take_profit_pct=2.0, stop_loss_pct=10.0, margin=10.0,
               leverage=3, min_equity=20.0, starting_equity=163.0)
    assert r.halted_reason == "", "a $163 wallet is far above a $20 floor"
    assert len(r.trades) > 0
    # and it does fire when the wallet really is below the floor
    r2 = bt.run(c, take_profit_pct=2.0, stop_loss_pct=10.0, margin=10.0,
                leverage=3, min_equity=20.0, starting_equity=15.0)
    assert "below floor" in r2.halted_reason and len(r2.trades) == 0


def test_no_wallet_figure_means_the_floor_is_skipped_not_guessed():
    c = _falling(60, step=0.2)
    r = bt.run(c, take_profit_pct=2.0, stop_loss_pct=10.0, margin=10.0,
               leverage=3, min_equity=1_000_000.0)
    assert r.halted_reason == "" and len(r.trades) > 0


def test_the_exposure_engine_honours_the_same_breakers():
    """The compare table ranked bracket strategies that stopped on the operator's
    limits against exposure strategies that ignored them — one league table, two
    sets of rules."""
    # numbers chosen so the floor genuinely trips: a 40% fall on $100 notional
    # costs $40, taking a $60 wallet below a $50 floor.
    c = _falling(80, step=-0.5)
    a = bt.run_positions(c, [1.0] * len(c), margin=100.0, leverage=1,
                         min_equity=50.0, starting_equity=60.0)
    assert "below floor" in a.halted_reason
    b_ = bt.run_positions(c, [1.0] * len(c), margin=100.0, leverage=1)
    assert b_.halted_reason == "", "no limits given means no early stop"


def test_the_daily_limit_stands_the_exposure_engine_down():
    c = _falling(200, step=-0.2)
    with_limit = bt.run_positions(c, [1.0] * len(c), margin=1000.0, leverage=1,
                                  daily_loss_limit=1.0)
    without = bt.run_positions(c, [1.0] * len(c), margin=1000.0, leverage=1)
    assert with_limit.pnl > without.pnl, \
        "standing down after the daily loss must lose less than holding through it"
