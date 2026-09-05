---
name: harddev
description: The operator's dev loop for EVERY code change - build, then loop "is there a potential bug?" and revise until the answer is no, and only then test. Asked for by name on 2026-09-05.
---

# harddev — build, hunt bugs in a loop, then test

The operator's words, verbatim (2026-09-05):

> AFTER YOU DEV, LOOP BY ASKING IS THERE A POTENTIAL BUG IF YOU DETECT THERE
> IS THEN REVISE, UNTIL THERE IS NOT POPTENTIAL BUG DONT STOP LOOP, AFTER
> THERE IS NO POTENTIAL BUG THEN TEST IT

Why it exists: on 2026-09-04 a one-line-of-thought change shipped with eleven
passing tests and still froze all trading for nine hours, because nobody asked
"what else could this break" before testing. Tests confirm what you thought
of; the loop is for what you did not.

## The loop

1. **DEV** — write the change.
2. **HUNT** — ask "is there a potential bug?" and actually look:
   - every CALLER of what changed (grep the name, not memory)
   - every path that runs it: the runner's own entry point, the API, tests,
     tools — in the STATE the operator runs (live armed, multi-coin)
   - shared state: what outlives one call? who clears it? two sessions?
   - the failure path: what happens when the venue call raises, returns
     rubbish, or returns slowly?
   - units and sides: percent vs fraction, bid vs ask, paper vs real
   - concurrency: the runner, the API thread, a second Claude session
3. **FOUND ONE?** Revise, write the finding down, go to 2. DO NOT STOP THE
   LOOP EARLY. Each round is named in the commit message.
4. **FOUND NONE?** Say so once — then TEST:
   - unit tests for the change AND for each bug found in the loop
   - run the affected suite, compare failures against the baseline
   - when it touches the runner/UI: run it for real and read the result
5. Commit with the loop's findings in the message. Push.

## Rules

- The loop's rounds are REAL work, not a checklist recital: each round names
  a concrete potential bug and what was done about it, or names the places
  checked that came back clean.
- A bug found by the loop gets a test, so it stays fixed.
- "No potential bug" after round 1 is suspicious. The 2026-09-04 freeze was
  round-2 material (a caller one level up).
