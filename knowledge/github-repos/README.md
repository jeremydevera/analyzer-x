# GitHub repos for learning trade signals — what each one does

Reviewed Nov 18, 2026: 36 GitHub repos and one GitHub topic page, found by three searches
(see `LINKS.md`). Six helpers each read six repos: the README, the file list, and the code that
makes the trading decision. Nothing from these repos was run or installed. Every result they
claim is the repo's own number, unchecked by us. One note per repo is in this folder as
`OWNER__REPO.md`. Each note gives the strategies with their real settings, how the repo tests
them, what it claims, what it means for us, and its doubts.

## The short answer

None of the 36 shows a trading edge that would survive our costs. On Gate, the average trade
earns about $0.00 before costs, and the fee plus the buy-sell gap cost about $0.23 for every
$100 traded. Most repos charge no cost at all, or choose their settings on the same days they
are judged on.

The few that tested themselves honestly found what we found:

- **stefan-jansen's book:** its best crypto setup of 2,807 lost 44.8% a year on the held-back
  years.
- **Danny-397:** crypto −44.6% against buy-and-hold's +10%.
- **Thomas-lcb:** −9.51% against a random agent's −9.30%.
- **tmr-crypto:** "about as good as holding the coin".
- **KennethMartin06:** 0 of 15 model-and-stock pairs beat buy-and-hold.
- **NehrenD:** every rule loses money once a 0.15% cost is charged.

## Backtested on our own market (Nov 18, 2026)

48 strategies from 22 of these repos were ported into the app (`tradingagents/gh_strats`) and run on
every Gate coin x 15m, 30m, 1h, 4h, 1d with every cost. All 48 lost money on days no setting was chosen
on (-$0.83 a trade over 10,977,658 trades, random entries -$0.65), and only 7 are above zero even
before costs. The full table and what it means: `RESULTS.md`; every row with its trades:
https://claude.ai/artifact/38jHY5XM5u2nuccx3jYYSq

## Every repo at a glance

"Costs" = does it charge fees and slippage. "Unseen" = does it judge on days it never used for
choosing settings.

