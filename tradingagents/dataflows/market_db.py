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
    if _ENGINE is None or _ENGINE_URL != url:
        from sqlalchemy import create_engine
        _ENGINE = create_engine(url, pool_pre_ping=True, pool_size=2,
                                max_overflow=2)
        _ENGINE_URL = url
    return _ENGINE


def _ready() -> bool:
    return time.time() >= _down_until and db_url() is not None


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
        PRIMARY KEY (row_code, data_end, code_version))""",
    """CREATE INDEX IF NOT EXISTS idx_results_lookup
        ON backtest_results (symbol, timeframe, signal)""",
]


def ensure_schema() -> bool:
    if not _ready():
        return False
    from sqlalchemy import text
    try:
        with _engine().begin() as cx:
            for stmt in DDL:
                cx.execute(text(stmt))
        return True
    except Exception as exc:
        _stand_down(exc, "ensure_schema")
        return False


# ------------------------------------------------------------------ candles
def upsert_candles(symbol: str, interval: str, df) -> int:
    """Store closed candles; re-sent bars overwrite (a bar refetched after
    its close corrects one saved while still forming). Returns rows sent."""
    if df is None or not len(df) or not _ready():
        return 0
    rows = [{"s": symbol, "f": interval,
             "ts": int(d.timestamp()), "o": float(o), "h": float(h),
             "l": float(l), "c": float(c), "v": float(v)}
            for d, o, h, l, c, v in zip(df["Date"], df["Open"], df["High"],
                                        df["Low"], df["Close"], df["Volume"])]
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
RESULT_FIELDS = ("row_code", "symbol", "timeframe", "signal", "tp", "sl",
                 "sizing", "data_start", "data_end", "code_version",
                 "profit", "trades", "wins", "losses", "win_rate",
                 "worst_streak", "worst_streak_len", "months_json",
                 "detail_json", "computed_at")


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
                 code_version: str | None = None) -> list[dict]:
    if not _ready():
        return []
    from sqlalchemy import text
    sql = f"SELECT {', '.join(RESULT_FIELDS)} FROM backtest_results WHERE 1=1"
    params: dict = {}
    for name, val in (("symbol", symbol), ("timeframe", timeframe),
                      ("signal", signal), ("data_end", data_end),
                      ("code_version", code_version)):
        if val is not None:
            sql += f" AND {name}=:{name}"
            params[name] = val
    try:
        with _engine().connect() as cx:
            rows = cx.execute(text(sql), params).fetchall()
    except Exception as exc:
        _stand_down(exc, "load_results")
        return []
    return [dict(zip(RESULT_FIELDS, r)) for r in rows]
