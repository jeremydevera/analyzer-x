"""ALL COINS x ALL TIMEFRAMES: several strategies for every coin on 15m, 30m, 1h, 4h and 1d, taken
from the backtests ALREADY MEASURED (Backtest v2's rows, Backtest v3's per-coin verdicts), never a new
grid. The operator, Nov 05, 2026: "use all my existing data from v2 , v3 and generate me the best
strateigioes for all coins for all time frame / make i rule for this becaues i keep on repeating"
(CLAUDE.md "Strategies for every coin and every timeframe").

    python -m tradingagents.acs pick        # choose, write research/acs/plan.json + picks.json
    python -m tradingagents.acs dispatch    # GitHub rebuilds every pick's trades (acs.yml)
    python -m tradingagents.acs collect     # bring the trades home
    python -m tradingagents.acs page        # the results page (kit A-H)

HOW A v2 STRATEGY IS CHOSEN - on days it is then checked against, never on all of them. A v2 row is
30 days with its newest 15 inside it (`t15`/`w15`/`p15`), so its OLDER 15 days are the difference.
A pair's picks are its rows that made money on the older 15 days with at least `MIN_OLD[tf]` older
trades, ranked by `RANK` (the trading cost against the target, lowest first), identical results kept
once, `PER_PAIR` of them. Measured Nov 05, 2026 over 12,527,659 rows on 5,114 coin-timeframes, of 8
ways of choosing on the older 15 days EVERY one lost money over the newest 15 (15m-4h: -$0.17 to -$0.47
a trade), and this one lost least (15m -$0.171, 30m -$0.187, 1h -$0.188, 4h -$0.202 a trade, against
-$0.232, -$0.254, -$0.273, -$0.215 for an average row of the same pairs). So the page says, beside
every pick, what it did on the days it was not chosen on, and the pair's average row beside that.

A v3 strategy is the per-coin verdict of each year measured (its setting chosen on the coin's older
days, judged on 90 unseen days, beside its own 200 random runs): 2026 (`all-coins`) and 2025
(`all-2025`), and a group that was PROFITABLE in both years says so.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import time
from pathlib import Path

TFS = ("15m", "30m", "1h", "4h", "1d")
PER_PAIR = 3
# the fewest trades on the OLDER 15 days a pick may be chosen on; 1d has at most ~15 candles there
MIN_OLD = {"15m": 10, "30m": 8, "1h": 6, "4h": 4, "1d": 2}
RECENT_DAYS = 15                  # backtest_report.RECENT_DAYS: the newest days every v2 row carries
PLAN_FILE = Path(__file__).resolve().parent.parent / "research" / "acs" / "plan.json"
WORKFLOW = "acs.yml"
SHARDS = 20                       # machines per account (MACHINES_PER_ACCOUNT)
V3_RUNS = ("all-coins", "all-2025")
ARTIFACTS = ("acs-trades-*",)


def home() -> Path:
    from tradingagents import market_sweep as msw

    p = Path(msw.HOME) / "acs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cost_share(row: dict) -> float:
    """The round trip the row's own trades paid (`rt_paid`, else the estimate `rt`) against its
    target, both in percent: the RANK, lowest first."""
    rt = row.get("rt_paid")
    rt = row.get("rt") if rt is None else rt
    return float(rt or 0.0) / float(row["tp"])


RANK = cost_share


def older(row: dict) -> dict:
    """The row's OLDER 15 days: its 30 days less the newest 15 it carries."""
    t, w, p = int(row["trades"]), int(row["wins"]), float(row["profit"])
    t15, w15, p15 = int(row["t15"] or 0), int(row["w15"] or 0), float(row["p15"] or 0.0)
    return {"trades": t - t15, "wins": w - w15, "profit": round(p - p15, 4)}


def pick_pair(rows: list[dict], tf: str, k: int = PER_PAIR) -> list[dict]:
    """Up to `k` picks of one coin-timeframe: rows that made money on the older 15 days with
    MIN_OLD[tf] older trades, lowest cost share first, identical results (the same trades, wins and
    profit on both halves) kept once. A row without the newest-15-day count cannot be split, so it
    is never a pick."""
    seen, cands = set(), []
    for r in rows:
        if r.get("t15") is None or not r.get("tp") or not r.get("sl"):
            continue
        o = older(r)
        if o["trades"] < MIN_OLD[tf] or o["profit"] <= 0:
            continue
        key = (o["trades"], o["wins"], round(o["profit"], 2), int(r["t15"]), int(r["w15"]),
               round(float(r["p15"]), 2))
        if key in seen:
            continue
        seen.add(key)
        cands.append((RANK(r), -o["profit"], str(r["id"]), r, o))
    cands.sort(key=lambda c: c[:3])
    return [{**r, "older": o, "rank": round(c, 6)} for c, _p, _i, r, o in cands[:k]]


