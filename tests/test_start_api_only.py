"""`python start.py api` — restart the back end and the room programs only
(Oct 07, 2026; the fixer's one allowed restart, and the operator's own rule:
"start.py start darkens the site 3+ min", so a code fix must not take the
page down).

Held here: the API port is freed with tree=False (its detached children —
runners, jobs, a running fixer — survive), the page's port is never touched,
uvicorn starts exactly as `start` starts it, and the rooms are restarted only
after the back end answers.
"""
from __future__ import annotations

import pytest

import start


@pytest.fixture
def calls(monkeypatch):
    seen: dict = {"free": [], "spawn": [], "rooms": 0, "health": []}
    monkeypatch.setattr(start, "wait_for_downloads", lambda *a, **k: None)
    monkeypatch.setattr(start, "free_port",
                        lambda port, *, tree: seen["free"].append((port, tree)))
    monkeypatch.setattr(start, "spawn",
                        lambda cmd, log, cwd, env=None: seen["spawn"].append(cmd) or 777)
    monkeypatch.setattr(start, "fresh", lambda p: p)
    monkeypatch.setattr(start.time, "sleep", lambda s: None)

    def rooms():
        seen["rooms"] += 1
        return seen.get("rooms_code", 0)
    monkeypatch.setattr(start, "_restart_rooms", rooms)
    monkeypatch.setattr(start, "_dirty_code", lambda: [])
    seen["bells"] = []
    monkeypatch.setattr(start, "_bell", lambda title: seen["bells"].append(title))
    monkeypatch.delenv("TA_FIXER", raising=False)
    return seen


def test_only_the_back_end_restarts(calls, monkeypatch, tmp_path):
    monkeypatch.setattr(start, "LOGS", tmp_path)
    monkeypatch.setattr(start, "health",
                        lambda port, timeout=2.0: calls["health"].append((port, timeout)) or True)
    assert start.cmd_api(now=True) == 0
    assert calls["free"] == [(start.API_PORT, False)]
    assert all(port != start.UI_PORT for port, _ in calls["free"])
    assert calls["spawn"] == [start.api_command()]
    ports = [p for p, _t in calls["health"]]
    assert start.API_PORT in ports and start.UI_PORT not in ports
    assert calls["rooms"] == 1


def test_the_start_command_uses_the_same_back_end_command(calls, monkeypatch, tmp_path):
    """One definition of how the back end starts, so `api` can never drift
    from `start`."""
    import inspect

    assert "_start_api()" in inspect.getsource(start.cmd_start)
    assert "_start_api()" in inspect.getsource(start.cmd_api)
    assert "api_command()" in inspect.getsource(start._start_api)


def test_rooms_wait_for_the_back_end(calls, monkeypatch, tmp_path):
    """New code that cannot start the back end must not be pushed into the
    rooms as well: they keep running the old code in memory."""
    monkeypatch.setattr(start, "LOGS", tmp_path)
    monkeypatch.setattr(start, "health", lambda port, timeout=2.0: False)
    assert start.cmd_api(now=True) == 1
    assert calls["rooms"] == 0


def test_the_word_api_is_a_command():
    assert start.COMMANDS["api"] is start.cmd_api


def test_the_fixer_never_restarts_onto_someone_elses_unfinished_code(calls, monkeypatch, tmp_path):
    """C3: `start.py api` starts the back end and every room from the shared
    checkout. During the final review main moved under it with +244 lines of
    another session's auto_trader.py; a fixer restart then would have put
    every room on half-written trading code, unattended."""
    monkeypatch.setattr(start, "LOGS", tmp_path)
    monkeypatch.setattr(start, "health", lambda port, timeout=2.0: True)
    monkeypatch.setattr(start, "_dirty_code", lambda: ["tradingagents/auto_trader.py"])
    monkeypatch.setenv("TA_FIXER", "1")
    assert start.cmd_api(now=True) == 3
    assert calls["free"] == [] and calls["rooms"] == 0
    # a person restarting by hand decides for themselves
    monkeypatch.delenv("TA_FIXER")
    assert start.cmd_api(now=True) == 0


def test_the_back_end_gets_long_enough_to_answer(calls, monkeypatch, tmp_path):
    """I6: /api/health measured 26 s on the first call after an API-only
    restart and up to 77 s under load; 30 probes of 2 s called a slow back
    end dead and left the rooms unrestarted."""
    monkeypatch.setattr(start, "LOGS", tmp_path)
    timeouts: list = []
    monkeypatch.setattr(start, "health",
                        lambda port, timeout=2.0: timeouts.append(timeout) or False)
    start.cmd_api(now=True)
    assert min(timeouts) >= 10
    assert sum(timeouts) >= 150


def test_a_back_end_that_does_not_come_back_rings_the_bell(calls, monkeypatch, tmp_path):
    monkeypatch.setattr(start, "LOGS", tmp_path)
    monkeypatch.setattr(start, "health", lambda port, timeout=2.0: False)
    assert start.cmd_api(now=True) == 1
    assert calls["bells"] and "did not come back" in calls["bells"][0]


def test_a_room_that_could_not_be_restarted_is_not_a_success(calls, monkeypatch, tmp_path):
    """I5: room_restart failing printed nothing and `api` still said 0."""
    monkeypatch.setattr(start, "LOGS", tmp_path)
    monkeypatch.setattr(start, "health", lambda port, timeout=2.0: True)
    calls["rooms_code"] = 1
    assert start.cmd_api(now=True) == 4


def test_the_rooms_are_restarted_by_the_projects_own_python(monkeypatch, tmp_path):
    ran: list = []

    class R:
        returncode = 0
        stdout = "restarted 3 room(s)"

    monkeypatch.setattr(start.subprocess, "run", lambda cmd, **kw: ran.append((cmd, kw)) or R())
    start._restart_rooms()
    cmd, kw = ran[0]
    assert cmd[0] == start.venv_python()
    assert cmd[1:] == ["-m", "tradingagents.room_restart"]
