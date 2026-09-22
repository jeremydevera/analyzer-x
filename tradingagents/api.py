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
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from tradingagents import stores as _stores
from tradingagents.slow_cache import BackgroundValue


def _sweep_days() -> int:
    """The default measuring window, from ONE place (cloud_sweep.SWEEP_DAYS).

    Seven call sites here each carried `or 365`, so the operator's "past 30
    days not 1 year" would have had to be typed seven times and would drift on
    the eighth. Imported lazily to keep the module import graph flat.
    """
    from tradingagents import cloud_sweep as _cs

    return int(_cs.SWEEP_DAYS)


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
    # BY NAME. This job knows exactly which coins the PC never reached — it is
    # the whole point of a hand-off — and until Sep 10, 2026 it sent only how
    # MANY, so the fleet measured the top of its own alphabetical board and the
    # missed coins stayed missed.
    run = cs.dispatch(shards=20, coins=0, coin_list=left,
                      timeframes=",".join(tfs),
                      min_days=0,      # every contract — never the 365 default nobody chose
                      # and the HANDED-OVER job's own stake and window, or the
                      # two halves of one sweep are two different measurements
                      days=int(spec.get("days") or _sweep_days()),
                      base=float(spec.get("base") or 5.0))
    cs.remember(run)
    dj.clear_handoff(kind)              # the cloud has it; the request is served
    named = len(run.get("coins_named") or [])
    print(f"[handoff] {len(left)} coins the Mac never reached -> GitHub run "
          f"{run.get('id')}"
          + (", named one by one" if named == len(left) and named else "")
          # a list too long for one command line measures the whole board:
          # more work than asked for, and it must not be discovered later
          + (f" — BUT {run.get('coin_list_why')}"
             if run.get("coin_list_why") else ""), flush=True)
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
                # LAND FINISHED CLOUD RUNS — it never starts one. The dispatch
                # half died on 2026-09-09: the operator started localhost and
                # got a 20-machine backtest they never asked for, because the
                # 2026-09-05 goal "USE GITHUB WHEN THERE IS FREE" had been
                # read as a standing rule. Their words: "no no no, i want
                # option to start the backtest". Buttons dispatch; this
                # collects, because artifacts delete themselves after 14 days.
                try:
                    from tradingagents import cloud_autopilot as _ca

                    _ca.tick()
                except Exception as exc:                       # noqa: BLE001
                    print(f"[cloud-autopilot] failed: {exc!r}", flush=True)
                # NO AUTOMATIC CANDLE TOP-UP. candle_autopilot.tick() ran here
                # from 2026-09-06 to 2026-09-09 and started an UPDATE by itself
                # whenever the store was 3h stale. The operator saw
                # "downloading 39%" they had not asked for and said: *"i dont
                # want it, it will only update when i click update candle
                # button"*. Candles now change only from the Candles screen's
                # own buttons; "pending" climbing overnight is the store going
                # stale, not a fault (test_the_supervisor_does_NOT_top_up).
                # the v2 jobs (Backtest v2, Sep 17, 2026) are supervised
                # exactly like the v1 ones — a crashed 1m download must not
                # stay dead any more than a crashed 15m one
                for kind in ("backtest", "download", "btupdate",
                             "download_v2", "backtest_v2", "btupdate_v2"):
                    try:
                        got = _dj.resume_if_died(kind)
                        if got.get("resumed"):
                            print(f"[supervisor] {kind} resumed, attempt "
                                  f"{got['attempt']} (pid {got['pid']})",
                                  flush=True)
                    except Exception:
                        pass
                # AND THE INDEXER — the process that keeps the SCREEN true.
                #
                # It was spawned once, at API startup, and nothing ever looked
                # again. On Sep 13, 2026 4:05pm it died on `database is
                # locked` (a collect held the write lock) and stayed dead:
                # `rows_index.log` ended on a traceback, no process was
                # running, and Stored strategies went on answering from
                # whatever had last been filed while the REINDEX button
                # offered to catch up **5,344** pairs. The operator asked
                # *"what's the reason why you decide it should not be
                # updated"* — nobody decided; the thing that does it was gone.
                #
                # THE UI IS THE SOURCE OF TRUTH FOR WHAT THEY CAN SEE, so the
                # process that feeds it is supervised exactly like the runner
                # and the jobs above. `spawn_indexer` no-ops while one is
                # alive, so this cannot double it.
                try:
                    from tradingagents import rows_index as _ri

                    pid = _ri.spawn_indexer()
                    if pid:
                        print(f"[supervisor] the row indexer was down — "
                              f"restarted (pid {pid})", flush=True)
                except Exception as exc:                       # noqa: BLE001
                    print(f"[supervisor] could not restart the indexer: "
                          f"{exc!r}", flush=True)
                # AND THE RUNNER, on the machines launchd cannot watch.
                # Operator, 2026-09-04: *"IF I RUN IT RUN IT / I DONT WANT ANY
                # INCONVENIENCE"*. `supervisor.py` is a macOS LaunchAgent, so
                # on Windows a runner that dies stays dead — three starts died
                # in a row that morning and nothing brought them back. The
                # WANT flag is the operator's own intent: STOP removes it and
                # this loop leaves it alone. It cannot double a runner —
                # `start_runner` returns the existing pid when one is alive,
                # and the runner takes an exclusive lock before it trades.
                try:
                    import tradingagents.auto_trader as _at
                    from tradingagents import portable as _portable

                    if (not _portable.MACOS and _at.wants_runner()
                            and not _at.runner_pid()):
                        pid = _at.start_runner()
                        print(f"[supervisor] runner was down — restarted "
                              f"(pid {pid})", flush=True)
                except Exception as exc:
                    print(f"[supervisor] could not restart the runner: "
                          f"{exc!r}", flush=True)

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
    # A ROW DEPLOYED FROM BACKTEST v2 KEEPS ITS v2 ID (Sep 17, 2026). The
    # runner trades the same coin/frame/signal/barriers either way; the id
    # names which MEASUREMENT the operator chose, and `strategy_res` (written
    # by deploy_preset from a preset row's `res`) remembers it per coin.
    res = ((settings.get("strategy_res") or {})
           .get(at.book_slot(key, coin)) or None)
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
            at.sizing_for(settings, key),
            res=res)
    except Exception:                                          # noqa: BLE001
        return ""


# Every kind `db_jobs.FILES` can run. A kind missing here is a job that
# STARTS and cannot be watched: `/api/jobs/pairbt` answered "unknown job kind"
# while the job it names was running, so the row's UPDATE button could never
# follow its own work (2026-09-09). Derived from FILES so the next kind cannot
# be forgotten.
JOB_KINDS = tuple(sorted(__import__("tradingagents.db_jobs",
                                    fromlist=["FILES"]).FILES))

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
               # the low end of each range: "BETWEEN .5 - 2.5", both ends
               # inclusive (operator, 2026-09-03)
               min_tp: float = 0.0, min_sl: float = 0.0,
               # the checkbox: only rows whose target is wider than their stop
               tp_over_sl: bool = False,
               # "crypto" or "stocks" — tokenized stocks carry a STOCK suffix
               asset: str | None = None,
               sizing: str | None = None, row_id: str | None = None,
               group: str | None = None,
               months: int = 0, days: int = 0,
               # HOW FRESH THE MEASUREMENT IS. Operator, Sep 10, 2026: *"my
               # goal is to filter on when was the last backtest for each
               # strategy, because even i filter last 30 days some of them was
               # last backtested 3 weeks ago which is obsolete"*. Measured on
               # their store the same minute: EPIK-30m last measured Aug 26,
               # BICO-15m Sep 10 — 15.8 days apart, so a 30-day window on the
               # first ends 15.8 days ago.
               measured_days: int = 0,
               desc: bool | None = None) -> dict:
    """Every stored strategy, filtered. Rows carry their stable id.

    Served from the SQLite index, NOT by re-reading the store. This route used
    to call `market_sweep.all_rows()`, which parses every pair file: measured
    28.6s for 648,181 rows over 363 MB, 53 pairs into a 3,960-pair sweep. The
    grid polls every 4s, so the calls piled up, the threadpool jammed, and the
    browser reported `HTTP 500`. See tradingagents/rows_index.py.
    """
    from tradingagents import rows_index as ri

    _t0 = _time.time()
    # no sync kick here: a timer thread keeps the index current (see the
    # startup hook), so a page open does not decide whether data appears.
    try:
        got = ri.query(coin=coin, tf=tf, signal=signal,
                       profitable=profitable, limit=limit,
                       offset=offset, sort=sort,
                       min_trades=min_trades, min_winrate=min_winrate,
                       max_tp=max_tp, sizing=sizing, row_id=row_id,
                       group=group, max_sl=max_sl, months=months, desc=desc,
                       min_tp=min_tp, min_sl=min_sl,
                       tp_over_sl=tp_over_sl, asset=asset or None,
                       measured_days=measured_days)
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
    got["window_hidden"] = 0
    if months and got.get("window") and len(got.get("rows") or []) <= RESTATE_MAX:
        for r in got["rows"]:
            r.update(restate_window(r, got["window"]))
        # THE FLOORS AGAIN, ON THE WINDOW. The SQL floors ran on whole-history
        # figures; the page prints the window's. See rows_index.window_floors.
        got["rows"], got["window_hidden"] = ri.window_floors(
            got["rows"], min_winrate=min_winrate, min_trades=min_trades,
            profitable=profitable)
    got["restate_max"] = RESTATE_MAX
    # HOW MANY ROWS A WINDOWED DOWNLOAD CAN ACTUALLY HOLD, so the button can
    # say it instead of promising `total`. With `days` on, the export
    # re-measures at most this many rows from the candles and then drops the
    # ones the window's own figures fail — measured Sep 09, 2026 on the
    # operator's own press: the button read "download all (566,990) CSV" and
    # the file held **1,184** rows (2,000 re-measured, 816 cut by the window
    # floor). A count nobody can deliver is a false label on a true number.
    got["days_csv_max"] = ri.DAYS_CSV_MAX
    # LAST N DAYS. Operator, 2026-09-02: "can you add days textbox isntead of
    # using past 1 month only / if months is 0 then follow the days" -- so
    # MONTHS WINS when both are set, and the days window is a re-measurement
    # (the store keeps profit per MONTH and no trade counts at all, so a day
    # window cannot be derived from it). Every row on the page is restated or
    # the request says why, rather than a table where some rows are the window
    # and others are their whole history.
    got["days"] = 0
    # ECHOED, not assumed: the panel sets its "served filters" from what came
    # BACK, because `applied` and `served` differ every time a request fails
    # and the old rows stay on screen under the new filter's label
    # (label-must-match-data, paid for on 2026-08-27).
    got["measured_days"] = int(measured_days or 0)
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
            _st = _store_now()
            win = msw.window_rows(rows, int(days),
                                  base_margin=float(rows[0].get("base") or 5.0)
                                  if rows else 5.0,
                                  # v2 rows re-measure from the 1-minute store
                                  store=None if _st.name == "v1" else _st)
        except msw.WindowTooWide as exc:
            raise HTTPException(503, str(exc)) from exc
        got["days"] = int(days)
        got["days_window"] = [win["first"], win["last"]]
        got["days_groups"] = win["groups"]
        # WHY SOME ROWS KEPT THEIR WHOLE-HISTORY FIGURES, and how many counted
        # trades opened before the window began. Both are rule 20 (whatever was
        # excluded is counted out loud): without them a row that could not be
        # re-measured is indistinguishable from one that traded nothing, and a
        # window leaning on one long trade looks like 30 days of work.
        got["window_skipped"] = win.get("skipped") or {}
        got["window_straddled"] = int(win.get("straddled") or 0)
        # THE FLOORS AGAIN, ON THE WINDOW. Sep 09, 2026: "Winrate 90% or
        # better" chip over rows printing 89.47 / 86.36 / 80.00 / 75.00 — each
        # was >= 90 over its whole history (what SQL checked) and under 90 in
        # the last 30 days (what the column printed). The cut is COUNTED, and
        # the page says it: a row hidden silently is rule 20 broken.
        got["rows"], got["window_hidden"] = ri.window_floors(
            rows, min_winrate=min_winrate, min_trades=min_trades,
            profitable=profitable)
    # NOT ri.status() — 267.55 s measured on this store, on a POLLED route
    # (see INDEX_STATUS_TTL)
    got["index"] = index_status()          # so the UI can say "still indexing"
    # THE PRESS, AND WHETHER THE ANSWER AGREES WITH IT. The operator asked for
    # this after the 89.47% row: every filter fix had been verified by reading
    # the code around one filter, and the bug lived only in the finished table.
    # `disagreements` re-tests each row that is about to be sent against each
    # filter that was on, using the figure the COLUMN prints — so a chip that
    # disagrees with its own table writes a MISMATCH line the moment it happens.
    # WITH THE STORE: a v2 press and a v1 press with the same filters were
    # indistinguishable lines in the screen log (Sep 18, 2026 review)
    _screen_note("apply", {**locals(), "store": _store_now().name}, got,
                 _time.time() - _t0)
    return got


