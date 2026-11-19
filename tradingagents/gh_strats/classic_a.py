"""BATCH classic_a - the textbook rules of three reviewed repos, ported to the skill engine (Nov 18, 2026).

* je-suis-tm/quant-trading - the single-series scripts: MACD oscillator, Awesome oscillator,
  Heikin-Ashi, Parabolic SAR, RSI, Bollinger W bottom, Dual Thrust, London Breakout, Shooting Star.
* Log-zz-ikIO/crypto-signal - the RSI bot (`app/behaviours/rsi_bot.py`).
* QuantConnect/Research - the EMA cross notebook (`Analysis/04 EMA Cross Strategy Based on VXX.ipynb`).

Each rule is copied from the repo's own code (read Nov 18, 2026; the notes are
`knowledge/github-repos/`), with three kinds of change, each named in RULE_OF:

* LOOK-AHEAD REMOVED. Shooting Star read the NEXT candle (`shift(-1)`) and the whole history's average
  body; here the signal comes one candle later, at the close of the candle that confirms it, and the
  average body is the one up to that candle. Dual Thrust's range included the day being traded; here it
  is the 5 sessions BEFORE it.
* ONE POSITION, THE ENGINE'S SIZE. The engine holds one position at a time at $5 x 20x and puts a stop
  on every trade, so the repos' share counts, stacking (Heikin-Ashi's 3 buys) and leverage are not
  ported. A repo whose position state blocked new entries because it never had a stop (Bollinger) is
  gated by the engine instead: an entry fires only when the engine is flat.
* PRICE UNITS -> FRACTIONS. Bollinger's 0.0001 and London's 0.01 / 0.005 were GBP/USD price units
  (GBP/USD near 1.30); here they are fractions of the coin's price.

A "long while X" rule enters on the candle X becomes true and exits on the candle it stops, as the
repos' own `positions.diff()` marks its trades. The clock rules (Dual Thrust, London Breakout) read UTC
candle open times and trade only on 15m, 30m and 1h candles; on 4h and 1d every signal is None.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.skill_ta import _to_signals

HOUR_MS = 3_600_000
DAY_MS = 86_400_000


# ---------------------------------------------------------------- helpers

def _ms(df) -> np.ndarray:
    return df.index.as_unit("ms").asi8


def _bar_ms(df) -> int | None:
    """The frame's candle length (the most common gap between candle times)."""
    if len(df) < 2:
        return None
    d = np.diff(_ms(df))
    d = d[d > 0]
    if not len(d):
        return None
    vals, counts = np.unique(d, return_counts=True)
    return int(vals[np.argmax(counts)])


def _intraday_ok(bar: int | None) -> bool:
    """A clock rule runs on candles of one hour or less that fit the hour exactly."""
    return bar is not None and bar <= HOUR_MS and HOUR_MS % bar == 0


def _none(n: int) -> list:
    return [None] * n


def _flips(pos: np.ndarray, side: int):
    """The candles where a position series enters and leaves `side` (+1 long, -1 short)."""
    on = pos == side
    prev = np.r_[False, on[:-1]]
    return on & ~prev, ~on & prev


class _Base:
    name = "base"

    def signals_all(self, df: pd.DataFrame, params: dict) -> list:
        raise NotImplementedError


# ---------------------------------------------------------------- je-suis-tm/quant-trading

class QtMacd(_Base):
    """`MACD Oscillator backtest.py`: positions[ma1:] = 1 where SMA(ma1) >= SMA(ma2) (both with
    min_periods=1), else 0; a trade on every change."""

    name = "gh_qt_macd"

    def signals_all(self, df, params):
        a, b = int(params["ma1"]), int(params["ma2"])
        c = df["close"]
        m1 = c.rolling(a, min_periods=1).mean().to_numpy()
        m2 = c.rolling(b, min_periods=1).mean().to_numpy()
        pos = np.zeros(len(df), int)
        pos[a:] = np.where(m1[a:] >= m2[a:], 1, 0)
        up, down = _flips(pos, 1)
        return _to_signals(len(df), b, up, np.zeros(len(df), bool), long_out=down)


