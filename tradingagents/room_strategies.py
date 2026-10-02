"""Prompt 4: find new winning room strategies and keep them (Oct 02, 2026).

The operator: *"when i run the prompt #4 its up to you what kind of combination
you want, like last 15 days or last 7 days or last 30 days with Tp highger than
sl or 90%winrate, its up to you, when i run that prompt i want you to look for
all kinds of combination then add it in room strategy"* — and, asked before
starting, *"Start everything now"*.

How a run goes (docs/FORECAST-PROMPTS.md, prompt 4):

1. DATA: a replay written loose enough for every rule set tried
   (watcher_research.SCENARIOS6_WRITE), so no looser rule leans on hindsight.
2. ROUND 1, the known: grid 6, Forecast v2's base grid, the rooms' own rules
   and every winner already kept — measured on GitHub by research.yml reading
   a LIST of rule sets from this repo (`write_round`, `scenarios=file:...`).
3. NEW ROUNDS: one step on every dial around the 20 best, never a rule set
   already tried on this data (`neighbours`, the tried ids beside the store),
   until a round beats nothing already kept, or 5 rounds.
4. WINNING, by a fair pick (`winners`): money after the reality check in every
   complete month AND in the newest 15 days, ranked by the WORST complete
   month, then the worst 15-day stretch — never by the best.

What is kept (`keep`): every winner, never deleted, with the day and run that
found it, its rules in words and its trades, in
~/.tradingagents/forecast_v2/room_strategies.jsonl — on the store's drive.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUNDS_DIR = ROOT / "research" / "p4"
WINDOWS = (7, 15, 30)
LINES = tuple(float(x) for x in range(40, 100, 5))          # 40 .. 95
TRADES = (1, 3, 5, 10, 20, 30, 40, 50)
SHAPES = ("any", ">", "1.5x", "2x", "=", "<")
CAPS = (0.0, 1.0, 1.5, 2.0, 3.0)
FLOORS = (0.0, 1.0, 2.0, 3.0)
DIALS = ("window_days", "on_winrate", "min_trades", "tp_rule", "max_sl", "min_tp")
TOP = 20
MAX_ROUNDS = 5


def _home() -> Path:
    """The store's folder. ROOM_STRATEGIES_HOME points a TRIAL or a test
    somewhere else, so nothing measured on old data can land in the real,
    never-delete store."""
    import os

    from tradingagents import market_sweep as msw

    p = Path(os.environ.get("ROOM_STRATEGIES_HOME") or (Path(msw.HOME) / "forecast_v2"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def store_path() -> Path:
    return _home() / "room_strategies.jsonl"


def tried_path(replay_run: str) -> Path:
    return _home() / f"room_strategies_tried_{replay_run}.json"


def cfg(window_days, on_winrate, min_trades, tp_rule, max_sl, min_tp=0.0) -> dict:
    """One room strategy as the watcher's cfg, raw, the rooms' way."""
    from tradingagents import forecast_rules as fr

    return fr.cfg_of(int(window_days), float(on_winrate), int(min_trades), str(tp_rule),
                     float(max_sl), min_tp=float(min_tp) or None)


def dials(c: dict) -> tuple:
    return tuple(c.get(k) if k != "min_tp" else float(c.get("min_tp") or 0) for k in DIALS)


def sid(c: dict) -> str:
    """The id a room strategy is kept under: Forecast v2's (forecast_rules)."""
    from tradingagents import forecast_rules as fr

    return fr.rule_id(c)


# ------------------------------------------------------------- round 1
_KEPT: dict = {}          # path -> (mtime, size, winners)


def kept() -> list[dict]:
    """Every winner kept so far, in the order first found — each the NEWEST
    line written for its id (a later run re-measures a winner by appending,
    never by rewriting), with the day it was FIRST found. Read again only
    when the file has changed."""
    path = store_path()
    try:
        st = path.stat()
    except OSError:
        return []
    hit = _KEPT.get(str(path))
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    import numpy as np

    first: dict = {}
    latest: dict = {}
    order: list = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            w = json.loads(line)
        except ValueError:
            continue
        # TRADES AS ONE ARRAY, never lists of lists: round 1 kept 673 winners
        # holding 2,427,758 trades, ~400 MB of Python objects inside the API
        # process against ~58 MB as (n, 3) float64
        w["trades"] = np.asarray(w.get("trades") or [], dtype=np.float64).reshape(-1, 3)
        if w["id"] not in first:
            first[w["id"]] = w.get("found_at")
            order.append(w["id"])
        latest[w["id"]] = w
    out = [{**latest[i], "found_at": first[i]} for i in order]
    _KEPT[str(path)] = (st.st_mtime, st.st_size, out)
    return out


