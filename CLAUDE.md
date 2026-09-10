
## Backtest reporting requirements (MANDATORY — user directives, cumulative)

EVERY results table (chat summary or artifact) MUST include ALL of these columns — no exceptions,
even when constant across rows:
1. **PROFIT / TOTAL $** (the total profit column — explicit, clearly labeled)
2. **TP** (take-profit % or rule)
3. **SL** (stop-loss % or rule)
4. **leverage**
5. **margin and/or notional** — stated in the provenance line above the table and in
   the per-row detail panel. NOT as grid columns: they are constant on every row, and the
   operator had them removed on 2026-08-19.
6. **WINS and LOSSES** (counts; per day for intraday), and the **WORST LOSING STREAK** —
   the sum of the worst unbroken run of losses, with how many trades it was. A "worst
   trade" column alone is not acceptable: on APEX the worst trade was -$9.12 while the
   worst streak was -$79.80 over 13 trades on a $65 wallet, and the ladder makes the run
   the thing that empties the account.
7. trades count (and trades/day for intraday)
8. total combos/configs tested stated above the table

EVERY results-table artifact MUST additionally have (the "standard kit"):
A. published as an artifact with link (never chat-only tables)
B. click any row -> full trade-by-trade log (in-page simulation from embedded bars)
C. "base margin $" input textbox that live-rescales every dollar figure
D. trade-log panel shows an explicit TOTAL PROFIT summary (not just a running column)
E. sortable columns when >20 rows

F. **every row carries every column.** If the payload is too big, compress the ENCODING
   (arrays aligned to a header, ids, fewer decimals) — NEVER drop a field from a subset of
   rows. On 2026-08-18 the monthly columns were kept only for survivor rows, so the
   operator's own live APEX config showed 11 empty months on a row with 307 trades.
   Verify with every filter at its widest, on a row the default view hides.

G. **filters for the columns that decide things**: min win rate, min profit total, min
   months green (a count), max worst dip, **max TP %**, **max SL %**, and **last N months / last N days** — which RE-RUNS every row
   over that slice of candles rather than hiding rows, so profit, trades, wins, losses and
   win rate are the window's own; print the window's real dates beside the row count, and
   REMOVE the month columns outside the window rather than filling them with em dashes — live-typing, stacking, measured at the CURRENT base
   margin, with the active filters named in the row count and a clear-all button.
   **Every filter takes the unit its column PRINTS**: GREEN prints `11/12`, so the box
   counts months — set 10 and a 9/12 row must vanish. A percent box beside a count column
   reads as broken, because 11 typed as a percent matches everything. And when a filter
   cannot cut anything in the current view, print why beside the count.
   **MAX TP % and MAX SL % are on every artifact and in Stored strategies** — the
   operator's words, in the order they arrived: *"add a filter min tp and min sl ... it
   should be read as AND / always remember this setting when generating artefact"*
   (2026-09-02), then *"for sl if i input 1 then show below 1 or equal 1"*, then
   *"when i input tp 3% it should show tp below 3%"* (2026-09-03). **BOTH ARE CEILINGS**:
   3 keeps TP 3% and smaller, 1 keeps SL 1% and tighter. What they are hunting is a
   target the market actually reaches with a stop that risks little — not the widest
   target on the page. Both are inclusive, in the percent their column prints, stack
   with every other filter as AND, and are named in the row count.
   The TP box was a FLOOR for one day, which is why the parameter was RENAMED to
   `max_tp` end to end rather than reused: a field still called `min_tp` while meaning a
   maximum is a lie inside the API, and this repo has paid five times for a true number
   under a false label.
   A filter must also be able to REACH THE DATA. `SL <= 1%` returned nothing on the
   first version of that page because the page held the top 500 rows by win rate while
   **61** rows with a stop that tight had passed the screen. Publish every row that
   passed (all 3,613 there, logs included, 7.5 MB) or the filter answers about the page
   instead of the measurement.

   **THIS IS NOT ONLY ABOUT ARTIFACTS — it happened again on Sep 09, 2026, in a
   panel.** FILTER WHERE THE DATA IS, NEVER AFTER A WINDOW HAS BEEN TAKEN. The
   operator asked why row #YDMRLEZ5 showed one loss that was missing from the demo
   history. The loss was real — KITE 1h squeeze, `Sep 07, 2026 5:01pm`, SL, -3.19,
   on the paper book — and `HistoryPanel` fetched the newest **200 ledger rows**, then
   picked out `enter`/`exit` in the browser. Their ledger was **3,666 rows of which
   2,868 were `gate_blocked`, 552 `blocked`, 169 `stale_skip` and 12 were trades**;
   the newest 200 spanned 23 hours and held 2 of the 12, and that exit sat **640 rows
   from the end**. A filter cannot recover rows that never arrived.
   The shape to look for, anywhere: **a `.filter(...)` in a component over a list the
   server already truncated by `limit`, `head`, `tail` or "top N"** — the predicate has
   to travel to the query. `/api/ledger` takes `actions` now, and returns `matched`
   beside `total` so "no trades" is distinguishable from "no ledger". Kit item G is the
   artifact case of this rule; the rule itself is about every screen.
H. **a stable row ID as the first column** (`#LLZM9D`), HASHED FROM THE COMBINATION
   (`backtest_report.row_code`), never a per-page sequence — a sequence gives the same
   live row a different number on every page, which is how "#05146 / #02054 / not there"
   happened. Plus a find-by-ID box that overrides the other filters and opens that row's
   log. Quote the ID in chat when naming a row — "the first
   row" is what deployed the wrong config on 2026-08-17.

