"""Forecast v2, once a day — and the page's what-if box.

The build prompt (docs/FORECAST-V2.md): *"Heavy work runs as a job (on GitHub
if the research already does, collected like the replay), once a day after
the daily GitHub update is collected, never in a page request."*

THE DAILY CHAIN, one step per supervisor tick (api.py, every 30 seconds),
every step's state kept in ~/.tradingagents/forecast_v2/state.json:

  idle     due once the day's GitHub backtest update is on this PC (the same
           test the v1 automatic forecast uses, room_forecasts._update)
  replay   .github/workflows/replay.yml from the first day of the month
           MONTHS_BACK months ago to now, every strategy that could pass the
           loosest rule set (WRITE_RULE) — about an hour on 20 machines
  base     .github/workflows/forecast.yml, stage base, on that replay; the
           common end comes from the machines' replay-report-<N> artifacts
  options  the same, stage options, on the TOP_FOR_OPTIONS best base sets and
           the rooms' own rules
  done     merged into latest.json (forecast_v2_merge), the month's first
           prediction kept, ONE bell message for the day

A failure is NAMED in the state and on the page, and that step is tried again
after RETRY_S — never every tick, never silently. GitHub is asked at most
every POLL_S. Never under pytest against the real files.

WHAT-IF: a rule set the operator types is one `custom` forecast run on the
last FINISHED replay (`ready`); its answer is kept by rule id with the data it
was measured on, so asking again returns at once. Every save of whatif.json is
one record over a fresh read, under one lock; a start a restart cut off is
marked so it can be asked again, and the re-ask adopts any run it made.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import threading
import time
from pathlib import Path

from tradingagents import forecast_rules as fr, forecast_v2 as f2

MONTHS_BACK = 3
WRITE_RULE = "wr=70,trades=20,tp=any,windows=15|30"      # the loosest base rule set, every shape
REPLAY_WF = "replay.yml"
FORECAST_WF = "forecast.yml"
SHARDS = 20
POLL_S = 120
RETRY_S = 30 * 60
KEEP_RUNS = 3                 # downloaded forecast runs kept beside the store
WORST_FAMILIES = 5            # the skip-families option skips this many
_LOCK = threading.Lock()
_WHATIF_LOCK = threading.Lock()


def home() -> Path:
    return f2._home()


def _state_path() -> Path:
    return home() / "state.json"


def _switch_path() -> Path:
    return home() / "switch.json"


def is_on() -> bool:
    """The page's on/off box, kept in ITS OWN FILE (bug hunt, round 6): the
    chain's tick reads the state, may spend minutes downloading and merging,
    then writes the whole state back — a switch saved into that same file
    meanwhile was written over, and "off" came back "on"."""
    try:
        return json.loads(_switch_path().read_text(encoding="utf-8"))["on"] is not False
    except (OSError, ValueError, KeyError, TypeError):
        try:            # never switched since the box got its own file
            return json.loads(_state_path().read_text(encoding="utf-8")).get("on", True) is not False
        except (OSError, ValueError, AttributeError):
            return True


def read() -> dict:
    try:
        st = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {"phase": "idle"}
    st["on"] = is_on()
    return st


def _write(st: dict) -> None:
    if not _switch_path().exists() and _state_path().exists():
        # CARRIED OVER, never dropped (bug hunt, round 10): before the box had
        # its own file it lived in this one — the first save without it
        # would have turned an "off" into the default "on"
        try:
            was = json.loads(_state_path().read_text(encoding="utf-8")).get("on")
        except (OSError, ValueError, AttributeError):
            was = None
        if was is False:
            f2.publish(_switch_path(), json.dumps({"on": False, "at": time.time(), "from": "state.json"}))
    keep = {k: v for k, v in st.items() if k != "on"}     # the switch has its own file
    f2.publish(_state_path(), json.dumps(keep, separators=(",", ":"), allow_nan=False))


# -------------------------------------------------------------- GitHub
def _gh(*args: str, timeout: int = 120) -> str:
    from tradingagents import cloud_sweep as cs

    return cs._gh(*args, timeout=timeout)


def slug() -> str:
    """The account every run of one chain goes to: a forecast run can only
    read a replay run's artifacts in the SAME repository."""
    from tradingagents import cloud_sweep as cs

    return cs.origin_fleet() or cs.repo_slug()


def title_of(workflow: str, inputs: dict) -> str:
    """The run-name GitHub gives this dispatch (the workflows' own
    `run-name:` lines) — how a dispatcher finds ITS run (bug hunt, round 3:
    "the newest run" could be the other session's replay)."""
    if workflow == REPLAY_WF:
        return f"Watcher replay · from {inputs['start']} · {inputs['write_rule']}"
    return (f"Forecast v2 · {inputs['stage']} · replay {inputs['source_run']} "
            f"{inputs.get('custom') or ''}").rstrip()


