# Confluence research: the best confluence entry per coin and timeframe (Prompt 1), and open TP/SL (Prompt 2)

The operator, Oct 21, 2026: *"I want you to reasearch confluence for each coins
and each time frame, my goal is 2:1R"*, the two prompts they built and approved
over the evening (Prompt 1, Prompt 2: the full text is in
`research/cq/prompts.md`), and *"then start the prompt, use superpower for
reviewing then if there are any questions instead of waiting for me, use
supwerpower to decide the recommended"*. Every choice below that the prompts
left open was decided that way; each is marked **Ruling** with what it costs if
it is wrong.

## What the data already says

| fact | measured |
|---|---|
| Fees are the whole loss | before fees the average Backtest v2 trade made about $0.00; median round trip 0.228% (Pro Trader spec, Oct 20, 2026) |
| The 49 existing confluence types lose | 3,196,436 stored 2:1 strategies, 15.7% of 43,139,491 trades won, every type lost money (Oct 21, 2026) |
| Per-coin picking found luck | Pro Trader picks on 120 unseen days: -$0.23 a trade vs -$0.22 for random entries |
| Best of many tries looks good by chance | best of 100 no-edge settings at 2:1: ~60% wins on 20 trades, 57% on 30 (simulated) |
| Practice matches the backtest | 35 of 41 practice trades (85.4%) matched, Oct 12-18, 2026 |
| Minutes exist for a year | BTC: 516,440 minutes for 370 days from Gate's archive in 13.3 s (Oct 21, 2026) |
| One engine walk is cheap | BTC, a year, minute exits: 10-23 ms on 1h, 39-57 ms on 15m (this PC) |

## Prompt 1 - the design

### Names and runner parity

* Prefix **`cq_`** (confluence quest), module `tradingagents/signals_cq.py`,
  routed in `auto_trader.signal_for` (last bar) and `_dirs_for_backtest` (every
  bar) exactly like `pt_`. Every indicator is fixed-window
  (`pro_indicators`; the EMA is a fixed 250-bar weighted sum, never a
  recursion), every combination's lookback stays within 250 candles, so the
  runner's 299 closed candles decide what the backtest decides (cut-frame
  test, the `pt_` pattern).
* A name carries its parts and parses back to them by its own grammar:
  `cq_<trigger code>[-<confirmation code>[-<confirmation code>]]`, each code a
  block letter pair plus its setting digits, e.g. `cq_fl00-ev0-vs1`.
  **Ruling:** a dash between parts, never an underscore (the grid appends
  `_gh_<tf>`, and names are never split on "_").

### The 12 building blocks (written down before measuring)

| code | block | role | family | settings (standard first) | expected |
|---|---|---|---|---|---|
| `fl` | bull/bear flag: a pole of at least k x ATR(14) inside 8 candles, then a flag of 3..L candles that pulls back at most half the pole, entered on the close above (below) the flag | trigger | structure | pole k 3 / 2; flag L 10 / 6 | 15m-1h on trending coins: a few points over random |
| `sb` | session break: the first close above the session's high (below its low) after its first hour | trigger | time | session UTC day / London / New York; first break only yes / no | stock tokens at the New York open; crypto weak |
| `ec` | EMA cross: the fast EMA crosses the slow | trigger | trend | pair 9/21 / 20/50 | the random rate intraday; slightly better 4h |
| `pb` | pullback to a level in the trend: price dips to the level and closes back on the trend side | trigger | structure | level session VWAP / EMA 21; depth touch / 0.25 x ATR beyond | wins more often, smaller moves |
| `sq` | squeeze release: Bollinger(20, 2) inside Keltner(20, 1.5) for at least n candles, then a close outside, taken that way | trigger | volatility | n 3 / 6 | 1h-4h: random to +4 points |
| `ev` | EMA 9 above EMA 21 (below for shorts) | confirmation | trend | — | — |
| `vs` | price on the trend side of the session VWAP | confirmation | volume | session UTC day / New York | — |
| `ht` | the bigger picture from the same chart: close above the average of the last N candles | confirmation | trend | N 240 / 120 | — |
| `vo` | the signal candle's volume at least m x the average of the 20 before | confirmation | volume | m 1.5 / 2 | — |
| `rs` | momentum side: RSI(14) above x (below 100-x for shorts) | confirmation | momentum | x 50 / 55 | — |
| `kp` | near a key price: within d x ATR(14) of yesterday's high, low or close, the session open, the session VWAP or a round number | confirmation | structure | d 0.5 / 1.0 | — |
| `tr` | trending, not choppy: Kaufman efficiency of the last 20 candles at least e | confirmation | volatility | e 0.3 / 0.4 | — |

