---
name: blast-radius
description: Use after ANY code change in this repo, before reporting it done — especially fixes to the trading engine, state, ledger, settings, or shared risk logic. Forces enumeration of every other reader and writer of what was touched, because in this repo the NEXT bug is always in the seam the last fix created.
---

# Blast Radius

The operator named the failure precisely:

> "It's like you are fixing bugs without thinking the connected feature to fix."

That is the pattern. Not carelessness in the fix itself — every fix here was correct in
isolation. The bug was always in something ELSE that reads the same field, state key,
ledger row or invariant, and was never looked at.

**A fix is not done when it works. It is done when every reader of what you changed has
been checked.**

## The receipts — seven bugs in one day, all seam bugs

| The fix | The seam it broke | Cost |
|---|---|---|
| Bracket prices rounded for precision | Position *lookup* took `open_positions()[0]` — grabbed the wrong side | orphan, −$3.62 |
| Orphan adoption added | The adopted dict had no `dry` key → the demo could "close" real money | mis-accounted real loss |
| Paper and real split into two books | Risk limits still summed BOTH → a demo loss would halt live trading | breaker unreliable |
| `_closed_bars` filter added | Assumed nanosecond dtype; pandas 3 returns `datetime64[s]` → silent no-op | traded unbacktested rule |
| `trend50` live rule corrected | The *backtest* copy of the rule still had the old one | backtest measured a phantom |
| Exit check tightened to 5s | Would have re-downloaded candles every 5s → truncated history | near-miss |
| 2078 liquidation fallback written | Both ternary branches identical → could never fill for a short | escape path guaranteed liquidation |
| First BDX fix (self-close when bracket never verified) | Said nothing about a bracket that verified once and later vanished | the original loop survived |

Read that table before deciding a fix is finished.

## The procedure — mechanical, not intuitive

Intuition is what failed. Do this instead, and paste the evidence.

### 1. Name what you changed, precisely

One of these, always:
- a **field** on a dict that outlives the function (`pos["dry"]`, `pos["margin"]`)
- a **state key** (`state[symbol]` → `state[symbol + "#paper"]`)
- a **ledger row** shape or a new `action` value
- a **settings key** (`settings["loss_limit"]`)
- a **function's** return shape, or a new early-return / new exception path
- a **constant** (`DRY_EXIT_POLL_SECONDS`, `TAKER_FEE`, a threshold)
- an **invariant** ("the runner only trades configured coins", "one book per coin")

### 2. Enumerate every reader and writer. With grep. Paste the output.

```bash
grep -rn 'pos\["margin"\]\|\["margin"\]' tradingagents/ app.py tests/
grep -rn 'state\[' tradingagents/auto_trader.py app.py
grep -rn 'pnl_today\|ledger_since\|ledger_tail' tradingagents/ app.py
grep -rn 'loss_limit\|tripped_strategies' tradingagents/ app.py
```

A reader you did not grep for is a bug you have not found. **"I think that's all of them"
is not an answer** — the command output is.

### 3. For each reader, answer out loud: does my change alter what it sees?

Three specific questions that caught real bugs here:

- **Does it read a field my change can now leave absent or different?**
  (`pos.get("dry", dry)` fell back to the *current checkbox* when the key was missing.)
- **Does it aggregate across something my change split?**
  (Risk limits summed paper + real after the books were separated.)
- **Is there a SECOND implementation of the same rule?**
  Live `sig_*` vs backtest `_dirs_for_backtest`; Python engine vs the artifact's JS
  re-simulation; `spx_bot` vs `auto_trader`. Fix one, and the other now disagrees.

### 4. Walk the seam list for this repo

Every change touching the engine gets checked against all of these:

- [ ] **Live vs paper** — does it behave correctly in BOTH books, and can one affect the other?
- [ ] **Live vs backtest** — is the same rule implemented twice? Do they still agree?
- [ ] **Book vs exchange** — does it trust local state where the venue is the truth?
- [ ] **Risk controls** — do the loss limits, kill file, gate and chase guard still read the
      number they think they read?
- [ ] **Accounting** — margin, notional, vol, PnL: after this change do they still describe
      the same trade? (A capped order kept the full ladder margin and inflated everything.)
- [ ] **Open positions** — what does this do to a position that is ALREADY open, mid-flight?
- [ ] **UI display** — does any panel still read a field or key that moved?
- [ ] **Rate/cost budget** — does it add API calls per cycle? At what multiple of coins?
- [ ] **Persistence** — will an OLD state or settings file on disk still load correctly?

### 5. Test the seam, not just the fix

The regression test for the fix proves the fix. A second test must prove the **seam**:

- fix in the live path → a test that the paper path is unaffected (and vice versa)
- fix to a rule → the differential test that both implementations agree
- fix to accounting → assert the derived numbers, not just the one you changed
- fix to state layout → a test that loads an OLD-format file

Then run the WHOLE suite, never just the file you touched. Two of today's seam bugs
surfaced only as unrelated test failures.

## Red flags

| Thought | Reality |
|---|---|
| "Small, contained change" | Containment is the claim to verify, not to assume |
| "Only the live path uses this" | Grep it. Twice today that was false |
| "The tests pass" | They test the paths you thought of. The seam is the one you didn't |
| "I'll note the follow-up" | The follow-up is the bug. Do it now |
| "The other copy of this rule is probably fine" | Two implementations of one rule always drift |
| "It defaults sensibly if the key is missing" | Name the default and check it. `pos.get("dry", dry)` looked sensible and lost real money |

## One line to remember

**Every fix opens a seam. The next bug is in the seam. Grep the seam before saying done.**
