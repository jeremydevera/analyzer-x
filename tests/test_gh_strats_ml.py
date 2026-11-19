"""The machine-learning GitHub repos' strategies (tradingagents/gh_strats/ml.py): a causal
walk-forward, cut-invariant signals, the two plain rules against hand-written copies of the repos'
own code, and the speed a GitHub machine needs (Nov 18, 2026)."""
import time

import numpy as np
import pandas as pd
import pytest

from tradingagents.gh_strats import ml


def _df(n=1500, seed=7, ar=0.0, freq="15min"):
    """A random walk; `ar` plants a weak pattern (each move leans on the one before)."""
    rng = np.random.default_rng(seed)
    e = rng.normal(0, 0.008, n)
    r = np.empty(n)
    r[0] = e[0]
    for i in range(1, n):
        r[i] = ar * r[i - 1] + e[i]
    close = 100 * np.exp(np.cumsum(r))
    spread = np.abs(rng.normal(0, 0.004, n))
    idx = pd.date_range("2026-01-01", periods=n, freq=freq)
    return pd.DataFrame({"open": np.r_[close[0], close[:-1]], "high": close * (1 + spread),
                         "low": close * (1 - spread), "close": close,
                         "volume": rng.lognormal(3, 0.6, n)}, index=idx)


def _key(s):
    return None if s is None else (s.entry, s.direction if s.entry else None, s.exit, s.exit_dir)


# ------------------------------------------------------------------ 1. no signal reads a later candle

@pytest.mark.parametrize("name", list(ml.GRID))
def test_cutting_the_frame_changes_no_earlier_signal(name):
    df = _df(1500)
    strat = ml.STRATEGIES[name]
    for params in ml.GRID[name]:
        whole = [_key(s) for s in strat.signals_all(df, params)]
        assert len(whole) == len(df)
        for cut in (700, 901, 1203, 1499):
            part = [_key(s) for s in strat.signals_all(df.iloc[:cut], params)]
            assert part == whole[:cut], (name, params, cut)


@pytest.mark.parametrize("build", [ml._km_features, ml._hur_features, ml._xgt_features, ml._mal_features,
                                   ml._mk_features, ml._agi_features, ml.tz_indicators])
def test_no_feature_reads_a_later_candle(build):
    df = _df(900)
    whole = build(df)
    for cut in (300, 611, 899):
        part = build(df.iloc[:cut])
        np.testing.assert_array_equal(part, whole[:cut])


def test_the_crypticalgo_shape_flag_ends_at_the_current_candle():
    df = _df(400)
    c = df["close"].to_numpy()
    hs = ml._xgt_features(df)[:, 8]
    for i in range(3, len(df)):
        assert hs[i] == float(c[i - 2] < c[i - 3] and c[i - 1] > c[i - 2] and c[i] > c[i - 1]), i


def test_the_marshal_label_is_the_future_move_not_the_past_one():
    df = _df(600)
    y = ml._mk_label(df)
    c = df["close"].to_numpy()
    high_atr = ml._mk_atr_high(df)
    for j in range(len(df) - 6):
        r = np.log(c[j + 6] / c[j])
        want = 0.0 if high_atr[j] else 1.0 if 0.012 <= r <= 0.03 else 2.0 if -0.03 <= r <= -0.012 else 0.0
        assert y[j] == want, j
    assert np.isnan(y[-6:]).all()


# ------------------------------------------------------------------ 2. the walk-forward helper

def test_the_model_never_trains_on_an_answer_it_could_not_know_yet():
    rng = np.random.default_rng(1)
    n, h = 2300, 7
    X = rng.normal(size=(n, 3))
    X[:40] = np.nan                                     # features not ready yet
    y = (rng.random(n) > 0.5).astype(float)
    y[n - h:] = np.nan                                  # the newest answers are not known
    y[100:120] = np.nan                                 # some rows left out
    trace = []
    ml.walk_forward(X, y, h, ml._hgb(), classes=(0, 1), trace=trace)
    assert [r for r, _ in trace] == ml.refit_points(n) == [500, 1000, 1500, 2000]
    for r, idx in trace:
        assert idx.max() + h <= r                       # every training answer was known at r
        want = [j for j in range(r - h + 1) if j >= 40 and not 100 <= j < 120]
        assert idx.tolist() == want                     # and every known one was used (expanding)


def test_the_refit_candles_do_not_depend_on_the_frames_length():
    assert ml.refit_points(1203) == [500, 1000]
    assert ml.refit_points(2880)[:2] == ml.refit_points(1203)
    assert ml.refit_points(499) == []


