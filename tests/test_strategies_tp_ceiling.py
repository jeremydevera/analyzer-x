"""A TAKE-PROFIT CEILING, typed as a number, applied in the store.

Operator, 2026-09-03: "when i input tp 3% it should show tp below 3%" — so the
box is a maximum. It was a FLOOR for one day, on their earlier ask ("when i
input 4 then show that has TP equal or greater than 4", 2026-08-27), which is
why the parameter was RENAMED to `max_tp` instead of being quietly reused: a
field still called `min_tp` while meaning a maximum is a lie in the API
itself, and this repo has paid for that kind of label five times.

TP is the profit target a winning trade aims at, so this box means "only show
me strategies whose target is 3% or smaller" — the ones the market reaches more
often. Three things this holds shut:

* the unit is the one the TP% column PRINTS. 3 means 3%, not 0.03, and a row
  at exactly 3.0 SURVIVES the ceiling (CLAUDE.md rule G).
* the ceiling runs in SQLite, not on the page — the same reason the win % floor
  does: the tightest-TP row in the store is not on the first page.
* the box only offers TP values the measuring grid produced, and stops at the
  largest. `tp` has no index, so proving nothing matches costs a scan of every
  row: measured on the operator's store (35,863,520 rows), `tp <= 3` answered
  in 0.02 s and `tp >= 10` — a value only the 1d grid has, and this store holds
  no 1d rows — had not returned after 25 s.
"""
import json
import re

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
    """TPs that straddle 3 exactly, and the TIGHTEST TP is NOT the best profit —
    so a ceiling that quietly did nothing would still look plausible."""
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    (rows_dir / "AAA-1h.json").write_text(json.dumps([
        _row("AAA", "1h", "wide8", 12.0, 8.0),
        _row("AAA", "1h", "wide5", 30.0, 5.0),
        _row("AAA", "1h", "exact3", 44.0, 3.0),      # the boundary: stays
        _row("AAA", "1h", "just_over", 99.0, 3.5),    # best profit: goes
        _row("AAA", "1h", "tight", 80.0, 0.6),
    ]))
    (rows_dir / "BBB-4h.json").write_text(json.dumps([
        _row("BBB", "4h", "wide6", 25.0, 6.0, winrate=71.0),
        _row("BBB", "4h", "tight", 61.0, 0.4, winrate=88.0),
    ]))
    _settled()
    return None


def test_three_means_tp_three_percent_or_smaller(store):
    got = ri.query(max_tp=3)
    assert sorted(r["signal"] for r in got["rows"]) == [
        "exact3", "tight", "tight"]
    assert all(r["tp"] <= 3 for r in got["rows"])
    assert got["total"] == 3, "the count is of what MATCHES, not the store"


def test_the_boundary_row_is_kept_and_the_one_above_it_is_not(store):
    """"tp below 3" — a row at exactly 3.0 must survive, and the 3.5 row goes
    even though it has the best profit in the store."""
    got = ri.query(max_tp=3)["rows"]
    tps = [r["tp"] for r in got]
    assert 3.0 in tps
    assert 3.5 not in tps
    assert "just_over" not in [r["signal"] for r in got]


def test_it_is_a_percent_not_the_fraction_the_grid_stores(store):
    """BARRIERS holds .030; the rows and this box hold 3.0. Typed as 0.03 a
    ceiling would match NOTHING in the store and read as broken."""
    assert ri.query(max_tp=0.03)["total"] == 0, "0.03% keeps nothing"
    assert ri.query(max_tp=6)["total"] == 6       # everything but the 8.0
    assert ri.query(max_tp=9)["total"] == 7       # the whole store


def test_the_payload_says_the_ceiling_it_applied(store):
    """The caption is DERIVED from this, never from a literal beside it."""
    got = ri.query(max_tp=5)
    assert got["max_tp"] == 5.0
    assert all(r["tp"] <= 5 for r in got["rows"])
    assert ri.query()["max_tp"] == 0.0


def test_it_stacks_with_the_other_ceilings_and_filters(store):
    got = ri.query(max_tp=3, min_winrate=70, min_trades=100)
    assert [r["signal"] for r in got["rows"]] == ["tight"]      # BBB 4h, 88%
    assert ri.query(max_tp=3, tf="1h")["total"] == 2            # exact3, tight
    assert ri.query(max_tp=3, coin="BBB")["total"] == 1
    # and with the SL ceiling beside it, both downwards
    assert ri.query(max_tp=3, max_sl=0.3)["total"] == 3


