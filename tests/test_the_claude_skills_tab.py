"""The Claude skills tab (operator, Oct 15, 2026: *"can you create a tab
called 'Claude skills' then categorize them for their function and what do
they do / for example harddev-categorize as coding then give me
description"*).

The page's list, groups and counts come from `claude_skills.listing()`, which
reads `.claude/skills/*/SKILL.md` on every call. These tests hold that the
words on the page agree with the folders: every skill shown, every one
sorted, harddev under Coding, and "runs by itself" read from the skill's own
text or CLAUDE.md — never typed in.
"""
from __future__ import annotations

from pathlib import Path

from tradingagents import claude_skills as cs

REPO = Path(__file__).resolve().parent.parent


def _on_disk() -> set:
    return {d.name for d in (REPO / ".claude" / "skills").iterdir()
            if (d / "SKILL.md").is_file()}


def test_every_skill_folder_is_on_the_page_and_sorted():
    """A skill added without a group still shows ("Not sorted yet"), but this
    fails so it gets a group and plain words the same day."""
    d = cs.listing()
    names = [s["name"] for g in d["groups"] for s in g["skills"]]
    assert len(names) == len(set(names)) == d["total"]
    assert set(names) == _on_disk()
    unsorted = [s["name"] for g in d["groups"] if g["name"] == cs.UNSORTED
                for s in g["skills"]]
    assert unsorted == [], f"give these a group in claude_skills.SKILLS: {unsorted}"


def test_the_operators_example_harddev_is_coding():
    d = cs.listing()
    hd = [s for g in d["groups"] for s in g["skills"] if s["name"] == "harddev"]
    assert hd and hd[0]["group"] == "Coding" and hd[0]["description"]


def test_no_entry_names_a_skill_that_does_not_exist():
    """A deleted skill must leave the table, or the map keeps a ghost."""
    assert set(cs.SKILLS) <= _on_disk(), set(cs.SKILLS) - _on_disk()
    assert {g for g, _ in cs.SKILLS.values()} <= set(cs.GROUPS)


def test_the_counts_on_the_page_add_up():
    d = cs.listing()
    assert sum(len(g["skills"]) for g in d["groups"]) == d["total"]
    assert sum(s["always"] for g in d["groups"] for s in g["skills"]) == d["always"]


def test_runs_by_itself_is_read_not_typed():
    """CLAUDE.md lists say-done as ALWAYS ON; harddev is run when coding."""
    flags = {s["name"]: s["always"] for g in cs.listing()["groups"] for s in g["skills"]}
    assert flags["say-done"] is True and flags["short-and-plain"] is True
    assert flags["harddev"] is False


def test_a_new_skill_shows_up_unsorted_with_its_own_words(tmp_path):
    d = tmp_path / "brand-new"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: brand-new\ndescription: Does a new thing. More words.\n---\nbody\n",
        encoding="utf-8")
    out = cs.listing(tmp_path)
    assert out["total"] == 1
    g = out["groups"][0]
    assert g["name"] == cs.UNSORTED
    assert g["skills"][0]["description"] == "Does a new thing."


def test_the_tab_is_in_the_menu_once():
    nav = (REPO / "webapp/src/layout/AppSidebar.tsx").read_text(encoding="utf-8")
    assert nav.count('path: "/claude-skills"') == 1
    assert (REPO / "webapp/src/app/(admin)/claude-skills/page.tsx").is_file()