def test_changing_a_later_answer_changes_no_earlier_prediction():
    rng = np.random.default_rng(2)
    n, h = 1700, 5
    X = rng.normal(size=(n, 4))
    y = (X[:, 0] + rng.normal(0, 1, n) > 0).astype(float)
    base = ml.walk_forward(X, y, h, ml._hgb(), classes=(0, 1))
    y2 = y.copy()
    y2[996:] = 1 - y2[996:]                             # answers known only from candle 1001 on
    other = ml.walk_forward(X, y2, h, ml._hgb(), classes=(0, 1))
    np.testing.assert_array_equal(base[:1500], other[:1500])   # the refit at 1000 used j <= 995
    assert np.isnan(base[:500]).all()                   # no model before the first fit


def test_a_class_weight_moves_the_probability_toward_the_rare_class():
    rng = np.random.default_rng(3)
    n = 1200
    X = rng.normal(size=(n, 2))
    y = (rng.random(n) < 0.15).astype(float)            # 15% ones
    plain = ml.walk_forward(X, y, 1, ml._hgb(), classes=(0, 1))[:, 1]
    bal = ml.walk_forward(X, y, 1, ml._hgb(), classes=(0, 1), weight="balanced")[:, 1]
    ok = np.isfinite(plain)
    assert (bal[ok] >= plain[ok] - 1e-12).all() and bal[ok].mean() > plain[ok].mean()


# ------------------------------------------------------------------ 3. every strategy trades

@pytest.mark.parametrize("name", list(ml.GRID))
def test_every_strategy_makes_an_entry_on_a_moving_market(name):
    df = _df(3000, seed=11, ar=0.08)
    n = sum(bool(s and s.entry) for p in ml.GRID[name] for s in ml.STRATEGIES[name].signals_all(df, p))
    assert n > 0, name


# ------------------------------------------------------------------ 4. the plain rules are the repos'

def _ema_loop(x, span):
    a = 2 / (span + 1)
    out = np.full(len(x), np.nan)
    prev = None
    for i, v in enumerate(x):
        if np.isnan(v):
            continue
        prev = v if prev is None else a * v + (1 - a) * prev
        out[i] = prev
    return out


def test_the_ridwat_rule_is_the_notebooks_own():
    df = _df(1500, seed=4)
    close = df["close"].to_numpy()
    macd = _ema_loop(close, 12) - _ema_loop(close, 26)          # EMA(): ewm(span, adjust=False)
    sig = _ema_loop(macd, 9)
    chg = np.r_[np.nan, np.diff(close)]
    gain = np.where(np.isnan(chg), np.nan, np.maximum(chg, 0))
    loss = np.where(np.isnan(chg), np.nan, -np.minimum(chg, 0))
    rsi = 100 - 100 / (1 + _ema_loop(gain, 14) / _ema_loop(loss, 14))
    got = ml.STRATEGIES["gh_rid_macd_rsi"].signals_all(df, {"within": 1})
    buys = sells = 0
    for i in range(35, len(df)):
        buy = macd[i] > sig[i] and macd[i - 1] <= sig[i - 1] and rsi[i] < 30
        sell = macd[i] < sig[i] and macd[i - 1] >= sig[i - 1] and rsi[i] > 70
        buys, sells = buys + buy, sells + sell
        assert (got[i].entry and got[i].direction == "long") == buy, i
        assert (got[i].entry and got[i].direction == "short") == sell, i
        assert got[i].exit == (buy or sell), i
    want_within = [ml.ridwat_rule(df, 5)[0][i] for i in range(len(df))]
    assert sum(want_within) >= buys                     # the 5-candle setting fires at least as often


