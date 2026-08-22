"""Permanent market database on Neon Postgres.

The disk kline cache is a cache — capped, deletable, one machine. This is
the archive: every closed candle ever downloaded, plus every backtest row
ever computed, keyed so a result is only reused while its inputs stand.

The URL comes from ``TRADINGAGENTS_DB_URL`` in the environment, else
``~/.tradingagents/neon_db.json`` (same pattern as the MEXC credentials:
outside the repo, one place to rotate). Everything here is best-effort by
design — a dead database must never stop a fetch, a backtest or the runner,
so callers get a working answer from the venue either way.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DB_URL_ENV = "TRADINGAGENTS_DB_URL"
STORE_PATH = Path(os.path.expanduser("~/.tradingagents")) / "neon_db.json"

# UI label -> MEXC interval, the five timeframes the grid searches.
# candles were stored under MEXC's names (Min60) and results under the short
# label (1h), so the two tables could not be joined at all. One vocabulary —
# the short label — and a normaliser every writer goes through.
_TF_CANON = {"Min1": "1m", "Min5": "5m", "Min15": "15m", "Min30": "30m",
             "Min60": "1h", "Hour4": "4h", "Hour8": "8h", "Day1": "1d",
             "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h",
             "4h": "4h", "8h": "8h", "1d": "1d"}


def tf_label(tf: str) -> str:
    """MEXC interval or short label in, short label out."""
    return _TF_CANON.get(str(tf), str(tf))


TIMEFRAMES = {"15m": "Min15", "30m": "Min30", "1h": "Min60",
              "4h": "Hour4", "1d": "Day1"}
BAR_SECONDS = {"Min1": 60, "Min5": 300, "Min15": 900, "Min30": 1800,
               "Min60": 3600, "Hour4": 14400, "Day1": 86400}

# One fetch this deep pulls everything MEXC serves for a pair/timeframe
# (measured ceilings: 1m 30 days, 15m ~360 days, 1h 400+ days).
DOWNLOAD_BARS = 40_000

_INSERT_CHUNK = 2_000        # rows per INSERT statement (params cap safety)


def _multi_insert(cx, sql_head: str, sql_tail: str, fields: tuple,
                  rows: list[dict]) -> None:
    """One INSERT statement per chunk, many VALUES tuples per statement.

    Passing a row list to execute() runs psycopg2's executemany — one network
    round trip PER ROW, measured >4 minutes for a single 15m history against
    a remote database. Composing the VALUES inline makes it one round trip
    per chunk (~18 for a full year of 15m bars).
    """
    from sqlalchemy import text
    for i in range(0, len(rows), _INSERT_CHUNK):
        chunk = rows[i:i + _INSERT_CHUNK]
        values, params = [], {}
        for j, r in enumerate(chunk):
            values.append("(" + ", ".join(f":{f}{j}" for f in fields) + ")")
            for f in fields:
                params[f"{f}{j}"] = r[f]
        cx.execute(text(sql_head + ", ".join(values) + sql_tail), params)


def db_url() -> str | None:
    url = os.getenv(DB_URL_ENV, "").strip()
    if url:
        return url
    try:
        return (json.loads(STORE_PATH.read_text()).get("url") or "").strip() \
            or None
    except Exception:
        return None


def available() -> bool:
    return db_url() is not None


_ENGINE = None
_ENGINE_URL = None
# After a connection failure the store stands down for a while instead of
# adding a timeout to every kline fetch in a sweep.
_down_until = 0.0


def _engine():
    global _ENGINE, _ENGINE_URL
    url = db_url()
    if url is None:
        return None
    if _ENGINE is None or url != _ENGINE_URL:
        from sqlalchemy import create_engine
        # A hanging connection must never hang a caller: without a connect
        # timeout, one dropped Neon socket froze the whole Backtest page
        # mid-render (2026-08-20). SQLite (tests) takes no such argument.
        kw = {}
        if url.startswith(("postgresql://", "postgres://")):
            # Neon's pooler rejects startup options like statement_timeout —
            # only the connect timeout goes in the startup packet.
            kw["connect_args"] = {"connect_timeout": 10}
        _ENGINE = create_engine(url, pool_pre_ping=True, pool_size=2,
                                max_overflow=2, **kw)
        _ENGINE_URL = url
        # A new engine means a different database, or a reconnect to one that
        # may have been reset. Whatever ensure_schema() proved before does not
        # apply to it.
        global _SCHEMA_DONE_URL
        _SCHEMA_DONE_URL = None
    return _ENGINE


def _ready() -> bool:
    return time.time() >= _down_until and db_url() is not None


def is_down() -> bool:
    """True while the store is standing down after a connection failure.
    Callers use it to say "unreachable" instead of the false "empty"."""
    return time.time() < _down_until


def _stand_down(exc: Exception, what: str) -> None:
    global _down_until
    _down_until = time.time() + 120
    logger.warning("market db unavailable during %s (%s) — carrying on "
                   "without it for 2 minutes.", what, exc)


DDL = [
    """CREATE TABLE IF NOT EXISTS candles (
        symbol text NOT NULL, timeframe text NOT NULL, ts bigint NOT NULL,
        open double precision NOT NULL, high double precision NOT NULL,
        low double precision NOT NULL, close double precision NOT NULL,
        volume double precision NOT NULL DEFAULT 0,
        PRIMARY KEY (symbol, timeframe, ts))""",
    """CREATE TABLE IF NOT EXISTS backtest_results (
        row_code text NOT NULL, symbol text NOT NULL, timeframe text NOT NULL,
        signal text NOT NULL, tp double precision NOT NULL,
        sl double precision NOT NULL, sizing text NOT NULL,
        data_start bigint NOT NULL, data_end bigint NOT NULL,
        code_version text NOT NULL DEFAULT '',
        profit double precision, trades integer, wins integer,
        losses integer, win_rate double precision,
        worst_streak double precision, worst_streak_len integer,
        months_json text, detail_json text, computed_at bigint,
        threshold double precision, months_green integer,
        months_total integer, days integer, max_dd double precision,
        funding double precision,
        PRIMARY KEY (row_code, data_end, code_version))""",
    """CREATE INDEX IF NOT EXISTS idx_results_lookup
        ON backtest_results (symbol, timeframe, signal)""",
    # What was live, when. Config files overwrite, so without this nobody can
    # answer "what was running on APEX on 12 August, at what barriers" — the
    # question behind every "did that change help?"
    # Keyed on a hash of the CHANGE, not on the second it happened: two edits
    # to one strategy inside the same second are two pieces of history, and a
    # timestamp key threw the second away. Identical re-saves still collapse.
    """CREATE TABLE IF NOT EXISTS deployments (
        change_id text PRIMARY KEY,
        changed_at bigint NOT NULL, strategy_key text NOT NULL,
        symbol text NOT NULL, action text NOT NULL,
        timeframe text, signal text, threshold double precision,
        tp double precision, sl double precision, sizing text,
        books text, base_margin double precision, ladder_step integer,
        row_code text, prev_json text, note text)""",
    """CREATE INDEX IF NOT EXISTS idx_deploy_lookup
        ON deployments (symbol, changed_at)""",
    # The live record of what the money actually did. One local file today; if
    # that disk goes, so does every entry, exit and rejection ever made.
    """CREATE TABLE IF NOT EXISTS trade_ledger (
        fingerprint text PRIMARY KEY, ts bigint NOT NULL, action text NOT NULL,
        symbol text, strategy text, side text, dry_run boolean,
        entry double precision, exit_price double precision,
        vol double precision, margin double precision, leverage integer,
        step integer, pnl double precision, why text, raw_json text)""",
    """CREATE INDEX IF NOT EXISTS idx_ledger_lookup
        ON trade_ledger (symbol, ts)""",
]


# Columns added after the table shipped. Run one at a time and let each
# failure pass: `ADD COLUMN IF NOT EXISTS` is Postgres-only, and on SQLite
# — which the tests use — the whole schema step died on it.
MIGRATIONS = [
    "ALTER TABLE backtest_results ADD COLUMN threshold double precision",
    "ALTER TABLE backtest_results ADD COLUMN months_green integer",
    "ALTER TABLE backtest_results ADD COLUMN months_total integer",
    "ALTER TABLE backtest_results ADD COLUMN days integer",
    "ALTER TABLE backtest_results ADD COLUMN max_dd double precision",
    "ALTER TABLE backtest_results ADD COLUMN funding double precision",
]


# The twenty DDL/migration statements are idempotent, so running them twice
# against the same database buys nothing and costs a full round trip each.
# Measured against Neon on 2026-08-20: 12,490 ms for one call.
#
# Keyed to the DATABASE URL, never a bare bool: a plain flag said "schema is
# done" about whichever database happened to be first, so pointing at a second
# one skipped its DDL entirely and every query failed with "no such table".
# _engine() also clears this whenever it builds a new engine, which is what a
# reconnect or a swapped DSN looks like from here.
_SCHEMA_DONE_URL: str | None = None


def ensure_schema(*, force: bool = False) -> bool:
    global _SCHEMA_DONE_URL
    url = db_url()
    if url is not None and url == _SCHEMA_DONE_URL and not force:
        return True
    if not _ready():
        return False
    from sqlalchemy import text
    try:
        with _engine().begin() as cx:
            for stmt in DDL:
                cx.execute(text(stmt))
        for stmt in MIGRATIONS:
            try:
                with _engine().begin() as cx:
                    cx.execute(text(stmt))
            except Exception:
                pass          # already there, or the dialect refuses it
        _SCHEMA_DONE_URL = url
        return True
    except Exception as exc:
        _stand_down(exc, "ensure_schema")
        return False


# ------------------------------------------------------------------ candles
def upsert_candles(symbol: str, interval: str, df) -> int:
    interval = tf_label(interval)
    """Store closed candles; re-sent bars overwrite (a bar refetched after
    its close corrects one saved while still forming). Returns rows sent."""
    if df is None or not len(df) or not _ready():
        return 0
    rows = [{"s": symbol, "f": interval,
             "ts": int(d.timestamp()), "o": float(o), "h": float(h),
             "l": float(lo), "c": float(c), "v": float(v)}   # "l" is the COLUMN
            for d, o, h, lo, c, v in zip(df["Date"], df["Open"], df["High"],
                                        df["Low"], df["Close"], df["Volume"], strict=False)]
    try:
        with _engine().begin() as cx:
            _multi_insert(
                cx,
                "INSERT INTO candles (symbol, timeframe, ts, open, high,"
                " low, close, volume) VALUES ",
                " ON CONFLICT (symbol, timeframe, ts) DO UPDATE SET"
                " open=excluded.open, high=excluded.high, low=excluded.low,"
                " close=excluded.close, volume=excluded.volume",
                ("s", "f", "ts", "o", "h", "l", "c", "v"), rows)
        return len(rows)
    except Exception as exc:
        _stand_down(exc, f"upsert {symbol} {interval}")
        return 0


def last_ts(symbol: str, interval: str) -> int | None:
    interval = tf_label(interval)
    if not _ready():
        return None
    from sqlalchemy import text
    try:
        with _engine().connect() as cx:
            val = cx.execute(text(
                "SELECT max(ts) FROM candles WHERE symbol=:s AND timeframe=:f"
            ), {"s": symbol, "f": interval}).scalar()
        return int(val) if val is not None else None
    except Exception as exc:
        _stand_down(exc, f"last_ts {symbol} {interval}")
        return None


def candles_df(symbol: str, interval: str,
               start: int | None = None, end: int | None = None):
    """Stored candles as the same DataFrame shape ``fx.klines`` returns,
    or None when the store is empty/unreachable."""
    interval = tf_label(interval)
    if not _ready():
        return None
    import pandas as pd
    from sqlalchemy import text
    sql = ("SELECT ts, open, high, low, close, volume FROM candles"
           " WHERE symbol=:s AND timeframe=:f")
    params = {"s": symbol, "f": interval}
    if start is not None:
        sql += " AND ts >= :a"
        params["a"] = int(start)
    if end is not None:
        sql += " AND ts <= :b"
        params["b"] = int(end)
    sql += " ORDER BY ts"
    try:
        with _engine().connect() as cx:
            rows = cx.execute(text(sql), params).fetchall()
    except Exception as exc:
        _stand_down(exc, f"candles {symbol} {interval}")
        return None
    if not rows:
        return None
    return pd.DataFrame({
        "Date": pd.to_datetime([r[0] for r in rows], unit="s", utc=True)
                  .tz_localize(None),
        "Open": [r[1] for r in rows], "High": [r[2] for r in rows],
        "Low": [r[3] for r in rows], "Close": [r[4] for r in rows],
        "Volume": [r[5] for r in rows],
    })


def coverage() -> list[dict]:
    """What the archive holds: one row per (symbol, timeframe)."""
    if not _ready():
        return []
    from sqlalchemy import text
    try:
        with _engine().connect() as cx:
            rows = cx.execute(text(
                "SELECT symbol, timeframe, count(*), min(ts), max(ts)"
                " FROM candles GROUP BY symbol, timeframe"
                " ORDER BY symbol, timeframe")).fetchall()
    except Exception as exc:
        _stand_down(exc, "coverage")
        return []
    return [{"symbol": r[0], "timeframe": r[1], "bars": int(r[2]),
             "first_ts": int(r[3]), "last_ts": int(r[4])} for r in rows]


def download(symbols: list[str], intervals: list[str],
             progress=None, *, fx=None) -> dict:
    """Fetch everything the venue serves for each pair x timeframe and store
    it. Also THE update: the kline fetch only pages the missing tail, so a
    second run moves only the new bars. Returns a per-pair summary."""
    import pandas as pd
    if fx is None:
        from tradingagents.dataflows import mexc_futures as fx  # noqa: PLC0415
    ensure_schema()
    done, out = 0, {"pairs": [], "bars_stored": 0, "errors": []}
    total = len(symbols) * len(intervals)
    for sym in symbols:
        for iv in intervals:
            done += 1
            if progress:
                progress(done, total, sym, iv)
            try:
                df = fx.klines(sym, iv, DOWNLOAD_BARS)
                prev = last_ts(sym, iv)
                fresh = df if prev is None else df[
                    df["Date"] > pd.Timestamp(prev, unit="s")]
                n = upsert_candles(sym, iv, fresh)
                out["bars_stored"] += n
                out["pairs"].append({"symbol": sym, "timeframe": iv,
                                     "new_bars": n, "have": len(df)})
            except Exception as exc:
                out["errors"].append(f"{sym} {iv}: {exc}")
    return out


# ------------------------------------------------------------------ results
# A strategy IS the seven fields the operator names: coin, timeframe, signal,
# THRESHOLD, TP, SL, sizing. Threshold was missing, so two variants of one rule
# were indistinguishable in a query despite being different strategies.
RESULT_FIELDS = ("row_code", "symbol", "timeframe", "signal", "tp", "sl",
                 "sizing", "data_start", "data_end", "code_version",
                 "profit", "trades", "wins", "losses", "win_rate",
                 "worst_streak", "worst_streak_len", "months_json",
                 "detail_json", "computed_at", "threshold", "months_green",
                 "months_total", "days", "max_dd", "funding")


def save_results(rows: list[dict]) -> int:
    """Store computed grid rows. Same key (row_code, data_end, code_version)
    overwrites — recomputing a window replaces that window's row."""
    if not rows or not _ready():
        return 0
    cols = ", ".join(RESULT_FIELDS)
    sets = ", ".join(f"{f}=excluded.{f}" for f in RESULT_FIELDS[3:])
    payload = [{f: r.get(f) for f in RESULT_FIELDS} for r in rows]
    for p in payload:
        if not p.get("computed_at"):
            p["computed_at"] = int(time.time())
        p["code_version"] = p.get("code_version") or ""
    try:
        with _engine().begin() as cx:
            _multi_insert(
                cx, f"INSERT INTO backtest_results ({cols}) VALUES ",
                f" ON CONFLICT (row_code, data_end, code_version)"
                f" DO UPDATE SET {sets}",
                RESULT_FIELDS, payload)
        return len(payload)
    except Exception as exc:
        _stand_down(exc, "save_results")
        return 0


