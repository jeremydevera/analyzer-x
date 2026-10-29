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
   α = ALPHA / every combination measured (`v3_families.combos()`, 63 —
   counted, never estimated) and z = Φ⁻¹(1 - α/2), 3.355.
3. Every verdict is kept, passed or failed, with its numbers.

A trade still open when a walk ends (`why` END: at the split for the older
walk, at the plan's end for the unseen one) counts, marked at that candle's
close and paying the market exit; the verdict says how many there were.
"""
from __future__ import annotations

import random
from statistics import NormalDist, fmean, median, stdev

from tradingagents import v3_families as vf, v3_filters as vfl, v3_random as vrn, v3_universe as vu

ALPHA = 0.05
MIN_CHOOSE = 30
MIN_UNSEEN = 300
BOOT_DRAWS = 2000
DAY_MS = 86_400_000
CHECKS = ("profit", "random", "bootstrap", "trades")
TRIED = len(vf.combos())
# What each filter that can surprise says on its verdict (the decisions doc, "The filters").
NOTES = {
    "busy_hours": ("No family's universe holds stock tokens, so only the no-weekend half of "
                   "busy hours can bite."),
    "btc_mood": "Only crypto alt-coins' longs are filtered; BTC and other contracts pass.",
    "funding_side": ("A signal the funding history cannot judge passes and is counted "
                     "funding_unknown."),
    "funding_minutes": (f"No order within {vfl.SETTLE_GAP_MS // 60_000} minutes of a funding "
                        "settlement. Orders go in on the hour, so every order that goes in on a "
                        "settlement hour is blocked: every 4h order of a coin that settles "
                        "every 4 hours, half the 4h orders of an 8-hour coin, and 6 or 3 of the "
                        "24 1h orders of a 4- or an 8-hour coin (all of a 1-hour coin's). It is "
                        "not tried on 1d, where it would block every order (00:00 UTC is a "
                        "settlement on every cycle). The filter's blocked count is on the "
                        "verdict."),
}
# The engine's counts that turn a signal candle away before any order goes in, in the order a tie is
# settled, and the words each is said in ({at} is " at $x risk" when the records name a risk).
REFUSALS = (("too_small", "were under one lot{at}"),
            ("unsafe_stop", "had no safe leverage"),
            ("gate_blocked", "were turned away by the cost check"))


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


def pool_random(per_coin, names=None) -> list[tuple[int, float]]:
    """Run k pooled over the coins: (its trades, its profit), summed. A coin
    whose number of runs differs from the first coin's is refused by name:
    `names` gives the coins' names in the order of `per_coin`."""
    runs: list[list] | None = None
    first = ""
    for i, coin_runs in enumerate(per_coin):
        if runs is None:
            runs = [[0, 0.0] for _ in coin_runs]
            first = names[i] if names else "the first coin"
        if len(coin_runs) != len(runs):
            who = names[i] if names else "a coin"
            raise ValueError(f"{who} holds {len(coin_runs)} random runs, {first} holds {len(runs)}")
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


def not_traded(held: list[dict], key: str) -> dict | None:
    """The random runs' entries that never became a trade, summed over every
    coin and every run, by why: "short" (could not be placed: the month had
    too few candles to draw from, `random_short`), "in_trade" (it fell inside
    the run's own open trade, `random_in_trade`) and the engine's own counts
    (`random_refused`: e.g. `no_levels`, a snap drawn on the far side of its
    average, which has no target). Only the counts above 0 are kept. None when
    a coin's record does not carry them (measured before they were kept):
    never a zero nobody counted."""
    out: dict[str, int] = {}
    for c in held:
        combo = c["combos"][key]
        if not all(f in combo for f in ("random_short", "random_in_trade", "random_refused")):
            return None
        for k, v in {"short": combo["random_short"], "in_trade": combo["random_in_trade"],
                     **combo["random_refused"]}.items():
            if int(v):
                out[k] = out.get(k, 0) + int(v)
    return out


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


def _refuse_mixed(coins: list[dict]) -> None:
    """Coins are pooled only when each is listed once and all were measured on
    one risk, one run count, one plan end, one plan BUILD (`plan_id`: builds
    of one UTC day share an end, and only their content tells them apart; a
    record written before builds were stamped has none, so two of them pool with
    each other and never with a stamped one) and one record `version` (a
    version 1 trade row has no stop or target, and its older walk paid another
    flat gap). Anything else is refused by name:
    the pooled trades would not all exist at one risk, one coin would be counted
    twice, or the coins would come from two universes."""
    names = [c.get("coin") for c in coins]
    for i, name in enumerate(names):
        if name in names[:i]:
            raise ValueError(f"{name} is listed twice: pooling it twice would count its trades twice")
    for key in ("risk_usd", "runs", "plan_end_ms", "plan_id", "version"):
        for c in coins[1:]:
            if c.get(key) != coins[0].get(key):
                raise ValueError(
                    f"coins measured at different {key} cannot be pooled: {c.get('coin')} at "
                    f"{c.get(key)!r}, {coins[0].get('coin')} at {coins[0].get(key)!r}")


def _blocked_all(used: list, ck: dict, keys: list) -> int | None:
    """The most signals any setting had on the older days, when the filter
    blocked every one of them for every setting and there was a signal; else
    None. The counts are the older walks' own (`filter`: signal_candles and
    blocked; an absent count is zero)."""
    signals = dict.fromkeys(keys, 0)
    blocked = dict.fromkeys(keys, 0)
    for k in keys:
        for w in _walks(used, ck[k], "older"):
            signals[k] += int(w.get("filter", {}).get("signal_candles", 0))
            blocked[k] += int(w.get("filter", {}).get("blocked", 0))
    most = max(signals.values())
    return most if most >= 1 and all(blocked[k] == signals[k] for k in keys) else None


def _refusal_words(counts: dict, risk, settings: int = 1) -> str:
    """The dominant reason signal candles were turned away, from the engine's
    own counts summed over the older walks (`REFUSALS`: the biggest, a tie to
    the first), as "228 of 228 signals over the 3 settings (a candle counts
    once for each setting it signals under) were under one lot at $1.00 risk";
    "" when none was refused. The counts are summed over `settings` settings,
    so a candle that signals under three of them is three signals there: the
    words say so whenever there is more than one. The risk is the records',
    and is left unsaid when they name none. `signal_candles` is what the filter
    counted: a count above it (a record that kept no signal count) is said
    without a denominator."""
    key, words = max(REFUSALS, key=lambda kw: int(counts.get(kw[0], 0)))
    n = int(counts.get(key, 0))
    if n <= 0:
        return ""
    signals = int(counts.get("signal_candles", 0))
    of = f"{n:,} of {signals:,}" if signals >= n else f"{n:,}"
    at = f" at ${float(risk):,.2f} risk" if risk is not None else ""
    what = ("signal candles" if settings == 1 else
            f"signals over the {settings} settings (a candle counts once for each setting it "
            "signals under)")
    return f"{of} {what} {words.format(at=at)}"


def verdict(family: str, tf: str, filt: str, coins: list[dict], *, z: float | None = None,
            tried: int = TRIED) -> dict:
    """One family on one timeframe with one filter, chosen and judged over
    every coin record that measured it.

    z=None (the default) takes z_for(tried), so a verdict's alpha and z are
    always for the same count of tries. An explicit z is used as given, and the
    record's alpha is the one that z makes, 2 x (1 - Φ(z)), so no label names
    one count with another count's z. z must be positive.

    A verdict that failed at the choice carries `older_counts` - the older
    walks' counts summed over every setting and every coin - and its `why` names
    the dominant reason signals were turned away; one that went on to be judged
    carries `random_runs`, whether or not a bar came of them: the runs made,
    the runs that traded, the real run's unseen trades, the runs' median
    trades and why their other entries never traded (`not_traded`). The bar is
    stricter than one drawn from runs with as many trades as the real run:
    a random entry inside an open trade, or a snap drawn on the far side of
    its average, does not trade, and fewer trades spread profit a trade wider
    (decisions doc, "Random entries")."""
    _refuse_mixed(coins)
    if isinstance(tried, bool) or not isinstance(tried, int) or tried < 1:
        raise ValueError(f"tried must be a positive whole number, got {tried!r}")
    if z is None:
        z, alpha = z_for(tried), ALPHA / tried
    elif not z > 0:
        raise ValueError(f"z must be positive, got {z!r}")
    else:
        alpha = 2 * (1 - NormalDist().cdf(z))
    keys = [vf.setting_key(family, v) for v in vf.FAMILIES[family]["settings"]]
    ck = {k: vf.combo_key(family, k, tf, filt) for k in keys}
    used = [c for c in coins if any(ck[k] in c.get("combos", {}) for k in keys)]
    older = {k: [r for w in _walks(used, ck[k], "older") for r in w["rows"]] for k in keys}
    chosen, table = choose(older, keys)
    for k in keys:
        # the older exits that paid the coin's usual cost, no minute's book recorded: beside the
        # figure the choice was made on, as the unseen walk's is beside its own (CLAUDE.md, "Every
        # backtest LOOKS AT THE COSTS")
        table[k]["cost_unmeasured"] = sum(int(w.get("counts", {}).get("cost_unmeasured", 0))
                                          for w in _walks(used, ck[k], "older"))
    wins =[c["windows"][tf] for c in used if tf in c.get("windows", {})]
    # One plan end - `_refuse_mixed` has seen to it - is one split and one end, so the window's text
    # is the first coin's label of that one instant. The texts are never compared: each machine
    # prints them in its own time zone, and a coin measured on this PC and one measured on GitHub
    # print the same instant two ways
    window = ({"split": wins[0].get("split"), "end": wins[0].get("end"),
               "older_candles": sum(int(w.get("older_candles", 0)) for w in wins),
               "unseen_candles": sum(int(w.get("unseen_candles", 0)) for w in wins)}
              if wins else None)
    notes = [vu.SURVIVORSHIP] + ([NOTES[filt]] if filt in NOTES else [])
    base = {"id": vf.verdict_id(family, tf, filt), "family": family, "tf": tf, "filter": filt,
            "tried": tried, "alpha": alpha, "z": z, "coins": [c["coin"] for c in used],
            "window": window, "months": next((c["unseen_months"] for c in used
                                               if c.get("unseen_months")), []),
            "older": table, "setting": chosen, "notes": notes}
    if chosen is None:
        most = _blocked_all(used, ck, keys)
        # what the older walks of every setting, of every coin, could not measure or turned away
        older_counts = tally([w for k in keys for w in _walks(used, ck[k], "older")])["counts"]
        # a plain group names no filter; a filtered one says which, as "with <filter>"
        named = "" if filt == "none" else f" with {filt}"
        if not used:
            why = f"no coin measured {family} on {tf}{named}"
        elif most is not None:
            why = f"{filt} blocked all {most:,} signals on the older days"
        else:
            why = f"no setting had {MIN_CHOOSE} trades on the older days{named}"
            # a group can fail here because its signals never became orders: say so, at the risk
            # the records were measured at (every coin of `used` shares one: `_refuse_mixed`)
            refused = _refusal_words(older_counts, used[0].get("risk_usd"), len(keys))
            if refused:
                why += f": {refused}"
        return {**base, "passed": False, "failed": "choose", "why": why,
                "older_counts": older_counts}
    key = ck[chosen]
    walks = _walks(used, key, "unseen")
    rows = [r for w in walks for r in w["rows"]]
    s = summary(rows)
    held = [c for c in used if key in c["combos"]]
    pooled = pool_random([c["combos"][key]["random"] for c in held], [c["coin"] for c in held])
    bar = random_bar(pooled, z)
    se, days = boot_se(rows, vrn.seed_of("boot", key))
    ppt = s["per_trade"]
    checks = {"profit": ppt is not None and ppt > 0,
              "random": ppt is not None and bar is not None and ppt > bar["bar"],
              "bootstrap": ppt is not None and se is not None and ppt - z * se > 0,
              "trades": s["trades"] >= MIN_UNSEEN}
    failed = next((k for k in CHECKS if not checks[k]), "")
    return {**base, "passed": not failed, "failed": failed, "checks": checks, "unseen": s,
            "random": bar,
            # the runs made and the runs that traded, kept whether or not a bar came of them, and how
            # far the runs' trades fell short of the real run's (decisions doc, "Random entries")
            "random_runs": {"runs": len(pooled), "traded": sum(1 for n, _p in pooled if n),
                            "real_trades": s["trades"],
                            "median_trades": median(n for n, _p in pooled) if pooled else None,
                            "not_traded": not_traded(held, key)},
            "bootstrap": {"draws": BOOT_DRAWS, "days": days, "se": se,
                          "low": ppt - z * se if ppt is not None and se is not None else None},
            **tally(walks)}


def verdicts(coins: list[dict]) -> list[dict]:
    """Every judged group's verdict, in `v3_families.judged()` order."""
    return [verdict(f, tf, filt, coins) for f, tf, filt in vf.judged()]
