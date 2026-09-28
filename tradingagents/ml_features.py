"""Price-only clues for the Sep 27 ML models (the operator's "use machine
learning on what's best strategy", Sep 27, 2026).

THE CONTRACT: row i reads only bars <= i, and every clue is a FINITE window of
at most MAX_WINDOW bars — no running average that remembers the whole array.
So the same candle gives the same number whether the array starts 300 bars
before it (the stored row's cut, sweep_shard.window) or a year before it (the
learner), and the grid, the grade and the live runner agree by construction.
The Sep 25 loop had to grade on the stored row's cut because its EMAs drift;
this module removes the reason. NaN until a window is full, or where an input
does not exist (a contract with no volume); the model abstains on any NaN row.

NO FUNDING CLUE (VERSION 2, Sep 28, 2026 review). Version 1 carried the rate
in force at the next open as a clue. The live runner calls `signal_for`
without a funding list, so every live bar read 0 there while the grid read
the real rate — a model measured one way and run another. Funding is charged
by the engine on every trade; it is never read as a clue.
"""
from __future__ import annotations

import numpy as np

VERSION = 2
MAX_WINDOW = 200
RETURNS = (1, 3, 6, 12, 24, 48)
FEATURES = tuple(
    [f"ret_{k}" for k in RETURNS]
    + ["rsi_14", "atrpct_14", "retstd_20", "range_20", "range_50",
       "dist_sma_20", "dist_sma_50", "dist_sma_200",
       "body", "upper_wick", "lower_wick", "vol_ratio_20",
       "hour", "dow"])

_BAR_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000,
           "4h": 14_400_000, "1d": 86_400_000}


def _roll(x: np.ndarray, w: int, fn) -> np.ndarray:
    """fn over each window of w bars ending at i; NaN before the first."""
    out = np.full(len(x), np.nan)
    if len(x) >= w:
        out[w - 1:] = fn(np.lib.stride_tricks.sliding_window_view(x, w), axis=1)
    return out


def _div(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a / b
    out[~np.isfinite(out)] = np.nan
    return out


def features(o, h, lo, c, v, ts, funding, tf) -> np.ndarray:
    """One row of clues per bar, columns in FEATURES order.

    `funding` is accepted and IGNORED: funding is charged by the engine,
    never read as a clue — the live runner calls signal_for without it
    (Sep 28, 2026 review). The parameter stays because every caller passes it."""
    del funding
    o = np.asarray(o, dtype=float)
    h = np.asarray(h, dtype=float)
    lo = np.asarray(lo, dtype=float)
    c = np.asarray(c, dtype=float)
    n = len(c)
    if n == 0:
        # A frame with nothing before the cut (Sep 28, 2026: DOGE/TIA 15m on
        # GitHub, a fetch that came back with no candles before the last 30
        # days) has no bar to read. Every column below indexes bar 0
        # (`tr[0] = h[0] - lo[0]`), which raises IndexError on an empty
        # array; the caller (MLLearner) is the one that says why history is
        # short, this function just answers "no rows" instead of crashing.
        return np.zeros((0, len(FEATURES)))
    v = np.asarray(v, dtype=float) if v is not None and len(v) == n else np.zeros(n)
    ts = np.asarray(ts, dtype=np.int64) if ts is not None and len(ts) == n \
        else np.zeros(n, dtype=np.int64)
    cols = []
    for k in RETURNS:
        r = np.full(n, np.nan)
        r[k:] = _div(c[k:], c[:-k]) - 1.0
        cols.append(r)
    d = np.concatenate([[np.nan], np.diff(c)])
    up = _roll(np.where(d > 0, d, 0.0), 14, np.mean)
    dn = _roll(np.where(d < 0, -d, 0.0), 14, np.mean)
    up[:14] = np.nan
    rsi = _div(100.0 * up, up + dn)
    rsi[(up == 0) & (dn == 0)] = 50.0
    cols.append(rsi)
    prev = np.concatenate([[np.nan], c[:-1]])
    tr = np.fmax(h - lo, np.fmax(np.abs(h - prev), np.abs(lo - prev)))
    tr[0] = h[0] - lo[0]
    cols.append(_div(_roll(tr, 14, np.mean), c))
    r1 = np.concatenate([[np.nan], _div(c[1:], c[:-1]) - 1.0])
    std = _roll(r1, 20, np.std)
    std[:20] = np.nan
    cols.append(std)
    for w in (20, 50):
        hi, lw = _roll(h, w, np.max), _roll(lo, w, np.min)
        cols.append(_div(c - lw, hi - lw))
    for w in (20, 50, 200):
        cols.append(_div(c, _roll(c, w, np.mean)) - 1.0)
    rng = h - lo
    cols.append(_div(c - o, rng))
    cols.append(_div(h - np.maximum(o, c), rng))
    cols.append(_div(np.minimum(o, c) - lo, rng))
    base = np.concatenate([[np.nan], _roll(v, 20, np.mean)[:-1]])   # the 20 BEFORE i
    cols.append(_div(v, np.where(base > 0, base, np.nan)))
    t_next = ts + _BAR_MS.get(tf, 3_600_000)          # the order goes in at the next open
    cols.append(((t_next // 3_600_000) % 24).astype(float))
    cols.append(((t_next // 86_400_000 + 3) % 7).astype(float))     # Monday = 0
    out = np.column_stack(cols) if n else np.zeros((0, len(FEATURES)))
    return out