class QtAwesome(_Base):
    """`Awesome Oscillator backtest.py`: 5- and 34-candle averages of (high+low)/2. As the script
    runs, the average rule overwrites the saucer on every candle where the averages differ, so the
    trades are: long when the 5 is above the 34, out when below (long only). `saucer=True` adds the
    script's two saucer blocks as their own trades (the README's intent): its first block (a red
    candle after two green, the oscillator below zero and rising) buys, its second sells; the averages
    then act only on the candle they cross, and win a candle both claim."""

    name = "gh_qt_awesome"

    def signals_all(self, df, params):
        f, s = int(params["fast"]), int(params["slow"])
        o, c = df["open"].to_numpy(), df["close"].to_numpy()
        med = (df["high"] + df["low"]) / 2
        m1, m2 = med.rolling(f).mean().to_numpy(), med.rolling(s).mean().to_numpy()
        ao = m1 - m2
        n = len(df)
        long_in, long_out = np.zeros(n, bool), np.zeros(n, bool)
        p = 0
        for i in range(s, n):                    # both averages exist from candle s - 1
            above, below = m1[i] > m2[i], m1[i] < m2[i]
            if not params.get("saucer"):
                if above and p == 0:
                    long_in[i], p = True, 1
                elif below and p == 1:
                    long_out[i], p = True, 0
                continue
            want = None
            if i >= 2 and o[i] > c[i] and o[i - 1] < c[i - 1] and o[i - 2] < c[i - 2] \
                    and ao[i - 1] > ao[i - 2] and ao[i - 1] < 0 and ao[i] < 0:
                want = 1
            if i >= 2 and o[i] < c[i] and o[i - 1] > c[i - 1] and o[i - 2] > c[i - 2] \
                    and ao[i - 1] < ao[i - 2] and ao[i - 1] > 0 and ao[i] > 0:
                want = 0
            if above and not m1[i - 1] > m2[i - 1]:         # the averages cross: they win
                want = 1
            elif below and not m1[i - 1] < m2[i - 1]:
                want = 0
            if want == 1 and p == 0:
                long_in[i], p = True, 1
            elif want == 0 and p == 1:
                long_out[i], p = True, 0
        return _to_signals(n, s, long_in, np.zeros(n, bool), long_out=long_out)


class QtHeikinAshi(_Base):
    """`Heikin-Ashi backtest.py` signal_generation, as coded: BUY when the HA candle is red with
    HA open == HA high, its body bigger than the previous HA body, and the previous HA candle red;
    SELL everything when the HA candle is green with HA open == HA low and the previous one green."""

    name = "gh_qt_heikin_ashi"

    def signals_all(self, df, params):
        o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        n = len(df)
        hc = (o + c + h + lo) / 4
        ho = np.empty(n)
        if n:
            ho[0] = o[0]
        for k in range(1, n):
            ho[k] = (ho[k - 1] + hc[k - 1]) / 2
        hh = np.maximum.reduce([ho, hc, lo, h])
        hl = np.minimum.reduce([ho, hc, lo, h])
        body = np.abs(ho - hc)
        long_in, long_out = np.zeros(n, bool), np.zeros(n, bool)
        for k in range(1, n):
            if ho[k] > hc[k] and ho[k] == hh[k] and body[k] > body[k - 1] and ho[k - 1] > hc[k - 1]:
                long_in[k] = True
            elif ho[k] < hc[k] and ho[k] == hl[k] and ho[k - 1] < hc[k - 1]:
                long_out[k] = True
        return _to_signals(n, int(params.get("warm", 10)), long_in, np.zeros(n, bool), long_out=long_out)


