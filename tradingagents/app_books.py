"""The order book the APP can trade, every minute, for every Gate contract
(Oct 16, 2026, RCA-2026-10-16-A).

WHY. Gate's published order-book history (`book_history`, the costs job) holds
RPI offers, and "RPI orders are only matched with non-API taker orders" (Gate,
Jan 07, 2026). The app trades through Gate's API, so it can never fill them,
and every backtest priced off that history got better prices than practice
could. Measured Oct 15, 2026 8:00-8:03pm at the same instants: the record
matched the app's own REST book on BTC 42 of 45 times and on QNTX 0 of 45
(record 36.94 / 36.96, the app's 36.91 / 37.12); ANKR 4 of 45, CLANKER 31,
IOTX 33, RECALL 38. Gate's public feed carries both books - `futures.obu`,
the normal one, equal to REST's order book (QNTX 37.20 / 37.34), and
`futures.rpi_obu`, with the RPI offers (37.20 / 37.22).

WHAT. The operator chose, Oct 16, 2026: "Record app's prices". Every minute,
`READ_AT_S` seconds in - when practice looks - this process asks Gate's feed
for a one-shot snapshot of every contract's normal book (`futures.obu`, 50
levels: all 1,039 contracts answered in ~0.5 s, 1.9 MB, measured Oct 16,
2026) and keeps one reading per coin per minute in `book_history`'s shape,
source "app". `cost_store.engine_book` prefers these readings to Gate's
record wherever both hold a minute (`cost_store.merge`).

WHERE. `~/.tradingagents/app_books/<SYMBOL>/<YYYYMMDD>.bin`, one file per
coin per UTC day on the store's own drive, fixed-size records (`REC`)
APPENDED every `FLUSH_S`: 1,039 coins x 1,440 minutes x 39 bytes is 58 MB a
day of writes, where rewriting each day file every five minutes measured
~5.8 GB a day on this PC's mechanical G: (harddev round 2, Oct 16, 2026).

A minute the feed did not answer for a coin has no reading, and the backtest
falls back to Gate's record for it - never an invented book.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import time
from pathlib import Path

from tradingagents import book_history as bh

HOME = Path(os.path.expanduser("~/.tradingagents")) / "app_books"
WS_URL = "wss://fx-ws.gateio.ws/v4/ws/usdt"
LEVEL = 50                 # futures.obu offers 50 or 400; $100 rarely needs more
CONNS = 4                  # 1,039 streams over 4 connections answered in 0.5 s
BATCH = 100                # streams per subscribe message
NOTIONAL = 100.0           # the runner's $5 x 20, as the costs job walks it
ASK_EARLY_S = 0.5          # ask this early: the snapshots take ~0.4 s to arrive
WAIT_S = 6.0               # a snapshot later than this is not this minute's
FLUSH_S = 300
SIZES_TTL_S = 3600
LOG_EVERY_S = 3600
WARN_EVERY_S = 600         # the same failure is logged once in ten minutes
# THE BACKTEST READS THESE ONLY WHEN EVERY MACHINE CAN (harddev round 3, Oct
# 16, 2026): the nightly v2 update measures on GitHub, which cannot see this
# PC's files, so a PC press preferring them would give one strategy two
# results by where it was measured ("the analysis and the button run the
# same grid"). Recording starts now - a minute not recorded is lost for good
# - and this goes True with the publishing step that lets GitHub read them.
IN_BACKTEST = False

logger = logging.getLogger("app_books")


def _paths() -> dict:
    return {"status": HOME / "status.json", "pid": HOME / "recorder.pid",
            "lock": HOME / "recorder.lock",
            "log": HOME.parent / "app_books.log"}


# ------------------------------------------------------------ one reading
def reading_from_snapshot(result: dict, *, contract_size: float,
                          minute_start: int, seen_at: float | None = None,
                          notional_usd: float = NOTIONAL) -> dict | None:
    """A full `futures.obu` snapshot -> the reading `book_history` makes of a
    replayed book (`_sample`, the same $100 walk of each side), source "app",
    `at` the second of its minute the snapshot ARRIVED (`seen_at`). Never
    Gate's own `t`: that is when the book last CHANGED - 46 minutes before
    the snapshot for NEURALINK on Oct 16, 2026. None when a side is empty or
    the book is crossed."""
    bids, asks = {}, {}
    for side, rows in ((bids, result.get("b")), (asks, result.get("a"))):
        for p, q in rows or []:
            q = float(q)
            if q > 0:
                side[float(p)] = q
    r = bh._sample(bids, asks, int(minute_start), contract_size=contract_size,
                   notional_usd=notional_usd, source="app")
    if r is None:
        return None
    r["at"] = (int(min(max(round(float(seen_at) - minute_start), 0), 59))
               if seen_at else int(bh.READ_AT_S))
    return r


def _sym_of(stream: str | None) -> str | None:
    """"ob.QNTX_USDT.50" -> "QNTX_USDT"."""
    if not stream or "." not in stream:
        return None
    return stream.split(".", 1)[1].rsplit(".", 1)[0]


# ------------------------------------------------------------ the store
def _rec():
    """One reading on disk: the packed month's columns, little-endian, no
    padding - 39 bytes."""
    import numpy as np

    return np.dtype([("t", "<i8"), ("bid", "<f8"), ("ask", "<f8"),
                     ("spread", "<f4"), ("buy", "<f4"), ("sell", "<f4"),
                     ("exhausted", "u1"), ("source", "i1"), ("at", "i1")])


def _day(t: int) -> str:
    return time.strftime("%Y%m%d", time.gmtime(int(t)))


def _day_file(sym: str, day: str) -> Path:
    from tradingagents import cost_store as cs

    # a coin Gate names in Chinese gets cost_store's plain name
    name = cs.asset(sym, "x").rsplit("-", 1)[0]
    return HOME / name / f"{day}.bin"


def _read(path: Path) -> dict | None:
    """The day's records, packed in `cost_store`'s keys. A record cut short
    by a killed process (the file's tail) is dropped, never misread."""
    import numpy as np

    rec = _rec()
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    n = len(raw) // rec.itemsize
    if not n:
        return None
    a = np.frombuffer(raw[:n * rec.itemsize], dtype=rec)
    return {"t": a["t"].astype("int64"), "bid": a["bid"].astype("float64"),
            "ask": a["ask"].astype("float64"),
            "spread": a["spread"].astype("float32"),
            "buy": a["buy"].astype("float32"), "sell": a["sell"].astype("float32"),
            "exhausted": a["exhausted"].astype("bool"),
            "source": a["source"].astype("int8"), "at": a["at"].astype("int8")}


class Store:
    """Readings by coin and UTC day: `add` holds them, `flush` APPENDS each
    coin-day's new records to its file. A restart in the middle of a day
    appends after the morning's records; a minute recorded twice is read
    once (`book_for` keeps the last)."""

    def __init__(self) -> None:
        self.new: dict = {}        # (sym, day) -> [reading, ...] not yet written

    def add(self, sym: str, reading: dict) -> None:
        self.new.setdefault((sym, _day(reading["t"])), []).append(reading)

    def flush(self) -> int:
        import numpy as np

        rec = _rec()
        wrote = 0
        for (sym, day), rows in list(self.new.items()):
            p = bh.pack(rows)
            a = np.zeros(len(p["t"]), dtype=rec)
            for k in rec.names:
                a[k] = p[k]
            path = _day_file(sym, day)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "ab") as fh:
                fh.write(a.tobytes())
            wrote += 1
            self.new.pop((sym, day), None)
        return wrote


