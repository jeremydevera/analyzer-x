"""A crashed sweep must restart itself.

The operator, after a 3,960-pair run died at 11.8% and stayed dead for hours:
"if it fails it should have automatic retry and you did not even think of it".
Per-pair checkpointing was already there, so a restart resumes — nothing ever
did the restarting.
"""

import json
import os

import pytest

from tradingagents import db_jobs as dj


@pytest.fixture
def crashed(monkeypatch):
    """A job whose progress says running while its pid is long gone."""
    f = dj.FILES["backtest"]
    f["progress"].write_text(json.dumps({"running": True, "done": 466,
                                         "total": 3960, "now": "AXS 15m"}))
    f["spec"].write_text(json.dumps({"coins": ["BTC_USDT"], "tfs": ["1h"],
                                     "base": 5.0, "days": 365, "fresh": True}))
    f["pid"].write_text("999999")            # a pid that cannot be alive
    dj.RETRY_FILE.write_text("{}")
    started = []
    monkeypatch.setattr(dj, "start",
                        lambda kind, spec: started.append((kind, spec)) or 4242)
    monkeypatch.setattr(dj, "free_gb", lambda path=None: 50.0)
    return started


def test_a_crashed_job_is_restarted_from_its_checkpoint(crashed):
    got = dj.resume_if_died("backtest")
    assert got["resumed"] is True and got["pid"] == 4242
    kind, spec = crashed[0]
    assert kind == "backtest"
    assert spec["fresh"] is False, (
        "a crash is not a click on BACKTEST — resuming must not start over")
    assert spec["coins"] == ["BTC_USDT"], "it must reuse the original spec"


def test_a_finished_job_is_never_restarted(crashed):
    dj.FILES["backtest"]["progress"].write_text(json.dumps(
        {"running": False, "rows": 41190, "finished": 1787326445}))
    assert dj.resume_if_died("backtest")["resumed"] is False
    assert not crashed, "it restarted a job that had already finished"


def test_a_job_stopped_by_the_operator_is_never_restarted(crashed):
    dj.FILES["backtest"]["progress"].write_text(json.dumps(
        {"running": False, "stopped": True, "finished": 1787326445}))
    assert dj.resume_if_died("backtest")["resumed"] is False
    assert not crashed


def test_a_live_job_is_left_alone(crashed):
    dj.FILES["backtest"]["pid"].write_text(str(os.getpid()))   # very much alive
    assert dj.resume_if_died("backtest")["resumed"] is False
    assert not crashed, "it restarted a job that was still running"


def test_it_will_not_restart_into_the_disk_that_killed_it(crashed, monkeypatch):
    """The sweep died BECAUSE the volume filled. Relaunching into 0.4 GB just
    kills it again, and the crash log spends the last of the space."""
    monkeypatch.setattr(dj, "free_gb", lambda path=None: 0.4)
    got = dj.resume_if_died("backtest")
    assert got["resumed"] is False
    assert "0.4 GB free" in got["why"] and "waiting" in got["why"]
    assert not crashed
    # and it resumes by itself once there is room again
    monkeypatch.setattr(dj, "free_gb", lambda path=None: 50.0)
    assert dj.resume_if_died("backtest")["resumed"] is True


def test_retries_are_bounded(crashed):
    for i in range(dj.MAX_RETRIES):
        assert dj.resume_if_died("backtest")["attempt"] == i + 1
    got = dj.resume_if_died("backtest")
    assert got["resumed"] is False and "gave up" in got["why"], (
        "a crash loop that re-reads the same broken state looks like progress")
    assert len(crashed) == dj.MAX_RETRIES


def test_a_manual_start_gets_a_fresh_budget(crashed):
    for _ in range(dj.MAX_RETRIES):
        dj.resume_if_died("backtest")
    assert dj.resume_if_died("backtest")["resumed"] is False
    dj.clear_retries("backtest")
    assert dj.resume_if_died("backtest")["resumed"] is True


def test_the_sweep_stops_cleanly_before_the_disk_is_gone():
    """A fatal OSError mid-write loses the pair in flight and writes no
    terminal record at all — the operator found the dead job hours later."""
    import inspect

    src = inspect.getsource(dj._run_backtest_inner)
    assert "free_gb() < DISK_FLOOR_GB" in src, "no guard before the disk goes"
    assert "_LowDisk" in src
    # the terminal record has to say paused, not failed, and keep the work
    assert '"paused": True' in src
    assert "resumes by" in src


def test_the_api_runs_the_supervisor():
    import inspect

    from tradingagents import api

    src = inspect.getsource(api._keep_the_row_index_current)
    assert "resume_if_died" in src, "nothing is watching for crashed jobs"
