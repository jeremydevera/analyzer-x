# edtechre/pybroker

- Link: https://github.com/edtechre/pybroker
- What it is: a Python backtesting framework (fast engine on NumPy/Numba) built for strategies that use machine-learning models, with walk-forward testing, bootstrap statistics, parameter search, slippage models and margin.
- Stars, last push, licence: 3,721 stars, last push Nov 16, 2026, licence shown by GitHub as "NOASSERTION"; the README badge says "Apache 2.0 with Commons Clause" (you may use it, not sell a product built on it). Not archived.
- Markets and timeframes: US stocks in every example (Yahoo Finance, Alpaca, AKShare data sources); daily bars in the notebooks; the README shows 1-minute bars (`timeframe='1m'`). It can trade crypto (`enable_fractional_shares`, "Set to True for crypto trading", `config.py`) but has no idea of perpetual funding.
- Read: `README.md`; the user-guide notebooks 2 (Backtesting a Strategy), 3 (Bootstrap Metrics), 4 (Ranking Long and Short Signals), 6 (Training a Model), 8 (Applying Stops), 9 (Rebalancing), 10 (Rotational Trading), 12 (Parameter Optimization), 13 (Margin Trading, first half), 14 (Modeling Slippage), 16 (Time Series Models), 17 (Multi-Symbol Models), 18 (Dynamic Symbol Selection), all in `docs/source/notebooks/`, code and printed outputs; `src/pybroker/strategy.py` (`walkforward_split`), `src/pybroker/eval.py` (the bootstrap), `src/pybroker/config.py` (defaults). I did not run anything.

## The strategies

These are teaching examples, not strategies the author recommends. Every number below is from the notebook's own printed output, re-run on live Yahoo data when the docs were built. **Every example ran with `total_fees 0.0`.**

**1. Buy the dip / short the pop (notebooks 2, 3, 14)**
- Inputs: last close, the bar before's low and high. Daily bars.
- Buy: `if ctx.bars >= 2 and ctx.close[-1] < ctx.low[-2]` and no long open. Size `calc_target_shares(0.25)` = 25% of the account. Limit price `close[-1] - 0.01` (notebook 2; notebook 14 uses a market order).
- Exit: after `hold_bars = 3` bars. No stop, no target.
- Short side (TSLA): `close[-1] > ctx.high[-2]` and no short → short 100 shares, cover after `hold_bars = 2`.
- Notebook 2 (AAPL, MSFT long, TSLA short; Mar 01, 2017 - Mar 01, 2022; $500,000): 388 trades, 204 won (52.58%), total P&L $165,782.88, total return 33.16%, average trade +0.279691%, average hold 2.41 bars, worst drop -4.72%.
- Notebook 14 (F, BAC, T; Jan 01, 2021 - Jan 01, 2026): **+18.02% with no slippage; -8.66% with 10 basis points (0.10%) of slippage each way** (`FixedSlippageModel(bps=10)`); -39.55% with `VolatilitySlippageModel(atr_period=14, scale=0.1)`; +3.89% with random slippage of 0-10 bps. On three small caps (ESCA, BSET, HURC): +16.67% without, +12.46% with `VolumeSlippageModel(price_impact=0.1, volume_limit=0.025)`.

**2. Rank by volume (notebook 4)**
- If no long position across T, F, GM, PFE: buy 100% of the account in the one with the highest last-bar volume (`long_score = volume[-1]`, `set_max_long_positions(1)`), hold 2 bars. Jun 01, 2021 - Jun 01, 2022: 84 trades.

**3. 5-day rate of change, long and short (notebook 4)**
- `roc = (close[-1] - close[-6]) / close[-6]`. Long the stock with the highest positive roc, short the one with the most negative, 50% of the account each, hold 2 bars, at most 1 long and 1 short. T, F, GM, PFE, 2025: 146 trades.

**4. Stops (notebook 8)**
- Buy TSLA with 100% of the account whenever flat. Variants: stop 20% below entry (`stop_loss_pct = 20`); stop 20% + target 10% (`stop_profit_pct = 10`, 89 trades 2018-2022); trailing stop 20% + target 10% (`stop_trailing_pct = 20`, 106 trades).

**5. Monthly rebalance (notebook 9)**
- Equal weight (1/5 each) in TSLA, NFLX, AAPL, NVDA, AMZN at the start of each month; and a minimum-risk version (Riskfolio-Lib, lowest CVaR over the last 252 days).

**6. Rotation by 20-day rate of change (notebook 10)**
- `ta.ROC(adj_close, timeperiod=20)` on 10 large tech stocks; hold the top 2 at 50% each (`set_max_long_positions(2)`), sell one when it drops out of the top 5 (`enable_rotation(worst_rank_held=5)`); checked every day. Jan 01, 2018 - Jan 01, 2023: 260 orders. A variant puts 70% in rank 1 and 30% in rank 2.

