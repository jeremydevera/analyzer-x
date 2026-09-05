---
name: bug-scenario
description: ALWAYS ON, STRICT. Whenever a bug is reported, described, or asked about, show it as a concrete step-by-step scenario with real times, prices and dollar amounts from this operator's own data. Never describe a bug only in terms of code, functions or conditions. The operator has asked for this explicitly and it is not optional.
---

# Bug Scenario

The operator's instruction:

> "give me scenario for each, when i asked a bug always give me scenario,
> this is strict"

They are new to trading and do not read code. A bug described as "the book
filter also gated exits" tells them nothing. The same bug shown as a timeline
of what happened to their money tells them everything.

## The rule

**Every bug gets a numbered timeline before any explanation.** Real timestamps,
real prices, real dollar amounts, pulled from their ledger, their state file or
the exchange — never invented, never generic.

## The shape

```
WHAT HAPPENED
  08-13 08:00   bot opened XAUT short at 4353, real money
  08-17 09:22   MEXC stopped it out at 4388.10 -> -$0.85
  08-17 09:22   bot did not notice
  08-13..18     screen showed the position as still open for 26 hours
                the -$0.85 never reached your PnL

WHY
  one sentence, plain words

COST
  -$0.85, and a day of wrong numbers on screen

FIXED
  yes / no, and what now stops it
```

Then stop. No architecture, no function names unless asked.

## Rules for the timeline

- **Real data only.** Measure it: `ledger_tail`, `position_history`,
  `load_state`, `log_tail`. If it cannot be measured, say so instead of
  inventing a plausible example.
- **Include the money.** Every bug either cost money, risked money, or cost
  none — say which. "No money involved" is a valid and important line.
- **Include what they SAW.** The screen showing something false is part of the
  bug, often the worst part.
- **Timestamps in their local time**, the way the app shows them.
- **One timeline per bug.** Three bugs = three timelines, never merged.

## Applies to

- "what are the bugs" / "is there a bug" / "what was the bug"
- Reporting a bug found while doing something else
- Explaining a fix — show the scenario it prevents
- Any answer where the word "bug" appears

## When a bug cannot be shown as a scenario

If it never fired in their data — a latent bug found by reading code — say
exactly that, then give the scenario it WOULD produce, labelled clearly:

```
NEVER HAPPENED YET. What it would do:
  ...
```

Never let a hypothetical read as history.

## Combines with

`short-and-plain` — the timeline IS the answer, so the caps apply to the prose
around it, not the timeline itself, and the steps carry no jargon.
`label-must-match-data` — every number in the timeline must be verified, not
recalled.
