"""A queryable index over the backtest row store.

WHY THIS EXISTS
---------------
`/api/strategies` used to call `market_sweep.all_rows()`, which JSON-parses
EVERY pair file on the request thread. Measured on 2026-08-22, 53 pairs into a
3,960-pair sweep: **28.6 seconds for 648,181 rows across 363 MB**. The
Strategies grid polls every 4 seconds, so calls piled up seven deep, the API
threadpool jammed, the browser gave up, and the screen said
`/api/strategies?limit=300 -> HTTP 500`. The job-progress poll queued behind the
same jam, which is why the per-core panel looked frozen too.

That cost grows with the sweep: 53 pairs is 363 MB, so 3,960 pairs is roughly
25 GB. No amount of caching makes re-parsing that per request work.

So the rows go into SQLite once, and stay there. Local file, no server, no
cloud — the operator's standing rule. Reads become an indexed query; the answer
is EXACT under any filter, which a "top-N summary file" could not be.

The JSON pair files remain the source of truth: the sweep keeps writing them
and this index is rebuilt from them, per pair, whenever one changes. Nothing
here can lose a measurement.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import time
from collections.abc import Iterable
from pathlib import Path

from tradingagents import market_sweep as msw, portable

DB_PATH = Path.home() / ".tradingagents" / "backtest" / "rows.db"

# Bump when the table shape changes. The index is DERIVED, so a mismatch is
# rebuilt from the JSON files rather than migrated -- there is nothing here to
# preserve. Version 2 dropped "WITHOUT ROWID": a text primary key turned every
# insert into a random write and one pair stopped finishing inside 100 seconds.
SCHEMA_VERSION = 3

# set ROWS_INDEX_DEBUG=1 to trace where a sync stalls
DEBUG = bool(__import__("os").environ.get("ROWS_INDEX_DEBUG"))
if DEBUG:      # kill -USR1 <pid> dumps every thread's stack, live
    import faulthandler as _fh
    import signal as _sig
    _fh.register(_sig.SIGUSR1, all_threads=True)

# every scalar column of a row, in one place so writer and reader cannot drift
COLS = ("id", "coin", "tf", "signal", "th", "sl", "tp", "rr", "sizing", "lev",
        "base", "notional", "trades", "wins", "losses", "winrate", "profit",
        "funding", "h1", "h2", "green", "months", "worst", "dd", "liqs",
        "stop_reachable", "days", "bars", "cost_of_tp", "rt", "gate")
_NUMERIC = {"th", "sl", "tp", "rr", "base", "notional", "winrate", "profit",
            "funding", "h1", "h2", "worst", "dd", "cost_of_tp", "rt"}
_INTEGER = {"lev", "trades", "wins", "losses", "green", "months", "liqs",
            "days", "bars", "stop_reachable"}

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS rows (
  {', '.join(c + (' INTEGER' if c in _INTEGER else
                  ' REAL' if c in _NUMERIC else ' TEXT') for c in COLS)},
  monthly TEXT,
  pair TEXT NOT NULL
);
-- NOT "WITHOUT ROWID, PRIMARY KEY (id)". A text primary key made every one of
-- a pair's ~17,820 inserts a random write into a 415 MB B-tree, and one pair
-- stopped finishing inside 100 seconds while the sweep had the disk. A rowid
-- table appends. Uniqueness is guaranteed by delete-then-insert per pair, so
-- the id index does not need to enforce it.

-- what has been indexed, so a re-sync only touches pairs whose file moved
-- coin/tf/signals live here so the filter dropdowns never scan the rows.
-- SELECT DISTINCT over the row table measured 1.7s at 690,630 rows, and the
-- dropdowns load on mount; at the sweep's full size that is minutes.
CREATE TABLE IF NOT EXISTS pairs (
  pair TEXT PRIMARY KEY,
  mtime REAL NOT NULL,
  size INTEGER NOT NULL,
  n INTEGER NOT NULL,
  at REAL NOT NULL,
  coin TEXT,
  tf TEXT,
  signals TEXT,
  -- what /api/backtest/storage needs. It used to read every row file AND
  -- every state file (1.7 GB) per request, on a polled route.
  combos INTEGER,
  version TEXT,
  last_ms INTEGER,
  rows_mtime REAL,
  bytes INTEGER
) WITHOUT ROWID;
"""

