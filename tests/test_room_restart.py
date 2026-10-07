"""Each room whose runner the operator wants is restarted on the new code; a
room nobody started is left alone; and a room is NEVER left switched off
(Oct 07, 2026, for `python start.py api`).

The final review (I5) found the first version called `stop_runner()`, which
deletes the room's WANT flag before it kills the runner: anything that failed
between that and `start_runner()` left the room with no runner and no WANT,
so the supervisor would never bring it back — and the error was swallowed.
"""
from __future__ import annotations

import contextlib

import pytest

from tradingagents import room_restart as rr


@pytest.fixture
def rooms(monkeypatch):
    rooms = {"main": {"wants": True, "pid": 11, "events": []},
             "55D32617": {"wants": False, "pid": 0, "events": []},
             "4FC03172": {"wants": True, "pid": 22, "events": []}}
    cur = {"id": None}

    @contextlib.contextmanager
    def using(pid):
        cur["id"] = pid
        yield

    class AT:
        @staticmethod
        def wants_runner():
            return rooms[cur["id"]]["wants"]

        @staticmethod
        def runner_pid():
            return rooms[cur["id"]]["pid"] or None

        @staticmethod
        def stop_runner():
            raise AssertionError("stop_runner deletes the WANT flag - never used here")

        @staticmethod
        def start_runner():
            r = rooms[cur["id"]]
            if r.get("start_fails"):
                raise OSError("could not spawn")
            r["events"].append("start")
            return 99

    killed: list = []
    alive = {11: [True, False], 22: [False]}
    monkeypatch.setattr(rr, "_ids", lambda: list(rooms))
    monkeypatch.setattr(rr, "_using", using)
    monkeypatch.setattr(rr, "_at", lambda: AT)
    monkeypatch.setattr(rr, "_kill", lambda pid: killed.append(pid))
    monkeypatch.setattr(rr, "_alive", lambda pid: alive[pid].pop(0) if alive.get(pid) else False)
    monkeypatch.setattr(rr.time, "sleep", lambda s: None)
    return rooms, killed


def test_only_wanted_rooms_restart_and_their_flag_is_never_removed(rooms):
    state, killed = rooms
    done, errors = rr.restart_rooms()
    assert done == ["main", "4FC03172"] and errors == []
    assert killed == [11, 22], "the old runner is ended by its pid, nothing else"
    assert state["main"]["events"] == ["start"]
    assert state["55D32617"]["events"] == []


def test_one_room_failing_never_stops_the_others_and_is_named(rooms, capsys):
    state, _ = rooms
    state["main"]["start_fails"] = True
    done, errors = rr.restart_rooms()
    assert done == ["4FC03172"]
    assert len(errors) == 1 and "main" in errors[0] and "could not spawn" in errors[0]


def test_main_says_what_failed_and_does_not_report_success(rooms, monkeypatch, capsys):
    from tradingagents import notifications

    state, _ = rooms
    state["main"]["start_fails"] = True
    monkeypatch.setattr(notifications, "record", lambda *a, **k: 1)
    assert rr.main() == 1
    assert "could not spawn" in capsys.readouterr().out
