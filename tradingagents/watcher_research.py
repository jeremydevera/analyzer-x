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
from pathlib import Path

import numpy as np

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


def score(res: dict, end_ms: float | None = None) -> dict:
    """What a rule set did: the numbers the page prints for it.

    `end_ms` is the period's last moment: a trade that closed AFTER it (a
    July-August trade still open on Aug 31) is not counted, exactly as the
    days do not count it — so the count, the wins and the profit describe the
    same trades."""
    s = res["summary"]
    days = [round(d["pnl"], 2) for d in res["days"]]
    end = float("inf") if end_ms is None else end_ms
    peak = eq = dd = 0.0
    for p in days:
        eq += p
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    closed = sorted((t for sl in res["slots"] for t in sl["trades"]
                     if t[3] and t[1] <= end), key=lambda t: t[1])
    wins = sum(1 for t in closed if t[2] > 0)
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
    # THE MOST TRADES OPEN AT ONCE — what the wallet has to hold. More rules
    # passing means more trades, and every open one ties up its margin.
    marks = sorted([(t[0], 1) for t in closed] + [(t[1], -1) for t in closed],
                   key=lambda m: (m[0], m[1]))
    live = max_open = 0
    for _, step in marks:
        live += step
        max_open = max(max_open, live)
    return {"profit": round(sum(days), 2), "closed": len(closed), "wins": wins,
            "max_open": max_open,
            "losses": len(closed) - wins,
            "winrate": round(100 * wins / len(closed), 2) if closed else 0.0,
            "slots": s["slots"],
            "open": s["open"], "worst_day": min(days) if days else 0.0,
            "green_days": sum(1 for p in days if p > 0),
            "days_n": len(days), "max_dd": round(dd, 2),
            "worst_run": round(worst, 2), "worst_run_n": worst_n, "days": days}


# ------------------------------------------------------- the lean feeding path
# Measured Sep 28, 2026: the research run (36495354168) wrote 77,952
# combinations and ~10.4 million trades (394 MB on disk) while this PC had
# 2.4 GB free. As Python lists, one copy of the trades is ~1.6 GB, the books
# as many again, and the rows at every check ~2 GB — the machine would page
# to its spinning disk. So: the trades of each combination become ONE numpy
# array as its line is read, one set of books serves both periods (a row at
# an Aug check can only see exits before it, so it cannot see September),
# and the rows at each check are four small arrays. `simulate` is untouched:
# it is handed the same kind of books and rows it builds itself, and
# test_the_lean_path_gives_what_simulate_computes_itself pins that.


class ArrBook:
    """`watcher_replay._Book`, backed by numpy arrays: the same `row()`, the
    same `.c` (whose "trades" is an (n, 4) array: entry_ms, exit_ms, pnl,
    closed), a fraction of the memory."""

    __slots__ = ("c", "exits", "w", "p")

    def __init__(self, meta: dict, trades: np.ndarray):
        self.c = {**meta, "trades": trades}
        closed = trades[trades[:, 3] > 0]
        closed = closed[np.argsort(closed[:, 1], kind="stable")]
        self.exits = closed[:, 1].astype(np.int64)
        self.w = np.concatenate([[0], np.cumsum(closed[:, 2] > 0)]).astype(np.int64)
        self.p = np.concatenate([[0.0], np.cumsum(closed[:, 2])])

    def counts(self, at_ms: int, window_ms: int) -> tuple[int, int, float]:
        a = int(np.searchsorted(self.exits, at_ms - window_ms, "left"))
        b = int(np.searchsorted(self.exits, at_ms, "right"))
        return b - a, int(self.w[b] - self.w[a]), float(self.p[b] - self.p[a])

    def row(self, at_ms: int, window_ms: int = wr.WINDOW_MS) -> dict | None:
        n, wins, profit = self.counts(at_ms, window_ms)
        return None if n == 0 else _row_dict(self.c, n, wins, profit)


def _row_dict(c: dict, n: int, wins: int, profit: float) -> dict:
    """The dict `_Book.row` returns, field for field."""
    return {"id": c["id"], "coin": c["coin"], "tf": c["tf"],
            "signal": c["signal"], "th": c.get("th", 0.0),
            "group": c.get("group", "classic"),
            "sl": c["sl"], "tp": c["tp"], "gate": c.get("gate", "ok"),
            "trades": n, "wins": wins, "losses": n - wins,
            "winrate": round(100 * wins / n, 2), "profit": round(profit, 2)}


def load_lean(folders: list[str]) -> dict:
    """Every combination of the runs, as ArrBooks, cut to the common end."""
    got_tot = rc.merge_reports(folders)
    end = rc.common_end(got_tot["spans"])
    books: dict = {}
    for f in rc.combo_files(folders):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                c = json.loads(line)
                if c["id"] in books:
                    continue
                t = np.asarray(c.pop("trades") or [], dtype=np.float64).reshape(-1, 4)
                t = t[t[:, 0] < end]                  # nothing entered after the end
                late = (t[:, 3] > 0) & (t[:, 1] > end)
                t[late, 2] = 0.0                      # closed after the end = still open
                t[late, 3] = 0.0
                c.setdefault("group", rc.group_of(c["signal"]))
                books[c["id"]] = ArrBook(c, t)
    return {"books": books, "end": end, "totals": got_tot}


