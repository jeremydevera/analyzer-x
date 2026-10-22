# Confluence research prompts

Updated Oct 21, 2026: the 9 open points, the 8 trade-like-a-person rules, the before-fees first check, run-to-the-end, progress notifications, resume after a power cut, and market moods applied. Prompt 1: the best confluence entry. Prompt 2: open
TP/SL, the computer sets each trade's stop and target.

## Prompt 1 - the best confluence entry, 2:1R or better, per coin and timeframe

```text
PROMPT 1 - THE BEST CONFLUENCE ENTRY, PER COIN AND TIMEFRAME

ROLE
Act as a professional systematic trader for my app (analyzer-x). It trades Gate
USDT perpetual futures, $5 margin x 20x = $100 per trade, flat, practice account
only. For EACH coin and EACH timeframe (15m, 30m, 1h, 4h, 1d), find the
CONFLUENCE entry with the HIGHEST WIN RATE POSSIBLE at 2:1R or better after
fees, which still holds on days it was never built or chosen on.

WHAT 2:1R MEANS (use exactly this)
- R = what one losing trade costs: the stop distance PLUS the fees and spread
  that trade really paid.
- 2:1R = a win pays at least 2R after its own fees, so 1 win pays back 2 losses:
  (TP - cost) >= 2 x (SL + cost), where cost = the trade's real round trip
  (rt_paid). backtest_report.pays_two_to_one already checks this.
- So the target must be at least 2 x stop + 3 x cost. With the usual 0.228%
  round trip: stop 0.5% -> target 1.68% or more; stop 1% -> 2.68% or more.
- 3:1, 4:1 and 5:1 also qualify. Break-even win rate: 33.3% at 2:1, 25% at 3:1,
  20% at 4:1, 16.7% at 5:1. Profit per trade at k:1 = win rate x (k + 1) - 1, in
  R: a 2:1 winning 40% makes +0.20R a trade, a 4:1 winning 25% makes +0.25R.

HOW TO RANK (use exactly this)
- Within each payout (2:1, 3:1, 4:1, 5:1): the highest WORST-CASE win rate, the
  low end of the 90% range for its number of trades, never the raw win rate. So
  13 wins of 20 (65%) ranks below 45 wins of 100 (45%).
- Between payouts, for a coin and timeframe's final pick: the highest
  worst-case profit per trade in R.
- Show the best 2:1, 3:1, 4:1 and 5:1 side by side for every coin and timeframe.

WHAT CONFLUENCE MEANS (use exactly this)
- Each condition comes from a DIFFERENT family of information: trend, momentum,
  volume, volatility, price structure, time of day. RSI + Stochastic is one
  family twice, so it is not confluence.
- A confluence = 1 trigger (what opens the trade on a closed candle) + 1-2
  confirmations (what must already be true).
- Everything reads only the coin's own candles of its own timeframe, because
  that is all the trading program sees: no BTC filter, no funding, no other
  coin. A bigger timeframe's trend IS allowed when built from those same
  candles (for example a 4h trend from the last 240 1h candles).
- Include my own idea: bull and bear flags, confirmed by the 9 EMA vs the
  21 EMA, which side of VWAP price is on, and the session high/low.
  - Lock the flag's shape at standard values (how big the pole is, how long the
    flag lasts, how far it may pull back). Only 2 of its settings may be tuned:
    a flag has many knobs, and every knob adds luck.
  - "Session" is a setting. For crypto: the UTC day, London hours (8am-4:30pm
    London time) or New York hours (9:30am-4pm New York time). For stock
    tokens: New York hours.

TRADE LIKE A PERSON (every rule at its standard value, never tuned; keep a
rule only if the test proves it helps, the same as a confirmation)
1. Bigger picture first: the entry chart follows the bigger chart's trend
   (for example only buy on 15m when the 4h trend is up). Measure it two
   ways: (a) the bigger trend built from the same chart's last 250 candles,
   which the trading program can do today; (b) the coin's real 4h / 1d
   candles, which needs my OK to let the trading program read two timeframes.
   Show both.
2. Trade only near key prices: yesterday's high, low and close, the session
   open, VWAP and round numbers (BTC at 100,000). An entry must be within a
   fixed distance of one (for example 0.5 x ATR), the way a person waits for
   price to reach a level.
3. Skip bad moments: no entry from 30 minutes before to 30 minutes after big
   US news (the inflation report, the Fed decision, the jobs report), from a
   fixed calendar file kept in the project for every day tested; and no entry
   in quiet weekend hours on coins whose volume is below their normal. The
   trading program must skip the same moments.
4. Manage the trade: take half the profit at 1R, move the stop to break even,
   and let the rest run to 2-3R; or close if nothing happens after a fixed
   number of candles. Count every piece honestly: a break-even close is never
   a win, and a trade's result is the sum of its pieces.
5. Daily discipline: at most 3 trades per coin per day, stop that coin for the
   day after 2 losses, and wait 3 candles after a stop-out before the next
   entry on that coin.
6. Enter with a limit order at the level, the way people buy a pullback:
   cheaper (a 0.01% rebate instead of 0.075%), but some trades are missed.
   Count the missed ones. The trading program needs my OK before it sends
   limit orders.
7. Real fills: when price jumps past the stop (a stock token reopening, a
   sudden drop), fill at the first price after the jump, never at the stop.
8. Risk the same dollars every trade: show every result twice, with the flat
   $5 margin AND with $1 of risk per trade (what a flat $5 trade loses at a 1%
   stop; the position sized by its stop distance, margin never above $10).
   Changing the trading program to size by risk needs my OK.

RUN IT TO THE END, WITHOUT ME
- When I start this prompt I am away. Do not stop to ask me anything between
  the start and the finished results page. Run every coin on Gate and every
  timeframe (15m, 30m, 1h, 4h, 1d).
- The only early stop is THE FIRST CHECK in PART 5: if nothing beats random
  entries even before fees, stop and report that. That is a finished answer.
- Fix what breaks on the way and keep going: redo a failed coin by itself,
  start a share GitHub refused again, and commit and push every fix with its
  RCA entry (CLAUDE.md).
- Time budget: the whole run finishes within 48 hours. If the pilot's timing
  says it will not, cut the settings per round to fit and say so in the
  results.
- The ONLY things that wait for me: switching any strategy on, changing the
  trading program, and real money.
- Tell me how it is going while I am away: send a phone notification when the
  pilot's first check is known and when everything is finished (and if the run
  has to stop). Publish the results page as soon as the pilot is done, and keep
  it updated as the coins land.
- Survive a power cut or a closed chat: keep a progress file under
  ~/.tradingagents (which coins and timeframes are done, which GitHub runs exist
  and where their results are), so a new chat told "resume Prompt 1" picks up
  where it stopped instead of starting over.

READ FIRST, BEFORE ANY CODE
CLAUDE.md, docs/OPERATOR-ASKS.md (my own words), and these measured facts:
1. Fees are the whole loss. Before fees the average Backtest v2 trade made about
   $0.00. The median round trip is 0.228%, about $0.23 per $100 trade.
2. My 49 existing confluence types (45 cf_ setups + 4 cx_ votes) were summed
   over 3,196,436 stored 2:1 strategies (last 30 days, Oct 21, 2026). Only 15.7%
   of 43,139,491 trades won, and every type lost money. The best, cf_chan_l1,
   won 20.8%. https://claude.ai/artifact/KUSGMCCqF1vUNjxX1qrME6
3. The Pro Trader research (Oct 20-21, 2026) chose single-family rules per coin
   and timeframe on older days, then judged them on 120 days they never saw:
   -$0.23 a trade over 220,977 trades, against -$0.22 for random entries. Every
   family lost, and its 2 passes are what luck produces. Reuse its machinery
   (pro_search, pro_shard, pro_checks, pro_page): deep windows, untouched test
   months, coin groups, the random-entry luck bar and the drift check.
4. Searching hard finds luck. Sep 25 Strat fitted formulas per coin: +$66,803.59
   on the days they were picked, -$20,162.67 on the days after. And if you keep
   the best of 100 tries, a setting with NO edge still shows about a 60% win
   rate on 20 trades, 57% on 30, 50% on 50 and 45% on 100.
5. Practice matches the backtest well: 35 of 41 practice trades (85.4%,
   Oct 12-18, 2026) matched their backtest trade. A real edge in the backtest
   should carry into practice, and a fake one will not.
6. On Gate's contract list a maker (limit) order earns a 0.01% rebate, while a
   taker order pays 0.075%. Today the trading program only sends taker orders.

WHAT TO EXPECT (say so in the results, never hide it)
- Most coins will probably have NO passing pick. "Nothing passed" is a real
  answer, not a failure.
- Long losing runs are normal at 2:1: a strategy winning 40% usually hits 7-9
  losses in a row, with a 1-in-10 chance of 11-12. Show each pick's worst run.
- About 357 coins (mostly stock tokens listed Sep 03, 2026) are too young for
  120 test days: list them as "too young", never drop them silently.
- Per-minute order books exist only for the newest ~45 days and funding only
  for 180 days: older trades pay the coin's usual cost. Count them.

PART 1 - BUILDING BLOCKS (decide them before measuring, keep them few)
- From published evidence and the existing rules, pick at most 12 building
  blocks across the families above. Give each at most 2 settings to tune, with
  the standard setting first. Write down what each one should do BEFORE
  measuring it.
- Reuse existing code (signals_pro, pro_indicators, the cf_ conditions). Never
  rebuild an existing rule under a new name.
- Look back at most 250 candles, so the trading program's 299 closed candles
  decide exactly what the backtest decides. One implementation for the trading
  program and the backtest, with the cut-frame no-look-ahead test.

PART 2 - THREE SEPARATE STRETCHES OF TIME, PER COIN AND TIMEFRAME
- History per timeframe: 15m and 30m 365 days, 1h 365, 4h 730, 1d 1,095, each
  with 300 candles of lead-in.
- Settle EVERY exit by the minute over the whole history: Gate's monthly minute
  files for older months, its 5-minute bars over the current month's gap, and
  its last week of minutes (backtest_report.fine_bars). GitHub's machines
  download them per coin, never this PC.
- The pilot first checks how far back Gate's monthly minute files go for each
  coin and how long they take to download. Where minutes are missing, settle
  exits on the timeframe's own candles and label those trades.
- Split by closing time into:
  1. TUNING days (oldest): the only days the rounds search on.
  2. CHECK days (the stretch just before the test): used only to pick the best
     round and to decide when to stop.
  3. TEST days: the newest 120 days on 15m, 30m and 1h, 240 days on 4h and
     365 days on 1d, because slow timeframes trade less (120 daily candles
     give a strategy trading 1 day in 10 only about 12 trades). Judged ONCE,
     after the pick is final. Nothing is ever chosen, tuned or stopped by
     looking at them.
- A coin that still cannot reach 20 test-day wins on its own is judged only
  through its group's default, using the group's test trades together. It
  never passes alone.
- State the size of each stretch per timeframe, and how many trades each holds.

PART 3 - 100 ROUNDS, EACH COIN AND TIMEFRAME
- A round = one batch of up to 500 new candidates (trigger + confirmations +
  settings + stop/target), guided by what the earlier rounds learned, scored on
  the TUNING days only.
- Run up to 100 rounds (up to 50,000 candidates per coin and timeframe). Stop a
  coin+timeframe early when 10 rounds in a row do not improve its result on the
  CHECK days.
- Show, per round, the tuning-days result next to the check-days result, so
  anyone can see when more rounds stopped helping.
- Group the coins first (asset kind, volatility, trending vs. snapping back,
  cost) and run the same rounds per group. A coin keeps its own pick only if it
  beats its group's pick on both its tuning and its check days.
- Print the total number of candidates tried, per coin+timeframe and overall.
- Name the search method and its random seed in every run's saved inputs, so
  any run can be repeated exactly.
- Keep each round's best 10 per coin and timeframe in a research file under
  ~/.tradingagents (the G: drive), never in Stored strategies.

PART 4 - EXITS
- Fixed stop/target pairs that pay 2:1R or better after fees, stop 2% or less.
- Stops and targets sized to the coin's usual swing (ATR) are Prompt 2's job,
  not this run's. Taking half at 1R and moving the stop to break even is
  measured here (TRADE LIKE A PERSON, rule 4); a trade closed at break even is
  counted as break even, never as a win.

PART 5 - PROVE IT (this decides everything)
- THE FIRST CHECK, before anything else: on the pilot's TEST days, does any
  pick beat random entries BEFORE fees? Before fees my average trade makes
  about $0.00, and the Pro Trader picks did no better than random. If nothing
  beats random even before fees, stop and report it: no fee saving and no rule
  can rescue a pick with no edge, so do not spend the full market's machine
  time.
- Measure with the nightly grid's own engine on GitHub, using all 40 machines
  across both accounts. Every trade pays its own minute's order book and funding
  where they exist, and keeps practice's skip rules: cost check, price already
  ran away, closed stock market, re-entry.
- Never run while the nightly jobs hold the machines (Room strategies from
  1:00am, the backtest update from 1:31am).
- Prompt 1 and Prompt 2 take turns on the 40 machines, never both at once,
  in this order and without waiting for me: Prompt 1's pilot, Prompt 2's
  pilot, Prompt 1's full market, Prompt 2's full market.
- The luck bar, in two parts: every coin and timeframe gets a quick random
  check (random entries with the same exits, 3 seeds), and the full 100-round
  search on random entries, chosen the same way, runs on a fixed sample of 100
  coins spread across the coin groups to show how often luck alone passes.
- A pick passes only if, on its TEST days, it does ALL of these:
  - pays its payout (2:1R or better) on the fees those trades really paid
  - makes money with at least 20 wins
  - trades at least once a week
  - stays above zero at the low end of a 90% confidence range per trade
  - beats its own coin and timeframe's quick random check
  - survives costs x 1.5 and a stop filling 0.1% worse
  - its neighbouring settings also make money
  - every confirmation and every person-like rule helps (the same rule
    without it made less)
- Next to how many real picks pass, print how many random picks pass.
- Run a 20-coin pilot first, as a check: BTC, ETH and SOL plus 17 coins
  spread across the coin groups, including 3 stock tokens. Record its machine
  time, then go straight on to the full market without waiting for me, unless
  THE FIRST CHECK failed.

PART 6 - PUSH THE COST UNDER THE EDGE (a what-if, measured apart)
- For every pick that beats random before fees, measure it again with limit
  (maker) orders for the entry AND the target; the stop stays a market order.
  Count the trades a limit order would have missed, and show how the win rate
  and payout change when the fee drops.
- Look first where costs are smallest compared with the move: the cheapest
  coins (BTC, ETH and SOL pay about 0.15% a round trip) on 1h and 4h.
- Changing the trading program to send limit orders needs my OK first.

OUTPUT
- An artifact per coin and timeframe with the full standard kit from CLAUDE.md:
  row id first, PROFIT $, TP, SL, leverage, wins, losses, worst losing run,
  trades and trades/day, click a row for every trade, a base margin box, and
  filters including max TP %, max SL % and last N days. Each row shows its
  payout, its test-days win rate, its worst-case win rate and its break-even
  win rate, with the best 2:1, 3:1, 4:1 and 5:1 side by side.
- Show WHEN each pick works: its test-day results split by market mood (BTC
  going up, down or sideways; quiet or wild days) and by long vs. short trades,
  next to simply holding the coin over the same days. A pick that only wins
  when BTC rises is a different bet from one that wins in any market.
- One plain-word verdict: how many coin+timeframes have a pick that passed,
  compared with the luck bar, and what they would have made per day at $5.
- My rooms switch strategies on and off at 65-90% wins, so they would never
  run a 2:1 pick. Propose the rules for a room built for these picks (for
  example profit per trade, and a win rate above its break-even with enough
  wins). Change no room without my OK.
- Treat a room as one bet: most coins move with BTC, so 50 picks can lose
  together. Propose the most trades open at once and a daily loss stop, and
  show how the passing picks would have done together, as one room, on the
  test days.
- Keep a graveyard file (docs/research/graveyard.md) of every idea that failed,
  with its numbers, so no session tries it again.
- Nothing gets switched on, filed into Stored strategies or added to the nightly
  grid until I say "deploy". After any deploy, run /practice_backtest_audit
  every day for the first two weeks, re-test every deployed pick each week on
  the new days, and stop the whole project if the picks are below break-even
  after 4 weeks or 200 practice trades, whichever comes first.
- Change the trading program ONE thing at a time, practice only, starting with
  the change the pilot shows is worth the most (two timeframes, limit orders,
  or the same dollars of risk per trade), each with my OK.
```

