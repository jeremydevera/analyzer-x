"""A six-hour rebuild must not be thrown away at its last gate.

`rows_index.rebuild()` had no production caller until Sep 12, 2026, when the
operator asked for 6,845,648 newly measured rows to appear in Stored
strategies and the only path fast enough was a full rebuild (~6 h against a
measured 175 s/pair × 5,179 stale pairs = 252 h for the incremental sync).

Three gaps, each of which spends the six hours and then discards the result.
"""
import json
from pathlib import Path

import pytest

from tradingagents import rows_index as ri


@pytest.fixture
def store(tmp_path, monkeypatch):
    from tradingagents import market_sweep as msw

    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    return rows_dir


def _row(coin, tf="1h", signal="cx_veto", profit=1.0):
    return {"coin": coin, "tf": tf, "signal": signal, "th": 0.0, "sl": 1.0,
            "tp": 2.0, "rr": 2.0, "sizing": "flat", "lev": 20, "base": 5.0,
            "notional": 100.0, "trades": 12, "wins": 9, "losses": 3,
            "winrate": 75.0, "profit": profit, "funding": 0.0, "h1": 0.5,
            "h2": 0.5, "green": 1, "months": 1, "worst": -1.0, "dd": 1.0,
            "liqs": 0, "stop_reachable": True, "days": 30, "bars": 720,
            "monthly": {"2026-09": profit}, "cost_of_tp": 5.0, "rt": 0.05,
            "gate": "ok", "last_ms": 1_788_000_000_000}


def test_one_unreadable_file_does_not_discard_the_whole_rebuild(store):
    """THE FAILURE THIS WAS WRITTEN FOR. `index_pair` returns 0 on a file it
    cannot parse — BEFORE writing that pair's summary row — and the loop used
    to count it anyway, so the final gate read `pairs 3 vs 4`, deleted the
    partial, and the re-run met the same file. A collect rewrites ~1,800 pair
    files an hour while the loader reads them, so a half-written file is not
    a theory."""
    for coin in ("AAA", "BBB", "CCC"):
        (store / f"{coin}-1h.json").write_text(json.dumps([_row(coin)]),
                                               encoding="utf-8")
    (store / "HOT-1h.json").write_text("{ this file is half written",
                                       encoding="utf-8")

    got = ri.rebuild(resume=False, keep_backup=False)

    assert got["rebuilt"] is True, got.get("why")
    assert got["pairs"] == 3, "the three readable pairs counted"
    assert got["skipped"] == ["HOT-1h.json"], \
        "the unreadable file is NAMED, never silently dropped (rule 20)"
    assert ri.query(signal="cx_veto")["total"] == 3


def test_an_EMPTY_pair_file_still_counts(store):
    """`[]` is a real measurement — the trade floor kept nothing — and
    index_pair files its summary for it. It returns 0 rows like an unreadable
    file does, so telling them apart by the return value alone would drop a
    legitimate pair and fail the gate the other way."""
    (store / "AAA-1h.json").write_text(json.dumps([_row("AAA")]),
                                       encoding="utf-8")
    (store / "EMPTY-1d.json").write_text("[]", encoding="utf-8")

    got = ri.rebuild(resume=False, keep_backup=False)

    assert got["rebuilt"] is True, got.get("why")
    assert got["pairs"] == 2, "the empty pair is measured, not missing"
    assert got["skipped"] == []


def test_the_swap_queues_the_indexes_it_just_destroyed(store, monkeypatch):
    """The new file carries KEEP_INDEXES only. Five on-demand indexes had
    already cost hours on the operator's store — and `rows_signal` is what
    makes their `signal=cx_veto` filter answer at all — so a rebuild that
    does not queue them leaves the panel 503-ing on its own features."""
    called = []
    monkeypatch.setattr(ri, "_after_fill_indexes",
                        lambda: called.append(True) or ["rows_signal"])
    (store / "AAA-1h.json").write_text(json.dumps([_row("AAA")]),
                                       encoding="utf-8")

    got = ri.rebuild(resume=False, keep_backup=False)

    assert called, "the swap must queue the on-demand indexes"
    assert got["indexes_queued"] == ["rows_signal"]


