"""A click on a day of Auto Trade's calendar shows that day's trades as a table.

Operator, `Nov 12, 2026`: *"in auto trade, if i click a date in calendar show
me the trades made on that day in table"*. Looking at Practice, Nov 11, 2026:
the box said +1.61, 4W 2L, and ASTER, JIO, KAVA, WLFI — and nothing said which
six trades those were.

Three things have to hold, and each is a test below:

* the day is cut WHERE THE DATA IS (the server, over every closed trade), by the
  very key the calendar's boxes are filed under, so a box and its table count
  the same exits and add up to the same dollars;
* a malformed day is refused, never ignored — ignoring it would print every
  trade under one day's name;
* the screen asks the server for the day and never `.filter()`s a page it was
  already given (CLAUDE.md, filter where the data is).
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

import tradingagents.auto_trader as at
from tradingagents import api

ROOT = Path(__file__).resolve().parents[1]
STRAT = "willr14_30m_sl2tp05"


def _local(y, mo, d, h, mi=0) -> float:
    """A LOCAL clock time, the way the calendar's day is read."""
    return time.mktime((y, mo, d, h, mi, 0, 0, 0, -1))


def _exit(tid, symbol, pnl, ts, dry=True):
    return {"action": "exit", "trade_id": tid, "symbol": symbol, "strategy": STRAT,
            "pnl_est": pnl, "ts": ts, "dry_run": dry, "why": "TP" if pnl > 0 else "SL",
            "side": "LONG", "opened_at": ts - 3600, "held_s": 3600}


# Nov 11 and 12, 2026, with trades hugging local midnight on both sides: the
# 11:59pm one belongs to the 11th, the 12:01am one to the 12th, and a UTC day
# would have put them somewhere else.
LEDGER = [
    _exit("D10A0001", "WLFI_USDT", +0.86, _local(2026, 11, 10, 14)),
    _exit("D11A0001", "ASTER_USDT", +1.20, _local(2026, 11, 11, 0, 1)),
    _exit("D11A0002", "JIO_USDT", -0.40, _local(2026, 11, 11, 9)),
    _exit("D11A0003", "KAVA_USDT", +0.99, _local(2026, 11, 11, 13)),
    _exit("D11A0004", "WLFI_USDT", +0.556, _local(2026, 11, 11, 18)),
    _exit("D11A0005", "JIO_USDT", -0.314, _local(2026, 11, 11, 20)),
    _exit("D11A0006", "WLFI_USDT", -0.434, _local(2026, 11, 11, 23, 59)),
    _exit("D12A0001", "KAVA_USDT", -0.24, _local(2026, 11, 12, 0, 1)),
    # the same day on the REAL-money book: must never leak into the practice table
    _exit("D11LIVE1", "BTC_USDT", +5.00, _local(2026, 11, 11, 12), dry=False),
]


@pytest.fixture
def ledger(monkeypatch, write_ledger):
    write_ledger(reversed(LEDGER))
    monkeypatch.setattr(at, "load_settings", lambda: {
        "strategy_coins": {STRAT: ["WLFI_USDT"]}, "strategy_books": {STRAT: ["paper"]}})
    return LEDGER


# ------------------------------------------------ 1. the table is the box
def test_the_day_holds_exactly_the_trades_of_that_local_day(ledger):
    got = api.trade_history(dry=True, per_page=50, day="2026-11-11")
    assert got["total"] == 6, [r["id"] for r in got["rows"]]
    assert {r["id"] for r in got["rows"]} == {f"D11A000{i}" for i in range(1, 7)}
    assert got["day"] == "2026-11-11"


def test_the_table_adds_up_to_the_box_it_was_opened_from(ledger):
    """label-must-match-data: the calendar's box for the day and the table under
    it are two reads of one ledger and must agree on count, wins, losses and
    dollars — the box is `daily_pnl`, the table is the history route."""
    box = at.daily_pnl(dry=True)["2026-11-11"]
    got = api.trade_history(dry=True, per_page=50, day="2026-11-11")
    t = got["totals"]
    assert (t["trades"], t["wins"], t["losses"]) == (box["trades"], box["wins"], box["losses"])
    assert t["profit"] == box["pnl"]
    # the box adds EXACT amounts; the six rows, rounded to cents one by one, add up
    # to a cent more (Nov 11, 2026 on #RSS7CUKH: box +1.61, rows +1.62)
    assert box["pnl"] == 1.60 and round(sum(r["profit"] for r in got["rows"]), 2) == 1.61
    assert t["profit"] == box["pnl"], "the table's TOTAL is the box's number"
    assert all("_raw" not in r for r in got["rows"]), "the internal figure never leaves the server"
    assert sorted({r["coin"] for r in got["rows"]}) == box["coins"]


