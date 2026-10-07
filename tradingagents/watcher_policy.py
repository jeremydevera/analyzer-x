"""What the watcher switches on and off, and the sentence it says why.

Pure: no files, no network, no clock. Every number a decision uses arrives as
an argument, so every decision is a test."""
from __future__ import annotations

# on/off/min_trades/tp_rule are the operator's own numbers (Sep 28, 2026):
# "add it deployed if the trade is 90% above / Then undeploy if 90% below for
# past 30 days / I want tp is greater than sl / Then minimum trade for past 30
# days should be 20"
DEFAULTS = {"on_winrate": 90.0, "off_winrate": 90.0, "min_trades": 20,
            "tp_rule": ">", "profit_floor": 0.0, "max_slots": 100,
            "max_per_coin": 3, "max_new_per_day": 20, "judge_after": 10,
            "off_streak": 4, "cooldown_days": 7, "fresh_hours": 36,
            # NO STOP WIDER THAN 2% (operator, Sep 29, 2026, "okay do it"): of
            # the 457 practice trades since Sep 15, the 93 with a stop wider
            # than 2% won 31% and lost $139.66 — the whole -$138.02; the other
            # 364 made +$1.64. 0 means no cap (the replay and research dials).
            "max_sl": 2.0,
            # RESEARCH DIALS (Sep 28, 2026: "can you research whats the best
            # criteria for promotion and demotion"). The defaults are the
            # operator's rules exactly: judged on 30 days, ranked by win rate,
            # the practice record never switches a row off.
            "window_days": 30, "rank": "winrate", "off_streak_live": 0,
            # THE SWITCH-OFF'S OWN WINDOW (Oct 07, 2026): the 1-4 day rooms
            # switch on by their last few days and off by "the DEMO 30 DAYS
            # figure". 0 = the switch-on window, as every room before them.
            "judge_days": 0,
            # RAW (operator, Sep 30, 2026: "i want raw output, dont put any
            # limit, you only need to serach a criteria in the table and
            # deploy it in my strategies deployed that's it"): the criteria
            # alone — win rate, trades, TP vs SL, the SL cap — and nothing
            # the watcher added (profit floor, stored cost check, limits,
            # waits). Off for the replay/research, which measured the rest.
            "raw": False,
            # THE SMALLEST TARGET (Oct 01, 2026: "currently i think you are
            # avoiding ... tp that is very high but low trade"): a row whose
            # TP is under this percent is never switched on; 0 = no floor
            "min_tp": 0.0}

# "=" (Oct 01, 2026): the target EQUAL to the stop. Percents are stored to
# three places (backtest_report rounds them), so equal is equal to 1e-6.
TP_RULES = (">", ">=", "=", "<", "any")


def tp_equal(tp: float, sl: float) -> bool:
    return abs(float(tp) - float(sl)) < 1e-6


def break_even(win_usd: float, loss_usd: float) -> float:
    total = float(win_usd) + float(loss_usd)
    return round(100 * float(loss_usd) / total, 1) if total > 0 else 100.0


def tp_fails(tp, sl, cfg: dict) -> str:
    """Why a target and stop break the room's TP rule, or "". ONE reading,
    for the switch-on (passes_on) and the switch-off (judge): since Oct 06,
    2026 a room also switches OFF a running row its rule would not switch on
    (operator: "update it then", on dropping running strategies whose stop is
    as big as or bigger than their target)."""
    tp, sl = float(tp), float(sl)
    rule = cfg.get("tp_rule")
    if rule == ">" and not tp > sl:
        return f"TP {tp:g}% is not wider than SL {sl:g}%"
    if rule == ">=" and not tp >= sl:
        return f"TP {tp:g}% is narrower than SL {sl:g}%"
    # "<": the target NARROWER than the stop (Sep 29, 2026: "you can try sl
    # greater than tp") — it only pays at a high win rate
    if rule == "<" and not tp < sl:
        return f"TP {tp:g}% is not narrower than SL {sl:g}%"
    if rule == "=" and not tp_equal(tp, sl):
        return f"TP {tp:g}% is not equal to SL {sl:g}%"
    return ""


def passes_on(row: dict, cfg: dict) -> str:
    tp, sl = float(row["tp"]), float(row["sl"])
    why = tp_fails(tp, sl, cfg)
    if why:
        return why
    floor = float(cfg.get("min_tp") or 0)
    if floor > 0 and tp < floor - 1e-9:
        return f"TP {tp:g}% is under {floor:g}%"
    cap = float(cfg.get("max_sl") or 0)
    if cap > 0 and sl > cap:
        return f"SL {sl:g}% is wider than {cap:g}%"
    if float(row["winrate"]) < cfg["on_winrate"]:
        return f"win rate {row['winrate']:g}% is under {cfg['on_winrate']:g}%"
    if int(row["trades"]) < cfg["min_trades"]:
        return (f"{row['trades']} trades in {window_words(cfg)}, "
                f"fewer than {cfg['min_trades']}")
    if cfg.get("raw"):
        return ""
    if float(row["profit"]) <= cfg["profit_floor"]:
        return f"profit {row['profit']:+.2f} is not above {cfg['profit_floor']:+.2f}"
    if str(row.get("gate") or "") != "ok":
        return f"its cost check read {row.get('gate')!r}, not ok"
    return ""


