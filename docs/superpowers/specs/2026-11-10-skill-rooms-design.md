# Skill rooms — Forecast v4's three rule sets traded in practice, exactly as their backtest did

Date: Nov 10, 2026. Status: approved by the operator in chat ("go start use suporpower").

## The asks, word for word

1. *"in auto trade can you create forecast v4 but this time use my backtest v4 data"* — built
   (commit b69f18bf).
2. *"which one do you recommend that is stable"* — answered #D7EN8BNV, beside #RSS7CUKH and
   #7T3VJU82.
3. *"can you deploy this 3 and remove the existing strategy in my auto trade"* (Nov 10, 2026
   10:24pm).
4. Asked "My guess is that you want practice to trade these exactly the way their backtest did, so
   the forecast's dollars carry over", they answered *"okay es for this"* (10:30pm).
5. The playback (below, "What they approved") answered with *"go start use suporpower"* (10:41pm).

## Why

The operator's month-long goal is *"align it with practice so I know exactly how much will i
earn"*. Forecast v4 walked 3,600 switch-on rules day by day over Backtest v4's Claude-skill trades
and found three that were steady. These are their numbers, Aug 01 to Nov 06, 2026, $5 x 20x:

| Rule set | Profit | By month (Nov is part) | Worst day |
|---|---|---|---|
| #D7EN8BNV | +$289.81 | Aug +49.17, Sep +91.76, Oct +139.11, Nov +9.77 | −13.96 |
| #RSS7CUKH | +$283.67 | Aug +57.28, Sep +78.74, Oct +116.11, Nov +31.54 | −23.17 |
| #7T3VJU82 | +$498.16 | Aug +101.86, Sep +132.42, Oct +218.96, Nov +44.92 | −52.75 |

The app cannot trade them today. The practice runner only knows Backtest v2's rules: a target and
a stop resting on the minute, and one trade per coin. The skill strategies follow different rules:

- they buy and sell at a candle's close;
- they close on the close, on the opposite signal, or when the stop or target is reached;
- several strategies may hold the same coin.

Traded by the runner, their dollars would not carry over. **So practice must run the backtest's
OWN code, candle by candle. Practice and backtest then cannot drift apart, because there is only
one set of rules.**

## What they approved (the playback)

1. **Three new practice rooms in Auto Trade**, named by their rule: #D7EN8BNV, #RSS7CUKH and
   #7T3VJU82.
   - Each has its own tab, tiles, trades and calendar, like the other rooms.
   - Each trade is $5 x 20x = $100 of coin.
   - No real money, ever.
2. **Every day at 7:00pm (12:00am UTC)** each room switches on the strategies that pass its rule
   and switches off the ones that no longer pass. The rules, exactly as Forecast v4 walked them:

   | Room | Judged on | Won at least | Of at least | Timeframe | Skill | TP rule | Stop |
   |---|---|---|---|---|---|---|---|
   | #D7EN8BNV | the last 30 days | 90% | 20 trades | any | any | any | any |
   | #RSS7CUKH | the last 30 days | 80% | 20 trades | any | any | any | 1.5% or tighter |
   | #7T3VJU82 | the last 30 days | 80% | 20 trades | 1h | any | any | any |

   Forecast v4's own walk (`forecast_v4._walk`) is the definition. The trades read are those that
   CLOSED before that midnight, inside the window. The skill backtesting-trading-strategies' trades
   that opened before its split are left out, because it was chosen on them.
3. **Each trade follows the backtest's own rules.**
   - Buy at the signal candle's close plus the coin's usual gap.
   - At each later close: the stop, then the target, then the opposite signal.
   - Several strategies may hold one coin.
   - All of it comes from the backtest's code, never a second copy.
4. **Backtest v4 is re-measured every day on GitHub's machines**, so "the last 30 days" is always
   the latest 30. Forecast v4 is rebuilt with it.
5. **Removing the existing strategies:** the watchers in the other 10 rooms are switched off, so
   nothing new is switched on there.
   - Their tabs and past trades stay.
   - #09439DC2 (the room `main`) is left alone; they did not name it.
   - Measured Nov 10, 2026: all 11 rooms had 0 strategies switched on, each watcher still `act`.

## Goals

- The three rooms trade every switched-on strategy exactly as the backtest's own walk would, on
  the same candles, at the same prices, with the same fee and gap.
- Each room shows its trades in every existing Auto Trade panel: today, all time, open,
  history, calendar, and the Main tab's all-rooms past trades.
