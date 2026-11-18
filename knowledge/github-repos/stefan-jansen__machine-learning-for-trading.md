# stefan-jansen/machine-learning-for-trading

- Link: https://github.com/stefan-jansen/machine-learning-for-trading
- What it is: the code for the book "Machine Learning for Trading, 3rd Edition" — 27 chapters plus nine "case studies" that each carry one market from raw data through labels, features, models, backtest, costs, risk and a final untouched "holdout" test.
- Stars, last push, licence: 21,891 stars, last push Nov 18, 2026, MIT (code only; one data file is AlgoSeek's).
- Markets and timeframes: nine case studies (from `case_studies/README.md`): 100 ETFs daily; **19 Binance crypto perpetuals every 8 hours** (the one closest to us); NASDAQ-100 stocks 15-minute; S&P 500 stocks + options daily; ~2,500 US firms monthly; 20 FX pairs daily; 30 CME futures daily; S&P 500 straddles daily; ~3,200 US stocks daily. Chapter demos also use BTC/USDT daily.
- Read: root `README.md`, `case_studies/README.md`, the chapter READMEs of 06-09, 11-19, 20 and 21; `case_studies/crypto_perps_funding/README.md`, `config/setup.yaml`, `config/backtest/base.yaml`, `config/training/fwd_ret_24h.yaml`, `funding_backtest.py`, parts of `02_labels.py`; the saved outputs of `case_studies/crypto_perps_funding/19_strategy_analysis.ipynb`, `20_strategy_synthesis/08_recommendations.ipynb` and `20_strategy_synthesis/06_cost_survival.ipynb`; parts of `06_strategy_definition/01_where_ideas_come_from.py` and `16_strategy_simulation/03_single_asset_vectorbt.py`. The repo has 2,065 files; I did not read most notebooks line by line.

## The strategies

The book is not one strategy. It is one research pipeline run on nine markets, with each chapter adding a model family or a strategy step. Chapter by chapter (folder name first):

- `06_strategy_definition` — **12-1 month momentum** on the 100 ETFs: return from 12 months ago to 1 month ago (`LOOKBACK = 12`, `SKIP = 1`), sorted into 5 buckets each month (`N_QUANTILES = 5`, at least `MIN_NAMES = 30` ETFs), comparing next-month returns per bucket (`01_where_ideas_come_from.py`). An exploration, not a traded backtest. Also walk-forward cross-validation rules (purging, embargo).
- `07_defining_the_learning_task` — how labels are made: plain forward return, **triple-barrier** (target / stop / time limit), trend-scanning; barrier widths set from the real "maximum favorable / adverse excursion" of past trades; signal checked with the information coefficient (the rank correlation between prediction and next return); multiple-testing control (Benjamini-Hochberg false-discovery rate and the Deflated Sharpe Ratio).
- `08_financial_features` — feature families: momentum, reversal, volatility, liquidity, microstructure, cross-instrument (term structure, basis), fundamentals, macro and calendar.
- `09_model_based_features` — features from fitted models: Kalman filter, Fourier/wavelet, ARIMA, GARCH volatility, HAR volatility, hidden-Markov regimes, Wasserstein regimes, fractional differencing.
- `10_text_feature_engineering` — word2vec, FinBERT sentiment, news-to-return signals.
- `11_ml_pipeline` — the baseline every model must beat: OLS, **Ridge, Lasso, Elastic Net** for return prediction, logistic regression for direction; SHAP; conformal intervals; a first ML backtest.
- `12_gradient_boosting` — **XGBoost, LightGBM, CatBoost** (plus TabPFN, TabM) predicting returns, tuned with Optuna; the README says gradient boosting is "the strongest tabular model in most case studies".
- `13_dl_time_series` — MLP, 1D-CNN, **LSTM**, GRU, N-BEATS, Linear / D-Linear / N-Linear, PatchTST, iTransformer, TCN, TSMixer, Mamba, image-CNNs on Gramian-angular fields, and zero-shot Chronos / TinyTimeMixer. The README of `11_library_landscape` says of a simple "last value" forecast: "it is the one comparison that is like-for-like, and it wins."
- `14_latent_factors` — PCA eigenportfolios, IPCA, RP-PCA, conditional autoencoder, adversarial stochastic-discount-factor network, supervised autoencoder.
- `15_causal_estimation` — Double Machine Learning on (a) ETF 6-1 momentum vs 21-day return and (b) the crypto funding premium z-score vs 8-hour return; a causal forest for position sizing.
- `16_strategy_simulation` — **RSI mean reversion on BTC/USDT daily**: 14-day RSI, buy when the previous close's RSI < 30, sell when > 70, 95% of cash, 0.10% fee + 0.05% slippage per fill (`03_single_asset_vectorbt.py`, labelled "full sample, in-sample"); engine comparisons; the Deflated Sharpe Ratio, Rademacher Anti-Serum and White's Reality Check; cost-sensitivity sweeps.
- `17_portfolio_construction` — equal weight, mean-variance, Ledoit-Wolf, risk parity, HRP, Kelly, conformal-interval sizing, an LSTM that outputs weights trained on a Sharpe loss, DeePM.
- `18_transaction_costs` — spread estimation from OHLCV, market impact, VWAP/TWAP, Almgren-Chriss.
- `19_risk_management` — fixed stops, trailing stops, volatility exits, MAE/MFE stop calibration, an ML exit model, kill switches.
- `20_strategy_synthesis` — reads all nine case studies' results (see "What it claims").
- `21_rl_execution_hedging` — DQN, PPO, SAC used for **order execution, market making and hedging**, not for picking direction.

### The crypto case study in detail (`case_studies/crypto_perps_funding/`)

- Universe: 19 Binance USDT perpetuals (AAVE, ADA, APT, ATOM, AVAX, BNB, BTC, COMP, DOGE, DOT, ETH, INJ, LINK, MKR, NEAR, SOL, SUI, UNI, XRP), 2020-2025 (`config/setup.yaml`).
- Decision clock: every 8 hours, just before each funding settlement; trades at the settlement time.
- Labels (`02_labels.py`, `setup.yaml`): `fwd_ret_8h` (close-to-close return over the next 8 hours, the main one), `fwd_ret_24h`, `fwd_dir_8h` (up/down) and `fwd_dir_8h_3c` (3 classes).
- Inputs: 39 features from the **premium index** (perp vs spot) and **funding**: premium momentum over 1, 3, 9, 21, 42, 90 bars; premium z-score over 21 and 42 bars (7 and 14 days); premium percentile over 21/42/90 bars; premium RSI over 3/9 bars; price volatility 21/42 bars; funding z-score 42 bars; funding half-life; 7-day funding cash flow; cross-sectional rank of each coin's premium vs the other 18; plus 5 model features (GARCH volatility refit every 21 bars, 2-state hidden-Markov regime refit every 63 bars). One bar = 8 hours.
- Models (`config/training/fwd_ret_24h.yaml`): OLS, Ridge at 11 strengths (0.001 to 10,000,000), Lasso and Elastic Net at 8 strengths each, 15 LightGBM settings (default / 7 / 15 / 31 / 63 leaves × 3 loss types), NLinear, LSTM with 64 hidden units on 60-bar sequences, TabM in 3 sizes, a causal DML model.
- Entry rule: each 8 hours rank the coins by the prediction; go **long the top k and short the bottom k** (k = 3, 5 or 10) or long/short top and bottom fifth (`setup.yaml` `top_k_grid`, `quantile_grid`).
- Exit: at the next rebalance; then 14 exit overlays were tried — stop losses 3%, 5%, 10%, 15%; trailing stops 1%, 2%, 3%, 5%, 10%, 15%, 20%; time exits after 10, 20, 40 bars.
- Sizing: equal weight, then score-weighted, inverse volatility, risk parity, Ledoit-Wolf mean-variance, HRP and conformal-weighted. Starting cash $100,000. No leverage setting is stated; the synthesis notebook says the holdout drawdown "reflects the leverage the allocator took".
- The selected configuration (`19_strategy_analysis.ipynb` output): label `fwd_ret_24h`, family linear, model `enet_f0.03` (Elastic Net), 2,746 trades.

## How it tests them

- **Walk-forward with a frozen holdout.** Crypto: 2 folds, each 2 years of training then 1 year of validation; **2024-01-01 to 2025-12-31 is a holdout** that is only opened once, after the configuration is frozen (`setup.yaml` `evaluation`). Settings are chosen on the validation years, never the holdout.
- **Costs**: commission 0.04% + slippage 0.01% per side (`config/backtest/base.yaml`); the README names "2 bps maker and 4 bps taker". **Funding is charged** at every 8-hour settlement on the position held (`funding_backtest.py`). Fills are "same bar" at the price of the decision bar.
- **Selection correction**: the final pick is reported with a bootstrap interval, the Deflated Sharpe Ratio (corrects for having picked the best of many), a Rademacher bound and the minimum track record length.
- **Baselines**: an equal-weight benchmark per label (`benchmark/*.parquet`); the cost chapter sweeps costs from 0 to 50 bps per leg (`cost_grid_bps`). No random-entry baseline, but the deflated Sharpe plays the same role ("what the best of 2,807 worthless strategies would have produced").

## What it claims

All numbers below are the repo's own saved notebook outputs; I did not re-run anything — unchecked.

From `case_studies/crypto_perps_funding/19_strategy_analysis.ipynb`:
- "2807 candidates across 4 labels"
- Selected: `fwd_ret_24h`, linear, `enet_f0.03`, validation Sharpe `1.667939`, max drawdown `-0.468988`, total return `4.159751`, trades `2746.0`.
- "deflated Sharpe, raw K -0.130747"; "Sharpe, 95% interval low 0.422264"; "Rademacher-adjusted Sharpe 1.181596".
- Money breakdown: funding P&L `21932.255608`, total commission `95653.496717`, total slippage `23913.379225`.
- Holdout: "holdout ee7c119e1009: Sharpe -0.832 over 731 periods, CAGR -44.8%, max drawdown -82.26%".
- "Every uncorrected statistic here says the selection is real, and the correction says it is not."
- "The largest of 2,807 draws lands near 1.6 whether or not any of them has an edge, so 1.57 is what this search returns when nothing works."

From `20_strategy_synthesis/08_recommendations.ipynb`:
- Funnel: "Holdout SR > 0 █████░░░░ 5/9 dropped: Crypto, NASDAQ-100, US Equities".
- "Crypto: Holdout Sharpe -0.832, interval [-2.185, +0.394] spans zero"; "US Equities: Val SR → Holdout SR = -2.29".
- Holdout Sharpes of the others: ETFs 1.31, FX Pairs 0.43, S&P 500 Eq+Opt 1.32, US Firms 2.74, CME Futures 0.32, S&P 500 Options 0.59; of these, FX, S&P 500 Eq+Opt, CME and S&P 500 Options are marked "Statistically unresolved" (interval spans zero). Only ETFs and US Firms pass every gate with no exclusion.

From `20_strategy_synthesis/06_cost_survival.ipynb`: Crypto gross Sharpe `2.065`, assumed cost `3.0` bps per leg, net Sharpe `1.921`, **breakeven `19.4` bps per leg** — on the validation years, before the holdout lost money.

## What matters for us

Our own measurement on Gate: the average trade earns about $0.00 before fees, fees plus the buy-sell gap cost about $0.23 per $100 trade, and chosen strategies did no better than random entries on days they were not chosen on.

This repo is the most honest one in the batch, and its crypto result **agrees with ours**. It charges fees, slippage and funding, chooses on validation years only, and opens an untouched two-year holdout once. The best of 2,807 crypto configurations looked great on validation (Sharpe 1.67, a printed total return of 4.16) and then **lost 44.8% a year on 2024-2025 with an 82% drawdown** — exactly the "picked winners do no better than random on unseen days" pattern we keep finding. Its cost assumption is also lighter than ours: 0.05% per side in the engine (about $0.10 per $100 round trip) and 3 bps per leg in the cost table, against our ~$0.23. So nothing here is a strategy to copy; the evidence is that this pipeline did not find a lasting crypto edge either.

Ideas worth testing on our crypto data:
1. **The Deflated Sharpe Ratio on our own picks.** We choose from millions of rows; the book's tool says how good the best of N would look by luck alone. Applying it to Stored strategies would put a number on "could be luck" beside every pick (`16_strategy_simulation/12_dsr_validation`).
2. **Funding premium as a filter, not a signal.** The premium z-score over 14 days (42 eight-hour bars) and the funding z-score are the features the crypto case built on, and Gate publishes funding per contract. Cheap to test as a "skip this entry when the coin's funding is crowded against us" mask on rows we already have — expect little, since the full model failed its holdout.

## Doubts

- I read the crypto case and the synthesis outputs closely; most other chapters only from their READMEs. The other eight case studies' code was not read.
- The prose in `19_strategy_analysis.ipynb` says the validation Sharpe is 1.57 with deflated Sharpe -0.15 and interval [0.27, 2.80], while the table printed just above it says 1.667939, -0.130747 and [0.422264, 2.868461] — the prose looks stale from an earlier rebuild.
- Cost numbers disagree between files: `base.yaml` charges 0.04% + 0.01% per side, the README says 2 bps maker / 4 bps taker, the cost-survival table uses 3.0 bps per leg.
- Commissions of $95,653 and slippage of $23,914 on $100,000 starting cash means very high turnover (2,746 trades over ~2 validation years); leverage per position is not stated in what I read.
- The universe is 19 coins chosen as top perps by volume today; coins that died are not in it (survivorship), which the README does not discuss for crypto.
- Results live in a downloadable registry (`v3.1.0-artifacts`), not in the repo; the notebooks say numbers change when the registry is rebuilt.
