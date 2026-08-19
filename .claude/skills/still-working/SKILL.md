---
name: still-working
description: Pick a strategy by whether it is working NOW, not only across the whole history. Use when the operator asks what to run on a coin, says a recommendation "may lose this month", asks which deployed strategy has gone cold, or asks to re-check a live config. Screens every configuration across nested recent windows (1, 3, 6 months and the full year) and rejects anything that fails one of them.
---

# Still Working

The request this answers, in the operator's words:

> "what strategy do you recommend for apex because the recommended is losing
> this month, it may be winning for past months but it may lose this month"

They are right that a year-long total hides a cold streak. They are also at
risk of the opposite error — crowning whatever ran hot for three weeks. This
skill is the middle: **a configuration must be profitable in EVERY nested
window, from one month out to the whole history.** One good year does not
qualify it. One good month does not either.

## The screen — all seven, or it is not still working

For every combination (coin × timeframe × signal × threshold × SL × TP ×
sizing):

1. profitable over the **full history**
2. profitable over the **last 6 months**
3. profitable over the **last 3 months**
4. profitable over the **last 1 month**
5. **≥ 8 trades in the last 3 months and ≥ 3 in the last month** — a window
   with two trades is a coin flip wearing a result's clothes
6. green in **≥ 60%** of its months
7. worst dip **under half the operator's wallet**, at the base margin shown,
   and the stop reachable before liquidation

Measured on APEX, 2026-08-19: **59 of 4,680** combinations passed. That ratio
is the point — it is a narrow gate, and a wide grid is what makes it meaningful.

## Rank by the WEAKEST window, never the strongest

```
score = min( profit_1mo , profit_3mo / 3 , profit_6mo / 6 , profit_year / months )
```

Every term is dollars **per month**, so they are comparable, and taking the
minimum means a row is judged by its worst stretch. A row that made $200 in
one month and lost in the other eleven scores below a row that made $9 every
month. Sorting by the recent window alone is exactly the mistake the operator
is worried about, in the other direction.

Show the windows side by side — YEAR, 6mo, 3mo, 1mo, and the 1-month trade
count — so the shape is visible, not just the ranking.

## Check the DEPLOYED row against the same screen, first

The question is usually really "is what I am running still working?" Answer
that before recommending anything. On APEX the answer inverted the premise:

| row | year | Jun | Jul | Aug | verdict |
|---|---|---|---|---|---|
| **#05146 deployed** — sweep30 SL 1.00 / TP 4.00, ladder | +$111.52 | +$22.48 | **−$4.80** | **−$22.62** | cold for two months |
| #05302 — sweep30 SL 3.00 / TP 3.00, ladder | +$126.75 | +$23.22 | +$10.04 | +$8.21 | still working |

The operator believed the recommendation was the cold one. It was the live
config. **Measure before agreeing with the premise** — and say plainly which
row is which, with its ID.

## Report

- the deployed row first, with its last three months, and whether it passes
- the top 3 that pass, with all four windows and the 1-month trade count
- the best **flat** row that passes, separately — the ladder amplifies an edge,
  it does not create one
- how many combinations were tested and how many passed
- an artifact, following `CLAUDE.md` items 1-8 and kit A-H, with **LAST N
  MONTHS** set so the operator can re-run the check themselves

## Red flags

| Thought | Reality |
|---|---|
| "It is up this month, ship it" | Check the year. Three weeks cannot separate a better strategy from a luckier one |
| "It made $1,000 over the year" | Check the last month. On APEX the year's winner was −$48.74 in the last 30 days |
| "The recent window says 90% win rate" | Count the trades in it. Under 8 in three months, it is noise |
| "The operator says the recommendation is cold" | Measure it. Last time it was the DEPLOYED row that was cold, not the recommendation |
| "Rank by the 1-month column" | Rank by the weakest window. That is the whole point |
