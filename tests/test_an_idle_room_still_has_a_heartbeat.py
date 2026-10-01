"""An idle room's runner is alive, and the screen must say so.

Oct 01, 2026 10:19am the operator saw "no heartbeat for 892 min" on
#55D32617: its runner (pid 23988) had run since Sep 30, 2026 7:26pm, but with
nothing switched on a cycle scans no coin and wrote no line, and the badge
reads the log's age. 892 minutes = 7:26pm to 10:19am.
"""
from __future__ import annotations

import logging

from tradingagents import auto_trader as at


def test_a_cycle_with_nothing_switched_on_writes_one_line(caplog):
    with caplog.at_level(logging.INFO, logger=at.logger.name):
        at._idle_beat({"strategies": [], "strategy_coins": {}})
    assert any("idle: nothing is switched on in this room" in r.getMessage()
               for r in caplog.records)


def test_a_room_with_rows_writes_no_idle_line(caplog):
    s = {"strategies": ["bb20_15m_sl03tp04"], "strategy_coins": {"bb20_15m_sl03tp04": ["VUG_USDT"]}}
    with caplog.at_level(logging.INFO, logger=at.logger.name):
        at._idle_beat(s)
    assert not any("idle:" in r.getMessage() for r in caplog.records)


def test_the_runner_loop_calls_it_every_cycle():
    src = open("tradingagents/auto_trader.py", encoding="utf-8").read()
    loop = src[src.index("def run_forever"):]
    assert "                run_cycle()\n            _idle_beat(settings)" in loop


def test_stale_waits_past_one_idle_cycle(monkeypatch, tmp_path):
    """A cycle comes every POLL_SECONDS: at exactly 300 s the badge would
    flicker on every idle wait."""
    import os
    import time

    from fastapi.testclient import TestClient

    from tradingagents import api

    log = tmp_path / "auto_trade.log"
    log.write_text("x", encoding="utf-8")
    monkeypatch.setattr(at, "_pp", lambda p: log if p == at.LOG_PATH else p)
    c = TestClient(api.app)
    for age, stale in ((at.POLL_SECONDS + 20, False), (at.POLL_SECONDS + 120, True)):
        t = time.time() - age
        os.utime(log, (t, t))
        assert c.get("/api/trade/supervisor").json()["stale"] is stale, age
