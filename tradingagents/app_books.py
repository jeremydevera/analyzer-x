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

EVERY HOUR, NOT ONCE A DAY (operator, Oct 31, 2026: "Go"). Gate's own
archive ends Oct 22, 2026 04:00 UTC, so these readings are the only
per-minute cost since, and the nightly v2 update (~05:47 UTC) used to find
today's hours unpublished. `PARTIAL_AFTER_S` past every hour the day so far
goes up as ONE bundle (`publish_partial`), cut at the hour; the finished day
still goes up coin by coin at 00:20 UTC (`publish_day`), and that is what
every reader takes once the list names the day finished.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
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
# THE BACKTEST READS THESE WHERE EVERY MACHINE CAN (harddev round 3, Oct 16,
# 2026): the nightly v2 update measures on GitHub, which cannot see this
# PC's files, so a day counts only once `publish_day` has put it on GitHub -
# or, for today, only up to the cut `publish_partial` last put there
# (`book_for(published_only=True)` here, a release download there) - one
# strategy, one result, wherever it was measured ("the analysis and the
# button run the same grid"). False switches the app's books out of every
# backtest at once (`cost_store.with_app_books`).
IN_BACKTEST = True

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


def book_for(sym: str, start_s: int, end_s: int, *,
             published_only: bool = True) -> dict:
    """Every recorded reading of `sym` in [start_s, end_s], packed in
    `cost_store`'s keys; empty when none was recorded.

    ONLY PUBLISHED DAYS (RCA-2026-10-16-A, harddev round 3): the nightly v2
    update measures on GitHub, which reads a day only once `publish_day` put
    it there, so this PC reads the same days and no others - one strategy,
    one result, wherever it was measured. Today is read up to the cut of its
    last hourly upload (`publish_partial`), on both sides. A day with no file
    here (GitHub's machines) is downloaded from its release - or, while it is
    not finished, from its hourly bundle; `published_only=False` reads this
    PC's files as they are (the recorder's own checks)."""
    import numpy as np

    from tradingagents import cost_store as cs

    got = None
    d = int(start_s) - int(start_s) % 86400
    while d <= int(end_s):
        day = _day(d)
        local = _day_file(sym, day)
        if local.exists():
            cut = None if not published_only else _cut_here(day, sym)
            part = _read(local) if not published_only or cut else None
            if part is not None and cut:
                # an hourly upload is read up to its cut and no further: the
                # minutes after it are on this disk, not on GitHub
                keep = np.asarray(part["t"], dtype="int64") < int(cut)
                part = {k: np.asarray(v)[keep] for k, v in part.items()}
        elif HOME.exists():
            part = None          # the recorder's own PC: what it did not record, nobody did
        else:
            part = _remote(day, sym)
        if part is not None and len(part["t"]):
            got = cs.merge(got, part)
        d += 86400
    if got is None:
        return cs.empty()
    got = cs.merge(None, got)              # one reading a minute, the last kept
    t = np.asarray(got["t"], dtype="int64")
    keep = (t >= int(start_s)) & (t <= int(end_s))
    return {k: np.asarray(got[k])[keep] for k in cs.KEYS}


