# Forecast v2

*Auto Trade → Forecast v2 (`/forecast-v2`), built Oct 01, 2026. The first
Forecast page (`/forecast`, room cards and saved forecasts) is unchanged.*

## What the operator asked for

In their words, in the order they arrived (docs/OPERATOR-ASKS.md):

> when i say forecast, i mean you should be predicting what's the best
> combination of criteria to be using for deployed rooms, based on overall
> backtest results

> i want prediction like for example, you are seeing a coin is winning 9
> streak then inform me that specific coin i want it in a Streak section /
> then predict what combination of room will be effective, for example: 90%
> winrate with 40trade, tp is greater than SL will have profit of x this month

> okay run that prompt and create Forecast v2, use harddev skill and make
> sure to document this

The prompt itself grew over three rounds of "what else do you suggest" and is
kept below, word for word, as **The build prompt**.

## What the page shows

| section | what it answers | where the numbers come from |
|---|---|---|
| A. Streaks | which coins are on a run of wins (or losses) right now, and what happened after past runs that long | practice: each room's trade record; backtest: every strategy in the newest replay |
| B. Coins to avoid | which coins lose in every room | practice, all rooms together; the same strategies' backtest beside it |
| C. Where the money goes | costs, win size against loss size, timeframe, signal family, stocks or crypto, the hour a trade opened, fast stop-outs, the worst day, one coin in many rooms | practice beside the rooms' own rules replayed |
| D. Best room rules this month | which rule set should make the most this month, both as the backtest says it and after the reality check | the forecast research on GitHub, walked forward month by month |
| E. Daily summary | one bell message a day | the daily chain |

Everything is a NOTE. Nothing on this page switches a room on or off, changes
a watcher rule or touches real money.

## How it works

```
 ┌──────────────────────────────────────────────────────────────┐
 │ 1. PRACTICE HALF (live, every 30 s, in its own API thread)    │
 │    tradingagents/forecast_v2.py  live()                      │
 │    each room: trade record · open trades · watcher_slots ·    │
 │    deployments.jsonl · rolling30's rebuilt backtest trades    │
 └──────────────────────────────┬───────────────────────────────┘
                                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 2. DAILY CHAIN (forecast_v2_daily.tick, its own API thread)   │
 │    due once the day's GitHub backtest update is on this PC    │
 │    (the same test as the first Forecast's automatic one)      │
 └──────────────────────────────┬───────────────────────────────┘
                                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 3. REPLAY on GitHub (replay.yml) on BOTH accounts, ~1 hour:   │
 │    the market's ~1,100 coins dealt round robin between them,  │
 │    20 machines each = 40 (CLAUDE.md, "Every GitHub job uses   │
 │    ALL 40 machines") · every strategy that could pass the     │
 │    loosest rule set: wr=70, trades=20, tp=any, windows 15|30, │
 │    from the 1st of the month three months back · each machine │
 │    also uploads replay-report-<N> (a few KB) for the end      │
 └──────────────────────────────┬───────────────────────────────┘
                                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 4. FORECAST base (forecast.yml → forecast_shard.py), each     │
 │    account on ITS OWN replay run (a run reads its own repo)   │
 │    576 base rule sets + the rooms' own rules, 100 random      │
 │    picks each, every strategy's streak at the end, the rooms' │
 │    rules split "where the money goes" · measured 260-639 s    │
 │    a machine, ~15 min a run                                   │
 └──────────────────────────────┬───────────────────────────────┘
                                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 5. MERGE base (its OWN PROCESS: forecast_v2_merge) over every │
 │    account's machines (account i's machine k = i*100 + k)     │
 │    → pick the 20 best base sets + the rooms' rules            │
 └──────────────────────────────┬───────────────────────────────┘
                                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 6. FORECAST options: 22 options, ONE AT A TIME, on those sets │
 └──────────────────────────────┬───────────────────────────────┘
                                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 7. MERGE all → ~/.tradingagents/forecast_v2/latest.json,      │
 │    streaks.npz, predictions.jsonl (the month's FIRST one)     │
 │    → ONE bell message                                         │
 └──────────────────────────────────────────────────────────────┘

 IF ANYTHING FAILS: the step is named in state.json and on the page
 ("the base step failed at Oct 02, 2026 3:10pm — tried again after 30
 minutes: …") and tried again after RETRY_S; a step that then gets through
 clears it. A run red on SOME machines is used and says so ("PART OF THE
 MARKET … N of 40 machines", "used without: …"), both stages merged over
 the machines they share. An account that refuses a dispatch, or whose run
 is red on EVERY machine twice, is dropped and named, and the other account
 goes on. A run red on EVERY machine is started again once (that account
 alone); when no account is left the day is given up by name and the next
 daily update starts fresh —
 the last finished data stays on the page. A dispatch is saved before it is
 made, so a retry adopts the run GitHub took instead of starting a second.
 GitHub is asked at most every POLL_S. A failed practice refresh keeps
 serving the last good copy and says so. Nothing runs under pytest against
 the real files.
```

The page answers in well under 2 seconds from the copy and the saved files;
no request ever replays a trade.

## The definitions (one place: `tradingagents/forecast_v2.py`)

