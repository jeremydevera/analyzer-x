"""Reap worker processes whose pool parent is gone.

A multiprocessing pool that is killed at the parent leaves its children behind,
reparented to init. They sit at 0% CPU forever, holding the log file open and
counting against the load average. On 2026-08-25 there were 139 of them from
sweeps going back three days, load average 49 on an 8-core machine, while the
one live pool got 5 cores.

The signature of an orphan is exact and it is checked, never guessed:

  * the executable is THIS virtualenv's python (not system python, not another
    project's), and
  * the argv is a `multiprocessing` worker or resource tracker, and
  * the parent is pid 1.

A live pool's workers have their pool parent as ppid, so they can never match.
The runner, the API, the web app, the row indexer and the sweep orchestrator are
not multiprocessing workers, so they can never match either — and they are also
listed explicitly, because "it cannot happen" is how a live trading process gets
killed. `pkill -f python` is never the answer here.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time

VENV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    ".venv")

# argv marks that only a pool child carries
WORKER_MARKS = ("multiprocessing.spawn", "multiprocessing.resource_tracker",
                "from multiprocessing.spawn import spawn_main",
                "from multiprocessing.resource_tracker import main")

# argv marks that must NEVER be signalled, whatever else matches
NEVER = ("auto_trader", "uvicorn", "streamlit", "next", "node",
         "sweep_orchestrator", "rows_index", "market_sweep")


def _ps() -> list[dict]:
    out = subprocess.run(["ps", "-eo", "pid,ppid,%cpu,etime,args"],
                         capture_output=True, text=True).stdout.splitlines()
    rows = []
    for line in out[1:]:
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            rows.append({"pid": int(parts[0]), "ppid": int(parts[1]),
                         "cpu": float(parts[2]), "etime": parts[3],
                         "args": parts[4]})
        except ValueError:
            continue
    return rows


def protected() -> set[int]:
    """Pids that must survive no matter what the argv looks like."""
    keep = {os.getpid(), os.getppid(), 1}
    for row in _ps():
        if any(m in row["args"] for m in NEVER):
            keep.add(row["pid"])
    # anything holding a pidfile, and anything listening on the app's ports
    home = os.path.expanduser("~/.tradingagents")
    for name in os.listdir(home) if os.path.isdir(home) else []:
        if name.endswith(".pid"):
            with contextlib.suppress(ValueError, OSError):
                with open(os.path.join(home, name)) as fh:
                    keep.add(int(fh.read().strip()))
    for port in ("8787", "8503", "8501"):
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                             capture_output=True, text=True).stdout
        keep.update(int(p) for p in out.split() if p.isdigit())
    return keep


def orphans() -> list[dict]:
    """Pool children of this venv whose parent is gone. All three tests, ANDed."""
    keep = protected()
    out = []
    for row in _ps():
        if row["pid"] in keep or row["ppid"] != 1:
            continue
        if VENV not in row["args"]:
            continue
        if not any(m in row["args"] for m in WORKER_MARKS):
            continue
        if any(m in row["args"] for m in NEVER):
            continue
        out.append(row)
    return out


def reap(*, dry_run: bool = False, grace: float = 3.0) -> dict:
    """SIGTERM the orphans, give them a moment, SIGKILL whatever is left."""
    found = orphans()
    if dry_run or not found:
        return {"found": len(found), "termed": 0, "killed": 0,
                "pids": [r["pid"] for r in found]}

    termed = []
    for row in found:
        try:
            os.kill(row["pid"], signal.SIGTERM)
            termed.append(row["pid"])
        except (ProcessLookupError, PermissionError):
            pass
    time.sleep(grace)

    alive = {r["pid"] for r in _ps()}
    killed = []
    for pid in termed:
        if pid in alive:
            try:
                os.kill(pid, signal.SIGKILL)
                killed.append(pid)
            except (ProcessLookupError, PermissionError):
                pass
    return {"found": len(found), "termed": len(termed), "killed": len(killed),
            "pids": termed}


def main() -> int:
    dry = "--dry-run" in sys.argv
    r = reap(dry_run=dry)
    verb = "would reap" if dry else "reaped"
    print(f"{verb} {r['found']} orphaned pool workers "
          f"(TERM {r['termed']}, KILL {r['killed']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
