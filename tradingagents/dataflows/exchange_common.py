"""Arithmetic every exchange adapter shares (Oct 10, 2026, spec D3).

Moved out of `mexc_futures` unchanged so the Gate adapter answers the same
question the same way: what it costs to fill a size against a book, whether
an entry has already run away from its signal, and the headline funding
numbers from a settlement history. A second copy of any of these is the
thing this repo has paid for five times ("a second implementation of the
exit rules").
"""
from __future__ import annotations

from tradingagents.dataflows.exchange_errors import VenueError


def book_cost_from(book: dict, *, contract_size: float, notional_usd: float,
                   symbol: str, side: str = "buy") -> dict:
    """What it ACTUALLY costs to trade `notional_usd` of this contract,
    walked level by level through `book` ({"bids"/"asks": [[price,
    contracts], ...]}, best first).

    `side="buy"` walks the asks (MEXC's `book_cost` always did); "sell"
    walks the bids. Returns slippage/spread as FRACTIONS (0.0156 == 1.56%),
    the dict `mexc_futures.book_cost` has always returned.
    """
    asks, bids = book.get("asks") or [], book.get("bids") or []
    if not asks or not bids:
        raise VenueError(f"no order book for {symbol}")
    mid = (asks[0][0] + bids[0][0]) / 2.0
    size = float(contract_size or 0.0)
    if size <= 0 or mid <= 0:
        raise VenueError(f"cannot measure {symbol}: size={size} mid={mid}")
    levels = asks if side == "buy" else bids
    want = notional_usd / (size * mid)
    need, cost, got = want, 0.0, 0.0
    for px, vol in levels:
        take = min(need, vol)
        cost += take * px
        got += take
        need -= take
        if need <= 0:
            break
    if got <= 0:
        raise VenueError(f"empty book for {symbol}")
    avg = cost / got
    slippage = avg / mid - 1.0 if side == "buy" else mid / avg - 1.0
    exhausted = need > 0
    if exhausted:
        # The whole visible book cannot fill this order; the true cost is
        # worse than anything measurable here.
        far = levels[-1][0]
        slippage = max(slippage, far / mid - 1.0 if side == "buy"
                       else mid / far - 1.0)
    return {
        "symbol": symbol,
        "mid": mid,
        "spread": (asks[0][0] - bids[0][0]) / mid,
        "slippage": slippage,
        "book_exhausted": exhausted,
        "notional_tested": notional_usd,
    }


def chase_guard(entry_ref: float, live: float, max_chase_pct: float) -> tuple[bool, str]:
    """Refuse an entry that has already run away from the reference price.

    A signal computed a minute ago is not a licence to buy at any price.
    Returns (ok_to_enter, reason).
    """
    if entry_ref <= 0 or live <= 0:
        return False, "no reference price"
    drift = (live / entry_ref - 1) * 100
    if drift > max_chase_pct:
        return False, (f"price ran {drift:+.2f}% past the reference "
                       f"(limit {max_chase_pct:.2f}%)")
    return True, f"drift {drift:+.2f}% within {max_chase_pct:.2f}%"


def funding_summary_from(hist: list, symbol: str) -> dict:
    """Headline funding numbers for a contract, from the long side, given
    its settlement history ([{"settle_ms", "rate", "cycle_h"}, ...])."""
    if not hist:
        return {"symbol": symbol, "settlements": 0, "available": False}
    rates = [h["rate"] for h in hist]
    span_days = (hist[-1]["settle_ms"] - hist[0]["settle_ms"]) / 86400_000
    cycle = hist[0]["cycle_h"] or 8
    mean = sum(rates) / len(rates)
    return {
        "symbol": symbol, "available": True, "settlements": len(rates),
        "span_days": span_days, "cycle_h": cycle,
        "mean_rate": mean,
        "pct_positive": sum(1 for r in rates if r > 0) / len(rates) * 100,
        # A long's cumulative funding as a fraction of notional. Derived from
        # the actual settlement sum and elapsed span rather than the recorded
        # cycle: a contract's cycle can change mid-life (MEXC moved one from
        # 24h to 8h), so any single cycle value misstates the daily rate.
        "long_total": -sum(rates),
        "long_daily": (-sum(rates) / span_days) if span_days > 0 else 0.0,
        "long_annual": ((-sum(rates) / span_days) * 365) if span_days > 0 else 0.0,
    }
