"""THE PRO TRADER RESULTS PAGE'S DATA (Oct 20, 2026).

The operator: "show me the results each day per coin per time frame in artefact
so i can review it if we can push to prod". From a collected search
(pro_search.collect) this module makes:

* the CHOICE: one setting per coin + timeframe, chosen on the days before the
  four test months (pro_report.choose, upto=1) — never on the days it is judged;
* the CHECK PLAN: those settings, measured again by the check run over the
  search's own bars with every trade kept (research/pro/<name>.json.gz in the
  repository, which the machines read);
* the PAGE ROWS: each choice's trades on the 120 untouched days, its checks
  (pro_checks), the walk-forward beside it, and a stable id
  (backtest_report.row_code, the id the app would give the same combination).

Nothing here switches anything on, files anything into Stored strategies or
adds anything to the nightly grid.
"""
from __future__ import annotations

import gzip
import json
import math
from pathlib import Path

DAY_MS = 86_400_000
OOS_DAYS = 120                   # the four test months
MARGIN = 5.0
LEVERAGE = 20
FILE_ROWS = 150                  # rows per trade file the page loads on a click


def search_of(state_name: str | None = None) -> dict:
    """A collected search, read back: lines, months, coin stats, report and
    groups."""
    from tradingagents import pro_report as pr, pro_search as ps

    stem = Path(state_name or ps.STATE).stem
    got = json.loads((ps.home() / f"{stem}-collected.json").read_text(encoding="utf-8"))
    roots = got["roots"]
    lines = ps.read_lines(roots)
    if not lines:
        raise RuntimeError(f"the search {got.get('label')} wrote no lines")
    stats = ps.read_json_parts(roots, "pro-coins-*.json")
    report = ps.read_json_parts(roots, "pro-report-*.json", "report")
    return {"collected": got, "lines": lines, "mon": pr.months(lines), "stats": stats,
            "report": report, "groups": pr.groups(stats)}


def key_of(lines: dict, i: int) -> str:
    """'name:tf:sl:tp' (percent) of line i — the check run's own spelling."""
    tf = str(lines["tfs"][int(lines["tf"][i])])
    sl, tp = (float(x) for x in lines["barriers"][f"barriers_{tf}"][int(lines["bar"][i])])
    return f"{lines['names'][int(lines['var'][i])]}:{tf}:{round(sl * 100, 4):g}:{round(tp * 100, 4):g}"


def last_bars(report: list) -> dict:
    """(coin, tf) -> the search's last measured bar (unix s)."""
    return {(e["coin"], e["tf"]): int(e["last"]) for e in report
            if isinstance(e, dict) and e.get("last") and not e.get("error")}


def check_plan(S: dict, picks: dict) -> dict:
    """The check run's plan: per coin its search-time choices of minutes, book
    and usual cost ('pre'), and per timeframe the last bar and the chosen
    settings. A pick whose pair the report cannot date is refused by name."""
    L = S["lines"]
    last = last_bars(S["report"])
    plan: dict = {}
    for (ci, ti), (i, _how) in sorted(picks.items()):
        coin, tf = str(L["coins"][ci]), str(L["tfs"][ti])
        if (coin, tf) not in last:
            raise ValueError(f"{coin} {tf}: the report has no last bar for a chosen pair")
        pre = (S["stats"].get(coin) or {}).get("pre")
        if not pre:
            raise ValueError(f"{coin}: the search kept no minutes/book/cost choices")
        ent = plan.setdefault(coin, {"pre": pre, "tfs": {}})
        ent["tfs"].setdefault(tf, {"last": last[(coin, tf)], "keys": []})["keys"].append(key_of(L, i))
    return plan