def round1() -> list[dict]:
    """Grid 6, Forecast v2's base grid, the rooms' rules and every kept
    winner, each once (by its Forecast v2 id). Options are left out: the list
    is measured by research.yml's walk, which has none."""
    from tradingagents import forecast_rules as fr
    from tradingagents import profiles
    from tradingagents import watcher_research as rs

    out, seen = [], set()

    def add(c):
        c = cfg(*(c.get(k, d) for k, d in zip(DIALS, (30, 90.0, 20, ">", 2.0, 0.0))))
        k = sid(c)
        if k not in seen:
            seen.add(k)
            out.append(c)
    for c in rs.scenarios6():
        add(c)
    for c in fr.base_grid():
        add(c)
    for p in profiles.BUILTIN:
        if p.get("rules"):
            add({**rs.CURRENT, **p["rules"]})
    add({**rs.CURRENT, **rs.RAW})                              # Main
    for w in kept():
        add(w["cfg"])
    return out


def write_round(name: str, sets: list[dict]) -> Path:
    """The round's rule sets as a file the GitHub shard reads
    (`scenarios=file:research/p4/<name>.json`): only the dials, compact."""
    ROUNDS_DIR.mkdir(parents=True, exist_ok=True)
    p = ROUNDS_DIR / f"{name}.json"
    rows = [dict(zip(DIALS, dials(c))) for c in sets]
    p.write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")
    return p


def read_round(path: str) -> list[dict]:
    """What research_shard runs for `scenarios=file:<path>`."""
    rows = json.loads((ROOT / path).read_text(encoding="utf-8"))
    return [cfg(*(r[k] for k in DIALS)) for r in rows]


# ------------------------------------------------------------ new rounds
def _steps(values: tuple, v) -> list:
    if v not in values:
        return list(values)
    i = values.index(v)
    return [values[j] for j in (i - 1, i + 1) if 0 <= j < len(values)]


def neighbours(best: list[dict], tried: set) -> list[dict]:
    """One step on every dial around each of `best`, never a rule set in
    `tried` (Forecast v2 ids): the window and the target shape try every
    other value, the numbers move to the next value either side."""
    out, seen = [], set(tried)
    for b in best:
        base = dict(zip(DIALS, dials(b)))
        moves = ([("window_days", w) for w in WINDOWS if w != base["window_days"]]
                 + [("on_winrate", v) for v in _steps(LINES, float(base["on_winrate"]))]
                 + [("min_trades", v) for v in _steps(TRADES, int(base["min_trades"]))]
                 + [("tp_rule", v) for v in SHAPES if v != base["tp_rule"]]
                 + [("max_sl", v) for v in _steps(CAPS, float(base["max_sl"] or 0))]
                 + [("min_tp", v) for v in _steps(FLOORS, float(base["min_tp"] or 0))])
        for k, v in moves:
            c = cfg(**{**base, k: v})
            i = sid(c)
            if i not in seen:
                seen.add(i)
                out.append(c)
    return out


# ------------------------------------------------------------- winning
def _month(ms: float) -> str:
    return dt.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m")


