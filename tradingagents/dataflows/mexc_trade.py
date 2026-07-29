"""Signed MEXC spot trading client.

Separate from ``mexc.py`` on purpose: that module is keyless market data, safe to
call anywhere. Everything here spends real money, so it lives behind its own
import, its own credentials, and an explicit ``dry_run`` switch.

Credentials come from ``MEXC_API_KEY`` / ``MEXC_API_SECRET`` in the environment
and are never accepted as arguments — a key pasted into a call site ends up in
tracebacks, logs and shell history. Create the key with spot trading enabled,
withdrawals disabled, and an IP allowlist: a trade-only key that leaks can lose
value on bad trades, but it cannot move funds off the exchange.

Signing follows MEXC's documented scheme: HMAC-SHA256 of the exact query string,
lowercase hex, with the key in the ``X-MEXC-APIKEY`` header.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from tradingagents.dataflows.mexc import resolve_host

logger = logging.getLogger(__name__)

# MEXC rejects spot orders below 1 USDT of notional value.
MIN_QUOTE_USD = 1.0
_TIMEOUT = 20.0
_RECV_WINDOW_MS = 10_000
_UA = "tradingagents/0.3 (+https://github.com/TauricResearch/TradingAgents)"


class MexcTradeError(RuntimeError):
    """A trading request could not be made or was rejected by the exchange."""


def credentials() -> tuple[str | None, str | None]:
    """API key and secret from the environment, or ``(None, None)``."""
    key = os.getenv("MEXC_API_KEY", "").strip() or None
    secret = os.getenv("MEXC_API_SECRET", "").strip() or None
    return key, secret


def has_credentials() -> bool:
    return all(credentials())


def sign(params: dict, secret: str) -> tuple[str, str]:
    """Return ``(query_string, signature)`` for ``params``.

    The signed string and the transmitted string must be byte-identical, so the
    query is built once here and reused rather than re-encoded by the caller.
    Insertion order is preserved for the same reason.
    """
    ordered = {k: v for k, v in params.items() if k != "signature" and v is not None}
    query = urllib.parse.urlencode(ordered)
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query, signature


def _open(request):                      # separated so tests can patch the transport
    return urllib.request.urlopen(request, timeout=_TIMEOUT)


def _send(method: str, url: str, headers: dict, timeout: float):
    request = urllib.request.Request(url, headers=headers, method=method)
    try:
        with _open(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        # Surface the exchange's own message: "Signature for this request is not
        # valid" and "Oversold" need completely different fixes.
        raise MexcTradeError(f"MEXC HTTP {exc.code}: {body}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise MexcTradeError(f"{type(exc).__name__}: {exc}") from exc


def _signed(method: str, path: str, params: dict):
    """Perform a signed request and return the decoded response."""
    key, secret = credentials()
    if not key or not secret:
        raise MexcTradeError(
            "MEXC API credentials missing. Set MEXC_API_KEY and MEXC_API_SECRET "
            "in .env (spot trading only, withdrawals disabled)."
        )
    payload = {**params, "recvWindow": _RECV_WINDOW_MS,
               "timestamp": int(time.time() * 1000)}
    query, signature = sign(payload, secret)
    url = f"https://{resolve_host()}{path}?{query}&signature={signature}"
    headers = {"X-MEXC-APIKEY": key, "User-Agent": _UA,
               "Content-Type": "application/json"}
    return _send(method, url, headers, _TIMEOUT)


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def balances() -> dict:
    """Non-zero free balances, keyed by asset."""
    data = _signed("GET", "/api/v3/account", {})
    rows = data.get("balances", []) if isinstance(data, dict) else []
    out = {}
    for row in rows:
        free = _as_float(row.get("free"))
        if row.get("asset") and free > 0:
            out[row["asset"]] = free
    return out


def usdt_balance() -> float:
    return balances().get("USDT", 0.0)


def _fill_from(response: dict, quote_hint: float = 0.0) -> dict:
    qty = _as_float(response.get("executedQty"))
    quote = _as_float(response.get("cummulativeQuoteQty"), quote_hint)
    return {
        "order_id": str(response.get("orderId", "")),
        "qty": qty,
        "spent": quote,
        "received": quote,
        "price": (quote / qty) if qty else 0.0,
        "dry_run": False,
    }


def market_buy(symbol: str, quote_usd: float, *, dry_run: bool = False) -> dict:
    """Spend ``quote_usd`` USDT on ``symbol`` at market.

    Uses ``quoteOrderQty`` so the spend is exact and the quantity is whatever that
    buys — the only sane shape for a coin whose price is unknown seconds after
    listing. Rejects sub-minimum amounts before spending a request on them.
    """
    if quote_usd <= 0:
        raise MexcTradeError("Order amount must be positive.")
    if quote_usd < MIN_QUOTE_USD:
        raise MexcTradeError(
            f"Order of ${quote_usd:.2f} is below the exchange minimum of "
            f"${MIN_QUOTE_USD:.2f}."
        )
    if dry_run:
        logger.info("DRY RUN buy %s for $%.2f", symbol, quote_usd)
        return {"order_id": "dry-run", "qty": 0.0, "spent": quote_usd,
                "received": quote_usd, "price": 0.0, "dry_run": True}

    response = _signed("POST", "/api/v3/order", {
        "symbol": symbol, "side": "BUY", "type": "MARKET",
        # Rounded to cents, not trimmed: stripping trailing zeros turned "3.00"
        # into "3", and there is no reason to reshape a value the exchange accepts.
        "quoteOrderQty": str(round(quote_usd, 2)),
    })
    fill = _fill_from(response, quote_usd)
    logger.info("Bought %s: qty=%s spent=%.4f price=%.10g",
                symbol, fill["qty"], fill["spent"], fill["price"])
    return fill


def market_sell(symbol: str, qty: float, *, dry_run: bool = False) -> dict:
    """Sell ``qty`` of the base asset at market."""
    if qty <= 0:
        raise MexcTradeError("Sell quantity must be positive.")
    if dry_run:
        logger.info("DRY RUN sell %s qty=%s", symbol, qty)
        return {"order_id": "dry-run", "qty": qty, "spent": 0.0,
                "received": 0.0, "price": 0.0, "dry_run": True}

    response = _signed("POST", "/api/v3/order", {
        "symbol": symbol, "side": "SELL", "type": "MARKET",
        "quantity": f"{qty:.8f}".rstrip("0").rstrip("."),
    })
    fill = _fill_from(response)
    logger.info("Sold %s: qty=%s received=%.4f", symbol, fill["qty"], fill["received"])
    return fill
