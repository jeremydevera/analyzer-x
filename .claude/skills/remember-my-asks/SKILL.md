---
name: remember-my-asks
description: ALWAYS ON. The operator's own prompts are recorded verbatim in docs/OPERATOR-ASKS.md by a UserPromptSubmit hook, so they survive a new session AND a different machine. Read that file before assuming what they want — when picking up work you did not start, when a rule seems to conflict, when they say "i already told you", or when the answer depends on what they actually asked rather than what got built. Never summarise it in place of quoting it.
---

# Remember my asks

The operator, `Sep 21, 2026`:

> *"create a skill to record my prompt in claude so that you will remember all
> my prompt even when im in other machine"*

## How it works

`.claude/hooks/record_ask.py` runs on **every** prompt (`UserPromptSubmit`,
wired in `.claude/settings.json`) and appends it verbatim to
**`docs/OPERATOR-ASKS.md`**.

Two choices in that sentence are the whole design:

* **A hook, not a skill.** A skill relies on Claude remembering to run it. The
  harness runs a hook whether Claude is paying attention or not — the
  difference between "usually recorded" and "recorded".
* **In the REPO, not in memory.** `~/.claude/projects/.../memory/` is this
  machine only. The ask was explicitly about *another machine*, so the log
  travels the way everything else here does: `git push` here, `git pull`
  there.

## What this skill is for

The hook writes it. This skill is the instruction to **READ** it:

* before picking up work you did not start;
* when two rules seem to conflict — their words decide, and the newer ask wins;
* when they say *"i already told you"* or *"i dont want this again"*;
* when the answer turns on what they ASKED for rather than what got built.

**Quote it, never paraphrase it.** This whole repo exists because a summary of
an ask and the ask itself turned out to be different things — CLAUDE.md is full
of rules bought exactly that way. Their words are the record.

## What it does NOT record

* Slash commands (`/status`, `/loop …`) — the harness's, not a thought.
* Empty prompts.
* Anything, if it would cost the operator a prompt: every failure path exits 0,
  silently. A recorder that can block a prompt is worse than no recorder.

The log has no secrets in it that the repo does not already hold — it is the
operator's own words in the operator's own repository.

## Keeping it usable

It only grows. When it gets long, do NOT prune it — append a dated index at
the top pointing at the asks that became rules, and leave every word in place.
Deleting an ask is deleting the evidence a rule was bought with.
