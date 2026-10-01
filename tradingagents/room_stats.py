"""Every number on Auto Trade -> Forecast, worked out in ONE place.

Operator, Oct 01, 2026: *"go run this / Build ALL 15 Forecast features on Auto
Trade -> Forecast, and make sure there is no bug"*, with the rule *"Put all
calculations in one module ... The screen, the saved forecasts and the
automatic forecast all use it. No second copy anywhere."*

READ ONLY. This module reads each room's trade record and open trades and
never writes a trading file. The one thing built here that is ever saved is a
forecast, and that goes through `room_forecasts.add`.

THE DEFINITIONS (the operator's words, and nothing else):

* practice trades = exit rows with `dry_run` true; real-money trades are
  counted separately.
* a win = `pnl_est > 0`; everything else is a loss.
* break-even win rate = average loss / (average win + average loss), from the
  room's OWN closed trades; under 20 wins or 20 losses it is not worked out.
* worst losing run = the biggest sum of losses in a row, in exit-time order —
  dollars and how many trades.
* cost per trade = (price move x size) - `pnl_est`, size = margin x leverage
  from the matching "enter" row (same `trade_id`). A practice trade is booked
  as `(move - cost) * margin * LEVERAGE` (auto_trader, the paper exit), so
  this is exactly what was charged at the exit: the exchange fee, the exit's
  spread and any funding. The spread paid on the way IN is already inside
  the entry price and is not in it — the screen says so.
* worst case today = for every open trade, what it would book if its stop
  were hit now (its own charged cost included). Labelled "up to".
* US market hours = 9:30am-4pm New York time, Monday-Friday (holidays are
  not taken out). A stock coin = a symbol ending in STOCK: the project has no
  rule of its own, and the screen says which rule it used.
* "too early to tell" = under 100 closed trades OR under 7 days.

Big records are read INCREMENTALLY: a room's trade record is 17 MB and grows
with every safety refusal, so each file keeps its read position and only the
new lines are parsed; a file that shrank or was replaced is read again from
the start. The open trades are re-read only when their file changes.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
TOO_EARLY_TRADES = 100
TOO_EARLY_DAYS = 7.0
BREAKEVEN_MIN = 20            # wins AND losses each, before break-even is worked out
READY_TRADES = 200
READY_DAYS = 14.0
OFF_TRADES = 200
FAR_BELOW_SHARE = 0.5         # real profit a trade under half the research's
FAR_BELOW_MIN = 30            # ...once the room has this many closed trades
TOP_LOSERS = 5
STOCK_RULE = "a symbol ending in STOCK (the project has no rule of its own)"
COST_NOTE = ("charged at each exit: exchange fee, the exit's spread and funding; "
             "the spread paid on entry is already inside the entry price")
RESEARCH_FILE = Path(__file__).resolve().parent / "learned" / "room_research.json"

HEAD_BYTES = 4096             # a record's first bytes: changed means it was replaced
_LOCK = threading.Lock()
_LEDGERS: dict = {}
_STATES: dict = {}
_RESEARCH: dict = {"stamp": None, "value": {}}


# ------------------------------------------------------------------ reading
def _paths(room: str) -> tuple[Path, Path]:
    """(trade record, open trades) of `room` — always through profiles.path,
    never built by hand. Read at the call, so a test's monkeypatch holds.

    ONLY A KNOWN ROOM. `profiles.path` CREATES the folder of whatever id it
    is given, so a forecast naming a room that does not exist (a typo in a
    prompt-made forecast) would have made this read-only screen write a
    folder to disk (found in the bug hunt, Oct 01, 2026)."""
    from tradingagents import auto_trader as at, profiles

    if room not in profiles.ids():
        raise ValueError(f"unknown room {room!r}; the rooms are {profiles.ids()}")
    return (Path(profiles.path(at.LEDGER_PATH, room)),
            Path(profiles.path(at.STATE_PATH, room)))


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def ledger(path: Path) -> dict:
    """{"enters": {trade_id: row}, "exits": [row], "bad": n} for one trade
    record, brought up to date with only the lines added since last time."""
    path = Path(path)
    key = str(path)
    with _LOCK:
        c = _LEDGERS.get(key)
        try:
            st = path.stat()
        except OSError:
            _LEDGERS.pop(key, None)
            return {"enters": {}, "exits": [], "bad": 0, "missing": True}
        ident = (getattr(st, "st_ino", 0), getattr(st, "st_dev", 0))
        # THE SAME FILE, OR READ IT AGAIN. A shorter file or a new file id is
        # a replacement — and so is a file REWRITTEN IN PLACE to a longer
        # size, which neither check sees: carrying on from the old offset
        # would read the middle of the new content (found by the tests, Oct
        # 01, 2026). The first bytes and the newline the last read ended on
        # must both still be there.
        if c is not None and not (st.st_size < c["pos"] or c["ident"] != ident):
            try:
                with path.open("rb") as fh:
                    head = fh.read(len(c["head"]))
                    if c["pos"]:
                        fh.seek(c["pos"] - 1)
                        tail = fh.read(1)
                    else:
                        tail = b"\n"
                if head != c["head"] or tail != b"\n":
                    c = None
            except OSError:
                c = None
        if c is None or st.st_size < c["pos"] or c["ident"] != ident:
            c = {"ident": ident, "pos": 0, "head": b"", "enters": {}, "exits": [], "bad": 0}
            _LEDGERS[key] = c
        if st.st_size > c["pos"]:
            with path.open("rb") as fh:
                fh.seek(c["pos"])
                chunk = fh.read(st.st_size - c["pos"])
            last = chunk.rfind(b"\n")
            if last >= 0:                 # a half-written last line waits for next time
                _take(c, chunk[:last + 1])
                c["pos"] += last + 1
                if len(c["head"]) < HEAD_BYTES:
                    with path.open("rb") as fh:
                        c["head"] = fh.read(min(HEAD_BYTES, c["pos"]))
        # A SNAPSHOT, never the cache itself: the API answers from several
        # threads, and a dict another thread is adding to cannot be walked
        return {"enters": dict(c["enters"]), "exits": list(c["exits"]),
                "bad": c["bad"]}


def _take(c: dict, chunk: bytes) -> None:
    for raw in chunk.split(b"\n"):
        # most lines are safety refusals: skip them before parsing anything
        if not raw or (b'"exit"' not in raw and b'"enter"' not in raw):
            continue
        try:
            e = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            c["bad"] += 1
            continue
        act = e.get("action")
        if act == "enter":
            tid = e.get("trade_id")
            if tid:
                c["enters"][str(tid)] = {
                    "ts": _num(e.get("ts")), "margin": _num(e.get("margin"), None),
                    "leverage": _num(e.get("leverage"), None),
                    "dry": bool(e.get("dry_run")), "symbol": e.get("symbol")}
        elif act == "exit":
            c["exits"].append({
                "ts": _num(e.get("ts")), "pnl": _num(e.get("pnl_est")),
                "entry": _num(e.get("entry"), None), "exit": _num(e.get("exit"), None),
                "side": str(e.get("side") or ""), "symbol": str(e.get("symbol") or ""),
                "trade_id": str(e.get("trade_id") or ""),
                "opened_at": _num(e.get("opened_at") or e.get("entry_ts"), None),
                "dry": bool(e.get("dry_run"))})


def open_trades(path: Path) -> list[dict]:
    """Every open position in one room's state file, re-read only when the
    file changes."""
    path = Path(path)
    key = str(path)
    try:
        st = path.stat()
    except OSError:
        return []
    stamp = (st.st_mtime_ns, st.st_size)
    with _LOCK:
        c = _STATES.get(key)
        if c and c["stamp"] == stamp:
            return c["rows"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (c or {}).get("rows", [])      # mid-write: keep the last good read
    rows = []
    for k, v in (data.items() if isinstance(data, dict) else ()):
        pos = v.get("position") if isinstance(v, dict) else None
        if not pos:
            continue
        rows.append({"symbol": str(k).split("#", 1)[0],
                     "dry": bool(pos.get("dry")),
                     "side": _num(pos.get("side")), "entry": _num(pos.get("entry")),
                     "sl": _num(pos.get("sl")), "margin": _num(pos.get("margin")),
                     "rt_cost": _num(pos.get("rt_cost")),
                     "book_slippage": _num(pos.get("book_slippage"))})
    with _LOCK:
        _STATES[key] = {"stamp": stamp, "rows": rows}
    return rows


def research() -> dict:
    """learned/room_research.json, re-read when it changes."""
    try:
        st = RESEARCH_FILE.stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    if _RESEARCH["stamp"] != stamp:
        try:
            _RESEARCH.update(stamp=stamp, value=json.loads(
                RESEARCH_FILE.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return {}
    return _RESEARCH["value"]


def rules_of(room: str) -> dict:
    """The room's switch-on/off rules as its own watcher holds them — read
    WITHOUT the watcher's seeding write (strategy_watcher._read creates a
    missing state file; this must not)."""
    from tradingagents import profiles, strategy_watcher as sw

    st = {}
    try:
        st = json.loads(Path(profiles.path(sw.STATE, room)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rules = (profiles.get(room) or {}).get("rules")
        st = {"cfg": dict(rules)} if rules else {}
    return sw.cfg_of(st)


def rules_text(cfg: dict) -> str:
    tp = {">": "TP wider than SL", ">=": "TP at least SL", "<": "TP narrower than SL"}
    out = [f"judged on {int(cfg.get('window_days') or 30)} days",
           f"on at {_fmt_pct(cfg.get('on_winrate'))} wins",
           f"off under {_fmt_pct(cfg.get('off_winrate'))}",
           f"at least {int(cfg.get('min_trades') or 0)} trades"]
    if cfg.get("tp_rule") in tp:
        out.append(tp[cfg["tp_rule"]])
    if _num(cfg.get("max_sl")):
        out.append(f"SL at most {_fmt_pct(cfg.get('max_sl'))}")
    return " · ".join(out)


def _fmt_pct(v) -> str:
    x = _num(v)
    return f"{x:g}%"


# ------------------------------------------------------------- definitions
def _breakeven(wins: list[float], losses: list[float]) -> tuple[float | None, str]:
    if len(wins) < BREAKEVEN_MIN or len(losses) < BREAKEVEN_MIN:
        return None, (f"not enough trades yet — needs {BREAKEVEN_MIN} wins and "
                      f"{BREAKEVEN_MIN} losses, has {len(wins)} and {len(losses)}")
    avg_w = sum(wins) / len(wins)
    avg_l = -sum(losses) / len(losses)
    if avg_w + avg_l <= 0:
        return None, "the wins and losses are all $0.00"
    return round(100 * avg_l / (avg_w + avg_l), 1), ""


def worst_run(pnls: list[float]) -> tuple[float, int]:
    """The biggest sum of losses in a row (pnls in exit-time order), and how
    many trades that run was. A loss is <= 0, so a run's sum only falls: the
    run is judged when it ENDS, with every trade in it — a $0.00 trade at the
    end of a run is part of that run (it was counted out until Oct 01, 2026,
    found by the tests)."""
    worst, worst_n, run, n = 0.0, 0, 0.0, 0
    for p in list(pnls) + [1.0]:             # a closing "win" ends the last run
        if p > 0:
            if n and (run < worst or (run == worst and n > worst_n)):
                worst, worst_n = run, n
            run, n = 0.0, 0
            continue
        run += p
        n += 1
    return round(worst, 2), worst_n


def _move(row: dict) -> float | None:
    """The exit's price move as a fraction, in the trade's own direction."""
    entry, exit_ = row.get("entry"), row.get("exit")
    if not entry or exit_ is None:
        return None
    sign = -1.0 if str(row.get("side")).upper().startswith("S") else 1.0
    return (exit_ / entry - 1.0) * sign


def costs(exits: list[dict], enters: dict) -> dict:
    """What was charged at each exit: (price move x size) - pnl_est, size =
    margin x leverage from the trade's own enter row."""
    rows = []
    for e in exits:
        en = enters.get(e["trade_id"])
        mv = _move(e)
        if not en or mv is None or not en.get("margin") or not en.get("leverage"):
            continue
        size = en["margin"] * en["leverage"]
        gross = mv * size
        rows.append({"trade_id": e["trade_id"], "symbol": e["symbol"], "size": size,
                     "move": mv, "gross": gross, "pnl": e["pnl"],
                     "cost": gross - e["pnl"]})
    total = sum(r["cost"] for r in rows)
    gross = sum(r["gross"] for r in rows)
    return {"matched": len(rows), "of": len(exits),
            "total": round(total, 2),
            "per_trade": round(total / len(rows), 3) if rows else None,
            "without_costs": round(gross, 2) if rows else None,
            "with_costs": round(sum(r["pnl"] for r in rows), 2) if rows else None,
            "rows": rows}


