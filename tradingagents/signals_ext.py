"""Thirteen more entry rules, so the search has 20 to choose from.

The engine shipped with 7 (mom6, mom15, fade15, trend50, rsi14, sweep30, fvg).
The operator asked why Fibonacci, support and resistance were missing: they had
never been written. These are them, plus the other classics a discretionary
trader would reach for.

Every function returns a **direction array** — one entry per bar, ``1`` long,
``-1`` short, ``0`` nothing — computed with the same discipline the live rules
use: a bar may only look at itself and the bars BEFORE it. Peeking one bar ahead
is how a backtest invents an edge that cannot be traded.

All are O(n). ``auto_trader._dirs_for_backtest`` dispatches to them by key
prefix, so a spec named ``fib618_x`` picks up :func:`fib618`.
"""
from __future__ import annotations

import math


def _ema(vals: list[float], span: int) -> list[float]:
    if not vals:
        return []
    k = 2.0 / (span + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _rolling_extremes(vals: list[float], n: int, hi: bool) -> list[float]:
    """Rolling max (or min) of the n bars ENDING ONE BAR BACK."""
    out = [math.nan] * len(vals)
    for i in range(n, len(vals)):
        w = vals[i - n:i]
        out[i] = max(w) if hi else min(w)
    return out


def _atr(high, low, close, n: int = 14) -> list[float]:
    tr = [0.0] * len(close)
    for i in range(1, len(close)):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]),
                    abs(low[i] - close[i - 1]))
    out = [math.nan] * len(close)
    if len(close) <= n:
        return out
    run = sum(tr[1:n + 1]) / n
    out[n] = run
    for i in range(n + 1, len(close)):
        run = (run * (n - 1) + tr[i]) / n
        out[i] = run
    return out


# --------------------------------------------------------------- Fibonacci
def _fib(high, low, close, level: float, look: int = 50) -> list[int]:
    """Retracement entry against the last completed swing.

    The swing is the highest high and lowest low of the previous ``look`` bars.
    In an up-swing (the high came later than the low) the retracement level sits
    at ``high - level * range``; the rule waits for price to trade DOWN through
    it and close back above, which is the "buy the pullback" trade. A
    down-swing mirrors it.
    """
    n = len(close)
    out = [0] * n
    for i in range(look + 1, n):
        w_hi = high[i - look:i]
        w_lo = low[i - look:i]
        hh, ll = max(w_hi), min(w_lo)
        rng = hh - ll
        if rng <= 0:
            continue
        i_hi = i - look + w_hi.index(hh)
        i_lo = i - look + w_lo.index(ll)
        if i_hi > i_lo:                       # up-swing: buy the retracement
            lvl = hh - level * rng
            if low[i] <= lvl < close[i]:
                out[i] = 1
        else:                                 # down-swing: sell the bounce
            lvl = ll + level * rng
            if high[i] >= lvl > close[i]:
                out[i] = -1
    return out


def fib618(high, low, close) -> list[int]:
    """The 61.8% retracement — the deep pullback."""
    return _fib(high, low, close, 0.618)


def fib382(high, low, close) -> list[int]:
    """The 38.2% retracement — the shallow pullback.

    Whether it fires more often than 61.8% depends on the series: the level is
    easier to reach but harder to close back above. On PI's real 1h year it
    fired 1,021 times against 61.8%'s 621.
    """
    return _fib(high, low, close, 0.382)


# ------------------------------------------------- support and resistance
def sr_bounce(high, low, close, look: int = 40, tol: float = 0.002) -> list[int]:
    """Buy the touch of support, sell the touch of resistance.

    Support is the lowest low of the previous ``look`` bars, resistance the
    highest high. A bar that trades within ``tol`` of the level and closes back
    inside the range is the bounce.
    """
    n = len(close)
    out = [0] * n
    sup = _rolling_extremes(low, look, hi=False)
    res = _rolling_extremes(high, look, hi=True)
    for i in range(look, n):
        s, r = sup[i], res[i]
        if s != s or r != r or s <= 0:
            continue
        if low[i] <= s * (1 + tol) and close[i] > s:
            out[i] = 1
        elif high[i] >= r * (1 - tol) and close[i] < r:
            out[i] = -1
    return out


def sr_break(high, low, close, look: int = 40) -> list[int]:
    """The opposite trade: go WITH a close beyond the level, not against it."""
    n = len(close)
    out = [0] * n
    sup = _rolling_extremes(low, look, hi=False)
    res = _rolling_extremes(high, look, hi=True)
    for i in range(look, n):
        s, r = sup[i], res[i]
        if s != s or r != r:
            continue
        if close[i] > r:
            out[i] = 1
        elif close[i] < s:
            out[i] = -1
    return out


def donchian20(high, low, close) -> list[int]:
    """Donchian breakout: close outside the previous 20-bar channel."""
    return sr_break(high, low, close, look=20)


def pivot(high, low, close) -> list[int]:
    """Classic floor-trader pivots off the PREVIOUS bar's high/low/close.

    Long when price dips to S1 and closes above it, short at R1.
    """
    n = len(close)
    out = [0] * n
    for i in range(1, n):
        p = (high[i - 1] + low[i - 1] + close[i - 1]) / 3
        s1 = 2 * p - high[i - 1]
        r1 = 2 * p - low[i - 1]
        if low[i] <= s1 < close[i]:
            out[i] = 1
        elif high[i] >= r1 > close[i]:
            out[i] = -1
    return out


