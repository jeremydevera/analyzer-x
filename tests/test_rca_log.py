"""Every fixed bug is written down, in one place, with the same seven fields.

Operator, Sep 09, 2026: *"list this in rca to prevent this from happening in
the future / all fixes should be listed in a file so you will remember what
where the fixes / create a skill that is enabled always whenever a bug is
fixed"*.

They asked because the same faults keep returning in new clothes. Four bugs
were fixed that one day and in TWO of them a test written for exactly that
fault was passing at the time:

* `test_the_download_link_carries_the_window_too` asserted `api.ts` held two
  `p.set("days"` lines. It did — both inside `strategies`, which carried the
  block twice, while the download builder had none. A count is not a location.
* `test_the_browser_uses_one_date_format_everywhere` greps for `.toLocale`, so
  a `Date` built from seconds and sliced by hand printed `2026-09-07 17:01` on
  every row of the trade history with the guard green.

So the log's most important field is not the fix. It is **WHY IT WAS NOT
CAUGHT** — three permanent CLAUDE.md rules were bought by that sentence. This
file keeps the log's shape, and keeps the skill registered in the two places a
future session will look.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RCA = Path("docs/RCA.md")
SKILL = Path(".claude/skills/rca-log/SKILL.md")
FIELDS = ("SAW", "TIMELINE", "ROOT CAUSE", "WHY IT WAS NOT CAUGHT",
          "COST", "FIX", "GUARD")


def _entries() -> list[tuple[str, str]]:
    """(heading, body) per RCA entry."""
    text = RCA.read_text(encoding="utf-8")
    parts = re.split(r"^## (RCA-.*)$", text, flags=re.M)
    return list(zip(parts[1::2], parts[2::2], strict=True))


def test_the_log_exists_and_holds_entries():
    assert RCA.exists(), "the operator asked for ONE file; this is it"
    assert _entries(), "an empty log is a promise, not a record"


def test_every_entry_carries_all_seven_fields():
    for head, body in _entries():
        for field in FIELDS:
            assert f"**{field}**" in body, f"{head} is missing {field}"


def test_every_entry_says_why_the_test_did_not_catch_it():
    """The field that prevents the repeat. A heading with nothing under it is
    worse than no entry, because it reads as answered."""
    for head, body in _entries():
        i = body.index("**WHY IT WAS NOT CAUGHT**")
        j = body.index("**COST**", i)
        why = body[i + len("**WHY IT WAS NOT CAUGHT**"):j]
        assert len(why.strip(" —\n")) > 40, \
            f"{head}: 'why it was not caught' is a heading with no answer"


def test_every_entry_names_a_commit_and_a_guard():
    for head, body in _entries():
        fix = body[body.index("**FIX**"):body.index("**GUARD**")]
        # an entry that travels WITH its fix cannot know its own hash yet;
        # "this commit" is exact, because `git log -- docs/RCA.md` finds it
        assert re.search(r"\b[0-9a-f]{7,40}\b", fix) or "this commit" in fix, \
            f"{head}: FIX must name the commit (or say 'this commit')"
        guard = body[body.index("**GUARD**"):]
        assert "test_" in guard, \
            f"{head}: GUARD must name the test that fails if it comes back"


def test_every_entry_carries_measured_numbers():
    """An entry with no numbers cannot tell anyone later whether the fix
    mattered — 23.8s -> 3.8s is the whole value of the record."""
    for head, body in _entries():
        i = body.index("**TIMELINE**")
        j = body.index("**ROOT CAUSE**", i)
        timeline = body[i:j]
        digits = re.findall(r"\d", timeline)
        assert len(digits) >= 8, f"{head}: the timeline carries no real numbers"


def test_the_headings_are_dated_and_ordered_newest_first():
    dates = [re.match(r"RCA-(\d{4}-\d{2}-\d{2})-", h).group(1)
             for h, _ in _entries()]
    assert dates == sorted(dates, reverse=True), \
        f"newest first, so the last fix is the first thing read: {dates}"


# ------------------------------------------------- the skill stays registered
def test_the_skill_exists_and_is_always_on():
    body = SKILL.read_text(encoding="utf-8")
    assert body.startswith("---"), "a skill needs its frontmatter"
    head = body.split("---")[1]
    assert "name: rca-log" in head
    assert "ALWAYS ON" in head, \
        "the operator asked for it to run by itself, not to be typed"


def test_claude_md_carries_the_always_on_rule():
    """CLAUDE.md is what a fresh session reads. A skill nobody is told to run
    is a skill that does not run."""
    body = Path("CLAUDE.md").read_text(encoding="utf-8")
    assert "ALWAYS ON — `rca-log`" in body
    assert "docs/RCA.md" in body
    assert "WHY IT WAS NOT CAUGHT" in body


def test_skills_md_lists_it_under_always_on():
    """The operator's own index — 'when a new skill is made, add a row here'."""
    body = Path("SKILLS.md").read_text(encoding="utf-8")
    always = body[body.index("## Always on"):]
    always = always[:always.index("\n## ")]
    assert "`rca-log`" in always


@pytest.mark.parametrize("rule", [
    "FILTER WHERE THE DATA IS",
    "A GUARD IS ONLY AS WIDE AS ITS PATTERN",
])
def test_the_rules_that_field_bought_are_still_in_claude_md(rule):
    """These came out of a 'why it was not caught' sentence. If one is ever
    deleted, the entry that paid for it is still in docs/RCA.md."""
    assert rule in Path("CLAUDE.md").read_text(encoding="utf-8")


def test_the_repeating_patterns_list_is_there_to_read_before_testing():
    body = RCA.read_text(encoding="utf-8")
    assert "Patterns that keep repeating" in body
    for pattern in ("A count is not a location",
                    "A guard is only as wide as its pattern",
                    "Test the layer the operator actually touches"):
        assert pattern in body, pattern
