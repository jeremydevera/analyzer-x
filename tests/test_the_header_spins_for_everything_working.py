"""Everything that is working turns the header's spinner, beside the bell —
not only a disk job.

Operator, Sep 23, 2026, three hours into a 99M-row rebuild of the Backtest v2
index that no screen showed: *"can you make animation for all that is
loading? if its indexing i should be seeing a loading beside the notification
icon"*. `/api/jobs` (the header's one poll) now also reports an index rebuild
of either store, the v1 indexer working off a backlog, and a GitHub run still
measuring — each as a running chip with the same spinner the disk jobs get.
"""
from __future__ import annotations

import re
from pathlib import Path

from tradingagents import api, rows_index as ri

ROOT = Path(__file__).resolve().parents[1]


def _quiet(monkeypatch):
    """No disk job, no indexer backlog, no GitHub run — so what is asserted is
    the activity under test and nothing this PC happens to be doing."""
    monkeypatch.setattr(api, "index_status", lambda pending=None: {
        "behind": 0, "stale": 0, "indexer_running": False})
    monkeypatch.setattr(api._CLOUD_STATUS, "get", lambda pending=None: {})
    monkeypatch.setattr(ri, "rebuild_progress", lambda db_path=None: {})


def test_a_rebuild_of_the_v2_index_is_a_running_chip(monkeypatch):
    _quiet(monkeypatch)
    def progress(db_path=None):
        if db_path == api._stores.V2.rows_db:
            return {"running": True, "store": "this", "pid": 24444,
                    "phase": "indexing 3 of 4: rows_coin", "pairs_done": 5003,
                    "pairs_total": 5003, "rows": 98_986_982}
        return {}
    monkeypatch.setattr(ri, "rebuild_progress", progress)
    got = api._background_activity()
    assert [g["kind"] for g in got] == ["rebuild_v2"]
    assert "indexing 3 of 4: rows_coin" in got[0]["now"]
    assert "5,003 of 5,003 pairs" in got[0]["now"] and "98,986,982 rows" in got[0]["now"]
    assert got[0]["pct"] is None, "every pair is loaded; 100% beside 'indexing' reads as finished"


def test_a_loading_rebuild_prints_its_pair_percent(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(ri, "rebuild_progress", lambda db_path=None: {
        "running": True, "store": "this", "pid": 1, "phase": "loading pairs",
        "pairs_done": 1250, "pairs_total": 5000, "rows": 10} if db_path == api._stores.V1.rows_db else {})
    got = api._background_activity()
    assert got[0]["kind"] == "rebuild" and got[0]["pct"] == 25


def test_a_legacy_rebuild_answers_for_both_stores_but_is_one_chip(monkeypatch):
    """A rebuild started before Sep 23, 2026 writes to the shared path and
    `rebuild_progress` returns it for either store; one process is one chip."""
    _quiet(monkeypatch)
    monkeypatch.setattr(ri, "rebuild_progress", lambda db_path=None: {
        "running": True, "store": "unknown", "pid": 24444,
        "phase": "verifying", "pairs_done": 5003, "pairs_total": 5003, "rows": 1})
    got = api._background_activity()
    assert len(got) == 1 and got[0]["kind"] == "rebuild"
    assert got[0]["now"].startswith("rebuilding a row index")


def test_a_finished_or_dead_rebuild_is_no_chip(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(ri, "rebuild_progress", lambda db_path=None: {
        "running": False, "store": "this", "pid": 1, "phase": "verifying"})
    assert api._background_activity() == []


def test_the_indexer_working_off_a_backlog_is_a_chip(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(api, "index_status", lambda pending=None: {
        "behind": 806, "stale": 40, "indexer_running": True})
    got = api._background_activity()
    assert [g["kind"] for g in got] == ["indexing"]
    # the store is NAMED since Sep 24, 2026 — "indexing N pair(s)" read as the
    # Backtest v2 run the operator had just been told was finished
    assert "Backtest (v1)" in got[0]["now"] and "846" in got[0]["now"], got[0]["now"]
    # a backlog with NO worker is not "working" — that is the stalled screen
    # RCA-2026-09-14-B was about, and a spinner would say the opposite
    monkeypatch.setattr(api, "index_status", lambda pending=None: {
        "behind": 806, "stale": 40, "indexer_running": False})
    assert api._background_activity() == []


def test_a_github_run_still_measuring_is_a_chip(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(api._CLOUD_STATUS, "get", lambda pending=None: {
        "run": {"id": 35776582134, "res": "1m"}, "conclusion": None,
        "shards": [{"status": "completed", "conclusion": "success"},
                   {"status": "in_progress"}, {"status": "in_progress"}]})
    got = api._background_activity()
    assert [g["kind"] for g in got] == ["github_v2"]
    assert got[0]["now"] == "GitHub measuring · 1 of 3 machine(s) finished"
    assert got[0]["pct"] == 33
    # finished: no chip; still being read for the first time: no chip either
    monkeypatch.setattr(api._CLOUD_STATUS, "get", lambda pending=None: {
        "run": {"id": 1}, "conclusion": "success", "shards": []})
    assert api._background_activity() == []
    monkeypatch.setattr(api._CLOUD_STATUS, "get", lambda pending=None: {
        "run": None, "reading": True, "shards": []})
    assert api._background_activity() == []


def test_the_jobs_route_carries_the_activity_and_never_raises(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(ri, "rebuild_progress", lambda db_path=None: (_ for _ in ()).throw(OSError("disk")))
    monkeypatch.setattr(api, "index_status", lambda pending=None: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(api._CLOUD_STATUS, "get", lambda pending=None: (_ for _ in ()).throw(RuntimeError("x")))
    assert api._background_activity() == []
    src = (ROOT / "tradingagents" / "api.py").read_text(encoding="utf-8")
    i = src.index("def jobs_all()")
    assert "running.extend(_background_activity())" in src[i:i + 1800]


def test_every_kind_the_header_can_receive_has_a_name_and_a_way_back():
    """A chip printing a raw kind ("pairbt_v2") is a label nobody asked for;
    every disk job kind and every activity kind is named and linked."""
    tsx = (ROOT / "webapp" / "src" / "components" / "header" / "RunningJobs.tsx"
           ).read_text(encoding="utf-8")
    names = dict(re.findall(r'^\s+(\w+): "([^"]+)",', tsx[tsx.index("const NAME"):], re.M))
    hrefs = dict(re.findall(r'^\s+(\w+): "([^"]+)",', tsx[tsx.index("const HREF"):tsx.index("const NAME")], re.M))
    kinds = set(api.JOB_KINDS) | {"rebuild", "rebuild_v2", "indexing", "github", "github_v2"}
    missing = sorted(k for k in kinds if k not in names or k not in hrefs)
    assert not missing, f"unnamed or unlinked in the header: {missing}"
    assert "animate-spin" in tsx, "the chip moves — a static label cannot say 'still working'"
    for k, href in hrefs.items():
        page = ROOT / "webapp" / "src" / "app" / "(admin)" / href.strip("/") / "page.tsx"
        assert page.exists(), f"{k} links to {href}, which has no page"
