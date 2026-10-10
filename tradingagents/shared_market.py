"""One price board and one set of candles for EVERY trading room on this PC.

Operator, `Oct 02, 2026`: *"1+2 together"* — the fix for MEXC answering
"too many requests" (code 510) once six rooms ran side by side.

Why it exists. Each room is its own runner process (`TA_PROFILE`), and each
one asked MEXC for the same things on its own, down one internet line: the
1-minute candles of every open practice trade, the last price of every coin
holding one, and every armed strategy's own candles when its bar closed. In
the 24 hours to `Oct 02, 2026 8:00am` that was **64** rate-limit refusals
(Main 4, #55D32617 6, #4FC03172 10, #B2404C0B 17, #6B08FF64 12, #CC94D9FB 15),
nearly all on PRACTICE exit checks. Six rooms asking for one coin's candles in
the same second is six answers MEXC has to give; one answer read six times is
one.

What it shares, and the one rule each obeys:

* **The price board** — `fx.last_prices()`, EVERY contract's last price in
  ONE ticker call (0.38 s), written to `prices.json` with the time the fetch
  began. A reader uses it while it is at most `BOARD_MAX_AGE_S` old; never an
  older one, because a practice exit decided on a stale price is a fill that
  did not happen.
* **Candles** — one file per (coin, bar size, count). Valid until the NEXT bar
  of that size closes after the fetch, so every reader sees exactly the closed
  bars a fetch of its own would have shown (`auto_trader._closed_bars` still
  drops the forming bar, with the reader's own clock). A fetch made in the
  first `SETTLE_S` after a close is only trusted until `SETTLE_S` has passed —
  the bar that just closed may not be final at MEXC that early.

How one process fetches for all: an exclusive lock file per board/key. The
holder re-reads (somebody may have written while it waited), fetches, writes
atomically, releases. The others wait in short steps and re-read. A lock older
than `LOCK_STALE_S` belongs to a process that was killed, and is broken — a
dead room must never stop the live ones.

What it NEVER shares, on purpose:

* **The order book** behind the cost check (`edge_check`, `fx.book_cost`) —
  every signal reads a fresh book, as before (CLAUDE.md "every cost the
  backtest charges, the gate charges").
* **Anything signed or private** — orders, positions, stops. Real exits are
  the exchange's own brackets (rule 14); nothing here is on that path.
* **The backtest's candles** — `market_sweep`, the GitHub shards and the
  downloads keep calling `fx.klines` themselves. Only the RUNNER switches this
  on (`enable()`, from `auto_trader.run_forever`); switched off, every call
  below is the plain `fx` call, byte for byte.

Every failure falls back to the direct read the runner made before: a missing,
half-written, corrupt or locked file is "no answer", never an exception and
never a wrong number. Files are small (a board is ~40 KB, a candle file
~20 KB) and live under `~/.tradingagents/shared` — the store's own drive (a
junction onto G: on the operator's PC), machine-wide, never one room's folder.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

SHARED_DIR = Path(os.path.expanduser("~/.tradingagents")) / "shared"

# The oldest board a practice exit may decide on. `fx.last_prices` keeps its
# own in-process copy for the same 3 s (`_PRICES_TTL`).
BOARD_MAX_AGE_S = 3.0
# A lock this old is a killed process's. A healthy fetch is one call (0.38 s
# for the board); MEXC's own retries can stretch it, and breaking a slow but
# live holder costs only one duplicate call, never a wrong answer.
LOCK_STALE_S = 8.0
WAIT_STEP_S = 0.05
# The bar that just closed is not trusted final until this long after its
# close (measured Oct 02, 2026 6:30am: MEXC serves a just-closed 15m bar final
# at +1 s).
SETTLE_S = 1.0
# Bar sizes the runner reads, with their length in seconds.
INTERVAL_SECONDS = {"Min1": 60, "Min5": 300, "Min15": 900, "Min30": 1800,
                    "Min60": 3600, "Hour4": 14400, "Day1": 86400}
# One request's worth. A longer history pages and disk-caches inside
# `fx.klines` and is the backtest's business, not the runner's.
MAX_SHARED_LIMIT = 2000
# Candle files nobody has rewritten for this long belong to coins no room
# trades any more.
OLD_FILE_S = 2 * 86400

_ENABLED = [False]
# After the board could not be fetched, this process asks each coin directly
# for this long instead of asking for the whole board again per coin — a
# failing board must never cost MORE calls than no board.
BOARD_RETRY_S = 3.0
_BOARD_FAILED_AT = [0.0]
_MEMO: dict = {}
_MEMO_LOCK = threading.Lock()
# What the sharing actually did, so "it shares" is a number, not a claim.
STATS = {"board_read": 0, "board_fetch": 0, "kline_read": 0,
         "kline_fetch": 0, "direct": 0}


class _NoAnswer(LookupError):
    """The shared fetch produced nothing worth keeping."""


def enable(on: bool = True) -> None:
    """Switch sharing on for THIS process. Only the runner calls it."""
    _ENABLED[0] = bool(on)
    _BOARD_FAILED_AT[0] = 0.0
    with _MEMO_LOCK:
        _MEMO.clear()
    if on:
        _sweep_old_files()


def enabled() -> bool:
    return _ENABLED[0]


# ---------------------------------------------------------------- files
def _path(name: str) -> Path:
    return SHARED_DIR / f"{name}.json"


def _lock_path(name: str) -> Path:
    return SHARED_DIR / f"{name}.lock"


def _read(path: Path):
    """The parsed file, or None — missing, mid-replace, corrupt or locked
    all mean "no answer"."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                           # noqa: BLE001
        return None


