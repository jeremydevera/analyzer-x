"""BACKTEST V3 ON GITHUB (Part 2b, Oct 27, 2026), started from this PC.

The machines run .github/workflows/v3.yml (.github/scripts/v3_shard.py); this
module deals the plan's coins between EVERY GitHub account that can run now
(cloud_sweep.split_coins over forecast_v2_daily.fleets_now - three accounts,
60 machines, CLAUDE.md "Every GitHub job uses ALL ... machines"), starts one
run on each, and brings every machine's records home into the v3 store on the
store's drive (`stores.V3.home`, never the system drive), where
`python -m tradingagents.v3_verdicts publish <folder>` judges them pooled.
Plan: docs/superpowers/plans/2026-10-27-backtest-v3-part2b-github.md.

    python -m tradingagents.v3_cloud dispatch <name> [--coins A,B] [--plan FILE] [--force]
    python -m tradingagents.v3_cloud redo <name> <owner/repo>
    python -m tradingagents.v3_cloud collect <name>
    python -m tradingagents.v3_cloud retry <name>
    python -m tradingagents.v3_cloud progress
    python -m tradingagents.v3_cloud parity <folder> <coin> <local-label>

`<name>` is one plain folder name ("pilot", "universe"): the run's state file
(`<name>.json` beside this module's home) and the folder its records land in
(`stores.V3.home/research/<name>`, `v3_research.home`).

* A run is dispatched only with a plan that is COMMITTED and on origin/main
  (every machine reads the plan from its own checkout) and its id travels as
  the workflow's `plan_id`: a machine holding any other plan refuses.
* The state is saved BEFORE the first dispatch and after each one, so a
  dispatch that raised can be found again (`redo` adopts a run GitHub listed
  late, `forecast_v2_daily.dispatch(since=)`), never started twice.
* `collect` lands only records measured under the run's own plan build, risk
  and random-run count, and refuses to land into a folder holding another
  plan's records; every coin it did not land is NAMED: not reached (a share
  GitHub refused), failed (with its error), left out by the machine (with
  why), or refused at landing (with what differs), or unmeasured (claimed by a machine
  that stopped before it finished it: named once, redone by `retry`).
* `retry` redoes only the coins a collected run failed or never reached, into
  the SAME folder (CLAUDE.md: a failed coin is redone alone).

Never dispatched between 12:45am and 5:00am (this PC's clock: the nightly
room re-test and backtest update need every machine; `cq_search.quiet_hours`);
`--force` is for a person who knows they are not running.
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
import time
import zlib
from pathlib import Path

WORKFLOW = "v3.yml"
SHARDS = 20                         # machines per account (MACHINES_PER_ACCOUNT)
ARTIFACTS = ("v3-out-*",)
RUN_TTL_S = 7 * 86400               # a downloaded run folder older than this is swept (collect only)
PLAN_REL = "research/v3/plan.json"
# a record's fields that say WHEN and WHERE it was measured, never WHAT: `parity` ignores them
TIMING = ("seconds", "machine")


def home() -> Path:
    """Beside the v3 store, on the store's drive."""
    from tradingagents import stores

    p = Path(stores.V3.home) / "cloud"
    p.mkdir(parents=True, exist_ok=True)
    return p


def title_of(label: str) -> str:
    """The run-name v3.yml gives a dispatch - how its run is found."""
    return f"Backtest v3 research · {label}"


