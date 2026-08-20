"""A trade the candles ended on is OPEN. The log must not claim it closed.

Operator, 2026-08-20, on row 181 of a trend50/PI report: "you can literally see
it has date closed and its +1.62 already". They were right — the CLOSED cell
printed `t.close` unconditionally, and for why==='END' that is the LAST BAR's
timestamp, so an unexited position read as a closed win. The footer then added
its mark-to-market into TOTAL PROFIT and credited it in the W/L record.
"""
from __future__ import annotations

from tradingagents import report_template as rt

SRC = rt.TEMPLATE if hasattr(rt, "TEMPLATE") else open(
    "tradingagents/report_template.py", encoding="utf-8").read()


def test_the_closed_cell_is_not_printed_for_an_open_trade():
    assert "t.why==='END'" in SRC
    assert "still open" in SRC, "an END trade must say so where CLOSED would be"


def test_the_closed_timestamp_is_no_longer_printed_unconditionally():
    assert '<td class="l">${t.close}</td>' not in SRC, \
        "printing t.close for every row is what made an open trade read as closed"


def test_the_footer_separates_realised_from_open():
    assert "REALISED" in SRC
    assert "STILL OPEN" in SRC
    assert "not banked" in SRC


def test_the_realised_total_subtracts_the_open_mark():
    assert "res.profit - opPnl" in SRC, "realised profit excludes the open mark"
    assert "res.trades - op.length" in SRC, "an open trade is not a closed trade"
    assert "res.wins - op.filter" in SRC, "an open trade is not a win"


def test_the_open_row_is_visually_marked():
    assert "openrow" in SRC
    assert ".logbox tr.openrow" in SRC


def test_the_engine_still_marks_to_the_last_close():
    """The FIX IS LABELLING ONLY. The maths must be untouched: an open trade is
    still marked to market so the row shows what it is currently worth."""
    src = open("tradingagents/auto_trader.py", encoding="utf-8").read()
    assert 'out, why = s * (close[-1] / entry - 1), "END"' in src
