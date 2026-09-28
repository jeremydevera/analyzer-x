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


# ------------------------------------------------------------ the learner
def _ml_frame(days=260, tf="1h", seed=11, planted=True):
    """A walk with a PLANTED EDGE and no net drift: after three down closes
    in a row the next 6 bars drift up, after three up closes they drift down.
    Mean-reverting, so "always long" is not the answer — a model has to read
    the run to trade it."""
    from tradingagents import formula_learner as fl

    step = {"15m": 900, "1h": 3600, "1d": 86400}[tf]
    n = int(days * 86400 / step)
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.004, n)
    if planted:
        for i in range(3, n - 6):
            if r[i - 1] < 0 and r[i - 2] < 0 and r[i - 3] < 0:
                r[i:i + 6] += 0.0025
            elif r[i - 1] > 0 and r[i - 2] > 0 and r[i - 3] > 0:
                r[i:i + 6] -= 0.0025
    c = 100 * np.exp(np.cumsum(r))
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.002, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.002, n))
    dates = pd.date_range(end=pd.Timestamp("2026-09-20"), periods=n, freq=f"{step}s")
    df = pd.DataFrame({"Date": dates, "Open": o, "High": h, "Low": lo, "Close": c,
                       "Volume": rng.uniform(50, 150, n)})
    return fl.Frame(coin="TEST", tf=tf, df=df, fee=0.0002, slip=0.0001, liq=4.5)


def _now(frame):
    return int(frame.df["Date"].iloc[-1].timestamp() * 1000) + 3_600_000


def test_labels_are_the_engines_first_touch_and_stop_at_the_segment_end():
    from tradingagents import ml_learner as ml

    o = np.array([100, 100, 100, 100, 100, 100.0])
    h = np.array([100, 103, 100, 100, 101, 100.0])
    lo = np.array([100, 100, 98, 97, 100, 100.0])
    y = ml.labels(o, h, lo, 0, 6, tp=0.02, sl=0.01, side=1)
    assert y[0] == 1.0                        # bar 1 reaches 102 first
    assert y[1] == 0.0                        # bar 2 touches 99 first
    both = ml.labels(o, np.array([100, 103, 100, 100, 100, 100.0]),
                     np.array([100, 98, 100, 100, 100, 100.0]), 0, 6, 0.02, 0.01, 1)
    assert both[0] == 0.0                     # both in one bar: the stop
    y2 = ml.labels(o, h, lo, 0, 3, tp=0.02, sl=0.01, side=-1)
    assert np.isnan(y2[2])                    # unresolved before b: purged


def test_the_learner_finds_the_planted_edge_and_keeps_only_tp_above_sl():
    from tradingagents import ml_learner as ml

    fr = _ml_frame()
    rep = ml.MLLearner(fr, now_ms=_now(fr)).run()
    assert rep["formulas"], rep.get("why")
    for f in rep["formulas"]:
        assert f["name"].startswith("ml_TEST_1h_")
        assert f["tp"] > f["sl"]
        assert f["sl"] * 100 < 0.8 * 4.5
        lr = f["learned"]
        assert lr["validate"]["profit"] > 0
        assert lr["validate"]["winrate"] > lr["breakeven_winrate"]
        assert lr["unseen"]["chose"] is False
        assert lr["validate"]["wilson_lower"] > lr["breakeven_winrate"]
        assert "decision trees" in lr["describe"]
    # the edge is structural, so it persists into the 30 days nobody chose on
    assert sum(f["learned"]["unseen"]["profit"] for f in rep["formulas"]) > 0


@pytest.mark.parametrize("seed", (11, 12, 13))
def test_pure_noise_keeps_nothing(seed):
    """A random walk has nothing to learn: the best of ~80 tries on one month
    must not pass by luck (the plain floors kept 3 a seed here)."""
    from tradingagents import ml_learner as ml

    fr = _ml_frame(seed=seed, planted=False)
    rep = ml.MLLearner(fr, now_ms=_now(fr)).run()
    assert rep["formulas"] == [], [(f["tp"], f["sl"], f["learned"]["validate"])
                                   for f in rep["formulas"]]


def test_the_wilson_bound_is_the_textbook_one():
    from tradingagents import ml_learner as ml

    assert ml.wilson_lower(0, 0) == 0.0
    assert ml.wilson_lower(7, 10, z=1.645) == pytest.approx(44.17, abs=0.01)
    assert ml.wilson_lower(10, 10, z=1.645) == pytest.approx(78.70, abs=0.01)
    # 90% shared across the GRADE_TOP validate tries, one-sided
    assert ml.GRADE_TOP == 12 and ml.WILSON_Z == pytest.approx(2.394, abs=0.001)


