"""THE CRYPTO-PREDICTOR SEARCH, READ (Oct 19, 2026): which switch settings win.

The operator: "use the strategy and switches and come up with best combination
for all coins", then "use the best combination and see what's setting will
win". The machines kept SUMS per setting x timeframe x stop/target over every
coin (cpw_search.collect -> <home>/merged/sums.npz); this module ranks them,
measures what each switch does, picks the winners for the check run (every
trade kept), and turns the check run's trades into the columns a results table
must carry (CLAUDE.md: profit, TP, SL, wins, losses, the worst losing run,
months, the worst dip).

Two rules that keep the ranking honest:
* settings whose sums are IDENTICAL on every stop/target of a timeframe are
  one strategy there (a switch that changes nothing on that timeframe) — they
  are ranked once and listed together, never as three "winners";
* every setting is compared at ITS OWN best stop/target, and that choice is
  made on the same days it is measured on — said on the page, never hidden.
"""
from __future__ import annotations

import json
from pathlib import Path

from tradingagents import signals_cpw as cp

# what each switch does, in the words the page prints (checked against
# cpw_rules' decide_ functions; values[0] is always the app's own preset)
PLAIN = {
    "session": "London/New York hours only",
    "vol": "volatility needed",
    "ob": "order block needed",
    "fvg": "price gap needed",
    "htfema": "bigger chart's trend must agree",
    "retest": "retest needed",
    "agrade": "only the strongest breakouts",
    "htfema50": "bigger chart's 50-average must agree",
    "stoch": "stochastic must turn",
    "maxbars": "breakout within 8 candles",
    "model": "enter on",
    "htf": "bigger chart's trend must agree",
    "adx": "trend strength needed",
    "volume": "volume spike needed",
    "sweep": "liquidity sweep needed",
    "cisdretest": "wait for the turn's retest",
    "structure": "market structure must agree",
    "momentum": "momentum must agree",
    "minq": "minimum quality",
    "flip": "enter on the flip (not just the trend)",
    "relvol": "volume counts",
    "impulse": "impulse candle counts",
    "di": "DI lines count",
    "zone": "support/resistance zone needed",
    "reject": "close back inside the band",
    "stochx": "stochastic cross (not just oversold)",
    "revcandle": "reversal candle needed",
    "maxadx": "skip strong trends",
    "htf200": "bigger chart's 200-average must agree",
}
# Supertrend's switches are signals that MAY count toward its two-of-many
# rule, not filters — so "counts", never "needed"
VALUE_WORDS = {"retest_confirm": "retest confirmed", "retest_hold": "retest holds",
               "breakout_close": "breakout close", "medium": "medium", "any": "any",
               "high": "high"}


def words(name: str) -> str:
    """'Supertrend + RelVol: enter on the flip ON, volume counts OFF, ...'."""
    spec = cp.spec_for(name)
    parts = []
    for setting, val in spec["switches"].items():
        label = PLAIN.get(setting, setting)
        if isinstance(val, bool):
            parts.append(f"{label} {'ON' if val else 'OFF'}")
        else:
            parts.append(f"{label}: {VALUE_WORDS.get(val, val)}")
    return ", ".join(parts)


def digits_of(name: str) -> tuple:
    """cp_st_f1u0h0x0i0d0 -> (1, 0, 0, 0, 0, 0)."""
    code = name.split("_")[2]
    return tuple(int(code[k]) for k in range(1, len(code), 2))


def preset_of(strategy: str) -> str:
    """The app's own settings for a strategy: every switch at its preset."""
    return cp.name_of(strategy, [0] * len(cp.SWITCHES[strategy]))


def load_sums(path) -> dict:
    """<home>/merged/sums.npz in read_machines' shape."""
    import numpy as np

    with np.load(path) as z:
        tfs = [k[3:] for k in z.files if k.startswith("tf_")]
        return {"names": [str(x) for x in z["names"]], "fields": [str(x) for x in z["fields"]],
                "tf": {tf: np.asarray(z[f"tf_{tf}"], dtype=float) for tf in tfs},
                "barriers": {tf: [(float(a), float(b)) for a, b in z[f"barriers_{tf}"]]
                             for tf in tfs}}


def twins(merged: dict, tf: str) -> dict:
    """name -> the first name (in the list's order) whose sums are identical
    to it on every stop/target of `tf`: the same strategy there."""
    arr = merged["tf"][tf]
    first: dict = {}
    out = {}
    for i, name in enumerate(merged["names"]):
        key = (cp.spec_for(name)["strategy"], arr[i].tobytes())
        out[name] = first.setdefault(key, name)
    return out


def ranking(merged: dict) -> dict:
    """(strategy, tf) -> one line per DISTINCT setting at its best
    stop/target, most profitable first, each naming its twins."""
    from tradingagents import cpw_search as search

    best = search.best_by_setting(search.cells(merged))
    out: dict = {}
    for tf in merged["tf"]:
        tw = twins(merged, tf)
        groups: dict = {}
        for name in merged["names"]:
            groups.setdefault(tw[name], []).append(name)
        for head, members in groups.items():
            cell = best.get((head, tf))
            if cell is None:
                continue                       # never traded on this timeframe
            st = cp.spec_for(head)["strategy"]
            out.setdefault((st, tf), []).append({**cell, "same": members})
    for lines in out.values():
        lines.sort(key=lambda c: (-c["profit"], c["name"]))
    return out


