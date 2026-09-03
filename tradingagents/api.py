"""The HTTP layer the React frontend talks to. Thin on purpose.

Every route is a typed window onto a module the test suite already trusts —
no business logic lives here, so a bug here can only be a wiring bug, and
every route is pinned by tests/test_api.py before any frontend uses it.

Serves localhost by default. No response ever carries a secret: the tests
plant a canary MEXC key and sweep every GET for it.

Run:  .venv/bin/uvicorn tradingagents.api:app --port 8787
"""
from __future__ import annotations

import re
import time as _time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="TradingAgents API", version="1.0")




def _finish_handoff() -> None:
    """Dispatch the cloud sweep once a handed-off local job has stopped.

    Runs on the supervisor's tick. Three guards, each one a way this could go
    wrong: the local job must actually be stopped, the request must not already
    have been served, and the cloud gets ONLY the coins with no local
    watermark — `merge_into_store` replaces what it covers, so re-measuring a
    finished pair in the cloud would land rows behind the Mac's own watermark.
    """
    from tradingagents import cloud_sweep as cs, db_jobs as dj

    kind = "backtest"
    if not dj.handoff_requested(kind):
        return
    st = dj.status(kind)
    if st.get("running"):
        return                          # still finishing the pairs in flight
    spec = dj._read(dj.FILES[kind]["spec"])
    coins = list(spec.get("coins") or [])
    tfs = list(spec.get("tfs") or [])
    # gh flaps: its keyring token has been invalid on and off all day. If the
    # local job has already stood down and the dispatch fails, clearing the
    # flag would lose BOTH runs — so it is kept and retried on the next tick,
    # and cleared only once the cloud actually has the work.
    ok, why = cs.available()
    if not ok:
        print(f"[handoff] local job is down but GitHub is not usable ({why[:60]}) "
              f"— keeping the request and retrying", flush=True)
        return
    left = cs.unmeasured(coins, tfs)
    if not left:
        dj.clear_handoff(kind)
        print("[handoff] nothing left unmeasured — no cloud run needed",
              flush=True)
        return
    run = cs.dispatch(shards=20, coins=len(left), timeframes=",".join(tfs),
                      min_days=0)      # every contract — never the 365 default nobody chose
    cs.remember(run)
    dj.clear_handoff(kind)              # the cloud has it; the request is served
    print(f"[handoff] {len(left)} coins the Mac never reached -> GitHub run "
          f"{run.get('id')}", flush=True)
    try:
        from tradingagents import notifications as nt

        nt.record("backtest", "Handed off to GitHub Actions", ok=True,
                  detail=f"{len(left)} unmeasured coins dispatched; "
                         f"the Mac's {len(coins) - len(left)} finished coins "
                         f"are untouched")
    except Exception:
        pass


@app.on_event("startup")
def _keep_the_row_index_current() -> None:
    """The strategy index must advance whether or not anyone is watching. When
    it only synced from inside the request handler, closing the Backtest tab
    froze it: the row count climbed while 43 finished coins stayed invisible.
    """
    try:
        from tradingagents import rows_index as ri

        # a SEPARATE PROCESS, not a thread here: the indexer's work is pure
        # Python and would hold this process's GIL, which made every request
        # queue behind it (1.7s for a one-file endpoint) and the health probe
        # time out, printed on screen as "API unreachable".
        pid = ri.spawn_indexer()
        print(f"[rows-index] indexer pid={pid or 'already running'}", flush=True)
    except Exception as exc:
        print(f"[rows-index] COULD NOT START: {exc!r}", flush=True)

    # AUTO-RETRY. A crashed sweep used to stay dead until the operator noticed
    # hours later; per-pair checkpointing meant a restart would have resumed,
    # but nothing ever did the restarting.
    try:
        import threading as _th

        from tradingagents import db_jobs as _dj

        def _watch() -> None:
            while True:
                _time.sleep(30)
                # A HAND-OFF completes here, once the local job has actually
                # stood down — dispatching while it was still finishing would
                # have both measuring the same pairs.
                try:
                    _finish_handoff()
                except Exception as exc:
                    print(f"[handoff] failed: {exc!r}", flush=True)
                for kind in ("backtest", "download", "btupdate"):
                    try:
                        got = _dj.resume_if_died(kind)
                        if got.get("resumed"):
                            print(f"[supervisor] {kind} resumed, attempt "
                                  f"{got['attempt']} (pid {got['pid']})",
                                  flush=True)
                    except Exception:
                        pass

        _th.Thread(target=_watch, name="job-supervisor", daemon=True).start()
        print("[supervisor] watching for crashed jobs", flush=True)
    except Exception as exc:
        # The API must still start -- but SILENTLY skipping this is how
        # "behind 55 and never moving" looked like a working system.
        print(f"[supervisor] COULD NOT START: {exc!r}", flush=True)

# The Next.js dev server runs on :3000; the API on :8787. Same machine, two
# ports — the browser calls this CORS and blocks it without consent.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# interval -> the timeframe name row_code hashes with
_TF_OF = {"Min1": "1m", "Min5": "5m", "Min15": "15m", "Min30": "30m",
          "Min60": "1h", "Hour4": "4h", "Hour8": "8h", "Day1": "1d"}


def row_id_for(key: str, coin: str | None, settings: dict) -> str:
    """The stable row id for one strategy ON ONE COIN.

    Hashed by the same backtest_report.row_code every report uses, so the id
    beside an open position is the id to paste into a report's find-by-ID box.
    Shared by the strategies grid and the positions table — computing it twice
    is how two screens end up naming one row differently.
    """
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br
    from tradingagents.local_history import _sig_of

    # An unknown key (an exchange position the bot never opened carries
    # "(not the bot's)") must NOT hash: it would print a real-looking id that
    # matches no combination in any report.
    if not coin or key not in at.STRATEGY_SPECS:
        return ""
    spec = at.STRATEGY_SPECS[key]
    try:
        return br.row_code(
            coin.replace("_USDT", ""),
            _TF_OF.get(spec.get("interval") or "", ""),
            _sig_of(key),
            round(float(spec.get("threshold") or 0) * 100, 3),
            round(float(spec.get("sl") or 0) * 100, 3),
            round(float(spec.get("tp") or 0) * 100, 3),
            # THIS strategy's sizing, not the account default. Sizing is part
            # of the combination, so hashing a flat row with the account's
            # martingale gave it a laddered row's id: the deployed NOM row
            # printed #L4TCWCZY in the app and #F2S7J87Z on the board it came
            # from, which is the "same row, a different number on every page"
            # problem the stable id exists to end.
            at.sizing_for(settings, key))
    except Exception:                                          # noqa: BLE001
        return ""


JOB_KINDS = ("download", "backtest", "btupdate", "stratbt")

# A pair takes minutes; twelve is well past any of them, so a hand-off still
# unserved by then is not slow, it is stuck.
HANDOFF_STALL_SECONDS = 12 * 60


# ------------------------------------------------------------------ health
@app.get("/api/health")
def health() -> dict:
    """Liveness. The header chip polls this every 10 seconds, so it must never
    touch more than a directory listing — see parquet_store.sizes(rows=False).
    """
    from tradingagents import parquet_store as pqs

    return {"ok": True, "storage": pqs.sizes(rows=False)}


# -------------------------------------------------------------- strategies
@app.get("/api/strategies")
def strategies(coin: str | None = None, tf: str | None = None,
               signal: str | None = None, profitable: bool = False,
               limit: int = 500, offset: int = 0,
               sort: str = "profit", min_trades: int = 0,
               min_winrate: float = 0.0, max_tp: float = 0.0,
               max_sl: float = 0.0,
               sizing: str | None = None, row_id: str | None = None,
               group: str | None = None,
               months: int = 0, days: int = 0,
               desc: bool | None = None) -> dict:
    """Every stored strategy, filtered. Rows carry their stable id.

    Served from the SQLite index, NOT by re-reading the store. This route used
    to call `market_sweep.all_rows()`, which parses every pair file: measured
    28.6s for 648,181 rows over 363 MB, 53 pairs into a 3,960-pair sweep. The
    grid polls every 4s, so the calls piled up, the threadpool jammed, and the
    browser reported `HTTP 500`. See tradingagents/rows_index.py.
    """
    from tradingagents import rows_index as ri

    # no sync kick here: a timer thread keeps the index current (see the
    # startup hook), so a page open does not decide whether data appears.
    try:
        got = ri.query(coin=coin, tf=tf, signal=signal,
                       profitable=profitable, limit=limit,
                       offset=offset, sort=sort,
                       min_trades=min_trades, min_winrate=min_winrate,
                       max_tp=max_tp, sizing=sizing, row_id=row_id,
                       group=group, max_sl=max_sl, months=months, desc=desc)
    except ri.SortNotReady as exc:
        # 503: the request is fine, the store is not ready for it yet.
        # The screen shows this sentence rather than hanging on a sort
        # of 21 million rows (2026-08-26).
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        # 400, not 500: the request is wrong, and the message names
        # what IS allowed rather than making the caller guess
        raise HTTPException(400, str(exc)) from exc
    # the window's trades/W/L/win % where they can be EXACT (see restate_window)
    if months and got.get("window") and len(got.get("rows") or []) <= RESTATE_MAX:
        for r in got["rows"]:
            r.update(restate_window(r, got["window"]))
    got["restate_max"] = RESTATE_MAX
    # LAST N DAYS. Operator, 2026-09-02: "can you add days textbox isntead of
    # using past 1 month only / if months is 0 then follow the days" -- so
    # MONTHS WINS when both are set, and the days window is a re-measurement
    # (the store keeps profit per MONTH and no trade counts at all, so a day
    # window cannot be derived from it). Every row on the page is restated or
    # the request says why, rather than a table where some rows are the window
    # and others are their whole history.
    got["days"] = 0
    if days and not months:
        from tradingagents import market_sweep as msw

        rows = got.get("rows") or []
        if len(rows) > DAYS_ROW_MAX:
            raise HTTPException(
                503, f"a {int(days)}-day window re-measures every row from the "
                     f"stored candles, so one request restates at most "
                     f"{DAYS_ROW_MAX} rows — this page asked for {len(rows)}. "
                     f"Set the page to {DAYS_ROW_MAX} rows or fewer (and it is "
                     f"faster still with a coin named).")
        try:
            win = msw.window_rows(rows, int(days),
                                  base_margin=float(rows[0].get("base") or 5.0)
                                  if rows else 5.0)
        except msw.WindowTooWide as exc:
            raise HTTPException(503, str(exc)) from exc
        got["days"] = int(days)
        got["days_window"] = [win["first"], win["last"]]
        got["days_groups"] = win["groups"]
    got["index"] = ri.status()             # so the UI can say "still indexing"
    return got


