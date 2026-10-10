# Switch the whole app from MEXC to Gate — design

Date: Oct 10, 2026. Status: written for the build; decisions below were taken
without stopping to ask, on the operator's standing word (`/goal`, and
*"when the operator picks an offered option, build it"*). Every decision is
numbered so it can be overruled by number.

## What they asked, word for word

> okay switch to gate from now on, this means every logic in my app will be
> gate instead of mexc, like the backtest, the coins, downloading candles,
> updating the backtest to have cost using 1 min candle, the forecast room,
> everything, use appropirate superpower when working this

The asks that led here, Oct 09-10, 2026: *"can the backtest use other api to
know their past cost like okx?"*, *"in mexc there are lots of coin, what
platform can i use that has many coins and i can pull up past cost?"*, *"so
for rate limit which is better mexc or gate?"*. Behind all of them is the
month-long goal: *"my goal is to align it with practice so I know exactly how
much will i earn"*.

## What Gate is — measured, not assumed (Oct 10, 2026)

| fact | measured |
|---|---|
| USDT perpetual contracts | **1,027**, all `trading`; `contract_type`: 588 crypto, 402 `stocks`, 18 `indices`, 12 `metals`, 4 `forex`, 3 `commodities` |
| names | `BTC_USDT` like MEXC; stocks by ticker (`AAPL_USDT`), never `AAPLSTOCK_USDT` |
| fees | taker **0.075%**, maker **−0.01%** on every contract (MEXC's code floors taker at 0.02%) |
| funding cycle | 613 contracts 8 h, 410 contracts 4 h, 4 contracts 1 h |
| keyless rate limit | 200 asks / 10 s **per endpoint**, counted per IP (header `X-Gate-RateLimit-*`) |
| orders | 100 / s per account; cut to 10 per 10 s for an hour after 24 h with no fills |
| candles over REST | at most **10,000 recent points per bar size**: 1m = 6.9 days, 5m = 34.7 days, 15m = 104 days, 1h = 416 days, 4h = 4.5 years, 1d = all |
| minute archive | `download.gatedata.org/futures_usdt/candlesticks_1m/YYYYMM/<C>-YYYYMM.csv.gz`, one file per COMPLETED month (Sep 2026 published Oct 01 2:08am UTC), columns `t,v,c,h,l,o` |
| order-book archive | `.../orderbooks/YYYYMM/<C>-YYYYMMDDHH.csv.gz`, one file per hour, published ~2 h after: a full snapshot (`set`) then every change merged per 100 ms (`make`/`take`) |
| order-book replay | positive size = buy side, negative = sell side; **`make` adds the size, `take` subtracts it**. Replaying BTC Oct 09 00:00-01:00 that way reproduced the 01:00 snapshot on **41,387 of 41,387** price levels; reading the size as the new amount matched 221 of 4,909 |
| order-book gaps | Sep 30 – Oct 08 12:00: snapshot-only files (~180 KB an hour for BTC, against 20-50 MB on full days) |
| archive size | 0.84 MB per coin-hour on average (80 coins sampled): **~21 GB a day** for all 1,027 |
| GitHub machines | both accounts reach REST, the archive (23 MB in 0.28 s) and the websocket host (`101 Switching Protocols`), run 38030471652 / 38030473605 |
| this PC's busiest moment | Oct 10, 2026 2:00am: 26 candle asks in 2 s, 72 in 10 s (MEXC allows 20 per 2 s and said "too many requests" at 2:04am) |
| real money today | **no room has a real-money row**; every one of the 3,148 switched-on rows is practice |

## Decisions

**D1 — One switch, one name.** `tradingagents/venue.py` answers which exchange
the app trades: `TA_VENUE` in the environment, else `~/.tradingagents/venue.json`,
else **gate**. Nothing else in the app reads an exchange name from anywhere.

**D2 — One door to the exchange.** `tradingagents/dataflows/exchange.py` is the
module every caller imports as `fx`. It hands every attribute to the venue's
adapter (`gate_futures` or `mexc_futures`) at CALL time, so a test that
monkeypatches `mexc_futures` still reaches the code under test. Every
`from tradingagents.dataflows import mexc_futures as fx` in the app and the
GitHub scripts becomes `exchange as fx`.

**D3 — Errors carry a neutral name.** `exchange_errors.py` holds `VenueError`,
`VenueThrottled`, `VenueAuthFailed`, `VenueEdgeBlocked`, `VenueForbidden`.
MEXC's classes subclass them (their names and behaviour unchanged); Gate's
classes subclass them too; callers catch the neutral names.

**D4 — The Gate adapter answers in the shapes the app already reads.**
`gate_futures.contract_spec` returns `contractSize` (Gate's
`quanto_multiplier`), `minVol`, `maxVol`, `volUnit`, `priceUnit`,
`priceScale`, `maintenanceMarginRate`, `takerFeeRate`, `makerFeeRate`,
`maxLeverage`, `symbol` — the fields the runner reads — plus Gate's own
(`contract_type`, `funding_interval`). Candles come back as the same
`Date/Open/High/Low/Close/Volume` frame; intervals keep MEXC's names
(`Min1`..`Day1`) at the door and are translated inside. Volume is Gate's `v`
(contracts), the unit MEXC's `vol` was.

**D5 — What a coin IS comes from the venue's list, never from its name.**
`venue.kind(symbol)` → crypto / stocks / indices / metals / forex /
commodities, from Gate's `contract_type`. Every place that tested the
`STOCK` suffix (the daytime rule, the crypto/stocks filter, the coin lists)
asks `kind()` instead. Under MEXC `kind()` keeps the suffix rule.

**D6 — Ids never collide across exchanges.** `backtest_report.row_code` hashes
the venue for anything that is not MEXC (the way `res="1m"` keeps v2 ids apart
from v1). Every existing MEXC id is unchanged (`#LG9NSU4B` stays a fixed point).

**D7 — The cutover MOVES the MEXC data aside; it deletes nothing.** One script
(`tradingagents/venue_switch.py`) stops the jobs, then renames every
exchange-specific folder and file into `~/.tradingagents/archive-mexc-<date>/`
(same drive: a rename, seconds, no copy) and writes `venue.json = gate`. Gate's
data then fills the same places, so not one path constant in ~40 modules has
to learn about exchanges. App-level things stay where they are: rooms and
their trade records, the deploy log, notifications, credentials, error issues,
runtime recipes. Moving the folder back and writing `mexc` reverses it.

**D8 — Rooms start clean on Gate, practice only.** At the cutover each room's
open practice trades on MEXC are closed at MEXC's last price (reason
`venue_switch`, written to the room's trade record), and every MEXC row is
switched off with that reason in the deploy log — the rows were measured on
another exchange's candles and costs. Each room's watcher then switches on Gate
rows from the Gate backtest by its own unchanged rules. No real money is
involved (D-fact above); real-money boxes stay as they are.

**D9 — GitHub runs Gate.** Every workflow sets `TA_VENUE: gate` in its `env`
(no new input: `sweep.yml` is at GitHub's ten-input ceiling).

**D10 — Minute exits on Gate: the archive, then 5-minute candles, then the
last week of minutes.** For the v2 window the minutes come from (a) the
monthly 1m archive for completed months, (b) REST 1m for the last 6.9 days,
and (c) REST **5m** candles for the stretch between them (the current month
before the last week, at most 24 days). A 5-minute bar inside the gap settles
an exit exactly the way a minute does; when TP and SL fall in the same 5-minute
bar it is booked SL and counted in `unclear`, as today. The PC's own download
keeps 1m going forward, so its store fills the gap day by day.

**D11 — The cost of every trade is the order book AT ITS MINUTE.** A daily
GitHub job (`costs.yml`, both accounts, coins dealt) replays Gate's hourly
order-book files for each coin and writes, for every minute: best bid, best
ask, and the price that fills the runner's size ($5 margin x 20 = $100) on
each side. The backtest charges entry and exit at their own minutes' fills plus
Gate's taker fee and funding, and REFUSES an entry the runner's cost check
would refuse at that minute (`edge_check`'s rules: cost ≥ 50% of TP, stop
inside the gap, book that cannot fill, funding that eats the target), counting
the refusal. A minute with no reading uses the newest reading of that coin
within the hour before it (the snapshot-only days give one per hour); none at
all → the static per-contract cost of today, counted as `cost_unmeasured`.

**D12 — Real money on Gate is built but stays shut until a Gate key passes
the preflight.** Orders, the resting stop (Gate `price_orders`), positions,
closed-position history, wallet — all behind `gate_credentials` (same storage
pattern as MEXC's). Without a key every real-money path refuses by name; the
practice account needs no key.

**D13 — The screen says Gate.** `/api/venue` names the exchange; every
user-visible "MEXC" in the web app reads from it. The "MEXC only (not on OKX)"
filter becomes "only on <venue> (not on OKX)".

## Architecture

```
caller ── fx (exchange.py) ──► venue.current() ──► gate_futures  (D2, D4)
                                               └─► mexc_futures   (archive, tests)
gate_futures ─ REST api.gateio.ws/api/v4/futures/usdt   prices, candles, book, funding, orders
             ─ archive download.gatedata.org           1m months, hourly order books
live_price.PriceFeed ─ wss://fx-ws.gateio.ws/v4/ws/usdt   trades, tickers, candles (+ private)
book_history ─ hourly order-book file → per-minute {bid, ask, buy fill, sell fill}
costs.yml (GitHub, 40 machines) ─ book_history per coin-day → release asset per day
sweep_shard (v2) ─ candles + minutes (D10) + costs (D11) → rows with real cost and refusals
```

## Phases (each committed, pushed to both accounts, and verified before the next)

1. **Door + adapter (public data).** `venue.py`, `exchange_errors.py`,
   `exchange.py`, `gate_futures.py` public half, every import moved to the
   door, `kind()`, venue in row ids, tests pinned to MEXC for the old suite and
   new Gate tests against a local fake Gate server.
2. **GitHub on Gate.** Workflow env, minutes per D10, downloads and backtests
   (v1, v2) measured on Gate, collected into the Gate stores.
3. **Past cost per minute.** `book_history`, `costs.yml`, the backtest's cost
   and refusal per D11, the v2 shard reading the day files.
4. **Runner on Gate.** Websocket feed, shared price board, cost check with
   Gate's fees and funding cycle, the cutover script (D7, D8), the daily
   update and the watcher on the Gate store.
5. **Replays on Gate.** Forecast v2, room strategies' daily re-test, Backtest
   a room — all read the Gate store and Gate replays.
6. **Real money on Gate (shut).** The private half per D12, the keys screen,
   preflight.
7. **Words.** Every screen and document that names the exchange.

## What this does NOT claim

* Real-money trading on Gate is untested against a live key — there is none
  on this PC. It refuses until one passes the preflight.
* Minute exits in the current month's gap are 5-minute exits (D10) until the
  PC's own minutes cover them; the row's `unclear` count says how many were
  decided inside one small bar.
* Order-book history from Sep 30 to Oct 08, 2026 is one snapshot an hour, so a
  trade in those days is charged the hour's opening book (D11), and says so.
