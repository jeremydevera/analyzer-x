"""Press the daily costs job on GitHub, across both accounts (Oct 10, 2026).

Phase 4 of the move to Gate: every Backtest v2 trade pays the order book of
its own minute, read from per-minute cost files the `costs.yml` job writes
(tradingagents/cost_store.py). Gate publishes each order-book hour about two
hours after it ends, so once a UTC day — from READY_HOUR_UTC — this deals
Gate's coins between the accounts (cloud_sweep.split_coins, the 40-machine
rule) and starts `costs.yml` on each for the newest MAX_DAYS_PER_PRESS days
of the last BACKFILL_DAYS not yet done. The first presses therefore backfill
the month a week at a time, newest first; every later one adds yesterday.

A day is DONE only when every account's run finished green. A red share, a
share that never appeared, or one still running after STALE_S leaves its days
for the next press — named in `last_error`, which the API serves.

Runs in the API's supervisor, on its own thread. Never under pytest.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

STATE = Path(os.path.expanduser("~/.tradingagents")) / "costs_daily.json"
WORKFLOW = "costs.yml"
READY_HOUR_UTC = 3          # yesterday's 23:00 hour is published by ~01:00-02:00
# TODAY SO FAR, once, before the morning backtest (~08:30 UTC): without it
# the newest ~8 hours of every v2 row had no recorded book - the hours the
# 1-day rooms switch on by (RCA-2026-10-10-H). Today is never marked done;
# tomorrow's 03:00 press reads the rest of it.
TODAY_HOUR_UTC = 7
# the operator, Oct 11, 2026: "what i want is past 2 months of backtest" —
# two months of per-minute costs, so a 60-day backtest pays every minute
BACKFILL_DAYS = 61
# NEWEST DAYS FIRST, A WEEK A PRESS (Oct 15, 2026, RCA-2026-10-15-G). One
# day of every coin takes ~10 minutes on an account's 20 machines (the 03:00
# UTC presses of Oct 11-15, 2026); 61 at once would hold all 40 machines
# past the job's 350-minute limit, end red, back off, and stand in front of
# the nightly backtest. A week is ~70 minutes; the next week follows
# `RETRY_S` after it goes green, until the backfill is whole.
MAX_DAYS_PER_PRESS = 7
SHARDS = 20
RETRY_S = 30 * 60
MAX_WAIT_S = 8 * 3600       # the longest a run of red presses ever waits
STALE_S = 8 * 3600


def read() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(d: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_name(f"{STATE.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    os.replace(tmp, STATE)


def _day(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(int(t)))


def redo_if_read_differently(st: dict) -> bool:
    """Every day done before the book was read when practice looks
    (`book_history.READ_AT_S`, Oct 15, 2026, RCA-2026-10-15-G) is asked for
    again, ONCE: the shards re-read only the hours a month holds the old way
    (`costs_shard.held_hours`), so a press that runs out of time is resumed
    like any other. True when it just did."""
    from tradingagents import book_history as bh

    if st.get("read_at_s") == bh.READ_AT_S:
        return False
    st["done_days"] = []
    st.pop("today_pressed", None)
    st["read_at_s"] = bh.READ_AT_S
    _write(st)
    return True


def wanted_days(now: float, done) -> list[str]:
    today = int(now) - int(now) % 86400
    days = [_day(today - 86400 * k) for k in range(BACKFILL_DAYS, 0, -1)]
    return [d for d in days if d not in set(done or [])]


def _settle(st: dict, now: float) -> None:
    """Read the runs in flight; mark their days done when every share is
    green, or give them back when one is red, missing or stale."""
    from tradingagents import forecast_v2_daily as f2d

    fl = st.get("flight")
    if not fl:
        return
    states = []
    for r in fl.get("runs", []):
        try:
            got = f2d.run_status(int(r["run"]), r["repo"])
        except Exception as exc:                               # noqa: BLE001
            got = {"status": "unknown", "conclusion": f"unreadable: {exc}"}
        states.append((r, got))
    if any(g.get("status") != "completed" for _r, g in states):
        if now - float(fl.get("at") or now) > STALE_S:
            st["last_error"] = (f"the costs runs for {len(fl['days'])} day(s) were "
                                f"still not finished after {STALE_S // 3600} hours — "
                                f"asked again")
            st.pop("flight", None)
        return
    red = [f"{r['repo']} (run {r['run']}): {g.get('conclusion')}"
           for r, g in states if g.get("conclusion") != "success"]
    # EVERY PILE OF THE DEAL MUST HAVE RUN (RCA-2026-10-10-F): an account
    # `sync_fleet` refused has no run in the flight at all, and "every share
    # green" over the runs that exist marked 30 days done for half the market
    red += list(fl.get("unrun") or [])
    if red:
        st["last_error"] = "not every share finished green: " + "; ".join(red)
        st["reds"] = int(st.get("reds") or 0) + 1
    elif fl.get("read_at_s") != _read_at_s():
        # a run pressed before the book was read when practice looks: green,
        # but its hours were read at the close, so its days stay to be asked
        st["last_error"] = ("a costs run started before the order book was read "
                            f"{_read_at_s()} s after the close finished — its days "
                            "are read again")
        st["reds"] = 0
    else:
        today = fl.get("today")
        st["done_days"] = sorted(set(st.get("done_days") or [])
                                 | {d for d in fl["days"] if d != today})
        if today:
            st["today_pressed"] = today
        st["last_error"] = ""
        st["last_done_at"] = now
        st["reds"] = 0
    st.pop("flight", None)


def _read_at_s() -> int:
    from tradingagents import book_history as bh

    return int(bh.READ_AT_S)


def wait_s(reds: int) -> float:
    """How long after a press the next one may go: 30 minutes, doubled for
    every red run in a row before it, never past MAX_WAIT_S. Measured from the
    PRESS, so a run that took six hours to go red is pressed again at once and
    only a run that fails fast, again and again, is spaced out."""
    if reds <= 1:
        return RETRY_S
    return min(RETRY_S * 2 ** (reds - 1), MAX_WAIT_S)


def _under_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def tick(now: float | None = None) -> dict:
    if _under_pytest():
        return {"started": False, "why": "never under pytest"}
    from tradingagents import venue

    if venue.current() != "gate":
        return {"started": False, "why": "the costs job is Gate's (the app trades MEXC)"}
    now = time.time() if now is None else float(now)
    st = read()
    redo_if_read_differently(st)
    _settle(st, now)
    if st.get("flight"):
        _write(st)
        return {"started": False, "why": "a costs run is still going"}
    if time.gmtime(int(now)).tm_hour < READY_HOUR_UTC:
        _write(st)
        return {"started": False,
                "why": f"waiting until after {READY_HOUR_UTC}:00 UTC for yesterday's "
                       f"last order-book hour"}
    wait = wait_s(int(st.get("reds") or 0))
    if now - float(st.get("tried_at") or 0) < wait:
        _write(st)
        reds = int(st.get("reds") or 0)
        if reds:
            from tradingagents.positions_view import fmt_when

            return {"started": False,
                    "why": f"the last {reds} costs run(s) in a row ended red "
                           f"({st.get('last_error', '')[:160]}); trying again "
                           f"{fmt_when(float(st.get('tried_at') or 0) + wait)}"}
        return {"started": False, "why": "the last press failed; trying again soon"}
    days = wanted_days(now, st.get("done_days"))[-MAX_DAYS_PER_PRESS:]
    today = _day(now)
    today_due = (time.gmtime(int(now)).tm_hour >= TODAY_HOUR_UTC
                 and st.get("today_pressed") != today)
    if today_due:
        days = days + [today]
    if not days:
        _write(st)
        return {"started": False, "why": "every day of the last month is done"}
    # A BACKFILL OF THE V3 RESEARCH'S ORDER BOOKS may be in the air on a month this press also
    # writes (RCA-2026-10-28-F): two runs reading one coin-month file and uploading it back keep
    # only the later run's days, and both mark theirs done. Wait for it; say `pressing` before
    # the dispatch and look once more, so whichever of the two writes second sees the other.
    held = _held_by_backfill(days, now)
    if held:
        _write(st)
        return {"started": False, "why": held}
    st["pressing"] = {"at": now}
    _write(st)
    held = _held_by_backfill(days, now)
    if held:
        st.pop("pressing", None)
        _write(st)
        return {"started": False, "why": held}
    st["tried_at"] = now
    try:
        got = _dispatch(days, now)
    except Exception as exc:                                   # noqa: BLE001
        st.pop("pressing", None)
        st["last_error"] = f"could not start the costs job: {type(exc).__name__}: {exc}"
        _write(st)
        return {"started": False, "why": st["last_error"]}
    st.pop("pressing", None)
    st["flight"] = {"at": now, "days": days, "runs": got["runs"],
                    "unrun": got["unrun"], "today": today if today_due else None,
                    # the read its shards make: a flight pressed before
                    # READ_AT_S never marks its days done (`_settle`)
                    "read_at_s": _read_at_s()}
    if got["refused"]:
        st["last_error"] = "; ".join(got["refused"])
    _write(st)
    return {"started": True, "days": days, "runs": got["runs"]}


def _held_by_backfill(days: list[str], now: float) -> str:
    """Why this press of `days` must wait for a v3 backfill press in the air, or "". A record
    that cannot be read holds the press too, named: unknown is not clear."""
    from tradingagents import v3_coverage

    try:
        return v3_coverage.daily_held_off(days, now)
    except Exception as exc:                                   # noqa: BLE001
        return f"the daily press waits: {exc}"


def _dispatch(days: list[str], now: float) -> dict:
    from tradingagents import cloud_sweep as cs, forecast_v2_daily as f2d
    from tradingagents.dataflows import gate_futures as gf

    fleets, refused = cs.usable_fleets()
    if not fleets:
        raise RuntimeError("no GitHub account can run the workflow: "
                           + ("; ".join(refused) or "no remote"))
    coins = gf.trading_symbols()
    piles = cs.split_coins(coins, len(fleets))
    runs, unrun = [], []
    for slug, pile in zip(fleets, piles):
        drift = cs.sync_fleet(slug)
        if drift:
            # a pile was DEALT to this account and never ran: its coins are
            # unmeasured, so the days stay undone (an account usable_fleets
            # left out was dealt nothing — the others hold its coins)
            refused.append(drift)
            unrun.append(f"{slug}: {len(pile)} coins never ran ({drift})")
            continue
        inputs = {"shards": str(SHARDS), "days": ",".join(days),
                  "coin_list": ",".join(pile),
                  "label": f"{slug.split('/')[0]} {len(pile)} coins"}
        rid = f2d.dispatch(WORKFLOW, inputs, slug)
        runs.append({"repo": slug, "run": int(rid), "coins": len(pile)})
    if not runs:
        raise RuntimeError("; ".join(refused) or "no account took the run")
    return {"runs": runs, "refused": refused, "unrun": unrun}
