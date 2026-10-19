"""Stored strategies takes in EVERY night's backtest (P0, RCA-2026-10-19-A).

The operator, Oct 19, 2026: *"Why did you not updated it? Why did you not
asses that bactest stored strategies must be updated as well, you did know
that stored strategies is very important to me"*, then *"Make rca and
document this because this is getting frustrating, this is p0 critical issue
i dont want to happen this anymore in the future"*.

What happened: the Backtest v2 list (Stored strategies) last took in a
backtest on Oct 17, 2026 6:46am. On Oct 18, 2026 5:10am the nightly collect
asked "is a rebuild of the list running?", and `rebuild_progress` answered
yes because SOME program was alive under the number of rebuild 12208 — a
rebuild whose own record had said "done" for 22 hours. The collect left the
filing to it; nothing else files Backtest v2; all 4,144 coin-timeframe pairs
stayed a night behind, and rows that no longer paid 2:1 (#UC4AB4XN, 0G 15m
mom6, 1.98:1 on the Oct 18 measurement) stayed on the list.

The indexer got the same fix on Sep 14, 2026 (`run_lock_held`: "A PID IS NOT
ONE", RCA-2026-09-12-B); the rebuild check was never moved to it. These tests
hold the three layers: a finished rebuild is never running, a rebuild is
running only while it holds its lock, and a list left behind is filed by the
site's supervisor instead of waiting for the next night.
"""
from __future__ import annotations

import json
import os
import time

import pytest

from tradingagents import market_sweep as msw, rows_index as ri


def _pair_file(d, coin, tf, n, **extra):
    f = d / f"{coin}-{tf}.json"
    f.write_text(json.dumps([
        {"id": f"{coin}{tf}{i}", "coin": coin, "tf": tf, "signal": "rsi14",
         "sizing": "flat", "trades": 10, "winrate": 90.0, "profit": 1.0,
         "monthly": {}, **extra} for i in range(n)]), encoding="utf-8")
    return f


@pytest.fixture()
def store(tmp_path, monkeypatch):
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    # the store's real layout: results and watermarks side by side
    (tmp_path / "state").mkdir()
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    monkeypatch.setattr(ri, "REBUILD_PROGRESS", tmp_path / "rows_rebuild.json")
    ri._ready.discard(str(tmp_path / "rows.db"))
    _pair_file(rows_dir, "BTC", "15m", 30)
    _pair_file(rows_dir, "ETH", "1h", 20)
    return tmp_path


def _record(store, phase, pid):
    (store / "rows_rebuild.json").write_text(json.dumps({
        "db": str(store / "rows.db"), "phase": phase, "pairs_done": 4144,
        "pairs_total": 4144, "rows": 12_901_894, "pid": pid}), encoding="utf-8")


# ------------------------------------------------------- "is one running?"


def test_a_finished_rebuild_never_reads_as_running_whatever_owns_its_number(store):
    """Oct 18, 2026 5:10am: the record said "done" (written Oct 17, 2026
    6:46am) and a program was alive under its pid. This process stands in for
    that program: its own pid is alive."""
    _record(store, "done", os.getpid())
    assert ri.rebuild_progress(store / "rows.db")["running"] is False


def test_a_rebuild_is_running_only_while_it_holds_its_lock(store):
    """A rebuild killed part-way leaves a record that never says "done"; its
    number can belong to anything a day later. The lock is the identity."""
    _record(store, "verifying", os.getpid())
    held = ri.take_rebuild_lock()
    assert held is not None
    try:
        assert ri.rebuild_progress(store / "rows.db")["running"] is True
    finally:
        ri.release_rebuild_lock(held)
    assert ri.rebuild_progress(store / "rows.db")["running"] is False, \
        "the same record and a live pid, but nobody holds the lock"


def test_a_rebuild_holds_the_lock_while_it_runs_and_gives_it_up(store, monkeypatch):
    seen = []
    real = ri.swap_in

    def spy(*a, **k):
        seen.append(ri.rebuild_lock_held())
        return real(*a, **k)
    monkeypatch.setattr(ri, "swap_in", spy)
    got = ri.rebuild()
    assert got.get("rebuilt"), got
    assert seen == [True], "held while it rebuilt"
    assert ri.rebuild_lock_held() is False, "and given up when it returned"


def test_a_second_rebuild_refuses_while_one_holds_the_lock(store, monkeypatch):
    monkeypatch.setattr(ri, "REBUILD_LOCK_WAIT_S", 0.3)
    held = ri.take_rebuild_lock()
    try:
        got = ri.rebuild()
    finally:
        ri.release_rebuild_lock(held)
    assert got["rebuilt"] is False and "already running" in got["why"]


