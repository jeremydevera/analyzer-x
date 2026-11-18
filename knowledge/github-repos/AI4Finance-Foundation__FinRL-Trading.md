# AI4Finance-Foundation/FinRL-Trading

- Link: https://github.com/AI4Finance-Foundation/FinRL-Trading
- What it is: "FinRL-X", the successor to FinRL — a stock-trading system where every strategy outputs a list of target portfolio weights, which then go through one backtester and one broker connection (Alpaca), so the backtest and live trading use the same weights.
- Stars, last push, licence: 3,953 stars; last push Sep 18, 2026; Apache-2.0.
- Markets and timeframes: US stocks and ETFs only (S&P 500, NASDAQ-100, a 28-stock rotation list plus SPY/QQQ/IAU/XLU/XLV fallbacks). Daily bars; rebalanced quarterly (ML stock picking), weekly (rotation) or monthly (time-series momentum signal), with daily risk checks in the rotation strategy. No crypto.
- Read: `README.md`, `ML_STOCK_SELECTION.md`, `src/strategies/AdaptiveRotationConf_v1.2.2.yaml`, `src/strategies/adaptive_rotation/market_regime.py` (slow regime), `group_strength.py` and `intra_group_ranking.py` (headers), `walk_forward.py` (header), `src/strategies/run_adaptive_rotation_strategy.py` (how the backtest loop is driven), `src/strategies/ml_strategy.py` (model list and the train/validate/predict split), `src/strategies/tsmomsignal.py`, `src/strategies/fundamental_portfolio_drl.py` and `src/strategies/rl_model.py` (the DRL allocator), `src/backtest/backtest_engine.py` (cost settings).

## The strategies

