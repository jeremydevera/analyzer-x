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
newest replay the chain used; its answer is kept by rule id with the data it
was measured on, so asking again returns at once.
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


def home() -> Path:
    return f2._home()


def _state_path() -> Path:
    return home() / "state.json"


def read() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"phase": "idle", "on": True}


def _write(st: dict) -> None:
    home().mkdir(parents=True, exist_ok=True)
    tmp = _state_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(st, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    os.replace(tmp, _state_path())


# -------------------------------------------------------------- GitHub
def _gh(*args: str, timeout: int = 120) -> str:
    from tradingagents import cloud_sweep as cs

    return cs._gh(*args, timeout=timeout)


def slug() -> str:
    """The account every run of one chain goes to: a forecast run can only
    read a replay run's artifacts in the SAME repository."""
    from tradingagents import cloud_sweep as cs

    return cs.origin_fleet() or cs.repo_slug()


def dispatch(workflow: str, inputs: dict, repo: str) -> int:
    """Start a workflow and return its run id (`gh workflow run` prints none,
    so wait for a run newer than the last one)."""
    def last() -> int:
        got = json.loads(_gh("run", "list", "--repo", repo, "--workflow", workflow,
                             "--limit", "1", "--json", "databaseId"))
        return int(got[0]["databaseId"]) if got else 0

    before = last()
    args = ["workflow", "run", workflow, "--repo", repo]
    for k, v in inputs.items():
        args += ["-f", f"{k}={v}"]
    _gh(*args)
    for _ in range(30):
        time.sleep(2)
        now = last()
        if now and now != before:
            return now
    raise RuntimeError(f"the {workflow} run did not appear within a minute")


def run_status(run_id: int, repo: str) -> dict:
    d = json.loads(_gh("run", "view", str(run_id), "--repo", repo, "--json",
                       "status,conclusion,jobs,url"))
    jobs = [j for j in d.get("jobs", []) if j.get("name") != "plan"]
    return {"status": d.get("status"), "conclusion": d.get("conclusion"), "url": d.get("url"),
            "machines": len(jobs), "done": sum(1 for j in jobs if j.get("status") == "completed"),
            "failed": [j["name"] for j in jobs if j.get("conclusion") not in (None, "success")]}


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
    from tradingagents import replay_collect as rc

    tot = rc.merge_reports([str(report_dir)])
    end = rc.common_end(tot["spans"])
    if not end:
        raise RuntimeError("the replay's reports name no measured pair")
    return int(end)


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
    if st.get("done_day") == today:
        return False, f"today's Forecast v2 was made at {fmt_when(st.get('done_at') or now)}"
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
    """The supervisor's 30-second call: at most one step of the chain, and
    the what-if runs' polls."""
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
        except Exception as exc:                               # noqa: BLE001
            st.setdefault("whatif_error", f"{type(exc).__name__}: {str(exc)[:200]}")
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
    args += ["--runs", json.dumps(runs)] + ([] if keep else ["--no-keep"])
    with log.open("w", encoding="utf-8") as fh:
        got = subprocess.run(args, stdout=fh, stderr=subprocess.STDOUT, timeout=3600,
                             env={**os.environ, "PYTHONUNBUFFERED": "1"})
    if got.returncode != 0:
        tail = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
        raise RuntimeError(f"the merge ended {got.returncode}: {' | '.join(tail)[:300]}")


def _latest() -> dict:
    return json.loads((home() / "latest.json").read_text(encoding="utf-8"))


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
        run = dispatch(REPLAY_WF, {"shards": SHARDS, "timeframes": "15m,30m,1h,4h,1d",
                                   "coin_list": "", "start": start, "base": 5,
                                   "groups": "all", "write_rule": WRITE_RULE}, repo)
        avoid, fams = skip_lists()
        st.update(phase="replay", repo=repo, replay_run=run, start=start, started_at=now,
                  last_update=rf._update()["when"], avoid=avoid, families=fams,
                  base_run=None, options_run=None, error="", failed_at=0, polled_at=0,
                  why=f"replay {run} started on GitHub at {fmt_when(now)} (about an hour)")
        return
    if now - float(st.get("polled_at") or 0) < POLL_S:
        return
    st["polled_at"] = now
    run_key = {"replay": "replay_run", "base": "base_run", "options": "options_run"}[phase]
    s = run_status(int(st[run_key]), repo)
    if s["status"] != "completed":
        st["why"] = (f"{phase} run {st[run_key]} is working on GitHub: {s['done']} of "
                     f"{s['machines']} machines done")
        return
    if s["conclusion"] != "success" and not (phase == "replay" and s["done"] and
                                             len(s["failed"]) < s["machines"]):
        raise RuntimeError(f"{phase} run {st[run_key]} ended {s['conclusion']} "
                           f"({', '.join(s['failed'][:3]) or 'no machine named'})")
    if phase == "replay":
        rep = download(int(st["replay_run"]), repo, "replay-report-*")
        st["end_ms"] = common_end(rep)
        st["base_run"] = dispatch(FORECAST_WF, _forecast_inputs(st, "base"), repo)
        st.update(phase="base", why=f"forecast run {st['base_run']} (base) started on GitHub")
        return
    if phase == "base":
        art = download(int(st["base_run"]), repo, "forecast-*")
        run_merge(str(art), None, {"replay": st["replay_run"], "base": st["base_run"]}, keep=False)
        out = _latest()
        bases = [s_["cfg"] for s_ in out["sets"] if s_["base"]][:fr.TOP_FOR_OPTIONS]
        rooms = room_rules()
        have = {fr.rule_id(c) for c in bases}
        bases += [c for c in rooms.values() if fr.rule_id(c) not in have]
        st["options_run"] = dispatch(FORECAST_WF, _forecast_inputs(
            st, "options", {"bases": ";".join(fr.encode(c) for c in bases)}), repo)
        st.update(phase="options", base_dir=str(art),
                  why=f"forecast run {st['options_run']} (options) started on GitHub")
        return
    if phase == "options":
        art = download(int(st["options_run"]), repo, "forecast-*")
        run_merge(st["base_dir"], str(art), {"replay": st["replay_run"], "base": st["base_run"],
                                             "options": st["options_run"]}, keep=True)
        out = _latest()
        st.update(phase="done", done_day=dt.date.fromtimestamp(now).isoformat(), done_at=now,
                  options_dir=str(art), why=f"made at {fmt_when(now)}")
        bell(out, f2.live())


# ------------------------------------------------------------- the bell
def bell(out: dict, live: dict) -> None:
    """ONE message a day: the longest winning and losing streaks, the worst
    coin to avoid, and each room's month so far against its prediction."""
    from tradingagents import notifications as nt

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
    top = out["sets"][0] if out["sets"] else None
    if top and top["predicted"]:
        p = top["predicted"]
        c = p.get("corrected")
        parts.append(f"best rule set #{top['id']}: about {c:+.2f} this month after the reality check"
                     if c is not None else f"best rule set #{top['id']}: about {p['profit']:+.2f}")
    nt.record("forecast", "Forecast v2 is ready", detail="; ".join(parts)[:500], ok=True,
              meta={"made_at": out["made_at"]})


# ------------------------------------------------------------- what-if
def _whatif_path() -> Path:
    return home() / "whatif.json"


def whatifs() -> dict:
    try:
        return json.loads(_whatif_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _whatif_save(d: dict) -> None:
    home().mkdir(parents=True, exist_ok=True)
    tmp = _whatif_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(d, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    os.replace(tmp, _whatif_path())


def whatif(cfg: dict) -> dict:
    """Ask for one rule set. An answer measured on the newest data returns at
    once; otherwise a custom forecast run is started (or the one already
    running for it is reported)."""
    cfg = fr.cfg_of(int(cfg["window_days"]), float(cfg["on_winrate"]), int(cfg["min_trades"]),
                    str(cfg["tp_rule"]), float(cfg.get("max_sl") or 0),
                    **{k: cfg.get(k) for k in fr.OPTION_KEYS if cfg.get(k) not in (None, "", False)},
                    **({"coin_slices": int(cfg["coin_slices"])} if cfg.get("coin_slices") else {}))
    rid = fr.rule_id(cfg)
    st = read()
    if not st.get("replay_run") or not st.get("end_ms"):
        return {"id": rid, "status": "no replay yet",
                "why": "the daily Forecast v2 has not measured a replay yet — a what-if needs one"}
    w = whatifs()
    have = w.get(rid)
    if have and have.get("end_ms") == st["end_ms"] and have.get("status") in ("done", "working"):
        return have
    run = dispatch(FORECAST_WF, _forecast_inputs(
        st, "custom", {"custom": json.dumps(cfg, separators=(",", ":"))}), st.get("repo") or slug())
    rec = {"id": rid, "cfg": cfg, "words": fr.words(cfg), "status": "working", "run": run,
           "end_ms": st["end_ms"], "asked_at": time.time(), "result": None, "why": ""}
    w[rid] = rec
    _whatif_save(w)
    return rec


def _whatifs(st: dict, now: float) -> None:
    from tradingagents import forecast_v2_merge as fm

    w = whatifs()
    busy = [r for r in w.values() if r.get("status") == "working"]
    if not busy or now - float(st.get("whatif_polled") or 0) < POLL_S:
        return
    st["whatif_polled"] = now
    repo = st.get("repo") or slug()
    for r in busy:
        s = run_status(int(r["run"]), repo)
        if s["status"] != "completed":
            r["why"] = f"working on GitHub: {s['done']} of {s['machines']} machines done"
            continue
        if s["conclusion"] != "success":
            r.update(status="failed", why=f"the run ended {s['conclusion']}")
            continue
        art = download(int(r["run"]), repo, "forecast-*")
        metas, packs = fm.load(art)
        start = metas[0]["start"]
        start_ms = int(dt.datetime(*map(int, start.split("-"))).timestamp() * 1000)
        months, complete = fm.months_of(start_ms, int(metas[0]["end_ms"]))
        r["result"] = fm.summarize(0, metas, packs, start_ms, int(metas[0]["end_ms"]), months,
                                   complete, f2.live()["reality"]["all"])
        r.update(status="done", why="", done_at=now)
        shutil.rmtree(art, ignore_errors=True)
    _whatif_save(w)


def switch(on: bool) -> dict:
    """The page's on/off box. Off stops the chain dispatching; nothing else."""
    st = read()
    st["on"] = bool(on)
    _write(st)
    return st