| Repo | Main strategy | Costs | Unseen | Worth |
|---|---|---|---|---|
| stefan-jansen/machine-learning-for-trading | Book code: momentum and factor signals, linear and boosted-tree return prediction, LSTM and transformers; crypto case study on 19 Binance perpetuals, long-short every 8 hours on funding and premium features | yes (fee, slippage, funding) | yes, a 2024-2025 holdout opened once | high: the best example of honest testing, and it confirms "no edge" |
| PacktPublishing/Machine-Learning-for-Algorithmic-Trading-Second-Edition | Older 2nd edition of the same book: predict each US stock's next-day return, hold the top 25 long and the bottom 25 short daily | almost none | partly (the last 11-23 months; the LSTM chapters peek) | medium: frozen fork from Mar 05, 2023 |
| maleshchenko/trade-ml | LSTM on 1-minute BTC, label "+0.5% before −0.3% within 10 minutes", trades only above 80% sureness, 1.5% target / 10% stop | 0.04% a side, no slippage | weak (about 1.4 days, and the scaling peeks) | low |
| Marshal-Kalynchuk/crypto-lstm-prediction | 4-layer LSTM on hourly SOL with 15 indicators | 0.25-0.64% a side | no (target and stop chosen on the test days) | low: its 89% accuracy is a label bug |
| 772435284/transformers_versus_lstms_for_electronic_trading | Transformer vs LSTM predicting the ETH order-book middle price 20-100 updates ahead | no | yes (the last 3 of 12 days) | low: the move it predicts is about 25 times smaller than our cost |
| jwallbridge/translob | Convolution + transformer on Finnish stock order books, direction only | no trades at all | doubtful | low |
| ebrahimpichka/DeepRL-trade | PPO and DQN all-in long/flat/short on Google stock daily | 0.1% commission | no (the test days pick the reported model) | low |
| AI4Finance-Foundation/FinRL | RL agents (A2C, PPO, DDPG, TD3, SAC, TQC, CrossQ) on the Dow 30 daily, with a "turbulence" sell-everything switch | 0.1% a side, no gap | yes but short (Jan 01 - Mar 20, 2026, one run) | medium as a framework, no edge shown |
| AI4Finance-Foundation/FinRL-Tutorials | 13 tutorials; the ensemble strategy is the main one | mixed | mixed (the tuning notebook peeks) | low: its ensemble lost 3.9% a year |
| AI4Finance-Foundation/FinRL-Trading | Stocks only: quarterly ML stock picks, weekly rotation with −5% fixed and −10% trailing stops, monthly 12-month momentum | 0.1% | no (a hand-picked list chosen with hindsight) | low |
| Danny-397/RL-for-Crypto-and-stocks- | PPO sets a long/short position daily | 0.4% a round trip | yes, 10-30 runs against buy-and-hold and random | high as an honest negative result |
| TradeMaster-NTU/TradeMaster | RL platform: DeepScalper on BTC, Double DQN on BTC order books, execution, portfolios | gap via 5-level order book, but a typo fixes the fee at 0.005% | weak | low: an impossible −199.6% in its own example |
| Thomas-lcb/Deep-Reinforcemen-tLearning-Trading-Agent | PPO on BTC 1-minute, 200-minute wait after each trade | 0.1% a side | tuned on its test days; validation failed | medium: compares against a random agent; look-ahead bug in its 1-hour features |
| agiprolabs/claude-trading-skills | Recipes (EMA cross, RSI, z-score reversion, XGBoost up/down) and test methods (walk-forward with a gap, CPCV, deflated Sharpe, PBO) | 0.1-0.5% flat | made-up prices only | medium for the test methods (the deflated Sharpe in SKILL.md is wrong; the script is right) |
| sjev/twp | Course notebooks: moving-average cross, XLP open gap, VXX contango, nearest neighbours | almost none | one walk-forward test, lost money before costs | low |
| hudson-and-thames/backtest_tutorial | 50/252-day average cross on the S&P 500, sized by volatility | 0.20% (Sharpe 0.47 down to 0.33) | no | low |
| mindees/crypto-ai | Gone (GitHub answers 404) | - | - | none |
| tmr-crypto/wf_optim_crypto_analysis | 60-minute EMA cross on BTC, always in, re-tuned every 10-28 days | 0.1% a trade | yes (tuned on Jan 2018 - Sep 2019, run once on Oct 2019 - Sep 2021), against buy-and-hold and two random baselines | high: honest, and its "score a setting with its neighbours" trick |
| abailey81/Crypto-Statistical-Arbitrage | Altcoin pairs: trade when the gap is 2 standard deviations wide, close when it returns to normal | about 0.20% a pair trade | no (pairs picked on prices covering the whole test) | low: the 95% win claim is not believable |
| Log-zz-ikIO/crypto-signal | 2018 alert bot: daily RSI under 30 buy, over 70 sell | no | no backtest | none |
| je-suis-tm/quant-trading | 17 classic rules (average cross, pairs, London Breakout, Dual Thrust, Shooting Star, Oil Money ...) | no ("frictionless") | no, and two scripts read future prices | low, useful as a catalogue of rules |
| QuantConnect/Research | Buy stock funds when a fear index drops under its 10-day average; XOM/CVX pairs | no | no | low |
| NehrenD/algo_trading_and_quant_strategies | Average, Bollinger, breakout, two-average and RSI rules on rupee exchange rates | 0.15% | no | medium: every rule loses once costs are charged |
| topics/walk-forward-validation | The 30 most-starred repos on that topic, out of 222 | - | - | reading list; **the top repo looks like a fake: do not run it** |
| KennethMartin06/ml-based-algorithmic-trading-signals | Logistic, random forest, XGBoost, neural net and a blend on SPY/AAPL/MSFT, buy only when sure | 0.30% a round trip | yes (2022-2025) | high as an honest negative: 0 of 15 beat buy-and-hold |
| Ridwat/Project-3-ML-for-Predicting-Trading-Signal | Classifiers copy a MACD cross + RSI 30/70 rule on Tesla daily | no | no (random split) | none: its "100%" is always saying Hold |
| Huraira9913/trading-signal-ml | Random forest "up in 5 bars" on made-up prices | no | yes, but no trades | none |
| crypticalgo/XGTraderAGI---Training-and-Model-Only-XGBOOST- | XGBoost on 3-minute candles of six coins, learning a MACD + 5-candle-average rule it is fed | no | no, and one input reads 2 candles ahead | none |
| tzelalouzeir/XGB_CryptoStrategy | BTC 5-minute, long or short at 24x when five oscillators agree, 1% target / 1% stop | no fees, no funding, no liquidation | no (its "+182.50%" is look-ahead) | none |
| ahmedas91/ml-ohlcv-alpha-signals | Rank about 1,000 US stocks daily with 105 features, long the top tenth, short the bottom tenth | no | yes, one unseen year at a time 2013-2025 | medium: best spread about 1.56 basis points a day, far under our 23 per round trip |
| ethansilvas/sma-ml-trading-algorithm | Homework: two moving averages into a classifier on one thin ETF | no | no | none: it is buy-and-hold 97% of the time |
| Mun-Min/ML_Trading_Bot | The same homework with a small neural net | no | no | none |
| edtechre/pybroker | Backtest framework with honest walk-forward and a bootstrap luck check | its examples use $0 | yes (the method) | medium for the tools: 0.10% slippage turns its dip-buy from +18.02% to −8.66% |
| YuxinSUN89/quant-ohlcv-feature | 540 indicator formulas: momentum 240, volatility 107, volume 82, trend 73, price 19, composite 11, liquidity 8 | - | - | medium as a feature source; `BottomFractal.py` deletes your close and low columns |
| cbailes/awesome-deep-trading | Reading list, 122 links, mostly 2016-2020 papers, last updated Aug 08, 2023 | - | - | reading list |
| bernhardbrugger/awesome-ai-trading | Reading list, 139 links; a "backtests that lie" section matching our own lessons | - | - | reading list, the better of the two |