def _screen_note(event: str, args: dict, got: dict, took: float) -> None:
    """One line in `screen_log` for a press. Never raises."""
    try:
        from tradingagents import screen_log as sl

        asked = {k: args.get(k) for k in (
            "coin", "tf", "signal", "profitable", "min_trades", "min_winrate",
            "max_tp", "max_sl", "min_tp", "min_sl", "tp_over_sl", "asset",
            "sizing", "group", "row_id", "months", "days", "measured_days",
            "sort", "desc")}
        rows = got.get("rows") or []
        summary = {
            "rows": len(rows), "total": got.get("total"),
            "capped": got.get("total_capped") or None,
            "window_hidden": got.get("window_hidden") or None,
            "window": " -> ".join(got.get("days_window") or []) or None,
        }
        sl.record(event, asked, summary, took,
                  notes=sl.disagreements(rows, asked))
    except Exception:                                          # noqa: BLE001
        pass


# How often the CSV export hands the interpreter lock back. Small enough that
# the page stays alive during a long download, large enough to cost nothing:
# at 25 rows a pause of 2 ms is 0.08 s per 1,000 rows.
_CSV_BREATHE = 25


def strategies_csv_lines(coin=None, tf=None, signal=None, profitable=False,
                         sort="profit", min_trades=0, min_winrate=0,
                         max_tp=0, sizing=None, row_id=None, group=None,
                         max_sl=0, days=0,
                         desc=None, batch=5_000, min_tp=0, min_sl=0,
                         tp_over_sl=False, asset=None, measured_days=0,
                         db_path=None, store=None):
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
    import time as _time

    from tradingagents import positions_view as pv, rows_index as ri

    # kit item F: every row carries every column, the file included. `balanced`
    # is derived, so it is appended rather than living in ri.COLS (the table's
    # own shape) — and `iter_rows` does not compute it, so the CSV rates each
    # row here with the same function the grid used.
    cols = list(ri.COLS)
    # WHEN THE ROW WAS LAST BACKTESTED, on every row, always — not only when
    # the freshness filter is on. A file read a week later has to be able to
    # answer "was this stale when it was exported?" (operator, Sep 10, 2026:
    # *"when i do backtest make sure to show the last backtest"*).
    cols += ["measured_through", "last_backtest_run"]
    if days:
        # the window travels with the rows, so the file can be read a week
        # later without guessing which days it covered
        # kit item F: the file carries what the table shows, and the
        # table now says how many trades opened before the window
        cols += ["window_first", "window_last", "window_days",
                 "window_straddled"]
    buf = _io.StringIO()
    w = csv.writer(buf, lineterminator="\n")

    def flush() -> str:
        out = buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        return out

    # BALANCED SITS BESIDE WIN %, in the file as on the screen. Operator,
    # `Sep 15, 2026`: *"i want the balanced beside the winrate in table and
    # when downloading"*. It was last in both, which put the score that rates
    # win rate AND profit together several columns away from the win rate it
    # is there to qualify.
    _bal_at = (cols.index("winrate") + 1) if "winrate" in cols else len(cols)
    head = list(cols)
    head[_bal_at:_bal_at] = ["balanced", "balanced_why"]
    w.writerow(head + ["monthly_json"])
    yield flush()
    # A StreamingResponse has already sent 200 by the time a row fails, so an
    # exception here cannot become an error page — it just ENDS the download.
    # That is how 5,000 rows of 43,867 arrived looking like the whole file
    # (2026-08-27). So: count what left, and if the stream dies, SAY SO in the
    # file itself and in the log. A short file that says it is short is worth
    # more than a short file that does not.
    sent = 0
    stats: dict = {}
    # THE PRESS, IN WRITING. The operator asked for a log of every Apply and
    # every download so the status can be read back (Sep 09, 2026). `Watch`
    # tests each row as it streams — the file must not hold them — so a
    # download that carries rows its own filename denies says so in the log.
    from tradingagents import screen_log as _sl
    _asked = {"coin": coin, "tf": tf, "signal": signal,
              "profitable": profitable, "min_trades": min_trades,
              "min_winrate": min_winrate, "max_tp": max_tp, "max_sl": max_sl,
              "min_tp": min_tp, "min_sl": min_sl, "tp_over_sl": tp_over_sl,
              "asset": asset, "sizing": sizing, "group": group,
              "row_id": row_id, "days": days, "sort": sort, "desc": desc}
    _watch = _sl.Watch(_asked)
    _csv_t0 = _time.time()
    # A DOWNLOAD IN FLIGHT MUST BE VISIBLE. The completion line below is
    # written when the stream ENDS, so on Sep 09, 2026 the operator pressed
    # download, watched the browser sit at "0 B", asked why, and the log had
    # nothing to show — the request was running and no line existed yet. Now
    # the start is a line of its own, so "started and never finished" reads
    # differently from "never pressed".
    _sl.record("csv START", _asked, {"streaming": True}, 0.0)
    try:
        for r in ri.iter_rows(coin=coin, tf=tf, signal=signal,
                              profitable=profitable, sort=sort,
                              min_trades=min_trades, min_winrate=min_winrate,
                              max_tp=max_tp, sizing=sizing, row_id=row_id,
                              group=group, max_sl=max_sl, days=days,
                              desc=desc, batch=batch,
                              min_tp=min_tp, min_sl=min_sl,
                              tp_over_sl=tp_over_sl, asset=asset,
                              measured_days=measured_days,
                              # Backtest v2's rows.db when the v2 CSV asks,
                              # and its store for the window's re-measure
                              db_path=db_path, store=store,
                              stats=stats):
            score, why = ri.balanced_score(r)
            # THE PROJECT'S ONE DATE FORMAT (`Aug 03, 2026 8:03pm`), never a
            # raw epoch and never `strftime` — CLAUDE.md's date rule, which
            # has been broken by hand-rolled copies four times.
            r["measured_through"] = (pv.fmt_when(r["measured_ms"] / 1000)
                                     if r.get("measured_ms") else None)
            r["last_backtest_run"] = (pv.fmt_when(r["measured_run_ms"] / 1000)
                                      if r.get("measured_run_ms") else None)
            _watch.see(r)
            _row = [r.get(c) for c in cols]
            _row[_bal_at:_bal_at] = [score, why]
            w.writerow(_row + [_json.dumps(r.get("monthly") or {},
                                           separators=(",", ":"))])
            sent += 1
            yield flush()
            # LET THE REST OF THE APP BREATHE. A windowed download RE-MEASURES
            # every row from this PC's candles — about 0.09 s of pure Python
            # each — and that holds the interpreter lock. Measured Sep 09,
            # 2026 while one such download ran for 78 s: `/api/health` took
            # 23.8 s and `/api/backtest/logs` TIMED OUT at 47 s, so the page
            # the operator was looking at filled with errors and read as
            # "internal server error" while the file itself was fine.
            # A 2 ms sleep every `_CSV_BREATHE` rows hands the lock over and
            # costs well under a second on a run this long.
            if sent % _CSV_BREATHE == 0:
                _time.sleep(0.002)
        if days and sent >= ri.DAYS_CSV_MAX:
            # a capped file SAYS it is capped, IN the file (kit rule: a capped
            # grid says what it capped)
            w.writerow([f"WINDOW CAPPED: this download re-measured the first "
                        f"{sent} rows over the last {int(days)} days; a days "
                        f"window is a re-measurement (~0.09 s a row), so it "
                        f"stops there. Narrow the filter, or download without "
                        f"the window for every matching row's whole history."])
            yield flush()
        if stats.get("window_hidden"):
            # a cut row is counted out loud, IN the file (rule 20)
            w.writerow([f"WINDOW FLOOR: {stats['window_hidden']} row(s) passed "
                        f"the floors over their whole history but not inside "
                        f"the last {int(days)} days, and were left out — the "
                        f"rows above are the ones the window itself clears."])
            yield flush()
    except Exception as exc:                                   # noqa: BLE001
        print(f"[strategies.csv] export stopped after {sent:,} rows: "
              f"{type(exc).__name__}: {exc}", flush=True)
        w.writerow([f"EXPORT INCOMPLETE after {sent} rows: "
                    f"{type(exc).__name__}: {exc}"])
        yield flush()
        _sl.record("csv FAILED", _asked,
                   {"rows": sent, "why": f"{type(exc).__name__}: {exc}"},
                   _time.time() - _csv_t0, notes=_watch.notes())
        raise
    else:
        _sl.record("csv", _asked,
                   {"rows": sent,
                    "window_hidden": stats.get("window_hidden") or None,
                    "capped": (days and sent >= ri.DAYS_CSV_MAX) or None},
                   _time.time() - _csv_t0, notes=_watch.notes())