def load_results(symbol: str | None = None, timeframe: str | None = None,
                 signal: str | None = None,
                 data_end: int | None = None,
                 code_version: str | None = None,
                 sizing: str | None = None) -> list[dict]:
    if not _ready():
        return []
    from sqlalchemy import text
    sql = f"SELECT {', '.join(RESULT_FIELDS)} FROM backtest_results WHERE 1=1"
    params: dict = {}
    for name, val in (("symbol", symbol), ("timeframe", timeframe),
                      ("signal", signal), ("data_end", data_end),
                      ("code_version", code_version), ("sizing", sizing)):
        if val is not None:
            sql += f" AND {name}=:{name}"
            params[name] = val
    try:
        with _engine().connect() as cx:
            rows = cx.execute(text(sql), params).fetchall()
    except Exception as exc:
        _stand_down(exc, "load_results")
        return []
    return [dict(zip(RESULT_FIELDS, r, strict=False)) for r in rows]


# ------------------------------------------------------------------ storage
# Neon's free branch caps LOGICAL data at 512MB; the limit is overridable in
# neon_db.json ("size_limit_mb") for a paid plan.
DEFAULT_SIZE_LIMIT_MB = 512


def size_limit_bytes() -> int:
    try:
        mb = float(json.loads(STORE_PATH.read_text()).get("size_limit_mb")
                   or DEFAULT_SIZE_LIMIT_MB)
    except Exception:
        mb = DEFAULT_SIZE_LIMIT_MB
    return int(mb * 1024 * 1024)


