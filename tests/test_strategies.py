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


def test_registry_has_exactly_six_long_only_strategies():
    assert len(sg.REGISTRY) == 6
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


def test_session_long_only_holds_inside_the_window():
    df = frame([100] * 300, start_hour=10)      # spans 10:00 onwards
    p = sg.positions_for("session_long", df,
                         {"open_hour_utc": 13, "close_hour_utc": 20})
    hours = [d.hour for d in df["Date"]]
    for pos, h in zip(p, hours):
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
    assert len(rows) == 6
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
