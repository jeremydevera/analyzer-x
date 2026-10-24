"""RANDOM ENTRIES — the luck bar of the Backtest v3 proof test (decisions doc
docs/superpowers/specs/2026-10-23-backtest-v3-part2-decisions.md, "Random
entries"; spec Part 3).

For each combination and coin, `RUNS` seeded runs on the UNSEEN window. Each
run places, in every calendar month and on each side, as many entries as the
real run placed there — the orders it put in, filled or missed, by the month
of the minute each went in — on candles of that month drawn at random from
the ones the combination could have entered on (its universe months and
sides, its filter, its family's entry days), and is walked by the same
`v3_engine.walk` with the same exit, sizing and costs. An entry that lands
inside an open random trade is not taken (one position at a time), so a run
can trade fewer times than the real one; the proof compares profit PER
TRADE.

Reproducible on any machine: a run's seed is a hash of coin, timeframe,
family, filter and run number, and the draw uses only `random.Random.random`,
whose sequence Python keeps the same from version to version.
"""
from __future__ import annotations

import hashlib
import random

from tradingagents import v3_universe as vu

RUNS = 200


def seed_of(*parts) -> int:
    """A 64-bit seed from its parts, the same on every machine."""
    text = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(text, digest_size=8).digest(), "big")


def entries_by_month(walked: dict, t, bar_ms: int) -> dict[tuple[str, int], int]:
    """{(month, side): orders} of a real walk — its trades and its missed
    orders (rejected or never filled), by the month of the minute each order
    went in (the open of the candle after its signal)."""
    out: dict[tuple[str, int], int] = {}
    for x in list(walked["trades"]) + list(walked["missed"]):
        key = (vu.month_key(int(t[x["signal_bar"]]) + int(bar_ms)), int(x["side"]))
        out[key] = out.get(key, 0) + 1
    return out


def candidates(t, bar_ms: int, start: int, long_ok, short_ok) -> dict[tuple[str, int], list[int]]:
    """{(month, side): candle indices} a random entry may be drawn from: the
    walk's tradable signal candles (from `start` to the one before last, whose
    order goes in inside the window) where that side is allowed."""
    out: dict[tuple[str, int], list[int]] = {}
    for i in range(int(start), len(t) - 1):
        month = vu.month_key(int(t[i]) + int(bar_ms))
        for side, ok in ((1, long_ok), (-1, short_ok)):
            if ok[i]:
                out.setdefault((month, side), []).append(i)
    return out


def draw(n: int, wanted: dict, cands: dict, seed: int) -> tuple[list[int], int]:
    """One random run's signals: (dirs of length `n`, entries it could not
    place). Longs first, then shorts, month by month; a candle holds one side."""
    rng = random.Random(seed)
    dirs = [0] * n
    short_of = 0
    for month, side in sorted(wanted, key=lambda k: (k[0], -k[1])):
        pool = [i for i in cands.get((month, side), ()) if dirs[i] == 0]
        want = int(wanted[(month, side)])
        take = min(want, len(pool))
        short_of += want - take
        for k in range(take):                     # a partial Fisher-Yates shuffle
            j = k + int(rng.random() * (len(pool) - k))
            pool[k], pool[j] = pool[j], pool[k]
            dirs[pool[k]] = side
    return dirs, short_of