def same_title(shown: str, want: str) -> bool:
    """A run's title is this dispatch's own — or GitHub's cut of it: a
    what-if's title carries its whole rule set, and a cut title still holds
    the rule id within its first 60 characters."""
    shown = str(shown).strip()
    if shown == want:
        return True
    cut = shown.rstrip(".…").rstrip()
    return len(cut) >= 60 and want.startswith(cut)


def _ts(iso: str) -> float:
    return dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()


def _runs(workflow: str, repo: str, limit: int = 20) -> list:
    return json.loads(_gh("run", "list", "--repo", repo, "--workflow", workflow,
                          "--limit", str(limit), "--json", "databaseId,displayTitle,createdAt"))


def find_run(workflow: str, title: str, repo: str, since: float) -> int | None:
    """A run of this exact title made at or after `since` (less two minutes
    of clock difference): the run an earlier, failed-looking attempt really
    did start."""
    for r in _runs(workflow, repo):
        if same_title(r["displayTitle"], title) and _ts(r["createdAt"]) >= float(since) - 120:
            return int(r["databaseId"])
    return None


def dispatch(workflow: str, inputs: dict, repo: str, since: float | None = None) -> int:
    """Start a workflow and return ITS run id: `gh workflow run` prints none,
    so wait for a new run carrying this dispatch's own title.

    `since` — when an earlier attempt at THIS dispatch raised, the time it was
    made: GitHub may have taken the run and only been slow to list it, so a
    run of this title made since then is adopted, never started twice (bug
    hunt, round 6: a second replay is 20 machines for an hour)."""
    want = title_of(workflow, inputs)
    if since:
        got = find_run(workflow, want, repo, since)
        if got:
            return got
    before = {int(r["databaseId"]) for r in _runs(workflow, repo, 10)}
    args = ["workflow", "run", workflow, "--repo", repo]
    for k, v in inputs.items():
        args += ["-f", f"{k}={v}"]
    _gh(*args)
    for _ in range(45):
        time.sleep(2)
        for r in _runs(workflow, repo, 10):
            if int(r["databaseId"]) not in before and same_title(r["displayTitle"], want):
                return int(r["databaseId"])
    raise RuntimeError(f"the {workflow} run ({want[:80]}) did not appear within 90 seconds")


def run_status(run_id: int, repo: str) -> dict:
    d = json.loads(_gh("run", "view", str(run_id), "--repo", repo, "--json",
                       "status,conclusion,jobs,url,createdAt"))
    jobs = [j for j in d.get("jobs", []) if j.get("name") != "plan"]
    return {"status": d.get("status"), "conclusion": d.get("conclusion"), "url": d.get("url"),
            "created": _ts(d["createdAt"]) if d.get("createdAt") else None,
            "machines": len(jobs), "done": sum(1 for j in jobs if j.get("status") == "completed"),
            "failed": [j["name"] for j in jobs if j.get("conclusion") not in (None, "success")]}


def run_words(s: dict, also: str = "") -> str:
    """Where a run that has not finished really is (bug hunt, round 6): a run
    GitHub has not given machines yet read "working on GitHub: 0 of 0
    machines done" — a what-if asked at 7:26pm sat QUEUED behind the daily
    replay's 20 machines while the page said it was working."""
    from tradingagents.positions_view import fmt_when

    if s.get("status") in ("queued", "waiting", "pending", "requested"):
        when = f" since {fmt_when(s['created'])}" if s.get("created") else ""
        return f"waiting in GitHub's queue{when}, not started yet{also}"
    if not s.get("machines"):
        return "GitHub is starting it"
    return f"working on GitHub: {s['done']} of {s['machines']} machines done"


def download(run_id: int, repo: str, pattern: str) -> Path:
    """A run's artifacts BESIDE THE STORE (G:), never %TEMP% — the forecast
    artifacts are hundreds of MB (CLAUDE.md, big files go where the store is)."""
    dest = home() / "runs" / str(run_id)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    _gh("run", "download", str(run_id), "--repo", repo, "-p", pattern, "-D", str(dest),
        timeout=1800)
    _prune_runs(keep={str(run_id)})
    return dest


def _prune_runs(keep: set) -> None:
    root = home() / "runs"
    if not root.exists():
        return
    st = read()
    keep = set(keep) | {str(st.get(k)) for k in ("base_run", "options_run") if st.get(k)}
    dirs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime,
                  reverse=True)
    for d in dirs[KEEP_RUNS:]:
        if d.name not in keep:
            shutil.rmtree(d, ignore_errors=True)


def common_end(report_dir: Path) -> int:
    """The earliest last intraday bar over every machine — the one moment
    every coin reached (replay_collect.common_end, the research's own rule)."""
    return int(read_reports(report_dir)["end_ms"])


