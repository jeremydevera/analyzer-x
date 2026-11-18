# Danny-397/RL-for-Crypto-and-stocks-

- Link: https://github.com/Danny-397/RL-for-Crypto-and-stocks-
- What it is: a research study that builds a self-taught trading agent (PPO, written from scratch) for stocks and crypto and then tries hard to prove its own results wrong — and concludes the agent has no edge over buy-and-hold; the same code does help with hedging an option.
- Stars, last push, licence: 0 stars; last push Nov 14, 2026; MIT.
- Markets and timeframes: 10 US stocks (AAPL, AMZN, GOOGL, JNJ, JPM, MSFT, NVDA and three more in `data/SNAPSHOT.json`) and 6 coins (ADA, BTC, ETH, LTC, SOL, XRP against USD, from Yahoo), **1-day bars**, data through Aug 28, 2026 (coins from as early as Sep 17, 2014). Part 2 uses SPY daily closes and VIX for option hedging.
- Read: `README.md`, `guide/findings.md`, `RESULTS.md` (setup, §3, §5, §5c, §10 summary), `rl_trader/envs/base_env.py`, `rl_trader/envs/crypto_env.py`, `rl_trader/envs/stock_env.py`, `rl_trader/config/training_config.py`, `rl_trader/data/data_loader.py`, `rl_trader/evaluation/baselines.py` (function list), `data/SNAPSHOT.json`, `docs/preregistration/2026-11-13-rigor.results.md`.

## The strategies

### 1. The PPO trading agent (one coin or stock at a time) — `rl_trader/envs/base_env.py`, `rl_trader/config/training_config.py`
- **What it sees (state)**: the last 20 days (`window_size: int = 20`) of 28 features, plus 3 account numbers (position as a share of equity, cash as a share of starting money, equity relative to the start). Features (`data_loader.py`): returns over 1, 5, 20, 60 and 120 days and the daily log return; price versus its 10, 30, 50 and 100-day simple averages and 12-day exponential average; RSI 14; MACD 12/26/9 and its signal line (divided by price); Bollinger %B (20 days, 2 standard deviations); position inside the 20-day high-low range (Donchian); 10-day volatility, ATR 14 / price, and a 60-day z-score of volatility; 10-day versus 60-day volatility; distance below the 120-day high; high-low range / price; volume change and a 20-day volume z-score; and **market context**: 5- and 20-day return relative to SPY (stocks) or BTC (coins), the market's distance from its 50-day average, and its 20-day return. All scaled using the training period's average and spread only.
- **What it can do (action)**: one number from −1 to +1 = the target position as a share of equity (+1 fully long, 0 cash, −1 fully short). It rebalances to that target every day. Shorting is allowed; maximum 1x equity, so no leverage. The episode stops if equity falls under 20% of the start (`bankruptcy_threshold: float = 0.2`).
- **Reward** (`_compute_reward`): default = 100 x the day's log return − 0.05 x how far below its equity high it is (0.08 for crypto) − 0.0005 x turnover. An alternative is the "differential Sharpe ratio" (Moody & Saffell, 1998), which rewards each day's contribution to the running Sharpe ratio (adaptation rate 0.04).
- **Model** (`PPOConfig`): learning rate 0.0003, discount 0.99, GAE 0.95, clip 0.2, value weight 0.5, entropy 0.01, gradient clip 0.5, 10 passes per update, batch 256, two hidden layers of 128, 2,048 steps per update; the study's headline runs use 150,000 training steps (200,000 for the single published run). An LSTM version also exists. Since v2.3.0 seven implementation details were "repaired" to match Stable-Baselines3.
- **Training trick**: "domain randomization" — training on many simulated price paths so the agent cannot memorise one history (`reload()`); the study's own ablation says this is what stops it from memorising.
- **Entry and exit**: no separate rule — the daily target position is the decision. No stop or target.
- **Costs** (`stock_config`, `crypto_config`): stocks 0.05% fee + 0.03% slippage on every traded amount; crypto **0.10% fee + 0.10% slippage**, so 0.2% each time the position changes by its full size and 0.4% for a full in-and-out. No funding (the crypto class notes it as a future "extension point").
- Trades fill at the close of the day the agent just saw, and the position is marked at the next close.