def storage_stats() -> dict | None:
    """How full the database is: measured size, the plan limit, and each
    table's share — None when the store is unreachable."""
    if not _ready():
        return None
    from sqlalchemy import text
    try:
        with _engine().connect() as cx:
            db_bytes = int(cx.execute(text(
                "SELECT pg_database_size(current_database())")).scalar())
            tables = cx.execute(text(
                "SELECT c.relname, pg_total_relation_size(c.oid),"
                "       coalesce(s.n_live_tup, 0)"
                " FROM pg_class c"
                " JOIN pg_namespace n ON n.oid = c.relnamespace"
                " LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid"
                " WHERE n.nspname = 'public' AND c.relkind = 'r'"
                " ORDER BY 2 DESC")).fetchall()
    except Exception as exc:
        _stand_down(exc, "storage_stats")
        return None
    limit = size_limit_bytes()
    return {
        "db_bytes": db_bytes,
        "limit_bytes": limit,
        "percent": round(100 * db_bytes / limit, 1),
        "tables": [{"table": r[0], "bytes": int(r[1]), "rows": int(r[2])}
                   for r in tables],
    }


# ------------------------------------------------------------- deployments
DEPLOY_FIELDS = ("change_id", "changed_at", "strategy_key", "symbol", "action",
                 "timeframe", "signal", "threshold", "tp", "sl", "sizing",
                 "books", "base_margin", "ladder_step", "row_code",
                 "prev_json", "note")