def read_reports(report_dir: Path) -> dict:
    """The replay's common end and WHAT IT COVERED — its write rule, signal
    groups, coins and strategies (bug hunt, round 16): the same rule set
    walked forward on two replays gave #562C0147 1,703 July trades on the
    first (2 signal groups, 1,079 coins) and 2,098 on Oct 01, 2026's (4
    groups, 1,092 coins). A prediction is only comparable with a result
    measured over the same strategies, so each one carries this."""
    from tradingagents import replay_collect as rc

    tot = rc.merge_reports([str(report_dir)])
    end = rc.common_end(tot["spans"])
    if not end:
        raise RuntimeError("the replay's reports name no measured pair")
    coins = {str(k).rsplit(" ", 1)[0] for k in (tot.get("spans") or {})}
    return {"end_ms": int(end), "universe": {
        "write": tot.get("write") or {}, "groups": sorted(tot.get("groups") or []),
        "coins": len(coins), "strategies": int(tot.get("kept") or 0)}}


# --------------------------------------------------------- the inputs
def room_rules() -> dict:
    """{room id: its own rules as a rule set} for every room still trading."""
    from tradingagents import profiles, room_stats as rs

    out = {}
    for pid in profiles.ids():
        if profiles.retired(pid):
            continue
        c = rs.rules_of(pid)
        cfg = fr.cfg_of(int(c.get("window_days") or 30), float(c["on_winrate"]),
                        int(c["min_trades"]), str(c.get("tp_rule") or ">"),
                        float(c.get("max_sl") or 0))
        cfg["off_winrate"] = float(c.get("off_winrate", c["on_winrate"]))
        out[pid] = cfg
    return out


def skip_lists(live: dict | None = None) -> tuple[list, list]:
    """(coins to avoid, the worst signal families) from practice right now."""
    live = live or f2.live()
    coins = [c["coin"] for c in live["avoid"]["coins"]]
    fam = sorted((g for g in live["money"]["by_family"]
                  if g["trades"] >= f2.THIN and g["profit"] < 0), key=lambda g: g["profit"])
    return coins, [g["group"] for g in fam[:WORST_FAMILIES]]


def first_check(now: float) -> str:
    d = dt.date.fromtimestamp(now).replace(day=1)
    for _ in range(MONTHS_BACK):
        d = (d - dt.timedelta(days=1)).replace(day=1)
    return d.isoformat()


def _forecast_inputs(st: dict, stage: str, extra: dict | None = None) -> dict:
    rooms = room_rules()
    avoid, fams = st.get("avoid") or [], st.get("families") or []
    return {"source_run": st["replay_run"], "shards": SHARDS, "end_ms": st["end_ms"],
            "start": st["start"], "stage": stage, "bases": "", "rooms": fr.encode_rooms(rooms),
            "avoid": ",".join(avoid), "families": ",".join(fams), "custom": "",
            **(extra or {})}


# ------------------------------------------------------------ is it due
def due(now: float, st: dict) -> tuple[bool, str]:
    from tradingagents import room_forecasts as rf
    from tradingagents.positions_view import fmt_when

    today = dt.date.fromtimestamp(now).isoformat()
    # ONE CHAIN STARTED A DAY, counted by the day it STARTED (bug hunt, round
    # 6): counted by the day it finished, a chain that ran past midnight held
    # the next day's update back until the midnight after it
    started = st.get("started_day") or (dt.date.fromtimestamp(float(st["started_at"])).isoformat()
                                        if st.get("started_at") else None)
    if started == today:
        if st.get("phase") == "done":
            return False, f"today's Forecast v2 was made at {fmt_when(st.get('done_at') or now)}"
        return False, ("today's Forecast v2 was given up (the last error says why) — the next "
                       "daily update starts a new one")
    up = rf._update()
    if not up["runs"] or not up["when"]:
        return False, "waiting for the first daily GitHub update to go out"
    if up["when"] <= float(st.get("last_update") or 0):
        return False, (f"waiting for the next daily GitHub update — the last one "
                       f"({fmt_when(up['when'])}) already has its Forecast v2")
    if len(up["collected"]) < len(up["runs"]):
        return False, (f"waiting for the {fmt_when(up['when'])} GitHub update to be copied "
                       f"onto this PC ({len(up['collected'])} of {len(up['runs'])} runs in)")
    return True, f"the {fmt_when(up['when'])} GitHub update is on this PC"