def market_hours(ts: float) -> bool:
    """9:30am-4pm New York, Monday-Friday."""
    t = dt.datetime.fromtimestamp(ts, NY)
    if t.weekday() >= 5:
        return False
    minutes = t.hour * 60 + t.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


def is_stock(symbol: str) -> bool:
    return str(symbol).upper().replace("_USDT", "").endswith("STOCK")


def _group(rows: list[dict]) -> dict:
    n = len(rows)
    w = sum(1 for r in rows if r["pnl"] > 0)
    p = round(sum(r["pnl"] for r in rows), 2)
    return {"trades": n, "wins": w, "losses": n - w, "profit": p,
            "per_trade": round(p / n, 3) if n else None,
            "winrate": round(100 * w / n, 1) if n else None}


def hours_split(exits: list[dict]) -> dict:
    """Stock coins only, split by when the trade OPENED."""
    stock = [e for e in exits if is_stock(e["symbol"])]
    mk, off = [], []
    for e in stock:
        t = e.get("opened_at") or e["ts"]
        (mk if market_hours(t) else off).append(e)
    return {"stock_trades": len(stock), "other_trades": len(exits) - len(stock),
            "market": _group(mk), "off": _group(off), "rule": STOCK_RULE,
            "split_by": "when the trade opened, New York time"}


