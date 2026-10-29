"""COVERAGE FIRST for Backtest v3 (Part 2b, Oct 27, 2026): how much of a run's
trading paid a typical cost instead of its own minute's order book, and what
filling the missing order books would take - the decision the operator makes
before the whole universe runs (CLAUDE.md "Every backtest LOOKS AT THE COSTS of
every minute it tests": COVERAGE FIRST, fill or say so BEFORE running).

    python -m tradingagents.v3_coverage report <name>
    python -m tradingagents.v3_coverage backfill [--days-per-press 30] [--force]
    python -m tradingagents.v3_coverage settle

* `report` reads a collected run's records (the pilot's): the share of the
  minutes the books cover, per coin, older and unseen days apart; of every
  combination's trades, the exits that paid the coin's usual cost
  (`cost_unmeasured`) and the orders placed with no book to check post-only
  against (`placement_unmeasured`), older and unseen apart; the plan's days
  the cost store holds no reading for (the daily costs job's `done_days`, and
  this module's own backfilled days); and the measured time to fill them, at
  the speed the costs job's own runs measured (`costs_speed`: machine-seconds
  per coin-day, from each run's jobs' start and end).
* `backfill` presses `costs.yml` - the existing order-book replay, the same
  job, files and readers - for the plan's coins over the next
  `--days-per-press` missing days, newest first, dealt between every account
  (the 60-machine rule). One press at a time; `settle` marks a press's days
  done only when every share finished green, as `costs_daily` does. It never
  presses while the daily costs job has a run in the air, nor in the hours it
  presses (02:00-08:59 UTC) for a month that job also writes: two runs adding
  to one month file on one account would keep only one of them.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

DAY_S = 86_400
DAYS_PER_PRESS = 30
# the daily costs job presses at 03:00 and 07:00 UTC (costs_daily.READY_HOUR_UTC, TODAY_HOUR_UTC);
# a backfill of a month it also writes keeps clear of 02:00-08:59 UTC
DAILY_HOURS_UTC = range(2, 9)


def state_path() -> Path:
    from tradingagents import v3_cloud as vc

    return vc.home() / "backfill.json"


def read_state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(st: dict) -> None:
    p = state_path()
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    tmp.replace(p)


def _day(s: float) -> str:
    """A UTC day's KEY, the form costs.yml takes ("2026-10-01") - never printed:
    a printed day goes through `fmt_when` (CLAUDE.md "Date format")."""
    g = time.gmtime(int(s))
    return f"{g.tm_year:04d}-{g.tm_mon:02d}-{g.tm_mday:02d}"


def _start_of(key: str) -> int:
    """The first second of a UTC day KEY."""
    import calendar

    y, m, d = (int(x) for x in key.split("-"))
    return calendar.timegm((y, m, d, 0, 0, 0))


def trade_costs(records: list[dict]) -> dict:
    """Over every combination's walks of every record, older and unseen apart:
    {part: {"trades", "typical_exits" (cost_unmeasured), "orders" (trades +
    missed + post-only rejected), "unchecked_orders" (placement_unmeasured),
    "funding_estimated"}}."""
    out = {p: dict.fromkeys(("trades", "typical_exits", "orders", "unchecked_orders",
                             "funding_estimated"), 0) for p in ("older", "unseen")}
    for rec in records:
        for combo in rec.get("combos", {}).values():
            for part in ("older", "unseen"):
                w = combo.get(part) or {}
                c, n = w.get("counts") or {}, len(w.get("rows") or [])
                o = out[part]
                o["trades"] += n
                o["typical_exits"] += int(c.get("cost_unmeasured", 0))
                o["orders"] += n + int(c.get("missed", 0)) + int(c.get("post_only_reject", 0))
                o["unchecked_orders"] += int(c.get("placement_unmeasured", 0))
                o["funding_estimated"] += int(c.get("funding_estimated", 0))
    return out


def minute_cover(records: list[dict]) -> dict:
    """The books' share of each coin's minutes, older and unseen apart: the
    mean over the coins, the least, and the coins with none on the older days."""
    out = {}
    for part in ("older", "unseen"):
        got = {r["coin"]: float((r.get("pre") or {}).get(f"coverage_{part}") or 0.0)
               for r in records if r.get("pre")}
        out[part] = {"mean": statistics.fmean(got.values()) if got else None,
                     "least": min(got.values()) if got else None,
                     "none": sorted(c for c, v in got.items() if v == 0.0), "coins": len(got)}
    return out


PARTS = ("older", "unseen")


def missing_days(plan: dict, done, part: str | None = None) -> list[str]:
    """The UTC days of the plan's window ([start, end)) the cost store holds no
    replayed reading for, oldest first: every day but those in `done`. `part`
    names one of the window's two ranges - "unseen" (the last UNSEEN_DAYS, from
    the split `v3_measure.windows` gives) or "older" (the days before it); None
    is both. The operator's order (Oct 28, 2026): the unseen range's gap before
    the full run, the older range afterwards."""
    from tradingagents.v3_measure import windows

    if part not in (None, *PARTS):
        raise ValueError(f"part {part!r} is not one of 'older' or 'unseen'")
    start, end = int(plan["start_ms"]) // 1000, int(plan["end_ms"]) // 1000
    if part:
        split = windows(plan)[1] // 1000
        start, end = (start, split) if part == "older" else (max(start, split), end)
    have = set(done or ())
    return [d for d in (_day(t) for t in range(start - start % DAY_S, end, DAY_S))
            if d not in have]


def done_days() -> set:
    """Every day the cost store holds for every coin: the daily costs job's
    and this module's backfilled ones."""
    from tradingagents import costs_daily

    return set(costs_daily.read().get("done_days") or []) | set(read_state().get("done_days")
                                                                 or [])


