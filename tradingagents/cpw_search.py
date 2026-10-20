"""THE CRYPTO-PREDICTOR SWITCH SEARCH, started from this PC (Oct 19, 2026).

The operator: "use the strategy and switches and come up with best combination
for all coins", then "use the best combination and see what's setting will
win" and "One run first". The machines run .github/workflows/cpw.yml
(.github/scripts/cpw_shard.py); this module deals the market between BOTH
GitHub accounts and starts one run on each — the 40-machine rule (CLAUDE.md):
each account's claim board lives in its own repository, so two runs left to
find the coins themselves would each measure the whole market.

    python -m tradingagents.cpw_search dispatch [label]
    python -m tradingagents.cpw_search collect

The run ids are kept in <store>/cpw/state.json for the collect, which brings
every machine's results home beside the store (never the system drive), adds
the sums together and names every coin no machine reached.
"""
from __future__ import annotations

import glob
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

WORKFLOW = "cpw.yml"
SHARDS = 20                       # machines per account (MACHINES_PER_ACCOUNT)
TIMEFRAMES = "15m,30m,1h,4h,1d"


def home() -> Path:
    """Beside the v1 store's own folder, on the store's drive, whichever store
    the calling process was started for: the dispatch and the collect must
    find one state file."""
    from tradingagents import stores

    p = Path(stores.V1.home) / "cpw"
    p.mkdir(parents=True, exist_ok=True)
    return p


def title_of(label: str) -> str:
    """The run-name cpw.yml gives a dispatch — how its run is found."""
    return f"Crypto-Predictor search · {label}"


def _gh(*args: str, timeout: int = 120) -> str:
    from tradingagents import cloud_sweep as cs

    return cs._gh(*args, timeout=timeout)


def _runs(repo: str, limit: int = 10) -> list:
    return json.loads(_gh("run", "list", "--repo", repo, "--workflow", WORKFLOW,
                          "--limit", str(limit), "--json", "databaseId,displayTitle,createdAt"))


def _start(repo: str, inputs: dict) -> int:
    """Start cpw.yml on `repo` and return ITS run id, found by its title."""
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


ARTIFACTS = ("cpw-rows-*", "cpw-summary-*")             # the search's
CHECK_ARTIFACTS = ("cpw-trades-*", "cpw-summary-*")      # the check run's
STATE = "state.json"            # the search
CHECK_STATE = "check.json"      # the check run: the winners, every trade kept


def dispatch(label: str | None = None, *, days: int = 30, base: float = 5.0,
             configs: str = "", state_name: str = STATE) -> dict:
    """Deal the exchange's whole market between every account that can run
    now (round robin, cloud_sweep.split_coins) and start one run on each. An
    account that refuses, or cannot be brought up to this code, is NAMED and
    the others still run. With `configs` (name:tf:sl:tp,...) it is the CHECK
    RUN: those settings measured again on every coin with each trade kept,
    its runs saved in `state_name`."""
    from tradingagents import cloud_sweep as cs, forecast_v2_daily as fd
    from tradingagents.positions_view import fmt_when

    ready, refused = fd.fleets_now()
    if not ready:
        raise RuntimeError("no GitHub account can run the search: " + "; ".join(refused))
    coins = fd.market()
    piles = cs.split_coins(coins, len(ready))
    label = label or fmt_when(time.time())
    origin = cs.origin_fleet()
    runs, named = {}, list(refused)
    for k, (repo, pile) in enumerate(zip(ready, piles, strict=False)):
        if repo != origin:
            drift = cs.sync_fleet(repo)
            if drift:
                named.append(f"{repo}: not brought up to this code ({drift})")
                continue
        inputs = {"shards": str(SHARDS), "timeframes": TIMEFRAMES,
                  "coin_list": ",".join(pile), "days": str(days), "base": f"{base:g}",
                  "label": f"{label} · {k + 1} of {len(ready)}"}
        if configs:
            inputs["configs"] = configs
        try:
            runs[repo] = {"run": _start(repo, inputs), "coins": len(pile),
                          "label": inputs["label"],
                          # the account's board: the collect names every coin
                          # of it no machine reached
                          "coin_list": list(pile)}
        except Exception as exc:                               # noqa: BLE001
            named.append(f"{repo}: {str(exc)[:160]}")
    state = {"label": label, "started": time.time(), "started_at": fmt_when(time.time()),
             "coins": len(coins), "runs": runs, "refused": named,
             **({"configs": configs} if configs else {})}
    tmp = home() / f"{state_name}.tmp"
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(home() / state_name)
    return state


