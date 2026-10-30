"""Press the daily costs job on GitHub, across both accounts (Oct 10, 2026).

Phase 4 of the move to Gate: every Backtest v2 trade pays the order book of
its own minute, read from per-minute cost files the `costs.yml` job writes
(tradingagents/cost_store.py). Gate publishes each order-book hour about two
hours after it ends, so once a UTC day — from READY_HOUR_UTC — this deals
Gate's coins between the accounts (cloud_sweep.split_coins, the 40-machine
rule) and starts `costs.yml` on each for the newest MAX_DAYS_PER_PRESS days
of the last BACKFILL_DAYS not yet done. The first presses therefore backfill
the month a week at a time, newest first; every later one adds yesterday.

A day is DONE only when every account's run finished green AND Gate's archive
held its last hour when the press went out (RCA-2026-10-30-A: Gate published
nothing after Oct 22, 2026 04:00 UTC for eight days, every 404 was booked
final, and Oct 22-29 were marked done for ever). A day the archive does not
hold yet is never pressed and never marked done; the state says how many wait
(`waiting_for_gate`), and the log says so once an hour. A red share, a share
that never appeared, or one still running after STALE_S leaves its days for
the next press — named in `last_error`, which the API serves.

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
# A press held off by a v3 backfill (RCA-2026-10-28-F) looks again at most this often (each look
# is one `gh run view` per run), and says so in the log at most this often
HELD_RECHECK_S = 300
HELD_SAY_S = 3600
# Gate's archive is asked where it ends (`book_history.newest_published_hour`, a few dozen HEADs)
# at most this often: the supervisor ticks every 30 s
PROBE_EVERY_S = 30 * 60


def read_strict() -> dict:
    """The saved state; no file is `{}`, a file that cannot be read RAISES - for the v3 backfill,
    which must treat an unreadable record as a daily press possibly in the air (M7)."""
    try:
        text = STATE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    d = json.loads(text)
    if not isinstance(d, dict):
        raise ValueError(f"{STATE} is not an object")
    return d


def read() -> dict:
    try:
        return read_strict()
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
    newest, unread = None, ""
    if not red and fl.get("read_at_s") == _read_at_s():
        # THE ARCHIVE AS IT STOOD WHEN THE PRESS WENT OUT: an hour Gate published after the
        # shards asked for it was not there for them (RCA-2026-10-30-A); a flight from before
        # this rule is judged by the archive now
        newest, unread = ((fl["gate_newest"], "") if "gate_newest" in fl
                          else _gate_newest(st, now))
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
    elif unread:
        st["last_error"] = (f"could not read which hours Gate's archive has published "
                            f"({unread}): no day of the finished costs run is marked done, "
                            "they are asked again")
        st["reds"] = 0
    else:
        from tradingagents import book_history as bh

        today = fl.get("today")
        days = [d for d in fl["days"] if d != today]
        late = [d for d in days if not bh.day_published(d, newest)]
        st["done_days"] = sorted(set(st.get("done_days") or [])
                                 | {d for d in days if d not in late})
        if today:
            st["today_pressed"] = today
        st["last_error"] = waiting_words(newest, late) if late else ""
        st["last_done_at"] = now
        st["reds"] = 0
    st.pop("flight", None)


def waiting_words(newest: int | None, days: list[str]) -> str:
    """The plain sentence for days Gate has not published yet (RCA-2026-10-30-A)."""
    from tradingagents import book_history as bh, v3_coverage
    from tradingagents.positions_view import fmt_when

    after = (f"after the hour starting {fmt_when(newest)} (this PC's clock)" if newest is not None
             else f"in the last {bh.PROBE_BACK_HOURS // 24} days")
    return (f"Gate has published no order book {after}; {len(days)} day(s) wait for it "
            f"({v3_coverage.range_words(days)}): they are pressed and marked done once "
            "Gate's archive holds them")


def _gate_newest(st: dict, now: float) -> tuple[int | None, str]:
    """(the newest hour Gate's archive holds or None, "" or why it could not be read), asked at
    most every PROBE_EVERY_S - the answer, or the failure, is kept in the state."""
    from tradingagents import book_history as bh

    seen = st.get("gate_newest") or {}
    if seen and now - float(seen.get("at") or 0) < PROBE_EVERY_S:
        return seen.get("hour"), seen.get("error") or ""
    try:
        hour, err = bh.newest_published_hour(now), ""
    except Exception as exc:                                   # noqa: BLE001
        hour, err = None, f"{type(exc).__name__}: {str(exc)[:160]}"
    st["gate_newest"] = {"at": now, "hour": hour, "error": err}
    return hour, err


# THE ONE-TIME REPAIR (RCA-2026-10-30-A): the newest hour Gate's archive held when it was
# measured, Oct 30, 2026 - Oct 22, 2026 04:00 UTC. Every day after it that an older build marked
# done (Oct 22-29 by Oct 30, and any day the build still running marks before the site takes this
# code) comes out of the done days ONCE, on the first tick of this code, so it is pressed again
# when Gate publishes it. A fixed hour, never the archive's end as read later: a day marked done
# while it was unpublished stays wrong after Gate publishes it.
OUTAGE_LAST_HOUR = 1792641600
REPAIR_KEY = "forgot_unpublished"


def _repair_once(st: dict, now: float) -> None:
    """Take every done day after OUTAGE_LAST_HOUR out of the state, once: the file is copied
    beside itself first (`costs_daily.json.<stamp>.bak`) and the counts go to the log and the
    state (`forgot_unpublished`)."""
    import shutil

    from tradingagents import book_history as bh
    from tradingagents.positions_view import fmt_when

    if st.get(REPAIR_KEY):
        return
    before = list(st.get("done_days") or [])
    keep = [d for d in before if bh.day_published(d, OUTAGE_LAST_HOUR)]
    removed = [d for d in before if d not in keep]
    if removed and STATE.exists():
        shutil.copy2(STATE, STATE.with_name(
            f"{STATE.name}.{time.strftime('%Y%m%d-%H%M%S', time.gmtime(int(now)))}.bak"))
    st["done_days"] = keep
    st[REPAIR_KEY] = {"at": now, "before": len(before), "after": len(keep), "removed": removed}
    _write(st)
    print(f"[costs-daily] one-time repair (RCA-2026-10-30-A): {len(removed)} day(s) after the "
          f"hour starting {fmt_when(OUTAGE_LAST_HOUR)} (this PC's clock), when Gate's archive "
          f"stopped, taken out of the done days ({len(before)} -> {len(keep)}), so they are pressed once Gate "
          "publishes them", flush=True)


def forget_unpublished(newest: int, *, daily_path=None, backfill_path=None,
                       stamp: str | None = None) -> dict:
    """THE ONE-TIME REPAIR of Oct 30, 2026 (RCA-2026-10-30-A), by hand: every day after Gate's
    archive's newest hour `newest` comes out of this job's done days and out of the v3 backfill's
    green presses, so both ask for them again once Gate publishes - nothing else is changed. A
    path given as False is left alone (the daily job's own file is repaired by `_repair_once`
    on the first tick of this code: the build already running would press the days at once and
    mark them done again). Each file is copied beside itself first (`<name>.<stamp>.bak`).
    Returns the counts before and after, and the days removed."""
    import shutil

    from tradingagents import book_history as bh

    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    if backfill_path is None:
        from tradingagents import v3_coverage

        backfill_path = v3_coverage.state_path()
    out = {}
    todo = [(k, Path(p)) for k, p in (("daily", STATE if daily_path is None else daily_path),
                                       ("backfill", backfill_path)) if p is not False]
    for key, path in todo:
        if not path.exists():
            out[key] = {"missing": str(path)}
            continue
        shutil.copy2(path, path.with_name(f"{path.name}.{stamp}.bak"))
        d = json.loads(path.read_text(encoding="utf-8"))
        if key == "daily":
            before = list(d.get("done_days") or [])
            d["done_days"] = [x for x in before if bh.day_published(x, newest)]
            out[key] = {"before": len(before), "after": len(d["done_days"]),
                        "removed": [x for x in before if x not in d["done_days"]]}
        else:
            n_before = n_after = cd_before = cd_after = 0
            removed: set = set()
            for p in d.get("presses") or []:
                days = list(p.get("days") or [])
                keep = [x for x in days if bh.day_published(x, newest)]
                coins = len(p.get("coins") or [])
                n_before, n_after = n_before + len(days), n_after + len(keep)
                cd_before, cd_after = cd_before + coins * len(days), cd_after + coins * len(keep)
                removed |= set(days) - set(keep)
                p["days"] = keep
            out[key] = {"before": n_before, "after": n_after, "removed": sorted(removed),
                        "coin_days_before": cd_before, "coin_days_after": cd_after}
        tmp = path.with_name(f"{path.name}.{os.getpid()}.repair.tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    return out


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
    _repair_once(st, now)
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
    from tradingagents import book_history as bh

    wanted = wanted_days(now, st.get("done_days"))
    today = _day(now)
    today_due = (time.gmtime(int(now)).tm_hour >= TODAY_HOUR_UTC
                 and st.get("today_pressed") != today)
    newest = None
    if wanted or today_due:
        # NEVER A DAY GATE HAS NOT PUBLISHED (RCA-2026-10-30-A): its shards get 404 for every
        # hour, and a green run of nothing would mark it done for ever
        newest, unread = _gate_newest(st, now)
        if unread:
            _write(st)
            return {"started": False,
                    "why": f"could not read which hours Gate's archive has published "
                           f"({unread}): nothing is pressed or marked done until it can be; "
                           f"asked again in {PROBE_EVERY_S // 60} minutes"}
    late = [d for d in wanted if not bh.day_published(d, newest)]
    st["waiting_for_gate"] = {"after": newest, "days": late} if late else None
    days = [d for d in wanted if d not in late][-MAX_DAYS_PER_PRESS:]
    # today's hours so far, only once Gate has published one of them
    today_due = today_due and newest is not None and newest >= now - now % 86400
    if today_due:
        days = days + [today]
    if not days:
        why = "every day of the last month is done"
        if late:
            why = (f"every day of the last {BACKFILL_DAYS} that Gate has published is done; "
                   + waiting_words(newest, late))
            if not st.get("last_error") or st["last_error"].startswith("Gate has published"):
                st["last_error"] = waiting_words(newest, late)
            if now - float(st.get("gate_said_at") or 0) >= HELD_SAY_S:
                st["gate_said_at"] = now
                print(f"[costs-daily] {why}", flush=True)
        _write(st)
        return {"started": False, "why": why}
    # A BACKFILL OF THE V3 RESEARCH'S ORDER BOOKS may be in the air on a month this press also
    # writes (RCA-2026-10-28-F): two runs reading one coin-month file and uploading it back keep
    # only the later run's days, and both mark theirs done. Wait for it; say `pressing` before
    # the dispatch and look once more, so whichever of the two writes second sees the other.
    if st.get("held") and now < float(st.get("held_until") or 0):
        return {"started": False, "why": st["held"]["why"]}
    held = _held_by_backfill(days, now, st)
    if held:
        return _hold(st, now, held)
    st["pressing"] = {"at": now}
    _write(st)
    held = _held_by_backfill(days, now, st)
    if held:
        st.pop("pressing", None)
        return _hold(st, now, held)
    _released(st)
    st["tried_at"] = now
    t0 = time.time()

    def step(runs: list) -> None:
        # the `pressing` flag is said again before each account (M9): a v3 backfill judges it
        # live for v3_coverage.PRESSING_S from its newest step, and the runs started so far by
        # their own status, so a slow dispatch of three accounts never outlasts it
        st["pressing"] = {"at": now, "step_at": now + (time.time() - t0), "dispatching": True,
                          "runs": list(runs)}
        _write(st)

    try:
        got = _dispatch(days, now, step=step)
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
                    "read_at_s": _read_at_s(),
                    # the archive's end when the press went out: only days it held are done
                    "gate_newest": newest}
    if got["refused"]:
        st["last_error"] = "; ".join(got["refused"])
    _write(st)
    return {"started": True, "days": days, "runs": got["runs"]}


def _say(st: dict, now: float, text: str) -> None:
    """One log line (the API's own log, `.run/api.log`, which the error filer also reads) at
    most every HELD_SAY_S: a hold that is a line every 30 seconds is a silence."""
    if now - float(st.get("held_said_at") or 0) >= HELD_SAY_S:
        st["held_said_at"] = now
        print(f"[costs-daily] {text}", flush=True)


def _hold(st: dict, now: float, why: str) -> dict:
    """The press waits: the reason is kept in the state (`held`, `last_error`, the file the
    operator can open), said once an hour in the log, and not looked at again for
    HELD_RECHECK_S."""
    st["held"] = {"since": (st.get("held") or {}).get("since", now), "why": why}
    st["held_until"] = now + HELD_RECHECK_S
    st["last_error"] = why
    _say(st, now, why)
    _write(st)
    return {"started": False, "why": why}


def _released(st: dict) -> None:
    held = st.pop("held", None)
    st.pop("held_until", None)
    if held and st.get("last_error") == held["why"]:
        st["last_error"] = ""


def _held_by_backfill(days: list[str], now: float, st: dict) -> str:
    """Why this press of `days` must wait for a v3 backfill press in the air, or "". A record
    that cannot be read holds the press (it might describe a live run) but never longer than
    v3_coverage.STALE_S, judged from the EARLIER of the file's stamp and when it was first seen
    unreadable (so a stamp in the future cannot stretch it): after that the press runs and says
    once that it ignored it."""
    from tradingagents import v3_coverage

    try:
        got = v3_coverage.daily_held_off(days, now)
        st.pop("backfill_unreadable_since", None)
        st.pop("backfill_ignored", None)
        return got
    except Exception as exc:                                   # noqa: BLE001
        mtime = v3_coverage.record_mtime()
        first = st.setdefault("backfill_unreadable_since", now)
        hours = v3_coverage.STALE_S // 3600
        # a stamp in the FUTURE (a clock set ahead, or moved back) would stretch the bound by the
        # skew, today and again once the clock passes it: the earlier of the file's stamp and
        # when it was first seen unreadable decides: at most 12 hours of this PC's
        # clock (a clock stepped BACK during a hold adds that step; a deleted state file restarts it once)
        stamp = first if mtime is None else min(mtime, first)
        if now - stamp > v3_coverage.STALE_S:
            msg = (f"the v3 backfill record could not be read ({exc}) for more than {hours} "
                   "hours: the daily press runs without it")
            st["last_error"] = msg
            if not st.get("backfill_ignored"):
                # the notice that the press RAN without the record is never thinned by the
                # hourly gate that thins "still held" lines; said once per episode
                st["backfill_ignored"] = now
                st["held_said_at"] = now
                print(f"[costs-daily] {msg}", flush=True)
            return ""
        return (f"could not read the v3 backfill record ({exc}): the daily press waits for it, "
                f"at most {hours} hours")


def _dispatch(days: list[str], now: float, step=None) -> dict:
    """Deal Gate's coins between the accounts and start costs.yml on each. `step(runs so far)`
    is called before each account, so whoever watches the press sees it still going."""
    from tradingagents import cloud_sweep as cs, forecast_v2_daily as f2d
    from tradingagents.dataflows import gate_futures as gf

    fleets, refused = cs.usable_fleets()
    if not fleets:
        raise RuntimeError("no GitHub account can run the workflow: "
                           + ("; ".join(refused) or "no remote"))
    coins = gf.trading_symbols()
    piles = cs.split_coins(coins, len(fleets))
    runs, unrun = [], []
    for slug, pile in zip(fleets, piles, strict=False):
        if step is not None:
            step(runs)
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
