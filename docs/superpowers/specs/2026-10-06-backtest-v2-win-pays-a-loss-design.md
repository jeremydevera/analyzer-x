# Backtest v2 keeps only strategies whose win pays at least one loss, after fees

Date: Oct 06, 2026. Status: approved design, for the implementation plan.

## What the operator asked, in their words

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
6. Then: *"just to clarify you dont need to change the formula adjust the tp
   only"*.

The newest ask decides (CLAUDE.md, remember-my-asks): **the bare minimum is a
win that pays one loss in dollars after fees (1:1), reached by each strategy's
target, never by changing its formula.**

## What was measured before designing (Oct 06, 2026)

* Practice, all six rooms, Oct 01 – Oct 06 11:12am: average win +$0.80,
  average loss −$1.04 on $100 trades, because about $0.23 of cost comes off
  every win and goes on top of every loss; break-even 56.5% wins, got 45.6%.
* The round-trip fee the backtest charges, sampled over 983 coins' stored rows:
  median 0.218%, 10th–90th percentile 0.168%–0.508%.
* Backtest v2's grid is the full cross product of 10 stops × 11 targets per
  timeframe (`backtest_report.BARRIERS`), so **every stop is already measured
  with every target**. At a 0.22% fee, 53–83 of each timeframe's 110 pairs
  already pay at least 1:1; for every target of about 0.6% and up, a version
  that pays 1:1 exists in the grid, and the closest one pays 1.02–2.4 wins per
  loss (median about 1.1).
* Targets too small for any stop to reach 1:1 at a 0.22% fee: 15m 0.2–0.4%,
  30m 0.3–0.5%, 1h and 4h 0.4–0.6%. Their fee is larger than what is left of
  the target: TP 0.4% wins +$0.18, and even a 0.1% stop loses −$0.32.

## The rule

A Backtest v2 row is kept when

    (TP − fee) ≥ (SL + fee)        all in percent of the trade

where **fee** is that row's own measured round-trip cost — both exchange fees
plus the order book's slippage, the `rt` every row already carries (the cost the
backtest charges on every trade, `backtest_report.round_trip_cost`). Funding is
not in it: it depends on how long a trade is held and the backtest already
charges it per trade.

A row whose fee is unknown (`rt` missing and `cost_of_tp` 0 or missing) **fails**:
an unknown cost is not ok when it is money (CLAUDE.md rule 12's shape).

"Win pays" = (TP − fee) / (SL + fee). The rule is Win pays ≥ 1.

## How every stored strategy is "updated"

Each strategy keeps its signal, threshold and stop. Its target becomes the
first measured target that pays at least 1:1 for that coin's fee — that row
already exists, measured daily. Example, GPNSTOCK 15m keltner, stop 1.0%, fee
0.22%: TP 1.2% (win +$0.98, loss −$1.22) is replaced by TP 1.5% (win +$1.28,
loss −$1.22), with TP 2.0% and up kept too, since 1:1 is the bare minimum.

No new targets, no new stops, no change to any signal, and **no change to what
GitHub measures** — so it is reversible: the shards keep measuring every combo,
and only what the PC keeps changes.

## Components

1. `backtest_report.win_pays(row) -> float | None` and
   `backtest_report.pays_a_loss(row) -> bool` — the rule above, in one place.
   `store_keeps(row, running=frozenset())` gains: a Backtest v2 row (`res`
   "1m") is kept only when `pays_a_loss(row)` **or** its combination is in
   `running`. v1 rows are unchanged.
2. **The index** (`rows_index._kept`) calls `store_keeps(row)` with no running
   set, so the Stored strategies table, its CSV, its id lookup, and the rooms'
   switch-on search (which all read the index) hold only rows that pay 1:1.
3. **The pair files** (`market_sweep.save_pair_rows` and `rewrite_pair_rows`,
   the two writers every landing passes through) call `store_keeps(row,
   running=running_combos())`. `running_combos()` is every strategy-and-coin a
   room is running right now, as `(coin, tf, signal, th, sl, tp)`, read from
   each room's settings (`profiles`, `forecast_v2._settings`,
   `forecast_v2.spec_of`), cached on the settings files' change times. These
   rows stay in the pair files because the watcher's hourly switch-off check
   reads them there (`strategy_watcher._fresh_row` →
   `watcher_candidates.matched_rows`): a missing row is switched off at once,
   and the operator chose to leave the rooms as they are. They leave the file
   at the pair's next write after a room switches them off.
4. **Screen**: the Stored strategies table gains a **"win pays"** column beside
   SL%/TP%, printing `1.28 / 1.22 = 1.05` style figures as "1.05 losses", from
   the row's own `tp`, `sl` and `rt` — derived from the data it labels.
5. **CLAUDE.md**: a MANDATORY section recording the rule and the asks above.

## Data flow, and when the store becomes clean

GitHub measures as today → `cloud_sweep.land_rows` → `merge_pair_rows` →
`save_pair_rows` (rule + running set) → the v2 job files the pair into the index
(`_kept`, rule only). One UPDATE ALL BACKTESTS (v2) on both accounts lands every
pair, so every landed pair comes out clean. Pairs the run does not land (a coin
that failed or left MEXC) are cleaned by a one-time local pass that rewrites only
pairs whose index rows still fail the rule, then re-files them.

## What the rooms see

Their rules do not change. Strategies they run now keep running and keep being
judged exactly as today. New switch-ons can come only from rows that pay 1:1,
because that is all the index holds.

## Error handling

* A settings file that cannot be read makes `running_combos()` return what it
  could read and log the room it could not; it never empties the set silently
  for a room that is running strategies (a read failure keeps the previous
  cached set for that room).
* A row without a fee is not kept and is counted, never guessed.

## Testing

* The rule on real numbers: TP 1.5 / SL 1.0 / fee 0.22 kept (1.05); TP 1.2 /
  SL 1.0 / fee 0.22 not kept (0.80); TP 0.4 / SL 0.1 / fee 0.22 not kept; a row
  with no fee not kept; a v1 row untouched.
* `save_pair_rows` keeps a below-1:1 row that a room is running and drops it once
  the room switches it off; `_kept` never keeps it.
* Landing through `land_rows` with rows on both sides of the line writes only
  the kept ones, and the index files only the 1:1 ones.
* The existing guards that pin `store_keeps` in both writers and the index stay
  green (`tests/test_backtest_v2_keeps_flat_only.py`).
* The screen: the "win pays" column is computed from the row's own fields.
* After the real run: a count of index rows that fail the rule is 0.

## Out of scope

* Changing what GitHub measures, the barrier grid, or any signal.
* Room rules, watcher thresholds, real money.
* v1 (switched off since Sep 24, 2026).