def test_the_filing_after_a_collect_starts_a_rebuild_when_the_last_one_is_done(store, monkeypatch):
    """The exact Oct 18, 2026 5:10am state: pairs newer than the list, a
    "done" record whose pid is alive. It must file, not wait."""
    import subprocess

    ri.ensure()
    _record(store, "done", os.getpid())
    monkeypatch.setattr(ri, "BIG_FILL", 1)
    monkeypatch.setattr(ri, "jobs_writing", lambda: "")
    started = []

    class _Proc:
        pid = 4242

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a[0]) or _Proc())
    said = ri.file_after_collect()
    assert "already running" not in said, said
    assert started and "--rebuild" in started[0], said


def test_the_rebuild_files_what_landed_while_it_ran(store, monkeypatch):
    """The rebuild's own after-step (RCA-2026-10-10-O) asked the same
    question about ITSELF: its pid was alive (its own), so any batch bigger
    than BIG_FILL read "a rebuild of it is already running" for ever."""
    import subprocess

    monkeypatch.setattr(ri, "BIG_FILL", 1)
    monkeypatch.setattr(ri, "jobs_writing", lambda: "")
    assert ri.rebuild().get("rebuilt")
    time.sleep(0.05)
    for name in ("SOL-15m.json", "XRP-1h.json"):       # landed during it
        _pair_file(msw.ROWDIR, name.split("-")[0], name.split("-")[1][:-5], 5)
    started = []

    class _Proc:
        pid = 4343

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a[0]) or _Proc())
    _record(store, "done", os.getpid())                 # this very process
    said = ri.file_after_collect()
    assert started, said


# ------------------------------------------------- what the list keeps


def test_the_list_keeps_what_each_row_really_paid(store):
    """The 2:1 rule is judged on `rt_paid` when a row is filed, but the list
    never saved it: every one of 12,901,894 rows read NULL, so any check made
    from the list fell back to the estimate and called 2,505,201 of them not
    2:1."""
    _pair_file(msw.ROWDIR, "GPS", "15m", 3, rt_paid=0.2025)
    ri.ensure()
    with ri._open() as con:
        ri.index_pair(msw.ROWDIR / "GPS-15m.json", con)
        got = {r[0] for r in con.execute("SELECT rt_paid FROM rows WHERE pair = 'GPS-15m'")}
    assert got == {0.2025}


# ------------------------------------------- the safety net (supervisor)


class _V2:
    """A store the way the site's supervisor names Backtest v2."""

    def __init__(self, home):
        self.home = home
        self.rows_db = home / "rows.db"

    def env_for(self):
        return {"TA_ROWS_DB": str(self.rows_db)}


def _behind(store, minutes):
    old = time.time() - minutes * 60
    for f in msw.ROWDIR.glob("*.json"):
        os.utime(f, (old, old))


def test_a_list_left_behind_is_filed_by_the_supervisor(store, monkeypatch):
    """Nothing else files Backtest v2 (no indexer): a list behind its result
    files for half an hour, with nothing rebuilding or writing, is filed by a
    program started with the store's own settings — never by the site's own
    process, whose list is v1."""
    import subprocess

    monkeypatch.setattr(ri, "jobs_writing", lambda: "")
    ri._LIST_CHECKED.clear()
    _behind(store, 45)
    started = []

    class _Proc:
        pid = 777

    def spawn(cmd, **k):
        started.append((cmd, k.get("env") or {}))
        return _Proc()
    monkeypatch.setattr(subprocess, "Popen", spawn)
    said = ri.keep_list_filed(_V2(store))
    assert started, said
    cmd, env = started[0]
    assert cmd[-2:] == ["tradingagents.rows_index", "--file"]
    assert env.get("TA_ROWS_DB") == str(store / "rows.db"), "the store's own list"
    assert "2 pair(s)" in said


def test_the_supervisor_waits_while_results_are_still_landing_or_a_rebuild_runs(store, monkeypatch):
    import subprocess

    monkeypatch.setattr(ri, "jobs_writing", lambda: "")
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a) or None)
    # results landed 5 minutes ago: the collect may still be landing more
    ri._LIST_CHECKED.clear()
    _behind(store, 5)
    assert ri.keep_list_filed(_V2(store)) == "" and not started
    # behind, but a rebuild holds the lock
    ri._LIST_CHECKED.clear()
    _behind(store, 45)
    held = ri.take_rebuild_lock()
    try:
        assert ri.keep_list_filed(_V2(store)) == "" and not started
    finally:
        ri.release_rebuild_lock(held)
    # and it asks at most every LIST_CHECK_EVERY_S, never every 30 s tick
    assert ri.keep_list_filed(_V2(store)) == "" and not started


def test_the_site_supervisor_runs_the_safety_net_for_backtest_v2():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "tradingagents" / "api.py").read_text(encoding="utf-8")
    assert "keep_list_filed(_st.V2)" in src


def test_a_filing_program_files_on_the_command_line():
    import inspect

    assert '"--file"' in inspect.getsource(ri.main)


# ------------------------------- only the NEWEST backtest's rows are listed


T_OLD = 1_792_040_400_000          # Oct 12, 2026 (ARK's last rows)
T_NEW = 1_792_299_600_000          # Oct 18, 2026 (its newest backtest)


