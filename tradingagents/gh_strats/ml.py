"""THE MACHINE-LEARNING REPOS' STRATEGIES, RUN CAUSALLY ON OUR CANDLES (Nov 18, 2026).

Ten reviewed repos (`knowledge/github-repos/<owner>__<repo>.md`) train a classifier on indicator
features and trade its answer. Here every model is re-trained by ONE walk-forward (`walk_forward`):

* at candle i the model in use was fitted at a refit candle r <= i, on rows j whose label was
  already KNOWN at r (j + h <= r, h = the label's horizon) - never a row whose answer lies later;
* the refit candles are `MIN_TRAIN`, `MIN_TRAIN + REFIT`, ... - fixed by the candle's index, never
  by the frame's length, so cutting the frame at k gives exactly the same signals before k;
* the window grows (expanding); before the first fit there is no signal;
* every feature at candle j reads candles 0..j only (rolling / ewm / cumulative, never centred,
  never a whole-frame scaler); a scaler is fitted inside each refit on its training rows only.

Their models are replaced by scikit-learn stand-ins with a fixed `random_state`: XGBoost, random
forest, SVM and LSTM by `HistGradientBoostingClassifier` (an LSTM's window of past candles becomes
lagged / multi-horizon features), logistic regression by `LogisticRegression`. Each RULE_OF says so.

Fills, size and leverage are the engine's ($5 x 20x, entry at the signal candle's close); a repo's own
leverage (tzelalouzeir 24x) is not used. Two repos whose "model" only copies a rule (Ridwat, the
tzelalouzeir five-oscillator rule) run as plain rules.
"""
from __future__ import annotations

import hashlib
from collections import OrderedDict

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from tradingagents.skill_ta import _adx, _to_signals

MIN_TRAIN = 500          # first fit at this candle; no signal before it
REFIT = 500              # refit every this many candles, expanding window (250 measured 9.3 s a frame)
MIN_ROWS = 100           # a refit with fewer known rows than this fits nothing
SEED = 42
THREADS = 1              # on a few thousand rows the stand-in's thread pool costs more than it saves


# ------------------------------------------------------------------ the shared walk-forward

def refit_points(n: int, min_train: int = MIN_TRAIN, refit: int = REFIT) -> list[int]:
    """The candles a model is (re)fitted at - a function of the index only."""
    return list(range(min_train, n, refit))


def walk_forward(X, y, h: int, make, *, classes=None, weight=None, min_train: int = MIN_TRAIN,
                 refit: int = REFIT, min_rows: int = MIN_ROWS, trace: list | None = None) -> np.ndarray:
    """Causal expanding-window predictions.

    X: (n, f) features of each candle (NaN = not ready). y: (n,) label of each candle, NaN where
    unknown or left out. h: the label's horizon - row j's label is known at candle j + h.
    make(): a fresh unfitted model. classes: the label values (a classifier, returns (n, len(classes))
    probabilities) or None (a regressor, returns (n,) predictions). Rows before the first fit are NaN.
    weight: a repo's class weights - "balanced" or {class: weight} - applied to the fitted model's
    probabilities (each class's probability times its weight, renormalised; "balanced" = 1 / the
    class's share of the training rows), which is what weighting the training rows aims at and
    keeps the stand-in's fast unweighted fit.
    trace: if given, gets (refit candle, training row indices) for every refit."""
    with threadpool_limits(limits=THREADS, user_api="openmp"):
        return _walk(X, y, h, make, classes, weight, min_train, refit, min_rows, trace)


def _walk(X, y, h, make, classes, weight, min_train, refit, min_rows, trace):
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(X)
    out = np.full((n, len(classes)) if classes is not None else n, np.nan)
    okx = np.isfinite(X).all(axis=1)
    oky = np.isfinite(y)
    for r in refit_points(n, min_train, refit):
        last = r - h                                   # newest row whose answer is known at r
        idx = np.flatnonzero(okx[: last + 1] & oky[: last + 1]) if last >= 0 else np.zeros(0, int)
        if trace is not None:
            trace.append((r, idx))
        end = min(r + refit, n)
        rows = np.arange(r, end)[okx[r:end]]
        if len(idx) < min_rows or len(rows) == 0:
            continue
        Xt, yt = X[idx], y[idx]
        if classes is None:
            m = make()
            m.fit(Xt, yt)
            out[rows] = _predict_rows(m, X[rows])
            continue
        present = np.unique(yt)
        out[rows] = 0.0
        if len(present) == 1:                          # one answer only: that answer, surely
            out[rows, list(classes).index(int(present[0]))] = 1.0
            continue
        m = make()
        m.fit(Xt, yt.astype(int))
        p = _proba_rows(m, X[rows])
        if weight is not None:
            if weight == "balanced":
                w = np.array([len(yt) / (len(m.classes_) * np.sum(yt == c)) for c in m.classes_])
            else:
                w = np.array([float(weight[int(c)]) for c in m.classes_])
            p = p * w
            p = p / p.sum(axis=1, keepdims=True)
        for k, c in enumerate(m.classes_):
            out[rows, list(classes).index(int(c))] = p[:, k]
    return out


