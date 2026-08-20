---
name: analyze1hr4hr
description: Find the highest win rate for a coin on given timeframes that STILL makes money, then ship it as an artifact. Use when the operator asks for a high-win-rate strategy for a coin — e.g. "create a strategy for PROVE (1hr and 4hr) with high win rate, test it, show me in a new artifact".
---

# Analyze 1hr / 4hr

The request this answers:

> "is there a way for you to create a strategy for X (1hr and 4hr timeframe)
> that has high win rate — come up with the highest winrate possible, test it
> yourself, then show me the result in a new artifact"

## The trap, and the actual goal

**Win rate alone is free.** Put the target 0.30% away and the stop 5.00% away
and you win 92% of trades while losing $723 a year. Measured on PROVE:

| what | win rate | profit |
|---|---|---|
| highest win rate in the search | 92.3% | **−$723** |
| highest win rate that SURVIVES | 42.8% | +$189 |

So the goal is never "max win rate". It is **the highest win rate among
configurations that survive**, with the trap shown beside it so the operator
sees why the 92% row is not the answer.

## Store first — MANDATORY (operator: "not from scratch")

Never compute what the store already holds. Build payloads with
`backtest_report.grid_from_store(coins, tfs, deployed=…)` — it serves rows
from `market_sweep`'s pair store, computes ONLY bars printed since the last
run, computes a missing deployed combination once, and stamps the page with
`Store: N rows reused · M new bars tested · K recomputed`. Losers are stored
too ("i want everything stored"); the trade floor still applies. A stale
signal-library version resets the pair automatically.

## Grid — every field varies

| Dimension | Values |
|---|---|
| Timeframe | every one the operator named, each searched equally |
| Signal | EVERY entry in `backtest_report.SIGNALS` — read the list, never hardcode it. 75 as of 2026-08-19: the 7 originals, 15 in `signals_ext` (fibonacci, S/R, bands, oscillators), 53 in `signals_ext2` (Supertrend, Ichimoku, PSAR, ADX, ICT order blocks/BOS/CHoCH/Turtle Soup, candle patterns, volume rules) |
| Threshold | 3 per timeframe for mom6/mom15/fade15 — it changes which bars fire at all |
| SL | ~10 values, from well inside to near the liquidation distance |
| TP | ~11 values, from below round-trip cost to far above |
| Sizing | flat AND martingale, both, always |

At 75 signals that is ~17,000 combinations per timeframe (33,188 measured for
APEX 1h+4h, 542s). Drop anything under 30 trades.

## The signal list is a RESEARCH product, not a fixed menu — MANDATORY

The operator's instruction (2026-08-19, after being shown 22 signals):

> "it seems you only do what i told you and you are not researching what are
> possible strat outside" ... "research more this is still few"

The engine's list must grow toward what EXISTS, not wait for the operator to
name rules one by one. When they ask for "different strategies" or more of
them:

1. **Research outside the codebase** (web search: trend systems, oscillators,
   mean reversion, breakouts, ICT/SMC, candle patterns, volume rules,
   crypto-native like funding-rate fade). Present what exists, grouped, marked
   buildable-now vs needs-data-we-don't-have.
2. **Implement every crisply-definable single-coin rule** into
   `signals_ext2.py` (signature `(opens, high, low, close, volume, ts)`;
   a rule whose stream is missing ABSTAINS with zeros, never guesses).
   Skip fuzzy pattern recognition (head & shoulders) and say so.
3. **Wire BOTH dispatch paths**: `auto_trader._dirs_for_backtest` (backtest)
   AND `auto_trader.signal_for` (live runner). The first expansion was
   backtest-only for a day — a deployed fib618 strategy would have emitted 0
   forever. A test pins live/backtest parity
   (`test_live_signal_for_reaches_both_expansions`).
4. **Test the invariants** per rule: no look-ahead (truncation test), output
   alphabet {-1,0,1}, fires on a series containing its pattern, abstains when
   its stream is missing, no name shadows another in prefix dispatch.
