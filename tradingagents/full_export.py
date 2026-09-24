"""THE FULL CSV: every matching row, re-checked over the window, however many.

The operator, Sep 25, 2026: *"when i download csv you are only downloading top
2000, if the result is bilion i want to see billion in csv"*.

A days window ("last 30 days") has to RE-MEASURE every row from the candles —
the store keeps profit per month, not trades — and the quick download does it
row by row in the order the table shows, ~0.1 s a row because neighbours in
that order are different coins (a candle file and a signal computation each).
So it stops at `rows_index.DAYS_CSV_MAX` (2,000).

This job does the same re-measure a COIN at a time — every matching row of one
pair in one `market_sweep.window_rows` call, so the candles and each signal
are computed once for all of that pair's rows — on every core but two.
Measured on Backtest v2, Sep 25, 2026 (win % >= 85 and TP >= SL):

    one coin at a time     14 ms a row on one core (5 coins, 899 rows)
    the quick download    ~100 ms a row
    the operator's filter  1,369,665 rows -> ~32 min on 10 cores

Then it writes the file through the SAME `api.strategies_csv_lines` the quick
download uses — same columns, same order, same window floors, same notes —
looking each row's window figures up instead of re-measuring them. A file that
could not be told apart from the screen's own rows is the whole point (kit
item F).
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import time
from pathlib import Path

W_COLS = ("restated", "w_trades", "w_wins", "w_losses", "w_winrate",
          "w_profit", "w_dd", "w_worst", "w_funding", "w_first", "w_last",
          "w_days", "w_straddle")
# the filters the table's own query takes (api.COUNT_FILTERS), the window and
# the order the table shows
FILTER_KEYS = ("coin", "tf", "signal", "profitable", "min_trades",
               "min_winrate", "max_tp", "max_sl", "min_tp", "min_sl",
               "tp_over_sl", "asset", "sizing", "row_id", "group",
               "measured_days")


def export_dir(store_name: str = "v1") -> Path:
    """The STORE's own folder (on G:, never the system drive — a full file
    can be gigabytes; CLAUDE.md: big files go where the store is). Named by
    store, never read off `market_sweep.HOME`: the job runs in the store's
    environment and the API in v1's, and both must find the same file."""
    from tradingagents import stores

    d = Path(stores.by_name(store_name).home) / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clean_spec(spec: dict) -> dict:
    """The filters, the window and the order — nothing else — with the empty
    ones dropped, so the same filter always names the same file."""
    out = {k: spec[k] for k in FILTER_KEYS if spec.get(k)}
    out["days"] = int(spec.get("days") or 0)
    out["sort"] = str(spec.get("sort") or "profit")
    if spec.get("desc") is not None:
        out["desc"] = bool(spec["desc"])
    return out


def key_of(spec: dict) -> str:
    return json.dumps(clean_spec(spec), sort_keys=True)


def _pair_where(filters: dict) -> tuple[str, list]:
    """The table's WHERE for these filters, plus `pair = ?` — one pair's
    matching rows, read through the pair index."""
    from tradingagents import rows_index as ri

    where, args = ri._where(
        filters.get("coin"), filters.get("tf"), filters.get("signal"),
        bool(filters.get("profitable")), int(filters.get("min_trades") or 0),
        float(filters.get("min_winrate") or 0), float(filters.get("max_tp") or 0),
        filters.get("sizing"), filters.get("row_id"), filters.get("group"),
        float(filters.get("max_sl") or 0), float(filters.get("min_tp") or 0),
        float(filters.get("min_sl") or 0), bool(filters.get("tp_over_sl")),
        filters.get("asset"),
        ri.measured_cut_ms(int(filters.get("measured_days") or 0)))
    where = where.strip()
    if where:
        return f" {where} AND pair = ?", list(args)
    return " WHERE pair = ?", []


