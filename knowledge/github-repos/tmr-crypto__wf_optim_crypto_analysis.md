# tmr-crypto/wf_optim_crypto_analysis

- Link: https://github.com/tmr-crypto/wf_optim_crypto_analysis
- What it is: the code that turns an academic paper's results into its tables and charts; the paper tests a moving-average cross on Bitcoin with walk-forward re-tuning and asks how long the tuning and trading windows should be. The trading itself is computed in a companion repo, https://github.com/tmr-crypto/wf_optim_crypto (2 stars, last push Feb 11, 2026, no licence), which I also read.
- Stars, last push, licence: 3 stars, last push Feb 11, 2026, no licence file (all rights reserved by default). Authors: Tomasz Mroziewicz and Robert Ślepaczuk (University of Warsaw).
- Markets and timeframes: BTC (tuning), then BTC, ETH and BNB (unseen check), spot prices against the US dollar as far as the file names say. Built from 1-minute prices and resampled to 1, 5, 10, 15, 30 and 60 minutes; the unseen check runs on 60 minutes only.
- Read: this repo's `README.md`, `params.yaml`, `config.r`, `scripts/analyse_helper.r`, `scripts/bootstrap_helper.R`, `scripts/smooth_matrix.R`, and keyword lines of `reports/wf_optim_crypto_charts_table.rmd`. In the companion repo: `README.md`, `params.yaml`, `dvc.yaml` (first stages), `master/rcode/logic/strategy.r`, `strategy_param.yaml`, `WfHelper.r`, `WfHelper.yaml`, `helpers/metrics_helper.r`, `helpers/datetime_helper.r`, and steps `02`, `03`, `04`, `06`, `08`, `09` of `master/rcode/`.

## The strategies

**One strategy: an always-in-the-market EMA cross, re-tuned every few days** (`master/rcode/logic/strategy.r`, `strategy_param.yaml` in the companion repo)
- Inputs: the closing price of each bar, and exponential moving averages (EMA) of lengths `5, 7, 10, 15, 20, 30, 40, 50, 100, 150, 200` bars.
- Fast and slow are split at `ma_cutoff_int: 35`: fast = 5, 7, 10, 15, 20, 30; slow = 40, 50, 100, 150, 200. Every fast x slow pair is a candidate: **30 pairs**.
- Signal: if the fast EMA was above the slow EMA at the previous bar's close (`lag.xts(fast) > lag.xts(slow)`), hold **long (+1)**, otherwise hold **short (-1)**. It is never flat.
- Entry and exit: the position flips whenever the two averages cross. No stop, no target.
- Size: the whole account, 1x, long or short. No leverage.
- Profit per bar = position x the bar's log return, minus `fee_int: 0.001` (0.1%) for each unit of position change, so a flip from short to long pays 0.2% (the report's own words: "Each transaction incurs a 0.1% cost. Changing positions from short to long requires two transactions, resulting in a total cost of 0.2%").

**The walk-forward re-tuning** (`WfHelper.r`, `06_wf_calculate_indexes.r`, `08_wf_select_best_params.r`, `09_wf_eval_test.r`)
- A tuning window of T days is followed by a trading window of S days; the pair of 30 with the highest Sharpe ratio on the tuning window (`which.max`, ties to the first) trades the trading window; then everything moves forward by S days.
- The paper's real choice is T and S: each from `1, 2, 3, 5, 7, 10, 14, 21, 28` days = **81 window combinations**, x 6 bar sizes = 486 runs on the tuning period.
- The two window settings kept: **7 days tuning / 28 days trading** and **14 days tuning / 10 days trading**, on 60-minute bars.
- "Robust Sharpe Ratio" (`scripts/smooth_matrix.R`): to pick the window combination, each cell of the 9 x 9 Sharpe grid is replaced by (its own Sharpe + the average of its up-to-8 neighbours) / 2, so a lonely spike next to bad neighbours is marked down. This is an idea worth knowing: it prefers settings whose neighbours also worked.

## How it tests them