* **a win** = profit after all costs > 0. A $0.00 trade is a loss.
* **a winning streak** = wins in a row ending with the most recent closed
  trade; **a losing streak** the opposite. Practice: per room and coin (every
  strategy of that coin in that room, by exit time). Backtest: per stored
  combination (coin + timeframe + signal + TP + SL, with its #ID).
* **what followed** a streak of length k: across every strategy in the
  replay, every time a run reached k or more, how often the next trade won and
  what the next 10 trades made. Under 30 past cases the page says "not enough
  past streaks to tell".
* **break-even win rate** of a strategy = (SL + cost) / (TP + SL), in percent
  of the trade's size (a win pays TP less the cost, a loss costs SL plus the
  cost). Of a rule set: average loss / (average win + average loss) over its
  own trades.
* **a coin to avoid** = lost money over at least 5 practice trades, all rooms
  together.
* **a finding resting on fewer than 30 trades** is marked "too few trades to
  mean anything".

### The reality check

The same rows over the same hours. For every stretch a row was switched on in
a room (deployments.jsonl, `watcher_slots`), up to the end of its rebuilt
backtest (rolling30's cache), the backtest's trades that OPENED in it against
the practice trades that opened in it. The backtest side keeps the runner's
own 4 open trades per coin, first come, first served — exactly
`watcher_replay.cap_per_coin`, the rule the research applies too.

Two numbers come out:

* **took** — of the trades the backtest made, the share practice also made;
* **gap** — on the trades it did make, how much less practice made per trade
  than the backtest's average per trade.

A prediction of P over T trades becomes **took × (P − gap × T)**. It is exact
on the window it was measured on: each room's own backtest numbers there come
back as its practice result (#4FC03172: backtest +234.52 over 2,259 trades →
−7.87, its practice −7.87).

Measured Oct 01, 2026 6:10pm over 6,178 rows: practice took **803 of 4,463**
backtest trades (**18.0%**) and made **0.22 less** on each (backtest +0.03 a
trade, practice −0.19). So the September research's +4,967.44 for
#4FC03172's rules becomes about **+279** — and the room's own practice was
−172.73 by then.

### Beat random

For every rule set, 100 draws in which each switched-on strategy is swapped
for a random strategy of the same shape that was trading at the same check,
over the same on/off stretch. Compared **per trade, never in total**: the
random picks are not held to the runner's per-coin limit or the loss limit,
so they make more trades, and against a losing market more trades is a
bigger total loss — on 20,000 strategies of shard 0 the totals said three
rule sets beat random 100, 97 and 92 times in 100 when per trade they lost
to it (−0.234 against −0.143). Under 80 in 100 the page says "could be luck".

### The prediction for this month

Each rule set is walked forward day by day with `watcher_research.raw_fast`
(the rooms' raw rules): at each local midnight a strategy is switched on only
from the trades that closed before it. Its month is what its switched-on
strategies made in that month after fees, spread and funding, at $5 × 20x.

* **this month** = the typical complete past month (median), with the range
  (worst and best month), how many months it rests on, and the same after the
  reality check. Under 3 past months it is labelled "thin".
* A month is complete when the data reaches its last day.
* Ranked by the **worst past month after the reality check**, then the
  typical one (the still-working rule) — never by the best.
* **Money needed** = the most trades open at once × $5.

### The month so far (the tracker and its bell)

Each room's practice month so far is held against **what its own rule set
made by the END of the same day of each past month** in the backtest
(`forecast_v2_merge.by_day`, kept for the rooms' own rule sets), straight and
after the reality check. Day 31 of a 30-day month is that whole month. The
bell rings once a room a month, when the room falls under the worst of those.

Never a month's range divided by its days — the first build did that, and its
"worst case by today" was a number no past month produced (RCA-2026-10-01-J).
Measured Oct 01, 2026, the two part as the month goes on:

| room's rules | day 1: divided / measured | day 20: divided / measured |
|---|---|---|
| #4FC03172 (#562C0147) | −0.90 / −2.39 | −18.04 / −47.02 |
| #CC94D9FB (#C2B0F302) | +0.87 / +0.00 | +17.30 / −0.47 |
| #B2404C0B (#95E851AB) | +0.74 / +0.00 | +14.75 / −0.39 |

On Oct 01, 2026 all six rooms were under the measured day-1 floor too
(#4FC03172 −169.11 over 576 practice trades against −2.39), so the six bells
that rang at 7:25pm were right; the numbers printed in them were not.

### The bells

* **A practice streak**: every run that first reaches 9 wins or 5 losses in a
  row is named ONCE, in at most one bell an hour — 46 runs reached the line on
  Oct 01, 2026 (4 winning, 42 losing, 25 of them in #4FC03172), which as one
  bell each would bury every other message. A room that is off (no tab) never
  rings. The first run only remembers the runs already going.
* **A room under its worst case**: once a room a month (above).
* **The daily summary**: one message when the day's Forecast v2 is made.

### The rule sets (`tradingagents/forecast_rules.py`)

* **Base grid**, every combination: judged on 15 or 30 days × switch on/off
  at 70, 75, 80, 85, 90 or 95% × 20, 30, 40 or 50 trades × TP wider than SL,
  at least 1.5× SL, at least 2× SL, or any × stop 1%, 1.5% or 2% or tighter
  = **576**.
* **Options**, each tested one at a time on the 20 best base sets and the
  rooms' own rules: the coins to avoid skipped · Japanese stocks skipped ·
  stocks only while their own market is open · cost at most 5, 10 or 15% of
  the target · one timeframe only (each in turn) · the 5 worst signal families
  skipped · crypto only · stocks only · no new trades from 9am to noon New
  York · no new trades that day after losing 10, 20 or 40 (the account loss
  cap's own rule, realized only) · no stop smaller than the coin's normal
  15-minute move (its median 15-minute high−low over 30 days) · at most 1, 2
  or 3 trades per coin.
* **Ids** are hashed from the rule set's own values (`forecast_rules.rule_id`),
  e.g. #11823416, so "deploy #11823416" names one exact rule set.
* **Can a room run it today?** Only base sets with TP wider than SL or any:
  the watcher has no 1.5× or 2× rule, and no option is a switch a room has
  (`forecast_rules.deployable`).

## Data limits, said out loud

* **What a replay covers changes as the store grows.** The daily replay
  writes every strategy that could pass the loosest rule set in the grid
  (70% wins, 20 trades, any TP, judged on 15 or 30 days) over every signal
  group and listed coin of that day. Oct 01, 2026: 4 signal groups (classic,
  preset, sep25, sep27ml), 1,092 coins, 695,845 strategies. The first data,
  a research replay, covered 2 groups, 1,079 coins and 4,585,414 strategies
  under a looser rule (50% / 10 trades, TP wider than SL only) — so the same
  rule set's past months differ between them (#562C0147: July 1,703 trades
  on the first, 2,098 on Oct 01's). Every kept prediction carries what it
  covered, and a grade over other strategies says so.
* The replay settles every exit by the **bar rule** (MEXC sells about 30 days
  of 1-minute candles, so July and August cannot be settled minute by minute).
* The first data (replay 36763426504) holds only strategies with **TP wider
  than SL**, so "any TP" there is the same as "TP wider than SL" — the page
  says so. The daily chain's replays write every shape (`tp=any`).
* The replay only writes strategies whose cost is **under 20% of the
  target** (its own gate), so the cost options are 5, 10 and 15%.
* **Rooms per coin** is about running several rooms at once; a rule set is
  one room, so it is shown as section C's overlap warning instead.
* Market hours: holidays are not taken out; lunch breaks count as open.
* The reality check covers only rows switched on before their rebuilt
  backtest ends — on Oct 01, 2026, #4FC03172, #CC94D9FB, Main and the three
  retired rooms; the three 15-day rooms join after the next daily update.

## First results (Oct 01, 2026)

* Replay 36763426504: **4,585,414 strategies, 731,552,633 trades**, Jul 01 to
  Sep 30, 2026 12:00pm. Base run 36936689969: 576 rule sets, all 20 machines
  green; merged in 86-128 s; 189 MB downloaded in 28 s. Options run
  36938530506: 572 more, all 20 machines green; both merged in 111-120 s.
* Best of **1,148**: **#A8CD8C72** "70% wins, 50+ trades in 30 days, TP at
  least 1.5x SL, stop 1% or tighter, no stop smaller than the coin's normal
  15-minute move" — Jul +341.68, Aug +1,018.99, Sep +2,972.52 in the backtest;
  about **+92.17 a month after the reality check** (+47.98 to +281.70); beat
  random 100 in 100; won 68.04% against a 47.1% break-even; needs $240. Needs
  a new switch before a room can run it.
* Best base set: **#11823416** (the same without the option) ranks 8: about
  +68.43 after the reality check (+43.59 to +258.45), needs $265.
* The rooms' own rules after the reality check: #CC94D9FB's (#C2B0F302) rank
  272, about +118.52 (+26.82 to +223.56); #4FC03172's (#562C0147) rank 1,023,
  about −6.04 (−27.96 to +258.22).
* **Checked by hand** (Oct 01, 2026 7:32pm): August re-run on replay shard 0
  with the research's ORIGINAL path, `watcher_replay.simulate`, against what
  GitHub's machine 0 reported — #562C0147 158 trades, 70 won, −32.20 both
  ways; #C2B0F302 22, 13, +1.11 both ways. **On Windows, never set
  `TZ=America/New_York` for a check**: the C runtime does not read that
  name, so its midnights are not New York's (`datetime(2026, 7, 1)` gave
  1782860400 instead of 1782878400) and the first re-run disagreed, 168
  trades against 158. This PC's own clock is New York's; GitHub's Linux
  machines read the TZ variable correctly.
* Streaks: **689,474** strategies on a run of 5+ (33,050 winning, 656,424
  losing). VUG 15m prank won 25 in a row to Sep 30 (switched on in
  #4FC03172, #6B08FF64 and #CC94D9FB); after runs that long the next trade
  won 89.2% of 6,382 times. LUNRSTOCK lost 102 in a row.

## The first automatic day (Oct 01, 2026)

The chain ran by itself after the site restarted at 7:25pm, every step on
GitHub with all 20 machines green and none missing:

| step | run | when |
|---|---|---|
| replay (70% / 20 trades / any TP, from Jul 01) | 36940719775 | 7:25pm → ~8:31pm |
| base (576 rule sets + the rooms' rules) | 36946533025 | 8:32pm (queued behind the what-if) → ~8:37pm; merged 8:39-8:45pm |
| options (22 options on the 20 best + rooms) | 36947539505 | 8:45pm → merged, made 8:54pm |

* Data to `Oct 01, 2026 4:00pm`: 695,845 strategies, 162,910,671 trades;
  1,148 rule sets; reality check took 0.1799, gap 0.2225 (803 of 4,463).
* Best by the worst month after the reality check: **#A2C81BF9** "75% wins,
  20+ trades in 30 days, TP at least 2x SL, stop 2% or tighter, cost at most
  15% of the target" — about +63.61 a month (+59.44 to +181.15), beat random
  100 in 100, needs $205; needs a new switch before a room can run it.
* Best a room can run today: **#CFABDC2A** "90% wins, 30+ trades in 30 days,
  any TP, stop 1.5% or tighter" (rank 119) — about +105.84 a month (+41.27 to
  +168.79), needs $105.
* The what-if **#2F39EAEC** (asked 7:26pm, measured on the Sep 30 data): "85%
  wins, 30+ trades in 30 days, TP wider than SL, stop 2% or tighter" — about
  +98.04 a month (+21.02 to +115.57), beat random 100 in 100, needs $120, a
  room can run it today.
* The daily summary rang at 8:54pm (KIMISTOCK won 16 in a row in #CC94D9FB;
  DHRSTOCK lost 13 in a row in #4FC03172; IGV −50.87 over 47 trades; every
  room under what its rules made by day 1 except #6B08FF64).
* Streaks in the replay: 68,805 strategies on a run of 5+ (51,466 winning,
  17,339 losing) — fewer than the first data's 689,474 because the replay
  holds only strategies that can pass 70%.

## Files

| file | what |
|---|---|
| `tradingagents/forecast_v2.py` | the practice half and every definition |
| `tradingagents/forecast_rules.py` | the grid, options, ids, words, filters, loss limit |
| `.github/scripts/forecast_shard.py` | one machine's share of the research |
| `.github/workflows/forecast.yml` | the research run (ten inputs — the most a dispatch may carry) |
| `.github/workflows/replay.yml` | the replay, now also uploading `replay-report-<N>` |
| `tradingagents/forecast_v2_merge.py` | the machines added together, scored, saved |
| `tradingagents/forecast_v2_daily.py` | the daily chain and the what-if box |
| `tradingagents/forecast_v2_api.py` | the page's answers, filtered and paged |
| `webapp/src/components/forecast/ForecastV2.tsx` | the page |
| `tests/test_forecast_v2.py` | the guards, on one timeline |

On disk, beside the store (G:): `~/.tradingagents/forecast_v2/` — `latest.json`,
`streaks.npz`, `predictions.jsonl`, `state.json`, `switch.json` (the on/off
box, written by nothing else), `whatif.json`, `alarms.json`,
`streak_bells.json`, `merge.log`, `runs/<id>/` (the last 3 downloads).

## Running it by hand

```
python -m tradingagents.forecast_v2_merge <base dir> [<options dir>] [--runs JSON] [--keep]
gh workflow run forecast.yml --repo jeremydevera/analyzer-x -f source_run=<replay run> \
  -f end_ms=<common end> -f start=2026-07-01 -f stage=base -f rooms="<ID=w:on:off:trades:tp:cap;...>" \
  -f avoid=<coins> -f families=<families>
```

The page's "run it every day" box switches the chain off and on
(`POST /api/forecast-v2/switch`); off stops it dispatching and nothing else.

For NEW winning room strategies — prompt 3's every-shape search (7, 15 or 30
days, 40-95% wins, 1-50 trades, every target-vs-stop shape, stop and target
caps, this page's 22 options) — paste prompt 4 of `docs/FORECAST-PROMPTS.md`
(Auto Trade → Forecast shows it with a copy button, under Forecast v2 since the Oct 02, 2026 merge). Every winner becomes a row
of this page's rule-set table, never deleted, and each run tries combinations
no run tried before. The same prompt turns that section from "Best room rules
this month" into "Best room rules" with FROM and TO dates, every number
re-measured over exactly the chosen dates (operator, Oct 02, 2026: *"i want it
to be flexible where i can select a between date range instead of hard cap 1
month only"*). It needs prompt 3's loose replay
(`wr=40,trades=1,tp=any,windows=7|15|30`): the daily replay here is written at
70% / 20 trades, so it can keep only the winners at or above that line current
every day.

## Bug hunt (harddev) rounds

1. **Reality check without the per-coin cap**: the backtest side "made" 7,470
   trades in fourteen hours on #4FC03172 against practice's 138 (1.8%) —
   mostly the 4-a-coin rule, which the research already applies. Capped like
   the research.
2. **One correction number** ("dollars short per backtest trade") could not
   tell a rule set practice barely trades from one it trades badly; it became
   two (took, gap).
3. **Beat random in total** let the per-coin cap win the comparison
   (100/97/92 against per-trade 6/1/0). Per trade now — found before the first
   fleet run, which was cancelled while queued (36936402244).
4. **A Flat array built from a list of arrays** failed on the PC at 257 MB with
   5.6 GB free; one allocation each now.
5. **Streak rows as text** were 287 MB on disk and would have been over a
   gigabyte as dicts in the API; columns with coded names, 12.6 MB.
6. **The chain inside the supervisor loop**: downloads and an 86-128 s merge
   would have held the loop that restarts crashed runners. Its own thread; the
   merge its own process.
7. **The reality box** showed live numbers next to a table corrected with the
   merge-time ones; it shows those, and says when the live ones differ.
8. **3,868 file stats every refresh** (the queue that made /api/health take
   60 s); one folder stamp now.
9. **The month's graded prediction** was kept by the base-only merge; only the
   final merge keeps it. (The line it had already written stayed until round
   6 — RCA-2026-10-01-K.)

Round 3 (before the site ran the chain):

10. **A dispatch took "the newest run"** as its own; the other session
    dispatches replay.yml too. Both workflows carry a `run-name`, and the
    chain finds its run by that title.
11. **A run with some machines red** raised and was retried for ever; it is
    used when any machine is green, the missing ones named.
12. **The what-if button waited for GitHub** inside the request (up to a
    minute); it answers "starting" at once and dispatches behind the answer.
13. **The month alarm ran in the supervisor loop**; it rides the chain's
    thread, only once a practice copy exists.
14. **A new practice streak rang nothing**; it rings (round 6 made it at most
    one bell an hour), and the first run only remembers the runs going.

Round 4: 15. **A what-if asked while a replay ran** would have been sent to a
replay whose artifacts did not exist yet; the chain keeps `ready`, the last
FINISHED data, and the what-if box reads only that.

Round 5 (the Playwright passes, Oct 01, 2026 7:26pm and 7:35pm):

16. **1,590px wide at 1,440** and **489px at 390**: cards and grid children
    kept their content's width; every card and grid child may shrink
    (`min-w-0`) and a wide table scrolls in its own box.
17. **A 4,848px rules card**: the words column keeps 300-460px.
18. **The worst day printed "2026-10-01"**; it prints through fmtWhen.

Round 6 (Oct 01, 2026 7:40pm-8:10pm, the chain's first night):

19. **"By today" was a month divided by its days** — RCA-2026-10-01-J.
20. **October's prediction held 576 of 1,148 rule sets** — RCA-2026-10-01-K;
    replaced from the same data, the old file kept as
    `predictions.jsonl.before-repair`.
21. **A queued run read "working on GitHub: 0 of 0 machines done"**: the
    what-if #2F39EAEC, asked 7:26pm, sat QUEUED behind the daily replay's 20
    machines. A run GitHub has not started says "waiting in GitHub's queue
    since …"; the page prints the server's words, never "about 10-15
    minutes".
22. **"Off" could come back "on"**: the tick wrote back a state it read
    before a two-minute merge. The box has its own file.
23. **A what-if asked during another's download vanished** from the file the
    poll saved whole; every save is one record over a fresh read, under one
    lock.
24. **A slow listing could start a second replay**: a dispatch that raised
    because GitHub listed its run late was retried 30 minutes later as a new
    one. A retry adopts the run made since the first try; a GitHub-cut title
    still matches on its first 60 characters.
25. **A what-if cut off by a restart stayed "starting" for ever**, and asking
    again returned that answer; it is marked so it can be asked again, and the
    re-ask adopts any run the cut-off start made.
26. **"One a day" counted the day a chain FINISHED**, so a chain done after
    midnight held the next day's update back until the following midnight;
    it counts the day it started.
27. **A what-if was corrected with the live numbers**, the table with the
    merge-time ones; both use the table's.
28. **46 streak bells in a day** (Oct 01, 2026) — at most one an hour, every
    new run named once, none for a room that is off.
29. **A missing key could stop a finished day reaching "done"**, re-running
    the merge every 30 minutes; it reads with `.get`.

Round 7 (by 8:22pm, against the build prompt's section E word for word):

30. **The daily bell had no rooms**: section E asks for "each room's month so
    far against its predicted range" and the bell's own docstring promised
    it. Now in the prompt's order — longest winning run, longest losing run,
    worst coin, each room against what its rules made by the same day — then
    the best rule set.
31. **A long bell lost its count**: `notifications.record` keeps 500
    characters, so "and 34 more on the Forecast v2 page" was cut first.
    `forecast_v2_daily.fit` leaves a part out whole and counts it.
32. **"working — waiting in GitHub's queue … not started yet"**: a run with
    an id prints only its own words.

Round 8 (by 8:22pm, Windows): 33. **Every Forecast v2 file was one bare
`os.replace`**, and the page reads them every 30 s; `forecast_v2.publish` /
`replace_retry` give each save db_jobs' 3-second budget (RCA-2026-09-18-B),
and a dispatch's attempt is on disk BEFORE the dispatch, so a lost save can
never start the same run twice.

Round 9 found nothing new in rounds 7-8's code: the readers of every file
whose shape changed (`switch.json`, `latest.json`'s `by_day`,
`streak_bells.json`, `whatif.json`'s `tried_at`) and tonight's first
automatic replay → base step (run 36940719775 was dispatched from
cdd516295e46, whose replay.yml uploads `replay-report-<N>`) checked clean.

Round 10 (8:26pm, reading the files the restarted site wrote): 34. **An
"off" saved in `state.json` before the box got its own file** would have
come back "on" at the first save — on another machine after `git pull`.
This PC's chain was on; the old value is carried over now.

Round 11 (8:27pm, the page's own words): 35. the streaks card still said
"the bell rings once when a coin first reaches one" — every new run is named
once, in at most one bell an hour; 36. "last error" stayed on the page after
the retry that fixed it — a step that gets through clears it.

Round 12 (8:32pm, what tonight's bigger replay asks of the machines — the
first replay was 20 files, 2.77 GB zipped, the largest 192 MB, 1.3-1.4 GB
unpacked each, an hour on GitHub; both accounts are public, so a machine has
16 GB): 37. **one run red on every machine stopped the chain for good** — it
re-read the same failed run every 30 minutes, never back to idle; it is
started again once (`STAGE_RETRIES`), then the day is given up by name and
the next daily update starts fresh, the last finished data still on the
page. 38. **missing machines were never on the page**, and base and options
could each miss a different one — both stages now merge over the machines
they share, and the page prints "PART OF THE MARKET: the coins of N of the
run's 20 machines" and the chain line "used without: …".

Round 13 (8:36pm, the chain's first step landed — replay 36940719775 to
Oct 01, 2026 4:00pm): 39. **a what-if never said which data it was measured
on**; after tonight's merge #2F39EAEC's answer (Sep 30, 2026 12:00pm data)
would sit under a table measured to Oct 01. The row prints "data to …" and
says when it is older than the table's.

Round 14 (8:38pm, the first finished what-if): #2F39EAEC "85% wins, 30+
trades in 30 days, TP wider than SL, stop 2% or tighter" — about +98.04 a
month after the reality check (+21.02 to +115.57), beat random 100 in 100,
needs $120, a room can run it today. 40. **its download stayed on disk**: an
open .npz cannot be deleted on Windows and `ignore_errors` hid it; the files
are closed before the delete.

Round 15 (8:42pm, watching the base step land): 41. **"working on GitHub:
18 of 20 machines done" stayed through the download and merge** of a run
that had finished green — the tick saves at its end; a slow step now says
what it is doing, on disk, before it starts.

Round 16 (8:54pm-9:03pm, reading the first automatic day's results):
42. **October's prediction came from a research replay** (TP wider than SL
    only, 2 groups, 1,079 coins), so its 288 "any TP" rule sets would have
    been graded in November on other strategies; the merge's `main()` KEPT a
    month by default, which is how a hand-run merge claimed it. A month is
    kept only with `--keep`, which only the chain's final merge passes;
    every kept prediction and `latest.json` carry the replay's write rule,
    groups, coins and strategies; the grade names both sides when they
    differ; October's line is the chain's own first (8:54pm).
43. **The summary bell named 3 of 6 rooms** ("and 4 more") — the rooms are
    short now and all six fit.
44. **"made at 8:49pm"** was when the last step began; the merge finished at
    8:54pm. It is stamped after the merge.

Round 17 (9:05pm, the live page after the last restart, desktop 1440 and
phone 390: 0 errors, no sideways scroll, 444/302 ms): 45. **one event, two
times** — the status line said "today's Forecast v2 was made at Oct 01, 2026
8:49pm" while the card under it said "made Oct 01, 2026 8:54pm". The chain
now takes "made at" from the merge's own stamp, the one the card prints, and
tonight's status was corrected to 8:54pm (read back after the next check).
Nothing else found; every reader of round 16's new fields checked clean.

Streak bells under the old code, before 8:15pm: two, one per run —
ABNBSTOCK at 7:59pm and NECSTOCK at 8:04pm, both 6 losses in a row in
#4FC03172. All rounds that did find something: RCA-2026-10-01-J, -K and -L.

## The build prompt

Word for word, as it was run ("okay run that prompt and create Forecast v2").
The operator asked for it as **Forecast v2**, so it is its own page and the
first Forecast page keeps its room cards and saved forecasts.

```
Build the Forecast predictions on Auto Trade -> Forecast: STREAKS, COINS TO AVOID,
WHERE THE MONEY GOES, BEST ROOM RULES THIS MONTH and a DAILY SUMMARY, and make sure
there is no bug.

What I mean by forecast: predict, from ALL the backtest results, which coins are hot,
which coins to stay away from, what is losing the money, and which combination of
room rules will make the most this month. Put these sections at the top of the
Forecast page; keep the room cards and saved forecasts below them.

BEFORE WRITING ANY CODE
- Read CLAUDE.md, docs/OPERATOR-ASKS.md (my own words), docs/TRADING-ROOMS.md,
  docs/FORECAST-PROMPTS.md, tradingagents/watcher_policy.py, watcher_replay.py,
  watcher_research.py, replay_collect.py, rolling30.py, room_stats.py,
  room_forecasts.py, notifications.py, .github/workflows/replay.yml and research.yml,
  and webapp/src/components/forecast/RoomForecasts.tsx.
- Say back in 3 lines what already exists (the day-by-day replay, the TRAIN/TEST
  research that picked my rooms' rules, where every trade of every combination
  lives) and build ON it. The rules live in ONE place (watcher_policy), and each
  stock coin's market lives in ONE place (room_stats.home_market / market_open);
  never write a second copy of either.
- Run `git status`: other sessions edit this folder. Never `git stash`. Commit only
  your own files with `python scripts/commit_own.py -F msg.txt <paths>`.
- Read only on trading: never switch a room on or off, never change watcher rules,
  never touch real money. Every prediction and warning is a note, never a switch.
- Every example number below is from my practice trades as of Oct 01, 2026.
  Re-measure each one before you rely on it.

A. STREAKS ("inform me when a coin is on a streak")
1. A winning streak = wins in a row, ending with the most recent closed trade (a
   win = profit after all costs > 0, the same rule as everywhere); a loss ends it.
   A LOSING streak is the opposite, and a win ends it.
2. Two sources, each named on screen:
   - PRACTICE: per room and coin, from each room's own trade record.
   - BACKTEST: per stored combination (coin + timeframe + signal + TP + SL, with its
     #ID), from that combination's own trades in the latest backtest.
3. Two lists:
   - WINNING: every coin whose current winning streak is at least N (default 9).
   - LOSING: every coin whose current losing streak is at least M (default 5). For
     example, DHRSTOCK won 4 and lost 38 practice trades (-38.48) across 5 rooms.
   Each list has a box to change its number and is sorted longest first. Each row
   shows: coin, room or #ID, timeframe, signal, TP, SL, streak length, when it
   started and its last trade (dates), profit during the streak, total trades /
   wins / losses / win rate, its break-even win rate, and which room has it
   switched on (or "none").
4. Turn each streak into a MEASURED prediction: across all past backtest history,
   after a streak this long, how often did the next trade win, and what did the next
   10 trades make, with how many past cases. Under 30 past cases, say "not enough
   past streaks to tell" instead of a number.
5. Ring the app's bell (notifications.py) ONCE when a coin first reaches a streak
   (winning or losing); never again for the same streak.
6. Search EVERY combination on the server, never a top-N page filtered in the
   browser. Say how many combinations and trades were examined; an empty list says
   what it examined, never "none exist". Measure streaks where the trades already
   exist (the GitHub shard or the replay output) and store them. Never re-play
   millions of trades inside a page request.

B. COINS TO AVOID
1. Coins that lose across rooms. For example, IGV won only 3 of 47 practice trades
   (-50.87) across all 9 rooms. For each coin: rooms that traded it, trades,
   wins / losses, win rate, profit, worst losing run, and its backtest win rate
   beside its practice win rate.
2. Every number must equal a direct count of the trade records, and the list is
   sorted by profit, worst first.
3. Feed this list into section D as a rule option: "skip the coins to avoid".

C. WHERE THE MONEY GOES (each one measured on practice trades AND on the backtest,
   side by side, with trades, wins / losses, win rate and profit)
1. COSTS: profit, costs, and profit without costs, per room and for all rooms.
   All rooms lost -458.31, and 355.91 of that was costs.
2. WIN SIZE vs LOSS SIZE: the average win, the average loss, the break-even win
   rate they make, and the real win rate. An average win paid +0.78 and an average
   loss cost -1.02, so break-even was 56.6% against 41.2% won.
3. BY TIMEFRAME (15m, 30m, 1h, 4h, 1d). 1h trades won 32.7% (-41.17 over 104)
   against 41.7% on 15m.
4. BY SIGNAL FAMILY. cci20 won 15.9% of 44 trades (-35.04); stoch14 lost -128.12
   over 539.
5. STOCKS vs CRYPTO. Stocks: 1,328 trades, 40.7% won, -380.44. Crypto: 326
   trades, 43.6% won, -76.55.
6. BY THE HOUR OPENED (New York time). 9am to noon: 642 trades, 33.2% won,
   -279.89.
7. FAST STOP-OUTS: trades stopped out within 15 minutes, 15-60 minutes, and after
   an hour. 201 trades stopped out within 15 minutes (-176.26).
8. WORST DAY per room. #4FC03172 lost -158.80 on Oct 01, 2026.
9. SAME COIN IN MANY ROOMS: how many rooms hold each coin right now. VUG was open
   in 8 rooms at once. Warn about it: with real money, MEXC merges a coin into ONE
   position across rooms.
Each finding that looks bad becomes a rule option in section D. The page says
plainly which findings rest on too few trades to mean anything.

D. BEST ROOM RULES THIS MONTH (e.g. "90% win rate, 40 trades, TP wider than SL
   will make about +$X this month")
1. THE MAIN GRID, tested in full:
   - switch-on/off win rate 70, 75, 80, 85, 90 or 95
   - minimum trades 20, 30, 40 or 50
   - TP wider than SL, TP at least 1.5x SL, TP at least 2x SL, or any
   - stop 1%, 1.5% or 2% or tighter
   - judged on 15 or 30 days
   Use the research grid where it already holds these.
2. EXTRA OPTIONS, each tested ONE AT A TIME on top of the 20 best rule sets and my
   rooms' current rules (never all combined, which would test luck, not rules):
   - skip the coins to avoid (section B)
   - skip Japanese stocks
   - stocks only while their own market is open (room_stats.home_market /
     market_open). In #4FC03172, Japanese stocks traded during Tokyo's daytime won
     25.6% (-21.15 over 43 trades).
   - cost no more than 20%, 35% or 50% of the target (the same cost the cost gate
     charges: fee + spread + funding)
   - one timeframe only (each in turn), and skip the worst signal families
   - crypto only, or stocks only
   - no new trades from 9am to noon New York
   - a daily loss limit per room: no new trades that day after losing 10, 20 or 40
   - skip rows whose stop is smaller than the coin's normal 15-minute move (its
     median 15-minute high-low range over the backtest window)
   - at most 1, 2 or 3 rooms per coin, and at most 1, 2 or 3 trades per coin in a
     room
   State above the table how many rule sets and options were tested.
3. For each, WALK FORWARD month by month with watcher_replay.simulate (no
   look-ahead): each day the watcher switches rows on using only data from before
   that day; the month's profit is what those rows really made in it, after fees,
   spread and funding, at $5 x 20x.
4. The prediction for THIS calendar month: the typical past month (median) with
   the range (worst and best past month), how many months it is built on,
   expected trades, wins/losses, win rate, break-even win rate, worst losing run
   (dollars and trades). Under 3 past months, label it "thin". Measure the real
   history depth; never claim a month the data does not hold.
5. REALITY CHECK on every prediction. The backtest research promised #4FC03172
   +4967.44 for September, but its practice trades stood at -172.73. For every
   room, measure how far its real practice results fell short of what its backtest
   promised for the same days. Show each prediction twice: as the backtest says, and
   corrected by that measured shortfall. Say exactly how the correction was
   measured and from how many rooms and trades. Never hide the corrected number
   behind the raw one.
6. BEAT RANDOM: for each rule set, switch on the same number of rows picked AT
   RANDOM (100 draws) and show how often the rule set beat them. Under 80%, label it
   "could be luck".
7. MONEY NEEDED: for each rule set, the most trades open at once x $5 = the margin
   the wallet must hold. #4FC03172 had 138 trades open at once, which is $690. Show
   it beside the profit, and say it again before anything could ever go to real
   money.
8. Rank by the WORST past month after the reality check, not the best (the
   still-working rule). Show each room's current rules beside it: predicted for
   this month vs made so far this month.
9. One plain sentence per rule set on screen, e.g. "90% wins, 40+ trades, TP at
   least 1.5x SL, stop 2% or tighter, coins to avoid skipped: about +X this month
   after the reality check (backtest says +Y; past months +a, +b, -c), about T
   trades, needs $M in the wallet, beat random 92 times in 100".
10. A WHAT-IF box: I type any rules (everything in items 1 and 2) and see the same
    prediction for them. It runs in the background, never inside the page request,
    shows "working…" with progress, and keeps every result so the same rules come
    back at once.
11. TRACK THIS MONTH day by day: for my rooms' rules and the top 5 rule sets, a
    line of real profit so far against the predicted range. Ring the bell once when
    a room falls below its predicted worst case.
12. Save each month's predictions so that at month end each one is graded,
    predicted vs real, and shown as "inside its range X of Y".
13. Give every rule set the same kind of id the research uses (e.g. #52620A69), so
    that I can say "deploy #ID" and the standing setup in CLAUDE.md makes it a room.
14. The table follows CLAUDE.md's results-table rules: profit total, TP rule, SL
    rule, leverage, margin stated above, wins and losses, worst losing streak with
    its trade count, trades, rule sets tested above the table, sortable, and the id
    from item 13 first.

E. DAILY SUMMARY ON THE BELL
Once a day, after the daily forecast is made, ONE bell message: the longest
winning streak, the longest losing streak, the worst coin to avoid, and each room's
month so far against its predicted range. Never more than one a day.

HOW IT MUST BEHAVE
- Heavy work runs as a job (on GitHub if the research already does, collected
  like the replay), once a day after the daily GitHub update is collected, never
  in a page request. The page answers in under 2 seconds from the saved result and
  prints when it was made and what data it covers.
- A job that cannot start or fails says so on the page, by name, and the page
  says whether a job is running.
- Big files go under ~/.tradingagents (the G: drive), never C:.
- Every filter and page runs on the server. Every label comes from its data, and
  rows add up to the totals shown.
- Dates use fmtWhen / fmt_when only ("Oct 01, 2026 8:03pm"); money uses fmtMoney.
- Plain words on screen. Phone (390px) and desktop both work, and wide tables
  scroll inside their own box.

NO-BUG CHECKLIST (do all of it, show the results)
1. Tests for every definition and every section, with trades and months on ONE
   timeline; tests for the API routes and the page source.
2. Real-data check:
   - for 3 coins, the streak shown equals a direct read of their trades;
   - for 3 coins to avoid, every number equals a direct count of the trade records;
   - every number in section C equals a direct count, for 2 rooms and for all;
   - for 2 rule sets, re-run one past month by hand and compare;
   - for 2 rooms, re-work the reality-check shortfall by hand.
3. Bug hunt (harddev), round after round until a round finds nothing; list what
   each round found.
4. Run every test file you touched, the date-format guards, ruff, tsc and eslint.
5. Playwright screenshots at 1440px and 390px with zero console errors; open a
   streak, a coin to avoid, each part of section C, a rule set, a what-if run, the
   month tracker and the graded predictions.
6. Any bug you fix gets its docs/RCA.md entry in the same commit.

FINISH
- Commit with scripts/commit_own.py and push to both accounts (origin and
  colleague). Anything GitHub runs from main is pushed at once.
- Restart the site (warn me first: about 3-5 minutes dark), then check /forecast.
- Answer me in plain words: what was built, one real example (a real streak, a
  coin to avoid, or a rule-set prediction with its numbers), then "Pending for
  you:" with what I must do, or "No pending for you."
```

### Where the build differs from the prompt, and why

* **Its own page.** The operator asked for "Forecast v2", so `/forecast-v2`;
  the first Forecast page is untouched.
* **Cost options 5, 10 and 15%**, not 20, 35 and 50%: the replay only writes a
  strategy whose cost is under 20% of its target (replay_shard's own gate), so
  nothing above 20% exists to test.
* **Rooms per coin** is not a rule-set option — a rule set is one room — and is
  section C's overlap warning instead. Trades per coin is tested (1, 2, 3).
* **Walked forward with `watcher_research.raw_fast`**, not `simulate`: the rooms
  run raw rules, and raw_fast is held equal to simulate trade for trade by
  tests/test_watcher_research.py (`test_the_fast_raw_path_is_simulate`).
* **Beat random is per trade** — see "Beat random" above.
* **The bell for a new streak** is the daily summary's longest runs for the
  BACKTEST, not one message per strategy: 689,474 strategies were on a run of
  5+ at once, and a bell per strategy would bury every other message. For
  PRACTICE every new run is named once, in at most one bell an hour (46 runs
  reached the line on Oct 01, 2026).
