"""THE ALL-COINS STRATEGIES PAGE (Nov 05, 2026): every pick of `tradingagents.acs` - several Backtest
v2 strategies for every coin-timeframe, and every chosen Backtest v3 per-coin strategy of each year -
as one artifact page with the standard kit (CLAUDE.md "Backtest reporting requirements").

    python -m tradingagents.acs page   ->  <store>/acs/all-coins-strategies.html

Every figure in a row is worked out IN THE PAGE from that row's own trades (kit B, D, F, G): a v2
row's trades are GitHub's re-measure of that very strategy (`acs collect`), a v3 row's are its year's
unseen trades. A v2 row whose re-measured trades do not add up to the re-measured row is REFUSED,
never printed (the per-coin page's rule, RCA-2026-10-28-E).

Trades ride as [entry s, exit s, side, exit kind, profit x 10,000, stop % x 1,000 or -1, target % x
1,000 or -1] (the dollars at $5: v2's margin at 20x, v3's risk to the stop); the whole payload is
gzipped and base64-encoded, never trimmed.
"""
from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path

WHYS = ("TP", "SL", "TRAIL", "MA", "TIME", "END", "RANK", "SIGNAL", "OTHER")
FIELDS = ("id", "src", "coin", "tf", "strategy", "tp_rule", "sl_rule", "lev", "chosen_on", "check",
          "bar", "both", "luck", "end", "days", "lost", "split", "fwd")
BASE = 5.0


def _why(text: str) -> int:
    t = str(text).upper()
    for i, w in enumerate(WHYS):
        if t.startswith(w):
            return i
    return WHYS.index("OTHER")


def v2_rows(picks: dict, trades: dict, per_pair: int = 3) -> tuple[list, list, list]:
    """The first `per_pair` candidates of every coin-timeframe that came back with their re-measured
    trades, in the candidates' own order (made money on the older 15 days first, then the rest,
    flagged). A coin-timeframe left with fewer is NAMED in the third list with why, never dropped
    silently (rule 20)."""
    lines = trades["lines"]
    no_row = set(trades.get("no_row") or [])
    gone = set(trades.get("not_reached") or [])
    rows, tlists, missing = [], [], []
    for pair in sorted(picks["pairs"]):
        p = picks["pairs"][pair]
        bar = p["bar"]
        shown, why_not = 0, []
        for r in p["picks"]:
            if shown >= per_pair:
                break
            cfg = f"{r['signal']}:{float(r['th']):g}:{float(r['sl']):g}:{float(r['tp']):g}"
            key = f"{p['coin']}|{p['tf']}|{cfg}"
            line = lines.get(key)
            if line is None:
                why_not.append(f"#{r['id']} {cfg}: " + (
                    "GitHub's re-measure a day later made no row (no trade in the moved window, or it "
                    "no longer passes the list's 2:1 after fees)" if key in no_row else
                    "its coin was not reached" if p["coin"] in gone else "no trade list came back"))
                continue
            ts = [[int(t[0]) // 1000, int(t[1]) // 1000, int(t[2]), _why(t[3]),
                   int(round(float(t[4]) * 10_000)), int(round(float(r["sl"]) * 1000)),
                   int(round(float(r["tp"]) * 1000))] for t in line["trades"]]
            ts.sort(key=lambda t: (t[1], t[0]))
            got = sum(t[4] for t in ts) / 10_000
            said = float(line["row"].get("profit") or 0.0)
            if len(ts) != int(line["row"].get("trades") or 0) or abs(got - said) > 0.01 + 0.006 * len(ts):
                raise ValueError(f"#{r['id']} {p['coin']} {p['tf']}: its trades add to {got:+.2f} over "
                                 f"{len(ts)}, its re-measured row says {said:+.2f} over "
                                 f"{line['row'].get('trades')} - collect again")
            o = r["older"]
            lost = bool(r.get("older_lost"))
            young = bool(r.get("unchecked"))
            end = int(line["row"].get("last_ms") or (ts[-1][1] * 1000 if ts else 0)) // 1000
            rows.append({"id": r["id"], "src": "v2", "coin": p["coin"], "tf": p["tf"],
                         "strategy": f"{r['signal']}" + (f" th {float(r['th']):g}" if float(r["th"]) else ""),
                         "tp_rule": f"{float(r['tp']):g}% fixed", "sl_rule": f"{float(r['sl']):g}% fixed",
                         "lev": "20x", "chosen_on": ("TOO NEW TO CHECK: every trade of the coin falls in the "
                                                     "newest 15 days, so nothing was left to check it on; shown "
                                                     "by its 30-day profit" if young else
                                                     ("LOST on " if lost else "made money on ")
                                                     + f"the older 15 days of the stored backtest: "
                                                     f"{o['trades']} trades, {o['wins']} won, {o['profit']:+.2f}"
                                                     + (" (shown so the pair has strategies: none of its "
                                                        "rows did better there)" if lost else "")),
                         "check": f"stored newest 15 days: {r['t15']} trades, {r['w15']} won, {float(r['p15']):+.2f}",
                         "bar": bar["per_trade"], "both": None, "luck": None, "end": end,
                         "days": float(line["row"].get("days") or 30), "lost": 2 if young else 1 if lost else 0,
                         "split": end - 15 * 86_400, "fwd": 0})
            tlists.append(ts)
            shown += 1
        if shown < per_pair:
            missing.append(f"{p['coin']} {p['tf']}: {shown} of {per_pair} shown"
                           + (f" - {len(p['picks'])} candidates" if p["picks"] else
                              " - the Backtest v2 list holds no strategy for it (none passed a target above "
                              "the stop and a win paying two losses after fees)" if not p["rows"] else
                              f" - none of its {p['rows']:,} rows has a stop, a target and a trade")
                           + ("; " + "; ".join(why_not) if why_not else ""))
    return rows, tlists, missing