def _proba_rows(m, X):
    """predict_proba whose every row is independent of the batch it came in (a cut frame predicts
    shorter batches; a BLAS product could round a row differently)."""
    if isinstance(m, _ScaledLogit):
        return m.proba_rows(X)
    return m.predict_proba(X)


def _predict_rows(m, X):
    return m.predict(X)


class _ScaledLogit:
    """StandardScaler + LogisticRegression, the scaler fitted on the training rows only, and a
    prediction worked row by row (einsum, no BLAS) so batch size cannot change a probability."""

    def __init__(self, C: float = 1.0, balanced: bool = False):
        self.lr = LogisticRegression(C=C, max_iter=1000, class_weight="balanced" if balanced else None,
                                     random_state=SEED)

    def fit(self, X, y):
        self.mu = X.mean(axis=0)
        sd = X.std(axis=0)
        self.sd = np.where(sd > 0, sd, 1.0)
        self.lr.fit((X - self.mu) / self.sd, y)
        self.classes_ = self.lr.classes_
        return self

    def proba_rows(self, X):
        Z = (X - self.mu) / self.sd
        z = np.einsum("ij,kj->ik", Z, self.lr.coef_) + self.lr.intercept_
        if z.shape[1] == 1:                              # two classes
            p1 = 1.0 / (1.0 + np.exp(-z[:, 0]))
            return np.column_stack([1 - p1, p1])
        z = z - z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)


ITERS = 40              # boosting rounds of every stand-in (speed: 5 timeframes x ~18 coins a machine)
LEAVES = 15
BINS = 63


def _hgb(depth=3, lr=0.1, iters=ITERS, leaf=20):
    return lambda: HistGradientBoostingClassifier(max_depth=depth, learning_rate=lr, max_iter=iters,
                                                  min_samples_leaf=leaf, max_leaf_nodes=LEAVES,
                                                  max_bins=BINS, early_stopping=False,
                                                  random_state=SEED)


def _hgb_reg(depth=4, lr=0.1, iters=ITERS, leaf=20):
    return lambda: HistGradientBoostingRegressor(max_depth=depth, learning_rate=lr, max_iter=iters,
                                                 min_samples_leaf=leaf, max_leaf_nodes=LEAVES,
                                                 max_bins=BINS, early_stopping=False,
                                                 random_state=SEED)


# one frame's predictions are shared by every setting that only moves a threshold
_CACHE: OrderedDict = OrderedDict()
_CACHE_MAX = 64


def _fingerprint(df: pd.DataFrame) -> str:
    h = hashlib.blake2b(digest_size=16)
    h.update(np.ascontiguousarray(df[["open", "high", "low", "close", "volume"]].to_numpy(float)).tobytes())
    h.update(np.ascontiguousarray(df.index.asi8 if isinstance(df.index, pd.DatetimeIndex)
                                  else np.arange(len(df))).tobytes())
    return h.hexdigest()


def _cached(df, key, fn):
    k = (key, _fingerprint(df))
    if k in _CACHE:
        _CACHE.move_to_end(k)
        return _CACHE[k]
    v = fn()
    _CACHE[k] = v
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return v


def clear_cache():
    _CACHE.clear()


