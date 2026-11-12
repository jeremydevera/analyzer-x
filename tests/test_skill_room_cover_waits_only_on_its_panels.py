"""A skill room's loading cover waits only for the panels a skill room SHOWS.

Operator, Nov 12, 2026, with a screenshot of the cover: "why is it loading
slow" - it read "strategies — still not loading after 165s, retrying" and
"exchange keys — still not loading after 165s, retrying". Nothing was slow:
the API answered both in 0.01 s. A skill room (`follows: "v4"`) never mounts
the deploy grid ("strategies") or the keys panel ("exchange keys"), and since
Nov 11, 2026 8:00am every room tab is a skill room, so nothing ever reported
those two names and the cover waited for them for ever (RCA-2026-11-12-A).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "webapp/src"
TRADE = WEB / "components/trade"


def _src(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8")


def _room_body() -> str:
    s = _src("components/trade/AutoTradeScreen.tsx")
    return s[s.index("const RoomBody"):s.index("THE MAIN TAB'S BODY")]


def _hidden_from_skill_rooms() -> set[str]:
    """Components RoomBody mounts only when the room does NOT follow Backtest v4."""
    body = _room_body()
    hidden = set(re.findall(r"\{!follows && <(\w+)", body))
    alt = body[body.index("{follows ? <V4FollowPanel /> : ("):]
    alt = alt[:alt.index(")}")]
    hidden |= set(re.findall(r"<([A-Z]\w+)", alt))
    return hidden


def _marked_by(component: str) -> set[str]:
    f = TRADE / f"{component}.tsx"
    if not f.exists():
        return set()
    names: set[str] = set()
    for call in re.findall(r"markReady\(([^)]*)\)", f.read_text(encoding="utf-8")):
        names |= set(re.findall(r'"([^"]+)"', call))
    return names


def _run_on_tab(tmp_path) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "loading.mts").write_text(_src("lib/loading.ts"), encoding="utf-8")
    eight = ["summary", "positions", "strategies", "exchange keys",
             "trade history", "profit", "runner feed", "past trades"]
    waiting = [{"name": n, "waitedMs": 165_000} for n in eight]
    (tmp_path / "run.mjs").write_text(
        'import { onTab } from "./loading.mts";\n'
        f"const w = {json.dumps(waiting)};\n"
        "console.log(JSON.stringify({ main: onTab(w, true).map((x) => x.name),\n"
        "  room: onTab(w, false).map((x) => x.name),\n"
        "  skill: onTab(w, false, true).map((x) => x.name) }));\n", encoding="utf-8")
    out = subprocess.run([node, str(tmp_path / "run.mjs")], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_a_skill_room_cover_never_waits_on_a_panel_it_does_not_show(tmp_path):
    got = _run_on_tab(tmp_path)
    # the screenshot's two names are gone from a skill room's cover...
    assert "strategies" not in got["skill"] and "exchange keys" not in got["skill"], got["skill"]
    assert got["skill"] == ["summary", "positions", "trade history", "profit", "runner feed"]
    # ...and nothing else changed: a room with a runner and the Main tab wait as before
    assert got["room"] == ["summary", "positions", "strategies", "exchange keys",
                           "trade history", "profit", "runner feed"]
    assert got["main"] == ["past trades"]


def test_the_skill_list_is_what_a_skill_room_mounts(tmp_path):
    """Held to the JSX, not to a copy of it: every name a component hidden from a
    skill room reports is off the skill list, and every name on the skill list is
    reported by a component a skill room really mounts."""
    got = _run_on_tab(tmp_path)
    hidden = _hidden_from_skill_rooms()
    assert {"StrategiesGrid", "CredentialsPanel"} <= hidden, hidden
    body = _room_body()
    mounted = set(re.findall(r"<([A-Z]\w+)", body)) - hidden - {"RoomScope"}
    hidden_names = set().union(*(_marked_by(c) for c in hidden))
    shown_names = set().union(*(_marked_by(c) for c in mounted))
    assert hidden_names, "the probe found no names on the hidden panels"
    assert not hidden_names & set(got["skill"]), hidden_names & set(got["skill"])
    assert set(got["skill"]) <= shown_names, set(got["skill"]) - shown_names


def test_the_screen_tells_the_cover_which_tab_is_a_skill_room():
    s = _src("components/trade/AutoTradeScreen.tsx")
    shown = s[s.index("const shown = onTab("):]
    shown = shown[:shown.index(";")]
    assert "room === ALL_ROOMS" in shown
    assert 'follows === "v4"' in shown and "PROFILES" in shown, shown
