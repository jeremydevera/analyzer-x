---
name: three-gates
description: Use before delivering ANY answer, number, table, artifact, or "done" in this repo — especially backtests, strategy results, trading-engine changes, and UI work. Enforces the operator's three gates (accurate / production-real / tested) and forbids answering until all three pass.
---

# The Three Gates

The operator's standing rule, in their words:

> Before you submit me the result, ask yourself:
> 1. Is this 100% accurate?
> 2. Is it production ready and does it behave like real trading?
> 3. Did I do testing?
>
> **Until the answer is yes for all, don't stop fixing and don't provide me an answer.**

This is a **blocking** gate, not a checklist to recite. Run it, then paste the receipts — a gate
the operator cannot audit from your answer did not happen.

## Why this exists (the receipts)

Every gate below was bought with real money on 2026-08-12 — full post-mortem in
`docs/INCIDENT-2026-08-12-BDX.md`:

| Failure | Gate | Cost |
|---|---|---|
| Sweep published where every fill was free (zero slippage) — BDX showed +$1,560 | 1 | operator sized real money off it |
| One generic 0.03%/side charged to 941 different order books | 1 | +$698 shown for a config that cannot win a single trade |
| Bot assumed its stop existed instead of verifying it rested on MEXC | 2 | naked positions stacked → **liquidation, −$27.74** |
| Bracket prices sent with more decimals than the contract allows (2015) | 2 | positions opened unprotected |
| `open_positions()[0]` grabbed the wrong side mid-churn | 2 | orphaned position, −$3.62 |
| Ladder rung exceeded the venue's per-order cap (2051) | 2 | trades silently lost |
| Rebuild finished fast because MEXC rate-limited and served truncated history | 3 | would have published −1,280 where truth was −14,018 |
| **The 2078 liquidation-escape fallback had two identical ternary branches** | 3 | the escape path guaranteed the liquidation it existed to prevent — found by audit, never ran |
| **`trend50` live averaged 50 bars incl. the current one; the backtest excluded it** | 3 | the backtest measured a strategy that never traded |

The last two were found by an adversarial audit *after* the tests were green. Green tests are the
floor, not the ceiling.

## Scope — size the gates, never skip them

Every turn passes every gate. What changes is the **evidence** each needs.

| Tier | Trigger | Gate 1 | Gate 2 | Gate 3 |
|---|---|---|---|---|
| **A — Talk** | No number, no file changed | State any claim you did not read with your own eyes | N/A — say so | Cite the `file:line` you opened |
| **B — Code** | Any repo edit | Reread the diff; name behaviour changed but untested | Full, if the diff touches order/position/PnL paths; else "N/A — reason" | Whole suite (`pytest tests/ -q`, ~1190 tests, ~25s) + a **proven-red** regression test |
| **C — Numbers** | Any figure the operator could size money off | Full, incl. per-item costs and a priced range | Simulation-fidelity form (never N/A) | Independent recompute + scripted internals assertion + the CLAUDE.md publish checklist |
| **D — Live** | Anything that can send an order | Full | Full + portfolio worst case in dollars, before it runs | Live path exercised, or name the ladder rung reached |

Spanning two tiers → use the higher. **"N/A" is legitimate only with its reason attached.**

## Load this at PLAN time, not only at delivery time

Two checks cannot be retrofitted. Before writing the first line of a Tier C/D computation:

- What will this number be most sensitive to? (fees, **slippage**, depth, funding, data completeness)
- Is the target edge bigger than the cost of touching the market **on the worst instrument in the
  set**, not the average one? If no, that IS the answer — 30 seconds instead of an hour.
- Does the data exist at the resolution and window actually asked for?

## Gate 1 — Is this 100% accurate?

**Pass condition (terminal — this is what "yes" looks like, so the loop can end):**

1. Every cost touching the number is **measured per item** (per coin, per contract) — or the
   unmeasured ones are named **in the deliverable**, not a footnote.
2. You computed the number under the pessimistic assumption as well as the base one, and the
   deliverable **leads with the pessimistic figure**.

**Presenting the priced range IS the pass. A single point estimate with the caveat in prose is the
fail.** Gate 1 never demands certainty — it demands the uncertainty be measured, bounded, and
visible in the number read first. Cannot bound it? That is a BLOCKED gate, not an infinite loop.

Checks:

- **Name every assumption aloud.** Market-facing means at minimum: fees, slippage, book depth,
  venue limits, funding, data completeness.
- **Would a different reasonable assumption flip the sign?** Then it is not accurate — compute the
  range. (BDX: +$1,568 at zero slippage, −$135,790 at measured. That spread *was* the answer.)
