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
     "note": "anything else worth keeping",
     "source": "prompt" | "button" | "auto"}     # who made it; absent = prompt

Every room id must be one this machine has (profiles.ids), and every "real"
number a number (winrate, breakeven and per_trade may be null).

Usage from the prompt::

    python -m tradingagents.room_forecasts add <file.json>
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

FILE = Path.home() / ".tradingagents" / "room_forecasts.jsonl"
PER_PAGE = 10
VERDICTS = ("pick", "too early", "none proven")
# WHO MADE IT: the forecast prompt (a Claude session), the Forecast tab's
# button, or the automatic once-a-day run. A line without one came from the
# prompt, the only maker there was before Oct 01, 2026.
SOURCES = ("prompt", "button", "auto")
AUTO_RETRY_S = 30 * 60        # a failed automatic forecast is tried again after this
REAL_KEYS = ("closed", "wins", "losses", "winrate", "breakeven", "profit",
             "per_trade", "worst_run", "worst_run_trades", "open", "days")
# ...and these may be null: no closed trade has no win rate or profit a
# trade, and under 20 wins or 20 losses there is no break-even. Every other
# one must be a number, or the tab would print rubbish (or nothing at all).
MAY_BE_NULL = ("winrate", "breakeven", "per_trade")


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
        wrong = [k for k in REAL_KEYS if k in real and not (
            (real[k] is None and k in MAY_BE_NULL)
            or (isinstance(real[k], (int, float)) and not isinstance(real[k], bool)))]
        if wrong:
            out.append(f"room {r['id']} 'real' {', '.join(wrong)} must be number(s)")
    known = _known_rooms()
    strangers = sorted(i for i in ids if known and i not in known)
    if strangers:
        out.append(f"no such room on this machine: {', '.join(strangers)} "
                   f"(the rooms are {', '.join(sorted(known))})")
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
    if entry.get("source", "prompt") not in SOURCES:
        out.append(f"'source' must be one of {', '.join(SOURCES)}")
    return out


def _known_rooms() -> set:
    """Every room this machine has (profiles.ids), or empty if that cannot
    be read — then the id check is skipped rather than refusing everything."""
    try:
        from tradingagents import profiles

        return set(profiles.ids())
    except Exception:                                          # noqa: BLE001
        return set()


