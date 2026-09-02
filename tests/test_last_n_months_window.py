"""LAST N MONTHS — and one column per month.

Operator, 2026-08-27: *"add filter Last x month / if i entered 2 months then
adjust the number of trades, winrate, profit for last x month / also can you
show the column 'month' example month of aug, july then show profit for each
column"*. CLAUDE.md kit item G asks for the same thing, and for the months
OUTSIDE the window to be removed rather than filled with em dashes.

What the store can and cannot answer, exactly:

* PROFIT per month is stored — `fast_grid` and `auto_trader` both accumulate
  `monthly[month] += pnl` — so the window's profit and its green-month count
  are exact arithmetic on data that is already there.
* TRADES, WINS and WIN RATE are NOT stored per month. They exist per row only.
  So the grid keeps saying they are full-history while a window is on, and the
  window's own trade count comes from the row's REBUILT trade log (a click),
  where every trade carries its own exit date. Anything else would be a win %
  covering a different span than the profit printed beside it — the
  label-must-match-data failure this repo keeps paying for.
"""
import json
import time

import pytest

from tradingagents import market_sweep as msw, rows_index as ri

PANEL = "webapp/src/components/backtest/StrategiesPanel.tsx"


def test_the_window_is_the_last_n_month_keys_newest_first():
    assert ri.month_keys(2, "2026-08") == ["2026-08", "2026-07"]
    assert ri.month_keys(4, "2026-02") == ["2026-02", "2026-01", "2025-12",
                                          "2025-11"]
    assert ri.month_keys(1, "2026-01") == ["2026-01"]
    assert ri.month_keys(0, "2026-08") == [], "0 months is the whole history"


def test_the_window_sums_only_the_months_inside_it():
    monthly = {"2026-08": 933.7, "2026-07": 704.44, "2026-06": -50.0}
    got = ri.window_figures(monthly, ["2026-08", "2026-07"])
    assert got == {"w_profit": 1638.14, "w_green": 2, "w_months": 2}
    # June is outside it and must not be counted, good or bad
    assert ri.window_figures(monthly, ["2026-06"]) == {
        "w_profit": -50.0, "w_green": 0, "w_months": 1}


