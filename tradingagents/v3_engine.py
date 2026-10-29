"""THE BACKTEST V3 ENGINE — one strategy's trades the v3 way.

Spec: docs/superpowers/specs/2026-10-22-backtest-v3-design.md, Part 3
(operator, Oct 22, 2026: "i want to do backtest v3 where you will create the
strategy for the research you made"); plan:
docs/superpowers/plans/2026-10-22-backtest-v3-part1-engine.md.

For each signal candle: a waiting order at its close, POST-ONLY (Gate's
`poc`; the final review's ruling, Oct 23, 2026): when the recorded book of
the minute it goes in — at most CHASE_READING_MAX_AGE_S old — already crosses
it (`v3_rules.marketable`), Gate would fill it at once as a taker, so it is
REJECTED, a missed trade. Otherwise it rests, filled only when a point of
the NEXT candle trades through it (`v3_rules.limit_fill`); never filled = a
missed trade. Every missed trade is kept with what a market entry would have
made (`_market_twin`), so a waiting fill always pays the maker fee, by
construction. A filled trade risks `risk_usd` at a leverage that keeps its
stop safe (`v3_rules.risk_size`; a contract with no maintenance rate, no lot
size or no leverage is refused by name) and exits by its idea's own rule:

* ``trail``: a trailing stop `atr_mult` x ATR(20) (`v3_rules.trail_walk`),
  and, with `ma_n`, out at a candle close on the wrong side of its average;
* ``fixed``: a target resting as a waiting order (traded through, maker fee)
  and a stop at the market — the re-tested v2 rows;
* ``snap``: the `mean_n`-candle average at the signal as a resting target,
  an emergency stop `stop_atr` x ATR, and out at the close of the
  `max_bars`-th candle.

Any of the three can also be FORCED out (`walk(forced=)`, Backtest v3 Part
2a): an open trade leaves at the close of a flagged candle, at the market,
`why` "RANK" — the strength family's weekly rank exit. A stop or target the
candle reached first still comes first.

POINTS are Gate's minutes, or its 5-minute bars where the archive has a hole
(`backtest_report.fine_bars`). A touch stops (`v3_rules.stop_reached`). The
point an order fills in can stop the trade but can neither win it nor move
its trail: its high may have come before the fill (CLAUDE.md "A fill may
only see price the order was exposed to"). A stop the price jumped past
fills at the best price that point traded (`v3_rules.stop_fill`).

What the points cannot show, the candle settles by the candle rule, counted:
a WHOLE candle (walked from its open) with no points, or whose points show
nothing although its own high or low proves an exit; a waiting order's
candle whose points show no trade-through although its own low (a sell:
high) is strictly past the limit; and a STOP the candle proves while no point
shows it (a hole in the archive). A long trades through its limit before it
can fall to a stop under it (a short mirrors this), so even the fill candle's
own low proves a stop hit after the fill; only the target side of a fill
candle stays unproven, its high may predate the fill. When the points show a
target or a later trail exit while the candle proves the stop, nothing says
which came first: the stop, counted `unclear` as well (the repo's worst
case). A stop the candle rule decides fills at the stop — at the candle's
open when it opened past the stop — and inside a fill candle at the stop,
stamped at the first point after the fill.

Costs on every trade, all on the entry's notional: the maker fee in; out,
the maker fee at a resting target, else the taker fee plus the exit minute's
recorded gap (the coin's flat gap, `flat_slip`, where none was recorded: the
caller names it, there is no default); funding by settlement. What the
engine knows it could not measure is COUNTED (`COUNT_KEYS`): orders placed
with no fresh book (`placement_unmeasured`), exits that paid the flat gap,
estimated funding, candle-rule decisions, candles a trade lived through on
no points or on points that miss the candle's own high or low. Not counted
yet: a missed order's market-twin counts, and an entry cost check made with
no recorded book. The runner's own cost check is asked at the minute each
order goes in (`auto_trader.entry_refusal(entry="limit")`).
"""
from __future__ import annotations

import bisect

from tradingagents import v3_rules as vr

