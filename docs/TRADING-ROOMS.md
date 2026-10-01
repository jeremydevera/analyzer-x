# Trading rooms (the tabs on Auto Trade)

*Written Oct 01, 2026. Part 1 is for the owner and needs no programming
knowledge. Part 2 is for whoever changes the code. Every example uses real
numbers from this machine unless it says "made-up numbers".*

---

# PART 1 — CEO EXPLANATION

## What a room is, in one paragraph

A room is a separate practice trading account with its own rules. Each tab on
the Auto Trade screen is one room. Every room has its own tiles, its own
open trades, its own trade history, its own calendar of daily profit, and its
own **Smart Watcher**: a robot that switches strategies on and off by that
room's rules. Rooms never share money figures, so you can put two sets of
rules side by side and see which one actually makes money.

## Why rooms exist

On Sep 29, 2026 you asked: *"when i switch to B52662ED i should see its own
tiles, own live trade, own demo trade, own calendar pnl, in short it has its
own room/ profile"*. Before rooms there was one account, so testing a second
set of rules meant replacing the first one. Rooms let several rule sets run
at the same time on the same market, each keeping its own score.

## The rooms you have today

All of them trade **practice money only**, $5 per trade at 20x (so each trade
moves $100 of coin). In every room the "close it, I won" price (TP) must be
farther away than the "close it, I was wrong" price (SL), and the SL may be
no wider than 2%.

| tab | judges a strategy on | switches it ON at | switches it OFF under | needs at least | right now |
|---|---|---|---|---|---|
| **Main** | last 30 days | 90% wins | 90% | 20 trades | 67 rows on |
| **#55D32617** | last 15 days | 70% wins | 70% | 50 trades | waiting for the 15-day counts |
| **#4FC03172** | last 30 days | 70% wins | 70% | 50 trades | 2,878 rows on |
| **#B2404C0B** | last 15 days | 75% wins | 75% | 50 trades | waiting for the 15-day counts |
| **#6B08FF64** | last 15 days | 80% wins | 80% | 30 trades | waiting for the 15-day counts |
| **#CC94D9FB** | last 30 days | 80% wins | 80% | 30 trades | 539 rows on |