def losers(exits: list[dict], n: int = TOP_LOSERS) -> list[dict]:
    by: dict = {}
    for e in exits:
        by.setdefault(e["symbol"].replace("_USDT", ""), []).append(e)
    out = [{"coin": c, **_group(rows)} for c, rows in by.items()]
    out = [o for o in out if o["profit"] < 0]
    out.sort(key=lambda o: (o["profit"], o["coin"]))
    return out[:n]


def _day(ts: float) -> str:
    """The local calendar day a moment falls on, as a sortable key."""
    return dt.date.fromtimestamp(ts).isoformat()


def daily(exits: list[dict], first_at: float | None, now: float) -> list[dict]:
    """Profit per local day, with the running total, every day from the first
    trade to today (days with no closed trade are 0) — so a line drawn from
    it is to scale in time as well as money."""
    starts = [t for t in [first_at] + [e["ts"] for e in exits[:1]] if t]
    if not starts:
        return []
    start = min(starts)
    per: dict = {}
    for e in exits:
        per[_day(e["ts"])] = per.get(_day(e["ts"]), 0.0) + e["pnl"]
    out, total = [], 0.0
    d = dt.date.fromtimestamp(start)
    last = dt.date.fromtimestamp(now)
    while d <= last:
        key = d.isoformat()
        total += per.get(key, 0.0)
        out.append({"day": key, "at": int(time.mktime(d.timetuple())),
                    "profit": round(per.get(key, 0.0), 2), "total": round(total, 2)})
        d += dt.timedelta(days=1)
    return out


