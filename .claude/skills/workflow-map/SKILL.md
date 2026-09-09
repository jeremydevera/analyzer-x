---
name: workflow-map
description: ALWAYS ON when the operator asks how something WORKS, asks for "the workflow", "the flow", "the steps", or how a feature/job/button runs end to end. Answer with the boxed arrow diagram in this skill - numbered stages in boxes, arrows between them, a branch box for every decision, a failure block at the bottom - then one short line under it. Never a paragraph of prose, never a bullet list, never mermaid.
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
* any answer where the point is the ORDER things happen in

It does NOT fire for a single fact ("is there a new trade") or a number.
Those stay one sentence — `short-and-plain` still rules everything.

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

## Before drawing

Read the code that actually runs, in order — the emitter, not the label
(CLAUDE.md rule 23). A workflow diagram is a claim about what happens; if a
step is a guess, either check it or write `(not checked)` in that box.