# ------------------------------------------------------------ publishing
# WHERE GITHUB'S MACHINES READ THEM: one release per UTC day and half of the
# market (`cost_store.group`: 0-9 and A-M, N-Z), because a release holds at
# most 1,000 files and Gate lists 1,039 contracts; one compressed file per
# coin. On the origin account, public, so both accounts' machines read it.
PUBLISH_REPO = os.environ.get("APP_BOOKS_REPO", "jeremydevera/analyzer-x")
PUBLISH_AFTER_UTC_S = 20 * 60      # the recorder's last flush of a day is ~5 min past it
PUBLISH_DAYS = 61                  # as far back as the costs job keeps (BACKFILL_DAYS)
UPLOAD_BATCH = 100
UPLOAD_TRIES = 5
# THE DAY SO FAR, EVERY HOUR (operator, Oct 31, 2026: "Go"): ten minutes past
# each hour, cut at the hour. The recorder appends every FLUSH_S (5 min), so
# by :05 every minute before :00 is on disk; :10 leaves five more, and a
# coin whose file was last written earlier is cut where its file proves it
# complete (`publish_partial`). The nightly v2 update (~05:47 UTC) then reads
# through 05:00 instead of yesterday's 23:59. ONE bundle an hour - every
# coin of the day so far, ~12 MB for a whole day of 1,070 coins (measured
# Oct 31, 2026: 1,524,750 readings, 11,972,368 bytes) - in the list's own
# release: two uploads and a clean-up an hour, where 1,070 files an hour
# would be ~25,700 uploads a day on one account.
PARTIAL_AFTER_S = 10 * 60
# a bundle is kept this long after its hour: a GitHub job runs at most 6 h
# and reads the list again every INDEX_TTL_S, so none still reads it then
KEEP_PARTIAL_S = 12 * 3600
# a long-running reader asks for the list again after this long, so a newer
# hourly upload replaces the one it read (RCA-2026-10-30-C's shape: a copy
# that is never asked again is frozen)
INDEX_TTL_S = 1800
RETRY_LIST_S = 60          # a list never read is asked again this soon
# a reading reaches the recorder's memory well inside this long after its
# minute starts (asked 2.5 s in, at most WAIT_S to answer; an hourly contract
# list refresh can hold one burst back), so a file last appended at F holds
# every minute before floor(F) - PROOF_S. Under the 4 minutes between :10 and
# the last 5-minute flush before it, so a coin that is being recorded is
# never cut short of the hour.
PROOF_S = 120
_PARTIAL_RE = re.compile(r"partial-(\d{8})-(\d{2})\.npz")
# THE LIST OF PUBLISHED DAYS, one small file GitHub's machines read first:
# without it a replay reaching back to Jul 01, 2026 asked for ~110 days of
# each of ~26 coins a machine, nearly all "no such file". A day is published
# - here and there alike - only once this list names it.
INDEX_TAG = "appbook-index"
INDEX_ASSET = "days.json"
_REMOTE: dict = {}
_REMOTE_DAYS: dict = {}
_BUNDLES: dict = {}            # asset name -> ({sym: packed} | None, when asked)
_TICKED: dict = {}             # "final" / "partial" -> the UTC hour last done
_PARTIAL_FAIL: dict = {}       # the failing streak of the hourly upload
_clock = time.time


def tag(day: str, sym: str) -> str:
    from tradingagents import cost_store as cs

    return f"appbook-{day}-{cs.group(sym)}"


def asset(sym: str) -> str:
    from tradingagents import cost_store as cs

    return cs.asset(sym, "x").rsplit("-", 1)[0] + ".npz"


def url(day: str, sym: str, repo: str | None = None) -> str:
    import urllib.parse as _up

    return (f"https://github.com/{repo or PUBLISH_REPO}/releases/download/"
            f"{tag(day, sym)}/{_up.quote(asset(sym))}")


def _marker(day: str) -> Path:
    return HOME / "published" / f"{day}.json"


