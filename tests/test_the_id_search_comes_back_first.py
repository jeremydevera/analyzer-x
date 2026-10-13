"""After a rebuild, the index behind the id search is built FIRST
(RCA-2026-10-13-E).

Oct 13, 2026: Backtest v2's table was rebuilt and swapped in at 2:57pm
(22,747,944 rows). The new file carries the kept four indexes; the swap then
built them in INDEX_DDL order — rows_wr2 441 s, rows_wr3 112 s, rows_wr4
161 s, rows_pr2 532 s — and rows_id (103 s) LAST, so every search by id
answered "needs the rows_id index; the build has just started" until 3:21pm:
24 minutes. The operator's *"why is this taking too long"* the same morning
was this wait, and the id they copy from their practice trades is the one
thing they search by.
"""
import json

from tradingagents import rows_index as ri


def test_the_build_order_puts_the_id_index_first():
    names = ["rows_wr2", "rows_wr3", "rows_wr4", "rows_pr2", "rows_id"]
    assert ri.build_order(names) == ["rows_id", "rows_wr2", "rows_wr3", "rows_wr4",
                                     "rows_pr2"]
    assert ri.build_order(["rows_wr2", "rows_wr4"]) == ["rows_wr2", "rows_wr4"]


def test_a_rebuild_starts_the_id_index_before_any_other(monkeypatch):
    """`build_missing_indexes` starts the FIRST missing index it can — the
    one a swap starts — so `missing_indexes` must list rows_id first."""
    have = set(ri._kept_index_names())
    monkeypatch.setattr(ri, "has_index", lambda n: n in have)
    monkeypatch.setattr(ri, "forget_indexes", lambda: None)
    got = ri.missing_indexes()
    assert got[0] == "rows_id" and "rows_wr2" in got


def test_the_queue_builds_the_id_index_next(tmp_path, monkeypatch):
    """A queue written in the old order still builds rows_id first."""
    live = tmp_path / "rows.db"
    live.write_text("x", encoding="utf-8")
    started = []
    monkeypatch.setattr(ri, "has_index", lambda n: False)
    monkeypatch.setattr(ri, "build_running", lambda name=None: "")
    monkeypatch.setattr(ri, "forget_indexes", lambda: None)
    monkeypatch.setattr(ri, "_build_index", lambda n: started.append(n) or True)
    with ri.using_db(live):
        ri._index_queue_path().write_text(json.dumps(
            {"names": ["rows_wr3", "rows_wr4", "rows_pr2", "rows_id"], "tries": {}}),
            encoding="utf-8")
        said = ri.continue_index_queue()
    assert started == ["rows_id"]
    assert said.startswith("building rows_id again")


def test_remembering_a_swap_writes_the_id_index_first(tmp_path, monkeypatch):
    live = tmp_path / "rows.db"
    live.write_text("x", encoding="utf-8")
    monkeypatch.setattr(ri, "has_index", lambda n: False)
    with ri.using_db(live):
        ri._remember_indexes(["rows_wr2", "rows_wr4", "rows_id"])
        got = json.loads(ri._index_queue_path().read_text(encoding="utf-8"))
    assert got["names"][0] == "rows_id"
