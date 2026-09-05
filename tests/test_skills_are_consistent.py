"""The skills tree and CLAUDE.md must agree with what is on disk.

Operator, 2026-09-05: *"COMBINE THEM IN ONE CREATE NEW SKILL AND REMOVE THE
EIXSTING 3"* — short-answers, one-word and plain-words became `short-and-plain`.

Merging three files into one is exactly where a rule goes missing quietly, and
deleting three is exactly where a dangling reference survives. Both happened
while doing it, and both are guarded here:

* two operator-verbatim phrases ("worth noticing", "two things to flag") and
  the "offer it, do not impose it" nuance were dropped by the merge and had to
  be put back;
* the new skill and CLAUDE.md both referred to the deleted skills in BACKTICKS,
  which reads as a live, invokable skill name — a future session would try to
  invoke one and get nothing.

The last test here is the general invariant, not about this change: an ALWAYS ON
rule in CLAUDE.md that names a skill which is not on disk is a rule nothing can
follow.
"""
import pathlib
import re

SKILLS = pathlib.Path(".claude/skills")
CLAUDE = pathlib.Path("CLAUDE.md")
MERGED = SKILLS / "short-and-plain" / "SKILL.md"
GONE = ("short-answers", "one-word", "plain-words")


def _text(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def test_the_three_are_gone_and_the_merged_one_is_here():
    for name in GONE:
        assert not (SKILLS / name).exists(), f"{name} was supposed to be removed"
    assert MERGED.exists()


def test_every_skill_folder_declares_its_own_name():
    """A frontmatter name that disagrees with its folder is a skill that cannot
    be invoked by the name the listing shows."""
    bad = []
    for d in sorted(SKILLS.iterdir()):
        if not d.is_dir():
            continue
        f = d / "SKILL.md"
        if not f.exists():
            bad.append((d.name, "no SKILL.md"))
            continue
        m = re.search(r"^---\s*\nname:\s*(.+?)\s*\n", _text(f))
        if not m:
            bad.append((d.name, "no name in frontmatter"))
        elif m.group(1) != d.name:
            bad.append((d.name, f"frontmatter says {m.group(1)!r}"))
    assert not bad, bad


def test_nothing_backtick_references_a_deleted_skill():
    """Backticks read as a live skill name. Prose ABOUT the deleted three is
    fine — `short-answers` as an instruction is not."""
    offenders = []
    for p in list(SKILLS.rglob("*.md")) + [CLAUDE]:
        body = _text(p)
        for name in GONE:
            if f"`{name}`" in body:
                offenders.append(f"{p}: `{name}`")
    assert not offenders, offenders


def test_every_always_on_skill_named_in_claude_md_exists():
    """A rule pointing at a skill that is not on disk is a rule nothing can
    follow. This is the invariant the merge could have broken."""
    named = re.findall(r"ALWAYS ON — `([a-z0-9-]+)`", _text(CLAUDE))
    assert named, "no ALWAYS ON skills found — the format changed"
    missing = [n for n in named if not (SKILLS / n / "SKILL.md").exists()]
    assert not missing, missing


def test_claude_md_carries_the_merged_rule_once():
    body = _text(CLAUDE)
    assert body.count("ALWAYS ON — `short-and-plain`") == 1
    # the three old blocks, and the separate BASIC WORDS block that said the
    # same thing a fourth time, are folded in — not left beside it
    assert "ALWAYS ON — BASIC WORDS" not in body
    for name in GONE:
        assert f"ALWAYS ON — `{name}`" not in body


def test_the_merge_kept_the_caps_from_short_answers():
    body = _text(MERGED)
    for cap in ("**1 sentence**", "**3 sentences**", "**6 sentences**"):
        assert cap in body, cap
    assert "delete whole" in body and "paragraphs" in body


def test_the_merge_kept_the_beginner_rules_from_plain_words():
    body = _text(MERGED)
    assert "six words or fewer" in body
    assert "One idea per sentence" in body
    assert "Money, not ratios" in body
    # the glossary is the part that makes it usable on this project
    for term in ("margin", "leverage", "notional", "liquidation", "drawdown",
                 "round-trip cost", "martingale ladder", "chase guard"):
        assert term in body, term


def test_the_merge_kept_the_operators_own_phrases():
    """These were DROPPED by the first merge and caught by the hunt loop. They
    are the operator's own words from the replies they complained about."""
    body = _text(MERGED)
    for phrase in ("worth noticing", "two things to flag",
                   "do not impose it"):
        assert phrase in body, phrase


def test_it_says_both_halves_apply_at_once():
    """The whole reason for merging: each skill alone got followed alone —
    short but jargon-filled, or plain but four paragraphs long."""
    body = _text(MERGED)
    assert "SHORT AND PLAIN, both" in body
    assert "Compress **structure**, never **comprehension**" in body
    assert "Short answer, plain words. Not short words, long answer." in body
