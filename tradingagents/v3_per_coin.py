"""BACKTEST V3, JUDGED COIN BY COIN (Nov 03, 2026).

The operator: "can you run backtest for v3 for all coins all time frame and all strategy and tell
me which are profitable? even winrate is low as long as the win ratio is high, its ok", and the
three choices made that day: the older days' per-minute order-book costs filled first, each idea
on its own timeframes (the 63 combinations as built), and "profitable" = made money after every
fee on the 90 unseen days it was never tuned on, with 20+ trades, shown beside what random buys
made on the same coin.

    python -m tradingagents.v3_per_coin publish <name>

`<name>` is a run `v3_cloud dispatch` started and `collect` brought home, with every redo of it -
ONE run family, under the plan it was dispatched with, as the pooled store judges it
(`v3_verdicts.load_family`). For every coin and every judged group (family x timeframe x filter,
`v3_families.judged`, 27) the coin measured (`judge`):

1. CHOOSE on THAT coin's older walk: the best profit a trade after every fee among the settings
   with at least MIN_OLDER older trades, a tie to the simplest (the family's first setting); none
   with MIN_OLDER -> "could not choose", with why.
2. JUDGE it on that coin's unseen walk: PROFITABLE when its profit after every fee is above 0 and
   it made at least MIN_UNSEEN trades.
3. Beside it, from the coin's own random runs of that setting (`v3_random`, `RUNS` of them, on
   the same unseen days): their median profit, the share that made at least as much as the real
   run (`luck_share`), and the share that would be PROFITABLE by the same rule
   (`luck_profitable`). Added up over the rows, `luck_profitable` is how many rows luck alone
   would make profitable - the number the profitable count has to beat.

Written to `stores.V3.home/verdicts-per-coin.json` (VERSION), swapped whole, and kept for good in
`verdicts-per-coin/<name>-<ms>.json` (`v3_verdicts.keep_and_swap`). The pooled verdict store and
the Backtest v3 tab are untouched. The results page is `v3_per_coin_page`.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import statistics
import sys
import time
from pathlib import Path

VERSION = 1
MIN_OLDER = 10
MIN_UNSEEN = 20
RULE = (f"Each coin by itself: the setting with the best profit a trade after every fee on that "
        f"coin's older days, among the settings with at least {MIN_OLDER} older trades (a tie goes "
        f"to the simplest, the family's first setting; none with {MIN_OLDER} = could not choose), "
        f"judged on the coin's 90 unseen days, never tuned on: PROFITABLE when it made money after "
        f"every fee with at least {MIN_UNSEEN} trades. Beside it, the coin's own random runs of "
        "that setting on the same days: their median profit, the share that made at least as "
        "much, and the share that would be PROFITABLE by the same rule.")


def store_path() -> Path:
    from tradingagents import stores

    return Path(stores.V3.home) / "verdicts-per-coin.json"


def history_dir() -> Path:
    from tradingagents import stores

    return Path(stores.V3.home) / "verdicts-per-coin"


def row_id(coin: str, family: str, tf: str, filt: str, setting: str | None) -> str:
    """A coin x group row's stable id (kit H): hashed from the coin, the group and the chosen
    setting with res="v3" - never a pooled verdict's id (`v3_families.verdict_id`, coin "ALL")."""
    from tradingagents import backtest_report as br

    return br.row_code(coin, tf, family, 0.0, 0.0, 0.0, "flat",
                       plan=f"percoin|{filt}|{setting or 'none'}", res="v3")


def _spread(xs):
    return [min(xs), statistics.median(xs), max(xs)] if xs else None


