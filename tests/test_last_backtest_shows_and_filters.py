"""Every row says WHEN it was last backtested, and you can filter on it.

Operator, Sep 10, 2026: *"my goal is to filter on when was the last backtest
for each strategy, because even i filter last 30 days some of them was last
backtested 3 weeks ago which is obsolete"*, then *"okay then do it then, when i
do backtest make sure to show the last backtest"*.

They were right, and it was measurable on their own store the same minute:

    EPIK-30m          measured through  Aug 26, 2026 3:30am   (15.8 days old)
    SCRT-30m          measured through  Aug 26, 2026 4:00am
    BIANRENSHENG-15m  measured through  Sep 10, 2026 9:45am

A "last 30 days" window re-measures each row over its own last 30 days — but
it can only use candles that were fetched when that coin was last backtested,
so on the first row that window ENDS 15.8 days ago. The window was never
wrong; nothing on screen said how old the measurement underneath it was.

The date already existed: `pairs.last_ms`, one row per coin+timeframe. So this
costs no measurement at all — the alternative, rebuilding each row's trades to
find its last TRADE, was measured at **1.05 s per row**, which over the store's
96,313,064 rows is **28,091 hours**.

Two fields, because they answer different questions:

* `measured_ms` — the last CANDLE the backtest tested (`pairs.last_ms`)
* `measured_run_ms` — when that coin's results were last WRITTEN
  (`pairs.rows_mtime`); a coin can be re-run and still reach the same candle
"""
from __future__ import annotations

import inspect
import json
import sqlite3
import time
from pathlib import Path

import pytest

from tradingagents import market_sweep as msw, rows_index as ri

DAY = 86_400_000


def _pair(rows_dir, states, coin, tf, n, last_ms):
    (rows_dir / f"{coin}-{tf}.json").write_text(json.dumps([
        {"id": f"{coin}{tf}{i}", "coin": coin, "tf": tf, "signal": "rsi14",
         "sizing": "flat", "trades": 40, "wins": 30, "losses": 10,
         "winrate": 75.0, "profit": 10.0, "tp": 2.0, "sl": 1.0,
         "monthly": {}} for i in range(n)]), encoding="utf-8")
    (states / f"{coin}-{tf}.json").write_text(
        json.dumps({"__last_ms__": last_ms, "__version__": "t"}),
        encoding="utf-8")


@pytest.fixture()
def store(tmp_path, monkeypatch):
    rows_dir, states = tmp_path / "rows", tmp_path / "states"
    rows_dir.mkdir()
    states.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(msw, "STATES", states)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri._ready.discard(str(tmp_path / "rows.db"))
    now = int(time.time() * 1000)
    # FRESH: measured an hour ago.  STALE: 16 days ago, like EPIK-30m.
    _pair(rows_dir, states, "FRESH", "1h", 4, now - 3_600_000)
    _pair(rows_dir, states, "STALE", "1h", 3, now - 16 * DAY)
    ri.ensure()
    ri.sync()
    return tmp_path


# ------------------------------------------------------- the date on every row
def test_every_row_carries_when_it_was_last_backtested(store):
    got = ri.query(limit=10)
    assert got["rows"], "no rows to check"
    for r in got["rows"]:
        assert r.get("measured_ms"), f"#{r.get('id')} has no measured_ms"
        assert r.get("measured_run_ms"), f"#{r.get('id')} has no run stamp"
    fresh = [r for r in got["rows"] if r["coin"] == "FRESH"][0]
    stale = [r for r in got["rows"] if r["coin"] == "STALE"][0]
    assert fresh["measured_ms"] > stale["measured_ms"], \
        "the two pairs must not report the same date"
    age_days = (time.time() * 1000 - stale["measured_ms"]) / DAY
    assert 15 < age_days < 17, f"the stale pair reads {age_days:.1f} days old"


def test_the_private_pair_key_never_reaches_the_caller(store):
    """The lookup needs the pair; the row's shape is the table's contract, and
    an extra `_pair` would ride into the CSV and the browser."""
    for r in ri.query(limit=10)["rows"]:
        assert "_pair" not in r


def test_an_unknown_pair_reads_UNKNOWN_never_1970(store):
    """A zero here would print `Jan 01, 1970` and read as a real date —
    RCA-2026-09-10-F: a default that reads as data is a lie."""
    rows = [{"_pair": "NOSUCH-1h", "id": "X"}]
    ri.stamp_measured(None, rows)
    assert rows[0]["measured_ms"] is None
    assert rows[0]["measured_run_ms"] is None


def test_a_locked_store_leaves_the_dates_unknown_not_wrong(store, monkeypatch):
    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ri, "_open", locked)
    rows = [{"_pair": "FRESH-1h", "id": "X"}]
    ri.stamp_measured(None, rows)
    assert rows[0]["measured_ms"] is None, "unknown, and the screen prints a dash"


# ------------------------------------------------------------------ the filter
def test_the_filter_cuts_a_stale_pair_and_keeps_a_fresh_one(store):
    tight = ri.query(limit=10, measured_days=2)
    assert {r["coin"] for r in tight["rows"]} == {"FRESH"}
    wide = ri.query(limit=10, measured_days=30)
    assert {r["coin"] for r in wide["rows"]} == {"FRESH", "STALE"}
    off = ri.query(limit=10, measured_days=0)
    assert {r["coin"] for r in off["rows"]} == {"FRESH", "STALE"}