# ------------------------------------------------------------------ rooms
def room(room_id: str, now: float | None = None) -> dict:
    """Every number of one room, RIGHT NOW."""
    from tradingagents import auto_trader as at, profiles

    now = time.time() if now is None else float(now)
    ledger_path, state_path = _paths(room_id)
    led = ledger(ledger_path)
    exits = sorted(led["exits"], key=lambda e: e["ts"])
    prac = [e for e in exits if e["dry"]]
    real = [e for e in exits if not e["dry"]]
    pnls = [e["pnl"] for e in prac]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    closed = len(prac)
    profit = round(sum(pnls), 2)
    be, be_why = _breakeven(wins, losses)
    winrate = round(100 * len(wins) / closed, 1) if closed else None
    run, run_n = worst_run(pnls)
    starts = [en["ts"] for en in led["enters"].values() if en["dry"] and en["ts"]]
    first = min(starts) if starts else (min((e.get("opened_at") or e["ts"]) for e in prac)
                                        if prac else None)
    days = round((now - first) / 86400, 2) if first else None
    early = []
    if closed < TOO_EARLY_TRADES:
        early.append(f"{closed:,} of {TOO_EARLY_TRADES} closed trades")
    if days is None or days < TOO_EARLY_DAYS:
        early.append(f"{(days or 0):.1f} of {TOO_EARLY_DAYS:g} days")
    opens = open_trades(state_path)
    popen = [o for o in opens if o["dry"]]
    cost = costs(prac, led["enters"])
    # WORST CASE TODAY: every open practice trade booked at its stop, its own
    # charged cost included (the paper exit's own rule: rt_cost less the entry
    # side already inside the fill)
    worst_case = 0.0
    for o in popen:
        if not o["entry"] or not o["sl"] or not o["margin"]:
            continue
        mv = (o["sl"] / o["entry"] - 1.0) * (1 if o["side"] > 0 else -1)
        charge = max(o["rt_cost"] - o["book_slippage"], 0.0) if o["rt_cost"] else (
            (cost["per_trade"] or 0.0) / (o["margin"] * at.LEVERAGE))
        worst_case += (mv - charge) * o["margin"] * at.LEVERAGE
    res = (research().get("rooms") or {}).get(room_id)
    out = {
        "id": room_id, "name": "Main" if room_id == profiles.MAIN else f"#{room_id}",
        "retired": profiles.retired(room_id),
        "rules": rules_text(rules_of(room_id)),
        "practice": {
            "closed": closed, "wins": len(wins), "losses": len(losses),
            "winrate": winrate, "profit": profit,
            "per_trade": round(profit / closed, 3) if closed else None,
            "avg_win": round(sum(wins) / len(wins), 3) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 3) if losses else None,
            "breakeven": be, "breakeven_why": be_why,
            "vs_breakeven": (round(winrate - be, 1) if be is not None and winrate is not None
                             else None),
            "worst_run": run, "worst_run_trades": run_n,
            "open": len(popen), "first_at": int(first) if first else None,
            "days": days, "too_early": bool(early), "too_early_why": early},
        "real": {**_group(real), "open": len(opens) - len(popen)},
        "research": res,
        "worst_case": {"open": len(popen), "up_to": round(worst_case, 2)},
        "costs": {k: v for k, v in cost.items() if k != "rows"} | {"note": COST_NOTE},
        "hours": hours_split(prac),
        "losers": losers(prac),
        "daily": daily(prac, first, now),
        "unreadable_lines": led["bad"],
    }
    out["alarms"] = alarms(out)
    out["ready"] = ready(out)
    out["turn_off"] = turn_off(out)
    return out