## Ideas worth testing on our own crypto data

These came from the notes. Each is a measurement to make, not a strategy to switch on.

1. **A stricter luck test for our rule sets.** Apply "deflated Sharpe", a bootstrap of a
   strategy's own returns, or "probability of backtest overfitting" (PBO) to the 24,480
   Forecast v4 rule sets. Sources: stefan-jansen, agiprolabs (script version), pybroker.
2. **Score a setting together with its neighbours.** A setting that only works at one exact
   number is luck. Source: tmr-crypto.
3. **Short-term reversal ranking across coins.** Rank coins by their last 1-day and 5-day
   return, buy the biggest losers and short the biggest winners. Check the spread before costs
   first. Source: ahmedas91.
4. **20-day breakout on our cheapest coins.** Buy above the 20-day high, sell below the 20-day
   low, only on coins with a small recorded buy-sell gap. This fits our current best candidate,
   cheap-coin trend. Source: pybroker examples.
5. **A spread estimate from candles alone (EDGE).** Check it against our recorded order books,
   so days before Oct 17, 2026 can be priced. Source: awesome-ai-trading.
6. **Funding as an entry filter.** Hold the side that receives funding. Sources: stefan-jansen's
   crypto case study, awesome-ai-trading.

## Warnings

- `topics__walk-forward-validation.md`: the top-starred repo on that topic,
  assansolution-cell/options-commander-cli, looks like a fake. It copies another repo's
  description, sends Windows users to an outside setup page, and got 153 stars in three days.
  Never run anything from it.
- The pickled model file in crypticalgo's repo was not opened, because loading a pickle can run
  code.