def strategies_csv_name(coin=None, tf=None, signal=None, min_trades=0,
                        sort="profit", min_winrate=0, max_tp=0,
                        sizing=None, group=None, max_sl=0, days=0,
                        min_tp=0, min_sl=0, tp_over_sl=False,
                        asset=None) -> str:
    """A filename that says which slice of the store is in the file."""
    bits = [b for b in (coin, tf, signal,
                        f"min{min_trades}" if min_trades else "",
                        # the win-rate floor is part of WHICH slice this is:
                        # two downloads of the same coin differ only by it
                        f"wr{_trim(min_winrate)}" if min_winrate else "",
                        # a RANGE is named as one bit, both ends, because
                        # `tp2.5` for "between 0.5 and 2.5" names a different
                        # slice than the file holds
                        (f"tp{_trim(min_tp)}-{_trim(max_tp)}" if min_tp and max_tp
                         else f"tp{_trim(max_tp)}max" if max_tp
                         else f"tp{_trim(min_tp)}min" if min_tp else ""),
                        (f"sl{_trim(min_sl)}-{_trim(max_sl)}" if min_sl and max_sl
                         else f"sl{_trim(max_sl)}max" if max_sl
                         else f"sl{_trim(min_sl)}min" if min_sl else ""),
                        "tp-over-sl" if tp_over_sl else "",
                        str(asset or ""),
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
                   min_tp: float = 0.0, min_sl: float = 0.0,
                   tp_over_sl: bool = False,
                   asset: str | None = None,
                   sizing: str | None = None, row_id: str | None = None,
                   group: str | None = None, months: int = 0, days: int = 0,
                   measured_days: int = 0,
                   desc: bool | None = None):
    """EVERY matching row as CSV — no limit, streamed.

    The screen can hold a few thousand rows; the store holds 21,858,026. The
    operator asked for all of them ("give me all", 2026-08-26), so this writes
    all of them to a file instead of pretending a page is the whole list.
    """
    from fastapi.responses import StreamingResponse

    from tradingagents import rows_index as ri

    # Fail BEFORE the stream starts — an error mid-download is a truncated file
    # that looks complete — but WITHOUT running the query. This used to pull the
    # first row out of `iter_rows`, so one download ran the whole query TWICE,
    # and COLD on this store that is 126.1 s a pass (0.8 s warm): the check
    # alone blew the 30 s proxy limit and the operator got "Internal Server
    # Error" at 30.018 s with nothing written, twice (Sep 03, 2026: "ITS STILL
    # NOT WORKING"). `export_plan` reads no rows and refuses with exactly what
    # the query would have refused with, so the stream now starts at once.
    try:
        ri.export_plan(coin=coin, signal=signal, sort=sort, row_id=row_id,
                       group=group, min_winrate=min_winrate,
                       min_trades=min_trades, desc=desc)
    except ri.SortNotReady as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    name = strategies_csv_name(coin, tf, signal, min_trades, sort,
                               min_winrate=min_winrate, max_tp=max_tp,
                               sizing=sizing, group=group, max_sl=max_sl,
                               min_tp=min_tp, min_sl=min_sl,
                               tp_over_sl=tp_over_sl, asset=asset,
                               days=0 if months else days)
    return StreamingResponse(
        strategies_csv_lines(coin=coin, tf=tf, signal=signal,
                            profitable=profitable, sort=sort,
                            min_trades=min_trades, min_winrate=min_winrate,
                            max_tp=max_tp, sizing=sizing, row_id=row_id,
                            group=group, max_sl=max_sl,
                            min_tp=min_tp, min_sl=min_sl,
                            tp_over_sl=tp_over_sl, asset=asset,
                            days=0 if months else days,
                            measured_days=measured_days, desc=desc),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/screen/log")
def screen_log(n: int = 200, mismatch_only: bool = False) -> dict:
    """What was pressed, what came back, and every filter the answer broke.

    Operator, Sep 09, 2026: *"whenever i clicked apply filter and click
    download csv you should be getting the logs of it so you can see the
    status"*. Asked right after the reason the 89.47% row survived: every fix
    was verified by reading the code around ONE filter, and the bug existed
    only in the finished table. `mismatch_only=true` is the line that matters —
    a chip disagreeing with its own column, written by the code that served it.
    """
    from tradingagents import screen_log as sl

    lines = sl.mismatches(max(1, min(n, 4000))) if mismatch_only \
        else sl.tail(max(1, min(n, 4000)))
    all_lines = sl.tail(4000)
    return {"lines": lines, "total": len(all_lines),
            "mismatches": len([ln for ln in all_lines if "MISMATCH" in ln]),
            "path": str(sl.LOG_PATH)}


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
    # THE NUMBER THE BUTTON PRINTS IS THE NUMBER IT WILL WALK. `behind` counts
    # never-indexed pairs only; `sync()` walks `stale_pairs()`, which also
    # holds every pair whose file MOVED since it was indexed. On 2026-09-10
    # that was 806 against 5,276 — the button promised a seventh of its job.
    todo = int(st.get("stale") or 0) or behind
    if todo <= 0:
        return {"started": False, "behind": 0, "todo": 0,
                "why": "the index is up to date with every measured pair"}
    if st.get("syncing"):
        return {"started": False, "behind": behind, "todo": todo,
                "why": "already indexing — it is working through the backlog"}
    # A DOOR HELD BY SOMETHING ELSE IS NOT A BUTTON THAT WORKED. The catch-up
    # dies on `database is locked` the moment a cleanup owns the write lock,
    # and that failure used to be swallowed: "started" with nothing happening.
    held = st.get("blocked_by")
    if held:
        return {"started": False, "behind": behind, "todo": todo,
                "blocked_by": held,
                "why": f"the row index is locked by {held} — indexing cannot "
                       f"start until that finishes or is stopped"}
    if not ri.sync_in_background(force=True):
        return {"started": False, "behind": behind, "todo": todo,
                "why": "already indexing — it is working through the backlog"}
    return {"started": True, "behind": behind, "todo": todo,
            "why": f"indexing {todo:,} measured pair(s) now"}


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


import contextvars as _contextvars  # noqa: E402  (placed here with the ContextVar it defines)

# WHICH STORE THE STRATEGIES HANDLER RESTATES FROM. `strategies()` is one
# function serving v1 and, under `strategies_v2`, Backtest v2; the re-measure
# helpers it calls (`restate_window`, `market_sweep.window_rows`) read candle
# and state files, and FastAPI would turn an extra parameter into a query
# field. A ContextVar set by the v2 route for the length of the call is how
# they learn the store — the same shape as `rows_index.using_db`.
_STORE: _contextvars.ContextVar = _contextvars.ContextVar("api_store", default=None)


def _store_now():
    """The store the current request restates from: V2 under strategies_v2,
    V1 otherwise."""
    return _STORE.get() or _stores.V1


def restate_window(row: dict, window: list, store=None) -> dict:
    """`w_trades`, `w_wins`, `w_losses`, `w_winrate` and the log's own window
    profit, counted from this row's trades rebuilt from the candles.

    By EXIT month, which is how the sweep counts a trade into a month
    (`monthly[_month_of(exit_bar)] += pnl`). Returns {} when the log cannot be
    rebuilt — a missing figure must stay missing rather than become a zero.
    """
    from tradingagents import market_sweep as msw
    from tradingagents.positions_view import fmt_when  # noqa: F401

    if not window:
        return {}
    store = store or _store_now()
    try:
        got = msw.trades_for(row["coin"], row["tf"], signal=row["signal"],
                             th=float(row.get("th") or 0.0),
                             sl=float(row["sl"]), tp=float(row["tp"]),
                             sizing=row["sizing"],
                             base_margin=float(row.get("base") or 5.0),
                             # v2 rows are replayed from the 1-minute store
                             store=None if store.name == "v1" else store)
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


def _read_coverage() -> dict:
    """The slow read. Runs in `_COVERAGE`'s background thread only."""
    from tradingagents import market_sweep as msw

    return {"rows": msw.candle_coverage(), "reading": False}


# A REQUEST NEVER WAITS FOR THE DISK (Sep 15, 2026). `candle_coverage()` opens
# and JSON-parses every candle file — 5,235 files, 1.77 GB on the operator's
# mechanical G: — and this route called it INSIDE the handler, so opening the
# Storage screen held a browser lane for minutes. It is the same disease as
# `/api/cloud/status` (216 s, RCA-2026-09-09-I) and `/api/strategies`
# (267 s), and the same cure, which this file already imports.
#
# The TTL is long because the answer is: coverage moves only when a download
# runs, and the read itself is the expensive thing being spaced out.
COVERAGE_TTL = 600.0
_COVERAGE = BackgroundValue(
    "storage-coverage", _read_coverage, ttl=COVERAGE_TTL,
    on_error=lambda exc: {"rows": [], "reading": False,
                          "why": f"{type(exc).__name__}: {exc}"})


@app.get("/api/storage/coverage")
def storage_coverage() -> dict:
    # `reading: True` and an EMPTY list are different things and the screen
    # must be able to tell them apart — "no candles" is a fact about the
    # store, "still reading" is a fact about this request.
    return _COVERAGE.get(pending={"rows": [], "reading": True})


@app.get("/api/storage/sizes")
def storage_sizes() -> dict:
    from tradingagents import parquet_store as pqs

    return pqs.sizes()


@app.get("/api/storage/months")
def storage_months() -> dict:
    """Candles per month and backtest results per month measured, with the
    delete jobs' progress — see storage_months.py for what "month" means in
    each store. From the candle index and the pairs table: nothing here reads
    a candle file or a rows file on a polled route."""
    from tradingagents import storage_months as sm

    return sm.snapshot()


@app.get("/api/storage/delisted")
def storage_delisted() -> dict:
    """Every stored coin MEXC no longer lists, what it costs on disk, and the
    delete job's progress — the Backtest screen's DELETE N DELISTED button.
    `known: False` when the venue could not be asked: the button then says so
    and stays disabled, never guessing."""
    from tradingagents import storage_months as sm

    return {"delisted": sm.delisted_report(), "job": sm.progress("delisted"),
            "writer": sm._writer_running("delisted")}


class MonthDelete(BaseModel):
    kind: str          # "candles", "results" or "delisted"
    through: str = ""  # "2025-02" — this month AND every older one; unused
                       # for "delisted"


@app.post("/api/storage/months/delete")
def storage_months_delete(q: MonthDelete) -> dict:
    """Start deleting one month and everything older. 409 with the reason
    when it must not start (current month, a writer job running, a delete
    already running)."""
    from tradingagents import storage_months as sm

    try:
        return sm.start_delete(q.kind, q.through)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


# -------------------------------------------------------------------- jobs
def _check_kind(kind: str) -> None:
    if kind not in JOB_KINDS:
        raise HTTPException(404, f"unknown job kind: {kind}")


@app.post("/api/strategies/{row_id}/update")
def strategy_row_update(row_id: str, store: str = "v1") -> dict:
    """Re-measure THIS ROW's pair, now. The row's own UPDATE button.

    `store=v2` runs it in Backtest v2: the row is looked up in v2's own index
    and the job is `pairbt_v2`, which `db_jobs.start` launches with
    `stores.V2.env_for()` — so the frame is rebuilt from 1-minute bars and the
    reindex writes v2's table. The operator, `Sep 18, 2026`: *"can we join
    candle v2 and backtest v2? instead of me manually downloading the candles
    in candles v2, when i click update this backtest, it should automatically
    download the candles"*. The download half lives in `market_sweep.run_pair`,
    which now fetches the minutes it needs instead of refusing with "download
    them on Candles v2 first"; this half is what gives v2 a button at all.

    Operator, 2026-09-09, on #SW8Q96E6 whose last backtest read Aug 24, 2026
    4:00pm: *"can i have a button 'update' to force update the backtest"*.

    It measures the PAIR (coin + timeframe), not the single combination: the
    store keeps one file per pair and one watermark per pair, so bringing one
    row forward without the rest would leave the pair's other rows measured
    through an older bar than its own watermark claims. Detached, resuming
    from the watermark, so only the bars printed since are walked.
    """
    import contextlib as _ctx

    from tradingagents import db_jobs as dj, rows_index as ri

    rid = ri.clean_row_id(row_id)
    if not rid:
        raise HTTPException(422, "that is not a row id")
    _v2 = str(store).lower() == "v2"
    kind = "pairbt_v2" if _v2 else "pairbt"
    # v2 ids never collide with v1's (`row_code(res=)`), but the ROW only
    # exists in its own table — looking a v2 id up in v1's index answers 404
    # and the button would read as "this row is gone".
    _db = _v2_rows_db() if _v2 else None
    if _v2 and _db is None:
        raise HTTPException(404, "Backtest v2 has no rows yet")
    with (ri.using_db(_db) if _v2 else _ctx.nullcontext()):
        try:
            got = ri.query(row_id=rid, limit=1)
        except ri.SortNotReady as exc:
            # 503 WITH THE REASON, never a bare 500. Measured Sep 22, 2026
            # 10:47pm: pressing UPDATE on #XLV6V5HJ (XPIN 1h mom6, Backtest
            # v2) answered "Internal Server Error" because v2's 30,702,310
            # rows had no `rows_id` list yet and one was being built. The
            # press is fine and nothing is lost — the store is simply not
            # ready to look an id up — and the sentence says so. The same
            # answer the strategies list and the CSV have given since
            # 2026-08-26; this route was the one that still said nothing.
            raise HTTPException(503, str(exc)) from exc
        rows = (got.get("rows") if isinstance(got, dict) else got) or []
    if not rows:
        raise HTTPException(404, f"no stored row #{rid} in {store}")
    row = rows[0]
    coin, tf = row.get("coin"), row.get("tf")
    if not coin or not tf:
        raise HTTPException(500, f"row #{rid} does not name its pair")
    st = dj.status(kind)
    if st.get("running"):
        # ONE at a time: two runs on the same pair fight over its pair lock,
        # and on a DIFFERENT pair they still both rewrite the row index.
        raise HTTPException(409, f"already re-measuring "
                                 f"{st.get('pair') or 'a pair'} — wait for it")
    # THIS ROW'S SIGNAL, so the run touches this strategy and no other.
    # Operator: "its simple just update the backtest for that certain
    # strategy" — the first version measured all 120 signals for the pair.
    sig = row.get("signal") or ""
    # A BUSY MACHINE IS A 409, NOT A 500 (operator, Sep 17, 2026: pressing
    # UPDATE on #LG9NSU4B answered "Internal Server Error"). `dj.start`
    # refuses while ANY other job holds the disk — one job at a time, across
    # both versions — by raising JobBusy, and nothing here caught it. So the
    # one thing the operator needed to read, "a candle download is running",
    # came back as a blank crash with no traceback in api.log either. The
    # generic /api/jobs/{kind} route has answered 409 for this since it was
    # written; this button and the per-strategy backtest never learned.
    try:
        pid = dj.start(kind, {"coin": coin, "tf": tf, "signal": sig,
                                  "base": float(row.get("base") or 5.0),
                                  # 0 = let the job use the PAIR'S OWN span; a
                                  # flat 365 made the trade floor demand a
                                  # year's evidence from 103 days of candles
                                  "days": 0})
    except (dj.JobBusy, dj.LocalSweepsOff) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"started": True, "pid": pid, "row": rid, "store": store,
            "kind": kind,
            "coin": coin, "tf": tf, "signal": sig,
            # SAY THE DOWNLOAD OUT LOUD. It is the half the operator asked
            # for, and a job that fetches candles for a minute before it
            # measures reads as a stall if nothing said it would.
            "why": f"downloading {coin}'s newest candles, then re-measuring "
                   f"{tf} {sig} from its last measured bar to now"}


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

    PENDING = pairs a backtest TRIED and FAILED (2026-09-09: "pending only
    means these are the backtest that had problem during the update backtest
    or backtest button"). Pairs simply never swept — 117 of them, whether any
    run ever reached them or not — are still reported, under
    `never_measured`, because they are worth seeing; they are just not a
    problem, and a count including them cannot reach zero.
    """
    from tradingagents import backtest_logs as bl, pending_ledger as pl

    got = bl.logs(include_cloud=cloud)
    broke = pl.summary("backtest")
    never = got.get("pending") or {}
    return {**got, "pending": {**never, "count": broke["count"],
                               "failed_pairs": broke["pairs"],
                               "never_measured": int(never.get("count") or 0)}}


def _busy_run_covers(by_tf: dict):
    """(frames the in-progress run measures, pending frames it does NOT).

    Read from the dispatch's own record, and only when that record names the
    run GitHub is actually running — a stale entry for a finished run must not
    be reported as coverage. `(None, {})` means we do not know, which is said
    out loud rather than guessed.

    Two records are consulted: the autopilot's (historical — it stopped
    dispatching on 2026-09-09: "no no no, i want option to start the
    backtest") and `cloud_sweep.remembered()`, which every BUTTON dispatch
    writes and which carries the run's `timeframes` since the same date.
    """
    from tradingagents import cloud_autopilot as ca, cloud_sweep as cs

    try:
        live = cs.working_run() or {}
        if not live.get("id"):
            return None, {}
        st = ca._read()
        if int(st.get("run") or 0) != int(live["id"]):
            st = cs.remembered()
            if int(st.get("id") or 0) != int(live["id"]):
                return None, {}
        # A RUN ASKED FOR NAMED COINS COVERS NO FRAME. Since Sep 10, 2026 a
        # dispatch can name its coins, so "that run covers 1h" would be true
        # of the timeframe and false of the work: a two-coin run leaves every
        # other pending 1h pair exactly as pending as it was
        # (label-must-match-data). Unknown is the honest answer.
        if list(st.get("coins_named") or []):
            return None, {}
        covered = list(st.get("timeframes") or [])
        if not covered:
            return None, {}
        return covered, {t: n for t, n in by_tf.items()
                         if n and t not in covered}
    except Exception:                                          # noqa: BLE001
        return None, {}


@app.post("/api/backtest/pending/resolve")
def backtest_pending_resolve() -> dict:
    """RESOLVE PENDING — measure every pair this PC has candles for but has
    never measured, in one dispatch.

    Operator, Sep 05, 2026: *"can you create a buitton called 'Resolve Pending'
    when i click this i want you to resolve all pending, currently there is 681
    pending"*.

    WHAT IT SENDS, and why that is honest rather than a "681 pairs" claim: the
    sweep workflow slices its coins BY INDEX inside each shard, so a run cannot
    be pointed at an arbitrary list of pairs. What it can be pointed at is
    TIMEFRAMES, and the pendings are exactly a set of frames — 4h: 318, 1d:
    211, 1h: 84, 30m: 36, 15m: 32 when the operator asked. So this dispatches
    the frames the pendings live in.

    The fleet will therefore re-measure pairs this machine has already done.
    That costs GitHub time and costs the store nothing: `collect_into_store`
    REFUSES to overwrite a pair whose local watermark is above zero, because
    that watermark promises every bar up to X was tested. And a collected pair
    DOES get a state file (`save_states` with `__cloud__`), which is what makes
    it stop being pending — without that, this button could never move the
    number it is named after.
    """
    from tradingagents import backtest_logs as bl, capacity as cap, cloud_sweep as cs, db_jobs as dj

    pend = bl.pending(force=True)          # never a cached count for an ACTION
    # MEASURABLE, not "never measured". `pending()` already splits out the
    # delisted contracts no fleet can reach and the pairs under their
    # timeframe's bar floor, which no sweep will ever produce a row for.
    # Measured Sep 06, 2026: 653 pending, 8 measurable, 645 too short, 24
    # delisted. Promising 653 would send twenty runners for an hour to measure
    # 8 pairs and leave the number at 645 for ever — a button that reads as
    # broken because it was asked to do the impossible.
    # PENDING = WHAT BROKE (2026-09-09: "pending only means these are the
    # backtest that had problem during the update backtest or backtest button,
    # resolve mean you will restart or resume where it crash"). So the frames
    # come from the FAILED pairs on the ledger, not from pairs nobody ever
    # swept. When nothing has failed, this button has nothing to do — and
    # saying so is the honest answer, not dispatching twenty machines at the
    # whole market.
    from tradingagents import pending_ledger as pl

    broke = pl.pending("backtest")
    broke_by_tf: dict = {}
    for r in broke:
        broke_by_tf[r.get("timeframe")] = broke_by_tf.get(r.get("timeframe"), 0) + 1
    frames = [t for t in ("15m", "30m", "1h", "4h", "1d") if broke_by_tf.get(t)]
    short, dead = pend.get("too_short", 0), pend.get("delisted", 0)
    dead_coins = pend.get("delisted_coins") or []
    if not frames:
        return {"dispatched": False, "pending": len(broke),
                "failed_pairs": [f"{r['symbol']} {r['timeframe']}" for r in broke],
                "never_measured": pend.get("count", 0),
                "too_short": short, "unreachable": dead,
                "unreachable_coins": dead_coins, "timeframes": [],
                "why": ("nothing is pending — no backtest has failed. "
                        + (f"{pend.get('count', 0)} pair(s) have never been "
                           f"measured, which is not a failure: press BACKTEST "
                           f"or UPDATE ALL BACKTESTS for those."
                           if pend.get("count") else ""))}
    ok, why = cs.available()
    if not ok:
        raise HTTPException(400, f"GitHub cannot take it: {why}")
    free, cwhy = cap.cloud_free()
    if not free:
        # One sweep at a time: two runs measure the same contracts and the
        # merge then has to choose a winner.
        #
        # WHAT THE BUSY RUN ACTUALLY COVERS. This used to say "the pending
        # pairs are measured by the run already going" — flatly untrue when
        # pressed on Sep 06, 2026: run 34004227228 was measuring 4h and 15m
        # only (the autopilot sends at most MAX_TFS frames), which is 350 of
        # the 677 pending. The other 327, on 1d/1h/30m, were not in it and the
        # refusal said they were. A refusal that lies about why is worse than
        # no refusal (label-must-match-data).
        covered, left = _busy_run_covers(pend["by_timeframe"])
        if covered is None:
            extra = ("Press this again when it finishes — what that run "
                     "covers is not recorded here.")
        elif left:
            extra = (f"That run covers {', '.join(covered)} only "
                     f"({pend['count'] - sum(left.values()):,} of "
                     f"{pend['count']:,} pending). It does NOT reach "
                     f"{', '.join(f'{t}: {n}' for t, n in left.items())} — "
                     f"press this again when it finishes and those go next.")
        else:
            extra = (f"That run covers {', '.join(covered)}, which is every "
                     f"pending frame — nothing is left for a second run.")
        raise HTTPException(409, f"GitHub is busy — {cwhy}. {extra}")
    spec = dj._read(dj.FILES["backtest"]["spec"]) or {}
    # NO coin_list ON PURPOSE: "resolve the pending" means every pending pair
    # in the store on these frames — the whole board IS the ask here, not the
    # dropped pick that the other four dispatch paths had (fixed Sep 10, 2026;
    # this one was read with them and left alone deliberately).
    run = cs.dispatch(shards=cap.CLOUD_RUNNERS, coins=0,
                      timeframes=",".join(frames), min_days=0,
                      # the operator's own window and stake, not a default
                      days=int(spec.get("days") or _sweep_days()),
                      base=float(spec.get("base") or 5.0))
    cs.remember(run)
    reach = pend.get("measurable", 0)
    rest = []
    if short:
        rest.append(f"{short:,} under their bar floor")
    if dead:
        rest.append(f"{dead} delisted ({', '.join(dead_coins)})")
    note = f" · the other {'; '.join(rest)}" if rest else ""
    # `pending` is the FAILURE count this button acted on (2026-09-09) — it
    # reported `pend["count"]`, the never-measured tally, so a dispatch for one
    # failed pair answered "pending: 0" while starting twenty machines.
    return {"dispatched": True, "run": run, "pending": len(broke),
            "failed_pairs": [f"{r['symbol']} {r['timeframe']}" for r in broke],
            "never_measured": pend.get("count", 0),
            "measurable": reach, "reachable": reach,
            "too_short": short, "unreachable": dead,
            "unreachable_coins": dead_coins,
            "timeframes": frames, "by_timeframe": broke_by_tf,
            "why": f"{len(broke):,} failed pair(s) — retrying over "
                   f"{', '.join(frames)}, GitHub run {run.get('id')}{note}"}


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
        # the STORE's slots: a v2 job publishes into ~/.tradingagents/v2/
        # workers, and this process's own WORKERS folder is v1's — the v2
        # screen showed v1's cores (Sep 18, 2026 review)
        _st = _stores.for_kind(kind) if kind.endswith("_v2") else None
        got["workers"] = msw.worker_read(
            workers_dir=(_st.home / "workers") if _st else None)
    return got


@app.post("/api/jobs/{kind}/start")
def job_start(kind: str, spec: dict) -> dict:
    _check_kind(kind)
    from tradingagents import db_jobs

    # a run the operator starts by hand is a fresh budget of retries, so an
    # earlier bad patch cannot leave the supervisor refusing to restart this one
    db_jobs.clear_retries(kind)
    try:
        return {"pid": db_jobs.start(kind, spec)}
    except db_jobs.LocalSweepsOff as exc:
        # 409, not 500: nothing is broken — this machine no longer measures.
        # A 500 would read as a crash and send the operator to the logs.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except db_jobs.JobBusy as exc:
        # 409 again: another job holds the disk; the message names it
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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

    if kind.endswith("_v2"):
        # the generic route accepted this and stopped the v2 job under
        # "handed over to GitHub Actions" while nothing could take it
        # (Sep 18, 2026 review, never fired)
        raise HTTPException(400, _V2_NO_CLOUD)
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

    ok, why = ((False, _V2_NO_CLOUD) if kind.endswith("_v2")
               else cs.available())
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
def ledger(limit: int = 500, actions: str | None = None) -> dict:
    """The trade ledger, newest first.

    `actions` names the rows the caller wants — "enter,exit" for TRADES.
    Without it a caller asking for the newest 200 rows gets 200 LEDGER rows,
    and this ledger is almost entirely refusals: measured Sep 09, 2026 on the
    operator's own file, 3,666 rows of which 2,868 were `gate_blocked` and 552
    `blocked`, against 6 `enter` and 6 `exit`. The newest 200 spanned 23 hours
    and held 2 of the 12 trades.

    That is what hid a real demo trade. Row #YDMRLEZ5 (KITE 1h squeeze, SL 3 /
    TP 3, flat) showed one loss, the runner had taken it on paper at
    Sep 07, 2026 5:01pm for -3.19, and the history panel could not show it: the
    exit sat 640 rows from the end and the panel filtered to trades AFTER the
    server had already thrown them away.

    `total` stays the whole ledger's length — the panel prints it as "N lines
    on this PC", which is what it is. `matched` is how many rows the filter
    left, so a caller can tell "no trades" from "no ledger".
    """
    import tradingagents.auto_trader as at

    rows = at.ledger_tail(100000)
    want = {a.strip() for a in (actions or "").split(",") if a.strip()}
    kept = [r for r in rows if r.get("action") in want] if want else rows
    return {"rows": kept[:max(0, min(limit, 5000))],
            "total": len(rows), "matched": len(kept),
            "actions": sorted(want)}


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


def _slot_stats(stats: dict, key: str, coin: str | None) -> dict:
    """The record for ONE deployed row — this strategy on THIS contract.

    `stats` is keyed by `book_slot(strategy, symbol)`. A row with a coin reads
    its own slot and nobody else's; a row with NO coin (the catalog listing,
    and only that) sums every contract the key has traded, because that is the
    honest answer to "what has this strategy ever done" when no contract has
    been chosen yet.

    Grouping by strategy alone is what made the demo cell read **69W / 3L**
    while the ledger held **30W / 6L** across 26 deployed ids
    (`.claude/skills/deploy-by-id`).
    """
    if coin:
        return dict(stats.get(f"{key}|{coin}") or {})
    out = {"pnl": 0.0, "wins": 0, "losses": 0, "trades": 0}
    for slot, got in stats.items():
        if slot != key and not slot.startswith(f"{key}|"):
            continue
        out["pnl"] += float(got.get("pnl") or 0.0)
        out["wins"] += int(got.get("wins") or 0)
        out["losses"] += int(got.get("losses") or 0)
        out["trades"] += int(got.get("trades") or 0)
    out["pnl"] = round(out["pnl"], 2)
    n = out["wins"] + out["losses"]
    out["winrate"] = round(100 * out["wins"] / n, 1) if n else 0.0
    return out


def _slot_today(today: dict, key: str, coin: str | None) -> float:
    """Today's realized PnL for ONE deployed row, same keying as above."""
    if coin:
        return round(float(today.get(f"{key}|{coin}") or 0.0), 2)
    return round(sum(float(v or 0.0) for slot, v in today.items()
                     if slot == key or slot.startswith(f"{key}|")), 2)


