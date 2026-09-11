"""The index went quiet for 13 hours and nothing on the machine said why.

Operator, `Sep 10, 2026 1:05am`, after being told the measuring was finished
but the screen was not: *"is tehre a bug or what i dont understand"*, then
*"did you fix the bug"*.

What was actually true at that moment, all of it measured:

* the GitHub results HAD landed — 5,364 pair files on disk, last collect
  finished `Sep 10, 2026 12:38am`;
* `rows.db` (33 GB) had been locked since `Sep 09, 2026 11:55am` by a
  delisted-coin cleanup holding ONE transaction across 73 pairs;
* the indexer (pid 22424, up 18.7 h) sat at **0% CPU** behind it, so 5,276
  measured pairs stayed invisible;
* REINDEX, pressed at `12:47am`, answered `"started": true` and did nothing.

Three separate faults kept that invisible, and each one has a test here.
"""
import inspect

import pytest

from tradingagents import rows_index as ri


# ------------------------------------------------- 1. the swallowed failure
def test_a_failed_catch_up_is_remembered_not_swallowed(monkeypatch):
    """`except Exception: pass`. The thread died on its FIRST statement --
    `ensure()` raising `database is locked` -- and the button still said
    "started". Nothing on screen, nothing in a log, for 13 hours."""
    import sqlite3

    monkeypatch.setattr(ri, "_last_error", "")
    monkeypatch.setattr(ri, "_machine_is_busy", lambda: False)

    def boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ri, "sync", boom)
    assert ri.sync_in_background(force=True) is True
    for _ in range(200):                       # it runs on its own thread
        if ri._last_error:
            break
        import time

        time.sleep(0.01)
    assert "database is locked" in ri._last_error
    assert "OperationalError" in ri._last_error, "the TYPE is named"
    assert ri.status()["last_error"] == ri._last_error, \
        "and it must reach the screen, not just a variable"


def test_a_success_clears_the_last_failure(monkeypatch):
    monkeypatch.setattr(ri, "_last_error", "OperationalError: database is locked")
    monkeypatch.setattr(ri, "_machine_is_busy", lambda: False)
    monkeypatch.setattr(ri, "sync", lambda **k: {"pairs": 1})
    ri.sync_in_background(force=True)
    for _ in range(200):
        if not ri._last_error:
            break
        import time

        time.sleep(0.01)
    assert ri._last_error == "", "a stale error is its own false label"


def test_the_swallow_is_gone_from_the_source():
    src = inspect.getsource(ri.sync_in_background)
    assert "except Exception:\n            pass" not in src, \
        "a background failure that vanishes is a button that lies"


# --------------------------------------------------- 2. the undercount
def test_the_button_counts_the_work_it_will_actually_do(monkeypatch):
    """`behind` is never-indexed ONLY (806). `sync()` walks `stale_pairs()`,
    which also holds every pair whose file MOVED (5,276 that night). The
    button promised a seventh of its own job, so it would look finished while
    a sixth of the way in."""
    st = ri.status()
    assert "stale" in st, "status must expose what a catch-up really walks"

    class _P:
        def __init__(self, s):
            self.stem = s

    monkeypatch.setattr(ri, "stale_pairs",
                        lambda now=None: [_P(f"C{i}-1h") for i in range(5276)])
    assert ri.status()["stale"] == 5276


def test_the_route_prints_the_bigger_number():
    from tradingagents import api

    src = inspect.getsource(api.strategies_reindex)
    assert '"todo": todo' in src
    assert 'f"indexing {todo:,} measured pair(s) now"' in src, \
        "it must promise `todo`, never `behind`"
    assert 'st.get("stale")' in src


def test_the_BUTTON_prints_the_bigger_number_too():
    """The guard above stopped at the API and the fix stopped there with it.

    The route has sized itself as `stale or behind` since Sep 10, 2026 — and
    the button the operator actually presses went on printing `behind`.
    Measured on their store on Sep 12, 2026: `behind: 4`, `stale: 5,206`, so
    it read **"index the missing 4 pair(s) now"** over a 5,206-pair walk. The
    ten `cx_*` cascade rules that could not be found at all (RCA-2026-09-12-D)
    are inside those 5,206.

    A guard is only as wide as its pattern, and this one's pattern was one
    layer deep.
    """
    import pathlib

    panel = pathlib.Path(
        "webapp/src/components/backtest/StrategiesPanel.tsx"
    ).read_text(encoding="utf-8")
    # the one expression, and it is the route's own
    assert ("const indexTodo = Number(idx?.stale ?? 0) "
            "|| Number(idx?.behind ?? 0);") in panel
    # the label is DERIVED from it, and `behind` is not what is rendered
    button = panel[panel.index("onClick={catchUp}"):][:700]
    assert "indexTodo.toLocaleString()" in button, button[:300]
    assert "idx.behind.toLocaleString()" not in button, \
        "the button is labelled with the never-indexed count again"
    # and the client type has to carry it, or the panel reads undefined
    client = pathlib.Path("webapp/src/lib/api.ts").read_text(encoding="utf-8")
    assert "stale?: number | null;" in client

    # THE POLLING LOOP KEEPS `behind` ON PURPOSE. `stale` on a store being
    # swept is ~5,200 for the length of the sweep, so keying the 60 s
    # background refresh on it would arm it permanently — the regression the
    # comment above `catchingUp` was written for (8 requests a minute, 3.4 s
    # each, holding one of the browser's four lanes).
    assert ("const catchingUp = !!idx && (idx.syncing || idx.behind > 0);"
            in panel), "the refresh must keep asking 'are rows still arriving'"