- Backtest v4 and Forecast v4 are re-measured daily, with every failure named on screen.
- **A daily agreement check.** After each refresh, every trade the rooms made the day before is
  compared with the re-measured backtest's trade of the same strategy. The room prints the result,
  e.g. "yesterday: 37 of 37 trades the same as the backtest". This is the operator's goal measured
  every day, not assumed.
  - A trade is "the same" when the strategy, side, entry candle, exit candle and exit reason all
    match.
  - The dollar difference is printed beside the count, never hidden in a tolerance. The gap is
    read fresh by every run, so cents can move.
  - A trade only one side has is listed with its id.

## Non-goals

- Real money. The follower places no order at all; there is no real-money box in these rooms.
- Changing the runner, Backtest v2, any other room's rules, or #09439DC2.
- Minute-exact exits or per-minute order-book costs. The skill backtest charges the coin's usual
  gap and settles on the close; practice copies that.
- One trade per coin. The backtest allows several, so practice does too.

## Anti-goals (a failure even if it "works")

- Practice trades that differ from what the backtest says without the difference being counted
  and named.
- A second implementation of the exit or entry rules.
- A room that silently stops following. Every pass leaves a heartbeat the room shows.
- Switching on from yesterday's data without saying so.
- A normal runner acting on a follower room's positions. The runner books a TP/SL exit on any
  practice position whose key it knows, and writes `paper_cleared` rows for keys it does not.
- Ids that change from day to day.

## How it works

### 1. The rooms (`profiles.BUILTIN`)

- Three entries with ids `D7EN8BNV`, `RSS7CUKH` and `7T3VJU82`, appended after `BBE0A361` in tab
  order. Each carries `follows: "v4"` and `v4_rule: {window, win_rate, min_trades, tp_rule,
  sl_cap, tf, skill}`, copied from `forecast_v4.load()` (the values in the table above).
- A follower room:
  - forces its watcher off (`mode_of`, like `retired`);
  - is never given a runner. The supervisor's start check (`api.py` ~432), `room_restart`
    (~60) and `start_runner` all refuse it by name.
- `webapp/src/lib/api.ts` `PROFILES` gets the three in the same order, and the two tests that pin
  the list are updated. They are NOT added to `test_rooms_judge_on_15_days.TABLE`: they are not
  research rule ids.

### 2. One engine, stepped one candle at a time

- `skill_bt.walk()` is split into a per-candle `step()` and the loop that calls it. With no
  funding passed, `walk()` stays byte-for-byte the same in its results (`tests/test_skill_bt.py`
  and `test_skill_ta.py` keep passing). With funding, `step()` charges each settlement inside the
  hold. The follower calls `step()`, so there is ONE set of rules.
- A signal at candle i is computed as the backtest computes it:
  - backtesting-trading-strategies: `generate_signals` over the `window(params)` closed candles
    ending at i.
  - technical-analysis and backtesting-frameworks: `signals_all` over the newest `BARS[tf]`
    closed candles ending at i, taking the last value.
- Two families depend on where the frame starts: the ADX smoothing of `ma_filtered_cross`, and
  the swing list of `structure_break`. The daily agreement check counts any difference they make;
  it is never assumed to be zero.

### 3. The follower (`tradingagents/v4_follow.py`)

- One pass, in its own API supervisor thread (`v4-follow`, the `v3-forward` pattern) under a file
  lock (`portable.lock_exclusive`), 20 seconds after each 15-minute close.
- For every room and every strategy that is switched on, or still holds a trade, it processes
  EVERY closed candle since the last one it processed, in order. A sleeping PC or a restart
  therefore loses nothing: the follower catches up candle by candle, with candle times. Candles
  come through `exchange as fx` (one door), closed candles only.
- **Switch-on at midnight UTC:**
  - It first warms the strategy up by walking the newest `BARS[tf]` candles ending at 00:00 UTC
    with the same engine.
  - A trade that warm-up leaves open is CARRIED. It is followed to its exit, so the strategy
    cannot buy until the backtest could, but it is not counted and not shown, as Forecast v4 did
    not count it.
- **Switch-off:** a strategy switched off takes no new trade. A trade it holds is finished by its
  own rules, as the runner finishes a switched-off practice trade.
