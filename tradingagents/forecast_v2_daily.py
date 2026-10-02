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
           loosest rule set (WRITE_RULE) — about an hour, on EVERY GitHub
           account at once: the market's coins dealt between them, 20
           machines each (CLAUDE.md, "Every GitHub job uses ALL 40 machines")
  base     .github/workflows/forecast.yml, stage base, each account on ITS
           OWN replay run (a run reads artifacts of its own repository); the
           common end comes from every account's replay-report-<N> artifacts
  options  the same, stage options, on the TOP_FOR_OPTIONS best base sets and
           the rooms' own rules
  done     every account's machines merged into latest.json
           (forecast_v2_merge, account i's machine k numbered i*100 + k), the
           month's first prediction kept, ONE bell message for the day

  An account that refuses a dispatch, or whose run is red on every machine
  twice, is dropped and NAMED; the others go on and the page says the
  numbers cover part of the market.

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
SHARDS = 20                   # machines per ACCOUNT: a free GitHub account runs 20 at once
RUN_KEYS = {"replay": "replay_runs", "base": "base_runs", "options": "options_runs"}
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
    """The account a chain from before the accounts were dealt ran on
    (`origin`) — how a state, a `ready` or a what-if with no account is read."""
    from tradingagents import cloud_sweep as cs

    return cs.origin_fleet() or cs.repo_slug()


def fleets_now() -> tuple[list, list]:
    """`(ready, refused)`: every GitHub account that can run a job now, the
    operator's own (`origin`) first so account 0 is where a one-account chain
    always ran (operator, Oct 02, 2026 3:49pm: "moving forward i want 40
    machines to be used always , i want this setting to be remembered")."""
    from tradingagents import cloud_sweep as cs

    ready, refused = cs.usable_fleets()
    origin = cs.origin_fleet()
    return sorted(ready, key=lambda s: s != origin), refused


def market() -> list:
    """The coins a replay given no list measures (sweep_shard.eligible): every
    `_USDT` contract MEXC is trading now, sorted. Named HERE so the accounts
    can be dealt them — each account's claim board lives in its own
    repository, so two runs left to work the coins out would both measure
    every coin and call it forty machines (cloud_sweep.dispatch_across)."""
    from tradingagents.dataflows import mexc_futures as fx

    raw = fx._get_public(f"{fx.BASE}/api/v1/contract/detail").get("data") or []
    return sorted(x["symbol"] for x in raw
                  if str(x.get("symbol", "")).endswith("_USDT") and int(x.get("state", 1)) == 0)


def owner(repo: str) -> str:
    """"jeremydvera/analyzer-x" -> "jeremydvera", the name the page prints."""
    return str(repo).split("/")[0]


def _on(st: dict, repo: str) -> str:
    """" on <account>" when the chain runs on more than one, else "": a
    one-account chain says exactly what it always said."""
    return f" on {owner(repo)}" if len(st.get("fleets") or []) > 1 else ""


def _ready_of(r: dict) -> dict:
    """A `ready` (the last finished replay) in the per-account shape — one
    kept before the accounts were dealt had one `repo` and `replay_run`."""
    r = dict(r or {})
    if r.get("replay_run") and not r.get("replay_runs"):
        repo = r.pop("repo", None) or slug()
        r["replay_runs"] = {repo: int(r.pop("replay_run"))}
        r.setdefault("fleets", [repo])
    r.pop("repo", None)
    r.pop("replay_run", None)
    return r


def _normalize(st: dict) -> dict:
    """A chain state from before the accounts were dealt — one `repo`,
    `replay_run` / `base_run` / `options_run` and `base_dir` — read as a
    one-account chain, so a chain that was running when this code arrived
    (Oct 02, 2026: replay 37051918240, started 3:06pm) carries on."""
    repo = st.pop("repo", None)
    old = [k for k in ("replay_run", "base_run", "options_run", "base_dir", "options_dir") if k in st]
    if repo or old:
        repo = repo or slug()
        for was, now_key in (("replay_run", "replay_runs"), ("base_run", "base_runs"),
                             ("options_run", "options_runs"), ("base_dir", "base_dirs"),
                             ("options_dir", "options_dirs")):
            v = st.pop(was, None)
            if v and not st.get(now_key):
                st[now_key] = {repo: int(v) if now_key.endswith("runs") else v}
        if not st.get("fleets"):
            st["fleets"] = [repo]
        # a retry count kept per phase becomes that phase's count for the one account
        st["redo"] = {p: (n if isinstance(n, dict) else {repo: int(n)})
                      for p, n in (st.get("redo") or {}).items()}
    if st.get("ready"):
        st["ready"] = _ready_of(st["ready"])
    return st


def _dirs_arg(st: dict, dirs: dict) -> str:
    """{account: folder} as forecast_v2_merge reads it: "0=<dir>;1=<dir>",
    each account by its place in the chain's `fleets` — the place, never the
    order the folders came in, so an account dropped between the base and the
    options run cannot shift the other's machine numbers."""
    order = list(st.get("fleets") or []) or list(dirs)
    return ";".join(f"{order.index(repo) if repo in order else len(order) + i}={d}"
                    for i, (repo, d) in enumerate(dirs.items()))


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
    # THREE MINUTES (Oct 02, 2026): the second account listed its first replay
    # (37060968220) more than 90 seconds after the dispatch
    for _ in range(90):
        time.sleep(2)
        for r in _runs(workflow, repo, 10):
            if int(r["databaseId"]) not in before and same_title(r["displayTitle"], want):
                return int(r["databaseId"])
    raise RuntimeError(f"the {workflow} run ({want[:80]}) did not appear within 3 minutes")


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
    # EVERY ACCOUNT'S base and options runs of the chain under way: the
    # options merge reads every account's base folder
    keep = set(keep) | {str(st.get(k)) for k in ("base_run", "options_run") if st.get(k)} \
        | {str(r) for k in ("base_runs", "options_runs") for r in (st.get(k) or {}).values()}
    dirs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime,
                  reverse=True)
    for d in dirs[KEEP_RUNS:]:
        if d.name not in keep:
            shutil.rmtree(d, ignore_errors=True)