5. **Add the names to `backtest_report.SIGNALS`** so the app's backtest button
   sweeps the identical grid — the count test derives from both registries,
   never a pinned number.

History of this rule: "Fibonacci is not in the engine, say so" was correct on
2026-08-18, stale by the 19th when `signals_ext` landed, and the renderer's
hardcoded copy of it shipped a false label over a grid that contained
fib618 rows. State what the engine implements TODAY by reading the registry.

## Mandatory: model liquidation

`backtest_strategy(..., liq_move_pct=fx.liquidation_move_pct(coin, LEVERAGE))`

Without it the search crowns wide stops that the venue would never let fire.
On PROVE the first pass returned a 68% win rate on an 8.00% stop — at 20x MEXC
closes at 4.50%, so that trade loses the whole margin, not 8% of notional.
Modelling it cut survivors from 36 to 21 and deleted every wide-stop winner.

Mark rows whose stop sits beyond liquidation **STOP UNREACHABLE** and exclude
them from survivors.

## Three costs, not two — MANDATORY

A perpetual charges for **getting in**, **getting out**, and **staying in**.
`backtest_strategy` handles the first two by default (taker fee + 0.03%/side
slippage). The third is `funding`, and it must be passed:

```python
at.backtest_strategy(..., funding=fx.funding_history(coin))
```

Every settlement inside a trade's own window is applied at its real published
rate, so a 6-hour trade pays one cycle and a 5-day trade pays thirty. Sign is
MEXC's: a positive rate means longs pay shorts, so a short can be paid to hold.

Measured 2026-08-19 across the five live strategies, $5 base:

| coin | median hold | before | after | funding | change |
|---|---|---|---|---|---|
| PROVE | 6h | +$184.63 | +$176.04 | −$8.59 | **−4.7%** |
| APEX | 5h | +$128.25 | +$127.23 | −$1.02 | −0.8% |
| PI | 8h | +$1,004.10 | +$1,002.58 | −$1.52 | −0.2% |
| ALICE | 2h | +$444.77 | +$447.02 | **+$2.25** | +0.5% |
| XAUT | 25h | +$94.54 | +$94.98 | +$0.44 | +0.5% |

Note ALICE and XAUT: funding **paid them**, because they hold the side that
receives. Charging it is not pessimism, it is accuracy — omitting it is simply
a different number from the one the exchange would have produced.

Traps:

* **The page must replay funding too**, from settlements embedded per coin, or
  the trade log stops summing to the row it belongs to.
* **Convert bar timestamps through `datetime64[ms]`**, never by dividing a raw
  `int64`. MEXC frames arrive as `datetime64[s]`, so a nanosecond divisor read
  **1,754** instead of 1,754,406,000,000; every funding window then spanned the
  entire history and PROVE's year came out at **−$2,230 instead of +$176**.
  A test pins this (`test_funding_window_survives_second_resolution_timestamps`).
* **Rates are not small on every contract.** PROVE's history contains −2.00%
  settlements. One trade held through several is not a rounding error.

## The survivor test

All five, or it is not a survivor:

1. profitable overall
2. profitable in the **first half** of its history
3. profitable in the **second half**
4. green in **≥70% of months**
5. past the liquidity gate (round-trip cost < 50% of TP) **and** stop reachable

Then report separately: **best flat survivor**. Flat is how the signal is
measured; a row that only wins on the ladder is telling you about the ladder.

## Default sort: BALANCED — MANDATORY

The operator's instruction:

> "i want you to sort always by balance like profitable, high winrate and
> consistent on top"

Sorting by win rate alone puts a 70%-win / +$67 row above a 22%-win / +$1,197
row. Sorting by profit alone puts a 12%-win row on top. Neither is what they
want to see first.

**Default the table to a BALANCED score**, shown as its own column, combining
the three things they named — profitable, high win rate, consistent:

```
score = z(profit) + z(winrate) + z(months_green_pct) - z(max_dd)
```