The tab name IS the rule set's ID from the research page
(https://claude.ai/artifact/UUNAie322TPyjJU8MaZtQo), so you can always look a
room up there.

### What each room did in the research

The research tested 144 rule sets over 4,585,414 strategies. Each rule set
was picked on July–August and then graded on September (Sep 01 to Sep 30,
2026 12:00pm), the same way a new room will meet a month it has never seen.

| room | September profit | won / lost | win rate | trades | most open at once | worst losing run | July–August profit |
|---|---|---|---|---|---|---|---|
| #55D32617 | **+$4,888.85** | 10,675 / 5,551 | 65.8% | 16,226 | 97 | −$34.45 over 24 trades | +$2,174 |
| #4FC03172 | **+$4,967.43** | 10,305 / 5,040 | 67.2% | 15,345 | 106 | −$30.07 over 23 trades | +$1,624 |
| #B2404C0B | **+$3,597.61** | 6,087 / 2,582 | 70.2% | 8,669 | 64 | −$24.80 over 17 trades | +$1,738 |
| #6B08FF64 | **+$2,687.62** | 3,839 / 1,592 | 70.7% | 5,431 | 51 | −$23.41 over 17 trades | +$1,640 |
| #CC94D9FB | **+$2,317.48** | 3,382 / 1,241 | 73.2% | 4,623 | 47 | −$15.46 over 12 trades | — |
| Main's rules | **+$444.36** | 468 / 156 | 75.0% | 624 | 15 | −$21.47 over 15 trades | — |

Past results are not a promise. The rooms exist so the next month answers
which of these holds up.

## How one day works

```
┌──────────────────────────────────────────────────┐
│ 1. 9:13am EVERY DAY — GitHub re-tests every      │
│    strategy in Backtest v2 on the last 30 days,  │
│    and counts its last 15 days separately        │
│    e.g. #QHB5UVQP ALUMINUM 15m (TP 0.4% SL 0.3%):│
│    70 trades, 70 won, 100%                       │
└────────────────────────┬─────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────┐
│ 2. RESULTS LAND on this PC over the next hours   │
└────────────────────────┬─────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────┐
│ 3. EACH ROOM'S WATCHER, once a day, reads the    │
│    whole table and keeps every strategy that     │
│    passes ITS rules — no daily limit             │
└────────────────────────┬─────────────────────────┘
                         ▼
                 ┌───────────────┐
                 │ 4. PASSES?    │
                 └───┬───────┬───┘
                 yes │       │ no
                     ▼       ▼
┌────────────────────────┐ ┌────────────────────────┐
│ 5a. SWITCHED ON in     │ │ 5b. left out           │
│ that room's Deployed   │ │                        │
│ list, practice only.   │ │                        │
│ #QHB5UVQP went on in   │ │                        │
│ #CC94D9FB at Sep 30,   │ │                        │
│ 2026 8:22pm            │ │                        │
└───────────┬────────────┘ └────────────────────────┘
            ▼
╔══════════════════════════════════════════════════╗
║ 6. THE ROOM'S RUNNER watches the live price and  ║
║    opens a $5 x 20x practice trade when the      ║
║    strategy's signal fires                       ║
╚════════════════════════┬═════════════════════════╝
                         ▼
┌──────────────────────────────────────────────────┐
│ 7. EVERY HOUR the watcher re-checks each row it  │
│    switched on. A row that drops under the line  │
│    is switched off; its open trade still runs to │
│    its own TP or SL                              │
└──────────────────────────────────────────────────┘

IF ANYTHING FAILS
- GitHub's test is late or the PC was off → it runs as soon as the PC is back
  and 24 hours have passed
- the results list is busy (being rebuilt), or a 15-day room's counts are in
  the coin files but not yet in the table → the room waits and tries again
  every 30 minutes
- a coin is delisted → its rows are switched off
- you untick Smart Watcher → nothing is added or removed; trades keep running
```

## 15 days vs 30 days — the example you asked about

*(made-up numbers)* A room's rule is "90% wins over the last 15 days".

| | last 30 days | last 15 days |
|---|---|---|
| Bitcoin strategy | 90% | 80% |

**It is NOT switched on.** A 15-day room reads only the last 15 days, and
80% is under 90%. The 30-day figure is never used in its place.

The reverse also holds: a strategy at 70% over 30 days but 95% over its last
15 days IS switched on in a 15-day room, because it is doing well now.

Why the 15-day rooms were empty at first: until Oct 01, 2026 the daily test
only wrote 30-day numbers. On Sep 30, 2026 it was taught to count the last 15
days too, so #55D32617, #B2404C0B and #6B08FF64 start picking strategies once
the Oct 01, 2026 9:13am test has landed **and the Backtest v2 table has been
rebuilt with it** (about an hour after the run comes home). Until then their
status line says *"no Backtest v2 row carries its last-15-day count yet"*,
then *"... in the coin files but not yet in the Backtest v2 table"* —
"checking again every 30 minutes" either way. (Before Oct 01, 2026 the room
looked only at the coin files and would have searched the still-old table,
found nothing, and lost the whole day — RCA-2026-10-01-A.)

## Why a room can switch on fewer rows than it found

#CC94D9FB's first check found **1,511** strategies with 80%+ wins, 30+ trades
and a stop of 2% or less. **972** of them had the TP exactly equal to the SL
(for example 1% and 1%), and your rule is "TP wider than SL", so those were
left out. **539** passed every rule and all 539 were switched on. The status
line says exactly that: *"... 539 pass every rule (972 fail one, most often
TP is not wider than SL)"*.

## What you see on each tab

* **The tab row** — Main and the five rooms. The small **i** beside a name
  opens that room's rules, read from its watcher, so it shows what the room
  really does.
* **Tiles** — that room's money only (open trades, today, all time).
* **Deployed** — every strategy switched on in that room. `DEMO W/L · $` is
  wins, losses and dollars since the row was switched on; `% 30 DAYS` is its
  win rate over the last 30 days (the test, then its practice trades).
* **Watcher** — what this room's watcher switched on and off, and why, page
  by page; the **Smart Watcher** box; the **Watcher trades real money** box.
* **Trade history and calendar** — that room's trades and daily profit only.

## Real money

Every room starts on practice money. Real money is used **only** if you tick
**"Watcher trades real money"** inside that room. From then on each row it
switches on trades your real MEXC account too. Unticking it takes real money
off every row that room switched on and keeps their practice half.

