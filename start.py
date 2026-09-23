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
# How long a restart waits for downloads in flight before cutting them. The
# operator's own 30-day window CSV measured 67-110 s warm on Sep 24, 2026 and
# the cold one had run more than six minutes when a restart killed it.
RESTART_WAIT_S = 900


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


def kill(pid: int, *, tree: bool) -> None:
    """Windows has no SIGTERM for other processes, so it is taskkill -- and the
    choice of /T decides who else dies. `tree=True` takes the whole process tree,
    right for the UI port: `npx next start` is a chain of three processes.
    `tree=False` kills the one pid, right for the API port: its children are
    the DETACHED JOBS (db_jobs backtest/download/stratbt, rows_index), each
    checkpointed, supervised and pidfile-guarded. On 2026-08-25 3:55pm a /T on
    the API killed a 4,985-pair backtest 60 pairs in, and the supervisor logged
    "backtest restarted after a crash". The Mac never had this: `kill <pid>` is
    one process, and the jobs live through an app restart there."""
    if WINDOWS:
        cmd = ["taskkill", "/PID", str(pid)] + (["/T"] if tree else []) + ["/F"]
        subprocess.run(cmd, capture_output=True)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)


def free_port(port: int, *, tree: bool) -> None:
    for pid in port_pids(port):
        print(f"freeing port {port} (pid {pid}{', with its tree' if tree else ''})")
        kill(pid, tree=tree)
        time.sleep(1)


def health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def downloads_in_flight(port: int = API_PORT) -> list | None:
    """The downloads the API is streaming right now (GET /api/system/busy);
    None when the API is not answering or is too old to say — then there is
    nothing a restart could be cutting that we could know about."""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/system/busy", timeout=3) as r:
            import json as _json
            return list(_json.loads(r.read().decode("utf-8")).get("downloads") or [])
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _say(msg: str) -> None:
    """print() that cannot crash a restart on a console that lacks a
    character (a cp1252 pipe has no "≥"); a raise here would abort the
    restart after half of it had run."""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(msg.encode(enc, "replace").decode(enc, "replace"), flush=True)


def wait_for_downloads(max_s: float = RESTART_WAIT_S, *, sleep=time.sleep,
                       clock=time.time, port: int = API_PORT) -> bool:
    """Wait until no download is being streamed, up to `max_s`.

    A RESTART NEVER CUTS A DOWNLOAD IN FLIGHT (RCA-2026-09-24-D). The
    operator's CSV started at Sep 24, 2026 5:01am and died when the app was
    restarted under it; the UI's proxy told them "Internal Server Error".
    True when nothing is (or can be seen) in flight; False when it gave up
    and the caller is about to cut something — said out loud either way."""
    t0 = clock()
    said = False
    while True:
        got = downloads_in_flight(port)
        if not got:
            if said:
                _say("  the download(s) finished — restarting now")
            return True
        if not said:
            names = "; ".join(f"{d.get('what')} ({d.get('rows', 0):,} rows so far, "
                              f"since {d.get('since')})" for d in got)
            _say(f"waiting for {len(got)} download(s) to finish before "
                 f"stopping the API — {names} (up to {int(max_s // 60)} min; "
                 f"`start.py start --now` skips the wait)")
            said = True
        if clock() - t0 >= max_s:
            _say(f"  still downloading after {int(max_s // 60)} min — restarting "
                 f"anyway; that download will have to be pressed again")
            return False
        sleep(5)


def keep_previous(path: Path) -> Path:
    """The last run's log becomes `<name>.prev<ext>` instead of being deleted.

    A restart deleted `api.log` and `ui.log`, so the one record of what the
    previous API did — including the operator's download that a restart cut
    at 5:01am on Sep 24, 2026 — was gone before anyone could read it. A rename
    is a new inode for the fresh log, so the iCloud reason `fresh()` exists
    for still holds."""
    prev = path.with_name(path.stem + ".prev" + path.suffix)
    with contextlib.suppress(OSError):
        prev.unlink()
    with contextlib.suppress(OSError):
        path.rename(prev)
    return path


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
    with open(keep_previous(log), "w", encoding="utf-8") as fh:
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


def cmd_stop(now: bool = False) -> int:
    if not now:
        wait_for_downloads()
    free_port(UI_PORT, tree=True)
    free_port(API_PORT, tree=False)
    print("stopped")
    return 0


def cmd_start(now: bool = False) -> int:
    LOGS.mkdir(exist_ok=True)
    if not now:
        wait_for_downloads()
    free_port(API_PORT, tree=False)
    free_port(UI_PORT, tree=True)

    print(f"starting API on {API_PORT}…")
    # UTF-8 everywhere: Windows' default text encoding is cp1252, and the
    # store's JSON/progress files carry em dashes and coin names. Every job the
    # API spawns inherits this.
    # UNBUFFERED, so the log is complete and in order when it is read — a
    # restart is often exactly when someone needs its last lines
    api_env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    api_pid = spawn([venv_python(), "-m", "uvicorn", "tradingagents.api:app",
                     "--host", "127.0.0.1", "--port", str(API_PORT)],
                    LOGS / "api.log", ROOT, api_env)
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
    words = [a for a in args if not a.startswith("--")]
    action = words[0] if words else "start"
    if action not in COMMANDS:
        print(f"usage: {Path(sys.argv[0]).name} [start|stop|status] [--now]")
        return 2
    if action in ("start", "stop"):
        return COMMANDS[action](now="--now" in args)
    return COMMANDS[action]()


if __name__ == "__main__":
    raise SystemExit(main())
