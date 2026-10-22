"""THE CONFLUENCE RESEARCH (Prompt 1), started from this PC (Oct 21, 2026).

The machines run .github/workflows/cq.yml (.github/scripts/cq_shard.py); this
module deals the board between EVERY GitHub account that can run now (three
since Oct 21, 2026 - the 40-machine rule, CLAUDE.md) and starts one run on
each, brings every machine's results home beside the store (G:, never the
system drive), and keeps ~/.tradingagents/cq/progress.json, which a new chat
told "resume Prompt 1" reads first. Design:
docs/superpowers/specs/2026-10-21-confluence-research-design.md.

    python -m tradingagents.cq_search dispatch [label] [--coins A,B] [--luck all|A,B]
                                      [--search 500,100,10] [--state NAME] [--force]
    python -m tradingagents.cq_search redo <state-name> <owner/repo>
    python -m tradingagents.cq_search collect [state-name]
    python -m tradingagents.cq_search progress

Never dispatched between 12:45am and 5:00am (this PC's clock): the nightly
room re-test (1:00am) and backtest update (1:31am) need every machine;
`--force` is for a person who knows they are not running.
"""
from __future__ import annotations

import datetime as _dt
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

WORKFLOW = "cq.yml"
SHARDS = 20                       # machines per account (MACHINES_PER_ACCOUNT)
TIMEFRAMES = "15m,30m,1h,4h,1d"
SEARCH = "500,100,10"
ARTIFACTS = ("cq-out-*",)
STATE = "state.json"
QUIET = ((0, 45), (5, 0))         # the nightly jobs' hours: no dispatch


def home() -> Path:
    """Beside the v1 store's folder on the store's drive."""
    from tradingagents import stores

    p = Path(stores.V1.home) / "cq"
    p.mkdir(parents=True, exist_ok=True)
    return p


def title_of(label: str) -> str:
    """The run-name cq.yml gives a dispatch - how its run is found."""
    return f"Confluence research · {label}"


def _gh(*args: str, timeout: int = 120) -> str:
    from tradingagents import cloud_sweep as cs

    return cs._gh(*args, timeout=timeout)


def _runs(repo: str, limit: int = 10) -> list:
    return json.loads(_gh("run", "list", "--repo", repo, "--workflow", WORKFLOW,
                          "--limit", str(limit), "--json", "databaseId,displayTitle,createdAt"))


def _listed(repo: str, title: str, since: float) -> int | None:
    """A run of `title` on `repo` created at or after `since`, or None: GitHub
    can take a dispatch and list it late, and a run nobody adopts is twenty
    machines measuring coins nobody collects."""
    for r in _runs(repo, 30):
        if str(r.get("displayTitle", "")).strip() != title:
            continue
        made = _dt.datetime.fromisoformat(str(r["createdAt"]).replace("Z", "+00:00")).timestamp()
        if made >= since - 5:
            return int(r["databaseId"])
    return None


def _start(repo: str, inputs: dict) -> int:
    """Start cq.yml on `repo` and return ITS run id, found by its title."""
    want = title_of(inputs["label"])
    before = {int(r["databaseId"]) for r in _runs(repo)}
    args = ["workflow", "run", WORKFLOW, "--repo", repo]
    for k, v in inputs.items():
        args += ["-f", f"{k}={v}"]
    _gh(*args)
    for _ in range(45):
        time.sleep(2)
        for r in _runs(repo):
            if int(r["databaseId"]) not in before and str(r["displayTitle"]).strip() == want:
                return int(r["databaseId"])
    raise RuntimeError(f"the {WORKFLOW} run on {repo} ({want}) did not appear within 90 seconds")


def quiet_hours(now: float | None = None) -> bool:
    """Between 12:45am and 5:00am on this PC's clock."""
    t = _dt.datetime.fromtimestamp(time.time() if now is None else now)
    m = t.hour * 60 + t.minute
    (h0, m0), (h1, m1) = QUIET
    return h0 * 60 + m0 <= m < h1 * 60 + m1


def _luck_for(luck: str, pile: list) -> str:
    """One account's share of the luck coins: "all", or the named coins in its pile."""
    if luck.strip().lower() == "all":
        return "all"
    want = {c.strip().upper().replace("_USDT", "") for c in luck.split(",") if c.strip()}
    return ",".join(c.replace("_USDT", "") for c in pile if c.replace("_USDT", "") in want)