def costs_speed(runs: list[tuple[str, int]], *, gh=None) -> dict:
    """The costs job's measured speed from its own green runs [(repo, run id)]:
    machine-seconds (each job's start to end, the dealing job left out) per
    coin-day (coins x days the run's title names: "Costs per minute · <days> ·
    ... <N> coins", the daily press's label or a backfill's)."""
    import datetime as dt
    import re

    from tradingagents import forecast_v2_daily as fd

    gh = gh or fd._gh

    def ts(x):
        return dt.datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()

    secs = coin_days = used = 0
    for repo, run in runs:
        d = json.loads(gh("run", "view", str(run), "--repo", repo, "--json",
                          "displayTitle,conclusion,jobs"))
        m = re.match(r"Costs per minute · ([0-9,\-]+) · .*?(\d+) coins$",
                     d.get("displayTitle", ""))
        if d.get("conclusion") != "success" or not m:
            continue
        jobs = [j for j in d.get("jobs") or [] if j.get("name") != "plan"
                and j.get("startedAt") and j.get("completedAt")]
        secs += sum(ts(j["completedAt"]) - ts(j["startedAt"]) for j in jobs)
        coin_days += int(m.group(2)) * len(m.group(1).split(","))
        used += 1
    return {"runs": used, "machine_s": round(secs), "coin_days": coin_days,
            "s_per_coin_day": round(secs / coin_days, 1) if coin_days else None}


def estimate(coin_days: int, s_per_coin_day: float | None, machines: int) -> dict | None:
    """Machine-hours and the wall-clock hours of `machines` machines at the
    measured speed (the least it can take: the work spread perfectly)."""
    if not s_per_coin_day or machines < 1:
        return None
    hours = coin_days * s_per_coin_day / 3600
    return {"machine_hours": round(hours, 1), "wall_hours": round(hours / machines, 1),
            "machines": machines}


