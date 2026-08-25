"""Whole-market backtest on THIS Mac, into its own SQLite database.

Why a separate database: the operator runs two Claude sessions against one
repo and wants to compare what each produces (2026-08-25). Sharing the sweep
store would have them overwriting each other's per-pair state — those writes
are not atomic — so this run gets its own `TRADINGAGENTS_SWEEP_HOME` cache
AND its own `.sqlite` results file. Nothing here touches the other session's
files, and nothing here touches the network beyond candles already on disk.

Why SQLite rather than another JSONL: comparing two sweeps is a join, and a
1.5 GB text file cannot be joined. One row per combination, indexed by the
same content-hashed id the grid pages use, so "row #K4M7QP2X in run A vs run
B" is a two-line query.

Rows are written in COIN-SIZED CHUNKS and dropped from memory immediately:
452 coins x ~41,000 combinations is ~18 million rows, which no laptop holds.

Usage:
    python scripts/local_sweep.py --db ~/.tradingagents/sweeps/mine.sqlite
    python scripts/local_sweep.py --coins 20 --tfs 1h,4h     # a small probe

It is resumable: a coin already present in this database is skipped, so a
killed run continues where it stopped rather than starting the market again.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SCHEMA = """
CREATE TABLE IF NOT EXISTS rows (
  id TEXT, coin TEXT, tf TEXT, signal TEXT, th REAL, sl REAL, tp REAL,
  sizing TEXT, lev INTEGER, base REAL, notional REAL,
  trades INTEGER, wins INTEGER, losses INTEGER, winrate REAL,
  profit REAL, h1 REAL, h2 REAL, green INTEGER, months INTEGER,
  worst REAL, dd REAL, liqs INTEGER, stop_reachable INTEGER,
  days INTEGER, cost_of_tp REAL, gate TEXT, monthly TEXT,
  PRIMARY KEY (id, coin, tf, signal, th, sl, tp, sizing)
);
CREATE INDEX IF NOT EXISTS ix_rows_coin ON rows(coin);
CREATE INDEX IF NOT EXISTS ix_rows_profit ON rows(profit);
CREATE INDEX IF NOT EXISTS ix_rows_id ON rows(id);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS done (coin TEXT PRIMARY KEY, rows INTEGER,
                                 secs REAL, at INTEGER);
