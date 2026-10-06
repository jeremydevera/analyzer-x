"""Rooms switch off a running practice strategy whose target is not bigger
than its stop.

Operator, Oct 06, 2026, asked whether the rooms should also drop any running
strategy whose stop is as big as or bigger than its target: *"update it then,
then reset my backroom practice too"*. Main was running 16 such practice rows
(hand-picked, e.g. keltner_30m_sl2tp2 on GPNSTOCK); the five rule-set rooms
none, because their watchers already switch on only TP > SL.

The room's OWN TP rule decides (watcher_policy.tp_fails) — the same words the
switch-on uses — for the watcher's rows (judge) and for the operator's own
practice rows, whichever backtest they were armed from. Real money is never
touched: the hand pass only ever holds practice-only rows.
"""
from __future__ import annotations

import pytest

from tradingagents import auto_trader as at, strategy_watcher as sw
from tradingagents import watcher_policy as wp

CFG = {**wp.DEFAULTS, "tp_rule": ">", "off_winrate": 90.0, "window_days": 30}
GOOD = {"winrate": 95.0, "trades": 40, "wins": 38, "losses": 2, "profit": 5.0}


def test_judge_switches_off_an_equal_target_whatever_its_win_rate():
    why = wp.judge({"id": "X", "tp": 2.0, "sl": 2.0}, {**GOOD, "tp": 2.0, "sl": 2.0}, CFG)
    assert "TP 2% is not wider than SL 2%" in why


def test_judge_keeps_a_bigger_target_above_the_line():
    assert wp.judge({"id": "X", "tp": 2.5, "sl": 2.0}, {**GOOD, "tp": 2.5, "sl": 2.0}, CFG) == ""


def test_judge_reads_the_target_from_the_row_when_the_slot_has_none():
    """The replay passes {"id": rid} and a book row that carries tp/sl."""
    assert wp.judge({"id": "X"}, {**GOOD, "tp": 1.0, "sl": 1.2}, CFG)


def test_a_room_that_allows_any_target_is_not_changed():
    assert wp.judge({"id": "X", "tp": 1.0, "sl": 1.2}, {**GOOD, "tp": 1.0, "sl": 1.2},
                    {**CFG, "tp_rule": "any"}) == ""


def test_passes_on_and_judge_read_one_tp_rule():
    import inspect

    assert "tp_fails(" in inspect.getsource(wp.passes_on)
    assert "tp_fails(" in inspect.getsource(wp.judge)


# ------------------------------------------- the operator's own practice rows
@pytest.fixture
def room(tmp_path, monkeypatch):
    key, sym = "keltner_30m_sl2tp2", "GPNSTOCK_USDT"
    big = "keltner_30m_sl2tp25"
    w = {"settings": {"strategies": [key, big],
                      "strategy_coins": {key: [sym], big: [sym]},
                      "strategy_books": {key: ["paper"], big: ["paper"]},
                      "strategy_margins": {}, "strategy_sizing": {}, "enabled": False},
         "saves": 0}
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    monkeypatch.setattr(sw, "STATE", tmp_path / "w.json")
    monkeypatch.setattr(sw, "LOG", tmp_path / "w.jsonl")
    monkeypatch.setattr(at, "load_settings", lambda: sw._copy(w["settings"]))

    def _save(s):
        w["saves"] += 1
        w["settings"] = s
        return []

    monkeypatch.setattr(at, "save_settings", _save)
    monkeypatch.setattr(sw, "_candidates", lambda cfg, now: {"rows": [], "why": "fake"})
    monkeypatch.setattr(sw, "_as_the_off_check_sees", lambda rows, now, cfg: rows)
    monkeypatch.setattr(sw, "_fresh_row", lambda meta, now, cfg: (None, True))
    monkeypatch.setattr(sw, "_delisted", lambda syms: set())
    monkeypatch.setattr(sw.time, "sleep", lambda s: None)
    from tradingagents import notifications as nt

    monkeypatch.setattr(nt, "record", lambda *a, **k: 1)
    w["key"], w["big"], w["sym"] = key, big, sym
    return w


def test_your_own_equal_target_practice_row_is_switched_off(room):
    """Main's keltner_30m_sl2tp2 on GPNSTOCK, armed by hand (not from v2)."""
    got = sw.consider(now=1_791_340_000)
    offs = [d for d in got["decisions"] if d["action"] == "off"]
    assert len(offs) == 1, got["decisions"]
    assert "YOUR practice rows" in offs[0]["why"]
    assert "TP 2% is not wider than SL 2%" in offs[0]["why"]
    s = room["settings"]
    assert s["strategy_coins"][room["key"]] == [], "switched off: empty list"
    assert s["strategy_coins"][room["big"]] == [room["sym"]], "TP 2.5 / SL 2 stays"


def test_a_row_holding_real_money_is_never_switched_off_for_its_target(room):
    room["settings"]["strategy_books"][room["key"]] = ["real", "paper"]
    got = sw.consider(now=1_791_340_000)
    assert not [d for d in got["decisions"] if d["action"] == "off"]
    assert room["settings"]["strategy_coins"][room["key"]] == [room["sym"]]
