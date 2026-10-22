"""THE CONFLUENCE RESEARCH'S READER (Prompt 1, Oct 21, 2026): what the
machines found, and THE FIRST CHECK. Design:
docs/superpowers/specs/2026-10-21-confluence-research-design.md.

THE FIRST CHECK, the prompt's only early stop: on the test days - which the
search never read - does the real search's final pick make more per trade
BEFORE fees than the random search's final pick on the same coin and
timeframe? Before fees = each trade's whole charged round trip added back
(both fees and both fills). Per trade in R (one R = the stop), so a coin with
a 2% stop and one with a 0.4% stop weigh alike. A pick's trades are not
independent of each other, so a pick's average is the observation; the
difference real minus random is taken per coin + timeframe and AVERAGED PER
COIN (a coin's timeframes share its price path over the same test days, so
the coin is the unit of evidence); the low end of its 90% range (Student t,
n - 1 degrees of freedom over the coins) must be above zero. Fewer than
MIN_COINS coins is not evidence, and not evidence is a stop. A pick with
fewer than MIN_TEST_TRADES test trades is left out and named.

    python -m tradingagents.cq_report [state-name ...]   (several = one result)
"""
from __future__ import annotations

import gzip
import json
import math
import statistics
import sys
from pathlib import Path

MIN_COINS = 10            # coins with a real and a random pick: fewer is not evidence
MIN_TEST_TRADES = 10      # test-day trades a pick needs on each side to count
HALF_SPREAD_NOTE = ("Before fees adds back every round trip each trade was charged (both fees "
                    "and both fills), but an entry bought on a minute with a book reading "
                    "(the newest ~45 days) still pays its half-spread inside the fill price; "
                    "real and random picks pay it alike.")


def _tried(out: dict) -> int:
    return int((out.get("search") or {}).get("tried") or 0)


def results(roots) -> dict:
    """Every machine's out/cq-*.json.gz joined: {"meta": the run's settings,
    "coins": {coin: record}}. Joined per coin AND timeframe: one coin arrives
    from two runs that measured different timeframes (the pilot ran 4h+1d,
    then 15m/30m/1h) and keeps both; a coin + timeframe measured twice
    (claimed again after a machine died) keeps the copy whose search tried the
    most candidates."""
    from tradingagents import pro_search as ps

    meta: dict = {}
    coins: dict = {}
    for f in ps.files(roots, "cq-*.json.gz"):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            d = json.load(fh)
        meta = meta or {k: v for k, v in d.items() if k != "coins"}
        for coin, rec in (d.get("coins") or {}).items():
            have = coins.setdefault(coin, {**{k: v for k, v in rec.items() if k != "tfs"},
                                           "tfs": {}})
            for tf, out in (rec.get("tfs") or {}).items():
                if tf not in have["tfs"] or _tried(out) > _tried(have["tfs"][tf]):
                    have["tfs"][tf] = out
    return {"meta": meta, "coins": coins}


def prefee_r(part, sl_pct: float, notional: float = 100.0) -> float | None:
    """Profit per trade BEFORE fees, in R: (profit $ + the round trips paid,
    as $ of the position) / trades / (the stop, as $ of the position)."""
    t, _w, p, cost = part[:4]
    if not t or not sl_pct:
        return None
    return (float(p) + float(cost) * notional / 100.0) / t / (float(sl_pct) * notional / 100.0)


def after_fee_r(part, sl_pct: float, notional: float = 100.0) -> float | None:
    t, _w, p, _cost = part[:4]
    if not t or not sl_pct:
        return None
    return float(p) / t / (float(sl_pct) * notional / 100.0)


