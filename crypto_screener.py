"""New Crypto tab — MEXC new-listing screener with per-coin agent analysis.

Kept out of app.py, which already carries the whole single-run screen. The pure
helpers here (config building, instrument context, row formatting) are unit
tested without a Streamlit runtime; render_new_crypto_tab() is the only part
that touches st.*.
"""

from __future__ import annotations

import time
from copy import deepcopy

# Fundamentals is omitted rather than disabled: a three-week-old memecoin has no
# filings, and giving that analyst nothing to read only feeds placeholders into
# the debate. Mirrors how the CLI filters analysts for crypto.
CRYPTO_ANALYSTS = ("market", "social", "news")


def build_crypto_config(base: dict, *, provider: str, deep_model: str,
                        quick_model: str, debate_rounds: int,
                        risk_rounds: int) -> dict:
    """Config for a new-coin run: MEXC prices, Yahoo news, Twitter on.

    Returns a copy — the caller's DEFAULT_CONFIG must stay untouched so a later
    stock run in the same process still routes prices to yfinance.
    """
    cfg = deepcopy(base)
    cfg["llm_provider"] = provider
    cfg["deep_think_llm"] = deep_model
    cfg["quick_think_llm"] = quick_model
    cfg["max_debate_rounds"] = debate_rounds
    cfg["max_risk_discuss_rounds"] = risk_rounds
    vendors = dict(cfg.get("data_vendors", {}))
    vendors["core_stock_apis"] = "mexc"
    vendors["technical_indicators"] = "mexc"
    cfg["data_vendors"] = vendors
    cfg["include_twitter"] = True
    return cfg


def coin_instrument_context(coin) -> str:
    """Instrument identity for a coin Yahoo has never heard of.

    resolve_instrument_context() looks the ticker up on yfinance, which returns
    nothing for a brand-new MEXC listing. MEXC's own metadata is strictly better
    here, so it is passed to the graph directly.
    """
    contract = f" Contract address: {coin.contract}." if coin.contract else ""
    return (
        f"The ticker {coin.base} refers to {coin.name}, a crypto asset trading on "
        f"MEXC as the spot pair {coin.symbol}. It was first traded on MEXC on "
        f"{coin.listed_date} ({coin.age_days} days ago), so it has almost no price "
        f"history and no company fundamentals.{contract} Treat it as a newly listed "
        f"crypto asset rather than a company, and do not infer a business, revenue, "
        f"or filings for it."
    )


def verdict_key(symbol: str, date: str) -> str:
    """Session-state key so each coin/date verdict survives analyzing another coin."""
    return f"verdict:{symbol}:{date}"


def verdict_label(signal: str | None) -> str:
    """Render a signal as its table chip."""
    return {"BUY": "▲ BUY", "SELL": "▼ SELL", "HOLD": "■ HOLD"}.get(
        (signal or "").strip().upper(), "—"
    )


def _fmt_volume(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}k"
    return f"${value:.0f}"


def row_cells(coin) -> dict:
    """Pre-formatted display strings for one table row."""
    # Sub-cent coins need every digit; trailing zeros are noise at this scale.
    price = f"{coin.price:.8f}".rstrip("0") or "0"
    return {
        "symbol": coin.base,
        "name": coin.name,
        "listed": coin.listed_date,
        "age": f"{coin.age_days}d",
        "price": price,
        "change": f"{coin.change_pct:+.2f}%",
        "volume": _fmt_volume(coin.quote_volume),
    }


def status_caption(result) -> str:
    """One line describing sweep coverage. Never hides what could not be checked."""
    parts = [f"{result.scanned} MEXC USDT pairs scanned"]
    if result.unresolved:
        parts.append(f"{result.unresolved} could not be checked (rate-limited)")
    if result.hidden_by_volume:
        parts.append(f"{result.hidden_by_volume} hidden by the volume floor")
    if result.stale:
        parts.append("data is STALE — refresh failed, showing the last good sweep")
    elif result.fetched_at:
        age_min = max(0, int((time.time() - result.fetched_at) / 60))
        parts.append(f"data {age_min} min old")
    return " · ".join(parts)