"""

COLS = ("id", "coin", "tf", "signal", "th", "sl", "tp", "sizing", "lev",
        "base", "notional", "trades", "wins", "losses", "winrate", "profit",
        "h1", "h2", "green", "months", "worst", "dd", "liqs",
        "stop_reachable", "days", "cost_of_tp", "gate", "monthly")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=60)
    db.executescript(SCHEMA)
    # WAL so a reader (a comparison query, the other session) never blocks the
    # writer mid-sweep, and a crash cannot leave a half-written page.
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.commit()
    return db


def write_rows(db: sqlite3.Connection, rows: list) -> int:
    def pack(r: dict) -> tuple:
        out = []
        for c in COLS:
            v = r.get(c)
            if c == "monthly":
                # `mon` is the array aligned to the payload's month header;
                # stored as JSON so a comparison can still read per-month.
                v = json.dumps(r.get("mon") or r.get("monthly") or [])
            elif c == "stop_reachable":
                v = 1 if v else 0
            out.append(v)
        return tuple(out)

    db.executemany(
        f"INSERT OR REPLACE INTO rows ({','.join(COLS)}) "
        f"VALUES ({','.join('?' * len(COLS))})", [pack(r) for r in rows])
    db.commit()
    return len(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="~/.tradingagents/sweeps/local.sqlite")
    ap.add_argument("--home", default="~/.tradingagents/sweep-local",
                    help="this run's OWN cache, kept off the other session's")
    ap.add_argument("--tfs", default="15m,30m,1h,4h")
    ap.add_argument("--coins", type=int, default=0, help="0 = every eligible")
    ap.add_argument("--chunk", type=int, default=4,
                    help="coins per grid call; rows are flushed after each")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--base", type=float, default=5.0)
    ap.add_argument("--workers", type=int, default=0, help="0 = cores - 1")
    ap.add_argument("--progress",
                    default="~/.tradingagents/sweeps/local-progress.json")
    args = ap.parse_args(argv)

    os.environ["TRADINGAGENTS_SWEEP_HOME"] = os.path.expanduser(args.home)
    from tradingagents import backtest_report as br
    from tradingagents.dataflows import mexc_futures as fx

    tfs = [t.strip() for t in args.tfs.split(",") if t.strip()]
    db = connect(Path(os.path.expanduser(args.db)))
    prog = Path(os.path.expanduser(args.progress))

    raw = fx._get_public(f"{fx.BASE}/api/v1/contract/detail").get("data") or []
    coins = sorted(x["symbol"] for x in raw
                   if str(x.get("symbol", "")).endswith("_USDT")
                   and int(x.get("state", 1)) == 0)
    done = {r[0] for r in db.execute("SELECT coin FROM done")}
    todo = [c for c in coins if c.replace("_USDT", "") not in done]
    if args.coins:
        todo = todo[:args.coins]
    started = time.time()
    db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
               ("started", str(int(started))))
    db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
               ("tfs", ",".join(tfs)))
    db.commit()
    print(f"{len(coins)} contracts · {len(done)} already in this db · "
          f"{len(todo)} to run · tfs {tfs}", flush=True)

    total = 0
    for i in range(0, len(todo), args.chunk):
        batch = todo[i:i + args.chunk]
        t0 = time.time()
        try:
            payload = br.grid_from_store(
                batch, tfs, base_margin=args.base, days=args.days,
                workers=args.workers, embed_limit=0)
        except Exception as exc:                 # one bad coin must not end it
            print(f"!! {batch}: {type(exc).__name__}: {exc}", flush=True)
            continue
        rows = payload.get("rows") or []
        n = write_rows(db, rows)
        secs = time.time() - t0
        total += n
        for c in batch:
            short = c.replace("_USDT", "")
            db.execute("INSERT OR REPLACE INTO done VALUES (?,?,?,?)",
                       (short, sum(1 for r in rows if r["coin"] == short),
                        secs / max(1, len(batch)), int(time.time())))
        db.commit()
        rows.clear()
        payload.clear()
        el = time.time() - started
        pct = (i + len(batch)) / max(1, len(todo))
        eta = el / max(pct, 1e-9) - el
        line = (f"{i + len(batch)}/{len(todo)} coins · {total:,} rows · "
                f"{el / 60:.0f}m elapsed · ETA {eta / 60:.0f}m")
        print(line, flush=True)
        tmp = prog.with_suffix(".tmp")
        prog.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({
            "done": i + len(batch), "total": len(todo), "rows": total,
            "elapsed_s": int(el), "eta_s": int(eta), "note": line,
            "db": str(db_path_of(db)), "finished": False}))
        tmp.replace(prog)

    db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
               ("finished", str(int(time.time()))))
    db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
               ("rows", str(total)))
    db.commit()
    el = time.time() - started
    print(f"DONE: {total:,} rows from {len(todo)} coins in {el / 60:.0f} min",
          flush=True)
    tmp = prog.with_suffix(".tmp")
    tmp.write_text(json.dumps({"done": len(todo), "total": len(todo),
                               "rows": total, "elapsed_s": int(el),
                               "eta_s": 0, "finished": True,
                               "note": f"{total:,} rows in {el / 60:.0f} min"}))
    tmp.replace(prog)
    return 0


def db_path_of(db: sqlite3.Connection) -> str:
    for _, name, path in db.execute("PRAGMA database_list"):
        if name == "main":
            return path or ""
    return ""


if __name__ == "__main__":
    sys.exit(main())