def report(name: str, *, runs: list[tuple[str, int]] | None = None,
           machines: int = 60) -> list[str]:
    """COVERAGE FIRST's lines for the collected run `name` (see the module doc)."""
    from tradingagents import v3_cloud as vc, v3_research as vrs, v3_universe as vu
    from tradingagents.positions_view import fmt_when

    state = vc.load_state(name)
    plan = vu.load(state["plan_copy"])
    records = [r for r in vrs.load_coins(vrs.home(state["folder"]))
               if r.get("plan_id") == plan["id"]]
    cost, cover = trade_costs(records), minute_cover(records)
    missing = missing_days(plan, done_days())
    coins = len(plan["coins"])
    lines = [f"COVERAGE FIRST for {name}: {len(records)} coins measured under plan {plan['id']}"]
    for part, words in (("older", "older days"), ("unseen", "unseen days")):
        c, m = cost[part], cover[part]
        share = c["typical_exits"] / c["trades"] if c["trades"] else None
        lines.append(
            f"  {words}: the books cover {_pct(m['mean'])} of a coin's minutes on average (the "
            f"least {_pct(m['least'])}; {len(m['none'])} of {m['coins']} coins have none); "
            f"{c['typical_exits']:,} of {c['trades']:,} trades exited at a typical cost "
            f"({_pct(share)}); {c['unchecked_orders']:,} of {c['orders']:,} orders went in "
            f"with no book to check post-only against; funding estimated on "
            f"{c['funding_estimated']:,} trades")
    if not missing:
        lines.append("  the cost store holds every day of the plan's window: nothing to fill")
        return lines
    lines.append(f"  the cost store holds no reading for {len(missing)} of the window's days "
                 f"(UTC days from {fmt_when(_start_of(missing[0]))} to "
                 f"{fmt_when(_start_of(missing[-1]) + DAY_S)}): {len(missing) * coins:,} "
                 f"coin-days for the plan's {coins} coins")
    if runs:
        sp = costs_speed(runs)
        est = estimate(len(missing) * coins, sp["s_per_coin_day"], machines)
        if est:
            lines.append(f"  the costs job measured {sp['s_per_coin_day']} machine-seconds a "
                         f"coin-day over {sp['runs']} of its runs ({sp['coin_days']:,} "
                         f"coin-days): filling them is about {est['machine_hours']:,} "
                         f"machine-hours, at least {est['wall_hours']} hours of all "
                         f"{machines} machines")
        else:
            lines.append("  no green costs run could be read to measure the speed")
    return lines


def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def clash(days: list[str], now: float) -> str:
    """Why a backfill press of `days` may not go now, or "": the daily costs
    job has a run in the air, or it is within its pressing hours and one of
    the days is in a month it writes (its last BACKFILL_DAYS)."""
    from tradingagents import costs_daily

    if costs_daily.read().get("flight"):
        return "the daily costs job has a run in the air"
    daily = {_day(now - k * DAY_S)[:7] for k in range(costs_daily.BACKFILL_DAYS + 1)}
    if time.gmtime(int(now)).tm_hour in DAILY_HOURS_UTC and any(d[:7] in daily for d in days):
        return ("between 02:00 and 08:59 UTC the daily costs job writes the months "
                + ", ".join(sorted(daily)) + ": a press of the same month file would lose one "
                                             "of the two runs' days")
    return ""


