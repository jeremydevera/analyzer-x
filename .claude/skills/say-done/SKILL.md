---
name: say-done
description: ALWAYS ON. After finishing any task the operator asked for, speak ONE fast sentence out loud describing what was finished, in a male voice, via macOS `say`. Requested 2026-08-20 — "after you are finished, make a sound to describe what you finished".
---

# Say what you finished

The operator's instruction, verbatim:

> "for this session when you finish a task say what you finished ...
> after you are finished, make a sound to describe what you finished like
> 'I'm done fixing the section'. i want 1 sentence only, and male voice"
> — later: "make say done skill slower, i want normal human interaction"

## The rule

When a TASK the operator asked for is finished — code changed, sweep done,
artifact published, bug fixed — run, non-blocking:

```bash
_V="Daniel"; say -v '?' | grep -q "Jamie (Premium)" && _V="Jamie (Premium)"
say -v "$_V" -r 170 "<what was finished>, sir." &
```

- **One sentence, one utterance per task.** Not per tool call, not per
  message — per finished task. A multi-step task speaks once, at the end.
- **Jarvis delivery** (operator: "i want jarvis voice"): calm, butler-like,
  ending in "sir" — "The section is fixed, sir.",
  "The daily grid is complete, sir.", "The APEX artifact is published, sir.".
- **Keep it under ~12 words.** It is a chime with meaning, not a report —
  the written summary still goes in chat as usual.
- **Voice: `Jamie (Premium)` (en_GB) when installed, else `Daniel`** — the
  operator wants Jarvis; Jamie is macOS's closest voice but ships via
  System Settings -> Accessibility -> Spoken Content -> Manage Voices, so
  probe for it each time and fall back to Daniel. Rate 170, calm.
- **Background it (`&`)** so the turn never stalls on audio.

## When NOT to speak

- Answering a question (facts, status, "how many cores") — nothing finished.
- Progress ticks, monitors, partial steps of a larger task.
- A task that FAILED — say what happened in chat; do not chirp "done".
- Never put secrets, keys, file paths or numbers in the spoken line.

## Escaping

The sentence is shell-quoted with double quotes — keep it to plain words
(letters, spaces, apostrophes). No backticks, `$`, quotes, or symbols.
