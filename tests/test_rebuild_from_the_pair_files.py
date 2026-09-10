"""The index can be rebuilt from the pair files — all of them, compactly.

The operator's ask was *"i want this fixed"*, and the thing not fixed was
FILING: 4,612 of 5,365 coins searchable (86%), the rest measured and invisible,
filing at ~0.86 pairs/min because 38.8% of the 32 GB file is holes.

Two attempts before this one:

* dropping the ten on-demand indexes for a bulk fill (RCA-E) — helped, not
  enough, and it took the operator's win-% filter down with it (RCA-F);
* `compact()`, a `VACUUM INTO` copy of the existing file (RCA-G) — reached 90%
  and stalled for hours with no root cause established.

This is the technique CLAUDE.md has prescribed since 2026-08-26 and neither of
those was: *"Loading a FRESH file sequentially and swapping it in is faster and
leaves a compact database."* It starts from the pair JSON files, which
`_connect` already names as the source of truth, so it fixes both problems in
one pass:

* written with NO indexes, sequentially — the measured difference is
  **1.5 pairs/min against 75**, and the live catch-up was managing 0.86;
* it indexes EVERY pair file, so the answer is 100% and not 86%.

Safety is the same contract as `compact()`: a new file, verified before
anything is swapped, the original untouched on any failure. And after RCA-G,
progress is written after **every pair** — a stall must be visible in minutes,
not in seven hours.
"""
from __future__ import annotations

import inspect
import json
import sqlite3

import pytest

from tradingagents import market_sweep as msw, rows_index as ri


def _pair_file(d, coin, tf, n):
    f = d / f"{coin}-{tf}.json"
    f.write_text(json.dumps([
        {"id": f"{coin}{tf}{i}", "coin": coin, "tf": tf, "signal": "rsi14",
         "sizing": "flat", "trades": 10, "winrate": 90.0, "profit": 1.0,
         "monthly": {}} for i in range(n)]), encoding="utf-8")
    return f


@pytest.fixture()
def store(tmp_path, monkeypatch):
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    monkeypatch.setattr(ri, "REBUILD_PROGRESS", tmp_path / "prog.json")
    ri._ready.discard(str(tmp_path / "rows.db"))
    _pair_file(rows_dir, "BTC", "15m", 30)
    _pair_file(rows_dir, "BTC", "1h", 20)
    _pair_file(rows_dir, "ETH", "15m", 25)
    return tmp_path


def test_it_indexes_every_pair_file_not_just_the_ones_already_in_the_db(store):
    """86% was the whole complaint."""
    ri.ensure()
    with ri._open() as con:
        ri.index_pair(msw.ROWDIR / "BTC-15m.json", con)      # only one of three
    got = ri.rebuild()
    assert got["rebuilt"] is True, got
    assert got["pairs"] == 3, got
    assert got["rows"] == 75, got
    st = ri.status()
    assert st["pairs_indexed"] == 3
    assert int(st.get("behind") or 0) == 0, "100%, not 86%"


def test_the_rebuilt_file_holds_exactly_what_the_pair_files_say(store):
    ri.rebuild()
    with ri._open(readonly=True) as con:
        assert int(con.execute("SELECT count(*) FROM rows").fetchone()[0]) == 75
        assert int(con.execute(
            "SELECT count(*) FROM rows WHERE coin='BTC'").fetchone()[0]) == 50
        assert int(con.execute("SELECT count(*) FROM pairs").fetchone()[0]) == 3


def test_the_kept_indexes_exist_afterwards(store):
    ri.rebuild()
    with ri._open(readonly=True) as con:
        have = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
            " AND tbl_name='rows'")}
    for kept in ri._kept_index_names():
        assert kept in have, f"{kept} missing — the screen loses its order"


def test_indexes_are_created_AFTER_the_load_not_during(store):
    """That is the whole speed argument: 1.5 pairs/min with them, 75 without."""
    src = inspect.getsource(ri.rebuild)
    load = src.index("rows += index_pair(")
    build = src.index("for ddl in KEEP_INDEXES:")
    assert load < build, "indexes must be built over data already written"


