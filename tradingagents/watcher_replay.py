"""What the strategy watcher would have made, replayed day by day.

Operator, `Sep 28, 2026`: *"Lets say i deployed this on sept 1 / What is my
pnl overall / This means on sept 1 you will get the backtest of all coins for
past 30 days / If there is no backtest yet then do backtest for aug"*, then
*"Then do the backtest replay so i know the pnl for every day to know if my
plan has relevenave"*.

THE SAME RULES THE WATCHER WILL USE. Every decision goes through
`watcher_policy.pick` and `watcher_policy.judge`, the functions the live
watcher calls (docs/superpowers/plans/2026-09-28-strategy-watcher.md). A replay
with its own copy of the rules would be a measurement of a different plan.

NO LOOK-AHEAD. At each daily check D, a combination's figures are the trades
that CLOSED inside [D - 30 days, D), where "closed" means the exit bar had
finished by D. Nothing that happened after D can switch a row on at D.

WHAT A SWITCHED-ON ROW EARNS is the trades its own walk ENTERED while it was
on: entry at or after the switch-on, before the switch-off. A trade already
open when the row is switched off finishes normally (the runner's rule,
7897c110), so it still counts. Profit is booked on the day the trade closed;
a trade still open at the end of the data is listed as open, never counted.

Pure: no files, no network, no clock. Times are epoch MILLISECONDS inside, and
days are the operator's LOCAL calendar days (the day `fmt_when` prints).
"""
from __future__ import annotations

import bisect
import datetime as _dt

from tradingagents import watcher_policy as wp

DAY_MS = 86_400_000
WINDOW_MS = 30 * DAY_MS


def local_midnights(first_ms: int, end_ms: int) -> list[int]:
    """Every local midnight from the one on `first_ms`'s day through `end_ms`."""
    d = _dt.datetime.fromtimestamp(first_ms / 1000).date()
    out = []
    while True:
        ms = int(_dt.datetime(d.year, d.month, d.day).timestamp() * 1000)
        if ms > end_ms:
            return out
        out.append(ms)
        d += _dt.timedelta(days=1)


def day_of(ms: int) -> str:
    """The local calendar day a moment falls on, as YYYY-MM-DD (a KEY, never
    printed — the page prints days through fmt_when)."""
    return _dt.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


class _Book:
    """One combination's trades, indexed by EXIT for window questions."""

    def __init__(self, combo: dict):
        self.c = combo
        closed = [t for t in combo["trades"] if t[3]]
        closed.sort(key=lambda t: t[1])
        self.exits = [int(t[1]) for t in closed]
        self.n = [0]
        self.w = [0]
        self.p = [0.0]
        for t in closed:
            self.n.append(self.n[-1] + 1)
            self.w.append(self.w[-1] + (t[2] > 0))
            self.p.append(self.p[-1] + float(t[2]))

    def row(self, at_ms: int, window_ms: int = WINDOW_MS) -> dict | None:
        """The row as the store would have held it at `at_ms`: the trades that
        closed in the `window_ms` (30 days) before. None when there were none —
        a combination with no trade is not a row (sweep_shard's own rule)."""
        a = bisect.bisect_left(self.exits, at_ms - window_ms)
        # a trade whose exit bar closed AT the check is known at the check
        b = bisect.bisect_right(self.exits, at_ms)
        n = self.n[b] - self.n[a]
        if n == 0:
            return None
        wins = self.w[b] - self.w[a]
        c = self.c
        return {"id": c["id"], "coin": c["coin"], "tf": c["tf"],
                "signal": c["signal"], "th": c.get("th", 0.0),
                "group": c.get("group", "classic"),
                "sl": c["sl"], "tp": c["tp"], "gate": c.get("gate", "ok"),
                "trades": n, "wins": wins, "losses": n - wins,
                "winrate": round(100 * wins / n, 2),
                "profit": round(self.p[b] - self.p[a], 2)}


def rows_by_check(books: dict, checks: list[int], window_ms: int) -> dict:
    """{check: every combination's row at that check} — the one expensive
    part of a replay, and the only part that does not depend on the rules
    beyond the window. The research sweep computes it ONCE per window and
    hands it to thousands of `simulate` calls; `simulate` computes exactly
    this itself when it is not given."""
    return {at: [r for r in (b.row(at, window_ms) for b in books.values())
                 if r is not None] for at in checks}


def _live_streak(trades: list, on_ms: int, at_ms: int) -> int:
    """The unbroken run of losses at the END of what a slot has closed in
    practice by `at_ms` — the trades it entered since `on_ms`."""
    closed = sorted((t for t in trades if t[3] and t[0] >= on_ms and t[1] <= at_ms),
                    key=lambda t: t[1])
    n = 0
    for t in reversed(closed):
        if t[2] > 0:
            break
        n += 1
    return n


