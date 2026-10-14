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
    # THE PRINTED NAME FINDS ITS ROOM (found on the real site, Oct 14, 2026
    # 9:26am): "#09439DC2" answered 0 of 3,793 because the search read the id
    # "main", the one room whose id and printed name differ
    renamed = two_rooms.get("/api/trade/history/rooms?q=%2309439dc2&per_page=50").json()
    assert {r["id"] for r in renamed["rows"]} == {"AAAA1111", "SAME0000"}
    assert {r["room"] for r in renamed["rows"]} == {"main"}


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
    # "rooms" are the rooms EXAMINED — the label prints its count beside the
    # red line naming the one that was not (final review, Oct 14, 2026)
    assert [r["room"] for r in got["rooms"]] == ["main", "4FC03172"]


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
    assert "ALL_ROOMS" in s and 'export const ALL_ROOMS = "all";' in _web("lib/api.ts")
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
    assert s.count('if (id !== ALL_ROOMS) setProfile(id); else { setProfile("main"); setOnScreen(ALL_ROOMS); }') == 2
    # the Main tab's list is watched from the first frame (its name lives in
    # lib/loading.ts since Oct 14, 2026, with each tab's own list)
    assert "...MAIN_TAB_PANELS" in s[s.index("begin(["):s.index("setStarted(true)")]
    assert 'export const MAIN_TAB_PANELS: string[] = ["past trades"];' in _web("lib/loading.ts")


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


def test_a_date_wraps_in_its_own_cell_instead_of_running_into_the_next():
    """Found on the real site, Oct 14, 2026 9:27am: with the Room column the
    table has eleven columns, and "Oct 14, 2026 8:45am" ran into the closed
    time and the held time beside it (the cells were whitespace-nowrap in a
    fixed table). A date may wrap to two lines; it may never cover a neighbour."""
    th = _web("components/trade/TradeHistory.tsx")
    for cell in ('{r.opened ?? "—"}</TableCell>', "{r.when}</TableCell>", '{r.held ?? "—"}</TableCell>'):
        line = next(ln for ln in th.splitlines() if cell in ln)
        assert "whitespace-nowrap" not in line, cell
    # ...and the Room and id cells (final review, Oct 14, 2026: at 1,024 px
    # "#09439DC2" ran into the trade id beside it — 75 px of text in a 57 px
    # column; a guard is only as wide as its pattern)
    body = th[th.index("<TableBody"):th.index("</TableBody>")]
    room_cell = body[body.index("{allRooms && ("):body.index("{r.room_name")]
    assert "whitespace-nowrap" not in room_cell and "break-all" in room_cell
    at_id = body.index("title=\"copy this trade's id\"")
    id_cell = body[body.rindex("<TableCell", 0, at_id):at_id]
    assert "whitespace-nowrap" not in id_cell and "break-all" in id_cell
    # ...and EVERY cell (checking those fixes on the live site, Oct 14, 2026
    # 10:20am: at 1,024 px the strategy cell held "#FQJDT7UX" over
    # "elder_15m_sl08tp1", 96 px of unbroken text in a 62 px column, and ran
    # into the reason beside it — the third cell this table learned about one
    # at a time). No cell refuses to wrap, and the TABLE lets a word that
    # cannot fit break where it must; the rule is inherited, so a long coin,
    # reason or key in any cell is held without a line of its own here.
    for ln in body.splitlines():
        if "<TableCell" in ln:
            assert "whitespace-nowrap" not in ln, ln.strip()
    table = th[th.index("<Table fixed"):th.index("<TableHeader")]
    assert "[overflow-wrap:anywhere]" in table, table


