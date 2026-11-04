# Daily trend over 3 years, and funding carry — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find out, with fees paid, whether (A) the Backtest v3 daily trend idea still beats random entries over about 3 years of Gate candles, and (C) collecting Gate's funding on a spot-long / perp-short pair pays more than its fees.

**Architecture:** A reuses the v3 pipeline unchanged except that the plan carries its own window (`window_days`, `unseen_days`, defaults 365 and 90 so every old id and plan is byte for byte the same). C is a new small, pure module over Gate's published funding history, because the v3 engine walks directional trades and a carry has no entry signal.

**Tech Stack:** Python, `tradingagents.v3_*` modules, `dataflows.exchange as fx` (Gate), pytest. Relations read from `graphify-out/graph.json`: `v3_universe.collect` → `v3_measure.windows` / `measure_coin` → `v3_proof` → `v3_per_coin`; funding comes only from `gate_futures.funding_history` (`fx.funding_history`).

**Spec:** the operator's Nov 04, 2026 ask ("okay do both"), the Oct 22, 2026 research note `docs/research/2026-10-22-why-the-system-does-not-profit.md`, and CLAUDE.md "Backtest v3 — the engine's rules". No new spec file: the choices are made here.

## Measured before planning (Nov 04, 2026, Gate, 524 coins with a spot market)

- Funding history on Gate is only about **210 days** deep (median 210; 1,000-1,345 settlements), so C can only be judged on 7 months, never 3 years. Said on every C result.
- Funding per day, % of the position: median **0.0098**, p75 0.0248, p90 0.0414, max 0.185 (last 30 days: median 0.0197, p90 0.0346).
- Holding 90 days and paying 0.55% (spot taker 0.2% + perp taker 0.075%, in and out): **302 of 524** coins earned more than the fees on their whole-history average, **282** also positive in the last 30 days. At 0.30% (maker legs): 314 and 292.
- So the average coin earns about 3.6% a year on the position and the top tenth about 15% — real, but small, and it is not "many trades".
- BTC daily candles: 2,000 served (5.5 years), enough for A.

## Global Constraints

- The venue is Gate (`TA_VENUE=gate`); never import an adapter directly, only `tradingagents.dataflows.exchange as fx`.
- Dates print as `Aug 03, 2026 8:03pm` through `positions_view.fmt_when`.
- Every trade pays entry, exit and funding, wins and losses alike (CLAUDE.md rule 9); costs read per minute where the cost store holds them, and the share that paid a typical cost is printed beside every result.
- Random entries are the luck bar; a result that does not beat them is "no edge", never "profitable".
- Results go to an artifact with the full kit (CLAUDE.md columns 1-8, items A-H) — A reuses `v3_per_coin_page`; C needs its own page only if it passes the Task 4 gate.
- Commit with `python scripts/commit_own.py`, push to origin, colleague and teammate.
- Nothing in this plan switches a strategy on or touches real money.

## Review Focus

1. A coin with a spot market but a contract that settles every 1 or 4 hours (funding stamps on 8-hour cycles are not assumed): earnings are summed from the published settlements, never `rate x 3 x days`.
2. A coin whose funding turns negative while the carry is open: the position pays, and the result must show the loss, not the average.
3. A coin with no spot market (stock tokens, indices): left out BY NAME with the reason, never dropped.
4. A plan window longer than the candles a coin has: the coin is judged on what it has (rule 20), and the window each row used is printed.
5. A plan built with the new window fields must produce the SAME id as before when the fields are left at their defaults.

---

### Task 1: The plan carries its own window (test A, part 1)

**Files:**
- Modify: `tradingagents/v3_universe.py` (`WINDOW_DAYS` use at lines ~236, ~310, ~369 in `build`, `build_all`, `collect`)
- Modify: `tradingagents/v3_measure.py:73` (`windows`)
- Test: `tests/test_v3_plan_window.py`

