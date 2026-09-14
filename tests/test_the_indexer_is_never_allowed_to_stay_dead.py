"""The indexer died on a locked database and nothing ever restarted it.

Operator, `Sep 13, 2026`, pointing at the REINDEX button: *"WHY DO I HAVE
THIS BUTTON HERE / WHAT DOES THIS MEAN"*, and then the question this file
exists to answer: *"what's the reason why you decide it should not be
updated"*.

Nobody decided. `~/.tradingagents/rows_index.log` ends at `Sep 13, 2026
4:05pm` with the same traceback repeating:

    [rows-index] sync failed: OperationalError('database is locked')
    ...
      File "tradingagents/rows_index.py", line 4102, in main
        ensure()
      File "tradingagents/rows_index.py", line 340, in ensure
        con.executescript("PRAGMA journal_mode=WAL;")
    sqlite3.OperationalError: database is locked

`PRAGMA journal_mode` wants a brief exclusive lock and cannot have one while
a collect is writing. `main()` called `ensure()` bare, so that raised out of
`__main__` and KILLED the process — and `spawn_indexer` is called once, at
API startup, so there was no indexer on the machine from that moment on.

What it cost: `stale` climbed to **5,344** pairs overnight. `EMBER-15m` held
**8,400** measured rows on disk and **0** in the index — invisible in Stored
strategies. `RCATSTOCK-15m` held 21,600 on disk against 18,900 indexed:
2,700 strategies measured and unsearchable. And the operator was told, twice,
that it "catches up on its own in the background".

Three rules, one per section:

* a daemon whose job is keeping a screen current MAY NOT EXIT because a
  neighbour held a lock;
* something must NOTICE when it dies — and the check for "is one already
  running" has to be a fact, not a pid, or the supervisor is a no-op;
* THE SCREEN SAYS WHICH. A backlog being worked and a backlog with no worker
  are different sentences.
"""
from __future__ import annotations

import ast
import inspect
import os
import pathlib
import sqlite3
import subprocess
import sys

import pytest

from tradingagents import rows_index as ri


def _code(fn) -> str:
    """Source with the docstring dropped — every "this is not done" assertion
    below is explained by a docstring that names the thing it forbids."""
    tree = ast.parse(inspect.getsource(fn).lstrip()).body[0]
    tree.body = [n for n in tree.body
                 if not (isinstance(n, ast.Expr)
                         and isinstance(n.value, ast.Constant)
                         and isinstance(n.value.value, str))]
    return ast.unparse(tree)


# ------------------------------------------- 1. a lock is not a reason to die
def test_a_locked_database_is_waited_out_not_died_on(monkeypatch):
    """The measured failure, reproduced: `ensure()` raising `database is
    locked`. It must retry and come back, never propagate."""
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ri, "ensure", flaky)
    ri._loop_stop.clear()      # another test may have called stop_keeping_up()
    tries = ri._ensure_or_wait(sleep_s=0.01)
    assert calls["n"] == 3
    assert tries == 2, "it reports how many times it had to wait"


def test_it_keeps_waiting_rather_than_giving_up(monkeypatch):
    """`attempts=0` (the daemon's setting) means keep trying for as long as
    the process lives. A database locked now is usually free in a minute; the
    alternative is no indexer at all, which is what happened."""
    assert inspect.signature(ri._ensure_or_wait).parameters[
        "attempts"].default == 0, "the daemon must not cap its own retries"
    calls = {"n": 0}

    def always_locked():
        calls["n"] += 1
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ri, "ensure", always_locked)
    ri._loop_stop.clear()      # another test may have called stop_keeping_up()
    with pytest.raises(sqlite3.OperationalError):
        ri._ensure_or_wait(attempts=4, sleep_s=0.001)
    assert calls["n"] == 4, "the cap is for tests only"


def test_a_real_stop_still_stops_it(monkeypatch):
    """Waiting forever must not outlive a shutdown request."""
    monkeypatch.setattr(ri, "ensure", lambda: (_ for _ in ()).throw(
        sqlite3.OperationalError("database is locked")))
    ri._loop_stop.set()
    try:
        with pytest.raises(sqlite3.OperationalError):
            ri._ensure_or_wait(sleep_s=5)
    finally:
        ri._loop_stop.clear()


def test_main_no_longer_calls_ensure_bare():
    body = _code(ri.main)
    assert "_ensure_or_wait()" in body
    assert "\n    ensure()" not in "\n" + body, \
        "a bare ensure() in main is what killed the process"


def test_the_wait_names_who_holds_the_lock():
    """"database is locked" with no holder sent a reader to the process table
    for 13 hours once (RCA-2026-09-10-C)."""
    assert "lock_holder()" in _code(ri._ensure_or_wait)


# --------------------------------------- 2. dead is noticed, and only once
def test_the_identity_is_a_lock_not_a_pid():
    """A live pid proves a process exists, not that it is ours. After a
    reboot the runner's recorded pid came back as NVIDIA Overlay
    (RCA-2026-09-12-B); the same mistake here would make the supervisor read
    "still running" for ever and never refill the index."""
    body = _code(ri._running_elsewhere)
    assert "run_lock_held()" in body, "the pid alone is not an identity"
    assert "pid_alive" in body, "and the pid still has to be alive"


def test_two_indexers_cannot_hold_it_at_once():
    """The lock is the whole mechanism, so it is proved across a REAL second
    process rather than asserted."""
    assert ri.take_run_lock() is True
    try:
        assert ri.run_lock_held() is True
        code = ("from tradingagents import rows_index as ri;"
                "ri.DB_PATH = ri.DB_PATH;"
                f"ri.RUNLOCK = __import__('pathlib').Path(r'{ri.RUNLOCK}');"
                "print('TOOK' if ri.take_run_lock() else 'REFUSED')")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, timeout=120)
        assert "REFUSED" in (out.stdout or ""), (out.stdout, out.stderr)
    finally:
        ri.release_run_lock()
    assert ri.run_lock_held() is False, "releasing must really release"


