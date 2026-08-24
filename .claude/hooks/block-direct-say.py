#!/usr/bin/env python3
"""Block a DIRECT `say` call and point the session at speak.sh.

WHY THIS EXISTS
A skill is injected into a session's context as a SNAPSHOT and then frozen.
Editing SKILL.md cannot reach a session that already loaded it, and the
session goes on repeating its stale copy — including copying its own earlier
messages. The operator edited the say-done skill ~20 times; sessions kept
speaking at the old rate with the old ", sir" suffix, because none of them was
reading the file any more.

Prose cannot fix that, since prose is the thing that goes stale. A hook can:
it runs on the harness side at tool-call time, so it does not depend on
anything the model remembers. Voice/rate/suffix live in config.json and are
resolved by speak.sh AT SPEAK TIME, so the operator's edits apply instantly
and no session can drift from them.
"""
from __future__ import annotations

import json
import re
import sys

# `say` as a command, not the word inside a longer sentence: start of the
# command, or after a shell separator / opener.
DIRECT_SAY = re.compile(r"(?:^|[;&|(]|&&|\|\|)\s*(?:/usr/bin/)?say\b")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0                      # never break a tool call on our account
    if payload.get("tool_name") != "Bash":
        return 0
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    if "say-done/speak.sh" in cmd or "speak.sh" in cmd:
        return 0                      # the sanctioned path
    if not DIRECT_SAY.search(cmd):
        return 0
    sys.stderr.write(
        "BLOCKED: direct `say` is not allowed.\n"
        "The operator's voice, rate and suffix live in "
        ".claude/skills/say-done/config.json and are read AT SPEAK TIME by "
        "speak.sh. Calling `say` yourself bypasses that config and re-speaks "
        "whatever stale rate/suffix your context happens to hold — this has "
        "happened repeatedly.\n"
        "Use exactly:\n"
        '  bash .claude/skills/say-done/speak.sh "<one short sentence>" &\n'
        "Do not pass -v or -r. Do not append a suffix. config.json owns those.\n")
    return 2                          # 2 = block the call, feed stderr back


if __name__ == "__main__":
    sys.exit(main())