def simulate(combos: list[dict], *, start_ms: int, end_ms: int,
             cfg: dict | None = None, rows: dict | None = None,
             books: dict | None = None) -> dict:
    """Replay the watcher from `start_ms`'s local midnight to `end_ms`.

    `combos`: each `{"id", "coin", "tf", "signal", "th", "sl", "tp", "gate",
    "trades": [[entry_ms, exit_ms, pnl, closed], ...]}`, one per combination
    that could ever pass. Returns `{"days", "slots", "events", "summary"}`.
    """
    cfg = {**wp.DEFAULTS, **(cfg or {})}
    window_ms = int(cfg.get("window_days", 30)) * DAY_MS
    books = books if books is not None else {c["id"]: _Book(c) for c in combos}
    running: dict[str, dict] = {}         # id -> the open slot
    slots: list[dict] = []
    events: list[dict] = []
    cooling: dict[str, float] = {}
    checks = local_midnights(start_ms, end_ms)
    if rows is None:
        rows = rows_by_check(books, checks, window_ms)
    live_n = int(cfg.get("off_streak_live") or 0)
    for at in checks:
        # 1. SWITCH OFF — judged on the row as it stood at this check, and
        # (a research dial, off by default) on its own practice losing run
        for rid in sorted(running):
            slot = running[rid]
            why = wp.judge({"id": rid}, books[rid].row(at, window_ms), cfg)
            if not why and live_n:
                n = _live_streak(books[rid].c["trades"], slot["on_ms"], at)
                if n >= live_n:
                    why = f"{n} practice losses in a row"
            if why:
                slot["off_ms"], slot["off_why"] = at, why
                cooling[rid] = at / 1000
                del running[rid]
                events.append({"at": at, "action": "off", "id": rid,
                               "coin": slot["coin"], "why": why})
        # 2. SWITCH ON — every combination's row at this check, then the rules
        cands = [r for r in rows.get(at, []) if not wp.passes_on(r, cfg)]
        picks = wp.pick(cands, [{"id": k, "coin": v["coin"]}
                                for k, v in running.items()],
                        cooling, at / 1000, cfg)
        for p in picks:
            r = p["row"]
            slot = {**{k: r[k] for k in ("id", "coin", "tf", "signal", "th",
                                          "sl", "tp", "group")},
                    "on_ms": at, "on_why": p["why"], "on_row": r,
                    "off_ms": None, "off_why": ""}
            running[r["id"]] = slot
            slots.append(slot)
            events.append({"at": at, "action": "on", "id": r["id"],
                           "coin": r["coin"], "why": p["why"]})
    # 3. WHAT EACH SLOT TRADED
    for s in slots:
        hi = s["off_ms"] if s["off_ms"] is not None else float("inf")
        s["trades"] = [t for t in books[s["id"]].c["trades"]
                       if s["on_ms"] <= t[0] < hi]
        _totals(s)
    return {"days": _days(slots, events, checks, end_ms), "slots": slots,
            "events": events, "summary": _summary(slots, checks, end_ms)}


def _totals(s: dict) -> None:
    closed = [t for t in s["trades"] if t[3]]
    s["closed"] = len(closed)
    s["open"] = len(s["trades"]) - len(closed)
    s["wins"] = sum(1 for t in closed if t[2] > 0)
    s["losses"] = len(closed) - s["wins"]
    s["profit"] = round(sum(float(t[2]) for t in closed), 2)
    run = worst = 0.0
    n = worst_n = 0
    for t in sorted(closed, key=lambda t: t[1]):
        if t[2] > 0:
            run, n = 0.0, 0
        else:
            run += float(t[2])
            n += 1
            if run < worst:
                worst, worst_n = run, n
    s["worst_streak"], s["worst_streak_len"] = round(worst, 2), worst_n


def _days(slots, events, checks, end_ms) -> list[dict]:
    """One row per local day, every day from the first check to the end —
    a day with nothing happening is a row of zeros, never a missing row."""
    by_day: dict[str, dict] = {}
    for at in checks:
        by_day[day_of(at)] = {"day": day_of(at), "at": at, "on": 0, "off": 0,
                              "running": 0, "closed": 0, "wins": 0,
                              "losses": 0, "pnl": 0.0}
    for e in events:
        d = by_day.get(day_of(e["at"]))
        if d is not None:
            d[e["action"]] += 1
    for s in slots:
        for t in s["trades"]:
            if not t[3]:
                continue
            d = by_day.get(day_of(t[1]))
            if d is None:
                continue
            d["closed"] += 1
            d["wins" if t[2] > 0 else "losses"] += 1
            d["pnl"] += float(t[2])
    total = 0.0
    out = []
    for key in sorted(by_day):
        d = by_day[key]
        d["running"] = sum(1 for s in slots if s["on_ms"] <= d["at"] and
                           (s["off_ms"] is None or s["off_ms"] > d["at"]))
        d["pnl"] = round(d["pnl"], 2)
        total += d["pnl"]
        d["total"] = round(total, 2)
        out.append(d)
    return out


def _summary(slots, checks, end_ms) -> dict:
    closed = sum(s["closed"] for s in slots)
    wins = sum(s["wins"] for s in slots)
    return {"start_ms": checks[0] if checks else None, "end_ms": end_ms,
            "checks": len(checks), "slots": len(slots),
            "ids": len({s["id"] for s in slots}),
            "closed": closed, "wins": wins, "losses": closed - wins,
            "open": sum(s["open"] for s in slots),
            "winrate": round(100 * wins / closed, 2) if closed else 0.0,
            "profit": round(sum(s["profit"] for s in slots), 2)}
