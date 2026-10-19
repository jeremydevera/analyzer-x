---
name: winning_room_strategy
description: Use when the operator asks which room strategy has been winning (this week, last week, the past N days, or between two dates), or runs "/winning_room_strategy". Reads Forecast -> Room strategies through the route the table itself reads, for the days asked, and reports the room strategies that made money, best first.
---

# winning_room_strategy

The operator, Oct 18, 2026, word for word:

> What room strategy has been winning this week, can you check the list of room strategy, also make a skill for this called '/winning_room_strategy' so that you will find the winning room strategy via room strategy table, I will give you the days i need for example, i need winning room stragy for past 2 days, or 7 days or last week
>
> Also add this skill in claude skills tab along with practice backtest audit skill since this is an automation

It sits in the **Automation** group of the Claude skills tab, beside
`practice_backtest_audit` (`tradingagents/claude_skills.py`).

## Run it

From the repo root, with the app's Python (the site must be running):

```bash
.venv/Scripts/python .claude/skills/winning_room_strategy/scripts/winning.py --days 2
.venv/Scripts/python .claude/skills/winning_room_strategy/scripts/winning.py --days 7
.venv/Scripts/python .claude/skills/winning_room_strategy/scripts/winning.py --this-week
.venv/Scripts/python .claude/skills/winning_room_strategy/scripts/winning.py --last-week
.venv/Scripts/python .claude/skills/winning_room_strategy/scripts/winning.py --from 2026-10-05 --to 2026-10-11
```

Options: `--show N` (lines printed, default 10; every row is saved),
`--no-save`, `--base` (default `http://127.0.0.1:8787`).

It prints the answer and saves every row that traded to
`~/.tradingagents/winning_room_strategy/runs/<yyyy-mm-dd>/<time> winners.json`
and `.csv`.

## Which dates each request means

The operator gives the days; turn them into one of these, and print the exact
dates used so a wrong reading is caught at once:

| they say | flag | dates |
|---|---|---|
| "past 2 days", "2 days", "last 48 hours" | `--days 2` | now minus 2 days to now — the table's own "or last N days" box |
| "7 days", "past week" | `--days 7` | now minus 7 days to now |
| "this week" | `--this-week` | Monday 12:00am of this week to today, this PC's days |
| "last week" | `--last-week` | the Monday-to-Sunday before this week |
| two dates | `--from` / `--to` | those days, as the table's date boxes |

## What it reads, and why it is the table

`GET /api/forecasts/room-strategies` is the route Forecast -> Room strategies
renders, row for row (`room_strategies.table`). The script sends the same
dates the table's boxes send (`RoomForecasts.tsx` `rsAsk`: seconds for "last N
days", days for the date boxes), sorts by profit like the table, and reads
every page, so each number in the answer is the one on the screen.

* **A trade counts on the day it CLOSED** (the table's rule since Oct 17,
  2026, `room_strategies.inside`).
* **Only rows that traded are asked for** (`min_profit` set very low): a row
  with no trade in the dates passes no floor, and on the screen's profit order
  the $0.00 rows of strategies that did not trade sort ABOVE every loss — this
  week the table's first ten rows were all $0.00 with no trade.
* **"Winning" = made money in the dates** (the table's Profit, above zero),
  best first. Rule sets with exactly the same numbers share one line with every
  id (eight "60% wins, 50+ trades in 7 days" sets differing only in their stop
  limit printed the same 9 trades and -1.52).
* A page whose header changes mid-read (a daily re-test landed) is refused,
  never mixed.

## What to report

Plain words, short, with their own numbers (`short-and-plain`), and the
CLAUDE.md results-table rules:

1. One line above the table: the dates read (`fmt_when`), how many room
   strategies were checked, how many traded, how many made money, where the
   measured trades end, and **$5 a trade at 20x**.
2. The table, best first, in the table's own column names: ID, Rules, Trades,
   A day, Won / lost, Win rate, Break-even, **Profit** (the dates' total),
   After reality check, Worst day, **Worst losing run** (the sum, over how many
   trades), **TP rule**, **Stop rule** (a room strategy's TP and SL are rules,
   not single prices), Room can run it. Money as the screen prints it: `+3.48`.
3. If none made money, say so in one sentence and show the three closest —
   never an empty table, never a $0.00 row that did not trade.
4. Quote ids with `#` (`#BBE0A361`).

## What the first run taught (Oct 18, 2026)

* **This week none of the 1,008 made money**: 17 traded (Oct 12 - Oct 17,
  2026), all lost; the closest were eight "60% wins, 50+ trades in 7 days"
  sets at -1.52 over 9 trades (2 won, 7 lost). Last week (Oct 05 - Oct 11) 5
  made money, best #BBE0A361, #C1133C2A and #1A582A2B at +3.48 over 3 trades.
* **Why so few trade at all**: since Oct 16-17, 2026 the daily re-test applies
  "a win must pay two losses after fees" (`watcher_policy` `min_pay` 2.0) to
  every rule set, and none of the 1,008 sets its own — only 46 of them trade
  anywhere in the saved history (Jul 01 - Oct 17, 2026). A quiet list is that
  rule, not missing data; say so when the count is low.
* **The measured trades end at the last daily re-test** (1:00am), so "today"
  is not in the numbers until the next one. The script says so when the dates
  run past it.

## Rules

* **Read only.** It never switches a strategy on, deploys, presses a job or
  touches real money.
* **Never a second calculation.** If the table and the script ever disagree,
  the table is right and the script is wrong.
* `tests/test_winning_room_strategy.py` holds the dates, the pages, the
  winners, the grouping, the empty answer, the saved files and the tab.
