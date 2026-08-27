"""A deep page must arrive, not time out (2026-08-27).

Clicking page 50,000 of Stored strategies asks for offset 24,999,500. Measured
on the operator's store (35,863,520 rows, mechanical disk, a sweep running):

    SELECT *     ORDER BY profit DESC, id LIMIT 500 OFFSET 24999500
      SCAN rows USING INDEX rows_profit                          60.2 s
    SELECT rowid ORDER BY profit DESC, id LIMIT 500 OFFSET 24999500
      SCAN rows USING COVERING INDEX rows_profit                  1.4 s
    then SELECT * FROM rows WHERE rowid IN (those 500)            0.0 s

`SELECT *` makes rows_profit non-covering, so SQLite reads all 25 million
skipped rows off the disk only to discard them. The browser saw a 500 from
Next's proxy and left the PREVIOUS page's rows sitting under the new page
number — the numbered pager pointing at page 50,000 over page 3's data.

These tests hold the two-phase read shut and, more importantly, prove the two
paths return the SAME rows: a fast page that is a different page is worse than
a slow one.
"""
import json

import pytest

import tradingagents.rows_index as ri


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri._ready.discard(str(tmp_path / "rows.db"))
    ri.forget_indexes()
    ri.ensure()
    for coin in ("AAA", "BBB"):
        rows = [{"id": f"{coin}{i:04d}", "coin": coin, "tf": "1h",
                 "signal": "ema" if i % 3 else "rsi",
                 "profit": float(1000 - i), "winrate": 40 + i % 50,
                 "trades": 100 + i, "dd": 5.0, "monthly": {}}
                for i in range(300)]
        f = tmp_path / f"{coin}_USDT-1h.json"
        f.write_text(json.dumps(rows), encoding="utf-8")
        with ri._open() as con:
            ri.index_pair(f, con)
    return 600


def _ids(**kw):
    return [r["id"] for r in ri.query(**kw)["rows"]]


def test_the_deep_path_returns_exactly_what_the_shallow_path_would(
        store, monkeypatch):
    """The only thing that may differ between the two reads is the clock."""
    for sort, desc in (("profit", True), ("profit", False),
                       ("winrate", True), ("trades", True)):
        monkeypatch.setattr(ri, "DEEP_OFFSET", 10_000)     # shallow
        shallow = _ids(sort=sort, desc=desc, limit=50, offset=120)
        monkeypatch.setattr(ri, "DEEP_OFFSET", 0)          # deep
        deep = _ids(sort=sort, desc=desc, limit=50, offset=120)
        assert deep == shallow and len(deep) == 50, (sort, desc)


def test_the_deep_path_keeps_the_filters(store, monkeypatch):
    monkeypatch.setattr(ri, "DEEP_OFFSET", 10_000)
    shallow = _ids(tf="1h", signal="rsi", profitable=True, limit=25, offset=30)
    monkeypatch.setattr(ri, "DEEP_OFFSET", 0)
    deep = _ids(tf="1h", signal="rsi", profitable=True, limit=25, offset=30)
    assert deep == shallow and deep, deep


def test_a_deep_page_past_the_end_is_empty_not_an_error(store, monkeypatch):
    monkeypatch.setattr(ri, "DEEP_OFFSET", 0)
    got = ri.query(limit=100, offset=10_000)
    assert got["rows"] == []


def test_every_row_appears_on_exactly_one_page_through_the_deep_path(
        store, monkeypatch):
    """Paging is only paging if the pages partition the list."""
    monkeypatch.setattr(ri, "DEEP_OFFSET", 0)
    seen = []
    for page in range(6):
        seen += _ids(sort="profit", limit=100, offset=page * 100)
    assert len(seen) == store == 600
    assert len(set(seen)) == 600, "a row on two pages"


def test_the_deep_read_never_selects_star_over_the_skipped_rows():
    """The whole point: the skip runs over `rowid`, which the ORDER BY's index
    already carries, so 25 million skipped rows are never fetched."""
    import inspect

    src = inspect.getsource(ri._page_rows)
    assert 'sql % "rowid"' in src
    assert "WHERE rowid IN" in src
    # and the second statement re-sorts, because IN returns no order
    assert "ORDER BY %s, id ASC" in src
