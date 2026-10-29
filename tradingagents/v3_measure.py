"""ONE COIN'S WHOLE BACKTEST V3 MEASUREMENT — what one GitHub machine will
return per coin (Part 2b), runnable on this PC now (Part 2a).

Decisions doc: docs/superpowers/specs/2026-10-23-backtest-v3-part2-
decisions.md ("The window and the split", "What a machine returns per
coin"). For every family the plan lets the coin trade, on each of the
family's timeframes, for every setting and every filter:

* the OLDER walk: the candles from the window's start (the plan's end - 365
  days) up to the split (the plan's end - 90 days), with the setting's
  lead-in before them; a trade still open at the split is closed at its last
  candle (`END`). Its minutes, order books and funding are CUT at the split,
  so the setting can never be chosen on an unseen price — by construction.
  The flat gap it pays where a minute has no reading of its own is the
  older days' own (the median of the readings before the split, `older_gap`)
  once they have readings - the order-book backfill of Part 2b. Where they
  have none it is the whole window's figure, a cost level, never a price
  path, and `flat_slip_older_source` says which it is;
* the UNSEEN walk: the newest 90 days, the lead-in before them read by the
  indicators only;
* RUNS random runs on the unseen window (`v3_random`), measured for EVERY
  setting so the choice stays blind (only the chosen one is ever read).

ONE read per coin: its candles per timeframe, a year of minutes, the order
books, funding and its listing, and the coin's OWN flat gap (the median of
its recorded minutes, `cost_store.usual_slip`), then every walk off them.
Signals count only in the months the coin is a member of the family's
universe, on the sides that membership allows, and only where the filter
lets the order through — a per-candle mask on the signal, never a filter on
trades afterwards. Nothing is chosen here: `v3_proof` chooses and judges
after every coin is in.

Every number is kept compact: trade rows [signal_ms, entry_ms, exit_ms,
side, pnl, why], the engine's counts, the filter's counts, each random
run's [trades, profit], and what kept the random runs' entries from trading
(`_random_runs`: not placed, refused or never filled, inside an open trade).
"""
from __future__ import annotations

import bisect
import math
import time

from tradingagents import (
    v3_engine as ve,
    v3_families as vf,
    v3_filters as vfl,
    v3_random as vrn,
    v3_universe as vu,
)

# 2 (Backtest v3 Part 2b): every trade row carries the stop and target it opened with, as
# fractions of its entry, and the older walk pays the older days' own flat gap where they have
# readings. A record of version 1 holds neither; the proof reads only the first six fields
VERSION = 2
# A compact trade row, field by field. Every reader of a row's stop or target takes its place from
# here (`ROW_STOP`, `ROW_TARGET`), never a number typed; a record of VERSION 1 has the first six
# only, and `v3_proof` and `v3_research` refuse to pool or judge records of two versions
ROW_FIELDS = ("signal_ms", "entry_ms", "exit_ms", "side", "pnl", "why", "stop", "target")
ROW_STOP, ROW_TARGET = ROW_FIELDS.index("stop"), ROW_FIELDS.index("target")
UNSEEN_DAYS = 90
DAY_MS = 86_400_000
BOOK_USD = 100.0          # a recorded reading is the cost of walking the book for $100
FUNDING_PAD_DAYS = 31     # funding_side reads the 30 days before each order
TF_ORDER = ("1h", "4h", "1d")
# The engine's counts of a placed entry that never became a trade: refused before an order went in,
# or an order that never filled. Every placed entry the walk looks at ends as a trade or as one of
# these; the rest fell inside the walk's own open trade (`inside_open_trades`)
DROPS = ("no_levels", "too_small", "unsafe_stop", "gate_blocked", "chase_skip", "closed_skip",
         "missed", "post_only_reject", "no_next_bar")


def windows(plan: dict) -> tuple[int, int, int]:
    """(window start, split, end) in ms: the plan's own, the same for every
    coin and every machine."""
    end = int(plan["end_ms"])
    return int(plan["start_ms"]), end - UNSEEN_DAYS * DAY_MS, end


