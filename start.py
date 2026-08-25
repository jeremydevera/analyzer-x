#!/usr/bin/env python3
"""Start the app: React UI on 8503, Python API behind it on 8787.

    python start.py            # start (frees both ports first)
    python start.py status     # which ports are held, and whether the API answers
    python start.py stop       # free both ports by PID, never by process name

One launcher for macOS, Linux and Windows. `start.sh` and `start.cmd` are thin
wrappers around this file. Until 2026-08-25 the only launcher was a bash script
built on `lsof`, `nohup`, `curl` and `.venv/bin/uvicorn` — none of which exist
on a Windows PC, so the operator's second machine could not start the app at
all. Everything here is the standard library plus `npm`, which the UI needs
anyway.

The UI proxies /api/* to the API (webapp/next.config.ts), so the operator only
ever opens ONE url:  http://localhost:8503

Ports are freed by PID, never by process name — `pkill -f streamlit` once
killed the operator's own server.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEBAPP = ROOT / "webapp"
LOGS = ROOT / ".run"
WINDOWS = os.name == "nt"
UI_PORT = int(os.environ.get("UI_PORT", "8503"))
API_PORT = int(os.environ.get("API_PORT", "8787"))
READY_SECONDS = 30


# ---------------------------------------------------------------- helpers
def venv_python() -> str:
    """The project's own interpreter if the venv exists, else the one running us."""
    rel = ("Scripts", "python.exe") if WINDOWS else ("bin", "python")
    cand = ROOT.joinpath(".venv", *rel)
    return str(cand) if cand.exists() else sys.executable


def node_tool(name: str) -> str:
    """`npm` / `npx` — on Windows these are `npm.cmd` / `npx.cmd`; `which` finds them."""
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} is not installed or not on PATH — install Node.js first")
    return found


def port_pids(port: int) -> list[int]:
    """PIDs listening on `port`. Empty when the port is free (or no tool can tell)."""
    if WINDOWS:
        out = _run(["netstat", "-ano", "-p", "tcp"])
        pids: set[int] = set()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
                pids.add(int(parts[4]))
        return sorted(pids)
    if shutil.which("lsof"):
        out = _run(["lsof", "-nP", f"-tiTCP:{port}", "-sTCP:LISTEN"])
        return sorted({int(p) for p in out.split() if p.isdigit()})
    if shutil.which("ss"):
        out = _run(["ss", "-ltnpH", f"sport = :{port}"])
        pids = set()
        for chunk in out.split("pid="):
            digits = chunk.split(",")[0]
            if digits.isdigit():
                pids.add(int(digits))
        return sorted(pids)
    return []


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def kill(pid: int) -> None:
    """Windows has no SIGTERM for other processes; taskkill /T takes the whole tree,
    which matters because `npx next start` is a chain of three processes."""
    if WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)


def free_port(port: int) -> None:
    for pid in port_pids(port):
        print(f"freeing port {port} (pid {pid})")
        kill(pid)
        time.sleep(1)


def health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def fresh(path: Path) -> Path:
    """Unlink before rewriting. The operator's Mac keeps this repo in iCloud
    Drive, which evicts idle files; opening one for truncation blocks until the
    cloud sends it back — `TimeoutError: [Errno 60]` on .run/api.log on
    2026-08-25, AFTER both ports had been freed, so the app was simply down.
    A new inode never waits."""
    with contextlib.suppress(OSError):
        path.unlink()
    return path


def spawn(cmd: list[str], log: Path, cwd: Path, env: dict[str, str] | None = None) -> int:
    """Start a detached process whose output goes to `log`; survives this script
    and the terminal that ran it (nohup on unix, DETACHED_PROCESS on Windows)."""
    kwargs: dict = {}
    if WINDOWS:
        kwargs["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
                                   | subprocess.DETACHED_PROCESS)       # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    with open(fresh(log), "w", encoding="utf-8") as fh:
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=fh,
                                stderr=subprocess.STDOUT, env=env, **kwargs)
    return proc.pid


def tail(path: Path, n: int = 20) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


# ---------------------------------------------------------------- commands
def cmd_status() -> int:
    for port in (API_PORT, UI_PORT):
        pids = port_pids(port)
        print(f"port {port}: {' '.join(map(str, pids)) if pids else 'free'}")
    if health(UI_PORT):
        print("health: ok (UI is proxying the API)")
    else:
        print("health: NOT answering")
    return 0


def cmd_stop() -> int:
    free_port(UI_PORT)
    free_port(API_PORT)
    print("stopped")
    return 0


def cmd_start() -> int:
    LOGS.mkdir(exist_ok=True)
    free_port(API_PORT)
    free_port(UI_PORT)

    print(f"starting API on {API_PORT}…")
    api_pid = spawn([venv_python(), "-m", "uvicorn", "tradingagents.api:app",
                     "--host", "127.0.0.1", "--port", str(API_PORT)],
                    LOGS / "api.log", ROOT)
    fresh(LOGS / "api.pid").write_text(f"{api_pid}\n")

    print("building the UI…")
    with open(fresh(LOGS / "build.log"), "w", encoding="utf-8") as fh:
        build = subprocess.run([node_tool("npm"), "run", "build"], cwd=str(WEBAPP),
                               stdout=fh, stderr=subprocess.STDOUT)
    if build.returncode != 0:
        print(f"BUILD FAILED — see {LOGS / 'build.log'}")
        print(tail(LOGS / "build.log"))
        return 1

    print(f"starting UI on {UI_PORT}…")
    env = dict(os.environ, API_ORIGIN=f"http://127.0.0.1:{API_PORT}")
    ui_pid = spawn([node_tool("npx"), "next", "start", "-p", str(UI_PORT)],
                   LOGS / "ui.log", WEBAPP, env)
    fresh(LOGS / "ui.pid").write_text(f"{ui_pid}\n")

    for _ in range(READY_SECONDS):
        time.sleep(1)
        if health(UI_PORT):
            print(f"\n  ready:  http://localhost:{UI_PORT}\n")
            return 0
    print(f"the UI did not answer in {READY_SECONDS}s — see {LOGS / 'ui.log'}")
    print(tail(LOGS / "ui.log"))
    return 1


COMMANDS = {"start": cmd_start, "stop": cmd_stop, "status": cmd_status}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    action = args[0] if args else "start"
    if action not in COMMANDS:
        print(f"usage: {Path(sys.argv[0]).name} [start|stop|status]")
        return 2
    return COMMANDS[action]()


if __name__ == "__main__":
    raise SystemExit(main())
