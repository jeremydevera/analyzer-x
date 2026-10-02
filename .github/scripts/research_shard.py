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
    L = rs.load_lean([src], end_ms=end_ms)
    books = list(L["books"].values())
    # every trade as one set of arrays, for raw_trades (raw_fast's answer, held
    # equal to it by tests/test_research_every_shape.py, 15x faster on a loose rule)
    flat = rs.Flat(books)
    ids = [b.c["id"] for b in books]
    # the packed copies are Flat's now: raw_trades never asks a book for its
    # trades, and on unfiltered replay data the two copies together would not
    # fit a runner's memory
    for b_ in books:
        if isinstance(b_.c, rs._PackedMeta):
            b_.c.pk = ()
    print(f"shard {shard} chunk {chunk + 1}/{chunks}: {len(books):,} combinations, "
          f"{len(flat.ent):,} trades loaded in {time.time() - t0:.0f}s; {len(grid)} rule sets",
          flush=True)
    periods = {"train": (ms(os.environ.get("TRAIN_START", "2026-07-01")),
                         ms(os.environ.get("TRAIN_END", "2026-09-01")) - 1),
               "test": (ms(os.environ.get("TEST_START", "2026-09-01")), end_ms)}
    arrays: dict = {}
    meta = {"shard": shard, "chunk": chunk, "chunks": chunks, "end_ms": end_ms,
            "books": len(books), "rules": [], "strategies": []}
    strat_ix: dict = {}
    for part, (a, b) in periods.items():
        checks = wr.local_midnights(a, b)
        grids = {wd: rs.count_grid(books, checks, wd * wr.DAY_MS)
                 for wd in sorted({c["window_days"] for c in grid})}
        for j, cfg in enumerate(grid):
            r = rs.raw_trades(books, flat, grids[cfg["window_days"]], checks, cfg, b)
            m = r["closed"] & (r["ext"] <= b)
            arrays[f"{j}_{part}_e"] = (r["ent"][m] // 60_000 - T0_MIN).astype(np.int32)
            arrays[f"{j}_{part}_x"] = (r["ext"][m] // 60_000 - T0_MIN).astype(np.int32)
            arrays[f"{j}_{part}_p"] = r["pnl"][m].astype(np.float32)
            if part == "test":
                si = np.empty(int(m.sum()), np.int32)
                for n_, bi in enumerate(r["book"][m]):
                    k = strat_ix.get(int(bi))
                    if k is None:
                        c_ = books[int(bi)].c
                        k = strat_ix[int(bi)] = len(meta["strategies"])
                        meta["strategies"].append([ids[int(bi)], c_["coin"], c_["tf"], c_["signal"],
                                                   float(c_.get("th", 0.0)), float(c_["tp"]),
                                                   float(c_["sl"])])
                    si[n_] = k
                arrays[f"{j}_{part}_s"] = si
            if part == "train":
                meta["rules"].append({"cfg": cfg})
            meta["rules"][j][part] = {"slots": r["slots"], "open": r["open"]}
            if (j + 1) % 100 == 0:
                print(f"    {part}: {j + 1} of {len(grid)} in {time.time() - t0:.0f}s", flush=True)
        print(f"  {part}: {len(grid)} rule sets in {time.time() - t0:.0f}s", flush=True)
    name = f"research-{shard}" + (f"-{chunk}" if chunks > 1 else "")
    np.savez_compressed(out / f"{name}.npz", **arrays)
    (out / f"{name}.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"shard {shard} done in {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
