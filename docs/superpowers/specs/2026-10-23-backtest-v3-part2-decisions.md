# Backtest v3 Part 2 — how the families and the proof test are built (decisions inside the approved spec)

**Date:** Oct 23, 2026 · **Spec:** `docs/superpowers/specs/2026-10-22-backtest-v3-design.md` (approved Oct 22, 2026) ·
**Operator:** *"go"* (Oct 23, 2026), to "write step 2's plan and start it".

These are the choices the spec leaves open, made before any test, so nothing is chosen after seeing results.

## Two plans

* **Part 2a — on this PC, testable without GitHub:** the universe, the cross-coin data, the four families,
  the filters, the forced (rank) exit in the engine, the random entries, the proof test, and one coin's whole
  measurement (`measure_coin`) with a local command that runs a few coins end to end.
* **Part 2b — on GitHub (all 60 machines):** the shard and workflow, dispatch / redo / collect across the three
  accounts, the verdict store and the tab's tested-ideas list, the 20-coin pilot, the coverage check, the order-book
  backfill if the pilot shows it is needed, then the whole universe.

## The window and the split

* Up to the newest **365 days** per coin (younger coins: what exists, said on the row).
* **Unseen = the newest 90 days.** Two walks per setting, never one: the OLDER walk runs on the candles up to the
  split (a trade still open at the split is closed at its last candle, `END`), the UNSEEN walk runs on the newest
  90 days with the 300 candles before them as lead-in for the indicators only. So the setting choice can never see
  an unseen price, by construction — not by a filter applied afterwards.

## The universe (spec Part 2), built on this PC before a run and committed as the run's plan file

* Candidates are the contracts Gate trades TODAY (`fx.trading_symbols()`). Coins delisted during the year are
  missing — **survivorship bias, said beside every verdict**.
