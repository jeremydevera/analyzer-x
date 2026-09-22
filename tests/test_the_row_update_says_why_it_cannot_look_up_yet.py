"""UPDATE THIS BACKTEST must never answer "Internal Server Error".

`Sep 22, 2026 10:47pm`: pressing UPDATE on #XLV6V5HJ (XPIN 1h mom6, Backtest
v2) answered a bare 500. Nothing was wrong with the press — v2's table had
grown to 30,702,310 rows and had no `rows_id` sort list yet, so `ri.query`
raised `SortNotReady` ("it is being built NOW — minutes to hours on a store
this size. Nothing is lost") and this route let it out as a crash.

The strategies list and the CSV have answered 503 with that sentence since
2026-08-26. This is the same rule reaching the third door: a store that is
not ready yet is a 503 that SAYS SO, and the panel prints it.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException


def test_a_sort_still_building_is_a_503_with_the_reason(monkeypatch):
    from tradingagents import api, rows_index as ri

    why = ("finding row #XLV6V5HJ needs the rows_id index; it is being built "
           "NOW — minutes to hours on a store this size. Nothing is lost.")

    def _raise(**kw):
        raise ri.SortNotReady(why)

    monkeypatch.setattr(ri, "query", _raise)

    with pytest.raises(HTTPException) as got:
        api.strategy_row_update("XLV6V5HJ", store="v1")

    assert got.value.status_code == 503, "a store that is not ready is not a crash"
    assert "rows_id" in str(got.value.detail)
    assert "Nothing is lost" in str(got.value.detail), \
        "the operator reads this sentence on the button"


def test_a_row_that_really_is_missing_is_still_a_404(monkeypatch):
    """The 503 must not swallow the other answer: an id nobody has measured
    is gone, not pending."""
    from tradingagents import api, rows_index as ri

    monkeypatch.setattr(ri, "query", lambda **kw: {"rows": []})

    with pytest.raises(HTTPException) as got:
        api.strategy_row_update("XLV6V5HJ", store="v1")

    assert got.value.status_code == 404


def test_every_door_that_queries_the_index_answers_503_not_500():
    """Three routes reach `ri.query`/`export_plan`; all three must catch it.

    Counted, because the first two were fixed in 2026 and the third was
    found by pressing it — a rule that lives in two of three doors is a rule
    with a hole in it."""
    import inspect
    import re

    from tradingagents import api

    src = inspect.getsource(api)
    calls = len(re.findall(r"ri\.(query|export_plan)\(", src))
    guards = len(re.findall(r"except ri\.SortNotReady", src))
    assert guards >= calls, f"{calls} index calls, only {guards} say why"
