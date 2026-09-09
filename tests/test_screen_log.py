"""Every Apply and every download is written down, with a check on the answer.

Operator, Sep 09, 2026: *"whenever i clicked apply filter and click download
csv you should be getting the logs of it so you can see the status"*.

They asked for it one message after saying why the win-% bug survived:

  operator: *"what's hard on this?"*
  answer:   nothing — I checked the parts, you checked the result.

So this log is not a performance trace. Its job is to do what the operator's
glance did: take the rows that are about to be sent, re-test them against the
filters that were on, **using the figure the column PRINTS**, and write a
MISMATCH line naming the row and its real value. On the Sep 09 filter that
line would have read:

    MISMATCH win % >= 90: 7 of 9 rows on screen break it —
        #CGXLRJML 89.47, #DYKSLWB8 89.47, #DX7HAULZ 80.0, ...

written by the code that served the table, at the moment it served it.
"""
from __future__ import annotations

import inspect

import pytest

from tradingagents import api, screen_log as sl


@pytest.fixture(autouse=True)
def _tmp_log(tmp_path, monkeypatch):
    monkeypatch.setattr(sl, "LOG_PATH", tmp_path / "screen.log")


def _row(rid, **kw):
    base = {"id": rid, "coin": "BTC", "tf": "1h", "signal": "rsi14",
            "sizing": "flat", "tp": 3.0, "sl": 1.0, "trades": 50,
            "winrate": 95.0, "profit": 10.0}
    base.update(kw)
    return base


# ------------------------------------------------- the check that matters
def test_the_operators_own_screen_would_have_shouted():
    """The nine win rates from the Sep 09 screenshot, under a 90 floor."""
    printed = [89.47, 89.47, 80.0, 80.0, 100.0, 100.0, 86.36, 86.36, 75.0]
    rows = [_row(f"R{i}", restated=True, w_winrate=wr, winrate=95.0)
            for i, wr in enumerate(printed)]
    notes = sl.disagreements(rows, {"min_winrate": 90})
    assert len(notes) == 1
    assert "MISMATCH win % >= 90: 7 of 9 rows" in notes[0]
    assert "89.47" in notes[0] and "(+2 more)" in notes[0]


def test_the_check_reads_the_WINDOW_figure_when_the_row_was_restated():
    """Checking the stored number on a restated row is the original bug."""
    row = _row("A", winrate=95.0, restated=True, w_winrate=40.0)
    assert sl.disagreements([row], {"min_winrate": 90}), \
        "the column prints 40; the check must test 40"
    # and the store's number when there is no window
    assert not sl.disagreements([_row("B", winrate=95.0)], {"min_winrate": 90})


def test_a_table_that_agrees_with_its_chips_says_nothing():
    rows = [_row("A", restated=True, w_winrate=100.0),
            _row("B", restated=True, w_winrate=90.0)]      # inclusive at 90
    assert sl.disagreements(rows, {"min_winrate": 90, "sizing": "flat",
                                   "tp_over_sl": True}) == []


@pytest.mark.parametrize("asked,row,hit", [
    ({"min_trades": 20}, {"trades": 4}, "trades >= 20"),
    ({"profitable": True}, {"profit": -3.0}, "profitable only"),
    ({"max_tp": 3}, {"tp": 6.0}, "TP <= 3%"),
    ({"max_sl": 1}, {"sl": 2.0}, "SL <= 1%"),
    ({"min_tp": 5}, {"tp": 2.0}, "TP >= 5%"),
    ({"tp_over_sl": True}, {"tp": 1.0, "sl": 3.0}, "TP >= SL"),
    ({"sizing": "flat"}, {"sizing": "martingale"}, "sizing = flat"),
    ({"tf": "1h"}, {"tf": "4h"}, "tf = 1h"),
])
def test_every_filter_is_checked_not_just_the_win_rate(asked, row, hit):
    """The bug was in one box; the next one will be in another."""
    notes = sl.disagreements([_row("A", **row)], asked)
    assert notes and hit in notes[0], notes


def test_no_filter_means_nothing_to_disagree_with():
    assert sl.disagreements([_row("A", winrate=3.0)], {}) == []
    assert sl.disagreements([], {"min_winrate": 90}) == []


# ------------------------------------------------------- the stream's check
def test_the_download_is_checked_row_by_row_without_holding_them():
    w = sl.Watch({"min_winrate": 90})
    for i in range(1000):
        w.see(_row(f"R{i}", restated=True,
                   w_winrate=89.0 if i % 100 == 0 else 99.0))
    notes = w.notes()
    assert len(notes) == 1
    assert "10 of 1000 rows in the file break it" in notes[0]
    assert len(w.who["win % >= 90"]) == 5, "only the first few ids are kept"


# ---------------------------------------------------------------- the log
def test_a_press_is_one_readable_line_with_the_project_date_format():
    sl.record("apply", {"min_winrate": 90, "sizing": "flat", "days": 30,
                        "coin": None, "min_trades": 0},
              {"rows": 9, "total": 5000, "window_hidden": 16}, 74.1)
    line = sl.tail()[0]
    assert "apply" in line
    assert "min_winrate=90 AND sizing=flat AND days=30" in line, line
    assert "coin" not in line, "a filter that was OFF is not a filter"
    assert "rows=9" in line and "window_hidden=16" in line
    assert "took 74.10s" in line
    # the one date format, from the one formatter
    import re
    assert re.match(r"^[A-Z][a-z]{2} \d{2}, \d{4} \d{1,2}:\d{2}[ap]m  ", line), line


def test_the_mismatch_lines_can_be_read_on_their_own():
    sl.record("apply", {"min_winrate": 90}, {"rows": 2}, 1.0)
    sl.record("apply", {"min_winrate": 90}, {"rows": 9}, 2.0,
              notes=["MISMATCH win % >= 90: 7 of 9 rows on screen break it"])
    assert len(sl.tail()) == 3            # two presses, one carrying a note
    assert len(sl.mismatches()) == 1
    assert "7 of 9" in sl.mismatches()[0]


def test_the_log_never_breaks_a_page(monkeypatch):
    """A log line is never worth a failed request."""
    monkeypatch.setattr(sl, "LOG_PATH", None)      # unusable on purpose
    sl.record("apply", {"min_winrate": 90}, {"rows": 1}, 0.1)
    assert sl.tail() == []


# ------------------------------------------------------------- the wiring
def test_both_presses_are_recorded():
    page = inspect.getsource(api.strategies)
    assert "_screen_note(\"apply\"" in page, "Apply writes a line"
    csv = inspect.getsource(api.strategies_csv_lines)
    assert "_sl.Watch(" in csv and "_watch.see(r)" in csv
    assert '_sl.record("csv"' in csv and '_sl.record("csv FAILED"' in csv, \
        "a download that dies mid-stream is a status too"
    note = inspect.getsource(api._screen_note)
    assert "sl.disagreements(rows, asked)" in note


def test_the_log_can_be_read_back_over_http():
    src = inspect.getsource(api.screen_log)
    assert "mismatch_only" in src
    assert "sl.mismatches(" in src and "sl.tail(" in src
    got = api.screen_log(n=5)
    for key in ("lines", "total", "mismatches", "path"):
        assert key in got
