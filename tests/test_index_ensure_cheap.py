"""Opening the index must not rebuild the indexes a bulk fill is about to drop.

Measured 2026-08-26 on the operator's 8.9 GB store: a forced catch-up sat at
7.8 s of CPU for thirteen minutes with the machine otherwise idle. py-spy:

    ensure (rows_index.py:232)   <- for ddl in READ_INDEXES: con.execute(ddl)
    sync (rows_index.py:457)

`ensure()` was recreating rows_winrate, rows_trades, rows_coin, rows_tf and
rows_signal — five index builds, and rows_winrate alone measured 912 s — and
then `sync()` DROPPED all five for the bulk fill and rebuilt them at the end.
The same waste sat in front of every API startup.

So: ensure() creates only the indexes nothing drops (KEEP_INDEXES); the
filter/sort indexes are built by the end of a fill, or on demand by the query
that needs one (build_sort_index).
"""
from tradingagents import rows_index as ri


def test_ensure_only_creates_the_indexes_nothing_drops():
    import inspect

    src = inspect.getsource(ri.ensure)
    assert "KEEP_INDEXES" in src, "ensure must create the kept indexes"
    assert "READ_INDEXES" not in src, \
        "ensure must NOT build the filter indexes a bulk fill drops"


def test_the_fill_still_rebuilds_them_at_the_end():
    import inspect

    src = inspect.getsource(ri.sync)
    assert "FILTER_INDEXES" in src, "sync drops them for the fill"
    assert "DROP INDEX IF EXISTS" in src
    # and puts them back
    assert src.count("FILTER_INDEXES") >= 2, "dropped AND rebuilt"


def test_a_fresh_database_gets_its_tables_and_the_kept_indexes(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri._ready.discard(str(tmp_path / "rows.db"))
    ri.ensure()
    assert ri.has_index("rows_profit"), "the default order must never wait"
    assert ri.has_index("rows_pair"), "delete-by-pair needs it"


def test_a_sort_index_is_built_on_demand_when_it_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows2.db")
    ri._ready.discard(str(tmp_path / "rows2.db"))
    ri.ensure()
    assert not ri.has_index("rows_winrate"), "not built up front any more"
    assert ri.build_sort_index("winrate") is True
    import time

    for _ in range(50):
        if ri.has_index("rows_winrate"):
            break
        time.sleep(0.1)
    assert ri.has_index("rows_winrate"), "the query's guard builds it"