Rank each survivor against the other survivors on each axis (a plain z-score
or percentile is fine), add them, subtract drawdown. Show the raw components
next to it so the ranking is never a black box the operator has to trust.

Rules:

- **BALANCED is the default sort on load.** Win rate, profit and this month
  stay clickable, and stay in the table.
- **Survivors only in the default view.** A high score on a non-survivor is
  meaningless.
- **Drawdown is subtracted, not ignored** — a +$1,197 row with a $141 dip on a
  $65 wallet is not "top" for this operator.
- Name the formula in the footer, in one line, in plain words.

## Highlight the recommendation — MANDATORY

The operator's instruction:

> "highlight the ones you recommend — always do this"

A ranked table is not an answer. Say which rows to actually run, in the
artifact itself, marked so they are visible without reading anything.

- a **RECOMMENDED** badge on the qualifying rows, plus a green left rail
- pinned **at the top of the table regardless of the current sort**
- a short **why** on each one, in the row or its card: the single reason it
  earned the badge ("17/17 months green", "only row whose dip fits the wallet")
- a **RECOMMENDED** panel above the grid naming them in full — coin, timeframe,
  signal, threshold, SL, TP, sizing — so they can be deployed without guessing
- never more than **3**. A list of ten recommendations is a ranking, not advice.

Qualify a row only if ALL hold:

1. it is a survivor
2. its **drawdown fits the operator's wallet** (dip < half the wallet at the
   base margin shown) — a +$1,000 row with a $141 dip on a $65 account is not
   a recommendation
3. it has **≥100 trades**, so the record is not a handful of lucky months
4. it is **top-20 by BALANCED score**

If nothing qualifies, say so plainly and show what would need to change —
usually a smaller base margin. Never promote a row to fill the slot.

## Monthly breakdown — MANDATORY

Every row carries **its result for each calendar month**, and the artifact shows
**this month** as its own sortable column. The operator asked for it explicitly:

> "put the result per month as well so i know which one are working for this month"

- one column per month (`2026-08 $`, `2026-07 $` …), newest first
- a **THIS MONTH** column, pinned next to PROFIT, sorted on by default when the
  operator asks what is working now
- the trade count for this month beside it — a +$20 month on 3 trades is a coin
  flip, and the row must show that
- never present this month's ranking as a recommendation: 2–3 weeks cannot
  separate a better strategy from a luckier one. Say so once, in the footer.

Collect it from `backtest_strategy(...)["monthly"]`, which already returns a
`{"YYYY-MM": pnl}` dict — no second run needed.

## Report — per timeframe, then across

- best win rate that survives, with its profit
- best FLAT win rate
- best that fits the operator's wallet (drawdown < half the wallet)
- **best THIS MONTH**, with its trade count, and how many survivors are up vs down
- the highest win rate ignoring profit, as the trap
- when several timeframes were asked for: **which timeframe wins, and by how
  much**. Fewer survivors is itself the finding — 30m gave 5 of 2,860 against
  1h's 21 of 3,432, and that is the answer, not a gap.

## Artifact

Follow `CLAUDE.md` items 1–8 and the standard kit A–E. Plus:

- **win rate as a first-class column**, next to PROFIT, never alone
- verdict column: FLAT SURVIVOR / survivor / profitable / rejected / STOP UNREACHABLE
- threshold column — two rows identical but for threshold are different strategies
- embed the candles and the per-signal direction arrays so every row replays
  trade-by-trade in-page and the base-margin box **re-simulates** rather than
  rescaling
- **clicking a row opens its PAST TRADES immediately** — the operator asked for
  this explicitly. The panel must:
  - **scroll itself into view** on click; a log below the fold does not exist
  - be headed `PAST TRADES · N` so it is obvious what opened
  - lead with **OPENED / CLOSED / HELD**, then side, closed-by, entry, exit
  - carry a TOTAL PROFIT footer that equals the sum of its own rows
  - state the date range covered, so a 30-trade row is visibly thin
- a wallet box: green-bar the rows whose drawdown fits it
- footer stating the trap explicitly, with its numbers

