"""The three small opens, fixed together (operator: "Fix this", 2026-09-05).

None of them had fired yet; each was one bad day away.
"""
import inspect
import json
import time

import pytest

from tradingagents import auto_trader as at


def test_a_failed_disarm_cannot_kill_the_loop():
    """NEVER HAPPENED YET: save_settings raising inside the cap branch would
    have crashed run_forever; the watchdog would restart it onto the same
    disk and it would die again — a crash loop."""
    src = inspect.getsource(at.run_forever)
    i = src.index("loss_limit_hit()")
    head = src[:i]
    assert head.rstrip().endswith("if"), "the cap check must sit inside a try"
    guarded = src[src.rindex("try:", 0, i):]
    assert "cap-disarm-failed" in guarded
    assert "LOSS CAP DISARM FAILED" in guarded
    assert '_say_once("cap-disarm-failed", 3600)' in guarded, \
        "said once an hour, not once a cycle"


def test_a_real_exit_uses_the_exchanges_own_number(monkeypatch, tmp_path):
    src = inspect.getsource(at._process_slot)
    i = src.index('pnl_source = "simulated" if pos_dry else "estimate"')
    frag = src[i:i + 1400]
    assert "fx.position_history(symbol, 10)" in frag
    assert 'pnl = float(match["realised"])' in frag
    assert 'pnl_source = "exchange"' in frag
    assert "except Exception" in frag, "the estimate stays as the fallback"
    # and the ledger row names the source
    assert '"pnl_source": pnl_source' in src


def test_the_enter_row_is_written_before_the_bracket():
    """2026-09-05, the ledger read backwards: forced_close 8:45 then enter
    8:45, because the bracket (and its failure handling) ran first."""
    src = inspect.getsource(at._process_slot)
    enter = src.index('"action": "enter"')
    bracket = src.index("_rest_bracket(symbol,", enter - 3000)
    assert enter < bracket, "the story must read: enter, then the bracket"
