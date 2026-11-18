# AI4Finance-Foundation/FinRL

- Link: https://github.com/AI4Finance-Foundation/FinRL
- What it is: a teaching framework where a neural network "agent" learns by trial and error (reinforcement learning) to buy and sell a basket of stocks, plus ready-made trading "games" (environments) and wrappers around three learning libraries.
- Stars, last push, licence: 17,133 stars; last push Nov 18, 2026; MIT.
- Markets and timeframes: the main example trades the 30 Dow Jones stocks on 1-day bars (Yahoo Finance). There are also crypto environments (`finrl/meta/env_cryptocurrency_trading/`), a portfolio-weights environment and a paper-trading demo through Alpaca. The README lists Binance and CCXT as data sources down to 1-second / 1-minute bars, but the worked example is daily.
- Read: `README.md`, `finrl/config.py`, `finrl/meta/env_stock_trading/env_stocktrading.py` (the main trading game), `finrl/meta/env_stock_trading/env_stocktrading_stoploss.py` (header and reward), `finrl/meta/env_cryptocurrency_trading/env_multiple_crypto.py`, `finrl/meta/env_portfolio_allocation/env_portfolio.py` (step function), `finrl/meta/preprocessor/preprocessors.py` (turbulence index), `finrl/agents/stablebaselines3/models.py` (the agents and the ensemble), `finrl/agents/elegantrl/models.py` and `finrl/agents/rllib/models.py` (agent lists only), and the three 2026 example scripts `examples/FinRL_StockTrading_2026_1_data.py`, `_2_train.py`, `_3_Backtest.py`.

## The strategies

There is no hand-written trading rule. Every "strategy" is a neural network that is shown the market each day and outputs how many shares to buy or sell; it learns which outputs earn more by replaying the training years many times.

### The agents it offers
In `finrl/agents/stablebaselines3/models.py` the list is: A2C, DDPG, TD3, SAC, PPO, TQC and CrossQ (the last two added recently). The ElegantRL wrapper offers DDPG, TD3, SAC, PPO, A2C; the RLlib wrapper offers A2C, DDPG, TD3, SAC, PPO. A FastTD3 agent sits in `finrl/agents/fasttd3/`. **DQN is not in any of these lists** (it appears only in an old tutorial and in the notebook text).

Settings from `finrl/config.py`:
- A2C: 5 steps per update, entropy 0.01, learning rate 0.0007
- PPO: 2,048 steps per update, entropy 0.01, learning rate 0.00025, batch 64 (the 2026 training script uses batch 128)
- DDPG: batch 128, memory 50,000, learning rate 0.001
- TD3: batch 100, memory 1,000,000, learning rate 0.001
- SAC: batch 64 (128 in the training script), memory 100,000, learning rate 0.0001, starts learning after 100 steps, entropy "auto_0.1"
- TQC: like SAC, drops the top 2 quantiles per network
- CrossQ: batch 256, memory 1,000,000, learning rate 0.001
- The 2026 training script trains each of A2C, DDPG, PPO, TD3, SAC for only **20,000 steps** (`examples/FinRL_StockTrading_2026_2_train.py`).

### What the agent sees (the state)
From `env_stocktrading.py` and `finrl/config.py`, each day the agent gets one long list of numbers:
- cash on hand (starts at $1,000,000)
- today's closing price of each of the 30 stocks
- how many shares of each it holds
- for each stock, 8 indicators: MACD, Bollinger upper band, Bollinger lower band, RSI over 30 days, CCI over 30 days, DX over 30 days, 30-day average close, 60-day average close
- in the 2026 example, a 0/1 flag per stock saying whether it is a Dow member that day.
State size = 1 + 2 x 30 + (8 + 1) x 30 (`_2_train.py`).

### What it can do (the action)
One number per stock between -1 and +1, multiplied by `hmax` = 100, rounded down to whole shares: -100 = sell up to 100 shares, +100 = buy up to 100 shares. Sells are done first, then buys, and it can never spend more cash than it has. No short selling, no leverage. Trades fill at **the same day's close the agent just looked at** (`step()` in `env_stocktrading.py`).

### What it is rewarded for
The change in total account value (cash + shares x price) from one day to the next, multiplied by 0.0001 (`reward_scaling` = 1e-4). Costs are already subtracted from that value.

### The turbulence risk switch
`calculate_turbulence` in `preprocessors.py`: each day, how unusual today's returns across all 30 stocks are compared with the previous 252 trading days (a "Mahalanobis distance" — roughly, how many "standard surprises" away today is, taking the stocks' usual co-movement into account). In the trading game (`env_stocktrading.py`), when turbulence is at or above the threshold, **every stock is sold and no buying is allowed** until it drops back.
- In the 2026 backtest the switch is fed the **VIX** instead, with threshold **70** (`turbulence_threshold=70, risk_indicator_col="vix"` in `_3_Backtest.py`). VIX at 70 has happened only in extreme crashes (2008, March 2020), so it almost never fires.
- In the ensemble agent the threshold is the 99th percentile of training-period turbulence (`np.quantile(..., 0.99)`); code above it computes a 90%/100% adaptive version and then overwrites it.

