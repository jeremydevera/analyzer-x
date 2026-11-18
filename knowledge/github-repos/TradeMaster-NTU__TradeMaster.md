# TradeMaster-NTU/TradeMaster

- Link: https://github.com/TradeMaster-NTU/TradeMaster
- What it is: a research platform from Nanyang Technological University that packages about a dozen published self-teaching (reinforcement learning) trading methods, each with its own data set, trading "game", training loop and scorecard.
- Stars, last push, licence: 3,135 stars; last push Jun 04, 2025 (default branch `1.0.0`); Apache-2.0.
- Markets and timeframes: US stocks (Dow 30, S&P 500), China SSE 50, Hong Kong, currencies, Chinese futures (5-minute), BTC on 1-day bars (algorithmic trading) and BTC order-book snapshots (high-frequency trading and order execution).
- Read: `README.md`; configs `configs/high_frequency_trading/high_frequency_trading_BTC_dqn_dqn_adam_mse.py`, `configs/_base_/datasets/high_frequency_trading/BTC.py`, `configs/algorithmic_trading/algorithmic_trading_BTC_deepscalper_deepscalper_adam_mse.py`, `configs/_base_/datasets/algorithmic_trading/BTC.py`, `configs/_base_/datasets/order_execution/BTC.py` (top), `configs/_base_/datasets/portfolio_management/dj30.py` and `exchange.py`; code `trademaster/environments/high_frequency_trading/environment.py`, `trademaster/environments/algorithmic_trading/environment.py`, `trademaster/environments/portfolio_management/eiie_environment.py` (cost lines), `trademaster/agents/high_frequency_trading/ddqn.py` (outline), `trademaster/datasets/high_frequency_trading/dataset.py`, `trademaster/utils/utils.py` (`get_attr`), the two trainers' best-checkpoint logic; the saved outputs of `tutorial/Tutorial1_EIIE.ipynb`, `Tutorial2_DeepScalper.ipynb`, `Tutorial6_DDQN.ipynb`; first and last rows of `data/algorithmic_trading/BTC/train.csv`, `valid.csv`, `test.csv` and row counts of `data/high_frequency_trading/small_BTC/*.csv`.

## The strategies

TradeMaster groups its methods into task families. All are learning agents; none is a hand-written rule.

