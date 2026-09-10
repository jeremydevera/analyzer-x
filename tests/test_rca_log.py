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
        # "this commit" is exact, because `git log -- docs/RCA.md` finds it.
        # And a fix can legitimately be UNCOMMITTED — on Sep 09, 2026 three
        # files were being edited by a concurrent session, so committing them
        # would have shipped a feature this session did not write. That is a
        # real state and must be sayable, but LOUDLY and with a reason, never
        # by leaving the field vague.
        pending = "NOT YET COMMITTED" in fix
        assert re.search(r"\b[0-9a-f]{7,40}\b", fix) or "this commit" in fix \
            or pending, \
            f"{head}: FIX must name the commit, say 'this commit', or say " \
            f"'NOT YET COMMITTED' with the reason"
        if pending:
            why = fix.split("NOT YET COMMITTED", 1)[1]
            assert len(why.strip(" —:\n")) > 30, \
                f"{head}: 'NOT YET COMMITTED' needs the reason beside it"
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


def test_every_entry_has_its_own_id():
    """Two sessions fixing two bugs in the same hour both took `G` (Sep 09,
    2026). An id that names two entries names neither."""
    ids = [re.match(r"(RCA-\d{4}-\d{2}-\d{2}-[A-Z]+)", h).group(1)
           for h, _ in _entries()]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"the same id on two entries: {dupes} — take the next letter"


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


# ------------------------------------- two summaries, for the two real readers
# Operator, Sep 10, 2026: *"add this ceo style findings in documentation so it
# wont happen again also add technical/dev documentation as well / also update
# rca-log skill to inclde CEO summary, developer summary whenever i tell you to
# do rca documentation"*.
#
# They asked because the entries had stopped being readable BY THEM. RCA-F's
# root cause is "`_missing_ok` returned its default of 0 and the planner read it
# as a match count" — true, and useless to the person whose filter went blank.
# What they needed was "your filter said zero because it could not check".
#
# Entries from this date carry both. The ~20 older ones keep the seven fields
# alone and are deliberately NOT backfilled: a summary written months later from
# the entry itself adds no evidence, and rewriting the record to satisfy a new
# test is how a log stops being a record.
SUMMARIES_FROM = "2026-09-10"


def _dated_entries():
    for head, body in _entries():
        day = re.match(r"RCA-(\d{4}-\d{2}-\d{2})-", head).group(1)
        yield day, head, body


def _bullets(block: str) -> list[str]:
    return [ln for ln in block.splitlines() if ln.startswith("* ")]


def _summary(body: str, name: str) -> str:
    """The block from `**NAME**` to whatever heading comes next."""
    i = body.index(f"**{name}**") + len(f"**{name}**")
    rest = body[i:]
    ends = [rest.index(f"**{n}**") for n in ("CEO", "DEV") + FIELDS
            if f"**{n}**" in rest]
    return rest[:min(ends)] if ends else rest


@pytest.mark.parametrize("name", ["CEO", "DEV"])
def test_todays_entries_open_with_both_summaries(name):
    for day, head, body in _dated_entries():
        if day < SUMMARIES_FROM:
            continue
        assert f"**{name}**" in body, f"{head} is missing the {name} summary"


def test_the_summaries_come_before_the_evidence():
    """They are the way IN. A plain-words summary underneath a timeline of
    process ids has already lost the reader it was written for."""
    for day, head, body in _dated_entries():
        if day < SUMMARIES_FROM:
            continue
        assert body.index("**CEO**") < body.index("**DEV**") < body.index("**SAW**"), \
            f"{head}: order is CEO, then DEV, then the seven fields"


def test_the_ceo_summary_carries_no_code():
    """`_missing_ok`, `rows_wr4` and `file.py:1955` are all true and none of
    them belong here. If a bullet cannot be written without one, the term IS
    the problem — say what the effect was instead."""
    for day, head, body in _dated_entries():
        if day < SUMMARIES_FROM:
            continue
        ceo = _summary(body, "CEO")
        assert "`" not in ceo, \
            f"{head}: the CEO summary names code — {ceo[ceo.index('`'):][:60]!r}"
        assert ".py" not in ceo, f"{head}: the CEO summary names a file"


def test_the_dev_summary_names_a_location_and_its_guard():
    """The opposite failure: 'the count helper returned the wrong thing' sends
    the next session hunting. `rows_index.py:1955` does not."""
    for day, head, body in _dated_entries():
        if day < SUMMARIES_FROM:
            continue
        dev = _summary(body, "DEV")
        assert "`" in dev, f"{head}: the DEV summary names nothing precisely"
        assert "test_" in dev, \
            f"{head}: the DEV summary must name the guard, or say plainly " \
            f"that there is none and why"
        assert "invariant" in dev.lower(), \
            f"{head}: the DEV summary must name the RULE that broke, not " \
            f"only the line — a rule is what transfers to the next bug"


@pytest.mark.parametrize("name", ["CEO", "DEV"])
def test_each_summary_is_three_bullets(name):
    """Three, because the value is that they are read at all. The seven fields
    below are where length is allowed."""
    for day, head, body in _dated_entries():
        if day < SUMMARIES_FROM:
            continue
        got = _bullets(_summary(body, name))
        assert 3 <= len(got) <= 4, \
            f"{head}: {name} has {len(got)} bullets; the operator asked for 3"


def test_neither_summary_replaces_the_timeline():
    """A summary is not evidence. Both were added ON TOP of the seven fields,
    and an entry that answers only in summaries has lost the receipts."""
    for day, head, body in _dated_entries():
        if day < SUMMARIES_FROM:
            continue
        for field in FIELDS:
            assert f"**{field}**" in body, \
                f"{head}: {field} went missing when the summaries arrived"


def test_the_log_and_the_skill_both_document_the_two_summaries():
    """A shape enforced by a test and written nowhere a human reads is a trap.
    The skill is what a fresh session follows; the log's header is what a
    reader of the log sees."""
    log = RCA.read_text(encoding="utf-8")
    # the header ends at the first horizontal RULE, not at the first `---`:
    # `|---|---|` inside the field table is three dashes too.
    head = log[:log.index("\n---\n")]
    assert "**CEO**" in head and "**DEV**" in head, \
        "docs/RCA.md must describe both summaries in its own field table"
    assert SUMMARIES_FROM.replace("2026-09-10", "Sep 10, 2026") in head, \
        "the header must say from WHEN both are required"

    skill = SKILL.read_text(encoding="utf-8")
    front = skill.split("---")[1]
    assert "CEO" in front and "DEV" in front, \
        "the frontmatter description is all that loads until the skill opens"
    for line in ("**CEO**", "**DEV**", "no jargon", "test name"):
        assert line in skill, f"the skill must spell out {line!r}"
