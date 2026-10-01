"""The errors of every trading room, for Backtest -> Errors -> Deployed Tabs.

Operator, Oct 01, 2026: *"can you create a tab called 'Errors' then create a
section Named 'Deployed Tabs' there i should see errors ... i want it under
backtest tab"* — asked right after *"can you check if there has been outage
for the tabs"*, which took a person reading nine log files to answer.

WHAT IS AN ERROR HERE, and what is not:

* ERRORS — something went wrong that nobody chose: MEXC refused for asking
  too often (code 510), a cycle failed (no candles), a price or an order book
  could not be read, a Python exception, the room's runner (re)started, the
  log went quiet for longer than `QUIET_S` while the room had been working,
  or the room's watcher reported a failure.
* SAFETY REFUSALS — the runner declining a trade ON PURPOSE: the cost check
  (LIQUIDITY GATE on cost), the chase guard, a stale signal, a coin on two
  timeframes. They are counted beside the errors, never listed among them —
  #4FC03172 wrote 26,613 cost refusals in its first 14 hours and three real
  rate-limit errors; listed together the three are invisible.

Read where the data is (CLAUDE.md, kit item G): the API filters and pages,
the screen never receives the whole list. Each log is read once, then only
the bytes appended since (`_Tail`), so a 30-second poll costs nothing; the
first read of a log larger than `FIRST_READ_BYTES` starts that far from its
end, and every answer says which span it covers (`examined`).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading
from pathlib import Path

from tradingagents import profiles

FIRST_READ_BYTES = 64 * 1024 * 1024
QUIET_S = 10 * 60
PER_PAGE = 25

_LINE = re.compile(r"^([A-Z][a-z]{2} \d{2}, \d{4} \d{1,2}:\d{2}[ap]m) (\w+) (.*)")

# ONE table, in the order tried: the first pattern that matches names the line
ERROR_KINDS = (
    ("rate_limit", "MEXC said too many requests",
     re.compile(r"code.?=?\s?510\b|Requests are too frequent", re.I)),
    ("book_unreadable", "Order book could not be read",
     re.compile(r"order book could not be read", re.I)),
    ("no_price", "No live price", re.compile(r"no live price", re.I)),
    ("cycle_failed", "A check failed", re.compile(r"cycle failed", re.I)),
    ("exception", "Program error", re.compile(r"Traceback|\bException\b|\w+Error\b")),
    ("venue_error", "MEXC refused", re.compile(r"\bcode[ =]\d{3,5}\b", re.I)),
)
SAFETY_KINDS = (
    # both cost checks: the one before the order (LIQUIDITY) and the second
    # look just before it is sent (ENTRY) — refusals by design either way
    ("cost_gate", "cost check", re.compile(r"(?:LIQUIDITY|ENTRY) GATE: refusing .* round-trip cost")),
    ("chase", "price ran away", re.compile(r"CHASE GUARD")),
    ("stale", "old signal", re.compile(r"STALE SIGNAL")),
    ("two_timeframes", "coin on two timeframes", re.compile(r"REFUSING TO TRADE .* at once")),
)
EXTRA_KINDS = {"other_error": "Other error", "restart": "Runner started again",
               "quiet": "Runner went quiet", "watcher": "Watcher problem"}
LABELS = {k: lab for k, lab, _ in ERROR_KINDS} | EXTRA_KINDS


def _fmt(ts: float) -> str:
    from tradingagents.positions_view import fmt_when

    return fmt_when(ts)


def _when(s: str) -> float:
    return dt.datetime.strptime(s, "%b %d, %Y %I:%M%p").timestamp()


def _norm(msg: str) -> str:
    """The message with its numbers and times taken out — what groups the
    9,078 'no Min60 candles for CHYMSTOCK_USDT' lines into one row."""
    m = re.sub(r"[A-Z][a-z]{2} \d{2}, \d{4} \d{1,2}:\d{2}[ap]m", "<time>", msg)
    return re.sub(r"[-+]?\d[\d.,]*%?", "#", m)[:240]


def classify(level: str, msg: str) -> tuple[str, str]:
    """('error', kind) | ('safety', kind) | ('', '') for an ordinary line."""
    for kind, _lab, rx in SAFETY_KINDS:
        if rx.search(msg) and "could not be read" not in msg:
            return "safety", kind
    for kind, _lab, rx in ERROR_KINDS:
        if rx.search(msg):
            return "error", kind
    if level in ("ERROR", "CRITICAL"):
        return "error", "other_error"
    return "", ""


class _Tail:
    """One room's log, read once and then only its new bytes."""

    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.events: list = []          # (ts, kind, key, example)
        self.safety: list = []          # (ts, kind)
        self.lines: list = []           # (ts) of every scan line, for quiet gaps
        self.first: float | None = None
        self.last: float | None = None
        self.partial = b""

    def update(self) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self.offset:          # rotated or rewritten: start again
            self.__init__(self.path)
        if not self.offset and size > FIRST_READ_BYTES:
            self.offset = size - FIRST_READ_BYTES
            skip_first = True
        else:
            skip_first = False
        if size == self.offset:
            return
        with self.path.open("rb") as fh:
            fh.seek(self.offset)
            data = self.partial + fh.read(size - self.offset)
        self.offset = size
        lines = data.split(b"\n")
        self.partial = lines.pop()       # an unfinished last line waits
        if skip_first and lines:
            lines.pop(0)                 # started mid-line
        for raw in lines:
            m = _LINE.match(raw.decode("utf-8", "replace").rstrip("\r"))
            if not m:
                continue
            try:
                ts = _when(m.group(1))
            except ValueError:
                continue
            self.first = ts if self.first is None else self.first
            self.last = ts
            # QUIET is measured between SCANS only: a room with nothing
            # switched on logs nothing, and that is idle, not an outage
            # (#CC94D9FB "went quiet" for 64 minutes before its first rows)
            if m.group(3).startswith("scan "):
                self.lines.append(ts)
            what, kind = classify(m.group(2), m.group(3))
            if what == "error":
                self.events.append((ts, kind, _norm(m.group(3)), m.group(3)[:400]))
            elif what == "safety":
                self.safety.append((ts, kind))