def common_end(report_dir) -> int:
    """The earliest last intraday bar over every machine — the one moment
    every coin reached (replay_collect.common_end, the research's own rule)."""
    return int(read_reports(report_dir)["end_ms"])


def read_reports(report_dir) -> dict:
    """The replay's common end and WHAT IT COVERED — its write rule, signal
    groups, coins and strategies (bug hunt, round 16): the same rule set
    walked forward on two replays gave #562C0147 1,703 July trades on the
    first (2 signal groups, 1,079 coins) and 2,098 on Oct 01, 2026's (4
    groups, 1,092 coins). A prediction is only comparable with a result
    measured over the same strategies, so each one carries this."""
    from tradingagents import replay_collect as rc

    # one folder, or one per account — the common end is over EVERY machine
    dirs = report_dir if isinstance(report_dir, (list, tuple)) else [report_dir]
    tot = rc.merge_reports([str(d) for d in dirs])
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


def _forecast_inputs(st: dict, stage: str, repo: str, extra: dict | None = None) -> dict:
    """One account's forecast run: on THAT account's replay run (a run reads
    the artifacts of its own repository), with the whole chain's common end."""
    rooms = room_rules()
    avoid, fams = st.get("avoid") or [], st.get("families") or []
    return {"source_run": st["replay_runs"][repo], "shards": SHARDS, "end_ms": st["end_ms"],
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
    run GitHub took but listed late (dispatch's `since`). ONE RECORD PER
    DISPATCH (Oct 02, 2026): a step now starts a run on every account, and a
    single record let the second account's attempt overwrite the first's, so
    a tick that died between them would have started the first account's
    20-machine run again."""
    was = st.get("tried") or {}
    if "what" in was:                       # the one-attempt shape kept before
        was = {str(was["what"]): was.get("at")}
    since = was.get(what)
    st["tried"] = {**was, what: since or now}
    # ON DISK BEFORE THE DISPATCH (bug hunt, round 8): the tick writes its
    # state at its end, so a dispatch whose tick then failed to save left no
    # trace, and the next tick started the same run a second time
    _write(st)
    return since


STAGE_RETRIES = 1     # a run red on EVERY machine is started again this many times


def _replay_inputs(start: str, coins: list | None = None) -> dict:
    """`coins` — the account's pile; empty is the whole market, which ONE
    account works out for itself (two never may: see `market`)."""
    return {"shards": SHARDS, "timeframes": "15m,30m,1h,4h,1d", "coin_list": ",".join(coins or []),
            "start": start, "base": 5, "groups": "all", "write_rule": WRITE_RULE}


def _dispatch_replays(st: dict, start: str, now: float) -> tuple[dict, dict, list, str] | None:
    """The day's replay on EVERY account that can run it, each on its own
    pile of the market's coins, dealt round robin (cloud_sweep.split_coins,
    so both piles carry the same mix of stock tokens and young contracts).

    THE DEAL IS SAVED BEFORE THE FIRST DISPATCH and kept until the chain
    starts (`plan`). A refusal is usually GitHub listing a run late — on
    Oct 02, 2026 4:30pm the second account's first replay ever (37060968220)
    took more than the 90 seconds `dispatch` waited — so a refused account
    is asked again on the next try, with the SAME pile (a market listed again
    could deal differently while the other account's run holds its old one),
    and a run GitHub listed late is adopted. Only an account refusing
    STAGE_RETRIES + 1 times is left out, its coins named as lost. Returns
    ({account: run}, {account: coins}, lost, a note), or None when every
    account refused (the day is given up)."""
    from tradingagents import cloud_sweep as cs

    # A DEAL IS TODAY'S: a plan left by a day whose dispatch never got
    # through (the PC off overnight) is never reused — its runs are that
    # day's replays, and the title carries only the month
    day = dt.date.fromtimestamp(now).isoformat()
    plan = st.get("plan") or {}
    if plan.get("start") != start or plan.get("day") != day or not plan.get("piles"):
        ready, refused = fleets_now()
        if not ready:
            raise RuntimeError("no GitHub account can run the replay: "
                               + ("; ".join(refused) or "no GitHub remote found"))
        if len(ready) == 1:
            piles = {ready[0]: []}           # one account works the whole market out itself
        else:
            coins = market()
            if not coins:
                raise RuntimeError("MEXC listed no live contract to deal between the accounts")
            piles = dict(zip(ready, cs.split_coins(coins, len(ready)), strict=False))
        plan = {"start": start, "day": day, "piles": piles, "runs": {}, "tries": {}, "lost": [],
                "refused": refused}
        st["plan"] = plan
        _write(st)
    runs, errors = plan["runs"], []
    for repo, pile in plan["piles"].items():
        if repo in runs or plan["tries"].get(repo, 0) > STAGE_RETRIES:
            continue
        try:
            # THE SAME CODE ON EVERY ACCOUNT, or the halves are not comparable
            drift = cs.sync_fleet(repo)
            if drift:
                print(f"[forecast v2] {drift}", flush=True)
            runs[repo] = dispatch(REPLAY_WF, _replay_inputs(start, pile), repo,
                                  since=_tried(st, f"replay {day} {start} {repo}", now))
            _write(st)                       # started: on disk before the next account is asked
        except Exception as exc:                               # noqa: BLE001
            why = f"{type(exc).__name__}: {str(exc)[:160]}"
            plan["tries"][repo] = plan["tries"].get(repo, 0) + 1
            _write(st)                       # the count survives a tick that never saves
            if plan["tries"][repo] > STAGE_RETRIES:
                plan["lost"].append({"repo": repo, "phase": "replay", "coins": len(pile), "why": why})
                print(f"[forecast v2] {repo} refused the replay {plan['tries'][repo]} times ({why}) — "
                      f"its {len(pile)} coin(s) are not in today's Forecast v2", flush=True)
            else:
                errors.append(f"{owner(repo)}: {why}")
    if errors:
        raise RuntimeError(f"the replay was refused — tried again in {RETRY_S // 60} minutes "
                           f"({'; '.join(errors)})")
    if not runs:
        return None
    note = "".join(f" — not on {r}" for r in plan.get("refused") or [])
    note += "".join(f" — {owner(d['repo'])} refused it ({d['why'][:80]}), its {d['coins']} coins left out"
                    for d in plan["lost"])
    return dict(runs), dict(plan["piles"]), list(plan["lost"]), note


def _named_runs(st: dict, runs: dict) -> str:
    """"37051918240" for one account; "37051918240 on jeremydevera and
    37051918241 on jeremydvera" for two."""
    return " and ".join(f"{run}{_on(st, repo)}" for repo, run in runs.items())


def _drop(st: dict, phase: str, repo: str, why: str) -> None:
    """An account given up for the rest of the chain: its runs taken off every
    later stage, and NAMED — the page says the numbers cover part of the
    market (forecast_v2_merge's `machines` against `of`)."""
    order = list(RUN_KEYS)                    # replay, base, options
    for p in order[order.index(phase):]:      # this stage and every one after it
        (st.get(RUN_KEYS[p]) or {}).pop(repo, None)
    st.setdefault("lost", []).append({"repo": repo, "phase": phase, "why": why,
                                      "coins": int((st.get("coins") or {}).get(repo) or 0)})


def _redo(st: dict, phase: str, repo: str, s: dict, now: float) -> bool:
    """One account's run red on EVERY machine (bug hunt, round 12). Raising
    here re-read the same failed run every RETRY_S for ever: never started
    again, never back to idle, so no later day ran either. It is started
    again STAGE_RETRIES times — that account alone; then the account is
    dropped and named (True: started again, wait for it)."""
    key = RUN_KEYS[phase]
    run = st[key][repo]
    why = (f"{phase} run {run}{_on(st, repo)} ended {s['conclusion']} on every machine "
           f"({', '.join(s['failed'][:3]) or 'no machine named'})")
    redo = st.setdefault("redo", {}).setdefault(phase, {})
    if redo.get(repo, 0) < STAGE_RETRIES:
        wf, inputs = ((REPLAY_WF, _replay_inputs(st["start"], (st.get("piles") or {}).get(repo)))
                      if phase == "replay" else
                      (FORECAST_WF, _forecast_inputs(st, phase, repo, {"bases": st.get("bases") or ""}
                                                     if phase == "options" else None)))
        new = dispatch(wf, inputs, repo, since=_tried(st, f"redo {phase} {run}", now))
        st.pop("tried", None)
        redo[repo] = redo.get(repo, 0) + 1
        st[key][repo] = new
        st["why"] = f"{why} — started again as run {new} (try {redo[repo] + 1} of {STAGE_RETRIES + 1})"
        print(f"[forecast v2] {st['why']}", flush=True)
        return True
    _drop(st, phase, repo, f"{why}, on every try")
    st["last_why"] = why
    return False


def _dispatch_stage(st: dict, stage: str, now: float, extra: dict | None = None) -> None:
    """The base or options run on every account still in the chain, each on
    its own replay. A refusal is usually GitHub being slow to list the run,
    and that account's replay is an hour of twenty machines — so it RAISES,
    the step is tried again after RETRY_S, a run already started is kept (and
    one GitHub listed late is adopted), and only an account refusing
    STAGE_RETRIES + 1 times is dropped and named."""
    key = RUN_KEYS[stage]
    st.setdefault(key, {})
    tries = st.setdefault("refused", {}).setdefault(stage, {})
    errors = []
    for repo in list(st.get("replay_runs") or {}):
        if repo in st[key] or tries.get(repo, 0) > STAGE_RETRIES:
            continue                          # started on an earlier try, or dropped from it
        if stage == "options" and repo not in (st.get("base_runs") or {}):
            continue                          # no base results from that account to build on
        try:
            st[key][repo] = dispatch(FORECAST_WF, _forecast_inputs(st, stage, repo, extra), repo,
                                     since=_tried(st, f"{stage} {st['replay_runs'][repo]}", now))
        except Exception as exc:                               # noqa: BLE001
            why = f"{type(exc).__name__}: {str(exc)[:160]}"
            tries[repo] = tries.get(repo, 0) + 1
            _write(st)                       # the count survives a tick that never saves
            if tries[repo] > STAGE_RETRIES:
                _drop(st, stage, repo, f"refused the {stage} run {tries[repo]} times: {why}")
            else:
                errors.append(f"{owner(repo)}: {why}")
    if errors:
        raise RuntimeError(f"the {stage} run was refused — tried again in {RETRY_S // 60} minutes "
                           f"({'; '.join(errors)})")


def _give_up(st: dict, phase: str, why: str) -> None:
    """Today's chain ends, NAMED; the last finished data stays on the page and
    the next daily update starts a fresh chain."""
    st.update(phase="idle", failed_at=0, redo={}, refused={},
              error=f"{phase}: {why}, on every try — today's Forecast v2 is given up")
    st["why"] = f"{st['error']}; the next daily update starts a new one"
    print(f"[forecast v2] {st['why']}", flush=True)


def _downloads(st: dict, phase: str, pattern: str) -> dict:
    """{account: folder} — every account's run of this phase, downloaded."""
    return {repo: download(int(run), repo, pattern) for repo, run in (st.get(RUN_KEYS[phase]) or {}).items()}


def _merge_runs(st: dict) -> dict:
    """What the merge files under latest.json["runs"]: every account's runs,
    and `shards` = the machines DEALT — every account's twenty, a dropped one
    included — so a chain that lost an account prints "PART OF THE MARKET"."""
    return {"replay": st.get("replay_runs") or {}, "base": st.get("base_runs") or {},
            "options": st.get("options_runs") or {}, "fleets": st.get("fleets") or [],
            "shards": SHARDS * max(1, len(st.get("fleets") or [])), "per_account": SHARDS,
            "missing": st.get("missing") or {}, "lost": st.get("lost") or [],
            "universe": st.get("universe") or {}}


def _step(st: dict, now: float) -> None:
    from tradingagents.positions_view import fmt_when

    if st.get("on") is False:
        st["why"] = "switched off on the Forecast v2 page"
        return
    if st.get("failed_at") and now - float(st["failed_at"]) < RETRY_S:
        return
    _normalize(st)
    phase = st.get("phase") or "idle"
    if phase in ("idle", "done"):
        ok, why = due(now, st)
        st["why"] = why
        if not ok:
            return
        from tradingagents import room_forecasts as rf

        start = first_check(now)
        got = _dispatch_replays(st, start, now)
        if got is None:
            st["started_day"] = dt.date.fromtimestamp(now).isoformat()     # one try a day
            _give_up(st, "replay", "every account refused the replay")
            st.pop("plan", None)
            return
        runs, piles, lost, note = got
        avoid, fams = skip_lists()
        st.pop("tried", None)
        st.pop("plan", None)
        st.update(phase="replay", fleets=list(piles), replay_runs=runs, piles=piles,
                  coins={r: len(p) for r, p in piles.items()}, lost=lost, start=start,
                  started_at=now, started_day=dt.date.fromtimestamp(now).isoformat(),
                  last_update=rf._update()["when"], avoid=avoid, families=fams,
                  base_runs={}, options_runs={}, base_dirs={}, error="", failed_at=0, polled_at=0,
                  missing={}, redo={}, refused={}, bases="",
                  why=f"replay {_named_runs(st | {'fleets': list(piles)}, runs)} started on GitHub at "
                      f"{fmt_when(now)} (about an hour){note}")
        return
    if now - float(st.get("polled_at") or 0) < POLL_S:
        return
    st["polled_at"] = now
    key = RUN_KEYS[phase]
    runs = dict(st.get(key) or {})
    stat = {repo: run_status(int(run), repo) for repo, run in runs.items()}
    if any(s["status"] != "completed" for s in stat.values()):
        st["why"] = "; ".join(f"{phase} run {runs[repo]}{_on(st, repo)}: "
                              + ("finished" if s["status"] == "completed" else run_words(s))
                              for repo, s in stat.items())
        return
    # EVERY ACCOUNT'S RUN OF THIS PHASE FINISHED. SOME MACHINES FAILED, SOME
    # DID NOT (bug hunt, round 3): a run with 19 of 20 machines green is used —
    # its missing machines named in the state and on the page — instead of
    # retried for ever; a run red on EVERY machine is started again, that
    # account alone, then dropped (bug hunt, round 12)
    again = False
    for repo, s in stat.items():                   # every red account in this one round
        if s["conclusion"] != "success" and s["machines"] - len(s["failed"]) <= 0:
            again = _redo(st, phase, repo, s, now) or again
    if again:
        return
    if not st.get(key):
        _give_up(st, phase, st.pop("last_why", f"every account's {phase} run ended red"))
        return
    st.pop("last_why", None)
    used = {repo: s for repo, s in stat.items() if repo in st[key]}
    failed = [f"{owner(repo)}: {n}" if len(st.get("fleets") or []) > 1 else n
              for repo, s in used.items() for n in s["failed"]]
    if failed:
        st.setdefault("missing", {})[phase] = {"of": sum(s["machines"] for s in used.values()),
                                               "failed": failed[:40]}
    if phase == "replay":
        got = read_reports(list(_downloads(st, "replay", "replay-report-*").values()))
        st["end_ms"], st["universe"] = got["end_ms"], got["universe"]
        _dispatch_stage(st, "base", now)
        if not st["base_runs"]:
            _give_up(st, "base", "every account refused the base run")
            return
        st.pop("tried", None)
        # a step that got through clears the error a retry was for (bug hunt,
        # round 11: "last error" stayed on the page after the retry worked)
        st.update(phase="base", error="", failed_at=0,
                  why=f"forecast run {_named_runs(st, st['base_runs'])} (base) started on GitHub")
        return
    if phase == "base":
        _say(st, f"base run {_named_runs(st, st['base_runs'])} finished on GitHub — downloading and "
                 f"adding it up on this PC (a few minutes)")
        dirs = {repo: str(d) for repo, d in _downloads(st, "base", "forecast-*").items()}
        run_merge(_dirs_arg(st, dirs), None, _merge_runs(st), keep=False)
        out = _latest()
        bases = [s_["cfg"] for s_ in out["sets"] if s_["base"]][:fr.TOP_FOR_OPTIONS]
        rooms = room_rules()
        have = {fr.rule_id(c) for c in bases}
        bases += [c for c in rooms.values() if fr.rule_id(c) not in have]
        st["bases"] = ";".join(fr.encode(c) for c in bases)
        st["base_dirs"] = dirs
        _dispatch_stage(st, "options", now, {"bases": st["bases"]})
        if not st["options_runs"]:
            _give_up(st, "options", "every account refused the options run")
            return
        st.pop("tried", None)
        st.update(phase="options", error="", failed_at=0,
                  why=f"forecast run {_named_runs(st, st['options_runs'])} (options) started on GitHub")
        return
    if phase == "options":
        _say(st, f"options run {_named_runs(st, st['options_runs'])} finished on GitHub — downloading "
                 f"and adding up both runs on this PC (a few minutes)")
        dirs = {repo: str(d) for repo, d in _downloads(st, "options", "forecast-*").items()}
        # BOTH STAGES OVER THE SAME ACCOUNTS: the merge keeps the machines the
        # two runs share, and the folders carry each account's place
        base = {repo: d for repo, d in (st.get("base_dirs") or {}).items() if repo in dirs}
        run_merge(_dirs_arg(st, base), _dirs_arg(st, dirs), _merge_runs(st), keep=True)
        out = _latest()
        # THE MERGE'S OWN STAMP (bug hunt, rounds 16-17): "made at 8:49pm" was
        # the tick's start while the card under it said "made 8:54pm" — one
        # event, one time, read from the file the page reads
        made = float(out.get("made_at") or time.time())
        st.update(phase="done", done_day=dt.date.fromtimestamp(made).isoformat(), done_at=made,
                  error="", failed_at=0,
                  options_dirs=dirs, why=f"made at {fmt_when(made)}",
                  # what the what-if box measures on: the LAST FINISHED data,
                  # never a replay still running (bug hunt, round 4) — every
                  # account whose replay finished
                  # .get: a key missing here must never stop a finished day
                  # reaching "done", or the merge re-runs every RETRY_S
                  ready={"replay_runs": dict(st.get("replay_runs") or {}),
                         "fleets": list(st.get("fleets") or []),
                         **{k: st.get(k) for k in ("end_ms", "start", "avoid", "families")}})
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


def _whatif_runs(rec: dict) -> dict:
    """{account: run} of a what-if — one asked before the accounts were dealt
    kept a single `run`, on `origin`."""
    if rec.get("runs"):
        return {k: int(v) for k, v in rec["runs"].items()}
    return {slug(): int(rec["run"])} if rec.get("run") else {}


def _whatif_edit(rid: str, fields: dict, run=None) -> None:
    """ONE what-if's fields saved over a FRESH read, under the lock (bug hunt,
    round 6): the poll held its own copy of the file across a download of
    minutes and saved it whole, so a what-if asked meanwhile vanished from
    the file while its run went on on GitHub. `run` — its run (or its
    {account: run}): only if the record still belongs to it (it may have been
    asked again since)."""
    with _WHATIF_LOCK:
        w = whatifs()
        rec = w.get(rid)
        if rec is None or (run is not None and (rec.get("runs") if isinstance(run, dict)
                                                else rec.get("run")) != run):
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
    st = _ready_of(read().get("ready") or {})
    if not st.get("replay_runs") or not st.get("end_ms"):
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
    """One custom run on EVERY account the finished replay ran on, each on
    its own replay — a what-if over one account's coins would answer about
    half the market. An account refusing fails the what-if, named; asking
    again adopts every run that did start."""
    runs, refused = {}, []
    try:
        for repo in (st.get("replay_runs") or {}):
            try:
                runs[repo] = dispatch(FORECAST_WF, _forecast_inputs(st, "custom", repo, {"custom": custom}),
                                      repo, since=since)
            except Exception as exc:                           # noqa: BLE001
                refused.append(f"{owner(repo)}: {type(exc).__name__}: {str(exc)[:160]}")
        if refused:
            _whatif_edit(rid, {"status": "failed", "runs": runs or None,
                               "why": f"could not start it on {'; '.join(refused)}"})
        else:
            _whatif_edit(rid, {"runs": runs, "status": "working", "why": "started on GitHub"})
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
    busy = [r for r in w.values() if r.get("status") == "working" and (r.get("runs") or r.get("run"))]
    if not busy or now - float(st.get("whatif_polled") or 0) < POLL_S:
        return
    st["whatif_polled"] = now
    chain = st.get("phase") in ("replay", "base", "options")
    also = (f" — the daily Forecast v2's {st.get('phase')} run is on GitHub too" if chain else "")
    for r in busy:
        runs = _whatif_runs(r)
        if not r.get("runs") and st.get("repo"):
            runs = {st["repo"]: int(r["run"])}          # a one-account chain's own record
        mark = r.get("runs") or r.get("run")             # the guard: still this record's run(s)
        try:
            stat = {repo: run_status(run, repo) for repo, run in runs.items()}
            waiting = [s for s in stat.values() if s["status"] != "completed"]
            if waiting:
                _whatif_edit(r["id"], {"why": run_words(waiting[0], also)}, run=mark)
                continue
            red = [f"{owner(repo)} {s['conclusion']}" if len(runs) > 1 else str(s["conclusion"])
                   for repo, s in stat.items() if s["conclusion"] != "success"]
            if red:
                _whatif_edit(r["id"], {"status": "failed", "why": f"the run ended {', '.join(red)}"},
                             run=mark)
                continue
            # every account's machines, account i's machine k numbered i*100 + k
            arts = [(i, download(run, repo, "forecast-*")) for i, (repo, run) in enumerate(runs.items())]
            try:
                metas, packs = fm.load(arts)
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
                for _i, art in arts:
                    shutil.rmtree(art, ignore_errors=True)
            _whatif_edit(r["id"], {"result": result, "status": "done", "why": "", "done_at": now},
                         run=mark)
        except Exception as exc:                               # noqa: BLE001
            # one what-if GitHub could not answer never stops the others
            _whatif_edit(r["id"], {"why": f"could not read it from GitHub at this check: "
                                          f"{type(exc).__name__}: {str(exc)[:160]}"}, run=mark)


def switch(on: bool) -> dict:
    """The page's on/off box. Off stops the chain dispatching; nothing else.
    Written to its own file, which nothing else writes (see is_on)."""
    f2.publish(_switch_path(), json.dumps({"on": bool(on), "at": time.time()}))
    return read()
