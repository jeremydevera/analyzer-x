"""The hand-over to the skill rooms (Nov 10, 2026): ten watchers off, the room
whose id is `main` and the three skill rooms untouched, no row disarmed.

Everything runs under conftest's sandbox (tmp_path homes); nothing reaches the
real ~/.tradingagents.
"""
from __future__ import annotations

import json

from tradingagents import auto_trader as at
from tradingagents import local_history as lh
from tradingagents import profiles
from tradingagents import strategy_watcher as sw
from tradingagents import v4_rooms

SKILL = ("D7EN8BNV", "RSS7CUKH", "7T3VJU82")


def _on(pid):
    with profiles.using(pid):
        sw.set_mode("act")


def _state(pid):
    with profiles.using(pid):
        return sw._read()


def _mode(pid):
    with profiles.using(pid):
        return sw.mode_of(sw._read())


def test_the_ten_ids_are_the_rooms_that_exist_and_not_the_skill_rooms_or_main():
    assert len(v4_rooms.OTHERS) == 10 and len(set(v4_rooms.OTHERS)) == 10
    for pid in v4_rooms.OTHERS:
        assert profiles.valid(pid)
        assert not profiles.follows(pid)
    assert profiles.MAIN not in v4_rooms.OTHERS
    assert not set(SKILL) & set(v4_rooms.OTHERS)


def test_the_ten_are_the_ten_retired_on_nov_11():
    """Nov 11, 2026 ("i said undeploy the old existing rooms"): the ten whose
    watchers were switched off on Nov 10 lost their tabs too."""
    assert set(v4_rooms.OTHERS) == set(profiles.OFF_NOV11)
    for pid in v4_rooms.OTHERS:
        assert profiles.retired(pid) and pid not in profiles.shown()
        assert _mode(pid) == "off"
    assert _mode(profiles.MAIN) != "off" or not profiles.retired(profiles.MAIN)


def test_retire_others_turns_ten_watchers_off_and_leaves_main(old_rooms_on):
    old_rooms_on()       # retired in production since Nov 11, 2026: revived to prove the Nov 10 switch-off
    for pid in v4_rooms.OTHERS:
        _on(pid)
    _on(profiles.MAIN)
    assert all(_mode(p) == "act" for p in v4_rooms.OTHERS)
    main_state = _state(profiles.MAIN)

    out = v4_rooms.retire_others()

    assert out == {pid: "off" for pid in v4_rooms.OTHERS}
    assert all(_mode(p) == "off" for p in v4_rooms.OTHERS)
    assert _mode(profiles.MAIN) == "act", "the room that was main is never touched"
    assert _state(profiles.MAIN) == main_state
    for pid in v4_rooms.OTHERS:
        with profiles.using(pid):
            rows = lh.deployments()
            assert [r["note"] for r in rows] == [v4_rooms.REASON]
    with profiles.using(profiles.MAIN):
        assert lh.deployments() == []


def test_a_real_money_slot_is_never_disarmed():
    pid = v4_rooms.OTHERS[0]
    with profiles.using(pid):
        s = at.load_settings()
        s["strategy_coins"] = {"k_1h": ["BTC_USDT"]}
        s["strategy_books"] = {at.book_slot("k_1h", "BTC_USDT"): ["paper", "real"]}
        at.save_settings(s)
        before = json.dumps(at.load_settings().get("strategy_books"), sort_keys=True)
    v4_rooms.retire_others()
    with profiles.using(pid):
        s = at.load_settings()
        assert json.dumps(s.get("strategy_books"), sort_keys=True) == before
        assert s["strategy_coins"] == {"k_1h": ["BTC_USDT"]}


def test_running_it_twice_changes_nothing_the_second_time():
    v4_rooms.retire_others()
    v4_rooms.retire_others()
    for pid in v4_rooms.OTHERS:
        with profiles.using(pid):
            assert len(lh.deployments()) == 1
