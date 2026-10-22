"""Land the CONFLUENCE STORE run in Backtest v2 as the group "Oct 22".

The operator, Oct 22, 2026, after the confluence research (Prompt 1): *"Okay
deploy them in production, i want t to see then in stored strategies"* — the
group filter of Stored strategies, beside "Oct 21".

Three steps:

* THE PLAN (`build_plan`; `python -m tradingagents.cq_store plan`): every
  pick the search found on the all-coins page — per coin and timeframe, the
  pick of each payout: a name, a stop and a target, and the name's plain
  words — written to research/cq/store_plan.json, which is committed so the
  machines read it from main. Never a random entry: the luck search is the
  bar the picks were judged against, not a strategy.
* THE MEASURE (.github/workflows/cq.yml with store=1 ->
  .github/scripts/cq_store_shard.py): each pick measured exactly as a
  Backtest v2 row is, at its own stop and target.
* THE LANDING (`collect`): `pro_store.land`, the one body the group "Oct 21"
  lands through — per answered pair the old cq_ rows out and the new in under
  the pair's lock, the watermark never moved, each hundred pairs filed as
  soon as they are rewritten — then the group's own sort index started.

Nothing is switched on: a row in Stored strategies is a measurement, and a
strategy reaches a room only through the rooms' own rules. The nightly
update does not measure cq_ rules again (like "Oct 21", "Sep 25 Strat" and
"Sep 27 ML"): the rows are the last 30 days as of the store run.

    python -m tradingagents.cq_store plan
    python -m tradingagents.cq_store collect [state-name]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from tradingagents import learn_collect as lc, pro_store as pst

ROOT = Path(__file__).resolve().parent.parent
PLAN_FILE = ROOT / "research" / "cq" / "store_plan.json"
REPORT_FILE = Path(__file__).resolve().parent / "learned" / "oct22_report.json"
# the runs behind the all-coins page (Oct 22, 2026): the full market, its six
# follow-ups and the coins named in Chinese characters
STATES = ("full", "full-b-0", "full-b-1", "full-b-2", "full-b-3", "full-b-4", "full-b-5",
          "full-c")
CQ = lc.Family("cq", "cq_", "", "", ("cq-out-*",), "cq-store", "rows_cq_profit", "CQ_TERMS")
OCT22 = pst.Group("oct22", "Oct 22", CQ, "cq-rows-*.jsonl", lambda: REPORT_FILE)


def build_plan(coins: dict, label: str) -> dict:
    """{coin: {tf: [[name, sl %, tp %], ...]}} from cq_report.results' coins:
    the search's picks in payout order, each (name, stop, target) once, never
    a random entry, and every name's plain words (`names`), which a machine
    compares with its own code before it measures the name."""
    from tradingagents import signals_cq as sq
    from tradingagents.positions_view import fmt_when

    out: dict = {}
    names: dict = {}
    n = 0
    for coin, rec in sorted(coins.items()):
        for tf, res in sorted((rec.get("tfs") or {}).items()):
            picks = ((res or {}).get("search") or {}).get("picks") or {}
            seen: set = set()
            for _k, p in sorted(picks.items(), key=lambda kv: int(kv[0])):
                name, sl, tp = p["cand"][:3]
                name = str(name)
                if not name.startswith(sq.PREFIX) or name.startswith(sq.PREFIX + "rn"):
                    continue
                key = (name, float(sl), float(tp))
                if key in seen:
                    continue
                seen.add(key)
                out.setdefault(coin, {}).setdefault(tf, []).append([name, float(sl), float(tp)])
                names[name] = sq.words(name)
                n += 1
    return {"made": fmt_when(time.time()), "from": label, "picks": n,
            "pairs": sum(len(t) for t in out.values()), "names": dict(sorted(names.items())),
            "coins": out}


def plan_from_states(states=STATES) -> dict:
    """The plan of the runs behind the all-coins page, read from their
    collected folders on the store's drive."""
    from tradingagents import cq_report as cr, cq_search as cqs

    roots, labels = [], []
    for st in states:
        got = json.loads((cqs.home() / f"{st}-collected.json").read_text(encoding="utf-8"))
        roots += got["roots"]
        labels.append(f"{got['label']} (runs {', '.join(str(v) for v in got['runs'].values())})")
    return build_plan(cr.results(roots)["coins"], "; ".join(labels))


