"""PENDING = what BROKE. Not what is merely undone.

Operator, 2026-09-09, after a week of counts that climbed back on their own:

    "pending only means these are the candles that had problem during the
     update candles or download candle, resolve mean you will restart or
     resume where it crash / same as on backtest"

What the counts meant before, and why each was wrong under that definition:

* CANDLES said 5,095 pending — almost every stored pair, because "behind"
  measures the CLOCK: a 15m pair is behind fifteen minutes after any run. It
  went 0 at 10:55pm to 5,095 by 9:33am with nothing failing. That is a
  freshness reading, not a problem list.
* BACKTEST said 117 pending — pairs with no measurement file, whether a run
  ever tried them or not. A brand-new listing nobody has swept is not a
  problem either.

Both now mean: a run TRIED this pair and it FAILED. RESOLVE retries exactly
those, and nothing else.

WHY A LEDGER AND NOT THE JOB'S OWN `failed` LIST: the job files hold only the
LAST run. `db_download.lost.json` is rewritten at the end of every download —
"a clean run empties it" — so a failure from a whole-market run vanished the
moment someone downloaded one coin. A problem stays on the books here until
the pair actually succeeds.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

STATE_DIR = Path.home() / ".tradingagents"

# One file per kind. "candles" is filled by the download job, "backtest" by
# the sweep (local) and by the cloud shards' own named losses.
KINDS = ("candles", "backtest")

# A failure is kept even after many retries — it is the operator's to see. But
# the REASON is kept short: this file is read on every panel poll.
WHY_MAX = 160


def path(kind: str) -> Path:
    if kind not in KINDS:
        raise ValueError(f"unknown pending kind: {kind!r}")
    return STATE_DIR / f"pending_{kind}.json"


def _read(kind: str) -> dict:
    try:
        got = json.loads(path(kind).read_text())
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _write(kind: str, rows: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        p = path(kind)
        tmp = p.with_suffix(f".{__import__('os').getpid()}.tmp")
        tmp.write_text(json.dumps(rows))
        tmp.replace(p)
    except OSError:
        pass


def _norm(symbol: str) -> str:
    """One spelling for a pair, whichever the caller has.

    The store uses BOTH: the sweep and the download hold `CETUS_USDT`, while
    `cloud_sweep.collect_into_store` and the row files hold the bare `CETUS`.
    Recording under one and clearing under the other means nothing ever comes
    off the books — every landed pair would stay "pending" for ever. Normalised
    HERE rather than at each call site, because the next caller would get it
    wrong too.
    """
    s = str(symbol or "").strip().upper()
    return s if s.endswith("_USDT") else f"{s}_USDT"


def _key(symbol: str, tf: str) -> str:
    return f"{_norm(symbol)}|{tf}"


def record(kind: str, failures, *, run: str = "", now: float | None = None) -> int:
    """Put failed pairs on the books. `failures` is (symbol, tf, why) triples.

    A pair already on the books keeps its FIRST-SEEN time and gains a count —
    "failed once yesterday" and "failed on every run for a week" are different
    problems and the panel should be able to tell them apart.
    """
    now = time.time() if now is None else now
    rows = _read(kind)
    added = 0
    for item in failures or []:
        try:
            sym, tf, why = item
        except (TypeError, ValueError):
            continue
        if not sym or not tf:
            continue
        k = _key(sym, tf)
        was = rows.get(k) or {}
        if not was:
            added += 1
        rows[k] = {"symbol": _norm(sym), "timeframe": tf,
                   "why": str(why)[:WHY_MAX],
                   "first": was.get("first") or now,
                   "last": now,
                   "fails": int(was.get("fails") or 0) + 1,
                   "run": run or was.get("run") or ""}
    _write(kind, rows)
    return added


def clear(kind: str, pairs) -> int:
    """Take pairs OFF the books because they succeeded.

    Called with everything a run measured or fetched, not only the pairs it was
    retrying: a pair fixed by an unrelated whole-market run is fixed.
    """
    rows = _read(kind)
    gone = 0
    for item in pairs or []:
        try:
            sym, tf = item[0], item[1]
        except (TypeError, IndexError):
            continue
        if rows.pop(_key(sym, tf), None) is not None:
            gone += 1
    if gone:
        _write(kind, rows)
    return gone


def pending(kind: str) -> list[dict]:
    """Every pair still on the books, worst first (most failures, then oldest).

    Worst first because a pair that has failed nine times is telling you
    something a pair that failed once is not.
    """
    rows = list((_read(kind)).values())
    rows.sort(key=lambda r: (-int(r.get("fails") or 0), float(r.get("first") or 0)))
    return rows


def count(kind: str) -> int:
    return len(_read(kind))


def summary(kind: str) -> dict:
    """What the panel shows: the count, and the pairs NAMED (never a bare
    number — CLAUDE.md: every pair still lost is named)."""
    from tradingagents.positions_view import fmt_when

    rows = pending(kind)
    return {
        "kind": kind,
        "count": len(rows),
        "pairs": [{"symbol": r.get("symbol"), "timeframe": r.get("timeframe"),
                   "why": r.get("why"), "fails": r.get("fails"),
                   "first": fmt_when(r.get("first")),
                   "last": fmt_when(r.get("last"))}
                  for r in rows],
    }