# The read indexes. Kept out of _SCHEMA because a BULK fill drops them first:
# maintaining six indexes per row made the insert of one pair grow from 0.20s
# to 21.81s by the twenty-first pair, and a reader waiting on that write timed
# out at 25s. Built once at the end instead, which is the standard bulk-load
# shape. rows_pair is NOT droppable -- delete-by-pair needs it.
# Dropped during a bulk fill and rebuilt once at the end.
FILTER_INDEXES = {
    "rows_id": "CREATE INDEX IF NOT EXISTS rows_id ON rows (id)",
    # the operator asked to rank by win rate (2026-08-26). Without an
    # index that is a full sort of every row in the store on each poll.
    # (winrate, trades, id) — NOT (winrate, id). The screen asks for
    # "best win rate with at least N trades", and with `trades` absent from
    # the index SQLite had to fetch every candidate row to test it: on the
    # operator's 21,858,026-row store even LIMIT 300 did not return inside
    # ten minutes. In the index it is an index-only filter.
    "rows_winrate": "CREATE INDEX IF NOT EXISTS rows_winrate "
                    "ON rows (winrate DESC, trades, id)",
    "rows_trades": "CREATE INDEX IF NOT EXISTS rows_trades "
                   "ON rows (trades DESC, id)",
    "rows_coin": "CREATE INDEX IF NOT EXISTS rows_coin ON rows (coin, profit DESC)",
    "rows_tf": "CREATE INDEX IF NOT EXISTS rows_tf ON rows (tf, profit DESC)",
    "rows_signal": "CREATE INDEX IF NOT EXISTS rows_signal ON rows (signal, profit DESC)",
}
# NEVER dropped: rows_profit serves the default view (top 300 by profit) and
# rows_pair serves delete-by-pair. Losing the first would make the grid sort
# millions of rows on every poll during the very window it is slowest.
KEEP_INDEXES = (
    "CREATE INDEX IF NOT EXISTS rows_pair ON rows (pair)",
    "CREATE INDEX IF NOT EXISTS rows_profit ON rows (profit DESC, id)",
)
READ_INDEXES = tuple(FILTER_INDEXES.values()) + KEEP_INDEXES

# more pairs than this in one go and it is a bulk fill, not an update
BULK_PAIRS = 8

# How many pairs to index per cycle WHILE A BACKTEST IS RUNNING. Measured
# 2026-08-22: the sweep's seven workers put the load average at 23-33 on eight
# cores, and the same insert that takes 0.25s idle took 16.42s there -- with a
# reader waiting on it, which is what "API unreachable" and "stuck" looked
# like. The sweep is the job the operator is actually waiting three days for;
# the strategy list is a convenience. So trickle: one pair per cycle is
# 2 pairs/min, still faster than the sweep PRODUCES them (0.81 pairs/min
# measured), so the backlog shrinks without competing for the machine.
TRICKLE_PAIRS = 1          # only an explicit force= caller trickles now
_said_paused = [False]     # so the pause is logged once, not every 10 s


def _machine_is_busy() -> bool:
    """Is a backtest sweep running right now?"""
    try:
        from tradingagents import db_jobs as dj

        return bool(dj.status("backtest").get("running"))
    except Exception:
        return False

_lock = threading.Lock()
_syncing = threading.Event()
# Keyed by PATH, never a bare bool. A `_done = True` flag once left a second
# database with no schema at all and broke 14 tests, because the flag said the
# work was finished for a file it had never touched.
_ready: set = set()


