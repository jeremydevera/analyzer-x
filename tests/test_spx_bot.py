"""Tests for the SPX futures bot: safety gates, sizing, signing, state."""
import json
import os
from datetime import datetime, timedelta, timezone
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
    monkeypatch.setattr(spx_bot, "ALERT_PATH", tmp_path / "alerts.jsonl")
    # Offline by default. Without these, _snap() reached contract_spec and
    # do_run() reached clock_skew_ms over the real network: 21 tests in this
    # suite were making live HTTP calls and passing only because the code
    # swallows the failure and falls back — i.e. passing for the wrong reason,
    # flaky whenever MEXC is unreachable, and hammering the exchange on every
    # run. A test that wants a different clock or tick still monkeypatches it.
    monkeypatch.setattr(spx_bot.fx, "contract_spec",
                        lambda symbol: {"priceUnit": 0.1,
                                        "contractSize": 0.0001,
                                        "maxLeverage": 200})
    monkeypatch.setattr(spx_bot.fx, "clock_skew_ms", lambda: 0)
    # pick_lane() asks every lane for its own bars, which is a live fetch.
    monkeypatch.setattr(spx_bot.fx, "klines",
                        lambda symbol, interval="Min5", limit=400: _bars())
    # _reconcile() sweeps leftover resting orders when the exchange closes a
    # position, which is two more live calls.
    monkeypatch.setattr(spx_bot.fx, "open_orders", lambda symbol=None: [])
    monkeypatch.setattr(spx_bot.fx, "cancel_all_orders", lambda symbol: {})
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


def test_an_exposure_strategy_now_starts_as_an_entry_gate(monkeypatch):
    """This used to be refused, and the refusal was right at the time.

    As an EXPOSURE target vol_target rebalances every bar, which measured 148
    orders a day on 1-minute data. As an ENTRY GATE its signal only decides
    whether to open one bracketed trade, so turnover is bounded by the barriers
    and the objection disappears. The backtested figures for the exposure form do
    not transfer, which is why the UI labels these as gates.
    """
    _state()
    monkeypatch.setattr(spx_bot.fx, "clock_skew_ms", lambda: 0)
    monkeypatch.setattr(spx_bot, "step", lambda cfg, live: None)
    rc = spx_bot.do_run(spx_bot.Config(strategy="vol_target",
                                      timeframe="Min1"), live=False, once=True)
    assert rc == 0



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


# ============ alerts and the watchdog =======================================
# A bot that halts silently at 3am is discovered at 9am.
def test_an_alert_is_recorded_and_readable(monkeypatch):
    monkeypatch.setattr(spx_bot.sys, "platform", "linux")   # skip osascript
    spx_bot.alert("halted", "equity below the floor")
    got = spx_bot.recent_alerts()
    assert got[0]["kind"] == "halted"
    assert "equity" in got[0]["message"]
    assert got[0]["at"].endswith("+00:00")


def test_alerting_never_breaks_trading(monkeypatch):
    """A notification failure must not propagate — the bot holds a position."""
    monkeypatch.setattr(spx_bot, "ALERT_PATH",
                        spx_bot.STATE_DIR / "nope" / "x" / "alerts.jsonl")
    monkeypatch.setattr(spx_bot.sys, "platform", "darwin")
    spx_bot.alert("halted", "unwritable path and a bogus notifier")  # must not raise


def test_the_equity_floor_raises_an_alert(monkeypatch):
    _state()
    fired = []
    monkeypatch.setattr(spx_bot, "alert", lambda k, m: fired.append((k, m)))
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 100.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 1.0)
    spx_bot.step(spx_bot.Config(min_equity_usd=20.0), live=False)
    assert fired and fired[0][0] == "halted"


def test_the_loss_limit_raises_an_alert(monkeypatch):
    _state(position=_held(entry=100.0, notional=345.0))
    fired = []
    monkeypatch.setattr(spx_bot, "alert", lambda k, m: fired.append((k, m)))
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 88.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "close_long", lambda *a, **k: {})
    spx_bot.step(spx_bot.Config(max_losses=1, stop_loss_pct=10.0), live=False)
    assert any(k == "loss-limit" for k, _ in fired)