def test_the_row_query_keeps_the_order_its_index(store):
    """`tp` is indexed by nothing, so the term cannot steal a plan — but it
    still steps aside in the ROW query, which is what keeps the ORDER BY's own
    index the day someone adds one. Measured identical on the real store:
    `tp <= 3 ORDER BY profit LIMIT 500` was 0.02 s either way.
    """
    where, args = ri._where(max_tp=3)
    assert where == " WHERE tp <= ?" and args == [3.0], where
    row_where, row_args = ri._where(max_tp=3, order_owns_index=True,
                                    order_key="profit")
    assert row_where == " WHERE +tp <= ?", row_where
    assert row_args == [3.0]
    assert "WHERE +tp <= ?" in ri.query_sql(sort="profit", max_tp=3)
    assert "WHERE +tp <= ?" in ri.query_sql(sort="winrate", max_tp=3)
    # The PLAN is not asserted here: SQLite is cost-based, and on a seven-row
    # fixture it scans whatever it is asked, index or no index (measured:
    # `ORDER BY winrate DESC` alone plans USE TEMP B-TREE on this store and
    # SCAN rows USING INDEX rows_winrate on the operator's 35,863,520). What
    # is size-independent — and what the `+` buys — is the SQL above. The real
    # plans are asserted against a big store in test_strategies_sort.py and
    # test_coin_index_forced.py.
    for sort in ("profit", "winrate"):
        plan = " ".join(ri.explain(sort=sort, max_tp=3)).upper()
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

    got = api.strategies(max_tp=3, sort="profit")
    assert got["max_tp"] == 3.0
    assert all(r["tp"] <= 3 for r in got["rows"])
    assert sorted(r["signal"] for r in got["rows"]) == [
        "exact3", "tight", "tight"]
    assert "tps" in api.strategy_facets()


def test_the_csv_export_takes_the_same_ceiling_and_says_so_in_the_name(store):
    from tradingagents import api

    body = "".join(api.strategies_csv_lines(max_tp=3))
    lines = [ln for ln in body.strip().split("\n") if ln]
    assert len(lines) == 4, "header plus the three rows at TP 3% or smaller"
    assert "just_over" not in body and "exact3" in body
    name = api.strategies_csv_name(max_tp=3)
    assert "tp3" in name and "tp3.0" not in name, name
    assert "tp2.5" in api.strategies_csv_name(max_tp=2.5)
    # both ceilings at once, each named
    both = api.strategies_csv_name(min_winrate=50, max_tp=3, max_sl=1)
    assert "wr50" in both and "tp3" in both and "sl1" in both, both


def test_the_browser_sends_the_ceiling_and_caps_the_box_at_the_grid():
    """A state the page never sends is a filter that silently does nothing."""
    client = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert client.count('p.set("max_tp"') == 2, "the table AND the CSV"
    assert "tps?: number[]" in client, "the facets carry the offered TPs"

    panel = open("webapp/src/components/backtest/StrategiesPanel.tsx",
                 encoding="utf-8").read()
    assert "max TP %" in panel, "labelled in the column's unit"
    # the accessible name says MAXIMUM: a ceiling read out as "minimum take
    # profit" is the same label-must-match-data failure in the screen reader
    assert 'aria-label="Maximum take profit percent"' in panel
    assert panel.count("applied.maxTp") >= 3, "table, load-more and CSV"
    # the boxes are a DRAFT: the store is asked when Apply filters is clicked,
    # and `draft` must carry the TP ceiling or the button cannot send it. Matched
    # over the draft set rather than its last field, so the next filter added
    # there does not break this test (the sizing filter did).
    draft = re.search(r"const draft = \{([^}]*)\}", panel)
    assert draft and "maxTp" in draft.group(1), draft
    assert "const apply = () =>" in panel
    # the ceiling is computed from the facets, not typed here
    assert "Math.max(...facets.tps)" in panel
    assert "max={tpCeiling}" in panel and "Math.min(tpCeiling" in panel
    # the caption prints the ceiling the SERVER applied
    assert "servedTp > 0" in panel and "d.max_tp" in panel
