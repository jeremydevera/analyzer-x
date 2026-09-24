"""A download that stops at 2,000 rows must SAY 2,000 in the query.

Operator, `Sep 15, 2026`: *"i click download button but ive been waiting 20
mins now"*, then *"what is the reason why are you not fixing this bug that has
been running for 1 week"*.

What they clicked: the filter icon, min win % 95, "TP is equal to or greater
than SL", last 30 days, apply, download. They chose no ordering — the panel
ranks by profit on its own ("highest PROFIT $ first"), and that default
travelled into the export.

So the query filters on WIN RATE and orders by PROFIT. SQLite finds the
matches through the win-rate index and then has to sort them before it can
hand back row one. Measured on the operator's own store (113,439,286 rows,
48.01 GB, mechanical disk):

| set | rows |
|---|---|
| `winrate >= 95` | 5,513,709 |
| `winrate >= 95 AND tp >= sl` | 3,268,883 |

ROOT CAUSE — a WINDOWED export already has a ceiling. `iter_rows` stops after
`DAYS_CSV_MAX` rows (`win_left`), because every one of them is re-measured
from this PC's candles. That ceiling lived only in a Python countdown and was
never given to SQL, so SQLite was asked for an unbounded stream and sorted all
3.27 million matches before yielding anything. The docstring said it out loud
and believed it of every export: *"an export has no LIMIT, so a seek in the
wrong order must sort EVERY match before its first byte."* True for a plain
download. False for this one.

The fix is the limit reaching the query. Same index, same plan, same
`USE TEMP B-TREE FOR ORDER BY` — SQLite simply keeps 2,000 as it scans
instead of all 3.27 million:

| | first row |
|---|---|
| before | nothing after 500 s |
| after | **0.1 s** |

Nothing about the file changes. `iter_rows` consumed exactly `DAYS_CSV_MAX`
rows before and consumes exactly `DAYS_CSV_MAX` now, in the same order, so the
same rows are re-measured and the same rows are written.
"""
from __future__ import annotations

import inspect

from tradingagents import rows_index as ri


def test_a_windowed_export_puts_its_ceiling_in_the_sql():
    src = inspect.getsource(ri.iter_rows)
    # ONE number, `_cap`: DAYS_CSV_MAX unless the FULL export (Sep 25, 2026)
    # passes window_cap=0 - both the SQL and the loop read it
    assert "_cap = DAYS_CSV_MAX if window_cap is None else int(window_cap)" in src
    assert "_sql_limit = _cap if (days and int(days) > 0) else 0" in src, \
        "the windowed ceiling must be computed from the same constant that " \
        "stops the loop, never a second number that can drift from it"
    assert 'f" LIMIT {int(_sql_limit)}" if _sql_limit else ""' in src, \
        "and it must reach the query, not just a Python countdown"


def test_an_unwindowed_export_still_streams_everything():
    """The operator asked for every row ("i can still only see like about 100
    rows give me all"). A LIMIT on a plain download would silently truncate
    the answer, which is the opposite fault."""
    src = inspect.getsource(ri.iter_rows)
    assert "if _sql_limit else \"\"" in src, \
        "no window means no LIMIT clause at all"
    # and the ceiling is only ever set when a window is asked for
    assert "_sql_limit = _cap if (days and int(days) > 0) else 0" in src


def test_the_ceiling_is_the_same_number_the_loop_stops_at():
    """Two numbers for one cap is how a file ends up shorter than the rows it
    re-measured."""
    src = inspect.getsource(ri.iter_rows)
    assert "win_left = (_cap if _cap > 0 else -1) if win_days else -1" in src
    assert ri.DAYS_CSV_MAX == 2_000


def test_a_limited_export_keeps_the_win_rate_seek():
    """The plan chooser shrank the seek cap because an unbounded sort is
    ruinous. With a ceiling the sort is bounded, so the seek is right again —
    and the fallback it used instead needs `rows_pr2`, which is NOT on this
    operator's database, so it degraded to random row reads (measured: 500
    rows never finished)."""
    src = inspect.getsource(ri.export_plan)
    assert "limit=0" in inspect.signature(ri.export_plan).__str__() or \
        "limit" in inspect.signature(ri.export_plan).parameters, \
        "export_plan has to be told the export is bounded"
    assert 'if key != "winrate" and not limit:' in src, \
        "a bounded export must not be pushed off the win-rate seek"


def test_the_plan_signature_takes_a_limit():
    assert "limit" in inspect.signature(ri.export_plan).parameters


def test_export_plan_still_refuses_what_it_always_refused():
    """The limit must not become a way past the index guards — those refusals
    are what stop a download scanning 35 million rows to write line one."""
    src = inspect.getsource(ri.export_plan)
    for guard in ("SortNotReady", "build_filter_index", "rows_coin"):
        assert guard in src, guard