def book_for(sym: str, start_s: int, end_s: int) -> dict:
    """Every recorded reading of `sym` in [start_s, end_s], packed in
    `cost_store`'s keys; empty when none was recorded."""
    import numpy as np

    from tradingagents import cost_store as cs

    got = None
    d = int(start_s) - int(start_s) % 86400
    while d <= int(end_s):
        part = _read(_day_file(sym, _day(d)))
        if part is not None and len(part["t"]):
            got = cs.merge(got, part)
        d += 86400
    if got is None:
        return cs.empty()
    got = cs.merge(None, got)              # one reading a minute, the last kept
    t = np.asarray(got["t"], dtype="int64")
    keep = (t >= int(start_s)) & (t <= int(end_s))
    return {k: np.asarray(got[k])[keep] for k in cs.KEYS}


# ------------------------------------------------------------ the snapshots
async def _drain(ws) -> int:
    """Read and drop whatever is already waiting: the last burst's late
    snapshots and its last incremental messages. Cancelling `recv` loses no
    message (websockets' asyncio API), so the next burst starts clean."""
    n = 0
    while True:
        try:
            await asyncio.wait_for(ws.recv(), timeout=0.02)
        except asyncio.TimeoutError:
            return n
        n += 1


async def burst_one(ws, syms: list, *, ask_at: float,
                    deadline_s: float = WAIT_S) -> dict:
    """Subscribe `syms`' normal books on one connection, keep the first FULL
    snapshot of each, with the second it arrived at as `_seen`, unsubscribe.

    Every snapshot that arrives after the subscribe is this minute's book,
    whatever its `t` says: Gate stamps a book with when it last CHANGED, so
    a quiet coin's is minutes old (NEURALINK 46 on Oct 16, 2026) and still
    the book of now. What could pass for a fresh one is a snapshot already
    waiting from the last burst, so those are drained first. Incremental
    messages and coins not asked for are passed over. `ask_at` is the moment
    this burst was meant to ask at; it is kept for the caller's records."""
    await _drain(ws)
    streams = [f"ob.{s}.{LEVEL}" for s in syms]
    for i in range(0, len(streams), BATCH):
        await ws.send(json.dumps({"time": int(time.time()), "channel": "futures.obu",
                                  "event": "subscribe",
                                  "payload": streams[i:i + BATCH]}))
    want, got = set(syms), {}
    end = time.monotonic() + deadline_s
    try:
        while want:
            left = end - time.monotonic()
            if left <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=left)
            except asyncio.TimeoutError:
                break
            if '"full"' not in raw:
                continue                 # incremental or an ack: not a snapshot
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            r = m.get("result")
            if (m.get("channel") != "futures.obu" or not isinstance(r, dict)
                    or not r.get("full")):
                continue
            sym = _sym_of(r.get("s"))
            if sym in want:
                want.discard(sym)
                got[sym] = {**r, "_seen": time.time()}
    finally:
        for i in range(0, len(streams), BATCH):
            with contextlib.suppress(Exception):
                await ws.send(json.dumps({"time": int(time.time()),
                                          "channel": "futures.obu",
                                          "event": "unsubscribe",
                                          "payload": streams[i:i + BATCH]}))
    return got


