# Room forecast prompts

*Oct 01, 2026. The operator: "can you do a forecast on what's the best
strategy room? could you enhance this prompt so i can use it in the future",
then "create a forecast tab, then if i run this prompt make sure it will
generate a new forecast". Every forecast the first prompt makes is saved with
`python -m tradingagents.room_forecasts add <file>` and shows on Auto Trade ->
Forecast. The Forecast tab shows both prompts with a copy button.*

*Since Oct 01, 2026 the tab also makes forecasts itself — the "make a new
forecast now" button and an automatic one once a day after the daily GitHub
update is on this PC — from the same numbers it shows
(`tradingagents/room_stats.py`). Each saved forecast says who made it
(`source`: "prompt", "button" or "auto"). Prompt 1 below is for a WRITTEN
forecast with an artifact; it must use the room ids this machine has, and
every number in it must be a number (the save refuses anything else, naming
what is wrong).*

*Forecast v2 (Auto Trade -> Forecast v2, Oct 01, 2026) — streaks, coins to avoid, where the money goes and the room rules predicted for this month — has its own page and its own account: docs/FORECAST-V2.md.*

## 1. Make a new forecast

```
Forecast which trading room is most likely to make money over the next 30 days.

Rooms to judge: every tab on Auto Trade (Main and each #ID room), plus the
retired rooms (#DC57174E, #CC8DC54C, #B52662ED) for comparison only, never as a pick.

For each room, measure, do not assume:
1. Its RULES, read from that room's own watcher (window 15 or 30 days, switch-on and
   switch-off win rate, min trades, TP wider than SL, max SL).
2. What the RESEARCH said: the room's September result from the research page
   (profit, wins/losses, win rate, trades, worst losing run, most open at once).
3. What it has REALLY done in the practice account since it was switched on:
   closed trades, wins/losses, win rate, total profit, profit per trade, worst
   losing run (dollars and how many trades), trades still open, first trade time.
4. The BREAK-EVEN win rate for its typical TP/SL after costs, never 50%. Say how far
   above or below that line the room really is.
5. Whether there is ENOUGH evidence yet: say how many closed trades and days of
   practice there are, and call anything under 100 trades or 7 days "too early to tell".

Then:
- Rank the rooms by real practice profit per trade, and show the research number beside it.
- Flag any room whose real results are far worse than its research (say by how much).
- Pick ONE best room, or say plainly "none is proven yet" if the evidence is too thin.
- Say what would change the answer, for example "after 200 closed trades".

Save it so the Forecast tab shows it: write the forecast as one JSON object in the
shape documented at the top of tradingagents/room_forecasts.py (at, pick, pick_why,
verdict, rooms with rules/research/real, artifact, note, source "prompt") and run
`python -m tradingagents.room_forecasts add <file.json>`. If it refuses, fix what it
names and run it again; never edit ~/.tradingagents/room_forecasts.jsonl by hand.

Rules for the answer:
- Real numbers from my own trade records and room files only. If something cannot
  be measured, say so instead of guessing.
- Publish the full comparison as an artifact table with: room id, rules, research
  profit, real profit, wins/losses, win rate, break-even win rate, trades, profit per
  trade, worst losing run, open trades, days running, margin $5 x 20x stated above
  the table; put its link in the saved forecast's "artifact".
- In chat: the pick in one plain sentence with one real example number, then
  "Pending for you:" with what I must do, or "No pending for you."
- Do not switch any room on or off, and do not change any rules, unless I ask.
```

## 2. Look across every saved forecast

```
Look at every room forecast I have saved (the Forecast tab, which reads
~/.tradingagents/room_forecasts.jsonl) and tell me which room is truly the best so far.

Do this, measuring, never assuming:
1. List each saved forecast by its date and time, its pick, and the pick's real
   profit per trade at that moment.
2. CHECK THE OLD PICKS: for each past forecast, what did its picked room ACTUALLY do
   in the practice account from that date until now (closed trades, wins/losses,
   profit, worst losing run)? Was the pick right, wrong, or too early to tell?
3. For every room, show how its real profit per trade and win rate moved from
   forecast to forecast, and whether it is getting better, worse, or holding steady.
4. Show each room's real win rate against its break-even win rate after costs,
   every time.
5. Say how much evidence there is now: total closed trades and days per room.
   Anything under 100 trades or 7 days is "too early to tell".

Then:
- Name the room that has been the pick most often AND stayed above its break-even
  in its real results. Being picked often is not enough.
- Name any room that has fallen behind its own research numbers, and by how much.
- If no room has held up across the forecasts, say "none is proven yet".

Rules for the answer:
- Real numbers from the saved forecasts and my own trade records only. If an old
  forecast is missing a number, say so instead of guessing.
- Publish the history as an artifact: one table of all saved forecasts, and one
  table per room over time (date, closed trades, wins/losses, win rate, break-even,
  profit, profit per trade, worst losing run), with margin $5 x 20x stated above.
- In chat: the best room in one plain sentence with one real example number, then
  "Pending for you:" with what I must do, or "No pending for you."
- Do not switch any room on or off, and do not change any rules, unless I ask.
```

