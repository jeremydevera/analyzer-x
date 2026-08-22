"""Tests for the six-strategy registry and its comparison table."""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from tradingagents import strategies as sg

pytestmark = pytest.mark.unit


def frame(closes, start_hour=0):
    t0 = datetime(2026, 1, 1, start_hour)
    return pd.DataFrame({
        "Date": [t0 + timedelta(minutes=5 * i) for i in range(len(closes))],
        "Open": closes, "High": [c * 1.001 for c in closes],
        "Low": [c * 0.999 for c in closes], "Close": closes,
    })


def test_registry_has_exactly_seven_long_only_strategies():
    assert len(sg.REGISTRY) == 7
    assert set(sg.ORDER) == set(sg.REGISTRY)
    for s in sg.REGISTRY.values():
        assert s.kind in ("bracket", "position")
        assert s.summary and s.rationale and s.risk, f"{s.key} lacks documentation"


def test_buy_hold_is_always_fully_invested():
    p = sg.positions_for("buy_hold", frame([100] * 20), {})
    assert set(p) == {1.0}


def test_trend_filter_is_flat_below_the_average():
    rising = [100 + i for i in range(30)]
    falling = [130 - i for i in range(30)]
    p_up = sg.positions_for("trend_filter", frame(rising), {"ma_bars": 10})
    p_dn = sg.positions_for("trend_filter", frame(falling), {"ma_bars": 10})
    assert p_up[-1] == 1.0, "above its average -> long"
    assert p_dn[-1] == 0.0, "below its average -> flat"
    assert p_up[0] == 0.0, "no exposure before the average exists"


def test_trend50_is_trend_filter_with_a_50_bar_default():
    rising = [100 + i for i in range(80)]
    falling = [200 - i for i in range(80)]
    p_up = sg.positions_for("trend50", frame(rising), sg.REGISTRY["trend50"].params)
    p_dn = sg.positions_for("trend50", frame(falling), sg.REGISTRY["trend50"].params)
    assert sg.REGISTRY["trend50"].params["ma_bars"] == 50
    assert p_up[-1] == 1.0, "above its 50-bar average -> long"
    assert p_dn[-1] == 0.0, "below its 50-bar average -> flat"
    assert p_up[0] == 0.0, "no exposure before the average exists"


def test_trend50_gate_opens_and_reports_a_reason():
    rising = [100 + i for i in range(80)]
    assert sg.wants_long("trend50", frame(rising)) is True
    assert "average" in sg.gate_reason("trend50", frame(rising))


def test_session_long_only_holds_inside_the_window():
    df = frame([100] * 300, start_hour=10)      # spans 10:00 onwards
    p = sg.positions_for("session_long", df,
                         {"open_hour_utc": 13, "close_hour_utc": 20})
    hours = [d.hour for d in df["Date"]]
    for pos, h in zip(p, hours, strict=False):
        assert pos == (1.0 if 13 <= h < 20 else 0.0)


def test_ladder_reaches_full_exposure_and_never_exceeds_it():
    p = sg.positions_for("ladder_dca", frame([100] * 100),
                         {"steps": 4, "bars_between": 10})
    assert p[0] == pytest.approx(0.25)
    assert max(p) == pytest.approx(1.0)
    assert p == sorted(p), "a ladder only adds exposure"


def test_vol_target_cuts_size_when_volatility_rises():
    calm = [100 + (i % 2) * 0.01 for i in range(400)]
    wild = [100 * (1 + (0.05 if i % 2 else -0.05)) for i in range(400)]
    p_calm = sg.positions_for("vol_target", frame(calm),
                              {"lookback_bars": 50, "target_vol_pct": 0.05})
    p_wild = sg.positions_for("vol_target", frame(wild),
                              {"lookback_bars": 50, "target_vol_pct": 0.05})
    assert p_calm[-1] > p_wild[-1], "calm market -> larger size"
    assert all(0.0 <= x <= 1.0 for x in p_calm + p_wild), "exposure stays 0..1"


def test_backtest_runs_every_strategy_without_error():
    df = frame([100 + (i % 7) - 3 + i * 0.05 for i in range(600)])
    for key in sg.ORDER:
        r, fund = sg.backtest(key, df, margin=100, leverage=1)
        assert r.notional == 100
        assert isinstance(r.pnl, float)
        assert fund == 0.0, "no funding supplied -> no funding PnL"