def _alive(conn) -> bool:
    """Open, in websockets' asyncio API (`close_code` stays None until the
    connection closes) and in the legacy one (`closed`)."""
    return (conn is not None and getattr(conn, "close_code", None) is None
            and not getattr(conn, "closed", False))


async def _connect():
    import websockets

    return await websockets.connect(WS_URL, ping_interval=20, ping_timeout=20,
                                    max_size=2 ** 25, max_queue=None)


async def burst(conns: list, syms: list, *, ask_at: float) -> tuple[dict, list]:
    """Every coin's snapshot over `CONNS` connections at once, reconnecting
    any that died. Returns (snapshots, the reasons any share failed)."""
    parts = [syms[i::len(conns)] for i in range(len(conns))]
    why: list = []

    async def one(i: int) -> dict:
        try:
            if not _alive(conns[i]):
                conns[i] = await _connect()
            return await burst_one(conns[i], parts[i], ask_at=ask_at)
        except Exception as exc:                               # noqa: BLE001
            why.append(f"connection {i}: {type(exc).__name__}: {exc}")
            with contextlib.suppress(Exception):
                await conns[i].close()
            conns[i] = None
            return {}

    got: dict = {}
    for part in await asyncio.gather(*(one(i) for i in range(len(conns)))):
        got.update(part)
    return got, why


# ------------------------------------------------------------ the process
def _sizes() -> dict:
    """Every trading contract's size (`contractSize`), one cached list."""
    from tradingagents.dataflows import exchange as fx

    out = {}
    for sym in fx.trading_symbols():
        with contextlib.suppress(Exception):
            size = float(fx.contract_spec(sym).get("contractSize") or 0.0)
            if size > 0:
                out[sym] = size
    return out


def _status(**kw) -> None:
    p = _paths()["status"]
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(kw), encoding="utf-8")
    with contextlib.suppress(OSError):
        os.replace(tmp, p)


