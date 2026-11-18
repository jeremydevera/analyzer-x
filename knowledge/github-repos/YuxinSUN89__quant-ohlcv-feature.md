# YuxinSUN89/quant-ohlcv-feature

- Link: https://github.com/YuxinSUN89/quant-ohlcv-feature
- What it is: a library of 540 indicator formulas ("features" or "factors") computed from candles, one small Python file each, meant as inputs for a machine-learning model. It ships no strategy and no backtest.
- Stars, last push, licence: 132 stars, last push Oct 26, 2026, no licence on GitHub (one file, `volume_feature/QuoteVolumeMean.py`, carries "Copyright reserved. This code is for personal learning use only. Copying, modification, or commercial use without authorization is prohibited."). Not archived.
- Markets and timeframes: any candles. The README says "cryptocurrency and equity markets". The sample file `data/btcusd_data.csv` is BTC/USD 1-minute candles: 143,197 rows, every minute from Sep 21, 2013 to Dec 29, 2013 (99.4 days), with columns open, high, low, close, volume, quote_volume and taker_buy_quote_asset_volume (the column names a Binance download uses).
- Read: `README.md`, `requirements.txt`, the full list of 552 files, and the code of `momentum_feature/Bias.py`, `G106.py`, `AncRet.py`, `WinRate.py`, `composite_feature/FearGreed_Yidai_v1.py`, `liquidity_feature/BidaskSpread.py`, `trend_feature/BottomFractal.py`, `trend_feature/Turtle.py`, `volatility_feature/DcSignal.py`, `volatility_feature/KcSignal.py`, `volume_feature/QuoteVolumeMean.py`. I also searched all 540 files for ways a formula could read future candles (see "How it tests them"). I downloaded the files as data and ran nothing from them.

## The strategies

There are none: no labels, no model, no entry or exit rule, no stop or target, no position size. The files whose names end in "Signal" (`DcSignal`, `KcSignal`, `MaSignal` ...) return a number, not a buy or sell.

Every file has the same shape: `df = signal(df, n, factor_name)` adds one column computed over the last `n` candles.

**The feature families (my count of the files, which matches the README)**

| family | files | what it measures, in plain words |
|---|---|---|
| momentum (`momentum_feature/`) | 240 | how fast and how far price moved: RSI, MACD, stochastic (KDJ), CCI, rate of change, "bias" (distance from an average), CMO, Fisher, KST, Coppock, and about 100 numbered formulas `G*.py` / `H*.py` "ported from a broader factor reference" |
| volatility (`volatility_feature/`) | 107 | how wide the swings are: Bollinger bands and width, ATR, Keltner and Donchian channels, envelopes, candle shadows, amplitude, rolling standard deviation |
| volume (`volume_feature/`) | 82 | buying and selling pressure: OBV, money flow (CMF, MFI), force index, price-volume trend, taker-buy ratio, volume ratios |
| trend (`trend_feature/`) | 73 | direction: moving averages (simple, EMA, DEMA, TEMA, Hull, T3, KAMA, VIDYA), ADX, Aroon, Ichimoku, regression slopes, Turtle channel |
| price (`price_feature/`) | 19 | price levels: VWAP, typical price, distance from the N-day high, rolling drawdown, price percentile |
| composite (`composite_feature/`) | 11 | mixes of the above (for example `FearGreed_Yidai_v1`, `Adx+mtm`, `CoppAtrBull`) |
| liquidity (`liquidity_feature/`) | 8 | how costly or thin trading is: Amihud illiquidity, a bid-ask spread estimate |
| **total** | **540** | |