# ----------------------------------------------- 3. who is holding the door
def test_the_status_names_what_holds_the_write_lock(monkeypatch):
    """A reader that cannot say WHO is holding the door is how a stall becomes
    "the app is broken". This is the real phase string from that night."""
    from tradingagents import storage_months as sm

    monkeypatch.setattr(sm, "KINDS", ("delisted",))
    monkeypatch.setattr(sm, "progress", lambda k: {
        "running": True,
        "phase": "removing from the row index: 55 of 73 pairs"})
    got = ri.lock_holder()
    assert "delisted" in got and "55 of 73" in got


def test_a_cleanup_that_is_NOT_in_the_index_phase_does_not_get_blamed(
        monkeypatch):
    """It only holds the write lock during the index phase. Blaming it while
    it deletes FILES would send somebody to stop the wrong job."""
    from tradingagents import storage_months as sm

    monkeypatch.setattr(sm, "KINDS", ("delisted",))
    monkeypatch.setattr(sm, "progress", lambda k: {
        "running": True, "phase": "deleting candle files: 3 of 32 coins"})
    assert ri.lock_holder() == ""


def test_no_cleanup_running_means_nobody_is_blamed(monkeypatch):
    from tradingagents import storage_months as sm

    monkeypatch.setattr(sm, "KINDS", ("delisted",))
    monkeypatch.setattr(sm, "progress", lambda k: {"running": False})
    assert ri.lock_holder() == ""


def test_the_button_refuses_instead_of_pretending_when_the_door_is_held():
    from tradingagents import api

    src = inspect.getsource(api.strategies_reindex)
    assert 'st.get("blocked_by")' in src
    assert '"started": False' in src.split('blocked_by')[-1][:400], \
        "a locked index must NOT report started"


# ------------------------------------------------------ 4. the missing log
def test_the_indexer_writes_a_log_instead_of_DEVNULL():
    """This process is the only thing that prints "paused: a backtest is
    running" and "indexing N pairs". Every line went to DEVNULL, so when it
    stalled there was nothing to read — it took walking the process table and
    sampling CPU to find it idle at 0%."""
    src = inspect.getsource(ri.spawn_indexer)
    assert "stdout=subprocess.DEVNULL" not in src, \
        "the indexer's own account of itself was being thrown away"
    assert "stdout=log" in src and "stderr=subprocess.STDOUT" in src
    assert "LOGFILE" in src
    # WHERE IT DEFAULTS TO, read from the module's own source — not from
    # `ri.LOGFILE` at runtime. conftest sandboxes that constant into tmp_path
    # on purpose (so a test run can never write into the operator's real
    # ~/.tradingagents), which made the runtime spelling permanently
    # `tradingagents_state` and this assertion permanently red on main. A
    # guard that the test harness itself makes impossible proves nothing and
    # hides the six other failures beside it.
    import pathlib
    import re

    mod = pathlib.Path(ri.__file__).read_text(encoding="utf-8")
    line = re.search(r"^LOGFILE\s*=.*$", mod, re.M)
    assert line, "rows_index no longer declares LOGFILE"
    assert "rows_index.log" in line.group(0)
    assert ".tradingagents" in line.group(0), \
        "beside db_backtest.log and db_collect.log, where the others are"


def test_the_log_is_not_buffered_away():
    """A log that only appears when the process exits is no use for a process
    meant to run for days."""
    src = inspect.getsource(ri.spawn_indexer)
    assert '"PYTHONUNBUFFERED": "1"' in src


@pytest.mark.parametrize("field", ["stale", "last_error", "blocked_by"])
def test_every_new_field_is_actually_served(field):
    assert field in ri.status()
