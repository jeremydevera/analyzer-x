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
    when the file has changed.

    AND THE NEWEST DAILY RE-TEST ON TOP (Oct 07, 2026: "it should be updated
    everyday justd like the backtest"): a winner the daily re-test measured
    AFTER its newest line carries the re-test's trades and months
    (`retested`), and says so (`retested: True`). Its id, rules and the day it
    was found never change; a winner the re-test did not reach keeps its own
    line's numbers — never zeros."""
    base = _kept_lines()
    now = retested()
    if not now or not base:
        return base
    sig = (_stamp(store_path()), _stamp(now_path()))
    hit = _KEPT.get("retested")
    if hit and hit[0] == sig:
        return hit[1]
    by, made = now["by_id"], float(now["meta"].get("made_at") or 0)
    out = [{**w, "trades": by[w["id"]]["trades"], "p4": by[w["id"]]["p4"], "measured_at": made,
            "retested": True}
           if w["id"] in by and made >= float(w.get("measured_at") or 0) else w
           for w in base]
    _KEPT["retested"] = (sig, out)
    return out


def _stamp(p: Path):
    try:
        st = p.stat()
    except OSError:
        return None
    return (st.st_mtime, st.st_size)


def _kept_lines() -> list[dict]:
    """The never-delete store alone: the newest line per id, first found first."""
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


# ------------------------------------------------ the daily re-test's file
LIST_NAME = "kept"          # research/p4/kept.json — the list GitHub re-tests every day


def now_path() -> Path:
    """The newest daily re-test of every kept winner (room_strategies_daily):
    ONE file, swapped in whole each day — never appended to the never-delete
    store, which would grow by every trade of every winner every day (the
    992 kept hold 4,302,254 trades, ~150 MB a copy)."""
    return _home() / "room_strategies_now.npz"


_NOW: dict = {}


def retested() -> dict:
    """{"meta": {...}, "by_id": {id: {"trades": (n, 3), "p4": {...}}}} — the
    newest daily re-test, or {} before the first one. A file that cannot be
    read is {} and SAID, so the kept numbers stay on the page — never zeros."""
    import numpy as np

    from tradingagents.research_merge import T0_MIN

    p = now_path()
    sig = _stamp(p)
    if sig is None:
        return {}
    hit = _NOW.get(str(p))
    if hit and hit[0] == sig:
        return hit[1]
    try:
        with np.load(p, allow_pickle=False) as z:
            meta = json.loads(str(z["meta"]))
            e, x, pr, offs = z["e"], z["x"], z["p"], z["offs"]
            by = {}
            for k, rid in enumerate(meta["ids"]):
                a, b = int(offs[k]), int(offs[k + 1])
                # profit to 4 places, as research_merge keeps a winner's
                # trades in the store — so a row reads the same either way
                t = (np.column_stack([(e[a:b].astype(np.int64) + T0_MIN) * 60_000,
                                      (x[a:b].astype(np.int64) + T0_MIN) * 60_000,
                                      np.round(pr[a:b].astype(np.float64), 4)]).astype(np.float64)
                     if b > a else np.zeros((0, 3)))
                by[rid] = {"trades": t, "p4": meta["p4"][k]}
    except (OSError, ValueError, KeyError, IndexError) as exc:
        print(f"[room strategies] the daily re-test file {p} could not be read: {exc!r}", flush=True)
        return {}
    out = {"meta": {k: v for k, v in meta.items() if k not in ("ids", "p4")}, "by_id": by}
    _NOW[str(p)] = (sig, out)
    return out


def write_list() -> Path:
    """research/p4/kept.json: every kept winner's rules, the list the daily
    re-test hands GitHub (research.yml `scenarios=file:...`). A runner reads
    the COMMITTED file, so whoever keeps new winners commits it with them."""
    return write_round(LIST_NAME, [w["cfg"] for w in _kept_lines()])


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
        # a room switched off on ANOTHER window (the 1-4 day rooms, Oct 07,
        # 2026) is not a rule set the research walk measures: its six dials
        # have no `judge_days`, and raw_trades refuses a second window — left
        # out, never researched as a different rule set under another id
        if p.get("rules") and not int(p["rules"].get("judge_days") or 0):
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
    # the list the DAILY RE-TEST hands GitHub, now holding these winners too —
    # committed with this round's files, or tomorrow's re-test misses them
    write_list()
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
    """Every kept winner re-measured over [from_s, to_s], unfiltered — over
    the trades that OPENED AND CLOSED inside those dates (`inside`)."""
    import numpy as np

    from tradingagents import forecast_v2 as f2

    rows = []
    lo, hi = from_s * 1000, to_s * 1000
    for w in kept():
        t = np.asarray(w.get("trades") if w.get("trades") is not None else [],
                       dtype=np.float64).reshape(-1, 3)
        t = t[inside(t, lo, hi)] if len(t) else t
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


def span() -> tuple[int | None, int | None]:
    """When the saved trades begin and end: the first and the last CLOSE
    across every kept winner, in ms. A winner's trades are measured once, on
    the replay prompt 4 ran on (Oct 02, 2026: every trade closes by 8:00am
    that day), so a date range past the end holds nothing until prompt 4 runs
    again — and the page has to say so rather than print zeros as a result."""
    lo = hi = None
    for w in kept():
        t = w["trades"]
        if len(t):
            a, b = float(t[:, 1].min()), float(t[:, 1].max())
            lo = a if lo is None else min(lo, a)
            hi = b if hi is None else max(hi, b)
    return (int(lo) if lo is not None else None, int(hi) if hi is not None else None)


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
    on the first after a restart) while the page asks every minute.

    A ROW WITH NO TRADE IN THE DATES PASSES NO FLOOR (Oct 07, 2026). It has
    no win rate and made nothing, so "win rate 90% or better" and "made at
    least $X" are claims it cannot meet. It used to pass both: on the old
    "last 15 days" button (Sep 23 to Oct 08, 2026 on the operator's screen)
    26 of the 992 kept had no trade, and a 90% floor listed 32 rows — those
    26 beside the 6 that really won 90% or more. Over the last 3 days all 992
    have none (every saved trade closes by Oct 02, 2026 8:00am), so the floor
    would have kept every one. RCA-2026-10-07-N."""
    if reality is None:
        from tradingagents import forecast_v2 as f2

        reality = f2.live()["reality"]["all"]
    path = store_path()
    try:
        st = path.stat()
        sig = (str(path), st.st_mtime, st.st_size)
    except OSError:
        sig = (str(path), None, None)
    # and the daily re-test's file: a new re-test is on the very next ask
    sig += (_stamp(now_path()),)
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
        if min_winrate and (row["winrate"] is None or row["winrate"] < min_winrate):
            continue
        if min_profit is not None and (not row["trades"] or row["profit"] < min_profit):
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
    first, last = span()
    return {"rows": rows[(page - 1) * per: page * per], "matched": len(rows), "kept": total,
            "page": page, "pages": pages, "from": from_s, "to": to_s,
            # how many of ALL kept have a trade in the dates, before any filter,
            # and where the saved trades begin and end — so an empty range names
            # what it examined (CLAUDE.md, "an empty page may never speak for
            # the store") instead of reading as 992 strategies that did nothing
            "with_trades": sum(1 for r in measured if r["trades"]),
            "data_start": first, "data_end": last,
            "reality": {k: reality.get(k) for k in ("took", "gap")}, "margin": 5.0, "leverage": 20}


def inside(t, lo_ms: float, hi_ms: float):
    """Which trades belong to the dates [lo_ms, hi_ms]: those that OPENED and
    CLOSED inside them (operator, Oct 08, 2026, on "last 1 day": "i want to
    see the trades for past 1 day only because currently i see all past
    trades" — the list held every trade that CLOSED in the day, so one opened
    Oct 05, 2026 7:30pm showed in a day starting Oct 07, 2026 7:58pm). One
    rule for a row's numbers and its trade list, so the two always agree."""
    return (t[:, 0] >= lo_ms) & (t[:, 1] <= hi_ms)


def trades(rid: str, from_s: float, to_s: float, *, page: int = 1, per: int = 10) -> dict:
    """One kept winner's trades that OPENED AND CLOSED in [from_s, to_s] —
    exactly the trades its row in `table` counts — oldest first, each with the
    running total, and the total for the dates (operator, Oct 07, 2026: "if i
    input 3 days show me the room strat and its trade for past 3 days"). Paged
    here, ten a page like every list on the Forecast page; the pop-up's CSV
    export asks for all of them in one page.

    What a trade carries is what the replay kept: when it opened, when it
    closed and what it made at $5 x 20x — NOT which coin (research_merge keeps
    `p4_trades` as (entry, exit, profit)). The page says so; it never guesses."""
    import numpy as np

    want = (rid or "").strip().lstrip("#").upper()
    w = next((x for x in kept() if x["id"] == want), None)
    if w is None:
        raise KeyError(f"no room strategy #{want} is kept")
    t = np.asarray(w["trades"], dtype=np.float64).reshape(-1, 3)
    lo, hi = from_s * 1000, to_s * 1000
    sel = t[inside(t, lo, hi)] if len(t) else t
    sel = sel[np.lexsort((sel[:, 0], sel[:, 1]))] if len(sel) else sel   # by close, then open
    n = len(sel)
    p = sel[:, 2] if n else np.zeros(0)
    run = np.cumsum(p) if n else np.zeros(0)
    pages = max(1, -(-n // per))
    page = min(max(1, int(page)), pages)
    a, b = (page - 1) * per, page * per
    rows = [{"n": a + i + 1, "opened": int(o), "closed": int(c), "profit": round(float(v), 2),
             "total": round(float(r), 2)}
            for i, (o, c, v, r) in enumerate(zip(sel[a:b, 0], sel[a:b, 1], p[a:b], run[a:b]))]
    wins = int((p > 0).sum())
    return {"id": want, "words": w["words"], "from": from_s, "to": to_s,
            "trades": n, "wins": wins, "losses": n - wins,
            # the dates' own win rate, by the table's own formula (_measured),
            # so the pop-up, its CSV and the row print one number
            "winrate": round(100 * wins / n, 1) if n else None,
            "profit": round(float(p.sum()), 2) if n else 0.0,
            "rows": rows, "page": page, "pages": pages, "per": per,
            # this rule set's own saved trades, whatever the dates
            "saved": len(t), "first": int(t[:, 1].min()) if len(t) else None,
            "last": int(t[:, 1].max()) if len(t) else None,
            "margin": 5.0, "leverage": 20}




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


# ------------------------------------------------- every account's machines
# Operator, Oct 02, 2026 3:52pm: "moving forward i want 40 machines to be used
# always, i want this setting to be remembered" — two GitHub accounts, 20
# machines each (cloud_sweep.fleets). Round 2's confirm run and round 3 had
# sat queued behind another session's replay on one account while the other
# account's 20 were idle. A round is therefore always split: the replay's
# shards that hold coins are dealt between every account that can run the
# workflow, balanced by their size, and each account researches its share
# (research.yml `shards` takes a list, `source_repo` names the replay's repo).
EMPTY_SHARD_BYTES = 4096
# machines one free account runs at once. A round with ONE slice on 20 shards
# that hold coins kept 10 machines busy on each account and 10 idle
# (round 5's confirm, Oct 02, 2026 4:45pm: 37062305761 + 37062320182), so the
# slices are raised until every account has at least this many jobs
MACHINES_PER_ACCOUNT = 20


def replay_shard_sizes(run: str, repo: str) -> dict[int, int]:
    """{shard: bytes} of a replay run's replay-<N> artifacts that hold coins."""
    from tradingagents import cloud_sweep as cs

    raw = cs._gh("api", f"repos/{repo}/actions/runs/{run}/artifacts?per_page=100", "--paginate",
                 "--jq", '.artifacts[] | select(.expired | not) | "\\(.name) \\(.size_in_bytes)"')
    out: dict = {}
    for line in raw.splitlines():
        name, _, size = line.strip().partition(" ")
        if name.startswith("replay-") and name[7:].isdigit() and int(size) > EMPTY_SHARD_BYTES:
            out[int(name[7:])] = int(size)
    return out


def split_shards(sizes: dict[int, int], n: int) -> list[list[int]]:
    """Deal the shards between `n` accounts, biggest first to the lightest
    load, so both finish at about the same time. Every shard once."""
    loads = [[0, i, []] for i in range(max(1, n))]
    for shard in sorted(sizes, key=lambda s: (-sizes[s], s)):
        tgt = min(loads, key=lambda x: (x[0], x[1]))
        tgt[0] += sizes[shard]
        tgt[2].append(shard)
    return [sorted(x[2]) for x in loads]


def dispatch(round_file: str, output: str, chunks: int, replay_run: str, replay_repo: str,
             end_ms: int, fleets: list | None = None) -> list[dict]:
    """Start research.yml on EVERY account that can run it, each with its
    share of the replay's shards. Returns [{repo, run, shards}] — download
    them all into one folder and `daily`/`finish` score the whole round
    (check_complete refuses it while any account's share is missing)."""
    from tradingagents import cloud_sweep as cs

    if fleets is None:
        fleets, refused = cs.usable_fleets()
        for why in refused:
            print(f"account left out: {why}")
    if not fleets:
        raise ValueError("no GitHub account can run research.yml")
    sizes = replay_shard_sizes(replay_run, replay_repo)
    if not sizes:
        raise ValueError(f"replay run {replay_run} on {replay_repo} has no shard with coins")
    shares = split_shards(sizes, len(fleets))
    # EVERY MACHINE BUSY: the same slice count on every account (the round is
    # scored slice by slice), raised until the smallest share fills its 20
    smallest = min((len(x) for x in shares if x), default=1)
    chunks = max(int(chunks), -(-MACHINES_PER_ACCOUNT // smallest))
    out = []
    for slug, share in zip(fleets, shares):
        if not share:
            continue
        shards = "[" + ",".join(map(str, share)) + "]"
        before = {r["databaseId"] for r in json.loads(cs._gh(
            "run", "list", "--repo", slug, "--workflow", "research.yml", "--limit", "20",
            "--json", "databaseId"))}
        cs._gh("workflow", "run", "research.yml", "--repo", slug,
               "-f", f"source_run={replay_run}", "-f", f"source_repo={replay_repo}",
               "-f", f"shards={shards}", "-f", f"end_ms={int(end_ms)}",
               "-f", f"scenarios=file:{round_file}", "-f", f"chunks={int(chunks)}",
               "-f", f"output={output}")
        run = None
        for _ in range(30):
            time.sleep(2)
            new = [r["databaseId"] for r in json.loads(cs._gh(
                "run", "list", "--repo", slug, "--workflow", "research.yml", "--limit", "20",
                "--json", "databaseId")) if r["databaseId"] not in before]
            if new:
                run = max(new)
                break
        out.append({"repo": slug, "run": run, "shards": share, "chunks": chunks,
                    "jobs": len(share) * chunks, "bytes": sum(sizes[s] for s in share)})
    return out


def fetch(dest: str, runs: list[str]) -> Path:
    """Download every account's share ("<repo>:<run>") into one folder on the
    store's drive."""
    from tradingagents import cloud_sweep as cs

    import os

    d = Path(dest)
    d.mkdir(parents=True, exist_ok=True)
    # gh stages each zip in TMP — the SYSTEM drive unless told otherwise
    # (a round is ~345 MB); point it at the store's own scratch
    old = {k: os.environ.get(k) for k in ("TMP", "TEMP")}
    tmp = cs._scratch()
    try:
        if tmp:
            os.environ["TMP"] = os.environ["TEMP"] = tmp
        for spec in runs:
            repo, _, run = spec.rpartition(":")
            cs._gh("run", "download", run, "--repo", repo, "-D", str(d), timeout=3600)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return d


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
    if len(args) == 7 and args[0] == "dispatch":
        # dispatch <round file> <daily|full> <chunks> <replay run> <replay repo> <end ms>
        print(json.dumps(dispatch(args[1], args[2], int(args[3]), args[4], args[5], int(args[6])),
                         indent=1))
        return 0
    if len(args) >= 3 and args[0] == "fetch":
        # fetch <folder> <repo>:<run> [<repo>:<run> ...]
        print(fetch(args[1], args[2:]))
        return 0
    print("usage: room_strategies round1 <name> | daily <name> <research folder> <replay run id> "
          "| finish <name> <research folder> <replay folder> <replay run id> "
          "| dispatch <round file> <daily|full> <chunks> <replay run> <replay repo> <end ms> "
          "| fetch <folder> <repo>:<run> ...")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