def qt_psar(df, initial_af=0.02, step_af=0.02, end_af=0.2) -> np.ndarray:
    """`Parabolic SAR backtest.py` parabolic_sar, line for line: the 'real sar' column."""
    h, lo, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
    n = len(df)
    trend, sar, real, ep, af = np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)
    if n < 2:
        return real
    trend[1] = 1 if c[1] > c[0] else -1
    sar[1] = h[0] if trend[1] > 0 else lo[0]
    real[1] = sar[1]
    ep[1] = h[1] if trend[1] > 0 else lo[1]
    af[1] = initial_af
    for i in range(2, n):
        temp = sar[i - 1] + af[i - 1] * (ep[i - 1] - sar[i - 1])
        if trend[i - 1] < 0:
            sar[i] = max(temp, h[i - 1], h[i - 2])
            temp = 1 if sar[i] < h[i] else trend[i - 1] - 1
        else:
            sar[i] = min(temp, lo[i - 1], lo[i - 2])
            temp = -1 if sar[i] > lo[i] else trend[i - 1] + 1
        trend[i] = temp
        if trend[i] < 0:
            temp = min(lo[i], ep[i - 1]) if trend[i] != -1 else lo[i]
        else:
            temp = max(h[i], ep[i - 1]) if trend[i] != 1 else h[i]
        ep[i] = temp
        if abs(trend[i]) == 1:
            temp = ep[i - 1]
            af[i] = initial_af
        else:
            temp = sar[i]
            af[i] = af[i - 1] if ep[i] == ep[i - 1] else min(end_af, af[i - 1] + step_af)
        real[i] = temp
    return real


class QtParabolicSar(_Base):
    """`Parabolic SAR backtest.py`: long while the close is above the 'real sar', flat below."""

    name = "gh_qt_psar"

    def signals_all(self, df, params):
        real = qt_psar(df, float(params["initial_af"]), float(params["step_af"]), float(params["end_af"]))
        pos = np.where(real < df["close"].to_numpy(float), 1, 0)
        up, down = _flips(pos, 1)
        return _to_signals(len(df), 5, up, np.zeros(len(df), bool), long_out=down)


def qt_rsi(close: pd.Series, n: int) -> np.ndarray:
    """`RSI Pattern Recognition backtest.py` rsi(): the smoothed average seeded with the first value,
    placed on candles n.. as the script places it; 0 before (the script's own fill)."""
    c = close.to_numpy(float)
    out = np.zeros(len(c))
    if len(c) <= n:
        return out
    d = np.diff(c)
    up, down = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    su, sd = np.empty(len(d)), np.empty(len(d))
    su[0], sd[0] = up[0], down[0]
    for k in range(1, len(d)):
        su[k] = (su[k - 1] * (n - 1) + up[k]) / n
        sd[k] = (sd[k - 1] * (n - 1) + down[k]) / n
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 100 - 100 / (1 + su / sd)
    out[n:] = r[n - 1:]
    return out


class QtRsi(_Base):
    """`RSI Pattern Recognition backtest.py` signal_generation: long while RSI 14 < 30, short while
    > 70, flat in between."""

    name = "gh_qt_rsi"

    def signals_all(self, df, params):
        n, lo, hi = int(params["period"]), float(params["low"]), float(params["high"])
        r = qt_rsi(df["close"], n)
        pos = np.select([r < lo, r > hi], [1, -1], default=0)
        li, lx = _flips(pos, 1)
        si, sx = _flips(pos, -1)
        return _to_signals(len(df), n + 1, li, si, long_out=lx, short_out=sx)