def _book_record(stats: dict, today: dict, key: str, armed: bool,
                 coin: str | None = None) -> dict:
    """One book's realized record for one DEPLOYED ROW, as the screen shows it."""
    got = _slot_stats(stats, key, coin)
    return {"pnl": round(float(got.get("pnl") or 0.0), 2),
            "trades": int(got.get("trades") or 0),
            "wins": int(got.get("wins") or 0),
            "losses": int(got.get("losses") or 0),
            "winrate": got.get("winrate"),
            "today": _slot_today(today, key, coin),
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
    # BY CONTRACT, because this grid is one row per deployed id. Keyed by
    # strategy alone, `willr14_30m_sl2tp05`'s record was printed identically
    # on all five of its coins and the demo cell totalled 69W/3L against a
    # ledger holding 30W/6L (`.claude/skills/deploy-by-id`).
    stats_real = at.strategy_stats(dry=False, by_coin=True)
    stats_paper = at.strategy_stats(dry=True, by_coin=True)
    state = at.load_state()
    limits = settings.get("strategy_loss_limits") or {}
    sizing_now = at.sizing_for(settings)          # the account-wide default
    runstate = at.load_state()
    tripped = at.tripped_strategies(settings)
    locks = at.timeframe_locks(settings)
    # PER BOOK. This was `dry=False` for every row, so a demo-only row printed
    # the real book's today — always 0.00 for a strategy that has never traded
    # real money, whatever its demo did (label-must-match-data).
    # READ ONCE, not per row: the deploy log is 1,104 lines and this route is
    # polled every 5 seconds by the grid.
    from tradingagents import local_history as _lh
    # THE DEPLOY LOG FIRST, THE SETTINGS BACKUPS AS THE FALLBACK. The log
    # only sees a row that went through SAVE, and 113 of the operator's 120
    # rows were deployed by writing the settings file directly (their 280
    # pasted ids, Sep 16, 2026), so the column was blank on 113 rows:
    # *"fill up the deployed date column now i want the value when i did
    # added this strategy"*. `deployed_at()` falls back to the first saved
    # copy of the settings that holds the pair, and returns the copy BEFORE
    # it as well — a window, never a bare upper bound dressed as a fact.
    _armed_since = _lh.deployed_at()
    today_real = at.pnl_today_by_strategy(dry=False, by_coin=True)
    today_paper = at.pnl_today_by_strategy(dry=True, by_coin=True)
    deployed = [k for k in at.STRATEGY_ORDER
                if (books.get(k) or coins.get(k))]
    keys = at.STRATEGY_ORDER if catalog else deployed
    rows = []
    for key in keys:
        spec = at.STRATEGY_SPECS.get(key) or {}
        base_m = float(margins.get(key) or 5.0)
        # book keys are "SYMBOL" (real) and "SYMBOL#paper" (simulated), so the
        # coin name is what precedes '#' and the book is which side it came from
        open_real_on, open_paper_on = [], []
        for bkey, v in state.items():
            pos = v.get("position") if isinstance(v, dict) else None
            if not pos or pos.get("strategy") != key:
                continue
            coin = bkey.split("#", 1)[0]
            (open_paper_on if pos.get("dry") else open_real_on).append(coin)
        # ONE ROW PER COIN — never one row for five (Sep 16, 2026).
        #
        # A strategy KEY is `signal_timeframe_slXtpY`; the COIN is not in it,
        # so `willr14_30m_sl2tp05` ended up armed on DVNSTOCK, FASTSTOCK,
        # KKRSTOCK, ROLSTOCK and VUG at once. This built ONE row for all five
        # and hashed its id from `coins[key][0]`, so every one of them was
        # labelled **#DM84QDSZ** — which is DVNSTOCK 30m willr14 2.00/0.50
        # flat, 168 trades, 97.62%, +$36.72. Four labels in five named a
        # contract the row was not trading. The operator, who deploys by id:
        # *"WHY IS #DM84QDSZ IN LIVE TRADE HAVE DIFFERENT COINS?"* and *"DONT
        # GROUP THEM AS ONE"*.
        #
        # A row id is coin + timeframe + signal + threshold + SL + TP +
        # sizing — all seven, hashed by `backtest_report.row_code`. Drop the
        # coin and it is a different measurement wearing the same name. So
        # the grid emits one row per contract, each carrying ITS OWN id, and
        # a key with no coins still emits exactly one row (id blank, nothing
        # to hash) so a catalog listing is unchanged.
        # See .claude/skills/deploy-by-id.
        for _coin in (coins.get(key) or [None]):
          _rid = row_id_for(key, _coin, settings)
          _row_coins = [] if _coin is None else [_coin]
          # THIS CONTRACT decides which ladder and which record the row reads.
          # It was `"real" in books.get(key)` — the bare key — so after the
          # switch went per contract a coin armed demo could still be drawn
          # with the live book's ladder and the live book's record.
          _is_real = "real" in at.book_names(settings, key, _coin)
          st_row = _slot_stats(stats_real if _is_real else stats_paper,
                               key, _coin)
          rows.append({
            "key": key,
            "id": _rid,
            # the human name, for the operator. Empty for rows that have none,
            # so the cell simply does not render rather than printing "None".
            "label": at.label_for(key, settings),
            "interval": spec.get("interval"),
            "tp": spec.get("tp"), "sl": spec.get("sl"),
            "threshold": spec.get("threshold"),
            # THIS CONTRACT'S switch, not the strategy's. A key armed live
            # on one coin must not paint the other four red (deploy-by-id).
            "books": at.book_names(settings, key, _coin),
            "coins": _row_coins,
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
                (int(at.slot_of(runstate, c, not _is_real, key)
                     .get("step", 0) or 0)
                 for c in _row_coins), default=0)),
            "streak_book": ("real" if _is_real else "paper"),
            # Only a REAL rung can be shared, and only by another real row on
            # the same coin. A demo row shares nothing now, so this list is
            # empty for it rather than naming strategies it no longer affects.
            "streak_shared_with": sorted(
                other for other in at.STRATEGY_ORDER
                if _is_real and other != key
                and "real" in (books.get(other) or [])
                and set(coins.get(other) or []) & set(_row_coins)),
            # WHEN THIS ROW WAS DEPLOYED (operator, Sep 17, 2026: "i dont
            # need ladder $ · flat column, instead put when was this
            # strategies deployed"). Keyed by strategy AND coin, because a row
            # IS a strategy on a contract — the same rule on two coins was
            # armed on two different days. None means the deploy log has no
            # record of this pair and the screen prints a dash: the log is
            # written by the SAVE path, so a pair configured another way has
            # no date, and inventing one would be a false label. Measured
            # Sep 17, 2026: 7 of the 120 rows on screen are in the log.
            "deployed_at": (_dep := _armed_since.get(f"{key}|{_coin}") or {})
                           .get("at"),
            # set only when the date came from a settings backup: it is the
            # OTHER end of the window, so the screen can say "about" and
            # name both ends instead of printing a bound as a fact.
            "deployed_at_from": _dep.get("from"),
            # PER ROW. A row that runs flat must not be drawn with a ladder:
            # the ladder column is what the operator reads before deploying.
            "sizing": at.sizing_for(settings, key),
            # WHAT THE NEXT ORDER WILL ACTUALLY STAKE — asked of the same
            # function the runner calls, for THIS row's book, so the column
            # and the order can never disagree. With Martingale mode off it
            # is the base margin on every rung; with it on for this book the
            # base doubles once per loss in a row and drops back on a win
            # (operator, Sep 17, 2026).
            "martingale": at.martingale_on(settings, not _is_real),
            "ladder": ([base_m] if not at.martingale_on(settings, not _is_real)
                       else [round(base_m * (2 ** n), 2) for n in range(7)]),
            "ladder_rung": (streak if at.martingale_on(settings, not _is_real)
                            else 0),
            "next_stake": round(
                at.staked_margin(key, settings, streak, not _is_real), 2),
            "notional": round(base_m * at.LEVERAGE, 2),
            "tripped": key in tripped,
            "live_locked": locks.get(key),
            # the row's OWN book and OWN contract
            "today": _slot_today(today_real if _is_real else today_paper,
                                 key, _coin),
            "pnl": round(float(st_row.get("pnl") or 0.0), 2),
            "trades": int(st_row.get("trades") or 0),
            "wins": int(st_row.get("wins") or 0),
            "losses": int(st_row.get("losses") or 0),
            # ...and BOTH books, so the screen can show them side by side. A
            # strategy ticked LIVE and DEMO has two separate records and they
            # must never be blended into one "record" the operator judges it
            # by — `strategy_stats(dry=...)` keeps them apart at the source.
            "real": _book_record(stats_real, today_real, key,
                                 "real" in at.book_names(settings, key, _coin),
                                 _coin),
            "paper": _book_record(stats_paper, today_paper, key,
                                  "paper" in at.book_names(settings, key, _coin),
                                  _coin),
            # only THIS contract's open positions — the row is one coin now.
            # A row with NO configured coin still reports everything it holds:
            # the position is the only evidence there is, and filtering it
            # against an empty list would hide an open trade from the one
            # column that exists to show it.
            "open_on": ([c for c in open_real_on if c in _row_coins]
                        if _row_coins else open_real_on),
            "open_on_paper": ([c for c in open_paper_on if c in _row_coins]
                              if _row_coins else open_paper_on),
          })
    return {
        "rows": rows,
        "sizing": at.sizing_for(settings),
        "conflicts": at.timeframe_conflicts(settings),
        # Counted here so the screen's caption cannot invent its own number —
        # and counted off the ROWS, because a row is one deployed id now.
        # These read `books.get(key)`, the bare strategy key, which stopped
        # holding the switch when arming went per contract. On the operator's
        # own config that printed *"0 trading REAL money · 0 paper only · 85
        # deployed but switched off"* over 120 rows every one of which was
        # armed demo (label-must-match-data, `.claude/skills/deploy-by-id`).
        "real_count": sum(1 for r in rows if "real" in (r["books"] or [])),
        "paper_count": sum(1 for r in rows if (r["books"] or [])
                           and "real" not in r["books"]),
        "idle_count": sum(1 for r in rows
                          if (r["coins"] or []) and not (r["books"] or [])),
        "deployed_count": sum(1 for r in rows
                              if (r["books"] or []) or (r["coins"] or [])),
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
    # Same 409, same reason as the row UPDATE button: another job holding the
    # disk is something to wait for, not a crash to report.
    try:
        return {"pid": db_jobs.start("stratbt", {
            "key": key, "label": body.get("label") or key, "coins": coins,
            "base_margin": margin,
            "days": int(body.get("days") or _sweep_days())})}
    except (db_jobs.JobBusy, db_jobs.LocalSweepsOff) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/trade/settings")
def trade_settings_get() -> dict:
    import tradingagents.auto_trader as at

    return {"settings": at.load_settings()}


@app.post("/api/trade/settings")
def trade_settings_post(payload: dict) -> dict:
    """Save auto_trade.json. The deploy history records every change.

    TWO live strategies on one coin used to be REFUSED here. Since 2026-09-04
    they are allowed, on the operator's instruction — they armed 35 rows over
    9 coins, 20 of them on GPNSTOCK — because the protection moved to the
    RUNTIME and got stronger there: a coin with a position open accepts no
    other strategy's signal until it closes, whoever opened it
    (`auto_trader._busy_refusal`, tests/test_one_position_per_coin.py). MEXC
    nets by CONTRACT, and one open position per contract is exactly what that
    rule guarantees. `timeframe_locks` returns {} now; the check is kept so a
    future lock has somewhere to live.
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


@app.post("/api/trade/losscap/reset")
def trade_losscap_reset(body: dict) -> dict:
    """The RESET CAP button: forgive today's counted loss, delete nothing."""
    import tradingagents.auto_trader as at

    if body.get("confirm") is not True:
        raise HTTPException(400, "reset requires confirm=true")
    got = at.reset_loss_cap()
    got["ok"] = True
    return got


@app.post("/api/trade/record/reset")
def trade_record_reset(body: dict) -> dict:
    """The RESET W/L button. Requires {"confirm": true}; archives, never
    deletes. Resetting the real book also resets today's loss-cap counter —
    the response says so, and the button's confirm text says it first."""
    import tradingagents.auto_trader as at

    if body.get("confirm") is not True:
        raise HTTPException(400, "reset requires confirm=true")
    books = [b for b in (body.get("books") or ["paper", "real"])
             if b in ("paper", "real")]
    if not books:
        raise HTTPException(400, "books must name paper and/or real")
    try:
        got = at.reset_record(books)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    got["ok"] = True
    return got


@app.post("/api/trade/runner/start")
def runner_start() -> dict:
    import tradingagents.auto_trader as at

    return {"pid": at.start_runner()}


@app.post("/api/trade/runner/stop")
def runner_stop() -> dict:
    import tradingagents.auto_trader as at

    return {"stopped": at.stop_runner()}


@app.get("/api/trade/feed")
def trade_feed() -> dict:
    """What the RUNNER's websocket is seeing, straight from its own socket.

    The runner holds the feed in its own process, so it publishes to
    `live_price.json` from the feed thread every couple of seconds and this
    reads that. The screen therefore shows the connection being proven, not a
    second one opened to agree with it.

    `age` is how old the file is: a feed that stopped writing must read as
    stopped, never as the last price it happened to see (label-must-match-data).
    """
    import json as _json

    from tradingagents import live_price as _lp

    try:
        raw = _json.loads(_lp.STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        return {"running": False, "connected": False,
                "why": "the runner has not published a feed status — it is "
                       "either not running or has no coin to listen to"}
    now = _time.time()
    age = now - float(raw.get("written_at") or 0)
    rows = []
    for sym, d in sorted((raw.get("last") or {}).items()):
        rows.append({"symbol": sym, "price": d.get("price"),
                     "at": d.get("at"), "ticks": d.get("ticks"),
                     "age": round(now - float(d.get("at") or 0), 2)})
    # the file can outlive the process that wrote it
    fresh = age < 30
    return {"running": fresh, "connected": bool(raw.get("connected")) and fresh,
            "logged_in": bool(raw.get("logged_in")),
            "stale": bool(raw.get("stale")) or not fresh,
            "url": raw.get("url"), "messages": raw.get("messages"),
            "connects": raw.get("connects"), "tracking": raw.get("tracking"),
            "klines": raw.get("klines"), "armed": raw.get("armed"),
            "last_error": raw.get("last_error"),
            "status_age": round(age, 2), "prices": rows}


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
    scoins = settings.get("strategy_coins") or {}
    sizing = at.sizing_for(settings)
    want_c = {c for c in coins.split(",") if c}
    want_t = {t for t in tfs.split(",") if t}
    out = []
    # ONE ENTRY PER DEPLOYED ROW. `strategy_books` holds both the bare key and
    # `strategy|COIN` since Sep 16, 2026, so iterating it raw would hand
    # `willr14_30m_sl2tp05|VUG_USDT` to STRATEGY_SPECS as if it were a
    # strategy name and silently drop the row. Walk the STRATEGIES instead and
    # ask `book_names` per contract.
    for key in at.STRATEGY_ORDER:
        bk = sorted(at.book_names_any(settings, key))
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
_WORKING_RUN: dict = {"at": 0.0, "run": None}
_WORKING_RUN_TTL = 45.0        # the panel polls every 4 s; `gh` must not


def _working_run_cached() -> dict | None:
    """The run GitHub is really measuring, at most once every 45 seconds."""
    import time as _t

    from tradingagents import cloud_sweep as cs

    if _t.time() - _WORKING_RUN["at"] < _WORKING_RUN_TTL:
        return _WORKING_RUN["run"]
    try:
        got = cs.working_run()
    except Exception:                                          # noqa: BLE001
        got = None                     # never let the panel fail on this
    _WORKING_RUN.update({"at": _t.time(), "run": got})
    return got


@app.get("/api/cloud/status")
def cloud_status() -> dict:
    """Whether GitHub Actions can be used, and what the remembered run is
    doing — per machine, not just "20 running", which told the operator
    nothing (2026-08-20).

    ANSWERS AT ONCE, from the last background read. Measured Sep 09, 2026:
    the read below took **216.3 s** (`gh` for the live run, a status call, then
    `git fetch` plus a `git show` per shard), the panel asks every 4 s, and
    four of those sat in flight holding every browser lane — so the operator's
    filtered table request never left the browser ("searching 306s") while the
    API was perfectly healthy. Same disease as `/api/backtest/logs` the same
    morning (RCA-A); same cure: the request never waits for GitHub.
    """
    return _CLOUD_STATUS.get(pending={
        "available": False, "why": "reading GitHub in the background",
        "reading": True, "run": None, "shards": []})


def _read_cloud_status() -> dict:
    """The slow read. Runs in `_CLOUD_STATUS`'s background thread only."""
    from tradingagents import cloud_sweep as cs

    ok, why = cs.available()
    out = {"available": ok, "why": why, "run": None, "shards": []}
    # WHAT IS MEASURING beats what this machine last dispatched. `remembered()`
    # holds only our own last dispatch, so a run started by the autopilot, the
    # orchestrator, another PC or a session whose remember-file was cleared was
    # invisible: on Sep 05, 2026 the panel showed nothing while run 33954675312
    # had been measuring for 36 minutes and the operator said "i cannot see it
    # running in ui". A STALE remembered run hides a live one the same way,
    # which is the 2026-08-25 shape — three runs at once and the wrong one
    # adopted, reporting "0/0 shards" while the cloud was most of the way
    # through the grid. So the live run wins, and the remembered one is the
    # fallback that keeps a finished run's summary on screen.
    #
    # CACHED: this endpoint is polled every 4 s by the panel, and `working_run`
    # costs a `gh run list` plus a status call per live run. Polling the REST
    # API burned 5,000 requests in an hour on 2026-08-25 and blinded every tool
    # at once.
    run = (_working_run_cached() if ok else None) or cs.remembered()
    if run and run.get("id"):
        out["run"] = run
        try:
            out.update(cs.status(int(run["id"])))
        except Exception as exc:                               # noqa: BLE001
            out["why"] = f"{type(exc).__name__}: {exc}"
        # IS IT ALREADY IN THE STORE? A finished run stays on screen as its
        # own summary, and until Sep 15, 2026 it kept offering MERGE INTO
        # THIS PC whatever had already happened to it. Run 34631292767
        # finished `Sep 12, 2026 2:05am`, landed 85,352,010 rows over 4,266
        # pairs LIVE while it ran, was collected, and was superseded by five
        # newer collected runs — and the card still asked the operator to
        # merge it. Pressing that downloads twenty shard files to write
        # nothing (label-must-match-data).
        try:
            from tradingagents import cloud_autopilot as _ap

            out["collected"] = int(run["id"]) in set(
                _ap._read().get("collected") or [])
        except Exception:                                      # noqa: BLE001
            out["collected"] = False
        try:
            out["shards"] = cs.live_progress(int(run["id"]),
                                             run.get("repo") or None)
        except Exception:
            out["shards"] = []
        # THE OTHER ACCOUNTS' RUNS. Since Sep 21, 2026 one press can dispatch
        # to the operator's account and their partner's fork at once ("i want
        # 40"), and a tile that shows one of them says 20 machines about 40 —
        # the label-must-match-data failure this repo keeps paying for. Each
        # sibling costs ONE cached `gh` call in this background reader.
        sib = []
        for other in (run.get("runs") or []):
            rid2, slug2 = other.get("id"), other.get("repo") or ""
            if not rid2 or int(rid2) == int(run["id"]):
                continue
            row = {"id": int(rid2), "repo": slug2,
                   "url": other.get("url") or "",
                   "coins": int(other.get("coins") or 0)}
            try:
                st2 = cs.status(int(rid2), slug2 or None)
                row.update({k: st2.get(k) for k in
                            ("running", "queued", "done", "total",
                             "conclusion")})
            except Exception as exc:                           # noqa: BLE001
                row["why"] = f"{type(exc).__name__}: {str(exc)[:80]}"
            sib.append(row)
        if sib:
            out["siblings"] = sib
            out["accounts"] = 1 + len(sib)
            # EVERY ACCOUNT'S MACHINES ON THE TILE. Each run publishes its
            # progress to its OWN account's `sweep-progress` branch, so a
            # 40-machine press showed at most the lead run's 20 — and, while
            # the lead run was the one still queued, none at all. Measured
            # Sep 22, 2026 11:16pm: 15 machines reporting on the fork and 20
            # on the operator's account, and the panel drew zero.
            for row in sib:
                try:
                    out["shards"] += cs.live_progress(int(row["id"]),
                                                      row.get("repo") or None)
                except Exception as exc:                       # noqa: BLE001
                    row["progress_why"] = f"{type(exc).__name__}: {str(exc)[:80]}"
            # the totals the tile prints come from the same list it draws
            out["running"] = int(out.get("running") or 0) + sum(
                int(r.get("running") or 0) for r in sib)
            out["queued"] = int(out.get("queued") or 0) + sum(
                int(r.get("queued") or 0) for r in sib)
    # IS THE DOOR OPEN, and what has actually come through it — counted by THIS
    # PC, never by the machines' own claim (operator, Sep 09, 2026: "i want you
    # to post the result immediately to my pc"). The tally belongs to the run
    # on screen or it is not shown: a previous run's count under this run's
    # name is the label-must-match-data failure this repo keeps paying for.
    try:
        from tradingagents import live_ingest as li

        got = li.status()
        prog = got.get("progress") or {}
        rid = str((run or {}).get("id") or "")
        out["live"] = {"open": bool(got.get("open")), "url": got.get("url") or "",
                       **({"pairs": int(prog.get("pairs") or 0),
                           "rows": int(prog.get("rows") or 0),
                           # coins that ARRIVED and were already up to date —
                           # without this the screen reads "0 pairs written"
                           # for a door that worked perfectly (run
                           # 34370227474, Sep 09, 2026 11:28pm: both coins
                           # posted, both refused, nothing new had printed
                           # since the run five minutes earlier)
                           "stale": int(prog.get("stale") or 0),
                           "at": prog.get("at"), "last": prog.get("last")}
                          if rid and str(prog.get("run") or "") == rid else {})}
    except Exception:                                          # noqa: BLE001
        out["live"] = {"open": False}
    return out


# How long a cloud-status answer is reused before the background thread reads
# again. Shard progress moves on the order of minutes; the panel polls every
# 4 s; the read itself was 216 s on Sep 09, 2026.
#
# 30 -> 90 (Sep 12, 2026). The read is a `git fetch` of the progress branch
# plus a `git show` per shard, and with all 20 shards reporting it measured
# **31.9 s** end to end (the fetch alone 33.4 s on a second run). A TTL
# SHORTER THAN THE READ means the value is stale the instant it lands, so the
# background thread runs back to back for the whole sweep — one git fetch
# every half minute, for hours, against the same branch the shards are
# pushing to. `BackgroundValue` still serves the last answer while it works,
# so the only thing a longer TTL costs is up to 90 s of age on a number that
# moves in minutes; `PROGRESS_CACHE_S` (15 s) already bounds it below.
# Measure the read before choosing the interval that drives it.
CLOUD_STATUS_TTL = 90.0
# HOW LONG `rows_index.status()` REALLY TAKES, measured Sep 10, 2026 on the
# rebuilt 41.94 GB store: **267.55 s**. It walks `stale_pairs()`, which stats
# every one of 5,367 pair files AND their state files, so on a cold cache it is
# minutes — and `/api/strategies` called it INSIDE the request, on a route the
# panel polls. Pattern 4 in docs/RCA.md exists for this exact shape ("a polled
# route must never do the slow thing inside the request"), written after two
# routes took the page down the same way one day apart. This is the third.
#
# 20 s of staleness on "how far behind is the index" costs nothing: the number
# moves a pair at a time over hours.
INDEX_STATUS_TTL = 20.0
_INDEX_STATUS = BackgroundValue(
    "index-status",
    lambda: __import__("tradingagents.rows_index",
                       fromlist=["x"]).status(),
    ttl=INDEX_STATUS_TTL,
    # a failed read keeps the shape the panel reads, and says why — never a
    # zero, which would claim an empty store (RCA-2026-09-10-F)
    on_error=lambda exc: {"pairs_indexed": None, "rows": None, "behind": None,
                          "stale": None,
                          "unreadable": f"{type(exc).__name__}: {exc}"})


def index_status(pending: dict | None = None) -> dict:
    """`rows_index.status()`, from the background reader.

    `pending` is what a caller gets while the first read is still running —
    the panel needs the KEYS to exist, and `None` for a count reads as
    "not known yet" rather than as zero.
    """
    return _INDEX_STATUS.get(pending=pending or {
        "pairs_indexed": None, "pairs_on_disk": None, "behind": None,
        "stale": None, "rows": None, "reading": True,
        # None, never False: "not known yet" and "no indexer is running" are
        # different sentences and the screen prints a different one for each.
        # Leaving the key out made a missing value read as "catching up on
        # its own", which is the reassurance that was wrong for a day.
        "indexer_running": None, "paused_by": ""})


# BACKTEST v2's status, cached the same way and for the same reason: the v2
# routes called `ri.status(db_path=...)` inline on a polled route, and its
# per-pair watermark read grows with the store (Sep 18, 2026 review).
_INDEX_STATUS_V2 = BackgroundValue(
    "index-status-v2",
    lambda: __import__("tradingagents.rows_index",
                       fromlist=["x"]).status(db_path=_stores.V2.rows_db),
    ttl=INDEX_STATUS_TTL,
    on_error=lambda exc: {"pairs_indexed": None, "rows": None, "behind": None,
                          "stale": None, "filed_by": "job",
                          "unreadable": f"{type(exc).__name__}: {exc}"})


def index_status_v2() -> dict:
    """`rows_index.status()` over the v2 store, from the background reader."""
    return _INDEX_STATUS_V2.get(pending={
        "pairs_indexed": None, "pairs_on_disk": None, "behind": None,
        "stale": None, "rows": None, "reading": True,
        "indexer_running": None, "paused_by": "", "filed_by": "job"})


_CLOUD_STATUS = BackgroundValue(
    "cloud-status", _read_cloud_status, ttl=CLOUD_STATUS_TTL,
    # a failed read is an answer too — and it keeps the panel's shape
    on_error=lambda exc: {"available": False,
                          "why": f"{type(exc).__name__}: {exc}",
                          "run": None, "shards": []})


@app.post("/api/cloud/dispatch")
def cloud_dispatch(body: dict) -> dict:
    """Run the same grid on GitHub's machines. Their rows land in an artifact
    that must be MERGED into this Mac's store — nothing is written remotely."""
    from tradingagents import cloud_sweep as cs

    ok, why = cs.available()
    if not ok:
        raise HTTPException(400, why)
    # BACKTEST = from scratch, always: mode "full" is the deliberate reset.
    # UPDATE goes through the btupdate job, which dispatches mode "update".
    # WHICH coins, by name. `coins` is only the per-machine cap, and sending
    # it alone is how "BACKTEST with BTC picked" measured 0G, ALPINE, AVAAI…
    # and never BTC (Sep 10, 2026). An empty list still means the whole market.
    # EVERY ACCOUNT. Operator, Sep 21, 2026: "i want 40" — one free account
    # runs ~20 machines, and this press used one. `dispatch_across` deals the
    # coins between the accounts this checkout has remotes for; with one
    # remote it is the single run it always was. An EMPTY pick means the whole
    # market, which cannot be split unless it is named, so the store's own
    # coin list is sent (the same list the machines would have worked out).
    _picked = [str(c) for c in (body.get("coin_list") or [])]
    if not _picked:
        from tradingagents import db_jobs as _dj

        _res = str(body.get("res") or "")
        _picked = [s.replace("_USDT", "") for s in
                   _dj.stored_symbols(store="v2" if _res == "1m" else "v1")]
    got = cs.dispatch_across(shards=int(body.get("shards") or 20),
                      coins=int(body.get("coins") or 0),
                      coin_list=_picked,
                      timeframes=str(body.get("timeframes") or "15m,30m"),
                      min_days=int(body.get("min_days") or 0),
                      days=int(body.get("days") or _sweep_days()),
                      base=float(body.get("base") or 5.0),
                      # BACKTEST v2 ON THE FLEET. Operator, Sep 21, 2026:
                      # *"i want backtest to run on github ... the only
                      # difference is v2 will be using 1min candles"*. "1m"
                      # tells the shard to rebuild every frame from minutes
                      # and settle each exit minute by minute; "" is v1,
                      # byte-identical to before.
                      res=str(body.get("res") or ""),
                      mode="full")
    runs = got.get("runs") or []
    # the panel still reads ONE run id; the record keeps them all so the
    # collect chases every account's artifacts
    run = {**(runs[0] if runs else {}), "runs": runs, "why": got.get("why")}
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
    # THE STORE THE RUN WAS MEASURED FOR, and the ACCOUNT its artifacts are
    # on. Since Backtest v2 went to GitHub (Sep 21, 2026) and a press deals
    # the board across two accounts (Sep 22), collecting here in the API
    # process — which runs in v1's environment and asks origin — would refuse
    # every row of a v2 run (`land_rows` guards the store) and would look for
    # a partner's artifacts in the operator's repo. Hand it to the same
    # detached job the autopilot uses, which is spawned with that store's
    # environment and is told which repo to ask.
    import contextlib

    from tradingagents import db_jobs as dj

    res = cs.run_res(run_id)
    slug = ""
    with contextlib.suppress(Exception):
        rec = cs.remembered() or {}
        for one in [rec, *(rec.get("runs") or [])]:
            if int(one.get("id") or 0) == run_id:
                slug = str(one.get("repo") or "")
                break
    if res == "1m":
        pid = dj.start("collect_v2", {"run": run_id, "repo": slug})
        return {"started": True, "kind": "collect_v2", "pid": pid,
                "run": run_id, "repo": slug, "fetched": 0,
                "why": "Backtest v2 rows land in the v2 store, so the v2 "
                       "collect job is doing it — watch it on this screen"}
    got = cs.collect_into_store(run_id, slug or None)
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
def trade_history(dry: bool = False, per_page: int = 5, page: int = 1,
                  q: str = "") -> dict:
    """Every CLOSED trade on one book, newest first, with its running total —
    plus a per-month summary the page cannot give.

    Paginated because a wall of 200 rows hides a trade as effectively as a net
    figure does. The running total is computed oldest-first over the WHOLE
    book, so page 3's 'running $' is the real running total, not the page's.

    `q` SEARCHES BOTH BOOKS AT ONCE and ignores `dry`. Operator,
    `Sep 17, 2026`: *"in trade history, put a id search there, when i search
    LG9NSU4B for example it should show trade id LG9NSU4B for both live and
    demo trade"*. Both books stamp a trade with the SAME id, so a search that
    honoured the live/demo tab would show one of the two and look like the
    other did not happen — which is exactly the confusion that cost five
    answers about `MTX4FSGN` the day before.

    It matches the TRADE id or the STRATEGY id, with or without the leading
    `#`, either case. And it matches HERE, over every exit row on the ledger —
    never in the browser over a page the server already cut, which is the
    filter-where-the-data-is rule in CLAUDE.md, bought by a KITE loss that sat
    640 rows past the window a panel had fetched.

    While searching, `months` and `totals` describe the MATCHED rows, because
    a whole-book summary printed beside two matches is a false label. `total`
    is the number of matches and `examined` is how many closed trades were
    looked at, so an empty answer names what it checked instead of speaking
    for the store.
    """
    import datetime as dt

    import tradingagents.auto_trader as at
    from tradingagents import positions_view as pv

    _q = (q or "").strip().lstrip("#").upper()
    # a search spans BOTH books; without one the tab still rules
    _books = (False, True) if _q else (dry,)
    _all = at.ledger_tail(100000)
    _exits = [e for e in _all if e.get("action") == "exit"]
    _examined = len(_exits)

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
    # THE STRATEGY'S OWN ID, beside the trade's (operator, Sep 10, 2026:
    # "in trade history expose the strategy id as well"). The same
    # `row_id_for` the strategies grid and the positions table use, so one
    # combination has one name on every screen — and it is the id to paste
    # into a report's find-by-ID box. Settings are read ONCE: this loop runs
    # over the whole book.
    _settings = at.load_settings()
    _sid: dict = {}

    def _strategy_id(key: str, symbol: str) -> str:
        k = (key, symbol)
        if k not in _sid:
            try:
                _sid[k] = row_id_for(key, symbol, _settings)
            except Exception:                                  # noqa: BLE001
                _sid[k] = ""
        return _sid[k]

    rows, months = [], {}
    # PER BOOK, because the running total belongs to its own book: a live
    # exit must never advance the practice book's running total.
    for _dry in _books:
      run = 0.0
      ex = sorted((e for e in _exits if bool(e.get("dry_run")) is _dry),
                  key=lambda x: float(x.get("ts") or 0))
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
              # blank when the key is not one the runner knows (an adopted
              # exchange position): a real-looking id that matches no
              # combination is worse than no id
              "strategy_id": _strategy_id(str(e.get("strategy") or ""),
                                          str(e.get("symbol") or "")),
              "why": e.get("why") or "—",
              "profit": p, "running": run,
            # WHICH BOOK. Both stamp the same trade id, so a row that
            # does not say which one it is turns two trades into one —
            # #MTX4FSGN read as a single trade for a whole evening.
            "book": "demo" if _dry else "live"})
          key = dt.datetime.fromtimestamp(float(e.get("ts") or 0)).strftime("%Y-%m")
          m = months.setdefault(key, {"key": key, "trades": 0, "wins": 0,
                                      "losses": 0, "profit": 0.0})
          m["trades"] += 1
          m["wins" if p > 0 else "losses"] += 1
          m["profit"] = round(m["profit"] + p, 2)
    if _q:
        rows = [r for r in rows
                if _q in str(r.get("id") or "").upper()
                or _q in str(r.get("strategy_id") or "").upper()]
        # the summary describes what is SHOWN, never the whole book
        months = {}
        for r in rows:
            k = dt.datetime.fromtimestamp(r["ts"]).strftime("%Y-%m")
            m = months.setdefault(k, {"key": k, "trades": 0, "wins": 0,
                                      "losses": 0, "profit": 0.0})
            m["trades"] += 1
            m["wins" if r["profit"] > 0 else "losses"] += 1
            m["profit"] = round(m["profit"] + r["profit"], 2)
    rows.sort(key=lambda r: r["ts"])
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
        # what was SEARCHED, so an empty answer names what it looked at
        # rather than speaking for the store (CLAUDE.md, Sep 12 2026)
        "q": _q, "examined": _examined,
        "books": ["live", "demo"] if _q else (["demo"] if dry else ["live"]),
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