def t_quantile(p: float, df: int) -> float:
    """Student's t quantile by the Cornish-Fisher expansion (no scipy here):
    1.833 for 0.95 at 9 degrees of freedom, within 0.001 from 5 up."""
    z = statistics.NormalDist().inv_cdf(p)
    v = float(df)
    g1 = (z ** 3 + z) / 4
    g2 = (5 * z ** 5 + 16 * z ** 3 + 3 * z) / 96
    g3 = (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / 384
    g4 = (79 * z ** 9 + 776 * z ** 7 + 1482 * z ** 5 - 1920 * z ** 3 - 945 * z) / 92160
    return z + g1 / v + g2 / v ** 2 + g3 / v ** 3 + g4 / v ** 4


def _final(search: dict | None):
    if not search or not search.get("final"):
        return None
    return search["picks"][search["final"]]["cand"]


def first_check(coins: dict, notional: float = 100.0, min_coins: int = MIN_COINS,
                min_trades: int = MIN_TEST_TRADES) -> dict:
    """Real final pick against random final pick, per coin + timeframe, on the
    test days, before fees, then AVERAGED PER COIN: a coin's timeframes trade
    one price path over the same test days, so the coin is the unit of
    evidence (review, Oct 22, 2026). Go only when the low end of the 90% range
    of the coins' differences is above zero over at least `min_coins` coins.
    A pair with fewer than `min_trades` test trades on either side is left
    out and named (a handful of trades is noise; set before the second half's
    numbers were seen). The per-pair figures ride beside and never decide."""
    rows, thin = [], []
    for coin, rec in sorted(coins.items()):
        for tf, out in sorted((rec.get("tfs") or {}).items()):
            real, luck = _final(out.get("search")), _final(out.get("luck"))
            if real is None or luck is None:
                continue
            if int(real[6][0]) < min_trades or int(luck[6][0]) < min_trades:
                thin.append(f"{coin} {tf}: {real[6][0]} real / {luck[6][0]} random test trades")
                continue
            a, b = prefee_r(real[6], real[1], notional), prefee_r(luck[6], luck[1], notional)
            rows.append({"coin": coin, "tf": tf, "real": round(a, 4), "random": round(b, 4),
                         "diff": round(a - b, 4), "real_name": real[0], "random_name": luck[0],
                         "real_trades": real[6][0], "random_trades": luck[6][0],
                         "real_after_fee": round(after_fee_r(real[6], real[1], notional), 4)})
    per: dict = {}
    for x in rows:
        per.setdefault(x["coin"], []).append(x)
    by_coin = {c: {"diff": statistics.fmean(v["diff"] for v in xs),
                   "real": statistics.fmean(v["real"] for v in xs),
                   "random": statistics.fmean(v["random"] for v in xs), "pairs": len(xs)}
               for c, xs in per.items()}
    n = len(by_coin)
    out = {"coins": n, "pairs": len(rows), "rows": rows, "thin": thin, "min_coins": min_coins,
           "min_trades": min_trades, "notional": notional, "note": HALF_SPREAD_NOTE,
           "by_coin": {c: {k: round(v, 4) if isinstance(v, float) else v for k, v in d.items()}
                       for c, d in by_coin.items()}}
    if n < 2:
        out.update(verdict="stop", why=f"only {n} coin(s) have a real and a random pick with "
                                       f"{min_trades}+ test-day trades each: not evidence")
        return out
    d = [v["diff"] for v in by_coin.values()]
    mean, sd = statistics.fmean(d), statistics.stdev(d)
    t = t_quantile(0.95, n - 1)
    low, high = mean - t * sd / math.sqrt(n), mean + t * sd / math.sqrt(n)
    pdiff = [x["diff"] for x in rows]
    pt = t_quantile(0.95, len(pdiff) - 1)
    pm, psd = statistics.fmean(pdiff), statistics.stdev(pdiff)
    out.update(mean_diff=round(mean, 4), low90=round(low, 4), high90=round(high, 4),
               real_mean=round(statistics.fmean(v["real"] for v in by_coin.values()), 4),
               random_mean=round(statistics.fmean(v["random"] for v in by_coin.values()), 4),
               ahead=sum(v > 0 for v in d),
               pair_mean_diff=round(pm, 4),
               pair_low90=round(pm - pt * psd / math.sqrt(len(pdiff)), 4),
               pair_high90=round(pm + pt * psd / math.sqrt(len(pdiff)), 4),
               pairs_ahead=sum(x > 0 for x in pdiff),
               by_tf={tf: {"pairs": len(v), "mean_diff": round(statistics.fmean(v), 4)}
                      for tf in sorted({x["tf"] for x in rows})
                      for v in [[x["diff"] for x in rows if x["tf"] == tf]]})
    if n < min_coins:
        out.update(verdict="stop", why=f"not enough evidence: {n} coins, {min_coins} needed")
    elif low > 0:
        out.update(verdict="go", why=f"the real picks made {mean:+.3f}R a trade more than "
                                     f"random before fees, averaged per coin; the low end of "
                                     f"the 90% range is {low:+.3f}R, above zero, over {n} coins "
                                     f"({len(rows)} coin+timeframes)")
    else:
        out.update(verdict="stop", why=f"the real picks are not clearly ahead of random before "
                                       f"fees: {mean:+.3f}R a trade averaged per coin, the 90% "
                                       f"range runs {low:+.3f}R to {high:+.3f}R over {n} coins "
                                       f"({len(rows)} coin+timeframes)")
    return out


def summary(coins: dict, report: list | None = None) -> dict:
    """Per timeframe: coin+timeframes searched, skipped (each named with why),
    cut by the deadline and failed (from the machines' reports), candidates
    tried, why the searches stopped, and the final picks' payouts and
    test-day win rates - for the real search and the luck search."""
    def blank():
        return {"searched": 0, "skipped": [], "deadline": [], "failed": [], "tried": 0,
                "stop": {}, "final_payout": {}, "test_trades": 0, "test_wins": 0,
                "luck_tried": 0}

    per: dict = {}
    for rec in coins.values():
        for tf, out in (rec.get("tfs") or {}).items():
            row = per.setdefault(tf, blank())
            s = out.get("search") or {}
            row["searched"] += 1
            row["tried"] += int(s.get("tried") or 0)
            row["stop"][s.get("stop")] = row["stop"].get(s.get("stop"), 0) + 1
            row["luck_tried"] += int((out.get("luck") or {}).get("tried") or 0)
            fin = _final(s)
            if fin:
                row["final_payout"][str(fin[3])] = row["final_payout"].get(str(fin[3]), 0) + 1
                row["test_trades"] += int(fin[6][0])
                row["test_wins"] += int(fin[6][1])
    for e in report or []:
        tf = e.get("tf")
        if tf in (None, "*"):
            continue
        row = per.setdefault(tf, blank())
        if e.get("error"):
            row["failed"].append(f"{e.get('coin')}: {e['error']}")
        elif e.get("why"):
            row["skipped"].append(f"{e.get('coin')}: {e['why']}")
        elif e.get("stop") == "deadline":
            row["deadline"].append(str(e.get("coin")))
    for row in per.values():
        row["test_win_rate"] = (round(100 * row["test_wins"] / row["test_trades"], 1)
                                if row["test_trades"] else None)
    return {"coins": len(coins), "by_tf": dict(sorted(per.items()))}


def report_states(states: list) -> dict:
    """Read every collected run named (`<state>-collected.json` under
    cq_search.home()) as ONE result - the pilot's two halves together - and
    write `<stem>+<stem>-report.json` beside them."""
    from tradingagents import cq_search as cqs

    roots, labels = [], []
    for state in states:
        got = json.loads((cqs.home() / f"{Path(state).stem}-collected.json")
                         .read_text(encoding="utf-8"))
        roots += list(got["roots"])
        labels.append(got.get("label"))
    from tradingagents import pro_search as ps

    res = results(roots)
    meta = res["meta"]
    notional = float(meta.get("base") or 5.0) * float(meta.get("lev") or 20)
    report = ps.read_json_parts(roots, "cq-report-*.json", "report")
    rep = {"states": list(states), "labels": labels, "summary": summary(res["coins"], report),
           "first_check": first_check(res["coins"], notional=notional), "meta": meta}
    stem = "+".join(Path(s).stem for s in states)
    (cqs.home() / f"{stem}-report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep


if __name__ == "__main__":
    from tradingagents import cq_search as cqs

    states = sys.argv[1:] or [cqs.STATE]
    rep = report_states(states)
    fc = rep["first_check"]
    cqs.progress(f"first check ({' + '.join(Path(s).stem for s in states)}): {fc['verdict']} "
                 f"- {fc['why']}", first_check={k: v for k, v in fc.items() if k != "rows"})
    print(json.dumps({k: v for k, v in rep.items() if k != "meta"}
                     | {"first_check": {k: v for k, v in fc.items() if k != "rows"}}, indent=2))
