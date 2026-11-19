"""The classic_b batch of the reviewed GitHub repos' strategies (tradingagents/gh_strats/classic_b.py):
no signal reads a later candle, every strategy trades, three of them equal their repo's own rule
written out by hand, and the package merges the batch (Nov 18, 2026)."""
import time

import numpy as np
import pandas as pd
import pytest

from tradingagents.gh_strats import classic_b as cb

DAILY_ONLY = {"gh_finrl_tsmom"}


def _df(n=900, seed=5, freq="1h"):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
    spread = np.abs(rng.normal(0, 0.006, n))
    gap = rng.normal(0, 0.002, n)                      # opens a little off the last close
    idx = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": np.r_[close[0], close[:-1]] * (1 + gap),
                         "high": close * (1 + spread), "low": close * (1 - spread), "close": close,
                         "volume": rng.lognormal(3, 0.6, n)}, index=idx)


def _key(s):
    return None if s is None else (s.entry, s.direction if s.entry else None, s.exit, s.exit_dir)


def _path(sigs):
    """The position an engine with no stop and no target holds after each candle."""
    pos, out = 0, []
    for s in sigs:
        if s is not None:
            side = {1: "long", -1: "short"}.get(pos)
            if pos and s.exit and s.exit_dir in (None, side):
                pos = 0
            if s.entry and pos == 0:
                pos = 1 if s.direction == "long" else -1
        out.append(pos)
    return np.array(out)


@pytest.mark.parametrize("name", list(cb.GRID))
def test_no_signal_reads_a_later_candle(name):
    if name in DAILY_ONLY:
        df, cuts = _df(1300, seed=3, freq="1D"), (400, 450, 731, 900, 1299)
    else:
        df, cuts = _df(700), (260, 333, 401, 520, 699)
    strat = cb.STRATEGIES[name]
    for params in cb.GRID[name]:
        whole = [_key(s) for s in strat.signals_all(df, params)]
        assert len(whole) == len(df)
        for cut in cuts:
            part = [_key(s) for s in strat.signals_all(df.iloc[:cut], params)]
            assert part == whole[:cut], (name, params, cut)


@pytest.mark.parametrize("name", list(cb.GRID))
def test_every_strategy_trades_on_a_moving_market(name):
    df = _df(2000, seed=11, freq="1D" if name in DAILY_ONLY else "1h")
    n = sum(bool(s and s.entry) for p in cb.GRID[name] for s in cb.STRATEGIES[name].signals_all(df, p))
    assert n > 0, name


def test_the_monthly_signal_is_silent_off_daily_candles():
    df = _df(2000, seed=11, freq="4h")
    for p in cb.GRID["gh_finrl_tsmom"]:
        assert all(s is None for s in cb.STRATEGIES["gh_finrl_tsmom"].signals_all(df, p))


def test_tables_agree():
    assert set(cb.GRID) == set(cb.STRATEGIES) == set(cb.TARGETS) == set(cb.REPO_OF) == set(cb.RULE_OF)
    assert all(n.startswith("gh_") for n in cb.STRATEGIES)
    assert all(1 <= len(v) <= 2 for v in cb.GRID.values())
    assert sum(len(v) for v in cb.GRID.values()) <= 24
    assert set(cb.STOPS) <= set(cb.STRATEGIES)


def test_the_breakout_is_nehrens_own_resistance_support_strategy():
    df = _df(800)
    m = 30

    def resistance_support_strategy(prices, params):   # exercises/chapter5_solutions.ipynb
        rs_buy = prices.rolling(params.get("m")).max().shift()
        rs_sell = prices.rolling(params.get("m")).min().shift()
        signal = 0 * prices
        signal.loc[prices > rs_buy] = 1
        signal.loc[prices < rs_sell] = -1
        return signal

    want = resistance_support_strategy(df["close"], {"m": m}).to_numpy()
    got = _path(cb.NehrenBreakout().signals_all(df, {"m": m}))
    assert (got[m:] == want[m:]).all()
    assert (got[m:] != 0).sum() > 20