PRE-PUBLISH CHECK (mandatory): before publishing any artifact, verify items 1-8 and A-H explicitly,
one by one. A missing item = do not publish until fixed. User has escalated three times over missing
columns/features; treat this checklist as blocking.

## Commit and push EVERY change (MANDATORY — 2026-08-25)

**Finish a change, commit it, push it. Do not ask.** The operator's words:
*"just push right away, why did you asked this suddenly? take note somewhere to
push always whatever the change"*.

Work that only exists on this Mac is work that does not exist. On 2026-08-25 a
whole session of fixes sat uncommitted while GitHub Actions ran a sweep from
`main` — so the cloud executed the OLD shard, with the caps the session had
just removed, and would have written capped data into the store. The operator
saw "no changes" on GitHub and was right to.

- push after each coherent unit of work, not at the end of a session
- a commit message says WHAT changed and WHICH incident bought it, with the
  real numbers — the messages in this repo are the incident record
- never hold a change back to ask permission to push; if something genuinely
  must not ship, say so in the same breath as pushing the rest
- anything the CI runs from `main` (workflows, `.github/scripts/*`) is doubly
  urgent: unpushed means the cloud is running different code from this machine

DO NOT commit the operator's private notes (`.obsidian/`, `*.md` scratch files
in the repo root) — those are theirs, not the project's.

## A failed coin is redone alone (MANDATORY — 2026-08-25)

**If a coin fails: delete that coin's backtest, then redo THAT job — never the
whole sweep.** The operator's words: *"if a coin fails, delete the backtest then
redo again the last failed job (not the whole)"*.

Both halves are load-bearing:

* **DELETE first.** A pair that raised part-way has already written rows and a
  state file whose watermark is stale or missing. Measuring on top leaves one
  coin carrying a mixture of two runs, and no column anywhere says which rows
  came from which. `market_sweep.discard_pair(coin, tf)` removes the rows file,
  the state file and any `.tmp` beside them, under the pair lock. It runs inside
  `_worker`, BEFORE the failure is reported, so nothing that merges the store
  can see the wreckage. **Candles are kept** — they are the expensive part, they
  are shared with every other timeframe, and they were not what failed.
* **NOT THE WHOLE.** The failed pair is resubmitted into the same pool, up to
  `market_sweep.PAIR_RETRIES`. The other 4,964 pairs keep running. Restarting a
  sweep because one coin timed out throws away hours for one bad contract.

Two traps that tests now hold shut
(`tests/test_pair_retry.py`):

* `total` counts PAIRS. A retry must never bump it, or the percentage runs
  backwards the moment a coin fails.
* A pair that never recovers is **named** in `progress.json`
  (`BAD_USDT 1h: klines returned 0 bars`), not just counted — a bare "3 failed"
  sends somebody back to the logs to find out which three.

An INTERRUPTED pair is not a failed one. A SIGTERM or a closed laptop leaves a
consistent checkpoint, and the next pass resumes from its watermark. Only an
exception discards.

**The same rule for candle DOWNLOADS (2026-08-25).** A 4,985-pair download
ended `2 error(s): CHILLGUY_USDT 15m: IncompleteRead(183452 bytes read)` —
one connection cut mid-body, the pair skipped for good, the second lost pair
(NAORIS_USDT 30m) never even named, and "update" walks the store so neither
could ever be fetched again. Operator: *"i want 10/10 accuracy on download"*.
Three layers now, all tested (`tests/test_public_get_retry.py`,
`tests/test_download_retry.py`, `tests/test_cloud_download_retry.py`):

* `mexc_futures._get_public` retries a failed WIRE (cut connection, timeout,
  5xx, 429) up to `_PUBLIC_RETRIES` within `_PUBLIC_RETRY_BUDGET_S` of
  wall-clock. Never `_request` — a second order submit is a second order.
* `db_jobs._run_download` and `market_db.download` redo a pair whose error
  `is_transient` BY ITSELF, after the others, up to `db_jobs.PAIR_RETRIES`;
  a deterministic failure is named at once. Every pair still lost is NAMED
  in the progress file (`failed`), the bell and the log — never `errors[0]`
  alone — and written to `db_download.lost.json`, which the next "update"
  queues again.

## Never cap the grid with a default nobody chose (MANDATORY — 2026-08-25)

`cloud_sweep.dispatch()` defaults `min_days=365` and `sweep_orchestrator` did
not pass the argument. The sweep therefore measured **455 coins of 993** and the
panel still called it the whole market; 538 contracts younger than a year were
never in it. In the same function, a coin whose age check RAISED was dropped
from the grid with nothing but a log line — one timeout deleted a contract from
the search.

- `sweep_orchestrator.MIN_DAYS = 0`, passed explicitly and logged with the
  dispatch. Depth is reported by each row's own `days`/`months`/`bars`, and
  filtering on it is the reader's decision made in the artifact — never a
  deletion made in the sweep.
- A failed age check KEEPS the coin.
- **THERE IS NO BAR FLOOR (operator directive, 2026-09-09):** *"i told you to
  test 4hr then test it the available candles / its like use what's
  available"*. `backtest_report.MIN_BARS` is 2 on every timeframe — the
  physical minimum, one bar cannot contain a trade. The 500-bar floor before
  it held 622 young pairs "pending" for weeks. A signal whose lookback
  exceeds the history simply makes no trades; depth is the row's own
  `days`/`bars`, and the min-trades filter is where the reader decides trust.
  (History: a flat 500 made 1d impossible on 2026-08-25 — all 997 1d pairs
  excluded as "only 90 bars"; the floor went per-timeframe, then to zero.)