def test_the_watchdog_restarts_a_crash_but_not_a_misconfiguration(monkeypatch):
    """Restarting on a bad clock or an unrunnable strategy would spin forever."""
    monkeypatch.setattr(spx_bot.time, "sleep", lambda s: None)
    fired = []
    monkeypatch.setattr(spx_bot, "alert", lambda k, m: fired.append((k, m)))

    codes = iter([1, 1, 0])
    monkeypatch.setattr(spx_bot, "do_run", lambda *a, **k: next(codes))
    assert spx_bot.do_watchdog(spx_bot.Config(), live=False) == 0
    assert [k for k, _ in fired] == ["restarting", "restarting"]

    fired.clear()
    for permanent in (2, 3, 4):
        monkeypatch.setattr(spx_bot, "do_run",
                            lambda *a, _p=permanent, **k: _p)
        assert spx_bot.do_watchdog(spx_bot.Config(), live=False) == permanent
    assert all(k == "stopped" for k, _ in fired), \
        "a configuration error must not be retried"


def test_the_watchdog_names_an_open_position_when_it_restarts(monkeypatch):
    _state(position=_held(vol=19))
    monkeypatch.setattr(spx_bot.time, "sleep", lambda s: None)
    fired = []
    monkeypatch.setattr(spx_bot, "alert", lambda k, m: fired.append((k, m)))
    codes = iter([1, 0])
    monkeypatch.setattr(spx_bot, "do_run", lambda *a, **k: next(codes))
    spx_bot.do_watchdog(spx_bot.Config(), live=False)
    assert "POSITION IS OPEN" in fired[0][1]
    assert "19" in fired[0][1]


# ============ timeframe drives the poll cadence ==============================
def test_poll_is_derived_from_the_timeframe():
    assert spx_bot.Config(timeframe="Min1").poll == 30
    assert spx_bot.Config(timeframe="Min5").poll == 150
    assert spx_bot.Config(timeframe="Min60").poll == 300


def test_an_explicit_poll_override_wins():
    assert spx_bot.Config(timeframe="Min5", poll_seconds=45).poll == 45


def test_a_strategy_that_is_not_a_strategy_is_still_refused(monkeypatch):
    monkeypatch.setattr(spx_bot.fx, "clock_skew_ms", lambda: 0)
    rc = spx_bot.do_run(spx_bot.Config(
        lanes=[{"timeframe": "Min5", "strategy": "not_a_strategy"}]),
        live=False, once=True)
    assert rc == 2



def test_a_gate_on_fine_bars_is_permitted_because_it_does_not_rebalance(monkeypatch):
    """trend_filter on 1-minute bars was refused as an exposure target — 2,279x
    turnover in 31 days. As a gate it opens at most one bracketed trade at a
    time, so the turnover argument no longer holds and it may run."""
    _state()
    monkeypatch.setattr(spx_bot.fx, "clock_skew_ms", lambda: 0)
    monkeypatch.setattr(spx_bot, "step", lambda cfg, live: None)
    cfg = spx_bot.Config(lanes=[{"timeframe": "Min1",
                                 "strategy": "trend_filter"}])
    assert spx_bot.do_run(cfg, live=False, once=True) == 0



def test_the_watchdog_does_not_retry_a_ruinous_pairing(monkeypatch):
    monkeypatch.setattr(spx_bot.time, "sleep", lambda s: None)
    monkeypatch.setattr(spx_bot, "alert", lambda k, m: None)
    monkeypatch.setattr(spx_bot, "do_run", lambda *a, **k: 5)
    assert spx_bot.do_watchdog(spx_bot.Config(), live=False) == 5


def test_timeframe_round_trips_through_the_saved_config():
    spx_bot.Config(timeframe="Min60").save()
    loaded = spx_bot.Config.load()
    assert loaded.timeframe == "Min60"
    assert loaded.poll == 300


