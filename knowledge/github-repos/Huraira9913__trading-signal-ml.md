# Huraira9913/trading-signal-ml

- Link: https://github.com/Huraira9913/trading-signal-ml
- What it is: one short teaching script that trains a random forest to guess "up in 5 bars or not" on MADE-UP random prices; the regime detection, strategy mix, backtest and risk filters the README lists do not exist in the code.
- Stars, last push, licence: 0 stars, last push Oct 11, 2026, no licence.
- Markets and timeframes: none real. The script invents 2,000 hourly bars starting Jan 01, 2020 (`src/generate_signals.py`).
- Read: everything - `README.md`, `requirements.txt`, `src/generate_signals.py` (the only code file, 2,481 bytes).

## The strategies

**The data** (`generate_ohlcv`): a random walk. Each hourly return is drawn from a normal curve with average 0.0001 (0.01%) and spread 0.01 (1%), seed 42. Open equals close on every bar; high is up to 0.5% above, low up to 0.5% below; volume a random whole number from 1,000 to 9,999.

**The inputs** (`engineer_features`): 1-bar, 5-bar and 20-bar return; 20-bar wobble of 1-bar returns; distance of the close from its 50-bar average; volume z-score over 20 bars. (A 10-bar average is computed and never used.)

**The label:** 1 if the close 5 bars later is higher than now (`close.shift(-5) > close`), else 0.

**The model:** random forest, 100 trees, max depth 6, `random_state=42`.

**Entry, exit, stop, target, size, leverage:** none. The script prints a classification report and the feature importances and stops. No trade is ever simulated.

## How it tests them

- Split: first 75% of bars to train, last 25% to test, in time order (`train_test_split(test_size=0.25, shuffle=False)`).
- No settings are tuned, so the test part is not used to choose anything.
- No costs, no money, no buy-and-hold or random baseline - and since the prices are random by construction, there is nothing to beat.

## What it claims

Unchecked by us.

- `README.md` lists: "Market regime classification", "Ensemble of simple strategies (momentum, mean-reversion, breakout)", "Backtest-style evaluation", "Risk filters (spread, volatility, drawdown proxies)". None of these is in the code.
- `README.md`: "No live trading. Educational / research only."
- No result numbers are published.

## What matters for us

On Gate the average trade earns about $0.00 before fees and pays about $0.23 per $100 in fees and buy-sell gap, and chosen strategies did no better than random entries on unseen days. This repo says nothing about that: it never trades real prices, never charges a cost and has no baseline. On its own made-up data the honest answer is already known - a random walk cannot be predicted, so any accuracy above about 50% would be luck. Nothing here is worth testing on our crypto data; its six inputs are generic and already covered by our own signals.

## Doubts

- Bug, small: the last 5 rows have no future close, but `astype(int)` turns their "unknown" into 0 BEFORE `dropna()` runs, so they are kept and labelled "down".
- The 5-bar labels overlap and there is no gap between the training and test parts, so the last few training rows know the first test prices (tiny here, but the wrong habit).
- The README describes a much bigger project than the code; treat the README as a plan, not a description.
