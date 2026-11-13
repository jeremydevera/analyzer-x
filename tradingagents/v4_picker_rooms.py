"""Forecast v4 -> Rooms: every tested picker rule as a room, for the dates the operator picks.

Operator, Nov 12, 2026: *"in v4 just remove the streak section, then create a section 'room' where you
will list all the room that is earning this month take note i want to see necessary filter on this,
like dates, or winrate etc. if i adjust the date filter i should, the winrate should adjust asw well /
if i click the room, i want to see what switch-on has been deployed and undeployed per day"* - and, asked
what a room is: the tested picker rules, each one a room.

A ROOM here is one picker rule of the lab (`v4_picker_lab.RULES`, plus the rooms with no picker): it
keeps up to three switch-ons (Forecast v4 rule sets) deployed and swaps them by its rule. Everything is
read from the lab's newest run (`lab.json`, `trades.pkl`) - never a second measurement:

* the LIST is worked out here, on the server, for the window asked (CLAUDE.md "filter where the data
  is"): a room's trades are the ones it OPENED in the window - the day its picker chose them, the clock
  the lab walks on - so its profit, trades, wins, losses and win rate are the window's own. Every floor
  (win rate, trades, profit, "earning") is applied to those figures, then sorted and paged, ten a page;
* a room's LOG is its switch-ons day by day: what it deployed, what it undeployed, what kept running,
  and what the day's trades made.

A day is the picker's own day: it starts at 12:00am UTC, when the pick is made. With no window asked,
the window is the month of the newest day measured ("this month").
"""
from __future__ import annotations

import json
import pickle
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from tradingagents import v4_picker_lab as lab

DAY_S = 86_400
PER_PAGE = 10                      # ten a page, as every Forecast list
NEED_VERSION = 2                   # the lab run must carry each room's day-by-day switch-ons
SORTS = ("profit", "win_rate", "trades", "per_trade", "per_day", "worst_run", "deployed", "undeployed", "name", "id")
_CACHE: dict = {"key": None, "doc": None, "tr": None, "measured": None}


class BadAsk(ValueError):
    """Something the caller typed cannot be read (a date that is not a date): the route answers 400."""


def _files() -> tuple[Path, Path]:
    return lab.home() / "lab.json", lab.home() / "trades.pkl"


def load() -> tuple[dict, dict] | None:
    """The newest run and its trades, read once per run (the files are swapped in whole). None when
    there is no run, the run is older than this page needs, or its two files are from different runs."""
    doc_f, tr_f = _files()
    try:
        key = (doc_f.stat().st_mtime_ns, tr_f.stat().st_mtime_ns)
    except OSError:
        return None
    if _CACHE["key"] != key:
        try:
            doc = json.loads(doc_f.read_text(encoding="utf-8"))
            with open(tr_f, "rb") as fh:
                tp = pickle.load(fh)                                   # noqa: S301 - this PC's own file
            paired = tp.get("built_s") == doc.get("built_s")
        except (OSError, ValueError, pickle.UnpicklingError, EOFError):
            paired = False
        if not paired:
            # a run is being written (its trades are swapped in before the run that names them): keep
            # answering from the pair already held, and read again on the next ask
            held = _CACHE["doc"]
            return (held, _CACHE["tr"]) if held is not None and int(held.get("version") or 0) >= NEED_VERSION else None
        info = tp["info"]                   # each strategy's own stop and target (percent; None = no target)
        for t in tp["trades"].values():
            t["sl"] = np.array([info[int(x)][6] for x in t["sid"]], dtype="float64")
            t["tp"] = np.array([np.nan if info[int(x)][5] is None else info[int(x)][5] for x in t["sid"]],
                               dtype="float64")
        _CACHE.update(key=key, doc=doc, tr=tp["trades"], measured=None)
    doc = _CACHE["doc"]
    if int(doc.get("version") or 0) < NEED_VERSION:
        return None
    return doc, _CACHE["tr"]


