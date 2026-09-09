"""The download button must not promise rows the file cannot hold.

Found by pressing it, Sep 09, 2026, under the `press-and-watch` skill. With
`min win % 85 AND last 30 days` applied the button read:

    download all (566,990) CSV

and the file it produced held **1,184 rows** — 2,000 re-measured, **816** cut
because their win rate inside the window missed the 85% floor. Measured from
the press log:

    csv | asked: min_winrate=85.0 AND days=30 AND sort=profit AND desc=True
        | got: rows=1184 · window_hidden=816 | took 671.09s

566,990 is the count of rows that clear the floor over their WHOLE HISTORY —
what SQL matched before the window re-measured anything. It is a true number
under a label that cannot be delivered, which is `label-must-match-data`: the
label has to be DERIVED from the data it describes.

The cap is the server's (`rows_index.DAYS_CSV_MAX`) and travels in the payload
as `days_csv_max`, because a number typed into the component drifts away from
the code that enforces it.

The button also now says how LONG it takes. The file sat at 0 bytes for the
first four minutes of that press — Chrome only commits to disk in ~240 KB
blocks — and 0 bytes is indistinguishable from broken unless something says
otherwise.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from tradingagents import api, rows_index as ri

PANEL = Path("webapp/src/components/backtest/StrategiesPanel.tsx")


@pytest.fixture(scope="module")
def panel() -> str:
    return PANEL.read_text(encoding="utf-8")


def test_the_server_sends_the_cap_it_enforces():
    src = inspect.getsource(api.strategies)
    assert 'got["days_csv_max"] = ri.DAYS_CSV_MAX' in src, \
        "the button must read the cap from the code that applies it"
    client = Path("webapp/src/lib/api.ts").read_text(encoding="utf-8")
    assert "days_csv_max?: number" in client


def test_the_label_names_the_cap_when_a_days_window_is_on(panel):
    i = panel.index("download the window's top")
    around = panel[i - 400:i + 200]
    assert "servedFilters.days > 0 && !servedFilters.months && csvMax" in around
    assert "csvMax.toLocaleString()" in around, "the server's number, not a literal"


def test_the_label_still_says_the_match_count_without_a_window(panel):
    """An UNWINDOWED export re-measures nothing and is not capped, so `total`
    is what it really delivers."""
    i = panel.index("download the window's top")
    around = panel[i:i + 320]
    assert "download all (${total.toLocaleString()}" in around


def test_no_literal_cap_is_typed_into_the_panel(panel):
    """2000 in the component and DAYS_CSV_MAX in the store is two truths."""
    assert str(ri.DAYS_CSV_MAX) not in panel, \
        f"{ri.DAYS_CSV_MAX} is hard-coded in the panel; read days_csv_max instead"


def test_the_cap_is_refreshed_on_every_answer(panel):
    """A cap kept from an older answer would label the new one."""
    assert "setCsvMax(d.days_csv_max ?? 0)" in panel
    i = panel.index("setCsvMax(")
    assert "setServedFilters(applied)" in panel[i - 900:i + 900], \
        "the cap and the served filters must land in the same response handler"


def test_the_button_warns_that_it_takes_minutes_and_may_show_zero_bytes(panel):
    """The operator pressed it and asked 'why does it not download, its still
    downloading 0B'. The server was streaming; the browser had not flushed."""
    i = panel.index("title={servedFilters.days > 0")
    tip = panel[i:panel.index("/* the APPLIED set", i)]
    assert "MINUTES" in tip
    assert "0 bytes" in tip
    assert re.search(r"671s|671 s", tip), "with the measured number, not a guess"


def test_the_months_window_is_not_capped_so_its_label_is_the_match_count():
    """`iter_rows` only re-measures for DAYS. A months export streams every
    matching row, so `total` is honest there — which is why the label's
    condition excludes months."""
    src = inspect.getsource(ri.iter_rows)
    i = src.index("win_days = max(0, int(days or 0))")
    assert "months" not in src[i:i + 300], \
        "if months ever starts re-measuring, the label must name its cap too"
