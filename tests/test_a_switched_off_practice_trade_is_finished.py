"""A switched-off practice trade is finished, not erased (RCA-2026-09-24-J).

The operator's Sep 24, 2026 7:45pm replace deploy switched off every old row.
Two of them held open practice trades — PDDSTOCK eqraid 1h, long at 79.18
since 1:00pm, and CTC killzone 4h, short at 0.10908 since 12:00am — and the
runner's first cycle ERASED both: `reconcile_unconfigured` set the position
to None with a log line and no ledger row, because the cycle only kept
visiting coins that held REAL money. The practice record was left with two
entries and no exits.

Now the practice pass visits every coin a paper slot still holds, the
slot's own strategy books the exit (exits only), and the only practice
position ever cleared is one whose strategy no longer exists — in writing.
"""
from __future__ import annotations

import inspect
import json
import time

import pandas as pd
import pytest

from tests.test_auto_trader import FakeFx
from tradingagents import auto_trader as at

HELD, KEY = "PDDSTOCK_USDT", "eqraid_1h_sl25tp25"      # the erased trade
ARMED, ARMED_KEY = "GPNSTOCK_USDT", "keltner_30m_sl2tp2"
ENTRY = 79.18


def _hours(last_high):
    top = int(time.time()) // 3600 * 3600 - 3600       # last bar has closed
    opens = [top - (59 - i) * 3600 for i in range(60)]
    highs = [ENTRY + 0.3] * 59 + [last_high]
    return pd.DataFrame({"Date": pd.to_datetime(opens, unit="s"),
                         "Open": [ENTRY] * 60, "High": highs,
                         "Low": [ENTRY - 0.3] * 60, "Close": [ENTRY] * 60,
                         "Volume": [1.0] * 60}), opens


def _position(opened_at, strategy=KEY):
    return {"side": 1, "vol": 5, "entry": ENTRY, "tp": ENTRY * 1.025,
            "sl": ENTRY * 0.975, "margin": 5.0, "strategy": strategy,
            "entry_ts": opened_at - 3600, "opened_at": opened_at,
            "trade_id": "PDDTEST1", "dry": True, "bracket": True, "step": 0}


def _settings():
    return {"strategies": [ARMED_KEY], "strategy_coins": {ARMED_KEY: [ARMED]},
            "strategy_books": {ARMED_KEY: ["paper"]}, "margin": 5.0,
            "enabled": False, "dry_run": True}


def _ledger():
    return ([json.loads(x) for x in at.LEDGER_PATH.read_text().splitlines()]
            if at.LEDGER_PATH.exists() else [])


def test_the_cleanup_keeps_a_switched_off_practice_trade():
    slot = at.state_key(HELD, True, KEY)
    state = {slot: {"step": 0, "last_ts": {}, "position": _position(1)}}
    at.reconcile_unconfigured(_settings(), state, fx=FakeFx(_hours(80)[0]))
    assert state[slot]["position"], "an open practice trade was erased"
    assert not any(r.get("action") == "paper_cleared" for r in _ledger())


def test_only_a_trade_whose_strategy_is_gone_is_cleared_and_it_is_written_down():
    slot = at.state_key(HELD, True, "no_such_strategy_1h")
    state = {slot: {"step": 0, "last_ts": {},
                    "position": _position(1, "no_such_strategy_1h")}}
    at.reconcile_unconfigured(_settings(), state, fx=FakeFx(_hours(80)[0]))
    assert state[slot]["position"] is None
    row = [r for r in _ledger() if r.get("action") == "paper_cleared"][-1]
    assert row["symbol"] == HELD and row["trade_id"] == "PDDTEST1"


def test_the_cycle_books_the_exit_of_a_practice_trade_on_a_switched_off_coin():
    """End to end through `run_cycle` and the real `process_symbol`: the
    coin is armed by nothing, and its target is crossed."""
    df, opens = _hours(ENTRY * 1.03)                   # the target is hit
    slot = at.state_key(HELD, True, KEY)
    at._write_json(at.SETTINGS_PATH, _settings())
    at._write_json(at.STATE_PATH, {slot: {"step": 0, "last_ts": {},
                                          "position": _position(opens[-3])}})
    at.run_cycle(fx=FakeFx(df))
    assert at.load_state()[slot]["position"] is None
    exits = [r for r in _ledger() if r.get("action") == "exit"
             and r.get("symbol") == HELD]
    assert exits and exits[-1]["why"] == "TP" and exits[-1]["strategy"] == KEY
    assert not any(r.get("action") == "enter" and r.get("symbol") == HELD
                   for r in _ledger()), "exits only — nothing new on that coin"


def test_the_live_pass_never_visits_a_coin_only_the_practice_book_holds():
    src = inspect.getsource(at.run_cycle)
    assert "for symbol in (symbols + paper_held if dry else symbols):" in src
    assert "if True not in modes and paper_held:" in src
