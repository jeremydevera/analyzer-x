"""THE PRO TRADER FAMILIES (Oct 20, 2026), prefix `pt_`.

The operator: "think of your self as a professional trader, meaning you will
need to research on proven and working indicators out there", with the
approved prompt's rules: at most 12 families, each with a pre-registered
expectation and at most 3 knobs, digit 0 of every knob the literature's
default; one implementation for the runner (`auto_trader.signal_for`, last
bar) and the backtest (`_dirs_for_backtest`, every bar); no bar reads a later
one. The research behind each family: docs/research/2026-10-20-pro-trader-survey.md.

Every indicator is fixed-window (`pro_indicators`), and every family's whole
lookback stays within `pro_indicators.MAX_LOOKBACK` bars, so the runner's 299
closed candles and the backtest's deep window compute the same signal.

A name carries its settings: pt_<family>_<letter><digit>... — e.g.
pt_tsm_l0v1 is time-series momentum with lookback value 0 and volatility gate
value 1. Unknown names abstain (`spec_for` -> None).

`rand` is not a strategy: it is the luck baseline — seeded random entries at a
fixed rate, measured exactly like every family, so "beats random entries with
the same stop and target on the same coin" is a measured comparison.
"""
from __future__ import annotations

import hashlib
import itertools
import threading

import numpy as np

PREFIX = "pt_"

# stop/target pairs (percent) that can pay 2:1 after a ~0.23% round trip, stop
# 3% or less (rows over 2% are flagged: the rooms cap stops at 2%); each must
# be a pair the grid measures (backtest_report.pairs_for)
BARRIERS_PCT = {
    "15m": ((0.4, 1.5), (0.4, 2.0), (0.6, 2.0), (0.6, 2.5), (0.8, 2.5), (1.0, 3.0)),
    "30m": ((0.5, 2.0), (0.6, 2.5), (0.8, 2.5), (1.0, 3.0), (1.2, 4.0), (1.5, 5.0)),
    "1h": ((0.7, 2.5), (1.0, 3.0), (1.2, 4.0), (1.5, 5.0), (2.0, 6.0), (3.0, 8.0)),
    "4h": ((1.0, 3.0), (1.5, 4.0), (1.5, 5.0), (2.0, 6.0), (2.5, 8.0), (3.0, 8.0)),
    "1d": ((1.5, 5.0), (2.0, 6.0), (2.5, 8.0), (3.0, 10.0)),
}


# ------------------------------------------------------------------ families
#
# Each family: title, knobs ((letter, setting, values) x <= 3, values[0] the
# literature's default), fn(ctx, settings) -> np.int8 directions per bar.

def _edge(cond_long: np.ndarray, cond_short: np.ndarray) -> np.ndarray:
    """+1 / -1 on the bar a condition BECOMES true (not every bar while it
    holds), 0 elsewhere."""
    out = np.zeros(len(cond_long), dtype=np.int8)
    cl = np.nan_to_num(cond_long, nan=0).astype(bool)
    cs = np.nan_to_num(cond_short, nan=0).astype(bool)
    prev_l = np.r_[False, cl[:-1]]
    prev_s = np.r_[False, cs[:-1]]
    out[cl & ~prev_l] = 1
    out[cs & ~prev_s & ~(cl & ~prev_l)] = -1
    return out


def _rand(ctx, s) -> np.ndarray:
    """Seeded random entries: each bar is an entry with probability `rate`,
    long or short at random — decided by a hash of the seed and the bar's own
    time, so the runner and the backtest draw the same coin for the same bar
    whatever frame they hold."""
    out = np.zeros(ctx.n, dtype=np.int8)
    rate = float(s["rate"])
    for i, t in enumerate(ctx.ts):
        h = hashlib.blake2b(f"{s['seed']}:{int(t)}".encode(), digest_size=8).digest()
        u = int.from_bytes(h[:4], "big") / 2 ** 32
        if u < rate:
            out[i] = 1 if h[4] & 1 else -1
    return out


