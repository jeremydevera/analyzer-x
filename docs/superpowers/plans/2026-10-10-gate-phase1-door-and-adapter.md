# Gate phase 1 — one door to the exchange, and the Gate adapter (public half)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every caller reaches the exchange through one door (`exchange as fx`) that hands each call to the venue's adapter, and a Gate adapter answers every PUBLIC question (coins, specs, prices, books, costs, candles, minutes, funding) in the shapes the app already reads.

**Architecture:** `venue.current()` names the exchange (env `TA_VENUE`, else `~/.tradingagents/venue.json`, else `mexc` until the cutover writes the file). `exchange.py` uses a module `__getattr__` so `fx.klines` resolves to the venue module's attribute at call time — tests that monkeypatch `mexc_futures` keep working. `gate_futures.py` mirrors `mexc_futures`' public surface; its HTTP goes through one `_fetch(url)` so tests stub one function.

**Tech Stack:** Python 3.13 stdlib (`urllib`, `gzip`, `csv`), pandas, numpy, pytest.

**Spec:** `docs/superpowers/specs/2026-10-10-switch-to-gate-design.md` (D1-D6, D10).

## Global Constraints

- Dates printed anywhere: `positions_view.fmt_when` only (CLAUDE.md "Date format").
- No unit test touches the network (conftest `_no_network`); Gate tests stub `gate_futures._fetch`.
- Anything big on disk goes under `~/.tradingagents` (the G: store), never `%TEMP%`.
- `if __name__ == "__main__":` is the last thing in any module.
- Commit with `python scripts/commit_own.py -F msg <paths>`; push `origin` and `colleague`.
- MEXC behaviour stays byte-for-byte: every existing test passes with `TA_VENUE=mexc`.
- Gate's REST serves at most 10,000 recent candles per bar size; never ask past it.

## Review Focus

1. A symbol Gate does not list (`GPNSTOCK_USDT`) → a named `VenueError`, never an empty frame or a 0.0 price.
2. A 429 from Gate → retried, and every other process on this PC pauses (`public_pause_gate.json`).
3. Candles asked deeper than REST serves → the archive months fill the front; a month not yet published leaves a gap the frame does not pretend to fill (no invented bars).
4. A minute series for v2 never holds two bars over the same instant (1m wins over 5m).
5. With no `venue.json`, the app stays MEXC — a restart before the cutover must not flip production.

---

### Task 1: `venue.py` — which exchange, and what a coin is

**Files:**
- Create: `tradingagents/venue.py`
- Modify: `tests/conftest.py` (autouse fixture pinning `TA_VENUE=mexc`)
- Test: `tests/test_gate_venue.py`

**Interfaces:**
- Produces: `venue.current() -> str` ("gate" | "mexc"); `venue.name() -> str` ("Gate" | "MEXC"); `venue.kind(symbol) -> str`; `venue.is_stock_like(symbol) -> bool`; `venue.stock_symbols() -> list[str]`; `venue.set_current(name)` (writes the file, used by the cutover only); `VENUE_FILE`.

- [ ] **Step 1: failing tests** — `current()` reads env first, then the file, then "mexc"; an unknown name raises; `kind()` under mexc keeps the STOCK-suffix rule; under gate it reads `contract_type` from `gate_futures.contract_types()` (stubbed); `is_stock_like` is `kind in ("stocks",)`.
- [ ] **Step 2: run, see them fail.**
- [ ] **Step 3: implement** (env `TA_VENUE`, file `~/.tradingagents/venue.json` `{"venue": "gate", "since": ts}`).
- [ ] **Step 4: conftest** — autouse `monkeypatch.setenv("TA_VENUE", "mexc")` so no test reads the operator's file.
- [ ] **Step 5: run** `pytest tests/test_gate_venue.py -q`; commit.

### Task 2: neutral errors and shared pieces

**Files:**
- Create: `tradingagents/dataflows/exchange_errors.py`, `tradingagents/dataflows/exchange_common.py`
- Modify: `tradingagents/dataflows/mexc_futures.py` (classes subclass the neutral ones; `chase_guard` and the book walk come from `exchange_common`; add `trading_symbols()`, `klines_page`)
- Test: `tests/test_gate_errors_and_common.py`

**Interfaces:**
- Produces: `VenueError`, `VenueThrottled`, `VenueAuthFailed`, `VenueEdgeBlocked`, `VenueForbidden`; `exchange_common.walk_fill(levels, want_contracts) -> (avg_px, got, exhausted)`; `exchange_common.book_cost_from(book, contract_size, notional, symbol) -> dict` (the exact dict `mexc_futures.book_cost` returns); `chase_guard`; `funding_summary_from(hist, symbol)`.

- [ ] Test: `issubclass(mexc_futures.MexcFuturesError, VenueError)` etc.; `book_cost_from` on a hand-made book equals what `mexc_futures.book_cost` returned for it before the refactor (frozen numbers in the test).
- [ ] Implement; MEXC's `book_cost` calls `book_cost_from` after its own retry-on-empty.
- [ ] Run the MEXC suites that touch these (`pytest tests -q -k "book_cost or chase or funding_summary"`); commit.

### Task 3: the door — `exchange.py`, and every import moved to it

**Files:**
- Create: `tradingagents/dataflows/exchange.py`
- Modify: every `from tradingagents.dataflows import mexc_futures as fx` in `tradingagents/`, `.github/scripts/`, `scripts/` (34 lines in 21 files); the five raw `fx._get_public(f"{fx.BASE}/api/v1/contract/detail")` readers become `fx.trading_symbols()`; `learn_verify` uses `fx.klines_page`; `sweep_orchestrator`'s reachability check asks `fx.HOST`.
- Test: `tests/test_one_door_to_the_exchange.py`