def _day(text: str, what: str) -> int:
    try:
        d = datetime.strptime(str(text).strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise BadAsk(f"{what} must be a day written YYYY-MM-DD, not {text!r}") from exc
    return int(d.timestamp())


def window(q: dict, doc: dict) -> dict:
    """The days asked for, as the picker's own days: `days` = the last N, else `date_from` / `date_to`
    (YYYY-MM-DD, both counted), else the month of the newest day. Cut to the days the run measured."""
    first = int(doc["first_day_s"])
    last = int(doc["last_day_s"])
    end = last + DAY_S                                        # the end of the newest day (not counted)
    days = int(q.get("days") or 0)
    asked = "this month"
    if days > 0:
        lo, hi = end - days * DAY_S, end
        asked = f"the last {days} days"
    elif q.get("date_from") or q.get("date_to"):
        lo = _day(q["date_from"], "date_from") if q.get("date_from") else first
        hi = _day(q["date_to"], "date_to") + DAY_S if q.get("date_to") else end
        if hi <= lo:
            raise BadAsk("date_to is before date_from")
        asked = "the days picked"
    else:
        d = datetime.fromtimestamp(last, tz=timezone.utc)
        lo, hi = int(datetime(d.year, d.month, 1, tzinfo=timezone.utc).timestamp()), end
    cut = lo < first or hi > end
    lo, hi = max(lo, first), min(hi, end)
    n = max(0, (hi - lo) // DAY_S)
    return {"from_s": lo, "to_s": hi, "days": int(n), "asked": asked, "cut": bool(cut and n > 0),
            "first_day_s": first, "last_day_s": last, "outside": n <= 0}


def _figures(t: dict, lo: int, hi: int, k: float, days: int) -> dict:
    """One room over the trades it OPENED in [lo, hi), in closing order, dollars x k."""
    m = (t["en"] >= lo) & (t["en"] < hi)
    p4 = t["p4"][m]
    n = int(p4.size)
    wins = int((p4 > 0).sum())
    out = {"trades": n, "wins": wins, "losses": n - wins, "win_rate": None, "profit": None, "per_trade": None,
           "per_day": round(n / days, 2) if days else None, "avg_win": None, "avg_loss": None,
           "break_even": None, "worst_run": 0.0, "worst_run_n": 0,
           # the tightest to the widest stop and target among these trades; `no_target` = how many of
           # them come from a strategy with no target at all (it closes on its stop or its signal)
           "sl_min": None, "sl_max": None, "tp_min": None, "tp_max": None, "no_target": 0}
    if not n:
        return out
    sl, tp = t["sl"][m], t["tp"][m]
    has = ~np.isnan(tp)
    out.update(sl_min=round(float(sl.min()), 4), sl_max=round(float(sl.max()), 4), no_target=int((~has).sum()))
    if has.any():
        out.update(tp_min=round(float(tp[has].min()), 4), tp_max=round(float(tp[has].max()), 4))
    p = p4 / 1e4 * k
    out.update(win_rate=round(100.0 * wins / n, 2), profit=round(float(p.sum()), 4),
               per_trade=round(float(p.sum()) / n, 4))
    loss = p4 <= 0
    if loss.any():
        g = np.cumsum(~loss)
        s = np.bincount(g[loss], weights=p[loss])
        c = np.bincount(g[loss])
        j = int(np.argmin(np.where(c > 0, s, np.inf)))
        if s[j] < 0:
            out.update(worst_run=round(float(s[j]), 4), worst_run_n=int(c[j]))
    if wins and n - wins:
        aw, al = float(p[p4 > 0].mean()), -float(p[p4 <= 0].mean())
        out.update(avg_win=round(aw, 4), avg_loss=round(al, 4),
                   break_even=round(100.0 * al / (aw + al), 2) if aw + al > 0 else None)
    return out


def _changes(follow: list, a: int, b: int) -> tuple[list[dict], set]:
    """Day by day over the day indexes [a, b): what the room deployed, undeployed and kept running.
    A switch-on is DEPLOYED on a day it runs and did not run the day before (the room's first day
    deploys its first picks), UNDEPLOYED on a day it no longer runs."""
    out, used = [], set()
    for i in range(a, b):
        now = [x for x in follow[i] if x]
        was = [x for x in follow[i - 1] if x] if i > 0 else []
        used.update(now)
        out.append({"i": i, "deployed": [x for x in now if x not in was],
                    "undeployed": [x for x in was if x not in now], "running": now,
                    "empty": len(follow[i]) - len(now)})
    return out, used


def _span(doc: dict, w: dict) -> tuple[int, int]:
    first = int(doc["first_day_s"])
    return (w["from_s"] - first) // DAY_S, (w["to_s"] - first) // DAY_S


def _measured(doc: dict) -> dict:
    """What the list stands on, for the words above it: when it was measured, on which store, how that
    store priced each coin's gap, and what the same rooms did on the night before's store. Worked out
    once a run (the kept runs are read from disk), never once an ask."""
    if _CACHE["doc"] is doc and _CACHE["measured"] is not None:
        return _CACHE["measured"]
    out = _measure(doc)
    if _CACHE["doc"] is doc:
        _CACHE["measured"] = out
    return out


def _measure(doc: dict) -> dict:
    prev = lab.previous(doc)
    rules = [r for r in doc["rules"] if not r["baseline"]]
    out = {"built_s": doc["built_s"], "store_end_s": doc["store"]["data_end_s"],
           "store_built_s": doc["store"].get("built_s"), "gaps": doc["store"].get("gaps"),
           "rooms": len(doc["rules"]), "tested": len(rules), "rule_sets": doc["rule_sets"],
           "made_money": sum(1 for r in rules if r["trades"] and r["profit"] > 0), "night_before": None}
    if prev:
        ids = {r["id"] for r in rules}
        out["night_before"] = {"store_end_s": prev["store"]["data_end_s"], "built_s": prev["built_s"],
                               "made_money": sum(1 for r in prev["rules"] if r["id"] in ids and r["trades"]
                                                 and r["profit"] > 0)}
    return out


def _not_ready() -> dict:
    st = lab.status()
    why = ("the rooms are being measured now" if st["running"] else
           f"the rooms could not be measured: {st['error']}" if st.get("error") else
           "the rooms have not been measured yet: python -m tradingagents.v4_picker_lab run")
    return {"ready": False, "why": why, "status": st, "rows": [], "total": 0, "of": 0, "page": 1, "pages": 1}


def _num(v, default=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if np.isfinite(x) else default


def rooms_page(q: dict) -> dict:
    """The rooms for a window, filtered, sorted and paged HERE. Keys, all optional: days | date_from,
    date_to (YYYY-MM-DD); min_winrate (percent), min_trades, min_profit (dollars at the base margin),
    earning (made money in the window), q (a room's id: overrides every floor, the window stays),
    base_margin, sort, desc, page."""
    got = load()
    if got is None:
        return _not_ready()
    doc, tr = got
    w = window(q, doc)
    k = max(_num(q.get("base_margin"), 5.0) or 5.0, 0.01) / float(doc["store"]["margin"])
    a, b = _span(doc, w)
    rows = []
    for r in doc["rules"]:
        f = _figures(tr[r["id"]], w["from_s"], w["to_s"], k, w["days"])
        days, used = _changes(r["follow"], a, b)
        rows.append({"id": r["id"], "name": r["name"], "promote": r["promote"], "demote": r["demote"],
                     "baseline": bool(r["baseline"]), **f,
                     "deployed": sum(len(d["deployed"]) for d in days),
                     "undeployed": sum(len(d["undeployed"]) for d in days),
                     "switch_ons": len(used), "empty_room_days": sum(d["empty"] for d in days),
                     "room_days": 3 * len(days),
                     "running": days[-1]["running"] if days else []})
    of = len(rows)
    traded = sum(1 for r in rows if r["trades"])
    earning_n = sum(1 for r in rows if r["trades"] and r["profit"] > 0)
    find = str(q.get("q") or "").strip().lstrip("#").upper()
    named: list[str] = []
    if find:
        rows = [r for r in rows if r["id"] == find]
    else:
        wr, nt, pr = _num(q.get("min_winrate")), _num(q.get("min_trades")), _num(q.get("min_profit"))
        if q.get("earning"):
            rows = [r for r in rows if r["trades"] and r["profit"] > 0]
            named.append("made money in these days")
        if wr is not None and wr > 0:
            rows = [r for r in rows if r["win_rate"] is not None and r["win_rate"] >= wr]
            named.append(f"won {wr:g}% or more")
        if nt is not None and nt > 0:
            rows = [r for r in rows if r["trades"] >= nt]
            named.append(f"{int(nt)} or more trades")
        if pr is not None:
            rows = [r for r in rows if r["profit"] is not None and r["profit"] >= pr]
            named.append(f"profit of {pr:+.2f} or more")
    sort = q.get("sort") if q.get("sort") in SORTS else "profit"
    desc = bool(q.get("desc", True))

    def key(r):
        v = r.get(sort)
        return (v is None, v if isinstance(v, str) else (-(v or 0) if desc else (v or 0)))

    if sort in ("name", "id"):
        rows.sort(key=lambda r: r[sort], reverse=desc)
    else:
        rows.sort(key=key)                               # a room with no trade in the window sorts last
    total = len(rows)
    pages = max(1, -(-total // PER_PAGE))
    page = min(max(int(_num(q.get("page"), 1) or 1), 1), pages)
    why = ""
    if not total:
        # AN EMPTY PAGE NAMES WHAT WAS EXAMINED (CLAUDE.md): how many rooms, how many traded, how many earned
        if find:
            why = f"no room has the id #{find}: {of} rooms were measured"
        elif w["outside"]:
            why = "these days are outside what was measured"
        else:
            why = (f"none of the {of} rooms passes " + " and ".join(named or ["this"]) + f": {traded} of them "
                   f"traded in these {w['days']} days and {earning_n} made money in them")
    return {"ready": True, "rows": rows[(page - 1) * PER_PAGE: page * PER_PAGE], "total": total, "of": of,
            "page": page, "pages": pages, "per_page": PER_PAGE, "filters": named, "found_by_id": bool(find),
            "sort": sort, "desc": desc, "why": why, "window": w, "traded": traded, "earning": earning_n,
            "base_margin": round(k * float(doc["store"]["margin"]), 4), "leverage": doc["store"]["leverage"],
            "measured": _measured(doc), "status": lab.status(), "slots": doc["slots"]}


def room_log(room_id: str, q: dict) -> dict:
    """One room, day by day over the window: the switch-ons it deployed and undeployed, what kept
    running, and what that day's trades made. Keys: the window's (days | date_from, date_to),
    base_margin, every (true = every day; default: only the days something was deployed or undeployed),
    page. Newest day first, ten a page."""
    got = load()
    if got is None:
        return {**_not_ready(), "found": False}
    doc, tr = got
    rid = str(room_id or "").strip().lstrip("#").upper()
    r = next((x for x in doc["rules"] if x["id"] == rid), None)
    if r is None:
        return {"ready": True, "found": False, "why": f"no room has the id #{rid}", "rows": [], "total": 0,
                "page": 1, "pages": 1}
    w = window(q, doc)
    k = max(_num(q.get("base_margin"), 5.0) or 5.0, 0.01) / float(doc["store"]["margin"])
    a, b = _span(doc, w)
    days, used = _changes(r["follow"], a, b)
    words = doc.get("switch_ons") or {}
    first = int(doc["first_day_s"])

    def named(ids):
        return [{"id": i, "words": words.get(i, "")} for i in ids]

    rows = []
    for d in days:
        i = d["i"]
        n, wn = int(r["day_trades"][i]), int(r["day_wins"][i])
        rows.append({"day_s": first + i * DAY_S, "deployed": named(d["deployed"]),
                     "undeployed": named(d["undeployed"]), "running": d["running"], "empty": d["empty"],
                     "trades": n, "wins": wn, "losses": n - wn,
                     "win_rate": round(100.0 * wn / n, 2) if n else None,
                     "profit": round(float(r["day_profit"][i]) * k, 4) if n else None})
    changed = [x for x in rows if x["deployed"] or x["undeployed"]]
    every = bool(q.get("every"))
    shown = rows if every else changed
    shown = shown[::-1]                                   # newest day first
    total = len(shown)
    pages = max(1, -(-total // PER_PAGE))
    page = min(max(int(_num(q.get("page"), 1) or 1), 1), pages)
    why = ""
    if not total:
        why = ("these days are outside what was measured" if w["outside"] else
               f"nothing was deployed or undeployed in these {w['days']} days: the room kept "
               + (", ".join(f"#{x}" for x in (days[-1]["running"] if days else [])) or "no switch-on")
               + " running the whole time")
    return {"ready": True, "found": True, "id": r["id"], "name": r["name"], "promote": r["promote"],
            "demote": r["demote"], "baseline": bool(r["baseline"]),
            "figures": _figures(tr[r["id"]], w["from_s"], w["to_s"], k, w["days"]),
            "rows": shown[(page - 1) * PER_PAGE: page * PER_PAGE], "total": total, "page": page, "pages": pages,
            "per_page": PER_PAGE, "every": every, "why": why, "window": w,
            "days_changed": len(changed), "deployed": sum(len(x["deployed"]) for x in rows),
            "undeployed": sum(len(x["undeployed"]) for x in rows),
            "switch_ons": named(sorted(used)), "running_now": named(days[-1]["running"] if days else []),
            "base_margin": round(k * float(doc["store"]["margin"]), 4), "generated_s": int(time.time())}
