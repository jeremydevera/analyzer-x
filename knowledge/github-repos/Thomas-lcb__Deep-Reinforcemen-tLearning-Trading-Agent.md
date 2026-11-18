# Thomas-lcb/Deep-Reinforcemen-tLearning-Trading-Agent

- Link: https://github.com/Thomas-lcb/Deep-Reinforcemen-tLearning-Trading-Agent
- What it is: one person's project to train a self-teaching agent (first SAC, then PPO, through Stable-Baselines3) to trade BTC/USDT, with a frank lab diary (`Next_step.md`, in French) of every attempt and why it failed.
- Stars, last push, licence: 1 star; last push Oct 06, 2026; no licence file.
- Markets and timeframes: BTC/USDT on Binance (earlier phases: the top 10 coins). Bars went **1 hour → 1 minute** (current config: `timeframe: 1m`, one year of history), with 5-minute, 15-minute and 1-hour context features; a 15-minute version is proposed but not built.
- Read: `README.md`, `config/config.yaml`, `env/trading_env.py` (fees, prices, funding, liquidation), `env/action.py`, `env/reward.py` (formula), `features/multi_timeframe.py` (whole file), `features/indicators.py` and `features/normalizer.py` (window code), `evaluation/backtest.py` and `evaluation/benchmark.py` (baselines, test slice), `training/curriculum.py` (levels), `data/download.py` (download and split), and `Next_step.md` sections 4.9 to 4.16.

## The strategies

There is one strategy, the PPO agent, retrained through a 4-level "curriculum".

### Inputs (state) — `config/config.yaml`, `features/`
- The last 60 one-minute candles (`lookback_window: 60`) of: RSI, MACD, ATR, Bollinger bands, OBV, CCI, simple and exponential averages, log return, volatility (ADX is listed but the README says it was never computed). Each is turned into a rolling z-score over 30 bars (`normalizer.py`).
- Multi-timeframe context: RSI 14, ATR 14 / price, and position versus the 200-period exponential average (+1/−1 and the distance), computed on 5-minute, 15-minute and 1-hour candles built from the 1-minute ones (`multi_timeframe.py`).
- Fear & Greed index (`sentiment: fear_and_greed: true`).
- Portfolio context: position, entry price, cash (`env/observation.py`, not read in full). 37 feature columns in total (per `Next_step.md` 4.16).

### Action — `env/action.py`
One number from −1 to +1. Between −0.1 and +0.1 (`dead_zone: 0.1`) = do nothing. Above it = buy a proportion of cash, below = sell a proportion of holdings, each trade capped at 25% of capital (`max_position_pct: 0.25`). After any trade, no new trade for 200 minutes (`cooldown_steps: 200`). Long only, except level 4, which allows shorting.

### Reward — `env/reward.py`, `config/config.yaml`
`R = log(value now / value before) − c x |action| − λ x volatility + Sharpe bonus + trend bonus − drawdown penalty`, scaled by 100 (`reward_scale`), with: fee penalty weight 150 (`fee_penalty_weight: 150.0`, raised from 20), volatility penalty 0.1, unrealised-profit bonus 0.1, drawdown penalty x5 once the drawdown passes 3% (only when it gets worse), a rolling 100-step Sharpe bonus x0.01, and a trend-alignment bonus x0.005.

### Model — `config/config.yaml`
PPO: learning rate 0.0003, 4,096 steps per update, batch 256, 10 passes, discount 0.99, GAE 0.95, clip 0.2, entropy 0.01, stop an update early if KL divergence passes 0.02 (`target_kl: 0.02`), two layers of 256. 3 parallel games, episodes capped at 20,000 steps (about 14 days of minutes). (Earlier SAC: learning rate 0.0007 decaying to 0, memory 300,000, batch 64, layers 1024/1024/512.)

### Curriculum — `training/curriculum.py`
- Level 1: BTC/USDT, **0% fees**, 500,000 steps.
- Level 2: 0.1% fees, 1,000,000 steps.
- Level 3: 0.1% fees + randomised starting capital (±20%) and randomised fee 0.05%–0.15%, 1,500,000 steps.
- Level 4: as level 3 plus **shorting**, with funding of 0.000001 per minute (about 0.024% per 8 hours), forced close if the open loss reaches 50% of the position (`maintenance_margin_pct: 0.5`) plus a 1% liquidation penalty; 1,500,000 steps.
- Each level starts from the previous level's weights.

### Execution, stop, target, size
Trades fill at the **current 1-minute close** with 0.1% fee each way (`fees: taker: 0.001`), no bid-ask gap, no slippage. No stop or target beyond the drawdown penalty and (level 4) the forced liquidation. Size: up to 25% of capital per trade; no leverage.

### A regime-switching ensemble (tried and abandoned) — `Next_step.md` 4.15
Route to the level-2 (long) model in up markets and the level-4 (short) model in down markets, judged by the 1-hour 200-EMA or by the sign of the last 1,000 minutes' return. Result: "catastrophique" — −32.00% on test, −41.29% on validation, 2,105 trades from about 1,100 switches.

## How it tests them