One coin can hold only one real position on MEXC across ALL rooms, because
MEXC merges same-coin positions into one. If two rooms want to buy the same
coin with real money, the first one gets it and the second is refused, with
the reason written in its trade record.

## Turning a room off

When you say a room is **off**, its tab disappears completely (your rule,
Oct 01, 2026). Behind the scenes:

1. every practice row in it is switched off,
2. its watcher is switched off for good,
3. its open practice trades still finish at their own TP or SL,
4. its history stays on disk.

On Sep 30, 2026 #DC57174E (223 rows), #CC8DC54C (289) and #B52662ED (2,433)
were turned off this way: 2,945 practice rows switched off, Main untouched.

## Questions that have already been asked (and the standing answers)

| you say | it always means |
|---|---|
| "deploy the table" | one room per rule set, named by its ID, practice only |
| "which money?" | practice; real only through the room's own box |
| "undeploy my current" | switch off every row in every room except Main |
| "off" | remove the tab completely |
| "is the room empty a bug?" | check its status line first; a 15-day room waits for the 15-day counts |

---

# PART 2 — TECHNICAL EXPLANATION

## Moving parts

```
┌────────────────────────────────────────────────────────────┐
│ webapp/src/lib/api.ts  PROFILES (the tabs) + setProfile()  │
│ fetchLaned() sends  X-TA-Profile: <id>  on /api/trade/*    │
│ and /api/ledger only; Main sends nothing                   │
└─────────────────────────────┬──────────────────────────────┘
                              ▼
┌────────────────────────────────────────────────────────────┐
│ tradingagents/api.py  _ProfileMiddleware                   │
│ ?profile= or the header → profiles._CURRENT (ContextVar);  │
│ unknown id = 404, never served as Main                     │
└─────────────────────────────┬──────────────────────────────┘
                              ▼
┌────────────────────────────────────────────────────────────┐
│ every route reads/writes through auto_trader._pp(PATH)     │
│ Main  → ~/.tradingagents/<file>                            │
│ room  → ~/.tradingagents/profiles/<ID>/<file>              │
└─────────────────────────────┬──────────────────────────────┘
                              ▼
╔════════════════════════════════════════════════════════════╗
║ ONE RUNNER PROCESS PER ROOM  (TA_PROFILE=<ID>)             ║
║ ONE API for all rooms; supervisor restarts each runner     ║
║ whose auto_trade.WANT exists (api.py _watch, every 30 s)   ║
╚═════════════════════════════┬══════════════════════════════╝
                              ▼
┌────────────────────────────────────────────────────────────┐
│ ONE WATCHER STATE PER ROOM  (api.py _watcher_loop, 60 s):  │
│ for pid in profiles.ids(): with using(pid): sw.tick()      │
└────────────────────────────────────────────────────────────┘
```

### Files

| file | role |
|---|---|
| `tradingagents/profiles.py` | `BUILTIN` (id, name, rules, `retired`), `ids()`, `shown()`, `retired()`, `current()`, `using()`, `path()`, `NO_LIMIT` |
| `tradingagents/auto_trader.py` | `_pp()`, `_seed_profile_settings()` (copies Main's settings minus `_ROW_KEYS`), `start_runner()` (passes `TA_PROFILE`), `other_profile_holding()`, `cross_commit()` / `others_committed()` |
| `tradingagents/strategy_watcher.py` | per-room state (`_state_path`, `_log_path`), `_seed()`, `cfg_of()`, `mode_of()`, `set_live()`, `set_mode()`, `set_cfg()`, `retire_room()`, `consider()`, `_on_pass()`, `_off_pass()`, `_judged()` |
| `tradingagents/watcher_policy.py` | `DEFAULTS`, `passes_on()`, `judge()`, `pick()` — the ONE rule set shared with the replay and the research |
| `tradingagents/watcher_candidates.py` | `raw_candidates()`, `_raw_recent()`, `recent_measured()`, `window_of()`, `_fresh()`, `fresh_row()` |
| `tradingagents/rows_index.py` | `COLS` (+ `t15`,`w15`,`p15`), `LATE_COLUMNS`, `_late_columns()`, `recent_rows()` |
| `tradingagents/rolling30.py` | `figure(slot, window_ms=)` — the switch-off figure |
| `tradingagents/backtest_report.py` | `RECENT_DAYS = 15`, `RECENT_FIELDS`, `recent_fields()` |
| `.github/scripts/sweep_shard.py` | v2 rows carry `t15`/`w15`/`p15` |
| `webapp/src/components/trade/AutoTradeScreen.tsx` | tabs, the "i" popup, `key={room}` remount |
| `webapp/src/components/trade/WatcherPanel.tsx` | `rules()` (the popup and the panel use the same text), live box, paging |

### A room's folder

```
~/.tradingagents/profiles/CC94D9FB/
  auto_trade.json            settings (rows, books, margins)
  auto_trade_state.json      open positions
  auto_trade_ledger.jsonl    trade record
  auto_trade.log / .pid / .lock / .WANT
  auto_trade_state.lock
  deployments.jsonl          when each row was switched on (local_history._deploy_log)
  strategy_watcher.json      mode, cfg, live, pass timestamps
  strategy_watcher.jsonl     every decision
```

## A room's rules

`profiles.BUILTIN[i]["rules"]` seeds `strategy_watcher.json` the first time
the room's watcher reads a missing state file (`_seed`: `mode "act"`,
`live False`). After that the STATE FILE is the truth; `GET
/api/trade/profiles` reads it, so the popup shows what runs.

