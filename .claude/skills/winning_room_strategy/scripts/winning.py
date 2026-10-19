"""/winning_room_strategy — the room strategies that made money over the days
asked, read from Forecast -> Room strategies.

The operator, Oct 18, 2026: *"make a skill for this called
'/winning_room_strategy' so that you will find the winning room strategy via
room strategy table, I will give you the days i need for example, i need
winning room stragy for past 2 days, or 7 days or last week"*.

It asks the route the table itself reads (`GET /api/forecasts/room-
strategies`, tradingagents/api.py -> room_strategies.table), with the dates the
table's own boxes send (RoomForecasts.tsx `rsAsk`), so every number is the
table's — a second calculation would be a second answer:

  --days N        the table's "or last N days" box: now minus N days to now
  --this-week     Monday 12:00am of this week to today, on this PC's days
  --last-week     the Monday-to-Sunday before this week
  --from / --to   YYYY-MM-DD, the table's date boxes

Run from the repo root with the app's Python:

  .venv/Scripts/python .claude/skills/winning_room_strategy/scripts/winning.py --days 2

Read only: it never switches a strategy on, never deploys, never presses a job.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingagents.forecast_rules import TP_WORDS  # noqa: E402  the table's own rule words
from tradingagents.positions_view import fmt_when  # noqa: E402  the project's one date format

# the back end itself: the page's proxy gives up at 30 s, and the first ask
# after a restart walks every saved trade (82 s measured, Oct 07, 2026)
BASE = "http://127.0.0.1:8787"
TIMEOUT_S = 300
# A row with no trade in the dates passes no profit floor (RCA-2026-10-07-N),
# so one very low floor asks for exactly the rows that TRADED — never the
# $0.00 rows that sort above every loss on the screen's own profit order.
ANY_PROFIT = -1_000_000_000
HOME = Path.home() / ".tradingagents" / "winning_room_strategy"
SHOW = 10            # groups printed; every row is in the saved files
# what makes two rows "the same numbers": rule sets that differ only in a
# limit none of their trades reached print identical figures
_SAME = ("trades", "wins", "losses", "profit", "corrected", "worst_day",
         "worst_run", "worst_run_n")


# ------------------------------------------------------------------ dates


def window(*, days=None, week=None, from_day=None, to_day=None, now=None) -> dict:
    """The dates to read, the way the table's boxes send them. "Last N days"
    is a span of time back from now (seconds); a week or two dates are this
    PC's days, which the server turns into its own midnights (RCA-2026-10-16-D)."""
    now = time.time() if now is None else float(now)
    if days is not None:
        n = float(days)
        if not n > 0:
            raise ValueError("a number of days must be above 0, like 2")
        words = f"last {n:g} day" + ("" if n == 1 else "s")
        return {"from_s": int(now - round(n * 86_400)), "to_s": int(now),
                "from_day": "", "to_day": "", "words": words}
    if week is not None:
        if week not in ("this", "last"):
            raise ValueError("a week is 'this' or 'last'")
        today = dt.date.fromtimestamp(now)
        monday = today - dt.timedelta(days=today.weekday())
        a, b = (monday, today) if week == "this" else (monday - dt.timedelta(days=7),
                                                       monday - dt.timedelta(days=1))
        return {"from_s": None, "to_s": None, "from_day": a.isoformat(),
                "to_day": b.isoformat(), "words": f"{week} week"}
    if from_day or to_day:
        try:
            a = dt.date.fromisoformat(str(from_day))
            b = dt.date.fromisoformat(str(to_day))
        except ValueError as exc:
            raise ValueError(f"a day is YYYY-MM-DD, like 2026-10-12 ({exc})") from exc
        if b < a:
            raise ValueError("the 'to' day is before the 'from' day")
        return {"from_s": None, "to_s": None, "from_day": a.isoformat(),
                "to_day": b.isoformat(), "words": "the dates asked"}
    raise ValueError("say the days: --days N, --this-week, --last-week, or --from and --to")


# ------------------------------------------------------------- the table


def _get(base: str, params: dict, timeout: float) -> dict:
    url = f"{base}/api/forecasts/room-strategies?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def read_table(win: dict, *, base: str = BASE, timeout: float = TIMEOUT_S) -> dict:
    """Every row of the table that TRADED in the dates, every page, in the
    table's own order (profit, highest first), with the table's header
    numbers. A re-test that lands mid-read changes the answer under it, so a
    page whose header disagrees with the first page's is refused by name."""
    params = {"sort": "profit", "min_profit": ANY_PROFIT}
    if win.get("from_day"):
        params.update(from_day=win["from_day"], to_day=win["to_day"])
    else:
        params.update(from_s=win["from_s"], to_s=win["to_s"])
    rows: list = []
    first = None
    page = 1
    while True:
        d = _get(base, {**params, "page": page}, timeout)
        if first is None:
            first = d
        elif (d.get("matched"), d.get("data_end")) != (first.get("matched"), first.get("data_end")):
            raise RuntimeError("the Room strategies table changed while it was being read "
                               "(a daily re-test landed) — run it again")
        rows += d.get("rows") or []
        if page >= int(d.get("pages") or 1):
            break
        page += 1
    out = {k: v for k, v in first.items() if k != "rows"}
    out["rows"] = rows
    return out