def compact_rows(books: dict, checks: list[int], window_ms: int, lo: dict) -> dict:
    """{check: arrays of the rows that pass the loosest rule}: book index,
    trades, wins, profit — the rows `rows_by_check` would build, minus those
    no rule set could pick, in four arrays instead of a dict each."""
    ids = list(books)
    tp = np.array([books[i].c["tp"] for i in ids])
    sl = np.array([books[i].c["sl"] for i in ids])
    gate = np.array([books[i].c.get("gate", "ok") == "ok" for i in ids])
    tp_ok = tp > sl if lo["tp_rule"] == ">" else tp >= sl
    out = {}
    for at in checks:
        n = np.zeros(len(ids), np.int64)
        w = np.zeros(len(ids), np.int64)
        pr = np.zeros(len(ids))
        for k, i in enumerate(ids):
            n[k], w[k], pr[k] = books[i].counts(at, window_ms)
        rate = np.where(n > 0, 100 * w / np.maximum(n, 1), 0.0)
        keep = ((n >= lo["min_trades"]) & (np.round(rate, 2) >= lo["on_winrate"])
                & (np.round(pr, 2) > lo["profit_floor"]) & gate & tp_ok)
        k = np.nonzero(keep)[0]
        out[at] = (k, n[k], w[k], pr[k])
    return {"ids": ids, "tp": tp, "sl": sl, "at": out}


class CfgRows:
    """The rows one rule set can pick at each check, built as dicts only for
    the rows that clear ITS thresholds. `simulate` still applies
    `passes_on` to every one of them, so this can only ever hand it fewer
    rows that it would have thrown away itself."""

    def __init__(self, pre: dict, books: dict, cfg: dict):
        self.pre, self.books, self.cfg = pre, books, {**wp.DEFAULTS, **cfg}

    def get(self, at: int, default=None):
        got = self.pre["at"].get(at)
        if got is None:
            return default if default is not None else []
        k, n, w, pr = got
        c = self.cfg
        rate = np.round(100 * w / np.maximum(n, 1), 2)
        tp, sl = self.pre["tp"][k], self.pre["sl"][k]
        ok = ((n >= c["min_trades"]) & (rate >= c["on_winrate"])
              & (np.round(pr, 2) > c["profit_floor"])
              & ((tp > sl) if c["tp_rule"] == ">" else (tp >= sl)))
        ids = self.pre["ids"]
        return [_row_dict(self.books[ids[kk]].c, int(nn), int(ww), float(pp))
                for kk, nn, ww, pp in zip(k[ok], n[ok], w[ok], pr[ok])]


def research(folders: list[str], *, train_start: str = "2026-07-01",
             train_end: str = "2026-09-01", test_start: str = "2026-09-01",
             grid_: list[dict] | None = None, progress=None) -> dict:
    g = grid_ or grid()
    lo = loose(g)
    ms = lambda s: int(dt.datetime(*map(int, s.split("-"))).timestamp() * 1000)  # noqa: E731
    L = load_lean(folders)
    books, end = L["books"], L["end"]
    periods = {"train": (ms(train_start), ms(train_end) - 1),
               "test": (ms(test_start), end)}
    pre = {}
    for part, (a, b) in periods.items():
        checks = wr.local_midnights(a, b)
        for wd in sorted({c["window_days"] for c in g}):
            pre[(part, wd)] = compact_rows(books, checks, wd * wr.DAY_MS, lo)
    rows = []
    for i, cfg in enumerate(g):
        out = {"id": rule_id(cfg), "cfg": cfg}
        for part, (a, b) in periods.items():
            res = wr.simulate([], start_ms=a, end_ms=b, cfg=cfg,
                              rows=CfgRows(pre[(part, cfg["window_days"])], books, cfg),
                              books=books)
            out[part] = score(res, end_ms=b)
        rows.append(out)
        if progress and (i + 1) % 200 == 0:
            progress(i + 1, len(g))
    by_train = sorted(rows, key=lambda r: -r["train"]["profit"])
    cur = next(r for r in rows if r["id"] == rule_id(CURRENT))
    return {"train": list(periods["train"]), "test": list(periods["test"]),
            "end_ms": end, "totals": L["totals"], "combos": len(books),
            "grid": GRID, "current_id": cur["id"],
            "best_train_id": by_train[0]["id"], "rows": rows}


def main(argv=None) -> int:
    argv = list(argv or sys.argv[1:])
    name, folders = argv[0], argv[1:]
    res = research(folders, progress=lambda i, n: print(f"  {i:,} of {n:,} rule sets", flush=True))
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
