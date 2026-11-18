# GitHub topic: walk-forward-validation

- Link: https://github.com/topics/walk-forward-validation
- What it is: GitHub's list of public repos tagged "walk-forward-validation" (testing a model only on days that come after the days it was built on). 222 repos carried the tag when read; below are the 30 with the most stars.
- Read: `gh api "search/repositories?q=topic:walk-forward-validation&sort=stars&per_page=30"` on Nov 18, 2026 (name, description, stars, last push). Each line is built from the repo's own description; I opened the README of only three (marked "README read"). Stars on this topic are tiny (the most is 153), so none of these is a widely used tool.

## The 30 most-starred repos

1. **assansolution-cell/options-commander-cli** - 153 stars, last push Nov 18, 2026. Claims to be an order-entry and trailing-stop command line tool for a broker account. **Treat as suspicious** (README read): created Nov 15, 2026, no licence, a "PowerShell Setup Button" that sends Windows users to an outside page, a made-up "Users 3.4K" badge, and its description copies repo 4 below almost word for word. 153 stars in three days on a copy looks bought. Do not run anything from it.
2. **IsaacCheng9/quant-trading-strategy-backtester** - 47 stars, Aug 01, 2026. Stock backtester with a dashboard: buy-and-hold, mean reversion, moving-average cross and cointegration pair trading, settings re-chosen on expanding training windows, fees and slippage charged, results against SPY; picks tickers and pairs on a 70/30 train/test split (README read).
3. **AndyDu0921/wc26-predict** - 32 stars, Jul 22, 2026. Football World Cup 2026 match forecasts (Dixon-Coles, Elo and other rating models blended), checked walk-forward. Not trading.
4. **iAmGiG/OptionsCommander** - 23 stars, Nov 07, 2026. Paper-trading platform on Alpaca; its research uses walk-forward, out-of-sample and multiple-testing checks and says plainly that no tested signal (MACD+RSI, time-series momentum, options gamma exposure) has an edge yet.
5. **Abolfazlrwm/Machine-Learning** - 14 stars, Nov 18, 2026. A machine-learning portfolio (a small GPT, Persian search, a recommender, a spam filter) with one stock backtest among them.
6. **kiploks/engine** - 9 stars, Aug 19, 2026. TypeScript engine for repeatable backtests and walk-forward analysis of trading strategies (a testing tool, no strategy).
7. **sauravsingla/Time_Series** - 7 stars, Oct 01, 2026. Forecasting benchmark: classic time-series models and lag-based machine learning, walk-forward checked with care to avoid using future data.
8. **neeljshah/court-vision** - 6 stars, Oct 30, 2026. Sports forecasts with public calibration records. Not trading.
9. **Farxida/prediction-market-ml** - 6 stars, Apr 28, 2026. Machine learning for prediction-market bets (521K markets, 78 features, 7 models), walk-forward, purged cross-validation and deflated Sharpe; live A/B test ended "NO-GO" because the edge decayed.
10. **parthsarthisaxena/Gold-POC-Retest---Multi-Timeframe-Strategy** - 4 stars, Aug 05, 2026. Long-only gold (XAU/USD) day trading: buy when price comes back to the volume profile's busiest price ("point of control"), tested on 8 years of 5-minute data.
11. **Yanu403/NexaBask** - 4 stars, May 30, 2026. Basket trading system on MetaTrader 5 with walk-forward checks.
12. **mguerrero896/does-option-flow-predict-volatility** - 3 stars, Nov 18, 2026. Asks whether options activity forecasts a stock's 15-day realised volatility, on six US stocks; a forecasting study, not a trading rule.
13. **ArjiaTechnologies/ares-engine** - 3 stars, Nov 14, 2026. Machine-learning research and paper-trading engine for ETH market data.
14. **mperi1208/value-bet-model** - 3 stars, Sep 14, 2026. Can public data find profitable football bets. Not trading.
15. **mahmoud20138/Edge-Extractor-ML** - 3 stars, Apr 16, 2026. Machine-learning search for mean-reversion, pair and volatility edges on MetaTrader 5, with walk-forward and bootstrap checks.
16. **jackc625/nfl-predict** - 2 stars, Nov 12, 2026. American football win and spread forecasts, walk-forward. Not trading.
17. **marmurar/jano** - 2 stars, Oct 07, 2026. A library for splitting time-ordered data into train/test windows (a testing tool).
18. **Digantdc/swing-trading-ml** - 2 stars, Jun 16, 2026. Machine learning to pick 21-day swing trades in AI and chip stocks, walk-forward; its own verdict is that the "edge" was just the sector going up, not stock picking.
19. **TomCardeLo/boa-forecaster** - 2 stars, May 21, 2026. Many forecasting models (SARIMA, random forest, XGBoost, LightGBM, Prophet, LSTM) tuned by Bayesian search, walk-forward checked. A forecasting tool.
20. **ava-28/rl-trading-ppo** - 2 stars, Aug 13, 2026. Reinforcement-learning agent (PPO) that splits money between assets, walk-forward, several random seeds, and a shuffled-price control (a luck bar).
21. **Iftekhar-mobin/quant-market-regime-research** - 2 stars, Aug 27, 2026. Tests whether switching strategies by market "regime" helps out of sample, with purged walk-forward, costs and significance tests.
22. **Tussar98/quant-ml-research** - 2 stars, Apr 26, 2026. Machine-learning trading research framework with walk-forward and cost-aware backtests.
23. **BianchiGiacomo/alpha-research-framework** - 2 stars, Oct 05, 2026. Machine-learning stock-signal research whose finding is that the apparent edge is overfitting: its signal's correlation with future returns flips from +0.036 to -0.084 when the model is regularised 100x.
24. **Ssavan99/Formula1-RacePredictor** - 2 stars, Nov 17, 2026. Formula 1 race forecasts scored in public against one-line baselines. Not trading.
25. **Volodymyr4K/market-efficiency-lab** - 2 stars, Jun 13, 2026. Can models beat baseball and tennis betting markets; walk-forward, reports the no-edge results.
26. **Alikhabazian0/Gold-Market-Regime-Classification** - 2 stars, Jun 19, 2026. Classifies gold (XAU/USD) market regimes from economic data with tree models and temporal convolution networks, walk-forward.
27. **mtrinkner/edge-audit** - 2 stars, Nov 05, 2026. 856 pre-registered tests of technical trading on US stocks (41 daily chart signals, 12 hourly day-trading setups, 377 variants, published anomalies, two chart-reading AI models), realistic costs and a luck bar; README: "None beat just holding the stock", the only real effect was the overnight return, which "is a payment for bearing risk, not an edge" (README read).
28. **burugupallyprem-coder/systematic-trading-research** - 2 stars, Sep 21, 2026. Stock research platform with pre-registered, walk-forward, cost-realistic backtests built to reject overfit strategies (Alpaca, GitHub Actions).
29. **Miller-Petit-Dev/aurum-edge** - 2 stars, Feb 07, 2026. Machine-learning trading engine for the Nasdaq 100 on 5-minute bars: triple-barrier labels (a target, a stop and a time limit per trade), XGBoost tuned by Optuna, walk-forward without leakage, realistic costs. In Spanish.
30. **WayneSHC/trendpoint** - 2 stars, Nov 18, 2026. Trend-trading aid for Taiwan stocks and index futures: stepped long/short levels anchored on ATR volatility plus market-structure breaks, with walk-forward, ablation tests and look-ahead checks. In Chinese.

## What it tells us

- The serious trading repos on this topic mostly report "no edge after costs on unseen data": #4, #9, #18, #23, #25 and #27 all say so in their own descriptions. That matches our own Gate result: about $0.00 a trade before fees, about $0.23 per $100 in fees and the buy-sell gap, and chosen strategies no better than random entries on days they were not chosen on.
- Methods worth borrowing for our tests (not strategies): pre-registering a test before running it (#27, #28), a shuffled-price control as a luck bar (#20), deflated Sharpe and purged cross-validation for many-strategy searches (#9), and ablation (switch one part off at a time) (#30).
- Strategy ideas we could measure on crypto: buying the retest of the volume profile's busiest price (#10) and regime-switched strategies (#21, #26), each only if it beats random entries on unseen days after Gate's costs.

## Doubts

- Only three READMEs were opened; every other line is the repo's own one-line description, unchecked.
- The topic is self-tagged by owners, so it includes sports and betting projects and at least one likely fake (#1).
- The ranking is by stars on Nov 18, 2026; with stars this low, a few stars move a repo many places.
