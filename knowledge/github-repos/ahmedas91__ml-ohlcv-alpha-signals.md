# ahmedas91/ml-ohlcv-alpha-signals

- Link: https://github.com/ahmedas91/ml-ohlcv-alpha-signals
- What it is: a University of Chicago class project (summer 2026) that ranks about 1,000 US stocks every day by predicted 1-day and 5-day return, using 105 price-and-volume features in an elastic-net model, and finds only a tiny, unsteady edge before costs.
- Stars, last push, licence: 0 stars, last push Sep 30, 2026, no licence.
- Markets and timeframes: US stocks (CRSP daily data, about 1,000 names a day; the data file is licensed and NOT in the repo), 1-day bars; test years 2013-2025.
- Read: `README.md`, `run_models.py`, `src/data.py`, `src/validation.py`, `src/evaluation.py`, `src/scorecard.py`, `src/signals/baseline.py`, `src/signals/classic_features.py`, the first ~400 lines of `src/models.py`, the settings at the top of `src/prune.py`, `outputs/scorecard/scorecard_table.csv`, `outputs/report/model_comparison.csv`, `outputs/report/stress_years.csv`, and the abstract, results, limits and conclusion of `Report/main.tex`. NOT read: `src/signals/alphas.py` (the 90 formulas), `notebook.ipynb`, the ablation and audit scripts, `Report/main.pdf`.

## The strategies

This is a cross-sectional strategy: it does not decide "buy this stock or not"; each day it SORTS all stocks by predicted return, buys the top tenth and shorts the bottom tenth.

**The target** (`src/data.py` `build_forward_return_targets`): `close[t+h] / close[t] - 1` for h = 1 and 5 trading days, blank if the stock left the data for more than 10 days in between.

**The inputs** (about 105 columns)
- Baseline, 3 features (`src/signals/baseline.py`): 1-day reversal = minus the last 1-day return; 5-day reversal = minus the last 5-day return; momentum 12-1 = return from 252 days ago to 21 days ago. Plus their 3 pairwise products, each built from per-day ranks scaled to -1..1.
- 90 of Kakushadze's "101 Formulaic Alphas" (`src/signals/alphas.py`, not read; the paper is in `refs/`).
- 15 classic features (`src/signals/classic_features.py`): close/open - 1; (high - low)/close; overnight gap open/previous close - 1; close location (close - low)/(high - low + 0.01); 21-day return; 63-day return; 6-1 momentum (126 days ago to 21 days ago); 21-day return wobble; Parkinson high-low wobble over 21 days; wobble of that wobble over 63 days; volume / 21-day average volume - 1; rank of 21-day average dollar volume; Amihud illiquidity over 21 days; distance from the 252-day high; biggest 1-day return in 21 days.
- Every feature is turned into its per-day rank, scaled to -1..1, with missing values set to 0 (`src/models.py` `rank_normalize_features`).
- Pruning (`src/prune.py`): drop features present on under 20% of rows, then greedily drop one of any pair correlated above 0.7, measured only on 2001-2010, years never used for validation or testing: 103 kept features down to 85 (`Report/main.tex`).

**Four model setups x 2 horizons = 8 runs** (`src/models.py`): (a) the 3 baseline features, (b) baseline + its 3 products, (c) the 85 pruned features, (d) the full pool.

**The model:** elastic net (a linear model that shrinks weak features to zero). L1 share tried at 0.1, 0.3, 0.5, 0.7, 0.9, 1.0; strength tried at 30 values from the point where every weight is zero down to 1/10,000 of it, worked out from the training data each year; the pair with the lowest error on the validation year wins, then the model is refitted on training + validation (`max_iter=2000`, `tol=1e-3`). The scorecard also lists XGBoost runs, but the script that made them is not in the repo.

**Entry and exit** (`src/scorecard.py` `build_decile_portfolio`, `Report/main.tex` equation `ls`)
- Each formation day, sort the stocks into ten equal groups by predicted return. Long the top group, short the bottom group, equal weight: return = (top group - bottom group) / 2.
- 1-day horizon: rebuilt every day. 5-day: rebuilt every 5th trading day of each test year, held 5 days.
- No stop, no target, no leverage beyond the 50/50 long-short.

