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


# ---------------------------------------------------------------- deploy diff
_TF_NAME = {"Min1": "1m", "Min15": "15m", "Min30": "30m", "Min60": "1h",
            "Hour4": "4h", "Day1": "1d"}


def _sig_of(key: str) -> str:
    """The signal name inside a strategy key ('mom15_4h_w' -> 'mom15')."""
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