Verify before publishing: the replayed log must sum to the row's total, and the
row's win rate must equal the detail panel's.

## Filters — MANDATORY

The operator's instruction:

> "can you show me filter like / filter by winrate / filter by profit total /
> filter by green"

A 23,000-row grid with only a Show dropdown makes them read instead of ask. Every
results artifact carries these, as live-typing number boxes in the Controls row:

| Filter | Rule |
|---|---|
| **Min win rate %** | hide rows winning less often |
| **Min profit total $** | measured at the CURRENT base margin, not the stored one |
| **Min months green** | a COUNT of months, as the GREEN column prints it: 10 hides every 9/12 row |
| **Max worst dip $** | the operator's real constraint — their wallet |
| **Last N months** | RE-RUNS every row over just that slice of candles |
| **CLEAR FILTERS** | one button, empties all of them |

Rules:

- **They stack**, and they compose with Show / Coin / Timeframe.
- **Dollar filters run on the re-simulated figures.** `profit >= $200` at $10 base
  is a different set than at $5. Filtering stored values while the page shows
  rescaled ones is a label that disagrees with its data.
- **The count line names the active filters** — `2 of 23296 shown · filters:
  win >= 55% · green >= 90%`. A bare "2 of 23296" hides why.
- **Zero rows says so in the table body.** A blank table reads as broken, and the
  message must name the actual cause (an ID miss is not a filter miss).
- **A filter takes the unit the column PRINTS, not a derived one.** The GREEN
  column prints `11/12`, so `MIN MONTHS GREEN` counts months: set 10 and every
  9/12 row disappears. Shipping it as a percent instead was wrong twice over —
  the operator typed 11 meaning eleven months, matched 14,924 rows, and reported
  the filter dead; relabelling the box `Min green % (17/17=100)` did not fix it,
  because their instruction was *"if i set min green to 10 then you should not
  show 9 months green"*. Ship the share as its own sortable column (`GREEN %`)
  if it is useful for ranking — never as the thing the box takes.
- **When a filter cannot bite, say so where the count is.** A count above the
  deepest history in view can never match: print `no coin here has 18 months of
  history — the deepest is 17`, rather than going blank and reading as broken.

## "Last N months" re-simulates — MANDATORY

The operator's instruction:

> "add filter, last x month, if i set this to 3 months then show me last 3
> months of data only meaning you should show the total profit, no of trades,
> lose, winrate for past 3 months"

**A time window is not a row filter.** Hiding rows would leave a PROFIT column
covering a year under a label saying three months. Re-run the replay from the
first bar inside the window, and let EVERY figure fall out of that run: profit,
trades, wins, losses, win rate, months green, both halves, worst dip, worst
streak, trades/day, the month columns and the trade log.

Measured on PROVE mom6 1h at $5 base, one page, three window settings:

| window | profit | trades | W / L | win rate | verdict |
|---|---|---|---|---|---|
| full year | +$236.93 | 605 | 261 / 344 | 43.14% | survivor |
| last 6 months | +$172.33 | 214 | 98 / 116 | 45.79% | survivor |
| last 3 months | +$75.17 | 134 | 57 / 77 | 42.54% | survivor |
| last 1 month | +$24.07 | 24 | 12 / 12 | 50.00% | **profitable** |

Two traps this caught, both invisible until the window existed:

* **WIN % was never re-simulated.** It does not change with the base margin, so
  it had never needed to be — under a window it silently kept the year's
  43.14% beside 57 wins of 134. Any figure the page can change must be derived
  from the replay, not carried from the payload.
* **The VERDICT went stale.** A row labelled `survivor` on a year is only
  `profitable` on one month (1 of 2 months green is under the 70% bar).
  Recompute survivor/verdict from whatever is on screen, or the badge argues
  with the row it sits on.

Also: **print the window's real dates** in the count line —
`window: last 3 months (2026-05-18 → 2026-08-18)` — and mark the trade-log
header `PAST TRADES · 134 · LAST 3 MONTHS ONLY`.