def test_progress_is_written_after_every_pair(store):
    """RCA-G was seven hours of not knowing whether it had stalled."""
    ri.rebuild()
    p = ri.rebuild_progress()
    assert p.get("phase") == "done"
    assert p.get("pairs_done") == 3 and p.get("pairs_total") == 3
    assert "pairs_per_min" in p
    src = inspect.getsource(ri.rebuild)
    i = src.index("done += 1")
    assert '_say("loading")' in src[i:i + 200], \
        "the progress write must sit inside the per-pair loop"


def test_it_refuses_while_another_process_is_writing(store, monkeypatch):
    monkeypatch.setattr(ri, "write_available", lambda *a, **k: "someone is writing")
    got = ri.rebuild()
    assert got["rebuilt"] is False and "writing" in got["why"]


def test_a_rebuild_that_does_not_verify_is_thrown_away(store, monkeypatch):
    """The original must survive every failure — it is the only copy."""
    ri.ensure()
    with ri._open() as con:
        ri.index_pair(msw.ROWDIR / "BTC-15m.json", con)
    before = (ri.DB_PATH).stat().st_size
    real = ri.index_pair
    monkeypatch.setattr(ri, "index_pair",
                        lambda *a, **k: (_ for _ in ()).throw(
                            sqlite3.OperationalError("disk full")))
    got = ri.rebuild()
    assert got["rebuilt"] is False, got
    assert "disk full" in got["why"]
    assert ri.DB_PATH.exists(), "the original was moved before verifying"
    assert ri.DB_PATH.stat().st_size == before
    assert not ri.DB_PATH.with_suffix(".rebuild.db").exists(), \
        "the half-written file must not be left behind"
    monkeypatch.setattr(ri, "index_pair", real)


def test_it_verifies_rows_pairs_and_integrity_before_the_swap():
    src = inspect.getsource(ri.rebuild)
    assert "quick_check" in src
    assert "got_pairs != done" in src and "got_rows != rows" in src
    assert src.index("quick_check") < src.index("shutil.move"), \
        "verify BEFORE the swap, never after"


def test_the_old_file_is_kept_by_default_and_skippable(store):
    got = ri.rebuild()
    assert got["backup"], "the previous file must survive by default"
    got2 = ri.rebuild(keep_backup=False)
    assert got2["backup"] == ""


# ------------------------------------------------------------------ resuming
# Sep 10, 2026 1:48pm. A rebuild had been running 39 minutes and was stopped
# on purpose: it had fallen from 40.15 pairs/min to **0.25** — one pair every
# 305 seconds — because a `db_jobs collect` was 17 shards into 20, rewriting
# the same pair files on the same mechanical disk. Measured while both ran:
# `Memory\Pages/sec` 2,534, disk queue 5.0, and NEITHER process showing a byte
# of file I/O, because the traffic was page faults and seeks.
#
# Stopping was right. Losing the work was not: the partial file held **450
# pairs, 8,385,108 rows, 2.74 GB**. So a rebuild now resumes, and it refuses
# to start while another job is writing the files it reads.
def _partial(files):
    """A half-finished rebuild file, exactly as a KILLED run leaves one — no
    exception ran, so nothing cleaned up."""
    dest = ri.DB_PATH.with_suffix(".rebuild.db")
    con = sqlite3.connect(dest)
    try:
        con.executescript(ri._SCHEMA)
        con.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
        con.execute("INSERT OR REPLACE INTO meta (k,v) VALUES ('schema',?)",
                    (str(ri.SCHEMA_VERSION),))
        for f in files:
            ri.index_pair(f, con)
        con.commit()
    finally:
        con.close()
    return dest


def _watch(monkeypatch, seen):
    real = ri.index_pair

    def spy(f, con=None, **kw):
        seen.append(f.stem)
        return real(f, con, **kw)

    monkeypatch.setattr(ri, "index_pair", spy)


def test_a_killed_rebuild_resumes_instead_of_starting_over(store, monkeypatch):
    """33 minutes of work is not a rounding error."""
    _partial([msw.ROWDIR / "BTC-15m.json", msw.ROWDIR / "BTC-1h.json"])
    seen: list = []
    _watch(monkeypatch, seen)
    got = ri.rebuild()
    assert got["rebuilt"] is True, got
    assert seen == ["ETH-15m"], \
        f"only the pair that was missing may be re-read, got {seen}"
    # and the finished file is still WHOLE
    assert got["pairs"] == 3 and got["rows"] == 75, got
    with ri._open(readonly=True) as con:
        assert int(con.execute("SELECT count(*) FROM rows").fetchone()[0]) == 75
        assert int(con.execute("SELECT count(*) FROM pairs").fetchone()[0]) == 3


