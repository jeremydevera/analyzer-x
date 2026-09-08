"""Storage by calendar month, and a way to delete a month to free disk.

Operator, 2026-09-09: *"in candles create a table showing candles for each
month for example feb 2025 march 2025 and able to delete it so that i can free
up space same as for backtests results"*. Measured that morning on their PC:
candles 1.7 GB, backtest rows 23 GB, rows.db 33 GB.

Two stores, two different meanings of "a month":

* CANDLES are one file per contract+timeframe (`BTC_USDT-1h.json`), so a month
  is the bars whose timestamps fall inside it. Deleting a month trims every
  file — and it deletes that month AND EVERYTHING OLDER, never a month out of
  the middle. The sweep reads a pair's bars as one unbroken series and
  `refresh_candles` only fetches FORWARD from the last stored bar, so a hole
  in the middle would never be refilled and every signal computed across it
  would be silently wrong. Old bars are what frees space anyway.
* BACKTEST RESULTS are one rows file per coin+timeframe holding rows over the
  pair's whole history — there is no "February" inside a row file to remove.
  So a month here is WHEN THE PAIR WAS LAST MEASURED (its rows file's mtime,
  which the index already stores), and deleting a month drops every pair
  measured in that month or earlier: its rows in rows.db first, then its rows
  file and resume state. Those pairs can be measured again.

Both deletes run in a background THREAD with a progress record this module
owns, because trimming 5,243 files is minutes and the UI proxy gives up at
30 s. A delete REFUSES to start while a job that writes the same store is
running (a download rewrites candle files; backtest/collect/btupdate rewrite
rows files) — the loser of that race would silently lose bars or rows.
"""
from __future__ import annotations

import calendar
import re
import threading
import time

from tradingagents import market_sweep as msw

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
# the jobs that WRITE each store — a delete never runs beside one of these
WRITERS = {"candles": ("download",),
           "results": ("backtest", "collect", "btupdate")}

_lock = threading.Lock()
_jobs: dict = {"candles": None, "results": None}


# ---------------------------------------------------------------- months
def month_key(ms: int | float) -> str:
    """Epoch ms -> the store's month key, "2025-02". UTC, like the bars."""
    t = time.gmtime(float(ms) / 1000.0)
    return f"{t.tm_year:04d}-{t.tm_mon:02d}"


def month_label(key: str) -> str:
    """"2025-02" -> "Feb 2025". A month LABEL keeps its own short form (the
    date rule is about instants); the abbreviation is calendar's, not a
    locale's."""
    y, m = key.split("-")
    return f"{calendar.month_abbr[int(m)]} {int(y)}"


def month_start_ms(key: str) -> int:
    y, m = (int(x) for x in key.split("-"))
    return int(calendar.timegm((y, m, 1, 0, 0, 0))) * 1000


def next_month(key: str) -> str:
    y, m = (int(x) for x in key.split("-"))
    return f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"


def _months_between(first_ms: int, last_ms: int) -> list[str]:
    out, k, stop = [], month_key(first_ms), month_key(last_ms)
    while True:
        out.append(k)
        if k >= stop:
            return out
        k = next_month(k)


def _bar_ms(tf: str) -> int:
    from tradingagents.dataflows.market_db import BAR_SECONDS, TIMEFRAMES

    return int(BAR_SECONDS.get(TIMEFRAMES.get(tf, tf), 0)) * 1000