def test_no_choice_can_see_the_unseen_period():
    """Rewrite every candle from the unseen period on: the same models, the
    same TP/SL and the same validate numbers. Only the grade may differ."""
    from tradingagents import formula_learner as fl, ml_learner as ml

    fr = _ml_frame()
    a = ml.MLLearner(fr, now_ms=_now(fr))
    df = fr.df.copy()
    rng = np.random.default_rng(99)
    u = a.u0 + (len(df) - a.n)
    c = df["Close"].to_numpy().copy()
    c[u:] = c[u - 1] * np.exp(np.cumsum(rng.normal(0, 0.01, len(c) - u)))
    df.loc[u:, "Close"] = c[u:]
    df.loc[u:, "Open"] = np.concatenate([[c[u - 1]], c[u:-1]])
    df.loc[u:, "High"] = np.maximum(df.loc[u:, "Open"], c[u:]) * 1.003
    df.loc[u:, "Low"] = np.minimum(df.loc[u:, "Open"], c[u:]) * 0.997
    b = ml.MLLearner(fl.Frame(**{**fr.__dict__, "df": df}), now_ms=_now(fr))

    def chosen(rep):
        return [(f["tp"], f["sl"], f["sides"], f["q"], f["thr"],
                 json.dumps(f["models"]), f["learned"]["validate"])
                for f in rep["formulas"]]

    ra, rb = a.run(), b.run()
    assert ra["formulas"], "the fixture chose nothing, so this proved nothing"
    assert chosen(ra) == chosen(rb)


def test_too_little_history_says_so_instead_of_guessing():
    from tradingagents import ml_learner as ml

    fr = _ml_frame(days=80)
    rep = ml.MLLearner(fr, now_ms=_now(fr)).run()
    assert rep["formulas"] == [] and "not enough history" in rep["why"]


def test_a_side_whose_target_never_comes_first_is_skipped_not_a_crash():
    from tradingagents import ml_learner as ml

    fr = _ml_frame()
    lr = ml.MLLearner(fr, now_ms=_now(fr))
    y = np.zeros(lr.n)
    assert lr._fit_side(y) is None


def test_daily_candles_learn_from_two_years():
    from tradingagents import ml_learner as ml

    assert ml.LEARN_DAYS["1d"] == 720
    assert all(ml.LEARN_DAYS[t] == 180 for t in ("15m", "30m", "1h", "4h"))


def test_the_stored_cut_trades_what_the_grade_graded():
    """The stored UNSEEN grade is what production repeats: the model looked up
    by name through auto_trader._dirs_for_backtest (the call every backtest
    and the GitHub row measurement makes) on the stored cut, then the real
    engine on that cut, minute-exact."""
    import tradingagents.auto_trader as at
    from tradingagents import formula_learner as fl, ml_learner as ml, signals_ml as sml

    fr = _ml_frame()
    lr = ml.MLLearner(fr, now_ms=_now(fr))
    rep = lr.run()
    assert rep["formulas"], rep.get("why")
    f = rep["formulas"][0]
    w0 = lr.u0 - lr.WARM
    o, h, lo, c, v, ts = lr.f.arrays()
    sml.register({f["name"]: f})
    try:
        d = at._dirs_for_backtest(f"{f['name']}_bt_{f['tf']}", list(h[w0:]),
                                  list(lo[w0:]), list(c[w0:]), opens=list(o[w0:]),
                                  volume=list(v[w0:]), ts=[int(x) for x in ts[w0:]],
                                  funding=lr.f.funding)
    finally:
        sml.reload()
    assert any(d), "the model traded nothing on the stored cut"
    sub = lr.f.df.iloc[w0:].reset_index(drop=True)
    g = fl.engine_run(lr.f, lr.tf, sub, d, f["sl"], f["tp"], lr.u0 - w0, lr.f.fine)
    u = f["learned"]["unseen"]
    assert (g["trades"], g["wins"], round(g["profit"], 2)) ==         (u["trades"], u["wins"], round(u["profit"], 2))


def test_daily_candles_with_too_few_labelled_rows_say_so():
    from tradingagents import ml_learner as ml

    fr = _ml_frame(days=500, tf="1d")
    rep = ml.MLLearner(fr, now_ms=_now(fr)).run()
    assert rep["formulas"] == []
    assert rep["why"].startswith("not enough history"), rep


def test_it_is_fast_enough_to_learn_the_market():
    from tradingagents import ml_learner as ml

    fr = _ml_frame(days=260, tf="1h")
    t0 = time.time()
    ml.MLLearner(fr, now_ms=_now(fr)).run()
    assert time.time() - t0 < 120
