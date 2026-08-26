"""While a sweep is running the indexer stands down completely.

Measured on the PC, Aug 26, 2026 1:46am. The data home is on a spinning HDD
(G:), the row index is a 6 GB SQLite beside it. With the indexer trickling one
pair every 10 s the sweep managed 36 pairs/hour; with the indexer's process
killed it managed 220 pairs/hour, from the same 11 workers. Six times.

The disk explains it: G: showed 384 write IOPS at 5 MB/s -- ~13 KB random
writes -- with a queue of 5.2 and 15 ms per write, while the workers sat at
41% CPU waiting. One trickled pair is thousands of scattered inserts into a
6 GB B-tree with four filter indexes; a platter cannot do that and feed
eleven measuring processes at the same time.

The trickle was never draining the backlog anyway: eleven workers finish
~22 pairs a minute at 220/hour, and the trickle indexes 6. So while a
backtest runs the indexer indexes NOTHING and says so; when the sweep ends the
next tick takes the whole backlog in one BULK pass, which is the fast path
(it drops the four filter indexes, inserts, and rebuilds them once).
"""
import json
import time

import pytest

from tradingagents import market_sweep as msw, rows_index as ri


def _row(coin, tf, sig, profit):
    return {"coin": coin, "tf": tf, "signal": sig, "th": 0.0, "tp": 2.0,
            "sl": 1.0, "sizing": "flat", "profit": profit, "trades": 10,
            "wins": 6, "losses": 4, "winrate": 60.0, "dd": 1.0, "days": 60,
            "bars": 1000, "monthly": {}}


@pytest.fixture
def store(tmp_path, monkeypatch):
    rows = tmp_path / "rows"
    rows.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    monkeypatch.setattr(ri, "PIDFILE", tmp_path / "rows_index.pid")
    ri._ready.clear()
    ri.ensure()
    for i in range(20):
        (rows / f"MANY{i}-1h.json").write_text(json.dumps([_row(f"MANY{i}", "1h", "mom6", float(i))]))
    return rows


def test_a_running_sweep_pauses_indexing_altogether(store, monkeypatch):
    monkeypatch.setattr(ri, "_machine_is_busy", lambda: True)
    got = ri.sync(now=time.time() + ri.SETTLE_S + 1)
    assert got["pairs"] == 0, f"indexed {got['pairs']} pairs while the sweep ran"
    assert got["paused"] is True
    assert got["left"] >= 20, "the backlog is reported honestly, not hidden"
    assert ri.status()["paused"] is True, "the screen has to be able to say so"


def test_an_idle_machine_takes_the_whole_backlog(store, monkeypatch):
    monkeypatch.setattr(ri, "_machine_is_busy", lambda: False)
    got = ri.sync(now=time.time() + ri.SETTLE_S + 1)
    assert got["left"] == 0, f"idle machine still left {got['left']}"
    assert got["pairs"] >= 20 and not got.get("paused")
    assert ri.query(coin="MANY7", limit=5)["total"] == 1


def test_an_explicit_force_still_indexes_during_a_sweep(store, monkeypatch):
    """A person clicking 'index now' is not the timer; their request wins."""
    monkeypatch.setattr(ri, "_machine_is_busy", lambda: True)
    got = ri.sync(now=time.time() + ri.SETTLE_S + 1, force=True)
    assert got["pairs"] >= 20 and not got.get("paused")


def test_the_timer_loop_does_not_sync_while_a_sweep_runs(store, monkeypatch):
    calls = []
    monkeypatch.setattr(ri, "_machine_is_busy", lambda: True)
    monkeypatch.setattr(ri, "sync", lambda **kw: calls.append(kw) or {
        "pairs": 0, "rows": 0, "seconds": 0.0, "left": 20, "paused": True})
    assert ri.start_keeping_up(every_s=0.2, budget_s=5.0)
    try:
        time.sleep(1.0)
    finally:
        ri.stop_keeping_up()
    assert calls == [], "the timer must not call sync at all while sweeping"


def test_the_background_kick_refuses_while_a_sweep_runs(store, monkeypatch):
    monkeypatch.setattr(ri, "_machine_is_busy", lambda: True)
    assert ri.sync_in_background() is False
    monkeypatch.setattr(ri, "_machine_is_busy", lambda: False)
    assert ri.sync_in_background() is True
    for _ in range(50):
        if not ri._syncing.is_set():
            break
        time.sleep(0.1)


def test_the_pause_is_measured_not_a_guess():
    """The 6x figure is in the module, so the next person to raise the trickle
    reads why it was dropped."""
    src = open("tradingagents/rows_index.py", encoding="utf-8").read()
    assert "220 pairs/hour" in src and "36 pairs/hour" in src
