"""Forecast -> Backtest a room (operator, Oct 02, 2026: "i want ability to
backtest room in forecast v1, i want option to filter date range to backtest
so i can see if the deployed tabs attached matches the backtest", and "make
the room tiles in table instead so its not confusing").

One timeline: a 15m strategy switched on at Sep 30, 2026 8:00pm, its backtest
trades on the same clock as its practice trades (RCA-2026-09-12-A).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradingagents import room_backtest as rb

ROOT = Path(__file__).resolve().parents[1]
BAR = 900
ON = 1790812800              # Sep 30, 2026 8:00pm EDT
SLOT = "bb20_15m_sl03tp04|VUG_USDT"


@pytest.fixture
def room(tmp_path, monkeypatch):
    from tradingagents import auto_trader as at
    from tradingagents import local_history as lh
    from tradingagents import rolling30 as r30
    ledger = tmp_path / "ledger.jsonl"
    lines = [
        # the same trade, same result: signal 8:15pm, backtest entry 8:30pm
        {"action": "exit", "dry_run": True, "strategy": "bb20_15m_sl03tp04", "symbol": "VUG_USDT",
         "ts": ON + 3600, "entry_ts": ON + 900, "pnl_est": 0.33},
        # the same trade, a different result
        {"action": "exit", "dry_run": True, "strategy": "bb20_15m_sl03tp04", "symbol": "VUG_USDT",
         "ts": ON + 7200, "entry_ts": ON + 4500, "pnl_est": -0.6},
        # practice only: no backtest trade on that bar
        {"action": "exit", "dry_run": True, "strategy": "bb20_15m_sl03tp04", "symbol": "VUG_USDT",
         "ts": ON + 9000, "entry_ts": ON + 8100, "pnl_est": 0.33},
        # after the backtest's last candle: not comparable yet
        {"action": "exit", "dry_run": True, "strategy": "bb20_15m_sl03tp04", "symbol": "VUG_USDT",
         "ts": ON + 90000, "entry_ts": ON + 89000, "pnl_est": 0.33},
        # the cost check refused the backtest's 11:15pm trade
        {"action": "gate_blocked", "dry_run": True, "strategy": "bb20_15m_sl03tp04",
         "symbol": "VUG_USDT", "ts": ON + 11700},
    ]
    ledger.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    ms = lambda s: s * 1000  # noqa: E731
    rec = {"slot": SLOT, "bar_s": BAR, "end_ms": ms(ON + 43200), "wm": ms(ON + 42300),
           "trades": [[ms(ON - 3600), ms(ON - 1800), 0.33],      # before the switch-on: not counted
                      [ms(ON + 1800), ms(ON + 3600), 0.33],      # = practice #1, same
                      [ms(ON + 5400), ms(ON + 7200), 0.33],      # = practice #2, different
                      [ms(ON + 11700), ms(ON + 12600), 0.33],    # refused by the cost check
                      [ms(ON + 20000), ms(ON + 21000), -0.6]]}   # nothing recorded
    settings = {"strategies": ["bb20_15m_sl03tp04"], "strategy_coins": {"bb20_15m_sl03tp04": ["VUG_USDT"]},
                "watcher_slots": {SLOT: {"id": "ABCD1234", "tf": "15m", "signal": "bb20", "tp": 0.4,
                                         "sl": 0.3, "on_at": ON}}}
    monkeypatch.setattr(rb.profiles, "shown", lambda: ["main", "TESTROOM"])
    monkeypatch.setattr(rb.profiles, "valid", lambda pid: True)
    monkeypatch.setattr(rb.profiles, "get", lambda pid: {"id": pid, "name": pid})
    monkeypatch.setattr(at, "load_settings", lambda: settings)
    monkeypatch.setattr(at, "_pp", lambda p: ledger if p == at.LEDGER_PATH else p)
    monkeypatch.setattr(lh, "deployed_at", lambda: {})
    monkeypatch.setattr(r30, "_load", lambda slot: rec if slot == SLOT else None)
    rb._LEDGER.clear()
    yield
    rb._LEDGER.clear()


def test_both_sides_share_one_window_and_every_gap_has_a_reason(room):
    d = rb.compare("TESTROOM", ON - 86400, ON + 172800)
    m = d["match"]
    assert (m["same"], m["different"], m["practice_only"], m["after_backtest"]) == (1, 1, 1, 1)
    assert m["backtest_only"] == 2
    assert d["reasons"]["gate_blocked"] == 1 and d["reasons"]["none"] == 1
    assert d["backtest"]["trades"] == 4, "the trade before the switch-on is not counted"
    assert d["practice"]["trades"] == 3, "the one after the backtest's last candle is counted apart"
    row = d["rows"][0]
    assert row["id"] == "ABCD1234" and row["on_at"] == ON and row["tp"] == 0.4
    assert row["gap"] == round(d["practice"]["profit"] - d["backtest"]["profit"], 2)


def test_the_date_range_cuts_both_sides(room):
    d = rb.compare("TESTROOM", ON, ON + 5000)
    assert d["backtest"]["trades"] == 1 and d["practice"]["trades"] == 1
    assert d["match"]["same"] == 1


def test_a_room_without_a_tab_and_a_bad_sort_are_refused(room):
    with pytest.raises(ValueError, match="no room"):
        rb.compare("B52662ED", ON, ON + 1)
    with pytest.raises(ValueError, match="sort must be one of"):
        rb.compare("TESTROOM", ON, ON + 1, sort="nonsense")


def test_the_screen_has_the_table_and_the_backtest_and_asks_the_server():
    src = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    # the merged Forecast page has NO Rooms table (operator, Oct 03, 2026
    # 6:30am: "remove the rooms section on very bottom i dont need it"); the
    # first Forecast page keeps it
    merged = src.split("export function RoomsAndBacktest")[1].split("\nfunction ")[0]
    assert "<RoomTable" not in merged and "<RoomBacktestPanel rooms={live.rooms} />" in merged
    first = src.split("export default function RoomForecasts")[1].split("\nfunction ")[0]
    assert "<RoomTable rooms={live.rooms} rules={live.rules} />" in first
    assert "<RoomBacktestPanel rooms={live.rooms} />" in src
    assert "<RoomCard r={r} rules={rules} />" in src, "a row opens the full card"
    # SINCE OCT 03, 2026 the card is the room's own rules replayed day by day
    # (operator, Oct 02-03, 2026: "what strategies did switched on and off for
    # Sept 3, 4, 5, 6, 7 and so on"): days, then a day's switches and trades,
    # every list from the server, ten a page
    panel = src.split("function RoomBacktestPanel")[1].split("\nfunction ")[0]
    for view in ('view: "days"', 'view: "events"', 'view: "trades"'):
        assert view in panel, view
    assert "api.roomReplay(" in panel and "api.roomBacktest(" not in panel
    # the hindsight warning sits ABOVE the totals it changes, never under the
    # tables (Oct 03, 2026: replay +6,947.20 against practice -13.24), and a
    # printed day reads "Sep 01, 2026", never its key "2026-09-01"
    assert panel.index('startsWith("HINDSIGHT")') < panel.index('side("Replay (backtest trades)"')
    assert "{d.from_day} to {d.to_day} · its rules" not in panel and "dayOf(d.start_ms)" in panel
    assert 'type="date"' in src and "fmtWhen" in src
    api_py = (ROOT / "tradingagents/api.py").read_text(encoding="utf-8")
    assert '@app.get("/api/forecasts/room-backtest")' in api_py
    assert '@app.get("/api/rooms/replay")' in api_py


def test_a_quiet_cost_check_refusal_is_named_not_called_no_signal(room):
    """The cost check writes one refusal an hour and refuses silently in
    between (auto_trader._GATE_LOG_EVERY). A backtest trade 40 minutes after
    a written gate_blocked was refused by it — this page called 3,462 such
    trades "the live program saw no signal" (RCA-2026-10-02-B)."""
    mine = [(ON + 1000, "gate_blocked")]
    ts = [x[0] for x in mine]
    assert rb._reason(mine, ts, ON + 1000 + 2400, BAR) == "gate_blocked_quiet"
    assert rb._reason(mine, ts, ON + 1000 - 30, BAR) == "gate_blocked", "written inside its own entry bar"
    assert rb._reason(mine, ts, ON + 1000 + 3600 + BAR + 60, BAR) == "none", "past the quiet hour"
    assert rb._reason([(ON, "chase_skip")], [ON], ON + 2400, BAR) == "none", "only the cost check is quiet"
