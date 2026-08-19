---
name: label-must-match-data
description: Use before reporting ANY UI, table, tile, or artifact change as done in this repo. Catches the failure three-gates misses — where the number is correct but the words beside it are false. Every UI bug in this project so far has been of this class, not a wrong calculation.
---

# The Label Must Match the Data

`three-gates` asks "is it accurate?" and the honest answer keeps coming back **yes** —
because the *number* was verified. The number is almost never the bug.

**The bug is the text next to the number.**

> Operator, 2026-08-14, after a tile showed `+ open (RUNE) +7.59` while RUNE's real
> share was `+0.16`:
> *"can you create a skill to prevent that bug because you were not able to detect it
> in spite i created a skill to detect bug by asking 3 times"*

## The receipts — one night, five bugs, all the same shape

| What was displayed | What was true | The lie |
|---|---|---|
| `+ open (RUNE) +7.59` | RUNE was +0.16; the sum of **four** positions was +7.59 | an aggregate wearing one member's name |
| `PI · not yours` | PI is a configured strategy | label keyed on a **renamed** strategy id |
| `POSITIONS & PNL — REAL` | 8 of 9 rows were closed history | a title promising something the rows aren't |
| `TOTAL PROFIT +$7.58` | that summed 400 of **694** trades | a total over a truncated slice |
| row tagged `log` | clicking gave nothing — key was `1.0` vs `1` | a badge claiming a capability that fails |

In **every** case the arithmetic was right and the verification passed. Presence was
asserted. Values were asserted. Nobody asked whether the *sentence* was true.

## The rule

**Every label must be DERIVED from the same data it describes. Never a literal.**

If a tile shows a sum, the label must be built from the things summed. If it says
"not yours", that must be computed from the current config. If it says "TOTAL", it must
total everything the row claims to cover — or say what it excluded.

```python
# WRONG — a literal that was true once
f"<span>+ open (RUNE)</span><span>{open_total:+.2f}</span>"

# RIGHT — the label cannot drift from the data
"".join(f"<div>{sym}</div><div>{pnl:+.2f}</div>" for sym, pnl in open_rows)
+ f"<div>+ open total</div><div>{open_total:+.2f}</div>"
```

## The check — run it before saying done

For **every** number a change puts on screen, ask these five, out loud, in order:

1. **Is this one thing or many?** If the value is a sum, count, or average, does the
   label name the *set* rather than a member of it? A singular name on a plural value is
   the single most common bug in this repo.
2. **Where did every word in this label come from?** Point at the variable. If you cannot,
   it is a literal, and a literal is a claim frozen at the moment you typed it.
3. **Is anything excluded from this number that the label implies is included?**
   Truncated logs, capped tables, filtered rows, "top 400 of 2,028".
4. **Would this label survive a rename?** Strategy keys, coin symbols, and settings keys
   all get renamed. A label keyed on an id orphans its own history when that id changes.
5. **Does the badge promise an action that actually works?** A `log` tag must open a log.
   A sortable header must sort. Click it, do not assume it.

## Verifying it — assert agreement, not presence

A Playwright check that only asserts an element exists will pass on every bug above.
The check must **recompute the expected text from the source data and compare**:

```js
// NOT ENOUGH — passes while the label lies
console.log('tile present:', await tile.count() > 0);

// THE ACTUAL CHECK
const shown = await tile.innerText();                 // what the user reads
const truth = await computeFromSource();              // exchange / ledger / settings
assert(shown.includes(truth.label), `label says "${shown}" but data says "${truth.label}"`);
assert(nums(shown).total === truth.total, 'displayed total disagrees with source');
```

And for any itemised list: **the items must sum to the total shown**. That one assertion
would have caught the RUNE tile, the truncated TOTAL PROFIT, and the 400-of-2,028 footer.

## Red flags — stop and re-read the label

| Thought | Reality |
|---|---|
| "The number is right, I verified it" | The number is never the bug. Read the words |
| "It said RUNE because RUNE was the only one" | Then it was true once. Data changes; literals don't |
| "The test passed" | The test asserted presence. Assert *agreement* |
| "It's just a caption" | The caption is what the operator acts on |
| "I renamed the key and updated the config" | Every label keyed on that id just went stale |
| "Total is obviously the total" | Is it? Of the shown rows or all rows? Say which |

## Where this bites hardest in this repo

Money tiles, per-coin tables, the runner panel, and every published artifact — anywhere a
figure carries a name. The operator reads the label and acts on it. A mislabelled +$7.59
is indistinguishable from a real +$7.59 until they try to spend it.