class QtBollingerW(_Base):
    """`Bollinger Bands Pattern Recognition backtest.py`: the bottom-W search over the last 75
    candles (20-candle bands at 2 standard deviations) and the exit on a band squeeze. `alpha` and
    `beta` are fractions of the close at the candle being checked."""

    name = "gh_qt_bollinger_w"

    def signals_all(self, df, params):
        period, a_f, b_f = int(params["period"]), float(params["alpha"]), float(params["beta"])
        price = df["close"].to_numpy(float)
        cs = df["close"]
        std = cs.rolling(20, min_periods=20).std().to_numpy()
        mid = cs.rolling(20, min_periods=20).mean().to_numpy()
        up, low = mid + 2 * std, mid - 2 * std
        n = len(df)
        long_in, long_out = np.zeros(n, bool), np.zeros(n, bool)
        for i in range(period, n):
            a = a_f * price[i]
            moveon = False
            if price[i] > up[i]:
                for j in range(i, i - period, -1):
                    if abs(mid[j] - price[j]) < a and abs(mid[j] - up[i]) < a:
                        moveon = True
                        break
                if moveon:
                    moveon = False
                    for k in range(j, i - period, -1):
                        if abs(low[k] - price[k]) < a:
                            threshold = price[k]
                            moveon = True
                            break
                if moveon:
                    moveon = False
                    for l_ in range(k, i - period, -1):
                        if mid[l_] < price[l_]:
                            moveon = True
                            break
                if moveon:
                    moveon = False
                    for m in range(i, j, -1):
                        if price[m] - low[m] < a and price[m] > low[m] and price[m] < threshold:
                            long_in[i] = True
                            moveon = True
                            break
            if std[i] < b_f * price[i] and not moveon:
                long_out[i] = True
        return _to_signals(n, period, long_in, np.zeros(n, bool), long_out=long_out)


class QtDualThrust(_Base):
    """`Dual Thrust backtest.py`, on sessions from `open_h` to `close_h` UTC. The range is
    max(highest high - lowest close, highest close - lowest low) over the `rg` sessions before this
    one; at the open the lines are open + k x range and open - (1 - k) x range; a close above the
    upper line goes long, below the lower goes short (reversing an open trade), once per side, and
    everything is closed at the session end."""

    name = "gh_qt_dual_thrust"

    def signals_all(self, df, params):
        n = len(df)
        bar = _bar_ms(df)
        if not _intraday_ok(bar):
            return _none(n)
        rg, k = int(params["rg"]), float(params["k"])
        o_ms = int(params["open_h"]) * HOUR_MS
        length = ((int(params["close_h"]) - int(params["open_h"])) % 24 or 24) * HOUR_MS
        ms = _ms(df)
        h, lo, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
        li, si, lx, sx = (np.zeros(n, bool) for _ in range(4))
        sessions: list = []
        cur = None
        start = None
        sigup = siglo = None
        p = 0
        for i in range(n):
            t, e = int(ms[i]), int(ms[i]) + bar
            if cur is not None and start <= t < start + length:
                cur["high"] = max(cur["high"], h[i])
                cur["low"] = min(cur["low"], lo[i])
            if cur is not None and e == start + length:
                cur["close"] = c[i]
                sessions.append(cur)
                cur, sigup, siglo = None, None, None
                if p == 1:
                    lx[i] = True
                elif p == -1:
                    sx[i] = True
                p = 0
            elif cur is not None and (t >= start + length or e > start + length):
                cur, sigup, siglo = None, None, None        # a gap skipped the session end
                if p == 1:
                    lx[i] = True
                elif p == -1:
                    sx[i] = True
                p = 0
            elif sigup is not None and t >= start:
                if c[i] > sigup and p != 1:
                    if p == -1:
                        sx[i] = True
                    li[i], p = True, 1
                elif c[i] < siglo and p != -1:
                    if p == 1:
                        lx[i] = True
                    si[i], p = True, -1
            if (e - o_ms) % DAY_MS == 0:
                if cur is not None and p != 0:             # an unclosed session: close it here
                    lx[i] |= p == 1
                    sx[i] |= p == -1
                    p = 0
                start = e
                cur = {"high": -np.inf, "low": np.inf}
                sigup = siglo = None
                if len(sessions) >= rg:
                    last = sessions[-rg:]
                    hh = max(s["high"] for s in last)
                    ll = min(s["low"] for s in last)
                    hc = max(s["close"] for s in last)
                    lc = min(s["close"] for s in last)
                    r = max(hh - lc, hc - ll)
                    sigup, siglo = c[i] + k * r, c[i] - (1 - k) * r
        return _to_signals(n, 1, li, si, long_out=lx, short_out=sx)


