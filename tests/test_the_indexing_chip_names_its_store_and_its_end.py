"""The header's "indexing" spinner says WHICH store and HOW LONG, measured.

`Sep 24, 2026`, the operator, told Backtest v2 was finished: *"why is it still
indexing on upper right. fix this ui bug its confusing, if its finished i dont
want to see loading"*. The chip was Backtest **v1**'s re-file — 5,341
coin-timeframes, one at a time, 18-73 minutes each (about 194 days at the
measured pace) — and it said only "indexing", so it read as the v2 run.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def api(monkeypatch, tmp_path):
    from tradingagents import api, rows_index as ri

    log = tmp_path / "rows_index.log"
    log.write_text(
        "[rows-index] +1 pairs (24,800 rows) in 3490.16s, 83 left\n"
        "[rows-index] +1 pairs (10,120 rows) in 1090.8s, 82 left\n"
        "[rows-index] built rows_wr4 in 3247s\n"
        "[rows-index] +1 pairs (24,354 rows) in 4411.6s, 81 left\n",
        encoding="utf-8")
    monkeypatch.setattr(ri, "LOGFILE", log)
    monkeypatch.setattr(api, "_PACE_CACHE", {"at": 0.0, "per": None})
    monkeypatch.setattr(api, "index_status", lambda pending=None: {
        "behind": 2, "stale": 5339, "indexer_running": True})
    monkeypatch.setattr(ri, "rebuild_progress", lambda db=None: {})
    monkeypatch.setattr(api._CLOUD_STATUS, "get", lambda pending=None: {})
    return api


def _chip(api):
    got = [c for c in api._background_activity() if c["kind"] == "indexing"]
    assert len(got) == 1, got
    return got[0]


def test_it_names_the_v1_store(api):
    chip = _chip(api)
    assert "Backtest (v1)" in chip["now"], chip["now"]
    assert "5,341" in chip["now"]


def test_the_time_left_is_the_measured_pace_times_the_backlog(api):
    """(3490.16 + 1090.8 + 4411.6) / 3 passes = 2997.5 s a coin, x 5,341."""
    chip = _chip(api)
    per = (3490.16 + 1090.8 + 4411.6) / 3
    assert chip["eta_s"] == pytest.approx(per * 5341, rel=1e-6)
    assert "50 min each" in chip["now"], chip["now"]


def test_a_build_line_is_not_a_filing_pass(api):
    """"built rows_wr4 in 3247s" is an index build, not a coin filed."""
    assert api._index_pace_s() == pytest.approx((3490.16 + 1090.8 + 4411.6) / 3)


def test_no_pace_yet_says_so_instead_of_guessing(api, monkeypatch, tmp_path):
    from tradingagents import rows_index as ri

    empty = tmp_path / "empty.log"
    empty.write_text("[rows-index] up (pid 1): 5428 indexed\n", encoding="utf-8")
    monkeypatch.setattr(ri, "LOGFILE", empty)
    chip = _chip(api)
    assert chip["eta_s"] is None
    assert "no filing pass has finished" in chip["eta_why"]


def test_the_header_chip_names_the_store_too():
    src = (REPO / "webapp/src/components/header/RunningJobs.tsx").read_text(encoding="utf-8")
    assert 'indexing: "indexing Backtest v1"' in src


def test_time_left_past_a_day_prints_days():
    """~5,300 hours printed as "5341h 0m"; nobody reads that as seven months."""
    src = (REPO / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    fn = src[src.index("export function fmtLeft"):]
    fn = fn[:fn.index("\n}") + 2]
    assert "86400" in fn and "d ${dh}h" in fn, fn
