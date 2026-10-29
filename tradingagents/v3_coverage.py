"""COVERAGE FIRST for Backtest v3 (Part 2b, Oct 27, 2026): how much of a run's
trading paid a typical cost instead of its own minute's order book, and what
filling the missing order books would take - the decision the operator makes
before the whole universe runs (CLAUDE.md "Every backtest LOOKS AT THE COSTS of
every minute it tests": COVERAGE FIRST, fill or say so BEFORE running).

    python -m tradingagents.v3_coverage report <name> [--speed-runs owner/repo:run,...]
    python -m tradingagents.v3_coverage report --plan FILE
    python -m tradingagents.v3_coverage backfill [<name> | --plan FILE] [--days-per-press N]
                                                 [--part unseen|older] [--force]
    python -m tradingagents.v3_coverage settle

* `report` reads a collected run's records (the pilot's): the share of the
  minutes the books cover, per coin, older and unseen days apart; of every
  combination's FILLED trades, the entries and exits settled without their own
  minute's book - an exit that paid the coin's usual gap (`cost_unmeasured`),
  an entry whose order went in with no book to check post-only against
  (`placement_unmeasured`, counted per order placed, so the filled share is a
  range when some of those orders never filled) - older and unseen apart; the
  plan's coin-days the COST STORE does not hold, read from the store itself
  for each coin and day (`store_days`: the coin-month files the costs job
  wrote, a day held when all 24 of its hours hold a reading taken when
  practice looks - the costs job's own rule, `costs_shard.held_days`), never
  from a record keyed to a plan or a run; and the measured time to fill them,
  at the speed the costs job's own runs measured (`costs_speed`:
  machine-seconds per coin-day, from each run's jobs' start and end). With
  `--plan` and no run it says the days alone.
* `backfill` presses `costs.yml` - the existing order-book replay, the same
  job, files and readers - for the coins of a run's plan copy, or of a plan
  file before any run of it exists, over the next `--days-per-press` days the
  store lacks, newest first, dealt between every account (the 60-machine
  rule). A coin-day a green press already asked for is not asked again (Gate's
  archive may lack an hour of it for good). One press at a time; `settle` ends
  it and marks this PC's cached copies of every coin-month it pressed stale, so
  the next read here fetches what the press wrote (`cost_store` keeps a month
  older than 35 days for ever). It never presses while the daily costs job has
  a run in the air or a record it cannot read (at most `STALE_S`), and the
  daily job holds off a backfill press in the air on a month it would also
  write (`daily_held_off`): two runs adding to one month file on one account
  keep only one of them.
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
# never a pid. Past STALE_S a run whose status cannot be read no longer holds the other job, and
# past AIR_MAX_S nothing does: GitHub cancels a job queued 24 hours and stops one that ran 6, so
# a run GitHub still calls queued or in progress holds until then (M8), never for ever.
STALE_S = 12 * 3600
AIR_MAX_S = 36 * 3600
# A press still being dispatched holds the door for PRESSING_S from its newest STEP (each account
# says it again before it is synced and started, M9). One account's step, from the code's own
# timeouts: `gh repo sync` <= 120 s (a timeout is a refusal), one `gh run list` <= 120 s,
# `gh workflow run` <= 120 s, then <= 45 polls of 2 s plus a list each (a list that times out
# raises and ends the press) - 360 s of calls answering just inside their timeouts plus the
# polling; 1,800 s holds that with each poll's list answering in up to 30 s (360 + 45 x 32).
PRESSING_S = 1800
# the statuses GitHub gives a run that has not finished
NOT_DONE = ("queued", "waiting", "pending", "requested", "in_progress")


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


COST_KEYS = ("trades", "typical_exits", "orders", "missed", "unchecked_orders",
             "funding_estimated", "legs", "typical_low", "typical_high")


def _walk_costs(walks) -> dict:
    """The counts of some walks (each {"rows", "counts"}): {"trades" (filled), "typical_exits"
    (cost_unmeasured: an exit that paid the coin's usual gap), "orders" (every order placed:
    trades + missed + post-only rejected), "missed" (rested and never filled), "unchecked_orders"
    (placement_unmeasured: placed with no book of that minute to check post-only against, filled
    OR missed - the engine counts it per order placed), "funding_estimated", "legs" (an entry and
    an exit per FILLED trade), "typical_low" / "typical_high" (the filled legs settled without
    their own minute's book: every typical exit, plus between max(0, unchecked - missed) and
    min(unchecked, trades) entries - a post-only rejection was always checked)}."""
    o = dict.fromkeys(COST_KEYS, 0)
    for w in walks:
        w = w or {}
        c, n = w.get("counts") or {}, len(w.get("rows") or [])
        o["trades"] += n
        o["typical_exits"] += int(c.get("cost_unmeasured", 0))
        o["missed"] += int(c.get("missed", 0))
        o["orders"] += n + int(c.get("missed", 0)) + int(c.get("post_only_reject", 0))
        o["unchecked_orders"] += int(c.get("placement_unmeasured", 0))
        o["funding_estimated"] += int(c.get("funding_estimated", 0))
    o["legs"] = 2 * o["trades"]
    o["typical_low"] = o["typical_exits"] + max(0, o["unchecked_orders"] - o["missed"])
    o["typical_high"] = o["typical_exits"] + min(o["unchecked_orders"], o["trades"])
    return o


def trade_costs(records: list[dict]) -> dict:
    """Over every combination's walks of every record, older and unseen apart:
    {part: `_walk_costs` of those walks}."""
    return {part: _walk_costs([combo.get(part) for rec in records
                               for combo in rec.get("combos", {}).values()])
            for part in ("older", "unseen")}


def share_words(o: dict | None) -> str:
    """The share of a part's filled entries and exits settled without their own minute's book,
    its denominator named: "12.0% of 80 entries and exits", "12.0%-15.0% of 80 ..." when some
    orders placed with no book never filled (which of them filled is not counted), "no trade"."""
    if not o or not o.get("legs"):
        return "no trade"
    lo, hi, n = o["typical_low"], o["typical_high"], o["legs"]
    pct = (f"{100 * lo / n:.1f}%" if lo == hi
           else f"{100 * lo / n:.1f}%-{100 * hi / n:.1f}%")
    return f"{pct} of {n:,} entries and exits"


def verdict_costs(records: list[dict], v: dict) -> dict:
    """COVERAGE FIRST beside one verdict (I3): {"older": the older days' counts over every setting
    the choice compared, "unseen": the chosen setting's unseen counts or None when none was
    chosen, "words": both shares in words}. The same counting as `trade_costs`."""
    from tradingagents import v3_families as vf

    keys = [vf.combo_key(v["family"], k, v["tf"], v["filter"]) for k in (v.get("older") or {})]
    older = _walk_costs([rec.get("combos", {}).get(k, {}).get("older")
                         for rec in records for k in keys])
    unseen = None
    if v.get("setting"):
        key = vf.combo_key(v["family"], v["setting"], v["tf"], v["filter"])
        unseen = _walk_costs([rec.get("combos", {}).get(key, {}).get("unseen")
                              for rec in records])
    words = (f"settled without their own minute's book (a typical cost paid, or a post-only "
             f"check that could not be made): older days {share_words(older)} (every setting "
             f"compared); unseen days "
             + (share_words(unseen) if unseen else "no setting chosen"))
    return {"older": older, "unseen": unseen, "words": words}


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


def _months(start_s: int, end_s: int) -> list[str]:
    """The coin-month keys ("202610") a window [start_s, end_s) touches, oldest first."""
    out, t = [], int(start_s) - int(start_s) % DAY_S
    while t < int(end_s):
        g = time.gmtime(t)
        key = f"{g.tm_year:04d}{g.tm_mon:02d}"
        if key not in out:
            out.append(key)
        t += DAY_S
    return out


def held_days_of(packed: dict | None) -> set:
    """The UTC day KEYS whose 24 hours a coin-month file all holds, counting only readings taken
    when practice looks (`book_history.READ_AT_S`): the costs job's own rule
    (.github/scripts/costs_shard.py `held_days`), so "held" here is exactly what a press would
    skip."""
    from tradingagents import book_history as bh

    if not packed or packed.get("t") is None or packed.get("at") is None:
        return set()
    hours = {int(x) - int(x) % 3600 for x, a in zip(packed["t"], packed["at"], strict=True)
             if int(a) == bh.READ_AT_S}
    days = {h - h % DAY_S for h in hours}
    return {_day(d) for d in days if all(d + 3600 * k in hours for k in range(24))}


def store_days(coins: list[str], start_s: int, end_s: int, *, load=None,
               workers: int = 8) -> dict:
    """What the COST STORE holds for each coin over [start_s, end_s) - the source of truth, read
    from its coin-month files (`cost_store.load_month`, every account merged; this PC's cache
    first): {"by_coin": {coin: {day keys held}}, "unreadable": ["COIN YYYYMM: why"] (their days
    counted missing, named), "coin_months": how many were read}. Backfilled days belong to the
    coin and the day: no plan id or run name is part of it (I4)."""
    from concurrent.futures import ThreadPoolExecutor

    if load is None:
        from tradingagents import cost_store

        def load(sym, ym):
            return cost_store.load_month(sym, ym, strict=True)

    months = _months(start_s, end_s)

    def one(job):
        sym, ym = job
        try:
            return sym, ym, load(sym, ym), ""
        except Exception as exc:                               # noqa: BLE001
            return sym, ym, None, f"{type(exc).__name__}: {str(exc)[:120]}"

    by = {c: set() for c in coins}
    unreadable = []
    jobs = [(c, ym) for c in coins for ym in months]
    with ThreadPoolExecutor(max(1, int(workers))) as ex:
        for sym, ym, packed, err in ex.map(one, jobs):
            if err:
                unreadable.append(f"{sym} {ym}: {err}")
            else:
                by[sym] |= held_days_of(packed)
    return {"by_coin": by, "unreadable": sorted(unreadable), "coin_months": len(jobs)}


def pressed_days(st: dict) -> dict:
    """{coin: {day keys}} every GREEN backfill press asked for (`presses`): a coin-day the store
    still lacks after one is a day Gate's archive cannot complete, and is never asked again."""
    out: dict = {}
    for p in st.get("presses") or []:
        for c in p.get("coins") or []:
            out.setdefault(c, set()).update(p.get("days") or [])
    return out