def test_the_loser_of_the_race_exits_quietly():
    """The supervisor asks every 30 s and `spawn_indexer` writes the pid file
    AFTER the spawn, so two can briefly start. The second must stand down —
    two writers on one SQLite file is a lock storm that makes both slower."""
    body = _code(ri.main)
    assert "take_run_lock()" in body
    assert "return 0" in body[body.index("take_run_lock()"):][:400], \
        "the loser must exit 0, not raise"


def test_the_supervisor_restarts_a_dead_indexer():
    """It was spawned once at API startup and nothing looked again."""
    src = pathlib.Path("tradingagents/api.py").read_text(encoding="utf-8")
    i = src.index("def _watch() -> None:")
    watch = src[i:src.index("_th.Thread(target=_watch", i)]
    assert "_ri.spawn_indexer()" in watch, \
        "the supervisor never checks on the indexer"
    assert "the row indexer was down" in watch, "and it says so out loud"
    # it must sit with the other restarts, inside the 30 s loop
    assert watch.index("_ri.spawn_indexer()") > watch.index("_time.sleep(30)")


# ------------------------------------------------ 3. the screen says which
def test_status_reports_whether_anything_is_filling_the_backlog():
    st = ri.status()
    assert "indexer_running" in st, \
        "every other field describes the backlog; none said if a worker exists"
    assert isinstance(st["indexer_running"], bool)


def test_the_first_read_says_unknown_not_running():
    """`None` while the background read is in flight. Leaving the key out
    made a missing value print "catching up on its own" — the reassurance
    that was wrong for a day."""
    from tradingagents import api

    src = inspect.getsource(api.index_status)
    assert '"indexer_running": None' in src


def test_the_panel_prints_the_difference():
    panel = pathlib.Path(
        "webapp/src/components/backtest/StrategiesPanel.tsx"
    ).read_text(encoding="utf-8")
    assert "nothing is filling this — the indexer is not running" in panel
    assert "catching up on its own in the background" in panel
    # `=== false`, so "unknown" (null, the first read) is NOT reported as dead
    assert "idx.indexer_running === false" in panel
    client = pathlib.Path("webapp/src/lib/api.ts").read_text(encoding="utf-8")
    assert "indexer_running?: boolean;" in client


# ---------------------------------- 4. it stands down for a REBUILD as well
def _rebuild_progress(tmp_path, monkeypatch, *, pid, phase="loading", age=0.0):
    import json
    import os

    f = tmp_path / "rows_rebuild.json"
    f.write_text(json.dumps({"pid": pid, "phase": phase,
                             "pairs_done": 710, "pairs_total": 5401}))
    if age:
        old = f.stat().st_mtime - age
        os.utime(f, (old, old))
    monkeypatch.setattr(ri, "REBUILD_PROGRESS", f)


def test_a_running_rebuild_pauses_the_indexer(tmp_path, monkeypatch):
    """A rebuild is a writer and `db_jobs.FILES` has never heard of it, so
    `busy_job()` returned "" while `rows_index --rebuild --fresh` loaded the
    whole store. Measured Sep 14, 2026 3:30pm: a rebuild at 710 of 5,401
    pairs, 70.89 pairs/min, with a freshly restarted indexer beside it on the
    same platter — writing rows into a file the swap was about to discard."""
    _rebuild_progress(tmp_path, monkeypatch, pid=os.getpid())
    assert ri.busy_job() == "rebuild (loading)"
    assert ri._machine_is_busy() is True


def test_the_pause_names_the_phase(tmp_path, monkeypatch):
    """"paused" with no name is the stalled screen RCA-2026-09-10-C was
    about."""
    _rebuild_progress(tmp_path, monkeypatch, pid=os.getpid(),
                      phase="verifying")
    assert ri.busy_job() == "rebuild (verifying)"


def test_a_dead_rebuild_does_not_pause_it_for_ever(tmp_path, monkeypatch):
    """The failure this fix must not become. A pid that is gone, or a progress
    file nothing has touched for ten minutes, is a rebuild that died without
    tidying up — and a dead writer must never hold the indexer down."""
    _rebuild_progress(tmp_path, monkeypatch, pid=0)
    assert ri.busy_job() == "", "no pid, no rebuild"
    # alive pid, but the file has not been republished in an hour
    _rebuild_progress(tmp_path, monkeypatch, pid=os.getpid(),
                      age=ri.REBUILD_STALE_S + 60)
    assert ri.busy_job() == "", "a stale progress file is not a live rebuild"


def test_a_recycled_pid_cannot_pause_it(tmp_path, monkeypatch):
    """TWO FACTS, never one: after a reboot the runner's recorded pid came
    back as NVIDIA Overlay (RCA-2026-09-12-B). Here a live-but-recycled pid
    with an old file must not read as a rebuild."""
    _rebuild_progress(tmp_path, monkeypatch, pid=os.getpid(),
                      age=ri.REBUILD_STALE_S * 2)
    assert ri.busy_job() == ""


def test_the_paused_case_is_not_confused_with_the_dead_case():
    """Standing down while a collect owns the disk is healthy and temporary;
    having no process at all is neither. They must not print the same line."""
    panel = pathlib.Path(
        "webapp/src/components/backtest/StrategiesPanel.tsx"
    ).read_text(encoding="utf-8")
    assert "paused while ${idx.paused_by} has the disk" in panel