def test_the_resume_is_reported_so_a_reader_is_not_misled(store):
    _partial([msw.ROWDIR / "BTC-15m.json"])
    ri.rebuild()
    p = ri.rebuild_progress()
    assert p.get("resumed") == 1, p
    assert p.get("pairs_done") == 3 and p.get("pairs_total") == 3


def test_the_rate_it_reports_is_this_runs_work_only(store):
    """A resume of 450 pairs would otherwise print 450 pairs/min in its first
    minute and decay from there — a number that describes nothing."""
    _partial([msw.ROWDIR / "BTC-15m.json", msw.ROWDIR / "BTC-1h.json"])
    ri.rebuild()
    src = inspect.getsource(ri.rebuild)
    assert "(done - len(already))" in src, \
        "the rate must exclude the pairs this run did not do"
    assert ri.rebuild_progress().get("pairs_per_min") is not None


def test_a_partial_file_that_does_not_check_out_is_started_over(store):
    """`journal_mode=OFF` is the price of the speed: a kill mid-commit can
    tear pages. A file that cannot be verified is deleted, never resumed."""
    dest = ri.DB_PATH.with_suffix(".rebuild.db")
    dest.write_bytes(b"SQLite format 3\x00" + b"\x99" * 4096)
    got = ri.rebuild()
    assert got["rebuilt"] is True, got
    assert got["pairs"] == 3 and got["rows"] == 75, "a full rebuild ran"
    assert ri.rebuild_progress().get("restarted_because"), \
        "and it must SAY why it started over"


def test_a_partial_file_from_another_schema_is_started_over(store):
    dest = _partial([msw.ROWDIR / "BTC-15m.json"])
    con = sqlite3.connect(dest)
    con.execute("INSERT OR REPLACE INTO meta (k,v) VALUES ('schema','1')")
    con.commit()
    con.close()
    got = ri.rebuild()
    assert got["rebuilt"] is True and got["pairs"] == 3, got
    assert "schema" in (ri.rebuild_progress().get("restarted_because") or "")


def test_a_pair_whose_file_was_deleted_is_dropped_not_left_to_fail(store):
    """Otherwise its rows survive in the new file, the final count disagrees
    with the load, and a two-hour rebuild is thrown away at the last step."""
    _partial([msw.ROWDIR / "BTC-15m.json", msw.ROWDIR / "BTC-1h.json"])
    (msw.ROWDIR / "BTC-1h.json").unlink()
    got = ri.rebuild()
    assert got["rebuilt"] is True, got
    assert got["pairs"] == 2 and got["rows"] == 55, got
    with ri._open(readonly=True) as con:
        assert int(con.execute(
            "SELECT count(*) FROM rows WHERE pair='BTC-1h'").fetchone()[0]) == 0


def test_resume_can_be_turned_off(store, monkeypatch):
    _partial([msw.ROWDIR / "BTC-15m.json"])
    seen: list = []
    _watch(monkeypatch, seen)
    got = ri.rebuild(resume=False)
    assert got["rebuilt"] is True and got["pairs"] == 3
    assert sorted(seen) == ["BTC-15m", "BTC-1h", "ETH-15m"], \
        "resume=False re-reads everything"


# ------------------------------------------- it must not fight another job
def test_it_waits_for_a_job_that_is_writing_the_same_pair_files(store, monkeypatch):
    """`write_available()` said FREE at 12:56pm while a collect was 14 shards
    into 20: that job holds rows.db's write lock only at the very end. A lock
    answers "may I write?"; a multi-hour bulk pass has to ask "am I the only
    one working?".
    """
    from tradingagents import db_jobs as dj
    monkeypatch.setattr(dj, "status",
                        lambda kind: {"running": True, "done": 17, "total": 20}
                        if kind == "collect" else {})
    got = ri.rebuild()
    assert got["rebuilt"] is False, got
    assert "collect" in got["why"] and "17 of 20" in got["why"], got["why"]
    assert not ri.DB_PATH.with_suffix(".rebuild.db").exists(), \
        "a refusal must not leave a file behind"


