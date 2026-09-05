"""The RESET W/L button zeroes every record — archived, never deleted.

Operator, 2026-09-05: *"CREATE A BUTTON TO RESET WIN RATE OF ALL"* — the hand
reset had cleared demo and left the live 0/3 (-5.36) on screen.
"""
import json

import pytest

from tradingagents import auto_trader as at


def _seed(tmp_path, monkeypatch, running=False):
    import time as _t

    now = _t.time()
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(at, "STATE_PATH", tmp_path / "state.json",
                        raising=False)
    monkeypatch.setattr(at, "runner_pid", lambda: 4242 if running else None)
    monkeypatch.setattr(at, "start_runner", lambda: 4243)
    rows = [
        {"action": "enter", "symbol": "PSXSTOCK_USDT", "dry_run": False},
        {"action": "exit", "symbol": "PSXSTOCK_USDT", "why": "SL",
         "pnl_est": -1.8, "dry_run": False, "ts": now},
        {"action": "enter", "symbol": "KITE_USDT", "dry_run": True},
        {"action": "exit", "symbol": "KITE_USDT", "why": "TP",
         "pnl_est": 0.98, "dry_run": True, "ts": now},
        {"action": "gate_blocked", "symbol": "GPNSTOCK_USDT",
         "why": "cost", "dry_run": False},
        {"action": "runner_start"},
    ]
    at.LEDGER_PATH.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return rows


def test_both_books_are_zeroed_and_the_history_is_archived(tmp_path,
                                                           monkeypatch):
    _seed(tmp_path, monkeypatch)
    got = at.reset_record(["paper", "real"])
    assert got["removed"] == 4, "the four trade rows"
    assert got["loss_cap_counter_reset"] is True
    assert at.strategy_stats(dry=True) == {}
    assert at.strategy_stats(dry=False) == {}
    assert at.pnl_today(dry=False)["total"] == 0.0, "the cap counter too"
    # archived, never deleted
    baks = list(tmp_path.glob("*.before-reset-*"))
    assert len(baks) == 1 and got["backup"] == baks[0].name
    assert '"pnl_est": -1.8' in baks[0].read_text(encoding="utf-8")
    # diagnostics stay: refusals and runner marks are not records
    left = at.LEDGER_PATH.read_text(encoding="utf-8")
    assert "gate_blocked" in left and "runner_start" in left
    assert "record_reset" in left, "the reset itself is written down"


def test_paper_only_leaves_the_real_record_alone(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    got = at.reset_record(["paper"])
    assert got["removed"] == 2
    assert got["loss_cap_counter_reset"] is False
    assert at.strategy_stats(dry=True) == {}
    assert at.pnl_today(dry=False)["total"] == -1.8, "real money still counted"


def test_a_runner_that_will_not_stop_means_no_reset(tmp_path, monkeypatch):
    """Rewriting the file while the runner can still append would race it and
    could lose a trade row — refuse, with words (harddev find)."""
    _seed(tmp_path, monkeypatch, running=True)
    monkeypatch.setattr(at.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(at.time, "sleep", lambda s: None)
    before = at.LEDGER_PATH.read_text(encoding="utf-8")
    with pytest.raises(RuntimeError, match="nothing was reset"):
        at.reset_record(["paper", "real"])
    assert at.LEDGER_PATH.read_text(encoding="utf-8") == before


def test_the_route_needs_confirm_and_maps_the_refusal():
    import inspect

    from tradingagents import api

    src = inspect.getsource(api.trade_record_reset)
    assert 'body.get("confirm") is not True' in src
    assert "HTTPException(409" in src, "a busy runner is a 409, not a crash"


def test_the_button_says_the_side_effects_before_anything_happens():
    p = open("webapp/src/components/trade/StrategiesGrid.tsx",
             encoding="utf-8").read()
    assert "RESET W/L" in p
    assert "window.confirm" in p, "irreversible-looking actions confirm first"
    assert "archived to a backup file, not deleted" in p
    assert "loss-cap counter resets too" in p
    assert "real positions are untouched" in p
