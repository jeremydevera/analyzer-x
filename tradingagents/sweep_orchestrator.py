"""Run the whole sweep, unattended, wherever it can run.

The operator, after three days of watching it break:

    "do backtest on your own using github actions ... i want accurate data and
     make sure to resume if it hits rate limit. give me update on percentage
     every 1 min, if i've been disconnected to wifi then continue the backtest
     local ... you already have the candles so you can work on this locally if
     there is no internet, make sure to store the backtest in database"

So this is a supervisor with one job: keep measuring, from whichever machine is
available, and never lose ground.

    GitHub reachable      -> dispatch shards for the coins nobody has measured
    rate limited          -> stop asking, wait for the reset, keep working
    no internet at all    -> measure locally from the candles already on disk
    either way            -> every finished pair lands in SQLite

WHY IT WATCHES GIT, NOT THE API
    Shards publish their own progress to the `sweep-progress` branch. Reading
    it with `git fetch` costs no API quota, which matters because polling the
    REST API burned 5,000 requests in an hour on 2026-08-25 and blinded every
    tool at once. The API is used only to dispatch, and once per cycle at most.

WHY LOCAL WORK NEEDS NO NETWORK
    4,946 candle files are already on disk. `run_pair` only calls the venue to
    TOP UP candles; with `days` already covered it measures from the cache. So
    a dropped connection changes where the work happens, not whether it does.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from tradingagents import portable

HOME = Path.home() / ".tradingagents"
STATE = HOME / "orchestrator.json"
LOG = HOME / "orchestrator.log"
STOP = HOME / "orchestrator.STOP"

TICK = 60.0                 # the operator asked for a percentage every minute
CLOUD_SHARDS = 20
CLOUD_MAX_CONCURRENT = 1    # one cloud run at a time; shards are the parallelism
GH_BUDGET_FLOOR = 200       # below this, stop asking GitHub and work here

# How old a contract must be to enter the sweep. `cloud_sweep.dispatch` defaults
# this to 365 and the orchestrator used to let it, which quietly cut the grid
# from 993 coins to 455 -- 538 contracts younger than a year were never measured
# and nothing said so. Rule 20: never drop a dimension silently. Every listed
# contract is measured, and each row carries its own `days`/`months`/`bars`, so
# a four-month coin reports four months rather than being deleted from the
# search. Filtering on depth is the reader's decision, made in the artifact.
MIN_DAYS = 0


def log(msg: str) -> None:
    from tradingagents.positions_view import fmt_when

    line = f"{fmt_when(time.time())} {msg}"
    print(line, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as fh:      # noqa: SIM115
            fh.write(line + "\n")
    except OSError:
        pass


def _write(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def online() -> bool:
    """Is the venue reachable? The sweep needs MEXC, not github.com."""
    try:
        import socket

        socket.create_connection(("contract.mexc.com", 443), timeout=6).close()
        return True
    except OSError:
        return False


def gh_budget() -> tuple[int, float]:
    """(requests left, seconds until reset). (0, 0) if gh cannot answer."""
    try:
        out = subprocess.run(["gh", "api", "rate_limit", "--jq",
                              ".resources.core"], capture_output=True,
                             text=True, timeout=30)
        if out.returncode:
            return 0, 0.0
        d = json.loads(out.stdout)
        return int(d.get("remaining") or 0), max(
            0.0, float(d.get("reset") or 0) - time.time())
    except Exception:
        return 0, 0.0


def cloud_shards(run_id: int) -> dict:
    """What the shards say they are doing, read from the sweep-progress branch.

    `git fetch` costs no API quota. Returns {"done": n, "total": n, "rows": n}.
    """
    try:
        subprocess.run(["git", "fetch", "-q", "mine", "sweep-progress"],
                       capture_output=True, timeout=90, check=False)
        names = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "FETCH_HEAD"],
            capture_output=True, text=True, timeout=60).stdout.splitlines()
    except Exception:
        return {}
    want = [n for n in names if f"run-{run_id}/" in n]
    done = rows = 0
    for n in want:
        try:
            blob = subprocess.run(["git", "show", f"FETCH_HEAD:{n}"],
                                  capture_output=True, text=True,
                                  timeout=30).stdout
            d = json.loads(blob)
        except Exception:
            continue
        rows += int(d.get("rows") or 0)
        if d.get("stage") == "done":
            done += 1
    return {"shards_done": done, "shards": len(want), "cloud_rows": rows}


def collect_cloud(run_id: int):
    """Fold a finished cloud run into the store.

    Returns None while the run is still going, or the number of pairs merged
    once it has ENDED — including 0. The distinction matters: a run that was
    cancelled, or whose artifact cannot be downloaded, still has to release the
    slot. Returning 0 for both "not finished" and "finished with nothing"
    pinned the orchestrator to a cancelled run forever.

    Without this the orchestrator dispatched and then simply waited: `done`
    counts LOCAL watermarks, so the percentage sat at 0 for hours and then
    jumped — the same false label as a counter that measures the process
    instead of the work.
    """
    from tradingagents import cloud_sweep as cs

    try:
        st = cs.status(run_id)
    except Exception:
        return 0
    if st.get("status") != "completed":
        return None                      # still going: keep waiting
    # STREAM the per-shard artifacts. `cs.fetch` asked for the single merged
    # `sweep-results` file and built one list of every row, and on 2026-08-25
    # both halves of that failed at once: the workflow's merge job was OOM-killed
    # loading 29.7 million rows into a list on a 7 GB runner, so `sweep-results`
    # never existed -- and the collector, having no fallback, logged "ended with
    # no usable artifact" and released the run. The twenty `rows-N` artifacts,
    # 3.3 GB of measured rows, were sitting there the whole time. They ARE the
    # measurement; the merge job only concatenates them.
    try:
        got = cs.collect_into_store(
            run_id,
            on_progress=lambda name, i, n, pairs, rows: log(
                f"run {run_id}: {name} ({i}/{n}) · {pairs} pairs, "
                f"{rows:,} rows so far"))
    except Exception as exc:
        log(f"run {run_id} could not be collected ({str(exc)[:60]}) "
            f"— releasing it")
        return 0
    if not got.get("artifacts"):
        log(f"run {run_id} ended with no live artifact — releasing it")
        return 0
    log(f"merged run {run_id}: {got.get('pairs')} pairs, "
        f"{got.get('rows'):,} rows from {got.get('artifacts')} artifacts, "
        f"{got.get('skipped')} skipped")
    return int(got.get("pairs") or 0)


def local_measuring_on() -> bool:
    """Does this PC still take sweep work?

    A named decision rather than a condition buried inside a daemon thread —
    `work()` was the back door precisely because nothing about it could be
    called, only read. Read at call time, not import time, so flipping
    `capacity.LOCAL_SWEEPS` needs no restart and a test can monkeypatch it.
    """
    from tradingagents import capacity as _cap

    return bool(_cap.LOCAL_SWEEPS)


def plan(*, online_: bool, budget: int, prefer_cloud: bool) -> str:
    """Where should the next slice of work happen?

    Pulled out of the loop so it can be tested without threads or a network.
    Three outcomes, and the operator asked for each by name:
      "cloud"   — GitHub has budget, dispatch there AND keep measuring here
      "local"   — rate limited; "make sure to resume if it hits rate limit"
      "offline" — "if i've been disconnected to wifi then continue local"
    """
    # The move to GitHub closes this module's back door too. It is not reachable
    # from the panel, so it was never one of the OPTIONS the operator removed —
    # but `python -m tradingagents.sweep_orchestrator` would still have measured
    # here, and a switch with an exception is not a switch (Sep 05, 2026).
    # Offline now means WAIT: no wifi is also no GitHub, so there is no slice of
    # work this PC could take that the operator still wants taken.
    if not local_measuring_on():
        return "cloud" if (online_ and budget > GH_BUDGET_FLOOR) else "wait"
    if not online_:
        return "offline"
    if prefer_cloud and budget > GH_BUDGET_FLOOR:
        return "cloud"
    return "local"


# ----------------------------------------------------------------- the work
def pairs_wanted(coins, tfs) -> list:
    return [(c, tf) for c in coins for tf in tfs]


def measured(pairs) -> set:
    """Pairs already finished, read from their watermark — a tail read each."""
    from tradingagents import market_sweep as msw

    done = set()
    for sym, tf in pairs:
        if msw.pair_watermark(sym.replace("_USDT", ""), tf) > 0:
            done.add((sym, tf))
    return done


def store_pair(coin: str, tf: str) -> int:
    """Fold one finished pair into SQLite. Returns rows indexed."""
    from tradingagents import market_sweep as msw, rows_index as ri

    f = msw.ROWDIR / f"{coin}-{tf}.json"
    if not f.exists():
        return 0
    return ri.index_pair(f)


def local_round(pairs_left, *, workers: int = 0) -> int:
    """Measure locally, in parallel, from the candles already on disk."""
    from tradingagents import backtest_report as br

    coins = sorted({c for c, _ in pairs_left})
    tfs = sorted({tf for _, tf in pairs_left})
    got = br.grid_from_store(coins, tfs, base_margin=5.0, days=365,
                             workers=workers, fresh=False,
                             progress=lambda *a, **k: None)
    return len(got.get("rows") or [])


def shutdown_pool(grace: float = 4.0) -> int:
    """Stop this process's own pool workers before exiting.

    STOP is read once a TICK, so the loop notices within a minute. The process
    still did not exit for over two: `local_round` runs inside a daemon thread,
    but the ProcessPoolExecutor it opens registers an atexit handler that JOINS
    every worker at interpreter shutdown — so "stop" waited for the current
    24-pair round to drain, up to half an hour.

    Reaching for SIGTERM on the parent instead is worse: on 2026-08-25 it left
    8 workers reparented to init, which is the orphan problem this file's
    sibling `reap_orphans` exists to clean up. So the parent takes its own
    children down first, on purpose, and only then exits.

    A worker killed mid-pair is INTERRUPTED, not failed: its state file is a
    consistent checkpoint and the next pass resumes from that watermark. Only
    an exception discards a pair (see `market_sweep.discard_pair`).
    """
    mine = os.getpid()
    kids = portable.child_pids(mine)
    for pid in kids:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGTERM)
    if kids:
        time.sleep(grace)
    for pid in kids:
        # probe first, so a pid that already went is never re-aimed at. On
        # Windows os.kill IS the kill — portable.pid_alive never signals.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if portable.pid_alive(pid):
                portable.kill_hard(pid)
    return len(kids)


# ------------------------------------------------------------------- cycle
def run(coins, tfs, *, prefer_cloud: bool = True) -> None:
    """Publish every TICK; do the heavy work on threads.

    The first version measured inline, so a tick took as long as 40 pairs and
    the operator — who asked for "update on percentage every 1 min" — got one
    every several minutes. Cadence and work are separate now: two daemon
    threads carry the load, the loop only reports.
    """
    import threading

    from tradingagents import cloud_sweep as cs, rows_index as ri

    want = pairs_wanted(coins, tfs)
    total = len(want)
    started = time.time()
    # LOG BEFORE ri.ensure(), NOT AFTER. ensure() opens a 15 GB index and can
    # run a migration; on 2026-08-25 it held startup for over four minutes with
    # nothing on screen, so a healthy boot was indistinguishable from a hang and
    # I killed a working process twice before reading its stack.
    log(f"start: {total:,} pairs ({len(coins)} coins x {len(tfs)} timeframes)")
    log("opening the row index...")
    ri.ensure()
    log(f"row index ready in {time.time() - started:.0f}s")

    shared = {"done": set(), "where": "starting", "cloud": None,
              "budget": 0, "reset_in": 0.0, "indexed": 0, "shards": {}}
    lock = threading.Lock()

    def scan() -> None:
        """Which pairs are finished, and fold them into the database."""
        while not STOP.exists():
            done = measured(want)
            with lock:
                shared["done"] = done
            n = 0
            for sym, tf in list(done)[:60]:
                n += store_pair(sym.replace("_USDT", ""), tf)
            with lock:
                shared["indexed"] = n
            time.sleep(30)

    def cloud() -> None:
        """Keep GitHub busy. Its OWN thread, on its own clock.

        This lived inside the work loop, which meant it only got a turn after a
        local round finished — 30+ minutes — so a cancelled run sat adopted for
        twenty minutes with nothing dispatched behind it. Managing the cloud is
        seconds of work; it must not queue behind half an hour of measuring.
        """
        while not STOP.exists():
            with lock:
                done = set(shared["done"])
            left = [p for p in want if p not in done]
            if not left or not prefer_cloud:
                time.sleep(TICK)
                continue
            if not online():
                time.sleep(TICK)
                continue
            budget, reset_in = gh_budget()
            with lock:
                shared["budget"], shared["reset_in"] = budget, reset_in
            if plan(online_=True, budget=budget, prefer_cloud=True) != "cloud":
                time.sleep(TICK)
                continue

            with lock:
                run_ = shared["cloud"]
            if run_ is None:
                try:
                    # the run that is MEASURING, not merely the last dispatched
                    found = cs.working_run()
                    if found:
                        run_ = found
                        log(f"adopting GitHub run {found['id']}, shards live")
                except Exception:
                    run_ = None
            if run_ is None:
                try:
                    n_coins = len({c for c, _ in left})
                    run_ = cs.dispatch(shards=CLOUD_SHARDS,
                                       coins=n_coins,
                                       timeframes=",".join(tfs),
                                       min_days=MIN_DAYS)
                    cs.remember(run_)
                    log(f"dispatched GitHub run {run_.get('id')} for "
                        f"{n_coins} coins x {len(tfs)} timeframes, "
                        f"min_days={MIN_DAYS}")
                except Exception as exc:
                    log(f"dispatch failed: {str(exc)[:70]}")
            with lock:
                shared["cloud"] = run_
            if run_:
                rid = int(run_.get("id") or 0)
                sh = cloud_shards(rid)
                with lock:
                    shared["shards"] = sh
                if collect_cloud(rid) is not None:
                    with lock:
                        shared["cloud"] = None      # ended; dispatch next pass
                    log(f"run {rid} has ended — releasing the slot")
                shared["where"] = (
                    f"GitHub run {rid} "
                    f"({sh.get('shards_done', 0)}/{sh.get('shards', 0)} shards, "
                    f"{sh.get('cloud_rows', 0):,} rows) + this Mac")
            time.sleep(TICK)

    def work() -> None:
        """Measure here — only while this PC is still in the rota.

        It used to say "always", and called `local_round` on every tick with
        nothing consulted. That made it the real back door after the Sep 05,
        2026 move to GitHub: `plan()` could return "wait" all day while this
        thread quietly measured 24 pairs a round and published "this Mac" as
        the place the work was happening.
        """
        while not STOP.exists():
            if not local_measuring_on():
                time.sleep(TICK)
                continue
            with lock:
                done = set(shared["done"])
            left = [p for p in want if p not in done]
            if not left:
                time.sleep(TICK)
                continue
            if not online():
                shared["where"] = "this Mac (no internet — from stored candles)"
            local_round(left[:24])

    for fn in (scan, work, cloud):
        threading.Thread(target=fn, name=fn.__name__, daemon=True).start()

    while not STOP.exists():
        with lock:
            done, where = set(shared["done"]), shared["where"]
            budget, indexed = shared["budget"], shared["indexed"]
        pct = 100.0 * len(done) / total if total else 0.0
        _write(STATE, {"pct": round(pct, 2), "done": len(done), "total": total,
                       "left": total - len(done), "where": where,
                       "running": len(done) < total,
                       "indexed_rows": indexed, "gh_requests_left": budget,
                       "elapsed_min": round((time.time() - started) / 60, 1)})
        log(f"{pct:5.1f}%  {len(done):,}/{total:,} pairs  ·  {where}")
        if len(done) >= total:
            log(f"FINISHED {len(done):,}/{total:,} pairs")
            log(f"closing {shutdown_pool()} workers")
            return
        time.sleep(TICK)

    n = shutdown_pool()
    log(f"stopped by request, closed {n} workers")


def main() -> int:
    with contextlib.suppress(OSError, AttributeError):
        os.nice(5)                       # never outrank the operator's clicks
    STOP.unlink(missing_ok=True)
    spec = json.loads((HOME / "orchestrator.spec.json").read_text())
    run(spec["coins"], spec["tfs"],
        prefer_cloud=bool(spec.get("prefer_cloud", True)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
