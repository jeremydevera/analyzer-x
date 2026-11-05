"""THE technical-analysis AND backtesting-frameworks SKILLS' OWN STRATEGIES (Nov 05, 2026).

The operator: *"can you use these skills technical-analysis, backtesting-trading-strategies,
backtesting-framework / use all my existing data from v2 , v3 and generate me the best strateigioes
for all coins for all time frame"*. `skill_bt.py` ran the backtesting-trading-strategies skill's eight
strategies; these are the setups the OTHER two skills write down, run through the same walk-forward
(`skill_bt.pair`: chosen on the older 70% of the candles, judged on the newest 30%):

technical-analysis (`references/patterns.md`, each with a stop, and a target at 2x the stop - the
skill's "2:1+ R:R" and "always have a defined entry, stop, target"):

* `ta_wyckoff_spring` - Pattern 1's `detect_spring`: a low under the prior N-candle low that closes
  back above it on below-average volume -> long; its mirror (Wyckoff's upthrust) -> short.
* `ta_rsi_divergence` - Pattern 3: price makes a lower swing low while RSI makes a higher one, and
  the close breaks the swing high between them -> long; the mirror -> short. RSI is read AT the two
  price swing lows (the skill finds RSI's own swing lows separately; at the price lows is the common
  reading and needs no second pivot search).
* `ta_structure_break` - Pattern 5: higher highs and higher lows, then a close under the last higher
  low -> short; lower highs and lows, then a close over the last lower high -> long.
* `ta_vwap_reversion` - Pattern 6: a close outside VWAP -/+ 2 standard deviations is faded, out at
  VWAP (its own target, so no 2x target). VWAP is rolling over N candles: the skill's session VWAP
  resets each day, which a 1d or 4h candle cannot do.
* `ta_ma_filtered_cross` - the "Moving Average Crossover" anti-pattern's own fix: "if you must use
  crossovers, add filters: ADX > 25, volume increase on cross"; out at the opposite cross.
* `ta_ma_pullback` - the same section's "better uses for MAs": only long above the trend average
  (short below), entered when a candle touches the faster average and closes back on the trend side.

backtesting-frameworks (`references/details.md` Pattern 2): `bf_momentum` - its `momentum_signal`,
long while the close is above its N-candle average, flat otherwise.

Left out, named: the Fibonacci confluence zones (the skill draws them from a hand-picked major and
minor swing - no rule picks them) and the volume-profile value area (a whole-range distribution
with no stated entry rule).

Every signal at candle i is worked out from candles 0..i only (tested by cutting the frame at many
points: the signals before the cut never change).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tradingagents.vendor.btstrat.strategies import Signal

TARGET_R = 2.0          # technical-analysis: a target at 2x the stop
SWING_K = 3             # candles each side that make a swing point (rsi divergence)
DIV_WINDOW = 50         # the skill's 50-candle window for two swing lows


@dataclass
class TaSignal(Signal):
    """The skill_bt walk's Signal, plus WHICH side an exit closes (None: either), so a mirrored
    setup's exit cannot close the other side's trade."""

    exit_dir: str | None = None


def _sma(x: pd.Series, n: int) -> np.ndarray:
    return x.rolling(n).mean().to_numpy()


def _rsi(close: pd.Series, n: int) -> np.ndarray:
    d = close.diff()
    gain = d.where(d > 0, 0.0).rolling(n).mean()
    loss = (-d.where(d < 0, 0.0)).rolling(n).mean()
    return (100 - 100 / (1 + gain / loss)).to_numpy()


def _adx(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    h, lo, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    up, dn = h.diff(), -lo.diff()
    pdm = up.where((up > dn) & (up > 0), 0.0)
    ndm = dn.where((dn > up) & (dn > 0), 0.0)
    a = 1.0 / n
    atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pdm.ewm(alpha=a, adjust=False).mean() / atr
    ndi = 100 * ndm.ewm(alpha=a, adjust=False).mean() / atr
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi)
    out = dx.ewm(alpha=a, adjust=False).mean().to_numpy(copy=True)
    out[: 2 * n] = np.nan                  # not settled yet
    return out


def _pivots(x: np.ndarray, k: int, low: bool) -> np.ndarray:
    """True at j when x[j] is the lowest (highest) of j-k..j+k - known only at candle j+k."""
    n = len(x)
    out = np.zeros(n, dtype=bool)
    for j in range(k, n - k):
        w = x[j - k: j + k + 1]
        out[j] = x[j] == (w.min() if low else w.max())
    return out


def _to_signals(n, warm, long_in, short_in, long_out=None, short_out=None) -> list:
    out = []
    for i in range(n):
        if i < warm:
            out.append(None)
            continue
        lo_x = bool(long_out[i]) if long_out is not None else False
        sh_x = bool(short_out[i]) if short_out is not None else False
        exit_dir = "long" if lo_x and not sh_x else "short" if sh_x and not lo_x else None
        s = TaSignal(exit=lo_x or sh_x, exit_dir=exit_dir)
        if long_in[i]:
            s.entry, s.direction = True, "long"
        elif short_in[i]:
            s.entry, s.direction = True, "short"
        out.append(s)
    return out


class _Base:
    name = "base"
    lookback = 1
    target_r: float | None = TARGET_R

    def signals_all(self, df: pd.DataFrame, params: dict) -> list:
        raise NotImplementedError


class WyckoffSpring(_Base):
    name = "ta_wyckoff_spring"

    def signals_all(self, df, params):
        n = int(params["lookback"])
        lo, hi, c, v = df["low"], df["high"], df["close"], df["volume"]
        prior_lo = lo.rolling(n).min().shift(1).to_numpy()
        prior_hi = hi.rolling(n).max().shift(1).to_numpy()
        quiet = (v < v.rolling(20).mean()).to_numpy()
        long_in = (lo.to_numpy() < prior_lo) & (c.to_numpy() > prior_lo) & quiet
        short_in = (hi.to_numpy() > prior_hi) & (c.to_numpy() < prior_hi) & quiet
        return _to_signals(len(df), max(n, 20) + 1, long_in, short_in)


class RsiDivergence(_Base):
    name = "ta_rsi_divergence"

    def signals_all(self, df, params):
        p, k = int(params["period"]), SWING_K
        lo, hi, c = df["low"].to_numpy(), df["high"].to_numpy(), df["close"].to_numpy()
        rsi = _rsi(df["close"], p)
        piv_lo, piv_hi = _pivots(lo, k, True), _pivots(hi, k, False)
        n = len(df)
        long_in, short_in = np.zeros(n, bool), np.zeros(n, bool)
        for i in range(p + DIV_WINDOW, n):
            lows = [j for j in range(i - DIV_WINDOW, i - k + 1) if piv_lo[j]]
            if len(lows) >= 2:
                j1, j2 = lows[-2], lows[-1]
                if lo[j2] < lo[j1] and rsi[j2] > rsi[j1]:
                    level = hi[j1: j2 + 1].max()
                    if c[i] > level and c[i - 1] <= level:
                        long_in[i] = True
            highs = [j for j in range(i - DIV_WINDOW, i - k + 1) if piv_hi[j]]
            if len(highs) >= 2:
                j1, j2 = highs[-2], highs[-1]
                if hi[j2] > hi[j1] and rsi[j2] < rsi[j1]:
                    level = lo[j1: j2 + 1].min()
                    if c[i] < level and c[i - 1] >= level:
                        short_in[i] = True
        return _to_signals(n, p + DIV_WINDOW, long_in, short_in)


class StructureBreak(_Base):
    name = "ta_structure_break"

    def signals_all(self, df, params):
        k = int(params["swing"])
        lo, hi, c = df["low"].to_numpy(), df["high"].to_numpy(), df["close"].to_numpy()
        piv_lo, piv_hi = _pivots(lo, k, True), _pivots(hi, k, False)
        n = len(df)
        long_in, short_in = np.zeros(n, bool), np.zeros(n, bool)
        hs, ls = [], []                     # confirmed swing prices, oldest first
        for i in range(n):
            j = i - k                       # the point that becomes known at candle i
            if j >= k:
                if piv_hi[j]:
                    hs.append(hi[j])
                if piv_lo[j]:
                    ls.append(lo[j])
            if i == 0 or len(hs) < 2 or len(ls) < 2:
                continue
            if hs[-1] > hs[-2] and ls[-1] > ls[-2] and c[i] < ls[-1] <= c[i - 1]:
                short_in[i] = True
            elif hs[-1] < hs[-2] and ls[-1] < ls[-2] and c[i] > hs[-1] >= c[i - 1]:
                long_in[i] = True
        return _to_signals(n, 2 * k + 1, long_in, short_in)


class VwapReversion(_Base):
    name = "ta_vwap_reversion"
    target_r = None                         # its target is VWAP itself

    def signals_all(self, df, params):
        n, k = int(params["period"]), float(params["std"])
        tp = (df["high"] + df["low"] + df["close"]) / 3
        v = df["volume"].astype(float)
        sv = v.rolling(n).sum()
        vwap = (tp * v).rolling(n).sum() / sv
        var = (tp * tp * v).rolling(n).sum() / sv - vwap * vwap
        sd = np.sqrt(var.clip(lower=0))
        c = df["close"]
        lower, upper = (vwap - k * sd).to_numpy(), (vwap + k * sd).to_numpy()
        cv, pc = c.to_numpy(), c.shift(1).to_numpy()
        vw = vwap.to_numpy()
        with np.errstate(invalid="ignore"):
            long_in = (cv < lower) & (pc >= np.roll(lower, 1))
            short_in = (cv > upper) & (pc <= np.roll(upper, 1))
            long_out, short_out = cv >= vw, cv <= vw
        return _to_signals(len(df), n + 1, long_in, short_in, long_out, short_out)


class MaFilteredCross(_Base):
    name = "ta_ma_filtered_cross"

    def signals_all(self, df, params):
        f, s = int(params["fast_period"]), int(params["slow_period"])
        c, v = df["close"], df["volume"]
        fa, sl = _sma(c, f), _sma(c, s)
        pf, ps = np.roll(fa, 1), np.roll(sl, 1)
        adx = _adx(df)
        busy = (v > v.rolling(20).mean()).to_numpy()
        with np.errstate(invalid="ignore"):
            up = (pf <= ps) & (fa > sl)
            down = (pf >= ps) & (fa < sl)
            strong = adx > 25
        return _to_signals(len(df), max(s, 28) + 1, up & strong & busy, down & strong & busy,
                           long_out=down, short_out=up)


class MaPullback(_Base):
    name = "ta_ma_pullback"

    def signals_all(self, df, params):
        f, t = int(params["fast_period"]), int(params["trend_period"])
        c, lo, hi = df["close"].to_numpy(), df["low"].to_numpy(), df["high"].to_numpy()
        fa, tr = _sma(df["close"], f), _sma(df["close"], t)
        with np.errstate(invalid="ignore"):
            long_in = (c > tr) & (lo <= fa) & (c > fa)
            short_in = (c < tr) & (hi >= fa) & (c < fa)
        return _to_signals(len(df), max(f, t) + 1, long_in, short_in)


class BfMomentum(_Base):
    """backtesting-frameworks Pattern 2 `momentum_signal`: long while close > SMA(lookback)."""

    name = "bf_momentum"
    target_r = None                         # out when the close falls back under the average

    def signals_all(self, df, params):
        n = int(params["lookback"])
        c = df["close"].to_numpy()
        sma = _sma(df["close"], n)
        with np.errstate(invalid="ignore"):
            on = c > sma
        prev = np.roll(on, 1)
        prev[0] = False
        return _to_signals(len(df), n + 1, on & ~prev, np.zeros(len(df), bool), long_out=~on & prev)


STRATEGIES = {s.name: s for s in (WyckoffSpring(), RsiDivergence(), StructureBreak(), VwapReversion(),
                                  MaFilteredCross(), MaPullback(), BfMomentum())}
SKILL_OF = {name: ("backtesting-frameworks" if name.startswith("bf_") else "technical-analysis")
            for name in STRATEGIES}

# three settings each: the skill's own numbers first where it gives them, then a faster and a slower one
GRID = {
    "ta_wyckoff_spring": [{"lookback": 50}, {"lookback": 20}, {"lookback": 100}],
    "ta_rsi_divergence": [{"period": 14}, {"period": 7}, {"period": 21}],
    "ta_structure_break": [{"swing": 20}, {"swing": 5}, {"swing": 10}],
    "ta_vwap_reversion": [{"period": 50, "std": 2.0}, {"period": 20, "std": 2.0}, {"period": 100, "std": 2.0}],
    "ta_ma_filtered_cross": [{"fast_period": 50, "slow_period": 200}, {"fast_period": 10, "slow_period": 30},
                             {"fast_period": 20, "slow_period": 50}],
    "ta_ma_pullback": [{"fast_period": 20, "trend_period": 200}, {"fast_period": 10, "trend_period": 100},
                       {"fast_period": 50, "trend_period": 200}],
    "bf_momentum": [{"lookback": 20}, {"lookback": 50}, {"lookback": 100}],
}
TARGETS = {name: s.target_r for name, s in STRATEGIES.items()}
