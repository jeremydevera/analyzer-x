"""Every index in the set is paid for after EVERY bulk fill — so keep few.

A fill drops FILTER_INDEXES and rebuilds them at the end. Measured on the
operator's 31,159,970-row store, one index at a time:

    rows_coin     16.7 min      <- the coin filter needs it (INDEXED BY)
    rows_winrate   4.4 min      <- the operator's win-rate ranking
    rows_tf        4.1 min      <- never chosen: _where hints tf aside
    rows_signal    4.3 min      <- never chosen: same
    rows_id        3.5 min      <- nothing queries by id yet
    rows_trades    3.4 min      <- the count is LIMIT-bounded without it

Carrying the four unused ones cost ~15 minutes of rebuild after every fill,
and the sweep produces a fill every few hours. The set holds what a plan
actually names.
"""
from tradingagents import rows_index as ri


def test_only_the_indexes_a_plan_names_are_maintained():
    assert set(ri.FILTER_INDEXES) == {"rows_coin", "rows_winrate"}, \
        sorted(ri.FILTER_INDEXES)
    kept = " ".join(ri.KEEP_INDEXES)
    assert "rows_profit" in kept, "the default view must never wait"
    assert "rows_pair" in kept, "delete-by-pair needs it"


def test_the_sorts_that_have_no_index_are_not_offered_as_indexed():
    # trades and dd still SORT, they just do not claim an index behind them
    assert ri.SORT_INDEX["profit"] == "rows_profit"
    assert ri.SORT_INDEX["winrate"] == "rows_winrate"
    assert ri.SORT_INDEX["trades"] is None
    assert ri.SORT_INDEX["dd"] is None


def test_a_sort_with_no_index_is_never_refused(tmp_path, monkeypatch):
    """No index means no promise to keep: it sorts, and on a big store the
    LIMIT keeps it honest. Refusing it would remove a working feature."""
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    monkeypatch.setattr(ri, "_rows_estimate", lambda: ri.UNINDEXED_LIMIT + 1)
    monkeypatch.setattr(ri, "has_index", lambda name: False)
    ri._ready.discard(str(tmp_path / "rows.db"))
    ri.ensure()
    got = ri.query(sort="trades")          # must not raise SortNotReady
    assert got["sort"] == "trades"


def test_a_locked_read_does_not_look_like_a_missing_index(tmp_path, monkeypatch):
    """has_index() answered False when the DB was merely LOCKED, so the guard
    refused a coin filter while rows_coin sat right there — 503 in 0.02 s with
    every index present (2026-08-26)."""
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "locked.db")
    ri._ready.discard(str(tmp_path / "locked.db"))
    ri.ensure()
    assert ri.has_index("rows_profit") is True

    import sqlite3

    def boom(*a, **kw):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ri, "_connect", boom)
    assert ri.has_index("rows_profit") is True, "a lock must not erase the answer"
    assert ri.has_index("rows_nonexistent") is None, "unknown, not absent"
