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

import bisect
import datetime as dt
import hashlib
import heapq
import itertools
import json
import os
import re
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
           "off_streak_live": 0, "max_slots": 100,
           # live since Sep 29, 2026 ("okay do it"): no stop wider than 2%
           "max_sl": 2.0}

GRID = {"on_winrate": [80.0, 85.0, 90.0, 95.0],
        "off_gap": [0.0, 5.0, 10.0],
        "min_trades": [15, 20, 30],
        "tp_rule": [">", ">="],
        "window_days": [14, 30],
        "rank": ["winrate", "profit"],
        "max_per_coin": [1, 3],
        "max_new_per_day": [5, 20],
        "cooldown_days": [0, 7],
        "off_streak_live": [0, 3],
        "max_sl": [2.0]}

# THE 100 SCENARIOS (operator, Sep 29, 2026: "Could you try other
# combination like 60% above, min trade of 30, think of 100 scennarios and
# look which has highest winrate and profitable"). Five switch-on lines x
# five trade floors x four shapes (TP wider than SL or any TP, stop capped at
# 2% or not); the switch-off line is the switch-on line, as the operator set
# it, and every other dial is theirs. 5 x 5 x 4 = 100, their live rules
# (90% / 20 trades / TP wider / 2% cap) among them.
SCENARIOS = {"on_winrate": [60.0, 70.0, 80.0, 90.0, 95.0],
             "min_trades": [10, 20, 30, 40, 50],
             "shape": [(">", 2.0), (">", 0.0), ("any", 2.0), ("any", 0.0)]}


