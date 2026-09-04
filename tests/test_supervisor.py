"""Keep the runner up — without ever fighting a deliberate STOP.

Bought with a real outage: on 2026-08-22 the runner died at 05:33 from a
fatal OSError on a nearly full disk, and nothing restarted it. Two positions
closed at the exchange on their resting brackets and neither exit reached the
ledger for three hours.
"""
import contextlib
import plistlib

import pytest

import tradingagents.auto_trader as at
from tradingagents import supervisor as sv


@pytest.fixture(autouse=True)
def _paths(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    monkeypatch.setattr(at, "PID_PATH", tmp_path / "auto_trade.pid")
    monkeypatch.setattr(at, "WANT_PATH", tmp_path / "auto_trade.WANT")
    # a tmp lock per test: the REAL lock is held by the operator's live
    # runner, and every test would otherwise exit as the duplicate
    monkeypatch.setattr(at, "LOCK_PATH", tmp_path / "auto_trade.lock")
    monkeypatch.setattr(sv, "PLIST", tmp_path / "agent.plist")


def test_the_agent_restarts_only_while_the_operator_wants_it_up():
    """KeepAlive=true would resurrect a runner the operator just stopped. The
    condition is the want-flag, so STOP is respected."""
    body = sv.plist_body(python="/x/python")
    assert body["KeepAlive"] == {"PathState": {str(at.WANT_PATH): True}}
    assert body["ProgramArguments"] == ["/x/python", "-m",
                                       "tradingagents.auto_trader", "run"]
    assert body["ThrottleInterval"] >= 10, "a crash loop must not spin"
    # round-trips as a real plist
    assert plistlib.loads(plistlib.dumps(body))["Label"] == sv.LABEL


def test_starting_records_the_intent_and_stopping_clears_it(monkeypatch):
    spawned = {}

    class Proc:
        pid = 4242

    monkeypatch.setattr(at.subprocess, "Popen",
                        lambda *a, **kw: spawned.update(a=a) or Proc())
    assert at.wants_runner() is False
    at.start_runner()
    assert at.wants_runner() is True, "the supervisor needs the intent recorded"
    assert at.PID_PATH.read_text() == "4242"

    killed = []
    monkeypatch.setattr(at.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    # `stop_runner` only kills a pid that is ALIVE, and 4242 is a made-up
    # number: whether it happens to exist decided this test until 2026-09-04,
    # when it did not and the assert failed on a machine with nothing wrong
    monkeypatch.setattr(at.portable, "pid_alive", lambda pid: int(pid) == 4242)
    at.stop_runner()
    assert at.wants_runner() is False, "a deliberate stop must not be undone"
    assert killed and killed[0][0] == 4242


def test_a_second_start_does_not_spawn_twice_but_still_sets_the_intent(
        monkeypatch):
    """Two runners double every trade."""
    monkeypatch.setattr(at, "runner_pid", lambda: 99)
    calls = []
    monkeypatch.setattr(at.subprocess, "Popen",
                        lambda *a, **kw: calls.append(1))
    assert at.start_runner() == 99
    assert calls == [] and at.wants_runner() is True


def test_the_runner_refuses_to_start_on_a_nearly_full_disk(monkeypatch):
    """A write failing mid-cycle is how it died. Refuse loudly instead."""
    monkeypatch.setattr(at, "runner_pid", lambda: None)
    monkeypatch.setattr(at, "disk_free_mb", lambda: 12)
    with pytest.raises(SystemExit) as e:
        at.run_forever()
    assert e.value.code == 2


def test_a_healthy_disk_does_not_block_the_runner(monkeypatch):
    """The guard must not become the outage: with space free it runs a cycle.

    run_forever handles KeyboardInterrupt itself (a stop finishes the cycle
    in flight), so the proof is that the CYCLE was reached, not that an
    exception escaped.
    """
    monkeypatch.setattr(at, "runner_pid", lambda: None)
    monkeypatch.setattr(at, "disk_free_mb", lambda: 50_000)
    # a book must be enabled or the loop exits before any cycle, by design
    monkeypatch.setattr(at, "active_modes", lambda settings=None: [True])
    monkeypatch.setattr(at, "load_settings", lambda: {})
    monkeypatch.setattr(at, "append_ledger", lambda e: None)
    cycles = []

    def one_cycle(**kw):
        cycles.append(1)
        raise KeyboardInterrupt()

    monkeypatch.setattr(at, "run_cycle", one_cycle)
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        at.run_forever()
    assert cycles, "a healthy disk must let the runner past the guard"


def test_status_reports_what_the_operator_needs_to_decide(monkeypatch):
    monkeypatch.setattr(sv, "loaded", lambda: False)
    got = sv.status()
    for field in ("installed", "loaded", "wants_runner", "pid", "free_mb",
                  "disk_ok", "throttle_seconds"):
        assert field in got


def test_the_agent_never_starts_a_runner_on_its_own(monkeypatch):
    """RunAtLoad=True started a SECOND runner beside a healthy one when the
    agent was installed (2026-08-22). Only the want-flag may start it."""
    assert sv.plist_body()["RunAtLoad"] is False


def test_a_second_runner_cannot_hold_the_lock(tmp_path, monkeypatch):
    """The pid check alone lost a race: both processes lived for seconds while
    the newcomer was importing. The lock cannot race."""
    from tradingagents import portable

    holder = open(at.LOCK_PATH, "w")
    portable.lock_exclusive(holder, blocking=False)

    monkeypatch.setattr(at, "runner_pid", lambda: None)   # pid check passes
    monkeypatch.setattr(at, "disk_free_mb", lambda: 50_000)
    monkeypatch.setattr(at, "active_modes", lambda settings=None: [True])
    monkeypatch.setattr(at, "load_settings", lambda: {})
    monkeypatch.setattr(at, "append_ledger", lambda e: None)
    traded = []
    monkeypatch.setattr(at, "run_cycle", lambda **kw: traded.append(1))
    with pytest.raises(SystemExit) as e:
        at.run_forever()
    assert e.value.code == 1
    assert traded == [], "the loser must exit before it can trade"
    holder.close()


def test_the_api_restarts_a_dead_runner_where_launchd_cannot():
    """Operator, 2026-09-04: *"IF I RUN IT RUN IT / I DONT WANT ANY
    INCONVENIENCE"*. `supervisor.py` is a macOS LaunchAgent; on Windows three
    starts died in a row that morning and nothing brought them back. The
    API's job-supervisor thread now also watches the runner — only off macOS,
    where launchd already does it, and only while the WANT flag is there, so a
    deliberate STOP is never undone."""
    import inspect

    from tradingagents import api

    src = inspect.getsource(api)
    i = src.index("[supervisor] runner was down")
    frag = src[i - 700:i + 200]
    assert "_at.wants_runner()" in frag, "intent first: STOP must stick"
    assert "not _at.runner_pid()" in frag, "only when it is actually down"
    assert "not _portable.MACOS" in frag, "launchd owns it on the Mac"
    assert "_at.start_runner()" in frag


def test_a_restart_cannot_double_the_runner():
    """`start_runner` hands back the live pid instead of spawning a second."""
    import inspect

    src = inspect.getsource(at.start_runner)
    assert "existing = runner_pid()" in src
    assert "if existing:\n        return existing" in src
