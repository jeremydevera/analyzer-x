# KennethMartin06/ml-based-algorithmic-trading-signals

- Link: https://github.com/KennethMartin06/ml-based-algorithmic-trading-signals
- What it is: a student research project (Manipal Institute of Technology, 2026) that asks whether five machine-learning models can pick better "be in the market tomorrow or not" days than simply holding SPY, AAPL or MSFT, after costs.
- Stars, last push, licence: 0 stars, last push Oct 29, 2026, MIT.
- Markets and timeframes: US stocks only - SPY (S&P 500 fund), AAPL, MSFT - on 1-day bars from Yahoo Finance, Jan 01, 2010 to Dec 31, 2025 (`config.yaml`). Long only by default (no shorting).
- Read: `README.md` (the whole results block), `config.yaml`, `src/targets.py`, `src/backtester.py`, `src/baselines.py`, `results/metrics/feature_dictionary.csv`, `results/metrics/selected_thresholds.json`, and the full file list. NOT read: `src/experiment.py` (60 KB, the orchestration), `src/models.py`, `src/lstm_model.py`, `src/preprocessing.py`, `src/features.py`, the notebooks, the Streamlit app, the tests.

## The strategies

All five models share one recipe: predict tomorrow's direction, then be fully in the stock when the model is confident enough that it goes up, otherwise sit in cash.

**The label (what the models learn to predict)** - `src/targets.py`, `config.yaml` `target:`
- A decision is made after the close of day t. The order fills at the OPEN of day t+1 and the position is held to the OPEN of day t+2. The return it learns is `Open[t+2] / Open[t+1] - 1` (horizon 1 day, "next_open" convention).
- Three classes: Down if that return is below -0.1%, Neutral if it is between -0.1% and +0.1%, Up if above +0.1% (`neutral_threshold: 0.001`).
- A "close" version (`Close[t+1]/Close[t] - 1`) and a two-class Up/Down version are only run as side checks.

**The inputs: 42 features** (`results/metrics/feature_dictionary.csv`, windows from `config.yaml`)
- Returns: today's return, log return, returns of 1, 2, 3 and 5 days ago, total return over the last 5, 10, 20 and 60 days, overnight gap, open-to-close move, day's range (high-low)/close, where the close sits inside the day's range.
- Trend: close versus the 5, 10, 20 and 50-day simple averages and 5, 10, 20, 50-day exponential averages, the 10-day / 50-day average ratio, RSI 14 (Wilder), MACD 12/26 with a 9 signal line (all divided by price), Bollinger %B and width (20 days, 2 standard deviations).
- Volatility: ATR 14 / close, return wobble over 5, 20 and 60 days, 5/60 wobble ratio, today's move divided by 20-day wobble.
- Volume: volume versus its 5 and 20-day average, 20-day volume z-score.
- Regime: where the 20-day wobble ranks inside the last 252 days, close versus the 200-day average, 50-day above 200-day (yes/no), drop from the 252-day high.

**The five models** (`config.yaml` `models:`; every setting tuned by a purged time-ordered cross-validation with 4 folds inside the training years, scored by log loss)
1. Logistic regression: C tried at 0.001, 0.01, 0.1, 1.0; class weighting off or "balanced".
2. Random forest: 300 trees, sqrt of the features per split; depth 3, 6 or 10; at least 20 or 80 days per leaf; class weighting off or balanced.
3. XGBoost: subsample 0.8, column sample 0.8, min child weight 5, L2 1.0; depth 2, 3 or 5; learning rate 0.03 or 0.1; 100 or 300 trees; class weighting off or balanced.
4. LSTM (a neural net that reads the last 10 or 20 days in order): hidden size 16 or 32, 1 layer, dropout 0.2, learning rate 0.001, weight decay 0.0001, batch 64, up to 60 passes, stops after 8 passes with no improvement; tuned on the last 20% of the training years.
5. Ensemble: an equal-weight average of the members that did best on the validation years.

**Entry rule** (`src/backtester.py` `positions_from_probabilities`, `config.yaml` `signals:`)
- Be 100% long when the model's chance of "Up" is at least a threshold tau, otherwise cash.
- tau is picked from 0.30, 0.325, 0.35, 0.375, 0.40, 0.425, 0.45, 0.475, 0.50, 0.525, 0.55, 0.575, 0.60, 0.65 by the best Sharpe on the VALIDATION years only, and must keep the strategy in the market on at least 5% of validation days (`min_exposure: 0.05`).
- Chosen tau (`selected_thresholds.json`): SPY 0.425 / 0.30 / 0.375 / 0.375 / 0.30 (logistic, forest, XGBoost, LSTM, ensemble); AAPL 0.45 / 0.40 / 0.325 / 0.40 / 0.35; MSFT 0.375 / 0.30 / 0.40 / 0.30 / 0.425.

**Exit rule:** none of its own. Every day is a new decision; a trade lasts as long as the chance of Up stays at or above tau, and ends on the next open when it drops below. No stop, no target.

**Size and leverage:** all of the money, 1x (initial capital 100,000). A side check scales the position to aim for 15% yearly wobble using the last 20 days, never above 1x (`robustness: vol_target`).

