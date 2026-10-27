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
    """...and, since Oct 16, 2026, one that pays 2:1 after fees: bigger on
    paper is necessary, no longer enough (tests/test_two_to_one_after_fees.py)."""
    assert br.target_over_stop(_row(5.0, 6.0))
    assert br.index_keeps(_row(2.0, 6.0, cost_of_tp=5.0, gate="ok"))       # +5.70 vs -2.30
    assert not br.index_keeps(_row(5.0, 6.0, cost_of_tp=5.0, gate="ok"))   # +5.70 vs -5.30


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


def test_the_files_keep_only_flat_rows_that_pay_two_to_one():
    """Since Oct 27, 2026 the files hold what the list holds (they kept every
    flat row from Oct 06): equal and smaller targets, and a target that does
    not pay 2:1 after its fee, are not kept; v1 rows, any."""
    assert not br.store_keeps(_row(5.0, 5.0, cost_of_tp=5.0, gate="ok"))
    assert not br.store_keeps(_row(5.0, 4.0, cost_of_tp=5.0, gate="ok"))
    assert br.store_keeps(_row(1.0, 3.0, cost_of_tp=5.0, gate="ok"))
    assert not br.store_keeps(_row(1.0, 3.0, sizing="martingale", cost_of_tp=5.0, gate="ok"))
    assert br.store_keeps(_row(5.0, 5.0, res=None))


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


def _pays(tp):
    return _row(1.0, tp, tf="30m", signal="keltner", cost_of_tp=5.0, gate="ok")


def test_the_pair_file_keeps_only_two_to_one_after_fees(index):
    """Oct 27, 2026, "then update it now": the stored files hold what the list
    holds - 2:1 after fees - on EVERY write (a night's merge, a live post, an
    UPDATE). Until then they kept every row so rooms could replay what they
    had run; the list was cut from them (spec 2026-10-06)."""
    rows = [_pays(1.0), _pays(3.0), _pays(0.75)]     # equal, 2:1, smaller
    msw.save_pair_rows("GPNSTOCK", "30m", rows)
    assert [r["tp"] for r in msw.pair_rows("GPNSTOCK", "30m")] == [3.0]
    msw.merge_pair_rows("GPNSTOCK", "30m", [_pays(1.0)])
    assert [r["tp"] for r in msw.pair_rows("GPNSTOCK", "30m")] == [3.0]
    msw.rewrite_pair_rows("GPNSTOCK", "30m", lambda r: r + [_pays(0.75)])
    assert [r["tp"] for r in msw.pair_rows("GPNSTOCK", "30m")] == [3.0]


def test_a_v1_pair_file_is_never_trimmed(index):
    msw.save_pair_rows("GPNSTOCK", "30m", [_row(2.0, 1.0, tf="30m", res=None)])
    assert len(msw.pair_rows("GPNSTOCK", "30m")) == 1


def test_the_index_files_only_rows_whose_target_is_bigger(index):
    # a 1% stop: the bigger target (3%) also pays 2:1 after its 0.15% fee
    # (+2.85 vs -1.15 a loss); the equal and the smaller ones are left out
    msw.save_pair_rows("GPNSTOCK", "30m", [_row(1.0, tp, tf="30m", signal="keltner", cost_of_tp=5.0,
                                                gate="ok") for tp in (1.0, 3.0, 0.75)])
    ri.index_pair(msw.ROWDIR / "GPNSTOCK-30m.json")
    con = sqlite3.connect(index / "rows.db")
    try:
        filed = sorted((r[0], r[1]) for r in con.execute("SELECT sl, tp FROM rows"))
    finally:
        con.close()
    assert filed == [(1.0, 3.0)]


def test_the_index_and_the_files_read_their_own_rule():
    import inspect

    assert "br.index_keeps(r)" in inspect.getsource(ri._kept)
    assert "br.store_keeps(r)" in inspect.getsource(msw.save_pair_rows)
    assert "br.store_keeps(r)" in inspect.getsource(msw.rewrite_pair_rows)


def test_a_strategy_the_files_no_longer_hold_is_switched_off_by_the_watcher(index, monkeypatch):
    """The watcher's hourly check finds a running row in its pair file
    (watcher_candidates.matched_rows); a strategy that is not 2:1 after fees is
    no longer there, and the room switches it off ("the backtest store no
    longer holds this row") - the rule it already switches it off by."""
    from tradingagents import watcher_candidates as wc

    monkeypatch.setattr(wc, "stores", types.SimpleNamespace(V2=types.SimpleNamespace(home=index)))
    wc._MATCH_CACHE.clear()
    msw.save_pair_rows("GPNSTOCK", "30m", [_pays(1.0), _pays(3.0)])
    got = wc.matched_rows("GPNSTOCK", "30m", [{"signal": "keltner", "th": 0.0, "sl": 1.0, "tp": 1.0},
                                              {"signal": "keltner", "th": 0.0, "sl": 1.0, "tp": 3.0}])
    assert [float(r["tp"]) for r in got.values() if r] == [3.0]
