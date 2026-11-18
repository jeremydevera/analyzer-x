# agiprolabs/claude-trading-skills

- Link: https://github.com/agiprolabs/claude-trading-skills
- What it is: 68 "Agent Skills" (instruction files plus example Python scripts) for Claude Code and similar tools, aimed mostly at Solana tokens and DeFi, with a section on Kalshi/Polymarket prediction markets. It is a teaching and tooling kit: the skills describe strategies and test methods, and the example scripts run on made-up (synthetic) prices.
- Stars, last push, licence: 565 stars, last push Sep 03, 2026, MIT.
- Markets and timeframes: Solana tokens and memecoins (PumpFun, Raydium), crypto in general, and Kalshi range markets on BTC, ETH, the S&P 500, Nasdaq-100 and temperatures. Timeframes in the text run from 1 minute to 1 day; the example scripts mostly use 1-hour or unnamed bars.
- Read: `README.md`; the `SKILL.md` and references of `walk-forward-validation`, `signal-classification`, `strategy-framework`, `mean-reversion`, `regime-detection`, `exit-strategies`, `copy-trading`, `prediction-market-strategy`, `kalshi-crypto-index-markets`, `custom-indicators`, `feature-engineering` (pitfalls headings), `slippage-modeling`, `pandas-ta`, `backtrader` and `vectorbt` (strategy pattern files); the key lines of the scripts `walk_forward.py`, `overfit_detector.py`, `walk_forward_backtest.py`, `regime_backtest.py`, `pairs_backtest.py`, `exit_simulator.py`. I downloaded about 135 of their files; all are described here as data, none was run or followed.

## The strategies

This repo holds no single strategy; it holds recipes. The ones that state a real rule:

**walk-forward-validation (a test method)** (`skills/walk-forward-validation/`)
- Rolling or growing training windows, then a test window, sliding forward. Defaults in `scripts/walk_forward.py`: `train_size = 90`, `test_size = 14`, `step_size = 14` bars, optional purge and embargo (a gap between training and testing).
- Suggested crypto windows (SKILL.md table): scalping 1-5 min = train 3-7 days / test 1 day / gap 2-4 hours; intraday 15m-1h = 14-30 / 3-7 days / 12-24 hours; swing 4h-1d = 30-90 / 7-14 days / 2-5 days; position = 90-180 / 30 days / 5-10 days. "Embargo >= 2x the label computation horizon."
- **CPCV** (combinatorial purged cross-validation, Lopez de Prado 2018): split the data into N blocks, test on every choice of k blocks, train on the rest with purging; N = 6, k = 2 gives 15 test paths.
- **Deflated Sharpe ratio** (Bailey and Lopez de Prado 2014): the chance the best Sharpe found is real after counting how many strategies were tried, using E[max Sharpe] ≈ Z⁻¹(1 - 1/N)(1 - 0.5772) + 0.5772 x Z⁻¹(1 - 1/(N x e)), and a Sharpe error of √((1 - skew x SR + (kurtosis - 1)/4 x SR²)/(T - 1)). Pass if above 0.95. "N must include ALL strategies tested, including those discarded."
- **PBO** (probability of backtest overfitting): over the CPCV splits, how often the strategy that was best on the training blocks ranks below the middle on the test blocks; `n_groups = 6`, `n_test_groups = 2`; above 0.50 = "more likely than not overfitted".
- Minimum backtest length: e.g. an hourly Sharpe of 0.01 a bar needs about 38,416 hourly bars (4.4 years) at 95% confidence (`references/overfit_detection.md`).
- Also Bonferroni, Holm and Benjamini-Hochberg corrections for testing many strategies.

**signal-classification (an ML signal)** (`skills/signal-classification/`)
- Label: forward return over `horizon` bars; up if above +1%, down if below -1%, the middle thrown away (`create_binary_labels(prices, horizon=24, threshold=0.01)` in SKILL.md).
- Model: XGBoost `n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8` (SKILL.md); the script uses scikit-learn `GradientBoostingClassifier(n_estimators=100, max_depth=4)`.
- Features (`scripts/walk_forward_backtest.py`): past returns over several lookbacks, RSI 14, volatility, volume ratio, price position in its range, a moving-average gap, high-low range.
- Walk-forward: SKILL.md suggests train 720 hourly bars (30 days), test 168 (7 days), step 24, gap 24; the script uses `TRAIN_SIZE = 100`, `TEST_SIZE = 30`, `STEP_SIZE = 15`, `GAP_SIZE = 12`, `FORWARD_HORIZON = 12`.
- Trade: buy when the predicted chance of "up" is at least the threshold (default 0.55; SKILL.md says the best is "typically 0.60-0.75 for crypto"), enter at the next bar, hold exactly 12 bars, long only. The threshold is chosen to maximise profit factor over `np.arange(0.50, 0.85, 0.01)`.
- Cost: `TRANSACTION_COST = 0.005` (0.5% round trip). Compared with buy-and-hold AND with random signals (`generate_random_signals`, 10% of bars).