# ------------------------------------------------------------- one tick
def tick(now: float | None = None) -> dict:
    """The supervisor's 30-second call, in its own thread: at most one step of
    the chain, the what-if runs' polls, and the bells (a new practice streak,
    a room under its predicted worst case)."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"why": "never under a test run"}
    if not _LOCK.acquire(blocking=False):
        return {"why": "a tick is already running"}
    try:
        now = time.time() if now is None else float(now)
        st = read()
        try:
            _step(st, now)
        except Exception as exc:                               # noqa: BLE001
            _fail(st, now, f"{type(exc).__name__}: {str(exc)[:300]}")
        try:
            _whatifs(st, now)
            st.pop("whatif_error", None)
        except Exception as exc:                               # noqa: BLE001
            # the newest failure, never the first one kept for ever
            st["whatif_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        try:
            from tradingagents import forecast_v2_api as f2a

            if f2a._LIVE["value"] is not None:         # never a slow first read here
                f2a.tracker_alarms(now)
                streak_bells(f2a._LIVE["value"])
        except Exception as exc:                               # noqa: BLE001
            print(f"[forecast v2] the bells failed: {exc!r}", flush=True)
        _write(st)
        return {"phase": st.get("phase"), "why": st.get("why", "")}
    finally:
        _LOCK.release()


def _fail(st: dict, now: float, why: str) -> None:
    from tradingagents.positions_view import fmt_when

    st["error"] = f"{st.get('phase', 'idle')}: {why}"
    st["failed_at"] = now
    st["why"] = (f"the {st.get('phase', 'idle')} step failed at {fmt_when(now)} — tried again "
                 f"after {RETRY_S // 60} minutes: {why}")
    print(f"[forecast v2] {st['why']}", flush=True)


def run_merge(base_dir: str, options_dir: str | None, runs: dict, keep: bool) -> None:
    """forecast_v2_merge in its OWN PROCESS (bug hunt, round 2): adding up the
    machines' streak rows peaks over a gigabyte and takes about two minutes,
    which must never happen inside the API or hold its supervisor. Its output
    goes to a log beside the store; a failure is raised with that log's tail."""
    import subprocess
    import sys

    log = home() / "merge.log"
    args = [sys.executable, "-m", "tradingagents.forecast_v2_merge", base_dir]
    if options_dir:
        args.append(options_dir)
    args += ["--runs", json.dumps(runs)] + (["--keep"] if keep else [])
    with log.open("w", encoding="utf-8") as fh:
        got = subprocess.run(args, stdout=fh, stderr=subprocess.STDOUT, timeout=3600,
                             cwd=str(Path(__file__).resolve().parents[1]),
                             env={**os.environ, "PYTHONUNBUFFERED": "1"})
    if got.returncode != 0:
        tail = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
        raise RuntimeError(f"the merge ended {got.returncode}: {' | '.join(tail)[:300]}")


def _latest() -> dict:
    return json.loads((home() / "latest.json").read_text(encoding="utf-8"))


def _say(st: dict, why: str) -> None:
    """Where the chain is, ON DISK before a slow step (bug hunt, round 15):
    the tick saves at its end, so through a download and a merge of minutes
    the page still said "working on GitHub: 18 of 20 machines done" about a
    run that had finished."""
    st["why"] = why
    try:
        _write(st)
    except OSError as exc:                 # a status line never stops the step
        print(f"[forecast v2] could not save the status: {exc!r}", flush=True)


def _tried(st: dict, what: str, now: float) -> float | None:
    """When an earlier attempt at THIS dispatch was made, or None; and mark
    this attempt — kept in the state, so a retry after a failure can adopt a
    run GitHub took but listed late (dispatch's `since`)."""
    was = st.get("tried") or {}
    since = was.get("at") if was.get("what") == what else None
    st["tried"] = {"what": what, "at": since or now}
    # ON DISK BEFORE THE DISPATCH (bug hunt, round 8): the tick writes its
    # state at its end, so a dispatch whose tick then failed to save left no
    # trace, and the next tick started the same run a second time
    _write(st)
    return since


STAGE_RETRIES = 1     # a run red on EVERY machine is started again this many times


def _replay_inputs(start: str) -> dict:
    return {"shards": SHARDS, "timeframes": "15m,30m,1h,4h,1d", "coin_list": "", "start": start,
            "base": 5, "groups": "all", "write_rule": WRITE_RULE}


def _redo(st: dict, phase: str, run_key: str, s: dict, repo: str, now: float) -> None:
    """A run red on EVERY machine (bug hunt, round 12). Raising here re-read
    the same failed run every RETRY_S for ever: never started again, never
    back to idle, so no later day ran either. It is started again
    STAGE_RETRIES times; then the day is given up, named, and the next daily
    update starts a fresh chain — the last finished data stays on the page."""
    why = (f"{phase} run {st[run_key]} ended {s['conclusion']} on every machine "
           f"({', '.join(s['failed'][:3]) or 'no machine named'})")
    redo = st.setdefault("redo", {})
    if redo.get(phase, 0) < STAGE_RETRIES:
        wf, inputs = ((REPLAY_WF, _replay_inputs(st["start"])) if phase == "replay" else
                      (FORECAST_WF, _forecast_inputs(st, phase, {"bases": st.get("bases") or ""}
                                                     if phase == "options" else None)))
        run = dispatch(wf, inputs, repo, since=_tried(st, f"redo {phase} {st[run_key]}", now))
        st.pop("tried", None)
        redo[phase] = redo.get(phase, 0) + 1
        st[run_key] = run
        st["why"] = f"{why} — started again as run {run} (try {redo[phase] + 1} of {STAGE_RETRIES + 1})"
        print(f"[forecast v2] {st['why']}", flush=True)
        return
    st.update(phase="idle", failed_at=0, redo={},
              error=f"{phase}: {why}, on every try — today's Forecast v2 is given up")
    st["why"] = f"{st['error']}; the next daily update starts a new one"
    print(f"[forecast v2] {st['why']}", flush=True)


