# Why the system does not profit — research notes (Oct 22, 2026)

The operator, Oct 22, 2026: *"Can you do a research including other sessions
plan, and research outside as well, refer to books, reddit etc"* — after *"I
have million rows of strategy how come i do not profit and a pro trader
profits"*.

The readable report is the Claude Docs page "Why The System Doesn't Profit"
(https://claude.ai/artifact/Nbhge7m3MjVkF4R4qQTut3). These are the four
research tracks behind it, kept here so every session reads them before
giving strategy advice (see the memory note "read research before strategy
advice"). Nothing was edited, run or dispatched by the research itself.

**The answer in one paragraph.** Before fees the average trade makes about
$0.00, and on 120 days they were never picked from, the best picks lost $0.23 a
trade against $0.22 for random entries (Pro Trader, Oct 20, 2026). So the cost
of every trade (Gate taker 0.075% each way plus the price gap, median 0.228% a
round trip) is the whole loss. Books, studies and practitioners agree: stop
picking patterns by recent results, cut the cost per trade (waiting/limit
orders), match exits to the idea (trend: trailing stop, no target; held days),
test a few reasoned ideas as whole families against random entries with a
luck correction, and add leverage last.

Tags used below: [B] book or publisher contents page · [A] the author's own
paper/blog/slides · [R] third-party review · [read] full text read · [abs]
abstract only · [sec] secondary report · [api] Gate's public API · [calc]
arithmetic from cited inputs.

---

## 1. What this project already measured (internal digest)

**Costs**
- Gate: 0.075% for a market order each way; BTC_USDT's contract listing shows a
  0.01% rebate for a maker (limit) order [api, checked Oct 22, 2026]. Gate's
  2026 fee guide lists 0.020% maker / 0.050% taker for the base tier — the
  account's real rate can be read only with a Gate key.
- Median Backtest v2 round trip 0.228% (~$0.23 per $100) over 3,819,977 rows;
  before fees the average trade made about $0.00; every row kind lost
  $0.17-$0.25 a trade (Pro Trader spec, Oct 20).
- Practice, Oct 01: all rooms −458.31, of which 355.91 was costs; break-even
  56.6% against 41.2% won (FORECAST-V2.md).
- Practice, to Oct 06: six rooms −$889.10 on 4,375 trades, average win +$0.80,
  average loss −$1.04 (CLAUDE.md).
- Only 230,972 of the confluence research's 1,860,286 trades (12.4%) paid their
  own minute's order book (CLAUDE.md, Oct 22).

**Backtest against practice**
- After the Oct fixes, 35 of 41 practice trades (85.4%, Oct 12-18) matched
  their backtest trade (confluence spec).
- Oct 07 walk-forward: all replay trades 67.97% won, +$127,633.22; only trades
  practice can take 57.34%, +$6,228.37; each move counted once 53.46%,
  −$672.37 (OPERATOR-ASKS.md line 5961).

**Search picks against random picks**
- Sep 25 Strat: +$66,803.59 on the days chosen, −$20,162.67 over 165,661
  unseen trades. Sep 27 ML: +$13,150.19 chosen, −$229.49 over 15,566 unseen.
- Pro Trader (Oct 20; commits 50752d96f953, 5d90bc53f413): 2,255 picks made
  −$51,811.98 over 220,977 unseen trades (−$0.234 a trade, 23.9% won) against
  −$0.221 for random entries; all 8 families lost; the 2 rows that passed every
  check are luck (3 of 2,255 real picks vs 3 of 1,900 random picks).
- Confluence Prompt 1 (Oct 21-22): real +0.065R a trade before fees against
  random +0.0316R over 67 coins (226 coin-timeframes), 90% range −0.079R to
  +0.146R — stopped by its own check. Prompt 2 (computer-chosen TP/SL): beat
  random on 23 of 226 coin-timeframes, random beat it on 24.
- The 49 existing confluence types (Oct 21): 3,196,436 strategies at 2:1,
  15.7% of 43,139,491 trades won, every type lost money.

**Daytime rule (Oct 07, 20,604 trade lists, 16 days):** current rule 14,010
bets 53.4% won −$672.37; daytime rule 1,655 bets 60.1% won +$394.82 (16 of 16
days green); random 207,557 bets 34.3% −$30,469.01. Chosen with hindsight; the
trial room #4FC03172 passed 0 of 18 on Oct 19.

**Plans and status:** Pro Trader done (failed; group "Oct 21"); Confluence
Prompt 1 done (stopped; its Phase B — partial exits, time limits, limit-order
entries, $1-risk sizing — never ran); Prompt 2 stopped; group "Oct 22" (12,861
picks on 3,457 coin-timeframes) being filed; per-minute cost coverage planned
(~3-4 days on 60 machines).

**Never tested:** a limit-order backtest (no code exists), any exit other than
a fixed stop/target, family-level tests with multiple-testing corrections, a
year of data at real costs, a frozen-rules practice run of any one family.

## 2. The project's own literature survey (Oct 20, 2026) — key points

- With fixed barriers and no drift a trade wins SL/(TP+SL) and earns zero
  before costs; the lift needed over random is cost/(TP+SL): 6.2 points at
  SL 1% / TP 2.69%, 3.4 points at SL 2% / TP 4.69%.
- Among 3.8M variants with 30 trades each, the best win rate by chance is
  ~72.9% when the truth is 30%. Proving a 3.4-point lift takes 1,123 trades for
  one test, 6,912 for a million variants.
- Grades: A trend following (daily-monthly, calm contracts, stops near 2%);
  B trend-gated breakout, hold-time gate, liquidity split, session/spread cost
  gate; C funding, squeeze, liquidation rebound; rejected: intraday momentum,
  RSI(2)/IBS, calendar effects, carry, ML for now.

## 3. Academic and industry evidence (addendum to the survey)

**Checks on the survey's claims.** Hudson & Urquhart 2021 [read]: 14,919
daily rules, data to Dec 31, 2017; the best in-sample BTC rule earned Sharpe
−0.05/−0.06 out of sample (Jan-Jul 2018). Han, Kang & Ryu 2023 [read]: best
trend rule (28-day lookback, 5-day hold) Sharpe 1.51 vs 0.84 market, 15 bps
costs; lookback chosen in-sample; shorting negative momentum lost money.
Borri, Liu, Tsyvinski & Wu (arXiv 2510.14435) [read]: carry Sharpe 6.45 over
Aug 2020-May 2025, 4.06 from 2024. BIS WP 1087: carry up to 60% a year, high
carry predicts crashes. Zarattini, Pagani & Barbon 2025: net Sharpe above 1.5,
one in-sample backtest. arXiv 2607.27070: across 7 BTC cascades no variable
warned consistently.

**By family**
1. Trend following — B daily-weekly, long side, large coins; C at 15m-4h.
   Kogan, Makarov, Niessner & Schoar 2024 (JFE): retail trades crypto as
   momentum followers. Borri et al.: two-week cross-sectional momentum still
   significant after 2020 (t 3.70), longer lookbacks not.
2. Short-term reversal — B as a pattern, C at 0.23%. Ammann et al.:
   survivorship/delisting bias 62.19% a year equal-weighted; after correcting,
   no positive link to one-week momentum.
3. Funding carry — B, decaying, needs a spot leg; funding as a direction
   signal C. Kaiko (Jul 2025): BTC 30-day basis peaked 15.3% Jan 2025, carry
   worth deploying on 31 days (8%) of 2025. BitMEX Q3 2025: funding positive
   >92% of the time. Cao, Zhai & Luo 2024: 48 of 134 perp predictors
   significant, explained by a basis factor plus a price-volume factor. Memon
   et al. 2026 (weak journal): bottom-decile funding followed by +0.506% in 24h
   on Binance BTC.
4. Liquidations / open interest — C. Tran et al. 2026 (weak journal): OI
   change, cumulative funding and realized volatility predicted 5%+ crashes in
   8h, out-of-sample AUROC 0.76 — a crash filter, not a direction signal.
5. Time of day — B for liquidity/volatility, C for returns. Hansen, Kim &
   Kimbrough 2024: day/hour cycles in BTC/ETH volume and volatility. Shanaev et
   al. 2023: candle-turn minutes +0.58 bp/min in 2021, only at a zero-fee tier.
   Kaiko 2024: weekends 13% of BTC volume. IMF GFSR Oct 2026: >50% of
   tokenized-stock trading outside 9:30am-4:00pm ET; the stock re-prices 87-99%
   of the overnight move in the first 5 minutes — fits the daytime-rule result
   as a cost/noise effect.
6. Costs and maker orders — A that costs kill high turnover (Novy-Marx &
   Velikov 2016); B that maker orders save most of it (Harris & Hasbrouck 1996:
   limit orders beat market orders even with a non-fill penalty; Linnainmaa
   2010: retail limit orders get picked off). Albers et al. 2021: passive fills
   lose ~0.5-3.3 bps to adverse moves against a 2.5 bp rebate. [calc] With a
   post-only limit entry, a reduce-only limit take-profit and a market stop, at
   a 30% win rate the round trip falls to ~0.09% from 0.23%, cutting the lift
   needed over random from 6.2 to ~2.5 points (SL 1% / TP 2.69%). The backtest
   must fill a TP only when price trades through it and log unfilled entries.
7. Overfitting — A. Wiecki et al. 2016: backtest Sharpe explained <2.5% of
   out-of-sample Sharpe across 888 Quantopian algorithms. Suhonen et al. 2017:
   215 bank strategies, median Sharpe 1.20 backtest vs 0.31 live. McLean &
   Pontiff 2016: returns 26% lower out of sample, 58% lower after publication.

## 4. What the books say (digest)

- **López de Prado / Bailey** [B][A]: with 5 years of data try no more than 45
  configurations; after 7 tries a 2-year backtest with Sharpe > 1 is expected
  from noise. Deflated Sharpe (§14.7.3); PBO rejects a pick that is no better
  than choosing at random. Backtesting is not a research tool (§11.4). Stops
  and targets should depend on volatility (§3.3-3.4); on a random walk no
  stop/target pair is reliably best, and a tight stop under a big target is
  the worst shape (ch. 13). Meta-labeling (§3.6-3.7): a second model decides
  whether and how big, never the side. [calc] 12 million independent tries on
  30-day windows → a luck-only annualised Sharpe of ~19.
- **Aronson, EBTA** [B][R]: ch. 6 data-mining bias; ch. 8-9 tested 6,402 rules
  on the S&P 500, none significant after White's Reality Check.
- **Chan** [B][A]: every extra optimised parameter needs an extra year of daily
  data; test against randomly placed trades (AT ch. 1); no stop-losses on
  mean-reverting strategies and no profit caps on momentum strategies; Kelly
  leverage = mean excess return / variance (QT ch. 6) — ~$0 a trade means
  ~zero leverage.
- **Carver** [R][A]: backtested Sharpe of 2-3 is "far too optimistic"; costs at
  most a third of the pre-cost Sharpe; horizon map for futures: "One hour to
  several days: Nothing"; stops at X × volatility; profit targets "make no
  sense at all if you're looking for trends"; his own scalper and fast
  mean-reversion tests failed.
- **Clenow** [B][A]: "Buy rules are not important. Indicators are not
  important." "Expect to lose 60-70% of all trades. Winners win big." 50/100-day
  trend filter, 50-day breakout, 3-ATR trailing stop, ATR sizing.
- **Kaufman** [B][A]: judge a system by the average of all optimisation
  results; trend lookbacks that worked at 10 days in the 1970s now need
  60-200 days.
- **Harris** [B][A]: "If you have no edge, you should not trade for profit."
  "Market-makers profit from impatient uninformed traders." A contrarian
  system using market orders pays the spread instead of earning it.
- **Taleb** [R]: short bars are mostly noise; enough tries make some look
  brilliant. **Tharp** [B][A]: position sizing cannot rescue zero expectancy.

**The authors' eight changes:** count every test and correct for it; judge
whole signal families, not winners; use longer data and hold longer; match the
exit to the signal; scale stops and size to volatility; set a cost budget and
use maker orders; add leverage last; meta-label the signals and paper-trade.

## 5. What practitioners say (Hacker News, Elite Trader, QuantConnect, blogs)

Reddit refused the research tool (search, old.reddit and .json); these stand
in for it. Quotes were checked against the page text.

- **Why backtests fail live:** too many tries (Bailey et al.; Robot Wealth:
  "Anyone can make it pass out-of-sample tests if they try enough
  combinations"; Davey: re-testing "converts the out of sample period to an in
  sample period"); costs (HN simonhughes22: "once you factor in the trading
  fees, slippage and the spread, you will almost always lose money"); regime
  change; leverage (Davey: start "with very small leverage, for example 2 to
  1"); dead coins left out of the data.
- **What works for small crypto accounts, and the catch:** funding/basis carry
  (Robot Wealth ~30% in 2024 on DeFi, "gotten harder"; BIS: carry predicts
  crashes; auto-deleveraging broke hedges on Oct 10-11, 2025); market making
  needs rebate tiers (Gate's market-maker programme entry bar was $20M of 30-day
  volume in Dec 2022); slow trend following on big coins (Zarattini et al.; HN
  andr: hold "a few hours or more"); arbitrage needs speed. HN k9294 (claims a
  $6B best month, unverifiable): "nothing based on OHLC worked for us".
- **Process:** a reason first ("Edge comes first" — Robot Wealth); count tries;
  compare against random performance; Davey: walk-forward once, Monte Carlo,
  6-12 months live without money, ~20 of 200 strategies deployed; don't
  re-optimise too often.
- **Reality checks:** Taiwan day traders — fewer than 1% reliably profit after
  fees (Barber et al. 2014); Brazil — 97% of 300+-day futures day traders lost,
  0.4% earned more than a bank teller (Chague et al.); ESMA — 74-89% of retail
  CFD accounts lose; Hyperliquid Mar 2025-Jun 2026 — front-end traders −$1.11B,
  market makers +$208M, algorithmic takers about break even (Jia et al. 2026);
  56% of StockTwits finfluencers had negative skill and "antiskilled have more
  followers".

Sources with links are in the report's Sources section.
