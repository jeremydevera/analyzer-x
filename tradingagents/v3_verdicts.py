"""THE BACKTEST V3 VERDICT STORE (Part 2b, Oct 27, 2026): a collected run's
records judged pooled, every verdict kept with what it was judged under.

    python -m tradingagents.v3_verdicts publish <name>

`<name>` is a run `python -m tradingagents.v3_cloud dispatch <name>` started
and `collect <name>` brought home - with every redo `retry` made of it
(`<name>-redoN`, landed into the same folder: ONE run family; a redo's own name
is refused, pointing at the family's). `publish` judges the records in its folder
with the proof test (`v3_research.report` -> `v3_proof.verdicts`, the PC's own
judge, pooled over every coin), under the PLAN THE RUN WAS DISPATCHED WITH
(the copy `dispatch` kept, never whatever research/v3/plan.json holds today),
and writes:

* `stores.V3.home/verdicts.json` - the verdicts the Backtest v3 tab shows
  (`v3_page.tested`), swapped whole;
* `stores.V3.home/verdicts/<name>-<milliseconds>.json` - the same, kept for good
  (spec Part 3: "Every verdict is kept"); nothing here deletes one.

Each verdict carries its chosen setting's stop and target sizes on the unseen
days (`levels`: the smallest, the median and the largest, as fractions of the
entry), read from the records' trade rows. The file says what it was judged
under - the run, the plan build and its window, the risk, the random runs,
the coins pooled out of the plan's, and every coin of the plan that was NOT
judged, with why - so a page that shows it never has to guess.

What was not judged is recomputed from the records actually LANDED, against the
plan: every coin of the plan with no measured timeframe is named ONCE, in the
one bucket that is true (`BUCKETS`: failed, unmeasured, left out, not reached,
a refused record, an account whose download failed or whose share was refused,
a record of another plan or risk, a coin with no measured timeframe, a coin
the run was never sent), read from the newest collected summary of the family
that holds it - so a coin a redo landed is never "failed". The accounts that
failed are named beside, as `accounts`.
"""
from __future__ import annotations

import argparse
import json
import re
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


_REDO = re.compile(r"^(?P<base>.+)-redo(?P<n>\d+)$")

# the buckets a coin of the plan that was not judged falls in - each coin in exactly one
BUCKETS = ("not_reached", "failed", "unmeasured", "left_out", "refused_records",
           "downloads_failed", "shares_refused", "other_records", "no_walk", "not_dispatched")


def family(name: str) -> list[str]:
    """The run `name` and every redo `retry` made of it (`<name>-redo1`, ...): ONE
    run family, because a redo lands its coins into the same folder. A redo's
    own name is refused, pointing at the family's."""
    from tradingagents import v3_cloud as vc

    m = _REDO.match(name)
    if m:
        raise ValueError(f"{name} is a redo of {m['base']}: publish {m['base']}, which judges the "
                         f"run and every redo landed into its folder")
    names, n = [name], 1
    while vc._state_path(f"{name}-redo{n}").exists():
        names.append(f"{name}-redo{n}")
        n += 1
    return names


def _member(vc, name: str) -> tuple[dict, dict, Path]:
    """(a run's state, its collected summary, its plan copy's path), each refused by name when
    it is not there."""
    sp = vc._state_path(name)
    if not sp.exists():
        raise ValueError(f"no run named {name}: python -m tradingagents.v3_cloud dispatch {name}")
    state = json.loads(sp.read_text(encoding="utf-8"))
    done = vc.home() / f"{name}-collected.json"
    if not done.exists():
        raise ValueError(f"{name} is not collected yet: python -m tradingagents.v3_cloud "
                         f"collect {name}")
    copy = Path(state.get("plan_copy") or "")
    if not state.get("plan_copy") or not copy.exists():
        raise ValueError(f"the plan copy of {name} is missing ({state.get('plan_copy')}): it "
                         "cannot be judged under the plan it was dispatched with")
    return state, json.loads(done.read_text(encoding="utf-8")), copy