def test_a_six_hour_job_can_be_spawned_with_a_log():
    """CLAUDE.md, bought on Sep 10, 2026: a long-running process writes a log.
    `main()` took --build and resolve only, so a rebuild could run only inline
    in a shell somebody had to keep open."""
    import inspect

    src = inspect.getsource(ri.main)
    assert '"--rebuild"' in src
    assert "rebuild(resume=" in src, "and it must be resumable by default"


def _held(monkeypatch, target):
    """Make `shutil.move` refuse to move `target`, the way Windows does while
    another process has the file open."""
    import shutil

    real = shutil.move

    def fake(src, dst, *a, **k):
        if str(src) == str(target):
            raise PermissionError(
                32, "The process cannot access the file because it is being "
                    "used by another process")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(shutil, "move", fake)


def test_a_held_index_file_makes_the_swap_SAY_FAILED_not_raise(
        store, monkeypatch):
    """THE FAILURE THIS WAS WRITTEN FOR. Every phase of `rebuild()` reports
    into rows_rebuild.json from inside a try/except — and the swap sat
    OUTSIDE it. On Windows `shutil.move` raises PermissionError for as long
    as another process holds rows.db open, and the API on 8787 holds it all
    day, so a six-hour rebuild would end with the progress file still reading
    "verifying" and a traceback nobody was watching for."""
    (store / "AAA-1h.json").write_text(json.dumps([_row("AAA")]),
                                       encoding="utf-8")
    assert ri.rebuild(resume=False)["rebuilt"] is True
    (store / "BBB-1h.json").write_text(json.dumps([_row("BBB")]),
                                       encoding="utf-8")

    _held(monkeypatch, ri.DB_PATH)
    got = ri.rebuild(resume=False)

    assert got["rebuilt"] is False
    assert "swap could not take place" in got["why"]
    assert "PermissionError" in got["why"], "name what actually happened"
    assert ri.rebuild_progress()["phase"].startswith("failed:"), \
        "the progress file is the only thing a watcher reads"
    # six hours of work is not thrown away: the finished file is NAMED
    assert Path(got["rebuild_file"]).exists()


def test_a_failed_swap_leaves_the_live_index_exactly_where_it_was(
        store, monkeypatch):
    """The old order deleted the previous backup and the LIVE file's `-wal`
    BEFORE the move that can fail. A refused swap therefore destroyed two
    things and changed nothing else."""
    (store / "AAA-1h.json").write_text(json.dumps([_row("AAA")]),
                                       encoding="utf-8")
    assert ri.rebuild(resume=False)["rebuilt"] is True
    ri.query(coin="AAA")                       # the API's grip on the file
    before = ri.DB_PATH.read_bytes()

    (store / "BBB-1h.json").write_text(json.dumps([_row("BBB")]),
                                       encoding="utf-8")
    _held(monkeypatch, ri.DB_PATH)
    assert ri.rebuild(resume=False)["rebuilt"] is False

    assert ri.DB_PATH.exists(), "the operator's index must still be there"
    assert ri.DB_PATH.read_bytes() == before, "and untouched"
    assert ri.query(coin="AAA")["total"] == 1, "and still answering"


def test_the_retired_index_keeps_the_wal_it_arrived_with(store):
    """`rows.db-wal` was DELETED on the way past — throwing away whatever a
    reader had committed but not checkpointed, from the very file that is
    supposed to be the fallback. It travels to the backup instead, which
    also clears the name: a stale `rows.db-wal` beside a DIFFERENT rows.db
    is corruption, not clutter.

    Driven through `swap_in` with plain bytes on purpose. SQLite deletes its
    own `-wal` when the last connection closes, so a WAL planted around a
    real `rebuild()` is gone before the swap ever reaches it — the first
    version of this test failed for that reason and proved nothing about the
    code under it."""
    ri.DB_PATH.write_bytes(b"the live index")
    Path(str(ri.DB_PATH) + "-wal").write_bytes(b"committed-not-checkpointed")
    dest = ri.DB_PATH.with_suffix(".rebuild.db")
    dest.write_bytes(b"the new index")
    backup = ri.DB_PATH.with_suffix(".before-rebuild.db")

    ri.swap_in(dest, backup, keep_backup=True)

    assert ri.DB_PATH.read_bytes() == b"the new index"
    assert backup.read_bytes() == b"the live index", "retired, not deleted"
    assert Path(str(backup) + "-wal").read_bytes() == \
        b"committed-not-checkpointed", "the WAL follows its own database"
    assert not Path(str(ri.DB_PATH) + "-wal").exists(), \
        "a stale WAL beside a DIFFERENT database is corruption"


