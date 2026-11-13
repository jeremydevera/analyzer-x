# Real prices for skill trades — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every entry and exit of a skill trade is priced from the app's own recorded order book of its own minute, by one function used by the nightly backtest and the rooms' follower; every figure says what share of its trades paid a real price.

**Architecture:** `skill_bt.Book` holds a coin's recorded readings and answers "what does $100 really get at this minute"; `skill_bt.step(book=)` asks it for every fill and marks each trade 0 / 1 / 2 fills real. The nightly shard hands it the PUBLISHED readings, the follower this PC's own recording (waiting for a reading still on its way). The store keeps the mark per trade; Forecast v4 adds each rule set's result over real-priced trades alone.

**Tech Stack:** Python 3 (numpy, sqlite3, pytest), Next.js / TypeScript for the three pages.

**Spec:** `docs/superpowers/specs/2026-11-13-real-prices-for-skill-trades-design.md`

## Global Constraints

- A real price is a reading the app itself recorded: `source == book_history.SOURCES["app"]`, stamped at exactly the fill's minute, `exhausted` false. Nothing else (never the exchange's published books).
- Real prices begin `REAL_FROM_S` = Oct 17, 2026 00:00 UTC, and reach back no further than the minutes do (`fine_from_ms`, `MINUTE_DAYS` = 120).
- `book=None` is byte for byte the rule of before: no new key on a position or a trade.
- No reading at a fill's minute: the price of today (last price or barrier, worsened by the usual gap), that fill ESTIMATED. A trade is never dropped for it.
- One function prices both sides (`skill_bt.step`); the follower and the backtest never carry a second rule.
- A trade's mark is how many of its two fills were real: 2 real, 1 part, 0 estimated. "Real-priced" in every count means 2.
- No order is placed; no signal, stop, target, rule set, picker test or room changes.
- Every date printed is `fmt_when` / `fmtWhen`; every word on a page is plain (no "ledger", "book" alone, "TP/SL" unexplained).
- Commit with `.venv/Scripts/python scripts/commit_own.py -F <msg file> <paths>`; push `origin`, `colleague`, `teammate`; never commit `docs/OPERATOR-ASKS.md`.

## Builder's calls (not in the spec's words)

- A SELL fills at `mid / (1 + sell)` and a BUY at `mid x (1 + buy)`: the reading's own definition of its $100 walk (`book_history._sample`), so the fill IS the average price of the walk. The spec's `mid x (1 - sell)` differs by `sell^2`.
- A STOP the price had already jumped past fills from where the price was: a long's stop at `min(barrier, mid)`, a short's at `max(barrier, mid)`, then that minute's walk (Backtest v3's rule; never flatters). A target keeps its barrier.
- The wait for yesterday's published readings is made by `v4_daily` before it dispatches (this PC is the publisher and holds the marker), not by 60 machines polling.
- The follower gets a second pass 6 minutes after a close when something waited for a reading (the recorder writes every 5), so a fill is written about 6 minutes after its candle, not 15.

## Review Focus

1. A reading whose `bid`/`ask` is zero, NaN or crossed in a recorded file: the fill must be an estimate, never a price of 0 or infinity. (Task 1)
2. The follower asked for a fill whose reading is not on disk yet: nothing is written and no state moves; after 10 minutes it is written as an estimate and counted. (Task 3)
3. A store built before this change (no `real` column): Backtest v4's list, a trade list and Forecast v4's build all still answer, every trade read as estimated. (Tasks 4, 5)
4. A collected line from a machine still on the old code (5- or 6-item trades): filed as estimated, never an IndexError. (Task 4)
5. A rule set with no real-priced trade: its real-priced figure is blank (never $0.00 shown as a result), it fails "made money at real prices", and sorts last. (Task 5)

---

### Task 1: The price rule in the engine

**Files:**
- Modify: `tradingagents/skill_bt.py` (new `REAL_FROM_S`, `BookNotYet`, `Book`, `read_book`; `close_position`, `step`, `run`, `walk`, `measure`, `daily_line` take `book=`)
- Test: `tests/test_skill_real_prices.py` (new)