def write_plan(plan: dict, path: Path = PLAN_FILE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(plan, ensure_ascii=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return path


def land(report: list, roots, *, run=None) -> dict:
    """Write one store run into the v2 store, through the one landing body."""
    return pst.land(report, roots, run=run, group=OCT22)


def start_group_index() -> bool:
    return pst.start_group_index(OCT22)


def measured(roots, report: list) -> dict:
    """What the run measured, out loud: picks, rows, every pick with no row
    counted by why, and the trades' costs - how many paid their own minute's
    order book and how many a coin's usual cost (`cost_unmeasured`, CLAUDE.md:
    every backtest looks at the costs of every minute it tests)."""
    from tradingagents import backtest_report as br

    why: dict = {}
    picks = 0
    for e in report:
        if e.get("tf") in (None, "*"):
            continue
        picks += int(e.get("picks") or 0)
        for m in e.get("missing") or []:
            # [name, stop, target, why, kind]: counted by kind, the why
            # carries each pick's own numbers
            k = str(m[4]) if len(m) > 4 else str(m[3]).split(":")[0]
            why[k] = why.get(k, 0) + 1
    rows = listed = trades = unmeasured = blocked = chased = 0
    for _coin, _tf, rs in pst.pairs_in(roots, OCT22.rows_glob):
        for r in rs:
            rows += 1
            listed += 1 if br.index_keeps(r) else 0
            trades += int(r.get("trades") or 0)
            unmeasured += int(r.get("cost_unmeasured") or 0)
            blocked += int(r.get("gate_blocked") or 0)
            chased += int(r.get("chase_skip") or 0)
    return {"picks": picks, "rows": rows, "listed": listed,
            "no_row": dict(sorted(why.items(), key=lambda kv: -kv[1])),
            "trades": trades, "cost_unmeasured": unmeasured,
            "cost_unmeasured_share": round(unmeasured / trades, 4) if trades else None,
            "gate_blocked": blocked, "chase_skip": chased}


def collect(state_name: str | None = None) -> dict:
    """Bring a finished store run home (every account) and land it."""
    from tradingagents import cq_search as cqs, db_jobs as dj, pro_search as ps

    holder = dj.disk_holder("collect_v2")
    if holder:
        raise RuntimeError(f"{holder} is running — one job at a time on the store; "
                           f"collect when it finishes")
    got = cqs.collect(state_name or cqs.STORE_STATE)
    report = ps.read_json_parts(got["roots"], "cq-store-report-*.json", "report")
    result = land(report, got["roots"], run=got["runs"])
    result["coverage"] = got["coverage"]
    result["measured"] = measured(got["roots"], report)
    result["group_index"] = start_group_index()
    m = result["measured"]
    cqs.progress(f"landed the store run in Stored strategies (group Oct 22): {m['rows']:,} rows "
                 f"of {m['picks']:,} picks, {m['listed']:,} pay 2:1 after their own fees")
    return result


def main(argv: list[str]) -> int:
    if argv and argv[0] == "plan":
        plan = plan_from_states()
        path = write_plan(plan)
        print(json.dumps({"file": str(path), "made": plan["made"], "picks": plan["picks"],
                          "pairs": plan["pairs"], "coins": len(plan["coins"]),
                          "names": len(plan["names"])}, indent=1))
        return 0
    from tradingagents import market_sweep as msw

    if msw.FINE_TF != "1m":
        from tradingagents import stores

        env = {**os.environ, **stores.V2.env_for(), "PYTHONUNBUFFERED": "1"}
        return subprocess.call([sys.executable, "-m", "tradingagents.cq_store", *argv], env=env)
    if argv and argv[0] == "collect":
        got = collect(argv[1] if len(argv) > 1 else None)
        cov = got.get("coverage") or {}
        got["coverage"] = {**cov, **{k: (cov.get(k) or [])[:50]
                                     for k in ("not_reached", "pairs_failed", "skipped")}}
        print(json.dumps(got, indent=2, ensure_ascii=False))
        return 0
    print("usage: python -m tradingagents.cq_store plan | collect [state-name]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