def add(entry: dict, path: Path | None = None) -> dict:
    """Append one forecast. Refuses, naming every problem, rather than saving
    a line the tab or the next prompt cannot read."""
    bad = problems(entry)
    if bad:
        raise ValueError("forecast not saved: " + "; ".join(bad))
    from tradingagents import portable

    p = Path(path or FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    # ONE WRITER AT A TIME: the button, the daily run and a Claude session's
    # `add` can land in the same second, and two half-lines are two
    # unreadable forecasts
    with p.open("a", encoding="utf-8") as fh:
        portable.lock_exclusive(fh)
        try:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            fh.flush()
        finally:
            portable.unlock(fh)
    return entry


def saved(path: Path | None = None) -> tuple[list, int]:
    """(every readable forecast NEWEST FIRST, how many lines were not one)."""
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
    return good, bad


def read(page: int = 1, per: int = PER_PAGE, path: Path | None = None) -> dict:
    """The saved forecasts, NEWEST FIRST, one page at a time. A line that is
    not a forecast is counted in `unreadable`, never silently dropped."""
    p = Path(path or FILE)
    good, bad = saved(p)
    total = len(good)
    pages = max(1, -(-total // per))
    page = min(max(1, int(page)), pages)
    return {"forecasts": good[(page - 1) * per: page * per], "total": total,
            "page": page, "pages": pages, "per": per, "unreadable": bad,
            "file": str(p), "read_at": int(time.time())}


def make(source: str, now: float | None = None, path: Path | None = None) -> dict:
    """Build a forecast from room_stats — the same numbers the tab shows —
    and save it. The button and the daily run both come through here."""
    from tradingagents import room_stats as rs

    now = time.time() if now is None else float(now)
    return add(rs.forecast_entry(rs.rooms(now), now, source), path=path)


# The automatic forecast's last word, for the tab and the log. Kept in this
# process: the only file this feature writes is the forecast file itself.
AUTO: dict = {"why": "", "error": "", "failed_at": 0.0, "made_at": 0.0}


def _update() -> dict:
    """The last daily GitHub update: when it went out, its runs (both
    accounts), and which of them are copied onto this PC."""
    from tradingagents import cloud_autopilot as ap, cloud_sweep as cs, db_jobs as dj

    plan = {}
    try:
        plan = dj._read(dj.STATE_DIR / "db_btupdate_v2.plan.json") or {}
    except Exception:                                          # noqa: BLE001
        plan = {}
    lead = plan.get("cloud_run")
    ids = {int(lead)} if lead else set()
    try:
        rem = cs.remembered() or {}
        sib = {int(r["id"]) for r in (rem.get("runs") or []) if r.get("id")}
        if lead and int(lead) in (sib | {int(rem.get("id") or 0)}):
            ids |= sib
    except Exception:                                          # noqa: BLE001
        pass
    try:
        got = {int(x) for x in (ap._read().get("collected") or [])}
    except Exception:                                          # noqa: BLE001
        got = set()
    return {"when": float(plan.get("when") or 0), "runs": sorted(ids),
            "collected": sorted(ids & got)}


def auto_due(now: float | None = None, path: Path | None = None) -> tuple[bool, str]:
    """(due, why): ONCE A DAY, AFTER THE DAILY GITHUB UPDATE IS COLLECTED.

    Due when (1) no automatic forecast was made today, (2) a GitHub update
    went out AFTER the last automatic forecast, and (3) every run of it is
    copied onto this PC. Anything else is a wait, and says what it waits for.
    """
    from tradingagents.positions_view import fmt_when

    now = time.time() if now is None else float(now)
    autos = [f for f in saved(path)[0] if f.get("source") == "auto"]
    today = dt.date.fromtimestamp(now)
    made = [f for f in autos if dt.date.fromtimestamp(float(f["at"])) == today]
    if made:
        return False, f"today's automatic forecast was made at {fmt_when(made[0]['at'])}"
    up = _update()
    if not up["runs"] or not up["when"]:
        return False, "waiting for the first daily GitHub update to go out"
    last_auto = max((float(f["at"]) for f in autos), default=0.0)
    if up["when"] <= last_auto:
        return False, (f"waiting for the next daily GitHub update — the last one "
                       f"({fmt_when(up['when'])}) already has its forecast")
    if len(up["collected"]) < len(up["runs"]):
        return False, (f"waiting for the {fmt_when(up['when'])} GitHub update to be "
                       f"copied onto this PC ({len(up['collected'])} of "
                       f"{len(up['runs'])} runs in)")
    return True, f"the {fmt_when(up['when'])} GitHub update is on this PC"


def daily_tick(now: float | None = None, path: Path | None = None) -> dict:
    """The supervisor's 30-second call. NEVER under pytest against the real
    file (a test run must not write the operator's forecasts). A failure is
    kept, printed once and shown on the tab, and tried again after
    AUTO_RETRY_S — never silent, never every 30 seconds."""
    from tradingagents.positions_view import fmt_when

    if os.environ.get("PYTEST_CURRENT_TEST") and path is None:
        return {"made": False, "why": "never under a test run"}
    now = time.time() if now is None else float(now)
    if AUTO["failed_at"] and now - AUTO["failed_at"] < AUTO_RETRY_S:
        return {"made": False, "why": AUTO["why"]}
    try:
        due, why = auto_due(now, path)
    except Exception as exc:                                   # noqa: BLE001
        due, why = False, f"could not check the daily update: {type(exc).__name__}: {exc}"
    if not due:
        if why != AUTO["why"]:
            print(f"[forecast] {why}", flush=True)
        AUTO["why"] = why
        return {"made": False, "why": why}
    try:
        entry = make("auto", now, path)
    except Exception as exc:                                   # noqa: BLE001
        AUTO.update(failed_at=now, error=f"{type(exc).__name__}: {exc}",
                    why=(f"the automatic forecast FAILED at {fmt_when(now)}: "
                         f"{type(exc).__name__}: {str(exc)[:200]} — trying again at "
                         f"{fmt_when(now + AUTO_RETRY_S)}"))
        print(f"[forecast] {AUTO['why']}", flush=True)
        return {"made": False, "why": AUTO["why"]}
    AUTO.update(failed_at=0.0, error="", made_at=now,
                why=f"made today's automatic forecast at {fmt_when(now)} ({why})")
    print(f"[forecast] {AUTO['why']}: {entry['verdict']}"
          f"{' ' + str(entry['pick']) if entry.get('pick') else ''}", flush=True)
    return {"made": True, "why": AUTO["why"], "entry": entry}


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