def strategies_csv_lines(coin=None, tf=None, signal=None, profitable=False,
                         sort="profit", min_trades=0, min_winrate=0,
                         max_tp=0, sizing=None, row_id=None, group=None,
                         max_sl=0, days=0,
                         desc=None, batch=5_000):
    """The CSV, one chunk at a time — a module-level generator on purpose.

    Inside the route it was only reachable through StreamingResponse's ASYNC
    iterator, and draining that in a test needs an event loop, which on Windows
    opens a socket and trips the no-network guard. A plain generator is
    testable, and the route just wraps it.

    Same filters, same order and the same fields as the table (kit item F),
    plus the month figures as one JSON column.
    """
    import csv
    import io as _io
    import json as _json

    from tradingagents import rows_index as ri

    # kit item F: every row carries every column, the file included. `balanced`
    # is derived, so it is appended rather than living in ri.COLS (the table's
    # own shape) — and `iter_rows` does not compute it, so the CSV rates each
    # row here with the same function the grid used.
    cols = list(ri.COLS)
    if days:
        # the window travels with the rows, so the file can be read a week
        # later without guessing which days it covered
        cols += ["window_first", "window_last", "window_days"]
    buf = _io.StringIO()
    w = csv.writer(buf, lineterminator="\n")

    def flush() -> str:
        out = buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        return out

    w.writerow(cols + ["balanced", "balanced_why", "monthly_json"])
    yield flush()
    # A StreamingResponse has already sent 200 by the time a row fails, so an
    # exception here cannot become an error page — it just ENDS the download.
    # That is how 5,000 rows of 43,867 arrived looking like the whole file
    # (2026-08-27). So: count what left, and if the stream dies, SAY SO in the
    # file itself and in the log. A short file that says it is short is worth
    # more than a short file that does not.
    sent = 0
    try:
        for r in ri.iter_rows(coin=coin, tf=tf, signal=signal,
                              profitable=profitable, sort=sort,
                              min_trades=min_trades, min_winrate=min_winrate,
                              max_tp=max_tp, sizing=sizing, row_id=row_id,
                              group=group, max_sl=max_sl, days=days,
                              desc=desc, batch=batch):
            score, why = ri.balanced_score(r)
            w.writerow([r.get(c) for c in cols] + [score, why]
                       + [_json.dumps(r.get("monthly") or {},
                                      separators=(",", ":"))])
            sent += 1
            yield flush()
        if days and sent >= ri.DAYS_CSV_MAX:
            # a capped file SAYS it is capped, IN the file (kit rule: a capped
            # grid says what it capped)
            w.writerow([f"WINDOW CAPPED: this download re-measured the first "
                        f"{sent} rows over the last {int(days)} days; a days "
                        f"window is a re-measurement (~0.09 s a row), so it "
                        f"stops there. Narrow the filter, or download without "
                        f"the window for every matching row's whole history."])
            yield flush()
    except Exception as exc:                                   # noqa: BLE001
        print(f"[strategies.csv] export stopped after {sent:,} rows: "
              f"{type(exc).__name__}: {exc}", flush=True)
        w.writerow([f"EXPORT INCOMPLETE after {sent} rows: "
                    f"{type(exc).__name__}: {exc}"])
        yield flush()
        raise


def strategies_csv_name(coin=None, tf=None, signal=None, min_trades=0,
                        sort="profit", min_winrate=0, max_tp=0,
                        sizing=None, group=None, max_sl=0, days=0) -> str:
    """A filename that says which slice of the store is in the file."""
    bits = [b for b in (coin, tf, signal,
                        f"min{min_trades}" if min_trades else "",
                        # the win-rate floor is part of WHICH slice this is:
                        # two downloads of the same coin differ only by it
                        f"wr{_trim(min_winrate)}" if min_winrate else "",
                        f"tp{_trim(max_tp)}" if max_tp else "",
                        f"sl{_trim(max_sl)}" if max_sl else "",
                        # the WINDOW belongs in the name: two downloads of the
                        # same filter differ entirely by it
                        f"last{int(days)}d" if days else "",
                        sizing or "",
                        # the group is part of WHICH slice this file is: the
                        # same coin and order differ entirely by it
                        group or "",
                        sort) if b]
    return "strategies-" + "-".join(str(b) for b in bits) + ".csv"


def _trim(x) -> str:
    """50.0 -> "50", 62.5 -> "62.5" — a filename should not carry a dangling
    zero the screen never printed."""
    f = float(x)
    return str(int(f)) if f == int(f) else str(f)


