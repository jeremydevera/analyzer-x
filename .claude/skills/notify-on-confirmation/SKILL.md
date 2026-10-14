---
name: notify-on-confirmation
description: ALWAYS ON. Every time a reply asks the operator to confirm, choose or approve anything (an AskUserQuestion, "yes to this design?", "review the spec", "say go"), also send a PushNotification in the same turn naming what they need to answer. Requested Oct 14, 2026 — "i want you to notify me if you are asking for my confirmation".
---

# Notify the operator when a question is waiting for them

The operator's words, Oct 14, 2026, after a design question sat unanswered:

> "why did you not notify me, i want you to notify me if you are asking for my
> confirmation"

`say-done` speaks only when a task is FINISHED, so a question waiting on them
made no sound at all, and they had stepped away.

## The rule

Whenever a reply stops to ask the operator to **confirm, choose or approve**
something, send a `PushNotification` in the SAME turn:

- an `AskUserQuestion`
- "yes to this design?", "review the spec", "say go", "which one?"
- any reply whose last line asks them to decide before work continues

The message is one line, under 200 characters, naming what they need to
answer and where:

> Waiting for you: review the Main-tab spec (all rooms' past trades; the old
> Main room becomes #09439DC2) and say yes to make the plan.

`PushNotification` is a deferred tool: load it with
`ToolSearch("select:PushNotification")` before the first call.

## Never

- **Instead of** the question — the notification goes out WITH it, the
  question itself is still in the reply.
- For routine progress, a status update, or finished work (`say-done` covers
  finished work).
- Twice for the same question.
