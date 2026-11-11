# Skill Rooms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three practice rooms in Auto Trade (#D7EN8BNV, #RSS7CUKH, #7T3VJU82). Each switches on
Backtest v4 strategies by its Forecast v4 rule every midnight UTC and trades them with the skill
backtest's OWN engine, candle by candle. Backtest v4 is re-measured daily on every GitHub account,
and the other ten rooms' watchers are switched off.

**Architecture:**
- `skill_bt.walk()` is split into a per-candle `step()`. The backtest, the daily GitHub shard and
  the follower all call it, so there is one set of rules.
- A daily chain (`v4_daily`) runs the shard on every account at 00:05 UTC, collects, rebuilds the
  v4 store and Forecast v4 in a subprocess, writes each room's day list, and checks that
  yesterday's practice trades equal the re-measured backtest.
- A follower (`v4_follow`) in its own API thread replays every closed candle for the switched-on
  strategies into each room's own trade record, in the runner's shapes, so every existing panel
  reads it unchanged.

**Tech Stack:** Python 3.12 (pandas, numpy, sqlite3), FastAPI (`tradingagents/api.py`), Next.js +
TypeScript (`webapp/`), GitHub Actions (`skillbt.yml`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-10-skill-rooms-design.md` (commit ca16d742). Read it
first. Its "Calls I made" list is binding.

## Global Constraints

- Dates printed anywhere: `positions_view.fmt_when` (Python) / `fmtWhen` (TS) only — `Aug 03, 2026 8:03pm`.
- Every exchange call goes through `from tradingagents.dataflows import exchange as fx`; never import an adapter.
- No path under `~/.tradingagents` at module top level; resolve paths at call time (`auto_trader._pp`, `stores.V4.home`).
- No Python string constant containing the word "Main" (`test_main_tab_shows_every_rooms_trades.py`).
- Nothing below an `if __name__ == "__main__":` guard.
- A test writes only under `tmp_path` and starts no background program; `tick()` functions do nothing under `PYTEST_CURRENT_TEST`.
- "Is it running?" is a lock held (`portable.lock_exclusive`), never a pid.
- Every GitHub dispatch goes to every account (`forecast_v2_daily.fleets_now`, `cloud_sweep.split_coins`, `cloud_sweep.sync_fleet`); a refusing account is named.
- Big files under `market_sweep.HOME` / `stores.V4.home` (G:), never `%TEMP%`.
- Money is $5 margin x 20x = $100 of coin (`skill_bt.NOTIONAL`); the rooms never place an order and have no real-money path.
- Commit with `python scripts/commit_own.py -F msg.txt <paths>`, message ends `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; push to `origin`, `colleague`, `teammate` after every task.
- Room ids and rules, exactly:
  - `D7EN8BNV`: window 30, win_rate 90, min_trades 20, tp_rule "any", sl_cap 0, tf "", skill "".
  - `RSS7CUKH`: window 30, win_rate 80, min_trades 20, tp_rule "any", sl_cap 1.5, tf "", skill "".
  - `7T3VJU82`: window 30, win_rate 80, min_trades 20, tp_rule "any", sl_cap 0, tf "1h", skill "".
- The other rooms whose watchers go off: `55D32617 4FC03172 B2404C0B 6B08FF64 CC94D9FB 99E79CBA C7396286 1D4274C1 8F0C7926 BBE0A361`. `main` is untouched.

## Review Focus

1. **A strategy on today's list that was also on yesterday's.** It continues from its own state:
   no second warm-up and no second `enter` row. Test in Task 5
   (`test_a_strategy_on_two_days_lists_is_followed_once`).
2. **PC asleep across midnight UTC, and the list landing late.** The catch-up crosses the day
   boundary, uses each day's own list for its own candles, and writes every row once. Test in
   Task 5 (`test_catch_up_across_midnight_uses_each_days_list`).
3. **Two strategies holding the same coin at once.** They get distinct state slots and trade ids,
   and both show in the positions and today panels. Test in Task 5
   (`test_two_strategies_on_one_coin_are_two_trades`).
4. **A row written after local midnight for a candle that closed before it.** "Paper · today"
   and the calendar put it on the CANDLE's day. Test in Task 5
   (`test_late_written_exit_counts_on_its_candles_day`).
5. **A held strategy whose coin vanishes from the exchange or the store.** The trade closes
   `DELISTED` at its last candle, named, and is never stuck open. Test in Task 5
   (`test_a_delisted_coin_closes_its_trade`).

---

### Task 1: One engine — `step()`, `run()`, funding, and the live signal

**Files:**
- Modify: `tradingagents/skill_bt.py` (`walk` at :97-135; add `Funding`, `step`, `run`, `signal_at`)
- Create: `tradingagents/skill_frames.py` (the candle frame, moved out of `.github/scripts/skill_shard.py:43-52`)
- Modify: `.github/scripts/skill_shard.py` (import `frame` from `skill_frames`)
- Test: `tests/test_skill_engine_steps.py`

**Interfaces:**
- Produces:
  - `skill_bt.Funding(settlements: list[dict])` — each dict has `settle_ms`, `rate` (`fx.funding_history` shape). Method `.paid(from_ms: int, to_ms: int) -> float` is the sum of the rates with `from_ms < settle_ms <= to_ms` (cumulative array plus bisect).
  - `skill_bt.step(pos: dict | None, sig, *, close: float, when_ms: int, bar_ms: int, stop: float, fee: float, slip: float, target: float | None = None, funding: Funding | None = None) -> tuple[dict | None, dict | None]` — one candle of `walk`'s loop body, unchanged in order: stop, target, own exit signal, close, then entry. It returns `(pos_after, closed_trade_or_None)`. A `None` signal returns `(pos, None)` untouched (warm-up).
  - `skill_bt.run(df, sigs, *, stop, fee, slip, target=None, funding=None, bar_ms=0) -> tuple[list[dict], dict | None]` — the trades closed, and the position still open (NOT closed at the end).
  - `skill_bt.walk(df, sigs, *, stop, fee, slip, target=None, funding=None, bar_ms=0) -> list[dict]` = `run()` plus the existing END close.
  - `skill_bt.signal_at(df, name: str, params: dict, bars: int)` — the signal of `df`'s LAST row, computed as the backtest computes it:
    - a `signals_all` strategy (skill_ta): `signals_all(df.tail(bars))[-1]`;
    - otherwise `generate_signals(df.tail(window(params)))` when `len(df) > lookback`, else `None`.
  - `skill_frames.BARS = {"15m": 2880, "30m": 2880, "1h": 2160, "4h": 1080, "1d": 730}` and `skill_frames.frame(sym: str, tf: str, bars: int | None = None, *, end_ms: int | None = None) -> pd.DataFrame`. `end_ms` keeps only candles whose open is `< end_ms`; it is used for the midnight warm-up.
- Funding rule: a trade's funding is `-side * funding.paid(entry_fill_ms, exit_fill_ms) * NOTIONAL`, added to its `pnl`, where `entry_fill_ms = when[i] + bar_ms` and `exit_fill_ms = when[j] + bar_ms`. With `funding is None` the trade dict is EXACTLY today's: the same keys, no `fund` key.

- [ ] **Step 1: Write the failing tests** in `tests/test_skill_engine_steps.py`:
  - `test_walk_without_funding_is_unchanged`: a seeded 600-candle random-walk frame. For every bt `GRID` family's first setting and every `skill_ta.GRID` family's first setting x both `STOPS`, `walk(...)` equals a frozen copy of today's loop (paste today's `walk` body into the test as `_old_walk`), dict for dict.
  - `test_run_plus_end_close_is_walk`: `run()` trades plus the END close built from its open position equal `walk()`.
  - `test_stepping_one_candle_at_a_time_is_walk`: feeding `step()` candle by candle gives `run()`'s trades and open position.
  - `test_funding_is_charged_inside_the_hold`: a long held from fill 1,000,000 to fill 1,900,000 ms, with settlements at 900,000 (outside), 1,500,000 (+0.001) and 1,900,000 (+0.002), gets `fund = -1 * 0.003 * 100 = -0.3` taken from its pnl. A short gets `+0.3`.
  - `test_signal_at_equals_the_backtests_signal`: for sma_crossover, rsi_reversal, bollinger_bands and breakout, `signal_at(df.iloc[:i+1], ...) == signals(df, ...)[i]` (entry, exit, direction) for every `i`. For skill_ta's wyckoff_spring, rsi_divergence, vwap_reversion, ma_pullback and bf_momentum, `signal_at(df.iloc[:i+1], ..., bars=400)` equals `signals(df.iloc[i-399:i+1])[-1]`.
