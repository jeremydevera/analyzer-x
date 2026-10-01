"""Trading profiles: four rooms, each with its own settings, positions, trade
record, runner and watcher — and one real position per coin across all of
them.

Operator, Sep 29, 2026: "when i switch to B52662ED i should see its own
tiles, own live trade, own demo trade, own calendar pnl, in short it has its
own room/ profile", "Real money too", and "i want both, if i enable live
trade, then it should be included". Plan:
docs/superpowers/plans/2026-09-29-trading-profiles.md.

Everything lives under tmp_path: the runner's paths are monkeypatched there,
and every profile's folder sits beside the file it replaces.
"""
from __future__ import annotations

import re

import json

import pytest

from tradingagents import auto_trader as at
from tradingagents import profiles


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name in ("SETTINGS_PATH", "STATE_PATH", "LEDGER_PATH", "PID_PATH",
                 "LOG_PATH", "KILL_PATH", "WANT_PATH", "LOCK_PATH", "STATE_LOCK_PATH"):
        monkeypatch.setattr(at, name, tmp_path / getattr(at, name).name)
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    monkeypatch.setattr(at, "merge_runtime_specs", lambda: None)
    return tmp_path


def test_main_is_the_home_itself_and_nothing_moves(home):
    assert at._pp(at.LEDGER_PATH) == home / "auto_trade_ledger.jsonl"
    with profiles.using("B52662ED"):
        assert at._pp(at.LEDGER_PATH) == home / "profiles" / "B52662ED" / "auto_trade_ledger.jsonl"
    assert profiles.current() == profiles.MAIN, "the block ends, Main again"


def test_an_unknown_profile_is_refused_never_served_as_main():
    with pytest.raises(ValueError):
        with profiles.using("NOPE"):
            pass
    assert not profiles.valid("../main")


def test_each_room_keeps_its_own_trade_record(home):
    at.append_ledger({"action": "exit", "symbol": "VUG_USDT", "pnl_est": 1.0, "dry_run": True})
    with profiles.using("DC57174E"):
        at.append_ledger({"action": "exit", "symbol": "XLI_USDT", "pnl_est": -2.0, "dry_run": True})
        assert [e["symbol"] for e in at.ledger_since(0)] == ["XLI_USDT"]
    assert [e["symbol"] for e in at.ledger_since(0)] == ["VUG_USDT"]


def test_a_new_room_starts_with_mains_preferences_and_no_rows(home):
    at._write_json(at.SETTINGS_PATH, {"margin": 5, "martingale_demo": True, "dry_run": True,
                                      "enabled": True, "strategies": ["a"],
                                      "strategy_coins": {"a": ["VUG_USDT"]},
                                      "strategy_books": {"a": ["real"]}})
    with profiles.using("CC8DC54C"):
        s = at.load_settings()
    assert s["margin"] == 5 and s["martingale_demo"] is True and s["dry_run"] is True
    assert s["strategies"] == [] and s["strategy_coins"] == {} and s["strategy_books"] == {}
    assert s["enabled"] is False, "real money is never switched on by copying"
    assert at.load_settings()["strategies"] == ["a"], "Main is untouched"


def test_a_room_runner_is_started_as_that_room(home, monkeypatch):
    seen = {}

    class _P:
        pid = 4242

    def _popen(cmd, **kw):
        seen["env"] = kw["env"]
        return _P()

    monkeypatch.setattr(at.subprocess, "Popen", _popen)
    monkeypatch.setattr(at, "runner_pid", lambda: None)
    with profiles.using("B52662ED"):
        at.start_runner()
        assert at._pp(at.WANT_PATH).exists()
    assert seen["env"]["TA_PROFILE"] == "B52662ED"
    assert not at.WANT_PATH.exists(), "Main's intent is its own"


# ------------------------------------------------ one real position per coin
def _hold_real(pid, symbol):
    with profiles.using(pid):
        st = {at.state_key(symbol, False): {"position": {"side": 1, "vol": 1, "strategy": "k"}}}
        at._write_json(at._pp(at.STATE_PATH), st)


def test_a_coin_another_room_holds_with_real_money_is_refused(home):
    _hold_real("DC57174E", "VUG_USDT")
    with profiles.using("B52662ED"):
        assert at.other_profile_holding("VUG_USDT") == "DC57174E"
    assert at.other_profile_holding("VUG_USDT") == "DC57174E", "Main too"


def test_a_claim_stops_two_rooms_buying_at_the_same_moment(home):
    with profiles.using("DC57174E"):
        assert at.other_profile_holding("XLI_USDT") is None       # claims it
    with profiles.using("CC8DC54C"):
        assert at.other_profile_holding("XLI_USDT") == "DC57174E"
    with profiles.using("DC57174E"):
        assert at.other_profile_holding("XLI_USDT") is None, "its own claim"


def test_a_stale_claim_expires(home, monkeypatch):
    with profiles.using("DC57174E"):
        at.other_profile_holding("IGV_USDT")
    real = at.time.time
    monkeypatch.setattr(at.time, "time", lambda: real() + at.CLAIM_S + 1)
    with profiles.using("CC8DC54C"):
        assert at.other_profile_holding("IGV_USDT") is None