- The TRADE floor is per timeframe too (`market_sweep.MIN_TRADES_BY_TF`).
  A flat 100 deleted the whole 1d timeframe on 2026-08-26: all 739 1d row
  files were `[]` while the state files held 10,692 measured combinations
  per pair (SPX500-1d's best: 11 trades, median 3) — ~10.6 million
  measured combinations computed and dropped, and the run said five
  timeframes while the grid held two. 100 trades is impossible on ~90
  daily bars. It is a floor on EVIDENCE, not a judgement.
- The cloud shard takes the same `days` window as the local job (workflow
  input `days`), buffers a pair's rows until it completes, and redoes a failed
  pair by itself (`PAIR_RETRIES`, same as the sweep) — never the whole shard.
- Whatever really was excluded is counted out loud (rule 20).

## Date format (MANDATORY — asked three times, 2026-08-21 and 2026-08-22)

**Every date and time this project puts on a screen, in a log, in a report or
in an API response reads exactly like this:**

```
Aug 03, 2026 8:03pm
```

Operator's words: *"i want format of Aug 03, 2026 8:03pm ... i will not repeat
this again, i want this remembered so other session in claude will see this ...
this applies to whole module"*.

Every part of it was wrong at some point, so read it precisely:

| part | rule | wrong |
|---|---|---|
| month | three letters, capitalised — `Aug` | `08`, `August` |
| day | **two digits, zero padded** — `03` | `3` |
| year | four digits, after a comma | omitted |
| hour | 12-hour, **not** padded — `8`; midnight/noon are `12` | `08`, `20` |
| minute | two digits — `03` | |
| am/pm | **lowercase, no space** — `8:03pm` | `8:03 PM`, `8:03PM` |

Compact stamps (`08-21 00:18`) are banned outright, and so is
`toLocaleString()` (`8/22/2026, 8:03:00 PM`).

**There are exactly two implementations and you must call one of them:**

* Python — `tradingagents.positions_view.fmt_when(ts_seconds)`
* TypeScript — `fmtWhen(seconds)` / `fmtWhenMs(ms)` in `webapp/src/lib/api.ts`

Never write `strftime("%b %d, %Y ...")`, `time.strftime`, or `new Date(...)
.toLocale*` anywhere else. Three hand-rolled copies had already drifted apart
by 2026-08-22 — one in the runner's scan log (unpadded day, uppercase PM), one
in each of two API routes with a `.replace(" 0", " ")` hack to undo a padded
hour — plus seven `toLocaleString()` calls in the web app. Tests enforce this:
`test_the_date_format_is_exactly_what_the_operator_asked_for`,
`test_no_module_formats_a_timestamp_by_hand`,
`test_the_browser_uses_one_date_format_everywhere` and
`test_the_two_date_formatters_agree` (runs both implementations over the same
instants, including midnight and noon).

**LOG LINES COUNT.** The Runner feed shows raw log lines, so `%(asctime)s` is
a date on the operator's screen. `logging.basicConfig`'s default prints
`2026-08-22 19:27:03,488` — the banned stamp, on every row. Configure logging
with `positions_view.WhenFormatter`, never a bare format string; `datefmt`
cannot express the rule either, because strftime has no portable unpadded
12-hour hour and its `%p` is uppercase. This was the FOURTH ask: the message
content had been fixed while the line's own timestamp had not.

A month LABEL (`Aug 2026`) is a different thing and keeps its own form, and
PARSING someone else's format (`strptime` on an X/Twitter stamp) is fine — the
rule is about what this project PRINTS.

**A GUARD IS ONLY AS WIDE AS ITS PATTERN (Sep 09, 2026).** The banned stamp came
back on every row of the trade-history table — `2026-09-07 17:01`, from a Date
built out of the seconds with its ISO string sliced — and
`test_the_browser_uses_one_date_format_everywhere` passed the whole time,
because it greps for `.toLocale` and nothing else. The rule had never been
wrong; the check had one spelling of one way to break it. When a MANDATORY rule
is broken again, fix the code AND widen the guard in the same commit, then
confirm the widened guard fails on the old file. `test_history_shows_the_trades
_not_the_refusals.py` now also rejects a `Date` built from seconds, while still
allowing `toISOString().slice(0, 10)` for a date INPUT's value, which is not a
printed timestamp.

## The live door is write-only, signed, and never the trading API (MANDATORY — 2026-09-09)

The operator: *"why not immediately put the results in my pc"*, then *"i want
it open then, i want you to post the result immediately to my pc"*. GitHub's
machines now post each finished coin straight here (`tradingagents/live_ingest`),
and results appear in the store seconds after they are measured instead of an
hour after the run ends (run 34307921614 finished 7:32am and was still
importing at 10:42pm).

Anything that opens this PC to the internet obeys all five, always:

* **Never the API on 8787.** It can place real orders. The door is its own
  process on `127.0.0.1:8788` serving exactly `POST /rows` and `GET /up`;
  every other path is 404, including the ones a scanner tries first.
* **Outbound only.** A Cloudflare tunnel this PC dials out to — no router
  port, no firewall hole, and killing the process closes it. The address is
  new every run and the door shuts itself after `IDLE_STOP_S`.
* **Signed, never carrying the secret.** HMAC-SHA256 over path+body with the
  32 bytes in `~/.tradingagents/ingest_token`, given to GitHub as the
  repository secret `INGEST_TOKEN` (masked in logs). A tunnel hostname is
  temporary and can be reassigned; a raw token would teach the next holder
  something reusable, a signature teaches nothing.
* **The fast path is never the record.** The artifact is still written for
  every pair, BEFORE the post and whatever the post does, and the autopilot
  still collects the finished run. A pair that landed live is refused there by
  the one store rule (`cloud_sweep.land_rows`: equal is not newer), so nothing
  is written twice and a sleeping PC loses only immediacy.
* **Prove the address before handing it out**, and treat a local DNS failure
  as this machine's problem, not a shut door: the operator's ISP resolver
  answers "Non-existent domain" for a fresh `*.trycloudflare.com` name that
  1.1.1.1 resolves at once, so `reachable()` falls back to DNS-over-HTTPS. A
  refused connection or a wrong answer is still a shut door.

`tests/test_live_results.py` drives the real socket with real gzip and the real
signature check; `ensure()` refuses to open anything while `PYTEST_CURRENT_TEST`
is set, so no test run can put an address on the internet.

## Never put anything below an entry point (MANDATORY — 2026-08-22)

`if __name__ == "__main__":` is the LAST thing in a module. Always.

The runner starts with `python -m tradingagents.auto_trader run`, so the module
body executes top to bottom and stops at that guard — **nothing defined below
it exists**. A plain `import` runs the whole file, so the API and every test
still see those names and everything looks healthy. `save_settings` and
`timeframe_locks` sat below the guard and every LIVE cycle raised
`name 'timeframe_locks' is not defined` from 13:34:23 for five hours, 1,176
failures, four coins a cycle, while the paper book printed normal scan lines
beside them. `market_sweep.py` had the same trap with six definitions.
`test_nothing_is_defined_after_the_runner_entry_point` checks every module that
has an entry point.

## Trading-cost rules (MANDATORY — bought with real money, see docs/INCIDENT-2026-08-12-BDX.md)

9. **Every backtest charges all THREE costs: entry, exit and HOLDING.** A profit computed at
   candle prices with zero slippage is fiction, and one that never pays funding is fiction for
   anything held overnight. `auto_trader.backtest_strategy()` charges fee + slippage by
   default — never pass `slippage=0` — and **`funding=fx.funding_history(coin)` must be
   passed**, which applies each published settlement inside the trade's own window. Measured
   2026-08-19 on the live five: −4.7% on PROVE, −0.8% on APEX, −0.2% on PI, and +0.5% on both
   ALICE and XAUT, which hold the side that RECEIVES funding.
10. **Cost is measured PER CONTRACT, never averaged across coins.** One generic figure across many
    order books is an assumption wearing a measurement's clothes. Use
    `mexc_futures.book_cost(symbol, notional)`, which walks the live book.
11. **State the cost/target ratio next to any strategy recommendation.** Round-trip cost vs
    take-profit. Under 20% is comfortable, near 50% is fatal, above 100% is arithmetically
    impossible. BDX_USDT ran at 734% and could not win a single trade.
12. **Never enable a strategy on a coin without `auto_trader.edge_check()`.** `block` means no
    orders, in the UI and in the runner. `unknown` (book unreadable) is never treated as ok.
13. **Data honesty:** state the real history depth, and MEASURE it rather than assuming.
    Measured on BTC_USDT 2026-08-13 by paging `klines` backwards until it stopped:
    **1m = 30 days (44,473 bars, hard ceiling), 15m = 360 days, 1h = 400+ days.**
    A "months green" claim on 30 days of 1m is not evidence and must be labelled as
    such — and never cap a fetch below what the venue serves: a 15m sweep once ran on
    8,000 bars (83 days) when 34,636 were available, which silently made its results
    meaningless.

## Live-trading rules (same incident)

14. **The exchange is the source of truth, never the local book.** Verify a stop actually rests
    (`verify_position_stop`), a position is really open/closed (`open_positions`), and a realized
    PnL is real (`position_history`). "The request was sent" is not "it is in place".
15. **Never assume an exit happened.** If a barrier is crossed while no bracket is confirmed
    resting, the runner closes the position itself.
16. **Every venue rejection needs a handled path + loud log + ledger row:** 2015 precision,
    5003 stop already breached, 2051 order-size cap, 2078 close near liquidation, 510 rate limit.
17. **Orphan sweep every cycle** — any exchange position the book is not tracking gets adopted
    and bracketed. A position must never be open without a stop for longer than one cycle.

## Big files go where the STORE is, never the system drive (MANDATORY — 2026-09-10)

The operator, `Sep 10, 2026 12:10am`: *"why are you using my c drive?"*. Their
store is on `G:` on purpose. `C:` had **6 GB free of 118 GB**.

`cloud_sweep.fetch()` and `collect_into_store()` called
`tempfile.TemporaryDirectory()` with no `dir=`. That is `%TEMP%` —
`AppData\Local\Temp`, the SYSTEM drive — while `market_sweep.HOME` is
`~/.tradingagents`, a junction onto `G:`. Every result file the fleet produced
was downloaded and unzipped onto `C:` before being streamed to `G:`.

**The rule, in three parts:**

* **Anything that can exceed ~100 MB is written under `market_sweep.HOME`,**
  not `%TEMP%`, not `/tmp`, not the repo. Use `cloud_sweep._scratch()` or the
  same pattern: `Path(msw.HOME) / "tmp"`, created on demand, falling back to
  the system default WITH A WARNING if that drive cannot be used. The operator
  chose which drive holds this data; a library does not get to overrule it.
* **"Temporary" is a promise the code has to keep.** `TemporaryDirectory` only
  cleans up if the process reaches the end of the `with`. A KILLED job never
  does — and `start.py` kills the job tree with `taskkill /T` on every restart,
  so each hard stop leaked a whole 3.3 GB shard, permanently. Anything writing
  large scratch must SWEEP ITS OWN LEFTOVERS on the way in, by age, in its own
  directory only (`SCRATCH_TTL_S`, 6 hours — a download times out at 30
  minutes). Never sweep `%TEMP%` itself from library code; it is not ours.
* **Measure the SIZE before calling something temporary.** One shard is
  `rows-5.jsonl` at **3.33 GB**. Twenty is ~60 GB, more than `C:` had free at
  any point that day. The word "temp" hid a number nobody had looked at.

What it actually cost: no money, the machine. Windows on 6 GB of 118 GB stalls
its page file, and that same session had already traced the backtest's slowness
to page-file thrashing. Found on disk at 12:10am: two orphan folders holding the
SAME `rows-5.jsonl` (3.33 GB each, from collects that were killed) plus the live
`rows-18.jsonl` (2.73 GB) = 9.39 GB, and **147** leaked `tmp*` folders going
back to `Sep 03`. Deleting the two dead ones took `C:` from 6.4 GB to 13 GB free.

**WHY IT WAS NOT CAUGHT** — every test about the store checked its CONTENT:
rows, watermarks, cloud/local parity, ownership marks. Not one asked WHERE the
bytes land on the way in. When you add a path, assert its DRIVE, not just that
the data arrives.

`tests/test_cloud_sweep.py`:
`test_no_artifact_is_unpacked_on_the_system_drive` walks the AST for every
`TemporaryDirectory` call and demands `dir=_scratch()` — reading the CALLS, not
the prose, because the docstring quotes the broken form and a plain string
search matched it;
`test_the_scratch_sits_on_the_stores_own_drive`;
`test_a_store_drive_that_cannot_be_used_falls_back`;
`test_a_killed_collect_does_not_leak_a_shard_forever` proves a six-hour-old
unpack is removed, a live one is kept, and a folder that is not ours is never
touched. Full account: `docs/RCA.md` RCA-2026-09-10-B.

## A job that cannot start must SAY SO (MANDATORY — 2026-09-10)

The operator, `Sep 10, 2026 1:05am`, told the measuring was finished while
their screen still showed the day before's numbers: *"is tehre a bug or what i
dont understand"*.

It was finished — 5,364 pair files on disk, last collect `12:38am`. None of it
was visible, because a delisted cleanup had held `rows.db`'s write lock since
`Sep 09 11:55am` and the indexer sat behind it at **0.0 s of CPU per 30 s**.
Nothing on the machine said any of that. Three faults, each one a rule:

* **NEVER `except Exception: pass` on a worker thread.** REINDEX answered
  `{"started": true}` and the thread died on its FIRST statement, `ensure()`
  raising `database is locked`. A caller that has already returned "started"
  cannot learn the truth later unless the failure is KEPT somewhere a reader
  reaches — `_last_error`, served in `status()`. A swallowed failure is a
  button that lies, and it lied for 13 hours.
* **The number a button prints is the number of work it will DO.** The route
  printed `behind` (never-indexed, **806**) for a job that walks
  `stale_pairs()` (**5,276**) — 6.5x under. Even a working run would have
  looked finished a sixth of the way in. This is `label-must-match-data`
  applied to job SIZE, which is the reading nobody makes on their own.
* **A long-running process writes a LOG.** `spawn_indexer` ran with
  `stdout=DEVNULL, stderr=DEVNULL`. That process is the only thing that prints
  *"paused: a backtest is running"* and *"indexing N pairs"*; 18.7 hours of it
  went in the bin, while every other job here writes `~/.tradingagents/*.log`.
  Diagnosis took walking the process table and sampling CPU per-pid. Add
  `PYTHONUNBUFFERED=1`: a log that appears only at exit is no use for a
  process meant to run for days.
* **And a blocked resource NAMES ITS HOLDER.** `rows_index.lock_holder()`
  reports the cleanup and its phase, so the answer is *"the row index is
  locked by delisted cleanup: removing from the row index: 55 of 73 pairs"* —
  not a stalled screen the operator has to interpret.

**WHY IT WAS NOT CAUGHT** — 289 index tests, every one about what the index
CONTAINS or how fast it fills. None asked what happens when the fill **cannot
start**. A swallowed exception has no observable behaviour to assert unless you
decide the failure itself is a product surface, so the guard must be written
against the SWALLOW, not the success (`tests/test_index_stall_is_visible.py`,
14 tests; all three faults were re-introduced and each went red first).

**Still open, so it is not forgotten:** `rows_index.forget_pairs` holds ONE
transaction across every pair by design, so a 73-pair cleanup freezes the whole
index for as long as it takes (~14 min/pair on this spinning disk). Chunked
commits are the real repair, and `_drop_pairs`'s "may the files go now"
contract has to move with them. Full account: `docs/RCA.md` RCA-2026-09-10-C.

## The row index is a BULK LOAD, not a trickle (MANDATORY — 2026-08-26)

The operator: *"why is my stored strategy few? ... where are those?"* and then
*"i want it paginated load all the coins"*. Nothing was lost: 973 coins had
measured rows on disk and the list offered **711**, because while a sweep runs
the indexer trickles ONE pair a cycle (`TRICKLE_PAIRS`) — 1,094 pairs behind,
about three hours away — and no button could ask it to hurry.

Measured on the operator's own store (8.94 GB, 21,858,026 rows, mechanical
disk), and every number here was paid for in wall-clock:

* `ensure()` was creating FILTER_INDEXES, which the next bulk fill DROPS and
  rebuilds. A forced catch-up sat at 7.8 s of CPU for thirteen minutes doing
  exactly that (py-spy: `ensure -> con.execute(ddl)`); `rows_winrate` alone
  takes **912 s**. It now creates `KEEP_INDEXES` only; a missing sort index is
  built on demand (`build_sort_index`, and `query()` answers 503 with the
  reason meanwhile).
* An insert with the indexes in place managed **1.5 pairs/min**; with them
  dropped, **75 pairs/min**. Fifty times. A fill of more than a handful of
  pairs drops every index except `rows_pair` (delete-by-pair needs it), loads,
  then rebuilds.
* Do NOT repair a bloated file in place: this one carried **727,146 free pages
  (2.8 GB)** and a single `DROP INDEX rows_profit` had not finished in
  fourteen minutes. Loading a FRESH file sequentially and swapping it in is
  faster and leaves a compact database.
* `POST /api/strategies/reindex` is the operator's way to force it, and the
  panel shows "index the missing N pair(s) now" beside the count.

**MEASURED AT 96,313,064 ROWS (Sep 10, 2026) — a full `rows_index.rebuild()`
of the whole store, so the next session scales from real numbers instead of the
31M-row ones above.** Whole run 2:52pm → ~8:30pm on a mechanical G:.

