"""What the operator pressed, what came back, and whether the two agree.

Operator, Sep 09, 2026: *"whenever i clicked apply filter and click download
csv you should be getting the logs of it so you can see the status"*.

They asked for this straight after telling me why the win-% bug survived:

    "you were reading the screen; I was reading the code"

Every filter fix in `docs/RCA.md` was verified by driving one filter and
reading the code around it. The 89.47% row under a "Winrate 90% or better"
chip was invisible to that, because each piece was correct on its own — the
floor filtered, the window re-measured — and the bug lived only in the
finished table. A human saw it in one second by looking at the RESULT.

So this module does what that glance does, on every press, in writing:

* `record()` appends ONE line per Apply and per CSV download — what was asked,
  what came back, how long it took;
* `disagreements()` re-tests every row that came back against every filter that
  was on, **using the figure the screen actually PRINTS** (the window's when the
  row was restated, the store's when it was not). Any row that fails is a
  MISMATCH, named with its id and its real value.

A MISMATCH line is the whole point. It is not a performance number or a stack
trace — it is the sentence "you asked for >= 90 and row #CGXLRJML on screen
says 89.47", written at the moment it happens, by the code that served it.

Nothing here may slow or break a request: one appended line, everything inside
try/except, and the log is capped by line count.
"""
from __future__ import annotations

import os
from pathlib import Path

from tradingagents.positions_view import fmt_when

LOG_PATH = Path(os.path.expanduser("~/.tradingagents")) / "screen.log"
# Keep the tail readable by hand. The operator presses these a few times a
# minute at most, and a line is ~200 bytes.
MAX_LINES = 4_000


# --------------------------------------------------------------- the checks
def _printed(row: dict, field: str):
    """The number the SCREEN shows for this field.

    A restated row prints its WINDOW figure (`w_winrate`), an unrestated one
    prints the store's. Checking the store's number on a restated row is the
    exact mistake that produced 89.47 under a 90% chip, so the check has to ask
    the same question the column does.
    """
    if row.get("restated") and f"w_{field}" in row:
        return row[f"w_{field}"]
    return row.get(field)


def disagreements(rows: list, asked: dict) -> list[str]:
    """Every way the rows on screen fail the filters that produced them.

    One sentence per broken filter, naming the count and the worst offenders.
    An empty list means the table agrees with its own chips.
    """
    out: list[str] = []
    rows = rows or []
    if not rows:
        return out

    def bad(field: str, test, label: str) -> None:
        hits = [r for r in rows if _printed(r, field) is not None
                and test(float(_printed(r, field)))]
        if hits:
            worst = ", ".join(
                f"#{h.get('id')} {_printed(h, field)}" for h in hits[:5])
            more = f" (+{len(hits) - 5} more)" if len(hits) > 5 else ""
            out.append(f"MISMATCH {label}: {len(hits)} of {len(rows)} rows on "
                       f"screen break it — {worst}{more}")

    wr = float(asked.get("min_winrate") or 0)
    if wr > 0:
        bad("winrate", lambda v: v < wr, f"win % >= {wr:g}")
    mt = int(asked.get("min_trades") or 0)
    if mt > 0:
        bad("trades", lambda v: v < mt, f"trades >= {mt}")
    if asked.get("profitable"):
        bad("profit", lambda v: v <= 0, "profitable only")
    for key, field, cmp, label in (
            ("max_tp", "tp", "le", "TP <= {v:g}%"),
            ("max_sl", "sl", "le", "SL <= {v:g}%"),
            ("min_tp", "tp", "ge", "TP >= {v:g}%"),
            ("min_sl", "sl", "ge", "SL >= {v:g}%")):
        v = float(asked.get(key) or 0)
        if v <= 0:
            continue
        test = (lambda x, v=v: x > v) if cmp == "le" else (lambda x, v=v: x < v)
        bad(field, test, label.format(v=v))
    if asked.get("tp_over_sl"):
        hits = [r for r in rows
                if float(r.get("tp") or 0) < float(r.get("sl") or 0)]
        if hits:
            out.append(f"MISMATCH TP >= SL: {len(hits)} of {len(rows)} rows on "
                       f"screen break it — " + ", ".join(
                           f"#{h.get('id')} TP {h.get('tp')} SL {h.get('sl')}"
                           for h in hits[:5]))
    # the plain equality filters: a wrong row here means the WHERE clause, not
    # a window — worth naming separately because the cause is different
    for key, field in (("sizing", "sizing"), ("tf", "tf"),
                       ("signal", "signal"), ("coin", "coin")):
        want = asked.get(key)
        if not want:
            continue
        hits = [r for r in rows if str(r.get(field)) != str(want)]
        if hits:
            out.append(f"MISMATCH {field} = {want}: {len(hits)} of {len(rows)} "
                       f"rows on screen are " + ", ".join(
                           sorted({str(h.get(field)) for h in hits})[:5]))
    return out


