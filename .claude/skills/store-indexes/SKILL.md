---
name: store-indexes
description: Use after ANY sweep, backtest, bulk fill, schema bump or store rebuild, whenever a Stored-strategies query is refused for a "missing index", and before reporting any store change done. The row store's on-demand indexes are NOT created by a backtest and NOT created by `ensure()` — so the panel silently loses whole features (Preset Confluence, #id lookup, win % floors) until somebody builds them, and each one is 30-70 minutes.
---

# The store's indexes are not maintained by anything

**A backtest writes rows. It does not build indexes.** Neither does an API start.
Four of this store's indexes exist only because somebody asked for them, and every
feature behind them dies quietly when they are gone.

## What happened (2026-08-27, the receipts)

The operator selected **Preset Confluence** and got an empty table under
*"was asked for and did not come back"*. Their words: *"i did a backtest to
another session why was this not built?"*

1. `rows_cf_profit`, `rows_cf_winrate`, `rows_cf_trades`, `rows_cf_dd` were added
   in code that morning. They are deliberately **not** in `KEEP_INDEXES` — four
   more indexes would be paid for by every fill — so they are built ON DEMAND.
2. A backtest ran in another session. It inserted rows. Indexes that do not
   exist are not created by inserting rows, so nothing changed.
3. `ensure()` (every API start) creates `KEEP_INDEXES` only, on purpose: creating
   all of them there cost **13 minutes of every startup** (`rows_winrate` alone
   measured 912 s).
4. The on-demand build *did* fire — inside the API, in a daemon thread — and the
   API was restarted several times that afternoon shipping other fixes. Each
   restart killed the scan mid-way while the screen kept promising *"it is being
   built in the background"*. An hour of that, nothing landing. (Fixed: builds
   are now detached child processes, `_build_index` → `--build <name>`.)

Cost when they are missing, measured on the operator's 35.9M-row store:

| index | what dies without it | build time |
|---|---|---|
| `rows_pr2` | flat/martingale, TP and win % floors ranked by profit (503 at 20 s) | **4,291 s** |
| `rows_id` | the `#id` lookup (a 40 s+ full scan) | **1,982 s** |
| `rows_wr2` | win % floors, ranked by win % (52 s → ~1 s) | ~45 min |
| `rows_cf_*` | the whole Preset Confluence group (78.7 s a page) | minutes each (partial) |

**And a `SCHEMA_VERSION` bump drops the tables and rebuilds from the pair files,
recreating `KEEP_INDEXES` only** — so a version bump silently costs every one of
the above. That is hours of background work nobody was told about.

## The check — run it, paste it

```bash
.venv/Scripts/python -c "
from tradingagents import rows_index as ri
ri.forget_indexes()
missing = ri.missing_indexes()
print({n: ri.has_index(n) for n in ri.INDEX_DDL})
print('MISSING:', missing or 'none')
"
```

If anything is missing, start it **detached** (survives an API restart, `taskkill
/T`, and this session) and say so with the pid:

```bash
.venv/Scripts/python -c "
from tradingagents import rows_index as ri
print(ri.build_missing_indexes())      # returns the names it started
"
```

Then, before reporting anything as working:

1. **Confirm through the API, not the DB.** `has_index` caches a negative per
   process, so a finished build does not take effect in a long-lived API until
   `forget_indexes()` runs there — hit the real route and read the status code:
   `curl -s -m 90 -w " %{http_code} %{time_total}s" "http://127.0.0.1:8787/api/strategies?group=preset&limit=50"`.
2. **Never write "it is being built"** unless a live pid is building it. Check:
   `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*--build*' }`.
   A promise about a dead process is the label-must-match-data failure in prose.
3. **Report the seconds.** `build_index_now` logs `built <name> in <N>s`; that
   number is the only honest ETA for the next time.

## What each button actually does

The operator asked the right question — *"when i click backtest or update
backtest will it work too?"* — and before 2026-08-27 the answer was NO.

| the click | what it writes | who indexes it | does it build a missing index? |
|---|---|---|---|
| **BACKTEST** (a sweep) | row JSON files under `ROWDIR` | the indexer's next `sync()` | **yes, now** — any pass that indexed a pair calls `_after_fill_indexes()` |
| **UPDATE BACKTEST** (`btupdate`) | the same row files, a few pairs | same | **yes, now** (it used to skip: see below) |
| a one-coin backtest | one pair file | same | **yes, now** |
| **index the missing N pair(s)** (`POST /api/strategies/reindex`) | nothing | a forced `sync()` | yes |
| a candle DOWNLOAD | candles only, no rows | nobody | no rows, no index needed |

`db_jobs` never touches `rows_index` at all: a job writes FILES, and the index
is a separate process reading them. The check used to hang off `bulk`, which is
`len(todo) > BIG_FILL` — **500 pairs** — so a backtest of one coin, an UPDATE, the
reindex button and the trickle all skipped it. It now runs whenever a pass
indexed at least one pair; the check is 11 `sqlite_master` lookups and spawns
nothing when everything is there.

**Still not automatic:** a `SCHEMA_VERSION` bump rebuilds the store inside
`ensure()`, and `ensure()` deliberately does not build these. The first `sync()`
after it will, but if nothing needs indexing, nothing runs — so after a version
bump, run the check by hand.

## When to run it

* after any sweep, backtest, `db_jobs` fill or `reindex` — the store grew, and
  nothing in that path builds an index;
* after **any** `SCHEMA_VERSION` change, or any "rebuilding from the pair files"
  line in the log — every on-demand index is gone;
* the moment a query is refused with *needs its own index*;
* before telling the operator that a filter, a group or a lookup works.

## Do NOT

* **Do not add them to `KEEP_INDEXES` or `ensure()` to "fix" this.** That is the
  13-minutes-per-startup regression, and a bulk fill pays for every index it
  carries (measured: 1.5 pairs/min with six indexes against 75 with none).
* **Do not build them in a thread.** The API restarts; the work dies silently.
* **Do not repair a bloated file in place.** 727,146 free pages once made a
  single `DROP INDEX` outlast fourteen minutes; load a fresh file and swap.
* **Do not let the operator find out from an empty table.** If a feature needs an
  index that is missing, say which index, what it costs to build, and what works
  in the meantime (a named coin is answered now — 4.8 s for preset).
