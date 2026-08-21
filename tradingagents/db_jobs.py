"""Detached download/backtest jobs for the archive, with progress and STOP.

Running these inline froze the Backtest page for the whole job and offered
no way out but clicking something and hoping. Each job runs as its own
process (same pattern as the market sweep): the caller writes a spec file,
progress lands in a JSON file the page polls, and STOP is a flag file the
job checks between units of work — a stopped download KEEPS everything
already stored.

    python -m tradingagents.db_jobs download|backtest
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

STATE_DIR = Path(os.path.expanduser("~/.tradingagents"))

FILES = {
    "download": {"progress": STATE_DIR / "db_download.json",
                 "spec": STATE_DIR / "db_download.spec.json",
                 "pid": STATE_DIR / "db_download.pid",
                 "stop": STATE_DIR / "db_download.STOP"},
    "backtest": {"progress": STATE_DIR / "db_backtest.json",
                 "spec": STATE_DIR / "db_backtest.spec.json",
                 "pid": STATE_DIR / "db_backtest.pid",
                 "stop": STATE_DIR / "db_backtest.STOP"},
    # one deployed strategy, replayed over a year — the Auto Trade "1 YEAR"
    # button. Detached because the grid takes minutes and a request must not
    # hold it open.
    "stratbt": {"progress": STATE_DIR / "db_stratbt.json",
                "spec": STATE_DIR / "db_stratbt.spec.json",
                "pid": STATE_DIR / "db_stratbt.pid",
                "stop": STATE_DIR / "db_stratbt.STOP"},
    "btupdate": {"progress": STATE_DIR / "db_btupdate.json",
                 "spec": STATE_DIR / "db_btupdate.spec.json",
                 "pid": STATE_DIR / "db_btupdate.pid",
                 "stop": STATE_DIR / "db_btupdate.STOP"},
}

# Where the finished backtest report page goes — the same folder the app's
# other backtest buttons publish to, so links work identically.
REPORT_DIR = Path(__file__).resolve().parent.parent / "static" / "bt"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def status(kind: str) -> dict:
    """Progress plus whether the process is actually alive — a stale JSON
    from a crashed job must never read as RUNNING."""
    f = FILES[kind]
    prog = _read(f["progress"])
    pid = 0
    try:
        pid = int(f["pid"].read_text().strip())
    except Exception:
        pass
    if prog.get("running") and not (pid and _alive(pid)):
        prog["running"] = False       # crashed or killed: say so, not RUNNING
        prog.setdefault("note", "process died before finishing")
    prog["pid"] = pid
    return prog


def request_stop(kind: str) -> None:
    FILES[kind]["stop"].touch()


def _stopping(kind: str) -> bool:
    return FILES[kind]["stop"].exists()


def start(kind: str, spec: dict) -> int:
    """Write the job's spec and launch it detached. Refuses to double-start."""
    st = status(kind)
    if st.get("running"):
        return st.get("pid") or 0
    f = FILES[kind]
    f["stop"].unlink(missing_ok=True)
    _write(f["spec"], spec)
    logf = open(STATE_DIR / f"db_{kind}.log", "a")
    proc = subprocess.Popen(
        [sys.executable, "-m", "tradingagents.db_jobs", kind],
        cwd=str(Path(__file__).resolve().parent.parent),
        stdout=logf, stderr=logf, start_new_session=True)
    f["pid"].write_text(str(proc.pid))
    _write(f["progress"], {"running": True, "started": int(time.time()),
                           "done": 0, "total": 0, "now": "starting"})
    return proc.pid


# --------------------------------------------------------------- job bodies
def _run_download(spec: dict) -> None:
    """DOWNLOAD/UPDATE fill the operator's OWN MACHINE — the store every
    backtest reads. Pure local: no database is touched.

    `mode: "update"` means "top up what I already have": the pairs come from
    the store itself, so a store filled on 28 July and updated on 21 August
    fetches exactly the bars between — refresh_candles walks back from the
    stored last bar, never re-downloading a year.
    """
    from tradingagents import market_sweep as msw
    from tradingagents import parquet_store as pqs
    f = FILES["download"]
    if spec.get("mode") == "update" and not spec.get("coins"):
        pairs = [(c["symbol"], c["timeframe"]) for c in msw.candle_coverage()]
    else:
        coins = spec["coins"]
        tfs = [t for t in spec["tfs"]
               if t in ("15m", "30m", "1h", "4h", "1d")]
        pairs = [(c, tf) for c in coins for tf in tfs]
    stored, errors, stopped, i = 0, [], False, 0
    for i, (c, tf) in enumerate(pairs):
        if _stopping("download"):
            stopped = True
            break
        _write(f["progress"], {"running": True, "done": i, "total": len(pairs),
                               "now": f"{c} {tf}", "bars_stored": stored,
                               "errors": len(errors)})
        try:
            df, added, _src = msw.refresh_candles(c, tf, days=365)
            pqs.save_candles(c, tf, df)          # the parquet copy, atomically
            stored += int(added)
        except Exception as exc:
            errors.append(f"{c} {tf}: {str(exc)[:80]}")
            continue
    _write(f["progress"], {
        "running": False, "done": i if stopped else len(pairs),
        "total": len(pairs), "bars_stored": stored, "errors": len(errors),
        "first_error": (errors[0] if errors else ""),
        "stopped": stopped, "finished": int(time.time()),
        "mode": spec.get("mode") or "download",
        "note": ("stopped by you — everything downloaded so far is kept"
                 if stopped else
                 f"{'gap-filled' if spec.get('mode') == 'update' else 'downloaded'} "
                 f"{len(pairs)} pair(s)")})


