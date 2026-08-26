"""Stored strategies can be ranked by WIN RATE, not only by profit.

Operator, 2026-08-26: "i want winrate can you add option to sortby winrate in
stored strategies". The index already stores `winrate`; the query hard-coded
`ORDER BY profit DESC`, so the highest-win-rate configuration in a 21-million
row store could not be found from the screen at all.

The sort name arrives from a URL, so it is whitelisted rather than
interpolated — `?sort=profit; DROP TABLE rows` must be refused, not run.
"""
import json

import pytest

from tradingagents import market_sweep as msw, rows_index as ri


def _row(coin, tf, signal, profit, winrate, trades=120, sizing="flat"):
    wins = round(trades * winrate / 100)
    return {"coin": coin, "tf": tf, "signal": signal, "th": 0.1, "sl": 0.3,
            "tp": 0.9, "rr": 3.0, "sizing": sizing, "lev": 20, "base": 5.0,
            "notional": 100.0, "trades": trades, "wins": wins,
            "losses": trades - wins, "winrate": winrate, "profit": profit,
            "funding": -0.2, "h1": profit / 2, "h2": profit / 2, "green": 8,
            "months": 12, "worst": -4.1, "dd": 22.0, "liqs": 0,
            "stop_reachable": True, "days": 360, "bars": 34000,
            "monthly": {"2026-08": profit / 3}, "cost_of_tp": 12.5,
            "rt": 0.04, "gate": "ok"}


def _settled(**kw):
    import time

    return ri.sync(now=time.time() + ri.SETTLE_S + 1, **kw)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Profit and win rate deliberately DISAGREE, so a sort that silently
    ignores its argument cannot pass."""
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    batch = [
        _row("BTC", "1h", "mom6", 100.0, 31.0),      # best profit, worst rate
        _row("BTC", "1h", "rsi14", 40.0, 77.5),      # best win rate
        _row("BTC", "1h", "trend50", 70.0, 55.0),
        _row("BTC", "1h", "fade15", -5.0, 91.0, trades=110),   # a losing 91%
    ]
    (rows_dir / "BTC-1h.json").write_text(json.dumps(batch))
    _settled()
    return batch


def test_the_default_order_is_still_profit(store):
    got = ri.query()
    assert [r["signal"] for r in got["rows"]] == ["mom6", "trend50", "rsi14", "fade15"]


def test_sorting_by_winrate_puts_the_highest_rate_first(store):
    got = ri.query(sort="winrate")
    assert [r["signal"] for r in got["rows"]] == ["fade15", "rsi14", "trend50", "mom6"]
    assert [r["winrate"] for r in got["rows"]] == [91.0, 77.5, 55.0, 31.0]
    assert got["sort"] == "winrate", "the payload says how it was ordered"


def test_the_profitable_filter_still_applies_when_sorting_by_winrate(store):
    got = ri.query(sort="winrate", profitable=True)
    assert [r["signal"] for r in got["rows"]] == ["rsi14", "trend50", "mom6"], \
        "the 91% loser is filtered out, not ranked first"


def test_trades_is_offered_too_so_a_thin_row_can_be_spotted(store):
    got = ri.query(sort="trades")
    assert got["rows"][0]["trades"] >= got["rows"][-1]["trades"]
    assert got["sort"] == "trades"


@pytest.mark.parametrize("bad", ["profit; DROP TABLE rows", "rowid", "1",
                                 "profit DESC", "monthly"])
def test_an_unknown_sort_is_refused_not_interpolated(store, bad):
    with pytest.raises(ValueError):
        ri.query(sort=bad)
    # and the store is intact
    assert ri.query()["total"] == 4


def test_a_missing_sort_falls_back_to_profit(store):
    """`?sort=` is an absent parameter, not an attack: it means default."""
    for empty in ("", None):
        got = ri.query(sort=empty)
        assert got["sort"] == "profit"
        assert got["rows"][0]["signal"] == "mom6"


def test_every_offered_sort_is_a_real_indexed_column(store):
    for name in ri.SORTS:
        got = ri.query(sort=name, limit=2)
        assert got["sort"] == name and len(got["rows"]) == 2


def test_the_winrate_sort_has_an_index_behind_it():
    """21 million rows: an unindexed ORDER BY is a full sort on every poll."""
    ddl = " ".join(ri.FILTER_INDEXES.values()) + " ".join(ri.KEEP_INDEXES)
    assert "rows (winrate DESC" in ddl or "rows (winrate DESC, id)" in ddl


def test_the_api_passes_the_sort_through_and_validates_it(store, monkeypatch):
    from tradingagents import api

    got = api.strategies(sort="winrate")
    assert got["sort"] == "winrate"
    assert got["rows"][0]["signal"] == "fade15"

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        api.strategies(sort="nonsense")
    assert exc.value.status_code == 400
    assert "winrate" in str(exc.value.detail), "the error names what IS allowed"


def test_an_order_whose_index_is_missing_is_refused_not_run(store, monkeypatch):
    """Measured 2026-08-26 on the operator's 21,582,584-row store: an
    unindexed `ORDER BY winrate DESC` had not returned after ten minutes, and
    the screen showed HTTP 500 under a caption that already claimed "top 300
    by win %". Refuse fast, say why, build the index behind it."""
    built = []
    # a big store: the guard only bites at size (UNINDEXED_LIMIT)
    monkeypatch.setattr(ri, "_rows_estimate", lambda: ri.UNINDEXED_LIMIT + 1)
    monkeypatch.setattr(ri, "has_index", lambda name: False)
    monkeypatch.setattr(ri, "build_sort_index", lambda sort: built.append(sort) or True)
    with pytest.raises(ri.SortNotReady) as exc:
        ri.query(sort="winrate")
    assert "winrate" in str(exc.value) and "index" in str(exc.value)
    assert built == ["winrate"], "and the build is kicked off, not just refused"
    # profit is always indexed, so the default view never depends on this
    monkeypatch.setattr(ri, "has_index", lambda name: name == "rows_profit")
    assert ri.query(sort="profit")["sort"] == "profit"


