# ebrahimpichka/DeepRL-trade

- Link: https://github.com/ebrahimpichka/DeepRL-trade
- What it is: two reinforcement-learning traders (PPO and DQN, from stable-baselines3) that each day choose long, flat or short Google stock, compared with buying and holding.
- Stars, last push, licence: 21 stars, last push Feb 13, 2026, no licence.
- Markets and timeframes: GOOG only, **daily** bars. Original notebook: Tiingo data Jan 01, 2014 to Aug 01, 2022. Newer config (`configs/default.yaml`): yfinance, Jan 01, 2016 to Dec 01, 2025.
- Read: `README.md`, `configs/default.yaml`, `configs/ppo_goog.yaml`, `configs/dqn_goog.yaml`, `src/envs/trading_env.py`, `src/agents/dqn.py`, `src/agents/ppo.py`, `src/agents/networks.py`, `src/evaluation/testing.py`, `src/evaluation/metrics.py`, `scripts/train.py`, `scripts/evaluate.py`, and the code cells and saved outputs of `notebooks/DeepRL_trader.ipynb`. Not read: `scripts/visualize.py`, `src/visualization/plots.py`, `thesis-pdf/Thesis.pdf`.

## The strategies

Two agents, one environment.

- Inputs (notebook cell 12; `trading_env.py` `_process_data`): 7 daily features — adjusted volume, 5-, 10- and 21-day % return of the adjusted close, stochastic RSI (TA-Lib `STOCHRSI`, second output), MACD signal line (TA-Lib `MACD`, second output), ATR (TA-Lib default 14). Each is turned into a rolling z-score using only earlier days (notebook: 30-day window, shifted one day; config: `window: 180`). The agent sees the last 10 days (notebook) or 30 days (`window_size: 30`) of these, plus 2 numbers: share of the account in cash and in the position.
- Actions (`trading_env.py`): 0 = short, 1 = flat, 2 = long — always **the whole account**. A trade happens only when the direction changes; the fill is at that day's **open**.
- Timing: the features end the day before the decision day, and the trade is at the next day's open, so no look-ahead in the environment.
- Reward: daily % change of the account (`simple_return`), or the "differential Sharpe ratio" with `eta: 0.02` (config default `type: "dsr"`).
- Cost: commission 0.1% of the traded value in the notebook (`commission_rate=0.001`); **0.5%** in the newer config (`commission_rate: 0.005`). No slippage, no short-borrow fee.
- PPO (`ppo_goog.yaml`, `networks.py`): learning rate 0.0001, 1,000 steps per update, batch 512, 20 epochs, gamma 0.99, GAE 0.95, clip 0.2; separate policy and value networks, each 512 → 64 units with layer norm, ReLU, dropout 0.1; 300,000 steps (notebook: 256 → 64, dropout 0.07, 700,000 steps).
- DQN (`dqn_goog.yaml`): learning rate 0.0001, replay buffer 1,000,000, learning starts after 50,000 steps, batch 1,024, tau 0.99, gamma 0.99, a gradient step every 2,048 steps, target update every 5,000, exploration from 100% down to 2% over the first 20%; 500,000 steps (notebook: batch 512, every 1,000 steps, 700,000 steps).
- Stop / target / leverage: none; 1x, all-in, long or short.

## How it tests them

- Split by date: first 80% of days train, last 20% test (`train_ratio: 0.8`; in the notebook train ends Dec 07, 2020, test runs to Aug 01, 2022).
- **The test days choose the model.** `EvalCallback(test_env, best_model_save_path=...)` scores the agent on the test environment every 5,000 steps and keeps the best one, and that "best_model.zip" is then evaluated on the same test environment (`scripts/train.py`, notebook cells 38-41, 59-63).
- Evaluation: 500 runs on the test period, each starting on a random day and all ending on the same last day; the averages and 95% / 99% intervals are taken over those 500 overlapping runs (`testing.py`).
- Costs: commission only (0.1% or 0.5%); no slippage; stock, so no funding.
- Baseline: **buy-and-hold** on the same test window is computed (`bnh_perf_stat`). No random-action agent.

## What it claims

Quoted from the notebook (unchecked):
- Introduction: "it is shown that the proposed deep reinforcement learning approach performs better than the buy and hold benchmark in terms of risk assessment criteria and portfolio return."
- PPO, one full pass over the test period (cell 43): "'total_profit_percentage': 0.60911, 'buy_and_hold': 0.3322" (+60.9% vs +33.2%).
- DQN, one full pass (cell 67): "'total_profit_percentage': 1.17634, 'buy_and_hold': 0.3322" (+117.6% vs +33.2%).
- PPO, 500 runs (cell 41): "Annual return 0.457401", "Sharpe ratio 1.386655", "Max drawdown -0.202732".
- DQN, 500 runs (cell 63): "Annual return 0.525238", "Sharpe ratio 2.039023", "Max drawdown -0.117017".
- PPO on its own training days (cell 45): "'total_profit_percentage': 752.25708" — $100,000 turned into $75,325,707.89.

## What matters for us

Our own measurement on Gate: the average trade earns about $0.00 before fees, fees plus the buy-sell gap cost about $0.23 per $100 trade, and chosen strategies did no better than random entries on days they were not chosen on.

These results would not survive that. It does charge a commission (0.1% a trade, roughly our size) and it does compare with buy-and-hold, but the **test days pick which saved model is reported**, so the test is not unseen; there is one stock, one test window of about 20 months, and no random-action agent. The 75,000% gain on training days against +61% to +118% on test days is a sign of heavy over-fitting, and the 500 "runs" all share the same days, so their tight intervals overstate certainty.

Idea worth testing, low priority: **the differential Sharpe ratio as the score** a learner optimises (it rewards steady gains over lucky spikes) — relevant only if we ever train a model rather than pick rules. Nothing here is a crypto entry rule worth copying.

## Doubts

- The repo cannot run as committed: `scripts/train.py` imports `src.data.source` and `src.data.preprocess`, but there is no `src/data` folder in the repo (the README lists it).
- The notebook's results come from the older notebook code (Tiingo, 2014-2022, 0.1% commission, 10-day window); the newer scripts and configs (yfinance, 2016-2025, 0.5% commission, 30-day window, DSR reward) have no published results.
- The interval columns in the notebook are labelled "3sigma" while the script calls them "1.5sigma".
- The thesis PDF was not read.
