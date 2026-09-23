"""Backtest v2's win % filter must say what is really happening, and fast.

`Sep 24, 2026 12:29am`, the operator's filter on Backtest v2 (win % >= 85,
TP >= SL, last 30 days) spun "still working — asking again in a moment" for as
long as it was left. Measured:

* the v2 store (98,986,982 rows) had NO wide win-rate list — rows_wr2, wr3
  and wr4 were all missing — so the read walked the store until the 20 s
  budget and was refused, 27 s per attempt, every 15 s;
* the refusal said "the wide win-rate index ... is still being built" while
  the only build running was rows_pr2, the PROFIT list;
* the three workarounds it offered (min trades 100, rank by win %, name a
  coin) were each refused too, in 13 s, 24 s and 22 s.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def ri(monkeypatch):
    from tradingagents import rows_index as ri

    return ri


def test_it_never_claims_a_build_that_is_not_running(ri, monkeypatch):
    """The PROFIT list building is not the win-rate list building."""
    monkeypatch.setattr(ri, "has_index", lambda n: False)
    monkeypatch.setattr(ri, "build_running", lambda name=None: "rows_pr2")
    monkeypatch.setattr(ri, "_build_index",
                        lambda n: pytest.fail("one build at a time"))

    note = ri._winrate_list_note()

    assert "being built now" not in note, note
    assert "rows_pr2" in note and "starts when" in note, note


def test_it_says_building_only_while_it_is(ri, monkeypatch):
    monkeypatch.setattr(ri, "has_index", lambda n: False)
    monkeypatch.setattr(ri, "build_running", lambda name=None: "rows_wr4")

    assert "being built now" in ri._winrate_list_note()


def test_when_nothing_builds_it_says_so_and_starts_nothing(ri, monkeypatch):
    """A MESSAGE never spawns a process — the first draft did, from a test.
    The refusing read starts the list; the note only reports."""
    monkeypatch.setattr(ri, "has_index", lambda n: False)
    monkeypatch.setattr(ri, "build_running", lambda name=None: "")
    monkeypatch.setattr(ri, "_build_index",
                        lambda n: pytest.fail("a message may not start a build"))

    note = ri._winrate_list_note()

    assert "nothing is building it" in note, note


def test_once_a_list_exists_it_says_nothing(ri, monkeypatch):
    monkeypatch.setattr(ri, "has_index", lambda n: n == "rows_wr2")
    assert ri._winrate_list_note() == ""
    # …but a refusal about rows_wr4 specifically is still about rows_wr4
    monkeypatch.setattr(ri, "build_running", lambda name=None: "rows_wr4")
    assert "rows_wr4" in ri._winrate_list_note("rows_wr4")


def test_no_false_workarounds_while_no_list_exists(ri, monkeypatch):
    """"Add a min-trades floor - 100 answers in 0.2s" was measured on a store
    WITH a wide list; on v2 without one it was refused as well."""
    monkeypatch.setattr(ri, "has_index", lambda n: False)
    monkeypatch.setattr(ri, "build_running", lambda name=None: "rows_wr4")
    monkeypatch.setattr(ri, "_rows_estimate", lambda: 98_986_982)

    why = ri._slow_why(None, None, None, 85, 0, "profit")

    assert "0.2s" not in why and "rank by win" not in why.lower(), why
    assert "being built now" in why


def test_the_old_workarounds_come_back_once_a_list_exists(ri, monkeypatch):
    monkeypatch.setattr(ri, "has_index", lambda n: n == "rows_wr2")
    monkeypatch.setattr(ri, "_rows_estimate", lambda: 98_986_982)
    why = ri._slow_why(None, None, None, 85, 0, "profit")
    assert "min-trades floor" in why


def test_the_refusing_read_starts_the_list(ri, monkeypatch, tmp_path):
    """The promise in the sentence is kept by the read that refused."""
    started: list = []
    monkeypatch.setattr(ri, "has_index", lambda n: not n.startswith("rows_wr"))
    monkeypatch.setattr(ri, "build_running", lambda name=None: "")
    monkeypatch.setattr(ri, "_build_index", lambda n: started.append(n) or True)
    monkeypatch.setattr(ri, "_rows_estimate", lambda: 98_986_982)
    monkeypatch.setattr(ri, "_winrate_index", lambda: "")
    monkeypatch.setattr(ri, "_db", lambda: tmp_path / "rows.db")

    with pytest.raises(ri.SortNotReady):
        ri.query(min_winrate=85, tp_over_sl=True, limit=25)

    assert "rows_wr4" in started, started


def test_the_query_refuses_fast_instead_of_walking_the_store(ri, monkeypatch, tmp_path):
    """No wide list + a win % floor that cannot seek = refuse at once. The
    20 s walk it replaces was refused anyway, every 15 s."""
    monkeypatch.setattr(ri, "has_index", lambda n: not n.startswith("rows_wr"))
    monkeypatch.setattr(ri, "build_running", lambda name=None: "rows_wr4")
    monkeypatch.setattr(ri, "_rows_estimate", lambda: 98_986_982)
    monkeypatch.setattr(ri, "_winrate_index", lambda: "")
    monkeypatch.setattr(ri, "_db", lambda: tmp_path / "rows.db")
    walked: list = []
    monkeypatch.setattr(ri, "_connect", lambda *a, **k: walked.append(1) or
                        pytest.fail("the store may not be walked"), raising=False)

    with pytest.raises(ri.SortNotReady) as got:
        ri.query(min_winrate=85, tp_over_sl=True, limit=25)

    assert "being built now" in str(got.value)


def test_a_list_finished_by_another_process_is_noticed(ri, monkeypatch, tmp_path):
    """Sep 24, 2026 1:32am: rows_wr4 finished in a build child, a fresh process
    answered the filter in 14.6 s, and the API — holding "missing" from an
    hour before — refused it 30 s a time for as long as it ran."""
    import sqlite3

    db = tmp_path / "rows.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE rows (id TEXT, winrate REAL)")
    con.commit()
    monkeypatch.setattr(ri, "_db", lambda: db)
    monkeypatch.setattr(ri, "DB_PATH", db, raising=False)
    ri.forget_indexes()

    assert ri.has_index("rows_wr4") is False
    # another process builds it
    con.execute("CREATE INDEX rows_wr4 ON rows (winrate)")
    con.commit()
    con.close()
    assert ri.has_index("rows_wr4") is False, "within the minute it may still say missing"

    # a minute later the cache must look again
    key = (str(db), "rows_wr4")
    ri._INDEX_MISSING_AT[key] -= ri.INDEX_MISSING_TTL_S + 1
    assert ri.has_index("rows_wr4") is True, \
        "a finished index stayed 'missing' until the app was restarted"
    ri.forget_indexes()


def test_exists_is_remembered_forever(ri, monkeypatch, tmp_path):
    """Only the MISSING answer expires — an existing index is never re-read,
    which is what keeps a 4 s poll cheap."""
    key = (str(tmp_path / "x.db"), "rows_wr4")
    monkeypatch.setattr(ri, "_db", lambda: tmp_path / "x.db")
    ri._INDEX_SEEN[key] = True
    monkeypatch.setattr(ri, "_open", lambda *a, **k: pytest.fail("no re-read"))
    try:
        assert ri.has_index("rows_wr4") is True
    finally:
        ri._INDEX_SEEN.pop(key, None)