```python
def _rule(window, line, trades):
    return {"on_winrate": line, "off_winrate": line, "min_trades": trades,
            "tp_rule": ">", "max_sl": 2.0, "window_days": window, **NO_LIMIT}
# NO_LIMIT = max_new_per_day 0, max_slots 0, max_per_coin 0, raw True  (0 = no limit)
```

`tests/test_rooms_judge_on_15_days.py::test_each_room_is_its_rule_set_by_id`
recomputes each id with `watcher_research.rule_id()` over `scenarios5()` and
compares every rule, so a room can never drift from the research row it is
named after.

`window_days` is a live rule since Sep 30, 2026: `set_cfg` accepts exactly
`backtest_report.RECENT_DAYS` (15) or `store_window_days()` (30) and refuses
anything else with "must be one of".

## The watcher's two passes

| pass | when | does |
|---|---|---|
| switch-on (`_on_pass`) | once per local day; RAW rooms at any hour, others from `ON_HOUR` (12) | `_candidates()` → `passes_on()` → `pick()` → `_try_picks()` → `_arm()` in one `_write_settings` |
| switch-off (`_off_pass`) | every `OFF_EVERY_S` (1 h) | each watcher slot and each hand-armed v2 practice row: `_fresh_row()` → `_judged()` → `judge()` → `_disarm()` |

A pass that cannot read its list returns `not_ready`; it is retried every
`RETRY_S` (30 min) and never counted as the day's pass.

## The 15-day path, end to end

```
backtest_strategy(..., fine=minutes, recent_from_ms=last_candle - 15 d)
   counts trades whose exit (the minute, else the exit bar's open)
   >= recent_from_ms  →  result["recent"] = {trades, wins, profit}
        ▼
sweep_shard.py (v2 / RES "1m")  →  row += br.recent_fields(r)
   {"t15": 12, "w15": 5, "p15": -2.11}     (KII 1h macddiv tp0.6 sl0.3,
                                             run here Sep 30, 2026)
        ▼
cloud_sweep.land_rows → market_sweep.save_pair_rows   (keys kept as-is)
        ▼
rows_index.index_pair → _late_columns(con) adds t15/w15/p15 if missing
        ▼
watcher: _candidates(cfg) → window_of(cfg) == 15 → raw_candidates → _raw_recent
   1. recent_measured(): do the 5 newest v2 pair files carry "t15"?
      no  → not_ready ("checking again every 30 minutes")
      recent_filed(): does rows.db have the t15 column AND are those 5
      newest files filed in `pairs` at their current mtime/size?
      no  → not_ready (RCA-2026-10-01-A: the daily run lands files live and
            the table is rebuilt only after its collect)
   2. rows_index.recent_rows(min_trades, min_winrate, max_sl):
      SELECT * FROM rows WHERE t15 >= ? AND w15*100.0 >= ?*t15
        AND tp > sl AND (sizing='flat' OR sizing IS NULL) [AND sl <= ?]
   3. _fresh(..., window=15): trades/wins/winrate/profit = t15/w15/p15
        ▼
switch-off: _judged(slot, fresh, now, 15)
   → rolling30.figure(slot, window_ms=15 days)
     (backtest trades to the last candle + practice exits after it)
```

