"""Two asks of Sep 29, 2026: "paginate the Watcher" and "the Paper · open
tile i want to see the pnl for my demo overall starting when i did demo
trade".

The watcher's decisions are PAGED BY THE SERVER. The screen used to receive
the newest 50 only, so a pager drawn over that would have ended at page 5
while the log held 97 decisions (measured on this PC at 1:20pm) — a filter
after a window (CLAUDE.md kit item G)."""
from __future__ import annotations

import json

import pytest

from tradingagents import strategy_watcher as sw


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "LOG", tmp_path / "w.jsonl")
    sw._COUNT.update(path=None, size=0, lines=0)
    return tmp_path / "w.jsonl"


def _write(n, start=0):
    sw._log([{"at": i, "mode": "act", "action": "off", "id": f"X{i}", "why": "x" * 300}
             for i in range(start, start + n)])


def test_page_one_is_the_newest_ten_and_the_total_is_every_decision(log):
    _write(97)
    p = sw.decisions_page(1)
    assert p["decisions_total"] == 97 and p["decisions_pages"] == 10
    assert [d["id"] for d in p["decisions"]] == [f"X{i}" for i in range(96, 86, -1)]


def test_the_last_page_reaches_the_first_decision(log):
    _write(97)
    last = sw.decisions_page(10)
    assert [d["id"] for d in last["decisions"]][-1] == "X0"
    assert len(last["decisions"]) == 7


def test_a_page_deep_in_a_big_log_is_read_right(log):
    """Far past one 64 KB read block: 3,000 decisions of ~400 bytes."""
    _write(3000)
    p = sw.decisions_page(250)
    assert [d["id"] for d in p["decisions"]] == [f"X{i}" for i in range(509, 499, -1)]


def test_the_count_follows_the_log_as_it_grows(log):
    _write(5)
    assert sw.decisions_page(1)["decisions_total"] == 5
    _write(8, start=5)
    p = sw.decisions_page(1)
    assert p["decisions_total"] == 13 and p["decisions"][0]["id"] == "X12"


def test_a_page_past_the_end_is_the_last_page(log):
    _write(12)
    p = sw.decisions_page(99)
    assert p["decisions_page"] == 2 and [d["id"] for d in p["decisions"]] == ["X1", "X0"]


def test_an_empty_log_is_one_empty_page(log):
    p = sw.decisions_page(1)
    assert p["decisions"] == [] and p["decisions_total"] == 0 and p["decisions_pages"] == 1


def test_the_route_asks_for_the_page():
    api = open("tradingagents/api.py", encoding="utf-8").read()
    assert "def watcher_status(page: int = 1, per: int = 10)" in api
    assert "return sw.status(page, per)" in api
    client = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert "watcher: (page = 1) => get<Watcher>(`/api/trade/watcher?page=${page}`)" in client
    panel = open("webapp/src/components/trade/WatcherPanel.tsx", encoding="utf-8").read()
    assert "api.watcher(dPage)" in panel
    assert "Decisions · {w.decisions_total}" in panel
    assert "Running now · {w.slots.length}" in panel


# ---------------------------------------------------------- the demo tile
def test_the_practice_all_time_record_starts_at_its_first_trade():
    from tradingagents.api import _all_time_records

    rows = [
        {"ts": 100, "action": "gate_blocked", "dry_run": True},
        {"ts": 200, "action": "enter", "dry_run": True},
        {"ts": 250, "action": "exit", "dry_run": False, "pnl_est": 4.0},
        {"ts": 300, "action": "exit", "dry_run": True, "pnl_est": 1.5},
        {"ts": 400, "action": "exit", "dry_run": True, "pnl_est": -2.25},
        {"ts": 500, "action": "exit", "dry_run": True, "pnl_est": 0.0},
    ]
    real, paper = _all_time_records(rows)
    assert real == 4.0, "real money is never mixed into the practice figure"
    assert paper == {"total": -0.75, "wins": 1, "losses": 2, "trades": 3, "since": 200}


def test_the_tile_prints_the_practice_money_and_when_it_started():
    src = open("webapp/src/components/trade/SummaryRibbon.tsx", encoding="utf-8").read()
    assert 'label="Paper · all time"' in src
    assert "money(s.paper_all_time.total)" in src
    assert "since ${fmtWhen(s.paper_all_time.since)}" in src
    assert "${s.paper_positions.length} open" in src, "the open count is still there"


def test_two_rooms_counting_at_once_never_read_a_negative_length(tmp_path, monkeypatch):
    """Oct 07, 2026 7:52pm: the site failed with "read length must be
    non-negative" in _log_lines. The count is ONE memory for every room, and
    the API answers rooms on parallel threads: room A checked its log was
    bigger than the count, then room B swapped in its own (bigger) count
    before A read, so A asked for a negative number of bytes. Room B runs
    exactly between A's check and A's read here — the moment A opens its log."""
    import threading

    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_bytes(b"{}\n" * 3)
    b.write_bytes(b"{}\n" * 500)
    sw._COUNT.update(path=None, size=0, lines=0)
    monkeypatch.setattr(sw, "_COUNTS", {})
    room = threading.local()
    calls = {"a": 0}

    def path():
        if getattr(room, "name", "a") == "b":
            return b
        calls["a"] += 1
        if calls["a"] == 3:                     # A is about to read
            def other():
                room.name = "b"
                sw._log_lines()
            t = threading.Thread(target=other)
            t.start()
            t.join(timeout=0.5)
        return a

    monkeypatch.setattr(sw, "_log_path", path)
    assert sw._log_lines() == 3
    room.name = "b"
    assert sw._log_lines() == 500
