# Rooms that switch on by their last 1, 2, 3 or 4 days — design (Oct 07, 2026)

## What the operator asked, word for word

`Oct 07, 2026 3:34pm` (docs/OPERATOR-ASKS.md):

> how come CC94D9FB is 41W / 87L
> could you check if this criteria is being actually followed
>
> if its followed, can you create a room strategy that has criteria that looks
> for past 1 day or 2 days or 3 days or 4 days
>
> example:
>
> * switch on at 80%+ over the last 1 days/2 days/ 3 days/4 days (create seperate room for each)
> * switch off under 80%
> * 30+ trades
> * TP wider than SL
> * SL no wider than 2%
> * every matching row in the Backtest v2 table, no limit
> * judged on the DEMO 30 DAYS figure
> * practice account only

Asked two questions, they answered:

* *"30+ trades": over 30 days or inside the 1-4 day window?* —
  *"Then it should not show any results dont you get me? Think of this just
  like in backtest tab stored strategies where ids has its own winrate snd
  number of trade but the difference is room strategy is not for a coin, its a
  room where it searches for criteria, also when i click the id of it show me
  the trade history and what it promotes and demotes each day"* — so the 30
  trades are counted INSIDE the 1-4 days, and a room that finds nothing shows
  nothing.
* *"Switch off under 80%": over the same 1-4 days, or the 30-day DEMO figure
  as written?* — *"Refer to previous prompt"* — the 30-day DEMO figure.

The audit that came first: #CC94D9FB follows its rules exactly (1,335
switch-ons since Sep 30, 2026, none breaking a rule; 866 switch-offs, every one
"30-day win rate fell under 80%"). Its rows sit AT the line (median 81.5%) and
win 32% in practice (42W / 90L, Oct 06 6:55pm to Oct 07). The new rooms test
whether a row's last few days pick better than its last 30.

## The four rooms

| room | switch on | switch off | trades |
|---|---|---|---|
| 1-day | 80%+ over its last 1 day | DEMO 30 DAYS figure under 80% | 30+ inside that 1 day |
| 2-day | 80%+ over its last 2 days | same | 30+ inside those 2 days |
| 3-day | 80%+ over its last 3 days | same | 30+ inside those 3 days |
| 4-day | 80%+ over its last 4 days | same | 30+ inside those 4 days |

All four: TP wider than SL, SL no wider than 2%, raw (every matching row, no
limit, no wait), Smart Watcher on, practice account only, $5 at 20x — the
STANDING SETUP for a rule set made a room. Each is named by its id, hashed from
its rules (`forecast_rules.rule_id`), like every room since Sep 30, 2026.

Each room's tab already carries what the operator asked to see when they click
its id: its own win rate and trades (the tiles), its trade history, and the
Watcher panel listing every switch-on and switch-off by day. Backtest a room
replays the same rules over the stored days.

## One decision taken for the operator

**A row is never switched on when the hourly check would switch it off at
once.** RCA-2026-10-01-B is this repo's rule: the switch-on judges a row on the
number the switch-off will read (#FR34HHN4 went on at 71.13% and off 33 minutes
later, twice in five hours). With two windows that means a row needs its last
N days at 80%+ with 30+ trades AND its DEMO 30 DAYS figure not under 80%.
Without it, every row strong for two days but under 80% over thirty would go on
at the first check after midnight and off within the hour, every day, trading
in between — the room's results would mostly be rows its own switch-off
rejects. The count it leaves out is printed on the room's status line, never
silent. The switch-off rule is exactly as written.

## How it works

```
GitHub (daily Backtest v2 update)            this PC
┌──────────────────────────────┐   ┌──────────────────────────────────────┐
│ backtest_strategy(...,       │   │ pair files carry t1..t4, w1..w4,     │
│   recent_from_ms=15 days,    │──▶│ p1..p4 beside t15/w15/p15            │
│   recent_windows={1..4 days})│   │ index columns (LATE_COLUMNS)         │
└──────────────────────────────┘   └──────────────────┬───────────────────┘
                                                      ▼
                              ┌───────────────────────────────────────────┐
                              │ watcher switch-on (raw: first check of    │
                              │ the day): recent_rows(days=N) nominates,  │
                              │ the pair file's tN/wN decides, then the   │
                              │ DEMO N-day figure; a row whose DEMO       │
                              │ 30-day figure is under 80% is left out    │
                              └──────────────────┬────────────────────────┘
                                                 ▼
                              ┌───────────────────────────────────────────┐
                              │ watcher switch-off (hourly): DEMO 30 DAYS │
                              │ figure under 80% → off (judge_days = 30)  │
                              └───────────────────────────────────────────┘
```

* **Measured, never estimated.** `t1/w1/p1 … t4/w4/p4` are counted by the
  engine on the same exit clock as `t15` (the minute that settled the exit).
  A row measured before the code shipped has NULL there: `unmeasured`, never
  switched on by it — exactly the 15-day rule.
* **`window_days`** may be 1, 2, 3, 4, 15 or the store's 30 — the windows a
  row is measured over. Anything else is refused by name.
* **`judge_days`** (new live rule): the window the switch-off reads. 0 (every
  existing room) = the switch-on window, so nothing changes for them. The new
  rooms set 30. Hashed into the room id only when it differs from
  `window_days`, so no existing id moves.
* **The switch-on reads the measured count; the switch-off the DEMO figure.**
  `rolling30` counts back from now while `t1`..`t4` count back from the
  backtest's last candle, so the N-day switch-on uses the row's own `tN`
  (found by the final review: a 1-day figure read 16 trades where the row
  measured 36). A row whose backtest ended more than `fresh_hours` (36) ago
  is skipped and counted.
* **One search for the four rooms** (`rows_index.recent_rows_any`): a pass
  over the 16 GB table measured 283 s.
* **Not ready is not empty.** Until the daily update has written a room's
  N-day count, and the table has filed it, the switch-on pass waits and says
  so (tried every 30 minutes), as the 15-day rooms do.
* **Backtest a room** reads `judge_days` too: the switch-off on the 30-day
  window, the switch-on on N days with the same guard.

## Out of this cut

* The Room strategies table (prompt 4's kept winners) is untouched: these are
  rooms, not research winners.
* Forecast v2's grids stay at 15/30.
* Real money: never, unless the operator ticks a room's own box.

## Guards

`tests/test_rooms_judge_on_short_windows.py`: the engine counts per window;
the shard asks for 1-4; the index files and searches them; the watcher refuses
other windows, judges on N days, switches off on 30, leaves out a row the
switch-off would drop at once and says how many; ids of existing rooms do not
move; the replay switches off on 30 days; the screen prints both windows.
