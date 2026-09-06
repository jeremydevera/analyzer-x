"""Keep the candle store fresh, so "pending" stays near zero by itself.

Operator, 2026-09-06: *"up until now i still see 5095 pending for candles"* —
after the count had been driven to 0 at 10:55pm the night before, and then
*"then fix that bug"*.

The count was never wrong. "Behind" means a pair's newest stored candle is more
than one bar old, measured against the CLOCK, so the store goes stale on its
own: 0 at 10:55pm, 5,095 by 9:33am, a median 12.6 hours behind. Relabelling it
told the truth; it did not stop the operator from waking up to five thousand
again. The only real fix is to keep the candles current, which nothing did —
UPDATE CANDLES has always been a button somebody has to press.

This presses it. On the supervisor's tick: when the store is more than
STALE_HOURS behind and nothing else is downloading, run an update.

WHY AN UPDATE AND NOT A RESOLVE: an update fetches only the bars printed since
each pair's last stored bar, which is exactly what going stale means. RESOLVE
also attempts the 97 delisted pairs and the never-stored ones — work that
belongs to a person pressing a button, not to a loop running every hour.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# How far behind the store is allowed to get before this steps in. Below this
# an update is not worth the venue calls: the shortest timeframe is 15m, so
# under three hours the store is at most a handful of bars short and every
# backtest still reads the same candles.
STALE_HOURS = 3.0

# Never two updates inside this window. A full top-up took 12.7 minutes on
# 5,190 pairs; a tick every 30 seconds must not stack them.
COOLDOWN_S = 60 * 60

# The cheap local check runs every tick; this is only about not spamming the
# log with the same sentence.
STATE = Path.home() / ".tradingagents" / "candle_autopilot.json"

_LAST_SAID = {"why": ""}


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


def consider(*, now: float | None = None) -> dict:
    """Look once. Start an update if the store has gone stale.

    Returns what it did and WHY, always — including the no-ops. A silent
    autopilot is indistinguishable from a broken one.
    """
    from tradingagents import db_jobs as dj

    now = time.time() if now is None else now
    state = _read()

    last = float(state.get("last_started") or 0)
    if now - last < COOLDOWN_S:
        return {"started": False,
                "why": f"cooling down, {int((COOLDOWN_S - (now - last)) / 60)} "
                       f"min since the last top-up"}

    # A download of ANY mode is already fetching candles — including one the
    # operator started by hand. Never a second one: they write the same files.
    try:
        if dj.status("download").get("running"):
            return {"started": False, "why": "a download is already running"}
    except Exception as exc:                                   # noqa: BLE001
        return {"started": False, "why": f"cannot read the job: {exc}"}

    try:
        # `_pending_sources`, NOT `pending_work`: the latter also builds the
        # whole RESOLVE queue — 5,192 pairs sorted by staleness — to publish
        # its `queue` field, and this runs every 30 seconds for two numbers it
        # does not use. Measured on this store: 0.122 s a tick against 0.19 s.
        work = dj._pending_sources()
    except Exception as exc:                                   # noqa: BLE001
        return {"started": False, "why": f"cannot count the store: {exc}"}

    behind = int(work.get("behind") or 0)
    if not behind:
        return {"started": False, "why": "the store is current"}
    # `_pending_sources` is private and lives in another module that a second
    # session edits. If `behind_hours` ever goes away, `float(None or 0.0)` is
    # 0.0, which is under STALE_HOURS, which means this autopilot quietly stops
    # topping the store up FOR EVER with no error anywhere. Say it instead.
    if work.get("behind_hours") is None:
        return {"started": False, "behind": behind,
                "why": ("db_jobs._pending_sources no longer reports "
                        "behind_hours — the candle autopilot cannot tell how "
                        "stale the store is and is standing down; fix that "
                        "key rather than leaving this silent")}
    hours = float(work.get("behind_hours") or 0.0)
    if hours < STALE_HOURS:
        return {"started": False, "behind": behind, "hours": hours,
                "why": f"{behind:,} pair(s) behind but only {hours}h — under "
                       f"the {STALE_HOURS}h worth fetching for"}

    try:
        pid = dj.start("download", {"mode": "update"})
    except Exception as exc:                                   # noqa: BLE001
        # NAMED. An autopilot that fails silently looks like one that works.
        return {"started": False, "behind": behind, "hours": hours,
                "why": f"could not start the update: {type(exc).__name__}: {exc}"}

    _write({"last_started": now, "pid": pid, "behind": behind, "hours": hours})
    line = (f"[candle-autopilot] the store is {hours}h behind over {behind:,} "
            f"pair(s) — topping it up (pid {pid})")
    print(line, flush=True)
    try:
        from tradingagents import notifications as _nt

        _nt.record("download", "Candles were going stale — topping up",
                   detail=f"{hours}h behind over {behind:,} pair(s)",
                   ok=True, meta={"behind": behind, "hours": hours, "pid": pid})
    except Exception:                                          # noqa: BLE001
        pass
    return {"started": True, "pid": pid, "behind": behind, "hours": hours,
            "why": line}


def tick() -> dict:
    """`consider()`, with its answer logged whenever it CHANGES.

    Every tick would be a line every 30 seconds; only changes is one line per
    real event.
    """
    got = consider()
    why = str(got.get("why") or "")
    if why and why != _LAST_SAID["why"] and not got.get("started"):
        print(f"[candle-autopilot] {why}", flush=True)
    _LAST_SAID["why"] = why
    return got