| phase | measured |
|---|---|
| load 5,367 pair files, no indexes | **69.9 min, 70.3 pairs/min** |
| `rows_pair` (96M **text** keys) | **48 min** |
| `rows_profit` | **14 min** |
| `rows_coin` + `rows_winrate` | **~27 min** together |
| all four indexes | **~89 min** |
| pre-swap verify (2 counts + `quick_check` over 41.94 GB) | **~3 h** |
| file | 41.94 GB holding 96.3M rows, against 34.69 GB holding 52.3M |

Three things that table is worth knowing for:

* **The text index is the expensive one.** `rows_pair` cost 3.4x `rows_profit`
  on the same table — 96 million text keys to sort against numbers. Budget for
  it, and never assume four indexes cost 4x one.
* **`index_pair`'s delete-first is a FULL TABLE SCAN without `rows_pair`,** and
  a rebuild has no indexes while loading. Measured 39.9 s per pair at 2.94 GB,
  quadratic as the file grows: 54 hours across the store, and it is why filing
  looked like it decayed from 40 pairs/min to 0.25. `index_pair(..., fresh=True)`
  skips it for a caller that has PROVED the pair is absent (docs/RCA.md
  RCA-2026-09-10-K).
* **The pre-swap verify is the longest phase and it is disk-bound**, measured
  at **339 reads/sec of ~12 KB = 4.1 MB/s** while a plain sequential read of
  the same disk measured **106 MB/s**. It is kept anyway — it is the only thing
  between a bad file and the operator's one index — but every long phase
  publishes to `rows_rebuild.json` while it runs, because three separate
  phases went silent in one afternoon and each one got called a stall.

