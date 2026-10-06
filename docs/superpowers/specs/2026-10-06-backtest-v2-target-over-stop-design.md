# Backtest v2 keeps only strategies whose target is bigger than their stop

Date: Oct 06, 2026. Status: approved design, for the implementation plan.

## What the operator asked, in their words, in order

1. The goal: *"since none of the the strategies are working, what i want is in
   backtest tab stored strategies, update all to have atleast 1:2 / meaning 1
   win will break even 2 loss, because currently its 1:1"*.
2. Asked whether the ratio counts prices or dollars after fees: **dollars after
   fees**.
3. Asked what happens to the strategies below the line: *"update them no need
   to hide or delete, the logic is there so just study it and find a way to
   have atlest 1:2 R"*.
4. Asked whether the rooms should change too: **Backtest tab only**.
5. Shown wider targets for 1:2: *"those are too high tp, here's the bare
   mimimum, i want 1:1 but you just have to decrease the SL a little bit
   example 1.25% TP and 1.25 SL since if you lose in sl it will add another fee
   why dont you make it 1:25TP then 1.0% sl so that its 1:1"*.
6. *"just to clarify you dont need to change the formula adjust the tp only"*.
7. On the written spec: *"take note you will only replace the ones that has
   higher sl than tp or if tp same as sl , you will change it as well example
   tp=5% sl=5% / the goal is to have higher tp than sl"*.

The newest ask decides (CLAUDE.md, remember-my-asks). **Every stored strategy
has a target bigger than its stop. A strategy whose stop is bigger than or equal
to its target is replaced by its versions with a bigger target. Strategies whose
target is already bigger are not touched. No formula changes.**

## What was measured before designing (Oct 06, 2026)

* Practice, all six rooms, Oct 01 – Oct 06 11:12am: average win +$0.80,
  average loss −$1.04 on $100 trades, because about $0.23 of fees comes off
  every win and goes on top of every loss.
* Backtest v2's grid is the full cross product of 10 stops × 11 targets per
  timeframe (`backtest_report.BARRIERS`), so every stop is already measured
  with every target, and **every stop has bigger targets in the grid**:

  | timeframe | target bigger than stop | equal | stop bigger |
  |---|---|---|---|
  | 15m | 71 of 110 | 8 | 31 |
  | 30m | 79 of 110 | 7 | 24 |
  | 1h | 71 of 110 | 6 | 33 |
  | 4h | 71 of 110 | 6 | 33 |
  | 1d | 83 of 110 | 6 | 21 |

## The rule

A Backtest v2 row (`res` "1m") is kept when **TP > SL** (strictly; TP 5% /
SL 5% is replaced). v1 rows are not touched.

## How every stored strategy is "updated"

Each strategy keeps its signal, threshold and stop. A row whose stop is bigger
than or equal to its target is replaced by the same strategy and stop with the
bigger targets — rows that already exist, measured every day. Example: 1h
stoch14 with TP 5% / SL 5% is replaced by TP 6% and TP 8% with SL 5%. A row with
TP 1.2% / SL 1.0% is already bigger, and stays exactly as it is.

No new targets, no new stops, no change to any signal, and **no change to what
GitHub measures** — so it is reversible: the shards keep measuring every combo,
and only what the PC keeps changes.

## Components

1. `backtest_report.target_over_stop(row) -> bool` — the rule, in one place.
   `store_keeps(row, running=frozenset())` gains: a Backtest v2 row is kept
   only when `target_over_stop(row)` **or** its combination is in `running`.
2. **The index** (`rows_index._kept`) calls `store_keeps(row)` with no running
   set, so the Stored strategies table, its CSV, its id lookup, and the rooms'
   switch-on search (which all read the index) hold only TP > SL rows.
3. **The pair files** (`market_sweep.save_pair_rows` and `rewrite_pair_rows`,
   the writers every landing passes through) call `store_keeps(row,
   running=running_combos())`. `running_combos()` is every strategy-and-coin a
   room is running right now, as `(coin, tf, signal, th, sl, tp)`, read from
   each room's settings (`profiles`, `forecast_v2._settings`,
   `forecast_v2.spec_of`), cached on the settings files' change times. These
   rows stay in the pair files because the watcher's hourly switch-off check
   reads them there (`strategy_watcher._fresh_row` →
   `watcher_candidates.matched_rows`): a missing row is switched off at once,
   and the operator chose to leave the rooms as they are (Main runs hand-picked
   TP = SL rows such as keltner_30m_sl2tp2). They leave the file at the pair's
   next write after a room switches them off.
4. **CLAUDE.md**: a MANDATORY section recording the rule and the asks above.

## Data flow, and when the store becomes clean

GitHub measures as today → `cloud_sweep.land_rows` → `merge_pair_rows` →
`save_pair_rows` (rule + running set) → the v2 job files the pair into the index
(`_kept`, rule only). One UPDATE ALL BACKTESTS (v2) on both accounts lands every
pair, so every landed pair comes out clean. Pairs the run does not land (a coin
that failed or left MEXC) are cleaned by a one-time local pass that rewrites only
pairs whose index rows still break the rule, then re-files them.

## What the rooms see

Their rules do not change (they already switch on only TP > SL rows; Main also
runs some it was given by hand). Strategies they run now keep running and keep
being judged exactly as today. New switch-ons come only from TP > SL rows.

## Error handling

* A room settings file that cannot be read keeps the previous cached set for
  that room and logs which room; it never empties the set silently.

## Testing

* The rule: TP 6 / SL 5 kept; TP 5 / SL 5 not kept; TP 4 / SL 5 not kept; a v1
  row untouched; the flat-only rule still applies.
* `save_pair_rows` keeps a TP ≤ SL row that a room is running and drops it once
  the room switches it off; `_kept` never keeps it.
* Landing through `land_rows` with rows on both sides writes only the kept ones.
* The existing guards that pin `store_keeps` in both writers and the index stay
  green (`tests/test_backtest_v2_keeps_flat_only.py`).
* After the real run: a count of index rows with TP ≤ SL is 0.

## Out of scope

* Changing what GitHub measures, the barrier grid, or any signal.
* Room rules, watcher thresholds, real money.
* v1 (switched off since Sep 24, 2026).
