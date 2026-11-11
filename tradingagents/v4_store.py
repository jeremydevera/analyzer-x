"""BACKTEST V4 - the Claude skills' strategies, stored (operator, Nov 10, 2026: "can you do backtest
v4 i want the strategies stored there, then follow the format like backtest v2 where i can see
winrate and filter by day etc").

What it holds: every strategy the skills measured on every coin x timeframe (`acs`' skill runs:
`skilltaall.json` = the technical-analysis and backtesting-frameworks strategies, all 42 a
coin-timeframe; `skill.json` = the backtesting-trading-strategies skill's own, best 3), each with ALL of
its trades, in ONE SQLite file of its own (`stores.V4.rows_db`). Nothing here measures anything: the
GitHub runs did, and `build()` files their finished lists.

Why a database and not the all-coins page's embedded data: the screen has to FILTER WHERE THE DATA IS
(CLAUDE.md kit item G) - 242,313 rows and 6.9 million trades, so "last N days" can re-add every row
over that slice in the query, never over a page of rows the server already cut.

Tables:
* `strat`  - one row per strategy: id, coin, tf, strategy, TP, SL, its whole-history figures
             (trades, wins, losses, profit, worst losing run, worst dip, green months) and the figures
             of its older 70% (where it was chosen) and unseen newest 30% (where it was judged).
* `trade`  - every trade, clustered by (sid, exit second); `trade_ex` is the covering index a window
             ("last N days") scans.
* `meta`   - what was filed and when.

A trade's dollars are the skills' own: $100 of coin (the app's $5 at 20x) after 0.075% fee each way and
the coin's usual gap, a stop and a target settled minute by minute where the daily run holds the minutes
(`meta.exits` says how far; skill_bt.py), else on the candle's close. A trade that made
$0 or less is a loss. The window clock is the trade's CLOSE ("last 30 days" = closed in them); the unseen
clock is the trade's OPEN (a trade that opened after the row's split: RCA-2026-11-05-F).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from tradingagents import stores

MEASURED_MARGIN = 5.0            # the dollars in the files are $5 margin x 20x = $100 a trade
LEVERAGE = 20
DAY_S = 86_400
WHYS = ("SL", "TP", "SIGNAL", "END", "OTHER")
SOURCES = (("skilltaall.json", "technical-analysis / backtesting-frameworks"),
           ("skill.json", "backtesting-trading-strategies"))
# The daily re-measure (v4_daily): ONE collected file holding the pinned universe. Its strategies carry
# their own `split_ms` (the bt skill's picks keep the Nov 05, 2026 split they were chosen at) and never an
# `older_lost` flag - the daily run chooses nothing.
DAILY_SOURCES = (("skilldaily.json", "daily re-measure"),)
FIRST_COPY = "rows-2026-11-10.db"     # the Nov 10, 2026 store, kept once before the first daily refresh
FIRST_FORECAST = "forecast-2026-11-10-static.json.gz"   # ... and its Forecast v4, the rooms' rule sets
SORTS = {                         # the sort key -> its SQL (window figures are `a.*` when a window is on)
    "profit": "profit", "winrate": "win_rate", "trades": "trades", "wins": "wins", "losses": "losses",
    "tp": "tp", "sl": "sl", "worst_run": "worst_run", "dip": "dip", "green": "green",
    "id": "id", "coin": "coin", "tf": "tf", "strategy": "strategy", "days": "days",
}
SORT_TEXT = {"id", "coin", "tf", "strategy"}
PAGE_MAX = 200
STRAT_COLS = 35                  # the columns of `strat`, in SCHEMA order
SCHEMA = """
CREATE TABLE strat (
  sid INTEGER PRIMARY KEY, id TEXT NOT NULL, coin TEXT NOT NULL, tf TEXT NOT NULL,
  strategy TEXT NOT NULL, label TEXT NOT NULL, skill TEXT NOT NULL, params TEXT NOT NULL,
  tp REAL, sl REAL NOT NULL,
  trades INTEGER NOT NULL, wins INTEGER NOT NULL, losses INTEGER NOT NULL, win_rate REAL NOT NULL,
  profit REAL NOT NULL, worst_run REAL NOT NULL, worst_run_n INTEGER NOT NULL, dip REAL NOT NULL,
  green INTEGER NOT NULL, months_n INTEGER NOT NULL, months TEXT NOT NULL,
  older_trades INTEGER NOT NULL, older_wins INTEGER NOT NULL, older_profit REAL NOT NULL,
  newer_trades INTEGER NOT NULL, newer_wins INTEGER NOT NULL, newer_profit REAL NOT NULL,
  older_lost INTEGER NOT NULL, start_s INTEGER NOT NULL, split_s INTEGER NOT NULL,
  end_s INTEGER NOT NULL, days REAL NOT NULL, bars INTEGER NOT NULL, fee REAL, slip REAL
);
CREATE TABLE trade (
  sid INTEGER NOT NULL, ex INTEGER NOT NULL, en INTEGER NOT NULL, side INTEGER NOT NULL,
  why INTEGER NOT NULL, pnl REAL NOT NULL, at INTEGER,
  PRIMARY KEY (sid, ex, en)
) WITHOUT ROWID;
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""
INDEXES = (
    "CREATE INDEX trade_ex ON trade(ex, sid, pnl)",
    "CREATE INDEX trade_en ON trade(en, sid, pnl)",
    "CREATE INDEX strat_id ON strat(id)",
    "CREATE INDEX strat_cov ON strat(coin, tf)",
    "CREATE INDEX strat_profit ON strat(profit)",
    "CREATE INDEX strat_winrate ON strat(win_rate)",
)


