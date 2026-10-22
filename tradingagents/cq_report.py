"""THE CONFLUENCE RESEARCH'S READER (Prompt 1, Oct 21, 2026): what the
machines found, and THE FIRST CHECK. Design:
docs/superpowers/specs/2026-10-21-confluence-research-design.md.

THE FIRST CHECK, the prompt's only early stop: on the test days - which the
search never read - does the real search's final pick make more per trade
BEFORE fees than the random search's final pick on the same coin and
timeframe? Before fees = each trade's whole charged round trip added back
(both fees and both fills). Per trade in R (one R = the stop), so a coin with
a 2% stop and one with a 0.4% stop weigh alike. Each coin + timeframe is ONE
observation - a pick's trades are not independent of each other - and the
difference real minus random is taken per coin + timeframe; the low end of
its 90% range (Student t with n - 1 degrees of freedom: Welch's interval for
one sample of differences) must be above zero. Fewer than MIN_PAIRS pairs is
not evidence, and not evidence is a stop.

    python -m tradingagents.cq_report [state-name]
"""
from __future__ import annotations

import gzip
import json
import math
import statistics
import sys
from pathlib import Path

MIN_PAIRS = 10


def _tried(rec: dict) -> int:
    return sum(int((t.get("search") or {}).get("tried") or 0)
               for t in (rec.get("tfs") or {}).values())


def results(roots) -> dict:
    """Every machine's out/cq-*.json.gz joined: {"meta": the run's settings,
    "coins": {coin: record}}. A coin measured twice (claimed again after a
    machine died) keeps the copy whose searches tried the most candidates."""
    from tradingagents import pro_search as ps

    meta: dict = {}
    coins: dict = {}
    for f in ps.files(roots, "cq-*.json.gz"):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            d = json.load(fh)
        meta = meta or {k: v for k, v in d.items() if k != "coins"}
        for coin, rec in (d.get("coins") or {}).items():
            if coin not in coins or _tried(rec) > _tried(coins[coin]):
                coins[coin] = rec
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


def first_check(coins: dict, notional: float = 100.0, min_pairs: int = MIN_PAIRS) -> dict:
    """Real final pick against random final pick, per coin + timeframe, on the
    test days, before fees: go only when the low end of the 90% range of the
    difference is above zero over at least `min_pairs` pairs."""
    rows = []
    for coin, rec in sorted(coins.items()):
        for tf, out in sorted((rec.get("tfs") or {}).items()):
            real, luck = _final(out.get("search")), _final(out.get("luck"))
            if real is None or luck is None:
                continue
            a, b = prefee_r(real[6], real[1], notional), prefee_r(luck[6], luck[1], notional)
            if a is None or b is None:
                continue
            rows.append({"coin": coin, "tf": tf, "real": round(a, 4), "random": round(b, 4),
                         "diff": round(a - b, 4), "real_name": real[0], "random_name": luck[0],
                         "real_trades": real[6][0], "random_trades": luck[6][0],
                         "real_after_fee": round(after_fee_r(real[6], real[1], notional), 4)})
    n = len(rows)
    out = {"pairs": n, "rows": rows, "min_pairs": min_pairs}
    if n < 2:
        out.update(verdict="stop", why=f"only {n} coin+timeframe(s) have a real and a random "
                                       f"pick with test-day trades: not evidence")
        return out
    d = [x["diff"] for x in rows]
    mean, sd = statistics.fmean(d), statistics.stdev(d)
    t = t_quantile(0.95, n - 1)
    low, high = mean - t * sd / math.sqrt(n), mean + t * sd / math.sqrt(n)
    out.update(mean_diff=round(mean, 4), low90=round(low, 4), high90=round(high, 4),
               real_mean=round(statistics.fmean(x["real"] for x in rows), 4),
               random_mean=round(statistics.fmean(x["random"] for x in rows), 4),
               ahead=sum(x["diff"] > 0 for x in rows),
               by_tf={tf: {"pairs": len(v), "mean_diff": round(statistics.fmean(v), 4)}
                      for tf in sorted({x["tf"] for x in rows})
                      for v in [[x["diff"] for x in rows if x["tf"] == tf]]})
    if n < min_pairs:
        out.update(verdict="stop", why=f"not enough evidence: {n} pairs, {min_pairs} needed")
    elif low > 0:
        out.update(verdict="go", why=f"the real picks made {mean:+.3f}R a trade more than "
                                     f"random before fees; the low end of the 90% range is "
                                     f"{low:+.3f}R, above zero, over {n} coin+timeframes")
    else:
        out.update(verdict="stop", why=f"the real picks are not clearly ahead of random before "
                                       f"fees: {mean:+.3f}R a trade, the 90% range runs "
                                       f"{low:+.3f}R to {high:+.3f}R over {n} coin+timeframes")
    return out


def summary(coins: dict) -> dict:
    """Per timeframe: coin+timeframes searched and skipped (with why),
    why the searches stopped, candidates tried, and the final picks' payouts
    and test-day win rates - for the real search and the luck search."""
    per: dict = {}
    for rec in coins.values():
        for tf, out in (rec.get("tfs") or {}).items():
            row = per.setdefault(tf, {"searched": 0, "tried": 0, "stop": {}, "final_payout": {},
                                      "test_trades": 0, "test_wins": 0, "luck_tried": 0})
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
    for row in per.values():
        row["test_win_rate"] = (round(100 * row["test_wins"] / row["test_trades"], 1)
                                if row["test_trades"] else None)
    return {"coins": len(coins), "by_tf": dict(sorted(per.items()))}


if __name__ == "__main__":
    from tradingagents import cq_search as cqs

    state = sys.argv[1] if len(sys.argv) > 1 else cqs.STATE
    stem = Path(state).stem
    got = json.loads((cqs.home() / f"{stem}-collected.json").read_text(encoding="utf-8"))
    res = results(got["roots"])
    fc = first_check(res["coins"])
    rep = {"state": state, "summary": summary(res["coins"]), "first_check": fc,
           "meta": res["meta"]}
    (cqs.home() / f"{stem}-report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    cqs.progress(f"first check ({stem}): {fc['verdict']} - {fc['why']}",
                 first_check={k: v for k, v in fc.items() if k != "rows"})
    print(json.dumps({k: v for k, v in rep.items() if k != "meta"}
                     | {"first_check": {k: v for k, v in fc.items() if k != "rows"}}, indent=2))
