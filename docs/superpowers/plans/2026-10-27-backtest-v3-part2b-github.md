# Backtest v3 — Part 2b: the families measured on GitHub, judged, kept and shown — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure Part 2a's four idea families on every coin of the v3 universe on all 60 GitHub machines, bring every record home into the v3 store, judge them pooled with the proof test, keep every verdict with what it was judged under, show the verdicts on the Backtest v3 tab and on a results page with the standard kit, and state COVERAGE FIRST - with the order-book backfill it needs - before the whole universe runs.

**Architecture:** One new GitHub machine script (`.github/scripts/v3_shard.py`, workflow `.github/workflows/v3.yml`) calls Part 2a's `v3_measure.measure_coin` per claimed coin at the research's $5 risk and writes one record per coin. Five new PC modules, one job each: `v3_cloud` deals, starts, redoes, collects and lands the runs (the `cq_search` pattern, its run found through `forecast_v2_daily.dispatch`); `v3_verdicts` judges a landed run with Part 2a's own judge (`v3_research.report`) under the plan the run was dispatched with and keeps the verdict store; `v3_page.tested` lists it on the tab; `v3_results_page` builds the artifact page; `v3_coverage` states COVERAGE FIRST and presses the existing `costs.yml` backfill. Part 2a's engine and measurement change in one additive way: each trade row keeps the stop and target it opened with, and the older walk pays the older days' own flat gap once they have readings.

**Tech Stack:** Python 3.13 on this PC (`.venv`), Python 3.12 on GitHub (`pandas==3.0.5`, `numpy==2.5.2`, `requests` - the PC's own versions), pytest, ruff; `gh` (already signed in, active account `jeremydvera`); node (tests run the results page's own JavaScript); Next.js + TypeScript for the tab (`webapp/`).

**Spec:** `docs/superpowers/specs/2026-10-22-backtest-v3-design.md` (Part 2, Part 3, the build order, COVERAGE FIRST), and the binding decisions made inside it: `docs/superpowers/specs/2026-10-23-backtest-v3-part2-decisions.md` ("Two plans": this is Part 2b). Part 2a's plan and its "Notes for Part 2b": `docs/superpowers/plans/2026-10-23-backtest-v3-part2a-families-and-proof.md`.

## Decisions for the operator

Each is the operator's to make; the recommendation is beside it. None blocks Tasks 1-7 (the code); each is asked in Task 8's runbook at the step that needs it.

1. **Which order books to fill before the universe run (CLAUDE.md "COVERAGE FIRST").** The cost store holds every coin's per-minute book from Aug 16, 2026 on (`~/.tradingagents/costs_daily.json`, `done_days`, read Oct 27, 2026). A plan built on Oct 28, 2026 has unseen days Jul 30 - Oct 27, 2026 (so a 17-day gap, Jul 30 - Aug 15) and older days Oct 28, 2025 - Jul 29, 2026 (about 275 days, none held). Options: (a) fill the unseen gap only (about 3,900 coin-days), run, and print beside every verdict the older days' typical-cost share - the older days only CHOOSE the setting, and a typical cost there is a cost level, never a price path; (b) fill the whole window first (about 66,000 coin-days), then run; (c) run now with every gap disclosed. **Recommendation: (a) now, then (b) as a follow-up and the universe run again (about 40 minutes) and published again - both kept.** The time of each is MEASURED by the pilot's own first backfill press (Task 8 step 6) before anyone chooses: from the daily costs job's runs (353 coins of one day in 4-10 minutes on 20 machines) and BTC's 132 s a day, (a) is expected at 1-3 hours of all 60 machines and (b) at 10-30 hours. One read-only check made for this plan: Gate's archive answered 200 for `XAU_USDT` 2026-06-03 12:00 UTC (8.6 MB for the hour) and 404 for 2025-11-03 - a coin listed inside the window has no book before its listing, which the backfill counts as `hours_missing`, never as a failure.
2. **The 20 pilot coins.** **Recommendation:** BTC_USDT, ETH_USDT, SOL_USDT, XRP_USDT, DOGE_USDT, BNB_USDT, LINK_USDT, ADA_USDT (liquid every month and calm crypto in October), ZEC_USDT, PEPE_USDT, FARTCOIN_USDT, HYPE_USDT, TAO_USDT (liquid and volatile; HYPE and TAO settle funding every 4 hours), 龙虾_USDT (a Chinese-named coin: the claim board and file names), XAU_USDT, XAG_USDT, XPT_USDT (metals; XPT settles every 4 hours), EURUSD_USDT (forex), SPX500_USDT, NAS100_USDT (indices). All 20 are in research/v3/plan.json of Oct 24, 2026; a rebuilt plan that drops one replaces it with the next calm or liquid coin of the same kind, named in the runbook's log.
3. **Redraw the random runs?** The decisions doc says Part 2b *may* redraw them until a run trades as often as the real one. **Recommendation: no** - keep the stricter bar ruled on Oct 27, 2026 (it can fail a real edge at "random", never pass a false one; every verdict prints the shortfall). Decide it BEFORE the universe runs: changing the bar after seeing verdicts is choosing the test by its answer.
4. **Max TP % on a trailing stop.** Trend, breakout and strength exit on a trailing stop with no target. **Recommendation:** any max TP % leaves those rows out (no target is not "a target the market actually reaches", the operator's words of Sep 03, 2026), and the count line says how many it left out and why.
5. **"Last N days" and the risk box on the results page.** The page cannot carry a year of minutes, so it cannot re-walk candles. **Recommendation:** "last N days" re-adds each row from its measured trades that CLOSED in the window (the window's real dates and "re-added" printed beside the count, the month columns outside it removed), and the risk box rescales every dollar linearly with the words "scaled from the $5.00 measured: at another risk some trades would be sized differently or be under one lot". A true re-walk of one coin stays on the tab's run box.

## Global Constraints

- **Read before the first edit:** the newest entries of `docs/OPERATOR-ASKS.md` (CLAUDE.md "remember-my-asks"); quote, never paraphrase.
- **v1, v2, the live runner and the rooms do not change.** The one engine change is two keys added to each trade (`stop_px`, `target_px`); every other default is the rule of before, and every existing test named in a task stays green.
- **The research risk is $5 a trade, always passed explicitly:** the shard calls `measure_coin(..., risk_usd=v3_rules.RESEARCH_RISK_USD)`; records at any other risk are refused at landing and at judging, by name.
- **63 combinations, 27 judged groups, z = 3.355, 200 random runs, 2,000 bootstrap draws, 300 unseen trades to pass** - all read from Part 2a's code (`v3_proof.TRIED`, `v3_proof.Z`, `v3_random.RUNS`), never typed.
- **One plan per run:** the dispatch sends `research/v3/plan.json`'s id as the workflow's `plan_id` only when that file is the one on origin/main; a machine whose checkout holds another plan measures nothing (exit 2, named); the run keeps a copy of its plan (`<name>.plan.json`) and is judged under that copy, never under a rebuilt file.
- **Every GitHub job uses every account (CLAUDE.md, 60 machines):** coins are dealt with `cloud_sweep.split_coins` over `forecast_v2_daily.fleets_now()` (origin first), forks are synced with `cloud_sweep.sync_fleet` before they are dispatched to, an account that refuses is NAMED and redone alone (`redo`), never the whole run. Every workflow sets `env: TA_VENUE: gate`; `v3.yml` has 4 inputs (GitHub allows 10).
- **A failed coin is redone alone and its old record deleted first** - on the machine (`COIN_RETRIES = 2`, named if it never recovers) and on the PC (`retry`, into the same folder).
- **Never dispatch between 12:45am and 5:00am** (this PC's clock; `cq_search.quiet_hours`), and no backfill press beside the daily costs job on a month file it writes (`v3_coverage.clash`).
- **Where files go:** every big file under `stores.V3.home` (`~/.tradingagents/v3`, a junction onto G:): run artifacts in `cloud/run-<id>/`, records in `research/<name>/`, verdicts in `verdicts.json` and `verdicts/`, pages in `pages/`. Never `%TEMP%`, never C:.
- **The v3 store fence stays:** nothing here is a `db_jobs` kind and nothing runs with `stores.V3.env_for()` (the 16 `endswith("_v2")` gates beside `stores.V3` are untouched).
- **Do not import `sweep_shard` with `RES="v3"`** (it exits): the shard pops `RES` before importing it.
- **Code rules:** dates print only through `positions_view.fmt_when` (Python) and the page's `fmtWhen` copy (held equal by a node test); a UTC day KEY for `costs.yml` (`2026-10-01`) is never printed; nothing below an `if __name__ == "__main__":` guard; the exchange only as `fx` through `tradingagents.dataflows.exchange`; no literal exchange name in a printed string (`venue.name()`/the plan's `venue`); ruff with the project's config.
- **Labels from data (CLAUDE.md "label-must-match-data"):** every heading, count and sentence on the tab and the page is derived from the store (passed of judged, coins of the plan's coins, combinations tried, the window's dates); a store judged on fewer coins than its plan holds says "pilot ... not the proof".
- **Testing on this PC:** run ONE pytest at a time (check first: PowerShell `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'pytest' }`); each task runs only the files it names; tests reach no network and start no background program; the shard's tests run it in its own process in a temporary folder.
- **Before each commit:** the harddev hunt (callers, the state it runs in, failure paths, units, sides) named in the message; `git diff HEAD -- <path>` for every path (commit_own commits WHOLE files; other sessions edit this checkout); never `git add -A`, never `git stash`.
- **Commit and push:** message in a file OUTSIDE the repo (your scratchpad), ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; `.venv/Scripts/python scripts/commit_own.py -F <msg-file> <paths>`; `git push -q origin main && git push -q colleague main && git push -q teammate main`. Anything the CI runs (`.github/*`) is pushed the moment it is committed.

## Review Focus

1. **A coin named in Chinese characters** (龙虾_USDT and 牛来_USDT are liquid in October, 2026). Its claim, its record file (`x` + its UTF-8 in hex, `v3_research.coin_file`) and its landing must all work, never a coin silently unmeasured (RCA-2026-10-22-D). Pinned in Task 3 by `test_the_collect_lands_this_runs_records_and_names_every_coin_it_did_not` (the coin lands from a's share) and in the pilot (Decision 2 holds one).
2. **A share GitHub refuses, or takes and lists late.** The refused share is named and redone alone; a run that appears after a raised dispatch is ADOPTED, never started twice. Pinned in Task 3 by `test_a_refused_share_is_redone_by_itself_and_a_late_listed_run_is_adopted` and `test_the_dispatcher_adopts_a_run_github_listed_late_never_starting_a_second`.
3. **The plan file changing under a run** - rebuilt between dispatch and a fork's checkout, or between the run and its judging. A machine holding another plan measures nothing; the run is judged under its own kept copy; a retry after a rebuild is refused by name. Pinned in Task 2 by `test_a_machine_whose_plan_is_not_the_dispatchs_measures_nothing`, Task 3 by `test_a_plan_that_is_not_on_origin_main_is_never_dispatched`, Task 4 by `test_a_plan_copy_that_is_not_the_runs_plan_is_refused`.
4. **A coin that fails** (a cut connection, `IncompleteRead`) on a machine, or a coin whose old record sits in the landing folder from a run before. Redone alone on the machine, named when it never recovers, and its old record deleted at landing; a folder of another plan is never landed into. Pinned in Task 2 by `test_a_coin_that_fails_once_is_redone_by_itself_and_one_that_never_recovers_is_named`, Task 3 by `test_a_coin_that_failed_this_time_loses_its_old_record` and `test_a_folder_holding_another_plans_records_is_never_landed_into`.
5. **A backfill press beside the daily costs job.** Two runs adding to one month file on one account keep only one run's days. Refused while the daily job has a run in the air, and inside its hours for a month it writes. Pinned in Task 6 by `test_a_backfill_press_never_runs_beside_the_daily_costs_job_on_its_months`.

## Decisions this plan makes inside the decisions doc (each fixed before any result, with why)

A. **Records travel as artifacts only, not through the live door.** The door (`live_ingest`) lands Backtest v2 pair rows through `cloud_sweep.land_rows`; v3 records are one 72-90 KB file per coin (about 20 MB for 228 coins) and the run lasts about 30-45 minutes, so the door would add a tunnel and a second landing path for no hour saved.
B. **The shard reuses `sweep_shard`'s claim board, coin list and log** (`coin_stream`, `eligible`, `report`, `log`), imported with `RES` popped, exactly as `cq_shard` reuses them; it never calls `run_pair`.
C. **A machine refuses to measure, rather than measuring under the wrong plan or venue** (exit 2, `refused` in its report, named at collect).
D. **The run is judged by Part 2a's own judge** (`v3_research.split_records` + `report`), so the PC's `judge` command and the published verdicts can never disagree.
E. **Each trade row gains its opening stop and target** (rows of 8 fields, record version 2); `v3_proof` reads only the first six, so Part 2a's judge is unchanged.
F. **The older walk pays the older days' own flat gap once they have readings** (Part 2a's note: "two gaps, one per walk"); with none it keeps the whole window's figure, and says so.
G. **Results-page rows are the 27 judged groups**, each with its chosen setting's pooled unseen trades; the 63 combinations are counted above the table, and every setting's OLDER figures are in the row's panel (the unseen figures of settings not chosen are never shown: reading them would be choosing on the unseen days).
H. **A backfill press is the existing `costs.yml`** for the plan's coins and the missing days, newest first, 30 days a press by default; its days are done only when every share is green (the `costs_daily` rule), kept in `cloud/backfill.json`.

## Sizing (from Part 2a's measured numbers)

| quantity | measured or derived |
|---|---|
| one coin, 200 random runs, this PC | 148-194 s (BTC 194 s, XAU 148 s; 20-75 s of it reading the year of minutes), 72-90 KB compressed |
| coins in the plan | 228 (research/v3/plan.json, Oct 24, 2026) |
| one coin on a GitHub runner | assumed 150-300 s (no v3 coin has run there yet: the pilot measures it, `collect`'s `seconds`) |
| the universe on 60 machines | 228 / 60 = 3.8 coins a machine: about 15-25 minutes of measuring, the slowest machine at most ~5 coins x 5 minutes, far under the 350-minute job limit (`COIN_RETRIES` stop starting at 4.8 hours) |
| the pilot | 20 coins dealt 7 / 7 / 6: one coin a machine, about 5-8 minutes |
| collect + publish | about 20 MB of artifacts, a few minutes; judging 228 coins seconds to a minute |

---

### Task 1: Each trade keeps the stop and target it opened with; two flat gaps, one per walk

**Files:**
- Modify: `tradingagents/v3_engine.py:618-621` (the `trades.append` in `walk`)
- Modify: `tradingagents/v3_measure.py` (module docstring lines 11-20, `VERSION`, new `older_gap`, `read_window`, new `_frac`, `compact`, `_measure_tf`)
- Modify: `tradingagents/v3_research.py:171-175` (`coin_line`)
- Test: `tests/test_v3_engine.py` (append one test), `tests/test_v3_measure.py` (three assertions widened, one test extended, one test appended)

**Interfaces:**
- Consumes: Part 2a's `v3_engine.walk`, `v3_measure.measure_coin`, `cost_store.usual_slip`, `v3_measure._book_before`.
- Produces: every trade of `ve.walk` carries `"stop_px": float` and `"target_px": float | None`; every compact row is `[signal_ms, entry_ms, exit_ms, side, pnl, why, stop, target]` (stop and target as fractions of the entry, 5 places; target None for a trail); `v3_measure.VERSION == 2`; `rec["pre"]` gains `"flat_slip_older": float` and `"flat_slip_older_source": str`; `v3_measure.older_gap(book, split_ms, whole) -> (float, str)`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_v3_engine.py`:

```python
# ---- Backtest v3 Part 2b: a trade keeps the stop and the target its order went in with ---------

def test_a_trade_keeps_the_stop_and_target_its_order_went_in_with():
    # a fixed 2% stop and 1% target on a 100.0 entry
    fill_hour = [(100.1, 99.9)] * 10 + [(100.0, 99.95)] + [(100.5, 100.0)] * 49
    bars, fine = _fixed_world(fill_hour, [(101.5, 100.5)] + [(101.6, 101.0)] * 59)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["stop_px"] == pytest.approx(98.0) and tr["target_px"] == pytest.approx(101.0)
    # a trail: 3 x ATR(20) 0.205 under the 100.0 signal close, and no target. The trail moves
    # its stop later (to 99.485); the trade keeps the FIRST one, the one the order went in with
    bars, fine, dirs = _trail_world(FLAT, FLAT)
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine)["trades"]
    assert tr["stop_px"] == pytest.approx(100.0 - 3 * 0.205) and tr["target_px"] is None
```

In `tests/test_v3_measure.py`, in `test_a_coin_is_measured_for_every_family_setting_timeframe_and_filter_it_can_trade`, replace

```python
    # each dip's waiting buy at 99.3 fills in the next hour's first minute (low 99.25) and the
    # second minute (high 100.1) trades through the target
    assert old["rows"] == [[OLD_DIP, OLD_DIP + H, OLD_DIP + H + M, 1, pytest.approx(_snap_pnl()),
                            "TP"]]
    assert new["rows"] == [[NEW_DIP, NEW_DIP + H, NEW_DIP + H + M, 1,
                            pytest.approx(_snap_pnl()), "TP"]]
```

with

```python
    # each dip's waiting buy at 99.3 fills in the next hour's first minute (low 99.25) and the
    # second minute (high 100.1) trades through the target. The row ends with the stop and the
    # target the order went in with, as fractions of the 99.3 entry: 3 x ATR 0.23 = 0.69 under
    # it (0.69 / 99.3 = 0.00695) and the 99.965 average over it (0.665 / 99.3 = 0.0067)
    assert old["rows"] == [[OLD_DIP, OLD_DIP + H, OLD_DIP + H + M, 1, pytest.approx(_snap_pnl()),
                            "TP", 0.00695, 0.0067]]
    assert new["rows"] == [[NEW_DIP, NEW_DIP + H, NEW_DIP + H + M, 1,
                            pytest.approx(_snap_pnl()), "TP", 0.00695, 0.0067]]
```

In `test_the_flat_gaps_source_says_how_many_of_its_minutes_lie_on_the_older_days`, after its last line (`assert pre["coverage_older"] == 0.0`), add

```python
    # with no reading of their own, the older days keep the whole window's figure, and say so
    assert pre["flat_slip_older"] == pytest.approx(0.0005)
    assert pre["flat_slip_older_source"] == (
        "no reading of its own on the older days: the median of its 2 recorded minutes whose "
        "book did not run out, 0 of them on the older days")
```

In `test_strength_enters_at_a_monday_rank_and_is_forced_out_when_it_drops_past_the_top_2k`, replace the `k3` and `k5` row assertions

```python
    assert k3["older"]["rows"] == [[SEP21 - DAY, SEP21, SEP28, 1,
                                    pytest.approx(-166.0 * (0.0002 + 0.00075 + 0.0002)), "RANK"]]
```
```python
    assert k5["older"]["rows"] == [[SEP21 - DAY, SEP21, SPLIT_B, 1,
                                    pytest.approx(-166.0 * (0.0002 + 0.00075 + 0.0002)), "END"]]
```

with

```python
    # a 0.6 trail under a 100.0 entry is a 0.006 stop, and a trail has no target
    assert k3["older"]["rows"] == [[SEP21 - DAY, SEP21, SEP28, 1,
                                    pytest.approx(-166.0 * (0.0002 + 0.00075 + 0.0002)), "RANK",
                                    0.006, None]]
```
```python
    assert k5["older"]["rows"] == [[SEP21 - DAY, SEP21, SPLIT_B, 1,
                                    pytest.approx(-166.0 * (0.0002 + 0.00075 + 0.0002)), "END",
                                    0.006, None]]
```

Append to `tests/test_v3_measure.py`:

```python
# ---- Backtest v3 Part 2b: two flat gaps, one per walk ------------------------------------------

def test_the_older_walk_pays_the_older_days_own_flat_gap_once_they_have_readings(
        monkeypatch, gate_floors):
    from tradingagents import cost_store

    others = [f"C{k}_USDT" for k in range(9)]
    plan = _plan(START_B, END_B, {}, liquid={"2026-09": ["ABC_USDT"] + others,
                                             "2026-10": ["ABC_USDT"] + others},
                 strength={str(SEP21): ["ABC_USDT"] + others,
                           str(SEP28): others[:8] + ["ABC_USDT"],
                           str(OCT5): ["ABC_USDT"] + others},
                 kinds={"ABC_USDT": "crypto"})
    # one reading on the older days at 0.02% a side, two on the unseen days at 0.10%: the whole
    # window's median (of 0.02%, 0.10%, 0.10%) is 0.10%, the older days' own 0.02%
    book = bh.pack([_reading(START_B // 1000, 0.0002), _reading(SPLIT_B // 1000 + 3600, 0.0010),
                    _reading(SPLIT_B // 1000 + 7200, 0.0010)])
    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: book)
    up = {SPLIT_B + m * M: (101.1, 100.9) for m in range(3 * 1440)}
    rec = vm.measure_coin("ABC_USDT", plan, runs=2, fx=FakeFx(START_B, END_B, up))
    pre = rec["pre"]
    assert pre["flat_slip"] == pytest.approx(0.0010)
    assert pre["flat_slip_older"] == pytest.approx(0.0002)
    assert pre["flat_slip_older_source"] == (
        "the median of its 1 recorded minutes on the older days whose book did not run out")
    # K = 5's trade is still open at the split and closes at the last older close at the market,
    # with no reading in the hour before it: it pays the OLDER days' 0.02%, never the 0.10% read
    # off the unseen days. 166 lots of 0.01 x $100, maker in, taker out
    k5 = rec["combos"][vf.combo_key("v3_strength", "k5", "1d", "none")]
    (row,) = k5["older"]["rows"]
    assert row[5] == "END" and row[4] == pytest.approx(-166.0 * (0.0002 + 0.00075 + 0.0002))
```

- [ ] **Step 2: Run them to see them fail** (check no other pytest runs first).

Run: `.venv/Scripts/python -m pytest tests/test_v3_engine.py tests/test_v3_measure.py -q`
Expected: 5 failed - `KeyError: 'stop_px'` in the engine test; the three widened row assertions (rows of 6, not 8); `KeyError: 'flat_slip_older'`; the new older-gap test (the END row pays `0.0010`, the whole window's gap: `-166 x 0.00195`).

- [ ] **Step 3: Implement.** In `tradingagents/v3_engine.py`, `walk`, replace

```python
                       "contracts": size["contracts"], "notional": size["notional"],
                       "leverage": size["leverage"], "margin": size["margin"], **tr})
```

with

```python
                       "contracts": size["contracts"], "notional": size["notional"],
                       "leverage": size["leverage"], "margin": size["margin"],
                       # the stop and target the order went in with (a trail moves its stop
                       # later; this is the first one): what the results page's max TP % and
                       # max SL % read (Backtest v3 Part 2b)
                       "stop_px": float(levels["stop"]),
                       "target_px": None if levels["target"] is None else float(levels["target"]),
                       **tr})
```

In `tradingagents/v3_measure.py` apply this diff (every hunk is exact; the file's CRLF line endings are kept by any editor that keeps them):

```diff
--- a/tradingagents/v3_measure.py
+++ b/tradingagents/v3_measure.py
@@ -11,13 +11,11 @@
   lead-in before them; a trade still open at the split is closed at its last
   candle (`END`). Its minutes, order books and funding are CUT at the split,
   so the setting can never be chosen on an unseen price — by construction.
-  One number is NOT cut: the flat gap it pays where a minute has no reading
-  of its own — the coin's usual cost, the median of EVERY recorded minute of
-  the window, which today all lie after the split (the store holds about two
-  months). That is a cost level, never a price path, and `flat_slip_source`
-  says how many of its minutes lie on the older days, until an order-book
-  backfill over the older days (Part 2b, if the pilot shows it is needed)
-  gives them their own readings;
+  The flat gap it pays where a minute has no reading of its own is the
+  older days' own (the median of the readings before the split, `older_gap`)
+  once they have readings - the order-book backfill of Part 2b. Where they
+  have none it is the whole window's figure, a cost level, never a price
+  path, and `flat_slip_older_source` says which it is;
 * the UNSEEN walk: the newest 90 days, the lead-in before them read by the
   indicators only;
 * RUNS random runs on the unseen window (`v3_random`), measured for EVERY
@@ -51,7 +49,10 @@
     v3_universe as vu,
 )
 
-VERSION = 1
+# 2 (Backtest v3 Part 2b): every trade row carries the stop and target it opened with, as
+# fractions of its entry, and the older walk pays the older days' own flat gap where they have
+# readings. A record of version 1 holds neither; the proof reads only the first six fields
+VERSION = 2
 UNSEEN_DAYS = 90
 DAY_MS = 86_400_000
 BOOK_USD = 100.0          # a recorded reading is the cost of walking the book for $100
@@ -130,6 +131,22 @@
                                    f"({type(exc).__name__})")
 
 