def _reasons(members: list) -> tuple[dict, set, dict]:
    """(each plan coin's newest reason it was not landed: {coin: (bucket, why)}, every coin any
    member's board held, the account-level lists). A member later in the family overrides an
    earlier one: a coin a redo landed is no longer failed."""
    reasons, boards = {}, set()
    accounts = {"downloads_failed": [], "shares_refused": [], "machines_refused": [],
                "unreadable_records": []}
    for name, st, su in members:
        board = set(st.get("board") or [])
        boards |= board
        prefix = "" if name == members[0][0] else f"{name}: "
        owner = {c: repo for repo, d in (st.get("dealt") or {}).items()
                 for c in (d.get("coin_list") or "").split(",") if c}
        dl = {x.split(" run ", 1)[0]: x for x in su.get("downloads_failed") or []}
        sr = {x.split(": ", 1)[0]: x for x in su.get("shares_refused") or []}
        named = {}
        for key in ("failed", "unmeasured", "left_out", "refused_records"):
            for line in su.get(key) or []:
                coin, _, why = line.partition(": ")
                if coin in board:
                    named.setdefault(coin, (key, why))
                elif key == "refused_records":
                    accounts["unreadable_records"].append(prefix + line)
        landed = set(su.get("landed") or [])
        for coin in sorted(board):
            if coin in landed:
                reasons.pop(coin, None)
            elif coin in named:
                reasons[coin] = named[coin]
            elif owner.get(coin) in dl:
                reasons[coin] = ("downloads_failed", dl[owner[coin]])
            elif owner.get(coin) in sr:
                reasons[coin] = ("shares_refused", sr[owner[coin]])
            else:
                reasons[coin] = ("not_reached", "no machine reported it")
        for key in ("downloads_failed", "shares_refused", "machines_refused"):
            accounts[key] += [prefix + x for x in su.get(key) or []]
    return reasons, boards, accounts


def build(name: str, *, now: float | None = None) -> dict:
    """The verdict store's content for the collected run `name` and every redo of
    it (see the module doc). Refuses a redo's name, a run or redo not collected
    yet, a plan copy that is missing or is not the plan the run was dispatched
    with, and a folder with no record under that plan. What was not judged is
    recomputed from the records actually landed, against the plan."""
    from tradingagents import (
        v3_cloud as vc,
        v3_proof as vp,
        v3_research as vrs,
        v3_universe as vu,
    )
    from tradingagents.v3_measure import windows

    names = family(name)
    members = []
    for m in names:
        state, summary, copy = _member(vc, m)
        members.append((m, state, summary))
        plan_m = vu.load(copy)
        if plan_m["id"] != state["plan_id"]:
            raise ValueError(f"{copy} is plan {plan_m['id']}, the run was dispatched with "
                             f"{state['plan_id']}")
        if state["plan_id"] != members[0][1]["plan_id"]:
            raise ValueError(f"{m} was dispatched with plan {state['plan_id']}, not {name}'s "
                             f"{members[0][1]['plan_id']}: one family is judged under one plan")
    state = members[0][1]
    plan = vu.load(state["plan_copy"])
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
    # judged = a coin with at least one measured timeframe; every other coin of the plan is named
    # once, in the one bucket that is true, from what is LANDED
    measured = sorted(r["coin"] for r in records if not r.get("why") and r.get("windows"))
    idle = {r["coin"]: r.get("why") or "no timeframe was measured" for r in records
            if r["coin"] not in measured}
    other_why = {c: "; ".join(w) for c, w in other}
    reasons, boards, accounts = _reasons(members)
    not_judged = {k: [] for k in BUCKETS}
    for coin in sorted(set(plan["coins"]) - set(measured)):
        if coin in other_why:
            key, why = "other_records", other_why[coin]
        elif coin in idle:
            key, why = "no_walk", idle[coin]
        elif coin in reasons:
            key, why = reasons[coin]
        elif coin not in boards:
            key, why = "not_dispatched", "this run was not sent the coin"
        else:
            key, why = "not_reached", "no record in the folder and no reason recorded"
        not_judged[key].append(f"{coin}: {why}" if key != "not_dispatched" else coin)
    github_runs = {}
    for m, _st, su in members:
        for repo, run in (su.get("runs") or {}).items():
            github_runs[repo if m == name else f"{repo} ({m})"] = run
    return {"version": 2, "name": name, "family": names, "folder": state["folder"],
            "label": state["label"], "venue": plan.get("venue") or "", "plan_id": plan["id"],
            "plan_start": start, "plan_split": split, "plan_end": end, "risk_usd": risk,
            "runs": runs, "tried": vp.TRIED, "z": vp.Z, "judged_at": t,
            "github_runs": github_runs, "coins": measured, "plan_coins": len(plan["coins"]),
            "dispatched": len(state["board"]),
            "unseen_months": next((r["unseen_months"] for r in records if r.get("unseen_months")),
                                  []),
            "not_judged": not_judged, "accounts": accounts, "lines": lines, "verdicts": verdicts}


def publish(name: str, *, now: float | None = None) -> Path:
    """Write the verdict store and its kept copy (never over another: a name taken
    gets a counter); the store's path."""
    data = build(name, now=now)
    text = json.dumps(data, default=str)
    hist = history_dir()
    hist.mkdir(parents=True, exist_ok=True)
    stamp, k = int(data["judged_at"] * 1000), 0
    while True:
        kept = hist / (f"{name}-{stamp}.json" if not k else f"{name}-{stamp}-{k}.json")
        try:
            with open(kept, "x", encoding="utf-8") as fh:
                fh.write(text)
            break
        except FileExistsError:
            k += 1
    p = store_path()
    tmp = p.with_name(p.name + ".tmp")
    p.parent.mkdir(parents=True, exist_ok=True)
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