def test_the_all_rooms_list_carries_no_room_and_waits_by_its_own_tab():
    """Final review, Oct 14, 2026, proven in a live browser: while
    #55D32617's tab was on screen the all-rooms calls carried
    `X-TA-Profile: 55D32617`, and on the Main tab #09439DC2's hidden panels
    counted as on screen and took the front request lanes. The list is no
    room: no header, and it is "on screen" only when the Main tab is."""
    ts = _web("lib/api.ts")
    assert 'if (room !== "main" && room !== ALL_ROOMS && _roomed(input)) {' in ts
    assert "const behind = _roomed(input) && room !== _onScreen;" in ts
    assert "export function setOnScreen(id: string): void { _onScreen = id; }" in ts
    assert "export function setProfile(id: string): void { _profile = id; _onScreen = id; }" in ts
    th = _web("components/trade/TradeHistory.tsx")
    assert "withProfile(ALL_ROOMS, () => tradeApi.historyRooms(dry, page, 5, q.trim()))" in th


def test_the_cover_names_only_what_the_tab_shows(tmp_path):
    """Checking the review fixes on the live site (Oct 14, 2026 10:20am,
    Safari's engine): the Main tab's own list loaded at 1.2 s and the cover
    stayed to 2.7 s saying "loading profit…" — a panel the Main tab does not
    have — and a room tab waited on "loading past trades…", the hidden Main
    list. With the API slow, as after a restart, that is 30 s and then a red
    "still not loading" for something not on screen. Runs the page's own
    code: each tab's cover names that tab's panels and nothing else."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "loading.mts").write_text(_web("lib/loading.ts"), encoding="utf-8")
    eight = ["summary", "positions", "strategies", "exchange keys",
             "trade history", "profit", "runner feed", "past trades"]
    waiting = [{"name": n, "waitedMs": 1000} for n in eight]
    (tmp_path / "run.mjs").write_text(
        'import { onTab, MAIN_TAB_PANELS, ROOM_PANELS } from "./loading.mts";\n'
        f"const w = {json.dumps(waiting)};\n"
        "console.log(JSON.stringify({ main: onTab(w, true).map((x) => x.name),\n"
        "  room: onTab(w, false).map((x) => x.name),\n"
        "  all: [...ROOM_PANELS, ...MAIN_TAB_PANELS] }));\n", encoding="utf-8")
    out = subprocess.run([node, str(tmp_path / "run.mjs")], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["main"] == ["past trades"]
    assert got["room"] == [n for n in eight if n != "past trades"]
    # every name a trade panel reports is on exactly one tab's list
    marked = set()
    for f in (ROOT / "webapp/src/components/trade").glob("*.tsx"):
        for call in re.findall(r"markReady\(([^)]*)\)", f.read_text(encoding="utf-8")):
            marked |= set(re.findall(r'"([^"]+)"', call))
    assert sorted(got["all"]) == sorted(marked) and len(got["all"]) == len(set(got["all"]))
    # ...and the screen draws the cover, the blur and the busy flag from the
    # TAB's list, while still watching every name from the first frame
    s = _web("components/trade/AutoTradeScreen.tsx")
    assert "begin([...ROOM_PANELS, ...MAIN_TAB_PANELS]);" in s
    assert "const shown = onTab(waitlist, room === ALL_ROOMS);" in s
    assert "<LoadingOverlay waitlist={shown} />" in s
    blur = s[s.index("const blurred = !started"):].split(";")[0]
    assert "shown" in blur and "waitlist" not in blur, blur
    assert "waitlist.length" not in s


def test_no_string_the_server_prints_says_main_for_a_room():
    """Wider than the seven spellings above (final review, Oct 14, 2026): no
    string the Python code can print says "Main" (docstrings and comments may
    tell the history), and the venue switch names a room as the screen does."""
    import ast
    hits = []
    for p in (ROOT / "tradingagents").glob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and n.body and isinstance(n.body[0], ast.Expr)
                and isinstance(getattr(n.body[0], "value", None), ast.Constant)}
        hits += [f"{p.name}:{n.lineno}" for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and id(n) not in docs and re.search(r"\bMain\b", n.value)]
    assert not hits, hits
    vs = (ROOT / "tradingagents/venue_switch.py").read_text(encoding="utf-8")
    assert "room {pid}" not in vs and "room {room}" not in vs
