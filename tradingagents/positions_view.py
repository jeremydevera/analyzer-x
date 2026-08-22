"""One open position, with every column the operator reads.

Ported from app.py's `_TM_POS`, whose own comment records that these fourteen
columns were RESTORED on 2026-08-20 after a five-column "clean" remake — so
the column set is a standing operator decision, not a design choice. The
React port shipped five of them on 2026-08-21; this module is the shared
source so it cannot happen again in either UI.

Nothing here talks to Streamlit. Money maths lives here, not in the view.
"""
from __future__ import annotations

import datetime as _dt
import logging as _logging
import time


def fmt_when(ts: float) -> str:
    """THE date format, everywhere: ``Aug 03, 2026 8:03pm``.

    The operator's exact words on 2026-08-22, after asking three times:
    "i want format of Aug 03, 2026 8:03pm ... this applies to whole module".

    Read it precisely, because each part was wrong at some point:
      * month  — three letters, capitalised: ``Aug``
      * day    — TWO DIGITS, zero padded: ``03``, not ``3``
      * year   — four digits, after a comma
      * hour   — 12-hour, NOT padded: ``8``, and midnight/noon are ``12``
      * minute — two digits: ``03``
      * am/pm  — LOWERCASE, no space before it: ``8:03pm``

    Compact stamps like '08-21 00:18' were rejected outright. Every timestamp
    in this repo, Python and TypeScript alike, comes from here or from its
    TypeScript twin ``fmtWhen`` in webapp/src/lib/api.ts.
    """
    d = _dt.datetime.fromtimestamp(ts)
    hour = d.hour % 12 or 12
    ampm = "am" if d.hour < 12 else "pm"
    return f"{d:%b} {d.day:02d}, {d.year} {hour}:{d:%M}{ampm}"


class WhenFormatter(_logging.Formatter):
    """A logging formatter whose timestamps are THE format.

    `logging.basicConfig(format="%(asctime)s ...")` defaults to
    `2026-08-22 19:27:03,488` — precisely the compact stamp the operator
    banned, printed on every line of the Runner feed. `datefmt` cannot express
    the rule either: strftime has no portable unpadded 12-hour hour and its
    `%p` is uppercase. So the formatter asks fmt_when, like everything else.
    """

    def formatTime(self, record, datefmt=None):    # noqa: N802 (stdlib name)
        return fmt_when(record.created)


def fmt_age(seconds: float) -> str:
    """How long a position has been open, in words."""
    seconds = max(0, int(seconds))
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def progress(entry, tp, sl, px, side: int):
    """How far this position has travelled, as (percent, "TP"|"SL") or None.

    One calculation with one reader — the Streamlit version once re-parsed the
    rendered HTML to recover this number and drew every bar at 0%.
    """
    try:
        e, p = float(entry), float(px)
    except (TypeError, ValueError):
        return None
    if not e or not p:
        return None
    moved = (p / e - 1) * side          # positive = toward the target
    target, which = (tp, "TP") if moved >= 0 else (sl, "SL")
    try:
        t = float(target)
    except (TypeError, ValueError):
        return None
    span = abs(t / e - 1)
    if not span:
        return None
    return round(min(100.0, abs(moved) / span * 100), 1), which


def barrier_value(entry, barrier, notional: float, fee: float, *,
                  win: bool) -> dict | None:
    """What a barrier is worth in PERCENT and in DOLLARS, net of the
    round-trip taker fee.

    The percentage is on the NOTIONAL, so the dollar figure is the only one
    that says what actually lands in the wallet — and contract size matters:
    XAUT is 0.001, so entry x vol once overstated notional 1000x and claimed a
    2.40% take-profit was worth +2,279 USDT on a 5 USDT position.
    """
    try:
        e, b = float(entry), float(barrier)
    except (TypeError, ValueError):
        return None
    if not e or not b:
        return None
    pct = abs(b / e - 1) * 100
    cost = notional * fee * 2
    usd = (notional * pct / 100 - cost) if win else -(notional * pct / 100 + cost)
    return {"pct": round(pct, 2), "usd": round(usd, 2)}