def _git(*args: str) -> str:
    from tradingagents.v3_universe import PLAN_FILE

    out = subprocess.run(["git", *args], cwd=str(PLAN_FILE.parent.parent.parent),
                         capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {(out.stderr or out.stdout).strip()[:200]}")
    return out.stdout.strip()


def plan_on_main(path: Path, retrying: bool = False) -> str:
    """"" when the plan file at `path` is the one committed on origin/main (what
    every machine's checkout reads); else why not."""
    try:
        here = _git("hash-object", str(path))
        main = _git("rev-parse", f"origin/main:{PLAN_REL}")
    except RuntimeError as exc:
        return f"the committed plan could not be read: {exc}"
    if here != main and retrying:
        return ("the plan this run was dispatched with is no longer the plan on origin/main: a "
                "retry cannot run under another plan - start a new run with the current plan "
                "(the failed coins can be named with --coins)")
    if here != main:
        return (f"{path} is not the plan on origin/main: rebuild it, commit it and push it to "
                "every account first (every machine reads the plan from its own checkout)")
    return ""


def _state_path(name: str) -> Path:
    from tradingagents import v3_research as vrs

    return home() / f"{vrs.plain_label(name)}.json"


def _swap(tmp: Path, p: Path, wait: float = 3.0) -> None:
    """tmp over p, retried for a few seconds: Windows refuses the swap while a reader (the tab,
    another command) has the file open."""
    end = time.time() + wait
    while True:
        try:
            tmp.replace(p)
            return
        except PermissionError:
            if time.time() >= end:
                raise
            time.sleep(0.05)


def _write_whole(p: Path, text: str) -> None:
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    _swap(tmp, p)


def _save(name: str, state: dict) -> None:
    _write_whole(_state_path(name), json.dumps(state, indent=1))


def load_state(name: str) -> dict:
    return json.loads(_state_path(name).read_text(encoding="utf-8"))


def progress(stage: str, **extra) -> dict:
    """home()/progress.json, merged and swapped whole: where the v3 research
    stands, with a dated log line. An unreadable file is kept aside, never
    overwritten."""
    from tradingagents.positions_view import fmt_when

    p = home() / "progress.json"
    cur: dict = {"log": []}
    if p.exists():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            p.replace(p.with_name(f"progress.unreadable-{int(time.time())}.json"))
    now = time.time()
    cur["stage"] = stage
    cur.setdefault("log", []).append(f"{fmt_when(now)} {stage}")
    cur.update(extra)
    cur["updated"] = fmt_when(now)
    _write_whole(p, json.dumps(cur, indent=1, default=str))
    return cur


def _start(repo: str, inputs: dict, since: float | None = None) -> int:
    """Start v3.yml on `repo` and return ITS run id, found by its title; with
    `since`, a run of that title GitHub listed late is adopted instead."""
    from tradingagents import forecast_v2_daily as fd

    return fd.dispatch(WORKFLOW, inputs, repo, since=since)


def _refuse_reuse(name: str) -> None:
    """A name whose runs are still to be collected is never dispatched again: its state would be
    overwritten and the first run's machines forgotten (a run collected is finished)."""
    p = _state_path(name)
    if not p.exists() or (home() / f"{name}-collected.json").exists():
        return
    try:
        runs = json.loads(p.read_text(encoding="utf-8")).get("runs") or {}
    except ValueError:
        raise RuntimeError(f"{p} is unreadable: not overwritten; move it aside first") from None
    if runs:
        raise RuntimeError(f"{name} still has {len(runs)} run(s) going: collect or retry them "
                           "first")


def dispatch(name: str, *, coins: list | None = None, plan_path: Path | str | None = None,
             label: str | None = None, folder: str | None = None, force: bool = False,
             now: float | None = None, retrying: bool = False) -> dict:
    """Deal the plan's coins (or `coins`, every one of them in the plan) between
    every account that can run now and start one run on each. An account that
    refuses, or cannot be brought up to this code, is NAMED and the others still
    run; its share is kept for `redo`."""
    from tradingagents import (
        cloud_sweep as cs,
        cq_search,
        forecast_v2_daily as fd,
        v3_random as vrn,
        v3_research as vrs,
        v3_rules as vr,
        v3_universe as vu,
    )
    from tradingagents.positions_view import fmt_when

    vrs.plain_label(name)
    folder = vrs.plain_label(folder or name)
    _refuse_reuse(name)
    if cq_search.quiet_hours(now) and not force:
        raise RuntimeError("not dispatched: between 12:45am and 5:00am the nightly room "
                           "re-test and backtest update need every machine")
    path = Path(plan_path or vu.PLAN_FILE)
    plan = vu.load(path)
    why = plan_on_main(path, retrying)
    if why:
        raise RuntimeError(f"not dispatched: {why}")
    if coins:
        board = sorted({c if c.endswith("_USDT") else f"{c}_USDT" for c in coins})
        outside = [c for c in board if c not in set(plan["coins"])]
        if outside:
            raise ValueError(f"not in the plan's universe: {', '.join(outside)}")
    else:
        board = list(plan["coins"])
    ready, refused = fd.fleets_now()
    if not ready:
        raise RuntimeError("no GitHub account can run the research: " + "; ".join(refused))
    piles = cs.split_coins(board, len(ready))
    # a finished run's summary under a name being used again would be read as the new run's
    (home() / f"{name}-collected.json").unlink(missing_ok=True)
    t0 = time.time() if now is None else float(now)
    label = label or name
    state = {"name": name, "label": label, "folder": folder, "started": t0,
             "started_at": fmt_when(t0), "plan_id": plan["id"], "plan_end_ms": int(plan["end_ms"]),
             "plan_path": str(path), "risk_usd": vr.RESEARCH_RISK_USD, "runs_per_combo": vrn.RUNS,
             "coins": len(board), "board": board, "runs": {}, "refused": list(refused),
             "dealt": {}}
    for k, (repo, pile) in enumerate(zip(ready, piles, strict=False)):
        state["dealt"][repo] = {"shards": str(min(SHARDS, len(pile))),
                                "coin_list": ",".join(pile),
                                "label": f"{label} · {k + 1} of {len(piles)}",
                                "plan_id": plan["id"]}
    # the plan as dispatched, kept beside the state: research/v3/plan.json may be rebuilt before
    # this run is judged, and its records are judged under THEIR plan (v3_verdicts)
    copy = home() / f"{name}.plan.json"
    shutil.copyfile(path, copy)
    state["plan_copy"] = str(copy)
    _save(name, state)                 # BEFORE any dispatch: a lost save never starts a run twice
    origin = cs.origin_fleet()
    for repo, inputs in state["dealt"].items():
        if repo != origin:
            drift = cs.sync_fleet(repo)
            if drift:
                state["refused"].append(f"{repo}: not brought up to this code ({drift})")
                _save(name, state)
                continue
        try:
            run = _start(repo, inputs)
        except Exception as exc:                               # noqa: BLE001
            state["refused"].append(f"{repo}: {str(exc)[:160]}")
        else:
            state["runs"][repo] = {"run": run, "coins": len(inputs["coin_list"].split(",")),
                                   "label": inputs["label"]}
        _save(name, state)
    progress(f"dispatched {name}: {len(state['runs'])} run(s), {len(board)} coin(s), plan "
             f"{plan['id']}" + (f"; refused: {'; '.join(state['refused'])}"
                                if state["refused"] else ""))
    return state


def redo(name: str, repo: str) -> dict:
    """Start ONE account's share again by itself - the account GitHub refused,
    never the whole run. A share with a run already is refused by name (two
    runs would measure its coins twice); a run GitHub listed late is adopted."""
    from tradingagents import cloud_sweep as cs

    state = load_state(name)
    if repo in state["runs"]:
        raise ValueError(f"{repo} already has run {state['runs'][repo]['run']} in {name}")
    inputs = state["dealt"].get(repo)
    if not inputs:
        raise ValueError(f"{name} dealt no share to {repo}")
    if repo != cs.origin_fleet():
        drift = cs.sync_fleet(repo)
        if drift:
            raise RuntimeError(f"{repo}: not brought up to this code ({drift})")
    run = _start(repo, inputs, since=float(state["started"]))
    state["runs"][repo] = {"run": run, "coins": len(inputs["coin_list"].split(",")),
                           "label": inputs["label"]}
    state["refused"] = [x for x in state["refused"] if not x.startswith(repo + ":")]
    _save(name, state)
    return state


def download(run: int, repo: str) -> Path:
    """One run's artifacts, unpacked in THIS RUN'S OWN folder under home() -
    the store's drive - emptied first."""
    root = home() / f"run-{int(run)}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    cmd = ["gh", "run", "download", str(int(run)), "-R", repo, "-D", str(root)]
    for p in ARTIFACTS:
        cmd += ["-p", p]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=3600)
    return root


