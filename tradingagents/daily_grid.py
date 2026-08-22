"""Detached runner for the Backtest 2 daily grid.

Why it exists: the grid used to run INLINE inside the Streamlit script, with
`st.progress()` as the only record of it. Refreshing the browser therefore
lost the bar *and* killed the run — the operator hit exactly that on
2026-08-21 ("when i refresh the backtest page the loading are lost"), after
being told to "leave this tab alone", which is not something a page should
ask of anyone.

Now the work runs as its own process and reports through a file on disk:

* the page reads :func:`state` on every render, so a refresh (or a tab
  switch, or closing the laptop) shows the same progress it showed before
* the process is tracked by PID, never by name — matching on a name once
  killed the operator's own server
* every write is atomic (tmp + replace); a half-written progress file read
  by the page would blank the panel mid-run
* the finished page's path lives in the same file, so the OPEN link survives
  a refresh too
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home() / ".tradingagents" / "backtest"
STATE = HOME / "daily.json"
PIDFILE = HOME / "daily.pid"
JOBFILE = HOME / "daily-job.json"


def _atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(path)


def state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def is_running() -> bool:
    """True when the runner process is alive, by PID."""
    try:
        pid = int(PIDFILE.read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start(*, coins: list, tfs: list, base: float, days: int, deployed: list,
          out_path: str, page_url: str, title: str, note: str,
          repo_root: str) -> dict:
    """Spawn the detached run. Returns the initial state dict."""
    job = {"coins": list(coins), "tfs": list(tfs), "base": float(base),
           "days": int(days), "deployed": list(deployed),
           "out_path": out_path, "page_url": page_url,
           "title": title, "note": note}
    _atomic(JOBFILE, job)
    init = {"phase": "starting", "frac": 0.0, "note": "launching…",
            "started": int(time.time()), "done": False, "error": "",
            "page_url": page_url, "out_path": out_path, "rows": 0,
            "coins": list(coins), "tfs": list(tfs)}
    _atomic(STATE, init)
    # the detached child writes here; closing it would kill its output
    log = open(HOME / "daily.log", "a")   # noqa: SIM115
    proc = subprocess.Popen(
        [sys.executable, "-m", "tradingagents.daily_grid",
         "--job", str(JOBFILE)],
        cwd=repo_root, stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True)
    _atomic(PIDFILE.with_suffix(".json"), {"pid": proc.pid})
    PIDFILE.write_text(str(proc.pid))
    return init


def main(argv: list | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)
    job = json.loads(Path(args.job).read_text())
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))

    from tradingagents import backtest_report as br

    base = {"started": int(time.time()), "done": False, "error": "",
            "page_url": job["page_url"], "out_path": job["out_path"],
            "coins": job["coins"], "tfs": job["tfs"]}

    def report(note: str, frac: float, **extra) -> None:
        _atomic(STATE, {**base, "phase": "running", "frac": float(frac),
                        "note": note, **extra})

    report("fetching candles…", 0.0)
    try:
        fn = getattr(br, "grid_from_store", None) or br.run_grid
        payload = fn(job["coins"], job["tfs"],
                     base_margin=job["base"], days=job["days"],
                     deployed=job["deployed"], progress=report)
        rows = len(payload.get("rows") or [])
        if not rows:
            _atomic(STATE, {**base, "phase": "empty", "frac": 1.0, "rows": 0,
                            "done": True,
                            "note": "no rows survived the trade floor"})
            return 1
        report(f"writing the page · {rows:,} rows", 0.98, rows=rows)
        br.write_report(job["out_path"], payload, title=job["title"],
                        note=job["note"])
        _atomic(STATE, {**base, "phase": "done", "frac": 1.0, "rows": rows,
                        "done": True,
                        "note": f"{rows:,} combinations measured",
                        "finished": int(time.time())})
        return 0
    except Exception as exc:                      # a crash must be VISIBLE
        _atomic(STATE, {**base, "phase": "failed", "frac": 0.0, "rows": 0,
                        "done": True, "error": f"{type(exc).__name__}: {exc}",
                        "note": "the run failed — see daily.log"})
        raise


if __name__ == "__main__":
    sys.exit(main())
