"""Tests for the SPX futures bot: safety gates, sizing, signing, state."""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import spx_bot
from tradingagents.dataflows import mexc_futures as fx

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(spx_bot, "STATE_DIR", tmp_path)
    monkeypatch.setattr(spx_bot, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(spx_bot, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(spx_bot, "KILL_PATH", tmp_path / "KILL")
    monkeypatch.setattr(spx_bot, "PID_PATH", tmp_path / "bot.pid")
    monkeypatch.setattr(spx_bot, "LOG_PATH", tmp_path / "bot.log")
    monkeypatch.setattr(spx_bot, "HEARTBEAT_PATH", tmp_path / "heartbeat")
    monkeypatch.delenv("SPX_BOT_ARMED", raising=False)
    yield


# ---------------------------------------------------------------- gates
def test_dry_run_is_the_default():
    may, why = spx_bot.gates_open(live=False)
    assert may is False and "dry run" in why


def test_live_flag_alone_is_not_enough():
    may, why = spx_bot.gates_open(live=True)
    assert may is False and "SPX_BOT_ARMED" in why


def test_both_gates_open_permits_live(monkeypatch):
    monkeypatch.setenv("SPX_BOT_ARMED", "yes")
    may, why = spx_bot.gates_open(live=True)
    assert may is True and why == ""


def test_kill_file_overrides_everything(monkeypatch, tmp_path):
    monkeypatch.setenv("SPX_BOT_ARMED", "yes")
    (tmp_path / "KILL").write_text("stop")
    may, why = spx_bot.gates_open(live=True)
    assert may is False and "kill file" in why


# ---------------------------------------------------------------- breakers
def test_daily_loss_limit_blocks_trading():
    cfg = spx_bot.Config(daily_loss_limit_usd=25.0)
    state = {"day": spx_bot._today(), "realised_today": -25.5, "halted": False}
    ok, why = spx_bot.check_breakers(cfg, state)
    assert ok is False and "daily loss limit" in why


def test_loss_within_limit_still_trades():
    cfg = spx_bot.Config(daily_loss_limit_usd=25.0)
    state = {"day": spx_bot._today(), "realised_today": -10.0, "halted": False}
    assert spx_bot.check_breakers(cfg, state)[0] is True


def test_halted_state_blocks_trading():
    ok, why = spx_bot.check_breakers(spx_bot.Config(),
                                     {"halted": True, "halt_reason": "manual"})
    assert ok is False and "manual" in why


# ---------------------------------------------------------------- sizing
def test_contracts_round_down_never_overshoot():
    with patch.object(fx, "contract_spec", return_value={"contractSize": 0.0001}):
        # $346 notional at 7784 -> 0.7784 per contract -> 444.5 -> 444
        assert fx.contracts_for("SPX500_USDT", 346.0, 7784.0) == 444


def test_sizing_refuses_impossible_market():
    with patch.object(fx, "contract_spec", return_value={"contractSize": 0}):
        with pytest.raises(fx.MexcFuturesError):
            fx.contracts_for("SPX500_USDT", 100.0, 7784.0)


def test_notional_cap_is_respected(monkeypatch):
    """A large margin x leverage must still clamp to max_notional_usd."""
    cfg = spx_bot.Config(margin_usd=1000.0, leverage=5, max_notional_usd=400.0)
    captured = {}

    def fake_contracts(sym, notional, px):
        captured["notional"] = notional
        return 10

    monkeypatch.setattr(fx, "last_price", lambda s: 7784.0)
    monkeypatch.setattr(fx, "usdt_equity", lambda: 5000.0)
    monkeypatch.setattr(fx, "contracts_for", fake_contracts)
    monkeypatch.setattr(fx, "open_long", lambda *a, **k: {"dry_run": True})
    monkeypatch.setattr(fx, "limit_close_long", lambda *a, **k: {"dry_run": True})
    spx_bot.step(cfg, live=False)
    assert captured["notional"] == 400.0


# ---------------------------------------------------------------- signing
def test_signature_is_deterministic_and_key_prefixed():
    a = fx.sign("KEY", "SECRET", "1700000000000", params={"b": 2, "a": 1})
    b = fx.sign("KEY", "SECRET", "1700000000000", params={"a": 1, "b": 2})
    assert a == b, "param order must not change the signature"
    assert len(a) == 64 and all(c in "0123456789abcdef" for c in a)


def test_body_signing_uses_compact_sorted_json():
    s = fx._param_string(None, {"b": 1, "a": 2})
    assert s == '{"a":2,"b":1}'


def test_credentials_never_passed_as_arguments():
    import inspect
    for name in ("submit", "open_long", "close_long", "limit_close_long"):
        sig = inspect.signature(getattr(fx, name))
        assert not any(p in sig.parameters for p in ("key", "secret", "api_key"))


# ---------------------------------------------------------------- orders
def test_submit_refuses_zero_volume():
    with pytest.raises(fx.MexcFuturesError):
        fx.submit("SPX500_USDT", fx.SIDE_OPEN_LONG, 0, leverage=3, dry_run=True)


def test_dry_run_returns_payload_without_sending():
    r = fx.submit("SPX500_USDT", fx.SIDE_OPEN_LONG, 10, leverage=3, dry_run=True)
    assert r["dry_run"] is True
    assert r["request"]["vol"] == 10 and r["request"]["leverage"] == 3


def test_limit_close_requires_a_price():
    with pytest.raises(fx.MexcFuturesError):
        fx.submit("SPX500_USDT", fx.SIDE_CLOSE_LONG, 5, leverage=3,
                  order_type=fx.TYPE_LIMIT, price=None, dry_run=True)


# ---------------------------------------------------------------- state
def test_step_records_position_and_ledger(monkeypatch, tmp_path):
    cfg = spx_bot.Config(margin_usd=115.0, leverage=3)
    monkeypatch.setattr(fx, "last_price", lambda s: 7784.0)
    monkeypatch.setattr(fx, "usdt_equity", lambda: 200.0)
    monkeypatch.setattr(fx, "contracts_for", lambda *a: 444)
    monkeypatch.setattr(fx, "open_long", lambda *a, **k: {"dry_run": True})
    monkeypatch.setattr(fx, "limit_close_long", lambda *a, **k: {"dry_run": True})
    spx_bot.step(cfg, live=False)
    s = json.loads((tmp_path / "state.json").read_text())
    assert s["position"]["vol"] == 444
    assert s["position"]["tp"] == pytest.approx(7784.0 * 1.02, rel=1e-3)
    entries = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert entries[0]["action"] == "open" and entries[0]["dry_run"] is True


def test_stop_closes_and_books_the_loss(monkeypatch, tmp_path):
    cfg = spx_bot.Config(margin_usd=115.0, leverage=3, stop_loss_pct=10.0)
    spx_bot._write_state({"position": {"entry": 8000.0, "vol": 444,
                                       "notional": 345.0, "tp": 8160.0,
                                       "opened": spx_bot._today()},
                          "day": spx_bot._today(), "realised_today": 0.0,
                          "halted": False})
    monkeypatch.setattr(fx, "last_price", lambda s: 7000.0)   # -12.5%, past stop
    monkeypatch.setattr(fx, "usdt_equity", lambda: 200.0)
    closed = {}
    monkeypatch.setattr(fx, "close_long",
                        lambda *a, **k: closed.setdefault("hit", True) or {"dry_run": True})
    spx_bot.step(cfg, live=False)
    s = json.loads((tmp_path / "state.json").read_text())
    assert s["position"] is None
    assert s["realised_today"] < 0
    assert closed.get("hit") is True


def test_equity_floor_halts_the_bot(monkeypatch, tmp_path):
    cfg = spx_bot.Config(min_equity_usd=50.0)
    monkeypatch.setattr(fx, "last_price", lambda s: 7784.0)
    monkeypatch.setattr(fx, "usdt_equity", lambda: 10.0)
    spx_bot.step(cfg, live=False)
    s = json.loads((tmp_path / "state.json").read_text())
    assert s["halted"] is True and "below floor" in s["halt_reason"]


# ===================== loss-count breaker ===================================
# The operator asked for a plain counter: "I input 3, so after 3 losses the auto
# trade stops." Counts losing trades in TOTAL, not per day, and only a manual
# reset clears it — they chose that over a streak or a nightly reset.
def _state(**kw):
    base = {"position": None, "day": spx_bot._today(), "realised_today": 0.0,
            "losses": 0, "halted": False, "halt_reason": ""}
    base.update(kw)
    spx_bot._write_state(base)
    return base


def _held(entry=100.0, vol=10, notional=345.0, tp=102.0):
    return {"entry": entry, "vol": vol, "notional": notional, "tp": tp,
            "opened": spx_bot._today()}


def test_zero_losses_means_no_limit():
    cfg = spx_bot.Config(max_losses=0)
    st = {"day": spx_bot._today(), "realised_today": 0.0, "losses": 99}
    assert spx_bot.check_breakers(cfg, st)[0] is True


def test_breaker_trips_at_the_configured_count():
    cfg = spx_bot.Config(max_losses=3)
    st = {"day": spx_bot._today(), "realised_today": 0.0, "losses": 2}
    assert spx_bot.check_breakers(cfg, st)[0] is True, "2 of 3 may still trade"
    st["losses"] = 3
    ok, why = spx_bot.check_breakers(cfg, st)
    assert ok is False and "3 losing trades" in why
    st["losses"] = 7
    assert spx_bot.check_breakers(cfg, st)[0] is False


def test_the_count_survives_the_daily_rollover(monkeypatch):
    """'Total, ever' was the choice, so the rollover that clears
    realised_today must not clear this counter."""
    cfg = spx_bot.Config(max_losses=2)
    _state(day="1999-01-01", realised_today=-50.0, losses=2)
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 100.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    opened = []
    monkeypatch.setattr(spx_bot.fx, "open_long",
                        lambda *a, **k: opened.append(a) or {})
    spx_bot.step(cfg, live=False)
    st = spx_bot._read_state()
    assert st["day"] == spx_bot._today()
    assert st["realised_today"] == 0.0, "the daily figure does reset"
    assert st["losses"] == 2, "the loss count must NOT reset"
    assert opened == []


def test_a_stop_increments_the_count(monkeypatch):
    cfg = spx_bot.Config(max_losses=3, stop_loss_pct=10.0)
    _state(position=_held())
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 88.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "close_long", lambda *a, **k: {})
    spx_bot.step(cfg, live=False)
    st = spx_bot._read_state()
    assert st["position"] is None
    assert st["losses"] == 1
    assert st["realised_today"] < 0


def test_a_tripped_breaker_still_manages_an_open_position(monkeypatch):
    """The breaker blocks OPENING. Returning early while holding would stop the
    stop-loss being watched at exactly the moment the account is in trouble."""
    cfg = spx_bot.Config(max_losses=1, stop_loss_pct=10.0)
    _state(position=_held(), losses=5)
    closed = []
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 88.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "close_long",
                        lambda *a, **k: closed.append(a) or {})
    spx_bot.step(cfg, live=False)
    assert len(closed) == 1, "the exit must still run"
    assert spx_bot._read_state()["position"] is None


