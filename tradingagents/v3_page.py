"""THE BACKTEST V3 TAB — one coin and one idea, run the v3 way on request.

Operator, Oct 23, 2026: *"i dont see it in ui where is it i said to create
backtest v3 tab"*, then *"Tab now, fill it later"*. The tab opens now with a
run of the coin and idea the operator picks (`run`), and its tested-ideas
section says plainly that it fills when Part 2's GitHub test of every idea on
every coin has run (`tested`).

ONE measurement: `run` calls `v3_smoke.measure`, the code
`python -m tradingagents.v3_smoke` runs, so the tab and the command line can
never disagree on a trade. Every figure the tab prints is derived here from
the run — the profit is the sum of the trade rows as shown (to the cent),
wins and losses add up to the trades, the worst losing run is the run's own
— never a number typed in.
"""
from __future__ import annotations

import time
from decimal import ROUND_HALF_UP, Decimal

DAYS = (30, 60, 90, 120, 180, 365)
DEFAULT_DAYS = 30           # operator, Sep 10, 2026: "it should always default to past 30 days"
RISK = {"default": 1.0, "min": 0.1, "max": 100.0}
DEFAULTS = {"sym": "BTC_USDT", "tf": "1h", "signal": "bb20", "exit": "fixed"}

# the three exits Backtest v3 trades (spec Part 3), with the boxes the tab
# shows for each — in the units the boxes print (percent, multiples, candles)
EXITS = {
    "fixed": {"label": "Fixed target and stop", "fields": [
        {"key": "tp_pct", "label": "Target %", "default": 2.0, "min": 0.05, "max": 50.0},
        {"key": "sl_pct", "label": "Stop %", "default": 1.0, "min": 0.05, "max": 50.0}]},
    "trail": {"label": "Trailing stop", "fields": [
        {"key": "atr_mult", "label": "Trail (x ATR of 20 candles)", "default": 3.0,
         "min": 0.5, "max": 10.0},
        {"key": "ma_n", "label": "Also close past its average of (candles, 0 = off)",
         "default": 0, "min": 0, "max": 400, "whole": True}]},
    "snap": {"label": "Snap back to the 20-candle average", "fields": [
        {"key": "stop_atr", "label": "Emergency stop (x ATR of 20 candles)", "default": 3.0,
         "min": 0.5, "max": 10.0},
        {"key": "max_bars", "label": "Close after (candles)", "default": 24, "min": 1,
         "max": 500, "whole": True}]},
}

# how each exit and each missed order reads on the screen
HOW = {"TP": "target", "SL": "stop", "TRAIL": "trailing stop", "MA": "closed past its average",
       "TIME": "time limit", "END": "still open at the end"}
MISSED_HOW = {"not_traded_through": "the price never traded through it",
              "post_only_reject": "cancelled: it would have filled at once (post-only)"}


def cents(x: float) -> float:
    """Money as the screen prints it: to the cent, a half cent away from zero."""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def worst_run(pnls: list) -> tuple[float, int]:
    """The worst unbroken run of losing trades, as (its sum, how many trades),
    in the order the trades closed; (0.0, 0) when nothing lost."""
    worst, worst_n, cur, cur_n = 0.0, 0, 0.0, 0
    for v in pnls:
        if v <= 0:
            cur, cur_n = cur + v, cur_n + 1
            if cur < worst:
                worst, worst_n = cur, cur_n
        else:
            cur, cur_n = 0.0, 0
    return cents(worst) if worst_n else 0.0, worst_n


def tested(rows_db=None) -> dict:
    """What the tab's tested-ideas section can say today. Part 2 writes the
    v3 store; until it exists nothing has been tested and the section says so."""
    from tradingagents import stores

    path = stores.V3.rows_db if rows_db is None else rows_db
    if not path.exists():
        return {"state": "not_run", "rows": 0,
                "words": "The test of every idea on every coin (step 2 of the Backtest v3 plan) "
                         "has not run yet, so no idea has been tested against random entries. "
                         "This section fills when it does."}
    return {"state": "stored", "rows": None,
            "words": "The v3 store holds tested ideas; listing them here is step 4 of the plan."}


def options(*, fx=None) -> dict:
    """Everything the tab's boxes offer, from the registries — never typed in."""
    from tradingagents import backtest_report as br, stores, venue

    if fx is None:
        from tradingagents.dataflows import exchange as fx
    try:
        coins, coins_error = sorted(fx.trading_symbols()), ""
    except Exception as exc:                                   # noqa: BLE001
        coins, coins_error = [], f"{type(exc).__name__}: {exc}"
    return {"venue": venue.name(), "coins": coins, "coins_error": coins_error,
            "tfs": list(stores.FIVE), "signals": list(br.SIGNALS),
            "thresh_signals": sorted(br.THRESH_SIGNALS), "days": list(DAYS),
            "default_days": DEFAULT_DAYS, "exits": EXITS, "risk": RISK, "defaults": DEFAULTS,
            "tested": tested()}


