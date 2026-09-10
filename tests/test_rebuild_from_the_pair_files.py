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
