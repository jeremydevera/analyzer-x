"""The Backtest v2 tab lists only rows whose target is bigger than their stop.

Operator, Oct 06, 2026: "take note you will only replace the ones that has
higher sl than tp or if tp same as sl, you will change it as well example
tp=5% sl=5% / the goal is to have higher tp than sl", for the Backtest tab's
stored strategies only ("Backtest tab only" for the rooms). Spec:
docs/superpowers/specs/2026-10-06-backtest-v2-target-over-stop-design.md

THE INDEX ONLY, never the pair files (final review, Oct 06, 2026): the rooms
read the pair files. Main switched off 256 TP <= SL strategies in the 14 days
to Oct 06, 2026; dropping their rows from the files would have left Backtest
a room with nothing to replay for them (room_replay.room_picks reads the
files), and a paused one could never be switched back on (the watcher switches
off a row its file no longer holds). The index — the Stored strategies table,
its CSV, its id lookup and the rooms' switch-on search — is what "the Backtest
tab" is.
"""
from __future__ import annotations

import sqlite3
import types

import pytest

from tradingagents import backtest_report as br, market_sweep as msw
from tradingagents import rows_index as ri


def _row(sl, tp, res="1m", **kw):
    return {"coin": "GPNSTOCK", "tf": "1h", "signal": "stoch14", "th": 0.0,
            "sl": sl, "tp": tp, "sizing": "flat", "res": res, "trades": 12,
            "wins": 8, "losses": 4, "winrate": 66.67, "profit": 5.0,
            "monthly": {}, "last_ms": 1, **kw}


# ------------------------------------------------------------------ the rule
def test_a_target_bigger_than_the_stop_is_listed():
    assert br.target_over_stop(_row(5.0, 6.0))
    assert br.index_keeps(_row(5.0, 6.0))


def test_an_equal_target_is_not_listed():
    assert not br.target_over_stop(_row(5.0, 5.0))
    assert not br.index_keeps(_row(5.0, 5.0))


def test_a_stop_bigger_than_the_target_is_not_listed():
    assert not br.index_keeps(_row(5.0, 4.0))


def test_equal_within_rounding_is_not_bigger():
    assert not br.target_over_stop(_row(1.0, 1.0000000001))


def test_a_v1_row_is_never_touched():
    assert br.index_keeps(_row(5.0, 4.0, res=None))
    assert br.index_keeps(_row(5.0, 5.0, res=""))


def test_the_flat_only_rule_still_applies_to_the_list():
    assert not br.index_keeps(_row(1.0, 2.0, sizing="martingale"))


def test_the_files_keep_every_flat_row_whatever_its_target():
    assert br.store_keeps(_row(5.0, 5.0))
    assert br.store_keeps(_row(5.0, 4.0))
    assert not br.store_keeps(_row(1.0, 2.0, sizing="martingale"))


# ------------------------------------------------- the files and the index
@pytest.fixture
def index(tmp_path, monkeypatch):
    (tmp_path / "rows").mkdir()
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    ri.ensure()
    return tmp_path


def _three(tf="30m"):
    return [_row(2.0, tp, tf=tf, signal="keltner") for tp in (2.0, 3.0, 1.5)]


def test_the_pair_file_keeps_an_equal_row_the_rooms_read(index):
    """What the watcher and Backtest a room read: every row, untouched."""
    msw.save_pair_rows("GPNSTOCK", "30m", _three())
    msw.merge_pair_rows("GPNSTOCK", "30m", [])
    msw.rewrite_pair_rows("GPNSTOCK", "30m", lambda rows: rows)
    assert sorted(r["tp"] for r in msw.pair_rows("GPNSTOCK", "30m")) == [1.5, 2.0, 3.0]


def test_the_index_files_only_rows_whose_target_is_bigger(index):
    msw.save_pair_rows("GPNSTOCK", "30m", _three())
    ri.index_pair(msw.ROWDIR / "GPNSTOCK-30m.json")
    con = sqlite3.connect(index / "rows.db")
    try:
        filed = sorted((r[0], r[1]) for r in con.execute("SELECT sl, tp FROM rows"))
    finally:
        con.close()
    assert filed == [(2.0, 3.0)]


def test_the_index_and_the_files_read_their_own_rule():
    import inspect

    assert "br.index_keeps(r)" in inspect.getsource(ri._kept)
    assert "br.store_keeps(r)" in inspect.getsource(msw.save_pair_rows)
    assert "br.store_keeps(r)" in inspect.getsource(msw.rewrite_pair_rows)


def test_a_row_written_to_its_file_still_reaches_the_watcher(index, monkeypatch):
    """The watcher's hourly switch-off check finds a running row in its pair
    file (strategy_watcher._fresh_row -> watcher_candidates.matched_rows): a
    TP = SL row Main runs (keltner_30m_sl2tp2 on GPNSTOCK) must still be
    there after any write, or the room switches it off within the hour."""
    from tradingagents import watcher_candidates as wc

    monkeypatch.setattr(wc, "stores", types.SimpleNamespace(V2=types.SimpleNamespace(home=index)))
    wc._MATCH_CACHE.clear()
    msw.save_pair_rows("GPNSTOCK", "30m", _three())
    got = wc.matched_rows("GPNSTOCK", "30m",
                          [{"signal": "keltner", "th": 0.0, "sl": 2.0, "tp": 2.0}])
    assert got and [float(r["tp"]) for r in got.values() if r] == [2.0]