class QtLondonBreakout(_Base):
    """`London Breakout backtest.py`, in UTC (the script's EST 2am/3am/12pm = 7am/8am/5pm UTC): the
    high and low of the hour before 8:00 set the band; a candle OPENING in the first 30 minutes after
    8:00 whose close is above the band goes long (below: short), unless it is more than `risky` past
    the band, once a day; out at +/- `risky`/2 from the entry (the engine's stop and target, checked
    here too at each close outside the window) or at the 5pm close."""

    name = "gh_qt_london"

    def signals_all(self, df, params):
        n = len(df)
        bar = _bar_ms(df)
        if not _intraday_ok(bar):
            return _none(n)
        r0, o_ms = int(params["range_h"]) * HOUR_MS, int(params["open_h"]) * HOUR_MS
        win, c_ms = int(params["open_minutes"]) * 60_000, int(params["close_h"]) * HOUR_MS
        risky = float(params["risky"])
        ms = _ms(df)
        h, lo, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
        li, si, lx, sx = (np.zeros(n, bool) for _ in range(4))
        acc_h, acc_l = [], []
        upper = lower = None
        p, executed = 0, 0.0
        for i in range(n):
            t = int(ms[i])
            tod, tod_e = t % DAY_MS, (t + bar) % DAY_MS
            if r0 <= tod < o_ms:
                if tod == r0:
                    acc_h, acc_l = [], []
                acc_h.append(h[i])
                acc_l.append(lo[i])
                if tod_e == o_ms % DAY_MS:
                    upper, lower = max(acc_h), min(acc_l)
                    acc_h, acc_l = [], []
                continue
            if o_ms <= tod < o_ms + win:
                if upper is None:
                    continue
                if c[i] > upper and (c[i] - upper) <= risky * upper and p < 1:
                    if p == 0:
                        li[i], executed = True, c[i]
                    else:
                        sx[i] = True
                    p += 1
                if c[i] < lower and (lower - c[i]) <= risky * lower and p > -1:
                    if p == 0:
                        si[i], executed = True, c[i]
                    else:
                        lx[i] = True
                    p -= 1
                continue
            if tod_e == c_ms % DAY_MS:
                lx[i], sx[i] = p == 1, p == -1
                p, upper, lower = 0, None, None
                continue
            if p != 0 and (c[i] > executed * (1 + risky / 2) or c[i] < executed * (1 - risky / 2)):
                lx[i], sx[i] = p == 1, p == -1
                p = 0
        return _to_signals(n, 1, li, si, long_out=lx, short_out=sx)


class QtShootingStar(_Base):
    """`Shooting Star backtest.py`: a candle with open >= close, lower wick < 0.2 x body, body < 0.5 x
    |average (open - close)|, upper wick >= 2 x body, after two closes that did not fall - and the
    next candle's high and close no higher. Short at that NEXT candle's close (the script entered at
    the star's own close, which needed the next candle); out when the close is 5% from the entry
    either way, or after `hold` candles."""

    name = "gh_qt_shooting_star"

    def signals_all(self, df, params):
        lb, bs, hold = float(params["lower_bound"]), float(params["body_size"]), int(params["hold"])
        stop = float(params["stop"])
        o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        n = len(df)
        diff = o - c
        avg = np.cumsum(diff) / np.arange(1, n + 1)          # the average body up to each candle
        star = np.zeros(n, bool)
        for j in range(2, n):
            star[j] = (o[j] >= c[j] and (c[j] - lo[j]) < lb * abs(c[j] - o[j])
                       and abs(o[j] - c[j]) < abs(avg[j]) * bs and (h[j] - o[j]) >= 2 * (o[j] - c[j])
                       and c[j] >= c[j - 1] and c[j - 1] >= c[j - 2])
        si, sx = np.zeros(n, bool), np.zeros(n, bool)
        held, entry, count = False, 0.0, 0
        for i in range(3, n):
            if held:
                count += 1
                if abs(c[i] / entry - 1) > stop or count >= hold:
                    sx[i], held = True, False
            j = i - 1
            if not held and star[j] and h[i] <= h[j] and c[i] <= c[j]:
                si[i], held, entry, count = True, True, c[i], 0
        return _to_signals(n, 3, np.zeros(n, bool), si, short_out=sx)