def _v2_rows(coin, tf, specs):
    d = msw.ROWDIR / f"{coin}-{tf}.json"
    d.write_text(json.dumps([
        {"id": f"{coin}{tf}{i}", "coin": coin, "tf": tf, "signal": "volclimax",
         "sizing": "flat", "res": "1m", "trades": 30, "wins": 25, "profit": 9.0,
         "tp": tp, "sl": sl, "rt_paid": 0.2, "cost_of_tp": 10.0, "gate": "ok",
         "monthly": {}, **({"last_ms": lm} if lm else {})}
        for i, (tp, sl, lm) in enumerate(specs)]), encoding="utf-8")
    return d


def _listed(pair):
    with ri._open() as con:
        return sorted(r[0] for r in con.execute("SELECT tp FROM rows WHERE pair = ?", (pair,)))


def test_a_row_the_newest_backtest_did_not_produce_is_not_listed(store):
    """US 1h volclimax TP 1.5% / SL 0.3%: rows from Oct 16, 2026 sat in the
    list beside the pair's Oct 18 backtest, which made no trade for them — the
    merge keeps a row the newest run did not write (it must: the rooms read the
    file), and the list showed it as current. 5,579 of 187,070 listed rows on
    a sample of 60 pairs (2.98%)."""
    _v2_rows("US", "1h", [(1.5, 0.3, T_OLD), (2.0, 0.3, T_NEW), (3.0, 0.3, T_NEW)])
    msw.save_states("US", "1h", {"__cloud__": True, "__last_ms__": T_NEW})
    ri.ensure()
    with ri._open() as con:
        ri.index_pair(msw.ROWDIR / "US-1h.json", con)
    assert _listed("US-1h") == [2.0, 3.0]
    assert len(msw.pair_rows("US", "1h")) == 3, "the file keeps every row: the rooms read it"


def test_a_pair_whose_newest_backtest_found_nothing_leaves_the_list(store):
    """ARK, BLUR, COOKIE, LYN, PTB, RARE and VELODROME: Gate cut them to 10x,
    the app trades 20x, so every night's backtest found nothing (`landed 1
    pair(s) · 0 row(s) · ARK 15m`) while their Oct 12 rows stayed listed —
    100,892 rows of strategies the app cannot run."""
    _v2_rows("ARK", "15m", [(1.5, 0.3, T_OLD), (2.0, 0.3, T_OLD)])
    msw.save_states("ARK", "15m", {"__cloud__": True, "__last_ms__": T_NEW})
    ri.ensure()
    with ri._open() as con:
        ri.index_pair(msw.ROWDIR / "ARK-15m.json", con)
    assert _listed("ARK-15m") == []


def test_backtest_v1_rows_and_rows_without_a_date_are_filed_as_before(store):
    d = msw.ROWDIR / "ETH-1h.json"
    d.write_text(json.dumps([
        {"id": "v1old", "coin": "ETH", "tf": "1h", "signal": "rsi14", "sizing": "flat",
         "trades": 10, "tp": 2.0, "sl": 1.0, "monthly": {}, "last_ms": T_OLD},
        {"id": "nodate", "coin": "ETH", "tf": "1h", "signal": "rsi14", "sizing": "flat",
         "res": "1m", "trades": 10, "tp": 3.0, "sl": 1.0, "rt_paid": 0.2,
         "cost_of_tp": 5.0, "gate": "ok", "monthly": {}}]), encoding="utf-8")
    msw.save_states("ETH", "1h", {"__cloud__": True, "__last_ms__": T_NEW})
    ri.ensure()
    with ri._open() as con:
        ri.index_pair(d, con)
    assert _listed("ETH-1h") == [2.0, 3.0]


def test_a_row_another_job_measures_keeps_its_own_date(store):
    """Learned formulas (lx_) and ML models (ml_) are measured by their own
    jobs, never by the nightly grid: their rows carry their own run's date and
    must stay listed beside a newer nightly backtest of the same pair."""
    d = msw.ROWDIR / "SOL-1h.json"
    d.write_text(json.dumps([
        {"id": "lx1", "coin": "SOL", "tf": "1h", "signal": "lx_SOL_1h_3", "sizing": "flat",
         "res": "1m", "trades": 40, "tp": 3.0, "sl": 1.0, "rt_paid": 0.2,
         "cost_of_tp": 5.0, "gate": "ok", "monthly": {}, "last_ms": T_OLD},
        {"id": "new", "coin": "SOL", "tf": "1h", "signal": "volclimax", "sizing": "flat",
         "res": "1m", "trades": 40, "tp": 2.0, "sl": 0.5, "rt_paid": 0.2,
         "cost_of_tp": 5.0, "gate": "ok", "monthly": {}, "last_ms": T_NEW}]), encoding="utf-8")
    msw.save_states("SOL", "1h", {"__cloud__": True, "__last_ms__": T_NEW})
    ri.ensure()
    with ri._open() as con:
        ri.index_pair(d, con)
    assert _listed("SOL-1h") == [2.0, 3.0]
