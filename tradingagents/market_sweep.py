"""The Back Test module: a market-wide sweep that resumes instead of restarting.

The first run is expensive — every contract, both short timeframes, every entry
rule, the whole barrier grid. Running it again a day later should not repeat it,
and this module is why it doesn't:

* **candles are cached on disk** and only the bars after the last cached one are
  fetched from MEXC;
* **each combination's backtest is CONTINUED**, not re-run, using the tail state
  the engine hands back (`backtest_strategy(..., resume=state)`), so a refresh
  tests the new bars only.

A day of new 15m bars is 96 candles against 34,600 already tested, so a refresh
is ~360x less work than the first run. Verified exact: continuing a split run
reproduces the single-pass result trade-for-trade, including funding.

Layout under ``~/.tradingagents/backtest/``::

    candles/PI_USDT-15m.json      cached bars, appended
    state/PI-15m.json             per-combination resume state
    rows.jsonl                    the current grid
    manifest.json                 what ran, when, and how far
"""
from __future__ import annotations

import contextlib
import itertools
import json
import os
import re
import time
from collections.abc import Sequence
from pathlib import Path

from tradingagents import portable

# TRADINGAGENTS_SWEEP_HOME lets a second sweep run against its OWN cache and
# results, so two sessions on one Mac cannot overwrite each other's per-pair
# state files (those writes are not atomic — a shared run risks a corrupt
# state.json rather than merely a stale one). Unset, the default is unchanged.
HOME = Path(os.path.expanduser(
    os.environ.get("TRADINGAGENTS_SWEEP_HOME")
    or "~/.tradingagents/backtest"))
# Candles are IMMUTABLE once their bar closes, so an isolated run shares the
# downloaded set rather than re-fetching 4,900 pairs from MEXC — isolation is
# wanted for results and per-pair state, not for a read-only cache. Override
# separately only if a run really must have its own copy.
CANDLES = Path(os.path.expanduser(
    os.environ.get("TRADINGAGENTS_CANDLES")
    or "~/.tradingagents/backtest/candles"))
STATES = HOME / "state"
ROWS = HOME / "rows.jsonl"
MANIFEST = HOME / "manifest.json"

# The fewest trades a combination needs before its row is worth keeping — PER
# TIMEFRAME, because 100 is arithmetically impossible on a daily bar. A flat 100
# deleted the whole 1d timeframe from the 2026-08-26 sweep: every one of the 739
# 1d row files was `[]` while the state files held the work (SPX500-1d: 10,692
# measured combinations, best 11 trades, median 3), so ~10.6 million measured
# combinations were computed and dropped, and the run reported five timeframes
# while the grid held two. This is a floor on EVIDENCE, not a judgement: the row
# carries its own trades/days and the reader filters in the artifact (rule 20).
MIN_TRADES = 100          # the intraday floor; see min_trades()
MIN_TRADES_BY_TF = {"15m": 100, "30m": 100, "1h": 100, "4h": 40, "1d": 10}

# Those numbers are a RATE, tuned against a YEAR of bars. Read as an absolute
# count they delete the same thing the flat 100 deleted from 1d, one dimension
# over: the 60-day 1h/4h sweep of 2026-08-26 finished with 9,439,792 rows and
# only 58 of its 105 signals, because 100 trades in 60 days at 1h is one every
# 14 hours. Gone were 26 of the 30 confluence rules the operator had just asked
# for -- a confluence rule is SELECTIVE by construction -- plus 21 older ones.
# So the floor scales with the days actually measured, and never drops below
# MIN_TRADES_ABS, which is the "a handful of trades is not evidence" line 1d
# has always used.
MIN_TRADES_ABS = 10
DAYS_PER_YEAR = 365


def min_trades(tf: str, days: int | float | None = None) -> int:
    """The fewest trades a row needs to be kept, for a window of `days`.

    Without `days` the caller gets the per-timeframe rate unchanged, so no
    existing path silently loosens.
    """
    floor = MIN_TRADES_BY_TF.get(tf, MIN_TRADES)
    if not days or days <= 0:
        return floor
    scaled = round(floor * float(days) / DAYS_PER_YEAR)
    return max(MIN_TRADES_ABS, min(floor, scaled))

GATE_BLOCK = 0.50         # cost >= half the target: the trade cannot win
CONTEXT_BARS = 300        # lookback a signal needs before the first new bar


def fmt_stamp(ts: float | None = None) -> str:
    """The operator's one date format (2026-08-21): Aug 26, 2026 4:00PM.

    DELEGATES rather than reimplements. This was a second copy of the same
    six lines, and two copies of one rule is one rule waiting to drift.
    """
    from tradingagents.positions_view import fmt_when

    return fmt_when(time.time() if ts is None else ts)


def _paths() -> None:
    for d in (HOME, CANDLES, STATES):
        d.mkdir(parents=True, exist_ok=True)


def load_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text())
    except (OSError, ValueError):
        return {}


def save_manifest(m: dict) -> None:
    _paths()
    MANIFEST.write_text(json.dumps(m, indent=2))


# ---------------------------------------------------------------- candles
def save_candles_cache(symbol: str, tf: str, df) -> None:
    """Write the sweep's working copy of a pair's bars.

    ONE writer, because the reader below has to know the layout. `v` was
    missing until 2026-08-27: the cache stored t/o/h/l/c, so every pair served
    from it handed the signals volume=None, and the module contract makes a
    rule with a missing stream ABSTAIN. Seventeen volume rules could therefore
    never produce a row -- cf_donch and cf_maobv had none at all in a
    22,478,876-row sweep, and cf_emarsi had rows only for the pairs that
    happened to be fetched fresh.
    """
    # ATOMIC. A plain write_text leaves a HALF FILE when the process dies
    # mid-write, and on Windows that half is usually NUL bytes: the size is
    # allocated before the data reaches the disk. ENPHSTOCK_USDT-1d.json was
    # 597 bytes of NULs on Sep 03, 2026 — every download and every retry of
    # that pair raised "Expecting value: line 1 column 1 (char 0)" from the
    # CACHE READER, never from the venue (which serves the pair fine), so the
    # pair could not be repaired by any button. start.py kills detached jobs
    # with taskkill /T, so mid-write deaths are routine here.
    text = json.dumps({
        "t": [int(x) for x in df["Date"].to_numpy()
              .astype("datetime64[ms]").astype("int64")],
        "o": [float(x) for x in df["Open"]],
        "h": [float(x) for x in df["High"]],
        "l": [float(x) for x in df["Low"]],
        "c": [float(x) for x in df["Close"]],
        "v": ([float(x) for x in df["Volume"]]
              if "Volume" in df.columns else None)}, separators=(",", ":"))
    final = CANDLES / f"{symbol}-{tf}.json"
    tmp = final.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())        # the bytes, not just the size
    os.replace(tmp, final)


def cached_candles(symbol: str, tf: str):
    """Whatever bars are on disk for this contract, as a DataFrame or None.

    Volume comes from the cache when it is there, and otherwise from the
    PARQUET copy of the same bars, joined on Date. The 4,985 cache files
    written before volume was stored are usable immediately that way -- the
    parquet store has always kept it (BTC_USDT-1h: 9,479 bars, every one
    non-zero), so no pair has to be downloaded again.
    """
    import pandas as pd

    f = CANDLES / f"{symbol}-{tf}.json"
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text())
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        # A cache file that will not parse is NO CACHE — never an error that
        # travels up as the pair's answer. ENPHSTOCK_USDT 1d was 597 NUL bytes
        # after a job was killed mid-write, and because this raised, the
        # failure was reported as the DOWNLOAD's ("Expecting value: line 1
        # column 1 (char 0)"), retried three times against a venue that was
        # answering perfectly, and left on the lost list where no button could
        # clear it. Quarantined, so the bad bytes are kept to look at once and
        # can never be read as bars, and the caller re-downloads in full.
        bad = f.with_suffix(".json.corrupt")
        try:
            os.replace(f, bad)
        except OSError:
            pass
        print(f"[candles] {symbol} {tf}: the cache file was unreadable "
              f"({type(exc).__name__}: {str(exc)[:60]}) — moved to "
              f"{bad.name} and the pair will be downloaded in full",
              flush=True)
        return None
    df = pd.DataFrame({"Date": pd.to_datetime(d["t"], unit="ms"),
                       "Open": d["o"], "High": d["h"], "Low": d["l"],
                       "Close": d["c"]})
    if d.get("v"):
        df["Volume"] = [float(x) for x in d["v"]]
        return df
    try:
        from tradingagents import parquet_store as pqs

        other = pqs.load_candles(symbol, tf)
        if other is not None and "Volume" in other.columns and len(other):
            # joined on the bar's own timestamp, never pasted by position: a
            # parquet copy holding a longer history would otherwise land its
            # volume on the wrong bars
            vol = dict(zip(other["Date"], other["Volume"]))
            got = [vol.get(t) for t in df["Date"]]
            if all(v is not None for v in got):
                df["Volume"] = [float(v) for v in got]
    except Exception:
        pass                     # no volume anywhere: the rules abstain, loudly
    return df