def test_a_tripped_breaker_refuses_to_open(monkeypatch):
    cfg = spx_bot.Config(max_losses=1)
    _state(losses=1)
    opened = []
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 100.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "open_long",
                        lambda *a, **k: opened.append(a) or {})
    spx_bot.step(cfg, live=False)
    assert opened == []


def test_reset_is_the_only_thing_that_clears_it():
    _state(losses=4, halted=True,
           halt_reason="loss limit reached: 4 losing trades")
    assert spx_bot.do_reset_losses(spx_bot.Config()) == 0
    st = spx_bot._read_state()
    assert st["losses"] == 0
    assert st["halted"] is False, "the matching halt is lifted too"


def test_reset_does_not_lift_an_unrelated_halt():
    _state(losses=2, halted=True, halt_reason="equity 5.00 below floor 20.0")
    spx_bot.do_reset_losses(spx_bot.Config())
    st = spx_bot._read_state()
    assert st["losses"] == 0
    assert st["halted"] is True, "an equity halt is not a loss-count halt"


def test_max_losses_round_trips_through_the_saved_config():
    spx_bot.Config(max_losses=3).save()
    assert spx_bot.Config.load().max_losses == 3


# ============ reconciliation: believe the exchange, not the state file ======
# The take-profit rests on MEXC and fires without telling anyone. Before this,
# the bot kept its own notes, so after the very first take-profit filled it still
# believed it was long — forever. 1 trade instead of the backtest's 15.
def test_a_filled_take_profit_is_noticed_and_booked(monkeypatch):
    cfg = spx_bot.Config(max_losses=3)
    _state(position=dict(_held(entry=100.0, notional=345.0),
                         position_id=777, protected=True))
    monkeypatch.setenv("SPX_BOT_ARMED", "yes")
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 102.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "open_positions", lambda s=None: [])
    monkeypatch.setattr(spx_bot.fx, "list_position_stops", lambda symbol=None: [
        {"positionId": "777", "isFinished": 1, "errorCode": 0,
         "takeProfitPrice": 102.0, "updateTime": 2},
    ])
    spx_bot.step(cfg, live=True)
    st = spx_bot._read_state()
    assert st["position"] is None, "the bot must notice it is flat"
    assert st["realised_today"] > 0, "the win must be booked"
    assert st["losses"] == 0, "a take-profit is not a loss"
    entries = [json.loads(l) for l in
               spx_bot.LEDGER_PATH.read_text().splitlines()]
    assert entries[-1]["action"] == "closed_by_exchange"
    assert entries[-1]["reason"] == "take-profit"