# ------------------------------------------------- bringing the results home

FIELDS = ("pairs", "pairs_up", "trades", "wins", "profit",
          "l_pairs", "l_pairs_up", "l_trades", "l_wins", "l_profit")


def download(run: int, repo: str, patterns: tuple = ARTIFACTS) -> Path:
    """One run's artifacts, unpacked in THIS RUN'S OWN folder under home() —
    the store's drive (CLAUDE.md: big files go where the store is, never the
    system drive), emptied first because `gh run download` refuses to write
    over a previous attempt's files."""
    root = home() / f"run-{int(run)}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    cmd = ["gh", "run", "download", str(int(run)), "-R", repo, "-D", str(root)]
    for p in patterns:
        cmd += ["-p", p]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=1800)
    return root


def read_machines(roots: list) -> dict:
    """Every machine's sums added together: {names, fields, machines,
    tf: {tf: array setting x stop/target x field}, barriers: {tf: [(sl, tp)]}}.
    A machine that measured a different list of settings, fields or
    stop/target pairs is REFUSED by its file name — added in, it would put
    one setting's numbers under another's name."""
    import numpy as np

    out: dict = {"names": None, "fields": None, "machines": 0, "tf": {}, "barriers": {}}
    # never a half-written copy: a machine killed inside its save leaves
    # cpw-<N>.npz.tmp.npz beside the real file, and the upload's pattern takes
    # it too — added in, that machine would count twice
    files = sorted(f for r in roots for f in glob.glob(str(Path(r) / "**" / "cpw-*.npz"),
                                                       recursive=True)
                   if ".tmp" not in Path(f).name)
    for f in files:
        with np.load(f) as z:
            names = [str(x) for x in z["names"]]
            fields = [str(x) for x in z["fields"]]
            if out["names"] is None:
                out["names"], out["fields"] = names, fields
            if names != out["names"] or fields != out["fields"]:
                raise ValueError(f"{f}: measured a different list of settings or "
                                 f"fields than the first machine")
            for key in z.files:
                if not key.startswith("tf_"):
                    continue
                tf = key[3:]
                bars = [(float(a), float(b)) for a, b in z[f"barriers_{tf}"]]
                if tf in out["barriers"] and bars != out["barriers"][tf]:
                    raise ValueError(f"{f}: measured {tf} at different stop/target pairs")
                out["barriers"][tf] = bars
                arr = np.asarray(z[key], dtype=float)
                out["tf"][tf] = arr.copy() if tf not in out["tf"] else out["tf"][tf] + arr
        out["machines"] += 1
    return out


def read_reports(roots: list) -> list:
    """Every machine's line per coin and timeframe it attempted."""
    rep: list = []
    for r in roots:
        for f in sorted(glob.glob(str(Path(r) / "**" / "cpw-report-*.json"), recursive=True)):
            rep += json.loads(Path(f).read_text(encoding="utf-8")).get("report") or []
    return rep


def read_rows(roots: list) -> list:
    """The rows the machines kept (the best of each strategy per pair)."""
    rows: list = []
    for r in roots:
        for f in sorted(glob.glob(str(Path(r) / "**" / "rows-*.jsonl"), recursive=True)):
            with open(f, encoding="utf-8") as fh:
                rows += [json.loads(line) for line in fh if line.strip()]
    return rows


def coverage(board: list, report: list) -> dict:
    """What the machines actually measured, out loud (CLAUDE.md rule 20): the
    coins of the board no machine reached, and every pair that failed, NAMED."""
    reached = {str(e.get("coin")) for e in report}
    coins = [str(c).replace("_USDT", "") for c in board]
    failed = [f"{e.get('coin')} {e.get('tf')}: {e['error']}" for e in report if e.get("error")]
    ok = sum(1 for e in report if not e.get("error") and e.get("tf") not in (None, "*"))
    return {"board": len(coins), "reached": sum(1 for c in coins if c in reached),
            "not_reached": [c for c in coins if c not in reached],
            "pairs_ok": ok, "pairs_failed": failed}


def strategy_of(name: str) -> str:
    """cp_st_f0u0h0x0i0d0 -> "st"."""
    return str(name).split("_")[1]