def refresh_candles(symbol: str, tf: str, *, days: int = 365):
    """Bring the cache up to date and report what was actually fetched.

    Returns ``(df, added, source)`` where ``source`` is ``"fetch"`` on a first
    run and ``"delta"`` when only the new tail was pulled.
    """
    import pandas as pd

    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br
    from tradingagents.dataflows import mexc_futures as fx

    _paths()
    iv, bs, cap = br.TFS[tf]
    have = cached_candles(symbol, tf)
    # A cached frame with no VOLUME makes every volume rule abstain (17 of them,
    # 2026-08-27), and the tail of a delta fetch cannot repair the old bars. So
    # a pair whose cache predates volume is fetched in full ONCE: the venue
    # sends volume with the candles, save_candles_cache stores it, and every run
    # after this one reads it from disk.
    if have is not None and "Volume" not in have.columns:
        have = None
    if have is None or len(have) < 100:
        raw = at._closed_bars(fx.klines(symbol, iv, cap), bs)
        df, added, source = raw, len(raw), "fetch"
    else:
        last = have["Date"].iloc[-1]
        # how many bars could have printed since the last cached one, plus a
        # small overlap so a partially-formed bar is replaced rather than
        # duplicated
        gap = int((pd.Timestamp.utcnow().tz_localize(None) - last)
                  .total_seconds() // bs) + 5
        if gap <= 1:
            return have, 0, "cache"
        fresh = at._closed_bars(fx.klines(symbol, iv, min(cap, max(300, gap))),
                                bs)
        df = (pd.concat([have, fresh])
              .drop_duplicates(subset="Date", keep="last")
              .sort_values("Date").reset_index(drop=True))
        added = len(df) - len(have)
        source = "delta"
    cut = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=days + 30)
    df = df[df["Date"] >= cut].reset_index(drop=True)
    save_candles_cache(symbol, tf, df)
    return df, added, source


# ------------------------------------------------------------------ state


@contextlib.contextmanager
def _pair_lock(coin: str, tf: str):
    """Exclusive lock for one (coin, timeframe)'s files.

    BACKTEST and UPDATE can run at the same moment; both read-modify-write the
    same rows/state files, and without this the loser's writes vanish. flock
    is advisory but every writer in this module takes it, and it works across
    processes — the detached sweep and the Streamlit script included.
    """
    LOCKS = HOME / "locks"
    LOCKS.mkdir(parents=True, exist_ok=True)
    f = (LOCKS / f"{coin}-{tf}.lock").open("w")
    try:
        portable.lock_exclusive(f)
        yield
    finally:
        portable.unlock(f)
        f.close()


def _state_file(coin: str, tf: str) -> Path:
    return STATES / f"{coin}-{tf}.json"


def load_states(coin: str, tf: str) -> dict:
    f = _state_file(coin, tf)
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return {}


def save_states(coin: str, tf: str, states: dict) -> None:
    _paths()
    with _pair_lock(coin, tf):
        tmp = _state_file(coin, tf).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(states, separators=(",", ":")))
        tmp.replace(_state_file(coin, tf))


def pair_watermark(coin: str, tf: str) -> int:
    """The last candle a pair was measured through, or 0 if it never finished.

    Reads the TAIL of the state file, not the whole thing. `save_states` writes
    `__last_ms__` last, so 256 bytes answers it; the alternative is parsing
    25 GB of JSON, which is how a "how complete is the sweep?" check timed out
    at five minutes on 2026-08-23. Falls back to a full parse if the tail does
    not look the way it should, so a format change degrades to slow rather
    than to wrong.
    """
    f = _state_file(coin, tf)
    try:
        size = f.stat().st_size
        with f.open("rb") as fh:
            fh.seek(max(0, size - 256))
            tail = fh.read().decode("utf-8", "replace")
    except OSError:
        return 0
    m = re.search(r'"__last_ms__":\s*(\d+)\s*}\s*$', tail)
    if m:
        return int(m.group(1))
    if '"__last_ms__"' not in tail:      # not near the end: parse properly
        try:
            return int(json.loads(f.read_text()).get("__last_ms__") or 0)
        except (OSError, ValueError):
            return 0
    return 0


def completed_pairs(pairs) -> set:
    """Which of these (symbol, tf) pairs have already been measured through."""
    out = set()
    for sym, tf in pairs:
        if pair_watermark(sym.replace("_USDT", ""), tf) > 0:
            out.add((sym, tf))
    return out


def combo_key(signal: str, th: float, sl: float, tp: float,
              sizing: str) -> str:
    return f"{signal}|{th:g}|{sl:g}|{tp:g}|{sizing}"


def signals_in(states: dict) -> set:
    """Which signals a state file has measured, read from its own keys.

    Every measured combination is a key -- ``signal|th|sl|tp|sizing`` -- so the
    set is recoverable exactly, including signals whose rows the trade floor
    dropped. That matters when ADDING rules to a pair whose state predates
    ``__signals__`` (2026-08-27): the first merged pair wrote
    ``__signals__: 15`` beside 17,592 rows from 80 other signals, which would
    have sent the next pass back to re-measure all of it.
    """
    return {k.split("|", 1)[0] for k in states if not k.startswith("__")}


# ------------------------------------------------------------- worker slots
# A parallel run puts one PAIR on each core. A child process cannot call back
# into the parent, so each worker publishes its own progress to its own small
# file and anyone — the job, the API, the UI — reads them. One file per slot,
# so a crashed worker leaves its last state behind instead of a hole.
WORKERS = HOME / "workers"


def worker_write(slot: int | None = None, **fields) -> None:
    """Publish one worker's progress. Never raises: it is only telemetry.

    Keyed by the WORKER'S OWN PID, not by a slot number. The slot used to be
    the task's index (`i % n_workers`), which is a label on the work, not an
    identity: when a task finished, its file sat there reading "done" while
    the operator watched what looked like an idle core, and two in-flight
    tasks that happened to share an index overwrote each other's bar
    (2026-08-22 — "why is core 3 and 4 not working?", while all seven were).
    """
    try:
        WORKERS.mkdir(parents=True, exist_ok=True)
        pid = os.getpid()
        f = WORKERS / f"w{pid}.json"
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"pid": pid, "slot": slot,
                                   "updated": time.time(), **fields},
                                  separators=(",", ":")))
        tmp.replace(f)
    except Exception:
        pass


# A worker publishes every couple of seconds; past this it is not working.
WORKER_STALE_SECONDS = 30


def worker_read(stale_seconds: float = WORKER_STALE_SECONDS) -> list:
    """Every LIVING worker's last published state.

    A file whose process is gone, or that has not been written for
    `stale_seconds`, is dropped and deleted: showing a finished task's last
    line as if a core were stuck on it is what made seven busy cores look
    like five.
    """
    out, now = [], time.time()
    try:
        files = sorted(WORKERS.glob("w*.json"))
    except Exception:
        return []
    for f in files:
        try:
            row = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        pid = int(row.get("pid") or 0)
        # No pid means a worker from a run that started before this scheme
        # existed. FRESHNESS still governs it — which is the half that fixes
        # the reported bug — so a live run keeps its panel and a finished
        # task's line still disappears.
        alive = True
        if pid:
            alive = portable.pid_alive(pid)
        fresh = (now - float(row.get("updated") or 0)) <= stale_seconds
        if alive and fresh:
            out.append(row)
        elif not alive:
            # Hide a quiet line, but only DELETE one whose process is gone. A
            # living worker can be slow between publishes — few combinations
            # on a pair, or a long fetch — and unlinking its file made seven
            # busy cores render as four (2026-08-22): each deletion also cost
            # the row until that worker published again.
            with contextlib.suppress(OSError):
                f.unlink(missing_ok=True)
    out.sort(key=lambda r: r.get("pid", 0))
    for i, row in enumerate(out):          # a stable display index per core
        row["core"] = i
    return out


def worker_clear() -> None:
    """Wipe the slots before a run, so last run's cores are not shown as busy."""
    try:
        for f in WORKERS.glob("w*.json"):
            f.unlink(missing_ok=True)
    except Exception:
        pass


# How many combinations between checkpoints. A pair is roughly 2,000 of them,
# so 200 caps the loss from a crash at a twentieth of the pair while adding one
# small atomic write per 200 backtests.
CHECKPOINT_EVERY = 200

# ...and never more often than this, in seconds. The count was sized for a Mac
# SSD, where 200 combinations is about a second of work. On the PC on
# Aug 26, 2026 the data home sat on a spinning HDD: eleven workers each
# rewrote a 5.8 MB state file plus the rows file every 200 combinations (~89
# times per pair), the disk ran at 502% busy, and the workers spent their
# time blocked in those writes -- a pair that took ~90 s in the afternoon took
# ~23 minutes. A crash still costs at most this many seconds of work; a slow
# disk gets a breath between writes instead of a queue of them. 0 restores the
# pure count.
CHECKPOINT_MIN_S = 30.0
_clock = time.monotonic


def checkpoint_due(last_at: float, now: float | None = None) -> bool:
    """Has CHECKPOINT_MIN_S passed since the last checkpoint was written?"""
    return ((_clock() if now is None else now) - last_at) >= CHECKPOINT_MIN_S


# Telemetry is CHEAP (a ~130 byte file); a checkpoint is EXPENSIVE (it rewrites
# the pair's whole row file, which reaches 17 MB). Tying the progress display to
# the checkpoint made both wrong: seven workers each rewriting megabytes every
# 200 combinations, and a percentage that sat still for 30 seconds so the
# operator could not tell the machine was working. Publish often, checkpoint
# rarely.
PUBLISH_EVERY = 20

# The hand-off flag, read by the WORKERS.
#
# It used to be checked only when a whole PAIR finished, which is the natural
# place — a pair is the unit of work. But a 15m pair is 34,000 bars by 17,820
# combinations, and on 2026-08-25 nothing completed for EIGHT HOURS on a loaded
# machine, so the request was never seen and the screen sat on "finishing the
# current pairs, then handing over" the whole time.
#
# So the workers look too, at the checkpoint they already write. "Finish the
# current task" becomes finish the current CHECKPOINT rather than the current
# pair: no measured combination is lost, and the sweep stands down in seconds
# instead of hours.
HANDOFF_PATH = Path.home() / ".tradingagents" / "db_backtest.HANDOFF"
_HANDOFF_EVERY = 200          # combinations between checks; a stat is cheap
                              # but not free, and 200 is ~1 second of work