def _step(st: dict, now: float) -> None:
    from tradingagents.positions_view import fmt_when

    if st.get("on") is False:
        st["why"] = "switched off on the Forecast v2 page"
        return
    if st.get("failed_at") and now - float(st["failed_at"]) < RETRY_S:
        return
    phase = st.get("phase") or "idle"
    repo = st.get("repo") or slug()
    if phase in ("idle", "done"):
        ok, why = due(now, st)
        st["why"] = why
        if not ok:
            return
        from tradingagents import room_forecasts as rf

        start = first_check(now)
        run = dispatch(REPLAY_WF, _replay_inputs(start), repo,
                       since=_tried(st, f"replay {start}", now))
        avoid, fams = skip_lists()
        st.pop("tried", None)
        st.update(phase="replay", repo=repo, replay_run=run, start=start, started_at=now,
                  started_day=dt.date.fromtimestamp(now).isoformat(),
                  last_update=rf._update()["when"], avoid=avoid, families=fams,
                  base_run=None, options_run=None, error="", failed_at=0, polled_at=0,
                  missing={}, redo={}, bases="",
                  why=f"replay {run} started on GitHub at {fmt_when(now)} (about an hour)")
        return
    if now - float(st.get("polled_at") or 0) < POLL_S:
        return
    st["polled_at"] = now
    run_key = {"replay": "replay_run", "base": "base_run", "options": "options_run"}[phase]
    s = run_status(int(st[run_key]), repo)
    if s["status"] != "completed":
        st["why"] = f"{phase} run {st[run_key]}: {run_words(s)}"
        return
    # SOME MACHINES FAILED, SOME DID NOT (bug hunt, round 3): a replay or a
    # forecast with 19 of 20 machines green is used — its missing machines
    # named in the state and on the page — instead of retried for ever
    good = s["machines"] - len(s["failed"])
    if s["conclusion"] != "success" and good <= 0:
        _redo(st, phase, run_key, s, repo, now)
        return
    if s["failed"]:
        st.setdefault("missing", {})[phase] = {"of": s["machines"], "failed": s["failed"][:40]}
    if phase == "replay":
        rep = download(int(st["replay_run"]), repo, "replay-report-*")
        got = read_reports(rep)
        st["end_ms"], st["universe"] = got["end_ms"], got["universe"]
        st["base_run"] = dispatch(FORECAST_WF, _forecast_inputs(st, "base"), repo,
                                  since=_tried(st, f"base {st['replay_run']}", now))
        st.pop("tried", None)
        # a step that got through clears the error a retry was for (bug hunt,
        # round 11: "last error" stayed on the page after the retry worked)
        st.update(phase="base", error="", failed_at=0,
                  why=f"forecast run {st['base_run']} (base) started on GitHub")
        return
    if phase == "base":
        _say(st, f"base run {st['base_run']} finished on GitHub — downloading and adding it up on "
                 f"this PC (a few minutes)")
        art = download(int(st["base_run"]), repo, "forecast-*")
        run_merge(str(art), None, {"replay": st["replay_run"], "base": st["base_run"],
                                   "shards": SHARDS, "missing": st.get("missing") or {},
                                   "universe": st.get("universe") or {}}, keep=False)
        out = _latest()
        bases = [s_["cfg"] for s_ in out["sets"] if s_["base"]][:fr.TOP_FOR_OPTIONS]
        rooms = room_rules()
        have = {fr.rule_id(c) for c in bases}
        bases += [c for c in rooms.values() if fr.rule_id(c) not in have]
        st["bases"] = ";".join(fr.encode(c) for c in bases)
        st["options_run"] = dispatch(FORECAST_WF, _forecast_inputs(st, "options", {"bases": st["bases"]}),
                                     repo, since=_tried(st, f"options {st['replay_run']}", now))
        st.pop("tried", None)
        st.update(phase="options", base_dir=str(art), error="", failed_at=0,
                  why=f"forecast run {st['options_run']} (options) started on GitHub")
        return
    if phase == "options":
        _say(st, f"options run {st['options_run']} finished on GitHub — downloading and adding up "
                 f"both runs on this PC (a few minutes)")
        art = download(int(st["options_run"]), repo, "forecast-*")
        run_merge(st["base_dir"], str(art), {"replay": st["replay_run"], "base": st["base_run"],
                                             "options": st["options_run"], "shards": SHARDS,
                                             "missing": st.get("missing") or {},
                                             "universe": st.get("universe") or {}}, keep=True)
        out = _latest()
        made = time.time()         # after the merge (bug hunt, round 16: "made at 8:49pm"
        #                            was the tick's start; the merge finished 8:54pm)
        st.update(phase="done", done_day=dt.date.fromtimestamp(made).isoformat(), done_at=made,
                  error="", failed_at=0,
                  options_dir=str(art), why=f"made at {fmt_when(made)}",
                  # what the what-if box measures on: the LAST FINISHED data,
                  # never a replay still running (bug hunt, round 4)
                  # .get: a key missing here must never stop a finished day
                  # reaching "done", or the merge re-runs every RETRY_S
                  ready={k: st.get(k) for k in ("replay_run", "end_ms", "start", "repo",
                                                "avoid", "families")})
        bell(out, f2.live())


