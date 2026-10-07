"""An idle row index keeps no big journal (RCA-2026-10-07-C).

Oct 07, 2026: the Backtest tab's list stopped answering. `~/.tradingagents/
v2/rows.db` carried a 6.05 GB write-ahead journal left by the Oct 06 index
builds, every frame still valid. SQLite re-reads the WHOLE journal whenever a
process opens the file while no other process has it open, and the site opens
one connection per query — so after every quiet moment the next request paid
the re-read again: 324.7 s measured for one open at 7:44am, and a coin=DODO
list request that had not answered after 600 s.

A guard for exactly this existed — `checkpoint_if_bloated`, bought by a
27.4 GB journal on 2026-08-24 — and could not see it: it measured the v1 file
(`DB_PATH`) whatever store was asked about, and its only caller was the v1
indexer loop, which the operator switched off on Sep 24, 2026. These tests
hold the three halves: the guard measures the store it is asked about, the
site's 30-second tick folds an idle store's journal, and a store something is
writing is left alone.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tradingagents import rows_index as ri


def _bloated(path: Path, rows: int = 400) -> sqlite3.Connection:
    """A WAL-mode database whose journal holds `rows` committed rows that
    were never checkpointed — the state the Oct 06 builds left behind. The
    returned connection stays open on purpose: closing the LAST connection
    would checkpoint and delete the journal, which is precisely what never
    happened on the operator's PC (the site always had the file open)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("CREATE TABLE IF NOT EXISTS rows (id INTEGER PRIMARY KEY, blob TEXT)")
    con.execute("BEGIN")
    for i in range(rows):
        con.execute("INSERT INTO rows (blob) VALUES (?)", ("x" * 2000,))
    con.execute("COMMIT")
    return con


def _wal(path: Path) -> int:
    p = path.parent / (path.name + "-wal")
    return p.stat().st_size if p.exists() else 0


@pytest.fixture
def two_stores(tmp_path, monkeypatch):
    v1 = tmp_path / "v1" / "rows.db"
    v2 = tmp_path / "v2" / "rows.db"
    monkeypatch.setattr(ri, "DB_PATH", v1)
    held = [_bloated(v1, rows=10), _bloated(v2, rows=400)]
    # nothing is writing either store unless a test says so
    monkeypatch.setattr(ri, "busy_job", lambda: "")
    monkeypatch.setattr(ri, "build_running", lambda name=None: "")
    monkeypatch.setattr(ri, "lock_holder", lambda: "")
    getattr(ri, "_FOLD_TRIED", {}).clear()
    yield v1, v2
    for con in held:
        con.close()


def test_the_guard_measures_the_store_it_is_asked_about(two_stores):
    """The 2026-08-24 guard read DB_PATH (v1) whatever store the call was
    for, so the 6.05 GB v2 journal was invisible to it."""
    v1, v2 = two_stores
    big = _wal(v2)
    assert big > 500_000 and _wal(v1) < big
    with ri.using_db(v2):
        assert ri.wal_bytes() == big
        got = ri.checkpoint_if_bloated(cap=big - 1)
    assert got["checkpointed"] is True, got
    assert _wal(v2) == 0, "the v2 journal was not folded back"
    assert _wal(v1) > 0, "the v1 store was not the one asked about"


def test_the_guard_takes_the_store_as_an_argument_too(two_stores):
    v1, v2 = two_stores
    assert ri.wal_bytes(v2) == _wal(v2)
    got = ri.checkpoint_if_bloated(cap=1, db_path=v2)
    assert got["checkpointed"] is True and _wal(v2) == 0


def test_the_site_folds_an_idle_stores_journal(two_stores, monkeypatch):
    """`fold_idle_wal` is what the site's 30-second tick calls for each
    store. It works on its OWN thread: re-reading a 6 GB journal took 5.4
    minutes, and the tick is the loop that restarts dead runners."""
    _v1, v2 = two_stores
    monkeypatch.setattr(ri, "IDLE_WAL_CAP", 1)
    said = ri.fold_idle_wal(v2)
    assert "journal" in said and "rows.db" in said, said
    ri._FOLDING[ri._gate_key(v2)].join(timeout=30)
    assert _wal(v2) == 0
    # one attempt per store per IDLE_FOLD_EVERY_S, never every tick
    _bloated(v2, rows=50).close()
    assert ri.fold_idle_wal(v2) == ""


def test_a_small_journal_is_left_alone(two_stores):
    _v1, v2 = two_stores
    assert ri.wal_bytes(v2) < ri.IDLE_WAL_CAP
    assert ri.fold_idle_wal(v2) == ""
    assert ri._gate_key(v2) not in ri._FOLDING


@pytest.mark.parametrize("who", ["busy_job", "build_running", "lock_holder"])
def test_a_store_being_written_is_left_alone(two_stores, monkeypatch, who):
    """A collect filing rows, an index build or a delisted cleanup owns the
    file — folding beside it only fights them for the one mechanical disk.
    The tick tries again once they are done."""
    _v1, v2 = two_stores
    monkeypatch.setattr(ri, "IDLE_WAL_CAP", 1)
    monkeypatch.setattr(ri, who, lambda *a, **k: "collect_v2")
    before = _wal(v2)
    assert ri.fold_idle_wal(v2) == ""
    assert _wal(v2) == before


def test_the_stores_are_asked_through_their_own_file(two_stores, monkeypatch):
    """The holder checks read the store being folded (`using_db`), not v1."""
    _v1, v2 = two_stores
    monkeypatch.setattr(ri, "IDLE_WAL_CAP", 1)
    seen = []
    monkeypatch.setattr(ri, "busy_job", lambda: seen.append(str(ri._db())) or "")
    ri.fold_idle_wal(v2)
    assert seen == [str(v2)]


def test_the_site_tick_folds_every_store():
    """The guard has to be CALLED, for both stores, by the process that is
    always running — the v1 indexer that used to call it is switched off."""
    src = Path("tradingagents/api.py").read_text(encoding="utf-8")
    at = src.index("for _live in (_ri.DB_PATH, _st.V2.rows_db):")
    block = src[at:at + 1200]
    assert "_ri.fold_idle_wal(_live)" in block
