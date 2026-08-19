---
name: analyze15m30m
description: Find the highest win rate for a coin on 15m and 30m over a FULL YEAR that STILL makes money, then ship it as an artifact. Use when the operator asks for a high-win-rate strategy on the short timeframes — e.g. "create a strategy for PROVE (15m and 30m) over the past year with high win rate, test it, show me in a new artifact".
---

# Analyze 15m / 30m — one year

Sister skill to `analyze1hr4hr`. Same operator directives, same survivor test,
same artifact kit. What changes is the timeframe pair, the history depth, and
**which failure mode dominates** — read the "cost eats the target" section
before running anything, because on these timeframes it is the whole game.

The request this answers:

> "create a strategy for X (15m and 30m timeframe) for the past 1 year that has
> high win rate — come up with the highest winrate possible, test it yourself,
> then show me the result in a new artifact"

## Data depth — MEASURED, not assumed

MEXC really does serve a year at these resolutions. Measured on BTC_USDT,
2026-08-19, by paging backwards until the venue stopped:

| Timeframe | Bars requested | Bars returned | Days | Oldest bar |
|---|---|---|---|---|
| Min15 | 36,000 | **34,654** | **361** | 2025-08-22 |
| Min30 | 18,000 | **18,000** | **375** | 2025-08-08 |

So "past 1 year" is honest here, unlike 1-minute (CLAUDE.md item 13: ~13 days
only). `backtest_report.TFS` already asks for 36,000 and 20,000 bars.

Still state the real depth per coin in the artifact. A contract listed four
months ago has four months, whatever was requested, and a "12/12 months green"
claim on it is a lie. Print `bars` and `days` from the run, per row.

MEXC caps a single kline response at 2,001 candles — `fx.klines()` pages past
that. A run that quietly returns 2,001 bars means the paging was bypassed.

## Cost eats the target — THE dominant risk here

This is the difference between this skill and `analyze1hr4hr`, and it is the
BDX failure in a new costume (see `docs/INCIDENT-2026-08-12-BDX.md`).

The 15m barrier grid's tightest target is **TP 0.20%**. Measured round-trip
costs on real MEXC books:

| Coin | Round-trip cost | vs a 0.20% TP | vs a 0.90% TP |
|---|---|---|---|
| BTC_USDT | 0.040% | 20% | 4% |
| SPX500_USDT | 0.041% | 21% | 5% |
| CHEEMS_USDT | 0.107% | **54% — fatal** | 12% |
| MCDSTOCK_USDT | 0.240% | **120% — impossible** | 27% |
| BDX_USDT | 2.746% | **1,373%** | 305% |

A 0.20% target on anything but a deep book cannot win, no matter how good the
signal or how high the win rate looks. The shorter the timeframe, the tighter
the targets people reach for, and the more of the grid is arithmetically dead.

Rules:

- **Run `edge_check` / `book_cost` per coin BEFORE the sweep**, and print the
  round-trip cost in the provenance line. One average across coins is an
  assumption wearing a measurement's clothes (CLAUDE.md item 10).
- **Reject any row whose cost/TP >= 50%** as the liquidity gate does — mark it
  `COST > TARGET` and exclude it from survivors, exactly like
  `STOP UNREACHABLE`. It is not a survivor; it is impossible.
- **Say how much of the grid died to this.** "38 of 110 barrier pairs on 15m are
  unreachable on this coin's book" is the finding, not a footnote.
- **Never quote a 15m win rate without its cost/TP beside it.** A 90% win rate
  on a target smaller than the spread is the purest form of the trap this
  family of skills exists to catch.

## Liquidation — MANDATORY, same as the 1h/4h skill

`backtest_strategy(..., liq_move_pct=fx.liquidation_move_pct(coin, LEVERAGE))`

Measured on BTC_USDT at 20x: **4.90%**. Note this uses the venue's published
maintenance margin, so it is EARLIER than 100/leverage (5.00%) — and far earlier
on some contracts. Any stop at or beyond it can never fire; the venue closes you
first and takes the whole margin.

On 15m/30m the stop grid tops out at 1.50% and 2.00%, so most rows are safely
inside — but the gate still runs, because a thin contract's liquidation distance
is not BTC's. Mark violations **STOP UNREACHABLE** and exclude them.

## Grid — every field varies

