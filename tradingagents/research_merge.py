"""Add up a GitHub rule-set research (.github/workflows/research.yml) and
score it here, with the one score() the PC's own research uses.

    python -m tradingagents.research_merge <name> <research-artifacts-dir> <replay-data-dir>
      -> ~/.tradingagents/replay/research-<name>.json (the shape research() writes)

Each machine replayed whole coins, and a raw rule set links rows only
through the runner's per-coin limit, so a rule set's closed trades over the
market are the machines' closed trades put together. The days, win rate,
worst losing run and most trades open at once are then computed from that
sum — never added from per-machine figures, which would be wrong for the run
and the peak (Sep 30, 2026).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

from tradingagents import replay_collect as rc
from tradingagents import watcher_replay as wr
from tradingagents import watcher_research as rs

T0_MIN = 1_767_225_600 // 60


def ms(s: str) -> int:
    return int(dt.datetime(*map(int, s.split("-"))).timestamp() * 1000)


def _days(e_ms: np.ndarray, x_ms: np.ndarray, p: np.ndarray, start: int, end: int) -> list:
    """simulate's `days`: one row per check day, profit of the trades that
    CLOSED that day, each day rounded as _days rounds it."""
    checks = wr.local_midnights(start, end)
    # the midnight AFTER the last check day closes it: a trade that closed
    # later has no day here, as in _days
    # (local_midnights starts at the midnight OF the day it is given, which
    # is the last check itself — take the first one after it)
    later = [m for m in wr.local_midnights(checks[-1], checks[-1] + 2 * wr.DAY_MS)
             if m > checks[-1]]
    edges = np.asarray(checks + later[:1], dtype=np.int64)
    k = np.searchsorted(edges, x_ms, "right") - 1
    ok = (k >= 0) & (k < len(checks))
    raw = np.bincount(k[ok], weights=p[ok], minlength=len(checks))
    return [{"pnl": round(float(v), 2)} for v in raw]


def part_trades(packs: list, items: list, j: int, part: str) -> tuple:
    """Rule set j's closed trades in one part (train | test) over the machines
    `items`: (entry ms, exit ms, profit) arrays, machine after machine. ONE
    reading of research_shard's packed minutes, shared by `merge` and the
    daily re-test of the kept room strategies (room_strategies_daily)."""
    e = np.concatenate([(packs[i][f"{j}_{part}_e"].astype(np.int64) + T0_MIN) * 60_000 for i in items])
    x = np.concatenate([(packs[i][f"{j}_{part}_x"].astype(np.int64) + T0_MIN) * 60_000 for i in items])
    p = np.concatenate([packs[i][f"{j}_{part}_p"].astype(np.float64) for i in items])
    return e, x, p


def merge(name: str, art_dir: str, data_dir: str, log_top: int = 100,
          reality: dict | None = None) -> Path:
    """`log_top`: only the best `log_top` rule sets on July-August (the fair
    ranking the page uses) keep their trade-by-trade September list — 144
    rule sets with every list made a 1.2 GB file, 8,064 would be ~60 GB.
    0 keeps every list.

    `reality` (prompt 4, Oct 02, 2026): Forecast v2's reality check; given,
    every rule set also carries `p4` — its months, newest 15 days and worst
    15-day stretch after it (room_strategies.measure) — and every WINNER its
    whole trade list (`p4_trades`), so the page can re-measure any dates."""
    arts = sorted(Path(art_dir).rglob("research-*.json"))
    metas = [json.loads(a.read_text(encoding="utf-8")) for a in arts]
    packs = [np.load(a.with_suffix(".npz")) for a in arts]
    end = int(metas[0]["end_ms"])
    periods = {"train": (ms("2026-07-01"), ms("2026-09-01") - 1), "test": (ms("2026-09-01"), end)}
    # ONE STRATEGY LIST for the whole run, each strategy once: a run split in
    # grid slices (Oct 01, 2026) carries the same strategy in several
    # artifacts, and each artifact's `s` numbers its own list
    strategies: list = []
    where: dict = {}
    remap = []
    for m in metas:
        loc = []
        for row in m["strategies"]:
            k = where.get(row[0])
            if k is None:
                k = where[row[0]] = len(strategies)
                strategies.append(row)
            loc.append(k)
        remap.append(np.asarray(loc, dtype=np.int64))
    # SLICES IN GRID ORDER: every machine ran the same slice list, so a slice
    # is the artifacts carrying its number, and its rule j is the same rule set
    # on each of them
    slices: dict = {}
    for i, m in enumerate(metas):
        slices.setdefault(int(m.get("chunk") or 0), []).append(i)
    shards = {}
    for ch in slices.values():
        for i in ch:
            shards.setdefault(str(metas[i]["shard"]), int(metas[i].get("books") or 0))
    total_rules = sum(len(metas[ch[0]]["rules"]) for ch in slices.values())
    rows = []
    done = 0
    kept_ids: set = set()
    if reality is not None:
        from tradingagents import room_strategies as rst
        kept_ids = {w["id"] for w in rst.kept()}
    for c_ in sorted(slices):
        items = slices[c_]
        for j in range(len(metas[items[0]]["rules"])):
            cfg = metas[items[0]]["rules"][j]["cfg"]
            out = {"id": rs.rule_id(cfg), "cfg": cfg}
            both: list = []
            for part, (a, b) in periods.items():
                e, x, p = part_trades(packs, items, j, part)
                trades = np.column_stack([e, x, p, np.ones(len(e))]) if len(e) else np.zeros((0, 4))
                res = {"summary": {"slots": sum(metas[i]["rules"][j][part]["slots"] for i in items),
                                   "open": sum(metas[i]["rules"][j][part]["open"] for i in items)},
                       "days": _days(e, x, p, a, b), "slots": [{"trades": trades}]}
                out[part] = rs.score(res, end_ms=b)
                if reality is not None:
                    both.append(np.column_stack([e, x, p]) if len(e) else np.zeros((0, 3)))
            out["_at"] = (c_, j)
            # back to grid order: slices are dealt (watcher_research.chunk_of)
            out["_grid"] = j * int(metas[items[0]].get("chunks") or 1) + c_
            if reality is not None:
                from tradingagents import room_strategies as rst
                t_all = np.concatenate(both) if both else np.zeros((0, 3))
                out["p4"] = rst.measure(t_all, end, reality)
                ok, why = rst.is_winner(out["p4"])
                out["p4"]["winner"], out["p4"]["why"] = ok, why
                # a winner's trades, and an already-KEPT one's even when it no
                # longer wins (its row must show what it did, not zeros)
                if ok or rst.sid(cfg) in kept_ids:
                    # a plain list: the writer's fallback (rs._log_rows) is for
                    # 4-column logs, and this is entry, exit, profit
                    out["p4_trades"] = [[int(a), int(b), round(float(c), 4)] for a, b, c
                                         in t_all[np.argsort(t_all[:, 1], kind="stable")]]
            rows.append(out)
            done += 1
            if done % 100 == 0 or done == total_rules:
                print(f"  {done} of {total_rules} rule sets", flush=True)
    rows.sort(key=lambda r: r.pop("_grid"))
    by_train = sorted(rows, key=lambda r: -r["train"]["profit"])
    ids = {r["id"] for r in rows}
    want = rs.rule_id({**rs.CURRENT, **rs.RAW})
    # SECOND PASS: the September trade lists of the rule sets the page opens
    logged = {id(r) for r in (by_train if not log_top else by_train[:log_top])}
    logged |= {id(r) for r in rows if r["id"] == want}
    for r in rows:
        c_, j = r.pop("_at")
        if id(r) not in logged:
            continue
        items = slices[c_]
        e = np.concatenate([(packs[i][f"{j}_test_e"].astype(np.int64) + T0_MIN) * 60_000 for i in items])
        x = np.concatenate([(packs[i][f"{j}_test_x"].astype(np.int64) + T0_MIN) * 60_000 for i in items])
        p = np.concatenate([packs[i][f"{j}_test_p"].astype(np.float64) for i in items])
        s_ = np.concatenate([remap[i][packs[i][f"{j}_test_s"].astype(np.int64)]
                             if len(packs[i][f"{j}_test_s"]) else np.zeros(0, np.int64)
                             for i in items])
        log = np.column_stack([s_, e, x, p]) if len(e) else np.zeros((0, 4))
        r["test_log"] = log[np.argsort(log[:, 2], kind="stable")]
    tot = rc.merge_reports([data_dir])
    res = {"train": list(periods["train"]), "test": list(periods["test"]), "end_ms": end,
           "totals": tot, "combos": sum(shards.values()),
           "grid": {}, "current_id": want if want in ids else rows[0]["id"],
           "best_train_id": by_train[0]["id"], "rows": rows, "strategies": strategies}
    path = rs.OUT_DIR / f"research-{name}.json"
    rs.OUT_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(res, fh, separators=(",", ":"), default=rs._log_rows)
    return path


if __name__ == "__main__":
    print(merge(sys.argv[1], sys.argv[2], sys.argv[3],
                *([int(sys.argv[4])] if len(sys.argv) > 4 else [])))