Some formulas, with their real numbers:
- `Bias.py`: close ÷ average of the last n closes, minus 1.
- `G106.py`: close minus the close 20 candles ago (it ignores `n`; the 20 is fixed in the code).
- `WinRate.py`: share of the last n candles that closed higher.
- `Turtle.py`: how far the close broke out of the n-candle channel of the highest and lowest open-or-close (moved back one candle), divided by the channel's width; 0 inside the channel.
- `KcSignal.py`: where the close sits inside a Keltner channel, (close - EMA(n) + 2 x ATR) ÷ (4 x ATR): 0 at the lower band, 1 at the upper.
- `DcSignal.py`: close minus the middle of the n-candle Donchian channel.
- `AncRet.py`: above the n-candle average, the distance to the lowest close of the last 30 candles; below it, the distance to the highest (30 is fixed; n must be 30 or less).
- `FearGreed_Yidai_v1.py`: true range ÷ the n-candle average close, split into up-candle and down-candle parts, smoothed by weighted averages over n and 2n, then the difference of the differences, smoothed again over n.
- `BidaskSpread.py`: the EDGE estimate of the buy-sell gap from open, high, low and close alone (Ardia, Guidotti & Kroencke, Journal of Financial Economics 161, 2024), over a rolling 1,000-candle window, then averaged over n. Output 0.01 = a 1% gap.

20 files need TA-Lib; 79 need `quote_volume` or taker-buy volume (13 of them taker-buy volume, which plain exchange candles may not carry).

## How it tests them

- No tests, no backtest, no train/test split, no costs, no baseline. Nothing in the repo shows that any feature predicts anything.
- Look-ahead check (my own search of all 540 files): no negative shift (`shift(-`), no centred window (`center=True`), no back-filling, and the rank-style features rank inside a window ending at the current candle. So each value uses only the current and earlier candles. It does use the current candle's close, so a trade built on it can only enter on the next candle.

## What it claims

Quoted, unchecked:
- Repository description: "a collection of 540+ features/factors drawn from academic publications and leading industry reports".
- `README.md`: "A modular library of **540+ technical indicator implementations** for quantitative feature engineering on OHLCV (Open, High, Low, Close, Volume) financial data. Designed for use in machine learning pipelines for cryptocurrency and equity markets."
- `README.md`, composite section: "Multi-factor signals combining signals across categories for stronger predictive features."

There is no profit or accuracy claim.

## What matters for us

On Gate, across millions of backtested strategies, the average trade earns about $0.00 before fees, and fees plus the buy-sell gap cost about $0.23 per $100 trade; strategies we chose did no better than random entries on days they were not chosen on.

This repo has no results to survive or fail that test: it is a box of inputs. Our own finding is that signals built from candles alone earned about nothing before fees, and these 540 are more of the same kind (many are near-copies: 18 files named "Bias...", 12 with "Cci" in the name). Feeding all 540 into a model raises the risk of finding a lucky pattern, so any use must go through our unseen-days and random-entry checks.

Ideas worth testing on our crypto data:
1. **`BidaskSpread.py` (the EDGE gap estimate) to price days we have no recorded order book for.** Our real-price trades start Oct 17, 2026; older trades pay each coin's usual gap. Measure EDGE on 1-minute candles over the days we DO have recorded books, and check how close it comes to the recorded gap, coin by coin. If it tracks well, it could give older days a gap of their own instead of one usual figure.
2. **`Turtle.py` / `DcSignal.py` as the entry of the cheap-coin trend test** (a close outside the previous n-candle channel), since a channel breakout with a trailing stop on low-cost coins is our current best candidate.

## Doubts

- I read 11 of the 540 files; the rest I only searched for future-reading patterns, not for correctness.
- **Bug: `trend_feature/BottomFractal.py` overwrites the caller's `close` and `low` columns with their 3-candle averages and then deletes both columns** (`df.drop(columns=['close', 'low'], ...)`). Any feature computed after it in the same table gets no prices or wrong prices.
- The README lists `Pmarp_Yidai_v1.py` as composite, but the file is in `momentum_feature/`; `composite_feature/Mtam.py` is not in the README's table.
- "Drawn from academic publications" is true for a few (EDGE names its paper); most files name no source, and the `G*` / `H*` numbering suggests a factor list from a Chinese quant course rather than papers.
- No licence: reusing the code is not clearly allowed. Re-writing a formula from its description is the safe way.
- The sample BTC file covers only 99 days of 2013, so it is a format example, not test data.
