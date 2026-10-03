"""Backtest a room = replay the room's OWN rules over time, day by day.

Operator, Oct 02, 2026 (docs/OPERATOR-ASKS.md): *"backtest room should like
backtest for the room strategy example / what strategies did switched on and
off for Sept 3, 4, 5, 6, 7 and so on"*, and on how to settle each trade:
*"you should be using the backtest rows because this is the source of truth
for example in backtest when you click a specific id, it will show the rows
of its trade made, that's where you should look"*. Binding spec:
docs/superpowers/specs/2026-10-02-room-replay-design.md.

One run, end to end:

    candidates   every Backtest v2 row that could EVER pass the room's
                 switch-on line inside the stored span (SQL on the v2 index,
                 read-only, counted out loud)
    trade lists  each candidate's own Backtest v2 trade list,
                 market_sweep.trades_for(..., store=stores.V2) -- the list the
                 operator sees when they click that id -- cached per id on G:
                 and rebuilt only when what it is computed from changes
    replay       watcher_replay.simulate with the room's own rules
                 (strategy_watcher.cfg_of, the function the live watcher
                 reads) on the LIVE watcher's timing (watcher_replay.
                 live_schedule: switch-off every hour, switch-on whenever
                 strategy_watcher._on_due says)
    practice     every practice trade the room really closed in the range,
                 switched-off strategies included, reconciled trade by trade
    saved        ~/.tradingagents/v2/room_replay/<room>/ (by range + latest)

NO LOOK-AHEAD. A trade is KNOWN at the end of the minute it closed in (the end
of its exit bar where no minute settled it) and a check counts only what was
known by then. The one exception is stated on the page: the live watcher read
the daily update's numbers, hours old, and this replay reads each trade the
minute it closed.
"""
from __future__ import annotations

import bisect
import collections
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

from tradingagents import (
    profiles,
    room_backtest as rb,
    stores,
    watcher_policy as wp,
    watcher_replay as wr,
)

HOME = Path(stores.V2.home) / "room_replay"
VERSION = 1                 # a cached trade list of another VERSION is rebuilt
DAY_MS = 86_400_000
MIN_MS = 60_000
BASE_MARGIN = 5.0           # every room trades $5 a strategy (strategy_watcher.MARGIN)
# a worker holds Python + pandas + one coin's minutes: 428 MB private measured
# Oct 02, 2026 on YMTCSTOCK 1h after three trades_for calls
WORKER_MB = 500
HEADROOM_MB = 1500          # left for the site, the runners and the download
MAX_WORKERS = 8
PER_PAGE = 10               # forecast_v2_api.PER_PAGE: every Forecast list pages ten
STARTING_S = 120            # how long a spawned run may take to reach its lock
VIEWS = ("days", "events", "slots", "trades", "practice", "reconcile")
CAND_COLS = ("id", "coin", "tf", "signal", "th", "sl", "tp", "trades", "wins",
             "winrate", "profit", "cost_of_tp", "gate", "t15", "w15")
GROUPS = ("preset", "sep25", "sep27ml")       # every other signal is "classic"
# The screen asks no floor (operator, Oct 03, 2026: "what's this textbox i
# dont need this, i only need to input date and id of the room"): the API
# nominates rows within this many points of the room's own switch-on line.
# Measured on #6B08FF64 (80%): 70 nominated 4,801 rows; a fixed 70 for a 70%
# room would have been no floor below its line at all.
FLOOR_BELOW = 10.0
# Bumped when a saved replay would answer differently for the same range:
# 2 = the room's own switch-ons are always candidates (Oct 03, 2026).
RESULT_TAG = "r2"


# --------------------------------------------------------------- the paths
def _home() -> Path:
    return Path(HOME)


def room_dir(room: str) -> Path:
    return _home() / room


def trades_dir() -> Path:
    return _home() / "trades"


