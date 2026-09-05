"""The /feedcheck report: what traded since the LAST feedcheck, and what
should never have happened.

Operator, 2026-09-05: *"report me how many trades where done how many failed
and whats reason and how many success and include emergency for trades that
should not be"* — over the window since feedcheck last ran ("i run feedcheck
on 4:00pm, after 10 hrs i run feedcheck again").

The window comes from the ledger itself: every run writes a `feedcheck` marker
row, and the next run reports everything after the newest marker (first run:
the last 24 hours). The marker is not an enter/exit, so no record, no P&L and
no reset ever counts it.

EMERGENCIES are concrete markers only — things the ledger can prove, each one
a class that has really fired or is guarded by a rule:

  * `forced_close` — a stop could not rest and the runner had to bail out
    (the 5003 class: three real trades, -5.36 USDT, 2026-09-05)
  * `bracket_failed` — a position sat unprotected for at least one attempt
  * exits by PANIC_CLOSE or RECONCILED — the strategy did not close its own
    trade; something else had to
  * a REAL entry on a coin that already held a REAL position — two positions
    net into one on MEXC (the PROVE incident class); one open position per
    coin makes this impossible, so seeing it means that rule broke
  * `blocked: coin enabled on multiple timeframes` — a guard removed on
    2026-09-05 after freezing all trading for nine hours; any new row means
    it came back
"""
from __future__ import annotations

import json
import time
from collections import Counter

MARKER = "feedcheck"
DEFAULT_WINDOW_S = 24 * 3600
# refusals worth grouping by reason in the "failed and why" section
REFUSALS = ("gate_blocked", "order_failed", "size_failed", "no_price_skip",
            "chase_skip", "coin_busy", "stale_skip", "skip", "blocked")