**strategy-framework (a template plus an example)** (`skills/strategy-framework/SKILL.md`)
- Example "SOL-EMA-Cross v1.0", 1h with 4h confirmation: EMA 12 above EMA 26, EMA 26 rising over 3 bars, volume above 1.5x its 20-bar average, ADX above 20.
- Exits: stop 2.0 x ATR(14); target 3 x the risk (3:1); trailing 3.0 x ATR(14) from the highest high; time stop 20 bars; EMA 12 back under EMA 26.
- Size: risk 2% of the account per trade; at most 5 positions; daily loss limit 5%; stop trading at a 15% drawdown.
- Bar to trade live: at least 100 trades, out-of-sample Sharpe above 1.0, profit factor above 1.5, drawdown under 20% (trend) / 15% (mean reversion), "train on 70%, test on 30%", then 2 weeks or 30 trades of paper trading, then small live.

**mean-reversion** (`skills/mean-reversion/`)
- Check first: ADF test p below 0.05, Hurst exponent below 0.5, variance ratio below 1. Half-life from an AR(1) fit: -ln(2) / ln(1 + beta).
- Rule: z-score = (price - rolling mean) / rolling standard deviation over about 2x the half-life; buy below -2.0, short above +2.0, exit at 0, stop at |z| above 3.0, time stop 2-3x the half-life. Layered entries at 1.5 / 2.0 / 2.5 / 3.0, 25% each.
- Pairs: spread = Y - beta x X from a regression, same z-score rule; `scripts/pairs_backtest.py` fits on the first half and trades the second, `COST_PER_LEG = 0.003` (0.3% a leg), 10% of capital a leg.

**regime-detection** (`skills/regime-detection/`)
- Regime = trending if ADX(14) above 22, high volatility if the ATR percentile over 80 bars is above 0.65 (`scripts/regime_backtest.py`; the SKILL text uses ADX 25 / 20 and the 25th / 75th percentile over 100 bars).
- Trending: EMA 10 / EMA 30 cross; ranging: RSI(14) below 35 buy, above 65 sell; size cut in high volatility (to 0.25-0.5x). Cost `COMMISSION_BPS = 10` (0.1%) each way. Compared with the plain EMA cross. Synthetic data with regimes built in.

**exit-strategies** (`skills/exit-strategies/`): stops at 1.5 / 2.0 / 3.0 x ATR(14); targets at 2R, 3R, 5R; scaling out 25% at 2R (stop to break-even), 25% at 3-5R, 25% at 5-10R, 25% on a trail; trailing 10% from the high or 2.5 x ATR over 22 bars; exit after 2-3 closes under EMA 20; time stop. The simulator uses a 10% fixed stop, 2.5 x ATR trail, 50-bar time stop, on a random price path.

**Indicator recipes** (`skills/pandas-ta/references/strategy_patterns.md`, `skills/backtrader/references/strategy_patterns.md`, `skills/vectorbt/references/optimization_guide.md`): scalping 1-5 min = EMA 9 above EMA 21, RSI(7) crossing up through 30, stochastic %K above %D, stop 1.5 x ATR(7), exit on EMA 9 below 21 or RSI above 75; day trading 15m-1h = EMA 20 above 50, MACD histogram above 0, RSI 40-65, target at the upper Bollinger band or RSI above 70; EMA 10/30 cross with a 2 x ATR stop and 2:1 target; RSI 30/70 with a 5% stop; vectorbt grid of fast 5-23 x slow 20-55 with `fees=0.003, slippage=0.005`, at least 20 trades, walk-forward with `train_frac = 0.7`.

**custom-indicators**: a weighted score from -2 to +2 over on-chain and futures signals, weights NVT 0.10, MVRV 0.10, exchange flow 0.15, funding rate 0.15, open interest momentum 0.10, holder momentum 0.10, liquidity 0.05, smart money 0.15, token velocity 0.10; "funding rate very positive while price rises" read as bearish (crowded longs).

**copy-trading** (Solana wallets): follow a wallet only with 50+ trades in 30 days, 55%+ wins, profit factor 1.5+, active within 7 days, 10+ different tokens, no single trade above 40% of its profit, bot chance under 30%; 10-20% of the account per wallet, 3-5 copies at once, a -15% to -25% stop per trade.