def _warm_gap_index(store=None, cache=None) -> None:
    """Build the candle index off the request thread.

    A first build opens every stored pair (69s at 4,899 pairs) and would hold
    a request open past the UI proxy's timeout — so the route answers
    "indexing" and this fills it in.
    """
    import threading

    from tradingagents import market_sweep as msw

    cache = _GAP_CACHE if cache is None else cache
    root = None if (store is None or store.name == "v1") else store.candles
    if cache["building"]:
        return
    cache["building"] = True

    def run() -> None:
        try:
            if root is None:
                msw.candle_index()
            else:
                msw.candle_index(root=root)
        finally:
            cache["building"] = False
            cache["at"] = 0.0          # let the next call read it

    threading.Thread(target=run, daemon=True).start()


@app.get("/api/system/staleness")
def system_staleness() -> dict:
    """Which long-running process is still holding OLD CODE.

    Operator, Sep 04, 2026: *"SO WHAT'S NOT UPDATED?"* — the only way to answer
    was comparing process start times to `git log` by hand. The backtest job
    had been 24 commits behind for 32 hours and the live runner was holding a
    loss-cap version that killed the whole runner, two minutes stale.
    """
    from tradingagents import staleness

    return staleness.report()


def _candles_pending_for(store) -> dict:
    """PENDING = pairs a download or update TRIED and FAILED. Nothing else.

    Operator, 2026-09-09: *"pending only means these are the candles that had
    problem during the update candles or download candle, resolve mean you
    will restart or resume where it crash"*.

    `count` used to be behind + missing + lost, and "behind" is the CLOCK: a
    15m pair is behind fifteen minutes after any run, so the number went 0 at
    10:55pm to 5,095 by 9:33am with nothing failing. A freshness reading is
    not a problem list and could never reach zero.

    Everything else is still REPORTED, just not as pending: `behind` (how
    stale, the candle autopilot's job), `missing` (never stored), and
    `unfixable` (delisted, or the venue serves no candles). Each is its own
    field so nothing is hidden — only the MEANING of `count` changed.
    """
    from tradingagents import db_jobs, pending_ledger as pl, positions_view as pv

    v1 = store.name == "v1"
    got = db_jobs.pending_work(files_key=store.download_kind,
                               root=(None if v1 else store.candles),
                               tfs=tuple(store.tfs))
    broke = pl.summary("candles" if v1 else "candles_v2")
    return {**got,
            # the new meaning, and the old arithmetic kept under its own name
            # so a reader can see both
            "count": broke["count"], "failed_pairs": broke["pairs"],
            "count_stale_or_missing": int(got.get("count") or 0),
            "checked": pv.fmt_when(got.get("checked"))}


