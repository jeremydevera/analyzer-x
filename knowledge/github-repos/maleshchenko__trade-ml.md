# maleshchenko/trade-ml

- Link: https://github.com/maleshchenko/trade-ml
- What it is: a small LSTM model that reads the last 30 one-minute BTC candles and says "long", "short" or "neutral", with a simple backtest and a live signal stream from Binance.
- Stars, last push, licence: 1 star, last push Oct 26, 2026, no licence.
- Markets and timeframes: BTCUSDT on Binance, 1-minute candles (`config.py`: `SYMBOL = "BTCUSDT"`, `INTERVAL = "1m"`). Data comes from Binance's **spot** API (`https://api.binance.com/api/v3/klines`), although the backtest also goes short.
- Read: `README.md`, `config.py`, `dataloader.py`, `trade_model.py`, `train.py`, `evaluate.py`, `backtest.py`, `live.py`. Not read: the `tests/` folder, Docker files, `api.py`.

## The strategies

One strategy: an LSTM classifier with a probability threshold.

- Inputs (`trade_model.py`, `add_features`), 7 features per candle: 1-candle log return; volatility = 10-candle standard deviation of returns; volume z-score over 20 candles; 10-candle average minus 20-candle average of the close; 14-candle RSI; 14-candle ATR; volume % change. Each is scaled to mean 0 / spread 1.
- Window: the last 30 candles (`SEQ_LEN = 30`).
- Model: one LSTM layer, 64 hidden units, then a 3-way output with softmax (`LSTMModel`). Adam, learning rate 0.001, 10 epochs, batch 64; classes weighted by how rare they are (`compute_class_weights`: weight = total / count).
- Label (`create_labels`, horizon 10, target 0.005, stop 0.003): looking at the next 10 one-minute candles, **"long" if the highest high is more than 0.5% above this close AND the lowest low is less than 0.3% below it**; "short" is the mirror; everything else "neutral".
- Entry (`backtest`): when flat, go long if the model's long probability > 0.8 (`THRESHOLD = 0.8`) and above the short probability; short the mirror way. Entry at the candle's close, fee added to the price.
- Exit: take profit at **+1.5%** (`TAKE_PROFIT = 0.015`) or stop loss at **-10%** (`STOP_LOSS = 0.1`), checked only on each later candle's **close**. No time limit.
- Fee: 0.04% per side (`FEE = 0.0004`), applied to entry and exit price. No slippage, no funding.
- Size: whole balance on every trade, starting balance 1,000; compounding; no leverage.
- Data size: 10,000 one-minute candles by default (`TOTAL_POINTS = 10_000` in `config.py`, about 7 days); the README says 100,000.

## How it tests them

- Single split by position: first 80% to train, last 20% to test (`train.py`, `backtest.py`, `evaluate.py`). With 10,000 candles the test part is about 2,000 minutes (~1.4 days).
- The scaling averages are computed on the **whole** file, test part included, before the split (`train.py` calls `compute_normalization_params(df)` before `split`) — a small peek at the test days.
- `backtest.py --start-date/--end-date` can backtest any date range, including days the model was trained on; nothing stops that.
- Costs: 0.04% per side only. No slippage, no spread, no funding.
- Baselines: none — no buy-and-hold, no random entries. `evaluate.py` prints precision / recall per class only.

## What it claims

No performance numbers are published. The README's only claims are about method, quoted:
- "Backtesting assumes fixed fee structure and no slippage"
- "Real trading performance may differ from backtest results"
- Disclaimer: "It's impossible to predict price action reliably."
The README's example shows one live prediction "[0.13898478 0.01935222 0.84166306]" read as "84.2% chance of short (sell)". Unchecked.

## What matters for us

Our own measurement on Gate: the average trade earns about $0.00 before fees, fees plus the buy-sell gap cost about $0.23 per $100 trade, and chosen strategies did no better than random entries on days they were not chosen on.

This could not survive that. It charges 0.04% a side (about $0.08 per $100 round trip, a third of our real cost) and no spread; it tests on ~1.4 days of one coin with no buy-and-hold or random comparison; and the label (+0.5% before -0.3% within 10 minutes) is smaller than our cost would allow: a $0.50 target against $0.23 of cost is a 46% cost-to-target ratio, near our "fatal" line. It also trades a different rule from the one it learned (learns +0.5% / -0.3% in 10 minutes, trades +1.5% / -10% with no time limit).

One idea worth testing: **the confidence gate.** Instead of trading every signal, only trade when the model is very sure (here > 80%). On our side the equivalent is a cheap filter on existing rows (e.g. only take a signal when two independent rules agree) — but only on 15m and slower, where targets are big enough to pay the cost.

## Doubts

- The README and the code disagree: README says threshold 0.65 (then later 0.8), take profit 1%, stop 0.5%, 100,000 candles; the code says 0.8, 1.5%, 10% and 10,000.
- The model applies softmax and then trains with `CrossEntropyLoss`, which applies it again; this usually makes learning weak.
- `backtest.py` and `evaluate.py` read `data.csv` from the current folder, while `train.py` reads `data/data.csv` (`config.DATA_CSV`) — they may not even use the same file.
- Spot data with short trades: shorting spot BTC is not possible without margin, and perpetual funding is ignored.
- Exits on the close only: a stop or target touched inside a minute and recovered is missed.
- I did not read the tests, so I cannot say what they check.
