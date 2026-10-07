"""Each room whose runner the operator wants is stopped and started on the
new code; a room nobody started is left alone (Oct 07, 2026, for
`python start.py api`)."""
from __future__ import annotations

import contextlib

from tradingagents import room_restart as rr


class Room:
    def __init__(self, wants, pid):
        self.wants, self.pid = wants, pid
        self.events: list = []


def test_only_wanted_rooms_restart_and_each_waits_for_its_old_runner(monkeypatch):
    rooms = {"main": Room(True, 11), "55D32617": Room(False, 0), "4FC03172": Room(True, 22)}
    cur = {"id": None}

    @contextlib.contextmanager
    def using(pid):
        cur["id"] = pid
        yield

    class AT:
        @staticmethod
        def wants_runner():
            return rooms[cur["id"]].wants

        @staticmethod
        def runner_pid():
            return rooms[cur["id"]].pid or None

        @staticmethod
        def stop_runner():
            rooms[cur["id"]].events.append("stop")
            return True

        @staticmethod
        def start_runner():
            rooms[cur["id"]].events.append("start")
            return 99

    alive = {11: [True, False], 22: [False]}
    monkeypatch.setattr(rr, "_ids", lambda: list(rooms))
    monkeypatch.setattr(rr, "_using", using)
    monkeypatch.setattr(rr, "_at", lambda: AT)
    monkeypatch.setattr(rr, "_alive", lambda pid: alive[pid].pop(0) if alive[pid] else False)
    monkeypatch.setattr(rr.time, "sleep", lambda s: None)
    done = rr.restart_rooms()
    assert done == ["main", "4FC03172"]
    assert rooms["main"].events == ["stop", "start"]
    assert rooms["4FC03172"].events == ["stop", "start"]
    assert rooms["55D32617"].events == []