def scenarios() -> list[dict]:
    out = []
    for on in SCENARIOS["on_winrate"]:
        for mt in SCENARIOS["min_trades"]:
            for tp_rule, max_sl in SCENARIOS["shape"]:
                out.append({**CURRENT, "on_winrate": on, "off_winrate": on,
                            "min_trades": mt, "tp_rule": tp_rule, "max_sl": max_sl})
    assert len(out) == 100
    assert any(all(c[k] == v for k, v in CURRENT.items()) for c in out)
    return out


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
    vals = {k: cfg[k] for k in sorted(CURRENT)}
    # the smallest target (Oct 01, 2026) joins the id only when it is set, so
    # every id made before it — #55D32617 and the other room names — is unchanged
    if float(cfg.get("min_tp") or 0) > 0:
        vals["min_tp"] = float(cfg["min_tp"])
    key = json.dumps(vals, sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()[:8].upper()


def loose(grid_: list[dict]) -> dict:
    """The loosest on-rule any rule set in the grid uses — every row that
    could ever be a candidate passes it."""
    rules = {c["tp_rule"] for c in grid_}
    caps = [float(c.get("max_sl") or 0) for c in grid_]
    # the narrowest rule whose shapes cover every rule in the grid
    # (research_page.SHAPES): "<" with anything else, or "any", is no rule
    tp = (">" if rules <= {">"} else "=" if rules == {"="} else "<" if rules == {"<"}
          else ">=" if rules <= {">", ">=", "="} else "any")
    return {**wp.DEFAULTS, "on_winrate": min(c["on_winrate"] for c in grid_),
            "min_trades": min(c["min_trades"] for c in grid_),
            "tp_rule": tp,
            # 0 = no cap: the loosest cap is none at all if any set has none
            "max_sl": 0.0 if min(caps) <= 0 else max(caps),
            # and the loosest target floor is the lowest one
            "min_tp": min(float(c.get("min_tp") or 0) for c in grid_),
            "raw": any(c.get("raw") for c in grid_)}


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


def _cut_trades(t: np.ndarray, end: float) -> np.ndarray:
    """Nothing entered after the data's common end; a trade that closed after
    it is still open there."""
    t = t[t[:, 0] < end]
    late = (t[:, 3] > 0) & (t[:, 1] > end)
    t[late, 2] = 0.0
    t[late, 3] = 0.0
    return t


# COMPACT TRADES (Sep 30, 2026): the raw round switches on tens of thousands
# of strategies per rule set, and reading each one's trades back from the
# 2.3 GB of lines on G: ran at ~97 CPU-seconds per half hour while the disk
# served a v2 index rebuild beside it. Held in memory instead, at 13 bytes a
# trade (int32 seconds from T0, float32 profit, a closed flag) against 32 as
# float64 — 0.8 GB for 60,485,822 trades — and turned back into the
# (n, 4) float64 array each time a replay asks.
T0 = 1_767_225_600          # Jan 01, 2026 00:00 UTC, the zero of the int32 seconds


def _pack(t: np.ndarray) -> tuple:
    return ((t[:, 0] // 1000 - T0).astype(np.int32), (t[:, 1] // 1000 - T0).astype(np.int32),
            t[:, 2].astype(np.float32), t[:, 3] > 0)


def _unpack(pk: tuple) -> np.ndarray:
    ent, ext, pnl, closed = pk
    out = np.empty((len(ent), 4), dtype=np.float64)
    out[:, 0] = (ent.astype(np.int64) + T0) * 1000
    out[:, 1] = (ext.astype(np.int64) + T0) * 1000
    out[:, 2] = pnl.astype(np.float64)
    out[:, 3] = closed
    return out


class _PackedMeta(dict):
    """A book's `.c` whose "trades" live packed in memory and are unpacked
    on every ask (never kept unpacked: that would undo the saving)."""

    pk: tuple = ()

    def __missing__(self, key):
        if key != "trades":
            raise KeyError(key)
        return _unpack(self.pk)


class _LazyMeta(dict):
    """A book's `.c`: every field at hand, its "trades" read from its line on
    disk when first asked, cut exactly as load_lean cut it, and then kept."""

    src: tuple = ()

    def __missing__(self, key):
        if key != "trades":
            raise KeyError(key)
        path, off, end = self.src
        with open(path, "rb") as fh:
            fh.seek(off)
            c = json.loads(fh.readline())
        t = _cut_trades(np.asarray(c.get("trades") or [], dtype=np.float64).reshape(-1, 4), end)
        self["trades"] = t
        return t


class ArrBook:
    """`watcher_replay._Book`, backed by numpy arrays: the same `row()`, the
    same `.c` (whose "trades" is an (n, 4) array: entry_ms, exit_ms, pnl,
    closed), a fraction of the memory."""

    __slots__ = ("c", "exits", "w", "p")

    def __init__(self, meta: dict, trades: np.ndarray, src: tuple | None = None,
                 packed: bool = False):
        # `src` = (file, byte offset, end_ms): the trades are NOT kept — they
        # are read back from disk the first time `.c["trades"]` is asked,
        # which `simulate` does only for a strategy some rule switched on.
        # Measured Sep 29, 2026: run 36648844400 carries 60,485,822 trades
        # over 354,791 combinations; held as (n, 4) float64 that is 1.9 GB
        # on top of the counts, on a machine with 6.1 GB free.
        if packed:
            self.c = _PackedMeta(meta)
            self.c.pk = _pack(trades)
        elif src is None:
            self.c = {**meta, "trades": trades}
        else:
            self.c = _LazyMeta(meta)
            self.c.src = src
        closed = trades[trades[:, 3] > 0]
        closed = closed[np.argsort(closed[:, 1], kind="stable")]
        self.exits = closed[:, 1].astype(np.int64)
        self.w = np.concatenate([[0], np.cumsum(closed[:, 2] > 0)]).astype(
            np.int64 if (src is None and not packed) else np.int32)
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


def load_lean(folders: list[str], lazy: bool = False, packed: bool = True,
              end_ms: int | None = None) -> dict:
    """Every combination of the runs, as ArrBooks, cut to the common end —
    or to `end_ms`, the WHOLE run's end, when one machine loads only its own
    shard (research on GitHub, Sep 30, 2026)."""
    got_tot = rc.merge_reports(folders)
    end = int(end_ms) if end_ms else rc.common_end(got_tot["spans"])
    books: dict = {}
    for f in rc.combo_files(folders):
        with open(f, "rb") as fh:
            while True:
                off = fh.tell()
                line = fh.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                c = json.loads(line)
                if c["id"] in books:
                    continue
                t = _cut_trades(np.asarray(c.pop("trades") or [],
                                           dtype=np.float64).reshape(-1, 4), end)
                c.setdefault("group", rc.group_of(c["signal"]))
                books[c["id"]] = ArrBook(c, t, src=(str(f), off, end) if lazy else None,
                                         packed=packed and not lazy)
    return {"books": books, "end": end, "totals": got_tot}


# BATCHES OF WHOLE COINS (prompt 4, Oct 02, 2026): replay run 37007971331
# was written at 40% / 1 trade / any TP, and its shard 8 held 1,574,489
# combinations and 206,094,384 trades. load_lean's books (~33 bytes a
# trade), Flat (~21) and a loose rule set's walk (~100+ bytes for every trade
# it keeps — the loosest keeps nearly all of them) went past a GitHub
# machine's 16 GB, and the runner was shut down mid-run. A raw rule set never
# looks across coins (no slot, daily or total cap; the 4-per-coin limit is
# inside one coin), so a shard measured coin batch by coin batch adds up to
# exactly the shard measured at once — tests/test_research_every_shape.py
# holds the two equal.
_HEAD = re.compile(rb'^\{"id":"([^"]*)","coin":"([^"]*)"')


def coin_batches(folders: list[str], max_bytes: int) -> list[list[tuple[str, int]]]:
    """The combination lines of `folders` as batches of WHOLE coins, each
    about `max_bytes` of text (a coin bigger than that is a batch of its
    own): the (file, byte offset) of every id's FIRST line, the one load_lean
    keeps. One pass that reads each line's id and coin only."""
    seen: set = set()
    by_coin: dict = {}
    for f in rc.combo_files(folders):
        with open(f, "rb") as fh:
            off = 0
            for line in fh:
                n = len(line)
                if line.strip():
                    m = _HEAD.match(line)
                    if m:
                        cid, coin = m.group(1).decode(), m.group(2).decode()
                    else:
                        c = json.loads(line)
                        cid, coin = c["id"], c["coin"]
                    if cid not in seen:
                        seen.add(cid)
                        e = by_coin.setdefault(coin, [[], 0])
                        e[0].append((f, off))
                        e[1] += n
                off += n
    batches: list = []
    cur: list = []
    size = 0
    for coin in sorted(by_coin):
        locs, n = by_coin[coin]
        if cur and size + n > max_bytes:
            batches.append(cur)
            cur, size = [], 0
        cur.extend(locs)
        size += n
    if cur:
        batches.append(cur)
    return batches


def load_batch(locs: list[tuple[str, int]], end_ms: int, packed: bool = True) -> list:
    """The ArrBooks of one coin_batches batch, each cut to `end_ms` exactly
    as load_lean cuts it."""
    books = []
    handles: dict = {}
    try:
        for f, off in locs:
            fh = handles.get(f)
            if fh is None:
                fh = handles[f] = open(f, "rb")
            fh.seek(off)
            c = json.loads(fh.readline())
            t = _cut_trades(np.asarray(c.pop("trades") or [], dtype=np.float64).reshape(-1, 4),
                            int(end_ms))
            c.setdefault("group", rc.group_of(c["signal"]))
            books.append(ArrBook(c, t, packed=packed))
    finally:
        for fh in handles.values():
            fh.close()
    return books


def compact_rows(books: dict, checks: list[int], window_ms: int, lo: dict) -> dict:
    """{check: arrays of the rows that pass the loosest rule}: book index,
    trades, wins, profit — the rows `rows_by_check` would build, minus those
    no rule set could pick, in four arrays instead of a dict each."""
    ids = list(books)
    tp = np.array([books[i].c["tp"] for i in ids])
    sl = np.array([books[i].c["sl"] for i in ids])
    gate = np.array([books[i].c.get("gate", "ok") == "ok" for i in ids])
    tp_ok = _tp_ok(tp, sl, lo["tp_rule"]) & _sl_ok(sl, lo.get("max_sl"))
    out = {}
    for at in checks:
        n = np.zeros(len(ids), np.int64)
        w = np.zeros(len(ids), np.int64)
        pr = np.zeros(len(ids))
        for k, i in enumerate(ids):
            n[k], w[k], pr[k] = books[i].counts(at, window_ms)
        rate = np.where(n > 0, 100 * w / np.maximum(n, 1), 0.0)
        money = (np.ones(len(ids), bool) if lo.get("raw")
                 else (np.round(pr, 2) > lo["profit_floor"]) & gate)
        keep = ((n >= lo["min_trades"]) & (np.round(rate, 2) >= lo["on_winrate"])
                & money & tp_ok)
        k = np.nonzero(keep)[0]
        out[at] = (k, n[k], w[k], pr[k])
    return {"ids": ids, "tp": tp, "sl": sl, "at": out}


def _tp_ok(tp, sl, rule):
    """`passes_on`'s TP rule over arrays: ">" wider, ">=" at least, "=" equal,
    "<" narrower, "any" none."""
    if rule == "any":
        return np.ones(np.shape(tp), bool)
    if rule == "<":
        return tp < sl
    if rule == "=":
        return np.abs(np.asarray(tp) - np.asarray(sl)) < 1e-6
    # the target at least 1.5x / 2x the stop (Forecast v2's shapes, prompt 4)
    if rule == "1.5x":
        return np.asarray(tp) >= 1.5 * np.asarray(sl) - 1e-9
    if rule == "2x":
        return np.asarray(tp) >= 2.0 * np.asarray(sl) - 1e-9
    return tp > sl if rule == ">" else tp >= sl


def _min_tp_ok(tp, floor):
    """`passes_on`'s smallest target over arrays; 0 or None is no floor."""
    floor = float(floor or 0)
    return np.ones(np.shape(tp), bool) if floor <= 0 else np.asarray(tp) >= floor - 1e-9


def _sl_ok(sl, cap):
    """`passes_on`'s stop cap over arrays; 0 or None is no cap."""
    cap = float(cap or 0)
    return np.ones(np.shape(sl), bool) if cap <= 0 else sl <= cap


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
              & ((np.round(pr, 2) > c["profit_floor"]) if not c.get("raw")
                 else np.ones(len(n), bool))
              & _tp_ok(tp, sl, c["tp_rule"]) & _sl_ok(sl, c.get("max_sl")))
        ids = self.pre["ids"]
        return [_row_dict(self.books[ids[kk]].c, int(nn), int(ww), float(pp))
                for kk, nn, ww, pp in zip(k[ok], n[ok], w[ok], pr[ok])]


def research(folders: list[str], *, train_start: str = "2026-07-01",
             train_end: str = "2026-09-01", test_start: str = "2026-09-01",
             grid_: list[dict] | None = None, progress=None,
             keep_log: bool = False) -> dict:
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
    # THE TRADE-BY-TRADE LOG of the test period (kit B): each closed trade is
    # [strategy index, entry_ms, exit_ms, pnl], the strategies listed once in
    # `strategies` — only with `keep_log`, because 4,608 rule sets of logs
    # would not fit a page; the 100 scenarios do.
    strat_ix: dict = {}
    strategies: list = []
    for i, cfg in enumerate(g):
        out = {"id": rule_id(cfg), "cfg": cfg}
        for part, (a, b) in periods.items():
            res = wr.simulate([], start_ms=a, end_ms=b, cfg=cfg,
                              rows=CfgRows(pre[(part, cfg["window_days"])], books, cfg),
                              books=books)
            out[part] = score(res, end_ms=b)
            if keep_log and part == "test":
                log = []
                for sl_ in res["slots"]:
                    sid = sl_["id"]
                    if sid not in strat_ix:
                        c = books[sid].c
                        strat_ix[sid] = len(strategies)
                        strategies.append([sid, c["coin"], c["tf"], c["signal"],
                                           float(c.get("th", 0.0)), float(c["tp"]),
                                           float(c["sl"])])
                    for t in sl_["trades"]:
                        if t[3] and t[1] <= b:
                            log.append([strat_ix[sid], int(t[0]), int(t[1]),
                                        round(float(t[2]), 4)])
                log.sort(key=lambda t: t[2])
                # compact until written: 144 raw rule sets of September trades
                # held as lists of lists would be gigabytes
                out["test_log"] = np.asarray(log, dtype=np.float64).reshape(-1, 4)
        rows.append(out)
        if progress and (i + 1) % max(1, min(200, len(g) // 12)) == 0:
            progress(i + 1, len(g))
    by_train = sorted(rows, key=lambda r: -r["train"]["profit"])
    # "yours" is the operator's own rules as the grid runs them — raw in
    # round three, where the limited CURRENT is not a grid point
    ids_ = {r["id"] for r in rows}
    want = rule_id(CURRENT) if rule_id(CURRENT) in ids_ else rule_id({**CURRENT, **RAW})
    cur = next((r for r in rows if r["id"] == want), rows[0])
    return {"train": list(periods["train"]), "test": list(periods["test"]),
            "end_ms": end, "totals": L["totals"], "combos": len(books),
            "grid": GRID if grid_ is None else SCENARIOS_TEXT,
            "current_id": cur["id"],
            "best_train_id": by_train[0]["id"], "rows": rows,
            "strategies": strategies}


# ROUND TWO (operator, Sep 29, 2026: "Can you research more combination, you
# can try sl greater than tp then up to you what is winrate"): the target
# NARROWER than the stop joins wider and any; five lines from 70 to 95; four
# trade floors (40 makes #CC8DC54C a grid point). 5 x 4 x 3 x 2 = 120, every
# room's rules among them.
SCENARIOS2 = {"on_winrate": [70.0, 80.0, 85.0, 90.0, 95.0],
              "min_trades": [20, 30, 40, 50],
              "tp_rule": ["<", ">", "any"],
              "max_sl": [2.0, 0.0]}


def scenarios2() -> list[dict]:
    out = [{**CURRENT, "on_winrate": on, "off_winrate": on, "min_trades": mt,
            "tp_rule": tr, "max_sl": cap}
           for on in SCENARIOS2["on_winrate"] for mt in SCENARIOS2["min_trades"]
           for tr in SCENARIOS2["tp_rule"] for cap in SCENARIOS2["max_sl"]]
    assert len(out) == 120
    assert any(all(c[k] == v for k, v in CURRENT.items()) for c in out)
    return out


# ------------------------------------------------------------ the fast raw path
# RAW HAS NO RULE THAT LINKS TWO ROWS except the runner's 4 trades per coin,
# so it does not need simulate's check-by-check picking (Sep 30, 2026: the
# 50% / 10-trade data is 4,585,414 combinations and ~734M trades, and at 50%
# tens of thousands of rows pass every midnight). A row is ON from the check
# where it passes the criteria until the check where its window reads empty
# or under the off line — exactly simulate's two steps — which is a
# numpy walk over checks x books. Then each on-interval takes its trades,
# cap_per_coin applies, and the result has the shape score() reads, so both
# paths are scored by one function (test_the_fast_raw_path_is_simulate).


def count_grid(books: list, checks: list[int], window_ms: int) -> tuple:
    """(N, W): closed trades and wins in each book's window ending at each
    check, as (checks x books) int32 arrays — `ArrBook.counts` for all at once."""
    ck = np.asarray(checks, dtype=np.int64)
    N = np.zeros((len(ck), len(books)), dtype=np.int32)
    W = np.zeros_like(N)
    for i, b in enumerate(books):
        if not len(b.exits):
            continue
        a = np.searchsorted(b.exits, ck - window_ms, "left")
        z = np.searchsorted(b.exits, ck, "right")
        N[:, i] = z - a
        W[:, i] = b.w[z] - b.w[a]
    return N, W


_TPSL: dict = {}


def _tp_sl(books: list) -> tuple:
    """(tp, sl) arrays for a book list, made once per list (a grid of rule
    sets asks for the same list thousands of times)."""
    key = (id(books), len(books))
    hit = _TPSL.get(key)
    if hit is None or hit[0] is not books:
        hit = (books, np.array([float(b.c["tp"]) for b in books]),
               np.array([float(b.c["sl"]) for b in books]))
        _TPSL.clear()
        _TPSL[key] = hit
    return hit[1], hit[2]


def raw_fast(books: list, grid: tuple, checks: list[int], cfg: dict, end_ms: int) -> dict:
    """simulate() for a RAW rule set, from the (N, W) grid of count_grid."""
    from tradingagents import watcher_replay as wr_

    c = {**wp.DEFAULTS, **cfg}
    N, W = grid
    tp, sl = _tp_sl(books)
    # ONLY THE ROWS THIS RULE SET CAN EVER PICK (Oct 01, 2026): the target
    # shape, the stop cap and the target floor never change over time, so the
    # rest are dropped before the walk — a rule set's cost follows ITS rows,
    # and a grid of thousands of rule sets fits a GitHub machine's six hours.
    keep = np.nonzero(_tp_ok(tp, sl, c["tp_rule"]) & _sl_ok(sl, c.get("max_sl"))
                      & _min_tp_ok(tp, c.get("min_tp")))[0]
    books = [books[i] for i in keep]
    N, W = N[:, keep], W[:, keep]
    rate = np.round(100.0 * W / np.maximum(N, 1), 2)
    passon = (N >= int(c["min_trades"])) & (N > 0) & (rate >= float(c["on_winrate"]))
    off = (N == 0) | (rate < float(c["off_winrate"]))
    on = np.zeros(len(books), dtype=bool)
    open_slot = np.full(len(books), -1, dtype=np.int64)
    ids = [b.c["id"] for b in books]
    slots: list = []                   # [book, on_ms, off_ms] in SWITCH-ON order
    for k, at in enumerate(checks):
        stop = on & off[k]
        for i in np.nonzero(stop)[0]:
            slots[open_slot[i]][2] = int(at)
        on &= ~stop
        start = np.nonzero(~on & passon[k])[0]
        # simulate appends a check's picks in pick()'s own order — best win
        # rate, then most trades, then id — and cap_per_coin gives a tie in
        # the same minute to the slot switched on first, so the ORDER is part
        # of the answer (found: 10,067 against simulate's 10,692 without it)
        order = sorted(start, key=lambda i: (-rate[k, i], -int(N[k, i]), ids[i]))
        for i in order:
            open_slot[i] = len(slots)
            slots.append([int(i), int(at), None])
        on[start] = True
    out = []
    for i, a, z in slots:
        tr = books[i].c["trades"]
        hi = float("inf") if z is None else z
        b = books[i].c
        out.append({"id": b["id"], "coin": b["coin"], "tf": b["tf"], "signal": b["signal"],
                    "th": b.get("th", 0.0), "sl": b["sl"], "tp": b["tp"],
                    "group": b.get("group", "classic"), "on_ms": a, "off_ms": z,
                    "trades": tr[(tr[:, 0] >= a) & (tr[:, 0] < hi)]})
    if int(c.get("coin_slices") or 0) > 0:
        wr_.cap_per_coin(out, int(c["coin_slices"]))
    for s_ in out:
        wr_._totals(s_)
    return {"days": wr_._days(out, [], checks, end_ms), "slots": out, "events": [],
            "summary": wr_._summary(out, checks, end_ms)}


# ---------------------------------------------------------- raw, as arrays
# THE GRID OF EVERY SHAPE (Oct 01, 2026: "look for best posible room
# combination ... different winrate, tp sl, number of trades criteria ...
# currently i think you are avoiding sl is greater than tp or avoiding tp that
# is very high but low trade"). Thousands of rule sets, each switching on up to
# hundreds of thousands of strategies on a loose rule: raw_fast spent 38 s of
# one such rule on Python per switch-on and per trade (cProfile: 14.4 s in
# cap_per_coin over 3.6M trades, 7.6 s unpacking 325,904 slots). raw_trades
# is the same answer as arrays - held equal to raw_fast by a test - and only
# what the GitHub shard needs: every kept trade, its strategy, and the counts.

SPAN = 1 << 31            # every int32 entry second fits below one book's span


class Flat:
    """Every book's trades in one set of arrays, each book's run sorted by
    entry (stably, so equal entries keep their order), plus the per-book coin
    and id rank the per-coin limit and the pick order need. Built once per
    book list."""

    def __init__(self, books: list):
        lens = np.fromiter((len(b.c.pk[0]) if isinstance(b.c, _PackedMeta) else len(b.c["trades"])
                            for b in books), dtype=np.int64, count=len(books))
        self.off = np.concatenate([[0], np.cumsum(lens)]).astype(np.int64)
        n = int(self.off[-1])
        self.ent = np.empty(n, np.int32)
        self.ext = np.empty(n, np.int32)
        self.pnl = np.empty(n, np.float32)
        self.closed = np.empty(n, bool)
        for i, b in enumerate(books):
            pk = b.c.pk if isinstance(b.c, _PackedMeta) else _pack(b.c["trades"])
            o = np.argsort(pk[0], kind="stable")
            a, z = self.off[i], self.off[i + 1]
            self.ent[a:z], self.ext[a:z] = pk[0][o], pk[1][o]
            self.pnl[a:z], self.closed[a:z] = pk[2][o], pk[3][o]
        coins = [b.c["coin"] for b in books]
        uniq = {c: k for k, c in enumerate(sorted(set(coins)))}
        self.coin = np.fromiter((uniq[c] for c in coins), dtype=np.int32, count=len(books))
        ids = [b.c["id"] for b in books]
        rank = np.empty(len(ids), np.int64)
        rank[np.argsort(np.array(ids, dtype=object), kind="stable")] = np.arange(len(ids))
        self.id_rank = rank
        # one sorted key over every trade, (book, entry), so each switch-on's
        # trades are found by ONE vectorised search, not a loop per slot
        self.key = np.repeat(np.arange(len(books), dtype=np.int64), lens) * SPAN + self.ent


def _starts(N: np.ndarray, W: np.ndarray, checks: list, c: dict, ids_rank: np.ndarray):
    """Every switch-on of raw_fast's walk, in its order: (book, on_ms, off_ms
    or -1). The same state machine - a check first switches off what fell
    under the off line, then switches on what passes - with the pick order
    (best win rate, most trades, id) as one sort key."""
    rate = np.round(100.0 * W / np.maximum(N, 1), 2)
    passon = (N >= int(c["min_trades"])) & (N > 0) & (rate >= float(c["on_winrate"]))
    off = (N == 0) | (rate < float(c["off_winrate"]))
    nb = N.shape[1]
    on = np.zeros(nb, bool)
    cur = np.full(nb, -1, np.int64)
    book, on_ms, k_of, r_of, n_of = [], [], [], [], []
    count = 0
    stop_slot, stop_at = [], []
    for k, at in enumerate(checks):
        stop = on & off[k]
        if stop.any():
            stop_slot.append(cur[stop])
            stop_at.append(np.full(int(stop.sum()), int(at), np.int64))
        on &= ~stop
        start = np.nonzero(~on & passon[k])[0]
        if len(start):
            book.append(start)
            on_ms.append(np.full(len(start), int(at), np.int64))
            k_of.append(np.full(len(start), k, np.int64))
            r_of.append(rate[k, start])
            n_of.append(N[k, start].astype(np.int64))
            cur[start] = np.arange(count, count + len(start))
            count += len(start)
            on[start] = True
    if not count:
        z = np.zeros(0, np.int64)
        return z, z, z
    book = np.concatenate(book)
    k_of, r_of, n_of = np.concatenate(k_of), np.concatenate(r_of), np.concatenate(n_of)
    on_ms = np.concatenate(on_ms)
    off_ms = np.full(count, -1, np.int64)
    if stop_slot:                     # a slot is switched off at most once
        off_ms[np.concatenate(stop_slot)] = np.concatenate(stop_at)
    order = np.lexsort((ids_rank[book], -n_of, -r_of, k_of))
    return book[order], on_ms[order], off_ms[order]


def _cap(coin: np.ndarray, ent: np.ndarray, ext: np.ndarray, closed: np.ndarray,
         slot: np.ndarray, n: int) -> np.ndarray:
    """cap_per_coin over arrays: which candidate trades the runner's `n` open
    per coin lets through - first come, first served by entry, a tie going to
    the slot switched on first; a trade still open is open for ever. A coin
    whose candidates never overlap more than `n` deep keeps all of them
    without walking it."""
    keep = np.ones(len(ent), bool)
    if not len(ent):
        return keep
    if (len(slot) < 2 or bool((slot[1:] >= slot[:-1]).all())) and int(ent.min()) >= 0 \
            and int(ent.max()) < 2 ** 32:
        # raw_trades hands the candidates over slot by slot, so one STABLE
        # sort on (coin, entry) leaves a tie in slot order — lexsort's answer
        # in one pass instead of three (entries are int32 seconds, >= 0)
        o = np.argsort((coin.astype(np.int64) << 32) | ent.astype(np.int64), kind="stable")
    else:
        o = np.lexsort((slot, ent, coin))
    c_s, e_s = coin[o], ent[o].astype(np.int64)
    x_s = np.where(closed[o], ext[o].astype(np.int64), np.iinfo(np.int64).max)
    bounds = np.flatnonzero(np.diff(c_s)) + 1
    for a, z in zip(np.r_[0, bounds], np.r_[bounds, len(o)]):
        if z - a <= n:
            continue
        # the deepest overlap if every candidate were taken: an exit at the
        # very moment of an entry is no longer open (x > entry), so exits
        # sort before entries at a tie
        ev_t = np.concatenate([e_s[a:z], x_s[a:z]])
        ev_d = np.concatenate([np.ones(z - a, np.int64), -np.ones(z - a, np.int64)])
        oo = np.lexsort((ev_d, ev_t))
        if np.cumsum(ev_d[oo]).max() <= n:
            continue
        # FULL MEANS EVERYTHING UNTIL THE FIRST CLOSE IS REFUSED: with `n`
        # open, every candidate entering before the earliest of their exits is
        # turned away, so that whole run is skipped in one step (the loop
        # walked 3.6M refused trades one by one on a loose rule: 13.6 s)
        es, xs = e_s[a:z].tolist(), x_s[a:z].tolist()
        heap: list = []
        j, m = 0, z - a
        while j < m:
            e = es[j]
            while heap and heap[0] <= e:      # closed by now (open means x > e)
                heapq.heappop(heap)
            if len(heap) >= n:
                nxt = bisect.bisect_left(es, heap[0], j)
                keep[o[a + j:a + nxt]] = False
                j = nxt
                continue
            heapq.heappush(heap, xs[j])
            j += 1
    return keep


def starts_key(cfg: dict) -> tuple:
    """What _starts depends on besides the grid: rule sets that differ only
    in their target shape, stop cap or target floor share one walk."""
    c = {**wp.DEFAULTS, **cfg}
    return (int(c["window_days"]), int(c["min_trades"]), float(c["on_winrate"]),
            float(c["off_winrate"]))


def all_starts(flat: "Flat", grid: tuple, checks: list[int], cfg: dict) -> tuple:
    """_starts over EVERY book, for raw_trades(starts=): each book's
    switch-ons depend on its own counts only (a raw rule set has no cap that
    links books), so a rule set's slots are these, filtered to the books its
    target shape, stop cap and target floor allow — in the same order."""
    c = {**wp.DEFAULTS, **cfg}
    N, W = grid
    return _starts(N, W, checks, c, flat.id_rank)


def raw_trades(books: list, flat: "Flat", grid: tuple, checks: list[int], cfg: dict,
               end_ms: int, starts: tuple | None = None) -> dict:
    """raw_fast's answer as arrays: {"book", "ent", "ext", "pnl", "closed"}
    for every trade the rule set keeps (ms, after the per-coin limit), plus
    "slots" and "open" as raw_fast's summary counts them. `starts` is
    all_starts() for this grid and starts_key(cfg), shared by every rule set
    with that key (research_shard: 8,568 rule sets, 288 keys)."""
    c = {**wp.DEFAULTS, **cfg}
    N, W = grid
    tp, sl = _tp_sl(books)
    allow = (_tp_ok(tp, sl, c["tp_rule"]) & _sl_ok(sl, c.get("max_sl"))
             & _min_tp_ok(tp, c.get("min_tp")))
    if starts is None:
        keep = np.nonzero(allow)[0]
        b_sub, on_ms, off_ms = _starts(N[:, keep], W[:, keep], checks, c, flat.id_rank[keep])
        book = keep[b_sub]
    else:
        b_all, on_all, off_all = starts
        m = allow[b_all] if len(b_all) else np.zeros(0, bool)
        book, on_ms, off_ms = b_all[m], on_all[m], off_all[m]
    empty = {"book": np.zeros(0, np.int64), "ent": np.zeros(0, np.int64),
             "ext": np.zeros(0, np.int64), "pnl": np.zeros(0), "closed": np.zeros(0, bool),
             "slots": int(len(book)), "open": 0}
    if not len(book):
        return empty
    # each slot's trades: its book's run, entries in [on, off) — one search
    # over the (book, entry) key; a slot never switched off runs to the end
    # of its book's span
    base = book.astype(np.int64) * SPAN
    lo = np.searchsorted(flat.key, base + (on_ms // 1000 - T0), "left")
    hi = np.searchsorted(flat.key, base + np.where(off_ms < 0, SPAN, off_ms // 1000 - T0), "left")
    cnt = hi - lo
    tot = int(cnt.sum())
    if not tot:
        return {**empty, "slots": int(len(book))}
    slot_of = np.repeat(np.arange(len(book)), cnt)
    idx = np.arange(tot) - np.repeat(np.cumsum(cnt) - cnt, cnt) + np.repeat(lo, cnt)
    n = int(c.get("coin_slices") or 0)
    ok = (_cap(flat.coin[book][slot_of], flat.ent[idx], flat.ext[idx], flat.closed[idx],
               slot_of, n) if n > 0 else np.ones(tot, bool))
    sel = idx[ok]
    return {"book": book[slot_of[ok]],
            "ent": (flat.ent[sel].astype(np.int64) + T0) * 1000,
            "ext": (flat.ext[sel].astype(np.int64) + T0) * 1000,
            "pnl": flat.pnl[sel].astype(np.float64), "closed": flat.closed[sel],
            "slots": int(len(book)), "open": int((~flat.closed[sel]).sum())}


# ROUND THREE — RAW (operator, Sep 30, 2026: "can you create a strategy
# again on what's best combination to use / generate top 100 then show me in
# artefact, because the previous you gave me has limit of 20 per day"). Every
# rule set is replayed the way the rooms now run: every matching row on, no
# daily/total/per-coin cap, no wait, no profit floor or stored cost verdict —
# and the runner's own 4 open trades per coin (`coin_slices`). 6 x 4 x 3 x 2
# = 144; the data (run 36648844400) was written at 70% / 20 trades / any TP.
SCENARIOS3 = {"on_winrate": [70.0, 75.0, 80.0, 85.0, 90.0, 95.0],
              "min_trades": [20, 30, 40, 50],
              "tp_rule": [">", "<", "any"],
              "max_sl": [2.0, 0.0]}
RAW = {"raw": True, "max_new_per_day": 0, "max_slots": 0, "max_per_coin": 0,
       "cooldown_days": 0, "coin_slices": 4}


def scenarios3() -> list[dict]:
    out = [{**CURRENT, **RAW, "on_winrate": on, "off_winrate": on, "min_trades": mt,
            "tp_rule": tr, "max_sl": cap}
           for on in SCENARIOS3["on_winrate"] for mt in SCENARIOS3["min_trades"]
           for tr in SCENARIOS3["tp_rule"] for cap in SCENARIOS3["max_sl"]]
    assert len(out) == 144
    return out


# ROUND FOUR (operator, Sep 30, 2026: "have you tried last 15 days when
# searching for most profitable? example winrate over 50% last 15 days, tp
# higher than sl with 10 trades ... research for best combination"). Raw, as
# the rooms run, with the runner's 4 per coin; judged on 15 or 30 days. The
# data (run 36763426504) is written at 50% / 10 trades / TP > SL / 15|30 days,
# so no rule here is looser than it (RCA-2026-09-29-F).
SCENARIOS4 = {"window_days": [15, 30],
              "on_winrate": [50.0, 55.0, 60.0, 65.0, 70.0, 80.0, 90.0],
              "min_trades": [10, 20, 30],
              "max_sl": [2.0, 0.0]}


def scenarios4() -> list[dict]:
    out = [{**CURRENT, **RAW, "window_days": wd, "on_winrate": on, "off_winrate": on,
            "min_trades": mt, "tp_rule": ">", "max_sl": cap}
           for wd in SCENARIOS4["window_days"] for on in SCENARIOS4["on_winrate"]
           for mt in SCENARIOS4["min_trades"] for cap in SCENARIOS4["max_sl"]]
    assert len(out) == 84
    # "yours" is a grid point: the operator's Main rules (90% / 20+ / 2%), raw, 30 days
    assert any(all(c[k] == v for k, v in {**CURRENT, **RAW}.items()) for c in out)
    return out


# ROUND FIVE — the full 50% / 10-trade grid (operator, Sep 30, 2026: "show
# me the result for top 100 combinations so i can decide which to deploy").
# 2 windows x 9 lines x 4 trade floors x 2 SL caps = 144, raw, target wider
# than stop, the runner's 4 per coin. Measured on GitHub, one coin-whole
# shard per machine (.github/workflows/research.yml), with raw_fast.
SCENARIOS5 = {"window_days": [15, 30],
              "on_winrate": [50.0, 55.0, 60.0, 65.0, 70.0, 75.0, 80.0, 85.0, 90.0],
              "min_trades": [10, 20, 30, 50],
              "max_sl": [2.0, 0.0]}


def scenarios5() -> list[dict]:
    out = [{**CURRENT, **RAW, "window_days": wd, "on_winrate": on, "off_winrate": on,
            "min_trades": mt, "tp_rule": ">", "max_sl": cap}
           for wd in SCENARIOS5["window_days"] for on in SCENARIOS5["on_winrate"]
           for mt in SCENARIOS5["min_trades"] for cap in SCENARIOS5["max_sl"]]
    assert len(out) == 144
    assert any(all(c[k] == v for k, v in {**CURRENT, **RAW}.items()) for c in out)
    return out


# ROUND SIX — EVERY SHAPE (operator, Oct 01, 2026: "look for best posible
# room combination ... different winrate, tp sl, number of trades criteria?
# because currently i think you are avoiding sl is greater than tp or avoiding
# tp that is very high but low trade"). 3 windows x 6 lines x 7 trade floors x
# 4 target shapes x 4 stop caps x 4 target floors = 8,064, raw, the runner's
# 4 per coin. Its data must be written no stricter than its loosest rule
# (SCENARIOS6_WRITE) or the looser sets lean on hindsight (RCA-2026-09-29-F).
SCENARIOS6 = {"window_days": [7, 15, 30],
              "on_winrate": [40.0, 50.0, 60.0, 70.0, 80.0, 90.0],
              "min_trades": [1, 3, 5, 10, 20, 30, 50],
              "tp_rule": ["any", ">", "=", "<"],
              "max_sl": [0.0, 1.0, 2.0, 3.0],
              "min_tp": [0.0, 1.0, 2.0, 3.0]}
SCENARIOS6_WRITE = "wr=40,trades=1,tp=any,windows=7|15|30"


def scenarios6() -> list[dict]:
    out = [{**CURRENT, **RAW, "window_days": wd, "on_winrate": on, "off_winrate": on,
            "min_trades": mt, "tp_rule": tr, "max_sl": cap, "min_tp": ft}
           for wd in SCENARIOS6["window_days"] for on in SCENARIOS6["on_winrate"]
           for mt in SCENARIOS6["min_trades"] for tr in SCENARIOS6["tp_rule"]
           for cap in SCENARIOS6["max_sl"] for ft in SCENARIOS6["min_tp"]]
    assert len(out) == 8064
    return out


def chunk_of(grid_: list, chunk: int, chunks: int) -> list:
    """Rule sets `chunk` of `chunks` (0-based), DEALT like cards — every
    `chunks`-th rule set — so each slice gets the same mix of loose and strict
    rules. Consecutive runs put grid 6's loosest (40%, 1 trade, measured ~2 s
    each against a 0.59 s average) all in the first slice. Rule set j of slice
    c is grid rule j * chunks + c; the merge puts them back in grid order."""
    k = max(1, int(chunks))
    return grid_[int(chunk)::k]


SCENARIOS_TEXT = {"on_winrate": SCENARIOS["on_winrate"],
                  "min_trades": SCENARIOS["min_trades"],
                  "shape": [f"TP {r} SL, stop cap {c:g}%" for r, c in SCENARIOS["shape"]]}


def _log_rows(o):
    """json's fallback for a compact (n, 4) log array."""
    if hasattr(o, "tolist"):
        return [[int(a), int(b), int(c), round(float(d), 4)] for a, b, c, d in o]
    raise TypeError(f"not JSON: {type(o).__name__}")


def main(argv=None) -> int:
    argv = list(argv or sys.argv[1:])
    use = (scenarios4() if "--scenarios4" in argv
           else scenarios3() if "--scenarios3" in argv
           else scenarios2() if "--scenarios2" in argv
           else scenarios() if "--scenarios" in argv else None)
    argv = [a for a in argv if a not in ("--scenarios", "--scenarios2", "--scenarios3",
                                         "--scenarios4")]
    name, folders = argv[0], argv[1:]
    res = research(folders, grid_=use, keep_log=use is not None,
                   progress=lambda i, n: print(f"  {i:,} of {n:,} rule sets", flush=True))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"research-{name}.json"
    # STREAMED, the compact logs turned back into [strategy, entry, exit,
    # profit] as they are written — never one string of the whole result
    with path.open("w", encoding="utf-8") as fh:
        json.dump(res, fh, separators=(",", ":"), default=_log_rows)
    best = next(r for r in res["rows"] if r["id"] == res["best_train_id"])
    cur = next(r for r in res["rows"] if r["id"] == res["current_id"])
    print(f"{len(res['rows'])} rule sets on {res['combos']:,} combinations. "
          f"Best on Jul-Aug #{best['id']}: train {best['train']['profit']:+.2f}, "
          f"September {best['test']['profit']:+.2f}. Yours #{cur['id']}: train "
          f"{cur['train']['profit']:+.2f}, September {cur['test']['profit']:+.2f} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