* A combination = 1 trigger + 1 or 2 confirmations, every part from a
  DIFFERENT family. **Ruling:** the session of `sb` and `vs` is a setting;
  stock tokens use New York only (their own market), crypto all three.
* Round numbers: multiples of 10^(floor(log10 price) - 1) (BTC at 108,000 ->
  every 10,000; a 0.2534 coin -> every 0.01).
* The existing 45 `cf_` setups and 4 voting `cx_` rules join the pool as
  ready-made combinations (the prompt: reuse the cf_ conditions); they are
  measured and chosen like any other candidate.
* About 18 trigger settings x ~60 confirmation choices = ~1,100 combinations
  (+49 existing) x 30-45 stop/targets that pay 2:1R or better = ~35,000-50,000
  candidates per coin and timeframe.

### Person-like rules

* **On for every candidate, at their standard values (entry rules, inside the
  signal, so the runner skips the same candles):** no entry from 30 minutes
  before to 30 minutes after a US CPI release, FOMC decision or jobs report
  (`research/cq/us_news.json`, verified dates); no weekend entry (UTC) on a
  candle whose volume is below the average of the 20 before it.
* **Ruling - measured on the picks, not inside the search (second stage):**
  daily discipline (3 trades a coin a day, stop after 2 losses, 3 candles after
  a stop-out), half off at 1R with the stop to break even, a time limit,
  limit-order entries, fills after a jump past the stop, $1-risk sizing, and
  the bigger picture read from the coin's real 4h/1d candles. They change how
  a trade is managed, which the nightly engine cannot do; a rule is KEPT only
  if it improved the pick on its tuning and check days (never decided on the
  test days), then the pick is judged once with the kept rules. Cost if wrong:
  a rule that would have changed which entry was best is only applied to the
  entry chosen without it.

### History, minutes, stretches

| tf | history | tuning | check | test |
|---|---|---|---|---|
| 15m, 30m, 1h | 365 days | 185 | 60 | 120 |
| 4h | 730 days | 370 | 120 | 240 |
| 1d | 1,095 days | 550 | 180 | 365 |

