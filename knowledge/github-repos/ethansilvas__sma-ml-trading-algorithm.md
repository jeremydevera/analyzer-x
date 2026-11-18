# ethansilvas/sma-ml-trading-algorithm

- Link: https://github.com/ethansilvas/sma-ml-trading-algorithm
- What it is: a school homework notebook (UW FinTech "Machine Learning Trading Bot Challenge") that feeds two moving averages into a classifier to guess whether the next bar goes up or down.
- Stars, last push, licence: 1 star, last push Mar 08, 2023, GPL-3.0, not archived.
- Markets and timeframes: one emerging-markets stock ETF ("MSCI–based emerging markets ETF", `Resources/emerging_markets_ohlcv.csv`). 4,323 bars from Jan 21, 2015 9:30am to Jan 22, 2021 3:45pm. The bars sit on 15-minute marks, but only bars that had a trade are present: 1,060 trading days, a median of 3 bars a day (most 23), median volume 200 shares (my own count of the file). So the README's "4-day" and "150-day" averages are really 4 and 150 BARS, about 1.3 and 50 trading days.
- Read: `README.md`, `machine_learning_trading_bot.ipynb` (every code cell and its printed output), and the data file `Resources/emerging_markets_ohlcv.csv` (I counted bars, days and moves myself; I did not run the notebook).

## The strategies

There is one idea, tried with two models. Despite the name "Dual Moving Average Crossover", there is no crossover rule: the two averages are only the inputs.

**Inputs (notebook, "Step 2" and "Step 3")**
- `SMA_Fast` = average of the last `short_window` closes, `SMA_Slow` = average of the last `long_window` closes.
- The notebook as saved uses `short_window = 4`, `long_window = 150` in the first part (the tuned version) and `short_window = 4`, `long_window = 100` in the KNN part (the course's starting values).
- Both are moved back one bar (`X = signals_df[['SMA_Fast', 'SMA_Slow']].shift()`), so the bar being guessed is never inside its own inputs. No look-ahead there.
- Scaled with `StandardScaler`, fitted on the training bars only.

**Label (the "answer" the model learns)**
- `Signal = 1` when that bar's return is 0 or more, `Signal = -1` when it is below 0. In plain words: "did this bar close higher than the last one?"

**Models**
1. Support vector classifier, all default settings (`svm.SVC()`).
2. Same, "tuned": fast 4 bars, slow 150 bars, 6 months of training data.
3. K nearest neighbours, `KNeighborsClassifier(n_neighbors=5)`, with the starting values (4 / 100 bars, 3 months of training).

**Entry and exit**
- Every bar the position is whatever the model says: +1 = long the whole account, -1 = short the whole account. `Strategy Returns = Predicted x Actual Returns` for that bar. It is always in the market and switches side whenever the guess changes.
- No stop, no target, no position sizing beyond "100% long or 100% short", no leverage.

**What the models actually did (printed classification reports)**
- Tuned SVC, 3,911 test bars: it said "up" on 97% of the up bars and "down" on only 3% of the down bars (recall 0.97 / 0.03). Accuracy 0.56. Up bars were 2,193 of 3,911 = 56.1% of the test, so 0.56 accuracy is exactly what "always say up" scores. It is buy-and-hold with a few short bars.
- KNN, 4,092 test bars: accuracy 0.52, "up" recall 0.66, "down" recall 0.34. Up bars were 2,288 of 4,092 = 55.9%, so it scored below "always say up".

## How it tests them

- One split by date: train on the first 3 months (`DateOffset(months=3)`) or 6 months of data, test on everything after (`training_end + DateOffset(hours=1)` to Jan 22, 2021). No walk-forward.
- **The test days were used to choose the settings.** The author re-ran the notebook with different averages and training lengths and kept whichever gave the best final test return ("sweetspot" of 6-7 months, fast 4, slow 150). So the "tuned" result is chosen on the very days it is reported on.
- **No costs at all**: no fee, no spread, no slippage, nothing for going short.
- Baseline: "Actual Returns" = buying and holding the ETF over the same test bars. No random baseline.

## What it claims

Quoted from `README.md` (unchecked; I did not run it):
- Baseline SVC: "Strategy final cumulative return - 1.520", "Actual final cumulative return - 1.389", "Accuracy - 0.55".
- Tuned SVC: "Strategy final cumulative return - 2.018", "Accuracy - 0.56".
- KNN: "Strategy final cumulative return - 1.750", "Accuracy - 0.52".
- "the highest I was able to get that value to was 2.018 with a fast SMA of 4, long SMA of 150, and 6-months of training data."
- "all of the good models I experimented with could only reach around a 0.5 accuracy anyway."

## What matters for us

On Gate, across millions of backtested strategies, the average trade earns about $0.00 before fees, and fees plus the buy-sell gap cost about $0.23 per $100 trade; strategies we chose did no better than random entries on days they were not chosen on.

This repo cannot survive that, for three reasons:
- **No costs, and a strategy that changes side often.** In this file the average bar moves 0.345% and the median bar only 0.148% (my count). The true up/down answer changes side on 2,177 of 4,322 bars. Any model that follows it pays a round trip on many bars, and our round trip (about 0.23%) is bigger than the median bar's whole move.
- **Not tested on unseen days.** The best result (2.018) was picked by looking at the test period.
- **It does not beat a fair baseline.** The tuned SVC is long 97% of the time, so it is mostly buy-and-hold; its 56% accuracy equals "always say up". KNN scored below that.

Ideas worth testing on our crypto data: none new. Moving-average signals are already in our grid. The one lesson worth keeping is a check: **compare any model's hit rate with the share of the most common answer** (here 56% "up") before calling it skill.

## Doubts

- I did not run the notebook, so the cumulative returns are the author's.
- The saved notebook mixes settings: the first part runs fast 4 / slow 150 with `DateOffset(months=6)` while its comment says "offset of 3 months" and "4 and 100 days"; the KNN part runs 4 / 100 with 3 months. The README's numbers come from different runs of the same cells.
- The ETF is very thin (median 200 shares a bar), so even a stock-market spread would be large here.
- The README's "Baseline SVC ... 1.520" is not printed anywhere in the saved notebook; only the tuned run's report is.