- **Two periods** (companion `README.md`): "global training" Jan 01, 2018 to Sep 30, 2019 (file `data_global_train_20180101_20190930.csv`), and "unseen" Oct 01, 2019 to Sep 20, 2021 (`data_unseen_20191001_20210920.csv`). The window lengths are chosen on the first period only and run **once** on the second. Inside each period, the EMA pair is chosen only on the days before the days it trades. So yes, there are real unseen days, at two levels.
- The settings learned on BTC are applied unchanged to ETH and BNB on the unseen period (a second check on coins never tuned on).
- Metrics also reported on a "clipped" span that drops 37 days at the front and 30 at the back (`day_clip_front: 37`, `day_clip_back: 30`).
- **Costs:** 0.1% per transaction, nothing else: no spread, no slippage, no funding (it is a spot price series, so funding does not apply, but a short on spot is not free in real life either). A cost check re-prices the same positions at `0.0005, 0.0007, 0.002, 0.003, 0.004, 0.005` per transaction (`get_cost_sensitivity_returns` in `scripts/analyse_helper.r`).
- **Baselines:** buy-and-hold of each coin over the same span (`12_unseen_data_strategy_stats` in `params.yaml`), and two kinds of random check, 1,000 runs each, seed 3 (`scripts/bootstrap_helper.R`): (a) the strategy's own runs of long and short shuffled into a random order, and (b) a random EMA pair drawn for every walk-forward step. Each prints the share of random runs whose Sharpe was at least the strategy's. This is close to our "random entries" bar, which is rare among these repos.

## What it claims

Unchecked, from the abstract in `README.md` (no result numbers are committed in the repo; the tables are built from a 76 MB download):
- "In the training period for Bitcoin, all combinations of walk-forward windows outperformed a Buy-and-Hold strategy."
- "During the testing period, the strategy performed similarly to Buy-and-Hold but with lower drawdown and a higher Information Ratio. Similar results were observed for Binance Coin and Ethereum."
- "a portfolio combining Buy-and-Hold with our strategies outperformed all individual strategies and Buy-and-Hold alone, achieving the highest overall performance and a 50% reduction in drawdown."
- "A conservative fee of 0.1% per transaction was included in all calculations. A cost sensitivity analysis was performed as a sanity check, revealing that the strategy's break-even point was around 0.4% per transaction."

## What matters for us

Our Gate measurement says the average trade earns about $0.00 before fees, and fees plus the buy-sell gap cost about $0.23 per $100 traded, so fees are the whole loss; and chosen strategies did no better than random entries on days they were not chosen on. This repo is the most honest of the six on testing: it has truly unseen days, a buy-and-hold bar and two random bars. Its cost of 0.1% a side (0.2% a round trip) is close to Gate's 0.075% taker fee each way plus a small gap on BTC, ETH and BNB, so on those three coins it is roughly realistic; on our thin coins (gaps of 0.5% and more) it would be far too low. Its own claim is modest: on the unseen 23 months it did about as well as simply holding the coin, and its break-even is about 0.4% a side. That fits our finding: a slow trend rule on the biggest coins can survive costs, but it did not clearly beat holding. Note the unseen period (Oct 2019 to Sep 2021) was a huge bull market, where an always-in long-or-short trend rule naturally looks good.

Ideas worth testing on our crypto data:
1. **The "robust" choice rule**: when picking settings, score each setting by itself plus the average of its neighbouring settings (here, nearby window lengths), so a lucky spike is not chosen. Our picks on older days lost on newer days; this is a cheap check of whether smoothing the choice helps.
2. **A 60-minute EMA cross, long or short, re-tuned every 10 to 28 days, on BTC, ETH and other coins with a buy-sell gap of 5 basis points or less**, judged against buy-and-hold and a random-pair-per-step bar. It matches our own best candidate (trend with a trailing exit on cheap coins).

## Doubts

- The result tables are not in the repo (they need the 76 MB Google Drive file), so none of the claims could be read as numbers.
- The data source (which exchange) is not named in the files I read; the raw CSVs are behind DVC links.
- `params.yaml` sets `performance_stat: sharpe` for choosing the EMA pair, while the abstract says the walk-forward is "based on the Robust Sharpe Ratio". From the code, the smoothing is applied to the 81-window grid (choosing the window lengths), not to the choice of EMA pair inside each step.
- I did not read steps `01`, `05`, `07` of the companion pipeline or the full report file.
- Shorting the spot coin at no cost is assumed; on a futures exchange the short would pay or earn funding.
