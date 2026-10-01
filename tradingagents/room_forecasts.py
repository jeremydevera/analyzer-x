"""Saved room forecasts — what the Auto Trade -> Forecast tab shows.

Operator, Oct 01, 2026: *"create a forecast tab, then if i run this prompt make
sure it will generate a new forecast / take note create forecast tab only for
now"*. A forecast is made by a Claude session running the forecast prompt
(docs/FORECAST-PROMPTS.md); this module is only where it is KEPT and READ, so
the tab shows exactly what was saved and never works anything out itself.

ONE FILE, APPEND ONLY: `~/.tradingagents/room_forecasts.jsonl`, one forecast
per line, oldest first. A line is never edited — the "look at the best
forecast" prompt checks old picks against what happened since, and an old
forecast that could be rewritten would prove nothing.

A line, as `add()` checks it::

    {"at": 1790800000,                    # unix seconds, when it was made
     "pick": "4FC03172" | "main" | null,  # null = "none is proven yet"
     "pick_why": "one plain sentence",
     "verdict": "pick" | "too early" | "none proven",
     "rooms": [{
        "id": "4FC03172", "retired": false,
        "rules": "30 days · on 70% · off 70% · 50 trades · TP > SL · SL <= 2%",
        "research": {"profit": 4967.43, "wins": 10305, "losses": 5040,
                     "trades": 15345, "worst_run": -30.07, "worst_run_trades": 23},
        "real": {"closed": 406, "wins": 161, "losses": 245, "winrate": 39.7,
                 "breakeven": 62.3, "profit": -128.77, "per_trade": -0.317,
                 "worst_run": -27.5, "worst_run_trades": 25, "open": 122,
                 "days": 0.7, "first_at": 1790801800}}],
     "artifact": "https://claude.ai/..." | null,
     "note": "anything else worth keeping"}

Usage from the prompt::

    python -m tradingagents.room_forecasts add <file.json>
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

FILE = Path.home() / ".tradingagents" / "room_forecasts.jsonl"
PER_PAGE = 10
VERDICTS = ("pick", "too early", "none proven")
REAL_KEYS = ("closed", "wins", "losses", "winrate", "breakeven", "profit",
             "per_trade", "worst_run", "worst_run_trades", "open", "days")


def problems(entry: dict) -> list:
    """Why this forecast cannot be saved, in words; [] when it can."""
    out = []
    if not isinstance(entry, dict):
        return ["a forecast is one JSON object"]
    if not isinstance(entry.get("at"), (int, float)) or entry["at"] <= 0:
        out.append("'at' must be unix seconds")
    if entry.get("verdict") not in VERDICTS:
        out.append(f"'verdict' must be one of {', '.join(VERDICTS)}")
    rooms = entry.get("rooms")
    if not isinstance(rooms, list) or not rooms:
        out.append("'rooms' must list every room")
        rooms = []
    ids = set()
    for i, r in enumerate(rooms):
        if not isinstance(r, dict) or not r.get("id"):
            out.append(f"room {i + 1} has no 'id'")
            continue
        ids.add(str(r["id"]))
        real = r.get("real")
        if not isinstance(real, dict):
            out.append(f"room {r['id']} has no 'real' results")
            continue
        missing = [k for k in REAL_KEYS if k not in real]
        if missing:
            out.append(f"room {r['id']} 'real' lacks {', '.join(missing)}")
    pick = entry.get("pick")
    if entry.get("verdict") == "pick":
        if not pick:
            out.append("a 'pick' verdict needs the picked room's id")
        elif str(pick) not in ids:
            out.append(f"the pick {pick!r} is not one of the rooms listed")
    elif pick:
        out.append("only the 'pick' verdict names a room; use pick null")
    if not str(entry.get("pick_why") or "").strip():
        out.append("'pick_why' must say why, in one sentence")
    return out


def add(entry: dict, path: Path | None = None) -> dict:
    """Append one forecast. Refuses, naming every problem, rather than saving
    a line the tab or the next prompt cannot read."""
    bad = problems(entry)
    if bad:
        raise ValueError("forecast not saved: " + "; ".join(bad))
    p = Path(path or FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read(page: int = 1, per: int = PER_PAGE, path: Path | None = None) -> dict:
    """The saved forecasts, NEWEST FIRST, one page at a time. A line that is
    not a forecast is counted in `unreadable`, never silently dropped."""
    p = Path(path or FILE)
    good, bad = [], 0
    try:
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if problems(e):
                    bad += 1
                    continue
                good.append(e)
    except OSError:
        pass
    good.sort(key=lambda e: -float(e["at"]))
    total = len(good)
    pages = max(1, -(-total // per))
    page = min(max(1, int(page)), pages)
    return {"forecasts": good[(page - 1) * per: page * per], "total": total,
            "page": page, "pages": pages, "per": per, "unreadable": bad,
            "file": str(p), "read_at": int(time.time())}


PROMPTS_FILE = Path(__file__).resolve().parents[1] / "docs" / "FORECAST-PROMPTS.md"


def prompts(path: Path | None = None) -> list:
    """The prompts the tab offers to copy, read from docs/FORECAST-PROMPTS.md
    so the tab and the document can never say two different things:
    [{"title": "1. Make a new forecast", "text": "..."}, ...]."""
    try:
        lines = Path(path or PROMPTS_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out, title, body, inside = [], "", [], False
    for line in lines:
        if line.startswith("## ") and not inside:
            title = line[3:].strip()
        elif line.strip().startswith("```"):
            if inside:
                out.append({"title": title, "text": "\n".join(body).strip()})
                body = []
            inside = not inside
        elif inside:
            body.append(line)
    return out


def main(argv: list | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 2 and args[0] == "add":
        try:
            entry = json.loads(Path(args[1]).read_text(encoding="utf-8"))
            add(entry)
        except (OSError, ValueError) as exc:
            print(str(exc), flush=True)
            return 1
        from tradingagents.positions_view import fmt_when

        print(f"saved: forecast of {fmt_when(entry['at'])} ({entry['verdict']}"
              f"{', pick ' + str(entry['pick']) if entry.get('pick') else ''}) "
              f"to {FILE}", flush=True)
        return 0
    print("usage: python -m tradingagents.room_forecasts add <forecast.json>",
          flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