- **Is a per-item cost being applied globally?** One average across heterogeneous items is an
  assumption wearing a measurement's clothes.
- **Did the data arrive intact?** Truncation, rate limits and partial pages produce confident wrong
  numbers. State provenance — path, first and last timestamp, row count — and re-fetch a sample.
- **Do the internals agree?** `wins + losses + breakeven == trades` (this engine counts wins as
  `pnl > 0` and losses as `pnl < 0`, so flat trades are neither — show breakevens, never reclassify
  them); each trade log's final running total == its summary profit; monthly figures sum to total.
  **Assert over the FULL result set in a script and paste the output** ("941 rows, 0 mismatches").
  If an identity fails, fix the NUMBER, never the identity.
- **"Lead with the pessimistic end" means the number IN the cell**, not a sentence above the table.
  The mandated PROFIT column carries the pessimistic figure; the optimistic goes in a separate
  labelled column. A caveat the operator can sort or screenshot away from is not a caveat.
- **Never write "100% accurate" about a prediction.** The honest form: "verified accurate to these
  measured costs; here is the residual I cannot remove." Saying yes to an impossible claim is worse
  than saying no.

## Gate 2 — Production ready / does it behave like real trading?

**Pass condition:** the path ran against the real venue (or a named rung of Gate 3's ladder),
**every rejection code below has a handled branch, a loud log and a ledger row**, and anything
non-applicable is marked "N/A — reason".

Known venue rejections — this finite list *is* the checklist, so the gate is answerable:
**2015** precision · **5003** price past the stop · **2051** size over per-order cap ·
**2078** too near liquidation · **510/429** rate limit.
Meet a code not on this list → handle it *and add it here in the same change*.

At Tier C/D Gate 2 is never N/A; it takes one of two forms — say which:
- **Order-path form**: exercise the real path, then read the resulting state back from the exchange.
- **Simulation-fidelity form**: the venue is the counterparty you simulated. Could this fill exist
  at this price, at this size, at that moment (depth, tick/lot rounding, order caps)? Does the
  simulated config match the live runner parameter-for-parameter? **Name the live function compared
  against.**

Checks:

- **Portfolio math before anything runs.** Per-trade safety does not compose. State in dollars:
  worst-case simultaneous committed margin (Σ `base_margin × LADDER[-1]` over every enabled
  coin × strategy), that as a % of **actual venue equity**, the margin mode, and what happens when
  every enabled coin moves the same way at once.
- **Costs**: fees AND measured slippage AND funding AND venue caps. Compute
  **round-trip cost ÷ take-profit** before anything else. Under 20% comfortable; near 50% fatal;
  above 100% impossible. BDX ran at 734%.
- **The exchange is the source of truth — for STATE and for MONEY.** Verify the stop rests
  (`verify_position_stop`), the position is open/closed (`open_positions`), the PnL is real
  (`position_history`). Any figure a *control* acts on (loss limit, kill switch, ladder step) must
  be venue-realised, never a bracket-price estimate. **A control reading an estimate is a control
  that does not exist.**
- **Never assume an exit happened.** Barrier crossed with no bracket confirmed resting → the runner
  closes the position itself.
- **Can this orphan money?** A sweep every cycle, scoped to the ACCOUNT not the config — a sweep
  over the configured coin list cannot see a position on a coin just removed.
- **What does this change do to positions ALREADY OPEN?** Before editing the engine, its settings,
  or the strategy table: check `runner_pid()` and `open_positions()`, then state the effect on each
  in-flight position of a mode flip, an untick, a TP/SL change, and a restart. **A restart is a
  trading decision.**
- **What does DEGRADED look like — does it shed risk or add it?** Rate limits arrive when the market
  moves. Risk-reducing calls (rest a bracket, verify a stop, close) must not share a failure path
  with risk-taking calls (scan, enter). Under degradation: stop entering first, keep managing exits.
- **Does STOPPING leave it safe?** A kill switch that only blocks entries is not a kill switch. On
  halt every position is flat or **proven** bracketed — re-read from the venue, never assumed.
- **Exercising the venue has a protocol:** dry-run/validate > read-only > smallest permissible
  notional > nothing. **Anything that can hold a position needs explicit operator consent.** End
  every live exercise with an `open_positions()` check pasted in, confirming flat.

## Gate 3 — Did I do testing?

**Pass condition:** it ran, and you looked at the real output with your own eyes.

- `.venv/bin/python -m pytest tests/ -q` — the whole suite, not just the file touched.
- **A regression test proven RED**, not assumed red: revert the fix, run the test alone, paste the
  failure; restore, paste the pass. A test written after the fix and never seen failing agrees with
  the code, and will agree with the bug when it returns.
- **Failure branches you cannot trigger live still need tests.** Every venue error the code names
  gets a fake venue that RAISES it, asserting what happens **to the position**, not that it logged.
  *No `except` matching an error code ships without a test that triggers it.*
- **Directional paths need BOTH sides asserted** — closing a long vs a short, buy vs sell limits.
  A copy-pasted ternary with identical branches passes every one-sided test. (It did.)
- **One rule, two implementations = drift.** Where a rule exists in both a live `sig_*` and a
  vectorised `_dirs_for_backtest`, the equivalence test must be **differential and randomized**:
  many seeds, every bar, mismatch count reported. A last-bar check missed trend50 for weeks.
- **UI**: the `verifying-ui-with-playwright` loop — restart by PID, `verify.sh --find`, then **Read
  the screenshot**. HTTP 200 is not verification.
- **Live behaviour ladder** — name the rung reached: (1) real call against the venue (read-only
  endpoints are always available and always count), (2) validated/dry-run request, (3) recorded
  fixture with its capture date, (4) hand-written mock. **Rung 4 does not pass Gate 3** — report
  "Gate 3 PARTIAL — mocked only" and name the rejection codes the mock never produces.
- **Data/artifacts**: recompute a sample by a **different path** than the one that produced it
  (hand arithmetic, or a throwaway script not importing the engine) — best row, worst row, 3 random
  rows, agreeing to the cent. Re-calling the same function is not independence. Where the artifact
  re-simulates in-page, that JS is a **second engine**: its TOTAL must equal the Python cell to the
  cent. **Publish only after the check passes** — never publish first and verify after.
- **Artifacts have a second blocking checklist**: CLAUDE.md's columns 1–8 and kit A–E. The two
  lists compose; neither substitutes for the other.

## Money first

If at any point — mid-task, mid-refactor, mid-artifact — you observe real money exposed right now
(an open position with no verified stop, a failed close, an adopted orphan, a dead runner holding
positions, a possible double-send), **STOP the current task.** Make it safe or halt the engine, tell
the operator in one line what you found and did, then resume. A correct table delivered while a
position is naked fails all three gates at once.

## Report the gates, do not claim them

Every delivery ends with ONE line naming **evidence** — a file, a count, a runtime, a number —
never a verdict:

    Gates — 1: per-coin slippage from live depth, 28/28 books read; range −$135,790 (measured) …
    +$1,568 (zero-slip), leading measured | 2: sim-fidelity form, depth walked at top ladder rung,
    matches auto_trader.margin_for | 3: 1192 passed 24.7s; regression proven red then green;
    BDX row recomputed by hand −$141.02 vs engine −$141.02

**"Verified", "checked", "looks right", and "all three gates pass" with nothing after them are not
evidence — they are the exact sentence this skill exists to prevent.**

## The stop rule

```
while not (gate1 and gate2 and gate3):
    fix what failed
    re-run the gates
```

A gate that cannot be passed (the data to be certain does not exist — e.g. 1-minute history beyond
13 days) is **reported as blocked**, with what it would take to pass and the conservative number
leading. Never quietly downgraded to a caveat under a big green number.

## Red flags — you are about to violate this skill

| Thought | Reality |
|---|---|
| "The warning box explains the caveat" | If the caveat can flip the sign, it belongs IN the number |
| "Tests pass, so it's done" | Green tests missed an identical-branch ternary and a drifted strategy rule |
| "That finished fast" | Fast usually means truncated data or a skipped step |
| "The user is waiting / angry, ship it" | Shipping a wrong number is what made them angry |
| "I'll publish now and verify after" | The wrong version reaches them first and gets acted on |
| "One average cost is close enough" | Heterogeneous items need per-item measurement |
| "All three gates pass" | Name the file, the count, the number — or the gate did not happen |
| "It's the best row in the sweep" | The max of N noisy draws. Show the median and a holdout |
| "The equivalence test passes" | One fixture's last bar is not equivalence. Randomize, every bar, count mismatches |
| "I mocked the order path" | A mock that always succeeds tests nothing. Name the rung |
| "I'll just restart the engine" | A restart is a trading decision. Check for open positions first |
| "Only the config changed" | Config is re-read mid-position. A checkbox can orphan a live 20x position |

## Gate 1 has a blind spot: the label

"Is it accurate" keeps returning **yes** because the NUMBER gets verified. On
2026-08-14 a tile read `+ open (RUNE) +7.59` when RUNE's share was `+0.16` and the
`+7.59` was the sum of four positions. The arithmetic was right, the verification
passed, and the sentence was false.

Before gate 1 passes on anything with a figure on screen, run
**`label-must-match-data`**. Five UI bugs in one night were all this shape: correct
value, lying label.
