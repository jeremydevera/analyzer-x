"""The app must start and load data on Windows as well as macOS/Linux.

On 2026-08-25 the operator cloned the repo on a Windows PC and every storage
screen said "Storage unreadable": `import fcntl` at the top of market_sweep.py
raised ModuleNotFoundError, so the module — and everything importing it —
never loaded. The same code used `os.kill(pid, 0)` as a liveness probe, which
on Windows TERMINATES the process. Everything OS-specific now lives in
tradingagents/portable.py, and this file keeps it there.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import time

import pytest

from tradingagents import portable

FORBIDDEN = re.compile(
    r"^\s*(import|from)\s+(fcntl|msvcrt)\b"
    r"|os\.statvfs\("
    r"|os\.kill\(\s*\w+\s*,\s*0\s*\)"
    r"|signal\.SIGKILL")


def test_no_module_outside_portable_names_a_unix_only_api():
    offenders = []
    for f in pathlib.Path("tradingagents").rglob("*.py"):
        if f.name == "portable.py":
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if FORBIDDEN.search(line):
                offenders.append(f"{f}:{i}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_the_lock_is_exclusive_across_two_handles(tmp_path):
    """Two open() calls on the same file are two lock owners — the shape of the
    BACKTEST-vs-UPDATE race the pair lock exists for."""
    path = tmp_path / "x.lock"
    a = path.open("w")
    b = path.open("w")
    try:
        portable.lock_exclusive(a, blocking=False)
        with pytest.raises(OSError):
            portable.lock_exclusive(b, blocking=False)
        portable.unlock(a)
        portable.lock_exclusive(b, blocking=False)     # free now
        portable.unlock(b)
    finally:
        a.close()
        b.close()


def test_pid_alive_sees_this_process_and_not_a_finished_one():
    assert portable.pid_alive(os.getpid()) is True
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()                                  # reaped: the pid is free again
    for _ in range(20):                          # Windows takes a moment to close it
        if not portable.pid_alive(gone.pid):
            break
        time.sleep(0.05)
    assert portable.pid_alive(gone.pid) is False
    assert portable.pid_alive(None) is False
    assert portable.pid_alive("garbage") is False
    assert portable.pid_alive(0) is False
    assert portable.pid_alive(-1) is False


def test_child_pids_lists_a_child_we_spawned():
    kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        for _ in range(40):
            if kid.pid in portable.child_pids(os.getpid()):
                break
            time.sleep(0.05)
        assert kid.pid in portable.child_pids(os.getpid())
    finally:
        kid.kill()
        kid.wait()


def test_kill_hard_ends_a_process():
    kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    portable.kill_hard(kid.pid)
    assert kid.wait(timeout=5) != 0
    assert portable.pid_alive(kid.pid) is False


def test_disk_free_mb_is_a_positive_number_even_for_a_missing_path(tmp_path):
    assert portable.disk_free_mb(tmp_path) > 0
    assert portable.disk_free_mb(tmp_path / "not" / "yet" / "there") > 0
