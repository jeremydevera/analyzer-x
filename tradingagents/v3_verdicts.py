"""THE BACKTEST V3 VERDICT STORE (Part 2b, Oct 27, 2026): a collected run's
records judged pooled, every verdict kept with what it was judged under.

    python -m tradingagents.v3_verdicts publish <name>

`<name>` is a run `python -m tradingagents.v3_cloud dispatch <name>` started
and `collect <name>` brought home. `publish` judges the records in its folder
with the proof test (`v3_research.report` -> `v3_proof.verdicts`, the PC's own
judge, pooled over every coin), under the PLAN THE RUN WAS DISPATCHED WITH
(the copy `dispatch` kept, never whatever research/v3/plan.json holds today),
and writes:

* `stores.V3.home/verdicts.json` - the verdicts the Backtest v3 tab shows
  (`v3_page.tested`), swapped whole;
* `stores.V3.home/verdicts/<name>-<seconds>.json` - the same, kept for good
  (spec Part 3: "Every verdict is kept"); nothing here deletes one.

Each verdict carries its chosen setting's stop and target sizes on the unseen
days (`levels`: the smallest, the median and the largest, as fractions of the
entry), read from the records' trade rows. The file says what it was judged
under - the run, the plan build and its window, the risk, the random runs,
the coins pooled out of the plan's, and every coin of the plan that was NOT
judged, with why - so a page that shows it never has to guess.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path


def store_path() -> Path:
    from tradingagents import stores

    return Path(stores.V3.home) / "verdicts.json"


def history_dir() -> Path:
    from tradingagents import stores

    return Path(stores.V3.home) / "verdicts"


def levels(records: list[dict], v: dict) -> dict:
    """The chosen setting's stop and target sizes over its unseen trades, as
    fractions of each entry: {"stop": [least, median, most] | None, "target":
    same | None (a trail has none), "trades": how many rows carried them}. A
    record measured before rows carried them (version 1) counts in no list."""
    from tradingagents import v3_families as vf

    if not v.get("setting"):
        return {"stop": None, "target": None, "trades": 0}
    key = vf.combo_key(v["family"], v["setting"], v["tf"], v["filter"])
    rows = [r for rec in records for r in (rec.get("combos", {}).get(key, {})
                                           .get("unseen", {}).get("rows") or [])
            if len(r) >= 8]

    def spread(xs):
        return [min(xs), statistics.median(xs), max(xs)] if xs else None

    return {"stop": spread([float(r[6]) for r in rows]),
            "target": spread([float(r[7]) for r in rows if r[7] is not None]),
            "trades": len(rows)}


def build(name: str, *, now: float | None = None) -> dict:
    """The verdict store's content for the collected run `name` (see the
    module doc). Refuses a folder with no record, and a run whose plan copy is
    missing or is not the plan the records were measured under."""
    from tradingagents import (
        v3_cloud as vc,
        v3_proof as vp,
        v3_research as vrs,
        v3_universe as vu,
    )
    from tradingagents.v3_measure import windows

    state = vc.load_state(name)
    collected = json.loads((vc.home() / f"{name}-collected.json").read_text(encoding="utf-8"))
    plan = vu.load(state["plan_copy"])
    if plan["id"] != state["plan_id"]:
        raise ValueError(f"{state['plan_copy']} is plan {plan['id']}, the run was dispatched with "
                         f"{state['plan_id']}")
    root = vrs.home(state["folder"])
    runs, risk = int(state["runs_per_combo"]), float(state["risk_usd"])
    records, other = vrs.split_records(vrs.load_coins(root), plan, runs, risk)
    if not records:
        raise ValueError(f"{root} holds no record measured under plan {plan['id']}: collect "
                         f"{name} first")
    lines, verdicts = vrs.report(records, plan, runs, risk)
    for v in verdicts:
        v["levels"] = levels(records, v)
    start, split, end = windows(plan)
    t = time.time() if now is None else float(now)
    judged = sorted(r["coin"] for r in records)
    return {"version": 1, "name": name, "folder": state["folder"], "label": state["label"],
            "venue": plan.get("venue") or "", "plan_id": plan["id"], "plan_start": start,
            "plan_split": split, "plan_end": end, "risk_usd": risk, "runs": runs,
            "tried": vp.TRIED, "z": vp.Z, "judged_at": t, "github_runs": collected["runs"],
            "coins": judged, "plan_coins": len(plan["coins"]),
            "unseen_months": next((r["unseen_months"] for r in records if r.get("unseen_months")),
                                  []),
            "not_judged": {"not_reached": collected.get("not_reached", []),
                           "failed": collected.get("failed", []),
                           "left_out": collected.get("left_out", []),
                           "refused_records": collected.get("refused_records", []),
                           "machines_refused": collected.get("machines_refused", []),
                           "other_records": [f"{c}: {'; '.join(w)}" for c, w in other],
                           # a pilot dispatches a few of the plan's coins: the rest are named
                           "not_dispatched": sorted(set(plan["coins"]) - set(state["board"]))},
            "lines": lines, "verdicts": verdicts}


def publish(name: str, *, now: float | None = None) -> Path:
    """Write the verdict store and its kept copy; the store's path."""
    data = build(name, now=now)
    text = json.dumps(data, default=str)
    hist = history_dir()
    hist.mkdir(parents=True, exist_ok=True)
    (hist / f"{name}-{int(data['judged_at'])}.json").write_text(text, encoding="utf-8")
    p = store_path()
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)
    return p


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_verdicts")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("publish", help="judge a collected run and keep its verdicts").add_argument(
        "name")
    a = p.parse_args(argv)
    path = publish(a.name)
    data = json.loads(path.read_text(encoding="utf-8"))
    print("\n".join(data["lines"]))
    print(f"kept: {path} ({sum(1 for v in data['verdicts'] if v['passed'])} of "
          f"{len(data['verdicts'])} verdicts passed; {len(data['coins'])} of the plan's "
          f"{data['plan_coins']} coins judged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
