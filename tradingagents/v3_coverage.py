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
import os
import statistics
import time
from pathlib import Path

DAY_S = 86_400
DAYS_PER_PRESS = 30
# A press (this module's or the daily costs job's) is judged IN THE AIR by its runs' own status,
# never a pid; an entry this old is expired so a run that never finishes cannot hold the other
# job for ever. A press that has only said it is dispatching holds the door for PRESSING_S.
STALE_S = 12 * 3600
PRESSING_S = 600


def state_path() -> Path:
    from tradingagents import v3_cloud as vc

    return vc.home() / "backfill.json"


def read_state() -> dict:
    """The saved state; no file is `{}`. A file that cannot be read is REFUSED by name, never
    read as empty: an empty state forgets the press in the air and every day done, and a second
    press would go out beside the first."""
    p = state_path()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise RuntimeError(f"{p} is not readable: {exc}") from exc
    try:
        st = json.loads(text)
    except ValueError as exc:
        raise RuntimeError(f"{p} is not readable ({exc}): fix or remove it") from exc
    if not isinstance(st, dict):
        raise RuntimeError(f"{p} is not an object: fix or remove it")
    return st


def record_mtime() -> float | None:
    """When the saved state was last written, or None when there is no file to stat."""
    try:
        return os.stat(state_path()).st_mtime
    except OSError:
        return None


