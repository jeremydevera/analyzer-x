"""BATCH classic_b: the plain rule strategies of seven reviewed repos (Nov 18, 2026).

NehrenD/algo_trading_and_quant_strategies, sjev/twp, hudson-and-thames/backtest_tutorial,
tmr-crypto/wf_optim_crypto_analysis (with its code repo tmr-crypto/wf_optim_crypto), edtechre/pybroker,
agiprolabs/claude-trading-skills and AI4Finance-Foundation/FinRL-Trading - each rule as its repo's own
code writes it (read with the gh CLI, never run), on one coin's candles. Notes on every repo are in
`knowledge/github-repos/OWNER__REPO.md`.

Two shapes of rule, kept apart on purpose:

* A rule that names a POSITION for every candle (always long or short, or long/short/flat - Nehren,
  twp's cross, Hudson's cross, tmr-crypto's EMA pair, FinRL's monthly signal) enters on the candle the
  position CHANGES to long or short and exits the other side the same candle (`_from_state`). After the
  engine's stop closes a trade, it waits for the next change rather than buying back at once.
* A rule written as "if flat and <condition>: buy" (pybroker, agiprolabs) asks for an entry on every
  candle its condition holds; the engine opens one only when flat, as the repo's own `if not position`.

Day windows of daily-bar repos stay CANDLES on every timeframe (a 50-day average is a 50-candle
average on 15m too); tmr-crypto's re-pick windows are real days, because its own windows are days of
60-minute bars. Every signal at candle i reads candles 0..i only (tests cut the frame and compare).
Sizes, leverage and the repos' own fee models are not copied: the engine trades $5 x 20x and charges
Gate's real costs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.skill_ta import _adx, _sma, _to_signals

DAY_S = 86400


# ---------------------------------------------------------------- helpers

def _from_state(state: np.ndarray, warm: int) -> list:
    """A position per candle (+1 long, -1 short, 0 flat) -> signals: enter on the candle it changes
    to a side (and on the first live candle), close a side on every candle that is not that side."""
    n = len(state)
    st = np.asarray(state, dtype=float)
    prev = np.r_[np.nan, st[:-1]]
    first = np.zeros(n, dtype=bool)
    if warm < n:
        first[warm] = True
    long_in = (st == 1) & ((prev != 1) | first)
    short_in = (st == -1) & ((prev != -1) | first)
    return _to_signals(n, warm, long_in, short_in, long_out=st != 1, short_out=st != -1)


def _ema_seeded(x: pd.Series, n: int, alpha: float | None = None) -> np.ndarray:
    """An EMA seeded with the simple average of its first n values (TTR's EMA in R, backtrader's EMA
    and SMMA): NaN before candle n-1, then the usual recursion. Causal and the same on any prefix."""
    v = x.to_numpy(dtype=float).copy()
    out = np.full(len(v), np.nan)
    if len(v) < n:
        return out
    seed = pd.Series(v)
    seed.iloc[: n - 1] = np.nan
    seed.iloc[n - 1] = v[:n].mean()
    a = alpha if alpha is not None else 2.0 / (n + 1)
    return seed.ewm(alpha=a, adjust=False).mean().to_numpy()


def _bar_seconds(df) -> float:
    """The candle length: the smallest gap between two candles (a missing candle only widens gaps)."""
    if len(df) < 2:
        return 0.0
    ms = df.index.as_unit("ms").asi8
    d = np.diff(ms)
    d = d[d > 0]
    return float(d.min()) / 1000.0 if len(d) else 0.0


class _Base:
    name = "base"

    def signals_all(self, df: pd.DataFrame, params: dict) -> list:
        raise NotImplementedError


# ---------------------------------------------------------------- NehrenD (chapter 5 exercises)

class NehrenMa(_Base):
    """`mav_strategy`: position = sign(price - its m-day average)."""
    name = "gh_nehren_ma"

    def signals_all(self, df, params):
        m = int(params["m"])
        c = df["close"]
        with np.errstate(invalid="ignore"):
            st = np.sign((c - c.rolling(m).mean()).to_numpy())
        return _from_state(np.nan_to_num(st), m - 1)


class NehrenBollinger(_Base):
    """`bollinger_strategy`: long above mean + 2 sd, short below mean - 2 sd, flat inside."""
    name = "gh_nehren_bollinger"

    def signals_all(self, df, params):
        m, k = int(params["m"]), float(params["k"])
        c = df["close"]
        mav, sd = c.rolling(m).mean(), c.rolling(m).std()
        cv = c.to_numpy()
        with np.errstate(invalid="ignore"):
            st = np.where(cv > (mav + k * sd).to_numpy(), 1, np.where(cv < (mav - k * sd).to_numpy(), -1, 0))
        return _from_state(st, m - 1)


class NehrenBreakout(_Base):
    """`resistance_support_strategy`: long above the previous m days' highest close, short below the
    lowest (its `.shift()` keeps today out of its own window), flat in between."""
    name = "gh_nehren_breakout"

    def signals_all(self, df, params):
        m = int(params["m"])
        c = df["close"]
        hi, lo = c.rolling(m).max().shift(1).to_numpy(), c.rolling(m).min().shift(1).to_numpy()
        cv = c.to_numpy()
        with np.errstate(invalid="ignore"):
            st = np.where(cv > hi, 1, np.where(cv < lo, -1, 0))
        return _from_state(st, m)


class NehrenTwoMa(_Base):
    """`momentum`: position = sign(m-day average - n-day average), m < n."""
    name = "gh_nehren_two_ma"

    def signals_all(self, df, params):
        m, n = int(params["m"]), int(params["n"])
        c = df["close"]
        with np.errstate(invalid="ignore"):
            st = np.sign(_sma(c, m) - _sma(c, n))
        return _from_state(np.nan_to_num(st), max(m, n) - 1)


class NehrenRsi(_Base):
    """`rsi_strategy`: U = average of the POSITIVE returns among the last m, D = average size of the
    negative ones, RSI = 100 U / (U + D); long under 30, short over 70, flat between."""
    name = "gh_nehren_rsi"

    def signals_all(self, df, params):
        m = int(params["m"])
        r = df["close"].pct_change()
        pos, neg = r.where(r > 0), (-r).where(r < 0)
        u = pos.rolling(m, min_periods=1).sum() / pos.notna().astype(float).rolling(m, min_periods=1).sum()
        d = neg.rolling(m, min_periods=1).sum() / neg.notna().astype(float).rolling(m, min_periods=1).sum()
        # the window is the m returns ending at the candle (its first return is candle 1's)
        with np.errstate(invalid="ignore", divide="ignore"):
            rsi = (100 * u / (u + d)).to_numpy()
            st = np.where(rsi < 30, 1, np.where(rsi > 70, -1, 0))
        return _from_state(st, m)


# ---------------------------------------------------------------- sjev/twp

class TwpMaCross(_Base):
    """twp_302: long while the fast simple average is above the slow one, short otherwise."""
    name = "gh_twp_ma_cross"

    def signals_all(self, df, params):
        f, s = int(params["fast"]), int(params["slow"])
        c = df["close"]
        with np.errstate(invalid="ignore"):
            st = np.where(_sma(c, f) > _sma(c, s), 1, -1)
        return _from_state(st, max(f, s) - 1)


class TwpXlpGap(_Base):
    """twp_304 (Quantified Strategies' XLP rule): yesterday's close-to-close change under cc % AND today
    opened more than co % under yesterday's close -> long for one candle. The repo buys AT the open and
    sells at the same close; the engine fills at a close, so it buys the gap candle's close and sells
    the next candle's close."""
    name = "gh_twp_xlp_gap"

    def signals_all(self, df, params):
        cc_t, co_t = float(params["cc"]), float(params["co"])
        c, o = df["close"].to_numpy(dtype=float), df["open"].to_numpy(dtype=float)
        n = len(c)
        pc = np.r_[np.nan, c[:-1]]
        cc = 100 * (c / pc - 1)                      # close-to-close of each candle
        co = 100 * (o / pc - 1)                      # previous close to this open
        with np.errstate(invalid="ignore"):
            go = (np.r_[np.nan, cc[:-1]] < cc_t) & (co < co_t)
        go[:2] = False
        out_ = np.r_[False, go[:-1]]                 # sell one candle after the buy
        return _to_signals(n, 2, go, np.zeros(n, bool), long_out=out_)


# ---------------------------------------------------------------- hudson-and-thames

class HudsonMaCross(_Base):
    """Vectorized_Backtest_Tutorial: +1 when the 50-day average is above the 252-day, -1 below."""
    name = "gh_hudson_ma_cross"

    def signals_all(self, df, params):
        s, lg = int(params["short"]), int(params["long"])
        c = df["close"]
        with np.errstate(invalid="ignore"):
            st = np.sign(_sma(c, s) - _sma(c, lg))
        return _from_state(np.nan_to_num(st), max(s, lg) - 1)


# ---------------------------------------------------------------- tmr-crypto (walk-forward EMA pair)

TMR_PERIODS = (5, 7, 10, 15, 20, 30, 40, 50, 100, 150, 200)   # strategy_param.yaml ma_periods_array
TMR_CUTOFF = 35                                               # ma_cutoff_int: fast <= 35 < slow
TMR_FEE = 0.001                                               # fee_int, used only to CHOOSE the pair
TMR_FAST = tuple(p for p in TMR_PERIODS if p <= TMR_CUTOFF)
TMR_SLOW = tuple(p for p in TMR_PERIODS if p > TMR_CUTOFF)
TMR_PAIRS = tuple((f, s) for s in TMR_SLOW for f in TMR_FAST)  # R's column order: slow outer, fast inner


def tmr_choices(df, train_days: int, test_days: int):
    """The walk-forward of WfHelper.r: blocks of the trimmed series (from the candle where the 200-EMA
    exists) - tune on `train_days` x candles-a-day rows, trade the next `test_days` x candles-a-day,
    step by the trading length. Each block's pair is the best Sharpe of net pnl (position x log return
    - 0.1% per unit of position change) over its tuning rows, ties to the first in R's order.
    Returns (ema dict, start row s0, tune length T, trade length S, chosen pair index per block)."""
    bar = _bar_seconds(df)
    bpd = max(1, int(round(DAY_S / bar))) if bar > 0 else 1
    T, S = int(train_days) * bpd, int(test_days) * bpd
    c = df["close"]
    ema = {p: _ema_seeded(c, p) for p in TMR_PERIODS}
    n = len(c)
    s0 = max(TMR_PERIODS) - 1                        # precalculate(): rows from max(period) on
    if n <= s0 + T:
        return ema, s0, T, S, np.zeros(0, dtype=int)
    lr = np.r_[0.0, np.diff(np.log(c.to_numpy(dtype=float)))]
    rows = np.arange(s0, n)
    pnl = np.zeros((len(rows), len(TMR_PAIRS)))
    for j, (f, s) in enumerate(TMR_PAIRS):
        pos = np.where(ema[f][rows - 1] > ema[s][rows - 1], 1.0, -1.0)
        pos[0] = np.nan                              # lag.xts of the first trimmed row
        trans = np.abs(np.diff(pos, prepend=np.nan))
        p = pos * lr[rows] - np.nan_to_num(trans) * TMR_FEE
        pnl[:, j] = np.nan_to_num(p)
    c1 = np.vstack([np.zeros(len(TMR_PAIRS)), np.cumsum(pnl, axis=0)])
    c2 = np.vstack([np.zeros(len(TMR_PAIRS)), np.cumsum(pnl * pnl, axis=0)])
    nrow = len(rows)
    starts = np.arange(0, nrow - T + 1, S)           # block k tunes rows [kS, kS + T - 1]
    a, b = starts, starts + T
    s1, s2 = c1[b] - c1[a], c2[b] - c2[a]
    mean = s1 / T
    with np.errstate(invalid="ignore", divide="ignore"):
        var = (s2 - T * mean * mean) / (T - 1) if T > 1 else np.full_like(s2, np.nan)
        sharpe = mean / np.sqrt(np.clip(var, 0, None))
    sharpe = np.where(np.isnan(sharpe), -np.inf, sharpe)
    return ema, s0, T, S, np.argmax(sharpe, axis=1)


class TmrEmaWf(_Base):
    """strategy.r + WfHelper.r: always long (fast EMA above slow at the previous close) or short, the
    pair re-chosen every trading block from the tuning block just before it."""
    name = "gh_tmr_ema_wf"

    def signals_all(self, df, params):
        n = len(df)
        ema, s0, T, S, pick = tmr_choices(df, params["train_days"], params["test_days"])
        warm = s0 + T - 1                            # decides the first traded row s0 + T
        st = np.zeros(n)
        if len(pick) and warm < n:
            i = np.arange(warm, n)
            k = np.minimum((i + 1 - s0 - T) // S, len(pick) - 1)   # block of the row each candle sets
            ok = (i + 1 - s0 - T) // S < len(pick)
            k = k[ok]
            i = i[ok]
            fast = np.array([TMR_PAIRS[p][0] for p in pick])[k]
            slow = np.array([TMR_PAIRS[p][1] for p in pick])[k]
            ef = np.vstack([ema[p] for p in TMR_PERIODS])
            row = {p: r for r, p in enumerate(TMR_PERIODS)}
            fv = ef[[row[f] for f in fast], i]
            sv = ef[[row[s] for s in slow], i]
            st[i] = np.where(fv > sv, 1, -1)
        return _from_state(st, min(warm, n))


# ---------------------------------------------------------------- edtechre/pybroker

def _hold_sim(cond: np.ndarray, hold: int, warm: int):
    """pybroker's `if not position and <cond>: buy; hold_bars = N`: one position at a time, out N
    candles after the entry (and free to buy again on that candle)."""
    n = len(cond)
    ins, outs = np.zeros(n, bool), np.zeros(n, bool)
    exit_at = -1
    for i in range(warm, n):
        if exit_at == i:
            outs[i], exit_at = True, -1
        if exit_at < 0 and cond[i]:
            ins[i], exit_at = True, i + hold
    return ins, outs


class PybDip(_Base):
    """Notebook 2 `buy_low`: close under the previous candle's low -> buy, sell 3 candles later."""
    name = "gh_pyb_dip"

    def signals_all(self, df, params):
        c, lo = df["close"].to_numpy(), df["low"].to_numpy()
        n = len(c)
        cond = np.r_[False, c[1:] < lo[:-1]]
        ins, outs = _hold_sim(cond, int(params["hold"]), 1)
        return _to_signals(n, 1, ins, np.zeros(n, bool), long_out=outs)


class PybPop(_Base):
    """Notebook 2 `short_high`: close over the previous candle's high -> short, cover 2 candles later."""
    name = "gh_pyb_pop"

    def signals_all(self, df, params):
        c, hi = df["close"].to_numpy(), df["high"].to_numpy()
        n = len(c)
        cond = np.r_[False, c[1:] > hi[:-1]]
        ins, outs = _hold_sim(cond, int(params["hold"]), 1)
        return _to_signals(n, 1, np.zeros(n, bool), ins, short_out=outs)


class PybSmaStop(_Base):
    """Notebook 12 `sma_cross_stop`: flat and close above its average -> buy; close under it -> sell;
    the repo's own stop (`stop_pct`) is the engine's stop."""
    name = "gh_pyb_sma_stop"

    def signals_all(self, df, params):
        p = int(params["period"])
        c = df["close"].to_numpy()
        sma = _sma(df["close"], p)
        with np.errstate(invalid="ignore"):
            up, dn = c > sma, c < sma
        return _to_signals(len(c), p - 1, up, np.zeros(len(c), bool), long_out=dn)


class PybBreakout(_Base):
    """Notebook 18 `breakout`: flat and close above the highest high of the previous N candles -> buy;
    close under the lowest low of the previous N -> sell."""
    name = "gh_pyb_breakout20"

    def signals_all(self, df, params):
        k = int(params["lookback"])
        hi = df["high"].rolling(k).max().shift(1).to_numpy()
        lo = df["low"].rolling(k).min().shift(1).to_numpy()
        c = df["close"].to_numpy()
        with np.errstate(invalid="ignore"):
            up, dn = c > hi, c < lo
        return _to_signals(len(c), k, up, np.zeros(len(c), bool), long_out=dn)


# ---------------------------------------------------------------- agiprolabs/claude-trading-skills

class AgiEmaCross(_Base):
    """backtrader patterns 1 `EMABracket`: flat and the fast EMA crosses above the slow -> buy, out only
    by the bracket (stop, and a target at `rr_ratio` = 2 x the stop)."""
    name = "gh_agi_ema_cross"

    def signals_all(self, df, params):
        f, s = int(params["fast"]), int(params["slow"])
        fa, sl = _ema_seeded(df["close"], f), _ema_seeded(df["close"], s)
        pf, ps = np.r_[np.nan, fa[:-1]], np.r_[np.nan, sl[:-1]]
        with np.errstate(invalid="ignore"):
            up = (fa > sl) & (pf <= ps)
        n = len(fa)
        return _to_signals(n, max(f, s), up, np.zeros(n, bool))


class AgiSolEma(_Base):
    """strategy-framework "SOL-EMA-Cross v1.0" `entry_signal`: EMA 12 above EMA 26, EMA 26 up over 3
    candles, volume over 1.5x its 20-candle average, ADX over 20 -> buy; out when EMA 12 falls back
    under EMA 26 (or the stop / 3R target)."""
    name = "gh_agi_sol_ema"

    def signals_all(self, df, params):
        f, s = int(params["fast"]), int(params["slow"])
        c, v = df["close"], df["volume"].astype(float)
        e1 = c.ewm(span=f, adjust=False).mean().to_numpy()
        e2s = c.ewm(span=s, adjust=False).mean()
        e2 = e2s.to_numpy()
        rising = (e2s.diff(3) > 0).to_numpy()
        busy = (v > v.rolling(20).mean() * 1.5).to_numpy()
        adx = _adx(df)
        with np.errstate(invalid="ignore"):
            go = (e1 > e2) & rising & busy & (adx > 20)
            back = e1 < e2
        n = len(c)
        return _to_signals(n, max(s, 28) + 1, go, np.zeros(n, bool), long_out=back)


def _rsi_wilder(close: pd.Series, n: int) -> np.ndarray:
    """backtrader's RSI: Wilder's smoothing of the up and down moves, seeded with their simple average."""
    d = close.diff()
    up = _ema_seeded(d.clip(lower=0).iloc[1:], n, alpha=1.0 / n)
    dn = _ema_seeded((-d).clip(lower=0).iloc[1:], n, alpha=1.0 / n)
    with np.errstate(invalid="ignore", divide="ignore"):
        rsi = 100 - 100 / (1 + up / dn)
    return np.r_[np.nan, rsi]


class AgiRsi(_Base):
    """backtrader patterns 2 `RSIMeanReversion`: flat and RSI(14) under 30 -> buy; RSI over 70 -> sell;
    its 5% stop is the engine's stop."""
    name = "gh_agi_rsi"

    def signals_all(self, df, params):
        p = int(params["period"])
        rsi = _rsi_wilder(df["close"], p)
        with np.errstate(invalid="ignore"):
            lo, hi = rsi < float(params["oversold"]), rsi > float(params["overbought"])
        n = len(rsi)
        return _to_signals(n, p + 1, lo, np.zeros(n, bool), long_out=hi)


class AgiZscore(_Base):
    """mean-reversion `generate_signals`: z = (close - mean) / sd over the lookback; flat and z < -2 ->
    long, z > 2 -> short; a long closes when z > 0 or z < -3, a short when z < 0 or z > 3."""
    name = "gh_agi_zscore"

    def signals_all(self, df, params):
        k = int(params["lookback"])
        ez, xz, sz = 2.0, 0.0, 3.0
        c = df["close"]
        z = ((c - c.rolling(k).mean()) / c.rolling(k).std()).to_numpy()
        n = len(z)
        state = np.zeros(n)
        cur = 0
        for i in range(n):
            zi = z[i]
            if not np.isnan(zi):
                if cur == 0:
                    cur = 1 if zi < -ez else -1 if zi > ez else 0
                elif cur == 1:
                    if zi > -xz or zi < -sz:
                        cur = 0
                elif cur == -1:
                    if zi < xz or zi > sz:
                        cur = 0
            state[i] = cur
        return _from_state(state, k - 1)


# ---------------------------------------------------------------- AI4Finance-Foundation/FinRL-Trading

class FinrlTsmom(_Base):
    """tsmomsignal.py (Moskowitz 2012): at each month's end, ret = close of the month just ended /
    close of the month-end 11 months before it - 1 (`shift(1) / shift(12)` of month-end closes); long
    the coming month above +band, short below -band, flat between. 1d candles only."""
    name = "gh_finrl_tsmom"

    def signals_all(self, df, params):
        n = len(df)
        band = float(params["band"])
        look = int(params["months"])
        if n < 2 or _bar_seconds(df) < DAY_S:
            return [None] * n
        idx = df.index
        mcode = np.asarray(idx.year * 12 + idx.month)
        c = df["close"].to_numpy(dtype=float)
        month_end = np.asarray((idx + pd.Timedelta(days=1)).month != idx.month)   # this day ends its month
        last_close: dict[int, float] = {}            # month -> its last close seen so far
        st = np.zeros(n)
        cur, warm = 0, n
        for i in range(n):
            last_close[int(mcode[i])] = c[i]
            if month_end[i]:
                old = last_close.get(int(mcode[i]) - (look - 1))
                if old is not None and old > 0:
                    ret = c[i] / old - 1
                    cur = 1 if ret > band else -1 if ret < -band else 0
                    warm = min(warm, i)
            st[i] = cur
        # a monthly rebalance: re-enter the month's side at every month end where the engine is flat
        sig = _from_state(st, warm)
        for i in range(warm, n):
            if month_end[i] and st[i] != 0 and sig[i] is not None and not sig[i].entry:
                sig[i].entry, sig[i].direction = True, "long" if st[i] == 1 else "short"
        return sig


# ---------------------------------------------------------------- the batch's tables

STRATEGIES = {s.name: s for s in (
    NehrenMa(), NehrenBollinger(), NehrenBreakout(), NehrenTwoMa(), NehrenRsi(),
    TwpMaCross(), TwpXlpGap(), HudsonMaCross(), TmrEmaWf(),
    PybDip(), PybPop(), PybSmaStop(), PybBreakout(),
    AgiEmaCross(), AgiSolEma(), AgiRsi(), AgiZscore(), FinrlTsmom())}

GRID = {
    "gh_nehren_ma": [{"m": 90}],                          # the notebook's best m
    "gh_nehren_bollinger": [{"m": 80, "k": 2.0}],
    "gh_nehren_breakout": [{"m": 230}],
    "gh_nehren_two_ma": [{"m": 60, "n": 120}],
    "gh_nehren_rsi": [{"m": 60}, {"m": 20}],              # its worked cell's 60; 20 = the low end of its range
    "gh_twp_ma_cross": [{"fast": 10, "slow": 50}, {"fast": 18, "slow": 25}],
    "gh_twp_xlp_gap": [{"cc": -0.25, "co": -0.1}, {"cc": 0.03, "co": 0.09}],
    "gh_hudson_ma_cross": [{"short": 50, "long": 252}],
    "gh_tmr_ema_wf": [{"train_days": 7, "test_days": 28}, {"train_days": 14, "test_days": 10}],
    "gh_pyb_dip": [{"hold": 3}],
    "gh_pyb_pop": [{"hold": 2}],
    "gh_pyb_sma_stop": [{"period": 30}, {"period": 10}],
    "gh_pyb_breakout20": [{"lookback": 20}],
    "gh_agi_ema_cross": [{"fast": 10, "slow": 30}],
    "gh_agi_sol_ema": [{"fast": 12, "slow": 26}],
    "gh_agi_rsi": [{"period": 14, "oversold": 30, "overbought": 70}],
    "gh_agi_zscore": [{"lookback": 40}],
    "gh_finrl_tsmom": [{"months": 12, "band": 0.10}, {"months": 12, "band": 0.0}],
}

STOPS = {
    "gh_pyb_sma_stop": (0.06, 0.02),                      # notebook 12: default 6%, its search's best 2%
    "gh_agi_rsi": (0.05,),                                # stop_pct 0.05
}

TARGETS = {name: None for name in STRATEGIES}
TARGETS["gh_agi_ema_cross"] = 2.0                         # rr_ratio 2.0
TARGETS["gh_agi_sol_ema"] = 3.0                           # "target 3 x the risk"

REPO_OF = {
    **{n: "NehrenD/algo_trading_and_quant_strategies" for n in STRATEGIES if n.startswith("gh_nehren_")},
    **{n: "sjev/twp" for n in STRATEGIES if n.startswith("gh_twp_")},
    "gh_hudson_ma_cross": "hudson-and-thames/backtest_tutorial",
    "gh_tmr_ema_wf": "tmr-crypto/wf_optim_crypto_analysis",
    **{n: "edtechre/pybroker" for n in STRATEGIES if n.startswith("gh_pyb_")},
    **{n: "agiprolabs/claude-trading-skills" for n in STRATEGIES if n.startswith("gh_agi_")},
    "gh_finrl_tsmom": "AI4Finance-Foundation/FinRL-Trading",
}

_NB5 = "exercises/chapter5_solutions.ipynb"
RULE_OF = {
    "gh_nehren_ma": f"Long while the close is above its m-candle average, short while below (flipping on the cross); m-day windows become m candles on every timeframe; `mav_strategy` in {_NB5}.",
    "gh_nehren_bollinger": f"Long while the close is above the m-candle average + 2 standard deviations, short below the average - 2 (the repo's code adds 2 to both bands, a typo; the intended minus is used), flat inside; `bollinger_strategy` in {_NB5}.",
    "gh_nehren_breakout": f"Long while the close is above the highest close of the previous m candles, short below the lowest, flat in between; `resistance_support_strategy` in {_NB5}.",
    "gh_nehren_two_ma": f"Long while the 60-candle average is above the 120-candle average, short while below; `momentum` in {_NB5}.",
    "gh_nehren_rsi": f"RSI from the average up-return and average down-return of the last m candles: long under 30, short over 70, flat between (m = 60, its worked example, or 20); `rsi_strategy` in {_NB5}.",
    "gh_twp_ma_cross": "Long while the fast simple average (10 candles; the tuned 18) is above the slow one (50; tuned 25), short otherwise, always in; twp_302_moving_averages_strat.ipynb (day windows kept as candles, its 10-share size not copied).",
    "gh_twp_xlp_gap": "Yesterday's close-to-close change under -0.25% and today's open more than 0.1% under yesterday's close: long one candle - bought at the gap candle's close and sold at the next close, because the engine cannot buy at an open as the repo does; twp_304_xlp_strategy.ipynb (second setting: its hand-typed 0.03/0.09).",
    "gh_hudson_ma_cross": "Long while the 50-candle average is above the 252-candle average, short while below, always in; Vectorized_Backtest_Tutorial.ipynb (day windows kept as candles; its volatility-targeted size up to 2x cannot be copied, the engine trades a fixed $5 x 20x).",
    "gh_tmr_ema_wf": "Always long while the fast EMA is above the slow EMA at the previous close, else short, the pair (fast 5-30 x slow 40-200, 30 pairs) re-chosen every 28 (or 10) days as the best net Sharpe of the 7 (or 14) days before; tmr-crypto/wf_optim_crypto master/rcode/logic/strategy.r and WfHelper.r (windows are real days, its whole-account 1x size not copied).",
    "gh_pyb_dip": "Close under the previous candle's low: buy at the close, sell 3 candles later; notebook 2 `buy_low` (its 25%-of-account size and next-bar fill not copied).",
    "gh_pyb_pop": "Close over the previous candle's high: short at the close, cover 2 candles later; notebook 2 `short_high` (its 100-share size not copied).",
    "gh_pyb_sma_stop": "Flat and close above its 30-candle (or 10) average: buy; close under the average: sell; stop 6% (or 2%); notebook 12 `sma_cross_stop` (100-share size not copied).",
    "gh_pyb_breakout20": "Flat and close above the highest high of the previous 20 candles: buy; close under the lowest low of the previous 20: sell; notebook 18 `breakout` (its top-3-by-dollar-volume universe and 1/3 size not copied).",
    "gh_agi_ema_cross": "Flat and EMA 10 crosses above EMA 30: buy, out only by the stop or a target at 2x the stop (the repo's stop is 2x ATR, here the engine's fixed stops); skills/backtrader/references/strategy_patterns.md `EMABracket`.",
    "gh_agi_sol_ema": "EMA 12 above EMA 26, EMA 26 up over 3 candles, volume over 1.5x its 20-candle average and ADX over 20: buy; out when EMA 12 falls back under EMA 26, the stop, or a 3x-stop target (its ATR trail, 20-candle time stop and 4h check not copied); skills/strategy-framework/SKILL.md.",
    "gh_agi_rsi": "Flat and RSI(14) under 30: buy; RSI over 70: sell; 5% stop; skills/backtrader/references/strategy_patterns.md `RSIMeanReversion`.",
    "gh_agi_zscore": "z = (close - its N-candle average) / N-candle sd: under -2 long, over +2 short, out when z crosses back over 0 or runs past 3; skills/mean-reversion/scripts/mean_reversion_test.py `generate_signals` (N fixed at 40 = 2x its default 20-candle half-life; the half-life fit is not run on the whole frame, which would read later candles).",
    "gh_finrl_tsmom": "At each month's last daily candle: month-end close / the month-end close 11 months earlier - 1 (12 monthly rows); long for the coming month above +10% (or 0), short below -10% (or 0), flat between, re-entered each month end; src/strategies/tsmomsignal.py; 1d candles only.",
}

NOT_PORTED = {
    "NehrenD/algo_trading_and_quant_strategies: pair trading": "Distance, cointegration and APT pairs need two instruments at once, and the notebook stops before any pair rule exists.",
    "sjev/twp: walk-forward re-tuned MA cross": "Re-tunes 19 x 20 average pairs on 2 years of daily candles then trades 1 year - more daily history than most Gate coins have; its fixed settings are ported as gh_twp_ma_cross.",
    "sjev/twp: smartVXX and the VXX nearest-neighbours model": "Need the VIX and VIX3M indexes beside the traded fund (a second and third series); the neighbours model is ML, another batch's.",
    "sjev/twp: energy spread, permanent portfolio, leveraged-ETF pairs": "Each holds two to four instruments at once.",
    "hudson-and-thames/backtest_tutorial: volatility-targeted size": "Size = 15% / 22-day volatility capped at 2x cannot be copied: the engine stakes a fixed $5 x 20x; the signal itself is gh_hudson_ma_cross.",
    "tmr-crypto/wf_optim_crypto_analysis: robust-Sharpe window choice": "The 9 x 9 grid of tuning/trading windows was smoothed and chosen on BTC 2018-2019; the two windows it kept (7/28 and 14/10 days) are used directly.",
    "edtechre/pybroker: ML examples": "Linear regression, random forest, GARCH filter and the multi-symbol model are machine learning - another batch's.",
    "edtechre/pybroker: ranking, rotation, rebalance and symbol selection": "Volume rank, 5-day ROC rank, 20-day ROC rotation, monthly rebalance and the dollar-volume universe each choose among many stocks at once.",
    "edtechre/pybroker: stops notebook": "Buys whenever flat with no signal, to demonstrate stop and trailing-stop orders; there is no rule to port.",
    "agiprolabs/claude-trading-skills: signal classifier": "The XGBoost / gradient-boosting classifier is ML - another batch's.",
    "agiprolabs/claude-trading-skills: pairs, copy trading, prediction markets, on-chain score": "Need a second instrument, other wallets' trades, prediction-market brackets or on-chain data.",
    "agiprolabs/claude-trading-skills: regime-adaptive switch": "Left out to keep the batch small; its two halves (the EMA 10/30 cross and RSI mean reversion) are ported on their own, and its thresholds were tuned on made-up data with planted regimes.",
    "AI4Finance-Foundation/FinRL-Trading: rotation, ML stock picking, DRL allocator": "The weekly rotation ranks 28 stocks, the ML picker needs quarterly company fundamentals, and the DRL allocator weights many stocks at once.",
}