def _save(state_name: str, state: dict) -> None:
    tmp = home() / f"{state_name}.tmp"
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(home() / state_name)


def progress(stage: str | None = None, *, run: tuple | None = None, **extra) -> dict:
    """~/.tradingagents/cq/progress.json, merged and swapped whole: where
    Prompt 1 stands (`stage`, with a dated log line), each run's ids and coins
    (`runs`), and what the reader found. An unreadable file is kept aside,
    never overwritten."""
    from tradingagents.positions_view import fmt_when

    p = home() / "progress.json"
    cur: dict = {"prompt": 1, "runs": {}, "log": []}
    if p.exists():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
        except Exception:                                      # noqa: BLE001
            p.replace(p.with_name(f"progress.unreadable-{int(time.time())}.json"))
    now = time.time()
    if stage:
        cur["stage"] = stage
        cur.setdefault("log", []).append(f"{fmt_when(now)} {stage}")
    if run:
        cur.setdefault("runs", {})[run[0]] = run[1]
    cur.update(extra)
    cur["updated"] = fmt_when(now)
    tmp = p.with_name("progress.tmp")
    tmp.write_text(json.dumps(cur, indent=1, default=str), encoding="utf-8")
    tmp.replace(p)
    return cur


def dispatch(label: str | None = None, *, coins: list | None = None, luck: str = "",
             search: str = SEARCH, base: float = 5.0, timeframes: str = TIMEFRAMES,
             state_name: str = STATE, force: bool = False, now: float | None = None) -> dict:
    """Deal the board (the whole market, or `coins`) between every account
    that can run now (round robin, cloud_sweep.split_coins) and start one run
    on each. An account that refuses, or cannot be brought up to this code,
    is NAMED and the others still run; its share is kept for `redo`."""
    from tradingagents import cloud_sweep as cs, forecast_v2_daily as fd
    from tradingagents.positions_view import fmt_when

    if quiet_hours(now) and not force:
        raise RuntimeError("not dispatched: between 12:45am and 5:00am the nightly room "
                           "re-test and backtest update need every machine")
    ready, refused = fd.fleets_now()
    if not ready:
        raise RuntimeError("no GitHub account can run the research: " + "; ".join(refused))
    board = (sorted({c if c.endswith("_USDT") else f"{c}_USDT" for c in coins}) if coins
             else fd.market())
    piles = cs.split_coins(board, len(ready))
    t0 = time.time()
    label = label or fmt_when(t0)
    origin = cs.origin_fleet()
    runs, named, dealt = {}, list(refused), {}
    for k, (repo, pile) in enumerate(zip(ready, piles, strict=False)):
        if not pile:
            continue
        inputs = {"shards": str(min(SHARDS, len(pile))), "timeframes": timeframes,
                  "coin_list": ",".join(pile), "base": f"{base:g}",
                  "label": f"{label} · {k + 1} of {len(ready)}",
                  "luck": _luck_for(luck, pile), "search": search}
        dealt[repo] = inputs
        if repo != origin:
            drift = cs.sync_fleet(repo)
            if drift:
                named.append(f"{repo}: not brought up to this code ({drift})")
                continue
        try:
            runs[repo] = {"run": _start(repo, inputs), "coins": len(pile),
                          "label": inputs["label"], "coin_list": list(pile)}
        except Exception as exc:                               # noqa: BLE001
            named.append(f"{repo}: {str(exc)[:160]}")
    state = {"label": label, "started": t0, "started_at": fmt_when(t0), "base": base,
             "coins": len(board), "luck": luck, "search": search, "timeframes": timeframes,
             "runs": runs, "refused": named, "dealt": dealt}
    _save(state_name, state)
    progress(f"dispatched {state_name}: {len(runs)} run(s), {len(board)} coin(s)",
             run=(Path(state_name).stem, {"state": state_name, "label": label,
                                          "runs": {r: v["run"] for r, v in runs.items()},
                                          "refused": named, "coins": len(board)}))
    return state


