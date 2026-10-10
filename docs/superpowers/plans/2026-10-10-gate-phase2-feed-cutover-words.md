# Gate phase 2 — the live feed, the cutover, and the words on screen

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The rooms practice-trade on Gate's live prices, the MEXC data is moved aside in one cutover, and nothing on the screen still says MEXC.

**Architecture:** `live_price.PriceFeed` keeps every rule it has (recorder, total, never before the order) and gains a PROTOCOL object per exchange (`MexcProtocol` unchanged in behaviour, `GateProtocol` new) that owns the address, the subscribe/ping messages and the parsing. The cutover (`tradingagents/venue_switch.py`) is one command that refuses while any job holds the store, closes each room's open practice trades at their own exchange's last price, switches every MEXC row off with a named reason, renames the exchange's data into `~/.tradingagents/archive-mexc-<date>/` and writes `venue.json`. The screen reads the exchange's name from `/api/venue`.

**Spec:** `docs/superpowers/specs/2026-10-10-switch-to-gate-design.md` (D7, D8, D13).

## Global Constraints

- Practice only. No real-money path is opened; real rows are never switched off by the cutover (none exist on Oct 10, 2026).
- Nothing is deleted: the cutover RENAMES on the same drive and prints every path it moved.
- Warn the operator before restarting the site (memory "warn before restarting"); batch restarts.
- Dates through `fmt_when` / `fmtWhen`.

## Review Focus

1. The cutover while a job or the API still holds `rows.db` → refuse by name, move nothing.
2. A room with an open practice trade on a coin Gate does not list → closed at MEXC's last price, never left open forever.
3. Gate's socket drops → reconnect resubscribes candles and tickers (RCA-2026-10-02-D's lesson).
4. A Gate candle push with `w: true` and the next bar's first push both arriving → one close, not two.
5. `/api/venue` unreadable → the screen says "exchange unknown", never "MEXC".

### Task 1: `GateProtocol` in the live feed

**Files:** Modify `tradingagents/live_price.py`; Test `tests/test_gate_live_feed.py`.

- [ ] Tests (recorded Gate messages, Oct 10, 2026): a `futures.trades` update records `(create_time_ms/1000, price)` per contract; a `futures.tickers` update records `last` at `time_ms`; a `futures.candlesticks` update for `15m_BTC_USDT` with `t` moving on closes the bar keyed `(BTC_USDT, "Min15")` (the runner's interval name); `1m` pushes feed `minute_bars`; subscribe messages carry `{"time", "channel", "event": "subscribe", "payload"}`; ping is `futures.ping`; `FEED` built for the venue at import picks Gate's URL when `venue.current()` is gate.
- [ ] Implement `MexcProtocol` (the existing code moved, byte-for-byte messages) and `GateProtocol`; `PriceFeed(protocol=...)`; MEXC suites stay green.

### Task 2: the runner's costs on Gate

**Files:** Modify `tradingagents/auto_trader.py` (`FEE_FALLBACK` per venue), `tradingagents/shared_market.py` (pause and board names per venue); Test `tests/test_gate_runner_costs.py`.

- [ ] Tests: under gate `taker_fee("BTC_USDT")` is Gate's spec 0.00075 (MEXC's 0.0008 floor was measured on MEXC fills); a spec of 0 falls back to 0.00075; under mexc unchanged; `edge_check` under gate reads Gate's book through the door.

### Task 3: the cutover

**Files:** Create `tradingagents/venue_switch.py`; Test `tests/test_venue_switch.py`.

- [ ] Tests (tmp home): refuses while `db_jobs.disk_holder()` names a job, or while the API/indexer pid files point at live processes; moves exactly the listed exchange data (folders `backtest`, `v2`, `parquet`, `parquet-v2`, `kline_cache`, `shared`, `replay`, `forecast_v2`, `rolling30`; files `book_readings.jsonl`, `room_forecasts.jsonl`, `daily_update.json`, `candle_autopilot.json`, `cloud_autopilot.json`, `pending_*.json`, `db_*` job files, `rows_index_asked.json`, `rows_rebuild.json`) and nothing else; a room's open practice trade gets an `exit` row with reason `venue_switch` at the price given; every practice row in every room is switched off and the deploy log says why; `venue.json` reads gate; a second run is a no-op that says so.

### Task 4: the words

**Files:** `tradingagents/api.py` (`GET /api/venue`), `webapp/src/lib/api.ts` (`useVenue`), every user-visible "MEXC" in `webapp/src`; Test `tests/test_the_screen_names_the_exchange.py`.

- [ ] Test: no `.tsx` renders the literal text MEXC outside a comment (AST-free: regex over JSX text and string literals, comments stripped); `/api/venue` answers `{"venue": "gate", "name": "Gate"}`.
