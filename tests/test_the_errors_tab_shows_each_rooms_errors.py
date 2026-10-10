"""Auto Trade -> Errors -> Deployed Tabs (operator, Oct 01, 2026: "can you
create a tab called 'Errors' then create a section Named 'Deployed Tabs'
there i should see errors ... i want it under backtest tab").

The log lines here are the shapes the rooms really wrote between Sep 30, 2026
7:26pm and Oct 07, 2026 7:34am; each test keeps its log, its trade record and
its `now` on ONE clock.
"""
from __future__ import annotations

import json
import re
import threading
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
    # the exchange is named by the setting, never spelled (Oct 10, 2026)
    assert by["rate_limit"]["label"] == "The exchange said too many requests"
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


class _GatedFile:
    """A trade record opened for reading whose `read` first passes `gate` —
    AFTER the reader has fixed where and how much to read, BEFORE it gets the
    bytes. That is the moment two first reads of one record must not share."""

    def __init__(self, fh, gate):
        self.fh, self.gate = fh, gate

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fh.close()

    def seek(self, n):
        return self.fh.seek(n)

    def read(self, n=-1):
        self.gate()
        return self.fh.read(n)


def _held(path: Path, gate) -> Path:
    """`path`, every read of which passes `gate` first."""

    class Held(type(path)):
        def open(self, *a, **kw):
            return _GatedFile(super().open(*a, **kw), gate)

    return Held(path)


WAIT_S = 1.0       # how long a held reader waits for a second one to arrive

# the shape of #4FC03172's record, Sep 30 to Oct 07, 2026: its first start,
# then eight restarts — three deploys on Oct 02, three power cuts, the Oct 06
# reset and the daytime-rule start
STARTS_4FC = ("Sep 30, 2026 7:26pm", "Oct 02, 2026 8:39am", "Oct 02, 2026 10:02am",
              "Oct 02, 2026 4:09pm", "Oct 03, 2026 2:06am", "Oct 04, 2026 11:24pm",
              "Oct 06, 2026 5:09am", "Oct 06, 2026 6:55pm", "Oct 07, 2026 5:14am")


def test_two_first_reads_at_once_count_each_restart_once(rooms):
    """The API started at Oct 07, 2026 7:25am answered the 7-day view, when
    checked, with 17 restarts for #4FC03172, #B2404C0B, #6B08FF64 and
    #CC94D9FB, whose trade records hold 9 starts each: 8 restarts. The route
    runs on parallel request threads and the API warms it on one more at
    start; two FIRST reads of one record both read it from its first byte
    into one list. That morning the second reader was a check of the API; in
    normal use it is the page's 30-second poll during the warm-up's read.

    FORCED, NOT HOPED FOR: the first reader is held inside its read until the
    second has asked for the same bytes. A second reader kept out by a lock
    never arrives, and the first goes on alone after WAIT_S."""
    _, ledgers = rooms
    rows = []
    for when in STARTS_4FC:                 # the rows as auto_trader writes them
        ts = int(re_._when(when))
        rows += [json.dumps({"ts": ts, "action": "runner_start",
                             "books": ["PAPER — simulated"]}),
                 json.dumps({"ts": ts + 60, "symbol": "VUG_USDT", "action": "gate_blocked",
                             "strategy": "stoch14_15m_sl1tp12"})]
    _write(ledgers["4FC03172"], *rows)
    inside, both, reads = threading.Event(), threading.Barrier(2), []

    def gate():
        reads.append(threading.current_thread().name)
        if len(reads) > 2:
            return
        inside.set()
        try:
            both.wait(timeout=WAIT_S)
        except threading.BrokenBarrierError:
            pass                        # the other reader was kept out: go on alone

    ledgers["4FC03172"] = _held(ledgers["4FC03172"], gate)
    answers, errors = {}, []

    def ask():
        try:
            r = re_.report(kind="restart", hours=0, now=re_._when("Oct 07, 2026 7:34am"))
            answers[threading.current_thread().name] = sum(g["count"] for g in r["rows"])
        except Exception as exc:                               # noqa: BLE001
            errors.append(repr(exc))

    warm = threading.Thread(target=ask, name="warm-up")
    warm.start()
    assert inside.wait(10), "the first read never reached the trade record"
    page = threading.Thread(target=ask, name="page")
    page.start()
    for th in (warm, page):
        th.join(10)
        assert not th.is_alive(), f"the {th.name} read never finished"
    assert not errors, errors
    cached = len(re_._STARTS["4FC03172"]["starts"])
    assert (answers, cached) == ({"warm-up": 8, "page": 8}, 9), \
        f"each start counted once, whoever reads the record first (reads: {reads})"


