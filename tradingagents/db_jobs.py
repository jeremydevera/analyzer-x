"""Detached download/backtest jobs for the archive, with progress and STOP.

Running these inline froze the Backtest page for the whole job and offered
no way out but clicking something and hoping. Each job runs as its own
process (same pattern as the market sweep): the caller writes a spec file,
progress lands in a JSON file the page polls, and STOP is a flag file the
job checks between units of work — a stopped download KEEPS everything
already stored.

    python -m tradingagents.db_jobs download|backtest
"""

from __future__ import annotations

import contextlib
import contextlib as _contextlib
import http.client
import json
import os
import subprocess
import sys
import threading as _threading
import time
from pathlib import Path

from tradingagents import capacity as cap, portable

STATE_DIR = Path(os.path.expanduser("~/.tradingagents"))

FILES = {
    "download": {"progress": STATE_DIR / "db_download.json",
                 "spec": STATE_DIR / "db_download.spec.json",
                 # pairs the last run gave up on, so "update" can queue them
                 # again. Its own file: start() rewrites the progress file with a
                 # stub before the job even begins, so progress cannot carry it.
                 "lost": STATE_DIR / "db_download.lost.json",
                 "pid": STATE_DIR / "db_download.pid",
                 "stop": STATE_DIR / "db_download.STOP"},
    "backtest": {"progress": STATE_DIR / "db_backtest.json",
                 "spec": STATE_DIR / "db_backtest.spec.json",
                 "pid": STATE_DIR / "db_backtest.pid",
                 "stop": STATE_DIR / "db_backtest.STOP",
                 "handoff": STATE_DIR / "db_backtest.HANDOFF"},
    # one deployed strategy, replayed over a year — the Auto Trade "1 YEAR"
    # button. Detached because the grid takes minutes and a request must not
    # hold it open.
    "stratbt": {"progress": STATE_DIR / "db_stratbt.json",
                "spec": STATE_DIR / "db_stratbt.spec.json",
                "pid": STATE_DIR / "db_stratbt.pid",
                "stop": STATE_DIR / "db_stratbt.STOP"},
    "btupdate": {"progress": STATE_DIR / "db_btupdate.json",
                 "spec": STATE_DIR / "db_btupdate.spec.json",
                 "pid": STATE_DIR / "db_btupdate.pid",
                 "stop": STATE_DIR / "db_btupdate.STOP",
                 # UPDATE BACKTEST runs `_run_backtest_inner`, whose per-pair
                 # callback asks `handoff_requested(kind)`. Without this path
                 # the very first pair raised KeyError: 'handoff' and the job
                 # died reporting "Backtest update FAILED" (2026-09-03).
                 "handoff": STATE_DIR / "db_btupdate.HANDOFF"},
}

# Where the finished backtest report page goes — the same folder the app's
# other backtest buttons publish to, so links work identically.
REPORT_DIR = Path(__file__).resolve().parent.parent / "static" / "bt"


def _write(path: Path, payload: dict) -> None:
    """Atomic publish. Two threads write one progress file -- the per-pair
    callback and the 2 s heartbeat -- and the API reads it every few seconds.
    The tmp name is unique PER CALL: both threads used `db_backtest.tmp`, and
    on Windows a file another handle has open can be neither replaced nor
    removed, so on 2026-08-25 the collision raised PermissionError inside the
    per-pair callback and the job's `done` froze at 64 of 4,985 while its
    workers ran on for twenty minutes (6,419 errors in a 6 s reproduction).
    The replace itself is retried briefly: a reader holding the destination
    open is a few milliseconds of PermissionError on Windows, not a failure."""
    import threading as _th

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{_th.get_ident()}.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    for attempt in range(40):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 39:
                with contextlib.suppress(OSError):
                    tmp.unlink()
                raise
            time.sleep(0.005)


def _read(path: Path) -> dict:
    # a reader can land between a writer's unlink and rename on Windows: try
    # again before answering {} -- {} reads as "the job died" on screen
    for attempt in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError:
            time.sleep(0.005)
        except Exception:
            return {}
    return {}


def _alive(pid: int) -> bool:
    return portable.pid_alive(pid)


def status(kind: str) -> dict:
    """Progress plus whether the process is actually alive — a stale JSON
    from a crashed job must never read as RUNNING."""
    f = FILES[kind]
    prog = _read(f["progress"])
    pid = 0
    with contextlib.suppress(Exception):
        pid = int(f["pid"].read_text().strip())
    if prog.get("running") and not (pid and _alive(pid)):
        prog["running"] = False       # crashed or killed: say so, not RUNNING
        prog.setdefault("note", "process died before finishing")
    prog["pid"] = pid
    return prog


# ---------------------------------------------------------------- supervision
# The operator's words, after a 3,960-pair sweep died at 11.8%:
#   "if it fails it should have automatic retry and you did not even think of
#    it"
# Correct. Per-pair checkpointing was built so a restart RESUMES, but nothing
# ever did the restarting. On 2026-08-22 the sweep hit a full disk at 04:30:35,
# the interpreter died printing the OSError, and it simply stayed dead — the
# operator found out hours later.
MAX_RETRIES = 20
DISK_FLOOR_GB = 5.0

# MEMORY, the same shape as the disk floor above. The operator's PC froze twice
# on 2026-08-27 while a sweep ran unattended: 16 GB with 9.1 GB already held by
# other apps, and once the rest went Windows paged to a MECHANICAL disk, which
# is a freeze rather than a crash. Two guards, both measured on that machine:
#
#   * a worker on a 1h/4h pair peaks at 150-180 MB (eleven of them: 1.8 GB).
#     A 15m/30m pair carries four times the bars, so it gets a bigger budget.
#   * RAM_RESERVE_GB is left for Windows and whatever the operator has open.
#   * under RAM_FLOOR_GB the run stands down like a full disk: every finished
#     pair kept, the bell rung, the supervisor free to resume.
RAM_PER_WORKER_GB = {"15m": 0.5, "30m": 0.5, "1h": 0.2, "4h": 0.2, "1d": 0.2}
RAM_RESERVE_GB = 2.0
RAM_FLOOR_GB = 1.0


def free_ram_gb() -> float:
    """Available physical memory, or 0.0 when the machine will not say."""
    return portable.ram_gb()[1]


def _per_worker_gb(tfs) -> float:
    """The heaviest timeframe in the run decides the budget: one 15m pair in a
    1h job still holds a 15m pair's rows."""
    return max([RAM_PER_WORKER_GB.get(t, 0.2) for t in (tfs or [])] or [0.2])


# How long to let memory SETTLE before sizing the pool, and how often to look.
# A restart inherits the corpse of the process it replaces: on Sep 03, 2026 the
# 3:30pm restart measured 3.9 GB free while the dead run's workers were still
# being reaped, chose 3 of 11 cores, and stayed on 3 for the rest of the run —
# 5.6 GB was free minutes later and two of the three workers sat pegged at 100%
# of one core while nine cores idled. Measured rate on 3 cores: 15 pairs/hour,
# 28.6 hours for the 429 pairs left.
SETTLE_SECONDS = 20.0
SETTLE_EVERY = 4.0


