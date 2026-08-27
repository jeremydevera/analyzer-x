"""A win-rate FLOOR, typed as a number, applied in the store.

Operator, 2026-08-27: "add a textbox winrate, if i put 50 then show me coins
with winrate equal or greater than 50".

Two things this holds shut:

* the unit is the one the `win %` column PRINTS. 50 means 50.00% or better,
  inclusive — not 0.5, and not "the top 50". A box beside a column that prints
  62.50 must read 62.5 the same way (CLAUDE.md rule G).
* the floor runs in SQLite, not on the page. Filtering the 500 rows already on
  screen would hide the 70%-win configuration sitting at row 900,000 of
  21 million — which is the whole reason the operator asked.
"""
import json
import re

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
    """Rates that straddle 50 exactly, so an off-by-one or a `>` instead of
    `>=` cannot pass: EXACT50 is at 50.00 and must SURVIVE the floor."""
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    (rows_dir / "AAA-1h.json").write_text(json.dumps([
        _row("AAA", "1h", "high", 40.0, 77.5),
        _row("AAA", "1h", "exact50", 12.0, 50.0),     # the boundary: stays
        _row("AAA", "1h", "just_under", 90.0, 49.99),  # best profit: goes
        _row("AAA", "1h", "low", 100.0, 31.0),
    ]))
    (rows_dir / "BBB-4h.json").write_text(json.dumps([
        _row("BBB", "4h", "high", 55.0, 62.5),
        _row("BBB", "4h", "low", 61.0, 22.0),
        # a 100% rate over 3 trades: the floor is not a substitute for a
        # denominator, so this passes win% >= 50 and min_trades kills it
        _row("BBB", "4h", "fluke", 4.0, 100.0, trades=3),
    ]))
    _settled()
    return None


def test_fifty_means_fifty_percent_or_better(store):
    got = ri.query(min_winrate=50)
    assert sorted(r["signal"] for r in got["rows"]) == [
        "exact50", "fluke", "high", "high"]
    assert all(r["winrate"] >= 50 for r in got["rows"])
    assert got["total"] == 4, "the count is of what MATCHES, not the store"


def test_the_boundary_row_is_kept_and_the_one_below_it_is_not(store):
    """`>=`, in the operator's own words: "equal or greater than 50"."""
    rates = [r["winrate"] for r in ri.query(min_winrate=50)["rows"]]
    assert 50.0 in rates, "a row at exactly 50.00 must survive"
    assert 49.99 not in rates


def test_it_is_a_percentage_not_a_rank_and_not_a_fraction(store):
    """A 0-1 reading would let everything through; a rank would keep N rows."""
    assert ri.query(min_winrate=0.5)["total"] == 7, "0.5 is half a percent"
    assert ri.query(min_winrate=63)["total"] == 2      # 77.5 and 100.0
    assert ri.query(min_winrate=101)["total"] == 0


def test_the_payload_says_the_floor_it_applied(store):
    """The caption is DERIVED from this, never from a literal beside it."""
    got = ri.query(min_winrate=62.5)
    assert got["min_winrate"] == 62.5
    assert all(r["winrate"] >= 62.5 for r in got["rows"])
    assert ri.query()["min_winrate"] == 0.0


def test_it_stacks_with_the_other_filters(store):
    """A floor that ignored min_trades would put `100.00% over 3 trades` back
    at the top — the exact row min_trades exists to bury."""
    got = ri.query(min_winrate=50, min_trades=100, coin="BBB")
    assert [r["signal"] for r in got["rows"]] == ["high"]
    assert ri.query(min_winrate=50, profitable=True, tf="1h")["total"] == 2