- **What it writes, in the room's own files** (`profiles.using(room)`, `at.append_ledger`,
  `at.save_state(keys=[slot])`), in the runner's shapes so every panel reads them unchanged:
  - `strategy` = `v4_<ID>` (e.g. `v4_9HZYB3B5`);
  - `trade_id` = `at.trade_code(symbol, strategy, entry_ts, side)`;
  - `entry_ts` = the signal candle's open, as the backtest records it;
  - `opened_at` = that candle's close (the fill);
  - `margin` 5, `leverage` 20, `dry_run` true;
  - `entry` and `exit` = the close plus or minus the gap;
  - `pnl_est` = the engine's own dollars;
  - `why` = SL, TP or SIGNAL;
  - `ts` on an exit = the exit candle's close, so "today" and the calendar fall on the
    backtest's day;
  - `written_at` = when the follower wrote the row.
- **The gap and fee are the strategy's own** (`strat.slip`, `strat.fee` in the newest Backtest v4
  store), written on the enter row. A trade keeps them to its exit.
- **The strategy id column** shows the v4 id: `api.row_id_for` resolves `v4_` keys.

### 4. The daily refresh (`tradingagents/v4_daily.py`)

- **Starts 00:05 UTC (7:05pm local) every day**, so its candles end at exactly the midnight the
  rule is judged at. Forecast v4's walk judged the same way. The steps:
  1. `skillbt.yml` on every account's machines (all 60), dealt with `split_coins`, each fork
     synced first.
  2. Collect.
  3. `v4_store.build`.
  4. `forecast_v4.build`.
  5. Switch-on for the three rooms.
  6. The agreement check.
- **The universe is pinned to today's 242,313 strategies,** so ids never come and go:
  - all 42 technical-analysis + backtesting-frameworks settings on every coin-timeframe;
  - and exactly the 15,933 backtesting-trading-strategies settings kept on Nov 05, 2026. These
    are committed as a list the shard measures, never re-chosen. A daily re-choice of "the best 3"
    would swap ids every day.
  - Each bt strategy keeps its ORIGINAL split (Nov 05, 2026 run) as the line before which its
    trades are left out, because that is what it was chosen on.
- **Which day's list owns a trade:** the day its `entry_ts` (the signal candle's OPEN) falls in,
  as `forecast_v4._walk` counts by `en`. A 15m candle opening 11:45pm UTC and filling at midnight
  belongs to the day before, so does a 1d candle opening the day before.
- **Until the day's list lands, the follower HOLDS at midnight UTC.** It processes no candle that
  opened at or after 00:00 UTC, entries and exits alike, and nothing is ever written and taken
  back. The room says *"waiting for today's list (<why>); trades since 7:00pm are filled in when
  it lands"*. Then:
  - The follower replays every candle since midnight with the new list, at their real candle
    times. The ledger is append-only and always right.
  - The room says how many trades were filled in that way.
  - A day not landed by 06:00 UTC is given up by name. Yesterday's list is then applied from
    midnight the same way, and the room says so.
- **First start:** a refresh runs first. The rooms never switch on from the Nov 06, 2026 store.
- **The conventions every other daily job follows** (`room_strategies_daily` is the template):
  - The deal and each attempt are saved before a dispatch, and a run GitHub listed late is
    adopted (`forecast_v2_daily.dispatch(since=)`, a `title_of` entry for `skillbt.yml`).
  - An account refusing twice ends the day, named.
  - A green run that measured 0 coins is red.
  - A share missing coins is never published.
  - It does nothing under pytest, prints a `[v4-daily]` line only when its sentence changes, and
    serves a `status()` that the rooms and Backtest v4 show.
- Big files go under `market_sweep.HOME` (G:).
- Forecast v4 stays a note page. Its numbers now move daily.
- **The store is REPLACED daily, never merged.** Every number comes from one measurement over the
  shard's frames (15m 30 days, 30m 60, 1h 90, 4h 180, 1d 730), as Backtest v2's rolling 30 days
  does. Merging re-measured, overlapping frames would mix two runs in one strategy.
  - What replacing costs: Forecast v4's older months lose the short timeframes as the frames
    slide, so the Aug-Oct figures these rooms were chosen on cannot be re-made later.
  - What keeps them: each day's `forecast.json` is kept gzipped and dated under
    `stores.V4.home/forecast-days/`, never deleted. The Nov 10, 2026 store is kept as
    `rows-2026-11-10.db` before the first refresh.
- **A trade still open at the end of a run (`why` END) is NOT a finished trade.** It never counts
  towards a switch-on window, in the rooms or in Forecast v4's walk, and Forecast v4 does not
  count its made-up dollars. 44,174 of today's 7,145,966 trades are END. In the Nov 10 forecast
  they could only touch its last day; in a daily refresh they would touch every day.
