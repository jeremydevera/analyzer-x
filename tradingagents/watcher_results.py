"""The practice record of each row the watcher switched on, since it did.

Task 5 of docs/superpowers/plans/2026-09-28-strategy-watcher.md. Read from the
trade record's practice exits (`dry_run`), per slot (`book_slot(key, coin)`),
from the later of its switch-on and 30 days ago. The watcher SHOWS this; the
operator's one switch-off rule is the 30-day win rate (watcher_policy.judge),
and `warn()` is what turns this into a sentence on the screen.
"""
from __future__ import annotations

DAY_S = 86_400


def practice(slots: dict, *, now: float) -> dict:
    """{slot: {"trades", "wins", "losses", "pnl", "streak", "win_usd",
    "loss_usd"}} for every slot in `slots` ({slot: switched-on seconds}).
    The trade record is read ONCE, from the earliest start any slot needs."""
    from tradingagents import auto_trader as at

    starts = {s: max(float(on), now - 30 * DAY_S) for s, on in slots.items()}
    out = {s: {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "streak": 0,
               "win_usd": 0.0, "loss_usd": 0.0} for s in slots}
    if not slots:
        return out
    got: dict = {s: [] for s in slots}
    for e in at.ledger_since(min(starts.values())):
        if e.get("action") != "exit" or not e.get("dry_run"):
            continue
        slot = at.book_slot(e.get("strategy") or "", e.get("symbol"))
        if slot in got and float(e.get("ts") or 0) >= starts[slot]:
            got[slot].append(e)
    for slot, exits in got.items():
        exits.sort(key=lambda e: float(e.get("ts") or 0))
        wins = [float(e.get("pnl_est") or 0) for e in exits if float(e.get("pnl_est") or 0) > 0]
        losses = [float(e.get("pnl_est") or 0) for e in exits if float(e.get("pnl_est") or 0) <= 0]
        streak = 0
        for e in reversed(exits):
            if float(e.get("pnl_est") or 0) > 0:
                break
            streak += 1
        o = out[slot]
        o.update(trades=len(exits), wins=len(wins), losses=len(losses),
                 pnl=round(sum(wins) + sum(losses), 2), streak=streak,
                 win_usd=round(sum(wins) / len(wins), 4) if wins else 0.0,
                 loss_usd=round(-sum(losses) / len(losses), 4) if losses else 0.0)
    return out