+def older_gap(book, split_ms: int, whole: tuple[float, str]) -> tuple[float, str]:
+    """The OLDER walk's flat gap: the median of the recorded minutes stamped
+    before the split (`_book_before`, the cut every older read takes), so a
+    setting is chosen on the older days' own cost level once they have
+    readings (the order-book backfill, Part 2b). Where they have none - the
+    store held about two months on Oct 27, 2026 - the older walk keeps the
+    whole window's figure `whole` (value, source), and its source says so."""
+    from tradingagents import cost_store
+
+    slip, n = cost_store.usual_slip(_book_before(book, split_ms))
+    if slip is not None:
+        return slip, (f"the median of its {n:,} recorded minutes on the older days whose book "
+                      "did not run out")
+    return whole[0], f"no reading of its own on the older days: {whole[1]}"
+
+
 def prefetch(sym: str, plan: dict, leads: dict, *, fx) -> dict:
     """Everything one coin's walks read, fetched ONCE: {tf: bars} with each
     timeframe's longest lead-in before the window, the minutes of the window,
@@ -167,17 +184,20 @@
     fees = {"maker": at.maker_fee_floor(), "taker": at.fee_floor()}
     meta = {"contract": contract, "fees": fees, "flat_slip": slip, "flat_slip_source": source,
             "minutes": len(fine[0]), "five_minute": int(n5)}
+    slip_older = slip
     if split_ms is None:
         meta["coverage"] = cost_store.coverage(book, start // 1000, end // 1000)
     else:
         meta["coverage_older"] = cost_store.coverage(book, start // 1000, split_ms // 1000)
         meta["coverage_unseen"] = cost_store.coverage(book, split_ms // 1000, end // 1000)
+        slip_older, meta["flat_slip_older_source"] = older_gap(book, split_ms, (slip, source))
+        meta["flat_slip_older"] = slip_older
     meta |= {"funding": len(funding),
              "funding_from_ms": int(funding[0]["settle_ms"]) if funding else None,
              "cycle_h": float(spec.get("funding_interval_h") or 8)}
     return {"bars": bars, "fine": fine if fine[0] else None, "book": book, "funding": funding,
-            "contract": contract, "fees": fees, "slip": slip, "cycle_h": meta["cycle_h"],
-            "meta": meta}
+            "contract": contract, "fees": fees, "slip": slip, "slip_older": slip_older,
+            "cycle_h": meta["cycle_h"], "meta": meta}
 
 
 def _before(pre: dict, split: int) -> dict:
@@ -195,14 +215,25 @@
     return {k: v[a:b] for k, v in bars.items()}
 
 
+def _frac(px, entry: float) -> float | None:
+    """A level's distance from the entry, as a fraction of it (5 places), or None."""
+    return None if px is None else round(abs(float(px) - float(entry)) / float(entry), 5)
+
+
 def compact(walked: dict, t, signals: dict) -> dict:
-    """One walk in the shape every machine returns."""
+    """One walk in the shape every machine returns. A trade row is [signal_ms,
+    entry_ms, exit_ms, side, pnl, why, stop, target]: the last two are the stop
+    and the target the order went in with, as fractions of the entry (a trail
+    has no target: None) - what the results page's max SL % and max TP % read.
+    Everything that reads the first six fields reads them as before."""
     trades = walked["trades"]
     twins = [m["market"] for m in walked["missed"] if "pnl" in m["market"]]
     lev = [int(x["leverage"]) for x in trades]
     notional = [float(x["notional"]) for x in trades]
     return {"rows": [[int(t[x["signal_bar"]]), int(x["entry_ms"]), int(x["exit_ms"]),
-                      int(x["side"]), round(float(x["pnl"]), 6), x["why"]] for x in trades],
+                      int(x["side"]), round(float(x["pnl"]), 6), x["why"],
+                      _frac(x["stop_px"], x["entry"]), _frac(x.get("target_px"), x["entry"])]
+                     for x in trades],
             "counts": {k: int(v) for k, v in walked["counts"].items() if v},
             "filter": signals, "missed": len(walked["missed"]),
             "twins": [len(twins), round(sum(float(x["pnl"]) for x in twins), 6)],
@@ -267,7 +298,10 @@
     data = {"older": _before(pre, split),
             "unseen": {"fine": pre["fine"], "book": pre["book"], "funding": pre["funding"]}}
     common = {"bar_s": bar_s, "contract": pre["contract"], "fees": pre["fees"],
-              "flat_slip": pre["slip"], "risk_usd": risk_usd}
+              "risk_usd": risk_usd}
+    # each walk's own flat gap: the older days' where they have readings (`older_gap`), the whole
+    # window's for the unseen walk and its random runs
+    gap = {"older": pre.get("slip_older", pre["slip"]), "unseen": pre["slip"]}
     for fam in fams:
         if tf not in vf.FAMILIES[fam]["tfs"]:
             continue
@@ -290,7 +324,8 @@
                     a = p["a"]
                     dirs = dirs_of(p["rule"], ok_l, ok_s, a)
                     walked[part] = ve.walk(p["bars"], dirs, spec, start=p["start"],
-                                           forced=p["forced"], **common, **data[part])
+                                           forced=p["forced"], flat_slip=gap[part], **common,
+                                           **data[part])
                     out[part] = compact(walked[part], p["bars"]["t"],
                                         _signals(p["rule"], long_m, short_m, keep_l, keep_s,
                                                  flags, a, p["start"]))
@@ -298,7 +333,8 @@
                 seeds = [vrn.seed_of(sym, tf, fam, filt, k) for k in range(runs)]
                 out |= _random_runs(
                     u, walked["unseen"], ok_l, ok_s, days, bar_ms, seeds,
-                    {**common, **data["unseen"], "start": u["start"], "forced": u["forced"]},
+                    {**common, **data["unseen"], "flat_slip": gap["unseen"], "start": u["start"],
+                     "forced": u["forced"]},
                     spec)
                 rec["combos"][vf.combo_key(fam, vf.setting_key(fam, v), tf, filt)] = out
     return ""
```

In `tradingagents/v3_research.py`, `coin_line`, replace

```python
            f"{pre.get('flat_slip_source', '?')}); {len(rec.get('combos', {}))} combinations"
```

with

```python
            f"{pre.get('flat_slip_source', '?')}"
            + (f"; the older walk's: {100 * pre['flat_slip_older']:.5f}%, "
               f"{pre.get('flat_slip_older_source', '?')}" if "flat_slip_older" in pre else "")
            + f"); {len(rec.get('combos', {}))} combinations"
```

- [ ] **Step 4: Run them, and every file that reads a trade or a record.**

Run: `.venv/Scripts/python -m pytest tests/test_v3_engine.py tests/test_v3_measure.py tests/test_v3_research.py tests/test_v3_proof.py tests/test_v3_smoke.py tests/test_backtest_v3_tab.py tests/test_backtest_v3_tab_families.py tests/test_v3_shared_rules_learn_the_waiting_order.py -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_engine.py tradingagents/v3_measure.py tradingagents/v3_research.py tests/test_v3_engine.py tests/test_v3_measure.py`
Expected: all pass (proven in scratch: engine 67, measure 31, research + proof + smoke + tab files green); `All checks passed!`.

- [ ] **Step 5: Commit and push.** Check `git diff HEAD --` for the five paths, then

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_engine.py tradingagents/v3_measure.py tradingagents/v3_research.py tests/test_v3_engine.py tests/test_v3_measure.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
feat(v3): each trade row keeps the stop and target its order went in with (record version 2), and the older walk pays the older days' own flat gap once they have readings - Part 2b, Task 1

A results page cannot offer max TP % / max SL % on rows that never kept their sizes, and Part 2a's note asked for two flat gaps, one per walk, once the backfill gives the older days readings (today the older walk pays a median read off the unseen days' books, said in its source).

harddev: callers of walk's trades (compact, v3_page._tally, smoke) read keys, never the dict whole; proof reads rows[:6]; the trail keeps its FIRST stop; a no-reading older window falls back to the whole figure, named.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 2: The machine and the workflow

**Files:**
- Create: `.github/scripts/v3_shard.py`
- Create: `.github/workflows/v3.yml`
- Test: `tests/test_v3_shard.py`

**Interfaces:**
- Consumes: `v3_measure.measure_coin(sym, plan, *, runs, risk_usd, fx, log)`, `v3_research.save_coin(root, rec) -> Path`, `v3_research.drop_coin(root, sym)`, `v3_research.coin_file(root, sym)`, `v3_universe.load(path)`, `v3_rules.RESEARCH_RISK_USD`, `v3_random.RUNS`, `sweep_shard.coin_stream / eligible / COIN_LIST / SHARD / report / log`.
- Produces: on each machine `out/v3/<coin>.json.gz` (a `measure_coin` record plus `"machine": {"repo", "run", "shard", "sha"}`) and `out/v3-report-<N>.json` = `{"shard", "plan_id", "risk_usd", "runs", "version", "machine", "report": [entry, ...], "refused"?: str}` where an entry is `{"coin", "seconds", "bytes", "combos", "why"?, "skipped"?, "tries"?}` for a measured coin, `{"coin", "error", "tries"}` for one that never recovered, `{"coin", "why"}` for one never measured. Workflow `v3.yml`: inputs `shards`, `coin_list`, `label`, `plan_id`; run-name `Backtest v3 research · <label>`; artifacts `v3-out-<shard>`.

- [ ] **Step 1: Write the failing test** `tests/test_v3_shard.py`:

```python
"""One Backtest v3 research machine end to end on a made-up market
(.github/scripts/v3_shard.py, Part 2b), with no network: every coin it was
dealt measured by `v3_measure.measure_coin` at the research's risk, its record
written whole and stamped with the machine, a coin that raises redone by
itself and named when it never recovers, every coin left out named, and a
machine whose plan is not the dispatch's refusing to measure anything.

The shard clears RES and imports sweep_shard when it loads, and writes out/,
so it runs in its own process in a temporary folder, never inside the test
session (the pattern of tests/test_cq_shard.py). The world is
tests/test_v3_measure.py's calm metal, on ONE timeline (RCA-2026-09-12-A)."""
from __future__ import annotations

import gzip
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tradingagents import v3_research as vrs, v3_rules as vr, v3_universe as vu

ROOT = Path(__file__).resolve().parent.parent

_PROG = r'''
import json, os, sys
ROOT, PLAN, PLAN_ID, COINS = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sys.path.insert(0, os.path.join(ROOT, ".github", "scripts"))
sys.path.insert(0, ROOT)
os.environ.update({"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": "acct/analyzer-x",
                   "GITHUB_RUN_ID": "4242", "GITHUB_SHA": "abc123", "INGEST_URL": "",
                   "TA_VENUE": sys.argv[5], "SHARD": "0", "SHARDS": "1", "COIN_LIST": COINS,
                   "RUNS": "2", "PLAN_FILE": PLAN, "PLAN_ID": PLAN_ID, "RES": "v3"})
import time as _time
_time.sleep = lambda s: None
import tests.test_v3_measure as tm
import tradingagents.auto_trader as at
from tradingagents import cost_store, v3_measure as vm
vm.UNSEEN_DAYS = 3
at.maker_fee_floor = lambda *a, **k: 0.0002
at.fee_floor = lambda *a, **k: 0.00075
cost_store.engine_book = lambda *a, **k: tm._book(tm.START_A // 1000)
import v3_shard as sh
sh.ss.report = lambda *a, **k: None
sh.ss.log = lambda *a, **k: None
# the exchange trades every coin asked for but GONE_USDT
sh.ss.eligible = lambda: sorted(c for c in sh.ss.COIN_LIST if c != "GONE_USDT")
calls = {}


class World(tm.FakeFx):
    """XAU_USDT and SLOW_USDT read the calm metal; FLAKY_USDT's first candle read is cut
    mid-body, then it reads like the others; DEAD_USDT's never answers."""

    def klines(self, sym, iv, limit):
        calls[sym] = calls.get(sym, 0) + 1
        if sym == "DEAD_USDT" or (sym == "FLAKY_USDT" and calls[sym] == 1):
            raise ConnectionError(f"{sym}: IncompleteRead(183452 bytes read)")
        return super().klines(sym, iv, limit)


sh.FX = World(tm.START_A, tm.END_A, tm._dips(tm.OLD_DIP, tm.NEW_DIP))
code = sh.main()
print(json.dumps({"code": code, "calls": calls}))
'''


def _plan(tmp, coins):
    """The calm metal's window as a plan file every coin of `coins` is calm in."""
    import tests.test_v3_measure as tm

    calm = {"2026-09": list(coins), "2026-10": list(coins)}
    plan = {**tm._plan(tm.START_A, tm.END_A, calm, kinds=dict.fromkeys(coins, "metals")),
            "version": vu.VERSION, "venue": "Gate", "coins": sorted(coins),
            "start": "Sep 24, 2026 8:00pm", "end": "Oct 04, 2026 8:00pm"}
    plan["id"] = vu.plan_id(plan)
    path = vu.save(plan, Path(tmp) / "plan.json")
    return path, plan["id"]


def _run(tmp, asked, plan_id=None, venue="gate", inside=None):
    path, pid = _plan(tmp, inside or [c for c in asked if c not in ("OUT_USDT", "GONE_USDT")])
    out = subprocess.run([sys.executable, "-c", _PROG, str(ROOT), str(path), plan_id or pid,
                          ",".join(asked), venue], cwd=str(tmp), capture_output=True,
                         text=True, timeout=900)
    assert out.returncode == 0, out.stderr[-3000:]
    got = json.loads(out.stdout.strip().splitlines()[-1])
    rep = json.loads((Path(tmp) / "out" / "v3-report-0.json").read_text(encoding="utf-8"))
    return got, rep, pid


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("v3shard")
    got, rep, pid = _run(tmp, ["XAU_USDT", "FLAKY_USDT", "DEAD_USDT", "OUT_USDT", "GONE_USDT"])
    return tmp, got, rep, pid


def _record(tmp, sym):
    with gzip.open(vrs.coin_file(Path(tmp) / "out" / "v3", sym), "rt", encoding="utf-8") as fh:
        return json.load(fh)


def test_every_coin_it_can_measure_is_one_whole_record_at_the_research_risk(world):
    tmp, got, rep, pid = world
    assert got["code"] == 0
    rec = _record(tmp, "XAU_USDT")
    # measure_coin's own record, at $5 a trade (never the tab's $1) and the plan the dispatch named
    assert rec["coin"] == "XAU_USDT" and rec["risk_usd"] == vr.RESEARCH_RISK_USD == 5.0
    assert rec["runs"] == 2 and rec["plan_id"] == pid and rec["version"] == 2
    assert rec["combos"] and all(len(c["random"]) == 2 for c in rec["combos"].values())
    assert rec["machine"] == {"repo": "acct/analyzer-x", "run": "4242", "shard": 0, "sha": "abc123"}
    entry = next(e for e in rep["report"] if e["coin"] == "XAU_USDT")
    assert entry["combos"] == len(rec["combos"]) and entry["bytes"] > 0 and "error" not in entry
    assert rep["plan_id"] == pid and rep["risk_usd"] == 5.0 and rep["runs"] == 2


def test_a_coin_that_fails_once_is_redone_by_itself_and_one_that_never_recovers_is_named(world):
    tmp, got, rep, _pid = world
    flaky = next(e for e in rep["report"] if e["coin"] == "FLAKY_USDT")
    assert flaky["tries"] == 2 and "error" not in flaky
    assert _record(tmp, "FLAKY_USDT")["coin"] == "FLAKY_USDT"
    dead = next(e for e in rep["report"] if e["coin"] == "DEAD_USDT")
    assert dead["tries"] == 3 and dead["error"].startswith("ConnectionError: DEAD_USDT")
    assert not vrs.coin_file(Path(tmp) / "out" / "v3", "DEAD_USDT").exists(), \
        "a coin that never recovered leaves no record behind"
    # DEAD_USDT's three tries each died on its first candle read
    assert got["calls"]["DEAD_USDT"] == 3


def test_every_coin_left_out_is_named_with_why(world):
    _tmp, _got, rep, _pid = world
    why = {e["coin"]: e.get("why") for e in rep["report"] if "why" in e}
    assert why["GONE_USDT"] == "the exchange is not trading it now"
    assert why["OUT_USDT"] == "not in the plan's universe"
    assert {e["coin"] for e in rep["report"]} == {"XAU_USDT", "FLAKY_USDT", "DEAD_USDT",
                                                   "OUT_USDT", "GONE_USDT"}


def test_a_machine_whose_plan_is_not_the_dispatchs_measures_nothing(tmp_path):
    got, rep, pid = _run(tmp_path, ["XAU_USDT"], plan_id="0" * 16)
    assert got["code"] == 2 and rep["report"] == []
    assert rep["refused"].startswith(f"this checkout's plan is {pid}, the dispatch named "
                                     + "0" * 16)
    assert not (tmp_path / "out" / "v3").exists() or not list((tmp_path / "out" / "v3").iterdir())


def test_a_machine_not_on_gate_measures_nothing(tmp_path):
    got, rep, _pid = _run(tmp_path, ["XAU_USDT"], venue="mexc")
    assert got["code"] == 2 and rep["refused"].startswith("TA_VENUE is 'mexc'")


def test_the_workflow_takes_exactly_what_the_dispatch_sends():
    text = (ROOT / ".github" / "workflows" / "v3.yml").read_text(encoding="utf-8")
    block = text.split("inputs:", 1)[1].split("permissions:", 1)[0]
    names = re.findall(r"^      ([a-z_]+):\s*$", block, flags=re.M)
    assert len(names) <= 10                      # GitHub allows exactly ten
    assert set(names) == {"shards", "coin_list", "label", "plan_id"}
    assert 'run-name: "Backtest v3 research · ${{ inputs.label }}"' in text
    assert "TA_VENUE: gate" in text and "timeout-minutes: 350" in text
    assert "python .github/scripts/v3_shard.py" in text and "v3-out-${{ matrix.shard }}" in text
    assert "out/v3/*.json.gz" in text and "out/v3-report-*.json" in text
    for env in ("COIN_LIST", "PLAN_ID", "SHARD", "SHARDS", "GITHUB_TOKEN"):
        assert f"          {env}: " in text, env
```

- [ ] **Step 2: Run it to see it fail.**

Run: `.venv/Scripts/python -m pytest tests/test_v3_shard.py -q`
Expected: 6 errors/failures - the subprocess cannot import `v3_shard` (`ModuleNotFoundError`), and `v3.yml` does not exist (`FileNotFoundError`).

- [ ] **Step 3: Write the machine** `.github/scripts/v3_shard.py`:

```python
"""One GitHub machine of BACKTEST V3 PART 2b (Oct 27, 2026): its share of the
universe measured the v3 way, one record per coin.

The operator: "go" (Oct 27, 2026) to Part 2b - the four idea families judged
on every coin of the universe on GitHub. Spec:
docs/superpowers/specs/2026-10-22-backtest-v3-design.md; decisions:
docs/superpowers/specs/2026-10-23-backtest-v3-part2-decisions.md; plan:
docs/superpowers/plans/2026-10-27-backtest-v3-part2b-github.md.

For every coin it claims off the board (`sweep_shard.coin_stream`: one coin at
a time, claimed on this account's sweep-progress branch), the machine calls
`v3_measure.measure_coin` - the same function `python -m
tradingagents.v3_research run` calls on the PC - against the plan file in its
own checkout, at the research's risk (`v3_rules.RESEARCH_RISK_USD`) and with
`v3_random.RUNS` random runs, and writes, the moment each coin is done:

* out/v3/<coin>.json.gz - the coin's record whole (`v3_research.save_coin`,
  the PC's own file name for a coin), stamped with the machine that measured
  it (`machine`: account, run, shard, commit);
* out/v3-report-<N>.json - one entry per coin: its seconds and size, or the
  error that ended it, or why it was never measured.

A coin that raises is redone BY ITSELF after the others, up to COIN_RETRIES,
its file deleted first (CLAUDE.md: a failed coin is redone alone); one that
never recovers is NAMED with its error. Nothing is chosen or judged here: the
PC collects every account's records (`python -m tradingagents.v3_cloud
collect`) and judges them pooled (`python -m tradingagents.v3_verdicts
publish`).

The machine refuses to measure anything - exit 2, the reason in its report -
when its checkout's plan is not the plan the dispatch named (PLAN_ID), or the
run does not trade on Gate (TA_VENUE).
"""
# ruff: noqa: E402  (sweep_shard is imported after RES is cleared, below)
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
# sweep_shard exits on a resolution it cannot download, and "v3" is a row RESOLUTION, never a
# candle frame (stores.V3): this machine uses only sweep_shard's claim board, its coin list and its
# log, so it is imported as the plain shard
os.environ.pop("RES", None)

import sweep_shard as ss

from tradingagents import (
    v3_measure as vm,
    v3_random as vrn,
    v3_research as vrs,
    v3_rules as vr,
    v3_universe as vu,
    venue as _venue,
)

PLAN_FILE = os.environ.get("PLAN_FILE") or str(vu.PLAN_FILE)     # tests name their own
PLAN_ID = (os.environ.get("PLAN_ID") or "").strip()
RUNS = int(os.environ.get("RUNS") or vrn.RUNS)                     # tests only
OUT_DIR = Path("out") / "v3"
REPORT_OUT = Path("out") / f"v3-report-{ss.SHARD}.json"
COIN_RETRIES = 2
RETRY_CUTOFF_S = 4.8 * 3600      # no retry starts after this (GitHub ends a job at 6 h)
T0 = time.time()
FX = None                        # the exchange door; tests hand in their own


def machine() -> dict:
    """Which machine measured a record: account, run, shard and commit."""
    return {"repo": os.environ.get("GITHUB_REPOSITORY", ""),
            "run": os.environ.get("GITHUB_RUN_ID", ""), "shard": int(ss.SHARD),
            "sha": os.environ.get("GITHUB_SHA", "")}


def save_report(report: list, **head) -> None:
    """The machine's report, written whole after every coin (a machine stopped
    at the time limit still hands over what it finished)."""
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = REPORT_OUT.with_name(REPORT_OUT.name + ".tmp")
    tmp.write_text(json.dumps({"shard": int(ss.SHARD), **head, "report": report}),
                   encoding="utf-8")
    tmp.replace(REPORT_OUT)


def refusal(plan: dict | None, load_error: str = "") -> str:
    """Why this machine may not measure, or "": the plan it holds is the one the
    dispatch named, and the run trades on Gate."""
    if _venue.current() != "gate":
        return f"TA_VENUE is {_venue.current()!r}: Backtest v3 measures on Gate only"
    if plan is None:
        return f"the plan file {PLAN_FILE} could not be read: {load_error}"
    if not PLAN_ID:
        return "the dispatch named no plan (PLAN_ID is empty)"
    if plan["id"] != PLAN_ID:
        return (f"this checkout's plan is {plan['id']}, the dispatch named {PLAN_ID}: the plan "
                "file changed between the dispatch and this machine's checkout")
    return ""


def board_of(plan: dict, report: list) -> list:
    """The coins this machine's account was dealt that it can measure:
    `sweep_shard.eligible` (the dispatch's coin list, less the coins the
    exchange is not trading now), less the coins outside the plan's universe.
    Every coin left out is NAMED in the report."""
    want = [c if c.endswith("_USDT") else f"{c}_USDT" for c in ss.COIN_LIST]
    live = ss.eligible()
    for c in want:
        if c not in live:
            report.append({"coin": c, "why": "the exchange is not trading it now"})
    inside = set(plan["coins"])
    for c in live:
        if c not in inside:
            report.append({"coin": c, "why": "not in the plan's universe"})
    return [c for c in live if c in inside]


def late() -> bool:
    return time.time() - T0 > RETRY_CUTOFF_S


def measure(sym: str, plan: dict) -> dict:
    """One coin's record, saved whole; its report entry."""
    t0 = time.time()
    rec = vm.measure_coin(sym, plan, runs=RUNS, risk_usd=vr.RESEARCH_RISK_USD, fx=FX,
                          log=ss.log)
    rec["machine"] = machine()
    path = vrs.save_coin(OUT_DIR, rec)
    entry = {"coin": sym, "seconds": round(time.time() - t0, 1), "bytes": path.stat().st_size,
             "combos": len(rec.get("combos", {}))}
    if rec.get("why"):
        entry["why"] = rec["why"]
    if rec.get("skipped"):
        entry["skipped"] = rec["skipped"]
    return entry


def run(plan: dict, report: list, head: dict) -> int:
    """Measure every claimed coin; a coin that raises is redone by itself after
    the others (its file deleted first), and named if it never recovers."""
    board = board_of(plan, report)
    ss.report.board = len(board)
    tries: dict = {}
    queue: list = []
    stream = ss.coin_stream(board, T0)
    done = 0
    while True:
        sym = next(stream, None)
        if sym is None:
            if not queue or late():
                for q in queue:
                    report.append({"coin": q, "error": "not redone: out of time",
                                   "tries": tries[q]})
                break
            sym = queue.pop(0)
        tries[sym] = tries.get(sym, 0) + 1
        vrs.drop_coin(OUT_DIR, sym)                # never a half-run's file beside a redo
        try:
            entry = measure(sym, plan)
            if tries[sym] > 1:
                entry["tries"] = tries[sym]
            report.append(entry)
            done += 1
        except Exception as exc:                               # noqa: BLE001
            vrs.drop_coin(OUT_DIR, sym)
            said = f"{type(exc).__name__}: {str(exc)[:200]}"
            ss.log(f"{sym}: FAILED (try {tries[sym]}) {said}")
            ss.log(traceback.format_exc()[-800:])
            if tries[sym] <= COIN_RETRIES:
                queue.append(sym)
                time.sleep(5 * tries[sym])
            else:
                report.append({"coin": sym, "error": said, "tries": tries[sym]})
        save_report(report, **head)
        ss.report("testing", done, len(board), note=f"{sym} done")
    ss.log(f"done: {done} coin(s) in {(time.time() - T0) / 60:.0f} min")
    return 0


def main() -> int:
    plan, load_error = None, ""
    try:
        plan = vu.load(PLAN_FILE)
    except (OSError, ValueError) as exc:
        load_error = f"{type(exc).__name__}: {exc}"
    head = {"plan_id": PLAN_ID, "risk_usd": vr.RESEARCH_RISK_USD, "runs": RUNS,
            "version": vm.VERSION, "machine": machine()}
    report: list = []
    why = refusal(plan, load_error)
    if why:
        ss.log(f"REFUSED: {why}")
        save_report(report, refused=why, **head)
        return 2
    ss.log(f"backtest v3: plan {plan['id']} ({plan['start']} to {plan['end']}), "
           f"${vr.RESEARCH_RISK_USD:,.2f} risk a trade, {RUNS} random runs a combination")
    return run(plan, report, head)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Write the workflow** `.github/workflows/v3.yml`:

```yaml
name: Backtest v3 research
run-name: "Backtest v3 research · ${{ inputs.label }}"

# The operator, Oct 27, 2026: "go" to Backtest v3 Part 2b - the four idea
# families measured on every coin of the universe, judged against random
# entries. Spec: docs/superpowers/specs/2026-10-22-backtest-v3-design.md;
# plan: docs/superpowers/plans/2026-10-27-backtest-v3-part2b-github.md.
#
# Its own workflow, never sweep.yml: a research run must never write the
# market grid's pair-done markers, saved positions or the store. Public market
# data only - no credentials are read. Dealt between every account by
# tradingagents/v3_cloud.py (each account gets its own coin_list). Every
# machine reads the universe from the plan file in its own checkout
# (research/v3/plan.json) and refuses to measure when that file is not the
# plan the dispatch named (plan_id).

on:
  workflow_dispatch:
    inputs:
      shards:
        description: "How many runners to split the work across"
        default: "20"
      coin_list:
        description: "Comma-separated symbols this account was dealt (BTC_USDT,XAU_USDT)"
        default: ""
      label:
        description: "A name for this run (its title)"
        default: "manual"
      plan_id:
        description: "The id of research/v3/plan.json the dispatch was made with"
        default: ""

permissions:
  contents: write        # claims and progress on the sweep-progress branch
  actions: read

# THE EXCHANGE (Oct 10, 2026, the move to Gate)
env:
  TA_VENUE: gate

jobs:
  deal:
    runs-on: ubuntu-latest
    outputs:
      shards: ${{ steps.mk.outputs.shards }}
    steps:
      - id: mk
        run: |
          python3 - <<'PY' >> "$GITHUB_OUTPUT"
          import json, os
          n = int(os.environ["N"])
          print("shards=" + json.dumps(list(range(n))))
          PY
        env:
          N: ${{ github.event.inputs.shards }}

  measure:
    needs: deal
    runs-on: ubuntu-latest
    timeout-minutes: 350          # runners are killed at 6h; stop before that
    strategy:
      fail-fast: false            # one bad machine must not bin the others
      matrix:
        shard: ${{ fromJson(needs.deal.outputs.shards) }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install
        run: |
          python -m pip install --upgrade pip
          # the PC's own versions: the PC and the machines must compute the
          # same averages to the last bit
          pip install "pandas==3.0.5" "numpy==2.5.2" requests

      - name: Measure shard ${{ matrix.shard }}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          SHARD: ${{ matrix.shard }}
          SHARDS: ${{ github.event.inputs.shards }}
          COIN_LIST: ${{ github.event.inputs.coin_list }}
          PLAN_ID: ${{ github.event.inputs.plan_id }}
        run: python .github/scripts/v3_shard.py

      # always(): a machine stopped at the time limit still hands over every
      # coin it finished - each record is written the moment its coin is done
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: v3-out-${{ matrix.shard }}
          path: |
            out/v3/*.json.gz
            out/v3-report-*.json
          if-no-files-found: warn
          retention-days: 30
```

- [ ] **Step 5: Run it, and the guards every workflow and script must pass.**

Run: `.venv/Scripts/python -m pytest tests/test_v3_shard.py tests/test_every_workflow_names_the_exchange.py tests/test_ci_scripts_use_names_that_exist.py -q`, then `.venv/Scripts/python -m ruff check .github/scripts/v3_shard.py tests/test_v3_shard.py`
Expected: all pass (27 in scratch, about 5 s); `All checks passed!`.

- [ ] **Step 6: Commit and push at once** (the CI runs this from `main`):

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> .github/scripts/v3_shard.py .github/workflows/v3.yml tests/test_v3_shard.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
feat(v3): the Backtest v3 machine (.github/scripts/v3_shard.py, v3.yml) - each claimed coin measured by measure_coin at the research's $5 risk, one record per coin, a failed coin redone alone and named, a machine whose plan or venue is not the dispatch's measures nothing - Part 2b, Task 2

4 inputs (shards, coin_list, label, plan_id), TA_VENUE gate, 350-minute jobs, artifacts v3-out-N. sweep_shard is imported with RES popped (it exits on "v3").

harddev: the plan id is checked before any coin; a coin's file is dropped before each try; coins outside the plan and coins the exchange no longer trades are named, never measured.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 3: Dispatch, redo, collect, retry and parity from this PC

