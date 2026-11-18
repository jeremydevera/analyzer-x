# AI4Finance-Foundation/FinRL-Tutorials

- Link: https://github.com/AI4Finance-Foundation/FinRL-Tutorials
- What it is: a collection of step-by-step notebooks that run the FinRL library (see `AI4Finance-Foundation__FinRL.md`) on different markets — the strategies are FinRL's learning agents, set up in different ways.
- Stars, last push, licence: 1,235 stars; last push Mar 28, 2025; MIT.
- Markets and timeframes: mostly the 30 Dow Jones stocks on 1-day bars; also 10 large coins on 1-day bars (Binance), BTC on 1-hour bars, GBP/USD forex on 1-day bars, China A-shares on 1-day bars.
- Read: `README.md`, `1-Introduction/README.md`, the Python copies `2-Advance/FinRL_Ensemble_StockTrading_ICAIF_2020.py`, `3-Practical/FinRL_MultiCrypto_Trading.py`, `1-Introduction/Stock_NeurIPS2018_SB3.py`, `1-Introduction/FinRL_PortfolioAllocation_NeurIPS_2020.py`, `1-Introduction/Stock_Fundamental.py` (settings only), `1-Introduction/ForexTrading_Demo.py`, `1-Introduction/China_A_share_market_tushare.py` (settings only), `2-Advance/Crypto_Feature_Importance.py`, `2-Advance/execution_optimizing.py` (top only); the notebooks `2-Advance/FinRL_Ensemble_StockTrading_ICAIF_2020.ipynb`, `1-Introduction/Stock_NeurIPS2018_SB3.ipynb`, `3-Practical/FinRL_MultiCrypto_Trading.ipynb` and `4-Optimization/FinRL_HyperparameterTuning_using_Optuna_basic.ipynb` (code and saved outputs); `DQN-DDPG_Stock_Trading/README.md`, `run.py` and its `gym/envs/rlstock/rlstock_env.py` / `rlstock_testenv.py`; and the FinRL library files they call (listed in the FinRL note).

## The strategies

Every tutorial below uses FinRL's stock game unless said otherwise: the agent sees cash, prices, holdings and indicators each day, outputs how many shares to buy or sell (up to `hmax`), is rewarded for the daily change in account value, and trades at the close it just saw. Details are in the FinRL note.

### 1. Ensemble strategy (ICAIF 2020) — `2-Advance/FinRL_Ensemble_StockTrading_ICAIF_2020.ipynb`
- Market: Dow 30, daily. Notebook dates: train Jan 01, 2010 → Oct 01, 2021; validation + trading Oct 01, 2021 → Mar 01, 2023 (the `.py` copy uses Apr 01, 2009 → Jan 01, 2021 and Jan 01, 2021 → Jun 01, 2022).
- Inputs: FinRL's 8 indicators (MACD, Bollinger upper and lower, RSI 30, CCI 30, DX 30, 30- and 60-day averages) plus the turbulence index.
- Models: A2C (5 steps, entropy 0.005, learning rate 0.0007), PPO (2,048 steps, entropy 0.01, learning rate 0.00025, batch 128), DDPG (memory 10,000, learning rate 0.0005, batch 64); **10,000 training steps each**.
- Decision: every 63 trading days, train all three on all data so far, score each on the previous 63 days by Sharpe ratio, and the one with the best score trades the next 63 days. Turbulence switch: sell everything and stop buying when turbulence is above the 99th percentile of the training years.
- Size: up to 100 shares per stock per day, $1,000,000 start, no leverage, no stop or target.

### 2. Five single agents (NeurIPS 2018 workshop) — `1-Introduction/Stock_NeurIPS2018_SB3.ipynb` and the 3-part `Stock_NeurIPS2018/` notebooks
- Dow 30, daily. Train Jan 01, 2009 → Jul 01, 2020; trade Jul 01, 2020 → Oct 31, 2021.
- A2C, DDPG, PPO, TD3, SAC, 50,000 training steps each; trading uses the VIX switch at 70.
- Compared with a mean-variance portfolio and the DJIA.

### 3. Portfolio allocation (NeurIPS 2020) — `1-Introduction/FinRL_PortfolioAllocation_NeurIPS_2020.py`
- Dow 30, daily, Jan 01, 2009 → Jan 01, 2019. Train Jan 01, 2009 → Jan 01, 2018; trade Jan 01, 2018 → Jan 01, 2019.
- State: the 252-day covariance matrix of returns plus indicators. Action: one weight per stock, made to add to 1 (softmax), rebalanced daily.
- A2C 50,000 steps, PPO 80,000, DDPG 50,000, SAC 50,000, TD3 30,000.
- Reward: the new portfolio value. **The cost setting (0.1%) is passed in but the environment never charges it** (`env_portfolio.py`, see FinRL note), so every rebalance is free.