FAMILIES: dict = {
    "rand": {"title": "Random entries (the luck baseline)",
             "knobs": (("s", "seed", (0, 1, 2)), ("r", "rate", (0.01, 0.03))),
             "fn": _rand, "lookback": 0},
}


# ------------------------------------------------------------------- names

def name_of(family: str, digits) -> str:
    kn = FAMILIES[family]["knobs"]
    return PREFIX + family + "_" + "".join(f"{k[0]}{d}" for k, d in zip(kn, digits, strict=True))


def variants(families=None) -> list[str]:
    out = []
    for fam in families or FAMILIES:
        kn = FAMILIES[fam]["knobs"]
        out += [name_of(fam, d) for d in itertools.product(*[range(len(k[2])) for k in kn])]
    return out


def spec_for(key: str) -> dict | None:
    """The family and settings a name holds, or None. Anything after the code
    (the grid's `_gh_<tf>`) is ignored."""
    k = str(key)
    if not k.startswith(PREFIX):
        return None
    parts = k[len(PREFIX):].split("_")
    if len(parts) < 2 or parts[0] not in FAMILIES:
        return None
    fam, code = parts[0], parts[1]
    kn = FAMILIES[fam]["knobs"]
    if len(code) != 2 * len(kn):
        return None
    settings, digits = {}, []
    for j, (letter, setting, values) in enumerate(kn):
        if code[2 * j] != letter or not code[2 * j + 1].isdigit():
            return None
        d = int(code[2 * j + 1])
        if d >= len(values):
            return None
        settings[setting] = values[d]
        digits.append(d)
    return {"family": fam, "name": name_of(fam, digits), "settings": settings,
            "digits": tuple(digits)}


def describe(spec: dict) -> str:
    fam = FAMILIES[spec["family"]]
    return fam["title"] + " · " + ", ".join(f"{k} {v}" for k, v in spec["settings"].items())


# ------------------------------------------------------------- the frame

class Ctx:
    """One frame's candles, and the indicators every setting shares."""

    def __init__(self, o, h, lo, c, v, ts, funding=None):
        self.o = np.asarray(o, dtype=float)
        self.h = np.asarray(h, dtype=float)
        self.l = np.asarray(lo, dtype=float)
        self.c = np.asarray(c, dtype=float)
        self.v = np.asarray(v, dtype=float) if v is not None and len(v) else np.zeros(len(c))
        self.ts = [int(x) for x in ts]
        self.funding = funding or []
        self.n = len(self.c)
        self._memo: dict = {}

    def memo(self, key, make):
        if key not in self._memo:
            self._memo[key] = make()
        return self._memo[key]


_LOCK = threading.Lock()
_FRAMES: dict = {}
_KEEP = 4


def _fingerprint(c, ts) -> tuple:
    n = len(c)
    return (n, int(ts[0]) if n else 0, int(ts[-1]) if n else 0,
            float(c[0]) if n else 0.0, float(c[n // 2]) if n else 0.0, float(c[-1]) if n else 0.0)


def _ctx(o, h, lo, c, v, ts, funding) -> Ctx:
    key = _fingerprint(c, ts)
    with _LOCK:
        hit = _FRAMES.get(key)
        if hit is None:
            hit = Ctx(o, h, lo, c, v, ts, funding)
            _FRAMES[key] = hit
            while len(_FRAMES) > _KEEP:
                _FRAMES.pop(next(iter(_FRAMES)))
        return hit


def dirs_for(spec: dict, o, h, lo, c, v, ts, funding=None) -> list[int]:
    """+1 / -1 / 0 for every bar of the frame — the runner reads the last."""
    if spec is None or spec.get("family") not in FAMILIES:
        return [0] * len(c)
    ctx = _ctx(o, h, lo, c, v, ts, funding)
    out = FAMILIES[spec["family"]]["fn"](ctx, spec["settings"])
    return [int(x) for x in out]