def test_a_small_store_sorts_without_waiting_for_an_index(store, monkeypatch):
    """4,000 rows sort instantly; refusing them would be pure ceremony."""
    monkeypatch.setattr(ri, "has_index", lambda name: False)
    got = ri.query(sort="winrate")
    assert [r["winrate"] for r in got["rows"]] == [91.0, 77.5, 55.0, 31.0]


def test_build_sort_index_creates_it_once_and_query_then_works(store):
    import time

    assert ri.has_index("rows_winrate") in (True, False)
    if not ri.has_index("rows_winrate"):
        assert ri.build_sort_index("winrate") is True
        for _ in range(50):
            if ri.has_index("rows_winrate"):
                break
            time.sleep(0.1)
    assert ri.has_index("rows_winrate"), "the index exists after the build"
    assert ri.build_sort_index("winrate") is False, "and it is not built twice"
    assert [r["winrate"] for r in ri.query(sort="winrate")["rows"]] == [91.0, 77.5, 55.0, 31.0]


def test_the_api_says_503_while_the_index_builds(store, monkeypatch):
    from fastapi import HTTPException

    from tradingagents import api

    monkeypatch.setattr(ri, "_rows_estimate", lambda: ri.UNINDEXED_LIMIT + 1)
    monkeypatch.setattr(ri, "has_index", lambda name: False)
    monkeypatch.setattr(ri, "build_sort_index", lambda sort: True)
    with pytest.raises(HTTPException) as exc:
        api.strategies(sort="winrate")
    assert exc.value.status_code == 503
    assert "being built" in str(exc.value.detail)