def deployment_id(row: dict) -> str:
    """Hash of the whole change, so two edits in one second both survive."""
    import hashlib
    import json as _j

    seed = _j.dumps({k: row.get(k) for k in DEPLOY_FIELDS if k != "change_id"},
                    sort_keys=True, default=str)
    return hashlib.blake2s(seed.encode(), digest_size=10).hexdigest()


def record_deployment(entry: dict) -> int:
    """Write one change to what is live. Same key overwrites, so re-saving an
    unchanged config does not fill the table with duplicates."""
    if not _ready():
        return 0
    row = {f: entry.get(f) for f in DEPLOY_FIELDS}
    row["changed_at"] = int(row.get("changed_at") or time.time())
    for req in ("strategy_key", "symbol", "action"):
        if not row.get(req):
            return 0
    row["change_id"] = deployment_id(row)
    cols = ", ".join(DEPLOY_FIELDS)
    try:
        with _engine().begin() as cx:
            _multi_insert(
                cx, f"INSERT INTO deployments ({cols}) VALUES ",
                " ON CONFLICT (change_id) DO NOTHING", DEPLOY_FIELDS, [row])
        return 1
    except Exception as exc:
        _stand_down(exc, "record_deployment")
        return 0


def deployments(symbol: str | None = None, limit: int = 200) -> list[dict]:
    """What was live, newest first."""
    if not _ready():
        return []
    from sqlalchemy import text
    sql = f"SELECT {', '.join(DEPLOY_FIELDS)} FROM deployments"
    params: dict = {}
    if symbol:
        sql += " WHERE symbol=:symbol"
        params["symbol"] = symbol
    sql += " ORDER BY changed_at DESC LIMIT :lim"
    params["lim"] = int(limit)
    try:
        with _engine().connect() as cx:
            rows = cx.execute(text(sql), params).fetchall()
    except Exception as exc:
        _stand_down(exc, "deployments")
        return []
    return [dict(zip(DEPLOY_FIELDS, r, strict=False)) for r in rows]