**The rule-based comparisons** (`src/baselines.py`): buy and hold; a 10/50-day average crossover (long when the 10-day average is above the 50-day, else cash); "persistence" (long if today closed up); and, for accuracy only, always guessing the most common class.

## How it tests them

- **One clean split** (`config.yaml` `split:`, README): train Jan 2011 - Dec 2019, validation Jan 2020 - Dec 2021, test Jan 03, 2022 - Dec 29, 2025 (1,001 trading days per stock). "purge: true" drops any day whose 1-2 day label crosses a split line. The README says the test years are used once, at the end.
- **Walk-forward** (`walk_forward:`): every test year from 2016 to 2025, retrained each year on all earlier years, the year before the test year picks tau, 3 cross-validation folds, smaller grids.
- **Settings chosen on the test days?** No: tau and model settings come from training and validation years only (I read the config and the backtester; the code that enforces it is in `experiment.py`, not read).
- **Costs:** 10 basis points fee + 5 basis points slippage on every change of position (`fee_bps: 10`, `slippage_bps: 5`) = 0.15% each way, 0.30% a round trip. Charged on entry and exit only, from the equity at the time. A side test runs 0, 5, 10, 20 and 40 bps. No funding (these are stocks; holding overnight costs nothing in this model).
- **Baselines:** buy and hold, the 10/50 crossover and persistence all run through the SAME backtester. No random-entry baseline. A block bootstrap (2,000 draws, blocks of 20 days, 95%) tests whether "model Sharpe minus buy-and-hold Sharpe" is really above zero.

## What it claims

Quoted from `README.md` (results block, generated from `results/metrics/`). Unchecked by us.

- "Test period, 15 ML confidence-threshold strategies (models x tickers) vs buy-and-hold: Sharpe ratio higher for 4, lower for 6; cumulative return higher for 4, lower for 6; maximum drawdown smaller for 1, larger for 6 (the remainder are equal within 1e-09)."
- "5 of 15 ML strategies were invested on every test day and are therefore identical to buy-and-hold (Logistic Regression on SPY, Random Forest on SPY, Ensemble (soft vote) on SPY, Random Forest on MSFT, LSTM on MSFT): the threshold selected on the validation period kept them always long."
- "Block-bootstrap 95% intervals for Sharpe(strategy) - Sharpe(buy-and-hold) - ML strategies: 0 of 15 entirely above 0, 1 entirely below 0, 9 include 0, 5 identical to buy-and-hold (zero difference)"
- "Accuracy minus majority-class accuracy (block bootstrap): 0 of 15 model/ticker intervals lie entirely above 0, 1 entirely below 0, the rest include 0."
- "Walk-forward (2016-2025, annual retraining): 0 of 15 ML strategies had a higher out-of-sample Sharpe ratio than buy-and-hold (15 lower); 0 had a higher cumulative return."
- Example rows (test 2022-2025, after costs): SPY buy and hold "51.36%" Sharpe "0.66"; SPY XGBoost "45.16%" Sharpe "0.60" over 35 trades; AAPL random forest "61.28%" Sharpe "0.56" against buy and hold "52.42%" Sharpe "0.51". Walk-forward SPY buy and hold "301.95%" against the best model, random forest, "183.47%".
- Test accuracy sits at 0.472-0.510 against "majority-class accuracy 0.495" (SPY), 0.495 (AAPL), 0.502 (MSFT).

## What matters for us

On Gate we measured that across millions of backtested strategies the average trade earns about $0.00 before fees, while fees plus the buy-sell gap cost about $0.23 per $100 traded, and that chosen strategies did no better than random entries on days they were not chosen on.

This repo is the honest kind and its own answer agrees with ours: no edge. It charges 0.30% a round trip (a bit MORE than our 0.23%), it tests on years it never chose settings on, and it compares to buy and hold - and in the 10-year walk-forward none of its 15 model-stock pairs beat buy and hold, while its best-looking test results are mostly the model just staying long (5 of 15 were literally buy and hold). Nothing here would survive our numbers; there is no strategy in it to copy.

Worth borrowing as METHOD, not as a strategy:
1. The "is it just buy and hold?" check: count how many days the strategy is in the market, and call a strategy that is always in exactly what it is. On crypto a long-only model in a rising month can look clever for the same reason.
2. The block bootstrap of "strategy Sharpe minus baseline Sharpe" with 20-day blocks - a cheap second luck bar beside our random-entry runs.

## Doubts

- I did not read `src/experiment.py`, `src/models.py`, `src/lstm_model.py` or `src/preprocessing.py`, so the claim that test years are used only once rests on the config and README, not on reading the code that runs it.
- "win_rate" in the backtester is the share of IN-MARKET DAYS that made money, not trades; a separate `trade_win_rate` counts finished trades.
- The label is about the return from the next open to the open after; the features use the close of day t. That ordering is correct (no peek), and the README says tests check that features do not change when future rows are cut off (`tests/test_no_leakage.py`, not read).
- Stocks on daily bars with no funding and no gaps between sessions modelled beyond open-to-open; none of this transfers directly to 24-hour crypto.
