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
    # state files are keyed on the COIN (no _USDT); candle files on the SYMBOL
    measured = set()
    for f in msw.STATES.glob("*.json"):
        try:
            coin, tf = f.stem.rsplit("-", 1)
        except ValueError:
            continue
        measured.add((coin, tf))

    missing = sorted((s, t) for s, t in stored
                     if (s.replace("_USDT", ""), t) not in measured)
    by_tf: dict = {}
    for _s, t in missing:
        by_tf[t] = by_tf.get(t, 0) + 1
    payload = {
        "stored": len(stored), "measured": len(stored) - len(missing),
        "count": len(missing), "by_timeframe": by_tf,
        "pairs": [{"symbol": s, "timeframe": t} for s, t in missing[:NAME_LIMIT]],
        "unnamed": max(0, len(missing) - NAME_LIMIT),
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
