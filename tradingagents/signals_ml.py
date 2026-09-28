"""THE SEP 27 ML MODELS — one set per coin and timeframe, and how every caller
(the grid, the trade log, the UPDATE button and the live runner) turns one
into directions. One implementation, for the reason signals_learned states:
a strategy the grid measures one way and the runner computes another is a
strategy nobody tested.

A model is DATA: a spec saved in MODEL_FILE (gzipped JSON) named
`ml_<COIN>_<tf>_<n>`, holding up to two tree models (ml_trees) — one that
scores "a LONG from here reaches TP before SL", one for SHORT — and the
confidence each must reach. Directions per bar: 1 long, -1 short, 0 nothing;
a bar with any missing clue abstains.
"""
from __future__ import annotations

import gzip
import json
import threading
import time
from pathlib import Path

import numpy as np

PREFIX = "ml_"
MODEL_FILE = Path(__file__).resolve().parent / "learned" / "sep27_ml.json.gz"

_LOCK = threading.Lock()
_FILE: dict = {"mtime": None, "path": None, "specs": {}}
_REGISTERED: dict = {}


def read_file() -> dict:
    try:
        with gzip.open(MODEL_FILE, "rt", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError, EOFError):
        return {}
    return {k: v for k, v in (raw.get("models") or {}).items()
            if isinstance(v, dict) and str(k).startswith(PREFIX)}


def write_file(models: dict, run_id=None, max_bytes: int | None = None) -> int:
    """Write the whole model file atomically; returns its size in bytes.

    `max_bytes`, when given, is a CEILING: the new file is written to a
    temp path first, and if it would land bigger than the ceiling the temp
    file is discarded and MODEL_FILE is left untouched — a caller that asks
    for a size limit must never get a partially-replaced store, and never a
    silent no-op either, so this raises."""
    from tradingagents.positions_view import fmt_when

    MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = MODEL_FILE.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump({"about": "Sep 27 ML — decision-tree strategies, one set per "
                            "coin and timeframe (tradingagents/ml_learner.py)",
                   "run": run_id, "collected": fmt_when(time.time()),
                   "models": dict(sorted(models.items()))},
                  fh, separators=(",", ":"))
    size = tmp.stat().st_size
    if max_bytes is not None and size > max_bytes:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"the Sep 27 ML model file would be {size / 1e6:.1f} MB, past its "
            f"{max_bytes / 1e6:g} MB ceiling — not replacing it")
    tmp.replace(MODEL_FILE)
    reload()
    return MODEL_FILE.stat().st_size


def specs() -> dict:
    """Every model this process knows: the file (RE-READ WHEN IT CHANGES, so
    a runner started before a collect does not abstain for ever) plus any
    registered in-process (a GitHub machine measures what it just learned)."""
    with _LOCK:
        try:
            mtime = MODEL_FILE.stat().st_mtime_ns
        except OSError:
            mtime = None
        if mtime != _FILE["mtime"] or _FILE["path"] != MODEL_FILE:
            _FILE.update(mtime=mtime, path=MODEL_FILE, specs=read_file())
        return {**_FILE["specs"], **_REGISTERED}


def register(new: dict) -> None:
    with _LOCK:
        for k, v in (new or {}).items():
            if str(k).startswith(PREFIX):
                _REGISTERED[k] = v


def reload() -> None:
    with _LOCK:
        _FILE.update(mtime=None, path=None, specs={})
        _REGISTERED.clear()


def spec_for(key: str) -> dict | None:
    """The exact name, or the longest model name the key extends with "_"."""
    if not str(key).startswith(PREFIX):
        return None
    got = specs()
    if key in got:
        return got[key]
    for name in sorted(got, key=len, reverse=True):
        if key.startswith(name + "_"):
            return got[name]
    return None


def for_pair(coin: str, tf: str) -> list[str]:
    coin = str(coin).upper().replace("_USDT", "")
    return sorted(n for n, s in specs().items()
                  if str(s.get("coin", "")).upper() == coin and s.get("tf") == tf)


def compose(p: dict, thr: dict, sides: str) -> np.ndarray:
    """Directions from the side models' probabilities — the ONE place the
    rule is written, used by the learner and by every caller alike."""
    n = len(next(iter(p.values()))) if p else 0
    long_m = np.zeros(n)
    short_m = np.zeros(n)
    if sides in ("both", "long") and "long" in p:
        with np.errstate(invalid="ignore"):
            long_m = np.where(p["long"] >= thr["long"], p["long"] - thr["long"] + 1e-12, 0.0)
    if sides in ("both", "short") and "short" in p:
        with np.errstate(invalid="ignore"):
            short_m = np.where(p["short"] >= thr["short"], p["short"] - thr["short"] + 1e-12, 0.0)
    long_m, short_m = np.nan_to_num(long_m), np.nan_to_num(short_m)
    return np.where(long_m > short_m, 1, np.where(short_m > long_m, -1, 0)).astype(np.int8)


def dirs_for(spec: dict, o, h, lo, c, v, ts, funding=None) -> list[int]:
    from tradingagents import ml_features as mf, ml_trees as mt

    n = len(c)
    if not n:
        return []
    # A MODEL AND ITS CLUES MUST MATCH (Sep 28, 2026 review): a model fitted
    # on another clue set reads column j as a different clue, so it abstains
    # everywhere rather than trade on numbers it never learned from
    if spec.get("features") != mf.VERSION:
        return [0] * n
    X = mf.features(o if len(o) else c, h, lo, c, v, ts if len(ts) else [0] * n,
                    funding or [], spec.get("tf") or "1h")
    models = spec.get("models") or {}
    if any(not isinstance(m, dict) or m.get("nf") != X.shape[1]
           for m in models.values()):
        return [0] * n
    ok = np.isfinite(X).all(axis=1)
    p = {}
    for side, model in models.items():
        q = np.full(n, np.nan)
        if ok.any():
            q[ok] = mt.predict(model, X[ok])
        p[side] = q
    if not p:
        return [0] * n
    return [int(x) for x in compose(p, spec.get("thr") or {}, spec.get("sides", "both"))]


def describe(spec: dict) -> str:
    from tradingagents import ml_features as mf, ml_trees as mt

    gain: dict = {}
    for model in (spec.get("models") or {}).values():
        if not isinstance(model, dict):
            continue
        # A MODEL FROM ANOTHER CLUE SET (an older VERSION had a 21st clue,
        # funding) carries a longer `gain` vector than FEATURES names; its
        # unknown indexes are skipped, never an IndexError on the collect
        # (Task 8 harddev, item e)
        known = dict(model, gain=list(model.get("gain") or [])[:len(mf.FEATURES)])
        for rank, name in enumerate(mt.importance(known, mf.FEATURES)):
            gain[name] = gain.get(name, 0) + (len(mf.FEATURES) - rank)
    top = sorted(gain, key=lambda k: (-gain[k], k))[:4]
    side = {"both": "long and short", "long": "long only",
            "short": "short only"}.get(spec.get("sides"), "")
    pct = round((1 - float(spec.get("q", 0.9))) * 100)
    return (f"decision trees, {side}, its {pct}% most confident moments"
            + (f" · reads most: {', '.join(top)}" if top else ""))
