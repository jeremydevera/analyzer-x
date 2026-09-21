#!/usr/bin/env python
"""Append the operator's prompt to docs/OPERATOR-ASKS.md, verbatim.

Asked for on Sep 21, 2026: *"create a skill to record my prompt in claude so
that you will remember all my prompt even when im in other machine"*.

A HOOK, NOT A SKILL. A skill relies on Claude remembering to run it; the
harness runs this on `UserPromptSubmit` whether Claude is paying attention or
not. That is the difference between "usually recorded" and "recorded".

AND IT WRITES INTO THE REPO, not `~/.claude/projects/.../memory/`. That folder
is this machine only, and the whole point of the ask is that ANOTHER machine
gets the history — so the log travels the way everything else here does, with
`git pull`.

NO `jq`. The first draft piped through it and this machine has none, so the
hook would have silently done nothing forever — which is the exact failure
this repo keeps paying for (a swallowed error that looks like success).
Python is on PATH here and is what every other tool in this project uses.

It must NEVER fail a prompt: every path exits 0.

EXACTLY ONCE. The harness can invoke this more than once for a
single prompt, and on Sep 21, 2026 9:15pm it did — three identical
blocks for one ask. There is ONE dedupe, below, and it is scoped to
the same minute on purpose: the same words next week are a real
second ask and must be kept. Do not add a second dedupe.
"""
import json
import os
import pathlib
import sys
import time


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    prompt = str(payload.get("prompt") or "").strip()

    # STRIP THE HARNESS'S OWN CHROME. The editor wraps the prompt with notes
    # like `<ide_opened_file>The user opened ...</ide_opened_file>`, and on
    # Sep 21, 2026 9:17pm one landed in the record above the operator's real
    # sentence — so the file said they had "asked" something the editor said.
    # This log is their WORDS; anything the harness added is not.
    import re as _re
    prompt = _re.sub(r"<(ide_[a-z_]+|system-reminder)>.*?</>", "",
                     prompt, flags=_re.S).strip()
    if not prompt:
        return 0
    # A bare slash-command is the harness's, not a thought worth keeping.
    if prompt.startswith("/"):
        return 0

    root = os.environ.get("CLAUDE_PROJECT_DIR") or str(
        pathlib.Path(__file__).resolve().parent.parent.parent)
    log = pathlib.Path(root) / "docs" / "OPERATOR-ASKS.md"

    # THE DATE FORMAT IS THE PROJECT'S (CLAUDE.md): Sep 21, 2026 3:05pm.
    # Padded day, unpadded 12-hour hour, lowercase am/pm, no space.
    t = time.localtime()
    hour = t.tm_hour % 12 or 12
    when = (f"{time.strftime('%b %d, %Y', t)} {hour}:{t.tm_min:02d}"
            f"{'am' if t.tm_hour < 12 else 'pm'}")

    # quoted, so markdown, code fences or headings inside a prompt cannot
    # restructure this file
    body = "\n".join("> " + ln for ln in prompt.splitlines())

    # THE SAME PROMPT, THE SAME MINUTE, ALREADY AT THE END = DO NOT WRITE IT
    # AGAIN. The harness can invoke this more than once for one prompt — a
    # model switch re-submitted "activate OPERATOR-ASKS always from now on"
    # and the file grew three identical blocks in one minute (Sep 21, 2026
    # 9:15pm). A record that repeats itself is a record nobody trusts.
    #
    # Only the LAST block is compared, so the same words typed again next week
    # are still kept — that is a real second ask and the repetition is the
    # signal. What is lost is an intentional immediate repeat inside one
    # minute, which is worth losing to keep the file readable.
    try:
        if log.exists():
            with log.open("r", encoding="utf-8") as fh:
                fh.seek(max(0, log.stat().st_size - 8192))
                tail = fh.read()
            cut = tail.rfind("\n### ")
            last = tail[cut + 1:] if cut >= 0 else ""
            if last.startswith(f"### {when}\n\n{body}\n"):
                return 0
    except Exception:                                          # noqa: BLE001
        pass                      # a tail we cannot read is never a reason
        #                           to lose the prompt — fall through and write

    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        new = not log.exists()
        with log.open("a", encoding="utf-8") as fh:
            if new:
                fh.write(
                    "# What the operator actually asked for\n\n"
                    "Every prompt, verbatim, appended by\n"
                    "`.claude/hooks/record_ask.py` on `UserPromptSubmit`.\n\n"
                    "It lives in the repo so another machine gets it with\n"
                    "`git pull` — the memory folder does not travel.\n\n"
                    "**Read this before assuming what they want.** Their exact\n"
                    "words are the record; a summary of them is not.\n\n---\n\n")
            fh.write(f"### {when}\n\n{body}\n\n")
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
