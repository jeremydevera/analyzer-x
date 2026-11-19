# The reviewed repos' strategies, backtested on our market

Measured on GitHub, collected Nov 18, 2026 9:28pm: every strategy in `tradingagents/gh_strats` on 5,160 coin-timeframes (every coin x 15m, 30m, 1h, 4h, 1d), 371,520 strategy x setting x stop combinations tested in all. Figures are the NEWEST 30% of each coin-timeframe's candles (days no setting was chosen on), by the candle a trade opened in; every trade pays Gate's fee both ways, the recorded order book of its own minute where one exists (else the coin's usual gap) and funding over the hold, with stops and targets settled by the minute. $5 margin x 20x = $100 a trade, flat. Trades still open at the end are left out (115,780). Page: https://claude.ai/artifact/38jHY5XM5u2nuccx3jYYSq

The luck bar is random entries through the same engine (`gh_random`): profit a trade by timeframe 15m -0.76, 30m -0.83, 1h -0.43, 4h +0.02, 1d -0.17.

## What we learned

- **Every one of the 48 strategies lost money after costs**, pooled over every coin and timeframe:
  10,977,658 trades, -$9,088,185.96, -$0.83 a trade. The least bad, je-suis-tm's London Breakout,
  lost $0.56 a trade; random entries through the same engine lost $0.65. No strategy beat random on
  all five timeframes; the best beat it on 2 of 3 (London Breakout, Dual Thrust: 15m-1h only).
- **Before costs they are about zero too.** Adding each trade's usual round trip back (2 x 0.075% fee
  + 2 x the coin's usual gap, funding not added back) puts the best at +$0.23 a trade (Dual Thrust,
  19,702 trades); only 7 of the 48 are above zero before costs, all by $0.23 or less, and most sit
  between -$0.50 and $0.00 - the same picture as our own grid (the edge before fees is about $0.00,
  fees are the whole loss). The machine-learning repos are no better
  than the plain rules: KennethMartin06's four models -$0.65 to -$0.79 a trade.
- **On cheap crypto (a usual gap of 5 basis points or less, 86 coins) the losses shrink** -
  the better half lose $0.14-$0.37 a trade there instead of $0.60-$0.80 - because the cost is smaller,
  not because the signal is better (random entries: -$0.25 there).
- **The one cell worth a look: trend on daily candles of cheap crypto.** pybroker's "buy above the
  30-candle average, sell below" (`gh_pyb_sma_stop`, 1d) made +$1.21 a trade over 5,365 trades
  (random entries there: +$0.03): 45 of 86 coins made money, the median coin +$12.83, and without its
  10 best coins still +$1,326. But it is the best of about 240 strategy x timeframe cells (luck can
  produce one), its money came from Aug - Oct 2026 (Apr, Jun, Jul and Nov 2026 lost), and its best
  setting uses the repo's 6% stop, past the 4.5% liquidation line at 20x, which the app's cost check
  refuses. It agrees with our own earlier finding (cheap-coin trend is the best candidate). QuantConnect's
  EMA cross on the same days: +$0.22 a trade, but its 10 best coins carry all of it.
- **Bad data was caught on the way**: stock tokens show flat zero-volume placeholder candles before
  they really list (MDT 0.01287 then 86.40); entries there booked +$719,692 on one $100 trade
  (RCA-2026-11-18-A). Stock tokens now take no entry on a candle where nothing traded (14,045,991
  entries refused, mostly closed-market nights and weekends).
- **Losses past the margin are not capped.** 193,009 trades (1.8%) lost more than the $5 margin
  (-$1,458,973.90 in all) - a stop the price jumped past (TAIKO rose from 0.0785 to 0.4418 on Jul 01,
  2026), or a repo's own stop wider than 4.5% (pybroker 6%, agiprolabs 5%, maleshchenko 10%). At 20x
  the exchange would have closed those at about -$5, so those strategies look a little worse here than
  they would trade; it changes no ranking above.