**Files:**
- Create: `tradingagents/v3_cloud.py`
- Modify: `tradingagents/forecast_v2_daily.py:197-199` (`title_of`: v3.yml's run-name)
- Test: `tests/test_v3_cloud.py`

**Interfaces:**
- Consumes: Task 2's workflow and record shapes; `forecast_v2_daily.fleets_now() -> (ready, refused)`, `forecast_v2_daily.dispatch(workflow, inputs, repo, since=None) -> int`, `forecast_v2_daily.run_status(run, repo) -> {"status", "conclusion", ...}`, `cloud_sweep.split_coins / sync_fleet / origin_fleet`, `cq_search.quiet_hours(now)`, `pro_search.files(roots, pattern)`, `v3_research.home / plain_label / save_coin / load_coins / drop_coin / coin_file / differences`.
- Produces: `v3_cloud.home() -> Path` (`stores.V3.home/cloud`); `dispatch(name, *, coins=None, plan_path=None, label=None, folder=None, force=False, now=None) -> state`; `redo(name, repo) -> state`; `collect(name) -> summary`; `land(state, roots) -> dict`; `retry(name, *, now=None, force=False) -> state`; `load_state(name) -> dict`; `same_measure(a, b) -> list[str]`; `parity(folder, coin, local_label) -> list[str]`; `title_of(label) -> str`. A state file `cloud/<name>.json` holds `name, label, folder, started, started_at, plan_id, plan_end_ms, plan_path, plan_copy, risk_usd, runs_per_combo, coins, board, runs {repo: {run, coins, label}}, refused, dealt {repo: inputs}`; `cloud/<name>.plan.json` the plan as dispatched; `cloud/<name>-collected.json` the summary `{name, label, plan_id, runs, shares_refused, roots, folder, landed, not_reached, failed, left_out, refused_records, machines_refused, seconds {median, max, total}, bytes}`.

- [ ] **Step 1: Write the failing test** `tests/test_v3_cloud.py`:

```python
"""Backtest v3 on GitHub, started from this PC (tradingagents/v3_cloud.py,
Part 2b): every account gets its share of the plan's coins with the plan's id,
the state is saved before any dispatch, a plan that is not on origin/main is
never dispatched, a refused share is redone by itself (and a run GitHub listed
late is adopted, never doubled), the collect lands only this run's records and
names every coin it did not, a failed coin loses its old record, a folder of
another plan is never landed into, and a retry redoes only what failed."""
from __future__ import annotations

import datetime as dt
import gzip
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from tradingagents import (
    cloud_sweep as cs,
    forecast_v2_daily as fd,
    v3_cloud as vc,
    v3_research as vrs,
    v3_universe as vu,
)

ROOT = Path(__file__).resolve().parent.parent
NOON = dt.datetime(2026, 10, 28, 12, 0).timestamp()
ONE_AM = dt.datetime(2026, 10, 28, 1, 0).timestamp()
END = 1_792_800_000_000 - 1_792_800_000_000 % 86_400_000
# sorted, the board is BTC ETH PEPE SOL XAG XAU 龙虾, dealt in turn: a/x BTC SOL 龙虾, b/x ETH XAG,
# c/x PEPE XAU
COINS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XAU_USDT", "XAG_USDT", "PEPE_USDT", "龙虾_USDT"]


def _plan(tmp):
    plan = {"version": vu.VERSION, "venue": "Gate", "start_ms": END - 365 * 86_400_000,
            "end_ms": END, "coins": sorted(COINS), "months": [], "liquid": {}, "calm": {}}
    plan["id"] = vu.plan_id(plan)
    return vu.save(plan, tmp / "plan.json"), plan


@pytest.fixture()
def fleet(monkeypatch, tmp_path):
    """Three accounts, a/x the origin. `.fail` names the accounts whose dispatch GitHub refuses;
    `.started` holds (repo, inputs, since) of every start."""
    ns = SimpleNamespace(started=[], fail=set(), tmp=tmp_path)

    def start(repo, inputs, since=None):
        assert vc._state_path("pilot").exists() or vc._state_path("pilot-redo1").exists(), \
            "the state is saved before the dispatch"
        if repo in ns.fail:
            raise RuntimeError("could not create workflow dispatch event: HTTP 502")
        ns.started.append((repo, dict(inputs), since))
        return 1000 + len(ns.started)

    monkeypatch.setattr(vc, "home", lambda: (tmp_path / "cloud").mkdir(exist_ok=True)
                        or tmp_path / "cloud")
    monkeypatch.setattr(vrs, "home", lambda label="local": tmp_path / "research"
                        / vrs.plain_label(label))
    monkeypatch.setattr(vc, "_start", start)
    monkeypatch.setattr(vc, "_git", lambda *a: "same-blob")
    monkeypatch.setattr(fd, "fleets_now", lambda: (["a/x", "b/x", "c/x"], []))
    monkeypatch.setattr(cs, "origin_fleet", lambda: "a/x")
    monkeypatch.setattr(cs, "sync_fleet", lambda repo: "")
    ns.path, ns.plan = _plan(tmp_path)
    return ns


def test_every_account_gets_its_share_of_the_plans_coins_with_the_plans_id(fleet):
    started, path, plan = fleet.started, fleet.path, fleet.plan
    st = vc.dispatch("pilot", plan_path=path, now=NOON)
    assert [r for r, _i, _s in started] == ["a/x", "b/x", "c/x"]
    dealt = sorted(c for _r, i, _s in started for c in i["coin_list"].split(","))
    assert dealt == sorted(COINS), "every coin of the plan, once"
    for _repo, inputs, _since in started:
        assert inputs["plan_id"] == plan["id"]
        assert inputs["shards"] == str(len(inputs["coin_list"].split(",")))   # under 20: one each
        assert inputs["label"].startswith("pilot · ")
    assert st["plan_id"] == plan["id"] and st["risk_usd"] == 5.0 and st["runs_per_combo"] == 200
    assert st["folder"] == "pilot" and set(st["runs"]) == {"a/x", "b/x", "c/x"}
    saved = vc.load_state("pilot")
    assert saved["runs"]["b/x"]["run"] == 1002 and not saved["refused"]
    # the plan as dispatched is kept beside the state: the run is judged under it
    assert vu.load(saved["plan_copy"])["id"] == plan["id"]


def test_a_plan_that_is_not_on_origin_main_is_never_dispatched(fleet, monkeypatch):
    started, path = fleet.started, fleet.path
    monkeypatch.setattr(vc, "_git", lambda *a: "local-blob" if a[0] == "hash-object"
                        else "main-blob")
    with pytest.raises(RuntimeError, match="is not the plan on origin/main"):
        vc.dispatch("pilot", plan_path=path, now=NOON)
    assert started == []


def test_a_coin_outside_the_plan_is_refused_by_name_and_the_night_refuses_a_dispatch(fleet):
    started, path = fleet.started, fleet.path
    with pytest.raises(ValueError, match="not in the plan's universe: DOGE_USDT"):
        vc.dispatch("pilot", coins=["BTC", "DOGE"], plan_path=path, now=NOON)
    with pytest.raises(RuntimeError, match="12:45am and 5:00am"):
        vc.dispatch("pilot", plan_path=path, now=ONE_AM)
    assert started == []
    vc.dispatch("pilot", coins=["BTC", "XAU_USDT"], plan_path=path, now=ONE_AM, force=True)
    assert sorted(c for _r, i, _s in started for c in i["coin_list"].split(",")) == \
        ["BTC_USDT", "XAU_USDT"]


def test_a_refused_share_is_redone_by_itself_and_a_late_listed_run_is_adopted(fleet,
                                                                              monkeypatch):
    started, path = fleet.started, fleet.path
    fleet.fail = {"b/x"}
    st = vc.dispatch("pilot", plan_path=path, now=NOON)
    assert set(st["runs"]) == {"a/x", "c/x"} and st["refused"][0].startswith("b/x:")
    share = st["dealt"]["b/x"]
    started.clear()
    fleet.fail = set()
    got = vc.redo("pilot", "b/x")
    # the share it was dealt, asked with `since`: a run GitHub took and listed late is adopted
    assert started == [("b/x", share, NOON)] and got["runs"]["b/x"]["run"] == 1001
    assert got["refused"] == []
    with pytest.raises(ValueError, match="already has run"):
        vc.redo("pilot", "b/x")


def test_the_dispatcher_adopts_a_run_github_listed_late_never_starting_a_second(monkeypatch):
    # the real start path (forecast_v2_daily.dispatch) with a run of this title made after `since`
    inputs = {"label": "pilot · 2 of 3", "coin_list": "ETH_USDT", "shards": "1", "plan_id": "p"}
    title = vc.title_of(inputs["label"])
    made = dt.datetime.fromtimestamp(NOON + 30, dt.timezone.utc).isoformat()
    monkeypatch.setattr(fd, "_runs", lambda wf, repo, limit=20: [
        {"databaseId": 777, "displayTitle": title, "createdAt": made}])

    def no_new_run(*a, **k):
        raise AssertionError(f"a second run was started: {a}")

    monkeypatch.setattr(fd, "_gh", no_new_run)
    assert vc._start("b/x", inputs, since=NOON) == 777


def test_the_run_is_found_by_the_title_the_workflow_gives_it():
    text = (ROOT / ".github" / "workflows" / "v3.yml").read_text(encoding="utf-8")
    shown = re.search(r'run-name: "(.*)"', text).group(1).replace("${{ inputs.label }}", "L")
    assert fd.title_of(vc.WORKFLOW, {"label": "L"}) == vc.title_of("L") == shown


# ---- the collect ------------------------------------------------------------------------------

def _rec(coin, plan, **over):
    return {"version": 2, "coin": coin, "kind": "crypto", "plan_id": plan["id"],
            "plan_end_ms": plan["end_ms"], "risk_usd": 5.0, "runs": 200, "combos": {"x": {}},
            "windows": {"1d": {}}, "skipped": {}, "machine": {"repo": "a/x"}, **over}


def _artifact(root: Path, shard: int, recs: list, report: list, refused: str = ""):
    """One machine's artifact as `gh run download` unpacks it."""
    d = root / f"v3-out-{shard}"
    for r in recs:
        p = vrs.coin_file(d / "v3", r["coin"])
        p.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(p, "wt", encoding="utf-8") as fh:
            json.dump(r, fh)
    d.mkdir(parents=True, exist_ok=True)
    head = {"shard": shard, "machine": {"repo": "c/x"}, "report": report}
    if refused:
        head["refused"] = refused
    (d / f"v3-report-{shard}.json").write_text(json.dumps(head), encoding="utf-8")


def _collected(fleet, monkeypatch, fill):
    path, plan, tmp = fleet.path, fleet.plan, fleet.tmp
    fleet.fail = {"c/x"}                  # the third account's share never starts
    st = vc.dispatch("pilot", plan_path=path, now=NOON)
    roots = {}
    for repo, r in st["runs"].items():
        roots[repo] = tmp / f"art-{r['run']}"
        roots[repo].mkdir()
    fill(st, roots, plan)
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed"})
    monkeypatch.setattr(vc, "download", lambda run, repo: roots[repo])
    return st, vc.collect("pilot"), plan, tmp


def test_the_collect_lands_this_runs_records_and_names_every_coin_it_did_not(fleet,
                                                                            monkeypatch):
    def fill(st, roots, plan):
        a = st["dealt"]["a/x"]["coin_list"].split(",")       # BTC, SOL, 龙虾 (dealt in turn)
        b = st["dealt"]["b/x"]["coin_list"].split(",")       # ETH, XAG
        _artifact(roots["a/x"], 0, [_rec(a[0], plan), _rec(a[2], plan)],
                  [{"coin": a[0], "seconds": 150.0, "bytes": 80_000, "combos": 1},
                   {"coin": a[1], "error": "ConnectionError: cut", "tries": 3},
                   {"coin": a[2], "seconds": 190.0, "bytes": 90_000, "combos": 1}])
        _artifact(roots["b/x"], 0, [_rec(b[0], plan, risk_usd=1.0)],
                  [{"coin": b[0], "seconds": 100.0, "bytes": 70_000, "combos": 1},
                   {"coin": b[1], "why": "the exchange is not trading it now"}])
        _artifact(roots["b/x"], 1, [], [], refused="TA_VENUE is 'mexc': Backtest v3 measures "
                                                   "on Gate only")

    st, got, _plan_, _tmp = _collected(fleet, monkeypatch, fill)
    a = st["dealt"]["a/x"]["coin_list"].split(",")
    b = st["dealt"]["b/x"]["coin_list"].split(",")
    c = st["dealt"]["c/x"]["coin_list"].split(",")
    assert got["landed"] == sorted([a[0], a[2]])
    assert got["failed"] == [f"{a[1]}: ConnectionError: cut"]
    assert got["left_out"] == [f"{b[1]}: the exchange is not trading it now"]
    assert got["refused_records"] == [f"{b[0]}: risk $1.00, not $5.00"]
    assert got["machines_refused"] == ["c/x shard 1: TA_VENUE is 'mexc': Backtest v3 measures "
                                       "on Gate only"]
    # the share GitHub refused, and the record refused at landing, are coins not reached
    assert got["not_reached"] == sorted(c + [b[0]])
    assert got["seconds"] == {"median": 150.0, "max": 190.0, "total": 440.0}
    held = {r["coin"] for r in vrs.load_coins(vrs.home("pilot"))}
    assert held == {a[0], a[2]}, "a Chinese-named coin lands under its ASCII file name"


def test_a_coin_that_failed_this_time_loses_its_old_record(fleet, monkeypatch):
    plan = fleet.plan
    vrs.save_coin(vrs.home("pilot"), _rec("SOL_USDT", plan))

    def fill(st, roots, plan_):
        _artifact(roots["a/x"], 0, [], [{"coin": "SOL_USDT", "error": "ValueError: x",
                                         "tries": 3}])
        _artifact(roots["b/x"], 0, [], [])

    _st, got, _p, _t = _collected(fleet, monkeypatch, fill)
    assert got["failed"] == ["SOL_USDT: ValueError: x"]
    assert not vrs.coin_file(vrs.home("pilot"), "SOL_USDT").exists()


def test_a_folder_holding_another_plans_records_is_never_landed_into(fleet, monkeypatch):
    plan = fleet.plan
    vrs.save_coin(vrs.home("pilot"), _rec("BTC_USDT", plan, plan_id="0123456789abcdef"))

    def fill(st, roots, plan_):
        _artifact(roots["a/x"], 0, [_rec("SOL_USDT", plan_)], [])
        _artifact(roots["b/x"], 0, [], [])

    with pytest.raises(RuntimeError, match="holds records of another plan"):
        _collected(fleet, monkeypatch, fill)
    assert not vrs.coin_file(vrs.home("pilot"), "SOL_USDT").exists()


def test_retry_redoes_only_the_failed_and_unreached_coins_into_the_same_folder(fleet,
                                                                               monkeypatch):
    def fill(st, roots, plan):
        a = st["dealt"]["a/x"]["coin_list"].split(",")
        _artifact(roots["a/x"], 0, [_rec(a[0], plan), _rec(a[2], plan)],
                  [{"coin": a[1], "error": "ConnectionError: cut", "tries": 3}])
        _artifact(roots["b/x"], 0, [], [{"coin": c, "why": "the exchange is not trading it now"}
                                        for c in st["dealt"]["b/x"]["coin_list"].split(",")])

    started = fleet.started
    st, got, _p, _t = _collected(fleet, monkeypatch, fill)
    started.clear()
    fleet.fail = set()
    again = vc.retry("pilot", now=NOON)
    assert again["name"] == "pilot-redo1" and again["folder"] == "pilot"
    redone = sorted(c for _r, i, _s in started for c in i["coin_list"].split(","))
    # the failed coin and the refused share's coins; never the left-out or the landed ones
    want = sorted([st["dealt"]["a/x"]["coin_list"].split(",")[1]]
                  + st["dealt"]["c/x"]["coin_list"].split(","))
    assert redone == want == sorted(got["not_reached"] + [x.split(": ")[0] for x in got["failed"]])


def test_parity_ignores_when_and_where_and_names_what_differs():
    a = {"coin": "XAU_USDT", "pre": {"seconds": 20.1, "flat_slip": 0.0002},
         "windows": {"1h": {"seconds": 40.0, "older_candles": 6600}},
         "combos": {"k": {"older": {"rows": [[1, 2, 3, 1, 0.5, "TP", 0.007, 0.0067]]}}},
         "machine": {"repo": "a/x"}}
    b = json.loads(json.dumps(a))
    b["pre"]["seconds"], b["windows"]["1h"]["seconds"], b["machine"] = 31.0, 55.5, {"repo": "pc"}
    assert vc.same_measure(a, b) == []
    b["combos"]["k"]["older"]["rows"][0][4] = 0.51
    assert vc.same_measure(a, b) == ["combos.k.older.rows[0][4]"]
```

- [ ] **Step 2: Run it to see it fail.**

Run: `.venv/Scripts/python -m pytest tests/test_v3_cloud.py -q`
Expected: `ImportError: cannot import name 'v3_cloud' from 'tradingagents'`.

- [ ] **Step 3: Teach the dispatcher v3.yml's title.** In `tradingagents/forecast_v2_daily.py`, `title_of`, before the `research.yml` branch, add:

```python
    if workflow == "v3.yml":             # its run-name (Backtest v3 Part 2b, Oct 27, 2026)
        return f"Backtest v3 research · {inputs['label']}"
```

- [ ] **Step 4: Write** `tradingagents/v3_cloud.py`:

```python
"""BACKTEST V3 ON GITHUB (Part 2b, Oct 27, 2026), started from this PC.

The machines run .github/workflows/v3.yml (.github/scripts/v3_shard.py); this
module deals the plan's coins between EVERY GitHub account that can run now
(cloud_sweep.split_coins over forecast_v2_daily.fleets_now - three accounts,
60 machines, CLAUDE.md "Every GitHub job uses ALL ... machines"), starts one
run on each, and brings every machine's records home into the v3 store on the
store's drive (`stores.V3.home`, never the system drive), where
`python -m tradingagents.v3_verdicts publish <folder>` judges them pooled.
Plan: docs/superpowers/plans/2026-10-27-backtest-v3-part2b-github.md.

    python -m tradingagents.v3_cloud dispatch <name> [--coins A,B] [--plan FILE] [--force]
    python -m tradingagents.v3_cloud redo <name> <owner/repo>
    python -m tradingagents.v3_cloud collect <name>
    python -m tradingagents.v3_cloud retry <name>
    python -m tradingagents.v3_cloud progress
    python -m tradingagents.v3_cloud parity <folder> <coin> <local-label>

`<name>` is one plain folder name ("pilot", "universe"): the run's state file
(`<name>.json` beside this module's home) and the folder its records land in
(`stores.V3.home/research/<name>`, `v3_research.home`).

* A run is dispatched only with a plan that is COMMITTED and on origin/main
  (every machine reads the plan from its own checkout) and its id travels as
  the workflow's `plan_id`: a machine holding any other plan refuses.
* The state is saved BEFORE the first dispatch and after each one, so a
  dispatch that raised can be found again (`redo` adopts a run GitHub listed
  late, `forecast_v2_daily.dispatch(since=)`), never started twice.
* `collect` lands only records measured under the run's own plan build, risk
  and random-run count, and refuses to land into a folder holding another
  plan's records; every coin it did not land is NAMED: not reached (a share
  GitHub refused), failed (with its error), left out by the machine (with
  why), or refused at landing (with what differs).
* `retry` redoes only the coins a collected run failed or never reached, into
  the SAME folder (CLAUDE.md: a failed coin is redone alone).

Never dispatched between 12:45am and 5:00am (this PC's clock: the nightly
room re-test and backtest update need every machine; `cq_search.quiet_hours`);
`--force` is for a person who knows they are not running.
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
import time
from pathlib import Path

WORKFLOW = "v3.yml"
SHARDS = 20                         # machines per account (MACHINES_PER_ACCOUNT)
ARTIFACTS = ("v3-out-*",)
PLAN_REL = "research/v3/plan.json"
# a record's fields that say WHEN and WHERE it was measured, never WHAT: `parity` ignores them
TIMING = ("seconds", "machine")


def home() -> Path:
    """Beside the v3 store, on the store's drive."""
    from tradingagents import stores

    p = Path(stores.V3.home) / "cloud"
    p.mkdir(parents=True, exist_ok=True)
    return p


def title_of(label: str) -> str:
    """The run-name v3.yml gives a dispatch - how its run is found."""
    return f"Backtest v3 research · {label}"


def _git(*args: str) -> str:
    from tradingagents.v3_universe import PLAN_FILE

    out = subprocess.run(["git", *args], cwd=str(PLAN_FILE.parent.parent.parent),
                         capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {(out.stderr or out.stdout).strip()[:200]}")
    return out.stdout.strip()


def plan_on_main(path: Path) -> str:
    """"" when the plan file at `path` is the one committed on origin/main (what
    every machine's checkout reads); else why not."""
    try:
        here = _git("hash-object", str(path))
        main = _git("rev-parse", f"origin/main:{PLAN_REL}")
    except RuntimeError as exc:
        return f"the committed plan could not be read: {exc}"
    if here != main:
        return (f"{path} is not the plan on origin/main: rebuild it, commit it and push it to "
                "every account first (every machine reads the plan from its own checkout)")
    return ""


def _state_path(name: str) -> Path:
    from tradingagents import v3_research as vrs

    return home() / f"{vrs.plain_label(name)}.json"


def _save(name: str, state: dict) -> None:
    p = _state_path(name)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(p)


def load_state(name: str) -> dict:
    return json.loads(_state_path(name).read_text(encoding="utf-8"))


def progress(stage: str, **extra) -> dict:
    """home()/progress.json, merged and swapped whole: where the v3 research
    stands, with a dated log line. An unreadable file is kept aside, never
    overwritten."""
    from tradingagents.positions_view import fmt_when

    p = home() / "progress.json"
    cur: dict = {"log": []}
    if p.exists():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            p.replace(p.with_name(f"progress.unreadable-{int(time.time())}.json"))
    now = time.time()
    cur["stage"] = stage
    cur.setdefault("log", []).append(f"{fmt_when(now)} {stage}")
    cur.update(extra)
    cur["updated"] = fmt_when(now)
    tmp = p.with_name("progress.tmp")
    tmp.write_text(json.dumps(cur, indent=1, default=str), encoding="utf-8")
    tmp.replace(p)
    return cur


def _start(repo: str, inputs: dict, since: float | None = None) -> int:
    """Start v3.yml on `repo` and return ITS run id, found by its title; with
    `since`, a run of that title GitHub listed late is adopted instead."""
    from tradingagents import forecast_v2_daily as fd

    return fd.dispatch(WORKFLOW, inputs, repo, since=since)


def dispatch(name: str, *, coins: list | None = None, plan_path: Path | str | None = None,
             label: str | None = None, folder: str | None = None, force: bool = False,
             now: float | None = None) -> dict:
    """Deal the plan's coins (or `coins`, every one of them in the plan) between
    every account that can run now and start one run on each. An account that
    refuses, or cannot be brought up to this code, is NAMED and the others still
    run; its share is kept for `redo`."""
    from tradingagents import (
        cloud_sweep as cs,
        cq_search,
        forecast_v2_daily as fd,
        v3_random as vrn,
        v3_research as vrs,
        v3_rules as vr,
        v3_universe as vu,
    )
    from tradingagents.positions_view import fmt_when

    vrs.plain_label(name)
    folder = vrs.plain_label(folder or name)
    if cq_search.quiet_hours(now) and not force:
        raise RuntimeError("not dispatched: between 12:45am and 5:00am the nightly room "
                           "re-test and backtest update need every machine")
    path = Path(plan_path or vu.PLAN_FILE)
    plan = vu.load(path)
    why = plan_on_main(path)
    if why:
        raise RuntimeError(f"not dispatched: {why}")
    if coins:
        board = sorted({c if c.endswith("_USDT") else f"{c}_USDT" for c in coins})
        outside = [c for c in board if c not in set(plan["coins"])]
        if outside:
            raise ValueError(f"not in the plan's universe: {', '.join(outside)}")
    else:
        board = list(plan["coins"])
    ready, refused = fd.fleets_now()
    if not ready:
        raise RuntimeError("no GitHub account can run the research: " + "; ".join(refused))
    piles = cs.split_coins(board, len(ready))
    t0 = time.time() if now is None else float(now)
    label = label or name
    state = {"name": name, "label": label, "folder": folder, "started": t0,
             "started_at": fmt_when(t0), "plan_id": plan["id"], "plan_end_ms": int(plan["end_ms"]),
             "plan_path": str(path), "risk_usd": vr.RESEARCH_RISK_USD, "runs_per_combo": vrn.RUNS,
             "coins": len(board), "board": board, "runs": {}, "refused": list(refused),
             "dealt": {}}
    for k, (repo, pile) in enumerate(zip(ready, piles, strict=False)):
        state["dealt"][repo] = {"shards": str(min(SHARDS, len(pile))),
                                "coin_list": ",".join(pile),
                                "label": f"{label} · {k + 1} of {len(ready)}",
                                "plan_id": plan["id"]}
    # the plan as dispatched, kept beside the state: research/v3/plan.json may be rebuilt before
    # this run is judged, and its records are judged under THEIR plan (v3_verdicts)
    copy = home() / f"{name}.plan.json"
    shutil.copyfile(path, copy)
    state["plan_copy"] = str(copy)
    _save(name, state)                 # BEFORE any dispatch: a lost save never starts a run twice
    origin = cs.origin_fleet()
    for repo, inputs in state["dealt"].items():
        if repo != origin:
            drift = cs.sync_fleet(repo)
            if drift:
                state["refused"].append(f"{repo}: not brought up to this code ({drift})")
                _save(name, state)
                continue
        try:
            run = _start(repo, inputs)
        except Exception as exc:                               # noqa: BLE001
            state["refused"].append(f"{repo}: {str(exc)[:160]}")
        else:
            state["runs"][repo] = {"run": run, "coins": len(inputs["coin_list"].split(",")),
                                   "label": inputs["label"]}
        _save(name, state)
    progress(f"dispatched {name}: {len(state['runs'])} run(s), {len(board)} coin(s), plan "
             f"{plan['id']}" + (f"; refused: {'; '.join(state['refused'])}"
                                if state["refused"] else ""))
    return state


def redo(name: str, repo: str) -> dict:
    """Start ONE account's share again by itself - the account GitHub refused,
    never the whole run. A share with a run already is refused by name (two
    runs would measure its coins twice); a run GitHub listed late is adopted."""
    from tradingagents import cloud_sweep as cs

    state = load_state(name)
    if repo in state["runs"]:
        raise ValueError(f"{repo} already has run {state['runs'][repo]['run']} in {name}")
    inputs = state["dealt"].get(repo)
    if not inputs:
        raise ValueError(f"{name} dealt no share to {repo}")
    if repo != cs.origin_fleet():
        drift = cs.sync_fleet(repo)
        if drift:
            raise RuntimeError(f"{repo}: not brought up to this code ({drift})")
    run = _start(repo, inputs, since=float(state["started"]))
    state["runs"][repo] = {"run": run, "coins": len(inputs["coin_list"].split(",")),
                           "label": inputs["label"]}
    state["refused"] = [x for x in state["refused"] if not x.startswith(repo + ":")]
    _save(name, state)
    return state


def download(run: int, repo: str) -> Path:
    """One run's artifacts, unpacked in THIS RUN'S OWN folder under home() -
    the store's drive - emptied first."""
    root = home() / f"run-{int(run)}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    cmd = ["gh", "run", "download", str(int(run)), "-R", repo, "-D", str(root)]
    for p in ARTIFACTS:
        cmd += ["-p", p]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=3600)
    return root


def _reports(roots) -> tuple[list, list]:
    """(every machine's report entries, the machines that refused to measure,
    each "account shard N: why")."""
    from tradingagents import pro_search as ps

    entries, refused = [], []
    for f in ps.files(roots, "v3-report-*.json"):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        entries += d.get("report") or []
        if d.get("refused"):
            m = d.get("machine") or {}
            refused.append(f"{m.get('repo') or '?'} shard {d.get('shard')}: {d['refused']}")
    return entries, refused


def _held(root: Path) -> list:
    """The records already in a landing folder: [(coin, plan_id, risk, runs)]."""
    from tradingagents import v3_research as vrs

    return [(r.get("coin"), r.get("plan_id"), r.get("risk_usd"), r.get("runs"))
            for r in vrs.load_coins(root)]


def land(state: dict, roots) -> dict:
    """Every machine's records of a finished run into its folder in the v3
    store, and what was not landed, NAMED (see the module doc)."""
    from tradingagents import pro_search as ps, v3_research as vrs

    root = vrs.home(state["folder"])
    want = (state["plan_id"], float(state["risk_usd"]), int(state["runs_per_combo"]))
    other = [f"{c} (plan {p}, risk {r}, {n} runs)" for c, p, r, n in _held(root)
             if (p, float(r or 0), int(n or 0)) != want]
    if other:
        raise RuntimeError(f"not landed: {root} holds records of another plan, risk or run count "
                           f"({', '.join(other[:5])}{' ...' if len(other) > 5 else ''}); collect "
                           "into a new name")
    plan = {"id": state["plan_id"], "end_ms": int(state["plan_end_ms"])}
    entries, machines_refused = _reports(roots)
    board = set(state["board"])
    failed = {e["coin"]: e["error"] for e in entries if e.get("error")}
    # a coin the machine never measured says why (its report entry has no record size); a coin
    # measured into "no family's universe" has a record, which is landed like any other
    left = {e["coin"]: e["why"] for e in entries if e.get("why") and "bytes" not in e}
    for coin in failed:
        vrs.drop_coin(root, coin)          # DELETE first: never an old record beside a failure
    landed, refused, seen = [], [], set()
    for f in ps.files(roots, "*.json.gz"):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            rec = json.load(fh)
        coin = rec.get("coin")
        why = vrs.differences(rec, plan, want[2], want[1])
        if coin not in board:
            why = ["not on this run's board", *why]
        if coin in seen:
            why = ["measured twice: the first record is kept", *why]
        if why:
            refused.append(f"{coin}: {'; '.join(why)}")
            continue
        seen.add(coin)
        failed.pop(coin, None)             # a coin that failed once and was redone on a machine
        vrs.save_coin(root, rec)
        landed.append(coin)
    reached = set(landed) | set(failed) | set(left)
    secs = sorted(float(e["seconds"]) for e in entries if e.get("seconds") is not None)
    size = sum(int(e.get("bytes") or 0) for e in entries)
    return {"folder": str(root), "landed": sorted(landed),
            "not_reached": sorted(board - reached),
            "failed": [f"{c}: {e}" for c, e in sorted(failed.items())],
            "left_out": [f"{c}: {w}" for c, w in sorted(left.items())],
            "refused_records": refused, "machines_refused": machines_refused,
            "seconds": ({"median": secs[len(secs) // 2], "max": secs[-1],
                         "total": round(sum(secs), 1)} if secs else None),
            "bytes": size}


def collect(name: str) -> dict:
    """Bring a finished run home from every account and land it (see `land`)."""
    from tradingagents import forecast_v2_daily as fd

    state = load_state(name)
    unfinished = []
    for repo, r in state["runs"].items():
        st = fd.run_status(int(r["run"]), repo)
        if st.get("status") != "completed":
            unfinished.append(f"{repo} run {r['run']} is {st.get('status')}")
    if unfinished:
        raise RuntimeError("not collected, still running: " + "; ".join(unfinished))
    roots = [download(int(r["run"]), repo) for repo, r in state["runs"].items()]
    got = land(state, roots)
    summary = {"name": name, "label": state["label"], "plan_id": state["plan_id"],
               "runs": {k: v["run"] for k, v in state["runs"].items()},
               "shares_refused": list(state["refused"]), "roots": [str(r) for r in roots],
               **got}
    (home() / f"{name}-collected.json").write_text(json.dumps(summary, indent=1),
                                                   encoding="utf-8")
    progress(f"collected {name}: {len(got['landed'])} of {state['coins']} coin(s) landed in "
             f"{got['folder']}; {len(got['not_reached'])} not reached, {len(got['failed'])} "
             f"failed, {len(got['left_out'])} left out, {len(got['refused_records'])} refused "
             f"(each named in {name}-collected.json)")
    return summary


def retry(name: str, *, now: float | None = None, force: bool = False) -> dict:
    """Redo ONLY the coins a collected run failed or never reached, as a new run
    whose records land in the SAME folder (`<name>-redo<N>`), under the plan
    the run was dispatched with."""
    state = load_state(name)
    summary = json.loads((home() / f"{name}-collected.json").read_text(encoding="utf-8"))
    coins = summary["not_reached"] + [x.split(": ", 1)[0] for x in summary["failed"]]
    if not coins:
        raise ValueError(f"{name}: every coin landed or was left out with why; nothing to redo")
    n = 1
    while _state_path(f"{name}-redo{n}").exists():
        n += 1
    # the plan the run was dispatched with: once research/v3/plan.json is rebuilt no redo can
    # measure under it any more, and `plan_on_main` refuses by name
    return dispatch(f"{name}-redo{n}", coins=coins, plan_path=state["plan_copy"],
                    label=f"{state['label']} redo {n}", folder=state["folder"], force=force,
                    now=now)


def same_measure(a: dict, b: dict, path: str = "") -> list[str]:
    """Where two records of one coin differ in WHAT they measured - every field
    but those that say when and where (`TIMING`): [] when they agree, else the
    paths that differ. A GitHub record and this PC's of one coin under one plan
    must agree (the pilot's parity check)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k in TIMING:
                continue
            out += same_measure(a.get(k), b.get(k), f"{path}.{k}" if path else str(k))
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            out += same_measure(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [path or "(the record)"]


def parity(folder: str, coin: str, local_label: str) -> list[str]:
    """`same_measure` of the coin's record collected into `folder` and the one
    `python -m tradingagents.v3_research run <coin> --label <local_label>`
    wrote on this PC."""
    from tradingagents import v3_research as vrs

    def one(label):
        with gzip.open(vrs.coin_file(vrs.home(label), coin), "rt", encoding="utf-8") as fh:
            return json.load(fh)

    return same_measure(one(folder), one(local_label))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_cloud",
                                description="Backtest v3 on every GitHub account.")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dispatch")
    d.add_argument("name")
    d.add_argument("--coins", default="")
    d.add_argument("--plan", default=None)
    d.add_argument("--force", action="store_true")
    r = sub.add_parser("redo")
    r.add_argument("name")
    r.add_argument("repo")
    sub.add_parser("collect").add_argument("name")
    t = sub.add_parser("retry")
    t.add_argument("name")
    t.add_argument("--force", action="store_true")
    sub.add_parser("progress")
    q = sub.add_parser("parity")
    q.add_argument("folder")
    q.add_argument("coin")
    q.add_argument("local_label")
    a = p.parse_args(argv)
    if a.cmd == "dispatch":
        got = dispatch(a.name, coins=[c for c in a.coins.split(",") if c] or None,
                       plan_path=a.plan, force=a.force)
    elif a.cmd == "redo":
        got = redo(a.name, a.repo)
    elif a.cmd == "collect":
        got = collect(a.name)
    elif a.cmd == "retry":
        got = retry(a.name, force=a.force)
    elif a.cmd == "parity":
        diff = parity(a.folder, a.coin.upper(), a.local_label)
        print("the same measurement" if not diff else "differs at: " + ", ".join(diff[:20]))
        return 1 if diff else 0
    else:
        print((home() / "progress.json").read_text(encoding="utf-8"))
        return 0
    print(json.dumps(got, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run it, and every test of the dispatchers it shares.**

Run: `.venv/Scripts/python -m pytest tests/test_v3_cloud.py tests/test_cq_search.py tests/test_forecast_v2.py tests/test_costs_daily.py tests/test_forty_machines_across_two_accounts.py -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_cloud.py tests/test_v3_cloud.py`
Expected: all pass (`test_v3_cloud.py` 11 in scratch); `All checks passed!` (`forecast_v2_daily.py` carries an import-order finding from before this plan, I001 at line 38: leave it, it is not this task's).

- [ ] **Step 6: Commit and push.**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_cloud.py tradingagents/forecast_v2_daily.py tests/test_v3_cloud.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
feat(v3): python -m tradingagents.v3_cloud - deal the plan's coins between every account (60 machines), redo a refused share alone (a late-listed run adopted), collect every account's records into the v3 store on G: and name every coin not landed, retry only the failed and unreached coins, parity of a GitHub record and this PC's - Part 2b, Task 3

A run is dispatched only with the plan on origin/main and carries its id; the plan as dispatched is kept beside the state; the state is saved before the first dispatch; a folder holding another plan's records is never landed into; a coin that failed loses its old record first.

harddev: three accounts in fleets_now order, the origin never synced; status read per run before any download; records at another risk, run count or plan refused with what differs.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 4: The verdict store, and the tab's tested-ideas list

**Files:**
- Create: `tradingagents/v3_verdicts.py`
- Modify: `tradingagents/v3_page.py` (imports; replace `tested`, `CHECK_OLD`, `check`, `check_row` with the block below, up to `def options`)
- Modify: `webapp/src/components/backtest-v3/V3Check.tsx`, `webapp/src/components/backtest-v3/V3Runner.tsx`
- Test: `tests/test_v3_verdicts.py`

**Interfaces:**
- Consumes: Task 3's `v3_cloud.load_state / home` and the collected summary; `v3_research.split_records / report / load_coins / home / exit_words`; `v3_proof.TRIED / Z`; `v3_measure.windows / UNSEEN_DAYS`.
- Produces: `v3_verdicts.store_path() -> Path` (`stores.V3.home/verdicts.json`), `history_dir() -> Path` (`stores.V3.home/verdicts`), `levels(records, v) -> {"stop", "target", "trades"}`, `build(name, *, now=None) -> dict`, `publish(name, *, now=None) -> Path`. The store: `{version, name, folder, label, venue, plan_id, plan_start, plan_split, plan_end (ms), risk_usd, runs, tried, z, judged_at (s), github_runs, coins, plan_coins, unseen_months, not_judged {not_reached, failed, left_out, refused_records, machines_refused, other_records, not_dispatched}, lines, verdicts [v3_proof verdict + "levels"]}`. `v3_page.tested(store_file=None, check_file=None) -> {"state": "not_run" | "unreadable" | "stored", "rows", "store": store_view | None, "words", "check"}`; `v3_page.store_view(data)`, `stored_words(view)`, `level_words(lv, which)`; `check_row` gains `per_day, target, stop, target_pct, stop_pct, lev`.

- [ ] **Step 1: Write the failing test** `tests/test_v3_verdicts.py`:

```python
"""The Backtest v3 verdict store (tradingagents/v3_verdicts.py, Part 2b) and
the tab's tested-ideas list that reads it (`v3_page.tested`): a collected run
judged pooled under the plan it was DISPATCHED with, every verdict kept with
what it was judged under and every coin it did not judge named, each verdict's
stop and target sizes read from its trade rows, and the tab saying - from the
store's own numbers - when it is a pilot and not the proof."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tests.test_v3_proof as tp
from tradingagents import (
    v3_cloud as vc,
    v3_page as vpg,
    v3_proof as vp,
    v3_research as vrs,
    v3_universe as vu,
    v3_verdicts as vv,
)

DAY = 86_400_000


def _plan(coins, end=tp.PLAN_END):
    plan = {"version": vu.VERSION, "venue": "Gate", "start_ms": end - 365 * DAY, "end_ms": end,
            "coins": sorted(coins), "months": [], "liquid": {}, "calm": {}}
    plan["id"] = vu.plan_id(plan)
    return plan


def _eight(rows, stop=0.007, target=0.0067):
    return [r + [stop, target] for r in rows]


def _record(coin, plan, unseen, risk=5.0):
    """A coin's record of the snap family on 1h with no filter: k1.5 +0.05 a trade on the
    older days, k2 +0.10 (k2 is chosen), `unseen` k2's unseen trades, the random runs quiet."""
    walk = tp._walk
    return {"version": 2, "coin": coin, "kind": "metals", "plan_id": plan["id"],
            "plan_end_ms": plan["end_ms"], "risk_usd": risk, "runs": 200,
            "unseen_months": ["2026-07", "2026-08", "2026-09", "2026-10"],
            "windows": {"1h": {"split": "Jul 25, 2026", "end": "Oct 23, 2026",
                               "older_candles": 6600, "unseen_candles": 2160}},
            "combos": {tp.KEY15: {"older": walk(_eight(tp._rows([0.05] * 40))),
                                  "unseen": walk([]), "random": [[0, 0.0]] * 200},
                       tp.KEY: {"older": walk(_eight(tp._rows([0.10] * 40))),
                                "unseen": walk(unseen), "random": tp.QUIET}},
            "skipped": {}, "machine": {"repo": "a/x"}}


@pytest.fixture()
def run(monkeypatch, tmp_path):
    return make_run(monkeypatch, tmp_path)


def make_run(monkeypatch, tmp_path):
    """A collected run "pilot" of 2 of the plan's 4 coins, its plan kept beside the state
    (tests/test_v3_results_page.py builds its page from this run too)."""
    monkeypatch.setattr(vc, "home", lambda: tmp_path / "cloud")
    monkeypatch.setattr(vrs, "home", lambda label="local": tmp_path / "research"
                        / vrs.plain_label(label))
    monkeypatch.setattr(vv, "store_path", lambda: tmp_path / "v3" / "verdicts.json")
    monkeypatch.setattr(vv, "history_dir", lambda: tmp_path / "v3" / "verdicts")
    (tmp_path / "cloud").mkdir()
    plan = _plan(["XAU_USDT", "XAG_USDT", "XPT_USDT", "EURUSD_USDT"])
    copy = vu.save(plan, tmp_path / "cloud" / "pilot.plan.json")
    state = {"name": "pilot", "label": "pilot", "folder": "pilot", "plan_id": plan["id"],
             "plan_copy": str(copy), "risk_usd": 5.0, "runs_per_combo": 200,
             "board": ["XAU_USDT", "XAG_USDT", "XPT_USDT"]}
    (tmp_path / "cloud" / "pilot.json").write_text(json.dumps(state), encoding="utf-8")
    (tmp_path / "cloud" / "pilot-collected.json").write_text(json.dumps(
        {"runs": {"a/x": 11, "b/x": 12}, "not_reached": [], "left_out": [],
         "failed": ["XPT_USDT: ConnectionError: cut"], "refused_records": [],
         "machines_refused": []}), encoding="utf-8")
    # 400 unseen trades over the two coins: +0.30 a trade, each its own stop and target
    unseen = tp._rows([0.30] * 400, per_day=5)
    folder = vrs.home("pilot")
    vrs.save_coin(folder, _record("XAU_USDT", plan, _eight(unseen[:200], 0.004, 0.006)))
    vrs.save_coin(folder, _record("XAG_USDT", plan, _eight(unseen[200:], 0.010, 0.012)))
    return SimpleNamespace(plan=plan, tmp=tmp_path, folder=folder)


def test_publish_judges_the_run_under_the_plan_it_was_dispatched_with(run):
    path = vv.publish("pilot", now=1_793_000_000.0)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["plan_id"] == run.plan["id"] and data["coins"] == ["XAG_USDT", "XAU_USDT"]
    assert (data["risk_usd"], data["runs"], data["tried"]) == (5.0, 200, vp.TRIED)
    assert data["github_runs"] == {"a/x": 11, "b/x": 12} and data["plan_coins"] == 4
    snap = next(v for v in data["verdicts"] if v["id"] == vp.verdict(
        "v3_snap", "1h", "none", vrs.load_coins(run.folder))["id"])
    assert snap["setting"] == "k2" and snap["unseen"]["trades"] == 400
    assert len(data["verdicts"]) == len(vp.verdicts([]))       # every judged group, 27


def test_every_verdict_is_kept_with_every_coin_it_did_not_judge_named(run):
    vv.publish("pilot", now=1_793_000_000.0)
    vv.publish("pilot", now=1_793_000_100.0)
    kept = sorted(p.name for p in (run.tmp / "v3" / "verdicts").iterdir())
    assert kept == ["pilot-1793000000.json", "pilot-1793000100.json"], "nothing deletes one"
    data = json.loads((run.tmp / "v3" / "verdicts.json").read_text(encoding="utf-8"))
    nj = data["not_judged"]
    assert nj["failed"] == ["XPT_USDT: ConnectionError: cut"]
    assert nj["not_dispatched"] == ["EURUSD_USDT"], "a pilot names the coins it never sent"


def test_levels_are_the_chosen_settings_unseen_stops_and_targets(run):
    data = json.loads(vv.publish("pilot").read_text(encoding="utf-8"))
    snap = next(v for v in data["verdicts"] if v["family"] == "v3_snap" and v["tf"] == "1h"
                and v["filter"] == "none")
    # 200 trades at a 0.4% stop and 200 at 1.0%: least, median, most
    assert snap["levels"] == {"stop": [0.004, pytest.approx(0.007), 0.01],
                              "target": [0.006, pytest.approx(0.009), 0.012], "trades": 400}
    chose = next(v for v in data["verdicts"] if v["failed"] == "choose")
    assert chose["levels"] == {"stop": None, "target": None, "trades": 0}


def test_a_record_of_another_risk_is_named_and_never_pooled(run):
    vrs.save_coin(run.folder, _record("XPT_USDT", run.plan, [], risk=1.0))
    data = json.loads(vv.publish("pilot").read_text(encoding="utf-8"))
    assert "XPT_USDT" not in data["coins"]
    assert data["not_judged"]["other_records"] == ["XPT_USDT: risk $1.00, not $5.00"]


def test_a_plan_copy_that_is_not_the_runs_plan_is_refused(run):
    state = json.loads((run.tmp / "cloud" / "pilot.json").read_text(encoding="utf-8"))
    vu.save(_plan(["BTC_USDT"]), state["plan_copy"])
    with pytest.raises(ValueError, match="the run was dispatched with"):
        vv.publish("pilot")


def test_the_tab_lists_every_stored_verdict_and_says_a_pilot_is_not_the_proof(run):
    path = vv.publish("pilot", now=1_793_000_000.0)
    t = vpg.tested(path, check_file=run.tmp / "none.json")
    assert t["state"] == "stored" and t["rows"] == len(t["store"]["verdicts"])
    s = t["store"]
    assert s["tried"] == vp.TRIED and s["plan_coins"] == 4 and len(s["coins"]) == 2
    assert s["not_judged"] == {"failed": 1, "not_dispatched": 1}
    # the sentence is the store's own count, never typed
    passed = sum(1 for r in s["verdicts"] if r["passed"])
    assert t["words"].startswith(f"{passed} of {len(s['verdicts'])} judged ideas passed")
    assert "on 2 of the plan's 4 coins - a pilot of the machinery, not the proof" in t["words"]
    snap = next(r for r in s["verdicts"] if r["family"] == "v3_snap" and r["tf"] == "1h"
                and r["filter"] == "none")
    # the kit's columns: the rules in words, their sizes, leverage, trades a day
    assert snap["target"].startswith("the 20-candle average at the signal, resting")
    assert snap["stop"].startswith("an emergency stop 3 x ATR(20)")
    assert snap["stop_pct"] == "0.70% (0.40%-1.00%)" and snap["lev"] == "20x-20x"
    assert snap["per_day"] == round(400 / 90, 2) and snap["trades"] == 400
    for row in s["verdicts"]:
        for k, v in row.items():
            assert v is not None or row["blank"], f"{row['id']} {k} is empty with no reason"


def test_an_unreadable_store_says_so_and_none_says_nothing_has_run(tmp_path):
    bad = tmp_path / "verdicts.json"
    bad.write_text("{not json", encoding="utf-8")
    t = vpg.tested(bad, check_file=tmp_path / "none.json")
    assert t["state"] == "unreadable" and str(bad) in t["words"] and t["store"] is None
    t = vpg.tested(tmp_path / "absent.json", check_file=tmp_path / "none.json")
    assert t["state"] == "not_run" and t["store"] is None and "not run yet" in t["words"]


def test_the_tabs_list_prints_the_kits_columns_and_derives_its_heading():
    root = Path(__file__).resolve().parent.parent / "webapp" / "src" / "components" / "backtest-v3"
    src = (root / "V3Check.tsx").read_text(encoding="utf-8")
    for label in ('"ID"', "PROFIT (total $)", "Target (TP rule)", "Target size", "Stop (SL rule)",
                  "Stop size", '"Leverage"', "Unseen trades", "Trades a day", "Won / lost",
                  "Worst losing run"):
        assert label in src, label
    # the heading and the combinations come from the store, never typed
    assert "Pilot — ${coins.length} of the plan's ${planCoins} coins, not the proof" in src
    assert "combinations tried" in src and "check.tried" in src
    runner = (root / "V3Runner.tsx").read_text(encoding="utf-8")
    assert 'kind="stored"' in runner and "opts.tested.store" in runner
```

- [ ] **Step 2: Run it to see it fail.**

Run: `.venv/Scripts/python -m pytest tests/test_v3_verdicts.py -q`
Expected: `ImportError: cannot import name 'v3_verdicts' from 'tradingagents'`.

- [ ] **Step 3: Write** `tradingagents/v3_verdicts.py`:

```python
"""THE BACKTEST V3 VERDICT STORE (Part 2b, Oct 27, 2026): a collected run's
records judged pooled, every verdict kept with what it was judged under.

    python -m tradingagents.v3_verdicts publish <name>

`<name>` is a run `python -m tradingagents.v3_cloud dispatch <name>` started
and `collect <name>` brought home. `publish` judges the records in its folder
with the proof test (`v3_research.report` -> `v3_proof.verdicts`, the PC's own
judge, pooled over every coin), under the PLAN THE RUN WAS DISPATCHED WITH
(the copy `dispatch` kept, never whatever research/v3/plan.json holds today),
and writes:

* `stores.V3.home/verdicts.json` - the verdicts the Backtest v3 tab shows
  (`v3_page.tested`), swapped whole;
* `stores.V3.home/verdicts/<name>-<seconds>.json` - the same, kept for good
  (spec Part 3: "Every verdict is kept"); nothing here deletes one.

Each verdict carries its chosen setting's stop and target sizes on the unseen
days (`levels`: the smallest, the median and the largest, as fractions of the
entry), read from the records' trade rows. The file says what it was judged
under - the run, the plan build and its window, the risk, the random runs,
the coins pooled out of the plan's, and every coin of the plan that was NOT
judged, with why - so a page that shows it never has to guess.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path


def store_path() -> Path:
    from tradingagents import stores

    return Path(stores.V3.home) / "verdicts.json"


def history_dir() -> Path:
    from tradingagents import stores

    return Path(stores.V3.home) / "verdicts"


def levels(records: list[dict], v: dict) -> dict:
    """The chosen setting's stop and target sizes over its unseen trades, as
    fractions of each entry: {"stop": [least, median, most] | None, "target":
    same | None (a trail has none), "trades": how many rows carried them}. A
    record measured before rows carried them (version 1) counts in no list."""
    from tradingagents import v3_families as vf

    if not v.get("setting"):
        return {"stop": None, "target": None, "trades": 0}
    key = vf.combo_key(v["family"], v["setting"], v["tf"], v["filter"])
    rows = [r for rec in records for r in (rec.get("combos", {}).get(key, {})
                                           .get("unseen", {}).get("rows") or [])
            if len(r) >= 8]

    def spread(xs):
        return [min(xs), statistics.median(xs), max(xs)] if xs else None

    return {"stop": spread([float(r[6]) for r in rows]),
            "target": spread([float(r[7]) for r in rows if r[7] is not None]),
            "trades": len(rows)}


def build(name: str, *, now: float | None = None) -> dict:
    """The verdict store's content for the collected run `name` (see the
    module doc). Refuses a folder with no record, and a run whose plan copy is
    missing or is not the plan the records were measured under."""
    from tradingagents import (
        v3_cloud as vc,
        v3_proof as vp,
        v3_research as vrs,
        v3_universe as vu,
    )
    from tradingagents.v3_measure import windows

    state = vc.load_state(name)
    collected = json.loads((vc.home() / f"{name}-collected.json").read_text(encoding="utf-8"))
    plan = vu.load(state["plan_copy"])
    if plan["id"] != state["plan_id"]:
        raise ValueError(f"{state['plan_copy']} is plan {plan['id']}, the run was dispatched with "
                         f"{state['plan_id']}")
    root = vrs.home(state["folder"])
    runs, risk = int(state["runs_per_combo"]), float(state["risk_usd"])
    records, other = vrs.split_records(vrs.load_coins(root), plan, runs, risk)
    if not records:
        raise ValueError(f"{root} holds no record measured under plan {plan['id']}: collect "
                         f"{name} first")
    lines, verdicts = vrs.report(records, plan, runs, risk)
    for v in verdicts:
        v["levels"] = levels(records, v)
    start, split, end = windows(plan)
    t = time.time() if now is None else float(now)
    judged = sorted(r["coin"] for r in records)
    return {"version": 1, "name": name, "folder": state["folder"], "label": state["label"],
            "venue": plan.get("venue") or "", "plan_id": plan["id"], "plan_start": start,
            "plan_split": split, "plan_end": end, "risk_usd": risk, "runs": runs,
            "tried": vp.TRIED, "z": vp.Z, "judged_at": t, "github_runs": collected["runs"],
            "coins": judged, "plan_coins": len(plan["coins"]),
            "unseen_months": next((r["unseen_months"] for r in records if r.get("unseen_months")),
                                  []),
            "not_judged": {"not_reached": collected.get("not_reached", []),
                           "failed": collected.get("failed", []),
                           "left_out": collected.get("left_out", []),
                           "refused_records": collected.get("refused_records", []),
                           "machines_refused": collected.get("machines_refused", []),
                           "other_records": [f"{c}: {'; '.join(w)}" for c, w in other],
                           # a pilot dispatches a few of the plan's coins: the rest are named
                           "not_dispatched": sorted(set(plan["coins"]) - set(state["board"]))},
            "lines": lines, "verdicts": verdicts}


def publish(name: str, *, now: float | None = None) -> Path:
    """Write the verdict store and its kept copy; the store's path."""
    data = build(name, now=now)
    text = json.dumps(data, default=str)
    hist = history_dir()
    hist.mkdir(parents=True, exist_ok=True)
    (hist / f"{name}-{int(data['judged_at'])}.json").write_text(text, encoding="utf-8")
    p = store_path()
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)
    return p


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_verdicts")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("publish", help="judge a collected run and keep its verdicts").add_argument(
        "name")
    a = p.parse_args(argv)
    path = publish(a.name)
    data = json.loads(path.read_text(encoding="utf-8"))
    print("\n".join(data["lines"]))
    print(f"kept: {path} ({sum(1 for v in data['verdicts'] if v['passed'])} of "
          f"{len(data['verdicts'])} verdicts passed; {len(data['coins'])} of the plan's "
          f"{data['plan_coins']} coins judged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: The tab reads the store.** In `tradingagents/v3_page.py`, add `from pathlib import Path` after `from decimal import ROUND_HALF_UP, Decimal`; then replace everything from `def tested(rows_db=None, check_file=None) -> dict:` up to (not including) `def options(*, fx=None) -> dict:` with:

```python
def tested(store_file=None, check_file=None) -> dict:
    """What the tab's tested-ideas section can say today: the verdict store
    `python -m tradingagents.v3_verdicts publish` writes (Part 2b), as
    `store` - every verdict, its provenance and how many coins it did NOT
    judge, by why - or, until a run is published, that nothing has been
    tested. Beside it, `check`: the 3-coin check `v3_research` judged on this
    PC (`check()`), labelled a check on the page, never the proof."""
    import json

    from tradingagents import v3_verdicts as vv

    path = vv.store_path() if store_file is None else Path(store_file)
    if not path.exists():
        out = {"state": "not_run", "rows": 0, "store": None,
               "words": "The test of every idea on every coin (step 2 of the Backtest v3 plan) "
                        "has not run yet, so no idea has been tested against random entries. "
                        "This section fills when it does."}
        return {**out, "check": check(check_file)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        out = {"state": "unreadable", "rows": 0, "store": None,
               "words": f"The verdict store {path} could not be read ({type(exc).__name__}: "
                        f"{exc})"}
        return {**out, "check": check(check_file)}
    view = store_view(data)
    return {"state": "stored", "rows": len(view["verdicts"]), "store": view,
            "words": stored_words(view), "check": check(check_file)}


def stored_words(view: dict) -> str:
    """The sentence above the stored verdicts, every number from the store: how
    many passed, on how many of the plan's coins, judged when - and, when fewer
    coins were judged than the plan holds, that it is not the proof."""
    from tradingagents.positions_view import fmt_when

    n, passed = len(view["verdicts"]), sum(1 for r in view["verdicts"] if r["passed"])
    coins, plan_coins = len(view["coins"]), view.get("plan_coins") or 0
    head = (f"{passed} of {n} judged ideas passed against random entries, judged "
            f"{fmt_when(view['judged_at'])} on {coins} of the plan's {plan_coins} coins")
    if coins < plan_coins:
        return head + " - a pilot of the machinery, not the proof: the proof pools every coin."
    return head + "."


def store_view(data: dict) -> dict:
    """A verdicts file - the 3-coin check's or the verdict store - as the tab
    shows it: {"coins", "risk_usd", "runs", "judged_at" (seconds), "plan_end"
    (ms), "plan_id", "lev", "notional", "tried", "plan_coins", "name",
    "not_judged" ({why: how many coins}), "verdicts": one row per verdict,
    every column filled or saying why}."""
    vs = data.get("verdicts") or []
    lev = [x for v in vs for x in (v.get("lev") or [])]
    notional = [x for v in vs for x in (v.get("notional") or [])]
    nj = data.get("not_judged") or {}
    return {"coins": list(data.get("coins") or []), "risk_usd": data.get("risk_usd"),
            "runs": data.get("runs"), "judged_at": data.get("judged_at"),
            "plan_end": data.get("plan_end"), "plan_id": data.get("plan_id"),
            "lev": [min(lev), max(lev)] if lev else None,
            "notional": [min(notional), max(notional)] if notional else None,
            "tried": data.get("tried"), "plan_coins": data.get("plan_coins"),
            "name": data.get("name"), "not_judged": {k: len(x) for k, x in nj.items() if x},
            "verdicts": [check_row(v) for v in vs]}


CHECK_OLD = ("This check's verdicts were made before its details were kept (which plan, risk and "
             "coins) - run judge again: python -m tradingagents.v3_research judge")


def check(path=None) -> dict:
    """The check's verdicts file (`v3_research` writes it beside the coins it
    measured) as the tab shows it: {"state": "ok", **store_view(file)}. A file
    written before its provenance was kept (a bare list) is "old" and says to
    judge again; no file is "none"; a file that cannot be read is
    "unreadable", naming why."""
    import json

    from tradingagents import v3_research as vrs

    p = vrs.home(vrs.DEFAULT_LABEL) / "verdicts.json" if path is None else path
    if not p.exists():
        return {"state": "none", "words": "The 3-coin check has not been judged on this PC: "
                                          "python -m tradingagents.v3_research run BTC_USDT "
                                          "XAU_USDT ETH_USDT"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"state": "unreadable", "words": f"The check's file {p} could not be read "
                                                f"({type(exc).__name__}: {exc})"}
    if isinstance(data, list):
        return {"state": "old", "words": CHECK_OLD, "verdicts": len(data)}
    return {"state": "ok", **store_view(data)}


def _pct_range(xs) -> str | None:
    """[least, median, most] fractions -> "0.70% (0.41%-1.92%)", or None."""
    if not xs:
        return None
    lo, mid, hi = (100 * float(x) for x in xs)
    return f"{mid:.2f}% ({lo:.2f}%-{hi:.2f}%)"


def level_words(lv: dict, which: str) -> str:
    """A verdict's stop or target sizes in words: "0.70% (0.41%-1.92%)" (the
    median, then the least and the most), "none: a trailing stop has no
    target", or "not recorded" for a verdict judged from records whose trade
    rows did not keep them (Part 2a's)."""
    if not lv.get("trades"):
        return "not recorded"
    got = _pct_range(lv.get(which))
    if got is None:
        return "none: a trailing stop has no target" if which == "target" else "not recorded"
    return got


def check_row(v: dict) -> dict:
    """One verdict as the tab's tables print it - the kit's columns: id,
    profit, the target and stop rules (and, from the store's `levels`, their
    sizes), leverage, wins and losses, the worst losing run, trades and trades
    a day. A number the verdict does not have is None with `blank` saying why,
    so no cell is ever empty."""
    from tradingagents import v3_research as vrs
    from tradingagents.v3_measure import UNSEEN_DAYS

    chose = v.get("failed") == "choose"
    s = v.get("unseen") or {}
    rr = v.get("random_runs") or {}
    if chose:
        blank = "not judged: no setting was chosen"
    elif not s.get("trades"):
        blank = "no trade on the unseen days"
    else:
        blank = ""
    trades = None if chose else int(s.get("trades") or 0)
    has = bool(trades)
    target = stop = None
    if v.get("setting"):
        target, stop = vrs.exit_words(v["family"], v["setting"], v["tf"])
    lv = v.get("levels") or {}
    lev = v.get("lev") if has else None
    return {"id": v["id"], "family": v["family"], "tf": v["tf"], "filter": v["filter"],
            "setting": v.get("setting"), "passed": bool(v.get("passed")),
            "failed": v.get("failed") or "",
            "verdict": "PASSED" if v.get("passed") else f"FAILED at {v.get('failed')}",
            "trades": trades, "wins": s.get("wins") if has else None,
            "losses": s.get("losses") if has else None,
            "win_rate": s.get("win_rate") if has else None,
            "profit": cents(s["profit"]) if has and s.get("profit") is not None else None,
            "per_day": round(trades / UNSEEN_DAYS, 2) if has else None,
            "worst_run_usd": cents(s.get("worst_run_usd") or 0.0) if has else None,
            "worst_run_trades": int(s.get("worst_run_trades") or 0) if has else None,
            "target": target, "stop": stop,
            "target_pct": level_words(lv, "target") if has else None,
            "stop_pct": level_words(lv, "stop") if has else None,
            "lev": f"{lev[0]}x-{lev[1]}x" if lev else None,
            "random_median_trades": None if chose else rr.get("median_trades"),
            "real_trades": None if chose else rr.get("real_trades"),
            "why": (v.get("why") or "") if chose else f"chose {v.get('setting')} on the older days",
            "blank": blank or ("" if rr.get("median_trades") is not None
                               else "the random runs' trades were not recorded")}
```


- [ ] **Step 5: The tab shows it.** Apply to `webapp/src/components/backtest-v3/V3Check.tsx` and `V3Runner.tsx`:

```diff
--- a/webapp/src/components/backtest-v3/V3Check.tsx
+++ b/webapp/src/components/backtest-v3/V3Check.tsx
@@ -18,13 +18,23 @@
   losses: number | null; win_rate: number | null; profit: number | null;
   worst_run_usd: number | null; worst_run_trades: number | null;
   random_median_trades: number | null; real_trades: number | null; why: string; blank: string;
+  // Part 2b: the kit's remaining columns (v3_page.check_row)
+  per_day?: number | null; target?: string | null; stop?: string | null;
+  target_pct?: string | null; stop_pct?: string | null; lev?: string | null;
 };
 export type Check = {
   state: string; words?: string; coins?: string[]; risk_usd?: number | null; runs?: number | null;
   judged_at?: number | null; plan_end?: number | null; plan_id?: string | null;
   lev?: [number, number] | null; notional?: [number, number] | null; verdicts?: CheckRow[] | number;
+  // the verdict store's (v3_page.store_view): combinations tried, the plan's coins, the run's name,
+  // and how many of the plan's coins were not judged, by why
+  tried?: number | null; plan_coins?: number | null; name?: string | null;
+  not_judged?: Record<string, number>;
 } | null;
 
+/** "check": the 3-coin check on this PC; "stored": the verdict store a GitHub run published. */
+export type CheckKind = "check" | "stored";
+
 const PER_PAGE = 10;           // Auto Trade's own page size
 const th = "px-3 py-2 text-left text-theme-xs font-medium text-gray-500 dark:text-gray-400";
 const td = "whitespace-nowrap px-3 py-2 text-theme-sm tabular-nums text-gray-700 dark:text-gray-300";
@@ -38,11 +48,17 @@
   if (names.length <= 1) return names.join("");
   return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
 }
+// why a coin of the plan was not judged, in words (v3_verdicts' `not_judged` keys)
+const NOT_JUDGED: Record<string, string> = {
+  not_reached: "not reached", failed: "failed", left_out: "left out by the machine",
+  refused_records: "refused at landing", machines_refused: "machines refused",
+  other_records: "measured under another plan or risk", not_dispatched: "not sent (a pilot)",
+};
 function money(v: number): string {
   return `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
 }
 
