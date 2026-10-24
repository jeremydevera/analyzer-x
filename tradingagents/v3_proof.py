"""THE V3 PROOF TEST — choose a family's setting on the OLDER days, judge it on
the UNSEEN days against random entries, keep every verdict.

Spec: docs/superpowers/specs/2026-10-22-backtest-v3-design.md (Part 3, "The
proof test"); decisions: docs/superpowers/specs/2026-10-23-backtest-v3-part2-
decisions.md ("The proof test"). Pure: it reads what `v3_measure.measure_coin`
returned for each coin and decides nothing anywhere else.

1. CHOOSE, on the older walks only: the setting with the best profit per
   trade after costs, pooled over the coins (the walks only signal in a
   coin's member months), with at least MIN_CHOOSE older trades; a tie goes
   to the simplest (the first of the family's settings).
2. JUDGE the chosen setting on the unseen walks, pooled. It passes only when,
   in this order (the first that fails names the verdict):
   * ``profit`` — profit per trade after costs above 0;
   * ``random`` — profit per trade above BOTH the (1 - α/2) point of the
     pooled random runs' profit per trade, read off a normal curve fitted to
     them (mean + z x standard deviation: 200 runs cannot show a tail that
     far out by counting), and the best of the runs, its floor;
   * ``bootstrap`` — profit per trade - z x its day-clustered standard error
     above 0: BOOT_DRAWS seeded draws of the unseen trading days (a trade's
     day is the UTC day it closed), with replacement;
   * ``trades`` — at least MIN_UNSEEN unseen trades.
   α = ALPHA / every combination measured (`v3_families.combos()`, 70 —
   counted, never estimated) and z = Φ⁻¹(1 - α/2), 3.384.
3. Every verdict is kept, passed or failed, with its numbers.

A trade still open when a walk ends (`why` END: at the split for the older
walk, at the plan's end for the unseen one) counts, marked at that candle's
close and paying the market exit; the verdict says how many there were.
"""
from __future__ import annotations

import random
from statistics import NormalDist, fmean, median, stdev

from tradingagents import v3_families as vf, v3_random as vrn, v3_universe as vu

ALPHA = 0.05
MIN_CHOOSE = 30
MIN_UNSEEN = 300
BOOT_DRAWS = 2000
DAY_MS = 86_400_000
CHECKS = ("profit", "random", "bootstrap", "trades")
TRIED = len(vf.combos())
NOTES = {
    "busy_hours": ("No family's universe holds stock tokens, so only the no-weekend half of "
                   "busy hours can bite."),
    "btc_mood": "Only crypto alt-coins' longs are filtered; BTC and other contracts pass.",
}


def z_for(tried: int, alpha: float = ALPHA) -> float:
    """Φ⁻¹(1 - α/2) for α = `alpha` / `tried`."""
    return NormalDist().inv_cdf(1 - alpha / tried / 2)


Z = z_for(TRIED)


def summary(rows) -> dict:
    """Pooled compact trade rows ([signal_ms, entry_ms, exit_ms, side, pnl,
    why]) in the order they closed: the standard kit's figures."""
    from tradingagents.v3_page import worst_run

    rows = sorted(rows, key=lambda r: (int(r[2]), int(r[1])))
    pnls = [float(r[4]) for r in rows]
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    win_avg = sum(p for p in pnls if p > 0) / wins if wins else None
    loss_avg = -sum(p for p in pnls if p <= 0) / (n - wins) if n - wins else None
    worst, worst_n = worst_run(pnls)
    profit = sum(pnls)
    return {"trades": n, "wins": wins, "losses": n - wins,
            "win_rate": wins / n if n else None,
            "break_even": (loss_avg / (win_avg + loss_avg)
                           if win_avg is not None and loss_avg is not None else None),
            "profit": profit, "per_trade": profit / n if n else None,
            "worst_run_usd": worst, "worst_run_trades": worst_n,
            "open_at_end": sum(1 for r in rows if r[5] == "END")}


def choose(older: dict, order) -> tuple[str | None, dict]:
    """(the chosen setting or None, every setting's older figures)."""
    table, best = {}, None
    for key in order:
        rows = older.get(key, [])
        n, profit = len(rows), sum(float(r[4]) for r in rows)
        table[key] = {"trades": n, "profit": profit, "per_trade": profit / n if n else None,
                      "eligible": n >= MIN_CHOOSE}
        if n >= MIN_CHOOSE and (best is None or table[key]["per_trade"] > table[best]["per_trade"]):
            best = key
    return best, table


def pool_random(per_coin) -> list[tuple[int, float]]:
    """Run k pooled over the coins: (its trades, its profit), summed."""
    runs: list[list] | None = None
    for coin_runs in per_coin:
        if runs is None:
            runs = [[0, 0.0] for _ in coin_runs]
        if len(coin_runs) != len(runs):
            raise ValueError(f"a coin holds {len(coin_runs)} random runs, another {len(runs)}")
        for k, (n, p) in enumerate(coin_runs):
            runs[k][0] += int(n)
            runs[k][1] += float(p)
    return [(n, p) for n, p in runs or []]


