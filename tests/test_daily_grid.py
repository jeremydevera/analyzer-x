"""The detached daily-grid runner.

The property that matters: a browser refresh must not lose the run OR its
progress. That means progress lives on disk, the process is tracked by PID,
every write is atomic, and a crashed run reports a verdict instead of
leaving a bar that never moves.
"""
import json
import os

import pytest

from tradingagents import daily_grid as dg


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(dg, "HOME", tmp_path)
    monkeypatch.setattr(dg, "STATE", tmp_path / "daily.json")
    monkeypatch.setattr(dg, "PIDFILE", tmp_path / "daily.pid")
    monkeypatch.setattr(dg, "JOBFILE", tmp_path / "job.json")
    yield


def test_state_survives_a_reader_that_arrives_mid_write():
    """Atomic writes: the page reads STATE on every render, and a partial
    file would blank the panel mid-run."""
    dg._atomic(dg.STATE, {"phase": "running", "frac": 0.4})
    assert dg.state()["frac"] == 0.4
    assert not list(dg.STATE.parent.glob("*.tmp")), "tmp file left behind"


def test_state_is_empty_not_crashing_when_absent_or_corrupt():
    assert dg.state() == {}
    dg.STATE.write_text("{not json")
    assert dg.state() == {}


def test_is_running_checks_the_pid_not_a_name():
    assert dg.is_running() is False
    dg.PIDFILE.write_text(str(os.getpid()))
    assert dg.is_running() is True
    dg.PIDFILE.write_text("999999999")        # a PID that cannot exist
    assert dg.is_running() is False
    dg.PIDFILE.write_text("not-a-pid")
    assert dg.is_running() is False


def test_main_writes_a_done_verdict_with_the_page_url(monkeypatch, tmp_path):
    from tradingagents import backtest_report as br

    seen = {}

    def fake_grid(coins, tfs, **kw):
        kw["progress"]("half way", 0.5)
        seen["called"] = (list(coins), list(tfs), kw.get("days"))
        return {"rows": [{"id": "X"}, {"id": "Y"}]}

    monkeypatch.setattr(br, "grid_from_store", fake_grid, raising=False)
    monkeypatch.setattr(br, "run_grid", fake_grid)
    monkeypatch.setattr(br, "write_report",
                        lambda p, payload, **kw: open(p, "w").write("<html>"))
    out = tmp_path / "page.html"
    job = tmp_path / "job.json"
    job.write_text(json.dumps({
        "coins": ["PI_USDT"], "tfs": ["1h"], "base": 5.0, "days": 365,
        "deployed": [], "out_path": str(out),
        "page_url": "app/static/bt/page.html", "title": "t", "note": "n"}))

    assert dg.main(["--job", str(job)]) == 0
    s = dg.state()
    assert s["done"] is True and s["phase"] == "done"
    assert s["rows"] == 2
    assert s["page_url"] == "app/static/bt/page.html"
    assert out.exists()
    assert seen["called"] == (["PI_USDT"], ["1h"], 365)


def test_main_marks_an_empty_grid_as_empty_not_done_silently(monkeypatch):
    from tradingagents import backtest_report as br

    monkeypatch.setattr(br, "grid_from_store",
                        lambda *a, **k: {"rows": []}, raising=False)
    monkeypatch.setattr(br, "run_grid", lambda *a, **k: {"rows": []})
    job = dg.HOME / "job.json"
    dg.HOME.mkdir(parents=True, exist_ok=True)
    job.write_text(json.dumps({
        "coins": ["PI_USDT"], "tfs": ["1h"], "base": 5.0, "days": 365,
        "deployed": [], "out_path": str(dg.HOME / "p.html"),
        "page_url": "u", "title": "t", "note": "n"}))
    assert dg.main(["--job", str(job)]) == 1
    assert dg.state()["phase"] == "empty"
    assert dg.state()["done"] is True


def test_a_crash_is_recorded_as_failed_with_its_message(monkeypatch):
    from tradingagents import backtest_report as br

    def boom(*a, **k):
        raise RuntimeError("venue said no")

    monkeypatch.setattr(br, "grid_from_store", boom, raising=False)
    monkeypatch.setattr(br, "run_grid", boom)
    job = dg.HOME / "job.json"
    dg.HOME.mkdir(parents=True, exist_ok=True)
    job.write_text(json.dumps({
        "coins": ["PI_USDT"], "tfs": ["1h"], "base": 5.0, "days": 365,
        "deployed": [], "out_path": str(dg.HOME / "p.html"),
        "page_url": "u", "title": "t", "note": "n"}))
    with pytest.raises(RuntimeError):
        dg.main(["--job", str(job)])
    s = dg.state()
    assert s["done"] is True and s["phase"] == "failed"
    assert "venue said no" in s["error"]
