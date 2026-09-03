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
import os
import sqlite3
import subprocess
import sys
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
# Dropped before every bulk fill and rebuilt at its end, so every entry here
# is paid for again after each fill. Measured one at a time on the operator's
# 31,159,970-row store: rows_coin 16.7 min, rows_winrate 4.4, rows_tf 4.1,
# rows_signal 4.3, rows_id 3.5, rows_trades 3.4. The tf and signal indexes are
# NEVER chosen (a plan that filters on them is written `+tf`/`+signal` so the
# ORDER BY index can drive), nothing queries by id yet, and the count is
# LIMIT-bounded without rows_trades — so carrying those four cost about
# fifteen minutes of rebuild after every fill and bought nothing.
# Dropped ONLY by a load big enough that rebuilding beats maintaining (BIG_FILL).
# Everything the screen orders by lives in KEEP_INDEXES instead: on 2026-08-26
# rows_winrate kept vanishing because every time the sweep paused, the indexer
# found 800+ stale pairs, called it a bulk fill, dropped it — and any
# interruption before the rebuild left the operator's ranking answering 503 for
# hours. "when i clickk winrate header, the only sorted are the ones on the
# page" was that, three times over.
FILTER_INDEXES: dict = {}

# NEVER dropped by an incremental fill:
#   rows_pair    delete-by-pair needs it
#   rows_profit  the order the screen opens on
#   rows_coin    the coin filter names it explicitly (see _indexed_by); without
#                it SQLite walked the whole profit index for one coin in 974 and
#                the request did not return in 120 s
#   rows_winrate (winrate, trades, id) — the operator's ranking, with the trade
#                floor IN the index so "best win rate with at least N trades" is
#                an index-only filter
# Carrying them costs insert speed during a fill (six indexes measured 1.5
# pairs/min against 73 with none); losing them costs the feature.
KEEP_INDEXES = (
    "CREATE INDEX IF NOT EXISTS rows_pair ON rows (pair)",
    "CREATE INDEX IF NOT EXISTS rows_profit ON rows (profit DESC, id)",
    "CREATE INDEX IF NOT EXISTS rows_coin ON rows (coin, profit DESC)",
    "CREATE INDEX IF NOT EXISTS rows_winrate ON rows (winrate DESC, trades, id)",
)
# The wide win-rate index. Built on demand, not by ensure(): it is 45 min on a
# 35,863,520-row store, and everything works (slower) without it.
WIDE_WINRATE = ("CREATE INDEX IF NOT EXISTS rows_wr2 ON rows "
                "(winrate DESC, trades, profit DESC, id)")
# THE WIN-RATE SEEK THAT CARRIES SIZING. rows_wr2 stops before it, so a
# request with `sizing = flat` beside a win-rate floor still had to read every
# candidate ROW off the disk to test it. Measured on the operator's own
# request (win % >= 80 AND flat AND 100+ trades, ranked by profit, 49,770,670
# rows): 3,071.7 s on rows_winrate against 0.34 s here, and 0.01 s when the
# ranking is by win %. 41.7 min to build.
WIDER_WINRATE = ("CREATE INDEX IF NOT EXISTS rows_wr3 ON rows "
                 "(winrate DESC, trades, sizing, profit DESC, id)")
# The wide PROFIT index — the same trick as rows_wr2, for the order the page
# opens on. rows_profit is (profit DESC, id), so a filter on anything else has
# to read every candidate ROW off the disk to test it. The biggest profits in
# this store are all martingale rows (the ladder multiplies them), so
# `sizing = flat` ranked by profit had to walk millions of rows to find 500 —
# measured 2026-08-27 on the operator's store, 35,863,520 rows: HTTP 503 at the
# 20 s budget for `flat` alone, `flat AND tf=1h`, `flat AND 100+ trades` and
# `flat AND profit > 0`; only a named coin answered (2.0 s). Carrying the
# filter columns next to profit makes the same walk index-only.
WIDE_PROFIT = ("CREATE INDEX IF NOT EXISTS rows_pr2 ON rows "
               "(profit DESC, sizing, tp, winrate, trades, id)")
# Finding one row by the code printed in its first column (#6YACZSXX). The
# operator asked for it by example, 2026-08-27: "add filter to input a specific
# id, it should get speicic id example #6YACZSXX" — and it is CLAUDE.md kit item
# H, where quoting a row by its id is how the wrong config stops being deployed.
# `id` carries no index of its own, so the lookup was a scan: measured on the
# operator's store (35,863,520 rows), `WHERE id = ?` had not returned after 40 s
# — plain (SCAN rows) and over both covering indexes that already hold the id
# (rows_profit, rows_wr2). Built on demand like the other wide ones.
ROW_ID_INDEX = "CREATE INDEX IF NOT EXISTS rows_id ON rows (id)"
# ONE SIGNAL, RANKED. Measured on the operator's rebuilt store
# (49,043,628 rows) the moment the five 4-hour setups landed in it:
#   /api/strategies?signal=cf_bosfvg   -> HTTP 500 after 30.1 s (the proxy
#                                         gave up before the budget did)
#   /api/strategies?signal=cf_fundfade -> HTTP 503 at the 20 s budget
# `signal` had no index and stepped aside for the ORDER BY, on the
# reasoning that one rule of 105 cannot drive a plan. That stopped being
# true: cf_bosfvg is 161,828 rows of 49 million (0.3%), and the walk down
# rows_profit read a candidate ROW off the disk for every test.
# (signal, profit DESC, id) makes it a seek whose rows come out already
# in order -- no temp b-tree either. ~5 min to build on a compact file.
SIGNAL_INDEX = ("CREATE INDEX IF NOT EXISTS rows_signal ON rows "
                "(signal, profit DESC, id)")
# a load this size is a rebuild, not an update: there, dropping and recreating
# is faster than maintaining (measured at 73 pairs/min against 1.5)
BIG_FILL = 500
READ_INDEXES = tuple(FILTER_INDEXES.values()) + KEEP_INDEXES
# name -> DDL, for the on-demand builder (a kept index can still be
# missing: an older database, or a BIG_FILL that was interrupted)
INDEX_DDL = {**FILTER_INDEXES,
             **{d.split()[5]: d for d in KEEP_INDEXES},
             "rows_wr2": WIDE_WINRATE,
             "rows_wr3": WIDER_WINRATE,
             "rows_pr2": WIDE_PROFIT,
             "rows_id": ROW_ID_INDEX,
             "rows_signal": SIGNAL_INDEX}

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


def _connect(readonly: bool = False,
             same_thread: bool = True) -> sqlite3.Connection:
    """`synchronous=OFF` is deliberate: every row here is derived from a JSON
    file that is still the source of truth, so a torn write costs a re-index,
    never a measurement. Paid for by inserts that no longer fsync.
    """
    # `same_thread=False` is for a GENERATOR that is handed between threads:
    # Starlette advances a StreamingResponse's iterator in a threadpool, and
    # each `next()` can land on a different worker. sqlite3 refuses a connection
    # used off its creating thread, so the CSV export died mid-stream with
    # `SQLite objects created in a thread can only be used in that same thread`
    # — and StreamingResponse cannot send an error once it has started, so the
    # download just STOPPED: 5,000 rows of the 43,867 that matched, a file that
    # looked complete (operator, 2026-08-27: "i want thefilterd result to be
    # downloaded only" — the filters were right, the file was cut short).
    # Only ever passed by a serial consumer: one thread at a time, in order.
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if readonly and DB_PATH.exists():
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=60.0,
                              check_same_thread=same_thread)
    else:
        con = sqlite3.connect(DB_PATH, timeout=60.0,
                              check_same_thread=same_thread)
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
def _open(readonly: bool = False, same_thread: bool = True):
    """`with sqlite3.connect(...)` COMMITS but does NOT CLOSE. Every poll of
    /api/strategies therefore leaked an open reader, and because each writer
    connection re-issued `PRAGMA journal_mode=WAL` -- which needs a brief
    exclusive lock -- the indexer then blocked behind those readers forever:
    `syncing: True` with the pair count frozen at 5 for four minutes, while the
    same code in a lone process did a pair every 0.7s.
    """
    con = _connect(readonly, same_thread)
    try:
        yield con
        if not readonly:
            con.commit()
    finally:
        con.close()