def test_an_exchange_stop_is_booked_as_a_loss(monkeypatch):
    cfg = spx_bot.Config(max_losses=3)
    _state(position=dict(_held(entry=100.0, notional=345.0),
                         position_id=778, protected=True))
    monkeypatch.setenv("SPX_BOT_ARMED", "yes")
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 90.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "open_positions", lambda s=None: [])
    monkeypatch.setattr(spx_bot.fx, "list_position_stops", lambda symbol=None: [
        {"positionId": "778", "isFinished": 1, "errorCode": 0,
         "stopLossPrice": 90.0, "updateTime": 2},
    ])
    spx_bot.step(cfg, live=True)
    st = spx_bot._read_state()
    assert st["position"] is None
    assert st["realised_today"] < 0
    assert st["losses"] == 1, "an exchange stop counts toward the loss limit"


def test_a_failed_read_never_books_a_phantom_close(monkeypatch):
    """Assuming 'closed' from an unreachable exchange would book a fake profit
    and then re-enter on top of a position that is still open."""
    cfg = spx_bot.Config()
    _state(position=dict(_held(), position_id=779, protected=True))
    monkeypatch.setenv("SPX_BOT_ARMED", "yes")
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 101.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)

    def unreachable(symbol=None):
        raise spx_bot.fx.MexcFuturesError("transport failure")

    monkeypatch.setattr(spx_bot.fx, "open_positions", unreachable)
    opened = []
    monkeypatch.setattr(spx_bot.fx, "open_long",
                        lambda *a, **k: opened.append(a) or {})
    spx_bot.step(cfg, live=True)
    st = spx_bot._read_state()
    assert st["position"] is not None, "the position must be kept on the books"
    assert st["realised_today"] == 0.0, "nothing may be booked"
    assert opened == [], "and nothing may be opened on top of it"


