# Backtest v3 — Part 2a: the idea families and the proof test — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, on this PC and without GitHub, everything one Backtest v3 research run needs: the universe and its cross-coin data written as the run's plan file, the four idea families with their fixed settings, four filters laid on the signals as masks, the strength family's forced rank exit, seeded random entries, the proof test that chooses a setting on the older days and judges it on the unseen days, one coin's whole measurement, and a command that runs a few coins end to end and prints every verdict.

**Architecture:** Seven new modules, one job each. `v3_universe` builds the plan (who is liquid or calm each month, BTC's mood, the Monday strength ranks) from daily candles. `v3_families` holds the four rules, their settings, exits and lead-ins. `v3_filters` turns each filter into per-candle masks. `v3_random` draws the seeded random entries. `v3_measure.measure_coin` reads one coin once and walks every family × setting × timeframe × filter on the older and the unseen days, plus 200 random runs each, through the Part 1 engine (`v3_engine.walk`, which gains a `forced=` exit and a `contract_of` helper). `v3_proof` pools every coin's record, chooses and judges. `v3_research` is the command. Nothing in this part dispatches to GitHub, runs a job in the v3 store, or files anything in a list.

**Tech Stack:** Python 3.13 (this PC's `.venv`), numpy, pandas, pytest, ruff; `statistics.NormalDist` for z (no scipy). It reuses the exchange door (`tradingagents.dataflows.exchange as fx`), `book_history`, `cost_store`, `backtest_report.fine_bars` / `TFS` / `row_code`, `pro_indicators.donchian`, `daytime_rule.in_market_hours`, `v3_page.worst_run` and `positions_view.fmt_when`.

**Spec:** `docs/superpowers/specs/2026-10-22-backtest-v3-design.md` (approved Oct 22, 2026, "ok go ahead"), and the binding Part 2 decisions made inside it: `docs/superpowers/specs/2026-10-23-backtest-v3-part2-decisions.md` (operator, Oct 23, 2026: *"go"*). This plan is the decisions doc's "Part 2a"; Part 2b (the GitHub half) gets its own plan.

## Global Constraints

- **Read before the first edit:** the newest entries of `docs/OPERATOR-ASKS.md`, as CLAUDE.md "remember-my-asks" requires.
- **v1, v2 and the Part 1 tab do not change behaviour.** The one engine parameter added (`walk(forced=None)`) defaults to the rule of before, and every existing test named in a task stays green.
- **The window is the plan's, never the clock:** the 365 days to the plan's `end_ms` (a UTC midnight), the newest **90** of them unseen; every coin and every machine use the same three instants (`v3_measure.windows`).
- **Two walks per setting, never one:** the OLDER walk runs on the candles up to the split, and its minutes, order books and funding are cut at the split; a trade still open there closes at its last candle (`END`). The UNSEEN walk runs on the newest 90 days, its lead-in read by the indicators only.
- **Lead-in:** 300 candles, or the rule's own lookback where that is longer (v3_trend n=50 on 4h: 330; n=100 on 4h: 630).
- **Universe:** liquid = `venue.kind() == "crypto"`, the top **50** by 30-day traded value (a day's `Volume × contractSize × Close`, today's contract size) at each month start; calm = kinds `metals`, `indices`, `forex` every month, plus the calmest third (rounded up) of that month's liquid coins by 60-day realized volatility (the population standard deviation of daily log returns). A signal's month is the month its ORDER goes in (the close of the signal candle).
- **Families, settings in simplest-first order:** `v3_trend` n = 20, 50, 100 days (6n candles on 4h) on 1d and 4h; `v3_breakout` N = 20, 50 days on 1d; `v3_strength` K = 3, 5 on 1d; `v3_snap` k = 1.5, 2.0 on 1h and 4h. Exits: trail 3 × ATR(20) (+ out on a close past SMA(n) for trend; + forced out at a Monday's close outside the top 2K for strength, `why` RANK); snap: the SMA(20) at the signal as a resting target, an emergency stop 3 × ATR(20), out after 24 candles.
- **Filters:** `none`, `btc_mood`, `busy_hours`, `funding_side`, `funding_minutes`. `crash_guard` (#8) is not built: it is printed as "not tested yet".
- **The proof:** α = 0.05 / **70** (every family × setting × timeframe × filter measured, `len(v3_families.combos())`), z = Φ⁻¹(1 − α/2) = **3.384**; **200** random runs; **2,000** bootstrap draws; at least **30** older trades to be chosen; at least **300** unseen trades to pass.
- **Money:** every trade risks **$1** (`v3_rules.RISK_USD`); `risk_usd` is a parameter, never changed silently, and a record says the risk it was measured at.
- **Costs:** maker `auto_trader.maker_fee_floor()` (0.0002 on Gate), taker `auto_trader.fee_floor()` (0.00075); where a minute has no recorded book, each coin's OWN usual gap (`cost_store.usual_slip`, CLAUDE.md rule 10); the order books' coverage is printed FIRST (CLAUDE.md "COVERAGE FIRST").
- **Code rules:** dates print only through `positions_view.fmt_when`; nothing goes below an `if __name__ == "__main__":` guard; the exchange is reached only as `fx` from `tradingagents.dataflows.exchange`, and every `fx.<name>` read exists on both adapters (this plan reads `klines`, `contract_spec`, `funding_history`, `minutes`, `book_cost`, `trading_symbols`); no variable named `l` outside tests (ruff E741); imports from one package combined on one line (`combine-as-imports`); a printed string never names an exchange as a literal (the plan's own `venue` field, from `venue.name()`).
- **Where files go:** the command writes only the plan file (`research/v3/plan.json`) and `stores.V3.home / "research" / <label>` (on the store's drive, CLAUDE.md "Big files go where the STORE is"). No job runs with `stores.V3.env_for()`: the fence beside `stores.V3` stays.
- **Testing on this PC:** run ONE full pytest suite at a time (check for a running pytest first; other sessions share this PC). Each task runs only the files it names. Unit tests reach no network (the repo's conftest blocks it); the only real-data runs are Task 9's, read-only.
- **Before each commit:** run the harddev hunt (callers, the state it runs in, failure paths, units, sides) and name each check in the commit message; check `git diff HEAD -- <path>` for every path (commit_own commits WHOLE files and other sessions edit this checkout); never `git add -A`, never `git stash`.
- **Commit and push:** write the message to a file OUTSIDE the repo (your scratchpad), ending with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; commit with `.venv/Scripts/python scripts/commit_own.py -F <msg-file> <paths>`; push with `git push -q origin main && git push -q colleague main && git push -q teammate main`.

## Review Focus

1. **A coin listed inside the window.** It is measured on the candles it has, and its window says where it starts; a coin listed after the split has nothing to choose a setting on, and every timeframe is skipped and named. Pinned in Task 8 by `test_a_young_coin_is_measured_on_what_exists_and_one_listed_after_the_split_is_named`.
2. **A lot bigger than a $1-risk position.** At Gate's lot sizes a $1-risk trade of ETH, SOL or XRP on 1d is under one lot (measured Oct 23, 2026: 19 of October's 50 liquid coins on 1d, 7 on 4h, 4 on 1h); the trade is skipped, counted `too_small`, and every verdict prints how many signal candles were refused for it. Pinned in Task 8 by `test_the_risk_reaches_every_walk_and_a_risk_under_one_lot_trades_nothing` and in Task 9 by `test_the_report_prints_coverage_first_then_every_verdict_with_the_kits_figures`.
3. **The split itself.** A signal on the last older candle (its order would go in at the split) trades in neither walk, and the older walk reads no minute, book reading or funding settlement after the split. Pinned in Task 8 by `test_a_signal_on_the_last_older_candle_trades_in_neither_walk`, `test_the_older_walk_cannot_see_a_price_after_the_split`, `test_the_older_walks_data_is_cut_at_the_split`, and the K = 5 `END` row of `test_strength_enters_on_a_monday_and_is_forced_out_when_it_drops_past_the_top_2k`.
4. **Records that are not alike under one label** (another plan, another risk, another number of random runs). They are never pooled and always named. Pinned in Task 9 by `test_judge_pools_only_the_coins_measured_under_this_plan_and_names_the_rest`.
5. **A filter or month mask that removes every real entry.** The random runs then place nothing (no luck bar made of entries the real run could not place), and a verdict with no unseen trade says so in one line. Pinned in Task 8 by `test_random_runs_are_seeded_and_entered_like_the_real_run` and in Task 9 by `test_a_chosen_setting_with_no_unseen_trade_says_so_in_one_line`.

## Decisions this plan makes inside the decisions doc (each fixed before any result, with why)

1. **A signal's month is the month its order goes in** — the close of the signal candle (`t[i] + bar`). Membership, sides, the filters and the random draws all read that instant: it is when each is known, and when the order would exist.
2. **Lead-in = 300 candles or the rule's own lookback, whichever is longer.** With 300, v3_trend n = 100 on 4h (a 600-candle average and 30 candles back) could not signal for the first 330 candles — 55 of the 90 unseen days. The doc's "300 candles before them as lead-in for the indicators only" is met in its purpose.
3. **The "signals" the random runs match are the orders the real walk placed** — its trades and its missed orders (rejected or never filled), per month and side. Counting every candle a persistent rule held on would make a random trend run re-enter on almost every candle.
4. **Random entries are drawn from the candles the combination could have entered on**: its universe month and side, its filter, its family's entry days (Mondays for v3_strength). The spec's "same coins, same hours".
5. **`busy_hours`' weekend rule covers every contract that is not a stock token** (crypto, metals, indices, forex). The doc names only stocks and crypto; the other three's home markets are shut at weekends too.
6. **`btc_mood` filters only crypto alt-coins' longs**: "alt-coin longs" read literally; BTC and metals/indices/forex pass.
7. **`funding_side`'s "top 10%"** = at most 10% of the window's settlements are at or above the last rate (ties count against it), so the usual rate is never "the top" however many settlements tie with it; the bottom mirrors it. The history covers an order when it answers the whole 30 days before it (from one cycle before its first settlement to one cycle after its last, `v3_rules.funding_paid`'s convention); otherwise `funding_unknown`, the signal passes.
8. **`funding_minutes`** reads the recorded settlements within the history (± 5 minutes) and the contract's settlement cycle from 00:00 UTC elsewhere, counted `settle_by_cycle`. Measured on Gate's BTC and ETH (Oct 23, 2026): settlements land 0-5 s after a UTC-aligned 8-hour grid.
9. **The calmest third** is `ceil(n / 3)` of the month's liquid coins that have a full 60-day volatility (61 daily closes); a coin without them is never calm (unknown is not calm).
10. **The strength rank is taken at Monday 00:00 UTC** (the close of Sunday's candle). The signal candle is the Monday candle, as the doc's "long on each Monday's candle" says, so its order goes in at Tuesday 00:00; the forced exit is at the close of a Monday candle by that Monday's rank.
11. **The bootstrap clusters each trade by the UTC day it closed.**
12. **A trade still open when a walk ends (`END`) counts**, marked at the last close and paying the market exit; each verdict says how many there were. Dropping them would drop a trend family's longest trades.
13. **The normal fit uses the sample standard deviation** (n − 1), the slightly stricter bar.
14. **`settle_in_minutes` does not call `stop_reached`** (the question parked at Part 1's final review): it is the shared v2 and room-replay settle, and pulling `v3_rules` into its hot loop would couple v2 to v3 for an identical comparison (`lw <= sl_px`). A parity test (Task 1) holds the two touch rules equal.
15. **The risk stays $1**, and `measure_coin(risk_usd=)` / the command's `--risk` exist: at $1, Gate's lots remove ETH, SOL and XRP from the daily families (Review Focus 2). Changing the research risk is the operator's call before Part 2b; nothing here changes it.
16. **`research/v3/plan.json` is built and committed in Task 9 as the first plan**; Part 2b rebuilds it right before its run, so every machine reads that run's universe.

## Proven before this plan was handed over (Oct 23, 2026)

Nothing in the checkout changed. The code and tests below ran in a scratch copy: a small pytest plugin put the scratch folder first on `tradingagents.__path__`, so the new modules and the patched copies of `v3_engine.py`, `v3_smoke.py` and `cost_store.py` were the ones imported, and the new tests ran under the repo's own `tests/conftest.py` (no network, `TA_VENUE=mexc`).

- **The plan's tests:** 140 pass across the nine test files — 68 in the seven new files, 65 in `tests/test_v3_engine.py` (59 + 2 + 4) and 7 in `tests/test_v3_shared_rules_learn_the_waiting_order.py` (6 + 1).
- **RED before each task:** every new test file fails to import its module (`ImportError: cannot import name 'v3_…' from 'tradingagents'`); Task 2's 4 tests fail on the current engine (`TypeError: … unexpected keyword argument 'forced'`, `AttributeError: … 'contract_of'`); Task 8's tests fail without `cost_store.usual_slip`. Task 1's three tests pass on the current engine on purpose: they pin behaviour it already has.
- **Existing tests with every change applied:** 141 of 141 — `test_v3_engine` (59), `test_v3_rules` (26), `test_v3_smoke` (6), `test_backtest_v3_tab` (20), `test_v3_shared_rules_learn_the_waiting_order` (6), `test_backtest_v3_store` (4), `test_cost_store` (11), `test_cost_coverage` (3), `test_one_door_to_the_exchange` (6).
- **Lint:** ruff with the project's config, over the whole package with the changes laid on it: `All checks passed!`.
- **Source guards over that copy:** the one-door scan (6 of 6), the two date-format guards (2 of 2), nothing below an entry point (checked on every changed module). `test_the_backend_names_the_exchange` fails only on another session's `app_books.py:470`, exactly as before this plan (Part 1 ruling 11).
- **Mutation round:** 39 deliberate breaks — 8 in `v3_universe`, 6 `v3_families`, 5 `v3_filters`, 3 `v3_random`, 7 `v3_proof`, 7 `v3_measure`, 2 `v3_research`, 1 the forced exit — each run against its own test file: **39 of 39 caught**. Three survived the first round (the bootstrap without its z, the older walk's minutes not cut, random strength entries off Mondays); each got the pin that is now in this plan. Task 1's pins were shown to bite the same way (the short side of the candle proof read as a long's; a fixed stop that needs a trade-through).
- **Real Gate data, read-only, Oct 23, 2026** (the window Oct 22, 2025 8:00pm to Oct 22, 2026 8:00pm, this PC's clock):

| run | result | time |
|---|---|---|
| the plan, from 596 crypto contracts' daily candles | 13 months; 233 coins in some group; liquid 50 every month, calm 46-51 (34 by kind + 12-17 crypto); 0 skipped | 352 s |
| `measure_coin` BTC_USDT, 200 random runs | 70 combinations; 507,240 minutes; books cover 0.0% of the older days, 81.1% of the unseen | 194 s, 90 KB |
| `measure_coin` XAU_USDT, 200 random runs | 60 combinations (a metal: no strength); 379,670 minutes | 148 s, 72 KB |
| the two judged | 30 verdicts, 0 passed (a 2-coin check cannot reach 300 trades); e.g. `#TYB6WLRZ` v3_trend 4h none: n20 chosen, 47 unseen trades, +$0.123 a trade against a random bar of +$0.385 | 0.4 s |
| the command, `run XAU_USDT eth_usdt --runs 5` | exit 0; both coins' coverage first, 30 verdict lines; ETH's v3_trend 1d: 0 trades, all 213 older and 76 unseen signal candles under one lot | 108 s |

---

### Task 1: Part 1's parked items — two rule wordings, one RCA line, three pins

The final review of Part 1 parked these for "Part 2's first commit" (Part 1 plan, "Parked at the final review"). No engine code changes here.

**Files:**
- Modify: `CLAUDE.md` (two bullets of "## Backtest v3 — the engine's rules")
- Modify: `docs/RCA.md` (RCA-2026-10-23-B, timeline step 3)
- Modify: `tests/test_v3_engine.py` (append two short-side pins)
- Modify: `tests/test_v3_shared_rules_learn_the_waiting_order.py` (append the touch-rule parity test)

**Interfaces:**
- Consumes: the existing `v3_engine.walk`, `auto_trader.settle_in_minutes`, `v3_rules.stop_reached`, and the test files' own helpers (`_world`, `_walk`, `_without`, `FLAT`, `SIGNAL`, `TRAIL`, `M`, `H`, `T0` in `tests/test_v3_engine.py`; `_minutes`, `T0`, `at` in the shared-rules test).
- Produces: `SHORT_TRAIL_FILL` in `tests/test_v3_engine.py` (a fill hour in which a short sells at 100.0 in minute 0) — Task 2's tests reuse it.

- [ ] **Step 1: Append the two short-side pins** to the end of `tests/test_v3_engine.py`:

```python
# ---- parked at the final review of Part 1, added in Part 2a's first commit: a SHORT trail's -----
# ---- stop that a hole hides, (a) in the rest of the fill candle and (b) in a whole candle --------

SHORT_TRAIL_FILL = [(100.2, 99.95)] + [(100.1, 99.9)] * 59   # sells at 100.0 in minute 0


def test_a_short_trails_hidden_stop_in_the_rest_of_the_fill_candle_is_proven_by_its_high():
    # (a) the short sells at minute 0 (its 100.2 high is over the 100.0 limit); the trail starts
    # 3 x 0.205 = 0.615 over the entry, 100.615. Minutes 1-29 pull it down to 99.9 + 0.615 =
    # 100.515 and minute 30 trades up to 101.0: with every minute, out at minute 30 at 100.515
    fill_hour = SHORT_TRAIL_FILL[:30] + [(101.0, 99.9)] + SHORT_TRAIL_FILL[31:]
    bars, fine = _world([FLAT] * 21 + [SIGNAL, fill_hour, FLAT])
    dirs = [0] * 21 + [-1, 0, 0]
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine)["trades"]
    assert (tr["why"], tr["exit_ms"]) == ("TRAIL", T0 + 22 * H + 30 * M)
    assert tr["exit"] == pytest.approx(100.515)
    # minute 30 missing: a short trades through its limit before it can rise to a stop over it,
    # so the hour's own 101.0 high came after the fill and is over the 100.615 the trail BEGAN
    # with - the stop was hit. Whether minutes 1-29 pulled it down first is unknowable: out at
    # 100.615, stamped at minute 1, the first point after the fill
    got = _walk(bars, dirs, TRAIL, fine=_without(fine, T0 + 22 * H + 30 * M, T0 + 22 * H + 31 * M))
    (tr,) = got["trades"]
    assert (tr["why"], tr["exit_ms"]) == ("TRAIL", T0 + 22 * H + M)
    assert tr["exit"] == pytest.approx(100.615)
    assert got["counts"]["settled_by_candle"] == 1 and got["counts"]["unclear"] == 0


def test_a_short_trails_hidden_stop_in_a_whole_candle_cannot_ride_on_to_a_later_exit():
    # (b) the mirror of the long test above. Hour 23 begins with the short's trail at 100.515.
    # Minute 10 trades up to 101.0, over it; minute 20 down to 99.0 (which would pull the stop to
    # 99.615) and minute 30 up to 99.7. Every minute: out at minute 10, at 100.515
    hour = ([(100.1, 99.9)] * 10 + [(101.0, 100.0)] + [(100.1, 99.9)] * 9 + [(99.6, 99.0)]
            + [(99.5, 99.0)] * 9 + [(99.7, 99.4)] + [(99.7, 99.5)] * 29)
    bars, fine = _world([FLAT] * 21 + [SIGNAL, SHORT_TRAIL_FILL, hour, FLAT])
    dirs = [0] * 21 + [-1, 0, 0, 0]
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine)["trades"]
    assert (tr["why"], tr["exit_ms"]) == ("TRAIL", T0 + 23 * H + 10 * M)
    assert tr["exit"] == pytest.approx(100.515)
    # minute 10 missing: the minutes left would exit at 99.615 at minute 30 (a WIN for the short),
    # but the hour's own 101.0 high is over the 100.515 it began with (a trail only tightens inside
    # an hour): the stop was hit in a hidden minute, in an order nothing shows - out at 100.515 at
    # the hour's open (it opened at 100.0, under the stop), counted settled_by_candle and unclear
    got = _walk(bars, dirs, TRAIL, fine=_without(fine, T0 + 23 * H + 10 * M, T0 + 23 * H + 11 * M))
    (tr,) = got["trades"]
    assert (tr["why"], tr["exit_ms"]) == ("TRAIL", T0 + 23 * H)
    assert tr["exit"] == pytest.approx(100.515)
    assert got["counts"]["settled_by_candle"] == 1 and got["counts"]["unclear"] == 1
```

- [ ] **Step 2: Append the parity test** to the end of `tests/test_v3_shared_rules_learn_the_waiting_order.py`:

```python
def test_the_fixed_stop_reads_a_touch_exactly_as_stop_reached_does():
    """One touch rule kept in two places (parked at the final review of Backtest v3 Part 1):
    `settle_in_minutes` reads a fixed stop at a minute the archive holds (the shared v2 settle,
    `lw <= sl_px`), `v3_rules.stop_reached` everything else. A long's low AT its stop stops it in
    both, a low a hair above it in neither - and a short mirrors it."""
    from tradingagents import v3_rules as vr

    for s, stop, tp, touch, miss in ((1, 98.0, 110.0, (99.0, 98.0), (99.0, 98.01)),
                                     (-1, 102.0, 90.0, (102.0, 101.0), (101.99, 101.0))):
        for (hi, lo), hit in ((touch, True), (miss, False)):
            t, h, lw = _minutes([(hi, lo)])
            got = at.settle_in_minutes(t, h, lw, T0, 3600, s, tp, stop, None, liq=None,
                                       sl=0.02, tp_through=True)
            assert (got[0] == "SL") is hit, (s, hi, lo)
            assert vr.stop_reached(s, stop, hi, lo) is hit, (s, hi, lo)
```

- [ ] **Step 3: Run them**

Run: `.venv/Scripts/python -m pytest tests/test_v3_engine.py tests/test_v3_shared_rules_learn_the_waiting_order.py -q`
Expected: `68 passed` (61 + 7). These PASS at once: they pin behaviour the engine already has (the final review's probes showed the short side mirrors the long). They were shown to bite in scratch: reading the candle proof's points as a long's (`_points_reach` with side 1) fails both short pins, and a fixed stop that needs a trade-through (`lw < sl_px`) fails the parity test.

- [ ] **Step 4: Fix the two wordings in CLAUDE.md** (check `git diff HEAD -- CLAUDE.md` first: other sessions edit this file). Replace

```markdown
  - a touch STOPS: `stop_reached`, one rule for the trail, the fixed stop
    and a candle that proves a stop;
```

with

```markdown
  - a touch STOPS: `stop_reached` for the trail and for a candle that
    proves a stop; a fixed stop at a minute the archive holds is read by
    `settle_in_minutes` (`lw <= sl_px`), the same touch rule kept in the
    shared v2 settle and held equal to `stop_reached` by a test;
```

and replace

```markdown
  - funding outside Gate's history — before its first settlement, or more
    than one cycle (the last settlement's own) after its last, a saved list
    that stopped — pays the average known rate and is counted
    (RCA-2026-10-23-B); the cycle not settled yet is free.
```

with

```markdown
  - funding outside Gate's history — more than one cycle before its first
    settlement, or more than one cycle (the last settlement's own) after its
    last, a saved list that stopped — pays the average known rate and is
    counted (RCA-2026-10-23-B); the cycle not settled yet is free.
```

(`v3_rules.funding_paid` estimates only the part of a hold more than one cycle before the first settlement: a hold from T0 − 4h to T0 − 1h against a list starting at T0 returns `(0.0, False)`.)

- [ ] **Step 5: Correct the RCA timeline line.** In `docs/RCA.md`, RCA-2026-10-23-B, replace

```markdown
3. `Oct 23, 2026 ~1:45am` - the final review's probe: a list whose last
   settlement is an hour before the entry (0.1% every 8 hours), a long held
   41 hours on $50 of coin: $0.00, `estimated=False`. Settled every 8 hours
   it pays 5 x 0.1% = $0.25, so +$0.23 read as +$0.48.
```

with

```markdown
3. `Oct 23, 2026 ~1:45am` - the final review names the case: a list whose
   last settlement is an hour before the entry (0.1% every 8 hours), a long
   held 41 hours on $50 of coin. Its probe script passed NO list, so it ran
   the no-history path and printed `estimated=True`; called with the list,
   as the case reads, the `d8b2f00` code returns `(0, False)` - $0.00,
   marked measured (run again Oct 23, 2026 for Part 2a's first commit).
   Settled every 8 hours it pays 5 x 0.1% = $0.25, so +$0.23 read as +$0.48.
```

(Checked before this plan: `git show d8b2f00:tradingagents/v3_rules.py`, `funding_paid([T0 - 8h, T0], [0.001, 0.001], [8, 8], 1, T0 + 1h, T0 + 42h)` returns `(0, False)`; with no list, `(0.0, True)`.)

- [ ] **Step 6: Run the two test files again, then lint**

Run: `.venv/Scripts/python -m pytest tests/test_v3_engine.py tests/test_v3_shared_rules_learn_the_waiting_order.py -q`, then `.venv/Scripts/python -m ruff check tests/test_v3_engine.py tests/test_v3_shared_rules_learn_the_waiting_order.py`
Expected: `68 passed`, then `All checks passed!`

- [ ] **Step 7: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> CLAUDE.md docs/RCA.md tests/test_v3_engine.py tests/test_v3_shared_rules_learn_the_waiting_order.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message (write it to `<msg-file>`, outside the repo):

```text
test(v3): Part 1's parked items - a short trail's hidden stop pinned in the fill candle and a whole candle, the fixed stop's touch held equal to stop_reached, two CLAUDE.md wordings and an RCA line that said more than the code

Parked at the final review of Backtest v3 Part 1 for Part 2's first commit:
- CLAUDE.md: funding before the history is estimated only more than one cycle before its first settlement; a fixed stop at a visible minute is read by settle_in_minutes, the same touch rule, now held equal to stop_reached by a test (settle_in_minutes stays v2's shared settle)
- docs/RCA.md RCA-2026-10-23-B step 3: the probe passed no list; with the list the d8b2f00 code returns (0, False)
- tests: the short side of the hidden-stop rules (a) and (b); both fail when the candle proof reads the points as a long's

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 2: The engine's forced exit and one contract mapping

**Files:**
- Modify: `tradingagents/v3_engine.py` (the module docstring; `contract_of` after `_check_contract`; `_trade`; `walk`)
- Modify: `tradingagents/v3_smoke.py` (the `walk` call's `contract=`)
- Modify: `tests/test_v3_engine.py` (append four tests)

**Interfaces:**
- Consumes: Task 1's `SHORT_TRAIL_FILL` and the file's own helpers (`_trail_world`, `_world`, `_walk`, `_book`, `FLAT`, `SIGNAL`, `TRAIL`).
- Produces:
  - `v3_engine.walk(..., forced=None)`: per-candle flags; an open trade (the market twins' too) leaves at the close of a flagged candle, at the market (taker fee plus the exit minute's gap), `why` `"RANK"`. A stop or target the candle reached first comes first. `None` is the rule of before.
  - `v3_engine.contract_of(spec: dict) -> dict` — `fx.contract_spec`'s fields (`contractSize`, `minVol`, `maintenanceMarginRate`, `maxLeverage`, `minLeverage`) as the engine's `{"contract_size", "min_vol", "mmr", "max_lev", "min_lev"}`. A missing or non-numeric lot size, maintenance rate or maximum leverage raises `ValueError` naming the listing field; `minVol` and `minLeverage` default to 1; a `minLeverage` under 1 raises; 0 or less is refused by `_check_contract`, naming the engine field.

- [ ] **Step 1: Write the failing tests** — append to the end of `tests/test_v3_engine.py`:

```python
# ---- Backtest v3 Part 2a: the forced exit (v3_strength's weekly rank) and the contract read --------


def _forced_at(n, *flagged):
    return [k in flagged for k in range(n)]


def test_a_forced_candle_closes_the_trade_at_its_close_at_the_market():
    # the trail world: the fill hour (22) lifts the trail to 100.1 - 0.615 = 99.485, and hours 23
    # and 24 trade 99.9-100.1, never down to it. Flagged at hour 23, the trade leaves at that hour's
    # close, 100.0, at T0 + 24h, at the market. $162 of coin (a 0.615 stop from 100.0 at $1 risk),
    # +0% of it, less 0.02% in and the taker 0.075% plus the recorded 0.04% out = -0.2187
    bars, fine, dirs = _trail_world(FLAT, FLAT)
    book = _book((T0 + 24 * H, 99.95, 100.05, 0.0009, 0.0004))
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine, book=book, forced=_forced_at(25, 23))["trades"]
    assert (tr["why"], tr["exit_ms"], tr["exit_bar"]) == ("RANK", T0 + 24 * H, 23)
    assert tr["exit"] == pytest.approx(100.0) and tr["fee_out"] == 0.00075
    assert tr["slip_out"] == pytest.approx(0.0004)
    assert tr["pnl"] == pytest.approx(-162.0 * (0.0002 + 0.00075 + 0.0004))
    # no flags: the rule of before - still open when the data ends, out at hour 24's close
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine, book=book)["trades"]
    assert (tr["why"], tr["exit_ms"]) == ("END", T0 + 25 * H)


def test_a_stop_inside_the_forced_candle_comes_first():
    # minute 10 of the flagged hour trades down to 99.0, under the 99.485 trail: the stop was hit
    # before the hour closed, so it is the trail's exit, at 99.485, never the forced one
    hour = [(100.1, 99.9)] * 10 + [(100.0, 99.0)] + [(100.1, 99.9)] * 49
    bars, fine, dirs = _trail_world(hour, FLAT)
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine, forced=_forced_at(25, 23))["trades"]
    assert (tr["why"], tr["exit_ms"]) == ("TRAIL", T0 + 23 * H + 10 * M)
    assert tr["exit"] == pytest.approx(99.485)


def test_a_forced_exit_holds_for_a_short_and_for_a_missed_orders_twin():
    # a short sells at 100.0 in minute 0; the fill hour's 99.9 lows pull its trail down to 100.515,
    # and hour 23's 100.1 highs never reach it: flagged, it buys back at hour 23's close, 100.0.
    # +0% of $162 less 0.02% in and 0.075% out, no gap recorded here: -0.1539
    bars, fine = _world([FLAT] * 21 + [SIGNAL, SHORT_TRAIL_FILL, FLAT, FLAT])
    (tr,) = _walk(bars, [0] * 21 + [-1, 0, 0, 0], TRAIL, fine=fine,
                  forced=_forced_at(25, 23))["trades"]
    assert (tr["side"], tr["why"], tr["exit_ms"]) == (-1, "RANK", T0 + 24 * H)
    assert tr["pnl"] == pytest.approx(-162.0 * (0.0002 + 0.00075))
    # a long whose hour 22 only touches its 100.0 limit is missed; its twin buys at that hour's
    # open, 100.1, with the same 0.615 trail (99.485, lifted to 100.2 - 0.615 = 99.585 by the
    # hour's highs) and leaves where the real trade would have: at the flagged hour's close
    bars, fine = _world([FLAT] * 21 + [SIGNAL, [(100.2, 100.0)] * 60, FLAT, FLAT])
    got = _walk(bars, [0] * 21 + [1, 0, 0, 0], TRAIL, fine=fine, forced=_forced_at(25, 23))
    assert got["trades"] == [] and got["counts"]["missed"] == 1
    twin = got["missed"][0]["market"]
    assert twin["entry"] == pytest.approx(100.1)
    assert (twin["why"], twin["exit_ms"]) == ("RANK", T0 + 24 * H)


def test_the_contract_is_read_from_the_listing_one_way_and_a_missing_field_is_named():
    # Gate's BTC_USDT listing as `fx.contract_spec` gives it (Oct 23, 2026)
    spec = {"contractSize": 0.0001, "minVol": 1, "maintenanceMarginRate": 0.003,
            "maxLeverage": 200, "minLeverage": 1, "takerFeeRate": 0.00075}
    assert ve.contract_of(spec) == {"contract_size": 0.0001, "min_vol": 1, "mmr": 0.003,
                                    "max_lev": 200, "min_lev": 1}
    bare = {k: v for k, v in spec.items() if k not in ("minVol", "minLeverage")}
    assert (ve.contract_of(bare)["min_vol"], ve.contract_of(bare)["min_lev"]) == (1, 1)
    for key in ("contractSize", "maintenanceMarginRate", "maxLeverage"):
        with pytest.raises(ValueError, match=f"contract {key} is missing"):
            ve.contract_of({k: v for k, v in spec.items() if k != key})
    with pytest.raises(ValueError, match="maintenanceMarginRate = 'n/a' is not a number"):
        ve.contract_of({**spec, "maintenanceMarginRate": "n/a"})
    with pytest.raises(ValueError, match="minLeverage = 0"):
        ve.contract_of({**spec, "minLeverage": 0})
    # a rate READ as 0 passes the reading and is refused by the engine's own check, by name
    with pytest.raises(ValueError, match="contract mmr = 0.0"):
        ve.contract_of({**spec, "maintenanceMarginRate": 0.0})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_v3_engine.py -q`
Expected: `4 failed, 61 passed` — `TypeError: walk() got an unexpected keyword argument 'forced'` and `AttributeError: module 'tradingagents.v3_engine' has no attribute 'contract_of'`.

- [ ] **Step 3: Implement — the module docstring.** In `tradingagents/v3_engine.py`, directly after the paragraph that ends ``  `max_bars`-th candle.`` (the snap bullet), insert this paragraph, with one blank line before it and one after it:

```text
Any of the three can also be FORCED out (`walk(forced=)`, Backtest v3 Part
2a): an open trade leaves at the close of a flagged candle, at the market,
`why` "RANK" — the strength family's weekly rank exit. A stop or target the
candle reached first still comes first.
```

- [ ] **Step 4: Implement — `contract_of`**, inserted between `_check_contract` and `_span` (two blank lines around it):

```python
def contract_of(spec: dict) -> dict:
    """The engine's contract from the exchange's listing (`fx.contract_spec`):
    ONE mapping for every v3 caller — the smoke run and the tab
    (`v3_smoke.measure`) and one coin's whole measurement (`v3_measure`). A
    lot size, maintenance rate or maximum leverage that is missing or not a
    number is refused BY NAME, as `_check_contract` refuses one at 0 or less
    (unknown is not zero). The smallest order and the lowest leverage default
    to 1; a lowest leverage under 1 is refused (no position exists under 1x,
    and `v3_rules.safe_leverage` would divide by it)."""
    def field(key: str, cast, default=None):
        raw = spec.get(key)
        if raw is None or raw == "":
            if default is None:
                raise ValueError(f"contract {key} is missing: the listing cannot size a "
                                 "trade (unknown is not zero)")
            return default
        try:
            return cast(float(raw))
        except (TypeError, ValueError):
            raise ValueError(f"contract {key} = {raw!r} is not a number") from None

    c = {"contract_size": field("contractSize", float), "min_vol": field("minVol", int, 1),
         "mmr": field("maintenanceMarginRate", float), "max_lev": field("maxLeverage", int),
         "min_lev": field("minLeverage", int, 1)}
    if c["min_lev"] < 1:
        raise ValueError(f"contract minLeverage = {spec.get('minLeverage')!r}: no position "
                         "exists under 1x")
    _check_contract(c)
    return c
```

- [ ] **Step 5: Implement — the forced exit in `_trade`.** Replace

```python
    kind, spec, ma = ctx["kind"], ctx["spec"], ctx["ma"]
```

with

```python
    kind, spec, ma, forced = ctx["kind"], ctx["spec"], ctx["ma"], ctx["forced"]
```

and, in the loop, directly after the two lines that book `"MA"`

```python
                and s * (c[j] - ma[j]) < 0):
            hit = (b_ms, c[j], "MA")
```

insert

```python
        if hit is None and forced is not None and j < len(forced) and forced[j]:
            hit = (b_ms, c[j], "RANK")
```

(before the `"TIME"` check).

- [ ] **Step 6: Implement — `walk`.** Replace its signature's last line

```python
         funding=None, start: int = 0, closed=None, cost_check: bool = True) -> dict:
```

with

```python
         funding=None, start: int = 0, closed=None, cost_check: bool = True,
         forced=None) -> dict:
```

In its docstring replace

```text
    (the runner's rule, worked out by the caller; honoured with or without
    the cost check) or None.
```

with

```text
    (the runner's rule, worked out by the caller; honoured with or without
    the cost check) or None · forced: per-candle flags — an open trade, the
    market twins' too, leaves at the close of a flagged candle at the market,
    `why` "RANK" (v3_strength's weekly rank exit) — or None, the rule of
    before.
```

and in the `ctx` dict replace

```python
           "risk_usd": float(risk_usd), "cover": {},
```

with

```python
           "risk_usd": float(risk_usd), "cover": {}, "forced": forced,
```

- [ ] **Step 7: Implement — one mapping in the smoke run and the tab.** In `tradingagents/v3_smoke.py`, `measure`, replace

```python
        bars, dirs, spec, bar_s=bar_s,
        contract={"contract_size": float(c.get("contractSize") or 0.0),
                  "min_vol": int(c.get("minVol") or 1),
                  "mmr": float(c.get("maintenanceMarginRate") or 0.0),
                  "max_lev": int(c.get("maxLeverage") or 1),
                  "min_lev": int(c.get("minLeverage") or 1)},
```

with

```python
        bars, dirs, spec, bar_s=bar_s, contract=v3_engine.contract_of(c),
```

- [ ] **Step 8: Run the tests to verify they pass, then lint**

Run: `.venv/Scripts/python -m pytest tests/test_v3_engine.py tests/test_v3_rules.py tests/test_v3_smoke.py tests/test_backtest_v3_tab.py tests/test_v3_shared_rules_learn_the_waiting_order.py -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_engine.py tradingagents/v3_smoke.py tests/test_v3_engine.py`
Expected: `124 passed` (65 + 26 + 6 + 20 + 7), then `All checks passed!`. If a number disagrees, work it again by hand in the test's own comment and fix the ENGINE; never loosen an assertion.

- [ ] **Step 9: The harddev hunt.** Name each check in the commit message:
  - **Callers:** `walk` is called by `v3_smoke.measure` (the tab) with no `forced` — unchanged; `v3_measure` (Task 8) passes it.
  - **Sides:** a forced flag has no side; the strength family is long-only, the test covers a short.
  - **Twins:** a missed order's market twin walks the same `ctx`, so it is forced out at the same close.
  - **Failure path:** a Gate listing always carries the five fields (`gate_futures._spec_from` defaults them), so `contract_of` changes nothing for a real coin; a malformed listing now raises by name where it used to trade at a silent 1x.

- [ ] **Step 10: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_engine.py tradingagents/v3_smoke.py tests/test_v3_engine.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
feat(v3): the engine learns a forced exit (v3_strength's weekly rank, why RANK, at the close at the market) and reads a contract from its listing one way, refusing a missing field by name

Backtest v3 Part 2a, Task 2 (plan docs/superpowers/plans/2026-10-23-backtest-v3-part2a-families-and-proof.md).
- walk(forced=None): the rule of before when None; a stop or target the candle reached first still wins; twins are forced out too
- contract_of: one mapping for the smoke run, the tab and Part 2a's measurement (Part 1 final review: "contract-field mapping in one tested helper"; a min_lev of 0 or a None field now names the field)
- harddev: callers (the tab's v3_smoke.measure passes no forced: unchanged), sides (a short is forced out too), twins (a missed order's twin is forced out at the same close), failure path (every Gate listing carries the five fields; a malformed one now raises by name instead of trading at a silent 1x)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 3: The universe and its cross-coin data

**Files:**
- Create: `tradingagents/v3_universe.py`
- Test: `tests/test_v3_universe.py`

**Interfaces:**
- Consumes: `positions_view.fmt_when`, `venue.kind`, `venue.name`, `fx.trading_symbols`, `fx.contract_spec`, `fx.klines`.
- Produces:
  - constants `DAY_MS`, `WINDOW_DAYS = 365`, `LIQUID_TOP = 50`, `VALUE_DAYS = 30`, `VOL_DAYS = 60`, `STRENGTH_DAYS = 14`, `MOOD_DAYS = 50`, `CALM_KINDS`, `BTC = "BTC_USDT"`, `VERSION = 1`, `PLAN_FILE` (`<repo>/research/v3/plan.json`), `SURVIVORSHIP`, `SIZE_NOTE`;
  - `month_key(ms) -> "YYYY-MM"`, `month_start(ms) -> ms`, `months_between(start_ms, end_ms) -> [month start ms]`, `weekday(ms) -> 0..6` (Monday 0, UTC), `mondays_between(start_ms, end_ms) -> [ms]`;
  - `daily_of(df, end_ms) -> {"t", "c", "v"}` (closed candles only), `traded_value(daily, contract_size, at_ms) -> float`, `realized_vol(daily, at_ms) -> float | None`, `return_14(daily, at_ms) -> float | None`, `mood_of(daily, from_ms) -> {"t", "up"}`;
  - `build(dailies, kinds, sizes, end_ms, *, skipped=None, venue_name="", built_s=None) -> plan` and `collect(*, fx=None, end_ms=None, kind_of=None, log=print) -> plan`;
  - the plan dict: `version`, `venue`, `built`, `built_s`, `start_ms`, `end_ms`, `start`, `end`, `months` (["YYYY-MM"]), `liquid` {month: [symbols by value]}, `value` {month: [dollars]}, `calm` {month: [symbols]}, `vol` {month: {symbol: vol}}, `strength` {str(Monday ms): [symbols best first]}, `mood` {"t": [close ms], "up": [0/1]}, `kinds`, `sizes`, `coins`, `skipped` {symbol: why}, `notes`;
  - `save(plan, path=PLAN_FILE) -> Path`, `load(path=PLAN_FILE) -> plan` (refuses another version);
  - `member_mask(plan, groups, sym, at_ms) -> [bool]`, `mood_at(plan, at_ms) -> [bool | None]`, `rank_at(plan, sym, monday_ms) -> int | None`.

- [ ] **Step 1: Write the failing test** — `tests/test_v3_universe.py`:

```python
"""The Backtest v3 universe (decisions doc docs/superpowers/specs/2026-10-23-
backtest-v3-part2-decisions.md, "The universe"): who is liquid and who is calm,
month by month, BTC's mood and the Monday ranks — each worked from daily
candles CLOSED before it is used. Every day here is a real UTC day; day k
opens at FIRST + k days (Jul 01, 2026 is day 0, Sep 01 day 62, Oct 01 day 92,
the window ends Nov 01, 2026 00:00 UTC, after day 122)."""
import calendar
import math

import pandas as pd
import pytest

from tradingagents import v3_universe as vu

DAY = 86_400_000
FIRST = calendar.timegm((2026, 7, 1, 0, 0, 0)) * 1000
END = calendar.timegm((2026, 11, 1, 0, 0, 0)) * 1000        # a Sunday
SEP1, OCT1 = FIRST + 62 * DAY, FIRST + 92 * DAY
OCT5, SEP7 = FIRST + 96 * DAY, FIRST + 68 * DAY             # two Mondays


def _daily(first_k, closes, vols):
    return {"t": [FIRST + (first_k + j) * DAY for j in range(len(closes))],
            "c": list(closes), "v": list(vols)}


def _alt(lo, hi, n=123):
    """Day k closes at `hi` when k is odd, `lo` when even."""
    return [hi if k % 2 else lo for k in range(n)]


def _world():
    """BTC v=100 closing 100/102 on alternate days; AAA v=50, 100/101; BBB v=20,
    100/110; CCC v=1 at 100; NEW only from Sep 10 (day 71), v=1000, closing
    100, 101, 102 ... (rising a dollar a day); XAU a metal; AAPL a stock. Every
    contract size is 1."""
    d = {"BTC_USDT": _daily(0, _alt(100.0, 102.0), [100.0] * 123),
         "AAA_USDT": _daily(0, _alt(100.0, 101.0), [50.0] * 123),
         "BBB_USDT": _daily(0, _alt(100.0, 110.0), [20.0] * 123),
         "CCC_USDT": _daily(0, [100.0] * 123, [1.0] * 123),
         "NEW_USDT": _daily(71, [100.0 + j for j in range(52)], [1000.0] * 52)}
    kinds = {**dict.fromkeys(d, "crypto"), "XAU_USDT": "metals", "AAPL_USDT": "stocks"}
    sizes = dict.fromkeys(d, 1.0)
    return d, kinds, sizes


@pytest.fixture()
def plan(monkeypatch):
    monkeypatch.setattr(vu, "WINDOW_DAYS", 61)        # Sep 01 - Nov 01, 2026: two months
    monkeypatch.setattr(vu, "LIQUID_TOP", 3)
    d, kinds, sizes = _world()
    return vu.build(d, kinds, sizes, END, built_s=END / 1000)


def test_traded_value_sums_the_30_days_that_closed_by_the_month_start():
    # 40 days from Aug 22 (day 52): 10 contracts of size 0.5 at 2.0 = $10 a day, except the
    # day that opens Sep 30 (closes at Oct 01 00:00, so it counts) at $100, and the day that
    # opens Oct 01 (still forming at the month start, so it never counts) at $1,000
    vols = [10.0] * 40
    vols[39] = 100.0                 # day 91, Sep 30 (index 39 from day 52)
    daily = _daily(52, [2.0] * 41, vols + [1000.0])
    # the 30 days opening Sep 01 - Sep 30: 29 x $10 + $100 x 0.5 x 2.0 = $390
    assert vu.traded_value(daily, 0.5, OCT1) == pytest.approx(29 * 10.0 + 100.0)


def test_realized_vol_needs_all_60_returns_and_unknown_is_never_calm():
    # 61 closes alternating 100/102: every log return is +/- ln(1.02), mean 0
    daily = _daily(0, _alt(100.0, 102.0, 92), [1.0] * 92)
    assert vu.realized_vol(daily, OCT1) == pytest.approx(math.log(1.02))
    # one of those 61 days missing: no 60-day figure
    hole = {k: v[:60] + v[61:] for k, v in daily.items()}
    assert vu.realized_vol(hole, OCT1) is None


def test_the_14_day_return_reads_the_close_at_the_instant_and_14_days_before():
    # NEW closes 100 + (k - 71); at Oct 05 00:00 the candle that just closed is day 95 (124),
    # 14 days earlier day 81 (110): 124 / 110 - 1
    d, _kinds, _sizes = _world()
    assert vu.return_14(d["NEW_USDT"], OCT5) == pytest.approx(124 / 110 - 1)
    assert vu.return_14(d["NEW_USDT"], SEP7) is None, "day 67 is before NEW's first, day 71"


def test_the_liquid_list_is_the_top_by_value_at_each_month_start(plan):
    # Sep 01 (days 32-61): BTC 100 x (15 x 100 + 15 x 102) = 303,000; AAA 50 x 3,015 = 150,750;
    # BBB 20 x 3,150 = 63,000; CCC 3,000; NEW has no candles yet. The top 3:
    assert plan["liquid"]["2026-09"] == ["BTC_USDT", "AAA_USDT", "BBB_USDT"]
    assert plan["value"]["2026-09"] == [303_000, 150_750, 63_000]
    # Oct 01 (days 62-91): NEW traded 1,000 x (100 + 101 + ... + 120) = 2,310,000 over its 21
    # days and goes first; BBB drops out
    assert plan["liquid"]["2026-10"] == ["NEW_USDT", "BTC_USDT", "AAA_USDT"]
    assert plan["value"]["2026-10"][0] == 2_310_000


def test_calm_is_the_calm_kinds_plus_the_quietest_third_of_the_liquid(plan):
    # Sep: vols AAA ln(1.01) < BTC ln(1.02) < BBB ln(1.1); a third of 3 is 1: AAA, after the metal
    assert plan["calm"]["2026-09"] == ["XAU_USDT", "AAA_USDT"]
    assert plan["vol"]["2026-09"]["AAA_USDT"] == pytest.approx(math.log(1.01), abs=1e-6)
    # Oct: NEW has 21 days, not 61 - no 60-day vol, so it cannot be calm; of AAA and BTC the
    # third (rounded up) is AAA
    assert plan["calm"]["2026-10"] == ["XAU_USDT", "AAA_USDT"]
    assert "NEW_USDT" not in plan["vol"]["2026-10"]
    # a stock and a coin that never ranked are in no group
    assert plan["coins"] == ["AAA_USDT", "BBB_USDT", "BTC_USDT", "NEW_USDT", "XAU_USDT"]


def test_membership_is_by_the_month_an_instant_falls_in(plan):
    mid_sep, mid_oct, mid_nov = SEP1 + 14 * DAY, OCT1 + 14 * DAY, END + 14 * DAY
    assert vu.member_mask(plan, ("liquid",), "BBB_USDT", [mid_sep, mid_oct]) == [True, False]
    assert vu.member_mask(plan, ("liquid", "calm"), "XAU_USDT",
                          [mid_sep, mid_oct, mid_nov]) == [True, True, False]
    assert vu.member_mask(plan, (), "BTC_USDT", [mid_sep]) == [False]


def test_the_monday_ranks_order_the_months_liquid_coins_by_14_day_return(plan):
    # Oct 05: NEW +12.7%; BTC and AAA alternate with an even 14-day lag, so 0 (ties by name)
    assert plan["strength"][str(OCT5)] == ["NEW_USDT", "AAA_USDT", "BTC_USDT"]
    assert vu.rank_at(plan, "NEW_USDT", OCT5) == 1 and vu.rank_at(plan, "BTC_USDT", OCT5) == 3
    assert vu.rank_at(plan, "BBB_USDT", OCT5) is None, "not liquid in October"
    # Sep 07: September's liquid three, all at 0
    assert plan["strength"][str(SEP7)] == ["AAA_USDT", "BBB_USDT", "BTC_USDT"]
    # Aug 31 is before the plan's months: no one is liquid there
    assert plan["strength"][str(SEP7 - 7 * DAY)] == []


def test_btcs_mood_is_known_only_once_its_day_has_closed(plan):
    # the 50-day average of closes alternating 100/102 is 101: an odd day (102) is up. Day 63
    # (Sep 02, 102) closes at FIRST + 64 days
    close_63 = FIRST + 64 * DAY
    assert vu.mood_at(plan, [close_63, close_63 - 1]) == [True, False], \
        "a millisecond before day 63 closes, the last close is day 62's 100"
    assert vu.mood_at(plan, [END + 2 * DAY]) == [None], "no close of the last day: unknown"


def test_the_plan_round_trips_and_an_old_version_is_refused(plan, tmp_path):
    p = vu.save(plan, tmp_path / "v3" / "plan.json")
    assert vu.load(p) == plan
    p.write_text(p.read_text(encoding="utf-8").replace('"version":1', '"version":0'),
                 encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        vu.load(p)


def test_the_plan_names_its_window_and_its_limits(plan):
    assert plan["end"].endswith(("am", "pm")) and ", 2026 " in plan["end"]
    assert plan["months"] == ["2026-09", "2026-10"]
    assert any("survivorship" in n for n in plan["notes"])
    assert any("TODAY's contract size" in n for n in plan["notes"])


class FakeFx:
    """Daily frames of the world above plus the forming day (Nov 01, volume 0)."""

    def __init__(self):
        self.d, _k, _s = _world()

    def trading_symbols(self):
        return ["AAA_USDT", "BAD_USDT", "BTC_USDT", "NIL_USDT", "XAU_USDT"]

    def contract_spec(self, sym):
        return {"contractSize": 0.0 if sym == "NIL_USDT" else 1.0}

    def klines(self, sym, iv, limit):
        if sym == "BAD_USDT":
            raise RuntimeError("no Day1 candles for BAD_USDT")
        d = self.d[sym]
        t = d["t"] + [END]
        return pd.DataFrame({"Date": pd.to_datetime(t, unit="ms"), "Close": d["c"] + [d["c"][-1]],
                             "Volume": d["v"] + [0.0]})


def test_collect_cuts_the_forming_day_and_names_every_coin_it_could_not_read(monkeypatch):
    monkeypatch.setattr(vu, "WINDOW_DAYS", 61)
    kinds = {"AAA_USDT": "crypto", "BAD_USDT": "crypto", "BTC_USDT": "crypto",
             "NIL_USDT": "crypto", "XAU_USDT": "metals"}
    got = vu.collect(fx=FakeFx(), end_ms=END, kind_of=kinds.get, log=lambda *a: None)
    assert got["skipped"] == {"BAD_USDT": "RuntimeError: no Day1 candles for BAD_USDT",
                              "NIL_USDT": "contract size 0: its traded value cannot be worked out"}
    # the forming Nov 01 candle never counts: BTC's last mood is day 122's close, at END
    assert got["mood"]["t"][-1] == END
    assert got["liquid"]["2026-10"] == ["BTC_USDT", "AAA_USDT"]
    assert got["calm"]["2026-10"] == ["XAU_USDT", "AAA_USDT"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_v3_universe.py -q`
Expected: `ImportError: cannot import name 'v3_universe' from 'tradingagents'` (1 error during collection).

- [ ] **Step 3: Implement** — `tradingagents/v3_universe.py`:

```python
"""THE V3 UNIVERSE — which coins each Backtest v3 family may trade, month by
month, and the cross-coin data two families read (BTC's mood, the weekly
strength ranks).

Spec: docs/superpowers/specs/2026-10-22-backtest-v3-design.md (Part 2, the
universe words); decisions: docs/superpowers/specs/2026-10-23-backtest-v3-
part2-decisions.md ("The universe"). Built on this PC from daily candles
before a run and written as the run's plan file (`PLAN_FILE`), so every
machine reads the same universe.

* LIQUID crypto: kind "crypto", the top 50 by 30-day traded value at each
  month start. A day's traded value is its Volume (in contracts) x the
  contract size x its close — TODAY's contract size, said in the file.
* CALM contracts: kinds metals, indices and forex every month, plus the
  liquid crypto in the calmest third by 60-day realized volatility (the
  standard deviation of daily log returns) at each month start.
* BTC's MOOD: each daily close against its 50-day average, known only once
  that day's candle has closed.
* STRENGTH ranks: each Monday 00:00 UTC, that month's liquid crypto by 14-day
  return (the close at Monday 00:00 against the close 14 days before), best
  first.

Every number is worked from candles CLOSED before the instant it is used at,
so no coin is chosen with hindsight. Candidates are the contracts the
exchange trades TODAY: a coin delisted during the year is missing
(survivorship bias, said beside every verdict).
"""
from __future__ import annotations

import bisect
import calendar
import json
import math
import os
import statistics
import time
from pathlib import Path

DAY_MS = 86_400_000
WINDOW_DAYS = 365
LIQUID_TOP = 50
VALUE_DAYS = 30
VOL_DAYS = 60
STRENGTH_DAYS = 14
MOOD_DAYS = 50
CALM_KINDS = ("metals", "indices", "forex")
BTC = "BTC_USDT"
VERSION = 1
PLAN_FILE = Path(__file__).resolve().parent.parent / "research" / "v3" / "plan.json"
SURVIVORSHIP = ("Candidates are the contracts the exchange trades today: a coin delisted "
                "during the year is missing (survivorship bias).")
SIZE_NOTE = ("A day's traded value is its volume in contracts x TODAY's contract size x "
             "its close.")


def month_key(ms: int) -> str:
    """"YYYY-MM" of the UTC month an instant falls in."""
    g = time.gmtime(int(ms) // 1000)
    return f"{g.tm_year:04d}-{g.tm_mon:02d}"


def month_start(ms: int) -> int:
    g = time.gmtime(int(ms) // 1000)
    return calendar.timegm((g.tm_year, g.tm_mon, 1, 0, 0, 0)) * 1000


def _next_month(ms: int) -> int:
    g = time.gmtime(int(ms) // 1000)
    y, m = g.tm_year + (g.tm_mon == 12), g.tm_mon % 12 + 1
    return calendar.timegm((y, m, 1, 0, 0, 0)) * 1000


def months_between(start_ms: int, end_ms: int) -> list[int]:
    """The UTC month starts of every month that overlaps [start_ms, end_ms)."""
    out, m = [], month_start(start_ms)
    while m < int(end_ms):
        out.append(m)
        m = _next_month(m)
    return out


def weekday(ms: int) -> int:
    """Monday 0 ... Sunday 6, in UTC (Jan 01, 1970 was a Thursday)."""
    return (int(ms) // DAY_MS + 3) % 7


def mondays_between(start_ms: int, end_ms: int) -> list[int]:
    """Every Monday 00:00 UTC in [start_ms, end_ms)."""
    d = -(-int(start_ms) // DAY_MS)
    while weekday(d * DAY_MS):
        d += 1
    out = []
    while d * DAY_MS < int(end_ms):
        out.append(d * DAY_MS)
        d += 7
    return out


def daily_of(df, end_ms: int) -> dict:
    """A Date/Close/Volume frame -> {"t": opens ms, "c", "v"}, CLOSED candles
    only: the ones that ended by `end_ms`."""
    t = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    keep = t + DAY_MS <= int(end_ms)
    return {"t": [int(x) for x in t[keep]],
            "c": [float(x) for x in df["Close"].to_numpy()[keep]],
            "v": [float(x) for x in df["Volume"].to_numpy()[keep]]}


def _span(daily: dict, lo_ms: int, hi_ms: int) -> tuple[int, int]:
    """The candles OPENING in [lo_ms, hi_ms)."""
    t = daily["t"]
    return bisect.bisect_left(t, int(lo_ms)), bisect.bisect_left(t, int(hi_ms))


def traded_value(daily: dict, contract_size: float, at_ms: int) -> float:
    """What traded in the VALUE_DAYS daily candles that closed by `at_ms`, in
    dollars: the sum of volume x contract size x close."""
    a, b = _span(daily, at_ms - VALUE_DAYS * DAY_MS, at_ms)
    return sum(daily["v"][k] * contract_size * daily["c"][k] for k in range(a, b))


def realized_vol(daily: dict, at_ms: int) -> float | None:
    """The standard deviation of the VOL_DAYS daily log returns that closed by
    `at_ms` (VOL_DAYS + 1 closes); None when any of those days is missing:
    unknown is never calm."""
    a, b = _span(daily, at_ms - (VOL_DAYS + 1) * DAY_MS, at_ms)
    closes = daily["c"][a:b]
    if len(closes) < VOL_DAYS + 1 or min(closes) <= 0:
        return None
    rets = [math.log(y / x) for x, y in zip(closes, closes[1:], strict=False)]
    return statistics.pstdev(rets)


def _close_at(daily: dict, close_ms: int) -> float | None:
    """The close of the daily candle that ENDED at `close_ms`, or None."""
    k = bisect.bisect_left(daily["t"], int(close_ms) - DAY_MS)
    if k < len(daily["t"]) and daily["t"][k] == int(close_ms) - DAY_MS:
        return daily["c"][k]
    return None


def return_14(daily: dict, at_ms: int) -> float | None:
    """The STRENGTH_DAYS return at `at_ms`: the close at that instant against
    the close STRENGTH_DAYS before it; None when either candle is missing."""
    now, then = _close_at(daily, at_ms), _close_at(daily, at_ms - STRENGTH_DAYS * DAY_MS)
    if now is None or then is None or then <= 0:
        return None
    return now / then - 1.0


def mood_of(daily: dict, from_ms: int) -> dict:
    """BTC's mood at each daily close from `from_ms` on: {"t": close ms, "up":
    1 when that close is above the average of the MOOD_DAYS closes ending with
    it, else 0} — only closes with MOOD_DAYS of history."""
    t, c = daily["t"], daily["c"]
    out_t, out_up, total = [], [], 0.0
    for k, close in enumerate(c):
        total += close
        if k >= MOOD_DAYS:
            total -= c[k - MOOD_DAYS]
        if k >= MOOD_DAYS - 1 and t[k] + DAY_MS >= int(from_ms):
            out_t.append(t[k] + DAY_MS)
            out_up.append(int(close > total / MOOD_DAYS))
    return {"t": out_t, "up": out_up}


def build(dailies: dict, kinds: dict, sizes: dict, end_ms: int, *, skipped=None,
          venue_name: str = "", built_s: float | None = None) -> dict:
    """The plan: membership per month, BTC's mood and the Monday ranks over
    the WINDOW_DAYS before `end_ms` (a UTC midnight: every daily candle used
    closed by then). `dailies` {symbol: daily_of(...)}, `kinds` {symbol:
    venue kind} for every candidate, `sizes` {symbol: contract size}."""
    from tradingagents.positions_view import fmt_when

    end_ms = int(end_ms)
    start_ms = end_ms - WINDOW_DAYS * DAY_MS
    crypto = sorted(s for s in dailies if kinds.get(s) == "crypto" and sizes.get(s))
    calm_kind = sorted(s for s, k in kinds.items() if k in CALM_KINDS)
    liquid, value, calm, vol = {}, {}, {}, {}
    for m in months_between(start_ms, end_ms):
        key = month_key(m)
        ranked = sorted(((traded_value(dailies[s], sizes[s], m), s) for s in crypto),
                        key=lambda x: (-x[0], x[1]))
        top = [(v, s) for v, s in ranked if v > 0][:LIQUID_TOP]
        liquid[key] = [s for _v, s in top]
        value[key] = [round(v) for v, _s in top]
        vols = []
        for s in liquid[key]:
            v = realized_vol(dailies[s], m)
            if v is not None:
                vols.append((v, s))
        vols.sort()
        calmest = vols[:math.ceil(len(vols) / 3)]
        calm[key] = calm_kind + [s for _v, s in calmest]
        vol[key] = {s: round(v, 6) for v, s in vols}
    strength = {}
    for monday in mondays_between(start_ms - 7 * DAY_MS, end_ms):
        rets = [(return_14(dailies[s], monday), s) for s in liquid.get(month_key(monday), [])]
        strength[str(monday)] = [s for r, s in sorted(((r, s) for r, s in rets if r is not None),
                                                      key=lambda x: (-x[0], x[1]))]
    if BTC not in dailies:
        raise ValueError(f"{BTC} has no daily candles: its mood cannot be worked out")
    coins = sorted({s for g in (liquid, calm) for members in g.values() for s in members})
    built = time.time() if built_s is None else float(built_s)
    return {"version": VERSION, "venue": venue_name, "built": fmt_when(built),
            "built_s": built, "start_ms": start_ms, "end_ms": end_ms,
            "start": fmt_when(start_ms / 1000), "end": fmt_when(end_ms / 1000),
            "months": sorted(liquid), "liquid": liquid, "value": value, "calm": calm,
            "vol": vol, "strength": strength,
            "mood": mood_of(dailies[BTC], start_ms - 7 * DAY_MS),
            "kinds": {s: kinds[s] for s in sorted(set(coins) | {BTC}) if s in kinds},
            "sizes": {s: sizes[s] for s in crypto},
            "coins": coins, "skipped": dict(skipped or {}),
            "notes": [SURVIVORSHIP, SIZE_NOTE]}


def collect(*, fx=None, end_ms: int | None = None, kind_of=None, log=print) -> dict:
    """Read every candidate's daily candles from the exchange and build the
    plan. A candidate whose candles or listing cannot be read is NAMED in
    `skipped`, never dropped quietly."""
    from tradingagents import venue

    if fx is None:
        from tradingagents.dataflows import exchange as fx
    kind_of = kind_of or venue.kind
    now_ms = int(time.time() * 1000)
    end_ms = int(end_ms) if end_ms is not None else now_ms - now_ms % DAY_MS
    first = month_start(end_ms - WINDOW_DAYS * DAY_MS) - (VOL_DAYS + 2) * DAY_MS
    days = -(-(now_ms - first) // DAY_MS) + 2
    syms = sorted(fx.trading_symbols())
    kinds = {s: kind_of(s) for s in syms}
    dailies, sizes, skipped = {}, {}, {}
    crypto = [s for s in syms if kinds[s] == "crypto"]
    for n, s in enumerate(crypto, 1):
        try:
            sizes[s] = float(fx.contract_spec(s).get("contractSize") or 0.0)
            if sizes[s] <= 0:
                skipped[s] = "contract size 0: its traded value cannot be worked out"
                continue
            dailies[s] = daily_of(fx.klines(s, "Day1", days), end_ms)
        except Exception as exc:                               # noqa: BLE001
            skipped[s] = f"{type(exc).__name__}: {str(exc)[:160]}"
        if n % 100 == 0:
            log(f"  daily candles: {n} of {len(crypto)} crypto contracts")
    return build(dailies, kinds, sizes, end_ms, skipped=skipped, venue_name=venue.name())


def save(plan: dict, path: Path | str = PLAN_FILE) -> Path:
    """Write the plan whole (a temp file swapped in)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(plan, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)
    return p


def load(path: Path | str = PLAN_FILE) -> dict:
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("version") != VERSION:
        raise ValueError(f"{path}: plan version {plan.get('version')!r}, this code reads {VERSION}")
    return plan


def member_mask(plan: dict, groups, sym: str, at_ms) -> list[bool]:
    """Per instant: is `sym` in any of `groups` ("liquid", "calm") in the
    month that instant falls in. An instant outside the plan's months is no
    member."""
    months = {m for m in plan["months"] if any(sym in plan[g].get(m, ()) for g in groups)}
    return [month_key(ms) in months for ms in at_ms]


def mood_at(plan: dict, at_ms) -> list[bool | None]:
    """Per instant: BTC's mood from its last daily candle CLOSED by then —
    True above its 50-day average, False not, None when no close of the last
    day is in the plan (unknown)."""
    t, up = plan["mood"]["t"], plan["mood"]["up"]
    out = []
    for ms in at_ms:
        k = bisect.bisect_right(t, int(ms)) - 1
        out.append(bool(up[k]) if k >= 0 and int(ms) - t[k] < DAY_MS else None)
    return out


def rank_at(plan: dict, sym: str, monday_ms: int) -> int | None:
    """`sym`'s place (1 = best) in the strength ranking taken at that Monday
    00:00 UTC, or None when it is not ranked there."""
    ranked = plan["strength"].get(str(int(monday_ms)))
    if not ranked or sym not in ranked:
        return None
    return ranked.index(sym) + 1
```

- [ ] **Step 4: Run the test to verify it passes, then lint**

Run: `.venv/Scripts/python -m pytest tests/test_v3_universe.py -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_universe.py tests/test_v3_universe.py`
Expected: `11 passed`, then `All checks passed!`

- [ ] **Step 5: The harddev hunt** (name each in the commit message):
  - **No hindsight:** value, volatility and the 14-day return read only daily candles that CLOSED by the month start or the Monday (`_span` is `[lo, hi)` of candle OPENS); the forming candle is cut by `daily_of`.
  - **Failure path:** a candidate whose listing or candles cannot be read, or whose lot size is 0, is NAMED in `skipped`; BTC missing raises (the mood cannot be worked out).
  - **Units:** traded value is dollars (`Volume` is contracts on Gate); volatility is a fraction of a day.
  - **State:** `collect` reads venue kinds through `venue.kind` (the contract list, cached an hour); it makes one `klines` call per crypto contract (596 on Oct 23, 2026: 352 s).

- [ ] **Step 6: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_universe.py tests/test_v3_universe.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
feat(v3): the Backtest v3 universe - liquid (top 50 by 30-day traded value) and calm (metals, indices, forex + the quietest third) per month, BTC's mood and the Monday strength ranks, from closed daily candles, as the run's plan file

Backtest v3 Part 2a, Task 3. Survivorship said in the file: only contracts the exchange trades today. Every coin it cannot read is named in skipped.
- harddev: no hindsight (value, volatility and the 14-day return read only daily candles closed by the instant; the forming day is cut), failure path (an unreadable coin or a lot of 0 is named in skipped; no BTC raises), units (dollars; volume is in contracts), state (one klines call per crypto contract)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 4: The four families

**Files:**
- Create: `tradingagents/v3_families.py`
- Test: `tests/test_v3_families.py`

**Interfaces:**
- Consumes: Task 3's `v3_universe.weekday`, `rank_at`, `member_mask`; `v3_rules.sma`, `atr`, `ATR_N`, `TRAIL_ATR`; `pro_indicators.donchian`; `backtest_report.row_code`.
- Produces:
  - `LEAD_BARS = 300`, `BARS_PER_DAY`, `TREND_LAG_DAYS = 5`, `BREAKOUT_MA_DAYS = 100`, `SNAP_N = 20`, `SNAP_MAX_BARS = 24`;
  - `FAMILIES` {family: {"param", "settings", "tfs", "long", "short"}} and `FILTERS = ("none", "btc_mood", "busy_hours", "funding_side", "funding_minutes")`;
  - `setting_key(family, value) -> "n20" | "k1.5"`, `combo_key(family, key, tf, filt) -> "family|key|tf|filt"`, `combos() -> [(family, key, tf, filt)]` (70), `judged() -> [(family, tf, filt)]` (30), `verdict_id(family, tf, filt) -> str` (8 characters, `row_code(..., res="v3")`);
  - `lookback(family, value, tf) -> int`, `lead(family, value, tf) -> int`, `exit_spec(family, value, tf) -> dict` (the engine's shape);
  - `rule(family, value, tf, bars, *, sym="", plan=None) -> [+1 | -1 | 0]` (before the universe and the filters), `forced(family, value, tf, bars, *, sym="", plan=None) -> [bool] | None`, `entry_days(family, bars) -> [bool]`, `sides_allowed(family, sym, plan, at_ms) -> ([bool], [bool])`, `applies(plan, family, sym) -> bool`.
- Naming: no module-level function here starts with `test` (pytest would collect one imported into a test).

- [ ] **Step 1: Write the failing test** — `tests/test_v3_families.py`:

```python
"""The four Backtest v3 families (decisions doc docs/superpowers/specs/2026-10-23-
backtest-v3-part2-decisions.md, "The families"): each rule's signals worked by
hand on small candle series, their exits, their lead-ins, their universes, and
the count of combinations the luck correction divides by."""
import calendar

import pytest

from tradingagents import v3_families as vf

DAY = 86_400_000
OCT1 = calendar.timegm((2026, 10, 1, 0, 0, 0)) * 1000        # a Thursday
MONDAYS = [OCT1 + k * DAY for k in (4, 11, 18, 25)]          # Oct 05, 12, 19, 26, 2026


def _bars(c, h=None, lo=None, t0=OCT1, bar=DAY):
    c = [float(x) for x in c]
    return {"t": [t0 + k * bar for k in range(len(c))], "o": c, "c": c,
            "h": [float(x) for x in (h if h is not None else c)],
            "l": [float(x) for x in (lo if lo is not None else c)]}


def test_seventy_combinations_and_thirty_verdicts_are_counted_whether_or_not_they_trade():
    # (3 + 2 + 2 + 2 settings) x their timeframes = 6 + 2 + 2 + 4 = 14, each alone and with each
    # of the 4 filters: 70 combinations (the luck correction's count); one verdict per family,
    # timeframe and filter: 10 + 5 + 5 + 10 = 30
    assert len(vf.combos()) == len(set(vf.combos())) == 70
    assert len(vf.judged()) == 30
    assert ("v3_trend", "n100", "4h", "funding_minutes") in vf.combos()
    assert ("v3_snap", "k1.5", "1h", "none") in vf.combos()
    assert vf.setting_key("v3_snap", 2.0) == "k2" and vf.setting_key("v3_strength", 3) == "k3"
    ids = {vf.verdict_id(*g) for g in vf.judged()}
    assert len(ids) == 30, "every verdict its own id"


def test_a_trend_longs_above_a_rising_average_and_calm_coins_short_the_mirror():
    # n = 3 on daily candles closing 1, 2, ... 10: the 3-day average at candle i is i, under the
    # close i + 1, and 5 days earlier it was i - 5 - but it exists only from candle 2, so the
    # first candle with both is 7
    assert vf.rule("v3_trend", 3, "1d", _bars(range(1, 11))) == [0] * 7 + [1] * 3
    # closing 10, 9, ... 1: the average 11 - i sits over the close and under its value 5 days
    # earlier - a short
    assert vf.rule("v3_trend", 3, "1d", _bars(range(10, 0, -1))) == [0] * 7 + [-1] * 3


def test_a_trend_on_4h_reads_six_candles_a_day():
    # n = 1 day on 4h candles is a 6-candle average, and "5 days earlier" is 30 candles: with
    # rising closes the first candle with both is 5 + 30 = 35
    assert vf.rule("v3_trend", 1, "4h", _bars(range(1, 41), bar=4 * 3_600_000)) == \
        [0] * 35 + [1] * 5


def _drift(step, jump):
    """110 daily candles drifting `step` a day from 100, candle 108 jumping to `jump`; every
    candle's high and low half a dollar either side of its close."""
    c = [100 + step * k for k in range(110)]
    c[108] = jump
    return _bars(c, [x + 0.5 for x in c], [x - 0.5 for x in c])


def test_a_breakout_closes_over_the_last_n_days_highs_only_while_the_100_day_average_rises():
    # N = 3. Candle i's close, 100 + 0.1i, is 0.4 UNDER the high of candle i - 1, so the drift
    # never breaks out; candle 108 jumps to 115.0 over that candle's 111.2. The 100-day average
    # at 108 against 103: (110.4 + 110.5 + 110.6 + 110.7 + 115.0 - 100.4 - 100.5 - 100.6 - 100.7
    # - 100.8) / 100 = +0.542, rising. (Before candle 104 the average 5 days back does not exist)
    assert vf.rule("v3_breakout", 3, "1d", _drift(0.1, 115.0)) == [0] * 108 + [1, 0]
    # the same jump while the average FALLS (a drift of -0.1: -0.242 over those 5 days): no long
    assert vf.rule("v3_breakout", 3, "1d", _drift(-0.1, 115.0)) == [0] * 110
    # the mirror: a falling drift whose candle 108 drops to 85.0, under the last 3 days' lows
    # (88.8 at the lowest), while the average falls by 0.542: a calm contract's short
    assert vf.rule("v3_breakout", 3, "1d", _drift(-0.1, 85.0)) == [0] * 108 + [-1, 0]


def _ranked_plan():
    a_to_g = [f"{x}_USDT" for x in "ABCDEFG"]
    return {"months": ["2026-10"], "liquid": {"2026-10": a_to_g}, "calm": {"2026-10": []},
            "strength": {str(MONDAYS[0]): a_to_g,                                     # D 4th
                         str(MONDAYS[1]): ["D_USDT"] + [s for s in a_to_g if s != "D_USDT"],
                         str(MONDAYS[2]): [s for s in a_to_g if s != "D_USDT"] + ["D_USDT"],
                         str(MONDAYS[3]): ["A_USDT"]}}                                # D unranked


def test_strength_longs_a_top_k_coin_on_its_monday_and_forces_it_out_past_the_top_2k():
    plan, bars = _ranked_plan(), _bars([100.0] * 28)                  # Oct 01 - Oct 28, 2026
    mondays = [4, 11, 18, 25]
    # K = 3: D is 4th (Oct 05), 1st (Oct 12), 7th (Oct 19), unranked (Oct 26)
    got = vf.rule("v3_strength", 3, "1d", bars, sym="D_USDT", plan=plan)
    assert [got[i] for i in mondays] == [0, 1, 0, 0] and sum(got) == 1
    out = vf.forced("v3_strength", 3, "1d", bars, sym="D_USDT", plan=plan)
    assert [out[i] for i in mondays] == [False, False, True, True], "7th > 2K = 6; unranked"
    assert sum(out) == 2, "only Monday candles force anything"
    # K = 5: 4th is in, and 7th is inside 2K = 10
    got = vf.rule("v3_strength", 5, "1d", bars, sym="D_USDT", plan=plan)
    assert [got[i] for i in mondays] == [1, 1, 0, 0]
    out = vf.forced("v3_strength", 5, "1d", bars, sym="D_USDT", plan=plan)
    assert [out[i] for i in mondays] == [False, False, False, True]
    assert vf.forced("v3_trend", 20, "1d", bars) is None
    assert [i for i, x in enumerate(vf.entry_days("v3_strength", bars)) if x] == mondays


def test_a_snap_back_signals_a_close_k_atrs_past_its_20_candle_average():
    # 20 flat candles (high 100.5, low 99.5, close 100: a true range of 1.0), then candle 20 with
    # high 100.0, low 98.0, close 98.3 (true range 2.0). Its 20-candle average is
    # (19 x 100 + 98.3) / 20 = 99.915 and ATR(20) (19 x 1.0 + 2.0) / 20 = 1.05: k = 1.5 needs a
    # close at or under 99.915 - 1.575 = 98.34 (98.3 is), k = 2.0 under 97.815 (it is not)
    h, lo = [100.5] * 20 + [100.0], [99.5] * 20 + [98.0]
    dip = _bars([100.0] * 20 + [98.3], h, lo, bar=3_600_000)
    assert vf.rule("v3_snap", 1.5, "1h", dip) == [0] * 20 + [1]
    assert vf.rule("v3_snap", 2.0, "1h", dip) == [0] * 21
    # the mirror: high 102.0, low 100.0, close 101.7 - over 100.085 + 1.575 = 101.66, a short
    pop = _bars([100.0] * 20 + [101.7], [100.5] * 20 + [102.0], [99.5] * 20 + [100.0],
                bar=3_600_000)
    assert vf.rule("v3_snap", 1.5, "1h", pop) == [0] * 20 + [-1]
    # a market that never moved has no range to measure a snap by
    assert vf.rule("v3_snap", 1.5, "1h", _bars([100.0] * 21, bar=3_600_000)) == [0] * 21


def test_each_family_exits_by_its_own_rule():
    assert vf.exit_spec("v3_trend", 50, "4h") == {"kind": "trail", "atr_mult": 3.0, "ma_n": 300}
    assert vf.exit_spec("v3_trend", 20, "1d")["ma_n"] == 20
    assert vf.exit_spec("v3_breakout", 20, "1d") == {"kind": "trail", "atr_mult": 3.0,
                                                     "ma_n": None}
    assert vf.exit_spec("v3_strength", 3, "1d")["ma_n"] is None
    assert vf.exit_spec("v3_snap", 1.5, "1h") == {"kind": "snap", "mean_n": 20,
                                                  "stop_atr": 3.0, "max_bars": 24}


def test_the_lead_in_is_300_candles_or_the_rules_own_lookback_when_longer():
    # v3_trend n = 100 on 4h: a 600-candle average and 30 candles back = 630; n = 50: 330
    assert vf.lead("v3_trend", 100, "4h") == 630 and vf.lead("v3_trend", 50, "4h") == 330
    assert vf.lead("v3_trend", 20, "4h") == 300 and vf.lead("v3_trend", 100, "1d") == 300
    assert vf.lookback("v3_breakout", 50, "1d") == 105 and vf.lead("v3_snap", 2.0, "1h") == 300


def test_each_family_trades_only_the_sides_its_universe_allows_in_each_month():
    sep, octo = calendar.timegm((2026, 9, 15, 0, 0, 0)) * 1000, OCT1 + 14 * DAY
    plan = {"months": ["2026-09", "2026-10"], "liquid": {"2026-09": ["X_USDT"], "2026-10": []},
            "calm": {"2026-09": [], "2026-10": ["X_USDT"]}}
    # liquid in September (longs), calm in October (both sides)
    assert vf.sides_allowed("v3_trend", "X_USDT", plan, [sep, octo]) == ([True, True],
                                                                         [False, True])
    assert vf.sides_allowed("v3_strength", "X_USDT", plan, [sep, octo]) == ([True, False],
                                                                            [False, False])
    assert vf.sides_allowed("v3_snap", "X_USDT", plan, [sep, octo]) == ([False, True],
                                                                        [False, True])
    assert vf.applies(plan, "v3_snap", "X_USDT") and not vf.applies(plan, "v3_snap", "Y_USDT")
    assert not vf.applies({**plan, "calm": {"2026-09": [], "2026-10": []}}, "v3_snap", "X_USDT")


def test_an_unknown_family_is_refused_by_name():
    with pytest.raises(ValueError, match="v3_nope"):
        vf.exit_spec("v3_nope", 1, "1d")
    with pytest.raises(ValueError, match="v3_nope"):
        vf.rule("v3_nope", 1, "1d", _bars([1.0]))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_v3_families.py -q`
Expected: `ImportError: cannot import name 'v3_families' from 'tradingagents'` (1 error during collection).

- [ ] **Step 3: Implement** — `tradingagents/v3_families.py`:

```python
"""THE V3 IDEA FAMILIES — four rules whose settings were fixed BEFORE any test.

Spec: docs/superpowers/specs/2026-10-22-backtest-v3-design.md (Part 2);
decisions: docs/superpowers/specs/2026-10-23-backtest-v3-part2-decisions.md
("The families"). Each family has its own timeframes, its own exit and its
own universe:

| family | settings, simplest first | timeframes | longs / shorts in |
|---|---|---|---|
| v3_trend | n = 20, 50, 100 days (6n candles on 4h) | 1d, 4h | liquid or calm / calm |
| v3_breakout | N = 20, 50 days | 1d | liquid or calm / calm |
| v3_strength | K = 3, 5 | 1d | liquid / none |
| v3_snap | k = 1.5, 2.0 | 1h, 4h | calm / calm |

A signal holds on EVERY candle its rule holds; the engine places a waiting
order on the first one and, after an exit, on the next candle that still
signals — what a trend follower does. The averages and ranges are
`v3_rules`' own (`sma`, `atr`), the ones the engine's exits read, so a signal
and its exit never read two numbers for one average.

The proof test judges each family on each timeframe with each filter (a
"judged" group, 30 of them) and chooses its setting there; every family x
setting x timeframe x filter measured (`combos`, 70) counts toward the luck
correction.
"""
from __future__ import annotations

from tradingagents import pro_indicators as pi, v3_rules as vr, v3_universe as vu

LEAD_BARS = 300          # sweep_shard.WARMUP_BARS: the lead-in every stored rule reads
BARS_PER_DAY = {"1h": 24, "4h": 6, "1d": 1}
TREND_LAG_DAYS = 5       # "...and that average is above its value 5 days ago"
BREAKOUT_MA_DAYS = 100   # "...only while the 100-day average is rising"
SNAP_N = 20
SNAP_MAX_BARS = 24

FAMILIES = {
    "v3_trend": {"param": "n", "settings": (20, 50, 100), "tfs": ("1d", "4h"),
                 "long": ("liquid", "calm"), "short": ("calm",)},
    "v3_breakout": {"param": "n", "settings": (20, 50), "tfs": ("1d",),
                    "long": ("liquid", "calm"), "short": ("calm",)},
    "v3_strength": {"param": "k", "settings": (3, 5), "tfs": ("1d",),
                    "long": ("liquid",), "short": ()},
    "v3_snap": {"param": "k", "settings": (1.5, 2.0), "tfs": ("1h", "4h"),
                "long": ("calm",), "short": ("calm",)},
}
FILTERS = ("none", "btc_mood", "busy_hours", "funding_side", "funding_minutes")


def setting_key(family: str, value) -> str:
    """"n20", "n100", "k3", "k1.5" — the setting as the output names it."""
    return f"{FAMILIES[family]['param']}{float(value):g}"


def combo_key(family: str, key: str, tf: str, filt: str) -> str:
    return f"{family}|{key}|{tf}|{filt}"


def combos() -> list[tuple[str, str, str, str]]:
    """Every (family, setting, timeframe, filter) measured — the luck
    correction's count, whether or not a combination trades."""
    return [(f, setting_key(f, v), tf, filt) for f, d in FAMILIES.items() for tf in d["tfs"]
            for v in d["settings"] for filt in FILTERS]


def judged() -> list[tuple[str, str, str]]:
    """Every (family, timeframe, filter) the proof test gives a verdict: it
    chooses the setting inside each."""
    return [(f, tf, filt) for f, d in FAMILIES.items() for tf in d["tfs"] for filt in FILTERS]


def verdict_id(family: str, tf: str, filt: str) -> str:
    """A judged group's stable id (standard kit H): hashed from the group with
    res="v3", so it can never equal a v1 or v2 id."""
    from tradingagents import backtest_report as br

    return br.row_code("ALL", tf, family, 0.0, 0.0, 0.0, "flat", plan=f"judged|{filt}", res="v3")


def lookback(family: str, value, tf: str) -> int:
    """How many candles the rule reads before its first signal can hold."""
    d = BARS_PER_DAY[tf]
    if family == "v3_trend":
        return int(value) * d + TREND_LAG_DAYS * d
    if family == "v3_breakout":
        return max(int(value) * d + 1, (BREAKOUT_MA_DAYS + TREND_LAG_DAYS) * d)
    return max(SNAP_N, vr.ATR_N)


def lead(family: str, value, tf: str) -> int:
    """The candles read before a walk's first tradable one: LEAD_BARS, or the
    rule's own lookback where it is longer (v3_trend n=50 on 4h: 330, n=100:
    630), so the first unseen candle can already signal."""
    return max(LEAD_BARS, lookback(family, value, tf))


def exit_spec(family: str, value, tf: str) -> dict:
    """The family's own exit, in `v3_engine.walk`'s shape."""
    if family == "v3_trend":
        return {"kind": "trail", "atr_mult": vr.TRAIL_ATR,
                "ma_n": int(value) * BARS_PER_DAY[tf]}
    if family in ("v3_breakout", "v3_strength"):
        return {"kind": "trail", "atr_mult": vr.TRAIL_ATR, "ma_n": None}
    if family == "v3_snap":
        return {"kind": "snap", "mean_n": SNAP_N, "stop_atr": vr.TRAIL_ATR,
                "max_bars": SNAP_MAX_BARS}
    raise ValueError(f"unknown family {family!r}")


def _trend(c, n: int, lag: int) -> list[int]:
    ma = vr.sma(c, n)
    out = [0] * len(c)
    for i in range(lag, len(c)):
        now, then = ma[i], ma[i - lag]
        if now is None or then is None:
            continue
        if c[i] > now > then:
            out[i] = 1
        elif c[i] < now < then:
            out[i] = -1
    return out


def _breakout(h, lo, c, n: int, ma_n: int, lag: int) -> list[int]:
    top, bottom = pi.donchian(h, lo, n)            # the n candles BEFORE each one
    ma = vr.sma(c, ma_n)
    out = [0] * len(c)
    for i in range(lag, len(c)):
        now, then = ma[i], ma[i - lag]
        if now is None or then is None:
            continue
        if c[i] > top[i] and now > then:            # a NaN channel compares False
            out[i] = 1
        elif c[i] < bottom[i] and now < then:
            out[i] = -1
    return out


def _strength(t, sym: str, plan: dict, k: int) -> list[int]:
    out = [0] * len(t)
    for i, ms in enumerate(t):
        if vu.weekday(ms) == 0:
            r = vu.rank_at(plan, sym, ms)
            if r is not None and r <= k:
                out[i] = 1
    return out


def _snap(h, lo, c, k: float) -> list[int]:
    ma, atr = vr.sma(c, SNAP_N), vr.atr(h, lo, c, vr.ATR_N)
    out = [0] * len(c)
    for i in range(len(c)):
        if ma[i] is None or not atr[i]:
            continue
        if c[i] <= ma[i] - k * atr[i]:
            out[i] = 1
        elif c[i] >= ma[i] + k * atr[i]:
            out[i] = -1
    return out


def rule(family: str, value, tf: str, bars: dict, *, sym: str = "", plan=None) -> list[int]:
    """+1 / -1 / 0 per candle where the family's rule holds — before the
    universe and the filters, which `v3_measure` lays on top. Reads only
    candles up to each one (a closed candle), never after it."""
    h, lo, c, t = bars["h"], bars["l"], bars["c"], bars["t"]
    d = BARS_PER_DAY[tf]
    if family == "v3_trend":
        return _trend(c, int(value) * d, TREND_LAG_DAYS * d)
    if family == "v3_breakout":
        return _breakout(h, lo, c, int(value) * d, BREAKOUT_MA_DAYS * d, TREND_LAG_DAYS * d)
    if family == "v3_strength":
        return _strength(t, sym, plan, int(value))
    if family == "v3_snap":
        return _snap(h, lo, c, float(value))
    raise ValueError(f"unknown family {family!r}")


def forced(family: str, value, tf: str, bars: dict, *, sym: str = "", plan=None):
    """v3_strength's forced exit, as `walk(forced=)` flags: out at the close
    of a Monday candle where the coin is no longer in the top 2K of that
    Monday's ranking (or not ranked at all). None for every other family."""
    if family != "v3_strength":
        return None
    k = int(value)
    out = [False] * len(bars["t"])
    for i, ms in enumerate(bars["t"]):
        if vu.weekday(ms) == 0:
            r = vu.rank_at(plan, sym, ms)
            out[i] = r is None or r > 2 * k
    return out


def entry_days(family: str, bars: dict) -> list[bool]:
    """The candles the family can ever enter on: Monday candles for
    v3_strength (it ranks once a week), every candle for the others — the
    candles its random entries are drawn from."""
    if family == "v3_strength":
        return [vu.weekday(ms) == 0 for ms in bars["t"]]
    return [True] * len(bars["t"])


def sides_allowed(family: str, sym: str, plan: dict, at_ms) -> tuple[list[bool], list[bool]]:
    """Per instant (each candle's ORDER minute): may this coin go long, may it
    go short, by its universe membership in that month."""
    f = FAMILIES[family]
    return (vu.member_mask(plan, f["long"], sym, at_ms),
            vu.member_mask(plan, f["short"], sym, at_ms))


def applies(plan: dict, family: str, sym: str) -> bool:
    """Is the coin in any of the family's groups in any month of the plan."""
    f = FAMILIES[family]
    groups = set(f["long"]) | set(f["short"])
    return any(sym in plan[g].get(m, ()) for g in groups for m in plan["months"])
```

- [ ] **Step 4: Run the tests to verify they pass, then lint**

Run: `.venv/Scripts/python -m pytest tests/test_v3_families.py tests/test_v3_universe.py -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_families.py tests/test_v3_families.py`
Expected: `21 passed`, then `All checks passed!`

- [ ] **Step 5: The harddev hunt:**
  - **One average for a signal and its exit:** v3_trend's signal and the engine's MA exit both use `v3_rules.sma`; v3_snap's band and the engine's stop both use `v3_rules.atr`.
  - **No future:** every rule reads candles up to each one; the breakout's channel is the N candles BEFORE it (`donchian`).
  - **Sides:** each rule's short is the mirror of its long; `sides_allowed` decides whether a short may trade at all.
  - **A flat market:** v3_snap with an ATR of 0 signals nothing (a close equal to its average is no snap).

- [ ] **Step 6: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_families.py tests/test_v3_families.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
feat(v3): the four idea families with their settings fixed before any test - trend, breakout, strength (with its forced rank exit), snap - their exits, lead-ins, universes and the 70 combinations the luck correction divides by

Backtest v3 Part 2a, Task 4. Lead-in is 300 candles or the rule's own lookback (trend n=100 on 4h: 630).
- harddev: one average for a signal and its exit (v3_rules.sma and atr), no future (the breakout channel is the N candles before), sides (each short mirrors its long), a flat market signals no snap

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 5: The four filters

**Files:**
- Create: `tradingagents/v3_filters.py`
- Test: `tests/test_v3_filters.py`

**Interfaces:**
- Consumes: Task 3's `v3_universe.BTC`, `weekday`, `mood_at`; `daytime_rule.in_market_hours`.
- Produces: `NAMES`; `masks(name, *, sym, kind, order_ms, funding=None, cycle_h=8, plan=None) -> (longs allowed [bool], shorts allowed [bool], count name or "" per candle [str])` — one entry per order minute; the count names are `mood_unknown`, `funding_unknown`, `settle_by_cycle`; an unknown filter name raises `ValueError`. Also `btc_mood`, `busy_hours`, `funding_side`, `funding_minutes` (the four rules, `masks`' parts).

- [ ] **Step 1: Write the failing test** — `tests/test_v3_filters.py`:

```python
"""The four Backtest v3 filters (decisions doc docs/superpowers/specs/2026-10-23-
backtest-v3-part2-decisions.md, "The filters"), each judged at a candle's
ORDER minute and reading only what was known by then. Instants are real UTC
times: Oct 23, 2026 is a Friday, Oct 26 a Monday, and New York is on summer
time (UTC-4) until Nov 01, 2026."""
import calendar

import pytest

from tradingagents import v3_filters as vfl

H = 3_600_000
DAY = 24 * H
M = 60_000
F0 = calendar.timegm((2026, 6, 1, 0, 0, 0)) * 1000          # a UTC midnight


def _utc(*ymdhm):
    return calendar.timegm((*ymdhm, 0)) * 1000


def test_busy_hours_keeps_weekdays_for_crypto_and_new_york_hours_for_stock_tokens():
    fri, sat = _utc(2026, 10, 23, 23, 0), _utc(2026, 10, 24, 0, 0)
    sun, mon = _utc(2026, 10, 25, 23, 59), _utc(2026, 10, 26, 0, 0)
    for kind in ("crypto", "metals", "indices"):
        long_ok, short_ok, flag = vfl.masks("busy_hours", sym="X_USDT", kind=kind,
                                            order_ms=[fri, sat, sun, mon])
        assert long_ok == short_ok == [True, False, False, True], kind
        assert flag == [""] * 4
    # Monday Oct 26, 2026 in New York: 9:30am is 13:30 UTC, the 4:00pm close 20:00 UTC (out)
    at = [_utc(2026, 10, 26, 13, 29), _utc(2026, 10, 26, 13, 30), _utc(2026, 10, 26, 19, 59),
          _utc(2026, 10, 26, 20, 0), _utc(2026, 10, 24, 15, 0)]
    long_ok, _short, _flag = vfl.masks("busy_hours", sym="AAPL_USDT", kind="stocks", order_ms=at)
    assert long_ok == [False, True, True, False, False]


def _mood_plan():
    # BTC's daily closes known at F0 + 1 day (up), + 2 days (down), + 3 days (up)
    return {"mood": {"t": [F0 + DAY, F0 + 2 * DAY, F0 + 3 * DAY], "up": [1, 0, 1]}}


def test_btc_mood_lets_an_alts_longs_through_only_on_days_btc_closed_above_its_average():
    at = [F0 + DAY, F0 + 2 * DAY - 1, F0 + 2 * DAY, F0 + 3 * DAY + 5 * H, F0 + DAY - 1,
          F0 + 4 * DAY + 1]
    long_ok, short_ok, flag = vfl.masks("btc_mood", sym="ETH_USDT", kind="crypto", order_ms=at,
                                        plan=_mood_plan())
    # up, still the up day 1 ms before the down close, down, up again; before the first close
    # and more than a day after the last the mood is not known: the signal passes, counted
    assert long_ok == [True, True, False, True, True, True]
    assert flag == ["", "", "", "", "mood_unknown", "mood_unknown"]
    assert short_ok == [True] * 6, "shorts are never filtered by BTC's mood"
    for sym, kind in (("BTC_USDT", "crypto"), ("XAU_USDT", "metals")):
        long_ok, _s, _f = vfl.masks("btc_mood", sym=sym, kind=kind, order_ms=at,
                                    plan=_mood_plan())
        assert long_ok == [True] * 6, f"{sym} is not an alt-coin"


def _funding(n=120, spikes=None, offset_ms=0):
    """Settlements every 8 hours from F0 (+ offset), 0.01% each, `spikes` {index: rate}."""
    spikes = spikes or {}
    return [{"settle_ms": F0 + k * 8 * H + offset_ms, "rate": spikes.get(k, 0.0001),
             "cycle_h": 8} for k in range(n)]


def test_funding_side_skips_a_long_at_the_top_tenth_and_a_short_at_the_bottom_tenth():
    fund = _funding(spikes={100: 0.0010, 110: -0.0010})
    # an hour after settlement 100 (F0 + 801h) the 30 days before hold settlements 11..100:
    # 90 of them. Only 1 is >= 0.10% (itself): 1 <= 10% of 90 = 9, the top tenth - no long. 90
    # are <= it, so a short is fine
    after_spike = F0 + 801 * H
    # an hour after settlement 101 (back at 0.01%): all 90 are >= it and 89 <= it - neither tail:
    # the usual rate is never "the top", however many settlements tie with it
    after_calm = F0 + 809 * H
    # an hour after settlement 110 (-0.10%): only itself is <= it - no short
    after_dip = F0 + 881 * H
    long_ok, short_ok, flag = vfl.masks("funding_side", sym="X_USDT", kind="crypto",
                                        order_ms=[after_spike, after_calm, after_dip],
                                        funding=fund)
    assert (long_ok, short_ok) == ([False, True, True], [True, True, False])
    assert flag == ["", "", ""]


def test_funding_side_passes_and_counts_a_signal_whose_30_days_the_history_does_not_cover():
    fund = _funding()
    # the history answers from one cycle before its first settlement (F0 - 8h), so 30 days of it
    # end no earlier than F0 - 8h + 720h = F0 + 712h; and it answers to one cycle after its last
    # (F0 + 952h + 8h)
    at = [F0 + 711 * H, F0 + 712 * H, F0 + 960 * H, F0 + 960 * H + 1]
    long_ok, short_ok, flag = vfl.masks("funding_side", sym="X_USDT", kind="crypto",
                                        order_ms=at, funding=fund)
    assert flag == ["funding_unknown", "", "", "funding_unknown"]
    assert long_ok == short_ok == [True] * 4
    assert vfl.masks("funding_side", sym="X_USDT", kind="crypto", order_ms=[F0],
                     funding=[])[2] == ["funding_unknown"], "no history judges nothing"


def test_funding_minutes_blocks_orders_within_5_minutes_of_a_recorded_settlement():
    # Gate settles a few seconds after the hour (BTC_USDT, Oct 2026: 0-5 s); here 2 s
    fund = _funding(offset_ms=2000)
    s8 = F0 + 8 * H + 2000                                        # the settlement after F0 + 8h
    at = [F0 + 8 * H, s8 + 5 * M, s8 + 5 * M + 1, s8 - 5 * M, s8 - 5 * M - 1, F0 + 4 * H]
    ok, short_ok, flag = vfl.masks("funding_minutes", sym="X_USDT", kind="crypto", order_ms=at,
                                   funding=fund, cycle_h=8)
    assert ok == short_ok == [False, False, True, False, True, True]
    assert flag == [""] * 6


def test_funding_minutes_uses_the_contracts_cycle_where_no_settlement_was_recorded():
    # before the history: the 8-hour cycle from 00:00 UTC - F0 - 16h is a settlement, F0 - 12h
    # is not; a coin with no history at all on a 4-hour cycle: 04:00 UTC is, 3:55 and 4:05 are
    # inside 5 minutes of it, 3:54:59.999 is not
    fund = _funding(offset_ms=2000)
    ok, _s, flag = vfl.masks("funding_minutes", sym="X_USDT", kind="crypto",
                             order_ms=[F0 - 16 * H, F0 - 12 * H], funding=fund, cycle_h=8)
    assert ok == [False, True] and flag == ["settle_by_cycle"] * 2
    four = F0 + 4 * H
    ok, _s, flag = vfl.masks("funding_minutes", sym="X_USDT", kind="crypto",
                             order_ms=[four, four - 5 * M, four + 5 * M, four - 5 * M - 1,
                                       F0 + 2 * H], funding=[], cycle_h=4)
    assert ok == [False, False, False, True, True]
    # on daily candles every order goes in at 00:00 UTC, a settlement on every cycle there is
    ok, _s, _f = vfl.masks("funding_minutes", sym="X_USDT", kind="crypto",
                           order_ms=[F0 + k * DAY for k in range(5)], funding=[], cycle_h=8)
    assert ok == [False] * 5


def test_no_filter_lets_everything_through_and_an_unknown_one_is_refused():
    assert vfl.masks("none", sym="X_USDT", kind="crypto", order_ms=[F0, F0 + H]) == \
        ([True, True], [True, True], ["", ""])
    with pytest.raises(ValueError, match="crash_guard"):
        vfl.masks("crash_guard", sym="X_USDT", kind="crypto", order_ms=[F0])
    assert vfl.NAMES[1:] == ("btc_mood", "busy_hours", "funding_side", "funding_minutes")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_v3_filters.py -q`
Expected: `ImportError: cannot import name 'v3_filters' from 'tradingagents'` (1 error during collection).

- [ ] **Step 3: Implement** — `tradingagents/v3_filters.py`:

```python
"""THE V3 FILTERS — four rules laid ON TOP of every family, as a mask on its
signals (decisions doc docs/superpowers/specs/2026-10-23-backtest-v3-part2-
decisions.md, "The filters"; spec #5, #6, #7 and #9).

Each is judged at a candle's ORDER MINUTE — the close of the signal candle,
when its waiting order would go in — and reads only what was known by then:

* ``btc_mood``: a crypto alt-coin's longs only while BTC's last CLOSED daily
  candle is above its 50-day average (BTC itself, and contracts that are not
  crypto, are not filtered).
* ``busy_hours``: a stock token's orders only 9:30am-4:00pm New York on a
  weekday (`daytime_rule.in_market_hours`); every other contract's, never on
  a Saturday or Sunday (UTC).
* ``funding_side``: no long when the last settled funding rate is among the
  top 10% of the coin's own settlements of the 30 days before it, no short
  among the bottom 10% (ties count against the rate). Where the history does
  not cover those 30 days the filter cannot judge: the signal passes and is
  counted `funding_unknown`.
* ``funding_minutes``: no order within 5 minutes either side of a funding
  settlement — the recorded ones where the history reaches, else the
  contract's settlement cycle from 00:00 UTC, counted `settle_by_cycle`.

`masks` answers every candle at once, so random entries can be drawn from
the candles a filter lets through (`v3_random`).
"""
from __future__ import annotations

import bisect

from tradingagents import v3_universe as vu

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
SIDE_SHARE = 0.10
SIDE_DAYS = 30
SETTLE_GAP_MS = 5 * 60_000
NAMES = ("none", "btc_mood", "busy_hours", "funding_side", "funding_minutes")


def _arrays(funding) -> tuple[list[int], list[float], list[float]]:
    f = funding or []
    return ([int(x["settle_ms"]) for x in f], [float(x["rate"]) for x in f],
            [float(x.get("cycle_h") or 8) for x in f])


def btc_mood(sym: str, kind: str, order_ms, plan: dict):
    n = len(order_ms)
    if sym == vu.BTC or kind != "crypto":
        return [True] * n, [True] * n, [""] * n
    up = vu.mood_at(plan, order_ms)
    return ([u is not False for u in up], [True] * n,
            ["mood_unknown" if u is None else "" for u in up])


def busy_hours(kind: str, order_ms):
    from tradingagents import daytime_rule

    if kind == "stocks":
        ok = [daytime_rule.in_market_hours(ms / 1000) for ms in order_ms]
    else:
        ok = [vu.weekday(ms) < 5 for ms in order_ms]
    return ok, list(ok), [""] * len(order_ms)


def funding_side(order_ms, funding):
    f_ms, f_rate, f_cyc = _arrays(funding)
    long_ok, short_ok, flag = [], [], []
    for ms in order_ms:
        ms = int(ms)
        covered = (bool(f_ms) and f_ms[0] - f_cyc[0] * HOUR_MS <= ms - SIDE_DAYS * DAY_MS
                   and ms <= f_ms[-1] + f_cyc[-1] * HOUR_MS)
        hi = bisect.bisect_right(f_ms, ms) if covered else 0
        window = f_rate[bisect.bisect_right(f_ms, ms - SIDE_DAYS * DAY_MS):hi] if hi else []
        if not window:
            long_ok.append(True)
            short_ok.append(True)
            flag.append("funding_unknown")
            continue
        last = f_rate[hi - 1]
        cut = SIDE_SHARE * len(window)
        long_ok.append(sum(1 for r in window if r >= last) > cut)
        short_ok.append(sum(1 for r in window if r <= last) > cut)
        flag.append("")
    return long_ok, short_ok, flag


def funding_minutes(order_ms, funding, cycle_h: float):
    f_ms, _rate, _cyc = _arrays(funding)
    cycle = float(cycle_h or 8) * HOUR_MS
    ok, flag = [], []
    for ms in order_ms:
        ms = int(ms)
        if f_ms and f_ms[0] - SETTLE_GAP_MS <= ms <= f_ms[-1] + SETTLE_GAP_MS:
            k = bisect.bisect_left(f_ms, ms - SETTLE_GAP_MS)
            ok.append(not (k < len(f_ms) and f_ms[k] <= ms + SETTLE_GAP_MS))
            flag.append("")
        else:
            phase = ms % cycle
            ok.append(SETTLE_GAP_MS < phase < cycle - SETTLE_GAP_MS)
            flag.append("settle_by_cycle")
    return ok, list(ok), flag


def masks(name: str, *, sym: str, kind: str, order_ms, funding=None, cycle_h: float = 8,
          plan: dict | None = None) -> tuple[list[bool], list[bool], list[str]]:
    """(longs allowed, shorts allowed, a count name or "" per candle) for one
    filter over every candle's order minute."""
    n = len(order_ms)
    if name == "none":
        return [True] * n, [True] * n, [""] * n
    if name == "btc_mood":
        return btc_mood(sym, kind, order_ms, plan)
    if name == "busy_hours":
        return busy_hours(kind, order_ms)
    if name == "funding_side":
        return funding_side(order_ms, funding)
    if name == "funding_minutes":
        return funding_minutes(order_ms, funding, cycle_h)
    raise ValueError(f"unknown filter {name!r}")
```

- [ ] **Step 4: Run the test to verify it passes, then lint**

Run: `.venv/Scripts/python -m pytest tests/test_v3_filters.py -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_filters.py tests/test_v3_filters.py`
Expected: `7 passed`, then `All checks passed!`

- [ ] **Step 5: The harddev hunt:**
  - **Only the past:** each filter reads what was known at the order minute — BTC's last CLOSED day, the settlements at or before it.
  - **Unknown is not a block:** an order the funding history cannot judge passes and is counted; a mood that is not known passes and is counted.
  - **Ties:** the usual funding rate is never "the top 10%" (ties count against the rate).
  - **Gate's settlement offsets:** recorded settlements land 0-5 s after the UTC hour; the ± 5-minute window covers them.

- [ ] **Step 6: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_filters.py tests/test_v3_filters.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
feat(v3): the four Backtest v3 filters as signal masks - btc_mood, busy_hours, funding_side, funding_minutes - each judged at the order minute from what was known then, unknowns passed and counted

Backtest v3 Part 2a, Task 5. crash_guard (#8) is not built: no reader of open-interest history exists.
- harddev: only the past (BTC's last closed day, settlements at or before the order), unknown is not a block (passed and counted), ties (the usual rate is never the top 10%), Gate's 0-5 s settlement offsets inside the 5-minute window

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 6: Random entries, the luck bar

**Files:**
- Create: `tradingagents/v3_random.py`
- Test: `tests/test_v3_random.py`

**Interfaces:**
- Consumes: Task 3's `v3_universe.month_key`.
- Produces: `RUNS = 200`; `seed_of(*parts) -> int` (blake2b, 64 bits); `entries_by_month(walked, t, bar_ms) -> {(month, side): orders}` (the real walk's trades and missed orders, by the order minute's month); `candidates(t, bar_ms, start, long_ok, short_ok) -> {(month, side): [candle index]}`; `draw(n, wanted, cands, seed) -> (dirs [int], entries not placed)` — longs first, then shorts, month by month, using only `random.Random(seed).random()`.

- [ ] **Step 1: Write the failing test** — `tests/test_v3_random.py`:

```python
"""Random entries, the luck bar (decisions doc docs/superpowers/specs/2026-10-23-
backtest-v3-part2-decisions.md, "Random entries"): as many entries per month
and side as the real run placed, on candles the combination could have
entered on, seeded so every machine draws the same runs."""
import calendar
import random

from tradingagents import v3_random as vrn

H = 3_600_000
OCT31_22 = calendar.timegm((2026, 10, 31, 22, 0, 0)) * 1000   # the last hours of October


def test_a_seed_is_the_same_on_every_machine():
    # blake2b of "BTC_USDT|1d|v3_trend|none|0", its first 8 bytes read big-endian
    assert vrn.seed_of("BTC_USDT", "1d", "v3_trend", "none", 0) == 9232730103163168985
    assert vrn.seed_of("BTC_USDT", "1d", "v3_trend", "none", 1) != \
        vrn.seed_of("BTC_USDT", "1d", "v3_trend", "none", 0)


def test_a_draw_is_pinned_to_its_seed_and_takes_longs_then_shorts():
    s = vrn.seed_of("X_USDT", "1h", "v3_snap", "none", 7)
    # Python keeps random()'s sequence for an int seed from version to version: 0.9503..., 0.4640...,
    # 0.1798... The longs' partial shuffle of candles 0-9 swaps 0 with 0 + int(0.9503 x 10) = 9,
    # then 1 with 1 + int(0.4640 x 9) = 5, then 2 with 2 + int(0.1798 x 8) = 3: longs at 9, 5, 3.
    # The two shorts are drawn from the seven candles left
    assert round(random.Random(s).random(), 4) == 0.9503
    cands = {("2026-10", 1): list(range(10)), ("2026-10", -1): list(range(10))}
    wanted = {("2026-10", 1): 3, ("2026-10", -1): 2}
    got = vrn.draw(10, wanted, cands, s)
    assert got == ([0, 0, 0, 1, -1, 1, 0, 0, -1, 1], 0)
    assert vrn.draw(10, wanted, cands, s) == got, "the same seed, the same run"
    assert vrn.draw(10, wanted, cands, s + 1)[0] != got[0]


def test_a_draw_places_only_where_allowed_and_counts_what_it_could_not_place():
    # October: 2 longs wanted, 3 candles allowed; November: 2 shorts wanted, 1 allowed
    cands = {("2026-10", 1): [1, 4, 6], ("2026-11", -1): [8]}
    wanted = {("2026-10", 1): 2, ("2026-11", -1): 2}
    for run in range(20):
        dirs, short_of = vrn.draw(10, wanted, cands, vrn.seed_of("X", run))
        assert sorted(i for i, d in enumerate(dirs) if d == 1) in ([1, 4], [1, 6], [4, 6])
        assert [i for i, d in enumerate(dirs) if d == -1] == [8] and short_of == 1


def test_the_real_runs_entries_are_counted_by_the_month_their_order_went_in():
    # hourly candles from Oct 31, 2026 10:00pm UTC: candle 1's (11:00pm) order goes in at
    # midnight, November 1 - a November entry, though its signal candle is October's
    t = [OCT31_22 + k * H for k in range(6)]
    walked = {"trades": [{"signal_bar": 0, "side": 1}, {"signal_bar": 1, "side": 1}],
              "missed": [{"signal_bar": 3, "side": -1}, {"signal_bar": 4, "side": 1}]}
    assert vrn.entries_by_month(walked, t, H) == {("2026-10", 1): 1, ("2026-11", 1): 2,
                                                  ("2026-11", -1): 1}


def test_candidates_are_the_walks_tradable_candles_by_order_month_and_side():
    t = [OCT31_22 + k * H for k in range(6)]
    long_ok = [True, True, False, True, True, True]
    short_ok = [False, True, True, False, False, True]
    # from candle 1 (the walk's start) to candle 4 (candle 5 has no next candle to fill in)
    assert vrn.candidates(t, H, 1, long_ok, short_ok) == {
        ("2026-11", 1): [1, 3, 4], ("2026-11", -1): [1, 2]}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_v3_random.py -q`
Expected: `ImportError: cannot import name 'v3_random' from 'tradingagents'` (1 error during collection).

- [ ] **Step 3: Implement** — `tradingagents/v3_random.py`:

```python
"""RANDOM ENTRIES — the luck bar of the Backtest v3 proof test (decisions doc
docs/superpowers/specs/2026-10-23-backtest-v3-part2-decisions.md, "Random
entries"; spec Part 3).

For each combination and coin, `RUNS` seeded runs on the UNSEEN window. Each
run places, in every calendar month and on each side, as many entries as the
real run placed there — the orders it put in, filled or missed, by the month
of the minute each went in — on candles of that month drawn at random from
the ones the combination could have entered on (its universe months and
sides, its filter, its family's entry days), and is walked by the same
`v3_engine.walk` with the same exit, sizing and costs. An entry that lands
inside an open random trade is not taken (one position at a time), so a run
can trade fewer times than the real one; the proof compares profit PER
TRADE.

Reproducible on any machine: a run's seed is a hash of coin, timeframe,
family, filter and run number, and the draw uses only `random.Random.random`,
whose sequence Python keeps the same from version to version.
"""
from __future__ import annotations

import hashlib
import random

from tradingagents import v3_universe as vu

RUNS = 200


def seed_of(*parts) -> int:
    """A 64-bit seed from its parts, the same on every machine."""
    text = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(text, digest_size=8).digest(), "big")


def entries_by_month(walked: dict, t, bar_ms: int) -> dict[tuple[str, int], int]:
    """{(month, side): orders} of a real walk — its trades and its missed
    orders (rejected or never filled), by the month of the minute each order
    went in (the open of the candle after its signal)."""
    out: dict[tuple[str, int], int] = {}
    for x in list(walked["trades"]) + list(walked["missed"]):
        key = (vu.month_key(int(t[x["signal_bar"]]) + int(bar_ms)), int(x["side"]))
        out[key] = out.get(key, 0) + 1
    return out


def candidates(t, bar_ms: int, start: int, long_ok, short_ok) -> dict[tuple[str, int], list[int]]:
    """{(month, side): candle indices} a random entry may be drawn from: the
    walk's tradable signal candles (from `start` to the one before last, whose
    order goes in inside the window) where that side is allowed."""
    out: dict[tuple[str, int], list[int]] = {}
    for i in range(int(start), len(t) - 1):
        month = vu.month_key(int(t[i]) + int(bar_ms))
        for side, ok in ((1, long_ok), (-1, short_ok)):
            if ok[i]:
                out.setdefault((month, side), []).append(i)
    return out


def draw(n: int, wanted: dict, cands: dict, seed: int) -> tuple[list[int], int]:
    """One random run's signals: (dirs of length `n`, entries it could not
    place). Longs first, then shorts, month by month; a candle holds one side."""
    rng = random.Random(seed)
    dirs = [0] * n
    short_of = 0
    for month, side in sorted(wanted, key=lambda k: (k[0], -k[1])):
        pool = [i for i in cands.get((month, side), ()) if dirs[i] == 0]
        want = int(wanted[(month, side)])
        take = min(want, len(pool))
        short_of += want - take
        for k in range(take):                     # a partial Fisher-Yates shuffle
            j = k + int(rng.random() * (len(pool) - k))
            pool[k], pool[j] = pool[j], pool[k]
            dirs[pool[k]] = side
    return dirs, short_of
```

- [ ] **Step 4: Run the test to verify it passes, then lint**

Run: `.venv/Scripts/python -m pytest tests/test_v3_random.py -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_random.py tests/test_v3_random.py`
Expected: `5 passed`, then `All checks passed!`

- [ ] **Step 5: The harddev hunt:**
  - **The same on every machine:** the seed is a hash of its parts; the draw uses only `random()`, whose sequence Python keeps for an int seed; the pinned draw in the test fails if the algorithm ever changes.
  - **One side a candle:** longs are drawn first and shorts from what is left.
  - **Honest shortfall:** a month with fewer allowed candles than wanted entries places what it can and counts the rest.

- [ ] **Step 6: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_random.py tests/test_v3_random.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
feat(v3): random entries for the luck bar - as many orders per month and side as the real run placed, on candles it could have entered on, seeded so every machine draws the same runs

Backtest v3 Part 2a, Task 6.
- harddev: the same on every machine (a hashed seed, only random(); the pinned draw fails if the algorithm changes), one side a candle (longs first), an honest shortfall (counted)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 7: The proof test

**Files:**
- Create: `tradingagents/v3_proof.py`
- Test: `tests/test_v3_proof.py`

**Interfaces:**
- Consumes: Task 4's `FAMILIES`, `combos`, `judged`, `setting_key`, `combo_key`, `verdict_id`; Task 6's `seed_of`; Task 3's `SURVIVORSHIP`; `v3_page.worst_run`; the coin records Task 8 writes (their `combos`, `windows`, `unseen_months`, `coin`).
- Produces:
  - `ALPHA = 0.05`, `MIN_CHOOSE = 30`, `MIN_UNSEEN = 300`, `BOOT_DRAWS = 2000`, `CHECKS = ("profit", "random", "bootstrap", "trades")`, `TRIED` (70), `Z` (3.384), `z_for(tried, alpha=ALPHA) -> float`;
  - `summary(rows) -> {"trades", "wins", "losses", "win_rate", "break_even", "profit", "per_trade", "worst_run_usd", "worst_run_trades", "open_at_end"}`;
  - `choose(older, order) -> (setting key | None, {key: {"trades", "profit", "per_trade", "eligible"}})`, `pool_random(per_coin) -> [(trades, profit)]`, `random_bar(runs, z=Z) -> {"runs", "traded", "median", "mean", "sd", "best", "normal", "bar"} | None`, `boot_se(rows, seed, draws=BOOT_DRAWS) -> (se | None, days)`, `tally(walks) -> {"counts", "twins", "twins_pnl", "over_book", "lev", "notional"}`;
  - `verdict(family, tf, filt, coins, *, z=Z, tried=TRIED) -> dict` with `id`, `family`, `tf`, `filter`, `tried`, `alpha`, `z`, `coins`, `window`, `months`, `older`, `setting`, `notes`, `passed`, `failed` (`""` or `"choose" | "profit" | "random" | "bootstrap" | "trades"`). With a chosen setting it also holds `checks` {step: bool}, `unseen` (the summary), `random` (the bar, or None), `bootstrap` {"draws", "days", "se", "low"} and `tally`'s keys; without one, `why`;
  - `verdicts(coins) -> [verdict]` in `judged()` order.

- [ ] **Step 1: Write the failing test** — `tests/test_v3_proof.py`:

```python
"""The Backtest v3 proof test (decisions doc docs/superpowers/specs/2026-10-23-
backtest-v3-part2-decisions.md, "The proof test"): choose on the older days,
judge on the unseen days against the random runs' bar and a day-clustered
bootstrap, at least 300 unseen trades — and every verdict kept with the step
it failed. Rows are the compact trade rows `v3_measure` writes:
[signal_ms, entry_ms, exit_ms, side, pnl, why]."""
import calendar
import math

import pytest

from tradingagents import v3_families as vf, v3_proof as vp

DAY = 86_400_000
D0 = calendar.timegm((2026, 7, 25, 0, 0, 0)) * 1000        # the unseen days start here
KEY = vf.combo_key("v3_snap", "k2", "1h", "none")
KEY15 = vf.combo_key("v3_snap", "k1.5", "1h", "none")


def _rows(pnls, per_day=4, why="TP"):
    """One row per pnl, `per_day` of them closing on each UTC day from D0."""
    return [[D0 + (k // per_day) * DAY, D0 + (k // per_day) * DAY + 60_000,
             D0 + (k // per_day) * DAY + 3_600_000, 1, p, why] for k, p in enumerate(pnls)]


def _walk(rows, **extra):
    return {"rows": rows, "counts": {}, "filter": {}, "twins": [0, 0.0], "lev": [20, 20],
            "notional": [50.0, 50.0], "over_book": 0, **extra}


def _coin(name, older15, older2, unseen2, random2, unseen15=()):
    return {"coin": name, "windows": {"1h": {"split": "Jul 25, 2026", "end": "Oct 23, 2026"}},
            "unseen_months": ["2026-07", "2026-08", "2026-09", "2026-10"],
            "combos": {KEY15: {"older": _walk(older15), "unseen": _walk(list(unseen15)),
                               "random": [[0, 0.0]] * 200},
                       KEY: {"older": _walk(older2), "unseen": _walk(unseen2),
                             "random": random2}}}


QUIET = [[100, 0.1 * ((k % 5) - 2)] for k in range(200)]    # a run's profit a trade: +-0.002
LOUD = [[100, 10.0 * ((k % 5) - 2)] for k in range(200)]    # +-0.2


def _two_coins(unseen, random_runs=QUIET):
    """k1.5 makes +0.05 a trade on the older days, k2 +0.10 (40 trades each per coin): k2 is
    chosen. The unseen trades are split between the two coins."""
    half = len(unseen) // 2
    return [_coin(c, _rows([0.05] * 40), _rows([0.10] * 40), part, random_runs)
            for c, part in (("AAA_USDT", unseen[:half]), ("BBB_USDT", unseen[half:]))]


def test_alpha_divides_by_every_combination_measured():
    # 0.05 / 70 = 0.000714; z = the normal curve's 1 - 0.000357 point
    assert vp.TRIED == len(vf.combos()) == 70
    assert round(vp.Z, 4) == 3.384 and round(vp.z_for(1), 5) == 1.95996


def test_the_setting_is_chosen_on_the_older_days_with_30_trades_ties_to_the_simplest():
    older = {"n20": _rows([0.10] * 40), "n50": _rows([0.20] * 35), "n100": _rows([5.0] * 29)}
    chosen, table = vp.choose(older, ["n20", "n50", "n100"])
    # n100 makes far more a trade, but 29 trades are under the 30 a setting needs
    assert chosen == "n50" and table["n100"]["eligible"] is False
    assert table["n50"]["per_trade"] == pytest.approx(0.20) and table["n50"]["trades"] == 35
    tie = {"n20": _rows([0.2] * 30), "n50": _rows([0.2] * 30)}
    assert vp.choose(tie, ["n20", "n50", "n100"])[0] == "n20", "a tie goes to the simplest"
    assert vp.choose({"n20": _rows([1.0] * 29)}, ["n20"])[0] is None


def test_the_random_bar_is_the_normal_curves_point_with_the_best_run_as_its_floor():
    # three runs that traded make +0.1, -0.1 and +0.1 a trade (the run with no trade is left
    # out): mean 0.0333, sample sd sqrt((0.0667^2 + 0.1333^2 + 0.0667^2) / 2) = 0.11547, so
    # the point is 0.0333 + 3.384 x 0.11547 = 0.4241, over the best run's 0.1
    bar = vp.random_bar([(10, 1.0), (10, -1.0), (5, 0.5), (0, 0.0)])
    assert (bar["runs"], bar["traded"]) == (4, 3)
    assert bar["sd"] == pytest.approx(0.11547, abs=1e-5)
    assert bar["bar"] == pytest.approx(0.0333333 + vp.Z * 0.11547, abs=1e-4)
    # 199 runs at 0 and one at +0.5 a trade: mean 0.0025, sd sqrt(0.24875 / 199) = 0.035355,
    # the point 0.0025 + 3.384 x 0.035355 = 0.1221 - under the best run, which is the bar
    bar = vp.random_bar([(10, 0.0)] * 199 + [(10, 5.0)])
    assert bar["normal"] == pytest.approx(0.12214, abs=1e-4) and bar["bar"] == 0.5
    assert vp.random_bar([(10, 1.0), (0, 0.0)]) is None, "one run that traded is no curve"


def test_random_runs_pool_run_by_run_over_the_coins():
    assert vp.pool_random([[[10, 1.0], [5, -1.0]], [[2, 0.5], [0, 0.0]]]) == [(12, 1.5),
                                                                            (5, -1.0)]
    with pytest.raises(ValueError, match="random runs"):
        vp.pool_random([[[1, 1.0]], [[1, 1.0], [1, 1.0]]])


def test_the_bootstrap_draws_whole_days():
    # two days, one trade each, +1 and -1: a draw of 2 days is (+1, +1) a quarter of the time,
    # (-1, -1) a quarter, mixed half - profit a trade +1, -1 or 0: sd sqrt(0.5) = 0.7071
    two = _rows([1.0, -1.0], per_day=1)
    se, days = vp.boot_se(two, seed=1)
    assert days == 2 and se == pytest.approx(math.sqrt(0.5), abs=0.03)
    assert vp.boot_se(two, seed=1) == (se, 2), "seeded: the same every time"
    # two wins on day 1 and a loss on day 2 are 2 clusters, not 3 trades: a draw is +1 (both
    # day 1), -1 (both day 2) or (2 - 1) / 3 = +0.333 (one each), so the sd is
    # sqrt(0.25 + 0.25 + 0.5 x 0.1111 - 0.1667^2) = 0.7265
    se, days = vp.boot_se(_rows([1.0, 1.0, -1.0], per_day=2), seed=1)
    assert days == 2 and se == pytest.approx(0.7265, abs=0.03)
    assert vp.boot_se(_rows([1.0, 2.0], per_day=2), seed=1) == (None, 1)


def test_the_summary_is_the_standard_kits_figures_in_closing_order():
    rows = _rows([1.0, -0.5, -0.7, 2.0, -0.4], per_day=1)
    rows[4][5] = "END"
    s = vp.summary(list(reversed(rows)))                  # handed over in any order
    # wins 1.0 and 2.0 (avg 1.5), losses 0.5, 0.7, 0.4 (avg 0.5333): break-even 0.5333 / 2.0333
    assert (s["trades"], s["wins"], s["losses"]) == (5, 2, 3)
    assert s["profit"] == pytest.approx(1.4) and s["per_trade"] == pytest.approx(0.28)
    assert s["break_even"] == pytest.approx(0.53333 / 2.03333, abs=1e-4)
    assert (s["worst_run_usd"], s["worst_run_trades"]) == (pytest.approx(-1.2), 2)
    assert s["open_at_end"] == 1


STEADY = [1.2, -0.8] * 160                  # 320 trades, +0.20 each on average, every day alike


def test_a_family_that_clears_every_step_passes():
    v = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows(STEADY)))
    # k2 chosen (+0.10 against +0.05 on the older days); unseen 320 trades at +0.20; QUIET's runs
    # make -0.002..+0.002 a trade (mean 0, sd 0.0014178): the bar 3.384 x 0.0014178 = 0.0048;
    # every day makes the same +0.20, so the bootstrap's error is 0
    assert v["setting"] == "k2" and v["passed"] is True and v["failed"] == ""
    assert v["unseen"]["trades"] == 320 and v["unseen"]["per_trade"] == pytest.approx(0.2)
    assert v["random"]["bar"] == pytest.approx(vp.Z * 0.0014178, abs=1e-5)
    assert v["bootstrap"]["se"] == pytest.approx(0.0, abs=1e-12) and v["bootstrap"]["days"] == 80
    assert v["coins"] == ["AAA_USDT", "BBB_USDT"] and v["id"] == vf.verdict_id("v3_snap", "1h",
                                                                               "none")
    assert v["months"] == ["2026-07", "2026-08", "2026-09", "2026-10"], "the months used"
    assert v["window"] == {"split": "Jul 25, 2026", "end": "Oct 23, 2026"}


def test_each_step_that_fails_names_the_verdict():
    # the luck bar: LOUD's runs make -0.2..+0.2 a trade (sd 0.14178): 3.384 x 0.14178 = 0.4798
    v = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows(STEADY), LOUD))
    assert (v["passed"], v["failed"]) == (False, "random") and v["checks"]["profit"] is True
    # losing money: -0.20 a trade
    v = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows([-1.2, 0.8] * 160)))
    assert v["failed"] == "profit"
    # +0.20 a trade, all of it from ONE day: 79 days of 4 losses of 0.1, and one day of 3 losses
    # and a +95.9 win. A draw holds that day K times, K ~ Binomial(80, 1/80): profit a trade
    # (96K - 32) / 320 = 0.3K - 0.1, sd 0.3 x sqrt(0.9875) = 0.298, and 0.2 - 3.384 x 0.298 < 0
    lucky = [-0.1] * 319 + [95.9]
    v = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows(lucky)))
    assert v["unseen"]["per_trade"] == pytest.approx(0.2) and v["failed"] == "bootstrap"
    assert v["bootstrap"]["se"] == pytest.approx(0.298, abs=0.03)
    # +0.20 a trade, the days swinging: 40 days of 4 trades at +1.2, 40 of 4 at -0.8. Every day
    # holds 4 trades, so a draw's profit a trade is the mean of 80 drawn days' averages, whose sd
    # is 1.0: the error sqrt(1 / 80) = 0.1118, and 0.2 - 3.384 x 0.1118 = -0.178 - not proven,
    # though 0.2 is 1.8 errors above 0
    swing = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows(([1.2] * 4 + [-0.8] * 4) * 40)))
    assert swing["bootstrap"]["se"] == pytest.approx(0.1118, abs=0.01)
    assert swing["failed"] == "bootstrap" and swing["checks"]["random"] is True
    # every check passes but there are 299 trades, not 300
    v = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows([0.2] * 299)))
    assert v["failed"] == "trades" and [v["checks"][k] for k in vp.CHECKS[:3]] == [True] * 3


def test_a_family_that_shines_only_on_the_older_days_fails():
    # +0.10 a trade on the older days, +0.001 on the unseen ones: under QUIET's 0.0048 bar
    coins = _two_coins(_rows([0.501, -0.499] * 160))
    v = vp.verdict("v3_snap", "1h", "none", coins)
    assert v["older"]["k2"]["per_trade"] == pytest.approx(0.10)
    assert v["unseen"]["per_trade"] == pytest.approx(0.001) and v["failed"] == "random"


def test_a_group_with_too_few_older_trades_or_no_coin_fails_at_the_choice():
    thin = [_coin("AAA_USDT", _rows([0.1] * 10), _rows([0.1] * 29), _rows(STEADY), QUIET)]
    v = vp.verdict("v3_snap", "1h", "none", thin)
    assert (v["failed"], v["setting"]) == ("choose", None) and "30 trades" in v["why"]
    v = vp.verdict("v3_trend", "1d", "none", thin)
    assert v["failed"] == "choose" and v["why"] == "no coin measured v3_trend on 1d"
    assert v["coins"] == [] and any("survivorship" in n for n in v["notes"])


def test_every_judged_group_gets_a_verdict_and_what_could_not_be_measured_is_summed():
    coins = _two_coins(_rows(STEADY))
    for c in coins:
        c["combos"][KEY]["unseen"].update(counts={"cost_unmeasured": 7, "missed": 2},
                                          filter={"signals": 50}, twins=[2, 0.75], over_book=3,
                                          lev=[12, 20], notional=[40.0, 120.0])
    out = vp.verdicts(coins)
    assert [(v["family"], v["tf"], v["filter"]) for v in out] == vf.judged()
    v = next(v for v in out if (v["family"], v["tf"], v["filter"]) == ("v3_snap", "1h", "none"))
    assert v["counts"] == {"cost_unmeasured": 14, "missed": 4, "signals": 100}
    assert (v["twins"], v["twins_pnl"], v["over_book"]) == (4, pytest.approx(1.5), 6)
    assert v["lev"] == [12, 20] and v["notional"] == [40.0, 120.0]
    assert sum(1 for v in out if v["failed"] == "choose") == 29
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_v3_proof.py -q`
Expected: `ImportError: cannot import name 'v3_proof' from 'tradingagents'` (1 error during collection).

- [ ] **Step 3: Implement** — `tradingagents/v3_proof.py`:

```python
"""THE V3 PROOF TEST — choose a family's setting on the OLDER days, judge it on
the UNSEEN days against random entries, keep every verdict.

Spec: docs/superpowers/specs/2026-10-22-backtest-v3-design.md (Part 3, "The
proof test"); decisions: docs/superpowers/specs/2026-10-23-backtest-v3-part2-
decisions.md ("The proof test"). Pure: it reads what `v3_measure.measure_coin`
returned for each coin and decides nothing anywhere else.

1. CHOOSE, on the older walks only: the setting with the best profit per
   trade after costs, pooled over the coins (the walks only signal in a
   coin's member months), with at least MIN_CHOOSE older trades; a tie goes
   to the simplest (the first of the family's settings).
2. JUDGE the chosen setting on the unseen walks, pooled. It passes only when,
   in this order (the first that fails names the verdict):
   * ``profit`` — profit per trade after costs above 0;
   * ``random`` — profit per trade above BOTH the (1 - α/2) point of the
     pooled random runs' profit per trade, read off a normal curve fitted to
     them (mean + z x standard deviation: 200 runs cannot show a tail that
     far out by counting), and the best of the runs, its floor;
   * ``bootstrap`` — profit per trade - z x its day-clustered standard error
     above 0: BOOT_DRAWS seeded draws of the unseen trading days (a trade's
     day is the UTC day it closed), with replacement;
   * ``trades`` — at least MIN_UNSEEN unseen trades.
   α = ALPHA / every combination measured (`v3_families.combos()`, 70 —
   counted, never estimated) and z = Φ⁻¹(1 - α/2), 3.384.
3. Every verdict is kept, passed or failed, with its numbers.

A trade still open when a walk ends (`why` END: at the split for the older
walk, at the plan's end for the unseen one) counts, marked at that candle's
close and paying the market exit; the verdict says how many there were.
"""
from __future__ import annotations

import random
from statistics import NormalDist, fmean, median, stdev

from tradingagents import v3_families as vf, v3_random as vrn, v3_universe as vu

ALPHA = 0.05
MIN_CHOOSE = 30
MIN_UNSEEN = 300
BOOT_DRAWS = 2000
DAY_MS = 86_400_000
CHECKS = ("profit", "random", "bootstrap", "trades")
TRIED = len(vf.combos())
NOTES = {
    "busy_hours": ("No family's universe holds stock tokens, so only the no-weekend half of "
                   "busy hours can bite."),
    "btc_mood": "Only crypto alt-coins' longs are filtered; BTC and other contracts pass.",
}


def z_for(tried: int, alpha: float = ALPHA) -> float:
    """Φ⁻¹(1 - α/2) for α = `alpha` / `tried`."""
    return NormalDist().inv_cdf(1 - alpha / tried / 2)


Z = z_for(TRIED)


def summary(rows) -> dict:
    """Pooled compact trade rows ([signal_ms, entry_ms, exit_ms, side, pnl,
    why]) in the order they closed: the standard kit's figures."""
    from tradingagents.v3_page import worst_run

    rows = sorted(rows, key=lambda r: (int(r[2]), int(r[1])))
    pnls = [float(r[4]) for r in rows]
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    win_avg = sum(p for p in pnls if p > 0) / wins if wins else None
    loss_avg = -sum(p for p in pnls if p <= 0) / (n - wins) if n - wins else None
    worst, worst_n = worst_run(pnls)
    profit = sum(pnls)
    return {"trades": n, "wins": wins, "losses": n - wins,
            "win_rate": wins / n if n else None,
            "break_even": (loss_avg / (win_avg + loss_avg)
                           if win_avg is not None and loss_avg is not None else None),
            "profit": profit, "per_trade": profit / n if n else None,
            "worst_run_usd": worst, "worst_run_trades": worst_n,
            "open_at_end": sum(1 for r in rows if r[5] == "END")}


def choose(older: dict, order) -> tuple[str | None, dict]:
    """(the chosen setting or None, every setting's older figures)."""
    table, best = {}, None
    for key in order:
        rows = older.get(key, [])
        n, profit = len(rows), sum(float(r[4]) for r in rows)
        table[key] = {"trades": n, "profit": profit, "per_trade": profit / n if n else None,
                      "eligible": n >= MIN_CHOOSE}
        if n >= MIN_CHOOSE and (best is None or table[key]["per_trade"] > table[best]["per_trade"]):
            best = key
    return best, table


def pool_random(per_coin) -> list[tuple[int, float]]:
    """Run k pooled over the coins: (its trades, its profit), summed."""
    runs: list[list] | None = None
    for coin_runs in per_coin:
        if runs is None:
            runs = [[0, 0.0] for _ in coin_runs]
        if len(coin_runs) != len(runs):
            raise ValueError(f"a coin holds {len(coin_runs)} random runs, another {len(runs)}")
        for k, (n, p) in enumerate(coin_runs):
            runs[k][0] += int(n)
            runs[k][1] += float(p)
    return [(n, p) for n, p in runs or []]


def random_bar(runs, z: float = Z) -> dict | None:
    """The luck bar from the pooled runs (those that traded): the normal
    curve's (1 - α/2) point and the best run, whichever is higher. None
    when fewer than two runs traded."""
    ppt = [p / n for n, p in runs if n]
    if len(ppt) < 2:
        return None
    mean, sd, best = fmean(ppt), stdev(ppt), max(ppt)
    return {"runs": len(runs), "traded": len(ppt), "median": median(ppt), "mean": mean,
            "sd": sd, "best": best, "normal": mean + z * sd, "bar": max(mean + z * sd, best)}


def boot_se(rows, seed: int, draws: int = BOOT_DRAWS) -> tuple[float | None, int]:
    """(the day-clustered standard error of profit per trade, trading days):
    `draws` seeded draws of the days, with replacement. None under 2 days."""
    days: dict[int, list] = {}
    for r in rows:
        d = days.setdefault(int(r[2]) // DAY_MS, [0.0, 0])
        d[0] += float(r[4])
        d[1] += 1
    keys = sorted(days)
    m = len(keys)
    if m < 2:
        return None, m
    rng = random.Random(seed)
    out = []
    for _ in range(draws):
        p = n = 0
        for _k in range(m):
            dp, dn = days[keys[int(rng.random() * m)]]
            p += dp
            n += dn
        out.append(p / n)
    return stdev(out), m


def _walks(used: list, key: str, part: str) -> list[dict]:
    return [c["combos"][key][part] for c in used if key in c.get("combos", {})]


def tally(walks: list[dict]) -> dict:
    """What the walks could not measure, or skipped, summed — the engine's
    counts, the filter's, the missed orders' market twins, and the trades
    bigger than the book readings' $100."""
    counts: dict[str, int] = {}
    for w in walks:
        for k, v in {**w.get("counts", {}), **w.get("filter", {})}.items():
            counts[k] = counts.get(k, 0) + int(v)
    lev = [x for w in walks for x in (w.get("lev") or [])]
    notional = [x for w in walks for x in (w.get("notional") or [])]
    return {"counts": counts,
            "twins": sum(int(w["twins"][0]) for w in walks if w.get("twins")),
            "twins_pnl": sum(float(w["twins"][1]) for w in walks if w.get("twins")),
            "over_book": sum(int(w.get("over_book", 0)) for w in walks),
            "lev": [min(lev), max(lev)] if lev else None,
            "notional": [min(notional), max(notional)] if notional else None}


def verdict(family: str, tf: str, filt: str, coins: list[dict], *, z: float = Z,
            tried: int = TRIED) -> dict:
    """One family on one timeframe with one filter, chosen and judged over
    every coin record that measured it."""
    keys = [vf.setting_key(family, v) for v in vf.FAMILIES[family]["settings"]]
    ck = {k: vf.combo_key(family, k, tf, filt) for k in keys}
    used = [c for c in coins if any(ck[k] in c.get("combos", {}) for k in keys)]
    older = {k: [r for w in _walks(used, ck[k], "older") for r in w["rows"]] for k in keys}
    chosen, table = choose(older, keys)
    window = next((c["windows"][tf] for c in used if tf in c.get("windows", {})), None)
    notes = [vu.SURVIVORSHIP] + ([NOTES[filt]] if filt in NOTES else [])
    base = {"id": vf.verdict_id(family, tf, filt), "family": family, "tf": tf, "filter": filt,
            "tried": tried, "alpha": ALPHA / tried, "z": z, "coins": [c["coin"] for c in used],
            "window": window, "months": next((c["unseen_months"] for c in used
                                               if c.get("unseen_months")), []),
            "older": table, "setting": chosen, "notes": notes}
    if chosen is None:
        why = (f"no coin measured {family} on {tf}" if not used else
               f"no setting had {MIN_CHOOSE} trades on the older days")
        return {**base, "passed": False, "failed": "choose", "why": why}
    key = ck[chosen]
    walks = _walks(used, key, "unseen")
    rows = [r for w in walks for r in w["rows"]]
    s = summary(rows)
    bar = random_bar(pool_random(c["combos"][key]["random"] for c in used
                                 if key in c["combos"]), z)
    se, days = boot_se(rows, vrn.seed_of("boot", key))
    ppt = s["per_trade"]
    checks = {"profit": ppt is not None and ppt > 0,
              "random": ppt is not None and bar is not None and ppt > bar["bar"],
              "bootstrap": ppt is not None and se is not None and ppt - z * se > 0,
              "trades": s["trades"] >= MIN_UNSEEN}
    failed = next((k for k in CHECKS if not checks[k]), "")
    return {**base, "passed": not failed, "failed": failed, "checks": checks, "unseen": s,
            "random": bar,
            "bootstrap": {"draws": BOOT_DRAWS, "days": days, "se": se,
                          "low": ppt - z * se if ppt is not None and se is not None else None},
            **tally(walks)}


def verdicts(coins: list[dict]) -> list[dict]:
    """Every judged group's verdict, in `v3_families.judged()` order."""
    return [verdict(f, tf, filt, coins) for f, tf, filt in vf.judged()]
```

- [ ] **Step 4: Run the tests to verify they pass, then lint**

Run: `.venv/Scripts/python -m pytest tests/test_v3_proof.py tests/test_v3_families.py tests/test_v3_random.py -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_proof.py tests/test_v3_proof.py`
Expected: `26 passed`, then `All checks passed!`

- [ ] **Step 5: The harddev hunt:**
  - **Blind choice:** `choose` reads only older rows; the random runs and the bootstrap read only the chosen setting's unseen rows.
  - **The correction is counted:** `TRIED` is `len(v3_families.combos())`, never a typed 70.
  - **Every verdict kept:** a group with no coin, no eligible setting or no unseen trade still returns a verdict naming the step it failed.
  - **Pooling:** random run k is summed over the coins before its profit a trade is taken; coins with different run counts raise.

- [ ] **Step 6: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_proof.py tests/test_v3_proof.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
feat(v3): the proof test - choose on the older days (30+ trades, ties to the simplest), judge on the unseen days against the random bar (normal fit at alpha 0.05/70, the best run as its floor) and a day-clustered bootstrap, 300+ trades, every verdict kept with the step it failed

Backtest v3 Part 2a, Task 7.
- harddev: a blind choice (older rows only), the correction counted (TRIED = len(combos())), every verdict kept (no coin, no eligible setting, no unseen trade), pooling (run k summed over the coins; unequal run counts raise)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 8: One coin's whole measurement

**Files:**
- Create: `tradingagents/v3_measure.py`
- Modify: `tradingagents/cost_store.py` (append `usual_slip` at the end of the module)
- Test: `tests/test_v3_measure.py`

**Interfaces:**
- Consumes: Task 2's `walk(forced=)` and `contract_of`; Tasks 3-6; `backtest_report.TFS`, `fine_bars`, `charged_slippage`; `cost_store.engine_book`, `coverage`; `auto_trader.maker_fee_floor`, `fee_floor`, `PAPER_SLIPPAGE`; `fx.contract_spec`, `klines`, `minutes` (through `fine_bars`), `funding_history`, `book_cost`.
- Produces:
  - `cost_store.usual_slip(packed) -> (median one-side cost | None, minutes it was read from)`;
  - `v3_measure.VERSION = 1`, `UNSEEN_DAYS = 90`, `BOOK_USD = 100.0`, `windows(plan) -> (start_ms, split_ms, end_ms)`, `bars_of(df, bar_ms, end_ms) -> {"t", "o", "h", "l", "c"}`, `flat_gap(sym, book, *, fx) -> (fraction, where it came from)`, `prefetch(sym, plan, leads, *, fx) -> dict`, `compact(walked, t, signals) -> dict`;
  - `measure_coin(sym, plan, *, runs=200, risk_usd=None, fx=None, log=None) -> record`. The record: `version`, `coin`, `kind`, `plan_end_ms`, `unseen_months`, `families`, `runs`, `risk_usd`, `pre` (contract, fees, `flat_slip`, `flat_slip_source`, `minutes`, `five_minute`, `coverage_older`, `coverage_unseen`, `funding`, `funding_from_ms`, `cycle_h`, `seconds`), `windows` {tf: {"start", "split", "end", "older_candles", "unseen_candles", "seconds"}}, `skipped` {tf: why}, `why` (only when no family applies), and `combos` {`v3_families.combo_key(...)`: {"older": walk, "unseen": walk, "random": [[trades, profit]] × runs, "random_short": int}}. A walk: `rows` [[signal_ms, entry_ms, exit_ms, side, pnl, why]], `counts` (the engine's nonzero counts), `filter` ({"signal_candles", "blocked", and the filter's count names}), `missed`, `twins` [n, pnl], `lev` [min, max] | None, `notional` [min, max] | None, `over_book`.

- [ ] **Step 1: Write the failing test** — `tests/test_v3_measure.py`:

```python
"""One coin's whole Backtest v3 measurement (decisions doc docs/superpowers/specs/
2026-10-23-backtest-v3-part2-decisions.md, "The window and the split", "What a
machine returns per coin"). Two small worlds on ONE timeline: every candle in
the window is BUILT from its own minutes (RCA-2026-09-12-A); the lead-in
before the window is flat candles the indicators read and nothing trades on.
The unseen days are shortened to 3 here (the real run's are 90)."""
import calendar

import numpy as np
import pandas as pd
import pytest

from tradingagents import book_history as bh, v3_families as vf, v3_measure as vm

M = 60_000
H = 60 * M
DAY = 24 * H
FLAT = (100.1, 99.9)                    # a flat minute: high, low (it "closes" at 100.0)
IV = {"Min60": H, "Hour4": 4 * H, "Day1": DAY}
SPEC = {"contractSize": 0.01, "minVol": 1, "maintenanceMarginRate": 0.005, "maxLeverage": 20,
        "minLeverage": 1, "funding_interval_h": 8}


def _utc(*ymdh):
    return calendar.timegm((*ymdh, 0, 0)) * 1000


class FakeFx:
    """Minutes over [start, end) - flat except `special` {minute ms: (high, low)} - and the
    candles of every interval built from them; 700 flat candles before the window; funding at
    0% every 8 hours from 60 days before; Gate-like listing. `listed`: no candle before it."""

    def __init__(self, start, end, special, listed=None):
        self.start, self.end, self.listed = start, end, listed
        self.t = list(range(start, end, M))
        hl = [special.get(x, FLAT) for x in self.t]
        self.hi, self.lo = [x[0] for x in hl], [x[1] for x in hl]

    def contract_spec(self, sym):
        return dict(SPEC)

    def klines(self, sym, iv, limit):
        bar = IV[iv]
        rows = []
        for o in range(self.start - 700 * bar, self.end, bar):
            if self.listed is not None and o < self.listed:
                continue
            if o < self.start:
                rows.append((o, 100.0, 100.1, 99.9, 100.0))
                continue
            a, b = (o - self.start) // M, (o + bar - self.start) // M
            h, lo = self.hi[a:b], self.lo[a:b]
            rows.append((o, (h[0] + lo[0]) / 2, max(h), min(lo), (h[-1] + lo[-1]) / 2))
        df = pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close"])
        df.insert(0, "Date", pd.to_datetime(df.pop("t"), unit="ms"))
        return df.assign(Volume=1.0).tail(limit).reset_index(drop=True)

    def minutes(self, sym, start_s, end_s):
        keep = [k for k, x in enumerate(self.t) if start_s * 1000 <= x <= end_s * 1000]
        return pd.DataFrame({"Date": pd.to_datetime([self.t[k] for k in keep], unit="ms"),
                             "High": [self.hi[k] for k in keep],
                             "Low": [self.lo[k] for k in keep], "Seconds": 60})

    def funding_history(self, sym, since_ms=None):
        return [{"settle_ms": x, "rate": 0.0, "cycle_h": 8}
                for x in range(self.start - 60 * DAY, self.end + 1, 8 * H)]

    def book_cost(self, sym, notional):
        raise AssertionError("the recorded book has minutes: no live read")


def _book(t_s):
    """One recorded reading, buying and selling $100 at 0.02% each: the coin's flat gap."""
    return bh.pack([{"t": t_s, "bid": 99.95, "ask": 100.05, "spread": 0.001, "buy": 0.0002,
                     "sell": 0.0002, "exhausted": False, "source": "full"}])


@pytest.fixture()
def gate_floors(monkeypatch):
    import tradingagents.auto_trader as at

    monkeypatch.setattr(at, "maker_fee_floor", lambda *a, **k: 0.0002)
    monkeypatch.setattr(at, "fee_floor", lambda *a, **k: 0.00075)
    monkeypatch.setattr(vm, "UNSEEN_DAYS", 3)


# ---- a calm metal whose hourly candles dip twice: once on the older days, once on the unseen

END_A = _utc(2026, 10, 4, 0)            # a Sunday; the window is Sep 24 - Oct 04, 2026
START_A, SPLIT_A = END_A - 10 * DAY, END_A - 3 * DAY
OLD_DIP, NEW_DIP = _utc(2026, 9, 25, 10), _utc(2026, 10, 3, 10)      # a Friday, a Saturday
EDGE_DIP = SPLIT_A - _utc(1970, 1, 1, 1)                             # the last older hour


def _dips(*hours, depth=0.0):
    """Each dip hour trades 99.2-99.4 (it opens and closes at 99.3); the next hour's first
    minute trades 99.25-99.35, then the market is back at 100."""
    out = {}
    for o in hours:
        out.update({o + m * M: (99.4 - depth, 99.2 - depth) for m in range(60)})
        out[o + H] = (99.35, 99.25)
    return out


def _plan(start, end, calm, liquid=None, strength=None, kinds=None):
    months = sorted(set(calm) | set(liquid or {}))
    return {"start_ms": start, "end_ms": end, "months": months,
            "calm": {m: calm.get(m, []) for m in months},
            "liquid": {m: (liquid or {}).get(m, []) for m in months},
            "strength": strength or {}, "mood": {"t": [], "up": []},
            "kinds": kinds or {"XAU_USDT": "metals"}}


def _metal(monkeypatch, special, calm=None):
    from tradingagents import cost_store

    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: _book(START_A // 1000))
    calm = calm or {"2026-09": ["XAU_USDT"], "2026-10": ["XAU_USDT"]}
    return vm.measure_coin("XAU_USDT", _plan(START_A, END_A, calm), runs=3,
                           fx=FakeFx(START_A, END_A, special))


SNAP = vf.combo_key("v3_snap", "k1.5", "1h", "none")


def _snap_pnl():
    # the dip closes at 99.3 under its 20-hour average (19 x 100 + 99.3) / 20 = 99.965; ATR(20) is
    # (19 x 0.2 + 0.8) / 20 = 0.23 (the dip's true range runs from the 100.0 close to 99.2), so
    # the emergency stop is 3 x 0.23 = 0.69 under the entry: a 0.6949% stop, $1 risk = $143.91 of
    # coin = 144 lots of 0.01 x 99.3. Out at the resting 99.965 target: maker in and out
    return 144 * 0.993 * (99.965 / 99.3 - 1 - 2 * 0.0002)


def test_a_coin_is_measured_for_every_family_setting_timeframe_and_filter_it_can_trade(
        monkeypatch, gate_floors):
    rec = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP))
    # a metal is calm every month: trend (3 settings x 1d, 4h), breakout (2 x 1d), snap
    # (2 x 1h, 4h) - 12 family-setting-timeframes x 5 filters. Never strength (liquid only)
    assert rec["families"] == ["v3_trend", "v3_breakout", "v3_snap"]
    assert len(rec["combos"]) == 60 and rec["skipped"] == {}
    old, new = rec["combos"][SNAP]["older"], rec["combos"][SNAP]["unseen"]
    # each dip's waiting buy at 99.3 fills in the next hour's first minute (low 99.25) and the
    # second minute (high 100.1) trades through the target
    assert old["rows"] == [[OLD_DIP, OLD_DIP + H, OLD_DIP + H + M, 1, pytest.approx(_snap_pnl()),
                            "TP"]]
    assert new["rows"] == [[NEW_DIP, NEW_DIP + H, NEW_DIP + H + M, 1,
                            pytest.approx(_snap_pnl()), "TP"]]
    assert old["lev"] == [20, 20] and old["notional"] == [pytest.approx(142.99, abs=0.01)] * 2
    assert old["over_book"] == 1, "$143 of coin is more than the $100 a reading walks"
    # a flat market gives the trend and breakout rules nothing
    assert rec["combos"][vf.combo_key("v3_trend", "n20", "1d", "none")]["older"]["rows"] == []


def test_the_older_walk_cannot_see_a_price_after_the_split(monkeypatch, gate_floors):
    calm_world = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP))
    # the same coin crashing to 50 on the first unseen day: everything older is unchanged, to the
    # bit - a walk that read even one candle past the split would see the crash candle
    crash = {**_dips(OLD_DIP, EDGE_DIP, NEW_DIP),
             **{SPLIT_A + m * M: (60.0, 50.0) for m in range(1440)}}
    crash_world = _metal(monkeypatch, crash)
    for key in calm_world["combos"]:
        assert crash_world["combos"][key]["older"] == calm_world["combos"][key]["older"], key
    assert crash_world["combos"][SNAP]["unseen"] != calm_world["combos"][SNAP]["unseen"]


def test_the_older_walks_data_is_cut_at_the_split():
    # by construction, not by a filter afterwards: the older walk is handed no minute, no order
    # book and no funding settlement after the split (a settlement AT the split is the last one a
    # trade closed there pays; a book stamped at the split is read 3 s after it, so it is out)
    s = SPLIT_A
    pre = {"fine": ([s - M, s, s + M], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0]),
           "book": bh.pack([{"t": (s - M) // 1000, "bid": 1.0, "ask": 1.1, "spread": 0.1,
                             "buy": 0.001, "sell": 0.001, "exhausted": False, "source": "full"},
                            {"t": s // 1000, "bid": 1.0, "ask": 1.1, "spread": 0.1, "buy": 0.001,
                             "sell": 0.001, "exhausted": False, "source": "full"}]),
           "funding": [{"settle_ms": s - 8 * H}, {"settle_ms": s}, {"settle_ms": s + 8 * H}]}
    cut = vm._before(pre, s)
    assert cut["fine"] == ([s - M], [1.0], [1.0])
    assert list(cut["book"]["t"]) == [(s - M) // 1000]
    assert [f["settle_ms"] for f in cut["funding"]] == [s - 8 * H, s]


def test_a_signal_on_the_last_older_candle_trades_in_neither_walk(monkeypatch, gate_floors):
    # the hour before the split dips too: its order would go in AT the split, an unseen minute, so
    # the older walk has no candle to fill it in (counted no_next_bar), and in the unseen walk its
    # signal candle is lead-in, read by the indicators only. On 4h the same dip is the close of
    # the last older candle: (19 x 100 + 99.3) / 20 = 99.965 less 1.5 x (19 x 0.2 + 0.9) / 20 =
    # 99.6125 is over 99.3, a signal there too - and it trades nowhere either
    rec = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP))
    for key in (SNAP, vf.combo_key("v3_snap", "k1.5", "4h", "none")):
        older, unseen = rec["combos"][key]["older"], rec["combos"][key]["unseen"]
        assert older["counts"]["no_next_bar"] == 1, key
        assert EDGE_DIP not in [r[0] for r in older["rows"] + unseen["rows"]], key
    assert [r[0] for r in rec["combos"][SNAP]["older"]["rows"]] == [OLD_DIP]
    assert [r[0] for r in rec["combos"][SNAP]["unseen"]["rows"]] == [NEW_DIP]


def test_signals_count_only_in_member_months_and_where_the_filter_lets_the_order_in(
        monkeypatch, gate_floors):
    rec = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP))
    # the unseen dip's order would go in on Saturday Oct 03, 11:00am UTC: busy hours blocks it;
    # the older one is a Friday's
    busy = rec["combos"][vf.combo_key("v3_snap", "k1.5", "1h", "busy_hours")]
    assert len(busy["older"]["rows"]) == 1 and busy["unseen"]["rows"] == []
    assert busy["unseen"]["filter"] == {"signal_candles": 1, "blocked": 1}
    # funding settles at 00:00, 08:00 and 4:00pm UTC: an 11:00am order is never near one
    fm = rec["combos"][vf.combo_key("v3_snap", "k1.5", "1h", "funding_minutes")]
    assert len(fm["unseen"]["rows"]) == 1 and "blocked" not in fm["unseen"]["filter"]
    # calm in September only: the October dip is no signal at all, the September one trades - and
    # the edge dip of Sep 30, 11:00pm UTC, whose order would go in at Oct 01 00:00, is an OCTOBER
    # signal (a signal's month is the month its order goes in), so it is no signal either: no
    # no_next_bar this time
    sep_only = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP),
                      calm={"2026-09": ["XAU_USDT"], "2026-10": []})
    assert sep_only["combos"][SNAP]["unseen"]["rows"] == []
    assert sep_only["combos"][SNAP]["unseen"]["filter"] == {}
    assert sep_only["combos"][SNAP]["older"]["rows"] == rec["combos"][SNAP]["older"]["rows"]
    assert rec["combos"][SNAP]["older"]["counts"]["no_next_bar"] == 1
    assert "no_next_bar" not in sep_only["combos"][SNAP]["older"]["counts"]