def _write(path: Path, doc: dict) -> bool:
    """Atomic replace; never a half-written file. Windows refuses a replace
    while a reader has the target open, so it is retried for a moment and
    then given up — the value was already handed to the caller."""
    tmp = path.with_name(
        f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(doc, separators=(",", ":")),
                       encoding="utf-8")
        for _ in range(20):
            try:
                os.replace(tmp, path)
                return True
            except PermissionError:
                time.sleep(0.01)
    except Exception as exc:                                    # noqa: BLE001
        logger.debug("shared write %s failed: %s", path.name, exc)
    with contextlib.suppress(Exception):
        tmp.unlink()
    return False


_BUSY = object()
_DIRECT = object()


def _try_lock(lock: Path):
    """A token when this process now holds `lock`; _BUSY when another does;
    _DIRECT when the folder cannot hold a lock at all."""
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return _DIRECT
    token = f"{os.getpid()}-{uuid.uuid4().hex}"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return _BUSY
    except PermissionError:
        # on Windows a lock being deleted at this instant answers this; a
        # folder we may not write in answers it too, with no lock there —
        # and waiting on that would stall every read for LOCK_STALE_S
        return _BUSY if lock.exists() else _DIRECT
    except OSError:
        return _DIRECT
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token)
    except OSError:
        return _DIRECT
    return token


def _unlock(lock: Path, token: str) -> None:
    """Remove the lock only while it is still OURS — a holder that was
    declared stale and replaced must not delete its successor's lock."""
    with contextlib.suppress(Exception):
        if lock.read_text(encoding="utf-8") == token:
            lock.unlink()


def _stale(lock: Path) -> bool:
    try:
        return time.time() - lock.stat().st_mtime > LOCK_STALE_S
    except FileNotFoundError:
        return False                   # gone already: just try again
    except OSError:
        return False


def _memo_get(name: str):
    with _MEMO_LOCK:
        return _MEMO.get(name)


def _memo_put(name: str, doc: dict, value) -> None:
    with _MEMO_LOCK:
        _MEMO[name] = (doc, value)


def _valid(check, doc, now) -> bool:
    try:
        return bool(doc) and bool(check(doc, now))
    except Exception:                                           # noqa: BLE001
        return False


def _shared(name: str, check, fetch, encode, decode, stat: str):
    """The value behind `name`: this process's memo, else the shared file,
    else ONE fetch for every process, else (shared files unusable) a plain
    fetch. `fetch()` raising propagates exactly as the direct call would."""
    hit = _memo_get(name)
    if hit is not None and _valid(check, hit[0], time.time()):
        return hit[1]

    def _from_file():
        doc = _read(_path(name))
        if doc is not None and _valid(check, doc, time.time()):
            try:
                value = decode(doc)
            except Exception:                                   # noqa: BLE001
                return None
            _memo_put(name, doc, value)
            STATS[f"{stat}_read"] += 1
            return (value,)
        return None

    got = _from_file()
    if got is not None:
        return got[0]
    lock = _lock_path(name)
    deadline = time.monotonic() + LOCK_STALE_S + 2.0
    while True:
        token = _try_lock(lock)
        if token is _DIRECT:
            break
        if token is not _BUSY:
            try:
                got = _from_file()          # written while we were waiting
                if got is not None:
                    return got[0]
                at = time.time()
                value = fetch()
                STATS[f"{stat}_fetch"] += 1
                try:
                    doc = encode(value, at)
                except Exception:                               # noqa: BLE001
                    doc = None
                if doc is not None:
                    _write(_path(name), doc)
                    _memo_put(name, doc, value)
                return value
            finally:
                _unlock(lock, token)
        if _stale(lock):
            # a KILLED holder never comes back to release it
            with contextlib.suppress(Exception):
                lock.unlink()
        time.sleep(WAIT_STEP_S)
        got = _from_file()
        if got is not None:
            return got[0]
        if time.monotonic() > deadline:
            break
    STATS["direct"] += 1
    return fetch()


def _sweep_old_files() -> None:
    """Candle files for coins nobody trades any more, and stray temp files.
    Our own folder only."""
    try:
        cutoff = time.time() - OLD_FILE_S
        for f in SHARED_DIR.glob("*"):
            with contextlib.suppress(Exception):
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
    except Exception:                                           # noqa: BLE001
        pass


# ---------------------------------------------------------- price board
def _board_ok(doc, now) -> bool:
    age = now - float(doc["at"])
    return 0.0 <= age <= BOARD_MAX_AGE_S and isinstance(doc["px"], dict) \
        and bool(doc["px"])


