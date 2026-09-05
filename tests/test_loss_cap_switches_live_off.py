"""The account loss cap takes LIVE off and leaves DEMO running.

Operator, 2026-09-04: *"IF I LOSE 10 DOLLARS WILL IT STOP THE AUTO TRADE FOR
LIVE? ... DAY 1: I HAVE 115 AND MY ACCOUNT LOSS IS 15 MEANING IF IT BECAME 100
IT WILL STOP AUTO TRADE BUT DEMO TRADE SHOULD STILL WORK / YOU WILL NEED TO
SWITCH OFF THE LIVE TRADE HERE NO NEED TO STOP RUNNER"*.

Before this, hitting the cap wrote the KILL file and `break` — the runner
EXITED. `halted()` reads that file for BOTH books, so the demo stopped with
it, and getting the simulation back meant restarting the runner by hand. The
cap is a risk control for real money; it was switching off the rehearsal too.
"""
import inspect
import json

from tradingagents import auto_trader as at

A, B, C = "stoch14_1h_sl3tp3", "pivot_1h_sl3tp3", "cci20_4h_sl3tp3"


def _settings():
    return {
        "strategies": [A, B, C],
        "strategy_coins": {A: ["KITE_USDT"], B: ["NGAS_USDT"],
                           C: ["STBL_USDT"]},
        # A and B trade real money and paper; C is paper only
        "strategy_books": {A: ["real", "paper"], B: ["real"], C: ["paper"]},
        "strategy_margins": {A: 5.0, B: 5.0, C: 5.0},
        "enabled": True, "dry_run": True, "loss_limit": 15.0,
    }


def test_it_disarms_the_real_book_and_keeps_paper(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "SETTINGS_PATH", tmp_path / "auto_trade.json")
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    at.save_settings(_settings())

    got = at.disarm_live("account loss cap: -15.20 USDT against a cap of -15")

    assert got == sorted([A, B]), got
    now = at.load_settings()
    assert now["strategy_books"][A] == ["paper"], "paper survives"
    assert now["strategy_books"][B] == [], "a real-only row is left with nothing"
    assert now["strategy_books"][C] == ["paper"], "untouched"
    # the global switch too, or a row with no entry of its own falls back to it
    assert now["enabled"] is False
    assert now["dry_run"] is True, "the demo switch is not touched"
    # DEMO STILL RUNS
    assert at.active_modes(now) == [True]
    assert at.books_for(A, now) == [True]
    assert at.books_for(B, now) == []


def test_the_disarm_is_recorded_where_the_operator_looks(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "SETTINGS_PATH", tmp_path / "auto_trade.json")
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    at.save_settings(_settings())
    at.disarm_live("account loss cap: -15.20 USDT against a cap of -15.00")
    rows = [json.loads(x) for x in
            (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    said = [r for r in rows if r.get("action") == "live_disarmed"]
    assert said, rows
    assert sorted(said[0]["strategies"]) == sorted([A, B])
    assert "account loss cap" in said[0]["why"]


def test_a_second_pass_writes_nothing(tmp_path, monkeypatch):
    """The cap stays hit for the rest of the day — today's realized loss does
    not un-happen — so the loop must not rewrite the settings every cycle."""
    monkeypatch.setattr(at, "SETTINGS_PATH", tmp_path / "auto_trade.json")
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    at.save_settings(_settings())
    assert at.disarm_live("first") == sorted([A, B])
    assert at.disarm_live("second") == [], "nothing left on the real book"


def test_the_runner_does_not_exit_and_does_not_halt_the_demo():
    src = inspect.getsource(at.run_forever)
    i = src.index("loss_limit_hit()")
    # up to the sleep that follows the branch — the guard added on 2026-09-05
    # made the branch longer than a fixed window
    branch = src[i:src.index("slept = 0.0", i)]
    assert "disarm_live(" in branch
    assert "KILL_PATH" not in branch, (
        "the kill file gates BOTH books — it stopped the demo too")
    # the cap's own branch must not leave the loop. Comments quote the old
    # behaviour ("and `break` until 2026-09-04"), so read the CODE.
    body = branch.split(chr(10))     # branch already ends at the sleep
    code = chr(10).join(l for l in body if not l.strip().startswith('#'))
    assert 'break' not in code, code


def test_the_cap_still_reads_REAL_money_only(tmp_path, monkeypatch):
    """A demo drawdown must never switch live off."""
    monkeypatch.setattr(at, "SETTINGS_PATH", tmp_path / "auto_trade.json")
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    at.save_settings(_settings())
    import time

    now = time.time()
    for i in range(4):
        at.append_ledger({"action": "exit", "symbol": "KITE_USDT",
                          "strategy": A, "why": "SL", "pnl_est": -5.0,
                          "dry_run": True, "ts": now - i})
    assert at.loss_limit_hit() is False, "paper losses are not the account"
    at.append_ledger({"action": "exit", "symbol": "KITE_USDT", "strategy": A,
                      "why": "SL", "pnl_est": -15.5, "dry_run": False, "ts": now})
    assert at.loss_limit_hit() is True


def test_the_operators_own_numbers(tmp_path, monkeypatch):
    """"I HAVE 115 AND MY ACCOUNT LOSS IS 15 ... IF IT BECAME 100 IT WILL STOP"
    — the cap is on today's realized REAL loss, so -15 is the trigger."""
    monkeypatch.setattr(at, "SETTINGS_PATH", tmp_path / "auto_trade.json")
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    at.save_settings({**_settings(), "loss_limit": 15.0})
    import time

    now = time.time()
    at.append_ledger({"action": "exit", "symbol": "KITE_USDT", "strategy": A,
                      "why": "SL", "pnl_est": -14.99, "dry_run": False, "ts": now})
    assert at.loss_limit_hit() is False, "$14.99 down is not $15 down"
    at.append_ledger({"action": "exit", "symbol": "NGAS_USDT", "strategy": B,
                      "why": "SL", "pnl_est": -0.01, "dry_run": False, "ts": now})
    assert at.loss_limit_hit() is True
    assert at.disarm_live("cap") == sorted([A, B])
    assert at.active_modes() == [True], "demo keeps trading"