-export default function V3Check({ check }: { check: Check }) {
+export default function V3Check({ check, kind = "check" }: { check: Check; kind?: CheckKind }) {
   const [page, setPage] = useState(1);
   const [sort, setSort] = useState<{ key: Key; dir: 1 | -1 } | null>(null);
   const rows = useMemo(() => (Array.isArray(check?.verdicts) ? check.verdicts : []), [check]);
@@ -61,10 +77,17 @@
   }, [rows, sort]);
   if (!check) return null;
   const coins = check.coins ?? [];
-  const heading = check.state === "ok"
-    ? `Check only — ${coins.length} coin${coins.length === 1 ? "" : "s"}, not the proof`
-    : "Check only — not the proof";
-  if (check.state !== "ok") {
+  const planCoins = check.plan_coins ?? 0;
+  // every word of the heading from the file: a store judged on fewer coins than its plan holds is a
+  // pilot, never the proof
+  const heading = kind === "stored"
+    ? (coins.length < planCoins
+      ? `Pilot — ${coins.length} of the plan's ${planCoins} coins, not the proof`
+      : `Every idea's verdict — ${coins.length} coins`)
+    : check.state === "ok"
+      ? `Check only — ${coins.length} coin${coins.length === 1 ? "" : "s"}, not the proof`
+      : "Check only — not the proof";
+  if (kind === "check" && check.state !== "ok") {
     return (
       <div className="mt-4">
         <h4 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">{heading}</h4>
@@ -94,8 +117,12 @@
     <div className="mt-4">
       <h4 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">{heading}</h4>
       <p className="mt-1 max-w-3xl text-theme-xs text-gray-500 dark:text-gray-400">
-        {coinWords(coins)} judged {fmtWhen(check.judged_at)} at {risk} a trade, {check.runs ?? "an unrecorded number of"} random
-        runs a combination; the proof needs every coin (step 2b on GitHub). {passed} of {rows.length} verdicts passed.
+        {kind === "stored" ? `${coins.length} coins` : coinWords(coins)} judged {fmtWhen(check.judged_at)} at {risk} a
+        trade, {check.runs ?? "an unrecorded number of"} random runs a combination
+        {kind === "stored" ? `, ${check.tried ?? "an unrecorded number of"} combinations tried` : "; the proof needs every coin (step 2b on GitHub)"}.
+        {" "}{passed} of {rows.length} verdicts passed.
+        {kind === "stored" && check.not_judged && Object.keys(check.not_judged).length > 0 &&
+          ` Not judged: ${Object.entries(check.not_judged).map(([k, n]) => `${n} ${NOT_JUDGED[k] ?? k}`).join(", ")}.`}
       </p>
       <p className="mt-1 max-w-3xl text-theme-xs text-gray-500 dark:text-gray-400">
         Universe plan {check.plan_id ?? "not recorded"}, ending {fmtWhen(check.plan_end != null ? check.plan_end / 1000 : null)}
@@ -107,8 +134,10 @@
           <TableHeader className="border-b border-gray-100 dark:border-white/[0.05]">
             <TableRow>
               {head("id", "ID")}{head("family", "Idea")}{head("tf", "Timeframe")}{head("filter", "Filter")}
-              {head("setting", "Setting chosen")}{head("verdict", "Verdict")}{head("trades", "Unseen trades")}
-              {head("wins", "Won / lost")}{head("win_rate", "Win rate")}{head("profit", "PROFIT (total $)")}
+              {head("setting", "Setting chosen")}{head("verdict", "Verdict")}{head("profit", "PROFIT (total $)")}
+              {head("target", "Target (TP rule)")}{head("target_pct", "Target size")}{head("stop", "Stop (SL rule)")}
+              {head("stop_pct", "Stop size")}{head("lev", "Leverage")}{head("trades", "Unseen trades")}{head("per_day", "Trades a day")}
+              {head("wins", "Won / lost")}{head("win_rate", "Win rate")}
               {head("worst_run_usd", "Worst losing run")}{head("random_median_trades", "Random runs' median trades vs the real run's")}
               {head("why", "Why")}
             </TableRow>
@@ -122,10 +151,12 @@
                 <TableCell className={td}>{r.filter}</TableCell>
                 {cell(r, r.setting)}
                 <TableCell className={`${td} font-semibold ${r.passed ? "text-success-600 dark:text-success-400" : "text-error-600 dark:text-error-400"}`}>{r.verdict}</TableCell>
-                {cell(r, r.trades)}
+                {cell(r, r.profit != null ? money(r.profit) : null)}
+                {cell(r, r.target ?? null)}{cell(r, r.target_pct ?? null)}{cell(r, r.stop ?? null)}
+                {cell(r, r.stop_pct ?? null)}{cell(r, r.lev ?? null)}
+                {cell(r, r.trades)}{cell(r, r.per_day ?? null)}
                 {cell(r, r.wins != null && r.losses != null ? `${r.wins} / ${r.losses}` : null)}
                 {cell(r, r.win_rate != null ? `${(r.win_rate * 100).toFixed(1)}%` : null)}
-                {cell(r, r.profit != null ? money(r.profit) : null)}
                 {cell(r, r.worst_run_usd != null && r.worst_run_trades != null
                   ? (r.worst_run_trades ? `${money(r.worst_run_usd)} over ${r.worst_run_trades} trade${r.worst_run_trades === 1 ? "" : "s"}` : "no losses")
                   : null)}
@@ -136,7 +167,7 @@
           </TableBody>
         </Table>
       </div>
-      <PageButtons cur={page} pages={pages} goto={setPage} what="Check verdicts" />
+      <PageButtons cur={page} pages={pages} goto={setPage} what={kind === "stored" ? "Verdicts" : "Check verdicts"} />
     </div>
   );
 }
--- a/webapp/src/components/backtest-v3/V3Runner.tsx
+++ b/webapp/src/components/backtest-v3/V3Runner.tsx
@@ -35,7 +35,7 @@
   families: Family[];
   plan: { id: string; start_ms: number; end_ms: number; last_month: string } | null;
   plan_error: string;
-  tested: { state: string; rows: number | null; words: string; check: Check };
+  tested: { state: string; rows: number | null; words: string; store: Omit<NonNullable<Check>, "state"> | null; check: Check };
 };
 type Family = {
   name: string; words: string; tfs: string[]; long: string[]; short: string[];
@@ -555,6 +555,7 @@
         <div className={card}>
           <h3 className="text-theme-sm font-semibold text-gray-800 dark:text-white/90">Tested ideas</h3>
           <p className="mt-1 max-w-3xl text-theme-xs text-gray-500 dark:text-gray-400">{opts.tested.words}</p>
+          {opts.tested.store && <V3Check check={{ state: "ok", ...opts.tested.store }} kind="stored" />}
           <V3Check check={opts.tested.check} />
         </div>
       )}
```

- [ ] **Step 6: Run the tests, the tab's tests, the type check and the linters.**

Run: `.venv/Scripts/python -m pytest tests/test_v3_verdicts.py tests/test_backtest_v3_tab.py tests/test_backtest_v3_tab_families.py tests/test_backtest_v3_tab_no_trade_words.py tests/test_v3_research.py -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_verdicts.py tradingagents/v3_page.py tests/test_v3_verdicts.py`, then in `webapp/`: `npx tsc --noEmit` and `npx eslint src/components/backtest-v3`
Expected: all pass (`test_v3_verdicts.py` 8 in scratch; the existing tab tests unchanged - `tested()`'s first argument is now the store file, and `tests/test_backtest_v3_tab.py` passes a path that does not exist, so it still reads "not run yet"); tsc and eslint clean.

- [ ] **Step 7: Look at it (CLAUDE.md `verify-ui-change`).** Publish a test store into a scratch v3 home, serve the API and a built copy of the web app on spare ports as Part 2a's Task "after-2" did (`G:\tradingagents-home\tmp`, webpack, ports 8513 and 8797, never 8503/8787), and check at 1280 px and 390 px: the "Pilot — 2 of the plan's 4 coins, not the proof" heading, every column filled or saying why, sorting, paging, no sideways scroll, no console error. Stop both servers.

- [ ] **Step 8: Commit and push.**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_verdicts.py tradingagents/v3_page.py webapp/src/components/backtest-v3/V3Check.tsx webapp/src/components/backtest-v3/V3Runner.tsx tests/test_v3_verdicts.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
feat(v3): the verdict store (python -m tradingagents.v3_verdicts publish) - a collected run judged pooled with Part 2a's judge under the plan it was dispatched with, every verdict kept with its run, plan, risk, runs and the coins it did not judge - and the Backtest v3 tab lists it with the kit's columns, a pilot said to be a pilot - Part 2b, Task 4

harddev: the plan copy is checked against the run's id; records of another risk named, never pooled; a kept copy per publish, nothing deletes one; every cell a number or why; the tab's heading from the store's coin counts.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 5: The results page (the artifact, with the standard kit)

**Files:**
- Create: `tradingagents/v3_results_page.py`
- Test: `tests/test_v3_results_page.py`

**Interfaces:**
- Consumes: Task 4's store (`v3_verdicts.history_dir`, its kept copies) and its folder's records; `v3_page.check_row`; `v3_research.exit_words / load_coins / home`; `v3_families.combo_key`.
- Produces: `v3_results_page.payload(store, records) -> dict` (rows: `id, family, tf, filter, setting, passed, failed, verdict, why, blank, target, stop, lev, notional, older {setting: [trades, per_trade, eligible]}, random [median, bar, traded, runs], boot, rand_trades [median, real], notes, t [[coin, entry s, exit s, side, pnl x 1e4, why index, stop x 1e5 or -1, target x 1e5 or -1], ...]`), `build(store, records) -> str` (one HTML page, its data inline), `write(name) -> Path` (`stores.V3.home/pages/<name>.html`, from the NEWEST kept copy). The page's JavaScript functions `measure(row, from_s, k)`, `monthsIn(months, end_s, days)`, `fails(measured, filters)` sit between `/*LOGIC*/` and `/*END LOGIC*/` (the tests run them under node).

- [ ] **Step 1: Write the failing test** `tests/test_v3_results_page.py`:

```python
"""The Backtest v3 results page (tradingagents/v3_results_page.py, Part 2b)
carries the standard kit (CLAUDE.md "Backtest reporting requirements"): every
judged group a row with every field and its stable id first, the row's figures
worked out in the page FROM ITS TRADES (so they add up to the verdict), the
risk box rescaling every dollar, the window re-adding every row over the
trades that closed in it and dropping the months outside it, the max TP % and
max SL % boxes as inclusive ceilings, and the trade log with its TOTAL PROFIT.
The page's own JavaScript is run under node, on the payload it embeds."""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess

