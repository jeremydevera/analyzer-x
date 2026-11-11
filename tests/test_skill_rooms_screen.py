"""THE SKILL ROOMS' WIRING, ROUTES AND SCREENS (Nov 11, 2026; docs/superpowers/specs/
2026-11-10-skill-rooms-design.md, "6. What a follower room's tab shows").

The follower and the daily chain are started by the API's supervisor (each in its own thread: the
chain's build step can block for hours), the room tab reads them through two routes, and the tab
says in words what the follower is doing instead of showing a runner it does not have.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import tradingagents.auto_trader as at
from tradingagents import profiles

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
API = (REPO / "tradingagents/api.py").read_text(encoding="utf-8")
WEB = REPO / "webapp/src"
RIBBON = (WEB / "components/trade/SummaryRibbon.tsx").read_text(encoding="utf-8")
SCREEN = (WEB / "components/trade/AutoTradeScreen.tsx").read_text(encoding="utf-8")
PANEL_PATH = WEB / "components/trade/V4FollowPanel.tsx"
V4TAB = (WEB / "components/backtest-v4/V4Strategies.tsx").read_text(encoding="utf-8")
ROOM = "D7EN8BNV"
OTHER = "main"      # a watcher room still on screen (the old ten are off since Nov 11, 2026)


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from tradingagents import api
    from tradingagents.dataflows import exchange as fx
    from tradingagents.dataflows import mexc_credentials as cred

    monkeypatch.setattr(cred, "load_into_env", lambda: None)
    monkeypatch.setattr(fx, "has_credentials", lambda: False)
    monkeypatch.setattr(fx, "open_positions", lambda symbol=None: [])
    monkeypatch.setattr(fx, "last_prices", lambda: {"AAA_USDT": 101.0})
    monkeypatch.setattr(fx, "contract_spec", lambda s: {"contractSize": 1.0})
    monkeypatch.setattr(at, "runner_pid", lambda: None)
    return TestClient(api.app)


def _hdr(pid):
    return {"X-TA-Profile": pid}


# ------------------------------------------------------------------ the supervisor
def test_supervisor_starts_v4_threads():
    for mod, name in (("v4_daily", "v4-daily"), ("v4_follow", "v4-follow")):
        block = (f"from tradingagents import {mod} as _")
        assert block in API, mod
        assert f'if not any(t.name == "{name}" for t in _th.enumerate()):' in API, name
        assert re.search(rf'_th\.Thread\(target=_\w+\.tick, name="{name}", daemon=True\)\.start\(\)', API), name
    # in the daily chain's own thread, never inline in the 30 s loop: a build step can block 3 hours
    assert "_v4d.tick()" not in API and "v4_daily.tick()" not in API
    assert "target=_v4d.tick" in API and "target=_v4f.tick" in API


# ------------------------------------------------------------------ the routes
def test_follow_route_answers_for_a_follower_room_only(client, monkeypatch):
    from tradingagents import v4_daily, v4_follow

    status = {"last_pass_s": 1_000.0, "last_candle_ms": 900_000, "held_at": None, "why": None,
              "filled_in": 0, "errors": [], "fallback_from": None, "agreement": None,
              "switched_on": [{"sid": i, "id": f"ID{i:03d}", "coin": "AAA", "tf": "1h", "strategy": "x",
                               "label": "x test", "n": 25, "wins": 24} for i in range(23)]}
    monkeypatch.setattr(v4_follow, "status", lambda pid, *a, **k: dict(status))
    monkeypatch.setattr(v4_daily, "status", lambda: {"phase": "done", "why": "the list landed"})
    got = client.get("/api/trade/v4-follow", headers=_hdr(ROOM)).json()
    assert got["follows"] == "v4"
    assert got["rule_words"].startswith("Every day, switch on each any-timeframe strategy")
    assert "90% or more of at least 20 trades in its last 30 days" in got["rule_words"]
    assert got["daily"]["phase"] == "done"
    # the list is paged by the SERVER, ten at a time
    assert got["total_on"] == 23 and len(got["switched_on"]) == 10 and got["pages"] == 3
    assert got["switched_on"][0]["win_rate"] == pytest.approx(96.0)
    p3 = client.get("/api/trade/v4-follow?page=3", headers=_hdr(ROOM)).json()
    assert [r["id"] for r in p3["switched_on"]] == ["ID020", "ID021", "ID022"]
    # a room with a runner has no follower
    assert client.get("/api/trade/v4-follow", headers=_hdr(OTHER)).json() == {"follows": None}


def test_the_daily_route_only_reads(client, monkeypatch):
    from tradingagents import v4_daily

    monkeypatch.setattr(v4_daily, "status", lambda: {"phase": "unreadable", "why": "the state cannot be read"})
    monkeypatch.setattr(v4_daily, "_write", lambda st: (_ for _ in ()).throw(AssertionError("a route wrote")))
    got = client.get("/api/v4/daily").json()
    assert got["phase"] == "unreadable"


def test_summary_says_follows_for_a_follower_room(client, monkeypatch):
    from tradingagents import v4_follow

    monkeypatch.setattr(v4_follow, "status", lambda pid, *a, **k: {
        "last_pass_s": 5_000_000_000.0, "last_candle_ms": 900_000, "held_at": None, "why": None,
        "filled_in": 0, "errors": [], "switched_on": [], "fallback_from": None, "agreement": None})
    got = client.get("/api/trade/summary", headers=_hdr(ROOM)).json()
    assert got["follows"] == "v4"
    f = got["follow"]
    assert f["last_candle_ms"] == 900_000 and f["next_candle_s"] == 5_000_000_400   # the next 15-minute close after the pass
    assert f["why"] is None and f["held_at"] is None and f["stale"] is False
    plain = client.get("/api/trade/summary", headers=_hdr(OTHER)).json()
    assert plain["follows"] is None and plain["follow"] is None


def test_summary_marks_an_old_pass_stale(client, monkeypatch):
    from tradingagents import v4_follow

    monkeypatch.setattr(v4_follow, "status", lambda pid, *a, **k: {
        "last_pass_s": 1_000.0, "last_candle_ms": 900_000, "held_at": None,
        "why": "the last pass was Jan 01, 1970 12:16am", "filled_in": 0, "errors": [],
        "switched_on": [], "fallback_from": None, "agreement": None})
    f = client.get("/api/trade/summary", headers=_hdr(ROOM)).json()["follow"]
    assert f["stale"] is True and f["why"].startswith("the last pass was")


def test_positions_route_shows_a_follower_position(client, monkeypatch):
    """A slot written the way the follower writes it (strategy v4_<id>, no target, a size that may
    be blank) comes back from the positions and summary routes with coin, side, entry and stop."""
    with profiles.using(ROOM):
        slot = at.state_key("AAA_USDT", True, f"v4_TESTAAA1")
        at.save_state({slot: {"step": 0, "last_ts": {}, "position": {
            "side": 1, "vol": None, "entry": 100.0, "tp": None, "sl": 97.0, "margin": 5.0,
            "strategy": "v4_TESTAAA1", "entry_ts": 1_700_000_000, "opened_at": 1_700_000_060,
            "trade_id": "TID1", "dry": True, "bracket": True, "v4_id": "TESTAAA1"}}}, keys=[slot])
    pos = client.get("/api/trade/positions", headers=_hdr(ROOM))
    assert pos.status_code == 200, pos.text
    (row,) = pos.json()["paper"]
    assert row["coin"] and row["side"] in ("LONG", "long", 1) and row["entry"] == 100.0
    assert row["sl"] == 97.0 and row["tp"] is None
    summ = client.get("/api/trade/summary", headers=_hdr(ROOM))
    assert summ.status_code == 200, summ.text
    (p,) = summ.json()["paper_positions"]
    assert p["symbol"] == "AAA_USDT" and p["side"] == "LONG" and p["entry"] == 100.0
    assert p["strategy"] == "v4_TESTAAA1"


def test_the_room_popup_route_names_the_rule(client):
    rooms = {r["id"]: r for r in client.get("/api/trade/profiles").json()["profiles"]}
    assert rooms[ROOM]["follows"] == "v4"
    assert rooms[ROOM]["rule_words"].startswith("Every day, switch on each")
    assert "rule_words" not in rooms[OTHER] or not rooms[OTHER]["rule_words"]


# ------------------------------------------------------------------ the screens
def test_ribbon_has_the_follow_line_and_no_runner_buttons_for_followers():
    assert '"PAPER · follows Backtest v4"' in RIBBON and "` · last candle " in RIBBON
    assert "` · next " in RIBBON
    assert "not following: " in RIBBON
    assert "waiting for today's list (" in RIBBON
    assert "are filled in when it lands" in RIBBON
    assert "s.follows" in RIBBON
    # the runner's controls sit in the branch that is NOT a follower room
    i = RIBBON.index("s.follows")
    assert RIBBON.index("STOP RUNNER") > i and RIBBON.index("arm PANIC") > i
    assert "fmtWhen(" in RIBBON and "next_candle_s" in RIBBON


def test_screen_puts_the_follow_panel_in_place_of_the_watcher_and_keys(as_shipped):
    assert PANEL_PATH.is_file()
    assert 'import V4FollowPanel from "./V4FollowPanel"' in SCREEN
    assert "follows ? <V4FollowPanel />" in SCREEN or "follows ? (\n" in SCREEN
    assert "<WatcherPanel />" in SCREEN and "<CredentialsPanel />" in SCREEN
    api_ts = (WEB / "lib/api.ts").read_text(encoding="utf-8")
    for pid in ("D7EN8BNV", "RSS7CUKH", "7T3VJU82"):
        assert re.search(rf'id: "{pid}", name: "#{pid}", follows: "v4"', api_ts), pid
    # a watcher room is no follower; the ten older ones (profiles.OFF_NOV11) have no tab at all
    block = api_ts.split("export const PROFILES", 1)[1].split("];", 1)[0]
    # Nov 11, 2026 ("remove 09439DC2"): the room `main` has no tab either
    assert 'id: "main"' not in block
    for old in profiles.OFF_NOV11:
        assert f'id: "{old}"' not in block, old


def test_panel_columns_and_cost_line():
    panel = PANEL_PATH.read_text(encoding="utf-8")
    for col in ("Switched on today", "ID", "Coin", "Timeframe", "Strategy", "Last ${d.window_days} days", "Trades", "Wins",
                "Win rate"):
        assert col in panel, col
    assert "trades the same as the backtest" in panel and "apart" in panel
    assert ("Every trade pays its coin's usual gap, not its own minute's order book (100% typical cost) · "
            "no trade is refused by the runner's cost check · no order is placed") in panel
    assert "rule_words" in panel and "daily" in panel
    # the Backtest v4 tab says when it is refreshed and what it does not charge
    assert "refreshed every day" in V4TAB
    assert "usual gap" in V4TAB and "order book" in V4TAB
    assert "/api/v4/daily" in V4TAB


def test_the_popup_names_what_a_follower_follows():
    assert "follows Backtest v4: " in SCREEN
    assert "r.follows" in SCREEN


def test_no_client_filter_and_one_date_format():
    for src in (PANEL_PATH.read_text(encoding="utf-8"), RIBBON, V4TAB):
        assert not re.search(r"ans\??\.rows\??\.filter\(|rows\.filter\(|switched_on\??\.filter\(", src)
        assert "new Date(" not in src
        assert "toLocaleDateString" not in src and "toLocaleTimeString" not in src
    panel = PANEL_PATH.read_text(encoding="utf-8")
    assert "fmtWhen" in panel and ".filter(" not in panel and ".slice(" not in panel
    assert "toISOString" not in panel and "new Date(" not in panel


# ------------------------------------------------------------------ fix round 1
def test_the_deploy_grid_is_not_rendered_for_a_follower_room():
    assert "{!follows && <StrategiesGrid />}" in SCREEN
    assert "        <StrategiesGrid />\n" not in SCREEN        # never unconditional


def test_settings_writes_are_refused_for_a_follower_room_only(client, monkeypatch, tmp_path):
    monkeypatch.setattr(at, "SETTINGS_PATH", tmp_path / "auto_trade.json")
    want = "#D7EN8BNV is followed by Backtest v4's engine; it has no strategies to switch on"
    posts = [("/api/trade/settings", {"strategy_books": {"x": ["real"]}}),
             ("/api/trade/losscap/reset", {"confirm": True}),
             ("/api/trade/record/reset", {"confirm": True, "books": ["paper"]}),
             ("/api/trade/watcher", {"mode": "act"}),
             ("/api/trade/runner/start", {})]
    for path, body in posts:
        r = client.post(path, json=body, headers=_hdr(ROOM))
        assert r.status_code == 409, path
        assert r.json()["detail"] == want, path
    with profiles.using(ROOM):
        assert not at._pp(at.SETTINGS_PATH).exists(), "nothing was written into the follower room"
    ok = client.post("/api/trade/settings", json={"strategy_books": {}}, headers=_hdr(OTHER))
    assert ok.status_code == 200, ok.text


def test_the_daily_phase_is_said_in_plain_words():
    from tradingagents import v4_daily as vd
    from tradingagents.positions_view import fmt_when

    t = 1_800_000_000.0
    assert vd.words({"phase": "idle", "next_s": t}) == f"next refresh {fmt_when(t)}"
    assert vd.words({"phase": "dispatch"}) == "measuring on GitHub"
    assert vd.words({"phase": "running"}) == "measuring on GitHub"
    assert vd.words({"phase": "collect"}) == "collecting the results"
    assert vd.words({"phase": "build"}) == "rebuilding Backtest v4"
    assert vd.words({"phase": "lists"}) == "choosing today's strategies"
    assert vd.words({"phase": "agree"}) == "choosing today's strategies"
    assert vd.words({"phase": "done", "landed_s": t}) == f"done {fmt_when(t)}"
    assert vd.words({"phase": "given_up", "error": "collect: GitHub refused"}) == "gave up: collect: GitHub refused"
    assert vd.words({"phase": "unreadable", "error": "x.json cannot be read"}) == \
        "its record cannot be read: x.json cannot be read"
    # every phase the chain can be in has plain words, none is the bare phase name
    for ph in ("idle", "dispatch", "running", "collect", "build", "lists", "agree", "done", "given_up",
               "unreadable"):
        w = vd.words({"phase": ph, "next_s": t, "landed_s": t, "error": "e"})
        assert w != ph and w, ph


def test_the_daily_route_and_both_screens_print_the_words_not_the_phase(client, monkeypatch):
    from tradingagents import v4_daily

    monkeypatch.setattr(v4_daily, "read", lambda: {"phase": "build", "why": "x"})
    got = client.get("/api/v4/daily").json()
    assert got["phase"] == "build" and got["words"] == "rebuilding Backtest v4"
    panel = PANEL_PATH.read_text(encoding="utf-8")
    assert "daily.words" in panel and "daily.phase" not in panel
    assert "daily.words" in V4TAB and "daily.phase" not in V4TAB


# ------------------------------------------------------------------ final review (Nov 11, 2026)
@pytest.fixture
def v4home(tmp_path, monkeypatch):
    from tradingagents import stores

    home = tmp_path / "v4"
    monkeypatch.setattr(stores, "V4", stores.Store(**{**stores.V4.__dict__, "home": home,
                                                      "rows_db": home / "rows.db"}))
    (home / "rooms").mkdir(parents=True)
    return home


def _today():
    import time

    return int(time.time()) // 86400 * 86400


def test_before_todays_list_lands_the_panel_never_says_nothing_passes(client, monkeypatch, v4home):
    """IMPORTANT: until the day's list landed, the panel said "no strategy passes this rule today, so
    the room opens nothing" - a claim about a list nobody had made yet."""
    import json

    from tradingagents import v4_daily, v4_follow

    monkeypatch.setattr(v4_daily, "status", lambda: {"phase": "running", "words": "measuring on GitHub",
                                                     "why": "measuring 1,050 coins on GitHub: run 101 on me"})
    got = client.get("/api/trade/v4-follow", headers=_hdr(ROOM)).json()
    assert got["today_landed"] is False and got["total_on"] == 0
    assert got["today_why"] == "measuring 1,050 coins on GitHub: run 101 on me"
    v4_follow.list_path(_today()).write_text(json.dumps({"day_s": _today(), "fallback_from": None, "rooms": {
        ROOM: [{"id": "ONE", "coin": "AAA", "tf": "1h", "strategy": "x", "label": "x", "n": 25, "wins": 24}]}}),
        encoding="utf-8")
    got = client.get("/api/trade/v4-follow", headers=_hdr(ROOM)).json()
    assert got["today_landed"] is True and got["total_on"] == 1
    v4_follow.list_path(_today()).write_text(json.dumps({"day_s": _today(), "fallback_from": None,
                                                          "rooms": {ROOM: []}}), encoding="utf-8")
    got = client.get("/api/trade/v4-follow", headers=_hdr(ROOM)).json()
    assert got["today_landed"] is True and got["total_on"] == 0, "landed and empty: nothing passes, truly"
    panel = PANEL_PATH.read_text(encoding="utf-8")
    assert "today's list has not landed yet (" in panel and "d.today_why" in panel
    assert panel.index("d.today_landed === false") < panel.index("no strategy passes this rule today")


