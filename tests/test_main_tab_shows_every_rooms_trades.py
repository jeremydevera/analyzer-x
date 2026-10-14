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