# ---------------------------------------------------------------- Log-zz-ikIO/crypto-signal

def talib_rsi(close: pd.Series, n: int) -> np.ndarray:
    """TA-Lib's RSI (the bot's `abstract.RSI`): the first average is the plain mean of n changes,
    then Wilder's smoothing; NaN before candle n."""
    c = close.to_numpy(float)
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    d = np.diff(c)
    g, l_ = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    ag, al = g[:n].mean(), l_[:n].mean()

    def val(ag, al):
        return 0.0 if ag + al == 0 else 100 * ag / (ag + al)

    out[n] = val(ag, al)
    for k in range(n, len(d)):
        ag = (ag * (n - 1) + g[k]) / n
        al = (al * (n - 1) + l_[k]) / n
        out[k + 1] = val(ag, al)
    return out


class CsRsiBot(_Base):
    """`app/behaviours/rsi_bot.py`: buy when RSI 14 is at or under 30 and the coin is not held, sell
    when it is at or over 70 (long only, no stop of its own)."""

    name = "gh_cs_rsi"

    def signals_all(self, df, params):
        n = int(params["period"])
        r = talib_rsi(df["close"], n)
        with np.errstate(invalid="ignore"):
            buy, sell = r <= float(params["buy"]), r >= float(params["sell"])
        return _to_signals(len(df), n + 1, buy, np.zeros(len(df), bool), long_out=sell)


# ---------------------------------------------------------------- QuantConnect/Research

def lean_ema(close: pd.Series, n: int) -> np.ndarray:
    """LEAN's ExponentialMovingAverage(n): the first value is the plain mean of n closes, then
    k = 2 / (n + 1); NaN before."""
    c = close.to_numpy(float)
    out = np.full(len(c), np.nan)
    if len(c) < n:
        return out
    k = 2.0 / (n + 1)
    out[n - 1] = c[:n].mean()
    for i in range(n, len(c)):
        out[i] = c[i] * k + out[i - 1] * (1 - k)
    return out


class QcEmaCross(_Base):
    """`Analysis/04 EMA Cross Strategy Based on VXX.ipynb`, with the coin in VXX's place: 'buy' =
    close < EMA and the previous close > EMA (the notebook compares the previous close with TODAY's
    EMA; kept), 'sell' = close > EMA and the previous close < EMA; long on buy, cash on sell.
    `side="above"` swaps them (long when the price crosses above its EMA)."""

    name = "gh_qc_ema_cross"

    def signals_all(self, df, params):
        p = int(params["period"])
        c = df["close"].to_numpy(float)
        ema = lean_ema(df["close"], p)
        prev = np.r_[np.nan, c[:-1]]
        with np.errstate(invalid="ignore"):
            sell = (c > ema) & (prev < ema)
            buy = (c < ema) & (prev > ema)
        if params.get("side") == "above":
            buy, sell = sell, buy
        return _to_signals(len(df), p + 1, buy, np.zeros(len(df), bool), long_out=sell)


# ---------------------------------------------------------------- the seven tables

STRATEGIES = {s.name: s for s in (QtMacd(), QtAwesome(), QtHeikinAshi(), QtParabolicSar(), QtRsi(),
                                  QtBollingerW(), QtDualThrust(), QtLondonBreakout(), QtShootingStar(),
                                  CsRsiBot(), QcEmaCross())}

