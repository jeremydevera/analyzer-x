"""The technical-analysis and backtesting-frameworks skills' own strategies (tradingagents/skill_ta.py),
run through skill_bt's walk-forward on every coin-timeframe (Nov 05, 2026)."""
import numpy as np
import pandas as pd
import pytest

from tradingagents import skill_bt as sb, skill_ta as st
from tradingagents.vendor.btstrat.strategies import Signal


def _df(n=900, seed=5):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
    spread = np.abs(rng.normal(0, 0.006, n))
    idx = pd.date_range("2026-01-01", periods=n, freq="1h")
    return pd.DataFrame({"open": np.r_[close[0], close[:-1]], "high": close * (1 + spread),
                         "low": close * (1 - spread), "close": close,
                         "volume": rng.lognormal(3, 0.6, n)}, index=idx)


def _key(s):
    return None if s is None else (s.entry, s.direction if s.entry else None, s.exit, s.exit_dir)


@pytest.mark.parametrize("name", list(st.GRID))
def test_no_signal_reads_a_later_candle(name):
    df = _df(700)
    strat = st.STRATEGIES[name]
    for params in st.GRID[name]:
        whole = [_key(s) for s in strat.signals_all(df, params)]
        for cut in (260, 333, 401, 520, 699):
            part = [_key(s) for s in strat.signals_all(df.iloc[:cut], params)]
            assert part == whole[:cut], (name, params, cut)


@pytest.mark.parametrize("name", list(st.GRID))
def test_every_strategy_trades_on_a_moving_market(name):
    df = _df(2000, seed=11)
    n = sum(bool(s and s.entry) for p in st.GRID[name] for s in st.STRATEGIES[name].signals_all(df, p))
    assert n > 0, name


def test_the_spring_is_the_skills_own_detect_spring():
    df = _df(800)

    def detect_spring(df, lookback=50):                 # technical-analysis references/patterns.md
        recent_low = df["low"].rolling(lookback).min()
        return ((df["low"] < recent_low.shift(1)) & (df["close"] > recent_low.shift(1))
                & (df["volume"] < df["volume"].rolling(20).mean()))

    want = detect_spring(df).to_numpy()
    got = st.WyckoffSpring().signals_all(df, {"lookback": 50})
    for i in range(51, len(df)):
        assert (got[i].entry and got[i].direction == "long") == bool(want[i]), i


def test_momentum_is_the_frameworks_own_momentum_signal():
    df = _df(800)
    on = (df["close"] > df["close"].rolling(50).mean()).astype(int).to_numpy()   # momentum_signal
    got = st.BfMomentum().signals_all(df, {"lookback": 50})
    for i in range(51, len(df)):
        assert bool(got[i].entry) == (on[i] == 1 and on[i - 1] == 0), i
        assert bool(got[i].exit) == (on[i] == 0 and on[i - 1] == 1), i


def test_a_target_closes_a_winner_at_twice_the_stop():
    df = _df(60)
    sigs = [Signal() for _ in range(len(df))]
    sigs[10] = Signal(entry=True, direction="long")
    c = df.columns.get_loc("close")
    df.iloc[11:, c] = df["close"].iloc[10]
    df.iloc[25, c] = df["close"].iloc[10] * 1.031
    tr = sb.walk(df, sigs, stop=0.015, fee=0.00075, slip=0.0, target=0.03)
    assert tr[0]["why"] == "TP" and tr[0]["exit_ms"] == sb._ms(df.index)[25]


def test_a_short_side_exit_never_closes_a_long():
    df = _df(60)
    c = df.columns.get_loc("close")
    df.iloc[:, c] = 100.0
    sigs = [st.TaSignal() for _ in range(len(df))]
    sigs[10] = st.TaSignal(entry=True, direction="long")
    sigs[15] = st.TaSignal(exit=True, exit_dir="short")
    sigs[20] = st.TaSignal(exit=True, exit_dir="long")
    tr = sb.walk(df, sigs, stop=0.03, fee=0.0, slip=0.0)
    assert tr[0]["exit_ms"] == sb._ms(df.index)[20] and tr[0]["why"] == "SIGNAL"


def test_the_two_skills_are_chosen_on_the_older_candles_with_their_own_targets():
    out = sb.pair(_df(1200, seed=7), fee=0.00075, slip=0.0003, grid=st.GRID, targets=st.TARGETS)
    assert out["combos"] == sum(len(v) for v in st.GRID.values()) * len(sb.STOPS)
    assert 1 <= len(out["picks"]) <= sb.PER_PAIR
    for p in out["picks"]:
        r = st.TARGETS[p["strategy"]]
        assert p["target"] == (round(p["stop"] * r, 6) if r else None)
        assert ("target" in sb.label(p)) == bool(r)
        older = [t for t in p["trades"] if t["entry_ms"] < out["split_ms"]]
        assert p["older"]["trades"] == len(older)


def test_the_backtesting_skill_run_is_unchanged_without_a_grid():
    df = _df(500)
    out = sb.pair(df, fee=0.00075, slip=0.0003)
    assert out["combos"] == sum(len(v) for v in sb.GRID.values()) * len(sb.STOPS)
    assert all(p["target"] is None and "target" not in sb.label(p) for p in out["picks"])
