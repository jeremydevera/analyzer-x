"""A floor is checked against the figure the column PRINTS — the window's.

Operator, Sep 09, 2026, screenshot attached: chips read *Past 30 days AND flat
sizing only AND Winrate 90% or better AND TP at least as wide as SL*, and the
win % column read **89.47, 89.47, 80.00, 80.00, 100, 100, 86.36, 86.36,
75.00**. *"so why are you showing below 90% winrate when the filter is ..."*

Timeline:

1. `rows_index.query` applied `min_winrate=90` in SQL — against each row's
   WHOLE-HISTORY win rate, the only one the index holds. Every row on that
   page was >= 90 over its history. #CGXLRJML (GPNSTOCK 30m stoch14) among them.
2. The 30-day window then RE-MEASURED each row from the candles and the page
   printed the window's own figures: GPNSTOCK 30m stoch14, 57 trades, 51 W /
   6 L, **89.47%** over `Aug 14, 2026 9:30pm -> Sep 05, 2026 3:00am`.
3. Nothing compared the window's figure with the floor, so a chip saying
   ">= 90" sat over a column saying 89.47, 86.36, 80.00, 75.00.

Two rules, both already in CLAUDE.md, both broken by one missing step:

* kit item G — *every filter takes the unit its column PRINTS*; the column
  printed the window;
* `label-must-match-data` — a chip is a label, and it disagreed with the data
  under it.

The floors now run a SECOND time, on the window's figures, on the page and in
the CSV, and the rows cut are COUNTED in the caption and in the file's last
line (rule 20 — never drop a row silently). Rows the window could not restate
keep their whole-history figures and stay, marked unrestated as before.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from tradingagents import api, rows_index as ri


def _row(rid, hist_wr, win_wr, *, restated=True, w_trades=20, w_profit=5.0):
    r = {"id": rid, "winrate": hist_wr, "trades": 100, "profit": 40.0}
    if restated:
        r.update(restated=True, w_winrate=win_wr, w_trades=w_trades,
                 w_profit=w_profit)
    return r


# ------------------------------------------------------------- the helper
def test_the_operators_page_loses_exactly_the_rows_under_the_floor():
    """The screenshot's win % column, in order."""
    printed = [89.47, 89.47, 80.00, 80.00, 100.0, 100.0, 86.36, 86.36, 75.00]
    rows = [_row(f"R{i}", 92.0, wr) for i, wr in enumerate(printed)]
    kept, hidden = ri.window_floors(rows, min_winrate=90)
    assert [r["w_winrate"] for r in kept] == [100.0, 100.0]
    assert hidden == 7


def test_the_floor_is_inclusive_in_the_unit_the_column_prints():
    """90 keeps 90.00 — the same rule the SQL floor follows."""
    kept, hidden = ri.window_floors(
        [_row("A", 95, 90.0), _row("B", 95, 89.99)], min_winrate=90)
    assert [r["id"] for r in kept] == ["A"] and hidden == 1


def test_trades_and_profit_floors_follow_the_window_too():
    rows = [_row("A", 95, 95, w_trades=3), _row("B", 95, 95, w_profit=-1.0),
            _row("C", 95, 95)]
    kept, hidden = ri.window_floors(rows, min_trades=5, profitable=True)
    assert [r["id"] for r in kept] == ["C"] and hidden == 2


def test_an_unrestated_row_is_kept_not_judged():
    """No candles on this PC means no window figure to judge; the page already
    marks that row. Cutting it would hide a row for a reason nobody can see."""
    rows = [_row("A", 95, None, restated=False)]
    kept, hidden = ri.window_floors(rows, min_winrate=90)
    assert kept == rows and hidden == 0


def test_no_floor_means_nothing_is_cut():
    rows = [_row("A", 50, 10.0), _row("B", 50, 0.0, w_trades=0)]
    kept, hidden = ri.window_floors(rows)
    assert kept == rows and hidden == 0


# ---------------------------------------------------------- the two callers
def test_the_page_applies_the_floors_after_both_kinds_of_window():
    """Both the days re-measure and the months restate print window figures."""
    src = inspect.getsource(api.strategies)
    days = src[src.index("msw.window_rows("):]
    assert "ri.window_floors(" in days, "the DAYS window must re-check the floors"
    months = src[src.index("restate_window(r, got"):src.index("got[\"restate_max\"]")]
    assert "ri.window_floors(" in months, "the MONTHS window must re-check them too"
    assert 'got["window_hidden"]' in src, "and the cut is COUNTED for the caption"


def test_the_csv_applies_the_floors_and_writes_the_count_in_the_file():
    src = inspect.getsource(ri.iter_rows)
    i = src.index("if win_days:")
    assert "window_floors(" in src[i:], "the file prints the window; floor it there"
    assert 'stats["window_hidden"]' in src[i:]
    route = inspect.getsource(api.strategies_csv_lines)
    assert "stats=stats" in route
    assert "WINDOW FLOOR:" in route, "a cut row is counted IN the file (rule 20)"


def test_the_caption_names_the_hidden_rows():
    """The chip and the column can only disagree if the caption owns it."""
    panel = Path("webapp/src/components/backtest/StrategiesPanel.tsx").read_text(
        encoding="utf-8")
    assert "setWinHidden(d.window_hidden ?? 0)" in panel
    assert re.search(r"winHidden > 0 \?", panel), "rendered only when it cut something"
    assert "passed the floors over their whole history but not" in panel
    client = Path("webapp/src/lib/api.ts").read_text(encoding="utf-8")
    assert "window_hidden?: number" in client