def measure(trades, end_ms: int, reality: dict) -> dict:
    """A rule set's months, its newest 15 days and its worst 15-day stretch,
    straight and after the reality check (forecast_v2.corrected)."""
    from tradingagents import forecast_v2 as f2

    import numpy as np
    t = np.asarray(trades, dtype=np.float64).reshape(-1, 3) if len(trades) else np.zeros((0, 3))
    end_month = _month(end_ms)
    by: dict = {}
    for x, p in zip(t[:, 1], t[:, 2]):
        m = by.setdefault(_month(x), [0, 0, 0.0])
        m[0] += 1
        m[1] += int(p > 0)
        m[2] += float(p)
    months = []
    for m in sorted(by):
        n, w, p = by[m]
        months.append({"month": m, "complete": m != end_month, "trades": n, "wins": w,
                       "profit": round(p, 2), "corrected": f2.corrected(p, n, reality)})
    lo = end_ms - 15 * 86_400_000
    last = t[t[:, 1] > lo]
    n15, p15 = len(last), float(last[:, 2].sum()) if len(last) else 0.0
    # the worst stretch of 15 days in a row, by the day each trade closed
    worst15 = None
    if len(t):
        day = (t[:, 1] // 86_400_000).astype(np.int64)
        d0, d1 = int(day.min()), int(day.max())
        pnl = np.bincount(day - d0, weights=t[:, 2], minlength=d1 - d0 + 1)
        cnt = np.bincount(day - d0, minlength=d1 - d0 + 1)
        if len(pnl) >= 15:
            cs, cc = np.r_[0, np.cumsum(pnl)], np.r_[0, np.cumsum(cnt)]
            sums, ns = cs[15:] - cs[:-15], cc[15:] - cc[:-15]
            k = int(np.argmin(sums))
            worst15 = f2.corrected(float(sums[k]), int(ns[k]), reality)
    return {"months": months, "last15": {"trades": n15, "profit": round(p15, 2),
                                         "corrected": f2.corrected(p15, n15, reality)},
            "worst15": worst15}


def is_winner(m: dict) -> tuple[bool, str]:
    """Money after the reality check in EVERY complete month and in the newest
    15 days (which a pick made on the complete months never saw)."""
    done = [x for x in m["months"] if x["complete"]]
    if not done:
        return False, "no complete month"
    for x in done:
        if x["corrected"] is None:
            return False, "no reality check yet"
        if x["corrected"] <= 0:
            return False, f"lost money in {x['month']} after the reality check"
    if (m["last15"]["corrected"] or 0) <= 0:
        return False, "lost money in the newest 15 days after the reality check"
    return True, ""


def rank_key(m: dict) -> tuple:
    """The WORST complete month first, then the worst 15-day stretch."""
    done = [x["corrected"] for x in m["months"] if x["complete"] and x["corrected"] is not None]
    return (min(done) if done else float("-inf"),
            m["worst15"] if m["worst15"] is not None else float("-inf"))


# ---------------------------------------------------------------- keep
def keep(winners: list[dict], run: str, replay_run: str, now: float | None = None,
         remeasured: list[dict] | None = None) -> int:
    """Append every winner not kept yet, with the day and run that found it,
    and a fresh line for every kept one this run measured again
    (`remeasured`, winner or not — a kept winner that now loses shows
    "stopped working"). Never rewrites a line: the store only grows."""
    now = time.time() if now is None else now
    have = {w["id"] for w in kept()}
    new = [w for w in winners if w["id"] not in have]
    again = [w for w in (remeasured or []) if w["id"] in have]
    if not new and not again:
        return 0
    with store_path().open("a", encoding="utf-8") as fh:
        for w in new:
            fh.write(json.dumps({**w, "found_at": int(now), "found_by": "prompt 4",
                                 "run": run, "replay_run": replay_run, "measured_at": int(now)},
                                separators=(",", ":")) + "\n")
        for w in again:
            fh.write(json.dumps({**w, "found_at": int(now), "found_by": "prompt 4",
                                 "run": run, "replay_run": replay_run, "measured_at": int(now)},
                                separators=(",", ":")) + "\n")
    return len(new)


def remember_tried(replay_run: str, ids: list[str]) -> int:
    p = tried_path(replay_run)
    have = set(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else set()
    have |= set(ids)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(have)), encoding="utf-8")
    tmp.replace(p)
    return len(have)


