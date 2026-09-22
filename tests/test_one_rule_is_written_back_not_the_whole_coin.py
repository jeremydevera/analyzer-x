"""A row's UPDATE writes back the rule it measured, not the coin's 23,580
rows (docs/RCA.md RCA-2026-09-19-A).

Operator, `Sep 19, 2026`, on #L5LUR5TG (FASTSTOCK 15m, `prank`):
*"L5LUR5TG is just 1 strategy, when i click update backtest you should be
updating this strat only is that what you're doing?"*. The measure did — 180
rows — and then `index_pair` deleted and re-wrote every row the coin had:
**23,580** rows across 125 rules, 11.5 MB, ~190,000 index writes, 48 minutes
at the 8.1 rows/s this disk manages while Backtest v2 runs.

Three things have to stay true for the targeted write to be safe, and each is
a test here: the other rules are untouched, a combination the new measure no
longer produces is REMOVED, and `pairs.n` still equals what the table holds.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from tradingagents import rows_index as ri


def _row(signal: str, tp: float, profit: float = 1.0) -> dict:
    return {"id": f"{signal}{tp}", "coin": "FASTSTOCK", "tf": "15m",
            "signal": signal, "th": 0.0, "sl": 1.5, "tp": tp, "sizing": "flat",
            "trades": 10, "wins": 8, "losses": 2, "winrate": 80.0,
            "profit": profit, "days": 30, "bars": 2880}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    from tradingagents import market_sweep as msw
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    (tmp_path / "rows").mkdir()
    (tmp_path / "state").mkdir()
    ri.ensure()
    return tmp_path


def _write_file(store, rows) -> object:
    f = store / "rows" / "FASTSTOCK-15m.json"
    f.write_text(json.dumps(rows), encoding="utf-8")
    return f


def _in_table(store, signal=None):
    con = sqlite3.connect(store / "rows.db")
    try:
        if signal:
            return con.execute("SELECT COUNT(*) FROM rows WHERE pair=? AND signal=?",
                               ("FASTSTOCK-15m", signal)).fetchone()[0]
        return con.execute("SELECT COUNT(*) FROM rows WHERE pair=?",
                           ("FASTSTOCK-15m",)).fetchone()[0]
    finally:
        con.close()


def test_only_the_named_rule_is_rewritten(store):
    everything = [_row("prank", 0.4), _row("prank", 0.8),
                  _row("mom6", 1.0), _row("ibs", 2.0), _row("ote", 3.0)]
    f = _write_file(store, everything)
    assert ri.index_pair(f) == 5

    # the prank rule is re-measured: one of its rows changes, the others' rows
    # must not be touched
    changed = [_row("prank", 0.4, profit=99.0), _row("prank", 0.8, profit=98.0),
               _row("mom6", 1.0), _row("ibs", 2.0), _row("ote", 3.0)]
    _write_file(store, changed)
    landed = ri.index_pair(f, signals=["prank"])
    assert landed == 2, "only the rule's own rows were written"

    con = sqlite3.connect(store / "rows.db")
    try:
        got = dict(con.execute(
            "SELECT signal, MAX(profit) FROM rows WHERE pair=? GROUP BY signal",
            ("FASTSTOCK-15m",)).fetchall())
    finally:
        con.close()
    assert got["prank"] == 99.0, "the measured rule is current"
    assert got["mom6"] == 1.0 and got["ibs"] == 1.0 and got["ote"] == 1.0
    assert _in_table(store) == 5, "nothing was lost from the other rules"


def test_a_combination_that_vanished_leaves_the_table_too(store):
    f = _write_file(store, [_row("prank", 0.4), _row("prank", 0.8), _row("mom6", 1.0)])
    ri.index_pair(f)
    assert _in_table(store, "prank") == 2

    # the new measure keeps only one prank combination (the other fell under
    # the trade floor) — the stale one must not survive
    _write_file(store, [_row("prank", 0.4), _row("mom6", 1.0)])
    ri.index_pair(f, signals=["prank"])
    assert _in_table(store, "prank") == 1
    assert _in_table(store) == 2


def test_the_pair_count_still_matches_the_table(store):
    f = _write_file(store, [_row("prank", 0.4), _row("mom6", 1.0), _row("ibs", 2.0)])
    ri.index_pair(f)
    ri.index_pair(f, signals=["prank"])
    con = sqlite3.connect(store / "rows.db")
    try:
        n = con.execute("SELECT n FROM pairs WHERE pair=?",
                        ("FASTSTOCK-15m",)).fetchone()[0]
    finally:
        con.close()
    assert n == _in_table(store) == 3, \
        "`SUM(n) FROM pairs` is the row count every screen prints"


def test_a_full_refile_is_unchanged(store):
    """No `signals` means exactly what it always meant."""
    f = _write_file(store, [_row("prank", 0.4), _row("mom6", 1.0)])
    assert ri.index_pair(f) == 2
    _write_file(store, [_row("prank", 0.4)])
    assert ri.index_pair(f) == 1
    assert _in_table(store) == 1, "the whole coin is replaced, as before"


def test_the_row_update_job_names_its_one_rule():
    import inspect

    from tradingagents import db_jobs as dj

    src = inspect.getsource(dj._run_pairbt)
    i = src.index("ri.index_pair(")
    call = src[i:i + 200]
    assert "signals=([signal] if signal else None)" in call, call
    # and the ETA is the work this write will really do
    assert "_ix_total = (n_rows if signal" in src