**Interfaces — Produces:**
- `REAL_FROM_S: int` = `calendar.timegm((2026, 10, 17, 0, 0, 0))`
- `class BookNotYet(Exception)` — `.minute_ms`
- `class Book(packed: dict | None, *, now_ms: int | None = None, wait_ms: int = 0)` — keeps only app-source, not-exhausted readings with finite `0 < bid < ask` and finite `buy, sell >= 0`. `Book.at(minute_ms) -> (mid, buy, sell) | None`; `Book.fill(minute_ms, buying: bool, *, barrier: float | None = None, stop: bool = False) -> float | None` (raises `BookNotYet` when there is no reading and `now_ms - minute_ms < wait_ms`); `Book.minutes -> int`.
- `read_book(sym, from_s, to_s, *, published_only=True, reader=None, now_ms=None, wait_ms=0) -> Book` (`reader` defaults to `app_books.book_for`; an empty Book while `app_books.IN_BACKTEST` is off or `to_s <= REAL_FROM_S`; `from_s` raised to `REAL_FROM_S`).
- `step(..., book: Book | None = None)`: an opened position carries `"real": bool` and a closed trade `"real": 0|1|2` ONLY when `book` is given. `run`, `walk`, `measure`, `daily_line` pass `book` through.
- `measure` trade item with a book: `[entry_ms, exit_ms, side, why, pnl, at_or_None, real]` (7 items, always); without one, as before.
- `daily_line(..., book=)` adds `"book": {"minutes": book.minutes, "from_s": REAL_FROM_S}` when a book is given.

- [ ] **Step 1: Write the failing tests** in `tests/test_skill_real_prices.py` (1h candles on one timeline, readings stamped at minute starts in seconds; helper `_book({minute_s: (bid, ask, buy, sell)})`):