def gaps(plan: dict, part: str | None, by_coin: dict, listings: dict,
         skip: dict | None = None) -> dict:
    """For one range of the plan's window: {"every": its days, "days": the days at least one coin
    lacks (after its listing, and not in `skip` for it), "coins": {coin: [its missing days]},
    "coin_days", "before" (coin-days before a coin's listing, left out), "unknown" (coins with a
    missing day whose listing could not be read: every day counted)}."""
    every = missing_days(plan, [], part)
    skip = skip or {}
    per, before, unknown = {}, 0, 0
    for c in plan["coins"]:
        held = by_coin.get(c) or set()
        raw = [d for d in every if d not in held and d not in skip.get(c, ())]
        ms = listings.get(c)
        if ms is None:
            live = raw
            unknown += bool(raw)
        else:
            live = [d for d in raw if _start_of(d) + DAY_S > ms / 1000]
            before += len(raw) - len(live)
        if live:
            per[c] = live
    days = sorted({d for v in per.values() for d in v})
    return {"every": every, "days": days, "coins": per,
            "coin_days": sum(len(v) for v in per.values()), "before": before,
            "unknown": unknown}


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


def _plan_of(name: str | None, plan_path=None) -> tuple[dict, dict | None]:
    """(the plan, the run's state or None): a run's plan COPY - what its records were measured
    under - or, with no run, a plan file (default research/v3/plan.json), before any run of it."""
    from tradingagents import v3_cloud as vc, v3_universe as vu

    if name:
        state = vc.load_state(name)
        return vu.load(state["plan_copy"]), state
    return vu.load(plan_path or vu.PLAN_FILE), None


