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


# ------------------------------------------------------------ the registry
def _toy_spec(name="ml_TEST_1h_1", sides="both"):
    from tradingagents import ml_features as mf, ml_trees as mt

    df = _frame(900)
    o, h, lo, c, v, ts = _arrays(df)
    X = mf.features(o, h, lo, c, v, ts, [], "1h")
    ok = np.isfinite(X).all(axis=1)
    fwd = np.concatenate([c[3:] / c[:-3] - 1, [0, 0, 0]])
    models, thr = {}, {}
    for side, sgn in (("long", 1), ("short", -1)):
        y = (sgn * fwd > 0.004).astype(float)
        m = mt.fit(X[ok], y[ok])
        models[side] = m
        thr[side] = float(np.quantile(mt.predict(m, X[ok]), 0.9))
    if sides != "both":
        models, thr = {sides: models[sides]}, {sides: thr[sides]}
    return {"name": name, "coin": "TEST", "tf": "1h", "tp": 0.02, "sl": 0.01,
            "sides": sides, "q": 0.9, "thr": thr, "models": models,
            "features": mf.VERSION}


def test_a_model_reads_only_closed_candles_and_the_same_on_the_stored_cut():
    from tradingagents import signals_ml as sml

    spec = _toy_spec()
    o, h, lo, c, v, ts = _arrays(_frame(900))
    full = sml.dirs_for(spec, o, h, lo, c, v, ts)
    assert any(full) and set(full) <= {-1, 0, 1}
    part = sml.dirs_for(spec, o[:600], h[:600], lo[:600], c[:600], v[:600], ts[:600])
    assert part == full[:600]
    w0 = 400                      # the stored row's cut: 300 warm bars and more
    cut = sml.dirs_for(spec, o[w0:], h[w0:], lo[w0:], c[w0:], v[w0:], ts[w0:])
    assert cut[300:] == full[w0 + 300:]


def test_one_side_models_trade_one_side():
    from tradingagents import signals_ml as sml

    o, h, lo, c, v, ts = _arrays(_frame(900))
    assert set(sml.dirs_for(_toy_spec(sides="long"), o, h, lo, c, v, ts)) <= {0, 1}
    assert set(sml.dirs_for(_toy_spec(sides="short"), o, h, lo, c, v, ts)) <= {-1, 0}


def test_an_ml_key_reads_as_its_own_model_everywhere(monkeypatch):
    import tradingagents.auto_trader as at
    from tradingagents import signals_ml as sml
    from tradingagents.local_history import _sig_of

    sml.register({"ml_TEST_1h_1": _toy_spec()})
    try:
        for key in ("ml_TEST_1h_1", "ml_TEST_1h_1_1h_sl1tp2", "ml_TEST_1h_1_bt_1h"):
            assert _sig_of(key) == "ml_TEST_1h_1", key
            assert sml.spec_for(key)["name"] == "ml_TEST_1h_1"
        assert _sig_of("ml_NEWCOIN_4h_2_4h_sl10tp30") == "ml_NEWCOIN_4h_2"
        assert sml.spec_for("ml_NOPE_1h_9") is None
        o, h, lo, c, v, ts = _arrays(_frame(900))
        want = sml.dirs_for(_toy_spec(), o, h, lo, c, v, ts)
        got = at._dirs_for_backtest("ml_TEST_1h_1_bt_1h", list(h), list(lo), list(c),
                                    opens=list(o), volume=list(v), ts=list(ts), funding=[])
        assert list(got) == want
        assert at.signal_for("ml_TEST_1h_1_1h_sl1tp2", list(h), list(lo), list(c),
                             opens=list(o), volume=list(v), ts=list(ts)) == want[-1]
        assert at._dirs_for_backtest("ml_NOPE_1h_9_bt_1h", list(h), list(lo), list(c),
                                     opens=list(o)) == [0] * len(c)
    finally:
        sml.reload()


def test_a_running_process_sees_models_collected_after_it_started(tmp_path, monkeypatch):
    import os

    from tradingagents import signals_ml as sml

    f = tmp_path / "sep27_ml.json.gz"
    monkeypatch.setattr(sml, "MODEL_FILE", f)
    sml.reload()
    assert sml.spec_for("ml_TEST_1h_1") is None
    n = sml.write_file({"ml_TEST_1h_1": _toy_spec()}, run_id=1)
    assert n == f.stat().st_size > 0
    os.utime(f, ns=(time.time_ns(), time.time_ns() + 10**9))
    assert sml.spec_for("ml_TEST_1h_1")["tf"] == "1h"
    with gzip.open(f, "rt", encoding="utf-8") as fh:
        assert "ml_TEST_1h_1" in json.load(fh)["models"]
    sml.reload()


def test_the_model_file_refuses_to_grow_past_its_ceiling(tmp_path, monkeypatch):
    from tradingagents import signals_ml as sml

    f = tmp_path / "sep27_ml.json.gz"
    monkeypatch.setattr(sml, "MODEL_FILE", f)
    sml.reload()
    sml.write_file({"ml_TEST_1h_1": _toy_spec()}, run_id=1)
    first = f.read_bytes()
    with pytest.raises(RuntimeError, match="MB"):
        sml.write_file({"ml_TEST_1h_1": _toy_spec(), "ml_TEST_1h_2": _toy_spec("ml_TEST_1h_2")},
                       run_id=2, max_bytes=10)
    assert f.read_bytes() == first
    assert not f.with_suffix(".tmp").exists()
    assert sml.read_file()["ml_TEST_1h_1"]["name"] == "ml_TEST_1h_1"
    sml.reload()


def test_every_learned_family_keeps_tp_above_sl_on_the_update_button():
    from tradingagents import backtest_report as br

    assert br.LEARNED_FAMILIES == ("lx_", "ml_")
    assert br.is_learned("ml_BTC_1h_1") and br.is_learned("lx_BTC_1h_1")
    assert not br.is_learned("keltner")
    src = (REPO / "tradingagents/market_sweep.py").read_text(encoding="utf-8")
    assert src.count("br.is_learned(") >= 2
    assert 'startswith("lx_")' not in src