def prices(fx):
    """{symbol: last price} for every contract, at most BOARD_MAX_AGE_S
    old — or None when sharing is off or the board cannot answer."""
    if not enabled():
        return None
    board = getattr(fx, "last_prices", None)
    if board is None:
        return None
    if time.time() - _BOARD_FAILED_AT[0] < BOARD_RETRY_S:
        return None

    def fetch():
        px = board(max_age=0)
        if not px:
            raise _NoAnswer("the ticker list came back empty")
        return px

    try:
        return _shared("prices", _board_ok, fetch,
                       lambda v, at: {"at": at, "px": v},
                       lambda d: d["px"], "board")
    except Exception as exc:                                    # noqa: BLE001
        _BOARD_FAILED_AT[0] = time.time()
        logger.debug("price board unavailable: %s", exc)
        return None


def last_price(fx, symbol: str) -> float:
    """The board's price for `symbol`, or `fx.last_price(symbol)` when the
    board cannot answer for it. Raises exactly as `fx.last_price` does."""
    board = prices(fx)
    if board:
        try:
            v = float(board.get(symbol))
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            return v
    return float(fx.last_price(symbol))


# --------------------------------------------------------------- candles
def _safe(text: str) -> str:
    return "".join(c for c in text if c.isalnum() or c in "_-")


def valid_until(frame, at: float, per: int) -> float:
    """When a fetch made at `at` stops being the latest: the next close of
    this bar size — earlier if the frame's own forming bar says so, and only
    SETTLE_S after a close when the fetch was made inside that window."""
    open_now = int(at // per * per)
    until = float(open_now + per)
    if at - open_now < SETTLE_S:
        until = open_now + SETTLE_S
    if len(frame):
        last_t = int(frame["Date"].iloc[-1].timestamp())
        if last_t + per > at:
            until = min(until, float(last_t + per))
    return until


def _encode_frame(frame, at: float, per: int) -> dict:
    return {"at": at, "per": per, "until": valid_until(frame, at, per),
            "t": [int(d.timestamp()) for d in frame["Date"]],
            "o": [float(x) for x in frame["Open"]],
            "h": [float(x) for x in frame["High"]],
            "l": [float(x) for x in frame["Low"]],
            "c": [float(x) for x in frame["Close"]],
            "v": [float(x) for x in frame["Volume"]]}


def _decode_frame(doc: dict):
    """Built exactly the way `mexc_futures.klines` builds a fetched page, so
    a shared frame and a fetched one are the same frame."""
    import pandas as pd  # noqa: PLC0415

    return pd.DataFrame({
        "Date": pd.to_datetime(doc["t"], unit="s", utc=True).tz_localize(None),
        "Open": [float(x) for x in doc["o"]],
        "High": [float(x) for x in doc["h"]],
        "Low": [float(x) for x in doc["l"]],
        "Close": [float(x) for x in doc["c"]],
        "Volume": [float(x) for x in doc["v"]],
    })


def klines(fx, symbol: str, interval: str, limit: int = 300):
    """`fx.klines(symbol, interval, limit)`, fetched once for every room.

    Off (not the runner), an unknown bar size, or a paged history: the plain
    call. A venue failure raises exactly as the plain call would."""
    per = INTERVAL_SECONDS.get(interval)
    if not enabled() or per is None or int(limit) > MAX_SHARED_LIMIT:
        return fx.klines(symbol, interval, limit)
    name = "kl_" + _safe(f"{symbol}_{interval}_{int(limit)}")

    def check(doc, now):
        return (int(doc["per"]) == per and float(doc["at"]) <= now
                < float(doc["until"]))

    def fetch():
        # A copy fetched by this process before the bar closed must not be
        # filed as the fresh one: `fx.klines` keeps its own copy for up to
        # 30 s (Min1) - 300 s, which can still hold the bar as it was FORMING.
        # Each exchange forgets under ITS OWN key: Gate names a minute "1m"
        # and the old pop of `(symbol, "Min1", limit)` missed it
        # (RCA-2026-10-10-G).
        forget = getattr(fx, "forget_klines", None)
        if callable(forget):
            forget(symbol, interval, limit)
        else:
            cache = getattr(fx, "_KLINE_CACHE", None)
            if isinstance(cache, dict):
                cache.pop((symbol, interval, limit), None)
        return fx.klines(symbol, interval, limit)

    def encode(f, at):
        # A SHORT ANSWER IS KEPT TO ITSELF. MEXC answers a hammered client
        # with TRUNCATED history (the note on `auto_trader._BAR_CACHE`); one
        # room's truncated read must never become every room's bar. A young
        # coin's history only grows, so fewer bars than the file already
        # held (beyond the one or two a sliding window moves) is that.
        old = _read(_path(name))
        try:
            had = len(old["t"]) if isinstance(old, dict) else 0
        except Exception:                                       # noqa: BLE001
            had = 0
        if had and len(f) < had - 2:
            logger.info("%s %s: %d bars where the shared file held %d — "
                        "kept to this room, not shared", symbol, interval,
                        len(f), had)
            return None
        return _encode_frame(f, at, per)

    frame = _shared(name, check, fetch, encode, _decode_frame, "kline")
    return frame.copy()