def free_ram_settled(seconds: float = SETTLE_SECONDS,
                     every: float = SETTLE_EVERY) -> float:
    """The BEST free-memory reading over a short window, not the first one.

    Sizing a pool on a single sample taken at the worst instant of a restart
    locks a whole run to a fraction of the machine. Freeing is fast — a reaped
    worker's pages come back in seconds — so the maximum over twenty seconds is
    the honest figure, and it is never optimistic about memory that is genuinely
    in use.
    """
    best = free_ram_gb()
    if best <= 0:                      # the machine will not say
        return best
    waited = 0.0
    while waited < seconds:
        time.sleep(min(every, seconds - waited))
        waited += every
        got = free_ram_gb()
        if got > best:
            best = got
    return best


def workers_for_ram(cores: int, tfs, free_gb: float | None = None) -> int:
    """How many pairs may be measured at once without paging to disk.

    `cores` is what the machine offers (already one short of the total, so the
    API and the runner keep a core). A machine that cannot report its memory
    gets `cores` unchanged -- the guard must never silently halve a run on a
    number it does not have.
    """
    if free_gb is None:
        free = free_ram_gb()
        if free <= 0:
            # the machine will not say: leave the run exactly as it was
            return max(1, int(cores))
    else:
        free = float(free_gb)        # an explicit 0.0 means measured, not unknown
    budget = free - RAM_RESERVE_GB
    fits = int(budget // _per_worker_gb(tfs))
    return max(1, min(int(cores), fits))


def ram_reason(chosen: int, offered: int, tfs, free_gb: float | None = None) -> str:
    """Why the run is using fewer cores than the machine has -- printed beside
    the number, because "4 of 11 cores" alone reads as a broken machine
    (label-must-match-data). Empty when nothing was reduced.
    """
    if chosen >= offered:
        return ""
    free = free_ram_gb() if free_gb is None else float(free_gb)
    return (f"{chosen} of {offered} cores: {free:.1f} GB free, "
            f"{RAM_RESERVE_GB:.1f} GB reserved for the desktop, "
            f"~{_per_worker_gb(tfs):.1f} GB per pair at this timeframe")


def ram_exhausted() -> bool:
    """Is memory so low that continuing would page to disk? A machine that
    cannot report memory never pauses on it."""
    free = free_ram_gb()
    return bool(free) and free < RAM_FLOOR_GB
RETRY_FILE = STATE_DIR / "db_retries.json"


def free_gb(path: Path | None = None) -> float:
    """Free space where the stores live."""
    import shutil

    try:
        return shutil.disk_usage(path or STATE_DIR).free / 1e9
    except OSError:
        return 0.0


def _retries(kind: str) -> int:
    return int(_read(RETRY_FILE).get(kind) or 0)


def _set_retries(kind: str, n: int) -> None:
    got = _read(RETRY_FILE)
    got[kind] = n
    _write(RETRY_FILE, got)


def died_unfinished(kind: str) -> bool:
    """Was this job cut off mid-flight, one way or another?

    TWO ways count. A process that VANISHED leaves `running: true` with a dead
    pid. A process that hit a TRANSIENT failure — the network dropping — exits
    cleanly and records it; that used to read as "this job ended" and the
    supervisor walked away from 3,000 measured pairs while the connection was
    already back.

    A job that finished, was stopped by the operator, or failed on something
    deterministic is never resumed: retrying a broken spec forever looks like
    progress and is not.
    """
    prog = _read(FILES[kind]["progress"])
    if prog.get("error") and prog.get("transient"):
        return True                      # the network, not the config
    if not prog.get("running"):
        return False                     # finished, stopped, or hard-failed
    try:
        pid = int(FILES[kind]["pid"].read_text().strip())
    except Exception:
        return False
    return not _alive(pid)


def resume_if_died(kind: str) -> dict:
    """Restart a job that was cut off, from its own checkpoint.

    Never restarts a job that finished, was stopped by the operator, or has
    already burned its retries — a crash loop that re-reads the same broken
    state is worse than a stopped job, because it looks like progress.
    """
    if not died_unfinished(kind):
        return {"resumed": False, "why": "not a crashed job"}
    if free_gb() < DISK_FLOOR_GB:
        # exactly what killed it. Restarting into a full disk just kills it
        # again, and the log fills the last of the space doing so.
        return {"resumed": False, "why": f"only {free_gb():.1f} GB free — "
                                         f"waiting for {DISK_FLOOR_GB} GB"}
    n = _retries(kind)
    if n >= MAX_RETRIES:
        return {"resumed": False, "why": f"gave up after {n} retries"}
    spec = _read(FILES[kind]["spec"])
    if not spec:
        return {"resumed": False, "why": "no spec to resume from"}
    # A RESUMED run continues; it never starts over. The operator's split is
    # BACKTEST=scratch / UPDATE=gap-fill, and a crash is not a click on either.
    spec = {**spec, "fresh": False}
    _set_retries(kind, n + 1)
    try:
        from tradingagents import notifications as _nt

        _nt.record(kind, f"{kind} restarted after a crash",
                   ok=True, detail=f"attempt {n + 1} of {MAX_RETRIES}, "
                                   f"resuming from the last checkpoint")
    except Exception:
        pass
    pid = start(kind, spec)
    return {"resumed": True, "pid": pid, "attempt": n + 1}


def clear_retries(kind: str) -> None:
    """A run the operator starts by hand is a fresh budget of retries."""
    _set_retries(kind, 0)


def _handoff_path(kind: str):
    """The handoff flag for a job, or None when that job has no such channel.

    A MISSING path answers "nobody asked for a handoff" — never an exception.
    `_run_backtest_inner` asks once per finished pair, so on 2026-09-03 the
    first pair of every UPDATE BACKTEST raised KeyError: 'handoff' from inside
    the progress callback, the run ended "Backtest update FAILED", and the
    button the operator had just asked to rely on could not finish one pair.
    A new job kind must never be able to kill a run by not declaring a file.
    """
    return (FILES.get(kind) or {}).get("handoff")


def request_handoff(kind: str) -> None:
    """Ask a running job to finish its current pairs and hand over."""
    path = _handoff_path(kind)
    if path is None:
        raise KeyError(f"{kind} has no handoff channel")
    path.touch()


def handoff_requested(kind: str) -> bool:
    path = _handoff_path(kind)
    return bool(path is not None and path.exists())


def clear_handoff(kind: str) -> None:
    path = _handoff_path(kind)
    if path is not None:
        path.unlink(missing_ok=True)


def request_stop(kind: str) -> None:
    FILES[kind]["stop"].touch()


def _stopping(kind: str) -> bool:
    return FILES[kind]["stop"].exists()


def start(kind: str, spec: dict) -> int:
    """Write the job's spec and launch it detached. Refuses to double-start."""
    st = status(kind)
    if st.get("running"):
        return st.get("pid") or 0
    f = FILES[kind]
    f["stop"].unlink(missing_ok=True)
    _write(f["spec"], spec)
    # NOT a context manager: this handle is the detached child's stdout and
    # must outlive this function. Closing it would send the job SIGPIPE.
    logf = open(STATE_DIR / f"db_{kind}.log", "a")   # noqa: SIM115
    proc = subprocess.Popen(
        [sys.executable, "-m", "tradingagents.db_jobs", kind],
        cwd=str(Path(__file__).resolve().parent.parent),
        stdout=logf, stderr=logf, **portable.DETACHED)
    f["pid"].write_text(str(proc.pid))
    _write(f["progress"], {"running": True, "started": int(time.time()),
                           "done": 0, "total": 0, "now": "starting"})
    return proc.pid


# --------------------------------------------------------------- job bodies
# The operator, 2026-08-25, after a 4,985-pair download ended with
#   "2 error(s): CHILLGUY_USDT 15m: IncompleteRead(183452 bytes read)":
#   "so you mean if download fails, it wont try again? this is a stupid
#    design ... i want 10/10 accuracy on download"
# One pair's connection was cut mid-body and the pair was skipped for good;
# the second lost pair (NAORIS_USDT 30m) was never even named — only
# errors[0] was written down — and "update" walks the STORE, so a pair the
# download lost could never be fetched again by clicking anything.
# Now: a pair whose WIRE failed is redone BY ITSELF, after the others, up to
# PAIR_RETRIES times (the rule from the sweep — never the whole run again); a
# deterministic failure is named at once; every pair still lost at the end is
# named in the progress file, the bell and the log; and the next update queues
# the lost pairs again.
PAIR_RETRIES = 3
RETRY_PAUSE_S = 3.0          # a redo straight away hits the same bad connection
_BELL_NAMES = 5              # lost pairs named in the bell before "and N more"
_pause = time.sleep


_LIVE_CACHE: dict = {"at": 0.0, "symbols": None, "failed_at": 0.0}
# how long a FAILED contract-list lookup is remembered (see live_symbols)
FAIL_CACHE_S = 30.0


def live_symbols(max_age_s: float = 300.0):
    """Every symbol MEXC lists right now, or None when the venue could not be
    asked. Cached, because a download asks once per run and the list is 999
    rows.

    None is NOT an empty set: "I could not look" must never be read as "every
    pair is delisted", which would skip the whole store.
    """
    from tradingagents.dataflows import mexc_futures as fx

    c = _LIVE_CACHE
    now = time.time()
    if c["symbols"] is not None and now - c["at"] < max_age_s:
        return c["symbols"]
    if now - c.get("failed_at", 0.0) < FAIL_CACHE_S:
        # a FAILED lookup is remembered too, briefly. `is_delisted` runs per
        # pair inside routes the panel polls every 20-60 s, and each miss would
        # re-enter list_contracts -> _get_public with its own retry budget:
        # a venue outage would block those requests for minutes.
        return None
    try:
        got = {str(r["symbol"]) for r in fx.list_contracts() if r.get("symbol")}
    except Exception as exc:                                   # noqa: BLE001
        print(f"[download] could not list MEXC contracts: "
              f"{type(exc).__name__}: {str(exc)[:80]}", flush=True)
        c["failed_at"] = now
        return None
    if not got:
        c["failed_at"] = now
        return None
    c.update(at=now, symbols=got, failed_at=0.0)
    return got


# What the venue says when it has nothing for a contract. A pair is called
# DELISTED only when the ERROR looks like this AND the symbol is missing from
# the live list — two independent facts. A timeout on a live pair must never be
# reclassified as gone, or one bad minute deletes a coin from the store.
_GONE_ERRORS = ("no min", "no hour", "no day", "no candles", "returned 0 bars",
                "contract not found", "invalid symbol", "symbol not exist")


def looks_gone(exc_or_text) -> bool:
    """Does this failure mean "the venue has nothing for this contract"?"""
    text = str(exc_or_text).lower()
    return any(k in text for k in _GONE_ERRORS)


def is_delisted(symbol: str, live=None) -> bool:
    """Is this contract gone from the venue?

    MEZO_USDT and DRV_USDT failed every download and every retry on
    2026-08-27 with `no Min15 candles for MEZO_USDT`, sat in `lost.json`, were
    re-fetched by the next update, failed again, and kept the panel red for
    ever: the operator's *"this update candles is not reliable"*. They are not
    broken — they are not listed any more (999 contracts, neither in it).
    Nothing can fetch them, so they are named and SKIPPED, never counted as an
    error and never queued again.
    """
    if live is None:
        live = live_symbols()
    if not live:
        # None (could not ask) AND empty (a request that came back useless)
        # both mean "I do not know" — never "every contract is gone", which
        # would skip the entire store on one bad response
        return False
    return str(symbol) not in live


def update_pairs(lost: list | None = None) -> tuple:
    """What an UPDATE must fetch, in the order that survives being stopped.

    Three sources, and the store alone is none of them:

      * every pair the store already has, MOST BEHIND FIRST. A stopped update
        used to leave its tail untouched and the next one walked the same order
        again — 3,722 pairs sat more than a bar behind, the furthest 50.3 h
        (2026-08-27). Staleness order means a stop always did the work that
        mattered most.
      * every pair the venue lists that the store does NOT have. An update
        walked the store, so a NEW contract was never fetched by it: the panel
        read `store missing 20 of 4,995 pairs: DESTOCK 15m, IOTSTOCK 15m ...`
        and no button would ever fill them.
      * whatever the last run lost.

    Minus anything delisted. Returns
    (pairs, delisted, missing_added, lost_added) — `lost_added` being the lost
    pairs that were NOT already in the store, which is what the run's note
    counts ("N pair(s) the last download lost re-downloaded").
    """
    from tradingagents import market_sweep as msw

    live = live_symbols()
    now = time.time()
    have, ordered = set(), []
    for c in msw.candle_coverage():
        sym, tf = c.get("symbol"), c.get("timeframe")
        if not sym or not tf:
            continue
        have.add((sym, tf))
        behind = now - float(c.get("last_ms") or 0) / 1000.0
        ordered.append((behind, sym, tf))
    # most behind first, then alphabetical — `sort(reverse=True)` would also
    # reverse the tie-break, so two pairs the same distance behind came back in
    # descending symbol order and the order looked arbitrary
    ordered.sort(key=lambda x: (-x[0], x[1], x[2]))
    pairs = [(sym, tf) for _behind, sym, tf in ordered]

    missing = []
    if live is not None:
        for sym in sorted(live):
            for tf in ("15m", "30m", "1h", "4h", "1d"):
                if (sym, tf) not in have:
                    missing.append((sym, tf))
    # the store's gaps go FIRST: a pair with no file at all is worse than a
    # pair that is one bar behind
    pairs = missing + pairs

    lost_added = [(p[0], p[1]) for p in (lost or [])
                  if len(p) == 2 and (p[0], p[1]) not in have]
    missing_set = set(missing)
    pairs += [p for p in lost_added if p not in missing_set]

    # Which of them the venue no longer lists — REPORTED, not removed. A pair
    # is only ever called delisted after an attempt whose error agrees (see
    # `looks_gone` in _run_download): the contract list is filtered by
    # apiAllowed and by quote, and a partial or stale answer must not be able
    # to delete work from the queue. CLAUDE.md: "A failed age check KEEPS the
    # coin."
    likely_gone = [f"{c} {tf}" for c, tf in pairs if is_delisted(c, live)]
    return pairs, likely_gone, len(missing), lost_added


def _run_download(spec: dict) -> None:
    """DOWNLOAD/UPDATE fill the operator's OWN MACHINE — the store every
    backtest reads. Pure local: no database is touched.

    `mode: "update"` means "top up what I already have": the pairs come from
    the store itself, so a store filled on 28 July and updated on 21 August
    fetches exactly the bars between — refresh_candles walks back from the
    stored last bar, never re-downloading a year. Plus whatever the LAST run
    lost: a pair that failed is not in the store, so the store alone would
    never ask for it again.
    """
    from collections import deque

    from tradingagents import market_sweep as msw, parquet_store as pqs
    from tradingagents.positions_view import fmt_when
    f = FILES["download"]
    mode = spec.get("mode") or "download"
    lost_before: list[tuple[str, str]] = []
    # every branch sets these; declared here so a reordered branch cannot
    # silently degrade them to a default nobody chose
    delisted: list[str] = []
    # LISTED contracts the venue serves no candles for. Named, never filed as
    # a fault, never queued as lost — see the `looks_gone` branch below.
    empty: list[str] = []
    n_missing = 0
    if mode == "retry":
        # the RETRY FAILED button: exactly the pairs the last run gave up
        # on — no store walk, no re-download, one entry per pair
        pairs = []
        for p in (_read(f["lost"]).get("pairs") or []):
            if len(p) == 2 and (p[0], p[1]) not in pairs:
                pairs.append((p[0], p[1]))
        # A contract the venue no longer lists is ATTEMPTED once here too, so
        # the loop can classify it on the venue's own answer and clear it out of
        # lost.json for good. Dropping it unattempted would leave it in that
        # file for ever and the button would keep offering it.
        delisted = []
    elif mode == "update" and not spec.get("coins"):
        pairs, likely_gone, n_missing, lost_before = update_pairs(
            _read(f["lost"]).get("pairs") or [])
        if likely_gone:
            print(f"[download] {len(likely_gone)} pair(s) the venue no longer "
                  f"lists will be attempted once and then named as delisted: "
                  f"{', '.join(likely_gone)}", flush=True)
    else:
        coins = spec["coins"]
        tfs = [t for t in spec["tfs"]
               if t in ("15m", "30m", "1h", "4h", "1d")]
        pairs = [(c, tf) for c in coins for tf in tfs]
    stored, stopped, done, retries = 0, False, 0, 0
    failed: list[str] = []                 # "COIN tf: why" — one per pair given up on
    failed_pairs: list[list[str]] = []
    tries: dict[tuple[str, str], int] = {}
    queue = deque(pairs)
    while queue:
        if _stopping("download"):
            stopped = True
            break
        c, tf = queue.popleft()
        n = tries.get((c, tf), 0)
        # `total` counts PAIRS and `done` counts pairs settled (stored or given
        # up). A redo bumps neither, or the percentage runs backwards the
        # moment a coin fails.
        _write(f["progress"], {"running": True, "done": done, "total": len(pairs),
                               "now": f"{c} {tf}"
                                      + (f" (redo {n}/{PAIR_RETRIES})" if n else ""),
                               "bars_stored": stored, "errors": len(failed),
                               "retries": retries})
        if n:
            _pause(RETRY_PAUSE_S)
        try:
            df, added, _src = msw.refresh_candles(c, tf, days=365)
            pqs.save_candles(c, tf, df)          # the parquet copy, atomically
            stored += int(added)
        except Exception as exc:
            why = str(exc)[:80]
            if is_transient(exc) and n < PAIR_RETRIES:
                # redo THAT pair, not the whole — behind the others, so the
                # connection has time to come back
                tries[(c, tf)] = n + 1
                retries += 1
                print(f"[download] {fmt_when(time.time())} {c} {tf} failed "
                      f"({n + 1}/{PAIR_RETRIES}): {why} — redoing it after the others",
                      flush=True)
                queue.append((c, tf))
                continue
            if looks_gone(why):
                gone = is_delisted(c)
                if gone:
                    # not an error and not lost: the contract is gone, so no
                    # run can ever fetch it and it must not be queued again
                    delisted.append(f"{c} {tf}")
                    print(f"[download] {fmt_when(time.time())} {c} {tf} is "
                          f"DELISTED on MEXC — skipped, not counted as an "
                          f"error", flush=True)
                else:
                    # LISTED, and the venue serves no candles for this pair.
                    # A retry asks the same question and gets the same empty
                    # answer, so this must not go on the lost list: 25 pairs
                    # over five contracts did exactly that on Sep 02, 2026 and
                    # every later update re-queued them, failed again and kept
                    # the panel red — the same shape as the delisted case
                    # above, which is why they now share this branch.
                    # `update_pairs` still queues a pair the store lacks, so
                    # each update attempts it once; only the FILING changes.
                    empty.append(f"{c} {tf}")
                    print(f"[download] {fmt_when(time.time())} {c} {tf}: the "
                          f"venue serves no candles for this pair — named, "
                          f"not counted as an error", flush=True)
                done += 1
                continue
            failed.append(f"{c} {tf}: {why}")
            failed_pairs.append([c, tf])
            print(f"[download] {fmt_when(time.time())} {c} {tf} gave up after "
                  f"{n} redo(s): {why}", flush=True)
        done += 1
    # One line in the bell, so a click that did nothing is distinguishable
    # from a click that worked. Every lost pair is NAMED — a bare "2 error(s)"
    # sends somebody back to diff the store against the spec. Never allowed
    # to raise into the job.
    try:
        from tradingagents import notifications as _nt

        _ok = not failed and not stopped
        names = " · ".join(failed[:_BELL_NAMES])
        more = len(failed) - _BELL_NAMES
        _nt.record(
            "download",
            ("Download stopped" if stopped else
             "Download finished" if _ok else "Download finished with errors"),
            detail=(f"{stored:,} bars over {len(pairs)} pair(s)"
                    + (" · nothing to retry" if mode == "retry" and not pairs else "")
                    + (f" · {len(failed)} error(s): {names}" if failed else "")
                    + (f" · and {more} more" if more > 0 else "")
                    + (f" · {len(delisted)} delisted, skipped: "
                       f"{' · '.join(delisted[:3])}" if delisted else "")
                    + (f" · {len(empty)} pair(s) the venue serves no candles "
                       f"for: {' · '.join(empty[:3])}" if empty else "")),
            ok=_ok,
            meta={"pairs": len(pairs), "bars": stored,
                  "errors": len(failed), "failed": failed, "retries": retries,
                  "stopped": bool(stopped), "delisted": delisted,
                  "empty": empty,
                  "missing_added": n_missing,
                  "mode": spec.get("mode") or "download"})
    except Exception:
        pass
    # what this run could not get, for the next update to ask for again;
    # a clean run empties it
    _write(f["lost"], {"pairs": failed_pairs, "written": int(time.time())})
    _write(f["progress"], {
        "running": False, "done": done, "total": len(pairs),
        "bars_stored": stored, "errors": len(failed),
        "first_error": (failed[0] if failed else ""),
        "failed": failed, "failed_pairs": failed_pairs, "retries": retries,
        "stopped": stopped, "finished": int(time.time()),
        "mode": spec.get("mode") or "download",
        # named, never counted as errors: nothing can fetch a gone contract,
        # and a retry cannot conjure candles the venue does not have
        "delisted": delisted, "empty": empty, "missing_added": n_missing,
        "note": ("stopped by you — everything downloaded so far is kept"
                 if stopped else
                 (f"retried {len(pairs)} lost pair(s)" if pairs else
                  "nothing to retry — no pair is lost") if mode == "retry" else
                 f"{'gap-filled' if mode == 'update' else 'downloaded'} "
                 f"{len(pairs)} pair(s)"
                 + (f" · {n_missing} pair(s) the store did not have at all"
                    if n_missing else "")
                 + (f" · {len(delisted)} delisted, skipped"
                    if delisted else "")
                 + (f" · {len(empty)} pair(s) the venue serves no candles for"
                    if empty else "")
                 + (f" · {len(lost_before)} pair(s) the last download lost "
                    f"re-downloaded" if lost_before else "")
                 + (f" · {len(failed)} still lost — named in failed" if failed else ""))})


class _HandOff(Exception):
    """The operator asked to move this sweep to GitHub Actions.

    NOT a stop. "finish the current task then switch" — so the pairs already
    in flight run to completion and checkpoint, and only then does the job
    stand down. Every measured pair stays on disk; the cloud picks up the ones
    the Mac never reached.
    """


class _LowDisk(Exception):
    """Not enough disk left to keep going safely."""


class _LowRam(Exception):
    """Not enough memory left to keep going without paging to disk."""


class _StopRequested(Exception):
    pass


def result_rows(payload: dict, days: int, signals_count: int) -> list[dict]:
    """Grid rows -> backtest_results rows. One shape for the page, this job
    and the GitHub job, so no path quietly drops a column."""
    day_end = int(time.time()) // 86400 * 86400
    return [{
        "row_code": r["id"], "symbol": f"{r['coin']}_USDT",
        "timeframe": r["tf"], "signal": r["signal"],
        # threshold is part of WHICH strategy this is: mom6 at 0.2 and
        # mom6 at 0.3 are different strategies with different results
        "threshold": r.get("th"), "tp": r["tp"], "sl": r["sl"],
        "sizing": r["sizing"],
        "data_start": day_end - days * 86400, "data_end": day_end,
        "code_version": f"signals{signals_count}",
        "profit": r["profit"], "trades": r["trades"], "wins": r["wins"],
        "losses": r["losses"], "win_rate": r["winrate"],
        # worst_streak is the LOSING RUN summed, not the drawdown — two
        # different numbers, and the column is named for the first
        "worst_streak": r.get("wstreak"), "worst_streak_len": r.get("wstreakn"),
        "months_green": r.get("green"), "months_total": r.get("months"),
        "days": r.get("days"), "max_dd": r.get("dd"),
        "funding": r.get("funding"),
        # not every row carries months (the fast path skips them on rows
        # below the floor) — an absent field must not sink the whole save
        "months_json": json.dumps(r.get("monthly") or {}),
    } for r in payload["rows"]]


def _armed_symbols() -> list:
    """Coins with a live strategy — the only candles Neon keeps."""
    try:
        from tradingagents import auto_trader as at

        cfg = at.load_settings()
        books = cfg.get("strategy_books") or {}
        coins = cfg.get("strategy_coins") or {}
        return sorted({c for k, cs in coins.items()
                       for c in (cs or []) if books.get(k)})
    except Exception:
        return []


def _signals_count() -> int:
    from tradingagents import backtest_report as br

    return len(br.SIGNALS)


def _measured(payload: dict) -> int:
    """Combinations MEASURED — the page may hold fewer (streaming fold)."""
    return int(payload.get("rows_total") or len(payload.get("rows") or []))


def persist_results(payload: dict, *, days: int, label: str,
                    mdb=None, pq=None) -> int:
    """Snapshot the full grid to the operator's own disk. Pure local — "i
    told you that its pure local" — so no database is written or dieted; the
    pair store (market_sweep) already holds every row, and this file is the
    immutable record of THIS run. A failed snapshot raises."""
    if pq is None:
        from tradingagents import parquet_store as pq
    # The streaming fold already wrote every row as it read it (GridSink); the
    # payload's own `rows` is only the page's bounded selection, so saving THAT
    # would replace a complete snapshot with a truncated one.
    if payload.get("grid_path"):
        return int(payload.get("rows_total") or len(payload["rows"]))
    pq.save_grid(payload["rows"], label=label)
    return len(payload["rows"])


# A dropped connection is not a broken config.
#
# On 2026-08-24 the operator's internet went down mid-sweep and the job died
# with `transport failure: <urlopen error [Errno 8] nodename nor servname
# provided>`. It recorded that failure, so `died_unfinished` saw a job that had
# ENDED rather than one whose process vanished, and the supervisor left it dead
# — 3,000 measured pairs sitting there while the network was already back.
#
# Retrying a DETERMINISTIC error is a crash loop that looks like progress;
# retrying a TRANSIENT one is the whole point of having a supervisor. So the
# distinction is decided where the exception is caught, by type, and written
# down — never by pattern-matching the message later.
# http.client.HTTPException covers IncompleteRead / RemoteDisconnected — a
# connection cut mid-body. It is NOT an OSError, which is how the error that
# lost CHILLGUY_USDT 15m on 2026-08-25 would have read as deterministic.
# json.JSONDecodeError is a ValueError, not an OSError, so a body that came
# back EMPTY or half-written used to read as a permanent fault. ENPHSTOCK 1d
# failed the Sep 02, 2026 update with "Expecting value: line 1 column 1
# (char 0)" — MEXC answered with nothing — and the run reported `retries: 0`
# and left it on the lost list for the operator to press a button about. A
# truncated body is the wire, and the wire is worth one more go.
_TRANSIENT_TYPES = (OSError, TimeoutError, ConnectionError,
                    http.client.HTTPException, json.JSONDecodeError)
_TRANSIENT_MARKS = ("transport failure", "urlopen", "temporary failure",
                    "nodename nor servname", "timed out", "connection reset",
                    "connection refused", "rate limit", "too many requests",
                    # MEXC's own wording, taken from the runner's log:
                    # "code=510 msg='Requests are too frequent, please try
                    # again later'". "rate limit" alone never matched it.
                    "too frequent",
                    # an empty or half-written body, however it is wrapped
                    "expecting value", "unterminated string",
                    "unexpected end of", "incompleteread")


def is_transient(exc: BaseException) -> bool:
    """Would trying again, later, plausibly work?

    The CAUSE CHAIN counts. On 2026-08-26 funding_history began wrapping a cut
    connection in its own MexcFuturesError ("funding history is incomplete:
    page 2 failed (IncompleteRead...)"). That is a RuntimeError carrying no
    transient marker, so the supervisor read a dropped wire as a broken config
    and would have refused to retry the pair. A wrapped transient failure is
    still transient.
    """
    seen = 0
    while exc is not None and seen < 8:
        if isinstance(exc, _TRANSIENT_TYPES):
            return True
        msg = str(exc).lower()
        if any(m in msg for m in _TRANSIENT_MARKS):
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


def _run_backtest(spec: dict, files_key: str = "backtest",
                  kind: str = "backtest") -> None:
    """Crash containment: whatever happens inside, the progress file ends in
    running:false with the error named. A job that died at 80% once left
    'running: true' on screen for half an hour.

    UPDATE BACKTEST comes through here too (files_key="btupdate"), so a failed
    update cannot leave its own progress file claiming to be running either.
    """
    try:
        _run_backtest_inner(spec, files_key=files_key, kind=kind)
    except _StopRequested:
        raise
    except Exception as exc:
        try:
            from tradingagents import notifications as _nt

            # NAME THE TYPE. `str(MemoryError())` is "", so on 2026-08-26
            # 5:20am the bell read "Backtest FAILED" with nothing after it and
            # the progress file said `failed: ` — the operator had to be told
            # what happened from a stack trace.
            _nt.record(kind,
                       "Backtest update FAILED" if kind == "btupdate"
                       else "Backtest FAILED", ok=False,
                       detail=f"{type(exc).__name__}: {exc}"[:300],
                       meta={"fatal": True, "kind": type(exc).__name__})
        except Exception:
            pass
        _write(FILES[files_key]["progress"], {
            "running": False, "finished": int(time.time()),
            "error": f"{type(exc).__name__}: {exc}"[:200],
            # the supervisor reads this flag; it never parses the message
            "transient": is_transient(exc),
            "note": f"failed: {type(exc).__name__}: {exc}"[:160]})
        raise


def _run_backtest_inner(spec: dict, files_key: str = "backtest",
                        kind: str = "backtest") -> None:
    """`files_key`/`kind` exist so UPDATE BACKTEST can run this exact machinery
    while keeping its own progress file, stop flag and bell entries. One
    implementation: the update used to be a sequential loop beside it, which is
    how it ended up days slower than the button next to it (2026-09-03)."""
    from tradingagents import backtest_report as br
    f = FILES[files_key]

    # A missing field used to surface in the UI as `failed: 'coins'` -- a raw
    # KeyError repr, which says nothing to the person reading it. Name what is
    # missing, in words.
    _needs = {"coins": "which coins to test", "tfs": "which timeframes",
              "base": "the starting money per trade", "days": "how much history"}
    _gone = [f"{k} ({why})" for k, why in _needs.items()
             if spec.get(k) in (None, "", [], {})]
    if _gone:
        raise ValueError("the backtest was started without "
                         + ", ".join(_gone) + " — nothing ran")

    import os as _os

    from tradingagents import market_sweep as _msw

    # One pair per core, one core left free for the trading runner and the API.
    cores_offered = max(1, (_os.cpu_count() or 2) - 1)
    # Sized to the memory actually free, not just to the cores (2026-08-27) --
    # and to memory that has SETTLED, not to the instant of a restart
    # (2026-09-03, see free_ram_settled).
    _free = free_ram_settled()
    n_workers = workers_for_ram(cores_offered, spec.get("tfs") or [],
                                free_gb=_free if _free > 0 else None)
    cores_why = ram_reason(n_workers, cores_offered, spec.get("tfs") or [],
                           free_gb=_free if _free > 0 else None)
    if cores_why:
        print(f"[backtest] {cores_why}", flush=True)

    # What the heartbeat should say between pair completions.
    # done/total are the REAL pair counts once grid_from_store knows them.
    # Rescaling the fraction to 0-100 printed `0/100` beside a message that
    # said `16/3960` -- a correct value under a false label, which is the
    # failure shape label-must-match-data exists to catch.
    last = {"msg": "starting", "frac": 0.0, "done": 0, "total": 0}

    # PUBLISHED, not assumed. The UI used to print "from scratch" as a literal,
    # so a resumed run wore a from-scratch label -- a true value under a false
    # caption, which is the failure label-must-match-data exists to catch.
    fresh = bool(spec.get("fresh", True))

    def _publish() -> None:
        _write(f["progress"], {"running": True,
                               "done": last["done"],
                               "total": last["total"], "now": last["msg"],
                               "pct": last.get("pct"),
                               "cores": n_workers,
                               # what the machine offered and why fewer are in
                               # use, so "4 of 11" never reads as broken
                               "cores_offered": cores_offered,
                               "cores_why": cores_why,
                               "ram_free_gb": round(free_ram_gb(), 2) or None,
                               "fresh": fresh,
                               # Never MORE bars than there are cores. A pool
                               # worker that has just been replaced is still
                               # fresh enough to report while its successor
                               # reports too, and the screen read "8 OF 7 CORES
                               # WORKING" — a label arguing with its own
                               # denominator. The freshest n_workers are the
                               # ones actually working; the outgoing one is
                               # always the stalest.
                               "workers": sorted(
                                   _msw.worker_read(),
                                   key=lambda w: -(w.get("updated") or 0),
                               )[:n_workers]})

    def prog(msg: str, frac: float, done: int | None = None,
             total: int | None = None) -> None:
        if _stopping(kind):
            raise _StopRequested()
        # Raised from the per-PAIR callback on purpose: a pair has just
        # finished and checkpointed, and ProcessPoolExecutor's context manager
        # waits for the rest of the in-flight pairs on the way out. That is
        # "finish the current task", exactly as asked.
        if handoff_requested(kind):
            raise _HandOff(msg)
        # STOP BEFORE the disk is gone. On 2026-08-22 the sweep ran the volume
        # to zero at 04:30:35 and the interpreter died printing the OSError --
        # no terminal record, no notification, and the checkpoint of the pair
        # in flight was lost. Stopping with room left keeps every finished pair
        # and lets the supervisor resume once there is space.
        if free_gb() < DISK_FLOOR_GB:
            raise _LowDisk(f"{free_gb():.1f} GB free")
        # And the same for MEMORY: stopping with room left keeps every finished
        # pair, where running the machine out makes Windows page to a
        # mechanical disk and freezes the desktop the operator is using.
        if ram_exhausted():
            raise _LowRam(f"{free_ram_gb():.1f} GB of memory free")
        frac = max(0.0, min(1.0, frac))
        # no counts offered (a phase that only knows a fraction): keep the bar
        # moving on a permille scale rather than printing a rounded-to-zero one
        if total is None:
            done, total = round(frac * 1000), 1000
        last.update(msg=msg, frac=frac, done=done, total=total,
                    pct=round(frac * 100, 2))
        _publish()

    # HEARTBEAT. progress() only fires when a PAIR finishes, and a pair is
    # ~17,800 combinations — so with every core on a long pair the progress file
    # sat at "starting" with no cores for minutes while all seven were in fact
    # working. The workers publish their own slot files continuously; this
    # thread folds them into the job's progress on a timer so the UI sees them.
    _beat_stop = _threading.Event()

    def _beat() -> None:
        while not _beat_stop.wait(2.0):
            # telemetry must never kill the job
            with _contextlib.suppress(Exception):
                _publish()

    _beat_t = _threading.Thread(target=_beat, name="bt-heartbeat", daemon=True)
    _beat_t.start()

    try:
        # BACKTEST means from scratch. The operator's words: "when i click
        # backtest i want from scratch, when i click update backtest just fill
        # the gap" -- so this job throws the resume point away by default and
        # UPDATE (_run_btupdate) is the one that continues.
        payload = br.grid_from_store(
            spec["coins"], spec["tfs"], base_margin=float(spec["base"]),
            days=int(spec["days"]), deployed=spec.get("deployed") or [],
            progress=prog, workers=n_workers, fresh=fresh)
    except _HandOff as exc:
        _write(f["progress"], {"running": False, "handoff": True,
                               "finished": int(time.time()),
                               "done": last["done"], "total": last["total"],
                               "note": f"finished the pairs in flight at "
                                       f"{exc} and handed over to GitHub "
                                       f"Actions — every measured pair is kept"})
        try:
            from tradingagents import notifications as _nt

            _nt.record(kind, "Handed off to GitHub Actions", ok=True,
                       detail=f"stopped locally at {last['done']} of "
                              f"{last['total']} pairs; the cloud takes the rest")
        except Exception:
            pass
        return
    except _LowDisk as exc:
        _write(f["progress"], {"running": False, "paused": True,
                               "finished": int(time.time()),
                               "done": last["done"], "total": last["total"],
                               "note": f"paused — low disk ({exc}). Every "
                                       f"finished pair is kept; it resumes by "
                                       f"itself once there is room"})
        try:
            from tradingagents import notifications as _nt

            _nt.record(kind, "Backtest paused — low disk", ok=False,
                       detail=str(exc))
        except Exception:
            pass
        return
    except _LowRam as exc:
        _write(f["progress"], {"running": False, "paused": True,
                               "finished": int(time.time()),
                               "done": last["done"], "total": last["total"],
                               "note": f"paused — low memory ({exc}). Every "
                                       f"finished pair is kept; it resumes by "
                                       f"itself once there is memory"})
        try:
            from tradingagents import notifications as _nt

            _nt.record(kind, "Backtest paused — low memory", ok=False,
                       detail=str(exc))
        except Exception:
            pass
        return
    except _StopRequested:
        _write(f["progress"], {"running": False, "stopped": True,
                               "finished": int(time.time()),
                               "note": "stopped by you — a backtest has no "
                                       "partial answer, so nothing was saved"})
        return
    finally:
        # ALWAYS, and before any terminal write. The caller records a failure
        # in its own handler; a heartbeat still alive at that moment would fire
        # two seconds later and stamp the dead job "running" again, leaving a
        # crashed backtest looking like it was still going.
        _beat_stop.set()
        _beat_t.join(timeout=3.0)
    if not payload["rows"]:
        _write(f["progress"], {"running": False, "rows": 0,
                               "finished": int(time.time()),
                               "note": "nothing survived the trade floor"})
        return
    # NEVER a bare spec["report_name"]. A sweep that measured every pair used
    # to die here — hours of work discarded at the last step because one key
    # was missing, reported to the operator only as `failed: 'report_name'`.
    # A report always has somewhere to go; the name is a convenience.
    name = spec.get("report_name") or spec.get("name") or "archive.html"
    if not str(name).endswith(".html"):
        name = f"{name}.html"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    br.write_report(str(REPORT_DIR / name), payload,
                    title=spec.get("title") or "Archive backtest",
                    note=spec.get("note") or "")
    saved, save_err = 0, ""
    try:
        saved = persist_results(payload, days=int(spec["days"]),
                                label=spec.get("label") or "archive")
    except Exception as exc:                 # never claim a save that failed
        save_err = str(exc)[:160]
    try:
        from tradingagents import notifications as _nt

        _nt.record(
            kind,
            "Backtest finished" if not save_err else "Backtest saved with errors",
            detail=(f"{_measured(payload):,} rows measured"
                    + (f" · {len(payload['rows']):,} on the page"
                       if payload.get("rows_capped") else "")
                    + f" · report {name}"
                    + (f" · save error: {save_err}" if save_err else "")),
            ok=not save_err,
            meta={"rows": _measured(payload), "shown": len(payload["rows"]),
                  "capped": bool(payload.get("rows_capped")),
                  "grid": payload.get("grid_path") or "",
                  "saved": saved,
                  "report": name, "save_error": save_err})
    except Exception:
        pass
    _write(f["progress"], {"running": False, "rows": _measured(payload),
                           "shown": len(payload["rows"]),
                           "capped": bool(payload.get("rows_capped")),
                           "grid": payload.get("grid_path") or "",
                           "saved": saved, "save_error": save_err,
                           "report": name, "finished": int(time.time())})


def stored_symbols() -> list:
    """Every contract this machine has candles for, as SYMBOLS.

    `run_pair` takes `CETUS_USDT` — it passes the name straight to `klines` and
    derives the coin by stripping `_USDT`. Handing it the bare coin makes every
    pair raise `no Min15 candles for CETUS`, which is exactly what happened on
    2026-09-03 when the spec was built by hand.
    """
    from tradingagents import market_sweep as msw

    return sorted({c["symbol"] for c in msw.candle_coverage()
                   if c.get("symbol")})


def _run_btupdate(spec: dict) -> None:
    """CONTINUE stored backtests over new bars only — never from scratch.

    Runs the SAME parallel sweep the BACKTEST button runs, with `fresh=False`:
    every combination picks up with its ladder rung, running totals and any open
    position from where the last run stopped, and walks only the bars that
    printed since. A stopped update keeps every pair already continued.

    Two things this used to get wrong, both found by running it for real on
    2026-09-03 (operator: *"apply the fix to the button"*):

    * it was SEQUENTIAL — one `run_pair` at a time, 90 s for the first pair and
      4,124 pairs to go, while the button beside it used every core. The run
      that actually did the work was the backtest job with `fresh: False`, so
      that is what this is now.
    * an EMPTY coin list meant ZERO PAIRS. `[(c, tf) for c in [] ...]` is
      nothing, so clicking UPDATE without hand-picking 1,031 coins ran nothing
      and reported "0/0". Empty now means every contract this machine has
      candles for — what "update" means on the candles screen.
    """
    coins = list(spec.get("coins") or [])
    if not coins:
        coins = stored_symbols()
        print(f"[btupdate] no coins named — continuing every pair in the "
              f"store: {len(coins):,} contract(s)", flush=True)
    tfs = list(spec.get("tfs") or list(cap.ALL_TFS))

    # WHERE does it run? Both, when both are free. Operator, 2026-09-03: "i want
    # you to detect if there is a free both in github and machine", after asking
    # "why did you not use github since its free?" — GitHub had sat idle through
    # a 4,124-pair run that took most of a day, because nothing ever looked.
    #
    # The split is BY TIMEFRAME, the only axis the cloud shard can be pointed
    # at, which also means the two halves can never measure the same
    # combination. `use_cloud: False` in the spec keeps it all here.
    # `ignore=("btupdate",)`: this code runs INSIDE the update job, whose own
    # pid and progress say "running". Without it the job reads itself as the
    # busy machine and hands every frame to GitHub while this PC idles.
    plan = cap.plan(tfs, ignore=("btupdate",)) if spec.get("use_cloud", True) else {
        "local": list(tfs), "cloud": [],
        "why": "GitHub was switched off for this run"}
    print(f"[btupdate] {plan['why']}", flush=True)

    dispatched = {}
    if plan["cloud"]:
        from tradingagents import cloud_sweep as cs

        try:
            dispatched = cs.dispatch(
                shards=cap.CLOUD_RUNNERS, coins=0,
                timeframes=",".join(plan["cloud"]),
                min_days=0, days=int(spec.get("days") or 365))
            print(f"[btupdate] GitHub run {dispatched.get('id')} started for "
                  f"{', '.join(plan['cloud'])}: {dispatched.get('url')}",
                  flush=True)
        except Exception as exc:                               # noqa: BLE001
            # A cloud that will not start is NOT a reason to measure nothing:
            # this PC takes the frames back and the failure is named, not
            # swallowed (the download job's rule, applied here).
            print(f"[btupdate] GitHub refused the dispatch: "
                  f"{type(exc).__name__}: {exc} — this PC takes "
                  f"{', '.join(plan['cloud'])} as well", flush=True)
            plan = {**plan, "local": tfs, "cloud": [],
                    "why": f"GitHub refused the dispatch ({exc}); all of it "
                           f"on this PC"}
    _write_run_plan(plan, dispatched, coins, tfs)

    if not plan["local"]:
        # Everything went to GitHub. Finish cleanly and say so, rather than
        # running a sweep over an empty timeframe list.
        _finish_btupdate_cloud_only(plan, dispatched, coins)
        return

    # `fresh` is forced: this entry point IS the continuation. A spec that
    # asked for a fresh sweep here would silently throw away every resume
    # point the store has.
    _run_backtest({**spec, "coins": coins, "tfs": plan["local"],
                   "base": float(spec.get("base") or 5.0),
                   "days": int(spec.get("days") or 365),
                   "fresh": False},
                  files_key="btupdate", kind="btupdate")


def _write_run_plan(plan: dict, dispatched: dict, coins, tfs) -> None:
    """Record who took what, so the LOGS panel can say it after the fact."""
    try:
        _write(STATE_DIR / "db_btupdate.plan.json", {
            "when": int(time.time()), "why": plan.get("why", ""),
            "local": plan.get("local", []), "cloud": plan.get("cloud", []),
            "cloud_run": dispatched.get("id"), "cloud_url": dispatched.get("url"),
            "coins": len(coins), "timeframes": list(tfs)})
    except Exception:                                          # noqa: BLE001
        pass


def _finish_btupdate_cloud_only(plan, dispatched, coins) -> None:
    """Every frame went to GitHub — close the local job honestly."""
    f = FILES["btupdate"]
    note = (f"all of it went to GitHub: {', '.join(plan['cloud'])} over "
            f"{len(coins):,} contract(s)"
            + (f" · run {dispatched['id']}" if dispatched.get("id") else ""))
    _write(f["progress"], {"running": False, "done": 0, "total": 0, "rows": 0,
                           "new_bars": 0, "stopped": False, "errors": 0,
                           "finished": int(time.time()),
                           "cloud_run": dispatched.get("id"),
                           "cloud_url": dispatched.get("url"),
                           "note": note})
    try:
        from tradingagents import notifications as _nt

        _nt.record("btupdate", "Backtest update handed to GitHub", detail=note,
                   ok=True, meta={"cloud_run": dispatched.get("id"),
                                  "timeframes": plan["cloud"]})
    except Exception:                                          # noqa: BLE001
        pass


def _run_stratbt(spec: dict) -> None:
    """Replay ONE deployed strategy over a year and write its grid page."""
    from tradingagents import strategy_report as sr
    f = FILES["stratbt"]
    key = spec["key"]

    def prog(msg: str, frac: float) -> None:
        # `pct` carries the exact figure: `done` is a whole number, so a bar
        # asked to show two decimals had nothing finer to print.
        frac = max(0.0, min(1.0, frac))
        _write(f["progress"], {"running": True, "key": key, "now": msg,
                               "done": int(frac * 100), "total": 100,
                               "pct": round(frac * 100, 2)})

    try:
        got = sr.build(key, label=spec.get("label") or key,
                       coins=spec["coins"],
                       base_margin=float(spec.get("base_margin") or 5.0),
                       days=int(spec.get("days") or 365), progress=prog)
        _write(f["progress"], {"running": False, "key": key, "done": 100,
                               "total": 100, "report": got["name"],
                               "report_url": got["url"], "rows": got["rows"],
                               "cached": got["cached"],
                               "finished": int(time.time()),
                               "note": "cached page reused" if got["cached"]
                                       else f"{got['rows']} rows tested"})
    except Exception as exc:                                   # noqa: BLE001
        _write(f["progress"], {"running": False, "key": key,
                               "error": f"{type(exc).__name__}: {exc}",
                               "note": f"failed: {exc}",
                               "finished": int(time.time())})
        raise


def main(argv: list[str]) -> int:
    kind = argv[0]
    spec = _read(FILES[kind]["spec"])
    if kind == "stratbt":
        _run_stratbt(spec)
    elif kind == "download":
        _run_download(spec)
    elif kind == "backtest":
        _run_backtest(spec)
    elif kind == "btupdate":
        _run_btupdate(spec)
    else:
        print(f"unknown job: {kind}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