# ------------------------------------------------------------------ causal indicators

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def _rsi_w(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    g, l = _wilder(d.clip(lower=0), n), _wilder(-d.clip(upper=0), n)
    return 100 - 100 / (1 + g / l)


def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    h, lo, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return _wilder(tr, n)


def _stoch_raw(df: pd.DataFrame, n: int) -> pd.Series:
    hh, ll = df["high"].rolling(n).max(), df["low"].rolling(n).min()
    return 100 * (df["close"] - ll) / (hh - ll)


def _mad(x: np.ndarray, n: int) -> np.ndarray:
    """Rolling mean absolute deviation around the window's own mean (pandas_ta's cci `mad`)."""
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        w = sliding_window_view(x, n)
        out[n - 1:] = np.abs(w - w.mean(axis=1, keepdims=True)).mean(axis=1)
    return out


def _cci(df: pd.DataFrame, n: int, c: float = 0.015) -> np.ndarray:
    tp = ((df["high"] + df["low"] + df["close"]) / 3).to_numpy()
    sma = pd.Series(tp).rolling(n).mean().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        return (tp - sma) / (c * _mad(tp, n))


def _mfi(df: pd.DataFrame, n: int) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    mf = tp * df["volume"]
    up = mf.where(tp.diff() > 0, 0.0).rolling(n).sum()
    dn = mf.where(tp.diff() < 0, 0.0).rolling(n).sum()
    return 100 - 100 / (1 + up / dn)


def _cols(*cols) -> np.ndarray:
    a = np.column_stack([np.asarray(c, dtype=float) for c in cols])
    a[~np.isfinite(a)] = np.nan
    return a


def _fwd_ret(close: pd.Series, h: int) -> np.ndarray:
    return (close.shift(-h) / close - 1).to_numpy()


def _hold_exits(sig: np.ndarray, h: int | None, turn: np.ndarray | None):
    """Long-only 'be in while the model says so, at most h candles': entries, exits.
    Follows the engine without stops (causal: candle i reads only i and before). An entry is not
    signalled on the candle a horizon exit happens, so the trade is not closed and re-bought at once."""
    n = len(sig)
    long_in, long_out = np.zeros(n, bool), np.zeros(n, bool)
    held_from = -1
    for i in range(n):
        out_now = False
        if held_from >= 0:
            if (h is not None and i - held_from >= h) or (turn is not None and turn[i]):
                long_out[i], out_now, held_from = True, True, -1
        if sig[i] and not out_now:
            long_in[i] = True
            if held_from < 0:
                held_from = i
    return long_in, long_out


# ------------------------------------------------------------------ KennethMartin06

def _km_features(df: pd.DataFrame) -> np.ndarray:
    o, h, lo, c, v = (df[k] for k in ("open", "high", "low", "close", "volume"))
    r = c.pct_change()
    feats = [r, np.log(c).diff(), r.shift(1), r.shift(2), r.shift(3), r.shift(5)]
    feats += [c / c.shift(k) - 1 for k in (5, 10, 20, 60)]
    feats += [o / c.shift(1) - 1, c / o - 1, (h - lo) / c, (c - lo) / (h - lo)]
    feats += [c / c.rolling(k).mean() - 1 for k in (5, 10, 20, 50)]
    feats += [c / _ema(c, k) - 1 for k in (5, 10, 20, 50)]
    feats += [c.rolling(10).mean() / c.rolling(50).mean() - 1, _rsi_w(c, 14)]
    macd = _ema(c, 12) - _ema(c, 26)
    sig = _ema(macd, 9)
    feats += [macd / c, sig / c, (macd - sig) / c]
    m20, s20 = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
    feats += [(c - (m20 - 2 * s20)) / (4 * s20), 4 * s20 / m20, _atr(df, 14) / c]
    w5, w20, w60 = (r.rolling(k).std() for k in (5, 20, 60))
    feats += [w5, w20, w60, w5 / w60, r / w20]
    feats += [v / v.rolling(5).mean(), v / v.rolling(20).mean(),
              (v - v.rolling(20).mean()) / v.rolling(20).std()]
    feats += [c / c.rolling(200).mean() - 1,
              (c.rolling(50).mean() > c.rolling(200).mean()).astype(float).where(c.rolling(200).count() == 200),
              c / c.rolling(252).max() - 1]
    return _cols(*feats)


def _km_label(df: pd.DataFrame) -> np.ndarray:
    r = _fwd_ret(df["close"], 1)                       # our fills are at the close: close to close
    y = np.where(r > 0.001, 2.0, np.where(r < -0.001, 0.0, 1.0))
    y[~np.isfinite(r)] = np.nan
    return y


_KM_MODELS = {
    "logit": lambda: _ScaledLogit(C=0.1),
    "rf": _hgb(depth=6, lr=0.1, leaf=20),     # their random forest: depth 6, 20 days a leaf
    "xgb": _hgb(depth=3, lr=0.1, leaf=5),     # their XGBoost: depth 3, lr 0.1, min child 5
}


def _km_p_up(df, which: str) -> np.ndarray:
    def run():
        X = _cached(df, "km_X", lambda: _km_features(df))
        y = _cached(df, "km_y", lambda: _km_label(df))
        return walk_forward(X, y, 1, _KM_MODELS[which], classes=(0, 1, 2))[:, 2]
    return _cached(df, f"km_p_{which}", run)


class _KmModel:
    def __init__(self, name, members):
        self.name, self.members = name, members

    def signals_all(self, df, params):
        p = np.mean([_km_p_up(df, m) for m in self.members], axis=0)
        tau = float(params["tau"])
        with np.errstate(invalid="ignore"):
            on, off = p >= tau, p < tau
        z = np.zeros(len(df), bool)
        return _to_signals(len(df), MIN_TRAIN, on, z, long_out=off)


# ------------------------------------------------------------------ Ridwat (a plain rule)

def ridwat_rule(df: pd.DataFrame, within: int = 1):
    """MACD 12/26/9 crosses up AND RSI (ewm span 14) < 30 -> Buy; crosses down AND RSI > 70 -> Sell.
    `within` = 1 is the notebook's same-candle rule; > 1 lets the RSI condition be met on any of the
    last `within` candles (the note's suggested fix: the pair fired once in 1,500 Tesla days)."""
    c = df["close"]
    macd = _ema(c, 12) - _ema(c, 26)
    sig = _ema(macd, 9)
    up = ((macd > sig) & (macd.shift(1) <= sig.shift(1))).to_numpy()
    dn = ((macd < sig) & (macd.shift(1) >= sig.shift(1))).to_numpy()
    d = c.diff()
    rs = d.clip(lower=0).ewm(span=14, adjust=False).mean() / (-d.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rsi = 100 - 100 / (1 + rs)
    low = (rsi < 30).astype(float).rolling(within, min_periods=1).max().to_numpy() > 0
    high = (rsi > 70).astype(float).rolling(within, min_periods=1).max().to_numpy() > 0
    return up & low, dn & high


class _Ridwat:
    name = "gh_rid_macd_rsi"

    def signals_all(self, df, params):
        buy, sell = ridwat_rule(df, int(params["within"]))
        return _to_signals(len(df), 35, buy, sell, long_out=sell, short_out=buy)


# ------------------------------------------------------------------ Huraira9913

def _hur_features(df):
    c, v = df["close"], df["volume"]
    r1 = c.pct_change()
    return _cols(r1, c.pct_change(5), c.pct_change(20), r1.rolling(20).std(),
                 c / c.rolling(50).mean() - 1, (v - v.rolling(20).mean()) / v.rolling(20).std())


class _Huraira:
    name = "gh_hur_rf"
    H = 5

    def signals_all(self, df, params):
        def run():
            r = _fwd_ret(df["close"], self.H)
            y = np.where(np.isfinite(r), (r > 0).astype(float), np.nan)
            return walk_forward(_hur_features(df), y, self.H, _hgb(depth=6), classes=(0, 1))[:, 1]
        p = _cached(df, "hur_p", run)
        tau = float(params["tau"])
        with np.errstate(invalid="ignore"):
            on, off = p >= tau, p < tau
        on[: MIN_TRAIN] = False
        long_in, long_out = _hold_exits(on, self.H, off)
        return _to_signals(len(df), MIN_TRAIN, long_in, np.zeros(len(df), bool), long_out=long_out)


# ------------------------------------------------------------------ crypticalgo (look-ahead fixed)

def _xgt_features(df):
    o, h, lo, c, v = (df[k] for k in ("open", "high", "low", "close", "volume"))
    ema5 = _ema(c, 5)
    macd = _ema(c, 3) - _ema(c, 9)
    sig = _ema(macd, 9)
    m5, s5 = c.rolling(5).mean(), c.rolling(5).std(ddof=0)
    tp = (h + lo + c) / 3
    vwap = (tp * v).cumsum() / v.cumsum()               # their running VWAP: from the frame's first row
    # their "Head-Shoulders" flag read close[i+1] and close[i+2]; here the same down-up-up shape
    # ENDS at candle i (close[i-2] < close[i-3], then two rises)
    hs = ((c.shift(2) < c.shift(3)) & (c.shift(1) > c.shift(2)) & (c > c.shift(1))).astype(float)
    hs[c.shift(3).isna()] = np.nan
    return _cols(c, ema5, macd, sig, _rsi_w(c, 6), m5 + 2 * s5, m5 - 2 * s5, vwap, hs,
                 c.shift(1), v.shift(1), _atr(df, 14), c.pct_change(3))


def _xgt_label(df):
    c = df["close"]
    macd = _ema(c, 3) - _ema(c, 9)
    lab = np.array(((macd > _ema(macd, 9)) & (c > _ema(c, 5))).astype(float))
    lab[:9] = np.nan
    return lab


class _Xgt:
    name = "gh_xgt_xgb"

    def signals_all(self, df, params):
        def run():   # label describes the candle itself: known at j, so h = 0
            return walk_forward(_xgt_features(df), _xgt_label(df), 0, _hgb(depth=6, lr=0.1),
                                classes=(0, 1), weight={0: 0.5, 1: 1.0})[:, 1]
        p = _cached(df, "xgt_p", run)
        band = float(params["band"])
        with np.errstate(invalid="ignore"):
            up, dn = p >= band, p <= 1 - band
        return _to_signals(len(df), MIN_TRAIN, up, dn, long_out=dn, short_out=up)


# ------------------------------------------------------------------ tzelalouzeir (a plain rule)

def tz_indicators(df: pd.DataFrame) -> np.ndarray:
    """WILLR 14, STOCHd 14-3-3, BBP 20 2.0, CCI 20, STOCHk 14-3-3 (pandas_ta's formulas)."""
    c = df["close"]
    hh, ll = df["high"].rolling(14).max(), df["low"].rolling(14).min()
    willr = 100 * ((c - ll) / (hh - ll) - 1)
    k = _stoch_raw(df, 14).rolling(3).mean()
    d = k.rolling(3).mean()
    m, s = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
    bbp = (c - (m - 2 * s)) / (4 * s)
    return _cols(willr, d, bbp, _cci(df, 20), k)


def tz_rule(df: pd.DataFrame, window: int = 2, max_per: int = 10, per: int = 24):
    """Long when ALL five oscillators are above their average over the candles labelled 'long'
    (close above the close `window` candles ago); short when all five are below their average over
    the 'short' candles. The repo averaged over the WHOLE file, the days it then traded; here each
    average runs over candles 0..i only. At most `max_per` entries in any `per` candles."""
    ind = tz_indicators(df)
    c = df["close"].to_numpy()
    n = len(df)
    lab = np.zeros(n)
    lab[window:] = np.sign(c[window:] - c[:-window])
    ok = np.isfinite(ind).all(axis=1)

    def run_mean(mask):
        m = (mask & ok)[:, None]
        s = np.cumsum(np.where(m, ind, 0.0), axis=0)
        k = np.cumsum(m, axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(k > 0, s / k, np.nan)

    lm, sm = run_mean(lab > 0), run_mean(lab < 0)
    with np.errstate(invalid="ignore"):
        lo = ok & (ind > lm).all(axis=1)
        sh = ok & (ind < sm).all(axis=1) & ~lo
    long_in, short_in = np.zeros(n, bool), np.zeros(n, bool)
    recent: list[int] = []
    for i in range(n):
        while recent and recent[0] <= i - per:
            recent.pop(0)
        if (lo[i] or sh[i]) and len(recent) < max_per:
            recent.append(i)
            long_in[i], short_in[i] = lo[i], sh[i]
    return long_in, short_in


class _Tz:
    name = "gh_tz_osc5"

    def signals_all(self, df, params):
        long_in, short_in = tz_rule(df, int(params["window"]), int(params["max_per_24"]))
        return _to_signals(len(df), 40, long_in, short_in)


# ------------------------------------------------------------------ ethansilvas / Mun-Min

class _SmaMl:
    name = "gh_es_sma_ml"

    def signals_all(self, df, params):
        f, s = int(params["fast"]), int(params["slow"])

        def run():
            c = df["close"]
            X = _cols(c.rolling(f).mean(), c.rolling(s).mean())  # their raw average levels
            r = _fwd_ret(c, 1)
            y = np.where(np.isfinite(r), (r >= 0).astype(float), np.nan)   # 'Signal = 1 when return >= 0'
            return walk_forward(X, y, 1, _hgb(depth=3), classes=(0, 1))[:, 1]
        p = _cached(df, f"es_p_{f}_{s}", run)
        with np.errstate(invalid="ignore"):
            up, dn = p >= 0.5, p < 0.5
        return _to_signals(len(df), MIN_TRAIN, up, dn, long_out=dn, short_out=up)


# ------------------------------------------------------------------ maleshchenko

def _mal_features(df):
    c, v = df["close"], df["volume"]
    lr = np.log(c).diff()
    base = [lr, lr.rolling(10).std(), (v - v.rolling(20).mean()) / v.rolling(20).std(),
            (c.rolling(10).mean() - c.rolling(20).mean()) / c, _rsi_w(c, 14), _atr(df, 14) / c,
            v.pct_change()]
    # the LSTM read the last 30 candles; the stand-in gets the newest candle plus the path behind it
    path = [lr.shift(1), lr.shift(2), c / c.shift(5) - 1, c / c.shift(10) - 1, c / c.shift(30) - 1]
    return _cols(*base, *path)


def _mal_label(df, h=10, tp=0.005, sl=0.003):
    c = df["close"]
    hh = df["high"].rolling(h).max().shift(-h).to_numpy()   # highest of candles t+1..t+h
    ll = df["low"].rolling(h).min().shift(-h).to_numpy()
    cv = c.to_numpy()
    y = np.zeros(len(df))
    y[(hh > cv * (1 + tp)) & (ll > cv * (1 - sl))] = 1.0
    y[(ll < cv * (1 - tp)) & (hh < cv * (1 + sl))] = 2.0
    y[~(np.isfinite(hh) & np.isfinite(ll))] = np.nan
    return y


class _Mal:
    name = "gh_mal_lstm"

    def signals_all(self, df, params):
        p = _cached(df, "mal_p", lambda: walk_forward(
            _mal_features(df), _mal_label(df), 10, _hgb(depth=4), classes=(0, 1, 2),
            weight="balanced"))
        tau = float(params["tau"])
        with np.errstate(invalid="ignore"):
            lo = (p[:, 1] > tau) & (p[:, 1] > p[:, 2])
            sh = (p[:, 2] > tau) & (p[:, 2] > p[:, 1])
        return _to_signals(len(df), MIN_TRAIN, lo, sh)


# ------------------------------------------------------------------ Marshal-Kalynchuk (label fixed)

def _mk_atr_high(df):
    atr = _atr(df, 6)
    q = atr.rolling(500, min_periods=50).quantile(0.75)   # the repo used the whole file's 75th pct
    return (atr > q).to_numpy()


def _mk_features(df):
    o, h, lo, c, v = (df[k] for k in ("open", "high", "low", "close", "volume"))
    lr = np.log(c).diff()
    macd = _ema(c, 6) - _ema(c, 12)
    feats = [lr, (h - np.maximum(o, c)) / c, (np.minimum(o, c) - lo) / c, np.log1p(v),
             _rsi_w(c, 6), _stoch_raw(df, 6), c.pct_change(6), _mfi(df, 6), _atr(df, 6) / c,
             _cci(df, 6), (macd - _ema(macd, 9)) / c, _adx(df, 12),
             (c.shift(7) - c.rolling(12).mean()) / c,                       # DPO 12
             _ema(c.diff() * v, 13) / (c * v.rolling(48).mean())]           # force index, scaled
    # the LSTM read the last 48 candles
    feats += [c / c.shift(k) - 1 for k in (12, 24, 48)]
    return _cols(*feats)


def _mk_label(df, lo_t=0.012, hi_t=0.03, h=6):
    """FIXED: the FUTURE h-candle log move (the repo's column used the PAST one). 1 = buy if it is
    +1.2% to +3%, 2 = sell if -3% to -1.2%, else 0 = hold; and hold on a high-ATR candle."""
    c = df["close"]
    r = np.log(c.shift(-h) / c).to_numpy()
    y = np.zeros(len(df))
    y[(r >= lo_t) & (r <= hi_t)] = 1.0
    y[(r <= -lo_t) & (r >= -hi_t)] = 2.0
    y[_mk_atr_high(df)] = 0.0
    y[~np.isfinite(r)] = np.nan
    return y


class _Mk:
    name = "gh_mk_lstm"

    def signals_all(self, df, params):
        p = _cached(df, "mk_p", lambda: walk_forward(
            _mk_features(df), _mk_label(df), 6, _hgb(depth=4), classes=(0, 1, 2),
            weight="balanced"))
        calm = ~_mk_atr_high(df)
        with np.errstate(invalid="ignore"):
            best = np.where(np.isfinite(p).all(axis=1), np.argmax(np.nan_to_num(p), axis=1), 0)
        return _to_signals(len(df), MIN_TRAIN, (best == 1) & calm, (best == 2) & calm)


# ------------------------------------------------------------------ agiprolabs

def _agi_features(df):
    c, h, lo, v = df["close"], df["high"], df["low"], df["volume"]
    feats = [c / c.shift(k) - 1 for k in (3, 6, 12, 24)]
    feats.append(_rsi_w(c, 14))
    ret = c.diff() / c
    feats += [ret.rolling(w).std(ddof=0).shift(1) for w in (10, 20)]          # bars i-w .. i-1
    feats += [v / v.rolling(w).mean().shift(1) for w in (10, 20)]
    feats += [(c - lo.rolling(w + 1).min()) / (h.rolling(w + 1).max() - lo.rolling(w + 1).min())
              for w in (10, 20)]
    fast, slow = c.rolling(10).mean().shift(1), c.rolling(30).mean().shift(1)
    feats += [(fast - slow) / slow, (h - lo) / c]
    return _cols(*feats)


class _Agi:
    name = "gh_agi_xgb"

    def signals_all(self, df, params):
        hz, tau = int(params["horizon"]), float(params["tau"])

        def run():
            r = _fwd_ret(df["close"], hz)
            y = np.where(r > 0.01, 1.0, np.where(r < -0.01, 0.0, np.nan))   # the middle is dropped
            return walk_forward(_agi_features(df), y, hz, _hgb(depth=4, lr=0.05),
                                classes=(0, 1))[:, 1]
        p = _cached(df, f"agi_p_{hz}", run)
        with np.errstate(invalid="ignore"):
            on = p >= tau
        long_in, long_out = _hold_exits(on, hz, None)                    # hold exactly hz candles
        return _to_signals(len(df), MIN_TRAIN, long_in, np.zeros(len(df), bool), long_out=long_out)


# ------------------------------------------------------------------ edtechre/pybroker

class _Pyb:
    name = "gh_pyb_rf"

    def signals_all(self, df, params):
        lags = int(params["lags"])

        def run():
            lr = np.log(df["close"]).diff()
            X = _cols(*[lr.shift(k) for k in range(lags + 1)])
            y = lr.shift(-1).to_numpy()
            return walk_forward(X, y, 1, _hgb_reg(depth=4))
        pred = _cached(df, f"pyb_{lags}", run)
        with np.errstate(invalid="ignore"):
            on, off = pred > 0, pred < 0
        return _to_signals(len(df), MIN_TRAIN, on, np.zeros(len(df), bool), long_out=off)


# ------------------------------------------------------------------ the batch's tables

_ALL = [
    _KmModel("gh_km_logit", ("logit",)), _KmModel("gh_km_rf", ("rf",)),
    _KmModel("gh_km_xgb", ("xgb",)), _KmModel("gh_km_ens", ("logit", "rf", "xgb")),
    _Ridwat(), _Huraira(), _Xgt(), _Tz(), _SmaMl(), _Mal(), _Mk(), _Agi(), _Pyb(),
]
STRATEGIES = {s.name: s for s in _ALL}

GRID = {
    "gh_km_logit": [{"tau": 0.425}, {"tau": 0.375}],     # SPY's and MSFT's chosen tau
    "gh_km_rf": [{"tau": 0.30}],                         # SPY's
    "gh_km_xgb": [{"tau": 0.375}, {"tau": 0.325}],       # SPY's and AAPL's
    "gh_km_ens": [{"tau": 0.30}],                        # SPY's
    "gh_rid_macd_rsi": [{"within": 1}, {"within": 5}],
    "gh_hur_rf": [{"tau": 0.5}],
    "gh_xgt_xgb": [{"band": 0.5}],
    "gh_tz_osc5": [{"window": 2, "max_per_24": 10}, {"window": 4, "max_per_24": 10}],
    "gh_es_sma_ml": [{"fast": 4, "slow": 150}, {"fast": 8, "slow": 20}],   # ethansilvas, Mun-Min
    "gh_mal_lstm": [{"tau": 0.8}, {"tau": 0.65}],        # the code's 0.8, the README's 0.65
    "gh_mk_lstm": [{}],
    "gh_agi_xgb": [{"horizon": 12, "tau": 0.55}, {"horizon": 24, "tau": 0.60}],
    "gh_pyb_rf": [{"lags": 3}],
}

STOPS = {
    "gh_tz_osc5": (0.01,),
    "gh_mal_lstm": (0.10,),
    "gh_mk_lstm": (0.03,),
}

TARGETS = {name: None for name in STRATEGIES}
TARGETS.update({"gh_tz_osc5": 1.0, "gh_mal_lstm": 0.15, "gh_mk_lstm": round(0.05 / 0.03, 6)})

_KM = "KennethMartin06/ml-based-algorithmic-trading-signals"
REPO_OF = {
    "gh_km_logit": _KM, "gh_km_rf": _KM, "gh_km_xgb": _KM, "gh_km_ens": _KM,
    "gh_rid_macd_rsi": "Ridwat/Project-3-ML-for-Predicting-Trading-Signal",
    "gh_hur_rf": "Huraira9913/trading-signal-ml",
    "gh_xgt_xgb": "crypticalgo/XGTraderAGI---Training-and-Model-Only-XGBOOST-",
    "gh_tz_osc5": "tzelalouzeir/XGB_CryptoStrategy",
    "gh_es_sma_ml": "ethansilvas/sma-ml-trading-algorithm",
    "gh_mal_lstm": "maleshchenko/trade-ml",
    "gh_mk_lstm": "Marshal-Kalynchuk/crypto-lstm-prediction",
    "gh_agi_xgb": "agiprolabs/claude-trading-skills",
    "gh_pyb_rf": "edtechre/pybroker",
}

_KM_RULE = ("~40 of its 42 return, trend, volatility, volume and regime features, label next candle "
            "up/flat/down at +-0.1% (close to close, since our fills are at the close), {model}, "
            "walk-forward refit every 500 candles; long while P(up) >= tau, out when it drops below "
            "(src/targets.py, src/backtester.py, config.yaml)")
RULE_OF = {
    "gh_km_logit": _KM_RULE.format(model="logistic regression (C 0.1, scaled on training rows)"),
    "gh_km_rf": _KM_RULE.format(model="their random forest is replaced by gradient boosting (depth 6)"),
    "gh_km_xgb": _KM_RULE.format(model="their XGBoost is replaced by gradient boosting (depth 3)"),
    "gh_km_ens": _KM_RULE.format(model="the average of the logistic, forest and XGBoost stand-ins "
                                       "(their LSTM member is left out)"),
    "gh_rid_macd_rsi": ("The rule its classifiers copy, run as a rule: buy when MACD 12/26/9 crosses up "
                        "and RSI (ewm span 14) is under 30, short when it crosses down and RSI is over 70 "
                        "(same candle; setting 2: RSI within the last 5 candles); out on the opposite "
                        "signal or the engine's stop (Project_3_ML_for_Predicting_Trading_Signals.ipynb)."),
    "gh_hur_rf": ("Returns 1/5/20, 20-candle wobble, distance from the 50 average and volume z-score; "
                  "label 'close higher 5 candles later'; their random forest is replaced by gradient "
                  "boosting (depth 6); long while P(up) >= 0.5, out when it drops or after 5 candles "
                  "(src/generate_signals.py)."),
    "gh_xgt_xgb": ("Its 13 inputs (close, EMA 5, MACD 3/9/9, RSI 6, Bollinger 5, running VWAP, ATR 14, "
                   "ROC 3 ...) with the look-ahead removed (its 'Head-Shoulders' flag read two later "
                   "candles; here the shape ends at the current one) and no whole-file z-scoring; label "
                   "'MACD above signal and close above EMA 5' on the candle itself; their XGBoost is "
                   "replaced by gradient boosting; long when it says 1, short when 0, flipping (main.py, "
                   "BackTest.py)."),
    "gh_tz_osc5": ("Long when Williams %R 14, Stochastic %K and %D 14-3-3, Bollinger %B 20 and CCI 20 are "
                   "ALL above their average over the candles that closed higher than 2 candles before "
                   "(short: all below the falling candles' average), averages over past candles only "
                   "(the repo used the whole file), at most 10 entries per 24 candles, 1% target and 1% "
                   "stop; their 24x is the engine's 20x (xgb_backtrader.py)."),
    "gh_es_sma_ml": ("Fast and slow simple averages (4/150 bars ethansilvas, 8/20 Mun-Min) as inputs, "
                     "label 'next candle closes up or flat'; their SVM is replaced by gradient boosting; "
                     "long when it says up, short when down, always in and flipping "
                     "(machine_learning_trading_bot.ipynb)."),
    "gh_mal_lstm": ("Log return, 10-candle wobble, volume z-score, 10-20 average gap, RSI 14, ATR 14 and "
                    "volume change plus the recent path; label '+0.5% before -0.3% within 10 candles' "
                    "(short the mirror); their LSTM is replaced by gradient boosting (balanced classes); "
                    "enter above 80% sureness (setting 2: 65%), 1.5% target and 10% stop (trade_model.py, "
                    "backtest.py, config.py)."),
    "gh_mk_lstm": ("About 15 of its indicators (RSI/stoch/ROC/MFI/ATR/CCI 6, MACD 6/12, ADX 12, DPO 12, "
                   "force index, wicks) plus 12/24/48-candle returns; label FIXED to the FUTURE 6-candle "
                   "move (+1.2% to +3% buy, -3% to -1.2% sell, else hold, hold when ATR is above its "
                   "past-500-candle 75th percentile); their LSTM is replaced by gradient boosting; enter "
                   "on the most likely class, 5% target and 3% stop (lstm.ipynb)."),
    "gh_agi_xgb": ("Returns 3/6/12/24, RSI 14, 10/20 wobble, volume ratios, range position, 10/30 average "
                   "gap and range; label forward 12-candle return above +1% vs below -1% (middle dropped); "
                   "their XGBoost is replaced by gradient boosting (depth 4, lr 0.05); long when P(up) >= "
                   "0.55, held exactly 12 candles (setting 2: 24 candles, 0.60) "
                   "(skills/signal-classification/scripts/walk_forward_backtest.py)."),
    "gh_pyb_rf": ("The candle's log return and its 3 previous ones predict the next candle's return; "
                  "their random-forest regressor is replaced by gradient boosting; long when the forecast "
                  "is above 0, out when below (docs notebook 16, Time Series Models)."),
}

NOT_PORTED = {
    "KennethMartin06/ml-based-algorithmic-trading-signals: LSTM": (
        "its 10/20-day sequence LSTM would be another gradient-boosting stand-in on the same features, "
        "identical to gh_km_xgb's; left out of the ensemble too"),
    "edtechre/pybroker: other examples": (
        "the rotations, rankings and rebalances need several stocks at once; the linear-regression and "
        "GARCH examples are not its random-forest example, which is the one ported"),
    "agiprolabs/claude-trading-skills: other recipes": (
        "only the signal-classification recipe is a machine-learning signal; its Kalshi, copy-trading "
        "and on-chain recipes need data this engine does not have"),
}