## How it tests them

- **Walk-forward by year** (`src/validation.py`, `run_models.py`): for each test year 2013-2025, train on every year before the validation year, validate on the 1 year just before the test year, test on that year. The last 5 trading days of the training block and of the validation block are cut off (`PURGE_DAYS = 5`) so a 5-day target cannot reach into the next block. Features are built from 2011 on, with 2 extra years for look-back.
- **Test days never choose settings:** the elastic-net settings are picked on the validation year only (`src/models.py`); pruning used only 2001-2010.
- **Costs: NONE.** Every return and Sharpe is "gross of costs" (`Report/main.tex`: "Returns are gross of costs"; "transaction costs and turnover are absent").
- **Baseline:** the simple 3-feature reversal/momentum model is the yardstick the 100-feature models must beat. No random or buy-and-hold baseline; the score that matters is the information coefficient (IC: the per-day rank correlation between predicted and actual return, averaged per year, where 0 = no skill).

## What it claims

Unchecked by us.

- `Report/main.tex` abstract: "The baseline and its interaction extension attain the largest average rank correlations, while the technical specifications produce greater separation between the extreme deciles. Pruning 103 covered features to 85 has little effect on out-of-sample results. Predictability is small, varies materially across years, and is reported before transaction costs."
- `Report/main.tex` Table "Out-of-sample comparison, 2013--2025" (gross): Baseline 1d active IC 0.0102, spread 0.27 bp a day, Sharpe 0.08; Baseline 5d 0.0052, -1.90 bp, -0.12; Pruned technicals 1d 0.0079, 1.56 bp, 0.63; Pruned technicals 5d 0.0041, 1.78 bp, 0.12; Full technicals 1d 0.0081, 1.52 bp, 0.61; Full technicals 5d 0.0042, 1.67 bp, 0.11. ("Active" = the years the validation did not pick an all-zero model: 8 to 10 of 13.)
- `Report/main.tex` limits: "Daily decile rebalancing can make a statistically positive spread economically unusable."
- `Report/main.tex` conclusion: "These weak and time-varying results support the use of simple benchmarks, yearly validation, and multiple evaluation metrics when studying technical signals."

## What matters for us

On Gate the average trade earns about $0.00 before fees and pays about $0.23 per $100 in fees and buy-sell gap, and chosen strategies did no better than random entries on unseen days. This repo agrees in its own way: tested honestly on unseen years, its best daily long-short makes about 1.56 basis points (0.0156%) a day BEFORE costs. Our round trip costs 23 basis points, so rebuilding the book daily would cost roughly 15 times what it earns. It does not charge costs, so its results could not survive ours; its testing method is sound.

Ideas worth testing on our crypto data:
1. **Short-term reversal across coins**: each day (or 4 hours), rank every coin by its last 1-day and 5-day return, long the biggest losers and short the biggest winners. Measure the spread between the top and bottom tenth BEFORE costs first; only if it is many times 0.23% per rebuild is it worth a full test. Hold longer (5 days) to pay the cost less often.
2. **IC per year, not one pooled number**: report each window's rank correlation separately, so one lucky stretch cannot carry a result - a stricter version of our "chosen on older days, judged on unseen" bar.

## Doubts

- The data is not in the repo, so nothing here can be re-run or checked; every number rests on their saved summary files.
- The authors note some features use the closing price of day t while the target starts at that same close, so the portfolio returns assume trading exactly at the close ("same-close execution"); the IC is the fairer number.
- The XGBoost rows in `scorecard_table.csv` come from a script that is not in the repo.
- `src/evaluation.py` is a leftover marked "Decile Sharpe is still not implemented"; the real metrics live in `src/scorecard.py`.
- Universe membership by date "cannot be independently verified from this repository" (their words), so survivorship is possible.
