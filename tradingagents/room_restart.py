"""Restart every room's runner the operator wants, on the code now on disk.

`python start.py api` (Oct 07, 2026) restarts the back end and then calls
this, so a pushed fix reaches the rooms without `start.py start`, which takes
the page down for minutes. A room nobody started (no WANT file) is left
alone, and each room waits for its old runner to be gone before the new one
starts — a runner that still held the run lock would refuse to start.

A ROOM IS NEVER LEFT SWITCHED OFF (final review, I5). The first version
called `stop_runner()`, which deletes the WANT flag before it kills: anything
failing between that and `start_runner()` left a room with no runner and no
WANT, so the supervisor never brought it back, and the error was swallowed.
The old runner is now ended by its pid alone, WANT is never touched, and
every failure is named and returned.
"""
from __future__ import annotations

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


def _kill(pid) -> None:
    from tradingagents import portable

    portable.kill_hard(int(pid))


def restart_rooms() -> tuple[list, list]:
    """(the rooms restarted, one sentence per room that failed)."""
    done: list = []
    errors: list = []
    for room in _ids():
        with _using(room):
            at = _at()
            if not at.wants_runner():
                continue
            old = at.runner_pid()
            if old:
                try:
                    _kill(old)
                except OSError as exc:
                    errors.append(f"{room}: could not end its old runner (pid {old}): "
                                  f"{type(exc).__name__}: {exc}")
                deadline = time.monotonic() + WAIT_FOR_OLD_S
                while _alive(old) and time.monotonic() < deadline:
                    time.sleep(0.25)
            try:
                # start_runner writes WANT first, so even a failed spawn leaves
                # the supervisor a room to bring back
                at.start_runner()
                done.append(room)
            except Exception as exc:                           # noqa: BLE001
                errors.append(f"{room}: could not start its runner: "
                              f"{type(exc).__name__}: {exc}")
    return done, errors


def main() -> int:
    from tradingagents import notifications

    try:
        done, errors = restart_rooms()
    except Exception as exc:                                   # noqa: BLE001
        done, errors = [], [f"{type(exc).__name__}: {exc}"]
    names = ", ".join("Main" if r == "main" else f"#{r}" for r in done)
    print(f"restarted {len(done)} room(s): {names}", flush=True)
    for e in errors:
        print(f"FAILED {e}", flush=True)
    try:
        notifications.record("restart", f"Back end and {len(done)} room program(s) "
                             "restarted on the new code"
                             + (f" — {len(errors)} could not be" if errors else ""),
                             detail=(names + (" · " + " · ".join(errors) if errors else ""))[:500],
                             ok=not errors)
    except Exception:                                          # noqa: BLE001
        pass
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