CANDIDATES = 5                    # per pair sent to GitHub: the page shows the first PER_PAIR that come back


def candidates(rows: list[dict], tf: str, n: int = CANDIDATES) -> list[dict]:
    """Up to `n` strategies for EVERY coin-timeframe (operator, Nov 05, 2026: "generate multiple
    strategies" for each timeframe): the picks first (`pick_pair`), then, when fewer than `n` made
    money on the older 15 days, the next rows by the same rank flagged `older_lost` - so a pair is
    never left empty, and a strategy that lost where it was chosen says so. Rows without the
    newest-15-day count, or with fewer than half MIN_OLD[tf] older trades, are never shown."""
    out = [{**p, "older_lost": False} for p in pick_pair(rows, tf, n)]
    if len(out) >= n:
        return out
    taken = {p["id"] for p in out}
    seen = {(p["older"]["trades"], p["older"]["wins"], round(p["older"]["profit"], 2)) for p in out}
    rest = []
    for r in rows:
        if r.get("t15") is None or not r.get("tp") or not r.get("sl") or r["id"] in taken:
            continue
        o = older(r)
        key = (o["trades"], o["wins"], round(o["profit"], 2))
        if o["trades"] < max(1, MIN_OLD[tf] // 2) or key in seen:
            continue
        seen.add(key)
        rest.append((-o["profit"], RANK(r), str(r["id"]), r, o))
    rest.sort(key=lambda c: c[:3])
    out += [{**r, "older": o, "rank": round(rk, 6), "older_lost": o["profit"] <= 0}
            for _p, rk, _i, r, o in rest[: n - len(out)]]
    if len(out) >= n:
        return out
    # a coin too new to have older days (every trade in the newest 15): its best 30-day rows, flagged
    # `unchecked` - nothing can say whether they hold up, and the page says so
    taken = {p["id"] for p in out}
    young = []
    for r in rows:
        if r["id"] in taken or not r.get("tp") or not r.get("sl") or int(r.get("trades") or 0) < 1:
            continue
        key = (int(r["trades"]), int(r["wins"]), round(float(r["profit"]), 2))
        if key in seen:
            continue
        seen.add(key)
        young.append((-float(r["profit"]), RANK(r), str(r["id"]), r))
    young.sort(key=lambda c: c[:3])
    out += [{**r, "older": older(r) if r.get("t15") is not None else {"trades": 0, "wins": 0, "profit": 0.0},
             "rank": round(rk, 6), "older_lost": False, "unchecked": True}
            for _p, rk, _i, r in young[: n - len(out)]]
    return out


def pair_bar(rows: list[dict]) -> dict:
    """What an AVERAGE strategy of the pair did on the newest 15 days: the bar a pick is read
    against (a pick that did no better than the pair's average row was chosen by luck)."""
    n = trades = pos = 0
    profit = 0.0
    for r in rows:
        if r.get("t15") is None:
            continue
        n += 1
        trades += int(r["t15"])
        profit += float(r["p15"])
        pos += float(r["p15"]) > 0
    return {"rows": n, "trades": trades, "profit": round(profit, 2),
            "per_trade": round(profit / trades, 4) if trades else None,
            "share_positive": round(pos / n, 4) if n else None}


FIELDS = ("id", "coin", "tf", "signal", "th", "sl", "tp", "sizing", "lev", "base", "notional",
          "trades", "wins", "losses", "profit", "t15", "w15", "p15", "rt", "rt_paid", "days",
          "worst", "dd", "green", "months", "res")


def v2_picks(db_path=None, *, k: int = CANDIDATES, log=print) -> dict:
    """Every coin-timeframe of the Backtest v2 list, read once, pair by pair."""
    from tradingagents import stores

    db = Path(db_path or stores.V2.rows_db)
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=60)
    cols = [r[1] for r in con.execute("pragma table_info(rows)")]
    want = [c for c in FIELDS if c in cols]
    pairs = con.execute("select pair, coin, tf, last_ms from pairs order by coin, tf").fetchall()
    out, t0, total_rows = {}, time.time(), 0
    for i, (pair, coin, tf, last_ms) in enumerate(pairs):
        if tf not in TFS:
            continue
        rows = [dict(zip(want, x)) for x in
                con.execute(f"select {','.join(want)} from rows where pair=?", (pair,))]
        total_rows += len(rows)
        out[pair] = {"coin": coin, "tf": tf, "last_ms": last_ms, "bar": pair_bar(rows),
                     "picks": candidates(rows, tf, k), "rows": len(rows)}
        if i % 500 == 0:
            log(f"  {i} of {len(pairs)} coin-timeframes ({time.time() - t0:.0f} s)")
    con.close()
    return {"made_s": int(time.time()), "db": str(db), "rows": total_rows, "pairs": out,
            "rule": {"per_pair": PER_PAIR, "candidates": k, "min_old": MIN_OLD, "rank": "cost share (rt_paid / tp), lowest "
                     "first, among rows that made money on the older 15 days", "recent_days": RECENT_DAYS}}


