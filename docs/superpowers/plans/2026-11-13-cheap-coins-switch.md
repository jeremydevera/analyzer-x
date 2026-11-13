# Cheap-coins switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Forecast v4 switch-on rule set is also walked with a $0.25 round-trip cost cap, so the picker can hand a room a version that never switches on expensive coins.

**Architecture:** The cap is one more "kind" filter beside the stop cap (`SL_CAPS`): a strategy's cost = $100 x (2 x fee + 2 x slip) from its store row; the walk, `switched_on`'s SQL, the calendar's `_takes`, the picker's rule copy and the picker lab's kind key all carry `cost_cap`. A rule with no cap hashes and reads exactly as before.

**Tech Stack:** Python (numpy, sqlite3), FastAPI route params, Next.js/TypeScript page.

**Spec:** `docs/superpowers/specs/2026-11-13-cheap-coins-switch-design.md`

## Global Constraints

- `forecast_v4.COST_CAPS = (0.0, 0.25)` — dollars per $100 round trip; 0 = no cap; one value only.
- `rule_id(...)` adds `|cost=0.25` ONLY when `cost_cap` is set; `rule_id(30, 90, 20, "any", 0.0, "", "")` stays `D7EN8BNV`.
- A strategy whose fee or slip is unknown (NULL) is never cheap (unknown is not ok), in the walk and in the SQL alike.
- Rule words: `", only on coins costing $0.25 or less per $100 traded"` appended when capped.
- Dates printed only through `fmt_when` / `fmtWhen`; every filter applied on the server.

## Review Focus

- A strategy with a NULL slip: must be left out of a capped rule in BOTH the walk and `switched_on` (test in Task 1).
- The calendar folder written before this change has no cap column: a capped rule must not read it as "every coin is cheap" (WALK_FORMAT bump, test in Task 1).
- A twin listed through `same_as` must map capped twins to capped rules, never to an uncapped one (test in Task 1).
- The picker copying a capped record must carry `cost_cap` so the room's daily list skips expensive coins (test in Task 2).
- The picker lab must count a capped kind's random pool separately from the uncapped one (test in Task 2).

---

### Task 1: The cap in Forecast v4 (walk, ids, words, SQL, page filter, calendar)

**Files:**
- Modify: `tradingagents/forecast_v4.py` (constants, `rule_id`, `rule_words`, `_load`, `_walk`, `switched_on`, `rules_page`, `_file_walk`, `_takes`, `rule_day`, `WALK_FORMAT`)
- Modify: `tradingagents/api.py` (`/api/forecast-v4/rules` takes `cost`)
- Test: `tests/test_forecast_v4_cheap_coins.py`

**Interfaces:**
- Produces: `COST_CAPS: tuple[float, ...]`; `rule_id(window, win_rate, min_trades, tp_rule, sl_cap, tf, skill, money="", cost_cap=0.0) -> str`; `rule_words(..., money="", cost_cap=0.0) -> str`; each rule record carries `"cost_cap": float`; `switched_on(rule)` honours `rule["cost_cap"]`; `rules_page({"cost": "cheap" | "none"})`.

- [ ] Step 1: tests — `test_old_ids_never_change_and_a_capped_rule_has_its_own` (D7EN8BNV / KK9SRY28 unchanged, capped id differs); `test_a_capped_rule_switches_on_only_cheap_coins` (fixture adds CHP 1h, slip 0.0004 → $0.23; a capped rule's trades are CHP's only); `test_switched_on_matches_the_walk_for_capped_rules`; `test_an_unknown_cost_is_never_cheap` (slip set NULL, forecast rebuilt: CHP leaves the capped rule, `switched_on` agrees); `test_a_capped_twin_is_listed_as_a_capped_rule`; `test_the_page_filters_by_coin_cost_on_the_server`; `test_the_calendar_list_equals_its_box_for_capped_rules`; `test_a_calendar_folder_from_before_the_cap_is_not_read`.
- [ ] Step 2: run them — FAIL (`rule_id` has no `cost_cap`).
- [ ] Step 3: implement; the cost array in `_load` is `inf` where fee/slip is NULL; the walk's kind loop iterates `COST_CAPS` inside `SL_CAPS`; `same_as` maps with the kind's own cap; `WALK_FORMAT = 2` with an `s_cheap` column.
- [ ] Step 4: run `tests/test_forecast_v4_cheap_coins.py tests/test_forecast_v4.py tests/test_forecast_v4_calendar.py` — PASS.

### Task 2: The picker, the lab and the page carry the cap

**Files:**
- Modify: `tradingagents/v4_picker.py` (`_rule_of`), `tradingagents/v4_picker_lab.py` (visit key, rule entry), `webapp/src/components/forecast/ForecastV4.tsx` (a "coins" filter, `cost_cap` on `Rule`)
- Test: `tests/test_forecast_v4_cheap_coins.py`

**Interfaces:**
- Consumes: Task 1's `cost_cap` on records and `rule_id(..., cost_cap=)`.

- [ ] Step 1: tests — `test_the_picker_carries_the_cap_to_the_rooms_list` (`_rule_of(rec)` hashes back to `rec["id"]` for a capped record); `test_the_lab_counts_a_capped_kind_on_its_own` (the visit key holds `cost_cap`); `test_the_page_has_a_coin_cost_filter_sent_to_the_server`.
- [ ] Step 2: run — FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: run the new file plus `tests/test_v4_picker.py tests/test_v4_picker_lab.py tests/test_v4_picker_rooms.py`, then `npx tsc --noEmit` — PASS.

### Task 3: Rebuild, check on the real store, document, commit

- [ ] Rebuild Forecast v4 on the real store; print the leading rule sets beside their capped twins; restart the site; check the filter in the browser.
- [ ] CLAUDE.md Forecast v4 section: the cap, the numbers that bought it, the known simplification.
- [ ] Commit with `scripts/commit_own.py`, push to origin, colleague and teammate.
