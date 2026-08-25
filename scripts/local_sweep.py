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
import contextlib
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
-- Trade-by-trade detail, for the rows worth inspecting day to day. NOT for
-- all 18 million combinations: at ~500 trades each that is billions of rows,
-- and every one of them is reproducible from (coin, tf, signal, th, sl, tp,
-- sizing) anyway. Kept for the survivors, which is what gets compared.
CREATE TABLE IF NOT EXISTS trades (
  row_id TEXT, n INTEGER, opened TEXT, closed TEXT, day TEXT, side TEXT,
  why TEXT, entry REAL, exit REAL, margin REAL, funding REAL,
  pnl REAL, running REAL,
  PRIMARY KEY (row_id, n)
);
CREATE INDEX IF NOT EXISTS ix_trades_day ON trades(day);
CREATE INDEX IF NOT EXISTS ix_trades_row ON trades(row_id);
CREATE TABLE IF NOT EXISTS done (coin TEXT PRIMARY KEY, rows INTEGER,
                                 secs REAL, at INTEGER);
-- A pair that failed is NOT done. It is purged (its half-written rows
-- deleted from this database AND its state/rows files removed on disk) and
-- run again from clean, because a resumed state built from a crashed run is
-- how a silently-wrong number gets in. Only the failed pair repeats, never
-- the sweep. The operator asked for exactly this on 2026-08-25.
CREATE TABLE IF NOT EXISTS failed (
  coin TEXT, tf TEXT, error TEXT, attempts INTEGER, at INTEGER,
  resolved INTEGER DEFAULT 0,
  PRIMARY KEY (coin, tf)
);
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


def _pair_job(args_tuple):
    """One (coin, timeframe) in a worker.

    Returns a COUNT, never the rows. `run_pair` already writes them to
    `HOME/rows/{coin}-{tf}.json`, and handing multi-megabyte lists back
    through the pool's pipe deadlocks: measured 2026-08-25, both workers
    finished (5,797 rows on disk) and then sat at 0% CPU for 15 minutes with
    `done: 0`, because the pipe filled and nobody drained it. The parent
    reads the files instead.
    """
    import os as _os
    symbol, tf, home, base, days, thresholds = args_tuple
    _os.environ["TRADINGAGENTS_SWEEP_HOME"] = home
    # The Neon archive is FULL (512 MB project limit, measured 2026-08-25) and
    # every fresh worker re-tried it, stalled, then stood down for two minutes
    # — which is why 7 workers idled at 316% CPU instead of ~560%. This run is
    # local-only, so the archive is switched off per worker rather than by
    # editing the shared module.
    from tradingagents.dataflows import market_db as _mdb
    _mdb.available = lambda: False
    from tradingagents import market_sweep as ms
    try:
        r = ms.run_pair(symbol, tf, base_margin=base, days=days,
                        thresholds=thresholds)
        n = len(r.get("rows") or []) if isinstance(r, dict) else len(r or [])
        return symbol, tf, n, ""
    except Exception as exc:
        return symbol, tf, 0, f"{type(exc).__name__}: {exc}"


def _read_pair_rows(home: str, symbol: str, tf: str) -> list:
    """The rows this pair just wrote, straight off disk."""
    coin = symbol.replace("_USDT", "")
    f = Path(home) / "rows" / f"{coin}-{tf}.json"
    if not f.exists():
        return []
    try:
        d = json.loads(f.read_text())
    except ValueError:
        return []                       # a truncated file is not a crash
    return (d.get("rows") if isinstance(d, dict) else d) or []


def _purge_pair(db, home: str, symbol: str, tf: str) -> None:
    """Erase every trace of one (coin, timeframe) so the redo starts clean:
    its rows in this database, and its rows/state/lock files on disk. A
    resume point left by a crashed run would otherwise be trusted."""
    coin = symbol.replace("_USDT", "")
    db.execute("DELETE FROM rows WHERE coin=? AND tf=?", (coin, tf))
    db.execute("DELETE FROM trades WHERE row_id IN "
               "(SELECT id FROM rows WHERE coin=? AND tf=?)", (coin, tf))
    db.commit()
    h = Path(home)
    for f in (h / "rows" / f"{coin}-{tf}.json",
              h / "state" / f"{coin}-{tf}.json",
              h / "locks" / f"{coin}-{tf}.lock"):
        with contextlib.suppress(OSError):
            f.unlink()