GRID = {
    "gh_qt_macd": [{"ma1": 10, "ma2": 21}, {"ma1": 12, "ma2": 26}],
    "gh_qt_awesome": [{"fast": 5, "slow": 34, "saucer": False}, {"fast": 5, "slow": 34, "saucer": True}],
    "gh_qt_heikin_ashi": [{"warm": 10}],
    "gh_qt_psar": [{"initial_af": 0.02, "step_af": 0.02, "end_af": 0.2},
                   {"initial_af": 0.01, "step_af": 0.01, "end_af": 0.2}],
    "gh_qt_rsi": [{"period": 14, "low": 30, "high": 70}],
    "gh_qt_bollinger_w": [{"period": 75, "alpha": 0.0001, "beta": 0.0001},
                          {"period": 75, "alpha": 0.001, "beta": 0.001}],
    "gh_qt_dual_thrust": [{"rg": 5, "k": 0.5, "open_h": 8, "close_h": 17},
                          {"rg": 5, "k": 0.5, "open_h": 0, "close_h": 0}],
    "gh_qt_london": [{"range_h": 7, "open_h": 8, "open_minutes": 30, "close_h": 17, "risky": 0.01}],
    "gh_qt_shooting_star": [{"lower_bound": 0.2, "body_size": 0.5, "hold": 7, "stop": 0.05}],
    "gh_cs_rsi": [{"period": 14, "buy": 30, "sell": 70}],
    "gh_qc_ema_cross": [{"period": 10, "side": "below"}, {"period": 10, "side": "above"}],
}

# the repo's own stop where it has one (otherwise gh_strats.DEFAULT_STOPS)
STOPS = {
    "gh_qt_london": (0.005,),          # risky_stop / 2 = 0.005, read as 0.5% of the entry
    "gh_qt_shooting_star": (0.05,),    # stop_threshold = 0.05
}

# a target as a multiple of the stop; None = out by the stop or the rule's own exit
TARGETS = {
    "gh_qt_macd": None,
    "gh_qt_awesome": None,
    "gh_qt_heikin_ashi": None,
    "gh_qt_psar": None,
    "gh_qt_rsi": None,
    "gh_qt_bollinger_w": None,
    "gh_qt_dual_thrust": None,
    "gh_qt_london": 1.0,               # the same 0.5% either way
    "gh_qt_shooting_star": 1.0,        # the same 5% either way
    "gh_cs_rsi": None,
    "gh_qc_ema_cross": None,
}

REPO_OF = {name: "je-suis-tm/quant-trading" for name in STRATEGIES if name.startswith("gh_qt_")}
REPO_OF["gh_cs_rsi"] = "Log-zz-ikIO/crypto-signal"
REPO_OF["gh_qc_ema_cross"] = "QuantConnect/Research"

_SIZE = " The repo's share counts are not used: the engine trades $5 x 20x with its own stop."
RULE_OF = {
    "gh_qt_macd": "Long when the 10-candle average of the close moves to or above the 21 (or 12/26), "
                  "out when it falls below; long only (MACD Oscillator backtest.py)." + _SIZE,
    "gh_qt_awesome": "Long when the 5-candle average of (high+low)/2 is above the 34, out when below, "
                     "long only - the saucer setting also buys on the script's red-candle saucer and "
                     "sells on its green one (Awesome Oscillator backtest.py; as written the averages "
                     "overwrite the saucer, which is the first setting)." + _SIZE,
    "gh_qt_heikin_ashi": "Buy when the Heikin-Ashi candle is red with no upper wick, a bigger body than "
                         "the previous red one; sell when it is green with no lower wick after a green "
                         "one; one position, not the script's 3 stacked buys (Heikin-Ashi backtest.py)."
                         + _SIZE,
    "gh_qt_psar": "Long while the close is above the Parabolic SAR (0.02 start and step, 0.2 cap; or "
                  "the script's 0.01 for stocks), out when below (Parabolic SAR backtest.py)." + _SIZE,
    "gh_qt_rsi": "Long while Wilder RSI 14 is under 30, short while over 70, out when it returns between "
                 "(RSI Pattern Recognition backtest.py, its main rule)." + _SIZE,
    "gh_qt_bollinger_w": "Buy a close above the upper 20-candle band that completes a W double bottom in "
                         "the last 75 candles; out when the band's standard deviation drops under beta; "
                         "alpha and beta (0.0001 in GBP/USD prices) are read as 0.01% of the price, or "
                         "0.1% in the second setting (Bollinger Bands Pattern Recognition backtest.py)."
                         + _SIZE,
    "gh_qt_dual_thrust": "At the session open (8am UTC = the script's 3am EST, or 00:00 UTC) set lines "
                         "at the open +/- 0.5 x the 5 PREVIOUS sessions' range; a close above goes long, "
                         "below goes short, close all at the session end (5pm UTC / next 00:00); only on "
                         "15m-1h candles, no trades on 4h or 1d (Dual Thrust backtest.py; its range "
                         "included the day itself, removed)." + _SIZE,
    "gh_qt_london": "The 7am-8am UTC high and low set a band; a candle opening 8:00-8:29 that closes "
                    "above it buys (below sells) unless more than 1% past it; out at 0.5% either way or "
                    "at 5pm UTC; only on 15m-1h candles, none on 4h or 1d (London Breakout backtest.py; "
                    "its 0.01 and 0.005 were GBP/USD prices, read as 1% and 0.5%)." + _SIZE,
    "gh_qt_shooting_star": "Short at the close of the candle after a shooting star (red, long upper wick, "
                           "tiny lower wick, small body, after two rising closes) when that candle makes "
                           "no higher high or close; out at 5% either way or after 7 candles (Shooting "
                           "Star backtest.py; it read the next candle and the whole history's average "
                           "body, both removed; it needs an opening gap above the last close, so on "
                           "24-hour coins it almost never fires - 0 times on a month of BTC 5m-1h)."
                           + _SIZE,
    "gh_cs_rsi": "Buy when TA-Lib RSI 14 is at or under 30 and nothing is held, sell when it is at or "
                 "over 70; long only (app/behaviours/rsi_bot.py with app/default-config.json)." + _SIZE,
    "gh_qc_ema_cross": "The notebook's formula with the coin in VXX's place: buy when the close falls "
                       "back under its 10-candle EMA, go to cash when it rises above (or the mirror: "
                       "long on the rise above) (Analysis/04 EMA Cross Strategy Based on VXX.ipynb)."
                       + _SIZE,
}

