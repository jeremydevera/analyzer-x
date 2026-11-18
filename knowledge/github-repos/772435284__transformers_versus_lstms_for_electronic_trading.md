# 772435284/transformers_versus_lstms_for_electronic_trading

- Link: https://github.com/772435284/transformers_versus_lstms_for_electronic_trading
- What it is: a student project comparing transformer models (Autoformer, Informer, Reformer, FEDformer, Transformer) with LSTM-type models for predicting whether the ETH or BTC order-book middle price goes up, sideways or down over the next 20-100 order-book updates, with a simple backtest.
- Stars, last push, licence: 22 stars, last push Dec 04, 2023, no licence.
- Markets and timeframes: ETH-USDT and BTC-USDT order-book snapshots (10 levels each side), 12 days Jul 03-14, 2022, 10,255,344 snapshots for ETH (`lob_data_process/data_preprocess.ipynb`) — several per second. The exchange is not named (data "collected by kdb").
- Read: `README.md`, `run.py`, `exp/exp_main.py`, `utils/backtestor.py`, `data_provider/data_loader.py`, `models/DLSTM.py`, `models/LSTM.py`, `scripts/classification_script/LSTM.sh`, `scripts/classification_test_script/LSTM.sh`, `lob_data_process/generate_label.ipynb`, `lob_data_process/data_preprocess.ipynb`, `debug.ipynb`. Branch list (`main`, `price`, `price_diff`). Not read: the other model files and the `price` / `price_diff` branches.

## The strategies

One prediction task, nine models, one trading rule.

- Inputs (`data_preprocess.ipynb`): middle price = (best bid + best ask) / 2, its log, and bid-ask volume imbalance at each of the 10 levels, `(bidVol - askVol) / (bidVol + askVol)`, plus the imbalance of all 10 levels summed. Scripts use 41 input columns (`--enc_in 41`), `debug.ipynb` uses 11. Scaled with a standard scaler fitted on the training rows.
- Window: the last 100 snapshots (`--seq_len 100`).
- Label (`generate_label.ipynb`, "smoothing label"): l = (average of the NEXT k middle prices − average of the LAST k middle prices) / average of the last k. k = 20, 30, 50, 100 snapshots (`label_2` to `label_5`). Up if l > alpha, down if l < −alpha, else sideways; the notebook shows **alpha = 0.000092 (0.0092%)** for k = 100.
- Models: LSTM (2 layers, 64 hidden, `run.py`), DLSTM (the author's own: split the series into trend = 25-step moving average and remainder, an LSTM on each, add, then a linear layer to 3 classes — `models/DLSTM.py`), CNN-LSTM, MLP, Transformer, Informer, Autoformer, Reformer, FEDformer. Adam, learning rate 0.0001, batch 64, 10 epochs, early stop after 3 epochs without a better validation loss.
- Trading rule (`utils/backtestor.py`): predicted "up" → buy if flat, or close a short; predicted "down" → sell short if flat, or close a long; "sideways" → do nothing. A close does not reverse — it goes flat and waits for the next signal.
- Fill: at the **middle price 5 snapshots later** (`trade_delay=5`).
- Exit: only on the opposite signal. No stop, no target.
- Size: 1 unit, returns compounded; no leverage.
- Fee: **0** (`trade_fee=0.00000`).

## How it tests them

- Split by position: first 5,110,211 snapshots train, the next ~2.56 million validation (used for early stopping), last 2,580,162 test (~3 of the 12 days) (`data_loader.py`).
- Each model is trained once and scored once on the test days.
- Costs: none — zero fee, trades at the middle price (no spread), no funding.
- Baselines: the nine models against each other; no buy-and-hold, no random entries.
- "Sharpe ratio" is computed from **3 numbers** (the running total at two fixed row numbers and at the end, `exp_main.py` `backtest`), annualised with 365.

## What it claims

README, quoted: "A new model called DLSTM is developed for this task and outperforms other models." The result tables are only images on Google Drive (linked in the README), not text in the repo, so I could not read the numbers. Unchecked.

## What matters for us

Our own measurement on Gate: the average trade earns about $0.00 before fees, fees plus the buy-sell gap cost about $0.23 per $100 trade, and chosen strategies did no better than random entries on days they were not chosen on.

This cannot survive that. It charges **no fee and no spread**, and the move it labels as "up" is 0.0092% — about **25 times smaller** than our 0.23% round-trip cost — so even a perfect prediction of it would lose money for us. It does keep the test days apart (last 3 of 12 days), but 3 days of one coin in July 2022 is not enough, and there is no random or buy-and-hold baseline.

Idea worth testing, if any: **order-book volume imbalance** (bid size vs ask size at the top levels) as a filter on entries we already take on 15m and slower — "don't buy when the book is heavily ask-side". Our recorder (`app_books`) keeps the book each minute; whether it keeps the level volumes this needs would have to be checked first.

## Doubts

- `models/LSTM.py` builds `nn.LSTM(...)` without `batch_first=True` but feeds it batch-first data, so the plain LSTM mixes up samples and time steps; that alone could make LSTM look worse than DLSTM.
- `utils/backtestor.py` comments say class 0 is "stationary" and 1 is "down", but the label notebook makes 0 = down and 1 = sideways. The code's behaviour matches the labels; the comments are wrong.
- The "Sharpe" from 3 data points is meaningless, and its first daily figure subtracts 1 twice (`daily_pnl.append((daily_culmulative_pnl[0] -1)/1)` after already taking `- 1`).
- Only the alpha for k = 100 is visible; the thresholds for the other horizons are not in the notebook.
- `data_preprocess.ipynb` drops columns 1-40 (the raw book levels), but the label notebook later inserts columns at position 42 and the scripts expect 41 inputs; which file the scripts actually used is unclear.
- The results images were not read.