def effects(merged: dict) -> list:
    """What each switch does, per strategy and timeframe: every pair of
    settings that differ ONLY in that switch (preset value against the other),
    each at its own best stop/target — how many pairs the change made more
    money, fewer, the same, and by how much on average."""
    from tradingagents import cpw_search as search

    best = search.best_by_setting(search.cells(merged))
    out = []
    for tf in merged["tf"]:
        for st, sw in cp.SWITCHES.items():
            names = {digits_of(n): n for n in merged["names"]
                     if cp.spec_for(n)["strategy"] == st}
            for j, (_letter, setting, values) in enumerate(sw):
                for v in range(1, len(values)):
                    diffs = []
                    for dg, a in names.items():
                        if dg[j] != 0:
                            continue
                        b = names.get(dg[:j] + (v,) + dg[j + 1:])
                        if b is None:
                            continue
                        pa = best.get((a, tf), {}).get("profit", 0.0)
                        pb = best.get((b, tf), {}).get("profit", 0.0)
                        diffs.append(pb - pa)
                    if not diffs:
                        continue
                    out.append({"strategy": st, "tf": tf, "switch": setting,
                                "from": values[0], "to": values[v], "pairs": len(diffs),
                                "better": sum(1 for d in diffs if d > 0.005),
                                "worse": sum(1 for d in diffs if d < -0.005),
                                "same": sum(1 for d in diffs if abs(d) <= 0.005),
                                "mean": round(sum(diffs) / len(diffs), 2)})
    return out


def choose(merged: dict, top: int = 3) -> list:
    """The check run's settings: per strategy and timeframe, the `top` most
    profitable DISTINCT settings and the app's preset, each at its own best
    stop/target, with why it was chosen."""
    rank = ranking(merged)
    out, seen = [], set()
    for (st, tf), lines in sorted(rank.items()):
        picks = [(k + 1, c) for k, c in enumerate(lines[:top])]
        preset = preset_of(st)
        for k, c in enumerate(lines):
            if preset in c["same"]:
                picks.append((k + 1, c))
                break
        for place, c in picks:
            key = (c["name"], tf, c["sl"], c["tp"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": c["name"], "tf": tf, "sl": c["sl"], "tp": c["tp"],
                        "place": place, "of": len(lines), "same": c["same"],
                        "preset": preset in c["same"],
                        "search": {k2: c[k2] for k2 in ("pairs", "pairs_up", "trades",
                                                         "wins", "profit")}})
    return out


def configs_arg(cfgs: list) -> str:
    """The check run's `configs` input: name:tf:sl:tp,..."""
    return ",".join(f"{c['name']}:{c['tf']}:{c['sl']:g}:{c['tp']:g}" for c in cfgs)


# ------------------------------------------------- the check run's trades

def read_check(roots) -> dict:
    """config key -> its lines (one per coin), from cpw-trades-*.jsonl."""
    import glob

    out: dict = {}
    for r in roots:
        for f in sorted(glob.glob(str(Path(r) / "**" / "cpw-trades-*.jsonl"), recursive=True)):
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        d = json.loads(line)
                        out.setdefault(d["cfg"], []).append(d)
    return out


def _month(ms: int) -> str:
    import datetime as dt

    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m")


def stats(lines: list, start_ms: int | None = None) -> dict:
    """Every column of one setting over every coin, from its trades — those
    OPENED at or after `start_ms` when given (a last-N-days window). The worst
    losing run and the worst dip walk the trades in the order they CLOSED,
    across coins, with the engine's own rule (a trade that made nothing
    breaks no run: only a win does)."""
    trades = []
    for d in lines:
        for t in d["trades"]:
            if start_ms is None or t[0] >= start_ms:
                trades.append((t[1], t[0], d["coin"], t[4]))
    trades.sort()
    wins = sum(1 for t in trades if t[3] > 0)
    run = worst = 0.0
    run_n = worst_n = 0
    eq = peak = dd = 0.0
    monthly: dict = {}
    by_coin: dict = {}
    for exit_ms, _entry, coin, pnl in trades:
        if pnl > 0:
            run, run_n = 0.0, 0
        else:
            run += pnl
            run_n += 1
            if run < worst:
                worst, worst_n = run, run_n
        eq += pnl
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        m = _month(exit_ms)
        monthly[m] = monthly.get(m, 0.0) + pnl
        by_coin[coin] = by_coin.get(coin, 0.0) + pnl
    n = len(trades)
    return {"trades": n, "wins": wins, "losses": n - wins,
            "winrate": round(100.0 * wins / n, 2) if n else 0.0,
            "profit": round(sum(t[3] for t in trades), 2),
            "streak": round(worst, 2), "streak_len": worst_n, "dd": round(dd, 2),
            "monthly": {k: round(v, 2) for k, v in sorted(monthly.items())},
            "green": sum(1 for v in monthly.values() if v > 0), "months": len(monthly),
            "coins": len(by_coin), "coins_up": sum(1 for v in by_coin.values() if v > 0)}


