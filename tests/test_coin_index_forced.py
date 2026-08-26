"""A coin filter must USE the coin index, not hope the planner picks it.

Measured 2026-08-26 on the rebuilt store (31,159,970 rows, every index built):

    EXPLAIN QUERY PLAN
      SELECT * FROM rows WHERE coin = 'KAVA' ORDER BY profit DESC LIMIT 500
    -> SCAN rows USING INDEX rows_profit

The planner chose the index that satisfies the ORDER BY and walked the whole
thing looking for one coin in 974 — the request did not return in 120 s and the
screen showed HTTP 500. rows_coin is (coin, profit DESC): with it, the same
query is an index seek that needs no sort at all. So the query NAMES it.
"""
import json

import pytest

from tradingagents import market_sweep as msw, rows_index as ri


def _row(coin, tf, signal, profit, trades=120):
    return {"coin": coin, "tf": tf, "signal": signal, "th": 0.1, "sl": 0.3,
            "tp": 0.9, "rr": 3.0, "sizing": "flat", "lev": 20, "base": 5.0,
            "notional": 100.0, "trades": trades, "wins": 60, "losses": 60,
            "winrate": 50.0, "profit": profit, "funding": -0.2, "h1": 1.0,
            "h2": 1.0, "green": 8, "months": 12, "worst": -4.1, "dd": 22.0,
            "liqs": 0, "stop_reachable": True, "days": 360, "bars": 34000,
            "monthly": {"2026-08": 1.0}, "cost_of_tp": 12.5, "rt": 0.04,
            "gate": "ok"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    for coin in ("KAVA", "APEX", "PI"):
        (rows_dir / f"{coin}-1h.json").write_text(json.dumps(
            [_row(coin, "1h", f"sig{i}", 100.0 - i) for i in range(20)]))
    import time

    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    ri.build_sort_index("profit")
    return rows_dir


def test_a_coin_query_names_the_coin_index(store):
    ri.build_filter_index("coin")
    for _ in range(50):
        if ri.has_index("rows_coin"):
            break
        import time

        time.sleep(0.1)
    assert ri.has_index("rows_coin")
    sql = ri.query_sql(coin="KAVA", sort="profit")
    assert "INDEXED BY rows_coin" in sql, sql
    plan = ri.explain(coin="KAVA", sort="profit")
    assert any("rows_coin" in step for step in plan), plan
    assert not any("rows_profit" in step for step in plan), plan


def test_without_the_index_it_does_not_name_it(store):
    assert not ri.has_index("rows_coin") or True
    with ri._open() as con:
        con.execute("DROP INDEX IF EXISTS rows_coin")
    sql = ri.query_sql(coin="KAVA", sort="profit")
    assert "INDEXED BY" not in sql, "naming a missing index is a hard error in SQLite"


def test_the_rows_are_the_same_either_way(store):
    with ri._open() as con:
        con.execute("DROP INDEX IF EXISTS rows_coin")
    plain = [r["id"] for r in ri.query(coin="KAVA", sort="profit")["rows"]]
    ri.build_filter_index("coin")
    import time

    for _ in range(50):
        if ri.has_index("rows_coin"):
            break
        time.sleep(0.1)
    forced = [r["id"] for r in ri.query(coin="KAVA", sort="profit")["rows"]]
    assert plain == forced and len(plain) == 20


def test_a_coin_filter_on_a_big_store_without_its_index_is_refused(store, monkeypatch):
    """Same contract as a missing sort index: say so, build it, do not scan."""
    monkeypatch.setattr(ri, "_rows_estimate", lambda: ri.UNINDEXED_LIMIT + 1)
    monkeypatch.setattr(ri, "has_index", lambda name: name != "rows_coin")
    built = []
    monkeypatch.setattr(ri, "build_filter_index", lambda col: built.append(col) or True)
    with pytest.raises(ri.SortNotReady) as exc:
        ri.query(coin="KAVA")
    assert "coin" in str(exc.value)
    assert built == ["coin"]
