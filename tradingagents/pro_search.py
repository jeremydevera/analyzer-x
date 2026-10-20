"""THE PRO TRADER RESEARCH, started from this PC (Oct 20, 2026).

The machines run .github/workflows/pro.yml (.github/scripts/pro_shard.py); this
module deals the market between BOTH GitHub accounts and starts one run on each
(the 40-machine rule, CLAUDE.md), then brings every machine's results home
beside the store, never onto the system drive. Design:
docs/superpowers/specs/2026-10-20-pro-trader-research-design.md.

    python -m tradingagents.pro_search dispatch [label] [--coins A,B,...]
    python -m tradingagents.pro_search collect [state-name]

`--coins` limits the board (the 20-coin pilot); the check run passes a plan
file (`check=`) the machines read from the repository.
"""
from __future__ import annotations

import glob
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

WORKFLOW = "pro.yml"
SHARDS = 20                       # machines per account (MACHINES_PER_ACCOUNT)
TIMEFRAMES = "15m,30m,1h,4h,1d"
ARTIFACTS = ("pro-out-*",)
STATE = "state.json"              # the search
CHECK_STATE = "check.json"        # the check run


def home() -> Path:
    """Beside the v1 store's folder on the store's drive: the dispatch and the
    collect must find one state file whichever store the process serves."""
    from tradingagents import stores

    p = Path(stores.V1.home) / "pro"
    p.mkdir(parents=True, exist_ok=True)
    return p


def title_of(label: str) -> str:
    """The run-name pro.yml gives a dispatch — how its run is found."""
    return f"Pro Trader research · {label}"


def _gh(*args: str, timeout: int = 120) -> str:
    from tradingagents import cloud_sweep as cs

    return cs._gh(*args, timeout=timeout)


def _runs(repo: str, limit: int = 10) -> list:
    return json.loads(_gh("run", "list", "--repo", repo, "--workflow", WORKFLOW,
                          "--limit", str(limit), "--json", "databaseId,displayTitle,createdAt"))


def _start(repo: str, inputs: dict) -> int:
    """Start pro.yml on `repo` and return ITS run id, found by its title."""
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


def dispatch(label: str | None = None, *, coins: list | None = None, base: float = 5.0,
             check: str = "", state_name: str = STATE, timeframes: str = TIMEFRAMES) -> dict:
    """Deal the board (the whole market, or `coins`) between every account that
    can run now (round robin, cloud_sweep.split_coins) and start one run on
    each. An account that refuses, or cannot be brought up to this code, is
    NAMED and the others still run. `check` = the plan file of a check run."""
    from tradingagents import cloud_sweep as cs, forecast_v2_daily as fd
    from tradingagents.positions_view import fmt_when

    ready, refused = fd.fleets_now()
    if not ready:
        raise RuntimeError("no GitHub account can run the research: " + "; ".join(refused))
    board = sorted({c if c.endswith("_USDT") else f"{c}_USDT" for c in coins}) if coins \
        else fd.market()
    piles = cs.split_coins(board, len(ready))
    label = label or fmt_when(time.time())
    origin = cs.origin_fleet()
    runs, named = {}, list(refused)
    for k, (repo, pile) in enumerate(zip(ready, piles, strict=False)):
        if not pile:
            continue
        if repo != origin:
            drift = cs.sync_fleet(repo)
            if drift:
                named.append(f"{repo}: not brought up to this code ({drift})")
                continue
        inputs = {"shards": str(min(SHARDS, len(pile))), "timeframes": timeframes,
                  "coin_list": ",".join(pile), "base": f"{base:g}",
                  "label": f"{label} · {k + 1} of {len(ready)}"}
        if check:
            inputs["check"] = check
        try:
            runs[repo] = {"run": _start(repo, inputs), "coins": len(pile),
                          "label": inputs["label"], "coin_list": list(pile)}
        except Exception as exc:                               # noqa: BLE001
            named.append(f"{repo}: {str(exc)[:160]}")
    state = {"label": label, "started": time.time(), "started_at": fmt_when(time.time()),
             "coins": len(board), "runs": runs, "refused": named,
             **({"check": check} if check else {})}
    tmp = home() / f"{state_name}.tmp"
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(home() / state_name)
    return state


def download(run: int, repo: str) -> Path:
    """One run's artifacts, unpacked in THIS RUN'S OWN folder under home() —
    the store's drive — emptied first (`gh run download` refuses to write over
    a previous attempt's files)."""
    root = home() / f"run-{int(run)}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    cmd = ["gh", "run", "download", str(int(run)), "-R", repo, "-D", str(root)]
    for p in ARTIFACTS:
        cmd += ["-p", p]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=3600)
    return root