- **Split** (`data/download.py`, `evaluation/backtest.py`): one year of 1-minute candles cut in time order, 70% train / 15% validation / 15% test. The test slice is about 78,751 minutes (about 55 days) and was a rising market (buy-and-hold +22.08%); validation was a falling one (buy-and-hold −13.17%).
- **Test days used for choosing?** **Yes.** The cooldown was chosen by a sweep scored directly on the test set ("Sweep de `cooldown_steps`" … "Résultat sur le test set", `Next_step.md` 4.10–4.11), and the dead-zone and fee-penalty weight were then tuned the same way. The validation split was only scored afterwards (4.13: "jamais utilisé jusqu'ici pour scorer un résultat" — never used to score anything until then).
- **Costs**: 0.1% per buy and per sell (0.2% round trip, about our $0.23), no bid-ask gap, fills at the close. Funding only in level 4 (shorts), at a fixed made-up rate.
- **Baselines**: buy-and-hold and a **random agent run through the same environment with the same fees and the same cooldown** (`evaluation/benchmark.py`) — the right comparison.
- **Seeds**: 3 seeds for level 2, 2 for level 4.
- **Look-ahead bug** (my reading, not the author's): `features/multi_timeframe.py` builds 5-minute, 15-minute and 1-hour candles with `df.resample(rule)` (pandas labels each candle with its START time) and then `df.join(...)` + `ffill()` onto the 1-minute rows. So the 1-minute row at 10:00 receives the 1-hour candle stamped 10:00, whose close is the 10:59 close: **each 1-minute row can see up to 59 minutes of the future** through the 1-hour features (14 minutes through 15-minute, 4 through 5-minute). The code comment says the forward-fill is "to avoid look-ahead", but the start-time label defeats it. This matters because the author's own check (4.16) found that the most predictive features were exactly these: "`mtf_1h_rsi` (r=+0.162), `mtf_1h_ema200_dist` (r=+0.159)".

## What it claims

From `Next_step.md` (French; quoted as written, unchecked):

- 4.10, after retraining with cooldown 500: "rendement +8.76%" on test, but "Reste statistiquement indiscernable de l'aléatoire sur ce test set (+8.76% vs +8.83% aléatoire, Sharpe 2.91 vs 3.19, PF 2.02 vs 2.25 …) et loin derrière Buy & Hold (+22.08%)."
- 4.11, cooldown 200 retrained: "Rendement modèle … **+6.36%**", random under the same cooldown "**-0.62%**", and "**Premier signal crédible d'un edge réel**, même modeste".
- 4.12, fee-penalty weight 150: "**+9.10%**", Sharpe "**2.695**", trades "**392 (plafond, inchangé)**" — the agent still trades at the maximum the cooldown allows.
- 4.13, the same model on the validation split: "Rendement | -9.51% | -13.17% | -9.30%" (model, buy-and-hold, random) and "L'edge mesuré sur le test set … ne se reproduit pas sur le split validation".
- 4.14, level 4 (shorts): test "**-18.37%**", validation "**-2.58%**"; "zéro `buy`/`sell`, aucune position longue prise" — it only ever shorts.
- 4.16, a simple logistic regression on the same features: "AUC ~0.62 **remarquablement stable sur les trois splits**" at a 200-minute horizon, accuracy "58.9%".

README: Phase 4 on 1-minute bars was a "Result (Failure)" — "attempting to trade 1m micro-movements caused transaction fees to obliterate the portfolio".

## What matters for us

Our own measurement on Gate: the average trade earns about $0.00 before fees, fees plus the buy-sell gap cost about $0.23 per $100 trade, and chosen strategies did no better than random entries on unseen days.

This repo **ends where we ended**. Its cost (0.2% round trip) is close to ours, though it skips the bid-ask gap. It does keep separate test and validation days and it does compare with a random agent under the same fees — and the result is the same as ours: the "edge" on the test days (+9.10%) came after tuning on those same days, disappeared on the validation days (−9.51% vs random −9.30%), and lost to buy-and-hold (+22.08%) where it did win. On 1-minute bars the fees "obliterate the portfolio". The one hopeful number (AUC 0.62, stable on every split) is most likely the look-ahead in the 1-hour features, which would show the same stable "skill" on every split because it is reading the future, not learning.

Ideas worth testing on our crypto data:
1. **Check our own multi-timeframe features for the same bug.** Anywhere we build a bigger candle from smaller ones and attach it to the smaller rows, the bigger candle must only appear after it has CLOSED. CLAUDE.md already says this for the cpw rules ("the bigger-timeframe candles are what had happened by each close"); this repo is a clean example of how it goes wrong and why the fake signal looks stable.
2. **A cooldown after each trade as an explicit fee control** — their random agent went from −32.19% (cooldown 15) to −0.62% (cooldown 200) on the same days, purely from paying fewer fees. Measuring our rooms' strategies with a minimum gap between trades on the same coin would show how much of each loss is turnover.

## Doubts

- `Next_step.md` is long; I read sections 4.9–4.16 and skimmed the rest. I did not read `env/observation.py`, `training/train.py`, `training/hyperparams.py`, the tests, the Reptile meta-learning design or the short-selling plan.
- The look-ahead finding is from reading `multi_timeframe.py`, not from running it; pandas' default for `resample` is to label by the start of the period, which is what makes it a leak here.
- The README describes a 1-hour, 10-coin setup with a 30-hour window in its "Architecture" section, which is out of date against the 1-minute BTC config.
- Every result is one 55-day test window and one 2-month-ish validation window from a single year of data.
