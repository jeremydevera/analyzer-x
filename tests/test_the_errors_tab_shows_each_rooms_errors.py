"""Auto Trade -> Errors -> Deployed Tabs (operator, Oct 01, 2026: "can you
create a tab called 'Errors' then create a section Named 'Deployed Tabs'
there i should see errors ... i want it under backtest tab").

The log lines here are the shapes the rooms really wrote between Sep 30, 2026
7:26pm and Oct 01, 2026 9:51am, on ONE clock.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tradingagents import room_errors as re_

ROOT = Path(__file__).resolve().parents[1]

RATE = ("Oct 01, 2026 3:29am ERROR LIQUIDITY GATE: refusing crsi_30m_sl1tp12 on PARTI_USDT "
        "— the order book could not be read (code 510: Requests are too frequent, please try "
        "again later). No order placed.")
COST = ("Oct 01, 2026 3:30am ERROR LIQUIDITY GATE: refusing willr14_15m_sl1tp12 on EATSTOCK_USDT "
        "— round-trip cost 6.119% vs take-profit 1.20% = 510% of the target")
ENTRY = ("Oct 01, 2026 3:31am ERROR ENTRY GATE: refusing bb20_15m_sl1tp12 on FRMISTOCK_USDT at "
         "the last look — round-trip cost 0.651% vs take-profit 1.20%")
CHASE = "Oct 01, 2026 3:32am WARNING CHASE GUARD: skipping stoch14_15m_sl1tp12 PSXSTOCK_USDT — price moved"
FAIL = ("Oct 01, 2026 3:33am ERROR auto-trader cycle failed for CHYMSTOCK_USDT: no Min60 "
        "candles for CHYMSTOCK_USDT")


def scan(t):
    return f"{t} INFO scan VUG_USDT[paper]: 0 of 4 slot(s) open · flat"


def test_the_one_table_says_what_is_an_error_and_what_is_a_refusal():
    assert re_.classify("ERROR", RATE[RATE.index("LIQ"):]) == ("error", "rate_limit")
    assert re_.classify("ERROR", COST[COST.index("LIQ"):]) == ("safety", "cost_gate")
    assert re_.classify("ERROR", ENTRY[ENTRY.index("ENT"):]) == ("safety", "cost_gate")
    assert re_.classify("WARNING", CHASE[CHASE.index("CHA"):]) == ("safety", "chase")
    assert re_.classify("ERROR", FAIL[FAIL.index("auto"):]) == ("error", "cycle_failed")
    assert re_.classify("INFO", "scan VUG_USDT[paper]: flat") == ("", "")
    assert re_.classify("ERROR", "something nobody named") == ("error", "other_error")


@pytest.fixture
def rooms(tmp_path, monkeypatch):
    logs = {r: tmp_path / f"{r}.log" for r in ("main", "4FC03172", "B52662ED")}
    ledgers = {r: tmp_path / f"{r}.jsonl" for r in logs}
    for p in list(logs.values()) + list(ledgers.values()):
        p.write_text("", encoding="utf-8")
    monkeypatch.setattr(re_.profiles, "shown", lambda: ["main", "4FC03172"])
    monkeypatch.setattr(re_, "_log_path", lambda pid: logs[pid])
    monkeypatch.setattr(re_, "_ledger_path", lambda pid: ledgers[pid])
    monkeypatch.setattr(re_, "_alive", lambda pid: True)
    monkeypatch.setattr(re_, "_watcher_problem", lambda pid: [])
    re_._TAILS.clear()
    re_._STARTS.clear()
    yield logs, ledgers
    re_._TAILS.clear()
    re_._STARTS.clear()


def _write(p: Path, *lines: str, mode="a"):
    with p.open(mode, encoding="utf-8") as fh:
        fh.write("".join(x + "\n" for x in lines))


NOW = re_._when("Oct 01, 2026 9:51am")


def test_errors_are_grouped_refusals_are_counted_and_a_retired_room_has_no_row(rooms):
    logs, _ = rooms
    _write(logs["4FC03172"], scan("Oct 01, 2026 3:28am"), RATE, COST, ENTRY, CHASE, FAIL,
           FAIL.replace("3:33am", "3:34am"), scan("Oct 01, 2026 3:35am"))
    _write(logs["B52662ED"], RATE)                       # retired: no tab, no row
    r = re_.report(hours=0, now=NOW)
    assert [x["room"] for x in r["rooms"]] == ["main", "4FC03172"]
    room = r["rooms"][1]
    assert room["errors"] == 3 and room["safety"] == {"cost_gate": 2, "chase": 1}
    by = {g["kind"]: g for g in r["rows"]}
    assert by["cycle_failed"]["count"] == 2, "the same failure twice is one row, counted"
    assert by["rate_limit"]["label"] == "MEXC said too many requests"
    assert r["events"] == sum(g["count"] for g in r["rows"]) == 3


def test_the_log_is_read_once_then_only_its_new_lines(rooms):
    logs, _ = rooms
    _write(logs["4FC03172"], RATE)
    assert re_.report(hours=0, now=NOW)["events"] == 1
    t = re_._TAILS["4FC03172"]
    off = t.offset
    _write(logs["4FC03172"], FAIL)
    assert re_.report(hours=0, now=NOW)["events"] == 2
    assert t.offset > off and len(t.events) == 2, "nothing read twice"


def test_a_room_with_nothing_switched_on_is_idle_not_quiet(rooms):
    """#CC94D9FB logged its start at 7:26pm and its first scan at 8:30pm:
    that hour is idle. A gap BETWEEN SCANS is what counts."""
    logs, _ = rooms
    _write(logs["4FC03172"], "Sep 30, 2026 7:26pm INFO runner up",
           scan("Sep 30, 2026 8:30pm"), scan("Sep 30, 2026 8:31pm"),
           scan("Sep 30, 2026 9:20pm"))
    r = re_.report(hours=0, now=re_._when("Sep 30, 2026 9:21pm"))
    quiet = [g for g in r["rows"] if g["kind"] == "quiet"]
    assert len(quiet) == 1
    assert quiet[0]["message"] == ("no price check for 49 minutes (from Sep 30, 2026 8:31pm "
                                   "to Sep 30, 2026 9:20pm)")


def test_a_runner_started_again_is_an_error_and_the_first_start_is_not(rooms):
    logs, ledgers = rooms
    _write(ledgers["4FC03172"], json.dumps({"ts": NOW - 7200, "action": "runner_start"}),
           json.dumps({"ts": NOW - 600, "action": "runner_start"}))
    r = re_.report(hours=0, now=NOW)
    assert [(g["kind"], g["count"]) for g in r["rows"]] == [("restart", 1)]


def test_filters_and_paging_happen_on_the_server(rooms, monkeypatch):
    logs, _ = rooms
    lines = [FAIL.replace("CHYMSTOCK_USDT", f"X{chr(65 + i // 26)}{chr(65 + i % 26)}_USDT") for i in range(30)] + [RATE]
    _write(logs["4FC03172"], *lines)
    _write(logs["main"], RATE.replace("3:29am", "2:29am"))
    r = re_.report(hours=0, now=NOW, per=25)
    assert (r["groups"], r["pages"], len(r["rows"])) == (32, 2, 25)
    assert len(re_.report(hours=0, now=NOW, per=25, page=2)["rows"]) == 7
    only = re_.report(hours=0, now=NOW, kind="rate_limit")
    assert {g["room"] for g in only["rows"]} == {"main", "4FC03172"} and only["events"] == 2
    one = re_.report(hours=0, now=NOW, room="main")
    assert [x["room"] for x in one["rooms"]] == ["main"] and one["events"] == 1
    recent = re_.report(hours=7, now=NOW)            # 2:51am onward: main's 2:29am is out
    assert {g["room"] for g in recent["rows"]} == {"4FC03172"}


def test_the_route_refuses_a_room_without_a_tab():
    from fastapi.testclient import TestClient

    from tradingagents import api

    c = TestClient(api.app)
    assert c.get("/api/errors/rooms?room=B52662ED").status_code == 404
    assert c.get("/api/errors/rooms?kind=nonsense").status_code == 400


def test_errors_sits_under_auto_trade_and_the_screen_asks_the_server():
    """Oct 01, 2026: "make it udner auto trade instead" (it was first put
    under Backtest)."""
    nav = (ROOT / "webapp/src/layout/AppSidebar.tsx").read_text(encoding="utf-8")
    block = nav[nav.index('name: "Auto Trade"'):nav.index('name: "Candles"')]
    assert '{ name: "Auto Trade", path: "/trade" }' in block
    assert '{ name: "Errors", path: "/errors" }' in block
    assert nav.count('path: "/errors"') == 1, "one door to the page, not two"
    page = (ROOT / "webapp/src/app/(admin)/errors/page.tsx").read_text(encoding="utf-8")
    assert "DeployedTabsErrors" in page
    comp = (ROOT / "webapp/src/components/errors/DeployedTabsErrors.tsx").read_text(encoding="utf-8")
    assert ">Deployed Tabs<" in comp
    assert "api.roomErrors({ room, kind, hours, page })" in comp
    assert not re.search(r"d\.rows\.filter\(", comp), "filter where the data is"
    assert "fmtWhen" in comp and "new Date(" not in comp