- **Funding is charged (CLAUDE.md rule 9, mandatory).** The daily shard passes each coin's
  funding history, and the shared `step()` charges every settlement inside a trade's hold. With
  no funding passed, `walk()` gives exactly today's results, so the old tests still pin it.
  - Practice charges the same settlements through the same `step()`. Practice and backtest stay
    equal; both get more honest.
  - What this costs: every Forecast v4 number moves after the first refresh, and the three rules
    may switch on different strategies than the Nov 10 walk did. The rooms keep their rules.
- **Costs not charged, named on every room and on Backtest v4** (CLAUDE.md, Oct 22, 2026: print
  the share that paid a typical cost):
  - "every trade pays its coin's usual gap, not its own minute's order book (100% typical
    cost)";
  - "no trade is refused by the runner's cost check".

  The skill engine has neither, and building them is a separate job.
- **A pinned coin that cannot be measured:**
  - A coin the exchange no longer trades is dropped from the pinned list and named. A
    switched-on strategy on it is switched off. An open practice trade on it is closed at its
    last candle with `why` DELISTED, named.
  - A coin that fails is redone alone (the failed-coin rule). If it still fails, it is named and
    its strategies keep the previous day's trades, marked stale, while every other coin
    publishes. Completeness is judged against the pinned list less the delisted coins.

### 5. Removing the other rooms' strategies

- Once the code is live, `strategy_watcher.set_mode("off")` runs under `profiles.using(id)` for
  each of #55D32617, #4FC03172, #B2404C0B, #6B08FF64, #CC94D9FB, #99E79CBA, #C7396286, #1D4274C1,
  #8F0C7926 and #BBE0A361.
- Each room's deploy log gets a reason line.
- `retire_room()` is not used. It would also remove nothing (0 rows are on), and `retired` would
  remove the tab and the Main tab's history.

### 6. What a follower room's tab shows

- The usual tiles and panels (from the files above).
- In place of the runner's badge and buttons (STOP RUNNER, HALT ENTRIES, PANIC), one line:
  *"PAPER · follows Backtest v4 · last candle 7:15pm · next 7:30pm"*. It turns into
  *"not following: <why>"* when the last pass is more than 30 minutes old or failed.
- A "Switched on today" list: each strategy's id, coin, timeframe, rule words and its last-30-day
  record.
- The day's refresh sentence.
- Yesterday's agreement check.
- The room's rule in words.

## Constraints (from CLAUDE.md, the ones this touches)

- Dates only through `fmt_when` / `fmtWhen`.
- One door to the exchange (`exchange as fx`).
- Every GitHub job uses every account's machines; push every commit to origin, colleague and
  teammate (`commit_own.py`).
- A test starts no background program and writes only under `tmp_path`.
- No path under `~/.tradingagents` at module top level; paths are resolved through `_pp` at call
  time.
- No Python string constant containing the word "Main".
- Nothing is put below an entry-point guard.
- A long process writes a log and names its failures; "is it running" is a lock held, never a pid.
- Filters and pages run on the server.

## Left to the builder

- Exact file split.
- How the per-candle state is stored (one file per room, beside the room's state).
- How the follower batches candle reads per coin-timeframe.
- How the tab hides the runner buttons for a follower room.
- How the pinned bt list is passed to the shard (a committed file read by `skill_shard.py`, or a
  workflow input; `skillbt.yml`'s input count must stay within GitHub's 10).

## Calls I made (the operator can overrule any)

1. Practice runs the backtest's own code instead of the runner.
2. The other rooms' tabs stay; only their watchers go off.
3. The bt skill's strategies are pinned to the Nov 05 list.
4. The refresh starts 00:05 UTC and the day's list applies from midnight UTC, with trades filled
   in from the candles. The alternative, refreshing before midnight and judging on data up to an
   hour short, would differ from Forecast v4's walk.
5. A trade uses the gap of the refresh that was newest when it opened.
6. The daily agreement check exists, with "same" meaning the same candles and reason, and the
   dollars shown beside it.
7. The follower holds at midnight UTC until the day's list lands, rather than trading on
   yesterday's list and taking trades back.
8. END trades never count as finished.
9. Funding is charged from the first refresh on, in the backtest and in practice alike (rule 9).
   The order-book-per-minute cost and the cost-check refusal are named as not charged.
10. The store is replaced daily, with each day's forecast and the Nov 10 store kept.
11. A delisted pinned coin is dropped and named; a failing one keeps yesterday's trades, marked
    stale.
