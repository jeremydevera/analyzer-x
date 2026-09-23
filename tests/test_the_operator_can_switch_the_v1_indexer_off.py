"""The operator switched the v1 indexer off, and it STAYS off.

`Sep 24, 2026`: *"stop the v1 i dont need it anymore"* — about the v1 indexer
re-filing 5,340 coin-timeframes at ~52 min each (~194 days), whose spinner
sat in the header. Killing it is not stopping it: the API's supervisor
restarts a dead indexer every 30 s (the Sep 14 rule). `rows_index.OFF` is the
switch, and every door respects it. Nothing is deleted.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def off(tmp_path, monkeypatch):
    from tradingagents import rows_index as ri

    f = tmp_path / "rows_index.OFF"
    monkeypatch.setattr(ri, "OFF_FILE", f)
    return ri, f


def test_on_until_the_file_exists(off):
    ri, f = off
    assert ri.indexer_switched_off() == ""
    f.write_text("switched off by the operator, Sep 24, 2026", encoding="utf-8")
    assert "Sep 24, 2026" in ri.indexer_switched_off()


def test_the_supervisor_cannot_restart_it(off, monkeypatch):
    ri, f = off
    f.write_text("off", encoding="utf-8")
    monkeypatch.setattr(ri, "_running_elsewhere", lambda: False)
    monkeypatch.setattr(ri.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("a switched-off indexer was spawned"),
                        raising=False)
    import subprocess
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: pytest.fail("a switched-off indexer was spawned"))
    assert ri.spawn_indexer() is None


def test_the_catch_up_button_refuses_and_says_why(off, monkeypatch):
    from tradingagents import api

    ri, f = off
    f.write_text("switched off by the operator", encoding="utf-8")
    monkeypatch.setattr(ri, "status", lambda *a, **k: {
        "behind": 2, "stale": 5340, "indexer_off": ri.indexer_switched_off()})
    got = api.strategies_reindex()
    assert got["started"] is False
    assert "switched off" in got["why"]


def test_no_spinner_for_a_worker_that_is_switched_off(off, monkeypatch):
    from tradingagents import api

    ri, _ = off
    monkeypatch.setattr(api, "index_status", lambda pending=None: {
        "behind": 2, "stale": 5340, "indexer_running": True,
        "indexer_off": "switched off by the operator"})
    monkeypatch.setattr(ri, "rebuild_progress", lambda db=None: {})
    monkeypatch.setattr(api._CLOUD_STATUS, "get", lambda pending=None: {})
    assert [c for c in api._background_activity() if c["kind"] == "indexing"] == []


def test_the_screen_says_switched_off_not_dead():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "webapp" / "src" /
           "components" / "backtest" / "StrategiesPanel.tsx").read_text(encoding="utf-8")
    i = src.index("idx.indexer_off ? (")
    j = src.index("nothing is filling this")
    assert i < j, "the switched-off sentence must win over the red 'dead' one"
    assert "nothing was deleted" in src


def test_a_switched_off_indexer_exits_before_any_work(off, monkeypatch):
    """Each watchdog respawn used to run ensure() and status() — minutes of
    disk — before it read the switch."""
    ri, f = off
    f.write_text("off", encoding="utf-8")
    for name in ("take_run_lock", "_ensure_or_wait", "status", "start_keeping_up"):
        monkeypatch.setattr(ri, name,
                            lambda *a, _n=name, **k: pytest.fail(f"{_n} ran while off"))
    assert ri.main([]) == 0