def _budgeted(con, seconds=None):
    """Abort this connection's work after `seconds` of wall clock.

    SQLite calls the progress handler every N virtual-machine steps; returning
    non-zero raises `sqlite3.OperationalError("interrupted")`. 10,000 steps is
    a fraction of a millisecond of work, so the check is free and the deadline
    is honoured to well under a second.
    """
    budget = QUERY_BUDGET_S if seconds is None else seconds
    deadline = time.monotonic() + float(budget)

    def _tick():
        return 1 if time.monotonic() > deadline else 0

    con.set_progress_handler(_tick, 10_000)
    return deadline


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
        # COIN AND TF COME FROM THE PAIR KEY, not from the first row.
        #
        # Reading them off rows[0] meant an EMPTY pair recorded neither, so its
        # state watermark was never indexed (last_ms stayed 0) while the state
        # file carried a real one -- and stale_watermark() then reported the
        # pair unfinished forever. Measured on the operator's store after the
        # rebuild of 2026-08-28: 758 pairs permanently stale, every one of them
        # a 1d pair whose row file is `[]` because the trade floor kept nothing.
        # The indexer re-read all 758 on every pass and produced nothing.
        # ensure()'s own backfill had already learned this ("the key IS the
        # answer"); index_pair had not.
        # The ROW is authoritative when there is one: it carries the canonical
        # coin ("AAA"), while a file stem may carry the symbol form
        # ("AAA_USDT-1h") -- and reading the key first made a coin filter count
        # zero rows (test_exact_page_count).
        #
        # The KEY is the fallback, and it is what fixes an EMPTY pair: with no
        # rows to read, neither field was recorded, so the block below never
        # copied the state watermark and stale_watermark() called the pair
        # unfinished forever. Measured 2026-08-28: 758 pairs permanently
        # stale, every one a 1d pair whose row file is `[]`.
        coin = rows[0].get("coin") if rows else None
        tf = rows[0].get("tf") if rows else None
        if not coin or not tf:
            k_coin, _, k_tf = pair.rpartition("-")
            coin = coin or (k_coin.replace("_USDT", "") or None)
            tf = tf or (k_tf or None)
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

    An INTERRUPTION is re-raised. `_budgeted` stops a read that has run past
    QUERY_BUDGET_S by raising OperationalError("interrupted"), and swallowing
    that here turned "this filter needs longer than 20s" into "0 rows, total
    0" -- an empty screen presented as an answer, which is worse than the
    30-second HTTP 500 the budget exists to replace.
    """
    try:
        return fn()
    except sqlite3.Error as exc:
        if "interrupt" in str(exc).lower():
            raise
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
    # BULK_PAIRS still decides how CHATTY the fill is; only BIG_FILL earns
    # the right to drop the indexes the screen is ordering by right now.
    bulk = len(todo) > BIG_FILL
    if DEBUG:
        print(f"[rows-index] sync: {len(todo)} to do, opening writer"
              f"{' (BULK)' if bulk else ''}", flush=True)
    with _open() as con:
        # NOTHING IS DROPPED HERE, however big the fill.
        #
        # It used to drop rows_profit/rows_coin/rows_winrate past BIG_FILL to
        # reload faster and rebuild them at the end. On 2026-08-27 at 12:48am
        # that emptied the screen: the default order answered "ranking by
        # profit needs its index (rows_profit); it is being built" for the
        # ~25 minutes the three rebuilds took, and the operator asked "why does
        # it not show anything". A slower fill is a cost the operator never
        # sees; a blank Stored strategies is the product not working. A
        # rebuild-from-the-pair-files is a deliberate offline operation and can
        # drop indexes itself.
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
            for ddl in READ_INDEXES:
                con.execute(ddl)
            forget_indexes()
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
    # ANY pass that indexed a pair means the store grew — a BACKTEST of one
    # coin, an UPDATE BACKTEST, the reindex button, the trickle. `bulk` is
    # len(todo) > BIG_FILL (500 pairs), so hanging this off `bulk` meant the
    # operator's normal clicks never triggered it: *"when i click backtest or
    # update backtest will it work too?"* (2026-08-27) — no, it would not have.
    # The on-demand indexes stay OUT of READ_INDEXES on purpose (a fill pays for
    # every index it carries: 1.5 pairs/min with six against 75 with none), so
    # they are started here, in DETACHED children, instead of the panel finding
    # out they are missing. The check itself is 11 sqlite_master lookups and
    # spawns nothing when they are all there.
    # See .claude/skills/store-indexes.
    if done:
        _after_fill_indexes()
    return {"pairs": done, "rows": rows, "left": queued - done,
            "seconds": round(time.time() - started, 2)}


def _after_fill_indexes() -> list:
    """Start the on-demand indexes a fill did not build. Never raises: a fill
    that finished must not be reported as failed because a build could not
    start."""
    try:
        return build_missing_indexes()
    except Exception as exc:                                      # noqa: BLE001
        print(f"[rows-index] could not start the missing index builds: "
              f"{type(exc).__name__}: {exc}", flush=True)
        return []


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
def balanced_score(row: dict, profit=None, winrate=None, trades=None,
                   green=None, months=None) -> tuple:
    """A 1-10 rating of win rate AND profit together, plus the sentence behind
    it. Higher is better.

    The operator's own brief, 2026-08-27: *"sometimes it has high winrate but
    since tp is low and sl is high, its still not profitable so that would be
    1-4/10"*. So PROFIT is the anchor, not the win rate:

      * a row that did not make money scores 1-3 whatever its win rate — the
        1-4 band the operator asked for, and the reason `high win % + TP 0.3 /
        SL 3.0` cannot look good here;
      * a profitable row starts at 4 and earns up to 10 on how much it makes per
        trade, how often it wins, how many months it was green, and whether its
        take-profit is even reachable against the round-trip cost (rule 11:
        under 20% comfortable, near 50% fatal, over 100% arithmetically
        impossible);
      * and it LOSES up to 2 for a worst dip bigger than the profit it earned,
        because that is the ladder emptying a $65 account on the way to a green
        total (the APEX incident: -$79.80 over 13 trades).

    `profit`/`winrate`/... override the row's own figures, which is how the
    LAST N MONTHS window re-rates a row over its own slice.

    Returns (score, why). The `why` is shown on hover: a number the operator
    cannot audit is a number they cannot use.
    """
    def pick(given, key, default=0.0):
        v = given if given is not None else row.get(key)
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    pf = pick(profit, "profit")
    wr = pick(winrate, "winrate")
    n = pick(trades, "trades")
    dip = pick(None, "dd")
    tp = pick(None, "tp")
    sl = pick(None, "sl")
    rt = pick(None, "rt")                     # round-trip cost, % of notional
    base = pick(None, "base", 5.0) or 5.0
    grn = pick(green, "green")
    mos = pick(months, "months")

    payoff = (tp / sl) if sl else 0.0        # TP against SL: the operator's axis

    bits = []
    if pf <= 0:
        # 1.0 - 3.0, and the win rate can only move it inside that band
        score = min(3.0, 1.0 + 2.0 * max(0.0, wr) / 100.0)
        bits.append(f"lost {pf:,.2f} USDT — a losing row cannot rate above 3.0")
        if tp and sl:
            bits.append(f"wins {wr:.2f}% of the time on TP {tp:g}% against SL "
                        f"{sl:g}% (payoff {payoff:.2f}x): "
                        + ("a tiny target behind a wide stop, so one loss "
                           "erases many wins" if payoff < 1
                           else "the target is wider than the stop, so the "
                                "losses are elsewhere"))
        return round(score, 1), "; ".join(bits)

    score = 4.0
    bits.append(f"made {pf:,.2f} USDT")

    # per-trade return on the margin staked: 0.5% of it is nothing, 5% is a lot
    per = (pf / n / base * 100) if n and base else 0.0
    add = min(2.0, max(0.0, per / 5.0 * 2.0))
    score += add
    bits.append(f"{per:.2f}% of the {base:g} USDT margin per trade (+{add:.1f})")

    # win rate, scaled across the band that actually varies (40% -> 90%)
    add = min(2.0, max(0.0, (wr - 40.0) / 50.0 * 2.0))
    score += add
    bits.append(f"{wr:.2f}% win rate (+{add:.1f})")

    # consistency: months in the black
    if mos:
        add = min(1.0, max(0.0, grn / mos))
        score += add
        bits.append(f"green in {int(grn)}/{int(mos)} months (+{add:.1f})")

    # is the target even reachable? cost/TP under 20% is comfortable (rule 11)
    if tp and rt:
        ratio = rt / tp
        add = 1.0 if ratio <= 0.2 else (0.5 if ratio <= 0.5 else 0.0)
        score += add
        bits.append(f"round-trip cost is {ratio * 100:.0f}% of the TP "
                    f"(+{add:.1f})")

    # TP AGAINST SL, the axis the operator named. A target wider than the stop
    # pays for itself; a tiny target behind a wide stop is the trap the artifact
    # has warned about since it was written ("one loss erases hundreds of wins")
    # and it is why a 90%-win row can still be a bad row.
    if tp and sl:
        if payoff >= 2:
            add = 1.0
        elif payoff >= 1:
            add = 0.5
        elif payoff >= 0.7:
            add = -0.5
        elif payoff >= 0.4:
            add = -1.0
        else:
            # TP 0.4 behind SL 3.0 is the trap by name: one loss erases many
            # wins, and a 10/10 there would be the number arguing with itself
            add = -1.5
        score += add
        bits.append(f"TP {tp:g}% against SL {sl:g}% — payoff {payoff:.2f}x "
                    f"({add:+.1f})")

    # A row that loses most of its trades is carried by its sizing, not by its
    # signal — the audit behind rule 19 (the ladder produced "13/13 green
    # months"; flat was 7/12-11/12). Profitable or not, that is not BALANCED.
    if wr < 20:
        score -= 2.0
        bits.append(f"loses {100 - wr:.1f}% of its trades — the ladder is "
                    f"carrying this, not the signal (-2.0)")
    elif wr < 35:
        score -= 1.0
        bits.append(f"loses {100 - wr:.1f}% of its trades (-1.0)")

    # the dip that empties the account: against what the row earned, AND
    # against the stake, because -79.80 over 13 trades emptied a $65 wallet
    # while the total was still green (APEX, 2026-08-19)
    if dip > 0 and pf > 0:
        hit = 2.0 if dip > pf else (1.0 if dip > pf / 2 else 0.0)
        score -= hit
        if hit:
            bits.append(f"worst dip {dip:,.2f} USDT against {pf:,.2f} earned "
                        f"(-{hit:.1f})")
    if dip > 10 * base:
        score -= 1.0
        bits.append(f"worst dip is {dip / base:.0f}x the {base:g} USDT stake "
                    f"(-1.0)")

    # EVIDENCE. A rate needs a denominator: "CHF 30m soldiers 100.00% over 1
    # trade" was the top of this store once, and 10/10 for two trades is the
    # same lie with a nicer number.
    ceiling = 10.0
    if n < 30:
        ceiling = 4.0
        bits.append(f"only {int(n)} trades — too few to rate above 4")
    elif n < 100:
        ceiling = 7.0
        bits.append(f"{int(n)} trades — under 100, so it cannot rate above 7")
    score = min(score, ceiling)

    # ONE DECIMAL, asked for by name: two rows that both "score 8" are not the
    # same row, and the operator ranks by the difference (2026-08-27).
    return round(max(1.0, min(10.0, score)), 1), "; ".join(bits)


def month_keys(months: int, anchor: str | None = None) -> list:
    """The last `months` calendar months, newest first, as the store keys them
    ("2026-08"). `anchor` is the month to count back FROM — the caller passes
    the newest month the data actually has, so a window is never anchored on a
    month nobody measured.

    Operator, 2026-08-27: *"add filter Last x month / if i entered 2 months then
    adjust the number of trades, winrate, profit for last x month"*. CLAUDE.md
    kit item G asks for exactly this, and for the months outside the window to
    be REMOVED rather than shown as em dashes.
    """
    n = max(0, int(months or 0))
    if not n:
        return []
    if anchor:
        y, m = (int(x) for x in str(anchor).split("-")[:2])
    else:
        import datetime as _dt

        now = _dt.datetime.now()
        y, m = now.year, now.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def window_figures(monthly: dict, window: list) -> dict:
    """What a row DID inside the window, from the per-month profits the sweep
    stored.

    Exact for profit and for months-green. NOT trades, wins or win rate: the
    sweep accumulates those per ROW only (`fast_grid` and `auto_trader` both
    keep `monthly[month] += pnl` and nothing else), so the window's trade count
    cannot be derived here — it has to be re-measured from the candles, which
    is what the row's own trade log does on a click. Saying so is the point:
    a win % that silently covered a different span than the profit beside it
    would be the label-must-match-data failure this repo keeps paying for.
    """
    got = {k: float(monthly.get(k) or 0.0) for k in window if k in (monthly or {})}
    return {"w_profit": round(sum(got.values()), 2),
            "w_green": sum(1 for v in got.values() if v > 0),
            "w_months": len(got)}


def clean_row_id(row_id) -> str:
    """The id as the table PRINTS it, from whatever was typed or pasted.

    Strip first, THEN the hash: `" #6yaczsxx "` had the space in front of the
    `#`, so a `lstrip("#")` before the strip left the hash on and found
    nothing — a pasted id looked like an id that is not in the store.
    """
    return str(row_id or "").strip().lstrip("#").strip().upper()


# The operator's two groups (2026-08-27): "i want to group this new backtests to
# 'Preset Confluence' / then the existing backtests before this should be all
# grouped to 'Classic'". Decided by the signal's own NAME -- every rule in
# tradingagents/signals_conf.py is called `cf_...` -- so no column is added and
# 35.8 million indexed rows do not have to be rewritten to answer the question.
GROUPS = {
    "preset": {"label": "Preset Confluence"},
    "classic": {"label": "Classic", "negate": True},
}
# The group as a RANGE on the signal name, not a LIKE.
#
# `signal LIKE 'cf\_%' ESCAPE ''` is correct and unusable: SQLite's LIKE
# optimisation is off whenever ESCAPE is given, so no index can ever serve it
# and a PARTIAL index cannot be matched to it either. '`' is the byte straight
# after '_', so [cf_, cf`) is exactly "starts with cf_" -- and a range is
# something the planner can use. The literals are INLINED, not bound: SQLite
# decides at PREPARE time whether a query implies a partial index's WHERE, and
# a parameter it cannot see yet defeats that. They are constants from this
# module, never operator input.
PRESET_LO, PRESET_HI = "cf_", "cf`"
PRESET_TERMS = "signal >= '%s' AND signal < '%s'" % (PRESET_LO, PRESET_HI)
CLASSIC_TERMS = "(signal < '%s' OR signal >= '%s')" % (PRESET_LO, PRESET_HI)
GROUP_TERMS = {"preset": PRESET_TERMS, "classic": CLASSIC_TERMS}

# ONE PARTIAL INDEX PER (GROUP, ORDER) -- and only for `preset`.
#
# Measured on the operator's store (35,893,630 rows, mechanical disk) the day
# they hit it: "Preset Confluence" ranked by profit, LIMIT 500, walking
# rows_profit and reading each candidate ROW off the disk to test its signal
# took 78.7 s. The 20 s budget refused it, the proxy gave up before that, and
# the panel printed `ApiError: /api/strategies?...&group=preset... -> HTTP 500`
# under a caption that still said "all groups".
#
# The 30 cf_ rules are a slice of the store, so a PARTIAL index over just that
# slice is small, quick to build, and already IN the order the page wants.
#
# Only `preset` gets one. `classic` is ~95% of the store: the plain profit walk
# finds 500 of them at once (measured 1.5 s with no index), so an index there
# would cost a build and buy nothing.
GROUP_SORT_COLS = {
    "profit": "profit DESC, id",
    "winrate": "winrate DESC, trades, profit DESC, id",
    "trades": "trades DESC, profit DESC, id",
    "dd": "dd ASC, profit DESC, id",
}
GROUP_INDEXES = {
    ("preset", k): ("CREATE INDEX IF NOT EXISTS rows_cf_%s ON rows (%s) "
                    "WHERE %s" % (k, cols, PRESET_TERMS))
    for k, cols in GROUP_SORT_COLS.items()
}


# _build_index() looks its DDL up here, so a partial index is built and
# reported exactly like rows_wr2 or rows_id — the same 503-and-build contract.
INDEX_DDL.update({ddl.split()[5]: ddl for ddl in GROUP_INDEXES.values()})


def group_index(group=None, sort="profit") -> str:
    """The partial index this (group, order) wants, or "" when there is none."""
    ddl = GROUP_INDEXES.get((str(group or ""), str(sort or "")))
    return ddl.split()[5] if ddl else ""


def in_group(signal: str, group: str | None) -> bool:
    """Does this signal belong to the group? No group means every signal."""
    if not group:
        return True
    if group not in GROUPS:
        raise ValueError(f"unknown group {group!r}; use one of "
                         f"{', '.join(sorted(GROUPS))}")
    is_preset = str(signal or "").startswith("cf_")
    return (not is_preset) if GROUPS[group].get("negate") else is_preset


def _where(coin=None, tf=None, signal=None, profitable=False,
           min_trades=0, min_winrate=0, max_tp=0, sizing=None, row_id=None,
           group=None, max_sl=0, *, order_owns_index=False, order_key=None,
           winrate_seeks=False, signal_seeks=False) -> tuple:
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
    # A ROW ID names ONE row, so it is not a filter among filters: it OVERRIDES
    # them (kit item H — "a find-by-ID box that overrides the other filters").
    # Anything else in the WHERE could only contradict it, and a contradiction
    # reads as "that id is not in the store" when it is.
    if row_id:
        return " WHERE id = ?", [clean_row_id(row_id)]
    # A named coin outranks tf and signal in BOTH statements: the count chose
    # `SEARCH rows USING INDEX rows_tf (tf=?)` — 2.5M rows for 1h — and hung,
    # while rows_coin answers the same question in milliseconds (~18k rows for
    # a pair). `trades` steps aside only for the row query, which has the
    # ORDER BY to serve; the count wants rows_trades.
    step_aside = "+" if (order_owns_index or coin) else ""
    # `sizing` holds one of two values (backtest_report.SIZINGS), so it can
    # never be selective enough to drive a plan and always steps aside for the
    # ORDER BY, exactly like tf and signal. The operator's ask, 2026-08-27:
    # "i want filter to see flat / martingale" — the ladder produced the
    # "13/13 green months" behind six live strategies while flat was 7/12-11/12
    # (rule 19), so seeing one without the other is the whole point.
    # `signal` used to step aside like tf and sizing. With rows_signal built
    # it is a seek instead -- one confluence rule is 0.3% of the store -- so it
    # keeps its index exactly like a named coin (see SIGNAL_INDEX).
    for col, val, keeps_index in (("coin", coin, True), ("tf", tf, False),
                                  ("signal", signal, bool(signal_seeks)),
                                  ("sizing", sizing, False)):
        if val:
            sql.append(f"{'' if keeps_index else step_aside}{col} = ?")
            args.append(val)
    # GROUP: matched on the signal name, and it steps aside for the ORDER BY
    # like tf and signal do -- half the store is one group, so it can never be
    # selective enough to drive a plan.
    if group:
        if group not in GROUPS:
            raise ValueError(f"unknown group {group!r}; use one of "
                             f"{', '.join(sorted(GROUPS))}")
        # Inlined literals, and no "+": both are what let the planner match
        # this term to the partial index (GROUP_INDEXES). There is no index on
        # `signal` itself, so the missing "+" gives nothing away.
        sql.append(GROUP_TERMS[group])
    if profitable:
        sql.append("profit > 0")
    # A COUNT, in the unit the trades column prints (CLAUDE.md rule G).
    # Ranking the operator's store by win rate returned `CHF 30m soldiers
    # 100.00% over 1 trade` at the top: a rate with no denominator is not a
    # result.
    if min_trades and int(min_trades) > 0:
        # rows_winrate is (winrate DESC, trades, id), so when the win-rate
        # range drives the plan the trade floor is the SECOND column of the
        # same index and must not step aside either.
        floor_hint = ("+" if (order_owns_index and not coin
                              and not winrate_seeks) else "")
        sql.append(f"{floor_hint}trades >= ?")
        args.append(int(min_trades))
    # The WIN-RATE floor, in the unit the "win %" column PRINTS: 50 means
    # 50.00%, not 0.5 (CLAUDE.md rule G). Operator, 2026-08-27: "add a textbox
    # winrate, if i put 50 then show me coins with winrate equal or greater
    # than 50" -- so it is >=, inclusive: a row at exactly 50.00 stays.
    #
    # Unlike every other filter here, this one is the SAME COLUMN one of the
    # orders sorts by, so which form is fast depends on the ORDER BY. Measured
    # on the operator's own store, 35,570,060 rows, mechanical disk, LIMIT 50:
    #
    #   ORDER BY winrate DESC, winrate >= 70
    #     plain   SEARCH rows USING INDEX rows_winrate (winrate>?)   0.77 s
    #     +       SCAN rows USING INDEX rows_winrate                24.93 s
    #   ORDER BY profit DESC, winrate >= 70
    #     plain   SEARCH rows USING INDEX rows_winrate (winrate>?)
    #             + USE TEMP B-TREE FOR ORDER BY        did not return in 25 s
    #     +       SCAN rows USING INDEX rows_profit                   1.01 s
    #
    # So the range drives its own index when the screen is ranked by win %,
    # and steps aside when anything else owns the ORDER BY -- letting a
    # `winrate >= ?` range drive a query that must ORDER BY profit is the
    # `USE TEMP B-TREE` over millions of rows this module already paid for
    # once with `trades`.
    # `winrate_seeks` is the third case the comment above did not have: a
    # floor selective enough that seeking rows_winrate and sorting the few
    # matches beats scanning the order's own index (see WINRATE_SEEK_MAX).
    if min_winrate and float(min_winrate) > 0:
        rate_hint = ("+" if (order_owns_index and not winrate_seeks
                             and str(order_key) != "winrate")
                     else "")
        sql.append(f"{rate_hint}winrate >= ?")
        args.append(float(min_winrate))
    # The TAKE-PROFIT floor, in the unit the TP% column PRINTS: 4 means TP 4%
    # or wider, not 0.04 (operator, 2026-08-27: "add filter 'TP' when i input 4
    # then show that has TP equal or greater than 4"). TP is what a winning
    # trade aims at, so this is "only show me strategies that go for 4% a
    # trade or more".
    #
    # No index names `tp` (INDEX_DDL is pair/profit/coin/winrate), so the term
    # cannot steal a plan the way `winrate >= ?` could -- measured identical
    # on the operator's store, 35,863,520 rows, LIMIT 500:
    #     tp >= 4 ORDER BY profit   plain 0.02 s   +tp 0.02 s
    # It still steps aside in the row query for the same reason `trades` does:
    # if a tp index is ever added, the `+` is what keeps the ORDER BY's own
    # index instead of sorting every match in a temp b-tree.
    # MAX TP, a ceiling like the SL box beside it (operator, 2026-09-03:
    # "when i input tp 3% it should show tp below 3%"). It was a floor for one
    # day, which is why the parameter is renamed rather than reused: a field
    # called max_tp that means a maximum is a lie in the API itself.
    if max_tp and float(max_tp) > 0:
        tp_hint = "+" if (order_owns_index and not coin) else ""
        sql.append(f"{tp_hint}tp <= ?")
        args.append(float(max_tp))
    # MAX SL, the other direction on purpose: the useful end of a target is up
    # and the useful end of a stop is DOWN (operator, 2026-09-02, on the
    # artifact first: "for sl if i input 1 then show below 1 or equal 1"). No
    # index names `sl` either, so it steps aside for the ORDER BY exactly like
    # `tp` — the "+" is what keeps a future sl index from stealing the plan and
    # sorting every match in a temp b-tree.
    if max_sl and float(max_sl) > 0:
        sl_hint = "+" if (order_owns_index and not coin) else ""
        sql.append(f"{sl_hint}sl <= ?")
        args.append(float(max_sl))
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
    # no index, and none promised: these sort within the LIMIT and are never
    # refused — removing a working feature to protect a plan is a bad trade
    "trades": None,
    "dd": None,
}
_BUILDING: set = set()
# rows we are willing to sort with no index behind the order
UNINDEXED_LIMIT = 200_000
# how far a FILTERED count will go before it answers "N+"
COUNT_CAP = 5_000
# how many rows a WINDOWED csv re-measures before it stops and says so
DAYS_CSV_MAX = 2_000
# Past this offset a page is fetched in TWO steps — see `_page_rows`. The
# operator's own click: page 50,000 of Stored strategies, offset 24,999,500.
#
#   SELECT * ... ORDER BY profit DESC, id LIMIT 500 OFFSET 24999500
#     SCAN rows USING INDEX rows_profit                       60.2 s
#   SELECT rowid ... same order, same offset
#     SCAN rows USING COVERING INDEX rows_profit               1.4 s
#   then SELECT * FROM rows WHERE rowid IN (those 500)         0.0 s
#
# `SELECT *` makes the index non-covering, so SQLite pulls all 25 million
# skipped rows off the disk to throw them away. `SELECT rowid` never leaves
# the index. Next's proxy gave up on the 60 s version with a 500 and the
# screen showed the previous page under the new page number.
DEEP_OFFSET = 5_000
# A win-rate floor is the one filter that shares a column with an ORDER BY, so
# which plan is fast depends on HOW SELECTIVE the floor is. Counted from
# rows_winrate on this store (35,863,520 rows, mechanical disk):
#
#     winrate >= 95    31,768 rows   0.01 s
#     winrate >= 90    69,064 rows   0.01 s
#     winrate >= 80   643,186 rows   1.06 s
#
# `min_winrate=95` ranked by PROFIT wrote `+winrate` and scanned rows_profit.
# On the operator's screen that was two HTTP 500s from the proxy's 30 s
# timeout, with the panel leaving the previous rows sitting under the new
# filter. The benchmark left running to find out what it really cost came back
# after TWO HOURS FIFTY-ONE MINUTES:
#
#     SELECT * ... WHERE +winrate >= 95 ORDER BY profit DESC LIMIT 500
#       SCAN rows USING INDEX rows_profit                       10,771.7 s
#     SELECT * ... INDEXED BY rows_winrate WHERE winrate >= 95  (same answer)
#       SEARCH (winrate>?) + USE TEMP B-TREE FOR ORDER BY            10.0 s
#
# A thousand times, on the narrow index alone. (A 52.32 s figure for the seek
# appears in the history of this file; that sample was competing with the
# rows_wr2 build for the same disk. 10.0 s is the quiet-disk number.)
#
# It is not selectivity alone: 500/0.0009 is half a million rows, which is not
# three hours. It is that `SELECT *` makes rows_profit non-covering, so every
# one of those rows is a random read off a mechanical disk.
#
# The other direction is just as real: at `winrate >= 70` most of the store
# qualifies, and sorting all of it in a temp b-tree did not return in 25 s
# while the profit scan answered in 1.01 s.
#
# So: seek when the floor is selective, scan when it is loose. The crossover is
# where the two costs meet - 500/(n/35.8M) == n, so n ~ 134,000.
WINRATE_SEEK_MAX = 150_000
# ...but that number was calibrated against the NARROW index, where the seek
# has to fetch every matching row off the disk to find its profit. rows_wr2
# carries the profit, so the seek never leaves the index and the arithmetic
# changes completely. Measured on this store (35,863,520 rows) once rows_wr2
# was built, `win % >= 50` (7,465,262 matches) ranked by profit, LIMIT 500:
#
#   +winrate, SCAN rows USING INDEX rows_profit                  479.26 s
#   INDEXED BY rows_wr2, SEARCH (winrate>?) + temp b-tree          8.70 s
#
# 55x, and the reason the scan is so bad is not selectivity — 21% of rows
# qualify, so it should meet 500 of them almost at once. It is CORRELATION:
# the most profitable rows in this store are laddered rows with low win rates,
# so reading in profit order walks a very long way before 500 rows clear a
# win-rate floor. An earlier "4.10 s" for the same query was a warm page cache
# reading what the previous identical query had just pulled in.
#
# 8.70 s for 7.5 million matches is ~1.2 s per million, so a 20 s budget
# (QUERY_BUDGET_S) covers about 15 million. 12 million keeps room for the
# 500 row fetches at the end.
WIDE_SEEK_MAX = 12_000_000
# How long ONE read may run before the store gives up and says so.
#
# The UI reaches the API through Next's rewrite, which gives up at 30 s with a
# bare HTTP 500 and no body. The panel then showed the PREVIOUS rows under the
# new filter with nothing but a red line - the operator's "i thought its not
# working" again, this time with the screen actively lying about which filter
# the numbers belong to. `min_winrate=95` did that twice.
#
# So the store stops first, at 20 s, and raises SortNotReady - which the route
# already maps to 503 and the panel already renders as "still working on it,
# these rows are the previous answer". A sentence in 20 s beats a 500 in 30.
QUERY_BUDGET_S = 20.0
# rows one request may return. 2,000 was the cap while the screen showed a
# fixed 300; the operator asked to see the whole store, so a page can now be
# 5,000 and `iter_rows` streams the rest with no ceiling at all.
MAX_LIMIT = 5_000


def _pairs_total(coin=None, tf=None) -> int:
    """Exact row count for a coin and/or timeframe filter, from the pair
    summaries — no row scan at all.

    Numbered pages need a real LAST page, and a capped count cannot give one:
    "of 10+" beside a filter that really has 4,255 pages is the same refusal
    the operator was objecting to. A COUNT over the rows table cannot be
    exact and fast at once — measured on this store, counting a `tf='1h'`
    filter stopped at 5,000 rows in 0.69 s and had not reached 100,000 in
    six minutes. But `pairs` already carries one row per coin+timeframe with
    its own `n`, so the two filters that name a pair are a sum over ~4,200
    tiny rows: exact, and instant.

    Only coin/tf. A signal, a profit floor or a trade floor cuts INSIDE a
    pair and the summaries know nothing about it — those still get the
    capped count.
    """
    sql = "SELECT COALESCE(SUM(n),0) FROM pairs"
    where, args = [], []
    for col, val in (("coin", coin), ("tf", tf)):
        if val:
            where.append(f"{col} = ?")
            args.append(val)
    if where:
        sql += " WHERE " + " AND ".join(where)

    def _read():
        with _open(readonly=True) as con:
            return int(con.execute(sql, args).fetchone()[0])
    return int(_missing_ok(_read, 0))


def _rows_estimate() -> int:
    """How many rows the store holds, from the pair summaries (no scan)."""
    def _read():
        with _open(readonly=True) as con:
            return int(con.execute(
                "SELECT COALESCE(SUM(n),0) FROM pairs").fetchone()[0])
    return int(_missing_ok(_read, 0))


def _winrate_matches(min_winrate, min_trades=0, cap=None):
    """How many rows clear a win-rate (and trade) floor - index-only.

    The win-rate index carries the trade count, so this touches nothing but
    the index: 0.01 s at `winrate >= 90` (69,064 rows) on the operator's
    35,863,520-row store.

    BOUNDED, and that is the point. The same count at `winrate >= 50` is
    7,465,262 entries and took 25.50 s -- and it ran TWICE per request (once
    to choose the plan, once for the total), which is most of the 25 s the
    operator waited for a filter that then had to scan anyway. `cap` stops the
    walk at cap+1 entries: the answer is exact below the cap, and above it the
    caller only needs to know "more than the cap" to pick the plan.

    None when the database could not be read -- never 0, which the caller
    would read as "nothing matches".
    """
    inner = (f"SELECT 1 FROM rows{_winrate_index()} WHERE winrate >= ?")
    args = [float(min_winrate)]
    if min_trades and int(min_trades) > 0:
        inner += " AND trades >= ?"
        args.append(int(min_trades))
    if cap:
        inner += f" LIMIT {int(cap) + 1}"
    sql = f"SELECT COUNT(*) FROM ({inner})"

    def _read():
        with _open(readonly=True) as con:
            return int(con.execute(sql, args).fetchone()[0])
    got = _missing_ok(_read, None)
    return None if got is None else int(got)


class SortNotReady(RuntimeError):
    """This order needs an index that is still being built."""


class QueryTooSlow(SortNotReady):
    """This read hit QUERY_BUDGET_S.

    A SortNotReady on purpose: the route already answers those with 503 and a
    sentence, and the panel already keeps its rows and prints it. The screen
    saying "still working on this, the numbers below are the previous answer"
    is the truth; a 30-second HTTP 500 with the old rows under the new filter
    is not.
    """


def _slow_why(coin, tf, signal, min_winrate, min_trades, sort,
              sizing=None, max_tp=0) -> str:
    """Why this read ran out of budget, and what makes it fast - named from the
    REQUEST, so it cannot describe a filter that was not sent."""
    what = ", ".join(str(x) for x in (coin, tf, signal) if x) or "the store"
    # The order the page opens on, with a filter that is not in rows_profit.
    # Measured 2026-08-27: `sizing = flat` ranked by profit hit the budget on
    # its own, because every one of the biggest profits is a martingale row.
    if sort == "profit" and (sizing or float(max_tp or 0) > 0) and (
            has_index("rows_pr2") is not True):
        which = sizing or f"TP >= {float(max_tp):g}"
        return (f"{which} over {what} ranked by profit needs more than "
                f"{QUERY_BUDGET_S:g}s until the wide profit index (rows_pr2) "
                f"finishes building - the biggest profits are all martingale "
                f"rows, so the profit index has to be walked a long way. Pick "
                f"a coin, or rank by win %, and it answers now")
    if float(min_winrate or 0) > 0:
        # "the wide win-rate index ... is still being built" was printed after
        # it HAD been built (operator's screenshot, 2026-08-27) — a false label
        # on a true refusal. Say it only while it is actually missing.
        building = " The wide win-rate index that makes this instant is still being built." if has_index("rows_wr2") is not True else ""
        if not (min_trades and int(min_trades) > 0):
            return (f"a win % floor of {float(min_winrate):g} over {what} "
                    f"needs more than {QUERY_BUDGET_S:g}s on this store. "
                    f"Add a min-trades floor - 100 answers in 0.2s - or rank "
                    f"by win %.{building}")
        return (f"win % >= {float(min_winrate):g} with {int(min_trades)}+ "
                f"trades over {what} ran past {QUERY_BUDGET_S:g}s. Rank by "
                f"win %, or narrow it with a coin or a timeframe.{building}")
    return (f"ranking {what} by {sort} ran past {QUERY_BUDGET_S:g}s. "
            f"Narrow it with a coin, a timeframe or a trade floor")


_INDEX_SEEN: dict = {}


def forget_indexes() -> None:
    """After a drop or a build, the cache must not answer from memory."""
    _INDEX_SEEN.clear()


def has_index(name: str):
    """True, False, or None when the database could not be read.

    None matters: this returned False while the DB was merely LOCKED, so the
    coin guard refused a filter in 0.02 s with rows_coin sitting right there
    (2026-08-26). A caller must not treat "I could not look" as "it is gone".
    """
    key = (str(DB_PATH), name)
    if key in _INDEX_SEEN:
        return _INDEX_SEEN[key]

    def _read():
        with _open(readonly=True) as con:
            return bool(con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
                (name,)).fetchone())

    got = _missing_ok(_read, None)
    if got is not None:
        _INDEX_SEEN[key] = bool(got)
    return got


# which index a FILTER column needs. Only `coin` is selective enough to be
# worth naming (a pair is ~10k rows of 31 million); tf and signal step
# aside for the ORDER BY instead (see _where).
FILTER_INDEX_FOR = {"coin": "rows_coin", "signal": "rows_signal"}


def build_filter_index(col: str) -> bool:
    """Create the index a filter column needs, in a daemon thread."""
    return _build_index(FILTER_INDEX_FOR.get(col))


def build_sort_index(sort: str) -> bool:
    """Create the index an order needs, in a daemon thread. Returns False when
    there is nothing to build or a build is already under way."""
    return _build_index(SORT_INDEX.get(sort))


# How long a build lock is believed. A build is minutes to hours (rows_pr2 was
# 4,291 s), and a child that dies leaves its lock behind — so the lock has a TTL
# rather than a liveness check, which is not portable across Windows and POSIX.
BUILD_LOCK_TTL_S = 6 * 3600


def _build_lock(name: str) -> Path:
    """One file per index, beside the database. It exists while a build is
    believed to be running, and the CHILD removes it when it finishes.

    `_BUILDING` is per PROCESS and that was not enough: the check after every
    indexed pair (a backtest, an update, the trickle) spawned one child per
    pass, and 13 of them piled up blocked on the write lock within minutes
    (2026-08-27). A file is the only thing the API, the indexer and a detached
    child all share.
    """
    return DB_PATH.parent / f".build-{name}.pid"


def build_running(name: str | None = None) -> str:
    """The index a build is running for, or "" — across ALL processes.

    With a name: that index only. Without: ANY build, because SQLite takes one
    writer and a second CREATE INDEX can only queue behind the first. Eighteen
    of them queued on 2026-08-27, each holding memory and a connection, none
    finishing. So one at a time, and the next asker comes back later.
    """
    try:
        locks = ([_build_lock(name)] if name
                 else list(DB_PATH.parent.glob(".build-*.pid")))
    except OSError:
        return ""
    for lock in locks:
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            continue
        if age <= BUILD_LOCK_TTL_S:
            return lock.name[len(".build-"):-len(".pid")]
        # older than any real build: the child died without cleaning up
        with contextlib.suppress(OSError):
            lock.unlink()
    return ""


def missing_indexes() -> list:
    """Every index in INDEX_DDL that the database does not have.

    Nothing in the write path builds these: a backtest inserts rows, and
    `ensure()` creates KEEP_INDEXES only (creating all of them there cost 13
    minutes of every API start). So the on-demand ones — rows_wr2, rows_pr2,
    rows_id, rows_cf_* — exist only because somebody asked, and a SCHEMA_VERSION
    bump wipes them with the tables. On 2026-08-27 that left the operator's
    Preset Confluence group with an empty table and no explanation.
    """
    forget_indexes()
    return [n for n in INDEX_DDL if has_index(n) is False]


def build_missing_indexes() -> list:
    """Start a DETACHED build for every missing index. Returns the names.

    Safe to call after any fill: `CREATE INDEX IF NOT EXISTS` is idempotent,
    SQLite serialises the writers, and each child is nice(10) so a build never
    outranks a click. Costly, and that is the point — the alternative is a
    feature that quietly does not work (78.7 s a page for preset, 40 s+ for an
    #id lookup) until a human notices.
    """
    started = [n for n in missing_indexes() if _build_index(n)]
    if started:
        print(f"[rows-index] building {len(started)} missing index(es): "
              f"{', '.join(started)}", flush=True)
    return started


def build_index_now(name: str) -> bool:
    """Create one named index HERE, blocking. Returns True when it exists after.

    This is what the detached child runs. `IF NOT EXISTS` makes it idempotent,
    and the long busy_timeout is deliberate: another writer (the indexer, or a
    second build) may hold the lock for many minutes and WAITING is right.
    """
    ddl = INDEX_DDL.get(name or "")
    if not ddl:
        print(f"[rows-index] no such index: {name}", flush=True)
        return False
    started = time.time()
    # the lock is taken HERE as well as by the spawner: a build started
    # directly (a script, a test, the child itself) must be visible to every
    # other process, or the next asker spawns a twin (2026-08-27)
    with contextlib.suppress(OSError):
        _build_lock(name).write_text(str(os.getpid()), encoding="utf-8")
    try:
        with _open() as con:
            con.execute("PRAGMA busy_timeout=3600000")
            con.execute(ddl)
        forget_indexes()
        print(f"[rows-index] built {name} in {time.time() - started:.0f}s",
              flush=True)
        return True
    except Exception as exc:                                      # noqa: BLE001
        print(f"[rows-index] could not build {name} after "
              f"{time.time() - started:.0f}s: {type(exc).__name__}: {exc}",
              flush=True)
        return False
    finally:
        # whatever happened, the next asker must be able to try again
        with contextlib.suppress(OSError):
            _build_lock(name).unlink()


def _build_index(name) -> bool:
    """Start building one named index in a DETACHED CHILD PROCESS, so it
    outlives whoever asked. False when there is nothing to build or this
    process already started one.

    A thread was not enough: the API restarts (every deploy), and each restart
    killed the build mid-scan while the screen kept saying "being built in the
    background" — Preset Confluence spent an afternoon like that, 2026-08-27.
    """
    if not name or name not in INDEX_DDL or name in _BUILDING:
        return False
    if has_index(name) is True:
        return False
    busy = build_running()
    if busy:
        # already building something — this one waits its turn rather than
        # queueing behind it on SQLite's single write lock
        if busy != name:
            print(f"[rows-index] {name} waits: {busy} is building", flush=True)
        return False
    # A build child must never spawn builds. It does not today, but a child that
    # fell through to the indexer loop once did: on 2026-08-27 thirteen
    # `--build` processes existed inside a few minutes, each one indexing pairs
    # and asking for the next missing index. One env marker ends that whole
    # family of accidents.
    if os.environ.get("TA_INDEX_BUILD"):
        return False
    _BUILDING.add(name)                 # only stops THIS process re-asking
    cmd = [sys.executable, "-m", "tradingagents.rows_index", "--build", name]
    child_env = dict(os.environ, TA_INDEX_BUILD=name)
    kwargs: dict = {"env": child_env,
                    "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL,
                    "stdin": subprocess.DEVNULL,
                    "cwd": str(Path(__file__).resolve().parent.parent)}
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: taskkill /T on the API
        # (start.py does exactly that) must not reach the build.
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, **kwargs)                # noqa: S603
        # the lock goes down HERE, with the child's pid in it, so a second
        # asker in another process cannot spawn a twin before the child starts
        with contextlib.suppress(OSError):
            _build_lock(name).write_text(str(proc.pid), encoding="utf-8")
        print(f"[rows-index] building {name} in pid {proc.pid} (detached)",
              flush=True)
        return True
    except Exception as exc:                                      # noqa: BLE001
        _BUILDING.discard(name)
        print(f"[rows-index] could not start a build for {name}: "
              f"{type(exc).__name__}: {exc}", flush=True)
        return False


def _winrate_seek_cap() -> int:
    """How many matches the seek is worth, which depends on WHICH index exists.

    Narrow (winrate, trades, id): the seek must read every matching row to get
    its profit, so it is only worth it while the matches are few.
    Wide (rows_wr2, + profit): the seek stays inside the index, and beats the
    profit scan by 55x at 7.5 million matches.
    """
    if has_index("rows_wr3") is True or has_index("rows_wr2") is True:
        return WIDE_SEEK_MAX
    return WINRATE_SEEK_MAX


def winrate_index_name() -> str:
    """The widest win-rate index this store HAS, or "" — for the health check
    and for the panel's "this filter needs an index" sentence."""
    for name in ("rows_wr3", "rows_wr2", "rows_winrate"):
        if has_index(name) is True:
            return name
    return ""


def _winrate_index() -> str:
    """`INDEXED BY <the win-rate index>` - the wide one when it is there.

    rows_wr2 is (winrate DESC, trades, profit DESC, id): the same seek as
    rows_winrate plus the profit needed to RANK the matches. The narrow
    rows_winrate is (winrate DESC, trades, id), so the same query has to read
    all 31,768 matching ROWS off the disk to find their profit. Measured on
    the operator's `win % >= 95` ranked by profit, LIMIT 500:

        no index named (SCAN rows_profit)      10,771.7 s
        narrow rows_winrate                        10.0 s
        wide rows_wr2                               0.25 s

    Both are accepted so an older database keeps working while the wide one
    builds (3,247 s on this store) - naming an index that does not exist is a
    hard SQLite error.
    """
    # widest first: rows_wr3 adds `sizing`, which is what turned the
    # operator's flat-only request from 3,071.7 s into 0.34 s (see WIDER_WINRATE)
    for name in ("rows_wr3", "rows_wr2", "rows_winrate"):
        if has_index(name) is True:
            return f" INDEXED BY {name}"
    return ""


def _profit_index() -> str:
    """`INDEXED BY rows_pr2` when the wide profit index is there.

    Nothing is named when it is not: rows_profit is what the planner picks for
    `ORDER BY profit` anyway, and naming an index that does not exist is a hard
    SQLite error.
    """
    return " INDEXED BY rows_pr2" if has_index("rows_pr2") is True else ""


# the filters that cut INSIDE a pair and live in rows_pr2 next to profit. A
# request carrying one of these under `ORDER BY profit` is the case the wide
# index exists for.
def _wide_profit_helps(sizing=None, max_tp=0, min_winrate=0, min_trades=0,
                       max_sl=0,
                       profitable=False) -> bool:
    return bool(sizing or float(max_tp or 0) > 0 or float(max_sl or 0) > 0
                or float(min_winrate or 0) > 0
                or int(min_trades or 0) > 0 or profitable)


def _row_id_index() -> str:
    """`INDEXED BY rows_id` when the id index is there, else nothing."""
    return " INDEXED BY rows_id" if has_index("rows_id") is True else ""


def _indexed_by(coin, winrate_seeks=False, profit_wide=False,
                row_id=None, group_idx="", signal_seeks=False) -> str:
    """`INDEXED BY rows_coin` when a coin is named and that index exists.

    Measured on the rebuilt store (31,159,970 rows, every index present):

        SELECT * FROM rows WHERE coin = 'KAVA' ORDER BY profit DESC LIMIT 500
        -> SCAN rows USING INDEX rows_profit

    The planner took the index that satisfies the ORDER BY and walked all of it
    looking for one coin in 974: the request did not return in 120 s and the
    screen showed HTTP 500. rows_coin is (coin, profit DESC), so naming it
    turns the same query into a seek that needs no sort. Naming an index that
    does not exist is a hard SQLite error, hence the has_index check.
    """
    # One row by its own code outranks everything: it is one seek.
    if row_id:
        return _row_id_index()
    if coin and has_index("rows_coin") is True:
        return " INDEXED BY rows_coin"
    # ONE named signal with its index: a seek that arrives in profit order
    if signal_seeks:
        return " INDEXED BY rows_signal"
    # A GROUP's own partial index is the filter AND the order at once (see
    # GROUP_INDEXES), so nothing else beats it when no coin is named. The
    # caller passes it only once it exists.
    if group_idx:
        return f" INDEXED BY {group_idx}"
    # No coin named and a selective win-rate floor: rows_winrate is the seek.
    # Only one index can be named, and a coin is always the better driver
    # (~10k rows for a pair), so this never competes with the line above.
    if winrate_seeks:
        return _winrate_index()
    # No coin, no win-rate seek: `ORDER BY profit` with a filter beside it is
    # the wide profit index's case (see WIDE_PROFIT).
    if profit_wide:
        return _profit_index()
    return ""


def query_sql(coin=None, tf=None, signal=None, profitable=False,
              sort="profit", min_trades=0, min_winrate=0, max_tp=0,
              sizing=None, row_id=None, desc=None) -> str:
    """The row SELECT this query would run — for tests and for EXPLAIN."""
    key = str(sort or "profit")
    if key not in SORTS:
        raise ValueError(f"unknown sort {key!r}; use one of {sorted(SORTS)}")
    down = SORTS[key] if desc is None else bool(desc)
    where, _ = _where(coin, tf, signal, profitable, min_trades, min_winrate,
                      max_tp, sizing, row_id, order_owns_index=True,
                      order_key=key)
    return (f"SELECT * FROM rows{_indexed_by(coin, row_id=row_id)}{where} "
            f"ORDER BY {key} {'DESC' if down else 'ASC'}, id ASC LIMIT ? OFFSET ?")


def explain(**kw) -> list:
    """The plan for that SELECT, as SQLite describes it."""
    sql = query_sql(**kw)
    _, args = _where(kw.get("coin"), kw.get("tf"), kw.get("signal"),
                     kw.get("profitable", False), kw.get("min_trades", 0),
                     kw.get("min_winrate", 0), kw.get("max_tp", 0),
                     kw.get("sizing"), kw.get("row_id"),
                     order_owns_index=True,
                     order_key=str(kw.get("sort") or "profit"))

    def _read():
        with _open(readonly=True) as con:
            return [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql,
                                              (*args, 1, 0))]
    return list(_missing_ok(_read, []))