def _connect(readonly: bool = False) -> sqlite3.Connection:
    """`synchronous=OFF` is deliberate: every row here is derived from a JSON
    file that is still the source of truth, so a torn write costs a re-index,
    never a measurement. Paid for by inserts that no longer fsync.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if readonly and DB_PATH.exists():
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=60.0)
    else:
        con = sqlite3.connect(DB_PATH, timeout=60.0)
    con.row_factory = sqlite3.Row
    # busy_timeout, not "database is locked": the indexer holds the write lock
    # for seconds at a time and a reader must WAIT rather than fail the request.
    con.execute("PRAGMA busy_timeout=60000")
    if not readonly:
        # journal_mode is PERSISTENT -- setting it per connection needs a brief
        # exclusive lock, which any live reader blocks. Set once, in ensure().
        con.execute("PRAGMA synchronous=OFF")
    # journal_size_limit is NOT persistent: it is a property of the CONNECTION,
    # so setting it once in ensure() bound it to a connection that was then
    # closed. Without it SQLite keeps whatever high-water mark the WAL ever
    # reached — 27.4 GB on 2026-08-24, beside a 13.8 GB database.
    con.execute("PRAGMA journal_size_limit=536870912")       # 512 MB
    return con


@contextlib.contextmanager
def _open(readonly: bool = False):
    """`with sqlite3.connect(...)` COMMITS but does NOT CLOSE. Every poll of
    /api/strategies therefore leaked an open reader, and because each writer
    connection re-issued `PRAGMA journal_mode=WAL` -- which needs a brief
    exclusive lock -- the indexer then blocked behind those readers forever:
    `syncing: True` with the pair count frozen at 5 for four minutes, while the
    same code in a lone process did a pair every 0.7s.
    """
    con = _connect(readonly)
    try:
        yield con
        if not readonly:
            con.commit()
    finally:
        con.close()


def ensure() -> None:
    if str(DB_PATH) in _ready:
        return
    with _lock, _open() as con:
        con.executescript("PRAGMA journal_mode=WAL;")
        # ~16 MB of WAL before a passive checkpoint folds it back in. The
        # default 1,000 pages is fine for small writes; a pair is 18,000 rows.
        con.execute("PRAGMA wal_autocheckpoint=4000")
        con.execute("CREATE TABLE IF NOT EXISTS meta "
                    "(k TEXT PRIMARY KEY, v TEXT)")
        got = con.execute("SELECT v FROM meta WHERE k='schema'").fetchone()
        have = int(got[0]) if got else None
        if have is not None and have != SCHEMA_VERSION:
            con.executescript("DROP TABLE IF EXISTS rows;"
                              "DROP TABLE IF EXISTS pairs;")
            print(f"[rows-index] schema {have} -> {SCHEMA_VERSION}: rebuilding "
                  f"from the pair files", flush=True)
        elif have is None and con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rows'"
        ).fetchone():
            # built before versions existed, so it is the old shape
            con.executescript("DROP TABLE IF EXISTS rows;"
                              "DROP TABLE IF EXISTS pairs;")
            print("[rows-index] pre-version index found: rebuilding", flush=True)
        con.executescript(_SCHEMA)
        # KEEP_INDEXES only. FILTER_INDEXES are dropped by every bulk fill and
        # rebuilt at its end, so creating them here is work thrown away: a
        # forced catch-up on the operator's 8.9 GB store sat here for thirteen
        # minutes (py-spy: ensure -> con.execute(ddl)) building five indexes
        # that sync() dropped seconds later, and rows_winrate alone measured
        # 912 s. Every API startup paid the same toll. A missing sort index is
        # built on demand instead — see build_sort_index / SortNotReady.
        for ddl in KEEP_INDEXES:
            con.execute(ddl)
        con.execute("INSERT OR REPLACE INTO meta (k,v) VALUES ('schema',?)",
                    (str(SCHEMA_VERSION),))
        # a database built before the facet columns existed keeps its rows --
        # re-reading 363 MB of JSON to recover three strings per pair would be
        # absurd, so backfill them from the rows already indexed.
        have = {r[1] for r in con.execute("PRAGMA table_info(pairs)")}
        for col, typ in (("coin", "TEXT"), ("tf", "TEXT"), ("signals", "TEXT"),
                         ("combos", "INTEGER"), ("version", "TEXT"),
                         ("last_ms", "INTEGER"), ("rows_mtime", "REAL"),
                         ("bytes", "INTEGER")):
            if col not in have:
                con.execute(f"ALTER TABLE pairs ADD COLUMN {col} {typ}")
        # COIN AND TF COME FROM THE PAIR KEY, NOT FROM THE ROWS TABLE.
        #
        # This used to read them back out of `rows` with correlated subqueries.
        # A pair whose backtest produced NO profitable row -- the shard only
        # writes winners -- has nothing in `rows`, so the subquery returned NULL,
        # `coin` stayed NULL, and the guard above fired again on the NEXT
        # startup. On 2026-08-25 exactly one such pair (AASTOCK-30m, 0 rows) made
        # every boot re-scan a 15 GB table: the supervisor sat silent for minutes
        # before its first log line, looking hung, on every restart.
        #
        # The key IS the answer ("AASTOCK-30m" -> AASTOCK, 30m) and it is free,
        # so `coin` can never come back NULL and the scan can never repeat.
        need = [r[0] for r in
                con.execute("SELECT pair FROM pairs WHERE coin IS NULL")]
        if need:
            print(f"[rows-index] backfilling coin/tf for {len(need)} pair(s)",
                  flush=True)
            for pair in need:
                coin, _, tf = str(pair).rpartition("-")
                sigs = con.execute(
                    "SELECT group_concat(s, char(10)) FROM (SELECT DISTINCT "
                    "signal AS s FROM rows WHERE pair = ?)", (pair,)
                ).fetchone()[0]
                con.execute("UPDATE pairs SET coin=?, tf=?, signals=? "
                            "WHERE pair=?", (coin or pair, tf, sigs, pair))
        con.commit()
    _ready.add(str(DB_PATH))


# ------------------------------------------------------------------ writing
def _row_id(r: dict) -> str:
    from tradingagents import backtest_report as br

    got = r.get("id")
    if got:
        return str(got)
    return br.row_code(r["coin"], r["tf"], r["signal"], r.get("th") or 0.0,
                       r["sl"], r["tp"], r["sizing"])


def _values(r: dict, pair: str) -> tuple:
    out = []
    for c in COLS:
        v = r.get("id") if c == "id" else r.get(c)
        if c == "id":
            v = _row_id(r)
        elif c == "stop_reachable":
            v = 1 if v else 0
        out.append(v)
    out.append(json.dumps(r.get("monthly") or {}, separators=(",", ":")))
    out.append(pair)
    return tuple(out)


def index_pair(path: Path, con: sqlite3.Connection | None = None) -> int:
    """(Re)index one pair file. Returns how many rows landed."""
    own = con is None
    con = con or _connect()   # caller-owned when passed
    try:
        st = path.stat()
        try:
            rows = json.loads(path.read_text())
        except (OSError, ValueError):
            return 0
        pair = path.stem
        ph = "(" + ",".join("?" * (len(COLS) + 2)) + ")"
        _t = time.time
        t0 = _t()
        con.execute("DELETE FROM rows WHERE pair = ?", (pair,))
        t1 = _t()
        vals = [_values(r, pair) for r in rows if r.get("coin")]
        t2 = _t()
        con.executemany(
            f"INSERT INTO rows ({','.join(COLS)},monthly,pair) VALUES {ph}",
            vals)
        t3 = _t()
        coin = rows[0].get("coin") if rows else None
        tf = rows[0].get("tf") if rows else None
        # the state file too, so the storage screen never has to read 1.7 GB
        combos, version, last_ms, state_bytes = 0, "", 0, 0
        if coin and tf:
            try:
                sp = msw.STATES / f"{coin}-{tf}.json"
                state_bytes = sp.stat().st_size
                stt = json.loads(sp.read_text())
                last_ms = int(stt.get("__last_ms__") or 0)
                version = stt.get("__version__") or ""
                combos = sum(1 for k in stt if not str(k).startswith("__"))
            except (OSError, ValueError, TypeError):
                pass
        con.execute("INSERT OR REPLACE INTO pairs "
                    "(pair,mtime,size,n,at,coin,tf,signals,combos,version,"
                    " last_ms,rows_mtime,bytes) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pair, st.st_mtime, st.st_size, len(rows), time.time(),
                     coin, tf,
                     "\n".join(sorted({r.get("signal") for r in rows
                                        if r.get("signal")})),
                     combos, version, last_ms, st.st_mtime,
                     st.st_size + state_bytes))
        con.commit()
        if DEBUG:
            print(f"[rows-index]      delete {t1-t0:.2f}s  build {t2-t1:.2f}s  "
                  f"insert {t3-t2:.2f}s  commit {_t()-t3:.2f}s", flush=True)
        return len(rows)
    finally:
        if own:
            con.close()


SETTLE_S = 60.0


def stale_watermark(pair: str) -> bool:
    """Has this pair FINISHED since it was indexed, without its row file
    changing? The completion mark lives in the state file, not the row file."""
    coin, _, tf = pair.rpartition("-")
    if not coin:
        return False
    try:
        live = msw.pair_watermark(coin, tf)
    except Exception:
        return False
    if not live:
        return False
    def _known():
        with _open(readonly=True) as con:
            r = con.execute("SELECT last_ms FROM pairs WHERE pair = ?",
                            (pair,)).fetchone()
            return None if r is None else (r[0] or 0)

    was = _missing_ok(_known, None)
    return was is not None and int(was) != int(live)


def _missing_ok(fn, default):
    """Readers never create anything: DDL on a read path put the indexer and
    every poll in a queue behind each other. If the schema is not there yet,
    say so with an empty answer -- ensure() runs at startup and before a sync.
    """
    try:
        return fn()
    except sqlite3.Error:
        return default


def stale_pairs(now: float | None = None) -> list:
    """Pair files whose (mtime, size) differs from what is indexed.

    A pair being worked on right now is SKIPPED until its file stops moving
    for `SETTLE_S`. The sweep checkpoints every 200 combinations, so each of
    the seven in-flight pairs rewrites a file of up to 9.7 MB every few
    seconds; re-indexing those on every request would burn more disk than the
    sweep itself, to publish rows that are about to be replaced. A pair that
    has never been indexed is taken immediately — waiting a minute to show a
    brand-new coin is a different, worse bug.
    """
    if not msw.ROWDIR.exists():
        return []
    now = time.time() if now is None else now
    def _known():
        with _open(readonly=True) as con:
            return {r["pair"]: (r["mtime"], r["size"])
                    for r in con.execute("SELECT pair,mtime,size FROM pairs")}

    known = _missing_ok(_known, {})
    new, changed = [], []
    for f in sorted(msw.ROWDIR.glob("*.json")):
        try:
            st = f.stat()
        except OSError:
            continue
        # The ROW file being unchanged is not enough: a pair FINISHING writes
        # its watermark to the STATE file, and the storage screen reads
        # last_ms from here. 392 finished pairs were still reported
        # "interrupted part-way" on 2026-08-23 because only the row file was
        # watched. A tail read settles it in under a millisecond.
        if (known.get(f.stem) == (st.st_mtime, st.st_size)
                and not stale_watermark(f.stem)):
            continue
        if f.stem not in known:
            new.append(f)
            continue
        if now - st.st_mtime < SETTLE_S:
            continue                       # still being written; catch it later
        changed.append(f)
    # NEVER-INDEXED FIRST. Both lists are alphabetical and the sweep works
    # alphabetically, so a single list let 85 already-known pairs (which the
    # sweep keeps rewriting at every checkpoint) consume the whole budget
    # forever: the row count climbed 690,630 -> 715,593 while the pair count
    # sat at 85 and 43 finished coins stayed invisible. A pair nobody has ever
    # seen is missing; a pair that moved is merely a little stale.
    return new + changed


def sync(paths: Iterable[Path] | None = None, *, budget_s: float = 0.0,
         now: float | None = None, max_pairs: int = 0,
         force: bool = False) -> dict:
    """Index every changed pair. `budget_s` stops early so a caller on a timer
    never runs long; the rest is picked up next time. `now` moves the settle
    window, which is how a test says "pretend a minute has passed".

    WHILE A SWEEP IS RUNNING THIS DOES NOTHING unless `force`. Measured on
    the operator's PC on Aug 26, 2026, store on a spinning HDD: trickling one
    pair every 10 s held the sweep to 36 pairs/hour, and killing the indexer
    took the same eleven workers to 220 pairs/hour. The disk was doing 384
    random write IOPS at 5 MB/s with a queue of 5.2 while the workers waited
    at 41% CPU. The trickle could not have caught up either: eleven workers
    finish ~22 pairs a minute and the trickle indexes 6. So it stands down,
    reports the backlog, and takes the lot in one BULK pass when the sweep
    ends. `force` is for a person asking directly.
    """
    ensure()
    if not force and _machine_is_busy():
        left = len(list(paths) if paths is not None else stale_pairs(now))
        return {"pairs": 0, "rows": 0, "seconds": 0.0, "left": left,
                "queued": left, "paused": True}
    todo = list(paths) if paths is not None else stale_pairs(now)
    queued = len(todo)
    if max_pairs:
        todo = todo[:max_pairs]
    started, done, rows = time.time(), 0, 0
    bulk = len(todo) > BULK_PAIRS
    if DEBUG:
        print(f"[rows-index] sync: {len(todo)} to do, opening writer"
              f"{' (BULK)' if bulk else ''}", flush=True)
    with _open() as con:
        if bulk:
            # readers still work while these are gone: SQLite falls back to a
            # scan, which is slower per query but never blocked, and status()
            # keeps saying the list is still filling in.
            for name in FILTER_INDEXES:
                con.execute(f"DROP INDEX IF EXISTS {name}")
            con.commit()
        if DEBUG:
            print("[rows-index] writer open", flush=True)
        for f in todo:
            if DEBUG:
                print(f"[rows-index]   -> {f.name}", flush=True)
            rows += index_pair(f, con)
            done += 1
            if DEBUG:
                print(f"[rows-index]   ok {f.name} ({rows:,} rows so far)",
                      flush=True)
            # A BULK pass ignores the budget on purpose: it drops four indexes
            # up front and rebuilds them at the end, and paying that twice a
            # minute is what stalled the fill at 52 of 232 pairs. Incremental
            # passes still stop on time.
            if not bulk and budget_s and time.time() - started > budget_s:
                break
        if bulk:
            t_idx = time.time()
            for ddl in FILTER_INDEXES.values():
                con.execute(ddl)
            con.commit()
            if DEBUG:
                print(f"[rows-index] rebuilt read indexes in "
                      f"{time.time() - t_idx:.1f}s", flush=True)
        # NO wal_checkpoint(TRUNCATE) here. TRUNCATE takes an EXCLUSIVE lock,
        # which blocks every reader — with the grid polling every 4 seconds the
        # two convoyed into each other: reads went 0.04s -> 25s (timeout) and
        # the indexer sat at 26 pairs. SQLite's automatic checkpoint is PASSIVE
        # and keeps the WAL bounded without ever locking a reader out; the size
        # is set with wal_autocheckpoint in ensure().
    return {"pairs": done, "rows": rows, "left": queued - done,
            "seconds": round(time.time() - started, 2)}


def sync_in_background(budget_s: float = 0.0, *, force: bool = False) -> bool:
    """Kick a sync unless one is already running -- or a sweep is (see sync).
    Never blocks the caller."""
    if _syncing.is_set():
        return False
    if not force and _machine_is_busy():
        return False
    _syncing.set()

    def run() -> None:
        try:
            sync(budget_s=budget_s, force=force)
        except Exception:
            pass
        finally:
            _syncing.clear()

    threading.Thread(target=run, name="rows-index-sync", daemon=True).start()
    return True


def syncing() -> bool:
    return _syncing.is_set()


# ------------------------------------------------------------------ reading
def _where(coin=None, tf=None, signal=None, profitable=False,
           min_trades=0, *, order_owns_index=False) -> tuple:
    """The WHERE clause and its arguments.

    `order_owns_index=True` is for the ROW query, which has an ORDER BY and a
    LIMIT: every filter except a named COIN is written `+col = ?`, the `+`
    telling SQLite not to use an index for that term. Measured on the
    operator's 21,858,026-row store, all indexes present:

      WHERE tf='1h' AND coin='KAVA' AND trades>=100 ORDER BY winrate DESC
        planner's choice  SEARCH rows USING INDEX rows_tf (tf=?)
                          USE TEMP B-TREE FOR ORDER BY     -> minutes
        with +tf, +trades SEARCH rows USING INDEX rows_coin (coin=?)  -> ms

      WHERE trades >= 100 ORDER BY winrate DESC
        planner's choice  SEARCH rows USING INDEX rows_trades (trades>?)
                          USE TEMP B-TREE FOR ORDER BY     -> did not return
        with +trades      SCAN rows USING INDEX rows_winrate -> 0.03 s

    So: a coin is the one filter selective enough to drive the plan (~18k rows
    for a pair); tf is 12% of the store and `trades >= 100` most of it, and
    letting either drive means sorting millions of rows to return 300. The
    COUNT has no ORDER BY, wants the most selective index it can get, and asks
    for the plain form.
    """
    sql, args = [], []
    # A named coin outranks tf and signal in BOTH statements: the count chose
    # `SEARCH rows USING INDEX rows_tf (tf=?)` — 2.5M rows for 1h — and hung,
    # while rows_coin answers the same question in milliseconds (~18k rows for
    # a pair). `trades` steps aside only for the row query, which has the
    # ORDER BY to serve; the count wants rows_trades.
    step_aside = "+" if (order_owns_index or coin) else ""
    for col, val, keeps_index in (("coin", coin, True), ("tf", tf, False),
                                  ("signal", signal, False)):
        if val:
            sql.append(f"{'' if keeps_index else step_aside}{col} = ?")
            args.append(val)
    if profitable:
        sql.append("profit > 0")
    # A COUNT, in the unit the trades column prints (CLAUDE.md rule G).
    # Ranking the operator's store by win rate returned `CHF 30m soldiers
    # 100.00% over 1 trade` at the top: a rate with no denominator is not a
    # result.
    if min_trades and int(min_trades) > 0:
        floor_hint = "+" if (order_owns_index and not coin) else ""
        sql.append(f"{floor_hint}trades >= ?")
        args.append(int(min_trades))
    return (" WHERE " + " AND ".join(sql) if sql else ""), args


# column -> the direction worth seeing first. Best profit and best win rate
# are the TOP of the column; the smallest worst-dip is the BOTTOM. A second
# click on the header flips it (`desc=`), which is what the operator meant
# by "it does not sort to highes or lowest" (2026-08-26).
SORTS = {
    "profit": True,
    "winrate": True,
    "trades": True,
    "dd": False,                 # smallest worst-dip first: least painful
}

# Which index each order needs. Measured 2026-08-26 on the operator's own
# 21,582,584-row store: `ORDER BY winrate DESC` with no index had not returned
# after TEN MINUTES, and through the UI it was an HTTP 500 under a caption that
# already said "showing top 300 by win %" — a false label on unsorted rows.
# So an order whose index is missing is REFUSED, with the reason, and the index
# is built in the background rather than the screen hanging on it.
SORT_INDEX = {
    "profit": "rows_profit",
    "winrate": "rows_winrate",
    "trades": "rows_trades",
    "dd": None,                  # small: dd has no index, and is not offered
}
_BUILDING: set = set()
# rows we are willing to sort with no index behind the order
UNINDEXED_LIMIT = 200_000
# how far a FILTERED count will go before it answers "N+"
COUNT_CAP = 5_000
# rows one request may return. 2,000 was the cap while the screen showed a
# fixed 300; the operator asked to see the whole store, so a page can now be
# 5,000 and `iter_rows` streams the rest with no ceiling at all.
MAX_LIMIT = 5_000


def _rows_estimate() -> int:
    """How many rows the store holds, from the pair summaries (no scan)."""
    def _read():
        with _open(readonly=True) as con:
            return int(con.execute(
                "SELECT COALESCE(SUM(n),0) FROM pairs").fetchone()[0])
    return int(_missing_ok(_read, 0))


class SortNotReady(RuntimeError):
    """This order needs an index that is still being built."""


def has_index(name: str) -> bool:
    def _read():
        with _open(readonly=True) as con:
            return bool(con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
                (name,)).fetchone())
    return bool(_missing_ok(_read, False))


def build_sort_index(sort: str) -> bool:
    """Create the index an order needs, in a daemon thread. Returns False when
    there is nothing to build or a build is already under way."""
    name = SORT_INDEX.get(sort)
    ddl = FILTER_INDEXES.get(name or "")
    if not name or not ddl or name in _BUILDING or has_index(name):
        return False
    _BUILDING.add(name)

    def _work() -> None:
        try:
            with _open() as con:
                con.execute("PRAGMA busy_timeout=600000")
                con.execute(ddl)
            print(f"[rows-index] built {name}", flush=True)
        except Exception as exc:                                  # noqa: BLE001
            print(f"[rows-index] could not build {name}: {exc}", flush=True)
        finally:
            _BUILDING.discard(name)

    threading.Thread(target=_work, name=f"idx-{name}", daemon=True).start()
    return True


def query(coin=None, tf=None, signal=None, profitable=False,
          limit=500, offset=0, sort="profit", min_trades=0,
          desc=None) -> dict:
    """Rows sorted by `sort` (SORTS), profit first by default.

    STRICTLY READ-ONLY. It creates nothing and it indexes nothing.

    An earlier version filled an empty index from here, bounded to a few
    seconds. That put a WRITER on a route the grid polls every 4 seconds: the
    polls fought the indexer for SQLite's single write lock, the loop logged
    `database is locked`, and one pair that takes 0.7s alone took 29.2s. The
    index catches up on its own timer (`start_keeping_up`), and `status()`
    reports how far behind it is so the screen can say so.
    """
    where, args = _where(coin, tf, signal, profitable, min_trades)
    # the row select streams its own ORDER BY index; the count rides the
    # trades index instead (see _where)
    row_where, row_args = _where(coin, tf, signal, profitable, min_trades,
                                 order_owns_index=True)
    lim = max(0, min(int(limit), MAX_LIMIT))
    key = str(sort or "profit")
    if key not in SORTS:
        raise ValueError(
            f"unknown sort {key!r}; use one of {sorted(SORTS)}")
    down = SORTS[key] if desc is None else bool(desc)
    order = f"{key} {'DESC' if down else 'ASC'}"
    need = SORT_INDEX.get(key)
    # A missing index only matters at size. Sorting 4,000 rows without one is
    # instant; sorting 21,582,584 had not finished in ten minutes (measured
    # 2026-08-26) and became an HTTP 500 under a caption that already said
    # "top 300 by win %". So: small store, sort freely; big store, the order
    # must have its index and is refused with the reason until it does.
    if need and _rows_estimate() > UNINDEXED_LIMIT and not has_index(need):
        build_sort_index(key)
        raise SortNotReady(
            f"ranking by {key} needs its index ({need}); it is being "
            f"built in the background — try again shortly")

    def _read():
        with _open(readonly=True) as con:
            if where:
                # COUNT(*) with a filter is a full scan of tens of millions
                # of rows (30 s on the operator's store, and the proxy gave
                # up at 30). Stop at COUNT_CAP and let the caller print the
                # "+" — an exact number nobody can wait for is worth less
                # than an honest bound.
                total = con.execute(
                    f"SELECT COUNT(*) FROM (SELECT 1 FROM rows{where} "
                    f"LIMIT {COUNT_CAP + 1})", args).fetchone()[0]
            else:
                # COUNT(*) over every row is a full scan (25ms at 27k rows,
                # and this table is heading for tens of millions). The pair
                # summaries already carry the counts, and they sum to it.
                total = con.execute(
                    "SELECT COALESCE(SUM(n),0) FROM pairs").fetchone()[0]
            # id breaks ties: without it two rows on the same profit swap
            # places between 4-second polls and the row moves out from under
            # the operator's cursor mid-click.
            got = con.execute(
                f"SELECT * FROM rows{row_where} ORDER BY {order}, id ASC "
                f"LIMIT ? OFFSET ?",
                (*row_args, lim, max(0, int(offset)))).fetchall()
        return total, got

    total, got = _missing_ok(_read, (0, []))
    capped_count = bool(where) and total > COUNT_CAP
    total = min(total, COUNT_CAP) if capped_count else total
    out = []
    for r in got:
        # r.keys(), NOT `in r`: a sqlite3.Row iterates its VALUES
        d = {k: r[k] for k in r.keys() if k != "pair"}   # noqa: SIM118
        d["stop_reachable"] = bool(d.get("stop_reachable"))
        try:
            d["monthly"] = json.loads(d.get("monthly") or "{}")
        except ValueError:
            d["monthly"] = {}
        out.append(d)
    # the caller captions the table with this, so it is never a literal
    return {"rows": out, "total": total, "sort": key, "desc": down,
            # the caption prints "5,000+ match" when the count was capped,
            # never a bare 5,000 that reads as exact
            "total_capped": capped_count,
            "min_trades": int(min_trades or 0)}


def iter_rows(coin=None, tf=None, signal=None, profitable=False,
              sort="profit", min_trades=0, desc=None, batch=5_000):
    """Every matching row, in the asked order, a batch at a time.

    No limit and no list: 21,858,026 rows will not fit in a browser table or in
    this process's memory, and the operator asked to see ALL of them ("i can
    still only see like about 100 rows give me all", 2026-08-26). So the export
    streams — the reader gets a cursor, not an array.

    Yields dicts shaped exactly like `query()["rows"]`, so the CSV and the
    screen can never show different fields for the same row (kit item F).
    """
    key = str(sort or "profit")
    if key not in SORTS:
        raise ValueError(f"unknown sort {key!r}; use one of {sorted(SORTS)}")
    need = SORT_INDEX.get(key)
    if need and _rows_estimate() > UNINDEXED_LIMIT and not has_index(need):
        build_sort_index(key)
        raise SortNotReady(
            f"ranking by {key} needs its index ({need}); it is being built in "
            f"the background — try again shortly")
    down = SORTS[key] if desc is None else bool(desc)
    order = f"{key} {'DESC' if down else 'ASC'}"
    where, args = _where(coin, tf, signal, profitable, min_trades,
                         order_owns_index=True)
    step = max(100, int(batch))
    with _open(readonly=True) as con:
        cur = con.execute(
            f"SELECT * FROM rows{where} ORDER BY {order}, id ASC", args)
        while True:
            got = cur.fetchmany(step)
            if not got:
                return
            for r in got:
                d = {k: r[k] for k in r.keys() if k != "pair"}   # noqa: SIM118
                d["stop_reachable"] = bool(d.get("stop_reachable"))
                try:
                    d["monthly"] = json.loads(d.get("monthly") or "{}")
                except ValueError:
                    d["monthly"] = {}
                yield d


def facets() -> dict:
    """Filter dropdowns, read from the per-pair summary — 85 short rows rather
    than three DISTINCT scans over every measurement."""
    def _read():
        coins, tfs, signals = set(), set(), set()
        with _open(readonly=True) as con:
            for r in con.execute("SELECT coin,tf,signals FROM pairs"):
                if r["coin"]:
                    coins.add(r["coin"])
                if r["tf"]:
                    tfs.add(r["tf"])
                signals.update(x for x in (r["signals"] or "").split("\n") if x)
        return {"coins": sorted(coins), "tfs": sorted(tfs),
                "signals": sorted(signals)}

    return _missing_ok(_read, {"coins": [], "tfs": [], "signals": []})


def pair_storage() -> list:
    """One row per measured pair, for the storage screen — from the index, so
    it costs one small query instead of parsing every row file and every state
    file (2 GB) on a route the page polls."""
    def _read():
        with _open(readonly=True) as con:
            return [dict(r) for r in con.execute(
                "SELECT coin,tf,n,combos,version,last_ms,rows_mtime,bytes,at "
                "FROM pairs WHERE coin IS NOT NULL "
                "ORDER BY coin, tf")]

    return _missing_ok(_read, [])


def status() -> dict:
    """What the index holds vs what is on disk — so the UI can say "indexing"
    instead of quietly showing a partial list as if it were everything."""
    on_disk = len(list(msw.ROWDIR.glob("*.json"))) if msw.ROWDIR.exists() else 0

    def _read():
        with _open(readonly=True) as con:
            # SUM(n), never COUNT(*) FROM rows: this is polled every few
            # seconds and a full scan of the row table grows without bound.
            r = con.execute("SELECT COUNT(*), COALESCE(SUM(n),0), MAX(at) "
                            "FROM pairs").fetchone()
            return r[0], r[1], r[2]

    pairs, rows, newest = _missing_ok(_read, (0, 0, None))
    busy = _machine_is_busy()
    return {"pairs_indexed": pairs, "pairs_on_disk": on_disk, "rows": rows,
            "behind": max(0, on_disk - pairs), "syncing": syncing(),
            # kept for older readers; both mean "a sweep owns the disk"
            "trickling": busy, "paused": busy, "updated": newest}



# ------------------------------------------------------- keeping up on its own
_loop_stop = threading.Event()
_loop_thread: threading.Thread | None = None


PIDFILE = DB_PATH.parent / "rows_index.pid"


def _running_elsewhere() -> bool:
    """Is an indexer process already alive?"""
    try:
        pid = int(PIDFILE.read_text().strip())
    except (OSError, ValueError):
        return False
    return portable.pid_alive(pid)


def spawn_indexer() -> int | None:
    """Run the indexer in ITS OWN PROCESS.

    It lived inside the API at first, on a timer thread, and that was the last
    of this bug's disguises. Parsing a 9.7 MB pair file and building 18,000
    row tuples is pure Python: it HOLDS THE GIL, so every request behind it
    waited. `/api/jobs/backtest` — one small file — measured 1.7s to 2.2s, and
    the header's health probe timed out, which the UI printed as "API
    unreachable". A separate process shares nothing but the SQLite file, which
    is what WAL is for.
    """
    import os
    import subprocess
    import sys

    if _running_elsewhere():
        return None
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "tradingagents.rows_index"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **portable.DETACHED,
        env={**os.environ, "ROWS_INDEX_CHILD": "1"})
    PIDFILE.write_text(str(proc.pid))
    return proc.pid


def start_keeping_up(every_s: float = 10.0, budget_s: float = 60.0) -> bool:
    """Index on a timer. Used INSIDE the indexer process, never in the API —
    see spawn_indexer for why.
    """
    global _loop_thread
    if _loop_thread and _loop_thread.is_alive():
        return False

    def run() -> None:
        first = True
        while first or not _loop_stop.wait(every_s):
            first = False
            try:
                if _machine_is_busy():
                    # stand down entirely: on a slow disk the indexer and the
                    # sweep fight over the same platter and the sweep loses 6x
                    if not _said_paused[0]:
                        print(f"[rows-index] paused: a backtest is running "
                              f"({len(stale_pairs())} pairs waiting; they are "
                              f"indexed in one bulk pass when it ends)",
                              flush=True)
                        _said_paused[0] = True
                    continue
                _said_paused[0] = False
                todo = stale_pairs()
                if todo:
                    _syncing.set()         # so status() reports the timer too
                    try:
                        got = sync(budget_s=budget_s)
                    finally:
                        _syncing.clear()
                    checkpoint_if_bloated()
                    print(f"[rows-index] +{got['pairs']} pairs "
                          f"({got['rows']:,} rows) in {got['seconds']}s, "
                          f"{got['left']} left", flush=True)
            except Exception as exc:
                # never end the loop -- but never hide the reason either
                print(f"[rows-index] sync failed: {exc!r}", flush=True)

    _loop_stop.clear()
    _loop_thread = threading.Thread(target=run, name="rows-index-loop",
                                    daemon=True)
    _loop_thread.start()
    return True


def stop_keeping_up() -> None:
    _loop_stop.set()


WAL_CAP_BYTES = 2_000_000_000        # 2 GB before a blocking truncate is worth it


def wal_bytes() -> int:
    try:
        return (DB_PATH.parent / (DB_PATH.name + "-wal")).stat().st_size
    except OSError:
        return 0


def checkpoint_if_bloated(cap: int = WAL_CAP_BYTES) -> dict:
    """Fold an oversized write-ahead log back into the database.

    Only when it is genuinely large, because TRUNCATE takes an exclusive lock
    and running it every cycle convoyed with the UI's polling. Left alone it is
    unbounded: a single abandoned reader pinned it on 2026-08-24 and it grew to
    27.4 GB beside a 13.8 GB database, taking the volume to 3.5 GB free — the
    same wall that had already killed the sweep and the trading runner.
    """
    before = wal_bytes()
    if before < cap:
        return {"checkpointed": False, "wal": before}
    try:
        with _open() as con:
            con.execute("PRAGMA busy_timeout=60000")
            r = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    except sqlite3.Error as exc:
        return {"checkpointed": False, "wal": before, "error": str(exc)[:80]}
    after = wal_bytes()
    print(f"[rows-index] WAL {before/1e9:.1f} GB -> {after/1e9:.1f} GB "
          f"(busy={r[0] if r else '?'})", flush=True)
    return {"checkpointed": True, "wal": after, "was": before}


def main() -> int:
    """The indexer process. Nice, so it never outranks a click either."""
    import os

    with contextlib.suppress(OSError, AttributeError):
        os.nice(5)
    ensure()
    start_keeping_up()
    try:
        while True:
            _loop_stop.wait(3600)
    except KeyboardInterrupt:
        stop_keeping_up()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