def report(name: str | None = None, *, plan_path=None, runs: list[tuple[str, int]] | None = None,
           machines: int = 60, listings: dict | None = None, load=None) -> list[str]:
    """COVERAGE FIRST's lines for the collected run `name`, or for a plan file before any run of
    it (see the module doc). The coin-days the cost store lacks - read from the store - and what
    filling them takes are said for each range apart: the unseen days (filled before the full
    run) and the older days (after it)."""
    from tradingagents import v3_research as vrs

    plan, state = _plan_of(name, plan_path)
    coins = list(plan["coins"])
    if state is not None:
        records = [r for r in vrs.load_coins(vrs.home(state["folder"]))
                   if r.get("plan_id") == plan["id"]]
        lines = [f"COVERAGE FIRST for {name}: {len(records)} coins measured under plan "
                 f"{plan['id']}"]
        cost, cover = trade_costs(records), minute_cover(records)
        for part in PARTS:
            c, m = cost[part], cover[part]
            lo, hi = c["typical_low"], c["typical_high"]
            filled = (f"{lo:,}" if lo == hi else f"between {lo:,} and {hi:,}")
            lines.append(
                f"  {part} days: the books cover {_pct(m['mean'])} of a coin's minutes on "
                f"average (the least {_pct(m['least'])}; {len(m['none'])} of {m['coins']} coins "
                f"have none; {len(m['unknown'])} unknown); {filled} of the {c['legs']:,} entries "
                f"and exits of {c['trades']:,} filled trades were settled without their own "
                f"minute's book ({share_words(c).split(' of ')[0]}): {c['typical_exits']:,} of "
                f"{c['trades']:,} exits paid a coin's usual cost (a TP exit reads no book), and "
                f"{c['unchecked_orders']:,} of the {c['orders']:,} orders placed (filled or not) "
                f"went in with no book to check post-only against"
                + ("" if lo == hi else " - which of them filled is not counted")
                + f"; funding estimated on {c['funding_estimated']:,} trades")
        lines.append("  an entry's cost check made with no recorded book is not counted by the "
                     "engine: the minutes the books cover, above, are its measure")
    else:
        lines = [f"COVERAGE FIRST for the plan {plan['id']} ({plan_path or 'research/v3/plan.json'}"
                 f", {len(coins)} coins): no run of it is collected, so no trade's cost is known "
                 "yet - the days alone"]
    listings = listings_of(coins) if listings is None else listings
    start, end = int(plan["start_ms"]) // 1000, int(plan["end_ms"]) // 1000
    store = store_days(coins, start, end, load=load)
    pressed = pressed_days(read_state())
    lines.append(f"  read from the cost store: {store['coin_months']:,} coin-months of the plan's "
                 f"{len(coins)} coins (a day is held when all 24 of its hours hold a reading taken "
                 "when practice looks - the costs job's own rule)"
                 + (f"; {len(store['unreadable'])} could not be read and their days count as "
                    f"missing: {', '.join(store['unreadable'][:5])}"
                    + (" ..." if len(store["unreadable"]) > 5 else "")
                    if store["unreadable"] else ""))
    found = []
    for part in ("unseen", "older"):
        g = gaps(plan, part, store["by_coin"], listings)
        if not g["every"]:
            lines.append(f"  {part} days: the plan's window holds none")
        elif not g["days"]:
            lines.append(f"  {part} days: the cost store holds every one of its {len(g['every'])} "
                         "days for every coin listed by then: nothing to fill")
        else:
            stuck = sum(1 for c, ds in g["coins"].items() for d in ds if d in pressed.get(c, ()))
            lines.append(
                f"  {part} days: {len(g['days'])} of {len(g['every'])} days lack a reading for at "
                f"least one of the plan's coins in the cost store ({range_words(g['days'])}): "
                f"{g['coin_days']:,} coin-days missing over the plan's {len(coins)} coins (an "
                f"upper bound: {g['before']:,} coin-days before a coin's listing are left out; "
                f"listing unknown for {g['unknown']} coins, counted whole)"
                + (f"; {stuck:,} of them a green backfill press already asked for (Gate's "
                   "archive does not complete them, so they are not asked again)" if stuck else ""))
            found.append((part, g["coin_days"] - stuck))
    gaps_ = [(p, n) for p, n in found if n > 0]
    if not gaps_:
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
    for part, n in gaps_:
        est = estimate(n, sp["s_per_coin_day"], machines)
        lines.append(f"  filling the {part} days' {n:,} coin-days: about "
                     f"{est['machine_hours']:,} machine-hours, at least {est['wall_hours']} "
                     f"hours of all {machines} machines")
    return lines