import pytest

import tests.test_v3_verdicts as tv
from tradingagents import v3_page as vpg, v3_results_page as vrp, v3_verdicts as vv
from tradingagents.positions_view import fmt_when

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


@pytest.fixture()
def page(monkeypatch, tmp_path):
    run = tv.make_run(monkeypatch, tmp_path)
    store = vv.build("pilot", now=1_793_000_000.0)
    records = vv_records(run)
    return store, records, vrp.build(store, records), vrp.payload(store, records)


def vv_records(run):
    from tradingagents import v3_research as vrs

    return vrs.load_coins(run.folder)


def _js(html: str, data: dict, expr: str):
    logic = re.search(r"/\*LOGIC\*/(.*?)/\*END LOGIC\*/", html, re.S).group(1)
    prog = f"const D={json.dumps(data)};\n{logic}\nconsole.log(JSON.stringify({expr}));"
    # the program on stdin: a payload of thousands of trades is past Windows' command-line limit
    out = subprocess.run([NODE], input=prog, capture_output=True, text=True, timeout=60,
                         encoding="utf-8")
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


def _snap(data):
    return next(i for i, r in enumerate(data["rows"]) if r["family"] == "v3_snap"
                and r["tf"] == "1h" and r["filter"] == "none")


def test_every_judged_group_is_a_row_with_every_field(page):
    store, _records, html, data = page
    assert len(data["rows"]) == len(store["verdicts"]) == 27
    keys = {frozenset(r) for r in data["rows"]}
    assert len(keys) == 1, "every row carries every field (kit F)"
    chose = next(r for r in data["rows"] if r["failed"] == "choose")
    assert chose["t"] == [] and chose["blank"] == "not judged: no setting was chosen"
    embedded = json.loads(re.search(r"const D = (\{.*?\});\n", html).group(1))
    assert embedded == json.loads(json.dumps(data))


def test_a_rows_trades_are_its_chosen_settings_unseen_trades_in_closing_order(page):
    _store, records, _html, data = page
    row = data["rows"][_snap(data)]
    assert row["setting"] == "k2" and len(row["t"]) == 400
    assert [t[2] for t in row["t"]] == sorted(t[2] for t in row["t"])
    # coin index, entry and exit seconds, side, profit x 10,000, exit kind, stop and target x 100,000
    first = row["t"][0]
    assert data["coins"][first[0]] in ("XAG_USDT", "XAU_USDT") and first[3] == 1
    assert first[4] == 3000 and data["whys"][first[5]] == "TP" and first[6] in (400, 1000)


@needs_node
def test_the_row_adds_up_to_its_verdict_and_its_trades(page):
    store, _records, html, data = page
    i = _snap(data)
    m = _js(html, data, f"measure(D.rows[{i}],null,1)")
    v = next(x for x in store["verdicts"] if x["id"] == data["rows"][i]["id"])
    assert m["trades"] == v["unseen"]["trades"] == 400
    assert m["wins"] + m["losses"] == m["trades"] and m["wins"] == v["unseen"]["wins"]
    assert m["profit"] == pytest.approx(v["unseen"]["profit"], abs=0.005)
    assert (round(m["worst"], 2), m["worstN"]) == vpg.worst_run([t[4] / 1e4 for t in m["t"]])
    # the median stop of 200 at 0.4% and 200 at 1.0%, in percent, as the SL % box reads it
    assert m["stop"] == pytest.approx(0.7) and m["target"] == pytest.approx(0.9)


@needs_node
def test_the_risk_box_rescales_every_dollar(page):
    _store, _records, html, data = page
    i = _snap(data)
    one, two = _js(html, data, f"[measure(D.rows[{i}],null,1),measure(D.rows[{i}],null,2)]")
    assert two["profit"] == pytest.approx(2 * one["profit"])
    assert two["per"] == pytest.approx(2 * one["per"]) and two["trades"] == one["trades"]


@needs_node
def test_the_window_re_adds_each_row_and_drops_the_months_outside_it(page):
    _store, _records, html, data = page
    i = _snap(data)
    end = data["end"] // 1000
    got = _js(html, data, f"[measure(D.rows[{i}],{end - 30 * 86400},1),"
                          f"monthsIn(D.months,{end},30),monthsIn(D.months,{end},null)]")
    m, months30, every = got
    closed = [t for t in data["rows"][i]["t"] if t[2] >= end - 30 * 86400]
    # the fixture's trades close one day after another to Oct 12, 2026: some in the last 30
    # days, most before them
    assert 0 < len(closed) < 400
    assert m["trades"] == len(closed)
    assert m["profit"] == pytest.approx(sum(t[4] for t in closed) / 1e4)
    assert every == data["months"] and set(months30) <= set(every)
    assert all(mk >= months30[0] for mk in months30) and len(months30) <= 2


@needs_node
def test_max_tp_and_max_sl_are_inclusive_ceilings_and_a_trail_has_no_target(page):
    _store, _records, html, data = page
    m = {"win": 100.0, "profit": 120.0, "green": 2, "worst": 0, "stop": 0.7, "target": 0.9}
    trail = {**m, "target": None}
    got = _js(html, data, f"[fails({json.dumps(m)},{{sl:0.7,tp:0.9}}),"
                          f"fails({json.dumps(m)},{{sl:0.69}}),"
                          f"fails({json.dumps(m)},{{tp:0.89}}),"
                          f"fails({json.dumps(trail)},{{tp:50}}),"
                          f"fails({json.dumps(m)},{{gm:2}}),fails({json.dumps(m)},{{gm:3}})]")
    assert got == [[], ["max SL %"], ["max TP %"], ["max TP %"], [], ["min months green"]]


def test_the_kit_is_on_the_page(page):
    _store, _records, html, _data = page
    cols = re.search(r"const COLS=\[(.*?)\];\n", html, re.S).group(1)
    assert cols.startswith('["id","ID",1]'), "a stable id first (kit H)"
    for label in ("PROFIT (total $)", "TP (target rule)", "TP %", "SL (stop rule)", "SL %",
                  "Leverage", '"W"', '"L"', "Worst losing run", "Trades a day", "Months green"):
        assert label in cols, label
    for box in ("f-risk", "f-wr", "f-pr", "f-gm", "f-dd", "f-tp", "f-sl", "f-days", "f-id",
                "clear"):
        assert f'id="{box}"' in html, box
    assert "TOTAL PROFIT" in html and "margin = the coin bought ÷ its leverage" in html
    title = re.search(r"<title>(.*?)</title>", html).group(1)
    assert 2 <= len(title.split()) <= 4


@needs_node
def test_the_pages_date_format_is_the_projects(page):
    _store, _records, html, _data = page
    js = re.search(r"(const MON=.*?\nfunction fmtWhen\(ms\)\{.*?\n.*?\})\n", html, re.S).group(1)
    moments = [dt.datetime(2026, 8, 3, 20, 3), dt.datetime(2026, 9, 1, 0, 0),
               dt.datetime(2026, 9, 12, 12, 0)]
    ms = [int(x.timestamp() * 1000) for x in moments]
    out = subprocess.run([NODE, "-e", js + f"\nfor (const m of {ms}) console.log(fmtWhen(m));"],
                         capture_output=True, text=True, timeout=60).stdout.split("\n")
    assert out[:3] == [fmt_when(x / 1000) for x in ms]


def test_the_page_is_built_from_the_newest_kept_verdicts(monkeypatch, tmp_path):
    from tradingagents import stores

    tv.make_run(monkeypatch, tmp_path)
    vv.publish("pilot", now=1_793_000_000.0)
    vv.publish("pilot", now=1_793_000_100.0)
    monkeypatch.setattr(stores, "V3", stores.Store(**{**stores.V3.__dict__,
                                                      "home": tmp_path / "v3"}))
    out = vrp.write("pilot")
    data = json.loads(re.search(r"const D = (\{.*?\});\n", out.read_text(encoding="utf-8"))
                      .group(1))
    assert data["judged_at"] == 1_793_000_100.0 and out.parent == tmp_path / "v3" / "pages"
    with pytest.raises(ValueError, match="no verdicts kept for other"):
        vrp.write("other")
```

- [ ] **Step 2: Run it to see it fail.**

Run: `.venv/Scripts/python -m pytest tests/test_v3_results_page.py -q`
Expected: `ImportError: cannot import name 'v3_results_page' from 'tradingagents'`.

- [ ] **Step 3: Write** `tradingagents/v3_results_page.py`:

```python
"""THE BACKTEST V3 RESULTS PAGE (Part 2b): every judged idea of a published run
as one artifact page with the standard kit (CLAUDE.md "Backtest reporting
requirements").

    python -m tradingagents.v3_results_page <name>   ->  stores.V3.home/pages/<name>.html

Built from the verdict store's kept copy of the run (`v3_verdicts`) and the
records in its folder, never from anything typed: one row per judged group
(family x timeframe x filter, its stable id first, `v3_families.verdict_id`),
each carrying its chosen setting's pooled UNSEEN trades
([coin, entry s, exit s, side, profit x 10,000, exit kind, stop x 100,000,
target x 100,000 or -1]) and every other field - a group that chose nothing
carries no trade and says why in every column (kit F).

Everything a row prints is worked out IN THE PAGE from its trades, so the
risk box rescales every dollar (kit C: the research measured at $5 a trade;
at another risk some trades would be sized differently or be under one lot,
and the page says so), the window box re-adds every row over the trades that
CLOSED in its last N days and drops the month columns outside it (kit G; the
minutes cannot ride in a page, so it is a re-add of the measured trades, never
a new walk - said beside the count), and a click opens the trade-by-trade log
with its TOTAL PROFIT (kit B, D). Max TP % and max SL % read each row's median
target and stop (a trailing stop has no target, so any max TP % leaves it
out, said beside the count).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

WHYS = ("TP", "SL", "TRAIL", "MA", "TIME", "END", "RANK")


def payload(store: dict, records: list[dict]) -> dict:
    """The page's data: every judged group with every field (kit F) and its
    chosen setting's pooled unseen trades in the compact encoding above."""
    from tradingagents import v3_families as vf, v3_page as vpg, v3_research as vrs

    coins = sorted({r["coin"] for r in records})
    at = {c: i for i, c in enumerate(coins)}
    rows = []
    for v in store["verdicts"]:
        trades = []
        if v.get("setting"):
            key = vf.combo_key(v["family"], v["setting"], v["tf"], v["filter"])
            for rec in records:
                for r in (rec.get("combos", {}).get(key, {}).get("unseen", {}).get("rows") or []):
                    trades.append([at[rec["coin"]], int(r[1]) // 1000, int(r[2]) // 1000,
                                   int(r[3]), int(round(float(r[4]) * 10_000)),
                                   WHYS.index(r[5]),
                                   int(round(float(r[6]) * 100_000)) if len(r) > 6 else -1,
                                   int(round(float(r[7]) * 100_000))
                                   if len(r) > 7 and r[7] is not None else -1])
            trades.sort(key=lambda x: (x[2], x[1], x[0]))
        target, stop = (vrs.exit_words(v["family"], v["setting"], v["tf"]) if v.get("setting")
                        else (None, None))
        row = vpg.check_row(v)
        rnd = v.get("random") or {}
        rows.append({"id": v["id"], "family": v["family"], "tf": v["tf"], "filter": v["filter"],
                     "setting": v.get("setting"), "passed": bool(v.get("passed")),
                     "failed": v.get("failed") or "", "verdict": row["verdict"],
                     "why": row["why"], "blank": row["blank"], "target": target, "stop": stop,
                     "lev": v.get("lev"), "notional": v.get("notional"),
                     "older": {k: [o["trades"], o["per_trade"], o["eligible"]]
                               for k, o in (v.get("older") or {}).items()},
                     "random": [rnd.get("median"), rnd.get("bar"), rnd.get("traded"),
                                rnd.get("runs")],
                     "boot": (v.get("bootstrap") or {}).get("low"),
                     "rand_trades": [row["random_median_trades"], row["real_trades"]],
                     "notes": list(v.get("notes") or []), "t": trades})
    return {"name": store["name"], "venue": store.get("venue") or "", "risk": store["risk_usd"],
            "runs": store["runs"], "tried": store["tried"], "z": store["z"],
            "plan_id": store["plan_id"], "start": store["plan_start"],
            "split": store["plan_split"], "end": store["plan_end"],
            "judged_at": store["judged_at"], "coins": coins, "plan_coins": store["plan_coins"],
            "months": store["unseen_months"], "whys": list(WHYS),
            "not_judged": store.get("not_judged") or {}, "github_runs": store["github_runs"],
            "rows": rows}


def build(store: dict, records: list[dict]) -> str:
    return _HTML.replace("/*__DATA__*/null",
                         json.dumps(payload(store, records), separators=(",", ":")))


def write(name: str) -> Path:
    """The page of the run `name`'s newest kept verdicts, under the v3 store."""
    from tradingagents import stores, v3_research as vrs, v3_verdicts as vv

    kept = sorted(vv.history_dir().glob(f"{name}-*.json"),
                  key=lambda p: int(p.stem.rsplit("-", 1)[1]))
    if not kept:
        raise ValueError(f"no verdicts kept for {name}: python -m tradingagents.v3_verdicts "
                         f"publish {name}")
    store = json.loads(kept[-1].read_text(encoding="utf-8"))
    judged = set(store["coins"])
    records = [r for r in vrs.load_coins(vrs.home(store["folder"])) if r["coin"] in judged]
    out = Path(stores.V3.home) / "pages" / f"{name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(store, records), encoding="utf-8")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_results_page")
    p.add_argument("name")
    a = p.parse_args(argv)
    out = write(a.name)
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Backtest v3 Verdicts</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
:root{color-scheme:light;--bg:#f6f7f5;--panel:#fff;--ink:#15191a;--ink2:#4b5355;--ink3:#7a8386;--rule:#dde2df;
 --accent:#0f6b62;--gain:#2a78d6;--loss:#e34948;--warn:#9a6300;
 --sans:"Instrument Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"JetBrains Mono",ui-monospace,Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#111514;--panel:#181d1c;--ink:#eef2f0;
 --ink2:#b3bcb9;--ink3:#86908d;--rule:#2b3331;--accent:#4fb3a7;--gain:#3987e5;--loss:#e66767;--warn:#e0a53a}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#111514;--panel:#181d1c;--ink:#eef2f0;--ink2:#b3bcb9;--ink3:#86908d;
 --rule:#2b3331;--accent:#4fb3a7;--gain:#3987e5;--loss:#e66767;--warn:#e0a53a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 var(--sans)}
main{max-width:1400px;margin:0 auto;padding:16px}h1{font-size:20px;margin:0 0 6px}
.prov,.count,.note{color:var(--ink2);font-size:13px;margin:6px 0}.filters{display:flex;flex-wrap:wrap;gap:8px 12px;margin:12px 0}
.filters label{display:flex;flex-direction:column;font-size:12px;color:var(--ink2)}
input,select,button{font:13px var(--sans);padding:4px 6px;border:1px solid var(--rule);border-radius:6px;background:var(--panel);color:var(--ink)}
input[type=number]{width:96px}.wrap{overflow-x:auto;background:var(--panel);border:1px solid var(--rule);border-radius:8px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--rule);text-align:right;white-space:nowrap}
th{cursor:pointer;font-size:12px;color:var(--ink2);position:sticky;top:0;background:var(--panel)}
td.l,th.l{text-align:left}.id{font-family:var(--mono)}.pos{color:var(--gain)}.neg{color:var(--loss)}.muted{color:var(--ink3);font-style:italic}
tr.row:hover{background:color-mix(in srgb,var(--accent) 8%,transparent);cursor:pointer}
dialog{max-width:min(1100px,100vw - 32px);width:100%;border:1px solid var(--rule);border-radius:10px;background:var(--panel);color:var(--ink)}
.sum{display:flex;flex-wrap:wrap;gap:6px 18px;margin:8px 0}.total{font-size:18px}
</style></head><body><main>
<h1 id="h">Backtest v3 verdicts</h1>
<p class="prov" id="prov"></p>
<div class="filters">
 <label>Risk a trade $<input id="f-risk" type="number" min="0.1" step="0.5"></label>
 <label>Min win %<input id="f-wr" type="number" min="0" max="100" placeholder="any"></label>
 <label>Min profit $<input id="f-pr" type="number" step="1" placeholder="any"></label>
 <label>Min months green<input id="f-gm" type="number" min="0" step="1" placeholder="any"></label>
 <label>Max worst dip $<input id="f-dd" type="number" min="0" step="1" placeholder="any"></label>
 <label>Max TP %<input id="f-tp" type="number" min="0" step="0.1" placeholder="any"></label>
 <label>Max SL %<input id="f-sl" type="number" min="0" step="0.1" placeholder="any"></label>
 <label>Last N days<input id="f-days" type="number" min="1" step="1" placeholder="all unseen"></label>
 <label>Passed only<select id="f-pass"><option value="">all</option><option value="1">passed</option></select></label>
 <label>Find by ID<input id="f-id" type="text" placeholder="#XXXXXXXX"></label>
 <label>&nbsp;<button id="clear">Clear all filters</button></label>
</div>
<p class="count" id="count"></p>
<div class="wrap"><table><thead id="thead"></thead><tbody id="tbody"></tbody></table></div>
<p class="note" id="notes"></p>
</main>
<dialog id="dlg"><div id="dlg-body"></div><p><button id="dlg-close">Close</button></p></dialog>
<script>
const D = /*__DATA__*/null;
const MON=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
function fmtWhen(ms){const d=new Date(ms);let h=d.getHours();const ap=h<12?"am":"pm";h=h%12||12;
 return `${MON[d.getMonth()]} ${String(d.getDate()).padStart(2,"0")}, ${d.getFullYear()} ${h}:${String(d.getMinutes()).padStart(2,"0")}${ap}`}
/*LOGIC*/
// one row over the trades that CLOSED at or after from_s (null = every unseen trade), dollars x k
function measure(r,from_s,k){
 const t=from_s==null?r.t:r.t.filter(x=>x[2]>=from_s);
 let profit=0,wins=0,run=0,runN=0,worst=0,worstN=0;const months={},stops=[],tgts=[];
 for(const x of t){const p=x[4]/1e4*k;profit+=p;
  if(p>0){wins++;run=0;runN=0}else{run+=p;runN++;if(run<worst){worst=run;worstN=runN}}
  const m=monthKey(x[2]);months[m]=(months[m]||0)+p;if(x[6]>=0)stops.push(x[6]/1e3);if(x[7]>=0)tgts.push(x[7]/1e3)}
 const n=t.length;
 return {trades:n,wins,losses:n-wins,win:n?wins/n*100:null,profit:n?profit:null,per:n?profit/n:null,
  worst:worstN?worst:0,worstN,months,green:Object.values(months).filter(v=>v>0).length,
  stop:median(stops),target:median(tgts),t};
}
function median(xs){if(!xs.length)return null;const s=[...xs].sort((a,b)=>a-b),m=s.length>>1;return s.length%2?s[m]:(s[m-1]+s[m])/2}
function monthKey(s){const d=new Date(s*1000);return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,"0")}`}
function monthEnd(key){const [y,m]=key.split("-").map(Number);return Date.UTC(y,m,1)/1000}
// the unseen months a window of the last N days touches (null = every one)
function monthsIn(months,end_s,days){if(!days)return months.slice();const from=end_s-days*86400;return months.filter(m=>monthEnd(m)>from)}
// the filters a measured row fails, by name (inclusive ceilings and floors; a row with no number fails a floor)
function fails(m,f){const out=[];
 if(f.wr!=null&&!(m.win!=null&&m.win>=f.wr))out.push("min win %");
 if(f.pr!=null&&!(m.profit!=null&&m.profit>=f.pr))out.push("min profit $");
 if(f.gm!=null&&!(m.green>=f.gm))out.push("min months green");
 if(f.dd!=null&&!(-m.worst<=f.dd))out.push("max worst dip $");
 if(f.tp!=null&&!(m.target!=null&&m.target<=f.tp))out.push("max TP %");
 if(f.sl!=null&&!(m.stop!=null&&m.stop<=f.sl))out.push("max SL %");
 return out}
/*END LOGIC*/
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const money=v=>v==null?"":(v>0?"+":"")+(v<0?"-":"")+"$"+Math.abs(v).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
const usd=v=>"$"+Math.abs(v).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
const pct=v=>v==null?"":v.toFixed(2)+"%";
const num=s=>{const v=parseFloat(s);return Number.isFinite(v)?v:null};
const state={risk:D.risk,f:{},days:null,pass:"",id:"",sort:{k:"profit",dir:-1}};
const COLS=[["id","ID",1],["family","Idea",1],["tf","Timeframe",1],["filter","Filter",1],["setting","Setting",1],
 ["verdict","Verdict",1],["profit","PROFIT (total $)"],["target","TP (target rule)",1],["tp","TP %"],["stop","SL (stop rule)",1],
 ["sl","SL %"],["lev","Leverage",1],["trades","Trades"],["perday","Trades a day"],["wins","W"],["losses","L"],["win","Win %"],
 ["worst","Worst losing run"],["green","Months green"],["per","$ a trade"],["bar","Random bar $ a trade"]];
function view(){const end=D.end/1000,from=state.days?end-state.days*86400:null,k=state.risk/D.risk;
 const months=monthsIn(D.months,end,state.days),span=(state.days||Math.round((D.end-D.split)/86400000));
 const rows=D.rows.map(r=>({r,m:measure(r,from,k)}));
 let shown;const id=state.id.replace(/^#/,"").toUpperCase();
 if(id){shown=rows.filter(x=>x.r.id===id)}else{shown=rows.filter(x=>!fails(x.m,state.f).length&&(!state.pass||x.r.passed))}
 return {rows,shown,months,span,from,end,k}}
function cellOf(x,c,span,k){const r=x.r,m=x.m;const why=`<span class="muted">${esc(r.blank||"no trade in this window")}</span>`;
 switch(c){case"id":return `<span class="id">#${r.id}</span>`;case"family":return r.family;case"tf":return r.tf;case"filter":return r.filter;
  case"setting":return r.setting||why;case"verdict":return `<b class="${r.passed?"pos":"neg"}">${esc(r.verdict)}</b>`;
  case"profit":return m.trades?`<b class="${m.profit>0?"pos":"neg"}">${money(m.profit)}</b>`:why;
  case"target":return r.target?esc(r.target):why;case"stop":return r.stop?esc(r.stop):why;
  case"tp":return m.target!=null?pct(m.target):(m.trades?'<span class="muted">none (trailing stop)</span>':why);
  case"sl":return m.stop!=null?pct(m.stop):why;case"lev":return r.lev?`${r.lev[0]}x-${r.lev[1]}x`:why;
  case"trades":return m.trades;case"perday":return (m.trades/span).toFixed(2);case"wins":return m.trades?m.wins:why;
  case"losses":return m.trades?m.losses:why;case"win":return m.win!=null?m.win.toFixed(1)+"%":why;
  case"worst":return m.trades?(m.worstN?`${money(m.worst)} over ${m.worstN}`:"no losses"):why;
  case"green":return `${m.green}/${x.months.length}`;case"per":return m.trades?money(m.per):why;
  case"bar":return r.random[1]!=null?money(r.random[1]*k):why}}
function sortVal(x,c){const m=x.m,r=x.r;return {profit:m.profit,tp:m.target,sl:m.stop,trades:m.trades,perday:m.trades,wins:m.wins,
 losses:m.losses,win:m.win,worst:m.worst,green:m.green,per:m.per,bar:r.random[1]}[c]??String(r[c]??"")}
