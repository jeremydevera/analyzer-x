"""THE V3 FILTERS — four rules laid ON TOP of every family, as a mask on its
signals (decisions doc docs/superpowers/specs/2026-10-23-backtest-v3-part2-
decisions.md, "The filters"; spec #5, #6, #7 and #9).

Each is judged at a candle's ORDER MINUTE — the close of the signal candle,
when its waiting order would go in — and reads only what was known by then:

* ``btc_mood``: a crypto alt-coin's longs only while BTC's last CLOSED daily
  candle is above its 50-day average (BTC itself, and contracts that are not
  crypto, are not filtered).
* ``busy_hours``: a stock token's orders only 9:30am-4:00pm New York on a
  weekday (`daytime_rule.in_market_hours`); every other contract's, never on
  a Saturday or Sunday (UTC).
* ``funding_side``: no long when the last settled funding rate is among the
  top 10% of the coin's own settlements of the 30 days before it, no short
  among the bottom 10% (ties count against the rate). Where the history does
  not cover those 30 days the filter cannot judge: the signal passes and is
  counted `funding_unknown`.
* ``funding_minutes``: no order within 5 minutes either side of a funding
  settlement — the recorded ones where the history reaches, else the
  contract's settlement cycle from 00:00 UTC, counted `settle_by_cycle`.

`masks` answers every candle at once, so random entries can be drawn from
the candles a filter lets through (`v3_random`).
"""
from __future__ import annotations

import bisect

from tradingagents import v3_universe as vu

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
SIDE_SHARE = 0.10
SIDE_DAYS = 30
SETTLE_GAP_MS = 5 * 60_000
NAMES = ("none", "btc_mood", "busy_hours", "funding_side", "funding_minutes")


def _arrays(funding) -> tuple[list[int], list[float], list[float]]:
    f = funding or []
    return ([int(x["settle_ms"]) for x in f], [float(x["rate"]) for x in f],
            [float(x.get("cycle_h") or 8) for x in f])


def btc_mood(sym: str, kind: str, order_ms, plan: dict):
    n = len(order_ms)
    if sym == vu.BTC or kind != "crypto":
        return [True] * n, [True] * n, [""] * n
    up = vu.mood_at(plan, order_ms)
    return ([u is not False for u in up], [True] * n,
            ["mood_unknown" if u is None else "" for u in up])


def busy_hours(kind: str, order_ms):
    from tradingagents import daytime_rule

    if kind == "stocks":
        ok = [daytime_rule.in_market_hours(ms / 1000) for ms in order_ms]
    else:
        ok = [vu.weekday(ms) < 5 for ms in order_ms]
    return ok, list(ok), [""] * len(order_ms)


def funding_side(order_ms, funding):
    f_ms, f_rate, f_cyc = _arrays(funding)
    long_ok, short_ok, flag = [], [], []
    for ms in order_ms:
        ms = int(ms)
        covered = (bool(f_ms) and f_ms[0] - f_cyc[0] * HOUR_MS <= ms - SIDE_DAYS * DAY_MS
                   and ms <= f_ms[-1] + f_cyc[-1] * HOUR_MS)
        hi = bisect.bisect_right(f_ms, ms) if covered else 0
        window = f_rate[bisect.bisect_right(f_ms, ms - SIDE_DAYS * DAY_MS):hi] if hi else []
        if not window:
            long_ok.append(True)
            short_ok.append(True)
            flag.append("funding_unknown")
            continue
        last = f_rate[hi - 1]
        cut = SIDE_SHARE * len(window)
        long_ok.append(sum(1 for r in window if r >= last) > cut)
        short_ok.append(sum(1 for r in window if r <= last) > cut)
        flag.append("")
    return long_ok, short_ok, flag


def funding_minutes(order_ms, funding, cycle_h: float):
    f_ms, _rate, _cyc = _arrays(funding)
    cycle = float(cycle_h or 8) * HOUR_MS
    ok, flag = [], []
    for ms in order_ms:
        ms = int(ms)
        if f_ms and f_ms[0] - SETTLE_GAP_MS <= ms <= f_ms[-1] + SETTLE_GAP_MS:
            k = bisect.bisect_left(f_ms, ms - SETTLE_GAP_MS)
            ok.append(not (k < len(f_ms) and f_ms[k] <= ms + SETTLE_GAP_MS))
            flag.append("")
        else:
            phase = ms % cycle
            ok.append(SETTLE_GAP_MS < phase < cycle - SETTLE_GAP_MS)
            flag.append("settle_by_cycle")
    return ok, list(ok), flag


def masks(name: str, *, sym: str, kind: str, order_ms, funding=None, cycle_h: float = 8,
          plan: dict | None = None) -> tuple[list[bool], list[bool], list[str]]:
    """(longs allowed, shorts allowed, a count name or "" per candle) for one
    filter over every candle's order minute."""
    n = len(order_ms)
    if name == "none":
        return [True] * n, [True] * n, [""] * n
    if name == "btc_mood":
        return btc_mood(sym, kind, order_ms, plan)
    if name == "busy_hours":
        return busy_hours(kind, order_ms)
    if name == "funding_side":
        return funding_side(order_ms, funding)
    if name == "funding_minutes":
        return funding_minutes(order_ms, funding, cycle_h)
    raise ValueError(f"unknown filter {name!r}")