## 3. Find the best room rules (every shape, nothing left out)

```
Find the room rules that would have made the most money, testing EVERY shape of
rule — including the ones earlier research left out: a stop WIDER than the target,
a target EQUAL to the stop, wide targets, and rules that need only a few trades.

The grid is already built: grid 6 in tradingagents/watcher_research.py
(scenarios6) — 8,064 rule sets, every combination of:
- window: last 7, 15 and 30 days
- switch-on win rate: 40, 50, 60, 70, 80 and 90% (switch off under the same line)
- fewest trades in the window: 1, 3, 5, 10, 20, 30 and 50
- target vs stop: any, target wider, target equal, stop wider
- widest stop allowed: no cap, 1%, 2%, 3%
- smallest target allowed: none, 1%, 2%, 3%
Every rule set is raw (no limits) with the runner's 4 open trades per coin, $5 at 20x.

Run it like this, saying how long each step should take before starting it:
1. NEW DATA, written loose enough for every rule set (a stricter write rule makes
   the looser rule sets lean on hindsight — docs/RCA.md RCA-2026-09-29-F):
   gh workflow run replay.yml -f shards=40 -f start=2026-07-01 -f groups=classic,preset -f write_rule="wr=40,trades=1,tp=any,windows=7|15|30"
   Wait for it to finish (about 1.5–2 hours). If a machine fails, re-run only that
   machine, never the whole run.
2. THE COMMON END: download only the small replay-report-* artifacts of that run,
   then python -c "from tradingagents import replay_collect as rc; print(rc.common_end(rc.merge_reports('<folder>')['spans']))"
3. THE RESEARCH, 40 data shards x 4 grid slices = 160 GitHub jobs (each about
   1–2 hours; measured Oct 01, 2026 at 0.59 s per rule set on one shard of the
   older, smaller data):
   gh workflow run research.yml -f source_run=<replay run id> -f shards=40 -f end_ms=<common end> -f scenarios=6 -f chunks=4
   If a job fails, re-run only the failed jobs.
4. ADD IT UP on this PC: download every research-* artifact into a folder on G:
   (never C:), then
   python -m tradingagents.research_merge s6 <research folder> <folder with the replay reports>
   It writes ~/.tradingagents/replay/research-s6.json, keeping trade lists for the
   100 best rule sets on July–August only.
5. THE PAGE: python -m tradingagents.research_page s6 --split --log-top 100 --data <folder with the replay reports>
   It writes research-s6.html and research-s6/logs/*.gz.txt (their list is in
   research-s6/files.json); publish the page with every log file as an artifact.

Make it a FAIR test:
- Pick on July–August, grade on September 1 to the common end — never pick and
  grade on the same days. Report both periods for every rule set.
- Every trade pays all three costs (entry, exit and holding).
- Show each rule set's break-even win rate after costs, never 50%. A stop wider
  than the target needs a much higher win rate to break even — say how much.
- research_page.unfair() must find no rule set looser than the data. If it does,
  stop and say which.

Then rank:
- by September profit, but only rule sets that also made money in July–August;
- show beside each: wins/losses, win rate, break-even win rate, trades, trades a
  day, most open at once, worst losing run (dollars and how many trades), worst day,
  and green days;
- name the best rule set in each target-vs-stop shape (wider, equal, stop wider,
  any) so the shapes can be compared, even if one shape never wins overall.

The artifact: the top rule sets with a stable id per rule set, every column above,
the margin $5 x 20x stated above the table, a click on a row showing its September
trades one by one with a total, filters for min win rate, min profit, max TP %,
max SL %, smallest target, target-vs-stop shape and window, sortable columns, and
the number of rule sets tested (8,064) above the table.

Rules for the answer:
- Real numbers from the replay and my own records only; if something cannot be
  measured, say so.
- In chat: the best rule set in one plain sentence with its id and September profit,
  the best one in each shape in one line each, then "Pending for you:" with what I
  must do, or "No pending for you."
- Do not create rooms, switch anything on or off, or change any rules unless I say
  "deploy". When I do, each rule set I name becomes its own room, practice only
  (CLAUDE.md "STANDING SETUP"). Rooms can run every rule in grid 6 — "=" and the
  smallest target included — EXCEPT the 7-day window: a room judges on 15 or 30
  days only. If a 7-day rule set wins, say so plainly, and name the best 15- or
  30-day rule set beside it as the one that can be deployed today.
```

## 4. Find new room strategies for this month and the next 15 days