@app.get("/api/candles/pending")
def candles_pending() -> dict:
    return _candles_pending_for(_stores.V1)


@app.get("/api/v2/candles/pending")
def candles_pending_v2() -> dict:
    return _candles_pending_for(_stores.V2)


def _candle_gaps_for(store, cache) -> dict:
    """How far behind every stored pair is, so UPDATE can say what it fills.

    Nothing is fetched here — it reads the store's own last bar. A pair is
    "behind" when more than one bar could have printed since.
    """
    import time

    from tradingagents import backtest_report as br, market_sweep as msw, positions_view as pv

    # the scan opens one file per stored pair (4,899 today), so a repeat call
    # inside 30s gets the same answer rather than the same work
    now = time.time()
    if cache["payload"] and now - cache["at"] < 30:
        return cache["payload"]
    # never scan on a request thread: with a download running the files change
    # constantly, so even an incremental scan can outlast the proxy's timeout
    _warm_gap_index(store, cache)
    # `root` only for another store: tests stand in for `candle_index` with
    # fakes that take `scan` alone, and v1 must call it exactly as it always has
    index = (msw.candle_index(scan=False) if store.name == "v1"
             else msw.candle_index(scan=False, root=store.candles))
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
    cache.update({"at": now, "payload": payload})
    return payload