def db_path() -> Path:
    return Path(stores.V4.rows_db)


def month_key(ts_s: int) -> str:
    return datetime.fromtimestamp(ts_s, tz=timezone.utc).strftime("%Y-%m")


def why_code(text: str) -> int:
    t = str(text).upper()
    for i, w in enumerate(WHYS[:-1]):
        if t.startswith(w):
            return i
    return len(WHYS) - 1


def figures(pnls: list[float], exits_s: list[int]) -> dict:
    """Everything a row prints about ONE trade list, in closing order: counts, profit, the worst
    unbroken run of losses (its dollars and its length), the worst dip of the running total from its
    own peak (the peak starts at zero), and the profit of each calendar month the trades CLOSED in."""
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    run = run_n = worst = worst_n = 0
    total = peak = dip = 0.0
    months: dict[str, float] = {}
    for p, ex in zip(pnls, exits_s):
        total += p
        peak = max(peak, total)
        dip = max(dip, peak - total)
        if p <= 0:
            run += p
            run_n += 1
            if run < worst:
                worst, worst_n = run, run_n
        else:
            run = run_n = 0
        k = month_key(ex)
        months[k] = months.get(k, 0.0) + p
    return {"trades": n, "wins": wins, "losses": n - wins, "profit": total,
            "win_rate": (100.0 * wins / n) if n else 0.0,
            "worst_run": worst, "worst_run_n": worst_n, "dip": dip, "months": months,
            "green": sum(1 for v in months.values() if v > 0)}


def row_id(coin: str, tf: str, c: dict) -> str:
    """The id the all-coins page printed for this strategy (`acs_page.skill_rows`): hashed from the
    combination, never from a position, and with no exchange in it."""
    from tradingagents import backtest_report as br

    tg = c.get("target")
    return br.row_code(coin, tf, c["strategy"], 0, c["stop"] * 100, (tg or 0) * 100, "flat",
                       plan=c["label"], res="skill")


def skill_of(strategy: str) -> str:
    from tradingagents import skill_ta

    return skill_ta.SKILL_OF.get(strategy, "backtesting-trading-strategies")


