"""The sweep sizes itself to the memory the machine actually has free.

Operator, Aug 27, 2026, after the PC froze twice while they were away:
"could you add feature in app to detect what is free in my desktop and limit
the backtest if there are small ram?"

What made it necessary, measured on their 16 GB machine: eleven workers on a
1h/4h window peak at 150-180 MB each (1.8 GB together), but 9.1 GB was already
held by everything else, leaving ~4 GB. A 15m pair carries four times the bars
of a 1h pair, so the same eleven workers there are a different proposition
entirely -- and when RAM runs out Windows pages to a mechanical disk, which is
the freeze, not a crash.

The disk floor (DISK_FLOOR_GB) has guarded space this way since 2026-08-22;
memory gets the same two-part treatment: choose the worker count from what is
free at the START, and stop cleanly if it runs out MID-RUN, keeping every
finished pair for the supervisor to resume.
"""
from __future__ import annotations

import pytest

from tradingagents import db_jobs, portable, sysmon


# --------------------------------------------------------------- reading it
def test_the_machine_reports_its_memory():
    total, free = portable.ram_gb()
    assert total > 0.5, "a machine running this has more than half a gigabyte"
    assert 0 < free <= total


def test_unreadable_memory_is_zeros_not_a_guess(monkeypatch):
    """Every other portable helper degrades rather than inventing a number."""
    monkeypatch.setattr(portable, "_ram_windows", lambda: (0.0, 0.0))
    monkeypatch.setattr(portable, "_ram_unix", lambda: (0.0, 0.0))
    assert portable.ram_gb() == (0.0, 0.0)


def test_the_system_snapshot_carries_the_memory(monkeypatch):
    monkeypatch.setattr(portable, "ram_gb", lambda: (16.0, 6.5))
    got = sysmon.snapshot(force=True)
    assert got["ram_total_gb"] == 16.0
    assert got["ram_free_gb"] == 6.5
    assert got["ram_used_pct"] == 59.4        # (16-6.5)/16
    assert got["ram_kind"] in ("measured", "unknown")


def test_a_machine_that_cannot_report_memory_says_unknown(monkeypatch):
    monkeypatch.setattr(portable, "ram_gb", lambda: (0.0, 0.0))
    got = sysmon.snapshot(force=True)
    assert got["ram_kind"] == "unknown"
    assert got["ram_total_gb"] is None and got["ram_free_gb"] is None


# ------------------------------------------------------- choosing the workers
def test_the_worker_count_fits_the_free_memory():
    """(free - reserve) / per-worker, capped by the cores offered.

    Measured: a 1h/4h worker peaks near 0.16 GB, a 15m/30m one holds four
    times the bars. With the operator's 6.5 GB free and a 2 GB reserve, 1h
    keeps every core and 15m does not.
    """
    assert db_jobs.workers_for_ram(11, ["1h", "4h"], free_gb=6.5) == 11
    assert db_jobs.workers_for_ram(11, ["15m"], free_gb=6.5) == 9
    assert db_jobs.workers_for_ram(11, ["1h"], free_gb=4.1) == 10
    assert db_jobs.workers_for_ram(11, ["15m", "1h"], free_gb=4.1) == 4


def test_a_mixed_run_is_sized_for_its_heaviest_timeframe():
    """15m and 1h in one job: the 15m pairs decide the budget."""
    a = db_jobs.workers_for_ram(11, ["15m"], free_gb=5.0)
    assert db_jobs.workers_for_ram(11, ["1h", "15m", "4h"], free_gb=5.0) == a


def test_it_never_returns_zero_workers():
    """A tight machine measures slowly; it does not measure nothing."""
    assert db_jobs.workers_for_ram(11, ["15m"], free_gb=0.2) == 1
    assert db_jobs.workers_for_ram(11, ["1h"], free_gb=0.0) == 1


def test_it_never_exceeds_the_cores_offered():
    assert db_jobs.workers_for_ram(4, ["1h"], free_gb=64.0) == 4


def test_unknown_memory_leaves_the_core_count_alone(monkeypatch):
    """If the machine cannot say, the feature must not silently halve the run."""
    monkeypatch.setattr(portable, "ram_gb", lambda: (0.0, 0.0))
    assert db_jobs.workers_for_ram(11, ["15m"]) == 11


def test_the_reserve_and_the_per_worker_numbers_are_named():
    assert db_jobs.RAM_RESERVE_GB == 2.0
    assert db_jobs.RAM_PER_WORKER_GB["1h"] == 0.2
    assert db_jobs.RAM_PER_WORKER_GB["15m"] == 0.5
    assert db_jobs.RAM_FLOOR_GB == 1.0


# ---------------------------------------------------------- saying it out loud
def test_the_job_publishes_the_cap_and_why(monkeypatch, tmp_path):
    """label-must-match-data: a run using 4 of 11 cores must say WHY, or the
    panel reads as a machine that lost seven cores."""
    import inspect

    src = inspect.getsource(db_jobs._run_backtest_inner)
    assert "workers_for_ram(" in src, "the job must size itself"
    assert '"cores_why"' in src, "and publish the reason beside the number"
    assert '"cores_offered"' in src, "and what it would have used"


def test_the_reason_names_the_numbers():
    why = db_jobs.ram_reason(4, 11, ["15m"], free_gb=4.1)
    for piece in ("4", "11", "4.1", "2.0", "0.5"):
        assert piece in why, f"{piece!r} missing from {why!r}"
    assert db_jobs.ram_reason(11, 11, ["1h"], free_gb=6.5) == "", \
        "no reduction, nothing to explain"


# ----------------------------------------------------------- the hard floor
def test_the_floor_stops_the_run_the_way_low_disk_does():
    """Under RAM_FLOOR_GB the job stops cleanly — every finished pair kept,
    the bell rung, the supervisor free to resume — exactly as the disk floor
    has behaved since 2026-08-22."""
    import inspect

    src = inspect.getsource(db_jobs)
    assert "class _LowRam(Exception)" in src
    # inside the progress callback -- the place the disk floor is checked on
    # every finished pair, not the supervisor's pre-flight check
    inner = inspect.getsource(db_jobs._run_backtest_inner)
    i = inner.index("if free_gb() < DISK_FLOOR_GB:")
    window = inner[i:i + 500]
    assert "_LowRam(" in window, "the memory check belongs beside the disk one"
    h = src.index("except _LowRam as exc:")
    handler = src[h:h + 900]
    assert '"paused": True' in handler
    assert "low memory" in handler
    assert "finished pair is kept" in handler


def test_the_floor_is_reached_only_when_memory_is_really_gone(monkeypatch):
    monkeypatch.setattr(portable, "ram_gb", lambda: (16.0, 0.4))
    assert db_jobs.ram_exhausted() is True
    monkeypatch.setattr(portable, "ram_gb", lambda: (16.0, 3.0))
    assert db_jobs.ram_exhausted() is False
    # a machine that cannot report memory never pauses on it
    monkeypatch.setattr(portable, "ram_gb", lambda: (0.0, 0.0))
    assert db_jobs.ram_exhausted() is False