_GAP_CACHE_V2: dict = {"at": 0.0, "payload": None, "building": False}


@app.get("/api/candles/gaps")
def candle_gaps() -> dict:
    return _candle_gaps_for(_stores.V1, _GAP_CACHE)


@app.get("/api/v2/candles/gaps")
def candle_gaps_v2() -> dict:
    """The same answer for Backtest v2's 1-minute store."""
    return _candle_gaps_for(_stores.V2, _GAP_CACHE_V2)


# ------------------------------------------------------------- notifications
# One bell for "did the thing I clicked actually work". A click that reports
# nothing is indistinguishable from a click that failed silently — which is
# exactly how a 0-byte backtest report went unnoticed on 2026-08-20.

# ================================================================ Backtest v2
# Sep 17, 2026. The SAME handlers, pointed at ~/.tradingagents/v2 through
# `stores.V2`: rows.db via `rows_index.using_db`, candles via `root=`, the job
# files via the v2 kinds. An empty v2 store is a SENTENCE (CLAUDE.md, Sep 12,
# 2026: an empty page names what it examined), never a 500.
_V2_EMPTY_WHY = ("no v2 store yet — download 1m candles on Candles v2 first, "
                 "then press BACKTEST on Backtest v2")
_V2_NO_WINDOW = ("a MONTHS window has no CSV on Backtest v2 yet — the table "
                 "above is the window's own; export with a DAYS window "
                 "instead, which re-measures each row from the 1-minute store")
# THE REASON CHANGED ON Sep 21, 2026, so the sentence had to.
#
# It used to say the fleet has no 1-minute store. That stopped being true when
# Backtest v2 went to GitHub (`RES=1m`: each runner downloads its own minutes
# and rebuilds the frames). What is still missing is only the HAND-OFF half —
# `_finish_handoff` is hard-wired to the v1 job and reads v1's store to work
# out which coins were never reached — so pressing this would stop the v2 job
# and dispatch nothing.
#
# A refusal that gives a reason which is no longer true is worse than no
# reason: it sends the reader to fix the wrong thing. BACKTEST on Backtest v2
# dispatches the fleet directly and is the button to use.
_V2_NO_CLOUD = ("Backtest v2 measures on GitHub, but a mid-run HAND-OFF is "
                "still v1-only — press BACKTEST on Backtest v2 to dispatch "
                "the fleet directly instead")


def _v2_rows_db():
    """Backtest v2's rows.db, or None while there is no such file."""
    p = Path(_stores.V2.rows_db)
    return p if p.exists() else None


@app.get("/api/v2/strategies")
def strategies_v2(coin: str | None = None, tf: str | None = None,
                  signal: str | None = None, profitable: bool = False,
                  limit: int = 500, offset: int = 0,
                  sort: str = "profit", min_trades: int = 0,
                  min_winrate: float = 0.0, max_tp: float = 0.0,
                  max_sl: float = 0.0,
                  min_tp: float = 0.0, min_sl: float = 0.0,
                  tp_over_sl: bool = False,
                  asset: str | None = None,
                  sizing: str | None = None, row_id: str | None = None,
                  group: str | None = None,
                  months: int = 0, days: int = 0,
                  measured_days: int = 0,
                  desc: bool | None = None) -> dict:
    """`/api/strategies` over Backtest v2's rows. Every row carries `unclear`
    (trades whose exit minute touched both prices) and `res="1m"`; ids never
    collide with v1's (`backtest_report.row_code(res=)`)."""
    from tradingagents import rows_index as ri

    db = _v2_rows_db()
    if db is None:
        return {"rows": [], "total": 0, "store": "v2", "why": _V2_EMPTY_WHY,
                "index": {"rows": 0, "pairs_indexed": 0, "pairs_on_disk": 0,
                          "indexer_running": None}}
    # the same handler, reading v2's rows.db AND restating (days / months
    # windows, RESTATE_MAX row logs) from v2's 1-minute store with
    # minute-exact exits — `_STORE` is how the shared helpers learn which
    tok = _STORE.set(_stores.V2)
    try:
        with ri.using_db(db):
            got = strategies(coin=coin, tf=tf, signal=signal,
                             profitable=profitable, limit=limit, offset=offset,
                             sort=sort, min_trades=min_trades,
                             min_winrate=min_winrate, max_tp=max_tp,
                             max_sl=max_sl, min_tp=min_tp, min_sl=min_sl,
                             tp_over_sl=tp_over_sl, asset=asset, sizing=sizing,
                             row_id=row_id, group=group, months=months,
                             days=days, measured_days=measured_days, desc=desc)
    finally:
        _STORE.reset(tok)
    got["store"] = "v2"
    # the v2 index's own state, not v1's cached one (label-must-match-data)
    got["index"] = index_status_v2()
    return got


