# Candles v2 + Backtest v2 — minute-exact exits (design)

**Date:** Sep 17, 2026 · **Asked by the operator:** *"lets do a v2 of candles tab
... default to 1min ... then same for backtest, lets create backtest v2, it should
analyze the 1min candles ... do not replace the existing backtests strategies ...
we will use 1min candle so its more accurate"*.

**Decision (operator, same day, on the one question that changes the work):**
v2 keeps the SAME signals on the SAME timeframes and only makes the EXIT
minute-exact. A 1h strategy still decides on the finished 1h bar; the win/lose
price is then checked minute by minute. Brand-new 1-minute strategies were
offered and declined.

## Why

`#LG9NSU4B` (XPIN 1h ote, TP 1% / SL 3%) stopped out in the practice account at
`Sep 16, 2026 7:28am`; the stored backtest says `7:00am`, because an hour candle
only carries open/high/low/close. When one bar touches both prices the engine
books the loss (`fast_grid.walk` / `backtest_strategy`: SL before TP) — a guess.
Measured on the operator's five running rows: 2 of 208 exit bars held both
prices; 86 of 4,000 hour bars were wide enough to. Small, but a guess on the
number they deploy by.

**Proved before designing:** 60 one-minute MEXC candles rebuild MEXC's own
hour candle exactly — XPIN, 666 of 666 hours, open/high/low/close identical,
volume within 0.1% on 665. So signals on rebuilt bars ARE the v1 signals; v2
differs from v1 only in exit resolution.

## Approach: same machinery, a v2 folder

The existing download and sweep code already switch roots on environment
settings: `market_sweep.HOME` ← `TRADINGAGENTS_SWEEP_HOME`, `market_sweep.CANDLES`
← `TRADINGAGENTS_CANDLES`, `rows_index.DB_PATH` ← `TA_ROWS_DB`. v2 jobs are the
SAME job bodies launched as their own job kinds with those settings pointed at
`~/.tradingagents/v2/`. v1 files on disk are never opened for writing by a v2
job. One engine, one signal registry, one barrier grid — nothing to drift.

Rejected: a copied engine under `v2/` (a second copy of the exit rules — the
drift this repo has paid for five times); one store with tagged rows (mixes
30-day rows into a 113,495,608-row, year-deep ranking and needs a 41.94 GB
rebuild to add a column).

## Stores

```
~/.tradingagents/v2/
  candles/        1m only: SYMBOL-1m.parquet (market_sweep cache format)
  state/          per (coin, tf) resume states, as v1
  rows/           per (coin, tf) row files, as v1
  rows.db         the v2 row index (same schema + `unclear` column)
  manifest.json
~/.tradingagents/parquet-v2/candles/   the parquet copy the download job writes
```

`parquet_store.ROOT` gains an env override (`TRADINGAGENTS_PARQUET`) so the v2
download job's parquet copy lands beside the v2 store, not in v1's.

The 1m store ACCUMULATES: `refresh_candles` appends the minutes since the last
stored bar and keeps `days + 30` = 395 days. MEXC sells 30 days of 1m at once
(measured: BTC 44,000 bars = 30.6 days; ARKM 25 days back answered 2,000 bars),
so the first download is 30 days and every daily UPDATE extends it.

## Timeframe table

`backtest_report.TFS["1m"] = ("Min1", 60, 44000)`. Only the v2 download uses it
as a DOWNLOAD timeframe. It is NOT added to `capacity.ALL_TFS`, to any hardcoded
`("15m","30m","1h","4h","1d")` list, or to the barrier grid, so no v1 job, no
cloud shard and no completeness count ever sees a 1m pair.

## Bars from minutes

`market_sweep.bars_from_1m(df_1m, tf) -> df` resamples on UTC bar boundaries
(open=first, high=max, low=min, close=last, volume=sum), keeps only bars whose
minute count is complete for the frame (60 for 1h, 240 for 4h, 15 for 15m...),
except the last bar which is the forming one and is dropped as v1 does. A pair
whose rebuilt bars disagree with a fresh MEXC bar of that frame on any of
open/high/low/close is REFUSED and NAMED in the progress file (rule 20), never
measured.