# ------------------------------------------------------------- the bell
STREAK_BELL_GAP_S = 3600          # at most one streak bell an hour, every new run named in it
STREAK_BELL_NAMES = 12            # runs named in one bell; the rest counted


def streak_bells(live: dict, now: float | None = None) -> list:
    """Every room's coin that first reaches a winning run of WIN_N or a losing
    run of LOSS_M is announced ONCE (the build prompt's A5); never again for
    the same run (its start). The first time this ever runs it only remembers
    the runs already going, so switching it on is not a burst of old news.

    AT MOST ONE BELL AN HOUR (bug hunt, round 6): one bell per run would have
    been 46 bells on Oct 01, 2026 — 4 runs of 9 wins and 42 of 5 losses,
    25 of them in #4FC03172 alone — burying every other message on the bell.
    A run that reaches the line inside the hour waits for the next bell and
    is named in it. A room that is off (no tab) never rings."""
    from tradingagents import notifications as nt, profiles

    now = time.time() if now is None else float(now)
    path = home() / "streak_bells.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        first = False
    except (OSError, ValueError):
        saved, first = {}, True
    if "seen" not in saved:                       # the first file kept the keys at its top level
        saved = {"seen": saved, "waiting": [], "rung_at": 0.0}
    seen, waiting = saved["seen"], saved["waiting"]
    for s in live.get("streaks") or []:
        floor = f2.WIN_N if s["kind"] == "win" else f2.LOSS_M
        if s["length"] < floor or profiles.retired(s["room"]):
            continue
        key = f"{s['room']}|{s['coin']}|{s['kind']}|{int(s['started_at'] or 0)}"
        if key in seen:
            continue
        seen[key] = now
        if not first:
            word = "won" if s["kind"] == "win" else "lost"
            waiting.append({"key": key, "win": s["kind"] == "win", "length": s["length"],
                            "text": f"{s['coin']} has {word} {s['length']} in a row in {s['room_name']}",
                            "detail": (f"{s['coin']} {word} its last {s['length']} practice trades in "
                                       f"{s['room_name']} ({s['profit']:+.2f})")})
    rung = []
    if waiting and now - float(saved.get("rung_at") or 0) >= STREAK_BELL_GAP_S:
        waiting.sort(key=lambda w: (not w["win"], -w["length"]))
        if len(waiting) == 1:
            title, detail = waiting[0]["text"], waiting[0]["detail"]
        else:
            wins = sum(1 for w in waiting if w["win"])
            title = (f"{len(waiting)} new streaks: {wins} winning, {len(waiting) - wins} losing")
            detail = fit([w["text"] for w in waiting[:STREAK_BELL_NAMES]],
                         left=len(waiting) - min(len(waiting), STREAK_BELL_NAMES))
        nt.record("forecast", title, detail=detail, ok=all(w["win"] for w in waiting))
        rung = [w["key"] for w in waiting]
        saved.update(waiting=[], rung_at=now)
    f2.publish(path, json.dumps(saved))
    return rung


BELL_CHARS = 500                  # notifications.record keeps this much of a detail


def fit(parts: list[str], left: int = 0, limit: int = BELL_CHARS) -> str:
    """`parts` joined by "; " in order, within what the bell keeps (bug hunt,
    round 7): notifications.record cuts a detail at 500 characters, so a
    longer one lost its end — "and 34 more on the Forecast v2 page" first. A
    part that does not fit is left out WHOLE and counted with `left`, and the
    count always fits."""
    def text(shown: list[str], more: int) -> str:
        return "; ".join(shown + ([f"and {more} more on the Forecast v2 page"] if more else []))

    shown: list[str] = []
    for i, p in enumerate(parts):
        if len(text(shown + [p], left + len(parts) - i - 1)) > limit:
            return text(shown, left + len(parts) - i)[:limit]
        shown.append(p)
    return text(shown, left)[:limit]