def air_of(rec: dict | None, now: float) -> str:
    """What of a press record ({at, runs: [{repo, run}], dispatching?, step_at?}) is IN THE AIR
    at `now`, in words, or "". Its runs' own status decides: up to STALE_S a status that cannot be
    read counts as going; past it only a run GitHub itself calls not finished (queued, in
    progress) still holds, and past AIR_MAX_S nothing does (M8). A press still being dispatched
    holds for PRESSING_S from its newest step (M9). The ONE judgement both the backfill and the
    daily costs job make of the other."""
    from tradingagents import forecast_v2_daily as fd

    if not rec:
        return ""
    at = float(rec.get("at") or 0)
    age = now - at
    if age > AIR_MAX_S:
        return ""
    step = max(at, float(rec.get("step_at") or 0))
    going = []
    if (rec.get("dispatching") or not rec.get("runs")) and now - step < PRESSING_S:
        going.append("a press being dispatched")
    for r in rec.get("runs") or []:
        try:
            status = fd.run_status(int(r["run"]), r["repo"]).get("status")
        except Exception:                                      # noqa: BLE001
            status = None
        if status == "completed":
            continue
        if age <= STALE_S:
            going.append(f"run {r['run']} on {r['repo']}")
        elif status in NOT_DONE:
            going.append(f"run {r['run']} on {r['repo']} (GitHub still says {status} after "
                         f"{int(age // 3600)} hours)")
    return ", ".join(going)