def alarms(r: dict) -> list[dict]:
    """Losing run worse than research, more open than research ever had, and
    real results far below the research's."""
    p, res, out = r["practice"], r.get("research"), []
    if not res:
        return out
    if p["worst_run"] < res["worst_run"]:
        out.append({"kind": "losing_run", "text": (
            f"Losing run worse than its research: {_money(p['worst_run'])} over "
            f"{p['worst_run_trades']} trades, against the research's worst of "
            f"{_money(res['worst_run'])} over {res['worst_run_trades']}")})
    if p["open"] > res["max_open"]:
        out.append({"kind": "too_many_open", "text": (
            f"More trades open than its research ever had: {p['open']:,} open, "
            f"the research's most at once was {res['max_open']:,}")})
    rpt = res["profit"] / res["closed"] if res.get("closed") else None
    if (rpt and rpt > 0 and p["closed"] >= FAR_BELOW_MIN and p["per_trade"] is not None
            and p["per_trade"] < FAR_BELOW_SHARE * rpt):
        out.append({"kind": "far_below", "text": (
            f"Far below its research: {_money(p['per_trade'])} a trade and "
            f"{p['winrate']}% wins for real, against {_money(round(rpt, 3))} a trade "
            f"and {res['winrate']}% wins in September "
            f"({_money(p['profit'])} so far vs {_money(res['profit'])} in the research)")})
    return out