def tried(replay_run: str) -> set:
    p = tried_path(replay_run)
    return set(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else set()


# ------------------------------------------------------------ one round
def _reports_dir(replay_run: str) -> Path:
    """Where the replay's own reports were saved (replay_collect.OUT_DIR —
    `~/.tradingagents/replay`, not the sweep's HOME, which is one folder
    deeper and held no reports: the first draft looked there)."""
    from tradingagents import replay_collect as rc

    return Path(rc.OUT_DIR) / f"reports-{replay_run}"


def check_complete(art_dir: str, replay_run: str, reports: str | None = None) -> dict:
    """Refuse to score a round with a hole in it. Every replay shard that
    measured coins (its report says so) must be back from EVERY slice, with
    the same combinations in each — a missing job would otherwise just add up
    to a smaller number, and a rule set would look worse (or better) than it
    is with nothing on the page to say so. The research plan leaves the empty
    shards out on purpose (.github/scripts/research_plan.py)."""
    rep = Path(reports) if reports else _reports_dir(replay_run)
    want = set()
    for f in sorted(rep.rglob("replay-report-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if int(d.get("coins_done") or 0) > 0:
            want.add(int(f.stem.rsplit("-", 1)[1]))
    if not want:
        raise ValueError(f"no replay report with coins under {rep}: cannot tell what a whole round is")
    got: dict = {}
    chunks = None
    for f in sorted(Path(art_dir).rglob("research-*.json")):
        m = json.loads(f.read_text(encoding="utf-8"))
        chunks = int(m.get("chunks") or 1)
        got.setdefault(int(m.get("chunk") or 0), {})[int(m["shard"])] = int(m.get("books") or 0)
    if chunks is None:
        raise ValueError(f"no research results under {art_dir}")
    missing = [(s, c) for c in range(chunks) for s in sorted(want) if s not in got.get(c, {})]
    if missing:
        raise ValueError(f"{len(missing)} job(s) missing from {art_dir} — (shard, slice) {missing[:12]}"
                         f"{' ...' if len(missing) > 12 else ''}; redo them before scoring")
    for s in sorted(want):
        books = {got[c][s] for c in range(chunks)}
        if len(books) != 1 or 0 in books:
            raise ValueError(f"shard {s} read {sorted(books)} combinations across its slices; "
                             "every slice must read the whole shard")
    return {"shards": sorted(want), "chunks": chunks,
            "combinations": sum(got[0][s] for s in want)}


def finish(name: str, art_dir: str, data_dir: str, replay_run: str) -> dict:
    """Add up a round's GitHub research, keep its winners, remember every rule
    set it tried, and write the next round's list (neighbours of the 20 best
    not tried yet). Returns what the chat reports."""
    import numpy as np

    from tradingagents import forecast_rules as fr
    from tradingagents import forecast_v2 as f2
    from tradingagents import research_merge as rmg

    whole = check_complete(art_dir, replay_run, reports=data_dir)
    reality = f2.live()["reality"]["all"]
    path = rmg.merge(name, art_dir, data_dir, log_top=100, reality=reality)
    res = json.loads(path.read_text(encoding="utf-8"))
    rows = res["rows"]
    n_tried = remember_tried(replay_run, [sid(r["cfg"]) for r in rows])
    ranked = sorted(rows, key=lambda r: rank_key(r["p4"]), reverse=True)
    winners = []
    for r in ranked:
        if not r["p4"]["winner"]:
            continue
        ok, why = fr.deployable(r["cfg"])
        t = np.asarray(r.get("p4_trades") or [], dtype=np.float64).reshape(-1, 3)
        winners.append({"id": sid(r["cfg"]), "cfg": r["cfg"], "words": fr.words(r["cfg"]),
                        "deployable": ok, "deploy_why": why, "p4": r["p4"],
                        "trades": [[int(a), int(b), round(float(c), 4)] for a, b, c in t]})
    have = {w["id"] for w in kept()}
    again = []
    for r in rows:
        i = sid(r["cfg"])
        if i in have and i not in {w["id"] for w in winners}:
            ok, why = fr.deployable(r["cfg"])
            t = np.asarray(r.get("p4_trades") or [], dtype=np.float64).reshape(-1, 3)
            again.append({"id": i, "cfg": r["cfg"], "words": fr.words(r["cfg"]), "deployable": ok,
                          "deploy_why": why, "p4": r["p4"],
                          "trades": [[int(a), int(b), round(float(c), 4)] for a, b, c in t]})
    new = keep(winners, name, replay_run, remeasured=winners + again)
    nxt = neighbours([r["cfg"] for r in ranked[:TOP]], tried(replay_run))
    nxt_path = write_round(f"{name}-next", nxt) if nxt else None
    return {"round": name, "rule_sets": len(rows), "tried_total": n_tried,
            "shards": whole["shards"], "combinations": whole["combinations"],
            "winners": len(winners), "kept_new": new,
            "best": [{"id": sid(r["cfg"]), "words": fr.words(r["cfg"]),
                      "worst_month": rank_key(r["p4"])[0], "winner": r["p4"]["winner"]}
                     for r in ranked[:5]],
            "next": len(nxt), "next_file": str(nxt_path.relative_to(ROOT)).replace("\\", "/")
            if nxt_path else None, "reality": {k: reality.get(k) for k in ("took", "gap")}}


# --------------------------------------------------------- the page's table
def _max_open(t) -> int:
    import numpy as np
    if not len(t):
        return 0
    ev = np.concatenate([np.c_[t[:, 0], np.ones(len(t))], np.c_[t[:, 1], -np.ones(len(t))]])
    ev = ev[np.lexsort((ev[:, 1], ev[:, 0]))]          # a close before an open at a tie
    return int(np.cumsum(ev[:, 1]).max())


_TABLE: dict = {}         # (from, to, store, reality) -> every kept winner measured
_TABLE_KEPT = 8


def _measured(from_s: float, to_s: float, reality: dict) -> list[dict]:
    """Every kept winner re-measured over [from_s, to_s], unfiltered."""
    import numpy as np

    from tradingagents import forecast_v2 as f2

    rows = []
    lo, hi = from_s * 1000, to_s * 1000
    for w in kept():
        t = np.asarray(w.get("trades") if w.get("trades") is not None else [],
                       dtype=np.float64).reshape(-1, 3)
        t = t[(t[:, 1] >= lo) & (t[:, 1] <= hi)] if len(t) else t
        n = len(t)
        p = t[:, 2] if n else np.zeros(0)
        wins = int((p > 0).sum())
        win_avg = float(p[p > 0].mean()) if wins else None
        loss_avg = float(-p[p <= 0].mean()) if n - wins else None
        be = (round(100 * loss_avg / (win_avg + loss_avg), 1)
              if win_avg is not None and loss_avg is not None else None)
        run = worst = 0.0
        rn = wn = 0
        for v in p:
            if v > 0:
                run, rn = 0.0, 0
            else:
                run += v
                rn += 1
                if run < worst:
                    worst, wn = run, rn
        day = (t[:, 1] // 86_400_000).astype(np.int64) if n else np.zeros(0, np.int64)
        worst_day = float(min(np.bincount(day - day.min(), weights=p))) if n else None
        days = max(1.0, (to_s - from_s) / 86_400)
        mx = _max_open(t)
        months = [m for m in w["p4"]["months"] if m["complete"]]
        row = {"id": w["id"], "words": w["words"], "found_at": w["found_at"],
               "found_by": w.get("found_by", "prompt 4"), "run": w.get("run"),
               "deployable": w["deployable"], "deploy_why": w.get("deploy_why", ""),
               "window": int(w["cfg"]["window_days"]), "tp": w["cfg"]["tp_rule"],
               "max_sl": float(w["cfg"].get("max_sl") or 0),
               "trades": n, "per_day": round(n / days, 1), "wins": wins, "losses": n - wins,
               "winrate": round(100 * wins / n, 1) if n else None, "break_even": be,
               "profit": round(float(p.sum()), 2), "corrected": f2.corrected(float(p.sum()), n, reality),
               "worst_day": round(worst_day, 2) if worst_day is not None else None,
               "worst_run": round(worst, 2), "worst_run_n": wn, "max_open": mx,
               "money_needed": round(mx * 5.0, 2),
               "worst_month": min((m["corrected"] for m in months if m["corrected"] is not None),
                                  default=None),
               "still_works": (w["p4"]["last15"]["corrected"] or 0) > 0}
        rows.append(row)
    return rows


def table(from_s: float, to_s: float, *, min_winrate: float = 0, min_profit: float | None = None,
          window: int = 0, deployable: str = "", find: str = "", sort: str = "worst_month",
          page: int = 1, per: int = 25, reality: dict | None = None) -> dict:
    """Every kept winner, RE-MEASURED over exactly [from_s, to_s] from its own
    stored trades (never a month scaled up or down), filtered and paged here.
    The measuring is remembered per date range until the store or the reality
    check changes: the page asks again every minute, and 2.4 million trades
    do not need walking again to answer the same question. `reality` is
    the reality check to use — the API hands in the Forecast page's own copy
    (forecast_v2_api.live), because working it out took 14 s a request (122 s
    on the first after a restart) while the page asks every minute."""
    if reality is None:
        from tradingagents import forecast_v2 as f2

        reality = f2.live()["reality"]["all"]
    path = store_path()
    try:
        st = path.stat()
        sig = (str(path), st.st_mtime, st.st_size)
    except OSError:
        sig = (str(path), None, None)
    ck = (float(from_s), float(to_s), sig, reality.get("took"), reality.get("gap"))
    measured = _TABLE.get(ck)
    if measured is None:
        measured = _measured(from_s, to_s, reality)
        while len(_TABLE) >= _TABLE_KEPT:
            _TABLE.pop(next(iter(_TABLE)))
        _TABLE[ck] = measured
    total = len(measured)
    want = find.strip().lstrip("#").upper() if find else ""
    rows = []
    for row in measured:
        if want and row["id"] != want:
            continue
        if row["winrate"] is not None and row["winrate"] < min_winrate:
            continue
        if min_profit is not None and row["profit"] < min_profit:
            continue
        if window and row["window"] != int(window):
            continue
        if deployable == "yes" and not row["deployable"] or deployable == "no" and row["deployable"]:
            continue
        rows.append(row)
    key = {"worst_month": lambda r: r["worst_month"] if r["worst_month"] is not None else -1e9,
           "profit": lambda r: r["profit"], "corrected": lambda r: r["corrected"] or -1e9,
           "winrate": lambda r: r["winrate"] or -1, "found": lambda r: r["found_at"]}.get(sort)
    if key is None:
        raise ValueError(f"unknown sort {sort!r}")
    rows.sort(key=key, reverse=True)
    pages = max(1, -(-len(rows) // per))
    page = min(max(1, int(page)), pages)
    return {"rows": rows[(page - 1) * per: page * per], "matched": len(rows), "kept": total,
            "page": page, "pages": pages, "from": from_s, "to": to_s,
            "reality": {k: reality.get(k) for k in ("took", "gap")}, "margin": 5.0, "leverage": 20}




# ------------------------------------------------- a round in daily totals
def measure_days(edges, n, w, p, end_ms: int, reality: dict) -> dict:
    """`measure` from a rule set's day-by-day totals (research_shard OUT=daily):
    the same months, newest 15 days and worst 15-day stretch, by whole local
    days — the newest 15 days are the 15 days to the data's end, the day that
    holds their start counted whole."""
    import numpy as np

    from tradingagents import forecast_v2 as f2

    edges = np.asarray(edges, dtype=np.int64)
    n, w, p = (np.asarray(x) for x in (n, w, p))
    end_month = _month(end_ms)
    by: dict = {}
    for k in np.nonzero(n)[0]:
        m = by.setdefault(_month(int(edges[k]) + 3_600_000), [0, 0, 0.0])
        m[0] += int(n[k])
        m[1] += int(w[k])
        m[2] += float(p[k])
    months = [{"month": m, "complete": m != end_month, "trades": v[0], "wins": v[1],
               "profit": round(v[2], 2), "corrected": f2.corrected(v[2], v[0], reality)}
              for m, v in sorted(by.items())]
    last = edges[1:] > end_ms - 15 * 86_400_000
    n15, p15 = int(n[last].sum()), float(p[last].sum())
    worst15 = None
    if len(p) >= 15:
        cs, cc = np.r_[0, np.cumsum(p)], np.r_[0, np.cumsum(n)]
        sums, ns = cs[15:] - cs[:-15], cc[15:] - cc[:-15]
        k = int(np.argmin(sums))
        worst15 = f2.corrected(float(sums[k]), int(ns[k]), reality)
    tot_n, tot_w = int(n.sum()), int(w.sum())
    return {"months": months, "last15": {"trades": n15, "profit": round(p15, 2),
                                         "corrected": f2.corrected(p15, n15, reality)},
            "worst15": worst15,
            "total": {"trades": tot_n, "wins": tot_w, "profit": round(float(p.sum()), 2),
                      "winrate": round(100 * tot_w / tot_n, 1) if tot_n else None}}


def finish_daily(name: str, art_dir: str, replay_run: str) -> dict:
    """Add up a round run with OUT=daily: score every rule set, remember them
    as tried, write the WINNERS' list for the small OUT=full run that brings
    their trades home (`finish` then keeps them), and the next round's list
    (neighbours of the 20 best, untried)."""
    import numpy as np

    from tradingagents import forecast_rules as fr
    from tradingagents import forecast_v2 as f2

    whole = check_complete(art_dir, replay_run)
    reality = f2.live()["reality"]["all"]
    arts = sorted(Path(art_dir).rglob("research-*.json"))
    metas = [json.loads(a.read_text(encoding="utf-8")) for a in arts]
    packs = [np.load(a.with_suffix(".npz")) for a in arts]
    if not metas or "day_edges" not in metas[0]:
        raise ValueError(f"{art_dir} holds no daily research (run research.yml with output=daily)")
    edges = metas[0]["day_edges"]
    end = int(metas[0]["end_ms"])
    slices: dict = {}
    for i, m in enumerate(metas):
        slices.setdefault(int(m.get("chunk") or 0), []).append(i)
    rows = []
    for c_ in sorted(slices):
        items = slices[c_]
        for j, rule in enumerate(metas[items[0]]["rules"]):
            cfg_ = rule["cfg"]
            n = sum(packs[i][f"{j}_{pt}_dn"].astype(np.int64) for i in items for pt in ("train", "test"))
            w = sum(packs[i][f"{j}_{pt}_dw"].astype(np.int64) for i in items for pt in ("train", "test"))
            p = sum(packs[i][f"{j}_{pt}_dp"].astype(np.float64) for i in items for pt in ("train", "test"))
            meas = measure_days(edges, n, w, p, end, reality)
            ok, why = is_winner(meas)
            meas["winner"], meas["why"] = ok, why
            rows.append({"id": sid(cfg_), "cfg": cfg_, "words": fr.words(cfg_), "p4": meas,
                         "deployable": fr.deployable(cfg_)[0]})
    n_tried = remember_tried(replay_run, [r["id"] for r in rows])
    ranked = sorted(rows, key=lambda r: rank_key(r["p4"]), reverse=True)
    winners = [r for r in ranked if r["p4"]["winner"]]
    have = {w_["id"] for w_ in kept()}
    # the winners, plus every kept winner this round measured (re-measured)
    confirm = winners + [r for r in rows if r["id"] in have and not r["p4"]["winner"]]
    conf_path = write_round(f"{name}-confirm", [r["cfg"] for r in confirm]) if confirm else None
    nxt = neighbours([r["cfg"] for r in ranked[:TOP]], tried(replay_run))
    nxt_path = write_round(f"{name}-next", nxt) if nxt else None
    out = {"round": name, "rule_sets": len(rows), "tried_total": n_tried, "winners": len(winners),
           "shards": whole["shards"], "combinations": whole["combinations"],
           "best": [{"id": r["id"], "words": r["words"], "worst_month": rank_key(r["p4"])[0],
                     "worst15": r["p4"]["worst15"], "last15": r["p4"]["last15"]["corrected"],
                     "winner": r["p4"]["winner"], "why": r["p4"]["why"]} for r in ranked[:10]],
           "confirm": len(confirm), "confirm_file": _rel(conf_path),
           "next": len(nxt), "next_file": _rel(nxt_path),
           "reality": {k: reality.get(k) for k in ("took", "gap")}}
    (_home() / f"p4_{name}.json").write_text(json.dumps({**out, "rows": rows}, separators=(",", ":")),
                                             encoding="utf-8")
    return out


def _rel(p: Path | None) -> str | None:
    return str(p.relative_to(ROOT)).replace("\\", "/") if p else None


def main(argv: list | None = None) -> int:
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 5 and args[0] == "finish":
        print(json.dumps(finish(*args[1:]), indent=1))
        return 0
    if len(args) == 4 and args[0] == "daily":
        print(json.dumps(finish_daily(*args[1:]), indent=1))
        return 0
    if len(args) == 2 and args[0] == "round1":
        p = write_round(args[1], round1())
        print(p, len(json.loads(p.read_text(encoding="utf-8"))), "rule sets")
        return 0
    print("usage: room_strategies round1 <name> | daily <name> <research folder> <replay run id> "
          "| finish <name> <research folder> <replay folder> <replay run id>")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