| Dimension | Values |
|---|---|
| Timeframe | 15m and 30m, searched equally |
| Signal | EVERY entry in `backtest_report.SIGNALS` — read the list, never hardcode it. 75 as of 2026-08-19: the 7 originals, 15 in `signals_ext` (fibonacci, S/R, bands, oscillators), 53 in `signals_ext2` (Supertrend, Ichimoku, PSAR, ADX, ICT order blocks/BOS/CHoCH/Turtle Soup, candle patterns, volume rules) |
| Threshold | 3 per timeframe for mom6/mom15/fade15 — it changes which bars fire at all |
| SL / TP | `backtest_report.BARRIERS["15m"]` and `["30m"]` — 110 pairs each, already scaled tighter than the 1h list |
| Sizing | flat AND martingale, both, always |

## The signal list is a RESEARCH product, not a fixed menu — MANDATORY

Same rule as `analyze1hr4hr`, born 2026-08-19 from the operator's words:
*"it seems you only do what i told you and you are not researching what are
possible strat outside ... research more this is still few."* When the
operator asks for more or different strategies: research OUTSIDE the codebase
(web), implement every crisply-definable single-coin rule into
`signals_ext2.py` (`(opens, high, low, close, volume, ts)`, abstain with
zeros when a stream is missing), wire BOTH `_dirs_for_backtest` and the live
`signal_for` (the first expansion was backtest-only for a day — a deployed
fib618 would have emitted 0 forever), pin the invariants (no look-ahead,
alphabet, fires-on-its-pattern, no prefix shadowing), and add the names to
`backtest_report.SIGNALS` so the app button sweeps the identical grid.
State what the engine implements TODAY by reading the registry — "Fibonacci
is not in the engine" was true on the 18th, false on the 19th, and its
hardcoded copy shipped a false label over a grid containing fib618 rows.

At 75 signals expect ~17,000+ combinations per timeframe; on 15m candles the
sweep is minutes-long — say the cost out loud before running it.

### Minimum trades — raise the bar for these timeframes

A year of 15m is 34,654 bars, so trade counts run high: one mom15 config
produced **795 trades on 15m** and **749 on 30m** (measured, BTC, 20x).

The `analyze1hr4hr` bar of 30 trades is therefore meaningless here — nearly
everything clears it. Use:

- **drop rows under 100 trades** (they are the anomaly on this timeframe, and
  usually mean the threshold silenced the signal)
- **require >= 300 trades to earn RECOMMENDED**, not the 1h skill's 100

More trades is not more evidence when each one is smaller. A +$200 year over 795
trades is 25 cents a trade — check that against the round-trip cost before
calling it an edge.

### Runtime — state it, and count the HALF runs

Measured per backtest over a full year: **0.039s on 15m** (34,654 bars),
**0.022s on 30m** (18,000 bars).

`run_grid` runs each combination **three times** — full history, first half,
second half — because the survivor test needs both halves. So the cost is 3x the
naive figure, not 1x:

| Per coin | Combos | Backtests | Measured |
|---|---|---|---|
| 15m | 2,860 | 8,580 | ~6 min |
| 30m | 2,860 | 8,580 | ~3 min |

**~9 minutes per coin for both timeframes**, so five coins is **~45 minutes**,
plus kline paging (18 requests for 15m, 9 for 30m, per coin).

A first version of this skill claimed "~3 minutes per coin" by counting one
backtest per combination. Budget for the halves, and run the sweep in the
background — a 10-minute foreground tool call will be killed mid-sweep.

## Three costs, not two — MANDATORY

A perpetual charges for **getting in**, **getting out**, and **staying in**.
Fee and slippage are charged by default; the third must be passed:

```python
at.backtest_strategy(..., funding=fx.funding_history(coin))
```

Each published settlement inside a trade's own window is applied at its real
rate, so a 6-hour trade pays one cycle and a 5-day trade pays thirty. MEXC's
sign: a positive rate means longs pay, so a short can be PAID to hold.

Measured 2026-08-19 on the five live strategies, $5 base: PROVE **−4.7%**,
APEX −0.8%, PI −0.2%, ALICE **+0.5%** and XAUT **+0.5%** — the last two receive
it. Charging funding is accuracy, not pessimism.

Traps:

* **The artifact must replay funding too**, from settlements embedded per coin,
  or the trade log stops summing to the row it belongs to.
* **Convert bar timestamps through `datetime64[ms]`**, never by dividing a raw
  `int64`: MEXC frames are `datetime64[s]`, and a nanosecond divisor read 1,754
  instead of 1,754,406,000,000 — every window then spanned the whole history and
  PROVE's year read **−$2,230 instead of +$176**.
