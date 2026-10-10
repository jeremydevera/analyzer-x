# Gate phase 4 — every trade pays the order book of its own minute

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The backtest charges each trade the cost Gate's order book really had at its entry minute and its exit minute, and refuses an entry the runner's cost check would have refused at that minute — the part of the backtest/practice gap measured at ~85% of missed trades (Oct 09, 2026: backtest 59,511 trades against practice 2,939 over the same hours).

**Spec:** D11 in `docs/superpowers/specs/2026-10-10-switch-to-gate-design.md`.

**Measured facts it rests on (Oct 10, 2026):**
- `download.gatedata.org/futures_usdt/orderbooks/YYYYMM/<C>-YYYYMMDDHH.csv.gz`: one hour per file, published ~2 h after; a `set` snapshot then every change merged per 100 ms; columns `timestamp, action, price, size, begin_id, merged`.
- Positive size = buy side, negative = sell side; `make` ADDS the size, `take` SUBTRACTS it: BTC Oct 09 00:00-01:00 replayed this way equals the 01:00 snapshot on 41,387 of 41,387 levels.
- Sep 30 – Oct 08 12:00, 2026: snapshot-only files (one book an hour).
- 0.84 MB per coin-hour on average → ~21 GB a day for 1,027 coins; ~2.3 billion events a day → ~40 CPU-minutes at 1 µs an event, ~1 minute per machine across 40.

## Global Constraints

- The runner's rule is the rule: the backtest calls the SAME verdict function `edge_check` uses (`auto_trader.cost_verdict`, extracted), never a copy.
- Size = the runner's: `$5 margin x 20 = $100` notional (`auto_trader.LEVERAGE`, the base margin of the run).
- A minute with no reading uses the newest reading of that coin up to 60 minutes old; older or none → the static per-contract cost of today, and the row COUNTS it (`cost_unmeasured`).
- Results live where both accounts' machines can read them without a key: a GitHub release per month on each account, one asset per day per account (`costs-YYYYMMDD-a<i>.npz`).

## Review Focus

1. A snapshot-only hour → the hour's opening book answers every minute of it, flagged `source=snapshot`.
2. A level whose size goes negative from a `take` larger than it holds → removed, never a negative book.
3. A crossed book (best bid ≥ best ask) after replay → that minute has no reading, never a negative spread.
4. A day file missing for one account → the shard uses what exists and counts the rest as unmeasured; it never stops.
5. The engine with `book=None` is byte-identical to today (`backtest_strategy` parity on 200 hours).

### Task 1: `book_history` — one hour in, sixty readings out
**Files:** Create `tradingagents/book_history.py`; Test `tests/test_book_history.py` (a hand-built hour + the real BTC Oct 09 00:00 file's first minutes checked against its 01:00 snapshot in an integration test).

### Task 2: `cost_verdict` — the runner's rule as a pure function
**Files:** `tradingagents/auto_trader.py` (`edge_check` calls it); Test `tests/test_cost_verdict_is_the_runners.py` (every branch of `edge_check` — ratio, exhausted, stop inside the gap, funding eats, funding blind, stop past liquidation — gives the same verdict through both).

### Task 3: the engine pays the minute
**Files:** `tradingagents/auto_trader.py` (`backtest_strategy(book=...)`); Test `tests/test_backtest_pays_the_minute.py`.

### Task 4: `costs.yml` — the daily job on 40 machines
**Files:** `.github/workflows/costs.yml`, `.github/scripts/costs_shard.py`, `tradingagents/cloud_sweep.py` (dispatch across both accounts); Test `tests/test_costs_job.py`.

### Task 5: the v2 shard reads the day files
**Files:** `.github/scripts/sweep_shard.py`; Test extends `tests/test_gate_shard_inputs.py`.
