# RCA log — every bug that was fixed, and what now stops it

Operator, Sep 09, 2026: *"list this in rca to prevent this from happening in
the future / all fixes should be listed in a file so you will remember what
where the fixes"*.

**One entry per bug that got fixed. Newest first. Never delete an entry.**
Ids are `RCA-<date>-<letter>`, the next free letter for that day — read the
file first, because two sessions took `G` within an hour of each other on
Sep 09, 2026, and `tests/test_rca_log.py` now refuses a repeated id.
The `rca-log` skill (`.claude/skills/rca-log/`) is ALWAYS ON and writes the
entry in the same commit as the fix. `tests/test_rca_log.py` holds the shape.

**Two summaries first, then the seven questions** — operator, Sep 10, 2026:
*"add this ceo style findings in documentation so it wont happen again also add
technical/dev documentation as well"*. They asked because the entries had become
unreadable to them: engineer prose about swallowed defaults and index write
amplification, when what they needed was *"your filter said zero because it
could not check, and it now says so"*. Both readers are real, and neither is
served by the other's version. Entries dated **on or after Sep 10, 2026** carry
both; the older ones keep the seven fields alone and are not being rewritten.

| field | why it is there |
|---|---|
| **CEO** | 3 bullets, no code and no file names: what you saw or lost, why in one plain sentence, what stops it now |
| **DEV** | 3 bullets, exact: the failing call path (`file:line` → function → the wrong value), the invariant that broke named as a rule, the guard by test name |
| **SAW** | what was on the operator's screen, in their words where possible |
| **TIMELINE** | numbered, real timestamps and real numbers (`bug-scenario`) |
| **ROOT CAUSE** | the line that was wrong, not the symptom |
| **WHY IT WAS NOT CAUGHT** | the missing or too-narrow check — this is the part that prevents the repeat |
| **COST** | money lost, money risked, or "none" — say which |
| **FIX** | the commit |
| **GUARD** | the test that now fails if it comes back |

Older incidents, before this file existed, live in the rules of
`CLAUDE.md` and in `docs/INCIDENT-2026-08-12-BDX.md`. Every commit message in
this repo is also part of the record.

---

# WHERE THE BACKTEST STANDS — Sep 10, 2026, in plain words

The operator, mid-session: *"I dont even know what you are doing"* and *"We did
the github backtest already right? Now what are you doing?"*. Fair. This is the
whole picture without engineering language.

**The measuring was done. The filing now is too, as of `7:08pm`.**

There are three steps between pressing UPDATE ALL BACKTESTS and seeing results
on screen. Only the third had been failing.

| step | who does it | state |
|---|---|---|
| 1. Measure on GitHub's 20 machines | the button, via `_run_btupdate` | **works by itself** |
| 2. Bring the results back to the PC | `cloud_autopilot` collects them | **works by itself** |
| 3. File them into the searchable list | a background indexer | **was the broken one — 100% as of Sep 10, 2026 7:08pm** |

Steps 1 and 2 have never needed a person. The store grew from 51,943,352 to
**52,348,156 rows** during this session with nobody touching it — that is
proof they run on their own. Everything done by hand this session was step 3.

**What "filing" means.** A result is measured into a per-pair file
(`BTC-15m.json`). It is not searchable until its rows are copied into
`rows.db`, the index the Stored strategies screen reads. Until then the result
exists on disk and no filter can find it.

**WHERE IT STANDS, `Sep 10, 2026 7:08pm` — DONE.** The searchable list was
rebuilt from scratch and swapped in. Measured, not estimated:

| | before | after |
|---|---|---|
| coins searchable | 4,612 of 5,365 (**86%**) | **5,367 of 5,367 (100%)** |
| rows | 52,348,156 | **96,313,064** |
| file | 34.69 GB, 38.8% holes | **41.94 GB, packed** |
| filing speed | 0.25–0.86 coins/min | **70.3 coins/min** |
| `behind` | 753 coins | **0** |

The run, phase by phase, on a mechanical G: — these are the numbers
`CLAUDE.md`'s bulk-load rule now carries:

| phase | measured |
|---|---|
| load 5,367 pair files (no indexes) | 68 min, **70.3 pairs/min** |
| `rows_pair` (96M **text** keys) | **48 min** |
| `rows_profit` | **14 min** |
| `rows_coin` + `rows_winrate` | ~27 min together |
| pre-swap check over 41.94 GB | **95 min** (estimate had been 170) |
| whole run | **252 min**, 2:56pm → 7:08pm |

The old file is kept as `rows.before-rebuild.db`; nothing was deleted, and
347.4 GB is free on that drive.

**What still needs to happen by itself**

* **The wide filter indexes are building now** (`rows_pr2`, then `rows_wr4`,
  detached). Until they finish, a win-% filter over the WHOLE store answers
  *"a win % floor of 90 over the store needs more than 20s ... the wide
  win-rate index is still being built"* — a refusal with a reason, which is
  RCA-F's fix doing its job. A coin filter already answers in **0.60 s**
  (BTC: 120,604 rows) and the first page in **0.04 s**.
* **84 coins are stale** — their pair files gained rows during the four hours
  the rebuild ran. The indexer picks those up on its own; `behind` is 0, so
  nothing is missing, they are just not the newest.
* The app was started on this code at 7:12pm and answers: `/api/strategies`
  200, `/api/backtest/storage` 200.

**Why step 3 kept breaking — SEVEN separate faults, all found today**

1. It went silent for 13 hours behind a database lock and nothing anywhere said
   why (**RCA-C**). Fixed: the error is kept and shown, the indexer writes a
   log, the button refuses instead of pretending.
2. It was doing 3.5x the work it was designed for — 14 indexes maintained per
   row where the design assumed 4 (**RCA-E**). Fixed, but see 3.
3. The fix for 2 dropped the indexes the operator's own win-% filter needs, so
   their filter stopped working (**RCA-F**). Fixed: the drop is opt-in and off
   by default, and a missing index can no longer read as "nothing matches".
4. Compaction — the first attempt at the repair — reached 90% of its copy and
   stopped, and no root cause was ever established (**RCA-G**). Abandoned in
   favour of the rebuild. Nothing was lost: it never swaps until the copy
   verifies.
5. **The rebuild searched the whole file before filing each coin** — 39.9
   seconds per coin, measured, for rows that were not there, because the delete
   it does first has no index to delete by (**RCA-K**). That is the real reason
   filing kept getting slower, and it is what "one coin every 70 seconds" and
   "one coin every 305 seconds" both were. **Fixed: 0.25 → 72.0 coins a
   minute.**
6. The rebuild also raced the collect for one disk, because its gate asked "can
   I write?" instead of "am I the only one working?" (**RCA-I**). Fixed: it
   waits, and names the job it is waiting for. A real effect, but not the cause
   of the slowness — that was 5.
7. Two of my own repairs then went quiet or overpriced: a resume check that
   would have taken **9 hours** on the finished file to save 30 minutes
   (**RCA-J**), and phases that ran for minutes while the progress file still
   showed the previous run's numbers (**RCA-J**, **RCA-K**). Both fixed: the
   check reads a 450-row summary, and every long phase publishes while it runs.

**What is fixed and pushed**

* the 13-hour silence, with the log and the honest refusal (`4300962c80f`)
* the 14-vs-4 index write amplification (`aeb6357ebe4`)
* a missing index reading as "nothing matches" (`ac62504a8cb`)
* the sweep window: 30 days by default and the 1-year option removed, after a
  full-year sweep of the whole market was heading for 4.7 days
  (`4f18962a5b5`, `dc1a41c26d9`) — that run was cancelled
* compaction built, with verify-before-swap (`7f9a2773650`) — and it does not
  work; the rebuild replaced it (`84664a06c44`)
* the rebuild waits for a writing job, and resumes instead of starting over
  (`24207ed4569`)
* the resume check reads the summaries, not the whole file (`b3d307d5ce6`)
* **no per-pair scan: 0.25 → 62.3 then 72.0 coins a minute** (`052d4462358`,
  `6e3e112f4d5`)
* the pre-swap check publishes while it walks 32 GB (`4095c13354c`)

**What is NOT fixed, stated plainly**

* **the rebuild has not finished yet.** It is at 33% and moving; the last step
  is a check of the whole 32 GB file before it replaces the live one, and
  **nothing has measured that check at this size** — 5 minutes at the
  106 MB/s this disk does sequentially, hours if it reads the way RCA-J
  measured. It now publishes every 5 seconds, so it can be told apart from a
  stall.
* **`forget_pairs` still holds one transaction across every pair**, so a
  delisted-coin cleanup freezes filing until it ends (named in RCA-C, still
  true).
* **24.8 GB of dead files** (`rows.prev.db`, `rows.old.db`) are read by nothing
  and could be deleted — plus a fresh 32 GB `rows.before-rebuild.db` when the
  swap happens. G: has 355.7 GB free, so this is tidying, not urgent, and it is
  the operator's data to keep or drop.
* **the app is still serving code from before today's fixes.** Restarting it
  runs `taskkill /T`, which would kill the rebuild, so it waits until the
  rebuild is done.

---

## RCA-2026-09-24-G — three deployed rows showed ids that are in no store: a signal name with an underscore was cut at its first `_`

**CEO**

* Since Sep 16, 2026 1:54am the deployed-strategies table showed three of
  your FASTSTOCK rows as #GYWZS995, #T724QASK and #3FBZAH3B. Those ids
  exist nowhere, so searching them found nothing. Their real ids are
  #KDY5M3LQ, #46SGBAHD and #HQH72A8L. None of the three ever traded (534
  refusals, 0 trades), so no trade carried a wrong id.
* Why: the app read a strategy's signal out of its name by cutting at the
  first underscore, so cf_soup1 became cf. 57 signal types have an
  underscore in their name.
* What stops it now: one reader that knows every signal name, used by every
  screen. A test checks every strategy's id against the rule the runner
  really trades, and another fails if any part of the app cuts a name by
  itself again. It was found while deploying your 1,473 Backtest v2 ids,
  before it could mislabel the 30 new slots (58 of your ids) whose signal
  has an underscore — #R88RRLU4 (SOL 4h cx_first) would have shown as
  #TBRL24VM.

**DEV**

* `api.py:row_id_for` → `local_history._sig_of(key)` returned
  `key.split("_")[0]`; the same split was copied into `api.backtest_deployed`,
  `strategy_report.build` and `market_sweep.deployed_combos`, which also took
  the TIMEFRAME from `bits[1]` — `soup1`, `veto`, `rt`, `sp`, `fvg`, or
  skipped `mom6`/`trend50` outright (8 keys read wrong in all, so the sweep's
  "a deployed combination is never skipped" rule could not match them).
* Invariant broken: **a row id is hashed from the combination's own fields**
  (`deploy-by-id`), and the id's signal must be the rule `signal_for`
  dispatches (the longest registered name the key starts with). One parser,
  never four copies; the id is a LABEL (`label-must-match-data`).
* Guard: `tests/test_an_underscored_signal_keeps_its_id.py` (62) — fixed
  points #KDY5M3LQ / #46SGBAHD / #HQH72A8L, all 57 underscored names, the
  real dispatcher spied for every `STRATEGY_SPECS` key, `deployed_combos`,
  and an AST check that no module calls `.split("_")` outside `_sig_of`.
  61 of the 62 are red on the pre-fix tree.

**SAW** — not reported; found by the deploy of the operator's 1,473 ids
(*"undeploy all deployed ids in strategies deployed / then deploy these
ids"*), whose read-back checks that every armed slot prints the id it runs
as.

**TIMELINE**

1. `Sep 16, 2026 1:54am` — the 127-row deploy arms `cf_soup1_1h_sl25tp1`,
   `cf_soup1_1h_sl3tp1` and `cx_veto_1h_sl3tp1` on FASTSTOCK, practice
   account.
2. From then on the table hashes them with signal `cf` / `cx`:
   #GYWZS995, #T724QASK, #3FBZAH3B. The v1 store holds none of those; it
   holds #KDY5M3LQ (44 trades, 97.73%, +$30.82), #46SGBAHD (44 trades,
   100%, +$34.32) and #HQH72A8L (39 trades, 100%, +$30.42).
3. `Sep 16 → Sep 24, 2026` — 534 `gate_blocked`, 0 entries on the three
   keys.
4. `Sep 24, 2026 ~7:00pm` — resolving the 1,473 ids: 15 of their 67 signal
   types carry an underscore; after the refusals 30 armed slots (58 ids) use
   one. The fixed parser changes the reading of exactly the three broken
   keys among the 180 that existed, and no other.

**ROOT CAUSE** — a signal name was parsed out of a strategy key by splitting
on `_`, while 57 registered signal names contain `_`.

**WHY IT WAS NOT CAUGHT** — every id test hashes a one-word signal
(`willr14`, `ote`, `keltner`, `mom15`), and the Sep 16 deploy proved each key
reached a real rule in `signal_for` — the RUNNER's reading — without ever
comparing it with the ID's reading of the same key. Two readers of one name,
each tested alone; the list of names was never run through either.

**COST** — none in money: the three rows never traded. Three ids on screen
that led nowhere for eight days.

**FIX** — this commit.

**GUARD** — `tests/test_an_underscored_signal_keeps_its_id.py`.

---

## RCA-2026-09-24-H — MERGE INTO THIS PC on a Backtest v2 run would have said "Internal Server Error" whenever another job had the disk

**CEO**

* NEVER HAPPENED YET. Pressing MERGE INTO THIS PC on a finished Backtest v2
  run while another job (an update, a download) was using the disk would
  have shown "Internal Server Error" instead of saying which job was busy.
* Why: the button was taught on Sep 22 to hand v2 results to the v2 collect
  job, and that hand-over did not catch the "another job has the disk"
  refusal the way every other button does.
* What stops it now: it answers with the busy job's name, and a test drives
  exactly that case. It was found by the full test suite during the
  RCA-2026-09-24-E fix, not by you.

**DEV**

* `api.cloud_merge` (`tradingagents/api.py`, the `res == "1m"` branch added
  in 1af413fbd358) called `dj.start("collect_v2", …)` bare; `db_jobs.start`
  raises `JobBusy` while any disk job runs, which became a 500.
* Invariant broken: **a busy machine is a 409 with the holder's name, never a
  500** — the rule `test_a_busy_machine_is_not_a_crash.py` has enforced over
  every route since Sep 17, 2026. Fixed with `except dj.JobBusy` → 409.
* Guard: `tests/test_a_busy_machine_is_not_a_crash.py::test_no_route_starts_a_job_without_catching_it`
  (found it) and
  `tests/test_the_panel_sees_every_accounts_machines.py::test_merging_a_v2_run_on_a_busy_machine_is_a_409_with_the_reason`.

**SAW** — nothing on screen; the full suite, Sep 24, 2026 ~7:10pm:
`these start a job outside any except JobBusy, so a busy machine answers
500: line 3056: pid = dj.start("collect_v2", …)`.

**TIMELINE**

1. `Sep 22, 2026 ~11:55pm` — 1af413fbd358 routes a v2 MERGE to the
   `collect_v2` job; only the nearest suites were run, and the route-wide
   JobBusy guard was not among them.
2. `Sep 22 → Sep 24` — the guard is red on `main` for two days; nobody runs
   the full suite, and no v2 MERGE is pressed while a job is busy (0 times).
3. `Sep 24, 2026 ~7:10pm` — the full suite run for RCA-2026-09-24-E stops on
   it; fixed and guarded the same hour.

**ROOT CAUSE** — a new job door written without the busy-machine catch every
other door has.

**WHY IT WAS NOT CAUGHT** — the guard that catches exactly this existed and
was red; only the suites nearest the change were run, so a failing test two
directories away went unseen for two days. **Before calling a change done,
run the whole suite, not the neighbourhood.**

**COST** — none: it never fired.

**FIX** — this commit.

**GUARD** — `tests/test_the_panel_sees_every_accounts_machines.py::test_merging_a_v2_run_on_a_busy_machine_is_a_409_with_the_reason`.

---

## RCA-2026-09-24-F — the portfolio forecast crashed on the way to reporting its own failure

**CEO**

* If your portfolio forecast ever failed, instead of the plain sentence it was
  written to show you — *"the replay raised ..."* — the page would have
  crashed outright.
* Why: the line that writes the failure into the log used a name that does not
  exist anywhere in that file, so the error handler broke while handling the
  error.
* What stops it now: the name is defined, and the whole project is checked for
  undefined names again — which found a second one, in a test that could never
  have run the check it was written for.

**DEV**

* `api.py:3693` called `logger.exception("portfolio forecast failed")` inside
  the `except` of `portfolio_forecast`, and `api.py` has no `logger`, no
  `logging` import and no other reference — so the handler raised `NameError`
  instead of returning the `{"why": ...}` dict written on the next line.
  Added `Sep 22, 2026` in commit `aa29e8f6571c`.
* Invariant broken: **the error path is code too.** A handler that has never
  been executed is not a handler, and this one could only run on the day it
  was needed.
* Guard: `ruff` F821 across the whole repo is green again, and it also caught
  `tests/test_the_panel_sees_every_accounts_machines.py:148` using `pytest`
  with no import — that test's `pytest.fail("a v2 run may not land here")`
  would itself have raised `NameError`, so the assertion it exists to make
  could never have fired.

**SAW** — nothing. Found `Sep 24, 2026` by a repo-wide lint run while
switching v1 off, not by anything failing.

**TIMELINE**

1. `Sep 22, 2026` — `aa29e8f6571c` adds the `logger.exception` call.
2. It sits in an exception handler, so it runs only when the forecast fails.
3. `Sep 24, 2026` — `ruff check .` reports `F821 Undefined name logger` at
   `api.py:3693`, and a second F821 in a test.
4. Fixed: `logging` imported, `logger = logging.getLogger(__name__)` defined
   beside the other module-level setup; `import pytest` added to the test.

**ROOT CAUSE** — a name used only on a failure path, in a module that never
defined it.

**WHY IT WAS NOT CAUGHT** — nothing exercises the forecast's failure branch,
and a `NameError` on a path nobody takes is invisible to every test that takes
the other path. Lint is the only thing that reads code it does not run, and
the repo's lint had been red for days with 34 unrelated errors — so the ONE
error that was a real crash was buried among import-sort complaints nobody was
reading. **A lint run that is allowed to stay red stops being a signal.**

**COST** — none. The forecast did not fail in that window.

**FIX** — this commit, alongside switching v1 off.

**GUARD** — `ruff check .` clean repo-wide (F821 is what surfaced both), plus `tests/test_v1_is_switched_off.py::test_a_refused_v1_job_is_409_and_not_a_crash`, which is in this same commit and asserts the OTHER half of the same rule: a refusal must reach the operator as a sentence, never as a 500 they have to read the logs to understand.

---

## RCA-2026-09-24-E — Backtest v2's "last 30 days" CSV re-measured every row on the OLD v1 candles, so #5JWGQZPG read 100% in the file and 96% on screen (FIXED)

**CEO**

* You downloaded Backtest v2's CSV with "last 30 days" and strategy
  #5JWGQZPG (GPNSTOCK, 30 minutes, keltner) said 100% wins; the screen said
  96%. The screen is right: 28 trades, 27 won, 1 lost. The file missed the
  one loss — a short on Sep 17, 2026 at 1:00pm, stopped out at 4:09pm for
  -$2.23.
* Why: when the download re-checks each strategy over the last 30 days, it
  is supposed to use Backtest v2's own 1-minute prices. One hand-off inside
  the download forgot to say which price store to use, so it quietly used
  the old v1 prices instead — and those stop at Sep 15, 2026 5:30pm for this
  coin. The file's "last 30 days" was really 21.7 days, settled by the
  candle, not by the minute.
* What stops it now: the setting can no longer be forgotten — the
  hand-off passes on everything it was given, automatically — and every step
  from the screen to the re-check is tested, so a filter or setting dropped
  at any of the four hand-offs fails a test before it reaches you. Checked
  after the fix: the CSV reads 28 trades, 27 won, 1 lost, 96.43%, exactly
  the screen. Re-download any v2 CSV made with "last N days" since Sep 18.

**DEV**

* `rows_index.py:4366-4375` — `iter_rows(db_path=…, store=…)`, called for
  another store, re-enters itself through
  `iter_rows_in(db_path=db_path, coin=…, …, stats=stats,
  measured_days=measured_days)` and forwards every argument EXCEPT `store`.
  The re-entered call runs with `store=None`, so `rows_index.py:4471`
  `_msw.window_rows(batch_rows, win_days, …, store=store)` gets None and
  `market_sweep.py:1986` reads `cached_candles(sym, tf)` — the v1 cache — and
  settles exits by the bar. The screen's path (`api.py:424`,
  `msw.window_rows(rows, days, store=_st)`) never goes through `iter_rows`,
  which is why the two disagree.
* Invariant broken: **a request for store X reads store X, on every path it
  takes** (the Sep 18 rule), and **a wrapper forwards every argument or
  names the ones it drops**. `store` was added to `iter_rows` in
  6e649d590da5 (Sep 18, 2026 3:39am) on top of the hand-off added in
  3f459fc847f1 (Sep 17, 2026 6:59pm), and the hand-off was never updated.
* Guard: `tests/test_the_v2_csv_window_uses_the_v2_candles.py` (7) — the
  hand-off forwards EVERY parameter (driven with a distinct value per
  parameter, so next month's parameter is covered unedited), the real v2
  route hands `window_rows` the v2 store, v1 keeps `None`, and each of the
  three other hand-written pass-throughs (v2 table route -> `strategies`, v2
  CSV route -> `strategies_csv_lines`, builder -> `iter_rows`) forwards every
  filter. Each was proved RED in a scratch worktree by breaking its link.

**SAW** — the operator, `Sep 24, 2026`: *"when i download csv 5JWGQZPG has
100% winrate but but in ui its 96% winrate"*.

**TIMELINE** (all measured on this PC, Sep 24, 2026)

1. The stored v2 row: 28 trades, 27W/1L, **96.43%**, +$73.53 over 29 days
   (1,439 bars), measured through `Sep 23, 2026 3:00am`.
2. `GET /api/v2/strategies?row_id=5JWGQZPG&days=30` (the screen): window
   `Aug 25, 2026 12:30am → Sep 22, 2026 12:30am`, 28.0 days, **28 trades,
   27W/1L, 96.43%**, +$72.84.
3. `GET /api/v2/strategies.csv?row_id=5JWGQZPG&days=30` (the download):
   window `Aug 25, 2026 12:30am → Sep 15, 2026 5:30pm`, 21.7 days, **23
   trades, 23W/0L, 100.0%**, +$63.94. Without `days` the CSV prints the
   stored 96.43% — only the window path is wrong.
4. Reproduced in a fresh process through `api.strategies_csv_lines(...,
   store=stores.V2)`: same 23 / 100%. A spy on `market_sweep.window_rows`
   shows ONE call, and `store=None` in it. Replaying that exact row with
   `store=stores.V2` gives 28 / 96.43% / Sep 22.
5. The candles: v1's `GPNSTOCK_USDT-30m` holds 1,529 bars ending
   **Sep 15, 2026 5:30pm**; v2's 1-minute file holds 49,885 bars ending
   **Sep 22, 2026 1:10am**. All 5,278 v1 candle files were last written
   between Aug 26 and Sep 19, 2026 — so every v2 CSV window since Sep 18
   ended days before the v2 data does, per coin.
6. The missed trade, from `trades_for(store=V2)`: SHORT, entry
   `Sep 17, 2026 1:00pm` at 89.92, stop at 91.72 at `4:09pm`, -$2.23 — after
   the v1 candles end, so the CSV could never see it.

7. `Sep 24, 2026 ~7:00pm` — fixed on the operator's "okay start now … i dont
   want any bug in the future": the hand-off became
   `iter_rows_in(**_given)` with `_given = dict(locals())` taken as the
   generator's first statement, so it forwards whatever `iter_rows` is given.
   Re-run through the real builder: **28 trades, 27W/1L, 96.43%, +$72.84,
   Aug 25 12:30am -> Sep 22 12:30am** — the screen's figures exactly.
8. The harddev loop, round by round: (1) the other five re-measure calls
   (`api.py:391, 432, 955, 1021, 3681`) were read — each picks its store
   correctly; (2) the three other hand-written pass-throughs between the
   screen and the re-measure were found and given parameter-parity guards;
   (3) the first draft of the builder guard read the parameters of its own
   stand-in (`**kw`), so it compared nothing and passed with `store`
   dropped — caught only because every guard was also run against a
   deliberately broken scratch copy; (4) a concurrent session briefly swapped
   `rows_index.py` back while testing its own work, so red-proofs were moved
   to throwaway worktrees and never touch the shared folder.
9. Two tests that were ALREADY red before this change were brought back
   rather than left to hide the next fault:
   `test_v2_surfaces_read_their_own_store.py::test_the_backlog_waits_for_the_other_store_but_a_pressed_row_does_not`
   (a zero-argument `rebuild_progress` stub, stale since 723aecc46d6d) and
   `test_v2_reads_from_its_own_store.py::test_the_v2_update_job_dispatches_the_fleet_and_continues`
   (still expected `cs.dispatch(` after de4ed7a86771 moved the v2 update to
   `dispatch_across`).

**ROOT CAUSE** — a pass-through wrapper that lists its arguments by hand and
was not updated when the function it wraps gained one.

**WHY IT WAS NOT CAUGHT** — the v2 CSV test asserts that a file comes back,
not what is in it; and every CSV-window test runs in the DEFAULT store with
`db_path=None`, where the hand-off branch (`db_path and _DB_OVERRIDE.get() !=
str(db_path)`) never runs — so `store` being dropped there was invisible to
all of them. The Sep 18 review that added `store=` checked the route passed
it; nobody followed it to the call that uses it. **Follow an argument to the
line that consumes it, and test the store you mean with data only that store
has.**

**COST** — no money moved. Every Backtest v2 CSV downloaded with "last N
days" since Sep 18, 2026 carries window figures from v1 candles that end
between Aug 26 and Sep 19, bar-settled — win rates, trade counts and profits
are a different, shorter measurement than the screen's, and the win-% floor
applied to the file used those figures, so rows may be missing from or
wrongly present in those files. Files downloaded WITHOUT a days window are
correct.

**FIX** — this commit: `rows_index.iter_rows` forwards `**_given` (every
argument, captured before anything else is bound) instead of a hand-written
list.

**GUARD** — `tests/test_the_v2_csv_window_uses_the_v2_candles.py::test_every_argument_survives_the_hand_off`,
`::test_the_v2_csv_re_measures_with_the_v2_store`,
`::test_the_csv_builder_forwards_every_filter_to_the_walker`,
`::test_the_v2_table_route_forwards_every_filter` and
`::test_the_v2_csv_route_forwards_every_filter_and_the_v2_store`.

---

## RCA-2026-09-24-D — restarting the app cut the operator's CSV download half-way, and the site called it "Internal Server Error"

**CEO**

* You pressed download on Backtest v2 (Winrate 70% or better, TP at least as
  wide as SL, last 30 days) at 5:01am and got "Internal Server Error". Nothing
  was wrong with the filter or the file: the download takes one to two minutes
  or more, and I restarted the app while it was still being made, which killed
  it; a second download at 5:12am was cut the same way at 373 KB of 905 KB.
* Why: restarting the app stopped it immediately, whatever it was in the
  middle of, and the website's go-between turns "the app vanished" into the
  words "Internal Server Error" — the same words the 30-second limit produced
  on Sep 09, which is why it looked like the old problem coming back.
* What stops it now: a restart first asks the app what downloads are in
  progress and waits for them (up to 15 minutes, and it says what it is
  waiting for); and the previous run's log is kept instead of deleted, so if
  anything cuts a download again the evidence is still there to read.

**DEV**

* `start.py:cmd_start` / `cmd_stop` called `free_port(API_PORT)` at once;
  `strategies_csv_lines` (both `/api/strategies.csv` and
  `/api/v2/strategies.csv`) streams for minutes, and killing uvicorn under it
  makes `next/dist/server/lib/router-utils/proxy-request.js` answer
  `500 Internal Server Error` (or append it to the partial body).
  `spawn()` opened each log with `fresh()`, which unlinks it — so the 5:13am
  restart deleted the only record of the 5:01am request. Now:
  `api._ACTIVE_DOWNLOADS` + `GET /api/system/busy`; the generator lists itself
  and unlists in a `finally` (so an abandoned download does not linger);
  `start.wait_for_downloads()` polls it before either command frees the API
  port (`--now` skips); `keep_previous()` rotates `api.log`/`ui.log` to
  `*.prev.log`; the API runs with `PYTHONUNBUFFERED=1`.
* Invariant broken: **a job that cannot finish must SAY SO** (RCA-2026-09-10-C)
  — and its restart-side twin: **whatever stops the API must first see what it
  would cut.** A guard is only as wide as its pattern: the Sep 09 fix closed
  the proxy's 30-second cause and left every other way to produce the same
  500 open.
* Guard: `tests/test_a_restart_never_cuts_a_download.py` (8) — listed while
  streaming, unlisted when finished or abandoned, start/stop wait BEFORE
  `free_port`, give up loudly after the limit, never wait on an API that does
  not answer, and the previous log survives.

**SAW** — "when downloading using this filter im having internal server error
in csv, why is this occuring again? i had same issue from the past", under
Stored strategies · V2 · Filters 3: Past 30 days · Winrate 70% or better · TP
at least as wide as SL.

**TIMELINE** (from `~/.tradingagents/screen.log`, which survives restarts)

1. `Sep 24, 2026 5:01am` — `csv START | min_winrate=70.0 AND tp_over_sl=True
   AND days=30 AND sort=profit AND desc=True`. No completion line follows —
   ever.
2. `~5:03am–5:08am` — `start.py start` (after commit c8bcd3cd7591) frees port
   8787; the download dies with the API; the UI's proxy answers
   "Internal Server Error".
3. `5:12am` — another download of the same filter starts; `5:13:23am` a
   second restart kills it at **373,236 bytes** (the complete file is
   905,744) — and `fresh()` deletes `api.log` and `ui.log`, the only record of
   both requests.
4. `5:13am–5:17am` — the same filter downloaded three times on the new API:
   complete each time, **1,735 rows, 265 cut by the window, 905,744 bytes**,
   in 110 s, 67 s and 64 s (the last through the UI's proxy, as the browser
   does).

**ROOT CAUSE** — a restart that stopped the API without looking at what it
was serving, and logs deleted on the way.

**WHY IT WAS NOT CAUGHT** — `tests/test_start_launcher.py` asserts WHICH
process a restart kills and how (tree or not, SIGTERM or taskkill); nothing
asked WHAT that process was doing at the time. The Sep 09 CSV fix asserted the
proxy timeout value, not the words the proxy prints for every other failure.

**COST** — none in money; two downloads lost and a report of an error that
was not in the export.

**FIX** — 0e61980a8aaf, and a second round found by pressing the real
download on the live app (`Sep 24, 2026 7:09am`): six seconds in, the list of
downloads in flight was still EMPTY — the route was planning the query before
its stream started — so a restart in those seconds would still have cut it.
Both CSV routes now list the download the instant the request arrives, unlist
it if they refuse (a 503/400 never lingers), and hand the listing to the
stream; a listing whose stream never starts is dropped after
`DOWNLOAD_STALE_S` (the proxy's own 30 minutes). The same press, watched: a
restart would have waited **155 s** and then gone ahead with the file complete
(905,744 bytes, 1,735 rows, "WINDOW FLOOR" trailer). The launcher's messages
print through `_say()`, so a console missing a character cannot abort a
restart half-way.

**GUARD** — `tests/test_a_restart_never_cuts_a_download.py` (11), including
`test_the_route_lists_the_download_the_instant_the_request_arrives`.

---

## RCA-2026-09-24-C — the "indexing" spinner was Backtest v1's seven-month re-file, and it looked like Backtest v2 still running

**CEO**

* After being told Backtest v2 was finished, you still saw "indexing" in the
  top-right corner, twice, and asked why. The first time you were told it was
  a leftover and to refresh — that was wrong: the check behind that answer
  asked the app a question it does not understand and read the error as "no
  jobs".
* Why: the spinner was never about v2. It is the OLD Backtest (v1) store
  re-filing 5,341 coin-timeframes into its search table, one at a time, at
  about 50 minutes each — roughly 194 days — and it said only "indexing".
* What stops it now: the spinner says "indexing Backtest v1" and how long is
  left at the real pace, e.g. "~194d". Ending it for real is a separate
  choice: a one-pass rebuild of the v1 table measured at about 6 hours.

**DEV**

* `api._background_activity` built the chip from `index_status()` (the V1
  store) as `{"kind": "indexing", "now": "indexing N pair(s) into the row
  index"}` — no store, no pace, no end; `RunningJobs.NAME["indexing"]` was
  the bare word. `_index_pace_s()` now reads the indexer's own "+N pairs
  (… rows) in Xs" lines (last 5, cached 60 s) and the chip carries `eta_s`,
  `eta_at`, a store-named sentence and `eta_why` when there is no pace yet.
  `fmtLeft` prints days past 24 h ("5341h 0m" was the alternative).
* Invariant broken: **label-must-match-data** — a label names WHAT it counts;
  "indexing" beside the notification bell counted a different store's work.
  Found beside it: `test_webapp.py::test_the_two_date_formatters_agree`, the
  guard of the MANDATORY date format, had been red since `fmtLeft` landed
  between `MONTHS` and `fmtWhen` with a type spelling its lifter did not strip.
* Guard: `tests/test_the_indexing_chip_names_its_store_and_its_end.py` (6),
  four of which fail on the pre-fix files.

**SAW** — the header chip "indexing", `Sep 24, 2026 12:2xam` and again at
`5:0xam`, after "Backtest v2 is finished".

**TIMELINE**

1. `Sep 21, 2026 8:52pm` — the v1 indexer (pid 17896) starts; the v1 store
   holds ~5,300 coin-timeframes whose files are newer than their index entry.
2. `Sep 24, 2026 12:2xam` — "is it still indexing". `curl /api/jobs/all`
   answers `404 unknown job kind: all`; its body has no `running` key, which
   the check read as an empty list, and the operator was told to refresh. The
   header polls `/api/jobs`.
3. `5:02am` — polling `/api/jobs` every 4 s for 60 s like the header: 15 of 15
   answers carry `indexing 5,341 pair(s) into the row index`. py-spy: the
   indexer's loop is inside `index_pair`'s INSERT; 14.7 MB read and 7.2 MB
   written in 30 s; the log's last passes took 1,090-4,411 s per pair.
4. `5:30am` — the chip names the store and the measured time left.

**ROOT CAUSE** — a status chip with no subject, over a job whose pace makes
it effectively endless.

**WHY IT WAS NOT CAUGHT** — `test_the_indexer_working_off_a_backlog_is_a_chip`
asserted the COUNT ("846 pair(s)") and nothing about WHOSE count it was;
with one store that was enough, and the second store arrived without anyone
re-reading the chip. And the verification that produced the wrong "refresh"
answer checked a URL instead of the endpoint the screen polls — **verify
against the exact request the screen makes, and treat a response with no
expected key as an error, never as empty.**

**COST** — none in money or rows; two wrong reassurances and a confusing
screen. The v1 search table is behind on 5,341 coin-timeframes, which is
real and is not changed by this fix.

**FIX** — this commit.

**GUARD** — `tests/test_the_indexing_chip_names_its_store_and_its_end.py::test_it_names_the_v1_store`
and `::test_the_time_left_is_the_measured_pace_times_the_backlog`.

---

## RCA-2026-09-24-B — the win % filter on Backtest v2 spun for ever, claiming a build that was not happening

**CEO**

* Your filter on Backtest v2 (win 85% or better, the "close it, I won" price
  at least as wide as the "close it, I was wrong" price, last 30 days) showed
  "still working — asking again in a moment" and never finished.
* Why: Backtest v2's table grew to about 99 million strategies and was
  missing the fast list that answers a win-rate filter. Each try read the
  disk for 20 seconds, gave up, and tried again 15 seconds later, for ever.
  It said the list was "still being built" — nothing was building it — and
  every shortcut it suggested was refused too.
* What stops it now: the answer comes back in under a second and says what
  is really happening; the missing list was started at 12:36am and your
  filter answers by itself the moment it finishes.

**DEV**

* `rows_index._slow_why` printed "The wide win-rate index … is still being
  built" whenever `has_index("rows_wr2")` was not True — no `build_running()`
  check. On the v2 store (98,986,982 rows) wr2/wr3/wr4 were all missing and
  the only build was `rows_pr2`. `_winrate_list_note(need)` now reports the
  real state (being built / queued behind X / nothing building) with no
  side effects, and the min-trades / rank-by-win-% / name-a-coin advice is
  dropped at size while no wide list exists (all three measured refused).
* `rows_index.query`: a win % floor that cannot seek, on a big store with no
  wide list, used to walk until `QUERY_BUDGET_S` (27 s measured) on every
  panel retry; it now starts `rows_wr4` and refuses at once (0.7 s
  measured), and the `rows_wr4` refusal stopped claiming "being built in the
  background" unconditionally.
* Invariant broken: **a status line is derived from what is HAPPENING, never
  from what is missing** (`rows_index.py:3198`, `_slow_why`) — the same shape
  as RCA-2026-09-24-A an hour earlier. Guard:
  `tests/test_the_winrate_refusal_tells_the_truth.py` (8), six of which fail
  on the pre-fix file.

**SAW** — the operator's screenshot, `Sep 24, 2026 12:2xam`: Backtest v2 →
min win % 85, TP ≥ SL, last days 30, and the badge "still working — asking
again in a moment…".

**TIMELINE**

1. `Sep 23, 2026` — the v2 table is rebuilt from scratch (RCA-2026-09-23-H)
   and comes back with the basic search lists only; the on-demand ones
   (rows_wr2/wr3/wr4, rows_pr2) are gone.
2. `Sep 24, 2026 12:18am` — a `rows_pr2` build starts on v2.
3. `12:29am` — the operator's filter, replayed against the app: HTTP 503
   after **27.0 s**, "…still being built". Min trades 100 → 503 in 13.0 s;
   rank by win % → 503 in 23.9 s; coin XPIN → 503 in 22.3 s. The panel's
   retry is every 15 s, so the disk was reading for nothing almost
   continuously, beside the build.
4. `12:36am` — on the operator's "start now", the `rows_pr2` build is stopped
   (18 minutes in; SQLite rolls the half-built index back) and `rows_wr4`
   started in pid 27296, reading the 32.3 GB file at ~6 MB/s.
5. `12:43am` — with the fix, the same filter is refused in **0.7 s** with
   "…rows_wr4 … is being built now — this answers the moment it finishes."

**ROOT CAUSE** — a status sentence derived from "is the index missing"
instead of "is anything building it", on a store that had just lost every
on-demand index in a rebuild.

**WHY IT WAS NOT CAUGHT** — `test_query_budget.py` pins that the refusal
suggests a min-trades floor, on a 400-row fixture where that is true. Every
test of the refusal text runs on a store too small to need a wide list, so
neither "nothing is building" nor "the workaround fails too" could occur. The
workarounds were measured once, on the v1 store, and written into the
sentence as facts about every store.

**AND THE APP NEVER NOTICED THE LIST HAD FINISHED** (found at 1:32am, fixed
in the follow-up commit). `rows_wr4` finished at ~1:30am (`built rows_wr4 in
3247s`) and a fresh process answered the filter in **14.6 s** — but the
running API had cached `has_index("rows_wr4") = False` an hour earlier and
`has_index` cached that answer for the life of the process, so the app kept
refusing the filter, 30 s a time, still saying "being built". The Sep 06 fix
for this shape cleared the cache only for builds the SAME process had
started; this build was started from another one. "Exists" is still cached
for ever (an index only vanishes through a drop, which calls
`forget_indexes`); "missing" now expires after `INDEX_MISSING_TTL_S = 60`.
Guard: `tests/test_the_winrate_refusal_tells_the_truth.py::test_a_list_finished_by_another_process_is_noticed`.
The same pass found that RCA-2026-09-24-A's pid check had turned
`test_wide_profit_index.py::test_two_processes_cannot_build_the_same_index_twice`
red (its fake child's pid 99 is not alive) — fixed in the fixture, and a
one-hour-old commit shipped with a red test because only the nearest suites
were run: **after touching a shared helper, run every test that names it.**

**COST** — none in money or rows; about an hour of a filter that could not
answer, and a disk kept busy by retries while the fix was trying to build.

**FIX** — this commit.

**GUARD** — `tests/test_the_winrate_refusal_tells_the_truth.py::test_it_never_claims_a_build_that_is_not_running`
and `::test_the_query_refuses_fast_instead_of_walking_the_store`.

---

## RCA-2026-09-24-A — a finished index build still said "building NOW", so Backtest v2 could not look a strategy up

**CEO**

* You asked whether it was still indexing. It was not — and the app still
  believed it was, so any search for a strategy by its code on Backtest v2
  answered "the list is being built now, wait".
* Why: while the app builds a sorted list it leaves a small marker file
  naming the process doing the work. That process was gone, and nothing ever
  checked — the marker was simply believed for six hours. It also blocked a
  new build from starting, so the wait could never end by itself.
* What stops it now: the app checks whether the process in the marker is
  still alive. A dead one is cleared at once and the next search starts a new
  build. Checked after the fix: strategy #XLV6V5HJ (XPIN, 1 hour, mom6) is
  found in 0.3 seconds.

**DEV**

* `rows_index.build_running` compared only `lock.stat().st_mtime` against
  `BUILD_LOCK_TTL_S` (6 h) and never read the pid the lock has always
  carried. `.build-rows_id.pid` in the v2 store held **17152**, written
  `Sep 23, 2026 11:24pm`; that process was gone by `Sep 24, 2026 12:11am`
  and `build_running()` still answered `rows_id`.
* Knock-on: `_build_index` refuses while `build_running()` names anything, so
  the dead build also prevented a live one — and `query()` raises
  `SortNotReady` meanwhile, which is what the screen printed.
* Invariant broken: **something must notice when it dies** (the Sep 14 rule
  for the indexer), applied to a BUILD. A recycled pid can only make a dead
  build look alive, which is the old behaviour, so the check cannot regress.
* Guard: `tests/test_a_dead_build_stops_saying_it_is_building.py` (3),
  verified red on the pre-fix file.

**SAW** — `Sep 24, 2026 12:11am`: `ri.build_running()` → `'rows_id'` on the v2
store, `.build-rows_id.pid` = 17152 dated `Sep 23, 2026 11:24pm`, and no such
process in the task list.

**TIMELINE**

1. `Sep 23, 2026 11:24pm` — a build of v2's id list starts (the store had
   grown to 98,986,982 rows over 5,004 coin-timeframes).
2. `~11:30pm` — that process ends. The index itself exists
   (`has_index("rows_id")` is True), but the marker is left behind.
3. `Sep 24, 2026 12:11am` — the operator asks whether it is still indexing.
   `build_running()` says yes; the task list says the pid is gone.
4. `12:20am` — with the pid check, `build_running()` answers `""`, the marker
   is cleared with a line saying why, and `#XLV6V5HJ` is found in **0.297 s**.

**ROOT CAUSE** — a liveness marker whose liveness was never checked.

**WHY IT WAS NOT CAUGHT** — the comment above `BUILD_LOCK_TTL_S` says a TTL
was chosen *instead of* a liveness check because liveness "is not portable
across Windows and POSIX" — but `portable.pid_alive` was written for exactly
that and is already used twice in the same file. The tests all drive a build
that finishes; none kills one. **When a module writes a pid and then only
reads a timestamp, the pid is a comment, not a check.**

**COST** — none in rows or money: the index existed and nothing was lost. An
hour of a screen that told the operator to wait for work that had finished.

**FIX** — this commit.

**GUARD** — `tests/test_a_dead_build_stops_saying_it_is_building.py::test_a_build_whose_process_is_gone_is_not_running`.

---

## RCA-2026-09-23-K — the rebuild's final check read the 30 GB file at 0.54 MB/s: six hours, unfinished, against a two-hour estimate

**CEO**

* The fresh Backtest v2 index (99 million rows, 30 GB) was complete by
  1:57pm and then sat in a "checking" step that its own screen estimated at
  2 hours; at 11:20pm it was still checking — the disk was handing it half a
  megabyte a second — and a second check with a 3 GB memory cache did no
  better. Your table kept showing Sep 17 dates for another nine hours.
* Why: the check reads the file one small page at a time in an order the
  spinning disk cannot serve quickly, and the estimate assumed a speed eight
  times what it got.
* What stops it now: the check reads each lookup list once, end to end,
  which finishes in minutes and still catches a broken list; the estimate
  uses the speed that check really gets; and tonight the fresh file was put
  in place by hand on the strength of its exact row and pair counts
  (98,986,982 and 5,003), with the old file kept as a backup.

**DEV**

* `rows_index.rebuild` ran `PRAGMA quick_check` as its verify;
  `VERIFY_MB_PER_S = 4.1` sized the estimate. Measured on pid 24444,
  `Sep 23, 2026 4:58pm`: `ReadTransferCount` +0.54 MB/s, 166 GB read in total
  since 3:51am, 577 MB working set; a second reader with
  `PRAGMA cache_size=-3000000` and `mmap_size` (pid 14412) counted the table
  in 301 s and the pairs in 32 s, then sat in `quick_check` for 6 h 14 min
  with 106 s of CPU. `_walk_every_index` now counts `rows INDEXED BY <each
  index>` and is the default; `quick_check` runs only with
  `rebuild(full_check=True)` / `--full-check`; `VERIFY_MB_PER_S = 50`.
* Invariant broken: **a job's estimate is a measurement of the job it
  describes** (label-must-match-data) — 4.1 MB/s was measured for a 42 GB
  file on a different day and applied to a walk that never reached it; and
  **a finishing step must be able to finish** in the time its screen names.
* Guard: `tests/test_rebuild_from_the_pair_files.py::test_the_verify_walks_every_index_and_only_page_walks_on_request`;
  `::test_the_estimate_matches_the_file_it_is_about` re-pinned to the
  index-walk pace.

**SAW** — Stored strategies: "REBUILDING a row index — verifying · 5,003 of
5,003 pairs · 98,986,982 rows · running 10h 34m · about 1h 55m left (around
Sep 23, 2026 4:30pm)"; at 4:58pm the same line, "about 2h 3m left (around
7:02pm)".

**TIMELINE**

1. `Sep 23, 2026 3:51am` — rebuild starts under the v2 store.
2. `1:57pm` — loading and four indexes done (36,377 s); `verifying` begins,
   estimate 7,449 s.
3. `4:58pm` — read rate 0.54 MB/s; 3 h into the 2 h estimate; killed. A
   big-cache check started 5:00pm: counts in 301 s + 32 s, then
   `quick_check` for 6 h 14 min without a result.
4. `11:22pm` — the API stopped, `rows.db` (11.9 GB, 30.7 M rows) renamed to
   `rows.db.before-rebuild-20260923-2322`, `rows.rebuild.db` (30.5 GB)
   renamed in, the API restarted at `11:24pm`; the v2 table answers
   `total 98,986,982`; the id list (`rows_id`) builds on demand.

**ROOT CAUSE** — a page-order integrity walk as the verify of a 30 GB file
on a mechanical disk, and an estimate constant measured for another walk.

**WHY IT WAS NOT CAUGHT** — `test_the_estimate_matches_the_file_it_is_about`
pinned the constant to the day it was measured; nothing measured the check's
pace on THIS file, and no test bounds how long a verify may run against the
estimate its screen prints.

**COST** — none in money; the v2 table showed a third of its rows and
week-old dates for nine hours longer than needed.

**FIX** — this commit; the file swap was done by hand tonight (counts
matched exactly; the old file is kept beside it).

**GUARD** — `tests/test_rebuild_from_the_pair_files.py::test_the_verify_walks_every_index_and_only_page_walks_on_request`.

---

## RCA-2026-09-23-J — the rebuild's "time left" jumped from 1h 39m back to 2h 2m every time the check's heartbeat wrote its file

**CEO**

* Twenty minutes after the "about 1h 39m left" line appeared, it read "about
  2h 2m left" — the wait had grown while the work went on.
* Why: the time left was worked out as "estimate minus how old the progress
  file is", and the checking step rewrites that file every few minutes to
  show it is alive — so every heartbeat made the file young again and the
  estimate started over.
* What stops it now: the rebuild writes how long the current step has been
  running, and the time left counts from that; a rebuild from before this fix
  counts from the moment the screen first saw the step and says the figure
  may finish sooner.

**DEV**

* `rows_index._rebuild_eta` (cf77df96fcad) computed `verify_estimate_s -
  age_s`; `rebuild()`'s `_tick` progress handler calls `_say("verifying")`
  every `VERIFY_TICK_OPS` steps, refreshing the mtime. Measured: 5,940 s left
  at `2:21pm`, 7,320 s left at `2:27pm` after the `2:26pm` heartbeat. Now
  `_say` writes `phase_seconds` (from `phase_since[phase]`), and the reader
  uses `phase_seconds + age_s`; for a record without it, `_PHASE_FIRST_SEEN`
  keeps the rebuild's own `seconds` at first sight and the `eta_why` says the
  figure may finish sooner.
* Invariant broken: **label-must-match-data** — a "time left" that grows
  while the work advances is a false label; and **a heartbeat is a sign of
  life, not a restart**.
* Guard: `tests/test_the_screen_says_the_index_is_rebuilding.py::test_the_rebuild_says_how_long_is_left_from_its_own_pace`
  (a fresher file with a larger `phase_seconds` must read LESS time left; a
  legacy record's two heartbeats 28 minutes apart must read 28 minutes less).

**SAW** — Stored strategies: "about 1h 39m left (around Sep 23, 2026
4:02pm)" at `2:21pm`; "about 2h 2m left (around Sep 23, 2026 4:30pm)" at
`2:27pm`.

**TIMELINE**

1. `Sep 23, 2026 1:57pm` — the v2 rebuild enters `verifying`;
   `verify_estimate_s` 7,449.
2. `2:21pm` — the ETA feature ships; reads 5,940 s left.
3. `2:26pm` — the verify heartbeat rewrites the progress file.
4. `2:27pm` — the screen reads 7,320 s left; the fix follows.

**ROOT CAUSE** — the file's age used as the phase's elapsed time.

**WHY IT WAS NOT CAUGHT** — the guard set the mtime once and read once; it
never wrote a second heartbeat and asked whether the figure went down.

**COST** — none.

**FIX** — this commit.

**GUARD** — `tests/test_the_screen_says_the_index_is_rebuilding.py::test_the_rebuild_says_how_long_is_left_from_its_own_pace` — it now writes two heartbeats and demands the second reads less time left.

---

## RCA-2026-09-23-I — the run card said "Testing … → now" and "nothing has arrived yet" about a run that had finished and landed hours earlier

**CEO**

* At 6:42am the Backtest v2 run card still read "Testing Jul 25, 2026 6:42am
  → Sep 23, 2026 6:42am" and "results are landing here — nothing has arrived
  yet", while the same card showed the run 100% green with an "already in
  this PC" badge: the run had finished at 3:59am and 35 of its 50 pairs were
  already in your store. You asked whether it was still testing and whether
  you had to refresh.
* Why: the end date was the clock on the wall, not the run's end, so it kept
  moving; and the "arrived" counter is kept per run while a two-account press
  puts two runs on one card, so it counted the wrong one.
* What stops it now: a finished run reads "Tested … → 3:59am" with the last
  machine's real finish time, and a run whose rows are in this PC says
  exactly that instead of "nothing has arrived yet".

**DEV**

* `JobsPanel.tsx:581` rendered `Testing {from} → {fmtWhenMs(Date.now())}`
  regardless of `cloud.conclusion`; `cloud_sweep.status` carried
  `jobs[].completedAt` but no run-level finish. `finished_at(d)` (max
  `completedAt` once every job has one and the run has a conclusion) is now in
  the payload as `finished`, and the card prints `{done ? "Tested" :
  "Testing"} … → {finished}`. `JobsPanel.tsx:623` printed "nothing has
  arrived yet" whenever `live.at` was unset; `live_ingest` keys its counter by
  ONE run id (`cur = {"run": run_id, …}`) and the card showed runs
  35776582134 + 35776595829 together. `cloud.collected` — the store's own
  word — is checked first and prints "every coin of this run is in this PC's
  store".
* Invariant broken: **label-must-match-data** — a tense and a date are labels;
  a moving clock under a finished run and "nothing" over 35 landed pairs were
  both false.
* Guard: `tests/test_the_screen_says_the_index_is_rebuilding.py::test_a_finished_run_speaks_in_the_past_tense_and_ends_when_it_ended`,
  `::test_the_finish_time_is_the_last_machines_completion`,
  `::test_rows_already_in_this_pc_are_never_nothing_has_arrived`.

**SAW** — "GitHub run #35776582134 + #35776595829 · 2 accounts · success ·
100.0% · 10/10 coins · 939,144 rows measured · Testing Jul 25, 2026 6:42am →
Sep 23, 2026 6:42am … results are landing here as each coin finishes —
nothing has arrived yet … already in this PC".

**TIMELINE**

1. `Sep 23, 2026 3:52am` — two runs dispatched, 5 coins each.
2. `3:57am → 4:00am` — 35 pairs land through the live door (XPIN-4h.json
   `4:00am`); `3:59am` — the last machine finishes; both runs green.
3. `6:42am` — the card: "Testing … → 6:42am", "nothing has arrived yet",
   "already in this PC", all on one screen.

**ROOT CAUSE** — `Date.now()` as the end of a finished window, and a
per-run-id counter read for a two-run card.

**WHY IT WAS NOT CAUGHT** — the card's tests assert on counts (rows, coins,
machines); the sentence's tense and its end date were literals nobody
compared to `conclusion`.

**COST** — none in money; a morning spent asking whether a finished run was
running.

**FIX** — this commit.

**GUARD** — `tests/test_the_screen_says_the_index_is_rebuilding.py` (10).

---

## RCA-2026-09-23-H — a 99-million-row rebuild of the Backtest v2 index ran for three hours and no screen said so; its progress was written to the other store's file

**CEO**

* Row #AA2CRSTY BASECAT 1h showed "last backtest Sep 17, 2026 9:00pm" at
  6:42am on Sep 23 while its new measurement had landed at 2:20am — because
  the table reads an index file that was being rebuilt from scratch
  underneath it (5,003 pairs, 98,986,982 rows, 25 GB, three hours in), and
  nothing on the page said a rebuild was happening. You asked to be shown
  when indexing is happening.
* Why: the rebuild wrote its progress to one shared file meant for the old
  store, so the Backtest v2 screen had nowhere to read it from.
* What stops it now: each store keeps its own progress file, and the
  strategies table prints a pulsing "REBUILDING this row index — phase, pairs,
  rows, running 2h 52m — the dates on this table catch up when it finishes"
  the moment one is in flight; a rebuild from before today is shown too,
  marked as not saying which store it is filing.

**DEV**

* `rows_index.REBUILD_PROGRESS` was `~/.tradingagents/rows_rebuild.json`
  for every `DB_PATH`; `rebuild()` under `stores.V2.env_for()` wrote there;
  `status(db_path=V2)` carried no `rebuild` field and `StrategiesPanel` had
  no sentence for it. Now `REBUILD_PROGRESS = DB_PATH.parent /
  "rows_rebuild.json"`, `_say` writes `"db"`, `rebuild_progress(db_path)`
  reads this store's file (or the legacy one as `store: "unknown"`), marks
  `running` by file age (`REBUILD_FRESH_S`), and `status()` carries it as
  `rebuild`; the panel prints it first.
* Invariant broken: **a request for store X reads store X, on the WRITE paths
  too** (RCA-2026-09-18-B), and **the screen says which state it is in**
  (RCA-2026-09-14-B).
* Guard: `tests/test_the_screen_says_the_index_is_rebuilding.py` — per-store
  path, another store's file refused, a dead rebuild's file not "running",
  the legacy file read as unknown, the status field, the panel sentence.

**SAW** — Backtest v2, Stored strategies: `#AA2CRSTY` … last backtest
`Sep 17, 2026 9:00pm`; no spinner, no sentence; `rows.rebuild.db` at 25.5 GB
on disk.

**TIMELINE**

1. `Sep 23, 2026 1:12am–1:25am` — six `pairbt_v2` index writes raise
   "database disk image is malformed"; the rows are measured, not filed.
2. `3:51am` — `rows_index --rebuild` started under the v2 store; progress
   to `~/.tradingagents/rows_rebuild.json` (v1's readers' path).
3. `2:20am` (earlier) — BASECAT-1h.json lands from GitHub, measured through
   `Sep 22, 2026 10:00pm`; the table keeps saying `Sep 17, 2026 9:00pm`.
4. `6:42am` — the operator asks; progress file reads "indexing 3 of 4:
   rows_coin · 5,003 of 5,003 pairs · 98,986,982 rows · 10,350 s".

**ROOT CAUSE** — one progress path for two stores, and no reader of it on
the store's own screen.

**WHY IT WAS NOT CAUGHT** — `test_the_indexer_is_never_allowed_to_stay_dead`
and `test_index_stall_is_visible` cover the INDEXER process (which v2 does not
have); a REBUILD is a third state neither imagined, and every path test for
v2 was about `rows.db`, never the progress file beside it.

**COST** — none in money; the store's own numbers were on disk and invisible
for hours.

**FIX** — this commit. The rebuild started at 3:51am keeps writing to the
legacy path and is shown as "a row index (started before Sep 23, 2026)" until
it finishes.

**GUARD** — `tests/test_the_screen_says_the_index_is_rebuilding.py` (10).

---

## RCA-2026-09-23-G — the practice account paid the entry spread twice: once in the fill price, once again at the exit

**CEO**

* Every practice trade got in at the exchange's asking price — a little
  worse than the bar's own price, 0.022% on average across 92 trades — and
  then, when it closed, was charged the full cost of getting in AND out,
  which already contained that same 0.022%.
* Why: two good ideas added on the same day never met — "fill the practice
  trade at the real asking price" and "charge the practice trade the real
  round trip" — and each one carried the entry half of the spread.
* What stops it now: a practice trade remembers the spread its fill already
  paid and is charged the round trip minus that one side; on an XPIN trade
  that is 0.057% less taken off every close.

**DEV**

* `auto_trader._process_slot`: the paper fill prices at the ask/bid via
  `_CYCLE_PRICES` (Sep 05, 2026) and the position carried
  `rt_cost = 2 * (slippage + taker_fee) + funding` (Sep 05, 2026, same day);
  `paper_round_trip` charged all of `rt_cost` at exit. Measured on the 92
  practice fills matched to the account replay's bar-open entry, Sep 15-22,
  2026: median 0.022% adverse, 64% of fills adverse — the half-spread. The
  position now carries `book_slippage = gate["slippage"]` and
  `paper_round_trip` returns `max(rt_cost - book_slippage, 0)` when it is
  present; a position from before today pays as before.
* Invariant broken: **one trade, one cost, charged once** — the same rule
  RCA-2026-09-23-E bought for the fee, in its spread half.
* Guard: `tests/test_the_backtest_forecasts_the_account.py::test_the_paper_book_charges_the_entry_spread_once`.

**SAW** — the account replay and the practice account agreed on which trades
and which outcomes (37 of 39 matched) and disagreed on the money; after the
fee fix (E) a residual of ~$0.02–$0.05 a trade remained.

**TIMELINE**

1. `Sep 05, 2026` — `_CYCLE_PRICES`: a paper buy prices at the ask, a sell
   at the bid ("read once, both books use that one number"). Same day:
   `rt_cost` carried on the position and charged at exit.
2. `Sep 15 → Sep 22, 2026` — 92 practice fills matched to their bar:
   PSXSTOCK `Sep 15, 2026 10:00pm` filled 261.95 against a bar price of
   262.1 (a short — 0.06% better), `Sep 15 11:15pm` 262.7 against 262.3 (a
   short — 0.15% worse); median across all 92: 0.022% worse.
3. `Sep 23, 2026` — `book_slippage` carried; the exit charges the round trip
   less that side.

**ROOT CAUSE** — the entry half of the spread lived in two places: the fill
price and the round-trip charge.

**WHY IT WAS NOT CAUGHT** — `test_demo_matches_live` checked the practice
charge against the gate's round trip and the fill against the ask
separately; nothing summed what one trade paid end to end against what a
live fill pays. Two lists modelling one trade were never added up.

**COST** — none in money (paper book); ~0.02%-0.06% of notional a trade,
$0.02–$0.06 at $100, on 166 trades ≈ $5 of the practice account's stated loss.

**FIX** — this commit.

**GUARD** — `tests/test_the_backtest_forecasts_the_account.py::test_the_paper_book_charges_the_entry_spread_once`.

---

## RCA-2026-09-23-F — the fee helper believed a spec that under-states: the venue takes 0.08% a side where the spec says 0.04%

**CEO**

* Every cost this app charges starts from the exchange's own fee figure for
  each coin. For CTC, STBL and the older live coins (ALICE, NOM, PI, PROVE,
  APEX) that figure reads 0.04% a side — and your real fills at MEXC paid
  **0.08% a side**, every time. So half the fee was missing from the backtest,
  from the gate that refuses expensive trades, and from the practice account,
  on those coins.
* Why: the code trusted the exchange's published rate whenever it was above
  zero, and only fell back to the real figure when the spec said nothing.
* What stops it now: the fee is the published rate or 0.08% a side, whichever
  is higher — read off 48 of your own closed positions, where 44 paid exactly
  0.08% and 4 paid 0.04% because one side closed as a maker.

**DEV**

* `auto_trader.taker_fee:1928` returned `rate if rate > 0 else FEE_FALLBACK`;
  `contract_spec()["takerFeeRate"]` is `0.0004` for CTC/STBL/ALICE/NOM/PI/
  PROVE/APEX and `0` for every stock contract, while `position_history()`
  shows `fee / (closeVol * contractSize * (openAvg + closeAvg))` = **0.080%**
  on 44 of 48 positions (`Aug 29` → `Sep 16, 2026`). It now returns
  `max(rate, FEE_FALLBACK)`.
* Invariant broken: **the exchange is the source of truth** (rule 14) — a
  published rate is a label; the fill is the data.
* Guard: `tests/test_the_backtest_forecasts_the_account.py::test_the_fee_helper_believes_the_venues_fills_over_a_low_spec`;
  `tests/test_auto_trader.py::test_taker_fee_is_per_contract_and_never_assumes_btc`
  (widened — it had asserted the under-statement).

**SAW** — nothing on a screen; found while reconciling the account replay to
the practice book (RCA-2026-09-23-E), when the venue's `fee` field on
VUG_USDT (`Sep 16, 2026 1:37pm`, $396.81 a side) read $0.3174 against a spec
of 0.

**TIMELINE**

1. `Aug 29, 2026 7:00pm` — ALICE_USDT closes live: $100.06 a side, fee
   $0.1592 = 0.080% a side; spec 0.0004. Same for NOM ($0.3261 on $199.87),
   PI, PROVE, APEX — 44 of 48 positions at 0.080%, 4 at 0.040%.
2. `Sep 16, 2026 2:37am` — CTC_USDT live: $99.63 a side, fee $0.1581 =
   0.080%; spec 0.0004. The gate on CTC's `killzone_4h_sl3tp15` was charging
   0.04%.
3. `Sep 23, 2026` — `taker_fee` returns the higher of spec and 0.0008.

**ROOT CAUSE** — `return rate if rate > 0 else FEE_FALLBACK`: a fallback used
only for a MISSING figure, never for a WRONG one.

**WHY IT WAS NOT CAUGHT** — `test_taker_fee_is_per_contract_and_never_assumes_btc`
asserted `taker_fee("CHEEMS_USDT") == 0.0004` for a spec of 0.0004: the test
pinned the spec's word, and no test had ever read a real fill's fee back from
`position_history`.

**COST** — on CTC and STBL: 0.08% of notional a trade under-charged in every
backtest row and in the gate; on the practice book it was masked by
RCA-2026-09-23-E charging the fee twice.

**FIX** — this commit; and the cached copy of the spec's fee in each coin's
cost file (`CTC_USDT.json`, `XPIN_USDT.json`: 0.0004, Sep 22, 2026) is floored
the same way where `trades_for` and `window_rows` read it back.

**GUARD** — `tests/test_the_backtest_forecasts_the_account.py::test_the_fee_helper_believes_the_venues_fills_over_a_low_spec`,
`::test_an_old_cost_files_fee_is_floored_like_the_fee_helper`.

---

## RCA-2026-09-23-E — the practice account paid the exchange fee TWICE on every trade: $25.92 of its −$52.76

**CEO**

* Your practice account's money figure was **−$52.76** over 166 trades. With
  the fee charged once, as MEXC charges it, the same trades are **−$26.84**.
  Half of what the practice book said you lost was a fee it invented.
* Why: when a practice trade closed, the app charged the fee for getting in
  and out, and then ALSO charged the full round-trip cost it had measured at
  entry — which already had that same fee inside it.
* What stops it now: a practice trade is charged the measured round trip and
  nothing on top; a test checks the practice charge against the gate's own
  number instead of re-typing the formula.

**DEV**

* `auto_trader._process_slot` (exit branch, formerly `cost = 2 * taker_fee(...)`
  then `cost += pos["rt_cost"]`): `rt_cost` is `edge_check`'s
  `round_trip = 2 * (slippage + taker_fee) + funding` (`auto_trader.py:2337`),
  so a paper exit paid `4 * taker_fee`. Now `cost = paper_round_trip(pos,
  symbol, fx=fx)` — the round trip when carried, else fee-once plus the flat
  paper slippage.
* Invariant broken: **every cost the backtest charges, the gate charges — and
  ONLY once** (CLAUDE.md, "Every cost the BACKTEST charges, the GATE charges").
  Two lists modelling one trade must be tested against each other.
* Guard: `tests/test_demo_matches_live.py::test_the_paper_book_never_pays_the_fee_twice`,
  `::test_the_paper_pnl_now_matches_what_live_would_keep` (now calls the code
  it used to re-implement);
  `tests/test_the_backtest_forecasts_the_account.py::test_the_paper_book_charges_the_gates_round_trip_and_nothing_on_top`.

**SAW** — Auto Trade, demo W/L: **72.0% · −$45.92** over 164 trades
(`Sep 15` → `Sep 22, 2026`), against Backtest v2's **97.3% · +$3,591.97**
for the same rows. The operator: *"i want forecast to be 10/10"*.

**TIMELINE**

1. `Sep 05, 2026` — `rt_cost` (the gate's measured round trip) is carried on
   every paper position and charged at exit, so a demo trade "can never be
   cheaper than the live one beside it". The existing `2 * taker_fee` line
   above it is left in place.
2. `Sep 15, 2026 12:00pm` → `Sep 23` — 166 practice trades close; realised
   cost median **0.350%** a trade against a gate reading of ~0.19% on the
   same coins: 0.19% + 2 × 0.08%.
3. `Sep 23, 2026` — the account replay (`portfolio_replay`) matches 39 demo
   trades bar for bar, 37 of 39 with the same outcome, and cannot match the
   money; the demo's per-trade cost is `rt_cost + 0.16%`. Booked −$52.76 →
   fee once −$26.84 (the same trades, $25.92 apart).

**ROOT CAUSE** — two cost terms for one trade: `2 * taker_fee` written on
`Aug 12` for a live estimate, `rt_cost` (fee inside) added beside it on
`Sep 05` instead of replacing it on the paper branch.

**WHY IT WAS NOT CAUGHT** — `test_the_paper_pnl_now_matches_what_live_would_keep`
computed `pnl = (move - (fee + rt)) * margin * lev` — it re-typed the exit
path's arithmetic instead of calling it, so the double charge was asserted as
the expected value. A test that copies a formula tests nothing about the code.

**COST** — none in money (paper book). $25.92 of reported loss that did not
exist, on the number the operator picks deployments by; and the practice
book's 72.0% was right while its money was 96% too pessimistic.

**FIX** — this commit. Old exit rows are not rewritten; `portfolio_replay`
takes the doubled fee back out of any reading dated before
`DEMO_FEE_TWICE_UNTIL_S`, and the screen says "booked … with the fee counted
twice until Sep 23, 2026" beside the restated figure.

**GUARD** — `tests/test_demo_matches_live.py::test_the_paper_book_never_pays_the_fee_twice`.

---

## RCA-2026-09-23-D — 23 rows stayed switched on for coins MEXC had delisted, and one of them filled the record with 4,177 refusals

**CEO**

* ROLSTOCK, APOSTOCK and FLUTSTOCK were removed by the exchange, and 23 of
  your rows were still switched on for them — 13 on ROLSTOCK alone. Nothing
  could trade, and every bar the app wrote another "no order book" line into
  your record: 4,177 for ROLSTOCK.
* Why: the delisted clean-up forgets a coin's candles and measurements, but
  never touched the list of what you have switched on.
* What stops it now: the clean-up also switches the coin off on every row and
  writes a "disarmed" line in the deploy log; the 23 rows were switched off on
  Sep 23, 2026 (97 remain).

**DEV**

* `storage_months._run_delisted` called `_forget_lost` (candles, rows, index)
  and returned; `settings["strategy_coins"]` and `strategy_books` were never
  read. New `auto_trader.disarm_coins(symbols, why)` removes the coins from
  every key, drops their `book_slot` entries, saves, and records a
  `disarmed` deployment per row; `_run_delisted` calls it after forgetting.
* Invariant broken: **a coin that cannot trade is not deployed** — one rule,
  every door (the deploy path refuses a delisted coin; the clean-up path did
  not undeploy one).
* Guard: `tests/test_the_backtest_forecasts_the_account.py::test_a_delisted_coin_is_disarmed_from_every_row_and_written_down`.

**SAW** — Auto Trade's strategies grid: ROLSTOCK on 13 rows with `100%` and
no trades; the ledger: `gate_blocked · no order book for ROLSTOCK_USDT` every
cycle.

**TIMELINE**

1. `Sep 16, 2026 5:56am` — the last real ROLSTOCK position closes live
   (−$3.5577); the contract is delisted after.
2. `Sep 16` → `Sep 23` — 4,177 `gate_blocked` rows for ROLSTOCK, 405 book
   readings for APOSTOCK, 11 for FLUTSTOCK; the delisted clean-up runs and
   forgets their candles; the 23 rows stay armed.
3. `Sep 23, 2026` — `disarm_coins({ROLSTOCK, APOSTOCK, FLUTSTOCK})`: 23 rows
   off, backup at `auto_trade.json.before-rolstock-<ts>`; the v2 download for
   APOSTOCK/FLUTSTOCK skips them as delisted, as it should.

**ROOT CAUSE** — `_run_delisted` cleaned the store and not the deployment.

**WHY IT WAS NOT CAUGHT** — every delisted test asserts on what is FORGOTTEN
(files, rows, index); none asked what stays SWITCHED ON.

**COST** — none in money; 4,177 noise rows in the record and 23 rows of
false 100% on the grid.

**FIX** — this commit.

**GUARD** — `tests/test_the_backtest_forecasts_the_account.py::test_a_delisted_coin_is_disarmed_from_every_row_and_written_down`.

---

## RCA-2026-09-23-C — two fade15 rows were waiting for a 50% move in one hour, so they measured 0 trades and were deployed at "100%"

**CEO**

* fade15_1h_sl3tp06 and fade15_4h_sl3tp1 were switched on for six coins
  and showed 100% — over zero trades, ever. Their trigger was written as
  0.5 and 0.4 where every other rule writes 0.005: a 50% and a 40%
  move in one bar, which no coin has made.
* Why: one number typed in percent inside a table that reads fractions.
* What stops it now: 0.005 / 0.004 — 940 and 211 signals over the same
  bars — and a test refuses any trigger at or above 5%.

**DEV**

* `auto_trader._OPERATORS_127["fade15_1h_sl3tp06"]["threshold"] = 0.5` and
  `["fade15_4h_sl3tp1"]["threshold"] = 0.4`; `sig_fade15` compares
  `abs(close/open - 1) >= threshold`. Measured on the deployed coins' 1m-rebuilt
  bars: 0 signals at 0.5, 940 at 0.005 (1h); 0 at 0.4, 211 at 0.004 (4h).
* Invariant broken: **one unit per table** — `STRATEGY_SPECS` thresholds are
  fractions (`tp: 0.006`), and a row's label ("100% · 0 trades") must never
  be read as a measurement.
* Guard: `tests/test_the_backtest_forecasts_the_account.py::test_no_spec_threshold_is_a_percentage_wearing_a_fractions_clothes`.

**SAW** — `docs/STRATEGIES.md` (Sep 22, 2026): *"fade15 rows: 0 signals
measured over the whole store"*; the grid: 100% on six rows with no trades.

**TIMELINE**

1. `Sep 16, 2026 1:54am` — the six fade15 rows are switched on with the
   Sep 16 batch.
2. `Sep 16` → `Sep 23` — 0 signals, 0 trades, `100%` printed.
3. `Sep 23, 2026` — thresholds corrected; the account replay measures them
   with everything else.

**ROOT CAUSE** — a percent typed where the table takes a fraction.

**WHY IT WAS NOT CAUGHT** — no test bounds a spec's numeric fields, and a
rule that never fires produces no failing assertion anywhere — it just makes
the number smaller (the same shape as the missing funding term,
RCA-2026-09-15-C).

**COST** — none in money; six rows of false 100%.

**FIX** — this commit.

**GUARD** — `tests/test_the_backtest_forecasts_the_account.py::test_no_spec_threshold_is_a_percentage_wearing_a_fractions_clothes`.

---

## RCA-2026-09-23-B — the backtest charged a flat 0.03% of slippage while the practice book charged the coin's real book, so 97.3% and 72.0% were the same rows

**CEO**

* Backtest v2 said your 80 rows win **97.3%** and make **+$3,591.97**; the
  practice account running the same rows said **72.0%** and **−$45.92**. Part
  of that gap was nothing but the cost per trade: the backtest charged a flat
  guess of 0.03% a side for the spread, while the practice book charged what
  the coin's order book really cost — 0.35% a trade on your coins against the
  backtest's 0.22%.
* Why: the backtest engine has a built-in default for the spread, and the
  code that measures a coin never passed it the spread it had just read from
  the book.
* What stops it now: every place a trade is simulated — the local backtest,
  the window re-measure, the trade log, the GitHub shards, the resume path —
  charges the book's measured spread, and the coin's cost file keeps it. And
  a new panel on Backtest v2 replays every switched-on row TOGETHER through
  the runner's own gates, at the venue's own book readings, beside what the
  practice account really did on the same days.

**DEV**

* `market_sweep.run_pair` read `book = fx.book_cost(...)` for the gate and
  called `at.backtest_strategy(key, frame, base, fee=fee, ...)` without
  `slippage=` → the engine's `PAPER_SLIPPAGE = 0.0003` default. Same in
  `restate_window`, `trades_for`, `window_rows`, `.github/scripts/sweep_shard.py`
  (`fee=fee + 0.0003` literal) and `resume_state.continue_combo`. All six
  engine calls in `market_sweep` and both in the shard now pass the book's
  `slippage`; `save_costs` stores it; the disk-only paths read it back.
  `portfolio_replay.py` (new) + `GET /api/v2/portfolio` + `PortfolioForecast.tsx`.
* Invariant broken: **every cost the backtest charges, the gate charges** —
  and its mirror: every cost the gate charges, the backtest charges. Rule 10:
  cost is measured per contract, never a flat figure.
* Guard: `tests/test_the_backtest_forecasts_the_account.py::test_every_simulated_trade_charges_the_books_slippage`
  (walks the AST for every `backtest_strategy` call and demands `slippage=`).

**SAW** — Backtest v2 for the deployed rows: 97.3%, +$3,591.97, 8,077 trades;
Auto Trade demo W/L: 72.0%, −$45.92, 164 trades; live 57.1%, +$0.48, 21.

**TIMELINE**

1. `Aug 19, 2026` — `backtest_strategy` charges fee + slippage by default;
   the sweep passes `fee` and never `slippage`.
2. `Sep 05, 2026` — the practice book starts charging the measured round trip
   (`rt_cost`), so demo and backtest now charge DIFFERENT costs for one trade.
3. `Sep 15` → `Sep 22, 2026` — 164 demo trades pay a median 0.350%; the
   backtest rows they were picked from paid 0.220%.
4. `Sep 23, 2026` — the review: 97.3% vs 72.0% on the same rows; the operator:
   *"start fixing the bugs now … i want forecast to be 10/10"*. The account
   replay over the same days, at the venue's own readings: **124 trades,
   76.6%, +$6.41 flat** against the practice book's **135 trades, 69.6%,
   about −$21 at $5 flat with the fee once** on the rows still switched on.
   The rest of the original gap: 18,163 refusals the backtest never modelled
   (a book too wide for the target most of the day — FASTSTOCK median 2.49%
   across 1,469 gate readings, floor 0.181%), 54 rows on one coin measured as
   54 simultaneous positions, and the doubled fee (RCA-2026-09-23-E).

**ROOT CAUSE** — an engine default (`slippage=PAPER_SLIPPAGE`) silently used
where the caller had the measured figure in hand.

**WHY IT WAS NOT CAUGHT** — every backtest test asserts on TRADES and
BARRIERS; the cost was a keyword with a default, and a default produces no
failing assertion — it makes the number bigger. The demo's cost and the
backtest's cost were never compared as lists.

**COST** — none in money; the number the operator picks deployments by was
~25 points of win rate and ~$3,600 too kind.

**FIX** — this commit. A stored row measured before it keeps its old cost
until re-measured (UPDATE THIS BACKTEST); the cost file's `slippage` is
`null` until then and the replay charges the venue's reading, never the file.

**GUARD** — `tests/test_the_backtest_forecasts_the_account.py` (19 tests).

---

## RCA-2026-09-23-A — the Auto Trade tables were unreadable on a phone, and 15 columns had nowhere to go

**CEO**

* You opened the app on your phone for the first time and the live trade table
  was unusable — columns cut off at the edge of the screen with no way to
  reach them.
* Why: that screen lays out 15 columns for open trades and 10 for closed ones.
  On a phone that is about 26 pixels per column, and the table was built to
  squeeze rather than scroll, so the text was simply clipped.
* What stops it now: on a phone the same trades are shown as one card each —
  what it made, on what, which way, how close to your win or lose price — with
  the CLOSE button on the card. On a computer nothing changed at all.

**DEV**

* `PositionsPanel.tsx` renders `HEADS` of 15 columns and `TradeHistory.tsx`
  10, both through `<Table fixed>` — `table-fixed w-full` with `break-words`
  cells, whose own comment says the Auto Trade screen must not scroll
  sideways. `TradeHistory` then put `whitespace-nowrap` on nearly every cell,
  which defeats that wrapping, and the panel's `overflow-hidden` clipped the
  result.
* Invariant broken: a screen must be READABLE on the device it is opened on.
  Neither "wrap" nor "scroll" was ever going to work at 26px a column; the
  layout had to change shape, not squeeze.
* Guard: `tests/test_the_trade_tables_work_on_a_phone.py` (5 tests).

**SAW** — the operator, `Sep 23, 2026`: *"in mobile. the live trade table is
not mobile responsive"*, minutes after reaching the app from their phone over
Tailscale for the first time.

**TIMELINE**

1. `Sep 23, 2026` — Tailscale is set up and the app becomes reachable from a
   phone at all. Before this, every view of it was on a 1920px desktop.
2. Minutes later the operator reports the live trade table.
3. Measured: `PositionsPanel` 15 columns, `TradeHistory` 10, on a ~390px
   viewport — 26px and 39px per column respectively, with
   `whitespace-nowrap` on the history cells and `overflow-hidden` on the card.
4. Fixed: below `md`, both render stacked cards; at `md` and up the tables are
   untouched. Built and served over Tailscale, `md:hidden` present in the
   shipped chunk.

**ROOT CAUSE** — a fixed-width table of 15 columns has no readable form on a
390px screen, and the component was built to squeeze into the viewport rather
than change shape.

**WHY IT WAS NOT CAUGHT** — every check in this repo renders at desktop width.
The Playwright gate (`.claude/skills/verify-ui-change`) screenshots ONE
viewport and its whole discipline is about composition — nested chrome,
baselines, semantic colour — none of which is wrong at 1920px here.
`test_port_audit` asks whether a control EXISTS, and **a column pushed off the
side of a 390px screen exists perfectly.** There was no phone to test on until
today, so the gap was real for as long as the screen has existed and could not
have been reported.

**COST** — none in money. The operator could not read their own open trades on
the device they had in their hand.

**FIX** — this commit. Cards below `md` in both panels, tables unchanged above
it. The close button rides the phone card, because a real position that cannot
be shut from the device in your hand is the one thing that panel must never
be; the empty state is rendered in the phone view too, since it lived inside
the table body and would otherwise have vanished with it.

**GUARD** — `tests/test_the_trade_tables_work_on_a_phone.py`: each table has a
phone layout AND hides the table there (rendering both would show every row
twice); the phone card can still close a REAL position; both ids stay
copyable; the empty state still says how many trades were examined; and the
column counts that made this necessary are pinned, so a table that grows
starts hiding data silently rather than re-arranging it.

---

## RCA-2026-09-22-A — Backtest v2 lost the whole DAILY timeframe, because it rebuilt the bars out of the minutes

**CEO**

* Your Backtest v2 had no daily results at all — **zero** coins, against
  **1,080** on the old backtest. Every other timeframe was there. Nothing said
  a word about it; the daily rows simply never existed.
* Why: v2 was building its candles out of 1-minute candles. MEXC only sells
  about 30 days of those, which makes 33 daily candles — and every strategy
  has to look back over 300 candles before it is allowed to trade. So there
  was never enough daily history to trade on, and every daily coin was quietly
  skipped.
* What stops it now: v2 takes the ordinary daily candles from the exchange,
  which go back 2,300 days, and uses the minutes only for the thing it needed
  them for — deciding whether the win price or the lose price was hit first
  inside a candle. Daily now measures: BTC gives 29 usable days and 8 trades
  where it gave nothing.

**DEV**

* `.github/scripts/sweep_shard.py` `run_pair` called
  `msw.bars_from_1m(m1, tf)` for every frame when `RES` was set. With
  `br.TFS["1m"]` capped at 44,000 bars (MEXC's own limit, ~30.6 days), `1d`
  rebuilt to 33 bars; `window()` then computes
  `warm = min(WARMUP_BARS=300, len(df) - len(measured))` and `run_pair`
  returns early on `len(df) - warm < br.min_bars(tf)` — 33 − 33 = 0 < 2.
* Invariant broken: **the warm-up is history the rule READS, never bars it
  trades**, so it may not be sourced from a feed that is shorter than the
  lookback. And v2's own design sentence — *"the SAME signals on the SAME
  timeframes, and only the EXIT made minute-exact"* — was implemented as a
  replacement of the bars rather than an addition to them.
* Guard: `tests/test_v2_measures_on_github.py::test_v2_ADDS_the_minutes_it
  _does_not_replace_the_bars_with_them`.

**SAW** — the operator, `Sep 21, 2026`, setting the goal: *"what ever existing
on v1 i want on v2 the only difference is v2 will be using 1min candles that's
the only difference i want"*. The daily gap is exactly the part of that which
was not true, and it was found while checking whether it was.

**TIMELINE**

1. `Sep 17, 2026` — v2 ships. Its design proves 60 one-minute candles rebuild
   MEXC's own hour candle exactly (XPIN, 666 of 666 hours), and rebuilding is
   chosen for every frame.
2. That equality holds for 15m/30m/1h/4h, where 30 days is thousands of bars.
   On 1d it is 33 bars, and nothing compares 33 against the 300-bar lookback.
3. `Sep 22, 2026 8:40am` — counted on the operator's store: v2 holds **1,001**
   pair files at 15m, **1,002** each at 30m/1h/4h and **0** at 1d. v1 holds
   **1,080** at 1d. The v2 row index agrees independently: 9,203,416 rows at
   15m, 9,535,482 at 30m, 7,877,860 at 1h, 4,085,552 at 4h, **none** at 1d.
4. `9:05am` — measured on BTC: 49,799 stored minutes = 34.6 days; rebuilt to
   **33** daily bars against a **300**-bar warm-up. Measurable bars: **0**.
5. `10:1xam` — after the fix, the same pair: **2,300** daily candles from the
   venue, 300 warm-up, **29** measurable bars, 28 signals, **8 trades,
   2W/6L, −$6.95**.

**ROOT CAUSE** — the frame's bars were rebuilt from a feed (1-minute candles)
whose available history is shorter than the lookback every rule needs, so on
the coarsest frame there was nothing left to measure.

**WHY IT WAS NOT CAUGHT** — `tests/test_bars_from_minutes.py` proves
`bars_from_1m` is CORRECT, and it is: the bars it builds are the venue's own,
to the tick. Correctness of the conversion says nothing about the QUANTITY it
can be fed, and no test asked how many bars each frame ends up with. The
number that mattered was never computed anywhere — 44,000 minutes is a cap on
the download, 300 is a constant in the shard, and nothing multiplied them out
per timeframe.

It was also invisible from every direction a reader looks: the shard LOGS the
skip (`only 0 measurable bars, skipped`), but that line is one of thousands in
a fleet run; the store just has fewer files; and the panel shows the
timeframes it has rather than the ones it does not. **A timeframe that
produces nothing looks exactly like a timeframe nobody asked for.** The only
way it surfaced was counting v1 and v2 side by side.

**COST** — no money, no wrong number, no trade. Every daily strategy was
absent from Backtest v2 for five days (`Sep 17` – `Sep 22`), while the screen
gave no sign that daily was missing rather than empty.

**FIX** — this commit. `run_pair` fetches the frame's own candles for every
run (`at._closed_bars(fx.klines(sym, iv, cap), bs)`, the v1 line) and, when
`RES` is set, ALSO downloads the minutes purely to build `fine` for the exit
settlement. The minutes are an addition, never a replacement. Every bar in the
measured 30-day window has minutes beneath it (the store carries ~34 days) and
a bar without them falls back to the bar rule, which the engine already does.
The now-unreachable `except ValueError` that caught `bars_from_1m`'s
missing-minute refusal is removed rather than left to swallow an unrelated
fault and silently skip a pair.

**GUARD** — `tests/test_v2_measures_on_github.py::test_v2_ADDS_the_minutes_it
_does_not_replace_the_bars_with_them`: the frame's own candles are fetched for
v1 and v2 alike, `bars_from_1m` is not called in the shard at all, and the
minutes are still fetched for the exit. The arithmetic that caused it —
30 days of minutes is 33 daily bars against a 300-bar lookback — is written
into the test so the next reader meets the number, not the symptom.

---

## RCA-2026-09-22-B — one account refusing threw away the other account's run, twice, and left 1,062 coins measuring for nobody

**CEO**

* Pressing BACKTEST on GitHub answered "Internal Server Error" — twice — and
  each time, before the error, a run had ALREADY started on your partner's
  machines. Two runs of 531 coins each were measuring with nothing on this PC
  recording them, so their results would never have been collected.
* Why: the press sends half the board to each account. The partner's account
  did not yet have permission to start runs on YOUR repository, so the second
  half failed — and the code treated one account's refusal as the whole press
  failing, after the first account was already working.
* What stops it now: an account that refuses is named, with how many coins it
  did not take, and the run that DID start is kept and recorded. Only if every
  account refuses is the press an error. (The permission itself is fixed too —
  the partner's account now has write access to your repository.)

**DEV**

* `cloud_sweep.dispatch_across` built its runs with a list comprehension, so
  the first `CloudError` from `dispatch()` propagated out of the whole call —
  past the runs already started, past `cs.remember()`, and out of
  `POST /api/cloud/dispatch` as a 500. The loop collects failures now:
  successes are returned, failures go in `refused` with their reason,
  `unmeasured` carries the coin count, and only an empty `runs` raises.
* Invariant broken: **work that has started is recorded** — and rule 20, a
  run that measured half a board says which half it missed.
* Guard: `tests/test_forty_machines_across_two_accounts.py::test_a_refusing_account_does_not_throw_away_the_run_that_started`
  and `::test_every_account_refusing_is_still_an_error`.

**SAW** — `Sep 22, 2026 7:43pm` and `7:44pm`: `http 500` from
`/api/cloud/dispatch`, `.run/api.log` ending
`CloudError: could not create workflow dispatch event: HTTP 403: Must have
admin rights to Repository`, and `gh run list --repo jeremydvera/analyzer-x`
holding **three** queued "Market sweep" runs — two of them orphans from those
presses, 1,062 coins between them.

**TIMELINE**

1. `Sep 21, 2026 10:51pm` — the operator asks for 40 machines; the fork is
   added as a second fleet and `dispatch_across` ships.
2. `Sep 22, 2026 7:43pm` — BACKTEST pressed. The fork accepts (20 machines
   start on 531 coins); the operator's own repo refuses `jeremydvera` with
   403; the press answers 500 and records nothing.
3. `7:44pm` — pressed again, same thing: a second orphan run.
4. `7:45pm` — `jeremydvera` invited to the operator's repo with write access
   and the invitation accepted from here; the press then answered 200 with
   both runs (`35723247890` on the fork, `35723261621` on the operator's).
5. `7:51pm` — the two orphans cancelled by hand; at `7:55pm` the real pair
   was measuring with 20 machines on one account and 6 on the other (its CI
   run held the rest of that account's capacity).

**ROOT CAUSE** — a multi-target dispatch written as one expression, so the
first failure discarded every success beside it.

**WHY IT WAS NOT CAUGHT** — the 15 tests written with the feature drove the
splitter with a dispatch that always succeeded; the one failure case they
covered was `usable_fleets()` returning nothing, which fails BEFORE anything
starts. A partial failure only exists when one call has already worked, and
no fixture made one call behave differently from another.

**COST** — none in money (public repos, free machines); two orphan runs of
531 coins each, cancelled before they finished, and ten minutes.

**FIX** — this commit.

**GUARD** — `tests/test_forty_machines_across_two_accounts.py::test_a_refusing_account_does_not_throw_away_the_run_that_started`.

---

## RCA-2026-09-22-E — the machine tiles had shown nothing for EIGHT DAYS, and a 40-machine press could only ever have shown 20

**CEO**

* You asked why there was no loading on screen while 30 machines were
  measuring Backtest v2. The tiles were blind: they had shown nothing since
  Sep 14, 2026 4:51pm — eight days, every run.
* Why: the app reads each machine's progress out of the repo over git, and a
  progress read that was cut short on Sep 14 left a lock file behind. Every
  read since answered "another git process is running" and gave up. On top of
  that, the reader only ever looked in YOUR copy of the repo, so your
  partner's machines could never appear, and the tile followed their run,
  which was still queued.
* What stops it now: a lock left by a dead read is cleared and the read is
  retried; each account's machines are read from that account's own copy and
  shown together with the account's name on the tile. Right now that is 35
  machines reporting — 20 of yours and 15 of the partner's.

**DEV**

* `cloud_sweep._fetch_progress` used `--depth=1`, which takes
  `.git/shallow.lock`; this reader kills a fetch at 180 s and the kill never
  removed it. `_clear_dead_lock()` now runs before every progress fetch
  (older than `DEAD_LOCK_S = 600 s`) and after any git refusal naming a
  `.lock`, then retries — the same shape as the `cannot lock ref` repair
  beside it.
* `cloud_sweep.live_progress(run_id, slug)` ignored `slug` and read
  `origin/sweep-progress`; it now resolves the fleet's remote
  (`remote_for(slug)`), reads THAT branch, caches per `(run, remote)` and
  tags each machine with `repo`/`run`, while `api._read_cloud_status` appends
  every sibling's machines and counts, and `JobsPanel` keys a tile by
  `repo#shard` (both runs number machines 0..19).
* Invariant broken: **THE UI IS THE SOURCE OF TRUTH** — and its corollary
  from Sep 10, *a blocked resource names its holder*: git named the holder in
  a string nobody read, once per poll, for eight days.
* Guard: `tests/test_the_panel_sees_every_accounts_machines.py` (8).

Found by pressing the real screen, and fixed in the same commit: `JobsPanel`'s
poll began `if (store !== "v1") return;` — written before Backtest v2 moved to
GitHub — so the v2 tab never fetched the cloud status at all and the v1 tab
drew a run that was not its own. Each tab now shows the run whose `res`
matches its store; `runProgress` adds one board PER RUN (it took the max
across both, counting 35 machines' coins against one account's 499); and
`/api/cloud/merge` hands a v2 run to the `collect_v2` job with its repo rather
than collecting it in the API's v1 environment, where `land_rows` would refuse
every row.

**SAW** — the panel: *"no machine has reported through GitHub's API yet"*
with 30 machines working; `.git/shallow.lock` dated `Sep 14, 2026 4:51pm`
(the same bytes as `.git/shallow`, 6,888 of them); and
`cs.live_progress(35740445165, "jeremydvera/analyzer-x")` returning `[]`.

**TIMELINE**

1. `Sep 14, 2026 4:51pm` — a progress fetch is killed at its 180 s timeout
   and leaves `.git/shallow.lock`.
2. `Sep 14 → Sep 22` — every progress read fails with `fatal: Unable to
   create '…/.git/shallow.lock': File exists`, caught and printed as one
   line into the API log. The panel's empty state reads "no machine has
   reported", which is also what a GitHub rate-limit looks like, so it never
   read as a fault.
3. `Sep 22, 2026 10:27pm` — Backtest v2 across two accounts, 40 machines.
4. `11:14pm` — the operator asks why nothing is loading. The lock is found
   and removed by hand; a hand fetch of the partner's branch takes **80 s**
   and then `live_progress` returns **15** machines for the fork and **20**
   for the operator's account, 6,146,000+ rows measured between them.
5. `11:30pm` — both faults fixed, 45 tests over the cloud suites green.
6. `11:52pm` — pressing the real screen finds the third fault: Backtest v2
   drew nothing because it never fetched the cloud status. After the fix,
   measured in a real browser on `/backtest-v2`: **35** machine tiles named
   by account (`machine 0 · jeremydvera`), a `2 accounts` badge and
   `456/997 coin(s)`; `/backtest` shows none of it, which is correct — that
   run is a v2 run.

**ROOT CAUSE** — a lock file from a killed fetch that nothing cleaned, and a
progress reader that knew only one account.

**WHY IT WAS NOT CAUGHT** — `test_cloud_sweep.py` covers `_fetch_progress`'s
`cannot lock ref` race, which is the OTHER lock git takes; nothing covered
the one `--depth=1` adds, because no test ever kills a fetch. And every
progress test drives one run on one remote — the multi-account press was
added on Sep 21 and its 15 tests are about SPLITTING coins, not about
reading back. **When a feature grows a second target, re-read every path that
reported on the first one.**

**COST** — none in rows or money; eight days of a screen that could not tell
a healthy run from a dead one, and one press the operator could not watch.

**FIX** — this commit.

**GUARD** — `tests/test_the_panel_sees_every_accounts_machines.py::test_a_killed_fetchs_lock_is_cleared_and_a_live_one_is_not`
and `::test_the_tile_gets_every_accounts_machines`.

---

## RCA-2026-09-22-D — UPDATE THIS BACKTEST answered "Internal Server Error" on Backtest v2 while the table was getting its id list

**CEO**

* Pressing UPDATE THIS BACKTEST on #XLV6V5HJ (XPIN, 1 hour, mom6) in Backtest
  v2 answered **"Internal Server Error"**. Nothing was wrong with the press
  and nothing was lost.
* Why: Backtest v2's table has grown to **30,702,310 rows** and it is building
  the sorted list that finds a strategy by its code. Until that finishes, the
  app cannot look an id up — and instead of saying so, it crashed.
* What stops it now: the button says the real sentence — *"finding row
  #XLV6V5HJ needs the rows_id index; it is being built NOW … Nothing is
  lost"* — the same answer the strategy list and the CSV have given for a
  month.

**DEV**

* `api.strategy_row_update` (`tradingagents/api.py:1079`) called
  `ri.query(row_id=rid, limit=1)` bare. `rows_index.query` raises
  `SortNotReady` when a sort index is missing or being built; the two other
  doors (`/api/strategies` since 2026-08-26, the CSV export) translate it to
  `503` with `str(exc)`, this one did not exist when that was written.
* Invariant broken: **a store that is not ready yet is a 503 that says why**,
  never a 500 — the same shape as the `JobBusy` 409 this very route was given
  on Sep 17, 2026.
* Guard: `tests/test_the_row_update_says_why_it_cannot_look_up_yet.py`,
  including `::test_every_door_that_queries_the_index_answers_503_not_500`,
  which COUNTS `ri.query`/`ri.export_plan` calls against
  `except ri.SortNotReady` handlers so the next door cannot be added without
  one.

**SAW** — `Sep 22, 2026 10:47pm`: `POST /api/strategies/XLV6V5HJ/update?store=v2`
→ `Internal Server Error`, `.run/api.log` ending
`tradingagents.rows_index.SortNotReady: finding row #XLV6V5HJ needs the
rows_id index; it is being built NOW`.

**TIMELINE**

1. `Sep 22, 2026 10:27pm` — Backtest v2 dispatched to 40 machines; the v2
   table stands at 30,702,310 rows, 11.39 GB.
2. `10:47pm` — UPDATE pressed on #XLV6V5HJ to time the press end to end.
   500. `ri.build_running()` on the v2 store: `rows_id`.
3. `10:52pm` — the route translates it: 503 with the sentence, proved red on
   the pre-fix file.

**ROOT CAUSE** — a third door onto the index that never learned the answer
the other two give.

**WHY IT WAS NOT CAUGHT** — every test of this route drives a store whose
sort lists already exist, because the fixtures are small: a sort index on a
few hundred rows is built instantly by `ensure()`, so `SortNotReady` cannot
occur in a test that does not raise it deliberately. A failure that only
appears at 30 million rows has to be injected, not waited for.

**COST** — none in money or rows; one press, and a screen that said nothing
useful.

**FIX** — this commit.

**GUARD** — `tests/test_the_row_update_says_why_it_cannot_look_up_yet.py` (3).

---

## RCA-2026-09-22-C — the Backtest v2 press shut its own fast door and filed half its machines under the wrong store

**CEO**

* You asked for Backtest v2 on 40 machines. Both halves started and both are
  measuring with 1-minute candles — but this PC opened no fast door for them,
  so every result comes home the slow way (an hour after the run, instead of
  seconds after each coin), and this PC had written down that half of those
  machines were doing the OLD kind of backtest.
* Why: the fast door was still set up for the old backtest, and the code that
  swaps it for the new one tripped over itself and crashed; separately, the
  press now starts one run per account and only the FIRST one was recorded as
  the new kind. The second account's results would have been offered to the
  wrong filing cabinet, which would have refused them one by one.
* What stops it now: the swap works and is proved by a test that runs it; and
  every account's run is recorded with the kind of backtest it is doing. The
  run that is going right now was corrected by hand, so nothing is lost.

**DEV**

* `live_ingest.ensure` (`tradingagents/live_ingest.py:565`): the
  `log(f"the open door did not answer ({why}) …")` line sat one indent level
  out of the `else:` that assigns `why`, so the res-mismatch branch
  (`stop(); cur = {}`) fell into it with `why` unbound.
  `UnboundLocalError` → `dispatch`'s `except Exception` → `live_why`, and the
  press returned 200 with `live: false`.
* `cloud_sweep.remember` (`tradingagents/cloud_sweep.py:1332`) filed
  `RESFILE[run["id"]]` only. Since `dispatch_across`, the API passes
  `{**runs[0], "runs": runs}` — so run `35740488141` was filed `""` while its
  twin `35740445165` was filed `"1m"`, and `cloud_autopilot` picks the collect
  kind with `cs.run_res(rid)`.
* Invariants broken: **a swallowed failure still has to be readable** (a
  reason nobody can act on is not a reason), and **every started run is
  recorded** — the same rule RCA-2026-09-22-B bought, one field further in.
* Guard: `tests/test_every_account_run_knows_its_store.py` (4 tests; both
  fixes verified red on the pre-fix files).

**SAW** — `Sep 22, 2026 10:27pm`, the answer to the Backtest v2 press:
`{"id":35740445165, …, "live":false, "live_why":"UnboundLocalError: cannot
access local variable 'why' where it is not associated with a value"}`, and
`cs.run_res("35740488141")` returning `''` for a run dispatched with
`res=1m`.

**TIMELINE**

1. `Sep 22, 2026 7:51pm` — the v1 pair of runs starts; `live_ingest` opens a
   door for the v1 store (`res=""`) and leaves it open.
2. `8:59pm` and `9:38pm` — both v1 runs finish on their own, 22 of 22
   machines successful on each.
3. `10:27pm` — Backtest v2 pressed across both accounts. `ensure(res="1m")`
   sees the live v1 door, stops it, and crashes on the unbound `why`; the
   dispatch continues with `ingest_url=""`, so runs `35740445165` (partner)
   and `35740488141` (operator) start 40 machines with no live posting.
4. `10:29pm` — `run_res` reads `'1m'` for the first and `''` for the second.
   The res map is corrected by hand for the run in flight.
5. `10:33pm` — both fixes in, 4 new tests green, 79 tests over the cloud and
   v2 suites green.

**ROOT CAUSE** — one log line at the wrong indent, and one record written for
one run where a press now starts two.

**WHY IT WAS NOT CAUGHT** — `test_the_live_door_serves_ONE_store_and_says_which`
was written for exactly this branch and passes on the broken file, because it
reads the SOURCE for `cur.get("res")`, `stop()` and `_stores.V2.env_for()` —
all three present, all three at the right place, with the fault entirely in the
indentation of a fourth line. A source check cannot see a scope. And every
`remember` test passed a single-run dict, which is the shape that stopped being
the only one when "i want 40" shipped: when a caller's payload gains a plural,
re-test the singular AND the plural.

**COST** — none in money or rows: the artifacts still carry every row (the
live door is the fast path, never the record), and the mis-filed run was
corrected before it finished. What it cost is immediacy — this v2 run's rows
land after the run instead of during it.

**FIX** — this commit.

**GUARD** — `tests/test_every_account_run_knows_its_store.py::test_replacing_a_door_for_the_other_store_does_not_raise`
and `::test_every_account_run_is_filed_with_its_own_store`.

---

## RCA-2026-09-19-A — updating ONE strategy rewrote all 23,580 of that coin's rows, so a 25-second job took 48 minutes

**CEO**

* Pressing UPDATE THIS BACKTEST on #L5LUR5TG (FASTSTOCK, 15-minute, "prank"
  rule) took 48 minutes. Downloading that coin's new candles took about two
  seconds and re-testing the rule about twenty; the other 47 minutes were
  spent putting the answer away.
* Why: the searchable table keeps a coin's whole 15-minute block together —
  125 rules, **23,580 strategies** — and the code threw all of it away and
  wrote it back, although only the 180 rows of the one rule had changed.
* What stops it now: it writes back only the rule it measured. The same
  press writes 180 rows instead of 23,580 — about 130 times less work — and
  the screen's estimate counts the smaller job.

**DEV**

* `rows_index.index_pair` was `DELETE FROM rows WHERE pair = ?` plus a
  re-insert of the whole file (11.5 MB, 23,580 rows), each row re-filed in 8
  sort indexes: ~190,000 random writes at the 8.1 rows/s this spinning disk
  manages while `btupdate_v2` runs. `_run_pairbt` already passes ONE signal
  to `msw.run_pair`; it now passes the same `signals=` to `index_pair`,
  whose delete becomes `pair AND signal` and whose `pairs.n` is re-counted
  with `SELECT COUNT(*)` instead of `len(vals)`.
* Invariant broken: **write what changed** — and the two ways a partial write
  could lie are held by tests: a combination the new measure no longer
  produces must leave the table (the delete is by rule, not by id), and
  `SUM(n) FROM pairs` — the row count every screen prints — must still equal
  what the table holds.
* Guard: `tests/test_one_rule_is_written_back_not_the_whole_coin.py` (5) and
  `tests/test_row_update_button.py::test_it_refiles_only_the_rule_it_measured`.

**SAW** — `Sep 19, 2026 12:10am`, the row's own line:
`FASTSTOCK 15m · prank: writing 23,580 row(s) into the table — 2 min so far,
about 47 min left`, with `index_rows: 23580` in `/api/jobs/pairbt` while the
measure had produced 180.

**TIMELINE**

1. `Sep 18, 2026 11:22pm` — the operator presses UPDATE on #L5LUR5TG.
2. Seconds later the candles are current and the `prank` rule is measured:
   **180 rows**.
3. `index_pair` deletes the coin's 23,580 rows and re-inserts them; the
   estimate says 47 minutes and the button is disabled for all of it.
4. `Sep 19, 2026 12:30am` — `signals=` lands: the delete is by rule, 180 rows
   are written, and the ETA quotes 180.

**ROOT CAUSE** — the pair file was treated as the unit of writing because it
is the unit of storage.

**WHY IT WAS NOT CAUGHT** — every test of this path asserts that the row's
numbers CHANGE after the press, which a whole-coin rewrite satisfies
perfectly; none measured what the write cost. A correct answer that takes 130
times longer than it needs to has no failing assertion anywhere — it only
shows up as an operator asking why their one row takes an hour.

**COST** — none in money; about 45 minutes per press, and the single
re-measure slot held for that long, which is why a second row could not be
updated.

**FIX** — this commit.

**GUARD** — `tests/test_one_rule_is_written_back_not_the_whole_coin.py`.

---

## RCA-2026-09-18-N — the candle fill ran BACKWARDS over its own new bars, so XPIN's hourly history stopped three weeks ago

**CEO**

* You pressed UPDATE on #LG9NSU4B twice and the trade log still ended
  Aug 27, 2026 4:00pm — three weeks before today. The press worked both
  times; the candles it had to work with stopped on Aug 27.
* Why: yesterday's fix that fills a short history BACKWARDS took whichever
  copy of the candles was LONGER. For XPIN's hourly candles the longer copy
  was an old one that stopped on Aug 27, so it replaced the 522 fresh hours
  that had just been downloaded — every time, so the coin could never catch
  up.
* What stops it now: the two copies are merged instead of one replacing the
  other, so the oldest bar and the newest bar both survive. XPIN's hourly
  candles now run to Sep 18, 2026 7:00am and the row can be measured to
  today.

**DEV**

* `market_sweep.refresh_candles:466` — `if older is not None and len(older) >
  len(df): df = older`, where `older` is `fx.klines_backfill(...)`, i.e. the
  DISK kline cache grown at the FRONT. That cache is a different frame from
  the delta `fx.klines` just fetched and can end earlier; length was the only
  test. It is a `concat` + `drop_duplicates(subset="Date", keep="last")` now,
  with an assertion that the last bar can never move backwards.
* Invariant broken: **a repair may not undo the work it was run after** —
  and, in the store's terms, a pair's newest bar only ever moves forward.
* Guard: `tests/test_a_backfill_never_loses_the_new_tail.py` (3 tests: a
  longer-but-older backfill keeps both ends, the file on disk ends where the
  venue ends, and a backfill that raises still keeps the new tail).

**SAW** — `Sep 18, 2026 4:07pm`. `refresh_candles("XPIN_USDT", "1h")`:
`before: 2,813 bars, last 2026-08-27 13:00` → `after: 8,602 bars, last
2026-08-27 13:00` while `_klines_page("XPIN_USDT", "Min60", 2000, now)`
answered `2,000 bars, 2026-06-27 01:00 .. 2026-09-18 08:00`. The same coin's
other frames were current: 15m to Sep 15 5:45pm, 30m to Sep 15, 4h to Sep 15,
1d to Sep 14 — only 1h was stuck.

**TIMELINE**

1. `Sep 17, 2026 7:49pm` — `klines_backfill` ships (RCA-2026-09-17-A) with
   `df = older` whenever the backfilled frame is longer.
2. `Sep 18, 2026 3:01am` — the operator's UPDATE re-measures XPIN 1h over
   candles ending Aug 27: 220 rows, 175 trades, last trade Aug 27 4:00pm.
3. `4:00pm` — they press again and send the screenshot: still Aug 27.
4. `4:07pm` — reproduced in one call (above); the venue is proved to serve
   the missing hours.
5. `4:12pm` — merge instead of replace; `refresh_candles` reports `522`
   added and the store holds **9,124 bars to Sep 18, 2026 7:00am**.

**ROOT CAUSE** — "longer" used as a proxy for "more complete".

**WHY IT WAS NOT CAUGHT** — `tests/test_a_short_kline_cache_is_backfilled.py`
proves the FRONT is filled and that a full frame is left alone; both fixtures
have a backfill that ends at the same bar as the cache, so no test could tell
"longer" from "fresher". A repair's test must include the case where the
repair is WORSE than what it replaces.

**COST** — none in money. Three weeks of hourly candles missing for XPIN, two
presses of a button that could not have worked, and a row that read 175
trades over 117 days when it should read to today.

**FIX** — this commit.

**GUARD** — `tests/test_a_backfill_never_loses_the_new_tail.py`.

---

## RCA-2026-09-18-M — the UPDATE button on your XPIN row said "UPDATING… AMP 15m" about a row you never pressed

**CEO**

* Under #LG9NSU4B (XPIN 1h) the button read UPDATING… with "AMP 15m · ibs:
  index busy, retrying (2/3)" beside it. Nothing about AMP belongs on that
  row; the XPIN numbers on the same screen had already been brought up to
  date (175 trades, −5.68 USDT).
* Why: only one row can be re-measured at a time for the whole app, and the
  button showed THAT job whatever row it belonged to — so a job on another
  coin made your row look like it was working.
* What stops it now: the button compares the job's coin and timeframe with
  the row's own. Another row's job reads "AMP 15m is being re-measured first
  — one row at a time", and only this row's job can print UPDATING… or its
  result here.

**DEV**

* `StrategiesPanel.tsx:1987` — `pairJob?.running ? "UPDATING…"` and the two
  spans beside it read the single `/api/jobs/pairbt` payload with no
  comparison; `pairJob.pair` ("AMP 15m") was already in it. `jobIsThisRow`
  compares it with `${open.coin} ${open.tf}`.
* Invariant broken: **a label is derived from the data it describes**
  (label-must-match-data) — the presence of a job is not the fact "this row
  is updating".
* Guard: `tests/test_the_row_update_button_speaks_for_its_own_row.py`
  (3 tests over the button's words).

**SAW** — the operator's screenshot, `Sep 18, 2026 6:20am`: the XPIN 1h trade
log ("Log sum −5.68 USDT over 175 trades — losers cost −122.52, wins earned
+116.84"), and under it `UPDATING…   AMP 15m · ibs: index busy, retrying
(2/3)`.

**TIMELINE**

1. `Sep 18, 2026 6:13am` — a Playwright check of the UPDATE button (asked
   for: *"did you verify using playwright?"*) clicked it on the first row on
   screen, #VT6WUJXY (AMP 15m ibs), and the job started: `{"started": true,
   "pid": 15460}`.
2. `6:14am` — that job measured 60 rows and could not file them: an index
   build held the write lock, so it printed "index busy, retrying (2/3)"
   and left the pair queued.
3. `6:20am` — the operator opened #LG9NSU4B, whose own numbers had just
   been refreshed, and the button under it reported the AMP job.
4. `6:35am` — the button reads the job's pair; another pair's job is named
   as another pair's job.

**ROOT CAUSE** — one global job, shown on every row.

**WHY IT WAS NOT CAUGHT** — every test of this button drives ONE row and one
job, so the job always belonged to the row on screen; a second row was never
opened while a job ran. And the check that made it visible was run by me:
a browser test that clicks "the first row" leaves its job on the operator's
screen, which is its own lesson — a verification must not look like their
own work.

**COST** — none in money; a wrong sentence on the row they were reading.

**FIX** — this commit.

**GUARD** — `tests/test_the_row_update_button_speaks_for_its_own_row.py`.

---

## RCA-2026-09-18-L — UPDATE THIS BACKTEST answered "one job at a time" for every hour Backtest v2 was measuring

**CEO**

* Clicking UPDATE THIS BACKTEST on a stored row did nothing but flash an
  error while Backtest v2 was measuring: the app answered "btupdate_v2 is
  running — one job at a time, across both versions". For a 21-hour run that
  is 21 hours in which no row could be brought up to date.
* Why: there is a rule that stops two whole-market jobs fighting over the one
  hard disk. A single row's update is not a whole-market job — it is one coin
  on one timeframe, a few minutes — but the rule was checking the OTHER job
  without ever asking whether the thing being started was a big job at all.
* What stops it now: the rule applies only to the market-wide jobs it was
  written for. A one-row update starts whatever else is running, and a real
  click in Chrome proves it.

**DEV**

* `db_jobs.disk_holder:684` (extracted from `start()`, where the check has
  lived since `65d13cb9f5c8`) looped the `_DISK_JOBS` list for every caller;
  `pairbt` and `stratbt` are deliberately absent from that tuple, and the
  loop never tested `kind` for membership, so `start("pairbt", ...)` raised
  `JobBusy` and `api.strategy_row_update` turned it into `409`.
* Invariant broken: **a rule about sweeps applies to sweeps** — the small
  operator-pressed jobs are excluded from `_DISK_JOBS` on purpose and must be
  excluded from everything keyed on it.
* Guard: `tests/test_v2_surfaces_read_their_own_store.py::test_a_one_pair_remeasure_is_never_refused_for_a_sweep`
  (both small kinds start beside a running v2 sweep; both sweeps still yield,
  in both directions).

**SAW** — `Sep 18, 2026 5:35am`, a real Chrome click driven by Playwright on
`http://localhost:8503/backtest`: `POST /api/strategies/VT6WUJXY/update` →
**409**, body `{"detail": "btupdate_v2 is running — one job at a time, across
both versions; stop it or wait for it to finish"}`, and the page printing
that sentence under the button.

**TIMELINE**

1. `Sep 17, 2026 6:30pm` — `JobBusy` and the cross-version check land with
   the v2 store; `pairbt`/`stratbt` are left out of `_DISK_JOBS` but not out
   of the check.
2. `Sep 18, 2026 3:05am` — the operator's UPDATE on #LG9NSU4B measured 220
   rows (it started BEFORE `btupdate_v2`), and its filing was then blocked
   by the indexer pause (RCA-2026-09-18-K).
3. `3:40am` — `btupdate_v2` starts. From this minute every UPDATE THIS
   BACKTEST press is a 409.
4. `5:35am` — the button is clicked in a real browser for the first time
   instead of being reasoned about: 409, with the sentence above.
5. `5:45am` — `disk_holder` returns "" for any kind outside `_DISK_JOBS`;
   the same click is a 200 that starts a `pairbt` job.

**ROOT CAUSE** — a rule keyed on a list, applied to callers that are not in
the list.

**WHY IT WAS NOT CAUGHT** — `test_a_v2_job_waits_for_a_v1_job_and_the_other_way_round`
drives `start()` with the SWEEP kinds only, and every check of this button so
far went through the API function or the route, where the refusal is a
correct-looking 409 with a true-sounding sentence. The operator asked the
question that found it — *"did you verify using playwright?"* — and the
answer was no. A button is verified by clicking it (press-and-watch), in the
state the machine is actually in.

**COST** — none in money; two and a half hours in which no stored row could
be re-measured from the screen.

**FIX** — this commit.

**GUARD** — `tests/test_v2_surfaces_read_their_own_store.py::test_a_one_pair_remeasure_is_never_refused_for_a_sweep`,
plus the Chrome click re-run after the fix.

---

## RCA-2026-09-18-K — Backtest v2's 21-hour run froze the OLD screen's index, so UPDATE on #LG9NSU4B measured 220 rows nobody could see

**CEO**

* You searched #LG9NSU4B on the old Backtest screen, pressed UPDATE THIS
  BACKTEST, and the new numbers never appeared. The measuring worked — 220
  rows for XPIN 1h — but the step that copies them into the searchable table
  was switched off, and would have stayed off for the ~21 hours Backtest v2
  needs to finish.
* Why: the copier stands aside whenever a big job is running, so the two do
  not fight over the one hard disk. When Backtest v2's jobs were added they
  joined that list — even though Backtest v2 writes only its own folder and
  never touches the old store's files. You were right: they are separate.
* What stops it now: the copier only stands aside for jobs that write the
  store IT is filling. While the other one is measuring it still shares the
  disk politely — it copies the rows you pressed UPDATE on straight away and
  leaves the 5,270-pair backlog until that job ends — so neither screen
  freezes and neither run is starved. (The six-hour full rebuild still
  yields to both; that one really is about the disk.)
* One more thing the same hunt found: a test run at 4:38am emptied the real
  queue-jump list, so XPIN 1h lost the place the UPDATE press had given it.
  That file is now inside the test sandbox, with the pending list.

**DEV**

* `rows_index.busy_job:294` looped `for kind in db_jobs.FILES` and returned
  the first running kind; `FILES` gained `download_v2`/`backtest_v2`/
  `btupdate_v2` on Sep 17. `_machine_is_busy()` gates `sync`
  (`:1069`), `sync_in_background` (`:1874`) and the indexer loop (`:4608`),
  so `btupdate_v2` paused all three. `pairbt` had already failed its own
  three filing attempts with `OperationalError: database is locked` and left
  `index_queued: true` for a catch-up that could not run.
* Invariant broken: **a store's index yields to the jobs that write THAT
  store** — plus CLAUDE.md's *THE UI IS THE SOURCE OF TRUTH, SO IT IS KEPT
  CURRENT*: a 21-hour pause is the RCA-2026-09-14-B silence with a different
  cause. `other_store_job()` is the second half: the other version's job
  shares the platter, so the loop files only `_asked()` pairs while it runs
  and `status()` carries `deferring_to` for the panel's third sentence.
  `ASKED_FIRST` (added Sep 18) was outside the conftest sandbox and
  `test_the_sandbox_covers_every_path_constant_it_can_find` was RED for it
  at the time, in a suite with two other long-standing Windows reds.
* Guard: `tests/test_v2_surfaces_read_their_own_store.py::test_a_v2_job_does_not_pause_the_v1_index`
  (v2 job → v1 keeps filing; v1 job → v2 keeps filing; each still yields to
  its own) and `::test_the_rebuild_still_yields_to_both_because_it_is_the_disk`.

**SAW** — `Sep 18, 2026 4:45am`, `GET /api/strategies`: `"stale": 5270,
"paused": true, "paused_by": "btupdate_v2", "indexer_running": true`; and
`GET /api/jobs/pairbt`: `{"pair": "XPIN 1h", "rows": 220, "indexed": 0,
"index_error": "OperationalError: database is locked", "index_queued": true,
"note": "XPIN 1h · ote: 220 row(s), 0 indexed · measured, waiting on the
index"}`.

**TIMELINE**

1. `Sep 17, 2026 6:30pm` — `download_v2`, `backtest_v2` and `btupdate_v2`
   join `db_jobs.FILES`; nothing asks whether they write v1's files.
2. `Sep 18, 2026 3:05:52am` — UPDATE THIS BACKTEST on `#LG9NSU4B`: `pairbt`
   measures XPIN 1h ote, 220 rows, and its 3 filing attempts (20 s apart)
   all raise `database is locked`; the pair is queued for the catch-up.
3. `3:40:11am` — `btupdate_v2` starts: 4,012 pairs, ~21 hours at the
   measured 2.99 pairs/min.
4. From that minute the v1 indexer prints *"paused: a btupdate_v2 is
   running (5,270 pairs waiting)"* every cycle — including XPIN 1h, the one
   the operator pressed.
5. `4:38am` — a local test run rewrites the real `rows_index_asked.json`
   to `[]`: XPIN 1h loses its queue-jump place too.
6. `4:50am` — `busy_job()` reads the store it is filling: with
   `btupdate_v2` running, v1 answers `""` and v2 answers `"btupdate_v2"`.
7. `5:05am` — round 4 of the harddev loop: filing the whole 5,270-pair
   backlog beside the v2 sweep would starve it (measured 36 pairs/hour
   against 220 when a trickle fought a sweep), so while the other store's
   job runs only `_asked()` pairs are filed — seconds of work — and the
   backlog waits. The v2 sweep's rate across the change: 2.99 → 3.11
   pairs/min.

**ROOT CAUSE** — a pause meant for "do not fight the big job on this store"
was applied to a job on the OTHER store, because the list it reads is every
job kind rather than every job that writes these files.

**WHY IT WAS NOT CAUGHT** — `test_the_indexer_is_never_allowed_to_stay_dead`
and `test_index_stall_is_visible` (31 tests between them) assert that the
indexer PAUSES for a running job and says which — never that it must NOT
pause for a job it shares nothing with. The v2 work added three kinds to a
list five guards read and I checked the three guards about correctness, not
the two about yielding. The review's own ops reader raised this as finding
32 and I fixed its rebuild-gate half and left this half.

**COST** — none in money; the old screen could not show a re-measured row
for the 1 h 45 min between the press and this fix, and would not have for
~21 h.

**FIX** — this commit.

**GUARD** — `tests/test_v2_surfaces_read_their_own_store.py::test_a_v2_job_does_not_pause_the_v1_index`,
`::test_the_backlog_waits_for_the_other_store_but_a_pressed_row_does_not`, and
`tests/test_tests_cannot_write_the_real_home.py::test_the_sandbox_covers_every_path_constant_it_can_find`
(now watching `rows_index.ASKED_FIRST` and `pending_ledger.STATE_DIR`).

---

## RCA-2026-09-18-A — the row you pressed UPDATE on was filed 5,095th of 5,272

**CEO**

* You pressed UPDATE on #LG9NSU4B and it worked — but your screen kept showing
  the old numbers, so it looked like it had not.
* The new numbers WERE saved to your disk at 3:01am. The app files them into
  its search list afterwards, and your coin went to the back of a queue of
  5,272 — position **5,095**. It would have been days.
* What stops it now: a coin you press UPDATE on goes to the FRONT of that
  queue instead of the back. XPIN moved from 5,095th to 1st the moment it
  was asked for.

**DEV**

* `rows_index.stale_pairs()` returned never-indexed-then-changed, both
  alphabetical, with no notion of a hand-requested pair. `db_jobs._run_pairbt`
  retries `index_pair` three times, 20 s apart, and every attempt lost the
  write lock to the indexer's bulk transaction.
* Invariant: **THE UI IS THE SOURCE OF TRUTH, SO IT IS KEPT CURRENT**
  (CLAUDE.md). A measurement the operator watched succeed, which cannot reach
  the screen for days, has not updated anything they can see.
* Guard: `tests/test_the_operators_own_ask_is_filed_first.py`, 9 tests;
  removing the jump turns the one that drives the real `stale_pairs()` red.

**SAW** — the operator, `Sep 18, 2026`, after the UPDATE job finished cleanly:
*"is download done now / contunue"* — with the row still reading its old
figures.

**TIMELINE**

1. `Sep 18  12:25am` — the blocking candle download finishes, 1,003 of 1,003.
2. `Sep 18  ~3:00am` — the pairbt job runs and MEASURES correctly: XPIN 1h
   `ote`, **175 trades, 136 won, 39 lost, −$5.73 over 117 days**, written to
   `XPIN-1h.json` at `3:01am`.
3. It then tries to file the rows three times, 20 s apart —
   `index busy, retrying (1/3) … (2/3) … (3/3)` — and gives up, reporting
   honestly: *"220 row(s), 0 indexed · measured, waiting on the index"*.
   No "died" note this time.
4. The screen still shows the OLD row: **50 trades, +$36.97 over 29 days**.
5. `Sep 18  3:05am` — measured why retrying cannot work: six independent
   attempts to take the write lock, 10-second wait each, **0 of 6 got in**.
   The indexer holds it in one long bulk transaction over the backlog.
6. Measured the queue: XPIN 1h at position **5,095 of 5,272**.
7. After the fix: position **1 of 5,272**.

**ROOT CAUSE** — nothing in the filing order knew the difference between a
pair the nightly sweep happened to rewrite and a pair a person pressed a
button for and is watching.

**WHY IT WAS NOT CAUGHT** — every test of this button asks whether the
MEASUREMENT landed, and it always did. The button's own suite
(`test_row_update_button.py`, 17 tests) even has
`test_a_locked_index_says_WAITING_not_FAILED`, which pins the honest wording
for exactly this case — so the failure mode was known, named, and considered
handled by wording it politely. **A truthful message about an unbounded wait
is still an unbounded wait**; "queued" needed a number beside it, and once it
had one (5,095) the wording stopped being the answer.

**COST** — no money. One strategy's real result — a LOSS of $5.73 where the
screen promised a $36.97 profit — was invisible, on the number the operator
picks deployments by.

**FIX** — this commit. `rows_index.ask_first(pair)` keeps a small capped list
(`ASKED_MAX = 200`) and `stale_pairs()` returns those first; entries drop
themselves as soon as the pair is no longer stale, so nothing can stay pinned
to the front. `db_jobs._run_pairbt` calls it on the filing-failed branch only.
Every failure path is swallowed — a queue hint must never fail a good
measurement.

**GUARD** — `tests/test_the_operators_own_ask_is_filed_first.py`:
`test_stale_pairs_puts_the_asked_pair_first` builds 301 real pair files, drives
the REAL `stale_pairs()`, and asserts XPIN starts buried past position 250 and
ends first with nothing lost or duplicated;
`test_an_asked_pair_that_is_no_longer_stale_leaves_the_list`;
`test_the_list_is_capped`; `test_a_missing_or_broken_file_is_an_empty_list`;
`test_an_unwritable_file_never_breaks_the_caller`;
`test_the_job_asks_when_it_cannot_file` (and only on the failure branch).
The first draft of the ordering test re-implemented the ordering inline and
asserted on its own copy — proving the test could add, not that the code
could; it drives the real function now.

---

## RCA-2026-09-18-B — the v1 backtest died at 96% because the screen's progress file was busy for a fifth of a second

**CEO**

* At 7:31pm on Sep 17 the market-wide backtest stopped at 3,948 of 4,124
  coins, and the Backtest screen has said "process died before finishing"
  since. Every finished coin was kept; the last 176 were never measured.
* Why: after each coin the job rewrites the small file the screen reads. On
  Windows that rewrite is refused while anything else has the file open, and
  the job gave up after a fifth of a second and treated a refused screen
  update as a fatal error.
* What stops it now: the rewrite keeps trying for three seconds, and even
  past that a failed screen update is printed once a minute and the
  measuring goes on — the screen may lag, the run may not die.

**DEV**

* `db_jobs._write:132` — 40 attempts x 5 ms, then `raise` out of
  `_run_backtest_inner` → `prog` → `_publish` (`grid_from_store:1063
  _say → progress`); the per-pair callback carried the exception to the
  job's top level. The traceback in `db_backtest.log` reads `PermissionError:
  [WinError 5] Access is denied: 'db_backtest.json.20768.4772.tmp' ->
  'db_backtest.json'`.
* Invariant broken: **telemetry never ends a run** — the progress file is
  read by the screen and resumed from by nothing; a write the OS refuses is
  a sentence in the log, not a crash.
* Guard: `tests/test_a_progress_write_never_ends_a_run.py` —
  `test_the_replace_outlasts_a_reader_that_holds_the_file` (46 refusals,
  then it lands), `test_a_refused_progress_write_is_swallowed_and_said_once`,
  `test_every_mid_run_progress_write_is_forgiving` (all 7 `running: True`
  writes go through `_write_progress`; terminal writes stay loud).

**SAW** — `Sep 18, 2026 3:05am`, `~/.tradingagents/db_backtest.json` last
written `Sep 17, 2026 7:31pm` reading `running: true, done: 3948, total:
4124, pct: 95.73`; `db_jobs.status("backtest")` resolving it to *"process
died before finishing"* (pid 22540 gone); the traceback above in
`db_backtest.log`.

**TIMELINE**

1. `Sep 17, 2026 7:31pm` — pair 3,948 of 4,124 finishes; `prog` publishes;
   `tmp.replace(db_backtest.json)` is refused 40 times in 0.2 s (the API's
   poll or the antivirus held the file); the 41st raises.
2. The exception leaves `grid_from_store` through `_say`; the pool's
   in-flight pairs finish and are checkpointed; the job exits with the
   progress file still saying `running: true`.
3. `7:50pm` — the runner and API restart (a start.py restart); the
   supervisor's `resume_if_died("backtest")` answers *"measuring moved to
   GitHub Actions — a crashed local sweep is not restarted here"*
   (`capacity.LOCAL_SWEEPS` is False on this PC), so the run stays dead.
4. `Sep 18, 2026 3:05am` — found while checking which jobs held the disk
   before pressing UPDATE on Backtest v2. `_write` waits up to 3.0 s with a
   growing pause; the 7 mid-run progress writes go through
   `_write_progress`, which swallows and prints once a minute.

**ROOT CAUSE** — a 0.2 s budget for a Windows rename that a reader can hold
longer than that, raised out of a callback that had no business being fatal.

**WHY IT WAS NOT CAUGHT** — the Aug 25 fix for the same rename
(`f7e756acde7a`) added the retry and a test that the retry exists; nothing
asked what happens when the retry is NOT enough, because "40 tries" read as
"always enough". A budget is a number, and a number needs its failure path
tested, not its happy path.

**COST** — none in money; 176 coins of a v1 sweep unmeasured until it is
re-run.

**FIX** — this commit.

**GUARD** — `tests/test_a_progress_write_never_ends_a_run.py` (9 tests).

---

## RCA-2026-09-18-C — every row on the v1 Candles screen's pending list was a test fixture

**CEO**

* The Candles screen's RESOLVE PENDING count came from a list of 11 "coins
  the last download lost" — C0 to C7, FLAKY, NAORIS and MEZO — and none of
  them was a real download. They were written by the automated tests, some
  since Sep 09, and re-written every time the tests ran.
* Why: the tests that exercise the download run the real download code,
  which records lost coins in a file, and that file's folder was the real
  one, not a test folder.
* What stops it now: every test gets its own folder for that file, a test
  proves it, and the 11 fixture rows were removed from the real list.

**DEV**

* `pending_ledger.STATE_DIR = Path.home() / ".tradingagents"` was never
  sandboxed: `tests/conftest.py` swaps `db_jobs.STATE_DIR`/`FILES` but not the
  ledger's folder, so `tests/test_download_retry.py` → `_run_download` →
  `_pl.record("candles", ...)` (`db_jobs.py:1313`) wrote fixtures into
  `~/.tradingagents/pending_candles.json`.
* Invariant broken: **a test writes only under its own tmp_path** — the
  sandbox fixture must cover every module that writes to the home folder.
* Guard: `tests/test_tests_never_write_the_operators_ledger.py` (no fixture
  of its own; proves the sandbox is what a test sees) and the conftest
  sandbox itself.

**SAW** — `Sep 18, 2026 3:10am`, `GET /api/candles/pending` counting 11;
`pending_ledger.pending("candles")`: MEZO_USDT 15m (32 fails), C0_USDT to
C7_USDT 1h (19 fails each), FLAKY_USDT 15m (12 fails, `timed out`),
NAORIS_USDT 30m (1 fail) — every `why` the CLAUDE.md quote
`IncompleteRead(183452 bytes read)` or the fixture's `timed out`.

**TIMELINE**

1. `Sep 09, 2026 1:40pm` — the first fixture rows land (C0–C7, MEZO) as the
   download-retry tests run.
2. `Sep 17, 2026 7:48pm` and `10:40pm` — this session's test runs re-write
   them (`last` stamps on all 11 rows).
3. `Sep 18, 2026 3:12am` — `pending_ledger.clear("candles", <all 11>)` →
   0 rows; the conftest sandbox points `pending_ledger.STATE_DIR` at the
   test's folder from now on.

**ROOT CAUSE** — one module writing to the home folder was left out of the
test sandbox.

**WHY IT WAS NOT CAUGHT** — the ledger's own tests set `STATE_DIR` to
`tmp_path` and so never saw the real file; the download tests asserted on
what the download DID, not on where the ledger wrote. Found by a reviewer
reading the live file, not by any test.

**COST** — none in money; a false "11 pending" on the Candles screen for
nine days.

**FIX** — this commit (sandbox + data fix).

**GUARD** — `tests/test_tests_never_write_the_operators_ledger.py::test_the_ledger_a_test_sees_is_not_the_operators`.

---

## RCA-2026-09-18-D — the Backtest v2 report printed every row under its v1 twin's id

**CEO**

* The report file a Backtest v2 run writes named each of its 82,758 rows by
  the code of the OLD measurement of the same combination — so a code copied
  from that report finds nothing on the Backtest v2 screen, and finds the
  hour-bar row on the old screen.
* Why: the report re-stamps each row's code from its coin, timeframe, rule,
  target, stop and sizing, and the piece that says "measured to the minute"
  was left out of that stamp.
* What stops it now: the stamp includes it, on both places the report
  mints codes, and a test reads both.

**DEV**

* `backtest_report.grid_from_store:1529` and `run_grid:659` —
  `r["id"] = row_code(coin, tf, signal, th, sl, tp, sizing)` without
  `res=r.get("res")`, while `rows_index._row_id` passes it. The same dict
  `{XPIN, 1h, ote, 0, 3, 1, flat, res="1m"}` minted `LG9NSU4B` in the report
  and `U9YP5N7L` in the v2 table.
* Invariant broken: **one row, one id, on every page** (kit item H) and
  the v2 rule *a v2 row's id can never equal a v1 id*.
* Guard: `tests/test_v2_surfaces_read_their_own_store.py::test_both_report_minters_carry_res`
  and `::test_a_v2_row_and_its_v1_twin_never_share_an_id`.

**SAW** — `static/bt/archive-v2.html` written `Sep 17, 2026 7:57pm` by the
5-coin v2 backtest: 82,758 rows, ids equal to the v1 store's.

**TIMELINE**

1. `Sep 17, 2026 6:30pm` — `row_code(res=)` added and threaded through
   `rows_index._row_id`; the two report minters were not on the grep because
   they call `row_code` positionally.
2. `7:57pm` — the first v2 report is written with v1 ids on all 82,758 rows.
3. `Sep 18, 2026 3:00am` — found by the review's isolation reader with a
   two-line probe; both minters pass `res`.

**ROOT CAUSE** — a new id component added to one of three minters.

**WHY IT WAS NOT CAUGHT** — `test_a_v2_id_never_equals_the_v1_id` drives
`row_code` directly; no test opened the report the job writes and compared
an id in it with the table's. A rule about "every page" needs a test per
page.

**COST** — none.

**FIX** — this commit.

**GUARD** — `tests/test_v2_surfaces_read_their_own_store.py::test_both_report_minters_carry_res`.

---

## RCA-2026-09-18-E — Backtest v2's screen read the OLD store's index process as its own

**CEO**

* Several small readings on the Backtest v2 screen were about the old
  store, not the new one: whether "something is filling the table", which
  computer cores were working, and — had the new store grown past 200,000
  rows — a sort that needed a new index would have been built on the OLD
  store's file and the new screen would have said "being built" for ever.
* Why: the new store is served by the same app as the old one, and a few
  places read a fixed "the database" setting instead of "the database this
  request is about".
* What stops it now: every one of those places reads the store being
  served; the v2 screen says plainly that its rows are filed by the backtest
  job when it finishes; and a test holds each place.

**DEV**

* `rows_index._build_lock:2950`, `build_running:2963`, `_build_index:3096`,
  the spawn at `:3130` (`TA_ROWS_DB=str(DB_PATH)`) — module global under
  `using_db(v2)`; `status():4255` returned `_running_elsewhere()`,
  `syncing()`, `_last_error`, `lock_holder()` (v1 process state) for v2;
  `stale_watermark:847` parsed a ~9 MB state file whole (0.2 s a pair);
  `api.job_status:1338` `msw.worker_read()` (v1's folder);
  `_PAIR_WRITERS:790` lacked the v2 kinds; `api.strategies` wrote the
  screen log with no store.
* Invariant broken: **a request for store X reads store X** — every path
  under `using_db` resolves through `_db()`, never `DB_PATH`.
* Guard: `tests/test_v2_surfaces_read_their_own_store.py` —
  `test_the_build_lock_and_the_spawned_child_target_the_store_being_read`,
  `test_build_running_looks_beside_the_store_being_read`,
  `test_v2_status_does_not_borrow_v1s_indexer`,
  `test_stale_watermark_under_the_override_reads_the_tail_not_the_whole_file`,
  `test_worker_read_takes_another_stores_folder`,
  `test_the_rebuild_gate_knows_the_v2_kinds`;
  `tests/test_v2_jobs_have_no_cloud.py::test_a_v2_jobs_workers_come_from_the_v2_folder`.

**SAW** — `Sep 17, 2026 10:47pm`, `GET /api/v2/strategies` → `index:
{pairs_indexed: 5, pairs_on_disk: 5, indexer_running: true, paused_by:
"download_v2"}` — `true` is v1's run lock; nothing indexes v2.

**TIMELINE**

1. `Sep 17, 2026 8:00pm` — `using_db` lands with `_db()` on the readers
   (`_connect`, `has_index`, `stale_pairs`, `status` counts).
2. `10:47pm` — the review's live probe shows v1's `indexer_running` on the
   v2 payload; the index-build spawn, the lock and the workers list are
   found on `DB_PATH`/`WORKERS` by reading; v2 holds 82,758 rows, under the
   200,000 gate, so the wrong-store build NEVER HAPPENED YET.
3. `Sep 18, 2026 3:30am` — every listed spot reads the store being served;
   `status()` under the override answers `indexer_running: None`,
   `filed_by: "job"`; the panel prints "the v2 backtest files its rows when
   it finishes"; the watermark reads the file's tail through
   `pair_watermark(root=)`; `/api/v2/strategies` takes its index block from
   a 20 s background reader like v1.

**ROOT CAUSE** — a per-request store override added on the read paths while
the write/spawn paths and the process-liveness fields kept the module
global.

**WHY IT WAS NOT CAUGHT** — `tests/test_v2_store_is_its_own_folder.py`
asserts on the ENV a v2 JOB is spawned with, not on what the API PROCESS
(which has no env) does under the override; and a status payload's
liveness flags were asserted by no test on either store.

**COST** — none.

**FIX** — this commit.

**GUARD** — `tests/test_v2_surfaces_read_their_own_store.py` (12 tests).

---

## RCA-2026-09-18-F — every one-minute download paged 4,000 bars it had fetched seconds earlier

**CEO**

* Each of the 1,003 one-minute downloads on Sep 17 asked the exchange for
  two extra pages — about 2,006 requests over the evening — re-fetching
  bars it had just received and thrown away.
* Why: the app keeps a copy of each coin's candles on disk, trimmed to
  40,000 bars, and the one-minute frame asks for 44,000; so the copy could
  never satisfy the ask and the "fill the front" step always ran.
* What stops it now: the copy keeps 44,000 bars, at least as many as the
  largest ask, and a test compares the two numbers.

**DEV**

* `mexc_futures._KLINE_DISK_MAX = 40_000:1057` trimmed the cache
  (`_kline_disk_save:1131`) below `backtest_report.TFS["1m"][2] = 44_000`;
  `market_sweep.refresh_candles:463` saw `len(df) < cap` (43,999 after
  `_closed_bars`) and `klines_backfill` paged 2 x 2,000 bars every time.
* Invariant broken: **a cache holds at least what is asked of it** (the
  shape of RCA-2026-09-17-A, from the other side).
* Guard: `tests/test_v2_surfaces_read_their_own_store.py::test_the_kline_disk_cache_holds_a_full_1m_frame`.

**SAW** — `~/.tradingagents/kline_cache/CCJSTOCK_USDT_Min1.json.gz` at
40,000 bars after a 44,000-bar fetch, `Sep 17, 2026 10:50pm`, and two
backfill pages in the download log for the same pair.

**TIMELINE**

1. `Sep 17, 2026 7:49pm` — `klines_backfill` lands (RCA-2026-09-17-A) and
   runs whenever a frame is shorter than its cap.
2. `10:17pm`–`Sep 18, 2026 3:00am` — the 1,003-pair download: 22 pages for
   44,000 bars, trimmed to 40,000 on disk, 43,999 after the forming bar is
   dropped, 2 more pages per pair.
3. `Sep 18, 2026 3:30am` — the cap is 44,000.

**ROOT CAUSE** — two constants for one size, in two modules.

**WHY IT WAS NOT CAUGHT** — the backfill test fixes the cache at 40,000
bars deliberately (`T0 - 40_000 * 60`) and asserts that the front is
filled; a wasted request produces correct data and no failing assertion.

**COST** — none in money; ~2,006 avoidable venue requests.

**FIX** — this commit.

**GUARD** — `tests/test_v2_surfaces_read_their_own_store.py::test_the_kline_disk_cache_holds_a_full_1m_frame`.

---

## RCA-2026-09-18-G — a job rule added on one side and not the other: the resume counted refusals, the hand-off accepted v2

**CEO**

* NEVER HAPPENED YET. Two doors the one-job-at-a-time rule forgot: a job
  that crashed while another job held the disk would have used up all 20 of
  its restart attempts in ten minutes without ever starting, ringing
  "restarted after a crash" each time; and the "hand the rest to GitHub"
  button's back door accepted a Backtest v2 job and would have stopped it
  under a sentence about a cloud that has no one-minute candles.
* Why: the rule was written into the start button and not into the two
  other places that start or stop a job.
* What stops it now: the resume waits (and says so) without spending an
  attempt; a hand-off request for a v2 job is refused with the reason; both
  are tested.

**DEV**

* `db_jobs.resume_if_died:540` `_set_retries(kind, n + 1)` and the bell
  BEFORE `start()` (`:549`), which raises `JobBusy` (`:651`); the supervisor
  tick (`api.py:178`) swallows it every 30 s → 20 x 30 s = 10 minutes.
  `api.job_handoff:1362` accepted `backtest_v2`; `_finish_handoff:54` is
  hard-wired to `"backtest"`.
* Invariant broken: **a refusal is not an attempt**, and **a request the
  system cannot serve is refused, never accepted and dropped**.
* Guard: `tests/test_a_progress_write_never_ends_a_run.py::test_a_resume_waits_for_the_disk_without_spending_a_retry`,
  `::test_disk_holder_names_who_keeps_a_kind_off_the_disk`;
  `tests/test_v2_jobs_have_no_cloud.py::test_a_v2_handoff_is_refused_with_the_reason`,
  `::test_the_v2_handoff_state_says_no_cloud_is_available`.

**SAW** — nothing on a screen; `db_retries.json` read `{download: 0,
download_v2: 0, backtest_v2: 0}` on `Sep 18, 2026 3:05am`. Found by two
reviewers reading `start()` beside `resume_if_died()`.

**TIMELINE** (made-up numbers on the real mechanism)

1. A v1 download is killed mid-run by a start.py restart at 10:16pm; at
   10:17pm UPDATE CANDLES on Candles v2 starts the 1-minute download.
2. Ticks at 10:17:30, 10:18:00 … 10:27:00 — 20 `resume_if_died("download")`
   calls, each `_set_retries` +1 and a bell, each `start()` → `JobBusy`.
3. 3:00am — the disk is free; `resume_if_died` answers "gave up after 20
   retries"; the v1 download stays dead with `running: true` in its file.

**ROOT CAUSE** — one rule, three doors, one guarded.

**WHY IT WAS NOT CAUGHT** — `test_a_v2_job_waits_for_a_v1_job_and_the_other_way_round`
drives `start()`; nothing drove `resume_if_died` with the other version's
job running, and the hand-off route's tests never asked it about a v2 kind.
(CLAUDE.md, Sep 05: *grep for the CONCEPT — every guard keyed on the same
subject.*)

**COST** — none.

**FIX** — this commit (`disk_holder()` is the one
rule both doors read).

**GUARD** — `tests/test_a_progress_write_never_ends_a_run.py::test_a_resume_waits_for_the_disk_without_spending_a_retry` and `tests/test_v2_jobs_have_no_cloud.py::test_a_v2_handoff_is_refused_with_the_reason`.

---

## RCA-2026-09-18-H — a coin re-deployed from the old screen kept printing its Backtest v2 code

**CEO**

* NEVER HAPPENED YET. Deploy a coin from Backtest v2, then later deploy the
  same coin and rule from the old Backtest screen: the app would have gone
  on printing the Backtest v2 code for it everywhere — the code of a
  measurement the operator had just decided against.
* Why: the deploy remembered "this coin came from v2" and only ever ADDED
  to that memory; a deploy from the old screen wrote nothing, so the old
  memory stayed.
* What stops it now: a deploy from the old screen erases that memory for
  the coins it arms (other coins keep theirs), and the preview printed
  before any deploy says "Backtest v2 · minute-exact" on the rows that are.

**DEV**

* `deploy_preset.merged:168` merge mode `{**old, **_res_map(got)}`;
  `_res_map` emits nothing for a row without `res`, so a slot's `"1m"`
  survived a v1 re-arm and `api.row_id_for` kept hashing with it.
  `describe:203` printed no store.
* Invariant broken: **the printed id is the row that was deployed** (rule
  22, and the id rule of the v2 work).
* Guard: `tests/test_v2_surfaces_read_their_own_store.py::test_a_v1_redeploy_over_a_v2_slot_forgets_the_v2_id`,
  `::test_the_read_back_names_the_store`.

**SAW** — nothing on a screen (`strategy_res` landed Sep 17 and no coin has
been deployed from v2 yet); found by the review's deploy reader with a
two-call probe: after a v2 deploy `{"ote_1h_sl3tp1|XPIN_USDT": "1m"}`,
after a v1 re-deploy still `"1m"`, `row_id_for` → `U9YP5N7L`.

**TIMELINE** (made-up numbers on the real mechanism)

1. Day 1 — XPIN 1h ote TP 1% / SL 3% deployed from Backtest v2 as
   `#U9YP5N7L`.
2. Day 3 — the same rule and coin deployed from the old screen as
   `#LG9NSU4B`, merge mode; the screen keeps printing `#U9YP5N7L`.
3. `Sep 18, 2026 3:30am` — the merge forgets `strategy_res` for every slot
   the preset arms, then applies the preset's own; `describe` names the
   store.

**ROOT CAUSE** — a memory with an add path and no clear path.

**WHY IT WAS NOT CAUGHT** — `test_a_preset_row_from_v2_writes_strategy_res`
tests the write; nothing tested the deploy AFTER it.

**COST** — none.

**FIX** — this commit.

**GUARD** — `tests/test_v2_surfaces_read_their_own_store.py::test_a_v1_redeploy_over_a_v2_slot_forgets_the_v2_id`.

---

## RCA-2026-09-18-I — a Backtest v2 trade said it closed at 1:28am and was held "less than an hour"

**CEO**

* On every Backtest v2 trade log row the "held" column was still measured
  in whole candles while the "closed at" column beside it was measured to
  the minute: a trade that opened at 1:00am and closed at 1:28am printed
  "held <1h", and one closing at 11:28am after a 9:00am entry printed "2h
  0m".
* Why: the column that says how long a trade lasted was never taught about
  the minutes; only the closing time was.
* What stops it now: when the minutes settled the exit, "held" is the
  minutes too — "28m" — through the same formatter the live Positions
  table uses.

**DEV**

* `auto_trader.backtest_strategy:3141` — `"held": _held(i + 1, j)` bar to
  bar, beside `"exit time": fmt_when(_exit_min / 1000)`. Now
  `_held_fine(i + 1, _exit_min)` / `_held_s_fine` when `_exit_min` is set.
* Invariant broken: **two columns on one row read one clock**
  (label-must-match-data).
* Guard: `tests/test_v2_surfaces_read_their_own_store.py::test_held_follows_the_exit_minute_not_the_bar`.

**SAW** — the Backtest v2 trade log for `#U9YP5N7L` (XPIN 1h) on `Sep 17,
2026 8:50pm`: 585 rows, 42 exits off the hour, every `held` a whole number
of hours or `<1h`.

**TIMELINE**

1. `Sep 17, 2026 6:45pm` — `fine=` lands; `exit time` and
   `exit_minute_ms` read the minute; `held`/`held_s` untouched.
2. `8:50pm` — the log is opened in the browser with both columns on every
   row.
3. `Sep 18, 2026 3:30am` — fixed; the fixture with a stop at minute 28
   prints `held 28m`, `held_s 1680`.

**ROOT CAUSE** — a finer clock added to one of two columns that share it.

**WHY IT WAS NOT CAUGHT** — the minute-exact tests assert `exit time` and
`exit_minute_ms`; none asserted `held`.

**COST** — none.

**FIX** — this commit.

**GUARD** — `tests/test_v2_surfaces_read_their_own_store.py::test_held_follows_the_exit_minute_not_the_bar`.

---

## RCA-2026-09-18-J — Backtest v2 offered a CSV download that answered "not on Backtest v2 yet", for a reason that was no longer true

**CEO**

* With a "last 30 days" window on, the Backtest v2 screen offered
  "download the window's CSV"; clicking it gave an error saying the window
  reads the old store — which had stopped being true hours earlier when
  the window itself was fixed to read the one-minute store.
* Why: the table's window was fixed and the file's window was left refused
  with the old sentence.
* What stops it now: a days window exports from the one-minute store like
  the table; a months window (which the file cannot yet do) shows a plain
  sentence instead of a link, and the app's refusal says the true reason.

**DEV**

* `api.strategies_csv_v2:3214` raised 400 `_V2_NO_WINDOW` for `months or
  days` with a reason describing the pre-56ed9d67 code; `StrategiesPanel`
  rendered the link regardless of store. `strategies_csv_lines` and
  `rows_index.iter_rows` now take `store=` and pass it to
  `window_rows(store=)`; months is refused with the true sentence and the
  panel shows it instead of a link.
* Invariant broken: **a link promises what the route delivers**
  (label-must-match-data), and **a refusal states the true reason**.
* Guard: `tests/test_v2_routes.py::test_the_v2_csv_takes_a_days_window_and_names_the_months_gap`.

**SAW** — `/api/v2/strategies.csv?days=30` → `{"detail": "a days/months
window is not on Backtest v2 yet — the window re-measure reads the v1 candle
store…"}` on `Sep 17, 2026 10:50pm`, 35 minutes after the JSON window began
reading the v2 store.

**TIMELINE**

1. `Sep 17, 2026 10:15pm` — `restate_window(store=)` lands; the v2 table
   restates 30-day windows from the 1-minute store.
2. `10:50pm` — the review's live probe: the CSV route still refuses with
   the old reason; the panel still offers the link.
3. `Sep 18, 2026 3:30am` — days exports; months is a sentence.

**ROOT CAUSE** — a feature fixed on one of its two surfaces.

**WHY IT WAS NOT CAUGHT** — `test_v2_routes.py` asserted the CSV refuses a
window, so the test was green when the refusal became a lie: a test that
pins a limitation must also pin its REASON.

**COST** — none.

**FIX** — this commit.

**GUARD** — `tests/test_v2_routes.py::test_the_v2_csv_takes_a_days_window_and_names_the_months_gap`.

---

## RCA-2026-09-17-F — UPDATE THIS BACKTEST answered "Internal Server Error" whenever any other job was running

**CEO**

* You pressed UPDATE on strategy #LG9NSU4B and got **"Internal Server Error"**.
  Nothing was broken — a candle download was running, and this app only lets
  one job touch the store at a time.
* The app knew that and had the sentence ready: *"download_v2 is running —
  wait for it to finish"*. The button threw it away and showed a blank crash
  instead, so the one thing you needed to read never reached you.
* What stops it now: the button says which job is in the way, the same as the
  other job buttons already did. Pressed again for real, it answers
  *"download_v2 is running"* instead of a crash.

**DEV**

* `db_jobs.start` raises `JobBusy` when another kind holds the store
  (`db_jobs.py:651`). `api.py:1072 strategy_row_update` and `api.py:1916
  strategy_backtest` both called it bare, so the exception escaped FastAPI as
  a 500 — and it never reached `api.log` either, so there was no traceback to
  find. `POST /api/jobs/{kind}` (`api.py:1345`) has caught it and answered
  409 since it was written; two of the three call sites never learned.
* Invariant broken: **a job that cannot start must SAY SO** (CLAUDE.md,
  RCA-2026-09-10-C). A refusal is not a crash, and a 500 sends the operator
  to logs that do not have it.
* Guard: `tests/test_a_busy_machine_is_not_a_crash.py`, 6 tests. Reverting the
  fix turns 3 of them red.

**SAW** — the operator, `Sep 17, 2026`, on #LG9NSU4B (XPIN 1h, `ote`,
TP 1.0% / SL 3.0%, flat):

> *"when i click update this backtest for #LG9NSU4B im getting process died
> before finishing and the last closed trade was Aug 27, 2026 4:00pm"*

and, pressed for real: `HTTP 500, Internal Server Error`.

**TIMELINE**

1. `Sep 17, 2026 10:05pm` — an earlier press DID work: 220 rows measured and
   written to `XPIN-1h.json`. Its index step then failed on `database is
   locked` and the job was killed before clearing its own flag — which is why
   the screen read *"process died before finishing"*. That note was true.
2. A `download_v2` job then started (1-minute candles, 1,003 coins).
3. `Sep 17` — pressing UPDATE again returns **HTTP 500** with an empty body.
   The POST does not appear in `api.log` at all.
4. Calling `api.strategy_row_update("LG9NSU4B")` by hand names it at once:
   `tradingagents.db_jobs.JobBusy: download_v2 is running — one job at a
   time, across both versions; stop it or wait for it to finish`.
5. Three `start(` call sites in the API; **one** caught it.
6. After the fix, pressed again through the real route while the same
   download ran (244 of 1,003 coins, 24.3%, 10,342,038 bars stored):
   **HTTP 409**, `{"detail": "download_v2 is running — one job at a time..."}`.

**ROOT CAUSE** — `api.py:1072` and `api.py:1916` called `db_jobs.start()`
outside any `try`. The refusal was designed, the message was written, and two
buttons dropped it on the floor.

**WHY IT WAS NOT CAUGHT** — `tests/test_row_update_button.py` has seventeen
tests for this button, including `test_the_route_resolves_a_row_id_to_its_pair`
which asserts the 409 for *"already re-measuring"*. That is the SAME STATUS for
a DIFFERENT refusal — the button's own kind being busy — so the suite looked
like it covered "busy" and covered only half of it. **A route that can refuse
for two reasons needs a test per reason**; one passing 409 says nothing about
the other path. Nothing anywhere drove the route with a foreign job running.

**COST** — no money. One strategy could not be re-measured, and the operator
was sent looking for a crash that never happened.

**FIX** — this commit. Both routes catch `(JobBusy, LocalSweepsOff)` and raise
409 with the exception's own text. The browser already surfaces it:
`postDetail` parses `detail` into `ApiError.message` and `StrategiesPanel`
prints it in `updateErr`.

**GUARD** — `tests/test_a_busy_machine_is_not_a_crash.py`:
`test_the_row_update_button_says_what_is_busy` drives the real route with a
refusing `start`; `test_every_button_that_starts_a_job_catches_the_refusal`
walks each route's AST for an `except` naming `JobBusy`;
`test_no_route_starts_a_job_without_catching_it` does it over the WHOLE file so
a fourth button cannot reintroduce it; `test_the_exceptions_it_catches_actually
_exist` (an `except` naming a missing class crashes worse than the bug);
`test_a_free_machine_still_starts`.

**A GUARD THAT PASSED ON THE BROKEN FILE, CAUGHT IN THE HARDDEV LOOP** — the
first draft of the two AST tests grepped the source for the string `"JobBusy"`.
Both PASSED against the un-fixed code, because the comment explaining the fix
contains that word. A guard satisfied by a comment is satisfied by nothing;
they read `ast.Try` handlers now, and the revert turns 3 tests red instead of 1.

---

## RCA-2026-09-17-E — UPDATE CANDLES on Candles v2 said "nothing is downloaded again", then downloaded the whole market

**CEO**

* Pressing UPDATE CANDLES on the Candles v2 screen asked *"Update 5 stored
  pair(s)? Only the bars printed since each pair's last stored bar are
  fetched — nothing is downloaded again"*, and then started a run over
  **1,003** coins, each fetching 30 days of one-minute candles — about four
  hours of downloading behind a sentence about five coins.
* Why: an update has always also fetched every coin the venue lists that the
  store has never had. On the old screen that is a handful, so the sentence
  was near enough; the new store held five coins, so "the rest" was the whole
  market and the sentence was false.
* What stops it now: the box names both halves — the stored pairs it tops up
  AND the count of never-stored pairs it fetches in full — from the same
  numbers the screen already shows two lines lower.

**DEV**

* `webapp/src/components/candles/DownloadScreen.tsx` `update()`: the confirm
  was a literal string. `db_jobs._run_download(mode="update")` queues
  `pending_work(...)` = behind + missing; `/api/v2/candles/pending` answered
  `"missing": 998, "count_stale_or_missing": 1003` and the job's own progress
  file said `"total": 1003`.
* Invariant broken: **the number a button prints is the number of work it
  will DO** (label-must-match-data; RCA-2026-09-10-C's second fault, where a
  route printed `behind` for a job that walks `stale_pairs`).
* Guard: `tests/test_the_update_confirm_names_the_whole_queue.py` — the
  confirm reads `pending?.missing`, says "fetched in full", carries no typed
  duration, and the field it reads is one the route's type declares.

**SAW** — `Sep 17, 2026 10:17pm`, Candles v2, UPDATE CANDLES: the confirm
above; then `~/.tradingagents/db_download_v2.json` reading `{"running": true,
"done": 87, "total": 1003, "mode": "update"}` at `10:40pm`.

**TIMELINE**

1. `Sep 17, 2026 7:39pm` — the first Candles v2 download stored five coins'
   one-minute history (ARKM, GLM and XPIN among them); the v2 store held 5
   pairs, MEXC listed 1,003 contracts.
2. `10:17pm` — UPDATE CANDLES pressed on Candles v2. Confirm: *"Update 5
   stored pair(s)? … nothing is downloaded again."* The job queued 1,003
   pairs: 5 behind by 3 hours, 998 never stored.
3. `10:47pm` — 113 pairs done, 4,829,131 bars stored, 0 errors: about 3.8
   pairs a minute, so ~4.4 hours for the whole queue, not "nothing".
4. Fixed: the confirm prints `PLUS 998 pair(s) MEXC lists that this store does
   not have yet — those are fetched in full (30 days of 1-minute candles
   each).` The first draft typed "about 1.5 hours" into that sentence and was
   cut by the harddev loop — the measured rate says 4.4, and a duration nobody
   measured is the same defect again.

**ROOT CAUSE** — a literal label over a queue whose size the route already
knew.

**WHY IT WAS NOT CAUGHT** — every test on this screen asserts that the
button EXISTS and which job MODE it sends
(`test_the_button_exists_and_says_what_it_will_do`); none compares the words
in the confirm with the queue the job builds. An empty-of-rows screen can only
be guarded against its WORDS (RCA-2026-09-12-G), and nobody had written that
guard for this box.

**COST** — none in money. About four hours of the store's disk, which the
operator wanted anyway (the v2 store needs the whole market) but had not been
told.

**FIX** — this commit.

**GUARD** — `tests/test_the_update_confirm_names_the_whole_queue.py`
(3 tests).

---

## RCA-2026-09-17-C — the sweep orchestrator's shutdown could crash on Windows

**CEO**

* When the sweep coordinator finished and cleaned up its helper processes,
  Windows sometimes answered "the parameter is incorrect" for a helper that
  had already gone, and the clean-up itself crashed instead of finishing.
* Why: the code expected the two errors a Unix machine gives for a vanished
  process and Windows gives a third.
* What stops it now: every "could not signal it" answer is treated as "it is
  already gone", which is what it means at shutdown.

**DEV**

* `sweep_orchestrator._stop_children:285` — `os.kill(pid, SIGTERM)` under
  `suppress(ProcessLookupError, PermissionError)`; on Windows `os.kill` is
  `TerminateProcess` and a dead/unopenable pid raises `OSError(87)`.
* Invariant: **a best-effort shutdown never raises on a pid it cannot reach.**
  The second kill site in the same function (`pid_alive` → `kill_hard`, line
  297) carried the same two-error list and a child can exit between the probe
  and the kill; it takes `OSError` too (found by the harddev loop while the
  RCA was being written).
* Guard: `tests/test_sweep_orchestrator.py::test_progress_is_published_every_tick`
  — permanently red on this PC until this fix, which is how it was found.

**SAW** — `OSError: [WinError 87] The parameter is incorrect` from
`tests/test_sweep_orchestrator.py` on `Sep 17, 2026`, one of four reds
sitting in the suite (with `test_days_window`, `test_live_results` and
`test_compact_rebuilds_into_a_fresh_file`).

**TIMELINE**

1. `Sep 17, 2026`, afternoon — the whole replay/window/deploy set is run to
   baseline the v2 work: 378 pass, 4 files red, this one with WinError 87.
2. The test drives `run()` to completion; `_stop_children` lists 1 child pid
   that has already exited.
3. `os.kill(pid, SIGTERM)` on Windows is `TerminateProcess`; it raises
   `OSError(87)`, which is neither of the 2 suppressed types, and the test
   dies in the shutdown instead of asserting on the progress file.
4. Same evening — both kill sites suppress `OSError`; the file is green
   (6 passed).

**ROOT CAUSE** — a Unix error list on a Windows call.

**WHY IT WAS NOT CAUGHT** — the test WAS red, in a suite with three other
long-standing reds: a suite that is always red is one nobody reads, and each
red had been assumed to be "the other session's". Baselining the suite before
new work is what surfaced all four.

**COST** — none in money.

**FIX** — this commit (`56ed9d67a59b`; the second kill site in the commit
that carries this text).

**GUARD** — `tests/test_sweep_orchestrator.py::test_progress_is_published_every_tick`.

---

## RCA-2026-09-17-D — every trade log's source line printed the banned date stamp

**CEO**

* Under a row's trade-by-trade log the line *"667 bars, 2026-08-20 16:00 to
  2026-09-17 10:00"* used the date form you banned on Aug 21 (three asks).
* Why: that one line sliced the raw timestamp instead of going through the
  project's single date formatter, and the guard test only looks for two
  spellings of the mistake.
* What stops it now: it prints "Aug 20, 2026 4:00pm to Sep 17, 2026 10:00am"
  through the one formatter, and a test holds it.

**DEV**

* `market_sweep.trades_for` returned `"first": str(df["Date"].iloc[0])[:16]`;
  `test_no_module_formats_a_timestamp_by_hand` greps `strftime`/`toLocale`,
  and a sliced `str(Timestamp)` is neither (the shape of RCA-2026-09-09-C).
* Invariant: **every date the project prints goes through
  `positions_view.fmt_when`** (CLAUDE.md, "Date format").
* Guard: `tests/test_v2_reads_from_its_own_store.py::test_the_v2_trade_log_replays_from_the_minutes`
  asserts `first == fmt_when(...)`.

**SAW** — the Backtest v2 trade log's source line under `#U9YP5N7L` (XPIN
1h), `Sep 17, 2026 8:50pm`, in the Playwright check of the new
`/api/v2/strategies/trades` route: *"667 bars, 2026-08-20 16:00 to
2026-09-17 10:00"*.

**TIMELINE**

1. `Aug 21, 2026` — the date rule was written after three asks; the trade
   log's source line already printed `str(ts)[:16]` and no guard reads that
   spelling.
2. `Sep 17, 2026 8:50pm` — the v2 trade log is opened in the browser for the
   first time (585 exit stamps, 42 of them off the hour) and the source line
   under it reads `2026-08-20 16:00`.
3. Same evening — `first`/`last` go through `fmt_stamp`, and the new v2 test
   compares them with `fmt_when` instead of the old sliced string; two
   older trade-log tests that compared the sliced form are moved to
   `fmt_when` as well.

**ROOT CAUSE** — a third spelling of one mistake: a Timestamp's `str()`
sliced to 16 characters is the banned stamp, and the guard greps for
`strftime` and `toLocale` only.

**WHY IT WAS NOT CAUGHT** — the guard is only as wide as its pattern
(RCA-2026-09-09-C, again): `test_no_module_formats_a_timestamp_by_hand`
looks for two spellings of the mistake, and a sliced `str(Timestamp)` is a
third. Widening that grep to `str(...)[:16]` / `[:19]` slices is the
follow-up; this entry's guard asserts on the VALUE instead.

**COST** — none.

**FIX** — this commit (`56ed9d67a59b`).

**GUARD** — `tests/test_v2_reads_from_its_own_store.py::test_the_v2_trade_log_replays_from_the_minutes`.

---

## RCA-2026-09-17-A — the Candles v2 download stored 2.4 days of 1-minute candles for two coins while MEXC serves 30

**CEO**

* The very first Candles v2 download (five coins) came back "downloaded 5
  pair(s), 0 errors" — and two of the five, ARKM and GLM, held **3,505**
  one-minute candles (2.4 days) where the other three held about 40,000 (28
  days). Nothing on the screen said so; the run looked clean.
* Why: the app keeps a copy of every candle it has ever fetched and, when
  asked again, only fetches what is NEWER than that copy. ARKM's copy had been
  started by a small look-up earlier that day, so every later fetch just added
  the newest minutes to a history that was never going to grow at the front.
* What stops it now: when a download comes back with fewer candles than the
  timeframe should have, it asks the venue for OLDER ones, page by page, until
  it has the full history or the venue has no more. Re-run after the fix, ARKM
  and GLM hold the same ~40,000 minutes as the others.

**DEV**

* `mexc_futures.klines:1160-1190` — a disk-cached frame is treated as
  complete: `fetch_from = last_s - 2 * per` pages the TAIL only; the front is
  never revisited. `market_sweep.refresh_candles:359-377` inherits that, and
  the v2 download (`db_jobs._run_download` → `refresh_candles(symbol, "1m")`)
  stored whatever came back. Found in the press-and-watch WATCH step by
  listing the files: 163 KB against 2.1 MB.
* Invariant broken: **a cache is complete only if it holds what was ASKED**
  — the same shape as the 8,000-bar 15m sweep in CLAUDE.md rule 13 ("never
  cap a fetch below what the venue serves"), this time from a cache rather
  than a limit.
* Guard: `tests/test_a_short_kline_cache_is_backfilled.py` — `klines_backfill`
  pages backwards until the venue answers an empty page and stops at `want`;
  `refresh_candles` asks for it whenever `len(df) < cap` and not when the
  frame is full.

**SAW** — `Sep 17, 2026 7:39pm`, `~/.tradingagents/v2/candles`: `ARKM_USDT-1m.json`
163,751 bytes and `GLM_USDT-1m.json` 177,348 bytes beside three files of ~2.1
MB; the progress file read `"errors": 0, "note": "downloaded 5 pair(s)"`.

**TIMELINE**

1. `Sep 17, 2026` afternoon — measuring how much accuracy 1-minute candles
   would buy, `fx.klines("ARKM_USDT", "Min1", 44000)` was called while the
   disk cache for that pair held a small frame from an earlier page fetch;
   the call extended its tail and saved **3,356** bars.
2. Same day, asked directly (`_klines_page(..., end=now-25d)`), MEXC answered
   **2,000** bars for ARKM 25 days back — the venue had the history the cache
   did not.
3. `7:39pm` — the Candles v2 download ran `refresh_candles("ARKM_USDT",
   "1m")`: `cached_candles` (the v2 sweep cache) was empty, so it called
   `fx.klines(..., 44000)`, which served the 3,356-bar disk cache plus the
   newest tail: **3,505** bars, stored as the pair's whole history.
4. After the fix: `klines_backfill` paged backwards from the cached oldest
   bar and the pair holds the venue's full 1-minute history.

**ROOT CAUSE** — a cache that grows only at the tail, read by a fetch that
takes its length as the venue's.

**WHY IT WAS NOT CAUGHT** — every candle test checks the TAIL (a delta fetch,
a forming bar, a corrupt file) or a COLD fetch (paging a full history); none
seeds a SHORT warm cache and asks whether the front is ever filled. The
download's own report counted pairs and errors, not bars against the cap.

**COST** — none in money; two pairs of one test download. A Backtest v2 row on
either coin would have been measured on 2.4 days and labelled by its `days`
field, so the label would have been true and the history a fraction of what
was available.

**FIX** — this commit (`klines_backfill`, `refresh_candles` fills a short
history from the front).

**GUARD** — `tests/test_a_short_kline_cache_is_backfilled.py` (4 tests).

---

## RCA-2026-09-17-B — the Candles v2 download could not write its own pending list

**CEO**

* The same first Candles v2 download ended with a line in its log: *"could
  not update the pending ledger: ValueError: unknown pending kind:
  'candles_v2'"*. Had a pair failed, RESOLVE PENDING on Candles v2 would have
  had nothing to resolve and the failure would have been invisible.
* Why: the list of "things that failed and need a retry" is kept in one file
  per kind, and the file names were a fixed list of two. The v2 download was
  given its own name so its failures never mix with v1's — and the list did
  not know the name.
* What stops it now: the name is registered, and a test asks for it.

**DEV**

* `pending_ledger.KINDS = ("candles", "backtest")` while `db_jobs._ledger_kind`
  returned `"candles_v2"` for the v2 job; `_run_download` caught the
  `ValueError` and printed it, so the run finished "clean" with its ledger
  unwritten.
* Invariant broken: **a job that cannot record its own failures reports a
  success it cannot vouch for** (CLAUDE.md, "a job that cannot start must SAY
  SO", in its ledger form).
* Guard: `test_the_v2_download_has_its_own_pending_ledger` in
  `tests/test_a_short_kline_cache_is_backfilled.py`.

**SAW** — `~/.tradingagents/db_download_v2.log`, last line, `Sep 17, 2026
7:39pm`: *"[download] could not update the pending ledger: ValueError:
unknown pending kind: 'candles_v2'"*.

**TIMELINE**

1. `Sep 17, 2026 7:39pm` — the first Candles v2 download finished 5 pairs
   (about 40,000 one-minute bars each, 0 errors) and refreshed the candle
   index in 0 s.
2. Its last step, writing the run's pending list, called the ledger with the
   kind `candles_v2`; the ledger knew 2 kinds (`candles`, `backtest`) and
   raised; the job logged the line and exited 0.
3. `7:49pm` — `candles_v2` registered as the third kind; the re-run of the
   same 5 pairs wrote its ledger and the log gained no new error line (the
   file holds 3 lines in total, the error being line 2).

**ROOT CAUSE** — a new kind added on the writer's side and not on the ledger's.

**WHY IT WAS NOT CAUGHT** — the ledger's tests drive `record`/`clear` with the
two known kinds; the v2 job tests asserted the kind's NAME in the job's
source, never that the ledger accepts it.

**COST** — none; no pair failed in the run that revealed it.

**FIX** — `41066585dcc6` (the kind registered); the guard below arrived with
the commit that carries this text, because the first version of this entry
pointed at a source grep — exactly the gap its own fourth field names.

**GUARD** — `tests/test_pending_ledger.py::test_every_download_kinds_ledger_is_a_ledger_the_ledger_knows`
drives `record`/`pending`/`clear` with the kind each download job really uses.

---

## RCA-2026-09-16-D — the demo W/L cell printed one strategy's record on every coin it was armed on, and the caption above it said 85 rows were switched off while 120 were running

**CEO**

* The demo win/loss column added up to **69 wins and 3 losses**. Your ledger
  held **30 wins and 6 losses**. And the line above the grid read *"0 trading
  REAL money · 0 paper only · 85 deployed but switched off"* while 120 rows
  were armed and trading demo.
* Why: a strategy can be armed on several coins, and the record was counted by
  STRATEGY instead of by the row you deployed. So one strategy armed on five
  coins added its five coins' wins together and printed that same total on all
  five rows — five rows of one trade each read as five rows of five.
* What stops it now: every row counts only its own coin's trades, and the rows
  on screen add up exactly to the ledger. Checked after the fix: the grid shows
  30W/3L, the three rows you no longer deploy hold the other 4W/3L, and
  together they are the ledger's 34W/6L to the trade.

**DEV**

* `auto_trader.strategy_stats:3155` grouped exit rows by `e["strategy"]` alone,
  and `api.trade_strategies:1643` read `stats.get(key)` — the bare strategy
  key. The same bare key was used for `_is_real`, `today`, and the
  `real_count`/`paper_count`/`idle_count` counters at `api.py:1799`, all of
  which stopped resolving once arming moved to `book_slot(key, coin)` on
  Sep 16, 2026 (RCA-2026-09-16-C).
* Invariant broken: `label-must-match-data`, in its SUM form — the itemised
  rows must add to the total shown — and `deploy-by-id`: a row id is coin +
  timeframe + signal + threshold + SL + TP + sizing, so anything keyed to a row
  is keyed to its coin.
* Guard: `tests/test_the_record_belongs_to_one_id.py` — 11 tests, verified RED
  on the pre-fix files (8 of 9 failed before the caption tests were added).

**SAW** — while choosing how the demo cell should be drawn: *"in demo win/l
what if i make it mini pie graph then indicate the win and lose count"*, then
*"use Badge on a soft disc"*. The drawing was the ask; the number underneath it
was wrong, and the caption above it was wrong too.

**TIMELINE**

1. `Sep 16, 2026` (RCA-2026-09-16-C) — arming moved from `strategy_books[key]`
   to `strategy_books["key|COIN"]`, so 85 per-strategy switches became **120
   per-id switches**. Everything keyed on the bare key silently stopped
   matching.
2. The grid's record did not move with it. `stoch14_30m_sl2tp05` is armed on
   five contracts, and all five printed **5W 0L +$0.80** — one strategy's
   total, five times.
3. The counters above the grid did the same thing in the other direction:
   `books.get(key)` was empty for every migrated strategy, so the caption read
   **"0 trading REAL money · 0 paper only · 85 deployed but switched off"** over
   120 armed rows.
4. Measured against the ledger at the time: the grid summed to **69W / 3L**;
   counting the same demo exits by `(strategy, coin)` gave **30W / 6L** over 36
   closed trades across 26 rows.
5. AFTER, measured on the running API: the five `stoch14_30m_sl2tp05` rows read
   **#ZSMP3CF4 DVNSTOCK 2W 0L +$0.32**, **#JXRSKJSW FASTSTOCK 1W 0L +$0.16**,
   **#9FTN66Y4 KKRSTOCK 1W 0L +$0.15**, **#2NYXSXTR ROLSTOCK 0W 0L $0.00**,
   **#XH2KSFXG VUG 1W 0L +$0.17**.
6. And the whole grid reconciles: **0** rows disagree with the ledger; grid
   30W/3L plus the 4W/3L on three `(strategy, coin)` pairs no longer deployed
   equals the ledger's **34W / 6L over 40 demo exits**. The caption now reads
   **"0 trading REAL money · 120 paper only"**.
7. The cell itself was redrawn as the operator picked it from twenty drawings:
   a donut on a soft disc, the win rate in the hole, `2W` / `1L` beside it.

**ROOT CAUSE** — the unit of deployment became the row id (strategy + coin),
and the record, the book flag, today's PnL and the four counters were all still
keyed by the strategy alone.

**WHY IT WAS NOT CAUGHT** — RCA-2026-09-16-C changed the KEY SHAPE and its
guard, `test_one_id_is_one_switch.py`, asserted on ids, books and switches. It
never asserted on a NUMBER. A key-shape change breaks every reader of that key
at once, and the ones that read it through `.get()` fail SILENTLY — `books.get(key)`
returning `[]` looks exactly like "not armed", and `stats.get(key)` returning the
strategy total looks exactly like a record. **When a key changes shape, grep for
every `.get(` on that key and list them before editing** — the same lesson
CLAUDE.md already carries as *"when changing a rule, grep for the CONCEPT"*,
here applied to a dictionary key rather than a guard.

The second half is the assertion to add, not the grep: **a grid that itemises
must be tested against the SUM of its source.** Every W/L test in this repo
checked one row's numbers against one fixture. Not one added the rows up and
compared them to the ledger they came from, which is the only check that could
see 69 where there were 36.

**COST** — no money and no wrong order. Nothing armed live (`real_count` 0, no
open real positions) and the runner's own loss caps read
`pnl_today_by_strategy` per STRATEGY, which is deliberately unchanged. The cost
was the operator's ability to tell which deployed id is actually working: a row
with one trade and a row with five were shown as identical, and that column is
what they pick deployments by.

**FIX** — this commit. `auto_trader.strategy_stats(dry, by_coin=True)` and
`pnl_today_by_strategy(now, dry, by_coin=True)` key by `book_slot(strategy,
symbol)`; both default to OFF so `tripped_strategies` keeps its per-strategy
loss cap. `api._slot_stats` / `_slot_today` read one contract's slot, and sum
across contracts only for a row with no coin (the catalog listing).
`trade_strategies` computes `_is_real` per contract inside the coin loop, and
the four counters count ROWS by their own `books`. The cell is
`webapp/src/components/trade/WinBadge.tsx`: a donut on a soft disc with the win
rate in the hole and the counts written out beside it — never colour alone,
because `#039855` against `#f04438` measures ΔE 8.3 for a deutan reader, which
clears the floor but only just.

**GUARD** — `tests/test_the_record_belongs_to_one_id.py`, 11 tests, verified
RED on the pre-fix files and green after; 225 tests across
`test_api_trade.py`, `test_both_books_on_a_deployed_row.py`,
`test_one_id_is_one_switch.py`, `test_auto_trader.py`, `test_deploy_preset.py`,
`test_runner_stakes_flat.py`, `test_a_real_position_is_never_unwatched.py` and
`test_feedcheck.py` pass beside it. Verified on the running app: the API
restarted onto the fix, the UI rebuilt and restarted, and the badge rendered
and read back from the DOM (`2 won, 1 lost, 67% win rate`) with no console
errors in either theme.

---

## RCA-2026-09-16-C — five of the operator's row ids collapsed into one switch, and four trades in five were labelled with a coin they were not trading

**CEO**

* You deployed 280 ids. On the trade screen five of them showed as ONE line,
  under a single id, DM84QDSZ, and one switch moved all five together.
  Four of those five were labelled with the wrong coin.
* Why: a strategy is named by its signal, timeframe and targets, and the COIN
  is not part of that name. So five of your ids, which differ only by coin,
  became one strategy holding five contracts — and the screen printed the id
  of whichever coin happened to be first.
* What stops it now: the screen shows one line per id, each with its own id,
  and each can be switched to live or demo on its own without moving the
  other four. A written rule now says an id is the coin plus the
  six other fields, always.

**DEV**

* `api.trade_strategies` built one row per STRATEGY KEY and hashed its id
  with `row_id_for(key, coins[key][0], settings)` — the first contract of
  however many the key held. `strategy_books` was keyed by strategy only, so
  one entry armed every contract at once.
* Invariant broken: `label-must-match-data`, and CLAUDE.md rule 22 (name the
  exact row back before writing) — an id that names the wrong contract cannot
  be pasted back into a report's find-by-ID box, which is the whole purpose
  of a stable id (kit item H).
* Guard: `tests/test_one_id_is_one_switch.py` — 10 tests, driving
  `api.trade_strategies` with the operator's own shape (one strategy, several
  contracts).

**SAW** — *"WHY IS #DM84QDSZ IN LIVE TRADE HAVE DIFFERENT COINS?"*, then
*"FIX IT I DEPLOY SAID DEPLOY AND ID BUT IT HAS DIFFERNT COINS THEN DEPLOY
THE ID, DONT GROUP THEM AS ONE, CREAET A SKILL FIRST"*.

**TIMELINE**

1. `Sep 16, 2026` — 280 ids deployed. They became **83 strategy keys**,
   because a key is `signal_timeframe_slXtpY`.
2. `willr14_30m_sl2tp05` ended up armed on five contracts at once. Their own
   ids, measured from the store:

   | coin | its real id |
   |---|---|
   | DVNSTOCK | **#DM84QDSZ** |
   | FASTSTOCK | #7BSMBRFA |
   | KKRSTOCK | #DGCSMB9N |
   | ROLSTOCK | #MU2AU5P6 |
   | VUG | #GXTHE8EJ |

3. `#DM84QDSZ` is DVNSTOCK 30m willr14, SL 2.00% / TP 0.50%, flat — **168
   trades, 97.62%, +$36.72**. The grid printed it on all five, so four labels
   in five named a contract that row was not trading.
4. The TRADE HISTORY was already right — it passes each trade's own symbol to
   `row_id_for` — which is why the fault only showed on the strategies grid,
   and why it read as "the same id on different coins".
5. AFTER: the grid returns **120 rows for 85 strategies** — one per deployed
   id — `willr14_30m_sl2tp05` shows as five separate lines with the five ids
   above, and **0** rows carry an id that is not their own coin's.
6. Arming proved on the live settings: with `willr14_30m_sl2tp05|VUG_USDT`
   set to live, `books_for` answers `[False, True]` for VUG and `[True]` for
   the other four.

**ROOT CAUSE** — the deployment unit was the strategy key, which does not
carry the coin, while the operator's unit is the row id, which does.

**WHY IT WAS NOT CAUGHT** — every existing test of that grid asserts on a
strategy with ONE coin, so the id and the coin agreed by accident. The repo
had the right rule written down in two places already (the `row_code` hash
takes seven fields; kit item H says the id is hashed from the combination)
and no test ever put a second contract on one key. **A guard built on the
simplest fixture cannot see a bug that needs two of something** — and the
operator's own deploy was the first time five appeared.

The `blast-radius` half is worth keeping too: making the switch per contract
changed the SHAPE of `strategy_books`, and six readers did `books.get(key)`.
The harddev loop found `active_modes` first — it answered `[True]` with one
id armed live, so the live book would never have run and that row would have
sat armed on screen taking no trade. `book_names` / `book_names_any` now
carry the both-shapes rule in one place.

**COST** — no money and no wrong order: the ids were labels, and the trades
themselves were placed by the strategy on the right contract. The cost was
the operator's ability to tell which row made the money, and a switch that
moved five deployments when they meant one.

**FIX** — this commit. `auto_trader.book_slot(key, coin)` (`strategy|COIN`),
`books_for(key, settings, coin)` consulting the contract entry before the
bare key, and `book_names` / `book_names_any` for the readers. Every caller
that knows the contract passes it — `_process_slot`'s entry filter, the live
and paper armed lists, the scan line's watched timeframes,
`timeframe_locks`, `deploy_preset._claims`, `db_jobs`'s deployed-coin list —
and `active_modes` unions across contracts. `api.trade_strategies` emits one
row per contract with its own id, its own books and only its own open
positions; a key with no contracts still emits exactly one row, so the
catalog listing is unchanged. The operator's live config was migrated: 85
per-strategy switches became **120 per-id switches**.

**GUARD** — `tests/test_one_id_is_one_switch.py`, 10 tests, verified RED on
the pre-fix files (9 of 10 fail) and green after. 136 tests across
`test_auto_trader.py`, `test_deploy_preset.py`, `test_runner_stakes_flat.py`
and `test_a_real_position_is_never_unwatched.py` pass beside it.
`.claude/skills/deploy-by-id/SKILL.md` is the written rule, registered in
`SKILLS.md`.

---

## RCA-2026-09-16-B — switching to demo-only stopped the runner watching the live book, so three closed trades never reached the screen

**CEO**

* You turned every strategy to demo. An hour later MEXC closed one of your
  real trades at a profit and your screen went on showing it open — the money
  was in your wallet and nowhere in your history.
* Why: the runner decides which books to look at from what your strategies are
  set to. With everything on demo it stopped looking at the real book at all,
  including the trades that were still open in it.
* What stops it now: as long as the book holds ONE real position, the runner
  looks at the real side every cycle whatever the settings say — for exits
  only, it can never open a new real trade while you are on demo. Your CTC
  trade is now in your live history at **+$1.44**, and two DVNSTOCK trades
  that were stale for the same reason came back at **+$0.64** each.

**DEV**

* `auto_trader.run_cycle` walks `active_modes(settings)`, which answers
  *which books do the ARMED strategies want*. All-demo returns `[True]`, so
  `process_symbol` was never called with `dry=False` and the slot-level
  rescue written for exactly this — *"no strategy armed in this book but a
  position is open — tracking its EXIT only"*, `_process_slot` — could not
  run. `live_gone` (`fx.open_positions`) is inside that same call.
* Invariant broken: rule 14 (the exchange is the source of truth) and rule 17
  (a position is never open without management for longer than one cycle).
  The 2026-08-17 XAUT incident is the SAME bug and its fix was placed one
  layer too low — inside the function the caller had already decided not to
  call.
* Guard: `tests/test_a_real_position_is_never_unwatched.py` — 7 tests, and
  `_has_real_position` reads the POSITION's own `dry`, never the settings.

**SAW** — *"FOR DEMO CTTKPGQE I'VE ALREADY TP IT WHY IS IT NOT IN LIVE TRADE
HISTORY? IT SHOULD BE REALTIME"*, then *"BUT ITS STILL NOT CORRECT"*, then
*"I MEAN IN THE UI WHEN IT CLOSE IN MEXC I DOES NOT REFLECT IN UI"*.

**TIMELINE**

1. `Sep 16, 2026 1:43am` — LIVE CTC short opens, entry **0.10166**, target
   0.10014, MEXC position **1498235091**. A demo twin opens 16 seconds later
   at 0.10168 with target 0.100155 — and the SAME `trade_id` CTTKPGQE, which
   is what made the operator read them as one trade.
2. `2:08am` — all 85 strategies set to `["paper"]` on their instruction.
3. `2:14am` — the last `scan CTC_USDT[real]` line in `auto_trade.log`. From
   here the live book is never visited again.
4. `2:37am` — MEXC's own bracket closes the position: exit **0.10003**,
   realised **+1.4398**.
5. `2:38am` — the DEMO twin books its own TP, **+1.07**, and appears in demo
   history. That is the row the operator could see, and it is why the two
   numbers differ: the demo target was the easier one.
6. `3:13am` — measured against the venue with the operator's own keys: MEXC
   reports **4** open positions and CTC is not among them, while the book
   still lists `CTC_USDT#live#killzone_4h_sl3tp15` as open and the ledger
   holds **0** live exit rows for CTTKPGQE. 35 minutes unrecorded.
7. `3:19am` — AFTER the fix, the first cycle reconciled it and two more:
   CTC **TP 0.10003 +1.44** (matching MEXC's realised 1.4398), DVNSTOCK
   willr14 **+0.64**, DVNSTOCK stoch14 **+0.64**. All three now in
   `/api/trade/history?dry=false`.

**ROOT CAUSE** — the cycle chose its books from what the SETTINGS arm, not
from what the BOOK holds, so a demo-only settings file hid every open real
position from the code that books its exit.

**WHY IT WAS NOT CAUGHT** — there IS a test for this, and a comment in the
code describing this exact incident from 2026-08-17 ("Moving XAUT to
demo-only left an open real short unmanaged … a phantom position for over a
day"). Both sit at the SLOT level, and the slot level was never reached.
**When a fix is written inside a function, ask what decides whether that
function is called at all** — every assertion about `_process_slot`'s rescue
passed throughout, because the rescue is correct. The caller was not.

That is the same shape as the 2026-09-04 nine-hour freeze, whose rule this
file already carries: *the tests drove `process_symbol`; the runner enters
through `run_cycle`*. The new guard asserts on `run_cycle`'s own source for
that reason.

**COST** — no money lost, and nothing was at risk: MEXC closed the trade
correctly and better than the demo (+1.4398 against the demo's +1.07). The
cost was the record and the trust in it — three closed trades worth **+$2.72**
absent from the operator's history, a position shown open that was not, and a
coin the book believed busy would have refused new entries on.

**FIX** — this commit. `run_cycle` adds the live book to `modes` whenever
`_has_real_position(state)` — the position's own `dry` flag, fixed at entry,
never the settings — and `symbols` now also includes every contract holding a
real position, so deleting a strategy cannot hide the position it left
behind. Entries are untouched: `_process_slot` still filters them by book and
adds the rescued strategy to `tripped`, so the live pass is exits only (the
2026-08-18 XAUT re-entry is what that protects).

**GUARD** — `tests/test_a_real_position_is_never_unwatched.py`, 7 tests,
verified RED on the pre-fix file (5 of 7 fail) and green after; 109 tests in
`test_auto_trader.py` pass beside it. Proven in the field: the first cycle
after the restart booked all three stale exits.

**STILL OPEN** — the live and demo books share one `trade_id`
(`trade_code(symbol, key, entry_bar, side, dry)` produced CTTKPGQE for both),
so one id names two trades with different entries and different outcomes.
That is what made this look like a display fault rather than a missing exit,
and it is not fixed here.

---

## RCA-2026-09-16-A — MEXC says "too frequent" in a 200, so five coins were told they had no candles at all

**CEO**

* Minutes after your 127 strategies went live, five of your coins did nothing
  and the log said they had no price history: CTSHSTOCK, DXCMSTOCK, SYFSTOCK,
  CHYMSTOCK and TRGPSTOCK. They all had history — between 492 and 3,302 bars
  each, sitting on your drive.
* Why: MEXC refused those requests because we asked for too many at once, and
  it says so in a way that looks like a normal successful reply. Our code only
  noticed refusals that arrive as an obvious error, so it read "we refused
  you" as "there is no data", and the strategies stood down.
* What stops it now: a "too frequent" refusal is recognised and simply asked
  again a moment later, the same way a dropped connection already was. If it
  still will not answer, it says so as a refusal instead of pretending the
  coin has no history.

**DEV**

* `mexc_futures._get_public` retried on the HTTP STATUS only
  (`_RETRY_STATUSES` = 429, 500, 502, 503, 504). MEXC throttles a keyless call
  with **HTTP 200** and `{"success": false, "code": 510, "message":
  "Requests are too frequent"}`, so the wire looked perfect, the body was
  handed back, and every caller's `payload.get("data") or {}` turned the
  refusal into an empty answer — `klines()` then returned an empty frame and
  `auto_trader` logged `no Min60 candles for TRGPSTOCK_USDT`.
* Invariant broken: **read the emitter, not the label** (rule 23) and rule 16,
  which already names 510 — but only for `_request`, the SIGNED path, which
  reads `payload.get("code")`. The keyless path never looked at the body at
  all. A refusal that is indistinguishable from an empty answer is the
  `label-must-match-data` failure one layer below the screen.
* Guard: `tests/test_a_throttle_is_not_an_empty_answer.py` — 8 tests driving
  `_get_public` against a real 200-with-510 body.

**SAW** — not reported by the operator; found while watching the runner after
arming their 127 strategies. `auto_trade.log`:

    Sep 16, 2026 1:45am WARNING auto-trader cycle failed for TRGPSTOCK_USDT:
                        no Min60 candles for TRGPSTOCK_USDT
    Sep 16, 2026 1:45am WARNING ... (code=510 msg='Requests are too
                        frequent, please try again later')

**TIMELINE**

1. `Sep 16, 2026 1:40am` — 127 strategies armed across **26 coins**, up from
   the 9 the runner had been scanning. The runner is restarted to load the new
   specs, so `_BAR_CACHE` is empty and the first cycle asks the venue for
   every coin and timeframe at once.
2. `1:45am` — five pairs come back throttled. The runner reports them as
   having no candles and their strategies take no action.
3. Checked against the store the same minute — every one of them was present:
   `CTSHSTOCK_USDT-30m` **1,954 bars**, `DXCMSTOCK_USDT-30m` **1,708**,
   `SYFSTOCK_USDT-30m` **3,302**, `CHYMSTOCK_USDT-1h` **658**,
   `TRGPSTOCK_USDT-1h` **492**. The UPDATE CANDLES run that finished at
   `6:27:52pm` the previous evening had gap-filled 5,278 pairs with 0 errors.
4. `grep code=510` over the same window: the refusal was in the log, beside
   the warning that blamed the candles.
5. AFTER the fix, driven against a real 200-carrying-510 body: the call is
   retried on the same budget as a cut connection and the second answer is
   served; a throttle that never clears raises `MexcFuturesThrottled` instead
   of returning; a genuine rejection (code 1001, "contract not exist") is
   still answered in **one** call and never retried.

**ROOT CAUSE** — the keyless HTTP helper decided retryability from the status
line, and this venue puts its rate limit in the body with a 200.

**WHY IT WAS NOT CAUGHT** — `tests/test_public_get_retry.py` exists and passes.
It was written for the 2026-08-25 `IncompleteRead`, so every case in it is a
BROKEN WIRE: a cut connection, a timeout, a 5xx, a 429. The success path is
asserted only as "returns the parsed body". **A test suite shaped around one
failure mode proves nothing about a failure that arrives looking like
success** — and this one had to, because MEXC's own signed path already reads
`payload.get("code")` for exactly this reason, twenty lines away in the same
file. The knowledge was in the module and not in the function.

It also needed 26 coins to show itself. At 9 coins the burst stayed under the
limit, so the bug was reachable for weeks and never reached.

**COST** — no money and no wrong trade: the five strategies did nothing, which
is the safe direction. The cost was five of the operator's coins silently not
trading in the first cycles after their deploy, under a message that blamed
their own candle store — and they would have gone looking there.

**FIX** — this commit. `_RETRY_BODY_CODES = {510, 1002, 1004}` and a new
`MexcFuturesThrottled(MexcFuturesError)`; `_get_public` parses the body on the
success path through `_body()` and, when the code is a throttle, retries it on
the existing `_PUBLIC_RETRIES` / `_PUBLIC_RETRY_BUDGET_S` budget, raising if it
never clears. A business code still raises immediately and is never retried.
`MexcFuturesThrottled` subclasses `MexcFuturesError`, so every `except
MexcFuturesError` already written keeps catching it.

**GUARD** — `tests/test_a_throttle_is_not_an_empty_answer.py`, 8 tests,
verified RED on the pre-fix file (6 of 8 fail) and green after;
`tests/test_public_get_retry.py` still passes beside it.

---

## RCA-2026-09-15-E — "try again shortly" was hours: the id-index build was queued behind a collect and nothing said so

**CEO**

* You searched a row by its id and the screen kept loading. It was not stuck
  and nothing was lost — the search needs a lookup table the database does not
  have yet, and building it has to wait for the cloud results currently being
  written in.
* Why: the message said the table was "being built, try again shortly". A
  build had indeed been started, but it could not do any work, because only
  one thing can write to the store at a time and an import had it. Nobody
  checked that before promising "shortly".
* What stops it now: the refusal names what it is waiting for and how long
  that really means — *"queued behind collect, which is writing the store"* —
  so a wait you can plan around looks different from something broken.

**DEV**

* `rows_index.py:3385` raised `SortNotReady("... it is being built in the
  background — try again shortly")` after `_build_index("rows_id")`, without
  consulting `lock_holder()` or `busy_job()`. `build_running()` reports a name
  from a LOCK FILE's mtime, so a build blocked on the write lock and a build
  doing work are indistinguishable, and the message was written from the
  wrong one. Same sentence at `:3705` for the group index.
* Invariant broken: **a blocked resource NAMES ITS HOLDER** — already
  MANDATORY in CLAUDE.md, bought by RCA-2026-09-10-C, which is the reason
  `lock_holder()` exists. This path was written after that rule and never
  called it.
* Guard: `tests/test_a_blocked_build_says_who_is_holding_it.py` (7 tests),
  including one that fails if the old sentence returns to either refusal.

**SAW** — *"when i search 46SGBAHD in filter its taking too long is tihs
expected"*, then *"its still loading i clicked filter then id; 46SGBAHD then
click apply filter"*.

**TIMELINE**

1. `9:11pm` — the API refuses the search, starts a build child, and writes
   `.build-rows_id.pid`.
2. `9:23pm` — twelve minutes later, that child (**pid 2124**) has used
   **1 second of CPU**. It is alive and doing nothing.
3. The reason, from the store's own status: `paused_by: "collect"`. A cloud
   collect is **4 of 20 shards** in, **17,329,312 rows** written so far.
   SQLite takes one writer, so `CREATE INDEX` queues behind it.
4. The index really is missing — `has_index("rows_id")` is **False** — and
   without it this search is a covering scan of **113,439,286** rows,
   measured at **49.8 s** for this id (it is `FASTSTOCK 1h`).
5. AFTER: the same request answers
   *"finding row #46SGBAHD needs the rows_id index, and that build is QUEUED
   behind collect, which is writing the store — SQLite takes one writer, so
   nothing is being built until it finishes. Nothing is lost; this answers as
   soon as that job is done."*

**ROOT CAUSE** — the refusal described the CHILD ("a build exists") and the
reader needed the WAIT ("and it cannot start"). Those are different facts and
only one of them was checked.

**WHY IT WAS NOT CAUGHT** — the tests over this path assert that a 503 is
raised and that a build is started, which was all true here. Nothing asserted
on the SENTENCE, and the sentence was the whole product: a wait with a named
cause is information, the same wait called "shortly" is a broken screen.
**When a refusal is the deliverable, the assertion goes against its words** —
the same lesson as RCA-2026-09-12-G, where 289 row-shaped tests could not see
an empty state's text. It is now the second time a screen said "it catches up
in the background" while nothing was catching up (RCA-2026-09-14-B was the
first), so this is a pattern, not an incident.

**COST** — none in money. Roughly 15 minutes of the operator's time and a
second report of the same shape of lie.

**FIX** — this commit. `rows_index.index_wait_reason(name, what)` reads
`lock_holder()` then `busy_job()`, distinguishes queued / building now / just
started, and is total (a failed status read still returns a sentence rather
than turning a 503 into a 500). Both refusal sites call it.

**STILL OPEN, named not hidden:** `rows_id` is an on-demand index by design —
a bulk fill drops everything except `rows_pair` — so find-by-ID will need it
rebuilt after every large sweep. Whether it should be a KEEP index is a real
trade (a text index over 113M rows cost 48 minutes for `rows_pair`) and is
the operator's call, not one to make quietly.

**GUARD** — `tests/test_a_blocked_build_says_who_is_holding_it.py`.

---

## RCA-2026-09-15-D — UPDATE CANDLES sat on "starting" for four minutes, because the fix for that was applied to one caller and not its sibling

**CEO**

* You press UPDATE CANDLES and the screen says "starting" for about four
  minutes before anything moves. Nothing is wrong — it is reading all 5,235
  candle files, 1.77 GB, just to learn the names and dates it already has
  written down elsewhere.
* Why: this is the same fault fixed on Sep 12 for the UPDATE BACKTEST button.
  That fix was applied to the one place that had the problem, and the
  identical line behind UPDATE CANDLES was never looked for.
* What stops it now: it reads the small index instead, which skips any file
  that has not changed. The Storage screen had the same slow read inside the
  page request, so that is now done in the background too, and it says
  "reading the candle files…" instead of showing a false "0 bars · 0 pairs"
  while it works.

**DEV**

* `db_jobs.update_pairs` (`db_jobs.py:759`) called `msw.candle_coverage()`,
  which opens and JSON-parses every file in `CANDLES` to build display
  strings, and kept three fields from each: `symbol`, `timeframe`, `last_ms`.
  py-spy on the live worker (pid 1448):
  `read_text -> candle_coverage -> update_pairs -> _run_download`.
  `api.storage_coverage` called the same function INSIDE the request handler.
* Invariant broken: **when a rule changes, grep the CONCEPT, not the caller**
  (CLAUDE.md, 2026-09-05) — and, for the route, *a request never waits for the
  disk*, the rule `/api/cloud/status` (216 s) and `/api/strategies` (267 s)
  were both fixed under.
* Guard: `tests/test_update_says_what_it_is_doing.py` — three new tests, one
  of which walks the AST of every module and allows `candle_coverage` exactly
  one caller, by line number.

**SAW** — found by the press-and-watch loop, not reported: UPDATE CANDLES was
pressed at `Sep 15, 2026 5:55pm` and `/api/jobs/download` answered
`{"running":true,"done":0,"total":0,"now":"starting"}` on every poll for the
next four minutes.

**TIMELINE**

1. `5:55:28pm` — pressed; pid 7304 (the previous download was 20780, so this
   really started a new job).
2. `5:55:28pm` to `5:58:28pm` — ten polls, twenty seconds apart, every one
   `done 0, total 0, now "starting"`. `db_download.log` untouched since
   `Sep 09`.
3. py-spy on the worker put it in `pathlib.read_text` under
   `candle_coverage`, called from `update_pairs`. Not stalled — reading
   **5,235 files, 1.77 GB** off a mechanical G:.
4. `6:01:31pm` — the walk finished and the job moved: **244 of 5,278** pairs,
   8,110 bars, 0 errors, and from there a steady **~235 pairs/min**.
5. The same expensive call sits in `/api/storage/coverage`, which the Storage
   screen requests on mount — minutes of a held browser lane for a table of
   coin names and dates.

**ROOT CAUSE** — two callers wanted names and timestamps and asked a function
that reads every byte of the candle store to produce display strings.

**WHY IT WAS NOT CAUGHT** — because it WAS caught, three days earlier, in the
sibling. RCA-2026-09-14-F fixed exactly this in `stored_symbols` (579 s ->
0.4 s warm) and the guard written with it asserted on `stored_symbols` alone.
Two other callers in this repo already carried comments saying never to use
`candle_coverage` for this — `cloud_autopilot.missing_by_timeframe` and
`_pending_sources` — so the knowledge existed as PROSE beside four call sites
and as a test over one. **A guard that names the function it protects cannot
protect the function nobody has written yet.** The new test inverts it: it
walks the AST of every module in `tradingagents/` and allows `candle_coverage`
exactly ONE caller, so the next sibling fails at the point it is added rather
than the next time somebody presses a button and waits.

**COST** — no money and no lost data: the job was correct, and once past the
walk it ran clean at 235 pairs/min. The cost was four minutes of a button that
looks hung every time it is pressed, on a screen whose whole job is to say
what is happening — and an unknown number of Storage page loads that blocked
for minutes.

**FIX** — this commit. `update_pairs` reads `msw.candle_index()`
(incremental: a file whose mtime and size have not moved is taken from cache),
skipping any pair with no bars exactly as `candle_coverage` did, so an empty
candle file still falls into `missing` and is re-downloaded.
`/api/storage/coverage` answers from a `BackgroundValue` (`COVERAGE_TTL`,
600 s) and carries `reading`, and `StoragePanel` prints "reading the candle
files…" instead of `0 bars · 0 coin/timeframe pairs` while that first read is
in flight.

**GUARD** — `tests/test_update_says_what_it_is_doing.py`:
`test_no_job_walks_the_candle_store_to_learn_names_or_times` (AST, one allowed
caller), `test_the_storage_screen_never_waits_for_the_disk`,
`test_reading_and_empty_are_different_sentences`. All three verified RED on
the pre-fix files and green after.

---

## RCA-2026-09-15-C — the live gate charged two of the three costs, so a contract could eat its own target in funding and still read "ok"

**CEO**

* Before opening a trade the system checked what it costs to get in and out.
  It never checked what it costs to HOLD. On a contract whose funding is
  expensive, the venue can take the whole profit target back in settlements
  while every check on screen says the trade is affordable.
* Why: the backtests were fixed in August to charge all three costs. The live
  check was never given the third one.
* What stops it now: holding is charged like the other two, from the venue's
  own published rate, and a contract whose funding alone eats half the target
  in a day is refused outright. Three more checks went in beside it — what
  the account can afford, what the fill actually cost, and a real count of
  orders the venue shrinks.

**DEV**

* `auto_trader.py:1574` computed `round_trip = 2 * (slippage + taker_fee)`
  and nothing else; `edge_check` had no funding term at all, while
  `backtest_strategy` has charged `funding_history` per settlement since
  2026-08-19. Same decision, two answers.
* Invariant broken: **every cost the backtest charges, the gate charges.** A
  live guard that models fewer costs than the measurement it is guarding will
  approve trades the measurement would have rejected. Funding now enters
  through `funding_cost()` off `mexc_futures.funding_now()` — one call, the
  forward rate, cached 6h.
* Guard: `tests/test_what_it_checks_before_it_spends.py`, 28 tests.

**SAW** — no incident yet. The operator asked for the review: *"think that you
will use this for traiding high money, you will need a guard to check if fees
are too high etc"*. **NEVER HAPPENED YET** at their size; at 5 USDT a trade
the omission is invisible.

**TIMELINE** (what the gate would have done, on the operator's own contracts,
measured `Sep 15, 2026`)

1. `PSXSTOCK_USDT` — the long pays **0.0423% a day**, cycle 8h. On
   `willr14_15m_sl12tp12` (target 1.20%) the old gate charged 0 for holding.
2. `STBL_USDT` — the long pays **0.0300% a day**, cycle 4h, on `macddiv_4h`
   trades that hold hours by design.
3. `NGAS_USDT` — the long RECEIVES **0.1464% a day**, cycle 1h. The new rule
   charges that side nothing rather than crediting it: a receipt depends on
   the rate holding for the whole trade, the spread is paid the instant the
   order lands, and a guard may not net an uncertain gain against a certain
   loss.
4. The account, same morning: **153.61 USDT equity**. One position per coin
   was the only cap, so with 35 strategies armed nothing bounded total
   exposure but how many signals happened to fire, and no code read the
   wallet before sending an order.
5. AFTER: holding is inside `round_trip`; funding at or above
   **50% of the target per day** is a block on its own; an unreadable rate on
   a hold of an hour or more is a block, because MEXC's shortest cycle is
   **1 hour** (NGAS) and an uncounted cost on money is a refusal.

**ROOT CAUSE** — `edge_check` modelled entry and exit and omitted the holding
cost the backtests had been charging for four weeks.

**WHY IT WAS NOT CAUGHT** — every test of the gate asserts on the SPREAD: the
BDX incident was a spread, the PSXSTOCK 5003 losses were a spread, and the
suite grew around that shape. Funding has no test because it had no code, and
a missing term produces no failing assertion anywhere — it just makes the
number smaller. **A guard that models fewer costs than the measurement it
guards has a hole the size of the difference, and only a test that compares
the two lists can see it.**

**COST** — none realised. The exposure was that any funding-expensive
contract could pass the gate, and that grows directly with the stake.

**FIX** — this commit. `funding_now` (one call, 0.18 s, against 13.5 s and 46
pages for `funding_summary`), `funding_cost`, and the two funding blocks in
`edge_check`, which now also sizes the book read at the notional actually
traded rather than at a martingale rung that has not existed since Sep 11.
Beside it: `capital_check` (the wallet, an exposure ceiling, and margin
committed earlier in the same cycle), `slippage_paid` with a `fill_slippage`
ledger row and a loud line when the fill is worse than modelled, and a
`size_capped` row when the venue shrinks an order.

**ALSO IN THIS ROUND (the loop kept going):** a stop the VENUE would
liquidate through. At 20x the wall is `1/20 - 0.005 = 4.50%` and MEXC's own
`liquidatePrice` on the operator's live PDDSTOCK read **4.59%** from entry —
the arithmetic and the venue agree. Twenty registry strategies carry a **4%**
stop, leaving 0.5% of room for fees and funding to eat, after which the venue
takes the whole margin instead of the 4% the backtest measured. `edge_check`
refuses a stop past 80% of that distance, and `liquidation_warning` calls out
an already-open position whose stop has drifted behind the wall, using the
payload the exit check already fetched rather than a second venue call. The
widest ARMED stop is 3.00%, so nothing trading today is affected.

**GUARD** — `tests/test_what_it_checks_before_it_spends.py`. Two of its tests
found bugs in this work before it shipped: the unknown-funding block was DEAD
CODE at an 8-hour threshold (no strategy holds that long), and the capital
ceiling could be spent five times over by five signals on one bar close.

---

## RCA-2026-09-15-B — a download that stops at 2,000 rows asked SQLite for 3,268,883

**CEO**

* You set three filters, pressed download, and watched nothing happen for
  twenty minutes. Nothing was broken and nothing was lost — the file simply
  could not start, because the database was being asked to line up three and
  a quarter million rows before handing over the first one.
* Why: the download already knew it would stop after two thousand rows, but
  it never told the database that. So the database prepared everything
  instead of just the top two thousand.
* What stops it now: the limit is part of the question. Same filters, same
  data, same rows in the file — the first line now arrives in a tenth of a
  second instead of never. It was first measured on Sep 09 and answered with
  a warning tooltip rather than a fix; that is the part that should not have
  happened.

**DEV**

* `rows_index.py:3804` `win_left = DAYS_CSV_MAX if win_days else -1` caps a
  windowed export at 2,000 rows in a PYTHON countdown; the query built at
  `rows_index.py:3808` carried no `LIMIT`. With `min_winrate` filtering and
  `sort=profit` ordering, the plan is
  `SEARCH rows USING COVERING INDEX rows_wr4 (winrate>?)` +
  `USE TEMP B-TREE FOR ORDER BY` — an unbounded sort of every match.
* Invariant broken: **a cap that exists must travel to the query.** This is
  CLAUDE.md's *filter where the data is* in its LIMIT half: a predicate the
  server applies after the fact cannot save the work the database already
  did. `export_plan` also shrank its seek cap to `EXPORT_SEEK_MAX` on the
  premise that "an export has no LIMIT" — true for a plain download, false
  for a windowed one, so a bounded export was pushed onto a plan that needs
  `rows_pr2`.
* Guard: `tests/test_a_windowed_download_tells_sql_where_to_stop.py` — 6
  tests pinning that the SQL ceiling is computed from the same constant that
  stops the loop, that an unwindowed export still streams everything, and
  that the plan guards still refuse what they always refused.

**SAW** — *"i click download button but ive been waiting 20 mins now"*. Filter
icon, min win % 95, "TP is equal to or greater than SL", last 30 days, apply,
download. The browser showed 0 bytes throughout; nothing reached the Downloads
folder, not even a partial file.

**TIMELINE**

1. `Sep 15, 2026 3:47am` — first press. `screen.log` records `csv START` and
   no finish line.
2. `Sep 15, 2026 4:00am` — pressed again 13 minutes later. Also `csv START`
   only. Two exports then competed for the same interpreter lock.
3. The API process burned **1,389 CPU-seconds** and returned to idle
   (0.3 s per 6 s sample) with nothing delivered. A `StreamingResponse` logs
   `200 OK` when it BEGINS, so the access log said success for both.
4. Measured on the store as it stands — **113,439,286 rows, 5,402 pairs,
   48.01 GB, mechanical disk**:
   `winrate >= 95` matches **5,513,709** rows (counted in 32 s);
   `winrate >= 95 AND tp >= sl` matches **3,268,883** (1 s over the covering
   index).
5. The same query with no ordering: **0.3 s for 5 rows**. With
   `ORDER BY profit DESC` and no limit: **no first row after 500 s**.
6. `INDEXED BY rows_profit` (the fallback plan) — **5 rows in 7.7 s, 50 rows
   in 11.9 s, 500 rows never finished**, because `rows_profit` does not carry
   `winrate` so every candidate is a random row read. The plan that WOULD
   carry it, `rows_pr2`, does not exist on this database
   (`has_index("rows_pr2") -> False`).
7. The same query, same index, same plan, with `LIMIT 2000`: **2,000 rows in
   2.3 s**.
8. AFTER the fix, through the real export generator:
   **first byte 0.1 s**, then the re-measure proceeds at its own pace
   (1,094 lines in 181 s and still going, which is the candle work the
   tooltip already described).

**ROOT CAUSE** — `iter_rows` capped a windowed export in Python and asked
SQLite for an unbounded stream, so the sort had no bound. One clause.

**WHY IT WAS NOT CAUGHT** — it WAS caught, on `Sep 09, 2026`, on one of the
operator's own presses: the measurement is still in the code
(`671 s`, `1,184 rows`, "the file sat at 0 for the first four minutes — which
is indistinguishable from broken unless the button says so"). The response was
a hover tooltip, a `DAYS_CSV_MAX` cap and a note in the file. Every one of
those describes the symptom; none removes it, and a tooltip is invisible once
the button has been clicked. **Measuring a slow path and labelling it is not
fixing it — if the number is bad enough to warn about, it is the bug.** Six
days later the operator waited twenty minutes on the same press. No test
covered the export's query PLAN, only its output shape, so nothing went red
when the store grew from 52 million rows to 113 million and the unbounded sort
went from slow to impossible.

**COST** — no money, no data. Roughly 35 minutes of the operator's time across
two presses, six days of a filter combination being unusable, and the trust
cost of a button that looks broken.

**FIX** — this commit. `iter_rows` computes `_sql_limit` from `DAYS_CSV_MAX`
and appends it to the query; `export_plan` takes `limit` and keeps the
win-rate seek when the export is bounded. Output is unchanged: the loop
consumed exactly `DAYS_CSV_MAX` rows in `ORDER BY profit DESC, id ASC` before
and consumes exactly those rows now — a total order, so the same 2,000.

**STILL OPEN** — `rows_pr2` (the wide profit index, `WIDE_PROFIT` in
`rows_index`) is defined but absent from this database, so an UNWINDOWED
download with a win-rate floor still falls back to random row reads. Building
it is a long write against a 48.01 GB file and the indexer is currently
catching up on 5,335 stale pairs, so it is named here rather than started
quietly.

**GUARD** — `tests/test_a_windowed_download_tells_sql_where_to_stop.py`.

---

## RCA-2026-09-15-A — "it retries by itself" retried exactly once, so a filter that was ready sat unanswered until the page was reloaded

**CEO**

* You set a filter, the screen said it was busy and would keep trying on its
  own, and it never came back — you had to reload the page by hand. The
  answer had actually been ready for a while.
* Why: it did try again, once, fifteen seconds later. When that second try
  was refused too, the screen showed the same message as before — and because
  the message had not changed, the part of the page that schedules a retry
  never noticed anything had happened, so it never tried a third time.
* What stops it now: it keeps asking every fifteen seconds until the answer
  arrives, and stops the moment it does. Your filter now answers in 7.5
  seconds.

**DEV**

* `StrategiesPanel.tsx` retried a 503 with `setTimeout(..., 15000)` in an
  effect keyed `[waiting, load]`. The 503 handler sets `waiting` to
  `e.detail`, which for a repeat refusal is the SAME STRING — so the
  dependency was unchanged by value, the effect never re-ran, and the single
  timeout was the whole retry.
* Invariant broken: `label-must-match-data`, applied to a PROMISE rather than
  a number. The caption said "it retries by itself"; the component retried
  once. A one-shot retry is the hard version of this to spot, because it
  works exactly once and therefore looks implemented.
* Guard: `tests/test_a_refused_filter_retries_itself.py` — 6 tests; the first
  one pins the caption's wording, so if the promise is ever removed the file
  is revisited rather than quietly passing.

**SAW** — *"im using this filter is this expected to be so slow"*, then
*"its still loading till now"*, then *"so i need to refersh it to finish?
why"*.

**TIMELINE**

1. `Sep 15, 2026` — the operator filters Stored strategies on win % >= 100,
   TP >= SL, last 30 days.
2. The store refuses with 503: `rows_wr4` — the widest win-rate index — did
   not exist, because the full rebuild that finished that morning writes a
   file with the kept four indexes only and the on-demand ones are built when
   something asks for them.
3. The panel shows the store's own sentence, ending *"it retries by itself"*,
   and re-asks once at +15 s. Refused again; `waiting` set to the identical
   string; effect not re-armed. No further attempt is ever made.
4. `rows_wr4` finishes building in the background. Measured straight after:
   the same filter answers in **7.5 s**, twice in a row, returning **6 rows**
   of a capped **5,000**.
5. The screen kept saying "the store has not answered this filter yet" the
   whole time, with the previous answer underneath it.

**ROOT CAUSE** — a retry scheduled by `setTimeout` inside an effect whose
only trigger was a state value that a repeat failure sets to the same string.

**WHY IT WAS NOT CAUGHT** — the first diagnosis in this session was that
NOTHING retried, and a duplicate interval was very nearly committed on top of
the existing timeout. Reading `grep -n "waiting"` showed the retry effect and
it looked correct; what it did not show is that `setTimeout` fires once and
that the re-arm depends on a string CHANGING. **An effect that re-runs on a
value is only a loop if the value differs each time** — and the 503 detail is
deliberately stable, because it is a sentence for a human to read.

The wider reason: this repo's UI guards read the source for a call and assert
it is present. `setTimeout` and `setInterval` both read as "there is a retry".
Nothing drove the component through two consecutive refusals, which is the
only thing that separates them.

**COST** — no money, nothing measured wrongly: the rows were correct and the
answer existed. The cost was the operator being unable to use a filter they
had asked for specifically, and being told by their own screen that waiting
would fix it.

**FIX** — this commit. The effect uses `setInterval(..., 15000)` with
`clearInterval` on teardown, still keyed `[waiting, load]` and still guarded
by `inFlight` so a slow answer cannot stack (four stacked requests once held
every browser lane, RCA-2026-09-09-I). It re-asks with `load(true)` —
background — so a retry never throws the table back into its loading state
under the operator, and the success path's `setWaiting("")` tears the timer
down.

**GUARD** — `tests/test_a_refused_filter_retries_itself.py`. Verified RED on
the pre-fix file and green after; `tsc --noEmit` and `next build` clean, and
the web UI restarted so the running server is not serving old chunks.

---

## RCA-2026-09-14-B — the indexer died on a locked database, nothing restarted it, and the screen said it was catching up

**CEO**

* Your Stored strategies list stopped taking in new results on Sep 13 at
  4:05pm and nobody noticed for a day. The button offering to catch up 5,344
  coins was not a normal after-a-sweep message — it was the only thing left
  doing that job, because the program that does it automatically had died.
* Why: that program starts by claiming the results database. A collect was
  writing to it at that moment, so the claim failed — and instead of waiting
  a few seconds and trying again, it shut down. Nothing ever checked on it
  afterwards, so the machine simply had no indexer from then on.
* What stops it now, three things: it waits for a busy database instead of
  quitting; something checks every 30 seconds that it is alive and starts it
  again if not; and the screen now says which of the two situations you are
  in — "catching up on its own" or "nothing is filling this". I was wrong
  twice telling you it catches up by itself, and the screen now cannot say
  that unless it is true.

**DEV**

* `rows_index.main` called `ensure()` bare. `ensure()`'s first statement is
  `con.executescript("PRAGMA journal_mode=WAL;")`, which needs a brief
  exclusive lock, so `sqlite3.OperationalError: database is locked` raised
  out of `__main__` and ended the process. `spawn_indexer` is called once,
  from the API's `startup` event, and the supervisor thread beside it
  resumed `backtest`/`download`/`btupdate` and the runner — never the
  indexer.
* Invariants broken: **a daemon whose job is keeping a screen current may not
  exit because a neighbour held a lock**, and the label rule one layer up —
  every field in `status()` described the BACKLOG and none said whether a
  worker existed to clear it, so "catching up on its own" was printable while
  nothing was.
* Guard: `tests/test_the_indexer_is_never_allowed_to_stay_dead.py` — 17
  tests, four sections, including a real second process proving the run lock
  excludes one.

**SAW** — *"WHY DO I HAVE THIS BUTTON HERE / WHAT DOES THIS MEAN IM ONLY
ASKING"*, then, after two answers that said it would catch up by itself:
*"what do you mean newest numbers? so you mean its not updated?"* and
*"what's the reason why you decide it should not be updated"*.

**TIMELINE**

1. `Sep 13, 2026 4:05pm` — `rows_index.log` ends. Its last lines are
   `[rows-index] sync failed: OperationalError('database is locked')`
   repeated, then the traceback out of `main -> ensure -> executescript`.
   No indexer process on the machine after this.
2. Overnight two sweeps landed (runs 34677707977 and 34739539427) and their
   collects rewrote thousands of pair files. Nothing filed them.
3. `Sep 14, 2026 4:02pm` — `status()`: `rows 112,364,317`,
   `pairs_indexed 5,392`, `pairs_on_disk 5,401`, **`stale 5,344`**,
   `syncing False`. The button read "index the 5,344 pair(s) that moved".
4. Measured what that meant on two real pairs: `RCATSTOCK-15m` held
   **21,600** rows in its file against **18,900** indexed — 2,700 measured
   strategies unsearchable. `EMBER-15m` held **8,400** on disk and **0** in
   the index, written `Sep 14, 2026 12:06am`: the coin was missing from the
   screen entirely. Of 12 sampled stale pairs, 9 matched and 3 were short.
5. `3:13pm` — started an indexer by hand. It filed `CME-1d` at `3:13:36pm`
   and `EMBER-15m` at `3:21:49pm`: **one pair in 8 minutes**, and `stale`
   did not move for six minutes of watching.
6. `3:30pm` — py-spy on the process found the reason, and it was not the
   indexer: a **full rebuild** was running (`rows_index --rebuild --fresh`,
   pid 8624) at `loading 710 of 5,401 pairs, 70.89 pairs/min`. A rebuild
   loads a fresh copy of the whole store and swaps it in, so it owns the
   disk — and `busy_job()`, which walks `db_jobs.FILES`, has never heard of
   it. The indexer that is supposed to stand down for a big job was instead
   fighting one, on a mechanical disk, writing rows into a file about to be
   replaced. It is also the most likely author of the lock that killed it on
   the 13th.
7. AFTER the fix, on the live machine: the API's supervisor restarted the
   indexer by itself; `/api/strategies` reports `stale 5342`,
   **`indexer_running True`**, **`paused_by "rebuild (loading)"`**; and the
   panel reads *"index the 5,342 pair(s) that moved since they were
   indexed · catching up on its own · paused while rebuild (loading) has the
   disk"*.

**ROOT CAUSE** — `main()` let a transient `database is locked` terminate the
process, and nothing in the system was responsible for noticing an indexer
had stopped existing.

**WHY IT WAS NOT CAUGHT** — RCA-2026-09-10-C is the same organ: it fixed a
swallowed exception, an undercounted button and a DEVNULL'd log so that an
indexer that could not START would say so. Every one of those assumes there
IS an indexer. `tests/test_index_stall_is_visible.py` has 15 tests about a
stalled fill and not one about the process being absent — **"stalled" and
"gone" produce the same screen, and only one of them had ever been
imagined.**

Two narrower reasons it survived a day. The supervisor thread that resumes
crashed jobs was written for `db_jobs` kinds and the indexer is not one, so a
concept-level grep ("what else must never stay dead?") had never been run
over it. And the log could not distinguish the two states either: a
successful start printed NOTHING, so the newest line in `rows_index.log` was
the previous day's traceback whether the indexer was healthy or had been dead
for 24 hours. It prints `up (pid N): X indexed of Y, Z to re-file` now.

The loop also found a bug in the fix itself, which is the reason for the
loop: `_running_elsewhere()` tested only `pid_alive`, and a supervisor asking
every 30 s turns a recycled pid from a curiosity into a permanent no-op — the
NVIDIA Overlay shape of RCA-2026-09-12-B, one file along. The identity is a
run lock now, proved across a real second process.

**COST** — no money, nothing lost, every measurement safe on disk the whole
time: the pair files are the source of truth and they were complete. The cost
was a day of a search screen quietly answering with yesterday's data, two
wrong reassurances from me that it would fix itself, and the operator having
to ask three times.

**FIX** — this commit.
`rows_index._ensure_or_wait()` retries a busy database for as long as the
process lives (`ENSURE_RETRY_S`, 15 s), naming the holder via `lock_holder()`
and thinning the log after three attempts; `main()` calls it instead of
`ensure()`. `take_run_lock()`/`run_lock_held()`/`RUNLOCK` give the indexer a
real identity, and `_running_elsewhere()` requires the lock AND a live pid.
The API supervisor calls `spawn_indexer()` on its 30 s tick beside the runner
and the jobs. `busy_job()` now sees a live rebuild (pid alive AND a progress
file younger than `REBUILD_STALE_S`, so a dead one cannot pause the indexer
for ever) and names its phase. `status()` carries `indexer_running`, the
API's pending shape carries it as `None` — "not known yet" is not "dead" —
and `StrategiesPanel` prints one of three sentences beside the button.

**GUARD** — `tests/test_the_indexer_is_never_allowed_to_stay_dead.py`, 17
tests. Verified RED on the pre-fix files (13 of 13 then; 17 of 17 with the
rebuild section) and green after. `tests/test_rows_index.py::
test_only_one_indexer_process_at_a_time` was updated: it asserted that a live
pid IS an indexer, which is the rule that made the supervisor impossible.
`conftest` sandboxes `RUNLOCK`, caught by this repo's own
`test_the_sandbox_covers_every_path_constant_it_can_find` during the loop.

---

## RCA-2026-09-14-A — the LIVE toggle undid itself five seconds after it was clicked, and looked armed the whole time

**CEO**

* You clicked LIVE on a strategy and it switched itself back a few seconds
  later, before you could reach SAVE. Reaching the save button was a race
  against a hidden five-second timer.
* Why: that screen re-reads your saved settings every five seconds so your
  win/loss figures stay current. It was re-reading the toggles too, so it
  wrote the saved setting back over the click you had just made — and it also
  cleared the little "unsaved changes" note, so nothing told you the click
  had been thrown away.
* What stops it now: the refresh keeps updating the numbers that move, and
  never touches a switch you have changed but not saved. The note beside it
  now says in plain words that nothing is live until you press SAVE, and
  there is a DISCARD button if you change your mind. Nothing was ever armed
  by the click itself — no real order can be placed until the file is saved.

**DEV**

* `StrategiesGrid.tsx:42` — `load()` ran `setRows(st.rows)`,
  `setSettings(se.settings)` and `setDirty(false)` unconditionally, and
  `useLiveRefresh(load, 5_000)` at line 61 calls it every five seconds (and
  again on `window.focus`). `toggleBook -> mut` only ever writes local state,
  so the draft lived entirely in the component the poll was overwriting.
* Invariant broken: **a refresh owns the values that MOVE; the operator owns
  the fields they can type in.** The poll was added on Sep 10, 2026 for live
  W/L and took the whole payload with it, edit buffer included.
* Guard: `tests/test_an_unsaved_toggle_survives_the_refresh.py` — 9 tests,
  including one that pins `setDirty(false)` out of `load`'s body and one that
  proves `toggleBook` names no network call at all.

**SAW** — *"WHEN I CLICK LIVE TOGGLE OFF IT GOES BACK ON WHY?"*, then, after
a first answer that blamed the save step: *"MY ISSUE IS WHEN I CLICK LIVE
BUTTON IT GOES ON IMMEDIATELY BEFORE CLICKING SAVE BUTTON"*.

**TIMELINE**

Driven in a real browser against the running app at `Sep 14, 2026 5:27am`,
clicking the first LIVE pill on the trade grid:

1. `t = 7 ms` — `aria-checked` **true**. The pill goes red instantly.
2. `t = 1,003 ms` — still true.
3. `t = 3,016 ms` — still true.
4. `t = 6,015 ms` — **false**. The draft is gone, and so is the
   "unsaved changes" note.
5. Non-GET requests over that whole window: **0**. Nothing had been armed and
   nothing had been saved — the click simply evaporated.
6. 23 GET requests landed in the same window: the 5 s poll plus the other
   panels on the page.

The first diagnosis was WRONG and is recorded here because it cost the
operator a round trip: it said the toggle "never saved", which is true but is
not what they were asking. They were describing step 1 — a switch that looks
armed the moment it is touched — and step 4, which made it snap back before
SAVE was reachable. **They had to repeat themselves in capitals to get past
an answer that was technically correct and about the wrong thing.**

AFTER the fix, same browser, same page, rebuilt and restarted:

7. on at **11 ms**, still on at **6 s**, **12 s** and **18 s**.
8. **27 polls** landed in 11 seconds while the draft stood — the live numbers
   never stopped updating.
9. DISCARD returned it to off and cleared the banner.
10. Non-GET requests throughout: **0**.

**ROOT CAUSE** — a five-second poll called `setSettings` / `setRows` /
`setDirty(false)` unconditionally, so it overwrote an unsaved edit with the
copy on disk.

**WHY IT WAS NOT CAUGHT** — the poll was added on Sep 10, 2026 to answer
*"i want the ui realtime when i lose it should show the winrate lose"*, and
it was verified by watching a number CHANGE. Nobody typed into the page while
it ran. **A test for "does this update by itself" and a test for "does this
keep what I typed" look identical until someone types.** There is no test
anywhere in this repo that edits a control and then waits — every UI guard
here reads the source or asserts one render.

The second reason is the one worth keeping: the first answer to the operator
was assembled from the CODE PATH and their settings file, and it was
self-consistent and wrong about what they were seeing. The screen was never
driven until they insisted. **Reproduce the click before explaining the
click** — three of the four facts in the timeline above (7 ms, 6,015 ms,
0 writes) could not have come from reading the source.

**COST** — no money and no wrong order: the click never reached the server,
`toggleBook` has no network call, and the runner only reads the saved file.
The cost was the operator's control over their own real-money switches — they
could not reliably arm or disarm a strategy — and two rounds of being told
something they had not asked.

**FIX** — this commit. `load()` reads a `dirtyRef` and, while a draft is
pending, keeps `books`, `coins` and `base_margin` from the rows already on
screen and leaves `settings` alone; it no longer calls `setDirty(false)` at
all. Everything that moves — counts, locks, the account cap, conflicts, every
non-editable column — is still taken fresh on every poll. `save()` clears the
flag on success and deliberately KEEPS the draft when the live-lock guard
refuses with a 409. The banner now reads *"unsaved — the runner is still on
the saved config"* and carries a DISCARD button, since the poll no longer
drops a draft by accident.

**GUARD** — `tests/test_an_unsaved_toggle_survives_the_refresh.py`, 9 tests.
Verified RED on the pre-fix file (6 of the 9 fail there) and green after;
`tsc --noEmit` clean, `next build` clean, and the web UI restarted afterwards
so the running server is not serving chunks that no longer exist.

---

## RCA-2026-09-13-E — the indexer stood down for a backtest and had never heard of the other five jobs

**CEO**

* While your results were downloading this afternoon, the indexer was fighting
  the download for the same disk instead of waiting its turn. In twenty
  minutes it finished nothing at all — not one coin — and it made the
  download slower the whole time.
* Why: the indexer is supposed to stand aside whenever a big job is using the
  store. It only knew how to check for ONE kind of big job, and six kinds
  exist. A download of results was not on its list, so it never stood aside.
* What stops it now: it checks every kind, and when it stands aside it says
  which job it is waiting for. Measured cost of getting this wrong, from this
  project's own earlier notes: a big job ran at 36 coins an hour with the
  indexer fighting it and 220 an hour with it stopped — six times faster.

**DEV**

* `rows_index._machine_is_busy` read `db_jobs.status("backtest")` only, while
  `db_jobs.FILES` holds six kinds (download, backtest, pairbt, stratbt,
  collect, btupdate). With a collect running, it returned False and the
  trickle loop ran at full tilt.
* Invariant broken: the rule is "do not fight the machine's big job", stated
  in `sync`'s own docstring with the 36-vs-220 pairs/hour measurement behind
  it. The implementation encoded one instance of the rule, not the rule.
  Second break, same entry: the pause line printed the literal *"a backtest
  is running"* whatever was actually running (`label-must-match-data`).
* Guard: `tests/test_index_stall_is_visible.py` —
  `test_the_indexer_stands_down_for_EVERY_heavy_job` (parametrised over all
  six kinds), `test_a_job_that_cannot_be_read_does_not_pause_the_indexer`,
  `test_the_pause_NAMES_the_job_that_is_actually_running`,
  `test_status_says_WHO_paused_it`. Seven go red against the one-job rule.

**SAW** — nothing on screen; found while proving whether the indexer had
really recovered from RCA-2026-09-13-D.

**TIMELINE**

1. `Sep 13, 2026 4:04pm` — a collect starts (run 34739539427), 20 shards.
2. `4:30pm` — the indexer is restarted after the WAL repair (pid 12216).
   `_machine_is_busy()` returns False: `db_jobs.status("backtest")` says
   `running: false`, and nothing asks about the collect.
3. `4:35pm – 4:55pm` — measured: sustained **5,487 disk writes per 30
   seconds**, 105,453 writes total, WAL **200 MB → 486 MB**, and
   `MAX(at) FROM pairs` frozen at `Sep 12, 2026 7:09am` for the whole twenty
   minutes. **Zero pairs committed.**
4. `4:57pm` — py-spy, three samples 40 s apart, all identical:
   `index_pair (rows_index.py:492)` ← `sync (rows_index.py:917)`. Line 492 is
   `DELETE FROM rows WHERE pair = ?` — one pair's ~20,000 rows against SEVEN
   indexes on a 42 GB file, ~140,000 scattered index-entry deletions on a
   mechanical disk.
5. `5:10pm` — the collect had reached shard 6 of 20, **1,949 pairs,
   34,198,454 rows**, with the indexer competing throughout.
6. `5:12pm` — the indexer is stopped by hand so the collect gets the disk.
   Killing it mid-DELETE rolls the transaction back and costs nothing: the
   pair files are the source of truth.

**ROOT CAUSE** — a rule about "any heavy job" was implemented as a check for
one named job, and the six job kinds were never enumerated at the one place
that had to know them.

**WHY IT WAS NOT CAUGHT** — the 14 tests in
`tests/test_index_stall_is_visible.py` were bought by RCA-2026-09-10-C and
every one of them asks whether a failure is VISIBLE: is the error kept, does
the button print the real size, is the holder named. Not one asks whether the
indexer stands down when it should. The pause is the opposite shape from the
rest of that file — it is correct behaviour, so there is no failure to make
visible, and a suite built around "make the failure reachable" has nowhere to
put it.

It also cannot be seen from the symptom. A paused indexer and a starved
indexer look identical from outside: no pairs land. The difference is only
legible in disk I/O against a stack sample, which is why py-spy settled it in
one command after twenty minutes of inference.

**COST** — no money, no lost measurement, no trade. Roughly one hour of a
20-shard collect run slower than it needed to be, and 20 minutes of index work
thrown away on rollback. The measured ratio elsewhere in this project for the
same fight is 6x.

**FIX** — this commit. `rows_index.busy_job()` walks every kind in
`db_jobs.FILES` and returns the NAME of the first one running, `""` when none
is; `_machine_is_busy()` is now `bool(busy_job())`. Each `status()` call is
individually suppressed, so one unreadable progress file cannot read as "busy
forever" and stop the index dead — the fix must not become the silence it
prevents. The loop's pause line and `status()["paused_by"]` both carry the
real job name.

**GUARD** — `tests/test_index_stall_is_visible.py`:
`test_the_indexer_stands_down_for_EVERY_heavy_job` (parametrised over all six
kinds, and asserting each is still a real key in `db_jobs.FILES`, so adding a
seventh without teaching this rule fails here),
`test_nothing_running_means_the_indexer_works`,
`test_a_job_that_cannot_be_read_does_not_pause_the_indexer`,
`test_the_pause_NAMES_the_job_that_is_actually_running` and
`test_status_says_WHO_paused_it`. Seven assertions go red against the
one-job rule, and no existing test needed changing: `_machine_is_busy()`
stays the GATE that six tests across two files patch, and `busy_job()` only
supplies the name.

---

## RCA-2026-09-13-D — the rebuild handed over an index the indexer could never open for writing

**CEO**

* Your indexer — the thing that makes newly measured coins show up in Stored
  strategies — had been dead since yesterday morning. It crashed on its very
  first instruction, every single time it started, five times over 29 hours.
  A fresh download of results started at 4:04pm today and none of it would
  ever have appeared on your screen.
* Why: when I rebuilt your index yesterday I built the new file in a fast
  mode that skips crash protection, and I handed it over still in that mode.
  From then on the indexer had to switch the 41 GB file over before it could
  do anything — and switching needs the file entirely to itself for a moment,
  which it can never have, because your app reads it every second.
* What stops it now: the new file is switched over at the last moment it is
  still private, before it takes over as the live one — and if that ever
  fails, the rebuild still finishes and says so out loud instead of leaving
  you a file nothing can write to. Your live file was switched over at 4:30pm
  today and the indexer is filing again.

**DEV**

* `rows_index.rebuild()` loads with `PRAGMA journal_mode=OFF`
  (`rows_index.py:1329`) and swapped the file in as-is. `OFF` is not
  persistable, so the live `rows.db` reopened in `delete` —
  `journal_mode` is stored in the file header, which `_connect` states at
  `rows_index.py:289`: *"setting it per connection needs a brief exclusive
  lock, which any live reader blocks. Set once, in ensure()."* `ensure()`
  then raised `OperationalError: database is locked` at
  `rows_index.py:340` on `PRAGMA journal_mode=WAL`, on every spawn.
  `compact()` carried the same latent fault — `VACUUM INTO` writes the
  DEFAULT mode, also `delete`.
* Invariant broken: **a fresh file that takes the live name must arrive in
  the state the live name requires.** The rule existed and was written down
  three lines above the code that depends on it; the rebuild simply was not
  read as a maker of that file.
* Guard: `tests/test_rebuild_guards.py` —
  `test_the_swapped_in_index_is_already_in_WAL`,
  `test_a_compacted_index_is_in_WAL_too`,
  `test_a_file_that_refuses_WAL_is_still_swapped_in_and_named`.

**SAW** — the operator, `Sep 13, 2026 4:03pm`: *"STATUS"*. Nothing on their
screen showed this; Stored strategies answered every query correctly off the
5,392 pairs already filed, and would have gone on doing so while every new
coin silently failed to appear.

**TIMELINE**

1. `Sep 12, 2026 10:38am` — the rebuild swaps in a fresh 34.41 GB `rows.db`,
   verified, 5,392 pairs / 112,364,317 rows. Built with `journal_mode=OFF`.
2. `10:38am – 11:03am` — the queued `rows_wr2` build runs and succeeds (it
   opens its own connection and does not need the flip). The file reaches
   44.35 GB. **This is the last write the index ever receives.**
3. Every indexer spawn from here raises `database is locked` at
   `rows_index.py:340` within seconds. Five tracebacks land in
   `rows_index.log`, the last at `Sep 13, 2026 4:05pm`.
4. `Sep 13, 2026 4:04pm` — a cloud collect starts (run 34739539427) and
   begins landing new pair files: by 4:40pm, **635 pairs / 11,129,408 rows**
   over 2 of 20 shards. Every one of those pairs is stale and unindexable.
5. `4:06pm` — measured: `PRAGMA journal_mode` on the live file reads
   `delete`. Pidfile named pid 11124, which was not running.
6. `4:30pm` — the API is stopped for 3 seconds, `make_wal()` flips the file
   (`delete` → `wal`), the API is restarted (pid 19668, up in 2s).
7. `4:31pm` — `ensure()` no longer fails at line 340. It now fails at line
   392 on an ordinary INSERT, which is a DIFFERENT and healthy thing: the
   indexer has the write lock. Measured on the worker (pid 12216):
   **6,719 reads and 5,082 writes in 25 seconds**. It is filing again.

**ROOT CAUSE** — `rebuild()` and `compact()` each produce the file that
becomes `rows.db`, and neither put it into the journal mode that every writer
afterwards assumes, while the only code that would fix it can only run at a
moment when it is guaranteed to fail.

**WHY IT WAS NOT CAUGHT** — three reasons, and the third is the general one:

* **The failure was in a process nobody watches.** The indexer writes to
  `rows_index.log` (RCA-2026-09-10-C bought that), but nothing READS it. Five
  identical tracebacks sat there for 29 hours. A log is necessary and is not
  sufficient; something has to notice.
* **Every test of `rebuild()` runs in a `tmp_path` with no second process**,
  so the exclusive flip always succeeds there and the swapped-in file's mode
  is never asserted. Exactly the gap RCA-2026-09-12-K named yesterday for the
  swap itself, one layer along: the tests measure what the rebuild CONTAINS,
  never what state it LEAVES the file in.
* **`rebuild()` was written as a filler of a table, not as a maker of a
  file.** Its verify asks about rows, pairs and `quick_check` — everything
  about the CONTENT. The file's own properties (journal mode, page size,
  which indexes survive) were nobody's job, which is also how the on-demand
  indexes came to be destroyed silently by the same function last week.

**COST** — none yet, and only because it was caught while the collect was on
its second shard of twenty. Had it run to the end, ~5,000 pairs of freshly
measured results would have been invisible in Stored strategies with the panel
reporting no error at all.

**FIX** — this commit. `rows_index.make_wal(path)` is the one definition, and
both `rebuild()` and `compact()` call it on `dest` immediately before
`swap_in()` — the last moment the file is private and the flip is guaranteed
to get its exclusive lock. The result is returned as `journal_mode` in both
functions' dicts so it is reported, never assumed. A failure to set it does
NOT fail the swap: a `delete`-mode index still answers every read, only the
indexer cannot start, and that is a thing to repair rather than a reason to
discard five hours — it is caught, recorded as `NOT SET: <type>: <msg>`, and
printed. The operator's live file was flipped by hand at `Sep 13, 2026
4:30pm`.

**GUARD** — `tests/test_rebuild_guards.py`, 3 new tests (11 in the file): a
rebuilt index is in WAL and says so; a compacted one is too (`VACUUM INTO` is
the other maker, found by grepping the concept); and a file that refuses WAL
is still swapped in, with the failure named in the return. The first two go
red against the old code.

---

## RCA-2026-09-13-C — a failed index build threw away the one line that said why, and retried forever

**NEVER HAPPENED YET** as far as anything can tell — and that is the defect:
if it HAD happened there would be no record. Found Sep 13, 2026 4:20pm while
checking whether the app had the same flaw that took the API down in
RCA-2026-09-13-B.

**CEO**

* Your Stored strategies screen sometimes says *"this filter needs an index;
  it is being built in the background"*. That build takes about 45 minutes. If
  it ever failed, the reason went straight in the bin — and the app would
  start it again, and again, while the screen kept saying the same hopeful
  sentence forever.
* Why: the code that builds the index already writes a clear sentence when it
  fails. The code that STARTS it was throwing that sentence away instead of
  saving it to a file.
* What stops it now: those builds now write their reason into the same log
  the rest of the app uses, as it happens rather than at the end. If that
  log cannot be written at all, the build still goes ahead and says so out
  loud — a missing note must never cost you the index itself.

**DEV**

* `rows_index.py:2889` — `_spawn_build` passed `stdout=subprocess.DEVNULL,
  stderr=subprocess.DEVNULL`, so `build_index_now`'s own
  `print(f"[rows-index] could not build {name} after {n}s: …")`
  (`rows_index.py:2835`) had nowhere to land. `build_index_now` releases
  `_build_lock(name)` in its `finally`, so the next asker re-spawns: a
  deterministic failure loops with zero evidence.
* Invariant broken: **"a long-running process writes a LOG"** (CLAUDE.md, "A
  job that cannot start must SAY SO", RCA-2026-09-10-C). That fix landed in
  `spawn_indexer` and never reached this sibling.
* Guard: `tests/test_index_stall_is_visible.py` —
  `test_a_detached_index_build_writes_a_log_instead_of_DEVNULL`,
  `test_a_build_whose_LOG_cannot_open_still_builds`,
  `test_a_blind_build_does_not_claim_a_log_that_is_not_there`,
  `test_the_parent_does_not_leak_the_log_handle`. Three of the four go red
  against the old spawner; the fourth guards the fix's own failure mode.

**SAW** — nothing, which is the whole entry. On `Sep 12, 2026` five index
builds ran after the rebuild swap and all five succeeded (`rows_wr2` at
10:38am, the `#id` lookup answering by 11:08am, the signal filter by 11:13am),
so no failure was there to be lost. Nothing anywhere would have shown one.

**TIMELINE** — what would have happened

1. A build starts: `[rows-index] building rows_signal in pid 16148
   (detached)` — the only line, written by the PARENT.
2. 45 minutes later the child hits `database is locked` (the exact error that
   held this index for 13 hours on `Sep 10, 2026`). `build_index_now` prints
   `could not build rows_signal after 2731s: OperationalError: database is
   locked` — into `DEVNULL`.
3. `finally` unlinks the build lock. The panel still answers *"needs its index
   (rows_signal); it is being built in the background — try again shortly"*.
4. The next request re-spawns it. Go to 1. Nothing on disk ever changes.

**ROOT CAUSE** — the spawner discarded the child's stdout and stderr, which is
where the only explanation of a failed build is written.

**WHY IT WAS NOT CAUGHT** — `tests/test_index_stall_is_visible.py` was written
for exactly this fault and asserts it against **`spawn_indexer` by name**
(`test_the_indexer_writes_a_log_instead_of_DEVNULL`,
`test_the_log_is_not_buffered_away`, both reading
`inspect.getsource(ri.spawn_indexer)`). `_build_index` starts a different
long-lived child in the same module and no test named it. This is **"when
changing a rule, grep for the CONCEPT"** (CLAUDE.md, Sep 04) in its
test-shaped form: a guard pinned to one function's NAME does not defend a
rule. The new tests drive the spawner and read the Popen kwargs, so any third
spawner added later is covered by the same argument rather than a new grep.

**COST** — none. No build is known to have failed.

**FIX** — this commit. `_build_index` opens `LOGFILE` in append mode and
passes it as `stdout` with `stderr=subprocess.STDOUT`, and adds
`PYTHONUNBUFFERED=1` to the child env. The log is opened in its OWN
`try/except OSError` with `subprocess.DEVNULL` as the fallback, because the
first draft let an unopenable log reach the spawner's `except` — which would
have meant an index that used to build never building again, to gain a log
nobody could read. The "building …" line names the log only when there IS one
and prints `NO LOG` otherwise (`label-must-match-data`), and the parent closes
its own copy of the handle in a `finally` so the API process does not leak one
per build over weeks of uptime.

**GUARD** — the four tests named in DEV, plus `tests/test_detached_spawns.py`
from RCA-2026-09-13-B, which covers the same function's creation flags.

---

## RCA-2026-09-13-B — the app was dead for 28 hours and the only thing that would have noticed was me

**CEO**

* Your app's back end was down from Sep 12, 2026 11:44am to Sep 13, 2026
  4:05pm — **28 hours 18 minutes**. Every screen that reads data would have
  been blank or spinning.
* Why: I restarted it after the index rebuild, but I started it the wrong way —
  hooked to my own session instead of standing on its own. When my session's
  processes were cleaned up, your app was cleaned up with them. Then I read my
  own "API back up" message as proof and never checked again.
* What stops it now: a test that checks every place this project starts a
  long-running program and fails if it is not properly cut loose. **Your
  trading was never affected** — the runner kept going the whole time and took
  7 entries and 2 exits while the screen was dark.

**DEV**

* The swap guard (`scratchpad/swap_guard.py`, and the older
  `scratchpad/restart_api.py`) used
  `creationflags=CREATE_NEW_PROCESS_GROUP` only. That flag separates a child
  from the parent's Ctrl-C; it does **not** detach it. `start.py:139` uses
  `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`, which is the only form that
  survives the parent's tree being reaped.
* Invariant broken: **"the exchange is the source of truth, never the local
  book"** (CLAUDE.md rule 14) applied to my own reporting — *"the request was
  sent" is not "it is in place"*. `start_api()` polled `/api/health` once at
  t+18s and I reported success from that single sample, for a process whose
  whole failure mode is dying later.
* Guard: `tests/test_detached_spawns.py` — walks the AST of `start.py` and
  every module under `tradingagents/`, folds each creation-flag expression to
  a number, and fails any long-lived spawn missing either flag.

**SAW** — the operator, `Sep 13, 2026 4:03pm`: *"WHY DID YOU NOT RESTART"*.

**TIMELINE**

1. `Sep 12, 2026 10:21am` — the swap guard stops the API on purpose, so the
   6-hour rebuild can move `rows.db` (Windows refuses to move a held file).
2. `10:38am` — the swap lands. The guard restarts the API as **pid 16988** and
   confirms `/api/health` answers. I report "API back up".
3. `11:13am – 11:44am` — the API serves normally; I use it for the cascade
   counts. Last line in `api.log`: `GET /api/health HTTP/1.1 200 OK`.
4. `11:44am` — the API stops. **No traceback, no shutdown line, nothing.** Its
   parent shell was reaped and it went with it.
5. `Sep 13, 2026 4:02pm` — `curl /api/health` returns **000** (no connection).
   No `uvicorn` process on the machine. Down **28 h 18 min**.
6. `4:05pm` — restarted via `start.spawn` as **pid 18256**, up in 18 seconds.
7. Same minute, measured: the runner was never affected — pids 9004/19428
   alive since `Sep 12, 2026 2:27am`, **911 ledger rows** since 11:44am
   (896 `gate_blocked`, 7 `enter`, 2 `exit`, 5 `error`, 1 `coin_busy`).
   Example trade: `#ML5W2LSD` KITE_USDT SHORT, `squeeze_1h_sl3tp3`, entry
   0.1063, TP 0.103111, SL 0.109489, $1 margin, 20x, opened
   `Sep 12, 2026 4:00pm`, closed `Sep 13, 2026 1:54pm`.

**ROOT CAUSE** — a helper script started a long-lived service with one of the
two Windows flags that detach a process, so the service was a child of a shell
that did not last.

**WHY IT WAS NOT CAUGHT** — three layers, and the third is the one worth
keeping:

* **Nothing on this machine watches the API.** Every job here has a progress
  file, a log and a bell. The thing all of them are *displayed in* has none.
* **The spawn sites were unfindable by name.** Grepping
  `DETACHED_PROCESS` returns `rows_index.py:2895` and
  `storage_months.py:556` — both **comments**; those two files spell the
  actual flags `0x00000008 | 0x00000200`. So a name search finds prose and
  misses code, and a hex search misses `start.py` and `live_ingest`, which use
  the names. Same shape as the `.toLocale` grep of Sep 09. The new guard folds
  the expression to a NUMBER and accepts either spelling.
* **I verified at t+18s a failure whose whole nature is arriving later.** One
  health check right after start proves the port opened, nothing more. The
  honest check for "did it survive" happens after the thing that kills it —
  which for a process attached to my shell means after my shell is gone.

**COST** — no money, no lost data, no missed trade, no measurement lost. The
operator's screen, for 28 h 18 min, plus their time asking why.

**FIX** — this commit adds the guard. The API itself was restarted at
`Sep 13, 2026 4:05pm` with `start.spawn` (pid 18256), which is the launcher
that sets both flags. The scratchpad helpers that caused it are throwaway and
are not in the repository; the rule they broke now has a test in it.

**GUARD** — `tests/test_detached_spawns.py`, 5 tests: the probe must find at
least four real spawn sites before any of its verdicts count (a probe that
finds zero has verified nothing), and each site must set BOTH flags. Proved
red by dropping `DETACHED_PROCESS` from `rows_index.py:2907`. It deliberately
skips blocking `subprocess.run` calls — the first version failed
`portable.py:199`, a `wmic` call that uses `CREATE_NO_WINDOW` to hide a
console window and returns in milliseconds.

---

## RCA-2026-09-13-A — the Runner feed showed an eight-day-old bar for coins whose candles were current

**CEO**

* The feed said four of your coins had last seen a candle on Sep 05 while
  the runner had been up 38 hours and their data was completely up to date. It
  reads as a dead price feed, and that is exactly how it was read.
* Why: the line adds up every slot's record of "last candle I looked at", and
  a slot keeps that record after the strategy that wrote it is gone. Those
  four numbers were left behind by a change on Sep 05 and never moved again.
* What stops it now: only a timeframe something is actually watching on that
  book can speak for the coin, and a book with nothing armed says so in words
  instead of showing a date. No trade, position or exit was ever decided by
  this value — it was a caption, and the caption was wrong.

**DEV**

* `auto_trader.py:4421` built `seen` as a union of `state[slot]["last_ts"]`
  over `book_slots(state, symbol, dry)`, unfiltered. Every write to `last_ts`
  lives in the entry loop (`:3812`, `:3839`, `:3867`, `:3886`, `:3950`,
  `:4001`), and since partial TP/SL the real BASE slot is visited with
  `entries=False` (`:3319`), so its stamps froze the day the switch was made.
* Invariant broken: **a label must be derived from the data it describes.**
  `last_bars` claimed to describe this coin's feed and actually described the
  union of some dead slots' memories. The line now filters to intervals armed
  for this coin on THIS book, plus the interval of any open position whose
  strategy was disarmed while holding.
* Guard: `tests/test_the_scan_line_names_only_live_bars.py` — 6 tests driving
  `run_cycle` with the operator's own slot shapes. Red on the pre-fix file for
  both incident cases.

**SAW** — `Sep 13, 2026 4:01pm`, four lines in the Runner feed:
`scan GPNSTOCK_USDT[real] ... last_bars=Min15@Sep 05, 2026 9:00am
Min30@Sep 13, 2026 3:30pm` and `scan KITE_USDT[real] ...
last_bars=Min60@Sep 05, 2026 8:00am`, with ROLSTOCK and DVNSTOCK the same.

**TIMELINE**

1. `Sep 05, 2026` — partial TP/SL moved the real book onto per-strategy slots
   (`SYM#live#KEY`). The base slot `SYM` kept being visited so a position
   opened before the switch stays managed, but with `entries=False`.
2. Its `last_ts` stopped advancing that day: GPNSTOCK froze at
   **Min15@9:00am**, KITE and ROLSTOCK at **Min60@8:00am**, DVNSTOCK at
   **Min15@9:00am**.
3. `Sep 13, 2026 4:01pm` — 38 hours into a healthy runner (pid **19428**, lock
   held), the feed still printed those four dates. Measured at the same
   moment, the live per-strategy slots read **Min30@Sep 13, 2026 3:30pm** —
   the same coin, the same process, eight days apart on one line.
4. On KITE, ROLSTOCK and DVNSTOCK the base slot is the ONLY real slot and
   nothing is armed on the real book at all, so the fossil WAS the whole line:
   `0 of 1 slot(s) open` where the 1 is a leftover.
5. After the fix, the same state prints `last_bars=Min30@Sep 13, 2026 3:30pm`
   for GPNSTOCK and `last_bars=nothing armed on this book` for the other
   three.

**ROOT CAUSE** — an unfiltered union: `for _tf, _ts in _ls.items()` over every
slot the coin has ever had on this book. A slot's memory outlives its
strategy, so the union mixed live readings with fossils and printed them in
one sentence with no way to tell which was which.

**WHY IT WAS NOT CAUGHT** — no test anywhere asserts on this line; a grep for
`last_bars` across `tests/` returns nothing. It is a log line, and log lines
are treated as commentary rather than as product — but this one is the answer
to *"why has this coin not traded"*, which is the question the feed exists to
answer. **A line the operator reads to make a decision is a product surface
and needs a test, even when it changes nothing.** The same blind spot that
CLAUDE.md already records for the runner's own timestamps ("LOG LINES COUNT")
applies to their CONTENT, not only their format.

**COST** — none in money and none in behaviour: this value never reached an
order, a barrier or a book. It cost an investigation, and it would have cost
more the next time a feed really did go stale, because the feed had been
crying wolf on four coins for eight days.

**FIX** — this commit. `auto_trader.run_cycle` filters the union to watched
intervals and distinguishes "nothing armed on this book" from "none yet".

**GUARD** — `tests/test_the_scan_line_names_only_live_bars.py`, verified red
on the pre-fix file (2 of 6, both incident cases).

---

## RCA-2026-09-12-K — the last 8 seconds of a 6-hour rebuild could throw all of it away and still read "verifying"

**NEVER HAPPENED YET.** Found at `Sep 12, 2026 9:35am` while the rebuild it
would have destroyed was still running (pid 12576, verify phase, due to reach
the swap around `11:00am`). The timeline below is what WOULD have happened,
and the three measured facts under it are real.

**CEO**

* Nothing was lost. I found this while waiting for your rebuild to finish —
  the very last step, moving the new index into place, was the one step that
  could fail **without telling anyone**. Your screen would have said
  "verifying" forever, and the six hours would have looked like a stall.
* Why: the app itself keeps the old index file open all day, and Windows
  refuses to move a file another program is holding. That refusal was
  happening in the one part of the job that had no one listening for it.
* What stops it now: the move is watched like every other step, so a refusal
  is reported in plain words — *"close whatever holds rows.db open"* — and it
  names the finished file so the work is never thrown away. It also does the
  risky part FIRST: it used to delete your backup and your unsaved changes
  before attempting the move that fails, so a refusal destroyed two things
  and achieved nothing.

**DEV**

* `rows_index.py:1479` — `shutil.move(str(DB_PATH), str(backup))` sat AFTER
  `rebuild()`'s `try/except`, so `PermissionError(32)` propagated out of the
  function. `_say("failed: …")` is only reachable from inside that block, so
  `rows_rebuild.json` keeps its last value — `{"phase": "verifying"}` — and
  `main()` prints a traceback to a log nobody is tailing. `compact()` carried
  the identical six lines with the identical hole.
* Invariants broken: **"a job that cannot start must SAY SO"** (CLAUDE.md,
  RCA-2026-09-10-C) — a swallowed failure is a button that lies, and an
  ESCAPED one is the same lie; and **"when changing a rule, grep for the
  CONCEPT"** (CLAUDE.md, Sep 04) — two copies of the swap, both wrong the
  same two ways.
* Guard: `tests/test_rebuild_guards.py` — `test_a_held_index_file_makes_the
  _swap_SAY_FAILED_not_raise`, `test_a_failed_swap_leaves_the_live_index
  _exactly_where_it_was`, `test_the_retired_index_keeps_the_wal_it_arrived
  _with`, `test_both_swaps_are_the_same_one`. All four go red against the
  old swap; proved by reintroducing it.

**SAW** — nothing, and that is the defect. The operator's Stored strategies
panel would still have been empty and `rows_rebuild.json` would still have
read `{"phase": "verifying", "rows": 112364317}`.

**TIMELINE** — what would have happened

1. `Sep 12, 2026 5:50am` — `python -m tradingagents.rows_index --rebuild`
   starts as pid 12576.
2. `7:11am` — load finishes: **5,392 pairs, 112,364,317 rows in 5,503 s**
   (65.97 pairs/min).
3. `7:11am → 8:33am` — the four kept indexes, **82 minutes**.
4. `8:33am` — verify begins, estimate **8,394 s**.
5. `~11:00am` — verify passes. `rebuild()` reaches
   `shutil.move(rows.db → rows.before-rebuild.db)`. **The API (pid 20320,
   `uvicorn tradingagents.api:app --port 8787`) has had `rows.db` open since
   it started.** Windows raises `PermissionError(32)`.
6. The raise escapes `rebuild()`. Before it: `backup.unlink()` had already
   deleted the previous 34.69 GB backup, and `Path(rows.db-wal).unlink()`
   had already tried to delete the live file's write-ahead log.
7. `rows_rebuild.json` still reads `"phase": "verifying"`. The watcher waits.
   `rows.rebuild.db` — **34.41 GB, verified, complete** — sits on disk with
   nothing pointing at it.

**Three measured facts, today, not hypothetical:** the rebuild is pid 12576
in the verify phase; the API holds `rows.db` as pid 20320 under launcher
14940; and `rows.db` is **65.15 GB** against the finished `rows.rebuild.db`
at **34.41 GB**.

**ROOT CAUSE** — the swap ran outside the try/except that reports every other
phase, and its steps were ordered so that the one that can fail came last,
after two that cannot be undone.

**WHY IT WAS NOT CAUGHT** — `rebuild()` had **no production caller** until
today (it is named in `tests/test_rebuild_from_the_pair_files.py` eight times
and nowhere else), and every one of those tests runs in a `tmp_path` where
**nothing else has the file open**. A failure mode that only exists when a
second process is holding the file cannot appear in a suite where there is no
second process. The three guards written on Sep 12 morning
(`test_rebuild_guards.py`) asked what happens when a pair file cannot be
READ — the loading phase — and stopped at the gate before the swap, because
that is where the previous six hours had been lost.

This is the same lesson as **"test the path the RUNNER takes, in the state it
will run in"** (CLAUDE.md, Sep 05): the eleven passing tests there drove
`process_symbol` while the runner entered at `run_cycle`, and the
verification ran paper-only while the guard was live-only. Here the state
that was never reproduced is *"another process has this file open"* — which
on this machine is the normal state, every hour of every day.

**COST** — none. Found before it fired, with the job it would have hit still
running. Had it fired: 5 h 10 min of rebuild wall-clock, plus however long
the "verifying" line went unquestioned.

**FIX** — this commit. `rows_index.swap_in(dest, backup, keep_backup=)` is
now the ONE definition of the swap and both `compact()` and `rebuild()` call
it inside a `try/except` that writes `failed: …` to the progress file, prints
it, and returns `{"rebuilt": False, "why": …, "rebuild_file": <the finished
file>, "holder": lock_holder()}`. Order reversed: the move that can fail runs
FIRST, before the previous backup is cleared of anything irreversible. The
live `-wal` is **moved to the backup** rather than deleted, so the retired
index stays a consistent fallback and the name is still freed (a stale
`rows.db-wal` beside a different `rows.db` is corruption, not clutter).
`put_back()` restores the retired file — with its WAL — if the move got half
way. The `keep_backup=False` cleanup suppresses `OSError`, not just
`FileNotFoundError`: it runs after the new file is already in place, so a
refusal there would have reported a swap that SUCCEEDED as failed.

For the run that is in flight, a guard process
(`scratchpad/swap_guard.py`) stops the API at `seconds >= 16000` — about 35
minutes before the verify is due to end — and restarts it the moment the
phase reads `done`, because pid 12576 loaded the OLD module and no edit made
today can reach it.

**GUARD** — `tests/test_rebuild_guards.py`, 4 new tests (8 in the file). A
held file must make the swap SAY FAILED rather than raise, and the progress
file must carry it; a failed swap must leave `rows.db` byte-identical and
still answering `query()`; the retired index must keep its WAL and the new
one must not inherit it; and both swaps must be the same function — that last
one greps CODE lines only, because the first version of it failed on the
comment that EXPLAINS the old bug.

---

## RCA-2026-09-12-J — 211 GB of abandoned git transfers on the store's own drive, built up over six days and still growing

**CEO**

* Your G: drive had lost **211 GB** to junk files nobody had looked at. They
  had been piling up since Sep 06 and a new one arrived while I was reading
  the folder. After clearing them the drive went from **314.7 GB free to
  538.3 GB free**, and the repository folder from **219 GB to 11 GB**.
* Why: the app asks GitHub for the machines' live progress by downloading a
  branch. That branch had grown to **250,966 saved states** because twenty
  machines write one every few seconds — so the download got slower every
  day, and every download that ran out of time left its half-finished file
  behind. Nothing ever removed them, and the fuller the folder got the slower
  the next download was, which made it fail more often.
* What stops it now: the app downloads only the latest state instead of the
  whole six-day history, and it clears any half-finished download older than
  an hour before it starts. Your own work history is untouched — the
  repository still goes all the way back to its first day.

**DEV**

* `cloud_sweep._fetch_progress` ran a full `git fetch` of `sweep-progress`
  (250,966 commits) on a 180 s timeout, while its only reader,
  `live_progress`, does `git show <ref>:progress/run-<id>/shard-<n>.json` —
  the TIP, never the history. Each timeout left a partial
  `.git/objects/pack/tmp_pack_*`, which git's own `count-objects -vH` reports
  as "garbage found"; 6,876 of them held 211.05 GB against 6.97 GB of real
  packs.
* Invariant broken: **"temporary" is a promise the code has to keep**
  (CLAUDE.md, "Big files go where the STORE is"), and **measure the SIZE
  before calling something temporary**. Both rules were written on
  2026-09-10 for `%TEMP%` scratch and never applied to the transfers this
  repo's own git makes on the same drive.
* Guard: `tests/test_the_progress_branch_does_not_eat_the_disk.py` — 8 tests;
  the "only the tip is read" argument is asserted, not assumed, so a future
  history walk fails here rather than silently breaking on a shallow clone.

**SAW** — not reported: found at `Sep 12, 2026 3:41am` while establishing why
the cloud panel's per-machine detail would not arrive for run 34631292767,
which was measuring perfectly.

**TIMELINE**

1. `Sep 12, 2026 3:24am` — the panel showed `available: true` with the right
   run and `shards: []`. The run itself was healthy: 20 shards, in progress.
2. `3:30am` — `_fetch_progress` timed out at **180.6 s** and was killed (the
   bounded timeout from RCA-2026-09-12-I, working). `live_progress` then
   answered **20 shards in 114.4 s** off the ref an earlier fetch had left,
   so the data was reachable and the fetch in front of it was not.
3. `3:35am` — `git count-objects -vH` printed `warning: garbage found:
   .git/objects/pack/tmp_pack_...`, repeatedly.
4. `3:41am` — counted: **6,876 `tmp_pack_*` files, 211.05 GB**, against
   **59 real `.pack` files, 6.97 GB**. Oldest `Sep 06, 2026 12:41pm`, newest
   `Sep 12, 2026 3:41am` — arriving as it was being measured. `.git` totalled
   **219.03 GB**; G: had **314.7 GB free of 909.5**.
5. `origin/sweep-progress`: **250,966 commits**.
6. `3:50am` — deleted every `tmp_pack_*` older than two hours (the fetch
   timeout is 180 s, so nothing live is close): **6,862 files, 208.36 GB**.
   13 recent ones were deliberately kept.
7. `3:55am` — `.git` **11.04 GB**, G: free **538.3 GB**. Main's history
   intact: 695 commits, still reaching the original root `c2fa046a9bc1`
   ("TradingAgents-AI"); `.git/shallow` holds four entries, all on the
   progress branch.
8. With `--depth=1`, three consecutive fetches measured **69.3 s** (the first
   also establishes the boundary), **42.8 s**, **19.3 s** — against a 180 s
   timeout it had been exceeding.

**ROOT CAUSE** — an append-only progress branch was fetched in full on every
poll although only its tip is read, and every fetch that timed out left a
partial pack that nothing ever removed.

**WHY IT WAS NOT CAUGHT** — the disk rule in CLAUDE.md was bought on
2026-09-10 by 147 leaked `tmp*` folders in `%TEMP%`, and the guards written
for it ask where a `TemporaryDirectory` is created. Not one asks about the
bytes a SUBPROCESS writes on our behalf, in our own `.git`, on the store's
drive. **We audited the temporary files we create and ignored the ones we
cause.** The second half of the rule was skipped too — "measure the SIZE
before calling something temporary": nobody had ever counted the progress
branch, and 250,966 commits is not a number anyone would have guessed from
"a small JSON file per machine".

It was also invisible from the symptom: a slow fetch looks like a slow
network, and the feedback loop hid its own cause — each timeout made `.git`
bigger, which made the next fetch slower, which made another timeout more
likely. The thing that finally pointed at it was git's own
`count-objects -vH`, which had been saying "garbage found" all along to
nobody.

**COST** — no money, no lost measurement, no trade affected. **211 GB of the
operator's 909 GB store drive for six days** — the same drive the candle and
row stores live on, and the drive they moved everything to specifically to
keep big files off C:. Plus the cloud panel's per-machine detail, which was
the visible symptom.

**FIX** — this commit. `_PROGRESS_FETCH = ("--depth=1", "--no-tags",
"--force", "origin")`, used by both the fetch and its retry-after-lock-race;
and `_sweep_dead_packs()`, which runs before each fetch (at most once every
ten minutes) and unlinks `.git/objects/pack/tmp_pack_*` older than
`DEAD_PACK_S` (3600 s), in this repository's pack directory only, logging
what it freed. A file another git process holds open is skipped, not raised.
The 208.36 GB already on disk was deleted by hand at 3:50am.

**GUARD** — `tests/test_the_progress_branch_does_not_eat_the_disk.py`, 8
tests: the fetch is shallow in BOTH places; only the tip is read (asserted
against the AST of `live_progress`); an hour-old partial pack is removed
while a live one and every real `.pack`/`.idx` survive; the sweep is rate
limited; it touches nothing but our own prefix in our own directory; an
open handle is not an error; the sweep runs BEFORE the fetch that might
leak; and it prints what it freed. Every "this call is not made" assertion
runs against code with docstrings and comments stripped, because the
explanation names the call it forbids — the trap this repo has now paid for
five times.

---

## RCA-2026-09-12-I — one hung `git fetch` blanked the cloud panel until the API was restarted, because a subprocess timeout is not a guarantee

**CEO**

* While your 1,054-coin update ran on 20 machines, the panel that shows it
  said "reading GitHub in the background" and nothing else — for seventeen
  minutes, and it would have said that until the app was restarted. The run
  was completely healthy the whole time: 291 coins done, 24 million rows, no
  failures.
* Why: the app asks git for the machines' progress. One of those git commands
  got stuck waiting, and the safety timer that was supposed to cut it off had
  a hole — after the timer fired, the app sat waiting for the stuck command's
  leftovers instead. Nothing could ask again after that.
* What stops it now: git is never allowed to stop and ask a question (there
  is nobody at the keyboard to answer it), the safety timer now kills the
  whole thing and gives up after ten more seconds no matter what, and the
  screen keeps showing the last known progress instead of going blank.

**DEV**

* `cloud_sweep._git` used `subprocess.run(..., timeout=)`. Its TimeoutExpired
  path kills the DIRECT child and then calls `communicate()` with NO timeout
  to drain the pipes; `git fetch` spawns `git-remote-https`, which inherits
  those handles and outlives the kill, so the drain blocks for ever. py-spy
  on pid 14732: `_git -> run (subprocess.py:565) -> communicate ->
  _communicate -> join`, under thread `cloud-status`, in
  `_read_cloud_status -> slow_cache._work`. `BackgroundValue` holds `_busy`
  until the reader returns, so `get()` could never start another read.
* Invariant broken: **a bounded call must be bounded on every path**, and the
  library call that looks like the bound is not one. Underneath it, a cache
  whose refresh flag is only cleared on the success path is a latch, and one
  wedged read closes it permanently.
* Guard: `tests/test_a_hung_git_cannot_blind_the_cloud_panel.py` — 7 tests,
  including one that drives a real 60-second child through `_git` with a
  2-second timeout and asserts it returns in under 20.

**SAW** — found while watching run 34631292767 for the operator after they
asked to press UPDATE and be told about any errors. `/api/cloud/status`
answered `{"available":false,"why":"reading GitHub in the
background","reading":true,"run":null,"shards":[]}` on every poll.

**TIMELINE**

1. `Sep 12, 2026 2:08am` and `2:13am` — the endpoint answered normally: 4,
   then 7 shards reporting, 289,466 then 673,616 rows. Nothing was wrong.
2. `2:27am` — the API was restarted (another session's commits), so the
   cached value was discarded and a fresh read began.
3. `2:42am` — every poll returned the PENDING payload. The run itself,
   checked straight against GitHub with `gh run view`, was
   `in_progress` with 20 shards healthy.
4. `2:44am` — py-spy on the listening process (pid 14732, found by port, not
   by `api.pid`, which was stale) put the `cloud-status` thread in the
   post-timeout drain. It had been there 17 minutes.
5. Measured the same read from a SECOND process, where it was not wedged:
   **31.9 s**, against `CLOUD_STATUS_TTL` of **30.0 s**. A second run of the
   fetch alone took **33.4 s**. The value was stale the instant it landed, so
   the background thread ran back to back for the length of the sweep,
   git-fetching the branch the 20 shards were pushing to.
6. `2:52am` — the API restarted on the fixed code.
7. `2:55am` — the panel answered in full: run **34631292767**, 20 shards,
   **291 of 1,068 coins (27.2%)**, **24,029,290 rows**, **1,196 pairs posted
   live**, **0 failed**. All of that had been true and invisible.

**ROOT CAUSE** — `subprocess.run`'s timeout kills the child and then drains
its pipes with no timeout; a surviving grandchild holds those pipes open, so
the "timed out" call never returns.

**WHY IT WAS NOT CAUGHT** — `tests/test_cloud_status_never_waits_on_github.py`
exists and passes. It guards the REQUEST — that the route answers from the
background value and never blocks — which is the fault of Sep 09 (RCA-A/I).
Nothing asked what happens when the BACKGROUND READ itself never finishes,
because a reader that hangs has no observable behaviour to assert unless you
decide the hang is a product surface. Same blind spot as RCA-2026-09-10-C,
where 289 index tests all covered what the index contains and none covered
the fill failing to start. **A cache makes a slow read safe; it does nothing
about a read that never returns, and the second failure looks exactly like
the first from the outside — which is why the panel's message was reassuring
prose rather than a duration.** The new guard drives a real child that
ignores its deadline.

Two smaller things this exposed, both fixed here: a TTL shorter than the read
it drives means the value is never fresh and the thread never rests (30 s
against a 31.9 s read); and `api.pid` named a process that was not the API —
the listening pid had to be found through the port, the same recycled-pid
shape as RCA-2026-09-12-B the same night.

**COST** — no money and no lost measurement: the run was correct throughout
and its rows landed live (1,196 pairs by 2:55am). The cost was the only
window onto a multi-hour job the operator had just started and explicitly
asked to be watched.

**FIX** — this commit. `cloud_sweep._git` runs git through `Popen` with
`stdin=DEVNULL` and `_GIT_NO_PROMPT` (`GIT_TERMINAL_PROMPT=0`,
`GIT_ASKPASS=echo`, `SSH_ASKPASS=echo`, `GCM_INTERACTIVE=never`,
`GIT_OPTIONAL_LOCKS=0`), and on timeout calls `_git_kill_tree` — `taskkill
/T /F` on Windows, `killpg` elsewhere — then drains with a BOUNDED
`communicate(timeout=10)` and raises. `api.CLOUD_STATUS_TTL` 30 -> 90, above
the measured read. `slow_cache.BackgroundValue._work` clears `_busy` in a
`finally`, so a reader that raises a `BaseException` (or an `on_error` that
raises) can no longer latch the cache shut for the life of the process.

`_git_kill_tree` uses `taskkill` rather than `portable.child_pids`: the first
version asked PowerShell for the process table and measured **20 seconds of
the 32** the timeout path took, on the very thread a blank panel is waiting
on. A cleanup slower than the hang it cleans up after is its own hang.

**GUARD** — `tests/test_a_hung_git_cannot_blind_the_cloud_panel.py`, 7 tests:
git is launched with no stdin and every prompt door shut; the environment is
proved to reach the child by asking git itself; a real `sleep 60` child
driven through a 2-second timeout raises in under 20 s; the post-kill drain
carries its own timeout; the kill takes the tree (asserted against the AST,
because the docstring names `child_pids` to explain why it is NOT used); the
TTL is longer than the read; and a slow refresh still serves the last good
answer instead of `pending`.

---

## RCA-2026-09-12-H — the REINDEX button offered a 4-pair job for a 5,206-pair walk, because the fix for that had stopped at the API

**CEO**

* The button under Stored strategies said "index the missing 4 pair(s) now".
  The job behind it had 5,206 coins to work through — more than a thousand
  times what the button promised. Press it and it would have looked stuck
  forever, or finished-in-a-second and wrong.
* Why: there are two counts. One is "coins never indexed" (4). The other is
  "coins whose results have changed since they were indexed" (5,206), and
  that is the one the job actually walks. The button was printing the first.
* What stops it now: the button reads the same number the job sizes itself
  with, and a test checks the button, not only the code behind it. This is
  the same mistake as Sep 10 — it was fixed then in the part the screen does
  not show.

**DEV**

* `api.strategies_reindex` has computed `todo = stale or behind` since
  RCA-2026-09-10-C and is guarded by
  `test_the_route_prints_the_bigger_number`. `StrategiesPanel.tsx:935`
  rendered `idx.behind.toLocaleString()`, and `IndexStatus` in
  `webapp/src/lib/api.ts` did not even declare `stale`, so the browser could
  not have printed it. Measured on the operator's store, Sep 12, 2026
  2:35am: `behind: 4`, `stale: 5,206`, `pairs_indexed: 5,388`,
  `rows: 96,307,386`.
* Invariant broken: **the number a button prints is the number of work it
  will DO** — and, underneath it, a guard is only as wide as its pattern.
  The Sep 10 guard asserted on `inspect.getsource(api.strategies_reindex)`
  and never opened the component, so the half of the fix the operator can
  see was never covered.
* Guard: `tests/test_index_stall_is_visible.py::
  test_the_BUTTON_prints_the_bigger_number_too`, which reads the panel and
  the client type, and pins `catchingUp` to `behind` on purpose.

**SAW** — found on Sep 12, 2026 while establishing why ten new cascade rules
returned 0 rows (RCA-2026-09-12-D). The operator would have met it at the
moment they tried to fix that themselves.

**TIMELINE**

1. `Sep 10, 2026` — RCA-2026-09-10-C fixed the route: a button that printed
   806 for a job walking 5,276 pairs. `test_the_route_prints_the_bigger_
   number` was written against `api.strategies_reindex`.
2. `Sep 11, 2026` — ten `cx_*` cascade rules were measured across the market.
   6,845,648 rows landed in the pair FILES; the index was not refreshed.
3. `Sep 12, 2026 2:20am` — `signal=cx_veto` -> **0 rows** through the real
   API. `rows_index.status()`: `behind: 4`, `stale: 5,194`.
4. `2:35am` — the same read, fifteen minutes later: `stale: 5,206`. It climbs
   while a collect lands rows, which is why the catch-up must wait for quiet.
5. The panel's button read **"index the missing 4 pair(s) now"** throughout.
   The route, if pressed, would have started a 5,206-pair job — correct work
   under a label off by a factor of 1,301.
6. `2:45am` — with the panel change stashed, the new guard fails; with it,
   it passes.

**ROOT CAUSE** — the label was rendered from `behind` while the job is sized
from `stale or behind`, and the client type did not carry `stale` at all.

**WHY IT WAS NOT CAUGHT** — the guard written for this exact fault on Sep 10
reads the Python route's source and stops there. The failing surface is a
React component; nothing in the test suite connected the two. **When a fix
has an API half and a screen half, the guard must assert both halves or it
certifies the half nobody looks at.** This is the third variant of "a guard
is only as wide as its pattern" in four days (the `.toLocale` grep on Sep 09,
the `%Y` grep on Sep 12), and the first where the pattern was right and the
FILE was wrong.

**COST** — no money. The cost was the operator's only lever for making 6.8
million measured rows searchable, labelled as a job not worth pressing.

**FIX** — this commit. `const indexTodo = Number(idx?.stale ?? 0) ||
Number(idx?.behind ?? 0)` in `StrategiesPanel.tsx`, the button labelled from
it ("index the 5,206 pair(s) that moved since they were indexed"), and
`stale?: number | null` added to `IndexStatus`. `catchingUp` deliberately
keeps `behind`: `stale` stays ~5,200 for the length of a sweep and would arm
the 60 s background refresh permanently, which is the regression the comment
above it records.

**GUARD** — `tests/test_index_stall_is_visible.py::
test_the_BUTTON_prints_the_bigger_number_too`. Verified RED with the panel
change stashed and green with it.

---

## RCA-2026-09-12-G — "no stored strategy passes" was a claim about 893,508 rows, made after checking 25

**CEO**

* Your filter — Past 30 days, Winrate 85% or better, TP at least as wide as SL
  — said **no stored strategy passes**. That was not true. Real strategies
  passed it; the screen just never looked at them.
* Why: 893,508 of your saved strategies clear the win-rate and TP/SL parts. But
  "past 30 days" has to re-run each one against your stored candles, which is
  slow, so the page only ever fetches **25** — the 25 with the biggest lifetime
  profit. All 25 missed inside the window, and the page reported that as a fact
  about all 893,508. It checked **0.003%** of them.
* What stops it now: the sentence says what it actually did — how many matched,
  how many it could check, and how to see the rest. It can no longer speak for
  rows it never fetched. Checking by hand found 30 passing on one coin alone.

**DEV**

* `StrategiesPanel.tsx:1394` printed one unconditional sentence whenever
  `shown.length === 0 && chips.length > 0`. With a days window the panel caps
  the request at `DAYS_PAGE = 25` (`StrategiesPanel.tsx:489`, API refuses more
  than `api.py:766 DAYS_ROW_MAX = 50`), SQL orders by WHOLE-HISTORY profit, and
  `api.py:399 -> rows_index.window_floors` cuts every row missing the floor on
  the window's own `w_winrate`. Empty page, non-empty store, one sentence for
  both.
* Invariant broken: **a page may report only what it examined** — kit item G's
  *"filter where the data is, never after a window has been taken"*, in its
  label form. `total` (the pre-window SQL count) was already in the payload and
  on screen eight lines above; the empty-state sentence simply did not read it.
* Guard: `tests/test_empty_page_is_not_an_empty_store.py`, 8 tests. Restoring
  the old unconditional sentence turns 5 of them red.

**SAW** — the operator, `Sep 12, 2026`, three filter chips on screen:

> *"no stored strategy passes Past 30 days with Winrate 85% or better with TP
> at least as wide as SL — lower the floor to see what is close."*

then *"is this accurate?"*, then *"does my filter really shows 0 resullt?"*.

**TIMELINE**

1. The index holds **96,307,386** rows over **5,388** pairs, 4 pairs behind.
2. `winrate >= 85` matches **1,961,285** rows (111 s). Adding `tp >= sl`:
   **893,508** (42 s). Both floors run in SQL, on whole-history figures.
3. The panel, with a days window on, asks for **25** rows
   (`DAYS_PAGE = 25`) sorted by whole-history profit.
4. `window_floors` re-measures those 25 over the last 30 days and cuts every
   one whose **window** win rate is under 85. All 25 go.
5. The page prints *"no stored strategy passes …"* — 25 examined, 893,508
   spoken for, **0.003%**.
6. Re-measuring rows the page never asked for, stopping at the first coin with
   matches: **30 rows pass all three filters**, e.g. **0G 15m
   `cf_obretest_l1` TP 2.5% / SL 1.2% flat — 2 trades, 2 wins, 0 losses,
   100% win rate, +$4.79** over the window. There are 4,168 pairs with candles
   inside the last three days.

**ROOT CAUSE** — the empty-state sentence was written for one case (nothing
matched) and rendered in two (nothing matched; nothing SURVIVED a window
applied to a 25-row slice). It is the label half of kit item G: the rows
behaved exactly as designed, and the words around them claimed a search that
never happened.

**WHY IT WAS NOT CAUGHT** — 289 tests read this panel, including
`test_window_floors_apply_to_the_window.py` and `test_days_window.py`, and
every one of them asserts on the ROWS. None asserts on the sentence shown when
there are no rows. An empty state has no rows to check, so a suite built around
row correctness has no natural place to stand — the assertion has to be made
against the WORDS, deliberately. The count that falsifies the sentence
(`total`) was already rendered eight lines above it.

**COST** — no money. The operator was told their filter had no answers when it
had 893,508 candidates and at least 30 passing rows, and was being steered to
widen a filter that was working.

**FIX** — this commit. The empty state now branches: when a window actually cut
rows (`winHidden > 0`) it names the match count, the number really checked, and
how to see the rest; when the page ran past the last row it says so; otherwise
it keeps the original sentence. Found by the `harddev` loop, in order —
(1) a capped `total` printed as exact, (2) a page past the end blamed on the
window, (3) `min(askPage, total)` was an estimate where `winHidden` is the
exact number re-measured, (4) the MONTHS window has the same shape and the
first fix covered only days, (5) `restateMax` — an identifier I invented, which
would have thrown at render, (6) coin/tf/signal/profitable are already chips
and were being appended AGAIN, so with the profit filter on it read "passes
Made money … and profit above zero".

**GUARD** — `tests/test_empty_page_is_not_an_empty_store.py`:
`test_the_empty_message_never_speaks_for_rows_it_did_not_check`,
`test_it_names_how_many_matched_and_how_many_were_actually_checked`,
`test_the_window_is_only_blamed_when_it_actually_cut_something`,
`test_a_capped_total_is_never_printed_as_exact`,
`test_the_MONTHS_window_gets_the_same_answer_as_days`,
`test_the_filter_set_is_named_once`,
`test_the_caps_that_make_this_possible_are_still_what_the_message_says` (pins
`DAYS_ROW_MAX`, `RESTATE_MAX` and `DAYS_PAGE` so the arithmetic cannot drift
from the words), and `test_the_window_really_can_hide_passing_rows` — whose
first draft asserted on `winrate` and passed both rows through, because
`window_floors` judges only `restated` rows and reads `w_winrate`. Rule 23 in
miniature, inside the test for a labelling bug.

---

## RCA-2026-09-12-F — UPDATE ALL BACKTESTS sat on "starting" for 9 minutes 39 seconds with an empty log, reading 1.77 GB to learn 1,054 names

**CEO**

* You pressed UPDATE ALL BACKTESTS at 1:55am. The screen said "starting" and
  nothing else until 2:05am — nearly ten minutes where the only honest
  reading was "this has hung". It had not; it was busy, and it finished and
  dispatched correctly.
* Why, two things at once. It was opening all 5,235 candle files — 1.77 GB
  off the slow drive — just to collect the 1,054 coin names, which are
  already written on the files' own labels. And its diary was being held in
  memory instead of written down, so there was nothing to read while it ran.
* What stops it now: it reads the labels from a list it keeps up to date, so
  the same step takes under a second when nothing has changed, and it writes
  a line saying "reading the candle store" before it starts and how long it
  took when it ends. All four long-running buttons now write their diary as
  they go.

**DEV**

* Three call sites, one symptom. `db_jobs.py:1722` (`stored_symbols`) called
  `market_sweep.candle_coverage`, which JSON-parses every file in `CANDLES`
  to build `first`/`last`/`bars` strings of which this caller keeps one —
  `symbol`, derivable from `f.stem` (py-spy on the live pid: `read_text ->
  candle_coverage -> stored_symbols -> _run_btupdate`). `db_jobs.py:616`
  (`start`) launched the detached child with no `env`, so Python
  block-buffered its stdout into `db_{kind}.log`. And `_run_btupdate`
  published nothing before the call, leaving `start()`'s `"now": "starting"`
  on screen for the whole phase.
* Invariants broken, all three already rules here: **a long phase publishes
  while it runs**; **a long-running process writes a log** (RCA-2026-09-10-C,
  which fixed exactly this for `rows_index.spawn_indexer` and nothing else);
  and **read the cheap thing** — two other callers already carry a comment
  forbidding `candle_coverage` for this purpose.
* Guard: `tests/test_update_says_what_it_is_doing.py` — 12 tests, AST-based
  so the module's own docstrings quoting the banned call cannot satisfy them.

**SAW** — *"can you click update backtest to update my backtests then look
for errors if there are errors report it to me"*, and then nine minutes of a
screen that read `{"running":true,"done":0,"total":0,"now":"starting"}`.

**TIMELINE**

1. `Sep 12, 2026 1:55:31am` — `POST /api/jobs/btupdate/start` returned pid
   16368. Progress: `now: "starting"`, `done 0`, `total 0`.
2. `1:57am` through `2:05am` — polled every 20 s. The payload never changed.
   `db_btupdate.log` still had mtime `Sep 06, 2026 9:42am` and held one line,
   from six days earlier.
3. `2:00am` — py-spy on the worker (pid 6492, 9.2 s CPU, 46 MB RSS) put it in
   `pathlib.read_text` under `candle_coverage`. Not stalled: disk-bound.
4. Measured the same store from a second process: **5,235 candle files,
   1.77 GB**, listed by name in **13.0 s**.
5. `2:05:15am` — the job finished the phase and dispatched. All five log
   lines appeared **at once**, and the answer was **1,054 contracts**. Total
   silent time **9 minutes 39 seconds**, of a 9m44s job.
6. AFTER the fix, same store, same answer of **1,054 contracts**:
   **86.8 s cold** (the index cache stale, and a collect rewriting files
   underneath it) and **0.4 s warm**, against **579 s**.

**ROOT CAUSE** — the symbol list was built by parsing every candle file, and
the phase that did it published nothing and logged nothing.

**WHY IT WAS NOT CAUGHT** — `candle_coverage`'s cost was already known: two
callers carry comments saying never to use it ("opens every candle file and
takes minutes on a 5,147-pair store"), and `backtest_logs.py` repeats the
warning in its module docstring. The knowledge existed as PROSE next to three
call sites and as a rule in nobody's test. No guard asked "which functions
call this", so the third caller was written and shipped. **A warning in a
comment is a note; only a test is a rule.** The new guard reads the AST of
`stored_symbols` and refuses the call by name — deliberately not a string
search, because this repo has now twice had a grep-based guard satisfied by
the docstring that quotes the broken form (RCA-2026-09-10-B, and
RCA-2026-09-12-E the same night).

Separately: 289 index tests exist about what the index CONTAINS and how fast
it fills, and the buffered-log fault was found and fixed for the indexer on
Sep 10 — `test_the_log_is_not_buffered_away` has guarded `spawn_indexer`
since. It was never generalised to `db_jobs.start`, which launches all four
of the operator's long-running buttons. A fix applied to one caller of a
pattern is half a fix; the CONCEPT has to be grepped (CLAUDE.md, 2026-09-05).

**COST** — no money, no lost work: the job was correct and the run it
dispatched (34631292767, 1,054 coins, 15m/30m/1h/4h) is measuring normally.
The cost was ten minutes of a screen that could not be distinguished from a
hang, on a button whose whole history is jobs that looked fine and were not —
and the real risk that the next reader kills a healthy job.

**FIX** — this commit. `stored_symbols` reads `market_sweep.candle_index()`
(incremental, cached by mtime+size) and keeps a pair only when it has bars;
`_run_btupdate` publishes `"reading the candle store"` before the call and
logs the duration after it; `db_jobs.start` passes
`PYTHONUNBUFFERED=1` to every detached job.

**GUARD** — `tests/test_update_says_what_it_is_doing.py`. Verified RED on the
pre-fix file — 4 of its 12 tests fail there — and green after.

---

## RCA-2026-09-12-E — the Storage screen printed the banned date format for weeks, and the guard against it wanted a `%Y` that was never there

**CEO**

* Your Candles/Storage table printed dates like Sep 3, 2026 3:07PM. Your
  rule, asked for three times, is Sep 03, 2026 3:07pm — the day must be two
  digits and the am/pm must be small letters. Two of the six parts were wrong
  on every row of that table.
* Why: that one screen built the date itself, letter by letter, instead of
  calling the single date function the whole project is supposed to use.
* What stops it now: that screen calls the shared function, so it cannot
  drift again — and the automatic check that was supposed to catch this has
  been widened and proved to go red on the old file before the fix was kept.

**DEV**

* `market_sweep.py:1456` (`candle_coverage`) produced `first`/`last` with
  `f"{_d0:%b} {_d0.day}, {_d0.year}"` and `f"{_h1}:{_d1:%M}{_d1:%p}"`.
  `.day` is unpadded and `%p` is uppercase with no lowercase strftime code to
  swap in. `/api/storage/coverage` (`api.py:876`) serves those strings
  verbatim and `StoragePanel.tsx:259-260` renders them raw, so the defect
  reached the screen unmodified.
* Invariant broken: **there are exactly two date implementations and you must
  call one of them** (CLAUDE.md, Date format). The block even carried a
  comment quoting the WRONG form — `"Operator's one date format
  (2026-08-21): Aug 26, 2026 4:00PM"` — so the rule had been copied down
  incorrectly and then obeyed.
* Guard: `tests/test_webapp.py::test_no_module_formats_a_timestamp_by_hand`,
  widened to also reject a `%b` beside a hand-built `.day}`/`.year}` and any
  production of `%p`.

**SAW** — not reported by the operator; found on Sep 12, 2026 while reading
`candle_coverage` for an unrelated reason (it is what makes UPDATE ALL
BACKTESTS sit silent for its first ten minutes).

**TIMELINE**

1. `Sep 12, 2026 2:02am` — running the exact expression from
   `candle_coverage` against `Sep 03, 2026 3:07pm` printed
   **`Sep 3, 2026 3:07PM`**, beside `positions_view.fmt_when`'s
   **`Sep 03, 2026 3:07pm`**. Day unpadded, meridiem uppercase.
2. The same expression on a two-digit day, `Sep 12, 2026 1:55am`, printed
   **`Sep 12, 2026 1:55AM`** — so the day fault hides on 21 days of each
   month and the `AM`/`PM` fault is on every row, always.
3. `Sep 12, 2026 2:31am` — with the fix stashed, the widened guard named
   **three** offending lines (`market_sweep.py:1469`, `:1470`, `:1471`); with
   the fix restored it passed.

**ROOT CAUSE** — a third hand-rolled copy of the date rule, written with
datetime ATTRIBUTES (`.day`, `.year`) rather than strftime codes, which is
both wrong and invisible to the check that looks for codes.

**WHY IT WAS NOT CAUGHT** — `test_no_module_formats_a_timestamp_by_hand` asks
for `%b` AND `%Y` AND a clock code **on one line**. This code never writes
`%Y` at all — it writes `{_d0.year}` — and it splits the stamp across two
lines, so neither line could match. This is the third time in four days that a
MANDATORY rule was broken while its guard passed (`.toLocale` on Sep 09, the
`p.set("days"` count on Sep 09), and it is the same shape every time: **the
guard pinned one SPELLING of the mistake, not the mistake.** The widened
version now also rejects the attribute spelling and any `%p` at all, on the
principle that there is no lowercase strftime meridiem — producing one means
re-implementing the rule.

**COST** — no money and no wrong decision: the field is a coverage label, not
an input to anything. The cost is the rule itself. It has been asked for four
times, and a screen that disobeys it teaches the next reader that the format
is approximate.

**FIX** — this commit. `candle_coverage` calls
`positions_view.fmt_when(ts/1000)` for both `first` and `last`.

**GUARD** — `tests/test_webapp.py::test_no_module_formats_a_timestamp_by_hand`,
widened in the same commit and **verified red on the pre-fix file** (three
named offenders) and green after.

---

## RCA-2026-09-12-D — ten new cascade strategies answered the "Classic" filter, and none of them could be found at all

**CEO**

* Ten new strategy rules (the cascade family) were measured across your
  whole market —
  **6.8 million rows** of results sitting on your G: drive. Searching for any
  of them in Stored strategies returned **nothing**, and even once found they
  would have appeared under the heading **"Classic"**, which means "the old
  signals from before confluence" — the opposite of what they are.
* Why, two separate things: the search index had not been refreshed since
  they were measured (**5,194 of 5,392 coins stale**), and the code decided
  which heading a rule belongs to by the first letters of its name, and the
  new family did not match, so it fell out of its own group.
* What stops it now: the grouping reads one shared list of name prefixes that
  both the database and the app use, and a test compares those two answers
  over every rule in the library, so they can never disagree again. The index
  refresh is the remaining step and is being run once the measuring in flight
  finishes.

**DEV**

* `rows_index.py:1868` defined the group as a single half-open range on the
  signal name, from `cf_` up to the byte after `_`, with `in_group` spelling
  `startswith("cf_")` separately. `signals_conf.py:755` registers
  `build_cascades(...)` into the SAME `CONF_SIGNALS` dict, and `'x' > 'f'`,
  so all ten `cx_*` rules matched `CLASSIC_TERMS`.
* Invariant broken: **a label must be derived from the data it describes**
  (`label-must-match-data`). "Classic" is defined as *not* the confluence
  library; it was implemented as *not this one prefix*. The two stopped being
  the same thing the moment a second family was registered.
* Guard: `tests/test_strategy_group_filter.py` —
  `test_the_two_groups_partition_the_signal_library` now asserts
  `set(preset) == set(CONF_SIGNALS)` through `ri.in_group` rather than
  re-spelling a prefix, and `test_the_sql_and_the_python_agree_on_every_signal`
  runs `GROUP_TERMS` against a real SQLite table of the whole registry and
  diffs it with `in_group`.

**SAW** — *"did you add it in backtest stored strategies"*, then *"/goal i
want it in my backtest store, whenever i ask you to create a new strategy i
want you to store it in my backtest strategies"*.

**TIMELINE**

1. `Sep 11, 2026` — ten cascade rules were written, registered in
   `backtest_report.SIGNALS` (the grid went **120 -> 130** signals,
   `CONF_SIGNALS` **45 -> 55**) and swept over 1,047 coins on four
   timeframes.
2. The Stored-strategies dropdown listed all ten. That list is built from the
   CODE registry, so the feature looked finished.
3. `Sep 12, 2026 2:20am` — measured on the operator's store: 22 of 25
   randomly sampled pair files hold cascade rows; **33,822 of 503,840**
   sampled rows are `cx_*` (6.7%).
4. Same minute, through the real API: `/api/strategies?signal=cx_veto` ->
   **0 rows**; `cx_maj3` -> **0 rows**; `cx_any2` -> **0 rows**.
5. `rows_index.status()`: `rows=96,307,386`, `pairs_indexed=5,388`,
   `behind=`**4**, `stale=`**5,194**. The REINDEX button prints `behind`, so
   it would have offered a 4-pair job for a 5,194-pair walk — the same
   6.5x under-count as RCA-2026-09-10-C.
6. Independently of the index: with 130 signals in the registry,
   `in_group(s, "classic")` returned **True** for all ten `cx_*` names, so
   the Classic filter (85 signals by its own count) was answering with
   cascade rules and Preset Confluence was short by ten.
7. The store carries **no** `rows_cf_*` partial index yet, so widening the
   predicate cost nothing here — but the DDL is
   `CREATE INDEX IF NOT EXISTS`, which on a machine that DID have one would
   have silently kept the old `cf_`-only index and served it to the new
   two-range query. The indexes are renamed `rows_conf_*` for that reason and
   the old names are dropped by `ensure()`.

**ROOT CAUSE** — the group was keyed on ONE name prefix while its meaning was
"everything the confluence library registers". Adding a second family to that
library changed the data and not the rule.

**WHY IT WAS NOT CAUGHT** — the guard that should have caught it,
`test_the_two_groups_partition_the_signal_library`, asserted
`len(preset) == 45 == len(CONF_SIGNALS)` — and it DID go red. But it went red
as a *count* (`45 != 55`), which reads exactly like a stale number after a
feature lands, and it sat on `main` beside six other red tests from three
unrelated causes (a hardcoded 120, a superseded window expression, a stake
assertion the flat-only rule had retired, and one guard the test sandbox
makes structurally impossible to pass). **A count is not a location**: nothing
in that failure said "the new rules are in the wrong group", so it was read as
a number to bump. Every count in those tests is now derived from the registry,
and the partition is asserted as a SET through the function that decides it.
The impossible guard — `ri.LOGFILE.parent.name == ".tradingagents"`, checked
at runtime while conftest deliberately redirects it into `tmp_path` — is fixed
to read the module's declared default, because a permanently-red test is a
place other failures hide.

**COST** — no money. The cost was the whole feature: 6,845,648 measured rows
the operator could not reach, and a heading that would have told them ten
confluence rules were not confluence rules.

**FIX** — this commit. `rows_index.PRESET_PREFIXES = ("cf_", "cx_")` is the
one definition; `PRESET_TERMS`/`CLASSIC_TERMS` are built from it as a union of
ranges (still ranges, so a partial index can still be matched), `in_group`
reads the same tuple, and `GROUP_INDEXES` is renamed `rows_conf_*` with
`ensure()` dropping the retired `rows_cf_*` names. Getting the ROWS visible is
the separate, remaining step: a reindex of the stale pairs, run once the
collect of run 34612655037 and the sweep 34631292767 are finished — indexing
a moving target was measured climbing 5,179 -> 5,194 during the check itself.

**GUARD** — `tests/test_strategy_group_filter.py` (18 tests), in particular
`test_the_sql_and_the_python_agree_on_every_signal`, which walks the real
`br.SIGNALS` through both implementations; plus the two `cx_` rows added to
`test_the_where_clause_selects_the_group`, which are the only ones that fail
when the second range is missing (the `cf_` rows pass either way, because the
assertion is a substring check).

---

## RCA-2026-09-12-B — the runner's pid was reused by NVIDIA Overlay, so START would have done nothing and STOP would have killed it

**CEO**

* You said "go start" and the Trade tab would have told you the runner was
  already running — it was not. The number this project had written down for
  "my runner" had, after the Windows Update restart, been handed by Windows
  to a graphics process. Pressing stop would have shut that down instead.
* Why: the project identified its own runner by a process number, and process
  numbers get reused after a reboot.
* What stops it now: the runner already had a real badge nobody was checking —
  a file lock it holds for as long as it lives. The number alone is no longer
  accepted as proof. Caught before pressing start, so nothing was lost.

**DEV**

* `auto_trader.py:4489` `runner_pid()` returned the recorded pid whenever
  `portable.pid_alive(pid)` was true. After the `Sep 11, 2026 9:35pm` reboot
  the file held **9364**, which `Get-Process` resolved to **NVIDIA Overlay**.
  `start_runner():4499` short-circuits on `existing` and returns it without
  spawning; `stop_runner():4524` calls `os.kill(pid, SIGTERM)` on it.
* Invariant broken: **liveness is not identity.** `main():4606` already takes
  an exclusive lock on `auto_trade.lock` and holds it for the life of the
  process, and nothing else in the project opens that file — so lock-held is
  the identity, and `runner_pid()` now requires BOTH it and a live pid.
  Verified across processes and, because per-handle lock semantics are easy
  to assume wrongly, measured inside one process too.
* Guard: `tests/test_a_recycled_pid_is_not_the_runner.py` — 10 tests, with a
  real child process holding a real lock. Red on the old behaviour, 5 of 10.

**SAW** — nothing yet; the operator typed *"go start"* and the pre-flight check
of `press-and-watch` read the pid file before pressing. **NEVER HAPPENED YET**
as a symptom, but the condition was live on the machine at the time of writing.

**TIMELINE**

1. `Sep 09, 2026 6:23am` — the runner started and wrote **9364** into
   `auto_trade.pid`.
2. `Sep 11, 2026 9:35:46pm` — TrustedInstaller restarted the PC for
   KB5124008 and KB5126052 (System event **1074**). The runner died. Its pid
   file, lock file and WANT flag all survived, all still dated **Sep 9**.
3. `Sep 11, 2026 9:36:08pm` — the machine came back up and reissued pids from
   the start.
4. `Sep 12, 2026` — `Get-Process -Id 9364` answers **NVIDIA Overlay**.
   `portable.pid_alive(9364)` is therefore **True**.
5. What would have happened on the next press: `start_runner()` returns
   **9364** and spawns **nothing** — the tab says started, the runner stays
   down, and the operator finds out hours later from an empty scan log. A
   later `stop_runner()` sends **SIGTERM to NVIDIA Overlay**.
6. After the fix, on the same machine with the same stale files:
   `run_lock_held()` is **False**, `runner_pid()` is **None**, and
   `start_runner()` spawns for real.

**ROOT CAUSE** — `return pid if portable.pid_alive(pid) else None`. A pid that
exists is not a pid that is yours. The project had an unambiguous identity
available (the run lock) and was not consulting it.

**WHY IT WAS NOT CAUGHT** — every test of this path invented a pid and then
told `pid_alive` to agree with it (`test_supervisor.py` monkeypatches
`pid_alive` to `int(pid) == 4242`, after a 2026-09-04 fix for the same test
being decided by whether 4242 happened to exist). A fake that answers "yes,
that is a live process" is asserting the very premise under test, so no test
here could distinguish OUR live process from ANY live process. The lock — the
one thing that tells them apart — appeared in no test of `runner_pid` at all.
**When a test has to fake the fact the code is checking, the code is checking
the wrong fact.** The new guard holds a REAL lock in a REAL child process, and
`test_supervisor` now makes its fake runner hold one too.

**COST** — none. Found by the `press-and-watch` PREDICT step before the button
was pressed. The exposure was a runner that would have silently failed to
start, with two real positions (NGAS, PDDSTOCK) open at MEXC — protected by
their resting brackets, but unattended for as long as the lie held.

**FIX** — this commit. `auto_trader.run_lock_held()`, required by
`runner_pid()` alongside `pid_alive`.

**GUARD** — `tests/test_a_recycled_pid_is_not_the_runner.py`, verified red on
the pre-fix behaviour (5 of 10, including both the silent-start and the
kill-a-stranger cases).

---

## RCA-2026-09-12-A — the demo book booked wins on price that printed before the trade existed

**CEO**

* Your demo results were flattering themselves. A demo trade could "win"
  seconds after opening by looking at prices from up to four hours earlier —
  prices it was never in the market for. On CHYMSTOCK the demo showed a 100%
  win rate on a strategy whose one real trade lost money.
* Why: when a trade opens, the runner wrote down the *candle's* start time
  instead of the clock time the order went out, and the demo book used that
  to decide "has my target been hit yet".
* What stops it now: the demo can only look at price from the moment the
  order existed, which is the same rule the backtest uses. The 8 affected
  trades have been re-scored from the real candles, so the demo win rate now
  reads 56% instead of 64% and matches the live book trade for trade. Real
  money was never at risk — a live order rests at MEXC and can only fill
  forward.

**DEV**

* `auto_trader.py:3414` (`_process_slot`) filtered the barrier walk with
  `if t > pos["entry_ts"]`, and `pos["entry_ts"]` is `last_ts` — the SIGNAL
  CANDLE's open (`auto_trader.py:4052`), not `opened_at`. The one-minute
  fallback at `auto_trader.py:3431` reused the same floor at 60-second
  resolution, so it replayed `bar_seconds` of pre-entry history: 3,600 s on a
  1h strategy, 14,400 s on 4h.
* Invariant broken: **a fill may only be decided by price the order was
  exposed to.** Two clocks were being mixed — bar time and wall-clock time —
  and the field name said neither. The rule is now one helper,
  `_bars_exposed_to`: a bar counts when `t + bar_seconds > opened_at`, which
  is the backtest's own convention (`fast_grid.walk` enters at `opens[i+1]`
  and tests bar `i+1`), so the demo book and the grid answer the same
  question.
* Guard: `tests/test_demo_cannot_fill_before_it_opened.py` — 8 tests, driving
  `process_symbol`, with an AST check that every `_dry_fill` call takes its
  bars from `_bars_exposed_to` rather than a comprehension built on the spot.

**SAW** — *"how come trade id 7WZMH7EN lose in live and in demo its still 100%
winrate?"*, then *"so you mean the demo trade is not correct?"*

**TIMELINE**

1. `Sep 10, 2026 10:00pm` — the 9:00pm hourly bar closed and `bb20_1h_sl25tp25`
   fired on CHYMSTOCK. Both books opened LONG at **33.02**, target **33.8455**,
   stop **32.1945**. Live `7WZMH7EN` at 10:00:08pm, demo `ZXS6ETX5` three
   seconds later. Both stored `entry_ts` = **1789045200** (9:00pm) while
   `opened_at` was **1789048811** — a gap of **3,611 seconds**.
2. `Sep 10, 2026 10:01pm` — the demo booked **TP +0.41** after **69 seconds**.
   CHYMSTOCK's high that minute was **33.02**; the next four minutes printed
   32.85, 32.80, 32.79.
3. The bars that filled it were **9:01pm-9:29pm**, 29 one-minute bars with
   highs of **33.88 to 34.02** — 31 to 59 minutes BEFORE the order existed.
4. `Sep 11, 2026 9:00am` — the live twin's barrier was really crossed and the
   runner closed it at market: **SL, exit 32.19, -0.53**.
5. Measured across the whole demo book: **8 of 39** closed demo trades were
   decided by pre-entry price. Worst case was `macddiv_4h`, which replayed
   **240 minutes**: three STBL trades booked **+2.76, +2.76, +2.26** at
   `Sep 09, 2026 8:01pm`, 67 seconds after opening, when the real outcome was
   the **stop at 10:04pm**.
6. It cut both ways — `VYSZ6TLS` (KITE 1h squeeze, `Sep 07, 2026 5:01pm`)
   booked **SL -3.19** off the 4:00pm-5:00pm hour when the real outcome was
   **TP at Sep 08, 2026 6:40am**. That is the same row the operator queried in
   RCA-2026-09-09-B.
7. AFTER the re-score, from MEXC's own one-minute candles walked forward from
   `opened_at`: demo overall **25W/14L (64%) -> 22W/17L (56%)**; invented PnL
   **+12.81** removed; `bb20_1h_sl25tp25` demo **100% (2/2) -> 50% (1W/1L)**
   against live **0% (0W/1L)**; `ZXS6ETX5` now reads **SL -0.59** beside its
   live twin's **SL -0.53**.

**ROOT CAUSE** — `if t > pos["entry_ts"]` used the signal candle's open as the
floor of a barrier walk. `entry_ts` is bar time; exposure starts at
`opened_at`, wall-clock time. A one-minute walk against a one-hour floor
replays the hour before the trade.

**WHY IT WAS NOT CAUGHT** — two tests covered this exact code path and both
were structurally incapable of seeing it, for the same reason.
`test_paper_bracket_catches_an_intrabar_wick` built its wick bar ending at
`now` while `process_symbol` stamped `opened_at` = `now`, so it *asserted* a
fill on a bar that closed as the order was placed.
`test_book_is_never_flushed_while_the_exchange_says_open` put its candles
**400 bars (66 days)** before the position's own `opened_at`, via the shared
`_bars()` helper and `_T0`. In both, the fixture's candle clock and the
position's wall clock were disconnected — which is precisely the confusion the
bug is made of, so a floor expressed in the wrong clock looked identical to a
correct one. **A fixture whose candles and whose position disagree about what
time it is cannot test anything that depends on time.** Both fixtures are now
pinned to the clock a runner actually sees, and each carries a comment saying
why.

**COST** — no money: the live book never used this path, its brackets rest at
MEXC, and the two positions open during the incident were untouched. The cost
was trust and, nearly, a decision — the demo book overstated itself by
**+12.81 USDT** and **8 percentage points** of win rate, and the operator
judges which strategies to deploy by exactly that number.

**FIX** — this commit. `_order_live_from` and `_bars_exposed_to` in
`tradingagents/auto_trader.py`, used by both walks; the 8 ledger exit rows
re-scored in place, each keeping its original values under `was` and marked
`corrected: RCA-2026-09-12-A`, with the untouched ledger kept as
`auto_trade_ledger.jsonl.bak-rca20260912a-1789150338`.

**GUARD** — `tests/test_demo_cannot_fill_before_it_opened.py`. Verified RED on
the pre-fix file (7 of its 8 tests fail there) and green after. The AST check
means a third barrier walk cannot reintroduce the floor by writing a new
comprehension.

---

## RCA-2026-09-11-B — a newer run REPLACED each pair's rows, so 1,261,358 measured rows were deleted and 100 pairs emptied

**CEO**

* You asked whether backtests from previous days were lost. They were: **1,261,358 measured
  results across 267 coins**, and **100 of those coins were wiped completely** — GPNSTOCK
  15m went from 18,880 results to zero, SUPRA 15m from 21,780 to zero.
* Nothing was wrong with the lost results. A later run measured FEWER results for
  those coins, because the backtest skips targets that trading costs eat half of — and
  those coins were expensive at the moment it ran. The save then wrote the smaller
  set OVER the bigger one, because it judged "newer" by the clock and never looked at
  what it was about to overwrite.
* An update can now only ADD to a coin's results or replace a result it re-measured.
  It can never leave a coin with less than it found. And all 1.26 million rows are
  still in the backup copy from 1:09pm, so they are recoverable.

**DEV**

* `cloud_sweep.land_rows` called `msw.save_pair_rows(coin, tf, rows)` — a REPLACE —
  gated only by `is_fresher()`, which compares `__last_ms__` watermarks: when a run
  ENDED, nothing about what it holds. So a shard that returned 0 rows with a newer
  watermark emptied the pair. Measured across the operator's own index copies
  (`rows.before-rebuild.db` at `Sep 10 1:09pm` versus now): 4,214 pairs gained
  39,370,830 rows, 267 lost 1,261,358, 100 emptied. The cause of the smaller runs is
  RCA-2026-09-11-A's gate: `UTILITY-1h` records `rt=3.5866%`, so of the 1h grid's
  eleven targets only 8.0% cleared `rt/0.5` — and the surviving TP set matches
  `rt / GATE_BLOCK` on every affected pair.
* Broken invariant: **newer is not emptier.** A write that can shrink what it is
  updating is a delete, whatever it is called — and freshness by timestamp cannot
  authorise it.
* Guard: `tests/test_a_newer_run_can_never_empty_a_pair.py` (6) —
  `test_a_newer_but_emptier_run_keeps_every_stored_row`,
  `test_a_newer_smaller_run_keeps_what_it_did_not_measure` (the re-measured
  combination wins, the untouched ones stay),
  `test_the_shrink_is_impossible_by_construction` (AST-checks that
  `save_pair_rows` is not called at all, then drives three landings and asserts the
  file never shrinks), `test_a_FIRST_measurement_may_still_write_nothing` (the 1d
  incident's empty file stays legal), `test_the_watermark_still_decides_whether_to_land_at_all`,
  `test_it_is_the_ONE_place_the_rule_lives`.

**SAW** — the operator: *"so you mean there are backtest from my previous days that
was lost?"*, then *"why were they deleted"*, then *"so you mean whenver i update
backtest they get deelted?"*.

**TIMELINE**

1. `Sep 10, 2026 ~1:09pm` — the index holds 4,612 pairs, including GPNSTOCK-15m with
   **18,880** rows and GPNSTOCK-30m with **20,880**.
2. `11:33am-1:17pm` — the collect lands the fleet's results for the expensive coins.
   Each pair's file is REPLACED by what that run measured; for GPNSTOCK that was
   nothing, because every barrier failed the cost gate at 1am New York.
3. `Sep 11 12:40am` — measured by diffing the two index copies: 267 pairs lost rows,
   100 emptied, 1,261,358 rows gone. 176 of the losers are tokenized stocks, **91 are
   crypto** — thin books (SUPRA, ASP, AURASOL, UTILITY), not market hours.
4. `12:55am` — `merge_pair_rows` found to have existed all along, used by the LOCAL
   sweep, with a docstring warning that `save_pair_rows` "would delete every
   combination not yet reached". The cloud path used the destructive one.

**ROOT CAUSE** — two writers for one rule. `run_pair` merges by combination;
`land_rows` replaced. Whichever path last touched a pair decided whether its earlier
measurements survived.

**WHY IT WAS NOT CAUGHT** — every test of `land_rows` asserts what it writes for a
pair the store has never seen, so REPLACE and MERGE are indistinguishable in all of
them. Not one seeds a pair with rows first. The loss also has no symptom at the
moment it happens: the watermark advances, the collect reports "kept", and the pair
simply has fewer rows than yesterday — which reads as "not measured yet".

**COST** — 1,261,358 measured rows, of which the operator noticed the ones under
their own deployed strategies. No money, and recoverable: `rows.before-rebuild.db`
still holds every one of them, which is the copy previously described in this file
as "dead files ... read by nothing and could be deleted".

**FIX** — this commit. `land_rows` calls `merge_pair_rows`, so what a run measured
wins and what it did not measure is kept; an empty landing on a pair that already has
rows now changes nothing, while a first measurement may still store the empty file the
1d incident requires. `append` becomes redundant (the merge dedupes by combination)
and is left accepted so callers need not change.

**GUARD** — `tests/test_a_newer_run_can_never_empty_a_pair.py`, six tests named in
the DEV block. Still open: **the 1,261,358 rows are not yet restored** — the fix stops
the next loss, it does not undo this one; and `market_sweep.run_pair(merge=False)`
remains the DEFAULT, so a local caller that forgets the argument still replaces
(RCA-2026-09-10-A bought that lesson for the row UPDATE button and the default stayed).

---

## RCA-2026-09-11-A — 28 of the operator's 35 DEPLOYED strategies had no backtest row, because a spread read at 1am judged them unwinnable

**CEO**

* You searched one of your own live strategies, #PNK3G9KZ, and the backtest
  had nothing for it. You said this means strategies are being deleted rather
  than updated. Measured: **28 of your 35 deployed strategies had no row**, and
  two coins' result files (GPNSTOCK 15m and 30m) were completely **empty**.
* Nothing was deleted. The measurement REFUSES to test a take-profit that the
  trading costs eat more than half of — which is right, a target smaller than
  its cost cannot win. But it reads that cost from the order book **at the
  moment it runs**, and your tokenized stocks were measured between
  **11:33am and 1:17pm** — which is the middle of the night in New York, when
  those markets are shut and their spreads blow out five to ten times.
* Same coin, same strategy: at 1am the cost read **1.287%** against your 1.2%
  target and was thrown away as impossible; with the market open it reads
  **0.263%**, which is 22% of the target and perfectly fine. The grid's
  contents depended on the clock.
* Fixed: a strategy you have DEPLOYED is now always measured, whatever the
  spread says, and every skipped combination is counted instead of silently
  vanishing.

**DEV**

* `market_sweep.run_pair` → `if rt is not None and rt / tp >= GATE_BLOCK:
  continue` (`GATE_BLOCK = 0.50`), where `rt = br.round_trip_cost(fee,
  fx.book_cost(symbol, base_margin * at.LEVERAGE))` — a LIVE book read, once,
  at sweep time. Recorded in the rows themselves: `PSXSTOCK rt=1.287%`,
  `CHYMSTOCK rt=2.4347%`, `DVNSTOCK rt=1.007%`, `STBL rt=0.1087%`. The TP
  values each pair kept are exactly those above `rt / 0.5`:
  CHYMSTOCK kept 5/6/8% (floor 4.87%), DVNSTOCK kept 2.5/3% (floor 2.01%),
  STBL kept all eleven (floor 0.22%). `pairs.rows_mtime` dates those files to
  `Sep 10, 2026 11:33am-1:17pm` (+08:00) = `11:33pm-1:17am` America/New_York.
  Re-measured live at `Sep 11 12:15am` (+08:00), US market open:
  `PSXSTOCK rt=0.263%`, `GPNSTOCK rt=0.296%`.
* Broken invariant: **a strategy the operator is RUNNING is always measured** —
  CLAUDE.md rule 21 screens the deployed row FIRST, and it cannot be screened
  if it was never measured. Second: **a measurement whose CONTENT depends on
  the wall clock has to say so** — an excluded combination must be counted
  (rule 20), not left as an absence.
* Guard: `tests/test_a_deployed_row_is_always_measured.py` (6) —
  `test_the_deployed_combination_is_never_skipped` walks the AST of the gate's
  own branch and requires the `not in deployed` term;
  `test_the_gate_still_skips_an_undeployed_combination` keeps rule 11 intact;
  `test_the_deployed_set_is_read_from_the_operators_own_settings` pins the
  PERCENT unit and the bare-coin form;
  `test_a_settings_file_that_cannot_be_read_exempts_nothing`;
  `test_a_strategy_with_no_spec_is_skipped_not_guessed`;
  `test_the_counters_reach_the_caller`.

**SAW** — the operator: *"why is #PNK3G9KZ not searchable it says no row
#PNK3G9KZ in the store"*, then *"so what is PNK3G9KZ in the deployed
strategies? this only means you are deleting existing strategies and you are
not updating them"*, then *"im getting tired of these errors"*.

**TIMELINE**

1. `Sep 10, 2026 11:33am-1:17pm` (+08:00) — the fleet's results for the
   tokenized stocks are written. US market closed; spreads 5-10x normal.
2. `~10:00pm` — the operator searches `#PNK3G9KZ`. No row.
3. `10:02pm` — measured: the id is well-formed, `rows_id` exists, and a direct
   `WHERE id = ?` returns 0 rows. The lookup is healthy.
4. `11:20pm` — 152,315,460 grid combinations hashed against the id: no match.
   **That search was in the wrong UNIT** (fractions, while the store hashes
   percents), so its verdict was worthless — see step 6.
5. `11:52pm` — the operator says it is a DEPLOYED strategy. Hashing the 35
   deployed combinations finds it at once:
   **#PNK3G9KZ = PSXSTOCK 15m willr14 TP 1.2% SL 1.0% flat**, and **28 of 35
   deployed rows are missing**.
6. `11:58pm` — the unit bug proven: `row_code` over `#SW8Q96E6`'s own stored
   fields reproduces its id only with `sl=2.5` / `tp=2.5`, not `0.025`.
7. `Sep 11 12:05am` — the kept-TP pattern matches `rt / GATE_BLOCK` on every
   affected pair. Root cause established.
8. `12:15am` — the same books read live: 0.263% and 0.296%. The gate that
   refused these rows at 1am passes them at midday.
9. `12:20am` — `pairbt` re-measured PSXSTOCK 15m willr14: **160 rows**,
   including the operator's own. Reported "0 indexed — waiting on the index":
   the write lock is held by the on-demand index builds, so the row is measured
   and not yet filed.

**ROOT CAUSE** — `GATE_BLOCK` applied to a DEPLOYED combination, using a
single instant's order-book spread. The gate is correct in principle (rule 11)
and wrong in two ways here: it may not silently exclude a strategy the operator
is already running, and a cost sampled once at 1am is not the cost that
strategy trades at.

**WHY IT WAS NOT CAUGHT** — the gate has no test at all: it is four tokens
inside a triple-nested loop, and every test of `run_pair` asserts what lands in
the file, never what was skipped on the way. A skip left no trace anywhere —
no counter, no log line, no column — so its only symptom was a row that did not
exist, which reads as "not measured yet" instead of "refused". And the deployed
set was never cross-checked against the store: 28 missing rows for LIVE
strategies had been true for weeks with nothing looking.

**COST** — no money directly, but the exposure is the point: 28 live
strategies, 20 of them on GPNSTOCK, were running with **no backtest evidence at
all**, and `still-working` cannot screen a row that does not exist. Plus the
operator's time across three sessions asking why their own rows were missing,
and two wrong answers from me (the unit bug, and "the cost eats 107% of the
target" — true of a 1am spread, not of the market they trade in).

**FIX** — this commit. `market_sweep.deployed_combos()` reads the operator's
own settings (bare coin, PERCENT barriers) and `run_pair` never applies
`GATE_BLOCK` to a member of that set; skipped barriers are counted in `gated`.
The row keeps its real `rt`/`cost_of_tp`/`gate`, so a deployed strategy whose
cost genuinely eats its target now SHOWS that instead of vanishing.

**GUARD** — `tests/test_a_deployed_row_is_always_measured.py`:
`test_the_deployed_combination_is_never_skipped`,
`test_the_gate_still_skips_an_undeployed_combination`,
`test_the_deployed_set_is_read_from_the_operators_own_settings`,
`test_a_settings_file_that_cannot_be_read_exempts_nothing`,
`test_a_strategy_with_no_spec_is_skipped_not_guessed`,
`test_the_counters_reach_the_caller`.

**Still open, and named rather than left implied:**

* **26 of the 28 are still unmeasured.** Only PSXSTOCK 15m willr14 has been
  re-run. The other pairs — GPNSTOCK 15m/30m (20 rows, empty files),
  CHYMSTOCK 1h, DVNSTOCK 15m, PSXSTOCK 15m stoch14 — need the same treatment,
  and the fleet will do it on the next sweep now that the exemption exists.
* **`gated` is counted but not yet reported** to the screen or the progress
  file; it stops at the pair's own result dict.
* **The cost is still a single sample.** A median over a window, or a
  market-hours reading for stock tokens, is the real repair; the exemption
  only stops the operator's own strategies from disappearing.
* **Nothing alarms on "a deployed strategy has no row".** That check is three
  lines against the store and would have caught this weeks ago.

---

## RCA-2026-09-10-M — "no row #PNK3G9KZ in the store" told the operator a cause nobody had checked

**CEO**

* You searched an id, got told it was probably "re-measured with different
  barriers", and were told to check it against the table — advice that could
  never have worked for that id. You said you were tired of these errors, and
  the message was the error.
* Measured afterwards: **none** of the **152,315,460** strategy combinations
  your grid can currently produce make that id, on any of your 5,367
  coin+timeframes. So it did not come from this grid at all, and no amount of
  looking at the table would have found it.
* There is now a command that answers the question properly, and the message
  points at it: it says whether the id is a typo, a real strategy whose row is
  gone (naming the coin so you can re-measure it), or an id nothing here can
  produce — with the number of combinations it checked.

**DEV**

* `StrategiesPanel.tsx`'s id-miss branch printed *"The id is hashed from the
  combination, so it changes if the row was re-measured with different
  barriers — check it against the first column of the table"*. Two faults: the
  CAUSE was asserted without any check (for `PNK3G9KZ` it was false), and the
  ACTION was impossible. Established by measurement:
  `SELECT ... WHERE id = 'PNK3G9KZ'` → 0 rows with `rows_id` present, then
  152,315,460 grid candidates hashed → 0 matches in 166 s.
* Broken invariant: **an error message states what is KNOWN and names an
  action that can work.** A guessed cause in a fixed string is
  `label-must-match-data` with no data at all behind it.
* Guard: `tests/test_an_unknown_row_id_is_explained.py` (8) —
  `test_the_message_no_longer_asserts_a_cause_it_did_not_check` rejects the old
  sentence and requires the command; `test_a_combination_whose_row_is_GONE_is_still_named`;
  `test_an_id_no_grid_can_mint_says_exactly_that`;
  `test_a_typo_is_told_apart_from_a_miss` (and that a typo does not burn 166 s);
  `test_a_pasted_id_resolves_like_a_typed_one`;
  `test_it_is_never_called_from_a_request` (AST-walks `api` — 166 s on a polled
  route would be RCA-L again).

**SAW** — the operator, quoting their own screen: *"why is #PNK3G9KZ not
searchable it says no row #PNK3G9KZ in the store. The id is hashed from the
combination, so it changes if the row was re-measured with different barriers
— check it against the first column of the table or the artifact you copied it
from. / im getting tired of these errors"*.

**TIMELINE**

1. `Sep 10, 2026 ~10:00pm` — the find-by-id box returns nothing for
   `#PNK3G9KZ` and prints the guessed cause.
2. `10:02pm` — measured: `clean_row_id` returns `PNK3G9KZ` unchanged (8 chars,
   valid alphabet), `rows_id` EXISTS on the rebuilt store, and a direct
   `WHERE id = ?` finds **0 rows**. So the lookup is healthy and the row is
   genuinely absent.
3. `10:05pm` — two scans started (57 GB of pair files; the pre-rebuild index
   copies). Both saturated the disk and slowed every other command — the
   RCA-I mistake, made again by me — and were killed.
4. `10:20pm` — changed approach: the id is not opaque. `row_code` is
   `blake2s(coin|tf|signal|th|sl|tp|sizing, 5 bytes)` in base32, so the 8
   characters ARE that 40-bit number and the grid can be enumerated against it
   at 1.0M/s.
5. `10:28pm` — first pass: 148,773,240 candidates, 0 matches.
6. `10:41pm` — **the first test written against the new resolver went RED**: a
   real `mom6` row at threshold `0.000` was not found, because the search tried
   only each timeframe's threshold grid. That made the 10:28pm answer
   incomplete. Fixed, re-run: **152,315,460 candidates, 0 matches, 166 s.**

**ROOT CAUSE** — a fixed error string that named a cause. The row id genuinely
carries no back-pointer, so the panel could not know why a miss happened — and
instead of saying so, it guessed, in a sentence the operator then read as fact
and acted on.

**WHY IT WAS NOT CAUGHT** — nothing tests the TEXT of a refusal. Every guard on
this panel asserts that a filter cuts the right rows or that a label matches a
figure; a message with no number in it matched no rule. And the guessed cause
was plausible — ids DO change when barriers change — which is exactly why it
survived: a wrong explanation that sounds right is invisible until someone
measures it. The 10:41pm red test is the shape that catches this class: build
the tool that can check the claim, then test the tool against a real row.

**COST** — no money. The operator's time, twice: once following advice that
could not work, once telling me they were tired of it. And ~20 minutes of my
own disk contention (step 3) making the machine slower for them while I looked.

**FIX** — this commit. `rows_index.resolve_row_code(code)` returns
`well_formed` / `in_store` / `combination` / `searched`;
`python -m tradingagents.rows_index resolve <id>` prints the answer in the
operator's terms and exits 0 when it can name the row, 1 when it cannot, 2 on
misuse; it is documented as NEVER callable from a request. The panel's message
states only what is known and names that command.

**GUARD** — `tests/test_an_unknown_row_id_is_explained.py`:
`test_the_message_no_longer_asserts_a_cause_it_did_not_check`,
`test_a_combination_whose_row_is_GONE_is_still_named`,
`test_an_id_no_grid_can_mint_says_exactly_that`,
`test_a_typo_is_told_apart_from_a_miss`,
`test_a_pasted_id_resolves_like_a_typed_one`,
`test_a_row_that_IS_there_is_reported_as_there`,
`test_the_cli_answers_all_three_cases`,
`test_it_is_never_called_from_a_request`. Stated plainly: **the resolver only
knows the CURRENT grid.** An id from an older barrier set, a
renamed signal or a coin no longer in the store still resolves to "nothing here
mints it" — which is the true answer, but not a satisfying one. A retired-id
ledger (recording what an id WAS when a re-index removes it) is the real
repair, and it is not built.

---

## RCA-2026-09-10-L — the Stored-strategies route spent 267 seconds counting files, on a screen that polls it

**CEO**

* Right after the rebuild finished, your strategies screen took over four
  minutes to answer — while the search underneath it was answering in **one
  second**. Nothing was broken; the screen was waiting on the wrong thing.
* Every time the screen asked for rows, it also asked "how far behind is the
  index?", and answering that means checking all 5,367 coin files on disk. On
  the rebuilt 42 GB store that check takes **267 seconds**.
* That answer is now read in the background and reused for 20 seconds, so the
  table comes back at the speed of the search. The one place it is still
  measured live is the REINDEX button, because a button must print the real
  amount of work it is about to do.

**DEV**

* `api.strategies` called `ri.status()` inline; `status()` walks
  `stale_pairs()`, which `stat()`s every pair file AND its state file. Measured
  on the rebuilt store, same process, same minute:
  `ri.query(limit=500)` **1.11 s**, the same with the new freshness filter
  **2.25 s**, `stamp_measured(500)` **0.035 s**, `ri.status()` **267.55 s**.
  Two probes of `/api/strategies` timed out at 240 s while the store answered
  in under a second.
* Broken invariant: **a polled route must never do the slow thing inside the
  request** — already pattern 4 in this file, already given a tool
  (`slow_cache.BackgroundValue`, built that same morning for
  `/api/backtest/logs` at 82.3 s and `/api/cloud/status` at 216.3 s). This is
  the THIRD route, so the pattern is now: when a route gains a call, ask what
  that call costs COLD before shipping it.
* Guard: `tests/test_the_strategies_route_never_waits_on_status.py` (7) —
  `test_a_slow_status_does_not_slow_the_table` drives the real route with a
  5-second `status()` and requires an answer in under 2 s;
  `test_the_route_does_not_call_status_inline` and
  `test_the_storage_route_does_not_either` read the AST's CALLS, not the
  source text (the first version went red on the comment explaining the fix);
  `test_the_first_answer_says_UNKNOWN_not_zero`;
  `test_a_failing_status_is_reported_not_swallowed`;
  `test_the_reindex_button_still_reads_it_LIVE`.

**SAW** — the operator was not shown this one: it appeared while verifying the
new "last backtest" column minutes after the rebuild swapped in, and both
probes of the route timed out.

**TIMELINE**

1. `Sep 10, 2026 7:08pm` — the rebuild swaps in: 41.94 GB, 96,313,064 rows,
   5,367 pairs.
2. `7:12pm` — the app is started on that store. `/api/strategies?limit=3`
   answers in **43.5 s**; `/api/backtest/storage` in 17.7 s. Slow, and put
   down at the time to the on-demand index build sharing the disk.
3. `9:41pm` — verifying the new column: `/api/strategies?limit=3&coin=EPIK`
   **times out at 240 s**, then `/api/backtest/storage` times out at 60 s.
4. `9:43pm` — measured in-process, nothing else running: the query is
   **1.11 s** and `status()` is **267.55 s**. That is the whole gap.
5. Same hour — `index_status()` added, backed by `BackgroundValue` with a 20 s
   TTL, and both polled routes moved onto it.

**ROOT CAUSE** — `status()` is O(pairs) in `stat()` calls (5,367 pair files
plus 5,367 state files) and grew with the store, while the route that needs it
is polled every few seconds. The route's own work — the query — was never the
problem.

**WHY IT WAS NOT CAUGHT** — `status()` has ALWAYS been on this route; what
changed is the store. At 973 pairs it was milliseconds, and nothing anywhere
asserts what a route costs. Every test of `/api/strategies` runs against a
sandbox holding two or three pairs, where the difference between 1 ms and 267 s
does not exist — the same blindness that hid RCA-J (a resume check measured on
a 3-pair store) and RCA-K (a per-pair scan that is free on 3 pairs) earlier the
same day. The lesson those three share is now explicit: **a cost that only
appears at scale needs a test that FAKES the scale** — which is what driving
the real route with a deliberately slow dependency does.

**COST** — no money and no wrong numbers. Two and a half hours where the
operator's main screen would have been unusable had they opened it, on the
evening the rebuild finally made every coin searchable.

**FIX** — this commit. `api.index_status()` over
`slow_cache.BackgroundValue("index-status", ..., ttl=INDEX_STATUS_TTL=20.0)`,
used by `/api/strategies` and `/api/backtest/storage`; a pending read answers
with `None` counts and `reading: true` rather than zeros, and a failed read
reports `unreadable`. `POST /api/strategies/reindex` still calls `ri.status()`
directly, because the number on a button is the number of work it will do
(RCA-2026-09-10-C).

**GUARD** — `tests/test_the_strategies_route_never_waits_on_status.py`:
`test_a_slow_status_does_not_slow_the_table`,
`test_the_route_does_not_call_status_inline`,
`test_the_storage_route_does_not_either`,
`test_the_first_answer_says_UNKNOWN_not_zero`,
`test_a_failing_status_is_reported_not_swallowed`,
`test_the_reindex_button_still_reads_it_LIVE`,
`test_the_ttl_is_short_enough_to_be_useful`. Still open, and stated:
**`status()` itself is untouched** — it is still 267 s cold, so anything that
calls it synchronously will still be slow. Chunking `stale_pairs()` or caching
the pair-file mtimes is the real repair.

---

## RCA-2026-09-10-K — the rebuild deleted each pair before inserting it, with no index to delete by: 54 hours of full table scans

**CEO**

* The real reason the repair job kept getting slower, and it was not the other
  job I blamed in RCA-I. Every coin it filed made a search through the ENTIRE
  file first — and the file grows with every coin, so each one was slower than
  the last.
* Measured: **39.9 seconds of pointless searching per coin** at the point it
  had reached. For the 4,917 coins left that is **54 hours**, and rising.
* It no longer searches at all when it already knows the coin is not in the
  file. It proves that once, in 40 seconds, instead of 4,917 times.
* What I told you before — "two jobs fighting over one disk" — was a real
  effect but the wrong cause. Corrected in the entry below.

**DEV**

* `rows_index.index_pair` opens with `DELETE FROM rows WHERE pair = ?`.
  Delete-by-pair needs `rows_pair`, which CLAUDE.md has named since 2026-08-26
  as the one index a bulk fill may never drop — and `rebuild()` builds its
  file with NO indexes at all. Measured on the live 2.94 GB partial:
  `EXPLAIN QUERY PLAN SELECT count(*) FROM rows WHERE pair='NOPE-1h'` →
  **`SCAN rows`**, **39.9 s**, returning 0 rows. Per pair, against a table
  that grows per pair: O(n²). It is exactly why the run measured **40.15
  pairs/min in its first minute** (empty table, nothing to scan) and **0.25 by
  pair 448** (2.7 GB to scan).
* Broken invariant: **a delete needs the index it deletes by, or it is a full
  scan** — and a bulk load that writes each key exactly once must not delete
  at all. The delete-first exists for RE-indexing (RCA-2026-09-10-A was a lost
  delete); a fresh file is not re-indexing.
* Guard: `tests/test_rebuild_from_the_pair_files.py` (27) —
  `test_the_load_does_not_delete_per_pair` (pins `index_pair(f, con,
  fresh=True)` in the loop and carries the measured plan in its docstring),
  `test_fresh_skips_the_delete_and_the_default_still_deletes` (the default
  still replaces — every other caller re-indexes a pair that IS there),
  `test_a_resume_earns_fresh_with_one_scan_not_thousands` (inserts rows with
  no summary, exactly what a kill can leave, and proves the resume removes
  them), and `test_the_scan_is_named_in_the_source_so_it_is_not_re_added`.

**SAW** — the operator asked for status twice while the number did not move.
The honest answer had drifted from "ETA ~2h15m" to "about 5 hours" to
"thirteen days" without the work changing at all.

**TIMELINE**

1. `Sep 10, 2026 12:56pm` — rebuild starts on an EMPTY file: **40.15
   pairs/min**. Nothing to scan.
2. `1:36pm` — 447 pairs, 2.7 GB written, average down to **16.3**.
3. `1:46pm` — pair #448 takes **305 s**. Its file is `ARWRSTOCK-15m.json` at
   **0.0 MB**: the work was not the data.
4. `2:11pm` — resumed after the collect finished, on a disk with no
   competition. Still `WaitReason PageIn`, still 0 file I/O, **still stuck on
   one pair after 26 minutes**. That killed the contention theory: the collect
   was gone and nothing improved.
5. `2:55pm` — measured it directly on the partial file, in an idle process:
   `SCAN rows`, **39.9 s** for a pair that is not there. 4,917 x 39.9 s =
   **54.4 hours**.
6. Same hour — `fresh=True` for a caller that has proved the pair is absent,
   plus ONE reconciling scan on resume to earn that proof.

**ROOT CAUSE** — `index_pair`'s delete-first, running without `rows_pair`,
inside a loop over 5,367 pairs. Quadratic by construction.

**WHY IT WAS NOT CAUGHT** — every rebuild test runs on a **3-pair store**,
where a full scan of `rows` is three files' worth of rows and finishes in
microseconds. The tests proved the rebuild was CORRECT and could not see that
it was quadratic; the same blindness as RCA-J one hour earlier, which is why
both guards now carry the measured number in the test itself. And the
knowledge already existed in this repo, in prose: CLAUDE.md's own bulk-load
rule says `rows_pair` may not be dropped BECAUSE delete-by-pair needs it. The
rebuild dropped every index and then kept the delete — a rule known, written
down, and not applied to the new code path.

**COST** — no money, no data lost. About three hours of wall-clock across two
attempts, the operator's filing stuck at 86%, and two status answers from me
that named the wrong cause.

**FIX** — this commit. `index_pair(..., fresh=False)`; `rebuild()` passes
`fresh=True` and earns it: on a clean start the table is empty, and on a resume
`_resumable` runs `DELETE FROM rows WHERE pair NOT IN (SELECT pair FROM
pairs)` once (one scan, plan verified: `SCAN rows` + `USING INDEX
sqlite_autoindex_pairs_1 FOR IN-OPERATOR`) so any pair the loop will load is
provably absent. `fresh` is opt-in and every other caller still deletes first.

**MEASURED AFTER** — `Sep 10, 2026 3:2xpm`, resumed from the same 450 pairs on
the same file and the same disk:

| | before | after |
|---|---|---|
| pairs/min | **0.25** (one per 305 s) | **62.3** |
| pairs done | 450 of 5,367 | 613 of 5,367 in the first 157 s |
| rows | 8,385,108 | 11,337,264 |
| ETA for the rest | ~54 h and rising | **1.27 h** |

249x, and faster than the original run's best minute (40.15 on an EMPTY table),
because now there is no scan at all rather than a cheap one.

**A SECOND FAULT IN THIS FIX, found the same hour and fixed here too:** the
reconciling scan publishes nothing while it runs. It held 100% of a core for
minutes while `rows_rebuild.json` still carried the DEAD run's pid and
`pairs_done`, so a reader — me, twice — saw a rebuild that had "resumed" and
then done nothing, and reached for the process table again. That is exactly the
silence RCA-G is about, in a fix written to end it. `rebuild()` now publishes
`phase: "checking the partial file"` BEFORE the check, and the rate clock
starts after it, so a check that files no pairs cannot report a pairs/min it
never had.

**GUARD** — in `tests/test_rebuild_from_the_pair_files.py`:
`test_the_load_does_not_delete_per_pair`,
`test_fresh_skips_the_delete_and_the_default_still_deletes`,
`test_a_resume_earns_fresh_with_one_scan_not_thousands`,
`test_the_scan_is_named_in_the_source_so_it_is_not_re_added`,
`test_the_resume_check_says_it_is_running_before_it_runs` (drives the real
`_resumable` and reads the progress file from inside it) and
`test_the_rate_excludes_the_time_spent_checking`. 29 tests in that file.

---

## RCA-2026-09-10-J — the safety check I added an hour earlier cost 45 minutes to save 30, and the row count on screen counted rows the index does not hold

**CEO**

* The resume I built at 2pm sat for 22 minutes doing nothing visible before it
  had even started work. On the finished file the same check would have taken
  about nine hours — to decide whether to save thirty minutes.
* It was checking the half-built file page by page in the slowest possible
  order. The disk is fine: measured 106 MB a second while that check was
  crawling at 1 MB a second.
* It now reads only the small summary table, in under a second. The full check
  still runs at the end, before anything replaces your live file — that one is
  fast because it reuses the memory the load already had.
* Separately, and found the same minute: the row count on your Stored
  strategies screen was counting rows the index does not actually hold.

**DEV**

* `rows_index._resumable()` ran `PRAGMA quick_check` on the 2.74 GB partial
  through a plain `sqlite3.connect` — default page cache **2 MB** — so the
  b-tree walk reached the mechanical G: as random 4 KB reads: **1.0 MB/s**
  measured (`Get-Counter '\Process(python#3)\IO Read Bytes/sec'`), thread
  `WaitReason = PageIn`, 6.4 s of CPU in 22 minutes, while a 319 MB sequential
  read of `rows.db` in the same minute measured **106.3 MB/s**. Extrapolated
  to the finished 32 GB file: **~9 hours**. The same call also did
  `SELECT count(*) FROM rows` — another full scan of the big table.
* Broken invariant: **a safety check must cost less than the work it
  protects** — one that does not gets skipped by whoever is in a hurry, which
  is worse than not having it. And **`SUM(n) FROM pairs` is the row count this
  app prints, so `n` must be rows the index HOLDS**, never rows read from the
  file: `index_pair` stored `len(rows)` while inserting `len(vals)`, which
  skips any row without a coin.
* Guard: `tests/test_rebuild_from_the_pair_files.py` (23) —
  `test_the_resume_check_never_scans_the_big_table` (asserts no `quick_check`
  and no `count(*) FROM rows` in the resume path, AND that `rebuild()` still
  has its pre-swap `quick_check`),
  `test_the_row_count_a_pair_reports_is_what_the_index_HOLDS` (`n` equals
  `count(*)` for that pair, and `_rows_estimate()` equals `status()["rows"]`),
  `test_a_resume_seeds_the_row_count_from_the_summaries` (the seed must be
  EXACT or the pre-swap compare throws the run away).

**SAW** — the operator asked for status. The rebuild had "resumed" 22 minutes
earlier and every number on the progress file was still the one from before it
was stopped.

**TIMELINE**

1. `Sep 10, 2026 2:11pm` — the wrapper reports the collect finished and calls
   `rebuild()`. It prints `resuming from: {'pairs_done': 450, 'rows':
   8385108}`.
2. `2:37pm` — 26 minutes later: `rows.rebuild.db` untouched since `1:48:40pm`,
   the progress file still carrying the dead run's pid, the process at **0.1
   min of CPU** and 40 MB of RAM.
3. `2:38pm` — the one thread: `ThreadState Wait`, **`WaitReason PageIn`**.
   `PhysicalDisk(1 g:)` queue 2.0, `Pages/sec` 225.6. Per-process I/O:
   **1.0 MB/s then 0.58 MB/s** — it was working, at a hundredth of the disk's
   speed.
4. `2:39pm` — measured the disk itself: 319 MB read sequentially from
   `rows.db` in 3.0 s = **106.3 MB/s**. The disk was never the problem.
5. `2:40pm` — stopped it. 2.74 GB partial kept, untouched.
6. Same hour — `_resumable` rewritten to read `meta` and `SELECT pair, n FROM
   pairs` only: **450 rows of summary instead of 2.74 GB of pages**.

**ROOT CAUSE** — two, both a number that was not what it claimed:

* the resume verified the WHOLE FILE to decide whether to trust a 450-row
  summary table, on a connection with a 2 MB cache. The check's cost scales
  with the file; the work it saves does not.
* `pairs.n` was `len(rows)` (read from the JSON) while the insert wrote
  `len(vals)` (rows with a coin). `_rows_estimate()` and `query()`'s total are
  both `SUM(n)`, so the store's printed row count included rows no filter
  could ever return.

**WHY IT WAS NOT CAUGHT** — the resume tests all ran against a **3-pair
store**, where `quick_check` is instant and every path looks free. A cost that
only appears at 2.74 GB is invisible to a correctness test, and I shipped it 40
minutes earlier having run exactly those tests. This is pattern 3 (*test the
layer the operator actually touches*) in its measurement form: the tests proved
the resume was RIGHT and said nothing about whether it was USABLE. The `n`
half was never caught because no test compared `SUM(n)` against
`count(*) FROM rows` — the two numbers the app treats as interchangeable.

**COST** — no money and no data lost. 26 minutes of wall-clock, and the
operator got a status answer of "still 450 pairs" when the run had been going
half an hour. Had it not been measured, the pre-swap check on the finished file
would have added ~9 hours of apparent stall — RCA-G a second time, same shape,
built by the same hand.

**FIX** — this commit. `_resumable()` reads the summary table only, and its
docstring carries the two measured rates so the next person does not re-add the
check; `index_pair` stores `n = len(vals)`. The pre-swap verify is unchanged
and still runs `quick_check` — on the LOADING connection, which holds a 500 MB
cache over pages it has just written.

**GUARD** — the three tests named in the DEV block, in
`tests/test_rebuild_from_the_pair_files.py` (23 tests). Stated plainly: **no
test measures the pre-swap check on a 32 GB file** — that is the next run's
measurement, and if it turns out slow it is RCA-G's lesson again and belongs in
this file.

---

## RCA-2026-09-10-I — the rebuild fell from 40 pairs/min to 0.25 while a collect wrote the same files (the CAUSE is corrected by RCA-K; the gate here is still right)

**CEO**

* The repair job that makes your results searchable was running at 40 coins a
  minute at 12:56pm and **one coin every five minutes** by 1:45pm. At that
  speed it would have taken about two weeks instead of two hours.
* It was started while the job that brings your GitHub results home was still
  running. Both were reading and writing the same disk, and on a spinning disk
  two jobs at once is far worse than one after the other.
* Three things now: the repair refuses to start while that other job is
  running and says so; if it is stopped it picks up where it left off instead
  of starting from zero; and stopping it this time cost nothing.

**DEV**

* `rows_index.rebuild()` was gated on `write_available()` only, which asks
  *"can I take rows.db's write lock?"*. A `db_jobs collect` takes that lock
  only at the very end, so at `12:56pm` it answered FREE while the collect was
  **14 of 20 shards** into rewriting the pair JSONs that `rebuild()` reads.
  Measured at `1:45pm` with both running: `Memory\Pages/sec` **2,534**,
  `PhysicalDisk(_Total)\Current Disk Queue Length` **5.0**, and **0 MB of
  file I/O in 120 s from either process** — the traffic was page faults and
  seeks, which is why neither showed up in `ReadTransferCount`. Rate over the
  run: 40.15 → 24.0 → 16.3 → 13.78 pairs/min average, with the instantaneous
  rate at **one pair per 305 s**. Pair #448 was `ARWRSTOCK-15m.json` at
  **0.0 MB**, so file size explains none of it.
* Broken invariant: **a lock answers "may I write?"; a multi-hour bulk pass has
  to ask "am I the only one working?"** — and separately, **work that took
  33 minutes must not be thrown away by stopping the job that did it.**
* Guard: `tests/test_rebuild_from_the_pair_files.py` (20, was 9) —
  `test_it_waits_for_a_job_that_is_writing_the_same_pair_files` (refuses with
  the kind AND its progress, leaves no file behind),
  `test_a_running_job_can_be_overridden_on_purpose` (`force=True` is opt-in,
  after RCA-F),
  `test_a_job_state_that_cannot_be_read_does_not_block_the_rebuild`,
  `test_a_killed_rebuild_resumes_instead_of_starting_over` (asserts ONLY the
  missing pair is re-read),
  `test_a_partial_file_that_does_not_check_out_is_started_over`,
  `test_a_pair_whose_file_was_deleted_is_dropped_not_left_to_fail`,
  `test_the_rate_it_reports_is_this_runs_work_only`, and
  `test_index_pair_reports_what_LANDED_not_what_it_read`.

**SAW** — the operator saw the filing percentage barely move. Asked for a
status, the honest answer had gone from "ETA ~2h15m" to "about 5 hours" to,
measured properly, thirteen days.

**TIMELINE**

1. `Sep 10, 2026 12:37pm` — a wrapper polls `write_available()` waiting for
   the collect to release the store. It returns free.
2. `Sep 10, 2026 12:56pm` — `rebuild()` starts (pid 9816). First minute:
   **40.15 pairs/min**, 22 pairs, 489,322 rows. The collect (pid 27204/10540,
   started `10:48am`) is still running — shard 14 of 20.
3. `1:24pm` — 296 pairs, 5,662,888 rows, **24.0** pairs/min average.
4. `1:36pm` — 447 pairs, 8,357,108 rows, **16.3**.
5. `1:41pm` — measured over 45 s: **0.0 MB read, 0.0 MB write, 1.6 s CPU**.
   Progress had not moved for the whole window. Not a stall — pair #448
   landed at `1:46pm`, **305 seconds** for one pair.
6. `1:47pm` — machine measured: `Pages/sec` 2,534, disk queue 5.0, free RAM
   **3.2 GB of 16.0 GB**, no single runaway process (VS Code 2.31 GB across 17,
   Chrome 2.00 GB across 23, six `claude` sessions 1.72 GB, node 1.64 GB).
   The collect: **17 of 20** shards, still writing.
7. `1:48pm` — stopped the rebuild on purpose at **450 pairs / 8,385,108 rows
   / 2.74 GB**, so the collect gets the disk to itself. The partial file was
   KEPT.
8. Same hour — resume implemented so those 450 pairs are not lost, plus the
   refusal that would have prevented the whole episode.

**ROOT CAUSE** — **CORRECTED, see RCA-2026-09-10-K.** The mechanism was
`index_pair`'s per-pair `DELETE FROM rows WHERE pair = ?` running with no
`rows_pair` index: a full `SCAN rows` per pair, 39.9 s measured at 2.94 GB,
against a table that grows per pair. The collect made the disk slower and the
gate below is still the right fix, but the decay from 40.15 to 0.25 pairs/min
happened for that reason and would have happened on an idle machine — proved
at `2:11pm`, when the resumed run stuck on ONE pair for 26 minutes with the
collect finished and the disk to itself. What follows was written before that
was known, and is kept as it was written.

**ROOT CAUSE (as first recorded)** — the wrong question in the gate. `write_available()` proves
nothing about a job that writes the pair FILES and touches `rows.db` only at
the end, and `rebuild()`'s whole input is those files. Underneath it, an
assumption that two I/O-bound jobs on one mechanical disk each run at half
speed; measured, they ran at **1/160th**.

**WHY IT WAS NOT CAUGHT** — `test_it_refuses_while_another_process_is_writing`
existed and passed: it stubs `write_available` and asserts the refusal. The
guard tested the CHECK, never the question the check was supposed to answer.
That is pattern 3 (*test the layer the operator actually touches*) at the
process level: the only state that could have shown this is "two jobs at once
on the real store", which no test can hold, so the gate had to be widened by
reasoning about what `rebuild()` actually consumes. Recorded as measured, and
the causal chain (paging + seeks) is stated as MEASURED CORRELATION, not as a
proven mechanism — RCA-G is the entry that came from over-claiming here.

**COST** — no money, no data lost, nothing wrong on screen. 52 minutes of
rebuild wall-clock at a degraded rate, and the operator's filing stayed at 86%
for another hour. The 450 pairs were preserved.

**FIX** — this commit. `rows_index.jobs_writing()` (a running `collect`,
`backtest`, `btupdate` or `download` blocks a rebuild and names itself and its
progress; `force=True` overrides on purpose; an unreadable job state never
blocks), `_resumable()` + `rebuild(resume=True)` (resume rests on
`index_pair` writing the pair's summary row LAST and committing per pair, so a
pair in `pairs` is whole; refuses to resume a file that fails `quick_check` or
carries another `SCHEMA_VERSION`, and drops a pair whose JSON has since been
deleted), and `index_pair` returning what LANDED rather than what it read.

**GUARD** — `tests/test_rebuild_from_the_pair_files.py`, 20 tests, listed in
the DEV block above. Stated plainly: **no test proves the speed** — that needs
two real jobs and a real 32 GB store. The next run is the measurement, and its
rate is in the progress file.

---

## RCA-2026-09-10-H — two guards were RED on `main` for half a day, and both broke on a legitimate edit

**CEO**

* Two of the automatic checks that are supposed to catch mistakes were
  themselves broken for about half a day, and nothing told either of us. Your
  app was fine the whole time - the copy button copied, the answer rules held.
* Neither check was testing what it was written to test. Both were pinned to
  WHERE something lived, so tidying up the code broke the check while changing
  nothing you would ever see.
* Both now check the behaviour instead of the address, and the file that lists
  the repeating mistakes has this shape added to it.

**DEV**

* `test_it_says_both_halves_apply_at_once` asserted the literal string
  `"SHORT AND PLAIN, both"`; `fda4439544b` (`Sep 09 11:12pm`) rewrote that line
  to name three parts, per the operator's own ask. RED for **14 h 24 min**.
  `test_every_row_id_has_a_copy_button_that_reports_what_happened` asserted
  `"function CopyableId(" in StrategiesGrid.tsx`; `32b68feeeb4`
  (`Sep 10 12:46am`) lifted the component into
  `webapp/src/components/trade/CopyableId.tsx` so the positions table could
  stop hand-rolling its own. RED for **12 h 50 min**.
* Broken invariant: **a guard asserts WHAT, never WHERE.** A guard pinned to an
  address goes red on a refactor that changed nothing, and green on a
  regression that moved - it is wrong in both directions, and the false red is
  what teaches a reader to ignore it.
* Guard: both widened in this commit -
  `test_it_says_both_halves_apply_at_once` names SHORT, PLAIN and EXAMPLE
  individually plus the "all three, always" clause, so a fourth part cannot
  delete the third; the copy guard now reads `CopyableId.tsx` for the
  behaviour (icon, `"" | "ok" | "fail"`, `copied`, `could not copy`,
  `document.execCommand("copy")`, `${prefix}${id}`) and then asserts BOTH
  `StrategiesGrid.tsx` and `PositionsPanel.tsx` import and use it and contain
  no `navigator.clipboard` of their own - which is a wider promise than the
  original made.

**SAW** — nothing, and that is the point. Found while running
`tests/test_skills_are_consistent.py` before committing an unrelated docs
change; the operator was never shown a wrong number by either fault.

**TIMELINE**

1. `Sep 09, 2026 11:12pm` — `fda4439544b` lands: the `short-and-plain` rule
   becomes SHORT + PLAIN + EXAMPLE, three places updated (skill, `CLAUDE.md`,
   `SKILLS.md`). Its own test file was not run.
2. `Sep 10, 2026 12:46am` — `32b68feeeb4` lands: `CopyableId` extracted so
   `PositionsPanel` stops hand-rolling a copy button, after
   *"i still cannot copy the id ... y5ubbfpb"*. Its own test file was not run.
3. `Sep 10, 2026 1:23pm` — `pytest tests/test_skills_are_consistent.py`:
   **1 failed, 31 passed**, on the string `SHORT AND PLAIN, both`.
4. `Sep 10, 2026 1:26pm` — the full suite, stopping at the first failure,
   finds the second: `assert 'function CopyableId(' in src`.
5. `Sep 10, 2026 1:33pm` — both widened, `40 passed` across the three
   affected files. The whole suite then ran: **3,801 passed, 15 failed, 1
   error**, and every one of those 16 is pre-existing on this Windows box in a
   file this change does not touch (POSIX file modes, `SIGTERM`, console
   encoding, and the known `test_the_real_book_is_still_one_slot_per_coin`).
   Named here rather than left to read as green.

**ROOT CAUSE** — both guards asserted the ADDRESS of a behaviour: one an exact
sentence in a skill, the other a function body inside the component file that
happened to hold it. Neither commit changed behaviour; both changed an address.
This is the sibling of pattern 1 (*a count is not a location*) with the sign
flipped - there the location was too wide to catch a real fault, here it was so
narrow that a correct edit broke it.

**WHY IT WAS NOT CAUGHT** — nothing ran either test, because neither commit
felt like code: one edited a skill's prose and one moved a React component.
This repo already paid for that once - `e853001f5e5` pushed two red tests
because `pytest | tail -6 && git commit` returns `tail`'s exit code, fixed in
`83fee333983`. The lesson taken then was about the PIPE. The lesson missing was
the simpler one: **a commit that touches a file some test reads must run that
test**, and `grep -rl <file> tests/` finds them in one second.

**COST** — no money, no wrong data, nothing on the operator's screen. The cost
was to the suite's meaning: for 12 of those hours a session running the tests
saw failures it had not caused and could not distinguish from its own.

**FIX** — this commit.

**GUARD** — `tests/test_skills_are_consistent.py::test_it_says_both_halves_apply_at_once`
(names SHORT, PLAIN and EXAMPLE individually plus `all three, always`) and
`tests/test_both_books_on_a_deployed_row.py::test_every_row_id_has_a_copy_button_that_reports_what_happened`
(reads `CopyableId.tsx` for the behaviour, then demands both tables import it
and hold no `navigator.clipboard` of their own). Plus pattern 5 in *Patterns
that keep repeating*. Stated plainly: **nothing here checks that the suite was
actually run** before a commit, so that part remains a habit, not a guard.

---

## RCA-2026-09-10-G — the compaction reached 90% and stopped, and it is still not working

**CEO**

* Seven hours of a background clean-up that never finished, and an estimate I
  gave you ("about 14 minutes") that was wrong by hours. Nothing was lost and
  your app kept working the whole time.
* It copies a 35 GB file while another job writes to the same disk; it slowed
  down forty times over and then stopped, and I could not find out why.
* It is written down as NOT WORKING instead of quietly shelved. A full rebuild
  of the file from your per-coin results - a different route to the same
  result - is what ran instead, and that one moves.

**DEV**

* `rows_index.compact()` -> `VACUUM INTO` on a 34.69 GB source: 14.73 GB copied
  in 30 min (0.47 GB/min), then 4.4 GB in 6.4 h (0.011 GB/min), then **0 bytes**
  of file growth AND 0 bytes of process I/O over 90 s. Unchanged after stopping
  the competing writer (pid 14316, 62 min CPU, 311 GB I/O). `py-spy` could not
  attach ("Failed to find python version"), so no stack was ever obtained.
* Broken invariant: **a long-running job must publish progress often enough
  that a stall is visible in minutes.** `compact()` published none - which is
  why the only estimate available was an extrapolation of its first 30 minutes.
* Guard: `tests/test_compact_rebuilds_into_a_fresh_file.py` (10) holds the
  SAFETY properties, and `test_a_copy_that_does_not_match_is_thrown_away_not_swapped`
  is why abandoning the run cost nothing. **No test asserts that it finishes** -
  none can, off a real 34 GB file. Stated, not hidden.

**SAW** — nothing on screen. The operator asked *"What is estimated time to
finish this"*, was told **~14 minutes**, and the answer was wrong by hours.

**TIMELINE**

1. `Sep 10, 2026 05:31:49` — `compact()` started on the real store: 34.69 GB,
   38.8% free pages, 13.47 GB of holes.
2. First **30 minutes**: the copy reached **14.73 GB** at ~0.47 GB/min. On that
   rate the operator was told ~14 minutes remained.
3. Next **6.4 hours**: the copy reached only **19.16 GB** — 4.4 GB, about
   **0.011 GB/min**, forty times slower.
4. `~12:30` — measured over 90 s: **0 MB** of file growth and **0 MB** of disk
   I/O. Stopping the competing indexer (pid 14316, which had burned 62 min of
   CPU and 311 GB of I/O against the same spindle) changed nothing: still 0 and
   0 over the next 90 s.
5. Stopped it. The incomplete copy and its journal were deleted; `rows.db`
   remained **32.31 GB**, untouched, and the app kept working throughout.

**ROOT CAUSE** — **not established.** What is known: `VACUUM INTO` holds a read
snapshot for its whole run, another writer was hammering the same mechanical
disk for most of it, and the write rate collapsed by 40x rather than stopping
cleanly. What is not known: whether it was starved by that writer, blocked on
the 2.64 GB write-ahead log, or stuck inside SQLite. `py-spy` could not attach
to the process ("Failed to find python version"), so the one tool that would
have said where it sat was unavailable.

**WHY IT WAS NOT CAUGHT** — the ten tests
(`tests/test_compact_rebuilds_into_a_fresh_file.py`) all run on a small
temporary database where `VACUUM INTO` finishes in milliseconds. They prove the
SAFETY — every row and pair survives, a mismatched copy is thrown away with the
original intact — and say nothing about whether it completes on a 34 GB file
with a writer beside it. A green suite here means "it will not lose your data",
not "it will finish".

**COST** — none in money and no data. 7 hours of wall clock, and an ETA given
to the operator that was wrong by two orders of magnitude.

**FIX** — **NOT FIXED.** The code is committed (`7f9a2773650`) and the safety
properties hold, but the operation does not complete on this store. Before it
is trusted again it needs: nothing else writing for its whole duration, the WAL
checkpointed first so the snapshot is small, and a progress signal so a stall
is visible in minutes rather than hours. It must never again be started and
left, which is what turned this into a seven-hour unknown.

**GUARD** — the existing ten tests keep the safety guarantees.
`test_a_copy_that_does_not_match_is_thrown_away_not_swapped` is the one that
mattered here: the run was abandoned and the operator's 52,348,156 rows were
never at risk. No test yet asserts that it completes, because no test can
honestly do that off a real 34 GB file.

---

## RCA-2026-09-10-F — the win % filter answered "nothing matches" when its index was missing

**CEO**

* Your win % filter showed an empty table for about 40 minutes. Nothing was
  wrong with the filter and nothing was wrong with your data - 566,990 results
  had matched the same filter half an hour earlier.
* My own speed-up had removed the sorted lists that filter needs, and instead
  of saying "I cannot check right now" the screen said "nothing found".
* The speed-up is off unless someone asks for it, and a missing list can never
  again be reported as a zero.

**DEV**

* `api.strategies` -> `rows_index.query` -> `_winrate_matches` ->
  `_missing_ok(_read, 0)` at `rows_index.py:1955`. A stale `has_index` cache
  named `rows_wr4` after ANOTHER process dropped it; SQLite raised `no such
  index`; the wrapper returned its default of **0**, which the planner read as
  "no row clears this floor". Result: HTTP 200, `rows=0 total=0`, 18.42 s.
* Broken invariant: **a default that reads as data is a lie.** The absence of an
  answer must never be encoded as a valid answer.
* Guard: `tests/test_a_missing_index_never_reads_as_zero.py` (9) - re-raises on
  `no such index` and drops the cache, keeps the default for `no such table`
  and for a LOCK (`test_a_LOCK_still_earns_the_default_and_that_is_deliberate`,
  which protects `test_a_locked_read_does_not_look_like_a_missing_index`), plus
  `test_status_says_UNKNOWN_not_zero_when_it_cannot_read`.

**SAW** — *"There is nothing wrong with the filter, we are fixing the backtest
I want rootcause as why did you revert the filter now!"*. They were right.
Nothing was reverted, and nothing was wrong with the filter — the catch-up had
broken it.

**TIMELINE**

1. `Sep 10, 2026` — RCA-E's fix drops the ten on-demand indexes so a bulk fill
   can write fast. Three of them — `rows_wr2/wr3/wr4` — are exactly what a
   win-% floor uses.
2. `4:25am` — from the operator's own press log:

       apply | asked: min_winrate=85.0 AND days=30 AND sort=profit AND desc=True
             | got: rows=0 · total=0 | took 18.42s

   **Zero rows, HTTP 200.** The same filter had matched **566,990** rows half
   an hour earlier.
3. `ri.query()` in a FRESH process refused correctly the whole time — *"a win %
   floor of 85 over the store needs more than 20s ... The wide win-rate index
   that makes this instant is still being built"*. Only the API's process lied.

**ROOT CAUSE** — two together. The API's `has_index` cache still believed in an
index another process had dropped, so it named `rows_wr4` and SQLite answered
`no such index`. `_missing_ok(fn, default)` then returned the default — and for
`_winrate_matches` the default is **0**, i.e. "no row clears this floor". "I
could not check" became "nothing matches", and the whole query answered empty.

**WHY IT WAS NOT CAUGHT** — `_missing_ok`'s own docstring already described
this exact failure for a different trigger: *"swallowing that here turned 'this
filter needs longer than 20s' into '0 rows, total 0' — an empty screen
presented as an answer"*. The guard matched the word `interrupt` and nothing
else. Second time, same failure, one word away. **A guard is only as wide as
its pattern** — the third time that rule has been paid for.

**COST** — none in money. The operator's main filter returned an empty table
while their data was intact, and they were told the catch-up was helping.

**FIX** — `ac62504a8cb`. `_missing_ok` forgets the index cache and re-raises on
`no such index`, so the caller either refuses honestly (`SortNotReady`, the
wait the panel renders) or retries with a plan that exists. And the cause is
gone at the source: `sync(drop_indexes=...)` defaults to **False**, so a
catch-up never takes a filter away unless it is asked to.

NARROWED after the first attempt re-raised every SQLite error and instantly
broke `test_a_locked_read_does_not_look_like_a_missing_index` — which exists
because `has_index` answering False under a lock refused a coin filter with
every index present (2026-08-26, 503 in 0.02 s). A lock is transient and makes
the planner CAUTIOUS; a missing index makes it WRONG. Only the second is a lie,
so only the second raises.

**GUARD** — `tests/test_a_missing_index_never_reads_as_zero.py` (7): a missing
index re-raises and drops the stale cache, an interrupted read still re-raises,
a missing TABLE and a LOCK both still earn the empty default, and the win-rate
count is pinned as the call site that made it dangerous. Plus
`test_dropping_is_opt_in_and_off_by_default`.

---

## RCA-2026-09-10-E — the catch-up was paying for FOURTEEN indexes it was designed to rebuild afterwards

**CEO**

* 753 of your 5,365 coins had finished results that no filter and no download
  could find, and filing them was crawling at about one coin every 70 seconds -
  over a week of waiting.
* Every result has to be added to sorted lists so filters stay fast. Your store
  had built up 14 of those lists where the design assumed 4, so filing did 3.5x
  the work it was meant to.
* The extra lists are now set aside during a big catch-up. The deeper cause -
  a third of the file being empty holes - is what the entry above is about, and
  what rebuilding the file from your per-coin results fixes.

**DEV**

* `rows_index.sync()` -> `index_pair()` per pair with all 14 indexes live.
  `KEEP_INDEXES` is 4; `sqlite_master` held 14 (`rows_wr2/3/4`, `rows_pr2`,
  `rows_id`, `rows_signal`, 4x `rows_cf_*`) - every extra one built on demand by
  filter work and never dropped. Measured 250.5 MB of scattered I/O per 40 s
  with `pairs_indexed` static, against 38.8% free pages (13.47 GB of holes).
* Broken invariant: **a bulk fill must not carry indexes it is designed to
  rebuild afterwards.** `_after_fill_indexes()` existed for exactly that; the
  matching drop did not.
* Guard: `tests/test_bulk_fill_drops_only_the_on_demand_indexes.py` (8) - the
  drop list comes from `sqlite_master`, never a constant; no `KEEP_INDEXES`
  member can be dropped; and `test_dropping_is_opt_in_and_off_by_default` pins
  it off after RCA-F.

**SAW** — the operator, `Sep 10, 2026`: *"is the backtest done"*, then *"so the
measure is still in progress?"*. Measuring WAS done — cloud run
`34373004043` completed/success, 1 pending pair. The index had **806** pairs to
go (really **5,276**) and was moving roughly one pair every fourteen minutes:
over a week for a backlog the bulk path does in minutes.

RCA-C, the same night, made that stall VISIBLE and named the chunked-commit
repair it left undone. This entry is the reason the fill is slow in the first
place — RCA-C treats "~14 min/pair on this spinning disk" as a property of the
disk. It is not. It is write amplification nobody chose.

**TIMELINE**

1. `sync()`'s own closing note states the design out loud: *"a fill pays for
   every index it carries: **1.5 pairs/min with six against 75 with none**"* —
   fifty times — and `_after_fill_indexes()` rebuilds the on-demand ones
   afterwards, in detached children. A bulk fill is **supposed** to run on the
   kept four.
2. Nothing ever dropped the others. `KEEP_INDEXES` is the four `ensure()`
   creates; `FILTER_INDEXES` is an empty dict; the on-demand ones are created
   by `build_sort_index` / `build_missing_indexes` and **never removed**.
3. Measured on the operator's store, `Sep 10, 2026`:

       ensure() creates                    4  indexes
       sqlite_master on `rows` held       14
       built on demand, never dropped     10
         rows_wr2  rows_wr3  rows_wr4  rows_pr2  rows_id  rows_signal
         rows_cf_dd  rows_cf_profit  rows_cf_trades  rows_cf_winrate

   Every inserted row maintained fourteen index entries across a 33 GB file on
   a mechanical disk. Sampled per-pid: **250.5 MB of scattered I/O in 40 s**
   with `pairs_indexed` standing still.
4. Each of those ten arrived with a filter fix — `rows_wr2` → `rows_wr3` →
   `rows_wr4` as new boxes landed beside the win-rate floor, `rows_pr2` for
   profit order, the four `rows_cf_*` for the confluence columns. Each was
   correct on its own. The cost landed on a job nobody was watching.

**ROOT CAUSE** — half a design. The fill was built to run lean and rebuild the
extras afterwards; the "drop them first" half was never written. So the first
time a filter built an index, every future fill inherited it, permanently.

**WHY IT WAS NOT CAUGHT** — the index suites (289 passing across
`test_index_catchup`, `test_index_yields_to_the_sweep`, `test_rows_index`,
`test_index_ensure_cheap`) assert what the index CONTAINS and that `ensure()`
stays cheap. None asserts what the fill CARRIES. A test that counts indexes on
disk against `KEEP_INDEXES` would have gone red the day `rows_wr2` was created
— and nothing about the filters' own tests could ever have noticed, because the
filters were right.

**COST** — none in money. The operator's finished measurements sat invisible
for days: Stored strategies showed 4,558 of 5,364 pairs, and a filter or a
download could not see the other 806.

**FIX** — this commit. `sync()` drops the on-demand indexes for a bulk fill
(`len(todo) > BIG_FILL`, 500 pairs) and the existing `_after_fill_indexes()`
rebuilds them detached, which is what it was always for. Three things make it
safe:

* `_drop_on_demand_indexes` reads `sqlite_master` and can only drop what is
  **not** in `KEEP_INDEXES` — so `rows_profit`, `rows_coin`, `rows_winrate` and
  `rows_pair` always survive. Dropping `rows_profit` on `2026-08-27 12:48am`
  blanked the default screen for ~25 minutes (*"why does it not show
  anything"*); that is why the four are ring-fenced rather than trusted to a
  list.
* a read needing a dropped index already answers `SortNotReady` — the "it is
  being built" wait the panel renders — instead of a blank page.
* a `DROP` that fails is logged and skipped; the fill is not failed for it.

Read from `sqlite_master`, not a constant, so a filter index invented next
month is dropped by a fill that has never heard of it.

**GUARD** — `tests/test_bulk_fill_drops_only_the_on_demand_indexes.py` (8):
the kept four are exactly `ensure()`'s, the list comes from `sqlite_master` (a
`rows_future_filter` invented in the test is found), a bulk fill drops ten and
keeps four, **no kept index can ever be dropped**, the drop sits under
`if bulk` so an ordinary click pays nothing, every dropped index has DDL to
rebuild it, the rebuild still fires on `if done:`, and a refused DROP does not
fail the fill.

**MEASURED AFTER THE FIX, AND IT IS NOT ENOUGH** — the catch-up ran with the
ten dropped and only the protected four left, and the log confirms it:

    [rows-index] dropped rows_wr4 for a 5276-pair fill; it rebuilds when the
    fill ends

Pairs then moved — 4,558 → 4,571 — so the fill is committing per pair, not in
one transaction as first reported. But the rate is **~1 pair per 175 s
(0.34 pairs/min)**, not the 75/min the note promises with no indexes. At that
rate the remaining 793 pairs are **~39 hours**.

The reason is the file itself, measured `Sep 10, 2026`:

    rows.db      34.7 GB
    pages        8,469,643 total
    free pages   3,961,902  = 46.8% of the file = 16.23 GB of holes

Every insert scatters into a file that is nearly half empty space, so the disk
seeks instead of streaming. CLAUDE.md already carries the remedy — *"Do NOT
repair a bloated file in place ... Loading a FRESH file sequentially and
swapping it in is faster and leaves a compact database"* — written when the
store held **727,146** free pages (2.8 GB). It now holds **5.4x that**. And
there is **no compaction path in the code at all**: `checkpoint_if_bloated`
folds the write-ahead log back in and touches free pages not at all; there is
no `VACUUM`, no rebuild, no swap anywhere in `rows_index.py`.

So dropping the ten indexes was a real and necessary reduction in write
amplification, and the dominant cost is now bloat that nothing can reclaim.

**STILL NOT FIXED, named so neither is forgotten**

1. **No way to compact the store.** 16.23 GB of the 34.7 GB file is holes, and
   the documented fix (rebuild sequentially into a fresh file, swap on success)
   exists only as a sentence in CLAUDE.md. It must write a NEW file and swap
   only after it verifies, because this is the operator's only copy of
   51,943,352 measured rows.
2. **`forget_pairs` holds ONE transaction across every pair**, so a 73-pair
   cleanup freezes the whole index until it finishes. RCA-C named it; still
   true. Chunked commits are the repair, and the caller's "may the files go
   now" contract has to move with them.

---

## RCA-2026-09-10-D — you picked BTC and GitHub measured 0G, ALPINE, AVAAI…

**CEO**

* You picked BTC, pressed BACKTEST, and GitHub measured 0G, ALPINE, AVAAI and
  seventeen other coins you never asked for. BTC was measured by nobody.
* The screen sent how MANY coins you picked, never WHICH ones, so the 20
  machines helped themselves from the top of an alphabetical list.
* The names travel with the job now, and the screen prints back what GitHub was
  actually asked to measure.

**DEV**

* The Backtest screen sent `coins: coins.length`; the shard reads `COINS` as a
  per-machine claim CAP, so 20 workers started at board positions #1, #54, #107
  ... #1012 of 1,065 contracts. `BTC_USDT` is #190 and was claimed by no one.
  Four paths had the same hole: the button, `db_jobs._run_btupdate` (sent no
  coins at all), `api._finish_handoff` (sent `len(left)`), `sweep_orchestrator`.
* Broken invariant: **a field must mean the same thing to the sender and the
  receiver** - a COUNT written into a CAP is not a selection.
* Guard: `tests/test_picked_coins_travel.py` (15) - the names travel, the fleet
  is trimmed, `coins` goes to 0, an empty pick still means the whole market, a
  named coin the venue will not trade is NAMED, all four paths send the list
  while resolve-pending deliberately does not. Plus
  `test_state_runs_are_recorded_per_timeframe_and_expire` (3 per frame, newest
  first) - a named run would otherwise have become the only saved positions for
  its timeframe.

**SAW** — the operator, reading the live-results explanation: *"so when i
backtest btc it runs backtets on github then store the result direclty on my
machine right?"* Storing, yes. Measuring BTC, no. Then, on being shown why:
*"fix this use harddev can you please review your code first because it seems
you just code without considering impacts like this one"*.

**TIMELINE**

1. `Sep 05, 2026` — BACKTEST stopped running on this PC and started dispatching
   GitHub ("no option 'this mac'"). The Backtest screen kept its coin picker
   and sent `coins: coins.length` — **how many were picked, never which**.
2. `Sep 09, 2026` — work went claim-based (RCA of "why is it idle"): the shard
   reads `COINS` as "the most coins ONE machine may claim" and the twenty
   machines help themselves from a sorted board of **1,065 contracts**, each
   starting in its own region so they never collide.
3. `Sep 09, 2026 11:52pm` — measured, by pressing the real route with 2 coins
   asked for: the fleet measured **0G_USDT** and **1000000BABYDOGE_USDT** —
   the top of the board. Nobody picked those; they are simply first
   alphabetically. Every "proof" run of that evening was the same two coins.
4. `Sep 10, 2026` — computed from the live board for the operator's own case:
   pick **BTC**, press BACKTEST, 20 machines start at #1, #54, #107 … #1012 and
   claim **0G, ALPINE, AVAAI, BLAST, CC, CSOPSKHYNIX2L, EDGE, FLUX, HANA,
   IONQSTOCK, LASERTECSTOCK, MET, NGAS, PANASONICSTOCK, QCOMSTOCK, SANTOS,
   SONYSTOCK, TAO, UKOIL, XAN**. BTC_USDT is at **#190** and is measured by
   nobody.
5. The review that followed found **four** dispatch paths with the same hole,
   not one: the BACKTEST button, UPDATE BACKTEST (`db_jobs._run_btupdate`, which
   sent no coins at all, so picking BTC updated the whole market), the HAND-OFF
   (`api._finish_handoff`, which computes the exact coins this PC never reached
   and then sent only `len(left)`), and `sweep_orchestrator`.

**ROOT CAUSE** — a field that means one thing to the sender and another to the
receiver. `coins` is a per-machine CAP in the shard, and the screen filled it
with the SIZE of the pick. Nothing carried the names, so the fleet had nothing
to obey.

**WHY IT WAS NOT CAUGHT** — every cloud test asserted the ARGUMENTS a dispatch
sends (`min_days=`, `base=`, `days=`, `mode=`) and none asserted the WORK it
produces. `test_every_dispatch_path_asks_for_every_contract` even walks all the
dispatch paths — checking they pass `min_days` — and a whole-market run measures
every coin either way, so the picker was never the thing under test. The bug
only shows when the ask is SMALLER than the market, which no test and no
proof run had ever been.

**COST** — none in money, and no wrong data: every coin measured was measured
correctly. What was lost is every small run since Sep 05 — including this
session's own "proof" runs, which measured 0G and BABYDOGE while I believed I
had chosen them — and any hand-off, which measured the top of the board instead
of the coins this PC had missed.

**FIX** — this commit. `cloud_sweep.dispatch(coin_list=…)` sends the NAMES
(`symbols_of`: BTC → BTC_USDT, one conversion), trims the fleet to the list so
nineteen machines do not start for one coin, and drops the per-machine cap; the
workflow carries `coin_list` (its tenth and last allowed input) and the shard's
`eligible()` makes the board exactly those coins, NAMING any the venue is not
trading. All four paths send it; `POST /api/backtest/pending/resolve` keeps the
whole board and says in place that this is deliberate. The screen prints back
what GitHub was actually asked for, from the dispatch's own answer.

Two consequences the harddev loop caught before shipping, both bigger than the
fix itself:
* a named run would have become the ONLY source of saved positions for its
  timeframe (`record_state_run` kept one run per frame), so a two-coin run
  would have thrown away the fleet's memory and the next UPDATE would measure
  1,063 coins from scratch — RCA-2026-09-09-P again. Three runs are kept per
  timeframe now, newest first, and the shard takes each pair from the first run
  that has it (so a runner short of disk loses the OLDEST positions, not the
  freshest).
* "GitHub is busy — that run covers 1h, which is every pending frame" would be
  true of the frame and false of the work. A run that named its coins now
  covers no frame.

**GUARD** — `tests/test_picked_coins_travel.py` (15): the name travels, the
fleet is trimmed, `coins` goes to 0, an empty pick still means the whole market,
names are normalised once, too many names falls back AND says so, the shard's
board is exactly the named coins, a named coin the venue will not trade is
NAMED, every one of the four paths sends the list while resolve-pending
deliberately does not, the workflow stays inside GitHub's ten-input limit, and
the screen sends names and reports what came back. Plus
`test_state_runs_are_recorded_per_timeframe_and_expire` (three per frame,
newest first, old one-dict records still read) and
`test_the_handoff_waits_for_the_local_job_to_stand_down` (the names, not the
count). `test_cloud_percentage` and `test_backtest_dispatches_mode_full` were
red before this and are fixed here: both pinned a fixed slice of source that a
comment moved.

---

## RCA-2026-09-10-C — the row index went quiet for 13 hours and NOTHING anywhere said why

**CEO**

* Your finished results stayed invisible for 13 hours and nothing anywhere said
  why - the screen simply showed the day before's numbers.
* The filing job hit a locked file, the error was thrown away in silence, its
  log was being sent to nowhere, and the button said "started" when nothing had.
* The error is kept and shown now, the job writes a real log, and the button
  refuses with the reason instead of pretending.

**DEV**

* `sync_in_background`'s worker was `except Exception: pass`; the thread died on
  `ensure()`'s first statement (`database is locked`) after the caller had
  already returned `started: true`. `spawn_indexer` ran with
  `stdout=DEVNULL, stderr=DEVNULL`. And `POST /api/strategies/reindex` printed
  `behind` (806) for a job that walks `stale_pairs()` (5,276) - 6.5x under.
* Broken invariant: **a job that cannot start must say so** - and a count on a
  button must be the count of the work that button will actually do.
* Guard: `tests/test_index_stall_is_visible.py` (14), including
  `test_a_failed_catch_up_is_remembered_not_swallowed` (drives the real thread
  with a real `OperationalError`) and
  `test_the_indexer_writes_a_log_instead_of_DEVNULL`.

**SAW** — the operator, `Sep 10, 2026 1:05am`, told the measuring was finished
while their screen showed the day before's numbers: *"is tehre a bug or what i
dont understand"*, then *"did you fix the bug"*.

**TIMELINE**

1. `Sep 09  6:22am` — the standalone indexer starts (pid 22424).
2. `Sep 09 11:55am` — a delisted-coin cleanup starts (pid 12932): remove 32
   dead coins, **73 pairs**, from `rows.db`. `forget_pairs` takes the write
   lock in **ONE transaction across every pair** and holds it to the end.
3. `Sep 10 12:38am` — the last collect finishes. **5,364 pair files** on disk.
   The measuring is genuinely done.
4. `Sep 10 12:47am` — REINDEX pressed. It answers
   **`{"started": true, "behind": 806, "why": "indexing 806 measured pair(s)
   now"}`** and does **nothing at all**.
5. `Sep 10 12:50am–1:02am` — measured, repeatedly: `pairs_indexed` frozen at
   **4,558**, rows at **51,943,352**, across four samples 45 s apart. The
   write-ahead file grew **+7.3 MB in 60 s** — alive, crawling.
6. `Sep 10  1:00am` — the indexer used **0.0 s of CPU in 30 s** (258 min of
   CPU over 18.7 h of wall clock, 61 MB resident). Alive; doing nothing.
7. `Sep 10  1:03am` — calling `ri.sync(max_pairs=3, force=True)` by hand
   finally printed the cause: `sqlite3.OperationalError: database is locked`,
   raised by `ensure()` — the FIRST statement of `sync()`.
8. Real backlog at that moment: **5,276** pairs (814 never indexed, 4,462
   whose file had moved) against a 33 GB `rows.db` and a 5.4 GB WAL.

**ROOT CAUSE** — one stall, three faults that each hid it:

* `sync_in_background`'s worker was `except Exception: pass`. The thread died
  on its first statement and the caller had already returned `started: true`.
* `POST /api/strategies/reindex` printed `behind` (never-indexed, **806**)
  as the size of a job that walks `stale_pairs()` (**5,276**) — 6.5x under, so
  even a working run would have looked finished a sixth of the way in.
* `spawn_indexer` ran the process with `stdout=DEVNULL, stderr=DEVNULL`. That
  process is the only thing that prints *"paused: a backtest is running"* and
  *"indexing N pairs"*. Every line of 18.7 hours went in the bin, and every
  other job in this project writes `~/.tradingagents/*.log`.

**WHY IT WAS NOT CAUGHT** — the index had tests for what it CONTAINS and how
FAST it fills (`test_index_catchup`, `test_index_yields_to_the_sweep`,
`test_rows_index`, 289 passing). None asked what happens when the fill
**cannot start**. A swallowed exception has no observable behaviour to assert
unless you decide the failure itself is a product surface — so the guard has to
be written against the swallow, not the success. Two of the three faults were
pure reporting, which no correctness test would ever reach.

**COST** — no money. 13 hours of the operator's finished results invisible on
their own screen, and a diagnosis that took walking the process table and
sampling CPU per-pid because there was no log to read.

**FIX** — this commit. `_last_error` is kept and served in `status()`;
`status()` also reports `stale` (the real backlog) and `blocked_by`, a new
`lock_holder()` that names the cleanup holding the write lock and its phase;
the route refuses with that reason instead of answering `started`, and prints
`todo`, not `behind`; `spawn_indexer` writes `~/.tradingagents/rows_index.log`
with `PYTHONUNBUFFERED=1`.

NOT fixed here, and named so it is not forgotten: `forget_pairs` holds ONE
transaction across every pair by design, so a 73-pair cleanup freezes the whole
index for as long as it takes (~14 min/pair on this spinning disk). Chunked
commits are the real repair; that is a deliberate change, not a 1am one, and
the caller's "may the files go now" contract has to move with it.

**GUARD** — `tests/test_index_stall_is_visible.py`, 14 tests:
`test_a_failed_catch_up_is_remembered_not_swallowed` (drives the real thread
with a real `OperationalError` and asserts it reaches `status()`),
`test_the_swallow_is_gone_from_the_source`,
`test_a_success_clears_the_last_failure` (a stale error is its own false
label), `test_the_button_counts_the_work_it_will_actually_do`,
`test_the_route_prints_the_bigger_number`,
`test_the_status_names_what_holds_the_write_lock`,
`test_a_cleanup_that_is_NOT_in_the_index_phase_does_not_get_blamed` (blaming
the wrong job sends somebody to stop the wrong process),
`test_the_button_refuses_instead_of_pretending_when_the_door_is_held`,
`test_the_indexer_writes_a_log_instead_of_DEVNULL`,
`test_the_log_is_not_buffered_away`. All three faults were re-introduced and
the suite went red on each before this was committed.

**A CORRECTION I OWE THE RECORD** — at `1:02am` the operator was told the
cleanup was "frozen on coin 56 of 73, and its counter has not moved". The
counter had not moved, but `_drop_pairs`'s `on_pair` only flushes
`every 5 pairs` (`if job["index_done"] % 5 == 0`), so a still reading
"55 of 73" is consistent with anything from 55 to 59 and proves nothing about
a freeze. Rule 23 — read the emitter, not the label — and it was broken while
writing up a bug about invisible progress.

---

## RCA-2026-09-10-B — the fleet's rows were unpacked on the C: drive, and every killed collect left 3 GB behind

**CEO**

* Results coming back from GitHub were unpacked onto your C: drive - 9.39 GB of
  them, on a drive with 6 GB left - and 147 leftover folders had piled up since
  Sep 03.
* Each unpack asked Windows for "a temporary folder" and got the system drive,
  and a job that was stopped never cleaned its own folder up.
* Unpacking happens on G: beside your store now, and leftovers older than six
  hours are swept on the way in.

**DEV**

* `cloud_sweep.fetch()` and `collect_into_store()` both called
  `tempfile.TemporaryDirectory()` with no `dir=`, so shards (`rows-5.jsonl`,
  3.33 GB each) landed in `%TEMP%` on C: while `market_sweep.HOME` is a junction
  onto G:. `TemporaryDirectory` only cleans on a normal exit from its `with`,
  and `start.py` kills the job tree with `taskkill /T` - so every hard stop
  leaked a whole shard, permanently.
* Broken invariant: **scratch space belongs on the same volume as the data it is
  for**, and a killed job must not leak for ever. "Temporary" carried two false
  assumptions here: not small, and not self-cleaning.
* Guard: `tests/test_cloud_sweep.py` -
  `test_no_artifact_is_unpacked_on_the_system_drive` walks the AST for every
  `TemporaryDirectory` call and demands `dir=_scratch()` (reading the calls, not
  the prose), plus `test_the_scratch_sits_on_the_stores_own_drive`,
  `test_a_store_drive_that_cannot_be_used_falls_back` and
  `test_a_killed_collect_does_not_leak_a_shard_forever`.

**SAW** — the operator, `Sep 10, 2026 12:10am`: *"why are you using my c
drive?"*. Their store is on G: on purpose. C: had **6 GB free of 118 GB**.

**TIMELINE**

1. `Sep 09  9:48pm` — a collect starts (pid 22408) for run 34307921614:
   20 shards of GitHub artifacts to stream into the store.
2. `Sep 09 11:23pm` — TWO folders appear in `%TEMP%`, `tmpsmhtelf3` and
   `tmpcvnyccor`, **3.33 GB each**, each holding the same file: `rows-5.jsonl`.
   Both are orphans of collects that were killed. Neither is ever read again.
3. `Sep 10 12:14am` — a third, `tmpw3zb_lwl`, 2.73 GB, `rows-18.jsonl`. That
   one is live: the collect is on shard 18 of 20.
4. `Sep 10 12:10am` — **9.39 GB** of unpacked shards sitting on the system
   drive, which has 6 GB left. The operator asks the question above.
5. Counted the same minute: **147** leaked `tmp*` folders in `%TEMP%`, the
   oldest from `Sep 03`.
6. `Sep 10 12:22am` — the two dead unpacks deleted after checking no process
   held them open. C: **6.4 GB → 13 GB free**.

**ROOT CAUSE** — `cloud_sweep.fetch()` and `cloud_sweep.collect_into_store()`
both called `tempfile.TemporaryDirectory()` with no `dir=`. That is `%TEMP%` —
`AppData\Local\Temp`, on the SYSTEM drive — while `market_sweep.HOME` is
`~/.tradingagents`, a junction onto `G:`. Every byte the fleet produced was
written to C: first and only then streamed to G:.

Two things made it bite instead of being harmless:

* **A shard is not a temp file.** `rows-5.jsonl` is 3.33 GB. Twenty of them is
  ~60 GB, more than C: had free at any point today.
* **`TemporaryDirectory` only cleans if the process reaches the end of the
  `with`.** A KILLED collect never does — and `start.py` kills the job tree
  with `taskkill /T` on every restart (see the operator memory note). So each
  hard stop leaks a whole shard, permanently. That is where all three came
  from, and where the 147 came from.

**WHY IT WAS NOT CAUGHT** — every test about the store checks its CONTENT:
rows, watermarks, cloud/local parity, ownership marks. Not one asked WHERE the
bytes land on the way in. And the word "temporary" carries an assumption that
was false twice over here: not small, and not self-cleaning.

**COST** — no money. The risk was the machine: Windows on 6 GB of 118 GB
stalls its page file, and this same session had already traced the backtest's
slowness to page-file thrashing. A bigger run would have filled C: outright.

**FIX** — this commit. `cloud_sweep._scratch()`: unpack inside the store's own tree
(`HOME/tmp`), falling back to the system default with a warning if that drive
cannot be used, and sweep our own `tmp*` leftovers older than
`SCRATCH_TTL_S` (6 hours — a download times out at 30 minutes) on the way in.
The 147 already on C: were a one-time manual reclaim, not code: `%TEMP%` is
not ours to sweep from a library.

**GUARD** — `tests/test_cloud_sweep.py`:
`test_no_artifact_is_unpacked_on_the_system_drive` walks the AST for every
`TemporaryDirectory` call and demands `dir=_scratch()` (reading the calls, not
the prose — the docstring quotes the broken form);
`test_the_scratch_sits_on_the_stores_own_drive`;
`test_a_store_drive_that_cannot_be_used_falls_back`;
`test_a_killed_collect_does_not_leak_a_shard_forever` proves a six-hour-old
unpack is removed, a live one is kept, and a folder that is not ours is never
touched.

---

## RCA-2026-09-10-A — the row UPDATE button deleted rows, then silently binned the one it measured

**CEO**

* You pressed UPDATE on one strategy (#SW8Q96E6, STBL 4h). It deleted 30 of the
  67 strategies stored for that coin - including the one you were looking at -
  then measured your row correctly and binned the result, reporting success.
* Three things at once: it replaced the coin's whole file instead of adding to
  it, re-measured all 120 strategies instead of the one you asked for, and
  judged your 20 trades "too thin" using a whole year's yardstick on a coin with
  103 days of history.
* Fixed: it measures only your row, adds instead of replacing, and uses the
  coin's real history length. Your row now reads 20 trades, 19 wins, +$42.19.

**DEV**

* `market_sweep.run_pair(..., merge=False)` is the DEFAULT and was never passed,
  so `save_pair_rows` REPLACED the pair file and dropped every combination that
  produced no row this run. The same call sizes the trade floor from the `days`
  ARGUMENT: the route sent 365 against 103 days of candles, so the 4h floor was
  **40** instead of **11** and a genuine 20-trade row was discarded as thin.
* Broken invariant: **an update adds; only a delete deletes** - and a floor is
  computed from the DATA's own depth, never from a caller's parameter.
* Guard: `tests/test_row_update_button.py` (17), each test stating its own
  premise so it cannot rot - one asserts `run_pair`'s `merge` default is still
  False, another that the floor still varies with `days` - plus eight live
  scenarios against the real store. The 14 tests that passed while all three
  bugs were live had all stubbed `run_pair`.

**SAW** — the operator, on #SW8Q96E6 (STBL 4h, macddiv, tp2.5/sl2.5, flat):
first *"was there 15 days silent days? is this accurate"*, then *"its simple
just update the backtest for that certain strategy i dont understand what's
hard on that"*, then *"can you do multiple scenarios testing just to make sure
its working properly"*. Each question found a different bug in the button
shipped hours earlier (RCA-2026-09-09-Q).

**TIMELINE**

1. `Sep 09  9:14pm` — UPDATE pressed on STBL 4h. Measurement lands (watermark
   Aug 28 → Sep 09 4:00pm, 8,774 rows).
2. `Sep 09  ~9:50pm` — the pair file holds **37 signals**. It held **67**.
   `macddiv` — the operator's own row — is among the 30 deleted.
3. `Sep 09 later` — with merge fixed, a re-measure writes **0** macddiv rows,
   while `trades_for` on the same combination rebuilds **20 trades, 19 wins,
   +$42.19**. The button reports success and changes nothing.
4. `Sep 10` — eight live scenarios pass; the row reads 20/19/1/+$42.19 in the
   store.

**ROOT CAUSE** — three, in one function:

* `market_sweep.run_pair(..., merge=False)` is the DEFAULT and the argument
  was never passed. merge=False writes with `save_pair_rows`, which REPLACES
  the file: any combination producing no row this run is deleted, and a
  combination that takes no trade produces no row. The module says it at the
  definition — *"with save_pair_rows would delete every combination not yet
  reached"*.
* The button re-measured ALL 120 signals for the pair, which made that
  deletion large and the run slow, when the operator had asked for one row.
* `run_pair` sizes the trade floor as `min_trades(tf, days=days)` from the
  `days` ARGUMENT. The button asked for 365 on a pair holding 103 days of
  candles: 4h demands **40** trades at 365 days and **11** at 103. A row with
  20 genuine trades was counted "thin" and dropped — measured perfectly, then
  binned, with the job reporting success.

**FIX** (this commit) — `signals=[the row's own signal]`, `merge=True`, and
`days` taken from the pair's real candle span (route sends `days: 0` to mean
"ask the store"). Verified live: *"signals lost: NONE"*, and the row now holds
20 trades / 19 wins / +$42.19.

**WHY IT WAS NOT CAUGHT** — 14 tests passed over this button while all three
bugs were live. Every one of them stubbed `run_pair`, so they asserted what
the button ASKED FOR and never what the store ended up holding. A default
argument that destroys data, and a floor computed from a caller's parameter,
are both invisible to a mock. Only pressing it against the real store showed
them — which is exactly what the operator's three questions did, in sequence.

**COST** — 30 signals' rows on STBL 4h, gone. They came from a GitHub
measurement and a local run does not reproduce them; the pair needs a fleet
re-measure to be whole. No money, no live trading affected.

**GUARD** — `tests/test_row_update_button.py` (17), and each new test states
its own premise so it cannot rot: one asserts `run_pair`'s `merge` default is
still False, another that the trade floor still varies with `days`. Plus eight
live scenarios (another pair, double press, a signal that yields nothing, a
coin with no candles, both symbol forms) run against the real store.

## RCA-2026-09-09-S — the run bar read 100% from the first second, and a tile's dates were on a different clock from the store's

**SAW** — the Backtest screen during proof run 34360893326, photographed by the
press-and-watch script:

    10:03pm  GitHub run #34360893326  100.0%  1/1 coins · 0 rows measured · 0/1 machine(s) finished
             machine 0  100%   testing · 0G 1h: continuing from Sep 09, 2026 1…
    10:04pm  GitHub run #34360893326  100.0%  2/2 coins · 36,388 rows measured · 0/1 machine(s) finished
             machine 0  100%   testing · 1000000BABYDOGE 1h: rule 40/120 …
                               Sep 09, 2026 12:00pm → Sep 09, 2026 1:00pm

Nothing was finished at either moment. And the Stored strategies list on the
same PC named the same two bars `Sep 09, 2026 8:00pm → 9:00pm`. The operator's
question all day: *"currently i can only see machine loading and im not sure …
that way i know why its taking so long"*.

**TIMELINE**

1. `Sep 09, 2026` (earlier that day) — work moved to a claim board: a machine
   claims ONE coin at a time (`coin_stream`), and `run_pair` reports
   `report("testing", i, n)` with `i` = the coin it is on and `n` = the coins
   it has claimed so far. Those are equal on every report, so `pct = 100·i/n`
   is 100 from the first coin, on every machine, for the whole run; the panel
   summed `done`/`total` across machines and drew 100% too. Before the board,
   `n` was a machine's fixed slice and the bar meant something.
2. `10:03pm` and `10:04pm` — the two screenshots above, 0 machines finished.
3. The tile's dates came from `fmt_when` on the runner, whose clock is UTC:
   `12:00pm → 1:00pm`. The store on this PC (UTC+8) shows `8:00pm → 9:00pm`
   for the same bars. One bar, two names.

**ROOT CAUSE** — a counter renamed by its readers. `done`/`total` were
documented in `api.ts` as *"coins this machine has finished, and how many it
was given"*; they were the coin being tested and the coins claimed so far. And
a date string formatted where the data was, not where it is read.

**WHY IT WAS NOT CAUGHT** —
`test_the_payload_a_shard_writes_round_trips_to_the_panels_shape` asserted the
payload HAS `pct`, `done`, `total`; nothing asserted `pct` is below 100 while a
coin is still being tested, and nothing compared the panel's dates with the
store's for the same bar. Presence was checked; agreement was not
(`label-must-match-data`). The claim-board change did not re-read who consumed
`n`.

**COST** — none in money. A progress bar that could not answer "how far along",
on the day the operator asked exactly that.

**FIX** — this commit. The shard publishes `finished` (coins this machine has
completed) and `board` (coins the run holds, the same number on every machine);
the panel draws sum(finished) / board for the run and prints "N coin(s) done"
on each tile instead of a percentage a machine cannot have. Every span rides as
`span_ms` too and the browser prints it with `fmtWhenMs` — the same clock as
every other date on the page; `span` (UTC text) stays for the runner log and
older runs. Older shard files have neither field and fall back.

**GUARD** —
`tests/test_shard_reports_its_dates.py::test_the_bar_is_not_100_while_the_first_coin_is_still_being_tested`
(payload `pct` 0.0 with `done == total == 1`; 50.0 after one of two coins),
`test_the_shard_counts_finished_coins_and_the_runs_board`,
`test_the_panel_draws_the_run_from_finished_over_board`, and the span test now
requires `fmtWhenMs(sh.span_ms[…])`.

---

## RCA-2026-09-09-R — the position a continuation saved had no boundary flag, so the NEXT update would have taken trades the full run never took

**SAW** — found by reading what run 34360893326 (the second proof of UPDATE)
re-saved: `0G-1h.json.gz`, 27,720 combinations, `KeyError: 'exit_at_last'`
on the first of them. Every one of that run's **52,668** saved positions lacks
the flag. **NEVER HAPPENED YET** on a screen — the run after it had not been
pressed. Times below are this PC's (UTC+8); the shard logs print UTC.

**TIMELINE**

1. `Sep 09, 2026 9:33pm` — proof FULL run 34357754670 saved 0G-1h and
   1000000BABYDOGE-1h with `fast_grid.end_state`: every combination carries
   `exit_at_last` (True when its last trade closed on the last tested bar,
   `Sep 09, 2026 8:00pm`).
2. `10:01pm` — proof UPDATE run 34360893326 continued both over the one new
   bar (`8:00pm → 9:00pm`). `resume_state.continue_combo` built the new
   position as the engine's `state` plus the streak; the engine has no notion
   of the flag, so it was dropped. BABYDOGE `mom6 th 0.2 tp 0.4 sl 0.3 flat`:
   4,319 → 4,320 trades, −$823.93 → −$823.63; 5,740 of 0G's 27,720
   combinations ended the bar with an open trade. Collected `10:05pm`: 51,436
   rows, 2 pairs, state run → 34360893326.
3. What the NEXT update would have done, for every combination without an
   open trade: `prev.get("exit_at_last")` is None → start one bar early → the
   engine evaluates the signal on the `9:00pm` bar. A full run never does:
   after an exit on bar j it searches from j+1. So each combination whose
   last trade closed on that bar with a signal on it would have entered a
   trade on the next bar that the whole-history measurement does not
   contain. How many: not readable from the saved state — the flag was the
   only record, which is the point.

**ROOT CAUSE** — `continue_combo` returned `dict(r["state"])` plus the
streak; the flag lived only in `fast_grid.end_state`, the full path. Two
writers of one file shape, one missing a field the reader depends on.

**WHY IT WAS NOT CAUGHT** —
`test_the_gap_continued_from_the_saved_position_equals_one_full_run` pins ONE
continuation against a full run. The flag is consumed at the START of the next
continuation, so a state written by a continuation was never READ by anything
in a test, and the proof runs had the same shape (full → update). The second
update was the first reader, and it had not run. A field that only a later run
reads needs a test that runs later.

**COST** — none. Two proof pairs on GitHub; nothing on screen.

**FIX** — this commit. `continue_combo` sets `exit_at_last` from the engine's
own log (`auto_trader.backtest_strategy` log rows now carry `exit_bar`, the
name the slices rows already used); `sweep_shard.state_usable` refuses a
position saved without the flag ("measured in full"), so the two positions run
34360893326 saved are re-measured, never continued.

**GUARD** —
`tests/test_cloud_continue.py::test_two_continuations_in_a_row_equal_one_full_run`
chains full → continue → continue with the middle boundary on a bar where a
trade closed AND a signal sits, equal to one full run — and proves the flag is
load-bearing by dropping it and watching the phantom trade appear;
`test_the_continued_position_carries_the_boundary_flag` (present, and agreeing
with the engine's log);
`tests/test_cloud_update_mode.py::test_a_saved_position_without_the_boundary_flag_is_measured_in_full`.

---

## RCA-2026-09-09-P — UPDATE on GitHub re-measured the whole year, and the collector then threw 99% of it away

**SAW** — *"if the last backtest was sep1 and i click update it should run on
github to update the gap which is sept 2 onwards simple as that"* — after three
asks about which dates a run was testing, and the header finally admitting
"the whole 365-day window, from scratch".

**TIMELINE**

1. `Sep 05, 2026` — measuring moved to GitHub ("no option 'this mac'"). The
   cloud shard measures with `fast_grid` (two walks, no notion of a saved
   position); the "continue over new bars only" logic lived only in the PC
   path that was switched off. From here UPDATE and BACKTEST were the same
   job on the cloud: `db_jobs._run_btupdate` dispatched `days=365`, the
   shard cut every pair at `DAYS+30`.
2. The collector kept the pre-Sep-05 rule "never overwrite a pair the Mac
   finished" (`pair_watermark > 0 → refused`). The collect log for the eight
   runs to `Sep 09`: **0, 1, 17, 4, 0, 0, 0, 9 pairs kept** against
   **1,550–4,549 "skipped, already measured here"** per run. Run 34285739222
   alone: 40,148,482 rows measured by twenty machines, 9 pairs landed.
3. The Stored strategies therefore still held **August's** measurements —
   4,226 of 4,540 pairs — while UPDATE ran for hours several times a day.
4. Measured `Sep 09`: a saved position is 9–14 MB per pair on the PC (25 GB
   for 3,597 pairs), so shipping the PC's state to twenty machines every run
   was never an option; 1,008 pairs had no position anywhere.

**ROOT CAUSE** — two. The cloud had no memory between runs, so "update" could
only mean "start over"; and a store rule written for a PC-first world froze
the store the day the PC stopped measuring.

**WHY IT WAS NOT CAUGHT** — no test drove UPDATE end to end on the cloud path
and read what landed; the collector's tests asserted the old rule faithfully
(`test_a_locally_measured_pair_is_never_overwritten`) and passed while the
store stood still. The collect log said "skipped, already measured here" on
every run and nobody read it as a fault.

**COST** — none in money. Every UPDATE since Sep 05: hours of twenty machines,
almost nothing kept; a week of stale strategies under a fresh-looking screen.

**FIX** — this commit.
* `fast_grid.end_state` derives the engine's own resume state from the fast
  walk's trade list (open trade carried, not counted; streak carried; unrounded
  sums) — parity-pinned against `backtest_strategy(resume={})["state"]`.
* Every run saves each pair's position as a `state-<shard>` artifact (90
  days). `sweep_shard.continue_pair` (mode `update`) downloads the positions
  named in `state_runs`, fetches only the gap plus 300 bars of lookback, and
  continues every combination with `resume_state.continue_combo` — the same
  engine call the PC makes. Pinned equal to a single full run, streak included
  (`tests/test_cloud_continue.py`).
* harddev found the BOUNDARY BAR: a signal on the last tested bar enters on
  the first new bar and the engine's resume skipped it (65 trades against 66).
  `continue_combo` starts one bar early unless a trade exited on that bar or
  is still open across it. The PC's own update has the same gap (not fixed
  here; named).
* The collector keeps the NEWER measurement (`is_fresher`) and refuses only a
  stale or equal one; it records which run holds the latest positions per
  timeframe (`record_state_run`), and `_run_btupdate` dispatches
  `mode=update` with them. BACKTEST dispatches `mode=full`.
* The header tells UPDATE from FULL and counts continued vs measured-in-full;
  a continued tile reads "last test → now".

**GUARD** — `tests/test_fast_grid.py` (+31: end_state == engine state),
`tests/test_cloud_continue.py` (46: continued == full, boundary trade carried,
pack/unpack), `tests/test_cloud_update_mode.py` (19: shard, workflow,
dispatch, collector rule, state-run record, header), and the rewritten
`tests/test_cloud_collect.py` rules (fresher replaces, stale refused, marker
replaces only when fresher).

**PROVED** — `Sep 09, 2026`, on GitHub, 1 machine, 2 coins, 1h (times are
this PC's, UTC+8):
* FULL run 34357754670 (`9:33pm`, 4 min): 51,436 rows; both positions saved
  (`state-0`, 4,482,779 bytes — 0G-1h 27,720 combinations, 1000000BABYDOGE-1h
  24,948), last tested bar `Sep 09, 2026 8:00pm`; collected 2 pairs, 0
  skipped; state run recorded.
* UPDATE run 34358770484 (`9:42pm`): "saved positions from run 34357754670:
  2 pair(s)" then "no new bars since … 8:00pm — position kept, nothing
  written"; payload `mode=update, continued=2, fresh=0`; positions re-saved;
  the panel header read UPDATE with the continued count.
* UPDATE run 34360893326 (`10:01pm`, after the 9:00pm bar closed): both
  continued over ONE new bar — the tile read `Sep 09, 2026 8:00pm → Sep 09,
  2026 9:00pm` (screenshot taken while it ran); 51,436 rows; collected: 2
  pairs replaced as fresher, 0 skipped; `state_runs()` → 34360893326.
  BABYDOGE `mom6 th 0.2 tp 0.4 sl 0.3 flat`: 4,319 → 4,320 trades, 1,291 →
  1,292 wins, −$823.93 → −$823.63, bars 9,479 → 9,480; 0G's mom6 rows
  unchanged in trades, bars 8,565 → 8,566. The runner had 92.2 GB of disk
  free after the 4 MB download (the whole-market projection is ~12 GB).
* Measured cost of a continuation: **1.1 min per coin** for a one-bar gap,
  against **0.4 min per coin** for the full fast walk of the whole year on
  1h — the engine is called once per combination (27,720 calls), so UPDATE is
  now CORRECT and honest about its dates but not yet FASTER than starting
  over on 1h. Named here, not fixed here.
* Reading the re-saved positions found RCA-R (no boundary flag).

---

## RCA-2026-09-09-O — the download button promised 566,990 rows and the file held 1,184

**SAW** — found by pressing it. Operator: *"press and watch download csv in
backtest now"*. With `min win % 85 AND last 30 days` applied, the button read
**"download all (566,990) CSV"**.

**TIMELINE**

1. `Sep 09, 2026 3:02:56pm` — pressed the real link in the browser. The table
   showed 19 rows; the button offered 566,990.
2. `3:14:09pm` — it landed. From the press log:

       csv | asked: min_winrate=85.0 AND days=30 AND sort=profit AND desc=True
           | got: rows=1184 · window_hidden=816 | took 671.09s

   **1,184 rows**, not 566,990: the export re-measures at most
   `DAYS_CSV_MAX = 2,000` rows and then drops the ones the window's own figures
   fail — 816 of them here.
3. 566,990 is the count that clears 85% over each row's **whole history** —
   what SQL matched before the window re-measured anything.

**ROOT CAUSE** — the label was `total.toLocaleString()`, the SQL match count,
regardless of whether a window was on. A true number under a promise the file
cannot keep (`label-must-match-data`: a label must be DERIVED from the data it
describes).

**WHY IT WAS NOT CAUGHT** — every test of this download asserted what the file
CONTAINS (the window, the columns, the cap note). None compared the file with
what the BUTTON SAID it would contain. The two were never read together, which
is the same shape as RCA-G: each half right, the disagreement invisible.

**COST** — none in money. A button offering 480x the rows it can deliver.

**FIX** — **NOT YET COMMITTED**: the three files it touches (`api.py`,
`api.ts`, `StrategiesPanel.tsx`) are being edited by a concurrent session right
now — their row-level UPDATE / `pairbt` feature — so committing them would ship
a feature this session did not write or verify. The change is live in the
running build and verified in the browser, and the diff is kept at
`scratchpad/label-fix.patch`; it lands with whichever commit next carries those
files. The guard below is committed with this entry, so the rule is enforced
either way.

What it does: the label names the server's own cap when a days window is on
(`days_csv_max` in the payload, never a literal in the component) —
`download the window's top 2,000 CSV`. The hover text now also says it takes
MINUTES and that the browser may show 0 bytes at first, which is why that
matters (see below). The months path is untouched: `iter_rows` only re-measures
for `days`, so a months export really can deliver `total`.

**GUARD** — `tests/test_download_button_names_what_it_delivers.py` (7): the
server sends the cap it enforces, the label names it when a window is on and
names `total` when one is not, no literal cap is typed into the panel, the cap
is refreshed on every answer, the tooltip carries the measured 671s and the
0-bytes warning, and if `months` ever starts re-measuring the label must name
its cap too. All seven proven red against the previous panel.

**STILL NOT RIGHT, MEASURED AND NOT FIXED** — the download takes 11 minutes and
looks dead for the first four. From the same press, watching the browser's own
file on disk:

| time | browser file |
|---|---|
| 3:02:56pm pressed | — |
| 3:03 → 3:07:04 | **0 bytes** |
| 3:07:31 | 243,140 |
| 3:14:09 done | 668,984 |

The server was streaming the whole time (the worker held 369.6s of CPU); Chrome
only commits a download to disk in ~240 KB blocks. So the *server* stall of
RCA-N is fixed and the *experience* is not: 0 bytes for four minutes is
indistinguishable from broken. The only real cure is to stop re-measuring at
download time — store the window figures in the sweep (the first item under
"What would actually end it" below) — or to make the windowed export a
background job that writes the file and hands over a finished one. Neither is
done; the button now warns instead of pretending.

---

## RCA-2026-09-09-M — the run's date range was on screen and still nobody could tell whether UPDATE re-tests the whole year

**SAW** — *"the purpose of dates is so i know between what time are you
testing for example the last test for bitcoin was july 18 then i click update
backtest ... currently i can only see machine loading and im not sure maybe
they are testing jan 2025 to sept 2026, that way i know why its taking so
long"*. Third ask on the same subject in one day (after RCA-J).

**TIMELINE**

1. `Sep 09, 2026 05a092c775b` — the run's range was added as the TAIL of the
   grey one-line summary: `… 11/20 machine(s) finished · testing Aug 10, 2025
   8:00am → today (last 365 days)`. Small, grey, last.
2. `947c39fd140` — each tile got its own span, but written as `2,369 bars ·
   Aug 10, 2025 8:00am → Sep 09, 2026 12:00am` — the bar count first.
3. `1:15pm` — the operator, looking at run `34307921614` (dispatched from
   UPDATE, `days=365`), could not tell whether it was testing "Jul 18 → Sep 9"
   or the whole year. It WAS the whole year: the cloud shard has no watermark
   and `window(df)` cuts every pair at `DAYS + 30` (`sweep_shard.py:185`);
   `_run_btupdate` dispatches with `days=365` (`db_jobs.py:1763`);
   `cloud_sweep.py:599` says it in words: *"Cloud rows are a fresh
   full-history measurement"*. Nothing on screen said so.

**ROOT CAUSE** — the fact was present and unreadable: buried at the end of a
grey line, and without the one sentence that made it matter (GitHub cannot
continue from a coin's last test, so UPDATE re-measures everything — which is
WHY it takes hours).

**WHY IT WAS NOT CAUGHT** — the guard from RCA-J checked that the span exists,
not that a reader would find it or understand it. Presence is not
communication (label-must-match-data, last line).

**COST** — none in money. Three asks, one day, one fact.

**FIX** — this commit. The run's range is its own full-size line — `Testing
Aug 10, 2025 8:00am → Sep 09, 2026 1:15pm — the whole 365-day window plus 30
days of warm-up, from scratch. A GitHub run cannot continue from a coin's
last test, so BACKTEST and UPDATE both re-measure every bar in this range;
that is why a run takes hours.` The tile span is dates only; the bar count
moved into the note.

**GUARD** — `tests/test_shard_reports_its_dates.py` (+3): the header line is
full-size, derived from `days`, and the buried form is gone; the span is
dates only; and `window(df)` still takes nothing but the frame — if the cloud
ever learns to continue from a pair's last test, that assertion fails on
purpose so the sentence is rewritten with it.

---

## RCA-2026-09-09-Q — a row could be 73 bars stale with no way to move it, and the new button's job could not be watched

**SAW** — the operator, having searched #SW8Q96E6 and opened it: *"currently
the last backtest was Aug 24, 2026 4:00pm / can i have a button 'update' to
force update the backtest"*.

**TIMELINE**

1. `Sep 09, 2026` — #SW8Q96E6 is STBL 4h. Measured: its watermark stood at
   `Aug 28, 2026 12:00am` while the store held candles to `Sep 09, 2026
   4:00am` — **73 four-hour bars** measured by nobody, with no button on the
   screen that could move one pair.
2. The new `pairbt` job is pressed for real. The measurement lands: watermark
   `Aug 28` → `Sep 09 4:00pm`, **8,774 rows**. The REINDEX dies:
   `OperationalError: database is locked`.
3. Pressed through the API end to end. The route answers `started: true` —
   and `/api/jobs/pairbt` answers **`unknown job kind: pairbt`**.

**ROOT CAUSE** — three, each only visible by running it:

* No per-pair measure existed at all. The market grid moved to GitHub, and
  nothing was left that could bring ONE pair forward.
* `rows_index._connect` waits 60 s for the write lock, but a full index
  rebuild holds it far longer (`rows_winrate` alone takes 912 s), so a
  concurrent rebuild left the row file current and the SCREEN on August's
  numbers under a job that said it had finished.
* `api.JOB_KINDS` was a hand-written tuple of four. The job started and the
  panel could never follow it — a button that works and cannot be watched.

**FIX** (this commit) — `db_jobs._run_pairbt` measures the PAIR (one row file
and one watermark per coin+timeframe; moving one row alone would leave the
pair's others behind a watermark that claims otherwise), resuming from the
watermark with `thresholds=3` to match `grid_from_store` — a mismatched K
makes the two paths reset each other's store. The index is retried three
times, and when it still cannot be written the job checks
`rows_index.stale_pairs` and says *"waiting on the index — the row updates
when the catch-up runs"* rather than "FAILED", because the pair really is
queued. A failed measure goes on the pending ledger, so RESOLVE PENDING can
retry it. `JOB_KINDS` is now derived from `db_jobs.FILES`.

**WHY IT WAS NOT CAUGHT** — the first two could not be caught by any test that
did not RUN the thing: the lock needs a concurrent rebuild, and the stale
watermark needs the real store. The third is worse — it was a hand-maintained
list duplicating `FILES`, the classic two-places-for-one-fact, and every
existing job kind was in it so nothing looked wrong. Only pressing the button
end to end through HTTP showed it.

**COST** — none in money. One row sat 73 bars stale, and any future job kind
would have been unwatchable the same way.

**GUARD** — `tests/test_row_update_button.py` (14), including
`test_every_job_kind_can_be_watched` (derives the set from FILES),
`test_a_locked_index_says_WAITING_not_FAILED`, and
`test_the_threshold_count_matches_the_sweep`, which fails if the sweep's K
moves away from this button's.

## RCA-2026-09-09-L — "pending" counted the clock and the never-done, so neither number could ever reach zero

**SAW** — the operator, after a week of chasing counts that came back on their
own: *"pending only means these are the candles that had problem during the
update candles or download candle, resolve mean you will restart or resume
where it crash / same as on backtest"*. Before that, on the same day:
*"does the resolve pending 117 shows if the bar is not updated?"* — no, it did
not, and finding that out took reading the emitter.

**TIMELINE**

1. `Sep 06, 10:55pm` — the candle count is driven to **0** after three
   RESOLVE presses (5,152 + 1,722 + 252 pairs, 161,373 bars, zero errors).
2. `Sep 06, 9:33am` — it reads **5,095** again. Nothing failed. "Behind" is
   measured against the CLOCK, so a 15m pair is behind fifteen minutes after
   any run; 5,095 of ~5,190 stored pairs qualified, a median 12.6h old.
3. `Sep 09` — the BACKTEST count reads **117**: pairs with no measurement
   file, whether a run had ever tried them or not. A pair measured last week
   with 500 new bars since is invisible to it — it has a file.
4. Both numbers were therefore un-zeroable by design, and RESOLVE acted on
   them: the candles button queued **5,192 pairs on a store where nothing had
   failed** — a whole-market update wearing the word "resolve".

**ROOT CAUSE** — "pending" was defined as *not finished* rather than *broken*,
and the real failures had nowhere durable to live. `db_download.lost.json` is
rewritten at the end of EVERY download ("a clean run empties it"), so a
whole-market run's losses vanished the moment somebody fetched one coin, and a
shard's named losses reached the LOGS panel only — no button would ever retry
them.

**FIX** (this commit) — `tradingagents/pending_ledger.py`: a durable per-kind ledger of pairs
that a run TRIED and FAILED, cleared when the pair actually succeeds (by any
run — the download, the local sweep, or `collect_into_store` landing fleet
rows). Both RESOLVE buttons now act on exactly that. Everything else is still
reported, under its own name: `behind` (freshness, the candle autopilot's job),
`never_measured`, `too_short`, `unfixable`.

**WHY IT WAS NOT CAUGHT** — they could not: every test asserted the
OLD definition faithfully, and 17 of them failed the moment the meaning
changed. This was a specification defect, not a coding one. The tests were
rewritten to the new meaning rather than deleted, because they carry incident
knowledge (the busy-run refusal that lied, the pointless all-delisted
dispatch) that is still live.

**FOUR BUGS THE HARDDEV LOOP FOUND IN THE FIX ITSELF**

1. The sweep records `CETUS_USDT` while `collect_into_store` clears `CETUS` —
   nothing would ever come off the books, so every landed pair would stay
   pending for ever. Normalised inside the ledger, not at each call site.
2. The resolve route answered `pending: 0` while dispatching twenty machines
   for one failed pair: the success response still carried the never-measured
   tally (label-must-match-data).
3. The ledger READ that builds the RESOLVE queue was unguarded — an unreadable
   file would have killed the whole download job before it fetched a pair.
4. The guard test that should have caught (3) only inspected the FIRST
   `pending_ledger` use in each function; it now checks every one, and was
   proved to bite by removing the guard and watching it fail.

**COST** — none in money. In time: three RESOLVE presses over 42 minutes on
Sep 06 fetched 6,115 pairs to move a number that was never a problem list, and
several rounds of "why is it still 5,095".

**GUARD** — `tests/test_pending_ledger.py` (17), plus the rewritten
`tests/test_resolve_pending_backtest.py` (15) and
`tests/test_resolve_pending_button.py` (13).

## RCA-2026-09-09-N — the CSV download sat at "0 B" and wrote nothing, because its query had to sort 566,990 rows before the first one

**SAW** — *"so why does it not download? its still downloading 0B meaning it
does not write"*. Filter: `min win % 85 AND last 30 days`, no coin, by profit.

**TIMELINE**

1. `Sep 09, 2026 ~1:30pm` — pressed download. The request was real and in
   flight: `.run/api.log` has `GET /api/strategies.csv?sort=profit&
   min_winrate=85&days=30&desc=true 200 OK` (uvicorn logs a StreamingResponse
   at its START).
2. Measured on that exact URL: `0.33s` status 200, `content-length=None`,
   chunked; `0.33s` **first byte** — the header row; then **no first data row
   after 600 s**, when the probe gave up. The browser had a header and nothing
   else, so it showed 0 B. The operator was exactly right.
3. The press log could not answer the question either: it only wrote a line
   when the stream **ended**, so a download in flight was invisible.

**ROOT CAUSE** — the export's index choice. `export_plan` seeks the win-rate
index whenever the matches fit under the PAGE's cap (`_winrate_seek_cap()` =
**12,000,000** once `rows_wr4` exists), and 566,990 matched. But that seek
returns rows in **win-rate** order, and the request asked for **profit** order,
so SQLite must read and sort **every match** before emitting row 1 — and a
download has no `LIMIT` to bound that sort. The page never suffers it because
its sort stops at one screenful. Three plans, measured on this store
(51,943,352 rows, mechanical disk):

| plan | query plan | first row |
|---|---|---|
| `INDEXED BY rows_wr4` (what it did) | SEARCH + **USE TEMP B-TREE FOR ORDER BY** | **none after 600 s** |
| no index named | SCAN using `rows_profit` | 108.55 s (that index has no `winrate`, so every candidate is a random row read) |
| `INDEXED BY rows_pr2` | SCAN in profit order, `winrate` tested **inside** the index | **5.54 s** (25 rows in 7.57 s) |

Two amplifiers behind it: the windowed batch was **250 rows** re-measured
*whole* before any were yielded (up to 250 different candle files off a
mechanical disk), and `_DIRS_CACHE` held 24 entries and called `.clear()` when
full, so one batch wiped every cached signal repeatedly.

**WHY IT WAS NOT CAUGHT** — this is the third face of the same thing. RCA-A
proved the export SENDS the window; the Sep 03 rule proved the export makes the
same index choice as the page. Nobody asked **how long until the first byte**.
`test_the_download_is_checked_without_being_RUN_first` even asserts the route
must not pull a row before streaming — so by design no test ever waits for one.
And the press log, one hour old, still only recorded completions.

**COST** — none in money. Every windowed download with a broad win-rate floor
was unusable, and the browser gave no clue which.

**FIX** — this commit.

* `rows_index.EXPORT_SEEK_MAX = 20,000` — a download narrows the seek cap, but
  **only when the seek's own order is not the asked order** (`key != "winrate"`);
  ordering BY win rate still seeks, because there the seek needs no sort at all.
* `rows_index.WINDOW_CSV_STEP = 25` — the windowed export yields in the size
  the page has proven answerable (`api.DAYS_ROW_MAX` 50, `WINDOW_GROUP_MAX` 25),
  so bytes flow continuously instead of after 250 re-measurements.
* `_DIRS_CACHE` evicts the oldest ONE entry instead of clearing itself.
* `screen_log` writes a **`csv START`** line, so a download in flight is
  visible and "started and never finished" reads differently from "never
  pressed".

Measured end to end after, same filter: **first row 2.2 s** (was never), 25
rows 2.8 s, 100 rows 9.1 s, 500 rows 133 s — growing the whole time.

**GUARD** — `tests/test_windowed_download_streams.py` (10): a download never
picks a plan that must sort every match, ordering by win rate keeps the seek, a
selective floor still seeks (the Sep 03 rule holds), the windowed step is no
bigger than the page's proven slice, an unwindowed export still uses big
batches, the cache evicts one and keeps the newest, and the `csv START` line is
written before the first row.

---

## RCA-2026-09-09-K — the Stored-strategies panel re-ran the operator's filter 8 times a minute, forever, with nobody touching it

**SAW** — nothing. That is the point. Found by the press log the operator had
asked for **ten minutes earlier** (*"whenever i clicked apply filter and click
download csv you should be getting the logs of it so you can see the status"*),
by reading `~/.tradingagents/screen.log` after pressing Apply once.

**TIMELINE**

1. `Sep 09, 2026 12:54pm–1:00pm` — Apply pressed **once** with the four chips.
   The log holds **39 identical `apply` lines** in those six minutes, each
   `rows=9 · window_hidden=16 · took ~3.4s`.
2. Isolated it: page open and idle 60 s → **8 new lines**. Page closed 45 s →
   **0**. So the browser, not a job.
3. Each of those re-measured 25 rows from this PC's candles, on the machine
   that is measuring the market, and held one of the app's **four** browser
   lanes while it ran — the same lanes whose exhaustion made the table wait
   five minutes in RCA-I.

**ROOT CAUSE** — the catch-up refresh keyed on the response object:

    }, [idx, load]);      // idx = d.index, a NEW OBJECT every answer

`setIdx(d.index)` runs on every response, so `idx` changed identity every time,
the effect re-fired, its 5-second timeout re-armed, and the request went again.
The early return (`behind === 0`) could never stop it, because on a store being
swept the index is never caught up — 4,557 of 4,605 pairs at the time. **An
object from a response is not a dependency, it is a metronome.**

**WHY IT WAS NOT CAUGHT** — it produces no error, no wrong number and nothing
on screen; only a log of presses makes it visible, and there was none until
this morning. Nothing in the suite reads a dependency array.

**COST** — none in money. 3.4 s of candle re-measurement every ~8 seconds for
as long as the panel was open, and one browser lane permanently gone.

**FIX** — this commit. `catchingUp` is a **boolean**, so its identity is
stable; the refresh is a `setInterval` at **60 s**, not a re-armed 5-second
timeout. The one-shot 503 retry beside it was already correct (keyed on a
string) and is untouched.

**GUARD** — `tests/test_panel_does_not_refetch_forever.py` (5): the refresh
keys on the boolean, **no effect anywhere may depend on `idx`** (proven red
against the old file — it finds `}, [idx, load]`), the interval is ≥ 30 s, a
background load still shows no spinner, and the 503 retry stays a one-shot.

---

## RCA-2026-09-09-J — 17 of 20 machine tiles never showed which dates they were testing

**SAW** — *"so why does it not show what dates its testing like machine 7
Aug 11, 2025 12:00am → Sep 08, 20"*. Machine 7's tile had a date span;
machine 18's said only `testing · USTC 4h: rule 39/120 (fisher)`.

**TIMELINE**

1. `Sep 09, 2026` earlier — the operator asked *"i dont see what dates are
   being tested like is aug 3 - sept 27 being tested?"*. Commit `05a092c775b`
   put the span **inside the note**, written once per pair, right after that
   pair's candles load.
2. The per-rule report five lines below overwrites that note **120 times per
   pair** (`{coin} {tf}: rule {si}/120 ({sig})`), and `Reporter` publishes at
   most once every **45 seconds**.
3. So a tile showed dates only if its 45-second tick landed in the instant
   between those two lines. Measured on run `34307921614` at `12:46pm`:
   **3 of 20 machines had dates, 17 did not** — machine 18 among them, while
   it was demonstrably working (USTC 1h rule 1 → USTC 4h rule 39 and +36,520
   rows in 45 s).

**ROOT CAUSE** — one field carrying two facts. The span and the rule counter
shared `note`, so the frequent writer erased the rare one.

**WHY IT WAS NOT CAUGHT** — `05a092c775b` changed three files and added
**zero tests**. Nothing asserted that the fact survives the next report, which
is the only thing that mattered. Same shape as pattern 3 below: the layer the
operator reads was never the thing under test.

**COST** — none in money. The operator could not tell a working machine from a
stuck one, twice.

**FIX** — this commit. `span` is its own key in the shard payload and rides
**every** report while a pair is measured; it is explicitly cleared (`span=""`)
on "downloading candles", on "N pair(s) lost so far" and on "done", so a tile
never prints one pair's name beside another pair's dates. The tile renders it
on its own line, so the note's `truncate` cannot eat it.

**GUARD** — `tests/test_shard_reports_its_dates.py` (11): every `report(...)`
in the shard passes a span (AST-checked, so a new call site cannot forget),
the per-rule one passes the pair's real span, the three non-pair reports clear
it, no note contains `→` any more, the tile renders it on its own line, and an
old run with no `span` key renders nothing.

---

## RCA-2026-09-09-I — the filtered table waited five minutes behind four `/api/cloud/status` calls that never came back

**SAW** — Apply pressed with the four chips; the button read **"searching
306s"** and the table never changed. No error anywhere. Found while proving
RCA-G in the browser.

**TIMELINE**

1. `Sep 09, 2026 11:56am` — Playwright's network list: `/api/cloud/status`
   requests **95, 104, 112, 119** in flight with no answer; every other call
   200.
2. Measured straight at the API: `GET /api/cloud/status` **200 in 216.3 s**.
   The panel asks every **4 s**.
3. `webapp/src/lib/api.ts` had gained `MAX_LANES = 4` that morning (so a page
   switch stays instant). Four hung status calls held all four lanes; the
   filtered `/api/strategies` request never left the browser. `/api/health`
   direct: 0.4 s. The API was healthy; the page was dead.

**ROOT CAUSE** — `cloud_status` ran `cs.available()`, `cs.status(run)` and
`cs.live_progress(run)` — `gh` plus `git fetch` plus a `git show` per shard —
inside the request, on every 4-second poll. The comment above it said CACHED;
only `working_run` was.

**WHY IT WAS NOT CAUGHT** — RCA-A fixed the identical fault in
`/api/backtest/logs` five hours earlier and the fix stayed local to that
module. No test bounds a polled route's wall-clock, and nothing says which
routes shell out. The same shape, in a second route, the same day.

**COST** — none in money. Every filter on the page unusable while GitHub was
slow; the operator's proof of RCA-G could not be taken for 20 minutes.

**FIX** — this commit. `tradingagents/slow_cache.BackgroundValue`: one
background thread reads, the request answers with the last value or says
"reading GitHub in the background", a failure is a value too. `cloud_status`
uses it (`CLOUD_STATUS_TTL = 30 s`); the panel prints "checking GitHub…" for
that first answer instead of "GitHub is not available", which would be a false
label. Measured after: first call **<0.5 s**, then the cached answer.

**GUARD** — `tests/test_cloud_status_never_waits_on_github.py` (9): the first
call answers at once, one read at a time however often the panel polls, a
failure is cached, a stale value is served while the refresh runs, the route
holds no slow call, the pending answer keeps the panel's shape, the panel does
not call a first read "not available".

---

## RCA-2026-09-09-G — "Winrate 90% or better" over a column reading 89.47, 86.36, 80.00, 75.00

**SAW** — *"so why are you showing below 90% winrate when the filter is: Past
30 days AND flat sizing only AND Winrate 90% or better AND TP at least as wide
as SL"*, with a screenshot. Also `TypeError: Failed to fetch` in red above the
table — that one was the API being restarted underneath the page at `8:05am`
by another session, not this fault.

**TIMELINE**

1. `Sep 09, 2026` — four chips applied. The store's SQL floor `min_winrate=90`
   ran on each row's **whole-history** win rate, the only one the index holds.
   Every row on the page cleared it.
2. The 30-day window then re-measured each row from the candles and the page
   printed the window's own figures. #CGXLRJML GPNSTOCK 30m stoch14: **57
   trades, 51 W / 6 L, 89.47%** over `Aug 14, 2026 9:30pm → Sep 05, 2026
   3:00am`. #7ZZE2ANU ZRO 4h gmma: **4 trades, 3 W / 1 L, 75.00%**.
3. Nine rows on screen; **7** printed a win rate under 90 beside a chip
   saying "90% or better". Nothing compared the window's figure with the floor.

**ROOT CAUSE** — the floors were applied once, in SQL, to the whole-history
figures, and the window re-measure that overwrote the printed figures never
re-checked them. `api.strategies` and `rows_index.iter_rows` both had the gap.

**WHY IT WAS NOT CAUGHT** — `tests/test_days_window.py` proved the window
re-measures and the page prints the window's figures; the floor tests proved
SQL applies the floor. Each layer was right alone. No test set a floor AND a
window together and read the column. Same shape as RCA-D: the layer the
operator touches — chip beside column — was never the thing under test.

**COST** — none in money. A page that said 90% and showed 75%.

**FIX** — this commit. `rows_index.window_floors` re-applies win %, trades and
profit floors to the window's own figures, on the page (days AND months) and in
the CSV. Cut rows are **counted**: `window_hidden` in the payload, a warning
sentence in the caption, and a `WINDOW FLOOR:` last line in the file. Rows the
window could not restate are kept and marked, as before. What is NOT searched,
said plainly: a row under 90 over its whole history but over 90 inside the
window is never fetched — the window re-measures a page chosen on whole-history
figures, and re-measuring all 51,786,620 rows is ~54 days of CPU.

**GUARD** — `tests/test_window_floors_apply_to_the_window.py` (8): the
screenshot's nine win rates lose exactly seven, the floor is inclusive at 90.00,
trades and profit floors follow the window, an unrestated row is kept, both
callers apply it, the CSV writes the count, the caption names it.

---

## RCA-2026-09-09-H — the delete ran as a thread inside the API, so an API restart killed it; and one pair per lock gap

**SAW** — the job's progress line vanished mid-run ("none"); on the re-press
the button was refused with "the row index is being written by another
process" a moment after a probe had found the lock free.

**TIMELINE**

1. `Sep 09, 2026 7:55am` — first press; the delete ran in a thread of the
   API process.
2. `8:03am` — another session restarted the API. The thread died at coin
   **2 of 29**; the record went with the process.
3. `8:36am–11:31am` — the standalone indexer (`python -m
   tradingagents.rows_index`, pid 22424) committed **15 pairs in 3.5 hours**
   (4,541 → 4,556 indexed), holding the write lock ~95% of the time. The
   re-press probed the lock, found a gap, and by its first `forget_pair` the
   indexer had the lock again: **409**, nothing done.

**ROOT CAUSE** — two design choices. (1) Hours-long store work inside a
process that is restarted many times a day. (2) Taking the lock per pair,
which can only ever win one pair per gap against a writer that holds it 14
minutes at a time.

**WHY IT WAS NOT CAUGHT** — no test restarted the host process or held the
lock from a second connection during a run. The index builds had already
learned both lessons (detached child, one statement) and the delete did not
copy them.

**COST** — none in money. Four presses over four hours removed 24 files.

**FIX** — this commit. `storage_months` runs every delete as a DETACHED
process (`--run <kind> <through>`, same flags as the index builds) with a
progress file beside the store; `progress()` reads the file and a dead pid
reads as "died before finishing — press again", never RUNNING.
`rows_index.forget_pairs` removes every pair in ONE transaction, waiting up
to 30 minutes for the lock and holding it until done; if it fails, nothing
is deleted and no file goes.

**GUARD** — `tests/test_storage_months.py::test_the_worker_is_a_detached_process_and_a_dead_one_says_so`,
`::test_the_index_pairs_go_in_one_transaction`,
`::test_forget_pairs_waits_for_the_lock_then_takes_it`,
`::test_a_failed_index_delete_keeps_every_file`.

---

## RCA-2026-09-09-F — DELETE 29 DELISTED counted candle files the first press had already removed

**SAW** — after the interrupted press below, the button still read
**"97 candle files"** while 24 of them were gone from the disk (93 left).

**TIMELINE**

1. `Sep 09, 2026 7:55am` — press one removed AIINU's 4 candle files (and 20
   more files) before it was killed.
2. `8:36am` — the button, its hover text and the confirm all said 97 candle
   files, 217 MB. The disk had 93.

**ROOT CAUSE** — `storage_months.delisted_report` counted from
`candle_index(scan=False)`, a CACHE that the delete job refreshes only at its
END. A job killed part-way leaves the cache listing files it removed.

**WHY IT WAS NOT CAUGHT** — the tests built the index and the files together
and never made them disagree. Pattern 3 below: the layer the operator sees (the
count) was derived from a cache, and nothing asserted cache == disk.

**COST** — none in money. A wrong number on a delete button.

**FIX** — `b5935292fdde`. The report stats each DELISTED entry's file (dozens,
never thousands) and skips the ones that are gone.

**GUARD** — `tests/test_storage_months.py::test_the_report_does_not_count_candle_files_that_are_already_gone`.

---

## RCA-2026-09-09-E — DELETE 29 DELISTED deleted the files under 53,132 rows the index still held

**SAW** — pressed for real: `done` advanced (1 of 29 coins in 7 minutes) while
`rows_removed` stayed **0** and `errors` stayed **0**. Then the job record
vanished — another session restarted the API at `8:03am` and the thread died.

**TIMELINE**

1. `7:55:05am` — pressed via the button's own route with every job idle.
   AIINU's 4 candle files went at once (5.9 MB).
2. `7:55–8:02am` — every `rows_index.forget_pair` waited its 60 s
   `busy_timeout` behind `python -m tradingagents.rows_index` (pid 22424, up
   since 6:22am, inside one pair's `INSERT` for over an hour), got
   `database is locked`, and `_missing_ok` returned **0** as if it had worked.
3. The caller read 0 as success and called `discard_pair`: AIINU's and ASP's
   rows files and resume states were deleted — **5,652 + 47,480 = 53,132 rows**
   left in rows.db with no file behind them, exactly the orphan the
   index-first order was written to prevent.
4. `8:03am` — API restarted by another session; job gone at coin 2 of 29.

**ROOT CAUSE** — `forget_pair` used `_missing_ok`, a READER's wrapper that
turns any `sqlite3.Error` into a default. On a write path a lock is a failure,
not "nothing there".

**WHY IT WAS NOT CAUGHT** — the tests ran against an idle temp database; none
held the write lock from a second connection. Pattern: the failure path (the
venue raises, the lock is held) was never driven.

**COST** — none in money. 53,132 rows of two delisted coins shown as stored
with no files; a re-press finishes them (they are still in the pairs table).

**FIX** — `716098723f3e`. `forget_pair` raises on a lock; `_remove_pair`
names a pair whose index delete failed and KEEPS its files; a results or
delisted delete probes the lock first (`rows_index.write_available`) and
refuses with the reason. Then `c5ad728b746a`: the delisted delete no longer
waits for a candle download, which skips delisted symbols by the same test.

**GUARD** — `tests/test_storage_months.py::test_forget_pair_raises_behind_another_writer_instead_of_saying_zero`,
`::test_a_failed_index_delete_keeps_the_pairs_files`,
`::test_a_results_or_delisted_delete_refuses_while_another_process_writes_the_index`.

---

## RCA-2026-09-09-A — the CSV download threw away the table's 30-day window, and the page around it read "Internal Server Error"

**SAW** — *"check my current filter why is this having internal server error
once i open the csv file did you not still fix the bug? even i use harddev"*.
Filters on screen: sizing flat, min win % 90, TP > SL, last days 30.

**TIMELINE**

1. `Sep 09, 2026` — filters applied. The table showed **2,001 rows**, window
   `Jul 29, 2026 12:00am` → `Sep 05, 2026 5:00pm`.
2. Clicked *download all CSV*. The link sent no window, so the server measured
   every row's whole history: **42,420 rows / 17,289,982 bytes**, in a file
   still named `strategies-wr90-tp-over-sl-last30d-flat-profit.csv`. The
   windowed file is **876,283 bytes**.
3. While that ran, the app's own calls starved. Measured with one download in
   flight: `/api/health` **200 in 23.8s**, `/api/jobs` **200 in 2.4s**,
   `/api/backtest/logs` **TIMED OUT at 47.0s**.
4. `/api/backtest/logs` was already the slowest thing on the page —
   **82.26s** with the cloud half, **0.21s** with `?cloud=false` — and the LOGS
   panel polls it every 30 seconds, so one was permanently in flight.
5. Next's rewrite proxy turns a timed-out upstream call into the literal words
   **Internal Server Error**. That is what the operator read. The CSV itself
   answered 200 every single time.

**ROOT CAUSE** — three, meeting at one click:

* `strategiesCsvUrl` in `webapp/src/lib/api.ts` **declared** `days` and
  `months` in its argument type, the panel **passed** them, and the function
  body never wrote either into the `URLSearchParams`. Kit item G: the download
  has to carry the same slice as the table.
* `backtest_logs._cloud_errors` shelled out to `gh run list`, then `git fetch`
  plus one `git show` **per shard**, inside the request, on every poll.
* `rows_index.iter_rows` re-measured rows in batches of up to 250 — each row
  ~0.09s of pure Python holding the interpreter lock, so ~22s a batch during
  which nothing else in the process could answer.

**WHY IT WAS NOT CAUGHT** — a test written for this exact fault on Sep 03,
`test_the_download_link_carries_the_window_too`, asserted that `api.ts`
contained **two** `p.set("days"` lines. It did — **both inside `strategies`**,
which carried the block twice, while the download builder had none. **A count
is not a location.** Nothing tested the endpoint's wall-clock either, so an
82-second poll was invisible to the suite.

**COST** — no money. The file held 21× the rows with the wrong profit, wins,
losses and win rate, under a filename claiming 30 days; the page looked broken
while the store was healthy.

**FIX** — `65e8205cf83`.

* the builder writes `months`, else `days`; the duplicate block in `strategies`
  removed
* the GitHub read moved into one background thread
  (`_refresh_cloud_in_background`), request answers from cache — **0.61s** first
  call saying "reading GitHub in the background", **0.00s** after, **0.14s**
  once the thread lands with `run=34285739222 shards=20`. Failures cached too:
  a `gh` that is timing out will time out again a second later.
* `market_sweep.window_rows(..., breathe=)`, passed only by the export
  (`rows_index.EXPORT_BREATHE_S = 0.002`); the page's own window call passes
  nothing, because it re-measures ten rows inside a browser's 30-second limit.

Measured through the running API with one download in flight:

| | before | after |
|---|---|---|
| `/api/health` | 23.8s | 3.8s |
| `/api/jobs` | 2.4s | 2.0s |
| `/api/backtest/logs` | TIMED OUT 47.0s | 3.7s |
| the CSV | 78.5s, 200 | 56.0s, 200, 876,283 bytes |

Confirmed in the operator's own browser: the href now reads
`/api/strategies.csv?sort=profit&...&days=30&desc=true`.

**GUARD**

* `test_a_filter_the_builder_DECLARES_reaches_the_query_string` — reads the
  builder's declared fields and asserts each one is used INSIDE that function.
  Proven red against the old file (`days`, `months`).
* `tests/test_logs_panel_never_waits_on_github.py` — the first call cannot wait
  on GitHub, only one read runs at a time, a failure is cached, an unreadable
  cloud never reads as "no errors", and the export must hand the lock back.

---

## RCA-2026-09-09-B — a real demo loss was missing from the trade history

**SAW** — *"why is #YDMRLEZ5 has 1 lose and it does not reflect in demo history
trades"*.

**TIMELINE**

1. `Sep 07, 2026 5:01pm` — KITE 1h squeeze, paper book, stopped out, **-3.19**.
   The row was in the ledger the whole time.
2. `HistoryPanel` asked `/api/ledger` for the newest **200 rows**, then picked
   out `enter`/`exit` **in the browser**.
3. The ledger held **3,666 rows**: **2,868 `gate_blocked`**, **552 `blocked`**,
   **169 `stale_skip`**, and **12** actual trades.
4. The newest 200 rows spanned 23 hours and held **2 of those 12**. The exit
   the operator was asking about sat **640 rows from the end**, so it never
   arrived in the browser at all.

**ROOT CAUSE** — a `.filter(...)` in a component over a list the server had
already cut with `limit`. A filter cannot recover rows that never arrived.

**WHY IT WAS NOT CAUGHT** — every test drove the API, which was correct. None
drove the component's own fetch, so the truncation happened one layer above
everything under test.

**COST** — no money. A winning-and-losing record read as if the loss had never
happened, which is the worst possible thing for a page whose job is trust.

**FIX** — `07e98369cb6`. `/api/ledger` takes `actions=enter,exit` and does the
filtering in the query, and returns `matched` beside `total` so "no trades" is
distinguishable from "no ledger".

**GUARD** — `tests/test_history_shows_the_trades_not_the_refusals.py`, plus the
CLAUDE.md rule *FILTER WHERE THE DATA IS, NEVER AFTER A WINDOW HAS BEEN TAKEN*
and the memory note `filter-where-the-data-is`.

---

## RCA-2026-09-09-C — the banned date stamp came back, and the test that bans it passed

**SAW** — `2026-09-07 17:01` on every row of the trade-history table. The
project's format is `Sep 07, 2026 5:01pm`, asked for four times.

**TIMELINE**

1. `Sep 09, 2026` — every row of the trade-history table printed its time as
   `2026-09-07 17:01`. The one allowed form is `Sep 07, 2026 5:01pm`.
2. The table built a `Date` out of the row's seconds and sliced its ISO string,
   instead of calling `fmtWhen`.
3. `test_the_browser_uses_one_date_format_everywhere` passed the entire time —
   **1** pattern in the guard, `.toLocale`, and **0** of the ways this file
   actually broke the rule.
4. This was the **4th** time the date rule has been broken since `Aug 21, 2026`.

**ROOT CAUSE** — the printed stamp was hand-rolled instead of calling
`fmtWhen`, the only TypeScript formatter allowed.

**WHY IT WAS NOT CAUGHT** — the guard greps for `.toLocale` and nothing else.
It knew **one spelling of one way** to break the rule. The rule was never
wrong; the check was narrow.

**COST** — none in money. It is the fourth time this rule has been broken.

**FIX** — `07e98369cb6`, with the rule written down in `c15a355c49b`. The table
calls `fmtWhen`.

**GUARD** — `test_the_browser_uses_one_date_format_everywhere` and
`tests/test_history_shows_the_trades_not_the_refusals.py` now also reject a
`Date` built from seconds, while still allowing `toISOString().slice(0, 10)`
for a date INPUT's value, which is not a printed timestamp. Confirmed the
widened guard fails on the old file.

**Rule this bought:** *A GUARD IS ONLY AS WIDE AS ITS PATTERN.* When a
MANDATORY rule is broken again, fix the code AND widen the guard in the same
commit, then prove the widened guard red on the old file. Memory note
`widen-the-guard-not-just-the-fix`.

---

## RCA-2026-09-09-D — the Candles page answered 422 on every load

**SAW** — the download-history panel on Candles was empty on every load. Found
`Sep 09, 2026 6:30am` by restarting localhost and reading the browser's failed
requests; nothing else reported it.

**TIMELINE**

1. `Sep 09, 2026` — every load of the Candles page asked
   `GET /api/candles/download-history?limit=20`.
2. FastAPI answered **422** `{"loc": ["query", "symbol"], "msg": "Field
   required"}` — a field the browser had no reason to send.
3. The panel rendered empty and the page otherwise looked fine, so this ran
   unnoticed. **0** tests asked whether the paths the client calls exist; the
   web app calls **72** of them.

**ROOT CAUSE** — `@app.get("/api/candles/download-history")` had drifted off the
function it decorates. A helper, `_lost_kind_on(got, symbol, tf, texts=None)`,
was inserted BETWEEN the decorator and `download_history`, so FastAPI
registered the **helper** as the endpoint and its `got`, `symbol` and `tf`
arguments became required query and body fields. `download_history` was left
undecorated — a route that existed in the source and not in the app.

**WHY IT WAS NOT CAUGHT** — nothing asserted that every path the browser calls
is actually served, let alone by the function meant to serve it. A decorator can
move one line and the source still reads correctly.

**COST** — none in money. One panel of the app returned nothing.

**FIX** — `5fdbd8efb71`. The decorator moved onto `download_history`; the
helper is a plain function above it, with a comment saying why the order
matters.

**GUARD** — `tests/test_every_client_path_is_served.py` — every `/api/...` path
the web app calls resolves to a route, and each route's handler takes only
parameters a browser would send.

---

## Patterns that keep repeating — read this list before writing a test

Four separate bugs above share three shapes. If a fix matches one, the test
needs to be written differently:

1. **A count is not a location.** `src.count("p.set(\"days\"") == 2` passed
   while the function that mattered had zero. Assert inside the function, the
   route, the branch — never across a file.
2. **A guard is only as wide as its pattern.** A grep for `.toLocale` cannot see
   a `Date` sliced by hand. When a rule breaks twice, the check was narrow: widen
   it in the same commit and prove it red on the old file.
3. **Test the layer the operator actually touches.** The API was right and the
   component still showed the wrong thing; the route was right and the decorator
   published a helper. Drive the entry point, in the state it will run in.
4. **A polled route must never do the slow thing inside the request.** Two
   routes took the page down the same way one day apart (A and I): a panel
   polls every few seconds, the route shells out to `gh`/`git` for 82 s and
   216 s. `tradingagents/slow_cache.BackgroundValue` exists so the third one
   does not have to rediscover it. Before adding a poll, ask what the route
   costs COLD.
5. **A guard asserts WHAT, never WHERE.** `"SHORT AND PLAIN, both" in body` and
   `"function CopyableId(" in StrategiesGrid.tsx` both went red on an edit that
   changed no behaviour at all (H) — an address-pinned check is wrong in both
   directions: false red on a refactor, false green when the thing moves. Name
   the parts, read the file that declares the behaviour, and assert every caller
   uses it. This is pattern 1 with the sign flipped.

---

# The Stored-strategies filters: why 31 fixes in 14 days

Operator, Sep 09, 2026: *"give me the root cause because this has been an
issue for 1month already / you cant make the filters right what is the root
cause"*. Fair question, and the answer is not "each of those was a separate
mistake". Measured:

| week | `fix(strategies|filters|csv|balanced)` commits |
|---|---|
| Aug 19 → Aug 26 | 0 (the panel had no filters yet) |
| Aug 26 → Sep 02 | **17** |
| Sep 02 → Sep 09 | **14** |

31 fixes against 19 features. Two root causes account for 18 of the 31, and
they are both structural — not carelessness in any one commit.

## Cause 1 — every filter COMBINATION needs its own hand-built index (14 of 31)

The store is **51,943,352 rows** of SQLite on a mechanical disk. A combination
with no index carrying it must read candidate rows off the platter to test the
rest, and the 20-second budget refuses it: the operator sees HTTP 500, or a
503 that repeats forever, or an empty table.

So each combination only works if somebody hand-wrote an index for it. There
are **FOUR** indexes for the single win-% box, each added after a new box was
placed beside it:

| index | columns added | measured before it existed |
|---|---|---|
| `rows_winrate` | winrate, trades, id | — |
| `rows_wr2` | + profit DESC | ranking by profit beside the floor |
| `rows_wr3` | + sizing | **3,071.7 s** → 0.34 s (win % 80 + flat + 100 trades) |
| `rows_wr4` | + tf, signal, tp, sl, coin | **358.2 s** (win % 90 + TP≥SL + crypto) |

`rows_wr4` is the endless 503 the operator read as *"the crypto filter is not
working"*: 102,026 rows cleared the floor, 2 passed the rest, and proving that
cost 358.2 s of random reads while the panel retried every 15 s.

**16 filter parameters. 10 indexes. ~45 minutes to build each one.** A new
filter box therefore breaks combinations that worked yesterday, and there is
no warning — the box is added, tested alone, and the breakage only appears
when the operator puts it next to another box.

## Cause 2 — the store keeps one set of numbers, the screen prints another (4 of 31)

The `rows` table has **33 columns and ZERO window columns**. Every "last 30
days" figure is computed from the candles when Apply is pressed, at ~0.09 s a
row. So:

* a window filter can NEVER run in SQL — RCA-G is exactly this, the floor
  tested the stored number while the column printed the computed one;
* the window can only cover what one request can re-measure: **50 rows** on
  the page (`api.DAYS_ROW_MAX`), **2,000** in the download
  (`rows_index.DAYS_CSV_MAX`), out of 51.9 million.

## What would actually end it

1. **Store the window figures.** The sweep writes each row's 30/90/365-day
   trades, wins, losses, win % and profit as columns. "Last 30 days" becomes an
   ordinary indexed filter: no re-measure, no 50-row cap, no two sets of
   numbers to keep in agreement. This removes Cause 2 outright and is the only
   one of the three that changes what the operator can ask for.
2. **One covering index per SORT order, not per combination.** `rows_wr4` is
   already that shape for the win-% order; `rows_pr2` is a partial one for
   profit. Finish it and stop hand-picking, or every future box repeats this.
3. **Test filter PAIRS.** Every fix above was verified with its own filter on.
   Nothing drives two boxes together, and two boxes together is what breaks.
4. **DONE — log the press and check the answer against it.** Operator, the same
   day: *"whenever i clicked apply filter and click download csv you should be
   getting the logs of it so you can see the status"*, asked one message after
   the reason the bug survived — *"you were reading the screen; I was reading
   the code"*. `tradingagents/screen_log.py` writes one line per Apply and per
   download, and re-tests every row it is about to send against every filter
   that was on, **using the figure the column prints**. On the Sep 09 filter
   that line reads:

       MISMATCH win % >= 90: 7 of 9 rows on screen break it —
           #CGXLRJML 89.47, #DYKSLWB8 89.47, #DX7HAULZ 80.0, ... (+2 more)

   Read it with `GET /api/screen/log?mismatch_only=true`. It is the operator's
   glance, written by the code that served the table, on every press — which is
   the only check in this file that does not depend on somebody thinking to
   look.

---

## Sep 09, 2026 — four bugs the partial TP/SL build hit before it shipped

**What the operator asked for:** *"do a switch 'Enable Partial TP/SL for DEMO'
and 'Enable Partial TP/SL for Live' / if this is turned on then do the partial
trading / take note the win/L should still go in a specific trade so i can
still see which trade strategy id thas high winrate"*.

None of these four reached the operator: the harddev loop caught them between
the build and the push. They are logged because each is a shape this repo has
paid for before, and the next feature will meet them again.

1. **The base slot would have entered twice.** With partial ON the real book
   gains a slot per strategy (`SYM#live#KEY`), and the base slot (`SYM`) was
   still running its own entry loop — which sees EVERY armed strategy. One
   signal on strategy A would have opened a position in the base slot AND in
   A's slice: one signal, two positions, twice the money.
   *Fix:* the base slot manages what it already holds and never enters
   (`entries=False`). *Guard:*
   `test_the_base_slot_never_opens_a_trade_while_partial_is_on`.

2. **A phantom exit from a payload with no `holdVol`.** The new per-slice exit
   compares VOLUME instead of existence, and `_symbol_vol` summed a missing
   `holdVol` as 0 — so a position the venue reported but could not size read
   as closed, and the book flushed while the money was still on the table.
   That is the BDX loop. Caught by an EXISTING test
   (`test_book_is_never_flushed_while_the_exchange_says_open`), which is the
   argument for keeping old tests honest rather than updating them to pass.
   *Fix:* unknown volume returns None and is never zero; the base slot keeps
   the existence rule untouched. *Guard:*
   `test_an_unreadable_volume_never_books_an_exit`.

3. **A panic close would have left every slice as a phantom.** `report["closed"]`
   holds SYMBOLS; a slice slot is `SYM#live#KEY`. The membership test compared
   the two, so after a panic that really had closed the position, every slice
   stayed in the book logged as "NOT confirmed closed" — and the exit row would
   have carried the slot key in its `symbol` column.
   *Fix:* compare and record `coin_of_slot(key)`. *Guard:*
   `test_a_panic_close_clears_the_slices_it_closed`.

4. **Every real row's ladder rung would have read 0.** `state_key(sym, False,
   key)` used to IGNORE the strategy and answer the base slot; api.py reads a
   real row's rung with exactly that call. Giving the argument meaning silently
   repointed it at a slice that does not exist while partial is off — the same
   shape as the paper-slot regression already recorded in api.py's own comment.
   *Fix:* `at.slot_of(state, coin, dry, key)` answers whichever slot exists,
   and refuses to hand back another strategy's rung. *Guard:*
   `test_the_ladder_rung_reads_the_slot_that_exists`.

**Why the tests did not catch them first:** three of the four are in code the
change did not touch — a caller one level up (api.py), a sibling safety path
(panic_stop), and an existing test's fake payload. Only the loop's "grep every
caller of what changed" round finds those; a new feature's own tests never
will.

**Cost:** zero — live partial defaults OFF and no real strategy is armed.
**Commit:** the partial TP/SL feature commit of Sep 09, 2026.

---

## Sep 11, 2026 — panic_stop crashed on a name that was never there

**CEO summary**
- The emergency STOP button would have failed part-way: it closes your trades
  at the exchange, then crashes before writing them down.
- Your money was never in danger — the trades still close. The crash happens
  after that, while recording them, so the app would have shown positions that
  no longer exist.
- It never fired for real. A test caught it the day it landed.

**DEV summary**
- `auto_trader.py:2498` (panic_stop's clear loop) used `symbol`, which is not
  bound in that scope — the loop walks SLOTS (`for key, st in state.items()`)
  and the contract is `coin_of_slot(key)`. `NameError` after the venue-side
  close, before `st["position"] = None`.
- Introduced by `2f0e741da3a` ("the ledger never recorded the entry BAR"),
  which added `trade_id_of(symbol, pos)` at three sites; two had `symbol` in
  scope, this one did not.
- Guard: `tests/test_auto_trader.py::test_panic_books_the_loss_where_the_
  limits_can_see_it`, which already existed and went red on the next full run.

**Timeline**
1. Sep 10 — commit `2f0e741da3a` lands and is pushed.
2. Sep 11 — a full-suite run (the operator typed "test") fails on
   `test_panic_books_the_loss_where_the_limits_can_see_it` with
   `NameError: name 'symbol' is not defined`.
3. Fixed the same hour: `trade_id_of(coin, pos)`.

**Why the test did not catch it first:** it did — nobody ran it. The commit
shipped without the suite. That is the whole lesson: this repo's tests are
only worth the run.

**Cost:** zero. Live was armed but no panic was pressed.

**Found beside it, and mine:** `reconcile_unconfigured` bound `symbol = key`,
which was correct while every real slot WAS a symbol. Partial TP/SL (Sep 09)
made real slots `SYM#live#KEY`, so the sweep would have asked MEXC about
"GPNSTOCK_USDT#live#stoch14_30m_sl2tp2" and written that string into the
ledger's symbol column. Fixed to `coin_of_slot(key)`; guard:
`tests/test_partial_tp.py::test_the_reconcile_sweep_asks_about_the_CONTRACT_
not_the_slot`.

---

## Sep 11, 2026 — every cloud win rate was overstated: the rules were blind over the start of their own window

**CEO summary**
- Every backtest measured on GitHub reported a better win rate than the same
  strategy really had. Not a rounding difference: some strategies shown as
  profitable actually lose money.
- The reason: a strategy needs ~200 candles of history before its averages
  work. The cloud gave it the window and nothing before it, so at the start of
  every window the strategy could not tell what to do — and the trades it
  missed there were disproportionately losers.
- No money was lost. Nothing was deployed from those numbers and no report was
  published; the check that caught it was replaying a row on this PC and
  comparing.

**DEV summary**
- `.github/scripts/sweep_shard.py::window()` cut to `DAYS + 30` CALENDAR days
  and `run_pair` traded from bar 0. 30 days is 2,880 spare bars at 15m and
  **180** at 4h — under the 200 every `signals_conf` rule reads through its
  SMA200 — so the rule abstained across the first 200 bars of the measurement.
- Fixed: `window()` returns `(df, warm)` keeping `WARMUP_BARS = 300` (>=
  `market_sweep.CONTEXT_BARS`) in front of the measured span; `dirs_idx` drops
  any signal with `k2 < warm`; `days`, `bars` and the h1/h2 split describe the
  measured region only.
- Guards: `tests/test_shard_warmup.py` (6 tests) and the rewritten
  `test_sweep_shard_retry.py::test_the_window_keeps_warm_up_in_FRONT_of_what_it_measures`.

**Timeline, with real numbers**
1. **11:00am** — the 30-day, 4-timeframe, all-coin sweep (run 34539164594)
   finishes: 88,285,468 rows, 4,002 coin+timeframe pairs, 1,078 rows at a 90%+
   win rate.
2. **11:58am** — the top row, PUNDIX 1h `cx_veto`, claims **17 wins, 0 losses,
   100%, +$66.32**. Rebuilding its trade log from the same 1,439 candles gives
   **15 wins, 2 losses, 88.2%, +$48.07**.
3. The two missing trades are **Jul 11 6:00pm SHORT −$4.11** and **Jul 13
   9:00pm LONG −$4.15** — the first two days of the window.
4. Twelve rows replayed across four cascades and three timeframes: **12 of 12
   disagreed**, and four flipped from profit to loss (MMT 1h: +$8.04 published,
   **−$3.83** replayed; CRCLSTOCK 1h: +$2.68 -> −$2.57).
5. Cause isolated by running the cloud's own engine locally: `fast_grid` on the
   cut agrees with the row (10/10/$24.00 for MAV 4h), so the engines are fine —
   the INPUT was short. Signals inside one 30-day window, same coin, same rule:
   **MAV 4h 0 cold -> 11 warm**, PUNDIX 1h 47 -> 39 (different signals, not
   merely fewer), BAND 30m 49 -> 59.

**Why the tests did not catch it:** `test_fast_grid.py` pins the engine against
itself (74 tests, all passing here) and `test_sweep_shard_retry.py` pinned the
window as `DAYS + 30` — it asserted the bug. Nothing compared a cloud row
against a local replay of the same row, which is the only check that could see
this. That comparison is now the first thing done with a finished sweep.

**Cost:** zero in money; one 88M-row sweep discarded and re-run.

---

## Sep 12, 2026 — the only path fast enough to fill the index would have thrown itself away

**CEO summary**
- You asked for 6.8 million newly measured strategies to show up in Stored
  strategies. The only way fast enough takes about 6 hours — and it had three
  faults that would each have spent the 6 hours and then deleted the result.
- None of them had ever been hit, because that path had never been used in
  earnest. All three are fixed and tested before the run, not after.
- Nothing was lost and nothing was at risk. The strategies were on disk the
  whole time; they were simply not visible yet.

**DEV summary**
- `rows_index.rebuild()` had no production caller. `rows_index.py:1267` did
  `done += 1` unconditionally after `index_pair()`, which returns 0 from its
  `except (OSError, ValueError)` WITHOUT filing the pair's summary row — so
  the final gate at `:1345` compared `got_pairs != done`, unlinked the new
  file and returned `{"rebuilt": False, "why": "pairs N vs N+1"}`. A re-run
  meets the same file: unbreakable.
- `rebuild()` never called `_after_fill_indexes()`, so the swap dropped the
  five on-demand indexes the store had already paid hours for, plus the
  `rows_signal` build in flight — the one `signal=cx_veto` needs.
- `main()` accepted `--build` and `resolve` only, so a six-hour job could not
  be spawned detached with a log (the Sep 10 rule).
- Guards: `tests/test_rebuild_guards.py` — 4 tests, and guard 1 was proved by
  reintroducing the bug and watching it go red (`pairs 3 vs 4`).

**Timeline**
1. **02:0x** — `signal=cx_veto` returns 0 rows and `#WYQMPU8A` returns 0 rows,
   while 6,845,648 cascade rows sit in the pair files. `rows_index.status()`:
   96,307,386 rows, 5,388 pairs indexed, **5,179 stale**.
2. Indexing one pair by hand raises `database is locked`; the indexer's own
   log ends **Sep 11, 4:25am** with 15 consecutive
   `sync failed: OperationalError('database is locked')`. The keep-up indexer
   has been dead for ~22 hours behind an index build holding the write lock.
3. Five parallel readers measure the alternatives. Incremental sync at the
   rate measured on THIS store (175 s/pair) over 5,179 stale pairs = **252
   hours**; the kindest figure in the repo (1.5 pairs/min) still gives 57.5 h.
   A full rebuild, scaled from the Sep 10 run: 78 min load + 95 min indexes +
   183 min verify = **~6 hours**. Rebuild wins by 10x–43x.
4. Reading `rebuild()` for the first time as a production path turns up the
   three faults above. Probed on a fixture: one unreadable file →
   `{'rebuilt': False, 'why': 'pairs 3 vs 4'}`.

**Why it was not caught:** `rebuild()` is exercised only by tests that feed it
clean fixtures, and nothing had ever called it for real — so its failure modes
lived entirely in the gap between "the function works" and "the function
survives a store that is being written to while it reads". The pair files were
being rewritten at ~1,800/hour by a live collect during this very check.

**Cost:** none in money or data. The six hours had not been spent yet, which
is the whole point of reading the path before running it.