* **Rates are not always small.** PROVE's history carries −2.00% settlements.

## The survivor test — all five, or it is not a survivor

1. profitable overall
2. profitable in the **first half** of its history
3. profitable in the **second half**
4. green in **>=70% of months** (a year gives 12-13 months here, so this is a
   real test rather than the 2-month coin flip a short history makes it)
5. past the liquidity gate (**cost/TP < 50%**) **and** stop reachable

Then report separately: **best flat survivor**. Flat is how the signal is
measured; a row that only wins on the ladder is telling you about the ladder.

## Everything below is unchanged from `analyze1hr4hr`

These are cumulative operator directives and they apply to every results
artifact in this repo regardless of timeframe. Read that skill for the full
reasoning and the incidents that bought each one; the requirements are identical:

- **Default sort BALANCED** — `z(profit) + z(winrate) + z(months_green_pct) - z(max_dd)`,
  shown as its own column with its components beside it, survivors only in the
  default view, formula named in the footer.
- **Highlight the recommendation** — RECOMMENDED badge, green left rail, pinned
  to the top regardless of sort, a one-line why on each, a panel above the grid
  naming all six fields, never more than 3. Qualify only if: survivor, drawdown
  fits the wallet, >= 300 trades (raised, see above), top-20 by BALANCED.
- **Monthly breakdown** — one column per calendar month newest first, a THIS
  MONTH column pinned beside PROFIT with its trade count, and the standing note
  that 2-3 weeks cannot separate better from luckier.
- **Filters** — min win rate, min profit total, min months green (a COUNT, in
  the unit the GREEN column prints), max worst dip, last N months, clear-all.
  They stack, they run on re-simulated figures, the count line names the active
  ones, zero rows says why in the table body.
- **Last N months RE-RUNS every row** over that slice — profit, trades, wins,
  losses, win rate, months green, both halves, worst dip, worst streak, the
  month columns and the trade log all fall out of that run. Print the window's
  real dates. Remove month columns outside the window, never em-dash them.
- **WORST STREAK $**, not worst trade — the summed worst unbroken run of losses,
  with how many trades it was and the dates it ran. Keep the single worst trade
  only under the label `WORST SINGLE TRADE $`. Compare the streak to the wallet.
- **Row IDs** — `#LLZM9D2K` first column (8 chars), hashed from the combination via
  `backtest_report.row_code`, never a sequence. Find-by-ID box overrides every
  filter and opens that row's log. Lead with the ID when naming a row in chat.
- **Never trim per-row data for SOME rows** — compress the encoding, never the
  coverage. Verify with every filter at its widest, on a row the default hides.
- **Columns the operator does NOT want**: `base $`, `notional $`, `1st half`,
  `2nd half`, `green %`. The data stays; the columns go.
- **Artifact kit** — CLAUDE.md items 1-8 plus kit A-E, embedded candles so rows
  replay in-page, click-a-row opens PAST TRADES and scrolls into view, the
  base-margin box RE-SIMULATES rather than rescaling, verify the replayed log
  sums to the row total before publishing.

## The app's backtest button already covers these timeframes

`backtest_report.TFS` and `BARRIERS` already carry `15m` and `30m` — 110 pairs
each, tighter than the 1h/4h list on purpose. So unlike the 1h/4h case, nothing
needs widening: the button can already reproduce every row this skill publishes.

- **Do not widen the grid locally for an artifact.** Widen the module, or the
  operator cannot find a recommended row inside their own app (CLAUDE.md).
- **Check the recommended rows exist in `BARRIERS` before publishing** — the row
  code makes it a lookup, not a six-field comparison.
- **Deployed barriers are injected on top** via `pairs_for`, because a live
  0.80/2.40 pair is in no grid of round numbers.

## Red flags — the ones specific to short timeframes

| Thought | Reality |
|---|---|
| "92% win rate on a 0.20% target" | Check cost/TP. On anything but BTC that trade cannot win |
| "795 trades, so it is well evidenced" | 795 tiny trades. Profit per trade vs round-trip cost is the test |
| "more bars than the 1h sweep, so better" | More bars of a noisier series. The cost per trade did not shrink with the timeframe |
| "the 15m grid's tight stops are safer" | Tight stops fire more often; each firing pays the full round trip |
| "one timeframe is enough" | They asked for two. Search both equally and say which wins |
| "a year is a year" | Print each coin's real depth. A four-month contract has four months |