**Interfaces:**
- Produces: `collect(..., window_days: int = WINDOW_DAYS, unseen_days: int = UNSEEN_DAYS)`; a plan stores `window_days` and `unseen_days` ONLY when they differ from the defaults; `v3_measure.windows(plan)` returns `(start_ms, end_ms - unseen*DAY_MS, end_ms)` using the plan's `unseen_days` when present.
- Consumes: `v3_universe.plan_id(plan)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_v3_plan_window.py`:
  - `test_default_plan_id_is_unchanged`: build a small plan with the defaults and assert its `plan_id` equals the id computed before this change (pin the string from `research/v3/plan-all.json`'s `id`, `a36077ee3f993e46`, by rebuilding from its own stored inputs).
  - `test_a_longer_window_changes_the_id`: `window_days=1095, unseen_days=365` gives a different id and `windows(plan)` returns a start 1,095 days before `end_ms` and a split 365 days before it.
  - `test_default_plan_has_no_window_keys`.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_v3_plan_window.py -q` — expect FAIL.
- [ ] **Step 3: Implement** the two parameters; write the keys into the plan only when non-default; `windows` reads `plan.get("unseen_days", UNSEEN_DAYS)`.
- [ ] **Step 4: Run** the new tests and `tests/test_v3_universe.py tests/test_v3_measure.py tests/test_v3_all_plan.py` — expect PASS.
- [ ] **Step 5: Commit** with `commit_own.py`, message naming the ask and the unchanged id.

### Task 2: Run the daily families over 3 years (test A, part 2)

**Files:**
- Modify: `tradingagents/v3_research.py` (a `--families` option on `run`/`judge`, only the daily families `v3_trend`, `v3_breakout`, `v3_strength`)
- Create: `research/v3/plan-long.json` (data)
- Test: `tests/test_v3_research_families_option.py`

**Interfaces:**
- Consumes: Task 1's `collect(window_days=1095, unseen_days=365)`; `vf.FAMILIES`, `vf.applies(plan, family, sym)`.
- Produces: `v3_research run --families trend,breakout,strength` measures only those families and records the list in `verdicts.json`.

- [ ] **Step 1: Test** `test_families_option_limits_combos`: with `--families trend`, `combos()` contains no breakout, strength or snap names.
- [ ] **Step 2: Run** — expect FAIL. **Step 3: Implement.** **Step 4: Run** — expect PASS.
- [ ] **Step 5: Build the plan**: `python -m tradingagents.v3_research plan --kind all --window-days 1095 --unseen-days 365 --out research/v3/plan-long.json`; the printed counts name every coin without 3 years of candles.
- [ ] **Step 6: COVERAGE FIRST**: `python -m tradingagents.v3_coverage report --plan research/v3/plan-long.json`. If the older days' per-minute costs are mostly missing, say so beside every result (do not fill 3 years for a 1-day idea: its entries and exits pay a typical cost, printed as the share).
- [ ] **Step 7: Dispatch** `python -m tradingagents.v3_cloud dispatch trend-1d-long --plan research/v3/plan-long.json` (all three accounts, outside 12:45am-5:00am), then `collect`, then `python -m tradingagents.v3_per_coin publish trend-1d-long`.
- [ ] **Step 8: Gate for A**: pooled unseen-year profit a trade is above the random runs' 95th percentile AND above 0 AND the day-clustered bootstrap low end is above 0, over 300+ trades. Otherwise the result is printed as "no edge over random".

### Task 3: Funding carry measurement (test C)

**Files:**
- Create: `tradingagents/funding_carry.py`
- Test: `tests/test_funding_carry.py`

**Interfaces:**
- Produces: `carry_open(settlements: list[dict], start_ms: int, hold_days: float, fee_in: float, fee_out: float) -> dict` returning `{"earned", "fees", "net", "min_running", "settlements"}`, fractions of the position, where `settlements` rows are `{"settle_ms", "rate"}` as `fx.funding_history` returns them and `earned` is the sum of `rate` over settlements inside `[start_ms, start_ms + hold_days)`; `min_running` is the lowest running sum (the worst dip while open).
- Produces: `scan(coins, spot_ids, hold_days, fees) -> list[dict]` — one row per coin, over every start day in its history, with the share of starts that end above 0, the median net, the worst `min_running`, and the days of history.
- Consumes: `fx.funding_history(symbol)`; the Gate spot list (public `GET /spot/currency_pairs`, `trade_status == "tradable"`).

- [ ] **Step 1: Tests** (names and assertions):
  - `test_earned_sums_published_settlements_not_a_formula`: a coin with settlements every 4 hours earns twice a coin with the same rate every 8 hours over the same hold.
  - `test_negative_funding_is_a_loss`: three settlements at −0.0001 give `earned == -0.0003` and `net < 0`.
  - `test_fees_are_charged_once_in_once_out`: `fees == fee_in + fee_out`.
  - `test_min_running_is_the_worst_dip`: rates `[+, +, −, −, −]` report the lowest running sum, not the final one.
  - `test_coin_without_spot_is_named_not_dropped`: `scan` returns it in a `left_out` list with reason "no spot market".
- [ ] **Step 2: Run** — expect FAIL. **Step 3: Implement** both functions (pure; the network read lives only in the command). **Step 4: Run** — expect PASS.
- [ ] **Step 5: Command** `python -m tradingagents.funding_carry scan --hold 30,90 --fees 0.55,0.30` printing, per hold and fee level: coins scanned, coins left out with reasons, coins whose median start nets above 0, and the top 10 with history days. It saves rows to `~/.tradingagents/carry/scan.json`.
- [ ] **Step 6: Commit** with the measured numbers from "Measured before planning" in the message.

### Task 4: Decide, report, and (only if it passes) page

**Files:**
- Create: `docs/research/2026-11-04-trend-1d-and-funding-carry.md`

- [ ] **Step 1:** Write the two verdicts in plain words with the measured numbers (A: Task 2 Step 8; C: share of coins whose 90-day carry nets above 0 after 0.55% and after 0.30%, the worst dip, the 210-day depth). C passes only if at least 25% of the scanned coins net above 0 in at least 70% of their 90-day starts AND their worst dip is under half of the fees' size scaled to a year; otherwise it is "does not pay on Gate".
- [ ] **Step 2:** For each test that passes, publish an artifact (kit A-H) — A from `v3_per_coin_page`, C from a page that lists every coin, with the hold and the fee as inputs. A test that fails gets no page, only the note.
- [ ] **Step 3:** Commit the note with `commit_own.py` and push to all three remotes.

## Self-review

- Spec coverage: A (Tasks 1-2) and C (Task 3), decision and report (Task 4); Review Focus 1-5 each have a test (Task 3 tests 1-3, Task 1 tests 1 and 3; Review Focus 4 is the printed window in Task 2 Step 5).
- Type consistency: `settlements` rows have the same two keys everywhere; `window_days` / `unseen_days` are named the same in Tasks 1 and 2.
- Proportion: three code tasks, each with its signature and the assertions that pin it; no function bodies.
- Out of scope, said once: this plan does not deploy anything, does not open a spot account, and does not claim the carry's capital cost (spot is bought in full, so the return on total money is lower than the funding rate on the position).
