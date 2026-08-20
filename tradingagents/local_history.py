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
