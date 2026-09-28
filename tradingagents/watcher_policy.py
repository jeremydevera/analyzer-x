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
            # RESEARCH DIALS (Sep 28, 2026: "can you research whats the best
            # criteria for promotion and demotion"). The defaults are the
            # operator's rules exactly: judged on 30 days, ranked by win rate,
            # the practice record never switches a row off.
            "window_days": 30, "rank": "winrate", "off_streak_live": 0}


def break_even(win_usd: float, loss_usd: float) -> float:
    total = float(win_usd) + float(loss_usd)
    return round(100 * float(loss_usd) / total, 1) if total > 0 else 100.0


def passes_on(row: dict, cfg: dict) -> str:
    tp, sl = float(row["tp"]), float(row["sl"])
    if cfg["tp_rule"] == ">" and not tp > sl:
        return f"TP {tp:g}% is not wider than SL {sl:g}%"
    if cfg["tp_rule"] == ">=" and not tp >= sl:
        return f"TP {tp:g}% is narrower than SL {sl:g}%"
    if float(row["winrate"]) < cfg["on_winrate"]:
        return f"win rate {row['winrate']:g}% is under {cfg['on_winrate']:g}%"
    if int(row["trades"]) < cfg["min_trades"]:
        return f"{row['trades']} trades in 30 days, fewer than {cfg['min_trades']}"
    if float(row["profit"]) <= cfg["profit_floor"]:
        return f"profit {row['profit']:+.2f} is not above {cfg['profit_floor']:+.2f}"
    if str(row.get("gate") or "") != "ok":
        return f"its cost check read {row.get('gate')!r}, not ok"
    return ""


def pick(candidates, running, cooling, now, cfg) -> list:
    held = {r["id"] for r in running}
    per_coin: dict = {}
    for r in running:
        per_coin[r["coin"]] = per_coin.get(r["coin"], 0) + 1
    room = max(0, min(cfg["max_new_per_day"], cfg["max_slots"] - len(running)))
    wait = cfg["cooldown_days"] * 86400
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
        if per_coin.get(row["coin"], 0) >= cfg["max_per_coin"]:
            continue
        per_coin[row["coin"]] = per_coin.get(row["coin"], 0) + 1
        held.add(row["id"])
        out.append({"row": row, "why": (
            f"{row['winrate']:g}% over {row['trades']} trades in the last 30 "
            f"days, TP {row['tp']:g}% / SL {row['sl']:g}%, "
            f"{row['profit']:+.2f}")})
    return out


def judge(slot, fresh_row, cfg) -> str:
    """Switch off? Only the last 30 days of the backtest decide."""
    if fresh_row is None:
        return "the backtest store no longer holds this row"
    if float(fresh_row["winrate"]) < cfg["off_winrate"]:
        return (f"its last-30-days win rate fell to {fresh_row['winrate']:g}%, "
                f"under {cfg['off_winrate']:g}%")
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
