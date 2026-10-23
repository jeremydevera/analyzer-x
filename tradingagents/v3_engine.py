"""THE BACKTEST V3 ENGINE — one strategy's trades the v3 way.

Spec: docs/superpowers/specs/2026-10-22-backtest-v3-design.md, Part 3
(operator, Oct 22, 2026: "i want to do backtest v3 where you will create the
strategy for the research you made"); plan:
docs/superpowers/plans/2026-10-22-backtest-v3-part1-engine.md.

For each signal candle: a waiting order at its close, filled only when a
point of the NEXT candle trades through it (`v3_rules.limit_fill`); never
filled = a missed trade, kept with what a market entry would have made. A
filled trade risks `risk_usd` at a leverage that keeps its stop safe
(`v3_rules.risk_size`) and exits by its idea's own rule:

* ``trail``: a trailing stop `atr_mult` x ATR(20) (`v3_rules.trail_walk`),
  and, with `ma_n`, out at a candle close on the wrong side of its average;
* ``fixed``: a target resting as a waiting order (traded through, maker fee)
  and a stop at the market — the re-tested v2 rows;
* ``snap``: the `mean_n`-candle average at the signal as a resting target,
  an emergency stop `stop_atr` x ATR, and out at the close of the
  `max_bars`-th candle.

POINTS are Gate's minutes, or its 5-minute bars where the archive has a hole
(`backtest_report.fine_bars`). The point an order fills in can stop the
trade but can neither win it nor move its trail: its high may have come
before the fill (CLAUDE.md "A fill may only see price the order was exposed
to"). A stop the price jumped past fills at the best price that point traded
(`v3_rules.stop_fill`). A candle the points cannot settle keeps the candle
rule, counted: a WHOLE candle (walked from its open) with no points, or whose
points show nothing although its own high or low proves an exit; and a waiting
order's candle whose points show no trade-through although its own low (a
sell: high) is strictly past the limit. The rest of a candle after the fill
point is not whole (its high and low may predate the fill): what its points do
not show there is spent, never re-read.

Costs on every trade, all on the entry's notional: the maker fee in; out,
the maker fee at a resting target, else the taker fee plus the exit minute's
recorded gap (the coin's flat gap, `flat_slip`, where none was recorded: the
caller names it, there is no default); funding by settlement. What the engine
could not measure is COUNTED (`COUNT_KEYS`), never hidden. The runner's own
cost check is asked at the minute each order goes in
(`auto_trader.entry_refusal(entry="limit")`).
"""
from __future__ import annotations

import bisect

from tradingagents import v3_rules as vr

# missed: the waiting order never traded through · unsafe_stop: no leverage
# keeps the stop inside the liquidation ceiling · too_small: under one lot at
# the risk · no_levels: ATR or the average not ready, or a snap whose average
# is behind it · gate_blocked / chase_skip / closed_skip: the runner's own
# answer · cost_unmeasured: an exit that paid the coin's flat gap ·
# funding_estimated: a hold (partly) before the funding history ·
# settled_by_candle / fill_by_candle: decided by the candle rule because the
# points could not settle it (no points, or points that cannot show what the
# candle proves) ·
# unclear: stop and target in one point, booked as the stop · no_next_bar: a
# signal on the last candle
COUNT_KEYS = ("missed", "unsafe_stop", "too_small", "no_levels", "gate_blocked",
              "chase_skip", "closed_skip", "cost_unmeasured", "funding_estimated",
              "settled_by_candle", "fill_by_candle", "unclear", "no_next_bar")


def _span(fine, a_ms: int, b_ms: int) -> tuple[int, int]:
    return bisect.bisect_left(fine[0], a_ms), bisect.bisect_left(fine[0], b_ms)


