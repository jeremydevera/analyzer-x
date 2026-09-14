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
        # EVENT-DRIVEN RUNNER. The cycle waits on this instead of a timer;
        # anything that could change a decision sets it. The runner clears
        # it, never the feed (operator, Sep 14, 2026: "there should be no
        # refresh from now on").
        self.wake = threading.Event()
        # (symbol, interval) -> the OPEN time of the newest bar seen. MEXC
        # pushes a forming bar repeatedly and `t` is its open, so `t` moving
        # on is the only signal that the PREVIOUS bar is final.
        self._kline_at: dict[tuple, int] = {}
        self._want_klines: set[tuple] = set()
        self._subbed_klines: set[tuple] = set()
        self._closed_bars: set[tuple] = set()
        # slot_key -> the barriers to watch, so a tick can say "cycle NOW".
        # A TRIGGER ONLY: `auto_trader._dry_fill` still decides the outcome.
        self._barriers: dict[str, dict] = {}
        self._hits: dict[str, tuple] = {}
        # private stream: the runner learns a LIVE fill when it happens
        self._creds: tuple | None = None
        self._logged_in = False
        self._personal: list = []

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

    def track_klines(self, pairs) -> None:
        """The (symbol, interval) bars worth waiting on — every armed
        strategy's own timeframe. A closed bar here wakes the cycle, which is
        what replaces waking on a clock."""
        want = {(str(s), str(i)) for s, i in pairs if s and i}
        with self._lock:
            if want == self._want_klines:
                return
            self._want_klines = want
        self._nudge()

    def arm(self, slot_key: str, symbol: str, side: int, tp: float,
            sl: float, since_ts: float) -> None:
        """Watch a DEMO position's barriers on every tick.

        This is a TRIGGER, not a decision. When a tick crosses, the feed sets
        `wake` and the cycle runs `_dry_fill` over the real tick history,
        which is the single place a fill is ever decided. A trigger that is
        slightly wrong therefore costs one extra cycle, never a wrong book.
        """
        row = {"symbol": str(symbol), "side": int(side), "tp": float(tp),
               "sl": float(sl), "since": float(since_ts)}
        with self._lock:
            was = self._barriers.get(str(slot_key))
            self._barriers[str(slot_key)] = row
            # A recorded hit means "already told the runner about this one",
            # which is what stops one crossing waking every cycle for ever.
            # But if the BARRIERS themselves changed, the old hit is about a
            # trade that no longer exists and would silence the new one.
            if was is not None and was != row:
                self._hits.pop(str(slot_key), None)

    def keep_only(self, slot_keys) -> None:
        """Forget every armed barrier that is not in `slot_keys` — a closed
        position must not keep waking the runner."""
        keep = {str(k) for k in slot_keys}
        with self._lock:
            for k in [k for k in self._barriers if k not in keep]:
                self._barriers.pop(k, None)
                self._hits.pop(k, None)

    def use_credentials(self, api_key: str, api_secret: str) -> None:
        """Log in to the PRIVATE stream, so a live fill at MEXC reaches the
        runner when it happens instead of on the next look. Read-only: no
        order is ever placed over this socket."""
        creds = (str(api_key), str(api_secret)) if api_key and api_secret else None
        with self._lock:
            if creds == self._creds:
                return
            self._creds = creds
            self._logged_in = False
        self._nudge()

    def _nudge(self) -> None:
        loop, w = self._loop, self._wake
        if loop and w:
            with _quiet():
                loop.call_soon_threadsafe(w.set)

    # -------------------------------------------------------------- drains
    def drain_closed_bars(self) -> set:
        """(symbol, interval) pairs whose bar closed since the last drain."""
        with self._lock:
            out, self._closed_bars = self._closed_bars, set()
        return out

    def drain_hits(self) -> dict:
        """slot_key -> (why, ts) for barriers a tick crossed. Trigger only."""
        with self._lock:
            out, self._hits = self._hits, {}
        return out

    def drain_personal(self) -> list:
        """Private-stream events since the last drain (live fills, position
        and order changes, liquidation risk)."""
        with self._lock:
            out, self._personal = self._personal, []
        return out

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
                "logged_in": self._logged_in,
                "klines": sorted(f"{s}/{i}" for s, i in self._want_klines),
                "armed": sorted(self._barriers),
                "pending_hits": sorted(self._hits),
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
        self._check_barriers(symbol, float(price), ts)

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
            kwant, khave = set(self._want_klines), set(self._subbed_klines)
            creds, logged = self._creds, self._logged_in
        for sym in sorted(want - have):
            for method in ("sub.ticker", "sub.deal"):
                await ws.send(json.dumps({"method": method,
                                          "param": {"symbol": sym}}))
        for sym in sorted(have - want):
            for method in ("unsub.ticker", "unsub.deal"):
                with _quiet():
                    await ws.send(json.dumps({"method": method,
                                              "param": {"symbol": sym}}))
        for sym, iv in sorted(kwant - khave):
            await ws.send(json.dumps({"method": "sub.kline",
                                      "param": {"symbol": sym,
                                                "interval": iv}}))
        for sym, iv in sorted(khave - kwant):
            with _quiet():
                await ws.send(json.dumps({"method": "unsub.kline",
                                          "param": {"symbol": sym,
                                                    "interval": iv}}))
        if creds and not logged:
            # The private stream carries LIVE fills. Signed exactly like a
            # REST call (key + timestamp + empty parameter string) with the
            # project's one signer, so there is no second copy of the scheme
            # to drift from it. A login failure leaves the PUBLIC feed whole.
            from tradingagents.dataflows.mexc_futures import sign

            ts = str(int(time.time() * 1000))
            await ws.send(json.dumps({"method": "login", "param": {
                "apiKey": creds[0], "reqTime": ts,
                "signature": sign(creds[0], creds[1], ts)}}))
        with self._lock:
            self._subscribed = want
            self._subbed_klines = kwant

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
        elif ch == "push.kline" and sym and isinstance(data, dict):
            self._on_kline(sym, data)
        elif ch == "rs.login":
            ok = data == "success"
            self._logged_in = bool(ok)
            if ok:
                logger.info("live feed logged in - MEXC will push this "
                            "account's fills as they happen")
            else:
                self._last_error = f"login refused: {data}"
                logger.warning("live feed login refused (%s) - live fills "
                               "still arrive on the next cycle", data)
        elif isinstance(ch, str) and ch.startswith("push.personal."):
            with self._lock:
                self._personal.append({"channel": ch, "data": data,
                                       "at": time.time()})
                if len(self._personal) > 500:
                    del self._personal[:-500]
            # a real position changing at the venue is always worth a cycle
            if ch in ("push.personal.position", "push.personal.order"):
                self.wake.set()

    def _on_kline(self, symbol: str, d: dict) -> None:
        """A bar is CLOSED when its successor appears.

        MEXC pushes the forming bar over and over with `t` fixed at its OPEN
        time, so there is no "final" flag to read: `t` moving on is the
        event. The FIRST push for a pair only establishes the baseline - it
        says nothing about the bar before it, which this process never saw
        forming, and treating it as a close would fire an entry check on a
        candle the runner had already acted on.
        """
        iv = str(d.get("interval") or "")
        t = d.get("t")
        if not iv or t is None:
            return
        try:
            t = int(t)
        except (TypeError, ValueError):
            return
        key = (symbol, iv)
        with self._lock:
            prev = self._kline_at.get(key)
            self._kline_at[key] = t
            fresh_bar = prev is not None and t > prev
            if fresh_bar:
                self._closed_bars.add(key)
        if fresh_bar:
            self.wake.set()

    def _check_barriers(self, symbol: str, price: float, ts: float) -> None:
        """Trigger only - see `arm`."""
        fired = False
        with self._lock:
            for slot, br in self._barriers.items():
                if br["symbol"] != symbol or slot in self._hits:
                    continue
                if ts <= br["since"]:
                    continue        # never a print from before the order
                if br["side"] > 0:
                    why = ("SL" if price <= br["sl"]
                           else "TP" if price >= br["tp"] else None)
                else:
                    why = ("SL" if price >= br["sl"]
                           else "TP" if price <= br["tp"] else None)
                if why:
                    self._hits[slot] = (why, ts)
                    fired = True
        if fired:
            self.wake.set()


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