## The fold streams; the page is capped and says so (MANDATORY — 2026-08-26)

A market-wide sweep cannot be summarised in RAM. Measured on this PC's own
store: 12 pairs held 211,420 rows in 392 MB of Python, so the 2,991-pair
2-month grid needed **~98 GB** on a 17.1 GB machine. At 5:20am the job died
with `MemoryError` in `grid_from_store` (`rows += pair_rows(...)`) after
measuring 2,367 pairs perfectly — hours of correct work, no report.

* `parquet_store.GridSink` takes one pair at a time and writes EVERY row to
  the run's snapshot; `grid_from_store` keeps `row_cap` rows (default
  `DEFAULT_ROW_CAP = 250_000`, the most profitable, plus every deployed row —
  rule 21) and the aggregates it counts while streaming. Peak: 596 MB.
* A field outside the declared schema rides in the snapshot's `extra` column
  and is NAMED in `payload["schema_extra"]` — never dropped (kit item F).
* The page prints what was MEASURED, never its own length:
  `backtest_report._tested()` / `_capped_note()` print "21,278,772
  combinations — this page shows the 250,000 most profitable of them; every
  one is in <snapshot>". A capped grid says what it capped (rule 20).
* `persist_results` must NOT re-save `payload["rows"]` when `grid_path` is
  set: that would replace a complete snapshot with the page's selection.
* A failure names its exception type. `str(MemoryError())` is empty, so the
  bell read "Backtest FAILED" with nothing after it and the progress file said
  `failed: ` — the cause had to be read out of a stack trace.

Any strategy analysis and the app's BACKTEST button MUST run the same grid from
`tradingagents.backtest_report` — never widen it locally for an artifact. They diverged
once and the operator could not find a single recommended row inside their own app.
(This said `1 YEAR` button until 2026-09-10, when the operator had that window
removed: *"Also remove the previous 1 year i wont be using that, it should
always default to past 30 days"*. The window is now 30 days by default
— `cloud_sweep.SWEEP_DAYS` — and the dropdown offers 30/60/90/180. The rule was
never about the window; it is about the analysis and the button running the
same grid, whatever window is asked for.)

Before recommending or re-checking ANY strategy for a coin, run the `still-working`
skill: a configuration must be profitable in EVERY nested window (1 month, 3 months,
6 months, full history) with enough trades in each, and the DEPLOYED row is screened
first. On 2026-08-19 the live APEX row was cold two months running (-$4.80 then -$22.62)
while the alternative was green in both.

Before delivering ANY answer, number, table, artifact or "done" in this repo, run the
`three-gates` skill: (1) is it accurate — measured not assumed, (2) is it production-real,
(3) did I test it. Do not answer until all three pass.

ALWAYS ON — `bug-scenario`. STRICT. Any answer containing the word "bug" leads
with a numbered timeline of what actually happened — real timestamps, real prices,
real dollars from the operator's own ledger/state/exchange — then one line each for
why, cost, and whether it is fixed. Never describe a bug only as code or conditions.
A bug that never fired is labelled "NEVER HAPPENED YET" before its hypothetical
timeline. Applies to "what are the bugs", "is there a bug", reporting one found in
passing, and explaining any fix.

