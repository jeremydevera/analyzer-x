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

*Forecast v2 (Auto Trade -> Forecast v2, Oct 01, 2026) — streaks and the room rules predicted for this month (its coins to avoid were removed on Oct 07, 2026; where the money goes, the what-if box and this month so far on Oct 08, 2026) — has its own page and its own account: docs/FORECAST-V2.md.*

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

## 4. Find new winning room strategies and keep them in Best room rules

```
Find NEW winning room strategies, testing every shape of rule, and keep every
winner in Auto Trade -> Forecast v2 -> "Best room rules": a winner is a row in
that table, marked with the day this prompt found it, never deleted. Every run
must look further than the last one: it starts from everything already in the
table and tries combinations no run has tried before on that data.

And make that section a DATE RANGE instead of one month: rename it from "Best
room rules this month" to "Best room rules" and give it FROM and TO dates (any
days inside the data, with quick picks for the last 15 days, the last 30 days and
each calendar month — they are only ranges). Every number in the table is
re-measured over exactly the chosen dates, on the server, never a month scaled up
or down: trades, wins and losses, win rate, profit straight and after the reality
check, worst day, worst losing run, most open at once. Beside them, "a stretch
this long usually makes": the median, worst and best of every past stretch of the
same length, measured, after the reality check. The ranking follows the chosen
dates. (A month divided by 31 once printed a worst case no month ever made —
docs/RCA.md RCA-2026-10-01-J.)

A room strategy is one set of room rules, every one of these varied:
- judged on the last 7, 15 or 30 days
- switch on at a win rate of 40-95% (steps of 5), off under the same line
- fewest trades in that window: 1, 3, 5, 10, 20, 30, 40 or 50
- target vs stop: any, target wider, target at least 1.5x or 2x the stop, equal,
  stop wider
- widest stop allowed: none, 1%, 1.5%, 2%, 3%; smallest target: none, 1%, 2%, 3%
- Forecast v2's 21 options (forecast_rules.OPTIONS), one at a time and in pairs
Every one raw, with the runner's 4 open trades per coin, $5 at 20x, all three
costs charged (entry, exit and holding).

Run it like this, saying how long each step should take before starting it:
1. DATA loose enough for every rule set tried (a stricter write rule makes the
   looser ones lean on hindsight, docs/RCA.md RCA-2026-09-29-F): use a replay
   written today with write_rule "wr=40,trades=1,tp=any,windows=7|15|30" if
   there is one, otherwise start it the way prompt 3's step 1 does. Say its run
   id, its end, and what it covered (signal groups, coins, strategies).
2. ROUND 1, the known: every strategy already in Best room rules, the rooms' own
   rules, Forecast v2's daily grid and grid 6 (8,064). Walk each one forward day
   by day on GitHub (forecast.yml / forecast_shard.py, or research.yml, whichever
   reads this replay; add a stage that takes a list of rule sets if neither can).
3. NEW ROUNDS: around the 20 best, try what was never tried — one step on every
   dial, each option, then pairs of options on the 10 best — until a round beats
   nothing already in the table, or 5 rounds. Say per round how many rule sets
   were tried and how many were new. Keep the id of every rule set tried on this
   data (on G:, beside ~/.tradingagents/forecast_v2/) so the next run never
   repeats one and always reaches new ones.
4. WINNING, by A FAIR PICK: a strategy is a winner only when it would have been
   picked without the newest month AND, after the reality check, it made money
   in every complete month and in the newest 15 days, which the pick never saw.
   Rank by the WORST complete month after the reality check, then the worst
   15-day stretch — never by the best. Show how often it beat random picks (per
   trade); under 80 in 100 say "could be luck".

What is kept for every winner: its id (forecast_rules.rule_id), the rules in
words, the day and run that found it, and its trades — so any date range can be
re-measured — plus whether it still works. A winner whose newest month or newest
15 days loses stays in the table, marked "stopped working on <date>".
Kept current: the daily Forecast v2 run re-measures every winner it can measure
fairly (its replay is written at 70% / 20 trades / 15 or 30 days), so those carry
fresh numbers every day; a looser one shows the date it was last measured and is
re-measured on every run of this prompt. Measure what keeping the looser ones
current every day would cost (a looser daily replay: how much longer the daily
job takes) and tell me; change nothing until I choose.

The table, whatever dates are chosen: the id first; the rules in words; found by
(the daily grid, or this prompt on <date>); the range's trades and trades a day,
wins and losses, win rate, break-even win rate after costs (never 50%), profit
straight and after the reality check, worst day, worst losing run (dollars and
how many trades); "a stretch this long usually makes"; beat random; can a room
run it today, or which switch it needs. Margin $5 x 20x and the number of rule
sets tested stated above it; filters done by the server (min win rate, min
profit, the TP rule, stop at most %, judged on 7, 15 or 30 days, found by, a
room can run it today); a find-by-id box; a click on a row shows its trades in
the range one by one with a TOTAL.

Build it with the harddev skill; tests on one timeline in tests/test_forecast_v2.py,
at least one red on the old code; update docs/FORECAST-V2.md; an RCA entry for any
bug found on the way. Run `git status` first (other sessions edit this folder),
never `git stash`, commit only your own files with `python scripts/commit_own.py
-F msg.txt <paths>`, push both accounts, and restart the site only after warning
me (about 1-5 minutes dark), never while the daily chain is starting a GitHub run.

Rules for the answer:
- Real numbers from the replay and my own trade records only; if something cannot
  be measured, say so.
- In chat: one plain sentence naming the best new winner with its id and what it
  made over the newest 30 days after the reality check (or that nothing new beat
  the table), and how many new winners this run kept; then "Pending for you:"
  with what I must do, or "No pending for you."
- Read only on trading: create no rooms, switch nothing on or off and change no
  rules unless I say "deploy". When I do, each strategy I name becomes its own
  room, practice only (CLAUDE.md "STANDING SETUP"); one that needs a switch a
  room does not have yet (TP at least 1.5x or 2x SL, a 7-day window, any of
  Forecast v2's options) says so instead.
```