function render(){const v=view();v.shown.forEach(x=>x.months=v.months);
 const s=state.sort;v.shown.sort((a,b)=>{const p=sortVal(a,s.k),q=sortVal(b,s.k);if(p==null)return 1;if(q==null)return -1;
  return (typeof p==="number"&&typeof q==="number"?p-q:String(p).localeCompare(String(q)))*s.dir});
 $("thead").innerHTML="<tr>"+COLS.map(([c,l,left])=>`<th data-k="${c}" class="${left?"l":""}">${esc(l)}${s.k===c?(s.dir>0?" ▲":" ▼"):""}</th>`).join("")
  +v.months.map(m=>`<th>${MON[+m.slice(5)-1]} ${m.slice(0,4)} $</th>`).join("")+"</tr>";
 $("tbody").innerHTML=v.shown.map(x=>`<tr class="row" data-id="${x.r.id}">`+COLS.map(([c,_l,left])=>`<td class="${left?"l":""}">${cellOf(x,c,v.span,v.k)}</td>`).join("")
  +v.months.map(m=>{const p=x.m.months[m];return `<td class="${p>0?"pos":p<0?"neg":""}">${p==null?'<span class="muted">no trade</span>':money(p)}</td>`}).join("")+"</tr>").join("");
 const names=Object.entries(state.f).filter(([,val])=>val!=null).map(([key,val])=>({wr:`win ${val}%+`,pr:`profit ${money(val)}+`,gm:`${val}+ months green`,
  dd:`worst dip ${money(val)} or less`,tp:`TP ${val}% or less`,sl:`SL ${val}% or less`}[key]));
 if(state.pass)names.push("passed only");
 const idle=Object.entries(state.f).filter(([,val])=>val!=null).filter(([key])=>v.rows.every(x=>!fails(x.m,{[key]:state.f[key]}).length))
  .map(([key])=>`${{wr:"min win %",pr:"min profit $",gm:"min months green",dd:"max worst dip $",tp:"max TP %",sl:"max SL %"}[key]} cuts nothing here: every row already meets it`);
 const noTarget=state.f.tp!=null?v.rows.filter(x=>x.m.trades&&x.m.target==null).length:0;
 $("count").innerHTML=`<b>${v.shown.length}</b> of ${D.rows.length} judged groups`+(state.id?` · found by ID (the other filters are off)`:"")
  +(names.length&&!state.id?" · "+esc(names.join(" AND ")):"")
  +` · window ${fmtWhen((v.from??D.split/1000)*1000)} to ${fmtWhen(D.end)}`+(state.days?" (every row re-added from its trades that closed in it)":"")
  +` · at ${usd(state.risk)} risk a trade`+(state.risk!==D.risk?` (scaled from the ${usd(D.risk)} measured: at another risk some trades would be sized differently or be under one lot)`:"")
  +(noTarget?` · max TP % leaves out ${noTarget} row(s) whose trailing stop has no target`:"")+(idle.length?" · "+esc(idle.join("; ")):"");
 document.querySelectorAll("#thead th").forEach(th=>th.onclick=()=>{const k=th.dataset.k;if(!k)return;state.sort={k,dir:state.sort.k===k?-state.sort.dir:-1};render()});
 document.querySelectorAll("#tbody tr").forEach(tr=>tr.onclick=()=>open(tr.dataset.id));
 if(state.id&&v.shown.length===1)open(v.shown[0].r.id)}
function open(id){const v=view(),x=v.rows.find(y=>y.r.id===id);if(!x)return;const r=x.r,m=x.m;let run=0;
 const older=Object.entries(r.older).map(([s,[n,p,ok]])=>`${esc(s)}: ${n} older trades, ${p==null?"no trade":money(p*v.k)+" a trade"}${ok?"":" (too few to choose)"}`).join(" · ");
 $("dlg-body").innerHTML=`<h3><span class="id">#${r.id}</span> ${esc(r.family)} ${r.tf} ${esc(r.filter)} · ${esc(r.verdict)}</h3>
 <div class="sum"><span>TOTAL PROFIT <b class="total ${m.profit>0?"pos":"neg"}">${m.trades?money(m.profit):"$0.00"}</b></span>
 <span>${m.trades} trades · ${m.wins} won · ${m.losses} lost${m.win!=null?" · "+m.win.toFixed(1)+"%":""}</span>
 <span>worst losing run <b>${m.worstN?`${money(m.worst)} over ${m.worstN}`:"none"}</b></span></div>
 <p class="note">Setting ${esc(r.setting||"none chosen")} - ${esc(r.why)}. Older days: ${older||"no trades"}. Random runs: median ${money(r.random[0]==null?null:r.random[0]*v.k)}, bar ${money(r.random[1]==null?null:r.random[1]*v.k)} a trade (${r.random[2]??0} of ${r.random[3]??0} traded; their median ${r.rand_trades[0]??"-"} trades against the real run's ${r.rand_trades[1]??"-"}). Bootstrap low ${money(r.boot==null?null:r.boot*v.k)} a trade.
 Target: ${esc(r.target||"-")}. Stop: ${esc(r.stop||"-")}. Leverage ${r.lev?`${r.lev[0]}x-${r.lev[1]}x`:"-"}, ${r.notional?`${money(r.notional[0]*v.k)}-${money(r.notional[1]*v.k)} of coin a trade (margin = the coin bought ÷ its leverage)`:"no trade"}. ${r.notes.map(esc).join(" ")}</p>
 <div class="wrap"><table><thead><tr><th class="l">#</th><th class="l">Coin</th><th class="l">Side</th><th class="l">In</th><th class="l">Out</th><th class="l">Exit</th><th>SL %</th><th>TP %</th><th>Profit</th><th>Running</th></tr></thead><tbody>
 ${m.t.map((t,i)=>{const p=t[4]/1e4*v.k;run+=p;return `<tr><td class="l">${i+1}</td><td class="l">${esc(D.coins[t[0]])}</td><td class="l">${t[3]>0?"long":"short"}</td><td class="l">${fmtWhen(t[1]*1000)}</td><td class="l">${fmtWhen(t[2]*1000)}</td><td class="l">${D.whys[t[5]]}</td><td>${t[6]>=0?pct(t[6]/1e3):""}</td><td>${t[7]>=0?pct(t[7]/1e3):"none"}</td><td class="${p>0?"pos":"neg"}">${money(p)}</td><td>${money(run)}</td></tr>`}).join("")}
 </tbody></table></div>`;$("dlg").showModal()}
$("dlg-close").onclick=()=>$("dlg").close();
$("f-risk").value=D.risk;
for(const [el,key] of [["f-wr","wr"],["f-pr","pr"],["f-gm","gm"],["f-dd","dd"],["f-tp","tp"],["f-sl","sl"]])$(el).addEventListener("input",e=>{state.f[key]=num(e.target.value);render()});
$("f-risk").addEventListener("input",e=>{const v=num(e.target.value);state.risk=v&&v>0?v:D.risk;render()});
$("f-days").addEventListener("input",e=>{const v=num(e.target.value);state.days=v&&v>0?Math.floor(v):null;render()});
$("f-pass").addEventListener("change",e=>{state.pass=e.target.value;render()});
$("f-id").addEventListener("input",e=>{state.id=e.target.value.trim();render()});
$("clear").onclick=()=>{state.f={};state.days=null;state.pass="";state.id="";for(const el of ["f-wr","f-pr","f-gm","f-dd","f-tp","f-sl","f-days","f-id"])$(el).value="";$("f-pass").value="";render()};
const nj=Object.entries(D.not_judged).filter(([,v])=>v.length);
const NOTIONAL=D.rows.flatMap(r=>r.notional||[]);
$("h").textContent=D.coins.length<D.plan_coins?`Backtest v3 pilot - ${D.coins.length} of ${D.plan_coins} coins, not the proof`:`Backtest v3 verdicts - ${D.coins.length} coins`;
$("prov").innerHTML=`<b>${D.tried}</b> combinations tried (every family x setting x timeframe x filter), judged as ${D.rows.length} groups on <b>${D.coins.length}</b> of the plan's ${D.plan_coins} coins on ${esc(D.venue||"the exchange")}: each group's setting chosen on the older days ${fmtWhen(D.start)} to ${fmtWhen(D.split)}, judged on the unseen days to ${fmtWhen(D.end)} against ${D.runs} random runs (z ${D.z.toFixed(3)}). Every trade risks <b>${usd(D.risk)}</b> if its stop is hit: ${NOTIONAL.length?`each buys <b>${usd(Math.min(...NOTIONAL))}-${usd(Math.max(...NOTIONAL))}</b> of coin`:"no trade was bought"} at its own leverage (margin = the coin bought ÷ its leverage). Waiting-order entries, the idea's own exit, every fee, each minute's order book where one was recorded, funding. Judged ${fmtWhen(D.judged_at*1000)}; GitHub runs ${esc(Object.entries(D.github_runs).map(([a,n])=>a+" "+n).join(", "))}.`;
$("notes").innerHTML=nj.length?"Not judged: "+nj.map(([k,v])=>`${esc(k.replace(/_/g," "))}: ${v.length} (${esc(v.slice(0,8).join("; "))}${v.length>8?" ...":""})`).join(" · "):"Every coin of the plan was judged.";
render();
</script></body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run it, the date guards and the lint.**

Run: `.venv/Scripts/python -m pytest tests/test_v3_results_page.py -q`, then `.venv/Scripts/python -m pytest tests/test_webapp.py -k "date_format_is_exactly or formats_a_timestamp_by_hand" -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_results_page.py tests/test_v3_results_page.py`
Expected: 9 passed (scratch); the date guards pass; `All checks passed!`.