def _page_rows(con, coin, row_where, row_args, order, lim, off,
               winrate_seeks=False, profit_wide=False, row_id=None,
               group_idx="", signal_seeks=False) -> list:
    """One page of rows, in `order`, skipping `off` of them.

    A shallow page is one statement. A DEEP page is two: the rowids from the
    ORDER BY's own index (covering, so the skipped rows are never read off the
    disk), then those rowids. Measured at offset 24,999,500 on the operator's
    store: 60.2 s as one statement, 1.4 s as two. See DEEP_OFFSET.
    """
    sql = (f"SELECT %s FROM rows"
           f"{_indexed_by(coin, winrate_seeks, profit_wide, row_id, group_idx, signal_seeks)}"
           f"{row_where} ORDER BY {order}, id ASC LIMIT ? OFFSET ?")
    if off <= DEEP_OFFSET:
        return con.execute(sql % "*", (*row_args, lim, off)).fetchall()
    ids = [r[0] for r in con.execute(sql % "rowid", (*row_args, lim, off))]
    if not ids:
        return []
    # rowid IS the table's own key, so this is 500 direct seeks. The ORDER BY
    # is repeated because `IN` returns them in no particular order.
    return con.execute(
        "SELECT * FROM rows WHERE rowid IN (%s) ORDER BY %s, id ASC"
        % (",".join("?" * len(ids)), order), ids).fetchall()