# ============ multiple timeframe lanes ======================================
# The operator asked to tick several timeframes and pick an approach under each.
# Only ONE can place orders per symbol: MEXC merges same-symbol positions into
# one and a position carries a single stop, so two lanes cannot each hold their
# own barriers — one lane's stop would close part of the other's position.
def test_lanes_fall_back_to_the_single_pairing():
    c = spx_bot.Config(timeframe="Min15", strategy="buy_hold")
    assert c.active_lanes() == [{"timeframe": "Min15", "strategy": "buy_hold"}]
    assert c.primary_lane()["strategy"] == "buy_hold"


def test_the_first_lane_is_the_one_that_trades():
    c = spx_bot.Config(lanes=[
        {"timeframe": "Min60", "strategy": "buy_hold"},
        {"timeframe": "Min5", "strategy": "barrier_harvest"}])
    assert c.primary_lane() == {"timeframe": "Min60", "strategy": "buy_hold"}
    assert len(c.active_lanes()) == 2


def test_poll_follows_the_finest_lane():
    """Polling slower than the finest lane's bars would miss them entirely."""
    c = spx_bot.Config(lanes=[{"timeframe": "Day1", "strategy": "buy_hold"},
                              {"timeframe": "Min1", "strategy": "buy_hold"}])
    assert c.poll == 30


def test_duplicate_and_malformed_lanes_are_dropped():
    c = spx_bot.Config(lanes=[
        {"timeframe": "Min5", "strategy": "buy_hold"},
        {"timeframe": "Min5", "strategy": "buy_hold"},      # duplicate
        {"timeframe": "", "strategy": "buy_hold"},          # no timeframe
        {"timeframe": "Min60"},                             # no strategy
    ])
    assert c.active_lanes() == [{"timeframe": "Min5", "strategy": "buy_hold"}]


def test_every_lane_is_validated_not_just_the_first(monkeypatch):
    """All lanes race, so a bad strategy anywhere in the list must stop startup
    rather than waiting to be reached."""
    monkeypatch.setattr(spx_bot.fx, "clock_skew_ms", lambda: 0)
    monkeypatch.setattr(spx_bot, "step", lambda cfg, live: None)
    bad = spx_bot.Config(lanes=[
        {"timeframe": "Min5", "strategy": "barrier_harvest"},
        {"timeframe": "Min60", "strategy": "typo_strategy"}])
    assert spx_bot.do_run(bad, live=False, once=True) == 2



def test_step_trades_the_primary_lane_not_the_stale_field(monkeypatch):
    _state()
    seen = {}
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 100.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "contracts_for", lambda *a, **k: 5)
    monkeypatch.setattr(spx_bot.fx, "open_long", lambda *a, **k: {})
    monkeypatch.setattr(spx_bot, "_attach_bracket",
                        lambda cfg, *a, **k: seen.update(
                            strategy=cfg.strategy, timeframe=cfg.timeframe)
                        or {"protected": True, "tp": None, "sl": 90.0,
                            "position_id": 1})
    cfg = spx_bot.Config(strategy="barrier_harvest", timeframe="Min5",
                         lanes=[{"timeframe": "Min60",
                                 "strategy": "buy_hold"}])
    spx_bot.step(cfg, live=False)
    assert seen == {"strategy": "buy_hold", "timeframe": "Min60"}


def test_lanes_round_trip_through_the_saved_config():
    spx_bot.Config(lanes=[{"timeframe": "Min15", "strategy": "buy_hold"},
                          {"timeframe": "Hour4",
                           "strategy": "barrier_harvest"}]).save()
    assert spx_bot.Config.load().active_lanes() == [
        {"timeframe": "Min15", "strategy": "buy_hold"},
        {"timeframe": "Hour4", "strategy": "barrier_harvest"}]


# ============ the lane race ==================================================
# "Enable every timeframe with a different approach, whichever signals first
# wins." MEXC allows one position per symbol, so the winner OWNS it until it
# closes — a different lane's stop would close part of a position it does not own.
def _bars(n=400, rising=True):
    import pandas as pd
    base = 100.0
    rows = []
    for i in range(n):
        px = base + (i * 0.05 if rising else -i * 0.05)
        rows.append({"Date": datetime(2026, 1, 1, tzinfo=timezone.utc)
                     + timedelta(minutes=5 * i),
                     "Open": px, "High": px + 0.2, "Low": px - 0.2, "Close": px})
    return pd.DataFrame(rows)