- [ ] **Step 5: Look at it in a browser.** Build a page from the test store (the scratch helper `mkpage.py` of this plan's proof: `tests.test_v3_verdicts.make_run` + `v3_verdicts.build` + `v3_results_page.build`) and open it headless with the repo's Playwright (`.claude/skills/practice_backtest_audit/scripts/node_modules/playwright-core`, Chrome channel) at 1280 px and 390 px: 27 rows, no console error, no sideways scroll; `Max SL %` 0.7 keeps the snap row and 0.69 leaves 0 with "SL 0.69% or less" named in the count; `Last N days` 30 shows only the Sep and Oct month columns; risk 10 doubles every dollar and says "scaled from the $5.00 measured"; a row click opens its 400-trade log under a TOTAL PROFIT that equals the row's PROFIT. (Proven so in scratch, Oct 27, 2026.)

- [ ] **Step 6: Commit and push.**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_results_page.py tests/test_v3_results_page.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
feat(v3): the Backtest v3 results page (python -m tradingagents.v3_results_page <name>) - every judged group a row with every field and its stable id first, worked out in the page from its trades, the risk box, max TP % / max SL % as inclusive ceilings, last N days re-adding each row from the trades that closed in it, find by ID, sortable, the trade log with TOTAL PROFIT - Part 2b, Task 5

harddev: the row's profit adds up to its verdict to the cent; a trailing stop's row leaves any max TP % and says so; a group that chose nothing carries every field with why; dates through the page's fmtWhen, held equal to fmt_when under node.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 6: COVERAGE FIRST - the check on a run's records, and the order-book backfill

**Files:**
- Create: `tradingagents/v3_coverage.py`
- Test: `tests/test_v3_coverage.py`

**Interfaces:**
- Consumes: Task 3's `v3_cloud.load_state / home`; a landed run's records (`pre.coverage_older/unseen`, each walk's `counts`); `costs_daily.read()` (`done_days`, `flight`), `costs_daily.BACKFILL_DAYS`; `cloud_sweep.usable_fleets / split_coins / sync_fleet`; `forecast_v2_daily.dispatch / run_status / _gh`; the existing `costs.yml` (inputs `shards, days, coin_list, label`).
- Produces: `trade_costs(records)`, `minute_cover(records)`, `missing_days(plan, done) -> [UTC day keys]`, `done_days() -> set`, `costs_speed(runs, *, gh=None) -> {"runs", "machine_s", "coin_days", "s_per_coin_day"}`, `estimate(coin_days, s_per_coin_day, machines) -> {"machine_hours", "wall_hours", "machines"} | None`, `report(name, *, runs=None, machines=60) -> [lines]`, `clash(days, now) -> str`, `backfill(name, *, days_per_press=30, now=None, force=False)`, `settle()`; state `cloud/backfill.json` `{flight?, done_days, presses, last_error}`.

- [ ] **Step 1: Write the failing test** `tests/test_v3_coverage.py`:

```python
"""COVERAGE FIRST for Backtest v3 (tradingagents/v3_coverage.py, Part 2b): the
share of a run's trades that paid a typical cost instead of their minute's own
book, older and unseen days apart; the plan's days the cost store does not
hold; the backfill's time at the speed the costs job's own runs measured; and
the backfill press - the existing costs job, dealt between every account, one
press at a time, never beside the daily costs job on a month file it writes."""
from __future__ import annotations

import calendar
import json
from types import SimpleNamespace

import pytest

from tradingagents import (
    cloud_sweep as cs,
    costs_daily,
    forecast_v2_daily as fd,
    v3_cloud as vc,
    v3_coverage as vcv,
    v3_research as vrs,
    v3_universe as vu,
)
from tradingagents.positions_view import fmt_when

DAY = 86_400


def _utc(y, m, d, h=0):
    return calendar.timegm((y, m, d, h, 0, 0))


def _walk(trades, **counts):
    return {"rows": [[0, 0, 0, 1, 0.1, "SL", 0.01, None]] * trades, "counts": counts}


def _rec(coin, plan, older, unseen, cov_older, cov_unseen):
    return {"coin": coin, "plan_id": plan["id"], "pre": {"coverage_older": cov_older,
                                                         "coverage_unseen": cov_unseen},
            "combos": {"a": {"older": older, "unseen": unseen}}}


@pytest.fixture()
def world(monkeypatch, tmp_path):
    monkeypatch.setattr(vc, "home", lambda: tmp_path / "cloud")
    monkeypatch.setattr(vrs, "home", lambda label="local": tmp_path / "research"
                        / vrs.plain_label(label))
    (tmp_path / "cloud").mkdir()
    # a ten-day plan, Oct 01 - Oct 11, 2026, of three coins
    plan = {"version": vu.VERSION, "start_ms": _utc(2026, 10, 1) * 1000,
            "end_ms": _utc(2026, 10, 11) * 1000, "coins": ["BTC_USDT", "XAU_USDT", "ZEC_USDT"]}
    plan["id"] = vu.plan_id(plan)
    copy = vu.save(plan, tmp_path / "cloud" / "pilot.plan.json")
    (tmp_path / "cloud" / "pilot.json").write_text(json.dumps(
        {"folder": "pilot", "plan_copy": str(copy), "plan_id": plan["id"]}), encoding="utf-8")
    folder = vrs.home("pilot")
    vrs.save_coin(folder, _rec("BTC_USDT", plan, _walk(40, cost_unmeasured=40, missed=5,
                                                       placement_unmeasured=45),
                               _walk(10, cost_unmeasured=2, post_only_reject=3,
                                     funding_estimated=1), 0.0, 0.8))
    vrs.save_coin(folder, _rec("XAU_USDT", plan, _walk(60, cost_unmeasured=60),
                               _walk(30, cost_unmeasured=3), 0.0, 0.9))
    flights = {"daily": {}}
    monkeypatch.setattr(costs_daily, "read", lambda: flights["daily"])
    return SimpleNamespace(plan=plan, tmp=tmp_path, flights=flights)


def test_the_share_of_trades_that_paid_a_typical_cost_is_counted_older_and_unseen_apart(world):
    recs = vrs.load_coins(vrs.home("pilot"))
    got = vcv.trade_costs(recs)
    assert got["older"] == {"trades": 100, "typical_exits": 100, "orders": 105,
                            "unchecked_orders": 45, "funding_estimated": 0}
    assert got["unseen"] == {"trades": 40, "typical_exits": 5, "orders": 43,
                             "unchecked_orders": 0, "funding_estimated": 1}
    cover = vcv.minute_cover(recs)
    assert cover["older"] == {"mean": 0.0, "least": 0.0, "none": ["BTC_USDT", "XAU_USDT"],
                              "coins": 2}
    assert cover["unseen"]["mean"] == pytest.approx(0.85) and cover["unseen"]["none"] == []


def test_the_missing_days_are_every_window_day_the_store_does_not_hold(world):
    done = ["2026-10-08", "2026-10-09", "2026-10-10", "2026-10-11"]
    assert vcv.missing_days(world.plan, done) == [f"2026-10-0{d}" for d in range(1, 8)]


def test_the_speed_is_the_costs_jobs_own_machine_seconds_per_coin_day():
    runs = {11: {"displayTitle": "Costs per minute · 2026-10-26 · jeremydevera 353 coins",
                 "conclusion": "success",
                 "jobs": [{"name": "plan", "startedAt": "2026-10-27T03:00:00Z",
                           "completedAt": "2026-10-27T03:00:20Z"}]
                 + [{"name": f"costs ({k})", "startedAt": "2026-10-27T03:01:00Z",
                     "completedAt": "2026-10-27T03:04:31Z"} for k in range(20)]},
            12: {"displayTitle": "Costs per minute · 2026-09-01,2026-09-02 · v3 backfill "
                                 "jeremydvera 10 coins", "conclusion": "success",
                 "jobs": [{"name": "costs (0)", "startedAt": "2026-10-27T10:00:00Z",
                           "completedAt": "2026-10-27T10:10:00Z"}]},
            13: {"displayTitle": "Costs per minute · 2026-10-25 · x 353 coins",
                 "conclusion": "failure", "jobs": []}}
    gh = lambda *a, **k: json.dumps(runs[int(a[2])])          # noqa: E731
    got = vcv.costs_speed([("a/x", 11), ("b/x", 12), ("a/x", 13)], gh=gh)
    # 20 machines x 211 s + one of 600 s, over 353 x 1 + 10 x 2 coin-days; the red run is no
    # measurement and the dealing job is no work
    assert got == {"runs": 2, "machine_s": 20 * 211 + 600, "coin_days": 373,
                   "s_per_coin_day": round((20 * 211 + 600) / 373, 1)}
    assert vcv.estimate(66_804, 12.9, 60) == {"machine_hours": 239.4, "wall_hours": 4.0,
                                              "machines": 60}
    assert vcv.estimate(10, None, 60) is None


def test_the_report_says_coverage_first_with_every_number_from_the_records(world, monkeypatch):
    monkeypatch.setattr(vcv, "costs_speed", lambda runs: {"runs": 2, "machine_s": 4820,
                                                          "coin_days": 373,
                                                          "s_per_coin_day": 12.9})
    world.flights["daily"] = {"done_days": ["2026-10-09", "2026-10-10"]}
    lines = vcv.report("pilot", runs=[("a/x", 11)], machines=60)
    assert lines[0] == f"COVERAGE FIRST for pilot: 2 coins measured under plan {world.plan['id']}"
    assert "100 of 100 trades exited at a typical cost (100.0%)" in lines[1]
    assert "2 of 2 coins have none" in lines[1]
    assert "5 of 40 trades exited at a typical cost (12.5%)" in lines[2]
    # the days printed in the project's one date format, from the first missing day's start to
    # the last one's end
    assert lines[3] == ("  the cost store holds no reading for 8 of the window's days (UTC days "
                        f"from {fmt_when(_utc(2026, 10, 1))} to {fmt_when(_utc(2026, 10, 9))}): "
                        "24 coin-days for the plan's 3 coins")
    assert "about 0.1 machine-hours, at least 0.0 hours of all 60 machines" in lines[4]


def test_a_backfill_press_never_runs_beside_the_daily_costs_job_on_its_months(world):
    world.flights["daily"] = {"flight": {"at": 1}}
    now = _utc(2026, 10, 27, 12)
    assert vcv.clash(["2025-11-03"], now) == "the daily costs job has a run in the air"
    world.flights["daily"] = {}
    three_am = _utc(2026, 10, 27, 3)
    assert vcv.clash(["2026-08-10"], three_am).startswith("between 02:00 and 08:59 UTC")
    assert vcv.clash(["2025-11-03"], three_am) == "", "a month the daily job never writes"
    assert vcv.clash(["2026-08-10"], now) == "", "outside the daily job's hours"


def test_the_backfill_presses_the_newest_missing_days_for_the_plans_coins(world, monkeypatch):
    sent = []
    monkeypatch.setattr(cs, "usable_fleets", lambda: (["a/x", "b/x"], []))
    monkeypatch.setattr(cs, "sync_fleet", lambda slug: "")

    def dispatch(wf, inputs, slug, since=None):
        assert vcv.read_state()["flight"]["days"], "the press is saved before the dispatch"
        sent.append((wf, slug, dict(inputs)))
        return 500 + len(sent)

    monkeypatch.setattr(fd, "dispatch", dispatch)
    # noon UTC (outside the daily costs job's hours); `force` because the nightly quiet hours are
    # this PC's own clock, which a test cannot know
    now = _utc(2026, 10, 27, 12)
    got = vcv.backfill("pilot", days_per_press=3, now=now, force=True)
    assert got["days"] == ["2026-10-08", "2026-10-09", "2026-10-10"], "newest first"
    assert [s[:2] for s in sent] == [("costs.yml", "a/x"), ("costs.yml", "b/x")]
    assert sorted(c for _w, _s, i in sent for c in i["coin_list"].split(",")) == \
        world.plan["coins"]
    assert all(i["days"] == "2026-10-08,2026-10-09,2026-10-10" for _w, _s, i in sent)
    with pytest.raises(RuntimeError, match="still in the air"):
        vcv.backfill("pilot", now=now, force=True)
    # one share red: the days go back, named; then both green: the days are done
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {
        "status": "completed", "conclusion": "failure" if run == 502 else "success"})
    assert vcv.settle()["red"] == ["b/x (run 502): failure"]
    assert not vcv.read_state().get("done_days")
    vcv.backfill("pilot", days_per_press=3, now=now, force=True)
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed",
                                                             "conclusion": "success"})
    assert vcv.settle()["red"] == []
    assert vcv.read_state()["done_days"] == ["2026-10-08", "2026-10-09", "2026-10-10"]
    assert vcv.backfill("pilot", days_per_press=3, now=now, force=True)["days"] == \
        ["2026-10-05", "2026-10-06", "2026-10-07"]
```

- [ ] **Step 2: Run it to see it fail.**

Run: `.venv/Scripts/python -m pytest tests/test_v3_coverage.py -q`
Expected: `ImportError: cannot import name 'v3_coverage' from 'tradingagents'`.

- [ ] **Step 3: Write** `tradingagents/v3_coverage.py`:

```python
"""COVERAGE FIRST for Backtest v3 (Part 2b, Oct 27, 2026): how much of a run's
trading paid a typical cost instead of its own minute's order book, and what
filling the missing order books would take - the decision the operator makes
before the whole universe runs (CLAUDE.md "Every backtest LOOKS AT THE COSTS of
every minute it tests": COVERAGE FIRST, fill or say so BEFORE running).

    python -m tradingagents.v3_coverage report <name>
    python -m tradingagents.v3_coverage backfill [--days-per-press 30] [--force]
    python -m tradingagents.v3_coverage settle

* `report` reads a collected run's records (the pilot's): the share of the
  minutes the books cover, per coin, older and unseen days apart; of every
  combination's trades, the exits that paid the coin's usual cost
  (`cost_unmeasured`) and the orders placed with no book to check post-only
  against (`placement_unmeasured`), older and unseen apart; the plan's days
  the cost store holds no reading for (the daily costs job's `done_days`, and
  this module's own backfilled days); and the measured time to fill them, at
  the speed the costs job's own runs measured (`costs_speed`: machine-seconds
  per coin-day, from each run's jobs' start and end).
* `backfill` presses `costs.yml` - the existing order-book replay, the same
  job, files and readers - for the plan's coins over the next
  `--days-per-press` missing days, newest first, dealt between every account
  (the 60-machine rule). One press at a time; `settle` marks a press's days
  done only when every share finished green, as `costs_daily` does. It never
  presses while the daily costs job has a run in the air, nor in the hours it
  presses (02:00-08:59 UTC) for a month that job also writes: two runs adding
  to one month file on one account would keep only one of them.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

DAY_S = 86_400
DAYS_PER_PRESS = 30
# the daily costs job presses at 03:00 and 07:00 UTC (costs_daily.READY_HOUR_UTC, TODAY_HOUR_UTC);
# a backfill of a month it also writes keeps clear of 02:00-08:59 UTC
DAILY_HOURS_UTC = range(2, 9)


def state_path() -> Path:
    from tradingagents import v3_cloud as vc

    return vc.home() / "backfill.json"


def read_state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(st: dict) -> None:
    p = state_path()
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    tmp.replace(p)


def _day(s: float) -> str:
    """A UTC day's KEY, the form costs.yml takes ("2026-10-01") - never printed:
    a printed day goes through `fmt_when` (CLAUDE.md "Date format")."""
    g = time.gmtime(int(s))
    return f"{g.tm_year:04d}-{g.tm_mon:02d}-{g.tm_mday:02d}"


def _start_of(key: str) -> int:
    """The first second of a UTC day KEY."""
    import calendar

    y, m, d = (int(x) for x in key.split("-"))
    return calendar.timegm((y, m, d, 0, 0, 0))


def trade_costs(records: list[dict]) -> dict:
    """Over every combination's walks of every record, older and unseen apart:
    {part: {"trades", "typical_exits" (cost_unmeasured), "orders" (trades +
    missed + post-only rejected), "unchecked_orders" (placement_unmeasured),
    "funding_estimated"}}."""
    out = {p: dict.fromkeys(("trades", "typical_exits", "orders", "unchecked_orders",
                             "funding_estimated"), 0) for p in ("older", "unseen")}
    for rec in records:
        for combo in rec.get("combos", {}).values():
            for part in ("older", "unseen"):
                w = combo.get(part) or {}
                c, n = w.get("counts") or {}, len(w.get("rows") or [])
                o = out[part]
                o["trades"] += n
                o["typical_exits"] += int(c.get("cost_unmeasured", 0))
                o["orders"] += n + int(c.get("missed", 0)) + int(c.get("post_only_reject", 0))
                o["unchecked_orders"] += int(c.get("placement_unmeasured", 0))
                o["funding_estimated"] += int(c.get("funding_estimated", 0))
    return out


def minute_cover(records: list[dict]) -> dict:
    """The books' share of each coin's minutes, older and unseen apart: the
    mean over the coins, the least, and the coins with none on the older days."""
    out = {}
    for part in ("older", "unseen"):
        got = {r["coin"]: float((r.get("pre") or {}).get(f"coverage_{part}") or 0.0)
               for r in records if r.get("pre")}
        out[part] = {"mean": statistics.fmean(got.values()) if got else None,
                     "least": min(got.values()) if got else None,
                     "none": sorted(c for c, v in got.items() if v == 0.0), "coins": len(got)}
    return out


def missing_days(plan: dict, done) -> list[str]:
    """The UTC days of the plan's window ([start, end)) the cost store holds no
    replayed reading for, oldest first: every day but those in `done`."""
    start, end = int(plan["start_ms"]) // 1000, int(plan["end_ms"]) // 1000
    have = set(done or ())
    return [d for d in (_day(t) for t in range(start - start % DAY_S, end, DAY_S))
            if d not in have]


def done_days() -> set:
    """Every day the cost store holds for every coin: the daily costs job's
    and this module's backfilled ones."""
    from tradingagents import costs_daily

    return set(costs_daily.read().get("done_days") or []) | set(read_state().get("done_days")
                                                                 or [])


def costs_speed(runs: list[tuple[str, int]], *, gh=None) -> dict:
    """The costs job's measured speed from its own green runs [(repo, run id)]:
    machine-seconds (each job's start to end, the dealing job left out) per
    coin-day (coins x days the run's title names: "Costs per minute · <days> ·
    ... <N> coins", the daily press's label or a backfill's)."""
    import datetime as dt
    import re

    from tradingagents import forecast_v2_daily as fd

    gh = gh or fd._gh

    def ts(x):
        return dt.datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()

    secs = coin_days = used = 0
    for repo, run in runs:
        d = json.loads(gh("run", "view", str(run), "--repo", repo, "--json",
                          "displayTitle,conclusion,jobs"))
        m = re.match(r"Costs per minute · ([0-9,\-]+) · .*?(\d+) coins$",
                     d.get("displayTitle", ""))
        if d.get("conclusion") != "success" or not m:
            continue
        jobs = [j for j in d.get("jobs") or [] if j.get("name") != "plan"
                and j.get("startedAt") and j.get("completedAt")]
        secs += sum(ts(j["completedAt"]) - ts(j["startedAt"]) for j in jobs)
        coin_days += int(m.group(2)) * len(m.group(1).split(","))
        used += 1
    return {"runs": used, "machine_s": round(secs), "coin_days": coin_days,
            "s_per_coin_day": round(secs / coin_days, 1) if coin_days else None}


def estimate(coin_days: int, s_per_coin_day: float | None, machines: int) -> dict | None:
    """Machine-hours and the wall-clock hours of `machines` machines at the
    measured speed (the least it can take: the work spread perfectly)."""
    if not s_per_coin_day or machines < 1:
        return None
    hours = coin_days * s_per_coin_day / 3600
    return {"machine_hours": round(hours, 1), "wall_hours": round(hours / machines, 1),
            "machines": machines}


def report(name: str, *, runs: list[tuple[str, int]] | None = None,
           machines: int = 60) -> list[str]:
    """COVERAGE FIRST's lines for the collected run `name` (see the module doc)."""
    from tradingagents import v3_cloud as vc, v3_research as vrs, v3_universe as vu
    from tradingagents.positions_view import fmt_when

    state = vc.load_state(name)
    plan = vu.load(state["plan_copy"])
    records = [r for r in vrs.load_coins(vrs.home(state["folder"]))
               if r.get("plan_id") == plan["id"]]
    cost, cover = trade_costs(records), minute_cover(records)
    missing = missing_days(plan, done_days())
    coins = len(plan["coins"])
    lines = [f"COVERAGE FIRST for {name}: {len(records)} coins measured under plan {plan['id']}"]
    for part, words in (("older", "older days"), ("unseen", "unseen days")):
        c, m = cost[part], cover[part]
        share = c["typical_exits"] / c["trades"] if c["trades"] else None
        lines.append(
            f"  {words}: the books cover {_pct(m['mean'])} of a coin's minutes on average (the "
            f"least {_pct(m['least'])}; {len(m['none'])} of {m['coins']} coins have none); "
            f"{c['typical_exits']:,} of {c['trades']:,} trades exited at a typical cost "
            f"({_pct(share)}); {c['unchecked_orders']:,} of {c['orders']:,} orders went in "
            f"with no book to check post-only against; funding estimated on "
            f"{c['funding_estimated']:,} trades")
    if not missing:
        lines.append("  the cost store holds every day of the plan's window: nothing to fill")
        return lines
    lines.append(f"  the cost store holds no reading for {len(missing)} of the window's days "
                 f"(UTC days from {fmt_when(_start_of(missing[0]))} to "
                 f"{fmt_when(_start_of(missing[-1]) + DAY_S)}): {len(missing) * coins:,} "
                 f"coin-days for the plan's {coins} coins")
    if runs:
        sp = costs_speed(runs)
        est = estimate(len(missing) * coins, sp["s_per_coin_day"], machines)
        if est:
            lines.append(f"  the costs job measured {sp['s_per_coin_day']} machine-seconds a "
                         f"coin-day over {sp['runs']} of its runs ({sp['coin_days']:,} "
                         f"coin-days): filling them is about {est['machine_hours']:,} "
                         f"machine-hours, at least {est['wall_hours']} hours of all "
                         f"{machines} machines")
        else:
            lines.append("  no green costs run could be read to measure the speed")
    return lines


def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def clash(days: list[str], now: float) -> str:
    """Why a backfill press of `days` may not go now, or "": the daily costs
    job has a run in the air, or it is within its pressing hours and one of
    the days is in a month it writes (its last BACKFILL_DAYS)."""
    from tradingagents import costs_daily

    if costs_daily.read().get("flight"):
        return "the daily costs job has a run in the air"
    daily = {_day(now - k * DAY_S)[:7] for k in range(costs_daily.BACKFILL_DAYS + 1)}
    if time.gmtime(int(now)).tm_hour in DAILY_HOURS_UTC and any(d[:7] in daily for d in days):
        return ("between 02:00 and 08:59 UTC the daily costs job writes the months "
                + ", ".join(sorted(daily)) + ": a press of the same month file would lose one "
                                             "of the two runs' days")
    return ""


def backfill(name: str, *, days_per_press: int = DAYS_PER_PRESS, now: float | None = None,
             force: bool = False) -> dict:
    """Press costs.yml for the plan's coins over the next missing days, newest
    first, dealt between every account; one press at a time."""
    from tradingagents import (
        cloud_sweep as cs,
        cq_search,
        forecast_v2_daily as fd,
        v3_cloud as vc,
        v3_universe as vu,
    )

    now = time.time() if now is None else float(now)
    st = read_state()
    if st.get("flight"):
        raise RuntimeError("a backfill press is still in the air: python -m "
                           "tradingagents.v3_coverage settle")
    if cq_search.quiet_hours(now) and not force:
        raise RuntimeError("not pressed: between 12:45am and 5:00am the nightly jobs need every "
                           "machine")
    plan = vu.load(vc.load_state(name)["plan_copy"])
    days = missing_days(plan, done_days())[-int(days_per_press):]
    if not days:
        return {"started": False, "why": "every day of the plan's window is in the cost store"}
    why = clash(days, now)
    if why:
        raise RuntimeError(f"not pressed: {why}")
    ready, refused = cs.usable_fleets()
    if not ready:
        raise RuntimeError("no GitHub account can run the costs job: " + "; ".join(refused))
    piles = cs.split_coins(list(plan["coins"]), len(ready))
    st["flight"] = {"at": now, "days": days, "runs": [], "unrun": list(refused)}
    _write_state(st)                   # BEFORE the dispatch, as every dispatcher here
    for slug, pile in zip(ready, piles, strict=False):
        drift = cs.sync_fleet(slug)
        if drift:
            st["flight"]["unrun"].append(f"{slug}: {len(pile)} coins never ran ({drift})")
            continue
        inputs = {"shards": "20", "days": ",".join(days), "coin_list": ",".join(pile),
                  "label": f"v3 backfill {slug.split('/')[0]} {len(pile)} coins"}
        try:
            st["flight"]["runs"].append({"repo": slug, "coins": len(pile),
                                         "run": int(fd.dispatch("costs.yml", inputs, slug))})
        except Exception as exc:                               # noqa: BLE001
            st["flight"]["unrun"].append(f"{slug}: {str(exc)[:160]}")
        _write_state(st)
    return {"started": bool(st["flight"]["runs"]), "days": days, **st["flight"]}


def settle() -> dict:
    """Mark the press in the air done when every share finished green; give
    its days back, named, when one is red or never ran."""
    from tradingagents import forecast_v2_daily as fd

    st = read_state()
    fl = st.get("flight")
    if not fl:
        return {"settled": False, "why": "no backfill press in the air"}
    got = [(r, fd.run_status(int(r["run"]), r["repo"])) for r in fl["runs"]]
    if any(g.get("status") != "completed" for _r, g in got):
        return {"settled": False, "why": "still running"}
    red = [f"{r['repo']} (run {r['run']}): {g.get('conclusion')}" for r, g in got
           if g.get("conclusion") != "success"] + list(fl.get("unrun") or [])
    if red:
        st["last_error"] = "not every share finished green: " + "; ".join(red)
    else:
        st["done_days"] = sorted(set(st.get("done_days") or []) | set(fl["days"]))
        st["last_error"] = ""
        st.setdefault("presses", []).append({"days": fl["days"], "runs": fl["runs"]})
    st.pop("flight")
    _write_state(st)
    return {"settled": True, "red": red, "days": fl["days"]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_coverage")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("name")
    r.add_argument("--speed-runs", default="",
                   help="costs.yml runs to measure the speed on: owner/repo:run,...")
    b = sub.add_parser("backfill")
    b.add_argument("name")
    b.add_argument("--days-per-press", type=int, default=DAYS_PER_PRESS)
    b.add_argument("--force", action="store_true")
    sub.add_parser("settle")
    a = p.parse_args(argv)
    if a.cmd == "report":
        runs = [(x.rsplit(":", 1)[0], int(x.rsplit(":", 1)[1]))
                for x in a.speed_runs.split(",") if x]
        print("\n".join(report(a.name, runs=runs or None)))
    elif a.cmd == "backfill":
        print(json.dumps(backfill(a.name, days_per_press=a.days_per_press, force=a.force),
                         indent=1))
    else:
        print(json.dumps(settle(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run it and the daily costs job's own tests.**

Run: `.venv/Scripts/python -m pytest tests/test_v3_coverage.py tests/test_costs_daily.py tests/test_cost_store.py tests/test_cost_coverage.py -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_coverage.py tests/test_v3_coverage.py`
Expected: all pass (`test_v3_coverage.py` 6 in scratch); `All checks passed!`.

- [ ] **Step 5: Commit and push.**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_coverage.py tests/test_v3_coverage.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
feat(v3): COVERAGE FIRST (python -m tradingagents.v3_coverage report | backfill | settle) - the share of a run's trades that paid a typical cost, older and unseen days apart, the plan's days the cost store does not hold, the backfill's time at the costs job's own measured speed, and the backfill press: the existing costs.yml for the plan's coins, newest days first, dealt between every account - Part 2b, Task 6

CLAUDE.md "Every backtest LOOKS AT THE COSTS of every minute it tests": the store held every coin's book from Aug 16, 2026 only, so the older days paid 100% typical costs in Part 2a's check.

harddev: one press at a time, its days done only when every share is green; never beside the daily costs job on a month file it writes; day keys never printed (fmt_when).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 7: Write the rules down

**Files:**
- Modify: `CLAUDE.md` (a new MANDATORY section directly after "## Backtest v3 Part 2a — the families and the proof test", before "## The daytime rule")
- Modify: `docs/superpowers/specs/2026-10-22-backtest-v3-design.md` (line 3, the status)

- [ ] **Step 1: Add the CLAUDE.md section.** Check `git diff HEAD -- CLAUDE.md` first (other sessions edit it). Insert, after Part 2a's `Guards:` paragraph:

```markdown
## Backtest v3 Part 2b — on GitHub, judged, kept and shown (MANDATORY — Oct 27, 2026)

The operator: *"go"* (Oct 27, 2026). Plan:
`docs/superpowers/plans/2026-10-27-backtest-v3-part2b-github.md`.

* **One plan per run, and it travels by id.** `python -m
  tradingagents.v3_cloud dispatch <name>` sends `research/v3/plan.json`'s id
  as v3.yml's `plan_id` only when that file is the one on origin/main; a
  machine whose checkout holds another plan, or that is not on Gate,
  measures nothing (exit 2, named). The plan as dispatched is kept
  (`cloud/<name>.plan.json`) and the run is judged under it, never under a
  rebuilt file.
* **Every account, every machine** (`split_coins` over `fleets_now`, forks
  synced first); a refused share is redone alone (`redo`, a late-listed run
  adopted); the state is saved before the first dispatch.
* **The machine is Part 2a's measurement, nothing else**
  (`.github/scripts/v3_shard.py`): `measure_coin` per claimed coin at
  `v3_rules.RESEARCH_RISK_USD` ($5) and `v3_random.RUNS`, one record per
  coin stamped with its machine; a failed coin redone alone
  (`COIN_RETRIES`), named if it never recovers; `sweep_shard` imported with
  `RES` popped.
* **Collect lands only this run's records** (`stores.V3.home/research/
  <name>`, on G:): another plan, risk or run count is refused with what
  differs, a folder of another plan is never landed into, a coin that
  failed loses its old record first, and every coin not landed is NAMED
  (not reached, failed, left out by the machine, refused). `retry` redoes
  only the failed and unreached coins, into the same folder.
* **The verdict store** (`python -m tradingagents.v3_verdicts publish
  <name>`): Part 2a's own judge, pooled; `stores.V3.home/verdicts.json` for
  the tab, a kept copy per publish in `verdicts/` (nothing deletes one),
  every verdict with its chosen setting's stop and target sizes
  (`levels`) and every coin of the plan not judged, by why. The tab lists it
  with the kit's columns; a store judged on fewer coins than its plan holds
  is headed "Pilot ... not the proof".
* **The results page** (`python -m tradingagents.v3_results_page <name>`):
  the 27 judged groups, id first, worked out in the page from each group's
  pooled unseen trades - the risk box rescales (scaled from the $5 measured,
  said), last N days re-adds each row from its trades that closed in the
  window (said: no minutes ride in a page), max TP % / max SL % are inclusive
  ceilings on each row's median target and stop (a trailing stop has no
  target and leaves any max TP %, said), find by ID, the trade log with
  TOTAL PROFIT.
* **Each trade row keeps its opening stop and target** (record version 2),
  and the older walk pays the older days' own flat gap once they have
  readings; Part 2a's judge reads the first six fields only.
* **COVERAGE FIRST before the universe** (`python -m
  tradingagents.v3_coverage report <name>`): the typical-cost share of the
  older and the unseen days, the plan's days the cost store does not hold,
  and the backfill's time at the costs job's own measured speed; `backfill`
  presses the existing costs.yml for the plan's coins, newest days first, one
  press at a time, never beside the daily costs job on a month it writes.

Guards: `tests/test_v3_shard.py`, `tests/test_v3_cloud.py`,
`tests/test_v3_verdicts.py`, `tests/test_v3_results_page.py`,
`tests/test_v3_coverage.py`, and the Part 2b tests at the end of
`tests/test_v3_engine.py` and `tests/test_v3_measure.py`.
```

- [ ] **Step 2: Update the spec's status line** (line 3 of `docs/superpowers/specs/2026-10-22-backtest-v3-design.md`): append `; Part 2b, the GitHub run, the verdict store, the tab's list, the results page and COVERAGE FIRST, is built (plan docs/superpowers/plans/2026-10-27-backtest-v3-part2b-github.md)` before the line's end.

- [ ] **Step 3: Run every file this plan touched, once** (check first that no other pytest is running):

Run: `.venv/Scripts/python -m pytest tests/test_v3_*.py tests/test_backtest_v3_*.py tests/test_cost_store.py tests/test_cost_coverage.py tests/test_one_door_to_the_exchange.py tests/test_every_workflow_names_the_exchange.py tests/test_ci_scripts_use_names_that_exist.py tests/test_cq_search.py tests/test_forecast_v2.py tests/test_costs_daily.py tests/test_forty_machines_across_two_accounts.py tests/test_the_backend_names_the_exchange.py "tests/test_auto_trader.py::test_nothing_is_defined_after_the_runner_entry_point" -q`
Expected: 527 passed and 1 failed - `test_no_printed_string_spells_mexc` on another session's `app_books.py:470`, which fails before this plan too; check that its message names that line and nothing of this plan's files.

- [ ] **Step 4: Commit and push.**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> CLAUDE.md docs/superpowers/specs/2026-10-22-backtest-v3-design.md
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
docs(claude): Backtest v3 Part 2b's rules - one plan per run by id, every account, the machine is Part 2a's measurement, collect lands only this run's records and names the rest, the verdict store kept per publish, the results page's kit, COVERAGE FIRST before the universe

Backtest v3 Part 2b, Task 7. The spec's status line says Part 2b is built.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 8: The runbook - plan, pilot, coverage, the operator's go, the universe, the page

Not code: the controller runs these steps in order, one at a time, never between 12:45am and 5:00am (this PC's clock). Every command reads the exchange's public data or GitHub only; none places an order. Record each step's outcome in the build ledger appended to this plan.

- [ ] **Step 1: Rebuild the plan and commit it.** `.venv/Scripts/python -m tradingagents.v3_research plan` (about 6 minutes; prints the window, the groups and every left-out and skipped coin - a coin skipped by a 429 is a reason to build again, not to dispatch). Check `git diff HEAD -- research/v3/plan.json`, commit it alone (`commit_own`, message naming its id, window, months and coin counts), push to all three remotes.
- [ ] **Step 2: The pilot.** `.venv/Scripts/python -m tradingagents.v3_cloud dispatch pilot --coins BTC_USDT,ETH_USDT,SOL_USDT,XRP_USDT,DOGE_USDT,BNB_USDT,LINK_USDT,ADA_USDT,ZEC_USDT,PEPE_USDT,FARTCOIN_USDT,HYPE_USDT,TAO_USDT,龙虾_USDT,XAU_USDT,XAG_USDT,XPT_USDT,EURUSD_USDT,SPX500_USDT,NAS100_USDT` (Decision 2; a coin the new plan no longer holds is refused by name - replace it with the next coin of its kind and say which). Expect three runs, 7 / 7 / 6 machines. A share named in `refused`: `redo pilot <owner/repo>`.
- [ ] **Step 3: Measure this PC's twin while the machines run.** `.venv/Scripts/python -m tradingagents.v3_research run XAU_USDT --label parity` (about 150 s), started within the hour of the pilot (the minutes' REST week moves with the clock).
- [ ] **Step 4: Collect, and read what it says.** When every run is completed: `.venv/Scripts/python -m tradingagents.v3_cloud collect pilot`. Read: `landed` (20 expected), every `failed` / `not_reached` / `left_out` / `machines_refused` line (each needs a reason before going on; `retry pilot` for failed or unreached), `seconds` (median and max a coin on GitHub - the universe's time, see Sizing), `bytes` (the universe's artifact size is about 228 / 20 of it).
- [ ] **Step 5: Parity.** `.venv/Scripts/python -m tradingagents.v3_cloud parity pilot XAU_USDT parity` must say "the same measurement". A difference names its fields: one only in `pre.five_minute` or `pre.minutes` (the REST week) is named in the ledger and explained before going on; any difference in a walk's rows is a stop - GitHub must measure what this PC measures.
- [ ] **Step 6: COVERAGE FIRST, measured.** Press ONE backfill of the unseen gap for the pilot window: `.venv/Scripts/python -m tradingagents.v3_coverage backfill pilot --part unseen --days-per-press <the gap's days, 17 for a plan built Oct 28, 2026>` (`--part unseen` keeps the press inside the unseen days: without it the newest missing days of the WHOLE window are the gap only while no other day is missing) - it fills the plan's coins, which the universe run needs anyway. When `settle` says settled: `.venv/Scripts/python -m tradingagents.v3_coverage report pilot --speed-runs <each run of that press, owner/repo:run>` prints the typical-cost share of the older and unseen days, the days still missing and the measured hours to fill them. Publish the pilot's verdicts so the tab shows them as a pilot: `.venv/Scripts/python -m tradingagents.v3_verdicts publish pilot`.
- [ ] **Step 7: The operator's go.** Put to the operator, in one short message with a PushNotification (CLAUDE.md "notify-on-confirmation"): the pilot's seconds a coin, its 0 or more failures and why, parity, the COVERAGE FIRST lines, Decisions 1, 3, 4 and 5 with their recommendations and the measured hours of Decision 1's (a) and (b). Wait for the answer; their choice is the go-ahead (memory: "a choice is a go-ahead").
- [ ] **Step 8: Fill what they chose.** Repeat `backfill <name> --part older` / `settle` until `report` says nothing is left to fill in the chosen span (30 days a press; a red share's days come back by name - press again; a coin-day a green press asked for that Gate's archive cannot complete is counted by `report` and not asked again). Then rebuild the plan only if its end is more than a day old (Step 1 again): the days already filled stay filled - `report` and `backfill` read the cost store itself, per coin and day, never a record of a plan id or a run name - and `backfill --plan research/v3/plan.json --part unseen` presses the newest day(s) the rebuilt plan adds, before any run of it exists. A second round of the universe (Decision 1(b)) takes a NEW name (`universe-2`): a name is used once, and two rounds never share a folder.
- [ ] **Step 9: The universe.** `.venv/Scripts/python -m tradingagents.v3_cloud dispatch universe` (every coin of the plan; three runs of 20 machines). Expected about 15-25 minutes of measuring (Sizing; the pilot's seconds refine it). `redo` a refused share; when completed, `collect universe`; `retry universe` until every coin is landed or named with a reason that is the coin's own (delisted, listed after the split).
- [ ] **Step 10: Judge and keep.** `.venv/Scripts/python -m tradingagents.v3_verdicts publish universe` prints COVERAGE FIRST's coin lines first, then every verdict; then `.venv/Scripts/python -m tradingagents.v3_coverage report universe` for the run's own typical-cost shares.
- [ ] **Step 11: The page.** `.venv/Scripts/python -m tradingagents.v3_results_page universe` writes `stores.V3.home/pages/universe.html` (expected a few MB). Before publishing, the controller runs CLAUDE.md's PRE-PUBLISH CHECK item by item (1-8, A-H) against the page in a browser, then publishes it as an artifact (Artifact tool, `icon` "chart") and gives the link; the tab shows the same verdicts after an API restart (`.venv/Scripts/python start.py api`, warned first) and a web build.
- [ ] **Step 12: Say what came out.** One plain sentence with the real numbers (passed of 27, the best group's id and unseen profit), the link, and what is pending for the operator; append the run's ids, timings and outcomes to this plan's build ledger.

---

## Proven before this plan was handed over (Oct 27, 2026)

Nothing in the checkout changed. The plan's code was rebuilt in a scratch copy of the repo (`tradingagents/`, `tests/`, `.github/`, `research/v3/plan.json`, `webapp/src`, `start.py`, `pyproject.toml`) under this session's scratchpad, run with the repo's own `.venv` and `PYTHONPATH` pointing at the copy (the editable install otherwise resolves to G:), under the repo's own `tests/conftest.py` (no network, `TA_VENUE=mexc`).

- **The plan's tests:** 42 new - `test_v3_shard.py` 6, `test_v3_cloud.py` 11, `test_v3_verdicts.py` 8, `test_v3_results_page.py` 9, `test_v3_coverage.py` 6, one each appended to `test_v3_engine.py` and `test_v3_measure.py` - plus three widened row assertions and one extended test in `test_v3_measure.py`.
- **RED before the code:** run against the checkout's own modules, the four new modules' test files fail to import (`cannot import name 'v3_cloud'`, and so on); `test_v3_shard.py` fails 6 of 6 (no script, no workflow); `test_v3_measure.py` fails 4 and `test_v3_engine.py` 1, each for the reason Task 1 names.
- **Green with every change applied:** 527 passed across the v3, backtest_v3, cost store, cost coverage, one-door, workflow, CI-script, confluence-dispatch, Forecast v2, daily costs, forty-machine and backend-name files plus the entry-point guard; 1 failed - `test_no_printed_string_spells_mexc` on another session's `app_books.py:470`, failing before this plan too. The date-format guards pass. ruff: `All checks passed!` on every file this plan creates or changes (`forecast_v2_daily.py`'s I001 is the checkout's own). `tsc --noEmit` and eslint clean on the tab's two components.
- **Mutation round:** 33 planted breaks, each against its own test file - 6 in the machine (the tab's $1 risk, no redo, plan id or venue unchecked, coins outside the plan measured, record not stamped), 8 in `v3_cloud` (plan not checked on main, state saved after the dispatches, another plan's folder landed into, a failed coin's old record kept, another risk landed, retry of left-out coins, parity comparing timing, redo without `since`), 4 in the verdict store and tab (plan copy unchecked, levels from the older days, no kept copy, a pilot not said), 6 in the page (window ignored, max SL strict, a trail passing max TP, the risk box ignored, months outside the window kept, a choose-failed row losing fields), 6 in coverage (post-only rejects not orders, done days still missing, the dealing job counted as work, a press beside the daily flight, a red press marked done, oldest days first), 3 in the measurement and engine (the older walk on the whole window's gap, stop and target swapped, the trail's moved stop kept): **33 of 33 caught**.
- **The page in a browser** (headless Chrome through the repo's playwright-core, 1280 px and 390 px): 27 rows, no console error, no sideways scroll; max SL % 0.7 kept 1 row and 0.69 kept 0 with the filter named; last 30 days showed only the Sep and Oct columns; risk $10 doubled every dollar; the row's log held its 400 trades under TOTAL PROFIT +$240.00 = the row's PROFIT. One defect found that way and fixed in the code above: the risk printed with a "+" sign ("at +$5.00 risk").
- **Read-only facts measured for this plan:** `gh run list` of `costs.yml` on `jeremydevera/analyzer-x` (the 03:00 UTC press: 353 coins of one day in 4-10 minutes on 20 machines, Oct 20-27, 2026); `~/.tradingagents/costs_daily.json` (`done_days` Aug 16 - Oct 26, 2026); one HEAD pair on Gate's order-book archive (`XAU_USDT` 2026-06-03 12:00 UTC: 200, 8.6 MB; 2025-11-03 12:00 UTC: 404). No workflow was dispatched and no order sent.

## Notes for the build

- `cq_shard.usual_slip` keeps its own copy of `cost_store.usual_slip`'s rule; nothing here changes either.
- Part 2a's three check records under `research/local` are version 1 (rows of 6): the tab's check still shows them, with "not recorded" in the size columns; the results page is built only from a published run.
- `v3_page.tested`'s first parameter was `rows_db` (never written by anything); it is now the verdict store's file. Its only callers are `v3_page.options` and the tab's tests.