ALWAYS ON — `short-and-plain`. STRICT. Every reply is SHORT, in BEGINNER
language, **and carries a real example** — all three at once — one skill, because three separate ones (the deleted
short-answers, one-word and plain-words) each got followed alone: jargon, or
plain but four paragraphs long. Operator, 2026-09-05: *"COMBINE THEM IN ONE
CREATE NEW SKILL AND REMOVE THE EIXSTING 3"*.
Hard caps: a fact = 1 sentence. "why" = 3. "explain" = 6. Reporting work done =
3 plus the numbers. Over the cap, delete paragraphs before sending. No
unrequested caveats, no "worth noting", no stapled second findings, no recap of
the reply just given, no offering the next three things, no table for a single
number, no restating the question.
And in plain words: define a term the first time it appears, in six words or
fewer; lead with what it MEANS for them, then the number; money, not ratios; one
idea per sentence; yes/no answers start with yes or no. Words a 12-year-old
knows — *"STOP USING LONG WORDS AND DEEP WORDS FROM NOW ON I WANT BASIC WORDS,
ENABLE THIS FOR ALL SESSION"*. It took five repeats of one question ("why did
demo win and live lose") before the answer was small enough to use.
**ALWAYS AN EXAMPLE (2026-09-09):** *"can you answer short but clearly always
give me examples so i can easily undestand, i want this enabled always"*. Every
answer carries one CONCRETE example with their own numbers — a row id, a coin, a
dollar figure, a timestamp — never "Coin A" or "some strategy". It is not extra
length: the example REPLACES the explanation. `window_last` was answered as
*"#G4TLD68H GPNSTOCK 15m: candles to Sep 09, 2026 8:15am, backtest stops Sep 05,
2026 3:15am"* instead of a paragraph about measurement coverage — shorter AND
clearer. If a real one cannot be measured, label it "made-up numbers".
Compress structure, never comprehension. Verify as rigorously as ever — then
report only the answer.

ALWAYS ON — `say-done`. After finishing ANY task the operator asked for — code
changed, sweep finished, artifact published, bug fixed — speak one calm sentence
out loud (under ~12 words, no "sir" — removed 2026-08-20). One utterance per
finished task, not per tool call, never for a mid-task status update, never after
a failure. NEVER call `say` directly — always the script below, which reads
`.claude/skills/say-done/config.json` at speak time so operator edits apply live:

```bash
bash .claude/skills/say-done/speak.sh "<what was finished>" &
```

ALWAYS ON — `label-must-match-data`. Run it before reporting ANY change that puts a
figure on screen: a tile, table, artifact, caption or badge. This is not optional and does
not wait to be invoked. three-gates has a blind spot: "is it accurate" keeps passing
because the NUMBER gets verified, and the number is never the bug. Five UI failures on
2026-08-14 were all the same shape — correct value, false label:
`+ open (RUNE) +7.59` when RUNE was +0.16 and the figure summed four positions;
`PI · not yours` when PI was configured; a "POSITIONS" table that was 8/9 closed history;
`TOTAL PROFIT` over 400 of 694 trades; a `log` badge that opened nothing.
Every label must be DERIVED from the data it describes — never a literal. Verification
must assert the label AGREES with its source, and that itemised rows SUM to the total
shown. Presence is not correctness.

ALWAYS ON — `workflow-map`. When the operator asks how something WORKS — "give
me the workflow", "the flow", "what happens when i press this", "walk me
through it" — the answer is the BOXED ARROW DIAGRAM in
`.claude/skills/workflow-map/`, never a paragraph and never a bullet list.
Numbered stages in boxes, one arrow down the column, a branch box at every
decision, a loop in a double box, real names and numbers inside the boxes
(`port 8788`, `27,500 rows`), a mandatory "IF ANYTHING FAILS" block at the
bottom, and ONE line of plain words under the diagram. Asked for on
2026-09-10 after the same answer was given twice as prose and once as a list:
*"i want workflow style ... moving forward when i ask you a workflow i want
this format"*. A single fact is still one sentence — `short-and-plain` rules
everything.