def cfg_of(r: dict) -> str:
    return f"{r['signal']}:{float(r['th']):g}:{float(r['sl']):g}:{float(r['tp']):g}"


def plan_of(picks: dict, done: set | None = None) -> dict:
    """What GitHub rebuilds: {coin: {tf: ["signal:th:sl:tp", ...]}}, with an `id` over the
    configs so a machine can refuse a plan it was not sent. `done` ('COIN|tf|cfg' keys an earlier
    run already answered, with a list or with no row) is left out: a second run measures only what
    is new."""
    done = done or set()
    cfg: dict = {}
    for p in picks["pairs"].values():
        for r in p["picks"]:
            if f"{p['coin']}|{p['tf']}|{cfg_of(r)}" in done:
                continue
            cfg.setdefault(p["coin"], {}).setdefault(p["tf"], []).append(cfg_of(r))
    body = json.dumps(cfg, sort_keys=True, separators=(",", ":"))
    return {"id": hashlib.blake2b(body.encode(), digest_size=8).hexdigest(),
            "made_s": picks["made_s"], "configs": cfg}


def save_plan(plan: dict, path: Path = PLAN_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, sort_keys=True, indent=0), encoding="utf-8")
    return path


# ------------------------------------------------------------------- GitHub

def _gh(*args: str, timeout: int = 120) -> str:
    # utf-8, never this PC's code page: the run title carries "·", and read as cp1252 it never
    # matched, so three runs GitHub had taken were reported as not listed (Nov 05, 2026)
    r = subprocess.run(["gh", *args], capture_output=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[:300])
    return r.stdout


SKILL_WORKFLOW = "skillbt.yml"
# each skill set's files: bt = the backtesting skill, ta = technical-analysis + backtesting-frameworks
# (best 3 a coin-timeframe), ta_all = every one of their 42 a coin-timeframe, daily = the 42 plus the
# backtesting skill's pinned picks (research/v4/bt_pinned.json), funding charged
SKILL_PREFIX = {"bt": "skill", "ta": "skillta", "ta_all": "skilltaall", "daily": "skilldaily"}


