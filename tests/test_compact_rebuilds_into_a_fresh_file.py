"""rows.db can be compacted, and the copy is verified before it is trusted.

CLAUDE.md has carried the technique since 2026-08-26 and nothing implemented
it: *"Do NOT repair a bloated file in place: this one carried 727,146 free
pages (2.8 GB) and a single DROP INDEX rows_profit had not finished in fourteen
minutes. Loading a FRESH file sequentially and swapping it in is faster and
leaves a compact database."*

Measured on the operator's store, Sep 10, 2026:

    rows.db      34.7 GB
    pages        8,469,643
    free pages   3,288,083-3,961,902 over the day = 38.8-46.8% of the file
                 = 13.5-16.2 GB of holes

That is 5.4x the case the rule was written for, and it is why the catch-up
managed **0.86 pairs/min** against the 75/min a lean fill is supposed to do:
every insert lands in a hole somewhere else, so the disk seeks instead of
streaming. Dropping ten indexes (RCA-E) helped and was not enough, and it cost
the operator their win-% filter for the duration — compaction costs no filter
at all.

The rule this file enforces: **nothing is swapped until the copy has been
opened, integrity-checked, and found to hold the same rows and pairs.** This is
the only copy of 51,943,352 measured rows. A compaction that loses them is
infinitely worse than a slow one.
"""
from __future__ import annotations

import inspect
import sqlite3

import pytest

from tradingagents import rows_index as ri


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri._ready.discard(str(tmp_path / "rows.db"))
    ri.ensure()
    with ri._open() as con:
        for i in range(400):
            con.execute(
                f"INSERT INTO rows ({','.join(ri.COLS)},monthly,pair) VALUES "
                f"({','.join('?' * (len(ri.COLS) + 2))})",
                [f"ID{i}", "BTC", "1h", "rsi14"] + [0] * (len(ri.COLS) - 4)
                + ["{}", "BTC-1h"])
        con.execute("INSERT INTO pairs (pair,mtime,size,n,at,coin,tf)"
                    " VALUES ('BTC-1h',1,1,400,1,'BTC','1h')")
    # make holes: delete most of it, which frees pages without shrinking
    with ri._open() as con:
        con.execute("DELETE FROM rows WHERE id NOT IN"
                    " (SELECT id FROM rows LIMIT 40)")
    return tmp_path / "rows.db"


def test_bloat_reports_free_pages_without_touching_the_file(store):
    b = ri.bloat()
    assert b["pages"] > 0
    assert b["free"] > 0, "the fixture deleted 360 of 400 rows"
    assert 0 < b["pct"] <= 100
    assert b["bytes"] == store.stat().st_size


def test_compact_keeps_every_row_and_pair(store):
    with ri._open(readonly=True) as con:
        want = int(con.execute("SELECT count(*) FROM rows").fetchone()[0])
        pairs = int(con.execute("SELECT count(*) FROM pairs").fetchone()[0])
    got = ri.compact()
    assert got["compacted"] is True, got
    assert got["rows"] == want and got["pairs"] == pairs
    with ri._open(readonly=True) as con:
        assert int(con.execute("SELECT count(*) FROM rows").fetchone()[0]) == want
        assert int(con.execute("SELECT count(*) FROM pairs").fetchone()[0]) == pairs


def test_compact_actually_reclaims_the_holes(store):
    before = ri.bloat()
    got = ri.compact()
    after = ri.bloat()
    assert after["pct"] < before["pct"], (before["pct"], after["pct"])
    assert got["freed_bytes"] > 0, got


def test_the_kept_indexes_survive_a_compaction(store):
    ri.compact()
    with ri._open(readonly=True) as con:
        have = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
            " AND tbl_name='rows'")}
    for kept in ri._kept_index_names():
        assert kept in have, f"{kept} did not survive — the screen loses its order"


def test_the_old_file_is_kept_beside_it_by_default(store):
    got = ri.compact()
    assert got["backup"], "the previous file must still exist by default"
    from pathlib import Path
    assert Path(got["backup"]).exists()


def test_a_caller_can_refuse_another_copy(store):
    """24.8 GB of rows.prev.db / rows.old.db was already lying around on
    Sep 10, 2026, on a drive with 21.2 GB free."""
    got = ri.compact(keep_backup=False)
    assert got["compacted"] is True
    assert got["backup"] == ""


def test_compact_refuses_while_another_process_is_writing(store, monkeypatch):
    """A copy taken mid-transaction is a copy of a half-finished fill."""
    monkeypatch.setattr(ri, "write_available",
                        lambda *a, **k: "another process is writing rows.db")
    got = ri.compact()
    assert got["compacted"] is False
    assert "writing" in got["why"]


def test_a_copy_that_does_not_match_is_thrown_away_not_swapped(store, monkeypatch):
    """The whole safety of this rests on verifying before swapping."""
    real = sqlite3.connect

    def lying(*a, **kw):
        con = real(*a, **kw)
        if "compact.db" in str(a[0]):
            con.close()
            raise sqlite3.DatabaseError("file is not a database")
        return con

    monkeypatch.setattr(sqlite3, "connect", lying)
    got = ri.compact()
    assert got["compacted"] is False, got
    assert store.exists(), "the original must still be there"
    with ri._open(readonly=True) as con:
        assert int(con.execute("SELECT count(*) FROM rows").fetchone()[0]) == 40


def test_it_verifies_rows_pairs_and_integrity_before_swapping():
    src = inspect.getsource(ri.compact)
    assert "quick_check" in src
    assert "got_rows != want_rows" in src and "got_pairs != want_pairs" in src
    i = src.index("shutil.move")
    assert src.index("quick_check") < i, "verify BEFORE the swap, never after"


def test_the_threshold_is_named_and_below_what_was_measured():
    assert ri.BLOAT_PCT <= 46.8, \
        "the operator's store was 46.8% free; a threshold above that never fires"