# ------------------------------------------------------------- bands
def _bollinger(close, n: int = 20, k: float = 2.0):
    mid = [math.nan] * len(close)
    sd = [math.nan] * len(close)
    run = 0.0
    for i, v in enumerate(close):
        run += v
        if i >= n:
            run -= close[i - n]
        if i >= n - 1:
            m = run / n
            var = sum((close[j] - m) ** 2 for j in range(i - n + 1, i + 1)) / n
            mid[i], sd[i] = m, math.sqrt(var)
    return mid, sd, k


def bb20(high, low, close) -> list[int]:
    """Bollinger MEAN REVERSION: close outside the 2-sigma band, fade it."""
    mid, sd, k = _bollinger(close)
    out = [0] * len(close)
    for i in range(len(close)):
        if mid[i] != mid[i] or sd[i] == 0:
            continue
        if close[i] < mid[i] - k * sd[i]:
            out[i] = 1
        elif close[i] > mid[i] + k * sd[i]:
            out[i] = -1
    return out


def bbbreak(high, low, close) -> list[int]:
    """Bollinger BREAKOUT: the same event traded the other way."""
    return [-d for d in bb20(high, low, close)]


def keltner(high, low, close, n: int = 20, mult: float = 1.5) -> list[int]:
    """Keltner channel: EMA centre, ATR width. Fade a close outside it."""
    e = _ema(close, n)
    a = _atr(high, low, close)
    out = [0] * len(close)
    for i in range(len(close)):
        if a[i] != a[i]:
            continue
        if close[i] < e[i] - mult * a[i]:
            out[i] = 1
        elif close[i] > e[i] + mult * a[i]:
            out[i] = -1
    return out


def atrbreak(high, low, close, mult: float = 1.0) -> list[int]:
    """A bar that travels more than ``mult`` x ATR from the prior close, in
    the direction it travelled."""
    a = _atr(high, low, close)
    out = [0] * len(close)
    for i in range(1, len(close)):
        if a[i] != a[i] or a[i] == 0:
            continue
        move = close[i] - close[i - 1]
        if move > mult * a[i]:
            out[i] = 1
        elif move < -mult * a[i]:
            out[i] = -1
    return out


# ---------------------------------------------------------- oscillators
def macd(high, low, close) -> list[int]:
    """MACD 12/26/9 line crossing its signal."""
    f, s = _ema(close, 12), _ema(close, 26)
    line = [a - b for a, b in zip(f, s, strict=False)]
    sig = _ema(line, 9)
    out = [0] * len(close)
    for i in range(1, len(close)):
        if line[i - 1] <= sig[i - 1] and line[i] > sig[i]:
            out[i] = 1
        elif line[i - 1] >= sig[i - 1] and line[i] < sig[i]:
            out[i] = -1
    return out


def emacross(high, low, close) -> list[int]:
    """EMA 9 crossing EMA 21."""
    f, s = _ema(close, 9), _ema(close, 21)
    out = [0] * len(close)
    for i in range(1, len(close)):
        if f[i - 1] <= s[i - 1] and f[i] > s[i]:
            out[i] = 1
        elif f[i - 1] >= s[i - 1] and f[i] < s[i]:
            out[i] = -1
    return out


def stoch14(high, low, close, n: int = 14) -> list[int]:
    """Stochastic %K: long under 20, short over 80."""
    out = [0] * len(close)
    for i in range(n, len(close)):
        hh = max(high[i - n + 1:i + 1])
        ll = min(low[i - n + 1:i + 1])
        if hh == ll:
            continue
        k = 100 * (close[i] - ll) / (hh - ll)
        out[i] = 1 if k < 20 else (-1 if k > 80 else 0)
    return out


def cci20(high, low, close, n: int = 20) -> list[int]:
    """Commodity Channel Index: long under -100, short over +100."""
    tp = [(h + lo + c) / 3 for h, lo, c in zip(high, low, close, strict=False)]
    out = [0] * len(close)
    for i in range(n, len(close)):
        w = tp[i - n + 1:i + 1]
        m = sum(w) / n
        md = sum(abs(x - m) for x in w) / n
        if md == 0:
            continue
        c = (tp[i] - m) / (0.015 * md)
        out[i] = 1 if c < -100 else (-1 if c > 100 else 0)
    return out


def engulf(high, low, close) -> list[int]:
    """Engulfing bar: this bar's range swallows the previous one, traded in
    the direction of this bar's close."""
    out = [0] * len(close)
    for i in range(2, len(close)):
        prev_hi = max(close[i - 1], close[i - 2])
        prev_lo = min(close[i - 1], close[i - 2])
        if high[i] > prev_hi and low[i] < prev_lo:
            out[i] = 1 if close[i] > close[i - 1] else -1
    return out


# The dispatcher's table. Key prefixes map here; see
# ``auto_trader._dirs_for_backtest``.
EXTRA_SIGNALS = {
    "fib618": fib618, "fib382": fib382,
    "sr_bounce": sr_bounce, "sr_break": sr_break, "donchian20": donchian20,
    "pivot": pivot, "bb20": bb20, "bbbreak": bbbreak, "keltner": keltner,
    "atrbreak": atrbreak, "macd": macd, "emacross": emacross,
    "stoch14": stoch14, "cci20": cci20, "engulf": engulf,
}