def prune_results(keep_per_pair: int = 500,
                  symbol: str | None = None) -> int:
    """Keep the best `keep_per_pair` rows per coin/timeframe/window, drop the
    rest. Returns rows deleted.

    A full market sweep writes ~17,000 rows per coin and timeframe; across 447
    contracts that is hundreds of megabytes of mostly-losing combinations. The
    losers are worth keeping for one comparison and not for a year.
    """
    if not _ready():
        return 0
    from sqlalchemy import text
    sql = """DELETE FROM backtest_results WHERE row_code IN (
               SELECT row_code FROM (
                 SELECT row_code, row_number() OVER (
                   PARTITION BY symbol, timeframe, data_end, code_version
                   ORDER BY profit DESC NULLS LAST) AS rn
                 FROM backtest_results
                 WHERE (:symbol IS NULL OR symbol = :symbol)) ranked
               WHERE rn > :keep)"""
    try:
        with _engine().begin() as cx:
            return cx.execute(text(sql), {"keep": int(keep_per_pair),
                                          "symbol": symbol}).rowcount or 0
    except Exception as exc:
        _stand_down(exc, "prune_results")
        return 0


def retention_tick(*, keep_per_pair: int = 500,
                   armed_symbols: list | None = None,
                   grid_path=None) -> dict:
    """Enforce the storage split's Neon diet, loudly and guardedly.

    * results pruned to the best ``keep_per_pair`` per (symbol, timeframe,
      window, code_version) — but ONLY when the full grid is proven on disk
      (``grid_path`` exists and is non-empty). Never delete from the database
      what the file store does not yet hold.
    * candles kept only for coins with a live strategy. An EMPTY armed list
      deletes nothing: a config hiccup must not empty the archive.
    """
    out = {"results_dropped": 0, "candle_symbols_dropped": [], "aborted": ""}
    if grid_path is not None:
        try:
            ok = os.path.getsize(grid_path) > 0
        except OSError:
            ok = False
        if not ok:
            out["aborted"] = "grid snapshot missing or empty"
            return out
    out["results_dropped"] = prune_results(keep_per_pair=keep_per_pair)
    if armed_symbols:
        from sqlalchemy import text
        try:
            with _engine().begin() as cx:
                gone = sorted(r[0] for r in cx.execute(text(
                    "SELECT DISTINCT symbol FROM candles")).fetchall()
                    if r[0] not in set(armed_symbols))
                for sym in gone:
                    cx.execute(text("DELETE FROM candles WHERE symbol=:s"),
                               {"s": sym})
                out["candle_symbols_dropped"] = gone
        except Exception as exc:
            _stand_down(exc, "retention_tick")
    return out


