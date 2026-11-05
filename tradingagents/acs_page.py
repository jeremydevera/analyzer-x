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

WHYS = ("TP", "SL", "TRAIL", "MA", "TIME", "END", "RANK", "OTHER")
FIELDS = ("id", "src", "coin", "tf", "strategy", "tp_rule", "sl_rule", "lev", "chosen_on", "check",
          "bar", "both", "luck", "end", "days")
BASE = 5.0


def _why(text: str) -> int:
    t = str(text).upper()
    for i, w in enumerate(WHYS):
        if t.startswith(w):
            return i
    return WHYS.index("OTHER")


def v2_rows(picks: dict, trades: dict) -> tuple[list, list, list]:
    """The v2 picks with their re-measured trades. A pick GitHub returned no line for is NAMED in
    the third list with why, never dropped silently (rule 20)."""
    lines = trades["lines"]
    no_row = set(trades.get("no_row") or [])
    gone = set(trades.get("not_reached") or [])
    rows, tlists, missing = [], [], []
    for pair in sorted(picks["pairs"]):
        p = picks["pairs"][pair]
        bar = p["bar"]
        for r in p["picks"]:
            cfg = f"{r['signal']}:{float(r['th']):g}:{float(r['sl']):g}:{float(r['tp']):g}"
            line = lines.get(f"{p['coin']}|{p['tf']}|{cfg}")
            if line is None:
                key = f"{p['coin']}|{p['tf']}|{cfg}"
                why = ("GitHub's re-measure a day later made no row: no trade in the moved window, or it "
                       "no longer passes the list's 2:1 after fees" if key in no_row else
                       "its coin was not reached (the exchange no longer listed it to the machines)"
                       if p["coin"] in gone else "no trade list came back")
                missing.append(f"#{r['id']} {p['coin']} {p['tf']} {cfg}: {why}")
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
            end = int(line["row"].get("last_ms") or (ts[-1][1] * 1000 if ts else 0)) // 1000
            rows.append({"id": r["id"], "src": "v2", "coin": p["coin"], "tf": p["tf"],
                         "strategy": f"{r['signal']}" + (f" th {float(r['th']):g}" if float(r["th"]) else ""),
                         "tp_rule": f"{float(r['tp']):g}% fixed", "sl_rule": f"{float(r['sl']):g}% fixed",
                         "lev": "20x", "chosen_on": (f"older 15 days of the stored backtest: {o['trades']} "
                                                     f"trades, {o['wins']} won, {o['profit']:+.2f}"),
                         "check": f"stored newest 15 days: {r['t15']} trades, {r['w15']} won, {float(r['p15']):+.2f}",
                         "bar": bar["per_trade"], "both": None, "luck": None, "end": end,
                         "days": float(line["row"].get("days") or 30)})
            tlists.append(ts)
    return rows, tlists, missing


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


def payload(picks: dict, trades: dict, v3_names=("all-coins", "all-2025")) -> dict:
    rows, tl, missing = v2_rows(picks, trades)
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
    for r in rows:
        r.pop("_key", None)
        r.pop("_prof", None)
    return {"F": list(FIELDS), "R": [[r[f] for f in FIELDS] for r in rows], "T": tl,
            "whys": list(WHYS), "base": BASE, "missing": missing,
            "failed": trades.get("failed") or [], "not_reached": trades.get("not_reached") or [],
            "v2_rows_read": picks["rows"], "v2_pairs": len(picks["pairs"]),
            "v2_empty": sum(1 for p in picks["pairs"].values() if not p["picks"]),
            "rule": picks["rule"], "made_s": picks["made_s"], "collected_s": trades.get("collected_s"),
            "v3_names": list(v3_names)}


def pack(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, 9, mtime=0)).decode("ascii")


def write() -> Path:
    from tradingagents import acs

    picks = json.loads((acs.home() / "picks.json").read_text(encoding="utf-8"))
    trades = json.loads((acs.home() / "trades.json").read_text(encoding="utf-8"))
    html = _HTML.read_text(encoding="utf-8").replace('const Z="";', f'const Z="{pack(payload(picks, trades))}";', 1)
    out = acs.home() / "all-coins-strategies.html"
    out.write_text(html, encoding="utf-8")
    return out


_HTML = Path(__file__).with_name("acs_page.html")