def test_a_month_the_row_never_traded_is_not_counted_as_zero():
    """`w_months` is what the row HAS in the window, so "2/2 green" cannot be
    read off a row that only traded one of them."""
    got = ri.window_figures({"2026-08": 10.0}, ["2026-08", "2026-07"])
    assert got == {"w_profit": 10.0, "w_green": 1, "w_months": 1}


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Rows whose newest month is JULY, so the anchor rule is exercised: a
    window must not start on a month the data does not have."""
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")

    def row(sig, monthly):
        profit = round(sum(monthly.values()), 2)
        return {"coin": "AAA", "tf": "1h", "signal": sig, "th": 0.1, "sl": 0.3,
                "tp": 2.0, "rr": 3.0, "sizing": "flat", "lev": 20, "base": 5.0,
                "notional": 100.0, "trades": 120, "wins": 72, "losses": 48,
                "winrate": 60.0, "profit": profit, "funding": -0.2,
                "h1": 1.0, "h2": 1.0, "green": 2, "months": len(monthly),
                "worst": -4.1, "dd": 22.0, "liqs": 0, "stop_reachable": True,
                "days": 360, "bars": 34000, "monthly": monthly,
                "cost_of_tp": 12.5, "rt": 0.04, "gate": "ok"}

    (rows_dir / "AAA-1h.json").write_text(json.dumps([
        row("mom6", {"2026-05": 500.0, "2026-06": -100.0, "2026-07": 20.0}),
        row("rsi14", {"2026-06": 5.0, "2026-07": 60.0}),
    ]))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    return None


def test_every_row_reports_the_window_and_the_payload_names_its_months(store):
    got = ri.query(months=2)
    assert got["window"] == ["2026-07", "2026-06"], got["window"]
    assert got["months_window"] == 2
    by = {r["signal"]: r for r in got["rows"]}
    assert by["mom6"]["w_profit"] == -80.0     # 20.0 + -100.0
    assert by["mom6"]["w_green"] == 1 and by["mom6"]["w_months"] == 2
    assert by["rsi14"]["w_profit"] == 65.0
    assert by["rsi14"]["w_green"] == 2
    # and the full-history figures are untouched beside them
    assert by["mom6"]["profit"] == 420.0


def test_the_window_is_anchored_on_the_DATA_not_on_today(store):
    """This store ends in July. A window anchored on today's month would report
    an empty August as "the last month" and every row as flat."""
    got = ri.query(months=1)
    assert got["window"] == ["2026-07"]
    assert {r["w_profit"] for r in got["rows"]} == {20.0, 60.0}


def test_no_window_means_no_window_fields(store):
    got = ri.query()
    assert got["window"] == [] and got["months_window"] == 0
    assert all("w_profit" not in r for r in got["rows"]), (
        "a column nobody asked for must not appear half-filled")


def test_there_is_deliberately_no_window_trade_count(store):
    """The sweep does not keep trades per month, so the store must not invent
    one. `fast_grid` and `auto_trader` are the proof."""
    got = ri.query(months=2)
    for r in got["rows"]:
        assert "w_trades" not in r and "w_winrate" not in r
    for mod in ("tradingagents/fast_grid.py", "tradingagents/auto_trader.py"):
        src = open(mod, encoding="utf-8").read()
        assert "monthly[m] = monthly.get(m, 0.0) + pnl" in src \
            or "monthly[month] = monthly.get(month, 0.0) + pnl" in src, mod


def test_the_api_route_passes_the_window(store):
    from tradingagents import api

    got = api.strategies(months=2)
    assert got["window"] == ["2026-07", "2026-06"]
    assert all("w_profit" in r for r in got["rows"])


def test_the_panel_has_the_box_and_derives_its_month_columns():
    p = open(PANEL, encoding="utf-8").read()
    assert 'aria-label="Last N months"' in p
    assert "months: applied.months || undefined" in p, "the request carries it"
    # the columns come from the window the SERVER used, or from the months the
    # rows carry — never a fixed ladder (kit item G)
    # The month columns are DERIVED — from the served window when there is one,
    # otherwise from the months the rows carry. A DAYS window (2026-09-03)
    # removes them entirely, because a day cannot restate a month, so the
    # expression gained a branch in front; the rule this test guards is that
    # the columns are never a fixed list.
    assert "const monthCols = (servedFilters.days > 0" in p
    assert "? window_" in p and "Object.keys(r.monthly ?? {})" in p,         "the columns must still come from the window or from the rows"
    assert 'Object.keys(r.monthly ?? {})' in p
    assert "setWindow(d.window ?? [])" in p, "the window comes from the payload"
    # "month of aug, july" — a month LABEL keeps its own form
    assert '"Jul", "Aug", "Sep"' in p and "monthLabel" in p
    # the columns the operator NAMED are the window's: profit, win %, trades,
    # W, L and green — headed "(2mo)" so the label cannot outlive the window
    assert "const winHead = " in p and "(${months}mo)" in p
    assert "const win = (r: StrategyRow)" in p
    assert "r.w_profit" in p and "r.w_green" in p
    assert "r.w_trades" in p and "r.w_winrate" in p


def test_the_panel_says_which_figures_the_window_does_NOT_restate():
    """The honest half: trades/W/L/win % stay full-history in the grid, and the
    screen says so rather than letting the reader assume."""
    p = open(PANEL, encoding="utf-8").read()
    # trades/W/L/win % are the window's only where the row's log was rebuilt;
    # everywhere else they are the whole history, dimmed, and titled with why
    assert "const stale = (r: StrategyRow)" in p and "!r.restated" in p
    assert "the whole history, not the window" in p
    assert "italic text-gray-400" in p, "and they LOOK different, not just hover"
    assert "Type the row&apos;s <b>#id</b> to restate all five." in p
    # the log itself counts the window's trades, wins and win %
    assert "const winLog = " in p and "const winWins = " in p
    assert "% win" in p
    # by EXIT month, which is how the sweep counts a month too
    assert "exit time" in p and "window_.includes" in p
