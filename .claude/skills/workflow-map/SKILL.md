---
name: workflow-map
description: ALWAYS ON for EVERY EXPLANATION, not only "give me the workflow". Asked for again 2026-09-17 after a boxed diagram finally landed where four plain sentences had not: "this is what i want when you explain, update the skill". Fires on how something works, on WHY something happened, and on any comparison of two things that turned out differently. A "why" answer OPENS with one line starting BECAUSE, numbering the possible causes when it is not certain, and only then draws the diagram. Answer with the boxed arrow diagram in this skill - numbered stages in boxes, arrows between them, a branch box for every decision, a failure block at the bottom - then one short line under it. Never a paragraph of prose, never a bullet list, never mermaid.
---

# workflow-map — how a thing works is a DIAGRAM, not a paragraph

The operator, Sep 10, 2026, after being given the same answer twice — once as
prose, once as an indented list — and then the boxed version:

> *"i want workflow style"* … *"okay moving forward when i ask you a workflow i
> want this format, create a skill for this and give me the skill name"*

## When this fires

Any of these, no need to be asked twice:

* "give me the workflow", "what's the flow", "how does it work"
* "explain how X runs", "what happens when i press X"
* "walk me through it", "the steps"
* **"why did X happen"** — a cause is an order of events
* **"why did A win and B lose"** — any comparison of two things that started
  the same and ended differently
* **"explain again"** — if they had to ask twice, sentences are not working;
  draw it
* any answer where the point is the ORDER things happen in

It does NOT fire for a single fact ("is there a new trade") or a number.
Those stay one sentence — `short-and-plain` still rules everything.

**Why it was widened (2026-09-17).** They asked the same question four times
— *"so why did demo win if live lose?"* — and got four correct plain-English
sentences. None landed. The fifth answer was the boxed diagram below and the
reply was: *"this is what i want when you explain, update the skill i
mentioned to you to create using this workflow format"*.

A sentence makes the reader hold six facts in their head at once and work out
the order themselves. A diagram holds the order for them. **When an
explanation needs more than one sentence, it needs a diagram — not a longer
sentence, and never a paragraph.**

## The format — copy this shape exactly

````
        ┌────────────────────────────────────────────┐
        │  1. WHO ACTS — what they do                │
        │     • detail that matters                  │
        └───────────────────┬────────────────────────┘
                            ▼
        ┌────────────────────────────────────────────┐
        │  2. NEXT ACTOR ──► WHERE IT GOES           │
        │     what is sent, in plain words           │
        └───────────────────┬────────────────────────┘
                            ▼
   ╔═════════════════════════════════════════════════════════╗
   ║  3. A LOOP — double box, and say what repeats            ║
   ║                                                          ║
   ║     do the thing                                         ║
   ║        ▼                                                 ║
   ║     save it locally   ◄── THE BACKUP                     ║
   ║        ▼                                                 ║
   ║     send it ──► out ──┐                                  ║
   ╚═══════════════════════│══════════════════════════════════╝
                           ▼
        ┌────────────────────────────────────────────┐
        │  4. A DECISION — always a branch box       │
        │                                            │
        │     is it signed? ──NO──► thrown away      │
        │          │ YES                             │
        │          ▼                                 │
        │     is it newer?                           │
        │          ├─ YES ──► written to the store   │
        │          └─ NO  ──► ignored, counted       │
        └───────────────────┬────────────────────────┘
                            ▼
        ┌────────────────────────────────────────────┐
        │  5. WHAT THE OPERATOR SEES                 │
        │     the exact words on their screen        │
        └────────────────────────────────────────────┘

   IF ANYTHING FAILS ON THE WAY
     the send times out ──► retry twice ──► give up ──► still in the backup
     the PC is asleep ───► every send fails ──────────► the old path lands it
````

## The rules of the shape

1. **Numbered stages, one box each.** The number and WHO ACTS on the first
   line: `2. YOUR PC ──► GITHUB`. A stage nobody can name is not a stage.
2. **One arrow between boxes** (`▼`), down the same column. No crossing lines,
   no side-by-side lanes — a terminal is 80 characters wide.
3. **Every decision is a branch box** with `──NO──►` / `├─ YES ──►`. Never
   hide a branch in a sentence: the branch is usually the thing they are
   asking about.
4. **A loop gets the double box** (`╔═╗`) and says what it repeats over
   ("ONE MACHINE, ONE COIN — repeats for every coin").
