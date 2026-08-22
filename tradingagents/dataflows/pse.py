"""Philippine Stock Exchange vendor — keyless daily data for PSE tickers.

Yahoo Finance carries no PSE data (``MER.PS``/``MER.PH`` return nothing, and a
bare ``MER`` there is Meren Energy, an unrelated company), so PSE names such as
Meralco were unanalysable. Two free, keyless sources cover the gap:

* **phisix** (``phisix-api3.appspot.com``) serves one JSON document per trading
  date, giving that session's closing price and volume. Iterating dates builds a
  daily history; non-trading days simply 404 and are skipped.
* **TradingView's public scanner** returns the latest session's true open, high,
  low, close and volume for ``PSE:<symbol>``.

LIMITATION, stated plainly because it changes what the technicals mean: the
historical feed carries **close and volume only** — no per-day open/high/low.
Those columns are filled with the close for past sessions (the latest session
uses TradingView's real values), so close-based indicators (SMA, EMA, MACD, RSI,
Bollinger) are sound while range-based ones (ATR, Stochastic) are not. The CSV
header says so, so an analyst reading the data knows.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd

logger = logging.getLogger(__name__)

_PHISIX = "https://phisix-api3.appspot.com/stocks/{symbol}.{date}.json"
_PHISIX_NOW = "https://phisix-api3.appspot.com/stocks/{symbol}.json"
_TRADINGVIEW = "https://scanner.tradingview.com/philippines/scan"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; tradingagents/0.3)"}
_TIMEOUT = 15.0
# phisix answers in ~200ms; the exchange trades ~250 sessions a year, so a
# year of history is ~250 small requests. Eight at a time keeps a 30-day
# window near a second without hammering a free community service.
_MAX_WORKERS = 8
# Hard ceiling on how far back a single request will walk, so a careless
# start_date cannot fire thousands of requests at a free endpoint.
MAX_LOOKBACK_DAYS = 400


class PseUnavailable(RuntimeError):
    """Raised when no PSE data could be read for a symbol."""


def normalize_symbol(symbol: str) -> str:
    """``MER.PS`` / ``mer.ph`` / ``MER`` -> ``MER`` (PSE tickers carry no suffix)."""
    sym = (symbol or "").strip().upper()
    for suffix in (".PS", ".PH", ".PSE"):
        if sym.endswith(suffix):
            return sym[: -len(suffix)]
    return sym


def _get_json(url: str):
    with urlopen(Request(url, headers=_UA), timeout=_TIMEOUT) as resp:
        return json.load(resp)


def _close_on(symbol: str, day: str):
    """``(date, close, volume)`` for one session, or None when it did not trade."""
    try:
        payload = _get_json(_PHISIX.format(symbol=symbol, date=day))
        row = (payload.get("stocks") or [])[0]
        return day, float(row["price"]["amount"]), float(row.get("volume") or 0.0)
    except HTTPError:
        return None                       # weekend / holiday / no session
    except (OSError, ValueError, KeyError, IndexError) as exc:
        logger.debug("PSE %s %s unavailable: %s", symbol, day, exc)
        return None


def latest_quote(symbol: str) -> dict:
    """Latest session's real OHLCV from TradingView's public scanner.

    Returns ``{}`` when the scanner cannot be reached — callers fall back to the
    close-only history rather than failing the run.
    """
    sym = normalize_symbol(symbol)
    body = json.dumps({
        "symbols": {"tickers": [f"PSE:{sym}"], "query": {"types": []}},
        "columns": ["close", "open", "high", "low", "volume", "change"],
    }).encode()
    try:
        req = Request(_TRADINGVIEW, data=body,
                      headers={**_UA, "Content-Type": "application/json"})
        with urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.load(resp)
        close, open_, high, low, volume, change = data["data"][0]["d"]
        return {"close": close, "open": open_, "high": high, "low": low,
                "volume": volume, "change_pct": change}
    except (OSError, ValueError, KeyError, IndexError) as exc:
        logger.warning("PSE scanner quote failed for %s: %s", sym, exc)
        return {}


def fetch_history(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Daily OHLCV frame for a PSE symbol over an inclusive date range.

    Open/high/low repeat the close for past sessions (see the module docstring);
    the final session uses TradingView's real values when reachable.
    """
    sym = normalize_symbol(symbol)
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    if end < start:
        raise PseUnavailable(f"end_date {end_date} precedes start_date {start_date}")
    span = (end - start).days
    if span > MAX_LOOKBACK_DAYS:
        start = end - timedelta(days=MAX_LOOKBACK_DAYS)

    days = [(start + timedelta(days=i)).isoformat()
            for i in range((end - start).days + 1)]
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        rows = [r for r in pool.map(lambda d: _close_on(sym, d), days) if r]

    if not rows:
        raise PseUnavailable(
            f"No PSE sessions found for {sym} between {start_date} and {end_date}. "
            f"Check the ticker — PSE symbols carry no exchange suffix (e.g. MER).")

    rows.sort()
    frame = pd.DataFrame(rows, columns=["Date", "Close", "Volume"])
    frame["Open"] = frame["Close"]
    frame["High"] = frame["Close"]
    frame["Low"] = frame["Close"]

    quote = latest_quote(sym)
    if quote and quote.get("close"):
        # Give the newest bar its true range; the rest stay close-only.
        last = frame.index[-1]
        frame.loc[last, ["Open", "High", "Low", "Close", "Volume"]] = [
            quote["open"], quote["high"], quote["low"], quote["close"],
            quote["volume"]]

    frame["Date"] = pd.to_datetime(frame["Date"])
    return frame[["Date", "Open", "High", "Low", "Close", "Volume"]]


