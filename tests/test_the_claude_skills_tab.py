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


# --- the tile opens the skill's own text (operator, Oct 17, 2026: "in claude
# skills when i click the tile show me the md on how claude do that skill i
# want detailed") ------------------------------------------------------------
def test_a_skill_opens_its_whole_skill_md():
    d = cs.skill_doc("harddev")
    on_disk = (REPO / ".claude" / "skills" / "harddev" / "SKILL.md").read_text(encoding="utf-8")
    assert d["markdown"] == on_disk, "every word of the file, nothing trimmed"
    assert d["path"] == ".claude/skills/harddev/SKILL.md"
    assert d["group"] == "Coding" and d["description"] and d["own_description"]
    assert d["always"] is False


def test_only_a_skill_on_the_page_can_be_opened():
    """The name is looked up among the skill folders, never joined into a
    path: nothing outside .claude/skills can be read through this."""
    for bad in ("no-such-skill", "../CLAUDE", r"..\..\CLAUDE.md", "/etc/passwd",
                "harddev/../../CLAUDE", ""):
        assert cs.skill_doc(bad) is None, bad


def test_the_files_a_skill_works_with_are_listed_without_the_clutter():
    """practice_backtest_audit carries its scripts beside installed packages
    and screenshots; the panel lists the scripts, never node_modules."""
    d = cs.skill_doc("practice_backtest_audit")
    paths = [f["path"] for f in d["files"]]
    assert "scripts/audit.mjs" in paths and "scripts/match.mjs" in paths
    assert not [p for p in paths if "node_modules" in p or p.endswith(".png")
                or p.endswith("package-lock.json")]
    assert all(f["bytes"] > 0 for f in d["files"])


def test_a_skills_own_extra_notes_are_shown_in_full():
    """`design` keeps its detail in more .md files beside SKILL.md; each one
    is shown (up to the size the page can hold), and anything left out is
    named, never dropped quietly."""
    d = cs.skill_doc("design")
    extra = [x["path"] for x in d["docs"]]
    on_disk = sorted(p.relative_to(REPO / ".claude" / "skills" / "design").as_posix()
                     for p in (REPO / ".claude" / "skills" / "design").rglob("*.md")
                     if p.name != "SKILL.md" or p.parent.name != "design")
    assert sorted(extra + d["docs_left_out"]) == on_disk
    assert extra, "the design skill's notes are on the page"
    for x in d["docs"]:
        f = REPO / ".claude" / "skills" / "design" / x["path"]
        assert x["markdown"] == f.read_text(encoding="utf-8", errors="replace")


def test_the_route_answers_with_the_doc_or_a_404():
    import pytest
    from fastapi import HTTPException

    from tradingagents import api

    assert api.claude_skill_doc("harddev")["path"].endswith("harddev/SKILL.md")
    with pytest.raises(HTTPException) as e:
        api.claude_skill_doc("../CLAUDE")
    assert e.value.status_code == 404


def test_the_tile_opens_the_panel_and_the_panel_never_injects_html():
    """The panel turns markdown into React elements, never raw HTML: a skill
    file can only ever be text on this page."""
    tab = (REPO / "webapp/src/components/skills/ClaudeSkills.tsx").read_text(encoding="utf-8")
    doc = (REPO / "webapp/src/components/skills/SkillDoc.tsx").read_text(encoding="utf-8")
    assert "onClick={() => setOpen(s.name)}" in tab
    assert "<SkillDoc key={open} name={open}" in tab
    assert "/api/claude-skills/${encodeURIComponent(name)}" in doc
    assert "dangerouslySetInnerHTML" not in doc and "innerHTML" not in doc


def _marks(text: str, module=None) -> list:
    """The page's own inline-marks code, run by Node as it is (Node 22.6+
    strips the types from a .ts file)."""
    import json as _json
    import subprocess

    url = (module or REPO / "webapp" / "src" / "components" / "skills" / "inlineMarks.ts").as_uri()
    js = (f"import {{ inlineTokens }} from {_json.dumps(url)};"
          f"console.log(JSON.stringify(inlineTokens({_json.dumps(text)})));")
    got = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True,
                         text=True, timeout=60)
    assert got.returncode == 0, got.stderr[-800:]
    return _json.loads(got.stdout.strip().splitlines()[-1])


def test_an_underscore_inside_a_word_is_part_of_the_word():
    """Oct 18, 2026: the skill page of winning_room_strategy printed its own
    name as "winning" + an italic "room" + "strategy", the underscores gone
    (and practice_backtest_audit the same). CommonMark: an underscore inside a
    word is never a mark."""
    for name in ("winning_room_strategy", "practice_backtest_audit", "snake__case__name",
                 "/winning_room_strategy", "'/winning_room_strategy'"):
        assert _marks(name) == [{"kind": "text", "text": name}], name
    assert _marks("my_var and _real italic_ here") == [
        {"kind": "text", "text": "my_var and "}, {"kind": "em", "text": "real italic"},
        {"kind": "text", "text": " here"}]
    assert _marks("_whole_") == [{"kind": "em", "text": "whole"}]
    assert _marks("**bold** `a_b_c` *it*") == [
        {"kind": "strong", "text": "bold"}, {"kind": "text", "text": " "},
        {"kind": "code", "text": "a_b_c"}, {"kind": "text", "text": " "},
        {"kind": "em", "text": "it"}]
    assert _marks("see [the page](https://x.y/a_b_c)") == [
        {"kind": "text", "text": "see "}, {"kind": "link", "text": "the page", "href": "https://x.y/a_b_c"}]


def test_the_panel_draws_its_marks_with_the_tested_code():
    """The page must use the function the test above runs, not a copy."""
    src = (REPO / "webapp" / "src" / "components" / "skills" / "SkillDoc.tsx").read_text(encoding="utf-8")
    assert 'from "./inlineMarks"' in src and "inlineTokens(" in src
    assert "matchAll(" not in src and "const INLINE" not in src, "a second copy of the marks"