```
Find NEW room strategies that should make the most THIS MONTH and over the NEXT 15
DAYS, testing every shape of rule, and keep every one found in "Room Strategies"
inside Auto Trade -> Forecast v2 -> "Best room rules this month". A room strategy
and a row of that table are the same thing — one set of room rules and what it
should make — so they live in one place. Every run must look further than the
last: it starts from everything already stored and tries combinations never tried
before on that data.

A room strategy is one set of room rules, every one of these varied:
- judged on the last 7, 15 or 30 days
- switch on at a win rate of 40-95% (steps of 5), off under the same line
- fewest trades in that window: 1, 3, 5, 10, 20, 30, 40 or 50
- target vs stop: any, target wider, target at least 1.5x or 2x the stop, equal,
  stop wider
- widest stop allowed: none, 1%, 1.5%, 2%, 3%; smallest target: none, 1%, 2%, 3%
- Forecast v2's 22 options (forecast_rules.OPTIONS), one at a time and in pairs
Every one raw, with the runner's 4 open trades per coin, $5 at 20x, all three
costs charged (entry, exit and holding).

The two horizons — measure each one, never scale one into the other:
- THIS MONTH = the median complete past month, the worst and the best, and the
  same after the reality check (forecast_v2.corrected: took x (profit - gap x
  trades)).
- NEXT 15 DAYS = the same on complete 15-day stretches counted back from the last
  complete day of the data. Never a month divided by 2 (docs/RCA.md
  RCA-2026-10-01-J).

Run it like this, saying how long each step should take before starting it:
1. DATA loose enough for every rule set tried (a stricter write rule makes the
   looser ones lean on hindsight, docs/RCA.md RCA-2026-09-29-F): use a replay
   written today with write_rule "wr=40,trades=1,tp=any,windows=7|15|30" if
   there is one, otherwise start it the way prompt 3's step 1 does. Say its run
   id, its end, and what it covered (signal groups, coins, strategies).
2. ROUND 1, the known: every strategy already in Room Strategies, the rooms' own
   rules, Forecast v2's daily grid and grid 6 (8,064). Walk each one forward day
   by day on GitHub (forecast.yml / forecast_shard.py, or research.yml, whichever
   reads this replay; add a stage that takes a list of rule sets if neither can),
   adding up per month and per 15-day stretch.
3. NEW ROUNDS: around the 20 best of each horizon, try what was never tried — one
   step on every dial, each option, then pairs of options on the 10 best — until
   a round beats nothing already stored, or 5 rounds. Say per round how many rule
   sets were tried and how many were new. Keep the id of every rule set tried on
   this data (on G:, beside ~/.tradingagents/forecast_v2/) so the next run never
   repeats one and always reaches new ones.
4. A FAIR PICK: a strategy is kept as a WINNER only when it would have been
   picked without the newest month AND it still made money in the newest month
   and the newest 15 days, which the pick never saw. Rank by the WORST past month
   (or stretch) after the reality check, then the typical one — never by the
   best. Show how often it beat random picks (per trade); under 80 in 100 say
   "could be luck".

Room Strategies — what is kept, and how it shows:
- Every winner of every run, never deleted: its id (forecast_rules.rule_id), the
  rules in words, the date and run that found it, and both horizons with their
  ranges, straight and after the reality check.
- Kept current: the daily Forecast v2 run re-measures every stored strategy it
  can measure fairly (its replay is written at 70% / 20 trades / 15 or 30 days),
  so those carry fresh numbers every day. A looser one shows the date it was last
  measured and is re-measured on every run of this prompt. Measure what keeping
  the looser ones current every day would cost (a looser daily replay: how much
  longer the daily job takes) and tell me; change nothing until I choose.
- On the page, inside "Best room rules this month": a "this month | next 15 days"
  choice for the whole table, and a "Room Strategies" list holding every stored
  one with: the id first; the rules in words; found on; predicted profit and its
  range for both horizons; wins and losses; win rate; break-even win rate after
  costs (never 50%); trades and trades a day; worst losing run (dollars and how
  many trades); most open at once; money needed; beat random; last 15 days and
  last 30 days; still working or not; can a room run it today, or which switch it
  needs. Margin $5 x 20x and the number of rule sets tested stated above it;
  filters done by the server; a find-by-id box; a click on a row shows its trades
  one by one with a TOTAL.
- A stored strategy whose newest month or newest 15 days loses stays in the list,
  marked "stopped working on <date>" — never removed.

Build it with the harddev skill; tests on one timeline in tests/test_forecast_v2.py,
at least one red on the old code; update docs/FORECAST-V2.md; an RCA entry for any
bug found on the way. Run `git status` first (other sessions edit this folder),
never `git stash`, commit only your own files with `python scripts/commit_own.py
-F msg.txt <paths>`, push both accounts, and restart the site only after warning
me (about 1-5 minutes dark), never while the daily chain is starting a GitHub run.

Rules for the answer:
- Real numbers from the replay and my own trade records only; if something cannot
  be measured, say so.
- In chat: one plain sentence naming the new best strategy for this month and the
  new best for the next 15 days, each with its id and its prediction after the
  reality check, and how many new strategies this run kept; then "Pending for
  you:" with what I must do, or "No pending for you."
- Read only on trading: create no rooms, switch nothing on or off and change no
  rules unless I say "deploy". When I do, each strategy I name becomes its own
  room, practice only (CLAUDE.md "STANDING SETUP"); one that needs a switch a
  room does not have yet (TP at least 1.5x or 2x SL, a 7-day window, any of
  Forecast v2's options) says so instead.
```