def test_the_race_is_finest_bars_first():
    """A single poll can find several lanes ready; the tie-break must be
    deterministic, and the finest bar closed most recently."""
    c = spx_bot.Config(lanes=[{"timeframe": "Day1", "strategy": "buy_hold"},
                              {"timeframe": "Min1", "strategy": "buy_hold"},
                              {"timeframe": "Min15", "strategy": "buy_hold"}])
    assert [l["timeframe"] for l in spx_bot._lane_order(c)] == \
        ["Min1", "Min15", "Day1"]


def test_the_first_lane_that_wants_exposure_wins(monkeypatch):
    monkeypatch.setattr(spx_bot.fx, "klines", lambda s, tf, n=400: _bars())
    # trend_filter on a falling series declines; barrier_harvest never does
    c = spx_bot.Config(lanes=[{"timeframe": "Min1", "strategy": "trend_filter"},
                              {"timeframe": "Min5",
                               "strategy": "barrier_harvest"}])
    monkeypatch.setattr(spx_bot.fx, "klines",
                        lambda s, tf, n=400: _bars(rising=(tf != "Min1")))
    lane, why = spx_bot.pick_lane(c)
    assert lane["strategy"] == "barrier_harvest", \
        "the declining lane must be skipped, not used"
    assert "never declines" in why, "why describes the winner, not the misses"


def test_no_lane_wanting_exposure_means_no_trade(monkeypatch):
    monkeypatch.setattr(spx_bot.fx, "klines",
                        lambda s, tf, n=400: _bars(rising=False))
    c = spx_bot.Config(lanes=[{"timeframe": "Min5", "strategy": "trend_filter"}])
    lane, why = spx_bot.pick_lane(c)
    assert lane is None
    assert "moving average" in why


def test_a_lane_with_no_bars_is_skipped_not_fatal(monkeypatch):
    def flaky(sym, tf, n=400):
        if tf == "Min1":
            raise spx_bot.fx.MexcFuturesError("no bars")
        return _bars()
    monkeypatch.setattr(spx_bot.fx, "klines", flaky)
    c = spx_bot.Config(lanes=[{"timeframe": "Min1", "strategy": "buy_hold"},
                              {"timeframe": "Min5", "strategy": "buy_hold"}])
    lane, _ = spx_bot.pick_lane(c)
    assert lane["timeframe"] == "Min5"


def test_the_winner_is_recorded_and_owns_the_position(monkeypatch):
    _state()
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 100.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "contracts_for", lambda *a, **k: 5)
    monkeypatch.setattr(spx_bot.fx, "open_long", lambda *a, **k: {})
    monkeypatch.setattr(spx_bot.fx, "klines", lambda s, tf, n=400: _bars())
    seen = {}
    monkeypatch.setattr(spx_bot, "_attach_bracket",
                        lambda cfg, *a, **k: seen.update(strategy=cfg.strategy)
                        or {"protected": True, "tp": None, "sl": 90.0,
                            "position_id": 1})
    cfg = spx_bot.Config(lanes=[{"timeframe": "Min60", "strategy": "buy_hold"},
                                {"timeframe": "Min5",
                                 "strategy": "barrier_harvest"}])
    spx_bot.step(cfg, live=False)
    pos = spx_bot._read_state()["position"]
    assert pos["lane"] == {"timeframe": "Min5", "strategy": "barrier_harvest"}, \
        "finest lane should win the race"
    assert seen["strategy"] == "barrier_harvest", "and its barriers are used"