@app.get("/api/strategies.csv")
def strategies_csv(coin: str | None = None, tf: str | None = None,
                   signal: str | None = None, profitable: bool = False,
                   sort: str = "profit", min_trades: int = 0,
                   min_winrate: float = 0.0, max_tp: float = 0.0,
                   max_sl: float = 0.0,
                   sizing: str | None = None, row_id: str | None = None,
                   group: str | None = None, months: int = 0, days: int = 0,
                   desc: bool | None = None):
    """EVERY matching row as CSV — no limit, streamed.

    The screen can hold a few thousand rows; the store holds 21,858,026. The
    operator asked for all of them ("give me all", 2026-08-26), so this writes
    all of them to a file instead of pretending a page is the whole list.
    """
    from fastapi.responses import StreamingResponse

    from tradingagents import rows_index as ri

    # fail BEFORE the stream starts: an error mid-download is a truncated file
    # that looks complete
    try:
        next(ri.iter_rows(coin=coin, tf=tf, signal=signal,
                          profitable=profitable, sort=sort,
                          min_trades=min_trades, min_winrate=min_winrate,
                          max_tp=max_tp, sizing=sizing, row_id=row_id,
                          group=group, max_sl=max_sl,
                          days=0 if months else days, desc=desc), None)
    except ri.SortNotReady as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    name = strategies_csv_name(coin, tf, signal, min_trades, sort,
                               min_winrate=min_winrate, max_tp=max_tp,
                               sizing=sizing, group=group, max_sl=max_sl,
                               days=0 if months else days)
    return StreamingResponse(
        strategies_csv_lines(coin=coin, tf=tf, signal=signal,
                            profitable=profitable, sort=sort,
                            min_trades=min_trades, min_winrate=min_winrate,
                            max_tp=max_tp, sizing=sizing, row_id=row_id,
                            group=group, max_sl=max_sl,
                            days=0 if months else days, desc=desc),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/strategies/reindex")
def strategies_reindex() -> dict:
    """Index every measured pair NOW, instead of one per cycle.

    While a sweep runs the indexer trickles a single pair a cycle so it cannot
    steal the machine the operator is waiting on. On 2026-08-26 that left the
    list with 711 of the 973 coins that had rows — 1,094 pairs behind, about
    three hours of trickling — and nothing on screen could ask it to hurry.
    This is that ask: `force=True`, in a background thread, one at a time.
    """
    from tradingagents import rows_index as ri

    st = ri.status()
    behind = int(st.get("behind") or 0)
    if behind <= 0:
        return {"started": False, "behind": 0,
                "why": "the index is up to date with every measured pair"}
    if st.get("syncing") or not ri.sync_in_background(force=True):
        return {"started": False, "behind": behind,
                "why": "already indexing — it is working through the backlog"}
    return {"started": True, "behind": behind,
            "why": f"indexing {behind:,} measured pair(s) now"}


# How many rows a request may have restated from rebuilt trades. One: a rebuild
# reads the pair's candles and replays them (~1 s), so a 500-row page would be a
# ten-minute request. An #id lookup returns exactly one row, which is the case
# the operator asked for.
RESTATE_MAX = 1
# How many rows a DAYS window may re-measure in one request. Each row is a walk
# over the window (milliseconds) but each distinct coin/timeframe/signal costs
# a signal computation (~1-2 s), so a 500-row page would be minutes. 50 keeps
# the worst case near a minute, and the route says so rather than hanging.
DAYS_ROW_MAX = 50


def restate_window(row: dict, window: list) -> dict:
    """`w_trades`, `w_wins`, `w_losses`, `w_winrate` and the log's own window
    profit, counted from this row's trades rebuilt from the candles.

    By EXIT month, which is how the sweep counts a trade into a month
    (`monthly[_month_of(exit_bar)] += pnl`). Returns {} when the log cannot be
    rebuilt — a missing figure must stay missing rather than become a zero.
    """
    from tradingagents import market_sweep as msw
    from tradingagents.positions_view import fmt_when          # noqa: F401

    if not window:
        return {}
    try:
        got = msw.trades_for(row["coin"], row["tf"], signal=row["signal"],
                             th=float(row.get("th") or 0.0),
                             sl=float(row["sl"]), tp=float(row["tp"]),
                             sizing=row["sizing"],
                             base_margin=float(row.get("base") or 5.0))
    except Exception as exc:                                   # noqa: BLE001
        print(f"[strategies] could not restate {row.get('id')}: "
              f"{type(exc).__name__}: {exc}", flush=True)
        return {}
    log = got.get("log") or []
    if not log:
        return {}
    months = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
              "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
    keep = []
    for t in log:
        stamp = str(t.get("exit time") or "")
        # "Aug 03, 2026 8:03pm" — the project's one date format
        parts = stamp.replace(",", "").split()
        if len(parts) < 3 or parts[0] not in months:
            continue
        key = f"{parts[2]}-{months[parts[0]]:02d}"
        if key in window:
            keep.append(t)
    if not keep:
        return {"w_trades": 0, "w_wins": 0, "w_losses": 0, "w_winrate": 0.0,
                "w_profit_log": 0.0, "restated": True}
    wins = sum(1 for t in keep if float(t.get("pnl $") or 0) > 0)
    return {"w_trades": len(keep), "w_wins": wins,
            "w_losses": len(keep) - wins,
            "w_winrate": round(100 * wins / len(keep), 2),
            "w_profit_log": round(sum(float(t.get("pnl $") or 0)
                                      for t in keep), 2),
            "restated": True}


@app.get("/api/strategies/facets")
def strategy_facets() -> dict:
    """Distinct coins/timeframes/signals for the filter dropdowns, plus the
    TP% values this store's timeframes can actually hold (`tps`) — see
    rows_index.take_profits: the TP box offers those and caps itself at the
    largest, because asking for a TP no row has costs a full scan to answer
    "nothing" (25 s+ on 35,863,520 rows)."""
    from tradingagents import rows_index as ri

    return ri.facets()


class TradesQuery(BaseModel):
    coin: str
    tf: str
    signal: str
    th: float = 0.0
    sl: float
    tp: float
    sizing: str
    base_margin: float = 5.0


@app.post("/api/strategies/trades")
def strategy_trades(q: TradesQuery) -> dict:
    """Every trade one stored strategy made, rebuilt from local candles."""
    from tradingagents import market_sweep as msw

    got = msw.trades_for(q.coin, q.tf, signal=q.signal, th=q.th, sl=q.sl,
                         tp=q.tp, sizing=q.sizing, base_margin=q.base_margin)
    return got


# ----------------------------------------------------------------- storage
@app.get("/api/storage/by-coin")
def storage_by_coin() -> dict:
    """Bytes per coin and timeframe, plus WHEN each pair was last updated.

    The freshness comes from the candle index (scan=False, so this never walks
    every file on a request thread) — the store's own last bar, not a file
    mtime, because a rewrite that added no bars is not an update.
    """
    from tradingagents import market_sweep as msw

    rows = msw.storage_by_coin()
    index = msw.candle_index(scan=False)
    by_pair = {}
    for entry in index.values():
        coin = str(entry.get("symbol", "")).replace("_USDT", "")
        by_pair[(coin, entry.get("timeframe"))] = entry
    for r in rows:
        hit = by_pair.get((r["coin"], r["tf"]))
        r["last_ms"] = hit.get("last_ms") if hit else None
        r["bars"] = hit.get("bars") if hit else None
    return {"rows": rows}


@app.get("/api/storage/coverage")
def storage_coverage() -> dict:
    from tradingagents import market_sweep as msw

    return {"rows": msw.candle_coverage()}


@app.get("/api/storage/sizes")
def storage_sizes() -> dict:
    from tradingagents import parquet_store as pqs

    return pqs.sizes()


# -------------------------------------------------------------------- jobs
def _check_kind(kind: str) -> None:
    if kind not in JOB_KINDS:
        raise HTTPException(404, f"unknown job kind: {kind}")


@app.get("/api/backtest/capacity")
def backtest_capacity(timeframes: str = "") -> dict:
    """Who is free to run a sweep right now — this PC, GitHub, or both.

    The UPDATE BACKTEST button shows this BEFORE it is clicked, so the operator
    can see where the work will go. Operator, 2026-09-03: "why did you not use
    github since its free?" — GitHub had been idle all day because nothing ever
    asked.
    """
    from tradingagents import capacity as cap

    tfs = [t.strip() for t in timeframes.split(",") if t.strip()] or list(cap.ALL_TFS)
    return cap.plan(tfs)


@app.get("/api/backtest/logs")
def backtest_logs(cloud: bool = True) -> dict:
    """The LOGS section: what is still pending here, and every named error.

    Operator, 2026-09-03: "create a seperate section called logs just like in
    candles module si i can see what is pending on my side and what are errors".
    """
    from tradingagents import backtest_logs as bl

    return bl.logs(include_cloud=cloud)


@app.get("/api/jobs")
def jobs_all() -> dict:
    """Every job's state in ONE call, for the header's running-job indicator.

    Each screen used to poll only its own job, on a timer that died when the
    screen unmounted — so starting a backtest and navigating away left nothing
    on screen saying it was still running. The job itself was fine (db_jobs
    runs detached and keeps writing its progress file); the UI simply stopped
    reporting it. One request keeps a global indicator cheap.
    """
    from tradingagents import db_jobs

    out, running = {}, []
    for kind in JOB_KINDS:
        try:
            st = db_jobs.status(kind) or {}
        except Exception:
            st = {}
        out[kind] = st
        if st.get("running"):
            done, total = st.get("done") or 0, st.get("total") or 0
            running.append({
                "kind": kind,
                "now": st.get("now") or "",
                "done": done, "total": total,
                "pct": (round(100 * done / total) if total else None),
            })
    return {"jobs": out, "running": running, "any_running": bool(running)}


@app.get("/api/jobs/{kind}")
def job_status(kind: str) -> dict:
    _check_kind(kind)
    from tradingagents import db_jobs, market_sweep as msw

    got = db_jobs.status(kind)
    # Read the workers HERE rather than trusting the snapshot the job wrote:
    # the job process loaded its code when it started, so a running sweep
    # keeps publishing whatever that build did — including a finished task's
    # last line, which read as an idle core. This read drops anything whose
    # process is gone or that stopped being written.
    if got.get("running") and got.get("workers") is not None:
        got["workers"] = msw.worker_read()
    return got


@app.post("/api/jobs/{kind}/start")
def job_start(kind: str, spec: dict) -> dict:
    _check_kind(kind)
    from tradingagents import db_jobs

    # a run the operator starts by hand is a fresh budget of retries, so an
    # earlier bad patch cannot leave the supervisor refusing to restart this one
    db_jobs.clear_retries(kind)
    return {"pid": db_jobs.start(kind, spec)}


@app.post("/api/jobs/{kind}/handoff")
def job_handoff(kind: str) -> dict:
    """Finish the pairs in flight, then hand this sweep to GitHub Actions.

    Not a stop: the operator's words were "finish the current task then switch
    to github actions after its done". The local job completes what it is
    measuring, checkpoints it, and stands down; the supervisor then dispatches
    the cloud for the coins the Mac never reached.
    """
    _check_kind(kind)
    from tradingagents import cloud_sweep as cs, db_jobs

    ok, why = cs.available()
    if not ok:
        raise HTTPException(400, f"GitHub Actions is not usable: {why}")
    st = db_jobs.status(kind)
    if not st.get("running"):
        raise HTTPException(409, "that job is not running — start the cloud "
                                 "sweep directly instead")
    db_jobs.request_handoff(kind)
    return {"requested": True,
            "note": "finishing the pairs in flight, then handing over"}


@app.get("/api/jobs/{kind}/handoff")
def job_handoff_state(kind: str) -> dict:
    """What the button should say."""
    _check_kind(kind)
    from tradingagents import cloud_sweep as cs, db_jobs

    ok, why = cs.available()
    st = db_jobs.status(kind)
    # A request the running job CANNOT serve must say so, not sit on
    # "finishing the current pairs" forever. It hung for 19 minutes on
    # 2026-08-25 because the job had started before the handoff code existed,
    # so nothing in that process could ever notice the flag. The check is
    # deliberately generic — stale code, a wedged pair, a dead pool all look
    # the same from here, and all of them mean "this is not progressing".
    import time as _t

    stalled, reason = False, ""
    if db_jobs.handoff_requested(kind) and st.get("running"):
        try:
            age = _t.time() - db_jobs.FILES[kind]["handoff"].stat().st_mtime
        except OSError:
            age = 0.0
        if age > HANDOFF_STALL_SECONDS:
            stalled = True
            reason = (f"asked {age / 60:.0f} minutes ago and the job has not "
                      f"stood down. A pair takes minutes, but not this long — "
                      f"the likeliest cause is that this job started before "
                      f"the hand-off existed, so it cannot see the request. "
                      f"Stopping and restarting it resumes from the last "
                      f"checkpoint and loses nothing.")
    return {"available": ok, "why": ("" if ok else why),
            "requested": db_jobs.handoff_requested(kind),
            "handed_off": bool(st.get("handoff")),
            "running": bool(st.get("running")),
            "stalled": stalled, "stalled_why": reason}


@app.post("/api/jobs/{kind}/stop")
def job_stop(kind: str) -> dict:
    _check_kind(kind)
    from tradingagents import db_jobs

    db_jobs.request_stop(kind)
    return {"ok": True}


# ----------------------------------------------------------------- history
@app.get("/api/ledger")
def ledger(limit: int = 500) -> dict:
    import tradingagents.auto_trader as at

    rows = at.ledger_tail(100000)
    return {"rows": rows[:max(0, min(limit, 5000))], "total": len(rows)}


@app.get("/api/deployments")
def deployments(symbol: str | None = None, limit: int = 200) -> dict:
    from tradingagents import local_history as lh

    return {"rows": lh.deployments(symbol=symbol, limit=limit)}


# ----------------------------------------------------------------- reports
@app.get("/api/reports/file/{name}")
def report_file(name: str):
    """Serve one generated grid page. The name is checked against the folder's
    own listing, so a traversal ('../../etc/passwd') cannot reach anything."""
    from pathlib import Path

    from fastapi.responses import FileResponse

    d = Path(__file__).resolve().parent.parent / "static" / "bt"
    target = (d / name).resolve()
    if target.parent != d.resolve() or not target.is_file() \
            or target.suffix != ".html":
        raise HTTPException(404, f"no such report: {name}")
    return FileResponse(target, media_type="text/html")


@app.get("/api/reports")
def reports() -> dict:
    """Generated grid pages, newest first, so the frontend can link them."""
    from pathlib import Path

    d = Path(__file__).resolve().parent.parent / "static" / "bt"
    if not d.exists():
        return {"rows": []}
    files = sorted(d.glob("*.html"), key=lambda f: -f.stat().st_mtime)
    return {"rows": [{"name": f.name, "bytes": f.stat().st_size,
                      "mtime": int(f.stat().st_mtime)} for f in files[:50]]}


# ------------------------------------------------------------------- trading
@app.get("/api/trade/summary")
def trade_summary() -> dict:
    """The status ribbon: process, modes, wallet, today, all-time, open."""
    import tradingagents.auto_trader as at
    from tradingagents.dataflows import mexc_credentials as cred, mexc_futures as fx

    cred.load_into_env()
    pid = at.runner_pid()
    books = at.active_modes()
    equity = None
    open_rows: list[dict] = []
    # assets() returns a DICT keyed by currency, not a list — iterating it as
    # a list yields the key strings and .get() dies, which read as "no wallet"
    # instead of an error. usdt_equity() is the one reader both screens use.
    try:
        equity = round(fx.usdt_equity(), 2) if fx.has_credentials() else None
    except Exception:
        equity = None
    try:
        for p in fx.open_positions():
            open_rows.append({
                "symbol": p.get("symbol"),
                "unrealized": round(float(p.get("unRealizedPnl") or 0.0), 2),
                "margin": round(float(p.get("im") or 0.0), 2),
                "side": "LONG" if int(p.get("positionType") or 1) == 1 else "SHORT",
                "entry": float(p.get("holdAvgPrice") or 0.0),
            })
    except Exception:
        pass
    paper_rows: list[dict] = []
    for skey, sst in (at.load_state() or {}).items():
        pos = sst.get("position") if isinstance(sst, dict) else None
        if pos and pos.get("dry"):
            paper_rows.append({
                # the book key is "SYMBOL#paper" (auto_trader.state_key), so
                # the separator is '#'. Splitting on ':' left "PI#paper" on
                # screen where the coin name belongs.
                "symbol": skey.split("#", 1)[0],
                "side": "LONG" if int(pos.get("side") or 1) == 1 else "SHORT",
                "entry": pos.get("entry"),
                "margin": pos.get("margin"),
                "strategy": pos.get("strategy"),
            })
    life = at.coin_stats(dry=False)
    life_total = round(sum(v["pnl"] for v in life.values()), 2)
    open_real = round(sum(r["unrealized"] for r in open_rows), 2)
    return {
        "pid": pid,
        "mode": ("LIVE+PAPER" if (False in books and True in books) else
                 "LIVE" if False in books else
                 "PAPER" if True in books else "OFF") if pid else "STOPPED",
        "halted": at.halted(),
        "equity": equity,
        "today_real": at.pnl_today(dry=False),
        "today_paper": at.pnl_today(dry=True),
        "all_time_closed": life_total,
        "open_unrealized": open_real,
        "all_time": round(life_total + open_real, 2),
        "open_positions": open_rows,
        "paper_positions": paper_rows,
    }


@app.get("/api/trade/positions")
def trade_positions() -> dict:
    """Open positions on both books, with every column the operator reads.

    Fourteen columns, not five: the set is a standing operator decision
    (app.py's _TM_POS comment records restoring them on 2026-08-20), and
    `bracket` is the one that says whether real money is protected.
    """
    import tradingagents.auto_trader as at
    from tradingagents import positions_view as pv
    from tradingagents.dataflows import mexc_credentials as cred, mexc_futures as fx

    cred.load_into_env()

    def last_price(symbol: str):
        # fx.last_price is the mark-price reader. klines() returns a DataFrame,
        # so indexing it like a list silently yielded nothing and the "to TP"
        # progress column rendered empty on every row.
        try:
            return float(fx.last_price(symbol))
        except Exception:
            return None

    def contract_size(symbol: str) -> float:
        try:
            return float(fx.contract_spec(symbol).get("contractSize") or 1.0)
        except Exception:
            return 1.0

    state = at.load_state()
    try:
        live = fx.open_positions()
    except Exception:
        live = []
    settings = at.load_settings()
    kw = {"last_price": last_price, "contract_size": contract_size,
          "taker_fee": at.taker_fee, "leverage": at.LEVERAGE,
          "settings": settings}
    real = pv.build_rows(state=state, exchange_positions=live,
                         stats=at.coin_stats(dry=False), dry=False, **kw)
    paper = pv.build_rows(state=state, exchange_positions=[],
                          stats=at.coin_stats(dry=True), dry=True, **kw)
    # the same id the strategy grid prints, hashed with THIS row's coin — so
    # "which strategy is running here?" is answerable from the position alone
    for r in real + paper:
        r["id"] = row_id_for(r.get("strategy") or "", r.get("symbol"), settings)
    unprotected = [r["coin"] for r in real if r["bracket"]]
    return {"real": real, "paper": paper, "leverage": at.LEVERAGE,
            "unprotected": unprotected}


@app.post("/api/trade/positions/close")
def trade_close_one(body: dict) -> dict:
    """Close ONE position at market. Irreversible; the caller confirms."""
    import tradingagents.auto_trader as at
    from tradingagents.dataflows import mexc_credentials as cred

    cred.load_into_env()
    symbol = str(body.get("symbol") or "").strip()
    if not symbol:
        raise HTTPException(400, "a symbol is required")
    return at.close_one(symbol)


@app.post("/api/trade/panic")
def trade_panic(body: dict) -> dict:
    """PANIC: halt entries and close every position at market.

    Requires an explicit {"confirm": true} — a mis-click must not be able to
    flatten the account.
    """
    import tradingagents.auto_trader as at
    from tradingagents.dataflows import mexc_credentials as cred

    if body.get("confirm") is not True:
        raise HTTPException(400, "panic requires confirm=true")
    cred.load_into_env()
    return at.panic_stop(close_positions=bool(body.get("close_positions", True)))


def _book_record(stats: dict, today: dict, key: str, armed: bool) -> dict:
    """One book's realized record for one strategy, as the screen shows it."""
    got = stats.get(key) or {}
    return {"pnl": round(float(got.get("pnl") or 0.0), 2),
            "trades": int(got.get("trades") or 0),
            "wins": int(got.get("wins") or 0),
            "losses": int(got.get("losses") or 0),
            "winrate": got.get("winrate"),
            "today": round(float(today.get(key) or 0.0), 2),
            "armed": bool(armed)}


@app.get("/api/trade/strategies")
def trade_strategies(catalog: bool = False) -> dict:
    """The DEPLOYED strategies by default — the ones with a book or a coin.

    `catalog=true` adds every other key in STRATEGY_ORDER so a new one can be
    armed. It is not the default on purpose: showing all 27 made four armed
    strategies read as twenty-seven running ones (2026-08-21), and the
    Streamlit screen it replaced had made the same call in the other
    direction ("an unticked tile is clutter the operator has to read past").
    """
    import tradingagents.auto_trader as at

    settings = at.load_settings()
    books = settings.get("strategy_books") or {}
    coins = settings.get("strategy_coins") or {}
    margins = settings.get("strategy_margins") or {}
    stats_real = at.strategy_stats(dry=False)
    stats_paper = at.strategy_stats(dry=True)
    state = at.load_state()
    limits = settings.get("strategy_loss_limits") or {}
    sizing_now = at.sizing_for(settings)          # the account-wide default
    runstate = at.load_state()
    tripped = at.tripped_strategies(settings)
    locks = at.timeframe_locks(settings)
    # PER BOOK. This was `dry=False` for every row, so a demo-only row printed
    # the real book's today — always 0.00 for a strategy that has never traded
    # real money, whatever its demo did (label-must-match-data).
    today_real = at.pnl_today_by_strategy(dry=False)
    today_paper = at.pnl_today_by_strategy(dry=True)
    deployed = [k for k in at.STRATEGY_ORDER
                if (books.get(k) or coins.get(k))]
    keys = at.STRATEGY_ORDER if catalog else deployed
    rows = []
    for key in keys:
        spec = at.STRATEGY_SPECS.get(key) or {}
        base_m = float(margins.get(key) or 5.0)
        # the row's OWN book decides which ladder and which record to read: a
        # paper-only row was showing the live book's wins and losses
        _is_real = "real" in (books.get(key) or [])
        _bk_suffix = "" if _is_real else "#paper"
        st_row = ((stats_real if _is_real else stats_paper).get(key) or {})
        # book keys are "SYMBOL" (real) and "SYMBOL#paper" (simulated), so the
        # coin name is what precedes '#' and the book is which side it came from
        open_real_on, open_paper_on = [], []
        for bkey, v in state.items():
            pos = v.get("position") if isinstance(v, dict) else None
            if not pos or pos.get("strategy") != key:
                continue
            coin = bkey.split("#", 1)[0]
            (open_paper_on if pos.get("dry") else open_real_on).append(coin)
        # The row's STABLE ID, hashed from the combination by the same
        # backtest_report.row_code every report uses — so the id the operator
        # reads here is the id they can paste into a report's find-by-ID box.
        # Contracts are fixed per strategy, so the first coin identifies it;
        # with no coin there is no combination to hash and the id is blank.
        _rid = row_id_for(key, (coins.get(key) or [None])[0], settings)
        flat = at.sizing_for(settings, key) == "flat"    # THIS row's sizing
        rows.append({
            "key": key,
            "id": _rid,
            # the human name, for the operator. Empty for rows that have none,
            # so the cell simply does not render rather than printing "None".
            "label": at.label_for(key, settings),
            "interval": spec.get("interval"),
            "tp": spec.get("tp"), "sl": spec.get("sl"),
            "threshold": spec.get("threshold"),
            "books": books.get(key) or [],
            "coins": coins.get(key) or [],
            "base_margin": margins.get(key),
            "loss_cap": limits.get(key),
            # The LADDER RUNG. On the REAL book it belongs to the COIN, not
            # to this strategy — the exchange nets every order on a contract
            # into one position, so one counter is the truth there. On the
            # PAPER book each strategy has had its own slot since 2026-08-27
            # ("i want it isolated"), so a demo row's rung is its own and
            # nobody else's. This used to read `coin + "#paper"`, which stops
            # existing the moment the slots split, and every demo row would
            # have shown rung 0 for ever.
            "streak": (streak := max(
                (int((runstate.get(at.state_key(c, not _is_real, key)) or {})
                     .get("step", 0) or 0)
                 for c in (coins.get(key) or [])), default=0)),
            "streak_book": ("real" if _is_real else "paper"),
            # Only a REAL rung can be shared, and only by another real row on
            # the same coin. A demo row shares nothing now, so this list is
            # empty for it rather than naming strategies it no longer affects.
            "streak_shared_with": sorted(
                other for other in at.STRATEGY_ORDER
                if _is_real and other != key
                and "real" in (books.get(other) or [])
                and set(coins.get(other) or []) & set(coins.get(key) or [])),
            # PER ROW. A row that runs flat must not be drawn with a ladder:
            # the ladder column is what the operator reads before deploying.
            "sizing": at.sizing_for(settings, key),
            "ladder": ([base_m] if flat
                       else [round(base_m * m, 2) for m in at.LADDER]),
            "ladder_rung": (0 if flat else min(streak, len(at.LADDER) - 1)),
            "next_stake": (base_m if flat
                           else round(base_m * at.LADDER[min(streak, len(at.LADDER) - 1)], 2)),
            "notional": round(base_m * at.LEVERAGE, 2),
            "tripped": key in tripped,
            "live_locked": locks.get(key),
            # the row's OWN book, unchanged for every existing reader
            "today": round(float((today_real if _is_real else today_paper)
                                 .get(key) or 0.0), 2),
            "pnl": round(float(st_row.get("pnl") or 0.0), 2),
            "trades": int(st_row.get("trades") or 0),
            "wins": int(st_row.get("wins") or 0),
            "losses": int(st_row.get("losses") or 0),
            # ...and BOTH books, so the screen can show them side by side. A
            # strategy ticked LIVE and DEMO has two separate records and they
            # must never be blended into one "record" the operator judges it
            # by — `strategy_stats(dry=...)` keeps them apart at the source.
            "real": _book_record(stats_real, today_real, key,
                                 "real" in (books.get(key) or [])),
            "paper": _book_record(stats_paper, today_paper, key,
                                  "paper" in (books.get(key) or [])),
            "open_on": open_real_on,
            "open_on_paper": open_paper_on,
        })
    return {
        "rows": rows,
        "sizing": at.sizing_for(settings),
        "conflicts": at.timeframe_conflicts(settings),
        # counted here so the screen's caption cannot invent its own number
        "real_count": sum(1 for k in deployed if "real" in (books.get(k) or [])),
        "paper_count": sum(1 for k in deployed
                           if (books.get(k) or []) and "real" not in books[k]),
        "idle_count": sum(1 for k in deployed if not (books.get(k) or [])),
        "deployed_count": len(deployed),
        "catalog_count": len(at.STRATEGY_ORDER),
        "showing_catalog": catalog,
        # the account-wide breaker, and whether it has already fired today
        "account_loss_cap": float(settings.get("loss_limit") or 0.0),
        "account_cap_hit": at.loss_limit_hit(settings),
        "tripped": sorted(tripped),
        "locks": locks,
        # the ACCOUNT-WIDE default. Per-row sizing lives on each row now, so a
        # single flag here would contradict any row that overrides it.
        "flat": sizing_now == "flat",
        "leverage": at.LEVERAGE,
        "ladder_steps": list(at.LADDER),
    }


@app.post("/api/trade/strategies/backtest")
def strategy_backtest(body: dict) -> dict:
    """The '1 YEAR' button: replay one deployed strategy over a year.

    Detached, because the grid takes minutes — the caller polls
    /api/jobs/stratbt and opens the page when it lands.
    """
    import tradingagents.auto_trader as at
    from tradingagents import db_jobs

    key = str(body.get("key") or "")
    if key not in at.STRATEGY_SPECS:
        raise HTTPException(404, f"unknown strategy: {key}")
    settings = at.load_settings()
    coins = (body.get("coins")
             or (settings.get("strategy_coins") or {}).get(key) or [])
    if not coins:
        raise HTTPException(400, "this strategy has no contract selected")
    margin = float(body.get("base_margin")
                   or (settings.get("strategy_margins") or {}).get(key) or 5.0)
    return {"pid": db_jobs.start("stratbt", {
        "key": key, "label": body.get("label") or key, "coins": coins,
        "base_margin": margin, "days": int(body.get("days") or 365)})}


@app.get("/api/trade/settings")
def trade_settings_get() -> dict:
    import tradingagents.auto_trader as at

    return {"settings": at.load_settings()}


@app.post("/api/trade/settings")
def trade_settings_post(payload: dict) -> dict:
    """Save auto_trade.json. The deploy history records every change.

    A save that would put TWO strategies on one coin with real money at
    different timeframes is REFUSED, not warned about: MEXC nets them into
    one position, so the second entry resizes the first and either stop
    closes part of a trade it does not own.
    """
    import tradingagents.auto_trader as at

    locked = at.timeframe_locks(payload)
    books = payload.get("strategy_books") or {}
    clashing = {k: v for k, v in locked.items() if "real" in (books.get(k) or [])}
    if clashing:
        raise HTTPException(409, "; ".join(
            f"{k} cannot go live: {v['coin'].replace('_USDT', '')} is already "
            f"traded live by {v['held_by']} on another timeframe"
            for k, v in clashing.items()))
    changes = at.save_settings(payload)
    return {"ok": True, "changes_recorded": len(changes)}


@app.post("/api/trade/runner/start")
def runner_start() -> dict:
    import tradingagents.auto_trader as at

    return {"pid": at.start_runner()}


@app.post("/api/trade/runner/stop")
def runner_stop() -> dict:
    import tradingagents.auto_trader as at

    return {"stopped": at.stop_runner()}


@app.get("/api/trade/pnl/daily")
def trade_pnl_daily(dry: bool = False) -> dict:
    """Realized PnL per calendar day — the calendar view's data."""
    import tradingagents.auto_trader as at

    return {"days": at.daily_pnl(dry=dry)}


@app.get("/api/trade/pnl/by-coin")
def trade_pnl_by_coin(dry: bool = False) -> dict:
    import tradingagents.auto_trader as at

    return {"coins": at.coin_stats(dry=dry)}


@app.get("/api/trade/edge")
def trade_edge(key: str, symbol: str) -> dict:
    """The liquidity gate for one strategy/coin — block is block."""
    import tradingagents.auto_trader as at
    from tradingagents.dataflows import mexc_credentials as cred

    cred.load_into_env()
    return at.edge_check(key, symbol)


@app.get("/api/trade/log")
def trade_log(n: int = 200) -> dict:
    import tradingagents.auto_trader as at

    return {"lines": at.log_tail(max(1, min(n, 2000)))}


# ------------------------------------------------------------------- models
def _model_specs() -> dict:
    """Built-in models merged with the operator's own, from one place."""
    import app_models  # thin, import-safe catalog (no Streamlit)
    import model_registry
    from tradingagents.default_config import DEFAULT_CONFIG  # noqa: F401

    return model_registry.merged_models(app_models.MODELS)


@app.get("/api/models")
def models_list() -> dict:
    """The catalog: which are built in, which the operator added, and whether
    each one's key is present. The key VALUE never leaves this process."""
    import model_registry
    from tradingagents import model_health as mh

    custom = model_registry.load_custom()
    specs = _model_specs()
    rows = []
    for mid, spec in specs.items():
        rows.append({
            "id": mid,
            "label": spec.get("label"),
            "provider": spec.get("provider"),
            "base_url": spec.get("base_url"),
            "key_env": spec.get("key_env"),
            "key_present": mh.key_present(spec),
            "custom": mid in custom,
        })
    return {"rows": rows, "presets": list(model_registry.PROVIDER_PRESETS)}


class ModelAdd(BaseModel):
    model_id: str
    preset: str
    base_url: str = ""
    key_env: str = ""


@app.post("/api/models/add")
def models_add(body: ModelAdd) -> dict:
    import model_registry

    ok, msg = model_registry.add_model(body.model_id, body.preset,
                                      base_url=body.base_url,
                                      key_env=body.key_env)
    return {"ok": ok, "message": msg}


@app.post("/api/models/remove")
def models_remove(body: dict) -> dict:
    import model_registry

    mid = str(body.get("model_id") or "")
    return {"ok": model_registry.remove_model(mid)}


@app.post("/api/models/ping")
def models_ping(body: dict) -> dict:
    """Live-test one model against its own provider."""
    from tradingagents import model_health as mh

    mid = str(body.get("model_id") or "")
    spec = _model_specs().get(mid)
    if not spec:
        raise HTTPException(404, f"unknown model: {mid}")
    return {"model_id": mid, **mh.ping(mid, spec)}


# ------------------------------------------------------------- new listings
@app.get("/api/crypto/new")
def crypto_new(min_volume: float = 0.0, include_all: bool = False,
               min_age_hours: float = 0.0, max_age_hours: float | None = None,
               refresh: bool = False) -> dict:
    """Newly listed MEXC spot coins. Says what it could NOT resolve, and
    whether the answer came from cache — an empty table must never be
    mistaken for "no new coins" when the truth is "could not check"."""
    from tradingagents.dataflows import mexc

    r = mexc.screen_new_listings(min_quote_volume=min_volume,
                                 include_all=include_all,
                                 min_age_hours=min_age_hours,
                                 max_age_hours=max_age_hours,
                                 force_refresh=refresh)
    return {
        "rows": [{
            "symbol": c.symbol, "base": c.base, "name": c.name,
            "contract": c.contract, "listed_date": c.listed_date,
            "age_hours": round(c.age_hours, 2), "age_days": c.age_days,
            "price": c.price, "change_pct": round(c.change_pct, 2),
            "quote_volume": round(c.quote_volume, 2),
        } for c in r.coins],
        "scanned": r.scanned, "unresolved": r.unresolved,
        "hidden_by_volume": r.hidden_by_volume,
        "hidden_by_age": r.hidden_by_age,
        "fetched_at": r.fetched_at, "from_cache": r.from_cache,
        "stale": r.stale, "window_days": mexc.WINDOW_DAYS,
    }


@app.get("/api/crypto/upcoming")
def crypto_upcoming() -> dict:
    """Announced-but-not-trading listings, soonest first."""
    from tradingagents.dataflows import mexc

    try:
        rows = mexc.upcoming_listings()
    except Exception as exc:                                   # noqa: BLE001
        return {"rows": [], "why": f"{type(exc).__name__}: {exc}"}
    return {"rows": [{
        "symbol": r.get("symbol"), "base": r.get("base"),
        "name": r.get("name"), "open_ms": r.get("open_ms"),
        "hours_until": (round(r["hours_until"], 2)
                        if r.get("hours_until") is not None else None),
    } for r in rows]}


# --------------------------------------------------------------- grid math
@app.get("/api/backtest/plan")
def backtest_plan(coins: str = "", tfs: str = "") -> dict:
    """Say the cost BEFORE spending it: how many combinations this selection
    is, and roughly how long, from the real signal registry."""
    from tradingagents import backtest_report as br

    cl = [c for c in coins.split(",") if c]
    tl = [t for t in tfs.split(",") if t]
    n_sig = len(br.SIGNALS)
    per_tf = ((n_sig - len(br.THRESH_SIGNALS)) * 110 * 2
              + len(br.THRESH_SIGNALS) * 3 * 110 * 2)
    combos = per_tf * max(len(tl), 1) * max(len(cl), 1)
    # measured 2026-08-20: ~92s per coin for four timeframes, cache warm
    eta_s = 92 * max(len(cl), 1) * max(len(tl), 1) / 4
    return {"signals": n_sig, "barrier_pairs": 110, "sizings": 2,
            "coins": len(cl), "tfs": len(tl), "combinations": combos,
            "eta_minutes": round(eta_s / 60, 1),
            "note": "all three costs charged; liquidation modelled; every "
                    "live strategy on these coins/timeframes is marked "
                    "DEPLOYED"}


@app.get("/api/backtest/deployed")
def backtest_deployed(coins: str = "", tfs: str = "") -> dict:
    """The live rows to inject into a grid, so the operator's own config is
    always on the page (rule 21) even at barriers no round-number grid holds."""
    import tradingagents.auto_trader as at
    from tradingagents import strategy_report as sr

    settings = at.load_settings()
    books = settings.get("strategy_books") or {}
    scoins = settings.get("strategy_coins") or {}
    sizing = at.sizing_for(settings)
    want_c = {c for c in coins.split(",") if c}
    want_t = {t for t in tfs.split(",") if t}
    out = []
    for key, bk in books.items():
        if not bk:
            continue
        spec = at.STRATEGY_SPECS.get(key) or {}
        tf = sr.TF_NAME.get(spec.get("interval"))
        if want_t and tf not in want_t:
            continue
        signal = key.split("_")[1] if key.startswith("ict_") else key.split("_")[0]
        for c in scoins.get(key) or []:
            if want_c and c not in want_c:
                continue
            out.append({"coin": c.replace("_USDT", ""), "tf": tf,
                        "signal": signal,
                        "th": round(float(spec.get("threshold") or 0) * 100, 3),
                        "sl": round(float(spec.get("sl", 0)) * 100, 3),
                        "tp": round(float(spec.get("tp", 0)) * 100, 3),
                        "sizing": sizing, "key": key})
    return {"rows": out}


# ---------------------------------------------------------------- analysis
@app.get("/api/analysis/runs")
def analysis_runs(limit: int = 25) -> dict:
    from tradingagents import analysis_jobs as aj

    return {"rows": aj.runs(limit)}


@app.post("/api/analysis/start")
def analysis_start(spec: dict) -> dict:
    """Start one run, or one per model when `models` is given.

    Parallel is not a nicety: each model runs on ITS OWN provider, so mixing
    them spends separate rate-limit quotas and the calls can be compared on
    the same ticker and date.
    """
    from tradingagents import analysis_jobs as aj

    if not str(spec.get("ticker") or "").strip():
        raise HTTPException(400, "a ticker is required")
    if not str(spec.get("trade_date") or "").strip():
        raise HTTPException(400, "a trade date is required")
    models = [m for m in (spec.get("models") or []) if m]
    if not models:
        one = aj.start(spec)
        return {"run_id": one, "run_ids": [{"model": spec.get("model"),
                                            "run_id": one}]}
    runs = []
    for m in models:
        one = {k: v for k, v in spec.items() if k != "models"}
        one["model"] = m
        runs.append({"model": m, "run_id": aj.start(one)})
    return {"run_ids": runs, "run_id": runs[0]["run_id"]}


# NOTE: every STATIC /api/analysis/... path must be declared
# above this one. FastAPI matches in order, so a route added
# below it is swallowed by {run_id} — /api/analysis/tickers
# returned {'error': 'no such run', 'run_id': 'tickers'}.
@app.get("/api/analysis/tickers")
def analysis_tickers() -> dict:
    """The curated ticker list, with company names. Free text still works —
    this is a shortcut, not a restriction (Yahoo covers tens of thousands)."""
    import tickers

    return {"rows": [{"symbol": s, "name": n} for s, n in tickers.TICKERS.items()]}


@app.get("/api/analysis/{run_id}")
def analysis_status(run_id: str) -> dict:
    from tradingagents import analysis_jobs as aj

    return aj.status(run_id)


@app.post("/api/analysis/{run_id}/stop")
def analysis_stop(run_id: str) -> dict:
    from tradingagents import analysis_jobs as aj

    return {"stopped": aj.stop(run_id)}


@app.get("/api/analysis/social/sources")
def analysis_social_sources() -> dict:
    """Which social sources the Sentiment Analyst can read, and whether X is
    actually usable — X is metered and needs TWITTERAPI_IO_KEY, so the screen
    must be able to say "you picked X but there is no key" BEFORE a run."""
    import os

    from tradingagents import analysis_jobs as aj

    return {
        "sources": [
            {"id": "stocktwits", "label": "StockTwits only",
             "note": "free, keyless, carries Bullish/Bearish tags"},
            {"id": "twitter", "label": "X / Twitter only",
             "note": "metered — spends TwitterAPI.io credits"},
            {"id": "both", "label": "Both",
             "note": "StockTwits plus X — spends credits"},
        ],
        "default": aj.DEFAULT_SOCIAL,
        "x_key_present": bool(os.environ.get("TWITTERAPI_IO_KEY", "").strip()),
        "x_key_env": "TWITTERAPI_IO_KEY",
    }


@app.post("/api/trade/halt")
def trade_halt(body: dict) -> dict:
    """Halt entries, or clear the halt. The kill file blocks NEW entries; open
    positions keep their exchange-side brackets and their own exits."""
    import tradingagents.auto_trader as at

    if bool(body.get("halt", True)):
        at.KILL_PATH.parent.mkdir(parents=True, exist_ok=True)
        at.KILL_PATH.write_text("halted from the UI", encoding="utf-8")
    else:
        at.KILL_PATH.unlink(missing_ok=True)
    return {"halted": at.halted()}


# ------------------------------------------------------------- credentials
@app.get("/api/trade/credentials")
def credentials_status() -> dict:
    """Where the active MEXC keys came from — masked fingerprints only.

    cred.status() is built to be renderable: it returns no secret material,
    so this route cannot leak one. The canary test proves it.
    """
    from tradingagents.dataflows import mexc_credentials as cred

    cred.load_into_env()
    got = dict(cred.status())
    got["env_conflict"] = cred.env_conflict()
    return got


@app.post("/api/trade/credentials")
def credentials_save(body: dict) -> dict:
    """Store a key pair on this Mac at mode 0600, then reload the env."""
    from tradingagents.dataflows import mexc_credentials as cred

    key = str(body.get("api_key") or "").strip()
    secret = str(body.get("api_secret") or "").strip()
    if not key or not secret:
        raise HTTPException(400, "both an api key and a secret are required")
    cred.save(key, secret)
    cred.load_into_env()
    return {"saved": True, **credentials_status()}


@app.post("/api/trade/credentials/forget")
def credentials_forget() -> dict:
    """Delete the stored pair. A shell-supplied key still applies."""
    from tradingagents.dataflows import mexc_credentials as cred

    return {"cleared": cred.clear(), **credentials_status()}


@app.post("/api/trade/credentials/test")
def credentials_test(body: dict) -> dict:
    """What this key can actually DO — read, order, and rest a stop.

    'The request was sent' is not 'it is in place' (rule 14), so the probe
    checks resting a stop, not just reading a balance.
    """
    from tradingagents.dataflows import mexc_credentials as cred, mexc_futures as fx

    cred.load_into_env()
    symbol = str(body.get("symbol") or "BTC_USDT").strip()
    return fx.preflight(symbol)


# ------------------------------------------------------------ cloud sweeps
@app.get("/api/cloud/status")
def cloud_status() -> dict:
    """Whether GitHub Actions can be used, and what the remembered run is
    doing — per machine, not just "20 running", which told the operator
    nothing (2026-08-20)."""
    from tradingagents import cloud_sweep as cs

    ok, why = cs.available()
    out = {"available": ok, "why": why, "run": None, "shards": []}
    run = cs.remembered()
    if run and run.get("id"):
        out["run"] = run
        try:
            out.update(cs.status(int(run["id"])))
        except Exception as exc:                               # noqa: BLE001
            out["why"] = f"{type(exc).__name__}: {exc}"
        try:
            out["shards"] = cs.live_progress(int(run["id"]))
        except Exception:
            out["shards"] = []
    return out


@app.post("/api/cloud/dispatch")
def cloud_dispatch(body: dict) -> dict:
    """Run the same grid on GitHub's machines. Their rows land in an artifact
    that must be MERGED into this Mac's store — nothing is written remotely."""
    from tradingagents import cloud_sweep as cs

    ok, why = cs.available()
    if not ok:
        raise HTTPException(400, why)
    run = cs.dispatch(shards=int(body.get("shards") or 20),
                      coins=int(body.get("coins") or 0),
                      timeframes=str(body.get("timeframes") or "15m,30m"),
                      min_days=int(body.get("min_days") or 0),
                      days=int(body.get("days") or 365))
    cs.remember(run)
    return run


@app.post("/api/cloud/cancel")
def cloud_cancel(body: dict) -> dict:
    from tradingagents import cloud_sweep as cs

    run_id = int(body.get("run_id") or 0)
    if not run_id:
        raise HTTPException(400, "a run id is required")
    cs.cancel(run_id)
    return {"cancelled": run_id}


@app.post("/api/cloud/merge")
def cloud_merge(body: dict) -> dict:
    """Pull a finished run's rows into THIS Mac's store."""
    from tradingagents import cloud_sweep as cs

    run_id = int(body.get("run_id") or 0)
    if not run_id:
        raise HTTPException(400, "a run id is required")
    # `collect_into_store`, never `fetch`. Two reasons, both paid for:
    #
    # * fetch() asks for ONE artifact named "sweep-results", which the
    #   workflow's merge job stopped producing after it was OOM-killed
    #   concatenating 29.7 million rows on a 7 GB runner. Run 33636672697
    #   produced rows-0..rows-19 (~300 MB each) and this route answered
    #   HTTP 500 `no artifact matches any of the names or patterns provided`
    #   (2026-09-03) — 82.7 million measured rows sitting in artifacts the
    #   route would not look at.
    # * fetch() also builds one Python list of every row, which is the same
    #   MemoryError that killed the 5:20am grid on 2026-08-26.
    #
    # collect_into_store prefers the per-shard artifacts (they ARE the
    # measurement; the merge job only concatenates them), streams each file a
    # line at a time, and REFUSES to overwrite a pair this machine has already
    # measured — its watermark promises every bar up to X was tested.
    got = cs.collect_into_store(run_id)
    return {"fetched": got.get("rows", 0), **got}


@app.post("/api/cloud/forget")
def cloud_forget() -> dict:
    from tradingagents import cloud_sweep as cs

    cs.forget()
    return {"forgotten": True}


@app.get("/api/analysis/{run_id}/report.md")
def analysis_report_md(run_id: str):
    """The whole run as one markdown file — every section, then the decision.

    A browser download link, because the operator's own copy of a run should
    not live only inside a web page.
    """
    from fastapi.responses import PlainTextResponse

    from tradingagents import analysis_jobs as aj

    got = aj.status(run_id)
    if got.get("error") == "no such run":
        raise HTTPException(404, f"no such run: {run_id}")
    spec = got.get("spec") or {}
    head = [f"# {spec.get('ticker', run_id)} · {spec.get('trade_date', '')}",
            "",
            f"- run: `{run_id}`",
            f"- model: {spec.get('model')}",
            f"- analysts: {', '.join(spec.get('analysts') or [])}",
            f"- social source: {spec.get('social_source') or 'stocktwits'}"]
    if spec.get("twitter_keywords"):
        head.append(f"- extra X terms: {', '.join(spec['twitter_keywords'])}")
    head += ["", "---", ""]
    body = []
    for label, text in (got.get("reports") or {}).items():
        body += [f"## {label}", "", str(text), ""]
    if got.get("decision"):
        body += ["## Final decision", "", str(got["decision"]), ""]
    md = "\n".join(head + body)
    return PlainTextResponse(md, media_type="text/markdown", headers={
        "Content-Disposition": f'attachment; filename="{run_id}.md"'})


@app.post("/api/crypto/watch")
def crypto_watch(body: dict) -> dict:
    """One watch tick: which coins are new since the caller's baseline.

    Deliberately stateless — the browser holds the baseline and posts it back,
    so two open tabs cannot silence each other, and a restarted API does not
    replay yesterday's listings as new. An EMPTY baseline seeds and reports
    nothing, or the first tick would announce the whole exchange.
    """
    from tradingagents.dataflows import mexc

    known = set(body.get("known") or [])
    try:
        found, seen = mexc.poll_new_listings(
            known, max_age_hours=float(body.get("max_age_hours") or 48.0))
    except Exception as exc:                                   # noqa: BLE001
        return {"found": [], "known": sorted(known), "seeded": False,
                "why": f"{type(exc).__name__}: {exc}"}
    merged = mexc.merge_new_listings(found) if found else 0
    return {"found": found, "known": sorted(seen), "seeded": not known,
            "merged_into_sweep": merged, "why": ""}


@app.get("/api/crypto/candles")
def crypto_candles(symbol: str, interval: str = "Min60",
                   limit: int = 200) -> dict:
    """Candles for one contract, for the in-page chart."""
    from tradingagents.dataflows import mexc_futures as fx

    try:
        df = fx.klines(symbol, interval, max(10, min(limit, 1000)))
    except Exception as exc:                                   # noqa: BLE001
        raise HTTPException(502, f"{type(exc).__name__}: {exc}") from exc
    if df is None or not len(df):
        return {"rows": [], "symbol": symbol, "interval": interval}
    rows = [{"t": int(d.value // 1_000_000), "o": float(o), "h": float(h),
             "l": float(low), "c": float(c), "v": float(v)}
            for d, o, h, low, c, v in zip(df["Date"], df["Open"], df["High"],
                                          df["Low"], df["Close"], df["Volume"], strict=False)]
    return {"rows": rows, "symbol": symbol, "interval": interval}


def _fmt_held(secs) -> str:
    """How long a trade was held, from the seconds the ledger stores."""
    if not secs:
        return "—"
    s = int(secs)
    if s >= 86400:
        return f"{s / 86400:.1f}d"
    if s >= 3600:
        return f"{s // 3600}h {round((s % 3600) / 60)}m"
    return f"{max(1, round(s / 60))}m"


@app.get("/api/trade/history")
def trade_history(dry: bool = False, per_page: int = 5, page: int = 1) -> dict:
    """Every CLOSED trade on one book, newest first, with its running total —
    plus a per-month summary the page cannot give.

    Paginated because a wall of 200 rows hides a trade as effectively as a net
    figure does. The running total is computed oldest-first over the WHOLE
    book, so page 3's 'running $' is the real running total, not the page's.
    """
    import datetime as dt

    import tradingagents.auto_trader as at
    from tradingagents import positions_view as pv

    _all = at.ledger_tail(100000)
    ex = [e for e in _all
          if e.get("action") == "exit" and bool(e.get("dry_run")) is dry]
    ex.sort(key=lambda x: float(x.get("ts") or 0))

    # Exit rows written before 2026-08-21 carry no side, so the LONG/SHORT
    # column printed "-" for every closed trade. Pair each exit with the most
    # recent ENTER on the same symbol and book that precedes it, and take the
    # side from there. New exits record their own side; this is only for the
    # history already on disk.
    _entries: dict = {}
    for e in sorted(_all, key=lambda x: float(x.get("ts") or 0)):
        if e.get("action") != "enter":
            continue
        _entries.setdefault(
            (str(e.get("symbol")), bool(e.get("dry_run"))), []
        ).append(e)

    def _side_for(row: dict) -> str:
        if row.get("side"):
            return str(row["side"])
        cands = _entries.get((str(row.get("symbol")),
                              bool(row.get("dry_run")))) or []
        ts = float(row.get("ts") or 0)
        prior = [c for c in cands if float(c.get("ts") or 0) <= ts]
        if not prior:
            return "—"
        return str(prior[-1].get("side") or "—")
    run, rows, months = 0.0, [], {}
    for e in ex:
        p = round(float(e.get("pnl_est") or 0), 2)
        run = round(run + p, 2)
        # The trade's own id and opening time, stored on the ledger row since
        # 2026-08-22 (auto_trader.trade_code + backfill_ledger_ids). "—" only
        # for the handful of old exits whose entry predates the ledger: an
        # invented timestamp would be worse than an honest dash.
        _op = e.get("opened_at")
        _hs = e.get("held_s")
        rows.append({
            "ts": float(e.get("ts") or 0),
            "id": e.get("trade_id") or "—",
            "opened": pv.fmt_when(float(_op)) if _op else "—",
            "held": _fmt_held(_hs),
            "when": pv.fmt_when(float(e.get("ts") or 0)),
            "coin": str(e.get("symbol", "?")).replace("_USDT", ""),
            "side": _side_for(e),
            "strategy": e.get("strategy") or "—",
            "why": e.get("why") or "—",
            "profit": p, "running": run})
        key = dt.datetime.fromtimestamp(float(e.get("ts") or 0)).strftime("%Y-%m")
        m = months.setdefault(key, {"key": key, "trades": 0, "wins": 0,
                                    "losses": 0, "profit": 0.0})
        m["trades"] += 1
        m["wins" if p > 0 else "losses"] += 1
        m["profit"] = round(m["profit"] + p, 2)
    rows.reverse()                                   # newest first
    per = max(1, min(per_page, 100))
    pages = max(1, -(-len(rows) // per))
    page = max(1, min(page, pages))
    mrows = sorted(months.values(), key=lambda m: m["key"], reverse=True)
    for m in mrows:
        m["win_rate"] = round(100 * m["wins"] / m["trades"], 1) if m["trades"] else 0.0
        m["label"] = dt.datetime.strptime(m["key"], "%Y-%m").strftime("%b %Y")
    return {
        "rows": rows[(page - 1) * per:page * per],
        "total": len(rows), "page": page, "pages": pages, "per_page": per,
        "months": mrows,
        "totals": {"trades": sum(m["trades"] for m in mrows),
                   "wins": sum(m["wins"] for m in mrows),
                   "losses": sum(m["losses"] for m in mrows),
                   "profit": round(sum(m["profit"] for m in mrows), 2)},
    }


@app.get("/api/contracts")
def contracts() -> dict:
    """Every tradeable MEXC USDT perpetual, for the coin pickers."""
    from tradingagents.dataflows import mexc_futures as fx

    try:
        rows = fx.list_contracts()
    except Exception as exc:                                   # noqa: BLE001
        return {"rows": [], "why": f"{type(exc).__name__}: {exc}"}
    return {"rows": sorted({str(c.get("symbol")) for c in rows if c.get("symbol")}),
            "why": ""}


@app.get("/api/trade/equity")
def trade_equity(dry: bool = False) -> dict:
    """Cumulative realised PnL per closed trade — the equity curve.

    Built from the ledger's own exit rows, the same rows every other figure on
    the screen reads, so the curve cannot disagree with the totals beside it.
    """
    import tradingagents.auto_trader as at

    out, run = [], 0.0
    for e in at.ledger_since(0):
        if e.get("action") != "exit" or bool(e.get("dry_run")) is not dry:
            continue
        run = round(run + float(e.get("pnl_est") or 0), 2)
        out.append({"ts": float(e.get("ts") or 0), "equity": run,
                    "coin": str(e.get("symbol", "")).replace("_USDT", "")})
    return {"points": out, "last": out[-1]["equity"] if out else 0.0,
            "trades": len(out)}


# ----------------------------------------------------------- candle gaps
_GAP_CACHE: dict = {"at": 0.0, "payload": None, "building": False}


def _warm_gap_index() -> None:
    """Build the candle index off the request thread.

    A first build opens every stored pair (69s at 4,899 pairs) and would hold
    a request open past the UI proxy's timeout — so the route answers
    "indexing" and this fills it in.
    """
    import threading

    from tradingagents import market_sweep as msw

    if _GAP_CACHE["building"]:
        return
    _GAP_CACHE["building"] = True

    def run() -> None:
        try:
            msw.candle_index()
        finally:
            _GAP_CACHE["building"] = False
            _GAP_CACHE["at"] = 0.0          # let the next call read it

    threading.Thread(target=run, daemon=True).start()


@app.get("/api/candles/gaps")
def candle_gaps() -> dict:
    """How far behind every stored pair is, so UPDATE can say what it fills.

    Nothing is fetched here — it reads the store's own last bar. A pair is
    "behind" when more than one bar could have printed since.
    """
    import time

    from tradingagents import backtest_report as br, market_sweep as msw, positions_view as pv

    # the scan opens one file per stored pair (4,899 today), so a repeat call
    # inside 30s gets the same answer rather than the same work
    now = time.time()
    if _GAP_CACHE["payload"] and now - _GAP_CACHE["at"] < 30:
        return _GAP_CACHE["payload"]
    # never scan on a request thread: with a download running the files change
    # constantly, so even an incremental scan can outlast the proxy's timeout
    _warm_gap_index()
    index = msw.candle_index(scan=False)
    if not index:
        return {"rows": [], "pairs": 0, "behind": 0, "worst": None,
                "indexing": True}
    rows, behind = [], 0
    for c in index.values():
        tf = c.get("timeframe")
        bs = (br.TFS.get(tf) or (None, 3600, None))[1]
        last = int(c["last_ms"]) / 1000
        missing = max(0, int((now - last) // bs))
        if missing > 1:
            behind += 1
        rows.append({"symbol": c.get("symbol"), "timeframe": tf,
                     "bars": c.get("bars"),
                     "last": pv.fmt_when(last),
                     "missing_bars": missing,
                     "hours_behind": round((now - last) / 3600, 1)})
    rows.sort(key=lambda r: -r["missing_bars"])
    # A pair the venue no longer lists can never catch up, so counting it in
    # "N behind" makes that number unreachable and pins "furthest behind" on a
    # contract nothing can fetch — MEZO 15m at 50.4 h, for ever. Named
    # separately instead (review, 2026-08-27).
    from tradingagents import db_jobs as dj

    live = dj.live_symbols()
    dead = [r for r in rows if dj.is_delisted(r["symbol"], live)]
    gone_keys = {(r["symbol"], r["timeframe"]) for r in dead}
    live_rows = [r for r in rows if (r["symbol"], r["timeframe"]) not in gone_keys]
    behind = sum(1 for r in live_rows if r["missing_bars"] > 1)
    payload = {"rows": live_rows[:200], "pairs": len(rows), "behind": behind,
               "worst": live_rows[0] if live_rows else None, "indexing": False,
               # what UPDATE cannot fix however often it runs
               "delisted": [{"symbol": r["symbol"], "timeframe": r["timeframe"],
                             "hours_behind": r["hours_behind"]} for r in dead],
               "delisted_count": len(dead)}
    _GAP_CACHE.update({"at": now, "payload": payload})
    return payload


# ------------------------------------------------------------- notifications
# One bell for "did the thing I clicked actually work". A click that reports
# nothing is indistinguishable from a click that failed silently — which is
# exactly how a 0-byte backtest report went unnoticed on 2026-08-20.
@app.get("/api/notifications")
def notifications_list(limit: int = 30, kind: str | None = None,
                       unread: bool = False) -> dict:
    """Newest first, with the unread count for the badge."""
    from tradingagents import notifications as nt, positions_view as pv

    rows = nt.recent(limit=limit, kind=kind, unread_only=unread)
    for r in rows:
        r["when"] = pv.fmt_when(float(r.get("ts") or 0))
        # a failed download that has since been made whole says so, measured
        # against the store — the 2:00pm row on 2026-08-25 read as live for
        # an hour after both its pairs were back
        r["resolved"], r["resolved_why"] = _download_resolution(r)
    return {"rows": rows, "unread": nt.unread_count(), "total": len(rows)}


class NotifyRead(BaseModel):
    ids: list[int] | None = None


@app.post("/api/notifications/read")
def notifications_read(body: NotifyRead) -> dict:
    """Mark the given ids read, or every unread event when ids is omitted."""
    from tradingagents import notifications as nt

    changed = nt.mark_read(body.ids)
    return {"marked": changed, "unread": nt.unread_count()}


_LOST_PAIR_RE = re.compile(r"([A-Z0-9]+_USDT) (15m|30m|1h|4h|1d):")


def _named_lost(row: dict) -> tuple[list[tuple[str, str]], int]:
    """The pairs a download event names as lost, and how many of its errors it
    did NOT name. Rows written after 2026-08-25 carry every pair in
    meta.failed; the 2:00pm row that day carried only errors[0] in its detail,
    so its second lost pair (NAORIS_USDT 30m) is an unnamed count, not a name.
    """
    meta = row.get("meta") or {}
    texts = meta.get("failed")
    if texts is None:
        texts = [row.get("detail") or ""]
    pairs: list[tuple[str, str]] = []
    for text in texts:
        for sym, tf in _LOST_PAIR_RE.findall(text):
            if (sym, tf) not in pairs:
                pairs.append((sym, tf))
    return pairs, max(0, int(meta.get("errors") or 0) - len(pairs))


_EMPTY_HISTORY = None            # compiled on first use, below


def _serves_nothing(symbol: str, tf: str, texts) -> bool:
    """Did the run say the venue has NO candles for this pair?

    "no Min15 candles for AJINOMOTOSTOCK_USDT" is the venue answering with an
    empty list, which a retry repeats exactly. A cut connection or a truncated
    body is a different thing and IS worth retrying, so the two must not be
    counted together.
    """
    import re

    global _EMPTY_HISTORY
    if _EMPTY_HISTORY is None:
        _EMPTY_HISTORY = re.compile(
            r"no (?:Min\d+|Hour\d+|Day\d+) candles for", re.I)
    want = f"{symbol} {tf}:"
    for text in texts or ():
        if str(text).startswith(want) and _EMPTY_HISTORY.search(str(text)):
            return True
    return False


def _lost_kind(got: dict, symbol: str, tf: str, texts=None) -> str:
    """One word for why a pair is on the lost list — see _serves_nothing."""
    if got.get("recovered"):
        return "recovered"
    if got.get("delisted"):
        return "delisted"
    if _serves_nothing(symbol, tf, texts):
        return "empty"
    return "retry"


def _stored_now(symbol: str, tf: str, since: float, live=None) -> dict:
    """Is the pair in the store, fetched SINCE `since` — from its file, never a
    flag.

    `since` is REQUIRED, not defaulted: a default is exactly what let two of
    the three call sites keep printing the old lie after the third was fixed
    (found in review, 2026-08-27).

    It is what makes this honest. It used to mean only "a parquet exists",
    so a retry that stored ZERO bars still read *"resolved — every pair that run
    lost is back in the store"*: MEZO's file had been sitting there since
    Aug 25, 1:22pm while the 2:43pm retry failed four times (operator's
    screenshot, 2026-08-27). A file older than the run that lost the pair is
    not a recovery.

    `delisted` rides beside it: a contract MEXC no longer lists can never be
    fetched by any run, so it is neither lost nor recovered — it is gone, and
    saying so is the only thing that lets the panel go green.
    """
    from tradingagents import db_jobs as dj, parquet_store as pqs, \
        positions_view as pv

    path = pqs._candle_path(symbol, tf)
    out = {"symbol": symbol, "timeframe": tf, "recovered": False,
           "bars": None, "when": "", "exists": False,
           "delisted": dj.is_delisted(symbol, live)}
    if not path.exists():
        return out
    try:
        import pyarrow.parquet as pq

        out["bars"] = int(pq.read_metadata(path).num_rows)
    except Exception:
        out["bars"] = None
    mtime = path.stat().st_mtime
    out.update(exists=True, when=pv.fmt_when(mtime),
               recovered=mtime > float(since or 0.0))
    return out


_TFS = ("15m", "30m", "1h", "4h", "1d")
_COMPLETENESS_CACHE: dict = {"at": 0.0, "payload": None}


def _store_completeness() -> dict:
    """Every contract MEXC lists x the five timeframes, against the store's
    own files. "Is the candles complete now?" answered by counting, not by
    the absence of a red row. Cached 5 minutes (30 s after a failure): the
    bell polls this through every download row, and list_contracts is a
    request to the venue.
    """
    import time as _t

    from tradingagents import parquet_store as pqs
    from tradingagents.dataflows import mexc_futures as fx

    now = _t.time()
    c = _COMPLETENESS_CACHE
    if c["payload"] is not None and now - c["at"] < 300:
        return c["payload"]
    try:
        contracts = [r["symbol"] for r in fx.list_contracts()]
    except Exception as exc:
        payload = {"ok": False, "why": f"could not list MEXC contracts: {str(exc)[:80]}",
                   "contracts": None, "wanted": None, "stored": None,
                   "missing": [], "complete": None}
        c.update(at=now - 270, payload=payload)
        return payload
    have = ({p.stem for p in pqs.CANDLES.glob("*.parquet")}
            if pqs.CANDLES.exists() else set())
    wanted = [(sym, tf) for sym in contracts for tf in _TFS]
    missing = [{"symbol": sym, "timeframe": tf}
               for sym, tf in wanted if f"{sym}-{tf}" not in have]
    payload = {"ok": True, "why": "", "contracts": len(contracts),
               "wanted": len(wanted), "stored": len(wanted) - len(missing),
               "missing": missing, "complete": not missing}
    c.update(at=now, payload=payload)
    return payload


def _download_resolution(row: dict) -> tuple[bool | None, str]:
    """Is a FAILED download event still live? (None, "") when there is nothing
    to resolve. Resolved means every pair the run NAMED is in the store and,
    for the errors it did not name, the store is complete — measured, so a
    2:00pm failure stops reading as live only once the files exist.
    """
    from tradingagents import db_jobs

    meta = row.get("meta") or {}
    if row.get("ok") or meta.get("stopped") or row.get("kind") != "download":
        return None, ""
    named, unnamed = _named_lost(row)
    when = float(row.get("ts") or 0)
    gone, still = [], []
    live = db_jobs.live_symbols() if named else None   # one lookup per row
    for sym, tf in named:
        got = _stored_now(sym, tf, since=when, live=live)
        if got["delisted"]:
            gone.append(f"{sym.replace('_USDT', '')} {tf}")
        elif not got["recovered"]:
            # `bars` is None when the parquet's metadata cannot be read — a
            # truncated or half-written file. `f"{None:,}"` RAISES, which would
            # 500 this route on exactly the store that needs explaining.
            bars = (f"{got['bars']:,} bars" if isinstance(got["bars"], int)
                    else "unreadable")
            still.append(f"{sym.replace('_USDT', '')} {tf}"
                         + (f" (store has {bars} from {got['when']}, older "
                            f"than this run)" if got["exists"] else " (no file)"))
    if still:
        return False, "still lost: " + ", ".join(still)
    if gone and not unnamed:
        # nothing can fetch a contract the venue dropped, so this row is as
        # resolved as it will ever be — and it says WHY rather than pretending
        return True, ("resolved — " + ", ".join(gone)
                      + f" {'is' if len(gone) == 1 else 'are'} DELISTED on "
                        f"MEXC and cannot be fetched by any run")
    if unnamed:
        comp = _store_completeness()
        if not comp["ok"]:
            return False, f"{unnamed} pair(s) that run did not name — {comp['why']}"
        if not comp["complete"]:
            return False, (f"{unnamed} pair(s) that run did not name — the store is "
                           f"missing {len(comp['missing'])} of {comp['wanted']:,} pairs")
        return True, (f"resolved — the store holds all {comp['wanted']:,} pairs "
                      f"({comp['contracts']} contracts × 5 timeframes)")
    return True, "resolved — every pair that run lost is back in the store"


@app.get("/api/candles/completeness")
def candles_completeness() -> dict:
    """Contracts on MEXC x five timeframes vs the store — the whole answer to
    "is the candles complete now?", with the missing pairs named."""
    return _store_completeness()


@app.get("/api/candles/lost")
def candles_lost() -> dict:
    """The pairs the last download gave up on — what RETRY FAILED will fetch.

    Read from the job's own lost file, so the button's count IS the retry's
    list, never a second bookkeeping of it. No file means nothing is lost.

    Plus what the LAST FAILED run lost and whether it is back: on 2026-08-25
    the operator read a 2:00pm "2 error(s)" row an hour after both pairs had
    been re-downloaded, saw a disabled RETRY button, and called it "still
    error". The button was right and the screen never said why.
    """
    from tradingagents import db_jobs, notifications as nt, positions_view as pv

    got = db_jobs._read(db_jobs.FILES["download"]["lost"])
    all_pairs = [(p[0], p[1]) for p in (got.get("pairs") or []) if len(p) == 2]
    # Which of the lost pairs the venue no longer lists — NAMED, still offered.
    # One retry attempts them, the download loop classifies them on the venue's
    # own answer (db_jobs.looks_gone AND is_delisted, two facts) and clears them
    # out of lost.json for good. Removing them here would leave them in that
    # file for ever with no button able to clear it, and would let a filtered,
    # cached contract list delete work that was never attempted.
    live = db_jobs.live_symbols()          # one lookup for the whole route
    delisted = [{"symbol": s_, "timeframe": t_} for s_, t_ in all_pairs
                if db_jobs.is_delisted(s_, live)]
    # WHY each one is lost, so "26 pairs still lost" stops reading as 26
    # things to do when 25 of them are the venue serving no candles at all
    # (operator, 2026-09-02: "i dont know if there are still errors or not").
    # Measured against the RUN THAT LOST THEM, never against "a file exists".
    # ENPHSTOCK 1d has a parquet from Aug 26 and its Sep 02 fetch failed; with
    # `since=0` that read as "recovered", which is the exact lie _stored_now's
    # own docstring was written about. Older than the run = still lost.
    _texts: list = []
    _since = 0.0
    for _row in nt.recent(limit=20, kind="download"):
        _meta = _row.get("meta") or {}
        if _row.get("ok") or _meta.get("stopped"):
            continue
        _texts = _meta.get("failed") or []
        _since = float(_row.get("ts") or 0)
        break
    pairs = []
    for s_, t_ in all_pairs:
        # NOT `got`: that name already holds the lost FILE in this function,
        # and shadowing it blanked the "written" stamp the panel prints
        # ("lost by the last download (Sep 02, 2026 4:10pm)").
        state = _stored_now(s_, t_, since=_since, live=live)
        pairs.append({"symbol": s_, "timeframe": t_,
                      "kind": _lost_kind(state, s_, t_, _texts)})
    recovered, failed_when, unnamed = [], "", 0
    for row in nt.recent(limit=20, kind="download"):
        meta = row.get("meta") or {}
        if row.get("ok") or meta.get("stopped"):
            continue
        named, unnamed = _named_lost(row)
        when = float(row.get("ts") or 0)
        failed_when = pv.fmt_when(when)
        # measured against the RUN that lost them, and a contract the venue
        # dropped is never "recovered" — it belongs in the delisted line. Both
        # were wrong here until review caught it: the screen printed "MEZO 15m
        # (14,030 bars, stored Aug 26 1:22am)" as recovered for a run that
        # failed on Aug 28 at 2:43am.
        recovered = [{"symbol": r["symbol"], "timeframe": r["timeframe"],
                      "bars": r["bars"], "when": r["when"]}
                     for r in (_stored_now(sym, tf, since=when)
                               for sym, tf in named)
                     if r["recovered"] and not r["delisted"]]
        break
    return {"pairs": pairs, "count": len(pairs),
            "written": pv.fmt_when(float(got["written"])) if got.get("written") else "",
            "recovered": recovered, "failed_run_when": failed_when,
            "unnamed": unnamed,
            # named so the screen can say "2 delisted — nothing to retry"
            "delisted": delisted, "delisted_count": len(delisted)}


@app.get("/api/candles/download-history")
def _lost_kind_on(got: dict, symbol: str, tf: str, texts=None) -> dict:
    """`_stored_now` plus the one word for WHY (see _lost_kind)."""
    got["kind"] = _lost_kind(got, symbol, tf, texts)
    return got


def download_history(limit: int = 20) -> dict:
    """Every download this machine has run, newest first, with its outcome.

    The operator asked to see whether a DOWNLOAD succeeded. The job's progress
    file only holds the LAST run, so the history comes from the event store.
    """
    from tradingagents import notifications as nt, positions_view as pv

    rows = nt.recent(limit=limit, kind="download")
    out = []
    for r in rows:
        m = r.get("meta") or {}
        named, unnamed = _named_lost(r)
        out.append({
            "ts": r["ts"], "when": pv.fmt_when(float(r.get("ts") or 0)),
            "ok": r["ok"], "title": r["title"], "detail": r["detail"],
            "pairs": m.get("pairs"), "bars": m.get("bars"),
            "errors": m.get("errors"), "stopped": bool(m.get("stopped")),
            "mode": m.get("mode") or "download",
            # a FAILED row says whether its lost pairs are back — from the
            # store's own files, so a fixed failure never reads as a live one
            # since= the run's own time: a file older than the run is not a
            # recovery, and `delisted` rides along so the row cannot call a
            # dropped contract "recovered" (review, 2026-08-27)
            # `kind` per pair, so the screen can tell a delisted contract
            # (nothing to do) from one a retry would fetch. Without it the
            # panel drew both in red and a row could read
            # "FAILED - RESOLVED" beside "4 pairs still lost".
            "lost": [_lost_kind_on(_stored_now(sym, tf,
                                               since=float(r.get("ts") or 0)),
                                   sym, tf, m.get("failed"))
                     for sym, tf in named],
            "unnamed": unnamed,
        })
        out[-1]["resolved"], out[-1]["resolved_why"] = _download_resolution(r)
    ok = sum(1 for r in out if r["ok"])
    return {"rows": out, "total": len(out), "ok": ok, "failed": len(out) - ok}


# ------------------------------------------------------------ backtest store
@app.get("/api/backtest/storage")
def backtest_storage() -> dict:
    """What the MEASURED grid costs and how current it is, per coin/timeframe.

    Two different "last updated" figures, because they answer different
    questions and conflating them hides a stale pair:

    * ``measured_through`` — the last CANDLE the grid was tested against
      (``__last_ms__``). This is the honest freshness marker: a pair rewritten
      with no new bars is not more current than it was.
    * ``last_run`` — when the row file was last written. A pair can have been
      re-run recently and still be measured through an old bar.
    """

    from tradingagents import positions_view as pv, rows_index as ri

    # From the INDEX. This route used to parse every row file and every state
    # file — over 2 GB, measured 2026-08-22 — and the Backtest screen polls it,
    # which is why /api/health and /api/strategies queued behind it and the
    # header chip printed "API unreachable".
    rows = []
    for r in ri.pair_storage():
        # NULL is UNKNOWN, not zero. A pair indexed before these columns
        # existed printed "0 combinations, 0 B, interrupted" while holding
        # 12,960 measured rows.
        known = r.get("last_ms") is not None
        last_ms = int(r.get("last_ms") or 0)
        n = int(r.get("n") or 0)
        mtime = r.get("rows_mtime") or 0
        rows.append({
            "coin": r["coin"], "tf": r["tf"],
            "rows": n,
            "combos": (int(r["combos"]) if r.get("combos") is not None
                       else None),
            "bytes": int(r.get("bytes") or 0),
            "version": r.get("version") or "",
            "measured_through": (pv.fmt_when(last_ms / 1000)
                                 if last_ms else None),
            "measured_ms": last_ms or None,
            # a pair with rows but NO watermark was interrupted part-way:
            # the checkpoint kept its work, the pair never completed
            "incomplete": bool(known and n and not last_ms),
            "last_run": pv.fmt_when(mtime) if mtime else None,
            "last_run_ts": mtime or None,
        })
    rows.sort(key=lambda r: -r["bytes"])
    total_b = sum(r["bytes"] for r in rows)
    newest = max((r["measured_ms"] or 0 for r in rows), default=0)
    return {
        "rows": rows,
        "pairs": len(rows),
        "coins": len({r["coin"] for r in rows}),
        "total_rows": sum(r["rows"] for r in rows),
        "total_bytes": total_b,
        "incomplete": sum(1 for r in rows if r["incomplete"]),
        # the screen must be able to say this list is still filling in
        "index": ri.status(),
        "newest_measured": (pv.fmt_when(newest / 1000) if newest else None),
    }


@app.get("/api/backtest/history")
def backtest_history(limit: int = 20) -> dict:
    """Every backtest run, newest first, with whether it worked.

    Same source as the bell — the local event feed — because the job's own
    progress file only ever holds the LAST run.
    """
    from tradingagents import notifications as nt, positions_view as pv

    out = []
    for r in nt.recent(limit=limit, kind="backtest"):
        m = r.get("meta") or {}
        out.append({
            "ts": r["ts"], "when": pv.fmt_when(float(r.get("ts") or 0)),
            "ok": r["ok"], "title": r["title"], "detail": r["detail"],
            "rows": m.get("rows"), "report": m.get("report"),
            "fatal": bool(m.get("fatal")),
            "save_error": m.get("save_error") or "",
        })
    ok = sum(1 for r in out if r["ok"])
    return {"rows": out, "total": len(out), "ok": ok, "failed": len(out) - ok}


# ------------------------------------------------------------- supervisor
@app.get("/api/trade/supervisor")
def supervisor_status() -> dict:
    """Whether the runner is being kept alive, and how healthy it looks.

    `last_beat_seconds` comes from the runner's own log mtime: a live runner
    writes a scan line every cycle, so a stale log IS a dead runner even when
    a stale pid file says otherwise.
    """
    import time

    import tradingagents.auto_trader as at
    from tradingagents import supervisor as sv

    got = sv.status()
    try:
        beat = at.LOG_PATH.stat().st_mtime
        got["last_beat_seconds"] = round(time.time() - beat, 1)
    except OSError:
        got["last_beat_seconds"] = None
    got["stale"] = (got["last_beat_seconds"] is not None
                    and got["last_beat_seconds"] > 300)
    return got


@app.post("/api/trade/supervisor")
def supervisor_set(body: dict) -> dict:
    """Turn auto-restart on or off."""
    import sys

    from tradingagents import supervisor as sv

    if bool(body.get("enabled")):
        return sv.install(python=sys.executable)
    return sv.uninstall()


@app.get("/api/system")
def system_load() -> dict:
    """What the machine is doing — shown beside the job bars.

    Temperature is absent on purpose when it cannot be read: see sysmon.
    """
    from tradingagents import sysmon

    return sysmon.snapshot()