def dispatch(label: str | None = None, plan_path: Path = PLAN_FILE, skip=(), skill: bool = False,
             coins=None, skill_set: str = "bt") -> dict:
    """Deal the plan's coins between every account that can run (cloud_sweep.split_coins) and start
    one acs.yml run on each; an account that refuses or cannot be brought up to this code is named
    and the others still run (CLAUDE.md: every GitHub job uses every account). The plan must be the
    committed one: the machines read it from their checkout and refuse another id."""
    from tradingagents import cloud_sweep as cs, cq_search, forecast_v2_daily as fd
    from tradingagents.positions_view import fmt_when

    if cq_search.quiet_hours():
        raise RuntimeError("no press between 12:45am and 5:00am (the nightly jobs' hours)")
    # the skill run measures the exchange's whole market and needs no plan (skill_bt.py); `skill_set`
    # "ta" runs the technical-analysis and backtesting-frameworks skills' strategies (skill_ta.py)
    if skill_set not in SKILL_PREFIX:
        raise ValueError(f"skill_set must be one of {sorted(SKILL_PREFIX)}, not {skill_set!r}")
    redo = bool(coins)            # named coins = a redo; `coins` is the dealt list from here on
    plan = ({"id": "", "configs": {c.replace("_USDT", ""): 1 for c in (coins or fd.market())}} if skill
            else json.loads(Path(plan_path).read_text(encoding="utf-8")))
    workflow = SKILL_WORKFLOW if skill else WORKFLOW
    ready, refused = fd.fleets_now()
    # an account whose machines are all held by another job (`--skip`) is named, never queued behind it
    refused = list(refused) + [f"{r}: skipped - its machines are busy with another job" for r in ready
                               if r in skip]
    ready = [r for r in ready if r not in skip]
    if not ready:
        raise RuntimeError("no GitHub account can run it: " + "; ".join(refused))
    coins = sorted(plan["configs"])
    piles = cs.split_coins(coins, len(ready))
    label = label or fmt_when(time.time())
    origin = cs.origin_fleet()
    runs, named = {}, list(refused)
    for n, (repo, pile) in enumerate(zip(ready, piles, strict=False)):
        if repo != origin:
            drift = cs.sync_fleet(repo)
            if drift:
                named.append(f"{repo}: not brought up to this code ({drift})")
                continue
        title = f"{label} · {n + 1} of {len(ready)}"
        inputs = {"shards": str(SHARDS), "coin_list": ",".join(pile), "label": title}
        if not skill:
            inputs["plan_id"] = plan["id"]
        elif skill_set != "bt":
            inputs["set"] = skill_set
        before = {r["databaseId"] for r in json.loads(_gh(
            "run", "list", "-R", repo, "-w", workflow, "-L", "20", "--json", "databaseId"))}
        try:
            _gh("workflow", "run", workflow, "-R", repo, *sum([["-f", f"{k}={v}"]
                                                              for k, v in inputs.items()], []))
            run = None
            for _ in range(30):
                time.sleep(4)
                fresh = [r for r in json.loads(_gh("run", "list", "-R", repo, "-w", workflow, "-L",
                                                   "20", "--json", "databaseId,displayTitle"))
                         if r["databaseId"] not in before and title in r["displayTitle"]]
                if fresh:
                    run = fresh[0]["databaseId"]
                    break
            if run is None:
                raise RuntimeError("GitHub took the run but did not list it within 2 minutes")
            runs[repo] = {"run": run, "coins": len(pile), "label": title, "coin_list": list(pile)}
        except Exception as exc:                                   # noqa: BLE001
            named.append(f"{repo}: {str(exc)[:160]}")
    state = {"label": label, "plan_id": plan["id"], "started_s": int(time.time()),
             "coins": len(coins), "runs": runs, "refused": named, "set": skill_set if skill else None}
    (home() / _state_name(skill, redo, skill_set)).write_text(json.dumps(state, indent=1), encoding="utf-8")
    return state


def _state_name(skill: bool, redo: bool, skill_set: str = "bt") -> str:
    """Where a dispatch's state is kept: a whole-market skill run and a redo of named coins apart,
    and each skill set apart."""
    if not skill:
        return "state.json"
    return f"{SKILL_PREFIX[skill_set]}-{'redo-' if redo else ''}state.json"


def answered() -> set:
    """Every 'COIN|tf|cfg' a collected run already answered: a trade list, or no row."""
    out: set = set()
    for f in home().glob("trades-*.json"):
        t = json.loads(f.read_text(encoding="utf-8"))
        out |= set(t["lines"]) | set(t.get("no_row") or [])
    return out


