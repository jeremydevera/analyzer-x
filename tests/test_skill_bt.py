"""The backtesting-trading-strategies skill run on every coin-timeframe (tradingagents/skill_bt.py):
its own signals, computed over a trailing window, give the SAME trades as the skill's own engine,
and a setting is chosen on the older 70% only."""
import numpy as np
import pandas as pd
import pytest

from tradingagents import skill_bt as sb
from tradingagents.vendor.btstrat import strategies as ss


def _df(n=900, seed=3):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    idx = pd.date_range("2026-01-01", periods=n, freq="1h")
    return pd.DataFrame({"open": close, "high": close * 1.005, "low": close * 0.995, "close": close,
                         "volume": 1.0}, index=idx)


@pytest.mark.parametrize("name,params", [("sma_crossover", {"fast_period": 20, "slow_period": 50}),
                                         ("rsi_reversal", {"period": 14, "overbought": 70, "oversold": 30}),
                                         ("bollinger_bands", {"period": 20, "std_dev": 2.0}),
                                         ("breakout", {"lookback": 20, "threshold": 0.0})])
def test_windowed_signals_equal_the_skills_whole_history_signals(name, params):
    df = _df(500)
    st = ss.get_strategy(name)
    fast = sb.signals(df, name, params)
    for i in range(st.lookback, len(df)):
        full = st.generate_signals(df.iloc[: i + 1], params)
        f = fast[i]
        assert (f.entry, f.exit, f.direction) == (full.entry, full.exit, full.direction), i


def test_a_stop_closes_a_losing_trade_and_fees_are_paid_both_ways():
    df = _df(60)
    sigs = [None] * len(df)
    sigs[10] = ss.Signal(entry=True, direction="long")
    for i in range(11, len(df)):
        sigs[i] = ss.Signal()
    df.iloc[20, df.columns.get_loc("close")] = df["close"].iloc[10] * 0.95
    tr = sb.walk(df, sigs, stop=0.03, fee=0.00075, slip=0.0)
    assert tr[0]["why"] == "SL"
    move = df["close"].iloc[20] / df["close"].iloc[10] - 1
    assert tr[0]["pnl"] == pytest.approx(100 * move - 0.075 - 0.075 * (1 + move), abs=1e-3)


def test_a_setting_is_chosen_on_the_older_candles_only():
    out = sb.pair(_df(700), fee=0.00075, slip=0.0003)
    assert out["combos"] == sum(len(v) for v in sb.GRID.values()) * len(sb.STOPS)
    assert 1 <= len(out["picks"]) <= sb.PER_PAIR
    for p in out["picks"]:
        older = [t for t in p["trades"] if t["entry_ms"] < out["split_ms"]]
        assert p["older"]["trades"] == len(older)
        if not p["older_lost"]:
            assert p["older"]["trades"] >= sb.MIN_OLDER and p["older"]["profit"] > 0


@pytest.mark.parametrize("unit", ["s", "ms", "ns"])
def test_trade_times_are_real_whatever_unit_the_candles_carry(unit):
    df = _df(700)
    df.index = df.index.as_unit(unit)
    out = sb.pair(df, fee=0.00075, slip=0.0003)
    first = int(df.index[0].value // 1_000_000)
    assert out["start_ms"] == first and out["split_ms"] > first
    assert any(p["newer"]["trades"] for p in out["picks"]) or out["bar"] is not None
    for p in out["picks"]:
        assert all(t["entry_ms"] >= first for t in p["trades"])


def test_the_skill_shard_has_no_bar_floor_but_two():
    # RCA-2026-11-05-C: a 60-candle floor skipped 158 young coin-timeframes against CLAUDE.md's
    # "no bar floor" rule; a strategy whose lookback exceeds the history simply makes no trade
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / ".github" / "scripts" / "skill_shard.py"
    floors = [int(n) for n in re.findall(r"len\(df\) < (\d+)", src.read_text(encoding="utf-8"))]
    assert floors == [2]
    out = sb.pair(_df(40), fee=0.00075, slip=0.0003)      # shorter than most lookbacks
    assert out["bars"] == 40
