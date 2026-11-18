# Marshal-Kalynchuk/crypto-lstm-prediction

- Link: https://github.com/Marshal-Kalynchuk/crypto-lstm-prediction
- What it is: one Colab notebook that builds 15 technical indicators on hourly crypto candles, trains a 4-layer LSTM to say buy / sell / hold, and simulates trading its predictions.
- Stars, last push, licence: 4 stars, last push Jul 10, 2025, MIT.
- Markets and timeframes: SOL/USD (main), with ETH/USD and BTC/USD added in a "multi-set" version; CSV files resampled to **1 hour** (`freq = 'H'`). The data source is not named (files `/content/datasets/solusd.csv` etc.).
- Read: `README.md` and every cell of `lstm.ipynb` with its saved outputs.

## The strategies

One strategy: LSTM classifier → buy / sell / hold → fixed take-profit / stop-loss trade.

- Inputs (cells 8, 10, 15): log return, upper and lower wick length, volume, and indicators from the `ta` library with short / medium / long windows 6 / 12 / 24 hours: RSI(6), stochastic(6), rate of change(6), money flow index(6), mass index(6, 12), ATR(6), CCI(6), MACD difference(6, 12), ADX(12), vortex(12), DPO(12), KST signal, parabolic SAR, force index. Scaled with outlier removal (3x the middle range) and a robust scaler fitted on the training part only (cell 12).
- Window: the last 48 hours (`n_past = 48`).
- Model (cell 36): 4 stacked LSTM layers of 100 units, dropout 0.2 after each, softmax output with 3 classes; Adam, categorical cross-entropy, class weights "balanced", early stopping patience 7, learning-rate cut patience 4. Batch 64, 10 or 25 epochs. Trained with a 5-fold time-series split inside the training part. One run first squeezes the features with PCA to the components holding 95% of the variance.
- Label (cells 10-11): uses a column called `log_return_future = -log(close / close 6 bars earlier)` (`n_future = 6`). With thresholds `([0.012, 0.03], [-0.03, -0.012])`: a value between -3% and -1.2% is one class, between +1.2% and +3% the other, everything else "hold"; any hour whose ATR is above the 75th percentile of the whole file is also forced to "hold" (`ATR_HIGH_VOL_HOLD = 0.75`).
- Trading rule (cell 45): the class coming from -1 is mapped to **"buy"** and +1 to **"sell"** (`label_to_action`). Because of the minus sign above, "buy" means the last 6 hours rose 1.2-3%, i.e. a momentum entry.
- Entry: at the hour's close when flat (`simulate_trades`, cell 41). Long or short.
- Exit: take profit or stop loss, checked on each later hour's close only.
- Size: all capital each trade (`risk_capital_percentage = 1`), starting capital 100,000; no leverage.
- Cost: 0.25% per side in the grid search (`transaction_cost_percentage = 0.0025`), 0.64% per side in the final run.
- Take-profit / stop-loss chosen by grid search: TP 3% to 10% in 0.5% steps, SL 2% to 5.5% in 0.5% steps, keeping the pair with the highest final capital (`grid_search_simulate_trades`).

## How it tests them

- Split: first 80% of hours to train, last 20% held back (`split_data_test_train`, `test_ratio=0.2`); a 5-fold time-series split inside the 80% for training.
- **The take-profit / stop-loss grid is searched on the held-back predictions themselves** — the test days choose the settings.
- Costs: 0.25% or 0.64% per side (higher than ours); no funding (spot USD pairs), no separate spread.
- Baselines: none — no buy-and-hold, no random entries.

## What it claims

Quoted from saved outputs (unchecked):
- Cell 44, hold-out classification: "Accuracy on hold-out test set: 0.89", "F1 Score on hold-out test set: 0.90". Cell 48: "Accuracy on hold-out test set: 0.90".
- Cell 22 (random forest on PCA features): "accuracy 0.88".
- Cell 45, grid search at 0.25% per side: "Average Success Rate: 0.43283582089552236", "Average Final Capital: 153266.35333199802", "Average Stop Loss: 0.05", "Average Take Profit: 0.09999999999999996".
- Cell 45, final run at 0.64% per side: "Best parameters: Take-Profit: 5.00%, Stop-Loss: 3.00%", "Success rate: 51.69%", "Final capital: $24807.55" (from 100,000).
- README: "Although this LSTM-based strategy did not yield a profitable backtest here, the end-to-end process ... offers a solid foundation for future experimentation".

## What matters for us

Our own measurement on Gate: the average trade earns about $0.00 before fees, fees plus the buy-sell gap cost about $0.23 per $100 trade, and chosen strategies did no better than random entries on days they were not chosen on.

Nothing here survives that, and the author says so: at 0.64% a side it lost 75% (100,000 → 24,807.55). The +53% grid-search result is chosen on the very days it is scored on, with no baseline. The 89-90% "accuracy" is not prediction (see Doubts): the label is the **past** 6-hour move, which the model can read from its own window. It does charge costs, but it does not test on truly unseen days and has no buy-and-hold or random comparison.

One idea worth a cheap test on our rows: **skip the most volatile hours** — the notebook forces "hold" when ATR is above its 75th percentile. On our data that is a mask on existing trades (ATR percentile measured only from candles before the entry, never the whole file).

## Doubts

- **The label looks backwards.** `df['log_return_future'] = -np.log(df['close'] / df['close'].shift(n_future))` uses the close 6 hours EARLIER (`shift(6)`), so it is minus the past 6-hour return, not a future one; and `create_windows` takes the label at `end_ix - 1`, the last hour inside the input window. The model is graded on something it can work out from what it sees, which explains the 0.89-0.90 accuracy.
- The final run passes `average_stop_loss` (5%) to the simulator but prints "Stop-Loss: 3.00%" — the printed setting is not the one that ran.
- The ATR "hold" cut uses the 75th percentile of the whole file, test part included.
- The notebook was run out of order: cell 45 reads `df['close']` after cell 19 reassigned `df` to a BTC frame with renamed columns, so which coin's prices were simulated is unclear.
- "hold" is also given to moves bigger than 3%, so the biggest moves are never traded.
- The data source and exact dates are not stated (the multi-set output starts at Feb 26, 2021).
