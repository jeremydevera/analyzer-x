# abailey81/Crypto-Statistical-Arbitrage

- Link: https://github.com/abailey81/Crypto-Statistical-Arbitrage
- What it is: a very large student-style research project (it cites "PDF" coursework pages throughout) that collects crypto data from 32 exchanges and backtests coin-pair trading on hourly prices plus a BTC funding-rate and futures-curve strategy.
- Stars, last push, licence: 6 stars, last push Mar 15, 2026, MIT.
- Markets and timeframes: altcoin pairs (top ~50 coins by volume on big exchanges, ~25 DeFi coins on decentralised exchanges) on 1-hour candles; BTC perpetual funding and dated futures across Binance, Hyperliquid, dYdX, OKX, Bybit, GMX, Aevo, CME, rebalanced hourly. Funding normalised to 8 hours (`config/config.yaml`).
- Read: `README.md`, `docs/methodology.md`, `config/config.yaml`, and searched in `phase2run.py` (the pair-trading engine), `strategies/pairs_trading/baseline_strategy.py` (its cost table), `backtesting/transaction_costs.py`, `strategies/funding_rate_arb/single_venue.py`, `strategies/futures_curve/fast_futures_core.py` and `strategies/futures_curve/phase3run.py`. I read parts of these by searching for the numbers, not every line.

## The strategies

**1. Altcoin pair trading (the "statistical arbitrage", Phase 2).**
- Pair choice: every pair of coins is tested for "cointegration" (the two prices tend to stay a fixed distance apart) with three tests (Engle-Granger, Johansen, Phillips-Ouliaris); a pair passes on a combined score of 0.35 or more (`docs/methodology.md`). The "half-life" (how fast the gap closes) must be 1 to 7 days in the config, 24 to 480 hours (1 to 20 days) in the backtest (`phase2run.py` line ~3929). Pairs are also ranked by liquidity, sector and exchange, and 10-15 "tier 1" pairs plus a few others are kept.
- Signal: the z-score of the price gap (how many standard deviations the gap is from its average), with a 60-bar look-back in the engine (`lookback=60`, `phase2run.py` line 2927; the config says 90 days). A Kalman filter keeps the hedge ratio between the two coins up to date (`kalman_delta=0.0001`, `kalman_obs_noise=0.001`).
- Entry: z below -2.0 buys the gap (buy one coin, sell the other), above +2.0 sells it, for pairs on big exchanges; 2.2 for mixed, 2.5 for decentralised-exchange pairs (`phase2run.py` lines 2928-2930).
- Exit: when z returns to 0 (big exchanges), 0.5 (mixed) or inside +/-1.0 (decentralised).
- Stop: |z| over 3.0 (3.5 for decentralised in one place). Time stop: 30 days in the config, 14 days in the walk-forward backtest (`max_holding_days=14`, with a comment "tighter: cut losers faster for higher Sharpe").
- Extras switched on: "adaptive" thresholds that move with volatility and a market-regime model, partial exits at z -1.0, -0.5 and 0.0, a trailing stop that starts at 2% profit, and quarter-Kelly sizing (`phase2run.py` lines 2936-2960).
- Machine learning filter: Gradient Boosting + Random Forest predict the gap's next direction from lagged z-scores (1, 2, 4, 8, 24 bars), gap momentum, volume ratios, BTC return and volatility, sector returns; only signals the models agree with are taken (`docs/methodology.md` section 4.6).
- Size: $10M paper account, 3% ($300K) base per pair, 10% ($1M) maximum (`phase2run.py`); no leverage (1.0x).

**2. Funding-rate carry on one exchange** (`strategies/funding_rate_arb/single_venue.py`): hold spot and short the perpetual when funding, annualised, is above 10%; close when it falls under 2%; 5% stop, 30-day time limit, 0.1% cost per side.

**3. Cross-exchange funding difference** (`docs/methodology.md` section 3): go long the perpetual where funding is lower and short where it is higher; enter when the yearly difference beats twice the costs; 2.0x leverage cap, 5% stop on the basis, hold at least 8 hours.

**4. BTC futures curve (Phase 3)** (`config/config.yaml`, `docs/methodology.md` section 5): calendar spread (buy the near future, sell the far one) when the yearly premium is over 15%, exit under 5%; reverse below -10%, exit above -3%; at least 7 days to expiry. Cross-exchange basis trades need at least a 0.5% gap. The fast engine's settings grid tries z entries of 1.5/2.0/2.5 and exits of 0.3/0.5/0.7 (`fast_futures_core.py` lines 2526-2527). Its trade profit is "(Entry_Spread - Exit_Spread) x Notional x (Days/365) - Costs" (`fast_futures_core.py` line 2082).

## How it tests them

