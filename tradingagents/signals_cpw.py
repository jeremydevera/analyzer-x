"""THE CRYPTO-PREDICTOR STRATEGIES (Oct 19, 2026) — the seven entry rules of
github.com/jeremydevera/Crypto-Predictor-Web with every combination of their
main switches, as one strategy family of this backtest. The operator: "use the
strategy and switches and come up with best combination for all coins", then,
asked about exits: "Im talking about the switches used for the strategy in the
repo im not talking about the tp sl, use the best combination and see what's
setting will win" — so the switches vary here and the stop/target grid closes
the trades, as for every other strategy.

A strategy is a NAME, `cp_<strategy>_<code>`: one letter and one digit per
switch, the digit the index of its value in SWITCHES, 0 being the app's own
preset. `cp_ecb_s0v0o0f0h0r0` is Elite Context Breakout exactly as the app
ships it; `cp_ecb_s1v0o0f0h0r0` is the same with the session filter off. The
settings are in the name, so the grid, the trade list and the runner read one
spec, and a row's id names the setting it was measured with.

One implementation (as signals_learned): `dirs_for` is what the grid measures
with and what the runner and the trade list call — `cpw_rules` holds the rules,
`cpw_indicators` the app's indicators. Directions per bar: 1 long, -1 short, 0
nothing.
"""
from __future__ import annotations

import itertools
import threading

from tradingagents import cpw_rules as rules

PREFIX = "cp_"

NAMES = {
    "ecb": "Elite Context Breakout",
    "err": "Elite Retest Reversal",
    "br": "Breakout Retest",
    "cm": "Confirmation Model",
    "fg": "FluxGate Dual Engine",
    "st": "Supertrend + RelVol",
    "bb": "BB Stoch S/D",
}

# (letter, setting, values) — values[0] is the app's preset (tradingStore.ts
# DEFAULT_*_FILTERS); what each one does is in the strategy's decide_ function
SWITCHES = {
    "ecb": (("s", "session", (True, False)), ("v", "vol", ("medium", "any", "high")),
            ("o", "ob", (True, False)), ("f", "fvg", (False, True)),
            ("h", "htfema", (False, True)), ("r", "retest", (False, True))),
    "err": (("s", "session", (True, False)), ("o", "ob", (True, False)),
            ("a", "agrade", (False, True)), ("h", "htfema50", (False, True)),
            ("k", "stoch", (False, True)), ("m", "maxbars", (False, True))),
    "br": (("e", "model", ("retest_confirm", "retest_hold", "breakout_close")),
           ("h", "htf", (True, False)), ("x", "adx", (True, False)),
           ("u", "volume", (True, False)), ("r", "retest", (True, False))),
    "cm": (("w", "sweep", (True, False)), ("f", "fvg", (True, False)),
           ("c", "cisdretest", (False, True)), ("o", "ob", (False, True)),
           ("u", "volume", (False, True)), ("s", "session", (False, True))),
    "fg": (("s", "session", (True, False)), ("x", "adx", (True, False)),
           ("t", "structure", (True, False)), ("m", "momentum", (True, False)),
           ("u", "volume", (True, False)), ("h", "htf", (True, False)),
           ("q", "minq", (0, 5))),
    "st": (("f", "flip", (True, False)), ("u", "relvol", (True, False)),
           ("h", "htf", (True, False)), ("x", "adx", (True, False)),
           ("i", "impulse", (False, True)), ("d", "di", (False, True))),
    "bb": (("z", "zone", (True, False)), ("j", "reject", (True, False)),
           ("k", "stochx", (True, False)), ("c", "revcandle", (True, False)),
           ("x", "maxadx", (True, False)), ("h", "htf200", (False, True))),
}

