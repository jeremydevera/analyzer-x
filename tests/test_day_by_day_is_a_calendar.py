"""Day by day is a month calendar (operator, Sep 27, 2026: *"in day by day
section can you create calendar and show me the pnl for day insteead"*).

Source-level, like the other panel guards: the calendar has to key its boxes
exactly the way `auto_trader.daily_pnl` keys its days, sum the month caption
from those same boxes, name the book it is showing, and drop a late answer
for the book the operator switched away from.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = (ROOT / "webapp/src/components/trade/PnlPanel.tsx").read_text(encoding="utf-8")


def _calendar() -> str:
    start = PANEL.index("export function DayCalendar")
    return PANEL[start:]


def test_day_by_day_is_a_calendar_not_a_list():
    cal = _calendar()
    assert "grid-cols-7" in cal, "a calendar is seven columns, one per weekday"
    assert "<DayCalendar" in PANEL
    assert "dayRows" not in PANEL, "the old 30-row list is gone"


def test_boxes_use_the_same_day_key_as_the_server():
    """`daily_pnl` files a day under strftime('%Y-%m-%d', localtime(ts));
    a box keyed any other way would sit blank beside a day that traded."""
    src = (ROOT / "tradingagents/auto_trader.py").read_text(encoding="utf-8")
    assert 'time.strftime("%Y-%m-%d", time.localtime(' in src
    assert re.search(r"dayKey = \(y: number, m: number, d: number\) => `\$\{y\}-\$\{pad2\(m \+ 1\)\}-\$\{pad2\(d\)\}`",
                     _calendar() + PANEL)
    # and that key is today's local date, spelled the same way
    lt = time.localtime()
    assert f"{lt.tm_year}-{lt.tm_mon:02d}-{lt.tm_mday:02d}" == time.strftime("%Y-%m-%d", lt)


def test_the_month_total_is_summed_from_the_boxes_it_sits_over():
    cal = _calendar()
    assert "const inMonth = Array.from({ length: count }, (_, i) => days[dayKey(month.y, month.m, i + 1)])" in cal
    for name in ("total", "wins", "losses"):
        assert re.search(rf"const {name} = inMonth\.reduce", cal), name


def test_the_calendar_names_the_book_it_is_showing():
    assert 'book={dry ? "practice account" : "real-money account"}' in PANEL
    assert "{book} ·" in _calendar()


def test_a_late_answer_for_the_other_book_is_dropped():
    assert "const asked = dry;" in PANEL
    assert "if (asked !== dryNow.current) return;" in PANEL
    # the guard runs BEFORE either state is written
    guard = PANEL.index("if (asked !== dryNow.current) return;")
    assert guard < PANEL.index("setDays(d.days)")


def test_a_day_without_trades_is_blank_not_zero():
    cal = _calendar()
    assert "disabled={!v}" in cal
    assert "{v && <>" in cal


def test_it_opens_on_the_book_that_has_trades():
    """Sep 27, 2026: 'i cannot see day by day pnl' — the page opened on the
    real-money account, 0 closed trades, every box blank."""
    assert "if (!asked && !picked.current && !Object.keys(d.days).length) { setDry(true); return; }" in PANEL
    # the operator's own choice is never overridden
    assert "const pick = (v: boolean) => { picked.current = true; setDry(v); };" in PANEL
    assert "onChange={(e) => pick(e.target.checked)}" in PANEL
    assert '"Real money"' in _calendar() and '"Practice"' in _calendar()