def test_the_dip_buy_is_pybrokers_own_buy_low():
    df = _df(800)
    c, lo = df["close"].to_numpy(), df["low"].to_numpy()
    held, left, want = False, 0, []
    for i in range(len(df)):                           # notebook 2: buy_low, hold_bars = 3
        if held:
            left -= 1
            if left == 0:
                held = False
        if not held and i >= 1 and c[i] < lo[i - 1]:
            held, left = True, 3
        want.append(1 if held else 0)
    got = _path(cb.PybDip().signals_all(df, {"hold": 3}))
    assert (got == np.array(want)).all()
    assert sum(want) > 50


def _ttr_ema(x, n):
    out = np.full(len(x), np.nan)
    out[n - 1] = x[:n].mean()
    a = 2.0 / (n + 1)
    for t in range(n, len(x)):
        out[t] = a * x[t] + (1 - a) * out[t - 1]
    return out


def test_the_ema_pair_is_tmr_cryptos_own_walk_forward():
    df = _df(2880, seed=9)                             # 120 days of 60-minute candles
    c = df["close"].to_numpy()
    td, sd = 14, 10
    T, S = td * 24, sd * 24
    ema = {p: _ttr_ema(c, p) for p in cb.TMR_PERIODS}
    s0 = 199                                           # precalculate(): rows from max(period)
    rows = list(range(s0, len(c)))
    pnl, pos_of = {}, {}
    for s in cb.TMR_SLOW:                              # strategy.r: slow outer, fast inner
        for f in cb.TMR_FAST:
            pos = [np.nan] + [1.0 if ema[f][t - 1] > ema[s][t - 1] else -1.0 for t in rows[1:]]
            p = []
            for r, t in enumerate(rows):
                tr = abs(pos[r] - pos[r - 1]) if r >= 1 else np.nan
                g = 0.0 if np.isnan(pos[r]) else pos[r] * np.log(c[t] / c[t - 1])
                p.append(g - (0.0 if np.isnan(tr) else tr) * 0.001)
            pnl[(f, s)], pos_of[(f, s)] = np.array(p), pos
    want = np.zeros(len(c))
    k = 0
    while k * S + T <= len(rows):                      # WfHelper.calculate.indexes, block by block
        a = k * S
        sh = [pnl[pr][a:a + T].mean() / pnl[pr][a:a + T].std(ddof=1) for pr in cb.TMR_PAIRS]
        best = cb.TMR_PAIRS[int(np.argmax(sh))]        # which.max: the first of the best
        for r in range(a + T, min(a + T + S, len(rows))):
            want[rows[r] - 1] = pos_of[best][r]        # the position of row r is set at candle r - 1
        k += 1
    t0 = time.perf_counter()
    sig = cb.TmrEmaWf().signals_all(df, {"train_days": td, "test_days": sd})
    assert time.perf_counter() - t0 < 1.0
    got = _path(sig)
    start = s0 + T - 1
    bad = np.flatnonzero(got[start:-1] != want[start:-1])
    assert len(bad) == 0, (start + bad[:5], got[start + bad[:5]], want[start + bad[:5]])
    assert got[-1] in (1, -1)                          # the last candle sets the coming candle's row
    assert (np.diff(got[start:]) != 0).sum() > 5


def test_the_zscore_rule_is_the_skills_own_generate_signals():
    df = _df(800)
    c = df["close"]
    z = ((c - c.rolling(40).mean()) / c.rolling(40).std()).to_numpy()
    cur, want = 0, []
    for zi in z:                                       # mean_reversion_test.py generate_signals
        if not np.isnan(zi):
            if cur == 0:
                cur = 1 if zi < -2 else -1 if zi > 2 else 0
            elif cur == 1 and (zi > 0 or zi < -3):
                cur = 0
            elif cur == -1 and (zi < 0 or zi > 3):
                cur = 0
        want.append(cur)
    got = _path(cb.AgiZscore().signals_all(df, {"lookback": 40}))
    assert (got == np.array(want)).all()


def test_the_package_loads_this_batch():
    import tradingagents.gh_strats as g
    assert "classic_b" in g.LOADED
    for name in cb.STRATEGIES:
        assert g.STRATEGIES[name] is cb.STRATEGIES[name]
    assert g.STOPS["gh_agi_rsi"] == (0.05,)
    assert g.STOPS["gh_nehren_ma"] == g.DEFAULT_STOPS
    assert any(c["strategy"] == "gh_agi_ema_cross" and c["target"] == round(c["stop"] * 2, 6)
               for c in g.combos())
