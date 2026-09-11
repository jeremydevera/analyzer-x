"""NON-LINEAR confluence rules: cascades, votes and vetoes.

Operator, Sep 11, 2026, after reading the Preset Confluence artifact:

    "Make sure the formula for the strategy is not linear, meaning for example
    if i met this criteria then open a position ... you can combine each
    different confluence, or you can use (if confluence 1 is met then open
    else if confluence 2 is met open as well else if confluence 3 is met open
    ad well) this is what i call not linear"

and, a minute later: *"you should use differenct approach per coin per
timeframe"*.

WHAT IS NEW HERE. Every rule in `signals_conf` is ONE setup, optionally
gated — a straight line from conditions to a direction. These ten are
combinations of those setups, and none of them is a straight line:

  * a PRIORITY CASCADE takes the first setup that fires and stops looking, so
    which setup produced a trade depends on what the earlier ones did;
  * a VOTE needs N of M setups agreeing on the SAME side, so no single setup
    can open a trade by itself;
  * a VETO lets one setup open a trade unless another disagrees;
  * an ESCALATOR asks for less agreement the stronger the gate that passed —
    two of five is enough behind the 200-bar trend, three of five without it.

WHICH SETUPS ARE IN THEM, and why those. The artifact measured the whole
market and screened the still-working way (green in June, July AND August
separately). Of the 197 rows that survived, the members are:

    cf_soup1  166 rows      cf_mom     16 rows
    cf_soup     8 rows      cf_mom_l1   7 rows

so `soup1` and `mom` lead every cascade. `donch` and `ttm` join the votes for
breadth, and the four setups that appear only in the research ledger's 4-HOUR
ranking (bosfvg, obretest, stflip, diadx) get their own cascade.

PER COIN PER TIMEFRAME is not decided here. Every rule below is measured on
every coin and every timeframe by the sweep, and the winner is whichever row
that coin+timeframe actually scored best — which is the operator's own
instruction, and the only honest way to pick.

Contract, unchanged from signals_conf: one direction per bar (1 long, -1
short, 0 nothing), a bar may read only itself and the bars before it, and a
rule whose inputs are missing ABSTAINS with zeros rather than guessing.
"""
from __future__ import annotations

# Which setups each cascade may consult, in the order it consults them.
# Names are `signals_conf._SETUPS` keys.
LEAD = ("soup1", "mom", "soup", "donch")
VOTERS5 = ("soup1", "mom", "soup", "donch", "ttm")
FOURHOUR = ("bosfvg", "obretest", "stflip", "diadx")
FAST = ("soup", "ttm", "soup1")


def _first(dirs_by_name, order, i):
    """The FIRST setup in `order` that fires at bar i wins, and the rest are
    not consulted. This is the operator's own shape: "if confluence 1 is met
    then open else if confluence 2 is met open as well"."""
    for name in order:
        d = dirs_by_name[name][i]
        if d:
            return d
    return 0


def _tally(dirs_by_name, names, i):
    """(longs, shorts) among `names` at bar i."""
    up = dn = 0
    for name in names:
        d = dirs_by_name[name][i]
        if d > 0:
            up += 1
        elif d < 0:
            dn += 1
    return up, dn


def _vote(dirs_by_name, names, i, need):
    """`need` setups agreeing on ONE side, and no more on the other. A tie is
    not a majority: two longs against two shorts is the market disagreeing
    with itself, which is exactly when a single-setup rule would trade."""
    up, dn = _tally(dirs_by_name, names, i)
    if up >= need and up > dn:
        return 1
    if dn >= need and dn > up:
        return -1
    return 0


