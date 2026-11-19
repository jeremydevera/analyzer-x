"""THE REST OF THE REVIEWED REPOS: the reinforcement-learning, order-book, machine-learning-book and
reading-list repos (Nov 18, 2026).

Most of these repos have no hand-written trading rule: a neural network decides, trained per market,
which this engine cannot do. What IS a plain rule is ported here, from each repo's own code:

* `gh_danny_ma_baseline` - Danny-397's rule baseline (`rl_trader/evaluation/baselines.py`
  `_ma_crossover_action`): long while the 10-candle average is above the 30-candle one, else flat.
* `gh_finrl_turbulence_hold` - FinRL's turbulence switch (`finrl/meta/preprocessor/preprocessors.py`
  `calculate_turbulence`, used by `env_stocktrading.py`) on FinRL's own buy-and-hold baseline, for
  ONE coin: the Mahalanobis distance of today's return from the previous 252 returns is, for one
  series, (r - mean)^2 / variance. Long while it is under the threshold, out (and no buying) at or
  above it. FinRL's threshold is the 0.99 (or the overwritten 0.90) quantile of the IN-SAMPLE
  turbulence; here it is the quantile of every turbulence value BEFORE the candle (at least 252 of
  them), so no candle reads its own future.
* `gh_mlt_rsi_reversion` - stefan-jansen's chapter 16 rule (`16_strategy_simulation/
  03_single_asset_vectorbt.py`): 14-candle RSI (simple averages, vectorbt's default) under 30 ->
  long, out when it is over 70. The book shifts both by a row to fill at the NEXT bar; this engine
  fills at the close the RSI is read on, which is the same decision.
* `gh_mlt_momentum_band` - stefan-jansen's chapter 16 stateful strategy (`05_stateful_strategies.py`
  `make_signals("momentum", lookback=20)` with `entry_threshold=0.01`, `exit_threshold=-0.01`): long
  when the 20-candle return is over +1%, out when it is under -1%. Its adaptive Kelly sizing is not
  ported (the engine stakes a fixed $5 x 20x).
* `gh_ahmed_reversal` - A SINGLE-COIN STAND-IN; the repo ranks ~1,000 stocks against each other each
  day. ahmedas91's strongest simple features are 1-day and 5-day reversal (`src/signals/baseline.py`);
  here a coin is bought when BOTH its 1-candle and 5-candle return sit in the bottom 10% of its own
  previous 250 values, sold short when both sit in the top 10%, and held `hold` candles (5, the
  repo's 5-day horizon; 1, its daily rebuild). The hold is tracked inside `signals_all` from candles
  0..i only: a stop that closed the trade early leaves the coin flat until the next signal after the
  hold would have ended.

Everything else is named in NOT_PORTED with why, and the repo's own result where it printed one.
Every signal at candle i is worked out from candles 0..i only (the tests cut the frame and compare).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.skill_ta import _rsi, _sma, _to_signals


def _ret(c: np.ndarray, k: int) -> np.ndarray:
    out = np.full(len(c), np.nan)
    if len(c) > k:
        out[k:] = c[k:] / c[:-k] - 1
    return out


class DannyMaBaseline:
    """Long while SMA(fast) > SMA(slow), else flat (Danny-397 `_ma_crossover_action`)."""

    name = "gh_danny_ma_baseline"

    def signals_all(self, df, params):
        f, s = int(params["fast"]), int(params["slow"])
        fa, sl = _sma(df["close"], f), _sma(df["close"], s)
        with np.errstate(invalid="ignore"):
            on = fa > sl
        n = len(df)
        return _to_signals(n, s, on, np.zeros(n, bool), long_out=~on)


class FinrlTurbulenceHold:
    """FinRL's buy-and-hold baseline under FinRL's turbulence switch, for one coin."""

    name = "gh_finrl_turbulence_hold"

    def signals_all(self, df, params):
        w, q = int(params["window"]), float(params["quantile"])
        c = df["close"].to_numpy(dtype=float)
        n = len(c)
        r = pd.Series(_ret(c, 1))
        # FinRL: the previous `w` returns (rows i-w .. i-1), the first return being blank
        mean = r.rolling(w).mean().shift(1).to_numpy()
        var = r.rolling(w).var().shift(1).to_numpy()            # pandas cov: ddof 1
        start = w + 1
        turb = np.full(n, np.nan)
        count = 0
        for i in range(start, n):
            v = var[i]
            t = (r.iat[i] - mean[i]) ** 2 / v if v > 0 else 0.0   # pinv of a zero variance = 0
            if t > 0:
                count += 1
                t = t if count > 2 else 0.0                     # FinRL zeroes the first two
            else:
                t = 0.0
            turb[i] = t
        # the threshold: the quantile of every turbulence value before this candle, 252+ of them
        thr = pd.Series(turb).expanding(min_periods=w).quantile(q).shift(1).to_numpy()
        with np.errstate(invalid="ignore"):
            calm = turb < thr
            wild = turb >= thr
        return _to_signals(n, start + w, calm, np.zeros(n, bool), long_out=wild)


class MltRsiReversion:
    """stefan-jansen ch.16: RSI(14) < 30 -> long, RSI > 70 -> out."""

    name = "gh_mlt_rsi_reversion"

    def signals_all(self, df, params):
        p, lo, hi = int(params["window"]), float(params["lower"]), float(params["upper"])
        rsi = _rsi(df["close"], p)
        with np.errstate(invalid="ignore"):
            long_in, long_out = rsi < lo, rsi > hi
        n = len(df)
        return _to_signals(n, p + 1, long_in, np.zeros(n, bool), long_out=long_out)


class MltMomentumBand:
    """stefan-jansen ch.16 stateful strategy: 20-candle return > +1% -> long, < -1% -> out."""

    name = "gh_mlt_momentum_band"

    def signals_all(self, df, params):
        k = int(params["lookback"])
        up, dn = float(params["entry"]), float(params["exit"])
        m = _ret(df["close"].to_numpy(dtype=float), k)
        with np.errstate(invalid="ignore"):
            long_in, long_out = m > up, m < dn
        n = len(df)
        return _to_signals(n, k + 1, long_in, np.zeros(n, bool), long_out=long_out)


class AhmedReversal:
    """Single-coin stand-in of ahmedas91's 1-day + 5-day reversal: both returns in the coin's own
    bottom (top) `pct` of its previous `lookback` values -> long (short), held `hold` candles."""

    name = "gh_ahmed_reversal"

    def signals_all(self, df, params):
        lb, pct, hold = int(params["lookback"]), float(params["pct"]), int(params["hold"])
        c = df["close"].to_numpy(dtype=float)
        n = len(c)
        r1, r5 = _ret(c, 1), _ret(c, 5)
        warm = 5 + lb                       # r5 exists from 5; lb earlier values of it from 5 + lb

        def share(r):
            """At i: the share of the previous `lb` values below r[i], and above it."""
            below, above = np.full(n, np.nan), np.full(n, np.nan)
            if n > warm:
                win = np.lib.stride_tricks.sliding_window_view(r[:-1], lb)   # win[j] = r[j..j+lb-1]
                idx = np.arange(warm, n)
                past = win[idx - lb]                                         # r[i-lb .. i-1]
                cur = r[idx][:, None]
                below[idx] = (past < cur).sum(axis=1) / lb
                above[idx] = (past > cur).sum(axis=1) / lb
            return below, above

        b1, a1 = share(r1)
        b5, a5 = share(r5)
        with np.errstate(invalid="ignore"):
            want_long = (b1 < pct) & (b5 < pct)
            want_short = (a1 < pct) & (a5 < pct)
        long_in, short_in = np.zeros(n, bool), np.zeros(n, bool)
        long_out, short_out = np.zeros(n, bool), np.zeros(n, bool)
        side, since = None, 0               # the strategy's own position, ignoring stops
        for i in range(warm, n):
            if side is not None and i - since >= hold:
                (long_out if side == "long" else short_out)[i] = True
                side = None
            if side is None:
                if want_long[i]:
                    long_in[i], side, since = True, "long", i
                elif want_short[i]:
                    short_in[i], side, since = True, "short", i
        return _to_signals(n, warm, long_in, short_in, long_out, short_out)


STRATEGIES = {s.name: s for s in (DannyMaBaseline(), FinrlTurbulenceHold(), MltRsiReversion(),
                                  MltMomentumBand(), AhmedReversal())}

GRID = {
    "gh_danny_ma_baseline": [{"fast": 10, "slow": 30}],
    # 0.99: the threshold FinRL uses; 0.90: the in-sample quantile its ensemble computes and overwrites
    "gh_finrl_turbulence_hold": [{"window": 252, "quantile": 0.99}, {"window": 252, "quantile": 0.90}],
    "gh_mlt_rsi_reversion": [{"window": 14, "lower": 30, "upper": 70}],
    "gh_mlt_momentum_band": [{"lookback": 20, "entry": 0.01, "exit": -0.01}],
    # hold 5: the repo's 5-day horizon; hold 1: its daily rebuild
    "gh_ahmed_reversal": [{"lookback": 250, "pct": 0.10, "hold": 5},
                          {"lookback": 250, "pct": 0.10, "hold": 1}],
}

STOPS: dict = {}                            # none of these rules has a stop of its own

TARGETS = {name: None for name in STRATEGIES}   # out by its own exit (or the engine's stop)

REPO_OF = {
    "gh_danny_ma_baseline": "Danny-397/RL-for-Crypto-and-stocks-",
    "gh_finrl_turbulence_hold": "AI4Finance-Foundation/FinRL",
    "gh_mlt_rsi_reversion": "stefan-jansen/machine-learning-for-trading",
    "gh_mlt_momentum_band": "stefan-jansen/machine-learning-for-trading",
    "gh_ahmed_reversal": "ahmedas91/ml-ohlcv-alpha-signals",
}

RULE_OF = {
    "gh_danny_ma_baseline": "Buy while the 10-candle average is above the 30-candle average and sell "
                            "when it is not (rl_trader/evaluation/baselines.py, the moving-average "
                            "baseline the study's agent had to beat).",
    "gh_finrl_turbulence_hold": "Hold the coin while today's move is not unusually large against the "
                                "last 252 candles (FinRL's turbulence index, one coin) and sell at "
                                "or above the 99% (or 90%) mark of all earlier readings "
                                "(finrl/meta/preprocessor/preprocessors.py calculate_turbulence).",
    "gh_mlt_rsi_reversion": "Buy when the 14-candle RSI is under 30 and sell when it is over 70 "
                            "(16_strategy_simulation/03_single_asset_vectorbt.py).",
    "gh_mlt_momentum_band": "Buy when the price is more than 1% above where it was 20 candles ago "
                            "and sell when it is more than 1% below "
                            "(16_strategy_simulation/05_stateful_strategies.py).",
    "gh_ahmed_reversal": "A single-coin stand-in (the repo ranks across ~1,000 stocks): buy when "
                         "the coin's 1-candle and 5-candle drops are both in the worst 10% of its "
                         "own last 250, short when both rises are in the best 10%, and close after "
                         "5 (or 1) candles (src/signals/baseline.py reversal features).",
}

NOT_PORTED = {
    "AI4Finance-Foundation/FinRL: RL agents": "A2C/PPO/DDPG/TD3/SAC/TQC/CrossQ networks trained on "
        "a 30-stock basket choose share counts each day; training a network per coin is not a rule "
        "this engine can run (only the turbulence switch is ported). No results printed in the repo.",
    "AI4Finance-Foundation/FinRL: ensemble": "Picks the best of five trained agents every 63 days "
        "by Sharpe - trained models again, and the same choose-on-recent idea the picker lab found "
        "does not carry forward.",
    "AI4Finance-Foundation/FinRL-Tutorials": "Notebooks running FinRL's trained agents (ensemble, "
        "portfolio allocation, multi-crypto PPO, forex, A-shares); the triple-barrier part only "
        "labels data for a neural network. Its own saved runs: the ensemble lost 3.9% a year, and "
        "3 of 5 single agents ended down.",
    "TradeMaster-NTU/TradeMaster": "Every method is a trained RL agent (DeepScalper, Double DQN on "
        "order books, EIIE, DeepTrader, ...); its only plain baseline is buy-and-hold. DeepScalper's "
        "BTC result: -199.6% on validation, one seed.",
    "Danny-397/RL-for-Crypto-and-stocks-: PPO agent": "A PPO network trained per coin; its own "
        "result: crypto -44.6% against buy-and-hold +10% over 10-30 seeds.",
    "Danny-397/RL-for-Crypto-and-stocks-: supervised baselines": "Ridge and logistic models fitted "
        "on a training split - trained models, not rules.",
    "Thomas-lcb/Deep-Reinforcemen-tLearning-Trading-Agent": "A PPO agent on BTC 1-minute candles; "
        "its 200-minute cooldown is attached only to that agent and to a random agent, never to a "
        "rule. Its own result: +9.10% on test days it was tuned on, -9.51% on validation against "
        "random -9.30%.",
    "ebrahimpichka/DeepRL-trade": "PPO and DQN networks trading GOOG long/flat/short; no rule. The "
        "test days chose which saved model was reported (+61% / +118% vs buy-and-hold +33%).",
    "772435284/transformers_versus_lstms_for_electronic_trading": "Predicts the order-book middle "
        "price over the next 20-100 book updates from 10-level snapshots; our candle frame has no "
        "order-book series. Its results are only images.",
    "jwallbridge/translob": "A transformer classifier of the next 10-100 order-book events on the "
        "FI-2010 stock book data; no trading rule, and our candle frame has no order-book series.",
    "stefan-jansen/machine-learning-for-trading: crypto perps funding": "Ranks 19 perpetuals every "
        "8 hours by a trained elastic net on premium and funding features, long the top and short "
        "the bottom - cross-sectional and trained. Its own holdout: -44.8% a year, 82% drawdown.",
    "stefan-jansen/machine-learning-for-trading: 12-1 momentum and ML chapters": "The momentum "
        "study sorts 100 ETFs into buckets each month (cross-sectional); the model chapters "
        "(linear, boosting, deep learning, RL) are trained models.",
    "PacktPublishing/Machine-Learning-for-Algorithmic-Trading-Second-Edition": "Every backtest is "
        "a long 25 / short 25 basket of 500-1,000 stocks ranked by a factor or a trained model, a "
        "two-series cointegrated pair, or a DQN on AAPL - none is a single-series rule. Its one "
        "model tested on two clean unseen years (Japan) lost 6% a year.",
    "ahmedas91/ml-ohlcv-alpha-signals: cross-sectional decile long-short": "Ranks ~1,000 stocks "
        "each day by an elastic net over 105 features and holds the top tenth long, bottom tenth "
        "short - needs every coin at once. Its own result: about 1.56 basis points a day before "
        "costs (ported only as the single-coin reversal stand-in).",
    "abailey81/Crypto-Statistical-Arbitrage": "Pair trading needs two coins' prices at once, and "
        "its funding and futures-curve trades need several venues' funding and dated futures; one "
        "coin's candles cannot run either.",
    "YuxinSUN89/quant-ohlcv-feature": "A library of 540 indicator formulas for a model's inputs; "
        "no entry, exit or backtest to port.",
    "mindees/crypto-ai": "The repo is gone (GitHub answers 404 on Nov 18, 2026); nothing to read.",
    "cbailes/awesome-deep-trading": "A reading list of papers and links; no strategy of its own.",
    "bernhardbrugger/awesome-ai-trading": "A reading list of tools, data and papers; no strategy "
        "of its own.",
    "topics/walk-forward-validation": "A GitHub topic page listing other repos; no strategy of its "
        "own.",
}