NOT_PORTED = {
    "je-suis-tm/quant-trading: Pair trading": "trades NVDA against AMD at once (a cointegration test "
        "on two price series); the engine holds one coin.",
    "je-suis-tm/quant-trading: Oil Money": "regresses a currency on Brent crude, two series at once; "
        "the engine holds one coin.",
    "je-suis-tm/quant-trading: Options Straddle": "buys a call and a put; Gate's contracts have no "
        "options.",
    "je-suis-tm/quant-trading: VIX Calculator": "a volatility calculator from an options chain, no "
        "trading rule.",
    "je-suis-tm/quant-trading: Monte Carlo": "a test of price forecasting by random paths, no trading "
        "rule.",
    "je-suis-tm/quant-trading: Smart Farmers": "a yearly crop supply forecast, no trading rule.",
    "je-suis-tm/quant-trading: Portfolio Optimization": "lives in another repo (graph-theory) and "
        "weights many assets; no timing rule.",
    "je-suis-tm/quant-trading: Wisdom of Crowds": "lives in another repo (machine-learning); not a "
        "single-coin rule.",
    "je-suis-tm/quant-trading: RSI head-and-shoulders": "never run by the script's main, and its "
        "tolerances (0.2, 1.1 x 0.2) are dollars of one stock, meaningless across coins.",
    "Log-zz-ikIO/crypto-signal: default alerts": "SMA, EMA, MACD, Bollinger, Ichimoku and the "
        "breakout share are called with thresholds 0, so they fire on every coin every time or never; "
        "they print alerts and name no buy or sell.",
    "QuantConnect/Research: VXX fear-index rule": "reads VXX (a fear-index fund) to trade SPY, IWM and "
        "DIA - two series at once, and Gate has no fear index; its formula is ported on the coin "
        "itself as gh_qc_ema_cross.",
    "QuantConnect/Research: XOM/CVX pairs": "cointegration and Kalman-filter pair trades need two coins "
        "at once (and fit their bands on the whole period).",
    "QuantConnect/Research: other notebooks": "factor ranking, P/E picks, uncorrelated assets, "
        "mean-variance and Treasury mean reversion pick among many assets; the HMM, random forest, PCA "
        "and LSTM notebooks forecast without a trading rule.",
}
