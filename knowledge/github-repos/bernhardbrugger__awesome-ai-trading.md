# bernhardbrugger/awesome-ai-trading

- Link: https://github.com/bernhardbrugger/awesome-ai-trading
- What it is: a reading list (an "awesome list") of tools, data sources, papers and courses for AI and machine-learning trading, with a section on why backtests mislead; it holds links, not strategies or code.
- Stars, last push, licence: 1 star, last push Nov 10, 2026, CC0-1.0 (public domain). Not archived. Its README says every project "was checked for existence and recent activity on **2026-11-05**", and a monthly GitHub job re-checks the links (`.github/workflows/links.yml`, `scripts/check-links.mjs`).
- Markets and timeframes: whatever each linked item covers: stocks, crypto, futures, macro data; one section is Austrian data.
- Read: `README.md` (every entry), `CONTRIBUTING.md`, and the file list. I did not open the linked papers or projects, except one check of the OpenBB link (see Doubts).

## The categories

139 links in all (my count, not counting the table of contents):

| section | links | what is in it |
|---|---|---|
| LLMs and AI agents | 10 + 3 MCP servers | multi-agent LLM "trading firms" (TradingAgents, ai-hedge-fund), finance LLMs (FinGPT, FinBERT), agent platforms; 3 data/broker servers for AI assistants |
| Time series and forecasting | 9 | pretrained forecasting models (Kronos for candles, Chronos, TimesFM, Moirai) and classic libraries (Darts, sktime, StatsForecast, arch for GARCH, statsmodels) |
| Machine learning and RL | 5 | Qlib, FinRL, TensorTrade, a multi-factor stack, OpenBB |
| Backtesting and trading engines | 13 | NautilusTrader, Lean, VectorBT, backtesting.py, Zipline Reloaded, Backtrader, bt, Lumibot, vn.py, hftbacktest, Hummingbot, Freqtrade, Jesse; plus a table comparing 8 of them |
| Brokers and execution | 3 | Alpaca, Interactive Brokers (ib_async), CCXT |
| Portfolio and risk | 9 | PyPortfolioOpt, Riskfolio, skfolio, QuantStats, pyfolio, empyrical, alphalens (does a factor carry information), ffn, QuantLib |
| Technical analysis | 3 | TA-Lib, pandas-ta-classic, ta |
| Data | 11 market + 5 filings/macro + 4 Austria + 5 academic + 4 alternative + 5 crypto | Yahoo, Alpaca, Databento, FRED, SEC EDGAR, Fama-French, Open Source Asset Pricing (200+ published predictors), CoinGecko, Glassnode ... |
| Research papers | 21 | foundations (3), LLMs and agents (7), time-series foundation models (3), RL (3), news and sentiment (3), market microstructure (2) |
| Pitfalls: backtests that lie | 6 + a checklist | backtest overfitting, the deflated Sharpe ratio, "t above 3" for new factors, replication of 153 factors, a backtesting protocol |
| Strategy ideas | 1 link (Quantpedia) + 5 idea groups | see below |
| Courses and books | 7 books + 4 courses | López de Prado, Jansen, Chan, Hilpisch, Harris, Narang; Georgia Tech ML4T, QuantConnect |
| Community | 5 + 4 blogs + 3 YouTube | r/algotrading, Quantocracy, Robot Wealth, Quantpedia ... |

The strategy categories it names (section "Strategy Ideas", quoted):
- "**Trend following:** moving-average crossover, dual momentum (relative plus absolute), channel breakouts."
- "**Mean reversion:** Bollinger Band reversion, pairs trading on cointegrated assets, RSI extremes."
- "**Sentiment and alternative data:** LLM/FinBERT scoring of news and earnings calls, social-media signals, search-interest momentum."
- "**Machine learning:** tree ensembles and gradient boosting on engineered features, sequence models, reinforcement-learning allocation, foundation-model forecasts."
- "**Crypto:** cross-exchange arbitrage, funding-rate strategies, on-chain flow signals."