def test_a_slow_first_read_of_one_rooms_record_never_holds_up_another_room(rooms):
    """The lock is the ROOM's, never the whole tab's: #4FC03172's record was
    144 MB on its first read after a restart, and Main's answer must not wait
    behind it."""
    _, ledgers = rooms
    _write(ledgers["4FC03172"], json.dumps({"ts": NOW - 600, "action": "runner_start"}))
    _write(ledgers["main"], json.dumps({"ts": NOW - 7200, "action": "runner_start"}),
           json.dumps({"ts": NOW - 600, "action": "runner_start"}))
    inside, release = threading.Event(), threading.Event()

    def gate():
        inside.set()
        release.wait(10)

    ledgers["4FC03172"] = _held(ledgers["4FC03172"], gate)
    slow = threading.Thread(target=lambda: re_.report(room="4FC03172", hours=0, now=NOW))
    slow.start()
    try:
        assert inside.wait(10), "the slow read never reached the trade record"
        got: dict = {}
        main = threading.Thread(target=lambda: got.update(
            re_.report(room="main", kind="restart", hours=0, now=NOW)))
        main.start()
        main.join(5)
        assert not main.is_alive(), "Main's answer waited behind #4FC03172's first read"
        assert [(g["room"], g["count"]) for g in got["rows"]] == [("main", 1)]
    finally:
        release.set()
        slow.join(10)