def test_a_read_only_check_claims_nothing(home):
    with profiles.using("DC57174E"):
        assert at.other_profile_holding("TSLA_USDT", claim=False) is None
    with profiles.using("CC8DC54C"):
        assert at.other_profile_holding("TSLA_USDT") is None


def test_the_orphan_sweep_never_adopts_another_rooms_position(home):
    _hold_real("B52662ED", "VUG_USDT")
    calls = []

    class FX:
        def open_positions(self, symbol=None):
            calls.append(symbol)
            return [{"symbol": symbol, "holdVol": 1, "positionType": 1}]

    settings = {"strategies": ["keltner_30m_sl2tp2"],
                "strategy_coins": {"keltner_30m_sl2tp2": ["VUG_USDT"]}}
    state = {}
    at.adopt_orphans(settings, state, fx=FX(), dry=False)
    assert calls == [], "it never even asked the venue about another room's coin"
    assert not (state.get(at.state_key("VUG_USDT", False)) or {}).get("position")


def test_panic_in_a_room_closes_only_that_rooms_money(home, monkeypatch):
    _hold_real("DC57174E", "VUG_USDT")
    closed = []

    class FX:
        def open_positions(self, symbol=None):
            return [{"symbol": "VUG_USDT", "holdVol": 3, "positionType": 1, "positionId": 1},
                    {"symbol": "XLI_USDT", "holdVol": 2, "positionType": 1, "positionId": 2}]

    monkeypatch.setattr(at, "_force_close", lambda sym, pos, fx: closed.append(sym))
    monkeypatch.setattr(at, "stop_runner", lambda: True)
    with profiles.using("DC57174E"):
        rep = at.panic_stop(fx=FX())
    assert closed == ["VUG_USDT"] and rep["left_to_other_profiles"] == ["XLI_USDT"]
    closed.clear()
    _hold_real("DC57174E", "VUG_USDT")        # the room still holds it
    at.panic_stop(fx=FX())                                      # Main
    assert closed == ["XLI_USDT"], "Main closes orphans, never another room's coin"


def test_a_rooms_screen_lists_only_its_own_real_positions(home):
    from tradingagents import api

    _hold_real("DC57174E", "VUG_USDT")
    live = [{"symbol": "VUG_USDT"}, {"symbol": "XLI_USDT"}]
    with profiles.using("DC57174E"):
        assert [p["symbol"] for p in api._own_exchange_positions(live)] == ["VUG_USDT"]
    assert [p["symbol"] for p in api._own_exchange_positions(live)] == ["XLI_USDT"]


# --------------------------------------------------------------- the API
def test_the_request_names_its_room(home):
    from fastapi.testclient import TestClient

    from tradingagents import api

    with profiles.using("B52662ED"):
        at.append_ledger({"action": "exit", "symbol": "IGV_USDT", "pnl_est": 2.5,
                          "dry_run": True, "ts": 1})
    c = TestClient(api.app)
    main = c.get("/api/trade/summary").json()
    room = c.get("/api/trade/summary?profile=B52662ED").json()
    assert main["paper_all_time"]["trades"] == 0
    assert room["paper_all_time"]["trades"] == 1 and room["paper_all_time"]["total"] == 2.5
    hdr = c.get("/api/trade/summary", headers={"X-TA-Profile": "B52662ED"}).json()
    assert hdr["paper_all_time"]["trades"] == 1
    assert c.get("/api/trade/summary?profile=NOPE").status_code == 404


def test_the_supervisor_and_watcher_loops_walk_every_room():
    src = open("tradingagents/api.py", encoding="utf-8").read()
    assert src.count("for _pid in _pf.ids():") >= 2
    assert "with _pf.using(_pid):\n                            _sw.tick()" in src


# --------------------------------------------------------------- the screen
def _src(p):
    return open(p, encoding="utf-8").read()


def test_the_screen_offers_exactly_the_servers_rooms():
    import re

    api_ts = _src("webapp/src/lib/api.ts")
    block = api_ts[api_ts.index("export const PROFILES"):]
    block = block[:block.index("];")]
    assert re.findall(r'id: "([^"]+)"', block) == profiles.shown()


def test_every_trade_call_names_its_room_and_nothing_else_does():
    """Since Oct 01, 2026 every room stays loaded, so the room is the CALL's
    (captured at entry, withProfile) — never whatever tab is on screen."""
    api_ts = _src("webapp/src/lib/api.ts")
    assert 'headers.set("X-TA-Profile", room);' in api_ts
    assert "if (room !== \"main\" && _roomed(input))" in api_ts
    assert r"/^\/api\/(trade\/|ledger)/.test(path)" in api_ts
    assert "room: string = _roomNow()" in api_ts
    get = api_ts[api_ts.index("async function get<T>"):api_ts.index("async function post<T>")]
    assert get.count(", room)") == 2, "the retry asks the same room as the first try"


