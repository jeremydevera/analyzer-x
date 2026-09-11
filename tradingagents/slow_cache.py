"""A value that is slow to read, served instantly from the last read.

Two endpoints have now taken the page down the same way, one day apart in the
same file of RCAs (`docs/RCA.md`, A and I): a panel polls a route every few
seconds, the route shells out to `gh` and `git` for a minute or more, and every
poll is a request that never comes back. On Sep 09, 2026 `/api/cloud/status`
took **216.3 s**, the panel asked every 4 s, four of them sat in flight
holding all four browser lanes (`webapp/src/lib/api.ts` MAX_LANES), and the
operator's filtered table request waited behind them for five minutes with the
button reading "searching 306s". The API was fine. The page was dead.

The rule this module carries: **a request never waits for GitHub.** The slow
read runs in ONE background thread; the request answers with the last value it
produced, or says it is still reading. A failure is a value too — a `gh` that
is timing out will time out again a second later, and re-discovering that on
every poll is what starves the app.

    STATUS = BackgroundValue("cloud-status", _read_cloud_status, ttl=30.0)

    @app.get("/api/cloud/status")
    def cloud_status():
        return STATUS.get(pending={"available": False,
                                   "why": "reading GitHub in the background"})
"""
from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from typing import Any


class BackgroundValue:
    """The last answer of `reader()`, refreshed in the background at most once
    per `ttl` seconds. `get()` never blocks on the reader."""

    def __init__(self, name: str, reader: Callable[[], Any], ttl: float,
                 on_error: Callable[[BaseException], Any] | None = None):
        self.name = name
        self.reader = reader
        self.ttl = float(ttl)
        # a failure becomes the value, so a broken read is not retried on
        # every poll; the caller decides what a failure looks like on screen
        self.on_error = on_error or (lambda exc: {
            "ok": False, "why": f"{type(exc).__name__}: {exc}"})
        self._lock = threading.Lock()
        self._at = 0.0
        self._value: Any = None
        self._have = False
        self._busy = False
        self.reads = 0                  # how many background reads ran (tests)

    # ------------------------------------------------------------ reading
    def get(self, pending: Any = None) -> Any:
        """The last value, kicking a refresh if it is stale. `pending` is what
        the caller gets before the FIRST read lands."""
        with self._lock:
            stale = not self._have or time.time() - self._at >= self.ttl
            if stale and not self._busy:
                self._busy = True
                threading.Thread(target=self._work, name=self.name,
                                 daemon=True).start()
            if self._have:
                return self._value
        return pending

    def _work(self) -> None:
        """`_busy` is released in a FINALLY, always.

        `get()` refuses to start a second read while `_busy` is set, which is
        what stops a slow reader being asked twenty times a minute. The cost
        of that is a LATCH: anything which leaves this method without clearing
        the flag means no further read is ever attempted for the life of the
        process, and the caller keeps whatever it last had -- or `pending` for
        ever if it never had anything.

        `except Exception` does not cover `BaseException`, so a
        `KeyboardInterrupt` or `SystemExit` raised inside a reader, or an
        `on_error` that itself raises, used to latch it shut. That is the same
        shape as the wedge found on Sep 12, 2026, where the reader simply
        never returned -- `git fetch`'s post-timeout drain blocking in
        `communicate()` -- and the cloud panel read "reading GitHub in the
        background" for the 17 minutes until the API was restarted. That one
        is fixed at its source (`cloud_sweep._git` is bounded now); this makes
        the latch itself survivable instead of trusting every future reader.
        """
        got, have = None, False
        try:
            got, have = self.reader(), True
        except Exception as exc:                                # noqa: BLE001
            with contextlib.suppress(Exception):
                got, have = self.on_error(exc), True
        finally:
            with self._lock:
                if have:
                    self._value, self._have = got, True
                    self.reads += 1
                # the CLOCK moves either way, so a reader that blew up is not
                # re-run on the very next poll; and the flag always clears
                self._at = time.time()
                self._busy = False

    # ------------------------------------------------------------- control
    def wait(self, timeout: float = 30.0) -> bool:
        """Block until a value exists — for tests and one-off scripts, never
        for a request."""
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                if self._have:
                    return True
            time.sleep(0.02)
        return False

    def forget(self) -> None:
        with self._lock:
            self._have, self._value, self._at, self._busy = False, None, 0.0, False

    @property
    def age(self) -> float:
        """Seconds since the value was read; inf before the first read."""
        with self._lock:
            return time.time() - self._at if self._have else float("inf")