def _retest_pair(job: tuple) -> tuple:
    """ONE COIN: its matching rows, re-measured over the window in one call.

    Top-level so a worker process can run it. Returns the pair, how many rows
    it re-checked, and (id, *W_COLS) for each.
    """
    db, pair, where, args, days, store_name = job
    from tradingagents import market_sweep as msw, stores

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    try:
        got = con.execute(f"SELECT * FROM rows INDEXED BY rows_pair{where}",
                          [*args, pair]).fetchall()
    finally:
        con.close()
    rows = []
    for r in got:
        d = {k: r[k] for k in r.keys() if k != "pair"}          # noqa: SIM118
        try:
            d["monthly"] = json.loads(d.get("monthly") or "{}")
        except ValueError:
            d["monthly"] = {}
        rows.append(d)
    if rows:
        store = stores.by_name(store_name) if store_name == "v2" else None
        msw.window_rows(rows, int(days), group_max=len(rows) + 1, store=store)
    return pair, len(rows), [(r["id"], *[r.get(c) for c in W_COLS]) for r in rows]


def workers() -> int:
    """Every core but two: the runner and the screen still have to answer."""
    return max(1, (os.cpu_count() or 4) - 2)


def run(spec: dict, db, store_name: str, publish, stop=None,
        processes: int | None = None) -> dict:
    """Re-check every matching row a coin at a time, then write the whole file.

    `publish(**fields)` reports progress; `stop()` returning True ends the job
    cleanly between coins. `processes=0` re-checks in THIS process (tests,
    whose stand-ins a worker process would not see); None uses workers().
    Returns the finished file's facts.
    """
    from concurrent.futures import ProcessPoolExecutor, as_completed

    from tradingagents import api, rows_index as ri, stores

    filters = clean_spec(spec)
    days = int(filters.get("days") or 0)
    t0 = time.time()
    publish(running=True, phase="counting the rows", now="counting the rows…")
    with ri.using_db(db):
        total = ri.count_exact(**{k: v for k, v in filters.items()
                                  if k in FILTER_KEYS})
    out_dir = export_dir(store_name)
    stem = f"{store_name}-full-" + api.strategies_csv_name(
        filters.get("coin"), filters.get("tf"), filters.get("signal"),
        int(filters.get("min_trades") or 0), filters["sort"],
        min_winrate=float(filters.get("min_winrate") or 0),
        max_tp=float(filters.get("max_tp") or 0), sizing=filters.get("sizing"),
        group=filters.get("group"), max_sl=float(filters.get("max_sl") or 0),
        min_tp=float(filters.get("min_tp") or 0),
        min_sl=float(filters.get("min_sl") or 0),
        tp_over_sl=bool(filters.get("tp_over_sl")), asset=filters.get("asset"),
        days=days).removesuffix(".csv")
    win_db = out_dir / f"{stem}.window.sqlite"
    part = out_dir / f"{stem}.csv.part"
    final = out_dir / f"{stem}.csv"
    for f in (win_db, part):
        f.unlink(missing_ok=True)

    lookup = None
    lcon = None
    if days > 0:
        # PHASE 1 — re-check every matching row, a coin at a time
        wcon = sqlite3.connect(win_db)
        wcon.execute(f"CREATE TABLE win (id TEXT PRIMARY KEY, {', '.join(W_COLS)})")
        rcon = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
        q = "SELECT pair FROM pairs"
        qa: list = []
        if filters.get("coin") or filters.get("tf"):
            q += " WHERE 1=1"
            if filters.get("coin"):
                q, qa = q + " AND coin = ?", [*qa, str(filters["coin"]).upper()]
            if filters.get("tf"):
                q, qa = q + " AND tf = ?", [*qa, filters["tf"]]
        pairs = [r[0] for r in rcon.execute(q, qa)]
        rcon.close()
        where, args = _pair_where(filters)
        done_rows = done_pairs = 0
        publish(running=True, phase="re-checking", total=total, done=0,
                pairs_total=len(pairs), pairs_done=0,
                now=f"re-checking {total:,} row(s) over the last {days} days, "
                    f"a coin at a time on {workers()} cores")
        t1 = time.time()
        jobs = [(str(db), p, where, args, days, store_name) for p in pairs]
        if processes == 0:
            from concurrent.futures import Future

            futs = []
            for j in jobs:
                f = Future()
                f.set_result(_retest_pair(j))
                futs.append(f)
            pool_cm = contextlib.nullcontext()
        else:
            pool_cm = ProcessPoolExecutor(max_workers=processes or workers())
        with pool_cm as pool:
            if pool is not None:
                futs = [pool.submit(_retest_pair, j) for j in jobs]
            for fut in as_completed(futs):
                _, n, got = fut.result()
                if got:
                    wcon.executemany(
                        f"INSERT OR REPLACE INTO win VALUES "
                        f"({', '.join('?' * (len(W_COLS) + 1))})", got)
                done_rows += n
                done_pairs += 1
                if done_pairs % 20 == 0 or done_pairs == len(pairs):
                    wcon.commit()
                    el = time.time() - t1
                    rate = done_rows / el if el > 0 else 0
                    left = (total - done_rows) / rate if rate > 0 else None
                    publish(running=True, phase="re-checking", total=total,
                            done=done_rows, pairs_total=len(pairs),
                            pairs_done=done_pairs,
                            eta_s=int(left) if left is not None else None,
                            now=f"re-checked {done_rows:,} of {total:,} row(s) "
                                f"({done_pairs:,} of {len(pairs):,} coins)")
                if stop and stop():
                    for f in futs:
                        f.cancel()
                    wcon.close()
                    publish(running=False, stopped=True, finished=int(time.time()),
                            note=f"stopped after {done_rows:,} of {total:,} rows")
                    return {"stopped": True}
        wcon.commit()
        wcon.close()
        lcon = sqlite3.connect(win_db, check_same_thread=False)

        def lookup(batch: list) -> None:
            ids = [r["id"] for r in batch]
            found = {}
            for i in range(0, len(ids), 900):
                chunk = ids[i:i + 900]
                for row in lcon.execute(
                        f"SELECT id, {', '.join(W_COLS)} FROM win WHERE id IN "
                        f"({', '.join('?' * len(chunk))})", chunk):
                    found[row[0]] = dict(zip(W_COLS, row[1:], strict=True))
            for r in batch:
                got = found.get(r["id"])
                if got and got.get("restated"):
                    # ONLY what the re-check produced: `window_rows` never
                    # sets some figures (w_worst), and the quick download then
                    # falls back to the stored value; copying a NULL over it
                    # printed "" where the quick file printed "0.0" (found by
                    # comparing the two files, 688 rows, Sep 25, 2026)
                    r.update({k: v for k, v in got.items() if v is not None})
                    r["restated"] = True

    # PHASE 2 — the file, through the quick download's own writer
    publish(running=True, phase="writing the file", total=total, done=0,
            now=f"writing the file ({total:,} row(s) matched)…")
    written = 0
    stats_line = ""
    with open(part, "w", encoding="utf-8", newline="") as fh:
        gen = api.strategies_csv_lines(
            **{k: v for k, v in filters.items() if k in FILTER_KEYS},
            sort=filters["sort"], desc=filters.get("desc"), days=days,
            db_path=db, store=stores.V2 if store_name == "v2" else None,
            _dl={}, window_lookup=lookup, window_cap=0)
        for i, chunk in enumerate(gen):
            fh.write(chunk)
            if i == 0:
                continue
            for line in chunk.splitlines():
                # the csv writer QUOTES a note (it holds commas), so the line
                # begins with '"' — a note is never a row (found by the test:
                # 49 counted for 48 written)
                bare = line.lstrip('"')
                if bare.startswith(("WINDOW FLOOR", "WINDOW CAPPED")):
                    stats_line = bare.rstrip('"')
                elif line and not bare.startswith("#"):
                    written += 1
            if i % 50 == 0:
                publish(running=True, phase="writing the file", total=total,
                        done=written, now=f"writing the file: {written:,} row(s) so far")
    if lcon is not None:
        lcon.close()               # Windows will not delete an open file
    final.unlink(missing_ok=True)
    part.rename(final)
    win_db.unlink(missing_ok=True)
    facts = {"file": str(final), "name": final.name, "rows": written,
             "matched": total, "bytes": final.stat().st_size,
             "seconds": round(time.time() - t0, 1), "key": key_of(spec),
             "days": days, "floor_note": stats_line}
    (out_dir / f"{stem}.json").write_text(json.dumps(facts), encoding="utf-8")
    return facts