def _run_batch(batch, tfs, args, n_workers):
    """Every (coin, tf) of this batch, across ONE pool."""
    import concurrent.futures as cf

    home = os.path.expanduser(args.home)
    jobs = [(c, tf, home, args.base, args.days, args.thresholds)
            for c in batch for tf in tfs]
    out, failures = [], []
    with cf.ProcessPoolExecutor(max_workers=min(n_workers, len(jobs))) as ex:
        for sym, tf, _n, err in ex.map(_pair_job, jobs):
            if err:
                print(f"!! {sym} {tf}: {err}", flush=True)
                failures.append((sym, tf, err))
                continue
            out.extend(_read_pair_rows(home, sym, tf))
    return out, failures


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="~/.tradingagents/sweeps/local.sqlite")
    ap.add_argument("--home", default="~/.tradingagents/sweep-local",
                    help="this run's OWN cache, kept off the other session's")
    ap.add_argument("--tfs", default="15m,30m,1h,4h")
    ap.add_argument("--coins", type=int, default=0, help="0 = every eligible")
    ap.add_argument("--symbols", default="",
                    help="comma-separated symbols to run FIRST (or only, with "
                         "--only). Alphabetical order otherwise puts obscure "
                         "contracts ahead of the ones being compared")
    ap.add_argument("--only", action="store_true",
                    help="run just --symbols and stop")
    ap.add_argument("--chunk", type=int, default=4,
                    help="coins per grid call; rows are flushed after each")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--base", type=float, default=5.0)
    ap.add_argument("--workers", type=int, default=0, help="0 = cores - 1")
    ap.add_argument("--thresholds", type=int, default=1,
                    help="momentum thresholds per timeframe. 1 matches the "
                         "GitHub sweep; 3 triples those signals' combinations")
    ap.add_argument("--retries", type=int, default=2,
                    help="redo a FAILED pair this many times, purged first")
    ap.add_argument("--progress",
                    default="~/.tradingagents/sweeps/local-progress.json")
    args = ap.parse_args(argv)

    os.environ["TRADINGAGENTS_SWEEP_HOME"] = os.path.expanduser(args.home)
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
    want = [x.strip() for x in args.symbols.split(",") if x.strip()]
    if want:
        first = [c for c in want if c in coins
                 and c.replace("_USDT", "") not in done]
        rest = [] if args.only else [c for c in todo if c not in first]
        todo = first + rest
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
    n_workers = args.workers or max(1, (os.cpu_count() or 2) - 1)
    print(f"workers: {n_workers}", flush=True)
    for i in range(0, len(todo), args.chunk):
        batch = todo[i:i + args.chunk]
        t0 = time.time()
        rows, failures = _run_batch(batch, tfs, args, n_workers)
        # Redo ONLY what failed, from clean, up to --retries times.
        home = os.path.expanduser(args.home)
        for attempt in range(1, args.retries + 1):
            if not failures:
                break
            again = [(c, tf) for c, tf, _ in failures]
            print(f"   retry {attempt}/{args.retries} for "
                  f"{[f'{c}/{t}' for c, t in again]}", flush=True)
            for c, tf in again:
                _purge_pair(db, home, c, tf)
            retry_rows, failures = _run_batch(
                [c for c, _ in again], [t for _, t in dict.fromkeys(again, 1)],
                args, n_workers)
            rows.extend(retry_rows)
        bad_coins = set()
        for c, tf, err in failures:
            short = c.replace("_USDT", "")
            bad_coins.add(short)
            _purge_pair(db, home, c, tf)        # leave nothing half-written
            db.execute(
                "INSERT OR REPLACE INTO failed VALUES (?,?,?,?,?,0)",
                (short, tf, err[:400], args.retries, int(time.time())))
        db.commit()
        n = write_rows(db, rows)
        secs = time.time() - t0
        total += n
        for c in batch:
            short = c.replace("_USDT", "")
            if short in bad_coins:
                # NOT done: a later run picks it up again rather than
                # inheriting a coin that is missing a timeframe.
                print(f"   {short} left unfinished — it will be retried on "
                      f"the next run", flush=True)
                continue
            db.execute("INSERT OR REPLACE INTO done VALUES (?,?,?,?)",
                       (short, sum(1 for r in rows if r["coin"] == short),
                        secs / max(1, len(batch)), int(time.time())))
        db.commit()
        rows.clear()
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
