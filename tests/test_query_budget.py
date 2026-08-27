"""A read that runs too long says so; it never returns an empty answer.

The UI reaches the API through Next's rewrite, which gives up at 30 s with a
bare HTTP 500 and no body. Measured on the operator's store on 2026-08-27:

    GET /api/strategies?min_winrate=95&limit=500              http 500 @ 30.0s
    GET /api/strategies?min_winrate=50&limit=500              http 500 @ 30.0s
    GET /api/strategies?min_winrate=95&min_trades=100         http 200 @  0.26s

The panel then showed the PREVIOUS rows under the new filter with only a red
line beside them — the screen actively saying the wrong thing about which
filter its numbers belong to.

So the store gives up first, at QUERY_BUDGET_S, and raises QueryTooSlow, which
IS a SortNotReady: the route answers 503, and the panel keeps its rows and
prints the sentence. A sentence in 20 s beats a 500 in 30.

And the interruption must never be swallowed: `_missing_ok` catches
sqlite3.Error to survive a missing schema, and it turned the abort into
"total 0, no rows" — an empty screen presented as an answer.
"""
import json
import sqlite3

import pytest

import tradingagents.rows_index as ri


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri._ready.discard(str(tmp_path / "rows.db"))
    ri.forget_indexes()
    ri.ensure()
    rows = [{"id": f"R{i:04d}", "coin": "AAA", "tf": "1h", "signal": "ema",
             "profit": float(i % 97), "winrate": 50.0 + (i % 50),
             "trades": 40 + i, "dd": 2.0, "monthly": {}}
            for i in range(400)]
    f = tmp_path / "AAA_USDT-1h.json"
    f.write_text(json.dumps(rows), encoding="utf-8")
    with ri._open() as con:
        ri.index_pair(f, con)
    return rows


def test_the_budget_is_a_503_with_a_reason_not_a_500(store, monkeypatch):
    monkeypatch.setattr(ri, "QUERY_BUDGET_S", 0.0)     # every read is too slow
    with pytest.raises(ri.SortNotReady) as got:
        ri.query(min_winrate=60, limit=100)
    said = str(got.value)
    assert "win %" in said and "60" in said, said
    assert "min-trades" in said, "it must say what makes it fast"


def test_it_is_a_sort_not_ready_so_the_screen_keeps_its_rows(store):
    assert issubclass(ri.QueryTooSlow, ri.SortNotReady)


def test_the_route_turns_it_into_503(store, monkeypatch):
    from fastapi import HTTPException

    from tradingagents import api

    monkeypatch.setattr(ri, "QUERY_BUDGET_S", 0.0)
    with pytest.raises(HTTPException) as got:
        api.strategies(min_winrate=60, limit=100)
    assert got.value.status_code == 503
    assert "win %" in str(got.value.detail)


def test_an_interruption_is_never_swallowed_into_an_empty_answer():
    """`_missing_ok` survives a missing schema by returning the default. An
    abort is not a missing schema, and 'total 0, no rows' is not an answer."""
    def _interrupted():
        raise sqlite3.OperationalError("interrupted")

    with pytest.raises(sqlite3.OperationalError):
        ri._missing_ok(_interrupted, "the default")

    def _no_table():
        raise sqlite3.OperationalError("no such table: rows")

    assert ri._missing_ok(_no_table, "the default") == "the default"


def test_a_normal_read_is_untouched_by_the_budget(store):
    got = ri.query(min_winrate=60, min_trades=100, limit=50)
    assert got["rows"] and all(r["winrate"] >= 60 for r in got["rows"])
    assert got["total"] > 0


def test_the_sentence_prints_the_budget_it_actually_used(store, monkeypatch):
    """0.5 must not print as "0s" — the number in the sentence is the number
    the store is set to (label-must-match-data)."""
    monkeypatch.setattr(ri, "QUERY_BUDGET_S", 0.5)
    said = ri._slow_why(None, None, None, 60, 0, "profit")
    assert "0.5s" in said, said
    monkeypatch.setattr(ri, "QUERY_BUDGET_S", 20.0)
    assert "20s" in ri._slow_why(None, None, None, 60, 0, "profit")