def ready(r: dict) -> dict:
    """The 'ready for real money' badge. A badge only — never a switch."""
    p, res = r["practice"], r.get("research")
    missing = []
    if r["retired"]:
        missing.append("the room is turned off")
    if p["closed"] < READY_TRADES:
        missing.append(f"{READY_TRADES} closed trades (has {p['closed']:,})")
    if (p["days"] or 0) < READY_DAYS:
        missing.append(f"{READY_DAYS:g} days (has {(p['days'] or 0):.1f})")
    if p["breakeven"] is None:
        missing.append("a break-even win rate (not enough trades yet)")
    elif (p["winrate"] or 0) <= p["breakeven"]:
        missing.append(f"a win rate above break-even ({p['winrate']}% against "
                       f"{p['breakeven']}%)")
    if not res:
        missing.append("research to compare its losing run with")
    elif p["worst_run"] < res["worst_run"]:
        missing.append(f"a losing run no worse than research ({_money(p['worst_run'])} "
                       f"against {_money(res['worst_run'])})")
    return {"ok": not missing, "missing": missing}


def turn_off(r: dict) -> dict:
    """The 'should be turned off' note. A note only — never a switch."""
    p = r["practice"]
    ok = (not r["retired"] and p["closed"] >= OFF_TRADES and p["breakeven"] is not None
          and (p["winrate"] or 0) < p["breakeven"])
    return {"ok": ok, "why": (f"still below break-even after {p['closed']:,} closed trades: "
                              f"{p['winrate']}% wins against {p['breakeven']}% needed")
            if ok else ""}


def _money(v) -> str:
    x = _num(v)
    return f"{'+' if x >= 0 else '-'}${abs(x):,.2f}"


def _sort_key(r: dict):
    p = r["practice"]
    return (1 if r["retired"] else 0, 0 if p["closed"] else 1,
            -(p["per_trade"] if p["per_trade"] is not None else -1e9), r["id"])


def rooms(now: float | None = None) -> list[dict]:
    """Every room, best first: the shown rooms by real profit per trade, then
    rooms with no closed trade, then the turned-off rooms (comparison only)."""
    from tradingagents import profiles

    now = time.time() if now is None else float(now)
    return sorted((room(pid, now) for pid in profiles.ids()), key=_sort_key)