**Interfaces:**
- Produces: `exchange.adapter() -> module`; attribute access delegates at call time.

- [ ] Test: with `TA_VENUE=mexc`, `exchange.klines is mexc_futures.klines` after a monkeypatch of `mexc_futures.klines` (proves call-time delegation); with `TA_VENUE=gate`, `exchange.adapter() is gate_futures`; AST scan: no module under `tradingagents/` or `.github/scripts/` imports `mexc_futures` except `exchange.py`, `mexc_credentials.py`, `venue_switch.py`; no file builds `contract.mexc.com` or `api/v1/contract` outside `mexc_futures.py` and `live_price.py` (the socket moves in phase 4).
- [ ] Implement and move the imports (sed over the exact line, then read each diff).
- [ ] Full suite with `TA_VENUE=mexc`: same pass/fail set as before the change (baseline recorded first); commit.

### Task 4: `gate_futures.py` — HTTP core, contracts, prices, books, funding

**Files:**
- Create: `tradingagents/dataflows/gate_futures.py`
- Test: `tests/test_gate_futures_public.py`

**Interfaces:**
- Produces (same names and return shapes as `mexc_futures`): `BASE`, `HOST`, `_fetch(url) -> bytes`, `_get_public(url)`, `list_contracts()`, `trading_symbols()`, `contract_types() -> {symbol: kind}`, `contract_spec(symbol)` (MEXC field names), `clear_spec_cache()`, `last_prices()`, `last_price(symbol)`, `order_book(symbol)`, `book_cost(symbol, notional)`, `contracts_for`, `round_vol`, `liquidation_move_pct`, `chase_guard`, `funding_history(symbol)`, `funding_now(symbol)`, `funding_summary(symbol)`, `has_credentials()` (False until phase 6), error classes `GateFuturesError(VenueError)` and friends plus the neutral names.

- [ ] Tests against canned Gate bodies (the real shapes, recorded Oct 10, 2026): contract → spec mapping (`quanto_multiplier`→`contractSize`, `order_price_round`→`priceUnit`/`priceScale`, `maintenance_rate`, `taker_fee_rate`, `leverage_max`, `order_size_min/max`); tickers → `last_prices` keeps only > 0; `last_price` of an unknown contract raises `VenueError` naming it; order book `{"p","s"}` → `[[float, float]]`; `book_cost` walks asks with the contract size; funding pages back with `to=` until a short page; `funding_now.per_day = rate * 24 / cycle_h`; 429 retried then raised as `VenueThrottled` and the pause file written; 400 `CONTRACT_NOT_FOUND` not retried.
- [ ] Implement; commit.

### Task 5: Gate candles — REST pages, the archive, and the v2 minutes

**Files:**
- Modify: `tradingagents/dataflows/gate_futures.py`
- Test: `tests/test_gate_futures_candles.py`

**Interfaces:**
- Produces: `klines(symbol, interval="Min5", limit=300)`, `klines_page(symbol, interval, limit, end)`, `klines_backfill(symbol, interval, want)`, `clear_kline_cache(disk=True)`, `KLINE_DISK_DIR` (`~/.tradingagents/kline_cache/gate`), `_KLINE_CACHE`, `_KLINE_PAGE = 2000`, `REST_POINTS = 10_000`, `archive_month(symbol, kind, yyyymm) -> DataFrame | None` (`kind` in `1m`,`5m`,`1h`,`4h`,`1d`), `minutes(symbol, start_s, end_s) -> DataFrame` (1m where it exists, 5m bars only where no minute covers them).

- [ ] Tests: `klines(limit=300)` = one REST call translated (`Min60`→`1h`); `limit > 2000` pages back with `to=`; a request deeper than 10,000 points takes the front from `archive_month` (15m/30m resampled from 5m: open first, high max, low min, close last, volume sum) and never calls REST past the cap; a 404 month is skipped, not fatal; `minutes()` merges archive 1m + REST 5m + REST 1m with no overlapping instants and sorted times.
- [ ] Implement; commit.

### Task 6: what a coin is, everywhere

**Files:**
- Modify: `tradingagents/daytime_rule.py:is_stock`, `tradingagents/room_stats.py:is_stock`, `tradingagents/rows_index.py:_where` (asset), `tradingagents/venues.py` (the "only here, not on OKX" list)
- Test: `tests/test_gate_coin_kinds.py`

- [ ] Tests: under gate, `daytime_rule.is_stock("AAPL_USDT")` is True from the venue's list and `"BTC_USDT"` False; `rows_index._where(asset="stocks")` → `+coin IN (...)` of the venue's stock list; under mexc, both unchanged (`%STOCK`).
- [ ] Implement; commit.

### Task 7: ids and stores never mix exchanges

**Files:**
- Modify: `tradingagents/backtest_report.py:row_code` (venue appended when not mexc), `tradingagents/cloud_sweep.py:land_rows` (refuse a row whose `venue` is not `venue.current()`), `.github/scripts/sweep_shard.py` (stamp `venue` on every row and `pair_done`)
- Test: `tests/test_gate_ids_and_landing.py`

- [ ] Tests: `row_code(...)` under mexc unchanged (`#LG9NSU4B` fixed point); under gate differs; `land_rows` with venue mexc refuses a `venue: "gate"` row naming both, and accepts a row with no venue only under mexc (old shards).
- [ ] Implement; commit; push both remotes.
