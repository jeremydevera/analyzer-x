---
name: crypto_skills
description: Use when the operator asks "what are available crypto skills", "what crypto skills do I have", "list crypto skills", or "/crypto_skills". Names the four installed crypto/trading skills and says in plain words how each one works. Asked for Nov 05, 2026.
---

# crypto_skills

The operator, Nov 05, 2026: *"install backtesting-frameworks,
backtesting-trading-strategies, technical-analysis, nextjs-app-router-patterns
(wshobson) then create a rule when i ask what are available crypto skills, you
mention them then give me description how they work"*.

## What to answer

First check each one is still installed on this PC:

```bash
ls ~/.claude/skills/ | grep -E "backtesting-frameworks|backtesting-trading-strategies|technical-analysis|nextjs-app-router-patterns"
```

Then answer with THIS table (plain words, short-and-plain), marking any that
are missing as "not installed on this PC" with its install command below:

| Skill | What it is for | How it works |
|---|---|---|
| **backtesting-frameworks** (wshobson, 17.3K installs) | Building a backtest you can trust | A guide, no programs. It lists the 5 ways backtests lie (peeking at future prices, testing only coins that survived, over-tuning to the past, cherry-picking, leaving out fees) and how to avoid each, with walk-forward testing (pick on old days, check on new days). It wakes up when we build or check backtesting code. |
| **backtesting-trading-strategies** (jeremylongshore, 4.7K installs) | Quick tests of simple strategies | Comes with its own Python programs and 8 ready strategies (moving averages, RSI, MACD, Bollinger, breakout, mean reversion, momentum). It downloads price history from Yahoo Finance or CoinGecko, replays the trades, and prints profit, worst drop and Sharpe ratio (profit versus how bumpy the ride was). It can also try many settings to find the best one. It does NOT use Gate or your per-minute fees, so its numbers will look better than your app's — use it for quick ideas, never to decide what to switch on. |
| **technical-analysis** (omer-metin, 2K installs) | Understanding chart signals | A guide, no programs. It explains indicators (RSI, MACD, moving averages), chart patterns, support and resistance, candlesticks and Fibonacci, and warns which ones fail when tested. It wakes up when we talk about indicators or chart patterns. |
| **nextjs-app-router-patterns** (wshobson, 33.3K installs) | Building the website itself | A guide, no programs. It covers how to build pages in Next.js (your site runs Next.js 16 with the `app` folder): what loads on the server vs the browser, loading screens, and fetching data. It wakes up when we change the web pages. |

Then ONE line: they wake up by themselves when the work matches, or the
operator can name one (e.g. "use backtesting-frameworks to check this").

Mention, in one line, that the project's own trading skills
(`/practice_backtest_audit`, `/still-working`, `/winning_room_strategy`,
`/feedcheck`, `/press-and-watch`) know Gate and this app's rules and stay the
ones that decide anything.

## On another PC

These four live in the user's own skills folder, not in this repo. Install
them there with:

```bash
npx -y skills add wshobson/agents@backtesting-frameworks -g -y
npx -y skills add jeremylongshore/tons-of-skills-marketplace@backtesting-trading-strategies -g -y
npx -y skills add omer-metin/skills-for-antigravity@technical-analysis -g -y
npx -y skills add wshobson/agents@nextjs-app-router-patterns -g -y
```

backtesting-trading-strategies needs `pip install pandas numpy yfinance
matplotlib` in the Python it runs with before its programs work.