**The month columns follow the window.** The operator's words: *"if i input 3
months then show 4 months, no need to show other months as -"*. A trailing
3-month window starting mid-May reaches into four calendar months, so it gets
exactly those four columns and the other thirteen are REMOVED, not filled with
em dashes. Rebuild the month headers whenever the window changes; a `—` must
only ever mean "no trades that month", never "outside the window".

## Worst LOSING STREAK, not worst trade — MANDATORY

The operator's instruction:

> "for worst trade, it should be the sum of the lose streak"

A single worst trade is the wrong number to show a martingale operator. On their
live APEX row the worst single trade is **-$9.12** — survivable. The worst
unbroken run of losses is **-$79.80 over 13 trades, 7-20 Oct 2025**, against a
$65 wallet. The ladder is exactly why: consecutive losses get bigger, so the run
is what empties the account, and a "worst trade" column hides it.

- **`WORST STREAK $` is a first-class column**, next to `STREAK LOSSES` (how many
  in a row). Keep the single worst trade too, renamed `WORST SINGLE TRADE $` —
  never let it wear the plain label `worst trade`.
- **The detail panel names the dates the streak ran**, so the operator can see it
  was two weeks and not two years.
- **Derive it from the same replay everything else uses**, so it rescales with the
  base-margin box. It is not in the sweep output — the sweep stores no logs.
- **Compare it to the wallet, not to the profit.** A row earning +$126 with a
  -$79.80 streak on a $65 wallet did not survive; it was liquidated in reality.

A trap that bit while shipping this: `view()` returns the RAW payload row when the
base margin is unchanged, so a field that exists only on the re-simulated copy
threw `Cannot read properties of undefined` and rendered **zero rows**. Derive
per-row extras in the same memoised pass that fills the month trade counts, hang
them on the row itself, and key that cache by base margin.

## Columns the operator does NOT want

Removed at their request, and they stay removed:

| Column | Why it goes |
|---|---|
| `base $`, `notional $` | constant on every row — they belong in the provenance line above the table and in the detail panel, not in 23,000 identical cells |
| `1st half`, `2nd half` | the survivor test still uses them; the operator reads the verdict, not the halves |
| `green %` | `GREEN` already prints `11/12`, and the filter counts months, so the share is a second unit for the same fact |

Keep the DATA — `h1`, `h2` and the derived share are still needed by the
survivor test and the BALANCED score. It is the *columns* that go.

## The app's backtest button runs THIS grid — MANDATORY

The operator's instruction:

> "when i request it always update the backtest automatically ... i want to see
> result just like the artifact, the code used in artifact should only be
> reused to backtest button"

**One grid, one renderer, no monkeypatching.** The analysis and the in-app
`1 YEAR` button both call `tradingagents.backtest_report`, and the barrier grid
lives in `BARRIERS` there. An analysis must NEVER widen the grid locally for its
own artifact — widen the module, so the next click contains the same rows.

What went wrong when they diverged: the artifact recommended 1h SL 1.50 /
TP 2.00 and the button's six-pair grid had never tested it, so the operator
could not find a single recommended row inside their own app. `BARRIERS` is now
110 pairs per timeframe (10 stops x 11 targets), identical for 1h and 4h,
because those are the two this skill sweeps.

Rules:

- **Publish nothing the button cannot reproduce.** Before publishing, check the
  recommended rows exist in `BARRIERS`; a test pins this
  (`test_the_app_grid_contains_every_row_the_analysis_publishes`).
- **1h and 4h share one barrier list.** A "scaled" 4h list looks more
  principled and silently dropped SL 1.00 / TP 3.00 — a row that had just been
  recommended.
- **Deployed barriers are injected on top** (`pairs_for`), because a live
  0.80/2.40 pair is in no grid of round numbers.
- **State the cost.** The wide grid means a click takes minutes, not seconds:
  measured 164 seconds for one coin across 1h and 4h at 7 signals (5,720
  rows), 542 seconds at 75 signals (33,188 rows). That is the
  price of the button and the artifact agreeing.