def test_the_coins_own_flat_gap_and_the_books_coverage_come_first(monkeypatch, gate_floors):
    rec = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP))
    pre = rec["pre"]
    assert pre["flat_slip"] == pytest.approx(0.0002)
    assert pre["flat_slip_source"] == "the median of its 1 recorded minutes"
    # the one reading (at the window's first second) answers its own minute and the 60 after
    # it: 61 of the older days' 7 x 1,440 minutes; nothing of the unseen days
    assert pre["coverage_older"] == pytest.approx(61 / (7 * 1440))
    assert pre["coverage_unseen"] == 0.0
    assert pre["contract"]["max_lev"] == 20 and pre["minutes"] == 10 * 1440
    assert rec["windows"]["1h"]["older_candles"] == 7 * 24
    assert rec["windows"]["1h"]["unseen_candles"] == 3 * 24
    assert rec["windows"]["1h"]["split"].endswith(("am", "pm"))
    # the unseen days, Oct 01 - Oct 04, 2026, fall in one month
    assert rec["unseen_months"] == ["2026-10"]


def test_random_runs_are_seeded_and_entered_like_the_real_run(monkeypatch, gate_floors):
    rec = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP))
    again = _metal(monkeypatch, _dips(OLD_DIP, EDGE_DIP, NEW_DIP))
    runs = rec["combos"][SNAP]["random"]
    assert len(runs) == 3 and runs == again["combos"][SNAP]["random"], "seeded"
    # the real unseen run placed one order (October, long), so each run places one, on an
    # October hour; on a flat hour a snap has no average to aim at and does not trade
    assert all(n in (0, 1) for n, _p in runs) and rec["combos"][SNAP]["random_short"] == 0
    # a filter that blocked the real order leaves the random runs nothing to match
    busy = rec["combos"][vf.combo_key("v3_snap", "k1.5", "1h", "busy_hours")]
    assert busy["random"] == [[0, 0.0]] * 3