def cells(merged: dict) -> list:
    """One line per setting x timeframe x stop/target that traded on at least
    one coin — the market-wide sums. SL and TP in percent, as every screen
    prints them."""
    idx = {f: k for k, f in enumerate(merged["fields"])}
    out = []
    for tf, arr in merged["tf"].items():
        for i, name in enumerate(merged["names"]):
            for k, (sl, tp) in enumerate(merged["barriers"][tf]):
                c = arr[i, k]
                if c[idx["pairs"]] <= 0:
                    continue
                trades, wins = int(c[idx["trades"]]), int(c[idx["wins"]])
                out.append({
                    "name": name, "strategy": strategy_of(name), "tf": tf,
                    "sl": round(sl * 100, 4), "tp": round(tp * 100, 4),
                    "pairs": int(c[idx["pairs"]]), "pairs_up": int(c[idx["pairs_up"]]),
                    "trades": trades, "wins": wins, "losses": trades - wins,
                    "profit": round(float(c[idx["profit"]]), 2),
                    "listed": {"pairs": int(c[idx["l_pairs"]]),
                               "pairs_up": int(c[idx["l_pairs_up"]]),
                               "trades": int(c[idx["l_trades"]]),
                               "wins": int(c[idx["l_wins"]]),
                               "profit": round(float(c[idx["l_profit"]]), 2)}})
    return out


def best_by_setting(cells_: list) -> dict:
    """(setting, timeframe) -> its most profitable stop/target, market-wide."""
    best: dict = {}
    for c in cells_:
        key = (c["name"], c["tf"])
        if key not in best or c["profit"] > best[key]["profit"]:
            best[key] = c
    return best


def collect() -> dict:
    """Bring both runs home, add them up and write <home>/merged/: sums.npz
    (every machine's sums added), report.json (what was measured and what was
    not, named) and rows.jsonl (every kept row)."""
    import numpy as np

    from tradingagents import cloud_sweep as cs, forecast_v2_daily as fd
    from tradingagents.positions_view import fmt_when

    state = json.loads((home() / STATE).read_text(encoding="utf-8"))
    roots, board, notes = [], [], []
    for repo, r in state["runs"].items():
        roots.append(download(int(r["run"]), repo))
        pile = r.get("coin_list")
        if pile is None:
            # a run dispatched before the board was saved: dealt again from
            # today's market, and SAID — a board that moved since is not hidden
            k = list(state["runs"]).index(repo)
            pile = cs.split_coins(fd.market(), len(state["runs"]))[k]
            notes.append(f"{repo}: board dealt again from today's market "
                         f"({len(pile)} coins, {r['coins']} at dispatch)")
        board += list(pile)
    merged = read_machines(roots)
    report = read_reports(roots)
    rows = read_rows(roots)
    out = home() / "merged"
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "sums.npz", names=np.array(merged["names"]),
                        fields=np.array(merged["fields"]),
                        **{f"tf_{tf}": a for tf, a in merged["tf"].items()},
                        **{f"barriers_{tf}": np.array(b) for tf, b in merged["barriers"].items()})
    with open(out / "rows.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")
    summary = {"collected": fmt_when(time.time()), "label": state.get("label"),
               "runs": {k: v["run"] for k, v in state["runs"].items()},
               "machines": merged["machines"], "settings": len(merged["names"] or []),
               "timeframes": sorted(merged["tf"]), "rows_kept": len(rows),
               "coverage": coverage(board, report), "notes": notes,
               "report": report}
    (out / "report.json").write_text(json.dumps(summary, indent=0), encoding="utf-8")
    return {k: v for k, v in summary.items() if k != "report"}


def collect_check() -> dict:
    """Bring the check run home: {"roots": [...], "lines": n, "coverage":
    ...} — the trades stay in the run folders for cpw_report.read_check."""
    from tradingagents import cpw_report as rep

    state = json.loads((home() / CHECK_STATE).read_text(encoding="utf-8"))
    roots, board = [], []
    for repo, r in state["runs"].items():
        roots.append(download(int(r["run"]), repo, CHECK_ARTIFACTS))
        board += list(r.get("coin_list") or [])
    check = rep.read_check(roots)
    return {"roots": [str(r) for r in roots], "configs": len(check),
            "lines": sum(len(v) for v in check.values()),
            "coverage": coverage(board, read_reports(roots))}


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "dispatch":
        print(json.dumps(dispatch(sys.argv[2] if len(sys.argv) > 2 else None), indent=2))
    elif len(sys.argv) >= 2 and sys.argv[1] == "collect":
        got = collect()
        cov = got["coverage"]
        got["coverage"] = {**cov, "not_reached": cov["not_reached"][:50],
                           "pairs_failed": cov["pairs_failed"][:50]}
        print(json.dumps(got, indent=2))
    else:
        print("usage: python -m tradingagents.cpw_search dispatch [label] | collect")
