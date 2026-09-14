"""A live price feed for the DEMO book, so a simulated trade fills like a real one.

Operator, `Sep 14, 2026`: *"is it possible to make demo realtime? like watch
the realtime price of the coin"*.

Why it exists. A live trade has a stop and a target RESTING AT MEXC; it fills
the instant any trade prints through the price, intrabar, on a wick, at 3am.
The demo book owns no order, so it can only look — and it was looking every 60
seconds at closed one-minute bars plus one REST price call. That is accurate to
the minute, which is not the same thing as accurate. On `Sep 13, 2026` NGAS
`JKTTD9GC` closed on the demo book at `10:14pm` for a target first touched at
`10:13pm`.

Polling harder is not the answer and has already been tried. On
`Aug 19, 2026` a 5-second poll produced **77 scans in one minute**, **166**
`code=510 Requests are too frequent` refusals, **668** paper exit checks that
could not read a price at all, and a 106 MB log. REST is the wrong instrument.

So this module subscribes to MEXC's public futures stream
(`wss://contract.mexc.com/edge`) and keeps, per symbol, the ticks it has seen
with their venue timestamps. It is a RECORDER, not a decision-maker: the
barrier rules stay in `auto_trader._dry_fill`, which the backtest and both
books already share. Measured on the operator's own coins, 40 seconds:

| channel | messages per coin |
|---|---|
| `push.ticker` | 15 (a snapshot roughly every 2.7s) |
| `push.deal` | 3-5 (every individual trade) |

Both are recorded. `push.deal` is what catches a wick that stabs a barrier and
retraces; `push.ticker` is the heartbeat that says the feed is alive on a coin
nobody is trading.

Five rules this obeys, all of them bought by an earlier incident:

* **It can only ever make the demo book MORE right, never less.** Every
  reader falls back to the existing closed-bar and last-price checks when the
  feed is down, stale, or has no ticks for a coin. A silent failure here costs
  nothing that was not already being lost.
* **It never touches the live book.** A real exit is the exchange's bracket
  (CLAUDE.md rule 14) and nothing here changes that.
* **It never reaches back before the order existed.** `extremes_since` takes a
  floor and drops every tick at or before it — the same rule as
  `auto_trader._bars_exposed_to`, which exists because the demo book once
  booked a win on price from an hour before the trade (RCA-2026-09-12-A).
* **It never raises into the cycle.** Every public call is total: it answers
  `None` rather than propagating a socket error into the runner's loop.
* **It opens no socket under test.** `PYTEST_CURRENT_TEST` refuses `start()`,
  the same guard `live_ingest.ensure()` carries.
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import threading
import time

logger = logging.getLogger("tradingagents.live_price")

URL = "wss://contract.mexc.com/edge"
# MEXC drops a connection that has not spoken for 60s; ping well inside that.
PING_EVERY_S = 15.0
# How much tick history to keep per symbol. The demo cycle looks every
# DRY_EXIT_POLL_SECONDS (60), so 15 minutes is generous cover for a slow
# cycle, a reconnect, or a wake that was delayed by a busy machine.
KEEP_S = 900.0
# Per-symbol tick cap, so one wild contract cannot grow without bound. At the
# measured rate (~20 messages/coin/40s) 15 minutes is ~450 ticks.
MAX_TICKS = 20_000
# No message of ANY kind for this long means the feed cannot be trusted, and
# every reader falls back. Ticker alone arrives about every 2.7s per coin.
STALE_S = 90.0
# Reconnect backoff, seconds: never hammer the venue after a drop.
BACKOFF_S = (1.0, 2.0, 5.0, 10.0, 30.0)


class PriceFeed:
    """Records ticks per symbol. Thread-safe, total, and fails to silence."""

    def __init__(self, url: str = URL):
        self.url = url
        self._lock = threading.Lock()
        self._ticks: dict[str, collections.deque] = {}
        self._want: set[str] = set()
        self._subscribed: set[str] = set()
        self._last_msg_at: float = 0.0
        self._connected = False
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connects = 0
        self._msgs = 0
        self._last_error = ""

    # ------------------------------------------------------------- control
    def start(self) -> bool:
        """Begin (or keep) the background connection. False when refused."""
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return False            # a test must never open a real socket
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="live-price",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        loop, wake = self._loop, self._wake
        if loop and wake:
            with _quiet():
                loop.call_soon_threadsafe(wake.set)

    def track(self, symbols) -> None:
        """The set of coins worth listening to — the demo book's open coins.

        Subscribing to everything would be 993 contracts of traffic for the
        handful actually holding a simulated position.
        """
        want = {str(s) for s in symbols if s}
        with self._lock:
            if want == self._want:
                return
            self._want = want
        loop, wake = self._loop, self._wake
        if loop and wake:
            with _quiet():
                loop.call_soon_threadsafe(wake.set)

    # -------------------------------------------------------------- readers
    def ticks_since(self, symbol: str, since_ts: float):
        """Every recorded (ts, price) strictly AFTER `since_ts`, oldest first.

        `None` when the feed is stale, the symbol is unknown, or nothing has
        arrived in the window — all three mean "I cannot help", never
        "nothing happened". The caller must fall back, not conclude.

        **This is a TAIL, not a transcript.** Only `KEEP_S` of history is
        retained and a reconnect loses whatever fell in the gap, so an empty
        answer proves nothing. That is safe for the only thing it is used
        for: finding a barrier that WAS crossed. Seeing part of a window can
        discover a fill; it can never invent one. Never use it to conclude a
        barrier was missed.

        Strictly after, never at: a tick stamped exactly when the order went
        out is a print the order may not have been resting for. The demo book
        has already paid once for reading price the trade was never exposed
        to (RCA-2026-09-12-A).
        """
        try:
            if self.stale():
                return None
            cutoff = float(since_ts)
            with self._lock:
                q = self._ticks.get(symbol)
                rows = [(t, p) for t, p in q if t > cutoff] if q else []
            return rows or None
        except Exception as exc:                                # noqa: BLE001
            logger.debug("ticks_since(%s) failed: %s", symbol, exc)
            return None

    def extremes_since(self, symbol: str, since_ts: float):
        """(high, low) over `ticks_since`, or None. Same tail caveat."""
        rows = self.ticks_since(symbol, since_ts)
        if not rows:
            return None
        prices = [p for _t, p in rows]
        return (max(prices), min(prices))

    def last(self, symbol: str):
        """(price, ts) of the newest tick, or None."""
        try:
            if self.stale():
                return None
            with self._lock:
                q = self._ticks.get(symbol)
                if not q:
                    return None
                t, p = q[-1]
            return (p, t)
        except Exception:                                       # noqa: BLE001
            return None

    def stale(self) -> bool:
        return (not self._connected
                or (time.time() - self._last_msg_at) > STALE_S)

    def status(self) -> dict:
        with self._lock:
            counts = {s: len(q) for s, q in self._ticks.items()}
            want = sorted(self._want)
            subbed = sorted(self._subscribed)
        age = time.time() - self._last_msg_at if self._last_msg_at else None
        return {"connected": self._connected, "stale": self.stale(),
                "tracking": want, "subscribed": subbed, "ticks": counts,
                "messages": self._msgs, "connects": self._connects,
                "seconds_since_message": None if age is None else round(age, 1),
                "last_error": self._last_error}

    # --------------------------------------------------------------- engine
    def _record(self, symbol: str, price: float, ts_ms) -> None:
        if not symbol or not price or price <= 0:
            return
        now = time.time()
        if ts_ms:
            try:
                ts = float(ts_ms) / 1000.0
            except (TypeError, ValueError):
                return              # a stamp we cannot read is not a tick
            # A TIMESTAMP WE CANNOT BELIEVE IS DROPPED, NEVER RELABELLED.
            # Stamping an implausible tick with `now` is manufacturing
            # evidence: it would let a print from BEFORE the order answer for
            # the window after it, which is RCA-2026-09-12-A rebuilt out of
            # ticks — and it would make a tick older than KEEP_S immortal.
            # Found by the harddev loop before this shipped.
            if ts > now + 5 or ts < now - KEEP_S:
                return
        else:
            ts = now                # no stamp at all: arrival time is fair
        with self._lock:
            q = self._ticks.get(symbol)
            if q is None:
                q = self._ticks[symbol] = collections.deque(maxlen=MAX_TICKS)
            q.append((ts, float(price)))
            floor = now - KEEP_S
            while q and q[0][0] < floor:
                q.popleft()

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except Exception as exc:                                # noqa: BLE001
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("live price feed stopped: %s", exc)
        finally:
            self._connected = False

    async def _serve(self) -> None:
        import websockets

        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        attempt = 0
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url, ping_interval=None,
                                              open_timeout=20,
                                              close_timeout=5) as ws:
                    self._connected = True
                    self._connects += 1
                    logger.info(
                        "live price feed connected to %s — the demo book now "
                        "fills on prints, not on a 60-second look", self.url)
                    self._last_msg_at = time.time()
                    with self._lock:
                        self._subscribed = set()
                    attempt = 0
                    await self._pump(ws)
            except Exception as exc:                            # noqa: BLE001
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.info("live price feed reconnecting: %s", exc)
            self._connected = False
            if self._stop.is_set():
                return
            delay = BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    async def _sync_subs(self, ws) -> None:
        with self._lock:
            want, have = set(self._want), set(self._subscribed)
        for sym in sorted(want - have):
            for method in ("sub.ticker", "sub.deal"):
                await ws.send(json.dumps({"method": method,
                                          "param": {"symbol": sym}}))
        for sym in sorted(have - want):
            for method in ("unsub.ticker", "unsub.deal"):
                with _quiet():
                    await ws.send(json.dumps({"method": method,
                                              "param": {"symbol": sym}}))
        with self._lock:
            self._subscribed = want

    async def _pump(self, ws) -> None:
        await self._sync_subs(ws)
        last_ping = time.time()
        while not self._stop.is_set():
            if self._wake is not None and self._wake.is_set():
                self._wake.clear()
                await self._sync_subs(ws)
            now = time.time()
            if now - last_ping > PING_EVERY_S:
                await ws.send(json.dumps({"method": "ping"}))
                last_ping = now
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            self._last_msg_at = time.time()
            self._msgs += 1
            try:
                self._on_message(json.loads(raw))
            except Exception as exc:                            # noqa: BLE001
                logger.debug("bad feed message: %s", exc)

    def _on_message(self, m: dict) -> None:
        ch = m.get("channel")
        sym = m.get("symbol")
        data = m.get("data")
        if ch == "push.deal" and sym:
            rows = data if isinstance(data, list) else [data]
            for r in rows:
                if isinstance(r, dict):
                    self._record(sym, _num(r.get("p")), r.get("t"))
        elif ch == "push.ticker" and sym and isinstance(data, dict):
            self._record(sym, _num(data.get("lastPrice")), m.get("ts"))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class _quiet:
    """Swallow an ERROR raised inside — used only where a failure is already
    handled by the surrounding retry and raising would kill the feed.

    Exception, never BaseException: swallowing KeyboardInterrupt or
    SystemExit would make this thread ignore the operator stopping the
    runner. Found by the harddev loop.
    """

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return exc_type is not None and issubclass(exc_type, Exception)


# One feed per process. The runner owns it; readers just ask.
FEED = PriceFeed()