class _StopRequested(Exception):
    pass


def result_rows(payload: dict, days: int, signals_count: int) -> list[dict]:
    """Grid rows -> backtest_results rows. One shape for the page, this job
    and the GitHub job, so no path quietly drops a column."""
    day_end = int(time.time()) // 86400 * 86400
    return [{
        "row_code": r["id"], "symbol": f"{r['coin']}_USDT",
        "timeframe": r["tf"], "signal": r["signal"],
        # threshold is part of WHICH strategy this is: mom6 at 0.2 and
        # mom6 at 0.3 are different strategies with different results
        "threshold": r.get("th"), "tp": r["tp"], "sl": r["sl"],
        "sizing": r["sizing"],
        "data_start": day_end - days * 86400, "data_end": day_end,
        "code_version": f"signals{signals_count}",
        "profit": r["profit"], "trades": r["trades"], "wins": r["wins"],
        "losses": r["losses"], "win_rate": r["winrate"],
        # worst_streak is the LOSING RUN summed, not the drawdown — two
        # different numbers, and the column is named for the first
        "worst_streak": r.get("wstreak"), "worst_streak_len": r.get("wstreakn"),
        "months_green": r.get("green"), "months_total": r.get("months"),
        "days": r.get("days"), "max_dd": r.get("dd"),
        "funding": r.get("funding"),
        # not every row carries months (the fast path skips them on rows
        # below the floor) — an absent field must not sink the whole save
        "months_json": json.dumps(r.get("monthly") or {}),
    } for r in payload["rows"]]


def _armed_symbols() -> list:
    """Coins with a live strategy — the only candles Neon keeps."""
    try:
        from tradingagents import auto_trader as at

        cfg = at.load_settings()
        books = cfg.get("strategy_books") or {}
        coins = cfg.get("strategy_coins") or {}
        return sorted({c for k, cs in coins.items()
                       for c in (cs or []) if books.get(k)})
    except Exception:
        return []


def _signals_count() -> int:
    from tradingagents import backtest_report as br

    return len(br.SIGNALS)


def persist_results(payload: dict, *, days: int, label: str,
                    mdb=None, pq=None) -> int:
    """Snapshot the full grid to the operator's own disk. Pure local — "i
    told you that its pure local" — so no database is written or dieted; the
    pair store (market_sweep) already holds every row, and this file is the
    immutable record of THIS run. A failed snapshot raises."""
    if pq is None:
        from tradingagents import parquet_store as pq
    pq.save_grid(payload["rows"], label=label)
    return len(payload["rows"])


def _run_backtest(spec: dict) -> None:
    """Crash containment: whatever happens inside, the progress file ends in
    running:false with the error named. A job that died at 80% once left
    'running: true' on screen for half an hour."""
    try:
        _run_backtest_inner(spec)
    except _StopRequested:
        raise
    except Exception as exc:
        _write(FILES["backtest"]["progress"], {
            "running": False, "finished": int(time.time()),
            "error": str(exc)[:200],
            "note": f"failed: {str(exc)[:160]}"})
        raise


