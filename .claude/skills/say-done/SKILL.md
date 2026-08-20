---
name: say-done
description: ALWAYS ON. After finishing any task the operator asked for, speak ONE calm sentence out loud describing what was finished, in a male voice, via macOS `say`. Requested 2026-08-20 — "after you are finished, make a sound to describe what you finished".
---

# Say what you finished

The operator's instruction, verbatim:

> "for this session when you finish a task say what you finished ...
> after you are finished, make a sound to describe what you finished like
> 'I'm done fixing the section'. i want 1 sentence only, and male voice"
> — later: "make say done skill slower, i want normal human interaction"

## The rule — LIVE settings

NEVER call `say` directly. Always go through `speak.sh`, which reads
`config.json` AT SPEAK TIME — so the operator's edits to voice, rate, suffix
or enabled apply to every session instantly, without any skill reload. This
exists because an edit ("no 'sir'") once sat unread while sessions kept
speaking their stale copies of the rule.


When a TASK the operator asked for is finished — code changed, sweep done,
artifact published, bug fixed — run, non-blocking:

```bash
bash .claude/skills/say-done/speak.sh "<what was finished>" &
```

- **One sentence, one utterance per task.** Not per tool call, not per
  message — per finished task. A multi-step task speaks once, at the end.
- **Jarvis delivery** (operator: "i want jarvis voice"): calm, butler-like —
  "The section is fixed.", "The daily grid is complete.",
  "The APEX artifact is published." **No "sir"** — the operator removed it
  on 2026-08-20: "i dont want 'sir' on the end".
- **Keep it under ~12 words.** It is a chime with meaning, not a report —
  the written summary still goes in chat as usual.
- **Voice: `Jamie (Premium)` (en_GB) when installed, else `Daniel`** — the
  operator wants Jarvis; Jamie is macOS's closest voice but ships via
  System Settings -> Accessibility -> Spoken Content -> Manage Voices, so
  probe for it each time and fall back to Daniel. Rate 145 — the operator flagged 170 as still too fast (2026-08-20: "why is saydone too fast?").
- **Background it (`&`)** so the turn never stalls on audio.

## When NOT to speak

- Answering a question (facts, status, "how many cores") — nothing finished.
- Progress ticks, monitors, partial steps of a larger task.
- A task that FAILED — say what happened in chat; do not chirp "done".
- Never put secrets, keys, file paths or numbers in the spoken line.

## Escaping

The sentence is shell-quoted with double quotes — keep it to plain words
(letters, spaces, apostrophes). No backticks, `$`, quotes, or symbols.