def table_sizes() -> dict:
    """Rows and disk per table, so growth is visible before it is a problem."""
    if not _ready():
        return {}
    from sqlalchemy import text
    out = {}
    for t in ("candles", "backtest_results", "deployments", "trade_ledger"):
        try:
            with _engine().connect() as cx:
                n = cx.execute(text(f"SELECT count(*) FROM {t}")).scalar()
                try:
                    size = cx.execute(text(
                        "SELECT pg_size_pretty(pg_total_relation_size(:t))"),
                        {"t": t}).scalar()
                except Exception:
                    size = None                 # sqlite has no such function
            out[t] = {"rows": int(n or 0), "size": size}
        except Exception:
            continue
    return out


# ------------------------------------------------------------------ ledger
LEDGER_FIELDS = ("fingerprint", "ts", "action", "symbol", "strategy", "side",
                 "dry_run", "entry", "exit_price", "vol", "margin", "leverage",
                 "step", "pnl", "why", "raw_json")


def ledger_fingerprint(e: dict) -> str:
    """Stable id for a ledger line, so syncing twice writes once.

    Hashes the WHOLE record. A field-list version dropped a real exit: two BDX
    lines shared a second, a symbol and an action but differed in `why` —
    MANUAL/EXCHANGE against LIQUIDATED — and only one survived the sync.
    """
    import hashlib
    import json as _j

    try:
        seed = _j.dumps(e, sort_keys=True, default=str)
    except Exception:
        seed = repr(sorted(e.items()))
    return hashlib.blake2s(seed.encode(), digest_size=10).hexdigest()


