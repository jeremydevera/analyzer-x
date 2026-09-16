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


def test_there_is_one_reset_button_per_book():
    """Operator, `Sep 17, 2026`: *"i want option to reset w/l for deom and
    live"*. One button wiped both records together; the demo record is a
    measurement you may want to start again, the live record is what really
    happened to your money."""
    p = open("webapp/src/components/trade/StrategiesGrid.tsx",
             encoding="utf-8").read()
    assert 'RESET {word} W/L' in p
    assert '[["paper", "DEMO"], ["real", "LIVE"]]' in p
    assert "recordReset([book])" in p, "one book per press, never both"
    assert "RESET W/L<" not in p, "the old both-books button is still there"


def test_each_button_says_ITS_OWN_side_effects_before_anything_happens():
    """The two confirms must DIFFER, because the side effects do: only a demo
    reset clears open demo positions, and only a live reset moves today's
    loss-cap counter. One shared wording would be false on one of the two
    buttons (label-must-match-data)."""
    p = open("webapp/src/components/trade/StrategiesGrid.tsx",
             encoding="utf-8").read()
    assert "window.confirm" in p, "irreversible-looking actions confirm first"
    assert "archived to a backup file, not deleted" in p, "true of both"
    # the DEMO half
    assert "open demo positions are cleared" in p
    assert "LIVE record and open real positions are untouched" in p
    # the LIVE half
    assert "loss-cap counter resets too" in p
    assert "real positions are untouched" in p
    assert "DEMO record is untouched" in p
    # and the branch that keeps them apart
    assert 'book === "paper"' in p, (
        "both buttons share one wording again — the confirm has to branch on "
        "which book is being reset")


def test_a_live_reset_leaves_the_demo_record_alone(tmp_path, monkeypatch):
    """The other direction of `test_paper_only_leaves_the_real_record_alone`,
    which is the half the new LIVE button uses."""
    _seed(tmp_path, monkeypatch)
    got = at.reset_record(["real"])
    left = [json.loads(x) for x in
            at.LEDGER_PATH.read_text(encoding="utf-8").splitlines() if x]
    trades = [r for r in left if r.get("action") in ("enter", "exit")]
    assert trades, "the demo trades were removed by a LIVE reset"
    assert all(r.get("dry_run") for r in trades),         "a real trade row survived a real reset"
    assert got["removed"] > 0