def test_every_room_stays_loaded_in_its_own_scope():
    """Oct 01, 2026: "when i switch tabs you forget it ... load all the info
    for all, then i want all the numbers updating in realtime". Every room is
    mounted once in its own RoomScope and only hidden; each panel takes its
    calls from useRoomApis(), so nothing one room draws comes from another."""
    screen = _src("webapp/src/components/trade/AutoTradeScreen.tsx")
    assert 'role="tablist" aria-label="Trading rooms"' in screen
    assert "{room && PROFILES.map((p) => (" in screen
    assert "<RoomScope key={p.id} id={p.id} active={p.id === room}>" in screen
    assert "hidden={p.id !== room}" in screen
    assert "setProfile(id);" in screen
    for f in ("SummaryRibbon", "PositionsPanel", "StrategiesGrid", "WatcherPanel",
              "CredentialsPanel", "TradeHistory", "PnlPanel", "FeedPanel", "SmartWatcherBox"):
        src = _src(f"webapp/src/components/trade/{f}.tsx")
        assert "= useRoomApis();" in src, f
        imp = [ln for ln in src.splitlines() if ln.startswith("import") and '"@/lib/api"' in ln]
        assert not any(re.search(r"(api|tradeApi)", ln) for ln in imp),             f"{f} imports the unbound api — its calls would go to the room on screen"
    live = _src("webapp/src/lib/live.ts")
    assert "withProfile(id, () => fn.current())" in live
    assert "Math.max(ms, BEHIND_MS)" in live
    api_ts = _src("webapp/src/lib/api.ts")
    assert "await takeLane(_roomed(input) && room !== _profile);" in api_ts, "the room on screen goes first"
    for f in ("SmartWatcherBox", "WatcherPanel"):
        assert ".profile !== room.id) return;" in _src(f"webapp/src/components/trade/{f}.tsx"), f


def test_each_rooms_watcher_has_its_real_money_switch():
    panel = _src("webapp/src/components/trade/WatcherPanel.tsx")
    assert "api.watcherSet({ live: v })" in panel and "Watcher trades real money" in panel
    assert "if (v && !window.confirm(" in panel


def test_the_wallet_check_counts_margin_other_rooms_just_committed(home, monkeypatch):
    """Four rooms, one wallet whose used margin lags a fill: a real order
    in one room must shrink what the next room sees at once."""
    with profiles.using("DC57174E"):
        at.cross_commit(5.0)
        assert at.others_committed() == 0.0, "its own margin is its own cycle's"
    assert at.others_committed() == 5.0
    with profiles.using("CC8DC54C"):
        at.cross_commit(5.0)
        at.cross_commit(-5.0)                  # refused: given back
        assert at.others_committed() == 5.0
    real = at.time.time
    monkeypatch.setattr(at.time, "time", lambda: real() + at.COMMIT_WINDOW_S + 1)
    assert at.others_committed() == 0.0, "the venue shows it by then"
    src = open("tradingagents/auto_trader.py", encoding="utf-8").read()
    assert "held += float(_CYCLE_COMMITTED.get(\"usdt\") or 0.0) + _others" in src
    assert "cross_commit(float(margin))" in src and "cross_commit(-float(margin))" in src


def test_the_tab_i_reads_each_rooms_own_rules(home, monkeypatch):
    """Sep 29, 2026: "put i icon beside each tab id when i click it show pop
    up on what's the criteria" — the rules the room's watcher RUNS on."""
    from fastapi.testclient import TestClient

    from tradingagents import api, strategy_watcher as sw

    monkeypatch.setattr(sw, "STATE", home / "strategy_watcher.json")
    monkeypatch.setattr(sw, "LOG", home / "strategy_watcher.jsonl")
    got = {r["id"]: r for r in TestClient(api.app).get("/api/trade/profiles").json()["profiles"]}
    assert list(got) == profiles.shown()
    # the table's rooms (Sep 30, 2026): #55D32617 judges on 15 days
    b = got["55D32617"]
    assert (b["cfg"]["on_winrate"], b["cfg"]["min_trades"], b["cfg"]["max_sl"]) == (70.0, 50, 2.0)
    assert b["window_days"] == 15 and b["cfg"]["window_days"] == 15
    assert b["mode"] == "act" and b["live"] is False
    assert got["CC94D9FB"]["cfg"]["on_winrate"] == 80.0 and got["CC94D9FB"]["window_days"] == 30
    # ...and the rooms before it are retired: no tab, so no popup either
    assert "B52662ED" not in got


def test_the_popup_and_the_panel_say_the_rules_with_one_function():
    screen = _src("webapp/src/components/trade/AutoTradeScreen.tsx")
    panel = _src("webapp/src/components/trade/WatcherPanel.tsx")
    assert 'import { rules } from "./WatcherPanel";' in screen
    assert "rules(r.cfg, r.window_days, r.live)" in screen
    assert "export function rules(c: Watcher[\"cfg\"], days: number, live = false)" in panel
    assert 'live ? "practice AND real money" : "practice account only"' in panel
    assert "aria-label={`What ${p.name} switches on and off`}" in screen