### Other trading games in the repo
- **Stop-loss game** (`env_stocktrading_stoploss.py`): forced sale of a stock when its price falls under 0.9 x average buy price (`stoploss_penalty=0.9`, so a 10% stop); expects a profit of 2x the loss (`profit_loss_ratio=2`); cost 0.3% per side by default (`buy_cost_pct=3e-3`); reward = (total assets − penalties + bonus) / starting cash / days passed, with a penalty if cash falls under 10% of assets (`cash_penalty_proportion=0.1`).
- **Crypto game** (`env_multiple_crypto.py`): several coins, $1,000,000 start, 0.1% per side (`buy_cost_pct=1e-3`), reward = change in account value x 2^-16.
- **Portfolio game** (`env_portfolio.py`): the action is a set of weights (made to add to 1 with a softmax), the state is the 252-day covariance of returns plus indicators. **It accepts a `transaction_cost_pct` setting but never charges it** — the step function multiplies weights by returns and nothing else.

### The ensemble strategy (paper: ICAIF 2020)
`DRLEnsembleAgent.run_ensemble_strategy` in `models.py`: every 63 trading days (one quarter), train A2C, PPO, DDPG, SAC and TD3 on everything up to now, score each on the last 63 days (Sharpe ratio), and let the winner trade the next 63 days. Then roll forward and repeat.

### Position size, stop, target, leverage
Up to 100 shares per stock per day, whole shares only, no leverage, no stop or target in the main game (only the turbulence sell-everything switch).

## How it tests them

- **Split** (`finrl/config.py`, 2026 example): train **Jan 06, 2014 → Dec 31, 2025**, trade/test **Jan 01, 2026 → Mar 20, 2026** — only about 55 trading days of test, one window, one run per agent.
- The test days are not used to pick settings in the 2026 scripts (no tuning step at all). The ensemble version picks the model on the 63 days just before each trading window, which is fair.
- **Costs**: 0.1% per buy and 0.1% per sell (`buy_cost_list = sell_cost_list = [0.001]`), so 0.2% round trip. No bid-ask gap, no slippage, trades at the close it already saw. No funding (stocks, no leverage).
- **Baselines** (`_3_Backtest.py`): a point-in-time equal-weight Dow basket rebalanced daily, and the DJIA index itself (buy and hold). The README says the baselines are "Mean Variance Optimization (MVO) and the DJIA index", but the 2026 code uses equal-weight instead of MVO. No random-entry baseline.
- Only one seed per agent, no repeat runs.

## What it claims

From `README.md`: "This script loads the trained agents, runs them on the trading data, and compares their performance against two baselines: Mean Variance Optimization (MVO) and the DJIA index." The main README of the current version prints **no performance numbers**; the claims live in the papers it cites (not read). Saved results from older runs are in the FinRL-Tutorials notebooks (see that note). All unchecked.

## What matters for us

Our own measurement on Gate: across millions of backtested strategies the average trade earns about $0.00 before fees, and fees plus the buy-sell gap cost about $0.23 per $100 trade; chosen strategies did no better than random entries on days they were not chosen on.

Could FinRL's results survive that? **No evidence that they would.**
- Its cost (0.2% round trip) is close to ours in size, but it has no bid-ask gap and fills at a close the agent has already seen, which is easier than real life.
- It does test on unseen days, but on one short window (55 days in 2026) with one seed per agent — exactly the "one lucky run" pattern the Danny-397 study showed collapses when repeated across seeds.
- It compares against buy-and-hold and equal weight, never against random trades.
- The portfolio game charges no cost at all.

Ideas worth testing on our crypto data:
1. **The turbulence switch as a "stand aside" filter** — measure, for each day, how unusual the whole market's returns are versus the last 252 days, and switch every strategy off when it is in the top 1%. This is cheap to add on top of our existing rooms and can be tested on our stored trades without any new model: compare the trades opened on "turbulent" days with the rest.
2. **The ensemble's "pick the best of five on the last quarter" idea** is the same idea our own picker lab already tested (choose on recent results, judge on the next period) — our result was that it does not carry over, so it is not worth retesting as-is.

## Doubts

- I did not read the papers, the paper-trading code, the portfolio-optimisation agents (`finrl/agents/portfolio_optimization/`), FastTD3, or the NeurIPS 2018 notebooks inside this repo.
- `run_ensemble_strategy` loops over every name in `MODELS` (which now includes "tqc" and "crossq") but only receives settings for five agents, so `kwargs[model_name]` looks like it would stop with an error on current code. Not run, so unconfirmed.
- The README's baseline description (MVO) does not match the 2026 code (equal weight).
- Turbulence fed by VIX at 70 almost never triggers, so the "risk switch" is close to switched off in the main example.
- Filling at the same close the agent observed is not a look-ahead, but it ignores the gap between seeing a price and getting it.