* 300 candles of lead-in; every exit settled by the minute over the whole
  history (`br.fine_bars` from the window's first day; where Gate has no minute,
  the frame's own candle settles it and the trade is counted `unclear`).
* The per-minute order book exists only for the newest ~45 days: older trades
  pay the coin's usual cost (median of its recorded minutes), counted
  `cost_unmeasured` (the Pro Trader rule).
* One engine walk gives all three stretches: the engine counts the trades that
  CLOSED in the last W days (`recent_windows`), asked for W = test and W = test
  + check.

### The search (on GitHub, per coin and timeframe)

* **Payouts.** Each stop/target pair (the grid's own, `br.pairs_for`, stop 2%
  or less) is classed by its payout after the coin's usual round trip:
  2:1 (2-3), 3:1 (3-4), 4:1 (4-5), 5:1 (5 or more); below 2:1 is never a
  candidate.
* **Score:** the worst-case win rate — the Wilson lower bound (z 1.645) of the
  TUNING days' win rate. Within a payout the highest score wins.
* **Rounds:** up to 100 rounds of up to 500 new candidates. Round 1 is a seeded
  random draw of the space. Each later round takes the 25 best so far (by
  score, spread over the payouts) and tries their neighbours (one setting one
  step away, one confirmation swapped, added or dropped, the next stop/target
  of the same payout), plus 20% fresh random draws. Never a candidate twice.
  The seed is a hash of the coin, timeframe and search version, written into
  every output, so a run repeats exactly.
* **Early stop:** after 10 rounds in a row in which no payout's best check-days
  score improved, or when the space is exhausted.
* **The pick, per payout:** among every round's best-by-tuning candidate, the
  one with the best CHECK-days worst-case win rate. **The final pick:** the
  payout whose pick has the best check-days worst-case profit per trade in R.
  Test-day numbers are written beside each candidate and never read by the
  search or the choice (a test holds that shuffling them changes no pick).
* **Kept:** each round's best 10, every payout's pick, the round curve (tuning
  vs check), the candidates tried, under `~/.tradingagents/cq/` on G:.

### The luck bar and the first check

* **Random search:** the same rounds over random-entry candidates (seeded
  streams at 1% / 3% of candles x the same stop/targets), chosen the same way,
  on a fixed sample of 100 coins spread over the coin groups (the pilot: its 20
  coins).
* **Quick random check (second stage):** every pick against 3 seeded random
  streams at its own signal rate, same stop/target, same entry rules.
* **THE FIRST CHECK** (after the pilot's search): the average profit per trade
  BEFORE fees on the test days of the real picks against the random picks.
  Go on only if the real picks are ahead with the low end of the 90% range of
  the difference above zero (Welch). Otherwise stop both prompts and report it.
  **Ruling:** fees "before" = the trade's whole charged round trip added back
  (both fees and both fills).

### The second stage (check run, per pick)

Measured again over the SAME bars with every trade kept (`check_run`
pattern): the pick; its neighbours; the pick without each confirmation and
without each entry rule; the quick random check; the group candidates (each
group x timeframe's 5 best picks by pooled tuning score, measured on every coin
of the group); the trade-management rules above; the real-candle bigger
picture.

* **Group pick:** the group candidate with the best pooled tuning score; a coin
  keeps its own pick only if it beats the group pick on BOTH its tuning and its
  check days.
* **A coin that cannot reach 20 test-day wins** (mostly 1d, and 4h at 4:1-5:1)
  is judged only through its group pick's pooled test trades; it never passes
  alone.
* **Passes** (test days, all of them): pays its payout on the fees its trades
  paid; makes money with 20+ wins; at least one trade a week; above zero at the
  low end of the 90% range per trade; beats its quick random check; survives
  costs x 1.5 and stops 0.1% worse; neighbours make money on average; every
  confirmation and kept rule helps.
* **When it works:** test-day results by BTC mood (up, down, sideways by the
  sign and size of BTC's 7-day move) and calm (BTC's 7-day volatility above or
  below its median), long vs short, next to holding the coin.
* **Room as one:** the passing picks together, at most 5 open at once and a
  daily loss stop of 3R, on the test days.

### Machines, time, progress

* `research.yml`-style workflow `cq.yml`, dealt over every account
  (`cloud_sweep.fleets()`: 3 accounts, 60 machines since Oct 21, 2026) with the
  claim board, each job under 5.8 hours, waves until the board is empty.
  Never dispatched between 12:45am and 5:00am (the nightly jobs). Prompt 1 and
  Prompt 2 take turns.
* **Budget:** 48 hours. 60 machines x 48 h at ~30 ms a walk is ~170 million
  walks after overheads; the full search needs ~5,000 coin-timeframes x up to
  50,000 walks, so early stopping must cut it about in half. If the pilot says
  it will not fit, the round size drops (500 -> 300 -> 200) and the page says so.
* **Progress file:** `~/.tradingagents/cq/progress.json` (stage, runs per
  account, waves, coins done, picks, first-check verdict); "resume Prompt 1"
  reads it.
* **Notifications** (the session, PushNotification): the first check's
  verdict, the end of each prompt, any stop.

## Prompt 2 - the design (Step 1 only: the backtest)

* One function, `exit_levels(rule, settings, candles at entry, side, entry
  price, cost) -> (target, stop) or None` ("no 2:1 room"), used by the research
  walk only; the trading program, ids, list and rooms are not touched.
* Rules (at most 8): swing size (k x ATR 1 / 1.5 / 2), invalidation (flag low,
  swing low, session low, VWAP), room to run (next level at least 2R away),
  strength (3R when every confirmation agrees and volume is well above normal),
  time limit, half off at 1R with break even; every target at least 2R after
  the expected cost, stop between 2 x the round trip and 2%.
* Entries: every coin and timeframe's Prompt 1 pick, the 49 `cf_`/`cx_` setups
  and the 64 `pt_` settings (~114) x ~32 exit choices = ~3,600 candidates,
  tested in full on the tuning days (no rounds), picked on the check days,
  judged once on the test days against the best FIXED stop/target for the same
  entry and against random entries.
* **THE FIRST CHECK:** only entries that beat random before fees on their test
  days go on; with none, Prompt 2 stops and says so.
* Results in R, in dollars at the flat $5, and at $1 of risk a trade.

## Order of work

1. Prompt 1 building blocks, routing, the search shard, the dispatcher and the
   collector; the pilot (20 coins: BTC, ETH, SOL + 17 across the groups,
   including 3 stock tokens); the first check.
2. If the first check passes: the second stage, Prompt 2's exit walk, the full
   market, the pages. If it fails: the report, and both prompts stop.

Nothing is switched on, filed into Stored strategies or added to the nightly
grid. Guards: the tests named in the implementation plan.