5. **The failure block is not optional.** Bottom of the diagram, one line per
   way it can go wrong, each ending in what happens instead. A workflow drawn
   only for the happy path is the one that surprises them at 3am.
6. **Mark what is NEW or what changed** with `◄──` and a short label
   (`◄── THE BACKUP`, `◄── NEW`), so a redesign reads as a diff.
7. **Real names and real numbers inside the boxes** — `port 8788`,
   `27,500 rows`, `0G 30m` — never `<service>` or `the data`. Same rule as
   `explain-with-a-scenario`.
8. **One line of prose UNDER the diagram**, not above it: what to take away.
   Example: *"step 5 → 6 is new, step 8 is the old path kept as a safety net,
   and they can never double up because step 6 refuses anything not newer."*
9. **Plain words in every box.** `short-and-plain` applies inside the boxes:
   "mailbox", not "ingest endpoint"; "password", not "HMAC secret".
10. **No mermaid, no image, no artifact** unless they ask for one. This is
    text in the terminal, and it must survive being copied into a note.

## THE CAUSE GOES FIRST — one line, above the diagram

Operator, `Sep 17, 2026`, after five answers about one trade:

> *"why did you not explain that? you could have said, because 1. possibly it
> was closed in mexc"*

They were right and it is the worst kind of wrong: **the cause was known the
whole time and was drawn INSIDE box 4 of the diagram.** The trade record said
`MANUAL/EXCHANGE`, six real trades ended in the same minute, and the app had
no record of closing any of them. That is "somebody closed it at MEXC", and it
should have been the FIRST LINE of the FIRST answer. Instead five answers
explained the machinery around it.

**So, for any "why did X happen":**

```
BECAUSE — somebody closed it at MEXC, not the strategy.
  1. most likely — you pressed close in the MEXC app
  2. also possible — MEXC closed it itself

<then the diagram>
```

1. **One line, starting `BECAUSE`, before anything else.** Plain words, no
   numbers needed yet. If they read only that line they must already have the
   answer.
2. **If the cause is not certain, NUMBER the possibilities**, most likely
   first, and say which is which. They asked for this shape in their own
   words: *"1. possibly it was closed in mexc"*. Never present a guess as a
   fact and never hide behind the machinery instead of naming it.
3. **The diagram explains the cause; it does not hold it.** A fact buried in
   box 4 has not been said. If the answer can be found only by reading every
   box, the cause line is missing.
4. **Mechanism is never a substitute for cause.** "The feed only checks two
   prices" is HOW it kept waiting. "Somebody closed the real one at MEXC" is
   WHY they differ. They asked why.

The tell that this rule was broken: the operator asks the same question a
third time. Nobody asks three times about an answer that opened with its own
cause.

---

## The COMPARISON shape — two things that ended differently

The commonest explanation in this project: same coin, same strategy, same
minute, one won and one lost. Do NOT draw two diagrams side by side — a
terminal is 80 characters wide. Draw ONE column, and put the split in its own
box:

1. Stages 1-3 are what BOTH did, with both named on their own line inside the
   box (`REAL MONEY  ──►  bought VUG at 87.02` / `PRACTICE    ──►  bought VUG
   at 87.02`). Seeing them identical is half the answer.
2. **One box titled `HERE THEY SPLIT`**, with the moment and the price in its
   heading, and one branch per side. This box is the answer; everything above
   it exists to make it land.
3. The stages after the split follow only the side that kept going.
4. The last box is **WHAT YOUR SCREEN SHOWS** — the actual line they are
   looking at, so they can match the story to the screen that confused them.
5. The failure block becomes **`IF IT HAD GONE DIFFERENTLY`**: one line per
   alternative ending, each saying what both sides would have done. This is
   what proves the two are not broken — they follow the same rule.

Worked example, `Sep 16, 2026`, and the one that earned this skill its rewrite:
both copies of `#XH2KSFXG` bought VUG at 87.02 at 1:43am; the real one was
sold at MEXC at 86.89 at 1:38pm for −$0.84; the practice one was not reachable
by anyone, kept waiting, and sold itself at 87.455 at 7:04pm for +$0.17.

## Before drawing

Read the code that actually runs, in order — the emitter, not the label
(CLAUDE.md rule 23). A workflow diagram is a claim about what happens; if a
step is a guess, either check it or write `(not checked)` in that box.