| Strategy | Repo | TP | SL | Leverage | Trades | Wins | Losses | Win rate | PROFIT / TOTAL $ | $ a trade | Worst losing run | Coin-timeframes that made money | Beats random (timeframes) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gh_qt_london | je-suis-tm/quant-trading | 0.5% | 0.5% | 20x | 17,435 | 5,891 | 11,544 | 33.8% | -9,846.79 | -0.56 | -56.33 over 50 | 153 of 2,842 | 2 of 3 |
| gh_pyb_pop | edtechre/pybroker | own exit | 2% | 20x | 429,234 | 114,835 | 314,399 | 26.8% | -260,154.79 | -0.61 | -1,707.56 over 714 | 619 of 5,129 | 2 of 5 |
| gh_qt_dual_thrust | je-suis-tm/quant-trading | own exit | 2% | 20x | 19,702 | 5,272 | 14,430 | 26.8% | -12,030.45 | -0.61 | -1,762.03 over 634 | 1,863 of 5,660 | 2 of 3 |
| gh_twp_xlp_gap | sjev/twp | own exit | 2% | 20x | 1,176,235 | 229,633 | 946,602 | 19.5% | -756,408.69 | -0.64 | -860.42 over 377 | 513 of 9,958 | 2 of 5 |
| gh_mal_lstm | maleshchenko/trade-ml | 1.5% | 10% | 20x | 62,544 | 51,319 | 11,225 | 82.1% | -40,520.12 | -0.65 | -773.24 over 75 | 3,446 of 7,480 | 1 of 5 |
| gh_km_logit | KennethMartin06/ml-based-algorithmic-trading-signals | own exit | 2% | 20x | 585,866 | 161,882 | 423,984 | 27.6% | -380,753.21 | -0.65 | -2,143.95 over 242 | 337 of 8,207 | 2 of 5 |
| gh_hur_rf | Huraira9913/trading-signal-ml | own exit | 2% | 20x | 405,239 | 102,134 | 303,105 | 25.2% | -263,661.19 | -0.65 | -961.36 over 108 | 122 of 4,313 | 2 of 5 |
| gh_km_xgb | KennethMartin06/ml-based-algorithmic-trading-signals | own exit | 2% | 20x | 724,731 | 196,491 | 528,240 | 27.1% | -472,730.83 | -0.65 | -3,094.34 over 346 | 280 of 8,279 | 2 of 5 |
| gh_random | luck-bar/random-entries | own exit | 2% | 20x | 73,837 | 19,804 | 54,033 | 26.8% | -48,186.66 | -0.65 | -3,170.61 over 1323 | 1,887 of 9,171 | 0 of 5 |
| gh_tz_osc5 | tzelalouzeir/XGB_CryptoStrategy | 1% | 1% | 20x | 713,686 | 278,308 | 435,378 | 39.0% | -475,889.42 | -0.67 | -628.32 over 100 | 301 of 10,127 | 2 of 5 |
| gh_km_rf | KennethMartin06/ml-based-algorithmic-trading-signals | own exit | 2% | 20x | 370,398 | 98,946 | 271,452 | 26.7% | -249,754.79 | -0.67 | -1,727.39 over 193 | 140 of 4,145 | 2 of 5 |
| gh_mk_lstm | Marshal-Kalynchuk/crypto-lstm-prediction | 5% | 3% | 20x | 74,185 | 25,951 | 48,234 | 35.0% | -50,746.67 | -0.68 | -173.58 over 49 | 1,196 of 4,047 | 1 of 5 |
| gh_agi_zscore | agiprolabs/claude-trading-skills | own exit | 2% | 20x | 84,029 | 26,332 | 57,697 | 31.3% | -58,701.92 | -0.70 | -675.94 over 296 | 1,070 of 4,939 | 2 of 5 |
| gh_pyb_rf | edtechre/pybroker | own exit | 2% | 20x | 559,934 | 126,343 | 433,591 | 22.6% | -392,668.29 | -0.70 | -780.34 over 335 | 113 of 4,327 | 2 of 5 |
| gh_pyb_dip | edtechre/pybroker | own exit | 2% | 20x | 397,516 | 96,438 | 301,078 | 24.3% | -284,525.44 | -0.72 | -2,041.39 over 868 | 283 of 5,148 | 2 of 5 |
| gh_qt_heikin_ashi | je-suis-tm/quant-trading | own exit | 2% | 20x | 198,254 | 64,299 | 133,955 | 32.4% | -143,078.73 | -0.72 | -2,720.93 over 1175 | 395 of 5,116 | 2 of 5 |
| gh_nehren_breakout | NehrenD/algo_trading_and_quant_strategies | own exit | 2% | 20x | 78,409 | 13,707 | 64,702 | 17.5% | -60,311.47 | -0.77 | -985.60 over 426 | 503 of 4,533 | 2 of 5 |
| gh_twp_ma_cross | sjev/twp | own exit | 2% | 20x | 180,564 | 35,144 | 145,420 | 19.5% | -141,247.72 | -0.78 | -1,061.15 over 456 | 1,382 of 9,730 | 1 of 5 |
| gh_qc_ema_cross | QuantConnect/Research | own exit | 2% | 20x | 477,762 | 109,386 | 368,376 | 22.9% | -375,225.62 | -0.79 | -1,035.20 over 470 | 709 of 10,228 | 2 of 5 |
| gh_qt_rsi | je-suis-tm/quant-trading | own exit | 2% | 20x | 78,355 | 24,555 | 53,800 | 31.3% | -61,836.12 | -0.79 | -559.56 over 61 | 915 of 4,992 | 1 of 5 |
| gh_km_ens | KennethMartin06/ml-based-algorithmic-trading-signals | own exit | 2% | 20x | 293,182 | 70,689 | 222,493 | 24.1% | -233,050.11 | -0.79 | -3,183.25 over 1384 | 154 of 4,144 | 2 of 5 |
| gh_xgt_xgb | crypticalgo/XGTraderAGI---Training-and-Model-Only-XGBOOST- | own exit | 2% | 20x | 569,080 | 98,739 | 470,341 | 17.4% | -454,373.24 | -0.80 | -1,669.94 over 792 | 221 of 4,332 | 1 of 5 |
| gh_ahmed_reversal | ahmedas91/ml-ohlcv-alpha-signals | own exit | 2% | 20x | 337,745 | 85,605 | 252,140 | 25.3% | -287,038.98 | -0.85 | -934.20 over 2 | 1,130 of 9,173 | 0 of 5 |
| gh_qt_shooting_star | je-suis-tm/quant-trading | 5% | 5% | 20x | 31 | 11 | 20 | 35.5% | -26.99 | -0.87 | -16.05 over 7 | 10 of 30 | 2 of 5 |
| gh_nehren_bollinger | NehrenD/algo_trading_and_quant_strategies | own exit | 2% | 20x | 85,499 | 12,256 | 73,243 | 14.3% | -77,232.10 | -0.90 | -863.33 over 426 | 528 of 4,898 | 0 of 5 |
| gh_nehren_rsi | NehrenD/algo_trading_and_quant_strategies | own exit | 2% | 20x | 50,985 | 11,617 | 39,368 | 22.8% | -49,148.97 | -0.96 | -320.88 over 138 | 1,059 of 6,396 | 0 of 5 |
| gh_qt_psar | je-suis-tm/quant-trading | own exit | 2% | 20x | 238,146 | 35,701 | 202,445 | 15.0% | -234,970.53 | -0.99 | -2,589.83 over 1161 | 669 of 10,101 | 0 of 5 |
| gh_nehren_ma | NehrenD/algo_trading_and_quant_strategies | own exit | 2% | 20x | 138,469 | 12,084 | 126,385 | 8.7% | -139,670.43 | -1.01 | -1,451.64 over 751 | 464 of 4,849 | 0 of 5 |
| gh_agi_xgb | agiprolabs/claude-trading-skills | own exit | 2% | 20x | 271,826 | 62,275 | 209,551 | 22.9% | -283,177.56 | -1.04 | -3,081.81 over 406 | 642 of 8,419 | 0 of 5 |
| gh_pyb_sma_stop | edtechre/pybroker | own exit | 2%, 6% | 20x | 726,561 | 86,499 | 640,062 | 11.9% | -770,213.27 | -1.06 | -4,470.95 over 1772 | 1,365 of 20,047 | 0 of 5 |
| gh_tmr_ema_wf | tmr-crypto/wf_optim_crypto_analysis | own exit | 2% | 20x | 88,302 | 10,234 | 78,068 | 11.6% | -95,937.74 | -1.09 | -1,693.32 over 352 | 1,356 of 8,938 | 0 of 5 |
| gh_qt_macd | je-suis-tm/quant-trading | own exit | 2% | 20x | 111,271 | 15,962 | 95,309 | 14.3% | -124,986.52 | -1.12 | -1,600.36 over 682 | 636 of 9,559 | 0 of 5 |
| gh_qt_awesome | je-suis-tm/quant-trading | own exit | 2% | 20x | 106,712 | 15,549 | 91,163 | 14.6% | -121,160.81 | -1.14 | -1,638.88 over 721 | 656 of 9,673 | 0 of 5 |
| gh_mlt_rsi_reversion | stefan-jansen/machine-learning-for-trading | own exit | 2% | 20x | 108,311 | 20,873 | 87,438 | 19.3% | -127,275.10 | -1.18 | -2,806.40 over 374 | 544 of 4,994 | 0 of 5 |
| gh_nehren_two_ma | NehrenD/algo_trading_and_quant_strategies | own exit | 2% | 20x | 19,171 | 2,623 | 16,548 | 13.7% | -22,824.24 | -1.19 | -618.63 over 123 | 661 of 4,309 | 1 of 5 |
| gh_rid_macd_rsi | Ridwat/Project-3-ML-for-Predicting-Trading-Signal | own exit | 2% | 20x | 47,264 | 8,123 | 39,141 | 17.2% | -56,786.59 | -1.20 | -979.25 over 428 | 730 of 6,087 | 0 of 5 |
| gh_es_sma_ml | ethansilvas/sma-ml-trading-algorithm | own exit | 2% | 20x | 243,728 | 41,362 | 202,366 | 17.0% | -308,152.87 | -1.26 | -2,055.38 over 874 | 962 of 7,811 | 0 of 5 |
| gh_agi_sol_ema | agiprolabs/claude-trading-skills | 6% | 2% | 20x | 50,286 | 7,764 | 42,522 | 15.4% | -63,714.85 | -1.27 | -566.64 over 227 | 522 of 4,712 | 0 of 5 |
| gh_finrl_turbulence_hold | AI4Finance-Foundation/FinRL | own exit | 2% | 20x | 424,388 | 86,980 | 337,408 | 20.5% | -542,219.69 | -1.28 | -6,359.88 over 806 | 387 of 8,626 | 0 of 5 |
| gh_agi_ema_cross | agiprolabs/claude-trading-skills | 4% | 2% | 20x | 31,859 | 6,362 | 25,497 | 20.0% | -42,001.93 | -1.32 | -1,128.74 over 477 | 788 of 4,625 | 1 of 5 |
| gh_danny_ma_baseline | Danny-397/RL-for-Crypto-and-stocks- | own exit | 2% | 20x | 101,446 | 13,464 | 87,982 | 13.3% | -147,452.72 | -1.45 | -1,211.00 over 476 | 405 of 4,885 | 0 of 5 |
| gh_mlt_momentum_band | stefan-jansen/machine-learning-for-trading | own exit | 2% | 20x | 83,147 | 10,779 | 72,368 | 13.0% | -122,214.41 | -1.47 | -1,017.26 over 444 | 476 of 4,872 | 0 of 5 |
| gh_cs_rsi | Log-zz-ikIO/crypto-signal | own exit | 2% | 20x | 58,998 | 6,836 | 52,162 | 11.6% | -88,586.17 | -1.50 | -5,327.67 over 2291 | 641 of 4,793 | 0 of 5 |
| gh_qt_bollinger_w | je-suis-tm/quant-trading | own exit | 2% | 20x | 1,543 | 109 | 1,434 | 7.1% | -2,503.23 | -1.62 | -358.96 over 187 | 59 of 1,017 | 0 of 5 |
| gh_hudson_ma_cross | hudson-and-thames/backtest_tutorial | own exit | 2% | 20x | 9,202 | 716 | 8,486 | 7.8% | -15,208.54 | -1.65 | -878.89 over 370 | 356 of 3,463 | 0 of 5 |
| gh_pyb_breakout20 | edtechre/pybroker | own exit | 2% | 20x | 40,031 | 3,777 | 36,254 | 9.4% | -66,472.54 | -1.66 | -1,302.43 over 563 | 313 of 4,729 | 0 of 5 |
| gh_agi_rsi | agiprolabs/claude-trading-skills | own exit | 5% | 20x | 29,971 | 6,991 | 22,980 | 23.3% | -64,713.43 | -2.16 | -8,681.99 over 1643 | 878 of 4,688 | 0 of 5 |
| gh_finrl_tsmom | AI4Finance-Foundation/FinRL-Trading | own exit | 2% | 20x | 2,589 | 54 | 2,535 | 2.1% | -8,793.48 | -3.40 | -4,645.29 over 669 | 16 of 687 | 0 of 1 |