### How prompt 4 runs now — the steps and what they cost (first run, Oct 02, 2026)

The operator, Oct 02, 2026: *"when i run the prompt #4 its up to you what kind
of combination you want ... when i run that prompt i want you to look for all
kinds of combination then add it in room strategy"*. Measured on the first run,
so the next one can say how long each step takes before starting it:

| step | command | first run |
|---|---|---|
| data | a replay written at `wr=40,trades=1,tp=any,windows=7\|15\|30` | run 37007971331: 1,098 coins on **20 of 40** machines (the replay hands coins out first come, first served — an empty shard is normal), 23,494,320 combinations, 3,139,117,865 trades, end Oct 02, 2026 8:00am |
| round 1 list | `python -m tradingagents.room_strategies round1 round1` | 8,568 rule sets, 156 switch-on walks |
| round 1 | `python -m tradingagents.room_strategies dispatch research/p4/round1.json daily 4 <replay> <replay repo> <end ms>` — **both accounts, 40 machines** (CLAUDE.md, Oct 02, 2026); then `... fetch <folder on G:> <repo>:<run> <repo>:<run>` | first run (one account, before that rule): run 37033893955, the 20 shards with coins x 4 slices = 80 jobs, **2 h 13 min**, peak memory ~3.3 GB a machine (16 GB there) |
| score | `python -m tradingagents.room_strategies daily round1 <downloaded folder> <replay>` | 458 s; refuses a round with any job missing (`check_complete`); 673 winners, writes `round1-confirm.json` and `round1-next.json` |
| confirm | `... dispatch research/p4/round1-confirm.json full 1 <replay> <replay repo> <end ms>`, then `fetch` | run 37050144154, ~15 min |
| keep | `python -m tradingagents.room_strategies finish round1c <folder> ~/.tradingagents/replay/reports-<replay> <replay>` — it also rewrites `research/p4/kept.json`, the list the DAILY RE-TEST reads: **commit and push it** with the round's files, or tomorrow's re-test misses the new winners (the page counts them) | 75 s; 662 kept (2,381,217 trades, 83 MB on G:) |
| new rounds | `daily` on `round<N>-next.json`, then its confirm, until a round beats nothing or 5 rounds | round 2: 92 rule sets, ~20 min, 56 winners |

**AFTER PROMPT 4, EVERY DAY (Oct 07, 2026).** The operator: *"what do you mean
saved strategy? it should be updated everyday justd like the backtest"*. Every
kept winner is re-measured once a day on GitHub by
`tradingagents/room_strategies_daily.py` — the same replay start (Jul 01, 2026),
signal groups (classic, preset) and research walk, so a row's numbers reach last
night. Prompt 4 still FINDS new winners; the daily job never adds or deletes one.

Before trusting a new round's numbers, the confirm run's months were checked
against the day totals (2,357 months, 0 differences). The newest-15-days figure
differs by design: day totals count whole days, so their window starts ~8 hours
earlier. **The kept verdict always comes from the trades.** Download every
round to G: (`~/.tradingagents/tmp/`), never `C:`. A round's results are about
345 MB.
Full account of what broke on the first run: `docs/RCA.md` RCA-2026-10-02-E
and RCA-2026-10-02-F.