def test_the_swapped_in_index_is_already_in_WAL(store):
    """THE FAULT THIS WAS WRITTEN FOR, found Sep 13, 2026 4:06pm.

    `_connect` states the rule: *"journal_mode is PERSISTENT -- setting it per
    connection needs a brief exclusive lock, which any live reader blocks. Set
    once, in ensure()."* `rebuild()` loads with `journal_mode=OFF`, which is
    not persistable, so the file it swapped in reopened in `delete`. From then
    on `ensure()` had to flip a 41 GB file that the API polls every second —
    an EXCLUSIVE lock it can never get — and the indexer died on its FIRST
    statement, `database is locked`, on every single spawn for 29 hours while
    a collect landed pairs that nothing would index."""
    (store / "AAA-1h.json").write_text(json.dumps([_row("AAA")]),
                                       encoding="utf-8")
    got = ri.rebuild(resume=False, keep_backup=False)

    assert got["rebuilt"] is True, got.get("why")
    assert got["journal_mode"] == "wal", \
        "the mode must be REPORTED, not assumed"
    import sqlite3
    con = sqlite3.connect(f"file:{ri.DB_PATH}?mode=ro", uri=True)
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal", \
            "the live index is not in WAL, so the indexer cannot start"
    finally:
        con.close()


def test_a_compacted_index_is_in_WAL_too(store):
    """`VACUUM INTO` writes the DEFAULT journal mode, which is `delete`. Same
    landmine, different maker — grep the CONCEPT, not the name."""
    (store / "AAA-1h.json").write_text(json.dumps([_row("AAA")]),
                                       encoding="utf-8")
    ri.rebuild(resume=False, keep_backup=False)

    got = ri.compact(keep_backup=False)

    assert got.get("compacted") is True, got.get("why")
    assert got["journal_mode"] == "wal"


def test_a_file_that_refuses_WAL_is_still_swapped_in_and_named(
        store, monkeypatch):
    """A delete-mode index still answers every read; only the indexer cannot
    start. That is a thing to repair, not a reason to throw away five hours —
    and an exception here would escape `rebuild()` exactly like the swap used
    to (RCA-2026-09-12-K)."""
    (store / "AAA-1h.json").write_text(json.dumps([_row("AAA")]),
                                       encoding="utf-8")

    def refuse(path):
        raise OSError(5, "the drive went away")

    monkeypatch.setattr(ri, "make_wal", refuse)
    got = ri.rebuild(resume=False, keep_backup=False)

    assert got["rebuilt"] is True, "five hours must not be thrown away"
    assert got["journal_mode"].startswith("NOT SET: OSError"), \
        "and the operator must be told the indexer will not start"


def test_both_swaps_are_the_same_one(store):
    """`compact()` and `rebuild()` each carried their own copy of these six
    lines and BOTH copies were wrong the same two ways. CLAUDE.md, bought on
    Sep 04: when changing a rule, grep for the CONCEPT and list every place
    it lives — `timeframe_conflicts` was the third guard nobody found, and it
    froze all trading for nine hours."""
    import inspect

    for fn in (ri.compact, ri.rebuild):
        src = inspect.getsource(fn)
        # CODE lines only. The first version of this check read the comments
        # too and failed on the paragraph that EXPLAINS the old bug — the
        # same shape as the `.toLocale` grep that passed while a Date was
        # being sliced by hand.
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.strip().startswith("#"))
        assert "swap_in(" in code, f"{fn.__name__} must use the one swap"
        assert "shutil.move(" not in code, \
            f"{fn.__name__} grew its own copy of the swap again"
        assert "put_back(" in code, \
            f"{fn.__name__} must roll back a half-finished swap"