def bars_of(df, bar_ms: int, end_ms: int) -> dict:
    """A candle frame -> {"t" (opens ms), "o", "h", "l", "c"}, only the
    candles that CLOSED by `end_ms` (the plan's end, never the clock)."""
    t = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    keep = t + int(bar_ms) <= int(end_ms)
    col = {"o": "Open", "h": "High", "l": "Low", "c": "Close"}
    return {"t": [int(x) for x in t[keep]],
            **{k: [float(x) for x in df[v].to_numpy()[keep]] for k, v in col.items()}}


def _book_before(book, split: int):
    """The order-book readings stamped before the split, or None. A reading
    stamped AT the split is the book 3 s after it — an unseen price — so it is
    out. The older walk's book and the count of the flat gap's minutes that lie
    on the older days are cut by this one function."""
    if book is None:
        return None
    import numpy as np

    j = int(np.searchsorted(book["t"], split // 1000, side="left"))
    return {k: v[:j] for k, v in book.items()}


def flat_gap(sym: str, book, *, fx, split_ms: int | None = None) -> tuple[float, str]:
    """The coin's own usual one-side cost where a minute has no recorded
    book, and where it came from (said beside every result).

    From the recorded minutes it is the median of EVERY one of them in the
    window, whichever side of the split it lies on — the unseen walk pays it,
    and so does the older walk where the older days have no reading of their
    own (`older_gap`) — so with `split_ms` the source says how many of those
    minutes lie on the older days (counted as `usual_slip` counts, on the
    book cut as the older walk's is). With no recorded minute: one live reading of the book,
    or the app's paper figure. A live reading that is not a positive finite
    number - 0, below 0, not a number, infinite, none at all - is no reading:
    never a free, a missing or an infinite cost. Each is named for what it is."""
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br, cost_store

    slip, n = cost_store.usual_slip(book)
    if slip is not None:
        source = f"the median of its {n:,} recorded minutes whose book did not run out"
        if split_ms is not None:
            older = cost_store.usual_slip(_book_before(book, split_ms))[1]
            source += f", {older:,} of them on the older days"
        return slip, source
    try:
        said = fx.book_cost(sym, BOOK_USD).get("slippage")
        live = None if said is None else float(said)
        if live is None or not (math.isfinite(live) and live > 0):
            shown = "None" if live is None else format(live, "g")
            return at.PAPER_SLIPPAGE, (f"the app's paper figure: its one live reading said "
                                       f"{shown} (no minute recorded)")
        return (br.charged_slippage([live]),
                "one live reading of its book (no minute recorded)")
    except Exception as exc:                                   # noqa: BLE001
        return at.PAPER_SLIPPAGE, (f"the app's paper figure: no book could be read "
                                   f"({type(exc).__name__})")


def older_gap(book, split_ms: int, whole: tuple[float, str]) -> tuple[float, str]:
    """The OLDER walk's flat gap: the median of the recorded minutes stamped
    before the split (`_book_before`, the cut every older read takes), so a
    setting is chosen on the older days' own cost level once they have
    readings (the order-book backfill, Part 2b). Where they have none - the
    store held about two months on Oct 27, 2026 - the older walk keeps the
    whole window's figure `whole` (value, source), and its source says so."""
    from tradingagents import cost_store

    older = _book_before(book, split_ms)
    slip, n = cost_store.usual_slip(older)
    if slip is not None:
        return slip, (f"the median of its {n:,} recorded minutes on the older days whose book "
                      "did not run out")
    stamped = len(older["t"]) if older is not None else 0
    if stamped:
        return whole[0], (f"no usable reading on the older days ({stamped:,} recorded, every "
                          f"book ran out): {whole[1]}")
    return whole[0], f"no reading of its own on the older days: {whole[1]}"


def prefetch(sym: str, plan: dict, leads: dict, *, fx) -> dict:
    """Everything one coin's walks read, fetched ONCE: {tf: bars} with each
    timeframe's longest lead-in before the window, the minutes of the window,
    its order books, funding, the listing and the fees."""
    start, split, end = windows(plan)
    return read_window(sym, start, end, leads, fx=fx, split_ms=split)


def read_window(sym: str, start: int, end: int, leads: dict, *, fx,
                split_ms: int | None = None) -> dict:
    """What `prefetch` reads, over any window [start, end) in ms: the plan's
    (with its split, so the coverage and the flat gap's source are said for
    the older and the unseen days), or the Backtest v3 tab's one look at a
    family on one coin (no split: one coverage over the window). ONE body, so
    the tab and the research read a coin the same way."""
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br, cost_store

    spec = fx.contract_spec(sym)
    contract = ve.contract_of(spec)
    now_ms = int(time.time() * 1000)
    bars = {}
    for tf, lead in leads.items():
        iv, bar_s, _cap = br.TFS[tf]
        bar_ms = bar_s * 1000
        need = -(-(now_ms - (start - lead * bar_ms)) // bar_ms) + 2
        bars[tf] = bars_of(fx.klines(sym, iv, need), bar_ms, end)
    ft, fh, fl, n5 = br.fine_bars(sym, start // 1000, end // 1000, fx=fx)
    keep = ft < end
    fine = (ft[keep].tolist(), fh[keep].tolist(), fl[keep].tolist())
    book = cost_store.engine_book(sym, start // 1000, end // 1000)
    slip, source = flat_gap(sym, book, fx=fx, split_ms=split_ms)
    funding = [f for f in fx.funding_history(sym, since_ms=start - FUNDING_PAD_DAYS * DAY_MS)
               if int(f["settle_ms"]) <= end]
    fees = {"maker": at.maker_fee_floor(), "taker": at.fee_floor()}
    meta = {"contract": contract, "fees": fees, "flat_slip": slip, "flat_slip_source": source,
            "minutes": len(fine[0]), "five_minute": int(n5)}
    slip_older = slip
    if split_ms is None:
        meta["coverage"] = cost_store.coverage(book, start // 1000, end // 1000)
    else:
        meta["coverage_older"] = cost_store.coverage(book, start // 1000, split_ms // 1000)
        meta["coverage_unseen"] = cost_store.coverage(book, split_ms // 1000, end // 1000)
        slip_older, meta["flat_slip_older_source"] = older_gap(book, split_ms, (slip, source))
        meta["flat_slip_older"] = slip_older
    meta |= {"funding": len(funding),
             "funding_from_ms": int(funding[0]["settle_ms"]) if funding else None,
             "cycle_h": float(spec.get("funding_interval_h") or 8)}
    return {"bars": bars, "fine": fine if fine[0] else None, "book": book, "funding": funding,
            "contract": contract, "fees": fees, "slip": slip, "slip_older": slip_older,
            "cycle_h": meta["cycle_h"], "meta": meta}


def _before(pre: dict, split: int) -> dict:
    """The older walk's data: minutes, order books and funding CUT at the
    split, so nothing it reads can be an unseen price."""
    fine = pre["fine"]
    if fine is not None:
        j = bisect.bisect_left(fine[0], split)
        fine = (fine[0][:j], fine[1][:j], fine[2][:j])
    return {"fine": fine, "book": _book_before(pre["book"], split),
            "funding": [f for f in pre["funding"] if int(f["settle_ms"]) <= split]}


def _view(bars: dict, a: int, b: int) -> dict:
    return {k: v[a:b] for k, v in bars.items()}


def _frac(px, entry: float) -> float | None:
    """A level's distance from the entry, as a fraction of it (5 places), or None."""
    return None if px is None else round(abs(float(px) - float(entry)) / float(entry), 5)


def compact(walked: dict, t, signals: dict) -> dict:
    """One walk in the shape every machine returns. A trade row is [signal_ms,
    entry_ms, exit_ms, side, pnl, why, stop, target]: the last two are the stop
    and the target the order went in with, as fractions of the entry (a trail
    has no target: None) - what the results page's max SL % and max TP % read
    (`ROW_FIELDS`, `ROW_STOP`, `ROW_TARGET`).
    Everything that reads the first six fields reads them as before."""
    trades = walked["trades"]
    twins = [m["market"] for m in walked["missed"] if "pnl" in m["market"]]
    lev = [int(x["leverage"]) for x in trades]
    notional = [float(x["notional"]) for x in trades]
    return {"rows": [[int(t[x["signal_bar"]]), int(x["entry_ms"]), int(x["exit_ms"]),
                      int(x["side"]), round(float(x["pnl"]), 6), x["why"],
                      _frac(x["stop_px"], x["entry"]), _frac(x.get("target_px"), x["entry"])]
                     for x in trades],
            "counts": {k: int(v) for k, v in walked["counts"].items() if v},
            "filter": signals, "missed": len(walked["missed"]),
            "twins": [len(twins), round(sum(float(x["pnl"]) for x in twins), 6)],
            "lev": [min(lev), max(lev)] if lev else None,
            "notional": [round(min(notional), 2), round(max(notional), 2)] if notional else None,
            "over_book": sum(1 for x in notional if x > BOOK_USD)}


def allowed(long_m, short_m, keep_l, keep_s) -> tuple[list[bool], list[bool]]:
    """Per candle: may a long, may a short go in - the universe's sides AND the
    filter's. The research's walks and the tab's one look both read this."""
    return ([m and k for m, k in zip(long_m, keep_l, strict=True)],
            [m and k for m, k in zip(short_m, keep_s, strict=True)])


def dirs_of(rule, ok_l, ok_s, a: int) -> list[int]:
    """The walk's +1 / -1 / 0 per candle of a view starting at candle `a`: the
    family's rule where its side is allowed there, else 0."""
    return [1 if r == 1 and ok_l[a + i] else -1 if r == -1 and ok_s[a + i] else 0
            for i, r in enumerate(rule)]


def _signals(rule, long_m, short_m, keep_l, keep_s, flags, a: int, start: int) -> dict:
    """Among a walk's tradable candles (from `start` to the one before last):
    the candles the rule held on inside the universe (`signal_candles`), the
    ones the filter blocked, and the filter's own counts (unknown, judged by
    the cycle)."""
    out: dict[str, int] = {}
    for i in range(int(start), len(rule) - 1):
        r, g = rule[i], a + i
        if not ((r == 1 and long_m[g]) or (r == -1 and short_m[g])):
            continue
        out["signal_candles"] = out.get("signal_candles", 0) + 1
        if not (keep_l[g] if r == 1 else keep_s[g]):
            out["blocked"] = out.get("blocked", 0) + 1
        if flags[g]:
            out[flags[g]] = out.get(flags[g], 0) + 1
    return out


def _measure_tf(rec: dict, sym: str, kind: str, tf: str, fams: list, pre: dict, plan: dict,
                runs: int, risk_usd: float) -> str:
    """Every family, setting and filter of one timeframe into `rec`; "" when
    measured, else why not."""
    from tradingagents import backtest_report as br
    from tradingagents.positions_view import fmt_when

    start, split, end = windows(plan)
    bar_s = br.TFS[tf][1]
    bar_ms = bar_s * 1000
    b = pre["bars"][tf]
    t = b["t"]
    i0, i1 = bisect.bisect_left(t, start), bisect.bisect_left(t, split)
    if i1 - i0 < 2 or len(t) - i1 < 2:
        return f"{max(0, i1 - i0)} older and {max(0, len(t) - i1)} unseen {tf} candles"
    order = [x + bar_ms for x in t]
    masks = {f: vfl.masks(f, sym=sym, kind=kind, order_ms=order, funding=pre["funding"],
                          cycle_h=pre["cycle_h"], plan=plan) for f in vf.filters_for(tf)}
    rec["windows"][tf] = {"start": fmt_when(t[i0] / 1000), "split": fmt_when(split / 1000),
                          "end": fmt_when(end / 1000), "older_candles": i1 - i0,
                          "unseen_candles": len(t) - i1}
    data = {"older": _before(pre, split),
            "unseen": {"fine": pre["fine"], "book": pre["book"], "funding": pre["funding"]}}
    common = {"bar_s": bar_s, "contract": pre["contract"], "fees": pre["fees"],
              "risk_usd": risk_usd}
    # each walk's own flat gap: the older days' where they have readings (`older_gap`), the whole
    # window's for the unseen walk and its random runs
    gap = {"older": pre.get("slip_older", pre["slip"]), "unseen": pre["slip"]}
    for fam in fams:
        if tf not in vf.FAMILIES[fam]["tfs"]:
            continue
        long_m, short_m = vf.sides_allowed(fam, sym, plan, order)
        days = vf.entry_days(fam, b, tf)
        for v in vf.FAMILIES[fam]["settings"]:
            lead, spec = vf.lead(fam, v, tf), vf.exit_spec(fam, v, tf)
            parts = {}
            for part, (a, z, s0) in (("older", (max(0, i0 - lead), i1, i0)),
                                     ("unseen", (max(0, i1 - lead), len(t), i1))):
                vb = _view(b, a, z)
                parts[part] = {"bars": vb, "a": a, "start": s0 - a,
                               "rule": vf.rule(fam, v, tf, vb, sym=sym, plan=plan),
                               "forced": vf.forced(fam, v, tf, vb, sym=sym, plan=plan)}
            for filt in vf.filters_for(tf):
                keep_l, keep_s, flags = masks[filt]
                ok_l, ok_s = allowed(long_m, short_m, keep_l, keep_s)
                out, walked = {}, {}
                for part, p in parts.items():
                    a = p["a"]
                    dirs = dirs_of(p["rule"], ok_l, ok_s, a)
                    walked[part] = ve.walk(p["bars"], dirs, spec, start=p["start"],
                                           forced=p["forced"], flat_slip=gap[part], **common,
                                           **data[part])
                    out[part] = compact(walked[part], p["bars"]["t"],
                                        _signals(p["rule"], long_m, short_m, keep_l, keep_s,
                                                 flags, a, p["start"]))
                u = parts["unseen"]
                seeds = [vrn.seed_of(sym, tf, fam, filt, k) for k in range(runs)]
                out |= _random_runs(
                    u, walked["unseen"], ok_l, ok_s, days, bar_ms, seeds,
                    {**common, **data["unseen"], "flat_slip": gap["unseen"], "start": u["start"],
                     "forced": u["forced"]},
                    spec)
                rec["combos"][vf.combo_key(fam, vf.setting_key(fam, v), tf, filt)] = out
    return ""


def inside_open_trades(walked: dict, dirs) -> int:
    """How many of a walk's placed entries (`dirs` not 0) the walk never looked
    at because its own trade was open on that candle: the candles after each
    trade's signal candle up to the candle it closed in (which may signal
    again), or to the last candle for a trade still open at the end (`END`).
    Counted where `v3_engine.walk` skips them, never worked out as a
    difference."""
    n, out = len(dirs), 0
    for x in walked["trades"]:
        last = n if x["why"] == "END" else int(x["exit_bar"])
        out += sum(1 for k in range(int(x["signal_bar"]) + 1, min(last, n)) if dirs[k])
    return out


def _random_runs(p: dict, real: dict, ok_l, ok_s, days, bar_ms: int, seeds, walk_kw: dict,
                 spec: dict) -> dict:
    """One random run per seed on the unseen view `p`: {"random": [[trades,
    profit], ...], "random_short": entries, over all the runs, that could not
    be placed (the month had too few candles to draw from), "random_refused":
    {engine count: entries} the walk turned away or that never filled
    (`DROPS`), summed over the runs, "random_in_trade": entries that fell
    inside the run's own open trade (`inside_open_trades`), summed}. Placed
    entries = trades + refused + in_trade, run by run. Entries are drawn where
    the side is allowed (universe and filter) on the family's entry days."""
    wanted = vrn.entries_by_month(real, p["bars"]["t"], bar_ms)
    if not wanted:
        return {"random": [[0, 0.0] for _ in seeds], "random_short": 0, "random_refused": {},
                "random_in_trade": 0}
    a, n = p["a"], len(p["rule"])
    cands = vrn.candidates(p["bars"]["t"], bar_ms, p["start"],
                           [ok_l[a + i] and days[a + i] for i in range(n)],
                           [ok_s[a + i] and days[a + i] for i in range(n)])
    out, short, refused, inside = [], 0, {}, 0
    for seed in seeds:
        dirs, missing = vrn.draw(n, wanted, cands, seed)
        short += missing
        w = ve.walk(p["bars"], dirs, spec, **walk_kw)
        out.append([len(w["trades"]), round(sum(float(x["pnl"]) for x in w["trades"]), 6)])
        for k in DROPS:
            if w["counts"].get(k):
                refused[k] = refused.get(k, 0) + int(w["counts"][k])
        inside += inside_open_trades(w, dirs)
    return {"random": out, "random_short": short, "random_refused": refused,
            "random_in_trade": inside}


def measure_coin(sym: str, plan: dict, *, runs: int = vrn.RUNS, risk_usd: float | None = None,
                 fx=None, log=None) -> dict:
    """Every combination the plan lets `sym` trade, walked older and unseen,
    with `runs` random runs each on the unseen window (see the module doc),
    every trade risking `risk_usd` (None: `v3_rules.RISK_USD`, the spec's
    $1). The risk decides which trades exist at all: a trade under one lot
    is skipped and counted (`too_small`), so coins measured at two risks
    are never pooled."""
    from tradingagents import v3_rules as vr

    risk_usd = vr.RISK_USD if risk_usd is None else float(risk_usd)
    if fx is None:
        from tradingagents.dataflows import exchange as fx
    kind = plan.get("kinds", {}).get(sym, "unknown")
    fams = [f for f in vf.FAMILIES if vf.applies(plan, f, sym)]
    _start, split, end = windows(plan)
    # The plan's BUILD is stamped beside its end: every build of one UTC day ends on one instant, so
    # the end cannot say which plan a coin was measured under. A plan built or loaded carries its
    # `id`; a hand-made one is fingerprinted by its content
    rec = {"version": VERSION, "coin": sym, "kind": kind,
           "plan_id": plan.get("id") or vu.plan_id(plan), "plan_end_ms": int(plan["end_ms"]),
           "unseen_months": [vu.month_key(x) for x in vu.months_between(split, end)],
           "families": fams, "runs": int(runs), "risk_usd": risk_usd, "windows": {}, "combos": {},
           "skipped": {}}
    if not fams:
        rec["why"] = "in no family's universe in any month of the plan"
        return rec
    tfs = [tf for tf in TF_ORDER if any(tf in vf.FAMILIES[f]["tfs"] for f in fams)]
    leads = {tf: max(vf.lead(f, v, tf) for f in fams if tf in vf.FAMILIES[f]["tfs"]
                     for v in vf.FAMILIES[f]["settings"]) for tf in tfs}
    t0 = time.time()
    pre = prefetch(sym, plan, leads, fx=fx)
    rec["pre"] = {**pre["meta"], "seconds": round(time.time() - t0, 1)}
    for tf in tfs:
        t1 = time.time()
        why = _measure_tf(rec, sym, kind, tf, fams, pre, plan, runs, risk_usd)
        if why:
            rec["skipped"][tf] = why
        else:
            rec["windows"][tf]["seconds"] = round(time.time() - t1, 1)
        if log:
            log(f"  {sym} {tf}: {why or 'measured'} ({time.time() - t1:.0f} s)")
    return rec
