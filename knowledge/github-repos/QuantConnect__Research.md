# QuantConnect/Research

- Link: https://github.com/QuantConnect/Research
- What it is: the QuantConnect company's public folder of teaching notebooks for its LEAN platform - short demonstrations of an idea (pair trading, an average crossover, a regime model, a neural network) rather than finished, tested strategies.
- Stars, last push, licence: 830 stars, last push May 17, 2024, Apache-2.0. Most notebooks date from 2018-2020.
- Markets and timeframes: US stocks and ETFs only (XOM/CVX, SPY, IWM, DIA, VXX, Treasury ETFs, sector ETFs, airlines), mostly 1-day candles, some 1-hour. No crypto. The notebooks only run inside QuantConnect's own research environment (`QuantBook`), which supplies the data.
- Read: `README.md` and the cell code and text (not the saved charts) of all 24 notebooks: `Analysis/01`-`05`, `Research2Production/Python/01`-`08` (the C# copies of 01, 03, 04, 05 are the same ideas), `Documentation/Python/*` (7), `Topical/*` (2), `Scratch Notebooks/Optimization Analysis - Draft.ipynb` (first cells only).

## The strategies

The notebooks that build a trading rule or a stock-picking rule:

**1. EMA cross on VXX, trading index ETFs** (`Analysis/04 EMA Cross Strategy Based on VXX.ipynb`). VXX (a fear-index fund) and SPY, IWM, DIA, daily, Jan 01, 2010 to the run date. Signal from a 10-day exponential average of VXX (`ExponentialMovingAverage(10)`; the text says "30-day"). When VXX falls back below its average (fear easing) BUY all three ETFs; when VXX rises above it, go to cash. $100,000 split equally, whole shares. No stop or target. Benchmark: buy-and-hold SPY.

**2. Pair trading by cointegration, XOM vs CVX** (`Analysis/05 Pairs Trading Strategy Based on Cointegration.ipynb`). Daily, Jan 01, 2003 to Jan 01, 2009. Regress log CVX on log XOM; the leftover gap passes the ADF stationarity test (statistic -3.45, p-value 0.009, quoted in the notebook). Trade when the gap is more than 1.5 standard deviations from its mean, with a rolling 250-day regression. The actual trading code is only on QuantConnect's site (a linked backtest), not in the repo.

**3. Kalman-filter pair trading, XOM vs CVX** (`Analysis/02 Kalman Filter Based Pairs Trading.ipynb`). Same pair and dates. First a fixed regression: buy the gap (buy 1 CVX, sell beta x XOM) when it crosses below mean - 1.96 standard deviations, sell it above mean + 1.96, close at the mean. Then a Kalman filter (pykalman, observation covariance 0.5, transition covariance 0.000001) lets the hedge ratio drift over time; the notebook only plots the new gap, it does not trade it.

**4. Kalman-filter hedge ratio for VIA/VIAB** (`Research2Production/Python/04 Kalman Filters and Pairs Trading.ipynb`). Daily, Jan 01 to Jan 11, 2019. Filter settings delta = 0.0001, observation noise 0.001, base size 2,000 shares (`self.qty = 2000`); prints the forecast error, its standard deviation and the hedge size each day. The entry rule (trade when the error is beyond its standard deviation) is described, not coded.

**5. Mean reversion on Treasury ETFs** (`Research2Production/Python/01 Mean Reversion.ipynb`). 18 Treasury ETFs (SHY, TLT, SHV, ... GOVT). Over the last 30 daily closes, pick every ETF whose latest price is more than one standard deviation below its 30-day average, and buy it expecting a bounce. No exit rule in the notebook.

**6. Fundamental factor ranking** (`Analysis/01 Fundamental Factor Analysis.ipynb`). 100 high-volume US stocks chosen on Jan 01, 2011 (45 used), Morningstar fundamentals (e.g. P/E ratio) at each month end, sorted into 5 groups; monthly returns of each group against SPY, scored by how well group rank lines up with return (minimum correlation 0.3). A factor test, then long the best group / short the worst.

**7. Stock picking by P/E** (`Documentation/Python/Stock-Picking-With-Fundamental-Data.ipynb`). Airline stocks; average P/E over 2014; plots the returns of the highest-P/E and lowest-P/E stock from 2009 to 2015 (note: the returns window starts before the P/E year).

**8. Least-correlated assets** (`Research2Production/Python/03 Uncorrelated Assets.ipynb`). 10 leveraged/volatility ETFs (SQQQ, TQQQ, TVIX, VIXY, SPLV, SVXY, UVXY, EEMV, EFAV, USMV); 150 hours of returns; keep the 5 with the lowest average absolute correlation divided by its spread. Portfolio choice, no timing.

**9. Z-scores of returns** (`Research2Production/Python/05 Stationary Processes and Z-Scores.ipynb`). S&P 500 sector ETFs, 500 hours; ADF test (p < 0.05) and z-score of each return. Suggests trading extreme z-scores; no rule coded.

**10. Hidden Markov regime model** (`Research2Production/Python/07 Hidden Markov Models.ipynb`). SPY, 900 daily returns, a 2-state Gaussian HMM (`n_components=2`, 1,000 iterations) labelling "bull" and "bear" days, meant as a risk switch. No trading rule.

**11. Machine-learning forecasts** - `Research2Production/Python/02 Random Forest Regression.ipynb` (100 trees on 500 hours of Treasury ETF returns, but the target is random numbers, `y = np.random.normal(100000, 5, ...)`, a placeholder for the real account value); `06 Principle Compenent Analysis.ipynb` (PCA of 100 days of Treasury yield changes, 95% of variance in 4 parts, next-day forecast by linear regression vs random forest); `08 Long Short-Term Memory.ipynb` (SPY 1,280 days, 60-day windows, a 4-layer LSTM with 50 units and 20% dropout, 50 epochs, predicts the last 20 days' prices); `Documentation/Python/Predicting-Future-Prices-With-Sklearn/Keras/TensorFlow` (SPY intraday, 5 bars of OHLCV to predict the next close). None turns a forecast into trades.

**12. Mean-variance portfolio** (`Analysis/03 Mean-Variance Portfolio Optimization .ipynb`). CCE, AAP, AAPL, GOOG, IBM, AMZN; efficient frontier with risk-free rate 0. Not a timing rule.

Not strategies: the plotting notebooks, `Topical/20200507_hopevfear_research.ipynb` (counts "hope" and "fear" words in 2020 S&P 500 news), `Topical/20200601_airlinebuybacks_research.ipynb` (airline buybacks vs cash flow), and the `Scratch Notebooks` draft (collects statistics from many saved backtests).

## How it tests them

- Only the EMA-cross notebook works out a profit, over the whole period at once, with no train/test split.
- Look-ahead in the pair notebooks: the regression line, the mean and the 1.96 standard-deviation bands are worked out on all six years and then used to trade inside those same years. The LSTM, sklearn and random-forest notebooks do hold back the last part of the data (20 days, or 20%) to check the forecast, but they never trade it.
- Costs: the EMA notebook says "Here we ignore the fees when we generate the profit curve". No other notebook charges anything. (QuantConnect's own backtester, linked from Analysis 04 and 05, does charge fees, but those runs are not in the repo.)
- Baselines: buy-and-hold SPY in the EMA notebook and the factor notebook. No random baseline.

## What it claims

Unchecked, from saved outputs:
- `Analysis/04 EMA Cross Strategy Based on VXX.ipynb`, its statistics cell: "'Compounding Annual Return (%)': 8.88316669670892", "'Net Profit (%)': 100.47742283569691", "'Sharpe Ratio': 0.8385125945061834", "'Drawdown (%)': 14.7", "'Win Rate (%)': 38.87269193391642", "'Beta': 0.481217139398708". (No fees; the "win rate" is per day, not per trade.)
- `Analysis/05 ...Cointegration.ipynb`: "Running the example prints the test statistic value of -3.45 ... The p-value 0.009 is less than 0.05."
- `Research2Production/Python/06 ...`: "Random Forest Regression has the highest R-squared values and the prediction SSE is approximately the same as Linear Regression".

## What matters for us

Nothing here is evidence that would survive our test: no costs, no unseen days for any trading result, no random baseline, and US stock data only. On Gate, where the average trade earns about $0.00 before fees and costs about $0.23 per $100, the EMA result (8.9% a year without fees, beta 0.48 to SPY, mostly just holding stocks in calm times) says nothing about a crypto edge.

Ideas worth testing on our crypto data:
- **"Fear easing" as a filter**: QuantConnect's idea is to hold risk only when a fear gauge is below its 10-day average. A crypto version: only allow long entries when BTC's short-term volatility (or the funding-rate level) is under its own 10-day average. That is a filter on top of our signals, measurable against the same signals without it.
- **Kalman-filter pair trading between two Gate perpetuals** (e.g. two coins in the same sector), with the hedge ratio updated each bar and the bands judged only on past data - this is the version the notebooks describe but never trade.

## Doubts

- The two LEAN backtests the pair and EMA notebooks link to (quantconnect.com terminal pages) were not opened, so the trading rules and results of those are unread.
- The EMA notebook's text says 30-day EMA and "five index ETFs", while the code uses a 10-day EMA and three ETFs.
- The random-forest notebook fits to random noise (`np.random.normal`) on purpose as a placeholder; its "weights" mean nothing.
- I skimmed only the first cells of the 730 KB scratch notebook and the airline-buyback notebook.