def test_the_filter_runs_IN_THE_QUERY_not_over_the_page(store):
    """FILTER WHERE THE DATA IS (CLAUDE.md). The page is the top N by profit,
    so cutting it afterwards would answer about the page instead of the
    store — the exact shape of the Sep 09, 2026 history bug."""
    where, args = ri._where(measured_since_ms=ri.measured_cut_ms(7),
                            order_owns_index=True, order_key="profit")
    assert "pair IN (SELECT pair FROM pairs WHERE last_ms >= ?)" in where
    assert args and isinstance(args[-1], int)
    # and it steps aside so it cannot steal the ORDER BY's index
    assert "+pair IN" in where


def test_the_count_agrees_with_the_rows(store):
    """MEASURED on the live store while building this: `measured within 3 days`
    over EPIK-30m showed **0 rows beside a count of 1,580**, because the exact
    count came from the pair summaries and the filter was not applied there.
    A count that disagrees with the rows under it is label-must-match-data."""
    tight = ri.query(coin="STALE", tf="1h", limit=10, measured_days=2)
    assert len(tight["rows"]) == 0
    assert tight["total"] == 0, \
        f"0 rows under a total of {tight['total']} is the bug this pins"
    wide = ri.query(coin="STALE", tf="1h", limit=10, measured_days=30)
    assert len(wide["rows"]) == 3 and wide["total"] == 3


def test_it_stacks_as_AND_with_the_other_filters(store):
    got = ri.query(limit=10, measured_days=2, min_winrate=70.0, sizing="flat")
    assert {r["coin"] for r in got["rows"]} == {"FRESH"}
    assert all(r["winrate"] >= 70 for r in got["rows"])


def test_zero_days_means_off_not_now(store):
    """`measured_days=0` must not become "measured since the epoch-now", which
    would cut every row."""
    assert ri.measured_cut_ms(0) == 0
    assert ri.measured_cut_ms(None) == 0
    assert ri.measured_cut_ms(7) > 0
    assert ri.query(limit=10, measured_days=0)["rows"]


def test_the_cut_is_one_implementation(store):
    """Two copies of a date rule in this repo have drifted apart before — the
    whole `fmt_when` rule exists for that reason."""
    for fn in (ri.query, ri.iter_rows):
        assert "measured_days" in str(inspect.signature(fn))
    src = inspect.getsource(ri)
    assert src.count("def measured_cut_ms(") == 1
    assert src.count("(time.time() - d * 86400) * 1000") == 1


# --------------------------------------------------------------- the CSV, kit F
def test_the_csv_carries_both_dates_on_every_row(store):
    from tradingagents import api
    out = "".join(api.strategies_csv_lines(coin="FRESH", batch=10))
    head = out.splitlines()[0].split(",")
    assert "measured_through" in head and "last_backtest_run" in head
    body = out.splitlines()[1]
    # the project's ONE date format, never an epoch and never a compact stamp
    assert ", 20" in body and ("am" in body or "pm" in body), body
    assert "1970" not in body


def test_the_csv_obeys_the_filter_too(store):
    from tradingagents import api
    tight = "".join(api.strategies_csv_lines(batch=10, measured_days=2))
    assert "FRESH" in tight and "STALE" not in tight, \
        "a file holding rows the table cut is the kit-item-F failure"
    wide = "".join(api.strategies_csv_lines(batch=10, measured_days=30))
    assert "FRESH" in wide and "STALE" in wide


def test_the_route_hands_the_filter_to_the_file():
    """The window itself was declared and never written once (Sep 09, 2026):
    42,420 rows of whole history under a filename saying `last30d`. So this
    reads the CALL, not the file."""
    src = inspect.getsource(__import__("tradingagents.api", fromlist=["x"])
                            .strategies_csv)
    assert "measured_days=measured_days" in src


# ------------------------------------------------------------------ the screen
PANEL = Path("webapp/src/components/backtest/StrategiesPanel.tsx")
CLIENT = Path("webapp/src/lib/api.ts")


def test_the_panel_has_the_box_the_chip_and_the_column():
    src = PANEL.read_text(encoding="utf-8")
    assert 'aria-label="Backtested within N days"' in src, "the box"
    assert "Backtested within ${f.measuredDays} day" in src, "its chip"
    assert '"last backtest",' in src, "the column header"
    assert "r.measured_ms ? fmtWhenMs(r.measured_ms) : \"—\"" in src, \
        "the cell, in the project's one date format, dash for unknown"


def test_the_panel_sends_it_and_names_it():
    src = PANEL.read_text(encoding="utf-8")
    assert "measuredDays: applied.measuredDays || undefined," in src
    assert src.count("measuredDays: applied.measuredDays || undefined,") == 2, \
        "the table AND the download, or the file disagrees with the screen"
    assert "backtested within ${f.measuredDays} day" in src, \
        "the AND sentence must name it, like every other filter"
    assert "measuredDays: setMeasuredDays," in src, "clear-all must reach it"


def test_the_client_sends_the_parameter_and_types_the_fields():
    src = CLIENT.read_text(encoding="utf-8")
    assert src.count('p.set("measured_days", String(q.measuredDays))') == 2
    assert "measured_ms?: number;" in src
    assert "measured_run_ms?: number;" in src


def test_the_column_is_not_hidden_behind_a_window():
    """The `window` column REPLACES green while a days window is on. This one
    must not: the whole point is to see the age of the measurement WHILE
    looking at a windowed table."""
    src = PANEL.read_text(encoding="utf-8")
    line = [ln for ln in src.splitlines() if '"last backtest",' in ln]
    assert len(line) == 1, line
    # a plain entry in the header array — no ternary, nothing spread in
    assert line[0].strip() == '"last backtest",', line[0]
    # and the CELL is unconditional too: it reads the row, never the filters
    cell = src[src.index("{r.measured_ms ? fmtWhenMs") - 900:
               src.index("{r.measured_ms ? fmtWhenMs")]
    assert "servedFilters" not in cell, \
        "the last-backtest cell must not depend on which window is on"