- Split: train Jan 01, 2022 to Jun 30, 2023, test Jul 01, 2023 to Dec 31, 2024 (`config/config.yaml`). The pair engine is set to 18-month train / 6-month test walk-forward windows (`phase2run.py` lines 3926-3927); the futures engine to 24-month train / 6-month test (`phase3run.py` lines 848-849), while the README says "6-month train / 18-month test" for it.
- **The test days ARE used to choose the pairs.** `phase2run.py` lines 1807-1817 pick the cointegrated pairs on prices from `COINT_TRAIN_START = '2022-01-01'` to `COINT_TRAIN_END = '2024-12-31'`, which covers the whole test period, right under a comment that says "Using full data for cointegration would introduce look-ahead bias." The walk-forward then "backtests Step 1's pairs directly" (line ~3937). So the pairs were chosen knowing they would stay together through the test days.
- Settings were also tuned toward the result: comments say the engine "produces impressive results (Sharpe 3.34+, 27%+ returns)" (`phase2run.py` line ~3913) and the 14-day hold was set "for higher Sharpe".
- Costs: the pair engine's table (`baseline_strategy.py` lines 123-169) charges 2.5 to 6 basis points taker fee plus 1 to 5 bp slippage per leg depending on the exchange (e.g. 4 bp + 1 bp for the first one), and up to 5 bp extra "MEV" on decentralised ones. The methodology states ~0.20% for a 4-leg pair round trip on big exchanges and ~1.00% on decentralised ones (0.05% fee + 0.02% slippage per side). Binance futures model: 0.01% maker, 0.04% taker, 1 bp base slippage, funding 0.01% per 8 hours as a default (`transaction_costs.py` lines 241-263). Single-venue funding carry: 0.1% per side.
- Baselines: the config lists "buy-and-hold BTC", "naive roll" and "perpetual hold" as benchmarks; no random-entry baseline. The methodology mentions a 10,000-run Monte Carlo test of the Sharpe; I did not find where it runs.

## What it claims

From `README.md`, unchecked:
- Altcoin pairs: "Sharpe Ratio 1.61", "Total Return 6.84%", "Max Drawdown 4.64%", "Win Rate 51.18%", "Total Trades 127", "Profit Factor 1.69".
- BTC futures curve: "Sharpe Ratio 5.81", "Total Return 203.70%", "Max Drawdown 0.89%", "Win Rate 95.02%", "Total Trades 44,652", "Profit Factor 28.53".
- "Walk-forward out-of-sample results. Train: Jan 2022 – Jun 2023 | Test: Jul 2023 – Dec 2024. No leverage (1.0x). Transaction costs included."

## What matters for us

Probably not. The pair results are not on unseen days: the pairs were picked on data that includes the whole test period, which is exactly the "chosen on the days it is judged on" mistake our own checks are built to avoid. 127 trades over 18 months for 6.84% is also a small sample. Its costs are realistic for a cheap exchange (~0.20% for the four legs of one pair trade), but on Gate the 0.075% fee alone is 0.30% for four legs before any buy-sell gap, so the thin edge it reports (6.84% over 18 months) would shrink a lot or vanish. The futures result (95% wins, 44,652 trades, 0.89% worst drawdown, profit factor 28.53) is not believable as a trading result; it scores annualised funding gaps between venues as profit and looks like it books the carry without the price risk and execution of moving money between exchanges. There is no random-entry baseline.

Ideas worth testing on our Gate data:
- Pair trading of two correlated perpetuals on Gate (both legs on one exchange, so no transfer risk): z-score of the hedged gap, enter at |z| 2.0, exit at 0, stop at 3.0, 14-day time limit - but with the pairs chosen ONLY on older days and judged on later days, and four legs of Gate costs charged.
- Funding carry within Gate: short the perpetual when its funding is very high (over 10% a year) and the rate is likely to keep paying; we already charge funding, so we can measure whether the receipt beats 0.075% x 2 legs plus the gap.

## Doubts

- I did not read every module (the repo is ~226,000 lines); the ML module, `optimized_backtest.py` and `walk_forward_optimizer.py` were not read line by line, so the exact way the ML filter is trained inside each window is unverified.
- The look-back is 60 in the engine but 90 in the config; the half-life limit is 1-7 days in the config but 1-20 days in the backtest; the futures walk-forward is 24/6 months in code but "6-month train / 18-month test" in the README. The README's numbers cannot be tied to one setting.
- `fast_futures_core.py` line 879 subtracts a cost in basis points from `abs(spread) * 100` (percent), which mixes units unless the spread is already a fraction; not checked further.
- The README's "Transaction costs included" is true in code, but I could not check that the reported figures came from the code as it stands (no saved run output was read).
