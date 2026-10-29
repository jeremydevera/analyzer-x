# Backtest v3 — research-backed ideas, proven against random, then practice

**Date:** Oct 22, 2026 · **Status:** approved Oct 22, 2026 ("ok go ahead"); Part 1, the engine, is built (plan docs/superpowers/plans/2026-10-22-backtest-v3-part1-engine.md); Part 2a, the families and the proof test on this PC, is built (plan docs/superpowers/plans/2026-10-23-backtest-v3-part2a-families-and-proof.md); Part 2b, the GitHub run, the verdict store, the tab's list, the results page and COVERAGE FIRST, is built (plan docs/superpowers/plans/2026-10-27-backtest-v3-part2b-github.md)

## The operator's words

- *"i want to do backtest v3 where you will create the strategy for the research
  you made can you create a plan"* (Oct 22, 2026)
- On what v3 should give: *"proven ideas then i want it in a new tab"*
- On which ideas: *"i want all but can you give me more research ideas and can
  you learn from my existing millions of stored strategies"* — slow trend on big
  coins, busy hours only, funding filter, snap-back on calm coins
- On practice: **"Yes, practice uses waiting orders"**
- On money per trade: **"Same risk, lower leverage"**
- On the approach: *"i want 1st and 2nd option idea families and retest my
  millions of rows"*
- Parts 1-5 of the design: approved one by one, Oct 22, 2026.

## Why v3 exists