def bell(out: dict, live: dict, rooms: list | None = None) -> None:
    """ONE message a day, in the build prompt's own order (section E): the
    longest winning and losing streaks, the worst coin to avoid, and each
    room's month so far against its predicted range — then the best rule set.

    Bug hunt, round 7: this said "and each room's month so far" while the
    code never added the rooms. `rooms` are the month tracker's rows
    (forecast_v2_api.tracker): the practice month against what the room's
    own rules made by the end of the same day of each past month."""
    from tradingagents import notifications as nt

    if rooms is None:
        from tradingagents import forecast_v2_api as f2a

        try:
            rooms = f2a.tracker()["rooms"]
        except Exception as exc:                               # noqa: BLE001
            print(f"[forecast v2] the bell has no month tracker: {exc!r}", flush=True)
            rooms = []
    st = live["streaks"]
    win = next((s for s in st if s["kind"] == "win"), None)
    loss = next((s for s in st if s["kind"] == "loss"), None)
    worst = (live["avoid"]["coins"] or [None])[0]
    parts = []
    if win:
        parts.append(f"longest winning run: {win['coin']} in {win['room_name']}, {win['length']} in a row")
    if loss:
        parts.append(f"longest losing run: {loss['coin']} in {loss['room_name']}, {loss['length']} in a row")
    if worst:
        parts.append(f"worst coin: {worst['coin']} {worst['profit']:+.2f} over {worst['trades']} trades")
    # every room, short (bug hunt, round 16: the long form fit 3 of 6 rooms
    # in the bell's 500 characters on Oct 01, 2026); the first one says what
    # the numbers are, once
    for i, r in enumerate(rooms):
        b = r.get("so_far") or {}
        lo, hi = b.get("corrected_low"), b.get("corrected_high")
        rng = f"{lo:+.2f} to {hi:+.2f}" if lo is not None else "no range yet"
        lead = (f"each room this month vs its rules by day {b.get('day', '?')} "
                f"(after the reality check): " if i == 0 else "")
        parts.append(f"{lead}{r['name']} {r['month']['profit']:+.2f}"
                     f"{' below' if r.get('below') else ''} ({rng})")
    top = out["sets"][0] if out["sets"] else None
    if top and top["predicted"]:
        p = top["predicted"]
        c = p.get("corrected")
        parts.append(f"best rule set #{top['id']}: about {c:+.2f} a month after the reality check"
                     if c is not None else f"best rule set #{top['id']}: about {p['profit']:+.2f}")
    nt.record("forecast", "Forecast v2 is ready", detail=fit(parts),
              ok=not any(r.get("below") for r in rooms), meta={"made_at": out["made_at"]})


# ------------------------------------------------------------- what-if
def _whatif_path() -> Path:
    return home() / "whatif.json"