def collect() -> dict:
    """Every account's trade lines, keyed 'COIN|tf|signal:th:sl:tp'. A coin no machine reported is
    named in `not_reached`, a coin-timeframe that raised in `failed` (rule 20)."""
    import shutil

    state = json.loads((home() / "state.json").read_text(encoding="utf-8"))
    lines, failed, reported, dl_failed, no_row = {}, [], set(), [], []
    for key, r in state["runs"].items():
        repo = r.get("repo", key)     # a share moved to another account is keyed apart, its repo named
        root = home() / f"run-{r['run']}"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        try:
            _gh("run", "download", str(r["run"]), "-R", repo, "-D", str(root), "-p", ARTIFACTS[0],
                timeout=1800)
        except Exception as exc:                                   # noqa: BLE001
            dl_failed.append(f"{repo}: {str(exc)[:160]}")
            continue
        for f in root.rglob("acs-trades-*.jsonl"):
            for text in f.read_text(encoding="utf-8").splitlines():
                if text.strip():
                    x = json.loads(text)
                    lines.setdefault(f"{x['coin']}|{x['tf']}|{x['cfg']}", x)
                    reported.add(x["coin"])
        for f in root.rglob("acs-report-*.json"):
            for e in json.loads(f.read_text(encoding="utf-8")):
                reported.add(e.get("coin"))
                no_row += [f"{e['coin']}|{e['tf']}|{x}" for x in e.get("no_row", [])]
                if e.get("error"):
                    failed.append(f"{e['coin']} {e.get('tf')}: {e['error']}")
    board = {c for r in state["runs"].values() for c in r["coin_list"]}
    out = {"plan_id": state["plan_id"], "lines": lines, "failed": failed, "no_row": sorted(set(no_row)),
           "not_reached": sorted(board - reported), "downloads_failed": dl_failed,
           "collected_s": int(time.time())}
    # one file per plan: a second run (only what the first did not answer) never replaces the first
    (home() / f"trades-{state['plan_id']}.json").write_text(json.dumps(out), encoding="utf-8")
    return out


def collect_redo(skill_set: str = "bt") -> dict:
    """A redo of named coins (`dispatch --skill --coins`): each account's lines downloaded and laid
    over the saved skill run (`merge_skill`)."""
    import shutil

    pre = SKILL_PREFIX[skill_set]
    state = json.loads((home() / f"{pre}-redo-state.json").read_text(encoding="utf-8"))
    out = {}
    for key, r in state["runs"].items():
        repo = r.get("repo", key)
        root = home() / f"{pre}-run-{r['run']}"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        _gh("run", "download", str(r["run"]), "-R", repo, "-D", str(root), "-p", "skill-lines-*",
            timeout=1800)
        out[repo] = merge_skill(root, skill_set)
    return out


def collect_skill(skill_set: str = "bt") -> dict:
    """The skill run's lines from every account, keyed 'COIN|tf' (skill_bt.py); a coin no machine
    reported is named in `not_reached`, a coin-timeframe that raised in `failed`. `skill_set` "ta"
    collects the technical-analysis and backtesting-frameworks run into skillta.json."""
    import shutil

    pre = SKILL_PREFIX[skill_set]
    state = json.loads((home() / f"{pre}-state.json").read_text(encoding="utf-8"))
    lines, failed, reported, dl_failed, skipped = {}, [], set(), [], []
    for key, r in state["runs"].items():
        repo = r.get("repo", key)
        root = home() / f"{pre}-run-{r['run']}"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        try:
            _gh("run", "download", str(r["run"]), "-R", repo, "-D", str(root), "-p", "skill-lines-*",
                timeout=1800)
        except Exception as exc:                                   # noqa: BLE001
            dl_failed.append(f"{repo}: {str(exc)[:160]}")
            continue
        for f in root.rglob(f"{pre}-*.jsonl"):
            for text in f.read_text(encoding="utf-8").splitlines():
                if text.strip():
                    x = json.loads(text)
                    lines.setdefault(f"{x['coin']}|{x['tf']}", x)
                    reported.add(x["coin"])
        for f in root.rglob(f"{pre}-report-*.json"):
            for e in json.loads(f.read_text(encoding="utf-8")):
                reported.add(e.get("coin"))
                if e.get("error"):
                    failed.append(f"{e['coin']} {e.get('tf')}: {e['error']}")
                if e.get("skipped"):
                    skipped.append(f"{e['coin']} {e['tf']}: only {e['skipped']}")
    board = {c for r in state["runs"].values() for c in r["coin_list"]}
    out = {"lines": lines, "failed": failed, "skipped": skipped, "not_reached": sorted(board - reported),
           "downloads_failed": dl_failed, "collected_s": int(time.time()), "set": skill_set}
    (home() / f"{pre}.json").write_text(json.dumps(out), encoding="utf-8")
    return out


