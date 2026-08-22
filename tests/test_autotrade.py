"""Auto-trade strategy: configurable entry rules, exits, and spend caps.

Real money, so the rules are unit-tested exhaustively and the engine is only ever
driven here through injected fills — no test may reach the exchange.
"""

import json

import pytest

from tradingagents import autotrade

pytestmark = pytest.mark.unit


def _config(**over):
    base = {"armed": True, "buy_trigger": autotrade.TRIGGER_EVERY,
                "per_trade_usd": 3.0, "daily_cap_usd": 15.0, "max_positions": 3,
                "min_volume_usd": 50_000.0, "exit_mode": autotrade.EXIT_TP_SL,
                "take_profit_pct": 50.0, "stop_loss_pct": 30.0, "max_hold_hours": 6.0}
    base.update(over)
    return autotrade.StrategyConfig(**base)


def _coin(**over):
    base = {"symbol": "XPLKUSDT", "base": "XPLK", "name": "xPayLink",
                "quote_volume": 120_000.0, "age_hours": 0.5}
    base.update(over)
    return base


# --- entry rules ----------------------------------------------------------


def test_every_listing_trigger_buys_anything():
    ok, why = autotrade.should_buy(_config(buy_trigger=autotrade.TRIGGER_EVERY),
                                   _coin(quote_volume=0.0), verdict=None)
    assert ok is True
    assert "every" in why.lower()


def test_volume_trigger_requires_the_floor():
    cfg = _config(buy_trigger=autotrade.TRIGGER_VOLUME, min_volume_usd=50_000.0)
    assert autotrade.should_buy(cfg, _coin(quote_volume=60_000.0), verdict=None)[0] is True
    ok, why = autotrade.should_buy(cfg, _coin(quote_volume=10_000.0), verdict=None)
    assert ok is False
    assert "volume" in why.lower()


def test_verdict_trigger_requires_a_buy_verdict():
    cfg = _config(buy_trigger=autotrade.TRIGGER_VERDICT)
    assert autotrade.should_buy(cfg, _coin(), verdict="BUY")[0] is True
    for verdict in ("HOLD", "SELL", "", None):
        ok, why = autotrade.should_buy(cfg, _coin(), verdict=verdict)
        assert ok is False, verdict
        assert "verdict" in why.lower()


def test_verdict_trigger_is_case_insensitive():
    cfg = _config(buy_trigger=autotrade.TRIGGER_VERDICT)
    assert autotrade.should_buy(cfg, _coin(), verdict="buy")[0] is True


def test_disarmed_config_never_buys():
    for trigger in autotrade.BUY_TRIGGERS:
        ok, why = autotrade.should_buy(_config(armed=False, buy_trigger=trigger),
                                       _coin(), verdict="BUY")
        assert ok is False
        assert "armed" in why.lower()


# --- spend caps -----------------------------------------------------------


def test_daily_cap_blocks_further_buys():
    cfg = _config(per_trade_usd=3.0, daily_cap_usd=6.0)
    ok, _ = autotrade.can_spend(cfg, spent_today=3.0, open_positions=0)
    assert ok is True
    ok, why = autotrade.can_spend(cfg, spent_today=6.0, open_positions=0)
    assert ok is False
    assert "daily" in why.lower()


def test_a_partial_remaining_cap_still_blocks_a_full_size_trade():
    """Spending less than the configured size would silently change the strategy."""
    cfg = _config(per_trade_usd=3.0, daily_cap_usd=5.0)
    ok, why = autotrade.can_spend(cfg, spent_today=3.0, open_positions=0)
    assert ok is False
    assert "daily" in why.lower()


def test_position_limit_blocks_further_buys():
    cfg = _config(max_positions=2)
    assert autotrade.can_spend(cfg, spent_today=0.0, open_positions=1)[0] is True
    ok, why = autotrade.can_spend(cfg, spent_today=0.0, open_positions=2)
    assert ok is False
    assert "position" in why.lower()


def test_per_trade_below_exchange_minimum_is_refused():
    ok, why = autotrade.can_spend(_config(per_trade_usd=0.5), 0.0, 0)
    assert ok is False
    assert "minimum" in why.lower()


# --- exit rules -----------------------------------------------------------


def _position(**over):
    base = {"symbol": "XPLKUSDT", "base": "XPLK", "qty": 1000.0, "entry_price": 0.003,
                "spent": 3.0, "opened_at": 1785000000.0}
    base.update(over)
    return base