def write_plan(plan: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(plan, fh, separators=(",", ":"))
    return path


def oos_start(last_s: int) -> int:
    """The first ms of a pair's untouched days: the engine counts its windows
    back from the pair's last bar's OPEN (sweep_shard's recent_windows)."""
    return int(last_s) * 1000 - OOS_DAYS * DAY_MS


def row_id(coin: str, tf: str, name: str, sl: float, tp: float) -> str:
    from tradingagents import backtest_report as br

    return br.row_code(coin, tf, name, 0.0, sl, tp, "flat", res="1m")


def rows(S: dict, picks: dict, wf: dict, check_lines: list) -> tuple[list, dict, list]:
    """(page rows, {file name: {row id: trades}}, problems). Each row: the
    pick's untouched-days trades [entry ms, exit ms, side, why, profit], its
    checks and verdict. A pick the check run did not return is NAMED in the
    problems, never dropped silently."""
    from tradingagents import pro_checks as pck, pro_report as pr, signals_pro as sp

    L, mon, grp = S["lines"], S["mon"], S["groups"]
    ix = pck.Index(L, mon)
    last = last_bars(S["report"])
    got = {(x["coin"], x["tf"], x["cfg"]): x for x in check_lines}
    coins = list(L["coins"])
    by_group: dict = {}
    for c, g in grp.items():
        if c in coins:
            by_group.setdefault(g, []).append(coins.index(c))
    sl_all, tp_all = pr.stops_targets(L)
    out, problems, logs = [], [], {}
    for (ci, ti), (i, how) in sorted(picks.items()):
        coin, tf = coins[ci], str(L["tfs"][ti])
        key = key_of(L, i)
        line = got.get((coin, tf, key))
        if line is None:
            problems.append(f"{coin} {tf} {key}: the check run returned no trades")
            continue
        start = oos_start(last[(coin, tf)])
        trades = [t for t in line["trades"] if int(t[1]) >= start]
        name = str(L["names"][int(L["var"][i])])
        sl, tp = float(sl_all[i]), float(tp_all[i])
        group = grp.get(coin, "?")
        cks = pck.checks(ix, ci, ti, i, how, group, by_group.get(group, []), trades,
                         (wf or {}).get((ci, ti)))
        rt = float(L["vals"][i][pr.F["rt_paid"]])
        rt = 0.23 if math.isnan(rt) else rt
        rid = row_id(coin, tf, name, sl, tp)
        # the search's own count for the four months beside the check run's:
        # the same bars and costs, so they must agree (named if not)
        want = int(round(float(mon[i, 1:, 0].sum())))
        if want != len(trades):
            problems.append(f"#{rid} {coin} {tf} {key}: the check run kept {len(trades)} "
                            f"untouched-days trades where the search counted {want}")
        before = mon[i, 0]
        spec = sp.spec_for(name)
        out.append({
            "id": rid, "coin": coin, "tf": tf, "group": group,
            # a name the families cannot read keeps its own code (never a blank)
            "fam": spec["family"] if spec else name.split("_")[1],
            "name": name, "words": sp.words(name) or name, "how": how, "sl": round(sl, 4),
            "tp": round(tp, 4), "be": round(pck.break_even(sl, tp, rt), 2), "rt": round(rt, 4),
            "pass": pck.passed(cks), "ok": sum(1 for c in cks if c[2] is True),
            "checks": [list(c) for c in cks],
            "chosen_on": {"trades": int(before[0]), "wins": int(before[1]),
                          "profit": round(float(before[2]), 2)},
            "tr": [[int(t[1]), round(float(t[4]), 2)] for t in trades],
        })
        logs[rid] = [[int(t[0]), int(t[1]), int(t[2]), str(t[3]), round(float(t[4]), 2)]
                     for t in trades]
    out.sort(key=lambda r: r["id"])
    files: dict = {}
    for k in range(0, len(out), FILE_ROWS):
        fname = f"trades/part-{k // FILE_ROWS:03d}.json"
        files[fname] = {}
        for r in out[k:k + FILE_ROWS]:
            r["file"] = fname
            files[fname][r["id"]] = logs[r["id"]]
    return out, files, problems


def baseline(S: dict, picks: dict) -> dict:
    """Random entries on the same coins, timeframes and stop/targets as the
    picks, over the same four months: $ a trade (the luck bar)."""
    from tradingagents import pro_report as pr

    L, mon = S["lines"], S["mon"]
    base = pr.baseline_mask(L)
    want = {(int(L["coin"][i]), int(L["tf"][i]), int(L["bar"][i])) for i, _h in picks.values()}
    t = p = 0.0
    for j in range(len(L["vals"])):
        if base[j] and (int(L["coin"][j]), int(L["tf"][j]), int(L["bar"][j])) in want:
            t += float(mon[j, 1:, 0].sum())
            p += float(mon[j, 1:, 2].sum())
    return {"trades": int(t), "profit": round(p, 2), "per_trade": round(p / t, 4) if t else None}


def walk_total(wf: dict) -> dict:
    """Re-choosing before each month: every month's pick judged on that month."""
    t = w = p = 0.0
    n = 0
    for months in (wf or {}).values():
        for m in months:
            if m:
                n += 1
                t += m[2]
                w += m[3]
                p += m[4]
    return {"picks": n, "trades": int(t), "wins": int(w), "profit": round(p, 2)}
