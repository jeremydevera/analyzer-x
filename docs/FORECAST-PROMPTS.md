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
rule — including the ones earlier research left out: a stop WIDER than the target
(SL > TP), a target equal to the stop, very wide targets, and rules that need only a
few trades.

A "room rule" is what a Smart Watcher room switches strategies on and off by:
the window it looks back over, the win rate to switch on and off at, the fewest
trades it needs, how the target compares to the stop, and the widest stop and
target it allows. Test at least this grid, every combination:
- window: last 7, 15 and 30 days
- switch-on win rate: 40, 50, 60, 70, 80 and 90% (switch off under the same line)
- fewest trades in the window: 1, 3, 5, 10, 20, 30 and 50
- target vs stop: any, target wider than stop, target equal to stop, stop wider than target
- widest stop allowed: no cap, 1%, 2%, 3%
- smallest target allowed: none, 1%, 2%, 3%
Say how many rule sets that is before starting, and how many strategies each one
picks from. Never cut the grid quietly — if something cannot run, name it and why.

Make it a FAIR test (this is what went wrong before):
1. The replay data must include every strategy each rule could pick. The last
   research data only kept strategies with the target wider than the stop and 10+
   trades, so stop-wider-than-target and few-trade rules found nothing or leaned on
   hindsight (docs/RCA.md RCA-2026-09-29-F). Re-run the replay on GitHub
   (.github/workflows/replay.yml) with a write rule no stricter than the loosest rule
   in the grid (win rate 40, trades 1, target vs stop "any"), then the research
   (.github/workflows/research.yml). Say how long each will take before starting.
2. Pick on July–August, grade on September 1 to today — never pick and grade on the
   same days. Report both periods for every rule set.
3. Charge all three costs on every trade (entry, exit and holding) and use the
   runner's own limits (at most 4 open trades per coin, $5 at 20x).
4. Show each rule set's break-even win rate after costs, never 50%. A stop wider
   than the target needs a much higher win rate to break even — say how much.

Then rank:
- by September profit, but only rule sets that also made money in July–August;
- show beside each: wins/losses, win rate, break-even win rate, trades, trades a
  day, most open at once, worst losing run (dollars and how many trades), worst day,
  and green days;
- name the best rule set in each target-vs-stop shape (wider, equal, stop wider) so
  the shapes can be compared, even if one shape never wins overall.

Publish it as an artifact: the top 100 rule sets, a stable id per rule set, every
column above, the margin $5 x 20x stated above the table, a click on a row showing
its September trades one by one with a total, filters for min win rate, min profit,
max TP %, max SL %, target-vs-stop shape and window, sortable columns, and the
number of rule sets tested above the table.

Rules for the answer:
- Real numbers from the replay and my own records only; if something cannot be
  measured, say so.
- In chat: the best rule set in one plain sentence with its id and September profit,
  the best one in each shape in one line each, then "Pending for you:" with what I
  must do, or "No pending for you."
- Do not create rooms, switch anything on or off, or change any rules unless I say
  "deploy". When I do, each rule set I name becomes its own room, practice only
  (CLAUDE.md "STANDING SETUP").
```