## Each strategy's rule

- `gh_qt_london` (je-suis-tm/quant-trading): The 7am-8am UTC high and low set a band; a candle opening 8:00-8:29 that closes above it buys (below sells) unless more than 1% past it; out at 0.5% either way or at 5pm UTC; only on 15m-1h candles, none on 4h or 1d (London Breakout backtest.py; its 0.01 and 0.005 were GBP/USD prices, read as 1% and 0.5%). The repo's share counts are not used: the engine trades $5 x 20x with its own stop.
- `gh_pyb_pop` (edtechre/pybroker): Close over the previous candle's high: short at the close, cover 2 candles later; notebook 2 `short_high` (its 100-share size not copied).
- `gh_qt_dual_thrust` (je-suis-tm/quant-trading): At the session open (8am UTC = the script's 3am EST, or 00:00 UTC) set lines at the open +/- 0.5 x the 5 PREVIOUS sessions' range; a close above goes long, below goes short, close all at the session end (5pm UTC / next 00:00); only on 15m-1h candles, no trades on 4h or 1d (Dual Thrust backtest.py; its range included the day itself, removed). The repo's share counts are not used: the engine trades $5 x 20x with its own stop.
- `gh_twp_xlp_gap` (sjev/twp): Yesterday's close-to-close change under -0.25% and today's open more than 0.1% under yesterday's close: long one candle - bought at the gap candle's close and sold at the next close, because the engine cannot buy at an open as the repo does; twp_304_xlp_strategy.ipynb (second setting: its hand-typed 0.03/0.09).
- `gh_mal_lstm` (maleshchenko/trade-ml): Log return, 10-candle wobble, volume z-score, 10-20 average gap, RSI 14, ATR 14 and volume change plus the recent path; label '+0.5% before -0.3% within 10 candles' (short the mirror); their LSTM is replaced by gradient boosting (balanced classes); enter above 80% sureness (setting 2: 65%), 1.5% target and 10% stop (trade_model.py, backtest.py, config.py).
- `gh_km_logit` (KennethMartin06/ml-based-algorithmic-trading-signals): ~40 of its 42 return, trend, volatility, volume and regime features, label next candle up/flat/down at +-0.1% (close to close, since our fills are at the close), logistic regression (C 0.1, scaled on training rows), walk-forward refit every 500 candles; long while P(up) >= tau, out when it drops below (src/targets.py, src/backtester.py, config.yaml)
- `gh_hur_rf` (Huraira9913/trading-signal-ml): Returns 1/5/20, 20-candle wobble, distance from the 50 average and volume z-score; label 'close higher 5 candles later'; their random forest is replaced by gradient boosting (depth 6); long while P(up) >= 0.5, out when it drops or after 5 candles (src/generate_signals.py).
- `gh_km_xgb` (KennethMartin06/ml-based-algorithmic-trading-signals): ~40 of its 42 return, trend, volatility, volume and regime features, label next candle up/flat/down at +-0.1% (close to close, since our fills are at the close), their XGBoost is replaced by gradient boosting (depth 3), walk-forward refit every 500 candles; long while P(up) >= tau, out when it drops below (src/targets.py, src/backtester.py, config.yaml)
- `gh_random` (luck-bar/random-entries): Random entries (our luck bar, not a repo): about 2 candles in 100 enter, long or short on a coin flip, out after 10 candles or at the stop - two seeds.
- `gh_tz_osc5` (tzelalouzeir/XGB_CryptoStrategy): Long when Williams %R 14, Stochastic %K and %D 14-3-3, Bollinger %B 20 and CCI 20 are ALL above their average over the candles that closed higher than 2 candles before (short: all below the falling candles' average), averages over past candles only (the repo used the whole file), at most 10 entries per 24 candles, 1% target and 1% stop; their 24x is the engine's 20x (xgb_backtrader.py).
- `gh_km_rf` (KennethMartin06/ml-based-algorithmic-trading-signals): ~40 of its 42 return, trend, volatility, volume and regime features, label next candle up/flat/down at +-0.1% (close to close, since our fills are at the close), their random forest is replaced by gradient boosting (depth 6), walk-forward refit every 500 candles; long while P(up) >= tau, out when it drops below (src/targets.py, src/backtester.py, config.yaml)
- `gh_mk_lstm` (Marshal-Kalynchuk/crypto-lstm-prediction): About 15 of its indicators (RSI/stoch/ROC/MFI/ATR/CCI 6, MACD 6/12, ADX 12, DPO 12, force index, wicks) plus 12/24/48-candle returns; label FIXED to the FUTURE 6-candle move (+1.2% to +3% buy, -3% to -1.2% sell, else hold, hold when ATR is above its past-500-candle 75th percentile); their LSTM is replaced by gradient boosting; enter on the most likely class, 5% target and 3% stop (lstm.ipynb).
- `gh_agi_zscore` (agiprolabs/claude-trading-skills): z = (close - its N-candle average) / N-candle sd: under -2 long, over +2 short, out when z crosses back over 0 or runs past 3; skills/mean-reversion/scripts/mean_reversion_test.py `generate_signals` (N fixed at 40 = 2x its default 20-candle half-life; the half-life fit is not run on the whole frame, which would read later candles).
- `gh_pyb_rf` (edtechre/pybroker): The candle's log return and its 3 previous ones predict the next candle's return; their random-forest regressor is replaced by gradient boosting; long when the forecast is above 0, out when below (docs notebook 16, Time Series Models).
- `gh_pyb_dip` (edtechre/pybroker): Close under the previous candle's low: buy at the close, sell 3 candles later; notebook 2 `buy_low` (its 25%-of-account size and next-bar fill not copied).
- `gh_qt_heikin_ashi` (je-suis-tm/quant-trading): Buy when the Heikin-Ashi candle is red with no upper wick, a bigger body than the previous red one; sell when it is green with no lower wick after a green one; one position, not the script's 3 stacked buys (Heikin-Ashi backtest.py). The repo's share counts are not used: the engine trades $5 x 20x with its own stop.
- `gh_nehren_breakout` (NehrenD/algo_trading_and_quant_strategies): Long while the close is above the highest close of the previous m candles, short below the lowest, flat in between; `resistance_support_strategy` in exercises/chapter5_solutions.ipynb.
- `gh_twp_ma_cross` (sjev/twp): Long while the fast simple average (10 candles; the tuned 18) is above the slow one (50; tuned 25), short otherwise, always in; twp_302_moving_averages_strat.ipynb (day windows kept as candles, its 10-share size not copied).
- `gh_qc_ema_cross` (QuantConnect/Research): The notebook's formula with the coin in VXX's place: buy when the close falls back under its 10-candle EMA, go to cash when it rises above (or the mirror: long on the rise above) (Analysis/04 EMA Cross Strategy Based on VXX.ipynb). The repo's share counts are not used: the engine trades $5 x 20x with its own stop.
- `gh_qt_rsi` (je-suis-tm/quant-trading): Long while Wilder RSI 14 is under 30, short while over 70, out when it returns between (RSI Pattern Recognition backtest.py, its main rule). The repo's share counts are not used: the engine trades $5 x 20x with its own stop.
- `gh_km_ens` (KennethMartin06/ml-based-algorithmic-trading-signals): ~40 of its 42 return, trend, volatility, volume and regime features, label next candle up/flat/down at +-0.1% (close to close, since our fills are at the close), the average of the logistic, forest and XGBoost stand-ins (their LSTM member is left out), walk-forward refit every 500 candles; long while P(up) >= tau, out when it drops below (src/targets.py, src/backtester.py, config.yaml)
- `gh_xgt_xgb` (crypticalgo/XGTraderAGI---Training-and-Model-Only-XGBOOST-): Its 13 inputs (close, EMA 5, MACD 3/9/9, RSI 6, Bollinger 5, running VWAP, ATR 14, ROC 3 ...) with the look-ahead removed (its 'Head-Shoulders' flag read two later candles; here the shape ends at the current one) and no whole-file z-scoring; label 'MACD above signal and close above EMA 5' on the candle itself; their XGBoost is replaced by gradient boosting; long when it says 1, short when 0, flipping (main.py, BackTest.py).
- `gh_ahmed_reversal` (ahmedas91/ml-ohlcv-alpha-signals): A single-coin stand-in (the repo ranks across ~1,000 stocks): buy when the coin's 1-candle and 5-candle drops are both in the worst 10% of its own last 250, short when both rises are in the best 10%, and close after 5 (or 1) candles (src/signals/baseline.py reversal features).
- `gh_qt_shooting_star` (je-suis-tm/quant-trading): Short at the close of the candle after a shooting star (red, long upper wick, tiny lower wick, small body, after two rising closes) when that candle makes no higher high or close; out at 5% either way or after 7 candles (Shooting Star backtest.py; it read the next candle and the whole history's average body, both removed; it needs an opening gap above the last close, so on 24-hour coins it almost never fires - 0 times on a month of BTC 5m-1h). The repo's share counts are not used: the engine trades $5 x 20x with its own stop.
- `gh_nehren_bollinger` (NehrenD/algo_trading_and_quant_strategies): Long while the close is above the m-candle average + 2 standard deviations, short below the average - 2 (the repo's code adds 2 to both bands, a typo; the intended minus is used), flat inside; `bollinger_strategy` in exercises/chapter5_solutions.ipynb.
- `gh_nehren_rsi` (NehrenD/algo_trading_and_quant_strategies): RSI from the average up-return and average down-return of the last m candles: long under 30, short over 70, flat between (m = 60, its worked example, or 20); `rsi_strategy` in exercises/chapter5_solutions.ipynb.
- `gh_qt_psar` (je-suis-tm/quant-trading): Long while the close is above the Parabolic SAR (0.02 start and step, 0.2 cap; or the script's 0.01 for stocks), out when below (Parabolic SAR backtest.py). The repo's share counts are not used: the engine trades $5 x 20x with its own stop.
- `gh_nehren_ma` (NehrenD/algo_trading_and_quant_strategies): Long while the close is above its m-candle average, short while below (flipping on the cross); m-day windows become m candles on every timeframe; `mav_strategy` in exercises/chapter5_solutions.ipynb.
- `gh_agi_xgb` (agiprolabs/claude-trading-skills): Returns 3/6/12/24, RSI 14, 10/20 wobble, volume ratios, range position, 10/30 average gap and range; label forward 12-candle return above +1% vs below -1% (middle dropped); their XGBoost is replaced by gradient boosting (depth 4, lr 0.05); long when P(up) >= 0.55, held exactly 12 candles (setting 2: 24 candles, 0.60) (skills/signal-classification/scripts/walk_forward_backtest.py).
- `gh_pyb_sma_stop` (edtechre/pybroker): Flat and close above its 30-candle (or 10) average: buy; close under the average: sell; stop 6% (or 2%); notebook 12 `sma_cross_stop` (100-share size not copied).
- `gh_tmr_ema_wf` (tmr-crypto/wf_optim_crypto_analysis): Always long while the fast EMA is above the slow EMA at the previous close, else short, the pair (fast 5-30 x slow 40-200, 30 pairs) re-chosen every 28 (or 10) days as the best net Sharpe of the 7 (or 14) days before; tmr-crypto/wf_optim_crypto master/rcode/logic/strategy.r and WfHelper.r (windows are real days, its whole-account 1x size not copied).
- `gh_qt_macd` (je-suis-tm/quant-trading): Long when the 10-candle average of the close moves to or above the 21 (or 12/26), out when it falls below; long only (MACD Oscillator backtest.py). The repo's share counts are not used: the engine trades $5 x 20x with its own stop.
- `gh_qt_awesome` (je-suis-tm/quant-trading): Long when the 5-candle average of (high+low)/2 is above the 34, out when below, long only - the saucer setting also buys on the script's red-candle saucer and sells on its green one (Awesome Oscillator backtest.py; as written the averages overwrite the saucer, which is the first setting). The repo's share counts are not used: the engine trades $5 x 20x with its own stop.
- `gh_mlt_rsi_reversion` (stefan-jansen/machine-learning-for-trading): Buy when the 14-candle RSI is under 30 and sell when it is over 70 (16_strategy_simulation/03_single_asset_vectorbt.py).
- `gh_nehren_two_ma` (NehrenD/algo_trading_and_quant_strategies): Long while the 60-candle average is above the 120-candle average, short while below; `momentum` in exercises/chapter5_solutions.ipynb.
- `gh_rid_macd_rsi` (Ridwat/Project-3-ML-for-Predicting-Trading-Signal): The rule its classifiers copy, run as a rule: buy when MACD 12/26/9 crosses up and RSI (ewm span 14) is under 30, short when it crosses down and RSI is over 70 (same candle; setting 2: RSI within the last 5 candles); out on the opposite signal or the engine's stop (Project_3_ML_for_Predicting_Trading_Signals.ipynb).
- `gh_es_sma_ml` (ethansilvas/sma-ml-trading-algorithm): Fast and slow simple averages (4/150 bars ethansilvas, 8/20 Mun-Min) as inputs, label 'next candle closes up or flat'; their SVM is replaced by gradient boosting; long when it says up, short when down, always in and flipping (machine_learning_trading_bot.ipynb).
- `gh_agi_sol_ema` (agiprolabs/claude-trading-skills): EMA 12 above EMA 26, EMA 26 up over 3 candles, volume over 1.5x its 20-candle average and ADX over 20: buy; out when EMA 12 falls back under EMA 26, the stop, or a 3x-stop target (its ATR trail, 20-candle time stop and 4h check not copied); skills/strategy-framework/SKILL.md.
- `gh_finrl_turbulence_hold` (AI4Finance-Foundation/FinRL): Hold the coin while today's move is not unusually large against the last 252 candles (FinRL's turbulence index, one coin) and sell at or above the 99% (or 90%) mark of all earlier readings (finrl/meta/preprocessor/preprocessors.py calculate_turbulence).
- `gh_agi_ema_cross` (agiprolabs/claude-trading-skills): Flat and EMA 10 crosses above EMA 30: buy, out only by the stop or a target at 2x the stop (the repo's stop is 2x ATR, here the engine's fixed stops); skills/backtrader/references/strategy_patterns.md `EMABracket`.
- `gh_danny_ma_baseline` (Danny-397/RL-for-Crypto-and-stocks-): Buy while the 10-candle average is above the 30-candle average and sell when it is not (rl_trader/evaluation/baselines.py, the moving-average baseline the study's agent had to beat).
- `gh_mlt_momentum_band` (stefan-jansen/machine-learning-for-trading): Buy when the price is more than 1% above where it was 20 candles ago and sell when it is more than 1% below (16_strategy_simulation/05_stateful_strategies.py).
- `gh_cs_rsi` (Log-zz-ikIO/crypto-signal): Buy when TA-Lib RSI 14 is at or under 30 and nothing is held, sell when it is at or over 70; long only (app/behaviours/rsi_bot.py with app/default-config.json). The repo's share counts are not used: the engine trades $5 x 20x with its own stop.
- `gh_qt_bollinger_w` (je-suis-tm/quant-trading): Buy a close above the upper 20-candle band that completes a W double bottom in the last 75 candles; out when the band's standard deviation drops under beta; alpha and beta (0.0001 in GBP/USD prices) are read as 0.01% of the price, or 0.1% in the second setting (Bollinger Bands Pattern Recognition backtest.py). The repo's share counts are not used: the engine trades $5 x 20x with its own stop.
- `gh_hudson_ma_cross` (hudson-and-thames/backtest_tutorial): Long while the 50-candle average is above the 252-candle average, short while below, always in; Vectorized_Backtest_Tutorial.ipynb (day windows kept as candles; its volatility-targeted size up to 2x cannot be copied, the engine trades a fixed $5 x 20x).
- `gh_pyb_breakout20` (edtechre/pybroker): Flat and close above the highest high of the previous 20 candles: buy; close under the lowest low of the previous 20: sell; notebook 18 `breakout` (its top-3-by-dollar-volume universe and 1/3 size not copied).
- `gh_agi_rsi` (agiprolabs/claude-trading-skills): Flat and RSI(14) under 30: buy; RSI over 70: sell; 5% stop; skills/backtrader/references/strategy_patterns.md `RSIMeanReversion`.
- `gh_finrl_tsmom` (AI4Finance-Foundation/FinRL-Trading): At each month's last daily candle: month-end close / the month-end close 11 months earlier - 1 (12 monthly rows); long for the coming month above +10% (or 0), short below -10% (or 0), flat between, re-entered each month end; src/strategies/tsmomsignal.py; 1d candles only.

## Not ported, and why

- 772435284/transformers_versus_lstms_for_electronic_trading: Predicts the order-book middle price over the next 20-100 book updates from 10-level snapshots; our candle frame has no order-book series. Its results are only images.
- AI4Finance-Foundation/FinRL-Trading: rotation, ML stock picking, DRL allocator: The weekly rotation ranks 28 stocks, the ML picker needs quarterly company fundamentals, and the DRL allocator weights many stocks at once.
- AI4Finance-Foundation/FinRL-Tutorials: Notebooks running FinRL's trained agents (ensemble, portfolio allocation, multi-crypto PPO, forex, A-shares); the triple-barrier part only labels data for a neural network. Its own saved runs: the ensemble lost 3.9% a year, and 3 of 5 single agents ended down.
- AI4Finance-Foundation/FinRL: RL agents: A2C/PPO/DDPG/TD3/SAC/TQC/CrossQ networks trained on a 30-stock basket choose share counts each day; training a network per coin is not a rule this engine can run (only the turbulence switch is ported). No results printed in the repo.
- AI4Finance-Foundation/FinRL: ensemble: Picks the best of five trained agents every 63 days by Sharpe - trained models again, and the same choose-on-recent idea the picker lab found does not carry forward.
- Danny-397/RL-for-Crypto-and-stocks-: PPO agent: A PPO network trained per coin; its own result: crypto -44.6% against buy-and-hold +10% over 10-30 seeds.
- Danny-397/RL-for-Crypto-and-stocks-: supervised baselines: Ridge and logistic models fitted on a training split - trained models, not rules.
- KennethMartin06/ml-based-algorithmic-trading-signals: LSTM: its 10/20-day sequence LSTM would be another gradient-boosting stand-in on the same features, identical to gh_km_xgb's; left out of the ensemble too
- Log-zz-ikIO/crypto-signal: default alerts: SMA, EMA, MACD, Bollinger, Ichimoku and the breakout share are called with thresholds 0, so they fire on every coin every time or never; they print alerts and name no buy or sell.
- NehrenD/algo_trading_and_quant_strategies: pair trading: Distance, cointegration and APT pairs need two instruments at once, and the notebook stops before any pair rule exists.
- PacktPublishing/Machine-Learning-for-Algorithmic-Trading-Second-Edition: Every backtest is a long 25 / short 25 basket of 500-1,000 stocks ranked by a factor or a trained model, a two-series cointegrated pair, or a DQN on AAPL - none is a single-series rule. Its one model tested on two clean unseen years (Japan) lost 6% a year.
- QuantConnect/Research: VXX fear-index rule: reads VXX (a fear-index fund) to trade SPY, IWM and DIA - two series at once, and Gate has no fear index; its formula is ported on the coin itself as gh_qc_ema_cross.
- QuantConnect/Research: XOM/CVX pairs: cointegration and Kalman-filter pair trades need two coins at once (and fit their bands on the whole period).
- QuantConnect/Research: other notebooks: factor ranking, P/E picks, uncorrelated assets, mean-variance and Treasury mean reversion pick among many assets; the HMM, random forest, PCA and LSTM notebooks forecast without a trading rule.
- Thomas-lcb/Deep-Reinforcemen-tLearning-Trading-Agent: A PPO agent on BTC 1-minute candles; its 200-minute cooldown is attached only to that agent and to a random agent, never to a rule. Its own result: +9.10% on test days it was tuned on, -9.51% on validation against random -9.30%.
- TradeMaster-NTU/TradeMaster: Every method is a trained RL agent (DeepScalper, Double DQN on order books, EIIE, DeepTrader, ...); its only plain baseline is buy-and-hold. DeepScalper's BTC result: -199.6% on validation, one seed.
- YuxinSUN89/quant-ohlcv-feature: A library of 540 indicator formulas for a model's inputs; no entry, exit or backtest to port.
- abailey81/Crypto-Statistical-Arbitrage: Pair trading needs two coins' prices at once, and its funding and futures-curve trades need several venues' funding and dated futures; one coin's candles cannot run either.
- agiprolabs/claude-trading-skills: other recipes: only the signal-classification recipe is a machine-learning signal; its Kalshi, copy-trading and on-chain recipes need data this engine does not have
- agiprolabs/claude-trading-skills: pairs, copy trading, prediction markets, on-chain score: Need a second instrument, other wallets' trades, prediction-market brackets or on-chain data.
- agiprolabs/claude-trading-skills: regime-adaptive switch: Left out to keep the batch small; its two halves (the EMA 10/30 cross and RSI mean reversion) are ported on their own, and its thresholds were tuned on made-up data with planted regimes.
- agiprolabs/claude-trading-skills: signal classifier: The XGBoost / gradient-boosting classifier is ML - another batch's.
- ahmedas91/ml-ohlcv-alpha-signals: cross-sectional decile long-short: Ranks ~1,000 stocks each day by an elastic net over 105 features and holds the top tenth long, bottom tenth short - needs every coin at once. Its own result: about 1.56 basis points a day before costs (ported only as the single-coin reversal stand-in).
- bernhardbrugger/awesome-ai-trading: A reading list of tools, data and papers; no strategy of its own.
- cbailes/awesome-deep-trading: A reading list of papers and links; no strategy of its own.
- ebrahimpichka/DeepRL-trade: PPO and DQN networks trading GOOG long/flat/short; no rule. The test days chose which saved model was reported (+61% / +118% vs buy-and-hold +33%).
- edtechre/pybroker: ML examples: Linear regression, random forest, GARCH filter and the multi-symbol model are machine learning - another batch's.
- edtechre/pybroker: other examples: the rotations, rankings and rebalances need several stocks at once; the linear-regression and GARCH examples are not its random-forest example, which is the one ported
- edtechre/pybroker: ranking, rotation, rebalance and symbol selection: Volume rank, 5-day ROC rank, 20-day ROC rotation, monthly rebalance and the dollar-volume universe each choose among many stocks at once.
- edtechre/pybroker: stops notebook: Buys whenever flat with no signal, to demonstrate stop and trailing-stop orders; there is no rule to port.
- hudson-and-thames/backtest_tutorial: volatility-targeted size: Size = 15% / 22-day volatility capped at 2x cannot be copied: the engine stakes a fixed $5 x 20x; the signal itself is gh_hudson_ma_cross.
- je-suis-tm/quant-trading: Monte Carlo: a test of price forecasting by random paths, no trading rule.
- je-suis-tm/quant-trading: Oil Money: regresses a currency on Brent crude, two series at once; the engine holds one coin.
- je-suis-tm/quant-trading: Options Straddle: buys a call and a put; Gate's contracts have no options.
- je-suis-tm/quant-trading: Pair trading: trades NVDA against AMD at once (a cointegration test on two price series); the engine holds one coin.
- je-suis-tm/quant-trading: Portfolio Optimization: lives in another repo (graph-theory) and weights many assets; no timing rule.
- je-suis-tm/quant-trading: RSI head-and-shoulders: never run by the script's main, and its tolerances (0.2, 1.1 x 0.2) are dollars of one stock, meaningless across coins.
- je-suis-tm/quant-trading: Smart Farmers: a yearly crop supply forecast, no trading rule.
- je-suis-tm/quant-trading: VIX Calculator: a volatility calculator from an options chain, no trading rule.
- je-suis-tm/quant-trading: Wisdom of Crowds: lives in another repo (machine-learning); not a single-coin rule.
- jwallbridge/translob: A transformer classifier of the next 10-100 order-book events on the FI-2010 stock book data; no trading rule, and our candle frame has no order-book series.
- mindees/crypto-ai: The repo is gone (GitHub answers 404 on Nov 18, 2026); nothing to read.
- sjev/twp: energy spread, permanent portfolio, leveraged-ETF pairs: Each holds two to four instruments at once.
- sjev/twp: smartVXX and the VXX nearest-neighbours model: Need the VIX and VIX3M indexes beside the traded fund (a second and third series); the neighbours model is ML, another batch's.
- sjev/twp: walk-forward re-tuned MA cross: Re-tunes 19 x 20 average pairs on 2 years of daily candles then trades 1 year - more daily history than most Gate coins have; its fixed settings are ported as gh_twp_ma_cross.
- stefan-jansen/machine-learning-for-trading: 12-1 momentum and ML chapters: The momentum study sorts 100 ETFs into buckets each month (cross-sectional); the model chapters (linear, boosting, deep learning, RL) are trained models.
- stefan-jansen/machine-learning-for-trading: crypto perps funding: Ranks 19 perpetuals every 8 hours by a trained elastic net on premium and funding features, long the top and short the bottom - cross-sectional and trained. Its own holdout: -44.8% a year, 82% drawdown.
- tmr-crypto/wf_optim_crypto_analysis: robust-Sharpe window choice: The 9 x 9 grid of tuning/trading windows was smoothed and chosen on BTC 2018-2019; the two windows it kept (7/28 and 14/10 days) are used directly.
- topics/walk-forward-validation: A GitHub topic page listing other repos; no strategy of its own.
