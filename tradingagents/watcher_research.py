"""Which promotion and demotion rules would have made the most — tuned on one
stretch of history, then graded on a later one it never saw.

Operator, `Sep 28, 2026`: *"Can you research more on what's the best
combination to earn money, maybe my criteria is not optimized can you research
whats the best criteria for promotion and demotion"*.

HONEST BY CONSTRUCTION. Tuning rules on September and quoting September's
profit would always find something that looks brilliant — thousands of rule
sets, one month, the best of them is partly luck. So every rule set is
replayed twice:

* TRAIN — checks from `train_start` to `train_end` (Jul 01 - Aug 31, 2026),
  with every trade that closed after `train_end` cut away (replay_collect.cut),
  so nothing from September can help a rule look good here;
* TEST — checks from `test_start` (Sep 01, 2026) to the end of the data,
  starting flat, exactly as if the watcher had been switched on that morning.

Rule sets are ranked on TRAIN; the page shows what the winners then did on
TEST, beside the operator's own rules. "Best on TEST" is printed too, but
labelled as hindsight: it is chosen by looking at the answer.

ONE IMPLEMENTATION. Every replay is `watcher_replay.simulate` itself, fed the
rows it would compute (`rows_by_check`), pre-cut to the rows the LOOSEST rule
in the grid could pick — a pure speed-up, pinned by
tests/test_watcher_research.py against `simulate` computing them itself.

    python -m tradingagents.watcher_research <result-name> <folder> [<folder> ...]
"""
from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from tradingagents import replay_collect as rc
from tradingagents import watcher_policy as wp
from tradingagents import watcher_replay as wr

OUT_DIR = Path(os.path.expanduser("~/.tradingagents")) / "replay"

# The operator's own rules — the row every other one is compared with.
CURRENT = {"on_winrate": 90.0, "off_winrate": 90.0, "min_trades": 20,
           "tp_rule": ">", "window_days": 30, "rank": "winrate",
           "max_per_coin": 3, "max_new_per_day": 20, "cooldown_days": 7,
           "off_streak_live": 0, "max_slots": 100}

GRID = {"on_winrate": [80.0, 85.0, 90.0, 95.0],
        "off_gap": [0.0, 5.0, 10.0],
        "min_trades": [15, 20, 30],
        "tp_rule": [">", ">="],
        "window_days": [14, 30],
        "rank": ["winrate", "profit"],
        "max_per_coin": [1, 3],
        "max_new_per_day": [5, 20],
        "cooldown_days": [0, 7],
        "off_streak_live": [0, 3]}


def grid() -> list[dict]:
    """Every rule set, the operator's own included (it is a grid point)."""
    keys = list(GRID)
    out = []
    for vals in itertools.product(*(GRID[k] for k in keys)):
        c = dict(zip(keys, vals))
        gap = c.pop("off_gap")
        c["off_winrate"] = c["on_winrate"] - gap
        c["max_slots"] = 100
        out.append(c)
    assert any(all(c[k] == v for k, v in CURRENT.items()) for c in out)
    return out


