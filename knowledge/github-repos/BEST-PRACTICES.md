# Best practices from the 36 reviewed repos

Written Nov 18, 2026, from the "How it tests them" sections of the notes in this folder. Each
practice says which repos did it, with their numbers, and whether this app already does it.
Most repos did NOT follow these practices; the list comes mainly from the honest few:
stefan-jansen, tmr-crypto, Danny-397, KennethMartin06, ahmedas91, Thomas-lcb, pybroker and
agiprolabs.

## 1. How the days are split

**1.1 Split by time, never shuffle.** Train on older days and test on newer ones. A random
shuffle puts test days between training days, so the model has already seen the neighbours of
every day it is tested on.
- Done right: ahmedas91, KennethMartin06, Danny-397, tmr-crypto, stefan-jansen.
- Broken: Ridwat, crypticalgo and tzelalouzeir use `train_test_split(..., random_state=42)`,
  which shuffles.
- **This app: yes.** Backtest v3 keeps 90 unseen days, Backtest v4 splits older 70% / newest 30%,
  and Forecast v4 walks forward day by day.

**1.2 Keep one holdout and open it only once.** Freeze every setting first, then run the
held-back years one time.
- stefan-jansen: 2024-2025 is opened once, after the configuration is frozen. Its best of 2,807
  setups then lost 44.8% a year there.
- tmr-crypto: tuned on Jan 01, 2018 - Sep 30, 2019, run once on Oct 01, 2019 - Sep 20, 2021.
- KennethMartin06: the test years Jan 03, 2022 - Dec 29, 2025 are used once, at the end.
- **This app: yes** (Backtest v3's unseen days, and the confluence research's "first check").

**1.3 Leave a gap between training and testing.** If the label looks N days ahead, the last N
training days already contain test prices.
- ahmedas91 cuts 5 days (`PURGE_DAYS = 5`) for a 5-day target. KennethMartin06 drops any day
  whose label crosses a split line (`purge: true`). pybroker's `lookahead` leaves N bars out.
  agiprolabs' walk-forward skill asks for a gap.
- **This app: partly.** A trade is judged by the day it OPENED after the split
  (RCA-2026-11-05-F), but a trade that opens just before the split and closes after it still sits
  on the line.

**1.4 Walk forward: re-choose settings at each step, using only the past.**
- tmr-crypto re-picks its EMA pair every 10-28 days from the days before.
- ahmedas91 trains on every year before a validation year, picks settings on that validation year,
  then tests the next year, for each year from 2013 to 2025.
- pybroker refits in every window and tunes each window separately.
- FinRL's ensemble picks the model on the 63 days just before each trading window.
- **This app: yes** (Forecast v4 and the picker lab decide each day from trades closed before that
  midnight).

**1.5 The test days never choose anything** — not the settings, not the stop/target, not the
saved model, not the epoch to stop training at.
- Broken, and how:
  - Marshal-Kalynchuk searched its stop/target on the test predictions.
  - ebrahimpichka kept the "best model" by scoring it on the test days.
  - Thomas-lcb swept its cooldown on the test set.
  - Packt's LSTMs stop training on the test year.
  - ethansilvas and Mun-Min re-ran until the test plot looked good.
  - abailey81 picked its pairs on prices covering the whole test.
