# tzelalouzeir/XGB_CryptoStrategy

- Link: https://github.com/tzelalouzeir/XGB_CryptoStrategy
- What it is: a Bitcoin 5-minute script that uses XGBoost only to pick its five "most important" indicators, then goes long or short at 24x leverage when all five are past their average values, with a 1% target and 1% stop and no fees.
- Stars, last push, licence: 11 stars, last push Nov 02, 2023, MIT.
- Markets and timeframes: BTC-USD from Yahoo Finance, 5-minute bars, 30 days: Aug 27, 2023 12:00am UTC to Sep 25, 2023 4:25pm UTC (`btc30d.csv`).
- Read: `README.md`, `xgb_backtrader.py` (the only code file), the data file's first and last rows, and the result images `img/per.PNG` and `img/results.png`. NOT read: `img/features.png`, `img/roc.png`, and the three "related" repos the README links.

## The strategies

**The inputs: 12 indicators** (`xgb_backtrader.py`, `pandas_ta`): SMA 50, EMA 50, WMA 50, MACD 12/26 (signal 9 by default), RSI 14, Bollinger Bands 20 (2 standard deviations by default, giving lower/middle/upper, width and %B), ADX 14, Stochastic 14 (3, 3), Williams %R 14, rate of change 10, CCI 20, ATR 14. The model is also given Open, High, Low, Close, Adj Close and Volume.

**The label:** compare this bar's close with the close 2 bars AGO (`window_size = 2`): "long" if it rose, "short" if it fell, "neutral" if equal. It describes the last 10 minutes, not the next ones.

**The model's only job:** XGBoost with default settings (`eval_metric='logloss'`, `random_state=42`) is fitted to that label, then its feature importances are sorted and the top 5 names are kept. In the run shown in `img/results.png` those were WILLR_14, STOCHd_14_3_3, BBP_20_2.0, CCI_20_0.015, STOCHk_14_3_3 - all overbought/oversold oscillators.

**Entry rule** (`strategy_signal`)
- First, for each indicator, its average value over every bar labelled "long" and over every bar labelled "short" - over the WHOLE 30 days, the same days it then trades.
- Long when ALL five top indicators are ABOVE their "long" average; short when ALL five are BELOW their "short" average; otherwise nothing. Entry at that bar's close.
- At most 10 entries per 24 bars (24 five-minute bars = 2 hours; the code's comment calls it a day).

**Exit, stop, target:** target 1% (`long_tp_pct = 1.01`, `short_tp_pct = 0.99`), stop 1% (`long_sl_pct = 0.99`, `short_sl_pct = 1.01`), both checked only against bar CLOSES, and the trade is booked at that close (which can be past the 1%). An open trade is closed at the last bar.

**Size and leverage:** the whole balance on every trade, compounding, `leverage = 24`. Starting balance $1,000. A 1% move is therefore ±24% of the balance before costs.

## How it tests them

- The XGBoost score uses `train_test_split(test_size=0.2, random_state=42)`: a random shuffle of 5-minute bars.
- The trading run uses NO split at all: it trades the same 30 days the indicator averages and the top-5 choice were taken from.
- No fees, no slippage, no funding, no liquidation. No buy-and-hold or random baseline.

## What it claims

Unchecked by us.

- `img/per.PNG`: "Accuracy: 0.88", "ROC-AUC Score: 0.95", "Final Balance: $2825.02", "Total Return: 182.50%" (classification report on 1,698 test bars: 853 long, 845 short, 0.88 precision and recall on both).
- `img/results.png` (a different run): "Max Trades Per 24 Bar: 10", "Leverage: 24"; the balance line peaks above $10,000 around Sep 12-13, 2023 and ends near $3,000 on Sep 25, 2023.
- `README.md`: "Ensure to interpret the results in a historical context and not as financial advice."

## What matters for us

On Gate the average trade earns about $0.00 before fees and pays about $0.23 per $100 in fees and buy-sell gap, and chosen strategies did no better than random entries on unseen days. This result could not survive that. At 24x every trade moves 24 times its notional, so our $0.23 per $100 is about 5.5% of the margin per round trip - against a 1% target that is worth 24% before costs, a quarter of every win gone and every loss 5.5 points worse. It never tests on days it did not look at (the thresholds come from the same 30 days it trades), has no baseline, and does not model liquidation: at 24x a move of about 4.2% against the trade wipes the margin, and a close-only stop check on 5-minute bars can miss the 1% stop by more than that in a fast candle. The 0.88 accuracy is the model reading back the last 10 minutes, which its own inputs (ROC, Williams %R) already contain.

One idea worth a test, only as an ordinary signal: "all of Williams %R 14, Stochastic %K/%D 14-3-3, Bollinger %B 20 and CCI 20 agree" as a stacked overbought/oversold entry, with the cut-offs set on older days only, our real costs, and the random-entry bar. Our confluence research (Oct 22, 2026) already found stacked indicator confluences carry no edge over random entries, so expect the same.

## Doubts

- The two result images disagree ($2,825.02 against about $3,000 at the end), so they come from different runs; neither run's code state is pinned.
- `roc_auc_score(y_test, probabilities[:, 1])` treats a three-class problem as two-class; it only works because no "neutral" bar appears in the test sample shown.
- The averages for the entry rule are computed BEFORE `dropna()` and over every bar, including the bars later traded: a direct look-ahead.
- Yahoo's 5-minute BTC volume is 0 on the first rows of the file, so volume-based work on this data would be unreliable (the strategy does not use volume).