def test_min_trades_keeps_a_one_trade_100_percent_row_off_the_top(store, monkeypatch):
    """Live on the operator's store, ranking by win rate returned
    `BRL 15m rsidiv 100.00% over 6 trades` and `CHF 30m soldiers 100% over 1`.
    A rate needs its denominator to mean anything, so the panel can demand a
    trade count — in the unit the trades column prints (CLAUDE.md rule G)."""
    import json

    extra = [_row("BTC", "1h", "fluke", 3.0, 100.0, trades=2),
             _row("BTC", "1h", "thin", 1.0, 95.0, trades=20)]
    (ri.msw.ROWDIR / "BTC-1h.json").write_text(json.dumps(store + extra))
    _settled(force=True)

    loose = ri.query(sort="winrate", min_trades=0)
    assert loose["rows"][0]["signal"] == "fluke", "unfiltered, the 2-trade row wins"

    got = ri.query(sort="winrate", min_trades=100)
    assert [r["signal"] for r in got["rows"]] == ["fade15", "rsi14", "trend50", "mom6"]
    assert all(r["trades"] >= 100 for r in got["rows"])
    assert got["min_trades"] == 100, "the payload says what it demanded"
    assert got["total"] == 4, "and the count is of what MATCHES, not the store"


def test_min_trades_is_a_count_not_a_percentage(store):
    """It filters the column the trades header prints: 110 means 110 trades."""
    assert ri.query(sort="winrate", min_trades=111)["total"] == 3
    assert ri.query(sort="winrate", min_trades=121)["total"] == 0


def test_the_api_passes_min_trades(store):
    from tradingagents import api

    got = api.strategies(sort="winrate", min_trades=115)
    assert got["min_trades"] == 115
    assert all(r["trades"] >= 115 for r in got["rows"])


def test_the_row_query_keeps_its_order_index_even_with_a_trade_floor(store):
    """The plan, not just the answer.

    The moment rows_trades existed the planner filtered on `trades` and then
    sorted every match — `USE TEMP B-TREE FOR ORDER BY` over 21,858,026 rows —
    so a request that answered in 0.08 s stopped returning and the browser got
    HTTP 500 from the proxy's 30 s timeout. `+trades` keeps the ORDER BY index.
    """
    where, args = ri._where(min_trades=100)
    assert where == " WHERE trades >= ?" and args == [100], where
    row_where, row_args = ri._where(min_trades=100, order_owns_index=True)
    assert row_where == " WHERE +trades >= ?", row_where
    assert row_args == [100]

    src = open("tradingagents/rows_index.py", encoding="utf-8").read()
    q = src[src.index("def query("):src.index("def facets(")]
    assert "FROM rows{row_where}" in q, "the row select must use the +trades form"
    assert "FROM rows{where}" in q, "and the count the plain one"


def test_the_answer_is_still_right_with_the_hint(store):
    got = ri.query(sort="winrate", min_trades=100)
    assert [r["winrate"] for r in got["rows"]] == [91.0, 77.5, 55.0, 31.0]
    assert all(r["trades"] >= 100 for r in got["rows"])


def test_a_second_click_flips_the_direction(store):
    """Operator: "when i click win% it does not sort to highes or lowest" — one
    click is descending, the next ascending, off the same index."""
    down = ri.query(sort="winrate", desc=True)
    up = ri.query(sort="winrate", desc=False)
    assert [r["winrate"] for r in down["rows"]] == [91.0, 77.5, 55.0, 31.0]
    assert [r["winrate"] for r in up["rows"]] == [31.0, 55.0, 77.5, 91.0]
    assert down["desc"] is True and up["desc"] is False


def test_the_direction_default_is_the_useful_end_of_each_column(store):
    """Best profit and best win rate are the TOP; the smallest dip is the
    BOTTOM — so each column's default direction is the one worth seeing."""
    assert ri.query(sort="profit")["desc"] is True
    assert ri.query(sort="winrate")["desc"] is True
    assert ri.query(sort="trades")["desc"] is True
    assert ri.query(sort="dd")["desc"] is False, "smallest worst-dip first"


def test_the_api_carries_the_direction(store):
    from tradingagents import api

    got = api.strategies(sort="winrate", desc=False)
    assert got["desc"] is False
    assert got["rows"][0]["winrate"] == 31.0