def whatifs() -> dict:
    try:
        return json.loads(_whatif_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _whatif_save(d: dict) -> None:
    f2.publish(_whatif_path(), json.dumps(d, separators=(",", ":"), allow_nan=False))


_STARTING: set = set()            # what-if ids this process is asking GitHub for right now


def _whatif_edit(rid: str, fields: dict, run: int | None = None) -> None:
    """ONE what-if's fields saved over a FRESH read, under the lock (bug hunt,
    round 6): the poll held its own copy of the file across a download of
    minutes and saved it whole, so a what-if asked meanwhile vanished from
    the file while its run went on on GitHub. `run` — only if the record
    still belongs to that run (it may have been asked again since)."""
    with _WHATIF_LOCK:
        w = whatifs()
        rec = w.get(rid)
        if rec is None or (run is not None and rec.get("run") != run):
            return
        rec.update(fields)
        _whatif_save(w)


def whatif(cfg: dict) -> dict:
    """Ask for one rule set. An answer measured on the newest data returns at
    once; otherwise a custom forecast run is started (or the one already
    running for it is reported)."""
    cfg = fr.cfg_of(int(cfg["window_days"]), float(cfg["on_winrate"]), int(cfg["min_trades"]),
                    str(cfg["tp_rule"]), float(cfg.get("max_sl") or 0),
                    **{k: cfg.get(k) for k in fr.OPTION_KEYS if cfg.get(k) not in (None, "", False)},
                    **({"coin_slices": int(cfg["coin_slices"])} if cfg.get("coin_slices") else {}))
    rid = fr.rule_id(cfg)
    st = read().get("ready") or {}
    if not st.get("replay_run") or not st.get("end_ms"):
        return {"id": rid, "status": "no replay yet",
                "why": "the daily Forecast v2 has not finished a replay yet — a what-if needs one"}
    with _WHATIF_LOCK:
        w = whatifs()
        have = w.get(rid)
        same = bool(have) and have.get("end_ms") == st["end_ms"]
        if same and (have.get("status") in ("done", "working")
                     or (have.get("status") == "starting" and rid in _STARTING)):
            return have
        # an earlier start that failed, or was cut off by a restart, may
        # still have reached GitHub: its run is adopted, never asked twice
        since = (have.get("tried_at") or have.get("asked_at")) if same and not have.get("run") else None
        now = time.time()
        rec = {"id": rid, "cfg": cfg, "words": fr.words(cfg), "status": "starting", "run": None,
               "end_ms": st["end_ms"], "asked_at": now, "tried_at": since or now, "result": None,
               "why": "asking GitHub to start it"}
        w[rid] = rec
        _whatif_save(w)
        _STARTING.add(rid)
    # STARTED BEHIND THE ANSWER (bug hunt, round 3): GitHub takes up to a
    # minute to show a dispatched run, and the page must not wait for it
    custom = json.dumps({"id": rid, **cfg}, separators=(",", ":"))
    threading.Thread(target=_start_whatif, args=(rid, st, custom, since),
                     name="forecast-v2-whatif", daemon=True).start()
    return rec


def _start_whatif(rid: str, st: dict, custom: str, since: float | None = None) -> None:
    try:
        run = dispatch(FORECAST_WF, _forecast_inputs(st, "custom", {"custom": custom}),
                       st.get("repo") or slug(), since=since)
        _whatif_edit(rid, {"run": run, "status": "working", "why": "started on GitHub"})
    except Exception as exc:                                   # noqa: BLE001
        _whatif_edit(rid, {"status": "failed",
                           "why": f"could not start it: {type(exc).__name__}: {str(exc)[:200]}"})
    finally:
        _STARTING.discard(rid)


def _cut_starts(now: float) -> list:
    """A what-if left "starting" with no thread of this process asking GitHub
    for it — the site restarted mid-ask — is marked so it can be asked again,
    instead of answering "starting" for ever. Checked UNDER the lock that
    `whatif` adds to _STARTING under, so a start a second old is never cut."""
    cut = []
    with _WHATIF_LOCK:
        w = whatifs()
        for r in w.values():
            if r.get("status") == "starting" and r.get("id") not in _STARTING \
                    and now - float(r.get("asked_at") or 0) > 60:
                r.update(status="failed", why=(
                    "the start was cut off (the site restarted while asking GitHub) — ask "
                    "again: a run it did start is picked up, never started twice"))
                cut.append(r["id"])
        if cut:
            _whatif_save(w)
    return cut


def _reality_of_table() -> dict:
    """The reality-check numbers the rule-set table was corrected with, so a
    what-if's "after the reality check" can be read beside it (bug hunt,
    round 6: it used the live numbers, which move every refresh)."""
    try:
        r = _latest().get("reality") or {}
        if r.get("took") is not None:
            return r
    except (OSError, ValueError):
        pass
    return f2.live()["reality"]["all"]


def _whatifs(st: dict, now: float) -> None:
    from tradingagents import forecast_v2_merge as fm

    _cut_starts(now)
    w = whatifs()
    busy = [r for r in w.values() if r.get("status") == "working" and r.get("run")]
    if not busy or now - float(st.get("whatif_polled") or 0) < POLL_S:
        return
    st["whatif_polled"] = now
    repo = st.get("repo") or slug()
    chain = st.get("phase") in ("replay", "base", "options")
    also = (f" — the daily Forecast v2's {st.get('phase')} run is on GitHub too" if chain else "")
    for r in busy:
        run = int(r["run"])
        try:
            s = run_status(run, repo)
            if s["status"] != "completed":
                _whatif_edit(r["id"], {"why": run_words(s, also)}, run=run)
                continue
            if s["conclusion"] != "success":
                _whatif_edit(r["id"], {"status": "failed", "why": f"the run ended {s['conclusion']}"},
                             run=run)
                continue
            art = download(run, repo, "forecast-*")
            try:
                metas, packs = fm.load(art)
                try:
                    start = metas[0]["start"]
                    start_ms = int(dt.datetime(*map(int, start.split("-"))).timestamp() * 1000)
                    months, complete = fm.months_of(start_ms, int(metas[0]["end_ms"]))
                    result = fm.summarize(0, metas, packs, start_ms, int(metas[0]["end_ms"]),
                                          months, complete, _reality_of_table())
                finally:
                    # CLOSED BEFORE THE DELETE (bug hunt, round 14): an open
                    # .npz cannot be deleted on Windows, and ignore_errors hid
                    # it — #2F39EAEC's 20 .npz files stayed on disk at 8:35pm
                    # while its .json files went
                    for pk in packs:
                        pk.close()
            finally:
                shutil.rmtree(art, ignore_errors=True)
            _whatif_edit(r["id"], {"result": result, "status": "done", "why": "", "done_at": now},
                         run=run)
        except Exception as exc:                               # noqa: BLE001
            # one what-if GitHub could not answer never stops the others
            _whatif_edit(r["id"], {"why": f"could not read it from GitHub at this check: "
                                          f"{type(exc).__name__}: {str(exc)[:160]}"}, run=run)


def switch(on: bool) -> dict:
    """The page's on/off box. Off stops the chain dispatching; nothing else.
    Written to its own file, which nothing else writes (see is_on)."""
    f2.publish(_switch_path(), json.dumps({"on": bool(on), "at": time.time()}))
    return read()