def test_a_running_job_can_be_overridden_on_purpose(store, monkeypatch):
    """The operator may know something the job file does not. It is opt-IN,
    never the default — RCA-F was a speed-up that defaulted to on."""
    from tradingagents import db_jobs as dj
    monkeypatch.setattr(dj, "status",
                        lambda kind: {"running": True} if kind == "backtest"
                        else {})
    assert ri.rebuild()["rebuilt"] is False
    assert ri.rebuild(force=True)["rebuilt"] is True


def test_a_job_state_that_cannot_be_read_does_not_block_the_rebuild(store, monkeypatch):
    """A refusal has to be evidence, not an accident: an unreadable job file
    is not proof that a job is running."""
    from tradingagents import db_jobs as dj

    def boom(kind):
        raise OSError("gone")

    monkeypatch.setattr(dj, "status", boom)
    assert ri.jobs_writing() == ""
    assert ri.rebuild()["rebuilt"] is True


def test_index_pair_reports_what_LANDED_not_what_it_read(store):
    """A row with no coin is skipped by the insert. Returning the file's
    length counted it anyway, and rebuild() compares its running total against
    `SELECT count(*)` before it dares swap: one coinless row in 5,366 files
    would have thrown away a two-hour rebuild.
    """
    f = msw.ROWDIR / "ZZZ-1h.json"
    f.write_text(json.dumps([
        {"id": "a", "coin": "ZZZ", "tf": "1h", "signal": "rsi14",
         "sizing": "flat", "trades": 5, "winrate": 80.0, "profit": 1.0},
        {"id": "b", "tf": "1h", "signal": "rsi14"},        # no coin: skipped
    ]), encoding="utf-8")
    ri.ensure()
    assert ri.index_pair(f) == 1, "one row landed, not two"
    got = ri.rebuild()
    assert got["rebuilt"] is True, got
    assert got["rows"] == 76, got


def test_the_resume_check_never_scans_the_big_table(store):
    """Measured on the real 2.74 GB partial: `PRAGMA quick_check` on a fresh
    connection ran at **1 MB/s and would have taken 45 minutes**, while a
    plain sequential read of the same disk measured **106 MB/s** in the same
    minute — a fresh `sqlite3.connect` gets a 2 MB page cache and walks the
    b-tree, so a mechanical disk serves it as random 4 KB reads. On the
    finished 32 GB file that is ~9 hours to decide whether to save 30 minutes.

    So the resume reads the SUMMARY table only. What guards the file is the
    verify before the swap, on the loading connection with its 500 MB cache.
    """
    src = inspect.getsource(ri._resumable)
    assert "quick_check" not in src.split('"""')[2], \
        "the resume path must not run quick_check — it costs more than it saves"
    assert "count(*) FROM rows" not in src, \
        "and it must not count the big table either; SUM(n) is the same number"
    # the guard that DOES protect the swap is still there
    assert "quick_check" in inspect.getsource(ri.rebuild)


def test_the_row_count_a_pair_reports_is_what_the_index_HOLDS(store):
    """`SUM(n) FROM pairs` is what the screen prints as the store's row count
    (`_rows_estimate`) and what a coin filter counts with — so a row the
    insert skipped must not be in `n`, or the operator is told they can find a
    row that is not there."""
    f = msw.ROWDIR / "NOCOIN-1h.json"
    f.write_text(json.dumps([
        {"id": "a", "coin": "NOCOIN", "tf": "1h", "signal": "rsi14",
         "sizing": "flat", "trades": 5, "winrate": 80.0, "profit": 1.0},
        {"id": "b", "tf": "1h", "signal": "rsi14"},        # no coin: skipped
    ]), encoding="utf-8")
    ri.ensure()
    ri.index_pair(f)
    with ri._open(readonly=True) as con:
        n = int(con.execute(
            "SELECT n FROM pairs WHERE pair='NOCOIN-1h'").fetchone()[0])
        real = int(con.execute(
            "SELECT count(*) FROM rows WHERE pair='NOCOIN-1h'").fetchone()[0])
    assert n == real == 1, f"n={n} but the index holds {real}"
    assert ri._rows_estimate() == int(
        ri.status().get("rows") or 0), "the two must agree"