def sweep_runs(now: float | None = None) -> list:
    """Remove the downloaded run folders (`run-<id>`, directly in home() and nowhere else) not
    touched for RUN_TTL_S: a killed download leaves one for ever otherwise. Returns the names."""
    cut = (time.time() if now is None else now) - RUN_TTL_S
    gone = []
    for d in home().iterdir():
        if (d.is_dir() and d.name.startswith("run-") and d.name[4:].isdigit()
                and d.stat().st_mtime < cut):
            shutil.rmtree(d, ignore_errors=True)
            gone.append(d.name)
    return gone


def _shards(nums: list) -> str:
    """[0, 1, 2, 5] -> "shards 0-2, 5 (4 machines)"; [3] -> "shard 3"."""
    nums = sorted({n for n in nums if n is not None}, key=lambda n: (not isinstance(n, int), n))
    if len(nums) == 1:
        return f"shard {nums[0]}"
    spans, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and isinstance(nums[j], int) and nums[j + 1] == nums[j] + 1:
            j += 1
        spans.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return f"shards {', '.join(spans)} ({len(nums)} machines)"


def _reports(roots) -> tuple[list, list]:
    """(every machine's report entries, the machines that refused to measure: ONE line per
    account and cause, "account shards 0-19 (20 machines): why")."""
    from tradingagents import pro_search as ps

    entries, causes = [], {}
    for f in ps.files(roots, "v3-report-*.json"):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        entries += d.get("report") or []
        if d.get("refused"):
            m = d.get("machine") or {}
            causes.setdefault((m.get("repo") or "?", str(d["refused"])), []).append(d.get("shard"))
    return entries, [f"{repo} {_shards(nums)}: {why}" for (repo, why), nums in causes.items()]


