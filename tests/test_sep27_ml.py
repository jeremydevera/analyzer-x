"""Sep 27 ML — decision-tree strategies per coin and timeframe.

Operator, Sep 27, 2026: "instead of using confluence, can you review past 30
days and create best strategy for each coin and each timeframe use machine
learning on what's best strategy i want tp higher than sl"; chose 6 months to
learn / last 30 days to test, and decision trees.
"""
from __future__ import annotations

import gzip
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent


def _frame(n=900, tf="1h", seed=7, end=None, volume=True):
    rng = np.random.default_rng(seed)
    step = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}[tf]
    end = end or pd.Timestamp("2026-09-20 00:00")
    dates = pd.date_range(end=end, periods=n, freq=f"{step}s")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.004, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.004, n))
    v = rng.uniform(50, 150, n) if volume else np.zeros(n)
    return pd.DataFrame({"Date": dates, "Open": o, "High": h, "Low": lo,
                         "Close": c, "Volume": v})


def _arrays(df):
    ts = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    return (df["Open"].to_numpy(float), df["High"].to_numpy(float),
            df["Low"].to_numpy(float), df["Close"].to_numpy(float),
            df["Volume"].to_numpy(float), ts)


# ------------------------------------------------------------- the clues
def test_a_clue_never_reads_a_later_candle():
    from tradingagents import ml_features as mf

    o, h, lo, c, v, ts = _arrays(_frame(700))
    full = mf.features(o, h, lo, c, v, ts, [], "1h")
    assert full.shape == (700, len(mf.FEATURES))
    for k in (260, 480, 650):
        part = mf.features(o[:k], h[:k], lo[:k], c[:k], v[:k], ts[:k], [], "1h")
        assert np.array_equal(part, full[:k], equal_nan=True), k


def test_a_candle_reads_the_same_on_a_300_bar_cut_as_on_the_whole_history():
    """The stored row is measured on UNSEEN + 300 warm bars; the learner and
    its grade read the long array. Finite windows make them identical."""
    from tradingagents import ml_features as mf

    o, h, lo, c, v, ts = _arrays(_frame(1500))
    full = mf.features(o, h, lo, c, v, ts, [], "1h")
    w0 = 1500 - 500
    cut = mf.features(o[w0:], h[w0:], lo[w0:], c[w0:], v[w0:], ts[w0:], [], "1h")
    assert np.array_equal(cut[mf.MAX_WINDOW:], full[w0 + mf.MAX_WINDOW:], equal_nan=True)
    assert np.isfinite(cut[mf.MAX_WINDOW:]).all()


def test_a_contract_with_no_volume_abstains_on_the_volume_clue_only():
    from tradingagents import ml_features as mf

    o, h, lo, c, v, ts = _arrays(_frame(400, volume=False))
    x = mf.features(o, h, lo, c, v, ts, [], "1h")
    j = mf.FEATURES.index("vol_ratio_20")
    assert np.isnan(x[:, j]).all()
    assert not np.isinf(x).any()
    others = [i for i, n in enumerate(mf.FEATURES) if n != "vol_ratio_20"]
    assert np.isfinite(x[mf.MAX_WINDOW:, others]).all()


def test_the_funding_clue_is_the_rate_in_force_at_the_close():
    from tradingagents import ml_features as mf

    df = _frame(300)
    o, h, lo, c, v, ts = _arrays(df)
    mid = int(ts[150])
    fund = [{"settle_ms": int(ts[0]) - 1, "rate": 0.0001},
            {"settle_ms": mid, "rate": -0.0005}]
    x = mf.features(o, h, lo, c, v, ts, fund, "1h")
    j = mf.FEATURES.index("funding")
    assert x[100, j] == pytest.approx(0.0001)
    assert x[160, j] == pytest.approx(-0.0005)


# ------------------------------------------------------------- the trees
def test_the_trees_learn_a_planted_rule():
    from tradingagents import ml_trees as mt

    rng = np.random.default_rng(1)
    X = rng.uniform(0, 1, (3000, 6))
    y = (X[:, 3] > 0.5).astype(float)
    m = mt.fit(X[:2000], y[:2000])
    p = mt.predict(m, X[2000:])
    assert ((p > 0.5) == (y[2000:] > 0.5)).mean() > 0.95
    assert mt.importance(m, [f"f{i}" for i in range(6)])[0] == "f3"


def test_the_same_data_makes_the_same_model_and_json_changes_nothing():
    from tradingagents import ml_trees as mt

    rng = np.random.default_rng(2)
    X = rng.normal(size=(1500, 5))
    y = ((X[:, 0] + X[:, 1] * X[:, 2]) > 0).astype(float)
    a, b = mt.fit(X, y), mt.fit(X, y)
    assert json.dumps(a) == json.dumps(b)
    back = json.loads(json.dumps(a))
    assert np.array_equal(mt.predict(a, X), mt.predict(back, X))


def test_fit_refuses_rows_it_cannot_split():
    from tradingagents import ml_trees as mt

    X = np.ones((500, 3))
    X[0, 1] = np.inf
    with pytest.raises(ValueError, match="finite"):
        mt.fit(X, np.zeros(500))