def _number(raw, field: dict) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{field['label']}: type a number") from None
    if not field["min"] <= v <= field["max"]:
        raise ValueError(f"{field['label']}: between {field['min']:g} and {field['max']:g}")
    if field.get("whole") and v != int(v):
        raise ValueError(f"{field['label']}: a whole number")
    return v


def parse(body: dict, coins=None) -> dict:
    """The tab's choices, checked, in the engine's units (fractions). A bad
    pick is refused naming the box it came from."""
    from tradingagents import backtest_report as br, stores

    sym = str(body.get("sym") or "").strip().upper()
    if not sym:
        raise ValueError("coin: pick one")
    if coins is not None and sym not in coins:
        raise ValueError(f"{sym} is not a coin the exchange lists")
    tf = body.get("tf")
    if tf not in stores.FIVE:
        raise ValueError(f"timeframe: pick one of {', '.join(stores.FIVE)}")
    signal = body.get("signal")
    if signal not in br.SIGNALS:
        raise ValueError(f"idea: {signal!r} is not a stored signal")
    kind = body.get("exit")
    if kind not in EXITS:
        raise ValueError(f"exit: pick one of {', '.join(EXITS)}")
    raw = body.get("params") or {}
    vals = {f["key"]: _number(raw.get(f["key"], f["default"]), f) for f in EXITS[kind]["fields"]}
    try:
        days = int(body.get("days") or DEFAULT_DAYS)
    except (TypeError, ValueError):
        raise ValueError("days: pick one of the listed windows") from None
    if days not in DAYS:
        raise ValueError(f"days: pick one of {', '.join(str(d) for d in DAYS)}")
    risk = _number(body.get("risk_usd", RISK["default"]),
                   {"label": "risk per trade $", "min": RISK["min"], "max": RISK["max"]})
    th_pct = None
    if signal in br.THRESH_SIGNALS and body.get("th_pct") not in (None, ""):
        th_pct = _number(body["th_pct"], {"label": "threshold %", "min": 0.01, "max": 20.0})
    if kind == "fixed":
        spec = {"kind": "fixed", "tp": vals["tp_pct"] / 100, "sl": vals["sl_pct"] / 100}
    elif kind == "trail":
        spec = {"kind": "trail", "atr_mult": vals["atr_mult"],
                "ma_n": int(vals["ma_n"]) or None}
    else:
        spec = {"kind": "snap", "mean_n": 20, "stop_atr": vals["stop_atr"],
                "max_bars": int(vals["max_bars"])}
    return {"sym": sym, "tf": tf, "signal": signal, "kind": kind, "params": vals,
            "spec": spec, "days": days, "risk_usd": risk, "th_pct": th_pct,
            "th": None if th_pct is None else th_pct / 100}


def row_id(p: dict) -> str:
    """The run's stable id: the combination hashed with res="v3" (never a v1
    or v2 id). A trailing or snap exit has no target or stop, so its exit
    rule rides in `plan` (final review of Part 1: otherwise two settings share
    an id). The risk box is not part of it: risk changes dollars, never which
    strategy it is."""
    from tradingagents import backtest_report as br

    th = p["th_pct"] or 0.0
    if p["kind"] == "fixed":
        return br.row_code(p["sym"], p["tf"], p["signal"], th, p["params"]["sl_pct"],
                           p["params"]["tp_pct"], "flat", res="v3")
    v = p["params"]
    plan = (f"trail:{v['atr_mult']:g}:{int(v['ma_n'])}" if p["kind"] == "trail"
            else f"snap:{v['stop_atr']:g}:{int(v['max_bars'])}")
    return br.row_code(p["sym"], p["tf"], p["signal"], th, 0.0, 0.0, "flat", plan=plan, res="v3")


def exit_words(p: dict) -> str:
    v = p["params"]
    if p["kind"] == "fixed":
        return f"target {v['tp_pct']:g}% and stop {v['sl_pct']:g}%"
    if p["kind"] == "trail":
        also = (f", also closes past its {int(v['ma_n'])}-candle average"
                if int(v["ma_n"]) else "")
        return f"trailing stop {v['atr_mult']:g} x ATR(20){also}"
    return (f"back to the 20-candle average, emergency stop {v['stop_atr']:g} x ATR(20), "
            f"out after {int(v['max_bars'])} candles")