def _write_state(st: dict) -> None:
    p = state_path()
    # a name of its own to every write: a settle and a backfill never share one temp file
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{time.time_ns()}.tmp")
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
    "funding_estimated", "legs" (every entry = order placed, and every exit),
    "typical_legs" (an entry that went in with no book to check, and an exit that
    paid the coin's usual gap)}}."""
    out = {p: dict.fromkeys(("trades", "typical_exits", "orders", "unchecked_orders",
                             "funding_estimated", "legs", "typical_legs"), 0)
           for p in ("older", "unseen")}
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
    for o in out.values():
        o["legs"] = o["orders"] + o["trades"]
        o["typical_legs"] = o["unchecked_orders"] + o["typical_exits"]
    return out


def minute_cover(records: list[dict]) -> dict:
    """The books' share of each coin's minutes, older and unseen apart: the mean over the coins
    with a reading, the least, the coins with NONE on the days (a measured 0.0) and the coins
    with no figure at all (`unknown`: not measured is not "no books")."""
    out = {}
    for part in ("older", "unseen"):
        got, unknown = {}, []
        for r in records:
            v = (r.get("pre") or {}).get(f"coverage_{part}")
            if v is None:
                unknown.append(r["coin"])
            else:
                got[r["coin"]] = float(v)
        out[part] = {"mean": statistics.fmean(got.values()) if got else None,
                     "least": min(got.values()) if got else None,
                     "none": sorted(c for c, v in got.items() if v == 0.0),
                     "unknown": sorted(unknown), "coins": len(got)}
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


def done_days(plan: dict) -> set:
    """Every day the cost store holds for this plan's coins: the daily costs job's (every coin
    Gate trades) and this module's own backfilled days - kept per plan id and only while the
    press covered every coin of the plan, never one global list."""
    from tradingagents import costs_daily

    rec = (read_state().get("done") or {}).get(plan["id"]) or {}
    mine = set(rec.get("days") or []) if set(plan["coins"]) <= set(rec.get("coins") or [])         else set()
    return set(costs_daily.read().get("done_days") or []) | mine


def costs_speed(runs: list[tuple[str, int]], *, gh=None) -> dict:
    """The costs job's measured speed from its own green runs [(repo, run id)]:
    machine-seconds (each job's start to end, the dealing job left out) per
    coin-day (coins x days the run's title names: "Costs per minute · <days> ·
    ... <N> coins", the daily press's label or a backfill's). ONLY runs of two
    days or more measure it: a one-day run's seconds are mostly each machine's
    setup, which a press of thirty days pays once, so mixing the two would
    overstate the time (`one_day_runs` counts the ones left out)."""
    import datetime as dt
    import re

    from tradingagents import forecast_v2_daily as fd

    gh = gh or fd._gh

    def ts(x):
        return dt.datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()

    secs = coin_days = used = one_day = 0
    for repo, run in runs:
        d = json.loads(gh("run", "view", str(run), "--repo", repo, "--json",
                          "displayTitle,conclusion,jobs"))
        m = re.match(r"Costs per minute · ([0-9,\-]+) · .*?(\d+) coins$",
                     d.get("displayTitle", ""))
        if d.get("conclusion") != "success" or not m:
            continue
        days = len(m.group(1).split(","))
        if days < 2:
            one_day += 1
            continue
        jobs = [j for j in d.get("jobs") or [] if j.get("name") != "plan"
                and j.get("startedAt") and j.get("completedAt")]
        secs += sum(ts(j["completedAt"]) - ts(j["startedAt"]) for j in jobs)
        coin_days += int(m.group(2)) * days
        used += 1
    return {"runs": used, "machine_s": round(secs), "coin_days": coin_days,
            "s_per_coin_day": round(secs / coin_days, 1) if coin_days else None,
            "one_day_runs": one_day}


def estimate(coin_days: int, s_per_coin_day: float | None, machines: int) -> dict | None:
    """Machine-hours and the wall-clock hours of `machines` machines at the
    measured speed (the least it can take: the work spread perfectly)."""
    if not s_per_coin_day or machines < 1:
        return None
    hours = coin_days * s_per_coin_day / 3600
    return {"machine_hours": round(hours, 1), "wall_hours": round(hours / machines, 1),
            "machines": machines}


def listings_of(coins: list[str], *, fx=None) -> dict:
    """{coin: the exchange's listing time in ms, or None when it cannot be read}: the
    contract's own create time. A coin's days before it are not missing books."""
    if fx is None:
        import tradingagents.dataflows.exchange as fx
    out = {}
    for c in coins:
        try:
            ms = int(fx.contract_spec(c).get("createTime") or 0)
        except Exception:                                      # noqa: BLE001
            ms = 0
        out[c] = ms or None
    return out


def coin_days(days: list[str], coins: list[str], listings: dict) -> tuple[int, int, int]:
    """(coin-days to fill, coin-days left out because they fall before the coin's listing,
    coins whose listing is unknown and so count every day): an UPPER bound."""
    starts = [_start_of(d) for d in days]
    total = before = unknown = 0
    for c in coins:
        ms = listings.get(c)
        if ms is None:
            unknown += 1
            total += len(days)
            continue
        live = sum(1 for s0 in starts if s0 + DAY_S > ms / 1000)
        total += live
        before += len(days) - live
    return total, before, unknown


def range_words(days: list[str]) -> str:
    """The days in words, the clock named: a day KEY is a UTC day, `fmt_when` prints this PC's
    local clock. Days that are not one unbroken stretch are said as a count and the number of
    stretches, never as a range from the first to the last."""
    from tradingagents.positions_view import fmt_when

    starts = [_start_of(d) for d in days]
    stretches = 1 + sum(1 for a, b in zip(starts, starts[1:], strict=False) if b - a != DAY_S)
    first, last = fmt_when(starts[0]), fmt_when(starts[-1] + DAY_S)
    if stretches == 1:
        return f"UTC days from {first} to {last}, printed in this PC's clock"
    return (f"{len(days)} UTC days in {stretches} separate stretches, not one range; the first "
            f"starts {first}, the last ends {last}, printed in this PC's clock")


def _pct(x) -> str:
    return "unknown" if x is None else f"{100 * x:.1f}%"


def report(name: str, *, runs: list[tuple[str, int]] | None = None, machines: int = 60,
           listings: dict | None = None) -> list[str]:
    """COVERAGE FIRST's lines for the collected run `name` (see the module doc). The days the
    cost store lacks and what filling them takes are said for each range apart - the unseen
    days (filled before the full run) and the older days (after it)."""
    from tradingagents import v3_cloud as vc, v3_research as vrs, v3_universe as vu

    state = vc.load_state(name)
    plan = vu.load(state["plan_copy"])
    records = [r for r in vrs.load_coins(vrs.home(state["folder"]))
               if r.get("plan_id") == plan["id"]]
    cost, cover = trade_costs(records), minute_cover(records)
    held = done_days(plan)
    coins = list(plan["coins"])
    listings = listings_of(coins) if listings is None else listings
    lines = [f"COVERAGE FIRST for {name}: {len(records)} coins measured under plan {plan['id']}"]
    for part in PARTS:
        c, m = cost[part], cover[part]
        share = c["typical_legs"] / c["legs"] if c["legs"] else None
        lines.append(
            f"  {part} days: the books cover {_pct(m['mean'])} of a coin's minutes on average "
            f"(the least {_pct(m['least'])}; {len(m['none'])} of {m['coins']} coins have none; "
            f"{len(m['unknown'])} unknown); {c['typical_legs']:,} of {c['legs']:,} entries and "
            f"exits paid a typical cost ({_pct(share)}): {c['unchecked_orders']:,} of "
            f"{c['orders']:,} entries went in with no book to check post-only against, "
            f"{c['typical_exits']:,} of {c['trades']:,} exits at a coin's usual cost (a TP exit "
            f"reads no book); funding estimated on {c['funding_estimated']:,} trades")
    lines.append("  an entry's cost check made with no recorded book is not counted by the "
                 "engine: the minutes the books cover, above, are its measure")
    gaps = []
    for part in ("unseen", "older"):
        every = missing_days(plan, [], part)
        miss = missing_days(plan, held, part)
        if not every:
            lines.append(f"  {part} days: the plan's window holds none")
        elif not miss:
            lines.append(f"  {part} days: every one of its {len(every)} days is in the cost "
                         "store: nothing to fill")
        else:
            n, before, unknown = coin_days(miss, coins, listings)
            lines.append(
                f"  {part} days: the cost store holds no reading for {len(miss)} of "
                f"{len(every)} days ({range_words(miss)}): {n:,} coin-days for the plan's "
                f"{len(coins)} coins (an upper bound: {before:,} coin-days before a coin's "
                f"listing are left out; listing unknown for {unknown} coins, counted whole)")
            gaps.append((part, n))
    if not gaps:
        return lines
    if not runs:
        lines.append("  no costs runs were given to measure the speed (--speed-runs "
                     "owner/repo:run,...): the time to fill is unknown")
        return lines
    sp = costs_speed(runs)
    if not sp["s_per_coin_day"]:
        lines.append(f"  no green costs run of two days or more could be read to measure the "
                     f"speed ({sp['one_day_runs']} one-day runs left out, their per-machine "
                     "setup would overstate it): the time to fill is unknown")
        return lines
    lines.append(f"  the costs job measured {sp['s_per_coin_day']} machine-seconds a coin-day "
                 f"over {sp['runs']} of its runs of two days or more ({sp['coin_days']:,} "
                 "coin-days)")
    for part, n in gaps:
        est = estimate(n, sp["s_per_coin_day"], machines)
        lines.append(f"  filling the {part} days' {n:,} coin-days: about "
                     f"{est['machine_hours']:,} machine-hours, at least {est['wall_hours']} "
                     f"hours of all {machines} machines")
    return lines


def air_of(rec: dict | None, now: float) -> str:
    """What of a press record ({at, runs: [{repo, run}], dispatching?}) is IN THE AIR at `now`,
    in words, or "": its runs' own status decides (a status that cannot be read counts as
    going), a press still being dispatched holds for PRESSING_S, and one older than STALE_S is
    expired. The ONE judgement both the backfill and the daily costs job make of the other."""
    from tradingagents import forecast_v2_daily as fd

    if not rec:
        return ""
    at = float(rec.get("at") or 0)
    if now - at > STALE_S:
        return ""
    going = []
    if (rec.get("dispatching") or not rec.get("runs")) and now - at < PRESSING_S:
        going.append("a press being dispatched")
    for r in rec.get("runs") or []:
        try:
            status = fd.run_status(int(r["run"]), r["repo"]).get("status")
        except Exception:                                      # noqa: BLE001
            status = None
        if status != "completed":
            going.append(f"run {r['run']} on {r['repo']}")
    return ", ".join(going)


def clash(days: list[str], now: float) -> str:
    """Why a backfill press of `days` may not go now, or "": the daily costs job has a run in
    the air (or is dispatching one), named. The daily job holds off a backfill in the air in its
    turn (`daily_held_off`): two runs adding to one coin-month file keep only one run's days."""
    from tradingagents import costs_daily
    from tradingagents.positions_view import fmt_when

    d = costs_daily.read()
    for key in ("flight", "pressing"):
        what = air_of(d.get(key), now)
        if what:
            return (f"the daily costs job is busy with {what} (pressed "
                    f"{fmt_when(float(d[key].get('at') or 0))})")
    return ""


def daily_held_off(days: list[str], now: float) -> str:
    """Why the daily costs press of `days` must wait, or "": a backfill press is in the air on a
    month it would also write. Read by `costs_daily.tick`."""
    fl = read_state().get("flight")
    what = air_of(fl, now)
    if not what:
        return ""
    months = sorted({d[:7] for d in days} & {d[:7] for d in fl.get("days") or []})
    if not months:
        return ""
    return (f"a v3 backfill press is in the air ({what}) on the month file(s) "
            f"{', '.join(months)} this press would also write: two runs adding to one month "
            "file keep only one run's days, so the daily press waits")


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
    days = missing_days(plan, done_days(plan), part)[-int(days_per_press):]
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
    st["flight"] = {"at": now, "days": days, "part": part, "plan_id": plan["id"],
                    "coins": list(plan["coins"]), "dispatching": True, "runs": [],
                    "unrun": list(refused)}
    _write_state(st)                   # BEFORE the dispatch, as every dispatcher here
    why = clash(days, now)             # a daily press that said it was pressing since the first look
    if why:
        st.pop("flight")
        _write_state(st)
        raise RuntimeError(f"not pressed: {why}")
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
    st["flight"]["dispatching"] = False
    _write_state(st)
    return {"started": bool(st["flight"]["runs"]), "days": days, **st["flight"]}


def settle(now: float | None = None) -> dict:
    """Mark the press in the air done when every share finished green; give
    its days back, named, when one is red, never ran, never finished within
    STALE_S or was never dispatched. A status that cannot be read keeps the
    press (it is still running until it is old)."""
    from tradingagents import forecast_v2_daily as fd

    now = time.time() if now is None else float(now)
    st = read_state()
    fl = st.get("flight")
    if not fl:
        return {"settled": False, "why": "no backfill press in the air"}
    age = now - float(fl.get("at") or now)
    runs = fl.get("runs") or []
    got = []
    for r in runs:
        try:
            g = fd.run_status(int(r["run"]), r["repo"])
        except Exception as exc:                               # noqa: BLE001
            g = {"status": "unknown", "conclusion": f"unreadable: {exc}"}
        got.append((r, g))
    going = [(r, g) for r, g in got if g.get("status") != "completed"]
    if (going or fl.get("dispatching")) and age <= (STALE_S if going else PRESSING_S):
        return {"settled": False, "why": "still running"}
    red = [f"{r['repo']} (run {r['run']}): never finished within {STALE_S // 3600} hours"
           for r, _g in going]
    red += [f"{r['repo']} (run {r['run']}): {g.get('conclusion')}" for r, g in got
            if g.get("status") == "completed" and g.get("conclusion") != "success"]
    red += list(fl.get("unrun") or [])
    if not runs and not red:
        red = ["no run was ever started for this press"]
    if red:
        st["last_error"] = "not every share finished green: " + "; ".join(red)
    else:
        done = st.setdefault("done", {}).setdefault(fl["plan_id"], {"coins": fl["coins"],
                                                                   "days": []})
        done["coins"] = fl["coins"]
        done["days"] = sorted(set(done["days"]) | set(fl["days"]))
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