def query(coin=None, tf=None, signal=None, profitable=False,
          limit=500, offset=0, sort="profit", min_trades=0,
          min_winrate=0, max_tp=0, sizing=None, row_id=None, group=None,
          max_sl=0, months=0, desc=None) -> dict:
    """Rows sorted by `sort` (SORTS), profit first by default.

    STRICTLY READ-ONLY. It creates nothing and it indexes nothing.

    An earlier version filled an empty index from here, bounded to a few
    seconds. That put a WRITER on a route the grid polls every 4 seconds: the
    polls fought the indexer for SQLite's single write lock, the loop logged
    `database is locked`, and one pair that takes 0.7s alone took 29.2s. The
    index catches up on its own timer (`start_keeping_up`), and `status()`
    reports how far behind it is so the screen can say so.
    """
    lim = max(0, min(int(limit), MAX_LIMIT))
    key = str(sort or "profit")
    if key not in SORTS:
        raise ValueError(
            f"unknown sort {key!r}; use one of {sorted(SORTS)}")
    # How many rows the win-rate floor lets through decides the plan, and the
    # answer is index-only (0.01 s at >= 90). Only without a coin, which is
    # always the better driver.
    # Which index drives when a win % floor is set. rows_wr2 SEEKS the floor
    # but is in win-rate order, so ranking by profit means sorting every match
    # — and it carries no `sizing`, so each match is read off the disk to test
    # it. rows_pr2 is already IN profit order and holds winrate, sizing, tp and
    # trades, so the same request is one index-only walk with no sort.
    # Measured 2026-08-27 on the operator's store, `win % >= 80 AND sizing =
    # flat AND profit > 0` ranked by profit: the win-rate seek ran past the 20 s
    # budget (which is what the operator saw as "nothing is showing"), the wide
    # profit index answers it. So: ranked by profit, rows_pr2 wins when it is
    # there; ranked by win %, the seek is right.
    # ONE SIGNAL: its own index makes the filter a seek. Without it the walk
    # is the 30-second HTTP 500 the operator saw on cf_bosfvg (SIGNAL_INDEX),
    # so refuse fast, say why, and build it behind the answer.
    signal_seeks = False
    if signal and not coin and not row_id:
        if has_index("rows_signal") is True:
            signal_seeks = True
        elif _rows_estimate() > UNINDEXED_LIMIT:
            build_filter_index("signal")
            raise SortNotReady(
                f"filtering by one signal ({signal}) needs its index "
                f"(rows_signal) on a store this size; it is being built in "
                f"the background — try again shortly, or name a coin, which "
                f"is answered now")
    wide_profit_ready = (key == "profit" and not coin
                         and has_index("rows_pr2") is True)
    winrate_seeks = False
    if (float(min_winrate or 0) > 0 and not coin and not wide_profit_ready
            and _winrate_index()):
        cap = _winrate_seek_cap()
        n = _winrate_matches(min_winrate, min_trades, cap=cap)
        winrate_seeks = n is not None and n <= cap
    # `ORDER BY profit` with a filter beside it: the wide profit index makes
    # that walk index-only (see WIDE_PROFIT). When it is missing, start it —
    # the request itself still runs, and the 20 s budget is what answers 503.
    # One row by its code: nothing else is asked, and it needs its own index
    # or it is a 40-second scan (see ROW_ID_INDEX). Refuse fast, say why, build
    # it behind the answer — the same contract as a missing sort index.
    if row_id:
        if has_index("rows_id") is not True and _rows_estimate() > UNINDEXED_LIMIT:
            _build_index("rows_id")
            raise SortNotReady(
                f"finding row #{clean_row_id(row_id)} needs the id "
                f"index (rows_id); it is being built in the background — try "
                f"again shortly")
    profit_wide = False
    if not row_id and key == "profit" and not coin and _wide_profit_helps(
            sizing, max_tp, min_winrate, min_trades, profitable):
        if wide_profit_ready:
            profit_wide = True
        elif _rows_estimate() > UNINDEXED_LIMIT:
            _build_index("rows_pr2")
    where, args = _where(coin, tf, signal, profitable, min_trades, min_winrate,
                         max_tp, sizing, row_id, group, max_sl,
                         signal_seeks=signal_seeks)
    # the row select streams its own ORDER BY index; the count rides the
    # trades index instead (see _where). The ORDER matters to the WHERE too:
    # a win-rate floor drives rows_winrate when the screen is ranked by win %
    # and steps aside otherwise.
    row_where, row_args = _where(coin, tf, signal, profitable, min_trades,
                                 min_winrate, max_tp, sizing, row_id, group,
                                 max_sl, order_owns_index=True, order_key=key,
                                 winrate_seeks=winrate_seeks,
                                 signal_seeks=signal_seeks)
    down = SORTS[key] if desc is None else bool(desc)
    order = f"{key} {'DESC' if down else 'ASC'}"
    # a coin filter without its index is the same trap as a sort without
    # one: refuse fast, say why, build it behind the answer
    if (coin and _rows_estimate() > UNINDEXED_LIMIT
            and has_index("rows_coin") is False):
        build_filter_index("coin")
        raise SortNotReady(
            "filtering by coin needs its index (rows_coin); it is being "
            "built in the background — try again shortly")
    # A GROUP ranked without its own index reads every candidate ROW off the
    # disk to test the signal: 78.7 s for the operator's 500 preset rows, which
    # the 20 s budget kills and the proxy turned into a bare HTTP 500. So:
    # refuse fast, SAY it, and build the partial index behind the answer — the
    # same contract as a missing sort index. Only `preset` has one (classic is
    # ~95% of the store and needs none), and a named coin is a better driver.
    group_idx = "" if (coin or signal_seeks) else group_index(group, key)
    if group_idx and has_index(group_idx) is not True:
        if _rows_estimate() > UNINDEXED_LIMIT:
            _build_index(group_idx)
            raise SortNotReady(
                f"{GROUPS[group]['label']} ranked by {key} needs its own index "
                f"({group_idx}) — without it the store reads millions of rows "
                f"off the disk to find 500 (measured 78.7 s). It is being built "
                f"in the background; try again shortly, or name a coin, which "
                f"is answered now")
        group_idx = ""          # small store: sorting it costs nothing
    need = SORT_INDEX.get(key)
    # A missing index only matters at size. Sorting 4,000 rows without one is
    # instant; sorting 21,582,584 had not finished in ten minutes (measured
    # 2026-08-26) and became an HTTP 500 under a caption that already said
    # "top 300 by win %". So: small store, sort freely; big store, the order
    # must have its index and is refused with the reason until it does.
    if (need and _rows_estimate() > UNINDEXED_LIMIT
            and has_index(need) is False):
        build_sort_index(key)
        raise SortNotReady(
            f"ranking by {key} needs its index ({need}); it is being "
            f"built in the background — try again shortly")

    # coin and/or tf ALONE are answered by the pair summaries: exact, no scan
    # (see _pairs_total). Anything that cuts inside a pair is not.
    # `group` belongs in this list: it cuts INSIDE a pair (half the signals in
    # every pair file), so the pair summaries cannot answer it. Without it the
    # count came from _pairs_total and both groups reported the whole store --
    # 35,893,630 rows beside a table showing one group (2026-08-27).
    from_pairs = not (signal or profitable or min_trades or min_winrate
                      or max_tp or sizing or row_id or group or max_sl)
    # A win-rate floor (with or without a trade floor) is an index-only range
    # on rows_winrate, so its total is EXACT and costs nothing - no "+".
    # The total is EXACT only when the bounded count came back under its cap:
    # above it, walking 7.5 million index entries for a number nobody waits
    # for is exactly the 25 s this request used to spend twice.
    from_winrate = bool(float(min_winrate or 0) > 0 and not coin and not tf
                        and not signal and not profitable and not max_tp
                        and not sizing and not row_id and not group
                        and not max_sl
                        and _winrate_index())

    def _read():
        with _open(readonly=True) as con:
            _budgeted(con)
            if where and from_winrate:
                cap = _winrate_seek_cap()
                got_total = _winrate_matches(min_winrate, min_trades, cap=cap)
                if got_total is None or got_total > cap:
                    total = -1          # over the cap: bound it, print the +
                else:
                    total = got_total
            elif where and group and not coin and not group_idx:
                # A GROUP has no index to seek: `signal` is not indexed, so
                # even the bounded count is a table scan -- measured 26.2 s for
                # 5,001 preset rows on this 35.9M-row store, which the 20 s
                # budget kills, and the whole request then fails. -1 is the
                # module's existing "bounded, over its cap" answer and prints
                # with the "+", so the caption says "5,000+ match" instead of
                # either lying or timing out. With a COIN the count rides
                # rows_coin and is cheap, so that case still counts for
                # real — and so does the partial index once it is built: the
                # bounded count then rides it and never touches the table.
                total = -1
            elif where and from_pairs:
                total = _pairs_total(coin, tf)
                # EXACT, so zero means zero: skip the row query. Without this
                # a timeframe with no measured rows (1d, whose row files were
                # all `[]` until the trade floor was fixed) made SQLite walk
                # the whole 35,863,520-row profit index looking for a first
                # match that does not exist — measured past five minutes,
                # while the honest answer is an empty page in 0.08 s.
                if total == 0:
                    return 0, []
            elif where:
                # COUNT(*) with a filter is a full scan of tens of millions
                # of rows (30 s on the operator's store, and the proxy gave
                # up at 30). Stop at COUNT_CAP and let the caller print the
                # "+" — an exact number nobody can wait for is worth less
                # than an honest bound.
                total = con.execute(
                    f"SELECT COUNT(*) FROM (SELECT 1 FROM rows"
                    f"{_indexed_by(coin, group_idx=group_idx, signal_seeks=signal_seeks)}"
                    f"{where} "
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
            got = _page_rows(con, coin, row_where, row_args, order, lim,
                             max(0, int(offset)), winrate_seeks, profit_wide,
                             row_id, group_idx, signal_seeks)
        return total, got

    try:
        total, got = _missing_ok(_read, (0, []))
    except sqlite3.OperationalError as exc:
        # "interrupted" is the budget, not a broken database (see _budgeted)
        if "interrupt" not in str(exc).lower():
            raise
        raise QueryTooSlow(_slow_why(coin, tf, signal, min_winrate,
                                     min_trades, key, sizing,
                                     max_tp)) from exc
    if total < 0:
        # -1 is "the bounded count went over its cap" (or could not be read):
        # a BOUND, and it must print with the "+". Without this it printed
        # "5,000 match · no +" for a `win % >= 50` filter that really has
        # 7,465,262 rows -- a true number under a false label, which is the
        # exact shape of the 2026-08-14 UI failures (label-must-match-data).
        total, capped_count = COUNT_CAP, True
    else:
        exact = from_pairs or from_winrate
        capped_count = bool(where) and not exact and total > COUNT_CAP
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
    # LAST N MONTHS. Anchored on the newest month the ROWS themselves carry,
    # never on today: a store whose last sweep ended in July must not report an
    # empty August as "the last month" (kit item G — print the window's REAL
    # dates). Profit and months-green are exact; trades and win % are not in
    # the store per month (see window_figures).
    newest = max((m for r in out for m in (r.get("monthly") or {})),
                 default=None)
    window = month_keys(months, newest)
    if window:
        for r in out:
            r.update(window_figures(r.get("monthly") or {}, window))
    # BALANCED, 1-10 over win rate AND profit. With a window it is rated on the
    # window's own figures — the operator asked for exactly that: *"when i apply
    # the months dropdown this column should adjust as well"*. Trades and win
    # rate inside a window are only known where the row's log was rebuilt (see
    # the API's restate_window), so the panel dims the score there, the same as
    # it dims those columns.
    for r in out:
        if window:
            r["balanced"], r["balanced_why"] = balanced_score(
                r, profit=r.get("w_profit"), green=r.get("w_green"),
                months=r.get("w_months"))
        else:
            r["balanced"], r["balanced_why"] = balanced_score(r)
    # the caller captions the table with this, so it is never a literal
    return {"rows": out, "total": total, "sort": key, "desc": down,
            # the caption prints "5,000+ match" when the count was capped,
            # never a bare 5,000 that reads as exact
            "total_capped": capped_count,
            "min_trades": int(min_trades or 0),
            # the caption prints the floors it actually asked for, never a
            # literal it hopes matches (label-must-match-data)
            "min_winrate": float(min_winrate or 0),
            "max_tp": float(max_tp or 0),
            "max_sl": float(max_sl or 0),
            "sizing": sizing or "",
            # what was LOOKED UP, cleaned exactly as the query cleaned it, so
            # the panel can say "#6YACZSXX is not in the store" and mean it
            "row_id": clean_row_id(row_id),
            # the window's REAL months, newest first, so the screen prints the
            # dates it has data for rather than the ones it asked for
            "window": window,
            "months_window": int(months or 0)}


def iter_rows(coin=None, tf=None, signal=None, profitable=False,
              sort="profit", min_trades=0, min_winrate=0, max_tp=0,
              sizing=None, row_id=None, group=None, max_sl=0, days=0,
              desc=None, batch=5_000):
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
    # a coin filter without its index is the same trap as a sort without
    # one: refuse fast, say why, build it behind the answer
    if (coin and _rows_estimate() > UNINDEXED_LIMIT
            and has_index("rows_coin") is False):
        build_filter_index("coin")
        raise SortNotReady(
            "filtering by coin needs its index (rows_coin); it is being "
            "built in the background — try again shortly")
    # the same partial index the page needs, and the same refusal: an export
    # that scans 35 million rows to write its first line is a download that
    # never starts (see GROUP_INDEXES)
    # ONE SIGNAL: its own index makes the filter a seek. Without it the walk
    # is the 30-second HTTP 500 the operator saw on cf_bosfvg (SIGNAL_INDEX),
    # so refuse fast, say why, and build it behind the answer.
    signal_seeks = False
    if signal and not coin and not row_id:
        if has_index("rows_signal") is True:
            signal_seeks = True
        elif _rows_estimate() > UNINDEXED_LIMIT:
            build_filter_index("signal")
            raise SortNotReady(
                f"filtering by one signal ({signal}) needs its index "
                f"(rows_signal) on a store this size; it is being built in "
                f"the background — try again shortly, or name a coin, which "
                f"is answered now")
    group_idx = "" if (coin or signal_seeks) else group_index(group, key)
    if group_idx and has_index(group_idx) is not True:
        if _rows_estimate() > UNINDEXED_LIMIT:
            _build_index(group_idx)
            raise SortNotReady(
                f"{GROUPS[group]['label']} ranked by {key} needs its own index "
                f"({group_idx}); it is being built in the background — try "
                f"again shortly")
        group_idx = ""
    need = SORT_INDEX.get(key)
    if (need and _rows_estimate() > UNINDEXED_LIMIT
            and has_index(need) is False):
        build_sort_index(key)
        raise SortNotReady(
            f"ranking by {key} needs its index ({need}); it is being built in "
            f"the background — try again shortly")
    down = SORTS[key] if desc is None else bool(desc)
    order = f"{key} {'DESC' if down else 'ASC'}"
    # the same selectivity switch the page uses (see query): a floor that
    # only 31,768 of 35,863,520 rows clear must SEEK rows_winrate, or the
    # export scans half a million rows to write its first line
    seeks = False
    if float(min_winrate or 0) > 0 and not coin and _winrate_index():
        cap = _winrate_seek_cap()
        n = _winrate_matches(min_winrate, min_trades, cap=cap)
        seeks = n is not None and n <= cap
    where, args = _where(coin, tf, signal, profitable, min_trades,
                         min_winrate, max_tp, sizing, row_id, group, max_sl,
                         order_owns_index=True, order_key=key,
                         winrate_seeks=seeks, signal_seeks=signal_seeks)
    # LAST N DAYS. The export RE-MEASURES what it exports, batch by batch, so
    # the file holds the same window the table showed. Without this the route
    # simply ignored the parameter (FastAPI drops an unknown one) and the
    # download quietly held every row's WHOLE history under a filter that said
    # "last 30 days" — the label-does-not-match-the-data failure this repo
    # keeps paying for (operator, 2026-09-03).
    win_days = max(0, int(days or 0))
    step = min(250, max(100, int(batch))) if win_days else max(100, int(batch))
    # A WINDOWED export re-measures every row it writes: ~0.09 s a row on this
    # store, so all 58,212 matches of one real filter would be 87 minutes. The
    # cap is stated in the file's last line and in its name (see
    # api.strategies_csv_lines / strategies_csv_name).
    win_left = DAYS_CSV_MAX if win_days else -1
    # same_thread=False: this generator is drained by Starlette's threadpool
    # (see _connect). Nothing else touches this connection.
    with _open(readonly=True, same_thread=False) as con:
        cur = con.execute(
            f"SELECT * FROM rows"
            f"{_indexed_by(coin, seeks, (not row_id and key == 'profit' and not coin and _wide_profit_helps(sizing, max_tp, min_winrate, min_trades, profitable)), row_id, group_idx, signal_seeks)}"
            f"{where} "
            f"ORDER BY {order}, id ASC", args)
        while True:
            got = cur.fetchmany(step)
            if not got:
                return
            batch_rows = []
            for r in got:
                d = {k: r[k] for k in r.keys() if k != "pair"}   # noqa: SIM118
                d["stop_reachable"] = bool(d.get("stop_reachable"))
                try:
                    d["monthly"] = json.loads(d.get("monthly") or "{}")
                except ValueError:
                    d["monthly"] = {}
                batch_rows.append(d)
            if win_days:
                from tradingagents import market_sweep as _msw

                if win_left <= 0:
                    return
                batch_rows = batch_rows[:win_left]
                win_left -= len(batch_rows)
                # one batch at a time, and the signal cache makes the second
                # row of a pair free. group_max is the batch itself: a batch
                # can never span more pairs than it has rows, so this never
                # raises mid-stream — a stream that raises is a truncated file
                # that looks complete.
                _msw.window_rows(batch_rows, win_days,
                                 group_max=len(batch_rows) + 1)
                for d in batch_rows:
                    if not d.get("restated"):
                        continue
                    # the WINDOW's figures in the row's own columns, so the
                    # file says what the table said, plus the window itself
                    d["trades"] = d["w_trades"]
                    d["wins"] = d["w_wins"]
                    d["losses"] = d["w_losses"]
                    d["winrate"] = d["w_winrate"]
                    d["profit"] = d["w_profit"]
                    d["dd"] = d.get("w_dd", d.get("dd"))
                    d["worst"] = d.get("w_worst", d.get("worst"))
                    d["funding"] = d.get("w_funding", d.get("funding"))
                    d["window_first"] = d.get("w_first")
                    d["window_last"] = d.get("w_last")
                    d["window_days"] = d.get("w_days")
            yield from batch_rows


def take_profits(tfs) -> list:
    """Every TP% the grid can have produced for these timeframes.

    From `backtest_report.BARRIERS` — the grid that MEASURED the rows — so the
    TP box offers values that exist instead of round numbers that do not.
    It matters: `tp` has no index, so proving that nothing matches costs a scan
    of every row. Measured on the operator's store (35,863,520 rows, a sweep
    running), LIMIT 500 in the default profit order:

        tp >= 4   0.02 s      tp >= 8    0.03 s
        tp >= 6   0.02 s      tp >= 10   did not return in 25 s

    TP 10 and above lives only in the 1d grid and this store holds no 1d rows,
    so the answer was "nothing" and it took a full scan to say so. The panel
    caps its box at the largest value here, which for 15m/30m/1h/4h is 8.
    """
    from tradingagents import backtest_report as br

    out = set()
    for tf in tfs or ():
        for _sl, tp in br.BARRIERS.get(str(tf), ()):
            out.add(round(float(tp) * 100, 6))
    return sorted(out)


def _sizings() -> tuple:
    """The sizings the grid measures (backtest_report.SIZINGS)."""
    from tradingagents import backtest_report as br

    return tuple(br.SIZINGS)


def stop_losses(tfs) -> list:
    """Every SL% the grid can have produced for these timeframes.

    The mirror of `take_profits`, for the MAX SL box (operator, 2026-09-02:
    "can you add the sl filter in the Stored strategies as well" — a ceiling,
    "if i input 1 then show below 1 or equal 1"). Same reason it is derived
    rather than typed: `sl` has no index either, so offering a value the grid
    never measured buys a full scan to answer "nothing".
    """
    from tradingagents import backtest_report as br

    out = set()
    for tf in tfs or ():
        for sl, _tp in br.BARRIERS.get(str(tf), ()):
            out.add(round(sl * 100, 3) if sl < 1 else round(float(sl), 3))
    return sorted(out)


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
        # the TP list is derived from the timeframes THIS store holds, never a
        # fixed ladder: with no 1d pairs there is no TP above 8% to ask for
        return {"coins": sorted(coins), "tfs": sorted(tfs),
                "signals": sorted(signals), "tps": take_profits(tfs),
                "sls": stop_losses(tfs),
                # the two sizings come from the GRID that measured the rows,
                # never a pair of literals in the browser
                "sizings": list(_sizings())}

    return _missing_ok(_read, {"coins": [], "tfs": [], "signals": [],
                               "tps": [], "sls": [],
                               "sizings": list(_sizings())})


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


def main(argv: list | None = None) -> int:
    """The indexer process — or, with `--build <name>`, one index and out.

    `--build` is what a detached child runs (see _build_index): it must not
    start the keep-up loop, or every refused query would leave another indexer
    running beside the real one.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--build":
        if len(args) < 2:
            print("usage: -m tradingagents.rows_index --build <index>",
                  flush=True)
            return 2
        with contextlib.suppress(OSError, AttributeError):
            os.nice(10)          # a build must never outrank a click
        return 0 if build_index_now(args[1]) else 1

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