# missed: the order rested and never traded through · post_only_reject: the
# book of the minute it went in already crossed it, so Gate rejected the
# post-only order (also a missed trade, with its twin) · placement_unmeasured:
# no book of that minute at most CHASE_READING_MAX_AGE_S old, so the order
# rested unchecked · unsafe_stop: no leverage keeps the stop inside the
# liquidation ceiling · too_small: under one lot at the risk · no_levels: ATR
# or the average not ready, or a snap whose average is behind it ·
# gate_blocked / chase_skip / closed_skip: the runner's own answer (a closed
# candle with or without the cost check) · cost_unmeasured: an exit that paid
# the coin's flat gap · funding_estimated: a hold (partly) outside the
# funding history · settled_by_candle: an exit decided by the candle rule
# (no points, or a price the candle proves that the points do not show) ·
# fill_by_candle: a waiting order's fill DECISION by the candle rule (filled
# or missed) · unclear: stop and target (or a later trail exit) both reached
# where nothing orders them, booked as the stop · no_points: a candle a trade
# lived through with no points under it · partial_points: one whose points
# miss its own high or low · no_next_bar: a signal on the last candle
COUNT_KEYS = ("missed", "post_only_reject", "placement_unmeasured", "unsafe_stop",
              "too_small", "no_levels", "gate_blocked", "chase_skip", "closed_skip",
              "cost_unmeasured", "funding_estimated", "settled_by_candle", "fill_by_candle",
              "unclear", "no_points", "partial_points", "no_next_bar")


def _check_contract(c: dict) -> None:
    """A contract that cannot be measured is refused BY NAME, never sized on a
    guess: unknown is not zero (CLAUDE.md rule 12's shape). Gate's listing
    reads a missing maintenance rate as 0.0, and at 0 a 3% stop gets 20x where
    Gate's real 5% allows 11x — at 20x, 1/20 - 5% = 0, liquidated at the
    entry."""
    for field, ok, why in (
            ("contract_size", float(c["contract_size"]) > 0, "a lot of no coin cannot be sized"),
            ("mmr", float(c["mmr"]) > 0,
             "no maintenance rate, so no leverage can be proven to keep a stop safe"),
            ("max_lev", int(c["max_lev"]) >= 1, "no leverage at all is allowed")):
        if not ok:
            raise ValueError(f"contract {field} = {c[field]!r}: {why} (unknown is not zero)")


def contract_of(spec: dict) -> dict:
    """The engine's contract from the exchange's listing (`fx.contract_spec`):
    ONE mapping for every v3 caller — the smoke run and the tab
    (`v3_smoke.measure`) and one coin's whole measurement (`v3_measure`). A
    lot size, maintenance rate or maximum leverage that is missing or not a
    number is refused BY NAME, as `_check_contract` refuses one at 0 or less
    (unknown is not zero). The smallest order and the lowest leverage default
    to 1; a lowest leverage under 1 is refused (no position exists under 1x,
    and `v3_rules.safe_leverage` would divide by it)."""
    def field(key: str, cast, default=None):
        raw = spec.get(key)
        if raw is None or raw == "":
            if default is None:
                raise ValueError(f"contract {key} is missing: the listing cannot size a "
                                 "trade (unknown is not zero)")
            return default
        try:
            return cast(float(raw))
        except (TypeError, ValueError):
            raise ValueError(f"contract {key} = {raw!r} is not a number") from None

    c = {"contract_size": field("contractSize", float), "min_vol": field("minVol", int, 1),
         "mmr": field("maintenanceMarginRate", float), "max_lev": field("maxLeverage", int),
         "min_lev": field("minLeverage", int, 1)}
    if c["min_lev"] < 1:
        raise ValueError(f"contract minLeverage = {spec.get('minLeverage')!r}: no position "
                         "exists under 1x")
    _check_contract(c)
    return c


def _span(fine, a_ms: int, b_ms: int) -> tuple[int, int]:
    return bisect.bisect_left(fine[0], a_ms), bisect.bisect_left(fine[0], b_ms)


def _has_points(fine, a_ms: int, b_ms: int) -> bool:
    if fine is None:
        return False
    a, b = _span(fine, a_ms, b_ms)
    return a < b