def _daily_record(now: float, st: dict) -> tuple[dict, str]:
    """(the daily costs job's saved state, why the backfill must wait for it). An UNREADABLE
    record may describe a run in the air - the daily side treats an unreadable backfill record the
    same way (`costs_daily._held_by_backfill`) - so it holds the backfill, at most STALE_S judged
    from the earlier of the file's stamp and when this side first found it unreadable (kept in
    `st`); after that the backfill goes and says so (M7)."""
    from tradingagents import costs_daily

    try:
        d = costs_daily.read_strict()
    except Exception as exc:                                   # noqa: BLE001
        first = float(st.setdefault("daily_unreadable_since", now))
        try:
            mtime = os.stat(costs_daily.STATE).st_mtime
        except OSError:
            mtime = None
        stamp = first if mtime is None else min(mtime, first)
        hours = STALE_S // 3600
        if now - stamp <= STALE_S:
            return {}, (f"the daily costs job's record {costs_daily.STATE} could not be read "
                        f"({type(exc).__name__}: {str(exc)[:120]}): it may describe a run in the "
                        f"air, so the backfill waits for it, at most {hours} hours")
        st["daily_ignored"] = (f"the daily costs job's record could not be read for more than "
                               f"{hours} hours ({type(exc).__name__}): pressed without it")
        return {}, ""
    st.pop("daily_unreadable_since", None)
    st.pop("daily_ignored", None)
    return d, ""


def clash(days: list[str], now: float, st: dict | None = None) -> str:
    """Why a backfill press of `days` may not go now, or "": the daily costs job has a run in
    the air (or is dispatching one), named, or its record cannot be read (`_daily_record`). The
    daily job holds off a backfill in the air in its turn (`daily_held_off`): two runs adding to
    one coin-month file keep only one run's days."""
    from tradingagents.positions_view import fmt_when

    d, why = _daily_record(now, {} if st is None else st)
    if why:
        return why
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