_TAILS: dict = {}
_LOCK = threading.Lock()


def _log_path(pid: str) -> Path:
    from tradingagents import auto_trader as at

    with profiles.using(pid):
        return Path(at._pp(at.LOG_PATH))


def _ledger_path(pid: str) -> Path:
    from tradingagents import auto_trader as at

    with profiles.using(pid):
        return Path(at._pp(at.LEDGER_PATH))


_STARTS: dict = {}            # pid -> {"path", "offset", "starts": [ts...]}


def _restarts(pid: str) -> list:
    """Every `runner_start` in the room's trade record after its first one:
    a runner that had to be started again. Read once, then only what was
    appended (the record grows by tens of thousands of rows a day)."""
    path = _ledger_path(pid)
    st = _STARTS.get(pid)
    if st is None or st["path"] != path:
        st = _STARTS[pid] = {"path": path, "offset": 0, "starts": [], "partial": b""}
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size < st["offset"]:
        st.update(offset=0, starts=[], partial=b"")
    if size > st["offset"]:
        with path.open("rb") as fh:
            fh.seek(st["offset"])
            data = st["partial"] + fh.read(size - st["offset"])
        st["offset"] = size
        lines = data.split(b"\n")
        st["partial"] = lines.pop()
        for line in lines:
            if b'"runner_start"' not in line:
                continue
            try:
                st["starts"].append(float(json.loads(line).get("ts") or 0))
            except ValueError:
                continue
    return st["starts"][1:]


def _quiet(lines: list, now: float, alive: bool) -> list:
    """(start, end) of every stretch longer than QUIET_S between two scans
    — and up to now, when the runner is not running."""
    out = [(a, b) for a, b in zip(lines, lines[1:]) if b - a > QUIET_S]
    if lines and not alive and now - lines[-1] > QUIET_S:
        out.append((lines[-1], now))
    return out


def _watcher_problem(pid: str) -> list:
    from tradingagents import strategy_watcher as sw

    try:
        with profiles.using(pid):
            st = sw._read()
    except Exception:                                          # noqa: BLE001
        return []
    why = str(st.get("why") or "")
    if "failed" in why:
        return [(float(st.get("last_on_try") or st.get("last_off_pass") or 0), why)]
    return []


def _alive(pid: str) -> bool:
    from tradingagents import auto_trader as at

    with profiles.using(pid):
        return at.runner_pid() is not None


def report(*, room: str | None = None, kind: str | None = None, hours: float = 0,
           page: int = 1, per: int = PER_PAGE, now: float | None = None) -> dict:
    """The grouped errors of every SHOWN room (a retired room has no tab),
    filtered HERE and paged HERE."""
    import time

    now = time.time() if now is None else now
    since = now - hours * 3600 if hours else 0.0
    rooms = [r for r in profiles.shown() if not room or r == room]
    groups: dict = {}
    per_room: list = []
    for pid in rooms:
        with _LOCK:
            t = _TAILS.get(pid)
            if t is None or t.path != _log_path(pid):
                t = _TAILS[pid] = _Tail(_log_path(pid))
            t.update()
        alive = _alive(pid)
        events = [e for e in t.events if e[0] >= since]
        for ts in _restarts(pid):
            if ts >= since:
                events.append((ts, "restart", "the runner was started again", "the runner was started again"))
        for a, b in _quiet([x for x in t.lines if x >= since], now, alive):
            mins = int((b - a) // 60)
            events.append((b, "quiet", "no price check",
                           f"no price check for {mins} minutes (from {_fmt(a)} to {_fmt(b)})"))
        for ts, why in _watcher_problem(pid):
            if ts >= since:
                events.append((ts, "watcher", _norm(why), why[:400]))
        n_err = 0
        for ts, k, key, example in events:
            if kind and k != kind:
                continue
            n_err += 1
            g = groups.setdefault((pid, k, key), {"room": pid, "kind": k, "label": LABELS.get(k, k),
                                                  "message": example, "count": 0,
                                                  "first": ts, "last": ts})
            g["count"] += 1
            g["first"] = min(g["first"], ts)
            if ts >= g["last"]:
                g["last"], g["message"] = ts, example
        safety: dict = {}
        for ts, k in t.safety:
            if ts >= since:
                safety[k] = safety.get(k, 0) + 1
        per_room.append({"room": pid, "running": alive, "errors": n_err,
                         "last_error": max((e[0] for e in events
                                            if not kind or e[1] == kind), default=None),
                         "safety": safety,
                         "examined": {"from": max(t.first or 0, since) if t.first else None,
                                      "to": t.last}})
    rows = sorted(groups.values(), key=lambda g: -g["last"])
    pages = max(1, -(-len(rows) // per))
    page = min(max(1, int(page)), pages)
    return {"rows": rows[(page - 1) * per: page * per], "groups": len(rows),
            "events": sum(g["count"] for g in rows), "page": page, "pages": pages,
            "rooms": per_room, "kinds": [{"kind": k, "label": v} for k, v in LABELS.items()],
            "safety_labels": {k: lab for k, lab, _ in SAFETY_KINDS},
            "filters": {"room": room or "", "kind": kind or "", "hours": hours}}
