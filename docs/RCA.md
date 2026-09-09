# RCA log — every bug that was fixed, and what now stops it

Operator, Sep 09, 2026: *"list this in rca to prevent this from happening in
the future / all fixes should be listed in a file so you will remember what
where the fixes"*.

**One entry per bug that got fixed. Newest first. Never delete an entry.**
The `rca-log` skill (`.claude/skills/rca-log/`) is ALWAYS ON and writes the
entry in the same commit as the fix. `tests/test_rca_log.py` holds the shape.

Every entry answers the same seven questions:

| field | why it is there |
|---|---|
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
