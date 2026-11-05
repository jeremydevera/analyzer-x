"""Funding carry on Gate: buy the coin on the spot market and short its perpetual in the same size,
so the price moves cancel and what is left is the funding the shorts are paid (when the rate is
positive) or pay (when it is negative).

A carry has no entry signal, so the v3 engine (directional trades) does not measure it. This module
does, from the exchange's own PUBLISHED settlements, never a rate times a count: contracts settle every
1, 4 or 8 hours and the list says which. Plan:
docs/superpowers/plans/2026-11-04-daily-trend-long-window-and-funding-carry.md (Task 3).

Measured Nov 04, 2026 on 524 spot-listed coins: Gate serves only ~210 days of funding history.
A result is a fraction of the position (one leg's notional). Not counted: the spot leg's own price gap,
the perp's margin and liquidation, borrowing, and the cost of the money tied up in the spot leg.

Everything here is pure except `main`, which reads Gate (`fx.funding_history`, the public spot list).
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

DAY_MS = 86_400_000
HOME = Path.home() / ".tradingagents" / "carry"
# Round trip for both legs, per side. Taker: spot 0.2% + perp 0.075%; makers: spot 0.2% + perp 0.02%
# (Gate's published schedule at the base tier, checked on Nov 04, 2026).
FEE_TAKER = 0.2 / 100 + 0.075 / 100
FEE_MAKER = 0.2 / 100 + 0.02 / 100


def carry_open(settlements: list[dict], start_ms: int, hold_days: float, fee_in: float,
               fee_out: float) -> dict:
    """One carry held from `start_ms` for `hold_days`: the published settlements inside the hold are
    added up (a negative rate is a loss), the fees are paid once in and once out. Fractions of the
    position. `min_running` is the lowest running sum while open: the worst dip, not the final."""
    end_ms = start_ms + int(hold_days * DAY_MS)
    inside = [s for s in settlements if start_ms <= s["settle_ms"] < end_ms]
    earned = low = running = 0.0
    for s in inside:
        running += s["rate"]
        low = min(low, running)
        earned = running
    fees = fee_in + fee_out
    return {"earned": earned, "fees": fees, "net": earned - fees, "min_running": low,
            "settlements": len(inside)}


def scan(history: dict[str, list[dict]], spot_ids: set, *, hold_days: float, fee: float) -> dict:
    """Every coin's carry from every start day its history allows. `fee` is the whole round trip
    (both legs, in and out). A coin with no spot market, or less history than the hold, is NAMED in
    `left_out` with the reason (rule 20), never dropped."""
    rows, left_out = [], []
    for coin in sorted(history):
        settles = sorted(history[coin], key=lambda s: s["settle_ms"])
        if coin not in spot_ids:
            left_out.append({"coin": coin, "why": "no spot market"})
            continue
        if not settles:
            left_out.append({"coin": coin, "why": "no funding history"})
            continue
        first, last = settles[0]["settle_ms"], settles[-1]["settle_ms"]
        days = (last - first) / DAY_MS
        if days < hold_days:
            left_out.append({"coin": coin, "why": f"history {days:.0f} days is under the {hold_days:g}-day hold"})
            continue
        nets, worst = [], 0.0
        start = first
        while start + hold_days * DAY_MS <= last + 1:
            r = carry_open(settles, start, hold_days, fee / 2, fee / 2)
            nets.append(r["net"])
            worst = min(worst, r["min_running"])
            start += DAY_MS
        rows.append({"coin": coin, "history_days": days, "starts": len(nets),
                     "median_net": statistics.median(nets),
                     "share_positive": sum(1 for n in nets if n > 0) / len(nets),
                     "worst_dip": worst,
                     "cycle_hours": round(statistics.median(
                         b["settle_ms"] - a["settle_ms"] for a, b in zip(settles, settles[1:])) / 3_600_000, 1)
                     if len(settles) > 1 else None})
    return {"rows": rows, "left_out": left_out, "hold_days": hold_days, "fee": fee}


def walk_forward(history: dict[str, list[dict]], spot_ids: set, *, hold_days: float, fee: float,
                 top_n: int, lookback_days: float, step_days: float = 7, seed: int = 1) -> dict:
    """The honest version of `scan`: on each start day pick the `top_n` coins whose funding was highest
    over the `lookback_days` BEFORE it (nothing after it is read), hold them `hold_days`, and count what
    those settlements really paid minus `fee`. Beside it: `top_n` random coins and every coin, on the
    same days. A start needs at least 3 x `top_n` coins with history on both sides; fewer and the day is
    skipped, said in `skipped_starts`. Starts `step_days` apart overlap when step < hold: the number of
    independent months is about starts x step / hold."""
    import bisect
    import random

    rng = random.Random(seed)
    h = {c: sorted(v, key=lambda r: r["settle_ms"]) for c, v in history.items() if v and c in spot_ids}
    times = {c: [r["settle_ms"] for r in v] for c, v in h.items()}
    cum = {}
    for c, v in h.items():
        run, arr = 0.0, [0.0]
        for r in v:
            run += r["rate"]
            arr.append(run)
        cum[c] = arr

    def paid(c, a, b):
        return cum[c][bisect.bisect_left(times[c], b)] - cum[c][bisect.bisect_left(times[c], a)]

    first = min(t[0] for t in times.values())
    last = max(t[-1] for t in times.values())
    picked, rand, every, skipped = [], [], [], 0
    day = first + int(lookback_days * DAY_MS)
    while day + hold_days * DAY_MS <= last:
        live = [c for c in h if times[c][0] <= day - lookback_days * DAY_MS
                and times[c][-1] >= day + (hold_days - 1) * DAY_MS]
        if len(live) < 3 * top_n:
            skipped += 1
        else:
            score = {c: paid(c, day - int(lookback_days * DAY_MS), day) for c in live}
            top = sorted(live, key=lambda c: -score[c])[:top_n]

            def net(cs):
                return statistics.mean(paid(c, day, day + int(hold_days * DAY_MS)) - fee for c in cs)

            picked.append(net(top))
            rand.append(net(rng.sample(live, top_n)))
            every.append(net(live))
        day += int(step_days * DAY_MS)
    mean = lambda a: statistics.mean(a) if a else None
    return {"starts": len(picked), "skipped_starts": skipped, "picked": mean(picked), "random": mean(rand),
            "every": mean(every), "share_positive": (sum(1 for x in picked if x > 0) / len(picked)) if picked else None,
            "worst": min(picked) if picked else None, "hold_days": hold_days, "fee": fee, "top_n": top_n,
            "lookback_days": lookback_days}


def _spot_ids() -> set:
    req = urllib.request.Request("https://api.gateio.ws/api/v4/spot/currency_pairs",
                                 headers={"User-Agent": "analyzer-x"})
    return {p["id"] for p in json.load(urllib.request.urlopen(req, timeout=30))
            if p.get("trade_status") == "tradable"}


def fetch(log=print) -> dict:
    """Gate's published funding for every spot-listed contract, saved raw under HOME so a scan can be
    repeated without asking the exchange again."""
    import tradingagents.dataflows.exchange as fx

    spot = _spot_ids()
    syms = sorted(s for s in fx.trading_symbols() if s in spot)
    out, t0 = {}, time.time()
    for i, sym in enumerate(syms):
        try:
            out[sym] = [{"settle_ms": int(h["settle_ms"]), "rate": float(h["rate"])}
                        for h in fx.funding_history(sym)]
        except Exception as e:  # a coin that cannot be read is named, never dropped
            out[sym] = []
            log(f"funding for {sym} could not be read: {type(e).__name__}: {str(e)[:80]}")
        if i % 50 == 0:
            log(f"{i}/{len(syms)} {sym} {time.time() - t0:.0f}s")
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / "funding.json").write_text(json.dumps({"spot": sorted(spot), "history": out,
                                                    "fetched_s": int(time.time())}), encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "scan"
    if cmd == "fetch":
        fetch()
        return 0
    saved = json.loads((HOME / "funding.json").read_text(encoding="utf-8"))
    spot = set(saved["spot"])
    from tradingagents.positions_view import fmt_when

    print(f"funding read {fmt_when(saved['fetched_s'])}")
    holds = [float(x) for x in (argv[argv.index("--hold") + 1].split(",") if "--hold" in argv else ["30", "90"])]
    fees = [float(x) / 100 for x in (argv[argv.index("--fees") + 1].split(",") if "--fees" in argv else
                                     [f"{FEE_TAKER * 100}", f"{FEE_MAKER * 100}"])]
    for h in holds:
        for fee in fees:
            r = scan(saved["history"], spot, hold_days=h, fee=fee)
            rows = r["rows"]
            good = [x for x in rows if x["median_net"] > 0 and x["share_positive"] >= 0.7]
            print(f"\nhold {h:g} days, round trip {fee * 100:.2f}%: {len(rows)} coins scanned, "
                  f"{len(r['left_out'])} left out; {len(good)} net above 0 in 70%+ of start days")
            for x in sorted(good, key=lambda x: -x["median_net"])[:10]:
                print(f"  {x['coin']:<16} median {x['median_net'] * 100:+.2f}%  positive {x['share_positive'] * 100:.0f}%"
                      f"  worst dip {x['worst_dip'] * 100:.2f}%  history {x['history_days']:.0f} days"
                      f"  settles every {x['cycle_hours']} h")
    print()
    print("WALK-FORWARD (coins chosen only from funding BEFORE each start day):")
    for h in holds:
        for fee in fees:
            for n in (10, 30):
                for lb in (7, 30):
                    w = walk_forward(saved["history"], spot, hold_days=h, fee=fee, top_n=n, lookback_days=lb)
                    if not w["starts"]:
                        continue
                    print(f"  hold {h:g}d fee {fee * 100:.2f}% top {n} by past {lb}d: {w['starts']} starts "
                          f"(~{w['starts'] * 7 / h:.0f} independent) picked {w['picked'] * 100:+.2f}% "
                          f"(positive {w['share_positive'] * 100:.0f}%, worst {w['worst'] * 100:+.2f}%) | "
                          f"random {w['random'] * 100:+.2f}% | every coin {w['every'] * 100:+.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