def files(roots, pattern: str) -> list:
    """Every machine's file of one kind — never a half-written copy a killed
    machine left (`.tmp`): added in, that machine would count twice."""
    return sorted(f for r in roots for f in glob.glob(str(Path(r) / "**" / pattern),
                                                      recursive=True)
                  if ".tmp" not in Path(f).name)


def read_lines(roots) -> dict:
    """Every machine's measured lines, joined: {names, fields, coins, tfs,
    coin, tf, var, bar, vals, barriers}. Machines that measured a different
    list of settings, fields or stop/targets are refused by their file name."""
    import numpy as np

    out: dict = {}
    parts: dict = {"coin": [], "tf": [], "var": [], "bar": [], "vals": []}
    coins: list = []
    coin_ix: dict = {}
    for f in files(roots, "pro-*.npz"):
        with np.load(f) as z:
            head = {k: [str(x) for x in z[k]] for k in ("names", "fields", "tfs")}
            bars = {k: [tuple(map(float, b)) for b in z[k]] for k in z.files
                    if k.startswith("barriers_")}
            if not out:
                out.update(head, barriers=bars)
            elif head != {k: out[k] for k in head} or bars != out["barriers"]:
                raise ValueError(f"{f}: measured other settings, fields or stop/targets "
                                 f"than the first machine")
            local = [coin_ix.setdefault(str(c), len(coin_ix)) for c in z["coins"]]
            for c in z["coins"]:
                if str(c) not in coins:
                    coins.append(str(c))
            parts["coin"].append(np.asarray(local, dtype=np.int32)[z["coin"]]
                                 if len(z["coin"]) else np.zeros(0, np.int32))
            for k in ("tf", "var", "bar", "vals"):
                parts[k].append(z[k])
    if not out:
        return {}
    out["coins"] = coins
    for k, v in parts.items():
        out[k] = np.concatenate(v) if v else np.zeros(0)
    return out


def read_json_parts(roots, pattern: str, key: str | None = None):
    """Every machine's JSON file of one kind joined: a list (`key` names the
    list inside each file) or a dict."""
    joined: list | dict | None = None
    for f in files(roots, pattern):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        part = d.get(key) if key else d
        if isinstance(part, list):
            joined = (joined or []) + part
        elif isinstance(part, dict):
            joined = {**(joined or {}), **part}
    return joined if joined is not None else ([] if key else {})


def read_trades(roots) -> list:
    """The check run's lines (one per coin, timeframe and setting)."""
    out = []
    for f in files(roots, "pro-trades-*.jsonl"):
        with open(f, encoding="utf-8") as fh:
            out += [json.loads(x) for x in fh if x.strip()]
    return out


def collect(state_name: str = STATE) -> dict:
    """Bring a run home (both accounts) and say what it measured: the folders,
    the coverage (coins of the board no machine reached, every failed pair,
    NAMED)."""
    from tradingagents import cpw_search as cpw

    state = json.loads((home() / state_name).read_text(encoding="utf-8"))
    roots, board = [], []
    for repo, r in state["runs"].items():
        roots.append(download(int(r["run"]), repo))
        board += list(r.get("coin_list") or [])
    report = read_json_parts(roots, "pro-report-*.json", "report")
    summary = {"label": state.get("label"), "runs": {k: v["run"] for k, v in state["runs"].items()},
               "roots": [str(r) for r in roots],
               "coverage": cpw.coverage(board, report)}
    (home() / f"{Path(state_name).stem}-collected.json").write_text(
        json.dumps(summary, indent=1), encoding="utf-8")
    return summary


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "dispatch":
        coins = None
        if "--coins" in args:
            coins = args[args.index("--coins") + 1].split(",")
            args = args[:args.index("--coins")] + args[args.index("--coins") + 2:]
        print(json.dumps(dispatch(args[1] if len(args) > 1 else None, coins=coins), indent=2))
    elif args and args[0] == "collect":
        got = collect(args[1] if len(args) > 1 else STATE)
        cov = got["coverage"]
        got["coverage"] = {**cov, "not_reached": cov["not_reached"][:50],
                           "pairs_failed": cov["pairs_failed"][:50]}
        print(json.dumps(got, indent=2))
    else:
        print("usage: python -m tradingagents.pro_search dispatch [label] [--coins A,B] | "
              "collect [state-name]")