class Watch:
    """The same check, for a STREAM.

    A download writes tens of thousands of rows and must never hold them in
    memory (`grid_from_store` died of exactly that — 98 GB on a 17 GB machine).
    So the CSV shows each row to a Watch as it goes by, and the Watch keeps
    only counts and the first few offender ids.
    """

    def __init__(self, asked: dict):
        self.asked = asked
        self.seen = 0
        self.counts: dict[str, int] = {}
        self.who: dict[str, list[str]] = {}

    def see(self, row: dict) -> None:
        self.seen += 1
        for note in disagreements([row], self.asked):
            # "MISMATCH <label>: 1 of 1 rows on screen break it — #ID 89.47"
            label = note.split(":", 1)[0].removeprefix("MISMATCH ").strip()
            self.counts[label] = self.counts.get(label, 0) + 1
            names = self.who.setdefault(label, [])
            if len(names) < 5:
                names.append(note.rsplit("— ", 1)[-1])

    def notes(self) -> list[str]:
        out = []
        for label, n in self.counts.items():
            names = ", ".join(self.who[label])
            more = f" (+{n - len(self.who[label])} more)" if n > len(self.who[label]) else ""
            out.append(f"MISMATCH {label}: {n} of {self.seen} rows in the file "
                       f"break it — {names}{more}")
        return out


# ---------------------------------------------------------------- the log
def _asked_sentence(asked: dict) -> str:
    """The filters that were ON, in the order the panel shows them."""
    on = [f"{k}={v}" for k, v in asked.items()
          if v not in (None, "", 0, 0.0, False)]
    return " AND ".join(on) if on else "no filters"


def record(event: str, asked: dict, got: dict | None = None,
           took: float = 0.0, notes: list[str] | None = None) -> None:
    """Append one line. Never raises — a log must not break a page."""
    try:
        got = got or {}
        bits = [f"{fmt_when(__import__('time').time())}  {event}",
                f"asked: {_asked_sentence(asked)}"]
        if got:
            bits.append("got: " + " · ".join(
                f"{k}={v}" for k, v in got.items() if v is not None))
        bits.append(f"took {took:.2f}s")
        line = " | ".join(bits)
        for n in (notes or []):
            line += f"\n    {n}"
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        _trim()
    except Exception:                                          # noqa: BLE001
        pass                       # a log line is never worth a failed request


def _trim() -> None:
    try:
        if not LOG_PATH.exists() or LOG_PATH.stat().st_size < 2_000_000:
            return
        lines = LOG_PATH.read_text(encoding="utf-8",
                                   errors="replace").splitlines()
        if len(lines) > MAX_LINES:
            LOG_PATH.write_text("\n".join(lines[-MAX_LINES:]) + "\n",
                                encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass


def tail(n: int = 200) -> list[str]:
    """The last `n` lines, oldest first — what `/api/screen/log` serves."""
    try:
        if not LOG_PATH.exists():
            return []
        lines = LOG_PATH.read_text(encoding="utf-8",
                                   errors="replace").splitlines()
        return lines[-max(1, min(n, MAX_LINES)):]
    except Exception:                                          # noqa: BLE001
        return []


def mismatches(n: int = 400) -> list[str]:
    """Only the lines that say a filter was broken — the ones worth reading
    first, and the reason this module exists."""
    return [ln for ln in tail(n) if "MISMATCH" in ln]
