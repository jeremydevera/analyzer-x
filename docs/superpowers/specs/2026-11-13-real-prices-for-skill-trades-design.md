# Real prices for the skill backtest and the skill rooms — design

Date: Nov 13, 2026. A project (the shared skill engine, the nightly GitHub run, the rooms' follower, the
store, two pages). Approach chosen by Claude on the operator's hand-over; awaiting approval.

## Why

The operator, Nov 13, 2026: *"for the best swittch what enhancement would you suggest? and is my logic
correct to create a room that deploys a switch? or do you recommend something else"*, then *"i switch
the model to fable 5.2 now analyze and check the best approach again use superpower"*.

Three checks were run on the store of Nov 12, 2026 7:33pm (242,283 strategies, 7.7M trades, $100 of coin
a trade) and Forecast v4's 24,480 rule sets. All read-only; scripts and outputs are in the session's
scratch folder, the numbers that matter are here.

**1. No way of choosing rule sets carries over to the next month.** Every rule set was walked over 10
months (Feb - Nov 2026) and chosen on the 3 months before each of 7 held-out months (May - Nov):

| chosen by | held-out months in profit |
|---|---|
| every month green, best worst month first (the page's order), top 10 | 2 of 5 |
| most total money, top 10 | 1 of 7 |
| most money a trade (100+ trades), top 10 | 1 of 7 |
| green and beat random picks every month | 2 of 5 |
| steadiest, top 50 | 1 of 7 |
| every eligible rule set (no choosing) | 0 of 7 |

The rank a rule set had over 3 months against its money a trade the next month: correlation between
-0.18 and +0.24, about +0.04 on average. Ranking, a "next month" check and a slower picker all stand on
this number, so none of them can find profit here.

**2. The edge before costs lives only on thin coins.** VWAP reversion, the strategy every leading rule
set switches on, makes +$0.25 (older days) and +$0.30 (unseen days) a trade before costs over all coins,
and -$0.01 / +$0.02 on coins costing $0.25 or less. An edge that exists only where the order book is
thin is the mark of a pricing error, not of a strategy.

**3. It is a pricing error: the leading rule sets lose at the real order book.** The engine gives a
trade the candle's last price plus the coin's stored gap. The app records every contract's real order
book 3 seconds into every minute (`app_books`, since Oct 16, 2026). Every trade the rooms' five rule
sets took from Oct 17 to Nov 12, 2026 that has a recorded book at its own minute (707), priced both ways:

| rule set | trades | as the backtest measured | at the real book of the same minute |
|---|---|---|---|
| #KK9SRY28 | 305 | +$92 (+$0.30 a trade) | -$488 (-$1.60) |
| #CKVS7G7Z | 477 | +$123 (+$0.26) | -$940 (-$1.97) |
| #RSS7CUKH | 144 | +$58 (+$0.40) | -$245 (-$1.70) |
| #7T3VJU82 | 135 | +$8 (+$0.06) | -$233 (-$1.73) |
| #D7EN8BNV | 67 | -$2 (-$0.03) | -$102 (-$1.52) |
| any of the five | 707 | +$131 (+$0.19) | -$1,125 (-$1.59) |

Where the $1.78 a trade goes, on average: at entry the real middle price is $0.47 worse than the candle's
last price and that minute's real one-side cost is $0.57 above the stored gap; a signal exit loses $0.42
and $0.56 the same way. Over all 112,779 priced trades on the same coin-timeframes the price error is
about zero for a random trade (-$0.02) and positive only for the reversion families (VWAP reversion
+$0.22 at entry, mean reversion +$0.36, Bollinger +$0.25): they buy when the last print was a seller
hitting the bid, and that price cannot be bought. The win-rate rules then pick exactly the strategies
and coins where this flatters most (VWAP reversion on coins costing over $1: measured +$0.61 a trade,
real -$4.54).

**Practice has the same error**, because a skill room is the backtest's engine stepping in real time,
not a fill against the book. Its 20 closed practice trades with a recorded book (Nov 10 - 13, 2026):
practice says -$4.99, the real book -$12.20. #7T3VJU82 CATL, Nov 11, 2026 7:00am: practice bought at
49.34 and booked +$1.26; the book showed bid 48.97 / ask 49.23 and $100 would have filled at 49.88:
-$0.34. On liquid coins the two agree to cents (SOL, WLD, WLFI, ASTER).

So the operator's logic - a room that follows one switch-on rule - is sound. What is wrong is the price
the test and the practice both use; every "best switch" found so far was chosen by that error.

## Approaches

1. **Real prices first (PICKED).** The skill backtest and the skill rooms price every entry and exit
   from the recorded order book of its own minute, by one function. Rankings, the picker and practice
   then mean what real money would have made. Trade-off: the truthful answer will probably be that
   today's leading rule sets lose; a medium build across the engine, the nightly run and the follower.
2. Keep the prices, improve the choosing (luck test first, a "next month" check, a slower picker) -
   Claude's suggestion before these checks. Check 1 shows no choosing carries over and check 3 shows the
   leaders lead because of the price error: this would polish a ranking of that error.
3. Stop the skill rooms and move the room idea to the forward-tested v3 group, which already pays the
   real book and waits with post-only orders. It is already followed by itself (`v3_forward`, since
   Nov 05, 2026: 74 closed trades -$64.63, 87 still open +$160.26 - too early to judge) and the runner
   cannot trade v3's waiting orders or trailing stops, so there is nothing to build now.

Picked: 1, with 3 left running as it is. Until prices are real no choice between rule sets can be
trusted, and practice cannot answer the operator's own goal (*"my goal is to align it with practice so I
know exactly how much will i earn"*).

## Goals

* Every skill trade's entry and exit is priced from the recorded book of its own minute wherever a
  reading exists - in the nightly backtest and in the rooms' practice, by ONE function.
* Every figure built on those trades says what share of them paid a real price and what share an
  estimate; an estimated trade is never dropped and never passed off as real.
* Forecast v4 shows each rule set's result over its real-priced trades, and can be sorted and filtered
  by it.
* A room's practice trade and tomorrow's backtest of the same trade agree to the cent.

## Non-goals

* No change to any signal, stop, target, window, rule set, picker test or room. Nothing is switched.
* No order is placed; no real-money path.
* The runner's entry checks (cost check, "the price ran away", closed market) are NOT added to the
  skill engine in this cut: they decide which trades exist, and most skill strategies have no target to
  judge a cost against. Named on the pages as not charged, as today. The cheap-coins rule sets stay the
  coarse guard.
* No re-pricing of days before the record (Oct 17, 2026): older trades keep the estimate.
* The rule sets do not yet count only real-priced trades (decided after a week of real numbers).

## Anti-goals

* Two pricing rules, one in the backtest and one in the follower, that can drift apart.
* A "real prices" figure that quietly includes estimated trades.
* A trade left out because its minute has no reading.

## Constraints

* **The readings: the app's OWN only.** A real price is a reading the app itself recorded
  (`app_books`, source "app", 3 s into the minute), read through the functions this PC and GitHub's
  machines already share. The exchange's own published books are NOT a real price: they hold offers the
  app cannot take (QNTX matched 0 of 45, RCA-2026-10-16-A), the outside check above used none of them
  and the follower never has them. They keep their one job, the usual gap. So real prices begin Oct 17,
  2026, the first whole day the app recorded, and cannot reach further back. A reading counts only for
  its own minute (`book_history.book_age_s` at most 59 s) and only when its $100 walk did not run out
  (`exhausted`).
* **Readings exist only while this PC records.** The recorder runs on this PC: BTC holds 53 of 1,440
  minutes on Nov 01, 2026, none on Nov 02 and 89 on Nov 10, and the outside check found no reading for
  25,630 of 138,409 trades (19%). Those fills stay estimates, and every page says the share.
* **The window is the stretch the minutes are read.** The engine already reads each coin's minutes for
  the `MINUTE_DAYS` = 120 days before the run's UTC midnight, and a candle older than that is settled
  the old way - an edge the store already has. Real prices use the same stretch: every recorded day
  since Oct 17, 2026 inside it. Nothing recorded falls out before Feb 2027, and when it does it is the
  minutes' own edge, not a second one. The nightly run loads those days' readings for each coin (today
  27 days, growing to 120); the follower's warm-up reads the same stretch.
* **One reading, both sides.** A finished UTC day's recordings are published at 00:20 UTC
  (`app_books.PUBLISH_AFTER_UTC_S`); the nightly chain starts at 00:05 UTC (`v4_daily.DUE_AFTER_S`). The
  follower reads this PC's own recording file. For the two to price a trade from the same reading the
  nightly run must not start measuring before the day it measures is published.
* A day's room list is written once; the store is replaced nightly; the follower's record is
  append-only.
* The store's row for a strategy keeps `fee` and `slip` (the usual gap): the cheap-coins rule sets and
  the estimate both read them.

## The design

**The price rule** (one function beside `skill_bt.step`, used by the backtest, the nightly shard and the
follower): a fill at minute `t` that BUYS (a long's entry, a short's exit) pays `mid x (1 + buy)` and one
that SELLS pays `mid x (1 - sell)`, where `mid` is the middle of the reading's best bid and ask and
`buy` / `sell` its own $100 walk - what $100 really gets from that book, thin books included. For an
entry and for an exit on the opposite signal, `t` is the candle's close and the reading replaces "the
candle's last price plus the gap" whole. For a stop or target settled by the minute, the price stays
the barrier and only the cost changes: the barrier price worsened by that minute's own walk instead of
the usual gap. No usable reading at `t`: the rule of today (last price or barrier, worsened by the usual
gap), and that side of the trade is ESTIMATED.

**A stop and a target are measured from the price really paid**, as a real order's are and as the engine
already does (`pos["px"]`): with a real entry price they sit where a real bracket would sit. So this
changes some trades, not only their dollars - #7T3VJU82's CATL buy at 49.88 with a 1.5% stop is stopped
in its first minute (the stop, 49.13, is above the 49.10 middle), which is what a real $100 market buy
on that book would have met.

**Each trade says how it was priced**: 2, 1 or 0 of its two fills at a real reading. The store keeps
it per trade, each strategy row counts its real-priced trades, and `meta` holds the share over the last
30 days and over everything.

**The nightly run** (`skill_shard`, `skill_bt.daily_line` / `measure`): loads the coin's readings once
(the load it already makes for the usual gap), hands them to the engine, and writes each trade's
pricing mark. Before it measures a day it waits for that day's recordings to be published (bounded: 30
minutes past 00:20 UTC); if they are not, it goes on, prices the unpublished hours by the estimate and
says so by name in the day's status - the next night re-prices them.

