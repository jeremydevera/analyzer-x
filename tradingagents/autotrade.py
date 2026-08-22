"""Auto-trade rules for newly listed MEXC coins.

Pure decision logic plus persistence — nothing here talks to the exchange. The
engine that acts on these decisions passes fills in, which keeps every rule
testable without risking an order.

The defaults are deliberately inert: a fresh install loads ``armed=False``, so the
strategy has to be configured and armed explicitly before anything is bought.

A note on what these rules can and cannot do. A stop-loss caps a loss only while
someone is still bidding. New listings include outright rug pulls — MEXC's own
feed carried a scam alert for $PIPEDOG noting the LP tokens were never burned and
99% of holder wallets were fresh — and in that situation there is no bid to sell
into at any percentage. Position sizing is the only real protection.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import time
from datetime import datetime, timezone

from tradingagents.dataflows.mexc_trade import MIN_QUOTE_USD

logger = logging.getLogger(__name__)

# Entry rules, cheapest signal first.
TRIGGER_EVERY = "every new listing"
TRIGGER_VOLUME = "volume floor"
TRIGGER_VERDICT = "agent verdict is BUY"
BUY_TRIGGERS = (TRIGGER_EVERY, TRIGGER_VOLUME, TRIGGER_VERDICT)

# Exit rules.
EXIT_TP_ONLY = "take-profit only"
EXIT_TP_SL = "take-profit + stop-loss"
EXIT_TP_SL_TIME = "take-profit + stop-loss + time"
EXIT_MODES = (EXIT_TP_SL, EXIT_TP_SL_TIME, EXIT_TP_ONLY)


@dataclasses.dataclass(frozen=True)
class StrategyConfig:
    """Everything the engine needs to decide. Persisted as JSON."""

    armed: bool = False
    buy_trigger: str = TRIGGER_VERDICT
    per_trade_usd: float = 3.0
    daily_cap_usd: float = 15.0
    max_positions: int = 3
    min_volume_usd: float = 50_000.0
    exit_mode: str = EXIT_TP_SL
    take_profit_pct: float = 50.0
    stop_loss_pct: float = 30.0
    max_hold_hours: float = 6.0


def should_buy(config: StrategyConfig, coin: dict, *, verdict: str | None):
    """``(buy, reason)`` for one candidate coin."""
    if not config.armed:
        return False, "auto-trade is not armed"

    if config.buy_trigger == TRIGGER_EVERY:
        return True, "trigger: every new listing"
    if config.buy_trigger == TRIGGER_VOLUME:
        volume = float(coin.get("quote_volume") or 0.0)
        if volume >= config.min_volume_usd:
            return True, f"24h volume ${volume:,.0f} clears ${config.min_volume_usd:,.0f}"
        return False, f"24h volume ${volume:,.0f} below floor ${config.min_volume_usd:,.0f}"
    if config.buy_trigger == TRIGGER_VERDICT:
        if (verdict or "").strip().upper() == "BUY":
            return True, "agent verdict is BUY"
        return False, f"agent verdict is {verdict or 'none'}, not BUY"
    return False, f"unknown trigger {config.buy_trigger!r}"


def can_spend(config: StrategyConfig, spent_today: float, open_positions: int):
    """``(allowed, reason)`` for the spend caps, checked before any order."""
    if config.per_trade_usd < MIN_QUOTE_USD:
        return False, (f"per-trade ${config.per_trade_usd:.2f} is below the exchange "
                       f"minimum ${MIN_QUOTE_USD:.2f}")
    if open_positions >= config.max_positions:
        return False, f"already holding {open_positions} positions (max {config.max_positions})"
    # Requires room for a full-size trade: buying a smaller amount to fit the
    # remaining cap would quietly change the strategy being tested.
    if spent_today + config.per_trade_usd > config.daily_cap_usd:
        return False, (f"daily cap ${config.daily_cap_usd:.2f} reached "
                       f"(${spent_today:.2f} spent)")
    return True, "within caps"


def should_sell(config: StrategyConfig, position: dict, price: float, now: float):
    """``(sell, reason)`` for an open position at ``price``."""
    entry = float(position.get("entry_price") or 0.0)
    if entry <= 0 or price <= 0:
        # A dry-run fill has no price; treating that as -100% would sell at once.
        return False, "no entry price recorded"

    change = (price - entry) / entry * 100.0
    if change >= config.take_profit_pct:
        return True, f"take-profit hit ({change:+.1f}%)"

    if (config.exit_mode in (EXIT_TP_SL, EXIT_TP_SL_TIME)
            and change <= -abs(config.stop_loss_pct)):
        return True, f"stop-loss hit ({change:+.1f}%)"

    if config.exit_mode == EXIT_TP_SL_TIME:
        held_hours = (now - float(position.get("opened_at") or now)) / 3600.0
        if held_hours >= config.max_hold_hours:
            return True, f"held {held_hours:.1f}h, past the {config.max_hold_hours:.0f}h limit"

    return False, f"holding ({change:+.1f}%)"


# --- persistence ----------------------------------------------------------


def _read_json(path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path, payload: dict) -> None:
    try:
        os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
    except OSError as exc:
        logger.warning("Could not write %s: %s", path, exc)


def load_config(path) -> StrategyConfig:
    """Stored strategy, or disarmed defaults.

    A missing or unreadable file must never produce an armed strategy: the failure
    mode of guessing wrong here is spending real money.
    """
    raw = _read_json(path)
    fields = {f.name for f in dataclasses.fields(StrategyConfig)}
    return StrategyConfig(**{k: v for k, v in raw.items() if k in fields})


def save_config(path, config: StrategyConfig) -> None:
    _write_json(path, dataclasses.asdict(config))


def _today() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def load_ledger(path, *, today: str | None = None) -> dict:
    """Open positions, today's spend, and closed-trade history.

    The daily spend counter resets when the UTC date changes, so yesterday's
    spending cannot block today's trades or vice versa.
    """
    raw = _read_json(path)
    day = today or _today()
    ledger = {
        "positions": raw.get("positions") or [],
        "spent_today": float(raw.get("spent_today") or 0.0),
        "day": raw.get("day") or day,
        "history": raw.get("history") or [],
    }
    if ledger["day"] != day:
        ledger["spent_today"] = 0.0
        ledger["day"] = day
    return ledger


def save_ledger(path, ledger: dict) -> None:
    _write_json(path, {
        "positions": ledger.get("positions") or [],
        "spent_today": float(ledger.get("spent_today") or 0.0),
        "day": ledger.get("day") or _today(),
        # Bounded: a long-running bot should not grow this file without limit.
        "history": (ledger.get("history") or [])[-200:],
    })


def open_position(coin: dict, fill: dict, *, now: float | None = None) -> dict:
    """Ledger entry for a filled buy."""
    return {
        "symbol": coin["symbol"],
        "base": coin.get("base") or coin["symbol"],
        "name": coin.get("name") or "",
        "qty": float(fill.get("qty") or 0.0),
        "entry_price": float(fill.get("price") or 0.0),
        "spent": float(fill.get("spent") or 0.0),
        "opened_at": now if now is not None else time.time(),
        "dry_run": bool(fill.get("dry_run")),
    }


def close_position(position: dict, fill: dict, reason: str,
                   *, now: float | None = None) -> dict:
    """History entry for a filled sell, including realised profit."""
    received = float(fill.get("received") or 0.0)
    spent = float(position.get("spent") or 0.0)
    return {
        **position,
        "closed_at": now if now is not None else time.time(),
        "received": received,
        "profit_usd": received - spent,
        "profit_pct": ((received - spent) / spent * 100.0) if spent else 0.0,
        "reason": reason,
    }