- **Row codes make the check trivial**: the same combination hashes to the same
  ID in both, so "is it there?" is a lookup, not a comparison of six fields.

## Row IDs — MANDATORY

The operator's instruction:

> "add ids for each row so i know what specific row to look for"

Without them, "the first row" means one thing to them and another to me. That
exact ambiguity deployed the wrong config on 2026-08-17 (see `CLAUDE.md` 21-22),
and produced "row 5 is deployed" / "row 6 is deployed" in two different tables.

- **`ID` is the first column**, `#LLZM9D2K`, eight characters, monospace (widened from six on 2026-08-19: at 75 signals a 6-char/30-bit code collided on PROVE — two different rows, one ID).
- **Derived from the combination itself** — a hash of coin, timeframe, signal,
  threshold, SL, TP, sizing (`backtest_report.row_code`). NOT a sequence.
  Sequential numbering looked stable inside one page and was useless across
  two: the live APEX row was `#05146` in one artifact, `#02054` in another and
  something else again in the app, and the operator said *"i dont see that id
  when doing backtest"*. A code travels with the row, between pages and between
  runs, and survives a grid that gains or loses rows.
- **Normalise before hashing.** A signal with no threshold was stored as `0.0`
  by one sweep and `0.3` by another, which handed the same live strategy two
  different codes. Zero the threshold for signals that do not use one.
- **Assert uniqueness when building** and raise on a collision — two rows
  sharing a name is exactly the failure the code exists to prevent.
- **A "Find row ID" box** jumps straight to one: it overrides every other filter
  (a looked-up row must never be hidden by a filter left set from before),
  opens that row's trade log, and scrolls it into view.
- **The find box is case-insensitive** and ignores punctuation, so a pasted
  `#llzm9d` works.
- **A missing ID says so**: `no row #XXXXXX in this grid of 23296`.
- **The ID appears in the detail panel and in every callout** — RECOMMENDED,
  DEPLOYED, the summary cards — so a quoted row is unambiguous.
- **When answering about a row in chat, lead with its ID.** "#05146 APEX 1h
  sweep30" cannot be confused with a neighbouring row.

## Never trim per-row data for SOME rows

When the payload is too big, compress the **encoding**, never the **coverage**.

On 2026-08-18 the packing step did this to fit the size cap:

```python
for r in rows:
    if not surv(r):
        r['monthly'] = {cur: r.get('monthly', {}).get(cur, 0.0)}   # WRONG
```

22,482 of 23,296 rows lost their month-by-month numbers. It went unnoticed because
the table defaults to survivors-only, and survivors were the rows that kept theirs.
The operator switched the filter to **all**, landed on their own LIVE APEX config,
and saw eleven empty month columns on a row with 307 trades over 325 days.

The fix that should have been written the first time — same data, 1/4 the bytes:

```python
r['mon'] = [monthly.get(m) for m in MONTHS]   # array aligned to the month header
r.pop('monthly')                              # decoded back to a dict in one JS line
```

Rules:

- **Every row carries every column, or the column does not exist.** A blank cell
  must mean "this month did not exist for this coin", never "I dropped it".
- **Shrink by re-encoding**: arrays instead of repeated keys, ids instead of
  strings, 2dp instead of 6. Never by dropping rows' fields.
- **Verify OUTSIDE the default filter.** Flip every filter to its widest setting
  and check a row the default hides — that is where trimming hides.
- **Check the live/deployed row specifically.** It is the one row the operator is
  guaranteed to look up, and it is often not a survivor.

## Red flags

| Thought | Reality |
|---|---|
| "89% win rate, ship it" | Check the profit column. It is probably −$237 |
| "wide stop, more room" | Past liquidation the stop cannot fire at all |
| "one timeframe is enough" | They asked for two. Search both equally |
| "the ladder version wins" | Report flat too, or you are measuring the ladder |
| "close enough to the operator's row" | Name the exact six fields back to them |
