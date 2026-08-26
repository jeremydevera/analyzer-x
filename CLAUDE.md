
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
   months green (a count), max worst dip, and **last N months** — which RE-RUNS every row
   over that slice of candles rather than hiding rows, so profit, trades, wins, losses and
   win rate are the window's own; print the window's real dates beside the row count, and
   REMOVE the month columns outside the window rather than filling them with em dashes — live-typing, stacking, measured at the CURRENT base
   margin, with the active filters named in the row count and a clear-all button.
   **Every filter takes the unit its column PRINTS**: GREEN prints `11/12`, so the box
   counts months — set 10 and a 9/12 row must vanish. A percent box beside a count column
   reads as broken, because 11 typed as a percent matches everything. And when a filter
   cannot cut anything in the current view, print why beside the count.
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
- The bar floor is PER TIMEFRAME (`backtest_report.MIN_BARS`, shared by the
  local sweep and the cloud shard). A flat 500 made 1d impossible: a year of
  daily bars is ~395 and the 60-day sweep of 2026-08-25 gave ~90, so all 997
  1d pairs were excluded as "only 90 bars" while the run reported five
  timeframes. 1d's floor is 60 bars; depth is the row's own `days`/`bars`.
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

Any strategy analysis and the app's `1 YEAR` backtest button MUST run the same grid from
`tradingagents.backtest_report` — never widen it locally for an artifact. They diverged
once and the operator could not find a single recommended row inside their own app.

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

ALWAYS ON — `short-answers`. STRICT, and the operator's last warning after five
requests. Hard caps: a fact = 1 sentence. "why" = 3. "explain" = 6. Reporting
work done = 3 plus the numbers. Over the cap, delete paragraphs before sending.
No unrequested caveats, no "worth noting", no stapled second findings, no recap
of the reply just given, no offering the next three things. Verify as rigorously
as ever — then report only the answer.

ALWAYS ON — `one-word`. A factual question gets the fact and nothing else. No table
for a single number, no "worth noticing", no restating the question, no re-explaining
what is settled. Expand ONLY when asked why/how/explain, when a qualifier is part of the
fact, or when a table/artifact is requested. Verify as thoroughly as ever — then report
only the answer. The operator has asked for this twice: "give me options short and
accurate" and "can you just tell me in 1 word ... this is getting annoying".

ALWAYS ON — `say-done`. After finishing ANY task the operator asked for — code
changed, sweep finished, artifact published, bug fixed — speak one calm sentence
out loud (under ~12 words, no "sir" — removed 2026-08-20). One utterance per
finished task, not per tool call, never for a mid-task status update, never after
a failure. NEVER call `say` directly — always the script below, which reads
`.claude/skills/say-done/config.json` at speak time so operator edits apply live:

```bash
bash .claude/skills/say-done/speak.sh "<what was finished>" &
```

ALWAYS ON — `plain-words`. The operator is new to crypto trading and said so:
"I don't know the terms you are talking about." Define a term the first time it
appears, in six words or fewer. Lead with what it MEANS for them, then the number.
Use money, not ratios. One idea per sentence. This is not optional and does not
wait to be invoked — it was skipped for an entire session of leverage, drawdown
and liquidation answers, which is exactly when it mattered most. It combines with
`one-word`: answer short AND in plain language, not one or the other.

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
    timeframe** × **both sizings (flat AND martingale)**. One combination = coin +
    timeframe + signal + TP + SL + sizing, and every one of those six fields varies.
19. **Flat sizing is always tested.** The martingale ladder is a sizing choice, not a
    measurement: an audit proved the "13/13 green months" behind six live strategies was
    produced by the ladder, not the signal (flat: 7/12–11/12).
20. **Never drop a dimension silently.** Pre-filter coins by the liquidity gate per
    timeframe and state how many were excluded and why. A capped grid says what it capped.