def skill_rows(skill: dict) -> tuple[list, list]:
    """The backtesting-trading-strategies skill's picks of every coin-timeframe (skill_bt.py), each
    with every trade, chosen on the older 70% of the candles and judged on the newest 30%; the
    technical-analysis and backtesting-frameworks run (skill_ta.py) the same way, each strategy's
    label naming its skill and a pattern's target (2x its stop) riding on every trade."""
    from tradingagents import skill_ta
    from tradingagents import backtest_report as br
    from tradingagents.positions_view import fmt_when

    rows, tlists = [], []
    for key in sorted(skill["lines"]):
        x = skill["lines"][key]
        for c in x["picks"]:
            o, n = c["older"], c["newer"]
            tg = c.get("target")
            who = skill_ta.SKILL_OF.get(c["strategy"], "backtesting-trading-strategies")
            name = c["label"] if who == "backtesting-trading-strategies" else f"{who}: {c['label']}"
            rid = br.row_code(x["coin"], x["tf"], c["strategy"], 0, c["stop"] * 100, (tg or 0) * 100, "flat",
                              plan=c["label"], res="skill")
            ts = [[int(t[0]) // 1000, int(t[1]) // 1000, int(t[2]), _why(t[3]),
                   int(round(float(t[4]) * 10_000)), int(round(c["stop"] * 100 * 1000)),
                   int(round(tg * 100 * 1000)) if tg else -1]
                  for t in c["trades"]]
            ts.sort(key=lambda t: (t[1], t[0]))
            rows.append({"id": rid, "src": "skill", "coin": x["coin"], "tf": x["tf"], "strategy": name,
                         "tp_rule": (f"{tg * 100:g}% (2x the stop, the technical-analysis skill's 2:1), "
                                     "checked on the close; or the strategy's own exit signal" if tg else
                                     "none: out on the strategy's own exit signal"),
                         "sl_rule": f"{c['stop'] * 100:g}% fixed, checked on the close", "lev": "20x",
                         "chosen_on": (("LOST on " if c["older_lost"] else "made money on ")
                                       + f"the older 70% ({fmt_when(x['start_ms'] / 1000)} to "
                                       f"{fmt_when(x['split_ms'] / 1000)}): {o['trades']} trades, "
                                       f"{o['win_rate']:.0f}% won, {o['profit']:+.2f}, expectancy "
                                       f"{o['expectancy']:+.3f} a trade (the skill's own statistics)"),
                         "check": f"newest 30%: {n['trades']} trades, {n['profit']:+.2f}",
                         "bar": x["bar"], "both": None, "luck": None, "end": int(x["end_ms"]) // 1000,
                         "days": (x["end_ms"] - x["start_ms"]) / 86_400_000,
                         "lost": 1 if c["older_lost"] else 0, "split": int(x["split_ms"]) // 1000, "fwd": 0})
            tlists.append(ts)
    return rows, tlists


def v3_rows(name: str) -> tuple[list, list]:
    """One v3 year's chosen per-coin strategies (a setting chosen on the older days), with their
    unseen trades, through the per-coin page's own payload (its agreement check included)."""
    from tradingagents import v3_per_coin_page as vpp

    store, records = _v3_inputs(name)
    pay = vpp.payload(store, records)
    F = pay["F"]
    split = int(pay["split"]) // 60_000 * 60
    rows, tlists = [], []
    year = {"all-coins": "2026", "all-2025": "2025"}.get(name, name)
    for arr, ts in zip(pay["R"], pay["T"], strict=True):
        r = dict(zip(F, arr))
        if not r["setting"] or not ts:
            continue
        out = []
        for x in ts:
            e = split + x[0] * 60
            # the per-coin page holds a stop and a target as a fraction x 100,000 = percent x 1,000
            out.append([e, e + x[1] * 60, int(x[2]), _why(pay["whys"][x[3]]), int(x[4]),
                        int(x[5]), int(x[6])])
        rows.append({"id": r["id"], "src": f"v3 {year}", "coin": r["coin"].replace("_USDT", ""),
                     "tf": r["tf"], "strategy": f"{r['family'].replace('v3_', '')} {r['filter']} {r['setting']}",
                     "tp_rule": r["target_rule"], "sl_rule": r["stop_rule"],
                     "lev": (f"{r['lev'][0]}x" if r["lev"] and r["lev"][0] == r["lev"][1]
                             else (f"{r['lev'][0]}x-{r['lev'][1]}x" if r["lev"] else "")),
                     "chosen_on": f"older days: {r['older']}", "check": r["verdict"],
                     "bar": r["random_median"], "both": None, "luck": r["luck_share"],
                     "end": int(pay["end"]) // 1000, "days": float(r["days"] or 90),
                     "lost": 0, "split": None, "fwd": 0, "_set": r["setting"],
                     "_key": (r["coin"], r["family"], r["tf"], r["filter"]),
                     "_prof": bool(r["profitable"])})
        tlists.append(out)
    return rows, tlists


def _v3_inputs(name: str):
    from tradingagents import (
        v3_cloud as vc,
        v3_per_coin as vpc,
        v3_research as vrs,
        v3_results_page as vrp,
        v3_universe as vu,
    )

    store = json.loads(vrp.newest_kept(name, vpc.history_dir(),
                                       "python -m tradingagents.v3_per_coin publish")
                       .read_text(encoding="utf-8"))
    plan = vu.load(json.loads(vc._state_path(store["name"]).read_text(encoding="utf-8"))["plan_copy"])
    records, _other = vrs.split_records(vrs.load_coins(vrs.home(store["folder"])), plan,
                                        store["runs"], store["risk_usd"])
    return store, records


def _skill_meta(skill: dict | None) -> dict | None:
    if not skill:
        return None
    return {"pairs": len(skill["lines"]), "failed": skill.get("failed") or [],
            "skipped": skill.get("skipped") or [], "not_reached": skill.get("not_reached") or [],
            "no_trade": sorted(f"{x['coin']} {x['tf']}: {x['bars']} candles, fewer than any "
                               "of the skill's strategies needs to make a trade"
                               for x in skill["lines"].values() if not x["picks"]),
            "collected_s": skill.get("collected_s"),
            "combos": next(iter(skill["lines"].values()))["combos"] if skill["lines"] else 0}


def payload(picks: dict, trades: dict, v3_names=("all-coins", "all-2025"), skill: dict | None = None,
            skill_ta: dict | None = None) -> dict:
    rows, tl, missing = v2_rows(picks, trades)
    for sk in (skill, skill_ta):
        if sk:
            rs, ts = skill_rows(sk)
            rows += rs
            tl += ts
    v3 = {}
    for name in v3_names:
        r3, t3 = v3_rows(name)
        v3[name] = r3
        rows += r3
        tl += t3
    # a v3 group PROFITABLE in both years says so on both rows
    if len(v3_names) == 2:
        a = {r["_key"]: r for r in v3[v3_names[0]]}
        b = {r["_key"]: r for r in v3[v3_names[1]]}
        for k in set(a) & set(b):
            both = a[k]["_prof"] and b[k]["_prof"]
            a[k]["both"] = b[k]["both"] = 1 if both else 0
            # FORWARD-TESTED (Nov 05, 2026): profitable on 2025's unseen days AND the same setting chosen
            # again by 2026's own older days - both known before 2026's unseen days began - judged on
            # 2026's unseen days. Over 119 distinct strategies on 67 coins this beat random entries by
            # +$3.86 a coin (90% range +$1.21 to +$6.50): the one rule in this research that held.
            if b[k]["_prof"] and a[k]["_set"] == b[k]["_set"]:
                a[k]["fwd"] = 1
    for r in rows:
        r.pop("_key", None)
        r.pop("_prof", None)
        r.pop("_set", None)
    return {"F": list(FIELDS), "R": [[r[f] for f in FIELDS] for r in rows], "T": columns(tl),
            "whys": list(WHYS), "base": BASE, "missing": missing,
            "failed": trades.get("failed") or [], "not_reached": trades.get("not_reached") or [],
            "v2_rows_read": picks["rows"], "v2_pairs": len(picks["pairs"]),
            "v2_empty": sum(1 for p in picks["pairs"].values() if not p["picks"]),
            "rule": picks["rule"], "made_s": picks["made_s"], "collected_s": trades.get("collected_s"),
            "v3_names": list(v3_names),
            "skill": _skill_meta(skill), "skill_ta": _skill_meta(skill_ta)}


def columns(tlists: list) -> dict:
    """Every trade of every row, stored by COLUMN (kit F: compress the encoding, never drop a
    field): `n` the trades of each row, then the 7 fields as 7 lists - an entry time as seconds
    after the row's previous entry (the first after 0), an exit as seconds after its own entry.
    The 52,820-row page of Nov 05, 2026 was 18.1 MB as one list per trade, over the 16 MB an
    artifact may be; by column it gzips to 7.2 MB. `uncolumns` (and the page's `untable`) undo it."""
    cols = [[] for _ in range(7)]
    for tl in tlists:
        prev = 0
        for t in tl:
            cols[0].append(t[0] - prev)
            cols[1].append(t[1] - t[0])
            for i in range(2, 7):
                cols[i].append(t[i])
            prev = t[0]
    return {"n": [len(tl) for tl in tlists], "c": cols}


def uncolumns(packed: dict) -> list:
    out, k = [], 0
    c = packed["c"]
    for n in packed["n"]:
        tl, prev = [], 0
        for j in range(k, k + n):
            e = prev + c[0][j]
            tl.append([e, e + c[1][j]] + [c[i][j] for i in range(2, 7)])
            prev = e
        out.append(tl)
        k += n
    return out


def merged(root: Path) -> dict:
    """Every collected run's trade lists together (one file per plan, `acs.collect`); a later run's
    line for the same strategy wins, a coin is "not reached" only if no run brought any of its lines."""
    files = sorted(root.glob("trades-*.json"), key=lambda f: f.stat().st_mtime)
    if not files:
        raise ValueError(f"no collected trade lists in {root}: python -m tradingagents.acs collect")
    lines, no_row, failed, gone, at = {}, set(), [], set(), None
    for f in files:
        t = json.loads(f.read_text(encoding="utf-8"))
        lines.update(t["lines"])
        no_row |= set(t.get("no_row") or [])
        failed += t.get("failed") or []
        gone |= set(t.get("not_reached") or [])
        at = t.get("collected_s") or at
    have = {k.split("|", 1)[0] for k in lines}
    return {"lines": lines, "no_row": sorted(no_row - set(lines)), "failed": failed,
            "not_reached": sorted(gone - have), "collected_s": at}


def pack(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode("ascii")


def write() -> Path:
    from tradingagents import acs

    picks = json.loads((acs.home() / "picks.json").read_text(encoding="utf-8"))
    trades = merged(acs.home())
    def _load(name):
        f = acs.home() / name
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    data = payload(picks, trades, skill=_load("skill.json"), skill_ta=_load("skillta.json"))
    html = _HTML.read_text(encoding="utf-8").replace('const Z="";', f'const Z="{pack(data)}";', 1)
    out = acs.home() / "all-coins-strategies.html"
    out.write_text(html, encoding="utf-8")
    return out


_HTML = Path(__file__).with_name("acs_page.html")