**7. Linear regression on "close minus its 20-day average" (notebook 6)**
- Feature: `cmma_20` = close minus the average of the 20 closes before it. Target: next day's return. Model: `LinearRegression()`, one per stock (NVDA, AMD), Mar 01, 2017 - Mar 01, 2022.
- Rule: buy 100 shares when the predicted next-day return is above 0; sell 100 when it is below 0. No stop or target.
- Out-of-sample fit (R², 1.0 = perfect, 0 = no better than the average): AMD -0.0080, NVDA -0.0420; AMD 0.0006, NVDA -0.0236; AMD -0.0155, NVDA -0.4567. The model predicts nothing.
- Walk-forward result (`walkforward(warmup=20, windows=3, train_size=0.5, lookahead=1, calc_bootstrap=True)`): 43 trades, 76.74% won, total return 10.41%, average hold 25.49 bars, fees 0.
- Its own bootstrap says this may be luck: profit factor lower bound 0.907 (97.5%), 0.942 (95%), 0.982 (90%), all under 1; Sharpe lower bound -0.026, -0.016, -0.003.

**8. Price above its average, with a stop, tuned (notebook 12)**
- Buy 100 shares when close > SMA(period); sell all when close < SMA; stop loss `stop_pct`. Search: period 10, 20, 30, 40, 50 x stop 2, 4, 6, 8, 10% = 25 combinations. MRK, TGT, ORCL, Jan 01, 2021 - Jan 01, 2026.
- Default (30, 6%) over the whole period: +2.88%. Grid search on the first half: best period 10, stop 2.0%, train score +6.03%; on the second half (Jul 05, 2023 - Dec 31, 2025): +5.70%. Other searches picked period 20 / stop 8% (+5.48%) and period 30 / stop 8% (**-5.98%**).
- Walk-forward tuning (3 windows) chose a different setting in every window: 30 / 4%, 10 / 2%, 10 / 10%.

**9. Leverage (notebook 13)**
- Hold GS, MS, C, USB while the close is above the 50-day average, 25% each, `leverage=2.0`. "PyBroker does not model margin calls."

**10. Volatility forecast filter (notebook 16)**
- GARCH(1,1) on daily log returns (`arch` library), trained on the training window only. Buy 50% when next-day volatility forecast (annualised) is below 0.30, sell when above. SBUX, IBM, 2021-2026, 2 walk-forward windows: 6 closed trades, realised -$9,971.31 (-9.97%), with +$69,832.59 still open.

**11. Random forest on the last returns (notebook 16)**
- `RandomForestRegressor(random_state=42)` on the bar's log return plus its 3 previous ones (`lags=3`), predicting the next bar's return. Buy 50% when the prediction is above 0, sell when below. SBUX, IBM, 2021-2026: 416 trades, 51.92% won, +29.06%, **average trade +0.137668%**, average hold 2.10 bars, fees 0.

**12. One model for four chip stocks (notebook 17)**
- `close_minus_ma(lookback=20, atr_length=14)` (distance from the 20-day average measured in ATRs), one `LinearRegression` trained on MU, TXN, ADI, AMAT together, buy 25% when predicted next-day return > 0, sell when < 0; 3 walk-forward windows, 2021-2026: 170 trades, 70.0% won, +76.16%, average trade +1.4658%, average hold 14.0 bars, worst drop -28.60%.

**13. Breakout on the most-traded names (notebook 18)**
- On each training window pick the 3 of 20 large caps with the highest average dollar volume (close x volume); in the next test window buy when the close is above the previous 20-day high, sell when it closes below the previous 20-day low; 1/3 of the account each; `walkforward(windows=4, train_size=0.5)`, 2021-2026: 31 trades, +136.80%.

## How it tests them