Rules that keep it honest:

* **A row without the count is `unmeasured`** (0 trades), so it can never be
  switched on by it, and a running row that is unmeasured is KEPT and
  reported, never switched off on a 30-day number relabelled 15.
* **`recent_from_ms=None` leaves the engine result byte-identical**
  (`test_without_the_window_the_result_is_unchanged`).
* **Every index writer adds the late columns first** — a job's own filing
  (`db_jobs`, `learn_collect`) may never have run `ensure()` with this code.

Not measured yet: how long `recent_rows` takes over the full v2 table (no
index carries `t15`; it is one pass over ~51.7M rows once a day per 15-day
room). Measure it on the first real pass before adding an index.

## Safety between rooms (real money)

| guard | where | what |
|---|---|---|
| one real position per coin across rooms | `auto_trader.other_profile_holding()` | claims the coin under a machine-wide lock for `CLAIM_S` (15 min) before a real entry |
| shared wallet | `cross_commit()` / `others_committed()` | margin another room committed in the last `COMMIT_WINDOW_S` (180 s) counts against this room's capital gate |
| orphan sweep | runner | never adopts another room's coin |
| PANIC | runner/API | closes only the room's own positions (Main also true orphans) |
| screens | `api._own_exchange_positions` | a room lists only its own real positions |
| live switch | `strategy_watcher.set_live()` | arms `["paper","real"]` and records `meta["real"]`; off removes only the real it armed |

## Turning a room off (retire)

```python
from tradingagents import profiles, strategy_watcher as sw
with profiles.using("B52662ED"):
    sw.retire_room()   # → {"switched_off": 2433, "real_kept": []}
```

then in `profiles.py` mark it `retired` and delete it from `PROFILES` in
`webapp/src/lib/api.ts`. `mode_of()` returns `"off"` for a retired room
whatever its state file says; `profiles.shown()` (the tabs and `GET
/api/trade/profiles`) leaves it out; `profiles.ids()` keeps it so the
supervisor keeps its runner alive to finish open practice trades. A row
holding REAL money is never taken off by `retire_room()` — it is listed in
`real_kept` for the operator.

## Adding a room

1. Add `{"id": "<RULE ID>", "name": "#<RULE ID>", "rules": _rule(w, line, n)}`
   to `profiles.BUILTIN` (before the retired ones — that is the tab order).
2. Add `{ id: "<RULE ID>", name: "#<RULE ID>" }` to `PROFILES` in
   `webapp/src/lib/api.ts` (a test holds the two equal).
3. Add the id to `TABLE` in `tests/test_rooms_judge_on_15_days.py`.
4. Commit, push, restart the site (`python start.py start`, ~3–5 min dark —
   say so first).
5. Start its runner once, after the API runs the new code:
   ```python
   with profiles.using("<RULE ID>"):
       at.start_runner()
   ```
   The supervisor keeps it up from then on.

## API

| call | body / query | does |
|---|---|---|
| `GET /api/trade/profiles` | — | every SHOWN room: mode, live, cfg, window_days, rows |
| `GET /api/trade/watcher?page=N` | header `X-TA-Profile` | that room's watcher status, decisions page N |
| `POST /api/trade/watcher` | `{"mode": "off"\|"preview"\|"act"}` | Smart Watcher box |
| `POST /api/trade/watcher` | `{"live": true\|false}` | Watcher trades real money box |
| `POST /api/trade/watcher` | `{"cfg": {"on_winrate": 75.0}}` | change a live rule |

## Tests

* `tests/test_rooms_judge_on_15_days.py` — engine count, shard fields, index
  search, `_fresh` window, `set_cfg` window, rolling window, rooms = research
  ids, retired rooms, tabs = `shown()`, `retire_room`, late columns, the
  not-ready wait, the "pass every rule" status line.
* `tests/test_every_profile_is_its_own_room.py` — paths, header, cross-room
  real-money guards, popup.
* `tests/test_the_strategy_watcher.py` — the passes, live switch, preview.

## Incident record

* `docs/RCA.md` RCA-2026-09-30-C — "1,511 meet the criteria" over 539
  switched on (TP equal to SL counted before the strict rule).
* `docs/RCA.md` RCA-2026-09-29-F — why the research only trusts rule sets no
  looser than the data they were written from.
