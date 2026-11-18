# jwallbridge/translob

- Link: https://github.com/jwallbridge/translob
- What it is: the code pieces and paper ("Transformers for limit order books", James Wallbridge, Feb 28, 2020) for TransLOB, a convolution + transformer model that predicts whether a stock's middle price goes up, sideways or down over the next 10-100 order-book events.
- Stars, last push, licence: 125 stars, last push Aug 09, 2020, no licence.
- Markets and timeframes: the public FI-2010 dataset — 5 Finnish stocks on Nasdaq Nordic (Helsinki), 10 trading days, 10 order-book levels each side, one row per order-book event (not time bars).
- Read: `README.md`, `python/LobTransformer.py`, `python/LobFeatures.py`, `python/LobPosition.py`, `python/LobAttention.py`, and the full text of `TransLOB.pdf` (16 pages). There is no training script, data loader or backtest in the repo.

## The strategies

No trading strategy — only a direction classifier.

- Inputs (paper p. 5): the last **100 order-book events**, each a vector of 40 numbers (price and size at 10 ask and 10 bid levels); scaled by the previous day's mean and spread. The 104 hand-made FI-2010 features are not used.
- Label (README and paper p. 5): r = (average of the next k middle prices − middle price now) / middle price now; **up if r ≥ 0.002 (0.2%), down if r ≤ −0.002, else sideways**; k = 10, 20, 50, 100 events.
- Model (`LobFeatures.py` `lob_dilated`, paper pp. 6-8): 5 causal 1-D convolutions, 14 filters, kernel 2, dilation 1, 2, 4, 8, 16, ReLU; layer norm; a one-number position ramp from −1 to +1 added (`LobPosition.py`), giving 15 numbers per event; 2 transformer blocks with **shared weights**, 3 attention heads, masked so each event only looks at earlier ones (`LobAttention.py`), feed-forward width 60; then flatten → dense 64 with ReLU and L2 → dropout 0.1 → softmax over 3 classes. Adam, learning rate 1e-4, batch 32, 150 epochs (paper Table 2).
- Entry / exit / stop / size: none — the paper never trades the predictions.

## How it tests them

- Split: first 7 days train, last 3 days test (paper p. 4 and p. 8). No separate validation set is described, yet the paper says "significant time was spend tuning hyperparameters of our model to negate overfitting" — the test days were probably used to tune.
- Costs: none (no trading).
- Baselines: published numbers of SVM, MLP, CNN, LSTM, CNN-LSTM, C(TABL) and DeepLOB on FI-2010; the CNN was re-trained only for k = 100. No buy-and-hold, no random entries, no money figures.

## What it claims

Quoted from `TransLOB.pdf` (unchecked):
- Abstract: "This architecture is shown to significantly outperform existing architectures such as those using convolutional networks (CNN) and Long-Short Term Memory (LSTM) establishing a new state-of-the-art benchmark for the FI-2010 dataset."
- Table 3 (k = 10): "TransLOB 87.66 91.81 87.66 88.66" (accuracy, precision, recall, F1) against "DeepLOB [41] 84.47 84.00 84.47 83.40".
- Table 5 (k = 50): "TransLOB 88.12 88.65 88.12 88.20".
- Table 6 (k = 100): "TransLOB 91.62 91.63 91.62 91.61" against "CNN [34] 63.06 63.29 63.06 62.97".
- p. 10: "our architecture was notably sensitive to the initialization."

## What matters for us

Our own measurement on Gate: the average trade earns about $0.00 before fees, fees plus the buy-sell gap cost about $0.23 per $100 trade, and chosen strategies did no better than random entries on days they were not chosen on.

These results say nothing about money. There are no costs, no trades, no profit, no buy-and-hold or random comparison — only how often a class was guessed right. The predicted move (0.2% over the next 10-100 order-book events) is about the size of our round-trip cost, so a correct guess would roughly break even before any wrong ones. Ten days of five Finnish stocks with a 7/3 split and test-day tuning is a very small test.

Ideas worth testing on our crypto data: none directly. The only transferable piece is the input choice — **raw order-book depth (prices and sizes at several levels)** as a feature — and that needs per-event book data we do not keep; our recorder takes one reading a minute.

## Doubts

- The code does not run as committed: `LobTransformer.py` imports `from tLobAttention import MultiHeadSelfAttention`, but the file is `LobAttention.py`; the README admits "some assembly may be required".
- The attention code has no final output projection (W^O), which the paper describes on p. 6.
- FI-2010 accuracy has known problems in the literature (labels built with a smoothed future price, overlapping samples); not checked here.
- The PDF figures (training curves, attention maps) were not looked at.