def rule_id(cfg: dict) -> str:
    """A stable short id for a rule set, hashed from its values (kit H)."""
    key = json.dumps({k: cfg[k] for k in sorted(CURRENT)}, sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()[:8].upper()


def loose(grid_: list[dict]) -> dict:
    """The loosest on-rule any rule set in the grid uses — every row that
    could ever be a candidate passes it."""
    return {**wp.DEFAULTS, "on_winrate": min(c["on_winrate"] for c in grid_),
            "min_trades": min(c["min_trades"] for c in grid_),
            "tp_rule": ">=" if any(c["tp_rule"] == ">=" for c in grid_) else ">"}


def prepare(combos: list[dict], start_ms: int, end_ms: int,
            windows: list[int], lo: dict) -> dict:
    """Books once, and for each window the rows at every check that pass the
    loosest rule — what `simulate` would compute, minus rows no rule set in
    the grid could pick."""
    books = {c["id"]: wr._Book(c) for c in combos}
    checks = wr.local_midnights(start_ms, end_ms)
    rows = {}
    for w in windows:
        allrows = wr.rows_by_check(books, checks, w * wr.DAY_MS)
        rows[w] = {at: [r for r in rs if not wp.passes_on(r, lo)]
                   for at, rs in allrows.items()}
    return {"books": books, "rows": rows, "start": start_ms, "end": end_ms,
            "combos": combos}


def score(res: dict) -> dict:
    """What a rule set did: the numbers the page prints for it."""
    s = res["summary"]
    days = [round(d["pnl"], 2) for d in res["days"]]
    peak = eq = dd = 0.0
    for p in days:
        eq += p
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    closed = sorted((t for sl in res["slots"] for t in sl["trades"] if t[3]),
                    key=lambda t: t[1])
    run = worst = 0.0
    n = worst_n = 0
    for t in closed:
        if t[2] > 0:
            run, n = 0.0, 0
        else:
            run += t[2]
            n += 1
            if run < worst:
                worst, worst_n = run, n
    # the profit IS the sum of the days the page draws, so the headline, the
    # card and the chart's last point are one number (label-must-match-data)
    return {"profit": round(sum(days), 2), "closed": s["closed"], "wins": s["wins"],
            "losses": s["losses"], "winrate": s["winrate"], "slots": s["slots"],
            "open": s["open"], "worst_day": min(days) if days else 0.0,
            "green_days": sum(1 for p in days if p > 0),
            "days_n": len(days), "max_dd": round(dd, 2),
            "worst_run": round(worst, 2), "worst_run_n": worst_n, "days": days}


# ---------------------------------------------------------- worker processes
_W: dict = {}


def _init(folders: list[str], train: tuple, test: tuple, windows: list[int],
          lo: dict) -> None:
    got = rc.merge(folders)
    end = rc.common_end(got["totals"]["spans"])
    everything = rc.cut(got["combos"], end)
    _W["train"] = prepare(rc.cut(everything, train[1]), train[0], train[1],
                          windows, lo)
    _W["test"] = prepare(everything, test[0], end, windows, lo)


def _run(cfg: dict) -> dict:
    out = {"id": rule_id(cfg), "cfg": cfg}
    for part in ("train", "test"):
        P = _W[part]
        res = wr.simulate(P["combos"], start_ms=P["start"], end_ms=P["end"],
                          cfg=cfg, rows=P["rows"][cfg["window_days"]],
                          books=P["books"])
        out[part] = score(res)
    return out


def research(folders: list[str], *, train_start: str = "2026-07-01",
             train_end: str = "2026-09-01", test_start: str = "2026-09-01",
             workers: int | None = None, grid_: list[dict] | None = None) -> dict:
    g = grid_ or grid()
    lo = loose(g)
    ms = lambda s: int(dt.datetime(*map(int, s.split("-"))).timestamp() * 1000)  # noqa: E731
    train = (ms(train_start), ms(train_end) - 1)
    test = (ms(test_start), None)
    windows = sorted({c["window_days"] for c in g})
    got = rc.merge(folders)
    end = rc.common_end(got["totals"]["spans"])
    test = (test[0], end)
    # each worker holds every trade in memory; six is what this 17 GB PC can spare
    workers = workers or max(1, min(6, (os.cpu_count() or 4) - 2))
    with ProcessPoolExecutor(workers, initializer=_init,
                             initargs=(folders, train, test, windows, lo)) as ex:
        rows = list(ex.map(_run, g, chunksize=16))
    by_train = sorted(rows, key=lambda r: -r["train"]["profit"])
    cur = next(r for r in rows if r["id"] == rule_id(CURRENT))
    return {"train": list(train), "test": list(test), "end_ms": end,
            "totals": got["totals"], "combos": len(got["combos"]),
            "grid": GRID, "current_id": cur["id"],
            "best_train_id": by_train[0]["id"], "rows": rows}


def main(argv=None) -> int:
    argv = list(argv or sys.argv[1:])
    name, folders = argv[0], argv[1:]
    res = research(folders)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"research-{name}.json"
    path.write_text(json.dumps(res, separators=(",", ":")), encoding="utf-8")
    best = next(r for r in res["rows"] if r["id"] == res["best_train_id"])
    cur = next(r for r in res["rows"] if r["id"] == res["current_id"])
    print(f"{len(res['rows'])} rule sets on {res['combos']:,} combinations. "
          f"Best on Jul-Aug #{best['id']}: train {best['train']['profit']:+.2f}, "
          f"September {best['test']['profit']:+.2f}. Yours #{cur['id']}: train "
          f"{cur['train']['profit']:+.2f}, September {cur['test']['profit']:+.2f} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
