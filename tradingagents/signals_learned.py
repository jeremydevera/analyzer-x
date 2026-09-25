"""LEARNED formulas — one set per coin and timeframe ("Sep 25 Strat").

The operator, Sep 25, 2026: *"create another set of formula for each coin and
each of their timeframe ... each coin should have different formula because a
formula will work for 1 coin but will not work on other coin. I want you to
apply different confluence ... tp is greater than sl"*, and then *"i need you
to research and loop on whats the best confluence for each coin per
timeframe"*. The research loop is `formula_learner`; this module is what a
learned formula IS once it has been found, and how every caller — the grid,
the trade log, the UPDATE button and the live runner — turns one into
directions. One implementation, because a formula the grid measures one way
and the runner computes another is a strategy nobody ever tested.

A formula is DATA, not code: a JSON spec saved in `LEARNED_FILE`, named
`lx_<COIN>_<tf>_<n>`. It is a confluence of existing ingredients:

    {"name": "lx_KKRSTOCK_15m_1", "coin": "KKRSTOCK", "tf": "15m",
     "join": "and" | "cascade" | "vote",
     "legs": [{"trigger": "crsi",
               "confirm": [{"k": "volx", "x": 1.5},
                           {"k": "session", "h0": 13, "h1": 20}]}],
     "vote": {"sigs": ["crsi", "rsi2", "bb20"], "need": 2, "confirm": [...]},
     "tp": 0.012, "sl": 0.006, "learned": {...how it was found...}}

* `and`     — ONE leg: the trigger fires AND every confirm holds.
* `cascade` — several legs, the FIRST that fires wins (the operator's own
              "if confluence 1 is met then open else if confluence 2 ...").
* `vote`    — `need` of the listed signals agree on ONE side (a tie is no
              trade), then the confirms.

A trigger or an `agree`/`veto` ingredient is any signal in
`backtest_report.SIGNALS`, computed by the same `auto_trader._dirs_for_backtest`
the grid uses. The confirm kinds that are not signals are below (`FILTERS`).

THE CONTRACT every existing rule keeps (signals_conf): one direction per bar
(1 long, -1 short, 0 nothing); a bar reads only itself and the bars before it;
missing inputs ABSTAIN with zeros; and every lookback is at most 200 bars,
because an incremental pass hands a rule `market_sweep.CONTEXT_BARS` (300) of
history before the first new bar.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

PREFIX = "lx_"
LEARNED_FILE = Path(__file__).resolve().parent / "learned" / "sep25.json"
MAX_LOOKBACK = 200

_LOCK = threading.Lock()
_FILE: dict = {"mtime": None, "path": None, "specs": {}}
_REGISTERED: dict = {}


# ------------------------------------------------------------------ registry
def _load() -> dict:
    try:
        raw = json.loads(LEARNED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in (raw.get("formulas") or {}).items()
            if isinstance(v, dict) and str(k).startswith(PREFIX)}


def specs() -> dict:
    """Every learned formula this process knows: the saved file, plus any
    registered in-process (a GitHub machine measures what it just learned).

    THE FILE IS RE-READ WHEN IT CHANGES. The live runner is a long process:
    loading once would leave a runner started before a collect abstaining on
    every newly learned formula — a deployed lx_ strategy that silently never
    trades until someone restarts it. A stat per call is the price."""
    with _LOCK:
        try:
            mtime = LEARNED_FILE.stat().st_mtime_ns
        except OSError:
            mtime = None
        if mtime != _FILE["mtime"] or _FILE["path"] != LEARNED_FILE:
            _FILE.update(mtime=mtime, path=LEARNED_FILE, specs=_load())
        return {**_FILE["specs"], **_REGISTERED}


def register(new: dict) -> None:
    """Make formulas callable in THIS process without saving them."""
    with _LOCK:
        for k, v in (new or {}).items():
            if str(k).startswith(PREFIX):
                _REGISTERED[k] = v


def reload() -> None:
    """Forget what was read (the file is read again on the next call) and
    everything registered in-process."""
    with _LOCK:
        _FILE.update(mtime=None, path=None, specs={})
        _REGISTERED.clear()


def spec_for(key: str) -> dict | None:
    """The spec a signal key names: the exact name, or the longest learned
    name the key extends with "_" (the grid calls `<name>_gh_<tf>`)."""
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
    """The learned formulas that belong to ONE coin and timeframe — the only
    place each is measured (a learned formula is its coin's own)."""
    coin = str(coin).upper().replace("_USDT", "")
    return sorted(n for n, s in specs().items()
                  if str(s.get("coin", "")).upper() == coin and s.get("tf") == tf)


# --------------------------------------------------------------- ingredients
def ingredient_dirs(sig: str, tf: str, o, h, lo, c, v, ts, funding) -> np.ndarray:
    """One existing signal's directions over the frame — the grid's own call.

    Threshold rules (mom6/mom15/fade15) use the MIDDLE threshold of the
    timeframe's grid; the key carries its own spec, set and removed here, so
    nothing a caller registered is disturbed."""
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br

    iv, bs, _cap = br.TFS[tf]
    th = br.THRESHOLDS[tf][1] if sig in br.THRESH_SIGNALS else None
    key = f"{sig}_lxing_{tf}"
    at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs, "tp": .02,
                              "sl": .01, "threshold": .003 if th is None else th}
    try:
        dk = "rsi14_1h" if sig == "rsi14" else key
        d = at._dirs_for_backtest(dk, list(h), list(lo), list(c), opens=list(o),
                                  volume=list(v) if v is not None else None,
                                  ts=list(ts), funding=funding or [])
    except Exception:                                          # noqa: BLE001
        d = [0] * len(c)
    finally:
        at.STRATEGY_SPECS.pop(key, None)
    out = np.zeros(len(c), dtype=np.int8)
    k = min(len(d), len(c))
    out[:k] = np.sign(np.asarray(d[:k], dtype=float)).astype(np.int8)
    return out


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    out = np.empty_like(x, dtype=float)
    if not len(x):
        return out
    a = 2.0 / (n + 1.0)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _atr(h, lo, c, n: int = 14) -> np.ndarray:
    prev = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - lo, np.maximum(np.abs(h - prev), np.abs(lo - prev)))
    return _ema(tr, n)