def status() -> dict:
    """What the recorder last said, for the screen and for a person: the
    minute it last read, how many coins answered, and why any did not."""
    try:
        return json.loads(_paths()["status"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


async def run(*, stop=None) -> None:
    """Read every coin's book `READ_AT_S` seconds into every minute, for
    ever. Never exits because one burst or one connection failed: it says
    why in the status and the log, and reads the next minute."""
    from tradingagents.positions_view import fmt_when

    store = Store()
    conns: list = [None] * CONNS
    sizes, sizes_at = {}, 0.0
    flushed = time.time()
    said = 0.0
    started = time.time()
    misses = 0
    warned = {"text": "", "at": 0.0}
    while not (stop and stop.is_set()):
        now = time.time()
        minute = int(now // 60 * 60)
        ask_at = minute + bh.READ_AT_S - ASK_EARLY_S
        if now > ask_at:
            minute += 60
            ask_at += 60
        await asyncio.sleep(max(0.0, ask_at - time.time()))
        if not sizes or time.time() - sizes_at > SIZES_TTL_S:
            try:
                fresh = await asyncio.to_thread(_sizes)
                if fresh:
                    sizes, sizes_at = fresh, time.time()
            except Exception as exc:                           # noqa: BLE001
                logger.warning("could not read Gate's contract list (%s) — "
                               "keeping the last one (%d coins)", exc, len(sizes))
        if not sizes:
            _status(error="no contract list yet", pid=os.getpid(),
                    since=fmt_when(started))
            continue
        got, why = await burst(conns, sorted(sizes), ask_at=ask_at)
        n = 0
        for sym, res in got.items():
            r = reading_from_snapshot(res, contract_size=sizes[sym],
                                      minute_start=minute,
                                      seen_at=res.get("_seen"))
            if r is not None:
                store.add(sym, r)
                n += 1
        missing = len(sizes) - n
        misses += missing
        # the LINE is rate-limited, never the count (CLAUDE.md): the status
        # file and the hourly line carry every missed coin-minute
        text = "; ".join(why)[:400]
        if why and (text != warned["text"]
                    or time.time() - warned["at"] >= WARN_EVERY_S):
            warned.update(text=text, at=time.time())
            logger.warning("%s: %d of %d coins read; %s", fmt_when(minute), n,
                           len(sizes), text)
        if time.time() - flushed >= FLUSH_S:
            try:
                wrote = await asyncio.to_thread(store.flush)
                flushed = time.time()
            except Exception as exc:                           # noqa: BLE001
                wrote = 0
                logger.error("could not write the readings (%s) — kept in "
                             "memory, tried again next minute", exc)
        else:
            wrote = 0
        _status(minute=fmt_when(minute), minute_s=minute, coins=len(sizes),
                read=n, missing=missing, why="; ".join(why)[:300],
                wrote_files=wrote, pid=os.getpid(), since=fmt_when(started))
        if time.time() - said >= LOG_EVERY_S:
            said = time.time()
            logger.info("%s: %d of %d coins read %d s into the minute; %d "
                        "coin-minutes missed since %s", fmt_when(minute), n,
                        len(sizes), bh.READ_AT_S, misses, fmt_when(started))
    with contextlib.suppress(Exception):
        store.flush()


# ------------------------------------------------------------ supervision
_RUN_LOCK = None


def _lock_held() -> bool:
    from tradingagents import portable

    p = _paths()["lock"]
    try:
        fh = open(p, "a+", encoding="utf-8")                   # noqa: SIM115
    except OSError:
        return False
    try:
        portable.lock_exclusive(fh, blocking=False)
    except OSError:
        return True
    else:
        portable.unlock(fh)
        return False
    finally:
        fh.close()


def take_run_lock() -> bool:
    """The recorder's identity, held open for its whole life: a lock, never
    a pid (pids are recycled, RCA-2026-09-12-B)."""
    global _RUN_LOCK
    from tradingagents import portable

    p = _paths()["lock"]
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        fh = open(p, "a+", encoding="utf-8")                   # noqa: SIM115
        portable.lock_exclusive(fh, blocking=False)
    except OSError:
        with contextlib.suppress(Exception):
            fh.close()
        return False
    _RUN_LOCK = fh
    return True


def running() -> bool:
    """Alive only when the lock is held AND the pid file names a live
    process (`rows_index._running_elsewhere`'s rule)."""
    from tradingagents import portable

    if not _lock_held():
        return False
    try:
        pid = int(_paths()["pid"].read_text().strip())
    except (OSError, ValueError):
        return True
    return portable.pid_alive(pid)


def spawn_recorder() -> int | None:
    """Start the recorder in its own process, with no window, when the app
    trades Gate and none is running; None otherwise. Its output goes to its
    own log (a job that cannot start must say so)."""
    import subprocess

    from tradingagents import portable, venue

    if venue.current() != "gate" or running():
        return None
    paths = _paths()
    paths["log"].parent.mkdir(parents=True, exist_ok=True)
    HOME.mkdir(parents=True, exist_ok=True)
    with open(paths["log"], "a", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "tradingagents.app_books", "run"],
            stdout=log, stderr=subprocess.STDOUT, **portable.DETACHED,
            env={**os.environ, "PYTHONUNBUFFERED": "1"})
    paths["pid"].write_text(str(proc.pid))
    return proc.pid


def main(argv: list[str]) -> int:
    from tradingagents.positions_view import WhenFormatter

    if not argv or argv[0] != "run":
        print("usage: python -m tradingagents.app_books run")
        return 2
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(WhenFormatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[h])
    if not take_run_lock():
        logger.info("another recorder holds the lock — nothing to do")
        return 0
    _paths()["pid"].write_text(str(os.getpid()))
    logger.info("up (pid %d): every Gate contract's own order book, %d s "
                "into every minute, into %s", os.getpid(), bh.READ_AT_S, HOME)
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
