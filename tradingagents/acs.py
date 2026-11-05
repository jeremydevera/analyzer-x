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


def v2_picks(db_path=None, *, k: int = PER_PAIR, log=print) -> dict:
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
                     "picks": pick_pair(rows, tf, k), "rows": len(rows)}
        if i % 500 == 0:
            log(f"  {i} of {len(pairs)} coin-timeframes ({time.time() - t0:.0f} s)")
    con.close()
    return {"made_s": int(time.time()), "db": str(db), "rows": total_rows, "pairs": out,
            "rule": {"per_pair": k, "min_old": MIN_OLD, "rank": "cost share (rt_paid / tp), lowest "
                     "first, among rows that made money on the older 15 days", "recent_days": RECENT_DAYS}}


def plan_of(picks: dict) -> dict:
    """What GitHub rebuilds: {coin: {tf: ["signal:th:sl:tp", ...]}}, with an `id` over the
    configs so a machine can refuse a plan it was not sent."""
    cfg: dict = {}
    for p in picks["pairs"].values():
        for r in p["picks"]:
            cfg.setdefault(p["coin"], {}).setdefault(p["tf"], []).append(
                f"{r['signal']}:{float(r['th']):g}:{float(r['sl']):g}:{float(r['tp']):g}")
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


def dispatch(label: str | None = None, plan_path: Path = PLAN_FILE) -> dict:
    """Deal the plan's coins between every account that can run (cloud_sweep.split_coins) and start
    one acs.yml run on each; an account that refuses or cannot be brought up to this code is named
    and the others still run (CLAUDE.md: every GitHub job uses every account). The plan must be the
    committed one: the machines read it from their checkout and refuse another id."""
    from tradingagents import cloud_sweep as cs, cq_search, forecast_v2_daily as fd
    from tradingagents.positions_view import fmt_when

    if cq_search.quiet_hours():
        raise RuntimeError("no press between 12:45am and 5:00am (the nightly jobs' hours)")
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    ready, refused = fd.fleets_now()
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
        inputs = {"shards": str(SHARDS), "coin_list": ",".join(pile), "label": title,
                  "plan_id": plan["id"]}
        before = {r["databaseId"] for r in json.loads(_gh(
            "run", "list", "-R", repo, "-w", WORKFLOW, "-L", "20", "--json", "databaseId"))}
        try:
            _gh("workflow", "run", WORKFLOW, "-R", repo, *sum([["-f", f"{k}={v}"]
                                                              for k, v in inputs.items()], []))
            run = None
            for _ in range(30):
                time.sleep(4)
                fresh = [r for r in json.loads(_gh("run", "list", "-R", repo, "-w", WORKFLOW, "-L",
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
             "coins": len(coins), "runs": runs, "refused": named}
    (home() / "state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
    return state


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
    (home() / "trades.json").write_text(json.dumps(out), encoding="utf-8")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.acs")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pick")
    d = sub.add_parser("dispatch")
    d.add_argument("--label", default=None)
    sub.add_parser("collect")
    sub.add_parser("page")
    a = p.parse_args(argv)
    if a.cmd == "pick":
        picks = v2_picks()
        (home() / "picks.json").write_text(json.dumps(picks), encoding="utf-8")
        plan = plan_of(picks)
        path = save_plan(plan)
        n = sum(len(v["picks"]) for v in picks["pairs"].values())
        empty = sum(1 for v in picks["pairs"].values() if not v["picks"])
        print(f"{picks['rows']:,} rows on {len(picks['pairs']):,} coin-timeframes: {n:,} picks, "
              f"{empty:,} coin-timeframes with none (no row made money on the older 15 days with "
              f"enough trades); plan {path} id {plan['id']}")
        return 0
    if a.cmd == "dispatch":
        print(json.dumps(dispatch(a.label), indent=1))
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
