"""The rest of the reviewed GitHub repos' plain rules (tradingagents/gh_strats/rest.py, Nov 18, 2026):
no signal reads a later candle, every rule trades, and every repo of the batch is either ported or
named with why."""
import numpy as np
import pandas as pd
import pytest

from tradingagents.gh_strats import rest as r

REPOS = (
    "AI4Finance-Foundation/FinRL", "AI4Finance-Foundation/FinRL-Tutorials",
    "TradeMaster-NTU/TradeMaster", "Danny-397/RL-for-Crypto-and-stocks-",
    "Thomas-lcb/Deep-Reinforcemen-tLearning-Trading-Agent", "ebrahimpichka/DeepRL-trade",
    "772435284/transformers_versus_lstms_for_electronic_trading", "jwallbridge/translob",
    "stefan-jansen/machine-learning-for-trading",
    "PacktPublishing/Machine-Learning-for-Algorithmic-Trading-Second-Edition",
    "ahmedas91/ml-ohlcv-alpha-signals", "abailey81/Crypto-Statistical-Arbitrage",
    "YuxinSUN89/quant-ohlcv-feature", "mindees/crypto-ai", "cbailes/awesome-deep-trading",
    "bernhardbrugger/awesome-ai-trading", "topics/walk-forward-validation",
)


def _df(n=900, seed=5):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
    spread = np.abs(rng.normal(0, 0.006, n))
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"open": np.r_[close[0], close[:-1]], "high": close * (1 + spread),
                         "low": close * (1 - spread), "close": close,
                         "volume": rng.lognormal(3, 0.6, n)}, index=idx)


def _key(s):
    return None if s is None else (s.entry, s.direction if s.entry else None, s.exit, s.exit_dir)


@pytest.mark.parametrize("name", list(r.GRID))
def test_no_signal_reads_a_later_candle(name):
    df = _df(700)
    strat = r.STRATEGIES[name]
    for params in r.GRID[name]:
        whole = [_key(s) for s in strat.signals_all(df, params)]
        assert len(whole) == len(df)
        for cut in (260, 333, 401, 520, 699):
            part = [_key(s) for s in strat.signals_all(df.iloc[:cut], params)]
            assert part == whole[:cut], (name, params, cut)


@pytest.mark.parametrize("name", list(r.GRID))
def test_every_strategy_trades_on_a_moving_market(name):
    df = _df(2000, seed=11)
    for params in r.GRID[name]:
        n = sum(bool(s and s.entry) for s in r.STRATEGIES[name].signals_all(df, params))
        assert n > 0, (name, params)


def test_every_repo_of_the_batch_is_ported_or_named():
    named = {k.split(":")[0].strip() for k in r.NOT_PORTED}
    ported = set(r.REPO_OF.values())
    missing = [repo for repo in REPOS if repo not in named | ported]
    assert not missing, missing
    for name in r.STRATEGIES:
        assert name.startswith("gh_") and name in r.GRID and name in r.RULE_OF and name in r.TARGETS
        assert 1 <= len(r.GRID[name]) <= 2


def test_the_package_loads_this_batch():
    import tradingagents.gh_strats as g
    assert "rest" in g.LOADED
    assert set(r.STRATEGIES) <= set(g.STRATEGIES)


def test_the_ma_baseline_is_dannys_own_rule():
    df = _df(500)
    c = df["close"].to_numpy()
    got = r.DannyMaBaseline().signals_all(df, {"fast": 10, "slow": 30})
    for i in range(30, len(df)):
        on = c[i - 9: i + 1].mean() > c[i - 29: i + 1].mean()   # baselines._ma_crossover_action
        assert bool(got[i].entry) == on and bool(got[i].exit) == (not on), i


def test_the_ahmed_reversal_holds_its_candles_and_never_overlaps():
    df = _df(2000, seed=11)
    for hold in (1, 5):
        sigs = r.AhmedReversal().signals_all(df, {"lookback": 250, "pct": 0.10, "hold": hold})
        side, since, entries = None, None, 0
        for i, s in enumerate(sigs):
            if s is None:
                continue
            if s.exit:
                assert side is not None and s.exit_dir == side and i - since == hold, (hold, i)
                side = None
            if s.entry:
                assert side is None, (hold, i)
                side, since, entries = s.direction, i, entries + 1
        assert entries > 0


def test_the_turbulence_switch_sells_on_a_shock():
    df = _df(900)
    c = df.columns.get_loc("close")
    df.iloc[800:, c] = df["close"].iloc[799] * 0.85        # one 15% drop, then flat
    sigs = r.FinrlTurbulenceHold().signals_all(df, {"window": 252, "quantile": 0.99})
    assert sigs[800].exit and not sigs[800].entry