**Fills at the 00:00 UTC close are real one night late.** Their reading (00:00:03) is in the NEW day's
recording, which first goes up at 01:10 UTC, after the run has read. So every daily-candle fill, one in
six on 4-hour candles and each day's last candle are estimates on their first night and real from the
second (the store is rebuilt every night). The run is not moved later for this: the rooms' lists would
land an hour later every day.

**The follower** (`v4_follow`): prices each fill with the same function from this PC's recording of
that minute. It waits for the reading the way it already waits for a candle's last minute
(`FINE_WAIT_S`, 10 minutes; the recorder writes every 5); none by then: the estimate, written on the
row and counted on the room. The row's entry and exit prices are the real ones, so every panel shows
them. A trade already open when this ships keeps the way it was entered.

**Forecast v4**: nothing in the walk changes - it reads the store's dollars, which are now real for the
last 30 days. The rule sets themselves therefore start judging strategies on real wins. Each rule set
also gets its result over real-priced trades alone (trades, wins, profit, profit a trade), shown as a
column, sortable, with a "made money at real prices" filter. The default order of the list is not
changed in this cut (Claude's call: the operator decides once they have seen the column).

**The choosers read mixed dollars, and the page says so.** The rule sets' own test, the list's order
and the picker are not changed, so they read real dollars where a fill was recorded and the estimate
where it was not (everything before Oct 17, 2026, and about a fifth of the trades since) - and the
estimate is what flattered the leaders. The real-priced column is the truthful figure. Whether a rule
set should count only real-priced trades is decided after the first week of real numbers, not guessed
now. Until three whole months are recorded (Feb 2027) the list's "worst whole month" order still rests
partly on estimates.

**The picker keeps acting.** On the first night it will very likely switch the last room off too
(#D7EN8BNV follows #KK9SRY28: -$488 over 305 trades at the real book). A room with no tab is the
truthful state until a rule set makes money at real prices; the bell and the picker's line say why.

**The pages say it**: Backtest v4's header prints the share of the last 30 days' trades that paid the
real book and that older trades pay the coin's usual gap; a strategy's trade list marks each trade
real / part / estimated; a room's line counts its estimated fills.

**The daily agreement check** keeps its form (same strategy, side, entry candle, exit candle, reason)
and expects the dollars to match to the cent whenever both sides read the same reading. A day is checked
again the following night for the trades whose midnight fills were still estimates on the first.

## Calls made by Claude (not the operator's words)

* The $100 walk of each side, not the best bid/ask alone: on a thin book the best price holds less than
  $100 (CATL above: ask 49.23, $100 fills at 49.88).
* Stops and targets keep their barrier price and pay that minute's real cost; only close-priced fills
  take the book's price whole.
* Only the app's own readings are a real price; the exchange's published books are not.
* Real prices over the stretch the minutes are read (120 days), from Oct 17, 2026; everything else stays
  estimated and marked.
* A stop and a target are measured from the price really paid, so some trades end differently.
* Midnight fills are real one night late; the run is not moved.
* The rule sets, the list's order and the picker are left as they are; the picker is not paused.
* The entry checks are left out of this cut (see Non-goals).

## Left to the builder

Function and column names; how the pricing mark is stored and migrated; how the shard waits for the
published day; fixtures and tests; where each page prints its line.

## How it is judged

* A test on a fixture: with a recorded reading at a fill's minute the engine's fill IS that reading's
  $100 price (the -$1.78 a trade the outside check found is 0 by construction), the stop is measured
  from it, and with no reading the trade is priced as today and marked estimated.
* The follower and the backtest, given the same candles and the same readings, write the same trade to
  the cent (one function, proved by replaying a day).
* The first night after it ships, the outside check is run again over the real-priced fills of the
  store: the price the store used against the recorded reading, difference 0; and whatever practice
  trades the rooms closed match their backtest rows to the cent.
* Expected and wanted: the leading rule sets fall, and VWAP reversion on thin coins stops winning 80%
  of its trades on paper. If any rule set still makes money on real-priced trades, that is the first
  one worth a room.
