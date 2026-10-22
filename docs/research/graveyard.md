# Research graveyard — ideas that were measured and did not hold

Prompt 2 (research/cq/prompts.md, Oct 21, 2026): *"If it did not: record it in
docs/research/graveyard.md and stop. Nothing else was changed, so there is
nothing to undo."* One entry per idea that failed its own pre-registered
check, with its numbers, newest first. Never delete an entry: the next idea
reads this before it spends machine time.

## Oct 22, 2026 — confluence entries (Prompt 1) and computer-chosen TP/SL (Prompt 2)

* **The idea.** Prompt 1: for every Gate coin and timeframe, search
  combinations of a trigger (flag, session break, EMA cross, pullback,
  squeeze) and one or two confirmations of other families, at 2:1R or better
  after fees, for the highest worst-case win rate. Prompt 2: let the computer
  choose each trade's stop and target from the chart at entry, only for
  entries that beat random entries before fees.
* **How it was measured.** The nightly grid's own engine on GitHub (minute
  exits, each minute's order book for the newest ~45 days, the runner's
  refusals), three stretches by the day each trade closed: tuning (chosen
  on), check (judged on), test (never read by the search). Random-entry
  searches chosen the same way on 100 sample coins as the luck bar. Code:
  `tradingagents/signals_cq.py`, `cq_core.py`, `cq_search.py`,
  `cq_report.py`, `.github/scripts/cq_shard.py`; plan
  `docs/superpowers/plans/2026-10-21-confluence-research-phase-a.md`.
* **Size.** 1,056 coins x 5 timeframes: 4,221 coin + timeframes searched
  (28,717,380 candidates + 3,156,820 random), 1,059 left out by name (683 on
  137 coins Gate will not let the app hold at 20x, 369 where no stop of 2% or
  less pays 2:1 on that coin's fees, 6 with one candle, KIMCHI 1d).
* **Prompt 1's first check (failed).** Search pick vs random pick per coin +
  timeframe, before fees, on the test days, averaged per coin: **+0.033R a
  trade, 90% range −0.079R to +0.146R over 67 coins** (226 coin +
  timeframes); the 20-coin pilot alone: +0.048R, −0.066R to +0.163R. Not
  clearly above zero.
* **Prompt 2's first check (failed).** The search's pick beat its random pick
  (low end of its 90% range above random's average, before fees) on **23 of
  226** coin + timeframes; the random pick beat the search's the same way on
  **24**. That is the luck rate, so no entry was carried into the open TP/SL
  search, and its engine was not built.
* **What it adds to the record.** The third independent search (after
  Crypto-Predictor, Oct 19, and Pro Trader, Oct 20, 2026) where the best
  strategy found on past days carries no edge into unseen days, even before
  fees.
* **Pages.** All coins: https://claude.ai/artifact/LjdTJfkfFUKk3Lxw3QT9Nk;
  Prompt 2's check: https://claude.ai/artifact/8wi95wHAjnZDeBf4XcsDxG; pilot:
  https://claude.ai/artifact/BkwHaSYNdkjoM68hu9JbME.
* **Changed in the trading program:** nothing. Nothing was switched on or
  filed into Stored strategies.
