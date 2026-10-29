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

THE FOUR V3 FAMILIES on one coin (operator, Oct 27, 2026: "go" to "both"):
`run_family` walks one family x setting x filter over the tab's window with
the research's own pieces - `v3_measure.read_window` (the coin read the way
the research reads it, its OWN flat gap), `v3_families.rule` / `forced` /
`sides_allowed` / `exit_spec`, `v3_filters.masks`, `v3_measure.allowed` /
`dirs_of` / `_signals` and `v3_engine.walk` - one walk, no older / unseen
split and no random runs: a look at one idea on one coin, never the proof.
The universe is the committed plan's (`v3_universe.load`); after the plan's
end the plan's last month's membership stands in, said on the page.

THE 3-COIN CHECK (`tested()["check"]`): the verdicts `v3_research` judged on
this PC, with their provenance (plan, risk, runs, coins, when), shown on the
tab as a check of the machinery - never the proof, which needs every coin.
"""
from __future__ import annotations

import bisect
import time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

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
       "TIME": "time limit", "END": "still open at the end",
       "RANK": "out at a Monday's rank"}
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


def tested(store_file=None, check_file=None) -> dict:
    """What the tab's tested-ideas section can say today: the verdict store
    `python -m tradingagents.v3_verdicts publish` writes (Part 2b), as
    `store` - every verdict, its provenance and how many coins it did NOT
    judge, by why - or, until a run is published, that nothing has been
    tested. Beside it, `check`: the 3-coin check `v3_research` judged on this
    PC (`check()`), labelled a check on the page, never the proof."""
    import json

    from tradingagents import v3_verdicts as vv

    path = vv.store_path() if store_file is None else Path(store_file)
    if not path.exists():
        out = {"state": "not_run", "rows": 0, "store": None,
               "words": "The test of every idea on every coin (step 2 of the Backtest v3 plan) "
                        "has not run yet, so no idea has been tested against random entries. "
                        "This section fills when it does."}
        return {**out, "check": check(check_file)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        out = {"state": "unreadable", "rows": 0, "store": None,
               "words": f"The verdict store {path} could not be read ({type(exc).__name__}: "
                        f"{exc})"}
        return {**out, "check": check(check_file)}
    view = store_view(data)
    return {"state": "stored", "rows": len(view["verdicts"]), "store": view,
            "words": stored_words(view), "check": check(check_file)}


def stored_words(view: dict) -> str:
    """The sentence above the stored verdicts, every number from the store: how
    many passed, on how many of the plan's coins, judged when - and, when fewer
    coins were judged than the plan holds, that it is not the proof."""
    from tradingagents.positions_view import fmt_when

    n, passed = len(view["verdicts"]), sum(1 for r in view["verdicts"] if r["passed"])
    coins, plan_coins = len(view["coins"]), view.get("plan_coins") or 0
    head = (f"{passed} of {n} judged ideas passed against random entries, judged "
            f"{fmt_when(view['judged_at'])} on {coins} of the plan's {plan_coins} coins")
    sent = view.get("dispatched")
    if sent is not None and sent < plan_coins:
        # a PILOT is a run that was SENT fewer coins than the plan holds; read from the run's state
        return head + " - a pilot of the machinery, not the proof: the proof pools every coin."
    if coins < plan_coins:
        return (f"{passed} of {n} judged ideas passed against random entries, judged "
                f"{fmt_when(view['judged_at'])} - a full run with {plan_coins - coins} of the "
                f"plan's {plan_coins} coins not judged (named below), {coins} judged.")
    return head + "."


def store_view(data: dict) -> dict:
    """A verdicts file - the 3-coin check's or the verdict store - as the tab
    shows it: {"coins", "risk_usd", "runs", "judged_at" (seconds), "plan_end"
    (ms), "plan_id", "lev", "notional", "tried", "plan_coins", "name",
    "not_judged" ({why: how many coins}), "verdicts": one row per verdict,
    every column filled or saying why}."""
    vs = data.get("verdicts") or []
    lev = [x for v in vs for x in (v.get("lev") or [])]
    notional = [x for v in vs for x in (v.get("notional") or [])]
    nj = data.get("not_judged") or {}
    accounts = {k: x for k, x in (data.get("accounts") or {}).items() if x}
    return {"coins": list(data.get("coins") or []), "risk_usd": data.get("risk_usd"),
            "runs": data.get("runs"), "judged_at": data.get("judged_at"),
            "plan_end": data.get("plan_end"), "plan_id": data.get("plan_id"),
            "lev": [min(lev), max(lev)] if lev else None,
            "notional": [min(notional), max(notional)] if notional else None,
            "tried": data.get("tried"), "plan_coins": data.get("plan_coins"),
            "name": data.get("name"), "dispatched": data.get("dispatched"),
            "family": list(data.get("family") or []),
            "not_judged": {k: len(x) for k, x in nj.items() if x},
            "not_judged_coins": {k: list(x) for k, x in nj.items() if x},
            "accounts": accounts,
            "verdicts": [check_row(v) for v in vs]}


CHECK_OLD = ("This check's verdicts were made before its details were kept (which plan, risk and "
             "coins) - run judge again: python -m tradingagents.v3_research judge")


def check(path=None) -> dict:
    """The check's verdicts file (`v3_research` writes it beside the coins it
    measured) as the tab shows it: {"state": "ok", **store_view(file)}. A file
    written before its provenance was kept (a bare list) is "old" and says to
    judge again; no file is "none"; a file that cannot be read is
    "unreadable", naming why."""
    import json

    from tradingagents import v3_research as vrs

    p = vrs.home(vrs.DEFAULT_LABEL) / "verdicts.json" if path is None else path
    if not p.exists():
        return {"state": "none", "words": "The 3-coin check has not been judged on this PC: "
                                          "python -m tradingagents.v3_research run BTC_USDT "
                                          "XAU_USDT ETH_USDT"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"state": "unreadable", "words": f"The check's file {p} could not be read "
                                                f"({type(exc).__name__}: {exc})"}
    if isinstance(data, list):
        return {"state": "old", "words": CHECK_OLD, "verdicts": len(data)}
    return {"state": "ok", **store_view(data)}


def _pct_range(xs) -> str | None:
    """[least, median, most] fractions -> "0.70% (0.41%-1.92%)", or None."""
    if not xs:
        return None
    lo, mid, hi = (100 * float(x) for x in xs)
    return f"{mid:.2f}% ({lo:.2f}%-{hi:.2f}%)"


def level_words(lv: dict, which: str) -> str:
    """A verdict's stop or target sizes in words: "0.70% (0.41%-1.92%)" (the
    median, then the least and the most), "none: a trailing stop has no
    target", or "not recorded" for a verdict judged from records whose trade
    rows did not keep them (Part 2a's)."""
    if not lv.get("trades"):
        return "not recorded"
    got = _pct_range(lv.get(which))
    if got is None:
        return "none: a trailing stop has no target" if which == "target" else "not recorded"
    return got


NO_COSTS = "not recorded: judged before the share was kept - judge again"


def check_row(v: dict) -> dict:
    """One verdict as the tab's tables print it - the kit's columns: id,
    profit, the target and stop rules (and, from the store's `levels`, their
    sizes), leverage, wins and losses, the worst losing run, trades and trades
    a day, wins and losses a day, and beside the verdict its typical-cost share
    (`costs`, COVERAGE FIRST: the unseen days of the chosen setting and the
    older days of every setting compared). A number the verdict does not have is
    None with `blank` saying why, so no cell is ever empty."""
    from tradingagents import v3_coverage as vcv, v3_research as vrs
    from tradingagents.v3_measure import UNSEEN_DAYS

    chose = v.get("failed") == "choose"
    s = v.get("unseen") or {}
    rr = v.get("random_runs") or {}
    if chose:
        blank = "not judged: no setting was chosen"
    elif not s.get("trades"):
        blank = "no trade on the unseen days"
    else:
        blank = ""
    trades = None if chose else int(s.get("trades") or 0)
    has = bool(trades)
    target = stop = None
    if v.get("setting"):
        target, stop = vrs.exit_words(v["family"], v["setting"], v["tf"])
    lv = v.get("levels") or {}
    lev = v.get("lev") if has else None
    costs = v.get("costs")
    unseen_c = (costs or {}).get("unseen")
    out = {"id": v["id"], "family": v["family"], "tf": v["tf"], "filter": v["filter"],
            "setting": v.get("setting"), "passed": bool(v.get("passed")),
            "failed": v.get("failed") or "",
            "verdict": "PASSED" if v.get("passed") else f"FAILED at {v.get('failed')}",
            "trades": trades, "wins": s.get("wins") if has else None,
            "losses": s.get("losses") if has else None,
            "win_rate": s.get("win_rate") if has else None,
            "profit": cents(s["profit"]) if has and s.get("profit") is not None else None,
            "per_day": round(trades / UNSEEN_DAYS, 2) if has else None,
            "wins_per_day": round(int(s.get("wins") or 0) / UNSEEN_DAYS, 2) if has else None,
            "losses_per_day": round(int(s.get("losses") or 0) / UNSEEN_DAYS, 2) if has else None,
            "worst_run_usd": cents(s.get("worst_run_usd") or 0.0) if has else None,
            "worst_run_trades": int(s.get("worst_run_trades") or 0) if has else None,
            "target": target, "stop": stop,
            "target_pct": level_words(lv, "target") if has else None,
            "stop_pct": level_words(lv, "stop") if has else None,
            # one leverage is "20x", as the results page prints it (M6)
            "lev": (f"{lev[0]}x" if lev[0] == lev[1] else f"{lev[0]}x-{lev[1]}x") if lev else None,
            # COVERAGE FIRST beside every verdict (I3); a verdict judged before it was kept says so
            "cost_unseen": (NO_COSTS if costs is None else vcv.share_words(unseen_c) if unseen_c
                            else "no setting chosen"),
            "cost_older": NO_COSTS if costs is None else vcv.share_words(costs.get("older")),

            "random_median_trades": None if chose else rr.get("median_trades"),
            "real_trades": None if chose else rr.get("real_trades"),
            "why": (v.get("why") or "") if chose else f"chose {v.get('setting')} on the older days",
            "blank": blank or ("" if rr.get("median_trades") is not None
                               else "the random runs' trades were not recorded")}
    if unseen_c and unseen_c.get("legs"):
        # what the tab's typical-cost column sorts by; a row with no trade has no share to sort
        out["cost_share"] = round(unseen_c["typical_low"] / unseen_c["legs"], 4)
    return out


def options(*, fx=None, store_file=None, check_file=None) -> dict:
    """Everything the tab's boxes offer, from the registries — never typed in.
    `store_file` / `check_file` are passed to `tested`, so a test never reads the
    operator's real verdict store."""
    from tradingagents import backtest_report as br, stores, venue

    if fx is None:
        from tradingagents.dataflows import exchange as fx
    try:
        coins, coins_error = sorted(fx.trading_symbols()), ""
    except Exception as exc:                                   # noqa: BLE001
        coins, coins_error = [], f"{type(exc).__name__}: {exc}"
    try:
        plan, plan_error = plan_info(load_plan()), ""
    except (OSError, ValueError) as exc:
        plan, plan_error = None, f"{type(exc).__name__}: {exc}"
    return {"venue": venue.name(), "coins": coins, "coins_error": coins_error,
            "tfs": list(stores.FIVE), "signals": list(br.SIGNALS),
            "thresh_signals": sorted(br.THRESH_SIGNALS), "days": list(DAYS),
            "default_days": DEFAULT_DAYS, "exits": EXITS, "risk": RISK, "defaults": DEFAULTS,
            "families": families(), "plan": plan, "plan_error": plan_error,
            "tested": tested(store_file, check_file)}


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


# ------------------------------------------------------------ the v3 families
# what each filter does, in the words the boxes print (the rules are v3_filters')
FILTER_WORDS = {
    "none": "no filter",
    "btc_mood": "alt-coin longs only while BTC closed above its 50-day average",
    "busy_hours": "stock tokens 9:30am-4:00pm New York on a weekday; others never on a weekend",
    "funding_side": "no long when funding is in the coin's top 10% of 30 days, no short in its "
                    "bottom 10%",
    "funding_minutes": "no order within 5 minutes of a funding settlement",
}


def load_plan(path=None) -> dict:
    """The committed universe plan (`v3_universe.load`): which coins each
    family may trade, month by month."""
    from tradingagents import v3_universe as vu

    return vu.load(vu.PLAN_FILE if path is None else path)


def plan_info(plan: dict) -> dict:
    from tradingagents import v3_universe as vu

    return {"id": plan.get("id") or vu.plan_id(plan), "start_ms": int(plan["start_ms"]),
            "end_ms": int(plan["end_ms"]), "last_month": plan["months"][-1]}


def setting_words(family: str, value) -> str:
    """A family's setting in its own words, from the numbers its rule reads."""
    from tradingagents import v3_families as vf, v3_rules as vr, v3_universe as vu

    v = float(value)
    if family in ("v3_trend", "v3_breakout"):
        return f"n = {v:g} days"
    if family == "v3_strength":
        return f"K = {v:g} (the top {v:g} by {vu.STRENGTH_DAYS}-day return each Monday)"
    if family == "v3_snap":
        return (f"k = {v:g} (a close {v:g} x ATR({vr.ATR_N}) past its {vf.SNAP_N}-candle "
                "average)")
    raise ValueError(f"unknown family {family!r}")


def family_words(family: str) -> str:
    """What the family's rule holds on, from the constants it reads."""
    from tradingagents import v3_families as vf, v3_rules as vr, v3_universe as vu

    if family == "v3_trend":
        return (f"Trend: the close above its n-day average while that average is above its value "
                f"{vf.TREND_LAG_DAYS} days ago (short: below a falling one)")
    if family == "v3_breakout":
        return (f"Breakout: a close past the high (short: the low) of the n days before, while "
                f"the {vf.BREAKOUT_MA_DAYS}-day average rises (falls)")
    if family == "v3_strength":
        return (f"Strength: each Monday, long the top K liquid coins by {vu.STRENGTH_DAYS}-day "
                "return")
    if family == "v3_snap":
        return (f"Snap back: a close k x ATR({vr.ATR_N}) past its {vf.SNAP_N}-candle average, "
                "bet on the way back")
    raise ValueError(f"unknown family {family!r}")


def families() -> list[dict]:
    """The four families as the tab's boxes offer them: their timeframes,
    settings (in words), the filters each timeframe is tried with (and the
    ones it is not, with why), and each setting's own exit in words - all
    read from v3_families and the research's exit words."""
    from tradingagents import v3_families as vf, v3_research as vrs

    out = []
    for fam, d in vf.FAMILIES.items():
        settings = []
        for v in d["settings"]:
            key = vf.setting_key(fam, v)
            exits = {}
            for tf in d["tfs"]:
                target, stop = vrs.exit_words(fam, key, tf)
                exits[tf] = {"target": target, "stop": stop}
            settings.append({"key": key, "value": v, "words": setting_words(fam, v),
                             "exit": exits})
        out.append({"name": fam, "words": family_words(fam), "tfs": list(d["tfs"]),
                    "long": list(d["long"]), "short": list(d["short"]), "settings": settings,
                    "filters": {tf: [{"key": f, "words": FILTER_WORDS[f]}
                                     for f in vf.filters_for(tf)] for tf in d["tfs"]},
                    "not_tried": {tf: [{"key": f, "why": why}
                                       for (f, t), why in vf.NOT_TRIED.items() if t == tf]
                                  for tf in d["tfs"]}})
    return out


def parse_family(body: dict, coins=None) -> dict:
    """A family pick, checked: the coin, one of the family's timeframes, one
    of its settings (its key, "n50", or its value), a filter that timeframe
    is tried with, a listed window and the risk. A bad pick is refused naming
    its box."""
    from tradingagents import v3_families as vf

    fam = body.get("signal")
    if fam not in vf.FAMILIES:
        raise ValueError(f"idea: {fam!r} is not a v3 family")
    d = vf.FAMILIES[fam]
    sym = str(body.get("sym") or "").strip().upper()
    if not sym:
        raise ValueError("coin: pick one")
    if coins is not None and sym not in coins:
        raise ValueError(f"{sym} is not a coin the exchange lists")
    tf = body.get("tf")
    if tf not in d["tfs"]:
        raise ValueError(f"timeframe: {fam} runs on {', '.join(d['tfs'])}")
    raw = body.get("setting")
    keys = {vf.setting_key(fam, v): v for v in d["settings"]}
    value = keys.get(str(raw))
    if value is None and not isinstance(raw, bool):
        try:
            value = next((v for v in d["settings"] if float(raw) == float(v)), None)
        except (TypeError, ValueError):
            value = None
    if value is None:
        raise ValueError(f"setting: {fam} is tried with {', '.join(keys)}")
    filt = body.get("filter") or "none"
    if filt not in vf.filters_for(tf):
        why = vf.NOT_TRIED.get((filt, tf))
        raise ValueError(f"filter: on {tf} pick one of {', '.join(vf.filters_for(tf))}"
                         + (f" ({filt} is not tried on {tf}: {why})" if why else ""))
    try:
        days = int(body.get("days") or DEFAULT_DAYS)
    except (TypeError, ValueError):
        raise ValueError("days: pick one of the listed windows") from None
    if days not in DAYS:
        raise ValueError(f"days: pick one of {', '.join(str(x) for x in DAYS)}")
    risk = _number(body.get("risk_usd", RISK["default"]),
                   {"label": "risk per trade $", "min": RISK["min"], "max": RISK["max"]})
    return {"sym": sym, "tf": tf, "family": fam, "value": value,
            "setting": vf.setting_key(fam, value), "filter": filt, "days": days, "risk_usd": risk}


def family_id(p: dict) -> str:
    """A family run's stable id: the coin, the timeframe and the family, with
    the setting and the filter in `plan` (`v3_families.combo_key`), hashed with
    res="v3" - every combination its own id, never a v1 or v2 one, and never a
    stored idea's (no family is a stored signal). The risk is not in it."""
    from tradingagents import backtest_report as br, v3_families as vf

    return br.row_code(p["sym"], p["tf"], p["family"], 0.0, 0.0, 0.0, "flat",
                       plan=vf.combo_key(p["family"], p["setting"], p["tf"], p["filter"]),
                       res="v3")


def universe_words(plan: dict, family: str, sym: str, start_ms: int, end_ms: int) -> list[str]:
    """What the plan lets `sym` do in the window, in words: in how many of the
    window's months it is in the family's universe, and what stands in after
    the plan's end (its last month's membership; no strength ranks)."""
    from tradingagents import v3_families as vf, v3_universe as vu
    from tradingagents.positions_view import fmt_when

    d = vf.FAMILIES[family]
    groups = set(d["long"]) | set(d["short"])
    end_plan = int(plan["end_ms"])
    months = vu.months_between(start_ms, end_ms)
    inside = sum(1 for m in months
                 if vu.member_mask(plan, groups, sym, [min(max(m, start_ms), end_plan - 1)])[0])
    sides = (f"longs: {' or '.join(d['long']) or 'none'}; "
             f"shorts: {' or '.join(d['short']) or 'none'}")
    out = [f"{sym} is in {family}'s universe in {inside} of the window's {len(months)} months "
           f"({sides})"]
    if end_ms > end_plan:
        out.append(f"membership after {fmt_when(end_plan / 1000)} (the plan's end) is "
                   f"{plan['months'][-1]}'s")
        if family == "v3_strength":
            out.append(f"v3_strength has no Monday ranks after {fmt_when(end_plan / 1000)}, so it "
                       "can make no entry there")
    if start_ms < int(plan["start_ms"]):
        out.append(f"the plan starts {fmt_when(int(plan['start_ms']) / 1000)}: before it the coin "
                   "is in no universe")
    return out


def run_family(body: dict, *, fx=None, plan=None, now_ms: int | None = None) -> dict:
    """One press of Run with a v3 family picked: the family's rule, its own
    exit, its universe and one filter over the window that ends `now_ms` (None:
    the clock), walked once (see the module doc), with every row and figure
    the tab prints."""
    from tradingagents import (
        backtest_report as br,
        v3_engine as ve,
        v3_families as vf,
        v3_filters as vfl,
        v3_measure as vm,
        v3_research as vrs,
        venue,
    )

    if fx is None:
        from tradingagents.dataflows import exchange as fx
    p = parse_family(body, coins=set(fx.trading_symbols()))
    plan = load_plan() if plan is None else plan
    t0 = time.time()
    fam, v, tf, filt, sym = p["family"], p["value"], p["tf"], p["filter"], p["sym"]
    bar_ms = br.TFS[tf][1] * 1000
    end = int(time.time() * 1000) if now_ms is None else int(now_ms)
    start = end - p["days"] * vm.DAY_MS
    lead = vf.lead(fam, v, tf)
    pre = vm.read_window(sym, start, end, {tf: lead}, fx=fx)
    b = pre["bars"][tf]
    t = b["t"]
    i0 = bisect.bisect_left(t, start)
    if len(t) - i0 < 2:
        raise ValueError(f"{sym} has {max(0, len(t) - i0)} closed {tf} candles in the window")
    end_plan = int(plan["end_ms"])
    order = [x + bar_ms for x in t]
    # after the plan's end its last month's membership stands in (said on the page)
    at = [ms if ms < end_plan else end_plan - 1 for ms in order]
    kind = plan.get("kinds", {}).get(sym, "unknown")
    long_m, short_m = vf.sides_allowed(fam, sym, plan, at)
    keep_l, keep_s, flags = vfl.masks(filt, sym=sym, kind=kind, order_ms=order,
                                      funding=pre["funding"], cycle_h=pre["cycle_h"], plan=plan)
    ok_l, ok_s = vm.allowed(long_m, short_m, keep_l, keep_s)
    a = max(0, i0 - lead)
    vb = {k: x[a:] for k, x in b.items()}
    s0 = i0 - a
    rule = vf.rule(fam, v, tf, vb, sym=sym, plan=plan)
    got = ve.walk(vb, vm.dirs_of(rule, ok_l, ok_s, a), vf.exit_spec(fam, v, tf), start=s0,
                  forced=vf.forced(fam, v, tf, vb, sym=sym, plan=plan), bar_s=bar_ms // 1000,
                  contract=pre["contract"], fees=pre["fees"], flat_slip=pre["slip"],
                  risk_usd=p["risk_usd"], fine=pre["fine"], book=pre["book"],
                  funding=pre["funding"])
    signals = vm._signals(rule, long_m, short_m, keep_l, keep_s, flags, a, s0)
    rows, missed, summary = _tally(got, vb["t"], (int(t[-1]) + bar_ms - int(t[i0])) / vm.DAY_MS)
    summary["filter"] = signals
    summary["filter_words"] = vrs._filter_counts(signals)
    target, stop = vrs.exit_words(fam, p["setting"], tf)
    win_start, win_end = int(t[i0]), int(t[-1]) + bar_ms
    meta = pre["meta"]
    provenance = {
        "sym": sym, "tf": tf, "signal": fam, "family": fam, "setting": p["setting"],
        "setting_words": setting_words(fam, v), "family_words": family_words(fam),
        "filter": filt, "filter_words": FILTER_WORDS[filt], "th_pct": None, "exit": "family",
        "exit_words": f"its own exit - target: {target}; stop: {stop}", "target": target,
        "stop": stop, "params": {}, "days": p["days"], "start_ms": win_start,
        "end_ms": win_end, "venue": venue.name(), "risk_usd": p["risk_usd"],
        "maker_fee": pre["fees"]["maker"], "taker_fee": pre["fees"]["taker"],
        "flat_slip": pre["slip"], "flat_slip_source": meta["flat_slip_source"],
        "coverage": meta["coverage"], "candles": len(t) - i0,
        "points": len(pre["fine"][0]) if pre["fine"] else 0,
        "universe": universe_words(plan, fam, sym, win_start, win_end),
        "plan_id": plan.get("id"), "plan_end_ms": end_plan,
        "look": "A look at one idea on one coin over this window - one walk, no older and unseen "
                "days, no random runs: never the proof, which judges every coin together."}
    return {"id": family_id(p), "provenance": provenance, "summary": summary, "trades": rows,
            "missed": missed, "elapsed_s": round(time.time() - t0, 1)}


def run(body: dict, *, fx=None) -> dict:
    """One press of the tab's Run button: the choices checked, the v3 walk,
    and every row and figure the tab prints."""
    from tradingagents import v3_families as vf, v3_smoke, venue

    if body.get("signal") in vf.FAMILIES:
        return run_family(body, fx=fx)
    if fx is None:
        from tradingagents.dataflows import exchange as fx
    p = parse(body, coins=set(fx.trading_symbols()))
    t0 = time.time()
    m = v3_smoke.measure(p["sym"], p["tf"], p["signal"], p["spec"], days=p["days"],
                         th=p["th"], risk_usd=p["risk_usd"], fx=fx)
    got, t = m["walk"], m["t"]
    rows, missed, summary = _tally(got, t, (int(m["end_s"]) - int(m["from_s"])) / 86400)
    provenance = {
        "sym": p["sym"], "tf": p["tf"], "signal": p["signal"], "th_pct": p["th_pct"],
        "exit": p["kind"], "exit_words": exit_words(p), "params": p["params"],
        "days": p["days"], "start_ms": int(m["from_s"]) * 1000, "end_ms": int(m["end_s"]) * 1000,
        "venue": venue.name(), "risk_usd": p["risk_usd"], "maker_fee": m["fees"]["maker"],
        "taker_fee": m["fees"]["taker"], "flat_slip": m["flat_slip"],
        "coverage": m["coverage"], "candles": len(t) - m["lead"], "points": m["points"]}
    return {"id": row_id(p), "provenance": provenance, "summary": summary, "trades": rows,
            "missed": missed, "elapsed_s": round(time.time() - t0, 1)}


def _tally(got: dict, t, span_days: float) -> tuple[list, list, dict]:
    """A walk as the tab prints it: (the trade rows with their running total,
    the orders that never filled with their market twins, the summary) - ONE
    body for a stored idea's run and a family's. Trades a day are over the
    days the walked candles span (`span_days`), never the window asked for:
    a young coin's window is shorter."""
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
        "trades_per_day": len(rows) / span_days if span_days > 0 else None,
        "counts": counts, "combos": 1}
    return rows, missed, summary