def test_the_exchange_wins_on_size_drift(monkeypatch):
    cfg = spx_bot.Config()
    _state(position=dict(_held(vol=10), position_id=780, protected=True))
    monkeypatch.setenv("SPX_BOT_ARMED", "yes")
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 101.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "open_positions", lambda s=None: [
        {"positionId": 780, "holdVol": 7}])
    spx_bot.step(cfg, live=True)
    assert spx_bot._read_state()["position"]["vol"] == 7


def test_a_dry_run_book_is_not_corrected_by_live_data(monkeypatch):
    """A simulated position has no exchange counterpart; reconciling it against
    the real account would delete it every cycle."""
    cfg = spx_bot.Config()
    _state(position=dict(_held(), position_id=None, protected=False))
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 101.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "open_positions", lambda s=None: [])
    monkeypatch.setattr(spx_bot.fx, "place_position_stop",
                        lambda *a, **k: {"dry_run": True, "request": {}})
    spx_bot.step(cfg, live=False)
    assert spx_bot._read_state()["position"] is not None


def test_after_the_exchange_closes_it_the_next_cycle_re_enters(monkeypatch):
    """The whole point: 1 trade becomes 15."""
    cfg = spx_bot.Config(max_losses=0)
    _state(position=dict(_held(entry=100.0), position_id=781, protected=True))
    monkeypatch.setenv("SPX_BOT_ARMED", "yes")
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 102.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "open_positions", lambda s=None: [])
    monkeypatch.setattr(spx_bot.fx, "list_position_stops", lambda symbol=None: [
        {"positionId": "781", "isFinished": 1, "errorCode": 0,
         "takeProfitPrice": 102.0, "updateTime": 2}])
    spx_bot.step(cfg, live=True)                    # cycle 1: books the win
    assert spx_bot._read_state()["position"] is None

    opened = []
    monkeypatch.setattr(spx_bot.fx, "contracts_for", lambda *a, **k: 5)
    monkeypatch.setattr(spx_bot.fx, "open_long",
                        lambda *a, **k: opened.append(a) or {})
    monkeypatch.setattr(spx_bot, "_attach_bracket",
                        lambda *a, **k: {"protected": True, "tp": 104.0,
                                         "sl": 91.8, "position_id": 782})
    spx_bot.step(cfg, live=True)                    # cycle 2: enters again
    assert len(opened) == 1, "the bot must open the next trade"
    assert spx_bot._read_state()["position"]["protected"] is True


