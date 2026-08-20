# Storage split: Neon keeps the irreplaceable, Parquet keeps the bulk

**Date:** 2026-08-20 · **Approved by the operator:** "okay im gonna use my own
disk lets do it"

## The problem, measured

A full-market sweep produces ~28.9M candles and ~38.6M strategy rows. In
Postgres that is ~20 GB against Neon's 0.5 GB free project. Measured on the
operator's real data (123,859 candles, 9,667 strategy rows), the same rows as
zstd Parquet are **14x smaller**: full market ≈ **2.0 GB**, which fits the
operator's own disk trivially.

The split follows one rule: **a database for what cannot be recomputed, files
for what can.**

## What stays in Neon (the existing free project)

| table | retention | why |
|---|---|---|
| `trade_ledger` | forever | the record of real money; irreplaceable |
| `deployments` | forever | what was live when; irreplaceable |
| `backtest_results` | best 500 rows per (symbol, timeframe, data_end, code_version) | answers every question asked so far; ceiling ~0.35 GB |
| `candles` | only coins with a live strategy | the app's hot path; ~40 MB |

## What moves to Parquet on disk

Root: `~/.tradingagents/parquet/`

```
candles/<SYMBOL>-<tf>.parquet         one file per contract+timeframe, zstd
grids/<YYYY-MM-DD>-<label>.parquet    one file per completed sweep snapshot
```

- Written with pandas/pyarrow (already installed). No new services, no accounts.
- Candle files are the SAME shape `fx.klines` returns, so a backtest can read
  them in place of the network.
- A grid snapshot is every row of one sweep — the full 17k-per-pair record the
  database prunes. Losing a file costs a re-run, never history.

## Components

1. **`tradingagents/parquet_store.py`** — save/load candles, save/load grids,
   `sizes()`. Mirrors `market_db`'s API shape so callers switch by one import.
2. **Retention in `market_db`** — `prune_results` already exists; add
   `retention_tick()` that (a) prunes results to 500/pair, (b) deletes candles
   for coins with no live strategy, and reports what it did. Called from the
   app after each save, never silently.
3. **Sweep integration** — the market sweep and the archive backtest write
   their full grid to `grids/` BEFORE pruned rows go to Neon, so the database
   diet never destroys data that was not yet on disk.
4. **Backtest 2 storage panel** — one table: each store, rows, bytes, last
   write, so growth is visible before it is a problem.

## Error handling

- Parquet writes are atomic: write to `<file>.tmp`, then rename.
- A failed Parquet write ABORTS the prune (rule 3 above): never delete from
  Neon what disk does not yet hold.
- Neon down: Parquet still written; sync resumes later (existing stand-down
  machinery).

## Testing

- Round-trip: candles df -> parquet -> df identical (dtypes, order, values).
- Retention: 500/pair kept, best kept, prune aborted when the grid write fails.
- Traded-coins rule: candles for a disarmed coin are deleted, armed kept.
- Sizes: `sizes()` reports every store.

## Out of scope (deliberately)

- DuckDB query layer over the files (pandas covers today's questions).
- Mirroring Parquet to R2/GitHub (add when runners need shared reads).
- Any change to how GitHub runners ship artifacts.