def handoff_pending() -> bool:
    try:
        return HANDOFF_PATH.exists()
    except OSError:
        return False


def be_polite() -> int:
    """Run this worker at low OS priority.

    Measured 2026-08-22 during a 3,960-pair sweep: CPU itself was fine (a 3M
    multiply-add loop still took its idle 0.26s) but /api/jobs/backtest — which
    reads ONE small file — took 1.7s, and the header's health probe timed out,
    so the app read "API unreachable" while it was merely queued behind the
    sweep. The sweep is a three-day background job; a click is not. `nice` is
    exactly this trade: the sweep gives up almost nothing because nothing else
    wants the machine most of the time.

    Returns the new niceness, or -1 if the platform would not allow it.
    """
    import os

    try:
        return os.nice(10)
    except (OSError, AttributeError):
        return -1

# ------------------------------------------------------------------ rows
ROWDIR = HOME / "rows"
# Per-contract COSTS, written by the sweep that already fetched them and read
# by the trade log so a click never has to. Measured on USELESS_USDT:
# funding_history is 9.2 s and 2,869 settlements EVERY call (no cache), the
# taker fee 0.17 s cold -- which is where a click's ten seconds went.
COSTS = HOME / "costs"


def save_costs(symbol: str, *, fee: float, liq, funding: list) -> None:
    """Keep what the replay of this contract needs. Never raises: telemetry
    for a click, not part of the measurement."""
    try:
        COSTS.mkdir(parents=True, exist_ok=True)
        tmp = COSTS / f"{symbol}.tmp"
        tmp.write_text(json.dumps({
            "symbol": symbol, "fee": fee, "liq": liq,
            "at": time.time(),
            "funding": [{"settle_ms": int(f["settle_ms"]),
                         "rate": float(f["rate"])}
                        for f in (funding or [])
                        if f and f.get("settle_ms") is not None],
        }, separators=(",", ":")))
        tmp.replace(COSTS / f"{symbol}.json")
    except (OSError, TypeError, ValueError):
        pass