def test_the_panel_labels_come_from_the_data(client, monkeypatch, v4home):
    import json

    from tradingagents import v4_daily, v4_follow
    from tradingagents.positions_view import fmt_when

    monkeypatch.setattr(v4_daily, "status", lambda: {"phase": "given_up", "words": "gave up: x", "why": "x"})
    today, day = _today(), 86400
    v4_follow.list_path(today).write_text(json.dumps({"day_s": today, "fallback_from": "2026-11-09",
                                                       "rooms": {ROOM: []}}), encoding="utf-8")
    (v4home / "rooms" / f"agree-{v4_follow.list_path(today - day).stem}.json").write_text(
        json.dumps({ROOM: {"day_s": today - day, "same": 0, "of": 0, "dollars_apart": 0.0,
                           "only_practice": [], "only_backtest": []}}), encoding="utf-8")
    got = client.get("/api/trade/v4-follow", headers=_hdr(ROOM)).json()
    nov09 = v4_follow._day_of("2026-11-09")
    # a given-up day never gets a list of its own: the line says so, never "has not landed yet"
    assert got["fallback_words"] == (f"today's list is a copy of the list of the day that began {fmt_when(nov09)}: "
                                     "today's refresh did not make one, and a day's list is never written twice")
    # the check names the UTC day it checked by its END, and says whether that is yesterday
    assert got["agreement"]["ended_s"] == today and got["agreement"]["yesterday"] is True
    # "Last N days" is the room's own rule window
    assert got["window_days"] == profiles.v4_rule(ROOM)["window"] == 30
    panel = PANEL_PATH.read_text(encoding="utf-8")
    assert "the new one has not landed yet" not in panel and "d.fallback_words" in panel
    assert "the day that ended ${fmtWhen(ag.ended_s)}" in panel and "Yesterday's check" in panel
    assert "no trades closed that day" in panel and "ag.of === 0" in panel
    assert "Last 30 days" not in panel and "Last ${d.window_days} days: Trades" in panel