- **This app: yes**, by construction in v3 (`_before` cuts the older walk's data at the split).

## 2. Costs

**2.1 Charge every cost on every change of position: fee, slippage and funding.**
- stefan-jansen: 0.04% commission + 0.01% slippage a side, plus funding at every 8-hour
  settlement on the position held.
- KennethMartin06: 0.10% fee + 0.05% slippage a side (0.30% a round trip).
- Danny-397: 0.4% a round trip, higher than ours.
- TradeMaster's high-frequency game pays the buy-sell gap by walking a 5-level order book.
- **This app: yes, and stricter than any of them.** Each trade pays its own minute's recorded
  order book, Gate's 0.075% fee each way, and funding over the hold.

**2.2 Re-run the same trades at several cost levels, and find where the edge dies.**
- tmr-crypto: 0.05%, 0.07%, 0.1%, 0.2%, 0.3%, 0.4% and 0.5% a trade. It stops paying around 0.4%.
- KennethMartin06: 0, 5, 10, 20 and 40 basis points.
- stefan-jansen: 0 to 50 basis points a leg.
- hudson-and-thames: 0.20% brokerage alone takes the Sharpe from 0.47 to 0.33.
- pybroker: 0.10% slippage per fill turns a dip-buy from +18.02% into −8.66%.
- **This app: partly.** The Pro Trader research re-chose at 1.5x fees, and Forecast v4 has a
  cheap-coins switch. But no strategy shows the cost at which it stops making money.

**2.3 Fill like a real order would.** Decide on a closed bar and fill on the next one, never at
the close the signal already saw. Don't trade a price you could not get.
- hudson-and-thames shifts the signal and the size one day.
- pybroker fills on the next bar (`buy_delay = 1`).
- Broken: crypticalgo traded z-scores as if they were prices.
- **This app: yes** (the recorded book at the fill minute; a waiting order fills only when the
  price trades through it).

## 3. Baselines: what a result must beat

**3.1 Beat buy-and-hold over the same days.** Most of the honest repos do this.
KennethMartin06: 0 of 15 model-and-stock pairs beat buy-and-hold over 2016-2025.
- **This app: partly.** It compares with random picks, and rarely with simply holding the coin.

**3.2 Beat random entries run through the SAME rules and costs.** This is the comparison that
matters.
- Thomas-lcb runs a random agent with the same fees and the same cooldown. Its +9.10% became
  −9.51% against random's −9.30% on validation.
- tmr-crypto runs 1,000 shuffled position runs plus 1,000 random EMA pairs, and prints the share
  of random runs that did at least as well.
- agiprolabs prints random signals beside its ML strategy.
- **This app: yes** (Backtest v3's 200 random runs per combination; Forecast v4's random picks on
  every day).

**3.3 Beat a market with no pattern at all.** Shuffle the price history to destroy any pattern,
then run the strategy on it. If it still "works", the result is an artefact.
- Danny-397's surrogate test does this.
- **This app: no.**

## 4. Luck and choosing among many

**4.1 Correct for having tried many strategies.** The best of thousands of worthless strategies
always looks good.
- stefan-jansen reports the Deflated Sharpe Ratio, a Rademacher bound and the minimum track record
  length.
- Danny-397 uses a Holm correction across tests.
- agiprolabs has CPCV (cross-validation over many train/test combinations), the deflated Sharpe
  and PBO (the probability that the in-sample winner is below the median out of sample).
- **This app: partly.** Backtest v3's proof divides its 5% bar by its 63 combinations. Forecast
  v4's "could be luck" is judged per rule set and is NOT corrected for the 24,480 rule sets it
  chooses from.

**4.2 Give a range, not one number.** Bootstrap the result, in blocks so losing streaks stay
together.
- KennethMartin06: a block bootstrap of 2,000 draws in 20-day blocks, testing whether "model
  Sharpe minus buy-and-hold Sharpe" is above zero.
- pybroker: 10,000 draws, with the lower end of 90/95/97.5% ranges. It draws single bars, which
  breaks up losing streaks.
- **This app: partly** (v3 uses a day-clustered bootstrap; Forecast v4 and the picker lab do not).

**4.3 Repeat the run many times.** Use several seeds or several start dates, and report how
many of them made money.
- Danny-397: 10, then 30 seeds. An early +275% run turned out to be luck.
- FinRL and TradeMaster use one seed each, which is a weakness.
- **This app: partly** (the picker lab restarts every 7 days and prints how many starts made
  money).

**4.4 Write the prediction down before the run.**
- Danny-397 pre-registers its predictions (`docs/preregistration/`), and runs and reports its
  full settings sweep instead of picking.
- **This app: partly** (the confluence research's first check was agreed before it ran).

**4.5 Score a setting together with its neighbours.** A setting that wins only at one exact
number, and loses at the numbers next to it, is luck.
- tmr-crypto does this.
- **This app: no.**

**4.6 Test on markets the settings were never tuned on.**
- tmr-crypto tuned on BTC, then applied the same settings unchanged to ETH and BNB.
- **This app: no.** Every coin is chosen on its own history.

## 5. Data honesty

**5.1 No look-ahead from bigger candles.** A 1-hour candle labelled 10:00 holds the 10:59
close.
- Thomas-lcb joined resampled candles onto 1-minute rows, so each row could see up to 59
  minutes ahead. It was probably the source of its "stable" signal.
- **This app: yes** (bigger candles are what had closed by each moment; tested by cutting frames
  at 11 points).

**5.2 Fit any scaling on the training days only.**
- Done right: Ridwat.
- Broken: maleshchenko (whole file) and crypticalgo (whole file, all six coins joined).

**5.3 The label must not be in the inputs.** Marshal-Kalynchuk's label was the past 6-hour
move, which the model could see; that is the source of its 89% "accuracy".

**5.4 Use the market as it was on each day.** Choosing today's winners and testing on the past
is hindsight.
- Done right: FinRL-Trading uses the point-in-time S&P 500 list.
- Broken: its growth list (NVDA, META, TSLA, GOOGL, AMZN) is the period's biggest winners.
  Packt chapter 12 picks the "1,000 biggest" over the whole sample.
- **This app: partly.** It uses only contracts Gate trades today, and says so in every v3
  verdict.

**5.5 Report money after costs, not accuracy.**
- Ridwat's "100%" was always saying Hold. jwallbridge reports accuracy and never trades. The
  maleshchenko label moves are smaller than the fee.
- **This app: yes.**

## 6. Before real money

**6.1 Paper-trade first, and long enough.**
- agiprolabs asks for 70/30 out of sample, 100+ trades and paper trading.
- FinRL-Trading paper-traded 5 months, one run, which is too short to judge.
- **This app: yes** (the practice rooms).

**6.2 Ask for enough trades.**
- agiprolabs: 100+.
- **This app: yes** (Backtest v3's proof asks for 300 unseen trades; the rooms ask for 20-30).

## What this app does not do yet

These are the practices above that the honest repos used and this app does not. Each is a
measurement to add, not a strategy:

1. **Correct Forecast v4 and the picker lab for the 24,480 tries** (4.1): a deflated Sharpe or
   PBO, so the leader's figure is shrunk for how many it was chosen from.
2. **A cost sweep per strategy** (2.2): print the round-trip cost at which each strategy stops
   making money, beside its result.
3. **Neighbour scoring** (4.5): a stop/target or window that wins alone among losing neighbours
   is flagged.
4. **A no-pattern market** (3.3): run the picker on shuffled prices. Whatever it "finds" there is
   the size of luck.
5. **Block bootstrap ranges on Forecast v4** (4.2).
6. **Choose on some coins, judge on others** (4.6).
7. **Buy-and-hold beside every result** (3.1).
