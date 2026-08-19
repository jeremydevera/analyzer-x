---
name: full-grid-search
description: Use whenever the operator asks for a strategy, a backtest, "best strategy", "find me something profitable", or any strategy comparison. Mandates a FULL grid — every coin, every timeframe, every signal, several TP/SL pairs, and BOTH sizing rules — because a partial search silently decides the answer.
---

# Full Grid Search

The operator's standing instruction:

> "When I ask you to create a strategy, always create a strategy for all coins, and
> different combinations for each coin per timeframe (15m, 30m, 1hr, 4hr, 1day) and
> different combinations of tp/sl."

Every dimension below **varies**. Nothing is assumed, nothing is inherited from the last
run, nothing is skipped because it "probably won't work."

## The unit of work: one combination

Each row of a result is one combination, and it names every dimension:

```
combination 1                    combination 3
  coin      BTC_USDT               coin      BTC_USDT
  timeframe 1h                     timeframe 1h
  signal    ICT fair value gap     signal    ICT fair value gap
  TP        3.5%                   TP        3.5%
  SL        1.0%                   SL        1.0%
  sizing    martingale             sizing    FLAT
```

Two rows that differ in exactly one field are the point of the exercise. If you cannot
say which single field separates two rows, the grid was not built properly.

## The dimensions — all five vary, always

| Dimension | Values |
|---|---|
| **Coin** | every tradeable contract on the venue (~940), minus those the liquidity gate blocks for that TP |
| **Timeframe** | **15m · 30m · 1h · 4h · 1d** — all five, every time |
| **Signal** | every rule in the library: mom6, mom15, fade15, trend50, RSI14, sweep30, Fibonacci, ICT FVG |
| **TP / SL** | **at least 3 pairs per timeframe**, scaled to the bar, spanning tight→wide and 2:1→4:1 |
| **Sizing** | **martingale AND flat** — both, for every combination |

Missing any one of these has produced a wrong answer before. See the receipts.

### Barriers scale with the bar

A 0.9% target is generous at 1-day and impossible at 15m once fees are paid. Suggested
starting grids — widen if the survivors cluster at an edge, which means the grid was cut
too small:

| Timeframe | SL / TP pairs |
|---|---|
| 15m | 0.20/0.60 · 0.30/0.90 · 0.40/1.60 |
| 30m | 0.30/0.90 · 0.40/1.20 · 0.50/2.00 |
| 1h | 0.60/1.80 · 0.80/2.40 · 1.00/4.00 |
| 4h | 1.20/3.60 · 1.50/4.50 · 2.00/8.00 |
| 1d | 2.50/10.0 · 3.00/9.00 · 4.00/12.0 |

Momentum/fade thresholds scale too — 0.3% is a large move in a minute and noise in a day.

### Sizing is a dimension, not a setting

Run every combination **twice**: flat stake, and the DEEP martingale ladder
(1,1,2,2,4,4,8). Report them as separate rows.

This is not optional. An independent audit found that the "13 of 13 green months" that
justified six live strategies was **produced by the ladder, not the signal** — flat-staked,
the same configs were 7/12 to 11/12. Flat is how you measure whether the signal works.
Martingale is a sizing choice made afterward, with its own risk.

## Receipts — what a partial grid cost

| What was skipped | What it caused |
|---|---|
| 4-hour left out of the first 941-coin sweep | The recommended top-10 was picked from the *weaker* half of the search space; 4h later showed 31.2% profitable vs 12.1% at 1h |
| 1h given ONE barrier set while 4h got two | "4h beats 1h" may partly be search effort, not edge — the comparison was unfair |
| 30-minute never tested at all | An entire timeframe unexamined, with no reason given |
| 1-day never tested | Missed **5.5 years** of history — every recommendation rested on ONE year of falling alt-coins |
| Flat sizing never tested | The headline validation statistic turned out to be a sizing artifact |
| One slippage figure across 941 order books | BDX showed +$1,560; its real spread made it unwinnable, and it cost real money |

## Execution — how to actually run it

The full grid is large (~940 coins × 5 timeframes × every signal in `backtest_report.SIGNALS` — 75 as of 2026-08-19, read the list, never hardcode it — × 3 barriers × 2 sizings).
Make it finite honestly, never by quietly dropping a dimension:

1. **Pre-filter coins by the liquidity gate, per timeframe.** A contract whose round-trip
   cost exceeds ~20% of the target cannot win at that timeframe; exclude it there and
   **state how many were excluded and why**.
2. **Throttle and checkpoint.** MEXC answers a hammered client with *truncated history*,
   which silently produces wrong numbers. ~7 requests/sec, retries, and validate the bar
   count before using a fetch. Write partial results every N coins.
3. **Fetch each coin's candles once per timeframe** and reuse them across all signals,
   barriers and sizings. The fetch is the cost; the arithmetic is free.
4. **Never truncate silently.** If you cap the grid, `log()` exactly what was dropped.

## Then the gauntlet — a grid is not an answer

Winning the grid means nothing on its own; the max of a million draws is mostly luck.
Every survivor must clear:

- **measured cost** — that coin's real taker fee and its order-book slippage, not an average
- **split-half holdout** — profitable in the first half of its history *and* the second
- **stability** — the result reproduces on freshly fetched candles
- **enough evidence** — trade count and months of history stated, never implied

## Reporting

Follow `CLAUDE.md` exactly: PROFIT/TOTAL $, TP, SL, leverage, margin/notional, WINS and
LOSSES, trades, and the total combination count above the table — plus, for this skill,
**sizing** and **timeframe** as visible columns, and a **verdict** column naming the
filter that killed each non-survivor.

Ship it as an artifact with clickable per-row trade logs. State the grid dimensions at the
top: *"N coins × 5 timeframes × N signals (from `backtest_report.SIGNALS`) × 3 barriers × 2 sizings = X combinations."*

## Red flags

| Thought | Reality |
|---|---|
| "15m/1m never works, skip it" | Then the table says so with numbers, and the operator sees why |
| "One barrier set is enough" | It decides the winner. Three minimum, per timeframe |
| "Martingale is how we trade, so test that" | Flat is how you MEASURE. Test both |
| "The 4h grid was fine, reuse its conclusion" | Every timeframe gets its own equal search |
| "Too many combinations" | Pre-filter by liquidity and say how many were dropped — never trim a dimension in silence |
