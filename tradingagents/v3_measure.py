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
  so the setting can never be chosen on an unseen price — by construction;
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
side, pnl, why], the engine's counts, the filter's counts, and each random
run's [trades, profit].
"""
from __future__ import annotations

import bisect
import time

from tradingagents import (
    v3_engine as ve,
    v3_families as vf,
    v3_filters as vfl,
    v3_random as vrn,
    v3_universe as vu,
)

VERSION = 1
UNSEEN_DAYS = 90
DAY_MS = 86_400_000
BOOK_USD = 100.0          # a recorded reading is the cost of walking the book for $100
FUNDING_PAD_DAYS = 31     # funding_side reads the 30 days before each order
TF_ORDER = ("1h", "4h", "1d")


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


def flat_gap(sym: str, book, *, fx) -> tuple[float, str]:
    """The coin's own usual one-side cost where a minute has no recorded
    book, and where it came from (said beside every result)."""
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br, cost_store

    slip, n = cost_store.usual_slip(book)
    if slip is not None:
        return slip, f"the median of its {n:,} recorded minutes"
    try:
        live = float(fx.book_cost(sym, BOOK_USD).get("slippage") or 0.0)
        return (br.charged_slippage([live or at.PAPER_SLIPPAGE]),
                "one live reading of its book (no minute recorded)")
    except Exception as exc:                                   # noqa: BLE001
        return at.PAPER_SLIPPAGE, (f"the app's paper figure: no book could be read "
                                   f"({type(exc).__name__})")


def prefetch(sym: str, plan: dict, leads: dict, *, fx) -> dict:
    """Everything one coin's walks read, fetched ONCE: {tf: bars} with each
    timeframe's longest lead-in before the window, the minutes of the window,
    its order books, funding, the listing and the fees."""
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br, cost_store

    start, split, end = windows(plan)
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
    slip, source = flat_gap(sym, book, fx=fx)
    funding = [f for f in fx.funding_history(sym, since_ms=start - FUNDING_PAD_DAYS * DAY_MS)
               if int(f["settle_ms"]) <= end]
    fees = {"maker": at.maker_fee_floor(), "taker": at.fee_floor()}
    meta = {"contract": contract, "fees": fees, "flat_slip": slip, "flat_slip_source": source,
            "minutes": len(fine[0]), "five_minute": int(n5),
            "coverage_older": cost_store.coverage(book, start // 1000, split // 1000),
            "coverage_unseen": cost_store.coverage(book, split // 1000, end // 1000),
            "funding": len(funding),
            "funding_from_ms": int(funding[0]["settle_ms"]) if funding else None,
            "cycle_h": float(spec.get("funding_interval_h") or 8)}
    return {"bars": bars, "fine": fine if fine[0] else None, "book": book, "funding": funding,
            "contract": contract, "fees": fees, "slip": slip, "cycle_h": meta["cycle_h"],
            "meta": meta}


def _before(pre: dict, split: int) -> dict:
    """The older walk's data: minutes, order books and funding CUT at the
    split, so nothing it reads can be an unseen price."""
    fine, book = pre["fine"], pre["book"]
    if fine is not None:
        j = bisect.bisect_left(fine[0], split)
        fine = (fine[0][:j], fine[1][:j], fine[2][:j])
    if book is not None:
        import numpy as np

        j = int(np.searchsorted(book["t"], split // 1000, side="left"))
        book = {k: v[:j] for k, v in book.items()}
    return {"fine": fine, "book": book,
            "funding": [f for f in pre["funding"] if int(f["settle_ms"]) <= split]}


def _view(bars: dict, a: int, b: int) -> dict:
    return {k: v[a:b] for k, v in bars.items()}


def compact(walked: dict, t, signals: dict) -> dict:
    """One walk in the shape every machine returns."""
    trades = walked["trades"]
    twins = [m["market"] for m in walked["missed"] if "pnl" in m["market"]]
    lev = [int(x["leverage"]) for x in trades]
    notional = [float(x["notional"]) for x in trades]
    return {"rows": [[int(t[x["signal_bar"]]), int(x["entry_ms"]), int(x["exit_ms"]),
                      int(x["side"]), round(float(x["pnl"]), 6), x["why"]] for x in trades],
            "counts": {k: int(v) for k, v in walked["counts"].items() if v},
            "filter": signals, "missed": len(walked["missed"]),
            "twins": [len(twins), round(sum(float(x["pnl"]) for x in twins), 6)],
            "lev": [min(lev), max(lev)] if lev else None,
            "notional": [round(min(notional), 2), round(max(notional), 2)] if notional else None,
            "over_book": sum(1 for x in notional if x > BOOK_USD)}


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
                          cycle_h=pre["cycle_h"], plan=plan) for f in vf.FILTERS}
    rec["windows"][tf] = {"start": fmt_when(t[i0] / 1000), "split": fmt_when(split / 1000),
                          "end": fmt_when(end / 1000), "older_candles": i1 - i0,
                          "unseen_candles": len(t) - i1}
    data = {"older": _before(pre, split),
            "unseen": {"fine": pre["fine"], "book": pre["book"], "funding": pre["funding"]}}
    common = {"bar_s": bar_s, "contract": pre["contract"], "fees": pre["fees"],
              "flat_slip": pre["slip"], "risk_usd": risk_usd}
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
            for filt in vf.FILTERS:
                keep_l, keep_s, flags = masks[filt]
                ok_l = [m and k for m, k in zip(long_m, keep_l, strict=True)]
                ok_s = [m and k for m, k in zip(short_m, keep_s, strict=True)]
                out, walked = {}, {}
                for part, p in parts.items():
                    a = p["a"]
                    dirs = [1 if r == 1 and ok_l[a + i] else -1 if r == -1 and ok_s[a + i] else 0
                            for i, r in enumerate(p["rule"])]
                    walked[part] = ve.walk(p["bars"], dirs, spec, start=p["start"],
                                           forced=p["forced"], **common, **data[part])
                    out[part] = compact(walked[part], p["bars"]["t"],
                                        _signals(p["rule"], long_m, short_m, keep_l, keep_s,
                                                 flags, a, p["start"]))
                u = parts["unseen"]
                seeds = [vrn.seed_of(sym, tf, fam, filt, k) for k in range(runs)]
                out["random"], out["random_short"] = _random_runs(
                    u, walked["unseen"], ok_l, ok_s, days, bar_ms, seeds,
                    {**common, **data["unseen"], "start": u["start"], "forced": u["forced"]},
                    spec)
                rec["combos"][vf.combo_key(fam, vf.setting_key(fam, v), tf, filt)] = out
    return ""


def _random_runs(p: dict, real: dict, ok_l, ok_s, days, bar_ms: int, seeds, walk_kw: dict,
                 spec: dict) -> tuple[list, int]:
    """One random run per seed on the unseen view `p`: [[trades, profit], ...]
    and how many entries, over all the runs, could not be placed. Entries are
    drawn where the side is allowed (universe and filter) on the family's
    entry days."""
    wanted = vrn.entries_by_month(real, p["bars"]["t"], bar_ms)
    if not wanted:
        return [[0, 0.0] for _ in seeds], 0
    a, n = p["a"], len(p["rule"])
    cands = vrn.candidates(p["bars"]["t"], bar_ms, p["start"],
                           [ok_l[a + i] and days[a + i] for i in range(n)],
                           [ok_s[a + i] and days[a + i] for i in range(n)])
    out, short = [], 0
    for seed in seeds:
        dirs, missing = vrn.draw(n, wanted, cands, seed)
        short += missing
        w = ve.walk(p["bars"], dirs, spec, **walk_kw)
        out.append([len(w["trades"]), round(sum(float(x["pnl"]) for x in w["trades"]), 6)])
    return out, short


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
    rec = {"version": VERSION, "coin": sym, "kind": kind, "plan_end_ms": int(plan["end_ms"]),
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
