# sjev/twp

- Link: https://github.com/sjev/twp
- What it is: the "Trading With Python" course by Jev Kuznetsov, made free: Jupyter notebooks that teach Python by backtesting a handful of daily stock and ETF strategies.
- Stars, last push, licence: 13 stars, last push Feb 14, 2021, no licence file (all rights reserved by default). Notebook outputs date from about Feb to Apr 2018.
- Markets and timeframes: US stocks and ETFs only (SPY, XLP, XLE and its member stocks, VXX, VXZ, TLT, GLD, TIP, leveraged ETFs), plus the VIX and VIX3M volatility indexes from CBOE. One bar a day, from Yahoo Finance via the author's own `tradingWithPython` library. No crypto.
- Read: `README.md`, `common.py`, and the cells and saved results of `twp_200_Leveraged_etfs`, `twp_201_Day_seasonality` (first part), `twp_302_moving_averages_strat`, `twp_302b_backtesting`, `twp_302c_backtesting-moving_averages`, `twp_303_permanent_portfolio`, `twp_304_xlp_strategy`, `twp_305_spread_trading_strategy`, `twp_306_Volatility_trading`, `twp_307_leveraged_etfs_ytd`, `twp_308_trading_VXX_with_nearest_neighbors`. Not read: the Python basics, plotting, csv, database and metrics notebooks (100-203, 301), and the `tradingWithPython` library itself (a separate repo).

## The strategies

**1. Moving-average cross on SPY, long or short** (`twp_302_moving_averages_strat.ipynb`)
- Long 10 shares when the 10-day simple average is above the 50-day, short 10 shares otherwise; always in the market.
- Tuning: fast `arange(1,20,1)` days x slow `arange(20,200,5)` days, the best Sharpe on the training part (all but the last 500 days). Best found: fast 18, slow 25, "Maximum sharpe: 0.39".
- The notebook's own verdict: *"even after optimization the results of moving averages crossover are disappointing. Needless to say, out-of-sample performance is not better."*

**2. The same cross, walk-forward** (`twp_302c_backtesting-moving_averages.ipynb`)
- $10,000 long or short. Each step: 3 years of data, tune fast `1..19` and slow `20..115` (step 5) on the first 2 years, trade the 3rd year (250 days), move on one year. 15 trading years, 2003 to 2017.
- Verdict, quoted: *"...that does not look good at all. Even without transaction costs and slippage the strategy loses money."*

**3. XLP "boring consumer stocks" gap rule** (`twp_304_xlp_strategy.ipynb`, taken from the Quantified Strategies blog)
- Rule: yesterday's close-to-close change was below -0.25%, AND today's open is more than 0.1% below yesterday's close: buy at the open, sell at the same day's close. Long only, one day.
- Tuning grid: yesterday's threshold `np.linspace(-1,1,30)` %, gap threshold `np.linspace(-0.5,0.5,30)` %, 900 settings, best Sharpe chosen.
- Walk-forward: tune on 250 days, trade the next 250, repeat (15 steps).

**4. Pairs and single-stock mean reversion on energy stocks** (`twp_305_spread_trading_strategy.ipynb`)
- Spread: $100 long of one stock, short $100 / beta of the other (CVX vs XOM, CVX vs COP), with the last 250 days held out.
- Signal: today's spread return divided by its 20-day (or 50-day) standard deviation = z-score; "above average" = the spread's running total above its 25-day average. Short for one day if above average and z-score > z_enter; long for one day if below average and z-score < -z_enter. z_enter scanned `np.arange(0.5,3,0.1)`.
- Verdict, quoted: *"this strategy does not look like a success"* and, on XOM alone out-of-sample, *"Also out-of-same the strategy is unpredictable"*.

**5. "smartVXX": short volatility only in steep contango** (`twp_306_Volatility_trading.ipynb`)
- Fit VIX3M as a 2nd-order curve of VIX (`np.polyfit(..., 2)`; on all data the coefficients were `[-0.00341517 1.05715063 2.07459118]`). delta = actual VIX3M minus the fitted value.
- Short VXX (a volatility fund that loses value in calm markets) when delta > 0, flat otherwise; signal applied the next day. A variant shorts VXX + 3x SPY together only when VIX < 25, at 2x leverage.
- Walk-forward version: fit the curve on 250 days, trade the next 50 with $10,000 short, 40 steps, Interactive Brokers cost of $0.005 a share with a $1 minimum.

**6. Nearest neighbours on VXX** (`twp_308_trading_VXX_with_nearest_neighbors.ipynb`)
- Features: a = VIX minus VIX3M; b = the sum of VXX's last 5 daily returns. Both scaled by (value - mean) / (95th - 5th percentile).
- Model: scikit-learn `NearestNeighbors` with n = 5, 10, 20, 30, 50 or 80. For today's point, take the n most similar past days and their NEXT-day VXX returns; their Sharpe (x square root of 250) above 2 = long, below -2 = short, else flat.
- Test: trained on all but the last 250 days, traded the last 250 days.