- [ ] **Step 2: Run them to see them fail.** Run `.venv/Scripts/python -m pytest tests/test_skill_engine_steps.py -q`. Expected: FAIL (`step` / `run` / `signal_at` / `Funding` not defined).
- [ ] **Step 3: Implement** the interfaces above in `skill_bt.py`. Move `frame()` into `skill_frames.py` and change `skill_shard.py` to `from tradingagents.skill_frames import BARS, frame`.
- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest tests/test_skill_engine_steps.py tests/test_skill_bt.py tests/test_skill_ta.py tests/test_acs.py -q`. Expected: all PASS.
- [ ] **Step 5: Commit and push.** Message: "feat(skill_bt): one engine stepped a candle at a time, with funding - walk() unchanged without it".

### Task 2: The daily shard set — pinned strategies, funding charged

**Files:**
- Create: `tradingagents/v4_pin.py` (builds the pinned bt list)
- Create: `research/v4/bt_pinned.json` (committed output)
- Modify: `tradingagents/skill_bt.py` (add `measure`)
- Modify: `.github/scripts/skill_shard.py` (SET `daily`)
- Modify: `.github/workflows/skillbt.yml` (the `set` description, upload `out/skilldaily-*`)
- Modify: `tradingagents/acs.py` (`SKILL_PREFIX["daily"] = "skilldaily"`)
- Test: `tests/test_v4_daily_shard.py`

**Interfaces:**
- Consumes: Task 1's `walk(funding=, bar_ms=)`, `skill_frames.frame`, `Funding`.
- Produces:
  - `v4_pin.build(src: Path, out: Path) -> dict` reads the collected `acs/skill.json` (Nov 05, 2026 run). It writes `{"made_s": int, "source": "skill.json", "pairs": {"COIN|tf": {"split_ms": int, "picks": [{"strategy", "params", "stop", "target"}]}}}`: every pick of every line, i.e. exactly the 15,933 strategies, with each pair's ORIGINAL `split_ms`. CLI: `python -m tradingagents.v4_pin build`.
  - `skill_bt.measure(df, combos: list[dict], *, fee, slip, funding=None, bar_ms) -> list[dict]` returns, per combo, `{"label", "strategy", "params", "stop", "target", "trades": [...], "older_lost": False}`, signals computed once per (strategy, params).
  - The shard line for SET `daily` (prefix `skilldaily`) has the same keys as `line()`. Its picks are:
    - all 42 `skill_ta.GRID` x `STOPS` with `skill_ta.TARGETS`;
    - then the pinned bt picks of that `COIN|tf`, each carrying its own `"split_ms"`.

    The coin's funding is `fx.funding_history(sym, since_ms=<the 1d frame's first candle ms>)`, read once per coin; `bar_ms` comes from `br.TFS[tf]`.
  - `acs.SKILL_PREFIX["daily"] == "skilldaily"`, so `acs.collect_skill("daily")` writes `acs/skilldaily.json`.

- [ ] **Step 1: Write the failing tests:**
  - `test_pin_keeps_every_bt_pick_with_its_split`: a two-line fixture `skill.json` gives 2 pairs with 3 picks each, and the split values are copied.
  - `test_daily_line_measures_ta_all_and_only_the_pinned_bt`: with `fx` stubbed (frame + funding + costs), the `daily` line for `BTC|1h` has 42 + 3 picks. The bt picks equal the pinned three and carry `split_ms`.
  - `test_daily_trades_pay_funding`: a pick's pnl differs from the same walk without funding by exactly that trade's `fund`.
  - `test_workflow_uploads_the_daily_lines`: `skillbt.yml` text contains `out/skilldaily-*.jsonl`. Its `on.workflow_dispatch.inputs` count is <= 10.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_v4_daily_shard.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** In the shard, `SET` accepts `daily`, and `PREFIX["daily"] = "skilldaily"`. The pinned file is read from `research/v4/bt_pinned.json` relative to `ROOT`. A coin missing from the pinned file measures its 42 ta strategies only.
- [ ] **Step 4: Build the pinned file for real.** Run `.venv/Scripts/python -m tradingagents.v4_pin build`. Then check `len(picks summed) == 15933`. Print the count.
- [ ] **Step 5: Run the tests to see them pass.** Run the Task 2 tests plus `tests/test_skill_bt.py`. Expected: PASS.
- [ ] **Step 6: Commit** (including `research/v4/bt_pinned.json`) **and push.**

### Task 3: The store and the forecast learn the daily run

**Files:**
- Modify: `tradingagents/v4_store.py` (`build`: per-pick `split_ms`, `older_lost` default, `DAILY_SOURCES`, keep the Nov 10 copy; CLI `build --daily`)
- Modify: `tradingagents/forecast_v4.py` (`_load` drops END; dated gzip copy; `switched_on`)
- Test: `tests/test_v4_store_daily.py`, additions to `tests/test_forecast_v4.py`

**Interfaces:**
- Produces:
  - `v4_store.DAILY_SOURCES = (("skilldaily.json", "daily re-measure"),)`.
  - `build()` uses `c.get("split_ms", x["split_ms"])` and `c.get("older_lost", False)`.
  - `v4_store.keep_first_copy(db: Path) -> Path | None` copies `rows.db` to `rows-2026-11-10.db` once. It returns `None` if that file exists.
  - CLI `python -m tradingagents.v4_store build --daily` runs `keep_first_copy`, then `build(sources=DAILY_SOURCES)`, then `forecast_v4.build()`. It exits 1 with the reason on any failure.
  - `forecast_v4._load` also reads `why`, and drops trades whose `why` is END from BOTH judging and counting (`left_open` count added to the doc's coverage).
  - `forecast_v4.build()` also writes `stores.V4.home / "forecast-days" / f"forecast-{YYYY-MM-DD of data_end_s UTC}.json.gz"`. It never deletes one.
  - `forecast_v4.switched_on(rule: dict, at_s: int, db: Path | None = None) -> list[dict]` — the strategies a rule set switches on at midnight `at_s`. The arithmetic is `_walk`'s: trades with `ex < at_s` and `ex >= at_s - window*86400`, END dropped, chosen-skill trades before `split_s` dropped; `n >= min_trades`; `100*wins/n >= win_rate`; the kind filters `tf`, `skill`, `tp_rule` (`">"` = TP > SL; no target fails `">"`) and `sl_cap` (`sl <= sl_cap` when `sl_cap > 0`). Each row is `{sid, id, coin, tf, strategy, label, skill, params (dict), stop (fraction), target (fraction or None), fee, slip, n, wins}`.

- [ ] **Step 1: Write the failing tests:**
  - `test_daily_build_keeps_each_picks_own_split`.
  - `test_first_daily_build_keeps_the_nov10_store_once`.
  - `test_end_trades_never_count` (a fixture strategy whose only qualifying trades include an END one is not switched on, and END pnl is not in any month).
  - `test_switched_on_matches_the_walk`: over the existing `test_forecast_v4` fixture, for each fixture rule, the sum over walk days of trades OPENED that day by `switched_on(rule, day)` equals the rule's `trades`, and the profit equals `profit` to 4 places.
  - `test_a_dated_copy_is_kept_per_day`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/test_v4_store_daily.py tests/test_forecast_v4.py tests/test_backtest_v4_store.py tests/test_backtest_v4_tab.py`. Expected: PASS.
- [ ] **Step 5: Commit and push.**

### Task 4: The three rooms exist, and no runner ever touches them

**Files:**
- Modify: `tradingagents/profiles.py` (three entries plus `follows()`)
- Modify: `tradingagents/strategy_watcher.py:165-172` (`mode_of` returns "off" for a follower room)
- Modify: `tradingagents/auto_trader.py` (`start_runner` at :8132 refuses a follower room by name)
- Modify: `tradingagents/api.py` (supervisor start check ~:432; `row_id_for` resolves `v4_` keys)
- Modify: `tradingagents/room_restart.py` (~:60, skip follower rooms)
- Modify: `webapp/src/lib/api.ts:135-157` (`PROFILES` gains the three, same order)
- Modify: `tests/test_every_profile_is_its_own_room.py:206-213`, `tests/test_rooms_judge_on_15_days.py:213-219` (lists)
- Test: `tests/test_skill_rooms_exist.py`

**Interfaces:**
- Produces:
  - BUILTIN entries `{"id": "D7EN8BNV", "name": "#D7EN8BNV", "rules": None, "follows": "v4", "v4_rule": {...}}` (and the same for `RSS7CUKH` and `7T3VJU82`), appended after `BBE0A361`, with the rule values from Global Constraints.
  - `profiles.follows(pid: str) -> str | None` returns `"v4"` or `None`.
  - `profiles.v4_rule(pid: str) -> dict | None`.
  - `api.row_id_for("v4_9HZYB3B5", ...)` returns `"9HZYB3B5"`.
  - `start_runner()` under a follower room raises `RuntimeError("#D7EN8BNV is followed by Backtest v4's engine; it has no runner")`.
- Note: do NOT add these ids to `test_rooms_judge_on_15_days.TABLE`; they are not research rule ids. The supervisor and watcher loops are pinned by source-text tests (`test_every_profile_is_its_own_room.py:195-198`, `test_supervisor.py:155-182`), so keep those strings and ADD the follower check beside them.

- [ ] **Step 1: Write the failing tests:**
  - `test_the_three_rooms_have_tabs_after_bbe0a361`.
  - `test_follower_rooms_switch_nothing_on` (`mode_of` under `profiles.using("D7EN8BNV")` == "off").
  - `test_a_follower_room_never_gets_a_runner` (`start_runner` raises; the supervisor source skips `profiles.follows`; `room_restart` skips it).
  - `test_v4_rule_matches_the_forecast_rule_id`: `forecast_v4.rule_id(**rule) == pid` for each.
  - `test_webapp_lists_the_rooms_in_order`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new test file and `tests/test_every_profile_is_its_own_room.py tests/test_rooms_judge_on_15_days.py tests/test_the_strategy_watcher.py tests/test_supervisor.py tests/test_main_tab_shows_every_rooms_trades.py tests/test_tests_cannot_write_the_real_home.py`. Expected: PASS.
- [ ] **Step 5: Commit and push.**

### Task 5: The follower

**Files:**
- Create: `tradingagents/v4_follow.py`
- Test: `tests/test_v4_follow.py`

**Interfaces:**
- Consumes: Task 1 (`step`, `run`, `signal_at`, `Funding`, `skill_frames.frame`/`BARS`); Task 3 (`switched_on` row shape); Task 4 (`profiles.follows`, `v4_rule`); `at.append_ledger`, `at.save_state(keys=)`, `at.load_state`, `at.state_key(symbol, True, strategy)`, `at.trade_code(symbol, strategy, entry_ts, side, dry=True)`.
- Day lists (written by Task 6, read here): `stores.V4.home / "rooms" / f"{YYYY-MM-DD}.json"` = `{"day_s": int, "made_s": int, "fallback_from": "YYYY-MM-DD" | None, "rooms": {pid: [switched_on rows]}}`.
- Produces:
  - `v4_follow.pass_once(now_s: float | None = None, *, fetch=None, funding_of=None, listed=None) -> dict`. For every follower room it advances every strategy through every closed candle not yet processed, and returns `{pid: {"processed": int, "entered": int, "exited": int, "held_at": day_s | None, "errors": [str]}}`. `fetch(sym, tf, end_ms=None) -> df` defaults to `skill_frames.frame`; `funding_of(sym) -> list` defaults to `fx.funding_history`; `listed() -> set[str]` defaults to the exchange's contracts. All are injectable for tests.
  - Per-room follower state: `at._pp(at.STATE_PATH).with_name("v4_follow.json")` (resolved inside `profiles.using(pid)`) = `{"strats": {id: {"last_ms": open ms of the last processed candle, "pos": dict | None, "carried": bool, "row": switched_on row}}, "last_pass_s", "held_at", "filled_in": int}`, written via a temp file and `os.replace`.
  - Heartbeat: `v4_follow.status(pid) -> dict` = `{"last_pass_s", "last_candle_ms", "held_at", "why", "filled_in", "errors", "switched_on": [rows], "agreement": {...} | None}`.
  - `v4_follow.tick()`: under pytest, nothing. Otherwise it runs `pass_once` once 20 s after every 15-minute close, under `portable.lock_exclusive` on `stores.V4.home / "follow.lock"` (`blocking=False`; held means skip), and prints `[v4-follow] <sentence>` only when the sentence changes.
- Rules the code must follow (from the spec):
  - **Day ownership.** A candle belongs to the day of its OPEN (`floor(open_ms/86_400_000)`). It is processed only when that day's list file exists. The follower holds at the first candle with no list (`held_at`). Exits are held too.
  - **Strategy membership.** A strategy takes a NEW entry on a candle only if its id is in that candle's day list. Exits are always processed for a held position.
  - **Warm-up.** When a strategy first gets state (no entry in `strats`), it calls `run()` over `fetch(sym, tf, end_ms=day_s*1000)` with its signals. The open position is stored with `carried: True`. A carried position closes silently: no ledger rows, no state slot.
  - **Signals.** For each new candle `i`: `signal_at(frame up to i, strategy, params, BARS[tf])`. Then `step(...)` with the row's `stop`, `target`, `fee` and `slip`, `bar_ms`, and `Funding(funding_of(sym))`.
  - **On a new (non-carried) entry:**
    - `append_ledger` with `action "enter"`, `ts = when_ms/1000 + bar_s` (the fill = candle close), `symbol` = `f"{coin}_USDT"`, `strategy = f"v4_{id}"`, `entry_ts = when_ms/1000`, `opened_at` = fill, `side` "LONG"/"SHORT", `entry` = fill price, `tp`/`sl` = price levels (`tp` None when no target), `margin 5.0`, `leverage 20`, `dry_run true`, `trade_id = at.trade_code(...)`, `fee`, `slip`, `v4_id`, `written_at = now`;
    - plus a state slot `at.state_key(symbol, True, strategy)` holding the runner's practice position shape (`side ±1`, `entry`, `tp`, `sl`, `margin`, `strategy`, `entry_ts`, `opened_at`, `trade_id`, `dry True`, `bracket True`, `vol = 100/entry`).
  - **On its exit:**
    - `append_ledger` with `action "exit"`, `ts` = exit candle close, `why` SL/TP/SIGNAL/DELISTED, `entry`, `exit`, `pnl_est` = the step's pnl (fund included), `pnl_source "v4_engine"`, `held_s`, the same `trade_id`/`entry_ts`/`opened_at`, `dry_run true`, `written_at`;
    - the state slot removed via `save_state(keys=[slot])`.
  - **Delisted.** A coin not in `listed()`, or a held strategy whose row's coin can no longer be fetched for 2 passes, closes its open trade at the last candle with `why "DELISTED"` and is named in `errors`.
  - **Failures.** A strategy whose fetch raises is retried once after the others in the same pass, then named (`"COIN tf id: Type: msg"`). Its state is untouched, so the next pass catches up.

- [ ] **Step 1: Write the failing tests** (all on ONE timeline: candles and list days built from one `T0 = 2026-11-01 00:00 UTC` clock, say so in the fixture's docstring; fetch and funding injected; rooms under `tmp_path` via the existing room-home fixture pattern from `tests/test_every_profile_is_its_own_room.py`):
  - `test_follower_trades_equal_the_engines_walk`: one 1h strategy listed every day for 3 days. The ledger's enter/exit pairs equal `run()` over the same frame (entries on or after day 1's midnight, the warm-up's carried trade excluded): same entry/exit candles, side, why, pnl to 4 places.
  - `test_holds_at_midnight_until_the_list_lands`: with no list for day 2, nothing is processed for candles opening on day 2; `held_at == day2_s`. Then the list is written, and the next pass processes them and counts `filled_in`.
  - `test_carried_trade_is_never_written`.
  - `test_switched_off_strategy_finishes_its_trade`: a day 2 list without it means no new entry, and its open trade exits by its own rule.
  - `test_a_strategy_on_two_days_lists_is_followed_once`.
  - `test_catch_up_across_midnight_uses_each_days_list`.
  - `test_two_strategies_on_one_coin_are_two_trades`.
  - `test_late_written_exit_counts_on_its_candles_day` (`at.pnl_today(now=<day of the candle>, dry=True)` includes it; a `now` the next day does not).
  - `test_a_delisted_coin_closes_its_trade`.
  - `test_ledger_rows_read_by_every_panel`: `at.ledger_trades()` returns the trade with `pnl_est` and `trade_id`; `/api/trade/history` row has `strategy` `v4_<id>`.
  - `test_tick_does_nothing_under_pytest`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** `v4_follow.py` to the interfaces and rules above.
- [ ] **Step 4: Run** `tests/test_v4_follow.py` plus Task 1's tests. Expected: PASS.
- [ ] **Step 5: Commit and push.**

### Task 6: The daily chain and the agreement check

**Files:**
- Create: `tradingagents/v4_daily.py`
- Modify: `tradingagents/forecast_v2_daily.py` (`title_of`: `if workflow == "skillbt.yml": return f"Skill backtest · {inputs['label']}"`)
- Test: `tests/test_v4_daily.py`

**Interfaces:**
- Consumes: `fd.fleets_now`, `fd.market`, `cs.split_coins`, `cs.sync_fleet`, `fd.dispatch(workflow, inputs, repo, since=)`, `fd.run_status`, `fd.run_words`, `acs.collect_skill("daily")` (fed by writing `acs/skilldaily-state.json` in `acs.dispatch`'s state shape), `forecast_v4.switched_on`, `profiles.v4_rule`, the Task 5 ledger rows.
- Produces:
  - State `stores.V4.home / "daily_state.json"` (written with `forecast_v2.publish`): `{"day": "YYYY-MM-DD", "phase": "dispatch"|"running"|"collect"|"build"|"lists"|"agree"|"done"|"given_up", "deal", "tried", "runs", "why", "error", "landed_s", "missing", "failed", "delisted"}`.
  - `v4_daily.due(now_s) -> bool`: true once per UTC day at or after 00:05 UTC, keyed by `day`.
  - `v4_daily.tick()`: under pytest, nothing. A non-waiting `threading.Lock`. It moves at most one phase per call, every `POLL_S = 120`.
  - Phases:
    1. **dispatch:** `skillbt.yml`, `set=daily`, `label=f"v4 daily {day}"`, `shards=20`, `coin_list` = each account's `split_coins` pile of `fd.market()`. The deal is saved before the first dispatch, and `tried` before each one. A run GitHub lists late is adopted. An account refusing twice gives the day up, named.
    2. **running:** poll `run_status` and show `run_words`. A green run that measured 0 coins is red: redo it once, then give up.
    3. **collect:** write `acs/skilldaily-state.json`, then `acs.collect_skill("daily")`. Delisted = pinned coins not in `fd.market()`, named. A failed or unreached coin is redone ALONE once (`fd.dispatch` with that `coin_list`), then named and kept from the previous `skilldaily.json` line (stale-marked). A share missing an account's coins is never built.
    4. **build:** `subprocess.run([sys.executable, "-m", "tradingagents.v4_store", "build", "--daily"])`. Non-zero means `_fail`.
    5. **lists:** for each follower room, `switched_on(profiles.v4_rule(pid), day_s)` is written to the day list file (Task 5 shape) in one swap.
    6. **agree:** `agreement(pid, day_s)` for yesterday.
  - `GIVE_UP_AT_S = 6*3600` after the day's midnight. On give-up it writes the day list file as a copy of yesterday's, with `fallback_from`, and says so.
  - `v4_daily.agreement(pid: str, day_s: int, db=None) -> dict` = `{"day", "same": int, "of": int, "dollars_apart": float, "only_practice": [trade_id], "only_backtest": [v4 id + entry]}`. It is saved to `stores.V4.home / "rooms" / f"agree-{YYYY-MM-DD}.json"` (`{pid: result}`, one swap) — never into the follower's own state file, which another thread writes. `v4_follow.status()` reads the newest one.
  - `v4_daily.start_now() -> dict`: starts today's chain at once, ignoring `due()` but never inside `cq_search.quiet_hours()`. It is used for the first refresh.
    - A pair is "the same" when the strategy id, side, entry candle (`entry_ts == en`), exit candle (`exit ts - bar_s == ex`) and `why` all match.
    - Compared: the room's exit rows whose `entry_ts` falls on day `day_s` against the store's trades of the strategies on that day's list with `en` on that day and `why != END`.
  - `v4_daily.status() -> dict` for the routes.

- [ ] **Step 1: Write the failing tests:**
  - `test_due_once_a_utc_day_after_0005`.
  - `test_the_deal_is_saved_before_the_dispatch`.
  - `test_a_late_listed_run_is_adopted` (`since=` passed on retry).
  - `test_an_account_refusing_twice_gives_the_day_up_named`.
  - `test_a_green_run_with_no_coins_is_red`.
  - `test_a_failed_coin_is_redone_alone_then_kept_stale`.
  - `test_delisted_pinned_coins_are_named_not_missing`.
  - `test_give_up_at_0600_copies_yesterdays_list_with_fallback`.
  - `test_lists_written_for_every_follower_room`.
  - `test_agreement_counts_same_and_names_the_rest`.
  - `test_title_of_skillbt`.
  - `test_tick_does_nothing_under_pytest`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/test_v4_daily.py tests/test_forecast_v2.py tests/test_room_strategies_retest_daily.py`. Expected: PASS.
- [ ] **Step 5: Commit and push.**

### Task 7: Wiring, routes and the screens

**Files:**
- Modify: `tradingagents/api.py` (supervisor threads `v4-daily` and `v4-follow` with the exact pattern the agent map quotes; routes `GET /api/trade/v4-follow` (room from `X-TA-Profile`) and `GET /api/v4/daily`; `/api/trade/summary` adds `follows` and the follower heartbeat for a follower room)
- Modify: `webapp/src/components/trade/SummaryRibbon.tsx` (a follower room shows the follow line instead of the runner badge and buttons)
- Create: `webapp/src/components/trade/V4FollowPanel.tsx`
- Modify: `webapp/src/components/trade/AutoTradeScreen.tsx` (follower room: `V4FollowPanel` in place of `WatcherPanel`/`CredentialsPanel`)
- Modify: `webapp/src/components/backtest-v4/V4Strategies.tsx` (the daily refresh sentence and the costs-not-charged line)
- Test: `tests/test_skill_rooms_screen.py`

**Interfaces:**
- `GET /api/trade/v4-follow` returns `v4_follow.status(pid)` plus `{"rule_words": forecast_v4.rule_words(**rule), "daily": v4_daily.status()}`. For a room that is not a follower it returns `{"follows": null}`.
- **Ribbon line, exact words:**
  - `PAPER · follows Backtest v4 · last candle <fmtWhen> · next <fmtWhen>`;
  - when the last pass is more than 1800 s old or has errors: `not following: <why>`;
  - while held: `waiting for today's list (<why>); trades since <fmtWhen of midnight UTC> are filled in when it lands`.
- **V4FollowPanel shows:**
  - the rule in words;
  - "Switched on today": each strategy's id, coin, tf, label, and its record (`n`, `wins`, win rate) over the last 30 days;
  - the day's refresh sentence;
  - yesterday's agreement, `"<same> of <of> trades the same as the backtest · $<dollars_apart> apart"`, with the ids of the rest;
  - the fixed line `Every trade pays its coin's usual gap, not its own minute's order book (100% typical cost) · no trade is refused by the runner's cost check · no order is placed`.
- Paging and filtering run on the server only (no `.filter(` over a fetched list). Dates use `fmtWhen` only.

- [ ] **Step 1: Write the failing tests:**
  - `test_supervisor_starts_v4_threads` (source contains both thread names in the established pattern).
  - `test_follow_route_answers_for_a_follower_room_only`.
  - `test_positions_route_shows_a_follower_position`: a state slot written the way Task 5 writes it (strategy `v4_<id>`, `tp` None) comes back from `/api/trade/positions` and `/api/trade/summary` without an error, with coin, side, entry and stop.
  - `test_summary_says_follows_for_a_follower_room`.
  - `test_ribbon_has_the_follow_line_and_no_runner_buttons_for_followers` (TSX source).
  - `test_panel_columns_and_cost_line`.
  - `test_no_client_filter_and_one_date_format` (the same checks as `tests/test_backtest_v4_tab.py`).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** Then run `cd webapp && npx eslint <changed files>` and `npm run build`. Expected: both clean (the older AppSidebar.tsx:268 lint error excepted).
- [ ] **Step 4: Run** the new tests, `tests/test_backtest_v4_tab.py` and `tests/test_main_tab_shows_every_rooms_trades.py`. Expected: PASS.
- [ ] **Step 5: Commit and push.**

### Task 8: Go live — switch the other watchers off, first refresh, verify

**Files:**
- Create: `tradingagents/v4_rooms.py` (one-time `retire_others()`)
- Modify: `CLAUDE.md` (a "Skill rooms (Nov 10, 2026)" section after "Forecast v4"), `docs/TRADING-ROOMS.md` (follower rooms)
- Test: `tests/test_v4_rooms.py`

**Interfaces:**
- `v4_rooms.retire_others() -> dict`: under `profiles.using(pid)` for each of the ten ids in Global Constraints, `strategy_watcher.set_mode("off")`, plus a deploy-log reason line `"watcher off: replaced by the skill rooms (operator, Nov 10, 2026)"`. It returns `{pid: mode}`. It never touches `main`, and never touches a slot that holds `"real"`.

- [ ] **Step 1: Write the failing test** `test_retire_others_turns_ten_watchers_off_and_leaves_main`, under `tmp_path` homes.
- [ ] **Step 2: Run it to see it fail, then implement it, then see it pass.**
- [ ] **Step 3: Full suite, once** (check that no other pytest is running first: `Get-Process python | ...`). Compare against the baseline. Only the known older failure (`test_the_claude_skills_tab.py::test_every_skill_folder_is_on_the_page_and_sorted`) may fail.
- [ ] **Step 4: Commit and push** (code, CLAUDE.md, docs). Then restart with `.venv/Scripts/python start.py start` (pre-approved), and say so.
- [ ] **Step 5: Live, in order:**
  1. `.venv/Scripts/python -m tradingagents.v4_rooms retire_others`, printing the result.
  2. The first refresh by hand, outside 12:45am-5:00am: `.venv/Scripts/python -c "from tradingagents import v4_daily; v4_daily.start_now()"` (a `start_now()` that ignores `due()` but not the quiet hours). Watch it to `done` with `v4_daily.status()`.
  3. Confirm the day list file holds the three rooms with counts, and print them.
  4. One `v4_follow.pass_once()`: print each room's processed, entered and exited counts.
  5. Open the three tabs in Chrome (`.claude/skills/verify-ui-change/scripts/gate.mjs`, or Playwright MCP if connected). The ribbon line, the panel and the tiles must render with no console errors and no sideways scroll at 390px.
  6. The next day, after 00:05 UTC, the agreement line is present.
- [ ] **Step 6: Report** the room counts, the first trades (ids, times, dollars), the refresh duration and the agreement status. Run say-done.