@app.get("/api/v2/strategies.csv")
def strategies_csv_v2(coin: str | None = None, tf: str | None = None,
                      signal: str | None = None, profitable: bool = False,
                      sort: str = "profit", min_trades: int = 0,
                      min_winrate: float = 0.0, max_tp: float = 0.0,
                      max_sl: float = 0.0,
                      min_tp: float = 0.0, min_sl: float = 0.0,
                      tp_over_sl: bool = False,
                      asset: str | None = None,
                      sizing: str | None = None, row_id: str | None = None,
                      group: str | None = None, months: int = 0, days: int = 0,
                      measured_days: int = 0,
                      desc: bool | None = None):
    """Every matching v2 row as CSV, streamed — `unclear` and `res` included."""
    from fastapi.responses import StreamingResponse

    from tradingagents import rows_index as ri

    db = _v2_rows_db()
    if db is None:
        raise HTTPException(404, _V2_EMPTY_WHY)
    if months:
        raise HTTPException(400, _V2_NO_WINDOW)
    try:
        ri.export_plan(coin=coin, signal=signal, sort=sort, row_id=row_id,
                       group=group, min_winrate=min_winrate,
                       min_trades=min_trades, desc=desc, db_path=db)
    except ri.SortNotReady as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    name = "v2-" + strategies_csv_name(coin, tf, signal, min_trades, sort,
                                       min_winrate=min_winrate, max_tp=max_tp,
                                       sizing=sizing, group=group,
                                       max_sl=max_sl, min_tp=min_tp,
                                       min_sl=min_sl, tp_over_sl=tp_over_sl,
                                       asset=asset, days=days)
    return StreamingResponse(
        strategies_csv_lines(coin=coin, tf=tf, signal=signal,
                            profitable=profitable, sort=sort,
                            min_trades=min_trades, min_winrate=min_winrate,
                            max_tp=max_tp, sizing=sizing, row_id=row_id,
                            group=group, max_sl=max_sl,
                            min_tp=min_tp, min_sl=min_sl,
                            tp_over_sl=tp_over_sl, asset=asset,
                            # the window re-measures from the v2 store's own
                            # 1-minute candles, exits settled by the minute:
                            # `store` travels with the generator because the
                            # request's ContextVar is not visible in the
                            # thread that drains it
                            days=days, measured_days=measured_days, desc=desc,
                            db_path=db, store=_stores.V2),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/v2/strategies/trades")
def strategy_trades_v2(q: TradesQuery) -> dict:
    """Every trade one v2 row made, replayed from the 1-minute store with
    exits settled minute by minute — so `#U9YP5N7L`'s Sep 16 stop reads
    `7:28am`, the minute the practice account saw, not the hour."""
    from tradingagents import market_sweep as msw

    if not _stores.V2.candles.exists():
        return {"log": [], "why": _V2_EMPTY_WHY}
    return msw.trades_for(q.coin, q.tf, signal=q.signal, th=q.th, sl=q.sl,
                          tp=q.tp, sizing=q.sizing, base_margin=q.base_margin,
                          store=_stores.V2)


_PORTFOLIO_CACHE: dict = {}
PORTFOLIO_TTL_S = 120


@app.get("/api/v2/portfolio")
def portfolio_forecast_v2(book: str = "demo", fresh: int = 0) -> dict:
    """What the ACCOUNT would do with every deployed row running together —
    the runner's own gates, the venue's own book readings, minute-exact exits
    (`portfolio_replay.forecast`) — beside what the practice book actually did
    on the same days. Three replays over ~50,000 minutes a coin take a few
    seconds, so the answer is kept for `PORTFOLIO_TTL_S` unless `fresh=1`."""
    from tradingagents import portfolio_replay as pr

    dry = book != "live"
    if not _stores.V2.candles.exists():
        return {"why": _V2_EMPTY_WHY, "book": "demo" if dry else "live"}
    hit = _PORTFOLIO_CACHE.get(dry)
    now = _time.time()
    if hit and not fresh and now - hit[0] < PORTFOLIO_TTL_S:
        return hit[1]
    try:
        out = pr.forecast(dry=dry)
    except Exception as exc:                                   # noqa: BLE001
        logger.exception("portfolio forecast failed")
        return {"why": f"the replay raised {type(exc).__name__}: {exc}",
                "book": "demo" if dry else "live"}
    # the same stable id the grid and the positions table print for the row
    # (kit item H): hashed from the combination, never a per-page sequence
    import tradingagents.auto_trader as at
    settings = at.load_settings()
    ids: dict[str, str] = {}
    for side in (out.get("account"), out.get("checked")):
        for r in (side or {}).get("rows") or []:
            try:
                r["id"] = row_id_for(r["key"], r["coin"], settings)
            except Exception:                                  # noqa: BLE001
                r["id"] = ""
            ids[r["row"]] = r["id"]
    # a twin names the row it copies BY ID, the way the screen names rows
    for side in (out.get("account"), out.get("checked")):
        for r in (side or {}).get("rows") or []:
            if r.get("twin_of"):
                r["twin_id"] = ids.get(r["twin_of"], "")
    out["computed_at"] = int(now)
    _PORTFOLIO_CACHE[dry] = (now, out)
    return out


@app.get("/api/v2/strategies/facets")
def strategy_facets_v2() -> dict:
    from tradingagents import rows_index as ri

    db = _v2_rows_db()
    if db is None:
        return {"coins": [], "tfs": [], "signals": [], "tps": [], "sls": [],
                "sizings": [], "store": "v2", "why": _V2_EMPTY_WHY}
    return {**ri.facets(db_path=db), "store": "v2"}


@app.get("/api/v2/backtest/storage")
def backtest_storage_v2() -> dict:
    from tradingagents import rows_index as ri

    db = _v2_rows_db()
    if db is None:
        return {"rows": [], "pairs": 0, "coins": 0, "total_rows": 0,
                "total_bytes": 0, "incomplete": 0, "index": {},
                "newest_measured": None, "store": "v2", "why": _V2_EMPTY_WHY}
    with ri.using_db(db):
        d = backtest_storage()
    d["index"] = index_status_v2()
    d["store"] = "v2"
    return d


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


def _stored_now(symbol: str, tf: str, since: float, live=None,
                parquet_root=None) -> dict:
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
    from tradingagents import db_jobs as dj, parquet_store as pqs, positions_view as pv

    # `parquet_root` is another store's parquet folder (Backtest v2's
    # ~/.tradingagents/parquet-v2); None is the store the operator always had
    if parquet_root:
        from tradingagents.dataflows.market_db import tf_label as _tfl

        path = Path(parquet_root) / "candles" / f"{symbol}-{_tfl(tf)}.parquet"
    else:
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
_COMPLETENESS_CACHE_V2: dict = {"at": 0.0, "payload": None}


def _store_completeness(store=None) -> dict:
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
    # WHICH STORE: v1 counts the five frames against ~/.tradingagents/parquet;
    # Backtest v2 counts 1m alone against its own parquet-v2 folder
    v1 = store is None or store.name == "v1"
    c = _COMPLETENESS_CACHE if v1 else _COMPLETENESS_CACHE_V2
    tfs = _TFS if v1 else tuple(store.tfs)
    cdir = pqs.CANDLES if v1 else (Path(store.parquet) / "candles")
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
    have = ({p.stem for p in cdir.glob("*.parquet")}
            if cdir.exists() else set())
    wanted = [(sym, tf) for sym in contracts for tf in tfs]
    missing = [{"symbol": sym, "timeframe": tf}
               for sym, tf in wanted if f"{sym}-{tf}" not in have]
    payload = {"ok": True, "why": "", "contracts": len(contracts),
               "wanted": len(wanted), "stored": len(wanted) - len(missing),
               "missing": missing, "complete": not missing,
               # the frames this count is OF, so "x 5 timeframes" is never
               # printed over a one-frame store (label-must-match-data)
               "timeframes": list(tfs)}
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


@app.get("/api/v2/candles/completeness")
def candles_completeness_v2() -> dict:
    """MEXC's contracts x ONE frame (1m) against Backtest v2's own parquet."""
    return _store_completeness(_stores.V2)


@app.get("/api/candles/completeness")
def candles_completeness() -> dict:
    """Contracts on MEXC x five timeframes vs the store — the whole answer to
    "is the candles complete now?", with the missing pairs named."""
    return _store_completeness()


def _candles_lost_for(store) -> dict:
    """The pairs the last download gave up on — what RETRY FAILED will fetch.

    Read from the job's own lost file, so the button's count IS the retry's
    list, never a second bookkeeping of it. No file means nothing is lost.

    Plus what the LAST FAILED run lost and whether it is back: on 2026-08-25
    the operator read a 2:00pm "2 error(s)" row an hour after both pairs had
    been re-downloaded, saw a disabled RETRY button, and called it "still
    error". The button was right and the screen never said why.
    """
    from tradingagents import db_jobs, notifications as nt, positions_view as pv

    got = db_jobs._read(db_jobs.FILES[store.download_kind]["lost"])
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
    for _row in nt.recent(limit=20, kind=store.download_kind):
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
        state = _stored_now(s_, t_, since=_since, live=live,
                            parquet_root=(None if store.name == "v1" else store.parquet))
        pairs.append({"symbol": s_, "timeframe": t_,
                      "kind": _lost_kind(state, s_, t_, _texts)})
    recovered, failed_when, unnamed = [], "", 0
    for row in nt.recent(limit=20, kind=store.download_kind):
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
                     for r in (_stored_now(sym, tf, since=when,
                                           parquet_root=(None if store.name == "v1"
                                                         else store.parquet))
                               for sym, tf in named)
                     if r["recovered"] and not r["delisted"]]
        break
    return {"pairs": pairs, "count": len(pairs),
            "written": pv.fmt_when(float(got["written"])) if got.get("written") else "",
            "recovered": recovered, "failed_run_when": failed_when,
            "unnamed": unnamed,
            # named so the screen can say "2 delisted — nothing to retry"
            "delisted": delisted, "delisted_count": len(delisted)}


@app.get("/api/candles/lost")
def candles_lost() -> dict:
    return _candles_lost_for(_stores.V1)


@app.get("/api/v2/candles/lost")
def candles_lost_v2() -> dict:
    return _candles_lost_for(_stores.V2)


def _lost_kind_on(got: dict, symbol: str, tf: str, texts=None) -> dict:
    """`_stored_now` plus the one word for WHY (see _lost_kind)."""
    got["kind"] = _lost_kind(got, symbol, tf, texts)
    return got


# The decorator belongs to `download_history`. This helper was inserted BETWEEN
# them, so FastAPI registered `_lost_kind_on` as the endpoint and its `got`,
# `symbol` and `tf` arguments became required query and body fields: every load
# of the Candles page answered
#   422 {"loc": ["query", "symbol"], "msg": "Field required"}
# and the download-history panel showed nothing, while `download_history`
# itself was left unregistered — a route that existed in the source and not in
# the app. Found Sep 09, 2026 by reading the browser's failed requests after a
# restart; nothing else reported it.
def _download_history_for(store, limit: int = 20) -> dict:
    """Every download this machine has run, newest first, with its outcome.

    The operator asked to see whether a DOWNLOAD succeeded. The job's progress
    file only holds the LAST run, so the history comes from the event store.
    """
    from tradingagents import notifications as nt, positions_view as pv

    rows = nt.recent(limit=limit, kind=store.download_kind)
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
                                               since=float(r.get("ts") or 0),
                                               parquet_root=(None if store.name == "v1"
                                                             else store.parquet)),
                                   sym, tf, m.get("failed"))
                     for sym, tf in named],
            "unnamed": unnamed,
        })
        out[-1]["resolved"], out[-1]["resolved_why"] = _download_resolution(r)
    ok = sum(1 for r in out if r["ok"])
    return {"rows": out, "total": len(out), "ok": ok, "failed": len(out) - ok}


@app.get("/api/candles/download-history")
def download_history(limit: int = 20) -> dict:
    return _download_history_for(_stores.V1, limit)


@app.get("/api/v2/candles/download-history")
def download_history_v2(limit: int = 20) -> dict:
    return _download_history_for(_stores.V2, limit)


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
        # the screen must be able to say this list is still filling in.
        # Background-read: this route is polled too, and status() is minutes
        # cold on the rebuilt store.
        "index": index_status(),
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