_RAW = {
    "ecb": lambda ctx: rules.raw_elite(ctx, "ecb"),
    "err": lambda ctx: rules.raw_elite(ctx, "err"),
    "br": rules.raw_br,
    "cm": rules.raw_cm,
    "fg": rules.raw_fg,
    "st": rules.raw_st,
    "bb": rules.raw_bb,
}
_DECIDE = {
    "ecb": rules.decide_ecb, "err": rules.decide_err, "br": rules.decide_br,
    "cm": rules.decide_cm, "fg": rules.decide_fg, "st": rules.decide_st,
    "bb": rules.decide_bb,
}


def name_of(strategy: str, digits) -> str:
    sw = SWITCHES[strategy]
    return PREFIX + strategy + "_" + "".join(f"{s[0]}{d}" for s, d in zip(sw, digits))


def variants(strategies=None) -> list:
    """Every switch combination of the given strategies (all seven by
    default), app preset first."""
    out = []
    for st in (strategies or NAMES):
        ranges = [range(len(s[2])) for s in SWITCHES[st]]
        out += [name_of(st, digits) for digits in itertools.product(*ranges)]
    return out


def spec_for(key: str) -> dict | None:
    """The settings a name holds, or None for a name that is not one of
    ours. The grid calls `<name>_gh_<tf>`, so anything after the code is
    ignored."""
    k = str(key)
    if not k.startswith(PREFIX):
        return None
    parts = k[len(PREFIX):].split("_")
    if len(parts) < 2 or parts[0] not in SWITCHES:
        return None
    st, code = parts[0], parts[1]
    sw = SWITCHES[st]
    if len(code) != 2 * len(sw):
        return None
    out = {}
    digits = []
    for j, (letter, setting, values) in enumerate(sw):
        if code[2 * j] != letter or not code[2 * j + 1].isdigit():
            return None
        d = int(code[2 * j + 1])
        if d >= len(values):
            return None
        out[setting] = values[d]
        digits.append(d)
    return {"strategy": st, "name": name_of(st, digits), "switches": out}


def describe(spec: dict) -> str:
    """'Elite Context Breakout · session off, ob on, ...' for a screen."""
    parts = []
    for setting, val in spec["switches"].items():
        if isinstance(val, bool):
            parts.append(f"{setting} {'on' if val else 'off'}")
        else:
            parts.append(f"{setting} {val}")
    return f"{NAMES[spec['strategy']]} · " + ", ".join(parts)


# A frame's work is shared by every switch setting tried on it: the grid
# calls dirs_for once per name with the same candle lists, so the frame and
# each strategy's per-bar facts are kept for the last few frames.
_LOCK = threading.Lock()
_FRAMES: dict = {}
_KEEP = 4


def _fingerprint(c, ts) -> tuple:
    n = len(c)
    return (n, int(ts[0]) if n and len(ts) else 0, int(ts[-1]) if n and len(ts) else 0,
            float(c[0]) if n else 0.0, float(c[n // 2]) if n else 0.0,
            float(c[-1]) if n else 0.0)


def _frame(o, h, lo, c, v, ts):
    fp = _fingerprint(c, ts)
    with _LOCK:
        got = _FRAMES.get(fp)
        if got is not None:
            return got
    ctx = rules.Ctx(o if len(o) else c, h, lo, c, v, ts)
    entry = {"ctx": ctx, "raw": {}}
    with _LOCK:
        if len(_FRAMES) >= _KEEP:
            _FRAMES.pop(next(iter(_FRAMES)))
        _FRAMES[fp] = entry
    return entry


def dirs_for(spec: dict, o, h, lo, c, v, ts, funding=None) -> list:
    n = len(c)
    if not n:
        return []
    fr = _frame(list(o), list(h), list(lo), list(c), list(v) if v is not None else [],
                list(ts) if ts is not None else [])
    st = spec["strategy"]
    raw = fr["raw"].get(st)
    if raw is None:
        raw = _RAW[st](fr["ctx"])
        fr["raw"][st] = raw
    return [int(x) for x in _DECIDE[st](fr["ctx"], raw, spec["switches"])]
