"""Restart every room's runner the operator wants, on the code now on disk.

`python start.py api` (Oct 07, 2026) restarts the back end and then calls
this, so a pushed fix reaches the rooms without `start.py start`, which takes
the page down for minutes. A room nobody started (no WANT file) is left
alone, and each room waits for its old runner to be gone before the new one
starts — a runner that still held the run lock would refuse to start.
"""
from __future__ import annotations

import contextlib
import time

WAIT_FOR_OLD_S = 15.0


def _ids() -> list:
    from tradingagents import profiles

    return list(profiles.ids())


def _using(pid):
    from tradingagents import profiles

    return profiles.using(pid)


def _at():
    from tradingagents import auto_trader

    return auto_trader


def _alive(pid) -> bool:
    from tradingagents import portable

    return portable.pid_alive(pid)


def restart_rooms() -> list:
    """The rooms restarted, in order."""
    done = []
    for room in _ids():
        with _using(room):
            at = _at()
            if not at.wants_runner():
                continue
            old = at.runner_pid()
            at.stop_runner()
            deadline = time.monotonic() + WAIT_FOR_OLD_S
            while old and _alive(old) and time.monotonic() < deadline:
                time.sleep(0.25)
            at.start_runner()
            done.append(room)
    return done


def main() -> int:
    from tradingagents import notifications

    with contextlib.suppress(Exception):
        done = restart_rooms()
        print(f"restarted {len(done)} room(s): {', '.join(done)}", flush=True)
        notifications.record("restart", f"Back end and {len(done)} room program(s) "
                             "restarted on the new code",
                             detail=", ".join("Main" if r == "main" else f"#{r}"
                                              for r in done))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