def _rolling_mean_before(x: np.ndarray, n: int) -> np.ndarray:
    """Mean of the n bars BEFORE each bar (bar i itself excluded)."""
    cs = np.concatenate([[0.0], np.cumsum(x)])
    out = np.full(len(x), np.nan)
    for i in range(n, len(x)):
        out[i] = (cs[i] - cs[i - n]) / n
    return out


def _pct_rank(x: np.ndarray, n: int) -> np.ndarray:
    """Where bar i sits among the n bars ending at i (0 = lowest, 1 =
    highest); nan until n bars exist."""
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    win = np.lib.stride_tricks.sliding_window_view(x, n)
    out[n - 1:] = (win < win[:, -1:]).sum(axis=1) / float(n - 1)
    return out


class Features:
    """The non-signal inputs a confirm can read, computed once per frame and
    only when asked for. Every one is causal: bar i reads bars <= i."""

    def __init__(self, o, h, lo, c, v, ts, tf):
        from tradingagents import backtest_report as br

        self.o = np.asarray(o, dtype=float)
        self.h = np.asarray(h, dtype=float)
        self.l = np.asarray(lo, dtype=float)
        self.c = np.asarray(c, dtype=float)
        self.v = (np.asarray(v, dtype=float) if v is not None and len(v)
                  else np.zeros(len(c)))
        self.ts = np.asarray(ts, dtype=np.int64) if len(ts) else np.zeros(len(c), np.int64)
        self.bar_ms = int(br.TFS[tf][1]) * 1000
        self._c: dict = {}

    def get(self, name: str):
        if name not in self._c:
            self._c[name] = self._make(name)
        return self._c[name]

    def _make(self, name: str):
        kind, _, arg = name.partition(":")
        if kind == "ema":
            return _ema(self.c, int(arg))
        if kind == "atr":
            return _atr(self.h, self.l, self.c)
        if kind == "atrpct":
            a = self.get("atr") / np.where(self.c > 0, self.c, np.nan)
            return _pct_rank(np.nan_to_num(a), 150)
        if kind == "volratio":
            base = _rolling_mean_before(self.v, 20)
            with np.errstate(divide="ignore", invalid="ignore"):
                return np.where(base > 0, self.v / base, np.nan)
        if kind == "hour":
            # the hour the ORDER goes in: the next bar's open, in UTC
            return ((self.ts + self.bar_ms) // 3_600_000) % 24
        raise KeyError(name)


# The confirm kinds that are not signals, and the settings the search may
# try. `side` "with" follows the trend, "against" fades it.
FILTERS = {
    "trend":   {"n": (50, 100, 200), "side": ("with", "against")},
    "htf":     {"n": (100, 200), "side": ("with", "against")},
    "session": {"h0": (0, 6, 12, 13, 18), "len": (6, 8, 12)},
    "atr":     {"band": ((0.0, 0.5), (0.5, 1.0), (0.2, 0.8))},
    "volx":    {"x": (1.2, 1.5, 2.0)},
    "stretch": {"x": (1.0, 1.5, 2.0)},
}


def _confirm_ok(cf: dict, d: np.ndarray, sig_dirs: dict, feats: Features) -> np.ndarray:
    """Where one confirm HOLDS for the trade direction `d` (1/-1/0 per bar)."""
    k = cf.get("k")
    n = len(d)
    long_, short_ = d > 0, d < 0
    if k in ("agree", "veto"):
        other = sig_dirs[cf["sig"]]
        if k == "veto":
            return ~((long_ & (other < 0)) | (short_ & (other > 0)))
        w = max(1, min(int(cf.get("within", 1)), MAX_LOOKBACK))
        up = np.convolve((other > 0).astype(float), np.ones(w))[:n] > 0
        dn = np.convolve((other < 0).astype(float), np.ones(w))[:n] > 0
        return (long_ & up) | (short_ & dn)
    c = feats.c
    if k == "trend":
        e = feats.get(f"ema:{min(int(cf['n']), MAX_LOOKBACK)}")
        above, below = c > e, c < e
        if cf.get("side", "with") == "with":
            return (long_ & above) | (short_ & below)
        return (long_ & below) | (short_ & above)
    if k == "htf":
        # the slow average's direction over the last 20 bars — the bigger
        # picture, inside the 200-bar lookback
        e = feats.get(f"ema:{min(int(cf['n']), MAX_LOOKBACK)}")
        prev = np.concatenate([np.full(20, np.nan), e[:-20]])
        rising, falling = e > prev, e < prev
        if cf.get("side", "with") == "with":
            return (long_ & rising) | (short_ & falling)
        return (long_ & falling) | (short_ & rising)
    if k == "session":
        hr = feats.get("hour")
        h0, ln = int(cf["h0"]) % 24, int(cf["len"])
        return ((hr - h0) % 24) < ln
    if k == "atr":
        p = feats.get("atrpct")
        lo, hi = float(cf["lo"]), float(cf["hi"])
        return (p >= lo) & (p <= hi)
    if k == "volx":
        r = feats.get("volratio")
        return np.nan_to_num(r, nan=0.0) >= float(cf["x"])
    if k == "stretch":
        # price stretched away from its 20-bar average, on the side the trade
        # fades: a long below it, a short above it
        e, a = feats.get("ema:20"), feats.get("atr")
        dist = (c - e) / np.where(a > 0, a, np.nan)
        x = float(cf["x"])
        return (long_ & (np.nan_to_num(dist) <= -x)) | (short_ & (np.nan_to_num(dist) >= x))
    return np.zeros(n, dtype=bool)          # an unknown kind never lets a trade through


def compose(spec: dict, sig_dirs: dict, feats: Features) -> np.ndarray:
    """A spec's directions from its ingredients' directions — the ONE place
    the joins are defined, used by the search and by every caller alike."""
    n = len(feats.c)

    def leg_out(d: np.ndarray, confirms) -> np.ndarray:
        d = d.astype(np.int8)
        ok = d != 0
        for cf in confirms or ():
            ok &= _confirm_ok(cf, d, sig_dirs, feats)
        return np.where(ok, d, 0).astype(np.int8)

    join = spec.get("join", "and")
    if join == "vote":
        vt = spec.get("vote") or {}
        up = np.zeros(n, dtype=int)
        dn = np.zeros(n, dtype=int)
        for s in vt.get("sigs") or ():
            up += sig_dirs[s] > 0
            dn += sig_dirs[s] < 0
        need = int(vt.get("need", 2))
        d = np.where((up >= need) & (up > dn), 1,
                     np.where((dn >= need) & (dn > up), -1, 0))
        return leg_out(d, vt.get("confirm"))
    out = np.zeros(n, dtype=np.int8)
    legs = spec.get("legs") or []
    if join == "and":
        legs = legs[:1]
    for leg in legs:
        got = leg_out(sig_dirs[leg["trigger"]], leg.get("confirm"))
        out = np.where(out != 0, out, got).astype(np.int8)
    return out


def ingredients(spec: dict) -> set:
    """Every existing signal a spec reads."""
    out = set()
    for leg in spec.get("legs") or ():
        out.add(leg["trigger"])
        out.update(cf["sig"] for cf in leg.get("confirm") or () if "sig" in cf)
    vt = spec.get("vote") or {}
    out.update(vt.get("sigs") or ())
    out.update(cf["sig"] for cf in vt.get("confirm") or () if "sig" in cf)
    return out


def dirs_for(spec: dict, o, h, lo, c, v, ts, funding=None) -> list[int]:
    """A learned formula's directions over a frame — what the grid, the trade
    log and the runner all call (through `auto_trader`)."""
    n = len(c)
    if not n:
        return []
    tf = spec.get("tf") or "1h"
    feats = Features(o if len(o) else c, h, lo, c, v, ts if len(ts) else [0] * n, tf)
    sig_dirs = {s: ingredient_dirs(s, tf, o if len(o) else c, h, lo, c, v,
                                   ts if len(ts) else [0] * n, funding)
                for s in ingredients(spec)}
    return [int(x) for x in compose(spec, sig_dirs, feats)]


def describe(spec: dict) -> str:
    """What a formula checks, in plain words (the report's column)."""
    def cf_words(cf):
        k = cf.get("k")
        if k == "agree":
            return f"{cf['sig']} agrees"
        if k == "veto":
            return f"unless {cf['sig']} disagrees"
        if k == "trend":
            return f"{'with' if cf.get('side') == 'with' else 'against'} the {cf['n']}-bar trend"
        if k == "htf":
            return f"{'with' if cf.get('side') == 'with' else 'against'} the slow {cf['n']}-bar direction"
        if k == "session":
            return f"only {int(cf['h0']):02d}:00-{(int(cf['h0']) + int(cf['len'])) % 24:02d}:00 UTC"
        if k == "atr":
            return f"volatility {cf['lo']:.1f}-{cf['hi']:.1f} of normal"
        if k == "volx":
            return f"volume {cf['x']}x its average"
        if k == "stretch":
            return f"price {cf['x']} ATR from its average"
        return str(k)

    join = spec.get("join", "and")
    if join == "vote":
        vt = spec.get("vote") or {}
        s = f"{vt.get('need')} of {', '.join(vt.get('sigs') or [])} agree"
        extra = [cf_words(c) for c in vt.get("confirm") or ()]
        return s + (" + " + " + ".join(extra) if extra else "")
    parts = []
    for leg in (spec.get("legs") or [])[: (1 if join == "and" else None)]:
        extra = [cf_words(c) for c in leg.get("confirm") or ()]
        parts.append(leg["trigger"] + (" + " + " + ".join(extra) if extra else ""))
    return (" · else " if join == "cascade" else "").join(parts)
