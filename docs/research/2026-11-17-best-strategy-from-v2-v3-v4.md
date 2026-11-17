# The most profitable strategy the v2, v3 and v4 data supports (Nov 17, 2026)

The operator, Nov 17, 2026 (`/goal`): *"you already have data for backtest v2,v3,v4 can you come up with the
most profitable strategy? use my existing skill for crypto to study and look for mathemetically high profit
outcome"*. Methods are the three crypto skills': walk-forward and "pick on old days, judge on new" and the five
lies of a backtest (backtesting-frameworks), the strategy families and metrics (backtesting-trading-strategies,
technical-analysis), expectancy and Kelly (risk-management). Every number is from this repo's own stores at
Gate's costs. Scripts: `docs/research/best-strategy-scripts/` (set `SCRATCH` to a folder for the intermediate
files). Read `2026-10-22-why-the-system-does-not-profit.md` first: this note agrees with it and narrows it.

## The answer in one paragraph

Strategies do not make money in general: the average Backtest v4 trade lost 65 cents (older days) and 91 cents
(newest 30 days) per $100. The only place the data shows a repeatable edge is **trend following with a
trailing stop, on the crypto contracts that are cheapest to trade** (a usual buy-sell gap of 5 basis points a
side or less; 107-159 coins a year). It makes about **+$0.17 to +$0.24 a trade at $5 risked** (3-5% of the
risk), wins 31-34% of its trades, and was green in 15-17 of 25 months. It is small, and its 90% range still
touches zero (-$0.02 to +$0.43), so it is a strategy worth practising, not a proven one.

## What was measured

1. **v4 (234,415 strategies, 7.4M trades; store Nov 16, 2026 8:42pm, TWUMC and WUXIBIO left out for the
   pricing bug of RCA-2026-11-17-A).** Pooled over all coins by strategy group (446 groups x 3 cost levels),
   judged by the day each trade opened, standard errors clustered by day (a market day moves every coin
   together). Of 534 group-and-cost-level cells with 300+ trades on each side of Oct 17, 2026, 76 made money on the older days,
   24 on the newer, **2 on both**. The best 15 chosen on the older days all lost on the newer ones. Every cost
   level lost: round trip $0.25 or less -$0.03 older / -$0.26 newer; $0.25-0.50 -$0.29 / -$0.41; over $0.50
   -$1.54 / -$1.88. The older 'ta_ma_pullback 4h 6%/3%' lost (-$0.46, t -5.2) and then won (+$0.54): a
   regime, not an edge. Of 39,407 strategies with 20+ trades in each half, 1,228 made money in both where
   chance gives about 586; the best single score (2.4) is far from the 4.7 a pick out of 39,407 needs.
2. **v2.** Not measured again: the Oct 20, 2026 walk-forward over 3.8M v2 rows (about $0.00 a trade before
   fees, $0.23 of fees, nothing picked on past results held) and the Oct 22 research already cover it, and v4
   above says the same on newer data.
3. **v3 (1,064 coins in 2026's run, 390 in 2025's; 63 idea combinations, settings fixed before any test; 4
   windows: 2025 older, 2025 unseen, 2026 older, 2026 unseen = 24 months; $5 risked a trade, post-only entry,
   every fee).** Pooled over every coin the combinations are near zero (one combination is positive in all
   four windows, +$0.1 a trade, score 0.3-2.0). **Split by what each coin costs to trade, trend following lines
   up monotonically** ($ a trade, both years, 'none' filter, crypto): gap 0-0.03% +0.143 (36,303 trades),
   0.03-0.05% +0.049, 0.05-0.08% -0.023, 0.08-0.12% -0.038, 0.12-0.20% -0.037, 0.20-0.40% -0.237 (t -2.1),
   over 0.40% -0.821 (t -8.6). Fees and gaps are the whole loss; where they are tiny the trend family keeps a
   small profit.
4. **Held forward:** chosen on 2025's whole year inside the cheap coins, judged on 2026's: of the 29 combinations
   positive in 2025, 20 were positive in 2026 (69%); of 26 negative in 2025, 1 was (4%). The top 3 on 2025 made
   +$0.113 a trade in 2026 against -$0.059 for all 55. Against 200 random-entry runs with the same trail exit on
   the same coins, the 4h trend beat 98-100% of them on both years' unseen days (n20 4h btc_mood: +$539 and
   +$1,229 real, random means +$202 and +$366). Random entries on cheap coins with this exit are positive too
   (+$355 in 90 days): part of the profit is the post-only entry plus trailing exit, not the signal.
5. **Live forward since Nov 5, 2026 11:07am** (`v3_forward`, 148 strategies, no order placed): at Nov 17, 2026
   12:10pm cheap coins +$172.51 (57 closed, +$58.10; 37 open, +$114.41), mid-cost coins +$120.64, all +$293.15.
   Shorts +$422.58, longs -$129.43: the stretch was a down move. 12 days: weak evidence.

## The strategy

`v3_trend` (Backtest v3's own): long when the close is above its n-day average and that average is above its value
5 days ago, short on the mirror; n = 20 days on 4h (120 candles) or 50 on 1d; optionally only when BTC's mood
agrees (`btc_mood`); a **post-only waiting entry**; exit on a **3 x ATR(20) trailing stop that is never loosened**
or a close past the n-day average; $5 risked a trade; only coins whose usual one-side gap is 5 bp or less.

| combination (cheap crypto, 25 months) | trades | $ a trade | win | months green | max dip (pooled) | 90% range |
|---|---|---|---|---|---|---|
| trend n20 4h btc_mood | 20,756 | +0.203 | 31% | 17 of 25 | -$2,297 | -0.019 to +0.429 |
| trend n20 4h none | 22,628 | +0.172 | 31% | 15 of 25 | -$2,101 | -0.026 to +0.380 |
| trend n50 1d btc_mood | 4,821 | +0.239 | 34% | 15 of 25 | -$1,008 | -0.012 to +0.511 |
| trend n20 1d btc_mood | 6,816 | +0.202 | 33% | 16 of 25 | -$720 | -0.007 to +0.402 |

Average win +$5.0, average loss -$2.0 (payoff 2.5; break-even win rate about 29%, so 31-34% wins is thin).
The pooled 2-year profit of n20 4h btc_mood is +$4,211 over about 265 coin-years (about +$16 a coin a year), with a
worst month of -$924 and a best of +$1,955. Longs +$0.17 and shorts +$0.22 a trade: not only bull-market beta.

## Limits, so nobody over-reads it

* Scores of 1.4-2.3 (day-clustered); no combination passes a luck correction over the 63 (z 3.2). 90% ranges
  touch zero. The 12 live days lean on one direction (shorts).
* The 5 bp line was chosen after seeing three buckets; the gradient itself (7 steps) is monotone.
* Only contracts the exchange lists today (survivorship), one regime sample (Nov 2024 - Nov 2026), costs
  from the coin's usual gap on days before the order books exist.
* **The practice runner cannot trade it**: no post-only entry, no trailing stop, no risk-based size. A v3
  practice room (the spec's later part) is the way to test it with real fills. Nothing was switched on.
* The v4 skill strategies (fixed stop and target on the close) show nothing; a leader there is luck.