The research of Oct 22, 2026 (`docs/research/2026-10-22-why-the-system-does-not-profit.md`,
report https://claude.ai/artifact/Nbhge7m3MjVkF4R4qQTut3) measured that the
system has no edge before fees: on 120 days they were never picked from, the
best of 2,255 picks lost $0.23 a trade and random entries lost $0.22 (Pro
Trader, Oct 20, 2026). Every cent of the loss is cost (median round trip
0.228%). Books, studies and practitioners agree on what to change: pay less per
trade (waiting orders), match the exit to the idea, test a few reasoned ideas
as whole families against random entries with a luck correction, size by risk,
and prove it in practice before money.

v3 is that, end to end. **v1 and v2 are not changed**: v3 has its own engine
switches, its own store and its own tab, as v2 did beside v1.

## What "success" means

A v3 idea is **proven** only when all of these hold:

1. On the months it never saw, after every cost, it makes money.
2. It beats random entries — same coins, same hours, same exit rule, same
   costs, same number of trades — by more than luck explains, after a
   correction for every idea and setting tried.
3. It has enough trades on those months to mean something (at least 300,
   pooled across coins).
4. In its own frozen practice room, over at least 4 weeks and 100 trades,
   practice matches what v3 predicted for the same days.

An idea that fails any step is listed as failed, with its numbers and the
step it failed. **It is never hidden.**

## Part 1 — the pipeline

```
A) idea families (rules fixed BEFORE testing)    B) stored v2 strategies
              \                                   /
               ->  THE V3 ENGINE on GitHub (60 machines, up to a year)
                   waiting-order entries · the idea's own exit · $1 risk
                         |
               THE PROOF TEST: pick a setting on older months,
               judge on the newest months it never saw, against random
                         |
            failed -> listed "failed", with why     passed -> FROZEN PRACTICE ROOM
                                                              (waiting orders, weeks)
                                                                     |
                                                   NEW "BACKTEST V3" TAB: proven on top
```

Everything heavy runs on GitHub across **all three accounts** (60 machines —
CLAUDE.md "Every GitHub job uses ALL 40 machines", now 60), dealt by
`cloud_sweep.split_coins` over `usable_fleets()`, results collected into the
v3 store.

## Part 2 — the ideas

Each idea is a FAMILY: a rule with a handful of settings fixed here, before any
test. The proof test chooses one setting on the older months; every setting
tried counts toward the luck correction. Universe words:

* **Liquid crypto** = Gate USDT perps of `venue.kind() == "crypto"` in the top
  50 by 30-day traded value at the start of each month (re-ranked monthly, so
  no coin is chosen with hindsight).
* **Calm contracts** = metals, indices and FX perps (`venue.kind()`), plus
  liquid crypto in the calmest third by 60-day realized volatility.
* **Stock tokens** = `venue.kind() == "stocks"`.

Entry ideas (all enter with a waiting order — Part 3):

| # | Family | Rule | Settings (fixed) | Exit | Universe |
|---|---|---|---|---|---|
| 1 | `v3_trend` slow trend | Long when the close is above its n-day moving average AND that average is above its value 5 days ago | n ∈ {20, 50, 100}; 1d and 4h candles | Trailing stop 3 × ATR(20), no target; also out when the close falls below the average | Liquid crypto (longs only — shorting trends lost in Han, Kang & Ryu 2023) and calm contracts (both sides) |
| 2 | `v3_breakout` | Close above the highest high of the last N days, only while the 100-day average is rising | N ∈ {20, 50}; 1d | Trailing stop 3 × ATR(20), no target | Same as #1 |
| 3 | `v3_strength` two-week leaders | Each Monday 00:00 UTC rank liquid crypto by 14-day return; long the top K | K ∈ {3, 5}; 1d | Out when it leaves the top 2K at a weekly rank, or trailing stop 3 × ATR(20) | Liquid crypto |
| 4 | `v3_snap` snap-back | Close at least k × ATR(20) away from its 20-bar average (below → long, above → short) | k ∈ {1.5, 2.0}; 1h and 4h | Target = the 20-bar average, resting as a waiting order; emergency stop 3 × ATR(20); time exit after 24 bars | Calm contracts |

Filters (each tested ON TOP of entry ideas 1-4, judged the same way):

| # | Filter | Rule | Data |
|---|---|---|---|
| 5 | `btc_mood` | Alt-coin longs only while BTC's daily close is above its 50-day average | BTC_USDT daily candles |
| 6 | `busy_hours` | Stock tokens: entries only 9:30am-4:00pm New York, weekdays (the existing `daytime_rule` hours). Crypto: a "no weekend entries" variant | the clock |
| 7 | `funding_side` | Skip longs when funding is in the coin's top 10% of its past 30 days; skip shorts in its bottom 10% | `fx.funding_history` |
| 8 | `crash_guard` | Skip entries while 24h open-interest change is in its top 10% AND funding in its top 25% AND 7-day realized volatility is rising | Gate contract stats; tested on the span Gate serves, and said so |
| 9 | `funding_minutes` | No entry within 5 minutes either side of a funding settlement | funding cycle per contract |
| 10 | `when_map` learned from the stored rows | Allow an entry only in the cells (coin kind × volatility third × hour block × BTC mood × funding third) whose pooled re-tested trades beat random on the OLDER months (Part 4) | the Part 4 re-test |

**Cross-coin data.** #3 and #5 read other coins' candles. The runner reads one
coin at a time today, so v3 adds one shared, machine-wide file the runner and
the engine both read (BTC's mood, the weekly ranking), written once a day
(`shared_market` pattern, never one room's folder).

## Part 3 — the v3 engine and the proof test

### A trade

* **Entry = a waiting (limit) order** at the signal candle's close, placed the
  minute that candle closes, side as the signal says.
  - It is FILLED only when price trades **through** it (a buy fills when a
    minute's low is strictly below the limit; a sell when a high is strictly
    above). Touching the price is not a fill — the queue is not modelled, so
    the engine assumes the worst place in it.
  - Fill window: until the next candle of the strategy's timeframe closes. An
    order not filled by then is a **missed trade**: recorded with the signal,
    the limit price and what a market entry would have made, so the cost of
    waiting is a number on the page (`missed`, `missed_pnl`).
  - The fill price is the limit price (no gap paid on entry).
  - Ruling, Oct 23, 2026 (final review of Part 1): the waiting order is post-only — an order marketable when placed (fresh book) is rejected and recorded as a missed trade with its market twin, so the maker fee is true by construction.
* **Exits, by idea:**
  - Trend ideas (#1-#3): a trailing stop 3 × ATR(20) of the strategy's
    timeframe, updated each closed minute, never loosened; closed at the market
    when crossed.
  - Snap-back (#4): the target rests as a waiting order (fills only when price
    trades through it); a 3 × ATR emergency stop and a 24-bar time exit close
    at the market.
  - Every exit is settled minute by minute through ONE rule shared with the
    backtest and the replay (`auto_trader.settle_in_minutes` for fixed levels;
    a trailing level is a new shared helper of the same shape, used by the
    engine and the runner). A candle with no minutes under it keeps the candle
    rule and is counted.
* **Costs — every trade pays all of them, wins and losses** (CLAUDE.md "Every
  backtest LOOKS AT THE COSTS"):
  - waiting-order fills: Gate's base-tier maker fee **+0.02%** (the fee guide's
    VIP0), never the −0.01% rebate the contract listing shows, until the
    account's own rate is read with a Gate key (`fee_floor()` grows a maker
    sibling);
  - market exits: the **0.075%** taker fee plus the exit minute's own order-book
    gap (`cost_store` / `book_history`);
  - funding over the hold, settlement by settlement. Gate serves about 180
    days of funding: older holds pay the coin's average known rate and are
    counted `funding_estimated`.
  - The runner's cost check (`entry_refusal` / `cost_verdict`) is asked at
    every entry minute — told the entry is a waiting order (maker fee, no entry
    gap) through ONE function the engine and the runner share.
* **COVERAGE FIRST.** Before any v3 run, the per-minute costs must cover its
  whole window: the cost store is filled for the v3 universe first (the
  existing order-book backfill, `costs.yml`), and every result prints its share
  of typical-cost trades (`cost_unmeasured`) beside its numbers.
* **Money — the same risk on every trade.** A trade risks **$1** if its stop is
  hit (the risk box on the page rescales every dollar). Size = $1 ÷ stop
  distance (a 5% stop → $20 of coin; a 1% stop → $100). Leverage is chosen per
  trade so the stop sits inside 80% of the liquidation distance
  (`STOP_LIQ_CEILING`), using the contract's own `maintenance_rate`; size is
  rounded to the contract's lot, and a trade smaller than one lot is skipped
  and counted (`too_small`).
* **Data:** each coin's own candles and minutes, up to the newest 365 days
  (younger coins: what exists, said on the row). Minutes come from
  `backtest_report.fine_bars` (Gate's monthly archive, 5-minute bars over the
  current month's gap, REST's last week).

### The proof test

* **Split:** the newest 90 days are **unseen**; the days before them are the
  **older months**. Nothing on the unseen days is read until the setting is
  chosen.
* **Setting choice:** on the older months only, the family's setting with the
  best profit per trade after costs; ties to the simplest.
* **Random entries:** for every family, coin and timeframe, 200 seeded runs of
  random entries with the same number of entries per month, the same side mix,
  the same exit rule, sizing and costs (`rand` in the Pro Trader design, kept as
  the luck bar).
* **Pass:** on the unseen days, pooled over the family's coins:
  1. profit per trade after costs > 0;
  2. profit per trade above the random runs' 1 − α/2 quantile, where α = 0.05 ÷
     (every family × setting × filter combination tried — counted, never
     estimated), and a day-clustered bootstrap that does not cross zero;
  3. at least 300 unseen trades.
* **Every verdict is kept** with its numbers: trades, wins, losses, win rate,
  break-even win rate, profit, profit per trade against random's, missed
  trades, `cost_unmeasured`, `funding_estimated`, and the setting chosen.

## Part 4 — re-testing the stored rows, and learning from them

* **Which rows:** every listed Backtest v2 strategy (about 12.4 million on
  Oct 22, 2026; `index_keeps`: TP > SL and 2:1 after fees). Each keeps its own
  coin, timeframe, signal, target and stop.
* **What changes:** the v3 engine — waiting-order entry, the target resting as
  a waiting order, the stop at the market, $1 risk, up to a year, minute by
  minute, all costs. Each row gets its own v3 numbers in the v3 store, and the
  same row's numbers with a MARKET entry and target (everything else equal),
  so the page shows what cheaper orders alone change.
* **The verdict is per signal, never per row.** All of a signal's re-tested
  rows, pooled over every coin, against random entries with the same targets
  and stops, on the unseen days, by the Part 3 pass rule. A row is marked by
  its signal's verdict; a single row is never "proven" on its own numbers.
* **The "when to trade" map (#10):** every re-tested trade on the OLDER months,
  pooled, its win rate minus random's for the same target and stop, by cell:
  coin kind × volatility third × hour block (4 hours) × BTC mood × funding
  third. Cells with at least 500 trades whose lift beats random by the Part 3
  rule become the map; the map is then a filter judged on the unseen days like
  any other.
* **Left out of the first version:** a trained take-or-skip model
  (meta-labeling). The Sep 27 ML per-coin models already failed unseen
  (−$229.49 over 15,566 trades); it is added only if the map shows real lift.
* **Time:** a 20-coin pilot first, measured; the full run's time estimate is
  shown before it starts.

## Part 5 — practice, the tab, the store

### Practice with waiting orders (practice account only)

* Each family that passes the proof test gets **its own frozen practice room**
  (CLAUDE.md STANDING SETUP: a rule set is a room named by its id), the chosen
  setting and filters written into it, **Smart Watcher OFF** — no switching by
  recent win rate.
* The runner, for v3 rooms only: places the waiting order at the signal
  candle's close; it fills only when the live price trades through it within
  the fill window (the engine's own fill rule, one function); an unfilled order
  writes a `missed` row; the target rests as a waiting order; stops and
  trailing stops close at the market; size from the $1 risk; leverage per
  trade as the engine sets it.
* **Real money stays off for v3 rooms** (the live box is refused there); real
  limit orders are a later decision.
* After 4 weeks and at least 100 trades, practice is compared with the v3
  engine's trades over the same days (the reality check: took / gap, as
  Forecast v2 measures it). A match makes the family **proven**.

### The "Backtest v3" tab (menu, beside Backtest)

1. **Proven** — families that passed the backtest and practice.
2. **In practice** — passed the backtest; practice running, with its progress.
3. **Every idea's verdict** — passed and failed, numbers against random.
4. **Re-tested signals** — each signal's verdict, market against waiting
   orders.
5. **Re-tested rows** — searchable, filtered and paged on the server, each row
   marked by its signal's verdict, click → its trade log.
6. **The "when to trade" map.**

Every results table follows CLAUDE.md's standard kit (ID first, profit, TP
rule, SL rule, leverage, wins/losses, worst losing run, trades and per day,
combinations tested above it, filters including max TP % and max SL %, last N
days that re-measures, find by ID, sortable, the trade log with a TOTAL
PROFIT). The kit's "base margin $" box is a **risk per trade $** box in v3:
every dollar rescales with it.

### The store and the ids

* `stores.V3` → `~/.tradingagents/v3` (its own rows, index, candles view),
  served at `/api/v3/...` through the same `using_db` switch v2 uses.
* A v3 row's id carries `res="v3"` in `backtest_report.row_code`, so it can
  never equal a v1 or v2 id; a family room's id is its rule set's own hash.
* v1 and v2 files are never written by v3.

## Build order (each phase finished, tested and pushed before the next)

0. **Costs coverage** for the v3 universe over the v3 window (the existing
   order-book backfill), with `cost_unmeasured` printed.
1. **The v3 engine:** waiting-order fills, missed trades, trailing and
   emergency exits, $1 risk sizing with safe leverage, maker/taker costs, the
   shared fill and trailing helpers — with parity tests against hand-worked
   trades on one timeline.
2. **Families 1-4 + filters 5-9 + random entries** on GitHub: 20-coin pilot,
   then the universe; the proof test; verdicts in the v3 store.
3. **Re-test of the stored rows** (pilot, then all), per-signal verdicts, the
   market-vs-waiting comparison, the "when to trade" map (#10) and its verdict.
4. **The Backtest v3 tab.**
5. **Practice with waiting orders** in the runner, and the frozen v3 rooms;
   "proven" after 4 weeks and 100 trades.

## Tests (each phase)

* Fill rule: a touch is not a fill; a trade-through is; the fill window ends
  at the next candle's close; a missed order is recorded with its market
  counterfactual.
* Trailing stop: updated per closed minute, never loosened, settled by the
  shared helper; engine and runner agree on one timeline.
* Sizing: $1 risk at every stop distance; the stop always inside 80% of
  liquidation; sub-lot trades skipped and counted.
* Costs: maker fee on waiting fills, taker plus the exit minute's gap on market
  exits, funding per settlement, `funding_estimated` before Gate's history.
* Proof test: seeded random runs reproduce; the luck correction counts every
  combination tried; a family that only beats random on the older months
  fails.
* Per-signal verdicts pool every row of a signal; no row is proven alone.
* The tab: the standard-kit tests, empty states that name what was examined,
  the risk box rescales every dollar.
* Practice: a v3 room never trades real money and never switches by win rate.

## Out of scope

Real-money limit orders; market making; funding carry (it needs a spot
position beside the future); cross-exchange arbitrage; a trained take-or-skip
model (unless the map shows lift); any change to v1 or v2.

## Open points, said out loud

* Your Gate account's real maker and taker fees are unknown until a Gate key is
  connected: v3 assumes +0.02% maker and 0.075% taker (the worse of Gate's
  published numbers).
* Gate serves about 180 days of funding and a limited span of open interest;
  older trades are counted `funding_estimated`, and the crash guard is judged
  on the span it has.
* Filling a year of per-minute costs for the universe takes machine time
  (2 years of every coin ≈ 3-4 days of all 60 machines); the pilot measures
  the v3 share first.
* The full re-test of about 12.4 million rows over a year is the largest job
  this project has run; its time is measured on the pilot before it starts.
