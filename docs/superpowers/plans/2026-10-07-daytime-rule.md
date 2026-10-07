# Daytime Rule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Room #4FC03172 switches on only strategies that pay a loss after fees, won 70%+ in daytime (stock tokens) and are still winning over 7 days, and never opens a stock-token trade outside 9:30am–4pm New York.

**Architecture:** One pure module (`daytime_rule.py`) holds every check; the watcher's daily switch-on pass, the runner's entry loop and Backtest a room's follow mask read one room-settings flag (`daytime_rule: {"since": ts}`) and call it. Trade lists come from `room_replay.build_lists` (cached, minute-exact).

**Tech Stack:** Python 3.13, pytest, zoneinfo.

**Spec:** `docs/superpowers/specs/2026-10-07-daytime-rule-design.md`

## Global Constraints

- Practice only; real money never touched. Other rooms unchanged (flag absent = today's behaviour, byte for byte).
- Market hours: Mon–Fri 9:30am–4:00pm `America/New_York`, judged on the ENTRY time; no holiday calendar.
- Stock token: coin/symbol name ends in `STOCK` (`..._USDT` stripped).
- Line = the room's `on_winrate` (70 for #4FC03172); daytime ≥ 20 trades; 7 days ≥ 5 trades.
- Dates printed with `positions_view.fmt_when`. Commit with `scripts/commit_own.py`, push to origin + colleague.

## Review Focus

1. A candidate with no trade list (build failed) — must fail the screen, named, never pass by default.
2. A list whose `end_ms` is far behind now (stale pair) — windows end at `end_ms`, so the 7-day check is not empty-by-clock.
3. The runner's skip must mark the candle seen, or it re-reads it every cycle and floods the log.
4. Daylight-saving: zoneinfo per timestamp, never a fixed −4/−5 hours.
5. The flag absent: every path behaves exactly as before.

---

### Task 1: the checks (`tradingagents/daytime_rule.py`)

**Files:** Create `tradingagents/daytime_rule.py`; Test `tests/test_daytime_rule.py`.

**Produces:** `is_stock(name)->bool`, `in_market_hours(ts_s)->bool`, `fee_of(row)->float|None`, `pays_a_loss(row)->bool`, `list_checks(trades, coin, end_ms, line)->str` ("" passes, else the reason), `screen(rows, cfg, *, lists_for)->(passed:list, failed:dict[id->why])`, `enabled(settings)->float|None` (the `since`).

- [ ] Tests: market hours (Mon 9:30am in, 4:00pm out, Sat out, a DST date), is_stock, pays_a_loss on real numbers (TP 1.5/SL 1.0/fee 0.22 passes; TP 1.0/SL 0.8/fee 0.22 fails; no fee fails), list_checks (daytime < 20 fails; daytime 70%+ and 7-day 70%+ passes; crypto ignores daytime; windows end at end_ms), screen (fee fail skips the list build; missing list fails "no trade list").
- [ ] Watch them fail; implement; pass; commit.

### Task 2: the watcher's daily pass

**Files:** Modify `tradingagents/strategy_watcher.py` (`_on_pass`); Test `tests/test_daytime_rule.py`.

- [ ] Test (watcher `world`-style fixture): with `daytime_rule` in settings, a candidate failing a check is not switched on and its reason is logged; a RUNNING watcher row that is a candidate but fails is switched off with "daytime rule: …"; without the flag nothing changes.
- [ ] Implement: after `rows = [r for r in cands if not wp.passes_on(r, cfg)]`, when `daytime_rule.enabled(settings)`: `rows, failed = dr.screen(rows, cfg, lists_for=_daytime_lists)` where `_daytime_lists(rows)` calls `room_replay.build_lists([room_replay._cand_of(r) ...], store=stores.V2)`; running watcher slots whose id is in `failed` are disarmed in the same settings write and logged as `off`.
- [ ] Pass; commit.

### Task 3: the runner never opens a stock token after hours

**Files:** Modify `tradingagents/auto_trader.py` (the per-strategy entry loop, before the cost gate); Test `tests/test_daytime_rule.py`.

- [ ] Test: with the flag, at a Saturday or 10:00pm New York instant, a stock-token strategy's candle is marked seen, no gate call, one `market_closed` ledger row within the hour (a second call in the same hour writes none); a crypto strategy is untouched; without the flag nothing changes.
- [ ] Implement `_daytime_closed(settings, symbol, now)` and the skip; pass; commit.

### Task 4: Backtest a room follows it

**Files:** Modify `tradingagents/room_replay.py` (`room_lists` skip); Test `tests/test_daytime_rule.py`.

- [ ] Test: a room with `daytime_rule.since` masks a stock-token backtest entry outside market hours after `since`, keeps one before `since`, keeps crypto.
- [ ] Implement; pass; commit.

### Task 5: switch it on for #4FC03172 and watch the first pass

- [ ] CLAUDE.md: a MANDATORY section (the asks, the measured table, the rule, the flag).
- [ ] Warn, restart the API (watcher thread) and #4FC03172's runner on the new code.
- [ ] Write `daytime_rule: {"since": now}` into #4FC03172's settings through `save_settings`; clear its watcher `last_on_pass` so today's pass runs now.
- [ ] Watch the pass: how many candidates, passed each check, switched on, switched off; the runner's first `market_closed` row; report Before | After.
