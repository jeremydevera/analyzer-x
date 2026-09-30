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


def merge(name: str, art_dir: str, data_dir: str) -> Path:
    arts = sorted(Path(art_dir).rglob("research-*.json"))
    metas = [json.loads(a.read_text(encoding="utf-8")) for a in arts]
    packs = [np.load(a.with_suffix(".npz")) for a in arts]
    end = int(metas[0]["end_ms"])
    periods = {"train": (ms("2026-07-01"), ms("2026-09-01") - 1), "test": (ms("2026-09-01"), end)}
    strategies: list = []
    offsets = []
    for m in metas:
        offsets.append(len(strategies))
        strategies += m["strategies"]
    n_rules = len(metas[0]["rules"])
    rows = []
    for j in range(n_rules):
        cfg = metas[0]["rules"][j]["cfg"]
        out = {"id": rs.rule_id(cfg), "cfg": cfg}
        for part, (a, b) in periods.items():
            e = np.concatenate([(pk[f"{j}_{part}_e"].astype(np.int64) + T0_MIN) * 60_000 for pk in packs])
            x = np.concatenate([(pk[f"{j}_{part}_x"].astype(np.int64) + T0_MIN) * 60_000 for pk in packs])
            p = np.concatenate([pk[f"{j}_{part}_p"].astype(np.float64) for pk in packs])
            trades = np.column_stack([e, x, p, np.ones(len(e))]) if len(e) else np.zeros((0, 4))
            res = {"summary": {"slots": sum(m["rules"][j][part]["slots"] for m in metas),
                               "open": sum(m["rules"][j][part]["open"] for m in metas)},
                   "days": _days(e, x, p, a, b), "slots": [{"trades": trades}]}
            out[part] = rs.score(res, end_ms=b)
            if part == "test":
                s = np.concatenate([pk[f"{j}_{part}_s"].astype(np.int64) + off
                                    for pk, off in zip(packs, offsets)])
                log = np.column_stack([s, e, x, p]) if len(e) else np.zeros((0, 4))
                out["test_log"] = log[np.argsort(log[:, 2], kind="stable")]
        rows.append(out)
        print(f"  {j + 1} of {n_rules} rule sets", flush=True)
    by_train = sorted(rows, key=lambda r: -r["train"]["profit"])
    ids = {r["id"] for r in rows}
    want = rs.rule_id({**rs.CURRENT, **rs.RAW})
    tot = rc.merge_reports([data_dir])
    res = {"train": list(periods["train"]), "test": list(periods["test"]), "end_ms": end,
           "totals": tot, "combos": sum(int(m.get("books") or 0) for m in metas),
           "grid": {}, "current_id": want if want in ids else rows[0]["id"],
           "best_train_id": by_train[0]["id"], "rows": rows, "strategies": strategies}
    path = rs.OUT_DIR / f"research-{name}.json"
    rs.OUT_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(res, fh, separators=(",", ":"), default=rs._log_rows)
    return path


if __name__ == "__main__":
    print(merge(sys.argv[1], sys.argv[2], sys.argv[3]))
