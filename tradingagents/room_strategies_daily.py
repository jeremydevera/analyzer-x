"""ROOM STRATEGIES, RE-TESTED EVERY DAY — like UPDATE ALL BACKTESTS.

The operator, Oct 07, 2026, told that "last 4 days" showed nothing because
every saved trade of the 992 kept rule sets ended Oct 02, 2026 8:00am — the
end of the replay prompt 4 found them on: *"what do you mean saved strategy?
it should be updated everyday justd like the backtest"*.

Prompt 4 FINDS winners (docs/FORECAST-PROMPTS.md). This job RE-MEASURES every
winner it kept, once a day, exactly the way prompt 4 measured it — the same
replay start, signal groups and research walk — so a row's numbers reach last
night instead of the day it was found. One step per supervisor tick (api.py,
every 30 seconds, in its own thread), the state beside the store
(room_strategies._home(): ~/.tradingagents/backtest/forecast_v2/retest_state.json):

  idle      due once a local day at or after DUE_HOUR — or at once when the
            PC was off through yesterday's
  replay    .github/workflows/replay.yml on EVERY account, the market's coins
            dealt between them (CLAUDE.md, "Every GitHub job uses ALL 40
            machines"), from FIRST_CHECK with GROUPS, written by the loosest
            rule any kept rule set switches on by (`write_rule_for`) — every
            strategy a kept rule set could pick is written, and nothing a
            stricter one could not
  research  .github/workflows/research.yml on every account over ITS OWN
            replay (`scenarios=file:research/p4/kept.json`, `output=full`),
            the slices raised until each account's 20 machines are busy; one
            common end over every account's replay reports
  merge     every account's share downloaded beside the store (G:) and
            checked WHOLE (room_strategies.check_complete); every kept rule
            set measured in its OWN PROCESS (room_strategies.measure) into
            room_strategies_now.npz, swapped in whole. room_strategies.kept()
            reads a winner's trades and months from it from then on.

NEVER HALF A MARKET. A re-test missing one account's coins would halve every
row's trades with no column saying so, so an account lost at any stage — a
refusal, or a run red after RETRIES restarts — ends the day's re-test, NAMED,
and the last whole re-test stays on the page. Every failure is named in the
state and on the page and tried again after RETRY_S; GitHub is asked at most
every POLL_S; never under pytest.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from tradingagents import room_strategies as rst

ROOT = Path(__file__).resolve().parents[1]
FIRST_CHECK = "2026-07-01"        # prompt 4's own replay start (run 37007971331)
GROUPS = "classic,preset"         # prompt 4's own signal groups (the same run)
DUE_HOUR = 1                      # 1:00am, this PC's clock: the day before is whole
SHARDS = 20                       # machines per ACCOUNT: a free account runs 20 at once
MAX_JOBS = 256                    # GitHub refuses a matrix past this
POLL_S = 120
RETRY_S = 30 * 60
RETRIES = 1                       # a run red on any machine is started again this many times
KEEP_DAYS = 2                     # downloaded days kept beside the store
STALE_S = 20 * 3600               # a day's re-test not done in this long is given up
REPLAY_WF = "replay.yml"
RESEARCH_WF = "research.yml"
_LOCK = threading.Lock()


def home() -> Path:
    return rst._home()


def state_path() -> Path:
    return home() / "retest_state.json"


def work() -> Path:
    p = home() / "retest"
    p.mkdir(parents=True, exist_ok=True)
    return p


def read() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"phase": "idle"}


def _write(st: dict) -> None:
    from tradingagents import forecast_v2 as f2

    f2.publish(state_path(), json.dumps(st, separators=(",", ":"), allow_nan=False))


def list_rel() -> str:
    return f"research/p4/{rst.LIST_NAME}.json"


# ------------------------------------------------------------ the inputs
def write_rule_for(cfgs: list) -> str:
    """The loosest rule any of `cfgs` switches on by: a strategy is written
    when it passes this rule at some check, and a rule set only ever picks a
    strategy that passes its own, stricter line — so each kept rule set sees
    exactly what prompt 4's own, wider replay (wr=40, trades=1) gave it."""
    if not cfgs:
        raise ValueError("no kept room strategy to re-test")
    line = min(float(c["on_winrate"]) for c in cfgs)
    trades = min(int(c["min_trades"]) for c in cfgs)
    wins = sorted({int(c["window_days"]) for c in cfgs})
    return f"wr={line:g},trades={trades},tp=any,windows={'|'.join(map(str, wins))}"


