"""Backtest a room takes a Room strategies id too (operator, Oct 16, 2026:
"when i am trying to back test CB69A137 i dont have option" — and, offered
the choices, "Let Backtest a room take ids").

#CB69A137 is one of the 992 rule sets prompt 4 kept, not a room, and the room
box listed only the 10 rooms. It cannot be REPLAYED on this PC either: its
rule wants a target narrower than the stop ("TP narrower than SL"), and since
Oct 06, 2026 the Backtest v2 list keeps only targets wider than their stop —
169 of the 992 rule sets ask for rows the list no longer holds. So an id's
backtest is its own daily re-test (room_strategies_daily, on GitHub, over
every row), laid out over the chosen dates by the same view the Room
strategies pop-up uses — and it now carries the worst losing run, which every
results table must (CLAUDE.md item 6).
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from tradingagents import room_strategies as rs

WEB = Path(__file__).resolve().parents[1] / "webapp" / "src"
FORECASTS = WEB / "components" / "forecast" / "RoomForecasts.tsx"
DAY = 86_400_000
T0 = 1_791_000_000_000          # Oct 2026, on one timeline with the dates asked


def _kept(monkeypatch, trades):
    w = {"id": "CB69A137", "words": "90% wins, 40+ trades in 15 days, TP narrower than SL",
         "cfg": {"window_days": 15, "tp_rule": "<"}, "trades": np.asarray(trades, float)}
    monkeypatch.setattr(rs, "kept", lambda: [w])
    monkeypatch.setattr(rs, "retested", lambda: {})


def test_a_rule_sets_dates_carry_their_worst_losing_run(monkeypatch):
    # (opened, closed, profit) in close order: +0.84, -1.10, -1.33, +0.86, -0.50
    trades = [(T0 + i * DAY, T0 + i * DAY + 3_600_000, p)
              for i, p in enumerate((0.84, -1.10, -1.33, 0.86, -0.50))]
    _kept(monkeypatch, trades)
    got = rs.trades("#cb69a137", T0 / 1000 - 1, (T0 + 10 * DAY) / 1000)
    assert (got["worst_run"], got["worst_run_trades"]) == (-2.43, 2)
    assert (got["trades"], got["wins"], got["losses"]) == (5, 2, 3)


def test_no_loss_in_the_dates_is_a_run_of_nothing(monkeypatch):
    _kept(monkeypatch, [(T0, T0 + 3_600_000, 0.84)])
    got = rs.trades("CB69A137", T0 / 1000 - 1, (T0 + DAY) / 1000)
    assert (got["worst_run"], got["worst_run_trades"]) == (0.0, 0)


def test_the_table_and_the_trade_list_count_the_run_one_way():
    """The row's "worst run" and the pop-up's must be one number: one helper."""
    src = Path(rs.__file__).read_text(encoding="utf-8")
    assert src.count("_worst_run(") >= 3, "defined once, used by the table AND trades()"


def test_the_room_box_offers_a_rule_set_id_and_the_panel_shows_its_re_test():
    tsx = FORECASTS.read_text(encoding="utf-8")
    picker = tsx[tsx.index("function RoomPicker"):tsx.index("function RoomBacktestPanel")]
    # an 8-letter id with no room behind it becomes a rule set pick
    assert re.search(r"/\^\[A-Z0-9\]\{8\}\$/", picker)
    assert 'pick(`rs:${' in picker
    panel = tsx[tsx.index("function RoomBacktestPanel"):]
    panel = panel[:panel.index("\nfunction ")]
    assert 'startsWith("rs:")' in panel
    assert "<StrategyTrades" in panel, "the id's dates through the pop-up's own view"
    trades_view = tsx[tsx.index("function StrategyTrades"):]
    assert "worst_run" in trades_view[:trades_view.index("\nfunction ")]
