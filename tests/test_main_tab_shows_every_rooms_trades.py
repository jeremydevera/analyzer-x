"""The Main tab is every room strategy's past trades; the room that was Main
is #09439DC2 (operator, Oct 14, 2026: "the main tab is a room strategy so what
i want is to assign and id for it and create a new tab for it / the main tab
is for seeing all room strategy past trades"). Spec:
docs/superpowers/specs/2026-10-14-main-tab-all-rooms-past-trades-design.md"""
from __future__ import annotations

import re
from pathlib import Path

from tradingagents import forecast_rules as fr, forecast_v2_daily as fd, profiles

ROOT = Path(__file__).resolve().parents[1]


def test_the_room_that_was_main_is_named_by_its_rules():
    assert profiles.name_of("main") == "#09439DC2"
    assert profiles.name_of("55D32617") == "#55D32617"
    assert profiles.name_of("NOPE1234") == "#NOPE1234"
    assert profiles.MAIN == "main", "only the NAME changes; the id and folder stay"
    # 09439DC2 is its rules' id, worked out the way the 1-4 day rooms were named
    assert fr.rule_id(fd.room_rules()["main"]) == profiles.MAIN_DISPLAY_ID == "09439DC2"


def test_no_module_prints_main_for_a_room():
    """Seven Python places spelled the name by hand ("Main" if pid == MAIN);
    every printed room name now comes from profiles.name_of."""
    hand = re.compile(r'"Main" if \w+ ==|\(profiles\.MAIN, "Main"|r != "Main"')
    found = [f"{p.name}:{i}" for p in (ROOT / "tradingagents").glob("*.py")
             for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
             if hand.search(line)]
    assert not found, found


# ------------------------------------------------ the all-rooms server route
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import tradingagents.auto_trader as at  # noqa: E402


def _exit(ts, pnl, tid, *, sym="KITE_USDT", strat="squeeze_1h_sl3tp3", dry=True):
    return {"ts": ts, "action": "exit", "symbol": sym, "strategy": strat, "dry_run": dry,
            "why": "TP" if pnl > 0 else "SL", "pnl_est": pnl, "trade_id": tid,
            "opened_at": ts - 600, "held_s": 600, "side": "LONG"}


@pytest.fixture
def two_rooms(write_ledger, monkeypatch):
    """#09439DC2 (id main) and #55D32617 on ONE timeline; #4FC03172 has no
    record yet — which is not 'unreadable', just no trades."""
    monkeypatch.setattr(profiles, "shown", lambda: ["main", "55D32617", "4FC03172"])
    write_ledger([_exit(1_000, 1.0, "AAAA1111"), _exit(3_000, -0.5, "SAME0000")])
    with profiles.using("55D32617"):
        write_ledger([_exit(2_000, 2.0, "BBBB2222"), _exit(3_000, 0.25, "SAME0000")])
    from tradingagents.api import app
    return TestClient(app)


def test_every_room_in_one_list_newest_first_with_its_room(two_rooms):
    got = two_rooms.get("/api/trade/history/rooms?dry=true&per_page=50").json()
    assert [(r["id"], r["room_name"]) for r in got["rows"]] == [
        ("SAME0000", "#55D32617"), ("SAME0000", "#09439DC2"),   # same second: room order, newest first
        ("BBBB2222", "#55D32617"), ("AAAA1111", "#09439DC2")]
    # ONE running total across the rooms, oldest first
    assert [r["running"] for r in reversed(got["rows"])] == [1.0, 3.0, 2.5, 2.75]
    assert got["total"] == 4 and got["examined"] == 4 and got["unreadable"] == []
    assert [r["room"] for r in got["rooms"]] == ["main", "55D32617", "4FC03172"]


def test_a_room_id_trade_id_or_strategy_id_finds_its_trades(two_rooms):
    by_room = two_rooms.get("/api/trade/history/rooms?q=%2355d32617&per_page=50").json()
    assert {r["id"] for r in by_room["rows"]} == {"BBBB2222", "SAME0000"}
    assert {r["room"] for r in by_room["rows"]} == {"55D32617"}
    same = two_rooms.get("/api/trade/history/rooms?q=SAME0000&per_page=50").json()
    assert sorted(r["room_name"] for r in same["rows"]) == ["#09439DC2", "#55D32617"], \
        "one trade id in two rooms is two trades"
    none = two_rooms.get("/api/trade/history/rooms?q=ZZZZ9999").json()
    assert none["total"] == 0 and none["examined"] == 4