# ---------------------------------------------------------------- forecasts
def verdict(all_rooms: list[dict]) -> dict:
    """The pick rule: the best profit per trade among rooms that are NOT too
    early AND win more often than their own break-even; else "too early"
    (no room has the evidence) or "none proven" (some have it, none clears
    its break-even). Turned-off rooms are never picked."""
    live = [r for r in all_rooms if not r["retired"]]
    proven = [r for r in live if not r["practice"]["too_early"]]
    ok = [r for r in proven if r["practice"]["breakeven"] is not None
          and (r["practice"]["winrate"] or 0) > r["practice"]["breakeven"]]
    if ok:
        best = max(ok, key=lambda r: r["practice"]["per_trade"] or -1e9)
        p = best["practice"]
        return {"verdict": "pick", "pick": best["id"], "pick_why": (
            f"{best['name']} makes the most per trade ({_money(p['per_trade'])}) of the "
            f"rooms past {TOO_EARLY_TRADES} trades and {TOO_EARLY_DAYS:g} days that win more "
            f"often than they need to ({p['winrate']}% against {p['breakeven']}%)")}
    traded = [r for r in live if r["practice"]["closed"]]
    if not proven:
        if not traded:
            return {"verdict": "too early", "pick": None, "pick_why": (
                "no room has closed a practice trade yet")}
        best = max(traded, key=lambda r: r["practice"]["per_trade"])
        p = best["practice"]
        return {"verdict": "too early", "pick": None, "pick_why": (
            f"no room has {TOO_EARLY_TRADES} closed trades and {TOO_EARLY_DAYS:g} days yet; "
            f"the best so far is {best['name']} at {_money(p['per_trade'])} a trade over "
            f"{p['closed']:,} trades in {p['days']:.1f} days")}
    near = max(proven, key=lambda r: (r["practice"]["vs_breakeven"]
                                      if r["practice"]["vs_breakeven"] is not None else -1e9))
    p = near["practice"]
    gap = (f"{p['winrate']}% against {p['breakeven']}% needed" if p["breakeven"] is not None
           else p["breakeven_why"])
    return {"verdict": "none proven", "pick": None, "pick_why": (
        f"{len(proven)} room(s) have enough trades, but none wins more often than it needs "
        f"to; the closest is {near['name']}: {gap}")}


def forecast_entry(all_rooms: list[dict], now: float, source: str) -> dict:
    """A forecast in room_forecasts' shape, built from the same numbers the
    screen shows."""
    v = verdict(all_rooms)
    out = []
    for r in all_rooms:
        p = r["practice"]
        out.append({"id": r["id"], "retired": r["retired"], "rules": r["rules"],
                    "research": r["research"] or {},
                    "real": {"closed": p["closed"], "wins": p["wins"], "losses": p["losses"],
                             "winrate": p["winrate"], "breakeven": p["breakeven"],
                             "profit": p["profit"], "per_trade": p["per_trade"],
                             "worst_run": p["worst_run"],
                             "worst_run_trades": p["worst_run_trades"],
                             "open": p["open"], "days": p["days"] or 0.0,
                             "first_at": p["first_at"]}})
    return {"at": int(now), **v, "rooms": out, "artifact": None,
            "note": "", "source": source}


def since(room_id: str, at: float, now: float | None = None,
          exits: list | None = None) -> dict | None:
    """What `room_id` really did in practice from `at` until now; None for a
    room this machine does not have (it is never created to answer).
    `exits` lets a caller checking many forecasts read each record once."""
    from tradingagents import profiles

    if room_id not in profiles.ids():
        return None
    now = time.time() if now is None else float(now)
    if exits is None:
        exits = ledger(_paths(room_id)[0])["exits"]
    rows = [e for e in exits if e["dry"] and e["ts"] >= at]
    g = _group(rows)
    days = round((now - at) / 86400, 2)
    early = g["trades"] < TOO_EARLY_TRADES or days < TOO_EARLY_DAYS
    return {**g, "days": days,
            "result": "too early" if early else ("right" if g["profit"] > 0 else "wrong")}


def check(forecasts: list[dict], now: float | None = None) -> tuple[list[dict], dict]:
    """Each saved forecast with what its pick really did since, and the score
    over every one that can be judged."""
    from tradingagents import profiles

    now = time.time() if now is None else float(now)
    out, right, judged = [], 0, 0
    read: dict = {}                     # each picked room's record read ONCE
    for f in forecasts:
        pick = f.get("pick")
        if pick and pick in profiles.ids() and pick not in read:
            read[pick] = ledger(_paths(pick)[0])["exits"]
        s = since(pick, f["at"], now, read.get(pick)) if pick else None
        if s and s["result"] in ("right", "wrong"):
            judged += 1
            right += s["result"] == "right"
        out.append({**f, "since": s})
    return out, {"right": right, "judged": judged, "saved": len(forecasts),
                 "with_pick": sum(1 for f in forecasts if f.get("pick"))}