**Fills and costs (defaults in `config.py` and notebook 14)**
- An order goes in on the NEXT bar (`buy_delay = 1`, `sell_delay = 1`) and fills at that bar's middle price, halfway between its low and high (`PriceType.MIDDLE`).
- Fees are off by default ("`None`: Fees are disabled (default)"). Fee modes exist: percent of order, per order, per share, or custom.
- Slippage is off unless set: fixed basis points, ATR-based, volume-based (caps the fill at a share of the bar's volume and adds `price_impact x (shares / volume)²`), or custom.
- Margin: `leverage`, and `interest_rate` on the borrowed part. No funding, no liquidation.

**Walk-forward (`strategy.py`, `walkforward_split`)**
- With `windows` above 1: the data is cut into equal windows; each has a training part (`train_size`, e.g. 0.5) and right after it a test part. The test parts sit back to back and end at the last date. With `lookahead = 1` the training part ends the bar before the test starts; a bigger `lookahead` leaves that many bars out so a target that looks N bars ahead cannot leak ("No bar in a window's test set is ever used to fit that window's models").
- The training part has a FIXED length (it rolls, it does not grow). Notebook 6's printout shows it: window 2 trains on Jun 04, 2018 - Aug 30, 2019, which is exactly window 1's test.
- Models are refit in every window; only the test parts are traded and reported. `shuffle` (default off) can shuffle training rows.
- Parameter search (`optimize`, Optuna grid / TPE / random) scores each setting on the training part only, then runs the best on the test part; with `windows > 1` it tunes each window separately.

**Bootstrap (`eval.py`, `bootstrap_eval_all`)**
- Takes the backtest's per-bar profit changes and returns (test bars only), draws the same number of bars at random WITH replacement, 10,000 times by default (`bootstrap_samples`), and measures profit factor (wins ÷ losses) and Sharpe on each draw. It reports the lower end of BCa confidence ranges at 97.5%, 95% and 90%, and worst-drop levels at 99.9%, 99%, 95% and 90%.
- Bars are drawn one at a time (no blocks), so losing streaks that come in bunches are broken up.
- It is NOT a random-entry baseline: it reshuffles the strategy's own bars. None of the notebooks I read compares a strategy with buy-and-hold or with random entries.

## What it claims

Quoted, unchecked:
- `README.md`: "Model training and backtesting using Walkforward Analysis, which simulates how the strategy would perform during actual trading."
- `README.md`: "Reliable trading metrics that use randomized bootstrapping to provide more accurate results."
- Notebook 6: "By using this approach, the Walkforward Analysis is able to simulate the real-world performance of a trading strategy, and produce more reliable and accurate backtesting results."
- Notebook 3: "We can observe that the bootstrapped max drawdown of -23.1% at a 99.9% confidence level is worse than the -4.7% we saw in our original results. This highlights the importance of using randomized tests to evaluate the performance of your trading strategy."
- Notebook 12: "Using the optimized parameters, we're able to see an improvment to the total return from before."
- Notebook 14: "A backtest that ignores it will overstate a strategy's true performance."

## What matters for us

On Gate, across millions of backtested strategies, the average trade earns about $0.00 before fees, and fees plus the buy-sell gap cost about $0.23 per $100 trade; strategies we chose did no better than random entries on days they were not chosen on.

- **The framework can test honestly; its examples do not.** Walk-forward keeps every test bar out of training, which is the same idea as our older-days / unseen-days split. But every example runs with no fee and no slippage, and none is compared with buy-and-hold or random entries.
- **Its own notebook shows our finding.** The dip-buy on F, BAC, T goes from +18.02% to -8.66% once each fill pays 0.10%. The random forest earns +0.137668% a trade before costs; after our ~0.23% it would lose about 0.09% a trade. The dip-buy's +0.279691% a trade (big US stocks, 2017-2022) would keep only about 0.05% after our cost.
- **The ML examples do not predict.** Notebook 6's out-of-sample R² is at or below zero in every window, and its own bootstrap cannot rule out luck (profit factor lower bound 0.907-0.982, under 1).
- **Tuning is unstable**: the 3-window tuning picked three different settings, and one TPE search's pick lost 5.98%. That matches our picker lab, where "the best" changed night to night.

Ideas worth testing on our crypto data:
1. **Donchian breakout on the cheapest coins, chosen on older days** (notebook 18's shape: buy a close above the previous 20-day high, sell a close below the previous 20-day low, universe picked on the training window only). Pick the coins by our lowest recorded buy-sell gap instead of dollar volume. This fits our current best candidate (trend with a trailing stop on coins whose gap is 5 basis points or less).
2. **The bootstrap lower bound of profit factor as an extra gate** beside our random-entry bar: a rule set whose 95% lower bound is under 1 is "could be luck" even when its total is positive. If used, draw blocks of days rather than single bars, so loss streaks stay together.

The rotation by 20-day rate of change (notebook 10) is close to our v3 "strength" family (Monday ranks, top 3 or 5), which did not pass our check, so it is not worth re-testing as is.

## Doubts

- I did not run anything; the notebook outputs come from whatever Yahoo returned when the docs were built, so the numbers change between builds.
- The docs say "the test data from the previous window is added to the training data", which sounds like a growing window; the code and the printed splits show a fixed-length rolling window.
- Notebook 3's text says "the Sharpe Ratio has a negative lower bound, and the Profit Factor's lower bound is less than 1", but the printed table above it shows 0.002662 and 1.000563, both just above. The text is from an older run.
- Notebook 12 says tuning "improved" the return, but compares +2.88% over 2021-2026 with +5.70% over only Jul 2023 - Dec 2025: two different periods.
- Notebook 16's GARCH example reports -9.97% realised while its account value is up to $159,861.28 from an open position; the headline depends on which you read.
- Notebook 18's 20-stock universe is a list chosen today (it includes PLTR and NVDA), so the stock list itself knows the future even though the selection inside it does not.
- Not read: notebooks 1, 5, 7, 11, 15 and FAQs; `portfolio.py` (how a stop and a target in the same bar are settled, and at what price a stop fills); `slippage.py`; `model.py`.