def pick(candidates, running, cooling, now, cfg) -> list:
    """The candidates to switch on now. `max_new_per_day`, `max_slots` and
    `max_per_coin` of 0 mean NO LIMIT (operator, Sep 30, 2026: "i dont want a
    limit remove it" — "if its millions then deploy all i dont care")."""
    held = {r["id"] for r in running}
    per_coin: dict = {}
    for r in running:
        per_coin[r["coin"]] = per_coin.get(r["coin"], 0) + 1
    big = float("inf")
    raw = bool(cfg.get("raw"))
    per_day = big if raw else (int(cfg["max_new_per_day"]) or big)
    slots = big if raw else (int(cfg["max_slots"]) or big)
    coin_cap = big if raw else (int(cfg["max_per_coin"]) or big)
    room = max(0, min(per_day, slots - len(running)))
    wait = 0 if cfg.get("raw") else cfg["cooldown_days"] * 86400
    out = []
    # which candidate goes first when there is not room for all of them
    by = cfg.get("rank", "winrate")
    if by == "profit":
        order = lambda r: (-float(r["profit"]), -float(r["winrate"]), r["id"])  # noqa: E731
    elif by == "trades":
        order = lambda r: (-int(r["trades"]), -float(r["winrate"]), r["id"])  # noqa: E731
    else:
        order = lambda r: (-float(r["winrate"]), -int(r["trades"]), r["id"])  # noqa: E731
    ranked = sorted(candidates, key=order)
    for row in ranked:
        if len(out) >= room:
            break
        if row["id"] in held or passes_on(row, cfg):
            continue
        if now - float(cooling.get(row["id"], -1e18)) < wait:
            continue
        if per_coin.get(row["coin"], 0) >= coin_cap:
            continue
        per_coin[row["coin"]] = per_coin.get(row["coin"], 0) + 1
        held.add(row["id"])
        out.append({"row": row, "why": (
            f"{row['winrate']:g}% over {row['trades']} trades in the last "
            f"{window_words(cfg)}, TP {row['tp']:g}% / SL {row['sl']:g}%, "
            f"{row['profit']:+.2f}")})
    return out


def _days(n: int) -> str:
    return f"{n} day{'' if n == 1 else 's'}"


def window_words(cfg) -> str:
    """The room's own switch-on window in words — "15 days", "30 days", "1
    day", never a literal (RCA-2026-10-02-H: #6B08FF64's log said "in the last
    30 days" over every 15-day count it judged on)."""
    return _days(int((cfg or {}).get("window_days") or 30))


def judge_days(cfg) -> int:
    """The window the switch-off reads: `judge_days`, or the switch-on window
    when it is 0 (every room before Oct 07, 2026)."""
    c = cfg or {}
    return int(c.get("judge_days") or 0) or int(c.get("window_days") or 30)


def judge_words(cfg) -> str:
    return _days(judge_days(cfg))


def judge(slot, fresh_row, cfg) -> str:
    """Switch off? The room's window of the backtest decides, and since
    Oct 06, 2026 the room's TP rule too: a running row whose target and stop
    the rule would not switch on is switched off (`tp_fails`). The target and
    stop come from the slot when it names them, else from the row."""
    if fresh_row is None:
        return "the backtest store no longer holds this row"
    tp = (slot or {}).get("tp", fresh_row.get("tp"))
    sl = (slot or {}).get("sl", fresh_row.get("sl"))
    try:
        why = tp_fails(tp, sl, cfg)
    except (TypeError, ValueError):
        why = ""                         # no readable target or stop: rule unknown
    if why:
        return why
    if float(fresh_row["winrate"]) < cfg["off_winrate"]:
        return (f"its last-{judge_words(cfg).replace(' ', '-')} win rate fell to "
                f"{fresh_row['winrate']:g}%, under {cfg['off_winrate']:g}%")
    return ""


def warn(practice, cfg) -> str:
    """What the practice record says, for the screen. Never an off switch."""
    out = []
    if int(practice["streak"]) >= cfg["off_streak"]:
        out.append(f"{practice['streak']} losses in a row in practice")
    if int(practice["trades"]) >= cfg["judge_after"]:
        if float(practice["pnl"]) < 0:
            out.append(f"practice lost {practice['pnl']:+.2f} over "
                       f"{practice['trades']} trades")
        else:
            be = break_even(practice["win_usd"], practice["loss_usd"])
            rate = 100 * practice["wins"] / practice["trades"]
            if rate < be:
                out.append(f"practice won {rate:.1f}%, under its {be:.1f}% "
                           f"break-even")
    return "; ".join(out)
