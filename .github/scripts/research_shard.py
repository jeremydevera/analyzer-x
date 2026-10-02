"""One machine's share of a raw rule-set research (Sep 30, 2026).

The operator: "show me the result for top 100 combinations so i can decide
which to deploy" — over data too big for the PC (run 36763426504: 4,585,414
combinations, ~734M trades, 28 GB). A replay shard holds WHOLE coins, and a
raw rule set links rows only through the runner's 4 trades per coin, so each
machine can replay its own coins for every rule set and hand back its CLOSED
TRADES; the PC adds the machines together and scores the sum with the one
score() (tradingagents/watcher_research.py).

Out: out/research-<SHARD>.npz — for rule set j and part (train|test):
  j_part_e / _x   entry / exit, int32 minutes from Jan 01, 2026 UTC
  j_part_p        profit, float32
  j_part_s        (test) index into the shard's strategy list
and out/research-<SHARD>.json — strategies, and each rule set's slots/open.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tradingagents import watcher_replay as wr  # noqa: E402
from tradingagents import watcher_research as rs  # noqa: E402

T0_MIN = 1_767_225_600 // 60          # Jan 01, 2026 00:00 UTC, in minutes
# lines of one coin batch (rs.coin_batches): ~40 bytes a trade, so ~26M
# trades — measured to stay well inside a runner's 16 GB
BATCH_MB = 1000


def peak_mb() -> int:
    """The process's peak memory so far (Linux, where the runner is; 0 on
    Windows), printed per batch so a run shows how near 16 GB it came."""
    try:
        import resource
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) // 1024
    except Exception:  # noqa: BLE001
        return 0


def ms(s: str) -> int:
    return int(dt.datetime(*map(int, s.split("-"))).timestamp() * 1000)


def main() -> int:
    src, shard = os.environ["SRC"], os.environ["SHARD"]
    end_ms = int(os.environ["END_MS"])
    # THE GRID'S SLICE for this job (Oct 01, 2026): 8,064 rule sets do not fit
    # one machine's six hours, so a run is shards x chunks jobs, each the
    # rule sets rs.chunk_of names; the merge on the PC puts them back in order
    chunk, chunks = int(os.environ.get("CHUNK", "0")), int(os.environ.get("CHUNKS", "1"))
    scen = os.environ.get("SCEN", "5")
    if scen.startswith("file:"):
        # a LIST of rule sets in this repo (prompt 4's rounds, Oct 02, 2026):
        # tradingagents.room_strategies.write_round wrote it before dispatch
        from tradingagents import room_strategies as rst
        full = rst.read_round(scen[5:])
    else:
        full = getattr(rs, f"scenarios{scen}")()
    grid = rs.chunk_of(full, chunk, chunks)
    out = Path("out")
    out.mkdir(exist_ok=True)
    t0 = time.time()
    # COIN BATCH BY COIN BATCH (Oct 02, 2026): shard 8 of replay run
    # 37007971331 — 1,574,489 combinations, 206,094,384 trades — loaded whole
    # and walked by a loose rule set passed the machine's 16 GB and the runner
    # was shut down. A raw rule set never looks across coins, so the shard is
    # read and measured a batch of whole coins at a time and the batches are
    # added up (rs.coin_batches; held equal to one pass by
    # tests/test_research_every_shape.py).
    batch_mb = int(os.environ.get("BATCH_MB") or BATCH_MB)
    batches = rs.coin_batches([src], batch_mb * 2 ** 20)
    print(f"shard {shard} chunk {chunk + 1}/{chunks}: {sum(map(len, batches)):,} combinations in "
          f"{len(batches)} batch(es) of whole coins (up to {batch_mb} MB of lines each); "
          f"{len(grid)} rule sets", flush=True)
    periods = {"train": (ms(os.environ.get("TRAIN_START", "2026-07-01")),
                         ms(os.environ.get("TRAIN_END", "2026-09-01")) - 1),
               "test": (ms(os.environ.get("TEST_START", "2026-09-01")), end_ms)}
    arrays: dict = {}
    meta = {"shard": shard, "chunk": chunk, "chunks": chunks, "end_ms": end_ms,
            "books": 0, "trades": 0, "batches": len(batches), "rules": [], "strategies": []}
    # OUT=daily (prompt 4, Oct 02, 2026): per rule set and part, the closed
    # trades, wins and profit of every LOCAL day — ~1.5 KB a rule set where the
    # trade lists of 8,568 rule sets over 40 shards were ~75 GB to bring home.
    # The winners get a second, small run with OUT=full for their trades.
    daily = os.environ.get("OUT", "full").strip() == "daily"
    if daily:
        mids = wr.local_midnights(ms(os.environ.get("TRAIN_START", "2026-07-01")), end_ms)
        nxt = [m for m in wr.local_midnights(mids[-1], mids[-1] + 2 * wr.DAY_MS) if m > mids[-1]]
        edges = np.asarray(mids + nxt[:1], dtype=np.int64)
        meta["day_edges"] = [int(x) for x in edges]
        n_days = len(edges) - 1
    # per (rule set, part), over every batch: [slots, open], and the day sums
    # (daily) or the trade pieces (full)
    counts: dict = {}
    acc: dict = {}
    strat_ix: dict = {}
    base = 0
    for bi, locs in enumerate(batches):
        books = rs.load_batch(locs, end_ms)
        # every trade as one set of arrays, for raw_trades (raw_fast's answer,
        # held equal to it by tests/test_research_every_shape.py)
        flat = rs.Flat(books)
        # the packed copies are Flat's now: raw_trades never asks a book for
        # its trades
        for b_ in books:
            if isinstance(b_.c, rs._PackedMeta):
                b_.c.pk = ()
        meta["trades"] += len(flat.ent)
        print(f"  batch {bi + 1} of {len(batches)}: {len(books):,} combinations, "
              f"{len(flat.ent):,} trades, loaded by {time.time() - t0:.0f}s", flush=True)
        for part, (a, b) in periods.items():
            checks = wr.local_midnights(a, b)
            grids = {wd: rs.count_grid(books, checks, wd * wr.DAY_MS)
                     for wd in sorted({c["window_days"] for c in grid})}
            # ONE switch-on walk per (window, trades, line), shared by every
            # rule set that differs only in its target shape, stop cap or
            # target floor (rs.all_starts): the rule sets are visited key by
            # key, and each answer still lands under its own j
            walk_key, walk = None, None
            for done, j in enumerate(sorted(range(len(grid)), key=lambda i: rs.starts_key(grid[i]))):
                cfg = grid[j]
                if rs.starts_key(cfg) != walk_key:
                    walk_key = rs.starts_key(cfg)
                    walk = rs.all_starts(flat, grids[cfg["window_days"]], checks, cfg)
                r = rs.raw_trades(books, flat, grids[cfg["window_days"]], checks, cfg, b, starts=walk)
                m = r["closed"] & (r["ext"] <= b)
                n_ = counts.setdefault((j, part), [0, 0])
                n_[0] += r["slots"]
                n_[1] += r["open"]
                if daily:
                    k = np.searchsorted(edges, r["ext"][m], "right") - 1
                    ok = (k >= 0) & (k < n_days)
                    pv = r["pnl"][m][ok]
                    # the types are fixed here: bincount over NO trades
                    # answers whole numbers even with weights, and the add
                    # into the running float sum then refuses
                    day = (np.bincount(k[ok], minlength=n_days).astype(np.int64),
                           np.bincount(k[ok], weights=(pv > 0).astype(np.float64),
                                       minlength=n_days).astype(np.float64),
                           np.bincount(k[ok], weights=pv.astype(np.float64),
                                       minlength=n_days).astype(np.float64))
                    s = acc.get((j, part))
                    if s is None:
                        acc[(j, part)] = list(day)
                    else:
                        for q in range(3):
                            s[q] += day[q]
                else:
                    si = None
                    if part == "test":
                        si = np.empty(int(m.sum()), np.int32)
                        for n2, lb in enumerate(r["book"][m]):
                            g = base + int(lb)
                            k2 = strat_ix.get(g)
                            if k2 is None:
                                c_ = books[int(lb)].c
                                k2 = strat_ix[g] = len(meta["strategies"])
                                meta["strategies"].append([c_["id"], c_["coin"], c_["tf"], c_["signal"],
                                                           float(c_.get("th", 0.0)), float(c_["tp"]),
                                                           float(c_["sl"])])
                            si[n2] = k2
                    acc.setdefault((j, part), []).append(
                        ((r["ent"][m] // 60_000 - T0_MIN).astype(np.int32),
                         (r["ext"][m] // 60_000 - T0_MIN).astype(np.int32),
                         r["pnl"][m].astype(np.float32), si))
                if (done + 1) % 500 == 0:
                    print(f"    batch {bi + 1}, {part}: {done + 1} of {len(grid)} by {time.time() - t0:.0f}s",
                          flush=True)
            del grids, walk
            print(f"  batch {bi + 1}, {part}: {len(grid)} rule sets by {time.time() - t0:.0f}s, "
                  f"peak memory {peak_mb():,} MB", flush=True)
        base += len(books)
        # free the batch before the next one loads: the (tp, sl) cache holds
        # the book list until another list asks
        del books, flat
        rs._TPSL.clear()
    meta["books"] = base
    for j, cfg in enumerate(grid):
        rule = {"cfg": cfg}
        for part in periods:
            slots, open_ = counts.get((j, part), (0, 0))
            rule[part] = {"slots": int(slots), "open": int(open_)}
            got = acc.get((j, part))
            if daily:
                dn, dw, dp = got if got else (np.zeros(n_days, np.int64), np.zeros(n_days), np.zeros(n_days))
                arrays[f"{j}_{part}_dn"] = dn.astype(np.int32)
                arrays[f"{j}_{part}_dw"] = np.rint(dw).astype(np.int32)
                arrays[f"{j}_{part}_dp"] = dp.astype(np.float32)
                continue
            got = got or []
            arrays[f"{j}_{part}_e"] = np.concatenate([g[0] for g in got]) if got else np.zeros(0, np.int32)
            arrays[f"{j}_{part}_x"] = np.concatenate([g[1] for g in got]) if got else np.zeros(0, np.int32)
            arrays[f"{j}_{part}_p"] = np.concatenate([g[2] for g in got]) if got else np.zeros(0, np.float32)
            if part == "test":
                arrays[f"{j}_{part}_s"] = (np.concatenate([g[3] for g in got]) if got
                                           else np.zeros(0, np.int32))
        meta["rules"].append(rule)
    name = f"research-{shard}" + (f"-{chunk}" if chunks > 1 else "")
    np.savez_compressed(out / f"{name}.npz", **arrays)
    (out / f"{name}.json").write_text(json.dumps(meta), encoding="utf-8")
    meta["peak_mb"] = peak_mb()
    print(f"shard {shard} done in {time.time() - t0:.0f}s: {meta['books']:,} combinations, "
          f"{meta['trades']:,} trades, peak memory {meta['peak_mb']:,} MB", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