def winners(rows: list) -> list:
    """The rows that made money in the dates, in the table's order."""
    return [r for r in rows if (r.get("trades") or 0) > 0 and float(r.get("profit") or 0) > 0]


def same_numbers(rows: list) -> list:
    """Rows whose figures are all equal, as one entry with every id, in the
    order the first of each appears."""
    groups: list = []
    by: dict = {}
    for r in rows:
        k = tuple(r.get(x) for x in _SAME)
        if k in by:
            by[k]["ids"].append(r["id"])
            by[k]["rules"].append(r.get("words", ""))
            by[k]["members"].append(r)
        else:
            g = {"ids": [r["id"]], "rules": [r.get("words", "")], "row": r, "members": [r]}
            by[k] = g
            groups.append(g)
    return groups


# ------------------------------------------------------------ the report


def _money(v) -> str:
    """As the screen prints it (api.ts fmtMoney): +3.48, -1.52."""
    return "—" if v is None else f"{'+' if float(v) >= 0 else ''}{float(v):.2f}"


def _pct(v) -> str:
    return "—" if v is None else f"{float(v):.1f}%"


def _stop_words(max_sl) -> str:
    x = float(max_sl or 0)
    return "any stop" if x <= 0 else f"stop {x:g}% or tighter"


COLUMNS = ["ID", "Rules", "Trades", "A day", "Won / lost", "Win rate", "Break-even",
           "Profit", "After reality check", "Worst day", "Worst losing run",
           "TP rule", "Stop rule", "Room can run it"]


def _every(g: dict, words) -> str:
    """One cell for every id on a shared line: each distinct value its rule
    sets have, in order — never only the first set's (label-must-match-data:
    eight sets with one stop limit each printed "any stop")."""
    seen: list = []
    for m in g.get("members") or [g["row"]]:
        w = words(m)
        if w not in seen:
            seen.append(w)
    return " or ".join(seen)


def _cells(g: dict) -> list:
    r = g["row"]
    ids = " ".join(f"#{i}" for i in g["ids"])
    rules = g["rules"][0] + (f" (+{len(g['ids']) - 1} more with the same numbers)"
                             if len(g["ids"]) > 1 else "")
    run = (f"{_money(r.get('worst_run'))} over {r.get('worst_run_n')}"
           if r.get("worst_run_n") else "—")
    return [ids, rules, f"{int(r.get('trades') or 0):,}", str(r.get("per_day", "—")),
            f"{int(r.get('wins') or 0):,} / {int(r.get('losses') or 0):,}",
            _pct(r.get("winrate")), _pct(r.get("break_even")), _money(r.get("profit")),
            _money(r.get("corrected")), _money(r.get("worst_day")), run,
            _every(g, lambda m: TP_WORDS.get(str(m.get("tp")), str(m.get("tp")))),
            _every(g, lambda m: _stop_words(m.get("max_sl"))),
            _every(g, lambda m: "yes" if m.get("deployable") else "needs a new switch")]


def _table(groups: list) -> str:
    lines = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    lines += ["| " + " | ".join(_cells(g)) + " |" for g in groups]
    return "\n".join(lines)


def report(win: dict, table: dict, *, show: int = SHOW) -> str:
    """The answer in the table's own words and numbers. An empty one names
    what it checked and where the measured trades end (CLAUDE.md: an empty
    page may never speak for the store)."""
    kept = int(table.get("kept") or 0)
    rows = table.get("rows") or []
    traded = int(table.get("with_trades") or len(rows))
    won = winners(rows)
    end_ms = table.get("data_end")
    end = fmt_when(end_ms / 1000) if end_ms else "—"
    retest = (table.get("retest") or {}).get("made_at")
    when = (f"{fmt_when(win['from_s'])} to {fmt_when(win['to_s'])}" if win.get("from_s") is not None
            else f"{fmt_when(table['from'])} to {fmt_when(table['to'])}" if table.get("from") is not None
            else f"{win['from_day']} to {win['to_day']}")
    out = [f"Room strategies, {win['words']}: {when}",
           f"{kept:,} room strategies checked · {traded:,} traded · {len(won):,} made money · "
           f"their trades are measured up to {end}"
           + (f" (daily re-test made {fmt_when(retest)})" if retest else "")
           + f" · ${float(table.get('margin') or 5):g} a trade at {int(table.get('leverage') or 20)}x"]
    if end_ms and table.get("to") is not None and float(table["to"]) * 1000 > float(end_ms):
        out.append(f"Anything after {end} is not in these numbers yet; the next daily "
                   f"re-test (1:00am) adds it.")
    out.append("")
    if won:
        groups = same_numbers(won)
        out.append(f"{len(won):,} made money (rule sets with the same numbers share a line), "
                   f"best first:")
        out.append(_table(groups[:show]))
        if len(groups) > show:
            out.append(f"... and {len(groups) - show:,} more lines in the saved files.")
    else:
        out.append(f"None of the {kept:,} room strategies made money in these dates; "
                   f"{traded:,} traded.")
        if rows:
            out.append("Closest (the least lost):")
            out.append(_table(same_numbers(rows)[:3]))
    return "\n".join(out)


