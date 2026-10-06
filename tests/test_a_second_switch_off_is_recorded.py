"""A strategy switched off a SECOND time is written to the deployment record.

RCA-2026-10-05-H: #ES68FMKK DVNSTOCK 15m ibs was switched off in #CC94D9FB at
Oct 01, 2026 12:51pm (recorded), on again at Oct 02, 2026 12:12am (recorded),
and off again at 12:56am — and that last line was never written: the
duplicate check compared the new line with the OLDEST same-strategy line among
the newest 200, which was the Oct 01 switch-off, word for word the same. The
room's replay then kept the strategy on for three days (84 trades the room
never made); 43 of #CC94D9FB's 497 watcher switch-offs were missing.
"""
from __future__ import annotations

from tradingagents import local_history as lh

SLOT = ("ibs_15m_sl03tp04", "DVNSTOCK_USDT")


def _row(action, t, key=SLOT[0], sym=SLOT[1]):
    return {"changed_at": t, "strategy_key": key, "symbol": sym, "action": action,
            "books": "paper" if action == "deployed" else None}


def test_a_second_switch_off_is_written():
    t = 1_790_800_000
    assert lh.record_deployment(_row("deployed", t)) == 1
    assert lh.record_deployment(_row("disarmed", t + 60)) == 1
    for k in range(150):                       # the room's other strategies
        lh.record_deployment(_row("deployed", t + 100 + k, key=f"k{k}_15m", sym="X_USDT"))
    assert lh.record_deployment(_row("deployed", t + 1000)) == 1
    assert lh.record_deployment(_row("disarmed", t + 1100)) == 1, \
        "the second switch-off is history, not a copy of the first"
    mine = [d["action"] for d in reversed(lh.deployments(limit=1000))
            if d["strategy_key"] == SLOT[0]]
    assert mine == ["deployed", "disarmed", "deployed", "disarmed"]


def test_the_same_save_twice_in_a_row_is_still_one_line():
    t = 1_790_800_000
    assert lh.record_deployment(_row("deployed", t)) == 1
    assert lh.record_deployment(_row("deployed", t + 5)) == 0