def test_pages_are_cut_on_the_server(two_rooms):
    p2 = two_rooms.get("/api/trade/history/rooms?dry=true&per_page=3&page=2").json()
    assert (p2["page"], p2["pages"], len(p2["rows"])) == (2, 2, 1)
    assert p2["rows"][0]["id"] == "AAAA1111"


def test_a_room_that_raises_is_named_and_the_others_still_show(two_rooms, monkeypatch):
    real = at.ledger_trades

    def boom(ts=0):
        if profiles.current() == "55D32617":
            raise OSError("the disk said no")
        return real(ts)
    monkeypatch.setattr(at, "ledger_trades", boom)
    got = two_rooms.get("/api/trade/history/rooms?dry=true&per_page=50").json()
    assert [u["name"] for u in got["unreadable"]] == ["#55D32617"]
    assert {r["room"] for r in got["rows"]} == {"main"}


def test_the_one_room_history_is_unchanged(two_rooms):
    one = two_rooms.get("/api/trade/history?dry=true&per_page=50").json()
    assert [r["id"] for r in one["rows"]] == ["SAME0000", "AAAA1111"]
    assert [r["running"] for r in one["rows"]] == [0.5, 1.0]
    assert "room" not in one["rows"][0]


# ------------------------------------------------------------- the page
def _web(rel: str) -> str:
    return (ROOT / "webapp/src" / rel).read_text(encoding="utf-8")


def test_the_main_tab_draws_only_the_all_rooms_list():
    s = _web("components/trade/AutoTradeScreen.tsx")
    assert 'const ALL_ROOMS = "all";' in s
    assert "<TradeHistory allRooms active={room === ALL_ROOMS} />" in s
    body = s[s.index("<AllRoomsBody"):]
    body = body[:body.index("</AllRoomsBody>")]
    for panel in ("SummaryRibbon", "PositionsPanel", "StrategiesGrid", "WatcherPanel",
                  "CredentialsPanel", "PnlPanel", "FeedPanel"):
        assert panel not in body, panel
    # a browser that saved the old "main" opens the SAME room (#09439DC2);
    # nothing saved, or something unknown, opens the all-rooms Main tab
    first = s[s.index("function firstRoom"):s.index("/** ONE ROOM'S PANELS")]
    assert "let id = ALL_ROOMS;" in first
    assert 'if (id !== ALL_ROOMS) setProfile(id); else setProfile("main");' in s
    assert '"past trades"' in s[s.index("begin(["):s.index("setStarted(true)")]


def test_one_name_for_the_room_that_was_main_on_every_screen():
    ts = _web("lib/api.ts")
    assert '{ id: "main", name: "#09439DC2", display_id: "09439DC2" },' in ts
    assert "export function roomName(id: string): string" in ts
    for rel in ("components/errors/DeployedTabsErrors.tsx", "components/forecast/ForecastV2.tsx",
                "components/forecast/RoomForecasts.tsx", "components/trade/AutoTradeScreen.tsx"):
        src = _web(rel)
        assert '=== "main" ? "Main"' not in src and '"main" ? p.name' not in src, rel
        assert "const roomName = " not in src, rel


def test_the_all_rooms_list_asks_the_server_and_waits_behind_its_tab():
    th = _web("components/trade/TradeHistory.tsx")
    assert "tradeApi.historyRooms(dry, page, 5, q.trim())" in th
    assert "allRooms && !active ? 15_000 : 5_000" in th
    assert 'markReady(allRooms ? "past trades" : "trade history")' in th
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", th, flags=re.S)        # code, not the comments
    assert ".filter(" not in code, "the server searches and pages"
    assert 'historyRooms: (dry: boolean, page = 1, per_page = 5, q = "") =>' in _web("lib/api.ts")
