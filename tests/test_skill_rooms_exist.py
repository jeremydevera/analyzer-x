"""The three skill rooms (Nov 10, 2026): Forecast v4's best rule sets as
practice rooms. Their trades are written by a follower, never a runner."""
import inspect
import re
from pathlib import Path

import pytest

from tradingagents import profiles

ROOT = Path(__file__).resolve().parent.parent
IDS = ["D7EN8BNV", "RSS7CUKH", "7T3VJU82"]


def test_the_three_rooms_have_tabs_right_after_main():
    """Nov 11, 2026: "i said undeploy the old existing rooms / only deploy your
    3 suggested room" - the ten older watcher rooms are off, no tab, so the
    tabs are #09439DC2 (main) and the three follower rooms, in that order."""
    shown = profiles.shown()
    assert shown == ["main"] + IDS
    for old in profiles.OFF_NOV11:
        assert old not in shown and profiles.retired(old)
    assert not profiles.retired("main")
    for pid in IDS:
        assert profiles.follows(pid) == "v4"
        assert profiles.get(pid)["rules"] is None
        assert profiles.name_of(pid) == f"#{pid}"
    assert profiles.follows("BBE0A361") is None      # retired, still no follower
    assert profiles.follows("main") is None
    assert profiles.v4_rule("main") is None


def test_v4_rule_is_a_copy():
    r = profiles.v4_rule("D7EN8BNV")
    r["window"] = 1
    assert profiles.v4_rule("D7EN8BNV")["window"] == 30


@pytest.mark.parametrize("pid", IDS)
def test_follower_rooms_switch_nothing_on(pid):
    from tradingagents import strategy_watcher as sw

    with profiles.using(pid):
        assert sw.mode_of({"mode": "act"}) == "off"
    with profiles.using("main"):                     # a watcher room still acts
        assert sw.mode_of({"mode": "act"}) == "act"
    with profiles.using("55D32617"):                 # retired Nov 11, 2026: forced off
        assert sw.mode_of({"mode": "act"}) == "off"


@pytest.mark.parametrize("pid", IDS)
def test_a_follower_room_never_gets_a_runner(pid, tmp_path, monkeypatch):
    import tradingagents.auto_trader as at

    spawned = []
    monkeypatch.setattr(at.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    with profiles.using(pid):
        with pytest.raises(RuntimeError) as e:
            at.start_runner()
    assert str(e.value) == f"#{pid} is followed by Backtest v4's engine; it has no runner"
    assert spawned == []


def test_the_supervisor_and_the_restart_skip_a_follower_room():
    from tradingagents import api, room_restart

    src = inspect.getsource(api)
    i = src.index("runner was down")
    assert "_pf.follows(_pid)" in src[i - 900:i]
    # the strings the older tests pin are still there
    assert "for _pid in _pf.ids():" in src
    assert "profiles.follows(room)" in inspect.getsource(room_restart.restart_rooms)


def test_restart_rooms_starts_no_follower(monkeypatch):
    from tradingagents import room_restart

    started = []
    monkeypatch.setattr(room_restart, "_ids", lambda: ["D7EN8BNV", "RSS7CUKH"])

    class _At:
        def wants_runner(self):
            return True

        def start_runner(self):
            started.append(1)

    monkeypatch.setattr(room_restart, "_at", lambda: _At())
    assert room_restart.restart_rooms() == ([], [])
    assert started == []


@pytest.mark.parametrize("pid", IDS)
def test_v4_rule_matches_the_forecast_rule_id(pid):
    from tradingagents import forecast_v4

    assert forecast_v4.rule_id(**profiles.v4_rule(pid)) == pid


def test_a_v4_key_resolves_to_its_own_id():
    from tradingagents import api

    assert api.row_id_for("v4_9HZYB3B5", "BTC_USDT", {}) == "9HZYB3B5"
    assert api.row_id_for("v4_9HZYB3B5", None, {}) == "9HZYB3B5"


def test_webapp_lists_the_rooms_in_order(as_shipped):
    ts = (ROOT / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    block = ts.split("export const PROFILES", 1)[1].split("];", 1)[0]
    ids = re.findall(r'\bid: "([^"]+)"', block)
    assert ids == profiles.shown()
    assert ids == IDS      # Nov 11, 2026: the three skill rooms are ALL the tabs
    assert "main" not in ids


# ---- the loops that walk every room (review of Task 4, Nov 10, 2026)
def test_the_daily_forecast_sends_no_follower_room_to_github():
    from tradingagents import forecast_v2_daily as fd

    got = fd.room_rules()
    assert not set(IDS) & set(got)
    assert "main" in got
    assert not set(profiles.OFF_NOV11) & set(got)    # the retired ten are off


@pytest.mark.parametrize("pid", IDS)
def test_backtest_a_room_refuses_a_follower_by_name(pid):
    from tradingagents import room_backtest, room_replay

    want = (f"#{pid} is followed by Backtest v4's engine; Backtest a room replays "
            "watcher rules, which it does not have")
    with pytest.raises(ValueError) as e:
        room_backtest.compare(pid, 0, 1)
    assert str(e.value) == want
    with pytest.raises(ValueError) as e:
        room_replay._check_room(pid)
    assert str(e.value) == want
    with pytest.raises(ValueError):
        room_replay.rules_for(pid)
    room_replay._check_room("main")              # a watcher room still passes


def test_the_watcher_and_30_day_loops_skip_a_follower_room():
    from tradingagents import api, rolling30, strategy_watcher

    src = inspect.getsource(api)
    i = src.index("_sw.tick()")
    assert "_pf.follows(_pid)" in src[i - 400:i]
    assert "with _pf.using(_pid):\n                            _sw.tick()" in src
    assert "profiles.follows(pid)" in inspect.getsource(rolling30.refresh)
    assert "profiles.follows(pid)" in inspect.getsource(strategy_watcher.restore_backtest_notes)


def test_the_room_list_says_what_a_follower_follows(tmp_path):
    from fastapi.testclient import TestClient

    from tradingagents import api

    got = {p["id"]: p for p in TestClient(api.app).get("/api/trade/profiles").json()["profiles"]}
    for pid in IDS:
        assert got[pid]["follows"] == "v4" and got[pid]["mode"] == "off"
        assert got[pid]["v4_rule"] == profiles.v4_rule(pid)


@pytest.mark.parametrize("pid", IDS)
def test_a_follower_rooms_stats_name_its_v4_rule_not_default_watcher_rules(pid):
    from tradingagents import forecast_v4, room_stats

    assert room_stats._rules_words(pid) == forecast_v4.rule_words(**profiles.v4_rule(pid))