def _has_points(fine, a_ms: int, b_ms: int) -> bool:
    if fine is None:
        return False
    a, b = _span(fine, a_ms, b_ms)
    return a < b


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
    """The size that risks `risk_usd`, or (None, the count that says why not)."""
    c = ctx["contract"]
    if vr.safe_leverage(abs(entry - stop) / entry, float(c["mmr"]), int(c["max_lev"]),
                        int(c.get("min_lev", 1))) is None:
        return None, "unsafe_stop"
    size = vr.risk_size(ctx["risk_usd"], entry, stop,
                        contract_size=float(c["contract_size"]), min_vol=int(c["min_vol"]),
                        mmr=float(c["mmr"]), max_lev=int(c["max_lev"]),
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


def _fill(s: int, limit: float, ctx: dict, i: int) -> tuple[int | None, bool]:
    """When the waiting order of candle `i` traded through, inside candle i+1,
    and whether the CANDLE decided it: (the fill's ms or None, by the candle).
    The points decide when they show a trade-through. The candle rule decides,
    counted, when there are no points, and when the points show none although
    the candle's own low (a sell: high) is strictly past the limit — the
    points cannot settle what the candle proves. It fills at the candle's
    open; a touch is no fill by either rule."""
    fine, t = ctx["fine"], ctx["t"]
    a_ms, b_ms = int(t[i + 1]), int(t[i + 1]) + ctx["bar_ms"]
    through = ctx["lo"][i + 1] < limit if s == 1 else ctx["hi"][i + 1] > limit
    if _has_points(fine, a_ms, b_ms):
        ms = vr.limit_fill(s, limit, fine[0], fine[1], fine[2], a_ms, b_ms)
        if ms is not None or not through:
            return ms, False
    ctx["counts"]["fill_by_candle"] += 1
    return (a_ms if through else None), True


def _stopped(s: int, stop: float, hi: float, lo: float) -> bool:
    return lo <= stop if s == 1 else hi >= stop


def _fill_point(s: int, stop: float, fill_ms: int, j: int, ctx: dict, by_candle: bool):
    """The point a waiting order filled in can STOP the trade — a long's price
    passes its limit on the way down to its stop, so the order was filled
    first — but cannot win it or move its trail: its high may have come
    before the fill. A fill the CANDLE decided (`_fill`) has no point to read:
    the candle's own high and low stand in for it, counted when they stop the
    trade, and the rest of the candle is spent. Returns (the stop exit or
    None, where the walk resumes)."""
    fine = ctx["fine"]
    b_ms = int(ctx["t"][j]) + ctx["bar_ms"]
    if by_candle:
        hi, lo, resume = ctx["hi"][j], ctx["lo"][j], b_ms
    else:
        k = bisect.bisect_left(fine[0], fill_ms)
        hi, lo, resume = fine[1][k], fine[2][k], fill_ms + 1
    if not _stopped(s, stop, hi, lo):
        return None, resume
    if by_candle:
        ctx["counts"]["settled_by_candle"] += 1
    return (fill_ms, vr.stop_fill(s, stop, hi, lo), "SL"), resume


def _fixed_bar(s: int, tp_px: float, sl_px: float, a_ms: int, b_ms: int, j: int,
               ctx: dict, whole: bool):
    """A stop at the market and a target resting as a waiting order over
    [a_ms, b_ms) of candle `j`: the points say which came first
    (`settle_in_minutes(tp_through=True)`). A WHOLE candle the points cannot
    settle — no points under it, or points that show neither price although
    the candle's own high / low proves one was reached (a hole in the
    archive; `settle_in_minutes` answers "NONE" and leaves the candle rule to
    its caller) — keeps the candle rule, counted: both prices in one candle
    is the stop. The rest of a candle after the fill point is not whole (its
    own high / low may predate the fill), so what its points do not show is
    spent. Returns (exit ms, price, why) or None."""
    import tradingagents.auto_trader as at

    fine, counts = ctx["fine"], ctx["counts"]
    hi, lo = ctx["hi"][j], ctx["lo"][j]
    reach_sl = lo <= sl_px if s == 1 else hi >= sl_px
    reach_tp = hi > tp_px if s == 1 else lo < tp_px
    if not (reach_sl or reach_tp):
        return None
    got = None
    if _has_points(fine, a_ms, b_ms):
        got = at.settle_in_minutes(fine[0], fine[1], fine[2], a_ms, 0, s, tp_px, sl_px,
                                   None, liq=None, sl=0.0, span=_span(fine, a_ms, b_ms),
                                   tp_through=True)
    if got is not None and got[0] != "NONE":
        counts["unclear"] += int(got[2])
        if got[0] == "TP":
            return got[1], tp_px, "TP"
        k = bisect.bisect_left(fine[0], got[1])
        return got[1], vr.stop_fill(s, sl_px, fine[1][k], fine[2][k]), "SL"
    if not whole:
        return None
    counts["settled_by_candle"] += 1
    if reach_sl:
        counts["unclear"] += int(reach_tp)
        return int(ctx["t"][j]), vr.stop_fill(s, sl_px, hi, lo), "SL"
    return int(ctx["t"][j]), tp_px, "TP"


def _trail_bar(s: int, stop: float, dist: float, a_ms: int, b_ms: int, j: int,
               ctx: dict, whole: bool) -> tuple[int | None, float]:
    """The trailing stop over [a_ms, b_ms) of candle `j`, point by point; a
    WHOLE candle with no points is walked as one point, counted when it
    decides the exit. A WHOLE candle whose points find no exit although its
    own low (a short: high) is past the stop the candle BEGAN with has a hole
    in its points: a stop only tightens inside a candle, so the candle proves
    it was hit, and the exit is by the candle rule — at the candle's open, at
    the stop the candle began with (`stop_fill`), counted. Otherwise the
    points' answer stands, the moved stop included. The rest of a candle after
    the fill point is not whole: what its points do not show is spent."""
    fine = ctx["fine"]
    hi, lo, t0 = ctx["hi"][j], ctx["lo"][j], int(ctx["t"][j])
    if _has_points(fine, a_ms, b_ms):
        ms, px = vr.trail_walk(s, stop, dist, fine[0], fine[1], fine[2], a_ms, b_ms)
        if ms is None and whole and _stopped(s, stop, hi, lo):
            ctx["counts"]["settled_by_candle"] += 1
            return t0, vr.stop_fill(s, stop, hi, lo)
        return ms, px
    if not whole:
        return None, stop
    ms, px = vr.trail_walk(s, stop, dist, [t0], [hi], [lo], t0, t0 + 1)
    if ms is not None:
        ctx["counts"]["settled_by_candle"] += 1
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
    entry at a candle's open is exposed to all of it."""
    t, c, n, bar_ms = ctx["t"], ctx["c"], len(ctx["c"]), ctx["bar_ms"]
    kind, spec, ma = ctx["kind"], ctx["spec"], ctx["ma"]
    stop, walk_from = levels["stop"], int(entry_ms)

    def done(hit, j):
        return {**_close(s, entry, entry_ms, hit[1], hit[0], hit[2], size, fee_in, ctx),
                "exit_bar": j}

    if partial:
        hit, walk_from = _fill_point(s, stop, int(entry_ms), entry_bar, ctx, by_candle)
        if hit is not None:
            return done(hit, entry_bar)
    for j in range(entry_bar, n):
        a_ms, b_ms = max(walk_from, int(t[j])), int(t[j]) + bar_ms
        whole, hit = a_ms == int(t[j]), None
        if a_ms < b_ms:
            if kind == "trail":
                ms, px = _trail_bar(s, stop, levels["trail"], a_ms, b_ms, j, ctx, whole)
                if ms is None:
                    stop = px
                else:
                    hit = (ms, px, "TRAIL")
            else:
                hit = _fixed_bar(s, levels["target"], stop, a_ms, b_ms, j, ctx, whole)
        if (hit is None and kind == "trail" and ma is not None and ma[j] is not None
                and s * (c[j] - ma[j]) < 0):
            hit = (b_ms, c[j], "MA")
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
         funding=None, start: int = 0, closed=None, cost_check: bool = True) -> dict:
    """Every trade of one strategy the v3 way (see the module doc).

    bars: {"t" (candle opens, ms), "o", "h", "l", "c"} · dirs: +1/-1/0 per
    candle · fine: (point opens ms, highs, lows) or None · contract:
    {"contract_size", "min_vol", "mmr", "max_lev", "min_lev"?} · fees:
    {"maker", "taker"} · flat_slip (REQUIRED, like `fees`: the caller names the
    coin's gap, never a silent 0 — CLAUDE.md rule 9, "never pass slippage=0"):
    what a market exit, a market twin's entry and the entry cost check pay
    where no recorded reading exists · book: book_history's packed readings or
    None · funding: [{"settle_ms", "rate", "cycle_h"}] oldest first · start:
    the first candle whose signal may trade · closed: per-candle "the market
    was closed" flags (the runner's rule, worked out by the caller) or None.
    Returns {"trades": [...], "missed": [...], "counts": {COUNT_KEYS}}.
    """
    t, hi, lo, c = bars["t"], bars["h"], bars["l"], bars["c"]
    n, kind, f = len(c), exit_spec["kind"], funding or []
    counts = dict.fromkeys(COUNT_KEYS, 0)
    ctx = {"t": t, "o": bars["o"], "hi": hi, "lo": lo, "c": c, "bar_s": int(bar_s),
           "bar_ms": int(bar_s) * 1000, "kind": kind, "spec": exit_spec, "fine": fine,
           "fees": fees, "book": book, "flat_slip": float(flat_slip),
           "f_ms": [int(x["settle_ms"]) for x in f], "f_rate": [float(x["rate"]) for x in f],
           "f_cyc": [float(x.get("cycle_h") or 8) for x in f], "counts": counts,
           "contract": contract, "closed": closed, "cost_check": bool(cost_check),
           "risk_usd": float(risk_usd),
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
        if size is not None and cost_check:
            why = _ask_runner(s, i, _target_frac(levels, c[i]), size, ctx, "limit")
        if why:
            counts[why] += 1
            i += 1
            continue
        fill_ms, by_candle = _fill(s, c[i], ctx, i)
        if fill_ms is None:
            counts["missed"] += 1
            missed.append({"side": s, "signal_bar": i, "signal_ms": int(t[i]),
                           "limit": c[i], "market": _market_twin(s, i, levels, ctx)})
            i += 1
            continue
        tr = _trade(s, c[i], fill_ms, i + 1, levels, size, float(fees["maker"]), ctx,
                    partial=True, by_candle=by_candle)
        trades.append({"side": s, "signal_bar": i, "entry_bar": i + 1,
                       "entry_ms": int(fill_ms), "entry": c[i],
                       "contracts": size["contracts"], "notional": size["notional"],
                       "leverage": size["leverage"], "margin": size["margin"], **tr})
        if tr["why"] == "END":
            break
        i = tr["exit_bar"]          # a candle a trade closed in may signal again
    return {"trades": trades, "missed": missed, "counts": counts}
