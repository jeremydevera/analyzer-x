# cbailes/awesome-deep-trading

- Link: https://github.com/cbailes/awesome-deep-trading
- What it is: a reading list (an "awesome list") of papers, code repositories and courses about deep learning and machine learning for trading; it holds links, not code.
- Stars, last push, licence: 2,071 stars, last push Aug 08, 2023, MIT (the README also offers CC-BY). Not archived. The newest paper on it is from 2020.
- Markets and timeframes: whatever each linked item covers; mostly stocks, a few crypto and limit-order-book (tick) papers.
- Read: `README.md` (all 202 lines, every entry). I did not open any linked paper or repository, so every one-line summary below comes from the title, the list's own description, and what I already know of the paper; none was re-checked here.

## The categories

122 links in all (my count):

| section | links | what is in it |
|---|---|---|
| Papers, general | 28 | mixed deep-learning trading papers, 2016-2020 (stock prediction, high-frequency nets, deep hedging, RL trading) |
| Meta analyses and reviews | 5 | surveys of ML in stock trading and forecasting |
| CNNs (image-style networks) | 3 | price charts turned into images; DeepLOB on order books |
| LSTMs (sequence networks) | 8 | next-price or trend prediction with recurrent networks |
| GANs (generator vs. judge networks) | 4 | generating or predicting price paths |
| High frequency | 4 | deep nets on tick and order-book data |
| Portfolio | 3 | RL for allocation and goal-based wealth |
| Reinforcement learning | 12 | agents that learn buy/sell/hold by trial and reward (Q-learning, policy gradient, pairs trading, FX) |
| Vulnerabilities | 1 | attacks on trading agents |
| Cryptocurrency (papers) | 1 | RL trading points for crypto |
| Behavioural and sentiment | 2 + 5 | investor behaviour; news and Twitter sentiment |
| Guides | 3 | YouTube and blog LSTM tutorials |
| Repositories | 15 + 2 (GAN) + 3 (crypto) | code: trading gyms, CNN/LSTM predictors, RL agents (PGPortfolio, RLTrader, tforce_btc_trader ...) |
| Datasets and simulation | 3 + 2 | Kaggle US stocks, Alpha Vantage, Quandl; simulated order streams |
| Presentations, courses, meetups | 4 + 3 + 1 | talks, Udacity / Quantra / Coursera courses |
| Further reading | 10 | blog posts (Medium, Towards Data Science, WildML) |

In strategy terms the list covers: next-bar price or direction prediction (LSTM, CNN, plain deep nets), chart-image classification, order-book prediction, reinforcement-learning agents that choose buy/sell/hold or portfolio weights, deep-learning-enhanced momentum (trend following), pairs trading, and news/social sentiment.

## Top 10 for learning trade signals

1. Enhancing Time Series Momentum Strategies Using Deep Neural Networks (Lim, Zohren, Roberts, 2019) — a network that sizes a trend-following bet, judged by risk-adjusted return rather than prediction accuracy: https://arxiv.org/abs/1904.04912
2. DeepLOB: Deep Convolutional Neural Networks for Limit Order Books (Zhang, Zohren, Roberts, 2019) — predicts the next mid-price move from the order book itself: https://ieeexplore.ieee.org/abstract/document/8673598
3. Deep Learning for Limit Order Books (Sirignano, 2016) — the earlier order-book paper that DeepLOB builds on: https://arxiv.org/pdf/1601.01987
4. A Deep Reinforcement Learning Framework for the Financial Portfolio Management Problem (Jiang, Xu, Liang, 2017) — an RL agent that spreads money across crypto coins, with its code at https://github.com/ZhengyaoJiang/PGPortfolio: https://arxiv.org/pdf/1706.10059
5. An Application of Deep Reinforcement Learning to Algorithmic Trading (Théate, Ernst, 2020) — a Q-learning trader on single stocks, compared with simple benchmark strategies: https://arxiv.org/abs/2004.06627
6. Evaluating the Performance of Machine Learning Algorithms in Financial Market Forecasting: A Comprehensive Survey (Ryll, Seidens, 2019) — what the published ML forecasting studies did and how they tested: https://arxiv.org/abs/1906.07786
7. Financial Time Series Forecasting with Deep Learning: A Systematic Literature Review: 2005-2019 (Sezer, Gudelek, Ozbayoglu, 2019) — a map of which deep-learning models were tried on which markets: https://arxiv.org/abs/1911.13288
8. Reinforcement learning in financial markets - a survey (Fischer, 2018) — a survey of RL trading papers and their pitfalls: http://hdl.handle.net/10419/183139
9. Classification-based Financial Markets Prediction using Deep Neural Networks (Dixon, Klabjan, Bang, 2016) — a deep net that classifies the next move of many futures at once from lagged prices: https://arxiv.org/pdf/1603.08604
10. Introduction to Learning to Trade with Reinforcement Learning (Denny Britz, 2018) — a plain blog introduction to framing trading as RL and why it is hard: http://www.wildml.com/2018/02/introduction-to-learning-to-trade-with-reinforcement-learning/

## What it claims

The list makes no performance claim of its own. Its description, quoted from `README.md`: "List of code, papers, and resources for AI/deep learning/machine learning/neural networks applied to algorithmic trading." The papers' own results are theirs and unchecked here.

## What matters for us

On Gate, across millions of backtested strategies, the average trade earns about $0.00 before fees, and fees plus the buy-sell gap cost about $0.23 per $100 trade; strategies we chose did no better than random entries on days they were not chosen on.

The list does not choose entries by whether they charge realistic costs, test on unseen days or beat a random or buy-and-hold baseline, and most of the 2016-2020 price-prediction papers it links report accuracy or returns before realistic costs. Expect most of them to fail our test; treat each as an idea to measure, not a result.

Ideas worth testing on our crypto data:
1. **Order-book features (DeepLOB, Sirignano).** We record every contract's order book 3 seconds into every minute, which is exactly the input these papers use. But their predictions are over seconds to minutes, where the move is usually far smaller than our ~0.23% round trip, so first measure how big the predictable move is against our cost.
2. **Trend following with the bet sized by recent volatility (Lim et al.)**: it fits our current best candidate (trend with a trailing stop on cheap coins); test volatility-scaled size against flat size.

## Doubts

- I did not open any linked paper or repository; the summaries are from titles and prior knowledge.
- The list stopped in 2023 and its papers stop in 2020; links were not checked here and some (ResearchGate, ScienceDirect, IEEE, Springer) are behind logins or paywalls. Quandl is now Nasdaq Data Link.
- The table of contents puts "Guides" under Repositories, but the Guides section sits inside Papers.
- Some linked crypto repos (for example RLTrader, tforce_btc_trader) are old hobby projects; their published results should not be trusted without re-measuring.