def redo(state_name: str, repo: str) -> dict:
    """Start ONE account's share again by itself - the account GitHub refused,
    never the whole run. An account that already has a run is refused by
    name: two runs would measure its coins twice."""
    from tradingagents import cloud_sweep as cs

    state = json.loads((home() / state_name).read_text(encoding="utf-8"))
    if repo in state.get("runs", {}):
        raise ValueError(f"{repo} already has run {state['runs'][repo]['run']} in {state_name}")
    inputs = dict((state.get("dealt") or {}).get(repo) or {})
    if not inputs:
        raise ValueError(f"{state_name} dealt no share to {repo}")
    pile = inputs["coin_list"].split(",")
    run = _listed(repo, title_of(inputs["label"]), float(state.get("started") or 0))
    if run is None:
        if repo != cs.origin_fleet():
            drift = cs.sync_fleet(repo)
            if drift:
                raise RuntimeError(f"{repo}: not brought up to this code ({drift})")
        run = _start(repo, inputs)
    state.setdefault("runs", {})[repo] = {"run": run, "coins": len(pile),
                                          "label": inputs["label"], "coin_list": pile}
    state["refused"] = [x for x in state.get("refused", []) if not x.startswith(repo + ":")]
    _save(state_name, state)
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


def collect(state_name: str = STATE) -> dict:
    """Bring a run home (every account) and say what it measured: the
    folders, and the coverage - coins no machine reached and every failed
    pair, NAMED (CLAUDE.md rule 20)."""
    from tradingagents import cpw_search as cpw, pro_search as ps

    state = json.loads((home() / state_name).read_text(encoding="utf-8"))
    unfinished = []
    for repo, r in state["runs"].items():
        st = json.loads(_gh("run", "view", str(r["run"]), "--repo", repo, "--json", "status"))
        if st.get("status") != "completed":
            unfinished.append(f"{repo} run {r['run']} is {st.get('status')}")
    if unfinished:
        raise RuntimeError("not collected, still running: " + "; ".join(unfinished))
    roots = [download(int(r["run"]), repo) for repo, r in state["runs"].items()]
    dealt = state.get("dealt") or {}
    board = sorted({c for x in dealt.values() for c in str(x.get("coin_list", "")).split(",") if c})
    report = ps.read_json_parts(roots, "cq-report-*.json", "report")
    summary = {"label": state.get("label"),
               "runs": {k: v["run"] for k, v in state["runs"].items()},
               "roots": [str(r) for r in roots], "coverage": cpw.coverage(board, report)}
    stem = Path(state_name).stem
    (home() / f"{stem}-collected.json").write_text(json.dumps(summary, indent=1),
                                                    encoding="utf-8")
    cov = summary["coverage"]
    progress(f"collected {state_name}: {cov['reached']} of {cov['board']} coin(s), "
             f"{cov['pairs_ok']} coin+timeframe(s) ok, {len(cov['pairs_failed'])} failed",
             run=(stem, {"state": state_name, "label": state.get("label"),
                         "runs": summary["runs"], "collected": f"{stem}-collected.json",
                         "reached": cov["reached"], "board": cov["board"]}))
    return summary


def _arg(args: list, flag: str, default=None):
    if flag in args:
        i = args.index(flag)
        val = args[i + 1]
        del args[i:i + 2]
        return val
    return default


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "dispatch":
        coins = _arg(a, "--coins")
        luck = _arg(a, "--luck", "")
        srch = _arg(a, "--search", SEARCH)
        state = _arg(a, "--state", STATE)
        force = "--force" in a
        a = [x for x in a if x != "--force"]
        print(json.dumps(dispatch(a[1] if len(a) > 1 else None,
                                  coins=coins.split(",") if coins else None, luck=luck,
                                  search=srch, state_name=state, force=force), indent=2))
    elif a and a[0] == "redo":
        print(json.dumps(redo(a[1], a[2]), indent=2))
    elif a and a[0] == "collect":
        print(json.dumps(collect(a[1] if len(a) > 1 else STATE), indent=2))
    elif a and a[0] == "progress":
        print((home() / "progress.json").read_text(encoding="utf-8"))
    else:
        print("usage: python -m tradingagents.cq_search dispatch [label] [--coins A,B] "
              "[--luck all|A,B] [--search 500,100,10] [--state NAME] [--force] | "
              "redo <state-name> <owner/repo> | collect [state-name] | progress")