def test_the_owning_lane_manages_the_exit_not_another(monkeypatch):
    """A different lane's stop would close part of a position it does not own."""
    _state(position=dict(_held(entry=100.0), protected=True,
                         lane={"timeframe": "Min60", "strategy": "buy_hold"}))
    seen = {}
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 101.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "open_positions",
                        lambda s=None: [{"positionId": 1, "holdVol": 10}])
    monkeypatch.setattr(spx_bot, "_attach_bracket",
                        lambda cfg, *a, **k: seen.update(strategy=cfg.strategy)
                        or {"protected": True, "tp": None, "sl": 90.0,
                            "position_id": 1})
    cfg = spx_bot.Config(strategy="barrier_harvest", timeframe="Min5",
                         lanes=[{"timeframe": "Min5",
                                 "strategy": "barrier_harvest"}])
    _s = spx_bot._read_state()
    _s["position"]["protected"] = False        # force a bracket retry
    spx_bot._write_state(_s)
    spx_bot.step(cfg, live=False)
    assert seen["strategy"] == "buy_hold", \
        "the lane that opened it must keep managing it"


def test_every_strategy_is_usable_as_a_gate():
    """As a gate there is no per-bar rebalancing, so the turnover objection that
    made four of them backtest-only does not apply."""
    from tradingagents import strategies as sg
    for key in sg.ORDER:
        assert spx_bot.lane_may_gate(key), key
    assert not spx_bot.lane_may_gate("no_such_strategy")


# ============ one-shot lanes ================================================
def test_buy_hold_declines_after_its_one_entry(monkeypatch):
    """Without this, buy_hold re-entered every time a stop closed it — which is
    "hold until stopped, then buy again", a different strategy wearing the name."""
    monkeypatch.setattr(spx_bot.fx, "klines", lambda s, tf, n=400: _bars())
    c = spx_bot.Config(lanes=[{"timeframe": "Min5", "strategy": "buy_hold"}])
    assert spx_bot.pick_lane(c, {})[0]["strategy"] == "buy_hold"
    lane, why = spx_bot.pick_lane(c, {"lanes_used": ["buy_hold@Min5"]})
    assert lane is None
    assert "already had its one entry" in why


def test_a_used_one_shot_lane_yields_to_the_next(monkeypatch):
    monkeypatch.setattr(spx_bot.fx, "klines", lambda s, tf, n=400: _bars())
    c = spx_bot.Config(lanes=[{"timeframe": "Min5", "strategy": "buy_hold"},
                              {"timeframe": "Min60",
                               "strategy": "barrier_harvest"}])
    lane, _ = spx_bot.pick_lane(c, {"lanes_used": ["buy_hold@Min5"]})
    assert lane == {"timeframe": "Min60", "strategy": "barrier_harvest"}


def test_a_repeating_lane_is_never_marked_one_shot(monkeypatch):
    """barrier_harvest is meant to re-enter after every exit — that IS the
    strategy. Marking it used would stop it after one trade."""
    monkeypatch.setattr(spx_bot.fx, "klines", lambda s, tf, n=400: _bars())
    c = spx_bot.Config(lanes=[{"timeframe": "Min5",
                               "strategy": "barrier_harvest"}])
    assert spx_bot.pick_lane(
        c, {"lanes_used": ["barrier_harvest@Min5"]})[0] is not None


def test_taking_a_one_shot_entry_records_it(monkeypatch):
    _state()
    monkeypatch.setattr(spx_bot.fx, "last_price", lambda s: 100.0)
    monkeypatch.setattr(spx_bot.fx, "usdt_equity", lambda: 500.0)
    monkeypatch.setattr(spx_bot.fx, "contracts_for", lambda *a, **k: 5)
    monkeypatch.setattr(spx_bot.fx, "open_long", lambda *a, **k: {})
    monkeypatch.setattr(spx_bot.fx, "klines", lambda s, tf, n=400: _bars())
    monkeypatch.setattr(spx_bot, "_attach_bracket",
                        lambda *a, **k: {"protected": True, "tp": None,
                                         "sl": 90.0, "position_id": 1})
    cfg = spx_bot.Config(lanes=[{"timeframe": "Min5", "strategy": "buy_hold"}])
    spx_bot.step(cfg, live=False)
    assert spx_bot._read_state()["lanes_used"] == ["buy_hold@Min5"]


