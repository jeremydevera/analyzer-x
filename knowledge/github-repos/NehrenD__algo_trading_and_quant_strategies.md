# NehrenD/algo_trading_and_quant_strategies

- Link: https://github.com/NehrenD/algo_trading_and_quant_strategies
- What it is: the unfinished companion repo of the textbook "Algorithmic Trading and Quantitative Strategies" (Velu, Hardy, Nehren), holding worked answers to the book's chapter 2-6 exercises as notebooks plus their data files; only one chapter (5) actually tests trading rules.
- Stars, last push, licence: 336 stars, last push Feb 04, 2021, no licence stated. The README says: "We are actively working on this repo and it's not ready for usage just now."
- Markets and timeframes: daily exchange rates (Indian rupee against the US dollar, pound and euro, Dec 04, 2006 to Nov 05, 2010; 25 currencies against the dollar 2000-2012), daily and monthly US stock returns (15 stocks, Jan 11, 2000 to Mar 31, 2013), AAPL daily 2015-2018, and one day of full order-book messages for CSCO and BIOF. No crypto.
- Read: `README.md`, the file list, and the cell code and text of `exercises/chapter2_solutions.ipynb`, `chapter3_solutions.ipynb`, `chapter4_solutions.ipynb`, `chapter5_solutions.ipynb`, `chapter6_solutions.ipynb` and `notebooks/Chapter2_Univariate_Time_Series_Models.ipynb` (chapter 5 read in full; the others by their exercise text and headings). The `temp/` folder (homework PDFs, LaTeX, R code) was not read.

## The strategies

Only `exercises/chapter5_solutions.ipynb` builds trading rules. All are tested on the three rupee exchange rates (USD/INR, GBP/INR, EUR/INR), daily, with one equal unit in each currency, long or short by the sign of the signal, the position taken the day AFTER the signal (`pos.shift(1)`).

**Rule 1 - price against its moving average.** Signal = price - its m-day average; long when above, short when below (`mav_strategy`). m tried from 20 to 300 days in steps of 10 (`m_values = list(range(20,310,10))`). (The exercise text says the opposite: sell when above.)

**Rule 2 - Bollinger.** m-day average plus/minus 2 standard deviations; long above the upper band, short below the lower band (`bollinger_strategy`). Same m range.

**Rule 3 - breakout ("resistance-support").** Long when the price is above the highest price of the previous m days, short when below the lowest (`resistance_support_strategy`, with `.shift()` so today is not in its own window). Same m range.

**Rule 4 - two moving averages ("momentum").** Signal = m-day average - n-day average with m < n, every pair from the same 20-300 range; long when the short one is above.

**Rule 5 - RSI.** RSI over m days built from the average up-move and down-move of daily returns: long when under 30, short when over 70, flat in between.

**Pair trading** (distance method, cointegration method, regression-on-the-market "APT" method) is set as exercises 3-5 but the notebook stops part-way through the distance method (a function measuring the squared gap between currency pairs month by month); there is no pair trading rule or result.

The other chapters are statistics, not strategies: chapter 2 (ARMA and GARCH models of the rupee rates, normality tests, AAPL serial correlation, building an order book from BIOF messages), chapter 3 (PCA and VAR models of 15 stocks and 7 currencies), chapter 4 (5-minute trade counts, returns, durations and best-price exchange for CSCO), chapter 6 (mean-variance portfolio weights for CME, GS, ICE, LM, MS in 2014, how much they change when expected returns move by 5%, a no-short-selling version, LASSO, index tracking).

No stops, no targets, no leverage anywhere: each rule is always in (long or short) or flat.

## How it tests them

- Vectorised backtest on daily log returns, one equal unit per currency, Sharpe ratio with a 3% risk-free rate, 250 trading days a year (`backtest_strategy`).
- **Costs: 15 basis points (0.15%) per unit traded** (`tc_pct = 15/10000`), every rule run with and without it.
- **No unseen days.** Every setting is tried over the whole 2006-2010 period and the best one is reported for that same period ("What is the optimal m?"). No train/test split, no walk-forward, no buy-and-hold or random baseline.

## What it claims

From the text cells of `exercises/chapter5_solutions.ipynb`, unchecked:
- Rule 1: "We see that the current optimal $m$ is 90 days with a return of 4.35% and a SR of 0.2." Then: "In this case the return is always negative with 90 days still the best case."
- Bollinger: "the best $m$ is 80 with a small 0.01 SR without cost and -0.71 SR when cost are included".
- Breakout: "$m$ of 230 as the best performing lag but with negative 0.36 SR that goes down to -1.8 including TC. Not a very good strategy..."
- Two averages: "Optimal $m$ and $n$ pair is 60-120 without TCs reaching a respectable 0.6 SR. Again things turn negative when TCs are included with optimal pair 60-110 achieves a -1.36 SR".
- RSI: no conclusion written.

## What matters for us

This repo's own answer agrees with ours: even after picking the best setting on the same days it is judged on (which flatters every rule), every rule loses money once a 0.15% cost is charged. That is the same picture as our Gate measurement - about $0.00 a trade before fees, about $0.23 per $100 of fees and buy-sell gap, fees are the whole loss. Nothing here could beat that: no unseen days, no random baseline, and the "best" settings were chosen with hindsight.

Worth testing: not much new. The one idea that is not already a standard signal in our grid is the **pair-selection by similar market sensitivity** ("APT method": regress each coin's return on BTC's over a rolling 3 months and pair the coins with the closest coefficients), as an alternative to cointegration for picking two Gate perpetuals to trade against each other - but it is only an exercise statement here, never built.

## Doubts

- The cost charge is worked out across currencies instead of across days: `delta_pos = pos.diff(axis=1)` takes the difference between the three currencies' positions on the same day, not the change in each position since yesterday, so the 15 bp is charged on the wrong amount. The direction of the conclusion (costs make everything negative) may still hold, but the numbers are not reliable.
- The Bollinger lower band is written as `p_minus = mav + 2*mstd` (a plus sign), the same as the upper band, so the rule can never go short on a band break and is not the Bollinger rule it claims to test.
- Rule 1's code goes long above the average, the exercise says sell above it.
- Chapter 3 contains an unanswered note ("Question for Raja: it seems that the optimal order is VAR(3), but the exercise calls for VAR(5), why?") and a "TODO Add Commentary"; the repo is openly unfinished.
- I did not read the `temp/` homework files or the saved chart outputs.