def save(win: dict, table: dict, *, now=None) -> tuple[Path, Path]:
    """The run, under runs/<yyyy-mm-dd>/<time> winners.json and .csv (the
    operator's folder rule: a day folder that sorts, the time with a dash)."""
    now = time.time() if now is None else float(now)
    stamp = fmt_when(now)
    folder = HOME / "runs" / dt.date.fromtimestamp(now).isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    base = folder / f"{stamp.split()[-1].replace(':', '-')} winners"
    rows = table.get("rows") or []
    won = winners(rows)
    js = base.with_suffix(".json")
    js.write_text(json.dumps({
        "asked_at": stamp, "window": win,
        "checked": table.get("kept"), "traded": table.get("with_trades"),
        "made_money": len(won),
        "trades_measured_up_to": fmt_when(table["data_end"] / 1000) if table.get("data_end") else None,
        "margin": table.get("margin"), "leverage": table.get("leverage"),
        "winners": won, "traded_rows": rows}, indent=1), encoding="utf-8")
    cs = base.with_suffix(".csv")
    with cs.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "rules", "trades", "a_day", "wins", "losses", "win_rate",
                    "break_even", "profit", "after_reality_check", "worst_day", "worst_run",
                    "worst_run_trades", "tp_rule", "stop_rule", "room_can_run_it", "made_money"])
        for r in rows:
            w.writerow([r["id"], r.get("words", ""), r.get("trades"), r.get("per_day"),
                        r.get("wins"), r.get("losses"), r.get("winrate"), r.get("break_even"),
                        r.get("profit"), r.get("corrected"), r.get("worst_day"),
                        r.get("worst_run"), r.get("worst_run_n"),
                        TP_WORDS.get(str(r.get("tp")), str(r.get("tp"))),
                        _stop_words(r.get("max_sl")), "yes" if r.get("deployable") else "no",
                        "yes" if r in won else "no"])
    return js, cs


# ------------------------------------------------------------------ run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="The room strategies that made money over the days asked.")
    pick = ap.add_mutually_exclusive_group()
    pick.add_argument("--days", type=float, help="the last N days, counted back from now")
    pick.add_argument("--this-week", action="store_true", help="Monday of this week to today")
    pick.add_argument("--last-week", action="store_true", help="the Monday-to-Sunday before this week")
    ap.add_argument("--from", dest="from_day", help="first day, YYYY-MM-DD")
    ap.add_argument("--to", dest="to_day", help="last day, YYYY-MM-DD")
    ap.add_argument("--base", default=BASE, help=f"the back end (default {BASE})")
    ap.add_argument("--show", type=int, default=SHOW, help="lines to print (every row is saved)")
    ap.add_argument("--no-save", action="store_true", help="print only, write no files")
    a = ap.parse_args(argv)
    # the answer carries "·" and "—": a Windows console's own code page
    # printed them as "?" boxes on the first run (Oct 18, 2026)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        if a.days is not None:
            win = window(days=a.days)
        elif a.this_week:
            win = window(week="this")
        elif a.last_week:
            win = window(week="last")
        else:
            win = window(from_day=a.from_day, to_day=a.to_day)
    except ValueError as exc:
        print(f"winning_room_strategy: {exc}", file=sys.stderr)
        return 2
    try:
        table = read_table(win, base=a.base)
    except urllib.error.HTTPError as exc:
        # it answered, and said no: its own reason, never "did not answer"
        try:
            why = json.loads(exc.read().decode("utf-8")).get("detail")
        except Exception:                                      # noqa: BLE001
            why = None
        print(f"winning_room_strategy: the Room strategies table refused the dates "
              f"(HTTP {exc.code}): {why or exc.reason}", file=sys.stderr)
        return 3
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"winning_room_strategy: the back end at {a.base} did not answer ({exc}) — "
              f"is the site running?", file=sys.stderr)
        return 3
    except RuntimeError as exc:
        print(f"winning_room_strategy: {exc}", file=sys.stderr)
        return 4
    print(report(win, table, show=a.show))
    if not a.no_save:
        js, cs = save(win, table)
        print(f"\nSaved: {js}\n       {cs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