def test_the_ribbon_never_prints_a_list_file_name(monkeypatch, v4home):
    from tradingagents import v4_follow

    v4_follow.list_path(_today()).write_text("{", encoding="utf-8")
    s = v4_follow.status(ROOM)
    assert s["today_landed"] is False and s["today_list_error"]
    assert ".json" not in s["today_list_error"] and "rooms" not in s["today_list_error"]


# ------------------------------------------------------------------ the price badge
# Operator, Nov 11, 2026: "why does it say websocket down". A follower room has no runner, so no
# runner ever opens a price connection for it - by design, it checks at each candle close as its
# backtest did - and the badge read the one machine-wide feed file, last written Oct 30, 2026, and
# called that "websocket down" (label-must-match-data: a false label over a true number).
def _follow_status(**over):
    st = {"last_pass_s": 1_793_000_020.0, "last_candle_ms": 1_793_000_000_000, "held_at": None,
          "why": None, "filled_in": 0, "errors": [], "switched_on": [], "fallback_from": None,
          "agreement": None}
    st.update(over)
    return lambda pid, *a, **k: st


def test_the_feed_route_says_a_follower_room_checks_at_each_close(client, monkeypatch):
    from tradingagents import v4_follow
    from tradingagents.positions_view import fmt_when

    monkeypatch.setattr(v4_follow, "status", _follow_status())
    got = client.get("/api/trade/feed", headers=_hdr(ROOM)).json()
    assert got["follows"] == "v4"
    assert got["connected"] is False and got["running"] is False and got["prices"] == []
    assert got["checked_s"] == 1_793_000_000 and got["problem"] is None
    assert "websocket" not in got["why"].lower()
    assert "candle close" in got["why"] and fmt_when(1_793_000_000) in got["why"]
    # a watcher room still reads its runner's socket, exactly as before
    plain = client.get("/api/trade/feed", headers=_hdr(OTHER)).json()
    assert plain.get("follows") is None and "checked_s" not in plain


