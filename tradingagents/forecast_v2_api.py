"""The Forecast v2 page's answers — every filter, sort and page done HERE,
never in the browser over a list already cut (CLAUDE.md, filter where the
data is).

* the PRACTICE half (forecast_v2.live) is a copy made in the background, the
  way the Forecast tab's room numbers are (api._forecast_live_refresh): a
  request gets the copy at once and, when it is older than LIVE_FRESH_S,
  starts a new one; a failed refresh is named and the last copy served.
* the BACKTEST half is latest.json / streaks.json, written once a day by
  forecast_v2_daily and read here, re-read only when the file changes.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import threading
import time
from pathlib import Path

from tradingagents import forecast_rules as fr, forecast_v2 as f2

LIVE_FRESH_S = 30
# TEN A PAGE, THE AUTO TRADE SIZE (operator, Oct 02, 2026: "in forecast, make
# it paginated just like in auto trade" — Positions and the Watcher there page
# ten rows at a time under numbered buttons). Every list on the Forecast page
# pages at this size: the streaks and the rule sets here, and Backtest a room
# and Room strategies through their routes in api.py. (The signal families
# and the what-ifs went on Oct 08, 2026, with "Where the money goes" and the
# what-if box.)
PER_PAGE = 10
_LIVE: dict = {"value": None, "busy": False, "error": ""}
_LIVE_LOCK = threading.Lock()
_FILES: dict = {}
_FILES_LOCK = threading.Lock()


class NotReady(Exception):
    """No practice copy yet and the first one is being made — the routes
    answer 503 with this sentence (RCA-2026-10-07-M)."""


# ------------------------------------------------------- the practice copy
def live_refresh() -> dict:
    with _LIVE_LOCK:
        if _LIVE["busy"]:
            return _LIVE["value"]
        _LIVE["busy"] = True
    try:
        value = f2.live()
        json.dumps(value, allow_nan=False)          # a copy that cannot be sent is never kept
        _LIVE["value"] = value
        _LIVE["error"] = ""
        return value
    except Exception as exc:                                   # noqa: BLE001
        from tradingagents.positions_view import fmt_when

        why = f"{type(exc).__name__}: {str(exc)[:200]}"
        if why not in _LIVE["error"]:
            print(f"[forecast v2] the practice numbers could not be worked out: {why}", flush=True)
        _LIVE["error"] = f"could not be worked out at {fmt_when(time.time())}: {why}"
        if _LIVE["value"] is None:
            raise
        return _LIVE["value"]
    finally:
        _LIVE["busy"] = False


def live() -> dict:
    """The kept practice copy. NEVER {} (RCA-2026-10-07-M): right after a
    restart the first copy takes a minute or two, and an empty dict handed
    to every reader crashed 21 asks at 3:39pm on Oct 07, 2026 and made the
    signal families look empty — so while it is being made, say so."""
    have = _LIVE["value"]
    if have is None:
        have = live_refresh()
        if not have:
            raise NotReady("the practice numbers are still being worked out after a restart "
                           "— they show here in a minute or two")
    if time.time() - have["at"] > LIVE_FRESH_S and not _LIVE["busy"]:
        threading.Thread(target=live_refresh, name="forecast-v2-live", daemon=True).start()
    return have


# ----------------------------------------------------- the backtest files
def _file(name: str, default):
    """latest.json / streaks.json, re-read only when the file changes."""
    p = f2._home() / name
    try:
        st = p.stat()
    except OSError:
        return default
    stamp = (st.st_mtime_ns, st.st_size)
    with _FILES_LOCK:
        got = _FILES.get(name)
        if got and got[0] == stamp:
            return got[1]
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return got[1] if got else default
    with _FILES_LOCK:
        _FILES[name] = (stamp, value)
    return value


def latest() -> dict | None:
    return _file("latest.json", None)


def backtest_streaks() -> dict | None:
    """streaks.npz as columns (forecast_v2_merge.streak_arrays), re-read only
    when the file changes."""
    import numpy as np

    p = f2._home() / "streaks.npz"
    try:
        st = p.stat()
    except OSError:
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    with _FILES_LOCK:
        got = _FILES.get("streaks.npz")
        if got and got[0] == stamp:
            return got[1]
    try:
        with np.load(p) as z:
            value = {k: z[k] for k in z.files}
    except (OSError, ValueError):
        return got[1] if got else None
    with _FILES_LOCK:
        _FILES["streaks.npz"] = (stamp, value)
    return value


def _streak_row(a: dict, i: int) -> dict:
    import math

    be = float(a["break_even"][i])
    name = lambda k: str(a[f"{k}_names"][int(a[k][i])])  # noqa: E731
    return {"source": "backtest", "kind": "win" if int(a["kind"][i]) == 0 else "loss",
            "length": int(a["length"][i]), "id": a["id"][i].decode(), "coin": name("coin"),
            "tf": name("tf"), "signal": name("signal"), "th": float(a["th"][i]),
            "tp": round(float(a["tp"][i]), 3), "sl": round(float(a["sl"][i]), 3),
            "started_ms": int(a["started_ms"][i]), "last_ms": int(a["last_ms"][i]),
            "profit": round(float(a["profit"][i]), 2), "trades": int(a["trades"][i]),
            "wins": int(a["wins"][i]), "break_even": None if math.isnan(be) else round(be, 1)}


def _by_id() -> dict:
    lt = latest() or {}
    return {s["id"]: s for s in lt.get("sets", [])}


# ------------------------------------------------------------------ pages
def _page(rows: list, page: int, per: int = PER_PAGE) -> dict:
    total = len(rows)
    pages = max(1, -(-total // per))
    page = min(max(1, int(page)), pages)
    return {"rows": rows[(page - 1) * per: page * per], "total": total, "page": page,
            "pages": pages, "per": per}


def _follow_for(kind: str, length: int) -> dict | None:
    """What followed past backtest streaks this long (forecast_shard.streaks):
    under 30 past cases it says so instead of giving a number."""
    lt = latest() or {}
    table = (lt.get("follow") or {}).get(kind) or []
    k = min(int(length), len(table))
    if k < 1:
        return None
    row = table[k - 1]
    if row["cases"] < 30:
        return {"k": row["k"], "cases": row["cases"], "enough": False}
    return {"k": row["k"], "cases": row["cases"], "enough": True,
            "next_win": round(100 * row["next_win"] / row["cases"], 1),
            "cases10": row["cases10"],
            "next10": round(row["pnl10"] / row["cases10"], 2) if row["cases10"] else None,
            "capped": k < int(length)}


def streaks(source: str = "practice", kind: str = "win", min_len: int | None = None,
            page: int = 1) -> dict:
    """One streak list, longest first, filtered and paged here."""
    if source not in ("practice", "backtest"):
        raise ValueError(f"source must be practice or backtest, not {source!r}")
    if kind not in ("win", "loss"):
        raise ValueError(f"kind must be win or loss, not {kind!r}")
    lv = live()
    floor = f2.WIN_N if kind == "win" else f2.LOSS_M
    n = floor if min_len is None else max(1, int(min_len))
    if source == "practice":
        every = [s for s in lv["streaks"] if s["kind"] == kind]
        examined = {"rooms": len(lv["rooms"]), "rows": len(lv["streaks"]),
                    "what": "every room and coin with a closed practice trade"}
        note = ""
    else:
        import numpy as np

        a = backtest_streaks()
        lt = latest() or {}
        data = lt.get("data") or {}
        examined = {"strategies": data.get("strategies"), "trades": data.get("trades"),
                    "end_ms": data.get("end_ms"),
                    "what": "every strategy in the replay that could pass the loosest rule set"}
        written = (lt.get("streaks") or {}).get("floor", 5)
        note = (f"only runs of {written}+ were kept from the replay; a shorter "
                f"setting shows the same list" if n < written else "")
        on = lv.get("on_ids") or {}
        if a is None:
            out = _page([], page)
            out.update(source=source, kind=kind, min=n, of=0, examined=examined, note=note)
            return out
        mine = np.flatnonzero(a["kind"] == (0 if kind == "win" else 1))
        hit = mine[a["length"][mine] >= n]           # already longest first
        out = _page(list(range(len(hit))), page)
        out["rows"] = [{**_streak_row(a, int(hit[i])),
                        "rooms_on": on.get(a["id"][hit[i]].decode(), [])} for i in out["rows"]]
        for r in out["rows"]:
            r["follow"] = _follow_for(kind, r["length"])
        out.update(source=source, kind=kind, min=n, of=int(len(mine)), examined=examined, note=note)
        return out
    rows = [s for s in every if s["length"] >= n]
    out = _page(rows, page)
    for r in out["rows"]:
        r["follow"] = _follow_for(kind, r["length"])
    out.update(source=source, kind=kind, min=n, of=len(every), examined=examined, note=note)
    return out


SORTS = {"rank": lambda s: s["rank"],
         "predicted": lambda s: -((s["predicted"] or {}).get("profit") or -1e18),
         "corrected": lambda s: -((s["predicted"] or {}).get("corrected") or -1e18),
         "beat": lambda s: -((s["random"] or {}).get("beat") or -1),
         "money": lambda s: s["money_needed"],
         "winrate": lambda s: -(s["total"]["winrate"] or 0),
         "trades": lambda s: -((s["predicted"] or {}).get("trades") or 0)}


def rules(sort: str = "rank", page: int = 1, base: str = "", deployable: bool = False,
          min_beat: int = 0, tp_rule: str = "", window: int = 0, max_sl: float = 0.0,
          q: str = "") -> dict:
    """The rule sets, sorted, filtered and paged here."""
    lt = latest()
    if not lt:
        return {"rows": [], "total": 0, "page": 1, "pages": 1, "per": PER_PAGE,
                "tested": None, "why": "no Forecast v2 has been measured yet"}
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {sorted(SORTS)}, not {sort!r}")
    rows = list(lt["sets"])
    named = []
    if q.strip():
        want = q.strip().lstrip("#").upper()
        rows = [s for s in rows if s["id"] == want]
        named.append(f"id #{want}")
    else:
        if base == "base":
            rows = [s for s in rows if s["base"]]
            named.append("base rule sets only")
        elif base == "options":
            rows = [s for s in rows if s["options"]]
            named.append("with an option only")
        if deployable:
            rows = [s for s in rows if s["deployable"]]
            named.append("a room can run it today")
        if min_beat:
            rows = [s for s in rows if ((s["random"] or {}).get("beat") or 0) >= int(min_beat)]
            named.append(f"beat random {int(min_beat)}+ times in 100")
        if tp_rule:
            rows = [s for s in rows if s["cfg"]["tp_rule"] == tp_rule]
            named.append(fr.TP_WORDS.get(tp_rule, tp_rule))
        if window:
            rows = [s for s in rows if int(s["cfg"]["window_days"]) == int(window)]
            w = int(window)
            # a 1-4 day rule set is switched on by those days and off by its
            # own judge window (Oct 07, 2026) — "judged on 2 days" was false
            named.append(f"judged on {w} days" if w > 4 else
                         f"switched on by its last {w} day{'' if w == 1 else 's'}")
        if max_sl:
            rows = [s for s in rows if float(s["cfg"].get("max_sl") or 99) <= float(max_sl) + 1e-9]
            named.append(f"stop {float(max_sl):g}% or tighter")
    rows.sort(key=SORTS[sort])
    out = _page(rows, page)
    out.update(tested=lt["tested"], filters=named, sort=sort)
    return out


# ------------------------------------------------- the month, and grading
def band_on(s: dict | None, day: int, reality: dict) -> dict | None:
    """What a rule set made by the END of day `day` in each past month
    (forecast_v2_merge.by_day), as a range — straight and after the reality
    check. A month shorter than `day` gives its whole month. None when the
    set carries no days (a latest.json from before they were kept): the
    tracker then says nothing rather than guess (RCA-2026-10-01-J — a month's
    worst case divided by 31 rang six bells on day 1)."""
    import statistics

    bd = (s or {}).get("by_day") or {}
    prof, corr = [], []
    for m in sorted(bd):
        v = bd[m]
        k = min(int(day), len(v["p"])) - 1
        if k < 0:
            continue
        prof.append(float(v["p"][k]))
        c = f2.corrected(v["p"][k], v["n"][k], reality)
        if c is not None:
            corr.append(c)
    if not prof:
        return None
    return {"low": round(min(prof), 2), "profit": round(statistics.median(prof), 2),
            "high": round(max(prof), 2),
            "corrected_low": round(min(corr), 2) if corr else None,
            "corrected": round(statistics.median(corr), 2) if corr else None,
            "corrected_high": round(max(corr), 2) if corr else None,
            "day": int(day), "months": sorted(bd)}


def _month_names(keys: list[str]) -> str:
    """["2026-07", "2026-08", "2026-09"] -> "Jul, Aug and Sep 2026" — month
    LABELS, which keep their own form (CLAUDE.md, date format)."""
    if not keys:
        return ""
    names = [f"{_MONTHS[int(k[5:7]) - 1]} {k[:4]}" for k in keys]
    if len({k[:4] for k in keys}) == 1:
        names = [n[:3] for n in names[:-1]] + names[-1:]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def tracker(now: float | None = None) -> dict:
    """Each room's practice month so far against what its own rule set made
    by the same day of each past month, straight and after the reality
    check."""
    now = time.time() if now is None else float(now)
    lt = latest() or {}
    by = _by_id()
    today = dt.date.fromtimestamp(now)
    days_in = calendar.monthrange(today.year, today.month)[1]
    reality = lt.get("reality") or {}
    out = []
    lv = live()
    for r in lv["rooms"]:
        if r["retired"]:
            continue
        rid = ((lt.get("rooms") or {}).get(r["id"]) or {}).get("id")
        s = by.get(rid) if rid else None
        p = (s or {}).get("predicted") or {}
        band = band_on(s, today.day, reality)
        made = r["month"]["profit"]
        below = band is not None and band.get("corrected_low") is not None and made < band["corrected_low"]
        out.append({"room": r["id"], "name": r["name"], "id": rid, "words": (s or {}).get("words"),
                    "month": r["month"], "predicted": p or None, "so_far": band,
                    "below": below})
    tops = list(lt.get("sets") or [])[:5]
    cur = dt.datetime.fromtimestamp(now).strftime("%Y-%m")
    top_rows = []
    for s in tops:
        m = next((x for x in s["months"] if x["month"] == cur), None)
        top_rows.append({"id": s["id"], "words": s["words"], "predicted": s["predicted"],
                         "month": m})
    return {"rooms": out, "tops": top_rows, "month": cur, "day": today.day, "days": days_in}


def tracker_alarms(now: float | None = None) -> list:
    """The bell, ONCE per room per month, when a room's practice month falls
    under its predicted worst case after the reality check."""
    from tradingagents import notifications as nt

    path = f2._home() / "alarms.json"
    try:
        rung = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rung = {}
    t = tracker(now)
    out = []
    for r in t["rooms"]:
        key = f"{t['month']}|{r['room']}"
        if r["below"] and key not in rung:
            b = r["so_far"]
            nt.record("forecast", f"{r['name']} is under its predicted worst case",
                      detail=(f"{r['name']} has made {r['month']['profit']:+.2f} this month; in "
                              f"{_month_names(b['months'])} its rules #{r['id']} made at worst "
                              f"{b['corrected_low']:+.2f} by the end of day {b['day']}, after the "
                              f"reality check"), ok=False)
            rung[key] = time.time()
            out.append(key)
    if out:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        f2.publish(path, json.dumps(rung))
    return out


def summary(now: float | None = None) -> dict:
    """Everything on the page except the lists that page on their own routes
    (streaks, rule sets). No coins to avoid since Oct 07, 2026; and since
    Oct 08, 2026 no "Where the money goes", what-if or "This month so far"
    (operator: "i dont need it anymore"), so neither the practice money
    split, the rooms' backtest breakdowns, the month tracker, the graded
    predictions nor the what-if options are sent. The month tracker is still
    worked out for the bells (`tracker_alarms`, the daily summary)."""
    from tradingagents import forecast_v2_daily as fd

    lv = live()
    lt = latest()
    st = fd.read()
    return {"at": lv["at"], "took_ms": lv["took_ms"], "refresh_error": _LIVE["error"],
            "reality": lv["reality"], "defaults": lv["defaults"],
            "streak_counts": {"practice": {"win": sum(1 for s in lv["streaks"] if s["kind"] == "win"),
                                           "loss": sum(1 for s in lv["streaks"] if s["kind"] == "loss")},
                              "backtest": (lt or {}).get("streaks")},
            "backtest": None if lt is None else {
                "made_at": lt["made_at"], "runs": lt["runs"], "data": lt["data"],
                "tested": lt["tested"], "reality": lt["reality"], "follow": lt["follow"]},
            # the machines a run was used WITHOUT, named (bug hunt, round 12: the
            # chain said "named on the page" and the page was never sent them)
            # and, since Oct 02, 2026, every ACCOUNT's runs and any account
            # dropped (CLAUDE.md, "Every GitHub job uses ALL 40 machines")
            "chain": {k: st.get(k) for k in ("phase", "why", "error", "on", "done_at",
                                             "replay_run", "base_run", "options_run", "repo",
                                             "missing", "fleets", "replay_runs", "base_runs",
                                             "options_runs", "lost")},
            "grid": fr.BASE}