# ============ multi-cycle integration ========================================
# Unit tests check one call. These run the loop the way it actually runs, because
# the bugs that cost money today were all ORDERING bugs: state written too late,
# a lane switched at the wrong moment, an exit booked twice.
class FakeExchange:
    """A minimal MEXC that remembers a position and can close it behind the bot's
    back, which is what the real exchange does when a barrier fires."""

    def __init__(self, price=100.0):
        self.price = price
        self.position = None
        self.next_id = 500
        self.orders = []
        self.stops = []
        self.submitted = []

    def last_price(self, symbol):
        return self.price

    def usdt_equity(self):
        return 500.0

    def contracts_for(self, symbol, notional, px):
        return 10

    def open_positions(self, symbol=None):
        return [self.position] if self.position else []

    def open_long(self, symbol, vol, *, leverage, dry_run=True):
        assert self.position is None, "the bot stacked a position"
        self.next_id += 1
        self.position = {"positionId": self.next_id, "holdVol": vol,
                         "holdAvgPrice": self.price, "openType": 1,
                         "leverage": leverage}
        self.submitted.append(("open", vol))
        return {"dry_run": False, "response": self.next_id}

    def close_long(self, symbol, vol, *, leverage, dry_run=True):
        self.position = None
        self.submitted.append(("close", vol))
        return {"dry_run": False, "response": 1}

    def place_position_stop(self, symbol, pid, vol, **kw):
        self.stops.append({"positionId": str(pid), "errorCode": 0,
                           "isFinished": 0, "state": 2,
                           "stopLossPrice": kw.get("stop_loss_price")})
        return {"dry_run": False, "response": len(self.stops)}

    def limit_close_long(self, symbol, vol, price, *, leverage, dry_run=True):
        self.orders.append({"orderId": f"o{len(self.orders)}", "side": 4,
                            "price": price, "vol": vol})
        return {"dry_run": False, "response": "ok"}

    def list_position_stops(self, symbol=None):
        return list(self.stops)

    def open_orders(self, symbol=None):
        return list(self.orders)

    def cancel_all_orders(self, symbol):
        self.orders.clear()
        return {}

    def verify_bracket(self, symbol, pid, tp=None):
        active = [r for r in self.stops if str(r["positionId"]) == str(pid)
                  and r["errorCode"] == 0 and not r["isFinished"]]
        resting = [o for o in self.orders
                   if tp and abs(float(o["price"]) - float(tp)) < 1e-6]
        return {"stop_active": bool(active),
                "target_resting": bool(resting) if tp else True,
                "protected": bool(active) and (bool(resting) if tp else True),
                "stop_error_codes": [], "target_order_id": None}

    # the exchange closing the position on its own, as a barrier fill does
    def fill_target(self, price):
        self.position = None
        self.orders.clear()
        for r in self.stops:
            r["isFinished"] = 1
            r["state"] = 3
            r["takeProfitPrice"] = price
        self.price = price


@pytest.fixture
def wired(monkeypatch):
    ex = FakeExchange()
    for name in ("last_price", "usdt_equity", "contracts_for", "open_positions",
                 "open_long", "close_long", "place_position_stop",
                 "limit_close_long", "list_position_stops", "open_orders",
                 "cancel_all_orders", "verify_bracket"):
        monkeypatch.setattr(spx_bot.fx, name, getattr(ex, name))
    monkeypatch.setattr(spx_bot.fx, "klines", lambda s, tf, n=400: _bars())
    monkeypatch.setattr(spx_bot, "_snap", lambda cfg, target: round(target, 2))
    monkeypatch.setenv("SPX_BOT_ARMED", "yes")
    return ex