def _write_json(path: Path, obj, *, loud: bool = True) -> None:
    """Atomic. A progress write never raises (CLAUDE.md: telemetry never ends
    a run); a result write does."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
        for i in range(60):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                # Windows refuses a rename while a reader has the file open
                time.sleep(0.05 * (i + 1))
        os.replace(tmp, path)
    except OSError:
        if loud:
            raise


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _when(ms) -> str:
    from tradingagents.positions_view import fmt_when

    return fmt_when(float(ms) / 1000) if ms else "—"


def _midnight(day: str) -> int:
    """A local day key `YYYY-MM-DD` (a KEY, never printed) as its midnight."""
    d = dt.date.fromisoformat(str(day))
    return int(dt.datetime(d.year, d.month, d.day).timestamp() * 1000)


def _next_midnight(day: str) -> int:
    """The midnight that ENDS a local day — 23 or 25 hours later on the two
    days a year the clocks change, never a fixed 24."""
    d = dt.date.fromisoformat(str(day)) + dt.timedelta(days=1)
    return int(dt.datetime(d.year, d.month, d.day).timestamp() * 1000)


# ---------------------------------------------------------------- the room
def _check_room(room: str) -> None:
    if room not in profiles.shown():
        raise ValueError(f"no room {room!r}; the rooms are {profiles.shown()}")


def _watcher_state(room: str) -> dict:
    """The room's watcher state file, READ ONLY (strategy_watcher._read would
    write a seed for a room that has none)."""
    from tradingagents import strategy_watcher as sw

    p = Path(sw.STATE)
    path = p if room == profiles.MAIN else profiles.dir_for(room, home=p.parent) / p.name
    got = _read_json(path)
    return got if isinstance(got, dict) else {}


def rules_for(room: str) -> dict:
    """The rules the room's LIVE watcher reads — its own state through
    `strategy_watcher.cfg_of` (window 15 or the store's 30), the room's seed
    in `profiles.BUILTIN` where the state has none yet."""
    from tradingagents import strategy_watcher as sw

    _check_room(room)
    st = _watcher_state(room)
    if not st.get("cfg"):
        seed = (profiles.get(room) or {}).get("rules")
        st = {**st, "cfg": dict(seed or {})}
    return sw.cfg_of(st)


def coin_cap(room: str) -> int:
    """The runner's own per-coin limit in this room's PRACTICE book:
    `max_slices` when partial TP/SL is on for demo (the default), else one."""
    from tradingagents import auto_trader as at

    with profiles.using(room):
        s = at.load_settings()
    return int(at.max_slices(s)) if at.partial_on(s, True) else 1


def group_of(signal: str) -> str:
    from tradingagents import rows_index as ri

    return next((g for g in GROUPS if ri.in_group(signal, g)), "classic")


# ---------------------------------------------------------------- candidates
def _db_of(store) -> Path:
    """The store's table — and never the operator's REAL one under a test run
    (a fixture that forgot to pass its own store once sampled the live
    52-million-row table for 40 seconds, Oct 02, 2026)."""
    db = Path((store or stores.V2).rows_db)
    if os.environ.get("PYTEST_CURRENT_TEST") and db == Path(stores.V2.rows_db):
        raise RuntimeError("a test may not read the real Backtest v2 table; pass a store")
    return db


def wins_floor(cfg: dict) -> int:
    """The fewest wins a row's 30 days must hold for SOME window inside them
    to clear the line: min_trades at on_winrate (80% of 30 = 24)."""
    return max(0, math.ceil(float(cfg["on_winrate"]) * int(cfg["min_trades"]) / 100 - 1e-9))


def cost_block_pct() -> float:
    """Live's block line, in the percent `cost_of_tp` prints (50)."""
    from tradingagents import auto_trader as at

    return float(at.COST_RATIO_BLOCK) * 100


def candidate_sql(cfg: dict, cols=CAND_COLS, *, min_wr30: float | None = None,
                  below: bool = False) -> tuple[str, list]:
    """Spec item 4: TP vs SL by the room's rule, SL at or under its cap, cost
    under live's block line (or not read when measured), flat, minute-exact,
    and enough trades and wins in the row's 30 days to pass at some moment.

    `min_wr30` is the NOMINATION FLOOR (Oct 02, 2026), never on by default:
    item 4 exactly is ~5 million rows for a 15-day room, so a run may ask
    only rows whose own 30-day win rate is at least this — and says so, with
    an audit of what it left out (`below=True` selects exactly those)."""
    from tradingagents import rows_index as ri

    tp_rule = str(cfg.get("tp_rule") or ">")
    if tp_rule not in ri.RECENT_TP:
        raise ValueError(f"unknown target rule {tp_rule!r}")
    sql = (f"SELECT {', '.join(cols)} FROM rows WHERE res = '1m' "
           f"AND (sizing = 'flat' OR sizing IS NULL) AND trades >= ? AND wins >= ? "
           f"AND (cost_of_tp IS NULL OR cost_of_tp < ?)" + ri.RECENT_TP[tp_rule])
    args: list = [int(cfg["min_trades"]), wins_floor(cfg), cost_block_pct()]
    cap = float(cfg.get("max_sl") or 0)
    if cap > 0:
        sql += " AND sl <= ?"
        args.append(cap)
    floor = float(cfg.get("min_tp") or 0)
    if floor > 0:
        sql += " AND tp >= ?"
        args.append(floor - 1e-9)
    if min_wr30 is not None:
        # `+winrate`: never an index on it — the pass and the pair seek stay
        # what they are (rows_wr2 fetches each match off the disk, 26 ms each)
        sql += " AND +winrate < ?" if below else " AND +winrate >= ?"
        args.append(float(min_wr30))
    return sql, args


# A run past this many trade lists is refused unless forced: measured
# Oct 02, 2026, a list costs ~0.1 s a worker (48 in 2.6 s on 3 workers,
# spawn included) and ~20 KB of cache, so 250,000 is about two hours and 5 GB.
MAX_LISTS = 250_000
SAMPLE_PAIRS = 60


class TooMany(ValueError):
    """The run would rebuild more trade lists than this PC can in hours."""


def estimate(cfg: dict, *, store=None, min_wr30: float | None = None,
             pairs: int = SAMPLE_PAIRS, seed: int = 7) -> dict:
    """How many candidates there are, ESTIMATED from `pairs` random pairs of
    the v2 index (its pair index; ~30-50 s) — never the full scan, which took
    over 40 minutes on this PC's disk on Oct 02, 2026 while a download ran."""
    import random

    from tradingagents import rows_index as ri

    store = store or stores.V2
    db = _db_of(store)
    if not db.exists():
        return {"estimate": 0, "pairs": 0, "of": 0}
    with ri._open(readonly=True, db_path=db) as con:
        every = [r[0] for r in con.execute("SELECT pair FROM pairs")]
        if not every:
            return {"estimate": 0, "pairs": 0, "of": 0}
        pick = random.Random(seed).sample(every, min(pairs, len(every)))
        sql, args = candidate_sql(cfg, ("id",), min_wr30=min_wr30)
        sql = sql.replace("SELECT id FROM rows WHERE",
                          "SELECT count(*) FROM rows WHERE pair = ? AND")
        n = sum(con.execute(sql, [pr] + args).fetchone()[0] for pr in pick)
    return {"estimate": int(round(n * len(every) / len(pick))), "sampled": n,
            "pairs": len(pick), "of": len(every)}


def audit_sample(cfg: dict, min_wr30: float, *, store=None, want: int = 400,
                 seed: int = 11, batches: int = 20) -> list:
    """Up to `want` random candidate rows BELOW the floor (random row ids,
    so no full scan), to measure how many of them the floor wrongly left out."""
    import random

    from tradingagents import rows_index as ri

    store = store or stores.V2
    rnd = random.Random(seed)
    out: list = []
    with ri._open(readonly=True, db_path=_db_of(store)) as con:
        top = int(con.execute("SELECT max(rowid) FROM rows").fetchone()[0] or 0)
        have = {r[1] for r in con.execute("PRAGMA table_info(rows)")}
        cols = tuple(c for c in CAND_COLS if c in have)
        sql, args = candidate_sql(cfg, cols, min_wr30=min_wr30, below=True)
        seen: set = set()
        for _ in range(batches):
            if len(out) >= want or not top:
                break
            # never the same row twice across batches: a repeated row would
            # count one miss as two
            ids = sorted(set(rnd.sample(range(1, top + 1), min(4000, top))) - seen)
            seen.update(ids)
            if not ids:
                break
            q = sql.replace(" WHERE ", f" WHERE rowid IN ({','.join('?' * len(ids))}) AND ", 1)
            out += [{k: r[k] for k in cols} for r in con.execute(q, ids + args)]
    return [_cand_of(r) for r in out[:want]]


def _cand_of(r: dict) -> dict:
    from tradingagents import backtest_report as br

    th = float(r.get("th") or 0)
    c = {"coin": str(r["coin"]), "tf": str(r["tf"]), "signal": str(r["signal"]),
         "th": th, "sl": float(r["sl"]), "tp": float(r["tp"]),
         "trades30": int(r["trades"]), "wins30": int(r["wins"]),
         "winrate30": r.get("winrate"),
         "cost_of_tp": r.get("cost_of_tp"), "gate": r.get("gate") or ""}
    # the id the live watcher gives the same row (watcher_candidates._fresh)
    c["id"] = br.row_code(c["coin"], c["tf"], c["signal"], th, c["sl"], c["tp"],
                          "flat", res="1m")
    c["group"] = group_of(c["signal"])
    return c


def _cands_cache(cfg: dict, min_wr30, limit: int, db: Path) -> Path:
    """Where one room-rule set's candidates are kept: the SEARCH is the slow
    part (one pass over the whole v2 table, over 40 minutes on this disk on
    Oct 03, 2026) and it does not depend on the date range, so a second range
    for the same rules reuses it — until the table itself changes (the daily
    update re-files it, which moves its size or time)."""
    st = db.stat()
    # SQLite writes land in the -wal file first and reach the main file only
    # at a checkpoint, so both are read: a row filed an hour ago that sits in
    # the log is still a changed table
    wal = db.with_name(db.name + "-wal")
    w = wal.stat() if wal.exists() else None
    key = json.dumps({"sql": candidate_sql(cfg, CAND_COLS, min_wr30=min_wr30),
                      "limit": int(limit or 0), "db": [st.st_size, int(st.st_mtime)],
                      "wal": [w.st_size, int(w.st_mtime)] if w else None},
                     sort_keys=True, default=str)
    return _home() / "candidates" / f"{hashlib.sha1(key.encode()).hexdigest()[:16]}.json"


def candidates(cfg: dict, *, store=None, limit: int = 0,
               min_wr30: float | None = None) -> tuple[list, dict]:
    """Every candidate row, and how many there were and why each could pass."""
    store = store or stores.V2
    db = _db_of(store)
    if not db.exists():
        return [], {"count": 0, "ready": False,
                    "why": f"no Backtest v2 table at {db} yet"}
    try:
        cache = _cands_cache(cfg, min_wr30, limit, db)
    except OSError:
        cache = None
    hit = _read_json(cache) if cache else None
    if isinstance(hit, dict) and isinstance(hit.get("cands"), list):
        return hit["cands"], {**hit["info"], "cached": True}
    out, info = _search(cfg, store=store, db=db, limit=limit, min_wr30=min_wr30)
    if cache:
        _write_json(cache, {"cands": out, "info": info}, loud=False)
    return out, info


def auto_floor(cfg: dict) -> float:
    """The nomination floor the screen's runs use: FLOOR_BELOW points under
    the room's own switch-on line."""
    return max(0.0, float(cfg["on_winrate"]) - FLOOR_BELOW)


def room_picks(room: str, end_ms: int, *, store=None) -> tuple[list, dict]:
    """Every strategy the room's OWN watcher switched on up to `end_ms`, as
    candidates — whatever its 30-day win rate. A 15-day room switches on rows
    the floor cannot see: #DS598KQV APHSTOCK 1h ibs was switched on in
    #6B08FF64 at Oct 01, 2026 12:44pm on 24 of 29 trades in 15 days while its
    30-day win rate was 69.49%, under the 70% floor, so the first replay
    could never have matched that practice trade (14 of the room's 204
    switch-ons that day were missing). Looked up in each pair's own file by
    the id the watcher wrote (the v2 table has no index on `id`)."""
    from tradingagents import backtest_report as br
    from tradingagents import market_sweep as ms
    from tradingagents import profiles
    from tradingagents import strategy_watcher as sw

    store = store or stores.V2
    try:
        with profiles.using(room):
            path = Path(sw._log_path())
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    want: dict = {}
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("action") != "on" or e.get("mode") != "act":
            continue
        try:
            at_ms = float(e.get("at") or 0) * 1000
        except (TypeError, ValueError):
            continue
        rid = str(e.get("id") or "").lstrip("#").upper()
        if rid and e.get("coin") and e.get("tf") and at_ms <= end_ms:
            want.setdefault(rid, e)
    by_pair: dict = collections.defaultdict(dict)
    for rid, e in want.items():
        coin = str(e["coin"]).removesuffix("_USDT")
        by_pair[(coin, str(e["tf"]))][rid] = e
    out: list = []
    missing: list = []
    for (coin, tf), items in sorted(by_pair.items()):
        try:
            rows = ms.pair_rows(coin, tf, root=str(store.home)) or []
        except Exception:                                      # noqa: BLE001
            rows = []
        found: dict = {}
        for r in rows:
            if (r.get("sizing") or "flat") != "flat":
                continue
            try:
                sig, tp, sl = str(r["signal"]), float(r["tp"]), float(r["sl"])
            except (KeyError, TypeError, ValueError):
                continue
            # cheap test first: a pair file holds every barrier of every signal
            if not any(str(e.get("signal")) == sig and _same(e.get("tp"), tp)
                       and _same(e.get("sl"), sl) for e in items.values()):
                continue
            rid = br.row_code(coin, tf, sig, float(r.get("th") or 0), sl, tp, "flat", res="1m")
            if rid in items and rid not in found:
                found[rid] = _cand_of({**r, "coin": coin, "tf": tf,
                                       "trades": r.get("trades") or 0,
                                       "wins": r.get("wins") or 0})
        out += [found[k] for k in sorted(found)]
        missing += sorted(set(items) - set(found))
    return out, {"count": len(want), "found": len(out), "missing": missing}


def _same(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return False


def _search(cfg: dict, *, store, db: Path, limit: int, min_wr30) -> tuple[list, dict]:
    from tradingagents import rows_index as ri

    t0 = time.time()
    with ri._open(readonly=True, db_path=db) as con:
        have = {r[1] for r in con.execute("PRAGMA table_info(rows)")}
        cols = tuple(c for c in CAND_COLS if c in have)
        sql, args = candidate_sql(cfg, cols, min_wr30=min_wr30)
        # ONE PASS OVER THE TABLE, never the win-rate index: with a floor the
        # planner seeks rows_wr2 and then fetches every match off the disk —
        # measured Oct 02, 2026, 20,000 rows in 514 s (26 ms each), so the 75%
        # floor's 1,052,433 rows would have taken about 7.5 hours; one pass
        # reads the 18 GB file in order
        sql = sql.replace(" FROM rows WHERE ", " FROM rows NOT INDEXED WHERE ", 1)
        if limit:
            sql += " LIMIT ?"
            args.append(int(limit))
        got = [{k: r[k] for k in cols} for r in con.execute(sql, args)]
    out = [_cand_of(r) for r in got]
    out.sort(key=lambda c: (c["coin"], c["tf"], c["id"]))
    return out, {"count": len(out), "ready": True, "limit": int(limit or 0),
                 "min_wr30": min_wr30,
                 "seconds": round(time.time() - t0, 1),
                 "by_group": dict(collections.Counter(c["group"] for c in out)),
                 "no_cost_reading": sum(1 for c in out if c["cost_of_tp"] is None
                                        or c["gate"] == "unknown"),
                 "floors": {"trades": int(cfg["min_trades"]), "wins": wins_floor(cfg),
                            "cost_under_pct": cost_block_pct(),
                            "max_sl": float(cfg.get("max_sl") or 0),
                            "tp_rule": str(cfg.get("tp_rule") or ">")},
                 "sql": sql}


# ------------------------------------------------------------- trade lists
_CODE_SIG: list = []


def _code_sig() -> str:
    """What a trade list is COMPUTED BY: the engine's own files. A cached
    list never outlives a change to them."""
    if not _CODE_SIG:
        root = Path(__file__).resolve().parent
        parts = [str(VERSION)]
        for f in sorted(root.glob("*.py")):
            if f.name in ("auto_trader.py", "market_sweep.py", "backtest_report.py",
                          "strategy_keys.py") or f.name.startswith("signals"):
                st = f.stat()
                parts.append(f"{f.name}:{st.st_size}:{st.st_mtime_ns}")
        _CODE_SIG.append(hashlib.blake2s("|".join(parts).encode(), digest_size=8).hexdigest())
    return _CODE_SIG[0]


def _inputs(c: dict, store) -> list[Path]:
    """Every file `trades_for` reads for this row (store=stores.V2)."""
    from tradingagents import market_sweep as ms

    sym = f"{c['coin']}_USDT"
    return [Path(store.candles) / f"{sym}-{store.fine_tf}.json",
            Path(store.home) / "rows" / f"{c['coin']}-{c['tf']}.json",
            ms._state_file(c["coin"], c["tf"], str(store.home)),
            Path(store.home) / "costs" / f"{sym}.json"]


def stamp_of(c: dict, store) -> str:
    """Taken BEFORE the list is read, so a file that changes while it is
    being read can only make the cache look stale, never fresh."""
    from tradingagents import market_sweep as ms

    parts = [_code_sig(), str(ms._rule_stamp(c["signal"]))]
    for p in _inputs(c, store):
        try:
            st = p.stat()
            parts.append(f"{st.st_size}:{st.st_mtime_ns}")
        except OSError:
            parts.append("-")
    return "|".join(parts)


def record(c: dict, got: dict, stamp: str | None, coin_first_ms) -> dict:
    """`trades_for`'s answer as the replay's list. Each trade is
    `[entry_ms, known_ms, pnl, closed, exit_ms, why, side]`: `known_ms` is the
    END of the exit minute (the exit bar where no minute settled it) — the
    first moment the result existed — and is what every window counts by."""
    from tradingagents import backtest_report as br
    from tradingagents.rolling30 import _parse_when

    bar_ms = int(br.TFS[c["tf"]][1]) * 1000
    trades = []
    for t in got.get("log") or []:
        entry = _parse_when(t["entry time"])
        closed = t.get("why") != "END"
        ex = t.get("exit_minute_ms")
        if ex is not None:
            exit_ms = int(ex)
            known = exit_ms + MIN_MS
        else:
            exit_ms = _parse_when(t["exit time"])
            known = exit_ms + bar_ms
        trades.append([entry, known, float(t["pnl $"]), bool(closed), exit_ms,
                       str(t.get("why") or ""), str(t.get("side") or "")])
    return {"v": VERSION, "id": c["id"], "stamp": stamp, "coin": c["coin"], "tf": c["tf"],
            "signal": c["signal"], "th": c["th"], "sl": c["sl"], "tp": c["tp"],
            "bar_ms": bar_ms, "trades": trades, "why": str(got.get("why") or ""),
            "first_ms": _parse_when(got["first"]) if got.get("first") else None,
            "end_ms": (_parse_when(got["last"]) + bar_ms) if got.get("last") else None,
            "coin_first_ms": coin_first_ms, "row_last": got.get("row_last"),
            "candles_last": got.get("candles_last"),
            "candles_short": bool(got.get("candles_short")),
            "window_from": got.get("window_from"), "fee_from": got.get("fee_from"),
            "costs": got.get("costs"),
            "totals": {k: got.get(k) for k in ("trades", "wins", "losses", "profit")}}


def _cache_read(rid: str, stamp: str):
    got = _read_json(trades_dir() / f"{rid}.json")
    if isinstance(got, dict) and got.get("v") == VERSION and got.get("stamp") == stamp:
        return got
    return None


@contextlib.contextmanager
def _one_coin_memo():
    """ONLY INSIDE A REPLAY PROCESS: one coin's files are read and parsed once
    for all of its candidates, instead of twice a pair file and once the
    minutes per `trades_for` call. Same functions, same answers — each caller
    gets its own copy of a frame — and everything is dropped when the coin is
    done, so a worker never holds more than one coin's candles."""
    from tradingagents import market_sweep as ms

    names = ("cached_candles", "pair_rows", "load_states", "load_costs", "bars_from_1m")
    orig = {n: getattr(ms, n) for n in names}
    memo: dict = {}

    def cached_candles(symbol, tf, candles_dir=None):
        k = ("c", symbol, tf, str(candles_dir))
        if k not in memo:
            memo[k] = orig["cached_candles"](symbol, tf, candles_dir=candles_dir)
        df = memo[k]
        return None if df is None else df.copy()

    def bars_from_1m(df_1m, tf):
        if df_1m is None or not len(df_1m):
            return orig["bars_from_1m"](df_1m, tf)
        d = df_1m["Date"]
        k = ("b", len(df_1m), str(d.iloc[0]), str(d.iloc[-1]), tf)
        if k not in memo:
            try:
                memo[k] = orig["bars_from_1m"](df_1m, tf)
            except ValueError as exc:
                memo[k] = exc
        got = memo[k]
        if isinstance(got, ValueError):
            raise ValueError(str(got))
        return got.copy()

    def pair_rows(coin, tf, root=None):
        k = ("r", coin, tf, str(root))
        if k not in memo:
            memo[k] = orig["pair_rows"](coin, tf, root)
        return memo[k]

    def load_states(coin, tf, root=None):
        k = ("s", coin, tf, str(root))
        if k not in memo:
            memo[k] = orig["load_states"](coin, tf, root)
        return memo[k]

    def load_costs(symbol, root=None):
        k = ("k", symbol, str(root))
        if memo.get(k) is None:
            # a missing file is NOT remembered: trades_for writes it on the
            # first call, and the second must read what it wrote
            memo[k] = orig["load_costs"](symbol, root)
        return memo[k]

    local = {"cached_candles": cached_candles, "bars_from_1m": bars_from_1m,
             "pair_rows": pair_rows, "load_states": load_states, "load_costs": load_costs}
    try:
        for n in names:
            setattr(ms, n, local[n])
        yield
    finally:
        for n in names:
            setattr(ms, n, orig[n])
        memo.clear()


def _coin_first(coin: str, store):
    from tradingagents import market_sweep as ms

    with contextlib.suppress(Exception):                       # noqa: BLE001
        df = ms.cached_candles(f"{coin}_USDT", store.fine_tf, candles_dir=store.candles)
        if df is not None and len(df):
            return int(df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")[0])
    return None


def rebuild_coin(job: tuple) -> dict:
    """One coin's candidates, in this process: `(store, coin, cands, memo,
    cache_dir)`. Top level, so a spawned worker can import it — and the cache
    folder travels in the job, because a spawned worker imports this module
    afresh and would otherwise write beside its DEFAULT home, not the
    caller's."""
    from tradingagents import market_sweep as ms

    store, coin, cands, memo, cache_dir = job
    out: dict = {}
    with (_one_coin_memo() if memo else contextlib.nullcontext()):
        first = _coin_first(coin, store)
        for c in cands:
            try:
                got = ms.trades_for(c["coin"], c["tf"], signal=c["signal"], th=c["th"],
                                    sl=c["sl"], tp=c["tp"], sizing="flat",
                                    base_margin=BASE_MARGIN, store=store)
            except Exception as exc:                           # noqa: BLE001
                # NAMED, never dropped (rule 20) — and never cached: the next
                # run tries again
                out[c["id"]] = record(c, {"log": [], "why": f"could not be rebuilt: "
                                          f"{type(exc).__name__}: {str(exc)[:160]}"},
                                      None, first)
                continue
            rec = record(c, got, c.get("_stamp"), first)
            if c.get("_stamp"):
                with contextlib.suppress(OSError):
                    _write_json(Path(cache_dir) / f"{c['id']}.json", rec)
            out[c["id"]] = rec
    return out


def worker_count(jobs: int, want: int | None = None) -> int:
    """Sized to the memory FREE NOW: (free - headroom) / one worker, never
    more than the CPUs less two or MAX_WORKERS. 0 = in this process."""
    if want is not None:
        return max(0, min(int(want), jobs))
    from tradingagents import portable

    _total, avail = portable.ram_gb()
    by_mem = 1 if avail <= 0 else int((avail * 1024 - HEADROOM_MB) // WORKER_MB)
    by_cpu = max(1, (os.cpu_count() or 2) - 2)
    return max(0, min(by_mem, by_cpu, MAX_WORKERS, jobs))


def build_lists(cands: list, *, store=None, workers: int | None = None, memo: bool = True,
                progress=None, on_list=None) -> tuple[dict, dict]:
    """{id: list record} for every candidate, from the cache where nothing
    it is computed from has changed, rebuilt otherwise — one coin per job,
    in parallel worker processes."""
    store = store or stores.V2
    if not getattr(store, "fine_tf", ""):
        raise ValueError("the room replay reads the Backtest v2 store (minute-exact lists)")
    keep = on_list or (lambda rec: rec)

    class _Kept(dict):
        # every record passes through `on_list` the moment it arrives, so a
        # list the caller has no use for is never held whole
        def update(self, other=(), **kw):
            for k, v in dict(other, **kw).items():
                self[k] = keep(v)
    lists: dict = _Kept()
    todo: dict = {}
    for c in cands:
        st = stamp_of(c, store)
        hit = _cache_read(c["id"], st)
        if hit is not None:
            lists[c["id"]] = keep(hit)
        else:
            todo.setdefault(c["coin"], []).append({**c, "_stamp": st})
    hits = len(lists)
    jobs = sorted(todo.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    n = worker_count(len(jobs), workers)
    done = hits
    if progress:
        progress(done, len(cands))
    failed: list = []
    if n <= 1:
        for coin, cs in jobs:
            lists.update(rebuild_coin((store, coin, cs, memo, str(trades_dir()))))
            done += len(cs)
            if progress:
                progress(done, len(cands))
    else:
        import concurrent.futures as cf
        import multiprocessing as mp

        with cf.ProcessPoolExecutor(max_workers=n, mp_context=mp.get_context("spawn")) as pool:
            futs = {pool.submit(rebuild_coin, (store, coin, cs, True, str(trades_dir()))):
                    (coin, cs) for coin, cs in jobs}
            for f in cf.as_completed(futs):
                coin, cs = futs[f]
                try:
                    lists.update(f.result())
                except Exception as exc:                       # noqa: BLE001
                    failed.append((coin, cs, f"{type(exc).__name__}: {str(exc)[:120]}"))
                done += len(cs)
                if progress:
                    progress(done, len(cands))
    # A FAILED COIN IS REDONE ALONE (CLAUDE.md), here, once
    for coin, cs, _why in failed:
        try:
            lists.update(rebuild_coin((store, coin, cs, memo, str(trades_dir()))))
        except Exception as exc:                               # noqa: BLE001
            for c in cs:
                lists[c["id"]] = keep(record(c, {"log": [], "why": f"could not be rebuilt: "
                                                 f"{type(exc).__name__}: {str(exc)[:120]}"},
                                             None, None))
    return dict(lists), {"cached": hits, "rebuilt": len(cands) - hits, "coins": len(jobs),
                   "workers": n, "worker_failures": [f"{c}: {w}" for c, _cs, w in failed]}


# ------------------------------------------------------------------ helpers
def worst_run(pnls) -> tuple[float, int]:
    """The worst unbroken run of losses: its dollars and how many trades."""
    run = worst = 0.0
    n = worst_n = 0
    for p in pnls:
        if p > 0:
            run, n = 0.0, 0
        else:
            run += p
            n += 1
            if run < worst:
                worst, worst_n = run, n
    return round(worst, 2), worst_n


def _side(pnls: list) -> dict:
    wins = sum(1 for p in pnls if p > 0)
    n = len(pnls)
    w, wn = worst_run(pnls)
    return {"closed": n, "wins": wins, "losses": n - wins,
            "winrate": round(100 * wins / n, 2) if n else None,
            "profit": round(sum(pnls), 2), "worst_streak": w, "worst_streak_trades": wn}


def slot_key(c: dict) -> str:
    """The room's own name for this row's slot: `strategy_key|COIN_USDT`."""
    from tradingagents import strategy_keys as sk

    return f"{sk.key_for(c)}|{c['coin']}_USDT"


def _bar_s_of_key(key: str) -> int:
    """The candle length of a strategy key, read by forecast_v2.spec_of —
    the runner's own recipe first, never a second split of the key (a
    signal name may hold an underscore: RCA-2026-09-24-G)."""
    from tradingagents import forecast_v2 as f2, strategy_keys as sk

    tf = f2.spec_of(key).get("tf")
    return int(sk.TF_SPEC[tf][1]) if tf in sk.TF_SPEC else 0


def _ids_of_slots(room: str) -> dict:
    """{slot: id} for the room's slots the watcher armed — from its settings
    and its own log (a switched-off slot is only in the log)."""
    from tradingagents import strategy_keys as sk, strategy_watcher as sw

    out: dict = {}
    p = Path(sw.LOG)
    path = p if room == profiles.MAIN else profiles.dir_for(room, home=p.parent) / p.name
    with contextlib.suppress(OSError), path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("action") not in ("on", "off") or not d.get("id"):
                continue
            if d.get("signal") in sk.THRESHOLD_SIGNALS:
                continue            # the log carries no threshold: settings below
            with contextlib.suppress(Exception):               # noqa: BLE001
                out[f"{sk.key_for({**d, 'th': 0.0})}|{d['coin']}_USDT"] = str(d["id"])
    with contextlib.suppress(Exception):                       # noqa: BLE001
        from tradingagents import auto_trader as at

        with profiles.using(room):
            ws = at.load_settings().get("watcher_slots") or {}
        for slot, meta in ws.items():
            if meta.get("id"):
                out[slot] = str(meta["id"])
    return out


# ------------------------------------------------------------- the practice
def practice(room: str, lo_ms: int, hi_ms: int, now_s: float) -> dict:
    """Every PRACTICE trade the room closed in [lo_ms, hi_ms] — read from its
    own trade record, so a strategy switched off since is in it — with the
    on/off stretches of every slot (forecast_v2._intervals: its deploy log)."""
    from tradingagents import forecast_v2 as f2

    exits, refused, refused_candles = rb._practice_exits(room)
    stretches = f2._intervals(room, now_s)
    trades = []
    first_s = None
    for slot, xs in exits.items():
        for ex_s, en_s, pnl, why in xs:
            first_s = ex_s if first_s is None else min(first_s, ex_s)
            if lo_ms <= ex_s * 1000 <= hi_ms:
                trades.append({"slot": slot, "exit_ms": int(ex_s * 1000),
                               "entry_ms": int(en_s * 1000), "pnl": round(float(pnl), 4),
                               "why": why})
    trades.sort(key=lambda t: (t["exit_ms"], t["slot"]))
    on_first = min((a for v in stretches.values() for a, _b in v), default=None)
    starts = [s for s in (on_first, first_s) if s is not None]
    return {"trades": trades, "stretches": stretches, "refused": refused,
            "refused_candles": refused_candles,
            "start_ms": int(min(starts) * 1000) if starts else None,
            "slots_off_now": sorted(s for s, v in stretches.items()
                                    if v and v[-1][1] < now_s - 1)}


def _on_at(stretches: list, at_s: float) -> bool:
    return any(a <= at_s < b for a, b in stretches or ())


# --------------------------------------------------------------- the replay
def replay(room: str, from_day: str, to_day: str, *, store=None, workers: int | None = None,
           limit: int = 0, now: float | None = None, progress=None, memo: bool = True,
           min_wr30: float | None = None, force: bool = False, audit: int = 0) -> dict:
    """The whole result for one room and one range (local days, inclusive)."""
    now = time.time() if now is None else float(now)
    store = store or stores.V2
    _check_room(room)
    cfg = rules_for(room)
    window_ms = int(cfg["window_days"]) * DAY_MS
    start_ms = _midnight(from_day)
    end_ms = min(_next_midnight(to_day) - 1, int(now * 1000))
    if end_ms < start_ms:
        raise ValueError("the range ends before it starts")
    say = progress or (lambda *_a, **_k: None)
    if not force and not limit:
        say("estimating", 0, 0)
        est = estimate(cfg, store=store, min_wr30=min_wr30)
        if est["estimate"] > MAX_LISTS:
            ask = ("raise the 30-day win rate floor (min_winrate30) above "
                   f"{float(min_wr30):g}%" if min_wr30 is not None else
                   "ask only rows whose own 30-day win rate is at least a floor "
                   "(min_winrate30)")
            raise TooMany(
                f"about {est['estimate']:,} Backtest v2 rows could pass this room's line "
                f"(estimated from {est['pairs']} of {est['of']:,} pairs) — rebuilding that "
                f"many trade lists takes days on this PC: {ask}, or force it")
    say("candidates", 0, 0)
    cands, cinfo = candidates(cfg, store=store, limit=limit, min_wr30=min_wr30)
    # the room's own switch-ons are ALWAYS replayed, whatever the floor: the
    # point of the page is to check the replay against the room's practice
    picks, pinfo = room_picks(room, end_ms, store=store)
    have = {c["id"] for c in cands}
    added = [c for c in picks if c["id"] not in have]
    cands = cands + added
    cinfo = {**cinfo, "searched": cinfo.get("count", 0), "count": len(cands),
             "room_picks": {**pinfo, "added": len(added)}}
    sched =wr.live_schedule(start_ms, end_ms, bool(cfg.get("raw")))
    on_checks = [a for a, _f, o in sched if o]
    meta = {c["id"]: c for c in cands}
    combos: list = []
    books: dict = {}

    def on_list(rec: dict) -> dict:
        # EXACT, not a shortcut: a list whose row clears the line at NO
        # switch-on check can never be switched on, so it can trade nothing;
        # it is kept as its span and counts only (memory: a raw room has tens
        # of thousands of candidates, most of which never pass)
        c = meta.get(rec.get("id"))
        if c is None or not rec.get("trades"):
            return rec
        combo = {**{k: c[k] for k in ("id", "coin", "tf", "signal", "th", "sl", "tp",
                                      "group", "gate")}, "trades": rec["trades"]}
        book = wr._Book(combo)
        if ever_passes(book, on_checks, window_ms, cfg):
            combos.append(combo)
            books[c["id"]] = book
            return {**rec, "passes": True}
        return {**{k: v for k, v in rec.items() if k != "trades"},
                "trades": [], "n_trades": len(rec["trades"]), "passes": False}
    say("trade lists", 0, len(cands))
    lists, linfo = build_lists(cands, store=store, workers=workers, memo=memo,
                               progress=lambda d, t: say("trade lists", d, t),
                               on_list=on_list)
    if min_wr30 is not None and audit:
        # WHAT THE FLOOR LEFT OUT, measured: random rows under it, their own
        # lists, and how many would have cleared the line at some check
        say("audit", 0, audit)
        sample = audit_sample(cfg, min_wr30, store=store, want=audit)
        a_lists, _ = build_lists(sample, store=store, workers=workers, memo=memo,
                                 progress=lambda d, t: say("audit", d, t))
        a_pass = [c["id"] for c in sample
                  if (a_lists.get(c["id"]) or {}).get("trades")
                  and ever_passes(wr._Book({**c, "trades": a_lists[c["id"]]["trades"]}),
                                  on_checks, window_ms, cfg)]
        cinfo["audit"] = {"sampled": len(sample), "would_pass": len(a_pass),
                          "ids": a_pass[:20]}
    say("replay", 0, 0)
    combos.sort(key=lambda c: c["id"])
    cap = coin_cap(room)
    sim = wr.simulate(combos, start_ms=start_ms, end_ms=end_ms,
                      cfg={**cfg, "coin_slices": cap}, books=books, schedule=sched)
    say("practice", 0, 0)
    pr = practice(room, start_ms, end_ms, now)
    out = _assemble(room, cfg, start_ms, end_ms, now, cands, cinfo, lists, linfo, meta,
                    books, sim, pr, cap, window_ms, sched)
    out["from_day"], out["to_day"] = str(from_day), str(to_day)
    return out


def ever_passes(book, on_checks: list, window_ms: int, cfg: dict) -> bool:
    """Does this strategy's row clear the switch-on line at ANY switch-on
    check? The same `_Book.row` and `watcher_policy.passes_on` simulate
    applies, so a strategy this says no to can never be switched on."""
    for at in on_checks:
        r = book.row(at, window_ms)
        if r is not None and not wp.passes_on(r, cfg):
            return True
    return False


def _in_range(t, start_ms, end_ms) -> bool:
    return bool(t[3]) and start_ms <= int(t[4]) <= end_ms


def _assemble(room, cfg, start_ms, end_ms, now, cands, cinfo, lists, linfo, meta, books,
              sim, pr, cap, window_ms, sched) -> dict:
    day_keys = [wr.day_of(m) for m in wr.local_midnights(start_ms, end_ms)]
    # ---- the switch events, with the numbers each was judged on
    events = []
    gone = "the backtest store no longer holds this row"
    quiet = f"no trade closed in its last {wp.window_words(cfg)}"
    for s in sim["slots"]:
        # watcher_replay's book has no row for a window without a trade, and
        # judge() then speaks of a row the STORE lost; here the store holds
        # every candidate, so the true sentence is the quiet window
        if s.get("off_why") == gone:
            s["off_why"] = quiet
    for e in sim["events"]:
        if e["action"] == "off" and e["why"] == gone:
            e = {**e, "why": quiet}
        c = meta[e["id"]]
        row = books[e["id"]].row(e["at"], window_ms) or {}
        events.append({"at": e["at"], "day": wr.day_of(e["at"]), "action": e["action"],
                       "id": e["id"], "coin": c["coin"], "tf": c["tf"], "signal": c["signal"],
                       "th": c["th"], "tp": c["tp"], "sl": c["sl"], "group": c["group"],
                       "winrate": row.get("winrate"), "trades": row.get("trades", 0),
                       "wins": row.get("wins", 0), "profit": row.get("profit"),
                       "why": e["why"]})
    # ---- each switched-on stretch and what it traded
    slots = []
    traded = []          # (exit_ms, pnl, slot index, trade)
    for i, s in enumerate(sim["slots"]):
        ts = [t for t in s["trades"] if int(t[0]) <= end_ms]
        closed = [t for t in ts if _in_range(t, start_ms, end_ms)]
        pnls = [float(t[2]) for t in sorted(closed, key=lambda t: t[4])]
        side = _side(pnls)
        slots.append({"n": i, "id": s["id"], "coin": s["coin"], "tf": s["tf"],
                      "signal": s["signal"], "th": s["th"], "tp": s["tp"], "sl": s["sl"],
                      "group": s.get("group"), "on_ms": s["on_ms"], "off_ms": s["off_ms"],
                      "on_why": s["on_why"], "off_why": s["off_why"],
                      "open": sum(1 for t in ts if not t[3]
                                  or int(t[4]) > end_ms),
                      **side,
                      "trades": [[int(t[0]), int(t[4]), round(float(t[2]), 2), t[5], t[6]]
                                 for t in sorted(ts, key=lambda t: t[0])]})
        traded += [(int(t[4]), float(t[2]), i, t) for t in closed]
    traded.sort(key=lambda x: (x[0], x[2]))
    # ---- the practice account, beside it
    p_trades = pr["trades"]
    p_start = pr["start_ms"]
    # ---- reconcile, trade by trade
    rec_rows, rec_by_day, rec_tot = _reconcile(room, cands, lists, sim, pr, start_ms, end_ms,
                                               now, traded, slots)
    # ---- per day
    days = []
    bt_total = pr_total = 0.0
    by_day_bt = collections.defaultdict(list)
    for x in traded:
        by_day_bt[wr.day_of(x[0])].append(x[1])
    by_day_pr = collections.defaultdict(list)
    for t in p_trades:
        by_day_pr[wr.day_of(t["exit_ms"])].append(float(t["pnl"]))
    ev_by_day = collections.Counter((e["day"], e["action"]) for e in events)
    cov = _coverage(lists, window_ms)
    for key in day_keys:
        d0 = _midnight(key)
        d1 = min(_next_midnight(key), end_ms + 1)
        run_n = sum(1 for s in slots if s["on_ms"] < d1 and (s["off_ms"] is None
                                                            or s["off_ms"] >= d1))
        bt = _side(by_day_bt.get(key, []))
        # the running totals add the UNROUNDED day, so the last one is the
        # summary's total to the cent (a practice exit carries four places)
        bt_total += sum(by_day_bt.get(key, []))
        row = {"day": key, "at": d0, "on": ev_by_day.get((key, "on"), 0),
               "off": ev_by_day.get((key, "off"), 0), "running": run_n, **bt,
               "total": round(bt_total, 2), **_day_coverage(cov, d0, window_ms)}
        if p_start is not None and d1 > p_start:
            pd_ = _side(by_day_pr.get(key, []))
            pr_total += sum(by_day_pr.get(key, []))
            row["practice"] = {**pd_, "total": round(pr_total, 2)}
            row["reconcile"] = rec_by_day.get(key, {})
        else:
            row["practice"] = None           # the room did not exist yet: no column
            row["reconcile"] = None
        days.append(row)
    full_from = cov["full_from"](day_keys, window_ms)
    bt_side = _side([x[1] for x in traded])
    pr_side = _side([float(t["pnl"]) for t in p_trades])
    summary = {"backtest": {**bt_side, "switched_on": sum(1 for e in events if e["action"] == "on"),
                            "switched_off": sum(1 for e in events if e["action"] == "off"),
                            "ids": len({s["id"] for s in slots}),
                            "open": sum(s["open"] for s in slots)},
               "practice": {**pr_side, "from_ms": p_start,
                            "slots": len({t["slot"] for t in p_trades}),
                            "slots_switched_off": len(set(pr["slots_off_now"])
                                                      & {t["slot"] for t in p_trades})},
               "reconcile": rec_tot}
    off_now = set(pr["slots_off_now"])
    listed = [r for r in lists.values() if not r.get("why")]
    no_list = collections.Counter(_why_short(r.get("why")) for r in lists.values()
                                  if r.get("why"))
    notes = _notes(room, cfg, cinfo, listed, no_list, cov, full_from, pr, cap, start_ms,
                   end_ms, rec_tot, day_keys, window_ms)
    notes.insert(0, _hindsight(days, cov))
    return {"room": room, "name": "Main" if room == profiles.MAIN else f"#{room}",
            "computed_at": now, "start_ms": start_ms, "end_ms": end_ms,
            "cfg": {k: cfg.get(k) for k in ("on_winrate", "off_winrate", "min_trades",
                                            "tp_rule", "max_sl", "min_tp", "window_days",
                                            "raw", "max_new_per_day", "max_slots",
                                            "max_per_coin", "cooldown_days")},
            "coin_cap": cap, "margin": BASE_MARGIN, "leverage": _leverage(),
            "schedule": {"checks": len(sched), "on_passes": sum(1 for s in sched if s[2]),
                         "off_every_s": _off_every_s(), "raw": bool(cfg.get("raw"))},
            "candidates": {k: v for k, v in cinfo.items() if k != "sql"},
            "lists": {**linfo, "with_list": len(listed), "without": dict(no_list),
                      "ever_pass": sum(1 for r in listed if r.get("passes")),
                      "costs_fetched": sum(1 for r in listed
                                           if r.get("costs") == "fetched once"),
                      "first_ms": cov["pc_first"], "last_ms": cov["last"],
                      "end_min_ms": cov["end_min"], "end_max_ms": cov["end_max"]},
            "full_from_ms": _midnight(full_from) if full_from else None,
            "days": days, "events": events, "slots": slots,
            "practice_trades": [{**t, "id": rec_rows["ids"].get(t["slot"], ""),
                                 "off_now": t["slot"] in off_now} for t in p_trades],
            "reconcile_rows": rec_rows["rows"], "summary": summary, "notes": notes}


def _why_short(why: str) -> str:
    """A reason with its numbers and names taken out, to count by."""
    import re

    w = str(why or "")
    if "missing minute" in w:
        return "its 1-minute candles have a gap on this PC"
    if w.startswith("no ") and "candles" in w:
        return "no 1-minute candles for the coin on this PC"
    if w.startswith("could not be rebuilt"):
        return w.split(":", 2)[1].strip() if ":" in w else w
    return re.sub(r"\d[\d.,]*", "N", w)[:90]


def _leverage() -> int:
    from tradingagents import auto_trader as at

    return int(at.LEVERAGE)


def _off_every_s() -> int:
    from tradingagents import strategy_watcher as sw

    return int(sw.OFF_EVERY_S)


# --------------------------------------------------------------- data limits
def _coverage(lists: dict, window_ms: int) -> dict:
    """Where each list's knowledge begins and why: CUT at its Backtest v2
    row's own window, or this PC's first candle, or a coin whose candles
    start later (its own history — not a limit of this PC's data)."""
    recs = [r for r in lists.values() if r.get("first_ms")]
    firsts = [r["coin_first_ms"] for r in recs if r.get("coin_first_ms")]
    pc_first = min(firsts) if firsts else None
    limits = []          # (limit_ms or None, cause)
    for r in recs:
        cf = r.get("coin_first_ms") or r["first_ms"]
        if r["first_ms"] > cf + int(r["bar_ms"]) + MIN_MS:
            limits.append((int(r["first_ms"]), "row_window"))
        elif pc_first is not None and cf > pc_first + DAY_MS:
            limits.append((None, "young_coin"))
        else:
            limits.append((int(r["first_ms"]), "pc_candles"))
    ends = [int(r["end_ms"]) for r in recs if r.get("end_ms")]

    def full_from(day_keys, wms):
        for k in day_keys:
            d0 = _midnight(k)
            if all(lim is None or lim <= d0 - wms for lim, _c in limits):
                return k
        return None
    return {"limits": limits, "pc_first": pc_first, "full_from": full_from,
            "last": max(ends) if ends else None,
            "end_min": min(ends) if ends else None, "end_max": max(ends) if ends else None,
            "ends": sorted(ends),
            "cut": sorted(lim for lim, c in limits if c == "row_window"),
            "young": sum(1 for _l, c in limits if c == "young_coin")}


def _day_coverage(cov: dict, d0: int, window_ms: int) -> dict:
    """How many lists hold this day's whole window, and how many have already
    ended (their backtest stops before the day does)."""
    lim = [x for x, _c in cov["limits"]]
    short = sum(1 for x in lim if x is not None and x > d0 - window_ms)
    ended = bisect.bisect_left(cov["ends"], _next_midnight(wr.day_of(d0)))
    return {"lists_short": short, "lists_full": len(lim) - short,
            "lists_ended": ended, "judged_full": short == 0}


def _hindsight(days: list, cov: dict) -> str:
    """THE FIRST NOTE, because it changes how every total reads (Oct 03,
    2026, #6B08FF64 Sep 01 - Oct 02: the replay +6,947.20, the room's real
    practice -13.24). Which strategies may be replayed is decided by their
    STORED Backtest v2 rows, whose numbers cover each row's own last 30 days
    — so a day inside those 30 days picks only from strategies already known
    to have done well over them. The days the real room traded are the fair
    comparison, and that comparison is printed from this run's own rows."""
    starts = cov.get("cut") or []
    seen = [d for d in days if d.get("practice") is not None]
    fair = ""
    if seen:
        rp = round(sum(float(d["profit"]) for d in seen), 2)
        pp = round(sum(float(d["practice"]["profit"]) for d in seen), 2)
        fair = (f" On the {len(seen)} day(s) the room really traded "
                f"({_when(_midnight(seen[0]['day']))} to {_when(_midnight(seen[-1]['day']))}) "
                f"the replay made {rp:+.2f} and the "
                f"practice account {pp:+.2f}.")
    span = (f"{_when(min(starts))} to {_when(cov['end_max'])}" if starts and cov.get("end_max")
            else "each row's own last 30 days")
    return ("HINDSIGHT — read the totals with this: which strategies the replay could pick "
            f"was decided by their stored Backtest v2 results, measured over {span}. A day "
            "inside that span chooses only among strategies already known to have done well "
            "over it, so its profit reads far better than a room could have made on the day "
            "itself — most of all early in the range. The live cost check that refuses trades "
            "at night is not replayed either." + fair)


def _notes(room, cfg, cinfo, listed, no_list, cov, full_from, pr, cap, start_ms, end_ms,
           rec_tot, day_keys, window_ms) -> list:
    """The data limits, every one derived from what was measured (spec, "Data
    limits": printed on the screen, never hidden)."""
    w = int(cfg["window_days"])
    n = len(listed)
    out = []
    if cinfo.get("limit"):
        out.append(f"A TEST RUN: only the first {cinfo['limit']:,} candidate rows were read, "
                   f"so this is not the room's whole replay.")
    if cinfo.get("min_wr30") is not None:
        a = cinfo.get("audit") or {}
        out.append(f"NOMINATED BY A FLOOR: only rows whose own 30-day win rate is at least "
                   f"{float(cinfo['min_wr30']):g}% were replayed — the full rule is about 5 "
                   f"million rows for a 15-day room."
                   + (f" A random {a['sampled']:,} of the rows under the floor were replayed "
                      f"too: {a['would_pass']:,} of them would have been switched on at some "
                      f"check, so the floor misses about "
                      f"{100 * a['would_pass'] / a['sampled']:.1f}% of them."
                      if a.get("sampled") else " What it left out was not measured."))
    out.append(f"Candidates: {cinfo.get('searched', cinfo.get('count', 0)):,} Backtest v2 rows "
               f"could pass the line at "
               f"some moment — at least {cfg['min_trades']} trades and "
               f"{wins_floor(cfg)} wins in the row's last 30 days, TP {cfg.get('tp_rule')} SL, "
               f"stop {float(cfg.get('max_sl') or 0):g}% or tighter, cost under "
               f"{cost_block_pct():g}% of the target. A strategy that was strong only "
               f"before its row's 30 days cannot be nominated.")
    p = cinfo.get("room_picks") or {}
    if p.get("count"):
        out.append(f"The room's own switch-ons are always replayed: {p['count']:,} strategies "
                   f"its watcher switched on by the end of the range, {p.get('added', 0):,} of "
                   f"them outside the search above"
                   + (f"; {len(p['missing']):,} could not be found in this PC's Backtest v2 "
                      f"files ({', '.join('#' + m for m in p['missing'][:8])}"
                      f"{' …' if len(p['missing']) > 8 else ''}), so they cannot be replayed"
                      if p.get("missing") else "") + ".")
    if cov["pc_first"]:
        out.append(f"The trade lists are this PC's 1-minute candles, which begin "
                   f"{_when(cov['pc_first'])}; {n:,} candidates have a list.")
    if cov["cut"]:
        med = cov["cut"][len(cov["cut"]) // 2]
        out.append(f"{len(cov['cut']):,} of {n:,} lists are the Backtest v2 list exactly as "
                   f"clicking the id shows it, which holds only that row's own window — "
                   f"they start between {_when(cov['cut'][0])} and {_when(cov['cut'][-1])} "
                   f"(half by {_when(med)}). Before a list's start plus {w} days that "
                   f"strategy is judged on fewer than {w} days of trades.")
    if full_from:
        out.append(f"Every day from {_when(_midnight(full_from))} is judged on the room's "
                   f"whole {w}-day window.")
    elif day_keys:
        out.append(f"No day in this range is judged on the room's whole {w}-day window "
                   f"for every strategy; each day's row says how many were short.")
    if cov["young"]:
        out.append(f"{cov['young']:,} lists belong to coins whose 1-minute candles start "
                   f"later than {_when(cov['pc_first'])}: counted from their own first "
                   f"candle.")
    if cov["end_min"]:
        out.append(f"The backtest lists end where each row was last measured or where this "
                   f"PC's candles stop: {_when(cov['end_min'])} to {_when(cov['end_max'])}. "
                   f"Practice trades after a strategy's list ends are counted apart "
                   f"({rec_tot.get('after_backtest', 0):,} of them).")
    if no_list:
        top = "; ".join(f"{k} ({v:,})" for k, v in no_list.most_common(4))
        out.append(f"{sum(no_list.values()):,} candidates have no trade list on this PC and "
                   f"can never be switched on here: {top}.")
    out.append("The replay knows every trade the minute it closed. The live watcher "
               "judged on the daily update's numbers, hours old, plus the practice trades "
               "since each row's last candle.")
    out.append(f"Rows whose cost is {cost_block_pct():g}% of the target or more are left "
               f"out; a raw room's live watcher switches them on, and the runner then "
               f"refuses their trades at the cost check.")
    out.append(f"At most {cap} trade(s) open on one coin at once — the practice runner's "
               f"own limit; its rule that they all point the same way is not replayed.")
    if pr.get("start_ms"):
        out.append(f"The cost check at each live entry (that moment's spread) cannot be "
                   f"replayed for past days; only the refusals the room recorded since "
                   f"{_when(pr['start_ms'])} are matched.")
    out.append("Each daily update re-measures the rows, so a replay run tomorrow can "
               "start a list's window later than today's.")
    return out


# ---------------------------------------------------------------- reconcile
def _reconcile(room, cands, lists, sim, pr, start_ms, end_ms, now, traded, slots):
    """Every practice trade and every replay trade in the range, matched by
    strategy, coin and entry bar (the practice record keeps the SIGNAL
    candle; the backtest enters on the bar after it)."""
    cand_by_slot = {}
    for c in cands:
        with contextlib.suppress(ValueError):
            cand_by_slot[slot_key(c)] = c
    ids = _ids_of_slots(room)
    ids.update({s: c["id"] for s, c in cand_by_slot.items()})
    p_start = pr.get("start_ms")
    # replay trades by slot and entry, only where the room existed
    bt: dict = {}
    replay_on: dict = collections.defaultdict(list)
    for s in slots:
        c = {"coin": s["coin"], "tf": s["tf"], "signal": s["signal"], "th": s["th"],
             "sl": s["sl"], "tp": s["tp"]}
        try:
            key = slot_key(c)
        except ValueError:
            continue
        replay_on[key].append((s["on_ms"], s["off_ms"] if s["off_ms"] is not None
                               else float("inf")))
    for _exit_ms, _pnl, i, t in traded:
        s = slots[i]
        if p_start is None or int(t[0]) < p_start:
            continue
        try:
            key = slot_key(s)
        except ValueError:
            continue
        bt.setdefault(key, {})[int(t[0])] = (t, s)
    rows = []
    tot = collections.Counter()
    by_day: dict = collections.defaultdict(collections.Counter)
    used = set()
    for p in pr["trades"]:
        slot = p["slot"]
        key = slot.split("|", 1)[0]
        bar_ms = _bar_s_of_key(key) * 1000
        entry = int(p["entry_ms"] + bar_ms)
        twin = bt.get(slot, {}).get(entry)
        day = wr.day_of(p["exit_ms"])
        base = {"slot": slot, "id": ids.get(slot, ""), "day": day, "entry_ms": entry,
                "practice_exit_ms": p["exit_ms"], "practice_pnl": p["pnl"]}
        if twin is not None:
            t, _s = twin
            used.add((slot, entry))
            kind = "same" if (float(t[2]) > 0) == (float(p["pnl"]) > 0) else "different"
            tot[kind] += 1
            by_day[day][kind] += 1
            if kind == "different":
                rows.append({**base, "kind": kind, "reason": "",
                             "backtest_exit_ms": int(t[4]), "backtest_pnl": float(t[2])})
            continue
        c = cand_by_slot.get(slot)
        rec = lists.get(c["id"]) if c else None
        if c is None:
            reason = "not_candidate"
        elif rec and rec.get("end_ms") and entry >= int(rec["end_ms"]):
            reason = "after_backtest"
        elif not any(a <= entry < b for a, b in replay_on.get(slot, ())):
            reason = "replay_off"
        else:
            reason = "no_backtest_trade"
        kind = "after_backtest" if reason == "after_backtest" else "practice_only"
        tot[kind] += 1
        if kind == "practice_only":
            tot[f"practice_only:{reason}"] += 1
        by_day[day][kind] += 1
        rows.append({**base, "kind": kind, "reason": reason})
    refused, gone = pr["refused"], pr["refused_candles"]
    for slot, by_entry in bt.items():
        key = slot.split("|", 1)[0]
        bar_s = _bar_s_of_key(key)
        mine = refused.get(slot, [])
        ts_list = [x[0] for x in mine]
        stretch = pr["stretches"].get(slot) or []
        for entry, (t, _s) in sorted(by_entry.items()):
            if (slot, entry) in used:
                continue
            if not _on_at(stretch, entry / 1000):
                reason = "practice_off"
            elif entry // 1000 - bar_s in (gone.get(slot) or ()):
                reason = "gate_blocked"
            else:
                reason = rb._reason(mine, ts_list, entry / 1000, bar_s)
            day = wr.day_of(int(t[4]))
            tot["backtest_only"] += 1
            tot[f"backtest_only:{reason}"] += 1
            by_day[day]["backtest_only"] += 1
            rows.append({"slot": slot, "id": ids.get(slot, ""), "day": day, "entry_ms": entry,
                         "kind": "backtest_only", "reason": reason,
                         "backtest_exit_ms": int(t[4]), "backtest_pnl": float(t[2])})
    rows.sort(key=lambda r: (r["day"], r["entry_ms"], r["slot"]))
    return ({"rows": rows, "ids": ids}, {k: dict(v) for k, v in by_day.items()}, dict(tot))


REASONS = {
    "not_candidate": "not a replay candidate (its row cannot pass the line, costs half "
                     "the target or more, or is not in Backtest v2)",
    "replay_off": "the replay had this strategy switched off then",
    "no_backtest_trade": "switched on in both, but its backtest list took no trade on that "
                         "bar",
    "after_backtest": "after the strategy's backtest list ends",
    "practice_off": "the practice room had this strategy switched off then",
    **rb.REASONS,
    "gate_blocked_quiet": "fees too high for the target (cost check, which writes its "
                          "refusal once an hour)",
    "none": "no trade and no refusal recorded",
}


# ------------------------------------------------------------ saved results
def range_path(room: str, from_day: str, to_day: str, min_wr30: float | None = None) -> Path:
    """A floored run is a different answer and is kept apart from the exact one."""
    tail = ("" if min_wr30 is None else f"_wr{float(min_wr30):g}") + f"_{RESULT_TAG}"
    return room_dir(room) / "by-range" / f"{from_day}_{to_day}{tail}.json"


def save(res: dict) -> Path:
    if (res.get("candidates") or {}).get("limit"):
        # A TEST RUN (--limit) is kept apart: saved where the screen reads it,
        # a part of the candidates would be served as the room's replay
        p = room_dir(res["room"]) / "test-runs" / f"{res['from_day']}_{res['to_day']}.json"
        _write_json(p, res)
        return p
    p = range_path(res["room"], res["from_day"], res["to_day"],
                   (res.get("candidates") or {}).get("min_wr30"))
    _write_json(p, res)
    _write_json(room_dir(res["room"]) / "latest.json",
                {"from_day": res["from_day"], "to_day": res["to_day"],
                 "path": str(p), "computed_at": res["computed_at"],
                 "summary": res["summary"]})
    return p


_LOADED: dict = {}


def load(room: str, from_day: str, to_day: str, min_wr30: float | None = None) -> dict | None:
    """A saved result, read again only when its file changes."""
    p = range_path(room, from_day, to_day, min_wr30)
    try:
        st = p.stat()
    except OSError:
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _LOADED.get(str(p))
    if hit and hit[0] == stamp:
        return hit[1]
    got = _read_json(p)
    if not isinstance(got, dict):
        return None
    _LOADED.clear()                  # one result in memory at a time
    _LOADED[str(p)] = (stamp, got)
    return got


# ------------------------------------------------------------ the run itself
def _run_file() -> Path:
    return _home() / "run.json"


def _lock_file() -> Path:
    return _home() / "run.lock"


_LOCK: list = []


def lock_held() -> bool:
    """A FACT, not a pid: is a replay holding the run lock? (pids are reused,
    RCA-2026-09-12-B). One replay on the machine at a time — each sizes its
    workers to the memory that is free."""
    from tradingagents import portable

    try:
        fh = open(_lock_file(), "a+", encoding="utf-8")       # noqa: SIM115
    except OSError:
        return False
    try:
        portable.lock_exclusive(fh, blocking=False)
    except OSError:
        return True
    else:
        portable.unlock(fh)
        return False
    finally:
        fh.close()


def take_lock() -> bool:
    from tradingagents import portable

    _lock_file().parent.mkdir(parents=True, exist_ok=True)
    try:
        fh = open(_lock_file(), "a+", encoding="utf-8")       # noqa: SIM115
        portable.lock_exclusive(fh, blocking=False)
    except OSError:
        with contextlib.suppress(Exception):
            fh.close()
        return False
    _LOCK.append(fh)
    return True


def release_lock() -> None:
    from tradingagents import portable

    while _LOCK:
        fh = _LOCK.pop()
        with contextlib.suppress(Exception):
            portable.unlock(fh)
        with contextlib.suppress(Exception):
            fh.close()


def disk_job() -> str:
    """The long job that has the disk now (a candle download, a backtest, a
    collect), named with its progress — or ""."""
    with contextlib.suppress(Exception):                       # noqa: BLE001
        from tradingagents import db_jobs

        for kind in db_jobs._DISK_JOBS:
            st = db_jobs.status(kind)
            if st.get("running"):
                done, total = st.get("done"), st.get("total")
                return (f"{kind} ({int(done):,} of {int(total):,})" if done is not None
                        and total else kind)
    return ""


def status() -> dict:
    """What the replay is doing now. `running` is the LOCK, never the file:
    a file that says running while nothing holds the lock is a run that died."""
    from tradingagents import portable

    st = _read_json(_run_file())
    st = st if isinstance(st, dict) else {}
    alive = lock_held()
    if (st.get("running") and not alive and st.get("phase") == "starting"
            and time.time() - float(st.get("updated_at") or 0) < STARTING_S
            and (st.get("pid") is None or portable.pid_alive(st.get("pid")))):
        # spawned a moment ago: Python is still importing, the lock comes next
        return {**st, "running": True}
    if st.get("running") and not alive:
        st = {**st, "running": False,
              "error": st.get("error") or "the replay process stopped before it finished"}
    st["running"] = bool(alive and st.get("running", True))
    return st


def _progress_writer(room, from_day, to_day, started, min_wr30=None):
    last = {"t": 0.0}

    def write(phase, done=0, total=0):
        now = time.time()
        if now - last["t"] < 2 and phase == last.get("phase"):
            return
        last.update(t=now, phase=phase)
        _write_json(_run_file(), {"running": True, "pid": os.getpid(), "room": room,
                                  "from_day": from_day, "to_day": to_day,
                                  "min_wr30": min_wr30, "phase": phase,
                                  "done": int(done), "total": int(total),
                                  "started_at": started, "updated_at": now}, loud=False)
    return write


def start_run(room: str, from_day: str, to_day: str, min_wr30: float | None = None) -> dict:
    """Start measuring one range in its own process (the API's way in).
    Refuses — naming why — while another replay or a disk job is running,
    and never under a test run."""
    _check_room(room)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"started": False, "state": "not_measured", "why": "never under a test run"}
    st = status()
    if st.get("running"):
        return {"started": False, "state": "measuring", "why": "a replay is already running",
                "run": st}
    holder = disk_job()
    if holder:
        return {"started": False, "state": "waiting",
                "why": f"{holder} is using the disk; the replay starts on the next look "
                       f"after it finishes"}
    log = room_dir(room) / "run.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    from tradingagents import portable

    # BEFORE the spawn: a child that fails at once overwrites this, and is
    # never overwritten by it
    _write_json(_run_file(), {"running": True, "pid": None, "room": room,
                              "from_day": from_day, "to_day": to_day, "min_wr30": min_wr30,
                              "phase": "starting",
                              "done": 0, "total": 0, "started_at": time.time(),
                              "updated_at": time.time()}, loud=False)
    try:
        fh = open(log, "a", encoding="utf-8", errors="replace")  # noqa: SIM115
    except OSError as exc:
        _write_json(_run_file(), {"running": False, "room": room, "from_day": from_day,
                                  "to_day": to_day, "min_wr30": min_wr30,
                                  "error": f"could not open its log: {exc}"}, loud=False)
        return {"started": False, "state": "failed", "why": f"could not open its log: {exc}"}
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "tradingagents.room_replay", room,
             "--from", str(from_day), "--to", str(to_day)]
            + ([] if min_wr30 is None else ["--min-winrate30", f"{float(min_wr30):g}",
                                            "--audit", "400"]),
            stdout=fh, stderr=subprocess.STDOUT, cwd=str(Path(__file__).resolve().parents[1]),
            **portable.DETACHED,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"})
    except OSError as exc:
        # NAMED, never a "starting" that lasts two minutes and then reads as died
        why = f"could not start: {type(exc).__name__}: {exc}"
        _write_json(_run_file(), {"running": False, "room": room, "from_day": from_day,
                                  "to_day": to_day, "min_wr30": min_wr30, "error": why},
                    loud=False)
        return {"started": False, "state": "failed", "why": why}
    finally:
        fh.close()           # the child holds its own handle to the log
    return {"started": True, "state": "measuring", "pid": proc.pid}


# ------------------------------------------------------------ the API's page
def _page(rows: list, page: int, per: int) -> dict:
    per = max(1, min(int(per or PER_PAGE), 100))
    pages = max(1, -(-len(rows) // per))
    page = min(max(1, int(page or 1)), pages)
    return {"rows": rows[(page - 1) * per: page * per], "page": page, "pages": pages,
            "per": per, "total": len(rows)}


def view(room: str, from_s: float, to_s: float, *, what: str = "days", page: int = 1,
         per: int = PER_PAGE, day: str = "", rid: str = "", start: bool = True,
         refresh: bool = False, min_wr30: float | None = None) -> dict:
    """One page of a saved replay — or, when that range is not measured yet,
    WHY there is no table (measuring, waiting for the disk, failed), never an
    empty table that reads as "no trades"."""
    _check_room(room)
    if what not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}")
    if day:
        dt.date.fromisoformat(day)                    # a bad key is a 400
    from_day = wr.day_of(int(from_s * 1000))
    to_day = wr.day_of(int(to_s * 1000))
    if to_day < from_day:
        raise ValueError("the range ends before it starts")
    res = load(room, from_day, to_day, min_wr30)
    run = status()
    mine = (run.get("room") == room and run.get("from_day") == from_day
            and run.get("to_day") == to_day and run.get("min_wr30") == min_wr30)
    if res is None:
        if run.get("running"):
            return {"state": "measuring" if mine else "busy", "room": room,
                    "from_day": from_day, "to_day": to_day, "run": run,
                    "why": (f"being measured: {run.get('phase', '')} "
                            f"{run.get('done', 0):,} of {run.get('total', 0):,}" if mine else
                            f"another replay is being measured ({run.get('room')} "
                            f"{run.get('from_day')} to {run.get('to_day')}); this range "
                            f"starts after it")}
        if mine and run.get("error") and not refresh:
            # shown, not retried on every look: `refresh` asks again
            return {"state": "failed", "room": room, "from_day": from_day,
                    "to_day": to_day, "why": f"the last run failed: {run['error']}",
                    "run": run}
        got = start_run(room, from_day, to_day, min_wr30) if start else {
            "state": "not_measured", "why": "not measured yet"}
        return {"room": room, "from_day": from_day, "to_day": to_day, "run": run, **got,
                "why": got.get("why") or "being measured — the table appears when it is done"}
    head = {k: res[k] for k in ("room", "name", "computed_at", "start_ms", "end_ms", "cfg",
                                "coin_cap", "margin", "leverage", "schedule", "candidates",
                                "lists", "full_from_ms", "summary", "notes", "from_day",
                                "to_day")}
    head["state"] = "ready"
    head["reasons"] = REASONS
    if refresh and not run.get("running"):
        # measured again on request (a range that includes today grows); the
        # saved table keeps answering until the new one replaces it
        head["refresh"] = start_run(room, from_day, to_day, min_wr30)
        run = status()
    if run.get("running"):
        head["run"] = run
    if what == "days":
        rows = res["days"]
    elif what == "events":
        rows = [e for e in res["events"] if not day or e["day"] == day]
        rows = [e for e in rows if not rid or e["id"] == rid]
    elif what == "slots":
        rows = [{k: v for k, v in s.items() if k != "trades"} for s in res["slots"]
                if not rid or s["id"] == rid]
    elif what == "trades":
        rows = []
        for s in res["slots"]:
            if rid and s["id"] != rid:
                continue
            for t in s["trades"]:
                if day and wr.day_of(t[1]) != day:
                    continue
                rows.append({"id": s["id"], "coin": s["coin"], "tf": s["tf"],
                             "signal": s["signal"], "tp": s["tp"], "sl": s["sl"],
                             "entry_ms": t[0], "exit_ms": t[1], "pnl": t[2], "why": t[3],
                             "side": t[4], "slot_n": s["n"]})
        rows.sort(key=lambda r: (r["exit_ms"], r["id"]))
    elif what == "practice":
        rows = [t for t in res["practice_trades"]
                if (not day or wr.day_of(t["exit_ms"]) == day) and (not rid or t["id"] == rid)]
    else:
        rows = [r for r in res["reconcile_rows"]
                if (not day or r["day"] == day) and (not rid or r["id"] == rid)]
    return {**head, "view": what, "day": day, "id": rid, **_page(rows, page, per)}


# ------------------------------------------------------------------ the CLI
def _print_summary(res: dict) -> None:
    s = res["summary"]
    b, p = s["backtest"], s["practice"]
    print(f"[room_replay] {res['name']} {_when(res['start_ms'])} to {_when(res['end_ms'])}: "
          f"{res['candidates'].get('count', 0):,} candidates, "
          f"{res['lists'].get('with_list', 0):,} with a trade list "
          f"({res['lists'].get('cached', 0):,} cached, {res['lists'].get('rebuilt', 0):,} "
          f"rebuilt on {res['lists'].get('workers', 0)} worker(s))", flush=True)
    print(f"[room_replay] replay: {b['switched_on']:,} switched on, {b['switched_off']:,} off, "
          f"{b['closed']:,} trades closed ({b['wins']:,} won / {b['losses']:,} lost), "
          f"{b['profit']:+.2f} at ${res['margin']:g} x {res['leverage']}x, worst losing run "
          f"{b['worst_streak']:+.2f} over {b['worst_streak_trades']} trades", flush=True)
    print(f"[room_replay] practice: {p['closed']:,} trades closed ({p['wins']:,} won / "
          f"{p['losses']:,} lost), {p['profit']:+.2f}; reconcile {s['reconcile']}", flush=True)
    for n in res["notes"]:
        print(f"[room_replay] note: {n}", flush=True)


def main(argv: list | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m tradingagents.room_replay",
                                 description="Backtest a room: replay its own rules day by day")
    ap.add_argument("room")
    ap.add_argument("--from", dest="from_day", required=True, help="YYYY-MM-DD (local)")
    ap.add_argument("--to", dest="to_day", required=True, help="YYYY-MM-DD (local)")
    ap.add_argument("--limit", type=int, default=0, help="read only the first N candidates")
    ap.add_argument("--workers", type=int, default=None, help="default: sized to free memory")
    ap.add_argument("--min-winrate30", type=float, default=None,
                    help="nominate only rows whose own 30-day win rate is at least this")
    ap.add_argument("--audit", type=int, default=0,
                    help="with a floor: replay this many random rows under it too")
    ap.add_argument("--force", action="store_true",
                    help=f"run even past {MAX_LISTS:,} trade lists")
    ap.add_argument("--while-busy", action="store_true",
                    help="run even while a candle download or backtest has the disk")
    a = ap.parse_args(argv)
    dt.date.fromisoformat(a.from_day)
    dt.date.fromisoformat(a.to_day)
    if not take_lock():
        print("[room_replay] another replay is running — one at a time", flush=True)
        return 2
    started = time.time()
    write = _progress_writer(a.room, a.from_day, a.to_day, started, a.min_winrate30)
    try:
        holder = disk_job()
        if holder and not a.while_busy:
            print(f"[room_replay] refused: {holder} is using the disk", flush=True)
            _write_json(_run_file(), {"running": False, "room": a.room, "min_wr30": a.min_winrate30,
                                      "from_day": a.from_day, "to_day": a.to_day,
                                      "error": f"{holder} was using the disk"}, loud=False)
            return 3
        print(f"[room_replay] up (pid {os.getpid()}): {a.room} {a.from_day} to {a.to_day}"
              + (f", first {a.limit} candidates" if a.limit else "")
              + (f" — while {holder} runs" if holder else ""), flush=True)
        write("starting")
        res = replay(a.room, a.from_day, a.to_day, workers=a.workers, limit=a.limit,
                     progress=write, min_wr30=a.min_winrate30, force=a.force,
                     audit=a.audit)
        path = save(res)
        _print_summary(res)
        print(f"[room_replay] saved {path} in {time.time() - started:.0f} s", flush=True)
        _write_json(_run_file(), {"running": False, "room": a.room, "min_wr30": a.min_winrate30, "from_day": a.from_day,
                                  "to_day": a.to_day, "finished_at": time.time(),
                                  "started_at": started, "path": str(path)}, loud=False)
        return 0
    except TooMany as exc:
        # REFUSED, not crashed: the size is the answer, said once, no traceback
        why = f"refused: {exc}"
        print(f"[room_replay] {why}", flush=True)
        _write_json(_run_file(), {"running": False, "room": a.room, "min_wr30": a.min_winrate30,
                                  "from_day": a.from_day, "to_day": a.to_day, "error": why,
                                  "started_at": started, "finished_at": time.time()},
                    loud=False)
        return 4
    except Exception as exc:                                   # noqa: BLE001
        why = f"{type(exc).__name__}: {str(exc)[:300]}"
        print(f"[room_replay] FAILED: {why}", flush=True)
        _write_json(_run_file(), {"running": False, "room": a.room, "min_wr30": a.min_winrate30, "from_day": a.from_day,
                                  "to_day": a.to_day, "error": why, "started_at": started,
                                  "finished_at": time.time()}, loud=False)
        raise
    finally:
        release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