### 4. Explainable portfolio allocation — `2-Advance/FinRL_PortfolioAllocation_Explainable_DRL.ipynb`
Same allocation game; the README says it explains the agent's choices with "feature weights of a trained DRL agent", a "histogram of correlation coefficient" and "Z-statistics". Not read in detail.

### 5. Fundamentals + technicals — `1-Introduction/Stock_Fundamental.py`
Dow 30, daily, train Jan 01, 2009 → Jan 01, 2019, trade Jan 01, 2019 → Jan 01, 2021. Adds quarterly ratios to the state (operating margin, net margin, ROA = last 3 quarters' net income / total assets, ROE, EPS, BPS, DPS and others). Same agents and game.

### 6. Multi-crypto trading — `3-Practical/FinRL_MultiCrypto_Trading.py`
- Coins: BTC, ETH, ADA, BNB, XRP, SOL, DOT, DOGE, AVAX, UNI (all against USDT), **1-day bars** from Binance.
- Train Oct 01, 2020 → Nov 08, 2021; test Nov 08, 2021 → Jan 22, 2022 (about 75 days).
- Inputs: MACD, RSI, CCI, DX.
- Model: PPO from ElegantRL, learning rate 2^-15, batch 2,048, discount 0.99, network width 512, trained for 50,000 steps.
- Game: FinRL's crypto environment — $1,000,000 start, 0.1% per buy and per sell, reward = change in account value.
- Baselines: buy-and-hold BTC and an equal-weight basket of the 10 coins.

### 7. BTC feature importance — `2-Advance/Crypto_Feature_Importance.py`
Not an RL agent. BTC/USDT 1-hour bars (dates in the code read Jan 01, 2015 → Jan 03, 2020, which is older than Binance's listing; I did not check what data it really gets).
- Label ("triple barrier"): from each bar, a target at price x (1 + 2 x volatility), a stop at price x (1 − 2 x volatility) and a time limit of 25 bars; volatility = 100-bar exponential standard deviation of returns. Label 2 if the target was touched within the 25 bars, else 0 if the stop was touched, else 1.
- Features: RSI 14, MACD 12/26/9, CCI 14, DX 14, plus price and volume columns (12 inputs).
- Model: a small 4-layer neural network classifier, 100 epochs.
- Feature importance: shuffle one feature at a time and see how much accuracy drops.

### 8. Forex demo — `1-Introduction/ForexTrading_Demo.py`
GBP/USD, daily, Jan 01, 2017 → Jan 01, 2018. PPO, learning rate 2^-15, batch 2,048, 1,000,000 steps. **It trains and then plays on the same data** — there is no test period.

### 9. China A-shares — `1-Introduction/China_A_share_market_tushare.py`
Daily, train Jan 01, 2015 → Aug 01, 2019, trade Aug 01, 2019 → Jan 03, 2020. DDPG (10,000 steps) and A2C (50,000 steps). Costs 0.00687% to buy and 0.10687% to sell (the stamp duty is on sells), up to 1,000 shares per trade. Baseline: the CSI 300 index (code 399300).

### 10. Order execution (liquidation) — `2-Advance/execution_optimizing.py`
Copied from an ICML 2019 paper: two DDPG agents each sell a block of shares over 60 trades in a simulated market (the Almgren-Chriss model), risk aversion 1e-6, 1,300 practice episodes; the score is "implementation shortfall" (how much worse than the arrival price they sold). This is about selling cheaply, not about predicting direction.

### 11. DQN-DDPG stock trading (the original 2018 code) — `DQN-DDPG_Stock_Trading/`
OpenAI Baselines DDPG on 28 Dow stocks, daily. Train 2009 → 2015 (`datadate > 20090000 and < 20160000`), test from 2016 (`> 20160000`). Action: buy or sell up to 5 shares of each of 28 stocks; start $10,000; reward = change in account value. **No trading cost at all** in `rlstock_env.py`. The README's "Compare to our result" is an image, not numbers.

### 12. Hyperparameter tuning — `4-Optimization/FinRL_HyperparameterTuning_using_Optuna_basic.ipynb`
DDPG on Dow 30, 30 Optuna trials of 50,000 steps each, picking the settings with the best Sharpe ratio. Train Jan 01, 2009 → Jul 01, 2020; "trade" May 01, 2020 → Oct 01, 2021. **The objective scores each trial on `e_trade_gym` — the trade period itself** — so the test days choose the settings, and the train and trade windows overlap by two months (May 01 → Jul 01, 2020). The other tuning notebooks (Ray Tune, population-based training, Weights & Biases) and the vectorbt notebooks were not read.

### 13. Others (not read beyond file names)
`FinRL_Compare_ElegantRL_RLlib_Stablebaseline3` (same task through three libraries), `FinRL_Meta_Integrate_Trends_data_to_DOW_Jones` (adds Google Trends data), `MultiCrypto_Trading` in 2-Advance (same as #6), `nas100_gpu_podracer.py`, `stock_jq.py`, `stock_qc.ipynb`, `stock_wrds.ipynb`, `FinRL_PaperTrading_Demo` (Alpaca paper account), `FinRL_Tensor_Environment`, the 5-Others docker and cash-penalty notebooks.

## How it tests them

- **Splits**: a single fixed date cut per tutorial (train older, trade newer). The ensemble rolls forward every 63 days, which is closer to walk-forward. Each run is one seed.
- **Test days used for choosing?** In the ensemble, no (the model is picked on the 63 days before trading). In the Optuna notebook, **yes** — settings are chosen by their score on the trade period. In the forex demo there are no test days at all.
- **Costs**: 0.1% per buy and 0.1% per sell in the stock and crypto games (0.2% round trip), no bid-ask gap, no slippage, no funding. **Zero** in the portfolio game (cost ignored) and in the DQN-DDPG code.
- **Baselines**: DJIA index buy-and-hold in most stock tutorials, plus mean-variance in #2; buy-and-hold BTC and an equal-weight basket in #6. **No random-entry baseline anywhere.**

## What it claims

Saved outputs inside the notebooks (these are the authors' own runs, unchecked):

- Ensemble notebook, `2-Advance/FinRL_Ensemble_StockTrading_ICAIF_2020.ipynb`: the ensemble printed `Sharpe Ratio:  -0.11910800246459344`, `Annual return -0.039389`, `Max drawdown -0.173731`; the DJIA over the same days printed `Annual return -0.094324`, `Sharpe ratio -0.402058`. Its model-choice table shows every agent's validation Sharpe negative in three of four quarters (for example A2C `-0.302721`, PPO `-0.232303`, DDPG `-0.168003` for Apr 04 → Jul 06, 2022). So the ensemble lost 3.9% a year, less than the index lost.
- Five-agent notebook, `1-Introduction/Stock_NeurIPS2018_SB3.ipynb`, account values on Feb 27, 2023 from a $1,000,000 start: a2c `1.030205e+06`, ddpg `9.877202e+05`, td3 `1.018708e+06`, ppo `9.499940e+05`, sac `9.207091e+05`, mean var `9.135293e+05`, dji `9.581264e+05`. Two agents ended up, three down; the DJIA baseline's `Annual return -0.034876`, `Sharpe ratio -0.105351`.
- Optuna notebook: tuned DDPG `Annual return 0.311337`, `Sharpe ratio 1.968012`; untuned DDPG `Annual return 0.325768`, `Sharpe ratio 1.757594` — tuned on the very period it is reported on.
- Tutorial README: the ensemble "uses an ensemble strategy to combine multiple DRL agents to form an adaptive one to improve the robustness."

## What matters for us

Our own measurement on Gate: the average trade earns about $0.00 before fees, fees plus the buy-sell gap cost about $0.23 per $100 trade, and chosen strategies did no better than random entries on unseen days.

Could these results survive that? **No.** The authors' own saved runs already show it: the ensemble lost 3.9% a year on its unseen quarters, and of five agents two ended slightly up and three down over 16 months. Wherever a tutorial looks good, there is a reason to distrust it — the Optuna result was tuned on its own test days, the portfolio game charges no cost, the forex demo has no test days, and the DQN-DDPG code charges nothing. Costs are 0.2% round trip with no bid-ask gap (ours is about 0.23% including the gap), and there is never a random-entry baseline, so nothing here shows an edge over luck.

Ideas worth testing on our crypto data:
1. **The triple-barrier labels from #7** (target and stop set at 2x recent volatility, give up after 25 bars) are a cleaner way to score an entry than a fixed TP/SL percent: the stop widens in wild markets and tightens in calm ones. We could re-run one of our existing signal families with volatility-scaled TP and SL and compare against the same family at fixed percentages, after fees.
2. **The ensemble's quarterly "best of N on the last 63 days" choice** is the same idea our picker lab tested and found does not carry forward — not worth retesting.

## Doubts

- I read Python copies and saved outputs, not every notebook cell; notebooks in 4-Optimization (except the basic Optuna one) and 5-Others were not read.
- The `.py` ensemble script calls `run_ensemble_strategy` with three agents' settings, while the current FinRL function takes five, so the tutorials look out of date with the library.
- #7's code checks "target touched" before "stop touched" without checking which came first, so a bar range that touched both is labelled a win — a bias toward wins.
- #7 splits its data with `train_test_split(..., test_size=0.2, stratify=y, random_state=69)`, a random shuffle, on overlapping 25-bar labels, so test rows sit next to training rows in time — its accuracy is likely too high.
- The crypto tutorial's dates suggest about 75 test days on daily bars — 75 decisions is far too few to judge anything.