def _points_reach(s: int, stop: float, a_ms: int, b_ms: int, ctx: dict) -> bool:
    """Whether any point in [a_ms, b_ms) reached `stop` (`stop_reached` on the
    points' own extremes); none when there are no points."""
    fine = ctx["fine"]
    if not _has_points(fine, a_ms, b_ms):
        return False
    a, b = _span(fine, a_ms, b_ms)
    return vr.stop_reached(s, stop, max(fine[1][a:b]), min(fine[2][a:b]))


def _candle_stop_px(s: int, stop: float, j: int, ctx: dict) -> float:
    """Where a stop the CANDLE rule decided fills: at the stop — or at the
    candle's open when it opened past it, since the stop was marketable from
    the first trade (final review M1). Never the candle's best price, which
    may have come at its end."""
    o = float(ctx["o"][j])
    return min(stop, o) if s == 1 else max(stop, o)


def _after_fill_ms(fill_ms: int, b_ms: int, ctx: dict) -> int:
    """The first point after the fill point inside its candle — the earliest a
    stop the points do not show can have been hit — or the fill point itself
    when none follows. Never the candle's open: the order did not exist yet."""
    fine = ctx["fine"]
    if fine is not None:
        k = bisect.bisect_left(fine[0], int(fill_ms) + 1)
        if k < len(fine[0]) and fine[0][k] < b_ms:
            return int(fine[0][k])
    return int(fill_ms)


def _note_points(j: int, ctx: dict) -> None:
    """Once per candle a trade lives through: no points under it at all
    (`no_points`: the candle rule decides it, exit or not), or points whose
    own extremes stop short of the candle's high or low (`partial_points`: a
    hole hides a price the candle traded — what the candle proves is booked,
    an order of events it hides is not). Worked out once per candle per walk
    (`ctx["cover"]`, shared with the market twins' scratch tallies)."""
    cover = ctx["cover"]
    what = cover.get(j)
    if what is None:
        fine, t0 = ctx["fine"], int(ctx["t"][j])
        a, b = _span(fine, t0, t0 + ctx["bar_ms"]) if fine is not None else (0, 0)
        if a >= b:
            what = "no_points"
        elif max(fine[1][a:b]) < ctx["hi"][j] or min(fine[2][a:b]) > ctx["lo"][j]:
            what = "partial_points"
        else:
            what = ""
        cover[j] = what
    if what:
        ctx["counts"][what] += 1


def _levels(kind: str, spec: dict, s: int, entry: float, atr_i, mean_i) -> dict | None:
    """The trade's stop, target and trail distance from its own exit rule;
    None = it cannot trade yet (ATR or the average not ready, or a snap whose
    average is not on the winning side)."""
    if kind == "fixed":
        return {"stop": entry * (1 - s * float(spec["sl"])),
                "target": entry * (1 + s * float(spec["tp"])), "trail": None}
    if atr_i is None or atr_i <= 0:
        return None
    if kind == "trail":
        d = float(spec.get("atr_mult", vr.TRAIL_ATR)) * atr_i
        return {"stop": entry - s * d, "target": None, "trail": d}
    if kind == "snap":
        if mean_i is None or s * (mean_i - entry) <= 0:
            return None
        d = float(spec.get("stop_atr", vr.TRAIL_ATR)) * atr_i
        return {"stop": entry - s * d, "target": mean_i, "trail": None}
    raise ValueError(f"unknown exit kind {kind!r}")


def _target_frac(levels: dict, entry: float) -> float:
    """What the cost check weighs the cost against: the target's distance, or
    for a trend trade with no target its first risk (1R)."""
    if levels["target"] is not None:
        return abs(levels["target"] - entry) / entry
    return abs(entry - levels["stop"]) / entry


def _size(entry: float, stop: float, ctx: dict) -> tuple[dict | None, str]:
    """The size that risks `risk_usd`, or (None, the count that says why not).
    Leverage is the highest safe one, never above `v3_rules.LEVERAGE_CAP` (the
    rooms' own 20x) whatever the contract allows."""
    c = ctx["contract"]
    max_lev = min(int(c["max_lev"]), vr.LEVERAGE_CAP)
    if vr.safe_leverage(abs(entry - stop) / entry, float(c["mmr"]), max_lev,
                        int(c.get("min_lev", 1))) is None:
        return None, "unsafe_stop"
    size = vr.risk_size(ctx["risk_usd"], entry, stop,
                        contract_size=float(c["contract_size"]), min_vol=int(c["min_vol"]),
                        mmr=float(c["mmr"]), max_lev=max_lev,
                        min_lev=int(c.get("min_lev", 1)))
    return (size, "") if size is not None else (None, "too_small")


