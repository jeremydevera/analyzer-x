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
    from tradingagents.dataflows import market_db as mdb
    f = FILES["download"]
    coins = spec["coins"]
    ivs = [mdb.TIMEFRAMES[t] for t in spec["tfs"] if t in mdb.TIMEFRAMES]
    pairs = [(c, iv) for c in coins for iv in ivs]
    stored, errors, stopped, i = 0, [], False, 0
    mdb.ensure_schema()
    for i, (c, iv) in enumerate(pairs):
        if _stopping("download"):
            stopped = True
            break
        _write(f["progress"], {"running": True, "done": i, "total": len(pairs),
                               "now": f"{c} {iv}", "bars_stored": stored,
                               "errors": len(errors)})
        res = mdb.download([c], [iv])
        stored += res["bars_stored"]
        errors += res["errors"]
    _write(f["progress"], {
        "running": False, "done": i if stopped else len(pairs),
        "total": len(pairs), "bars_stored": stored, "errors": len(errors),
        "first_error": (errors[0] if errors else ""),
        "stopped": stopped, "finished": int(time.time()),
        "note": ("stopped by you — everything downloaded so far is kept"
                 if stopped else "")})


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
        "worst_streak": r["dd"], "worst_streak_len": None,
        "months_green": r.get("green"), "months_total": r.get("months"),
        "days": r.get("days"), "max_dd": r.get("dd"),
        "funding": r.get("funding"),
        # not every row carries months (the fast path skips them on rows
        # below the floor) — an absent field must not sink the whole save
        "months_json": json.dumps(r.get("monthly") or {}),
    } for r in payload["rows"]]


def _run_backtest(spec: dict) -> None:
    from tradingagents import backtest_report as br
    from tradingagents.dataflows import market_db as mdb
    f = FILES["backtest"]

    def prog(msg: str, frac: float) -> None:
        if _stopping("backtest"):
            raise _StopRequested()
        _write(f["progress"], {"running": True, "done": round(frac * 100),
                               "total": 100, "now": msg})

    try:
        payload = br.run_grid(
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
        mdb.ensure_schema()
        saved = mdb.save_results(
            result_rows(payload, int(spec["days"]), len(br.SIGNALS)))
    except Exception as exc:                 # never claim a save that failed
        save_err = str(exc)[:160]
    _write(f["progress"], {"running": False, "rows": len(payload["rows"]),
                           "saved": saved, "save_error": save_err,
                           "report": name, "finished": int(time.time())})


def main(argv: list[str]) -> int:
    kind = argv[0]
    spec = _read(FILES[kind]["spec"])
    if kind == "download":
        _run_download(spec)
    elif kind == "backtest":
        _run_backtest(spec)
    else:
        print(f"unknown job: {kind}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
