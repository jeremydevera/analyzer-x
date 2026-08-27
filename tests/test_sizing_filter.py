"""Flat or martingale, one at a time.

Operator, 2026-08-27: *"i want filter to see flat / martingale"*.

Sizing is HOW MUCH is staked per trade — flat stakes the same every time, the
martingale ladder doubles after a loss to win it back. It is a sizing CHOICE,
not a measurement: an audit proved the "13/13 green months" behind six live
strategies came from the ladder and not the signal, while flat was 7/12–11/12
(CLAUDE.md rule 19). Every row in the store exists in both, so a grid that
cannot separate them hides that fact.

Two traps this holds shut:

* the two values come from `backtest_report.SIZINGS` — the grid that MEASURED
  the rows — not from a pair of literals in the browser;
* the COUNT has to respect it. The count has two shortcuts that skip the rows
  table (`_pairs_total` for coin/tf, and the win-rate index), and both are only
  valid for filters that take WHOLE pairs. A sizing cuts inside a pair, so a
  shortcut that ignored it would print the unfiltered total beside filtered
  rows — which is exactly what happened to the TP floor while it was being
  written.
"""
import json

import pytest

from tradingagents import market_sweep as msw, rows_index as ri


def _row(coin, tf, signal, profit, sizing, winrate=60.0, trades=120, tp=2.0):
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
    """The ladder rows carry the big profits and the flat rows the small ones —
    the shape of the real store, so a filter that did nothing would still look
    plausible at the top of the page."""
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    (rows_dir / "AAA-1h.json").write_text(json.dumps([
        _row("AAA", "1h", "mom6", 900.0, "martingale"),
        _row("AAA", "1h", "mom6", 40.0, "flat"),
        _row("AAA", "1h", "rsi14", 700.0, "martingale", winrate=88.0),
        _row("AAA", "1h", "rsi14", 30.0, "flat", winrate=88.0),
        _row("AAA", "1h", "fade15", -60.0, "martingale"),
    ]))
    (rows_dir / "BBB-4h.json").write_text(json.dumps([
        _row("BBB", "4h", "trend50", 500.0, "martingale"),
        _row("BBB", "4h", "trend50", 25.0, "flat"),
    ]))
    _settled()
    return None


def test_flat_alone(store):
    got = ri.query(sizing="flat")
    assert {r["sizing"] for r in got["rows"]} == {"flat"}
    assert got["total"] == 3, "the count is of what MATCHES"
    assert sorted(r["profit"] for r in got["rows"]) == [25.0, 30.0, 40.0]


def test_martingale_alone(store):
    got = ri.query(sizing="martingale")
    assert {r["sizing"] for r in got["rows"]} == {"martingale"}
    assert got["total"] == 4
    assert got["rows"][0]["profit"] == 900.0, "still ranked by profit"


def test_no_sizing_means_both(store):
    got = ri.query()
    assert {r["sizing"] for r in got["rows"]} == {"flat", "martingale"}
    assert got["total"] == 7
    assert got["sizing"] == "", "the payload says it filtered nothing"


def test_the_payload_says_which_sizing_it_applied(store):
    """The caption is DERIVED from this, never from a literal beside it."""
    assert ri.query(sizing="flat")["sizing"] == "flat"
    assert ri.query(sizing="martingale")["sizing"] == "martingale"


def test_the_count_shortcuts_do_not_skip_it(store):
    """`_pairs_total` answers a coin/tf filter from the pair summaries, and a
    win-rate floor is counted inside the win-rate index. Neither knows what
    sizing a row has, so both must stand aside — or the page prints "7 match"
    over three flat rows."""
    assert ri.query(sizing="flat", tf="1h")["total"] == 2, "not 5"
    assert ri.query(sizing="flat", coin="AAA")["total"] == 2
    assert ri.query(sizing="flat", min_winrate=80)["total"] == 1, "not 2"
    assert ri.query(sizing="martingale", min_winrate=80)["total"] == 1
    # and the unfiltered shortcuts still work
    assert ri.query(tf="1h")["total"] == 5


def test_it_stacks_with_every_other_filter(store):
    got = ri.query(sizing="flat", min_winrate=80, min_trades=100, tf="1h",
                   profitable=True)
    assert [r["signal"] for r in got["rows"]] == ["rsi14"]
    assert got["rows"][0]["sizing"] == "flat"


def test_an_unknown_sizing_matches_nothing_rather_than_everything(store):
    """A typo in a URL must not quietly widen the answer."""
    assert ri.query(sizing="ladder")["total"] == 0


def test_the_two_values_come_from_the_grid_that_measured_the_rows(store):
    from tradingagents import backtest_report as br

    assert br.SIZINGS == ("flat", "martingale")
    assert ri.facets()["sizings"] == ["flat", "martingale"]
    # and the sweep builds its combinations from that same tuple, so the
    # dropdown cannot drift from what was measured
    src = open("tradingagents/market_sweep.py", encoding="utf-8").read()
    assert "br.SIZINGS" in src
    assert '("flat", "martingale")' not in src, (
        "the sweep must not carry its own copy of the list")


def test_the_row_query_keeps_the_order_its_index(store):
    """One of two values can never be selective enough to drive a plan, so it
    steps aside for the ORDER BY like tf and signal do."""
    where, args = ri._where(sizing="flat")
    assert where == " WHERE sizing = ?" and args == ["flat"], where
    row_where, _ = ri._where(sizing="flat", order_owns_index=True,
                             order_key="profit")
    assert row_where == " WHERE +sizing = ?", row_where
    assert "WHERE +sizing = ?" in ri.query_sql(sizing="flat")


def test_the_api_route_and_the_csv_carry_it(store):
    from tradingagents import api

    got = api.strategies(sizing="flat")
    assert got["sizing"] == "flat"
    assert {r["sizing"] for r in got["rows"]} == {"flat"}
    assert "sizings" in api.strategy_facets()

    body = "".join(api.strategies_csv_lines(sizing="flat"))
    lines = [ln for ln in body.strip().split("\n") if ln]
    assert len(lines) == 4, "header plus the three flat rows"
    assert "martingale" not in body
    # the filename says which slice is in the file
    assert "flat" in api.strategies_csv_name(sizing="flat")
    assert "martingale" in api.strategies_csv_name(sizing="martingale")


def test_the_browser_sends_it_and_offers_the_grid_values():
    client = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert client.count('p.set("sizing"') == 2, "the table AND the CSV"
    assert "sizings?: string[]" in client

    panel = open("webapp/src/components/backtest/StrategiesPanel.tsx",
                 encoding="utf-8").read()
    assert 'aria-label="Sizing"' in panel
    assert "flat and martingale" in panel, "the do-not-filter option, in words"
    assert "(facets.sizings ?? []).map" in panel, (
        "the options come from the grid, not from two literals here")
    assert panel.count("applied.sizing") >= 3, "table, load-more and CSV"
    # it is one of the Apply filters, and it is in the ANDed sentence. Matched
    # over the draft set, not its last field: the next filter added there must
    # not break this test (the row-id box did).
    import re

    draft = re.search(r"const draft = \{(.*?)\};", panel, re.S)
    assert draft and "sizing" in draft.group(1), draft
    assert "`sizing = ${f.sizing}`" in panel
    # and the caption says it from the SERVED set
    assert "servedFilters.sizing" in panel