def combos(merged: dict) -> int:
    """setting x coin x timeframe x stop/target combinations that traded —
    what the search measured and kept a number for."""
    k = merged["fields"].index("pairs")
    return int(sum(float(a[:, :, k].sum()) for a in merged["tf"].values()))


# ------------------------------------------------------------- the page

WHY = ("TP", "SL", "END", "LIQ")
DAY_MS = 86_400_000
WINDOW_DAYS = 31        # every last-N-days window the page can ask, 1..31


def _month_start(ms: int, back: int) -> int:
    """The first instant (UTC) of the month `back` months before `ms`'s."""
    import datetime as dt

    d = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    y, m = d.year, d.month - back
    while m < 1:
        y, m = y - 1, m + 12
    return int(dt.datetime(y, m, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


def end_of(check: dict) -> int:
    """Where the check run's candles end: the latest bar any row measured,
    closed — the anchor every last-N-days window counts back from."""
    from tradingagents import backtest_report as br

    end = 0
    for lines in check.values():
        for d in lines:
            last = int(d["row"].get("last_ms") or 0)
            end = max(end, last + br.TFS[d["tf"]][1] * 1000)
    return end


def row_id(c: dict) -> str:
    """A stable id hashed from the combination (CLAUDE.md kit H): every coin
    ("ALL"), the timeframe, the setting, its stop and target."""
    from tradingagents import backtest_report as br

    return br.row_code("ALL", c["tf"], c["name"], 0.0, c["sl"], c["tp"], "flat", res="1m")


def page_rows(cfgs: list, check: dict) -> tuple:
    """(rows, trade files): every chosen setting with every column over the
    whole window, each last-N-days window and each last-N-months window, and
    its trades for the click."""
    end = end_of(check)
    rows, files = [], {}
    for c in cfgs:
        key = f"{c['name']}:{c['tf']}:{c['sl']:g}:{c['tp']:g}"
        lines = check.get(key) or []
        rid = row_id(c)
        coins = sorted({d["coin"] for d in lines})
        ci = {k: i for i, k in enumerate(coins)}
        trades = sorted(([ci[d["coin"]], t[0] // 1000, t[1] // 1000, t[2], WHY.index(t[3]),
                          t[4]] for d in lines for t in d["trades"]),
                        key=lambda t: (t[2], t[1], t[0]))
        files[rid] = {"coins": coins, "t": trades}
        listed = sum(1 for d in lines if _listed(d["row"]))
        rows.append({
            "id": rid, "st": cp.spec_for(c["name"])["strategy"], "tf": c["tf"],
            "name": c["name"], "words": words(c["name"]), "same": c["same"],
            "place": c["place"], "of": c["of"], "preset": c["preset"],
            "sl": c["sl"], "tp": c["tp"], "search": c["search"], "listed": listed,
            "all": stats(lines),
            "days": [stats(lines, end - n * DAY_MS) for n in range(1, WINDOW_DAYS + 1)],
            "months": [stats(lines, _month_start(end - 1, k)) for k in range(0, 2)]})
    return rows, files, end


def _listed(row: dict) -> bool:
    from tradingagents import backtest_report as br

    try:
        return bool(br.index_keeps(row))
    except Exception:                                          # noqa: BLE001
        return False


def _val(v) -> str:
    if isinstance(v, bool):
        return "ON" if v else "OFF"
    return str(VALUE_WORDS.get(v, v))


def chips(name: str) -> list:
    """[label, on] per switch, for the page's switch chips."""
    spec = cp.spec_for(name)
    out = []
    for setting, val in spec["switches"].items():
        label = PLAIN.get(setting, setting)
        if isinstance(val, bool):
            out.append([label, val])
        else:
            out.append([f"{label}: {_val(val)}", True])
    return out


def page_json(merged: dict, cfgs: list, check: dict, *, meta: dict) -> tuple:
    """(the page's data, {row id: its trade file}). `meta` carries what the
    collect knows: the search's dates, coins and the files it wrote."""
    rows, files, end = page_rows(cfgs, check)
    for r in rows:
        r["chips"] = chips(r["name"])
    effs = []
    for e in effects(merged):
        effs.append({**e, "label": f"{PLAIN.get(e['switch'], e['switch'])}: "
                                   f"{_val(e['from'])} → {_val(e['to'])}"})
    rank = ranking(merged)
    distinct = sum(len(v) for v in rank.values())
    start = end - 30 * DAY_MS
    m = {**meta, "end_ms": end, "start_ms": start, "days": 30,
         "month_starts": [_month_start(end - 1, 0), _month_start(end - 1, 1)],
         "timeframes": [t for t in ("15m", "30m", "1h", "4h", "1d") if t in merged["tf"]],
         "distinct": distinct, "settings": len(merged["names"]), "lev": 20}
    return ({"meta": m, "window_days": WINDOW_DAYS, "strategies": dict(cp.NAMES),
             "rows": rows, "effects": effs}, files)