def test_a_resume_seeds_the_row_count_from_the_summaries(store):
    """The seeded total has to be EXACT: `rebuild()` compares it against
    `SELECT count(*)` before it dares swap, so a seed that is off by one row
    throws away the whole run at the last step."""
    _partial([msw.ROWDIR / "BTC-15m.json", msw.ROWDIR / "BTC-1h.json"])
    got = ri._resumable(ri.DB_PATH.with_suffix(".rebuild.db"),
                        {f.stem for f in msw.ROWDIR.glob("*.json")})
    assert isinstance(got, tuple), got
    pairs, rows = got
    assert pairs == {"BTC-15m", "BTC-1h"}
    assert rows == 50, f"30 + 20 rows, got {rows}"
    assert ri.rebuild()["rows"] == 75


# --------------------------------------------- the delete that cost 54 hours
def test_the_load_does_not_delete_per_pair(store):
    """MEASURED, Sep 10, 2026, on the real 2.94 GB partial:

        EXPLAIN QUERY PLAN SELECT count(*) FROM rows WHERE pair = 'NOPE-1h'
        -> SCAN rows
        -> 39.9 seconds

    `index_pair` deletes the pair's rows before inserting them, and
    delete-by-pair needs `rows_pair` — the one index CLAUDE.md says a bulk
    fill may never drop. `rebuild()` builds with NO indexes, so every pair
    paid a full scan of a table that grows with every pair: 4,917 pairs left
    x 39.9 s = **54 hours**, rising. That is why the first run did 40.15
    pairs/min on an empty table and 0.25 by pair 448.
    """
    ri.rebuild()
    src = inspect.getsource(ri.rebuild)
    assert "index_pair(f, con, fresh=True)" in src, \
        "the rebuild's loop must not delete per pair — it has no rows_pair"


def test_fresh_skips_the_delete_and_the_default_still_deletes(store):
    """`fresh` is opt-IN. Every other caller (`sync`, the row UPDATE button,
    the trickle) re-indexes a pair that IS already there, and for them the
    delete is the whole point — RCA-2026-09-10-A was a lost delete."""
    ri.ensure()
    f = msw.ROWDIR / "BTC-15m.json"
    with ri._open() as con:
        ri.index_pair(f, con)
        ri.index_pair(f, con)                    # default: replaces
        n = int(con.execute("SELECT count(*) FROM rows "
                            "WHERE pair='BTC-15m'").fetchone()[0])
    assert n == 30, f"the default must still delete first, got {n}"
    with ri._open() as con:
        ri.index_pair(f, con, fresh=True)        # promised it was absent
        n = int(con.execute("SELECT count(*) FROM rows "
                            "WHERE pair='BTC-15m'").fetchone()[0])
    assert n == 60, "fresh=True skips the delete, which is why it must be earned"


def test_a_resume_earns_fresh_with_one_scan_not_thousands(store):
    """The proof `fresh=True` rests on: rows whose pair has no summary row
    cannot survive the resume. One `SCAN rows`, once — against one per pair."""
    dest = _partial([msw.ROWDIR / "BTC-15m.json"])
    con = sqlite3.connect(dest)
    # exactly what a kill mid-transaction can leave: rows with no summary
    con.execute("INSERT INTO rows (coin,tf,signal,pair) VALUES "
                "('ETH','15m','rsi14','ETH-15m')")
    con.commit()
    con.close()
    got = ri._resumable(dest, {f.stem for f in msw.ROWDIR.glob("*.json")})
    assert isinstance(got, tuple), got
    con = sqlite3.connect(dest)
    left = int(con.execute("SELECT count(*) FROM rows "
                           "WHERE pair='ETH-15m'").fetchone()[0])
    con.close()
    assert left == 0, "a torn pair's rows must be gone before the loop trusts it"
    out = ri.rebuild()
    assert out["rebuilt"] is True and out["rows"] == 75, out


def test_the_scan_is_named_in_the_source_so_it_is_not_re_added(store):
    """This is the second time a check that scans the big table has been put
    in this path in one afternoon (RCA-J was the first). The measurement lives
    beside the code."""
    assert "SCAN rows" in inspect.getsource(ri.index_pair)
    assert "39.9" in inspect.getsource(ri.index_pair), \
        "the measured cost must stay next to the reason"
