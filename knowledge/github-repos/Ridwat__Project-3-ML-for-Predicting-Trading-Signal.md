# Ridwat/Project-3-ML-for-Predicting-Trading-Signal

- Link: https://github.com/Ridwat/Project-3-ML-for-Predicting-Trading-Signal
- What it is: a school assignment that teaches three classifiers to copy a MACD + RSI Buy/Sell/Hold rule on Tesla, which ends with only one Buy and no Sell in six years, so it shows nothing about trading.
- Stars, last push, licence: 0 stars, last push Oct 14, 2026, no licence.
- Markets and timeframes: Tesla (TSLA) stock, 1-day bars from Yahoo Finance, Jan 01, 2019 to Jan 01, 2025.
- Read: `README.md` and every cell of `Project_3_ML_for_Predicting_Trading_Signals.ipynb` (text and code). NOT read: the PDF report `pROJECT 3 - ML for Predicting Trading Signals.pdf`.

## The strategies

**The rule the models copy** (notebook, "MACD Buy/Sell Signals", "RSI Buy/Sell Signals", "Final Trading Signal")
- MACD: 12-day EMA minus 26-day EMA of the close, with a 9-day EMA of that as the signal line. MACD Buy = the MACD line crosses ABOVE the signal line on this bar (it was at or below on the previous bar). MACD Sell = crosses below.
- RSI 14: built by hand with `ewm(span=14)` averages of gains and losses (not Wilder's usual smoothing). RSI Buy = RSI below 30; RSI Sell = RSI above 70.
- Final label: Buy when MACD Buy AND RSI Buy on the same bar; Sell when MACD Sell AND RSI Sell on the same bar; Hold otherwise. Encoded Hold 0, Buy 1, Sell 2.
- The label describes TODAY's indicators; it is not about any future price.

**The inputs:** just three numbers - MACD, the signal line, RSI - the same numbers the label is made from.

**The models**
- Logistic regression, multinomial, `max_iter=500` (the README's words; the cell that fits it is missing from the notebook, only its report is printed).
- Random forest: 300 trees, `random_state=42`, no depth limit, `min_samples_split=2`, `min_samples_leaf=1`, trained on unscaled inputs.
- SVM with an RBF kernel, `C=1.0`, `gamma="scale"`, on standardised inputs.

**Entry, exit, stop, target, size, leverage:** none. Nothing is traded; the work ends at the classification report.

## How it tests them

- Split: `train_test_split(test_size=0.2, random_state=42)` - a RANDOM 80/20 shuffle of days, not time order, so test days sit between training days.
- No walk-forward, no costs, no fees, no money at all, no buy-and-hold or random baseline. Scaling is fitted on the training part only.
- Score: accuracy, precision, recall, F1 and the confusion matrix.

## What it claims

Unchecked by us.

- `README.md`: "The notebook reports extremely sparse actionable labels: one Buy and no Sell labels in the dataset. The saved test set contains 302 Hold examples and no Buy or Sell examples."
- `README.md`: "All three saved classification reports show 100% accuracy on that Hold-only test set. **This does not demonstrate useful Buy/Sell prediction.**"
- Notebook conclusion: "The MACD, MACD Signal Line, and RSI all contributed to the model, with importance values around 0.36, 0.36, and 0.28, respectively."

## What matters for us

On Gate we measured that the average trade earns about $0.00 before fees while fees plus the buy-sell gap cost about $0.23 per $100, and that chosen strategies did no better than random entries on unseen days. This repo cannot be held against that at all: it never trades, charges no costs, shuffles past and future together, and its "100%" is a model that always says Hold on a test set that only holds Hold days. The author says so in the README.

The one useful fact: requiring a MACD cross AND RSI under 30 on the SAME daily bar fired once in about 1,500 Tesla days - by the time MACD turns up, RSI has usually already climbed out of oversold. If we ever test this pair on crypto, the RSI condition needs a look-back ("RSI was under 30 within the last N bars, then MACD crosses up"), and our existing signal registry probably already holds that shape. Nothing else here is worth testing.

## Doubts

- The notebook prints the logistic regression report using `log_pred`, but no cell shown fits that model or makes `log_pred`; the notebook was edited after running.
- The notebook text has an unfilled placeholder ("[Usually RSI and MACD are among the most important; write what your bar chart shows ...]").
- The label is a function of the inputs plus the previous bar's MACD, so even with balanced classes this would measure copying a rule, not forecasting.
- I did not read the PDF report.