ALWAYS ON — `rca-log`. STRICT. **A bug fix is not finished until `docs/RCA.md`
has its entry, in the SAME commit as the fix.** No entry, no commit. The
operator, 2026-09-09: *"list this in rca to prevent this from happening in the
future / all fixes should be listed in a file so you will remember what where
the fixes / create a skill that is enabled always whenever a bug is fixed"*.
**Two summaries first** (2026-09-10: *"add this ceo style findings in
documentation so it wont happen again also add technical/dev documentation as
well"*): a **CEO** block — 3 bullets, no code, no file names, what they saw or
lost, why in one plain sentence, what stops it now — then a **DEV** block — 3
bullets, the failing call path as `file.py:line`, the invariant that broke named
as a rule, and the guard by test name. They asked because the entries had become
unreadable to them: `_missing_ok` returning its default is true and useless to
the person whose filter went blank. Neither summary replaces the fields below.
Then seven fields, all of them: what they SAW, the numbered TIMELINE with measured
numbers (before AND after), the ROOT CAUSE line, **WHY IT WAS NOT CAUGHT**, the
COST in dollars or "none", the FIX commit, and the GUARD test.
The fourth field is the whole point. On 2026-09-09 four bugs were fixed and in
**two** of them a test written for exactly that fault was passing at the time:
one counted `p.set("days"` across a whole file while the function that mattered
had zero, and one grepped for `.toLocale` while a `Date` was being sliced by
hand. Three permanent rules in this file were bought by that field — *filter
where the data is*, *a guard is only as wide as its pattern*, and *a count is
not a location*. Fires on a real defect only, never on a feature, refactor or
rename. `tests/test_rca_log.py` holds the shape and the registration.

## Test the path the RUNNER takes, in the state it will run in (MANDATORY — 2026-09-05)

The operator: *"It means you are not reviewing your code changes and testing
it"*. They were right, and the receipt is exact.

On 2026-09-04 the one-position-per-coin rule shipped with ELEVEN passing tests.
The runner then traded NOTHING for nine hours — 548 identical `blocked` rows
between 10:55pm and 8:01am, zero entries, both books — because a THIRD per-coin
guard (`timeframe_conflicts`, inside `run_cycle`) refuses any coin armed LIVE
on two bar sizes, and the operator's 35 rows put GPNSTOCK on 15m and 30m.

Three failures, each avoidable:

* **The tests drove `process_symbol`. The runner enters through `run_cycle`,**
  which returned before ever reaching it. A test one layer below the entry
  point proves nothing about the entry point. Drive the function the process
  actually calls, with the operator's own settings shape.
* **The verification ran in the wrong STATE.** The runner was confirmed working
  at 10:41am while every row was paper-only; the guard is LIVE-ONLY and armed
  at 10:55pm. Verify in the configuration the operator will actually run —
  live-armed, multi-coin, multi-timeframe — or say plainly that you could not.
* **One rule was replaced in two places out of three.** `timeframe_locks` and
  `deploy_preset._claims` were found by NAME; `timeframe_conflicts` was not.
  When changing a rule, grep for the CONCEPT (every guard keyed on the same
  subject) and list them all before editing.

And nothing raised a hand for nine hours: cycles ran, the ledger filled with
identical refusals, and no alarm anywhere says *"the runner is up and has taken
no action"*. A refusal repeated every cycle is a silence, not a message —
rate-limit it (`_say_once`) and count it somewhere the operator reads.

## Read the emitter, not the label (MANDATORY — 2026-08-18)

23. **Before explaining ANY log line, ledger action, counter or status string,
    open the code that writes it.** Not the name, not the docstring — the branch.
    `stale_skip` reads as "a trade signal was skipped". It is actually written when
    a bar ages past 30 minutes, and because the no-signal path never marks a bar
    seen, EVERY quiet hour emits one at HH:30. On 2026-08-18 that produced three
    confident wrong answers in a row — "94.8% of signals refused", then "your
    network is dropping", then "a crash is costing you hours" — each backed by real
    measurements resting on a premise never checked. The operator asked four times
    before the emitter was read. Counting rows is not understanding them.
24. **A percentage needs its denominator named out loud before it is spoken.**
    "94.8% refused" was skips ÷ (skips + entries), across BOTH books, of rows that
    were not refusals. Say what is being divided by what, or do not say the number.

## Pre-deploy rule (MANDATORY — bought with a live wrong deploy, 2026-08-17)

21. **Backtest the EXACT combination you are about to deploy, and paste its numbers
    before touching the config.** All six fields: coin + timeframe + signal + TP + SL +
    **sizing**. Not the row the operator pointed at, not a neighbouring row, not the
    same barriers at a different sizing — the literal thing that will run.
    On 2026-08-17 a config was taken from a FLAT-only survivor list and deployed with
    the ladder on, because the operator asked to keep the ladder. Flat it was +$141;
    laddered it was −$21 with a $339 drawdown on a $65 account. The combination had
    never been tested, because it appeared in no list. Sizing is not a dial you turn
    after choosing a strategy — it is part of the strategy.
    Verifying that the spec exists, the ladder step survived, the key is in
    STRATEGY_ORDER and the runner fetched the right candles proves the deploy WORKED.
    None of it asks whether it makes money. Run the backtest.
22. **When the operator says "deploy this", name the exact row back to them before
    writing anything** — coin, timeframe, signal, TP, SL, sizing, and its profit. Their
    "this" and yours were different rows in two different tables, and nothing in the
    deploy caught it.

## Strategy search rules (MANDATORY — operator directive)

18. **Every strategy request runs a FULL grid** — see `.claude/skills/full-grid-search`.
    All coins × timeframes **15m, 30m, 1h, 4h, 1d** × **every signal in
    `backtest_report.SIGNALS`** (75 as of 2026-08-19 — read the registry, never hardcode
    the count; it grows via the research rule in the analyze skills) × **≥3 TP/SL pairs per
    timeframe** × **both sizings (flat AND martingale)**. One combination =
    coin + timeframe + signal + TP + SL + sizing, and every one of those six
    fields varies.
19. **Flat sizing is always tested.** The martingale ladder is a sizing choice,
    not a measurement: an audit proved the "13/13 green months" behind six live
    strategies was produced by the ladder, not the signal (flat: 7/12–11/12).
    **BOTH ARE MEASURED (restored 2026-09-11).** The ladder was cut from the
    grid that morning on *"i only want flat so you will need to delete
    marigingalte for my backtest as well"* and put back hours later on *"i want
    the martingale back to backtest results and include the filter martingale
    again in filter"* — before the purge of the existing rows had finished, so
    712 pair files had already lost theirs and were restored from the index.
    What survives from that round trip is worth keeping: `SIZINGS` is ONE
    definition (it had been declared twice in `backtest_report`, the second
    shadowing the first) and every measuring path reads it —
    `fast_grid.combo_six`, `.github/scripts/sweep_shard.py` and
    `market_sweep.run_pair`, two of which carried `("flat", "martingale")`
    inline. So changing this dimension is now one line, and the fleet can never
    measure a sizing this PC is not asking for.
20. **Never drop a dimension silently.** Pre-filter coins by the liquidity gate per
    timeframe and state how many were excluded and why. A capped grid says what it capped.
