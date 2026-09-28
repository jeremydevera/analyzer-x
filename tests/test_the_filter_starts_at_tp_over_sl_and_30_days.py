"""The Stored strategies filter starts with TP >= SL ticked and the last 30 days.

Operator, `Sep 28, 2026`: *"when cloking filter i wnt the following as default
/ TP is equal or greater than sl - checked / last days - 30"*.

The panel keeps the filter twice: the BOXES the operator edits, and `applied`,
the set the first request is sent with. Both must start at the default. Ticked
boxes over a list that was never filtered by them are a correct list under a
false label (`label-must-match-data`), so this pins both halves, and pins that
`clear all` still means nothing is filtered.
"""
from __future__ import annotations

import pathlib
import re

SRC = (pathlib.Path(__file__).resolve().parent.parent / "webapp" / "src"
       / "components" / "backtest" / "StrategiesPanel.tsx").read_text(encoding="utf-8")


def _block(start: str) -> str:
    i = SRC.index(start)
    return SRC[i:SRC.index("});", i)]


def test_the_defaults_are_the_operators():
    assert re.search(r"^const DEFAULT_TP_OVER_SL = true;$", SRC, re.M)
    assert re.search(r"^const DEFAULT_DAYS = 30;$", SRC, re.M)


def test_the_boxes_start_at_the_default():
    assert "const [tpOverSl, setTpOverSl] = useState(DEFAULT_TP_OVER_SL);" in SRC
    assert "const [days, setDays] = useState(DEFAULT_DAYS);" in SRC


def test_the_first_request_is_filtered_by_what_the_boxes_show():
    first = _block("const [applied, setApplied] = useState({")
    assert "tpOverSl: DEFAULT_TP_OVER_SL" in first, (
        "a ticked box over an unfiltered list is a false label")
    assert "days: DEFAULT_DAYS" in first


def test_clear_all_still_clears_everything():
    none = _block("const NO_FILTERS = {")
    assert "tpOverSl: false" in none and "days: 0" in none, (
        "the button says clear all; it must not leave two filters behind")