def test_four_cycles_enter_hold_get_closed_then_re_enter(wired):
    """The full loop: the exchange fills the target behind the bot's back, the bot
    notices, books it, and races again. This is the 1-trade-vs-15 path."""
    ex = wired
    _state()
    cfg = spx_bot.Config(margin_usd=5.0, leverage=3, max_losses=0,
                         lanes=[{"timeframe": "Min5",
                                 "strategy": "barrier_harvest"}])

    spx_bot.step(cfg, live=True)                       # 1: enter
    st = spx_bot._read_state()
    assert st["position"]["vol"] == 10
    assert st["position"]["protected"] is True, "both barriers must be verified"
    assert ex.submitted == [("open", 10)]

    spx_bot.step(cfg, live=True)                       # 2: hold, do nothing
    assert ex.submitted == [("open", 10)], "no second order while holding"
    assert spx_bot._read_state()["position"] is not None

    ex.fill_target(102.0)                              # exchange takes profit
    spx_bot.step(cfg, live=True)                       # 3: notice and book it
    st = spx_bot._read_state()
    assert st["position"] is None, "the bot must notice the exchange closed it"
    assert st["realised_today"] > 0
    assert st["losses"] == 0

    spx_bot.step(cfg, live=True)                       # 4: race again, re-enter
    st = spx_bot._read_state()
    assert st["position"] is not None, "1 trade must become many"
    assert [a for a, _ in ex.submitted].count("open") == 2


def test_the_loss_limit_stops_the_cycle_after_n_losses(wired):
    ex = wired
    _state()
    cfg = spx_bot.Config(margin_usd=5.0, leverage=3, max_losses=2,
                         stop_loss_pct=10.0,
                         lanes=[{"timeframe": "Min5",
                                 "strategy": "barrier_harvest"}])
    for expected_losses in (1, 2):
        spx_bot.step(cfg, live=True)                   # enter
        assert spx_bot._read_state()["position"] is not None
        ex.price = 85.0                                # below the stop
        spx_bot.step(cfg, live=True)                   # backup stop fires
        st = spx_bot._read_state()
        assert st["position"] is None
        assert st["losses"] == expected_losses
        ex.price = 100.0
    opens_before = [a for a, _ in ex.submitted].count("open")
    spx_bot.step(cfg, live=True)                       # must refuse now
    assert [a for a, _ in ex.submitted].count("open") == opens_before, \
        "the loss limit must stop further entries"


def test_a_one_shot_lane_hands_over_across_cycles(wired):
    ex = wired
    _state()
    cfg = spx_bot.Config(margin_usd=5.0, leverage=3, max_losses=0,
                         lanes=[{"timeframe": "Min5", "strategy": "buy_hold"},
                                {"timeframe": "Min60",
                                 "strategy": "barrier_harvest"}])
    spx_bot.step(cfg, live=True)
    assert spx_bot._read_state()["position"]["lane"]["strategy"] == "buy_hold"
    ex.fill_target(102.0)
    spx_bot.step(cfg, live=True)                       # booked, now flat
    spx_bot.step(cfg, live=True)                       # buy_hold is spent
    lane = spx_bot._read_state()["position"]["lane"]
    assert lane["strategy"] == "barrier_harvest", \
        "the spent one-shot lane must hand over"


# ============ a stop beyond liquidation is not a stop ========================
# The UI warned about this; the BOT did not, so it would have run 200x with a 10%
# stop where liquidation arrives at 0.5% — the stop is decoration and the real
# exit is the venue taking the whole margin.
@pytest.mark.parametrize("lev,stop,ok", [
    (1, 10.0, True),
    (3, 10.0, True),        # wipe-out at 33%, stop well inside
    # 3x wipes out near 33.3%, so a 30% stop DOES still fire first — marginal,
    # not impossible. It warns rather than refusing. This expectation was mine and
    # it was wrong; the code is right.
    (3, 30.0, True),
    (3, 34.0, False),       # past the wipe-out: genuinely unreachable
    (10, 10.0, False),      # wipe-out at 10% — exactly unreachable
    (10, 5.0, True),
    (20, 10.0, False),
    (200, 10.0, False),
    (200, 0.3, True),       # inside 70% of the 0.5% wipe-out
])
def test_stop_reachability(lev, stop, ok):
    assert spx_bot.stop_is_reachable(lev, stop)[0] is ok