def run(body: dict, *, fx=None) -> dict:
    """One press of the tab's Run button: the choices checked, the v3 walk,
    and every row and figure the tab prints."""
    from tradingagents import v3_smoke, venue

    if fx is None:
        from tradingagents.dataflows import exchange as fx
    p = parse(body, coins=set(fx.trading_symbols()))
    t0 = time.time()
    m = v3_smoke.measure(p["sym"], p["tf"], p["signal"], p["spec"], days=p["days"],
                         th=p["th"], risk_usd=p["risk_usd"], fx=fx)
    got, t = m["walk"], m["t"]
    rows, total = [], 0.0
    for k, x in enumerate(got["trades"], 1):
        pnl = cents(x["pnl"])
        total = cents(total + pnl)
        rows.append({
            "n": k, "side": "long" if x["side"] == 1 else "short",
            "signal_ms": int(t[x["signal_bar"]]), "entry_ms": int(x["entry_ms"]),
            "entry": x["entry"], "exit_ms": int(x["exit_ms"]), "exit": x["exit"],
            "why": x["why"], "how": HOW.get(x["why"], x["why"]),
            "contracts": x["contracts"], "notional": cents(x["notional"]),
            "leverage": x["leverage"], "margin": cents(x["margin"]),
            "fee_in": round(x["notional"] * x["fee_in"], 4),
            "fee_out": round(x["notional"] * x["fee_out"], 4),
            "gap_out": round(x["notional"] * x["slip_out"], 4),
            "funding": round(x["funding"], 4), "pnl": pnl, "total": total,
            "measured_exit": bool(x["measured_exit"]),
            "funding_estimated": bool(x["funding_estimated"])})
    missed = []
    for x in got["missed"]:
        mk = x["market"]
        twin = ({"refused": mk["refused"]} if "pnl" not in mk else
                {"entry": mk["entry"], "entry_ms": int(mk["entry_ms"]), "exit": mk["exit"],
                 "exit_ms": int(mk["exit_ms"]), "why": mk["why"],
                 "how": HOW.get(mk["why"], mk["why"]), "pnl": cents(mk["pnl"])})
        why = x.get("why", "not_traded_through")
        missed.append({"signal_ms": int(x["signal_ms"]),
                       "side": "long" if x["side"] == 1 else "short", "limit": x["limit"],
                       "why": why, "how": MISSED_HOW.get(why, why), "market": twin})
    pnls = [r["pnl"] for r in rows]
    wins = sum(1 for v in pnls if v > 0)
    win_avg = sum(v for v in pnls if v > 0) / wins if wins else None
    losses = len(pnls) - wins
    loss_avg = -sum(v for v in pnls if v <= 0) / losses if losses else None
    worst, worst_n = worst_run(pnls)
    counts = got["counts"]
    twins = [r["market"] for r in missed if "pnl" in r["market"]]
    lev = [r["leverage"] for r in rows]
    notional = [r["notional"] for r in rows]
    summary = {
        "trades": len(rows), "wins": wins, "losses": losses,
        "win_rate": wins / len(rows) if rows else None,
        "break_even": (loss_avg / (win_avg + loss_avg)
                       if win_avg is not None and loss_avg is not None and win_avg + loss_avg
                       else None),
        "profit": total, "worst_run_usd": worst, "worst_run_trades": worst_n,
        "leverage_min": min(lev) if lev else None, "leverage_max": max(lev) if lev else None,
        "notional_min": min(notional) if notional else None,
        "notional_max": max(notional) if notional else None,
        "not_filled": sum(1 for r in missed if r["why"] == "not_traded_through"),
        "post_only_reject": sum(1 for r in missed if r["why"] == "post_only_reject"),
        "refused": sum(int(counts.get(k, 0)) for k in
                       ("gate_blocked", "chase_skip", "closed_skip", "too_small",
                        "unsafe_stop", "no_levels")),
        "missed_entered": len(twins), "missed_pnl": cents(sum(r["pnl"] for r in twins)),
        "open_at_end": sum(1 for r in rows if r["why"] == "END"),
        "counts": counts, "combos": 1}
    provenance = {
        "sym": p["sym"], "tf": p["tf"], "signal": p["signal"], "th_pct": p["th_pct"],
        "exit": p["kind"], "exit_words": exit_words(p), "params": p["params"],
        "days": p["days"], "start_ms": int(m["from_s"]) * 1000, "end_ms": int(m["end_s"]) * 1000,
        "venue": venue.name(), "risk_usd": p["risk_usd"], "maker_fee": m["fees"]["maker"],
        "taker_fee": m["fees"]["taker"], "flat_slip": m["flat_slip"],
        "coverage": m["coverage"], "candles": len(t) - m["lead"], "points": m["points"]}
    return {"id": row_id(p), "provenance": provenance, "summary": summary, "trades": rows,
            "missed": missed, "elapsed_s": round(time.time() - t0, 1)}