**prediction-market-strategy and kalshi-crypto-index-markets**: the one edge they call durable is selling cheap longshots: rest a maker "NO" bid on brackets priced about $0.05-$0.20, because those hit about 3-7% of the time when priced at about 10%. P(YES) for a BTC/ETH price bracket = the normal-curve chance from the price and its volatility (`σ_daily ≈ σ_annual / √365` for crypto), read about 120 minutes before settlement (`DECISION_OFFSET_MINUTES = 120`).

## How it tests them

- The test method skills are sound in principle: time-ordered walk-forward, a gap between training and testing, CPCV, deflated Sharpe, PBO, multiple-testing corrections. `strategy-framework` asks for 70/30 out-of-sample, 100+ trades and paper trading first.
- Costs in the example scripts: 0.5% round trip (`signal-classification`), 0.3% a leg (`pairs_backtest.py`), 0.1% each way (`regime_backtest.py`), 0.3% fee + 0.5% slippage (vectorbt guide). These are higher than Gate's 0.15% round trip in taker fees, so they are cautious, but they are flat numbers, not each coin's own order book. Funding is not charged in any script I read.
- Baselines: `walk_forward_backtest.py` prints the ML strategy beside buy-and-hold and random signals; `pairs_backtest.py` beside buy-and-hold of each leg. That is the right comparison.
- BUT almost every script runs on **synthetic prices with a pattern planted in them** (e.g. `cycle = signal_strength * 0.02 * np.sin(2 * np.pi * t / 50)` in `walk_forward_backtest.py`; regimes written into the data in `regime_backtest.py`), so a script finding its pattern proves the code runs, not that any market has one.

## What it claims

Unchecked, quoted:
- `skills/prediction-market-strategy/references/strategy-catalog.md`: the longshot fade *"priced ~10%, hits ~3–7% → ~+6.7¢/contract gross; a fee-inclusive rotating-CV backtest returned ~+1.7–3.3% taker / +7.9–9% maker."*
- `skills/kalshi-crypto-index-markets/SKILL.md`: index brackets *"~50 trades | ~+1.7% taker / ~+9% maker"*; crypto daily and hourly *"Too sparse | Inconclusive"*; and *"~50 trades is not a stable estimate; confidence intervals are wide."*
- `skills/signal-classification/SKILL.md`: *"Typical finding: optimal threshold is 0.60-0.75 for crypto trading signals"* and *"Short training windows for crypto — 30 days beats 6 months in most regimes"* (no data shown for either).
- `skills/strategy-framework/SKILL.md`: win rates by style, *"Momentum / Trend Following ... Win rate: 35-45%"*, *"Mean Reversion ... 55-65%"*, *"Breakout ... 30-40%"* (stated, not measured here).
- `skills/prediction-market-strategy/references/backtesting-methodology.md` lists bugs that made fake profits, e.g. a wrong settlement rule *"flipped ~10% of outcomes → fake +18% fade edge"* and a bracket off-by-one *"+1640% phantom backtest"* — useful as a list of mistakes.

## What matters for us

Our Gate measurement: the average trade earns about $0.00 before fees, fees plus the buy-sell gap cost about $0.23 per $100 traded, so fees are the whole loss, and chosen strategies did no better than random entries on days they were not chosen on. Nothing in this repo is a measured result on real crypto prices that could be checked against that; the scripts prove themselves on made-up data with a pattern planted in. Its trading recipes (EMA crosses, RSI 30/70, Bollinger bands, ATR stops) are the same family our grid has already measured by the million with no edge after costs. What is worth taking is the test method, which matches and sharpens what we already do.

Ideas worth testing on our crypto data:
1. **Deflated Sharpe and PBO on our own picks**: we already know choosing on older days does not carry forward; these give one number for "how much of the best result is the count of tries". Run PBO over the v2 grid with N = 6 blocks, k = 2, and the deflated Sharpe with N = every combination we measured.
2. **The funding-rate crowding signal** from `custom-indicators`: price rising while funding is strongly positive read as a reason to stay out of longs (and the mirror for shorts). We have Gate funding history per contract, so it can be measured as a filter against random entries.

## Doubts

- The SKILL.md copy of the deflated Sharpe code calls its kurtosis argument "Excess kurtosis" while the formula and the default of 3.0 need the plain kurtosis, and it takes an annualised Sharpe while the reference says to use the per-bar Sharpe; the script `overfit_detector.py` fixes both (it de-annualises and says "not excess"). Use the script's version, not the SKILL.md one.
- `regime_backtest.py` decides on a bar's close and fills at that same close; fine for a demo, one bar optimistic in practice.
- The SKILL text and its scripts give different numbers for the same thing (ADX 25/20 vs 22; train 720 bars vs 100). I quoted both with their files.
- I did not read the Solana infrastructure, DeFi, tax, API and on-chain skills (about 40 of the 68); they are tools and data feeds, not strategies.