def judge(rec: dict, family: str, tf: str, filt: str) -> dict | None:
    """One coin's row for one judged group, or None when the coin did not measure it (outside the
    family's universe in every month, or the timeframe skipped). Every row carries every field; a
    number the row does not have is None with `blank` saying why."""
    from tradingagents import (
        v3_coverage as vcv,
        v3_families as vf,
        v3_measure as vm,
        v3_proof as vp,
        v3_research as vrs,
        v3_universe as vu,
    )

    combos = rec.get("combos", {})
    keys = [vf.setting_key(family, v) for v in vf.FAMILIES[family]["settings"]]
    ck = {k: vf.combo_key(family, k, tf, filt) for k in keys}
    if not any(ck[k] in combos for k in keys):
        return None
    older = {k: list(combos.get(ck[k], {}).get("older", {}).get("rows") or []) for k in keys}
    chosen, table = vp.choose(older, keys, min_trades=MIN_OLDER)
    win = rec.get("windows", {}).get(tf) or {}
    days = (int(win["unseen_candles"]) / vf.BARS_PER_DAY[tf]
            if win.get("unseen_candles") is not None else float(vm.UNSEEN_DAYS))
    months_all = list(rec.get("unseen_months") or [])
    base = {"id": row_id(rec["coin"], family, tf, filt, chosen), "coin": rec["coin"],
            "kind": rec.get("kind", "unknown"), "family": family, "tf": tf, "filter": filt,
            "setting": chosen,
            "older": {k: [o["trades"], o["per_trade"]] for k, o in table.items()},
            "days": days, "unseen_months": months_all}
    blank_keys = ("trades", "wins", "losses", "win_rate", "profit", "per_trade", "avg_win",
                  "avg_loss", "win_loss_ratio", "worst_run_usd", "worst_run_trades",
                  "open_at_end", "per_day", "wins_per_day", "losses_per_day", "green",
                  "random_median", "random_runs", "luck_share", "luck_profitable", "lev",
                  "notional")
    if chosen is None:
        most = vp._blocked_all([rec], ck, keys)
        counts = vp.tally([combos[ck[k]]["older"] for k in keys if ck[k] in combos])["counts"]
        if most is not None:
            why = f"{filt} blocked all {most:,} signals on the older days"
        else:
            why = f"no setting had {MIN_OLDER} trades on the older days"
            refused = vp._refusal_words(counts, rec.get("risk_usd"), len(keys))
            if refused:
                why += f": {refused}"
        costs = vcv.verdict_costs([rec], {"family": family, "tf": tf, "filter": filt,
                                          "older": table, "setting": None})
        return {**base, **dict.fromkeys(blank_keys), "verdict": "could not choose",
                "profitable": False, "why": why, "blank": f"could not choose: {why}",
                "months": {}, "levels": {"stop": None, "target": None},
                "target_rule": None, "stop_rule": None,
                "cost": {"older": vcv.share_words(costs["older"]), "unseen": "no setting chosen",
                         "share": None}}
    combo = combos[ck[chosen]]
    rows = list(combo.get("unseen", {}).get("rows") or [])
    s = vp.summary(rows)
    pnls = [float(r[4]) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [-p for p in pnls if p <= 0]
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    n, profit = s["trades"], s["profit"]
    profitable = n >= MIN_UNSEEN and profit > 0
    if profitable:
        verdict = "PROFITABLE"
    elif not n:
        verdict = "not profitable: no trade on the unseen days"
    elif n < MIN_UNSEEN:
        verdict = f"not profitable: {n} trades, under {MIN_UNSEEN}"
    else:
        verdict = (f"not profitable: lost ${-profit:,.2f}" if profit < 0
                   else f"not profitable: made ${profit:,.2f}")
    months: dict[str, float] = {}
    for r in rows:
        m = vu.month_key(int(r[2]))
        months[m] = months.get(m, 0.0) + float(r[4])
    runs = [(int(k), float(p)) for k, p in combo.get("random") or []]
    target, stop = vrs.exit_words(family, chosen, tf)
    costs = vcv.verdict_costs([rec], {"family": family, "tf": tf, "filter": filt, "older": table,
                                      "setting": chosen})
    uc = costs["unseen"]
    unseen_walk = combo.get("unseen", {})
    return {**base, "verdict": verdict, "profitable": profitable,
            "why": "" if n else "no trade on the unseen days",
            "blank": "" if n else "no trade on the unseen days",
            "trades": n, "wins": s["wins"], "losses": s["losses"], "win_rate": s["win_rate"],
            "profit": profit, "per_trade": s["per_trade"], "avg_win": avg_win,
            "avg_loss": avg_loss,
            "win_loss_ratio": avg_win / avg_loss if avg_win and avg_loss else None,
            "worst_run_usd": s["worst_run_usd"], "worst_run_trades": s["worst_run_trades"],
            "open_at_end": s["open_at_end"], "per_day": n / days if days else None,
            "wins_per_day": s["wins"] / days if days else None,
            "losses_per_day": s["losses"] / days if days else None,
            "months": months, "green": [sum(1 for v in months.values() if v > 0), len(months_all)],
            "random_median": statistics.median(p for _k, p in runs) if runs else None,
            "random_runs": len(runs),
            "luck_share": sum(1 for _k, p in runs if p >= profit) / len(runs) if runs else None,
            "luck_profitable": (sum(1 for k, p in runs if k >= MIN_UNSEEN and p > 0) / len(runs)
                                if runs else None),
            "lev": unseen_walk.get("lev"), "notional": unseen_walk.get("notional"),
            "levels": {"stop": _spread([float(r[6]) for r in rows if len(r) > 6
                                        and r[6] is not None]),
                       "target": _spread([float(r[7]) for r in rows if len(r) > 7
                                          and r[7] is not None])},
            "target_rule": target, "stop_rule": stop,
            "cost": {"older": vcv.share_words(costs["older"]),
                     "unseen": vcv.share_words(uc) if uc else "no trade",
                     "share": (round(uc["typical_low"] / uc["legs"], 4)
                               if uc and uc.get("legs") else None)}}


def rows_of(records: list[dict]) -> list[dict]:
    """Every coin x judged group row the records measured, coin by coin in `judged()` order."""
    from tradingagents import v3_families as vf

    out = []
    for rec in sorted(records, key=lambda r: r["coin"]):
        if rec.get("why") or not rec.get("windows"):
            continue
        for fam, tf, filt in vf.judged():
            row = judge(rec, fam, tf, filt)
            if row is not None:
                out.append(row)
    return out


def totals(rows: list[dict]) -> dict:
    """The counts the page heads its table with, from the rows: judged, profitable, could not
    choose, no unseen trade, and what luck alone would make profitable (each row's
    `luck_profitable` added up)."""
    return {"rows": len(rows), "profitable": sum(1 for r in rows if r["profitable"]),
            "could_not_choose": sum(1 for r in rows if r["setting"] is None),
            "no_trade": sum(1 for r in rows if r["setting"] is not None and not r["trades"]),
            "luck_profitable": round(sum(r["luck_profitable"] or 0.0 for r in rows), 4),
            "coins": len({r["coin"] for r in rows})}


def build(name: str, *, now: float | None = None) -> dict:
    """The per-coin store's content for the collected run `name` and every redo of it, under the
    plan it was dispatched with; refused by name exactly as the pooled store refuses
    (`v3_verdicts.load_family`). What was not judged is named as the pooled store names it."""
    from tradingagents import (
        v3_families as vf,
        v3_proof as vp,
        v3_universe as vu,
        v3_verdicts as vv,
    )
    from tradingagents.v3_measure import windows

    members, plan, records, other = vv.load_family(name)
    state = members[0][1]
    start, split, end = windows(plan)
    measured, not_judged, accounts = vv.unjudged(members, plan, records, other)
    rows = rows_of(records)
    return {"version": VERSION, "kind": "per_coin", "name": name,
            "family": [m for m, _st, _su in members], "folder": state["folder"],
            "label": state["label"], "venue": plan.get("venue") or "", "plan_id": plan["id"],
            "plan_kind": vu.kind_of(plan), "plan_start": start, "plan_split": split,
            "plan_end": end, "risk_usd": float(state["risk_usd"]),
            "runs": int(state["runs_per_combo"]), "tried": vp.TRIED,
            "groups": len(vf.judged()),
            "min_older": MIN_OLDER, "min_unseen": MIN_UNSEEN, "rule": RULE,
            "judged_at": time.time() if now is None else float(now),
            "github_runs": vv.runs_of(name, members), "coins": measured,
            "plan_coins": len(plan["coins"]), "dispatched": len(state["board"]),
            "unseen_months": next((r["unseen_months"] for r in records if r.get("unseen_months")),
                                  []),
            "not_judged": not_judged, "accounts": accounts, "totals": totals(rows),
            "notes": [vu.SURVIVORSHIP], "rows": rows}


def publish(name: str, *, now: float | None = None) -> Path:
    """Write the per-coin store and its kept copy; the store's path."""
    from tradingagents import v3_verdicts as vv

    data = build(name, now=now)
    return vv.keep_and_swap(json.dumps(data, default=str), name, data["judged_at"], store_path(),
                            history_dir())


def money(x) -> str:
    return "-" if x is None else f"{'+' if x > 0 else '-' if x < 0 else ''}${abs(x):,.2f}"


def lines_of(data: dict, top: int = 40) -> list[str]:
    """What `publish` prints: the counts, then the profitable rows by profit, best first."""
    t = data["totals"]
    out = [f"{t['rows']:,} coin x idea rows judged on {t['coins']:,} coins of the plan's "
           f"{data['plan_coins']:,} ({data['groups']} ideas a coin, {data['tried']} combinations "
           f"each): {t['profitable']:,} profitable (made money after every fee with "
           f"{data['min_unseen']}+ trades on the unseen days); luck alone would make "
           f"{t['luck_profitable']:,.1f} of them profitable (each row's share of its "
           f"{data['runs']} random runs that pass the same rule, added up); "
           f"{t['could_not_choose']:,} could not choose a setting, {t['no_trade']:,} made no "
           "unseen trade.", data["rule"]]
    best = sorted((r for r in data["rows"] if r["profitable"]), key=lambda r: -r["profit"])
    for r in best[:top]:
        ratio = "-" if r["win_loss_ratio"] is None else f"{r['win_loss_ratio']:.2f}"
        out.append(f"#{r['id']} {r['coin']} {r['family']} {r['tf']} {r['filter']} "
                   f"{r['setting']}: PROFITABLE {money(r['profit'])} over {r['trades']} trades, "
                   f"{100 * r['win_rate']:.1f}% won, a win {money(r['avg_win'])} against a loss "
                   f"{money(-(r['avg_loss'] or 0))} ({ratio}x), random median "
                   f"{money(r['random_median'])}, {100 * (r['luck_share'] or 0):.1f}% of random "
                   "runs made as much")
    if len(best) > top:
        out.append(f"... and {len(best) - top:,} more profitable rows on the page")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_per_coin")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("publish", help="judge a collected run coin by coin and keep it").add_argument(
        "name")
    a = p.parse_args(argv)
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8")        # coin names in Chinese (RCA-2026-10-30-G)
    path = publish(a.name)
    data = json.loads(path.read_text(encoding="utf-8"))
    print("\n".join(lines_of(data)))
    print(f"kept: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