## Prompt 2 - open TP/SL: the computer sets each trade's stop and target

```text
PROMPT 2 - OPEN TP/SL: THE COMPUTER SETS EACH TRADE'S TARGET AND STOP

ROLE
Act as a professional systematic trader for my app (analyzer-x). It trades Gate
USDT perpetual futures, $5 margin x 20x = $100 per trade, flat, practice account
only. Today every strategy id is tied to ONE fixed take profit and stop loss
(e.g. TP 2% / SL 0.8%). I want OPEN TP/SL: when a confluence entry fires, the
computer decides THAT trade's stop and target from the chart at that moment.
Find, for each coin and each timeframe (15m, 30m, 1h, 4h, 1d), the exit rule
that gives the HIGHEST WIN RATE POSSIBLE while every single trade keeps 2:1R or
better after fees, and that still holds on days it was never built or chosen on.

RUN IT TO THE END, WITHOUT ME
- Run STEP 1 below from start to the finished results page without stopping
  to ask me anything, on every coin and timeframe, the same way as Prompt 1
  (fix what breaks and keep going, finish within 48 hours, stop early only if
  no entry beats random before fees). STEP 2 and STEP 3 change the trading
  program, so they wait for me.
- Same as Prompt 1: a phone notification when the pilot's first check is known
  and when everything is finished, the results page published after the pilot
  and kept updated, and a progress file so a new chat told "resume Prompt 2"
  picks up where it stopped.

DO IT IN STEPS - DO NOT BUILD AHEAD OF THE EVIDENCE
STEP 1 - TEST FIRST (backtest only)
- Build ONE piece: "set this trade's stop and target from the chart at entry"
  (one function, e.g. exit_levels). Only the backtest engine (backtest_strategy)
  and the GitHub replay use it.
- Do NOT change the trading program, the strategy ids, the Backtest list or
  the rooms in this step.
- Run the research below on GitHub.
DECISION
- Show me, per coin and timeframe, whether open TP/SL beat the best FIXED
  stop/target for the same entry on the 120 days it never saw.
- If it did not: record it in docs/research/graveyard.md and stop. Nothing
  else was changed, so there is nothing to undo.
STEP 2 - MAKE IT TRADE (practice only, only after I say yes to Step 1's results)
- The trading program's practice exits (_dry_fill) use the SAME function at
  entry, so practice and backtest set the same stop and target.
- Ids: hash coin + timeframe + entry + exit rule + its settings
  (backtest_report.row_code), adding the exit rule only when there is one, so
  EVERY CURRENT ID STAYS EXACTLY THE SAME. Never an exchange or a page number.
- The Backtest list shows each open-exit strategy's average stop and target
  (and their range), so the max TP % / max SL % filters still work.
- The rooms check "2:1R or better" and "stop 2% or less" on EVERY trade.
- Change the trading program ONE thing at a time, practice only, each with
  my OK.
STEP 3 - REAL MONEY: later, only with my OK and a working Gate key.
- In every step, my current fixed-TP/SL strategies are never touched and
  their ids never change.

RELATION TO PROMPT 1
- Prompt 1 finds the best confluence ENTRY with fixed stop/target pairs. This
  prompt finds the best EXIT RULE for an entry. Entries keep every one of
  Prompt 1's "TRADE LIKE A PERSON" rules (bigger picture, key prices, skipping
  bad moments, daily discipline, limit entries, real fills). Run it in parallel: start on the
  existing confluence entries (the 45 cf_ setups, the 4 cx_ votes and the Pro
  Trader pt_ families), then apply it to Prompt 1's picks as they come.
- Take turns with Prompt 1 on the 40 GitHub machines, never both at once,
  without waiting for me (Prompt 1's pilot, this pilot, Prompt 1's full market,
  this full market),
  and never run while the nightly jobs hold them (Room strategies from 1:00am,
  the backtest update from 1:31am).
- An open exit rule is worth keeping only if it beats the best FIXED stop/target
  for the same entry, coin and timeframe on the untouched test days.

WHAT 2:1R MEANS, PER TRADE (use exactly this)
- R = what that trade loses if its stop is hit: its stop distance PLUS the fees
  and spread it is expected to pay. Use the trading program's own cost check at
  the entry minute (auto_trader.cost_verdict / minute_verdict) for the cost.
- Every trade's own target must pay at least 2R after fees:
  (TP - cost) >= 2 x (SL + cost). A rule may aim at 3R, 4R or 5R, never less
  than 2R. If the chart does not leave room for 2R (for example the next
  resistance is too close), the trade is SKIPPED and counted as "no 2:1 room",
  never taken with a worse ratio.
- Stop at most 2% (the rooms' limit) and at least 2 x the round trip, so fees
  never decide the trade. Stops stay inside the 20x liquidation guard.
- Break-even win rate: 33.3% at 2R, 25% at 3R, 20% at 4R, 16.7% at 5R. A trade
  closed at break even is counted as break even, never as a win.
- With a flat $5 margin, a 2% stop loses about 4 times what a 0.5% stop loses,
  so wide-stop trades decide the dollars. Report every result in R, in dollars
  at the flat $5 margin, AND in dollars at $1 of risk per trade (the position
  sized by that trade's stop, margin never above $10). Changing the trading
  program to size by risk needs my OK.
- When price jumps past the stop (a stock token reopening, a sudden drop), fill
  at the first price after the jump, never at the stop.

HOW THE COMPUTER MAY DECIDE TP/SL (pick at most 8 rules, each with at most
2 settings, written down BEFORE measuring)
1. Swing size: stop = k x ATR(14) of the timeframe (k 1 / 1.5 / 2), target at
   2R after fees.
2. Invalidation: stop just past the level that proves the entry wrong (the
   flag's low, the last swing low, the session low, the other side of VWAP for
   a long; mirrored for a short), target at 2R after fees. "Session" is the
   same setting as in Prompt 1 (UTC day, London or New York hours for crypto;
   New York hours for stock tokens).
3. Room to run: stop at invalidation, target at the next level in the way (the
   session high, the last swing high, a VWAP band), taken only if that level is
   at least 2R after fees away.
4. Strength: a stronger confluence (every confirmation agreeing, volume well
   above normal) aims at 3R instead of 2R.
5. Time limit: close after N candles if neither price is reached; count the
   real result.
6. Manage it like a person: take half the profit at 1R, move the stop to break
   even, and let the rest run to 2-3R or trail it behind the last swing. A
   break-even close is never a win, and a trade's result is the sum of its
   pieces.
7. Not in this run (ask me after the results): trailing the whole stop once
   the trade is up 2R.
- Every rule reads only the coin's own closed candles of its own timeframe (no
  lookback past 250 candles), because that is all the trading program sees.
  One implementation of each rule, with the cut-frame no-look-ahead test.

READ FIRST, BEFORE ANY CODE
CLAUDE.md, docs/OPERATOR-ASKS.md (my own words), Prompt 1, and these facts:
1. Fees are the whole loss: before fees the average Backtest v2 trade made
   about $0.00, and the median round trip is 0.228% (about $0.23 a trade).
2. Searching hard finds luck: if you keep the best of 100 tries, a setting
   with NO edge still shows about a 60% win rate on 20 trades and 57% on 30.
   Sep 25 Strat made +$66,803.59 on the days it was picked and -$20,162.67
   after.
3. The Pro Trader research's per-coin picks lost $0.23 a trade on 120 unseen
   days, the same as random entries (-$0.22).
4. Practice matches the backtest well: 35 of 41 practice trades (85.4%,
   Oct 12-18, 2026) matched their backtest trade.
5. Expect the same as Prompt 1: most coins may have no passing pick, losing
   runs of 7-9 are normal at 2:1, and about 357 young coins cannot be judged
   yet.

THE SEARCH (same discipline as Prompt 1)
- Same history as Prompt 1 (15m and 30m 365 days, 1h 365, 4h 730, 1d 1,095),
  every exit settled by the minute over the whole history. The pilot checks how
  far back Gate's minute files go and how long they take; where minutes are
  missing, exits are settled on the timeframe's own candles and labelled.
- Three stretches of time per coin and timeframe, by closing time: TUNING days
  (oldest, the only days the search uses), CHECK days (pick the best round,
  decide when to stop), TEST days (the newest 120 days on 15m, 30m and 1h,
  240 on 4h, 365 on 1d; judged ONCE after the pick is final). State each
  stretch's size and trade count.
- A coin that cannot reach 20 test-day wins on its own is judged only through
  its group's exit rule, using the group's test trades together.
- About 113 entries x 32 ways to set TP/SL = about 3,600 candidates per coin
  and timeframe. That is small enough to test every one on the TUNING days, so
  no rounds are needed. Score each by its WORST-CASE win rate (the low end of
  the 90% range for its number of trades), and pick on the CHECK days.
- Group the coins first; a coin keeps its own exit rule only if it beats its
  group's on both its tuning and its check days.
- Print the total number of candidates tried, and name the search method and
  its random seed in every run's saved inputs, so any run can be repeated.
- Keep the best 10 per coin and timeframe in a research file under
  ~/.tradingagents (the G: drive), never in Stored strategies.

PROVE IT
- THE FIRST CHECK: only entries that beat random entries BEFORE fees on their
  TEST days (from Prompt 1's pilot, or the existing entries measured the same
  way) go on to the open-exit search. If no entry does, stop and report it: an
  exit rule cannot rescue an entry with no edge.
- Measure with the nightly grid's own engine on GitHub, all 40 machines across
  both accounts (shared with Prompt 1). Every trade pays its own minute's order
  book and funding where they exist, and keeps practice's skip rules.
- Luck bar, as in Prompt 1: every coin and timeframe gets a quick random
  check (random entries with the same exit rules, 3 seeds), and the full
  search on random entries runs on the same 100-coin sample.
- A pick passes only if, on its TEST days, it does ALL of these:
  - every trade paid 2:1R or better on the fees it really paid
  - makes money with at least 20 wins, and trades at least once a week
  - stays above zero at the low end of a 90% confidence range per trade
  - beats the best FIXED stop/target for the same entry, coin and timeframe
  - beats its own coin and timeframe's quick random check
  - survives costs x 1.5 and a stop filling 0.1% worse
  - its neighbouring settings also make money
- Run the same 20-coin pilot as Prompt 1 (BTC, ETH, SOL plus 17 across the
  coin groups, including 3 stock tokens) as a check, record its machine time,
  then go straight on to the full market without waiting for me.

OUTPUT
- An artifact per coin and timeframe with the full standard kit from CLAUDE.md
  (row id first, PROFIT $, TP and SL shown as each row's range and average,
  leverage, wins, losses, worst losing run, trades and trades/day, click a row
  for every trade with the stop and target the computer chose and why, e.g.
  "stop below swing low 1.04, target 2R = 1.12", a base margin box, filters
  including max TP %, max SL % and last N days), plus a column comparing each
  open exit with the best fixed stop/target for the same entry.
- Show WHEN each pick works, as in Prompt 1: test-day results by market mood
  (BTC up, down or sideways; quiet or wild days) and long vs. short, next to
  simply holding the coin.
- One plain-word verdict: on how many coin+timeframes the open TP/SL beat the
  fixed one on the test days, compared with the luck bar, and by how much a day
  at $5.
- Show how the passing picks would have done together, as one room, on the
  test days, with the most trades open at once and a daily loss stop you
  propose (most coins move with BTC, so many picks can lose together).
- Add every failed exit rule to docs/research/graveyard.md with its numbers.
- Nothing gets switched on, filed into Stored strategies, added to the nightly
  grid or changed in the trading program until I say "deploy". After any
  deploy, run /practice_backtest_audit every day for the first two weeks,
  re-test every deployed pick each week on the new days, and stop the whole
  project if the picks are below break-even after 4 weeks or 200 practice
  trades, whichever comes first.
```
