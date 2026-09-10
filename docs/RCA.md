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

**The measuring is done. The filing is not.**

There are three steps between pressing UPDATE ALL BACKTESTS and seeing results
on screen. Only the third has been failing.

| step | who does it | state |
|---|---|---|
| 1. Measure on GitHub's 20 machines | the button, via `_run_btupdate` | **works by itself** |
| 2. Bring the results back to the PC | `cloud_autopilot` collects them | **works by itself** |
| 3. File them into the searchable list | a background indexer | **this is what keeps breaking** |

Steps 1 and 2 have never needed a person. The store grew from 51,943,352 to
**52,348,156 rows** during this session with nobody touching it — that is
proof they run on their own. Everything done by hand this session was step 3.

**What "filing" means.** A result is measured into a per-pair file
(`BTC-15m.json`). It is not searchable until its rows are copied into
`rows.db`, the index the Stored strategies screen reads. Until then the result
exists on disk and no filter can find it.

**Where it stands:** **4,612 of 5,365 coins searchable (86%)**. 753 coins are
measured and not yet findable.

**Why step 3 keeps breaking — four separate faults, all found today**

1. It went silent for 13 hours behind a database lock and nothing anywhere said
   why (**RCA-C**). Fixed: the error is kept and shown, the indexer writes a
   log, the button refuses instead of pretending.
2. It was doing 3.5x the work it was designed for — 14 indexes maintained per
   row where the design assumed 4 (**RCA-E**). Fixed, but see 3.
3. The fix for 2 dropped the indexes the operator's own win-% filter needs, so
   their filter stopped working (**RCA-F**). Fixed: the drop is opt-in and off
   by default, and a missing index can no longer read as "nothing matches".
4. Filing is *still* slow — about one coin every 70 seconds — because 38.8% of
   the 32 GB index file is holes, so every write hunts for a gap instead of
   streaming (**RCA-E**, second half). The repair is compaction, which was
   built this session and **has not worked yet** (**RCA-G**).

**What is fixed and pushed**

* the 13-hour silence, with the log and the honest refusal (`4300962c80f`)
* the 14-vs-4 index write amplification (`aeb6357ebe4`)
* a missing index reading as "nothing matches" (`ac62504a8cb`)
* the sweep window: 30 days by default and the 1-year option removed, after a
  full-year sweep of the whole market was heading for 4.7 days
  (`4f18962a5b5`, `dc1a41c26d9`) — that run was cancelled
* compaction built, with verify-before-swap (`7f9a2773650`)

**What is NOT fixed, stated plainly**

* **filing is still slow.** ~15 hours for the remaining 753 coins.
* **compaction does not work yet.** It reached 90% of the copy and stopped
  (RCA-G). Nothing was lost — it never swaps until the copy verifies.
* **`forget_pairs` still holds one transaction across every pair**, so a
  delisted-coin cleanup freezes filing until it ends (named in RCA-C, still
  true).
* **24.8 GB of dead files** (`rows.prev.db`, `rows.old.db`) are read by nothing
  and could be deleted.

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
pairs)` once (one 40-second scan) so any pair the loop will load is provably
absent. `fresh` is opt-in and every other caller still deletes first.

**GUARD** — in `tests/test_rebuild_from_the_pair_files.py`:
`test_the_load_does_not_delete_per_pair`,
`test_fresh_skips_the_delete_and_the_default_still_deletes`,
`test_a_resume_earns_fresh_with_one_scan_not_thousands`,
`test_the_scan_is_named_in_the_source_so_it_is_not_re_added`. The speed itself
is the next run's measurement, and its rate is in `rows_rebuild.json`.

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
