"""A bulk catch-up must not pay for indexes it is designed to rebuild after.

Operator, Sep 10, 2026, after Stored strategies sat at 4,558 of 5,364 pairs all
day: *"so the measure is still in progress?"* — no. Measuring had finished
(cloud run 34373004043, completed/success, 1 pending pair). The INDEXING had
806 pairs to go and was moving about one pair every fourteen minutes, which is
over a week.

`sync()`'s own closing note states the design:

    "a fill pays for every index it carries: 1.5 pairs/min with six against
     75 with none"

and `_after_fill_indexes()` rebuilds the on-demand ones afterwards, detached.
So a bulk fill is *supposed* to run on the kept four. Nothing ever dropped the
others, so once they existed every fill carried them forever. Measured on the
operator's store that day:

    ensure() creates          4 indexes
    the file held            14
    built on demand, never dropped:
        rows_wr2 rows_wr3 rows_wr4 rows_pr2 rows_id rows_signal
        rows_conf_dd rows_conf_profit rows_conf_trades rows_conf_winrate

Ten extra indexes to maintain per inserted row, on a 33 GB file on a mechanical
disk — 250 MB of scattered I/O every forty seconds while `pairs_indexed` stood
still.

The four that stay are not negotiable. Dropping `rows_profit` on 2026-08-27 at
12:48am blanked the default screen for ~25 minutes ("why does it not show
anything"), which is why `KEEP_INDEXES` exists. A filter whose index is briefly
missing already answers `SortNotReady` — a wait the panel renders. A blank
Stored strategies is the product not working; a slow filter is not.
"""
from __future__ import annotations

import inspect
import sqlite3

import pytest

from tradingagents import rows_index as ri


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE rows (id TEXT, coin TEXT, pair TEXT, profit REAL,"
              " winrate REAL, trades INT, sizing TEXT, tf TEXT, signal TEXT,"
              " tp REAL, sl REAL, dd REAL)")
    for ddl in ri.KEEP_INDEXES:
        c.execute(ddl)
    # the ten the operator's store had accumulated
    for name, cols in (("rows_wr2", "winrate DESC, trades, profit DESC, id"),
                       ("rows_wr3", "winrate DESC, trades, sizing, profit DESC, id"),
                       ("rows_wr4", "winrate DESC, trades, sizing, tf, signal, tp, sl, coin"),
                       ("rows_pr2", "profit DESC, sizing, tp, winrate, trades, id"),
                       ("rows_id", "id"),
                       ("rows_signal", "signal, profit DESC"),
                       ("rows_conf_dd", "dd"),
                       ("rows_conf_profit", "profit"),
                       ("rows_conf_trades", "trades"),
                       ("rows_conf_winrate", "winrate")):
        c.execute(f"CREATE INDEX {name} ON rows ({cols})")
    return c


def _names(c):
    return sorted(r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='rows'"
        " AND name NOT LIKE 'sqlite_%'"))


def test_the_kept_four_are_exactly_what_ensure_creates():
    assert ri._kept_index_names() == {
        "rows_pair", "rows_profit", "rows_coin", "rows_winrate"}


def test_the_on_demand_list_is_read_from_the_database_not_a_constant(con):
    """An index added for next month's filter costs the fill the same and must
    be found without anyone remembering to list it."""
    con.execute("CREATE INDEX rows_future_filter ON rows (tp, sl)")
    assert "rows_future_filter" in ri.on_demand_indexes(con)
    src = inspect.getsource(ri.on_demand_indexes)
    assert "sqlite_master" in src


def test_a_bulk_fill_drops_the_ten_and_keeps_the_four(con):
    gone = ri._drop_on_demand_indexes(con)
    assert len(gone) == 10, gone
    assert _names(con) == ["rows_coin", "rows_pair", "rows_profit",
                           "rows_winrate"]


def test_it_can_never_drop_an_index_the_screen_orders_by(con):
    """The 2026-08-27 incident: dropping rows_profit blanked the page."""
    ri._drop_on_demand_indexes(con)
    for kept in ri._kept_index_names():
        assert kept in _names(con), f"{kept} was dropped — that blanks the page"


def test_dropping_is_opt_in_and_off_by_default():
    """It shipped as automatic-on-bulk and took the operator's filters down
    within minutes (Sep 10, 2026): three of the ten are rows_wr2/wr3/wr4,
    which is what a win-% floor uses, and the rebuild queue runs ONE index at
    a time (~42 min for rows_wr3 alone) so the outage outlasts the fill.
    A slow fill is invisible; a filter that cannot answer is not."""
    import inspect as _i

    assert _i.signature(ri.sync).parameters["drop_indexes"].default is False, \
        "a catch-up must never take a filter away unless it was asked to"
    src = inspect.getsource(ri.sync)
    i = src.index("_drop_on_demand_indexes(")
    guard = src[max(0, i - 260):i]
    assert "if bulk and drop_indexes:" in guard, \
        "the drop needs BOTH a bulk fill and an explicit ask"
    assert ri.BIG_FILL >= 100, ri.BIG_FILL


def test_every_dropped_index_can_be_rebuilt(con):
    """A drop is only safe because each one is rebuildable on demand."""
    gone = ri._drop_on_demand_indexes(con)
    for name in gone:
        assert name in ri.INDEX_DDL, \
            f"{name} was dropped with no DDL to rebuild it"


def test_the_fill_still_starts_the_rebuilds_when_it_ends():
    src = inspect.getsource(ri.sync)
    assert "_after_fill_indexes()" in src
    assert "if done:" in src[src.index("_after_fill_indexes()") - 120:
                             src.index("_after_fill_indexes()")]


def test_a_failed_drop_does_not_fail_the_fill(con):
    """A fill that indexed pairs must never be reported as failed because one
    DROP could not run. `sqlite3.Connection.execute` is read-only, so the
    refusal comes from a thin stand-in rather than a patched method."""

    class Flaky:
        def __init__(self, real):
            self._real = real

        def execute(self, sql, *a):
            if sql.startswith("DROP INDEX") and "rows_wr4" in sql:
                raise sqlite3.OperationalError("database is locked")
            return self._real.execute(sql, *a)

        def commit(self):
            return self._real.commit()

    gone = ri._drop_on_demand_indexes(Flaky(con))
    assert "rows_wr4" not in gone, "the one that refused must not be claimed"
    assert len(gone) == 9, gone
    assert "rows_wr4" in _names(con), "and it is still there, still usable"
