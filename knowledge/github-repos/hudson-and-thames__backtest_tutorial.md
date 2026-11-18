# hudson-and-thames/backtest_tutorial

- Link: https://github.com/hudson-and-thames/backtest_tutorial
- What it is: three teaching notebooks for a paid Udemy course on backtesting; one toy strategy (a moving-average cross on the S&P 500) is built, then charged for trading costs.
- Stars, last push, licence: 161 stars, last push Jan 09, 2024, MIT.
- Markets and timeframes: the S&P 500 index (`^GSPC`, 1991 to 2022) and the SPY fund (2000 to 2022), one bar a day, from Yahoo Finance.
- Read: `README.md`, `getting_started.md`, `requirements.txt`, `Vectorized_Backtest_Tutorial.ipynb` (all cells and printed results), `Intro_Transaction_Costs.ipynb` (all cells and printed results), and the headings of `YFinance_Tutorial.ipynb` (data download only, no strategy).

## The strategies

There is ONE strategy, and the notebook itself calls it *"just a toy exampe to illustrate how to run a backtest - don't use this in real life!"*

**1. Moving-average cross, always in the market, long or short** (`Vectorized_Backtest_Tutorial.ipynb`)
- Inputs: the daily close. Short average `short_window = 50` days, long average `long_window = 252` days (the text says 200, the code uses 252).
- Signal: `+1` (long) when the 50-day average is above the 252-day average, `-1` (short) when it is below. No neutral state once both averages exist, so it is always holding something.
- Entry and exit: the signal is lagged one day (`signals['signal'].shift(1)`) and multiplied by the next day's return. There is no separate exit: the position flips when the averages cross.
- Stop and target: none.

**2. The same signal, sized by volatility** (same notebook, and repeated in `Intro_Transaction_Costs.ipynb`)
- Target yearly swing (volatility) `tgt_vol = 0.15` (15%).
- Recent swing: the standard deviation of daily returns over 22 days, times the square root of 252 to make it yearly.
- Size = 0.15 / recent swing, clipped to between 0 and 2 (`.clip(0, 2)`), so up to **2x leverage**. The comment says "Clip weights to a maximum of 1 to avoid leverage" while the code uses 2; the next comment admits it is 2x.
- The size is lagged one day like the signal.

The course text also says that among simple price indicators only two "are known to work: momentum and short term reversals" (an opinion in the markdown, not tested here).

## How it tests them

- **No train/test split and no walk-forward.** The settings (50, 252, 15%, 22 days, cap 2) are fixed by hand and run once over the whole history, so there are no "unseen days" in the sense we use.
- **Look-ahead:** handled correctly for a daily strategy: signal and size are both shifted one day.
- **Costs** (`Intro_Transaction_Costs.ipynb`, SPY 2000 to 2022), all charged on turnover (the daily change in position size):
  - brokerage `brokerage_fees = 0.0020` = **20 basis points (0.20%)** per unit traded;
  - spread `bid_ask_fee = 0.000032` = **0.32 basis points**, an average taken from ETF.com, not from real quotes;
  - slippage: assumes at most $1,000,000 traded a day, and "1% of daily value traded moves the price 10 basis points", applied linearly: `cost = (adv / 0.01) * 0.0010`.
  - No borrowing cost for the short side (the text lists it as an "extra" few people add).
- **Baseline:** in the first notebook the "Benchmark" column is the UN-sized strategy, not buy-and-hold. There is no buy-and-hold comparison and no random-entry baseline anywhere.

## What it claims

Unchecked, quoted from the notebooks' saved outputs:

- `Vectorized_Backtest_Tutorial.ipynb` (1991-12-31 to 2022-12-30, before any cost): un-sized cross "Cumulative Return 426.4%", "CAGR 3.77%", "Sharpe 0.38", "Max Drawdown -47.5%"; volatility-sized: "Cumulative Return 859.68%", "CAGR 5.16%", "Sharpe 0.53", "Max Drawdown -34.35%", "Profit Factor 1.09", "Win Days % 53.09%".
- `Intro_Transaction_Costs.ipynb`: *"Wow! We pay almost 50% away to brokerage fees with only 20 basis points."*; spread *"We pay about 0.8% fees over an almost 30 year period."*; slippage *"less than 25 basis points for the entire period"*; and the printed *"Sharpe Ratio Before: 0.47 / Sharpe Ratio After: 0.33"*.

## What matters for us

On our Gate measurement the average trade earns about $0.00 before fees and the fees plus the buy-sell gap cost about $0.23 per $100 traded, so fees are the whole loss, and chosen strategies did no better than random entries on days they were not chosen on. This repo does not answer that question. It does charge a realistic-looking fee (0.20% per unit traded, close to Gate's 0.15% round trip in taker fees), and its own result shows the same lesson as ours: the fee alone took the Sharpe from 0.47 to 0.33 on a strategy that trades only a few times a year. But it never tests on unseen days, never compares to buy-and-hold (the S&P 500 itself rose far more than 3.77% a year over 1991 to 2022 with dividends), and never compares to random entries, so nothing here shows an edge.

Ideas worth testing on our crypto data:
1. **Volatility-targeted size** (size = 15% / recent 22-bar yearly swing, capped): it does not create an edge, but on our coins it could cut the worst losing runs on the jumpy contracts. It would need to be measured against our flat $5 stake on the same trades.
2. **The turnover-based cost check**: charge cost on every change of position size, not only on entries and exits. That matters only if we ever scale positions in and out.

## Doubts

- The cumulative profit after costs is only drawn as a chart (no number saved), so the after-cost return is not quoted here.
- Comment and code disagree twice: 200 vs 252 days for the long average, and "maximum of 1" vs a clip at 2.
- The notebook itself warns that its QuantStats "monthly active returns plot" values "don't look correct".
- The course lectures (causality, detecting false strategies) are not in the repo; only the notebooks are.
