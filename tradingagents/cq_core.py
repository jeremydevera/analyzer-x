"""THE CONFLUENCE SEARCH (Prompt 1, Oct 21, 2026): rounds, scores and picks.

No market data here: the GitHub shard (.github/scripts/cq_shard.py) hands
`search` an `evaluate` that measures candidates with the nightly grid's own
engine, and this module decides which candidates to try and which is the
pick. Design: docs/superpowers/specs/2026-10-21-confluence-research-design.md.

A candidate is (entry, stop/target). Each measured candidate has three
stretches, by the day its trades CLOSED: tuning (the oldest days), check, and
test (the newest). The search reads the tuning days to choose and the check
days to judge, and NEVER the test days, so they stay a test (a test holds
that changing them changes nothing here).

* score: the worst-case win rate on the tuning days - the Wilson lower bound
  at z 1.645 (the low end of a 90% range); a candidate needs `min_trades`
  tuning trades to have one;
* rounds: round 1 is a seeded random draw; each later round tries the
  neighbours of the best `top` so far, spread over the payouts (one setting,
  one confirmation, the next stop/target of the same payout), plus `fresh`
  random draws; never a candidate twice;
* the pick per payout: of every round's best-by-tuning candidate (the
  champion after each round), the one with the best check-days worst-case
  win rate; the final pick: the payout whose pick has the best check-days
  worst-case profit per trade in R;
* early stop: `patience` rounds in a row with no payout's pick improving on
  its check days, or no untried candidate left.
"""
from __future__ import annotations

import hashlib
import math
import random
import time
from typing import NamedTuple

Z90 = 1.6448536269514722          # one side of a two-sided 90% range
PAYOUTS = (2, 3, 4, 5)
MIN_TUNE_TRADES = 20


class Part(NamedTuple):
    trades: int
    wins: int
    profit: float      # $ at the run's base margin, after every cost
    cost: float        # the round trips those trades paid, summed, % of the position


class Stats(NamedTuple):
    tun: Part
    chk: Part
    tst: Part


EMPTY = Part(0, 0, 0.0, 0.0)


def minus(a: Part, b: Part) -> Part:
    return Part(a.trades - b.trades, a.wins - b.wins, round(a.profit - b.profit, 2),
                round(a.cost - b.cost, 6))


def wilson_low(wins: int, trades: int, z: float = Z90) -> float:
    """The worst-case win rate: the low end of the Wilson range (0 with no
    trade). 3 wins of 3 is 52.6%, 90 of 200 is 39.3%."""
    if trades <= 0:
        return 0.0
    p = wins / trades
    z2 = z * z
    centre = p + z2 / (2 * trades)
    spread = z * math.sqrt(p * (1 - p) / trades + z2 / (4 * trades * trades))
    return max(0.0, (centre - spread) / (1 + z2 / trades))


def payout_of(sl: float, tp: float, c: float) -> float:
    """What one win pays in losses after a round trip `c` (fractions):
    (target - cost) / (stop + cost)."""
    return (tp - c) / (sl + c)


def bucket(k: float) -> int | None:
    """2:1 (2 to 3), 3:1 (3 to 4), 4:1 (4 to 5), 5:1 (5 or more); below 2:1 is
    never a candidate."""
    if not k >= 2.0:
        return None
    return min(5, int(math.floor(k + 1e-12)))


def worst_r(part: Part, sl: float, tp: float, c_usual: float) -> float | None:
    """The worst-case profit per trade in R (one R = the stop plus the round
    trip): worst-case win rate x (payout + 1) - 1, the payout on the round
    trip those trades PAID (the coin's usual one when nothing is on record).
    None with no trade."""
    if part.trades <= 0:
        return None
    c = (part.cost / part.trades / 100.0) if part.cost > 0 else c_usual
    return wilson_low(part.wins, part.trades) * (payout_of(sl, tp, c) + 1.0) - 1.0


def seed_of(*parts) -> int:
    """A search's seed: a hash of its coin, timeframe and version, so a run
    repeats exactly and two coins never share a draw."""
    d = hashlib.blake2b("|".join(str(p) for p in parts).encode(), digest_size=8).digest()
    return int.from_bytes(d, "big")


def _spread(best: dict, top: int) -> list:
    """The `top` best so far, one payout at a time in turn: every payout keeps
    searching around its own best (2:1 wins more often by nature and would
    otherwise take every place)."""
    out, j = [], 0
    while len(out) < top and any(j < len(best[k]) for k in PAYOUTS):
        for k in PAYOUTS:
            if j < len(best[k]) and len(out) < top:
                out.append(best[k][j])
        j += 1
    return out


