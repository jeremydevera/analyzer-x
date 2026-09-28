"""Sep 27 ML — decision-tree strategies per coin and timeframe.

Operator, Sep 27, 2026: "instead of using confluence, can you review past 30
days and create best strategy for each coin and each timeframe use machine
learning on what's best strategy i want tp higher than sl"; chose 6 months to
learn / last 30 days to test, and decision trees.
"""
from __future__ import annotations

import gzip
import json
import os
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


def test_there_is_no_funding_clue_and_the_clue_set_is_version_2():
    """F1 (Sep 28, 2026 review): the live runner calls signal_for without a
    funding list, so a funding clue read the real rate in the grid and 0 live."""
    from tradingagents import ml_features as mf

    assert "funding" not in mf.FEATURES
    assert mf.VERSION == 2
    o, h, lo, c, v, ts = _arrays(_frame(300))
    fund = [{"settle_ms": int(ts[0]) - 1, "rate": 0.0001},
            {"settle_ms": int(ts[150]), "rate": -0.0005}]
    assert np.array_equal(mf.features(o, h, lo, c, v, ts, fund, "1h"),
                          mf.features(o, h, lo, c, v, ts, [], "1h"), equal_nan=True)


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


def test_a_model_reads_the_same_with_or_without_funding():
    """F1: the grid passes the coin's funding, the live runner passes none —
    the directions must not differ by a single bar."""
    from tradingagents import signals_ml as sml

    spec = _toy_spec()
    o, h, lo, c, v, ts = _arrays(_frame(900))
    fund = [{"settle_ms": int(ts[k]), "rate": r}
            for k, r in ((0, 0.0001), (300, -0.0007), (600, 0.0012))]
    with_f = sml.dirs_for(spec, o, h, lo, c, v, ts, fund)
    assert any(with_f)
    assert with_f == sml.dirs_for(spec, o, h, lo, c, v, ts, None)


def test_a_model_saved_with_another_clue_set_abstains_everywhere():
    """F7: a model fitted on clue version 1 (which had a funding column)
    reads column j as a different clue on version 2 — it must trade nothing."""
    from tradingagents import signals_ml as sml

    o, h, lo, c, v, ts = _arrays(_frame(900))
    old = {**_toy_spec(), "features": 1}
    assert sml.dirs_for(old, o, h, lo, c, v, ts) == [0] * 900
    wide = _toy_spec()
    wide["models"] = {k: {**m, "nf": m["nf"] + 1} for k, m in wide["models"].items()}
    assert sml.dirs_for(wide, o, h, lo, c, v, ts) == [0] * 900
    assert any(sml.dirs_for(_toy_spec(), o, h, lo, c, v, ts))


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


def test_a_contract_with_no_volume_names_the_missing_clue():
    """F8: a contract whose volume is always zero has no vol_ratio_20 on any
    candle. That used to read "not enough history: 0 labelled training
    candles" — true and useless. The pair keeps nothing and says why."""
    from tradingagents import formula_learner as fl, ml_learner as ml

    fr = _ml_frame()
    df = fr.df.copy()
    df["Volume"] = 0.0
    fr = fl.Frame(**{**fr.__dict__, "df": df})
    rep = ml.MLLearner(fr, now_ms=_now(fr)).run()
    assert rep["formulas"] == []
    assert rep["missing_clues"] == ["vol_ratio_20"]
    assert rep["why"] == ("the vol_ratio_20 clue is missing on every candle "
                          "(no volume on this contract?)")
    # a normal frame names nothing
    ok = ml.MLLearner(_ml_frame(), now_ms=_now(_ml_frame()))
    assert ok.missing_clues() == []


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


