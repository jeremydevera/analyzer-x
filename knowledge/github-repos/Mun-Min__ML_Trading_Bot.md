# Mun-Min/ML_Trading_Bot

- Link: https://github.com/Mun-Min/ML_Trading_Bot
- What it is: the same school homework as ethansilvas/sma-ml-trading-algorithm (a Trilogy Education / 2U course "Machine Learning Trading Bot" challenge), done by another student, with a small neural network as the second model.
- Stars, last push, licence: 8 stars, last push Apr 13, 2023, no licence on GitHub (the README's assignment text ends "© 2022 Trilogy Education Services, a 2U, Inc. brand. All Rights Reserved."), not archived.
- Markets and timeframes: the same emerging-markets ETF file as the ethansilvas repo (`Resources/emerging_markets_ohlcv.csv`; I compared both files and they differ only in line endings): 4,323 bars from Jan 21, 2015 to Jan 22, 2021, on 15-minute marks but only bars that traded, a median of 3 bars a day. "SMA 8 and 20" are bars, not days or months.
- Read: `README.md` (the assignment text), `Evaluation Report/README.md` (the student's report), `machine_learning_trading_bot.ipynb` (every code cell and printed output). I did not run it.

## The strategies

One idea, three runs. Inputs, label and trading rule are the course's starter code, word for word the same as in ethansilvas/sma-ml-trading-algorithm.

**Inputs (notebook, "Step 2")**
- `short_window = 8`, `long_window = 20` in the saved notebook (the course started at 4 and 100).
- `SMA_Fast` and `SMA_Slow` = simple averages of the last 8 and 20 closes, moved back one bar (`.shift()`), then scaled with `StandardScaler` fitted on the training bars.

**Label**
- `Signal = 1` when that bar's return is 0 or more, `-1` when below 0 ("did this bar close higher?").

**Models**
1. Support vector classifier, default settings (`svm.SVC()`).
2. The same after "tuning" (6 months of training data, then 8 / 20 bars).
3. A small neural network: `MLPClassifier(solver='sgd', alpha=1e-5, hidden_layer_sizes=(8, 4), random_state=42)`. It printed "ConvergenceWarning: Stochastic Optimizer: Maximum iterations (200) reached and the optimization hasn't converged yet." So it stopped before it finished learning.

**Entry and exit**
- Every bar: +1 = whole account long, -1 = whole account short; `Strategy Returns = Actual Returns x Predicted`. Always in the market, switching side whenever the guess changes. No stop, no target, no leverage.

**What the models actually did (printed reports, 4,049 test bars)**
- SVC (8 / 20 bars, 6 months): "up" recall 0.92, "down" recall 0.08, accuracy 0.55.
- MLP: "up" recall 0.99, "down" recall 0.01, accuracy 0.56. Up bars were 2,270 of 4,049 = 56.1% of the test, so the network learned "always say up". It is buy-and-hold.
- The assignment said to fit the new model with the ORIGINAL settings (4 / 100 bars, 3 months). The notebook fitted the MLP on the same 8 / 20-bar, 6-month data as the tuned SVC.

## How it tests them

- One split by date: training from Feb 02, 2015 10:15am to Aug 02, 2015 10:15am (`DateOffset(months=6)`; the comment above it still says "3 months"), test from the next hour to Jan 22, 2021. No walk-forward.
- The settings (training length, average lengths) were chosen by re-running and looking at the test-period plot, so the test days choose the settings.
- No fee, no spread, no slippage, nothing for shorting.
- Baseline: "Actual Returns" = holding the ETF over the test bars (plotted, no number given). No random baseline.

## What it claims

Quoted from `Evaluation Report/README.md` (unchecked):
- "The provided SVM model generated an accuracy score of 55% and a high recall score (96%) when buying but a low recall score (4%) when selling. This indicates the model performs extremely well when determining when to enter a position."
- "Adjusted the SMA input features: Increasing the short SMA window to 8 and decreasing the long SMA window to 20 months impacted the results a little bit."
- "Looking back at the models we can conclude that the Multilayer Perceptron (MLP) model performed the best because it generated an extremely high recall score (99%) for the buying target which indicates that the model will determine when to buy very well."
- "the strategy returns are much closer to the actual returns compared to the other models. This could indicate that the model is "learning" from the data and predicted quite accurately."

No profit figure is given anywhere; only plots.

## What matters for us

On Gate, across millions of backtested strategies, the average trade earns about $0.00 before fees, and fees plus the buy-sell gap cost about $0.23 per $100 trade; strategies we chose did no better than random entries on days they were not chosen on.

This repo cannot survive that: it charges no costs, it picks its settings on the test days, and its "best" model is "always long", which is buy-and-hold under another name. The report reads a 99% "buy" hit rate as skill, when it only means the model never says "sell". Its returns being "much closer to the actual returns" is that same fact.

Ideas worth testing on our crypto data: none. The useful lesson is the same as for ethansilvas: **a model's hit rate means nothing until it is compared with the share of the most common answer** (here 56.1% "up"), and a 99% "buy" recall paired with a 1% "sell" recall is a model that learned nothing.

## Doubts

- I did not run the notebook; only its saved outputs were read.
- The report's first numbers (96% / 4% recall for the "provided" SVC) are from a run with the course's original 4 / 100 bars and 3 months; the saved notebook shows only the 8 / 20-bar run (92% / 8%). The plots in `Plots/` were not opened.
- "20 months" in the report is 20 bars (about a week of this file's trading).
