"""/winning_room_strategy — the room strategies that made money over the days
asked, read from the Room strategies table.

The operator, Oct 18, 2026, word for word: *"What room strategy has been
winning this week, can you check the list of room strategy, also make a skill
for this called '/winning_room_strategy' so that you will find the winning
room strategy via room strategy table, I will give you the days i need for
example, i need winning room stragy for past 2 days, or 7 days or last week"*
and *"Also add this skill in claude skills tab along with practice backtest
audit skill since this is an automation"*.

The script asks the route the table itself reads (`/api/forecasts/room-
strategies`), with the dates the table's own boxes send, so its numbers are
the table's: a second calculation would be a second answer.
"""
import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest

from tradingagents.positions_view import fmt_when

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".claude" / "skills" / "winning_room_strategy" / "scripts" / "winning.py"


def _load():
    spec = importlib.util.spec_from_file_location("winning_room_strategy_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _at(*a) -> float:
    """An instant on THIS PC's clock, as the table's date boxes read it."""
    return dt.datetime(*a).timestamp()


# ------------------------------------------------------------- the dates


def test_past_n_days_is_the_tables_last_n_days_box():
    """`rsAsk` in RoomForecasts.tsx: now minus N days to now, in seconds."""
    w = _load()
    now = 1_792_377_000
    got = w.window(days=2, now=now)
    assert (got["from_s"], got["to_s"]) == (now - 2 * 86_400, now)
    assert (got["from_day"], got["to_day"]) == ("", "")
    assert got["words"] == "last 2 days"
    assert w.window(days=7, now=now)["from_s"] == now - 7 * 86_400
    assert w.window(days=1, now=now)["words"] == "last 1 day"


@pytest.mark.parametrize("bad", [0, -3])
def test_a_number_of_days_must_be_above_zero(bad):
    with pytest.raises(ValueError):
        _load().window(days=bad, now=1_792_377_000)


def test_this_week_is_monday_to_today_on_this_pcs_days():
    w = _load()
    sunday = _at(2026, 10, 18, 23, 30)
    got = w.window(week="this", now=sunday)
    assert (got["from_day"], got["to_day"]) == ("2026-10-12", "2026-10-18")
    assert got["words"] == "this week"
    monday = _at(2026, 10, 19, 9, 0)
    got = w.window(week="this", now=monday)
    assert (got["from_day"], got["to_day"]) == ("2026-10-19", "2026-10-19")


def test_last_week_is_the_monday_to_sunday_before_this_one():
    w = _load()
    got = w.window(week="last", now=_at(2026, 10, 18, 23, 30))
    assert (got["from_day"], got["to_day"]) == ("2026-10-05", "2026-10-11")
    got = w.window(week="last", now=_at(2026, 10, 19, 0, 5))
    assert (got["from_day"], got["to_day"]) == ("2026-10-12", "2026-10-18")
    assert got["words"] == "last week"


def test_dates_given_are_sent_as_days_and_must_be_in_order():
    w = _load()
    got = w.window(from_day="2026-10-01", to_day="2026-10-07")
    assert (got["from_day"], got["to_day"]) == ("2026-10-01", "2026-10-07")
    with pytest.raises(ValueError):
        w.window(from_day="2026-10-07", to_day="2026-10-01")
    with pytest.raises(ValueError):
        w.window(from_day="Oct 07", to_day="2026-10-09")
    with pytest.raises(ValueError):
        w.window()


# ------------------------------------------------------- reading the table


def _row(rid, profit, trades=3, wins=2, **k):
    r = {"id": rid, "words": f"rules of {rid}", "found_by": "prompt 4", "found_at": 1_791_000_000,
         "deployable": True, "deploy_why": "", "window": 30, "tp": "any", "max_sl": 1.0,
         "trades": trades, "per_day": round(trades / 7, 1), "wins": wins, "losses": trades - wins,
         "winrate": round(100 * wins / trades, 1) if trades else None, "break_even": 40.0,
         "profit": profit, "corrected": round(profit * 0.8, 2), "worst_day": -1.0,
         "worst_run": -1.2, "worst_run_n": 1, "still_works": True}
    r.update(k)
    return r


def _page(rows, page, pages, **k):
    d = {"rows": rows, "matched": 3, "kept": 1008, "page": page, "pages": pages,
         "from": 1_791_777_600, "to": 1_792_382_399, "with_trades": 3,
         "data_start": 1_783_146_600_000, "data_end": 1_792_296_000_000,
         "reality": {"took": 0.85, "gap": -0.08}, "margin": 5.0, "leverage": 20,
         "retest": {"phase": "done", "made_at": 1_792_312_114}}
    d.update(k)
    return d


def test_every_page_is_read_and_only_rows_that_traded_are_asked_for(monkeypatch):
    """A row with no trade in the dates passes no profit floor (RCA-2026-10-07-N),
    so one very low floor asks for exactly the rows that traded — never the
    $0.00 rows that sort above every loss."""
    w = _load()
    asked = []
    pages = {1: _page([_row("AAAAAAAA", 3.48), _row("BBBBBBBB", 0.5)], 1, 2),
             2: _page([_row("CCCCCCCC", -1.52)], 2, 2)}

    def fake_get(base, params, timeout):
        asked.append(dict(params))
        return pages[int(params["page"])]
    monkeypatch.setattr(w, "_get", fake_get)
    got = w.read_table(w.window(from_day="2026-10-12", to_day="2026-10-18"))
    assert [r["id"] for r in got["rows"]] == ["AAAAAAAA", "BBBBBBBB", "CCCCCCCC"]
    assert [a["page"] for a in asked] == [1, 2]
    for a in asked:
        assert a["sort"] == "profit"
        assert float(a["min_profit"]) <= -1_000_000
        assert (a["from_day"], a["to_day"]) == ("2026-10-12", "2026-10-18")
    assert got["kept"] == 1008 and got["with_trades"] == 3


def test_a_last_n_days_ask_sends_seconds_like_the_screen(monkeypatch):
    w = _load()
    asked = []
    monkeypatch.setattr(w, "_get", lambda base, params, timeout: asked.append(dict(params))
                        or _page([], 1, 1, with_trades=0, matched=0))
    w.read_table(w.window(days=2, now=1_792_377_000))
    assert asked[0]["from_s"] == 1_792_377_000 - 2 * 86_400 and asked[0]["to_s"] == 1_792_377_000
    assert "from_day" not in asked[0]


def test_winners_are_the_rows_that_made_money_in_the_tables_order():
    w = _load()
    rows = [_row("A1", 3.48), _row("A2", 3.48), _row("B1", 0.5), _row("C1", 0.0),
            _row("D1", -1.52)]
    assert [r["id"] for r in w.winners(rows)] == ["A1", "A2", "B1"]


def test_rows_with_the_same_numbers_are_listed_together():
    """Eight rule sets that differ only in a stop limit none of their trades
    reached print the same 9 trades and -1.52 — one line, eight ids."""
    w = _load()
    rows = [_row("A1", 3.48), _row("A2", 3.48), _row("B1", 0.5), _row("A3", 3.48)]
    groups = w.same_numbers(rows)
    assert [g["ids"] for g in groups] == [["A1", "A2", "A3"], ["B1"]]
    assert groups[0]["row"]["profit"] == 3.48


# ------------------------------------------------------------- the report


def test_the_report_carries_every_column_the_rules_ask_for():
    """CLAUDE.md, every results table: profit, TP, SL, leverage, margin above
    the table, wins and losses, the worst losing run with its count, trades
    and trades a day, and how many were checked."""
    w = _load()
    table = _page([_row("AAAAAAAA", 3.48), _row("BBBBBBBB", -1.0)], 1, 1)
    text = w.report(w.window(from_day="2026-10-12", to_day="2026-10-18"), table)
    # the table's own column names, and its money as the screen prints it
    for want in ("Profit", "TP rule", "Stop rule", "Won / lost", "Win rate", "Worst losing run",
                 "Trades", "A day", "$5 a trade at 20x", "1,008 room strategies checked",
                 "#AAAAAAAA", "+3.48"):
        assert want in text, want
    assert "#BBBBBBBB" not in text.split("made money")[1].split("Closest")[0], \
        "a row that lost is never listed as a winner"


def test_nothing_won_names_what_was_examined():
    """An empty answer names what it checked and where the measured prices
    end (CLAUDE.md: an empty page may never speak for the store)."""
    w = _load()
    table = _page([_row("LOSER001", -1.52, trades=9, wins=2), _row("LOSER002", -1.81, trades=5, wins=0)],
                  1, 1, with_trades=2, matched=2)
    text = w.report(w.window(from_day="2026-10-12", to_day="2026-10-18"), table)
    assert "None of the 1,008 room strategies made money" in text
    assert "2 traded" in text
    assert fmt_when(1_792_296_000) in text, "where the measured trades end"
    assert "Closest" in text and "#LOSER001" in text


def test_a_window_past_the_measured_prices_says_so():
    w = _load()
    table = _page([], 1, 1, with_trades=0, matched=0, to=1_792_400_000)
    text = w.report(w.window(days=1, now=1_792_400_000), table)
    assert f"measured up to {fmt_when(1_792_296_000)}" in text
    assert "not in these numbers yet" in text


def test_a_run_is_saved_with_its_dates_in_the_folder_name(tmp_path, monkeypatch):
    w = _load()
    monkeypatch.setattr(w, "HOME", tmp_path)
    table = _page([_row("AAAAAAAA", 3.48)], 1, 1)
    win = w.window(from_day="2026-10-12", to_day="2026-10-18")
    js, csv = w.save(win, table, now=_at(2026, 10, 18, 23, 41))
    assert js.parent.name == "2026-10-18" and js.name == "11-41pm winners.json"
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["window"]["from_day"] == "2026-10-12" and data["winners"][0]["id"] == "AAAAAAAA"
    assert csv.read_text(encoding="utf-8").splitlines()[0].startswith("id,")


# ------------------------------------------------- the Claude skills tab


def test_it_is_on_the_claude_skills_tab_beside_the_practice_audit():
    from tradingagents import claude_skills as cs

    assert cs.SKILLS["winning_room_strategy"][0] == "Automation"
    assert cs.SKILLS["practice_backtest_audit"][0] == "Automation"
    assert "Automation" in cs.GROUPS
    names = {s["name"] for g in cs.listing()["groups"] if g["name"] == "Automation"
             for s in g["skills"]}
    assert names == {"winning_room_strategy", "practice_backtest_audit"}


def test_a_shared_line_names_every_rule_its_ids_have():
    """Eight sets on one line differ in their stop limit (any, 1%, 2%, 3%):
    the line's TP and Stop cells must describe all of them, never only the
    first set's "any stop" (label-must-match-data)."""
    w = _load()
    rows = [_row("A1", -1.52, max_sl=0.0, tp="any"), _row("A2", -1.52, max_sl=1.0, tp="any"),
            _row("A3", -1.52, max_sl=2.0, tp=">", deployable=False)]
    table = _page(rows, 1, 1)
    text = w.report(w.window(from_day="2026-10-12", to_day="2026-10-18"), table)
    line = [x for x in text.splitlines() if "#A1" in x][0]
    for want in ("any stop", "stop 1% or tighter", "stop 2% or tighter", "any TP",
                 "TP wider than SL", "yes", "needs a new switch"):
        assert want in line, want


def test_a_refusal_prints_the_tables_own_reason(monkeypatch, capsys):
    """The site answered and said no: its reason is printed, never "the back
    end did not answer"."""
    import io
    import urllib.error

    w = _load()

    def refuse(base, params, timeout):
        raise urllib.error.HTTPError("http://x", 400, "Bad Request", {},
                                     io.BytesIO(b'{"detail": "a day is YYYY-MM-DD: bad"}'))
    monkeypatch.setattr(w, "_get", refuse)
    assert w.main(["--from", "2026-10-01", "--to", "2026-10-02", "--no-save"]) == 3
    err = capsys.readouterr().err
    assert "refused" in err and "a day is YYYY-MM-DD" in err and "did not answer" not in err
