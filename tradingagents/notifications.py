"""Event feed on THIS MACHINE — a local SQLite file, no cloud table.

The operator's standing rule, recorded twice in local_history.py: "i said i
want all local machine", "i told you that its pure local". So this is
~/.tradingagents/notifications.db, beside the ledger, not a Neon table.

What lands here: a download finishing or failing, a backtest finishing or
failing, a position opening or closing. The point is the operator can look at
one bell and see whether the thing they clicked actually worked — a click that
reports nothing is indistinguishable from a click that silently failed, which
is exactly what happened with the 0-byte backtest report on 2026-08-20.

SAFETY: every public function swallows its own errors. This module is called
from the live trading loop, and a notification failing to write must never be
able to interrupt an order, a stop, or an exit.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(os.path.expanduser("~/.tradingagents/notifications.db"))

# The kinds the UI knows how to draw. Anything else still stores fine.
KINDS = ("download", "backtest", "trade_open", "trade_close", "error")

_DDL = """
CREATE TABLE IF NOT EXISTS events (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts       REAL    NOT NULL,
  kind     TEXT    NOT NULL,
  ok       INTEGER NOT NULL DEFAULT 1,
  title    TEXT    NOT NULL,
  detail   TEXT    NOT NULL DEFAULT '',
  meta     TEXT    NOT NULL DEFAULT '{}',
  read_at  REAL
);
CREATE INDEX IF NOT EXISTS events_ts   ON events(ts DESC);
CREATE INDEX IF NOT EXISTS events_kind ON events(kind, ts DESC);
CREATE INDEX IF NOT EXISTS events_read ON events(read_at);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # WAL so the runner writing an event never blocks the API reading them.
    cx = sqlite3.connect(DB_PATH, timeout=5.0)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA journal_mode=WAL")
    cx.executescript(_DDL)
    return cx


def record(kind: str, title: str, *, detail: str = "", ok: bool = True,
           meta: dict | None = None) -> int:
    """Append one event. Returns its id, or 0 if it could not be stored.

    NEVER raises: called from the trading loop.
    """
    try:
        with _conn() as cx:
            cur = cx.execute(
                "INSERT INTO events (ts, kind, ok, title, detail, meta) "
                "VALUES (?,?,?,?,?,?)",
                (time.time(), str(kind), 1 if ok else 0, str(title)[:200],
                 str(detail)[:500], json.dumps(meta or {})[:2000]))
            return int(cur.lastrowid or 0)
    except Exception:
        return 0


def recent(limit: int = 30, kind: str | None = None,
           unread_only: bool = False) -> list[dict]:
    """Newest first. Returns [] rather than raising if the store is unusable."""
    try:
        q = "SELECT * FROM events"
        where, args = [], []
        if kind:
            where.append("kind = ?")
            args.append(kind)
        if unread_only:
            where.append("read_at IS NULL")
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        with _conn() as cx:
            rows = cx.execute(q, args).fetchall()
        out = []
        for r in rows:
            try:
                meta = json.loads(r["meta"] or "{}")
            except Exception:
                meta = {}
            out.append({"id": r["id"], "ts": r["ts"], "kind": r["kind"],
                        "ok": bool(r["ok"]), "title": r["title"],
                        "detail": r["detail"], "meta": meta,
                        "read": r["read_at"] is not None})
        return out
    except Exception:
        return []


def unread_count() -> int:
    try:
        with _conn() as cx:
            return int(cx.execute(
                "SELECT COUNT(*) FROM events WHERE read_at IS NULL"
            ).fetchone()[0])
    except Exception:
        return 0


def mark_read(ids: list[int] | None = None) -> int:
    """Mark the given ids read, or ALL when ids is None. Returns rows changed."""
    try:
        with _conn() as cx:
            if ids:
                qs = ",".join("?" * len(ids))
                cur = cx.execute(
                    f"UPDATE events SET read_at=? WHERE read_at IS NULL "
                    f"AND id IN ({qs})", [time.time(), *[int(i) for i in ids]])
            else:
                cur = cx.execute(
                    "UPDATE events SET read_at=? WHERE read_at IS NULL",
                    (time.time(),))
            return int(cur.rowcount or 0)
    except Exception:
        return 0


def prune(keep: int = 2000) -> int:
    """Keep the newest `keep` events. A feed is not an archive — the ledger is."""
    try:
        with _conn() as cx:
            cur = cx.execute(
                "DELETE FROM events WHERE id NOT IN "
                "(SELECT id FROM events ORDER BY ts DESC LIMIT ?)", (keep,))
            return int(cur.rowcount or 0)
    except Exception:
        return 0