def search(n_entries: int, barriers: list, buckets: list, evaluate, *, seed: int,
           neighbours_of, c_usual: float, round_size: int = 500, max_rounds: int = 100,
           patience: int = 10, top: int = 25, fresh: float = 0.2, keep: int = 10,
           min_trades: int = MIN_TUNE_TRADES, deadline: float | None = None,
           clock=time.time) -> dict:
    """Search (entry, stop/target) candidates. `barriers[b]` = (sl, tp)
    fractions, `buckets[b]` its payout class; `evaluate([(e, b), ...])` ->
    {(e, b): Stats or None (no trade)}; `neighbours_of(e)` -> entry indices one
    step away. Returns the rounds (each: candidates tried, its best `keep` by
    tuning score, each payout's champion), every payout's pick, the final
    pick (payout, candidate), the champions, why it stopped, and the Stats of
    every candidate it names."""
    nb = len(barriers)
    space = n_entries * nb
    rng = random.Random(seed)
    tried: dict = {}
    lists = {k: sorted((b for b in range(nb) if buckets[b] == k), key=lambda b: barriers[b])
             for k in PAYOUTS}
    pos = {b: (k, j) for k, bs in lists.items() for j, b in enumerate(bs)}

    def bar_nb(b):
        k, j = pos[b]
        return [lists[k][x] for x in (j - 1, j + 1) if 0 <= x < len(lists[k])]

    def score(st):
        if st is None or st.tun.trades < min_trades:
            return None
        return wilson_low(st.tun.wins, st.tun.trades)

    def chk(st):
        return wilson_low(st.chk.wins, st.chk.trades)

    def draw(n, avoid):
        free = space - len(tried) - len(avoid)
        if n <= 0 or free <= 0:
            return []
        if free <= 4 * n:
            pool = [(x // nb, x % nb) for x in range(space)]
            pool = [cd for cd in pool if cd not in tried and cd not in avoid]
            rng.shuffle(pool)
            return pool[:n]
        out, got = [], set()
        while len(out) < n:
            x = rng.randrange(space)
            cd = (x // nb, x % nb)
            if cd in tried or cd in avoid or cd in got:
                continue
            got.add(cd)
            out.append(cd)
        return out

    best: dict = {k: [] for k in PAYOUTS}
    champ: dict = {}
    champions: dict = {k: [] for k in PAYOUTS}
    picks: dict = {}
    rounds: list = []
    stale, stop = 0, "max_rounds"
    for r in range(1, max_rounds + 1):
        if deadline is not None and clock() >= deadline:
            stop = "deadline"
            break
        if len(tried) >= space:
            stop = "exhausted"
            break
        if r == 1:
            cands = draw(round_size, set())
        else:
            want = round_size - int(round(round_size * fresh))
            cands, seen = [], set()
            for _sc, (e, b) in _spread(best, top):
                for cd in [(e2, b) for e2 in neighbours_of(e)] + [(e, b2) for b2 in bar_nb(b)]:
                    if cd in tried or cd in seen:
                        continue
                    seen.add(cd)
                    cands.append(cd)
                    if len(cands) >= want:
                        break
                if len(cands) >= want:
                    break
            cands += draw(round_size - len(cands), seen)
        if not cands:
            stop = "exhausted"
            break
        got = evaluate(cands)
        scored = []
        for cd in cands:
            st = got.get(cd)
            tried[cd] = st
            sc = score(st)
            if sc is not None:
                scored.append((sc, cd))
        scored.sort(key=lambda x: (-x[0], x[1]))
        for sc, cd in scored:
            best[buckets[cd[1]]].append((sc, cd))
        improved = False
        for k in PAYOUTS:
            best[k] = sorted(best[k], key=lambda x: (-x[0], x[1]))[:top]
            if not best[k]:
                continue
            c0 = best[k][0][1]
            champ[k] = c0
            if c0 not in champions[k]:
                champions[k].append(c0)
            if k not in picks or chk(tried[c0]) > chk(tried[picks[k]]):
                picks[k] = c0
                improved = True
        rounds.append({"n": r, "tried": len(cands), "best": [cd for _sc, cd in scored[:keep]],
                       "champ": dict(champ)})
        stale = 0 if improved else stale + 1
        if stale >= patience:
            stop = "patience"
            break
    ranked = []
    for k, cd in picks.items():
        sl, tp = barriers[cd[1]]
        w = worst_r(tried[cd].chk, sl, tp, c_usual)
        ranked.append((-(w if w is not None else -math.inf), k, cd))
    final = None
    if ranked:
        ranked.sort()
        final = (ranked[0][1], ranked[0][2])
    named = (set(picks.values()) | {cd for k in PAYOUTS for cd in champions[k]}
             | {cd for rd in rounds for cd in rd["best"]})
    return {"tried": len(tried), "space": space, "stop": stop, "rounds": rounds,
            "picks": picks, "final": final, "champions": champions,
            "stats": {cd: tried[cd] for cd in named}}