def random_bar(runs, z: float = Z) -> dict | None:
    """The luck bar from the pooled runs (those that traded): the normal
    curve's (1 - α/2) point and the best run, whichever is higher. None
    when fewer than two runs traded."""
    ppt = [p / n for n, p in runs if n]
    if len(ppt) < 2:
        return None
    mean, sd, best = fmean(ppt), stdev(ppt), max(ppt)
    return {"runs": len(runs), "traded": len(ppt), "median": median(ppt), "mean": mean,
            "sd": sd, "best": best, "normal": mean + z * sd, "bar": max(mean + z * sd, best)}


def boot_se(rows, seed: int, draws: int = BOOT_DRAWS) -> tuple[float | None, int]:
    """(the day-clustered standard error of profit per trade, trading days):
    `draws` seeded draws of the days, with replacement. None under 2 days."""
    days: dict[int, list] = {}
    for r in rows:
        d = days.setdefault(int(r[2]) // DAY_MS, [0.0, 0])
        d[0] += float(r[4])
        d[1] += 1
    keys = sorted(days)
    m = len(keys)
    if m < 2:
        return None, m
    rng = random.Random(seed)
    out = []
    for _ in range(draws):
        p = n = 0
        for _k in range(m):
            dp, dn = days[keys[int(rng.random() * m)]]
            p += dp
            n += dn
        out.append(p / n)
    return stdev(out), m


def _walks(used: list, key: str, part: str) -> list[dict]:
    return [c["combos"][key][part] for c in used if key in c.get("combos", {})]


def tally(walks: list[dict]) -> dict:
    """What the walks could not measure, or skipped, summed — the engine's
    counts, the filter's, the missed orders' market twins, and the trades
    bigger than the book readings' $100."""
    counts: dict[str, int] = {}
    for w in walks:
        for k, v in {**w.get("counts", {}), **w.get("filter", {})}.items():
            counts[k] = counts.get(k, 0) + int(v)
    lev = [x for w in walks for x in (w.get("lev") or [])]
    notional = [x for w in walks for x in (w.get("notional") or [])]
    return {"counts": counts,
            "twins": sum(int(w["twins"][0]) for w in walks if w.get("twins")),
            "twins_pnl": sum(float(w["twins"][1]) for w in walks if w.get("twins")),
            "over_book": sum(int(w.get("over_book", 0)) for w in walks),
            "lev": [min(lev), max(lev)] if lev else None,
            "notional": [min(notional), max(notional)] if notional else None}


def verdict(family: str, tf: str, filt: str, coins: list[dict], *, z: float = Z,
            tried: int = TRIED) -> dict:
    """One family on one timeframe with one filter, chosen and judged over
    every coin record that measured it."""
    keys = [vf.setting_key(family, v) for v in vf.FAMILIES[family]["settings"]]
    ck = {k: vf.combo_key(family, k, tf, filt) for k in keys}
    used = [c for c in coins if any(ck[k] in c.get("combos", {}) for k in keys)]
    older = {k: [r for w in _walks(used, ck[k], "older") for r in w["rows"]] for k in keys}
    chosen, table = choose(older, keys)
    window = next((c["windows"][tf] for c in used if tf in c.get("windows", {})), None)
    notes = [vu.SURVIVORSHIP] + ([NOTES[filt]] if filt in NOTES else [])
    base = {"id": vf.verdict_id(family, tf, filt), "family": family, "tf": tf, "filter": filt,
            "tried": tried, "alpha": ALPHA / tried, "z": z, "coins": [c["coin"] for c in used],
            "window": window, "months": next((c["unseen_months"] for c in used
                                               if c.get("unseen_months")), []),
            "older": table, "setting": chosen, "notes": notes}
    if chosen is None:
        why = (f"no coin measured {family} on {tf}" if not used else
               f"no setting had {MIN_CHOOSE} trades on the older days")
        return {**base, "passed": False, "failed": "choose", "why": why}
    key = ck[chosen]
    walks = _walks(used, key, "unseen")
    rows = [r for w in walks for r in w["rows"]]
    s = summary(rows)
    bar = random_bar(pool_random(c["combos"][key]["random"] for c in used
                                 if key in c["combos"]), z)
    se, days = boot_se(rows, vrn.seed_of("boot", key))
    ppt = s["per_trade"]
    checks = {"profit": ppt is not None and ppt > 0,
              "random": ppt is not None and bar is not None and ppt > bar["bar"],
              "bootstrap": ppt is not None and se is not None and ppt - z * se > 0,
              "trades": s["trades"] >= MIN_UNSEEN}
    failed = next((k for k in CHECKS if not checks[k]), "")
    return {**base, "passed": not failed, "failed": failed, "checks": checks, "unseen": s,
            "random": bar,
            "bootstrap": {"draws": BOOT_DRAWS, "days": days, "se": se,
                          "low": ppt - z * se if ppt is not None and se is not None else None},
            **tally(walks)}


def verdicts(coins: list[dict]) -> list[dict]:
    """Every judged group's verdict, in `v3_families.judged()` order."""
    return [verdict(f, tf, filt, coins) for f, tf, filt in vf.judged()]