def _ask_runner(s: int, i: int, tp_frac: float, size: dict, ctx: dict, entry: str) -> str:
    """The runner's own answer at the minute an order goes in, seconds after
    candle `i` closed (`auto_trader.entry_refusal`); "" = it would place it."""
    import tradingagents.auto_trader as at
    from tradingagents import book_history as bh

    place_ms = int(ctx["t"][i + 1])
    book, closed = ctx["book"], ctx["closed"]
    r = bh.reading_at(book, place_ms // 1000) if book is not None else None
    why, _cv = at.entry_refusal(
        r, side=s, signal_close=ctx["c"][i], tp=tp_frac, sl=size["stop_frac"],
        fee=float(ctx["fees"]["taker"]), hold_s=ctx["bar_s"] * at.FUNDING_HOLD_BARS,
        liq=max(0.0, 1.0 / size["leverage"] - float(ctx["contract"]["mmr"])),
        fund_day=at.funding_day_at(ctx["f_ms"], ctx["f_rate"], ctx["f_cyc"], place_ms, s),
        flat_slip=ctx["flat_slip"],
        closed=bool(closed[i]) if closed is not None else False,
        entry=entry, maker_fee=float(ctx["fees"]["maker"]))
    return why


def _placement(s: int, limit: float, i: int, ctx: dict) -> str:
    """Gate's answer to the POST-ONLY waiting order of candle `i` the minute it
    goes in (the open of candle i+1), read from that minute's recorded book
    — the one the cost check reads: "post_only_reject" when the book already
    crosses the limit (`v3_rules.marketable`), "placement_unmeasured" when no
    book of that minute exists (at most CHASE_READING_MAX_AGE_S old, by
    `book_history.book_age_s` — a snapshot-only hour's book is as old as its
    hour), "" when it rests, measured."""
    import tradingagents.auto_trader as at
    from tradingagents import book_history as bh

    book = ctx["book"]
    r = bh.reading_at(book, int(ctx["t"][i + 1]) // 1000) if book is not None else None
    if r is None or bh.book_age_s(r) > at.CHASE_READING_MAX_AGE_S:
        return "placement_unmeasured"
    return "post_only_reject" if vr.marketable(s, limit, r["bid"], r["ask"]) else ""


def _fill(s: int, limit: float, ctx: dict, i: int) -> tuple[int | None, bool]:
    """When the waiting order of candle `i` traded through, inside candle i+1,
    and whether the CANDLE decided it: (the fill's ms or None, by the candle).
    The points decide when they show a trade-through. The candle rule decides,
    counted (`fill_by_candle`, filled or missed), when there are no points,
    and when the points show none although the candle's own low (a sell:
    high) is strictly past the limit — the points cannot settle what the
    candle proves. It fills at the candle's open; a touch is no fill by
    either rule."""
    fine, t = ctx["fine"], ctx["t"]
    a_ms, b_ms = int(t[i + 1]), int(t[i + 1]) + ctx["bar_ms"]
    through = ctx["lo"][i + 1] < limit if s == 1 else ctx["hi"][i + 1] > limit
    if _has_points(fine, a_ms, b_ms):
        ms = vr.limit_fill(s, limit, fine[0], fine[1], fine[2], a_ms, b_ms)
        if ms is not None or not through:
            return ms, False
    ctx["counts"]["fill_by_candle"] += 1
    return (a_ms if through else None), True


def _fill_point(s: int, stop: float, fill_ms: int, j: int, ctx: dict, by_candle: bool):
    """The point a waiting order filled in can STOP the trade — a long's price
    passes its limit on the way down to its stop, so the order was filled
    first — but cannot win it or move its trail: its high may have come
    before the fill. A fill the CANDLE decided (`_fill`) has no point to read:
    the candle's own high and low stand in for it, counted when they stop the
    trade (at `_candle_stop_px`), and the rest of the candle is spent.
    Returns (the stop exit or None, where the walk resumes)."""
    fine = ctx["fine"]
    b_ms = int(ctx["t"][j]) + ctx["bar_ms"]
    if by_candle:
        hi, lo, resume = ctx["hi"][j], ctx["lo"][j], b_ms
    else:
        k = bisect.bisect_left(fine[0], fill_ms)
        hi, lo, resume = fine[1][k], fine[2][k], fill_ms + 1
    if not vr.stop_reached(s, stop, hi, lo):
        return None, resume
    if by_candle:
        ctx["counts"]["settled_by_candle"] += 1
        return (fill_ms, _candle_stop_px(s, stop, j, ctx), "SL"), resume
    return (fill_ms, vr.stop_fill(s, stop, hi, lo), "SL"), resume


def _fixed_bar(s: int, tp_px: float, sl_px: float, a_ms: int, b_ms: int, j: int,
               ctx: dict, after: int | None):
    """A stop at the market and a target resting as a waiting order over
    [a_ms, b_ms) of candle `j`: the points say which came first
    (`settle_in_minutes(tp_through=True)`), and a stop a point reaches fills
    where that point traded.

    A stop the candle's own low (a short: high) proves while no point shows
    it was hit in a hidden minute: the stop, counted `settled_by_candle` —
    and `unclear` when the points show the target (nothing orders the two).
    `after` None is a WHOLE candle, walked from its open: there the candle
    rule also decides what its points cannot show at all (no points; "NONE"
    although the candle reached the target), at the candle's open, a stop at
    `_candle_stop_px`. `after` = the fill point's ms is the rest of the fill
    candle: its high may predate the fill, so only the stop is read from the
    candle — at the stop itself (the price traded the limit after the order
    existed, then on through the stop), stamped at the first point after the
    fill (`_after_fill_ms`); what else its points do not show is spent.
    Returns (exit ms, price, why) or None."""
    import tradingagents.auto_trader as at

    fine, counts = ctx["fine"], ctx["counts"]
    hi, lo = ctx["hi"][j], ctx["lo"][j]
    reach_sl = vr.stop_reached(s, sl_px, hi, lo)
    reach_tp = hi > tp_px if s == 1 else lo < tp_px
    if not (reach_sl or reach_tp):
        return None
    got = None
    if _has_points(fine, a_ms, b_ms):
        got = at.settle_in_minutes(fine[0], fine[1], fine[2], a_ms, 0, s, tp_px, sl_px,
                                   None, liq=None, sl=0.0, span=_span(fine, a_ms, b_ms),
                                   tp_through=True)
    seen = got[0] if got is not None else None
    if seen == "SL":
        counts["unclear"] += int(got[2])
        k = bisect.bisect_left(fine[0], got[1])
        return got[1], vr.stop_fill(s, sl_px, fine[1][k], fine[2][k]), "SL"
    if reach_sl and not _points_reach(s, sl_px, a_ms, b_ms, ctx):
        counts["settled_by_candle"] += 1
        if after is None:
            counts["unclear"] += int(seen == "TP" or reach_tp)
            return int(ctx["t"][j]), _candle_stop_px(s, sl_px, j, ctx), "SL"
        counts["unclear"] += int(seen == "TP")
        return _after_fill_ms(after, b_ms, ctx), sl_px, "SL"
    if seen == "TP":
        return got[1], tp_px, "TP"
    if after is not None:
        return None
    counts["settled_by_candle"] += 1
    return int(ctx["t"][j]), tp_px, "TP"


def _trail_bar(s: int, stop: float, dist: float, a_ms: int, b_ms: int, j: int,
               ctx: dict, after: int | None) -> tuple[int | None, float]:
    """The trailing stop over [a_ms, b_ms) of candle `j`, point by point; a
    WHOLE candle (`after` None) with no points is walked as one point,
    counted when it decides the exit, at `_candle_stop_px`. A stop only
    tightens inside a candle, so a candle whose own low (a short: high) is
    past the stop it BEGAN with while no point shows it proves a hit in a
    hidden minute: out at that starting stop, counted `settled_by_candle` —
    and `unclear` when the points show an exit of their own at a stop they
    moved (nothing orders the two) — a whole candle's at its open
    (`_candle_stop_px`), the rest of a fill candle's (`after` = the fill
    point's ms) at the stop, stamped at the first point after the fill.
    Otherwise the points' answer stands, the moved stop included."""
    fine, counts = ctx["fine"], ctx["counts"]
    hi, lo, t0 = ctx["hi"][j], ctx["lo"][j], int(ctx["t"][j])
    if _has_points(fine, a_ms, b_ms):
        ms, px = vr.trail_walk(s, stop, dist, fine[0], fine[1], fine[2], a_ms, b_ms)
    elif after is None:
        ms, px = vr.trail_walk(s, stop, dist, [t0], [hi], [lo], t0, t0 + 1)
        if ms is None:
            return None, px
        counts["settled_by_candle"] += 1
        return ms, _candle_stop_px(s, stop, j, ctx)
    else:
        ms, px = None, stop
    if vr.stop_reached(s, stop, hi, lo) and not _points_reach(s, stop, a_ms, b_ms, ctx):
        counts["settled_by_candle"] += 1
        counts["unclear"] += int(ms is not None)
        if after is None:
            return t0, _candle_stop_px(s, stop, j, ctx)
        return _after_fill_ms(after, b_ms, ctx), stop
    return ms, px


def _close(s: int, entry: float, entry_ms: int, exit_px: float, exit_ms: int, why: str,
           size: dict, fee_in: float, ctx: dict) -> dict:
    """The trade's money: the price move, the fees, the exit's gap, funding."""
    from tradingagents import book_history as bh

    counts, fees, book = ctx["counts"], ctx["fees"], ctx["book"]
    notional = size["notional"]
    if why == "TP":
        fee_out, slip_out, measured = float(fees["maker"]), 0.0, True
    else:
        r = bh.reading_at(book, int(exit_ms) // 1000) if book is not None else None
        fee_out = float(fees["taker"])
        if r is None:
            slip_out, measured = ctx["flat_slip"], False
            counts["cost_unmeasured"] += 1
        else:
            slip_out, measured = float(r["sell"] if s == 1 else r["buy"]), True
    paid, estimated = vr.funding_paid(ctx["f_ms"], ctx["f_rate"], ctx["f_cyc"], s,
                                      int(entry_ms), int(exit_ms))
    counts["funding_estimated"] += int(estimated)
    gross = notional * s * (exit_px / entry - 1.0)
    pnl = gross - notional * (fee_in + fee_out + slip_out) - notional * paid
    return {"exit_ms": int(exit_ms), "exit": float(exit_px), "why": why,
            "fee_in": fee_in, "fee_out": fee_out, "slip_out": slip_out,
            "funding": -notional * paid, "pnl": pnl, "measured_exit": measured,
            "funding_estimated": estimated}


def _trade(s: int, entry: float, entry_ms: int, entry_bar: int, levels: dict, size: dict,
           fee_in: float, ctx: dict, *, partial: bool, by_candle: bool = False) -> dict:
    """One trade walked candle by candle until its exit rule fires.
    `partial`: a waiting order filled INSIDE its first candle (`_fill_point`;
    `by_candle`: the candle rule, not a point, decided that fill); a market
    entry at a candle's open is exposed to all of it. Every candle it lives
    through is noted once (`_note_points`)."""
    t, c, n, bar_ms = ctx["t"], ctx["c"], len(ctx["c"]), ctx["bar_ms"]
    kind, spec, ma, forced = ctx["kind"], ctx["spec"], ctx["ma"], ctx["forced"]
    stop, walk_from = levels["stop"], int(entry_ms)

    def done(hit, j):
        return {**_close(s, entry, entry_ms, hit[1], hit[0], hit[2], size, fee_in, ctx),
                "exit_bar": j}

    if partial:
        _note_points(entry_bar, ctx)
        hit, walk_from = _fill_point(s, stop, int(entry_ms), entry_bar, ctx, by_candle)
        if hit is not None:
            return done(hit, entry_bar)
    for j in range(entry_bar, n):
        if j > entry_bar or not partial:
            _note_points(j, ctx)
        a_ms, b_ms = max(walk_from, int(t[j])), int(t[j]) + bar_ms
        # only the rest of a candle a POINT filled in starts after its open
        after, hit = (None if a_ms == int(t[j]) else int(entry_ms)), None
        if a_ms < b_ms:
            if kind == "trail":
                ms, px = _trail_bar(s, stop, levels["trail"], a_ms, b_ms, j, ctx, after)
                if ms is None:
                    stop = px
                else:
                    hit = (ms, px, "TRAIL")
            else:
                hit = _fixed_bar(s, levels["target"], stop, a_ms, b_ms, j, ctx, after)
        if (hit is None and kind == "trail" and ma is not None and ma[j] is not None
                and s * (c[j] - ma[j]) < 0):
            hit = (b_ms, c[j], "MA")
        if hit is None and forced is not None and j < len(forced) and forced[j]:
            hit = (b_ms, c[j], "RANK")
        if hit is None and kind == "snap" and j - entry_bar + 1 >= int(spec.get("max_bars", 24)):
            hit = (b_ms, c[j], "TIME")
        if hit is not None:
            return done(hit, j)
    return done((int(t[n - 1]) + bar_ms, c[n - 1], "END"), n - 1)


def _market_twin(s: int, i: int, levels: dict, ctx: dict) -> dict:
    """What a missed trade would have made entered at the market, the way
    Backtest v2 enters: the recorded best ask (a long) or bid (a short) of the
    minute the next candle opened, else that candle's open plus the minute's
    gap (`auto_trader.book_fill_price`), the taker fee, and the same stop
    distance, trail and target. {"refused": why} when the runner would not
    have entered at the market either. Its counts go to a scratch tally, so
    the real counts only count real trades."""
    import tradingagents.auto_trader as at
    from tradingagents import book_history as bh

    entry_ms, book = int(ctx["t"][i + 1]), ctx["book"]
    r = bh.reading_at(book, entry_ms // 1000) if book is not None else None
    px = at.book_fill_price(r, s)
    if px is not None:
        entry, slip_in = px, 0.0
    else:
        entry = ctx["o"][i + 1]
        slip_in = (float(r["buy"] if s == 1 else r["sell"]) if r is not None
                   else ctx["flat_slip"])
    if ctx["kind"] == "fixed":
        tw = _levels("fixed", ctx["spec"], s, entry, None, None)
    else:
        dist = abs(ctx["c"][i] - levels["stop"])
        tw = {"stop": entry - s * dist, "target": levels["target"], "trail": levels["trail"]}
        if tw["target"] is not None and s * (tw["target"] - entry) <= 0:
            return {"refused": "no_levels"}
    size, why = _size(entry, tw["stop"], ctx)
    if size is None:
        return {"refused": why}
    if ctx["cost_check"]:
        why = _ask_runner(s, i, _target_frac(tw, entry), size, ctx, "market")
        if why:
            return {"refused": why}
    scratch = {**ctx, "counts": dict.fromkeys(COUNT_KEYS, 0)}
    fee_in = float(ctx["fees"]["taker"]) + slip_in
    tr = _trade(s, entry, entry_ms, i + 1, tw, size, fee_in, scratch, partial=False)
    return {"entry": entry, "entry_ms": entry_ms, "notional": size["notional"], **tr}


def walk(bars: dict, dirs, exit_spec: dict, *, bar_s: int, contract: dict, fees: dict,
         flat_slip: float, fine=None, risk_usd: float = vr.RISK_USD, book=None,
         funding=None, start: int = 0, closed=None, cost_check: bool = True,
         forced=None) -> dict:
    """Every trade of one strategy the v3 way (see the module doc).

    bars: {"t" (candle opens, ms), "o", "h", "l", "c"} · dirs: +1/-1/0 per
    candle · fine: (point opens ms, highs, lows) or None · contract:
    {"contract_size", "min_vol", "mmr", "max_lev", "min_lev"?} — a lot size
    or maintenance rate of 0 or less, or a max leverage under 1, raises
    ValueError naming the field · fees: {"maker", "taker"} · flat_slip
    (REQUIRED, like `fees`: the caller names the coin's gap, never a silent 0
    — CLAUDE.md rule 9, "never pass slippage=0"): what a market exit, a
    market twin's entry and the entry cost check pay where no recorded
    reading exists · book: book_history's packed readings or None · funding:
    [{"settle_ms", "rate", "cycle_h"}] oldest first · start: the first candle
    whose signal may trade · closed: per-candle "the market was closed" flags
    (the runner's rule, worked out by the caller; honoured with or without
    the cost check) or None · forced: per-candle flags — an open trade, the
    market twins' too, leaves at the close of a flagged candle at the market,
    `why` "RANK" (v3_strength's weekly rank exit) — or None, the rule of
    before.
    Checks in order, per signal: sizing, the runner's cost check (or the
    closed flag alone), the post-only check, the fill.
    Returns {"trades": [...], "missed": [... each with "why":
    "post_only_reject" or "not_traded_through", and its "market" twin],
    "counts": {COUNT_KEYS}}.
    """
    _check_contract(contract)
    t, hi, lo, c = bars["t"], bars["h"], bars["l"], bars["c"]
    n, kind, f = len(c), exit_spec["kind"], funding or []
    counts = dict.fromkeys(COUNT_KEYS, 0)
    ctx = {"t": t, "o": bars["o"], "hi": hi, "lo": lo, "c": c, "bar_s": int(bar_s),
           "bar_ms": int(bar_s) * 1000, "kind": kind, "spec": exit_spec, "fine": fine,
           "fees": fees, "book": book, "flat_slip": float(flat_slip),
           "f_ms": [int(x["settle_ms"]) for x in f], "f_rate": [float(x["rate"]) for x in f],
           "f_cyc": [float(x.get("cycle_h") or 8) for x in f], "counts": counts,
           "contract": contract, "closed": closed, "cost_check": bool(cost_check),
           "risk_usd": float(risk_usd), "cover": {}, "forced": forced,
           "ma": vr.sma(c, int(exit_spec["ma_n"])) if exit_spec.get("ma_n") else None}
    atr_ = vr.atr(hi, lo, c, vr.ATR_N)
    mean = vr.sma(c, int(exit_spec.get("mean_n", 20))) if kind == "snap" else None
    trades, missed = [], []
    i = max(0, int(start))
    while i < n:
        s = int(dirs[i]) if i < len(dirs) else 0
        if s == 0:
            i += 1
            continue
        if i + 1 >= n:
            counts["no_next_bar"] += 1
            break
        levels = _levels(kind, exit_spec, s, c[i], atr_[i],
                         mean[i] if mean is not None else None)
        if levels is None:
            counts["no_levels"] += 1
            i += 1
            continue
        size, why = _size(c[i], levels["stop"], ctx)
        if size is not None:
            if cost_check:
                why = _ask_runner(s, i, _target_frac(levels, c[i]), size, ctx, "limit")
            elif closed is not None and closed[i]:
                why = "closed_skip"
        if why:
            counts[why] += 1
            i += 1
            continue
        placed = _placement(s, c[i], i, ctx)
        if placed == "post_only_reject":
            fill_ms, by_candle = None, False
        else:
            counts["placement_unmeasured"] += int(placed == "placement_unmeasured")
            fill_ms, by_candle = _fill(s, c[i], ctx, i)
        if fill_ms is None:
            rejected = placed == "post_only_reject"
            counts["post_only_reject" if rejected else "missed"] += 1
            missed.append({"side": s, "signal_bar": i, "signal_ms": int(t[i]),
                           "limit": c[i],
                           "why": "post_only_reject" if rejected else "not_traded_through",
                           "market": _market_twin(s, i, levels, ctx)})
            i += 1
            continue
        tr = _trade(s, c[i], fill_ms, i + 1, levels, size, float(fees["maker"]), ctx,
                    partial=True, by_candle=by_candle)
        trades.append({"side": s, "signal_bar": i, "entry_bar": i + 1,
                       "entry_ms": int(fill_ms), "entry": c[i],
                       "contracts": size["contracts"], "notional": size["notional"],
                       "leverage": size["leverage"], "margin": size["margin"],
                       # the stop and target the order went in with (a trail moves its stop
                       # later; this is the first one): what the results page's max TP % and
                       # max SL % read (Backtest v3 Part 2b)
                       "stop_px": float(levels["stop"]),
                       "target_px": None if levels["target"] is None else float(levels["target"]),
                       **tr})
        if tr["why"] == "END":
            break
        i = tr["exit_bar"]          # a candle a trade closed in may signal again
    return {"trades": trades, "missed": missed, "counts": counts}