def test_take_profit_fires_at_the_target():
    cfg = _config(exit_mode=autotrade.EXIT_TP_ONLY, take_profit_pct=50.0)
    pos = _position(entry_price=0.002)
    assert autotrade.should_sell(cfg, pos, price=0.003, now=1785000000.0)[0] is True
    assert autotrade.should_sell(cfg, pos, price=0.0029, now=1785000000.0)[0] is False


def test_take_profit_reason_names_the_gain():
    cfg = _config(exit_mode=autotrade.EXIT_TP_ONLY, take_profit_pct=50.0)
    _, why = autotrade.should_sell(cfg, _position(entry_price=0.002), price=0.004,
                                  now=1785000000.0)
    assert "take-profit" in why.lower()
    assert "100" in why


def test_take_profit_only_ignores_a_collapse():
    """The documented cost of that mode: no floor under the position."""
    cfg = _config(exit_mode=autotrade.EXIT_TP_ONLY, stop_loss_pct=30.0)
    ok, _ = autotrade.should_sell(cfg, _position(entry_price=0.002), price=0.0001,
                                 now=1785000000.0)
    assert ok is False


def test_stop_loss_fires_when_enabled():
    cfg = _config(exit_mode=autotrade.EXIT_TP_SL, stop_loss_pct=30.0)
    pos = _position(entry_price=0.002)
    ok, why = autotrade.should_sell(cfg, pos, price=0.0013, now=1785000000.0)
    assert ok is True
    assert "stop-loss" in why.lower()


def test_stop_loss_does_not_fire_above_the_threshold():
    cfg = _config(exit_mode=autotrade.EXIT_TP_SL, stop_loss_pct=30.0)
    assert autotrade.should_sell(cfg, _position(entry_price=0.002), price=0.0015,
                                 now=1785000000.0)[0] is False


def test_time_exit_only_in_the_timed_mode():
    pos = _position(opened_at=1785000000.0)
    late = 1785000000.0 + 7 * 3600
    assert autotrade.should_sell(_config(exit_mode=autotrade.EXIT_TP_SL), pos,
                                 price=0.003, now=late)[0] is False
    ok, why = autotrade.should_sell(_config(exit_mode=autotrade.EXIT_TP_SL_TIME,
                                           max_hold_hours=6.0),
                                   pos, price=0.003, now=late)
    assert ok is True
    assert "held" in why.lower()


def test_a_zero_entry_price_never_triggers_a_sell():
    """A dry-run fill has no price; treating it as -100% would sell instantly."""
    cfg = _config(exit_mode=autotrade.EXIT_TP_SL)
    assert autotrade.should_sell(cfg, _position(entry_price=0.0), price=0.001,
                                 now=1785000000.0)[0] is False


# --- persistence ----------------------------------------------------------


def test_config_round_trips_through_disk(tmp_path):
    path = tmp_path / "bot.json"
    cfg = _config(per_trade_usd=7.5, take_profit_pct=80.0)
    autotrade.save_config(path, cfg)
    assert autotrade.load_config(path) == cfg


def test_missing_config_loads_disarmed_defaults(tmp_path):
    cfg = autotrade.load_config(tmp_path / "absent.json")
    assert cfg.armed is False, "a fresh install must not trade"


def test_corrupt_config_loads_disarmed_defaults(tmp_path):
    path = tmp_path / "bot.json"
    path.write_text("{not json")
    assert autotrade.load_config(path).armed is False


def test_unknown_config_keys_are_ignored(tmp_path):
    path = tmp_path / "bot.json"
    path.write_text(json.dumps({"armed": True, "legacy_field": 1}))
    assert autotrade.load_config(path).armed is True


def test_ledger_round_trips(tmp_path):
    path = tmp_path / "ledger.json"
    autotrade.save_ledger(path, {"positions": [_position()], "spent_today": 3.0,
                                 "day": "2026-07-30", "history": []})
    # Read back as the same day, or the counter resets by design.
    led = autotrade.load_ledger(path, today="2026-07-30")
    assert led["positions"][0]["symbol"] == "XPLKUSDT"
    assert led["spent_today"] == 3.0


def test_spent_today_resets_on_a_new_day(tmp_path):
    path = tmp_path / "ledger.json"
    autotrade.save_ledger(path, {"positions": [], "spent_today": 9.0,
                                 "day": "2026-07-29", "history": []})
    led = autotrade.load_ledger(path, today="2026-07-30")
    assert led["spent_today"] == 0.0
    assert led["day"] == "2026-07-30"


def test_spent_today_survives_within_the_same_day(tmp_path):
    path = tmp_path / "ledger.json"
    autotrade.save_ledger(path, {"positions": [], "spent_today": 9.0,
                                 "day": "2026-07-30", "history": []})
    assert autotrade.load_ledger(path, today="2026-07-30")["spent_today"] == 9.0
