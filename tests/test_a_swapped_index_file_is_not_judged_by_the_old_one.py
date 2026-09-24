"""A rebuilt index swapped in by another process is read as it is
(RCA-2026-09-25-A).

Sep 25, 2026 ~1:01am the Backtest v2 index was rebuilt flat-only and swapped
in under the running API: 98,986,982 rows became 49,503,932, and the fresh
file carried only rows_pair / rows_profit / rows_coin / rows_winrate. The
API had cached "rows_id exists" for the OLD file — "IT EXISTS IS FOREVER",
because an index was thought to disappear only through a drop in the same
process — so an id search sent `INDEXED BY rows_id` to a file without it:
`/api/v2/strategies?row_id=5JWGQZPG` answered HTTP 500 "Internal Server
Error". `_missing_ok` forgot the cache and RE-RAISED, so only the NEXT search
would have planned from reality.

Two halves: the cache is keyed by the FILE at the path, and a stale-index
error is asked once more instead of becoming a 500.
"""
from __future__ import annotations

import json
import os
import sqlite3

import pytest

from tradingagents import market_sweep as msw, rows_index as ri


def _row(i, *, sizing="flat"):
    return {"coin": "GPNSTOCK", "tf": "30m", "signal": "keltner", "th": 0.0,
            "sl": 2.0, "tp": 3.0 + i / 10, "rr": 1.5, "sizing": sizing,
            "lev": 20, "base": 5.0, "notional": 100.0, "trades": 28,
            "wins": 27, "losses": 1, "winrate": 96.43, "profit": 73.53 - i,
            "funding": -0.01, "h1": 19.63, "h2": 53.89, "green": 2,
            "months": 2, "worst": -2.21, "dd": 2.21, "liqs": 0,
            "stop_reachable": True, "days": 29, "bars": 1439,
            "monthly": {"2026-09": 53.89}, "cost_of_tp": 6.5, "rt": 0.1953,
            "gate": "ok", "unclear": 0}


@pytest.fixture
def store(tmp_path, monkeypatch):
    (tmp_path / "rows").mkdir()
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri.forget_indexes()
    ri.ensure()
    f = tmp_path / "rows" / "GPNSTOCK-30m.json"
    f.write_text(json.dumps([_row(i) for i in range(5)]))
    ri.index_pair(f)
    yield tmp_path
    ri.forget_indexes()


def _add_id_index(db):
    con = sqlite3.connect(db)
    con.execute(ri.ROW_ID_INDEX)
    con.commit()
    con.close()


def test_a_file_swapped_in_under_the_same_name_is_asked_again(store):
    db = store / "rows.db"
    _add_id_index(db)
    assert ri.has_index("rows_id") is True          # cached for THIS file
    # what rebuild() does from another process: a fresh file, same name,
    # without the on-demand index — and nobody tells this process
    fresh = store / "fresh.db"
    con = sqlite3.connect(fresh)
    con.execute("CREATE TABLE rows (id TEXT)")
    con.commit()
    con.close()
    os.replace(fresh, db)
    assert ri.has_index("rows_id") is False, \
        "an index cached for the old file was believed of the new one"


def test_a_stale_index_is_asked_again_not_a_500(store):
    """The other way a cache goes stale: a drop in ANOTHER process, same file.
    The first plan names the missing index; the retry plans from the file."""
    code = json.loads((store / "rows" / "GPNSTOCK-30m.json").read_text())[0]
    want = ri._row_id(code)
    key = ri.index_cache_key("rows_id")
    ri._INDEX_SEEN[key] = True                       # believed, not there
    got = ri.query(row_id=want)
    assert [r["id"] for r in got["rows"]] == [want]


def test_both_read_doors_carry_the_retry():
    for fn in (ri.query, ri.export_plan):
        assert getattr(fn, "__wrapped__", None), f"{fn.__name__} has no retry"