def _run_backtest_inner(spec: dict) -> None:
    from tradingagents import backtest_report as br
    f = FILES["backtest"]

    def prog(msg: str, frac: float) -> None:
        if _stopping("backtest"):
            raise _StopRequested()
        _write(f["progress"], {"running": True, "done": round(frac * 100),
                               "total": 100, "now": msg})

    try:
        payload = br.grid_from_store(
            spec["coins"], spec["tfs"], base_margin=float(spec["base"]),
            days=int(spec["days"]), deployed=spec.get("deployed") or [],
            progress=prog)
    except _StopRequested:
        _write(f["progress"], {"running": False, "stopped": True,
                               "finished": int(time.time()),
                               "note": "stopped by you — a backtest has no "
                                       "partial answer, so nothing was saved"})
        return
    if not payload["rows"]:
        _write(f["progress"], {"running": False, "rows": 0,
                               "finished": int(time.time()),
                               "note": "nothing survived the trade floor"})
        return
    name = spec["report_name"]
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    br.write_report(str(REPORT_DIR / name), payload,
                    title=spec.get("title") or "Archive backtest",
                    note=spec.get("note") or "")
    saved, save_err = 0, ""
    try:
        saved = persist_results(payload, days=int(spec["days"]),
                                label=spec.get("label") or "archive")
    except Exception as exc:                 # never claim a save that failed
        save_err = str(exc)[:160]
    _write(f["progress"], {"running": False, "rows": len(payload["rows"]),
                           "saved": saved, "save_error": save_err,
                           "report": name, "finished": int(time.time())})


def _run_btupdate(spec: dict) -> None:
    """CONTINUE stored backtests over new bars only — never from scratch.

    Uses the sweep's per-combination resume state (`run_pair`): each
    combination picks up with its ladder rung, running totals and any open
    position from where the last run stopped, and walks only the bars that
    printed since. A stopped update keeps every pair already continued."""
    from tradingagents import backtest_report as br
    from tradingagents import market_sweep as msw
    f = FILES["btupdate"]
    pairs = [(c, tf) for c in spec["coins"] for tf in spec["tfs"]]
    days = int(spec.get("days") or 365)
    base = float(spec.get("base") or 5.0)
    rows, new_bars, stopped, i, notes = [], 0, False, 0, []
    for i, (sym, tf) in enumerate(pairs):
        if _stopping("btupdate"):
            stopped = True
            break
        _write(f["progress"], {"running": True, "done": i,
                               "total": len(pairs), "now": f"{sym} {tf}",
                               "rows": len(rows), "new_bars": new_bars})
        try:
            r = msw.run_pair(sym, tf, base_margin=base, days=days,
                             thresholds=3)
        except Exception as exc:
            notes.append(f"{sym} {tf}: {str(exc)[:80]}")
            continue
        rows += r.get("rows") or []
        new_bars += int(r.get("new_bars") or 0)
        if r.get("why"):
            notes.append(f"{sym} {tf}: {r['why']}")
    # run_pair already persisted every row into the local pair store — pure
    # local, nothing else to write. `saved` reports what landed there.
    saved, save_err = len(rows), ""
    for r in rows:                         # ids for the progress readout
        r.setdefault("id", br.row_code(
            r["coin"], r["tf"], r["signal"], r.get("th") or 0.0,
            r["sl"], r["tp"], r["sizing"]))
    _write(f["progress"], {
        "running": False, "done": i if stopped else len(pairs),
        "total": len(pairs), "rows": len(rows), "saved": saved,
        "save_error": save_err, "new_bars": new_bars, "stopped": stopped,
        "finished": int(time.time()),
        "note": ("stopped by you — every pair already continued is kept; " if stopped else "")
                + ("; ".join(notes[:3]))})


def _run_stratbt(spec: dict) -> None:
    """Replay ONE deployed strategy over a year and write its grid page."""
    from tradingagents import strategy_report as sr
    f = FILES["stratbt"]
    key = spec["key"]

    def prog(msg: str, frac: float) -> None:
        _write(f["progress"], {"running": True, "key": key, "now": msg,
                               "done": int(max(0.0, min(1.0, frac)) * 100),
                               "total": 100})

    try:
        got = sr.build(key, label=spec.get("label") or key,
                       coins=spec["coins"],
                       base_margin=float(spec.get("base_margin") or 5.0),
                       days=int(spec.get("days") or 365), progress=prog)
        _write(f["progress"], {"running": False, "key": key, "done": 100,
                               "total": 100, "report": got["name"],
                               "report_url": got["url"], "rows": got["rows"],
                               "cached": got["cached"],
                               "finished": int(time.time()),
                               "note": "cached page reused" if got["cached"]
                                       else f"{got['rows']} rows tested"})
    except Exception as exc:                                   # noqa: BLE001
        _write(f["progress"], {"running": False, "key": key,
                               "error": f"{type(exc).__name__}: {exc}",
                               "note": f"failed: {exc}",
                               "finished": int(time.time())})
        raise


def main(argv: list[str]) -> int:
    kind = argv[0]
    spec = _read(FILES[kind]["spec"])
    if kind == "stratbt":
        _run_stratbt(spec)
    elif kind == "download":
        _run_download(spec)
    elif kind == "backtest":
        _run_backtest(spec)
    elif kind == "btupdate":
        _run_btupdate(spec)
    else:
        print(f"unknown job: {kind}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