def load_costs(symbol: str) -> dict | None:
    """The saved fee/liquidation/funding for one contract, or None."""
    try:
        got = json.loads((COSTS / f"{symbol}.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(got, dict) or "fee" not in got:
        return None
    return got


def pair_rows(coin: str, tf: str) -> list:
    try:
        return json.loads((ROWDIR / f"{coin}-{tf}.json").read_text())
    except (OSError, ValueError):
        return []


def save_pair_rows(coin: str, tf: str, rows: list) -> None:
    ROWDIR.mkdir(parents=True, exist_ok=True)
    with _pair_lock(coin, tf):
        tmp = ROWDIR / f"{coin}-{tf}.json.tmp"
        tmp.write_text(json.dumps(rows, separators=(",", ":")))
        tmp.replace(ROWDIR / f"{coin}-{tf}.json")


def discard_pair(coin: str, tf: str) -> dict:
    """Delete everything a half-finished pair left behind.

    The operator, 2026-08-25: *"if a coin fails, delete the backtest then redo
    again the last failed job (not the whole)"*.

    A pair that raises part-way has usually already written some rows and a
    state file whose watermark is stale or absent. Retrying on top of that
    leaves the store carrying a mixture of two runs for one coin, and no column
    anywhere says which rows came from which. So the retry starts from nothing:
    the rows file, the state file and any `.tmp` beside them go first.

    The candles are NOT deleted -- they are the expensive part, they are shared
    with every other timeframe, and they were not what failed."""
    _paths()
    gone = []
    with _pair_lock(coin, tf):
        for f in (ROWDIR / f"{coin}-{tf}.json",
                  ROWDIR / f"{coin}-{tf}.json.tmp",
                  _state_file(coin, tf),
                  _state_file(coin, tf).with_suffix(".json.tmp")):
            try:
                size = f.stat().st_size
            except OSError:
                continue
            with contextlib.suppress(OSError):
                f.unlink()
                gone.append({"file": f.name, "bytes": size})
    return {"coin": coin, "tf": tf, "deleted": gone}


def _row_key(r: dict) -> str:
    """The combination a row measures — the identity a merge keys on."""
    return combo_key(str(r.get("signal")), float(r.get("th") or 0),
                     float(r.get("sl") or 0), float(r.get("tp") or 0),
                     str(r.get("sizing")))


def merge_pair_rows(coin: str, tf: str, rows: list) -> int:
    """Write `rows` OVER whatever is stored for this pair, keeping the rest.

    A checkpoint holds only the combinations measured so far, so writing it
    with save_pair_rows would delete every combination not yet reached — the
    pair would come back from a crash with a fraction of its grid and no sign
    that anything was missing. Merging by combination keeps the untouched rows
    and replaces the recomputed ones. Returns the stored row count.
    """
    have = {_row_key(r): r for r in pair_rows(coin, tf)}
    have.update({_row_key(r): r for r in rows})
    merged = list(have.values())
    save_pair_rows(coin, tf, merged)
    return len(merged)


def all_rows() -> list:
    """Every stored row, across every contract and timeframe."""
    if not ROWDIR.exists():
        return []
    out = []
    for f in sorted(ROWDIR.glob("*.json")):
        try:
            out += json.loads(f.read_text())
        except ValueError:
            continue
    return out


def coverage() -> dict:
    """What the store holds: pairs, rows, and how fresh each timeframe is."""

    pairs = sorted(p.stem for p in ROWDIR.glob("*.json")) if ROWDIR.exists() \
        else []
    newest = 0
    for f in (STATES.glob("*.json") if STATES.exists() else []):
        try:
            newest = max(newest, int(json.loads(f.read_text())
                                     .get("__last_ms__", 0)))
        except ValueError:
            continue
    return {"pairs": len(pairs), "rows": len(all_rows()),
            "last_bar": (fmt_stamp(newest / 1000) if newest else None),
            "coins": len({p.split("-")[0] for p in pairs})}


# ------------------------------------------------------------------- run
def run_pair(symbol: str, tf: str, *, slot: int | None = None,
             base_margin: float = 5.0,
             days: int = 365, signals: Sequence[str] | None = None,
             thresholds: int = 1, fresh: bool = False,
             merge: bool = False) -> dict:
    """Test (or continue) every combination for one contract and timeframe.

    `fresh=True` throws the resume point away and replays every combination
    from its first bar. That is what the BACKTEST button does; the UPDATE
    button leaves it False so it only walks bars that printed since.

    `merge=True` is for ADDING signals to a pair that is already measured: the
    named `signals` are walked over the whole window, and the result is merged
    into what is stored -- rows by combination, states by key, the watermark by
    max -- so the combinations this pass did not touch keep their rows AND
    their resume points. Registering the five 4-hour confluence setups took the
    registry from 105 to 120 (2026-08-27); without this, adding them would have
    re-measured 21.9 million rows to obtain 15 rules' worth of new ones."""
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br
    from tradingagents.dataflows import mexc_futures as fx

    coin = symbol.replace("_USDT", "")
    iv, bs, cap = br.TFS[tf]
    df, added, source = refresh_candles(symbol, tf, days=days)
    # per timeframe, never a flat 500: that made 1d impossible (br.MIN_BARS)
    if len(df) < br.min_bars(tf):
        return {"coin": coin, "tf": tf, "rows": [], "added": added,
                "source": source, "why": f"only {len(df)} bars"}
    # NOT wrapped in `except Exception: fund = []`. That turned an unreadable
    # funding history into a backtest with ZERO funding charged -- the same lie
    # funding_history used to tell by returning half its pages. A read that
    # fails now reaches the pool, which discards this pair and redoes it
    # (PAIR_RETRIES); a contract with no settlements still returns [].
    fund = fx.funding_history(symbol)

    try:
        fee = at.taker_fee(symbol, fx=fx)
        liq = fx.liquidation_move_pct(symbol, at.LEVERAGE)
        book = fx.book_cost(symbol, base_margin * at.LEVERAGE)
        rt = br.round_trip_cost(fee, book)
    except Exception as exc:
        return {"coin": coin, "tf": tf, "rows": [], "added": added,
                "source": source, "why": f"venue: {str(exc)[:60]}"}
    # keep what the click will need, so opening a row later is a pure read
    save_costs(symbol, fee=fee, liq=liq, funding=fund)
    thin = 0               # rows the trade floor dropped, for the report
    states = {} if (fresh and not merge) else load_states(coin, tf)
    # what this pass is measuring, and what the pair had measured before it
    sig_set = set(signals or br.SIGNALS)
    had_sigs = set(states.get("__signals__") or signals_in(states))
    # A pair measured in the CLOUD carries a watermark but no per-combination
    # state, so resuming from it would start every combination at that bar with
    # no ladder rung or running total behind it — extending a measurement this
    # machine never made. Recompute instead; the cloud rows stand until it does.
    if states.get("__cloud__"):
        states = {}
    # merge mode walks the whole window for the signals it was given: their
    # combinations have no state behind them, so resuming would start them at
    # the last bar with no ladder rung and no running total
    last_ms = 0 if (fresh or merge) else int(states.get("__last_ms__", 0))
    # A store built with an older signal library must not be served as if it
    # were current: 54-signal rows silently missing 21 rules is a wrong answer
    # wearing a cached one's clothes. Version mismatch resets the pair.
    # A store built with an older signal library must not be served as if it
    # were current: 54-signal rows silently missing 21 rules is a wrong answer
    # wearing a cached one's clothes.
    #
    # The COUNT was the whole fingerprint until 2026-08-27, and adding five
    # setups (105 -> 120 rules) therefore invalidated every pair in the store --
    # 21.9 million rows, days of measurement, to obtain the new rules' first
    # pass. A NAMED SET says the true thing instead: this pair is stale when the
    # registry has a signal the pair has never measured. The count string is
    # still written, and still used for a pair whose state predates the set.
    # what the pair HOLDS after this pass, never what this pass measured: a
    # merge of 15 rules onto 105 leaves 120 behind, and stamping "signals15"
    # would be a true number under a false label.
    ver = (f"signals{len(sig_set | had_sigs) if merge else len(signals or br.SIGNALS)}"
           f"-th{thresholds}")
    if last_ms and not merge:
        if had_sigs:
            if sig_set - had_sigs:
                states, last_ms, had_sigs = {}, 0, set()
        elif states.get("__version__") not in (None, ver):
            states, last_ms = {}, 0
    states["__version__"] = ver
    # State without rows shows the operator nothing. If the grid for this pair
    # is missing (first build, or a store wiped by hand), ignore the resume
    # point and measure it again rather than reporting "no new bars" forever.
    if last_ms and not pair_rows(coin, tf):
        states, last_ms = {}, 0
    ms = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    # Where does new work start? The first bar after everything already tested.
    start_at = 0
    if last_ms:
        newer = [k for k, v in enumerate(ms) if int(v) > last_ms]
        start_at = newer[0] if newer else len(df)
    incremental = bool(last_ms) and 0 < start_at < len(df)
    if last_ms and start_at >= len(df):
        save_states(coin, tf, states)          # persists a fresh __version__
        worker_write(pair=f"{coin} {tf}", done=0, total=0, pct=100.0,
                     state="no new bars")
        return {"coin": coin, "tf": tf, "rows": pair_rows(coin, tf), "thin": thin,
                "added": added, "source": source, "why": "no new bars",
                "incremental": True, "new_bars": 0, "fee": fee,
                "liq": liq, "rt": rt, "bars": len(df),
                "days": int((df["Date"].iloc[-1] - df["Date"].iloc[0]).days)}

    # An incremental pass only needs the new bars plus enough lookback for the
    # signal rules to be identical to what a full run would have computed.
    lo = max(0, start_at - CONTEXT_BARS) if incremental else 0
    frame = df.iloc[lo:].reset_index(drop=True)
    off = start_at - lo if incremental else 0
    hi_l = [float(x) for x in frame["High"]]
    lo_l = [float(x) for x in frame["Low"]]
    cl_l = [float(x) for x in frame["Close"]]
    # 17 of the entry rules read the OPEN, the VOLUME or the bar's clock
    # (candlestick shapes, opening-range breaks, volume spikes, kill zones).
    # Calling _dirs_for_backtest with only high/low/close returns an all-zero
    # array for those, so they appear in the signal list and can never produce
    # a row -- a silent hole in the grid.
    op_l = [float(x) for x in frame["Open"]]
    vol_l = ([float(x) for x in frame["Volume"]]
             if "Volume" in frame.columns else None)
    ts_l = list(frame["Date"].to_numpy().astype("datetime64[ms]")
                .astype("int64"))
    days_have = int((df["Date"].iloc[-1] - df["Date"].iloc[0]).days)
    n = len(frame)
    n // 2

    sigs = list(signals or br.SIGNALS)
    out_rows = []
    done_combos = 0
    last_ckpt = _clock()           # the time floor starts when the pair does
    # The denominator, computed the same way the loops below iterate — a
    # percentage whose total is a guess is worse than no percentage.
    total_combos = 0
    for _sig in sigs:
        _ths = ((br.THRESHOLDS[tf][:thresholds] if thresholds < 3
                 else br.THRESHOLDS[tf]) if _sig in br.THRESH_SIGNALS else [None])
        total_combos += len(_ths) * len(br.pairs_for(tf)) * 2
    worker_write(pair=f"{coin} {tf}", done=0, total=total_combos,
                 pct=0.0, state="starting")
    for sig in sigs:
        ths = (br.THRESHOLDS[tf][:thresholds] if thresholds < 3
               else br.THRESHOLDS[tf]) if sig in br.THRESH_SIGNALS else [None]
        for th in ths:
            key = f"{sig}_bt_{tf}"
            at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs,
                                      "tp": .02, "sl": .01,
                                      "threshold": .003 if th is None else th}
            try:
                dk = "rsi14_1h" if sig == "rsi14" else key
                dirs = at._dirs_for_backtest(dk, hi_l, lo_l, cl_l,
                                             opens=op_l, volume=vol_l,
                                             ts=ts_l, funding=fund)
            except Exception:
                at.STRATEGY_SPECS.pop(key, None)
                continue
            thp = 0.0 if th is None else round(th * 100, 3)
            for (sl, tp), sz in itertools.product(br.pairs_for(tf),
                                                  br.SIZINGS):
                if liq is not None and sl * 100 >= liq:
                    continue
                if rt is not None and rt / tp >= GATE_BLOCK:
                    continue
                ck = combo_key(sig, thp, sl * 100, tp * 100, sz)
                prev = states.get(ck) if incremental else None
                try:
                    r = at.backtest_strategy(
                        key, frame, base_margin, fee=fee, sizing=sz, dirs=dirs,
                        tp=tp, sl=sl, liq_move_pct=liq, funding=fund,
                        keep_log=False, resume=prev or {}, start_at=off)
                except Exception:
                    continue
                states[ck] = r["state"]
                # CHECKPOINT. Before this, states and rows were written once,
                # after the whole pair finished — so a crash at 99% threw away
                # every combination in the pair (~2,000 backtests) and the next
                # run recomputed all of it. Now a crash costs at most
                # CHECKPOINT_EVERY. __last_ms__ is deliberately NOT advanced
                # here: the watermark means "every bar up to here has been
                # tested for every combination", and that is only true when the
                # pair completes. Advancing it early would make the next run
                # skip bars the unreached combinations never saw.
                done_combos += 1
                # cheap: just say where we are
                if done_combos % PUBLISH_EVERY == 0:
                    worker_write(pair=f"{coin} {tf}",
                                 done=done_combos, total=total_combos,
                                 # two decimals: a core grinding through
                                 # 17,820 combinations moves less than a whole
                                 # percent between publishes
                                 pct=(round(100 * done_combos / total_combos, 2)
                                      if total_combos else 0.0),
                                 rows=len(out_rows), state="running")
                # expensive: make the work survive a crash -- on the count,
                # and only once the time floor has passed (see CHECKPOINT_MIN_S)
                if done_combos % CHECKPOINT_EVERY == 0 and checkpoint_due(last_ckpt):
                    save_states(coin, tf, states)
                    merge_pair_rows(coin, tf, out_rows)
                    last_ckpt = _clock()
                # STAND DOWN if the operator asked to hand over. Checked here,
                # beside the checkpoint, so everything measured is on disk
                # first and the pair resumes exactly here next time.
                if (done_combos % _HANDOFF_EVERY == 0) and handoff_pending():
                    save_states(coin, tf, states)
                    merge_pair_rows(coin, tf, out_rows)
                    last_ckpt = _clock()
                    worker_write(pair=f"{coin} {tf}", done=done_combos,
                                 total=total_combos, rows=len(out_rows),
                                 state="handed off")
                    return {"coin": coin, "tf": tf, "rows": out_rows, "thin": thin,
                            "added": added, "source": source,
                            "new_bars": (max(0, len(df) - start_at)
                                         if incremental else len(df)),
                            "why": "handed off to GitHub Actions"}
                # "everything stored": losers are measurements too, and the
                # store is what makes re-analysis free. Only the trade floor
                # filters — a 3-trade row is noise, not a loser.
                if r["trades"] < min_trades(tf, days=days):
                    thin += 1          # counted, never silent (rule 20)
                    continue
                m = r["monthly"]
                mk = sorted(m)
                h1 = sum(m[k2] for k2 in mk[:max(1, len(mk) // 2)])
                h2 = sum(m[k2] for k2 in mk[max(1, len(mk) // 2):])
                out_rows.append({
                    "coin": coin, "tf": tf, "signal": sig, "th": thp,
                    "sl": round(sl * 100, 3), "tp": round(tp * 100, 3),
                    "rr": round(tp / sl, 2), "sizing": sz, "lev": at.LEVERAGE,
                    "base": base_margin, "notional": base_margin * at.LEVERAGE,
                    "trades": r["trades"], "wins": r["wins"],
                    "losses": r["losses"],
                    "winrate": round(100 * r["wins"] / r["trades"], 2),
                    "profit": round(r["profit"], 2),
                    "funding": round(r["funding_total"], 2),
                    "h1": round(h1, 2), "h2": round(h2, 2),
                    "green": sum(1 for v in m.values() if v > 0),
                    "months": len(m), "worst": round(r["worst_trade"], 2),
                    # The WORST UNBROKEN RUN of losses, and how many trades it
                    # took. Mandatory since APEX (worst trade -$9.12, worst run
                    # -$79.80 over 13 trades on a $65 wallet): on a ladder the
                    # run is what empties the account, and a worst-trade column
                    # alone hides it. The engine has computed both all along;
                    # 17 GB of rows were written without them.
                    "streak": round(r["worst_streak"], 2),
                    "streak_len": r["worst_streak_len"],
                    "dd": round(r["max_dd"], 2), "liqs": r["liqs"],
                    "stop_reachable": True, "days": days_have,
                    "bars": len(df),
                    # WHERE THE WINDOW ENDED. The pair has one watermark and it
                    # moves: a later pass that only ADDS signals advances it,
                    # and an older row measured to Aug 27 12:00am can then no
                    # longer be reproduced from it (AGT 1h cf_soup1 came back
                    # 107 trades / $148.87 against 108 / $145.73). The row's
                    # own last bar is 8 bytes and settles it.
                    "last_ms": int(ms[-1]),
                    # AND THE FEE IT WAS CHARGED. A contract's taker fee
                    # changes: PONS_USDT reads 0.0004 today and its stored 15m
                    # rows were measured at 0.0002, so replaying one with
                    # today's fee turned +$1,638.14 into +$1,288.70 (21% off)
                    # over the identical 1,820 trades. `rt` cannot recover it —
                    # it mixes the fee with the book's spread at the time.
                    "fee": round(fee, 8),
                    "monthly": {k2: round(v2, 2) for k2, v2 in m.items()},
                    "cost_of_tp": round(rt / tp * 100, 1),
                    "rt": round(rt * 100, 4),
                    "gate": "warn" if rt / tp >= .2 else "ok"})
            at.STRATEGY_SPECS.pop(key, None)
    states["__last_ms__"] = max(int(ms[-1]),
                                int(states.get("__last_ms__") or 0)) \
        if merge else int(ms[-1])
    # The named set the version check reads: what this pass measured, plus what
    # the pair had measured before it (merge mode adds, it does not replace).
    states["__signals__"] = sorted(sig_set | (had_sigs if merge else set()))
    save_states(coin, tf, states)
    if merge:
        # rows BY COMBINATION: the 105 signals this pass never looked at keep
        # theirs, and the new ones are added beside them
        merge_pair_rows(coin, tf, out_rows)
    else:
        save_pair_rows(coin, tf, out_rows)
    worker_write(pair=f"{coin} {tf}", done=done_combos,
                 total=total_combos, pct=100.0, rows=len(out_rows),
                 state="done")
    return {"coin": coin, "tf": tf, "rows": out_rows, "thin": thin, "added": added,
            "source": source, "incremental": incremental,
            "fee": fee, "liq": liq, "rt": rt,
            "new_bars": max(0, len(df) - start_at) if incremental else len(df),
            "bars": len(df), "days": days_have}


# --------------------------------------------------------------- background
# How many times ONE pair is redone before the sweep gives up on it and moves
# on. Per pair, never per sweep: a coin that fails must not restart the other
# 4,964 (operator, 2026-08-25).
PAIR_RETRIES = 2


def min_bars(tf: str) -> int:
    """The shared floor (backtest_report.MIN_BARS) -- one definition."""
    from tradingagents import backtest_report as br

    return br.min_bars(tf)

PROGRESS = HOME / "progress.json"
PIDFILE = HOME / "sweep.pid"


def progress() -> dict:
    try:
        return json.loads(PROGRESS.read_text())
    except (OSError, ValueError):
        return {}


def is_running() -> bool:
    """True when a sweep process is alive. Checked by PID, never by name —
    matching on a name once killed the operator's own server."""
    try:
        pid = int(PIDFILE.read_text().strip())
    except (OSError, ValueError):
        return False
    return portable.pid_alive(pid)


def stop() -> bool:
    try:
        pid = int(PIDFILE.read_text().strip())
        os.kill(pid, 15)
        return True
    except (OSError, ValueError):
        return False


def br_signals():
    """The signal registry, imported late (backtest_report imports this one)."""
    from tradingagents import backtest_report as _br

    return _br.SIGNALS


def _worker(args):
    # The tuple grew when the 4-hour confluence setups were added (2026-08-27):
    # a pass may now name the SIGNALS it measures and merge them into what is
    # already stored. Old five-tuples still work.
    sym, tf, base_margin, days, thresholds = args[:5]
    signals = args[5] if len(args) > 5 else None
    merge = bool(args[6]) if len(args) > 6 else False
    try:
        r = run_pair(sym, tf, base_margin=base_margin, days=days,
                     thresholds=thresholds, signals=signals, merge=merge)
        return {"sym": sym, "tf": tf, "rows": len(r.get("rows") or []),
                "source": r.get("source"), "why": r.get("why"),
                "new_bars": r.get("new_bars", 0)}
    except Exception as exc:                      # one coin must not stop 446
        # Delete what the half-finished pair left behind BEFORE anyone can
        # merge it. A retry then starts from nothing rather than layering a
        # second run's rows on top of a first run's wreckage.
        drop = discard_pair(sym.replace("_USDT", ""), tf)
        return {"sym": sym, "tf": tf, "rows": 0, "why": str(exc)[:80],
                "failed": True, "discarded": len(drop["deleted"])}


def run_market(symbols: Sequence[str], tfs: Sequence[str] = ("15m", "30m"), *,
               base_margin: float = 5.0, days: int = 365,
               thresholds: int = 1, workers: int = 0,
               signals: Sequence[str] | None = None,
               merge: bool = False) -> dict:
    """Sweep many contracts across every core, writing progress as it goes.

    Runs in whatever process calls it — the Back Test tab spawns this detached
    so a click in Streamlit cannot restart or kill it.
    """
    from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

    _paths()
    workers = workers or max(1, (os.cpu_count() or 4) - 1)
    sigs = list(signals) if signals else None
    jobs = [(s, tf, base_margin, days, thresholds, sigs, merge)
            for s in symbols for tf in tfs]
    t0 = time.time()
    state = {"phase": "adding signals" if merge else "sweeping",
             # what is being measured, so the panel never reads a 15-rule pass
             # as if it were the whole grid
             "signals": len(sigs) if sigs else len(br_signals()),
             "merging": bool(merge),
             "total": len(jobs), "done": 0, "rows": 0, "new_bars": 0,
             "retries": 0, "failed": 0, "failures": [],
             "started": fmt_stamp(), "workers": workers,
             "running": True, "last": "", "eta_min": None}
    PROGRESS.write_text(json.dumps(state))
    PIDFILE.write_text(str(os.getpid()))
    tries: dict = {}
    try:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            # A dict rather than as_completed(): a failed pair is resubmitted
            # into the SAME pool, so the retry set has to be able to grow while
            # the sweep runs.
            pending = {ex.submit(_worker, j): j for j in jobs}
            while pending:
                ready, _ = wait(list(pending), return_when=FIRST_COMPLETED)
                for f in ready:
                    job = pending.pop(f)
                    r = f.result()
                    key = (r["sym"], r["tf"])
                    el = time.time() - t0

                    # The operator, 2026-08-25: "if a coin fails, delete the
                    # backtest then redo again the last failed job (not the
                    # whole)". _worker has already deleted the half-written
                    # pair; requeue THAT PAIR and nothing else. `total` counts
                    # pairs, so a retry never inflates the denominator and the
                    # percentage stays a percentage of the work asked for.
                    if r.get("failed") and tries.get(key, 0) < PAIR_RETRIES:
                        tries[key] = tries.get(key, 0) + 1
                        state["retries"] += 1
                        state["last"] = (
                            f"{r['sym']} {r['tf']} failed ({r.get('why')}) "
                            f"· discarded, redoing it "
                            f"{tries[key]}/{PAIR_RETRIES}")
                        pending[ex.submit(_worker, job)] = job
                        PROGRESS.write_text(json.dumps(state))
                        continue

                    state["done"] += 1
                    state["rows"] += r.get("rows", 0)
                    state["new_bars"] += int(r.get("new_bars") or 0)
                    if r.get("failed"):
                        state["failed"] += 1
                        # named, not just counted: a bare "3 failed" sends
                        # somebody back to the logs to find out which three
                        state["failures"] = (state["failures"] +
                                             [f"{r['sym']} {r['tf']}: "
                                              f"{r.get('why')}"])[-50:]
                    state["eta_min"] = round(
                        el / max(state["done"], 1)
                        * (state["total"] - state["done"]) / 60, 1)
                    state["elapsed_min"] = round(el / 60, 1)
                    state["last"] = (
                        f"{r['sym']} {r['tf']} · {r.get('rows', 0)} "
                        f"rows{' · ' + r['why'] if r.get('why') else ''}")
                    PROGRESS.write_text(json.dumps(state))
    finally:
        state["running"] = False
        state["finished"] = fmt_stamp()
        PROGRESS.write_text(json.dumps(state))
        with contextlib.suppress(OSError):
            PIDFILE.unlink()
    return state


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m tradingagents.market_sweep --coins 25`` — what the tab spawns."""
    import argparse

    ap = argparse.ArgumentParser(description="Market-wide 15m/30m sweep")
    ap.add_argument("--coins", type=int, default=0,
                    help="how many eligible contracts (0 = all)")
    ap.add_argument("--min-days", type=int, default=365)
    ap.add_argument("--tfs", default="15m,30m")
    ap.add_argument("--base", type=float, default=5.0)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--thresholds", type=int, default=1)
    # The WINDOW, in days. run_market defaulted to 365 and the CLI never passed
    # it, so a command line sweep always measured a year while the app's own
    # 2-month job measured 89 days -- two windows under one store. Named here so
    # a pass that ADDS signals can measure the same window the existing rows
    # were measured over (refresh_candles fetches days + 30).
    ap.add_argument("--days", type=int, default=365,
                    help="window in days (the fetch adds 30 for warm-up)")
    ap.add_argument("--signals", default="",
                    help="comma-separated signal names to measure (default: "
                         "every signal in backtest_report.SIGNALS)")
    ap.add_argument("--merge", action="store_true",
                    help="MERGE the measured signals into what is already "
                         "stored instead of replacing the pair's rows -- how "
                         "new rules are added without re-measuring the store")
    a = ap.parse_args(argv)

    import datetime as _dt

    from tradingagents.dataflows import mexc_futures as fx

    _paths()
    # Claim the PID here, not in run_market: screening runs first and can take
    # 15 minutes, and until the file exists the tab reports "not running".
    PIDFILE.write_text(str(os.getpid()))
    # Screening ~1,000 contracts for age takes a quarter of an hour and used to
    # happen in silence, so the tab showed nothing at all for the first 15
    # minutes. Cache it for the day, and report progress while it runs.
    elig_f = HOME / "eligible.json"
    keep = []
    try:
        cached = json.loads(elig_f.read_text())
        if cached.get("day") == _dt.date.today().isoformat() \
                and int(cached.get("min_days", 0)) == a.min_days:
            keep = cached["symbols"]
    except (OSError, ValueError, KeyError):
        keep = []
    if not keep:
        raw = fx._get_public(f"{fx.BASE}/api/v1/contract/detail").get("data") or []
        syms = sorted(x["symbol"] for x in raw
                      if str(x.get("symbol", "")).endswith("_USDT")
                      and int(x.get("state", 1)) == 0)
        for i, s in enumerate(syms, 1):
            try:
                d = fx.klines(s, "Day1", 500)
                if (d["Date"].iloc[-1] - d["Date"].iloc[0]).days >= a.min_days:
                    keep.append(s)
            except Exception:
                pass
            if i % 10 == 0 or i == len(syms):
                PROGRESS.write_text(json.dumps({
                    "phase": "screening", "total": len(syms), "done": i,
                    "rows": 0, "new_bars": 0, "running": True,
                    "workers": a.workers or max(1, (os.cpu_count() or 4) - 1),
                    "started": fmt_stamp(),
                    "last": f"{len(keep)} contracts at least "
                            f"{a.min_days} days old so far"}))
        elig_f.write_text(json.dumps({"day": _dt.date.today().isoformat(),
                                      "min_days": a.min_days,
                                      "symbols": keep}))
    if a.coins:
        keep = keep[:a.coins]
    print(f"{len(keep)} contracts at least {a.min_days} days old", flush=True)
    sigs = [x.strip() for x in a.signals.split(",") if x.strip()] or None
    if sigs:
        from tradingagents import backtest_report as _br
        unknown = [x for x in sigs if x not in _br.SIGNALS]
        if unknown:
            print(f"unknown signal(s): {', '.join(unknown)}", flush=True)
            return 2
        print(f"measuring {len(sigs)} signal(s), "
              f"{'merging into' if a.merge else 'replacing'} the store",
              flush=True)
    st = run_market(keep, [t.strip() for t in a.tfs.split(",") if t.strip()],
                    base_margin=a.base, thresholds=a.thresholds,
                    workers=a.workers, signals=sigs, merge=a.merge,
                    days=a.days)
    print(f"done: {st['done']}/{st['total']} jobs, {st['rows']:,} rows, "
          f"{st.get('elapsed_min')} min", flush=True)
    return 0




def compute_combos(symbol: str, tf: str, combos: list, *,
                   base_margin: float = 5.0, days: int = 365) -> list:
    """Compute SPECIFIC combinations over the full cached history and fold
    them into the pair's store.

    Exists for rule 21: the exact deployed combination must appear in every
    page, and a live 0.80/2.40 pair is in no grid of round numbers. Each combo
    dict names signal/th/sl/tp/sizing (percent units, like stored rows).
    """
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br
    from tradingagents.dataflows import mexc_futures as fx

    coin = symbol.replace("_USDT", "")
    iv, bs, cap = br.TFS[tf]
    df, _added, _src = refresh_candles(symbol, tf, days=days)
    if len(df) < 300:
        return []
    fee = at.taker_fee(symbol, fx=fx)
    liq = fx.liquidation_move_pct(symbol, at.LEVERAGE)
    # same rule as run_pair: an unreadable funding history is an error, never
    # silently zero funding (2026-08-26)
    fund = fx.funding_history(symbol)
    try:
        book = fx.book_cost(symbol, base_margin * at.LEVERAGE)
        rt = br.round_trip_cost(fee, book)
    except Exception:
        rt = None
    hi = [float(x) for x in df["High"]]
    lo = [float(x) for x in df["Low"]]
    cl = [float(x) for x in df["Close"]]
    op = [float(x) for x in df["Open"]]
    vol = [float(x) for x in df["Volume"]] if "Volume" in df.columns else None
    ts = list(df["Date"].to_numpy().astype("datetime64[ms]").astype("int64"))
    days_have = int((df["Date"].iloc[-1] - df["Date"].iloc[0]).days)
    n = len(df)
    half = n // 2
    out = []
    for c in combos:
        sig, thp = c["signal"], float(c.get("th") or 0)
        sl, tp = float(c["sl"]) / 100, float(c["tp"]) / 100
        sz = c["sizing"]
        key = f"{sig}_cc_{tf}"
        at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs,
                                  "tp": .02, "sl": .01,
                                  "threshold": (thp / 100) or .003}
        try:
            dk = "rsi14_1h" if sig == "rsi14" else key
            dirs = at._dirs_for_backtest(dk, hi, lo, cl, opens=op,
                                         volume=vol, ts=ts, funding=fund)
            r = at.backtest_strategy(key, df, base_margin, fee=fee,
                                     sizing=sz, dirs=dirs, tp=tp, sl=sl,
                                     liq_move_pct=liq, funding=fund,
                                     keep_log=False)
            a = at.backtest_strategy(key, df.iloc[:half], base_margin,
                                     fee=fee, sizing=sz, dirs=dirs[:half],
                                     tp=tp, sl=sl, liq_move_pct=liq,
                                     funding=fund, keep_log=False)
            b = at.backtest_strategy(key, df.iloc[half:], base_margin,
                                     fee=fee, sizing=sz, dirs=dirs[half:],
                                     tp=tp, sl=sl, liq_move_pct=liq,
                                     funding=fund, keep_log=False)
        except Exception:
            at.STRATEGY_SPECS.pop(key, None)
            continue
        at.STRATEGY_SPECS.pop(key, None)
        if not r["trades"]:
            continue
        out.append({
            "coin": coin, "tf": tf, "signal": sig, "th": round(thp, 3),
            "sl": round(sl * 100, 3), "tp": round(tp * 100, 3),
            "rr": round(tp / sl, 2), "sizing": sz, "lev": at.LEVERAGE,
            "base": base_margin, "notional": base_margin * at.LEVERAGE,
            "trades": r["trades"], "wins": r["wins"], "losses": r["losses"],
            "winrate": round(100 * r["wins"] / r["trades"], 2),
            "profit": round(r["profit"], 2),
            "funding": round(r["funding_total"], 2),
            "wstreak": r.get("worst_streak"),
            "wstreakn": r.get("worst_streak_len"),
            "h1": round(a["profit"], 2), "h2": round(b["profit"], 2),
            "green": r["months_green"], "months": r["months_total"],
            "worst": round(r["worst_trade"], 2), "dd": round(r["max_dd"], 2),
            "liqs": r["liqs"], "stop_reachable": bool(liq is None
                                                      or sl * 100 < liq),
            "days": days_have, "bars": n,
            "monthly": {k: round(v, 2) for k, v in r["monthly"].items()},
            "cost_of_tp": 0.0 if rt is None else round(rt / tp * 100, 1),
            "rt": None if rt is None else round(rt * 100, 4),
            "gate": ("unknown" if rt is None
                     else "warn" if rt / tp >= .2 else "ok")})
    if out:
        have = pair_rows(coin, tf)
        seen = {(r["signal"], r["th"], r["sl"], r["tp"], r["sizing"])
                for r in have}
        have += [r for r in out
                 if (r["signal"], r["th"], r["sl"], r["tp"], r["sizing"])
                 not in seen]
        save_pair_rows(coin, tf, have)
    return out


def candle_coverage() -> list:
    """What THIS MACHINE holds, per coin and timeframe — the store backtests
    actually read. The operator's words: "i said i want all local machine"."""
    import json as _json

    out = []
    if not CANDLES.exists():
        return out
    for f in sorted(CANDLES.glob("*.json")):
        try:
            d = _json.loads(f.read_text())
            ts = d.get("t") or []
            if not ts:
                continue
            sym, tf = f.stem.rsplit("-", 1)
            import datetime as _dt

            # Operator's one date format (2026-08-21): Aug 26, 2026 4:00PM.
            _d0 = _dt.datetime.fromtimestamp(ts[0] / 1000)
            _d1 = _dt.datetime.fromtimestamp(ts[-1] / 1000)
            _h1 = _d1.hour % 12 or 12
            out.append({
                "symbol": sym, "timeframe": tf, "bars": len(ts),
                "first": f"{_d0:%b} {_d0.day}, {_d0.year}",
                "last": (f"{_d1:%b} {_d1.day}, {_d1.year} "
                         f"{_h1}:{_d1:%M}{_d1:%p}"),
                # the raw epoch too: callers that need to MEASURE the gap must
                # not re-parse the display string (the gaps route did, and the
                # parse failed on every one of 4,899 rows in silence)
                "first_ms": int(ts[0]), "last_ms": int(ts[-1]),
                "days": round((ts[-1] - ts[0]) / 86400000)})
        except (ValueError, OSError):
            continue
    out.sort(key=lambda c: -c["bars"])
    return out


def trades_for(coin: str, tf: str, *, signal: str, th: float, sl: float,
               tp: float, sizing: str, base_margin: float = 5.0,
               days: int = 365) -> dict:
    """Every trade one stored strategy made, rebuilt from the local candles.

    The store keeps ONE row per strategy (trades, wins, profit…); the trades
    themselves are derivable because the replay is deterministic. This is the
    derivation: same candles in, same trades out, and the caller can check the
    log's sum against the stored row's profit — the check that once caught a
    rounding bug worth $1.53.
    """
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br
    from tradingagents.dataflows import mexc_futures as fx

    symbol = f"{coin}_USDT"
    iv, bs, cap = br.TFS[tf]
    # DISK ONLY. This used to call refresh_candles(), which fetches the newest
    # bars: the log then covered days the stored row never measured. On
    # #2UK7Z2D5 (USELESS 1h) the row is 40 trades and +$158.66 over 2,159 bars
    # to Aug 28 4:00am, and the click showed 42 trades and +$164.40 because it
    # had just downloaded through Sep 02. The operator's rule, Sep 02, 2026:
    # "when i click a row it should only read the backtest results it should
    # never update backtest because it will load slowly".
    df = cached_candles(symbol, tf)
    if df is None or len(df) < 60:
        return {"log": [], "why": f"no candles stored for {coin} {tf} — "
                                  f"download candles first"}
    # ...and cut to the window the ROW was measured over: the pair's own
    # watermark (the last bar the sweep saw) and the row's own bar count.
    want_bars, row_end = 0, 0
    for r in pair_rows(coin, tf):
        # a row with a missing field must not turn a click into a 500
        try:
            same = (r.get("signal") == signal
                    and abs(float(r.get("th") or 0) - float(th or 0)) < 1e-9
                    and abs(float(r["sl"]) - float(sl)) < 1e-9
                    and abs(float(r["tp"]) - float(tp)) < 1e-9
                    and r.get("sizing") == sizing)
        except (KeyError, TypeError, ValueError):
            continue
        if same:
            want_bars = int(r.get("bars") or 0)
            row_end = int(r.get("last_ms") or 0)
            break
    # The ROW's own last bar when it has one, the pair's watermark otherwise.
    # Rows measured before `last_ms` existed fall back and can be a trade or
    # two out; the answer says which basis it used so a caller can say so.
    wm = row_end or int(load_states(coin, tf).get("__last_ms__") or 0)
    if wm:
        # A MASK, not a prefix slice, so the cut holds even if a cache ever
        # comes back out of order -- and the conversion goes through
        # `to_numpy().astype("datetime64[ms]")`, never `Series.astype("int64")`.
        # The cached frame's Date is nanoseconds from the JSON cache and
        # MILLISECONDS from the parquet copy, so dividing by 10**6 turned every
        # timestamp into a number far below the watermark, the cut matched
        # everything, and the window slid to Sep 02 again (caught here, 41
        # trades against the row's 40, before it reached the operator).
        ms = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
        cut = df[[int(v) <= wm for v in ms]]
        if len(cut) >= 60:
            df = cut.reset_index(drop=True)
    # NOT sliced yet: the SIGNAL is computed on everything up to the watermark
    # and only then cut to the window, because that is what the sweep did. A
    # rule whose indicators start cold at the window's first bar is a different
    # rule: AGT 1h cf_soup1 came back 107 trades / $148.87 against the row's
    # 108 / $145.73 when the signal was computed on the slice alone.
    full = df
    if not (60 <= want_bars < len(full)):
        want_bars = 0
    # The costs the replay needs come from the file the sweep wrote (see
    # save_costs): funding_history alone is 9.2 s per call on this contract and
    # has no cache of its own. A pair measured before the file existed pays for
    # them once, here, and every click after that is a read.
    row_fee = 0.0
    for r in pair_rows(coin, tf):
        try:
            if (r.get("signal") == signal
                    and abs(float(r.get("th") or 0) - float(th or 0)) < 1e-9
                    and abs(float(r["sl"]) - float(sl)) < 1e-9
                    and abs(float(r["tp"]) - float(tp)) < 1e-9
                    and r.get("sizing") == sizing):
                row_fee = float(r.get("fee") or 0)
                break
        except (KeyError, TypeError, ValueError):
            continue
    costs = load_costs(symbol)
    if costs is None:
        fee = at.taker_fee(symbol, fx=fx)
        try:
            liq = fx.liquidation_move_pct(symbol, at.LEVERAGE)
        except Exception:
            liq = None
        # same rule as run_pair: an unreadable funding history is an error,
        # never silently zero funding (2026-08-26)
        fund = fx.funding_history(symbol)
        save_costs(symbol, fee=fee, liq=liq, funding=fund)
    else:
        fee, liq, fund = costs["fee"], costs.get("liq"), costs.get("funding") or []
    # the ROW's own fee wins: the venue's fee today is not the fee this row was
    # measured under (see the PONS figures above)
    if row_fee > 0:
        fee = row_fee
    hi = [float(x) for x in full["High"]]
    lo = [float(x) for x in full["Low"]]
    cl = [float(x) for x in full["Close"]]
    op = [float(x) for x in full["Open"]]
    vol = [float(x) for x in full["Volume"]] if "Volume" in full.columns else None
    ts = list(full["Date"].to_numpy().astype("datetime64[ms]").astype("int64"))
    key = f"{signal}_tf_{tf}"
    at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs, "tp": .02,
                              "sl": .01, "threshold": (float(th) / 100) or .003}
    try:
        dk = "rsi14_1h" if signal == "rsi14" else key
        dirs = at._dirs_for_backtest(dk, hi, lo, cl, opens=op, volume=vol,
                                     ts=ts, funding=fund)
        if want_bars:                      # signal first, THEN the window
            df = full.iloc[-want_bars:].reset_index(drop=True)
            dirs = dirs[-want_bars:]
        r = at.backtest_strategy(key, df, base_margin, fee=fee, sizing=sizing,
                                 dirs=dirs, tp=float(tp) / 100,
                                 sl=float(sl) / 100, liq_move_pct=liq,
                                 funding=fund, keep_log=True)
    finally:
        at.STRATEGY_SPECS.pop(key, None)
    return {"log": r["log"], "trades": r["trades"], "wins": r["wins"],
            "losses": r["losses"], "profit": round(r["profit"], 2),
            "max_dd": r["max_dd"],
            "winrate": round(100 * r["wins"] / max(r["trades"], 1), 2),
            # what was READ, so the panel can say it and a mismatch is visible
            "source": "stored candles",
            "window_from": "row" if row_end else "pair watermark",
            "fee": fee, "fee_from": "row" if row_fee > 0 else "the venue today",
            "bars": len(df), "first": str(df["Date"].iloc[0])[:16],
            "last": str(df["Date"].iloc[-1])[:16],
            "costs": "cached" if costs is not None else "fetched once"}


# How many (coin, timeframe, signal, threshold) groups one days-window request
# may re-measure. The signal computation is the cost -- ~1-2 s per group on this
# machine for a heavy rule -- and the browser's proxy gives up at 30 s: a 50-row
# page spanning 50 different coins took 30.0 s and came back as a bare HTTP 500
# (measured 2026-09-02). Measured again with the cache below, the panel's own
# rows cost ~0.2 s a group, so 25 is about 15 s in the worst case; past that the
# request SAYS what to narrow instead of dying.
WINDOW_GROUP_MAX = 25
# Signal directions, per (coin, timeframe, signal, threshold, last bar). Paging
# and re-sorting the same coin then costs one walk per row (milliseconds)
# instead of recomputing the rule over 2,000 bars every time.
_DIRS_CACHE: dict = {}
_DIRS_CACHE_MAX = 24
MS_PER_DAY = 86_400_000


class WindowTooWide(ValueError):
    """Too many distinct pairs/signals on the page to re-measure at once."""


def window_rows(rows: list, days: int, base_margin: float = 5.0,
                group_max: int = 0) -> dict:
    """Re-measure each row over the LAST `days` DAYS of its stored candles.

    Returns ``{"rows": [...], "first": str, "last": str, "groups": n}`` and
    mutates each row in place with the window's own figures -- ``w_trades``,
    ``w_wins``, ``w_losses``, ``w_winrate``, ``w_profit``, ``w_dd``,
    ``w_streak``, ``w_streak_len``, ``w_days`` -- and ``restated: True``.

    Three things it does the same way the sweep does, or the numbers would not
    be comparable with the row they sit beside:

    * STORED CANDLES ONLY (`cached_candles`) -- opening a page must never
      download (the operator's rule, 2026-09-02);
    * the window ENDS WHERE THE ROW'S OWN MEASUREMENT ENDS, never at the last
      candle on disk. PONS 15m has candles to Sep 02 while row #AG8FFTN3 was
      measured to Aug 26 04:15, so "last 1 day" reported 46 trades on Sep 01-02
      -- days that row has never been backtested over. The operator caught the
      same fault in the trade log the same morning ("why do i have sept 2
      result when im not yet downloading candle and doing update backtest") and
      it is the same answer: a window is a slice of the measurement, not of the
      candle file. The row's `last_ms` when it has one, the pair's watermark
      otherwise;
    * the SIGNAL is computed over the whole history and only then cut to the
      window, because starving the indicators of warm-up measures a different
      rule (AGT 1h cf_soup1: 107 trades against the row's 108);
    * all three costs, from the file the sweep wrote (`load_costs`): the taker
      fee it was charged, the liquidation distance, and every real funding
      settlement.
    """
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br
    from tradingagents.dataflows import mexc_futures as fx
    from tradingagents.positions_view import fmt_when

    n = max(0, int(days or 0))
    if not n or not rows:
        return {"rows": rows, "first": "", "last": "",
                "first_ms": 0, "last_ms": 0, "groups": 0}
    cap = int(group_max or WINDOW_GROUP_MAX)
    groups: dict = {}
    for r in rows:
        key = (r["coin"], r["tf"], r["signal"], round(float(r.get("th") or 0), 4))
        groups.setdefault(key, []).append(r)
    if len(groups) > cap:
        raise WindowTooWide(
            f"a {n}-day window re-measures every row from the candles, and "
            f"this page spans {len(groups)} different coin/timeframe/signal "
            f"combinations — more than the {cap} one request can do inside the "
            f"browser's 30-second limit. Name a COIN or a SIGNAL, or ask for "
            f"fewer rows a page (10 works everywhere).")
    # EPOCHS while they are compared — a formatted date sorts alphabetically
    # ("Aug 03, 2026" < "Jul 26, 2026"), so the string form is built once, at
    # the end, by the project's one formatter
    first_ms = last_ms = 0
    for (coin, tf, sig, th), grp in groups.items():
        sym = f"{coin}_USDT"
        try:
            full = cached_candles(sym, tf)
            if full is None or len(full) < 60:
                continue
            ms = full["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
            # where the MEASUREMENT ends, not where the candle file does
            wm = int(load_states(coin, tf).get("__last_ms__") or 0)
            ends = {int(r.get("last_ms") or 0) or wm or int(ms[-1]) for r in grp}
            op = [float(x) for x in full["Open"]]
            hi = [float(x) for x in full["High"]]
            lo = [float(x) for x in full["Low"]]
            cl = [float(x) for x in full["Close"]]
            vol = ([float(x) for x in full["Volume"]]
                   if "Volume" in full.columns else None)
            ts = [int(v) for v in ms]
            iv, bs, _cap = br.TFS[tf]
            key = f"{sig}_win_{tf}"
            at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs,
                                      "tp": .02, "sl": .01,
                                      "threshold": (th / 100.0) if th else .003}
            costs = load_costs(sym)
            if costs is None:
                fee = at.taker_fee(sym, fx=fx)
                try:
                    liq = fx.liquidation_move_pct(sym, at.LEVERAGE)
                except Exception:                              # noqa: BLE001
                    liq = None
                fund = fx.funding_history(sym)
                save_costs(sym, fee=fee, liq=liq, funding=fund)
            else:
                fee = costs["fee"]
                liq = costs.get("liq")
                fund = costs.get("funding") or []
            ck = (coin, tf, sig, th, int(ms[-1]), len(ms))
            dirs = _DIRS_CACHE.get(ck)
            if dirs is None:
                dirs = at._dirs_for_backtest(key, hi, lo, cl, opens=op,
                                             volume=vol, ts=ts, funding=fund)
                if len(_DIRS_CACHE) >= _DIRS_CACHE_MAX:
                    _DIRS_CACHE.clear()
                _DIRS_CACHE[ck] = dirs
            # one slice per distinct measurement end in this group (usually one)
            frames = {}
            for end in ends:
                keep = [i for i, v in enumerate(ms) if int(v) <= end]
                if len(keep) < 5:
                    continue
                stop = len(keep)
                lo = int(ms[stop - 1]) - n * MS_PER_DAY
                start = next((i for i in range(stop) if int(ms[i]) >= lo), 0)
                if stop - start < 5:
                    continue
                fr = full.iloc[start:stop].reset_index(drop=True)
                frames[end] = (fr, dirs[start:stop], start, stop)
                f0ms, l0ms = int(ms[start]), int(ms[stop - 1])
                first_ms = f0ms if not first_ms else min(first_ms, f0ms)
                last_ms = l0ms if not last_ms else max(last_ms, l0ms)
            for r in grp:
                end = int(r.get("last_ms") or 0) or wm or int(ms[-1])
                if end not in frames:
                    continue
                frame, win_dirs, start, stop = frames[end]
                # the project's ONE date format, never a hand-rolled slice
                # of a Timestamp: `2026-07-26 20:00` reached the operator's
                # screen on 2026-09-03 (CLAUDE.md bans compact stamps)
                f0 = fmt_when(int(ms[start]) / 1000)
                l0 = fmt_when(int(ms[stop - 1]) / 1000)
                # the ROW's own fee when it recorded one: a contract's fee
                # changes, and today's is not what this row was measured under
                row_fee = float(r.get("fee") or 0) or fee
                res = at.backtest_strategy(
                    key, frame, float(r.get("base") or base_margin),
                    fee=row_fee, sizing=r["sizing"], dirs=win_dirs,
                    tp=float(r["tp"]) / 100.0, sl=float(r["sl"]) / 100.0,
                    liq_move_pct=liq, funding=fund, keep_log=True)
                log = res.get("log") or []
                wins = sum(1 for t in log if t["WIN/LOSE"] == "WIN")
                run, runlen = 0.0, 0
                worst, worst_len = 0.0, 0
                for t in log:
                    pnl = float(t["pnl $"])
                    if pnl < 0:
                        run += pnl
                        runlen += 1
                        if run < worst:
                            worst, worst_len = run, runlen
                    else:
                        run, runlen = 0.0, 0
                r.update({
                    "w_trades": res["trades"], "w_wins": wins,
                    "w_losses": res["trades"] - wins,
                    "w_winrate": round(100.0 * wins / max(1, res["trades"]), 2),
                    "w_profit": round(res["profit"], 2),
                    "w_dd": round(res.get("max_dd") or 0, 2),
                    "w_streak": round(worst, 2), "w_streak_len": worst_len,
                    "w_funding": round(res.get("funding_total") or 0, 2),
                    "w_days": round((int(ms[stop - 1]) - int(ms[start]))
                                    / MS_PER_DAY, 1),
                    "w_first": f0, "w_last": l0,
                    # epochs too, so the browser can print them in the one date
                    # format (positions_view.fmt_when / fmtWhen) instead of
                    # inventing a second one
                    "w_first_ms": int(ms[start]), "w_last_ms": int(ms[stop - 1]),
                    "restated": True})
            at.STRATEGY_SPECS.pop(key, None)
        except Exception as exc:                               # noqa: BLE001
            print(f"[window] {coin} {tf} {sig}: {type(exc).__name__}: "
                  f"{str(exc)[:70]}", flush=True)
    return {"rows": rows,
            "first": fmt_when(first_ms / 1000) if first_ms else "",
            "last": fmt_when(last_ms / 1000) if last_ms else "",
            "first_ms": first_ms, "last_ms": last_ms,
            "groups": len(groups)}


def storage_by_coin() -> list:
    """Disk cost per coin and timeframe, across every store that scales with
    coins: candles (json cache + parquet copy), measured rows, resume states.

    The operator's ask: "i downloaded btc 15m, 30m, 1hr, 4hr … show me total
    size for bitcoin" — so the unit is bytes on THIS machine, per (coin, tf),
    summable per coin. Grid snapshots are per-RUN, not per-coin, and are
    reported separately by the storage panel.
    """
    from tradingagents import parquet_store as pqs

    out: dict = {}

    def add(coin, tf, kind, path):
        try:
            b = path.stat().st_size
        except OSError:
            return
        row = out.setdefault((coin, tf), {"coin": coin, "tf": tf,
                                          "candles": 0, "rows": 0,
                                          "states": 0})
        row[kind] += b

    if CANDLES.exists():
        for f in CANDLES.glob("*.json"):
            sym, tf = f.stem.rsplit("-", 1)
            add(sym.replace("_USDT", ""), tf, "candles", f)
    if pqs.CANDLES.exists():
        for f in pqs.CANDLES.glob("*.parquet"):
            sym, tf = f.stem.rsplit("-", 1)
            add(sym.replace("_USDT", ""), tf, "candles", f)
    if ROWDIR.exists():
        for f in ROWDIR.glob("*.json"):
            coin, tf = f.stem.rsplit("-", 1)
            add(coin, tf, "rows", f)
    if STATES.exists():
        for f in STATES.glob("*.json"):
            coin, tf = f.stem.rsplit("-", 1)
            add(coin, tf, "states", f)
    rows = list(out.values())
    for r in rows:
        r["total"] = r["candles"] + r["rows"] + r["states"]
    rows.sort(key=lambda r: (r["coin"], r["tf"]))
    return rows


# --------------------------------------------------------- candle index
# Reading every stored pair's JSON to learn its last bar took 30+ seconds at
# 4,899 pairs and timed out the UI's proxy. The index keeps one small file
# keyed by each candle file's mtime, so a rescan only opens what CHANGED.
INDEX_PATH = HOME / "candle_index.json"


def candle_index(rebuild: bool = False, scan: bool = True) -> dict:
    """{"SYMBOL-tf": {bars, first_ms, last_ms}} for every stored pair.

    Incremental: a pair whose file has not been rewritten since the last call
    is taken from the index rather than re-read.

    `scan=False` reads the index file and stops. A caller answering an HTTP
    request must use it: while a download is running the files change
    constantly, so even an incremental scan can take a minute and blow the
    UI proxy's timeout. Refresh happens on a background thread instead.
    """
    import json as _json

    _paths()
    try:
        cache = _json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if not scan:
        return cache
    if rebuild:
        cache = {}
    out, dirty = {}, False
    for f in sorted(CANDLES.glob("*.json")):
        key = f.stem
        try:
            stat = f.stat()
            mtime, size = int(stat.st_mtime_ns), int(stat.st_size)
        except OSError:
            continue
        was = cache.get(key)
        if was and was.get("mtime") == mtime and was.get("size") == size:
            out[key] = was
            continue
        try:
            ts = (_json.loads(f.read_text(encoding="utf-8")).get("t") or [])
        except (OSError, ValueError):
            continue
        if not ts:
            continue
        sym, tf = key.rsplit("-", 1)
        out[key] = {"mtime": mtime, "size": size, "symbol": sym,
                    "timeframe": tf,
                    "bars": len(ts), "first_ms": int(ts[0]),
                    "last_ms": int(ts[-1])}
        dirty = True
    if dirty or len(out) != len(cache):
        try:
            tmp = INDEX_PATH.with_suffix(".tmp")
            tmp.write_text(_json.dumps(out), encoding="utf-8")
            tmp.replace(INDEX_PATH)
        except OSError:
            pass
    return out


# The entry point is LAST, deliberately. It sat at line 734 with six more
# definitions below it, so `python -m tradingagents.market_sweep` never saw
# compute_combos and its neighbours while every import did. That is exactly
# how auto_trader lost timeframe_locks for five hours on 2026-08-22 — a bug
# that passes every test, because tests import.
if __name__ == "__main__":
    raise SystemExit(main())