# ---------------------------------------------------------------- candles
def candle_months(index: dict | None = None) -> dict:
    """Bars and bytes per month across every stored candle file — from the
    candle INDEX, never by parsing 1.7 GB of files on a polled route.

    The index holds bars/first/last per file, not per month, so the split is
    arithmetic over an unbroken series (first + k*bar): exact when there are
    no gaps, an estimate when there are — and the row says so
    (`estimated: True`). The DELETE reports the real bytes it freed.
    """
    index = msw.candle_index(scan=False) if index is None else index
    per: dict = {}
    for entry in index.values():
        bars = int(entry.get("bars") or 0)
        size = int(entry.get("size") or 0)
        first, last = entry.get("first_ms"), entry.get("last_ms")
        step = _bar_ms(str(entry.get("timeframe") or ""))
        if not bars or first is None or last is None or step <= 0:
            continue
        first, last = int(first), int(last)
        counts: dict = {}
        for k in _months_between(first, last):
            m0, m1 = month_start_ms(k), month_start_ms(next_month(k))
            lo = max(0, -((first - m0) // step))            # ceil((m0-first)/step)
            hi = min(bars, -((first - m1) // step))         # ceil((m1-first)/step)
            n = max(0, hi - lo)
            if n:
                counts[k] = n
        total = sum(counts.values()) or 1
        for k, n in counts.items():
            row = per.setdefault(k, {"bars": 0, "bytes": 0.0, "pairs": 0})
            # scaled so a file's months sum to ITS bar count even with gaps
            share = n * bars / total
            row["bars"] += share
            row["bytes"] += size * share / bars
            row["pairs"] += 1
    rows = [{"month": k, "label": month_label(k),
             "bars": int(round(v["bars"])), "bytes": int(round(v["bytes"])),
             "pairs": int(v["pairs"])}
            for k, v in sorted(per.items(), reverse=True)]
    return {"rows": rows, "estimated": True,
            "total_bars": sum(r["bars"] for r in rows),
            "total_bytes": sum(r["bytes"] for r in rows),
            "files": len(index)}


def _run_candles(job: dict) -> None:
    cut = month_start_ms(next_month(job["through"]))
    files = sorted(msw.CANDLES.glob("*.json"))
    job["total"] = len(files)
    for f in files:
        if job.get("stop"):
            break
        sym, _, tf = f.stem.rpartition("-")
        try:
            got = msw.trim_candles_cache(sym, tf, cut)
            job["freed"] += got["bytes_before"] - got["bytes_after"]
            job["bars_removed"] += got["bars_before"] - got["bars_after"]
            if got["removed_file"]:
                job["files_removed"] += 1
            elif got["bars_before"] != got["bars_after"]:
                job["files_trimmed"] += 1
            _trim_parquet(sym, tf, cut, job)
        except Exception as exc:                                # noqa: BLE001
            job["errors"].append(f"{f.stem}: {type(exc).__name__}: {exc}")
        job["done"] += 1
    # the candle index keys on (mtime, size), so only the rewritten files
    # are re-read here — and the storage screen then says what is left
    try:
        msw.candle_index(scan=True)
    except Exception as exc:                                    # noqa: BLE001
        job["errors"].append(f"candle index: {type(exc).__name__}: {exc}")


def _trim_parquet(symbol: str, tf: str, cut_ms: int, job: dict) -> None:
    """The parquet mirror holds the same bars; leaving it longer than the JSON
    would make storage_by_coin count bytes for months the screen said were
    deleted. Best effort — a missing pyarrow is not a failed delete."""
    try:
        import pandas as pd

        from tradingagents import parquet_store as pqs

        p = pqs._candle_path(symbol, tf)
        if not p.exists():
            return
        before = p.stat().st_size
        df = pqs.load_candles(symbol, tf)
        if df is None or "Date" not in df.columns or not len(df):
            return
        keep = df[pd.to_datetime(df["Date"]) >= pd.Timestamp(cut_ms, unit="ms")]
        if len(keep) == len(df):
            return
        if not len(keep):
            p.unlink()
            job["freed"] += before
            return
        pqs.save_candles(symbol, tf, keep.reset_index(drop=True))
        job["freed"] += before - p.stat().st_size
    except Exception as exc:                                    # noqa: BLE001
        job["errors"].append(f"parquet {symbol}-{tf}: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- results
def results_months() -> dict:
    """Pairs, rows and bytes per month LAST MEASURED — one small query over
    the pairs table (rows_mtime is the rows file's mtime, bytes is the rows
    file plus its state file, both recorded when the pair was indexed)."""
    from tradingagents import rows_index as ri

    def _read():
        with ri._open(readonly=True) as con:
            return [dict(r) for r in con.execute(
                "SELECT strftime('%Y-%m', rows_mtime, 'unixepoch') AS m, "
                "COUNT(*) AS pairs, COALESCE(SUM(n),0) AS rows_n, "
                "COALESCE(SUM(bytes),0) AS bytes, "
                "SUM(CASE WHEN bytes IS NULL THEN 1 ELSE 0 END) AS unsized "
                "FROM pairs WHERE coin IS NOT NULL AND rows_mtime IS NOT NULL "
                "GROUP BY m ORDER BY m DESC")]

    got = ri._missing_ok(_read, [])
    rows = [{"month": r["m"], "label": month_label(r["m"]),
             "pairs": int(r["pairs"]), "rows": int(r["rows_n"]),
             "bytes": int(r["bytes"]), "unsized": int(r["unsized"] or 0)}
            for r in got if r.get("m")]
    return {"rows": rows, "estimated": False,
            "total_rows": sum(r["rows"] for r in rows),
            "total_bytes": sum(r["bytes"] for r in rows)}


def _pairs_through(through: str) -> list[dict]:
    from tradingagents import rows_index as ri

    def _read():
        with ri._open(readonly=True) as con:
            return [dict(r) for r in con.execute(
                "SELECT pair, coin, tf FROM pairs WHERE coin IS NOT NULL "
                "AND rows_mtime IS NOT NULL "
                "AND strftime('%Y-%m', rows_mtime, 'unixepoch') <= ? "
                "ORDER BY pair", (through,))]

    return ri._missing_ok(_read, [])


def _run_results(job: dict) -> None:
    from tradingagents import rows_index as ri

    pairs = _pairs_through(job["through"])
    job["total"] = len(pairs)
    for p in pairs:
        if job.get("stop"):
            break
        try:
            # index FIRST, files second — see rows_index.forget_pair
            job["rows_removed"] += ri.forget_pair(p["pair"])
            gone = msw.discard_pair(p["coin"], p["tf"])
            job["freed"] += sum(int(g["bytes"]) for g in gone["deleted"])
            job["files_removed"] += len(gone["deleted"])
            # and the index AGAIN: the API's sync timer runs every few
            # seconds and takes a file it has no summary for as NEW, so a
            # tick between the two lines above re-indexes the pair just
            # before its file goes — rows on screen for a pair that no
            # longer exists (harddev round 1). Cheap when there is nothing.
            job["rows_removed"] += ri.forget_pair(p["pair"])
        except Exception as exc:                                # noqa: BLE001
            job["errors"].append(f"{p['pair']}: {type(exc).__name__}: {exc}")
        job["done"] += 1


# ---------------------------------------------------------------- the jobs
def _writer_running(kind: str) -> str:
    """The name of a job writing this store right now, or ""."""
    try:
        from tradingagents import db_jobs as dj
    except Exception:                                           # noqa: BLE001
        return ""
    for name in WRITERS.get(kind, ()):
        try:
            if dj.status(name).get("running"):
                return name
        except Exception:                                       # noqa: BLE001
            continue
    return ""


def start_delete(kind: str, through: str, now: float | None = None) -> dict:
    """Begin deleting `through` and every older month of `kind`. Raises
    ValueError with the reason when it must not — the route answers 409."""
    if kind not in _jobs:
        raise ValueError(f"unknown store {kind!r}; use candles or results")
    if not MONTH_RE.match(str(through or "")):
        raise ValueError(f"{through!r} is not a month like 2025-02")
    this_month = month_key((now if now is not None else time.time()) * 1000)
    if through >= this_month:
        raise ValueError(
            f"{month_label(through)} is the current month — deleting it would "
            f"remove what the runner and the next backtest need. Pick an older "
            f"month; everything older than it goes too")
    busy = _writer_running(kind)
    if busy:
        raise ValueError(
            f"a {busy} job is writing this store right now; wait for it to "
            f"finish, or stop it, then delete")
    with _lock:
        cur = _jobs.get(kind)
        if cur and cur.get("running"):
            raise ValueError(
                f"a delete of {kind} is already running "
                f"({cur['done']} of {cur['total']} done)")
        job = {"kind": kind, "through": through,
               "label": month_label(through), "running": True,
               "started": time.time(), "finished": None,
               "done": 0, "total": 0, "freed": 0, "errors": [],
               "files_removed": 0, "files_trimmed": 0, "bars_removed": 0,
               "rows_removed": 0}
        _jobs[kind] = job

    def _go():
        try:
            (_run_candles if kind == "candles" else _run_results)(job)
        except Exception as exc:                                # noqa: BLE001
            job["errors"].append(f"{type(exc).__name__}: {exc}")
        finally:
            job["running"] = False
            job["finished"] = time.time()

    threading.Thread(target=_go, name=f"delete-{kind}", daemon=True).start()
    return progress(kind)


def progress(kind: str) -> dict | None:
    """The job's record for the screen, dates in the operator's format."""
    from tradingagents.positions_view import fmt_when

    job = _jobs.get(kind)
    if not job:
        return None
    out = dict(job)
    out["started_at"] = fmt_when(job["started"])
    out["finished_at"] = fmt_when(job["finished"]) if job["finished"] else ""
    out["errors"] = list(job["errors"])[:20]
    out["error_count"] = len(job["errors"])
    out.pop("stop", None)
    return out


def snapshot() -> dict:
    """Everything the panel shows in one call."""
    return {"candles": candle_months(), "results": results_months(),
            "jobs": {k: progress(k) for k in _jobs},
            "writers": {k: _writer_running(k) for k in _jobs},
            "this_month": month_key(time.time() * 1000)}