def backfill(name: str, *, days_per_press: int = DAYS_PER_PRESS, now: float | None = None,
             force: bool = False, part: str | None = None) -> dict:
    """Press costs.yml for the plan's coins over the next missing days, newest
    first, dealt between every account; one press at a time. `part` keeps a
    press inside one named range ("unseen" or "older", see `missing_days`)."""
    from tradingagents import (
        cloud_sweep as cs,
        cq_search,
        forecast_v2_daily as fd,
        v3_cloud as vc,
        v3_universe as vu,
    )

    now = time.time() if now is None else float(now)
    st = read_state()
    if st.get("flight"):
        raise RuntimeError("a backfill press is still in the air: python -m "
                           "tradingagents.v3_coverage settle")
    if cq_search.quiet_hours(now) and not force:
        raise RuntimeError("not pressed: between 12:45am and 5:00am the nightly jobs need every "
                           "machine")
    plan = vu.load(vc.load_state(name)["plan_copy"])
    days = missing_days(plan, done_days(), part)[-int(days_per_press):]
    if not days:
        return {"started": False, "part": part,
                "why": f"every day of the plan's {part or 'whole'} window is in the cost store"}
    why = clash(days, now)
    if why:
        raise RuntimeError(f"not pressed: {why}")
    ready, refused = cs.usable_fleets()
    if not ready:
        raise RuntimeError("no GitHub account can run the costs job: " + "; ".join(refused))
    piles = cs.split_coins(list(plan["coins"]), len(ready))
    st["flight"] = {"at": now, "days": days, "part": part, "runs": [], "unrun": list(refused)}
    _write_state(st)                   # BEFORE the dispatch, as every dispatcher here
    for slug, pile in zip(ready, piles, strict=False):
        drift = cs.sync_fleet(slug)
        if drift:
            st["flight"]["unrun"].append(f"{slug}: {len(pile)} coins never ran ({drift})")
            continue
        inputs = {"shards": "20", "days": ",".join(days), "coin_list": ",".join(pile),
                  "label": f"v3 backfill {slug.split('/')[0]} {len(pile)} coins"}
        try:
            st["flight"]["runs"].append({"repo": slug, "coins": len(pile),
                                         "run": int(fd.dispatch("costs.yml", inputs, slug))})
        except Exception as exc:                               # noqa: BLE001
            st["flight"]["unrun"].append(f"{slug}: {str(exc)[:160]}")
        _write_state(st)
    return {"started": bool(st["flight"]["runs"]), "days": days, **st["flight"]}


def settle() -> dict:
    """Mark the press in the air done when every share finished green; give
    its days back, named, when one is red or never ran."""
    from tradingagents import forecast_v2_daily as fd

    st = read_state()
    fl = st.get("flight")
    if not fl:
        return {"settled": False, "why": "no backfill press in the air"}
    got = [(r, fd.run_status(int(r["run"]), r["repo"])) for r in fl["runs"]]
    if any(g.get("status") != "completed" for _r, g in got):
        return {"settled": False, "why": "still running"}
    red = [f"{r['repo']} (run {r['run']}): {g.get('conclusion')}" for r, g in got
           if g.get("conclusion") != "success"] + list(fl.get("unrun") or [])
    if red:
        st["last_error"] = "not every share finished green: " + "; ".join(red)
    else:
        st["done_days"] = sorted(set(st.get("done_days") or []) | set(fl["days"]))
        st["last_error"] = ""
        st.setdefault("presses", []).append({"days": fl["days"], "part": fl.get("part"),
                                                 "runs": fl["runs"]})
    st.pop("flight")
    _write_state(st)
    return {"settled": True, "red": red, "days": fl["days"]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_coverage")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("name")
    r.add_argument("--speed-runs", default="",
                   help="costs.yml runs to measure the speed on: owner/repo:run,...")
    b = sub.add_parser("backfill")
    b.add_argument("name")
    b.add_argument("--days-per-press", type=int, default=DAYS_PER_PRESS)
    b.add_argument("--force", action="store_true")
    b.add_argument("--part", choices=PARTS, default=None,
                   help="one range of the window: unseen (before the full run) or older "
                        "(after it); default both")
    sub.add_parser("settle")
    a = p.parse_args(argv)
    if a.cmd == "report":
        runs = [(x.rsplit(":", 1)[0], int(x.rsplit(":", 1)[1]))
                for x in a.speed_runs.split(",") if x]
        print("\n".join(report(a.name, runs=runs or None)))
    elif a.cmd == "backfill":
        print(json.dumps(backfill(a.name, days_per_press=a.days_per_press, force=a.force,
                                  part=a.part), indent=1))
    else:
        print(json.dumps(settle(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
