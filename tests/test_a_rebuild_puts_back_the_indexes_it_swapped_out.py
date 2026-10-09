"""A rebuild puts back every on-demand index the file it replaced carried
(RCA-2026-10-09-A).

Backtest v2's table is rebuilt every evening after the daily update's collect
(Oct 07, 2026 8:44pm; Oct 08, 2026 8:07pm). The fresh file carries the kept
four only, and the swap then "queued" the on-demand ones — but builds run one
at a time, so `build_missing_indexes` started `rows_wr2` and every other
missing index printed "waits: rows_wr2 is building" and was never asked for
again. The file the swap retired had held `rows_wr2` AND `rows_wr4`; the new
one held `rows_wr2` only. At midnight the rooms' switch-on passes need
`rows_wr4` (win % with filters beside it), so on Oct 08, 2026 12:02am Main
waited, and on Oct 09, 2026 12:00am Main and #4FC03172 waited, while the
search list was built from scratch on demand (2,222 s the first night).

These tests drive the two calls the API's 30-second tick makes —
`swap_ready_rebuild` then `continue_index_queue` — over a fake database whose
index list is read from which FILE sits at the path, so the old and new file
are told apart exactly as `has_index` tells them apart.
"""
import inspect
import json

import pytest

from tradingagents import api, rows_index as ri


@pytest.fixture
def store(tmp_path, monkeypatch):
    live = tmp_path / "rows.db"
    live.write_text("OLD", encoding="utf-8")
    dest = live.with_suffix(".rebuild.db")
    dest.write_text("NEW", encoding="utf-8")
    ri.ready_marker(dest).write_text("{}", encoding="utf-8")
    kept = set(ri._kept_index_names())
    on_file = {"OLD": kept | {"rows_wr2", "rows_wr4"}, "NEW": set(kept)}
    state = {"building": "", "started": [], "refuse": set()}

    def has_index(name):
        return name in on_file[ri._db().read_text(encoding="utf-8")]

    def build_index(name):
        state["started"].append(name)
        if name in state["refuse"]:
            return True                    # the child starts, then fails
        state["building"] = name
        return True

    def after_fill():
        # what the real one does on this store: starts the FIRST missing
        # index in INDEX_DDL order, and every other one only "waits"
        started = build_index("rows_wr2")
        return ["rows_wr2"] if started else []

    monkeypatch.setattr(ri, "has_index", has_index)
    monkeypatch.setattr(ri, "_build_index", build_index)
    monkeypatch.setattr(ri, "build_running", lambda name=None: state["building"])
    monkeypatch.setattr(ri, "lock_holder", lambda: "")
    monkeypatch.setattr(ri, "_after_fill_indexes", after_fill)
    monkeypatch.setattr(ri, "forget_indexes", lambda: None)

    def finish():
        """The detached child finished: the index is on the new file."""
        on_file["NEW"].add(state["building"])
        state["building"] = ""

    # the swap stands back while a build runs on the OLD file
    state["building"] = ""
    return live, state, finish, on_file


def _tick(live):
    with ri.using_db(live):
        return ri.continue_index_queue()


def test_the_index_the_old_file_had_is_built_again(store):
    live, state, finish, on_file = store
    said = ri.swap_ready_rebuild(live)
    assert said.startswith("swapped the rebuilt index into rows.db")
    assert state["started"] == ["rows_wr2"]
    # while rows_wr2 builds, nothing else may start: SQLite takes one writer
    assert _tick(live) == ""
    assert state["started"] == ["rows_wr2"]
    finish()
    said = _tick(live)
    assert state["started"] == ["rows_wr2", "rows_wr4"], (
        "rows_wr4 was on the file the swap retired and was never built again "
        "— the rooms' midnight switch-on waited for it (Oct 09, 2026 12:00am)")
    assert "rows_wr4" in said
    finish()
    assert _tick(live) == ""
    assert "rows_wr4" in on_file["NEW"]
    assert not ri._index_queue_path(live).exists(), "a finished queue is gone"


def test_an_index_the_old_file_never_had_is_not_built(store):
    live, state, finish, on_file = store
    ri.swap_ready_rebuild(live)
    finish()
    _tick(live)
    finish()
    _tick(live)
    assert "rows_id" not in state["started"]
    assert "rows_ml_dd" not in state["started"]
    assert set(state["started"]) == {"rows_wr2", "rows_wr4"}


def test_an_index_that_never_builds_is_given_up_and_named(store, capsys):
    live, state, finish, on_file = store
    state["refuse"].add("rows_wr4")
    ri.swap_ready_rebuild(live)
    finish()
    for _ in range(ri.INDEX_QUEUE_TRIES + 3):
        _tick(live)
    assert state["started"].count("rows_wr4") == ri.INDEX_QUEUE_TRIES, (
        "a build that fails every time must not be respawned every 30 s")
    assert not ri._index_queue_path(live).exists()
    assert "rows_wr4" in capsys.readouterr().out


def test_no_queue_is_nothing_to_do(tmp_path):
    live = tmp_path / "rows.db"
    with ri.using_db(live):
        assert ri.continue_index_queue() == ""


def test_an_unreadable_queue_file_never_raises(tmp_path):
    live = tmp_path / "rows.db"
    ri._index_queue_path(live).write_text("{not json", encoding="utf-8")
    with ri.using_db(live):
        assert ri.continue_index_queue() == ""


def test_the_rebuild_that_swaps_by_itself_remembers_too():
    src = inspect.getsource(ri.rebuild)
    assert "_remember_indexes(" in src, (
        "rebuild() swaps in-process on most nights (Oct 08, 2026 8:07pm) and "
        "must queue what the retired file held, exactly like the site's swap")


def test_the_sites_tick_carries_the_queue_on_for_every_store():
    src = inspect.getsource(api)
    assert "continue_index_queue()" in src
    tick = src[src.index("swap_ready_rebuild(_live)"):]
    tick = tick[:tick.index("spawn_indexer()")]
    assert "continue_index_queue()" in tick, (
        "the 30-second tick is the only thing that runs after a detached "
        "build finishes; nothing else would start the next index")
