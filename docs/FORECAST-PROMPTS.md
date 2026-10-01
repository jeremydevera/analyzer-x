# Room forecast prompts

*Oct 01, 2026. The operator: "can you do a forecast on what's the best
strategy room? could you enhance this prompt so i can use it in the future",
then "create a forecast tab, then if i run this prompt make sure it will
generate a new forecast". Every forecast the first prompt makes is saved with
`python -m tradingagents.room_forecasts add <file>` and shows on Auto Trade ->
Forecast. The Forecast tab shows both prompts with a copy button.*

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
verdict, rooms with rules/research/real, artifact, note) and run
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