def build_cascades(setups, bundle, level1, level2_hits, ok, zeros):
    """Return {name: rule}. The pieces are passed IN rather than imported, so
    this module never imports `signals_conf` and there is no cycle."""

    needed = sorted(set(LEAD) | set(VOTERS5) | set(FOURHOUR) | set(FAST))

    def _dirs(opens, high, low, close, volume, ts, funding):
        """Every member setup's directions, from ONE shared indicator bundle.

        The bundle is the expensive part (200-bar averages, ATR, pivots); a
        cascade that rebuilt it per member would cost five times a plain rule
        and the market sweep runs 105 of them.
        """
        b = bundle(opens, high, low, close, volume, ts)
        out = {}
        for name in needed:
            try:
                out[name] = setups[name](opens, high, low, close, volume, ts,
                                         b, funding)
            except Exception:                              # noqa: BLE001
                # one broken member must not silence the whole cascade — it
                # simply casts no vote (the abstain rule, signals_conf)
                out[name] = [0] * len(close)
        return b, out

    def _make(fn, doc, needs_funding=False):
        def rule(opens, high, low, close, volume, ts, funding=None):
            if not ok(opens, close) or len(close) < 5:
                return zeros(close)
            b, dbn = _dirs(opens, high, low, close, volume, ts, funding)
            return fn(b, dbn, opens, high, low, close, volume, ts)
        rule.__doc__ = doc
        rule.needs_funding = needs_funding
        return rule

    rules = {}

    # 1 — the operator's shape, exactly: first of four that fires.
    rules["cx_first"] = _make(
        lambda b, d, o, hh, lw, c, v, t: [_first(d, LEAD, i) for i in range(len(c))],
        "soup1, else mom, else soup, else donch — first one to fire wins")

    # 2 — the same four, asked in the opposite order. Which setup gets the
    #     first look changes the trades, and only measuring says which order
    #     suits a given coin.
    rules["cx_firstr"] = _make(
        lambda b, d, o, hh, lw, c, v, t: [_first(d, LEAD[::-1], i) for i in range(len(c))],
        "donch, else soup, else mom, else soup1 — the reverse priority")

    # 3 — nobody trades alone: two of four must agree on the same side.
    rules["cx_any2"] = _make(
        lambda b, d, o, hh, lw, c, v, t: [_vote(d, LEAD, i, 2) for i in range(len(c))],
        "two of (soup1, mom, soup, donch) agreeing on one side")

    # 4 — three of five. Rarer, and it should show up as a higher win rate.
    rules["cx_maj3"] = _make(
        lambda b, d, o, hh, lw, c, v, t: [_vote(d, VOTERS5, i, 3) for i in range(len(c))],
        "three of (soup1, mom, soup, donch, ttm) agreeing")

    # 5 — THE ESCALATOR. How much agreement is needed depends on the gate:
    #     behind the 200-bar trend two votes are enough, in front of it three.
    def _esc(b, d, o, hh, lw, c, v, t):
        l1 = level1(o, hh, lw, c, b)
        out = []
        for i in range(len(c)):
            two = _vote(d, VOTERS5, i, 2)
            three = _vote(d, VOTERS5, i, 3)
            if two and l1[i] == two:
                out.append(two)          # with the trend: two is enough
            elif three:
                out.append(three)        # against it: three, or nothing
            else:
                out.append(0)
        return out
    rules["cx_esc"] = _make(
        _esc, "two votes WITH the 200-bar trend, three votes without it")

    # 6 — the VETO: soup1 opens the trade unless mom points the other way.
    def _veto(b, d, o, hh, lw, c, v, t):
        out = []
        for i in range(len(c)):
            s, m = d["soup1"][i], d["mom"][i]
            out.append(0 if (s and m and m != s) else s)
        return out
    rules["cx_veto"] = _make(
        _veto, "soup1, unless mom disagrees — a conflict cancels the trade")

    # 7 — LEVEL ESCALATOR on one setup: take the strictest version that fires.
    def _lvl(b, d, o, hh, lw, c, v, t):
        l1 = level1(o, hh, lw, c, b)
        hits = level2_hits(o, hh, lw, c, v, t, b) if t else [0] * len(c)
        out = []
        for i in range(len(c)):
            s = d["soup1"][i]
            if not s:
                out.append(0)
            elif l1[i] == s and hits[i] >= 2:
                out.append(s)            # level 2: trend, engulfing, 2 levels
            elif l1[i] == s:
                out.append(s)            # level 1: trend and engulfing
            elif d["mom"][i] == s:
                out.append(s)            # ungated, but mom agrees
            else:
                out.append(0)
        return out
    rules["cx_lvl"] = _make(
        _lvl, "soup1 at level 2, else level 1, else only if mom agrees")

    # 8 — the FOUR-HOUR ranking's own cascade.
    rules["cx_4h"] = _make(
        lambda b, d, o, hh, lw, c, v, t: [_first(d, FOURHOUR, i) for i in range(len(c))],
        "bosfvg, else obretest, else stflip, else diadx (the 4h research list)",
        needs_funding=False)

    # 9 — for the FAST frames: mean-reversion first, then the squeeze.
    rules["cx_fast"] = _make(
        lambda b, d, o, hh, lw, c, v, t: [_first(d, FAST, i) for i in range(len(c))],
        "soup, else ttm, else soup1 — mean-revert first, for 15m and 30m")

    # 10 — the CONTROL, and the only linear one: both must agree. It is here
    #      so the operator can see in the same table what demanding agreement
    #      from everybody costs in trades.
    def _both(b, d, o, hh, lw, c, v, t):
        return [d["soup1"][i] if d["soup1"][i] and d["soup1"][i] == d["mom"][i]
                else 0 for i in range(len(c))]
    rules["cx_both"] = _make(
        _both, "soup1 AND mom must agree — the strict control")

    for name, fn in rules.items():
        fn.__name__ = name
    return rules