def backfill(name: str | None = None, *, plan_path=None, days_per_press: int = DAYS_PER_PRESS,
             now: float | None = None, force: bool = False, part: str | None = None,
             load=None, listings: dict | None = None) -> dict:
    """Press costs.yml over the next days the COST STORE lacks for a plan's coins (a run's plan
    copy, or a plan file before any run of it exists), newest first, for the coins that lack them,
    dealt between every account; one press at a time. `part` keeps a press inside one named range
    ("unseen" or "older", see `missing_days`). A coin-day a green press already asked for is never
    asked again (`pressed_days`)."""
    from tradingagents import cloud_sweep as cs, cq_search, forecast_v2_daily as fd

    now = time.time() if now is None else float(now)
    st = read_state()
    if st.get("flight"):
        raise RuntimeError("a backfill press is still in the air: python -m "
                           "tradingagents.v3_coverage settle")
    if cq_search.quiet_hours(now) and not force:
        raise RuntimeError("not pressed: between 12:45am and 5:00am the nightly jobs need every "
                           "machine")
    plan, _state = _plan_of(name, plan_path)
    coins = list(plan["coins"])
    listings = listings_of(coins) if listings is None else listings
    start, end = int(plan["start_ms"]) // 1000, int(plan["end_ms"]) // 1000
    store = store_days(coins, start, end, load=load)
    g = gaps(plan, part, store["by_coin"], listings, skip=pressed_days(st))
    days = g["days"][-int(days_per_press):]
    if not days:
        return {"started": False, "part": part,
                "why": f"the cost store holds every day of the plan's {part or 'whole'} window "
                       "for every coin listed by then (or a green press already asked for it)"}
    want = set(days)
    press = [c for c in coins if want & set(g["coins"].get(c, ()))]
    why = clash(days, now, st)
    if why:
        _write_state(st)               # when the daily record was first found unreadable is kept
        raise RuntimeError(f"not pressed: {why}")
    ready, refused = cs.usable_fleets()
    if not ready:
        raise RuntimeError("no GitHub account can run the costs job: " + "; ".join(refused))
    piles = cs.split_coins(press, len(ready))
    t0 = time.time()
    st["flight"] = {"at": now, "step_at": now, "days": days, "part": part, "plan_id": plan["id"],
                    "coins": press, "dispatching": True, "runs": [], "unrun": list(refused)}
    if st.get("daily_ignored"):
        st["flight"]["notice"] = st["daily_ignored"]
    _write_state(st)                   # BEFORE the dispatch, as every dispatcher here
    why = clash(days, now, st)         # a daily press that said it was pressing since the first look
    if why:
        st.pop("flight")
        _write_state(st)
        raise RuntimeError(f"not pressed: {why}")
    for slug, pile in zip(ready, piles, strict=False):
        st["flight"]["step_at"] = now + (time.time() - t0)     # still being dispatched (M9)
        _write_state(st)
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


def stale_months(coins: list[str], days: list[str]) -> tuple[int, list[str]]:
    """Take this PC's cached copy of every coin-month a press wrote out of `cost_store`'s cache
    (I5): a month that ended more than 35 days ago is served from the cache for ever
    (`cost_store.FINAL_AFTER_S`), so without this every PC reader - the tab's run box, a parity
    re-run, a v2 replay of those days - would keep the readings from BEFORE the press. Returns
    (copies removed, the ones that could not be, named)."""
    from tradingagents import cost_store

    months = sorted({d[:4] + d[5:7] for d in days})
    removed, failed = 0, []
    for c in coins:
        for ym in months:
            p = cost_store.CACHE / cost_store.asset(c, ym)
            for k in range(3):
                try:
                    if p.exists():
                        p.unlink()
                        removed += 1
                    break
                except OSError as exc:
                    if k == 2:
                        failed.append(f"{p.name}: {type(exc).__name__}")
                    else:
                        time.sleep(0.2)
    return removed, failed