def load_rows() -> list[dict]:
    from tradingagents import auto_trader as at

    out = []
    try:
        for line in at.LEDGER_PATH.read_bytes().decode(
                "utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def window_since_last_run(rows: list[dict], now: float | None = None) -> float:
    now = time.time() if now is None else now
    marks = [r for r in rows if r.get("action") == MARKER]
    return float(marks[-1].get("ts") or 0) if marks else now - DEFAULT_WINDOW_S


def _book(rows: list[dict], dry: bool) -> dict:
    ent = [r for r in rows if r.get("action") == "enter"
           and bool(r.get("dry_run")) is dry]
    ex = [r for r in rows if r.get("action") == "exit"
          and bool(r.get("dry_run")) is dry]
    wins = [r for r in ex if float(r.get("pnl_est") or 0) > 0]
    losses = [r for r in ex if float(r.get("pnl_est") or 0) <= 0]
    return {
        "entries": len(ent),
        "closed": len(ex),
        "wins": len(wins),
        "losses": len(losses),
        "pnl": round(sum(float(r.get("pnl_est") or 0) for r in ex), 2),
        "loss_reasons": dict(Counter(str(r.get("why")) for r in losses)),
        "win_reasons": dict(Counter(str(r.get("why")) for r in wins)),
    }


def emergencies(rows: list[dict]) -> list[dict]:
    """Trades (or states) that should not exist, with the row as evidence."""
    bad: list[dict] = []
    held: dict[str, dict] = {}          # symbol -> the REAL enter holding it
    for r in rows:
        act, sym = r.get("action"), r.get("symbol") or ""
        if act == "forced_close":
            bad.append({"ts": r.get("ts"), "what": "a stop could not rest and "
                        "the position had to be closed at market",
                        "symbol": sym, "why": str(r.get("why") or "")})
        elif act == "bracket_failed":
            bad.append({"ts": r.get("ts"), "what": "a position sat without "
                        "its stop for at least one attempt",
                        "symbol": sym, "why": str(r.get("why") or "")})
        elif act == "exit" and str(r.get("why")) in ("PANIC_CLOSE",
                                                     "RECONCILED"):
            bad.append({"ts": r.get("ts"), "what": "the strategy did not "
                        "close its own trade — something else had to",
                        "symbol": sym, "why": str(r.get("why"))})
        elif act == "blocked" and "multiple timeframes" in str(r.get("why")):
            bad.append({"ts": r.get("ts"), "what": "the dead nine-hour-freeze "
                        "guard fired again — it was removed on 2026-09-05",
                        "symbol": sym, "why": str(r.get("why"))})
        if bool(r.get("dry_run")):
            continue                     # the double-hold check is REAL only
        if act == "enter":
            if sym in held:
                bad.append({"ts": r.get("ts"), "what": "a SECOND real entry "
                            "on a coin already holding a real position — "
                            "MEXC nets them into one (the PROVE class); the "
                            "one-position rule should make this impossible",
                            "symbol": sym,
                            "why": f"{held[sym].get('strategy')} still held "
                                   f"it, {r.get('strategy')} entered"})
            held[sym] = r
        elif act == "exit":
            held.pop(sym, None)
    return bad


def report(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    rows = load_rows()
    since = window_since_last_run(rows, now)
    # STRICTLY AFTER the marker: a row on the marker's exact second was
    # already in the previous report (harddev round 5)
    win = [r for r in rows if float(r.get("ts") or 0) > since
           and r.get("action") != MARKER]
    refused = Counter()
    for r in win:
        if r.get("action") in REFUSALS:
            why = str(r.get("why") or "")[:70]
            label = (f"{r.get('action')}: {why}" if why
                     else str(r.get("action")))
            refused[label] += 1
    return {
        "since": since,
        "now": now,
        "hours": round((now - since) / 3600, 1),
        "live": _book(win, dry=False),
        "demo": _book(win, dry=True),
        "refused": dict(refused.most_common(12)),
        "refused_total": sum(refused.values()),
        "emergencies": _grouped(emergencies(win)),
    }


def _grouped(bad: list[dict]) -> list[dict]:
    """One line per KIND, not per row: 552 identical dead-guard rows printed
    one-per-line made an 82KB report nobody can read (harddev find,
    2026-09-05). Each group keeps its count, first and last time, and one
    example."""
    groups: dict = {}
    for e in bad:
        k = (e["what"], e["symbol"])
        g = groups.setdefault(k, {"what": e["what"], "symbol": e["symbol"],
                                  "count": 0, "first_ts": e.get("ts"),
                                  "last_ts": e.get("ts"),
                                  "example": e.get("why") or ""})
        g["count"] += 1
        g["last_ts"] = e.get("ts")
    return sorted(groups.values(), key=lambda g: -(g["count"]))


def mark(now: float | None = None) -> None:
    """Write the marker AFTER reporting, so this run ends the window."""
    from tradingagents import auto_trader as at

    at.append_ledger({"action": MARKER,
                      "ts": time.time() if now is None else now})


def main() -> int:
    from tradingagents.positions_view import fmt_when

    got = report()
    print(f"window: {fmt_when(got['since'])} -> {fmt_when(got['now'])} "
          f"({got['hours']} hours since the last feedcheck)")
    for name in ("live", "demo"):
        b = got[name]
        print(f"{name.upper():>5}: {b['entries']} opened · {b['closed']} "
              f"closed · {b['wins']} won · {b['losses']} lost · "
              f"{b['pnl']:+.2f} USDT"
              + (f" · losses by {b['loss_reasons']}" if b["losses"] else ""))
    print(f"refused entries: {got['refused_total']}")
    for why, n in got["refused"].items():
        print(f"   {n:>4}x {why}")
    if got["emergencies"]:
        total = sum(g["count"] for g in got["emergencies"])
        print(f"EMERGENCY — {total} thing(s) that should not have happened, "
              f"{len(got['emergencies'])} kind(s):")
        for g in got["emergencies"]:
            span = (fmt_when(g["first_ts"] or 0) if g["count"] == 1 else
                    f"{fmt_when(g['first_ts'] or 0)} -> "
                    f"{fmt_when(g['last_ts'] or 0)}")
            print(f"   {g['count']:>4}x {g['symbol'].replace('_USDT', '')} — "
                  f"{g['what']} ({span})"
                  + (f" e.g. {g['example'][:60]}" if g["example"] else ""))
    else:
        print("EMERGENCY: none")
    mark(got["now"])
    print("(marker written — the next feedcheck reports from here)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