def _held(root: Path) -> list:
    """The records already in a landing folder: [(coin, plan_id, risk, runs)]."""
    out = []
    for p in sorted(Path(root).glob("*.json.gz")):
        try:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                r = json.load(fh)
        except (OSError, EOFError, ValueError, zlib.error):
            continue                       # named by whoever lands it; never stops a collect
        out.append((r.get("coin"), r.get("plan_id"), r.get("risk_usd"), r.get("runs")))
    return out


def land(state: dict, roots) -> dict:
    """Every machine's records of a finished run into its folder in the v3
    store, and what was not landed, NAMED (see the module doc)."""
    from tradingagents import pro_search as ps, v3_research as vrs

    root = vrs.home(state["folder"])
    want = (state["plan_id"], float(state["risk_usd"]), int(state["runs_per_combo"]))
    other = [f"{c} (plan {p}, risk {r}, {n} runs)" for c, p, r, n in _held(root)
             if (p, float(r or 0), int(n or 0)) != want]
    if other:
        raise RuntimeError(f"not landed: {root} holds records of another plan, risk or run count "
                           f"({', '.join(other[:5])}{' ...' if len(other) > 5 else ''}); collect "
                           "into a new name")
    plan = {"id": state["plan_id"], "end_ms": int(state["plan_end_ms"])}
    entries, machines_refused = _reports(roots)
    board = set(state["board"])
    failed = {e["coin"]: e["error"] for e in entries if e.get("error") and not e.get("unfinished")}
    # a coin a machine claimed and did not finish (the claim cutoff, GitHub's time limit) was NOT
    # MEASURED: named once however many reports hold it, redone by `retry`, never an error that
    # stops the collect and never a measured coin
    unmeasured = {e["coin"]: e["error"] for e in entries if e.get("unfinished")}
    for e in entries:
        if "bytes" in e or e.get("error") and not e.get("unfinished"):
            unmeasured.pop(e["coin"], None)
    # a coin the machine never measured says why (its report entry has no record size); a coin
    # measured into "no family's universe" has a record, which is landed like any other
    left = {e["coin"]: e["why"] for e in entries if e.get("why") and "bytes" not in e}
    for coin in [*failed, *unmeasured]:    # a coin is in ONE bucket: a failure or a placeholder
        left.pop(coin, None)               # outranks "left out"
    for coin in [*failed, *unmeasured, *left]:
        vrs.drop_coin(root, coin)          # DELETE first: never an old record beside a failure
    landed, refused, seen = [], [], set()
    for f in ps.files(roots, "*.json.gz"):
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, EOFError, ValueError, zlib.error) as exc:
            refused.append(f"unreadable record {Path(f).name}: {type(exc).__name__}: "
                           f"{str(exc)[:100]}")
            continue
        coin = rec.get("coin")
        why = vrs.differences(rec, plan, want[2], want[1])
        if coin not in board:
            why = ["not on this run's board", *why]
        if coin in seen:
            why = ["measured twice: the first record is kept", *why]
        if why:
            refused.append(f"{coin}: {'; '.join(why)}")
            continue
        seen.add(coin)
        failed.pop(coin, None)             # a coin that failed once and was redone on a machine
        unmeasured.pop(coin, None)         # a record saved just before the machine was stopped
        left.pop(coin, None)
        vrs.save_coin(root, rec)
        landed.append(coin)
    reached = set(landed) | set(failed) | set(left) | set(unmeasured)
    secs = sorted(float(e["seconds"]) for e in entries if e.get("seconds") is not None)
    size = sum(int(e.get("bytes") or 0) for e in entries)
    return {"folder": str(root), "landed": sorted(landed),
            "not_reached": sorted(board - reached),
            "failed": [f"{c}: {e}" for c, e in sorted(failed.items())],
            "left_out": [f"{c}: {w}" for c, w in sorted(left.items())],
            "unmeasured": [f"{c}: {w}" for c, w in sorted(unmeasured.items())],
            "refused_records": refused, "machines_refused": machines_refused,
            "seconds": ({"median": secs[len(secs) // 2], "max": secs[-1],
                         "total": round(sum(secs), 1)} if secs else None),
            "bytes": size}


def collect(name: str) -> dict:
    """Bring a finished run home from every account and land it (see `land`)."""
    from tradingagents import forecast_v2_daily as fd

    state = load_state(name)
    unfinished = []
    for repo, r in state["runs"].items():
        st = fd.run_status(int(r["run"]), repo)
        if st.get("status") != "completed":
            unfinished.append(f"{repo} run {r['run']} is {st.get('status')}")
    if unfinished:
        raise RuntimeError("not collected, still running: " + "; ".join(unfinished))
    sweep_runs()
    roots, downloads_failed = [], []
    for repo, r in state["runs"].items():
        # one account's download failing names the account and the cause; every other account's
        # records are still landed, and `collect` can be run again for this one
        try:
            roots.append(download(int(r["run"]), repo))
        except subprocess.CalledProcessError as exc:
            said = (exc.stderr or exc.stdout or str(exc)).strip()[-200:] or str(exc)
            downloads_failed.append(f"{repo} run {r['run']}: {said}")
        except (subprocess.TimeoutExpired, OSError) as exc:
            downloads_failed.append(f"{repo} run {r['run']}: {type(exc).__name__}: "
                                    f"{str(exc)[:160]}")
    if not roots:
        raise RuntimeError("not collected, no run could be downloaded: "
                           + "; ".join(downloads_failed))
    got = land(state, roots)
    summary = {"name": name, "label": state["label"], "plan_id": state["plan_id"],
               "runs": {k: v["run"] for k, v in state["runs"].items()},
               "shares_refused": list(state["refused"]), "downloads_failed": downloads_failed,
               "roots": [str(r) for r in roots], **got}
    _write_whole(home() / f"{name}-collected.json", json.dumps(summary, indent=1))
    progress(f"collected {name}: {len(got['landed'])} of {state['coins']} coin(s) landed in "
             f"{got['folder']}; {len(got['not_reached'])} not reached, {len(got['failed'])} "
             f"failed, {len(got['unmeasured'])} unmeasured, {len(got['left_out'])} left out, "
             f"{len(got['refused_records'])} refused"
             + (f", {len(downloads_failed)} download(s) failed: {'; '.join(downloads_failed)}"
                if downloads_failed else "")
             + f" (each named in {name}-collected.json)")
    return summary


def retry(name: str, *, now: float | None = None, force: bool = False,
          abandon: bool = False) -> dict:
    """Redo ONLY the coins a collected run failed or never reached, as a new run
    whose records land in the SAME folder (`<name>-redo<N>`), under the plan
    the run was dispatched with."""
    from tradingagents import v3_research as vrs

    state = load_state(name)
    try:
        summary = json.loads((home() / f"{name}-collected.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"{name} has not been collected: collect it first") from None
    if summary.get("downloads_failed") and not abandon:
        raise RuntimeError(f"{name}: a download failed ({'; '.join(summary['downloads_failed'])})"
                           ": collect it again first - that share may hold the coins a redo would "
                           "measure twice - or pass --abandon to redo them anyway")
    coins = summary["not_reached"] + [x.split(": ", 1)[0]
                                      for x in summary["failed"] + summary.get("unmeasured", [])]
    n = 1
    while _state_path(f"{name}-redo{n}").exists():
        n += 1
    if n > 1 and not (home() / f"{name}-redo{n - 1}-collected.json").exists():
        raise RuntimeError(f"{name}-redo{n - 1} has not been collected: collect it first (a second "
                           "redo would measure its coins twice)")
    root = vrs.home(state["folder"])      # a coin that has landed since needs no redo
    coins = [c for c in dict.fromkeys(coins) if not vrs.coin_file(root, c).exists()]
    if not coins:
        raise ValueError(f"{name}: every coin landed or was left out with why; nothing to redo")
    # the plan the run was dispatched with: once research/v3/plan.json is rebuilt no redo can
    # measure under it any more, and `plan_on_main` refuses by name
    return dispatch(f"{name}-redo{n}", coins=coins, plan_path=state["plan_copy"],
                    label=f"{state['label']} redo {n}", folder=state["folder"], force=force,
                    now=now, retrying=True)


def same_measure(a: dict, b: dict, path: str = "") -> list[str]:
    """Where two records of one coin differ in WHAT they measured - every field
    but those that say when and where (`TIMING`): [] when they agree, else the
    paths that differ. A GitHub record and this PC's of one coin under one plan
    must agree (the pilot's parity check)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k in TIMING:
                continue
            out += same_measure(a.get(k), b.get(k), f"{path}.{k}" if path else str(k))
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            out += same_measure(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [path or "(the record)"]


def parity(folder: str, coin: str, local_label: str) -> list[str]:
    """`same_measure` of the coin's record collected into `folder` and the one
    `python -m tradingagents.v3_research run <coin> --label <local_label>`
    wrote on this PC."""
    from tradingagents import v3_research as vrs

    def one(label):
        with gzip.open(vrs.coin_file(vrs.home(label), coin), "rt", encoding="utf-8") as fh:
            return json.load(fh)

    return same_measure(one(folder), one(local_label))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_cloud",
                                description="Backtest v3 on every GitHub account.")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dispatch")
    d.add_argument("name")
    d.add_argument("--coins", default="")
    d.add_argument("--plan", default=None)
    d.add_argument("--force", action="store_true")
    r = sub.add_parser("redo")
    r.add_argument("name")
    r.add_argument("repo")
    sub.add_parser("collect").add_argument("name")
    t = sub.add_parser("retry")
    t.add_argument("name")
    t.add_argument("--force", action="store_true")
    t.add_argument("--abandon", action="store_true")
    sub.add_parser("progress")
    q = sub.add_parser("parity")
    q.add_argument("folder")
    q.add_argument("coin")
    q.add_argument("local_label")
    a = p.parse_args(argv)
    if a.cmd == "dispatch":
        got = dispatch(a.name, coins=[c for c in a.coins.split(",") if c] or None,
                       plan_path=a.plan, force=a.force)
    elif a.cmd == "redo":
        got = redo(a.name, a.repo)
    elif a.cmd == "collect":
        got = collect(a.name)
    elif a.cmd == "retry":
        got = retry(a.name, force=a.force, abandon=a.abandon)
    elif a.cmd == "parity":
        diff = parity(a.folder, a.coin.upper(), a.local_label)
        print("the same measurement" if not diff else "differs at: " + ", ".join(diff[:20]))
        return 1 if diff else 0
    else:
        f = home() / "progress.json"
        print(f.read_text(encoding="utf-8") if f.exists() else "no run yet")
        return 0
    print(json.dumps(got, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
