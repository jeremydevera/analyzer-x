# Log-zz-ikIO/crypto-signal

- Link: https://github.com/Log-zz-ikIO/crypto-signal
- What it is: an early (January 2018) copy of the "Crypto Signals" alert bot, which prints a few indicator readings for every coin on an exchange and sends a text, email or Slack message when one crosses a line; it has no backtest at all.
- Stars, last push, licence: 1 star, last push Apr 03, 2023, MIT. It is a fork of CryptoSignal/Crypto-Signal, made Jan 16, 2018, and holds that project's very early "alpha" code.
- Markets and timeframes: spot crypto pairs on Bittrex (and anything ccxt reads: Binance, GDAX, Bitfinex, Gemini), quoted in BTC, ETH, LTC or USDT. It reads 1-day candles for most checks and 5-minute candles for the "breakout" check, 100 days back, and repeats every 300 seconds (`update_interval` in `app/default-config.json`).
- Read: `README.md`, `app/default-config.json`, `app/app.py`, `app/behaviour.py`, `app/analysis.py`, `app/behaviours/default.py`, `app/behaviours/rsi_bot.py`, `app/strategies/breakout.py`, `app/strategies/ichimoku_cloud.py`, `app/strategies/strategy_utils.py`.

## The strategies

There are two "behaviours". Neither ever places a real order.

**1. Default alerts** (`app/behaviours/default.py`, numbers from `app/analysis.py`). For every pair it works out, and messages when "hot" or "cold":
- RSI over 14 candles of 1-day closes (`period_count = 14`). "Oversold" when RSI is at or under `hot_thresh`, "overbought" when at or over `cold_thresh`.
- Simple average and exponential average, both 15 candles of 1-day closes (`period_count = 15`). "Trending well" when the average is at or over `hot_thresh`.
- MACD with TA-Lib's defaults (12/26/9) on 1-day closes. Printed only; it never says hot or cold.
- Bollinger bands with TA-Lib's defaults (20 candles, 2 standard deviations). Printed only; the default behaviour never calls it.
- Ichimoku: "leading span A" and "B" over 9, 26 and 52 candles. Printed only; never hot or cold.
- "Breakout": out of 5 candles of 5-minute data, the share whose close equals their high AND whose open equals their low (a candle with no wicks that went straight up). "Breaking out" when that share is at or over `hot_thresh`.

The default behaviour calls every check with no thresholds, so they are all 0. That means: RSI "overbought" fires for every coin every time (RSI is always at or over 0), RSI "oversold" never fires, SMA and EMA "trending well" fire for every coin every time (a price average is always over 0), and "breaking out" fires for every coin every time (a share is always at or over 0). As shipped, the alerts carry no information.

**2. RSI bot** (`app/behaviours/rsi_bot.py`, settings in `app/default-config.json`, `"mode": "simulate"`):
- Input: RSI 14 on 1-day closes for every pair, sorted lowest RSI first.
- Entry: RSI at or under 30 (`buy.rsi_threshold`), the coin not already held, and some of the quote coin left. It "buys" at the best ask of the order book.
- Exit: RSI at or over 70 (`sell.rsi_threshold`); "sells" at the best bid.
- No stop, no target, no time limit on a holding. Open orders older than 24 hours (`open_order_max_hours`) are cancelled, but only in "live" mode, and live mode does nothing (`print('Nothing to do yet')`).
- Size: the whole free balance of the quote coin, capped per trade at 0.02 BTC, 0.2 ETH, 1.2 LTC or 250 USDT (`trade_limits`). No leverage.

## How it tests them

It does not. There is no backtest, no train/test split, no walk-forward, no baseline. The "simulate" mode keeps a paper balance in a local database as the bot runs forward in real time.
- Fees: recorded as `'fee_rate': 0` on every simulated buy and sell (`rsi_bot.py`). No fee is charged.
- Slippage: it buys at the best ask and sells at the best bid, so it does pay the buy-sell gap once each way, but only for the first level of the book.
- Funding: none (spot only).

## What it claims

Nothing about results. The README says: "Development state: alpha (There are many bugs and documentation is often lagging)" and "Use this program as an educational tool, and nothing more." (`README.md`). Unchecked, but there is nothing to check.

## What matters for us

There is no result here to survive or fail our test: no backtest, no fees (`fee_rate` 0), no unseen days, no baseline. As shipped the alerts fire on every coin every time. The only rule is the textbook "buy at RSI 14 under 30, sell over 70" on daily candles. Our own measurement on Gate says the average trade earns about $0.00 before fees and costs about $0.23 per $100 in fees and the buy-sell gap, so a plain RSI rule like this should be expected to lose roughly that much a trade unless it shows something better.

Worth testing, if anything: the "no-wick candle" count (close = high and open = low) is an unusual way to call a burst; we could measure it as a trigger on our 15m-1h crypto data against random entries. The daily RSI 30/70 rule is almost certainly already inside our grid's RSI signals.

## Doubts

- I did not read `app/exchange.py`, `app/database.py`, `app/conf.py`, `app/notification.py` or the notifier files; they move data and messages and make no trading decision.
- `analyze_breakout` and `analyze_ichimoku_cloud` take the FIRST candles of the 100-day history (`historial_data[0:5]`, `[0:9]` and so on), i.e. the OLDEST ones, not the newest, so they describe the market of about 100 days ago (for the 5-minute breakout, whatever the exchange returns first).
- The Ichimoku lines use closing prices, not highs and lows as Ichimoku defines them, and the "Kijun-sen" and "Tenkan-sen" functions are identical code.
- The rsi_bot's open-order check compares a date with a text string (`time_to_hold > order_time`), which would fail in live mode.
- This fork is a frozen 2018 snapshot; the upstream project (CryptoSignal/Crypto-Signal) grew much later and is not described here.