## Top 10 for learning trade signals

1. The Probability of Backtest Overfitting (Bailey, Borwein, López de Prado, Zhu, 2016) — how the number of strategies you tried changes what a good backtest means: https://doi.org/10.21314/JCF.2016.322
2. The Deflated Sharpe Ratio (Bailey, López de Prado, 2014) — shrinks a best-of-many result for how many were tried: https://doi.org/10.3905/jpm.2014.40.5.094
3. ...and the Cross-Section of Expected Returns (Harvey, Liu, Zhu, 2016) — with hundreds of ideas tried, a new one needs a much stronger result (t above 3): https://doi.org/10.1093/rfs/hhv059
4. A Backtesting Protocol in the Era of Machine Learning (Arnott, Harvey, Markowitz, 2019) — a checklist for testing an idea honestly: https://doi.org/10.3905/jfds.2019.1.064
5. Empirical Asset Pricing via Machine Learning (Gu, Kelly, Xiu, 2020) — how much ML really adds to return prediction on a large, careful test: https://doi.org/10.1093/rfs/hhaa009
6. Advances in Financial Machine Learning (López de Prado, 2018) — the book on labels with a stop, a target and a time limit, and on cross-validation that does not leak: https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086
7. Machine Learning for Algorithmic Trading, code (Stefan Jansen) — 27 chapters of free working code from features to backtests: https://github.com/stefan-jansen/machine-learning-for-trading
8. alphalens-reloaded — a tool that tests whether a signal ranks future returns at all before any strategy is built on it: https://github.com/stefan-jansen/alphalens-reloaded
9. Kronos — a forecasting model pretrained on candlesticks, worth a look as a ready-made signal to test: https://github.com/shiyu-coder/Kronos
10. Quantpedia — a searchable database of trading strategies with their academic sources: https://quantpedia.com/

## What it claims

The list claims no results of its own. Quoted from `README.md` (unchecked):
- "**Not financial advice.** Software and papers in this list are for research and education. Most published strategies stop working once costs, slippage and overfitting are accounted for."
- "A strategy that looks great in a backtest is usually a statistical accident. Read these first."
- "Checklist that applies to every tool above: no look-ahead bias, split by time (never shuffle), include fees and slippage, count every strategy you tried, test out-of-sample, then paper-trade before using real money."
- "Rule of thumb: vectorised engines are fast for screening ideas but make look-ahead and unrealistic fills easy; event-driven engines are slower and closer to how orders really work."

## What matters for us

On Gate, across millions of backtested strategies, the average trade earns about $0.00 before fees, and fees plus the buy-sell gap cost about $0.23 per $100 trade; strategies we chose did no better than random entries on days they were not chosen on.

The list itself agrees with that: its "Pitfalls" section and checklist are the same rules we learned the hard way (costs in, split by time, count every try, test on unseen days). It ships no strategy whose results could pass or fail our test.

Ideas worth testing on our crypto data:
1. **The deflated Sharpe ratio or the probability of backtest overfitting, applied to our picker lab and Forecast v4.** We choose among 24,480 rule sets; these papers say how much a winner's result must be shrunk for that many tries. It is a sharper bar than "beat random on more than half the days".
2. **A funding-rate strategy** (the list's crypto ideas): we trade Gate perpetuals and already read every coin's funding history, so "hold the side that is paid funding" can be measured with all costs, as its own entry rule rather than only as a filter.

## Doubts

- I did not open the linked papers or tools; the one-line summaries come from the list and from what I already know.
- One star and one maintainer: the list is new and small; "checked on 2026-11-05" is its own claim.
- The OpenBB link points at `openbq-org/OpenBB`, which looked like a typo. I checked: GitHub answers the old address `OpenBB-finance/OpenBB` with that same repository (75,529 stars, created Dec 20, 2020), so the organisation was renamed and the link is genuine.
- The "Strategy Ideas" are headings, not tested strategies; only Quantpedia is linked there.
- CCXT is listed twice (Brokers and Crypto Data); my count of 139 includes both.
