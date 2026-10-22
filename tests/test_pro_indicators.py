"""The Pro Trader indicators (tradingagents/pro_indicators.py), Oct 20, 2026.

The guard that matters: the live runner decides on its last 299 closed
candles, the backtest on a deep window. A fixed-window indicator must give
the SAME value at a bar from either frame, to the last bit — otherwise the
runner trades a signal no backtest measured. And no value may read a bar
after its own."""
from __future__ import annotations

import math
import random

import numpy as np
import pytest

from tradingagents import pro_indicators as pi


def _ohlcv(n=3000, seed=4):
    rnd = random.Random(seed)
    px, o, h, lo, c, v = 100.0, [], [], [], [], []
    for _ in range(n):
        op = px
        cl = op * math.exp(rnd.gauss(0, 0.006))
        o.append(op)
        h.append(max(op, cl) * (1 + abs(rnd.gauss(0, 0.002))))
        lo.append(min(op, cl) * (1 - abs(rnd.gauss(0, 0.002))))
        c.append(cl)
        v.append(1000 * (0.5 + rnd.random()))
        px = cl
    return (np.array(o), np.array(h), np.array(lo), np.array(c), np.array(v))


CASES = {
    "sma": lambda o, h, lo, c, v: pi.sma(c, 200),
    "rolling_std": lambda o, h, lo, c, v: pi.rolling_std(c, 100),
    "rolling_sum": lambda o, h, lo, c, v: pi.rolling_sum(v, 50),
    "rolling_max": lambda o, h, lo, c, v: pi.rolling_max(h, 55),
    "rolling_min": lambda o, h, lo, c, v: pi.rolling_min(lo, 55),
    "atr": lambda o, h, lo, c, v: pi.atr(h, lo, c, 20),
    "roc": lambda o, h, lo, c, v: pi.roc(c, 48),
    "donchian_hi": lambda o, h, lo, c, v: pi.donchian(h, lo, 55)[0],
    "donchian_lo": lambda o, h, lo, c, v: pi.donchian(h, lo, 55)[1],
    "efficiency": lambda o, h, lo, c, v: pi.efficiency(c, 30),
    "pct_rank": lambda o, h, lo, c, v: pi.pct_rank(pi.atr(h, lo, c, 20) / c, 120),
    "rsi": lambda o, h, lo, c, v: pi.rsi(c, 14),
    "zscore": lambda o, h, lo, c, v: pi.zscore(c, 50),
    "rolling_vwap": lambda o, h, lo, c, v: pi.rolling_vwap(h, lo, c, v, 48),
    "vol_ratio": lambda o, h, lo, c, v: pi.vol_ratio(v, 20),
    "ema_fixed_9": lambda o, h, lo, c, v: pi.ema_fixed(c, 9),
    "ema_fixed_50": lambda o, h, lo, c, v: pi.ema_fixed(c, 50),
}


@pytest.mark.parametrize("name", list(CASES))
def test_the_runners_299_candles_read_what_the_deep_window_reads(name):
    full = _ohlcv()
    whole = CASES[name](*full)
    for end in (400, 1234, 2017, 3000):
        tail = tuple(x[end - 299:end] for x in full)
        got = CASES[name](*tail)[-1]
        want = whole[end - 1]
        assert (math.isnan(got) and math.isnan(want)) or got == want, (name, end, got, want)


@pytest.mark.parametrize("name", list(CASES))
def test_no_value_reads_a_later_bar(name):
    full = _ohlcv(n=900, seed=9)
    whole = CASES[name](*full)
    for cut in (300, 512, 777):
        part = CASES[name](*(x[:cut] for x in full))
        a, b = part, whole[:cut]
        assert np.array_equal(np.isnan(a), np.isnan(b)), (name, cut)
        assert np.array_equal(a[~np.isnan(a)], b[~np.isnan(b)]), (name, cut)


def test_the_windows_are_what_they_say():
    c = np.arange(1.0, 11.0)
    assert np.isnan(pi.sma(c, 3)[1]) and pi.sma(c, 3)[2] == 2.0 and pi.sma(c, 3)[-1] == 9.0
    hi, lo = pi.donchian(c, c, 3)
    assert np.isnan(hi[2]) and hi[3] == 3.0 and lo[3] == 1.0     # the 3 bars BEFORE bar 3
    assert pi.roc(c, 2)[4] == pytest.approx(5.0 / 3.0 - 1.0)
    assert pi.efficiency(c, 5)[-1] == pytest.approx(1.0)          # a straight line
    zig = np.array([1.0, 2.0] * 10)
    assert pi.efficiency(zig, 4)[-1] == pytest.approx(0.0)         # back and forth
    assert pi.rsi(c, 5)[-1] == 100.0
    # bar 0 has no change: the first full window of 5 changes ends at bar 5
    assert np.isnan(pi.rsi(c, 5)[4]) and pi.rsi(c, 5)[5] == 100.0


def test_the_fixed_ema_is_an_ema():
    """Weights 2/(n+1) over a fixed window: on a long series it reads what the
    recursive EMA reads, to within its truncated tail."""
    import pandas as pd

    _o, _h, _lo, c, _v = _ohlcv(n=1000, seed=9)
    for n in (9, 21, 50):
        got = pi.ema_fixed(c, n)
        ref = pd.Series(c).ewm(span=n, adjust=False).mean().to_numpy()
        w = min(pi.MAX_LOOKBACK, 10 * n)
        assert np.isnan(got[w - 2]) and not np.isnan(got[w - 1])
        assert np.max(np.abs(got[400:] - ref[400:]) / ref[400:]) < 1e-3