def settle(now: float | None = None) -> dict:
    """End the press in the air: its days are named done when every share finished green, given
    back, named, when one is red, never ran or was never dispatched. A run is waited for while it
    may still be going (`air_of`'s rule: up to STALE_S whatever its status, past it while GitHub
    itself says queued or in progress, never past AIR_MAX_S). Either way every coin-month the
    press may have written is marked stale on this PC (`stale_months`)."""
    from tradingagents import forecast_v2_daily as fd

    now = time.time() if now is None else float(now)
    st = read_state()
    fl = st.get("flight")
    if not fl:
        return {"settled": False, "why": "no backfill press in the air"}
    age = now - float(fl.get("at") or now)
    step = now - max(float(fl.get("at") or now), float(fl.get("step_at") or 0))
    runs = fl.get("runs") or []
    got = []
    for r in runs:
        try:
            g = fd.run_status(int(r["run"]), r["repo"])
        except Exception as exc:                               # noqa: BLE001
            g = {"status": "unknown", "conclusion": f"unreadable: {exc}"}
        got.append((r, g))
    going = [(r, g) for r, g in got if g.get("status") != "completed"]
    if fl.get("dispatching") and not going and step <= PRESSING_S:
        return {"settled": False, "why": "still being dispatched"}
    if going and age <= STALE_S:
        return {"settled": False, "why": "still running"}
    queued = [(r, g) for r, g in going if g.get("status") in NOT_DONE]
    if queued and age <= AIR_MAX_S:
        return {"settled": False,
                "why": "still running past 12 hours: " + "; ".join(
                    f"{r['repo']} run {r['run']} is {g['status']}" for r, g in queued)}
    red = [f"{r['repo']} (run {r['run']}): never finished within "
           f"{(AIR_MAX_S if g.get('status') in NOT_DONE else STALE_S) // 3600} hours"
           for r, g in going]
    red += [f"{r['repo']} (run {r['run']}): {g.get('conclusion')}" for r, g in got
            if g.get("status") == "completed" and g.get("conclusion") != "success"]
    red += list(fl.get("unrun") or [])
    if not runs and not red:
        red = ["no run was ever started for this press"]
    removed, stuck = stale_months(fl.get("coins") or [], fl.get("days") or [])
    if red:
        st["last_error"] = "not every share finished green: " + "; ".join(red)
    else:
        st["last_error"] = ""
        st.setdefault("presses", []).append({"days": fl["days"], "part": fl.get("part"),
                                             "plan_id": fl.get("plan_id"),
                                             "coins": fl.get("coins") or [], "runs": fl["runs"]})
    if stuck:
        st["last_error"] = ((st["last_error"] + "; ") if st["last_error"] else "") + (
            "this PC's cached copies of these coin-months could not be removed, so this PC would "
            "keep reading them from before the press - remove them by hand: " + ", ".join(stuck))
    st.pop("flight")
    _write_state(st)
    return {"settled": True, "red": red, "days": fl["days"], "stale_removed": removed,
            "stale_failed": stuck}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_coverage")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("name", nargs="?", default=None)
    r.add_argument("--plan", default=None, help="a plan file, when no run of it exists yet")
    r.add_argument("--speed-runs", default="",
                   help="costs.yml runs to measure the speed on: owner/repo:run,...")
    b = sub.add_parser("backfill")
    b.add_argument("name", nargs="?", default=None)
    b.add_argument("--plan", default=None,
                   help="a plan file (default research/v3/plan.json), when no run of it exists")
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
        print("\n".join(report(a.name, plan_path=a.plan, runs=runs or None)))
    elif a.cmd == "backfill":
        print(json.dumps(backfill(a.name, plan_path=a.plan, days_per_press=a.days_per_press,
                                  force=a.force, part=a.part), indent=1))
    else:
        print(json.dumps(settle(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
