"""Use GitHub whenever GitHub is free.

Operator, 2026-09-05: *"I WANT TO USE GITHUB WHEN THERE IS FREE"*, after
*"SHOULD I USE GITHUB INSTEAD IF IM SHORT ON MEMORY"* and, before that,
*"why did you not use github since its free?"*.

They had to ask three times, and every time the answer was me dispatching a run
by hand. GitHub sat idle through a 4,124-pair local run that took most of a day.
Nothing ever looked, so nothing ever used it.

This looks, on the supervisor's tick. When GitHub is free and this machine has
pairs it has never measured, it dispatches — and it says out loud what it sent
and why. It never dispatches nothing, never dispatches while a run of ours is
already going, and never dispatches the same gap twice in a row.

WHY IT DISPATCHES BY TIMEFRAME: the shard takes a `timeframes` input and slices
its coins by index inside the run (`.github/scripts/sweep_shard.py`), so a
timeframe is the only unit that can be aimed at. It picks the timeframes with
the biggest holes, heaviest first, because 20 runners should get the work that
hurts.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# Don't dispatch for a handful of pairs: a run costs 20 machines spinning up,
# checking out and installing before they measure anything, and the local
# sweep clears a small tail faster than that.
MIN_MISSING = 25

# Never two dispatches inside this window, even if the count still looks big —
# a run takes minutes to appear as "in progress", and a tick every 30 s would
# otherwise fire several before the first one registers.
COOLDOWN_S = 30 * 60

# The most timeframes one run is given. All five at once measures the whole
# market on every frame; the point is to fill holes.
MAX_TFS = 2

# How often GitHub itself may be asked whether it is free. The supervisor ticks
# every 30 s; asking that often is 2 API calls a minute against the endpoints
# whose SECONDARY rate limit 403'd this account for hours on Sep 02, 2026.
CHECK_EVERY_S = 5 * 60

STATE = Path.home() / ".tradingagents" / "cloud_autopilot.json"


def _read() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _write(d: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d))
    except OSError:
        pass


def missing_by_timeframe() -> dict:
    """Pairs this machine holds candles for but has never measured, per frame.

    Two directory listings, names only — never `candle_coverage()`, which opens
    every candle file and takes minutes on a 5,000-pair store. This runs every
    supervisor tick.
    """
    from tradingagents import market_sweep as msw

    measured = {p.stem for p in msw.STATES.glob("*.json")}
    out: dict = {}
    for p in msw.CANDLES.glob("*.json"):
        try:
            sym, tf = p.stem.rsplit("-", 1)
        except ValueError:
            continue
        if f"{sym.replace('_USDT', '')}-{tf}" not in measured:
            out[tf] = out.get(tf, 0) + 1
    return out


def pick(missing: dict, *, busy_local=(), limit: int = MAX_TFS, skip=()) -> list:
    """Which timeframes to send, biggest hole first.

    A frame the LOCAL job is already working is taken last, not excluded: it is
    not wrong to measure it (the merge refuses to overwrite a locally-measured
    pair), but it is the least useful thing a free fleet could be doing.

    `skip` is the frames a previous dispatch did not improve — pairs no fleet
    can measure, because they have too few bars for their timeframe. Sending
    them again is 20 machines doing nothing, every 30 minutes, for ever.
    """
    from tradingagents import capacity as cap

    rows = [(n, t) for t, n in missing.items()
            if n >= 1 and t not in set(skip or ())]
    if not rows:
        return []
    busy = set(busy_local or ())
    rows.sort(key=lambda r: (r[1] in busy,          # local's frames last
                             -r[0],                  # biggest hole first
                             -cap.BARS_PER_YEAR.get(r[1], 1)))
    return [t for _n, t in rows[:limit]]


def consider(*, now: float | None = None) -> dict:
    """Look once. Dispatch if GitHub is free and there is a real hole.

    Returns what it did and WHY, always — a silent no-op is indistinguishable
    from a broken autopilot, which is the whole reason this exists.
    """
    from tradingagents import capacity as cap, cloud_sweep as cs, db_jobs as dj

    now = time.time() if now is None else now
    state = _read()
    last = float(state.get("last_dispatch") or 0)
    if now - last < COOLDOWN_S:
        return {"dispatched": False,
                "why": f"cooling down, {int((COOLDOWN_S - (now - last)) / 60)} "
                       f"min left since the last dispatch"}

    # CHEAP CHECKS FIRST. `cloud_free()` costs a GitHub Actions API call, and
    # this runs on a 30-second tick: asking every tick is 2 calls a minute
    # against the endpoints whose SECONDARY limit 403'd this account for hours
    # on Sep 02, 2026 and blinded the Cloud panel over a healthy run. The
    # directory listing below is local and answers in 0.1 s.
    missing = missing_by_timeframe()
    total = sum(missing.values())
    if total < MIN_MISSING:
        return {"dispatched": False, "missing": missing,
                "why": f"only {total} pair(s) unmeasured, under the "
                       f"{MIN_MISSING} it is worth 20 machines for"}

    # A FRAME THAT DID NOT IMPROVE IS NOT SENT AGAIN. Some pairs can never get
    # a state file — too few bars for their timeframe (backtest_report
    # .MIN_BARS) — so their gap never reaches zero. Without this the autopilot
    # would send 20 machines at the same dead work every 30 minutes for ever.
    #
    # It skips only THOSE FRAMES, and does not block the autopilot: a gap that
    # GREW (new candles downloaded) is real new work, and an earlier version
    # blocked on it too, because "did not shrink" also matches "got bigger".
    seen = state.get("missing") or {}
    stuck = [t for t in (state.get("timeframes") or [])
             if seen.get(t) is not None and missing.get(t, 0) >= seen[t]]

    if now - float(state.get("last_check") or 0) < CHECK_EVERY_S:
        return {"dispatched": False, "missing": missing,
                "why": "waiting before asking GitHub again"}
    state["last_check"] = now
    _write(state)

    free, why = cap.cloud_free()
    if not free:
        return {"dispatched": False, "missing": missing,
                "why": f"GitHub is not free: {why}"}

    busy_local = []
    try:
        st = dj.status("backtest")
        if st.get("running"):
            busy_local = list(dj._read(dj.FILES["backtest"]["spec"])
                              .get("tfs") or [])
    except Exception:                                          # noqa: BLE001
        pass

    tfs = pick(missing, busy_local=busy_local, skip=stuck)
    if not tfs:
        return {"dispatched": False, "missing": missing, "stuck": stuck,
                "why": (f"nothing left to aim at — {', '.join(stuck)} did not "
                        f"improve after run {state.get('run')}, so those pairs "
                        f"are ones no fleet can measure (too few bars for "
                        f"their timeframe)" if stuck else "nothing to aim at")}

    try:
        run = cs.dispatch(shards=cap.CLOUD_RUNNERS, coins=0,
                          timeframes=",".join(tfs), min_days=0, days=365)
    except Exception as exc:                                   # noqa: BLE001
        # NAMED, not swallowed. A dispatch that always fails silently is an
        # autopilot that looks like it is working.
        return {"dispatched": False, "missing": missing,
                "why": f"dispatch refused: {type(exc).__name__}: {exc}"}

    _write({"last_dispatch": now, "last_check": now, "run": run.get("id"),
            "timeframes": tfs, "missing": missing})
    covered = sum(missing.get(t, 0) for t in tfs)
    line = (f"[cloud-autopilot] GitHub was free — sent {', '.join(tfs)} "
            f"({covered} unmeasured pair(s) of {total}) to run "
            f"{run.get('id')}: {run.get('url')}")
    print(line, flush=True)
    try:
        from tradingagents import notifications as _nt

        _nt.record("backtest", "GitHub picked up the slack",
                   detail=(f"{', '.join(tfs)} — {covered} unmeasured pair(s) "
                           f"of {total} — run {run.get('id')}"),
                   ok=True, meta={"run": run.get("id"), "timeframes": tfs})
    except Exception:                                          # noqa: BLE001
        pass
    return {"dispatched": True, "run": run.get("id"), "timeframes": tfs,
            "missing": missing, "covered": covered, "why": line}
