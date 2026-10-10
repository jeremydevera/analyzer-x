# Gate phase 3 — GitHub measures on Gate

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Every GitHub job (sweep v1/v2, replay, research, forecast, download, learn, ml) measures on Gate, and the v2 exits settle on the finest bars Gate has (spec D10).

**Spec:** `docs/superpowers/specs/2026-10-10-switch-to-gate-design.md` (D9, D10).

## Global Constraints

- The workflows' `TA_VENUE: gate` is pushed IN THE SAME HOUR as the cutover, never before: a Gate row reaching a PC still on MEXC is refused (`land_rows`), and tonight's 1:00am re-test and the daily update would both be wasted.
- `sweep.yml` is at GitHub's ten-input ceiling: the exchange is a workflow-level `env`, never an input.
- Both accounts (`origin`, `colleague`) get every commit.

## Review Focus

1. A Gate contract younger than the window → measured on what exists, never refused for depth (rule: no bar floor).
2. Funding paged ~30 days at a time → `since_ms` = the window's first bar, or each pair walks years of pages five times.
3. The v2 minutes for the current month → 5-minute bars in the hole (`fx.minutes`), counted, never silently the bar rule.
4. A row id on GitHub must equal the id the PC computes for the same row (both hash `venue=gate`).
5. A MEXC run still in flight at the cutover → its rows refused by name at collect, never filed.

### Task 1: the shard asks for minutes and funding the Gate way

**Files:** `.github/scripts/sweep_shard.py`, `tradingagents/dataflows/mexc_futures.py` (`minutes()` for parity); Test `tests/test_gate_shard_inputs.py`.

- [ ] Tests: under gate the v2 path calls `fx.minutes(sym, window_start, now)` and passes `(t_ms, high, low)` built from it; under mexc `fx.minutes` = the old `klines(Min1, 44000)` frame; `fx.funding_history(sym, since_ms=window_start)` is what both paths call; a row counts the exits decided in a 5-minute bar (`fine5`).

### Task 2: every workflow on Gate

**Files:** the seven `.github/workflows/*.yml` that run a script; Test `tests/test_every_workflow_names_the_exchange.py`.

- [ ] Test: each workflow that runs a `.github/scripts/*.py` sets root-level `env: TA_VENUE: gate`; none takes it as an input.
- [ ] Pushed with the cutover (phase 2 Task 3), not before.

### Task 3: one GitHub run, landed

- [ ] After the cutover: press UPDATE ALL BACKTESTS (v2) the way the button does (`db_jobs.start("btupdate_v2", spec)`), watch both accounts to the end (press-and-watch), collect into the Gate store, and read three rows back by id.