def _tz_copy(df, window=2, max_per=10, per=24):
    """xgb_backtrader.py's strategy_signal, written out candle by candle - except that each average
    runs over the candles up to i, where the repo took it over the whole file."""
    h, lo, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    n = len(df)
    ind = np.full((n, 5), np.nan)
    raw = np.full(n, np.nan)
    for i in range(13, n):
        hh, ll = h[i - 13: i + 1].max(), lo[i - 13: i + 1].min()
        raw[i] = 100 * (c[i] - ll) / (hh - ll)
    k = np.full(n, np.nan)
    d = np.full(n, np.nan)
    for i in range(15, n):
        k[i] = raw[i - 2: i + 1].mean()
    for i in range(17, n):
        d[i] = k[i - 2: i + 1].mean()
    tp = (h + lo + c) / 3
    for i in range(n):
        if i >= 13:
            hh, ll = h[i - 13: i + 1].max(), lo[i - 13: i + 1].min()
            willr = 100 * ((c[i] - ll) / (hh - ll) - 1)
        else:
            willr = np.nan
        if i >= 19:
            w = c[i - 19: i + 1]
            m, s = w.mean(), w.std()
            bbp = (c[i] - (m - 2 * s)) / (4 * s)
            t = tp[i - 19: i + 1]
            cci = (tp[i] - t.mean()) / (0.015 * np.abs(t - t.mean()).mean())
        else:
            bbp = cci = np.nan
        ind[i] = [willr, d[i], bbp, cci, k[i]]
    long_in, short_in = np.zeros(n, bool), np.zeros(n, bool)
    ls, lk, ss, sk = np.zeros(5), 0, np.zeros(5), 0
    taken = []
    for i in range(n):
        ok = np.isfinite(ind[i]).all()
        lab = 0 if i < window else np.sign(c[i] - c[i - window])
        if ok and lab > 0:
            ls, lk = ls + ind[i], lk + 1
        if ok and lab < 0:
            ss, sk = ss + ind[i], sk + 1
        if not ok:
            continue
        go_long = lk > 0 and (ind[i] > ls / lk).all()
        go_short = sk > 0 and (ind[i] < ss / sk).all() and not go_long
        taken = [t for t in taken if t > i - per]
        if (go_long or go_short) and len(taken) < max_per:
            taken.append(i)
            long_in[i], short_in[i] = go_long, go_short
    return long_in, short_in


def test_the_tzelalouzeir_rule_is_the_scripts_own():
    df = _df(1200, seed=9, freq="5min")
    long_in, short_in = _tz_copy(df)
    got = ml.STRATEGIES["gh_tz_osc5"].signals_all(df, {"window": 2, "max_per_24": 10})
    assert long_in.sum() > 10 and short_in.sum() > 10
    for i in range(40, len(df)):
        assert (got[i].entry and got[i].direction == "long") == long_in[i], i
        assert (got[i].entry and got[i].direction == "short") == short_in[i], i
    # at most 10 entries in any 24 candles
    e = np.array([bool(s and s.entry) for s in got], dtype=int)
    assert max(e[i: i + 24].sum() for i in range(len(e) - 24)) <= 10


# ------------------------------------------------------------------ 5. the batch is loaded

def test_the_package_loads_this_batch():
    import tradingagents.gh_strats as g
    assert "ml" in g.LOADED
    for name in ml.STRATEGIES:
        assert name.startswith("gh_") and name in g.STRATEGIES
        assert g.RULE_OF[name] and g.REPO_OF[name] and 1 <= len(g.GRID[name]) <= 2
    assert g.STOPS["gh_tz_osc5"] == (0.01,) and g.TARGETS["gh_tz_osc5"] == 1.0
    assert g.STOPS["gh_mal_lstm"] == (0.10,) and g.TARGETS["gh_mal_lstm"] == 0.15
    assert g.STOPS["gh_km_logit"] == g.DEFAULT_STOPS and g.TARGETS["gh_km_logit"] is None
    mal = [c for c in g.combos() if c["strategy"] == "gh_mal_lstm"]
    assert {c["target"] for c in mal} == {0.015}         # 1.5% over a 10% stop
    assert "Mun-Min" in ml.RULE_OF["gh_es_sma_ml"] and "ethansilvas" in ml.RULE_OF["gh_es_sma_ml"]
    assert 15 <= sum(len(v) for v in ml.GRID.values()) <= 24
    for name in ("gh_km_rf", "gh_km_xgb", "gh_hur_rf", "gh_xgt_xgb", "gh_es_sma_ml", "gh_mal_lstm",
                 "gh_mk_lstm", "gh_agi_xgb", "gh_pyb_rf"):
        assert "replaced by gradient boosting" in ml.RULE_OF[name], name


# ------------------------------------------------------------------ 6. fast enough for a machine

def test_every_strategy_on_a_month_of_15m_candles_is_quick():
    df = _df(2880, seed=21)
    ml.clear_cache()
    t = time.perf_counter()
    for name, strat in ml.STRATEGIES.items():
        for params in ml.GRID[name]:
            strat.signals_all(df, params)
    took = time.perf_counter() - t
    assert took < 10, f"{took:.1f} s"
