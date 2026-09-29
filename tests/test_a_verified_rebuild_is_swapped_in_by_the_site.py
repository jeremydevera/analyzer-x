"""A finished, verified rebuild gets swapped in while the site is running
(RCA-2026-09-28-F).

Sep 28, 2026 10:33pm, Backtest v2: the rebuild loaded 5,006 pairs, 51,066,478
rows, verified them, and then failed on the rename — Windows refuses to
rename a file any handle holds, and the API on 8787 opens rows.db on every
poll. `shutil.move` then COPIED the 25.26 GB live file to the backup name
before failing to delete it.
"""
import inspect
import json
import threading
import time

import pytest

from tradingagents import api, rows_index as ri


@pytest.fixture
def store(tmp_path, monkeypatch):
    live = tmp_path / "rows.db"
    live.write_text("OLD", encoding="utf-8")
    dest = live.with_suffix(".rebuild.db")
    dest.write_text("NEW", encoding="utf-8")
    monkeypatch.setattr(ri, "lock_holder", lambda: "")
    monkeypatch.setattr(ri, "build_running", lambda: "")
    monkeypatch.setattr(ri, "_after_fill_indexes", lambda: ["rows_wr2"])
    monkeypatch.setattr(ri, "forget_indexes", lambda: None)
    (tmp_path / "rows_rebuild.json").write_text(
        json.dumps({"phase": "failed: the swap could not take place"}),
        encoding="utf-8")
    return live, dest


def test_a_refused_rename_never_copies_the_file(tmp_path, monkeypatch):
    live = tmp_path / "rows.db"
    live.write_text("OLD", encoding="utf-8")
    dest = tmp_path / "rows.rebuild.db"
    dest.write_text("NEW", encoding="utf-8")
    backup = tmp_path / "rows.before-rebuild.db"

    def refused(src, dst):
        raise PermissionError(32, "being used by another process")

    monkeypatch.setattr(ri.os, "replace", refused)
    with pytest.raises(PermissionError):
        ri.swap_in(dest, backup, live=live)
    assert not backup.exists(), "a refused rename must not leave a copy"
    assert live.read_text(encoding="utf-8") == "OLD"


def test_no_marker_no_swap(store):
    live, dest = store
    assert ri.swap_ready_rebuild(live) == ""
    assert live.read_text(encoding="utf-8") == "OLD"


def test_a_marked_rebuild_is_swapped_and_the_marker_cleared(store):
    live, dest = store
    ri.ready_marker(dest).write_text("{}", encoding="utf-8")
    said = ri.swap_ready_rebuild(live)
    assert said.startswith("swapped the rebuilt index into rows.db")
    assert "rows_wr2" in said
    assert live.read_text(encoding="utf-8") == "NEW"
    assert (live.with_name("rows.before-rebuild.db")
            .read_text(encoding="utf-8")) == "OLD"
    assert not ri.ready_marker(dest).exists()
    assert json.loads((live.parent / "rows_rebuild.json")
                      .read_text(encoding="utf-8"))["phase"] == "done"


def test_it_stands_back_while_an_index_is_building(store, monkeypatch):
    live, dest = store
    ri.ready_marker(dest).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ri, "build_running", lambda: "rows_wr2")
    said = ri.swap_ready_rebuild(live)
    assert "rows_wr2 is being built" in said
    assert live.read_text(encoding="utf-8") == "OLD"
    assert ri.ready_marker(dest).exists(), "kept for the next check"


def test_a_file_still_held_gives_up_cleanly_and_reopens_the_gate(store, monkeypatch):
    live, dest = store
    ri.ready_marker(dest).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ri, "SWAP_WINDOW_S", 0.3)

    def refused(src, dst):
        raise PermissionError(32, "being used by another process")

    monkeypatch.setattr(ri.os, "replace", refused)
    said = ri.swap_ready_rebuild(live)
    assert "could not be swapped in yet" in said
    assert live.read_text(encoding="utf-8") == "OLD"
    assert ri._gate_key(live) not in ri._SWAP_CLOSED
    assert ri.ready_marker(dest).exists()


def test_a_reader_waits_at_the_closed_gate_and_goes_on_after(tmp_path):
    live = tmp_path / "rows.db"
    key = ri._gate_key(live)
    with ri._SWAP_GATE:
        ri._SWAP_CLOSED.add(key)
    passed = threading.Event()
    t = threading.Thread(target=lambda: (ri._await_gate(live), passed.set()))
    t.start()
    time.sleep(0.2)
    assert not passed.is_set(), "a new reader must wait while the file is swapped"
    with ri._SWAP_GATE:
        ri._SWAP_CLOSED.discard(key)
        ri._SWAP_GATE.notify_all()
    t.join(2)
    assert passed.is_set()


def test_every_connection_passes_the_gate():
    assert "_await_gate(p)" in inspect.getsource(ri._connect)


def test_a_refused_rebuild_swap_leaves_the_ready_marker():
    src = inspect.getsource(ri.rebuild)
    i = src.index("put_back(backup)")
    assert "ready_marker(dest).write_text(" in src[i:i + 600]
    # and a new build of the file voids an old marker
    assert "ready_marker(dest).unlink()" in src


def test_the_sites_tick_swaps_both_stores():
    src = inspect.getsource(api)
    assert "for _live in (_ri.DB_PATH, _st.V2.rows_db):" in src
    assert "_ri.swap_ready_rebuild(_live)" in src
