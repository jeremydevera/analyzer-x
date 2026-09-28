"""UPDATE ALL BACKTESTS on Backtest v2, pressed by itself once a day.

Operator, `Sep 28, 2026`: *"yes i want github to start once a day / also
there are times where there is power outage when i turn on my pc, you should
detect the last run of update all backtest, if its greater than 24 hrs, you
should automatically run it"*.

ONE RULE COVERS BOTH HALVES. On every supervisor tick (30 s): if the last real
run of the v2 UPDATE is 24 hours old or more, press it. After a power cut the
API comes up, the supervisor's first tick sees the old run and presses it. So
there is no separate "on start-up" path that could drift from the daily one.

IT PRESSES THE BUTTON, IT IS NOT A SECOND BUTTON. `db_jobs.start("btupdate_v2",
...)` with the spec the Backtest v2 panel sends when nothing is picked: every
coin, the panel's default timeframes, the 30-day window, $5. It then goes to
GitHub exactly as a hand press does (`_run_btupdate_v2` -> `dispatch_across`).

THIS OVERTURNS SEP 09, 2026 FOR THIS ONE JOB, ON THE OPERATOR'S OWN WORD. That
day a tick started a 20-machine run nobody asked for (run 34285739222), and the
correction was *"no no no, i want option to start the backtest"*. Dispatching
was taken off the tick, and `cloud_autopilot` still never starts anything (its
tests are unchanged). This is a separate module with its own switch, and the
Backtest v2 screen says when it last ran, when it runs next and why it is
waiting. The operator can switch it off from there.

WHAT COUNTS AS "THE LAST RUN" is a real dispatch: `db_btupdate_v2.plan.json`
carrying a `cloud_run`, whether pressed by hand or by this. A press GitHub
refused measured nothing, so it does not reset the clock. It is retried every
`RETRY_S`, never every tick.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

STATE = Path(os.path.expanduser("~/.tradingagents")) / "daily_update.json"

EVERY_S = 24 * 3600
# Retry spacing after a try that did not start, or started and was refused.
# A busy disk or a busy GitHub is normal here, and asking GitHub every 30 s is
# what 403'd this account for hours on Sep 02, 2026.
RETRY_S = 30 * 60
# The Backtest v2 panel's own default (JobsPanel `tfs`): a hand press with
# nothing changed sends these four. A test holds the two equal.
DAILY_TFS = ("15m", "30m", "1h", "4h")
BASE = 5.0


def _read() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _write(d: dict) -> None:
    with contextlib.suppress(OSError):
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d))
        os.replace(tmp, STATE)


def enabled(state: dict | None = None) -> bool:
    """On unless the operator switched it off: they asked for it."""
    st = _read() if state is None else state
    return bool(st.get("enabled", True))


def set_enabled(on: bool) -> dict:
    st = _read()
    st["enabled"] = bool(on)
    st["why"] = ("switched on — it runs when the last run is 24 hours old"
                 if on else "switched off on the Backtest v2 screen")
    _write(st)
    return status()


def last_run(state: dict | None = None) -> float:
    """When UPDATE ALL BACKTESTS on v2 last REALLY went to GitHub, or 0.

    The plan file is the one both the button and this module write through
    (`_run_btupdate_v2` -> `_write_run_plan`). A refused press leaves it with
    no `cloud_run`, which would forget the good run before it, so the last
    good one is also kept here.
    """
    from tradingagents import db_jobs as dj

    st = _read() if state is None else state
    best = float(st.get("last_ok") or 0)
    plan = {}
    with contextlib.suppress(Exception):                       # noqa: BLE001
        plan = dj._read(dj.STATE_DIR / "db_btupdate_v2.plan.json")
    if plan.get("cloud_run") and float(plan.get("when") or 0) > best:
        best = float(plan["when"])
        st["last_ok"] = best
        st["last_ok_run"] = plan.get("cloud_run")
        st["last_ok_url"] = plan.get("cloud_url")
        _write(st)
    return best


def _github_busy() -> str:
    """The first sweep run still queued or running on ANY account, or "".

    `capacity.cloud_free` asks only the first account. Since Sep 21, 2026 a
    press goes to every account, so a run still going on the second one is
    just as busy.
    """
    from tradingagents import cloud_sweep as cs

    for slug in cs.fleets():
        for r in cs._runs(slug, limit=5):
            if r.get("status") in ("queued", "in_progress", "requested",
                                   "waiting"):
                return (f"GitHub is still running run {r.get('databaseId')} "
                        f"on {slug}")
    return ""


def spec() -> dict:
    """What a hand press of UPDATE ALL BACKTESTS sends with nothing picked."""
    from tradingagents import db_jobs as dj

    return {"coins": [], "tfs": list(DAILY_TFS), "days": dj._sweep_days(),
            "base": BASE, "label": "daily", "deployed": [], "fresh": False}


def consider(*, now: float | None = None) -> dict:
    """Look once, press if due. Returns what it did and WHY, always."""
    from tradingagents import db_jobs as dj
    from tradingagents.positions_view import fmt_when

    now = time.time() if now is None else now
    st = _read()

    def _say(why: str, started: bool = False, **more) -> dict:
        # written only when the sentence CHANGES: this runs every 30 s, and
        # the store's drive is a spinning disk shared with the collect
        if started or st.get("why") != why:
            st["why"] = why
            _write(st)
        return {"started": started, "why": why, **more}

    if not enabled(st):
        return _say("switched off on the Backtest v2 screen")
    last = last_run(st)
    if last and now - last < EVERY_S:
        return _say(f"next run {fmt_when(last + EVERY_S)} — the last one "
                    f"went to GitHub {fmt_when(last)}")
    tried = float(st.get("last_try") or 0)
    if tried and now - tried < RETRY_S:
        return {"started": False, "why": st.get("why") or "waiting to try again"}
    st["last_try"] = now
    _write(st)
    if dj.status("btupdate_v2").get("running"):
        return _say("UPDATE ALL BACKTESTS is already running")
    holder = dj.disk_holder("btupdate_v2")
    if holder:
        return _say(f"due, waiting for {holder} to finish (tries again "
                    f"{fmt_when(now + RETRY_S)})")
    try:
        busy = _github_busy()
    except Exception as exc:                                   # noqa: BLE001
        return _say(f"due, but GitHub could not be asked: "
                    f"{type(exc).__name__}: {str(exc)[:120]} (tries again "
                    f"{fmt_when(now + RETRY_S)})")
    if busy:
        return _say(f"due, waiting — {busy} (tries again "
                    f"{fmt_when(now + RETRY_S)})")
    try:
        pid = dj.start("btupdate_v2", spec())
    except Exception as exc:                                   # noqa: BLE001
        return _say(f"due, but it would not start: {type(exc).__name__}: "
                    f"{str(exc)[:160]} (tries again {fmt_when(now + RETRY_S)})")
    st["last_started"] = now
    st["last_pid"] = pid
    ago = (f"the last run was {fmt_when(last)}" if last
           else "no earlier run is on record")
    with contextlib.suppress(Exception):                       # noqa: BLE001
        from tradingagents import notifications as nt

        nt.record("backtest", "Daily UPDATE ALL BACKTESTS started", ok=True,
                  detail=f"Backtest v2, every coin, "
                         f"{', '.join(DAILY_TFS)}, last "
                         f"{spec()['days']} days — {ago}")
    return _say(f"started {fmt_when(now)} (pid {pid}) — {ago}", started=True,
                pid=pid)


def status(*, now: float | None = None) -> dict:
    """What the Backtest v2 screen prints. Every word comes from here."""
    from tradingagents import db_jobs as dj

    now = time.time() if now is None else now
    st = _read()
    last = last_run(st)
    return {"enabled": enabled(st), "last_run": last or None,
            "last_run_url": st.get("last_ok_url"),
            "next_run": (last + EVERY_S) if last else None,
            "due": bool(enabled(st) and (not last or now - last >= EVERY_S)),
            "every_hours": EVERY_S // 3600, "tfs": list(DAILY_TFS),
            "days": dj._sweep_days(), "why": st.get("why") or "",
            "last_started": st.get("last_started")}


_LAST_SAID = {"why": ""}


def tick() -> dict:
    """`consider()`, logged whenever its answer changes. NEVER under pytest:
    a test run must not be able to send forty GitHub machines to work (the
    live door's rule, `live_ingest.ensure`)."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"started": False, "why": "never under a test run"}
    got = consider()
    why = str(got.get("why") or "")
    if why and why != _LAST_SAID["why"]:
        print(f"[daily-update] {why}", flush=True)
    _LAST_SAID["why"] = why
    return got
