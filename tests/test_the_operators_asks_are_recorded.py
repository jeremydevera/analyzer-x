"""The operator's own prompts are recorded, verbatim, and they travel.

`Sep 21, 2026`: *"create a skill to record my prompt in claude so that you
will remember all my prompt even when im in other machine"*, then *"activate
OPERATOR-ASKS always from now on"*.

Three things have to stay true or the record quietly stops being one, and a
record nobody notices has stopped is worse than none:

* the HOOK is registered — a skill the model must remember to run is exactly
  what this replaced;
* the log lives in the REPO (`docs/OPERATOR-ASKS.md`), so `git pull` carries
  it to another machine, not in `~/.claude`, which does not travel;
* one prompt makes one entry, and a prompt is never lost because the hook
  failed — every path in it exits 0.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude/hooks/record_ask.py"
LOG = ROOT / "docs/OPERATOR-ASKS.md"
SETTINGS = ROOT / ".claude/settings.json"


def _run(prompt: str, cwd: Path) -> None:
    subprocess.run([sys.executable, str(HOOK)],
                   input=json.dumps({"prompt": prompt}),
                   text=True, capture_output=True, timeout=30,
                   env={**os.environ, "CLAUDE_PROJECT_DIR": str(cwd)}, check=False)


def test_the_hook_is_registered_on_every_prompt():
    got = json.loads(SETTINGS.read_text(encoding="utf-8"))
    hooks = got.get("hooks", {}).get("UserPromptSubmit") or []
    cmds = [h.get("command", "") for group in hooks for h in group.get("hooks", [])]
    assert any("record_ask.py" in c for c in cmds), cmds
    assert HOOK.exists(), "the hook the settings point at must exist"


def test_the_record_lives_in_the_repo_so_it_travels():
    assert LOG.exists(), "docs/OPERATOR-ASKS.md is the record"
    assert ".claude" not in str(LOG.relative_to(ROOT)), \
        "under ~/.claude it would not reach another machine"
    head = LOG.read_text(encoding="utf-8")[:600]
    assert "verbatim" in head and "record_ask.py" in head, \
        "the file says what it is and what writes it"


def test_a_prompt_is_written_verbatim_and_quoted(tmp_path):
    (tmp_path / "docs").mkdir()
    _run("# not a heading\nplease fix the thing", tmp_path)
    body = (tmp_path / "docs/OPERATOR-ASKS.md").read_text(encoding="utf-8")
    assert "> # not a heading" in body, "quoted, so it cannot restructure the file"
    assert "> please fix the thing" in body


def test_the_same_prompt_in_the_same_minute_is_written_once(tmp_path):
    """A model switch re-submitted one prompt and the file grew three
    identical blocks in a minute (Sep 21, 2026 9:15pm)."""
    (tmp_path / "docs").mkdir()
    for _ in range(3):
        _run("activate OPERATOR-ASKS always from now on", tmp_path)
    body = (tmp_path / "docs/OPERATOR-ASKS.md").read_text(encoding="utf-8")
    assert body.count("> activate OPERATOR-ASKS always from now on") == 1, body


def test_a_second_different_prompt_is_still_kept(tmp_path):
    (tmp_path / "docs").mkdir()
    _run("first ask", tmp_path)
    _run("second ask", tmp_path)
    body = (tmp_path / "docs/OPERATOR-ASKS.md").read_text(encoding="utf-8")
    assert "> first ask" in body and "> second ask" in body


def test_a_slash_command_is_not_a_thought_worth_keeping(tmp_path):
    (tmp_path / "docs").mkdir()
    _run("/status", tmp_path)
    log = tmp_path / "docs/OPERATOR-ASKS.md"
    assert not log.exists() or "/status" not in log.read_text(encoding="utf-8")


def test_the_hook_never_fails_a_prompt(tmp_path):
    """Whatever it is handed — rubbish, nothing, a read-only folder — it must
    exit 0. A hook that fails blocks the operator's own message."""
    for payload in ("", "not json", json.dumps({"no_prompt": 1})):
        got = subprocess.run([sys.executable, str(HOOK)], input=payload, text=True,
                             capture_output=True, timeout=30,
                             env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)},
                             check=False)
        assert got.returncode == 0, (payload, got.stderr[:200])


def test_the_stamp_is_the_projects_one_date_format(tmp_path):
    """`Sep 21, 2026 9:15pm` — padded day, unpadded hour, lowercase am/pm."""
    import re

    (tmp_path / "docs").mkdir()
    _run("what time is it", tmp_path)
    body = (tmp_path / "docs/OPERATOR-ASKS.md").read_text(encoding="utf-8")
    assert re.search(r"### [A-Z][a-z]{2} \d{2}, \d{4} \d{1,2}:\d{2}[ap]m", body), body
    assert not re.search(r"\d{4}-\d{2}-\d{2}", body), "the banned stamp"


def test_the_rule_is_in_claude_md_so_every_session_reads_it():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.count("ALWAYS ON — `remember-my-asks`") == 1, \
        "one rule, once — two sessions each wrote the block on Sep 21, 2026"
    assert "docs/OPERATOR-ASKS.md" in text
    # their two asks, in their words: record them, and read them before dev
    assert "READ IT BEFORE YOU WRITE ANY CODE" in text
    assert "never paraphrase" in text or "never summarise" in text


def test_the_editors_own_text_is_not_recorded_as_their_words(tmp_path):
    """`Sep 21, 2026 9:17pm`: the IDE wraps a prompt with
    `<ide_opened_file>…</ide_opened_file>` and it landed in the record, so
    the file quoted the editor as if the operator had said it."""
    (tmp_path / "docs").mkdir()
    _run("<ide_opened_file>The user opened the file x in the IDE.</ide_opened_file>\n"
         "update it, before doing a dev always read this md", tmp_path)
    body = (tmp_path / "docs/OPERATOR-ASKS.md").read_text(encoding="utf-8")
    assert "ide_opened_file" not in body, body
    assert "> update it, before doing a dev always read this md" in body


def test_an_unclosed_wrapper_takes_its_line_and_nothing_else(tmp_path):
    (tmp_path / "docs").mkdir()
    _run("<system-reminder>truncated note\nthe real ask is here", tmp_path)
    body = (tmp_path / "docs/OPERATOR-ASKS.md").read_text(encoding="utf-8")
    assert "system-reminder" not in body
    assert "> the real ask is here" in body


def test_the_stripper_holds_no_control_bytes():
    r"""The stripper's backreference was once written as a raw 0x01 byte in
    place of `\1`, so the pattern could never match and the tag went into the
    record anyway — a regex that cannot fire looks exactly like one with
    nothing to do. HOW it matches is the hook's business (the tests above
    drive the behaviour); a control byte in the source never is."""
    src = HOOK.read_text(encoding="utf-8")
    bad = [f"{c!r} at {src.index(c)}" for c in map(chr, range(1, 9)) if c in src]
    assert not bad, bad