def test_compare_sorts_by_pnl_and_reports_the_benchmark():
    df = frame([100 + i * 0.05 for i in range(600)])
    rows = sg.compare(df, margin=100, leverage=1)
    assert len(rows) == 7
    pnls = [r["pnl"] for r in rows]
    assert pnls == sorted(pnls, reverse=True)
    for r in rows:
        assert "beats_buy_hold" in r and "buy_hold_pnl" in r


def test_buy_hold_row_cannot_claim_to_beat_itself():
    df = frame([100 + i * 0.05 for i in range(400)])
    rows = {r["key"]: r for r in sg.compare(df, margin=100, leverage=1)}
    bh = rows["buy_hold"]
    assert bh["beats_buy_hold"] is False
    assert bh["pnl"] == pytest.approx(bh["buy_hold_pnl"], rel=0.02)


def test_leverage_scales_every_strategy():
    df = frame([100 + i * 0.05 for i in range(400)])
    a = {r["key"]: r["pnl"] for r in sg.compare(df, margin=100, leverage=1)}
    b = {r["key"]: r["pnl"] for r in sg.compare(df, margin=100, leverage=3)}
    for k in a:
        if abs(a[k]) > 1e-9:
            assert b[k] == pytest.approx(a[k] * 3, rel=1e-6)


def test_unknown_strategy_is_rejected():
    with pytest.raises(KeyError):
        sg.backtest("nope", frame([100] * 20), margin=100, leverage=1)
    with pytest.raises(ValueError):
        sg.positions_for("barrier_harvest", frame([100] * 20), {})



# ------------------------------------------------------------------ funding
def _funding(df, rate, every=20):
    """Synthetic settlements at `rate` on every Nth bar of the frame."""
    return [{"settle_ms": int(d.timestamp() * 1000), "rate": rate, "cycle_h": 8}
            for i, d in enumerate(df["Date"]) if i % every == 0]


def test_positive_funding_rate_costs_a_long_money():
    df = frame([100] * 300)
    r, fund = sg.backtest("buy_hold", df, margin=100, leverage=1,
                          funding=_funding(df, 0.0001))
    assert fund < 0, "a positive rate means longs pay"


def test_negative_funding_rate_pays_a_long():
    """SPX500's real rate is negative — shorts pay longs — so this must be income."""
    df = frame([100] * 300)
    r, fund = sg.backtest("buy_hold", df, margin=100, leverage=1,
                          funding=_funding(df, -0.0001))
    assert fund > 0, "a negative rate means longs receive"


def test_funding_scales_with_exposure_time():
    """Holding a third of the time must accrue about a third of the funding."""
    df = frame([100] * 600, start_hour=0)
    fh = _funding(df, -0.0001, every=10)
    _, all_day = sg.backtest("buy_hold", df, margin=100, leverage=1, funding=fh)
    _, session = sg.backtest("session_long", df, margin=100, leverage=1,
                             funding=fh)
    assert abs(session) < abs(all_day), "less exposure -> less funding"


def test_funding_scales_with_notional():
    df = frame([100] * 300)
    fh = _funding(df, -0.0001)
    _, a = sg.backtest("buy_hold", df, margin=100, leverage=1, funding=fh)
    _, b = sg.backtest("buy_hold", df, margin=100, leverage=3, funding=fh)
    assert b == pytest.approx(a * 3)


def test_compare_includes_funding_in_the_benchmark():
    """The buy&hold bar must also carry funding, or low-exposure strategies
    win merely by dodging a cost that the benchmark still pays."""
    df = frame([100 + i * 0.02 for i in range(600)])
    fh = _funding(df, 0.0005, every=10)          # expensive funding
    rows = {r["key"]: r for r in
            sg.compare(df, margin=100, leverage=1, funding=fh)}
    bh = rows["buy_hold"]
    assert bh["funding_pnl"] < 0
    assert bh["buy_hold_total"] == pytest.approx(bh["total_pnl"], rel=0.02)
    assert bh["beats_buy_hold"] is False


def test_compare_ranks_on_total_including_funding():
    df = frame([100 + i * 0.02 for i in range(600)])
    rows = sg.compare(df, margin=100, leverage=1, funding=_funding(df, -0.0002))
    good = [r for r in rows if "error" not in r]
    totals = [r["total_pnl"] for r in good]
    assert totals == sorted(totals, reverse=True)
    for r in good:
        assert r["total_pnl"] == pytest.approx(r["pnl"] + r["funding_pnl"])