def test_the_runner_refuses_an_unreachable_stop(monkeypatch):
    monkeypatch.setattr(spx_bot, "step", lambda cfg, live: None)
    cfg = spx_bot.Config(margin_usd=5.0, leverage=200, stop_loss_pct=10.0)
    assert spx_bot.do_run(cfg, live=False, once=True) == 6


def test_the_watchdog_will_not_retry_an_unreachable_stop(monkeypatch):
    monkeypatch.setattr(spx_bot.time, "sleep", lambda s: None)
    monkeypatch.setattr(spx_bot, "alert", lambda k, m: None)
    monkeypatch.setattr(spx_bot, "do_run", lambda *a, **k: 6)
    assert spx_bot.do_watchdog(spx_bot.Config(), live=False) == 6


def test_a_stop_near_the_wipeout_warns_but_runs(monkeypatch):
    _state()
    monkeypatch.setattr(spx_bot, "step", lambda cfg, live: None)
    ok, why = spx_bot.stop_is_reachable(10, 8.0)     # wipe-out 10%, 70% = 7%
    assert ok is True and "maintenance margin" in why
    assert spx_bot.do_run(spx_bot.Config(leverage=10, stop_loss_pct=8.0),
                          live=False, once=True) == 0


def test_the_operators_settings_are_permitted():
    """3x with a 10% stop: wipe-out at 33%, so the stop fires with room to spare."""
    ok, why = spx_bot.stop_is_reachable(3, 10.0)
    assert ok is True and why == ""


# ============ liquidation uses the exchange's maintenance margin =============
# Borrowed from reading OctoBot's position model: liquidation price is
# entry x (1 - initial_margin_rate + maintenance_margin_rate), and MEXC publishes
# maintenanceMarginRate = 0.004 directly. The 100/leverage figure this project used
# overstates the survivable move FIVEFOLD at 200x — 0.50% claimed, 0.10% actual.
def test_the_wipeout_point_accounts_for_maintenance_margin(monkeypatch):
    monkeypatch.setattr(spx_bot.fx, "contract_spec",
                        lambda s: {"maintenanceMarginRate": 0.004})
    assert spx_bot.fx.liquidation_move_pct("SPX500_USDT", 200) == \
        pytest.approx(0.1), "0.5% - 0.4% = 0.1%, not 0.5%"
    assert spx_bot.fx.liquidation_move_pct("SPX500_USDT", 3) == \
        pytest.approx((1 / 3 - 0.004) * 100)


def test_leverage_the_maintenance_margin_alone_exhausts_is_refused(monkeypatch):
    """At 1/mmr = 250x the maintenance margin equals the whole position, so it is
    liquidated on entry no matter where the stop sits."""
    monkeypatch.setattr(spx_bot.fx, "contract_spec",
                        lambda s: {"maintenanceMarginRate": 0.004})
    assert spx_bot.fx.liquidation_move_pct("SPX500_USDT", 250) == 0.0
    ok, why = spx_bot.stop_is_reachable(250, 0.01, "SPX500_USDT")
    assert ok is False and "liquidated on entry" in why


def test_a_stop_between_the_two_formulas_is_now_correctly_refused(monkeypatch):
    """A 0.3% stop at 200x passed the old 100/leverage guard (0.5% survivable) and
    is refused by the real one (0.1%). That gap is where an account dies."""
    monkeypatch.setattr(spx_bot.fx, "contract_spec",
                        lambda s: {"maintenanceMarginRate": 0.004})
    assert spx_bot.stop_is_reachable(200, 0.3, "SPX500_USDT")[0] is False
    assert 0.3 < 100 / 200, "the old guard would have allowed it"


def test_an_unreadable_margin_rate_falls_back_rather_than_crashing(monkeypatch):
    def boom(symbol):
        raise spx_bot.fx.MexcFuturesError("unreachable")
    monkeypatch.setattr(spx_bot.fx, "contract_spec", boom)
    assert spx_bot.fx.liquidation_move_pct("SPX500_USDT", 200) == \
        pytest.approx(0.5), "falls back to the naive figure"