# ------------------------------------------------------------- the group
def test_each_learned_group_holds_only_its_own_family():
    import sqlite3

    from tradingagents import backtest_report as br, rows_index as ri

    names = list(br.SIGNALS) + ["lx_BTC_1h_1", "ml_BTC_1h_1", "ml_KKRSTOCK_15m_2"]
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE rows (signal TEXT)")
    con.executemany("INSERT INTO rows VALUES (?)", [(s,) for s in names])
    for group, terms in ri.GROUP_TERMS.items():
        sql = {r[0] for r in con.execute(f"SELECT signal FROM rows WHERE {terms}")}
        assert sql == {s for s in names if ri.in_group(s, group)}, group
    assert {s for s in names if ri.in_group(s, "sep27ml")} == {"ml_BTC_1h_1", "ml_KKRSTOCK_15m_2"}
    assert {s for s in names if ri.in_group(s, "sep25")} == {"lx_BTC_1h_1"}
    assert not [s for s in names if ri.in_group(s, "classic") and br.is_learned(s)]
    assert ri.GROUPS["sep27ml"]["label"] == "Sep 27 ML"
    assert ri.group_index("sep27ml", "profit") == "rows_ml_profit"


def test_the_screen_offers_sep27_ml_by_its_name():
    src = (REPO / "webapp/src/components/backtest/StrategiesPanel.tsx").read_text(encoding="utf-8")
    assert 'sep27ml: "Sep 27 ML"' in src
    assert '<option value="sep27ml">{GROUP_LABEL.sep27ml}</option>' in src
    api = (REPO / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    assert api.count('"sep25" | "sep27ml"') == 2


# ------------------------------------------------------------ the collect
@pytest.fixture
def v2ml(tmp_path, monkeypatch):
    from tradingagents import (
        learn_collect as lc,
        market_sweep as msw,
        rows_index as ri,
        signals_learned as sl_,
        signals_ml as sml,
    )

    monkeypatch.setattr(msw, "FINE_TF", "1m")
    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    monkeypatch.setattr(sl_, "LEARNED_FILE", tmp_path / "sep25.json")
    monkeypatch.setattr(sml, "MODEL_FILE", tmp_path / "sep27_ml.json.gz")
    monkeypatch.setattr(lc, "REPORT_FILE", tmp_path / "sep25_report.json")
    monkeypatch.setattr(lc, "ML_REPORT_FILE", tmp_path / "sep27_ml_report.json")
    db = tmp_path / "rows.db"
    monkeypatch.setattr(ri, "DB_PATH", db)
    ri._ready.discard(str(db))
    ri.forget_indexes()
    ri.ensure()
    sl_.reload()
    sml.reload()
    yield msw, ri, sml, lc
    sl_.reload()
    sml.reload()


def _mlrow(coin, tf, signal, sl=1.0, tp=2.0):
    return {"coin": coin, "tf": tf, "signal": signal, "th": 0.0, "sl": sl, "tp": tp,
            "sizing": "flat", "trades": 12, "wins": 8, "losses": 4, "winrate": 66.67,
            "profit": 5.0, "monthly": {}, "res": "1m", "last_ms": 1}


def test_an_ml_run_lands_its_rows_and_models_and_leaves_lx_alone(v2ml):
    msw, ri, sml, lc = v2ml
    grid = [_mlrow("BTC", "1h", "keltner"), _mlrow("BTC", "1h", "lx_BTC_1h_1")]
    msw.save_pair_rows("BTC", "1h", grid + [_mlrow("BTC", "1h", "ml_BTC_1h_2")])
    msw.save_states("BTC", "1h", {"__cloud__": True, "__last_ms__": 123})
    sml.write_file({"ml_BTC_1h_2": {"coin": "BTC", "tf": "1h"},
                    "ml_ETH_4h_1": {"coin": "ETH", "tf": "4h"}})
    new = {"ml_BTC_1h_1": {"name": "ml_BTC_1h_1", "coin": "BTC", "tf": "1h",
                           "learned": {"validate": {"profit": 3.0},
                                       "unseen": {"profit": -1.0}}}}
    report = [{"coin": "BTC", "tf": "1h", "kept": ["ml_BTC_1h_1"]},
              {"coin": "ETH", "tf": "4h", "error": "HTTPError: 502"}]
    got = lc.land(new, report, {("BTC", "1h"): [_mlrow("BTC", "1h", "ml_BTC_1h_1", 1.0, 3.0)]},
                  run_id=7, family=lc.ML)
    sigs = sorted(r["signal"] for r in msw.pair_rows("BTC", "1h"))
    assert sigs == ["keltner", "lx_BTC_1h_1", "ml_BTC_1h_1"]
    assert msw.load_states("BTC", "1h").get("__last_ms__") == 123
    assert set(sml.read_file()) == {"ml_BTC_1h_1", "ml_ETH_4h_1"}
    # a model that lost on the unseen month is KEPT: the test never chooses
    assert "ml_BTC_1h_1" in sml.read_file()
    rep = json.loads(lc.ML_REPORT_FILE.read_text(encoding="utf-8"))["report"]
    assert {(e["coin"], e["tf"]) for e in rep} == {("BTC", "1h"), ("ETH", "4h")}
    assert got["rows"] == 1


def test_an_ml_collect_refuses_a_model_file_past_its_ceiling(v2ml, monkeypatch):
    msw, ri, sml, lc = v2ml
    monkeypatch.setattr(lc, "ML", lc.Family(**{**lc.ML.__dict__, "max_mb": 0.000001}))
    with pytest.raises(RuntimeError, match="MB"):
        lc.land({"ml_BTC_1h_1": {"coin": "BTC", "tf": "1h"}},
                [{"coin": "BTC", "tf": "1h"}], {}, family=lc.ML)


def test_an_ml_collect_drops_and_names_rows_no_report_accounts_for(v2ml):
    """F3: a GitHub machine stopped mid-coin can leave rows for a timeframe
    whose report line never landed. Sep 27 ML drops those rows and names the
    pair; it does not refuse the whole collect (Sep 25 Strat still does —
    test_landing_refuses_rows_it_cannot_account_for)."""
    msw, ri, sml, lc = v2ml
    new = {"ml_BTC_1h_1": {"name": "ml_BTC_1h_1", "coin": "BTC", "tf": "1h",
                           "learned": {"validate": {"profit": 3.0}}}}
    report = [{"coin": "BTC", "tf": "1h", "kept": ["ml_BTC_1h_1"]}]
    rows = {("BTC", "1h"): [_mlrow("BTC", "1h", "ml_BTC_1h_1", 1.0, 3.0)],
            ("BTC", "4h"): [_mlrow("BTC", "4h", "ml_BTC_4h_1", 1.0, 3.0)]}
    got = lc.land(new, report, rows, run_id=8, family=lc.ML)
    assert got["stray"] == ["BTC 4h"]
    assert got["rows"] == 1
    assert [r["signal"] for r in msw.pair_rows("BTC", "1h")] == ["ml_BTC_1h_1"]
    assert msw.pair_rows("BTC", "4h") == []
    assert set(sml.read_file()) == {"ml_BTC_1h_1"}
    # and Sep 25 Strat still refuses the same shape
    with pytest.raises(ValueError, match="does not account for"):
        lc.land({}, [{"coin": "BTC", "tf": "1h"}],
                {("BTC", "4h"): [_mlrow("BTC", "4h", "lx_BTC_4h_1", 1.0, 3.0)]},
                family=lc.LX)


# -------------------------------------------- a row this PC cannot rebuild
def test_an_ml_row_without_200_bars_before_its_window_is_named():
    from tradingagents import market_sweep as msw

    assert msw.ml_history_short("keltner", "1h", 0) is None
    assert msw.ml_history_short("lx_BTC_1h_1", "1h", 0) is None
    assert msw.ml_history_short("ml_BTC_1h_1", "1h", 200) is None
    assert msw.ml_history_short("ml_BTC_1h_1", "1h", 57) == (
        "this PC holds only 57 1h bars before the window; an ml_ model needs "
        "200 — the stored row came from GitHub's longer candles")


def test_the_trade_log_refuses_an_ml_row_it_cannot_rebuild(monkeypatch):
    """F5: the stored row is 100 bars; this PC holds 150, so only 50 bars of
    clues come before the window. The log says so instead of replaying a
    quieter strategy under the row's name."""
    from tradingagents import market_sweep as msw

    df = _frame(150, "1h")
    row = {"signal": "ml_TEST_1h_1", "th": 0.0, "sl": 1.0, "tp": 2.0,
           "sizing": "flat", "bars": 100, "last_ms": 0}
    monkeypatch.setattr(msw, "cached_candles", lambda *a, **k: df)
    monkeypatch.setattr(msw, "pair_rows", lambda *a, **k: [row])
    monkeypatch.setattr(msw, "load_states", lambda *a, **k: {})
    monkeypatch.setattr(msw, "load_costs", lambda *a, **k: pytest.fail(
        "the refusal must come before any cost read"))
    got = msw.trades_for("TEST", "1h", signal="ml_TEST_1h_1", th=0, sl=1.0,
                         tp=2.0, sizing="flat")
    assert got["log"] == []
    assert got["why"].startswith("this PC holds only 50 1h bars before the window")


def test_the_update_button_skips_an_ml_row_it_cannot_rebuild(monkeypatch, tmp_path):
    """F5: UPDATE measures a named signal with merge=True over this PC's
    frame from its first bar — no bars of clues before the window. The ml_
    row is skipped and named, and nothing is written over the stored one."""
    import tradingagents.auto_trader as at
    from tradingagents import market_sweep as msw
    from tradingagents.dataflows import mexc_futures as fx

    df = _frame(700, "1h")
    monkeypatch.setattr(msw, "FINE_TF", "")
    monkeypatch.setattr(msw, "refresh_candles", lambda *a, **k: (df, 0, "cache"))
    monkeypatch.setattr(fx, "funding_history", lambda *a, **k: [])
    monkeypatch.setattr(fx, "liquidation_move_pct", lambda *a, **k: 4.5)
    monkeypatch.setattr(fx, "book_cost", lambda *a, **k: {"slippage": 0.0001})
    monkeypatch.setattr(at, "taker_fee", lambda *a, **k: 0.0004)
    monkeypatch.setattr(msw, "charge_cost", lambda *a, **k: (0.0001, []))
    monkeypatch.setattr(msw, "save_costs", lambda *a, **k: None)
    monkeypatch.setattr(msw, "deployed_combos", lambda *a, **k: set())
    monkeypatch.setattr(msw, "load_states", lambda *a, **k: {})
    monkeypatch.setattr(msw, "worker_write", lambda *a, **k: None)
    wrote = []
    for name in ("save_states", "save_pair_rows", "merge_pair_rows"):
        monkeypatch.setattr(msw, name, lambda *a, _n=name, **k: wrote.append(_n))
    got = msw.run_pair("TEST_USDT", "1h", signals=["ml_TEST_1h_1"], merge=True)
    assert got["rows"] == [] and got["skipped"] == ["ml_TEST_1h_1"]
    assert got["why"].startswith("this PC holds only 0 1h bars before the window")
    assert wrote == []


def test_the_update_job_prints_why_an_ml_row_was_not_measured():
    src = (REPO / "tradingagents/db_jobs.py").read_text(encoding="utf-8")
    assert "not measured: {res.get('why')}" in src


def test_the_ml_workflow_artifacts_are_the_ones_the_collect_downloads():
    from tradingagents import learn_collect as lc

    wf = (REPO / ".github/workflows/ml.yml").read_text(encoding="utf-8")
    for pat in lc.ML.artifacts:
        assert pat.rstrip("*") in wf


# ------------------------------------------------------------ the machines
def test_an_ml_measurement_writes_rows_only_and_only_tp_above_sl(monkeypatch):
    import importlib.util
    import io
    import sys

    from tradingagents import signals_ml as sml

    monkeypatch.setenv("RES", "1m")
    monkeypatch.setenv("MODE", "full")
    spec = importlib.util.spec_from_file_location(
        "sweep_shard_ml", REPO / ".github/scripts/sweep_shard.py")
    ss = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "sweep_shard_ml", ss)
    spec.loader.exec_module(ss)
    now = pd.Timestamp.now("UTC").tz_localize(None).floor("h")
    df = _frame(1100, "1h", end=now)
    sml.register({"ml_TEST_1h_1": _toy_spec()})
    wrote = []
    monkeypatch.setattr(ss, "write_state", lambda *a, **k: wrote.append(1))
    monkeypatch.setattr(ss, "post_pair", lambda *a, **k: wrote.append(2))
    out = io.StringIO()
    try:
        ss.run_pair("TEST_USDT", "1h", out, signals=["ml_TEST_1h_1"],
                    learned={"fee": 0.0004, "liq": 4.5, "fund": [], "slip": 0.0001,
                             "df": df, "fine": None})
    finally:
        sml.reload()
    rows = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    assert rows and wrote == []
    assert not [r for r in rows if r.get("pair_done")]
    assert all(r["tp"] > r["sl"] and r["sl"] < 0.8 * 4.5 for r in rows)
    assert {r["signal"] for r in rows} == {"ml_TEST_1h_1"}


