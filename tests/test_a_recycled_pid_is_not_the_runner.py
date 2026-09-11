"""A pid is not an identity. The run lock is.

`Sep 11, 2026 9:35pm` — Windows Update restarted this PC (TrustedInstaller,
event 1074, "Operating System: Upgrade"). The runner died with it, leaving
`auto_trade.pid` holding **9364**. By `Sep 12, 2026` that pid was alive again
and belonged to **NVIDIA Overlay**.

`runner_pid()` returned any pid that was alive, so at that moment:

* `start_runner()` would have found "an existing runner", returned **9364**,
  and STARTED NOTHING. The Trade tab would have reported success while the
  runner stayed down — CLAUDE.md, *a job that cannot start must SAY SO*.
* `stop_runner()` would have sent **SIGTERM to NVIDIA Overlay**, a process
  this project has no business touching. The comment above it says "never by
  process name" precisely to avoid killing a stranger; by pid was not safer.

The runner already had a real identity and nobody was asking it. `main()`
takes an exclusive lock on `auto_trade.lock` and holds it for the life of the
process, and nothing else in the project opens that file. So a recorded pid
counts as THE RUNNER only when the lock is held too.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time

import pytest

from tradingagents import auto_trader as at, portable


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "PID_PATH", tmp_path / "auto_trade.pid")
    monkeypatch.setattr(at, "LOCK_PATH", tmp_path / "auto_trade.lock")
    monkeypatch.setattr(at, "WANT_PATH", tmp_path / "auto_trade.WANT")
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    return tmp_path


# ------------------------------------------------------------- the incident
def test_a_live_pid_that_is_not_ours_is_not_the_runner(paths):
    """9364 exactly: alive, recorded, and somebody else's."""
    at.PID_PATH.write_text(str(os.getpid()), encoding="utf-8")   # alive
    assert portable.pid_alive(os.getpid())
    assert not at.run_lock_held(), "nothing holds the run lock in this test"
    assert at.runner_pid() is None, (
        "a live pid with no run lock is a RECYCLED pid — this is what would "
        "have reported NVIDIA Overlay as the trading runner")


def test_stop_does_not_signal_a_process_that_is_not_the_runner(paths, monkeypatch):
    """The dangerous half. `stop_runner` must send NOTHING."""
    at.PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    killed: list[int] = []
    monkeypatch.setattr(at.os, "kill", lambda pid, sig: killed.append(pid))
    assert at.stop_runner() is False
    assert killed == [], "SIGTERM went to a stranger's pid"
    assert not at.PID_PATH.exists(), "the stale pid file is cleared"


def test_start_actually_starts_when_the_pid_is_stale(paths, monkeypatch):
    """The quiet half: the button reported the stranger's pid as success."""
    at.PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    spawned: list[list] = []

    class _Proc:
        pid = 4242

    monkeypatch.setattr(at.subprocess, "Popen",
                        lambda cmd, **kw: spawned.append(cmd) or _Proc())
    got = at.start_runner()
    assert spawned, "start_runner returned without spawning anything"
    assert got == 4242
    assert at.PID_PATH.read_text(encoding="utf-8").strip() == "4242"


# ------------------------------------------------ the lock is a real identity
def test_a_real_runner_holding_the_lock_is_found(paths):
    """Cross-process, with a real lock — the case the fix must NOT break."""
    script = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(os.getcwd())!r})
        from tradingagents import portable
        fh = open({str(at.LOCK_PATH)!r}, "w")
        portable.lock_exclusive(fh, blocking=False)
        print("held", flush=True)
        time.sleep(30)
    """)
    child = subprocess.Popen([sys.executable, "-c", script],
                             stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "held"
        at.PID_PATH.write_text(str(child.pid), encoding="utf-8")
        deadline = time.time() + 5
        while time.time() < deadline and not at.run_lock_held():
            time.sleep(0.05)
        assert at.run_lock_held(), "a held lock must be visible across processes"
        assert at.runner_pid() == child.pid
    finally:
        child.kill()
        child.wait(timeout=10)
    # and the moment it dies, the lock frees and the pid stops counting
    deadline = time.time() + 5
    while time.time() < deadline and at.run_lock_held():
        time.sleep(0.05)
    assert not at.run_lock_held()
    assert at.runner_pid() is None


def test_the_runner_can_still_recognise_ITSELF(paths):
    """`main`'s `finally` clears the pid file only when `runner_pid()` is its
    own. The runner holds the lock on another handle in the SAME process, and
    that must read as held — measured, because per-handle lock semantics are
    exactly the kind of thing to assume wrongly."""
    at.PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    fh = open(at.LOCK_PATH, "w")                       # noqa: SIM115
    portable.lock_exclusive(fh, blocking=False)
    try:
        assert at.run_lock_held(), \
            "a second handle in our own process must still see the lock"
        assert at.runner_pid() == os.getpid()
    finally:
        portable.unlock(fh)
        fh.close()


def test_a_starting_runner_does_not_refuse_itself(paths):
    """`main` checks `runner_pid()` BEFORE taking the lock. With no lock held
    and no pid recorded there is no other runner, and it must proceed."""
    assert at.runner_pid() is None
    assert not at.run_lock_held()


# ------------------------------------------------------------------- details
def test_the_check_never_truncates_the_lock_file(paths):
    """Opening the lock file "w" would truncate a file another process is
    holding a byte range in. The probe opens append-plus."""
    at.LOCK_PATH.write_text("keep me", encoding="utf-8")
    at.run_lock_held()
    assert at.LOCK_PATH.read_text(encoding="utf-8") == "keep me"


def test_no_lock_file_at_all_means_no_runner(paths):
    assert not at.LOCK_PATH.exists()
    assert at.run_lock_held() is False
    at.PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    assert at.runner_pid() is None


def test_a_dead_pid_is_still_refused_without_touching_the_lock(paths):
    """The original check has to survive: garbage and dead pids answer None."""
    at.PID_PATH.write_text("999999999", encoding="utf-8")
    assert at.runner_pid() is None
    at.PID_PATH.write_text("not a number", encoding="utf-8")
    assert at.runner_pid() is None


def test_both_halves_are_required_not_either(paths):
    """An OR here would be the same bug wearing a lock."""
    import inspect

    src = inspect.getsource(at.runner_pid)
    assert "run_lock_held()" in src and "pid_alive" in src
    assert " or run_lock_held" not in src, "both must be required"