def _scans(first: str, last: str) -> list[str]:
    """A scan line every minute from `first` to `last`, both included."""
    a, b = re_._when(first), re_._when(last)
    return [scan(re_._fmt(a + 60 * i)) for i in range(int((b - a) // 60) + 1)]


def _began(g: dict) -> float:
    """When the quiet stretch a row describes began, read from its own words."""
    return re_._when(re.search(r"\(from (.+?) to ", g["message"]).group(1))


def _covers(room: dict, rows: list) -> None:
    """The room card's "log read X to Y" holds the start of every quiet row
    the table lists beside it, and never reads backwards."""
    seen = room["examined"]
    said = f"log read {re_._fmt(seen['from'])} to {re_._fmt(seen['to'])}"
    for g in rows:
        assert seen["from"] <= _began(g), f"{said} beside {g['message']!r}"
    assert seen["from"] <= seen["to"], f"{said}: a span that ends before it begins"


# Oct 02, 2026 7:32pm the PC lost power: every room's last scan fell between
# 7:30pm and 7:32pm (7:30pm here), the next one at 2:06am, when the
# supervisor started all six again
POWER_CUT = (_scans("Oct 02, 2026 7:00pm", "Oct 02, 2026 7:30pm")
             + _scans("Oct 03, 2026 2:06am", "Oct 03, 2026 2:10am"))


def test_an_outage_that_began_before_the_window_is_still_shown(rooms):
    """Replayed: at Oct 03, 2026 2:10am, "last 6 hours" listed the restart and
    no outage: the scan lines were cut at the window's start (Oct 02, 2026
    8:10pm) BEFORE the gaps between them were measured, so a 396-minute
    stretch that ended 4 minutes earlier had lost its first scan; "last 24
    hours" did the same from about Oct 03, 2026 7:30pm until the restart
    itself left that window at Oct 04, 2026 2:06am. Found on Oct 07, 2026 by
    asking the API for 27 hours, a window the screen does not offer: 0 quiet
    rows, where 28 hours listed one per room. A stretch is in the window when
    it ENDS in it."""
    logs, ledgers = rooms
    _write(logs["4FC03172"], *POWER_CUT)
    _write(ledgers["4FC03172"],
           json.dumps({"ts": re_._when("Oct 02, 2026 4:09pm"), "action": "runner_start"}),
           json.dumps({"ts": re_._when("Oct 03, 2026 2:06am"), "action": "runner_start"}))
    at = re_._when("Oct 03, 2026 2:10am")
    r = re_.report(hours=6, kind="quiet", now=at)
    quiet = r["rows"]
    assert [(g["room"], g["message"]) for g in quiet] == [(
        "4FC03172",
        "no price check for 396 minutes (from Oct 02, 2026 7:30pm to Oct 03, 2026 2:06am)")]
    assert quiet[0]["first"] == quiet[0]["last"] == re_._when("Oct 03, 2026 2:06am"), \
        "the row sits at the stretch's END, which is inside the window"
    # the card beside that row read "log read Oct 02, 2026 8:10pm to Oct 03,
    # 2026 2:10am" in the first draft of this fix: a span that did not hold
    # the 7:30pm the row stands on
    _covers(r["rooms"][1], quiet)
    assert r["rooms"][1]["examined"] == {"from": re_._when("Oct 02, 2026 7:30pm"), "to": at}
    every = re_.report(hours=6, now=at)
    assert sorted(g["kind"] for g in every["rows"]) == ["quiet", "restart"], \
        "the outage is listed beside the restart that ended it"
    _covers(every["rooms"][1], [g for g in every["rows"] if g["kind"] == "quiet"])
    assert re_.report(hours=0, now=at)["rows"] == every["rows"], "the window cut nothing it holds"
    # with only the restarts asked for, no quiet row is listed and the card
    # keeps the window's own start
    only = re_.report(hours=6, kind="restart", now=at)["rooms"][1]["examined"]
    assert only == {"from": re_._when("Oct 02, 2026 8:10pm"), "to": at}


def test_a_runner_dead_longer_than_the_window_is_still_shown(rooms, monkeypatch):
    """NEVER HAPPENED YET: a runner whose last scan is 25 hours old has no
    scan inside "last 24 hours", so nothing was measured and the tab said
    "no errors" for a room that had been down all day."""
    logs, _ = rooms
    monkeypatch.setattr(re_, "_alive", lambda pid: pid != "4FC03172")
    _write(logs["4FC03172"], *_scans("Oct 06, 2026 3:45am", "Oct 06, 2026 4:15am"))
    r = re_.report(hours=24, kind="quiet", now=re_._when("Oct 07, 2026 5:15am"))
    assert [g["message"] for g in r["rows"]] == [
        "no price check for 1500 minutes (from Oct 06, 2026 4:15am to Oct 07, 2026 5:15am)"]
    room = r["rooms"][1]
    assert (room["room"], room["running"], room["errors"]) == ("4FC03172", False, 1)
    # this room's card always read "log read Oct 06, 2026 5:15am to Oct 06,
    # 2026 4:15am" here — the window's start to the last line read,
    # backwards — and the first draft of this fix put it beside that row
    _covers(room, r["rows"])
    last = re_._when("Oct 06, 2026 4:15am")
    assert room["examined"] == {"from": last, "to": last}, \
        "all this answer stands on in the log is its last scan, at 4:15am"


def test_an_answer_as_of_a_past_moment_does_not_see_the_scans_after_it(rooms, monkeypatch):
    """The same power cut answered as of Oct 03, 2026 1:00am, while the PC was
    still off: 330 minutes so far, and still going. Measuring over every scan
    read must not let an answer as of 1:00am know the stretch ends at 2:06am."""
    logs, _ = rooms
    monkeypatch.setattr(re_, "_alive", lambda pid: pid != "4FC03172")
    _write(logs["4FC03172"], *POWER_CUT)
    r = re_.report(hours=1, kind="quiet", now=re_._when("Oct 03, 2026 1:00am"))
    assert [g["message"] for g in r["rows"]] == [
        "no price check for 330 minutes (from Oct 02, 2026 7:30pm to Oct 03, 2026 1:00am)"]


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


def test_gates_too_many_requests_is_the_same_kind_as_mexcs():
    """Gate answers a rate limit with HTTP 429 TOO_MANY_REQUESTS where MEXC
    said code 510 (Oct 10, 2026, the move to Gate) — one row on the tab."""
    from tradingagents import room_errors as re_

    line = ("ERROR scan BTC_USDT failed: 429 TOO_MANY_REQUESTS: slow down "
            "(https://api.gateio.ws/api/v4/futures/usdt/candlesticks)")
    assert re_.classify("ERROR", line)[1] == "rate_limit"
