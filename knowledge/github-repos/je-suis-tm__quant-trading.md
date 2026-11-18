# je-suis-tm/quant-trading

- Link: https://github.com/je-suis-tm/quant-trading
- What it is: a very popular teaching collection of short Python scripts, one per classic trading idea (moving averages, RSI, Bollinger, breakouts, pair trading, candle patterns, options), each drawing a chart of where it would buy and sell on one example stock or currency.
- Stars, last push, licence: 11,310 stars, last push Jun 20, 2026, Apache-2.0. Most scripts were written in 2018.
- Markets and timeframes: US and UK stocks on daily candles from Yahoo Finance (NVDA, AMD, EA, FCAU, GE, VOD.L), GBP/USD on 1-minute candles from histdata.com (London Breakout, Dual Thrust, Bollinger), Norwegian krone vs Brent crude daily, Euro Stoxx 50 options. No crypto.
- Read: `README.md`, `Monte Carlo project/README.md`, the results parts of `Oil Money project/README.md` and `Smart Farmers project/README.md`, and the code of `MACD Oscillator backtest.py`, `Pair trading backtest.py`, `Heikin-Ashi backtest.py`, `London Breakout backtest.py`, `Awesome Oscillator backtest.py`, `Dual Thrust backtest.py`, `Parabolic SAR backtest.py`, `Bollinger Bands Pattern Recognition backtest.py`, `RSI Pattern Recognition backtest.py`, `Shooting Star backtest.py`, `Oil Money project/Oil Money Trading backtest.py`, `Options Straddle backtest.py`, `Monte Carlo project/Monte Carlo backtest.py`; skimmed `VIX Calculator.py` and `Smart Farmers project/forecast.py`.

## The strategies

Numbered as in the README. "Long" = buy, "short" = sell first.

**1. MACD oscillator** (`MACD Oscillator backtest.py`). Two simple moving averages of the close, lengths typed in by the user (`ma1`, `ma2`, no defaults). Long while the short average is at or above the long one, flat otherwise. No stop, no target. Only draws the chart; no profit is worked out.

**2. Pair trading** (`Pair trading backtest.py`). NVDA and AMD, daily, Jan 01, 2013 to Dec 31, 2014. Every day it re-runs an Engle-Granger cointegration test on the last 250 days (`bandwidth=250`): the price gap must be stationary (ADF p-value 0.05 or less) and the error-correction term negative. When the pair becomes cointegrated it fixes the fitted line and a band of plus/minus one standard deviation of the gap. Above the band: long asset 1, short asset 2; below: the reverse. If cointegration breaks, the position is closed. $20,000 per leg, as many whole shares as the highest price allows.

**3. Heikin-Ashi** (`Heikin-Ashi backtest.py`). NVDA daily, Apr 01, 2015 to Feb 15, 2018, chart from bar 700. Heikin-Ashi ("average bar") candles: close = average of open/high/low/close; open = average of the previous HA open and close. Buy when the HA candle is red with no upper wick (HA open = HA high), its body bigger than the previous one, and the previous one also red. Sell everything when the HA candle is green with no lower wick and the previous one green. Up to 3 stacked buys (`stls=3`). 100 shares a signal, $10,000 start. Compared with the S&P 500 (`^GSPC`).