def test_the_risk_reaches_every_walk_and_a_risk_under_one_lot_trades_nothing(monkeypatch,
                                                                            gate_floors):
    from tradingagents import cost_store

    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: _book(START_A // 1000))
    plan = _plan(START_A, END_A, {"2026-09": ["XAU_USDT"], "2026-10": ["XAU_USDT"]})
    rec = vm.measure_coin("XAU_USDT", plan, runs=1, fx=FakeFx(START_A, END_A, _dips(OLD_DIP)))
    assert rec["risk_usd"] == 1.0, "the spec's $1 by default"
    # $2 risk: $287.82 of coin at the same 0.6949% stop = 289 lots of 0.993 (at $1 it was 144:
    # lots round down, which is why a risk is measured, never rescaled afterwards)
    two = vm.measure_coin("XAU_USDT", plan, runs=1, risk_usd=2.0,
                          fx=FakeFx(START_A, END_A, _dips(OLD_DIP)))
    (row,) = two["combos"][SNAP]["older"]["rows"]
    assert row[4] == pytest.approx(289 * 0.993 * (99.965 / 99.3 - 1 - 2 * 0.0002))
    # half a cent of risk is $0.72 of coin, under one $0.99 lot: no trade, and it is counted
    tiny = vm.measure_coin("XAU_USDT", plan, runs=1, risk_usd=0.005,
                           fx=FakeFx(START_A, END_A, _dips(OLD_DIP)))
    old = tiny["combos"][SNAP]["older"]
    assert old["rows"] == [] and old["counts"] == {"too_small": 1}


def test_a_young_coin_is_measured_on_what_exists_and_one_listed_after_the_split_is_named(
        monkeypatch, gate_floors):
    from tradingagents import cost_store
    from tradingagents.positions_view import fmt_when

    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: _book(START_A // 1000))
    plan = _plan(START_A, END_A, {"2026-09": ["XAU_USDT"], "2026-10": ["XAU_USDT"]})
    # listed Sep 29, 2026: two older days (Sep 29, 30) and the three unseen ones - measured, its
    # window starting where its candles do, never at the plan's start
    young = vm.measure_coin("XAU_USDT", plan, runs=1,
                            fx=FakeFx(START_A, END_A, {}, listed=START_A + 5 * DAY))
    assert young["skipped"] == {} and young["windows"]["1d"]["older_candles"] == 2
    assert young["windows"]["1d"]["start"] == fmt_when((START_A + 5 * DAY) / 1000)
    # listed on the first unseen day: no older candle on any timeframe - nothing to choose a
    # setting on, so every timeframe is skipped and says why
    late = vm.measure_coin("XAU_USDT", plan, runs=1,
                           fx=FakeFx(START_A, END_A, {}, listed=SPLIT_A))
    assert late["combos"] == {}
    assert late["skipped"] == {"1h": "0 older and 72 unseen 1h candles",
                               "4h": "0 older and 18 unseen 4h candles",
                               "1d": "0 older and 3 unseen 1d candles"}


def test_a_coin_in_no_familys_universe_is_named_not_measured(monkeypatch, gate_floors):
    rec = vm.measure_coin("AAPL_USDT", _plan(START_A, END_A, {"2026-09": []},
                                             kinds={"AAPL_USDT": "stocks"}),
                          runs=3, fx=FakeFx(START_A, END_A, {}))
    assert rec["combos"] == {} and rec["why"] == "in no family's universe in any month of the plan"


# ---- a liquid coin the Monday ranks pick, then drop: v3_strength's forced exit -----------

END_B = _utc(2026, 10, 7, 0)            # a Wednesday; the window is Sep 20 - Oct 07, 2026
START_B, SPLIT_B = END_B - 17 * DAY, END_B - 3 * DAY
SEP21, SEP28, OCT5 = _utc(2026, 9, 21, 0), _utc(2026, 9, 28, 0), _utc(2026, 10, 5, 0)


def test_strength_enters_on_a_monday_and_is_forced_out_when_it_drops_past_the_top_2k(
        monkeypatch, gate_floors):
    from tradingagents import cost_store

    others = [f"C{k}_USDT" for k in range(9)]
    plan = _plan(START_B, END_B, {}, liquid={"2026-09": ["ABC_USDT"] + others,
                                             "2026-10": ["ABC_USDT"] + others},
                 strength={str(SEP21): ["ABC_USDT"] + others,          # 1st
                           str(SEP28): others[:8] + ["ABC_USDT"],      # 9th
                           str(OCT5): ["ABC_USDT"] + others},          # 1st
                 kinds={"ABC_USDT": "crypto"})
    # the book also holds a reading stamped AT the split - the book 3 s after it, an unseen
    # price - whose book ran out (so it is no part of the flat gap) and costs 5% to sell into
    split_book = {"t": SPLIT_B // 1000, "bid": 99.0, "ask": 101.0, "spread": 0.02, "buy": 0.05,
                  "sell": 0.05, "exhausted": True, "source": "full"}
    book = cost_store.merge(_book(START_B // 1000), bh.pack([split_book]))
    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: book)
    # Oct 05 and Oct 06 trade 100.9-101.1: a Monday order at Oct 05's 101.0 close fills on
    # Oct 06, while an order at a Sunday's 100.0 close would never fill on Oct 05
    up = {OCT5 + m * M: (101.1, 100.9) for m in range(2 * 1440)}
    rec = vm.measure_coin("ABC_USDT", plan, runs=6, fx=FakeFx(START_B, END_B, up))
    assert rec["families"] == ["v3_trend", "v3_breakout", "v3_strength"]
    # 1st on Monday Sep 21: the order goes in at the candle's close, Tuesday 00:00, and the flat
    # day's 99.9 low fills it. ATR(20) of flat days is 0.2: a 0.6 trail, a 0.6% stop, $1 risk =
    # 166 lots of 0.01 x $100. 9th on Sep 28, past 2K = 6: out at that Monday's close, 100.0, at
    # the market - taker 0.075% plus the coin's 0.02% gap, and the maker 0.02% in
    k3 = rec["combos"][vf.combo_key("v3_strength", "k3", "1d", "none")]
    assert k3["older"]["rows"] == [[SEP21, SEP21 + DAY, SEP28 + DAY, 1,
                                    pytest.approx(-166.0 * (0.0002 + 0.00075 + 0.0002)), "RANK"]]
    # K = 5: 9th is inside 2K = 10, so the trade is still open at the split and closes there, at
    # the last older close, 100.0 - paying the coin's flat 0.02% gap, never the 5% of the reading
    # stamped at the split, which the older walk cannot see
    k5 = rec["combos"][vf.combo_key("v3_strength", "k5", "1d", "none")]
    assert k5["older"]["rows"] == [[SEP21, SEP21 + DAY, SPLIT_B, 1,
                                    pytest.approx(-166.0 * (0.0002 + 0.00075 + 0.0002)), "END"]]
    assert k5["older"]["counts"]["cost_unmeasured"] == 1
    # unseen: 1st on Monday Oct 05, in at Oct 06 00:00 at 101.0, open at the window's end
    assert [(r[0], r[1], r[5]) for r in k3["unseen"]["rows"]] == [(OCT5, OCT5 + DAY, "END")]
    # strength only ever enters on a Monday, and Oct 05 is the unseen days' one: every random
    # run enters exactly where the real one did, and makes what it made (a run drawn on Sunday
    # Oct 04 would rest at 100.0 and never fill)
    real = k3["unseen"]["rows"][0][4]
    assert k3["random"] == [[1, pytest.approx(real)]] * 6


def test_the_flat_gap_falls_back_to_a_live_read_then_to_the_paper_figure_and_says_so():
    import tradingagents.auto_trader as at
    from tradingagents import cost_store

    class Live:
        def __init__(self, slip):
            self.slip = slip

        def book_cost(self, sym, notional):
            if self.slip is None:
                raise RuntimeError("book unreadable")
            return {"slippage": self.slip}

    empty = cost_store.empty()
    assert vm.flat_gap("X_USDT", empty, fx=Live(0.0004)) == (
        0.0004, "one live reading of its book (no minute recorded)")
    assert vm.flat_gap("X_USDT", empty, fx=Live(0.0))[0] == at.PAPER_SLIPPAGE, "never a free 0"
    assert vm.flat_gap("X_USDT", None, fx=Live(None)) == (
        at.PAPER_SLIPPAGE, "the app's paper figure: no book could be read (RuntimeError)")


def test_usual_slip_is_the_median_of_the_minutes_whose_book_did_not_run_out():
    from tradingagents import cost_store

    rows = [{"t": 60 * k, "bid": 1.0, "ask": 1.1, "spread": 0.1, "buy": b, "sell": s,
             "exhausted": x, "source": "full"}
            for k, (b, s, x) in enumerate([(0.0001, 0.0003, False), (0.0002, 0.0004, False),
                                           (0.0005, 0.0007, False), (0.01, 0.01, True)])]
    # (buy + sell) / 2 of the three that did not run out: 0.0002, 0.0003, 0.0006 - median 0.0003
    assert cost_store.usual_slip(bh.pack(rows)) == (pytest.approx(0.0003), 3)
    assert cost_store.usual_slip(cost_store.empty()) == (None, 0)
    assert cost_store.usual_slip(None) == (None, 0)


def test_the_candles_are_cut_at_the_plans_end_never_at_the_clock():
    t = [END_A - 2 * H, END_A - H, END_A]
    df = pd.DataFrame({"Date": pd.to_datetime(t, unit="ms"), "Open": [1.0, 2.0, 3.0],
                       "High": [1.0, 2.0, 3.0], "Low": [1.0, 2.0, 3.0], "Close": [1.0, 2.0, 3.0]})
    got = vm.bars_of(df, H, END_A)
    assert got["t"] == [END_A - 2 * H, END_A - H] and got["c"] == [1.0, 2.0]
    assert np.int64(got["t"][0]) == END_A - 2 * H
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_v3_measure.py -q`
Expected: `ImportError: cannot import name 'v3_measure' from 'tradingagents'` (1 error during collection).

- [ ] **Step 3: Implement — the coin's own usual gap.** Append to the end of `tradingagents/cost_store.py` (two blank lines before it):

```python
def usual_slip(packed: dict | None) -> tuple[float | None, int]:
    """A coin's OWN usual one-side cost (CLAUDE.md rule 10: per contract,
    never averaged across coins): the median over its recorded minutes of the
    average of buying and selling the book's $100, leaving out minutes whose
    book ran out. (median or None when nothing usable was recorded, the
    minutes it was read from.) The confluence shard keeps its own copy of
    this rule (.github/scripts/cq_shard.py `usual_slip`)."""
    import numpy as np

    if packed is None or not len(packed.get("t", [])):
        return None, 0
    ok = ~np.asarray(packed["exhausted"], dtype=bool)
    both = (np.asarray(packed["buy"], dtype=float)[ok]
            + np.asarray(packed["sell"], dtype=float)[ok]) / 2
    both = both[np.isfinite(both)]
    return (float(np.median(both)) if len(both) else None), int(len(both))
```

- [ ] **Step 4: Implement** — `tradingagents/v3_measure.py`:

```python
"""ONE COIN'S WHOLE BACKTEST V3 MEASUREMENT — what one GitHub machine will
return per coin (Part 2b), runnable on this PC now (Part 2a).

Decisions doc: docs/superpowers/specs/2026-10-23-backtest-v3-part2-
decisions.md ("The window and the split", "What a machine returns per
coin"). For every family the plan lets the coin trade, on each of the
family's timeframes, for every setting and every filter:

* the OLDER walk: the candles from the window's start (the plan's end - 365
  days) up to the split (the plan's end - 90 days), with the setting's
  lead-in before them; a trade still open at the split is closed at its last
  candle (`END`). Its minutes, order books and funding are CUT at the split,
  so the setting can never be chosen on an unseen price — by construction;
* the UNSEEN walk: the newest 90 days, the lead-in before them read by the
  indicators only;
* RUNS random runs on the unseen window (`v3_random`), measured for EVERY
  setting so the choice stays blind (only the chosen one is ever read).

ONE read per coin: its candles per timeframe, a year of minutes, the order
books, funding and its listing, and the coin's OWN flat gap (the median of
its recorded minutes, `cost_store.usual_slip`), then every walk off them.
Signals count only in the months the coin is a member of the family's
universe, on the sides that membership allows, and only where the filter
lets the order through — a per-candle mask on the signal, never a filter on
trades afterwards. Nothing is chosen here: `v3_proof` chooses and judges
after every coin is in.

Every number is kept compact: trade rows [signal_ms, entry_ms, exit_ms,
side, pnl, why], the engine's counts, the filter's counts, and each random
run's [trades, profit].
"""
from __future__ import annotations

import bisect
import time

from tradingagents import (
    v3_engine as ve,
    v3_families as vf,
    v3_filters as vfl,
    v3_random as vrn,
    v3_universe as vu,
)

VERSION = 1
UNSEEN_DAYS = 90
DAY_MS = 86_400_000
BOOK_USD = 100.0          # a recorded reading is the cost of walking the book for $100
FUNDING_PAD_DAYS = 31     # funding_side reads the 30 days before each order
TF_ORDER = ("1h", "4h", "1d")


def windows(plan: dict) -> tuple[int, int, int]:
    """(window start, split, end) in ms: the plan's own, the same for every
    coin and every machine."""
    end = int(plan["end_ms"])
    return int(plan["start_ms"]), end - UNSEEN_DAYS * DAY_MS, end


def bars_of(df, bar_ms: int, end_ms: int) -> dict:
    """A candle frame -> {"t" (opens ms), "o", "h", "l", "c"}, only the
    candles that CLOSED by `end_ms` (the plan's end, never the clock)."""
    t = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    keep = t + int(bar_ms) <= int(end_ms)
    col = {"o": "Open", "h": "High", "l": "Low", "c": "Close"}
    return {"t": [int(x) for x in t[keep]],
            **{k: [float(x) for x in df[v].to_numpy()[keep]] for k, v in col.items()}}


def flat_gap(sym: str, book, *, fx) -> tuple[float, str]:
    """The coin's own usual one-side cost where a minute has no recorded
    book, and where it came from (said beside every result)."""
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br, cost_store

    slip, n = cost_store.usual_slip(book)
    if slip is not None:
        return slip, f"the median of its {n:,} recorded minutes"
    try:
        live = float(fx.book_cost(sym, BOOK_USD).get("slippage") or 0.0)
        return (br.charged_slippage([live or at.PAPER_SLIPPAGE]),
                "one live reading of its book (no minute recorded)")
    except Exception as exc:                                   # noqa: BLE001
        return at.PAPER_SLIPPAGE, (f"the app's paper figure: no book could be read "
                                   f"({type(exc).__name__})")


def prefetch(sym: str, plan: dict, leads: dict, *, fx) -> dict:
    """Everything one coin's walks read, fetched ONCE: {tf: bars} with each
    timeframe's longest lead-in before the window, the minutes of the window,
    its order books, funding, the listing and the fees."""
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br, cost_store

    start, split, end = windows(plan)
    spec = fx.contract_spec(sym)
    contract = ve.contract_of(spec)
    now_ms = int(time.time() * 1000)
    bars = {}
    for tf, lead in leads.items():
        iv, bar_s, _cap = br.TFS[tf]
        bar_ms = bar_s * 1000
        need = -(-(now_ms - (start - lead * bar_ms)) // bar_ms) + 2
        bars[tf] = bars_of(fx.klines(sym, iv, need), bar_ms, end)
    ft, fh, fl, n5 = br.fine_bars(sym, start // 1000, end // 1000, fx=fx)
    keep = ft < end
    fine = (ft[keep].tolist(), fh[keep].tolist(), fl[keep].tolist())
    book = cost_store.engine_book(sym, start // 1000, end // 1000)
    slip, source = flat_gap(sym, book, fx=fx)
    funding = [f for f in fx.funding_history(sym, since_ms=start - FUNDING_PAD_DAYS * DAY_MS)
               if int(f["settle_ms"]) <= end]
    fees = {"maker": at.maker_fee_floor(), "taker": at.fee_floor()}
    meta = {"contract": contract, "fees": fees, "flat_slip": slip, "flat_slip_source": source,
            "minutes": len(fine[0]), "five_minute": int(n5),
            "coverage_older": cost_store.coverage(book, start // 1000, split // 1000),
            "coverage_unseen": cost_store.coverage(book, split // 1000, end // 1000),
            "funding": len(funding),
            "funding_from_ms": int(funding[0]["settle_ms"]) if funding else None,
            "cycle_h": float(spec.get("funding_interval_h") or 8)}
    return {"bars": bars, "fine": fine if fine[0] else None, "book": book, "funding": funding,
            "contract": contract, "fees": fees, "slip": slip, "cycle_h": meta["cycle_h"],
            "meta": meta}


def _before(pre: dict, split: int) -> dict:
    """The older walk's data: minutes, order books and funding CUT at the
    split, so nothing it reads can be an unseen price."""
    fine, book = pre["fine"], pre["book"]
    if fine is not None:
        j = bisect.bisect_left(fine[0], split)
        fine = (fine[0][:j], fine[1][:j], fine[2][:j])
    if book is not None:
        import numpy as np

        j = int(np.searchsorted(book["t"], split // 1000, side="left"))
        book = {k: v[:j] for k, v in book.items()}
    return {"fine": fine, "book": book,
            "funding": [f for f in pre["funding"] if int(f["settle_ms"]) <= split]}


def _view(bars: dict, a: int, b: int) -> dict:
    return {k: v[a:b] for k, v in bars.items()}


def compact(walked: dict, t, signals: dict) -> dict:
    """One walk in the shape every machine returns."""
    trades = walked["trades"]
    twins = [m["market"] for m in walked["missed"] if "pnl" in m["market"]]
    lev = [int(x["leverage"]) for x in trades]
    notional = [float(x["notional"]) for x in trades]
    return {"rows": [[int(t[x["signal_bar"]]), int(x["entry_ms"]), int(x["exit_ms"]),
                      int(x["side"]), round(float(x["pnl"]), 6), x["why"]] for x in trades],
            "counts": {k: int(v) for k, v in walked["counts"].items() if v},
            "filter": signals, "missed": len(walked["missed"]),
            "twins": [len(twins), round(sum(float(x["pnl"]) for x in twins), 6)],
            "lev": [min(lev), max(lev)] if lev else None,
            "notional": [round(min(notional), 2), round(max(notional), 2)] if notional else None,
            "over_book": sum(1 for x in notional if x > BOOK_USD)}


def _signals(rule, long_m, short_m, keep_l, keep_s, flags, a: int, start: int) -> dict:
    """Among a walk's tradable candles (from `start` to the one before last):
    the candles the rule held on inside the universe (`signal_candles`), the
    ones the filter blocked, and the filter's own counts (unknown, judged by
    the cycle)."""
    out: dict[str, int] = {}
    for i in range(int(start), len(rule) - 1):
        r, g = rule[i], a + i
        if not ((r == 1 and long_m[g]) or (r == -1 and short_m[g])):
            continue
        out["signal_candles"] = out.get("signal_candles", 0) + 1
        if not (keep_l[g] if r == 1 else keep_s[g]):
            out["blocked"] = out.get("blocked", 0) + 1
        if flags[g]:
            out[flags[g]] = out.get(flags[g], 0) + 1
    return out


def _measure_tf(rec: dict, sym: str, kind: str, tf: str, fams: list, pre: dict, plan: dict,
                runs: int, risk_usd: float) -> str:
    """Every family, setting and filter of one timeframe into `rec`; "" when
    measured, else why not."""
    from tradingagents import backtest_report as br
    from tradingagents.positions_view import fmt_when

    start, split, end = windows(plan)
    bar_s = br.TFS[tf][1]
    bar_ms = bar_s * 1000
    b = pre["bars"][tf]
    t = b["t"]
    i0, i1 = bisect.bisect_left(t, start), bisect.bisect_left(t, split)
    if i1 - i0 < 2 or len(t) - i1 < 2:
        return f"{max(0, i1 - i0)} older and {max(0, len(t) - i1)} unseen {tf} candles"
    order = [x + bar_ms for x in t]
    masks = {f: vfl.masks(f, sym=sym, kind=kind, order_ms=order, funding=pre["funding"],
                          cycle_h=pre["cycle_h"], plan=plan) for f in vf.FILTERS}
    rec["windows"][tf] = {"start": fmt_when(t[i0] / 1000), "split": fmt_when(split / 1000),
                          "end": fmt_when(end / 1000), "older_candles": i1 - i0,
                          "unseen_candles": len(t) - i1}
    data = {"older": _before(pre, split),
            "unseen": {"fine": pre["fine"], "book": pre["book"], "funding": pre["funding"]}}
    common = {"bar_s": bar_s, "contract": pre["contract"], "fees": pre["fees"],
              "flat_slip": pre["slip"], "risk_usd": risk_usd}
    for fam in fams:
        if tf not in vf.FAMILIES[fam]["tfs"]:
            continue
        long_m, short_m = vf.sides_allowed(fam, sym, plan, order)
        days = vf.entry_days(fam, b)
        for v in vf.FAMILIES[fam]["settings"]:
            lead, spec = vf.lead(fam, v, tf), vf.exit_spec(fam, v, tf)
            parts = {}
            for part, (a, z, s0) in (("older", (max(0, i0 - lead), i1, i0)),
                                     ("unseen", (max(0, i1 - lead), len(t), i1))):
                vb = _view(b, a, z)
                parts[part] = {"bars": vb, "a": a, "start": s0 - a,
                               "rule": vf.rule(fam, v, tf, vb, sym=sym, plan=plan),
                               "forced": vf.forced(fam, v, tf, vb, sym=sym, plan=plan)}
            for filt in vf.FILTERS:
                keep_l, keep_s, flags = masks[filt]
                ok_l = [m and k for m, k in zip(long_m, keep_l, strict=True)]
                ok_s = [m and k for m, k in zip(short_m, keep_s, strict=True)]
                out, walked = {}, {}
                for part, p in parts.items():
                    a = p["a"]
                    dirs = [1 if r == 1 and ok_l[a + i] else -1 if r == -1 and ok_s[a + i] else 0
                            for i, r in enumerate(p["rule"])]
                    walked[part] = ve.walk(p["bars"], dirs, spec, start=p["start"],
                                           forced=p["forced"], **common, **data[part])
                    out[part] = compact(walked[part], p["bars"]["t"],
                                        _signals(p["rule"], long_m, short_m, keep_l, keep_s,
                                                 flags, a, p["start"]))
                u = parts["unseen"]
                seeds = [vrn.seed_of(sym, tf, fam, filt, k) for k in range(runs)]
                out["random"], out["random_short"] = _random_runs(
                    u, walked["unseen"], ok_l, ok_s, days, bar_ms, seeds,
                    {**common, **data["unseen"], "start": u["start"], "forced": u["forced"]},
                    spec)
                rec["combos"][vf.combo_key(fam, vf.setting_key(fam, v), tf, filt)] = out
    return ""


def _random_runs(p: dict, real: dict, ok_l, ok_s, days, bar_ms: int, seeds, walk_kw: dict,
                 spec: dict) -> tuple[list, int]:
    """One random run per seed on the unseen view `p`: [[trades, profit], ...]
    and how many entries, over all the runs, could not be placed. Entries are
    drawn where the side is allowed (universe and filter) on the family's
    entry days."""
    wanted = vrn.entries_by_month(real, p["bars"]["t"], bar_ms)
    if not wanted:
        return [[0, 0.0] for _ in seeds], 0
    a, n = p["a"], len(p["rule"])
    cands = vrn.candidates(p["bars"]["t"], bar_ms, p["start"],
                           [ok_l[a + i] and days[a + i] for i in range(n)],
                           [ok_s[a + i] and days[a + i] for i in range(n)])
    out, short = [], 0
    for seed in seeds:
        dirs, missing = vrn.draw(n, wanted, cands, seed)
        short += missing
        w = ve.walk(p["bars"], dirs, spec, **walk_kw)
        out.append([len(w["trades"]), round(sum(float(x["pnl"]) for x in w["trades"]), 6)])
    return out, short


def measure_coin(sym: str, plan: dict, *, runs: int = vrn.RUNS, risk_usd: float | None = None,
                 fx=None, log=None) -> dict:
    """Every combination the plan lets `sym` trade, walked older and unseen,
    with `runs` random runs each on the unseen window (see the module doc),
    every trade risking `risk_usd` (None: `v3_rules.RISK_USD`, the spec's
    $1). The risk decides which trades exist at all: a trade under one lot
    is skipped and counted (`too_small`), so coins measured at two risks
    are never pooled."""
    from tradingagents import v3_rules as vr

    risk_usd = vr.RISK_USD if risk_usd is None else float(risk_usd)
    if fx is None:
        from tradingagents.dataflows import exchange as fx
    kind = plan.get("kinds", {}).get(sym, "unknown")
    fams = [f for f in vf.FAMILIES if vf.applies(plan, f, sym)]
    _start, split, end = windows(plan)
    rec = {"version": VERSION, "coin": sym, "kind": kind, "plan_end_ms": int(plan["end_ms"]),
           "unseen_months": [vu.month_key(x) for x in vu.months_between(split, end)],
           "families": fams, "runs": int(runs), "risk_usd": risk_usd, "windows": {}, "combos": {},
           "skipped": {}}
    if not fams:
        rec["why"] = "in no family's universe in any month of the plan"
        return rec
    tfs = [tf for tf in TF_ORDER if any(tf in vf.FAMILIES[f]["tfs"] for f in fams)]
    leads = {tf: max(vf.lead(f, v, tf) for f in fams if tf in vf.FAMILIES[f]["tfs"]
                     for v in vf.FAMILIES[f]["settings"]) for tf in tfs}
    t0 = time.time()
    pre = prefetch(sym, plan, leads, fx=fx)
    rec["pre"] = {**pre["meta"], "seconds": round(time.time() - t0, 1)}
    for tf in tfs:
        t1 = time.time()
        why = _measure_tf(rec, sym, kind, tf, fams, pre, plan, runs, risk_usd)
        if why:
            rec["skipped"][tf] = why
        else:
            rec["windows"][tf]["seconds"] = round(time.time() - t1, 1)
        if log:
            log(f"  {sym} {tf}: {why or 'measured'} ({time.time() - t1:.0f} s)")
    return rec
```

- [ ] **Step 5: Run the tests to verify they pass, then lint**

Run: `.venv/Scripts/python -m pytest tests/test_v3_measure.py tests/test_cost_store.py tests/test_cost_coverage.py -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_measure.py tradingagents/cost_store.py tests/test_v3_measure.py`
Expected: `28 passed` (14 + 11 + 3), then `All checks passed!`

- [ ] **Step 6: The harddev hunt:**
  - **By construction:** the older walk's candles end at the split, and its minutes, books and funding are cut there (`_before`); the strength test's K = 5 `END` row proves a book reading stamped at the split is not read.
  - **One read per coin:** candles per timeframe with that timeframe's longest lead-in, one year of minutes, one book, one funding list; every walk reads them.
  - **Failure paths:** a funding page that fails raises (a short history makes trades cheaper than they were); a timeframe with under 2 older or unseen candles is skipped and named; a coin in no group returns `why`.
  - **Costs:** the flat gap is the coin's own (never one figure for every coin); a live read of 0 or no book at all falls back to `PAPER_SLIPPAGE`, labelled.
  - **Book size:** readings are the cost of $100; trades bigger than that are counted `over_book` on every walk.

- [ ] **Step 7: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_measure.py tradingagents/cost_store.py tests/test_v3_measure.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
feat(v3): one coin's whole v3 measurement - every family, setting, timeframe and filter walked on the older days (data cut at the split) and the unseen days, 200 seeded random runs each, from one read of the coin with its own flat gap, in the compact shape a machine returns

Backtest v3 Part 2a, Task 8. cost_store.usual_slip is the coin's own median one-side cost of its recorded minutes (CLAUDE.md rule 10).
- harddev: by construction (the older walk's minutes, books and funding cut at the split; the K=5 END row reads no book stamped at the split), one read per coin, failure paths (a failed funding page raises; a timeframe with under 2 older or unseen candles is named), the coin's own flat gap (labelled fallbacks), trades bigger than the $100 readings counted

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 9: The command, and the first real plan

**Files:**
- Create: `tradingagents/v3_research.py`
- Test: `tests/test_v3_research.py`
- Create (by running it): `research/v3/plan.json`

**Interfaces:**
- Consumes: Tasks 3, 4, 7 and 8; `stores.V3.home`; `v3_rules.RISK_USD`; `positions_view.fmt_when`.
- Produces: `DEFAULT_LABEL = "local"`, `CRASH_GUARD`, `FEW_COINS`; `home(label) -> Path` (`stores.V3.home / "research" / label`), `coin_file(root, sym)`, `save_coin(root, rec)`, `load_coins(root)`, `money`, `pct`, `exit_words(family, key) -> (target words, stop words)`, `coin_line(rec)`, `header_lines(plan, runs, coins, risk)`, `verdict_lines(verdict)`, `report(records, plan, runs, risk) -> (lines, verdicts)`, `main(argv=None) -> int`; the command `python -m tradingagents.v3_research plan [--out PATH] | run COIN [COIN ...] [--plan PATH] [--runs N] [--risk USD] [--label NAME] | judge [--plan PATH] [--runs N] [--risk USD] [--label NAME]`.

- [ ] **Step 1: Write the failing test** — `tests/test_v3_research.py`:

```python
"""The Backtest v3 Part 2a command (`python -m tradingagents.v3_research`): it
builds the plan, measures a few coins, prints the order books' coverage FIRST
and then every verdict with the standard kit's figures, and never pools a
coin measured under another plan."""
import calendar
import json

import pytest

from tradingagents import v3_families as vf, v3_research as vr, v3_universe as vu

DAY = 86_400_000
END = calendar.timegm((2026, 10, 23, 0, 0, 0)) * 1000
D0 = END - 90 * DAY
KEY = vf.combo_key("v3_snap", "k2", "1h", "none")
KEY15 = vf.combo_key("v3_snap", "k1.5", "1h", "none")


def _rows(pnls, per_day=4):
    return [[D0 + (k // per_day) * DAY, D0 + (k // per_day) * DAY + 60_000,
             D0 + (k // per_day) * DAY + 3_600_000, 1, p, "TP"] for k, p in enumerate(pnls)]


def _walk(rows):
    return {"rows": rows, "counts": {"cost_unmeasured": 5}, "filter": {"signal_candles": 9},
            "twins": [1, 0.5], "lev": [20, 20], "notional": [45.0, 130.0], "over_book": 2}


def _record(coin="XAU_USDT", end=END, risk=1.0):
    """A coin whose snap 1h k2 makes +0.10 a trade on 40 older trades and +0.20 on 320 unseen
    ones (1.2 and -0.8 in turn), against random runs of -0.002..+0.002 a trade."""
    quiet = [[100, 0.1 * ((k % 5) - 2)] for k in range(200)]
    return {"coin": coin, "kind": "metals", "plan_end_ms": end, "runs": 200, "risk_usd": risk,
            "pre": {"coverage_older": 0.0, "coverage_unseen": 0.712, "flat_slip": 0.00012,
                    "flat_slip_source": "the median of its 95,012 recorded minutes"},
            "windows": {"1h": {"split": "Jul 24, 2026 8:00pm"}}, "skipped": {},
            "combos": {KEY15: {"older": _walk(_rows([0.05] * 40)), "unseen": _walk([]),
                               "random": [[0, 0.0]] * 200},
                       KEY: {"older": _walk(_rows([0.10] * 40)),
                             "unseen": _walk(_rows([1.2, -0.8] * 160)), "random": quiet}}}


def _plan():
    return {"version": vu.VERSION, "venue": "Gate", "start_ms": END - 365 * DAY, "end_ms": END}


def test_the_report_prints_coverage_first_then_every_verdict_with_the_kits_figures():
    lines, verdicts = vr.report([_record()], _plan(), 200, 1.0)
    text = "\n".join(lines)
    assert len(verdicts) == 30 and sum(v["passed"] for v in verdicts) == 1
    assert "70 combinations tried (14 family-setting-timeframes x 5 filter choices)" in lines[1]
    assert "$1.00 risk a trade" in lines[1]
    cover = next(k for k, ln in enumerate(lines) if ln.startswith("XAU_USDT (metals)"))
    first = next(k for k, ln in enumerate(lines) if ln.startswith("#"))
    assert cover < first, "COVERAGE FIRST"
    assert "71.2% of the unseen days'" in lines[cover] and "0.01200% a side" in lines[cover]
    snap = "\n".join(vr.verdict_lines(next(v for v in verdicts if v["passed"])))
    # 320 trades over the 90 unseen days, 160 won (+1.2) and 160 lost (-0.8): +$64.00
    assert f"#{vf.verdict_id('v3_snap', '1h', 'none')} v3_snap 1h none: setting k2 - PASSED" in snap
    assert "320 trades (3.56 a day), 160 won / 160 lost, 50.0%" in snap
    assert "(break-even 40.0%)" in snap, "0.8 / (1.2 + 0.8)"
    assert "PROFIT +$64.00, +$0.200 a trade" in snap
    assert "worst losing run -$0.80 over 1 trades" in snap
    assert "target: the 20-candle average, resting" in snap and "leverage 20x-20x" in snap
    assert "$45-$130 of coin a trade (2 over the books' $100)" in snap
    assert "exits at a typical cost 5 of 320" in snap and "1 of 30 verdicts passed." in text
    assert "refused signal candles: under one lot 0, no safe leverage 0, the cost check 0" in snap
    assert vr.CRASH_GUARD in text and vr.FEW_COINS in text and vu.SURVIVORSHIP in text


def test_a_chosen_setting_with_no_unseen_trade_says_so_in_one_line():
    rec = _record()
    rec["combos"][KEY]["unseen"] = _walk([])
    lines, verdicts = vr.report([rec], _plan(), 200, 1.0)
    snap = next(v for v in verdicts if (v["family"], v["tf"], v["filter"]) ==
                ("v3_snap", "1h", "none"))
    assert vr.verdict_lines(snap) == [
        f"#{snap['id']} v3_snap 1h none: setting k2 - FAILED at profit: no trade on the unseen "
        "days (older days: k1.5 +$0.050 a trade over 40, k2 +$0.100 a trade over 40)"]


def test_a_group_no_coin_measured_says_so_in_one_line():
    lines, verdicts = vr.report([_record()], _plan(), 200, 1.0)
    trend = next(v for v in verdicts if (v["family"], v["tf"], v["filter"]) ==
                 ("v3_trend", "1d", "none"))
    assert vr.verdict_lines(trend) == [
        f"#{trend['id']} v3_trend 1d none: FAILED at choose - no coin measured v3_trend on 1d "
        "(older days: n20 - a trade over 0 (too few), n50 - a trade over 0 (too few), n100 - a "
        "trade over 0 (too few))"]


def test_judge_pools_only_the_coins_measured_under_this_plan_and_names_the_rest(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(vr, "home", lambda label="local": tmp_path / label)
    vr.save_coin(tmp_path / "local", _record())
    vr.save_coin(tmp_path / "local", _record("OLD_USDT", end=END - DAY))
    vr.save_coin(tmp_path / "local", _record("BIG_USDT", risk=5.0))
    vr.save_coin(tmp_path / "local", {**_record("FEW_USDT"), "runs": 20})
    plan_path = vu.save(_plan(), tmp_path / "plan.json")
    assert vr.main(["judge", "--plan", str(plan_path)]) == 0
    out = capsys.readouterr().out
    # a coin measured at another risk is not the same trades, and runs of another count cannot
    # be pooled run by run: never pooled, always named
    assert ("left out, measured under another plan, at another risk than $1.00 or with other "
            "than 200 random runs: BIG_USDT, FEW_USDT, OLD_USDT") in out
    saved = json.loads((tmp_path / "local" / "verdicts.json").read_text(encoding="utf-8"))
    snap = next(v for v in saved if v["passed"])
    assert snap["coins"] == ["XAU_USDT"] and snap["unseen"]["trades"] == 320


def test_run_measures_each_coin_saves_it_and_prints_its_line(monkeypatch, tmp_path, capsys):
    from tradingagents import v3_measure

    asked = []

    def fake(sym, plan, *, runs, risk_usd, log=None):
        asked.append((sym, runs, risk_usd))
        return _record(sym, risk=risk_usd)

    monkeypatch.setattr(v3_measure, "measure_coin", fake)
    monkeypatch.setattr(vr, "home", lambda label="local": tmp_path / label)
    plan_path = vu.save(_plan(), tmp_path / "plan.json")
    assert vr.main(["run", "xau_usdt", "--plan", str(plan_path), "--runs", "3",
                    "--label", "t"]) == 0
    assert asked == [("XAU_USDT", 3, 1.0)], "the spec's $1 unless --risk says otherwise"
    assert vr.coin_file(tmp_path / "t", "XAU_USDT").exists()
    assert "XAU_USDT (metals): order books cover 0.0%" in capsys.readouterr().out


def test_plan_builds_the_universe_and_names_every_coin_it_skipped(monkeypatch, tmp_path, capsys):
    plan = {**_plan(), "start": "Oct 23, 2025 8:00pm", "end": "Oct 22, 2026 8:00pm",
            "months": ["2026-10"], "coins": ["BTC_USDT"], "liquid": {"2026-10": ["BTC_USDT"]},
            "calm": {"2026-10": []}, "skipped": {"BAD_USDT": "RuntimeError: no Day1 candles"}}
    monkeypatch.setattr(vu, "collect", lambda **k: plan)
    assert vr.main(["plan", "--out", str(tmp_path / "plan.json")]) == 0
    out = capsys.readouterr().out
    assert "1 skipped" in out and "skipped BAD_USDT: RuntimeError: no Day1 candles" in out
    assert vu.load(tmp_path / "plan.json")["coins"] == ["BTC_USDT"]


def test_a_coin_named_in_chinese_is_filed_under_plain_ascii(tmp_path):
    # the cost store's rule: "x" + the name's UTF-8 in hex
    assert vr.coin_file(tmp_path, "龙虾_USDT").name == "x" + "龙虾_USDT".encode().hex() + ".json.gz"
    assert vr.coin_file(tmp_path, "BTC_USDT").name == "BTC_USDT.json.gz"
    rec = vr.save_coin(tmp_path, {"coin": "龙虾_USDT", "combos": {}})
    assert vr.load_coins(tmp_path) == [{"coin": "龙虾_USDT", "combos": {}}] and rec.exists()


@pytest.mark.parametrize("family, key, words", [
    ("v3_trend", "n50", ("none; out on a close past its 50-day average",
                         "a trailing stop 3 x ATR(20), never loosened")),
    ("v3_strength", "k3", ("none; out at a Monday's close outside the top 6",
                           "a trailing stop 3 x ATR(20), never loosened")),
    ("v3_snap", "k1.5", ("the 20-candle average, resting; out after 24 candles",
                         "an emergency stop 3 x ATR(20) at the market"))])
def test_each_familys_target_and_stop_are_said_in_words(family, key, words):
    assert vr.exit_words(family, key) == words
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_v3_research.py -q`
Expected: `ImportError: cannot import name 'v3_research' from 'tradingagents'` (1 error during collection).

- [ ] **Step 3: Implement** — `tradingagents/v3_research.py`:

```python
"""BACKTEST V3 PART 2a ON THIS PC — build the universe plan, measure a few
coins end to end, print every verdict.

    .venv/Scripts/python -m tradingagents.v3_research plan
    .venv/Scripts/python -m tradingagents.v3_research run BTC_USDT ETH_USDT XAU_USDT --runs 20
    .venv/Scripts/python -m tradingagents.v3_research judge

Decisions doc: docs/superpowers/specs/2026-10-23-backtest-v3-part2-
decisions.md. A few coins is a CHECK of the machinery, never the proof: the
proof pools the whole universe on GitHub (Part 2b), and a check of 3 coins
will rarely reach the 300 unseen trades a verdict needs — it says so.

Reads the exchange; writes only the plan file (`v3_universe.PLAN_FILE`) and
its own folder in the v3 store (`stores.V3.home / "research" / <label>`, on
the store's drive); places no order, files nothing in a list, touches no
screen. Prints the order books' coverage of each coin FIRST (CLAUDE.md
"COVERAGE FIRST"), then the verdicts with the standard kit's figures.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import time
from pathlib import Path

from tradingagents import v3_families as vf, v3_proof as vp, v3_universe as vu

DEFAULT_LABEL = "local"
CRASH_GUARD = ("crash_guard (#8) is not tested yet: it needs open-interest history no "
               "reader serves yet (decisions doc).")
FEW_COINS = ("A few coins is a check of the machinery, never the proof: the proof pools the "
             "whole universe on GitHub (Part 2b).")


def home(label: str = DEFAULT_LABEL) -> Path:
    from tradingagents import stores

    return Path(stores.V3.home) / "research" / str(label)


def coin_file(root: Path, sym: str) -> Path:
    """The coin's file; a name the exchange gives in Chinese is written as
    plain ASCII (`x` + its UTF-8 in hex), as the cost store names it."""
    s = str(sym)
    if not s.isascii():
        s = "x" + s.encode("utf-8").hex()
    return Path(root) / f"{s}.json.gz"


def save_coin(root: Path, rec: dict) -> Path:
    p = coin_file(root, rec["coin"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(rec, fh, separators=(",", ":"))
    tmp.replace(p)
    return p


def load_coins(root: Path) -> list[dict]:
    out = []
    for p in sorted(Path(root).glob("*.json.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            out.append(json.load(fh))
    return out


def money(x: float | None, places: int = 2) -> str:
    if x is None:
        return "-"
    return f"{'-' if x < 0 else '+'}${abs(x):,.{places}f}"


def pct(x: float | None) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def exit_words(family: str, key: str) -> tuple[str, str]:
    """(the target rule, the stop rule) of a family's setting, in words."""
    v = float(key[1:])
    trail = "a trailing stop 3 x ATR(20), never loosened"
    if family == "v3_trend":
        return f"none; out on a close past its {v:g}-day average", trail
    if family == "v3_breakout":
        return "none", trail
    if family == "v3_strength":
        return f"none; out at a Monday's close outside the top {2 * v:g}", trail
    return ("the 20-candle average, resting; out after 24 candles",
            "an emergency stop 3 x ATR(20) at the market")


def coin_line(rec: dict) -> str:
    """One coin's COVERAGE FIRST line."""
    if rec.get("why"):
        return f"{rec['coin']}: {rec['why']}"
    pre = rec.get("pre") or {}
    skipped = "; ".join(f"{tf} skipped: {why}" for tf, why in rec.get("skipped", {}).items())
    return (f"{rec['coin']} ({rec['kind']}): order books cover {pct(pre.get('coverage_older'))} "
            f"of the older days' minutes and {pct(pre.get('coverage_unseen'))} of the unseen "
            f"days' (the rest pay its usual {100 * pre.get('flat_slip', 0):.5f}% a side: "
            f"{pre.get('flat_slip_source', '?')}); {len(rec.get('combos', {}))} combinations"
            + (f"; {skipped}" if skipped else ""))


def header_lines(plan: dict, runs: int, coins: int, risk: float) -> list[str]:
    from tradingagents.positions_view import fmt_when
    from tradingagents.v3_measure import UNSEEN_DAYS, windows

    start, split, end = windows(plan)
    return [f"Backtest v3 Part 2a on {plan.get('venue') or 'the exchange'}: {coins} coin(s); "
            f"the window {fmt_when(start / 1000)} to {fmt_when(end / 1000)} - older days to "
            f"{fmt_when(split / 1000)}, then {UNSEEN_DAYS} unseen days; {runs} random runs a "
            f"combination",
            f"{vp.TRIED} combinations tried ({vp.TRIED // len(vf.FILTERS)} family-setting-"
            f"timeframes x {len(vf.FILTERS)} filter choices), "
            f"alpha = 0.05 / {vp.TRIED}, z = {vp.Z:.3f}; ${risk:,.2f} risk a trade (margin = the "
            f"coin bought / its leverage)"]


def verdict_lines(v: dict) -> list[str]:
    """One verdict as the standard kit asks: id first, profit, target and stop
    rules, leverage, wins and losses, worst losing run, trades and a day."""
    from tradingagents.v3_measure import UNSEEN_DAYS

    head = f"#{v['id']} {v['family']} {v['tf']} {v['filter']}"
    older = ", ".join(f"{k} {money(o['per_trade'], 3)} a trade over {o['trades']}"
                      + ("" if o["eligible"] else " (too few)")
                      for k, o in v["older"].items())
    state = "PASSED" if v["passed"] else f"FAILED at {v['failed']}"
    if v["failed"] == "choose":
        return [f"{head}: {state} - {v['why']} (older days: {older or 'no trades'})"]
    s, r, b = v["unseen"], v["random"] or {}, v["bootstrap"]
    if not s["trades"]:
        return [f"{head}: setting {v['setting']} - {state}: no trade on the unseen days "
                f"(older days: {older})"]
    target, stop = exit_words(v["family"], v["setting"])
    c = v["counts"]
    lev = v["lev"] or ["-", "-"]
    notional = v["notional"] or [0.0, 0.0]
    return [
        f"{head}: setting {v['setting']} - {state} (older days: {older})",
        f"   unseen: {s['trades']} trades ({s['trades'] / UNSEEN_DAYS:.2f} a day), {s['wins']} "
        f"won / {s['losses']} lost, {pct(s['win_rate'])} (break-even {pct(s['break_even'])}), "
        f"PROFIT {money(s['profit'])}, {money(s['per_trade'], 3)} a trade; random runs: median "
        f"{money(r.get('median'), 3)}, bar {money(r.get('bar'), 3)} ({r.get('traded', 0)} of "
        f"{r.get('runs', 0)} traded); bootstrap low {money(b['low'], 3)} over {b['days']} days; "
        f"worst losing run {money(s['worst_run_usd'])} over {s['worst_run_trades']} trades",
        f"   target: {target}; stop: {stop}; leverage {lev[0]}x-{lev[1]}x; "
        f"${notional[0]:,.0f}-${notional[1]:,.0f} of coin a trade ({v['over_book']} over the "
        f"books' $100)",
        f"   counts: missed {c.get('missed', 0)} and post-only rejected "
        f"{c.get('post_only_reject', 0)} (their market twins {money(v['twins_pnl'])} over "
        f"{v['twins']}); exits at a typical cost {c.get('cost_unmeasured', 0)} of {s['trades']}; "
        f"funding estimated {c.get('funding_estimated', 0)}, unknown "
        f"{c.get('funding_unknown', 0)}; filter blocked {c.get('blocked', 0)} of "
        f"{c.get('signal_candles', 0)} signal candles; refused signal candles: under one lot "
        f"{c.get('too_small', 0)}, no safe leverage {c.get('unsafe_stop', 0)}, the cost check "
        f"{c.get('gate_blocked', 0)}; open at the end {s['open_at_end']}; coins {len(v['coins'])}"]


def report(records: list[dict], plan: dict, runs: int, risk: float) -> tuple[list[str], list[dict]]:
    """Every line the command prints, and the verdicts."""
    verdicts = vp.verdicts(records)
    lines = header_lines(plan, runs, len(records), risk)
    lines += [coin_line(r) for r in records]
    for v in verdicts:
        lines += verdict_lines(v)
    passed = sum(1 for v in verdicts if v["passed"])
    lines += [f"{passed} of {len(verdicts)} verdicts passed.", vu.SURVIVORSHIP, CRASH_GUARD,
              FEW_COINS]
    return lines, verdicts


def main(argv=None) -> int:
    import sys

    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_research",
                                description="Backtest v3 Part 2a on this PC.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan", help="build the universe plan from daily candles")
    pl.add_argument("--out", default=str(vu.PLAN_FILE))
    ru = sub.add_parser("run", help="measure coins end to end and print every verdict")
    ru.add_argument("coins", nargs="+")
    ru.add_argument("--plan", default=str(vu.PLAN_FILE))
    ru.add_argument("--runs", type=int, default=200)
    ru.add_argument("--risk", type=float, default=None, help="dollars a trade risks ($1)")
    ru.add_argument("--label", default=DEFAULT_LABEL)
    ju = sub.add_parser("judge", help="judge the coins already measured under a label")
    ju.add_argument("--plan", default=str(vu.PLAN_FILE))
    ju.add_argument("--runs", type=int, default=200)
    ju.add_argument("--risk", type=float, default=None, help="dollars a trade risks ($1)")
    ju.add_argument("--label", default=DEFAULT_LABEL)
    a = p.parse_args(argv)
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8")        # coin names in Chinese
    if a.cmd == "plan":
        t0 = time.time()
        plan = vu.collect(log=print)
        path = vu.save(plan, a.out)
        print(f"plan {path}: {plan['start']} to {plan['end']}, {len(plan['months'])} months, "
              f"{len(plan['coins'])} coins in a group; liquid {len(plan['liquid'][plan['months'][-1]])}"
              f" and calm {len(plan['calm'][plan['months'][-1]])} in {plan['months'][-1]}; "
              f"{len(plan['skipped'])} skipped ({time.time() - t0:.0f} s)")
        for sym, why in plan["skipped"].items():
            print(f"  skipped {sym}: {why}")
        return 0
    from tradingagents import v3_rules

    plan = vu.load(a.plan)
    root = home(a.label)
    risk = v3_rules.RISK_USD if a.risk is None else float(a.risk)
    if a.cmd == "run":
        from tradingagents.v3_measure import measure_coin

        for sym in a.coins:
            t0 = time.time()
            rec = measure_coin(sym.upper(), plan, runs=a.runs, risk_usd=risk, log=print)
            save_coin(root, rec)
            print(coin_line(rec) + f" ({time.time() - t0:.0f} s)")
    records, other = [], []
    for r in load_coins(root):
        same = (r.get("plan_end_ms") == int(plan["end_ms"])
                and float(r.get("risk_usd", v3_rules.RISK_USD)) == risk
                and int(r.get("runs") or 0) == a.runs)
        (records if same else other).append(r)
    lines, verdicts = report(records, plan, a.runs, risk)
    if other:
        lines.insert(2, f"left out, measured under another plan, at another risk than "
                        f"${risk:,.2f} or with other than {a.runs} random runs: "
                        + ", ".join(r["coin"] for r in other))
    root.mkdir(parents=True, exist_ok=True)
    (root / "verdicts.json").write_text(json.dumps(verdicts, default=str), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass, then lint**

Run: `.venv/Scripts/python -m pytest tests/test_v3_research.py tests/test_v3_proof.py tests/test_v3_measure.py -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_research.py tests/test_v3_research.py`
Expected: `35 passed`, then `All checks passed!`

- [ ] **Step 5: Build the first real plan, on Gate's data.** Read-only: it reads every crypto contract's daily candles (about 6 minutes) and writes `research/v3/plan.json` only.

```bash
TA_VENUE=gate .venv/Scripts/python -m tradingagents.v3_research plan
```

Expected: progress lines every 100 contracts, then one line `plan ...research\v3\plan.json: <start> to <end>, 13 months, <about 230> coins in a group; liquid 50 and calm <about 50> in <the last month>; <n> skipped (<about 350> s)`, and one `skipped SYM: why` line per contract it could not read. On Oct 23, 2026: 13 months, 233 coins in a group, liquid 50 and calm 50 in 2026-10, 0 skipped, 352 s. If anything is skipped, read why before going on.

- [ ] **Step 6: Run three coins end to end, on Gate's data.** Read-only on the exchange; it writes only under `~/.tradingagents/v3/research/local/` (the store's drive).

```bash
TA_VENUE=gate .venv/Scripts/python -m tradingagents.v3_research run BTC_USDT XAU_USDT ETH_USDT --runs 20
```

Expected: per coin, one line per timeframe (`  BTC_USDT 1h: measured (N s)`), then its coverage line (`BTC_USDT (crypto): order books cover 0.0% of the older days' minutes and <about 81>% of the unseen days' ...`); then the two header lines, the three coverage lines again, 30 verdicts each starting `#` and its id, `<k> of 30 verdicts passed.`, and the survivorship, crash_guard and "a few coins" lines. About a minute a coin. A 3-coin check rarely reaches 300 unseen trades, so expect 0 passed; a pass here is still a check of the machinery, never the proof. Confirm in the output that ETH's `v3_trend 1d` verdicts show most of their signal candles refused as "under one lot" (Review Focus 2). Paste the plan line (Step 5), the three coverage lines and the last five lines (Step 6) into the commit message, under its "The real runs" line.

- [ ] **Step 7: The harddev hunt:**
  - **Labels from data:** the risk, the run count, the combinations count and the venue in the header are read from the records, `v3_families` and the plan, never typed.
  - **Mixed records:** coins measured under another plan, risk or run count are left out and named.
  - **Where it writes:** `research/v3/plan.json` and `~/.tradingagents/v3/research/<label>/` only; nothing on the system drive, no job, no list. The tab's tested-ideas section reads `~/.tradingagents/v3/rows.db`, which this never creates, so it still (truthfully) says the GitHub test has not run.
  - **Dates:** every instant printed through `fmt_when`.

- [ ] **Step 8: Commit and push** (the plan file too: the decisions doc names it the run's plan file; Part 2b rebuilds it right before its run)

```bash
git status --short -- research/v3/plan.json
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_research.py tests/test_v3_research.py research/v3/plan.json
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
feat(v3): python -m tradingagents.v3_research - build the universe plan, measure a few coins end to end, print the books' coverage first and every verdict with the standard kit's figures; the first real plan committed

Backtest v3 Part 2a, Task 9. A few coins is a check of the machinery, never the proof (Part 2b pools the universe on GitHub).
- harddev: labels from data (risk, runs, combinations, venue), mixed records left out and named, writes only the plan file and the store's research folder, every date through fmt_when

The real runs, Gate, read-only:

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

### Task 10: Write the rules down

**Files:**
- Modify: `CLAUDE.md` (a new MANDATORY section directly after "## Backtest v3 — the engine's rules", before "## The daytime rule")
- Modify: `docs/superpowers/specs/2026-10-22-backtest-v3-design.md` (line 3, the status)

- [ ] **Step 1: Add the CLAUDE.md section.** Check `git diff HEAD -- CLAUDE.md` first: other sessions edit this file. Insert, after the Part 1 section's `Guards:` paragraph:

```markdown
## Backtest v3 Part 2a — the families and the proof test (MANDATORY — Oct 23, 2026)

The operator: *"go"* (Oct 23, 2026), to the Part 2 decisions made inside
the approved spec. Decisions:
`docs/superpowers/specs/2026-10-23-backtest-v3-part2-decisions.md`; plan:
`docs/superpowers/plans/2026-10-23-backtest-v3-part2a-families-and-proof.md`.

* **One universe for every machine: the plan file** (`v3_universe`,
  `research/v3/plan.json`), built from daily candles CLOSED before each
  instant they rank. Liquid = crypto, the top 50 by 30-day traded value
  (volume x TODAY's contract size x close) at each month start; calm =
  metals, indices and forex, plus the quietest third of that month's liquid
  by 60-day volatility; BTC's mood; the strength ranks of each Monday 00:00
  UTC. Only contracts the exchange trades today are candidates
  (survivorship, said on every verdict); a coin it cannot read is named in
  `skipped`.
* **The window is the plan's, never the clock**: the 365 days to the plan's
  end, the newest 90 unseen (`v3_measure.windows`). The older walk's
  candles end at the split and its minutes, order books and funding are CUT
  there (`_before`): a setting is never chosen on an unseen price, by
  construction. A signal on the last older candle trades in neither walk.
* **A signal's month is the month its order goes in** (the close of the
  signal candle): the universe, the sides, the filters and the random draws
  all read that minute.
* **Four families, settings fixed before any test** (`v3_families`): trend
  (n 20/50/100 days, 1d and 4h), breakout (N 20/50, 1d), strength (K 3/5,
  1d; forced out at a Monday's close outside the top 2K, `walk(forced=)`,
  `why` RANK), snap (k 1.5/2.0, 1h and 4h). Lead-in: 300 candles or the
  rule's own lookback. Four filters as masks on the signal (`v3_filters`):
  btc_mood, busy_hours, funding_side, funding_minutes; an order the history
  cannot judge passes and is counted. crash_guard is not built.
* **The luck bar** (`v3_random`): per combination and coin, 200 seeded runs
  on the unseen days, as many orders per month and side as the real run
  placed, on candles it could have entered on.
* **The proof** (`v3_proof`): choose on the older walks (30+ trades, ties to
  the simplest); judge the chosen setting pooled over every coin: profit a
  trade above 0, above the random runs' normal-fit (1 - α/2) point and their
  best, a day-clustered bootstrap's low end above 0, 300+ unseen trades;
  α = 0.05 / 70 (every combination measured, `len(combos())`), z = 3.384.
  Every verdict is kept with the step it failed.
* **$1 of risk decides which trades exist.** At Gate's lots a $1-risk trade
  of ETH, SOL or XRP on 1d is under one lot (Oct 23, 2026: 19 of October's
  50 liquid coins on 1d, 7 on 4h, 4 on 1h): skipped, counted `too_small`,
  printed on every verdict. `measure_coin(risk_usd=)` and `--risk` exist;
  records measured at another risk, plan or run count are never pooled.
* **The command is a check, not the proof**: `python -m
  tradingagents.v3_research plan | run COIN ... | judge` prints the books'
  coverage first, writes only the plan file and
  `stores.V3.home/research/<label>`, and runs no job in the v3 store.
  `cost_store.usual_slip` is each coin's own flat gap.

Guards: `tests/test_v3_universe.py`, `tests/test_v3_families.py`,
`tests/test_v3_filters.py`, `tests/test_v3_random.py`,
`tests/test_v3_proof.py`, `tests/test_v3_measure.py`,
`tests/test_v3_research.py`, and the forced exit and `contract_of` in
`tests/test_v3_engine.py`.
```

- [ ] **Step 2: Update the spec's status line.** On line 3 of `docs/superpowers/specs/2026-10-22-backtest-v3-design.md`, replace

```markdown
**Date:** Oct 22, 2026 · **Status:** approved Oct 22, 2026 ("ok go ahead"); Part 1, the engine, is built (plan docs/superpowers/plans/2026-10-22-backtest-v3-part1-engine.md)
```

with

```markdown
**Date:** Oct 22, 2026 · **Status:** approved Oct 22, 2026 ("ok go ahead"); Part 1, the engine, is built (plan docs/superpowers/plans/2026-10-22-backtest-v3-part1-engine.md); Part 2a, the families and the proof test on this PC, is built (plan docs/superpowers/plans/2026-10-23-backtest-v3-part2a-families-and-proof.md)
```

- [ ] **Step 3: Run every file this plan touched, once** (check first that no other pytest is running):

Run: `.venv/Scripts/python -m pytest tests/test_v3_universe.py tests/test_v3_families.py tests/test_v3_filters.py tests/test_v3_random.py tests/test_v3_proof.py tests/test_v3_measure.py tests/test_v3_research.py tests/test_v3_engine.py tests/test_v3_shared_rules_learn_the_waiting_order.py tests/test_v3_rules.py tests/test_v3_smoke.py tests/test_backtest_v3_tab.py tests/test_backtest_v3_store.py tests/test_cost_store.py tests/test_cost_coverage.py tests/test_one_door_to_the_exchange.py -q`
Expected: `216 passed`.

- [ ] **Step 4: Run the source-scanning guards** — no task's own tests read every module, and this plan adds seven:

Run: `.venv/Scripts/python -m pytest tests/test_the_backend_names_the_exchange.py "tests/test_auto_trader.py::test_nothing_is_defined_after_the_runner_entry_point" -q`, then `.venv/Scripts/python -m pytest tests/test_webapp.py -k "date_format_is_exactly or formats_a_timestamp_by_hand" -q`
Expected: the entry-point guard and both date guards pass. `test_no_printed_string_spells_mexc` fails before this plan on another session's `app_books.py:470`; check that its message names that line and nothing of this plan's files.

- [ ] **Step 5: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> CLAUDE.md docs/superpowers/specs/2026-10-22-backtest-v3-design.md
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message:

```text
docs(claude): Backtest v3 Part 2a's rules - one plan file for the universe, the plan's window never the clock, a signal's month is its order's, four families and four filters, the luck bar and the proof, and what $1 of risk leaves out

Backtest v3 Part 2a, Task 10. The spec's status line says Part 2a is built.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

---

## Notes for Part 2b (the GitHub half)

Measured or found while proving this plan; each is Part 2b's to act on.

- **Rebuild `research/v3/plan.json` right before the run and commit it**; every machine reads it from its checkout. 233 coins were in some group on Oct 23, 2026 (`plan["coins"]`): about 4 a machine on 60 machines.
- **Time and size a coin:** 148-194 s with 200 random runs on this PC (20-75 s of it the year of minutes), 72-90 KB compressed. A shard calls `measure_coin` per coin and returns the record; nothing is chosen on a machine.
- **COVERAGE FIRST is not met yet:** the cost store covered 0.0% of the older days and 70-81% of the unseen days (BTC, XAU, ETH). The spec's build order 0 (the order-book backfill over the window) comes first, or every verdict carries its typical-cost share (it does: "exits at a typical cost N of M").
- **Decide the research risk with the operator before the run:** at $1, Gate's lots remove ETH, SOL, XRP and 16 more of October's 50 liquid coins from the daily families (`too_small`), so the daily families would be judged on cheap-lot coins. `--risk` / `measure_coin(risk_usd=)` exist; the book readings are the cost of $100, so about $10 keeps a daily trade's size near them.
- **Random snap runs trade less than the real run** (XAU 1h: 15-26 trades a run against 98): a random long on a candle at or over its average has no target (`no_levels`), and one barely under it fails the cost check. The bar is noisier, which makes the test harder to pass, never easier.
- **`funding_minutes` blocks every 1d entry** (daily candles open at 00:00 UTC, a settlement on every cycle there) — as the decisions doc says; its five 1d verdicts fail at "choose".
- **Do not import `sweep_shard` with `RES="v3"`** (it exits); `measure_coin` needs only `fx`, `cost_store` (with `COST_REPOS` for every account) and `app_books`.
- **Ids:** verdicts carry `verdict_id` (family, timeframe, filter, `res="v3"`); per-coin rows for the tab need their own `row_code` with the setting and filter in `plan` (Part 1 final review, rec 2).
- **The v3 store fence stays:** this part runs no job with `stores.V3.env_for()`. A db_jobs kind for v3 needs the 16 `endswith("_v2")` gates and the `FINE_TF` readers checked first (listed beside `stores.V3`).
- **`cq_shard.usual_slip`** keeps its own copy of `cost_store.usual_slip`'s rule; a later change to one must change the other.