def test_the_feed_route_names_a_follower_that_is_not_following(client, monkeypatch):
    from tradingagents import v4_follow

    monkeypatch.setattr(v4_follow, "status", _follow_status(
        last_pass_s=None, last_candle_ms=None, why="the follower has not run yet"))
    got = client.get("/api/trade/feed", headers=_hdr(ROOM)).json()
    assert got["checked_s"] is None and got["problem"] == "the follower has not run yet"
    assert "has not checked a candle yet" in got["why"]

    def boom(pid, *a, **k):
        raise OSError("disk gone")
    monkeypatch.setattr(v4_follow, "status", boom)
    got = client.get("/api/trade/feed", headers=_hdr(ROOM)).json()
    assert got["follows"] == "v4" and got["problem"].startswith("the follower's record cannot be read")


def test_the_badge_never_says_websocket_down_in_a_follower_room():
    src = (WEB / "components/trade/LivePrice.tsx").read_text(encoding="utf-8")
    badge = src[src.index("export function FeedBadge"):]
    assert badge.index("feed.follows") < badge.index('"websocket down"')
    assert "fmtWhen(feed.checked_s)" in badge          # one date format, from the route's own number
    assert "feed.problem" in badge
    ts = (WEB / "lib/api.ts").read_text(encoding="utf-8")
    block = ts[ts.index("export interface FeedStatus"):]
    block = block[:block.index("}")]
    for field in ("follows?:", "checked_s?:", "problem?:"):
        assert field in block, field
