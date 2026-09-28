"""Gradient-boosted decision trees in numpy — the Sep 27 ML models.

Operator, Sep 27, 2026, choosing between three kinds: "Decision trees". Many
small yes/no questions ("price fell 2% in 3 bars AND volume doubled") voted
together into one probability that a trade reaches its target first.

No scikit-learn: the runner, this PC and the GitHub machines all have numpy
and nothing else, and a model the runner cannot evaluate is a strategy that
never trades. Deterministic (fixed seed, rounded thresholds and leaves), and
a model is plain JSON, so what GitHub trained is exactly what the runner runs.
"""
from __future__ import annotations

import math

import numpy as np

N_TREES = 30
DEPTH = 3
LR = 0.1
MIN_LEAF = 40
BINS = 32
SUBSAMPLE = 0.8
SEED = 7
L2 = 1.0


def _sig(x: float) -> float:
    """Six significant digits: what JSON will carry, used while TRAINING too,
    so a round trip cannot move a single prediction."""
    return float(f"{float(x):.6g}")


def _edges(col: np.ndarray) -> np.ndarray:
    qs = np.quantile(col, np.linspace(0.0, 1.0, BINS + 1)[1:-1])
    return np.unique(np.asarray([_sig(q) for q in qs], dtype=float))


def _grow(nodes, B, X, g, h, rows, edges, depth, gain) -> int:
    G, H = float(g[rows].sum()), float(h[rows].sum())
    me = len(nodes)
    nodes.append(None)
    best = None
    if depth < DEPTH and len(rows) >= 2 * MIN_LEAF:
        parent = G * G / (H + L2)
        for j in range(B.shape[1]):
            nb = len(edges[j]) + 1
            if nb < 2:
                continue
            b = B[rows, j]
            gs = np.bincount(b, weights=g[rows], minlength=nb)
            hs = np.bincount(b, weights=h[rows], minlength=nb)
            cs = np.bincount(b, minlength=nb)
            GL, HL, CL = np.cumsum(gs)[:-1], np.cumsum(hs)[:-1], np.cumsum(cs)[:-1]
            GR, HR, CR = G - GL, H - HL, len(rows) - CL
            ok = (CL >= MIN_LEAF) & (CR >= MIN_LEAF)
            if not ok.any():
                continue
            gains = GL * GL / (HL + L2) + GR * GR / (HR + L2) - parent
            gains[~ok] = -np.inf
            k = int(np.argmax(gains))
            if gains[k] > 1e-12 and (best is None or gains[k] > best[0]):
                best = (float(gains[k]), j, k)
    if best is None:
        nodes[me] = [-1, _sig(-G / (H + L2) * LR)]
        return me
    gv, j, k = best
    gain[j] += gv
    thr = float(edges[j][k])                  # bin <= k  <=>  x < edges[k]
    go = X[rows, j] < thr
    left = _grow(nodes, B, X, g, h, rows[go], edges, depth + 1, gain)
    right = _grow(nodes, B, X, g, h, rows[~go], edges, depth + 1, gain)
    nodes[me] = [int(j), thr, left, right]
    return me


def _apply(nodes, X: np.ndarray) -> np.ndarray:
    out = np.empty(len(X))

    def walk(i, rows):
        nd = nodes[i]
        if nd[0] == -1:
            out[rows] = nd[1]
            return
        go = X[rows, nd[0]] < nd[1]           # NaN goes right
        walk(nd[2], rows[go])
        walk(nd[3], rows[~go])

    walk(0, np.arange(len(X)))
    return out


def fit(X, y, *, seed: int = SEED) -> dict:
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    if X.ndim != 2 or len(X) != len(y) or not len(y):
        raise ValueError("fit() needs a 2-D X with one label per row")
    if not np.isfinite(X).all():
        raise ValueError("fit() takes finite rows only; drop NaN/inf rows first")
    n, nf = X.shape
    edges = [_edges(X[:, j]) for j in range(nf)]
    B = np.empty((n, nf), dtype=np.int16)
    for j in range(nf):
        B[:, j] = np.searchsorted(edges[j], X[:, j], side="right")
    p0 = min(max(float(y.mean()), 1e-4), 1 - 1e-4)
    base = _sig(math.log(p0 / (1 - p0)))
    F = np.full(n, base)
    rng = np.random.default_rng(seed)
    trees, gain = [], np.zeros(nf)
    for _ in range(N_TREES):
        p = 1.0 / (1.0 + np.exp(-F))
        g, h = p - y, np.maximum(p * (1 - p), 1e-9)
        rows = np.flatnonzero(rng.random(n) < SUBSAMPLE)
        nodes: list = []
        _grow(nodes, B, X, g, h, rows, edges, 0, gain)
        trees.append(nodes)
        F = F + _apply(nodes, X)
    return {"v": 1, "base": base, "trees": trees, "nf": int(nf),
            "gain": [round(float(x), 4) for x in gain]}


def predict(model: dict, X) -> np.ndarray:
    X = np.asarray(X, dtype=float)
    F = np.full(len(X), float(model["base"]))
    for nodes in model["trees"]:
        F = F + _apply(nodes, X)
    return 1.0 / (1.0 + np.exp(-F))


def importance(model: dict, names) -> list:
    """The clues the trees leaned on most, by total split gain."""
    g = list(model.get("gain") or [])
    order = sorted(range(len(g)), key=lambda j: (-g[j], j))
    return [names[j] for j in order if g[j] > 0]
