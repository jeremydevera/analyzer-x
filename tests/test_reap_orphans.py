"""The reaper must never be able to signal a live process.

On 2026-08-25 the Mac carried 139 pool workers from sweeps up to three days old,
reparented to init, load average 49 on 8 cores. The obvious fix — `pkill -f
python` — would also have taken the LIVE TRADING RUNNER, the API and the web
app. So the selection is three ANDed tests and the tests below try to break it.
"""

from tradingagents import reap_orphans as ro

VENV = ro.VENV
POOL = (f"{VENV}/bin/python -c from multiprocessing.spawn import spawn_main; "
        "spawn_main(tracker_fd=8, pipe_handle=12)")


def _rows(monkeypatch, rows):
    monkeypatch.setattr(ro, "_ps", lambda: rows)
    monkeypatch.setattr(ro, "protected", lambda: {1})


def test_an_orphaned_pool_worker_is_reaped(monkeypatch):
    _rows(monkeypatch, [{"pid": 500, "ppid": 1, "cpu": 0.0, "etime": "3-01:00",
                         "args": POOL}])
    assert [r["pid"] for r in ro.orphans()] == [500]


def test_a_live_pools_worker_is_never_reaped(monkeypatch):
    """Identical argv — the ONLY difference is that its parent is alive."""
    _rows(monkeypatch, [{"pid": 501, "ppid": 22370, "cpu": 64.0,
                         "etime": "46:06", "args": POOL}])
    assert ro.orphans() == []


def test_the_live_trading_runner_is_never_reaped(monkeypatch):
    """It is ppid 1 (launchd) and it is this venv's python. Only the argv
    saves it, so the argv test is not decoration."""
    _rows(monkeypatch, [{"pid": 68282, "ppid": 1, "cpu": 2.0, "etime": "9-00:00",
                         "args": f"{VENV}/bin/python3 -m tradingagents.auto_trader run"}])
    assert ro.orphans() == []


def test_the_orchestrator_and_indexer_are_never_reaped(monkeypatch):
    _rows(monkeypatch, [
        {"pid": 22370, "ppid": 1, "cpu": 0.1, "etime": "49:12",
         "args": f"{VENV}/bin/python -m tradingagents.sweep_orchestrator"},
        {"pid": 7227, "ppid": 1, "cpu": 0.0, "etime": "2-00:00",
         "args": f"{VENV}/bin/python -m tradingagents.rows_index"}])
    assert ro.orphans() == []


def test_another_projects_python_is_never_reaped(monkeypatch):
    """Same multiprocessing argv, different virtualenv. Not ours to kill."""
    _rows(monkeypatch, [{"pid": 900, "ppid": 1, "cpu": 0.0, "etime": "1:00",
                         "args": "/opt/other/.venv/bin/python -c from "
                                 "multiprocessing.spawn import spawn_main"}])
    assert ro.orphans() == []


def test_an_explicitly_protected_pid_survives_a_matching_argv(monkeypatch):
    monkeypatch.setattr(ro, "_ps", lambda: [
        {"pid": 777, "ppid": 1, "cpu": 0.0, "etime": "1:00", "args": POOL}])
    monkeypatch.setattr(ro, "protected", lambda: {1, 777})
    assert ro.orphans() == []


def test_a_dry_run_signals_nothing(monkeypatch):
    sent = []
    monkeypatch.setattr(ro.os, "kill", lambda p, s: sent.append((p, s)))
    _rows(monkeypatch, [{"pid": 500, "ppid": 1, "cpu": 0.0, "etime": "1:00",
                         "args": POOL}])
    r = ro.reap(dry_run=True)
    assert r["found"] == 1 and sent == []


def test_term_first_then_kill_only_the_survivors(monkeypatch):
    import signal
    sent = []
    monkeypatch.setattr(ro.os, "kill", lambda p, s: sent.append((p, s)))
    monkeypatch.setattr(ro.time, "sleep", lambda s: None)
    rows = [{"pid": 500, "ppid": 1, "cpu": 0.0, "etime": "1:00", "args": POOL},
            {"pid": 501, "ppid": 1, "cpu": 0.0, "etime": "1:00", "args": POOL}]
    monkeypatch.setattr(ro, "protected", lambda: {1})
    calls = {"n": 0}

    def ps():
        calls["n"] += 1
        return rows if calls["n"] == 1 else rows[:1]   # 501 died on TERM

    monkeypatch.setattr(ro, "_ps", ps)
    r = ro.reap()
    assert r == {"found": 2, "termed": 2, "killed": 1, "pids": [500, 501]}
    assert (500, signal.SIGTERM) in sent and (501, signal.SIGTERM) in sent
    assert (500, signal.SIGKILL) in sent and (501, signal.SIGKILL) not in sent


def test_a_dead_pid_between_listing_and_signalling_is_not_an_error(monkeypatch):
    def boom(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(ro.os, "kill", boom)
    monkeypatch.setattr(ro.time, "sleep", lambda s: None)
    _rows(monkeypatch, [{"pid": 500, "ppid": 1, "cpu": 0.0, "etime": "1:00",
                         "args": POOL}])
    assert ro.reap()["termed"] == 0
