"""What is PENDING and what went WRONG — the backtest screen's LOGS section.

Operator, 2026-09-03: *"if there is error create a seperate section called logs
just like in candles module si i can see what is pending on my side and what are
errors"*. The candles screen names every pair it lost and every pair it can
never fetch; the backtest screen counted its failures and named at most three,
so an update that failed on 860 pairs read as `done: 860, rows: 0`.

Everything here is cheap enough to poll: PENDING comes from two DIRECTORY
LISTINGS (candle files against state files — names only, nothing parsed), never
from `candle_coverage()`, which reads every candle file and takes minutes on a
5,131-pair store.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# how long a pending count is reused. The panel polls every few seconds; the
# listing is two globs over ~9,500 names, which is cheap but not free.
PENDING_CACHE_S = 20.0
_PENDING: dict = {"at": 0.0, "payload": None}

# how many pairs a list names before it says "and N more". The operator has to
# be able to READ it; the count is always exact.
NAME_LIMIT = 40


def _fmt(ts) -> str:
    """The one date format (CLAUDE.md): Aug 03, 2026 8:03pm."""
    from tradingagents.positions_view import fmt_when

    try:
        return fmt_when(float(ts)) if ts else ""
    except Exception:                                          # noqa: BLE001
        return ""


def pending_pairs() -> list[tuple[str, str]]:
    """EVERY pending (symbol, timeframe) — the full list, not the sample.

    `pending()` names only the first `NAME_LIMIT` for the panel. An ACTION on
    the pendings (the RESOLVE PENDING button) has to see all of them, or it
    reports on a truncated slice of its own work.
    """
    from tradingagents import market_sweep as msw

    measured = {f.stem for f in msw.STATES.glob("*.json")}
    out = []
    for f in msw.CANDLES.glob("*.json"):
        try:
            sym, tf = f.stem.rsplit("-", 1)
        except ValueError:
            continue
        if f"{sym.replace('_USDT', '')}-{tf}" not in measured:
            out.append((sym, tf))
    return sorted(out)


_FLEET = {"at": 0.0, "symbols": None}


def fleet_symbols(max_age_s: float = 300.0):
    """Every contract a GitHub SHARD would sweep, or None when the venue could
    not be asked.

    THE SHARD'S OWN RULE, verbatim (`sweep_shard.py`): `state == 0`, quote
    USDT — NOT `db_jobs.live_symbols`, which also drops `apiAllowed=False`
    contracts. Those are listed and shard-reachable: using the download list
    here called 50 pairs unreachable when only 24 were (Sep 06, 2026). None
    is never an empty set: "could not look" must not uncount everything.
    """
    from tradingagents.dataflows import mexc_futures as fx

    now = time.time()
    if _FLEET["symbols"] is not None and now - _FLEET["at"] < max_age_s:
        return _FLEET["symbols"]
    try:
        raw = fx._get_public(f"{fx.BASE}/api/v1/contract/detail").get("data") or []
        got = {str(x["symbol"]) for x in raw
               if str(x.get("symbol", "")).endswith("_USDT")
               and int(x.get("state", 1)) == 0}
    except Exception:                                          # noqa: BLE001
        return None
    if not got:
        return None
    _FLEET.update(at=now, symbols=got)
    return got


def pending(force: bool = False) -> dict:
    """Pairs this machine holds candles for but has NEVER measured.

    A pair is measured when it has a state file — `market_sweep` writes one per
    (coin, timeframe) and keeps its watermark there. Measured on this store:
    5,131 candle pairs, 4,399 state files, so 732 pending.
    """
    from tradingagents import market_sweep as msw

    now = time.time()
    if not force and _PENDING["payload"] and now - _PENDING["at"] < PENDING_CACHE_S:
        return _PENDING["payload"]

    stored: set = set()
    for f in msw.CANDLES.glob("*.json"):
        try:
            sym, tf = f.stem.rsplit("-", 1)
        except ValueError:
            continue
        stored.add((sym, tf))
    # ONE definition of "pending", shared with the RESOLVE PENDING button.
    # Both used to walk the two directories themselves, and two copies of a
    # rule is one rule waiting to drift — the button would then have reported
    # a split of a set the badge beside it did not agree with.
    missing = pending_pairs()
    # DELISTED contracts are NAMED, never counted (Sep 06, 2026). 24 of the
    # 677 pending sat on coins MEXC no longer lists (ASP, BULLCOIN, CZ, DRV,
    # MEZO, ST): GitHub shards build their coin lists from the live venue so
    # no fleet can reach them, this PC no longer sweeps, and even a hand-run
    # dies walking their order book — a delisted contract has no live costs,
    # so its rows would be fiction on fees (rule 9). The candles module made
    # the same call for the same coins on 2026-08-27: named and skipped,
    # never queued again. An UNREADABLE venue list keeps every pair counted
    # ("a failed age check KEEPS the coin") — is_delisted returns False then.
    live = fleet_symbols()
    gone = ([] if live is None
            else [(s, t) for s, t in missing if s not in live])
    missing = [p for p in missing if p not in set(gone)]
    # NEVER MEASURED is not the same as MEASURABLE. A pair needs
    # `backtest_report.MIN_BARS[tf]` candles before any sweep produces a row —
    # 500 on 15m/30m/1h/4h, 60 on 1d — and a young contract has plenty of 15m
    # bars and almost no 4h ones. Measured Sep 06, 2026: of 677 never-measured
    # pairs, 649 were UNDER their floor and only 28 above it, and every short
    # one was JUST under (4h 493 of 500, 1h 490, 1d 59 of 60).
    #
    # Counting all 677 made the badge a promise nothing could keep: RESOLVE
    # PENDING would send twenty runners for an hour to measure 28 pairs and
    # the number would sit at 649 for ever, reading as a broken button instead
    # of as a store with young contracts in it. Same rule as the delisted
    # split above — counted out loud, never silently dropped (rule 20).
    #
    # `scan=False` on purpose: this answers an HTTP poll, and an incremental
    # scan of 5,000 candle files takes a minute while a download runs.
    from tradingagents import backtest_report as _br

    try:
        idx = msw.candle_index(scan=False) or {}
    except Exception:                                          # noqa: BLE001
        idx = {}
    short, ready = [], []
    for sym, t in missing:
        e = idx.get(f"{sym}-{t}") if idx else None
        floor = _br.MIN_BARS.get(t, 500)
        bars = int((e or {}).get("bars") or 0)
        # NO index entry means UNKNOWN, and unknown stays measurable: refusing
        # to try is worse than trying and finding out (the age-check rule).
        (short if e and bars < floor else ready).append((sym, t, bars, floor))

    def _tally(rows, i=1):
        out: dict = {}
        for r in rows:
            out[r[i]] = out.get(r[i], 0) + 1
        return out

    by_tf: dict = {}
    for _s, t in missing:
        by_tf[t] = by_tf.get(t, 0) + 1
    payload = {
        "stored": len(stored), "measured": len(stored) - len(missing) - len(gone),
        "count": len(missing), "by_timeframe": by_tf,
        # what a sweep can actually do — what RESOLVE PENDING promises
        "measurable": len(ready), "measurable_by_timeframe": _tally(ready),
        # and what it never will, with the reason attached to each pair
        "too_short": len(short), "too_short_by_timeframe": _tally(short),
        "too_short_pairs": [{"symbol": s, "timeframe": t, "bars": b,
                             "floor": f} for s, t, b, f in short[:NAME_LIMIT]],
        "pairs": [{"symbol": s, "timeframe": t} for s, t in missing[:NAME_LIMIT]],
        "unnamed": max(0, len(missing) - NAME_LIMIT),
        # counted OUT LOUD (rule 20): the panel prints these beside the count
        "delisted": len(gone),
        "delisted_coins": sorted({s.replace("_USDT", "") for s, _t in gone}),
        "checked": _fmt(now),
    }
    _PENDING.update(at=now, payload=payload)
    return payload


def _read(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _job_errors(kind: str) -> list:
    """Every pair a local job named, from its progress file.

    `failed` is a list of `"SYM tf: message"` — written by `_run_backtest_inner`
    since 2026-09-03, when 860 silent failures read as a run with nothing to do.
    """
    from tradingagents import db_jobs as dj

    st = _read(dj.FILES[kind]["progress"])
    when = _fmt(st.get("finished") or st.get("started"))
    out = []
    for line in (st.get("failed") or []):
        sym, _, text = str(line).partition(":")
        out.append({"where": "this PC", "job": kind, "when": when,
                    "pair": sym.strip(), "text": text.strip() or str(line)})
    # a run that failed as a WHOLE (MemoryError, a bad spec) names itself here
    if st.get("error"):
        out.append({"where": "this PC", "job": kind, "when": when,
                    "pair": "", "text": str(st["error"])})
    return out


def _cloud_errors(limit: int = 200) -> tuple[list, dict]:
    """What the GitHub shards lost, read from the progress branch (no API).

    Returns the rows and a small status block, so an unreadable branch is
    reported as unreadable rather than as "no errors" — the panel must never
    show a green count it did not earn.
    """
    from tradingagents import cloud_sweep as cs

    try:
        slug = cs.repo_slug()
        runs = cs._runs(slug, limit=1)
    except Exception as exc:                                   # noqa: BLE001
        return [], {"ok": False, "why": f"{type(exc).__name__}: {exc}"}
    if not runs:
        return [], {"ok": True, "why": "no run yet", "run": None}
    run = runs[0]
    try:
        shards = cs.live_progress(run["databaseId"], slug)
    except Exception as exc:                                   # noqa: BLE001
        return [], {"ok": False, "why": f"{type(exc).__name__}: {exc}",
                    "run": run["databaseId"]}
    out = []
    for sh in shards:
        for line in (sh.get("failed") or []):
            sym, _, text = str(line).partition(":")
            out.append({"where": f"GitHub shard {sh.get('shard')}",
                        "job": "cloud", "when": sh.get("updated", ""),
                        "pair": sym.strip(), "text": text.strip() or str(line)})
    return out[:limit], {
        "ok": True, "run": run["databaseId"], "url": run.get("url"),
        "status": run.get("status"), "shards": len(shards),
        # a shard that has not reported cannot be read for failures; saying so
        # keeps "0 errors" honest
        "silent": max(0, 20 - len(shards)),
    }


def logs(include_cloud: bool = True) -> dict:
    """Everything the LOGS section shows: pending work, then errors."""
    errs = _job_errors("backtest") + _job_errors("btupdate")
    cloud: dict = {"ok": True, "why": "not asked for"}
    if include_cloud:
        c, cloud = _cloud_errors()
        errs += c
    from tradingagents import db_jobs as dj

    return {
        "pending": pending(),
        "errors": errs[:NAME_LIMIT * 5],
        "error_count": len(errs),
        "cloud": cloud,
        "plan": _read(dj.STATE_DIR / "db_btupdate.plan.json"),
        "checked": _fmt(time.time()),
    }
