"""A missing index is "I cannot check", never "nothing matches".

Operator, Sep 10, 2026: *"There is nothing wrong with the filter"* — and they
were right. Their filter (`min win % 85 AND last 30 days`) had answered
**HTTP 200 with rows=0, total=0** for minutes, straight after a bulk catch-up
in ANOTHER process dropped `rows_wr2/wr3/wr4`. From their own press log:

    Sep 10, 2026 4:25am  apply | asked: min_winrate=85.0 AND days=30
        AND sort=profit AND desc=True | got: rows=0 · total=0 | took 18.42s

Nothing matched, said the page. 566,990 rows had matched half an hour earlier.

`ri.query()` in a FRESH process refused correctly — *"a win % floor of 85 over
the store needs more than 20s ... The wide win-rate index that makes this
instant is still being built"*. The API's process still had the index in its
`has_index` cache, so it named `rows_wr4`, SQLite answered `no such index`, and
`_missing_ok(fn, default)` returned the default. For `_winrate_matches` that
default is **0** — so "I could not check" became "no row clears this floor",
which then made the whole query answer nothing at all.

`_missing_ok`'s own docstring already warned about this shape for the query
BUDGET: *"swallowing that here turned 'this filter needs longer than 20s' into
'0 rows, total 0' -- an empty screen presented as an answer"*. The guard
matched the word `interrupt` and nothing else. Second time, same failure, one
word away. A guard is only as wide as its pattern.

Only `no such table` earns the empty default — that is `ensure()` not having
run yet, which is what the wrapper was written for.
"""
from __future__ import annotations

import sqlite3

import pytest

from tradingagents import rows_index as ri


def _raises(msg):
    def fn():
        raise sqlite3.OperationalError(msg)
    return fn


def test_a_missing_index_is_re_raised_not_defaulted():
    with pytest.raises(sqlite3.OperationalError):
        ri._missing_ok(_raises("no such index: rows_wr4"), 0)


def test_a_missing_index_drops_the_stale_cache_so_a_retry_can_work(monkeypatch):
    """The cache is what named an index that is gone; a refusal that leaves it
    in place refuses for ever."""
    forgotten = []
    monkeypatch.setattr(ri, "forget_indexes",
                        lambda: forgotten.append(True))
    with pytest.raises(sqlite3.OperationalError):
        ri._missing_ok(_raises("no such index: rows_wr2"), 0)
    assert forgotten, "the index cache must be dropped on the way out"


def test_an_interrupted_read_is_still_re_raised():
    """The original rule, unchanged: a query past its budget is not an empty
    result."""
    with pytest.raises(sqlite3.OperationalError):
        ri._missing_ok(_raises("interrupted"), 0)


def test_a_missing_TABLE_still_earns_the_empty_default():
    """`ensure()` has not run yet — the one case this wrapper exists for."""
    assert ri._missing_ok(_raises("no such table: rows"), 0) == 0
    assert ri._missing_ok(_raises("no such table: pairs"), {}) == {}


def test_a_LOCK_still_earns_the_default_and_that_is_deliberate():
    """The first version of this fix re-raised everything and broke
    `test_a_locked_read_does_not_look_like_a_missing_index`, which exists
    because `has_index` answering False under a lock refused a coin filter
    with every index present (2026-08-26, 503 in 0.02 s).

    A lock is transient and makes the planner CAUTIOUS. A missing index makes
    it WRONG. Only the second is a lie, so only the second raises.
    """
    assert ri._missing_ok(_raises("database is locked"), 0) == 0
    assert ri._missing_ok(_raises("database table is locked"), None) is None


def test_a_good_read_is_untouched():
    assert ri._missing_ok(lambda: 566990, 0) == 566990


def test_the_winrate_count_is_the_one_that_made_it_dangerous():
    """`_winrate_matches` defaults to 0 and its answer decides the query plan,
    so a swallowed error there is a filter that returns nothing."""
    import inspect
    src = inspect.getsource(ri._winrate_matches)
    assert "_missing_ok" in src, \
        "if this stops using _missing_ok, this test must follow it"
