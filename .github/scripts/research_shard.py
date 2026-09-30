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
    grid = getattr(rs, f"scenarios{os.environ.get('SCEN', '5')}")()
    out = Path("out")
    out.mkdir(exist_ok=True)
    t0 = time.time()
    L = rs.load_lean([src], end_ms=end_ms)
    books = list(L["books"].values())
    print(f"shard {shard}: {len(books):,} combinations loaded in {time.time() - t0:.0f}s", flush=True)
    periods = {"train": (ms(os.environ.get("TRAIN_START", "2026-07-01")),
                         ms(os.environ.get("TRAIN_END", "2026-09-01")) - 1),
               "test": (ms(os.environ.get("TEST_START", "2026-09-01")), end_ms)}
    arrays: dict = {}
    meta = {"shard": shard, "end_ms": end_ms, "books": len(books), "rules": [],
            "strategies": []}
    strat_ix: dict = {}
    for part, (a, b) in periods.items():
        checks = wr.local_midnights(a, b)
        grids = {wd: rs.count_grid(books, checks, wd * wr.DAY_MS)
                 for wd in sorted({c["window_days"] for c in grid})}
        for j, cfg in enumerate(grid):
            res = rs.raw_fast(books, grids[cfg["window_days"]], checks, cfg, b)
            e, x, p, si = [], [], [], []
            for sl in res["slots"]:
                t = sl["trades"]
                if not len(t):
                    continue
                m = (t[:, 3] > 0) & (t[:, 1] <= b)
                if not m.any():
                    continue
                e.append(t[m, 0])
                x.append(t[m, 1])
                p.append(t[m, 2])
                if part == "test":
                    k = strat_ix.get(sl["id"])
                    if k is None:
                        k = strat_ix[sl["id"]] = len(meta["strategies"])
                        meta["strategies"].append([sl["id"], sl["coin"], sl["tf"], sl["signal"],
                                                   float(sl.get("th", 0.0)), float(sl["tp"]),
                                                   float(sl["sl"])])
                    si.append(np.full(int(m.sum()), k, dtype=np.int32))
            cat = (lambda v, d: np.concatenate(v).astype(d) if v else np.zeros(0, d))
            arrays[f"{j}_{part}_e"] = (cat(e, np.int64) // 60_000 - T0_MIN).astype(np.int32)
            arrays[f"{j}_{part}_x"] = (cat(x, np.int64) // 60_000 - T0_MIN).astype(np.int32)
            arrays[f"{j}_{part}_p"] = cat(p, np.float64).astype(np.float32)
            if part == "test":
                arrays[f"{j}_{part}_s"] = cat(si, np.int32)
            if part == "train":
                meta["rules"].append({"cfg": cfg})
            meta["rules"][j][part] = {"slots": res["summary"]["slots"],
                                      "open": res["summary"]["open"]}
        print(f"  {part}: {len(grid)} rule sets in {time.time() - t0:.0f}s", flush=True)
    np.savez_compressed(out / f"research-{shard}.npz", **arrays)
    (out / f"research-{shard}.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"shard {shard} done in {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
