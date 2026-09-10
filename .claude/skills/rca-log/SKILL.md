---
name: rca-log
description: ALWAYS ON, STRICT. Whenever a bug is fixed in this repo, append an entry to docs/RCA.md in the SAME commit as the fix - opening with a CEO summary (3 plain bullets, no jargon) and a DEV summary (3 precise bullets, file:line and test names) - what the operator saw, the numbered timeline with real numbers, the root cause, WHY THE TEST DID NOT CATCH IT, the cost, the commit and the guard. Never fix a bug without logging it. The operator asked for this explicitly and it is not optional.
---

# RCA log

The operator's instruction, Sep 09, 2026:

> "list this in rca to prevent this from happening in the future / all fixes
> should be listed in a file so you will remember what where the fixes /
> create a skill that is enabled always whenever a bug is fixed"

They asked because the same faults keep coming back in new clothes. On Sep 09
alone: a filter applied over a list the server had already truncated, a banned
date stamp on every row, a route decorator bound to a helper, and a download
that dropped the table's window — and in **two** of those four, a test written
for exactly that fault was passing at the time.

The fix is not a better memory. It is a file.

## The rule

**A bug fix is not finished until `docs/RCA.md` has its entry, in the same
commit.** No entry, no commit.

This fires on a real defect — something behaved wrongly and the behaviour
changed. It does not fire on a new feature, a refactor, a rename, a typo in a
comment, or a test-only change.

## The entry

Newest first, at the top of the log, under a heading
`## RCA-YYYY-MM-DD-<letter> — <the fault in the operator's terms>`.

**Two summaries first, then the seven fields.** Operator, Sep 10, 2026: *"add
this ceo style findings in documentation so it wont happen again also add
technical/dev documentation as well / also update rca-log skill to inclde CEO
summary, developer summary whenever i tell you to do rca documentation"*.

They asked because the entries were unreadable to them — engineer prose about
`_missing_ok` defaults and index write amplification, when what they needed was
"your filter said zero because it could not check, and it now says so". Both
readers are real and neither is served by the other's version.

```
**CEO** — 3 bullets, no code, no file names, no jargon.
  * what YOU saw or lost (money, time, a wrong number on screen)
  * why it happened, in one plain sentence
  * what stops it happening again

**DEV** — 3 bullets, precise, for whoever touches this next.
  * the failing call path: file:line -> function -> the wrong value
  * the invariant that was broken, named as a rule
  * the guard, by test name, and what it asserts
```

Rules for the two:

* **CEO says money, minutes and screens.** Never a function name. "Your win %
  filter showed nothing for 40 minutes" — not "`_winrate_matches` returned 0".
* **DEV says exact locations.** `rows_index.py:1955` beats "the count helper".
* **Neither replaces the TIMELINE.** They are the way in; the timeline is the
  evidence.
* If the CEO bullet cannot be written without a technical term, the term is
  the problem — describe the effect instead.

Then the seven fields, all of them:

```
**SAW** — what was on their screen, in their own words where you have them.

**TIMELINE**
1. real timestamp, real number, what actually happened
2. ...

**ROOT CAUSE** — the line that was wrong. Not the symptom.

**WHY IT WAS NOT CAUGHT** — the missing check, or the check that was too
narrow and why. THIS IS THE FIELD THAT PREVENTS THE REPEAT.

**COST** — dollars lost, dollars risked, or "none" — say which.

**FIX** — the commit hash, or the words `this commit` when the entry travels
with the fix (it must — and `git log -- docs/RCA.md` finds it).

**GUARD** — the test that now fails if it comes back.
```

## Rules for the numbers

- **Measured, never recalled.** Take them from the ledger, the store, the
  progress file, a timing probe, the browser. The before/after pair is what
  makes an entry worth reading: `23.8s -> 3.8s`, `42,420 rows -> 2,001 rows`.
- **Both sides.** An entry with only the "after" cannot tell anyone later
  whether the fix mattered.
- **If it never fired,** label it `NEVER HAPPENED YET` exactly as
  `bug-scenario` requires, then give the timeline it would have produced.

## WHY IT WAS NOT CAUGHT is not optional

If the honest answer is "nothing tested this", write that. If a test existed and
passed anyway, say what it actually asserted and why that was not the same thing
as the rule. Those sentences are the only reason the file exists — three of them
have already become permanent rules in `CLAUDE.md`:

- **FILTER WHERE THE DATA IS, NEVER AFTER A WINDOW HAS BEEN TAKEN**
- **A GUARD IS ONLY AS WIDE AS ITS PATTERN**
- **A count is not a location** — assert inside the function, not across a file

When an entry's "why" repeats one of those, say which, and check whether the
existing guard needs widening too.

## Before writing the entry

Read the "Patterns that keep repeating" list at the bottom of `docs/RCA.md`. If
this fault matches one, the test has to be written the other way — and add the
pattern to that list if it is new and has now happened twice.

## Combines with

- `bug-scenario` — same timeline, same rules about real data. The chat answer
  and the log entry carry the same story; the log also carries the "why it was
  not caught" and the commit.
- `three-gates` — the guard field is gate 3 written down.
- `harddev` — the hunt rounds are where the root cause gets found; the entry is
  where it is kept.
- `widen-the-guard-not-just-the-fix` (memory) — when a MANDATORY rule breaks a
  second time, the guard goes in the same commit and is proven red.
