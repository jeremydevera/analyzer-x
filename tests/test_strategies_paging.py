"""Stored strategies must be walkable, not a 300-row peek.

Operator, 2026-08-26: "why is my stored strategy few? i have 800+ coins and
under those coins i have multiple strategy and under that strategy is
different timeframe and combinations of tp and sl, where are those?"

They were all there — 21,858,026 rows in the index — and the panel fetched
`limit=300` with no way to reach row 301. Measured at the same moment:
15m 8,761,615 rows over 666 pairs, 30m 9,747,810 over 679, 1h 2,555,551 over
475, 4h 793,050 over 375, and KAVA-15m alone holding 17,600 combinations.
"""
import json

import pytest

from tradingagents import market_sweep as msw, rows_index as ri


def _row(coin, tf, signal, profit, trades=120):
    return {"coin": coin, "tf": tf, "signal": signal, "th": 0.1, "sl": 0.3,
            "tp": 0.9, "rr": 3.0, "sizing": "flat", "lev": 20, "base": 5.0,
            "notional": 100.0, "trades": trades, "wins": 60, "losses": 60,
            "winrate": 50.0, "profit": profit, "funding": -0.2,
            "h1": 1.0, "h2": 1.0, "green": 8, "months": 12, "worst": -4.1,
            "dd": 22.0, "liqs": 0, "stop_reachable": True, "days": 360,
            "bars": 34000, "monthly": {"2026-08": 1.0}, "cost_of_tp": 12.5,
            "rt": 0.04, "gate": "ok"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    batch = [_row("BTC", "1h", f"sig{i:03d}", 1000.0 - i) for i in range(250)]
    (rows_dir / "BTC-1h.json").write_text(json.dumps(batch))
    import time

    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    return batch


def test_offset_walks_the_whole_store_without_repeating_a_row(store):
    seen, page = [], 0
    while True:
        got = ri.query(limit=100, offset=page * 100)
        if not got["rows"]:
            break
        seen += [r["id"] for r in got["rows"]]
        page += 1
        assert page < 10, "runaway"
    assert len(seen) == 250, len(seen)
    assert len(set(seen)) == 250, "no row appears on two pages"
    assert got["total"] == 250


def test_a_page_deep_in_the_store_is_the_same_order_as_the_first(store):
    first = ri.query(limit=250)["rows"]
    third = ri.query(limit=100, offset=200)["rows"]
    assert [r["id"] for r in third] == [r["id"] for r in first[200:250]]


def test_the_offset_survives_a_sort_and_a_direction(store):
    up = ri.query(sort="profit", desc=False, limit=10)["rows"]
    up_page2 = ri.query(sort="profit", desc=False, limit=10, offset=10)["rows"]
    assert up[0]["profit"] < up_page2[0]["profit"]
    assert not ({r["id"] for r in up} & {r["id"] for r in up_page2})


def test_the_api_takes_an_offset(store):
    from tradingagents import api

    a = api.strategies(limit=5)
    b = api.strategies(limit=5, offset=5)
    assert [r["id"] for r in a["rows"]] != [r["id"] for r in b["rows"]]
    assert a["total"] == b["total"] == 250