def _rows_of(path: Path):
    """(line, pick) of every strategy in one collected run file."""
    d = json.loads(path.read_text(encoding="utf-8"))
    for key in sorted(d["lines"]):
        x = d["lines"][key]
        for c in x["picks"]:
            yield x, c
    del d


def build(folder: str | os.PathLike | None = None, *, target: str | os.PathLike | None = None,
          sources=SOURCES, log=print) -> dict:
    """File every skill strategy and every trade into a NEW database, then swap it in whole - the
    screen never reads a half-built file. `folder` = where the collected run files are (default: the
    acs store); `target` = the database to write (default: V4's). Returns the meta."""
    src = Path(folder) if folder else Path(stores.V1.home) / "acs"
    out = Path(target) if target else db_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".building")
    for p in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
        if p.exists():
            p.unlink()
    con = sqlite3.connect(tmp)
    con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + SCHEMA)
    seen: set[str] = set()
    sid = dups = 0
    per_source: dict[str, int] = {}
    ends = []
    exit_counts = {"minute": 0, "candle": 0, "unclear": 0}   # how the daily run settled stops and targets
    seen_lines: set = set()
    t0 = time.time()
    for name, who in sources:
        path = src / name
        if not path.exists():
            log(f"v4: {name} is not there, skipped")
            continue
        n = 0
        for x, c in _rows_of(path):
            if x.get("exits") and (name, x["coin"], x["tf"]) not in seen_lines:      # one count a line, not a strategy
                seen_lines.add((name, x["coin"], x["tf"]))
                for k in ("minute", "candle", "unclear"):
                    exit_counts[k] += int(x["exits"].get(k) or 0)
                exit_counts["from_s"] = max(exit_counts.get("from_s", 0), int(x["exits"].get("from_ms") or 0) // 1000)
            rid = row_id(x["coin"], x["tf"], c)
            if rid in seen:                      # the same strategy in two files: the first one stays
                dups += 1
                continue
            seen.add(rid)
            sid += 1
            tr = sorted(c["trades"], key=lambda t: (t[1], t[0]))
            exits = [int(t[1]) // 1000 for t in tr]
            f = figures([float(t[4]) for t in tr], exits)
            split_s = int(c.get("split_ms", x["split_ms"])) // 1000
            old = [t for t in tr if int(t[0]) // 1000 < split_s]
            new = [t for t in tr if int(t[0]) // 1000 >= split_s]
            tg = c.get("target")
            con.execute(
                "INSERT INTO strat VALUES (" + ",".join("?" * STRAT_COLS) + ")",
                (sid, rid, x["coin"], x["tf"], c["strategy"], c["label"], skill_of(c["strategy"]),
                 json.dumps(c["params"], sort_keys=True), round(tg * 100, 6) if tg else None,
                 round(c["stop"] * 100, 6), f["trades"], f["wins"], f["losses"], f["win_rate"],
                 round(f["profit"], 4), round(f["worst_run"], 4), f["worst_run_n"], round(f["dip"], 4),
                 f["green"], len(f["months"]), json.dumps({k: round(v, 4) for k, v in sorted(f["months"].items())}),
                 len(old), sum(1 for t in old if float(t[4]) > 0), round(sum(float(t[4]) for t in old), 4),
                 len(new), sum(1 for t in new if float(t[4]) > 0), round(sum(float(t[4]) for t in new), 4),
                 1 if c.get("older_lost", False) else 0, int(x["start_ms"]) // 1000, split_s, int(x["end_ms"]) // 1000,
                 (x["end_ms"] - x["start_ms"]) / 86_400_000, int(x["bars"]), x.get("fee"), x.get("slip")))
            if tr:
                # `at` (a sixth item, Nov 11, 2026): the minute a trade the minutes settled ended in
                con.executemany("INSERT OR IGNORE INTO trade VALUES (?,?,?,?,?,?,?)",
                                [(sid, int(t[1]) // 1000, int(t[0]) // 1000, int(t[2]), why_code(t[3]),
                                  float(t[4]), int(t[5]) // 1000 if len(t) > 5 and t[5] is not None else None)
                                 for t in tr])
            ends.append(int(x["end_ms"]) // 1000)
            n += 1
            if sid % 20_000 == 0:
                log(f"v4: {sid:,} strategies filed, {time.time() - t0:.0f}s")
        per_source[who] = n
        con.commit()
    if not sid:
        con.close()
        tmp.unlink()
        raise RuntimeError(f"v4: nothing was filed - none of {[n for n, _ in sources]} is in {src}")
    log("v4: building the indexes")
    for ddl in INDEXES:
        con.execute(ddl)
    meta = {"built_s": int(time.time()), "strategies": sid, "duplicates_left_out": dups,
            "sources": per_source, "data_end_s": max(ends) if ends else 0,
            "trades": con.execute("SELECT COUNT(*) FROM trade").fetchone()[0],
            "measured_margin": MEASURED_MARGIN, "leverage": LEVERAGE}
    if exit_counts["minute"] or exit_counts["candle"]:
        # stops and targets settled minute by minute (Nov 11, 2026): the page says how far, from data
        meta["exits"] = exit_counts
    con.executemany("INSERT INTO meta VALUES (?,?)", [(k, json.dumps(v)) for k, v in meta.items()])
    con.commit()
    bad = con.execute("PRAGMA integrity_check").fetchone()[0]
    con.close()
    if bad != "ok":
        raise RuntimeError(f"the new v4 database failed its own check: {bad}")
    for p in (Path(str(out) + "-wal"), Path(str(out) + "-shm")):
        if p.exists():
            p.unlink()
    os.replace(tmp, out)
    log(f"v4: {sid:,} strategies, {meta['trades']:,} trades, {time.time() - t0:.0f}s")
    return meta


def keep_first_copy(db: Path | str | None = None) -> Path | None:
    """Copy the store as it stands (the Nov 10, 2026 measurement) to `rows-2026-11-10.db` beside it, ONCE.
    Returns the copy's path, or None when that file already exists (or there is no store to copy): a
    daily refresh REPLACES the store, so this is what keeps the numbers the three rooms were chosen on.
    The store's `forecast.json` beside it is kept too, once (`keep_first_forecast`): the daily build
    replaces it as well, and the rooms were chosen from ITS rule sets."""
    import shutil

    src = Path(db) if db else db_path()
    keep_first_forecast(src.parent)
    dst = src.with_name(FIRST_COPY)
    if dst.exists() or not src.exists():
        return None
    tmp = dst.with_name(dst.name + ".copying")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)
    return dst


def keep_first_forecast(home: Path | str) -> Path | None:
    """`<home>/forecast.json` kept gzipped as `forecast-days/forecast-2026-11-10-static.json.gz`, ONCE
    (final review, Nov 11, 2026): never written over, and never a forecast already built from a daily
    store (its `store.sources` names the daily re-measure). Returns the copy, or None when there is
    nothing to keep."""
    import gzip

    home = Path(home)
    src, dst = home / "forecast.json", home / "forecast-days" / FIRST_FORECAST
    if dst.exists() or not src.exists():
        return None
    raw = src.read_bytes()
    try:
        sources = (json.loads(raw).get("store") or {}).get("sources") or {}
    except (ValueError, AttributeError):
        return None                     # not the forecast it should be: nothing is kept under that name
    if DAILY_SOURCES[0][1] in sources:
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f"{dst.name}.{os.getpid()}.tmp")
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        fh.write(raw)
    os.replace(tmp, dst)
    return dst


# --------------------------------------------------------------------------- reading

def _con() -> sqlite3.Connection | None:
    p = db_path()
    if not p.exists():
        return None
    con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def meta() -> dict | None:
    con = _con()
    if con is None:
        return None
    try:
        out = {k: json.loads(v) for k, v in con.execute("SELECT k, v FROM meta")}
        out["traded"] = con.execute("SELECT COUNT(*) FROM strat WHERE trades > 0").fetchone()[0]
        return out
    finally:
        con.close()


def facets() -> dict:
    con = _con()
    if con is None:
        return {"coins": [], "tfs": [], "strategies": [], "skills": []}
    try:
        col = lambda sql: [r[0] for r in con.execute(sql)]
        return {"coins": col("SELECT DISTINCT coin FROM strat ORDER BY coin"),
                "tfs": [t for t in ("15m", "30m", "1h", "4h", "1d")
                        if t in set(col("SELECT DISTINCT tf FROM strat"))],
                "strategies": col("SELECT DISTINCT strategy FROM strat ORDER BY strategy"),
                "skills": col("SELECT DISTINCT skill FROM strat ORDER BY skill")}
    finally:
        con.close()


def _where(q: dict, args: list) -> list[str]:
    """The conditions that only read a row's own columns (coin, timeframe, strategy, TP, SL ...)."""
    w: list[str] = []
    if q.get("coin"):
        coins = [c.strip() for c in str(q["coin"]).split(",") if c.strip()]
        w.append("s.coin IN (%s)" % ",".join("?" * len(coins)))
        args += coins
    if q.get("tf"):
        tfs = [c.strip() for c in str(q["tf"]).split(",") if c.strip()]
        w.append("s.tf IN (%s)" % ",".join("?" * len(tfs)))
        args += tfs
    if q.get("strategy"):
        w.append("s.strategy = ?")
        args.append(q["strategy"])
    if q.get("skill"):
        w.append("s.skill = ?")
        args.append(q["skill"])
    if q.get("older_ok"):
        w.append("s.older_lost = 0")
    # BOTH ARE CEILINGS, inclusive, in the percent the column prints (CLAUDE.md kit item G). A row
    # with no target cannot be "a target at or under 3%", so max_tp leaves it out.
    if q.get("max_tp"):
        w.append("s.tp IS NOT NULL AND s.tp <= ?")
        args.append(float(q["max_tp"]) + 1e-9)
    if q.get("max_sl"):
        w.append("s.sl <= ?")
        args.append(float(q["max_sl"]) + 1e-9)
    if q.get("tp_over_sl"):
        w.append("s.tp IS NOT NULL AND s.tp > s.sl")
    if q.get("min_green"):
        w.append("s.green >= ?")
        args.append(int(q["min_green"]))
    if q.get("max_dip"):
        w.append("s.dip <= ?")
        args.append(float(q["max_dip"]) / (float(q.get("base_margin") or MEASURED_MARGIN) / MEASURED_MARGIN))
    return w


def window_bounds(days: int, data_end_s: int) -> tuple[int, int]:
    return data_end_s - int(days) * DAY_S, data_end_s


def query(q: dict) -> dict:
    """The list the screen shows. `q` keys (all optional): coin, tf, strategy, skill, older_ok,
    min_trades, min_winrate (percent), min_profit (dollars at `base_margin`), min_green (a count),
    max_dip (dollars), max_tp / max_sl (percent ceilings), tp_over_sl, profitable, days / months (the
    window: every row re-added over the trades that CLOSED in it), unseen (only trades that opened after
    each row's split), row_id (overrides every other filter), sort, desc, limit, offset, base_margin."""
    con = _con()
    if con is None:
        return {"rows": [], "total": 0, "ready": False,
                "why": "Backtest v4 has not been filed yet: python -m tradingagents.v4_store build"}
    try:
        return _query(con, q)
    finally:
        con.close()


def _query(con: sqlite3.Connection, q: dict) -> dict:
    mt = {k: json.loads(v) for k, v in con.execute("SELECT k, v FROM meta")}
    end_s = int(mt.get("data_end_s") or 0)
    base = float(q.get("base_margin") or MEASURED_MARGIN)
    if not (0 < base <= 1_000_000):
        base = MEASURED_MARGIN
    scale = base / MEASURED_MARGIN
    days = int(q.get("days") or 0)
    if not days and q.get("months"):
        days = int(round(float(q["months"]) * 30.4375))
    unseen = bool(q.get("unseen"))
    windowed = bool(days) or unseen
    limit = max(1, min(int(q.get("limit") or 50), PAGE_MAX))
    offset = max(0, int(q.get("offset") or 0))
    desc = True if q.get("desc") is None else bool(q.get("desc"))
    sort = q.get("sort") if q.get("sort") in SORTS else "profit"
    notes: list[str] = []

    rid = str(q.get("row_id") or "").strip().lstrip("#").upper()
    args: list = []
    conds = [] if rid else _where({**q, "base_margin": base}, args)
    if rid:
        conds, args = ["s.id = ?"], [rid]
    base_where = ("WHERE " + " AND ".join(conds)) if conds else ""

    # the figures of each row: stored whole-history ones, or re-added over the window / unseen days
    if windowed:
        tcond, targs = [], []
        if days:
            tcond.append("t.ex > ?")
            targs.append(end_s - days * DAY_S)
        if unseen:
            tcond.append("t.en >= s.split_s")
        agg = ("SELECT t.sid AS sid, COUNT(*) AS trades, SUM(t.pnl > 0) AS wins, SUM(t.pnl) AS profit "
               "FROM trade t JOIN strat s ON s.sid = t.sid " + base_where.replace("WHERE", "WHERE", 1)
               + (" AND " if conds else " WHERE ") + " AND ".join(tcond) + " GROUP BY t.sid")
        src_args = args + targs
        src = (f"strat s LEFT JOIN ({agg}) a ON a.sid = s.sid")
        fig = {"trades": "COALESCE(a.trades,0)", "wins": "COALESCE(a.wins,0)",
               "profit": "COALESCE(a.profit,0)"}
    else:
        src, src_args = "strat s", []
        fig = {"trades": "s.trades", "wins": "s.wins", "profit": "s.profit"}
    losses = f"({fig['trades']} - {fig['wins']})"
    rate = f"(CASE WHEN {fig['trades']} > 0 THEN 100.0 * {fig['wins']} / {fig['trades']} ELSE 0 END)"

    having: list[str] = []
    hargs: list = []
    if not rid:
        if q.get("min_trades"):
            having.append(f"{fig['trades']} >= ?")
            hargs.append(int(q["min_trades"]))
        if q.get("min_winrate"):
            having.append(f"{fig['trades']} > 0 AND {rate} >= ?")
            hargs.append(float(q["min_winrate"]) - 1e-9)
        if q.get("min_profit") not in (None, ""):
            having.append(f"{fig['profit']} >= ?")
            hargs.append(float(q["min_profit"]) / scale - 1e-9)
        if q.get("profitable"):
            having.append(f"{fig['profit']} > 0")
        if windowed:
            having.append(f"{fig['trades']} > 0")       # a row that did not trade in the window has no window
    # the row's own columns condition the list in BOTH modes: inside `agg` (so the join only reads their
    # trades) and again outside (so a row they remove never comes back as a row of zeros)
    wh = ([base_where.replace("WHERE ", "", 1)] if base_where else []) + having
    where_sql = ("WHERE " + " AND ".join(wh)) if wh else ""
    all_args = src_args + args + hargs

    col = {"profit": fig["profit"], "winrate": rate, "trades": fig["trades"], "wins": fig["wins"],
           "losses": losses}.get(sort, "s." + SORTS[sort])
    order = f"{col} {'DESC' if desc else 'ASC'}"
    if sort in ("tp",):
        order = f"s.tp IS NULL, {order}"       # a row with no target sorts last, either way
    sql_total = f"SELECT COUNT(*) FROM {src} {where_sql}"
    total = con.execute(sql_total, all_args).fetchone()[0]
    sql = (f"SELECT s.*, {fig['trades']} AS w_trades, {fig['wins']} AS w_wins, {losses} AS w_losses, "
           f"{rate} AS w_rate, {fig['profit']} AS w_profit FROM {src} {where_sql} "
           f"ORDER BY {order}, s.id LIMIT ? OFFSET ?")
    got = con.execute(sql, all_args + [limit, offset]).fetchall()

    rows = []
    for r in got:
        if windowed:
            ex_cond, ex_args = ["sid = ?"], [r["sid"]]
            if days:
                ex_cond.append("ex > ?")
                ex_args.append(end_s - days * DAY_S)
            if unseen:
                ex_cond.append("en >= ?")
                ex_args.append(r["split_s"])
            tr = con.execute("SELECT ex, pnl FROM trade WHERE " + " AND ".join(ex_cond) + " ORDER BY ex, en",
                             ex_args).fetchall()
            f = figures([x["pnl"] for x in tr], [x["ex"] for x in tr])
            worst_run, worst_n, dip, months = f["worst_run"], f["worst_run_n"], f["dip"], f["months"]
            green = f["green"]
        else:
            worst_run, worst_n, dip = r["worst_run"], r["worst_run_n"], r["dip"]
            months, green = json.loads(r["months"]), r["green"]
        rows.append({
            "id": r["id"], "coin": r["coin"], "tf": r["tf"], "strategy": r["strategy"], "label": r["label"],
            "skill": r["skill"], "params": json.loads(r["params"]), "tp": r["tp"], "sl": r["sl"],
            "leverage": LEVERAGE, "trades": r["w_trades"], "wins": r["w_wins"], "losses": r["w_losses"],
            "win_rate": r["w_rate"], "profit": round(r["w_profit"] * scale, 2),
            "worst_run": round(worst_run * scale, 2), "worst_run_n": worst_n, "dip": round(dip * scale, 2),
            "green": green, "months_n": len(months), "months": {k: round(v * scale, 2) for k, v in months.items()},
            "older_trades": r["older_trades"], "older_wins": r["older_wins"],
            "older_profit": round(r["older_profit"] * scale, 2), "newer_trades": r["newer_trades"],
            "newer_wins": r["newer_wins"], "newer_profit": round(r["newer_profit"] * scale, 2),
            "older_lost": bool(r["older_lost"]), "start_s": r["start_s"], "split_s": r["split_s"],
            "end_s": r["end_s"], "days_of_data": round(r["days"], 1), "total_trades": r["trades"],
            "total_profit": round(r["profit"] * scale, 2)})
    if windowed:
        notes.append("worst losing run, worst dip and green months are worked out over the same window "
                     "for the rows shown; the max-dip and min-green boxes read each row's whole history")
    if q.get("max_tp") and not rid:
        none = con.execute("SELECT COUNT(*) FROM strat WHERE tp IS NULL").fetchone()[0]
        notes.append(f"{none:,} strategies have no target (they exit on their own signal) and max TP leaves them out")
    out = {"ready": True, "rows": rows, "total": total, "offset": offset, "limit": limit,
           "base_margin": base, "leverage": LEVERAGE, "notional": round(base * LEVERAGE, 2),
           "measured": {"strategies": mt.get("strategies"), "trades": mt.get("trades"),
                        "built_s": mt.get("built_s"), "data_end_s": end_s, "sources": mt.get("sources"),
                        "exits": mt.get("exits")},
           "window": ({"days": days or None, "from_s": (end_s - days * DAY_S) if days else None, "to_s": end_s,
                       "unseen": unseen} if windowed else None),
           "sort": sort, "desc": desc, "notes": notes}
    return out


def trade_log(sid_or_id: str, *, base_margin: float = MEASURED_MARGIN, days: int = 0,
              unseen: bool = False) -> dict:
    """Every trade of one strategy, in closing order, in the dollars at `base_margin`, with the TOTAL
    PROFIT of exactly the trades listed. `days` / `unseen` are the row's own window, so the log opens
    on the same trades its row figure was worked out from."""
    con = _con()
    if con is None:
        return {"found": False, "log": [], "why": "Backtest v4 has not been filed yet"}
    try:
        s = con.execute("SELECT * FROM strat WHERE id = ?", (str(sid_or_id).strip().lstrip("#").upper(),)).fetchone()
        if s is None:
            return {"found": False, "log": [], "why": f"no v4 strategy has the id {sid_or_id}"}
        end_s = int(json.loads(con.execute("SELECT v FROM meta WHERE k='data_end_s'").fetchone()[0]))
        cond, args = ["sid = ?"], [s["sid"]]
        if days:
            cond.append("ex > ?")
            args.append(end_s - int(days) * DAY_S)
        if unseen:
            cond.append("en >= ?")
            args.append(s["split_s"])
        scale = float(base_margin or MEASURED_MARGIN) / MEASURED_MARGIN
        # a store built before Nov 11, 2026 has no `at` column: its trades were all settled by the close
        has_at = any(r[1] == "at" for r in con.execute("PRAGMA table_info(trade)"))
        tr = con.execute("SELECT en, ex, side, why, pnl" + (", at" if has_at else ", NULL AS at")
                         + " FROM trade WHERE " + " AND ".join(cond) + " ORDER BY ex, en", args).fetchall()
        log, run = [], 0.0
        for t in tr:
            run += t["pnl"] * scale
            log.append({"entry_s": t["en"], "exit_s": t["at"] if t["at"] is not None else t["ex"],
                        "by_minute": t["at"] is not None, "side": "long" if t["side"] > 0 else "short",
                        "why": WHYS[t["why"]], "pnl": round(t["pnl"] * scale, 2), "running": round(run, 2),
                        "unseen": t["en"] >= s["split_s"]})
        f = figures([t["pnl"] for t in tr], [t["ex"] for t in tr])
        return {"found": True, "id": s["id"], "coin": s["coin"], "tf": s["tf"], "label": s["label"],
                "skill": s["skill"], "tp": s["tp"], "sl": s["sl"], "split_s": s["split_s"],
                "start_s": s["start_s"], "end_s": s["end_s"], "base_margin": base_margin,
                "window": {"days": days or None, "unseen": unseen, "from_s": (end_s - int(days) * DAY_S) if days else None},
                "trades": f["trades"], "wins": f["wins"], "losses": f["losses"],
                "total_profit": round(f["profit"] * scale, 2), "win_rate": f["win_rate"],
                "worst_run": round(f["worst_run"] * scale, 2), "worst_run_n": f["worst_run_n"],
                "dip": round(f["dip"] * scale, 2),
                "months": {k: round(v * scale, 2) for k, v in sorted(f["months"].items())}, "log": log}
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    import sys

    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["build"] and "--daily" in args[1:]:
        # the daily refresh: keep the Nov 10 store once, file the pinned re-measure, work the forecast out.
        # Any failure exits non-zero with its reason printed (v4_daily reads the code and the output).
        try:
            from tradingagents import forecast_v4

            had = (db_path().parent / "forecast-days" / FIRST_FORECAST).exists()
            kept = keep_first_copy()
            if kept:
                print(f"v4: the Nov 10, 2026 store is kept as {kept}")
            if not had and (db_path().parent / "forecast-days" / FIRST_FORECAST).exists():
                print(f"v4: the Nov 10, 2026 forecast is kept as {db_path().parent / 'forecast-days' / FIRST_FORECAST}")
            print(json.dumps(build(sources=DAILY_SOURCES), indent=1))
            forecast_v4.build()
        except Exception as e:                      # noqa: BLE001 - the reason is the product
            print(f"v4 daily build FAILED: {type(e).__name__}: {e}")
            return 1
        return 0
    if args[:1] == ["build"]:
        meta_ = build()
        print(json.dumps(meta_, indent=1))
        # Forecast v4 is worked out from this store, so a new store means a new forecast
        from tradingagents import forecast_v4

        forecast_v4.build()
        return 0
    if args[:1] == ["status"]:
        print(json.dumps(meta(), indent=1))
        return 0
    print("usage: python -m tradingagents.v4_store build [--daily] | status")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