# ============ strategy wiring: the picker must not lie ======================
# Before this the bot never read cfg.strategy at all, so selecting "Trend filter"
# in the UI silently ran barrier_harvest instead.
def test_only_bracket_strategies_are_runnable():
    assert spx_bot.strategy_is_runnable("barrier_harvest")[0] is True
    assert spx_bot.strategy_is_runnable("buy_hold")[0] is True
    for k in ("trend_filter", "session_long", "ladder_dca", "vol_target"):
        ok, why = spx_bot.strategy_is_runnable(k)
        assert ok is False, f"{k} has no execution engine and must be refused"
        assert "rebalancing engine" in why


def test_the_runner_refuses_to_start_an_unrunnable_strategy(monkeypatch):
    """Refusing beats silently running something else: the operator would
    believe they were trading a strategy they were not."""
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 100.0)
    rc = spx_bot.do_run(spx_bot.Config(strategy="vol_target"),
                        live=False, once=True)
    assert rc == 2, "must exit non-zero rather than trade something else"


def test_every_registered_strategy_is_classified():
    """A new strategy must not default to runnable by omission."""
    from tradingagents import strategies as sg
    for key in sg.ORDER:
        assert isinstance(spx_bot.strategy_is_runnable(key)[0], bool)


def test_buy_hold_places_a_stop_but_no_target(monkeypatch):
    calls = {}
    monkeypatch.setattr(spx_bot.fx, "place_position_stop",
                        lambda *a, **k: calls.update(stop=k) or
                        {"dry_run": True, "request": {}})
    monkeypatch.setattr(spx_bot.fx, "limit_close_long",
                        lambda *a, **k: calls.setdefault("target", k))
    br = spx_bot._attach_bracket(spx_bot.Config(strategy="buy_hold"), 5, 100.0,
                                 dry=True)
    assert br["tp"] is None, "hold means never take profit"
    assert br["sl"] > 0, "but it still needs a stop"
    assert "target" not in calls, "and no resting target order"


def test_barrier_harvest_asks_for_both_barriers(monkeypatch):
    br = spx_bot._attach_bracket(spx_bot.Config(strategy="barrier_harvest"),
                                 5, 100.0, dry=True)
    assert br["sl"] == pytest.approx(90.0)
    assert br["tp"] == pytest.approx(102.0)


def test_strategy_round_trips_through_the_saved_config():
    spx_bot.Config(strategy="buy_hold").save()
    assert spx_bot.Config.load().strategy == "buy_hold"


# ============ supervision ==================================================
def test_a_stale_pid_file_does_not_read_as_running():
    """After a crash the pid file survives. Trusting it would report a dead bot
    as healthy, which is the opposite of what supervision is for."""
    spx_bot.PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    spx_bot.PID_PATH.write_text("999999")        # a pid that cannot be alive
    assert spx_bot.running_pid() is None
    spx_bot.PID_PATH.write_text(str(os.getpid()))
    assert spx_bot.running_pid() == os.getpid()
    spx_bot.PID_PATH.write_text("not-a-number")
    assert spx_bot.running_pid() is None


def test_health_flags_an_orphaned_position():
    _state(position=_held())
    spx_bot.PID_PATH.unlink(missing_ok=True)
    h = spx_bot.health()
    assert h["running"] is False
    assert h["position_open"] is True
    assert h["orphaned"] is True, \
        "a dead runner holding a position is the case that must be shouted about"


def test_health_is_not_orphaned_when_flat():
    _state(position=None)
    spx_bot.PID_PATH.unlink(missing_ok=True)
    assert spx_bot.health()["orphaned"] is False


def test_a_second_runner_refuses_to_start(monkeypatch):
    """Two runners would both trade the same merged MEXC position."""
    spx_bot.PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(spx_bot, "running_pid", lambda: os.getpid() + 1)
    rc = spx_bot.do_run(spx_bot.Config(), live=False, once=True)
    assert rc == 3