def test_the_ml_machines_claim_one_coin_at_a_time_and_hand_over_what_they_finished():
    src = (REPO / ".github/scripts/ml_shard.py").read_text(encoding="utf-8")
    assert "stream = ss.coin_stream(coins, t0)" in src
    assert "list(ss.coin_stream" not in src
    assert "ml.learn_pair(" in src and "sml.register(" in src
    wf = (REPO / ".github/workflows/ml.yml").read_text(encoding="utf-8")
    assert "python .github/scripts/ml_shard.py" in wf
    assert wf.count("if: always()") >= 2
    assert "ml-rows-" in wf and "ml-models-" in wf


@pytest.fixture
def ml_shard(monkeypatch):
    """.github/scripts/ml_shard.py loaded as a module, with the environment,
    sys.path and sys.modules it touches restored afterwards."""
    import importlib.util
    import sys

    for k in ("RES", "MODE", "DAYS"):
        monkeypatch.setenv(k, os.environ.get(k, ""))
    monkeypatch.setattr(sys, "path", list(sys.path))
    before = {k: sys.modules.pop(k, None) for k in ("sweep_shard", "learn_shard")}
    spec = importlib.util.spec_from_file_location(
        "ml_shard_test", REPO / ".github/scripts/ml_shard.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "ml_shard_test", mod)
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        for k, v in before.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _line(signal, tp, sl, **kw):
    return json.dumps({"coin": "TEST", "tf": "1h", "signal": signal,
                       "tp": tp, "sl": sl, "res": "1m", **kw})


def test_an_ml_model_stores_one_row_at_its_own_tp_and_sl(ml_shard):
    """F2: run_pair walks every TP > SL pair; only the row at the model's
    own pair is the model the learner kept."""
    kept = [{"name": "ml_TEST_1h_1", "tp": 0.02, "sl": 0.01},
            {"name": "ml_TEST_1h_2", "tp": 0.012, "sl": 0.006}]
    lines = [_line("ml_TEST_1h_1", 2.0, 1.0),          # its own pair: kept
             _line("ml_TEST_1h_1", 3.0, 1.0),          # another TP: dropped
             _line("ml_TEST_1h_1", 2.0, 1.5),          # another SL: dropped
             _line("ml_TEST_1h_2", 2.0, 1.0),          # model 1's pair: dropped
             _line("ml_TEST_1h_2", 1.2, 0.6),          # its own pair: kept
             json.dumps({"coin": "TEST", "tf": "1h", "pair_done": True}), ""]
    got = [json.loads(x) for x in ml_shard.own_rows(lines, kept)]
    assert [(r["signal"], r["tp"], r["sl"]) for r in got] == [
        ("ml_TEST_1h_1", 2.0, 1.0), ("ml_TEST_1h_2", 1.2, 0.6)]
    assert all(x.endswith("\n") for x in ml_shard.own_rows(lines, kept))


def test_the_ml_run_measures_exactly_the_learners_30_days(ml_shard):
    """F4: DAYS is pinned before sweep_shard reads it at import."""
    src = (REPO / ".github/scripts/ml_shard.py").read_text(encoding="utf-8")
    assert src.index('os.environ["DAYS"] = "30"') < src.index("import sweep_shard")
    assert ml_shard.ss.DAYS == 30
    from tradingagents import ml_learner as ml

    assert ml.UNSEEN_DAYS == 30


def test_a_machine_stopped_mid_coin_has_handed_over_every_finished_timeframe(
        ml_shard, monkeypatch):
    """F3 + F2 through ml_coin itself: the models and report are saved after
    EVERY timeframe, and only the model's own row reaches the output."""
    import io

    m = ml_shard
    df = _frame(400, "1h")
    monkeypatch.setattr(m, "TFS", ["1h", "4h"])
    monkeypatch.setattr(m.at, "taker_fee", lambda *a, **k: 0.0004)
    monkeypatch.setattr(m.fx, "liquidation_move_pct", lambda *a, **k: 4.5)
    monkeypatch.setattr(m.fx, "funding_history", lambda *a, **k: [])
    monkeypatch.setattr(m.fx, "book_cost", lambda *a, **k: {"slippage": 0.0001})
    monkeypatch.setattr(m.fx, "klines", lambda *a, **k: df)
    monkeypatch.setattr(m.at, "_closed_bars", lambda d, bs: d)
    monkeypatch.setattr(m, "charged", lambda *a: (0.0001, []))
    spec = {"name": "ml_TEST_1h_1", "coin": "TEST", "tf": "1h",
            "tp": 0.02, "sl": 0.01}

    def learn(frame, **kw):
        if frame.tf == "4h":
            raise KeyboardInterrupt           # the machine is stopped here
        return {"coin": "TEST", "tf": frame.tf, "formulas": [dict(spec)]}

    monkeypatch.setattr(m.ml, "learn_pair", learn)
    monkeypatch.setattr(m.sml, "register", lambda *a, **k: None)

    def run_pair(sym, tf, out, **kw):
        out.write(_line("ml_TEST_1h_1", 2.0, 1.0) + "\n")
        out.write(_line("ml_TEST_1h_1", 3.0, 1.0) + "\n")
        return 2

    monkeypatch.setattr(m.ss, "run_pair", run_pair)
    saved = []
    monkeypatch.setattr(m, "_save", lambda f, r: saved.append(
        (sorted(f), [(e["tf"], e.get("rows")) for e in r])))
    out = io.StringIO()
    formulas, report = {}, []
    with pytest.raises(KeyboardInterrupt):
        m.ml_coin("TEST_USDT", out, formulas, report, {})
    assert saved == [(["ml_TEST_1h_1"], [("1h", 1)])]
    assert [json.loads(x)["tp"] for x in out.getvalue().splitlines()] == [2.0]


# ------------------------------------------ Task 8 harddev, items (a)-(e)
def test_an_update_that_measured_nothing_never_says_already_current(monkeypatch):
    """(a): run_pair skipped the only rule it was given, wrote nothing, and so
    the watermark did not move. That is not "already current" — the job says
    only why it was not measured, and touches no index."""
    from tradingagents import db_jobs as dj, market_sweep as msw
    from tradingagents import notifications as nt, pending_ledger as pl
    from tradingagents import rows_index as ri

    why = ("this PC holds only 0 1h bars before the window; an ml_ model "
           "needs 200 — the stored row came from GitHub's longer candles")
    wrote = []
    monkeypatch.setattr(dj, "_write", lambda path, payload: wrote.append(payload))
    monkeypatch.setattr(msw, "pair_watermark", lambda *a, **k: 1_758_000_000_000)
    monkeypatch.setattr(msw, "run_pair", lambda *a, **k: {
        "coin": "TEST", "tf": "1h", "rows": [], "thin": 0, "why": why,
        "skipped": ["ml_TEST_1h_1"], "bars": 700, "days": 29})
    monkeypatch.setattr(ri, "index_pair", lambda *a, **k: pytest.fail(
        "nothing was measured, so nothing may be re-filed"))
    monkeypatch.setattr(nt, "record", lambda *a, **k: None)
    monkeypatch.setattr(pl, "clear", lambda *a, **k: 0)
    dj._run_pairbt({"coin": "TEST", "tf": "1h", "signal": "ml_TEST_1h_1",
                    "days": 29}, kind="pairbt")
    last = wrote[-1]
    assert last["running"] is False
    assert last["already_current"] is False
    assert last["not_measured"] == why
    assert "already current" not in last["note"]
    assert last["note"] == f"TEST 1h · ml_TEST_1h_1: not measured: {why}"
    assert last["measured_through"] == ""


def test_the_row_update_sentence_says_not_measured(tmp_path):
    """(a) on screen: `rowUpdateSentence` must not print "100% done" over a
    job that measured nothing."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    src = (REPO / "webapp/src/lib/rowUpdate.ts").as_uri()
    job = {"pair": "TEST 1h", "signal": "ml_TEST_1h_1", "rows": 0,
           "not_measured": "this PC holds only 0 1h bars before the window"}
    probe = tmp_path / "probe.mjs"
    probe.write_text(
        f'import {{ rowUpdateSentence }} from "{src}";\n'
        f"console.log(JSON.stringify(rowUpdateSentence({json.dumps(job)}, "
        f'"Sep 28, 2026 1:05am")));\n', encoding="utf-8")
    got = subprocess.run([node, str(probe)], capture_output=True, text=True,
                         encoding="utf-8")
    assert got.returncode == 0, got.stderr
    said = json.loads(got.stdout.strip().splitlines()[-1])
    assert said["text"] == ("Not measured at Sep 28, 2026 1:05am: this PC holds "
                            "only 0 1h bars before the window")
    assert said["bad"] is True and "100% done" not in said["text"]


def test_the_ml_workflow_has_no_days_box_that_does_nothing():
    """(b): ml_shard pins DAYS=30; a `days` input would be a false label."""
    wf = (REPO / ".github/workflows/ml.yml").read_text(encoding="utf-8")
    inputs = wf.split("inputs:", 1)[1].split("permissions:", 1)[0]
    assert "\n      days:" not in inputs
    assert "inputs.days" not in wf and "DAYS:" not in wf
    for kept in ("shards:", "timeframes:", "coin_list:", "base:"):
        assert f"\n      {kept}" in inputs, kept


def test_the_fingerprint_names_only_the_rules_that_were_measured(monkeypatch):
    """(c): keltner measured, ml_TEST_1h_1 skipped (no 200 bars before the
    window) — the state says one rule, never two."""
    import tradingagents.auto_trader as at
    from tradingagents import market_sweep as msw
    from tradingagents.dataflows import mexc_futures as fx

    df = _frame(700, "1h")
    monkeypatch.setattr(msw, "FINE_TF", "")
    monkeypatch.setattr(msw, "refresh_candles", lambda *a, **k: (df, 0, "cache"))
    monkeypatch.setattr(fx, "funding_history", lambda *a, **k: [])
    monkeypatch.setattr(fx, "liquidation_move_pct", lambda *a, **k: 4.5)
    monkeypatch.setattr(fx, "book_cost", lambda *a, **k: {"slippage": 0.0001})
    monkeypatch.setattr(at, "taker_fee", lambda *a, **k: 0.0004)
    monkeypatch.setattr(msw, "charge_cost", lambda *a, **k: (0.0001, []))
    monkeypatch.setattr(msw, "save_costs", lambda *a, **k: None)
    monkeypatch.setattr(msw, "deployed_combos", lambda *a, **k: set())
    monkeypatch.setattr(msw, "load_states", lambda *a, **k: {})
    monkeypatch.setattr(msw, "worker_write", lambda *a, **k: None)
    monkeypatch.setattr(msw, "merge_pair_rows", lambda *a, **k: 0)
    monkeypatch.setattr(msw, "save_pair_rows", lambda *a, **k: 0)
    saved = []
    monkeypatch.setattr(msw, "save_states", lambda c, t, s: saved.append(dict(s)))
    got = msw.run_pair("TEST_USDT", "1h", signals=["keltner", "ml_TEST_1h_1"],
                       merge=True)
    assert got["skipped"] == ["ml_TEST_1h_1"]
    st = saved[-1]
    assert st["__signals__"] == ["keltner"]
    assert st["__version__"].startswith("signals1-"), st["__version__"]


def _window_setup(monkeypatch, n):
    from tradingagents import market_sweep as msw
    from tradingagents import signals_ml as sml

    now = pd.Timestamp.now().floor("h") - pd.Timedelta(days=1)
    df = _frame(n, "1h", end=now)
    sml.register({"ml_TEST_1h_1": _toy_spec()})
    monkeypatch.setattr(msw, "cached_candles", lambda *a, **k: df)
    monkeypatch.setattr(msw, "load_states", lambda *a, **k: {})
    monkeypatch.setattr(msw, "load_costs", lambda *a, **k: {
        "fee": 0.0004, "liq": 4.5, "funding": [], "slippage": 0.0001})
    msw._DIRS_CACHE.clear()
    return {"coin": "TEST", "tf": "1h", "signal": "ml_TEST_1h_1", "th": 0.0,
            "tp": 2.0, "sl": 1.0, "sizing": "flat", "base": 5.0,
            "last_ms": int(df["Date"].iloc[-1].value // 1_000_000)}


def test_the_days_window_refuses_an_ml_row_it_cannot_rebuild(monkeypatch):
    """(d): 300 hours on disk, a 5-day window replayed from 12 days back —
    fewer than 200 bars of clues before it. Unrestated and COUNTED, never
    re-measured on too few bars."""
    from tradingagents import market_sweep as msw
    from tradingagents import signals_ml as sml

    try:
        row = _window_setup(monkeypatch, 300)
        win = msw.window_rows([row], 5)
        assert not row.get("restated")
        assert win["skipped"]["ml_history_short"] == 1
        # the same rule, 2,000 hours deep: re-measured
        row2 = _window_setup(monkeypatch, 2000)
        win2 = msw.window_rows([row2], 5)
        assert row2.get("restated") is True
        assert win2["skipped"]["ml_history_short"] == 0
    finally:
        sml.reload()
    empty = msw.window_rows([], 5)
    assert set(empty["skipped"]) == set(win["skipped"])


def test_the_months_window_refuses_an_ml_row_it_cannot_rebuild(monkeypatch):
    """(d), months: api.restate_window replays through trades_for, whose
    guard answers first — nothing is restated and no cost file is read."""
    from tradingagents import api, stores
    from tradingagents import market_sweep as msw

    df = _frame(150, "1h")
    row = {"id": "X", "coin": "TEST", "tf": "1h", "signal": "ml_TEST_1h_1",
           "th": 0.0, "sl": 1.0, "tp": 2.0, "sizing": "flat", "bars": 100,
           "last_ms": 0}
    monkeypatch.setattr(msw, "cached_candles", lambda *a, **k: df)
    monkeypatch.setattr(msw, "pair_rows", lambda *a, **k: [row])
    monkeypatch.setattr(msw, "load_states", lambda *a, **k: {})
    monkeypatch.setattr(msw, "load_costs", lambda *a, **k: pytest.fail(
        "the refusal must come before any cost read"))
    assert api.restate_window(row, ["2026-09"], store=stores.V1) == {}


def test_an_old_model_with_a_longer_gain_vector_still_describes():
    """(e): a version-1 model carried a 21st clue (funding); describe skips
    the index FEATURES does not name instead of raising IndexError."""
    from tradingagents import ml_features as mf
    from tradingagents import signals_ml as sml

    n = len(mf.FEATURES)
    gain = [0.0] * (n + 1)
    gain[n] = 9.0                  # the clue this version no longer has
    gain[0] = 1.0                  # ret_1
    spec = {"sides": "long", "q": 0.9,
            "models": {"long": {"gain": gain}, "short": "not a model"}}
    said = sml.describe(spec)
    assert said.endswith("reads most: ret_1"), said