def test_every_day_of_the_calendar_agrees_with_its_table(ledger):
    for day, box in at.daily_pnl(dry=True).items():
        got = api.trade_history(dry=True, per_page=50, day=day)
        assert got["total"] == box["trades"], day
        assert got["totals"]["profit"] == box["pnl"], day


def test_the_other_book_never_leaks_into_the_table(ledger):
    live = api.trade_history(dry=False, per_page=50, day="2026-11-11")
    assert [r["id"] for r in live["rows"]] == ["D11LIVE1"]
    assert all(r["book"] == "demo" for r in
               api.trade_history(dry=True, per_page=50, day="2026-11-11")["rows"])


def test_the_table_pages_and_counts_every_trade_not_the_page(ledger):
    """Ten a page in the screen: the total is the DAY's, never the page's."""
    p1 = api.trade_history(dry=True, per_page=4, page=1, day="2026-11-11")
    p2 = api.trade_history(dry=True, per_page=4, page=2, day="2026-11-11")
    assert (p1["total"], p1["pages"], len(p1["rows"]), len(p2["rows"])) == (6, 2, 4, 2)
    assert p1["totals"]["trades"] == p2["totals"]["trades"] == 6
    assert {r["id"] for r in p1["rows"]}.isdisjoint({r["id"] for r in p2["rows"]})


def test_a_day_with_no_trade_is_empty_and_names_what_was_examined(ledger):
    got = api.trade_history(dry=True, per_page=50, day="2026-11-13")
    assert got["rows"] == [] and got["total"] == 0
    assert got["examined"] == 9, "an empty page names what it looked at, not what exists"


def test_no_day_is_the_old_behaviour_byte_for_byte(ledger):
    got = api.trade_history(dry=True, per_page=50)
    assert got["total"] == 8 and got["day"] == ""


# ------------------------------------------------ 2. a bad day is refused
@pytest.mark.parametrize("bad", ["2026-11-1", "11/11/2026", "yesterday", "2026-11-11x", "2026-11"])
def test_a_malformed_day_is_refused_not_ignored(ledger, bad):
    with pytest.raises(HTTPException) as e:
        api.trade_history(dry=True, per_page=50, day=bad)
    assert e.value.status_code == 400


# ------------------------------------------------ 3. the screen
PANEL = (ROOT / "webapp/src/components/trade/PnlPanel.tsx").read_text(encoding="utf-8")
DAY = (ROOT / "webapp/src/components/trade/DayTrades.tsx").read_text(encoding="utf-8")
API_TS = (ROOT / "webapp/src/lib/api.ts").read_text(encoding="utf-8")


def test_the_screen_asks_the_server_for_the_day():
    assert 'tradeApi.history(dry, page, PER_PAGE, "", day)' in DAY
    assert "&day=" in API_TS


def test_the_screen_never_filters_a_page_it_was_given():
    """The day travels to the query. A `.filter(` over the rows here would cut
    the page the server already cut."""
    assert not re.search(r"\.rows\s*\.\s*filter\(|\(d\?\.rows \?\? \[\]\)\.filter\(", DAY)
    code = DAY[DAY.index("import { useRef"):]            # past the file's own comment
    assert ".filter(" not in code


def test_a_click_on_a_day_opens_the_table_on_the_auto_trade_calendar_only():
    assert "<DayTrades" in PANEL and "trades &&" in PANEL
    # the Room strategies calendar has no ledger behind its days: not turned on
    rf = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    assert re.search(r"<DayCalendar days=\{d\.days\}", rf)
    call = rf[rf.index("<DayCalendar days={d.days}"):][:400]
    assert "trades" not in call.split("/>")[0]


def test_the_table_states_a_total_profit_and_uses_the_one_date_format():
    assert "TOTAL PROFIT" in DAY
    for banned in ("toLocale", "new Date(", "toISOString"):
        assert banned not in DAY, banned
    assert "r.when" in DAY and "r.opened" in DAY, "times come from the server's fmt_when"


def test_the_table_is_remounted_per_day_and_book():
    assert "key={`${picked}|${dry}`}" in PANEL, "a new day or book starts on page 1"