### 2. Comparison strategies in the same environment — `rl_trader/evaluation/baselines.py`, `RESULTS.md` §3
Buy-and-hold; moving-average crossover (10-day versus 30-day); flat (cash only); random positions; and two simple supervised models on the same 28 features (ridge regression on the next day's return, logistic regression on its direction).

### 3. Portfolio allocator — `rl_trader/envs/portfolio_env.py` (not read)
The same PPO choosing long/short weights across the whole basket under a gross-exposure limit, compared with equal weight and a cross-sectional momentum factor. The guide says it "lands in the same place as the single-asset agent".

### 4. Option hedging (Part 2) — `rl_trader/hedging/` (not read in code)
Having sold a one-month option, each day the agent picks how many SPY shares to hold against it, paying a cost on every trade. Trained only on simulated prices, tested on 237 one-month episodes of real SPY data (Jan 2007 → Sep 2026) against Black-Scholes delta hedging and a tuned "no-trade band" around delta.

## How it tests them

- **Split**: chronological — train on the older 60% of each series, test on the newest 40% (`RESULTS.md` setup table; the code default in `prepare_market_data` is 70/15/15). Since v2.3.0 all coins are cut on **one calendar date** (`split="common"`); before that each coin was cut on its own history, which let some coins train on days that were test days for others — the study found and reported this leak itself.
- **Walk-forward**: §5c retrains BTC from scratch on an expanding window and tests 4 consecutive blocks (Aug 10, 2019 → Jun 17, 2026), 5 seeds each.
- **Test days used for choosing?** No: the predictions were written down before the runs ("pre-registered", `docs/preregistration/`), seeds are fixed (10 seeds, then 30), and a hyperparameter sweep is run at the full budget and reported, not cherry-picked.
- **Costs**: yes, on every change of position (above). No bid-ask gap beyond the slippage term, no funding.
- **Baselines**: buy-and-hold, random, flat, MA crossover, two supervised models, Stable-Baselines3's PPO and SAC, and a "surrogate" test where the price history is shuffled to destroy any pattern. Statistics: bootstrap confidence ranges across seeds, a paired permutation test across tickers, Holm correction for many tests.

## What it claims

From `README.md` (unchecked by me, but this repo checks itself unusually hard):

- "No edge. Trained on ten real stocks and six coins and scored on history it never saw, the agent loses to buy-and-hold on stocks (p = 0.002, in all 300 runs of a 30-seed follow-up). On crypto it trails on five of six coins, which six coins cannot make significant (p = 0.19 at 30 seeds)."
- Held-out result over 10 seeds: "Crypto | **−44.6%** `[−56%, −33%]` | +10% | indistinguishable (p = 0.22)" and "Stock | **−26.5%** `[−35%, −17%]` | +240% | significantly **worse** (p = 0.0021)".
- "An earlier build published a +275% crypto run (commit `d4c0ef9`); the multi-seed tests are what showed it was luck."
- "Its long-or-short calls match the next day's move as often as a coin flip, and it pays to reverse them most days."
- Single published run (`RESULTS.md` §3), crypto mean over 6 coins: "PPO agent | −34.4%", "Buy & hold | +10.1%", "MA crossover | −6.8%", "Random | −64.5%".
- Walk-forward on BTC (`RESULTS.md` §5c): agent −21.6%, −39.4%, −35.9%, −24.5% in the four test blocks against buy-and-hold +375.8%, −65.7%, +229.7%, +1.7% — it beat buy-and-hold only in the crash block, by losing less.
- Part 2: the hedging agent "beats a tuned textbook hedge at high costs on 19 years of real SPY data" — at 1% trading cost it beat the tuned band in "10/10 (p = 0.0021)" seeds; at no cost it did not (4/10).

## What matters for us

Our own measurement on Gate: the average trade earns about $0.00 before fees, fees plus the buy-sell gap cost about $0.23 per $100 trade, and chosen strategies did no better than random entries on unseen days.

This repo **agrees with us**, by a completely separate route. It charges realistic costs (its crypto cost, 0.4% for a full in-and-out, is higher than ours), tests on unseen years with one calendar cut, repeats across 10–30 seeds, and compares with buy-and-hold and random. Its answer is the same as ours: no edge, and a single good run (+275%) was luck. The one place where random did worse than the agent (−64.5% vs −34.4% on crypto) is because random flips its position every day and pays the cost every day — which is our "fees are the whole loss" result again.

Ideas worth taking from it:
1. **Its testing method, not its strategy.** Repeat every promising result across many independent seeds/starts, cut every coin on the same calendar date, and write the prediction down before running. Our own "chosen on older days, judged on unseen days" already matches this; the extra pieces are many seeds and the shuffled-history ("surrogate") check, which tells you whether any pattern exists at all.
2. **The turnover penalty in the reward** (−0.0005 x amount traded) and its finding that the agent "pays to reverse them most days" support our trade-less-often direction: any rule we test should be scored on how often it flips.
3. The hedging finding (learning to trade less when costs are high) is not a direction signal, so it is not a strategy for us.

## Doubts

- I did not read the portfolio environment, the hedging code, the LSTM version, the server, `RESULTS.md` sections 6–9 and 10a–10h in full, or the paper.
- Daily bars only — nothing here tests 15-minute or 1-hour trading, which is where our costs bite hardest.
- Costs are a flat percentage (fee + slippage); there is no per-minute order book and no funding, even for shorts on crypto.
- The code default split (70/15/15) differs from the 60/40 the results describe; the study's tools pass the split explicitly, which I did not check.
