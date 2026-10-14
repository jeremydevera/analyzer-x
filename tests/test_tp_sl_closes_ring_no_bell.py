"""A trade that closes at its target or its stop makes no notification.

The operator, Oct 14, 2026: *"i dont need notification if there is tp /sl
trades remove those and future notification"*. The bell held 22,583 events,
10,313 of them trade closes: 5,493 at the stop and 4,808 at the target, one
per practice trade, burying everything else. A close for any OTHER reason
still rings — the 9 MANUAL/EXCHANGE closes (a position the exchange or a hand
closed) and the 3 CLOSED ones are exactly the closes worth a look. The trade
record (the ledger's `exit` row) is untouched: only the bell goes quiet.

Driven end to end through `run_cycle`, the runner's own entry point, the way
tests/test_a_switched_off_practice_trade_is_finished.py books a target.
"""
from __future__ import annotations

import json
import time

import pandas as pd
import pytest

from tests.test_auto_trader import FakeFx
from tradingagents import auto_trader as at, notifications as nt

HELD, KEY = "PDDSTOCK_USDT", "eqraid_1h_sl25tp25"
ARMED, ARMED_KEY = "GPNSTOCK_USDT", "keltner_30m_sl2tp2"
ENTRY = 79.18


@pytest.fixture(autouse=True)
def _fresh_bars():
    at._BAR_CACHE.clear()
    yield
    at._BAR_CACHE.clear()


def _hours(last_high, last_low):
    top = int(time.time()) // 3600 * 3600 - 3600       # last bar has closed
    opens = [top - (59 - i) * 3600 for i in range(60)]
    return pd.DataFrame({"Date": pd.to_datetime(opens, unit="s"),
                         "Open": [ENTRY] * 60,
                         "High": [ENTRY + 0.3] * 59 + [last_high],
                         "Low": [ENTRY - 0.3] * 59 + [last_low],
                         "Close": [ENTRY] * 60, "Volume": [1.0] * 60}), opens


def _close_through_the_runner(df, opens):
    slot = at.state_key(HELD, True, KEY)
    at._write_json(at.SETTINGS_PATH, {
        "strategies": [ARMED_KEY], "strategy_coins": {ARMED_KEY: [ARMED]},
        "strategy_books": {ARMED_KEY: ["paper"]}, "margin": 5.0,
        "enabled": False, "dry_run": True})
    at._write_json(at.STATE_PATH, {slot: {"step": 0, "last_ts": {}, "position": {
        "side": 1, "vol": 5, "entry": ENTRY, "tp": ENTRY * 1.025,
        "sl": ENTRY * 0.975, "margin": 5.0, "strategy": KEY,
        "entry_ts": opens[-3] - 3600, "opened_at": opens[-3],
        "trade_id": "PDDTEST1", "dry": True, "bracket": True, "step": 0}}})
    at.run_cycle(fx=FakeFx(df))
    rows = ([json.loads(x) for x in at.LEDGER_PATH.read_text().splitlines()]
            if at.LEDGER_PATH.exists() else [])
    return [r for r in rows if r.get("action") == "exit" and r.get("symbol") == HELD]


@pytest.mark.parametrize("why,high,low", [
    ("TP", ENTRY * 1.03, ENTRY - 0.3),            # the target is crossed
    ("SL", ENTRY + 0.3, ENTRY * 0.97),            # the stop is crossed
])
def test_a_target_or_stop_close_rings_no_bell(why, high, low):
    exits = _close_through_the_runner(*_hours(high, low))
    assert exits and exits[-1]["why"] == why, "the trade record still books it"
    assert nt.recent(50, kind="trade_close") == []


@pytest.mark.parametrize("why,rings", [
    ("TP", False), ("SL", False),
    ("MANUAL/EXCHANGE", True), ("CLOSED", True),
])
def test_only_target_and_stop_closes_are_quiet(why, rings):
    assert at.close_rings_the_bell(why) is rings
