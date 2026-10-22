"""The Pro Trader research's indicators (Oct 20, 2026), all FIXED-WINDOW.

The live runner reads 300 candles (299 closed) before it decides a signal
(auto_trader.process_symbol), while the backtest walks a deep window. An
indicator whose value depends on where its history STARTS (a recursive EMA,
Wilder's RSI/ATR/ADX) would read differently in the two, and a strategy would
trade a signal no backtest measured. So every indicator here looks back over a
fixed number of bars and nothing more, and every family keeps its whole
lookback at or under `MAX_LOOKBACK` bars: given that many bars, the runner and
the backtest compute the same number to the last bit.

Every function takes numpy arrays and returns a float array of the same
length, NaN where the window is not yet full. A value at bar i reads bars up
to and including i (a closed candle), never after it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MAX_LOOKBACK = 250


def _s(x) -> pd.Series:
    return pd.Series(np.asarray(x, dtype=float))


def _windows(x, n: int):
    """(the last n values ending at each bar i >= n-1, as rows; the array).
    Each window is summed FRESH: a running sum carries rounding from bars
    before the window, so a frame that starts later (the runner's 300
    candles) could read a hair differently from the backtest's deep frame."""
    a = np.asarray(x, dtype=float)
    if len(a) < n:
        return None, a
    return np.lib.stride_tricks.sliding_window_view(a, int(n)), a


def rolling_sum(x, n: int) -> np.ndarray:
    w, a = _windows(x, n)
    out = np.full(len(a), np.nan)
    if w is not None:
        out[n - 1:] = w.sum(axis=1)
    return out


def sma(x, n: int) -> np.ndarray:
    w, a = _windows(x, n)
    out = np.full(len(a), np.nan)
    if w is not None:
        out[n - 1:] = w.sum(axis=1) / n
    return out


def rolling_std(x, n: int) -> np.ndarray:
    w, a = _windows(x, n)
    out = np.full(len(a), np.nan)
    if w is not None:
        out[n - 1:] = w.std(axis=1)
    return out


def rolling_max(x, n: int) -> np.ndarray:
    return _s(x).rolling(int(n), min_periods=int(n)).max().to_numpy()


def rolling_min(x, n: int) -> np.ndarray:
    return _s(x).rolling(int(n), min_periods=int(n)).min().to_numpy()


def shift(x, k: int = 1) -> np.ndarray:
    """x moved k bars later (bar i reads bar i-k); NaN where there is none."""
    a = np.asarray(x, dtype=float)
    out = np.full(len(a), np.nan)
    if k < len(a):
        out[k:] = a[:len(a) - k]
    return out


def true_range(h, lo, c) -> np.ndarray:
    h, lo, c = (np.asarray(v, dtype=float) for v in (h, lo, c))
    pc = shift(c, 1)
    tr = np.maximum(h - lo, np.maximum(np.abs(h - pc), np.abs(lo - pc)))
    tr[0] = h[0] - lo[0] if len(h) else np.nan
    return tr


def atr(h, lo, c, n: int) -> np.ndarray:
    """The plain average of the last n true ranges (not Wilder's recursion)."""
    return sma(true_range(h, lo, c), n)


def roc(c, n: int) -> np.ndarray:
    """The n-bar return, as a fraction."""
    c = np.asarray(c, dtype=float)
    return c / shift(c, n) - 1.0


def donchian(h, lo, n: int) -> tuple[np.ndarray, np.ndarray]:
    """The highest high and lowest low of the n bars BEFORE bar i — a close
    above the first is a breakout of the channel the bar did not help draw."""
    return shift(rolling_max(h, n), 1), shift(rolling_min(lo, n), 1)


def efficiency(c, n: int) -> np.ndarray:
    """Kaufman's efficiency ratio: how straight the last n bars went, from 0
    (back and forth) to 1 (one way)."""
    c = np.asarray(c, dtype=float)
    move = np.abs(c - shift(c, n))
    path = rolling_sum(np.abs(np.diff(c, prepend=np.nan)), n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return move / path


def pct_rank(x, n: int) -> np.ndarray:
    """Where bar i's value sits among the last n values, 0 (lowest) to 1."""
    s = _s(x)
    return s.rolling(int(n), min_periods=int(n)).rank(pct=True).to_numpy()


def rsi(c, n: int) -> np.ndarray:
    """Cutler's RSI: plain averages of the last n gains and losses."""
    d = np.diff(np.asarray(c, dtype=float), prepend=np.nan)
    # bar 0 has no change: NaN keeps the first window from counting a fake 0
    up = sma(np.where(np.isnan(d), np.nan, np.where(d > 0, d, 0.0)), n)
    dn = sma(np.where(np.isnan(d), np.nan, np.where(d < 0, -d, 0.0)), n)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = 100.0 - 100.0 / (1.0 + up / dn)
    out = np.where(dn == 0, np.where(up > 0, 100.0, 50.0), out)
    return np.where(np.isnan(up) | np.isnan(dn), np.nan, out)


def zscore(c, n: int) -> np.ndarray:
    m, s = sma(c, n), rolling_std(c, n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (np.asarray(c, dtype=float) - m) / s


def rolling_vwap(h, lo, c, v, n: int) -> np.ndarray:
    """The volume-weighted typical price of the last n bars."""
    tp = (np.asarray(h, dtype=float) + np.asarray(lo, dtype=float) + np.asarray(c, dtype=float)) / 3
    v = np.asarray(v, dtype=float)
    num = rolling_sum(tp * v, n)
    den = rolling_sum(v, n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def vol_ratio(v, n: int) -> np.ndarray:
    """This bar's volume against the average of the n before it."""
    v = np.asarray(v, dtype=float)
    base = shift(sma(v, n), 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(base > 0, v / base, np.nan)


def ema_fixed(x, n: int, window: int | None = None) -> np.ndarray:
    """The exponential average with weight 2/(n+1) as a FIXED-WINDOW sum: the
    last `window` values (default min(MAX_LOOKBACK, 10 x n)), weights
    normalised to 1. The recursion every chart uses depends on where its
    history starts; this reads the same bars from any frame, so the runner's
    299 candles and the backtest's year agree to the last bit (the weight
    beyond 10 x n is 2e-9 of the whole for n 9, 4.5e-5 for n 50). Elementwise
    multiply and a row sum, never a matrix product: BLAS blocks a product by
    the matrix's size, so two frames could round differently."""
    w = int(window or min(MAX_LOOKBACK, 10 * int(n)))
    win, a = _windows(x, w)
    out = np.full(len(a), np.nan)
    if win is None:
        return out
    alpha = 2.0 / (int(n) + 1.0)
    wts = alpha * (1.0 - alpha) ** np.arange(w - 1, -1, -1, dtype=float)
    out[w - 1:] = (win * (wts / wts.sum())).sum(axis=1)
    return out