def test_a_completed_cycle_leaves_a_heartbeat(monkeypatch):
    _state()
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 100.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "contracts_for", lambda *a, **k: 5)
    monkeypatch.setattr(spx_bot.fx, "open_long", lambda *a, **k: {})
    monkeypatch.setattr(spx_bot, "_attach_bracket",
                        lambda *a, **k: {"protected": False, "tp": 102.0,
                                         "sl": 90.0, "position_id": None})
    assert spx_bot.do_run(spx_bot.Config(), live=False, once=True) == 0
    assert spx_bot.HEARTBEAT_PATH.exists()
    assert spx_bot.health()["stale"] is False


# ============ clock skew ====================================================
# Signed requests are validated against a receive window. A slept-through or
# drifted clock gets every request rejected, and MEXC reports that as an auth
# failure — indistinguishable from a wrong secret unless it is measured.
def test_the_runner_refuses_to_start_on_a_skewed_clock(monkeypatch):
    monkeypatch.setattr(spx_bot.fx, "clock_skew_ms", lambda: 45_000)
    assert spx_bot.do_run(spx_bot.Config(), live=False, once=True) == 4


def test_a_small_skew_is_fine(monkeypatch):
    _state()
    monkeypatch.setattr(spx_bot.fx, "clock_skew_ms", lambda: -172)
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 100.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "contracts_for", lambda *a, **k: 5)
    monkeypatch.setattr(spx_bot.fx, "open_long", lambda *a, **k: {})
    monkeypatch.setattr(spx_bot, "_attach_bracket",
                        lambda *a, **k: {"protected": True, "tp": 102.0,
                                         "sl": 90.0, "position_id": 1})
    assert spx_bot.do_run(spx_bot.Config(), live=False, once=True) == 0


def test_an_unreachable_clock_does_not_block_startup(monkeypatch):
    """A failed check is not evidence of a bad clock."""
    _state()

    def boom():
        raise spx_bot.fx.MexcFuturesError("transport failure")

    monkeypatch.setattr(spx_bot.fx, "clock_skew_ms", boom)
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 100.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "contracts_for", lambda *a, **k: 5)
    monkeypatch.setattr(spx_bot.fx, "open_long", lambda *a, **k: {})
    monkeypatch.setattr(spx_bot, "_attach_bracket",
                        lambda *a, **k: {"protected": True, "tp": 102.0,
                                         "sl": 90.0, "position_id": 1})
    assert spx_bot.do_run(spx_bot.Config(), live=False, once=True) == 0


# ============ crash resilience ==============================================
def test_a_transient_fault_retries_instead_of_abandoning_the_position(monkeypatch):
    """Exiting on the first fault left a live position with nothing retrying the
    barriers, noticing fills, or enforcing the breakers."""
    _state(position=_held())
    monkeypatch.setattr(spx_bot.fx, "clock_skew_ms", lambda: 0)
    monkeypatch.setattr(spx_bot, "MAX_CONSECUTIVE_FAULTS", 3)
    monkeypatch.setattr(spx_bot.time, "sleep", lambda s: None)
    calls = []

    def flaky(cfg, live):
        calls.append(1)
        raise RuntimeError("boom")

    monkeypatch.setattr(spx_bot, "step", flaky)
    rc = spx_bot.do_run(spx_bot.Config(), live=False, once=False)
    assert rc == 1
    assert len(calls) == 3, "it must retry up to the limit, not exit at once"


def test_the_fault_counter_resets_after_a_good_cycle(monkeypatch):
    _state()
    monkeypatch.setattr(spx_bot.fx, "clock_skew_ms", lambda: 0)
    monkeypatch.setattr(spx_bot, "MAX_CONSECUTIVE_FAULTS", 2)
    monkeypatch.setattr(spx_bot.time, "sleep", lambda s: None)
    seq = iter([RuntimeError("a"), None, RuntimeError("b"), None,
                RuntimeError("c"), RuntimeError("d")])
    n = []

    def flaky(cfg, live):
        n.append(1)
        nxt = next(seq)
        if nxt:
            raise nxt

    monkeypatch.setattr(spx_bot, "step", flaky)
    assert spx_bot.do_run(spx_bot.Config(), live=False, once=False) == 1
    # one fault, reset, one fault, reset, then two in a row ends it
    assert len(n) == 6, f"good cycles must clear the counter, got {len(n)}"
