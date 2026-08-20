# Store-first analysis: nothing computes twice

**Date:** 2026-08-20 · **Approved:** "i want everything stored" / "when doing
analysis its not doing from scratch"

## The problem

Four paths run backtests; only one reuses work. The 1 YEAR button recomputes
~5 minutes per click, and chat analyses recompute 17k combinations per coin,
every time, even when the store already holds yesterday's answer and only 96
new bars exist.

## The rule

**Every analysis reads the store first and computes only what is new.**
`market_sweep.run_pair` already does this per (coin, timeframe): rows on disk,
per-combination resume state, incremental over new bars. It becomes the ONLY
way grids are produced.

## Changes

1. **Everything stored — losers included.** `run_pair` currently skips rows
   with `profit <= 0`; "everything stored" means they are kept. The trade
   floor (`MIN_TRADES`) stays: a 3-trade row is noise, not a loser.
2. **`backtest_report.grid_from_store(coins, tfs, *, thresholds, deployed,
   progress)`** — assembles a `run_grid`-shaped payload from `run_pair`
   results: rows from the store, candles for in-page replay from the
   parquet/disk cache, deployed combos injected and computed if the store
   lacks them (rule 21: the exact live combination must exist).
3. **All callers funnel through it:** the app's 1 YEAR button, Backtest 2's
   archive run, and the analysis skills (documented in `analyze1hr4hr`,
   `analyze15m30m`). `run_grid` itself remains for cold computation — it is
   what `run_pair` calls per pair.
4. **Provenance, spoken aloud on the page:** every artifact/table built from
   the store states `N rows from the store · M new bars tested · K rows
   recomputed`, so reuse is visible and a stale number is traceable.
5. **Retention unchanged:** grids to parquet, best-500 to Neon, prune only
   after the snapshot exists.

## Error handling

- Store unreadable → compute fresh (the old path), say so in provenance.
- A store row whose `code_version` (signal count) differs from the current
  library is recomputed, not trusted.

## Testing

- run_pair keeps losing rows; floor still applies.
- grid_from_store: reuses stored rows (no engine calls on second run),
  computes only the missing deployed combo, provenance counts correct.
- version mismatch forces recompute.