```python
def test_an_entry_fills_at_the_recorded_walk_not_the_last_price():
    # CATL's shape: last price 49.34, bid 48.97 / ask 49.23, buy walk 1.32% above the 49.10 middle
    assert pos["px"] == pytest.approx(49.10 * (1 + 0.0132)) and pos["real"] is True

def test_no_reading_at_the_minute_is_todays_price_marked_estimated():
    assert pos["px"] == pytest.approx(49.34 * (1 + SLIP)) and pos["real"] is False

def test_without_a_book_nothing_is_added():           # byte for byte
    assert "real" not in pos and "real" not in trade

def test_a_signal_exit_sells_at_the_recorded_walk():
    assert trade["exit_px"] == pytest.approx(mid / (1 + sell)) and trade["real"] == 2

def test_a_stop_by_the_minute_keeps_its_barrier_and_pays_that_minutes_walk():
    assert trade["exit_px"] == pytest.approx(sl_px / (1 + sell_at_minute))

def test_a_stop_the_price_jumped_past_fills_from_where_the_price_was():
    assert trade["exit_px"] == pytest.approx(mid_below_barrier / (1 + sell))

def test_the_stop_is_measured_from_the_price_really_paid():
    # real entry 49.88, stop 1.5% = 49.13: a minute low of 49.12 stops it; from 49.34 it would not
    assert trade["why"] == "SL"

def test_one_fill_real_is_marked_part():               # real == 1
def test_a_reading_that_ran_out_or_is_not_the_apps_is_not_a_price():   # exhausted / source 1 / bid 0 / NaN / crossed
def test_a_reading_on_its_way_raises_and_changes_nothing():            # BookNotYet; pos object untouched
def test_after_the_wait_the_fill_is_an_estimate():
def test_measure_writes_seven_items_with_a_book_and_the_old_shape_without():
def test_read_book_never_reads_before_the_record_began():              # reader asked from REAL_FROM_S
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_skill_real_prices.py -q` — expected: fail (`Book` not defined).
- [ ] **Step 3: Implement** in `tradingagents/skill_bt.py`. `Book` keeps sorted `t` (seconds) and looks a minute up with `searchsorted` for an exact match on `minute_ms // 1000`. In `step`: the minute-settled exit asks `fill(minute, buying=side == -1, barrier=barrier, stop=why == "SL")`; a close-priced exit and an entry ask `fill(when_ms + bar_ms, buying=...)`; `close_position(..., real: int | None = None)` writes the mark. The END close in `walk` stays an estimate (mark = the entry's).
- [ ] **Step 4: Run** the new file plus `tests/test_skill_engine_steps.py tests/test_skill_exits_by_the_minute.py tests/test_skill_bt.py tests/test_skill_ta.py` — expected: pass.
- [ ] **Step 5: Commit** (`feat(skill engine): a fill pays the recorded order book of its own minute`).

### Task 2: The nightly run reads the published readings

**Files:**
- Modify: `.github/scripts/skill_shard.py` (daily set: `book = sb.read_book(sym, today_s - sb.MINUTE_DAYS * 86400, now_s)` once a coin, passed to `daily_line`)
- Modify: `tradingagents/v4_daily.py` (`BOOKS_WAIT_S = 30 * 60`; `_books_ready(st, now) -> bool` called first in `_dispatch`; `_notes` says a late day; `_agree` checks the day before yesterday again)
- Test: `tests/test_v4_daily_shard.py`, `tests/test_v4_daily.py` (add)

**Interfaces — Consumes:** Task 1's `read_book`, `daily_line(book=)`. **Produces:** `st["books"] = {"day": "YYYYMMDD", "published": bool, "waited_until_s": float}`; an agreement file re-written for the day before yesterday carries `"rechecked_s"`.

- [ ] **Step 1: Failing tests**

```python
def test_the_daily_shard_hands_the_coins_readings_to_the_line()      # daily_line called with a Book; line["book"]["minutes"]
def test_dispatch_waits_for_yesterdays_readings_to_be_published()     # before 00:50 UTC, marker empty: phase stays "dispatch", why names the wait, nothing dispatched
def test_dispatch_goes_on_once_they_are_published()
def test_after_the_wait_it_goes_on_and_says_the_day_was_not_published()   # st["books"]["published"] is False; _notes names it
def test_a_manual_start_late_in_the_day_does_not_wait()               # now past the bound
def test_the_day_before_yesterday_is_checked_again()                   # its agree file rewritten with rechecked_s
```

- [ ] **Step 2: Run** them — expected: fail.
- [ ] **Step 3: Implement.** `_books_ready`: yesterday = `app_books._day(day_s - 1)`; published when `app_books._marker_of(yesterday).get("coins")`; the bound is `day_s + app_books.PUBLISH_AFTER_UTC_S + BOOKS_WAIT_S`; a PC with no recorder folder (`app_books.HOME` missing) never waits. `_agree`: `days` also holds `y - DAY_S` when its file exists.
- [ ] **Step 4: Run** `tests/test_v4_daily_shard.py tests/test_v4_daily.py tests/test_ci_scripts_use_names_that_exist.py` — expected: pass.
- [ ] **Step 5: Commit** (`feat(v4 daily): the nightly run prices from the published readings, and waits for yesterday's`).

### Task 3: The follower prices from this PC's recording

**Files:**
- Modify: `tradingagents/v4_follow.py` (`BOOK_WAIT_S = 600`, `RETRY_AFTER_S = 360`; `_Reads.book(sym, from_ms)`; `_warm`, `_advance`, `_delist` pass it; `_Writer` writes the marks and counts fills; `status()` returns `fills`; `_tick` runs one more pass `RETRY_AFTER_S` after a slot whose pass waited)
- Modify: `tradingagents/api.py` (`trade_v4_follow` returns `fills`)
- Test: `tests/test_v4_follow.py` (add)

**Interfaces — Consumes:** `sb.read_book(sym, from_s, to_s, published_only=False, now_ms=, wait_ms=)`, `sb.BookNotYet`, `step(book=)`. **Produces:** `pass_once(..., books=None)` (`books(sym, start_s, end_s) -> packed`, default `app_books.book_for(..., published_only=False)`); enter row `"real": bool`; exit row `"real": 0|1|2`; state `st["fills"] = {"real": n, "est": n, "since_s": first}`; a room's pass result `"waiting": n`; `status()["fills"]`.

- [ ] **Step 1: Failing tests**

```python
def test_follower_and_engine_write_the_same_trade_to_the_cent_with_the_same_readings(world)
def test_an_entry_row_carries_the_real_price_and_says_so(world)          # row["entry"] == the walk price; row["real"] is True
def test_a_fill_whose_reading_is_not_recorded_yet_waits_and_writes_nothing(world)   # no row, last_ms unchanged, out["waiting"] == 1
def test_ten_minutes_later_it_is_written_as_an_estimate_and_counted(world)          # row["real"] is False; fills["est"] == 1
def test_a_trade_open_before_this_keeps_its_entry_and_its_exit_is_part(world)       # pos without "real": exit row real in (0, 1)
def test_a_pass_that_waited_is_tried_again_six_minutes_after_the_close(world, monkeypatch)
def test_a_warm_up_waiting_for_a_reading_is_not_an_error(world)
```

- [ ] **Step 2: Run** — expected: fail.
- [ ] **Step 3: Implement.** `_Reads.book` mirrors `_Reads.fine` (one read a coin a pass, again only to reach further back; from `max(sb.REAL_FROM_S, from)` to now). `_advance` and `_warm` catch `sb.BookNotYet`: count it, leave the strategy where it was. `_delist` stays an estimate. The fills counter moves only when a row is really written (`_put` returned True).
- [ ] **Step 4: Run** `tests/test_v4_follow.py tests/test_skill_rooms_screen.py tests/test_v4_rooms.py` — expected: pass.
- [ ] **Step 5: Commit** (`feat(skill rooms): practice fills at this PC's recorded order book`).

### Task 4: The store keeps each trade's mark

**Files:**
- Modify: `tradingagents/v4_store.py` (schema: `trade.real INTEGER NOT NULL DEFAULT 0`; `strat.real_trades`, `real_wins`, `real_profit`; `STRAT_COLS = 38`; `build` reads item 6; `meta["real"]`; `trade_log` returns `priced` per trade and the three counts)
- Test: `tests/test_backtest_v4_store.py`, `tests/test_v4_store_daily.py` (add)

**Interfaces — Produces:** `meta["real"] = {"from_s": REAL_FROM_S, "trades": n, "real": n2, "part": n1, "trades_30d": .., "real_30d": .., "part_30d": ..}` (END trades left out; 30 days back from `data_end_s`, by the day a trade CLOSED); `trade_log()["log"][i]["priced"] in ("real", "part", "estimated")`; `trade_log()["priced"] = {"real": n, "part": n, "estimated": n}`.

- [ ] **Step 1: Failing tests**

```python
def test_a_seven_item_trade_files_its_mark_and_the_row_counts_its_real_trades()
def test_a_five_or_six_item_trade_is_filed_as_estimated()
def test_meta_says_the_share_that_paid_a_real_price_over_30_days_and_over_everything()
def test_the_trade_list_marks_each_trade_real_part_or_estimated()
def test_a_store_without_the_column_still_lists_its_trades_as_estimated()
```

- [ ] **Step 2: Run** — expected: fail. **Step 3: Implement.** **Step 4: Run** both files plus `tests/test_backtest_v4_tab.py` — pass.
- [ ] **Step 5: Commit** (`feat(backtest v4): each trade says whether it paid the recorded order book`).

### Task 5: Forecast v4 shows each rule set at real prices

**Files:**
- Modify: `tradingagents/forecast_v4.py` (`_load` reads `real`; `_walk` carries it; `_figures` adds `real_trades`, `real_wins`, `real_profit`, `real_per_trade`; `RULE_SORTS += ("real_profit", "real_per_trade")`; `MONEY += ("real_profit", "real_per_trade")`; `rules_page` filter `real_made`; `summary()` carries `real`)
- Modify: `tradingagents/api.py` (`/api/forecast-v4/rules` takes `real_made`)
- Test: `tests/test_forecast_v4.py` (add)

**Interfaces — Produces:** each rule: `real_trades: int`, `real_wins: int`, `real_profit: float | None`, `real_per_trade: float | None` (None when it has no real-priced trade); `rules_page({"real_made": "1"})`; `summary()["real"]` = the store's `meta["real"]`.

- [ ] **Step 1: Failing tests**

```python
def test_a_rule_sets_real_priced_figure_counts_only_trades_with_both_fills_real()
def test_no_real_priced_trade_is_blank_never_zero_and_fails_made_money_at_real_prices()
def test_sorting_by_real_prices_puts_rule_sets_with_none_last()
def test_the_real_priced_dollars_scale_with_the_base_margin()
def test_a_store_without_the_mark_builds_with_every_figure_blank()
def test_the_default_order_is_unchanged()
```

- [ ] **Step 2–4:** fail, implement, run `tests/test_forecast_v4.py tests/test_forecast_v4_calendar.py tests/test_forecast_v4_cheap_coins.py tests/test_v4_picker.py tests/test_v4_picker_lab.py tests/test_v4_picker_rooms.py` — pass.
- [ ] **Step 5: Commit** (`feat(forecast v4): every rule set's result over its real-priced trades`).

### Task 6: The pages say it

**Files:**
- Modify: `webapp/src/components/backtest-v4/V4Strategies.tsx` (header line from `meta.real`; a "Price" cell in the trade list: real / part / estimated)
- Modify: `webapp/src/components/forecast/ForecastV4.tsx` (column "At real prices": profit and trades; sort options; box "made money at real prices"; one line saying real prices begin Oct 17, 2026 and what share of the walked trades paid them)
- Modify: `webapp/src/components/trade/V4FollowPanel.tsx` (the fills line)
- Modify: `webapp/src/lib/api.ts` (types)
- Test: `tests/test_backtest_v4_tab.py`, `tests/test_forecast_v4.py`, `tests/test_skill_rooms_screen.py` (page-text assertions)

- [ ] **Step 1: Failing tests** (each asserts the words and the field read, never a literal count):

```python
def test_backtest_v4_prints_the_share_that_paid_the_recorded_order_book()   # reads m.real.real_30d / trades_30d
def test_the_trade_list_has_a_price_column()                                 # t.priced
def test_forecast_v4_has_the_real_prices_column_sort_and_box()               # real_profit, real_made
def test_the_room_panel_counts_its_estimated_fills()                         # fills.est
```

- [ ] **Step 2–4:** fail, implement, run the three test files, `npx tsc --noEmit` in `webapp` — pass.
- [ ] **Step 5: Commit** (`feat(pages): Backtest v4, Forecast v4 and the rooms say which trades paid a real price`).

### Task 7: Prove it on the real store, document, ship

- [ ] **Step 1:** On this PC, one real coin through the engine with its published readings (CATL 1h, the 42 settings): every fill marked real is re-priced by an independent lookup of the recording — difference 0; the Nov 11, 2026 7:00am CATL buy fills at the walk price. Paste the numbers.
- [ ] **Step 2:** One follower pass on a copy of a room's folder with the real recordings: its rows carry the marks; nothing else in the room moves.
- [ ] **Step 3:** `CLAUDE.md`: a section "Skill trades pay the recorded order book"; the "Costs NOT charged" bullet of Skill rooms rewritten; `memory/skill-rule-profits-are-a-price-error.md` updated.
- [ ] **Step 4:** Full related suite (one run): every test file named above. Then a fresh reviewer over the whole change; fix what it finds.
- [ ] **Step 5:** Commit, push to `origin`, `colleague`, `teammate` (before the 00:05 UTC chain), restart the site (`.venv/Scripts/python start.py start`), confirm the three pages render.