def merge_skill(folder, skill_set: str = "bt") -> dict:
    """A redo's lines (a skill_shard run's `out` folder) laid over the saved skill run: a redone
    coin-timeframe replaces its line and leaves the skipped and failed lists; one the redo could not
    measure keeps its reason (CLAUDE.md: a failed coin is redone alone, never the whole run)."""
    folder = Path(folder)
    pre = SKILL_PREFIX[skill_set]
    path = home() / f"{pre}.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    got, still_failed, still_skipped = {}, [], []
    for f in folder.rglob(f"{pre}-*.jsonl"):
        for text in f.read_text(encoding="utf-8").splitlines():
            if text.strip():
                x = json.loads(text)
                got[f"{x['coin']}|{x['tf']}"] = x
    for f in folder.rglob(f"{pre}-report-*.json"):
        for e in json.loads(f.read_text(encoding="utf-8")):
            if e.get("error"):
                still_failed.append(f"{e['coin']} {e.get('tf')}: {e['error']}")
            if e.get("skipped"):
                still_skipped.append(f"{e['coin']} {e['tf']}: only {e['skipped']}")
    saved["lines"].update(got)
    saved["not_reached"] = sorted(set(saved.get("not_reached") or []) - {x["coin"] for x in got.values()})
    done = {k.replace("|", " ") for k in got}
    keep = lambda xs: [x for x in xs if x.split(":")[0] not in done]
    saved["failed"] = sorted(set(keep(saved.get("failed") or []) + still_failed))
    saved["skipped"] = sorted(set(keep(saved.get("skipped") or []) + still_skipped))
    saved["redone_s"] = int(time.time())
    path.write_text(json.dumps(saved), encoding="utf-8")
    return {"redone": len(got), "failed": len(saved["failed"]), "skipped": len(saved["skipped"])}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.acs")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pick")
    d = sub.add_parser("dispatch")
    d.add_argument("--label", default=None)
    d.add_argument("--skip", action="append", default=[], help="owner/repo whose machines are busy")
    d.add_argument("--skill", action="store_true", help="the backtesting skill on the whole market")
    d.add_argument("--coins", default="", help="comma-separated coins (a redo of named ones)")
    d.add_argument("--set", dest="skill_set", default="bt", choices=("bt", "ta", "ta_all", "daily"),
                   help="with --skill: bt = the backtesting skill, ta = technical-analysis + backtesting-frameworks")
    c = sub.add_parser("collect")
    c.add_argument("--skill", action="store_true")
    c.add_argument("--set", dest="skill_set", default="bt", choices=("bt", "ta", "ta_all", "daily"))
    c.add_argument("--merge", default=None, help="a skill redo's out folder to lay over the saved run")
    sub.add_parser("page")
    a = p.parse_args(argv)
    if a.cmd == "pick":
        picks = v2_picks()
        (home() / "picks.json").write_text(json.dumps(picks), encoding="utf-8")
        plan = plan_of(picks, answered())
        path = save_plan(plan)
        n = sum(len(v["picks"]) for v in picks["pairs"].values())
        empty = sum(1 for v in picks["pairs"].values() if not v["picks"])
        print(f"{picks['rows']:,} rows on {len(picks['pairs']):,} coin-timeframes: {n:,} picks, "
              f"{empty:,} coin-timeframes with none (the v2 list holds no usable strategy for them); "
              f"{sum(len(t) for c in plan['configs'].values() for t in c.values()):,} not measured "
              f"yet; plan {path} id {plan['id']}")
        return 0
    if a.cmd == "dispatch":
        st = dispatch(a.label, skip=tuple(a.skip), skill=a.skill,
                      coins=[c for c in a.coins.split(",") if c] or None, skill_set=a.skill_set)
        print(json.dumps({k: v for k, v in st.items() if k != "runs"} | {
            "runs": {r: {k: v for k, v in x.items() if k != "coin_list"} for r, x in st["runs"].items()}},
            indent=1))
        return 0
    if a.cmd == "collect" and a.merge == "redo":
        print(collect_redo(a.skill_set))
        return 0
    if a.cmd == "collect" and a.merge:
        print(merge_skill(a.merge, a.skill_set))
        return 0
    if a.cmd == "collect" and a.skill:
        out = collect_skill(a.skill_set)
        print(f"{len(out['lines']):,} coin-timeframes; failed {len(out['failed'])}; too few candles "
              f"{len(out['skipped'])}; not reached {len(out['not_reached'])}; downloads failed "
              f"{len(out['downloads_failed'])}")
        return 0
    if a.cmd == "collect":
        out = collect()
        print(f"{len(out['lines']):,} trade lists; failed {len(out['failed'])}; not reached "
              f"{len(out['not_reached'])}; downloads failed {len(out['downloads_failed'])}")
        return 0
    from tradingagents import acs_page

    path = acs_page.write()
    print(f"{path} ({path.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
