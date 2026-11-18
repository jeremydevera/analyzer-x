# crypticalgo/XGTraderAGI---Training-and-Model-Only-XGBOOST-

- Link: https://github.com/crypticalgo/XGTraderAGI---Training-and-Model-Only-XGBOOST-
- What it is: an XGBoost model that learns to say whether, on the CURRENT candle, MACD is above its signal line and the close is above a 5-candle average - a rule it is handed the answer to - plus a toy backtest with no fees on prices that were turned into z-scores.
- Stars, last push, licence: 8 stars, last push Aug 11, 2023, no licence file (the README says MIT; GitHub reports none).
- Markets and timeframes: crypto, Binance USDT futures. Training: 3-minute candles of BTC, ETH, BNB, ADA, LTC and XRP (BTC from Jan 01, 2020 12:00am to Jul 30, 2023 11:57pm; ADA from Jan 31, 2020; XRP to Jul 31, 2023 4:24am). Signals and backtest: 5-minute candles of BTC (245 rows, Jul 30, 2023) and XRP (779 rows, Jul 29-31, 2023).
- Read: `README.md`, `main.py`, `BackTest.py`, `data_downloader.py`, `model_metrics.txt`, `model_params.txt`, and the first/last rows of the data files. NOT read or opened: `models/5momo101.pkl` (a 30 MB pickled model; a pickle can run code when loaded, so it was not touched), and the linked crypticalgo.com article.

## The strategies

**The inputs** (`main.py` `generate_features_and_labels`, same copy in `BackTest.py`), 13 columns: Close; EMA 5; MACD line and signal line with FAST settings (fast 3, slow 9, signal 9 by the `ta` library's default); RSI 6; Bollinger upper and lower band (5 candles, 2 standard deviations); VWAP summed from the first row of the file; a "Head-Shoulders" flag; previous close; previous volume; ATR 14; rate of change over 3 candles.

**The label:** 1 when MACD line > signal line AND close > EMA 5 on the same candle, else 0. It is a description of the current candle, not a forecast - and the model is given Close, EMA_5, MACD_line and Signal_line, the exact four numbers the label is made from.

**The model** (`train_model`)
- XGBoost classifier, settings searched by `BayesSearchCV` over 150 tries, 7 folds, scored by ROC-AUC. Search ranges: depth 3-10, gamma 0-5, column sample 0.5-1, learning rate 0.01-0.05, 500-1,000 trees, min child weight 1-10, subsample 0.5-1, L2 0.01-1, L1 0.01-1, GPU.
- Chosen (`model_params.txt`): column sample 0.8732, gamma 0, learning rate 0.05, depth 10, min child weight 1, 1,000 trees, L1 0.01, L2 0.01, subsample 0.5.
- Class weights: label 1 weighted 1, label 0 weighted 0.5.

**Signals** (`generate_signals`): predict 1 = "Buy", 0 = "Sell"; a repeat of the last signal becomes "Hold". In `main_generate_signals` the model is re-run on a sliding 20-row window and the last answer kept.

**The backtest** (`BackTest.py`), on XRP 5-minute candles
- Every candle: if the model says 1, close any short and buy 1 unit at the close; if it says 0, close any long and short 1 unit at the close.
- Starting balance 1,000. No stop, no target, no fee, no slippage, no funding. Units are added every candle while the signal stays the same (long only if the balance can pay).
- Leverage: none modelled.

## How it tests them

- Split: `train_test_split(test_size=0.2, random_state=42, stratify=labels)` - a RANDOM 80/20 shuffle of 3-minute candles, so test candles sit between training candles from the same minutes.
- All six coins are glued into one table before indicators are worked out, so averages run across the join from one coin into the next.
- Before any indicator, `preprocess_data` fits a StandardScaler on the WHOLE file and replaces the prices with z-scores. The backtest then trades those z-scores as if they were prices (they can be negative).
- Settings are chosen by cross-validation inside the training part only. The test part is used once for the scores.
- No costs, no buy-and-hold, no random baseline.

## What it claims

Unchecked by us.

- `model_metrics.txt`: "Accuracy: 0.8107315891472868, Precision: 0.9591620669309792, Recall: 0.5662769839797117, AUC-ROC: 0.7746427811422808"
- The README's article link is titled "money-printing-trading-bot-for-cryptocurrency-using-xgboost-machine-learning".
- `BackTest.py` prints `"Final balance:$"` but no result is saved in the repo.
- The repo's own description: "Please note this is not a full bot only ML Model."

## What matters for us

On Gate the average trade earns about $0.00 before fees and pays about $0.23 per $100 in fees and buy-sell gap, and chosen strategies did no better than random entries on unseen days. This repo could not survive that: it charges nothing, shuffles past and future candles together, has no baseline, and the "81% accuracy" is the model re-deriving a rule from its own inputs, not seeing the future. Its backtest flips long/short on every 5-minute candle; at our $0.23 per $100 round trip that alone would cost far more than a 5-minute move usually pays.

Ideas worth testing: none from the model. If anything, the fast MACD (3/9/9) with an EMA 5 filter is a quick trend-following entry we could add to the signal registry and measure like any other - but it is a plain indicator rule, and our Pro Trader and confluence research already found such rules lose after costs.

## Doubts

- The "Head-Shoulders" flag looks at `Close[i+1]` and `Close[i+2]` - two candles in the FUTURE - and is not a head-and-shoulders shape at all (it is down, then up, then up). This is a direct look-ahead in the inputs.
- `close_position` adds `price * abs(position)` to the balance for both longs and shorts, so closing a short ADDS money instead of paying it back: the backtest's balance is wrong even before the z-score prices.
- `evaluate_strategy` turns "Hold" into 0 before scoring, so the reported accuracy mixes the model with the Hold rewrite.
- VWAP is a running sum from the first row of a multi-year, multi-coin file, so it means nothing as a trading level.
- I did not open the pickled model or the external article.
