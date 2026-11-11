"""The three skill rooms (Nov 10, 2026): Forecast v4's best rule sets as
practice rooms. Their trades are written by a follower, never a runner."""
import inspect
import re
from pathlib import Path

import pytest

from tradingagents import profiles

ROOT = Path(__file__).resolve().parent.parent
IDS = ["D7EN8BNV", "RSS7CUKH", "7T3VJU82"]


def test_the_three_rooms_have_tabs_after_bbe0a361():
    shown = profiles.shown()
    i = shown.index("BBE0A361")
    assert shown[i + 1:i + 4] == IDS
    for pid in IDS:
        assert profiles.follows(pid) == "v4"
        assert profiles.get(pid)["rules"] is None
        assert profiles.name_of(pid) == f"#{pid}"
    assert profiles.follows("BBE0A361") is None
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
    with profiles.using("55D32617"):
        assert sw.mode_of({"mode": "act"}) == "act"


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


def test_webapp_lists_the_rooms_in_order():
    ts = (ROOT / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    block = ts.split("export const PROFILES", 1)[1].split("];", 1)[0]
    ids = re.findall(r'\bid: "([^"]+)"', block)
    assert ids == profiles.shown()
    assert ids[-3:] == IDS