**7. Permanent portfolio with a VIX switch** (`twp_303_permanent_portfolio.ipynb`)
- $25 each in SPY, TLT, GLD, TIP, rebalanced daily with no cost; variant: stay out the next day when VIX > 35.

**8. Short leveraged ETFs hedged with the plain fund** (`twp_307_leveraged_etfs_ytd.ipynb`)
- Five pairs over the last 250 days, e.g. `SPY 2 SSO -1` ($200 SPY long, $100 of the 2x fund SSO short); the idea is that leveraged funds lose value in choppy markets. `twp_200` shows the same thing by simulation: 5,000 random 1,000-day paths, 3x leverage keeps the average near $100 but most paths finish lower.

## How it tests them

- Splits: a held-back last 250 or 500 days (strategies 1, 4, 6), or walk-forward with tune-then-trade blocks (2: 2 years / 1 year; 3: 250 / 250 days; 5: 250 / 50 days). The author notes for strategy 2 that he *"did not split the datasets to in-sample and out-of-sample for convenience ... so caution is advised regarding the look-ahead bias"* (the moving averages there are worked out over the 3-year block, then only the last year is kept).
- Costs: almost never. Only strategy 5's walk-forward charges a broker fee ($0.005 a share, $1 minimum); no spread, no slippage, no short-borrowing cost anywhere. Strategy 3 trades open to close every time it fires and is costed at zero.
- Baselines: buy-and-hold appears for XLP (Sharpe 0.37), SPY (strategies 5 and 7) and "short VXX always" (strategy 5, 6). No random-entry baseline.

## What it claims

Unchecked, from saved outputs:
- `twp_304_xlp_strategy.ipynb`: original rules *"Sharpe: 1.00708745001"*; best of the grid *"Sharpe: 1.40688387138"*; walk-forward *"Sharpe: 1.40"* and *"So, the strategy seems to perform quite well out-of-sample"*; buy-and-hold *"Sharpe buy-and-hold: 0.372976063661"*.
- `twp_306_Volatility_trading.ipynb` (whole history, no walk-forward): *"dumbVXX 1.04 / SPY 1.04 / smartVXX 1.74 / smartSPY_VXX 1.58"* Sharpe; walk-forward with cost: *"Sharpe: 1.15062029972 / Profit ratio: 11.1532132193"*.
- `twp_308_trading_VXX_with_nearest_neighbors.ipynb`, last 250 days: Sharpe *"5 0.112911 / 10 0.867389 / 20 2.260852 / 30 1.985011 / 50 1.263594 / 80 2.234422"* against short-VXX-and-hold *"-0.0140970987892"*.
- `twp_303_permanent_portfolio.ipynb`: Sharpe *"strategy 0.98 / SPY 0.54 / strategy+ 1.16"*, *"Max drawdown: 5.89 %"* then *"4.56 %"* with the VIX switch.
- `twp_302_*`: the moving-average cross failed in its own test, quoted above.

## What matters for us

Our Gate measurement: the average trade earns about $0.00 before fees, fees plus the buy-sell gap cost about $0.23 per $100 traded, so fees are the whole loss, and chosen strategies did no better than random entries on days they were not chosen on. Nothing here could survive that as written: apart from one walk-forward, no strategy pays any cost, there is no random baseline, and the one strategy tested honestly on unseen days with a plain rule (the moving-average cross) lost money even before costs, which is our own finding in miniature. The XLP gap rule is the most interesting result, but it trades open-to-close for a fraction of a percent a day; a 0.15% round trip would eat much of it, and it is about a US market's opening gap, which crypto (open all day) does not have.

Ideas worth testing on our crypto data:
1. **Nearest neighbours on two features, with "do nothing" in the middle**: find the most similar past moments by (funding or basis, the last 5 bars' return) and trade only when their next-bar results were strongly one-sided (Sharpe above 2 among the neighbours). On crypto, funding rate or the futures-vs-spot gap could stand in for the VIX term structure. It must be fit only on older days and judged against random entries.
2. **"Down yesterday and opened lower" as a filter on stock tokens**: Gate's stock tokens do follow US market hours, so the XLP rule could be checked there as a long-only, one-session trade, with the full Gate cost charged.

## Doubts

- In `twp_308`, the scaling (mean and 5-95% range) is worked out over ALL the data, test days included, and `findNeighbors` uses the global `normalizer` rather than the trader's own; a small look-ahead. The 6 neighbour counts were all shown on the same 250 test days, so picking "20 neighbours, Sharpe 2.26" afterwards is choosing on the test.
- In `twp_304`, the best-of-grid printout says "Optimum CC 0.17 / CO 0.12" but the next cell runs with 0.03 / 0.09; the reported 1.41 is for hand-typed values.
- All data is from Yahoo through a separate library (`tradingWithPython`), which I did not read; how `pos2pnl` and `Backtest` time their fills is not checked here.
- VXX (the old one) was closed in Jan 2019, so strategies 5 and 6 can no longer be run as written.
