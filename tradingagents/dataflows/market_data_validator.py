"""Deterministic market-data verification snapshot.

The market analyst is an LLM that can confabulate exact numbers — citing a
Bollinger band or a "historically validated bounce" that the underlying data
doesn't support (#830). This module computes a ground-truth snapshot (latest
OHLCV row on or before the analysis date, common indicators, recent closes)
the analyst is told to treat as the source of truth for any exact numeric
claim. Deterministic, no LLM involved.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
from stockstats import wrap

from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.stockstats_utils import load_ohlcv

# A fixed, common indicator set so the snapshot is the same shape every run.
DEFAULT_SNAPSHOT_INDICATORS: tuple[str, ...] = (
    "close_10_ema", "close_50_sma", "close_200_sma",
    "rsi", "boll", "boll_ub", "boll_lb",
    "macd", "macds", "macdh", "atr",
)


# How many days of history to request from vendors that need an explicit range.
# Matches the depth load_ohlcv keeps, so slow indicators (200 SMA) have input.
_FRAME_LOOKBACK_DAYS = 500


def _mexc_frame(symbol: str, curr_date: str) -> pd.DataFrame:
    from tradingagents.dataflows.mexc import get_mexc_ohlcv

    start = (pd.to_datetime(curr_date)
             - pd.Timedelta(days=_FRAME_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    return get_mexc_ohlcv(symbol, start, curr_date)


def _frame_loaders() -> dict:
    # Built per call so a patched load_ohlcv (tests) is picked up.
    return {"yfinance": load_ohlcv, "mexc": _mexc_frame}


def _load_frame(symbol: str, curr_date: str) -> pd.DataFrame:
    """OHLCV frame from the configured price vendor chain.

    ``get_stock_data`` routes through VENDOR_METHODS, but this path needs a
    DataFrame rather than a formatted string, so it dispatches on the same
    ``core_stock_apis`` setting instead of hardcoding Yahoo — otherwise the
    verification tool hard-fails for any instrument Yahoo does not carry, which
    is every newly listed MEXC coin. Vendors with no frame loader (alpha_vantage)
    fall back to load_ohlcv, preserving this module's original behavior.
    """
    from tradingagents.dataflows.config import get_config

    configured = str(get_config().get("data_vendors", {}).get("core_stock_apis", ""))
    chain = [v.strip() for v in configured.split(",")
             if v.strip() and v.strip() != "default"]
    loaders = _frame_loaders()

    last_no_data: NoMarketDataError | None = None
    for vendor in chain:
        loader = loaders.get(vendor)
        if loader is None:
            continue
        try:
            return loader(symbol, curr_date)
        except NoMarketDataError as exc:
            last_no_data = exc      # another configured vendor may have it
            continue
    if last_no_data is not None:
        raise last_no_data
    return load_ohlcv(symbol, curr_date)


def _verified_rows(symbol: str, curr_date: str) -> pd.DataFrame:
    """OHLCV on or before curr_date, date-sorted. Raises if nothing usable.

    The loader already normalizes the Date column and filters out look-ahead
    rows, but we re-apply the cutoff defensively — this is a verification path,
    so it must not trust its input to be pre-filtered.
    """
    data = _load_frame(symbol, curr_date)
    if data is None or data.empty:
        raise ValueError(f"No OHLCV data available for {symbol}.")

    df = data.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    df = df[df["Date"] <= pd.to_datetime(curr_date)].sort_values("Date")
    if df.empty:
        raise ValueError(f"No OHLCV rows on or before {curr_date} for {symbol}.")
    return df


def _fmt(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def build_verified_market_snapshot(
    symbol: str,
    curr_date: str,
    look_back_days: int = 30,
    indicators: Iterable[str] | None = None,
) -> str:
    """Render a ground-truth snapshot: latest OHLCV row, indicators, recent closes."""
    # `df` keeps the original capitalized OHLCV columns (Open/High/Low/Close/
    # Volume); stockstats `wrap()` lowercases columns and adds indicator
    # columns, so read raw prices from `df` and indicators from `stock_df`.
    df = _verified_rows(symbol, curr_date)
    stock_df = wrap(df.copy())

    selected = tuple(indicators or DEFAULT_SNAPSHOT_INDICATORS)
    indicator_values: dict[str, str] = {}
    for name in selected:
        try:
            stock_df[name]  # triggers stockstats calculation
            indicator_values[name] = _fmt(stock_df.iloc[-1][name])
        except Exception as exc:  # noqa: BLE001 — one bad indicator shouldn't sink the snapshot
            indicator_values[name] = f"N/A ({type(exc).__name__})"

    latest = df.iloc[-1]
    latest_date = _fmt(latest["Date"])
    window = max(1, min(int(look_back_days), 30))
    recent = df.tail(window)

    lines = [
        f"## Verified market data snapshot for {symbol.upper()}",
        "",
        f"- Requested analysis date: {curr_date}",
        f"- Latest trading row used: {latest_date}",
        "- Rows after the requested analysis date are excluded before verification.",
        "",
        "### Latest verified OHLCV row",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    for field in ("Open", "High", "Low", "Close", "Volume"):
        lines.append(f"| {field} | {_fmt(latest.get(field))} |")

    lines += ["", "### Verified technical indicators (latest row)", "",
              "| Indicator | Value |", "|---|---:|"]
    for name, value in indicator_values.items():
        lines.append(f"| {name} | {value} |")

    lines += ["", f"### Recent verified closes (last {len(recent)} rows)", "",
              "| Date | Close |", "|---|---:|"]
    for _, row in recent.iterrows():
        lines.append(f"| {_fmt(row['Date'])} | {_fmt(row.get('Close'))} |")

    lines += [
        "",
        "Use this snapshot as the source of truth for exact OHLCV, price-level, "
        "and indicator-value claims. If another tool output conflicts with it, "
        "flag the discrepancy rather than inventing a reconciled number. Do not "
        "claim historical validation, support/resistance bounces, or exact "
        "percentage moves unless directly supported by tool output with concrete "
        "dates and prices.",
    ]
    return "\n".join(lines)