def build_rows(*, state: dict, exchange_positions: list, stats: dict,
               dry: bool, last_price, contract_size, taker_fee,
               leverage: int, now: float | None = None) -> list[dict]:
    """Every OPEN position on one book, with all fourteen columns.

    Callables are injected so this stays testable without a network: a wrong
    price here is a wrong dollar figure on screen.
    """
    now = now if now is not None else time.time()
    rows: dict[str, dict] = {}

    def blank(sym: str) -> dict:
        s = stats.get(sym) or {}
        return {"symbol": sym, "coin": sym.replace("_USDT", ""),
                "state": "", "strategy": s.get("strategy", ""),
                "side": "", "opened": "—", "held": "—", "vol": None,
                "margin": None, "entry": None, "tp": None, "sl": None,
                "bracket": "", "unrealized": None,
                "realized": round(float(s.get("pnl") or 0.0), 2),
                "wins": int(s.get("wins") or 0),
                "losses": int(s.get("losses") or 0),
                "trades": int(s.get("trades") or 0)}

    for bkey, sst in (state or {}).items():
        pos = sst.get("position") if isinstance(sst, dict) else None
        if not pos or bool(pos.get("dry", False)) is not dry:
            continue
        sym = bkey.split("#", 1)[0]
        r = rows.setdefault(sym, blank(sym))
        when = pos.get("opened_at") or pos.get("entry_ts")
        unreal = None
        if dry:                       # the paper book has no exchange to ask
            px = last_price(sym)
            if px and pos.get("entry"):
                unreal = round((px / pos["entry"] - 1) * pos["side"]
                               * pos["margin"] * leverage, 2)
        r.update({
            "state": "OPEN",
            "side": "LONG" if pos["side"] > 0 else "SHORT",
            "strategy": pos.get("strategy") or r["strategy"],
            "opened": fmt_when(when) if when else "—",
            "held": fmt_age(now - when) if when else "—",
            "opened_ts": when,
            "vol": pos.get("vol"), "margin": pos.get("margin"),
            "entry": pos.get("entry"), "tp": pos.get("tp"), "sl": pos.get("sl"),
            # Blank when the stop rests where it should. The column keeps its
            # space for the ONE state worth interrupting for: real money open
            # with no protection.
            "bracket": ("" if dry or pos.get("bracket", True)
                        else "NO STOP — RETRYING"),
        })
        if unreal is not None:
            r["unrealized"] = unreal

    if not dry:                       # the exchange is the source of truth
        for p in exchange_positions or []:
            sym = p.get("symbol")
            if not sym:
                continue
            r = rows.setdefault(sym, blank(sym))
            if r["state"] != "OPEN":
                r["state"] = "OPEN"
                r["strategy"] = "(not the bot's)"
                r["side"] = "LONG" if int(p.get("positionType") or 1) == 1 else "SHORT"
            r["vol"] = p.get("holdVol", r["vol"])
            r["entry"] = p.get("holdAvgPrice", r["entry"])
            if p.get("im") is not None:
                r["margin"] = round(float(p["im"]), 2)
            if p.get("unRealizedPnl") is not None:
                r["unrealized"] = round(float(p["unRealizedPnl"]), 2)

    out = [r for r in rows.values() if r["state"] == "OPEN"]
    for r in out:
        r["total"] = round(r["realized"] + (r["unrealized"] or 0), 2)
        side = 1 if r["side"] == "LONG" else -1
        notional = (float(r["entry"] or 0) * float(r["vol"] or 0)
                    * contract_size(r["symbol"]))
        r["notional"] = round(notional, 2)
        try:
            fee = taker_fee(r["symbol"])
        except Exception:
            fee = 0.0004
        r["tp_value"] = barrier_value(r["entry"], r["tp"], notional, fee, win=True)
        r["sl_value"] = barrier_value(r["entry"], r["sl"], notional, fee, win=False)
        px = last_price(r["symbol"])
        r["price"] = px
        prog = progress(r["entry"], r["tp"], r["sl"], px, side)
        r["progress_pct"], r["progress_to"] = prog if prog else (None, None)
    out.sort(key=lambda r: r["total"])
    return out