### Family 1 — Algorithmic (intraday-style) trading: DeepScalper (CIKM 2022)
Config `algorithmic_trading_BTC_deepscalper_deepscalper_adam_mse.py`, environment `environments/algorithmic_trading/environment.py`.
- **Data**: BTC **1-day** bars. Train Feb 23, 2014 → Aug 10, 2016 (900 days), validation Aug 16, 2019 → Mar 02, 2020 (200 days), test Apr 03, 2018 → Jun 01, 2019 (425 days) — note the **test period comes before the validation period**.
- **Inputs (state)**: the last 5 days (`backward_num_day = 5`) of 16 columns — high, low, open, close, adjusted close, and their "z" versions (each price relative to the close) and `zd_5` … `zd_30` (close relative to its 5- to 30-day averages) — plus current cash and BTC held. State size 82.
- **Action**: 3 choices — sell 1 BTC, do nothing, buy 1 BTC (`max_volume` 1, `action_dim=3`).
- **Reward ("hindsight")**: position x (tomorrow's price change + a weight x the price change over the next 5 days, `forward_num_day = 5`). Training sees the future on purpose; at test time the agent only acts on the past 5 days. An extra task predicts upcoming volatility.
- **Model**: DQN-style Q-network, layers 64 and 32, discount 0.9, batch 64, learning rate 0.001, 25% random exploration, memory 1,000,000, seed 42, 20 epochs (the tutorial ran 2).
- **Cost**: 0.1% per trade (`transaction_cost_pct` default 0.001 in the environment; the config does not set it).
- No stop, no target, no leverage limit beyond cash.

### Family 2 — High-frequency trading: Double DQN (from the EarnHFT line of work)
Config `high_frequency_trading_BTC_dqn_dqn_adam_mse.py`, environment `environments/high_frequency_trading/environment.py`.
- **Data**: BTC order-book snapshots — 5 levels of bid and ask prices and sizes per row (`small_BTC`: 25,000 validation rows, 5,000 test rows). Prices are around 23,088, i.e. BTC in late 2022 / early 2023. The step length is not written in the repo (the README's Binance data line says 1-minute, Apr 07 → Apr 19, 2021, which does not match these prices).
- **Inputs (state)**: 66 order-book and price features, e.g. volume imbalance, buy and sell spread, sizes at bid/ask levels 1–5, moving averages over 10/30/60 steps, rate of change, highs and lows, quantiles, counts of up and down steps, rolling beta and standard deviation (an "Alpha158"-style set).
- **Action**: 11 position levels from 0 to 0.01 BTC (`num_action=11`, `max_holding_number=0.01`) — long-only, tiny size.
- **Fills**: buys walk up the 5 ask levels and sells walk down the 5 bid levels, so the **bid-ask gap and book depth are paid** — the most realistic fill model in the platform.
- **Reward**: the change in value (cash + position at the best bid) after each step.
- **Teacher**: a dynamic-programming "perfect hindsight" action sequence is computed from the data and used only during training as an extra loss (KL divergence, weight 512); the test agent acts on the current state only.
- **Model**: Q-network width 16, 1% exploration, discount 0.99, batch 64 (512 in the trainer), learning rate 0.001, 10 epochs, memory 100,000, episodes of 14,400 steps.
- **Cost**: the config sets `transcation_cost=0` (misspelled), the dataset stores it as `transcation_cost`, but the environment reads `transaction_cost_pct` — which the dataset never has — so `get_attr` falls back to **0.005% per side** (`0.00005`). In other words the fee setting in the config is silently ignored.

### Family 3 — Order execution: ETEO and OPD (PD)
Configs `order_execution_BTC_eteo_eteo_adam_mse.py`, `order_execution_PD_BTC_pd_pd_adam_mse.py`. The task is to buy or sell a fixed amount (`target_order = 1`) cheaply over a time window (`length_keeping = 30`, `state_length = 10`) using BTC order-book data, not to predict direction. OPD trains a "teacher" that sees the future and a "student" that does not. Not read beyond the config.

### Family 4 — Portfolio management
- **EIIE** (Jiang et al. 2017), Dow 30, daily: a small convolution network looks at the last 10 days of each stock (`length_day = 10`) and outputs weights; reward = log of portfolio growth; cost 0.1% of the amount re-weighted (`transaction_cost_pct = 0.001`, charged in `eiie_environment.py` on the sum of weight changes). $100,000 start.
- **DeepTrader** (AAAI 2021), **SARL** (AAAI 2020; adds a price-trend predictor's output to the state), **Investor-Imitator** (KDD 2018; imitates rule-based investor types), all on Dow 30.
- **Classic agents** — PPO, A2C, SAC, DDPG, TD3, PG (via Ray RLlib) — on the "exchange" data set (currencies), 0.1% cost.
- **EarnMore** (`configs/earnmore/`): DQN, DDQN, SAC, PPO, TD3, DDPG and "mask" versions that can switch individual stocks off in a changing stock pool.

### Family 5 — Market dynamics modelling
Not a trading strategy: it labels stretches of history as up, down or sideways (e.g. `test_labeled_3_24_-0.15_0.15.csv`: 3 labels, 24-bar windows, ±15% thresholds) so any agent can be scored separately in each kind of market.

### Family 6 — FinAgent (LLM agent)
`configs/finagent/exp/trading*/` for AAPL, AMZN, GOOGL, MSFT, TSLA and **ETHUSD**: a large-language-model agent reading prices, news and tool outputs. Daily prices from FMP/Polygon/Yahoo. Not read beyond file names.

### Crypto and high-frequency examples, in short
DeepScalper on daily BTC; Double DQN on BTC order-book snapshots; ETEO/OPD order execution on BTC order books; FinAgent on ETH daily; the README also points to EarnHFT, MacroHFT and Market-GAN, which live in separate repos.

## How it tests them

- **Split**: fixed train / validation / test files per data set; each trainer saves a model after every epoch and keeps the epoch with the **best validation score** (`np.argmax(valid_score_list)` in the HFT trainer, best validation return rate in the algorithmic trainer), then runs it once on test. Test days are not used to choose, but there is one test window and one seed.
- **Costs**: 0.1% per trade in the daily games (DeepScalper, EIIE, the classic portfolio agents). In HFT the bid-ask gap is paid by walking the book, plus 0.005% per side. No funding anywhere, no slippage model in the daily games.
- **Baselines**: DeepScalper's environment computes a buy-and-hold curve (`buy_and_hold_asset`); the platform's scorecard (PRIDE-Star, PRUDEX-Compass) compares methods with each other. **No random-entry baseline** in the code I read.

## What it claims

The README claims, word for word: "TradeMaster is a first-of-its kind, best-in-class __open-source platform__ for __quantitative trading (QT)__ empowered by __reinforcement learning (RL)__" and "efficient implementations of over 13 novel RL-based trading algorithms" with "systematic evaluation toolkits with 6 axes and 17 measures". It prints no performance table.

Saved tutorial outputs (the authors' own runs, unchecked):
- `tutorial/Tutorial2_DeepScalper.ipynb` (BTC daily, 2 epochs): training "| 967.324329%  |   1.621369 |", validation "| -199.576611% |   0.292613  | 15.006834% | 289.010033%  |", then test of the best checkpoint "| 218.177594%  |   1.966325  | 2.131242%  |  29.503340%  |" (total return, Sharpe, volatility, max drawdown). A −199.6% return and a 289% drawdown are impossible for a cash account, which points to accounting that allows negative holdings.
- `tutorial/Tutorial6_DDQN.ipynb` (BTC order book): validation episodes "-6.387074%" and "-3.991204%"; test "|  0.479027%   | 0.009575%  |  0.570660%   |" (total return, volatility, max drawdown).
- `tutorial/Tutorial1_EIIE.ipynb` (Dow 30): test "|  14.641799%  |   1.304315  | 0.718882%  |  6.743468%   |".

## What matters for us

Our own measurement on Gate: the average trade earns about $0.00 before fees, fees plus the buy-sell gap cost about $0.23 per $100 trade, and chosen strategies did no better than random entries on unseen days.

Could these results survive that? **Not shown.** Every saved result is one seed on one test window, with no random baseline. The headline crypto example (DeepScalper +218%) lost on validation, tests on an earlier period than its validation set, uses daily bars with only 3 choices, and its numbers (−199.6% return) show the accounting is not trustworthy. The high-frequency example is the most realistic about the bid-ask gap — it walks a real 5-level order book — but its fee setting is silently ignored (0.005% per side instead of what the config says), its size is 0.01 BTC, and its best result is +0.48% on 5,000 test steps.

Ideas worth testing on our crypto data:
1. **Walk the order book for every fill**, as the HFT environment does. We already do this with our per-minute recorded books; this repo confirms that is the right model, and that without it high-frequency results are meaningless.
2. **Score each strategy separately in up, down and sideways stretches** (the market-dynamics labelling: e.g. 24-bar windows, ±15% thresholds). For our rooms, splitting each strategy's trades by the market's state when they opened would show whether a "winner" only wins in one kind of market — the problem the Thomas-lcb repo hit.

## Doubts

- I did not read the order-execution, DeepTrader, SARL, Investor-Imitator, EarnMore or FinAgent code, the evaluation toolkit, or the papers.
- The README's data table does not match the files: BTC is labelled "Foreign Exchange", the Binance order-book line says Apr 2021 1-minute while the HFT data sits around $23,088.
- DeepScalper's split puts test (Apr 2018 → Jun 2019) between train and validation, so "test" is not the newest data.
- The fee typo (`transcation_cost` vs `transaction_cost_pct`) is from reading the code, not from running it.
