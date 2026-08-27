"""A TAKE-PROFIT floor, typed as a number, applied in the store.

Operator, 2026-08-27: "add filter 'TP' when i input 4 then show that has TP
equal or greater than 4".

TP is the profit target a winning trade aims at, so this box means "only show
me strategies going for 4% a trade or more". Three things this holds shut:

* the unit is the one the TP% column PRINTS. 4 means 4%, not 0.04, and a row
  at exactly 4.0 SURVIVES the floor (CLAUDE.md rule G).
* the floor runs in SQLite, not on the page — the same reason the win % floor
  does: the widest-TP row in the store is not on the first page.
* the box only offers TP values the measuring grid produced, and stops at the
  largest. `tp` has no index, so proving nothing matches costs a scan of every
  row: measured on the operator's store (35,863,520 rows), `tp >= 4` answered
  in 0.02 s and `tp >= 10` — a value only the 1d grid has, and this store holds
  no 1d rows — had not returned after 25 s.
"""
import json

import pytest

from tradingagents import market_sweep as msw, rows_index as ri


def _row(coin, tf, signal, profit, tp, winrate=60.0, trades=120,
         sizing="flat"):
    wins = round(trades * winrate / 100)
    return {"coin": coin, "tf": tf, "signal": signal, "th": 0.1, "sl": 0.3,
            "tp": tp, "rr": 3.0, "sizing": sizing, "lev": 20, "base": 5.0,
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
    """TPs that straddle 4 exactly, and the WIDEST TP is the WORST profit — so
    a floor that quietly did nothing would still look plausible."""
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    (rows_dir / "AAA-1h.json").write_text(json.dumps([
        _row("AAA", "1h", "wide8", 12.0, 8.0),
        _row("AAA", "1h", "wide5", 30.0, 5.0),
        _row("AAA", "1h", "exact4", 44.0, 4.0),      # the boundary: stays
        _row("AAA", "1h", "just_under", 99.0, 3.0),   # best profit: goes
        _row("AAA", "1h", "tight", 80.0, 0.6),
    ]))
    (rows_dir / "BBB-4h.json").write_text(json.dumps([
        _row("BBB", "4h", "wide6", 25.0, 6.0, winrate=71.0),
        _row("BBB", "4h", "tight", 61.0, 0.4, winrate=88.0),
    ]))
    _settled()
    return None


def test_four_means_tp_four_percent_or_wider(store):
    got = ri.query(min_tp=4)
    assert sorted(r["signal"] for r in got["rows"]) == [
        "exact4", "wide5", "wide6", "wide8"]
    assert all(r["tp"] >= 4 for r in got["rows"])
    assert got["total"] == 4, "the count is of what MATCHES, not the store"


def test_the_boundary_row_is_kept_and_the_one_below_it_is_not(store):
    """"equal or greater than 4" — a row at exactly 4.0 must survive, and the
    3.0 row goes even though it has the best profit in the store."""
    tps = [r["tp"] for r in ri.query(min_tp=4)["rows"]]
    assert 4.0 in tps
    assert 3.0 not in tps
    assert "just_under" not in [r["signal"] for r in ri.query(min_tp=4)["rows"]]


def test_it_is_a_percent_not_the_fraction_the_grid_stores(store):
    """BARRIERS holds .040; the rows and this box hold 4.0. Typed as 0.04 a
    floor would match every row in the store and read as broken."""
    assert ri.query(min_tp=0.04)["total"] == 7, "0.04% keeps everything"
    assert ri.query(min_tp=6)["total"] == 2       # 8.0 and 6.0
    assert ri.query(min_tp=9)["total"] == 0


def test_the_payload_says_the_floor_it_applied(store):
    """The caption is DERIVED from this, never from a literal beside it."""
    got = ri.query(min_tp=5)
    assert got["min_tp"] == 5.0
    assert all(r["tp"] >= 5 for r in got["rows"])
    assert ri.query()["min_tp"] == 0.0


def test_it_stacks_with_the_other_floors_and_filters(store):
    got = ri.query(min_tp=4, min_winrate=70, min_trades=100)
    assert [r["signal"] for r in got["rows"]] == ["wide6"]
    assert ri.query(min_tp=4, tf="1h")["total"] == 3
    assert ri.query(min_tp=4, coin="BBB")["total"] == 1


def test_the_row_query_keeps_the_order_its_index(store):
    """`tp` is indexed by nothing, so the term cannot steal a plan — but it
    still steps aside in the ROW query, which is what keeps the ORDER BY's own
    index the day someone adds one. Measured identical on the real store:
    `tp >= 4 ORDER BY profit LIMIT 500` was 0.02 s either way.
    """
    where, args = ri._where(min_tp=4)
    assert where == " WHERE tp >= ?" and args == [4.0], where
    row_where, row_args = ri._where(min_tp=4, order_owns_index=True,
                                    order_key="profit")
    assert row_where == " WHERE +tp >= ?", row_where
    assert row_args == [4.0]
    assert "WHERE +tp >= ?" in ri.query_sql(sort="profit", min_tp=4)
    assert "WHERE +tp >= ?" in ri.query_sql(sort="winrate", min_tp=4)
    # The PLAN is not asserted here: SQLite is cost-based, and on a seven-row
    # fixture it scans whatever it is asked, index or no index (measured:
    # `ORDER BY winrate DESC` alone plans USE TEMP B-TREE on this store and
    # SCAN rows USING INDEX rows_winrate on the operator's 35,863,520). What
    # is size-independent — and what the `+` buys — is the SQL above. The real
    # plans are asserted against a big store in test_strategies_sort.py and
    # test_coin_index_forced.py.
    for sort in ("profit", "winrate"):
        plan = " ".join(ri.explain(sort=sort, min_tp=4)).upper()
        assert "TP" not in plan, ("tp has no index to steal", sort, plan)


def test_the_box_only_offers_tps_the_grid_measured(store):
    """The values come from BARRIERS for the timeframes the store HOLDS, so
    the ceiling is derived, never a round number typed into the panel.

    This store holds 1h and 4h and no 1d, so the widest TP anywhere in it is
    8% — and 8 is exactly where the box stops. On the operator's real store
    that is the difference between 0.03 s and a 25-second full scan that can
    only ever answer "nothing".
    """
    from tradingagents import backtest_report as br

    facets = ri.facets()
    offered = facets["tps"]
    assert offered, "the panel needs values to offer"
    assert max(offered) == 8.0, offered
    assert 4.0 in offered and 10.0 not in offered
    # every offered value is a real grid TP, in percent, for the timeframes
    # THIS store holds — derived from the data, never a typed ladder
    assert facets["tfs"] == ["1h", "4h"], facets["tfs"]
    grid = {round(tp * 100, 6) for tf in facets["tfs"]
            for _sl, tp in br.BARRIERS[tf]}
    assert set(offered) == grid
    # and a store WITH 1d reaches 20%, so the ceiling follows the data
    assert max(ri.take_profits(["1d"])) == 20.0


def test_the_api_route_passes_it_through(store):
    from tradingagents import api

    got = api.strategies(min_tp=4, sort="profit")
    assert got["min_tp"] == 4.0
    assert all(r["tp"] >= 4 for r in got["rows"])
    assert [r["signal"] for r in got["rows"]] == [
        "exact4", "wide5", "wide6", "wide8"]
    assert "tps" in api.strategy_facets()


def test_the_csv_export_takes_the_same_floor_and_says_so_in_the_name(store):
    from tradingagents import api

    body = "".join(api.strategies_csv_lines(min_tp=4))
    lines = [ln for ln in body.strip().split("\n") if ln]
    assert len(lines) == 5, "header plus the four rows at TP 4%+"
    assert "just_under" not in body and "exact4" in body
    name = api.strategies_csv_name(min_tp=4)
    assert "tp4" in name and "tp4.0" not in name, name
    assert "tp2.5" in api.strategies_csv_name(min_tp=2.5)
    # both floors at once, each named
    both = api.strategies_csv_name(min_winrate=50, min_tp=4)
    assert "wr50" in both and "tp4" in both, both


def test_the_browser_sends_the_floor_and_caps_the_box_at_the_grid():
    """A state the page never sends is a filter that silently does nothing."""
    client = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert client.count('p.set("min_tp"') == 2, "the table AND the CSV"
    assert "tps?: number[]" in client, "the facets carry the offered TPs"

    panel = open("webapp/src/components/backtest/StrategiesPanel.tsx",
                 encoding="utf-8").read()
    assert "min TP %" in panel, "labelled in the column's unit"
    assert 'aria-label="Minimum take profit percent"' in panel
    assert panel.count("minTp,") >= 3, "table, load-more and CSV"
    assert "sort, minTrades, minWinrate, minTp, desc, perPage]" in panel
    # the ceiling is computed from the facets, not typed here
    assert "Math.max(...facets.tps)" in panel
    assert "max={tpCeiling}" in panel and "Math.min(tpCeiling" in panel
    # the caption prints the floor the SERVER applied
    assert "servedTp > 0" in panel and "d.min_tp" in panel