def listed() -> list[dict]:
    """The rule sets in the list a runner reads: research/p4/kept.json as it
    is on `origin/main` (pushed) — a runner checks main out, never this PC's
    working copy. [] when it is not there."""
    for ref in ("origin/main", "HEAD"):
        got = subprocess.run(["git", "show", f"{ref}:{list_rel()}"], cwd=str(ROOT),
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        if got.returncode == 0:
            try:
                return [rst.cfg(*(r[k] for k in rst.DIALS)) for r in json.loads(got.stdout)]
            except (ValueError, KeyError, TypeError):
                return []
    return []


def _replay_inputs(rule: str, coins: list | None) -> dict:
    """`coins` — the account's pile; empty is the whole market, which ONE
    account works out for itself (two never may: forecast_v2_daily.market)."""
    return {"shards": SHARDS, "timeframes": "15m,30m,1h,4h,1d", "coin_list": ",".join(coins or []),
            "start": FIRST_CHECK, "base": 5, "groups": GROUPS, "write_rule": rule}


def _research_inputs(st: dict, repo: str) -> dict:
    return {"source_run": st["replay_runs"][repo], "source_repo": repo,
            "shards": "[" + ",".join(map(str, st["shares"][repo])) + "]",
            "end_ms": int(st["end_ms"]), "scenarios": f"file:{list_rel()}",
            "chunks": int(st["chunks"]), "output": "full"}


# ------------------------------------------------------------ is it due
def due(now: float, st: dict) -> tuple[bool, str]:
    from tradingagents.positions_view import fmt_when

    day = dt.date.fromtimestamp(now)
    today = day.isoformat()
    if st.get("started_day") == today:
        if st.get("phase") == "done":
            return False, f"today's re-test was made at {fmt_when(float(st.get('done_at') or now))}"
        return False, "today's re-test was given up (the last error says why) — tomorrow's starts a new one"
    yesterday = (day - dt.timedelta(days=1)).isoformat()
    hour = dt.datetime.fromtimestamp(now).hour
    if hour < DUE_HOUR and st.get("started_day") == yesterday:
        nxt = dt.datetime.combine(day, dt.time(DUE_HOUR)).timestamp()
        return False, f"the next re-test starts at {fmt_when(nxt)}"
    if not rst._kept_lines():
        return False, "no room strategy kept yet — prompt 4 keeps them"
    if not listed():
        return False, (f"GitHub has no list to re-test: {list_rel()} is not on main "
                       f"(room_strategies.write_list, then commit and push it)")
    return True, "due"


# ------------------------------------------------------------- GitHub
def _f2d():
    from tradingagents import forecast_v2_daily as f2d

    return f2d


def _tried(st: dict, what: str, now: float) -> float | None:
    """When an earlier attempt at THIS dispatch was made — saved ON DISK
    BEFORE the dispatch, so a dispatch GitHub took but listed late is adopted
    on the retry, never started twice (forecast_v2_daily._tried's rule)."""
    was = st.get("tried") or {}
    since = was.get(what)
    st["tried"] = {**was, what: since or now}
    _write(st)
    return since


def _download(run: int, repo: str, pattern: str, dest: Path) -> Path:
    """A run's artifacts beside the store (G:) — and gh's own staging there
    too (TMP), never the system drive (CLAUDE.md, "Big files go where the
    STORE is")."""
    from tradingagents import cloud_sweep as cs

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    tmp = cs._scratch()
    if tmp:
        env["TMP"] = env["TEMP"] = tmp
    got = subprocess.run(["gh", "run", "download", str(run), "--repo", repo, "-p", pattern, "-D", str(dest)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=1800, env=env)
    if got.returncode != 0:
        raise RuntimeError(f"gh run download {run} ({repo}, {pattern}): "
                           f"{(got.stderr or got.stdout or 'failed').strip()[:200]}")
    return dest


def _prune(keep_day: str) -> None:
    days = sorted((d for d in work().iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)
    for d in days[KEEP_DAYS:]:
        if d.name != keep_day:
            shutil.rmtree(d, ignore_errors=True)


def _dir(st: dict, repo: str, what: str) -> Path:
    i = list(st.get("fleets") or []).index(repo)
    return work() / st["day"] / f"account{i}" / what


# ------------------------------------------------------------- one tick
def tick(now: float | None = None) -> dict:
    """The supervisor's 30-second call, in its own thread: at most one step."""
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
        _write(st)
        return {"phase": st.get("phase"), "why": st.get("why", "")}
    finally:
        _LOCK.release()


def _fail(st: dict, now: float, why: str) -> None:
    from tradingagents.positions_view import fmt_when

    st["error"] = f"{st.get('phase', 'idle')}: {why}"
    st["failed_at"] = now
    st["why"] = (f"the {st.get('phase', 'idle')} step failed at {fmt_when(now)} — tried again after "
                 f"{RETRY_S // 60} minutes: {why}")
    print(f"[room strategies re-test] {st['why']}", flush=True)


def _give_up(st: dict, why: str, phase: str | None = None) -> None:
    """Today's re-test ends, NAMED; the last whole re-test stays on the page."""
    st.update(phase="idle", failed_at=0,
              error=f"{phase or st.get('phase')}: {why} — today's re-test is given up")
    st["why"] = f"{st['error']}; tomorrow's starts a new one"
    print(f"[room strategies re-test] {st['why']}", flush=True)


def _say(st: dict, why: str) -> None:
    """Where the job is, ON DISK before a slow step."""
    st["why"] = why
    try:
        _write(st)
    except OSError as exc:
        print(f"[room strategies re-test] could not save the status: {exc!r}", flush=True)


def _on(st: dict, repo: str) -> str:
    return f" on {repo.split('/')[0]}" if len(st.get("fleets") or []) > 1 else ""


def _named(st: dict, runs: dict) -> str:
    return " and ".join(f"{run}{_on(st, repo)}" for repo, run in runs.items())


def _start(st: dict, now: float) -> None:
    """The day's replay on every account, each on its own pile of the market.
    The deal is SAVED before the first dispatch, so a retry re-asks a refusing
    account with the SAME pile and adopts any run GitHub did take."""
    from tradingagents import cloud_sweep as cs
    from tradingagents.positions_view import fmt_when

    f2d = _f2d()
    today = dt.date.fromtimestamp(now).isoformat()
    plan = st.get("plan") or {}
    if plan.get("day") != today:
        cfgs = listed()
        ready, refused = f2d.fleets_now()
        if not ready:
            raise RuntimeError("no GitHub account can run the replay: " + ("; ".join(refused) or "none found"))
        piles = ({ready[0]: []} if len(ready) == 1
                 else dict(zip(ready, cs.split_coins(f2d.market(), len(ready)), strict=False)))
        kept_ids = {w["id"] for w in rst._kept_lines()}
        listed_ids = {rst.sid(c) for c in cfgs}
        plan = {"day": today, "piles": piles, "runs": {}, "tries": {}, "refused": refused,
                "rule": write_rule_for(cfgs), "listed": len(listed_ids),
                "unlisted": len(kept_ids - listed_ids)}
        st["plan"] = plan
        _write(st)
    errors = []
    for repo, pile in plan["piles"].items():
        if repo in plan["runs"]:
            continue
        try:
            # THE SAME CODE ON EVERY ACCOUNT, or the halves are not one
            # measure — and an unsynced copy of research.yml carries no
            # run-name, so its run could not even be found (and a retry would
            # start a second one): a failed sync counts as a refusal
            drift = cs.sync_fleet(repo)
            if drift:
                raise RuntimeError(drift)
            plan["runs"][repo] = f2d.dispatch(REPLAY_WF, _replay_inputs(plan["rule"], pile), repo,
                                              since=_tried(st, f"replay {today} {repo}", now))
            _write(st)
        except Exception as exc:                                   # noqa: BLE001
            plan["tries"][repo] = plan["tries"].get(repo, 0) + 1
            _write(st)
            errors.append(f"{repo.split('/')[0]}: {type(exc).__name__}: {str(exc)[:160]}")
    if errors:
        if any(n > RETRIES for n in plan["tries"].values()):
            st["started_day"] = today                # one try a day
            _give_up(st, f"an account refused the replay {RETRIES + 1} times ({'; '.join(errors)})",
                     phase="replay")
            st.pop("plan", None)
            return
        raise RuntimeError(f"the replay was refused — tried again in {RETRY_S // 60} minutes "
                           f"({'; '.join(errors)})")
    runs, piles = dict(plan["runs"]), dict(plan["piles"])
    st.pop("plan", None)
    st.pop("tried", None)
    st.update(phase="replay", day=today, started_day=today, started_at=now, fleets=list(piles),
              piles=piles, coins={r: len(p) for r, p in piles.items()}, replay_runs=runs,
              research_runs={}, refused={}, write_rule=plan["rule"], listed=plan["listed"],
              unlisted=plan["unlisted"], redo={}, error="", failed_at=0, polled_at=0,
              why=f"replay {_named(st | {'fleets': list(piles)}, runs)} started on GitHub at "
                  f"{fmt_when(now)} (about an hour)")


def _red(st: dict, phase: str, stat: dict, now: float) -> bool:
    """A run of `phase` that did not end green on EVERY machine: a missing
    machine is missing coins, so the account's run is started again RETRIES
    times, then the day is given up. True when the step should stop here."""
    f2d = _f2d()
    key = f"{phase}_runs"
    bad = {repo: s for repo, s in stat.items() if s["conclusion"] != "success"}
    if not bad:
        return False
    redo = st.setdefault("redo", {}).setdefault(phase, {})
    for repo, s in bad.items():
        why = (f"{phase} run {st[key][repo]}{_on(st, repo)} ended {s['conclusion']} "
               f"({', '.join(s['failed'][:3]) or 'no machine named'})")
        if redo.get(repo, 0) >= RETRIES:
            _give_up(st, f"{why}, on every try")
            return True
        inputs = (_replay_inputs(st["write_rule"], st["piles"].get(repo)) if phase == "replay"
                  else _research_inputs(st, repo))
        wf = REPLAY_WF if phase == "replay" else RESEARCH_WF
        new = f2d.dispatch(wf, inputs, repo, since=_tried(st, f"redo {phase} {st[key][repo]}", now))
        redo[repo] = redo.get(repo, 0) + 1
        st[key][repo] = new
        st["why"] = f"{why} — started again as run {new}"
        print(f"[room strategies re-test] {st['why']}", flush=True)
    st.pop("tried", None)
    return True


def _step(st: dict, now: float) -> None:
    from tradingagents.positions_view import fmt_when

    if st.get("failed_at") and now - float(st["failed_at"]) < RETRY_S:
        return
    phase = st.get("phase") or "idle"
    if phase in ("idle", "done"):
        ok, why = due(now, st)
        st["why"] = why if not ok else st.get("why", "")
        if ok:
            _start(st, now)
        return
    if now - float(st.get("started_at") or now) > STALE_S:
        _give_up(st, f"it was not done {STALE_S // 3600} hours after it started")
        return
    if now - float(st.get("polled_at") or 0) < POLL_S:
        return
    st["polled_at"] = now
    f2d = _f2d()
    key = f"{phase}_runs"
    runs = dict(st.get(key) or {})
    stat = {repo: f2d.run_status(int(run), repo) for repo, run in runs.items()}
    if any(s["status"] != "completed" for s in stat.values()):
        st["why"] = "; ".join(f"{phase} run {runs[repo]}{_on(st, repo)}: "
                              + ("finished" if s["status"] == "completed" else f2d.run_words(s))
                              for repo, s in stat.items())
        return
    if _red(st, phase, stat, now):
        return
    if phase == "replay":
        _say(st, f"replay {_named(st, runs)} finished — reading where it ended")
        dirs = {repo: _download(int(run), repo, "replay-report-*", _dir(st, repo, "reports"))
                for repo, run in runs.items()}
        got = f2d.read_reports(list(dirs.values()))
        shares = {repo: sorted(rst.replay_shard_sizes(str(run), repo)) for repo, run in runs.items()}
        empty = [repo for repo, sh in shares.items() if not sh]
        if empty:
            _give_up(st, f"replay {_named(st, {r: runs[r] for r in empty})} measured no coin")
            return
        smallest = min(len(x) for x in shares.values())
        chunks = max(1, -(-SHARDS // smallest))
        chunks = min(chunks, max(1, MAX_JOBS // max(len(x) for x in shares.values())))
        st.update(end_ms=got["end_ms"], universe=got["universe"], shares=shares, chunks=chunks)
        errors, tries = [], st.setdefault("refused", {})
        for repo in runs:
            if repo in (st.get("research_runs") or {}):
                continue
            try:
                st.setdefault("research_runs", {})[repo] = f2d.dispatch(
                    RESEARCH_WF, _research_inputs(st, repo), repo,
                    since=_tried(st, f"research {runs[repo]}", now))
                _write(st)
            except Exception as exc:                               # noqa: BLE001
                tries[repo] = tries.get(repo, 0) + 1
                _write(st)
                errors.append(f"{repo.split('/')[0]}: {type(exc).__name__}: {str(exc)[:160]}")
        if errors:
            if any(n > RETRIES for n in tries.values()):
                _give_up(st, f"an account refused the re-test {RETRIES + 1} times ({'; '.join(errors)})")
                return
            raise RuntimeError(f"the re-test was refused — tried again in {RETRY_S // 60} minutes "
                               f"({'; '.join(errors)})")
        st.pop("tried", None)
        st.update(phase="research", error="", failed_at=0,
                  why=f"re-test {_named(st, st['research_runs'])} started on GitHub at {fmt_when(now)} "
                      f"over prices to {fmt_when(st['end_ms'] / 1000)} (about 15 minutes)")
        return
    if phase == "research":
        from tradingagents import forecast_v2_api as f2a

        live = f2a._LIVE["value"]
        reality = ((live or {}).get("reality") or {}).get("all")
        if reality is None:
            st["why"] = ("the re-test finished on GitHub — waiting for the reality check (the "
                         "Forecast page's practice numbers) before adding it up")
            return
        _say(st, f"re-test {_named(st, runs)} finished — downloading and adding it up on this PC "
                 f"(a few minutes)")
        arts = []
        for repo, run in runs.items():
            art = _download(int(run), repo, "research-*", _dir(st, repo, "research"))
            # EVERY job of this account's share, or nothing is published
            rst.check_complete(str(art), str(st["replay_runs"][repo]),
                               reports=str(_dir(st, repo, "reports")))
            arts.append(str(art))
        out = run_merge({"arts": arts, "end_ms": int(st["end_ms"]), "reality": reality,
                         "made_at": now, "out": str(rst.now_path()),
                         "runs": {"replay": st["replay_runs"], "research": runs},
                         "write_rule": st.get("write_rule"), "universe": st.get("universe") or {},
                         "result": str(work() / st["day"] / "merge.json")})
        _prune(st["day"])
        st.update(phase="done", done_at=now, done_day=st["day"], error="", failed_at=0, last=out,
                  why=f"re-tested {out['retested']:,} room strategies at {fmt_when(now)}, prices to "
                      f"{fmt_when(out['end_ms'] / 1000)}")


# ------------------------------------------------------------- the merge
def run_merge(spec: dict) -> dict:
    """`merge` in its OWN PROCESS: 4.3 million trades are never added up
    inside the API (its supervisor restarts crashed runners). A failure is
    raised with the log's tail."""
    log = work() / "merge.log"
    spec_path = Path(spec["result"]).with_name("spec.json")
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    with log.open("w", encoding="utf-8") as fh:
        got = subprocess.run([sys.executable, "-m", "tradingagents.room_strategies_daily", "merge",
                              str(spec_path)], stdout=fh, stderr=subprocess.STDOUT, timeout=3600,
                             cwd=str(ROOT), env={**os.environ, "PYTHONUNBUFFERED": "1"})
    if got.returncode != 0:
        tail = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
        raise RuntimeError(f"the re-test's adding up ended {got.returncode}: {' | '.join(tail)[:300]}")
    return json.loads(Path(spec["result"]).read_text(encoding="utf-8"))


def _named_by(loc, raw):
    """A machine's strategy numbers through its list into the run's one list;
    -1 for any number its list does not hold."""
    import numpy as np

    raw = np.asarray(raw, dtype=np.int64)
    out = np.full(len(raw), -1, np.int64)
    ok = (raw >= 0) & (raw < len(loc))
    out[ok] = np.asarray(loc, dtype=np.int64)[raw[ok]]
    return out


def merge(spec: dict) -> dict:
    """Every kept rule set's trades over every account's machines, measured
    the way prompt 4 measured it (room_strategies.measure, is_winner), written
    WHOLE to spec["out"] — or nothing written at all."""
    import numpy as np

    from tradingagents import forecast_v2 as f2
    from tradingagents import research_merge as rm

    paths = [a for d in spec["arts"] for a in sorted(Path(d).rglob("research-*.json"))]
    metas = [json.loads(a.read_text(encoding="utf-8")) for a in paths]
    packs = [np.load(a.with_suffix(".npz")) for a in paths]
    if not metas:
        raise ValueError(f"no research results under {spec['arts']}")
    end, reality = int(spec["end_ms"]), spec["reality"]
    # WHICH STRATEGY MADE EACH TRADE (operator, Oct 08, 2026: "why can't i
    # see the coin?"): research_shard names it for the TEST part (Sep 01,
    # 2026 on) as an index into its machine's own list — one list for the
    # whole run here, each strategy once (research_merge's own second pass)
    strategies: list = []
    where: dict = {}
    remap = []
    for m in metas:
        loc = []
        for row in m.get("strategies") or []:
            k = where.get(row[0])
            if k is None:
                k = where[row[0]] = len(strategies)
                strategies.append(row)
            loc.append(k)
        remap.append(np.asarray(loc, dtype=np.int64))
    slices: dict = {}
    for i, m in enumerate(metas):
        slices.setdefault(int(m.get("chunk") or 0), []).append(i)
    ids, p4s, es, xs, ps, ss, offs, seen = [], [], [], [], [], [], [0], set()
    for c_ in sorted(slices):
        items = slices[c_]
        rules = metas[items[0]]["rules"]
        for i in items:                       # one rule list per slice, on every machine
            if [r["cfg"] for r in metas[i]["rules"]] != [r["cfg"] for r in rules]:
                raise ValueError(f"slice {c_} holds different rule lists on different machines "
                                 f"({paths[i].name})")
        for j, rule in enumerate(rules):
            rid = rst.sid(rule["cfg"])
            if rid in seen:
                continue
            seen.add(rid)
            parts = [rm.part_trades(packs, items, j, part) for part in ("train", "test")]
            e = np.concatenate([q[0] for q in parts])
            x = np.concatenate([q[1] for q in parts])
            p = np.concatenate([q[2] for q in parts])
            # -1 = a train-part trade, whose strategy the shard never names,
            # or a number outside its machine's own list (never a crash)
            s_test = np.concatenate([_named_by(remap[i], packs[i][f"{j}_test_s"]) for i in items])
            s = np.concatenate([np.full(len(parts[0][0]), -1, np.int64), s_test])
            # BY CLOSE, ties kept in machine order — research_merge's own
            # order, which the worst losing run is counted along (checked
            # Oct 07, 2026 on prompt 4's round 5 artifacts: all 91 rule sets
            # trade for trade identical to the store)
            order = np.argsort(x, kind="stable")
            e, x, p, s = e[order], x[order], p[order], s[order]
            t = np.column_stack([e, x, p]).astype(np.float64) if len(e) else np.zeros((0, 3))
            p4 = rst.measure(t, end, reality)
            p4["winner"], p4["why"] = rst.is_winner(p4)
            ids.append(rid)
            p4s.append(p4)
            es.append((e // 60_000 - rm.T0_MIN).astype(np.int32))
            xs.append((x // 60_000 - rm.T0_MIN).astype(np.int32))
            ps.append(p.astype(np.float32))
            ss.append(s.astype(np.int32))
            offs.append(offs[-1] + len(e))
    total = int(offs[-1])
    if not ids or not total:
        raise ValueError(f"the re-test measured {len(ids)} rule sets and {total} trades — not published")
    # THE SAME MEASURE AS BEFORE, OVER THE DAYS BOTH COVER: prompt 4's trades
    # against today's, up to where prompt 4's replay ended — printed, so a
    # re-test that measured something else is visible on its first day
    old = {w["id"]: w["trades"] for w in rst._kept_lines()}
    old_end = max((float(t[:, 1].max()) for t in old.values() if len(t)), default=0.0)
    was = sum(int((old[i][:, 1] <= old_end).sum()) for i in ids if i in old)
    now_ = sum(int(((xs[k].astype(np.int64) + rm.T0_MIN) * 60_000 <= old_end).sum())
               for k, i in enumerate(ids) if i in old)
    meta = {"made_at": float(spec["made_at"]), "end_ms": end, "runs": spec.get("runs") or {},
            "write_rule": spec.get("write_rule"), "universe": spec.get("universe") or {},
            "retested": len(ids), "trades": total,
            "named": int(sum(int((a >= 0).sum()) for a in ss)),
            "overlap": {"until": int(old_end), "kept": was, "retest": now_},
            "ids": ids, "p4": p4s, "strategies": strategies}
    out = Path(spec["out"])
    tmp = out.with_name(f"{out.name}.{os.getpid()}.tmp")
    with tmp.open("wb") as fh:
        np.savez(fh, e=np.concatenate(es), x=np.concatenate(xs), p=np.concatenate(ps),
                 s=np.concatenate(ss), offs=np.asarray(offs, dtype=np.int64),
                 meta=np.array(json.dumps(meta, allow_nan=False)))
    f2.replace_retry(tmp, out)
    summary = {k: v for k, v in meta.items() if k not in ("ids", "p4", "strategies")}
    if spec.get("result"):
        Path(spec["result"]).write_text(json.dumps(summary), encoding="utf-8")
    print(json.dumps(summary), flush=True)
    return summary


# ------------------------------------------------------------- the page
def status() -> dict:
    """What the Room strategies screen prints about the daily re-test."""
    st = read()
    now = rst.retested().get("meta") or {}
    return {"phase": st.get("phase") or "idle", "why": st.get("why") or "", "error": st.get("error") or "",
            "made_at": now.get("made_at"), "end_ms": now.get("end_ms"), "retested": now.get("retested"),
            "unlisted": int(st.get("unlisted") or 0), "due_hour": DUE_HOUR}


def main(argv: list | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 2 and args[0] == "merge":
        merge(json.loads(Path(args[1]).read_text(encoding="utf-8")))
        return 0
    if args == ["status"]:
        print(json.dumps(status(), indent=1))
        return 0
    print("usage: python -m tradingagents.room_strategies_daily merge <spec.json> | status")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
