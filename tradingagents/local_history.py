"""Deployment history on THIS MACHINE — no database anywhere.

The operator's instruction, twice: "i said i want all local machine", then
"i told you that its pure local". Config files overwrite, so what was live
must be recorded somewhere append-only; that somewhere is a jsonl file beside
the ledger, not a cloud table.

One line per change. Identical re-saves collapse by content hash; two
different edits in the same second both survive (the bug the Neon table had
and fixed — the fix carries over here).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

DEPLOY_LOG = Path(os.path.expanduser("~/.tradingagents/deployments.jsonl"))

FIELDS = ("changed_at", "strategy_key", "symbol", "action", "timeframe",
          "signal", "threshold", "tp", "sl", "sizing", "books",
          "base_margin", "ladder_step", "row_code", "prev_json", "note")


def _change_id(row: dict) -> str:
    seed = json.dumps({k: row.get(k) for k in FIELDS if k != "changed_at"},
                      sort_keys=True, default=str)
    return hashlib.blake2s(seed.encode(), digest_size=8).hexdigest()


def record_deployment(entry: dict) -> int:
    """Append one change. Returns 1 when written, 0 when refused or identical
    to the immediately previous record for the same strategy+coin."""
    row = {k: entry.get(k) for k in FIELDS}
    row["changed_at"] = int(row.get("changed_at") or time.time())
    if not (row.get("strategy_key") and row.get("symbol")
            and row.get("action")):
        return 0
    row["change_id"] = _change_id(row)
    # a Streamlit rerun re-saves the same config seconds apart; the same
    # CONTENT for the same strategy+coin is one piece of history, not two
    for old in reversed(deployments(limit=200)):
        if (old.get("strategy_key") == row["strategy_key"]
                and old.get("symbol") == row["symbol"]):
            if old.get("change_id") == row["change_id"]:
                return 0
            break
    DEPLOY_LOG.parent.mkdir(parents=True, exist_ok=True)
    with DEPLOY_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return 1


def deployments(symbol: str | None = None, limit: int = 200) -> list[dict]:
    """What was live, newest first."""
    try:
        lines = DEPLOY_LOG.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if symbol and d.get("symbol") != symbol:
            continue
        out.append(d)
    out.sort(key=lambda d: -(d.get("changed_at") or 0))
    return out[:limit]


def armed_since() -> dict:
    """`{"strategy_key|SYMBOL": unix_seconds}` — when the CURRENT arming began.

    The operator, `Sep 17, 2026`: *"i dont need ladder $ · flat column, instead
    put when was this strategies deployed"*.

    KEYED BY STRATEGY AND COIN, because that is what a row IS: the grid shows
    120 rows over 85 strategies, one per contract, and `macddiv_4h_sl25tp3` on
    STBL was armed on a different day from the same rule on another coin. A
    per-strategy answer would print one date on rows that started on two.

    NOT simply the newest `deployed` row. A pair can be deployed, disarmed and
    deployed again, and the honest answer to "when was this deployed" is when
    the run it is in NOW began — so a row armed since Sep 10 must not read
    Sep 16 because somebody edited its margin that day.

    So: walk the log OLDEST first. A `deployed` starts the clock only if it is
    not already running (`setdefault`). A `disarmed` stops it, because the next
    `deployed` is a new run. A `changed` is ignored on purpose — editing a
    margin does not redeploy anything, and counting it would show "deployed 2
    minutes ago" on a strategy that has been running for a week.

    A pair the log has never seen is absent, and the screen prints a dash
    rather than inventing a date.
    """
    since: dict = {}
    for row in reversed(deployments(limit=1_000_000)):     # oldest first
        key, sym, action = (row.get("strategy_key"), row.get("symbol"),
                            row.get("action"))
        if not key or not sym:
            continue
        pair = f"{key}|{sym}"
        if action == "disarmed":
            since.pop(pair, None)
        elif action == "deployed" and int(row.get("changed_at") or 0) > 0:
            since.setdefault(pair, int(row["changed_at"]))
    return since


# ---------------------------------------------------------------- deploy diff
_TF_NAME = {"Min1": "1m", "Min15": "15m", "Min30": "30m", "Min60": "1h",
            "Hour4": "4h", "Day1": "1d"}


_UNDERSCORED_SIGNALS: tuple = ()


def _sig_of(key: str) -> str:
    """The signal name inside a strategy key ('mom15_4h_w' -> 'mom15').

    THE ONE PARSER — every module that needs a key's signal calls this.

    A SIGNAL NAME MAY CONTAIN AN UNDERSCORE (RCA-2026-09-24-G): `cf_soup1`,
    `cx_veto`, `sr_break` and 54 more in `backtest_report.SIGNALS`. Splitting
    on the first `_` read `cf_soup1_1h_sl25tp1` as signal `cf`, so from
    Sep 16, 2026 1:54am the screen hashed FASTSTOCK's deployed row as
    #GYWZS995 — an id no store holds — instead of #KDY5M3LQ. The longest
    registered name that prefixes the key wins, which is how
    `auto_trader.signal_for` dispatches; a key naming no underscored signal
    reads exactly as it always did.
    """
    global _UNDERSCORED_SIGNALS
    if not _UNDERSCORED_SIGNALS:
        from tradingagents.backtest_report import SIGNALS

        _UNDERSCORED_SIGNALS = tuple(sorted((s for s in SIGNALS if "_" in s),
                                            key=len, reverse=True))
    for name in _UNDERSCORED_SIGNALS:
        if key == name or key.startswith(name + "_"):
            return name
    parts = key.split("_")
    return parts[1] if parts and parts[0] == "ict" and len(parts) > 1 else parts[0]


def deploy_diff(old: dict, new: dict) -> list[dict]:
    """What changed about what is LIVE, one entry per strategy/coin.

    Config files overwrite; this is the record of what was running when.
    Ported from the Streamlit layer so the API layer shares one diff.
    """
    from tradingagents import auto_trader as at

    out = []
    keys = set(list(old.get("strategy_books") or {})
               + list(new.get("strategy_books") or {}))
    for k in sorted(keys):
        ob = list((old.get("strategy_books") or {}).get(k) or [])
        nb = list((new.get("strategy_books") or {}).get(k) or [])
        oc = list((old.get("strategy_coins") or {}).get(k) or [])
        nc = list((new.get("strategy_coins") or {}).get(k) or [])
        om = (old.get("strategy_margins") or {}).get(k)
        nm = (new.get("strategy_margins") or {}).get(k)
        if ob == nb and oc == nc and om == nm:
            continue
        spec = at.STRATEGY_SPECS.get(k) or {}
        action = ("disarmed" if nb == [] and ob else
                  "deployed" if nb and not ob else "changed")
        for coin in (nc or oc or ["—"]):
            out.append({
                "strategy_key": k, "symbol": coin, "action": action,
                "timeframe": _TF_NAME.get(spec.get("interval")),
                "signal": _sig_of(k),
                "threshold": round(float(spec.get("threshold") or 0) * 100, 3),
                "tp": round(float(spec.get("tp", 0)) * 100, 3),
                "sl": round(float(spec.get("sl", 0)) * 100, 3),
                "sizing": at.sizing_for(new),
                "books": ",".join(nb), "base_margin": nm,
                "prev_json": json.dumps({"books": ob, "coins": oc,
                                         "base_margin": om}),
            })
    return out


SETTINGS_SNAPSHOTS = Path(os.path.expanduser("~/.tradingagents"))
_SNAP_CACHE: dict = {"stamp": None, "value": {}}


def _snapshots() -> list[tuple[int, Path]]:
    """Every saved copy of the settings file, oldest first, with its time.

    `auto_trade.json.before-percoin-1789542032` carries the moment it was
    taken in its own name; anything without one falls back to the file's
    modified time. The LIVE file counts as the newest snapshot, so a pair
    added since the last backup is still datable.
    """
    out: list[tuple[int, Path]] = []
    for f in SETTINGS_SNAPSHOTS.glob("auto_trade.json*"):
        if f.suffix in (".lock", ".WANT") or f.name.endswith(".pid"):
            continue
        stamp = 0
        tail = f.name.rsplit("-", 1)[-1]
        if tail.isdigit() and len(tail) >= 9:
            stamp = int(tail)
        if not stamp:
            try:
                stamp = int(f.stat().st_mtime)
            except OSError:
                continue
        out.append((stamp, f))
    out.sort()
    return out


def first_seen_in_settings() -> dict:
    """`{"strategy_key|SYMBOL": (seen_at, searched_from)}` from the settings
    backups — the fallback for a row the deploy log never saw.

    The operator, `Sep 17, 2026`: *"fill up the deployed date column now i
    want the value when i did added this strategy"*. The column was blank on
    **113 of 120 rows**, because `deployments.jsonl` is written by the SAVE
    path and those 113 were deployed by writing the settings file directly —
    the 280 ids they pasted on `Sep 16, 2026`. A log that never saw an event
    cannot date it.

    Their own backups can. Walking them oldest first, the FIRST copy that
    contains a pair puts an upper bound on when it was added, and the copy
    before it puts a lower bound. Measured on this machine: the pair count
    goes 35 (`Sep 16, 1:42am`) → 133 (`1:54am`), so those pairs were added
    inside a twelve-minute window and `1:54am` is the honest answer with
    `1:42am` as the other end.

    Both numbers are returned so the screen can say which it is. **Never
    return the upper bound alone** — printing a bound as if it were a fact is
    exactly the false label this project keeps paying for.

    Cached on the snapshot list and their sizes, because the grid polls every
    five seconds and this opens every backup.
    """
    snaps = _snapshots()
    try:
        stamp = tuple((t, f.name, f.stat().st_size) for t, f in snaps)
    except OSError:
        stamp = tuple((t, f.name) for t, f in snaps)
    if _SNAP_CACHE["stamp"] == stamp:
        return dict(_SNAP_CACHE["value"])
    seen: dict = {}
    prev = 0
    for when, path in snaps:
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key, coins in (cfg.get("strategy_coins") or {}).items():
            for coin in (coins or []):
                seen.setdefault(f"{key}|{coin}", (when, prev))
        prev = when
    _SNAP_CACHE["stamp"] = stamp
    _SNAP_CACHE["value"] = dict(seen)
    return seen


def deployed_at() -> dict:
    """`{"strategy_key|SYMBOL": {"at": secs, "from": secs|None}}` — when each
    deployed row was added, for the grid's DEPLOYED column.

    The deploy log WINS wherever it has an answer: it recorded a real event at
    a real second, so `"from"` is None and the screen prints the date plainly.
    Everything else falls back to the settings backups, where `"at"` is the
    first copy holding that pair and `"from"` is the copy before it — a
    window, and the screen has to say so.
    """
    out: dict = {}
    for pair, (at_, from_) in first_seen_in_settings().items():
        out[pair] = {"at": int(at_), "from": int(from_) or None}
    for pair, at_ in armed_since().items():
        out[pair] = {"at": int(at_), "from": None}
    return out