### 1. ML stock selection (quarterly) — `src/strategies/ml_strategy.py`, `ML_STOCK_SELECTION.md`
- Universe: S&P 500 members **as they were on each date** (point-in-time list `data/sp500_historical_constituents.csv`), so delisted and removed names are kept — this is done properly. (The README's Use Case 2 says NASDAQ-100; the ML guide uses the S&P 500.)
- Inputs: 52 quarterly fundamental factors (valuation such as PE, PS, PB; profitability such as ROE and margins; liquidity; debt; efficiency; cash flow; per-share values; dividends; solvency), price momentum features, and sector flags. Data from the FMP API.
- Label: `y_return = ln(next trade_price / this trade_price)` — the log return from one trade date to the next, where the trade date is when the quarterly report is already public (for a Sep 30, 2025 quarter, the trade date is Dec 01, 2025). The guide insists on this so the model never "buys" before the report exists.
- Models (two versions): `ml_strategy.py` fits Random Forest (200 trees, `max_features='sqrt'`), Gradient Boosting (250 trees, depth 3), and LightGBM (500 trees) / XGBoost (500 trees, depth 4) if installed; the bucket version (`ML_STOCK_SELECTION.md`) fits seven per sector group — Random Forest (200 trees, depth 8), XGBoost and LightGBM (200 trees, depth 6, learning rate 0.05), HistGradientBoosting, ExtraTrees, Ridge (alpha 1.0) and a stack of the top 3.
- Choosing the model: train on all quarters except the last 4, check prediction error (MSE) on those last 4 quarters, keep the model with the lowest error, predict the current quarter (`_rolling_train_single_date`, `test_quarters=4`). In rolling mode each date uses the 16 quarters before it plus the 4 validation quarters (`train_quarters=16`).
- Entry/exit: buy the stocks whose predicted return is in the top 25% (`top_quantile=0.75`), hold until the next quarter's rebalance, then replace. Weights: equal, minimum-variance (covariance over 8 quarters or 252 days), or the DRL allocator below.
- No stop, no target, no leverage.

### 2. DRL portfolio allocator — `src/strategies/fundamental_portfolio_drl.py`, `rl_model.py`
- Takes the stocks picked above and lets FinRL's portfolio game (`StockPortfolioEnv`) choose their weights.
- State: 252-day covariance of returns plus indicators; action: one weight per stock, made to add to 1.
- Agents: A2C (50,000 steps), PPO (80,000), DDPG (50,000), plus TD3 (30,000) and SAC (50,000); training window up to 1,095 days (3 years) before the trade date, test window 365 days.
- Cost: `transaction_cost_pct: 0.001` is passed in — **but FinRL's `StockPortfolioEnv` never charges it** (see the FinRL note), so the allocator learns as if rebalancing were free.

### 3. Adaptive multi-asset rotation (weekly) — `src/strategies/adaptive_rotation/`, config `AdaptiveRotationConf_v1.2.2.yaml`
- Universe: four groups of 7 names each — growth tech (AAPL, MSFT, NVDA, META, AMZN, GOOGL, TSLA), cyclical (JPM, GS, HD, CAT, UNP, DE, AXP), real assets (XOM, CVX, COP, FCX, BHP, GLD, SLV), defensive (JNJ, PG, KO, UNH, NEE, DUK, PEP). (The README says three groups; the config has four.) Fallback when nothing qualifies: SPY, QQQ, IAU, XLU, XLV, equal weight.
- **Market regime ("slow")**, `market_regime.py`: three yes/no warnings on weekly data — S&P 500 below its 26-week average; S&P 500 down 10% or more from its 13-week high; VIX unusually high (robust z-score of 3.0 or more versus the last 3 years). Count the warnings: 0 = risk on (no cap, 0% cash), 1 = neutral (each group capped at 70%, at least 10% cash), 2 = risk off (cap 50%, at least 30% cash). A state must hold 2 weeks before it switches.
- **Fast risk-off**: if prices fall 3% in 3 days, or VIX z-score reaches 3.0 (or its change reaches 3.5), cap groups at 30% and hold at least 50% cash for 10 days; stops are tightened by 0.7x.
- **Group choice**: each group's risk-adjusted return (information ratio against QQQ) over 12 weeks, with a trend filter; at most 2 groups active.
- **Stock choice inside a group**: "residual momentum" — the stock's return minus its group's return — turned into a robust z-score over 12 weeks (capped at 20); top 3 per group considered, up to 2 held per group. An "exception" lets a name in early if its z-score is 2.5+ in 2 of the last 4 weeks, or 3.5+ once with a 12-week return over 1.5x QQQ's; after leaving, a 6-week wait and a 1.5x stricter bar to come back.
- Weights: equal, leftover to cash.
- **Stops (checked daily)**: −5% from entry (absolute) and −10% from the high since entry (trailing); after a stop, that name is blocked for 20 days. No target, no leverage.

### 4. Time-series momentum signal (monthly) — `src/strategies/tsmomsignal.py`
From Moskowitz et al. (2012): each month, the return from 12 months ago to 1 month ago (`ret_12m = P(t-1m) / P(t-12m) - 1`). Above +10% = long (+1), below −10% = short (−1), in between = flat (`neutral_band=0.10`, `lookback_months=12`).

### 5. Allocation baselines (README "Use Case 1")
Equal weight (1/N), mean-variance, minimum variance, the DRL allocator, and a KAMA (Kaufman adaptive moving average) trend timing overlay — all producing the same weight list. I did not read the KAMA code.

## How it tests them

- **ML picking**: a fair train → validation → predict order per quarter, and the point-in-time S&P 500 list avoids picking only today's survivors. But the validation quarters choose the model and the README results are then shown on the same history.
- **Rotation**: "walk-forward-safe" here means each week's decision only uses data up to that week (`walk_forward.py`, `as_of` dates). It does **not** mean the settings were chosen on one period and judged on another: the config is at version v1.2.2 with hand-picked thresholds and a hand-picked list of stocks, and the README's backtest covers Jan 2018 → Oct 2025 with no held-out years mentioned.
- **The hand-picked list is chosen with hindsight**: NVDA, META, TSLA, GOOGL, AMZN in the growth group are the biggest winners of exactly the period being tested.
- **Costs**: the backtester (`backtest_engine.py`) defaults to `transaction_cost: float = 0.001  # 0.1% per trade`, with an optional market-impact cost model; no bid-ask gap by default. I could not confirm which cost the README's results used — `run_adaptive_rotation_strategy.py` only writes weights.
- **Baselines**: QQQ and SPY buy-and-hold. No random-picks baseline.
- **Paper trading**: Oct 2025 → Mar 2026 on Alpaca's paper account — real prices going forward, but about 5 months, one run.

## What it claims

From `README.md` (unchecked):

Historical backtest, "Jan 2018 – Oct 2025":

| Metric | Rolling Strategy | Adaptive Rotation | QQQ | SPY |
|:-------|:---:|:---:|:---:|:---:|
| Cumulative Return | 5.98x | 4.80x | 4.02x | 2.80x |
| Annualized Return | 25.85% | 22.32% | 19.56% | 14.14% |
| **Sharpe Ratio** | 0.93 | **1.10** | 0.81 | 0.72 |
| Max Drawdown | -38.95% | **-21.46%** | -35.12% | -33.72% |
| Win Rate | 54.36% | 54.77% | 56.25% | 55.28% |

Paper trading, "Oct 2025 – Mar 2026", "Ensemble of Rolling Selection + Adaptive Rotation deployed on Alpaca paper trading": "Total Return | **+19.76%** | -2.51% | -4.79%" (strategy, SPY, QQQ), "**Sharpe Ratio** | **1.96** | -0.55 | -0.73", "Max Drawdown | -12.22% | -5.35% | -7.88%".

Also: "Quarterly selection of top-25% NASDAQ-100 stocks via ML fundamental scoring, combined with DRL-based portfolio allocation. Strict no-lookahead semantics prevent data leakage."

## What matters for us

Our own measurement on Gate: the average trade earns about $0.00 before fees, fees plus the buy-sell gap cost about $0.23 per $100 trade, and chosen strategies did no better than random entries on unseen days.

Could these results survive that? **Partly unknown, and the main backtest is not convincing.** These strategies trade rarely (quarterly or weekly, a handful of names), so a 0.1% cost per trade matters far less to them than to our 15-minute to 1-day crypto trades — that is the real lesson. But the 2018–2025 backtest uses a stock list and thresholds picked with knowledge of that same period, has no held-out years, and is compared only with buy-and-hold, never with random picks from the same list. The five months of paper trading are real forward prices, but five months of one run is too short to separate skill from luck. Nothing here is crypto or futures, so funding never comes up.

Ideas worth testing on our crypto data:
1. **Trade less often.** The rotation rebalances weekly and the picker quarterly; our measured loss is the cost of many short trades. A weekly "hold the top 2–3 coins by 12-week return relative to BTC, else cash" rotation, using the same three-warning regime count (BTC below its 26-week average, BTC down 10% from its 13-week high, volatility unusually high) to raise cash, could be backtested on our daily candles with our real costs and a random-picks baseline. This is close to Backtest v3's strength family, so check those verdicts first.
2. **The −5% fixed / −10% trailing stop with a 20-day block after a stop** is a simple exit rule to try on our trend trades.

## Doubts

- I did not read the notebooks (`examples/*.ipynb`), the paper (arXiv 2603.21330), the live trading code, `ml_bucket_selection.py`, `group_selection_by_gics.py`, `risk_manager.py`, `portfolio_builder.py` or the KAMA timing.
- The README and the config disagree on the number of rotation groups (3 vs 4) and the README and the ML guide disagree on the universe (NASDAQ-100 vs S&P 500).
- Which cost model produced the README tables is not stated in the code I read.
- The DRL allocator inherits FinRL's portfolio game, which ignores its cost setting.