def test_which_form_the_row_query_uses_depends_on_the_order(store):
    """The PLAN, not just the answer — and this filter is the one column an
    ORDER also sorts by, so the fast form is not the same in both directions.
    Measured on the operator's own store (35,570,060 rows, LIMIT 50):

        ORDER BY winrate, winrate >= 70   plain 0.77 s   +  24.93 s
        ORDER BY profit,  winrate >= 70   plain  >25 s   +   1.01 s

    Ranked by win %, the range drives rows_winrate (a SEARCH). Ranked by
    anything else it must step aside, or SQLite sorts every matching row in a
    temp b-tree — the `trades` disaster this module already paid for.
    """
    where, args = ri._where(min_winrate=50)
    assert where == " WHERE winrate >= ?" and args == [50.0], where

    by_rate, rate_args = ri._where(min_winrate=50, order_owns_index=True,
                                   order_key="winrate")
    assert by_rate == " WHERE winrate >= ?", by_rate
    assert rate_args == [50.0]

    by_profit, _ = ri._where(min_winrate=50, order_owns_index=True,
                             order_key="profit")
    assert by_profit == " WHERE +winrate >= ?", by_profit
    # and the SQL each order really runs, not just the helper
    assert "WHERE winrate >= ?" in ri.query_sql(sort="winrate", min_winrate=50)
    assert "WHERE +winrate >= ?" in ri.query_sql(sort="profit", min_winrate=50)


def test_a_floor_never_costs_the_order_its_index(store):
    """No FULL temp-b-tree sort in any order the header offers.

    `USE TEMP B-TREE FOR LAST TERM OF ORDER BY` is fine and expected — that is
    only the `id ASC` tiebreak, and the 0.77 s real-store query has it too.
    `USE TEMP B-TREE FOR ORDER BY` is the whole result set being sorted, which
    is the 25-second-plus plan.
    """
    for sort in ("profit", "winrate"):
        plan = " ".join(ri.explain(sort=sort, min_winrate=50)).upper()
        assert "TEMP B-TREE FOR ORDER BY" not in plan, (sort, plan)


def test_the_api_route_passes_it_through(store):
    from tradingagents import api

    got = api.strategies(min_winrate=50, sort="winrate", min_trades=100)
    assert got["min_winrate"] == 50.0
    assert all(r["winrate"] >= 50 and r["trades"] >= 100 for r in got["rows"])
    assert [r["signal"] for r in got["rows"]] == ["high", "high", "exact50"]


def test_the_csv_export_takes_the_same_floor_and_says_so_in_the_name(store):
    from tradingagents import api

    body = "".join(api.strategies_csv_lines(min_winrate=50, sort="winrate"))
    lines = [ln for ln in body.strip().split("\n") if ln]
    assert len(lines) == 5, "header plus the four rows at 50%+"
    assert "just_under" not in body and "exact50" in body
    name = api.strategies_csv_name(min_winrate=50)
    assert "wr50" in name and "wr50.0" not in name, name
    assert "wr62.5" in api.strategies_csv_name(min_winrate=62.5)


def test_the_browser_sends_the_floor_and_the_box_prints_percent():
    """The wiring, end to end: a state the page never sends is a filter that
    silently does nothing (the "win % ↓" header was decoration once)."""
    client = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert 'p.set("min_winrate", String(q.minWinrate))' in client
    assert client.count('p.set("min_winrate"') == 2, "the table AND the CSV"

    panel = open("webapp/src/components/backtest/StrategiesPanel.tsx",
                 encoding="utf-8").read()
    assert "min win %" in panel, "the box is labelled in the column's unit"
    assert 'aria-label="Minimum win rate percent"' in panel
    # the request, LOAD MORE and the CSV all read the APPLIED floor — the
    # boxes are a draft until the operator clicks Apply filters (2026-08-27)
    assert panel.count("applied.minWinrate") >= 3, "table, load-more and CSV"
    # a floor typed and then not re-requested from page 1 shows page 40 of a
    # list the operator has not seen the top of. Matched as a REGEX over the
    # reset effect's dependency array, not as a fixed string: the next filter
    # added to that array must not break this test (the TP floor did).
    # Applying a filter IS the reset: `apply` sends the draft and goes back to
    # page 1, so there is no separate effect to inspect any more.
    apply_fn = re.search(r"const apply = \(\) => \{([^}]*)\}", panel)
    assert apply_fn, "the Apply filters handler must exist"
    assert "setApplied(draft)" in apply_fn.group(1)
    assert "setPage(1)" in apply_fn.group(1), (
        "a new filter is a new list — page 1, or the operator lands on page 40 "
        "of something they have not seen the top of")
    # the caption comes from what the SERVER applied
    assert "servedWinrate > 0" in panel and "d.min_winrate" in panel
