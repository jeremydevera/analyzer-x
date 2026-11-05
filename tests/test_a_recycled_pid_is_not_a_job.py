"""A job's pid that Windows gave to another program is not that job.

Nov 05, 2026: the daily UPDATE ALL BACKTESTS started at 5:18:57am and wrote
`db_btupdate_v2.pid` = 19776; the power went at 5:20am (Kernel-Power 41) and
killed it. At 5:25:33am Windows gave pid 19776 to Chrome. From then on
`db_jobs.status("btupdate_v2")` said RUNNING — its progress file said running
and pid 19776 was alive — so the cloud autopilot could not collect a finished
run ("btupdate_v2 is running — one job at a time"), the daily update would not
press itself ("UPDATE ALL BACKTESTS is already running"), and a dead job was
never resumed. A process born AFTER its pid file was written cannot be the
process the file names (RCA-2026-11-05-D).
"""

import json
import os
import subprocess
import sys
import time

import pytest

from tradingagents import db_jobs as dj
from tradingagents import portable


@pytest.fixture
def stranger():
    """A real live process, started now — the 'Chrome' of the story."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        yield proc.pid
    finally:
        proc.kill()
        proc.wait()


def _job(kind: str, pid: int, pid_written_at: float) -> None:
    f = dj.FILES[kind]
    f["progress"].write_text(json.dumps(
        {"running": True, "started": int(pid_written_at), "done": 0,
         "total": 0, "now": "reading the exchange's market"}))
    f["pid"].write_text(str(pid))
    os.utime(f["pid"], (pid_written_at, pid_written_at))


def test_the_process_start_time_is_read():
    born = portable.pid_started(os.getpid())
    assert born is not None, "this platform must say when a process started"
    assert time.time() - 86400 < born <= time.time() + 1


def test_a_missing_process_has_no_start_time():
    assert portable.pid_started(999999) is None
    assert portable.pid_started(0) is None
    assert portable.pid_started("garbage") is None


def test_a_pid_given_to_a_later_program_is_not_the_job(stranger):
    # the pid file was written ten minutes before this process existed
    _job("btupdate_v2", stranger, time.time() - 600)
    assert portable.pid_alive(stranger), "the stranger is alive"
    st = dj.status("btupdate_v2")
    assert st["running"] is False, (
        "a process started after the job's pid file was written is another "
        "program that inherited the number, not the job")
    assert dj.died_unfinished("btupdate_v2") is True, (
        "the dead job must be seen as cut off, so the supervisor resumes it")


def test_the_job_s_own_process_still_reads_as_running(stranger):
    # the pid file written just after the process started, as start() does
    _job("btupdate_v2", stranger, time.time() + 1)
    assert dj.status("btupdate_v2")["running"] is True
    assert dj.died_unfinished("btupdate_v2") is False