def test_bracket_strategy_gets_an_exposure_series():
    df = frame([100 + (i % 5) for i in range(200)])
    exp = sg.exposure_series("barrier_harvest", df)
    assert len(exp) == len(df)
    assert set(exp) <= {0.0, 1.0}
    assert any(x == 1.0 for x in exp), "a bracket strategy does hold sometimes"


# ===================== timeframes ===========================================
# The UI used to carry three interval pickers — chart, backtest, and none for the
# bot — so a person could study one timeframe, backtest another, and run neither.
def test_poll_is_half_a_bar_within_sane_bounds():
    assert sg.poll_seconds_for("Min1") == 30
    assert sg.poll_seconds_for("Min5") == 150
    assert sg.poll_seconds_for("Min60") == 300, "capped at 5 minutes"
    assert sg.poll_seconds_for("Day1") == 300, "still capped"
    assert sg.poll_seconds_for("nonsense") == 150, "falls back to Min5"


def test_per_bar_rebalancers_are_refused_on_fine_bars():
    """Measured on the real 1-minute file: 148 orders a day, 2,279x turnover in
    31 days — $10.22/month of spread at zero fees on a $163 account."""
    for key in ("trend_filter", "session_long", "vol_target"):
        assert sg.timeframe_fit("Min1", key)[0] == "avoid"
        assert sg.timeframe_fit("Min5", key)[0] == "avoid"
        assert sg.timeframe_fit("Min60", key)[0] == "good"


def test_strategies_that_do_not_rebalance_are_timeframe_independent():
    """buy_hold trades once and ladder_dca a fixed number of times, so the
    turnover argument does not apply to either. Classifying them by `kind` alone
    wrongly flagged both as ruinous on fine bars."""
    for tf in sg.TIMEFRAMES:
        assert sg.timeframe_fit(tf, "buy_hold")[0] == "good"
        assert sg.timeframe_fit(tf, "ladder_dca")[0] in ("good", "workable")


def test_a_bracket_strategy_is_only_flagged_on_sub_5m_bars():
    assert sg.timeframe_fit("Min1", "barrier_harvest")[0] == "workable"
    assert "optimistic" in sg.timeframe_fit("Min1", "barrier_harvest")[1]
    for tf in ("Min5", "Min15", "Min60", "Hour4", "Day1"):
        assert sg.timeframe_fit(tf, "barrier_harvest")[0] == "good"


def test_every_verdict_carries_a_reason():
    for tf in sg.TIMEFRAMES:
        for key in sg.ORDER:
            verdict, why = sg.timeframe_fit(tf, key)
            assert verdict in ("good", "workable", "avoid")
            assert len(why) > 40, f"{tf}/{key} has no usable explanation"


def test_strategies_are_ranked_best_fit_first():
    rows = sg.strategies_for("Min1")
    verdicts = [r["verdict"] for r in rows]
    assert verdicts == sorted(verdicts, key=lambda v:
                              {"good": 0, "workable": 1, "avoid": 2}[v])
    assert {r["key"] for r in rows} == set(sg.ORDER), "none may be dropped"


def test_an_unknown_strategy_is_refused_rather_than_defaulted():
    assert sg.timeframe_fit("Min5", "no_such_strategy")[0] == "avoid"


# ============ funding must be on both sides of the comparison ===============
def test_hold_comparison_charges_funding_to_the_benchmark_too():
    """Showing a strategy's PnL WITH funding against buy-and-hold WITHOUT it
    credits the strategy with income the benchmark also earned. On SPX500_USDT
    funding pays longs ~21.6%/yr, so the error flatters anything that sits flat
    part of the time — which is most strategies."""
    candles = frame([100 + i * 0.1 for i in range(300)])
    funding = [{"settle_ms": int(candles["Date"].iloc[i].timestamp() * 1000),
                "rate": -0.0001} for i in range(10, 290, 40)]
    res, fund = sg.backtest("barrier_harvest", candles, margin=100.0,
                            leverage=1.0, funding=funding)
    cmp_ = sg.hold_comparison(res, fund, candles, funding)
    assert cmp_["hold_funding"] > 0, "a long benchmark is paid here too"
    assert cmp_["hold_total"] == pytest.approx(res.buy_hold_pnl
                                              + cmp_["hold_funding"])
    assert cmp_["total"] == pytest.approx(res.pnl + fund)
    # the naive comparison would have claimed a bigger edge
    naive_edge = (res.pnl + fund) - res.buy_hold_pnl
    assert cmp_["edge"] < naive_edge, \
        "counting funding on one side only overstates the edge"