**4. London Breakout** (`London Breakout backtest.py`). GBP/USD, 1-minute. The high and low of the hour before London opens (hour 2 in the data's clock) set the band. In the first 30 minutes after the open (`open_minutes=30`), a price above the high buys and below the low sells, but not if the break is already more than 0.01 (100 pips, `risky_stop=0.01`) past the band. Exit at plus or minus 0.005 (50 pips, `risky_stop/2`) from the entry, or close everything at hour 12. One position at a time.

**5. Awesome oscillator** (`Awesome Oscillator backtest.py`). Median price (high+low)/2 averaged over 5 and 34 bars. "Saucer" rule: buy when the oscillator is below zero and turns up while the candles go red after two green ones (and the mirror to sell). Then a plain rule on top: long when the 5-bar average is above the 34-bar one, sell when below. Compared with an exponential MACD of 5/34. $5,000, 100 shares.

**6. Oil Money** (`Oil Money project/Oil Money Trading backtest.py`). NOK/JPY against Brent crude in JPY, daily. Fit a straight-line regression of NOK on Brent over the last 50 days (`train_len=50`); use it only if R-squared is over 0.7. If NOK goes above the fitted value + 2 standard deviations, BUY (it is a momentum rule, not a bet on return to the line); below - 2, sell. Exit after 10 days (`holding_threshold=10`) or when NOK has moved 0.5 from the entry (`stop=0.5`, a stop and a target in one). $5,000.

**7. Dual Thrust** (`Dual Thrust backtest.py`). GBP/USD 1-minute, the trading day taken as hour 3 to hour 12. Range = the larger of (highest high - lowest close) and (highest close - lowest low) over 5 days (`rg=5`). At the open: upper line = open + 0.5 x range, lower line = open - 0.5 x range (`param=0.5`). Above the upper line go long, below the lower go short, flipping sides when the price crosses from one line to the other. No stop or target; close everything at hour 12.

**8. Parabolic SAR** (`Parabolic SAR backtest.py`). EA daily, Jan 01, 2016 to Jan 01, 2018. Standard Wilder SAR: acceleration starts at 0.02, steps 0.02, caps at 0.2. Long while the close is above the SAR, flat when below. Chart only.

**9. Bollinger Bands pattern** (`Bollinger Bands Pattern Recognition backtest.py`). GBP/USD (the file it loads). 20-bar average, bands at 2 standard deviations. Looks back up to 75 bars (`period=75`) for a "W" double bottom: price at the middle band, then touching the lower band, a second low that stays above the band but under the first low, then a break above the upper band = buy. "Touching" means within 0.0001 (`alpha`). Exit when the bands squeeze (20-bar standard deviation under 0.0001, `beta`). No stop.

**10. RSI and head-and-shoulders** (`RSI Pattern Recognition backtest.py`). FCAU daily, Jan 01, 2016 to Jan 01, 2018. RSI 14 with Wilder smoothing. The script that runs is the simple one: long while RSI is under 30, short while over 70, flat in between. A second function (not run by `main`) finds a head-and-shoulders top in the close over 25 days (`period=25`, price tolerance 0.2, head and shoulder heights 1.1 x 0.2) and shorts it; exit when RSI rises more than 4 points from entry (`exit_rsi=4`) or after 5 days (`exit_days=5`).

**11. Monte Carlo** (`Monte Carlo project/Monte Carlo backtest.py`). Not a strategy but a test of one: GE daily Jan 15, 2016 to Jan 15, 2019, split 50/50. Simulate 100 to 1,000 random price paths with the first half's drift and volatility, pick the path closest to the first half, and see if it calls the second half's direction. Its point is that it does not.

**12. Options straddle** (`Options Straddle backtest.py`). Euro Stoxx 50 options (August expiry, from an Excel file). Buy a call and a put at the same strike when their prices are within 2 of each other (`threshold=2`), contract size 10. Profit at expiry = |spot - strike| x 10 - both premiums. Payoff chart only.

**13. Portfolio optimisation.** Lives in another repo (je-suis-tm/graph-theory); not read.

**14. Smart Farmers** (`Smart Farmers project/forecast.py`). Malaysian crops, yearly. A supply-and-demand optimisation of how much farmers plant, used to forecast price and production one year ahead. Not a trading rule.

**15. VIX calculator** (`VIX Calculator.py`). Works out a VIX-style 30-day expected volatility from any options chain (CBOE method). A tool, not a trading rule.

**16. Wisdom of Crowds.** Lives in another repo (je-suis-tm/machine-learning); not read.

**17. Shooting Star** (`Shooting Star backtest.py`). Vodafone (VOD.L) daily, Jan 01, 2000 to Nov 04, 2021. A red candle with a long upper wick (at least twice the body), a lower wick under 0.2 x the body (`lower_bound=0.2`), a body under 0.5 x the average body (`body_size=0.5`), after two rising closes - and the NEXT candle's high and close no higher. Short it; exit when the close is 5% away from entry either way (`stop_threshold=0.05`) or after 7 days (`holding_period=7`).

## How it tests them

- No train/test split anywhere except the Oil Money README (fit before Apr 25, 2017, test after, with the parameters then tuned on the results) and the Monte Carlo 50/50 test. Each script runs once on one example market over one period. Settings are fixed by hand, not optimised in code, but the examples look hand-picked.
- Costs: none. The README says: "The assumption is that all trades are frictionless. No slippage, no surcharge, no illiquidity." Every portfolio function buys and sells at the close (or the minute price) with no fee.
- Baselines: Heikin-Ashi compares with the S&P 500 and Awesome compares with MACD. No random-entry baseline.

## What it claims

Almost nothing in numbers; the README is explanation and charts. Unchecked quotes:
- Oil Money (`Oil Money project/README.md`): "In average, the return is around 2%, positively skewed. Yet, extreme values can go as far as -6% to 6%." and "The optimal holding period to maximize the return appears to be 9 trading days."
- Monte Carlo (`Monte Carlo project/README.md`): "the prediction accuracy is irrelavant to the numbers of simulation. The accuracy is more sort of tossing a coin".
- Smart Farmers (`Smart Farmers project/README.md`): "the model is a useful tool on around 65% of the crops", and "the excellent result of backtesting occurs because we are using God's eye view."

## What matters for us

None of these results could survive our test as written: no fees at all, no unseen days, one example chart each, and no random baseline. That is fine for what it is (a teaching book), but nothing here is evidence of an edge. On Gate, where the average trade earns about $0.00 before fees and costs about $0.23 per $100, a frictionless chart says nothing about profit. Most of these rules (MACD cross, RSI 30/70, Parabolic SAR, Bollinger, Heikin-Ashi, Awesome 5/34) are already in our signal grid or close to it.

Worth testing on our crypto data:
- **Dual Thrust / opening-range breakout adapted to crypto** - use the UTC day open (or the US stock-market open for stock tokens) with a 0.5 x 5-day range band, close before the day ends. A range-based breakout with a time exit is a different shape from our indicator signals.
- **Oil Money's "break out of a regression band, then follow it"** - e.g. regress an altcoin on BTC over 50 days and BUY when it breaks 2 standard deviations above its fitted value (momentum), exit after ~10 days or a fixed move. The README found the momentum version beat the "return to the line" version on NOK.

## Doubts

- Look-ahead in the code, so even the charts are too good: the Shooting Star rule requires the NEXT candle's high and close (`condition7`, `condition8` use `shift(-1)`) and compares the body with the average body of the whole 21-year history (`condition3`); Dual Thrust's range for a day includes that day's own high and low (`rolling(rg)` over daily bars that include the current day).
- In Pair trading, the band is the z-score at the moment cointegration starts plus/minus the gap's standard deviation in PRICE units, which mixes two scales; not the textbook +/-1 z.
- In Heikin-Ashi the buy fires on a strongly FALLING candle (HA open above HA close) and the sell on a strongly rising one, which is the opposite of the usual Heikin-Ashi trend rule the README points to; I report the code as written.
- The RSI script's `main` runs only the plain 30/70 rule; the head-and-shoulders function is never called.
- I did not read the Oil Money scripts for CAD, COP, NOK, RUB, the iron-ore and oil-production map scripts, or the two projects kept in other repos.
