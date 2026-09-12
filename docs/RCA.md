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
