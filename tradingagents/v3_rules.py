"""THE V3 RULES — one implementation of every rule Backtest v3 trades by.

Spec: docs/superpowers/specs/2026-10-22-backtest-v3-design.md (operator, Oct
22, 2026: "i want to do backtest v3 where you will create the strategy for
the research you made"). The engine (`v3_engine`) uses these now, and the
runner's v3 practice rooms will use the same functions (Part 5), so a v3
backtest and its practice room can never fill, size or trail by two rules.

All pure. Times are epoch ms. A POINT is one of Gate's minutes, or a 5-minute
bar where its archive has a hole (`backtest_report.fine_bars`); point
sequences may be lists or numpy arrays.
"""
from __future__ import annotations

import bisect

RISK_USD = 1.0      # lost when a stop is hit; the v3 page's risk box rescales it
ATR_N = 20
TRAIL_ATR = 3.0     # trailing stop = 3 x ATR(20) of the strategy's timeframe
LIQ_CEILING = 0.8   # auto_trader.STOP_LIQ_CEILING, held equal by a test


def atr(high, low, close, n: int = ATR_N) -> list:
    """The average true range of the last `n` candles; None until `n` exist."""
    out: list = [None] * len(close)
    trs: list = []
    window = 0.0
    for i in range(len(close)):
        prev = close[i - 1] if i else close[i]
        tr = max(high[i] - low[i], abs(high[i] - prev), abs(low[i] - prev))
        trs.append(tr)
        window += tr
        if i >= n:
            window -= trs[i - n]
        if i >= n - 1:
            out[i] = window / n
    return out


def sma(close, n: int) -> list:
    """The average of the last `n` closes; None until `n` exist."""
    out: list = [None] * len(close)
    total = 0.0
    for i, c in enumerate(close):
        total += c
        if i >= n:
            total -= close[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def _span(t_ms, start_ms: int, end_ms: int) -> tuple[int, int]:
    return bisect.bisect_left(t_ms, int(start_ms)), bisect.bisect_left(t_ms, int(end_ms))


def limit_fill(side: int, limit_px: float, t_ms, hi, lo,
               start_ms: int, end_ms: int) -> int | None:
    """The first point in [start_ms, end_ms) whose price traded THROUGH a
    waiting order: a buy when the low is strictly below the limit, a sell
    when the high is strictly above. A touch is not a fill — the queue is
    not modelled, so v3 assumes the back of it. None = never filled."""
    a, b = _span(t_ms, start_ms, end_ms)
    for k in range(a, b):
        if (side == 1 and lo[k] < limit_px) or (side == -1 and hi[k] > limit_px):
            return int(t_ms[k])
    return None


def stop_fill(side: int, stop: float, hi: float, lo: float) -> float:
    """Where a stop fills in a point that reached it: at the stop, or — when
    the whole point traded beyond it (the price jumped past) — at the best
    price that point traded. Never a price that did not trade."""
    return min(stop, hi) if side == 1 else max(stop, lo)


def safe_leverage(stop_frac: float, mmr: float, max_lev: int, min_lev: int = 1,
                  ceiling: float = LIQ_CEILING) -> int | None:
    """The highest whole leverage whose stop sits inside `ceiling` of the
    liquidation distance (1/leverage - maintenance rate); None when even the
    lowest leverage cannot keep the stop safe."""
    for lev in range(int(max_lev), int(min_lev) - 1, -1):
        if stop_frac < ceiling * (1.0 / lev - mmr):
            return lev
    return None


def risk_size(risk_usd: float, entry_px: float, stop_px: float, *, contract_size: float,
              min_vol: int, mmr: float, max_lev: int, min_lev: int = 1,
              ceiling: float = LIQ_CEILING) -> dict | None:
    """The trade that loses `risk_usd` when its stop is hit, in whole lots, at
    the highest safe leverage — or None (no safe leverage, or under one lot)."""
    if entry_px <= 0 or contract_size <= 0:
        return None
    stop_frac = abs(entry_px - stop_px) / entry_px
    if stop_frac <= 0:
        return None
    lev = safe_leverage(stop_frac, mmr, max_lev, min_lev, ceiling)
    if lev is None:
        return None
    # the allowance keeps 49.999999 lots (float division) from becoming 49
    contracts = int(risk_usd / stop_frac / (contract_size * entry_px) + 1e-9)
    if contracts < max(1, int(min_vol)):
        return None
    notional = contracts * contract_size * entry_px
    return {"contracts": contracts, "notional": notional, "leverage": lev,
            "margin": notional / lev, "stop_frac": stop_frac,
            "risk_usd": notional * stop_frac}


def trail_walk(side: int, stop: float, dist: float, t_ms, hi, lo,
               start_ms: int, end_ms: int) -> tuple[int | None, float]:
    """Walk the points in [start_ms, end_ms) with a trailing stop: each point
    is checked against the stop FIRST (its high and low have no order, so the
    worse is assumed), then the stop moves `dist` behind that point's extreme
    and is never loosened. Returns (the exit point and its fill price,
    `stop_fill`) or (None, the stop carried forward)."""
    a, b = _span(t_ms, start_ms, end_ms)
    for k in range(a, b):
        if side == 1:
            if lo[k] <= stop:
                return int(t_ms[k]), stop_fill(1, stop, hi[k], lo[k])
            stop = max(stop, hi[k] - dist)
        else:
            if hi[k] >= stop:
                return int(t_ms[k]), stop_fill(-1, stop, hi[k], lo[k])
            stop = min(stop, lo[k] + dist)
    return None, stop


def funding_paid(f_ms, f_rate, f_cyc, side: int, entry_ms: int,
                 exit_ms: int) -> tuple[float, bool]:
    """Funding over a hold as a fraction of notional PAID (a credit is
    negative; a positive rate means longs pay): every settlement in
    (entry_ms, exit_ms] at its own rate. `f_ms`/`f_rate`/`f_cyc` are the
    settlement history oldest first, in the arrays `auto_trader.funding_day_at`
    reads. The history answers from one cycle before its first settlement;
    any part of the hold before that pays the average known rate per cycle,
    and says so (`estimated`). No history is never a measured zero."""
    if not len(f_ms):
        return 0.0, True
    a = bisect.bisect_right(f_ms, int(entry_ms))
    b = bisect.bisect_right(f_ms, int(exit_ms))
    paid = side * sum(float(x) for x in f_rate[a:b])
    cycle_ms = (float(f_cyc[0]) or 8.0) * 3_600_000
    covered_from = int(f_ms[0]) - cycle_ms
    if int(entry_ms) >= covered_from:
        return paid, False
    avg = sum(float(x) for x in f_rate) / len(f_rate)
    uncovered = min(int(exit_ms), covered_from) - int(entry_ms)
    return paid + side * avg * (uncovered / cycle_ms), True
