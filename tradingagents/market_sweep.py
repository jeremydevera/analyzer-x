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


def min_trades(tf: str) -> int:
    return MIN_TRADES_BY_TF.get(tf, MIN_TRADES)

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
def cached_candles(symbol: str, tf: str):
    """Whatever bars are on disk for this contract, as a DataFrame or None."""
    import pandas as pd

    f = CANDLES / f"{symbol}-{tf}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text())
    df = pd.DataFrame({"Date": pd.to_datetime(d["t"], unit="ms"),
                       "Open": d["o"], "High": d["h"], "Low": d["l"],
                       "Close": d["c"]})
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
    (CANDLES / f"{symbol}-{tf}.json").write_text(json.dumps({
        "t": [int(x) for x in df["Date"].to_numpy()
              .astype("datetime64[ms]").astype("int64")],
        "o": [float(x) for x in df["Open"]],
        "h": [float(x) for x in df["High"]],
        "l": [float(x) for x in df["Low"]],
        "c": [float(x) for x in df["Close"]]}, separators=(",", ":")))
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
             thresholds: int = 1, fresh: bool = False) -> dict:
    """Test (or continue) every combination for one contract and timeframe.

    `fresh=True` throws the resume point away and replays every combination
    from its first bar. That is what the BACKTEST button does; the UPDATE
    button leaves it False so it only walks bars that printed since."""
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
    states = {} if fresh else load_states(coin, tf)
    # A pair measured in the CLOUD carries a watermark but no per-combination
    # state, so resuming from it would start every combination at that bar with
    # no ladder rung or running total behind it — extending a measurement this
    # machine never made. Recompute instead; the cloud rows stand until it does.
    if states.get("__cloud__"):
        states = {}
    last_ms = 0 if fresh else int(states.get("__last_ms__", 0))
    # A store built with an older signal library must not be served as if it
    # were current: 54-signal rows silently missing 21 rules is a wrong answer
    # wearing a cached one's clothes. Version mismatch resets the pair.
    ver = f"signals{len(signals or br.SIGNALS)}-th{thresholds}"
    if last_ms and states.get("__version__") not in (None, ver):
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
        return {"coin": coin, "tf": tf, "rows": pair_rows(coin, tf),
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
                                             ts=ts_l)
            except Exception:
                at.STRATEGY_SPECS.pop(key, None)
                continue
            thp = 0.0 if th is None else round(th * 100, 3)
            for (sl, tp), sz in itertools.product(br.pairs_for(tf),
                                                  ("flat", "martingale")):
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
                    return {"coin": coin, "tf": tf, "rows": out_rows,
                            "added": added, "source": source,
                            "new_bars": (max(0, len(df) - start_at)
                                         if incremental else len(df)),
                            "why": "handed off to GitHub Actions"}
                # "everything stored": losers are measurements too, and the
                # store is what makes re-analysis free. Only the trade floor
                # filters — a 3-trade row is noise, not a loser.
                if r["trades"] < min_trades(tf):
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
                    "dd": round(r["max_dd"], 2), "liqs": r["liqs"],
                    "stop_reachable": True, "days": days_have,
                    "bars": len(df),
                    "monthly": {k2: round(v2, 2) for k2, v2 in m.items()},
                    "cost_of_tp": round(rt / tp * 100, 1),
                    "rt": round(rt * 100, 4),
                    "gate": "warn" if rt / tp >= .2 else "ok"})
            at.STRATEGY_SPECS.pop(key, None)
    states["__last_ms__"] = int(ms[-1])
    save_states(coin, tf, states)
    save_pair_rows(coin, tf, out_rows)
    worker_write(pair=f"{coin} {tf}", done=done_combos,
                 total=total_combos, pct=100.0, rows=len(out_rows),
                 state="done")
    return {"coin": coin, "tf": tf, "rows": out_rows, "added": added,
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


def _worker(args):
    sym, tf, base_margin, days, thresholds = args
    try:
        r = run_pair(sym, tf, base_margin=base_margin, days=days,
                     thresholds=thresholds)
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
               thresholds: int = 1, workers: int = 0) -> dict:
    """Sweep many contracts across every core, writing progress as it goes.

    Runs in whatever process calls it — the Back Test tab spawns this detached
    so a click in Streamlit cannot restart or kill it.
    """
    from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

    _paths()
    workers = workers or max(1, (os.cpu_count() or 4) - 1)
    jobs = [(s, tf, base_margin, days, thresholds) for s in symbols
            for tf in tfs]
    t0 = time.time()
    state = {"phase": "sweeping",
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
    st = run_market(keep, [t.strip() for t in a.tfs.split(",") if t.strip()],
                    base_margin=a.base, thresholds=a.thresholds,
                    workers=a.workers)
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
                                         volume=vol, ts=ts)
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
    df, _added, _src = refresh_candles(symbol, tf, days=days)
    if df is None or len(df) < 60:
        return {"log": [], "why": "no candles stored for this pair"}
    fee = at.taker_fee(symbol, fx=fx)
    try:
        liq = fx.liquidation_move_pct(symbol, at.LEVERAGE)
    except Exception:
        liq = None
    # same rule as run_pair: an unreadable funding history is an error, never
    # silently zero funding (2026-08-26)
    fund = fx.funding_history(symbol)
    hi = [float(x) for x in df["High"]]
    lo = [float(x) for x in df["Low"]]
    cl = [float(x) for x in df["Close"]]
    op = [float(x) for x in df["Open"]]
    vol = [float(x) for x in df["Volume"]] if "Volume" in df.columns else None
    ts = list(df["Date"].to_numpy().astype("datetime64[ms]").astype("int64"))
    key = f"{signal}_tf_{tf}"
    at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs, "tp": .02,
                              "sl": .01, "threshold": (float(th) / 100) or .003}
    try:
        dk = "rsi14_1h" if signal == "rsi14" else key
        dirs = at._dirs_for_backtest(dk, hi, lo, cl, opens=op, volume=vol,
                                     ts=ts)
        r = at.backtest_strategy(key, df, base_margin, fee=fee, sizing=sizing,
                                 dirs=dirs, tp=float(tp) / 100,
                                 sl=float(sl) / 100, liq_move_pct=liq,
                                 funding=fund, keep_log=True)
    finally:
        at.STRATEGY_SPECS.pop(key, None)
    return {"log": r["log"], "trades": r["trades"], "wins": r["wins"],
            "losses": r["losses"], "profit": round(r["profit"], 2),
            "max_dd": r["max_dd"],
            "winrate": round(100 * r["wins"] / max(r["trades"], 1), 2)}


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