def test_hold_comparison_without_funding_is_a_plain_comparison():
    candles = frame([100 + i * 0.1 for i in range(300)])
    res, fund = sg.backtest("barrier_harvest", candles, margin=100.0,
                            leverage=1.0)
    cmp_ = sg.hold_comparison(res, fund, candles, None)
    assert cmp_["hold_funding"] == 0.0
    assert cmp_["beats_hold"] == res.beats_buy_hold


def test_a_tie_is_not_reported_as_beating_hold():
    candles = frame([100 + i * 0.1 for i in range(300)])
    res, fund = sg.backtest("buy_hold", candles, margin=100.0, leverage=1.0)
    cmp_ = sg.hold_comparison(res, fund, candles, None)
    assert cmp_["beats_hold"] is False, "buy and hold cannot beat itself"


# ============ nothing may be earned after liquidation =======================
def test_funding_stops_at_liquidation():
    """exposure_series re-runs the simulation UNLEVERED to find when a position
    was held, and an unlevered run is never liquidated — so it reported exposure
    for the whole window. At 200x that credited 166 days of funding to an account
    wiped out on day 23, turning a -$10 total into +$195.83.
    """
    candles = frame([100 - i * 0.5 for i in range(120)])
    funding = [{"settle_ms": int(candles["Date"].iloc[i].timestamp() * 1000),
                "rate": -0.001} for i in range(5, 115, 5)]
    res, fund = sg.backtest("barrier_harvest", candles, margin=10.0,
                            leverage=200, funding=funding)
    assert res.liquidated is True
    assert fund == pytest.approx(0.0, abs=0.51), \
        "funding must stop when the account does"
    cmp_ = sg.hold_comparison(res, fund, candles, funding)
    assert cmp_["total"] >= -10.0 - 1e-6, "total worse than the margin posted"
    assert cmp_["hold_total"] >= -10.0 - 1e-6, \
        "the benchmark is a real long facing the same move"


def test_a_surviving_run_still_earns_funding_for_the_whole_window():
    candles = frame([100 + i * 0.05 for i in range(200)])
    funding = [{"settle_ms": int(candles["Date"].iloc[i].timestamp() * 1000),
                "rate": -0.0002} for i in range(5, 195, 10)]
    res, fund = sg.backtest("barrier_harvest", candles, margin=100.0,
                            leverage=1, funding=funding)
    assert res.liquidated is False
    assert fund > 0.0, "a surviving long is still paid"


@pytest.mark.parametrize("lev", [1, 3, 10, 50, 125, 200])
def test_no_leverage_can_lose_more_than_the_margin(lev):
    """The property that matters, across the whole leverage range.

    This exposed a third instance of the same bug: funding is settled against the
    margin balance, so on a contract where longs PAY, the payments liquidate the
    account once they exhaust it. Applying funding as a lump sum after the price
    simulation let the combined figure pass the margin — a 3x run reporting a loss
    larger than the money posted. It is capped now; see _cap_funding_at_margin for
    why a cap is not the same as modelling it properly.
    """
    candles = frame([100 - i * 0.4 for i in range(150)])
    funding = [{"settle_ms": int(candles["Date"].iloc[i].timestamp() * 1000),
                "rate": 0.001} for i in range(5, 145, 5)]      # longs PAY here
    res, fund = sg.backtest("barrier_harvest", candles, margin=10.0,
                            leverage=lev, funding=funding)
    assert res.pnl + fund >= -10.0 - 1e-6, \
        f"{lev}x lost more than the margin: {res.pnl + fund}"


def test_a_run_that_took_no_trades_earns_no_funding():
    """exposure_series re-runs the simulation to find when a position was held, and
    running it WITHOUT the limits reported exposure for periods the limited run
    never traded — crediting $41.06 of funding to a backtest with zero trades."""
    candles = frame([100 + i * 0.05 for i in range(200)])
    funding = [{"settle_ms": int(candles["Date"].iloc[i].timestamp() * 1000),
                "rate": -0.001} for i in range(5, 195, 5)]
    res, fund = sg.backtest("barrier_harvest", candles, margin=10.0, leverage=3,
                            funding=funding,
                            limits={"min_equity": 100.0, "starting_equity": 10.0})
    assert res.trades == [] and res.halted_reason
    assert fund == 0.0, "no position, no funding"


def test_limits_flow_through_to_the_notional():
    candles = frame([100 + i * 0.05 for i in range(200)])
    res, _ = sg.backtest("barrier_harvest", candles, margin=10.0, leverage=200,
                         limits={"max_notional": 400.0})
    assert res.notional == 400.0
