"""A Backtest v2 collect brings the table up to its pair files
(RCA-2026-09-28-C).

Sep 28, 2026, after UPDATE ALL BACKTESTS on v2: 3,854 pairs on disk were
newer than the table, because v2 has no indexer and neither the live door nor
`collect_v2` filed anything — while the screen told the operator to press
UPDATE again.
"""
import inspect

from tradingagents import db_jobs, rows_index as ri


def _stub(monkeypatch, *, todo, running=False, held=""):
    calls = {"sync": 0, "spawn": 0}
    monkeypatch.setattr(ri, "stale_pairs", lambda *a, **k: ["p"] * todo)
    monkeypatch.setattr(ri, "sync", lambda **k: calls.__setitem__("sync", calls["sync"] + 1)
                        or {"pairs": todo})
    monkeypatch.setattr(ri, "rebuild_progress",
                        lambda *a, **k: {"running": running, "pairs_done": 10,
                                         "pairs_total": 5004})
    monkeypatch.setattr(ri, "write_available", lambda *a, **k: held)

    class _P:
        pid = 4242

    def popen(cmd, **kw):
        calls["spawn"] += 1
        calls["cmd"] = cmd
        return _P()

    monkeypatch.setattr(ri.subprocess, "Popen", popen)
    return calls


def test_nothing_waiting_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    calls = _stub(monkeypatch, todo=0)
    assert ri.file_after_collect() == "the table holds every measured pair"
    assert calls["sync"] == calls["spawn"] == 0


def test_a_small_backlog_is_synced_in_place(monkeypatch, tmp_path):
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    calls = _stub(monkeypatch, todo=28)
    assert ri.file_after_collect() == "filed 28 pair(s) into the table"
    assert calls["sync"] == 1 and calls["spawn"] == 0


def test_a_market_sized_backlog_starts_one_fresh_rebuild(monkeypatch, tmp_path):
    """3,854 pairs by sync is ~43 hours at 1.5 pairs/min; a fresh rebuild
    did all 5,004 v2 pairs in 73 minutes on Sep 24, 2026."""
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    calls = _stub(monkeypatch, todo=3854)
    said = ri.file_after_collect()
    assert calls["sync"] == 0 and calls["spawn"] == 1
    assert calls["cmd"][-3:] == ["-m", "tradingagents.rows_index", "--rebuild"]
    assert "3,854 pair(s)" in said and "pid 4242" in said
    assert (tmp_path / "rows_rebuild.log").exists(), "a long job writes a log"


def test_never_two_rebuilds(monkeypatch, tmp_path):
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    calls = _stub(monkeypatch, todo=3854, running=True)
    said = ri.file_after_collect()
    assert calls["spawn"] == 0 and "already running (10 of 5,004)" in said


def test_a_held_table_is_named_not_forced(monkeypatch, tmp_path):
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    calls = _stub(monkeypatch, todo=3854, held="the row index is locked by a cleanup")
    said = ri.file_after_collect()
    assert calls["spawn"] == 0 and "locked by a cleanup" in said


def test_the_v2_collect_files_after_it_says_finished():
    src = inspect.getsource(db_jobs._run_collect)
    i = src.index("_ri.file_after_collect()")
    assert 'if kind.endswith("_v2"):' in src[:i]
    # after the finished progress write, so a rebuild it starts does not see
    # this job as a writer on the disk
    assert src.index('"running": False, "run": run_id,\n                           "finished"') < i


def test_the_screen_no_longer_sends_the_operator_to_press_update_again():
    from pathlib import Path
    panel = (Path(__file__).resolve().parents[1]
             / "webapp/src/components/backtest/StrategiesPanel.tsx").read_text(encoding="utf-8")
    assert "press BACKTEST or UPDATE ALL BACKTESTS again`" not in panel
    assert "they are filed when GitHub's results finish copying in" in panel
