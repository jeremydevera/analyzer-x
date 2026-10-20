# Pro Trader research: a strategy per coin and timeframe, proven on days it never saw

Operator, Oct 20, 2026: *"i want to you to create different strategies for each
coin, with you applying all you've learned for the repository i gave you and the
existing strategies which uses different confluence, I want an advannced research
where you will think of your self as a professional trader, meaning you will need
to research on proven and working indicators out there"*, the enhanced prompt they
approved (24 additions, target **at least 2:1 after fees**), then *"okay start
developing, then show me the results each day per coin per time frame in artefact
so i can review it if we can push to prod"*.

## What the data already says (measured before building)

| lesson | measured |
|---|---|
| Fees are the whole loss | 3,819,977 v2 rows (450 random of 4,175 pair files, Oct 20, 2026): before fees the average trade made about $0.00; median round trip paid 0.228% ($0.23 on $100); every row kind lost $0.17-$0.25 a trade |
| Picking past winners does not hold | every rule tested (win rate, beat break-even, $/trade, best per coin, best rule across coins, green two periods in a row) lost on the days after the pick: about -$0.13 to -$0.22 a trade |
| Per-coin fitting finds luck | Sep 25 Strat, 5,020 formulas fitted per coin+tf: +$66,803.59 on the days they were chosen on, -$20,162.67 over 165,661 trades on unseen days (-$0.122 a trade, 38% of formulas green) |
| Confidence-filtered ML did best | Sep 27 ML, 474 models (top 2% most confident moments, Wilson lower bound): +$13,150.19 when chosen, -$229.49 over 15,566 unseen trades (-$0.015 a trade, 46% green) |
| Backtest win rate collapses in practice | rooms on MEXC: backtests 70-90%, practice won 44% of 4,347 trades, -$931.49 |
| 2:1 with a 65-90% floor is empty | 0 of 1,460,718 2:1 rows won 80%+ with 15+ trades; rooms took 3 practice trades after Oct 16, 2026 |
| A maker order is paid, a taker pays | Gate's contract list (BTC, SOL, AAPL): maker -0.01% (a rebate), taker 0.075%. The account's own rate needs a key to confirm |
| History Gate serves | candles: years (REST 10,000 bars + monthly archive); funding, open interest, liquidation totals, long/short ratio (`contract_stats`): the last 180 days only; single liquidation orders: one hour at a time |

## The design

* **Families** (`tradingagents/signals_pro.py`, prefix `pt_`): at most 12, from a
  literature survey (`docs/research/2026-10-20-pro-trader-survey.md`), each with a
  pre-registered expectation and at most 3 knobs; digit 0 of every knob is the
  literature's default. One implementation shared by the runner
  (`auto_trader.signal_for`) and the backtest (`_dirs_for_backtest`). A seeded
  random-entry family (`pt_rand`) is the luck baseline, measured exactly like the
  others.