## The engine change (shared, default-off)

`auto_trader.backtest_strategy(..., fine=None)` and `fast_grid.walk(...,
fine=None)`. `fine` is `(t_ms, high, low)` arrays of 1-minute bars covering the
frame. When `fine is None` behaviour is byte-identical to today (a test runs
both on the same frame and asserts equal output). When given, the exit walk for
bar `j` iterates the minutes in `[open(j), open(j)+bar_s)` in order:

* first minute whose low ≤ SL (long) → SL, exit minute recorded
* first minute whose high ≥ TP → TP
* liquidation first when nearer, as today
* both in the SAME minute → SL (still the worst case) and `unclear += 1`
* the entry price stays `opens[i+1]` (the first minute's open — identical)
* the log's exit time is the MINUTE, so `#LG9NSU4B` reads `7:28am`

`unclear` travels on the row: `rows_index.COLS` gains it (v2 db only; the v1 db
is never migrated — its rows have no `unclear` and the column is absent there).
Funding windows use the bar's minute for the exit, so a stop at `:28` pays
funding up to `:28`, not to the top of the hour.

## Row identity

`backtest_report.row_code(..., res=None)`: `res="1m"` is appended to the seed
only when given, exactly like `plan`, so every v1 id still hashes to itself and
no v2 id can equal a v1 id. v2 rows keep `tf="1h"` (the frame the signal ran
on) so the timeframe filter works unchanged.

## Jobs

`db_jobs.FILES` gains `download_v2` and `backtest_v2` (own progress/spec/pid/
stop/log files). `start()` sets the four environment settings for those kinds
before spawning. `main()` dispatches them to `_run_download` / `_run_backtest`
unchanged, except: the download whitelist accepts `"1m"` for `download_v2`, and
`_run_backtest` for `backtest_v2` runs LOCALLY (the 1m candles live here; the
cloud has none) through the existing worker pool with `fine=` supplied per pair.
`LOCAL_SWEEPS` stays False for v1. One job at a time across BOTH versions: a v2
start while any v1/v2 job holds the disk is refused with the holder named.

## API

`/api/v2/candles/*`, `/api/v2/jobs/*`, `/api/v2/strategies*` — the same handlers
parameterised by a `Store` (paths + db) object; the v1 routes pass the default
store. `rows_index.query/query_sql/status/export_plan/_connect` take an optional
`db_path`; default unchanged. `market_sweep.candle_index/stored_symbols/
update_pairs` take an optional `root`; default unchanged.

## Screens

* Sidebar: **Candles v2** (`/candles-v2`), **Backtest v2** (`/backtest-v2`).
* `DownloadScreen` gets `store="v2"`: timeframes fixed to `["1m"]`, the picker
  hidden, the "contracts × 5 timeframes" line reads "× 1 timeframe (1m)", a
  `v2 · minute-exact exits` badge in the heading, and the UPDATE button copy
  says it extends the 1m history.
* `JobsPanel` + `StrategiesPanel` + `BacktestStorage` get `store="v2"`: they
  call the v2 API, show the `unclear` column beside `losses`, and print
  `days` honestly (30 at first). BACKTEST and UPDATE ALL run locally; the
  RUN ON GITHUB button is not shown on v2.
* Every v1 screen is byte-identical.

## Failure paths

* a coin's 1m download breaks → redone by itself after the others, named if
  lost, next UPDATE re-queues it (v1 rules, same code)
* rebuilt bars ≠ MEXC's → coin refused and named in the progress file
* a v1 job is running → v2 start refused, holder named (`db_jobs.busy_job`)
* 1m store younger than a signal's lookback → no trades, row's `bars`/`days`
  say so; no floor invented (CLAUDE.md: there is no bar floor)
* API asked for a v2 store that does not exist yet → `{"rows": [], "total": 0,
  "why": "no v2 store yet — download 1m candles first"}`, never a 500

## Measured costs

* first 1m download: 22 pages × 1,056 coins = 23,232 requests at 0.12–0.8 s
  → ~1.5 h; daily UPDATE 1 page/coin → ~5 min
* measuring: barrier settle 0.79 ms vs 0.05 ms per combination (ARKM) → ~23 s
  vs 1.4 s per coin-timeframe → 5,280 pair-timeframes ≈ 34 h on one core,
  ≈ 3 h across 12 workers
* disk: ~2.5 GB of 1m candles (×3 copies incl. kline_cache and parquet) on G:,
  538 GB free

## What shipped (Sep 17, 2026) — where it differs from the design above

* `fast_grid.walk(fine=)` was NOT built: v2 rows come from `market_sweep.run_pair`
  → `backtest_strategy`, the only path a v2 measure takes. The click-path grid
  (`fast_grid`) stays v1-only.
* `unclear`/`res` live in ONE schema: `rows_index.COLS` gained them and
  `ensure()` adds them to an existing table with `ALTER TABLE ADD COLUMN`
  (metadata only, no pass over the 41.94 GB v1 file). A v1 row has NULL there.
* The API reads v2 through `rows_index.using_db(path)` — a ContextVar set and
  reset in the request thread — with `db_path=` on the readers; the CSV
  generator, drained by Starlette's threadpool, goes through `iter_rows_in`,
  which scopes the override around EACH `next()`. `market_sweep.candle_index`
  takes `root=`; `db_jobs.pending_work` takes the store's lost file, candle dir
  and frames; the v2 download writes the `candles_v2` pending ledger.
* The web client reaches `/api/v2` through `withApiPrefix`, which rebases the
  path inside `get`/`post` before the first await — the URL builders the tests
  read field by field are byte-identical to v1's.
* A v2 job refuses to start while ANY disk job runs, and a v1 job while a v2
  one runs (`db_jobs.JobBusy`, 409); v1 kinds among themselves are unchanged.
* The v2 sweep files its own rows at the end (`rows_index.sync(force=True)`)
  — nothing else watches the v2 folder — and writes `archive-v2.html`.
* Found by pressing the buttons: `fx.klines_backfill` fills a cached history
  from the FRONT when a frame is shorter than its cap (RCA-2026-09-17-A).
* First real run: five coins on 1h, 30 days → 82,758 rows filed into
  `~/.tradingagents/v2/rows.db` (29 MB); `#LG9NSU4B`'s v2 twin is `#U9YP5N7L`
  and its Sep 16 stop reads `7:28am`.

* Later the same evening (commit `56ed9d67a59b`): the days/months window on
  Backtest v2 re-measures from the 1m store (`api._STORE` ContextVar →
  `restate_window(store=)` → `window_rows(store=)`); the trade-by-trade log
  for a v2 row (`POST /api/v2/strategies/trades` → `trades_for(store=)`,
  Playwright: 585 exit stamps, 42 off the hour); UPDATE ALL BACKTESTS on v2
  (`btupdate_v2`, always on this PC); deploy from a v2 id (`deploy_preset`
  writes `strategy_res`, `row_id_for` prints the v2 id). The v2 CSV still
  refuses a window, with why.
* UPDATE CANDLES on Candles v2 names the never-stored pairs it will fetch in
  full (RCA-2026-09-17-E) — the first press queued 1,003 pairs behind a
  sentence about 5.

## Out of this cut

Cloud measuring for v2 — the fleet has no 1m store, so every v2 measure runs
on this PC.

## Tests (guards, all new)

* `bars_from_1m` reproduces MEXC's own bars exactly on a recorded fixture, and
  refuses a frame with a missing minute
* `backtest_strategy(fine=None)` output equals today's on a fixed frame (byte
  identical dict), for flat and martingale
* with `fine`, a bar that holds both prices resolves by minute ORDER (TP first
  → TP), the same-minute case books SL and counts `unclear`, and the exit time
  is the minute
* `row_code(res="1m") != row_code()` and `row_code()` unchanged for every
  stored id in a fixture
* v2 job kinds spawn with the four env settings and a v1 kind spawns without
* `"1m"` is absent from `ALL_TFS`, from the barrier grid and from every
  hardcoded five-frame list (AST/regex guard)
* the v2 API answers an empty store with the sentence above, never a 500
* Playwright: both new tabs render, Candles v2 shows `1m` only, Backtest v2
  shows the `unclear` column and the badge