def _marker_of(day: str) -> dict:
    try:
        return json.loads(_marker(day).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _published(day: str) -> set:
    """The coins of a FINISHED day that went up whole (`publish_day`)."""
    return set(_marker_of(day).get("coins") or [])


def _cut_here(day: str, sym: str) -> int | None:
    """Up to which second (exclusive) this PC may read `sym`'s `day`: the
    whole day once it went up whole, the coin's cut in the day's last hourly
    upload while it has not, None while nothing of it is on GitHub. The
    marker mirrors the list GitHub's machines read (`_publish_index`), so the
    two sides read the same minutes."""
    m = _marker_of(day)
    if m.get("coins"):
        if sym not in set(m["coins"]):
            return None
        return _day_start(day) + 86400
    cut = ((m.get("partial") or {}).get("coins") or {}).get(sym)
    return int(cut) if cut else None


def _day_start(day: str) -> int:
    """`YYYYMMDD` -> its first second, UTC (no strptime: its first call in a
    thread can race the module's own import)."""
    import calendar

    return calendar.timegm((int(day[:4]), int(day[4:6]), int(day[6:8]), 0, 0, 0))


def index_url(repo: str | None = None) -> str:
    return (f"https://github.com/{repo or PUBLISH_REPO}/releases/download/"
            f"{INDEX_TAG}/{INDEX_ASSET}")


def _remote_index() -> dict:
    """The list of published days - `days` finished, `partial` {day: {asset,
    through}} the hourly bundles of days not finished - read again after
    INDEX_TTL_S, so a long-running reader moves on to a newer hourly upload.
    Nothing when the list was never read (then no day is read from GitHub at
    all); a list that cannot be read again keeps the one read before."""
    from tradingagents import cost_store as cs

    if "days" not in _REMOTE_DAYS or _clock() - _REMOTE_DAYS.get("at", 0.0) > INDEX_TTL_S:
        status, raw = cs._fetch(index_url())
        days, partial = set(), {}
        try:
            if status == 200:
                got = json.loads(raw.decode("utf-8"))
                days = set(got["days"])
                partial = {str(d): e for d, e in (got.get("partial") or {}).items()
                           if isinstance(e, dict) and e.get("asset")}
        except (ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError):
            status = 0
        first = not _REMOTE_DAYS.get("read")
        if status == 200 or first:
            _REMOTE_DAYS.update(days=days, partial=partial, read=status == 200)
        # a list that could not be read AGAIN keeps the one read before: a
        # cut wire mid-run must not take every app book out of the coins left
        _REMOTE_DAYS["at"] = _clock()
        if status != 200 and first:
            # never read at all (the second the hourly upload swaps it in, or
            # a cut wire): asked again in a minute, not after INDEX_TTL_S
            _REMOTE_DAYS["at"] -= INDEX_TTL_S - RETRY_LIST_S
    return _REMOTE_DAYS


def _remote_days() -> set:
    """The FINISHED published days, from the list."""
    return _remote_index()["days"]


def _bundle(name: str) -> dict | None:
    """An hourly bundle from the list's release, once per process: {sym:
    packed}, each coin already cut at its own `cut` (and cut again here, so a
    bundle can never hand a reader a minute past its promise). The newest
    few are kept; None when it cannot be read."""
    import io
    import urllib.parse as _up

    import numpy as np

    from tradingagents import cost_store as cs

    held = _BUNDLES.get(name)
    if held is not None and (held[0] is not None or _clock() - held[1] <= INDEX_TTL_S):
        return held[0]
    status, raw = cs._fetch(f"https://github.com/{PUBLISH_REPO}/releases/download/"
                            f"{INDEX_TAG}/{_up.quote(name)}")
    coins = None
    if status == 200 and raw:
        try:
            with np.load(io.BytesIO(raw)) as z:
                cols = cs._whole({k: z[k] for k in cs.KEYS if k in z.files})
                names = [str(s) for s in z["coins"].tolist()]
                start = z["start"].astype("int64")
                cut = z["cut"].astype("int64")
            coins = {}
            for i, sym in enumerate(names):
                a, b = int(start[i]), int(start[i + 1])
                part = {k: np.asarray(cols[k])[a:b] for k in cs.KEYS}
                keep = np.asarray(part["t"], dtype="int64") < int(cut[i])
                coins[sym] = {k: v[keep] for k, v in part.items()}
        except (OSError, ValueError, KeyError, IndexError):
            coins = None
    _BUNDLES.pop(name, None)
    while len(_BUNDLES) >= 3:
        _BUNDLES.pop(next(iter(_BUNDLES)))
    # one that could not be read is asked again after INDEX_TTL_S, never on
    # every coin (a cut wire is four tries and ~18 s each)
    _BUNDLES[name] = (coins, _clock())
    return coins


def _remote(day: str, sym: str) -> dict | None:
    """A published coin-day from its release, once per process; None when it
    was never published (404) or cannot be read - the record answers then.
    Only a day the published list names is asked for: a finished day from its
    coin's own file, a day not finished yet from its newest hourly bundle."""
    from tradingagents import cost_store as cs

    idx = _remote_index()
    if day not in idx["days"]:
        entry = idx["partial"].get(day)
        if not entry:
            return None
        return (_bundle(str(entry["asset"])) or {}).get(sym)
    key = (day, sym)
    if key not in _REMOTE:
        status, raw = cs._fetch(url(day, sym))
        try:
            _REMOTE[key] = cs.from_bytes(raw) if status == 200 and raw else None
        except (OSError, ValueError, KeyError):
            _REMOTE[key] = None
    return _REMOTE[key]


_GH_ENV: dict = {}


def _gh_env() -> dict:
    """The environment `gh` runs in: the publishing repo's OWNER's login when
    this PC holds it (`gh auth token --user`), so the uploads never depend on
    which account happens to be active (Oct 16, 2026: jeremydvera active,
    jeremydevera owns the repo); else the active login, as before."""
    import subprocess

    if "env" not in _GH_ENV:
        env = dict(os.environ)
        owner = PUBLISH_REPO.split("/", 1)[0]
        with contextlib.suppress(Exception):
            r = subprocess.run(["gh", "auth", "token", "--user", owner],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and r.stdout.strip():
                env["GH_TOKEN"] = r.stdout.strip()
        _GH_ENV["env"] = env
    return _GH_ENV["env"]


def _gh(*args: str):
    import subprocess

    return subprocess.run(["gh", *args], capture_output=True, text=True,
                          env=_gh_env())


def _upload(tag_: str, files: list, *, quiet: bool = False) -> bool:
    """`files` into release `tag_`, creating it the first time; a refusal
    for the rate limit waits, never loses the files. `quiet`: the caller
    says a failure itself (the hourly upload, once per failing streak); the
    reason is kept in `_LAST_UPLOAD_ERROR` either way."""
    r = None
    for attempt in range(UPLOAD_TRIES):
        r = _gh("release", "upload", tag_, *[str(f) for f in files], "--clobber",
                "-R", PUBLISH_REPO)
        if r.returncode == 0:
            return True
        said = (r.stderr + r.stdout).lower()
        if "rate limit" in said:
            time.sleep(min(60 * 2 ** attempt, 600))
            continue
        if "not found" in said:
            _gh("release", "create", tag_, "-R", PUBLISH_REPO, "--title", tag_,
                "--latest=false", "--notes",
                "The order book the app can trade, recorded every minute 3 s in "
                "(tradingagents/app_books.py). One file per coin for one UTC day.")
        time.sleep(2 + 3 * attempt)
    _LAST_UPLOAD_ERROR["text"] = (r.stderr if r else "").strip()[:200]
    if not quiet:
        logger.warning("could not upload %d file(s) to %s: %s", len(files), tag_,
                       _LAST_UPLOAD_ERROR["text"])
    return False


_LAST_UPLOAD_ERROR: dict = {"text": ""}


def publish_day(day: str, only: set | None = None) -> dict:
    """One finished UTC day of every coin this PC recorded (or of `only`),
    to GitHub. The marker lists the coins that really went up and the ones
    that failed; a failed coin stays out of `coins`, so neither this PC nor
    GitHub reads it, and the next tick tries it again."""
    from tradingagents import cost_store as cs

    out = HOME / "outbox" / day
    out.mkdir(parents=True, exist_ok=True)
    by_tag: dict = {}
    for folder in sorted(p for p in HOME.iterdir() if p.is_dir()):
        f = folder / f"{day}.bin"
        if not f.exists() or folder.name in ("published", "outbox"):
            continue
        sym = _sym_of_folder(folder.name)
        if only is not None and sym not in only:
            continue
        packed = _read(f)
        if packed is None:
            continue
        packed = cs.merge(None, packed)
        target = out / asset(sym)
        target.write_bytes(cs.to_bytes(packed))
        by_tag.setdefault(tag(day, sym), []).append((sym, target))
    done, failed = [], []
    for tag_, items in sorted(by_tag.items()):
        for i in range(0, len(items), UPLOAD_BATCH):
            part = items[i:i + UPLOAD_BATCH]
            if _upload(tag_, [p for _s, p in part]):
                done += [s for s, _p in part]
            else:
                failed += [s for s, _p in part]
    coins = _published(day) | set(done)
    listed = bool(coins) and _publish_index(out, extra={day})
    for p in out.iterdir():
        with contextlib.suppress(OSError):
            p.unlink()
    with contextlib.suppress(OSError):
        out.rmdir()
    # THE MARKER LAST, and only once the list names the day: a day this PC
    # reads is a day GitHub reads, never one it cannot find
    if listed:
        _write_marker(day, coins=coins, failed=set(failed) - coins)
        return {"day": day, "coins": len(done), "failed": failed}
    if coins:
        # the files went up, the list did not: no marker, so the next tick
        # sends the whole day again (harmless: --clobber)
        logger.warning("%s: %d coins went up but the list of published days "
                       "did not - tried again next time", day, len(coins))
        return {"day": day, "coins": 0, "failed": sorted(coins | set(failed)),
                "why": "the list of published days did not go up"}
    if failed:
        # every coin refused: the day is not finished anywhere, so the hourly
        # upload GitHub's list still names stays what this PC reads as well
        _write_marker(day, coins=set(), failed=set(failed),
                      partial=_marker_of(day).get("partial"))
    return {"day": day, "coins": 0, "failed": failed}


def _write_marker(day: str, *, coins: set, failed: set,
                  partial: dict | None = None) -> None:
    """What this PC may read of `day`, written only once GitHub's list says
    the same: `coins` went up whole (the day is finished for them), else
    `partial` - the newest hourly upload, {asset, through, coins: {sym:
    cut}}. Swapped in whole: the readers parse it on every read."""
    m = _marker(day)
    m.parent.mkdir(parents=True, exist_ok=True)
    body = {"coins": sorted(coins), "failed": sorted(failed), "at": time.time()}
    if partial and not coins:
        body["partial"] = partial
    tmp = m.with_name(f"{m.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(body), encoding="utf-8")
    # Windows refuses a swap while a reader has the file open: retried for
    # 3 s, then written in place - a marker left behind GitHub's list would
    # make this PC read another cut than GitHub for an hour
    for _ in range(30):
        try:
            os.replace(tmp, m)
            return
        except PermissionError:
            time.sleep(0.1)
    m.write_text(json.dumps(body), encoding="utf-8")
    with contextlib.suppress(OSError):
        tmp.unlink()


def _index_partials(*, finished: set, extra: dict | None = None) -> dict:
    """{day: {asset, through}} for every day read from its newest hourly
    bundle, i.e. not finished: the markers', then `extra`."""
    folder = HOME / "published"
    known = {q.stem for q in folder.glob("*.json")} if folder.exists() else set()
    out = {}
    for d in sorted(known):
        p = _marker_of(d).get("partial") or {}
        if p.get("asset") and d not in finished:
            out[d] = {"asset": p["asset"], "through": p.get("through")}
    for d, e in (extra or {}).items():
        if d not in finished:
            out[d] = {"asset": e["asset"], "through": e.get("through")}
    return out


def _publish_index(out: Path, *, extra: set = frozenset(),
                   partial: dict | None = None, quiet: bool = False) -> bool:
    """Every finished day (the markers) plus `extra`, and every day not
    finished with its newest hourly bundle (plus `partial`), as the one list
    GitHub's machines read first."""
    folder = HOME / "published"
    known = {q.stem for q in folder.glob("*.json")} if folder.exists() else set()
    days = sorted({d for d in known if _published(d)} | set(extra))
    part = _index_partials(finished=set(days), extra=partial)
    f = out / INDEX_ASSET
    f.write_text(json.dumps({"days": days, "partial": part, "at": time.time()}),
                 encoding="utf-8")
    return _upload(INDEX_TAG, [f], quiet=quiet)


def _bundle_bytes(parts: list) -> bytes:
    """[(sym, cut, packed), ...] -> one compressed file: every coin's
    columns end to end, `coins`, `start` (each coin's first row, then the
    end) and `cut` (each coin's promise: no reading at or after it)."""
    import io

    import numpy as np

    from tradingagents import cost_store as cs

    cols = {k: np.concatenate([np.asarray(p[k]) for _s, _c, p in parts])
            for k in cs.KEYS}
    start = np.cumsum([0] + [len(p["t"]) for _s, _c, p in parts]).astype("int64")
    buf = io.BytesIO()
    np.savez_compressed(buf, coins=np.array([s for s, _c, _p in parts]),
                        start=start,
                        cut=np.array([c for _s, c, _p in parts], dtype="int64"),
                        **cols)
    return buf.getvalue()


def publish_partial(now: float | None = None) -> dict:
    """TODAY SO FAR, as one bundle: every coin's readings before the hour
    (`now` floored), in `partial-<day>-<HH>.npz` in the list's own release,
    then the list naming it, then this PC's marker - the order a finished day
    goes up in, so this PC never reads a cut GitHub's list does not name.

    A coin whose file was last appended before the hour (its feed stopped,
    or a flush failed) is cut where the file proves it complete - the minute
    before the minute of its last write - never promised further. A failed
    upload is tried again at the next hour; a failing streak is said once,
    and once more when it ends."""
    import numpy as np

    from tradingagents import cost_store as cs
    from tradingagents.positions_view import fmt_when

    now = time.time() if now is None else float(now)
    day = _day(now)
    start = int(now) - int(now) % 86400
    cut = int(now) - int(now) % 3600
    out = {"day": day, "through": cut, "coins": 0}
    if cut <= start:
        return {**out, "why": "no hour of today has finished yet"}
    if _published(day):
        return {**out, "why": "the day already went up whole"}
    if ((_marker_of(day).get("partial") or {}).get("through")) == cut:
        # a restart inside the hour: never the same name up twice (a reader
        # asking for it between the delete and the upload would get nothing)
        return {**out, "why": "this hour already went up"}
    parts = []
    folders = sorted(p for p in HOME.iterdir() if p.is_dir()) if HOME.exists() else []
    for folder in folders:
        if folder.name in ("published", "outbox"):
            continue
        f = folder / f"{day}.bin"
        try:
            flushed = int(f.stat().st_mtime)
        except OSError:
            continue
        c = min(cut, flushed - flushed % 60 - PROOF_S)
        if c <= start:
            continue
        packed = _read(f)
        if packed is None:
            continue
        packed = cs.merge(None, packed)
        keep = np.asarray(packed["t"], dtype="int64") < c
        if not keep.any():
            continue
        parts.append((_sym_of_folder(folder.name), c,
                      {k: np.asarray(packed[k])[keep] for k in cs.KEYS}))
    if not parts:
        return {**out, "why": "no reading before the cut"}
    name = f"partial-{day}-{(cut - start) // 3600:02d}.npz"
    box = HOME / "outbox" / f"partial-{day}"
    box.mkdir(parents=True, exist_ok=True)
    entry = {"asset": name, "through": cut}
    try:
        target = box / name
        target.write_bytes(_bundle_bytes(parts))
        size = target.stat().st_size
        if not _upload(INDEX_TAG, [target], quiet=True):
            return _partial_failed(out, "the bundle did not go up", now)
        if not _publish_index(box, partial={day: entry}, quiet=True):
            return _partial_failed(out, "the list of published days did not go up", now)
    finally:
        for p in list(box.iterdir()):
            with contextlib.suppress(OSError):
                p.unlink()
        with contextlib.suppress(OSError):
            box.rmdir()
    _write_marker(day, coins=set(), failed=set(),
                  partial={**entry, "coins": {s: c for s, c, _p in parts}})
    if _PARTIAL_FAIL.get("hours"):
        logger.info("the order books so far today went up again after %d failed "
                    "hour(s)", _PARTIAL_FAIL["hours"])
    _PARTIAL_FAIL.clear()
    logger.info("%s so far: %d coins up to %s (%.1f MB), read here and on GitHub",
                day, len(parts), fmt_when(cut), size / 1e6)
    try:
        _prune_partials(cut, keep={e["asset"] for e in
                                   _index_partials(finished=set()).values()})
    except Exception as exc:                                   # noqa: BLE001
        logger.debug("old hourly bundles not cleaned (%s) - next hour", exc)
    return {**out, "coins": len(parts), "bytes": size, "asset": name}


def _partial_failed(out: dict, why: str, now: float) -> dict:
    """One line for a failing streak, never one an hour: the count goes on
    in `_PARTIAL_FAIL` and is said when the upload goes up again."""
    if not _PARTIAL_FAIL.get("hours"):
        logger.warning("the order books so far today did not go up: %s (%s) - "
                       "tried again every hour, said again only once it goes up",
                       why, _LAST_UPLOAD_ERROR.get("text") or "no reason given")
    _PARTIAL_FAIL["hours"] = int(_PARTIAL_FAIL.get("hours") or 0) + 1
    _PARTIAL_FAIL.setdefault("since", now)
    return {**out, "why": why}


def _prune_partials(cut: int, *, keep: set) -> int:
    """Remove hourly bundles more than KEEP_PARTIAL_S older than `cut`, never
    one the list names; a removal that fails is tried at the next hour."""
    r = _gh("release", "view", INDEX_TAG, "-R", PUBLISH_REPO, "--json", "assets")
    if r.returncode != 0:
        return 0
    gone = 0
    for a in (json.loads(r.stdout or "{}").get("assets") or []):
        name = str(a.get("name") or "")
        m = _PARTIAL_RE.fullmatch(name)
        if not m or name in keep:
            continue
        if cut - (_day_start(m[1]) + int(m[2]) * 3600) > KEEP_PARTIAL_S:
            rr = _gh("release", "delete-asset", INDEX_TAG, name, "-y",
                     "-R", PUBLISH_REPO)
            gone += rr.returncode == 0
    return gone


def _sym_of_folder(name: str) -> str:
    """A folder's coin: the plain name back to Gate's own (`x` + hex)."""
    if name.startswith("x") and "_" not in name:
        with contextlib.suppress(ValueError):
            return bytes.fromhex(name[1:]).decode("utf-8")
    return name


def _days_here() -> set:
    days = set()
    if not HOME.exists():
        return days
    for folder in HOME.iterdir():
        if folder.is_dir() and folder.name not in ("published", "outbox"):
            days.update(p.stem for p in folder.glob("*.bin"))
    return days


def publish_tick(now: float | None = None) -> dict:
    """Two jobs, each at most once a UTC hour. From `PUBLISH_AFTER_UTC_S`
    past midnight: every finished day of the last `PUBLISH_DAYS` that holds
    readings here and has not gone up whole, oldest first (a PC that was off
    catches up). From `PARTIAL_AFTER_S` past every hour: today so far
    (`publish_partial`). Runs in the API's supervisor, on its own thread;
    never under pytest."""
    from tradingagents import venue

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"published": [], "partial": None, "why": "never under pytest"}
    if venue.current() != "gate":
        return {"published": [], "partial": None, "why": "the app trades MEXC"}
    now = time.time() if now is None else float(now)
    hour = int(now) // 3600
    got, partial, did = [], None, False
    # the supervisor asks every 30 s; walking ~1,000 coin folders that often
    # would churn the store's disk for nothing, so once an hour each
    if int(now) % 86400 >= PUBLISH_AFTER_UTC_S and _TICKED.get("final") != hour:
        _TICKED["final"] = hour
        did = True
        today = _day(now)
        oldest = _day(now - PUBLISH_DAYS * 86400)
        want = sorted(d for d in _days_here()
                      if oldest <= d < today
                      and (not _published(d) or _marker_of(d).get("failed")))
        for d in want:
            try:
                # a day that went up whole sends only the coins that failed;
                # one with only an hourly upload (or nothing) sends every coin
                left = ((set(_marker_of(d).get("failed") or []) or None)
                        if _published(d) else None)
                got.append(publish_day(d, only=left))
            except Exception as exc:                           # noqa: BLE001
                logger.error("could not publish %s (%s)", d, exc)
                got.append({"day": d, "coins": 0, "failed": [], "error": str(exc)})
        if got:
            logger.info("published %s", "; ".join(f"{g['day']}: {g['coins']} coins"
                                                  + (f", {len(g['failed'])} failed"
                                                     if g.get("failed") else "")
                                                  for g in got))
    if int(now) % 3600 >= PARTIAL_AFTER_S and _TICKED.get("partial") != hour:
        _TICKED["partial"] = hour
        did = True
        try:
            partial = publish_partial(now)
        except Exception as exc:                               # noqa: BLE001
            partial = _partial_failed({"day": _day(now), "coins": 0},
                                      f"{type(exc).__name__}: {exc}", now)
    if not did:
        why = ("waiting for the last minutes of yesterday"
               if int(now) % 86400 < PUBLISH_AFTER_UTC_S else "already looked this hour")
        return {"published": [], "partial": None, "why": why}
    return {"published": got, "partial": partial}


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