* **The families as built (64 settings, every one firing and matching the
  runner's 299 candles at every cut tested; no two settings of a family give
  the same signals):**

  | code | family | survey | knobs (digit 0 first) |
  |---|---|---|---|
  | `brk` | closing breakout (new n-bar closing high/low) | #1 | bars 20/55 · 200-bar trend gate on/off · quiet-stretch gate off/on (#3) |
  | `tsm` | time-series momentum, every lookback agreeing | #2 | 90 / 30 / 30+90 / 30+90+180 bars · hold / flip · both sides / long only |
  | `ses` | the #1 breakout in the busy hours | #7 | 12pm-9pm UTC / 9:30am-4pm New York · Mon-Fri on/off |
  | `sqz` | squeeze breakout (Bollinger bandwidth percentile) | #9 | lowest 20% / 10% · box 20/10 bars · trend gate on/off |
  | `abn` | big-candle continuation (k x the 60 candles' usual move) | #10 | k 2 / 1.5 / 2.5 · 1.5x volume off/on |
  | `ma` | moving-average crossover | BLL 1992, Szakmary 2010 | 50/200, 20/100, 10/50 · flip / hold |
  | `pull` | pullback inside the trend (2-bar RSI) | Connors | RSI 10 / 5 · trend 200 / 100 bars |
  | `vwm` | volume-weighted momentum | Huang et al. 2024 | 100 / 50 / 200 bars · hold / flip |
  | `rand` | random entries, the luck baseline | — | seed 0/1/2 · 1% / 3% of candles |

  Left out because the runner hands a strategy only its own coin's candles of
  its own timeframe (no funding, no BTC, no other coin): #4 liquidity tiers
  and #6 cross-sectional strength (the coin groups stand in for both), #5 the
  BTC gate, #8 funding crowding, #11 liquidation flushes. Each needs a runner
  change first, which is the operator's call. A session window on 1d never
  trades (every daily candle opens at midnight UTC) and is skipped there.
* **Exits:** fixed stop/target pairs from the grid (`br.pairs_for`) whose payout
  after fees is at least 2:1 on the coin's own cost (`br.pays_two_to_one`), stop
  at most 3% (rows over 2% are flagged: the rooms cap stops at 2%). No new exit
  type in this cut; ATR-sized exits need the operator's OK first.
* **Measured on GitHub, both accounts** (`pro.yml` -> `.github/scripts/pro_shard.py`
  -> `sweep_shard.run_pair` -> `backtest_strategy(fine=, book=)`), the nightly
  engine untouched: per-minute order-book costs and minute exits where they exist
  (the newest ~45 days), the flat cost and bar exits before (counted
  `cost_unmeasured`), funding where Gate still serves it (180 days).
* **Deep windows:** 15m and 30m 180 days, 1h 365, 4h 730, 1d 1,095, each with
  300 bars of lead-in.
* **Four test months, by closing time:** the engine's recent windows are asked
  for 30/60/90/120 days (`br.SHORT_DAYS` is set to those in the research
  process only), so every row carries the trades CLOSED in each of the last four
  30-day months plus everything before them, from one walk.
* **Coin groups** from the days BEFORE every timeframe's test months only (no
  look-ahead; the 1h candles are cut two days early because the 1d frame's
  months start up to two days before the 1h frame's): asset kind
  (`venue.kind`), daily volatility third, trending vs. snapping back (variance
  ratio of 24 one-hour returns). Each coin's usual cost and correlation with
  BTC are measured and kept beside them; they group nothing.
* **What the older days pay:** Gate's per-minute order books exist only for
  the newest ~45 days, so every older trade pays the coin's USUAL cost,
  measured on those newest days. The main test's choice therefore reads a
  cost level from the days it is judged on (a level per coin, never a trade's
  outcome): the page says so, and the choice is made again as if every
  choosing-day trade had paid 1.5x its fees, to show how much it leans on it
  (`pro_report.choose(cost_mult=)`).
* **Choosing, then judging:**
  * main test: one choice per coin and timeframe made on the days before the four
    test months, judged on the 120 days it never saw; the newest month is the
    strictest check;
  * walk-forward: the choice re-made before each test month from everything
    closed before it;
  * each group gets a default (best summed over the group's coins); a coin keeps
    its own pick only if it beat the group default on the choosing days.
    Deliberate change from the prompt: the prompt said to choose between the two on
    the untouched days, but choosing there would spoil them as a test.
* **A row passes** only if, over its untouched days, it does all of these
  (`pro_checks`):
  * pays 2:1 after the fees ITS UNTOUCHED-DAYS TRADES paid
  * makes money with at least 20 wins
  * stays above zero at the low end of a 90% confidence range per trade
  * beats `pt_rand` on the same coin and stop/target, per trade
  * survives costs x 1.5 and a stop filling 0.1% worse
  * its neighbouring settings (one knob one step away) make money on average
  * when it is a group's default, it made money on both halves of the group
  * every on/off filter in it helps (the same rule with it off made less)

  The first six MUST be judged and pass: a row that could not be compared
  with random entries, or whose neighbours never traded, has not passed. The
  last two may be "not applicable" (an own pick; no filter switched on).
  "One minute late" is reported as not measured (the engine has no entry
  delay).
* **The luck bar for passing:** random entries are chosen EXACTLY as a
  strategy is (`choose(baseline=True)`) and their money checks judged from
  their counts (`pro_page.money_pass`): how many of those pass is how often
  luck alone gets through, beside how many real rows do.
* **The check run** measures the chosen rows again with every trade kept, which
  gives every row its day-by-day results, market moods (BTC up / down / sideways,
  quiet / wild), long vs. short beside holding the coin, and the room-as-one test.
  It replays the search's own fee, liquidation distance, usual cost and both ends
  of the order book; what cannot be frozen without copying it (readings Gate or
  the app published for older minutes after the search, minutes that moved from
  one source to another, the oldest funding leaving Gate's 180 days) is caught by
  comparing every number of the two rows, and a row that differs says so on the
  page (`pro_page.drift`).
* **Nothing is switched on**, filed into Stored strategies or added to the nightly
  grid: the operator reviews the page first.