* **Liquid crypto** = `venue.kind() == "crypto"`, top 50 by 30-day traded value at each month start; traded value of
  a day = `Volume × contractSize × Close` of its daily candle (today's contract size: said).
* **Calm contracts** = kinds `metals`, `indices`, `forex`, plus liquid crypto in the calmest third by 60-day
  realized volatility (std of daily log returns) at each month start.
* **Never calm: a volatility index; never calm or liquid: a stablecoin** (ruled Oct 23, 2026, before any code
  of this part, when the first real plan put BVOL_USDT, EVOL_USDT, GVZ_USDT and VOLX_USDT — volatility
  indices, which jump by design — and USDC_USDT — a stablecoin Gate files as forex, which barely moves — in
  October's calm group by their kind). A stablecoin Gate filed as crypto would also top the liquid list by
  traded value and, on a falling week, rank first by its ~0% 14-day return, so it is never liquid either.
  Stablecoins are named by their base (USDC, USD1 and the other dollar stablecoins; never FRAX, which on Gate
  is the governance token at $0.26), and every contract left out is named in the plan's `left_out` with why.
* Membership is **per month**: a coin's signals count only in the months it is a member (a per-candle mask on the
  signal, never a filter on trades afterwards); a trade opened in a member month may run into the next.
* The plan file `research/v3/plan.json` carries every coin's monthly membership, BTC's daily mood and the weekly
  strength ranks, so every machine reads the same universe.

## The families (spec Part 2 table; settings fixed here)

| family | settings, in "simplest first" order (ties go to the earlier one) | timeframes | signal | exit |
|---|---|---|---|---|
| `v3_trend` | n = 20, 50, 100 (days; on 4h = 6n candles) | 1d, 4h | long every candle while close > SMA(n) and SMA(n) > its value 5 days earlier; calm contracts also short on the mirror | trail 3 × ATR(20) + out on a close past SMA(n) |
| `v3_breakout` | N = 20, 50 (days) | 1d | long when close > the highest high of the N days before it, while SMA(100 days) > its value 5 days earlier; calm contracts mirror short | trail 3 × ATR(20) |
| `v3_strength` | K = 3, 5 | 1d | long at each Monday 00:00 UTC rank when the coin is in the top K of liquid crypto by 14-day return: the signal candle is the daily candle CLOSING at that Monday 00:00 (Sunday's), so the order goes in at the rank | trail 3 × ATR(20), or out at the close of a later candle ending at a Monday 00:00 whose rank no longer has it in the top 2K (a FORCED exit, `why = "RANK"`) |
| `v3_snap` | k = 1.5, 2.0 | 1h, 4h | long when close ≤ SMA(20) − k × ATR(20), short when ≥ SMA(20) + k × ATR(20) | snap: the SMA(20) at the signal as a resting target, emergency stop 3 × ATR(20), out after 24 candles |

Signals are "every candle while it holds", so after an exit the engine's re-entry rule takes the next candle that
still signals — what a trend follower does.

The `v3_strength` row was corrected on Oct 23, 2026, before any of its code was written: the first text put the
signal on the candle OPENING on Monday, whose order goes in at Tuesday 00:00 — a day after the rank, on a price
the rank never saw. The spec says *"Each Monday 00:00 UTC rank liquid crypto by 14-day return; long the top K"*,
and the rank of Monday 00:00 reads the closes at that instant, so the order goes in right then.

## The filters (spec #5-#9), each on top of every family, as a mask on the signal

* `btc_mood` — alt-coin longs only while BTC's last CLOSED daily candle is above its 50-day SMA (BTC itself is not
  filtered; the mood of a day is known only after that day's candle closes).
* `busy_hours` — stock tokens: entries only when the order would go in 9:30am-4:00pm New York on a weekday
  (`daytime_rule.in_market_hours` of the order minute); every other contract — crypto, and the metals, indices and
  forex of the calm group, whose markets are shut at weekends — no entry whose order goes in on a Saturday or Sunday
  (UTC). No family's universe holds stock tokens today, so only the weekend half can bite — said on the verdict.
* `funding_side` — skip a long when the last settled funding rate before the order is in the top 10% of the coin's
  own settlements over the 30 days before it; a short in the bottom 10%. "Before" is strict: a settlement stamped
  AT the order's own instant has not settled for it, so an order on a settlement hour judges the cycle before it,
  and the 30 days are half-open, [order - 30 days, order) — a settlement stamped 0-7 s late lands on the same side
  of both edges as one stamped on the hour (ruled Oct 23, 2026, when the task review measured Gate stamping the same 00:00 / 08:00
  / 16:00 UTC settlements 0-7 s past the hour in some months and exactly on it in others — an "at or before" rule
  read the just-settled rate in one month and the rate 8 hours older in the next, which flipped 55 of BTC's 776
  daily decisions). Where the history does not reach, the filter cannot judge: the signal passes and is counted
  `funding_unknown` (Gate's funding history reached back to Jul 01-02, 2025 for BTC, ETH, SOL, XRP, LINK, XAUT and ADA
  on Oct 23, 2026 — about 480 days; it is the open-interest history that keeps about 180).
* `funding_minutes` — no order within 5 minutes either side of a funding settlement. On 1h/4h/1d candles that open on
  a settlement hour this blocks those entries outright; the verdict shows it.
* **`crash_guard` (#8) is NOT in Part 2a/2b's first run:** no reader of Gate's open-interest history exists yet and
  Gate keeps about 180 days; it is listed on the page as "not tested yet: needs open-interest history".
* `when_map` (#10) belongs to Part 3 (the re-test of the stored rows).

Combinations tried (the luck correction's count): 4 families with 3 + 2 + 2 + 2 = 9 settings × 2/1/1/2 timeframes
= 6 + 2 + 2 + 4 = **14 family-setting-timeframes**, each alone and with each of 4 filters = **70 combinations**,
so α = 0.05 / 70. Every combination is counted whether or not it trades.

## Random entries (the luck bar)

* For each combination's CHOSEN setting, per coin, on the unseen window: **200 seeded runs**. Each run places the same
  number of signals in each calendar month as the real run did there, on randomly drawn candles of that month (seeded
  by coin, timeframe, family, filter and run number — reproducible), with the same longs/shorts mix, the same exit,
  sizing and costs, through the same `v3_engine.walk`.
* To keep the choice blind, the shard measures the random runs for EVERY setting (only the chosen one is ever read).

## The proof test (spec Part 3), pooled over a family's coins

1. **Choose** on the older walks only: the setting with the best profit per trade after costs, pooled over the coins
   and their member months; a setting needs at least 30 older trades to be chosen; ties go to the simplest.
2. **Judge** the chosen setting on the unseen walks, pooled: passes only when
   * profit per trade after costs > 0;
   * profit per trade > the 1 − α/2 quantile of the 200 pooled random runs' profit per trade (α = 0.05 / 70)
     AND > the best of the 200. Two hundred runs cannot show a tail as far out as 1 − α/2 = 0.99964 by counting
     (their best is about the 0.995 point), so the quantile is read from a normal curve fitted to the 200
     (mean + z × standard deviation, z = Φ⁻¹(1 − α/2) ≈ 3.39), and the best run is the floor under it;
   * a day-clustered bootstrap: 2,000 seeded draws of the unseen trading days with replacement give the standard
     error of profit per trade; profit per trade − z × that error > 0 (the same z, for the same reason);
   * at least 300 unseen trades.
3. **Every verdict is kept** — passed or failed with the first failing step — with trades, wins, losses, win rate,
   break-even win rate, profit, profit per trade against random's (median and the bar), missed orders, post-only
   cancels, `cost_unmeasured`, `funding_estimated`, `funding_unknown`, the setting chosen, the coins and months used.

## What a machine returns per coin

Per combination and setting: the older and unseen trade lists in compact rows `[signal_ms, entry_ms, exit_ms, side,
pnl, why]`, the counts, and the random runs' per-run `(trades, profit)` on the unseen window. Nothing is chosen on a
machine; the PC chooses and judges after collecting every account's share.