_OHLC_NOTE = (
    "# NOTE: the free PSE feed publishes CLOSE and VOLUME only. Open/High/Low "
    "repeat the close for past sessions (the latest session carries real "
    "values), so close-based indicators (SMA, EMA, MACD, RSI) are reliable "
    "while range-based ones (ATR, Stochastic) are NOT meaningful here.\n"
)


def get_pse_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """Vendor entry point for ``get_stock_data`` — annotated CSV, like yfinance's."""
    sym = normalize_symbol(symbol)
    frame = fetch_history(sym, start_date, end_date)
    out = frame.copy()
    out["Date"] = out["Date"].dt.strftime("%Y-%m-%d")
    header = (
        f"# PSE daily data for {sym} (Philippine Stock Exchange, PHP) "
        f"from {start_date} to {end_date}\n"
        f"# Total records: {len(out)}\n"
        f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{_OHLC_NOTE}\n"
    )
    return header + out.to_csv(index=False)


def get_pse_indicators(symbol: str, indicator: str, curr_date: str,
                       look_back_days: int) -> str:
    """Vendor entry point for ``get_indicators``, computed off PSE closes."""
    import stockstats

    sym = normalize_symbol(symbol)
    end = datetime.strptime(curr_date, "%Y-%m-%d").date()
    # Indicators need a run-up of sessions before the window to warm up, and
    # the PSE trades ~5 days in 7, so the fetch reaches back further than the
    # requested window.
    start = end - timedelta(days=int(look_back_days * 2) + 60)
    frame = fetch_history(sym, start.isoformat(), end.isoformat())

    dates = frame["Date"].dt.strftime("%Y-%m-%d").tolist()
    stats = stockstats.wrap(frame.copy())
    values = stats[indicator].tolist()

    window_start = end - timedelta(days=look_back_days)
    lines = [
        f"{day}: {value:.4f}" if pd.notna(value) else f"{day}: n/a"
        for day, value in zip(dates, values, strict=False)
        if window_start.isoformat() <= day <= curr_date
    ]
    body = "\n".join(lines) if lines else "No values in the requested window."
    return (f"## {indicator} for {sym} (PSE, PHP), "
            f"{window_start.isoformat()} to {curr_date}:\n\n{body}\n\n{_OHLC_NOTE}")
