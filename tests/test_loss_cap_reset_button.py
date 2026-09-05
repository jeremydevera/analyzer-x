"""RESET CAP: the breaker counts from zero; nothing is deleted.

Operator, 2026-09-05: *"IF I CLICK IT FORGET THE PREVIOUS LOSS, YOU WILL
ASSUME I HAVE 0 LOSS AGAIN"*.
"""
import time

from tradingagents import auto_trader as at

A = "squeeze_1h_sl3tp3"


def _seed(tmp_path, monkeypatch, pnl=-5.36):
    monkeypatch.setattr(at, "SETTINGS_PATH", tmp_path / "auto_trade.json")
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    at.save_settings({"strategies": [A], "loss_limit": 5.0,
                      "strategy_books": {A: ["real"]},
                      "strategy_coins": {A: ["KITE_USDT"]}})
    at.append_ledger({"action": "exit", "symbol": "KITE_USDT", "strategy": A,
                      "why": "SL", "pnl_est": pnl, "dry_run": False,
                      "ts": time.time()})


def test_the_click_forgives_the_loss_but_keeps_the_history(tmp_path,
                                                           monkeypatch):
    _seed(tmp_path, monkeypatch)
    assert at.loss_limit_hit() is True, "-5.36 against a $5 cap"
    got = at.reset_loss_cap()
    assert got["forgave"] == -5.36
    assert at.loss_cap_pnl() == 0.0, "the breaker counts from zero"
    assert at.loss_limit_hit() is False
    # NOTHING deleted: the history and the today figure still show the truth
    assert at.pnl_today(dry=False)["total"] == -5.36
    text = at.LEDGER_PATH.read_text(encoding="utf-8")
    assert '"pnl_est": -5.36' in text
    assert "loss_cap_reset" in text, "the click itself is written down"


def test_new_losses_count_from_zero_after_the_click(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    at.reset_loss_cap()
    at.append_ledger({"action": "exit", "symbol": "KITE_USDT", "strategy": A,
                      "why": "SL", "pnl_est": -4.99, "dry_run": False,
                      "ts": time.time()})
    assert at.loss_cap_pnl() == -4.99
    assert at.loss_limit_hit() is False, "$4.99 of new loss is under $5"
    at.append_ledger({"action": "exit", "symbol": "KITE_USDT", "strategy": A,
                      "why": "SL", "pnl_est": -0.01, "dry_run": False,
                      "ts": time.time()})
    assert at.loss_limit_hit() is True, "the NEW $5 trips it again"


def test_yesterdays_baseline_cannot_soften_todays_cap(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    s = at.load_settings()
    s["loss_cap_baseline"] = {"day": "2020-01-01", "total": -99.0}
    at.save_settings(s)
    assert at.loss_cap_pnl() == -5.36, "an old mark is ignored"
    assert at.loss_limit_hit() is True


def test_a_full_record_reset_clears_the_baseline_too(tmp_path, monkeypatch):
    """A baseline pointing at rows that no longer exist would start the
    counter at +5.36 — a head start on losing (harddev round 4)."""
    _seed(tmp_path, monkeypatch)
    at.reset_loss_cap()
    monkeypatch.setattr(at, "runner_pid", lambda: None)
    monkeypatch.setattr(at, "start_runner", lambda: 0)
    at.reset_record(["paper", "real"])
    assert not at.load_settings().get("loss_cap_baseline")
    assert at.loss_cap_pnl() == 0.0


def test_the_button_says_what_it_does_first():
    p = open("webapp/src/components/trade/StrategiesGrid.tsx",
             encoding="utf-8").read()
    assert "RESET CAP" in p and "window.confirm" in p
    assert "only the breaker forgets it" in p
    assert "Live stays off until you" in p