def sync_ledger(entries: list[dict]) -> int:
    """Copy local ledger lines into the archive. Idempotent by fingerprint."""
    if not entries or not _ready():
        return 0
    payload = []
    for e in entries:
        payload.append({
            "fingerprint": ledger_fingerprint(e), "ts": int(e.get("ts") or 0),
            "action": e.get("action") or "", "symbol": e.get("symbol"),
            "strategy": e.get("strategy"), "side": e.get("side"),
            # 498 of 1,043 lines carry no dry_run at all. Storing absent as
            # False labelled them REAL MONEY, which they may not be. NULL is
            # the honest answer.
            "dry_run": (None if e.get("dry_run") is None
                        else bool(e.get("dry_run"))),
            "entry": e.get("entry"),
            "exit_price": e.get("exit"), "vol": e.get("vol"),
            "margin": e.get("margin"), "leverage": e.get("leverage"),
            "step": e.get("step"), "pnl": e.get("pnl"), "why": e.get("why"),
            "raw_json": _json_dumps(e)})
    cols = ", ".join(LEDGER_FIELDS)
    try:
        from sqlalchemy import text as _t

        with _engine().begin() as cx:
            before = cx.execute(_t("SELECT count(*) FROM trade_ledger")).scalar()
            _multi_insert(cx, f"INSERT INTO trade_ledger ({cols}) VALUES ",
                          " ON CONFLICT (fingerprint) DO NOTHING",
                          LEDGER_FIELDS, payload)
            after = cx.execute(_t("SELECT count(*) FROM trade_ledger")).scalar()
        # rows actually WRITTEN, not rows offered: syncing the same file twice
        # reported "1,043 written" both times, which is a lie the second time
        return int(after) - int(before)
    except Exception as exc:
        _stand_down(exc, "sync_ledger")
        return 0


def ledger_rows(symbol: str | None = None, action: str | None = None,
                limit: int = 500) -> list[dict]:
    if not _ready():
        return []
    from sqlalchemy import text
    sql = f"SELECT {', '.join(LEDGER_FIELDS)} FROM trade_ledger WHERE 1=1"
    params: dict = {}
    for name, val in (("symbol", symbol), ("action", action)):
        if val:
            sql += f" AND {name}=:{name}"
            params[name] = val
    sql += " ORDER BY ts DESC LIMIT :lim"
    params["lim"] = int(limit)
    try:
        with _engine().connect() as cx:
            rows = cx.execute(text(sql), params).fetchall()
    except Exception as exc:
        _stand_down(exc, "ledger_rows")
        return []
    return [dict(zip(LEDGER_FIELDS, r, strict=False)) for r in rows]


def _json_dumps(v) -> str:
    import json as _j

    try:
        return _j.dumps(v)
    except Exception:
        return "{}"
