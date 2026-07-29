# New Crypto tab — MEXC new-listing screener with Twitter-aware analysis

Date: 2026-07-29
Status: approved (sections 1–3 reviewed; 4–6 documented here)

## Goal

Add a "New Crypto" tab to the Streamlit web UI. It lists MEXC spot coins whose
first trade was within the last 30 days as a table, one row per coin, with an
Analyze action per row. Analyze runs the existing multi-agent pipeline over
Twitter, Reddit, and news data and returns a BUY / SELL / HOLD verdict.

## Decisions taken during brainstorming

| Question | Decision |
| --- | --- |
| Twitter data source | Third-party reseller API — twitterapi.io (`TWITTERAPI_IO_KEY`) |
| Definition of "new" | First trade on MEXC within 30 days, derived from earliest kline |
| Analysis depth | Sentiment + News + Market (MEXC prices) → debate → trader → risk |
| Verdict placement | Inline verdict column plus an expander holding full reports |
| Twitter scope | Shared sentiment analyst, config-gated; on for New Crypto, off for stocks |
| Scan scope | 6h cache, manual refresh, 24h quote-volume floor with a show-all escape |

## Constraints discovered by live probing

1. **The primary MEXC host is ISP-blocked.** `api.mexc.com` returns HTTP 302 to
   `https://prohibitedaccess.pldtsmart.com.ph/` on this network. `api.mexc.fm`
   and `api.mexc.co` serve the same v3 API and return 200.
2. **Yahoo Finance does not cover these coins.** `CATE-USD` and `CUPSEY-USD`
   return zero rows from yfinance. MEXC klines are the only price source, so the
   market analyst needs a MEXC-backed vendor.
3. **`startTime=0` does not return the earliest kline.** MEXC ignores it and
   serves the most recent candles. Listing age must be derived from the row
   count of a bounded request instead.
4. **MEXC rate-limits above roughly 25 requests/second.** A 200-symbol probe at
   31 req/s produced 12 HTTP 429s out of 200.
5. **No free Twitter/X read path exists.** `api.twitter.com` returns 401,
   `cdn.syndication.twimg.com` search returns an empty body, and nitter
   instances return 0 bytes or 503.

## Section 1 — MEXC data layer

New module `tradingagents/dataflows/mexc.py`. Keyless throughout.

**Host resolution.** Try `api.mexc.fm`, `api.mexc.co`, `api.mexc.com` in order,
probing `/api/v3/ping`, and cache the first working host for the process
lifetime. `MEXC_API_HOST` overrides the list. A 3xx whose `Location` host is not
a MEXC host counts as a failure, so an ISP block page is never parsed as data.

**Screener sweep.** Three stages, cheapest first:

1. `GET /api/v3/exchangeInfo` — one call. Yields 1741 USDT-quoted symbols with
   `fullName` and `contractAddress`.
2. `GET /api/v3/ticker/24hr` — one call. Yields `lastPrice`, `quoteVolume`, and
   `priceChangePercent` for every symbol; supplies the table's price columns and
   the volume filter.
3. `GET /api/v3/klines?symbol=X&interval=1M&limit=3` per symbol — the age
   prefilter. Fewer than three monthly candles means the symbol first traded
   within roughly two months. Survivors then get one
   `interval=1d&limit=500` call to pin the exact first-trade date, and the
   30-day cut is applied to that date.

Concurrency is capped so the sustained rate stays near 15 req/s, with one
`Retry-After`-aware backoff on 429 and a single retry per symbol. A symbol that
still fails is reported as unknown-age and excluded rather than guessed.

**Vendor functions.** `get_mexc_stock_data(symbol, start_date, end_date)`
returns the same CSV shape as `get_YFin_data_online`.
`get_mexc_indicators(symbol, indicator, curr_date, look_back_days)` feeds MEXC
candles through the existing `stockstats_utils` path. Both are registered in
`VENDOR_METHODS` under the `"mexc"` key for `get_stock_data` and
`get_indicators`, and both raise `NoMarketDataError` for symbols MEXC does not
list so `route_to_vendor`'s chain semantics work unchanged.

Symbol mapping (`CATE-USD` ↔ `CATEUSDT`) lives in `dataflows/symbol_utils.py`
beside the existing `_normalize_crypto`.

`default_config.py` gains `"mexc"` to the documented options for
`core_stock_apis` and `technical_indicators`, but the defaults stay `yfinance`.
Only the New Crypto run overrides them, so no existing stock run changes
behavior.

**Caching.** Sweep results are written to `data_cache_dir` with a 6h TTL, keyed
by date and window. The UI reads cache on open and only rescans on explicit
refresh.

## Section 2 — Twitter source

New module `tradingagents/dataflows/twitter.py`, contract identical to
`reddit.py`: `fetch_twitter_posts(...) -> str` returns a prompt-ready plaintext
block, degrades to `<twitter unavailable: Reason>` on any failure, and never
raises.

Calls twitterapi.io advanced search with `X-API-Key` from `TWITTERAPI_IO_KEY`,
querying the cashtag and coin name, bounded to the same 7-day window the
sentiment analyst already uses, capped at 30 posts, each rendered with author,
timestamp, like/retweet counts, and body so the model can weight engagement.
A missing key yields the placeholder, not an exception.

The response parser is written defensively over field names because the exact
schema is unverified — the implementation plan's first task is a live probe
against a real key to pin the shape, with the recorded response committed as a
test fixture.

Wiring: a fourth pre-fetched block in `sentiment_analyst.py`, beside news,
StockTwits, and Reddit, gated on `config["include_twitter"]` (default `False`).
The prompt names Twitter as a source only when the block is present, so the
model is never invited to invent tweets — the failure mode this analyst was
redesigned to prevent (#557).

## Section 3 — Analyze wiring

No new graph and no new agents. Analyze constructs
`TradingAgentsGraph(selected_analysts=("market", "social", "news"), config=cfg)`
where `cfg` sets `data_vendors["core_stock_apis"] = "mexc"`,
`data_vendors["technical_indicators"] = "mexc"`, and `include_twitter = True`,
then calls `propagate(symbol, date, asset_type="crypto")`.

Fundamentals is excluded by omission, matching how the CLI already filters
analysts for crypto (`cli/utils.py:filter_analysts_for_asset_type`). Debate,
trader, and risk nodes run unchanged, so the verdict comes from the same
machinery as the existing tab and `final_trade_decision` is populated the same
way.

`resolve_instrument_context` performs a yfinance identity lookup that will miss
for these coins. It is fail-open, so instead of letting it degrade to nothing,
the screener passes MEXC's `fullName` and `contractAddress` as the instrument
identity.

Streaming reuses the existing `graph.stream()` loop pattern from `app.py`, which
yields full state snapshots (`stream_mode="values"`), so per-stage progress needs
no new plumbing.

## Section 4 — Tab UI

`app.py` currently renders one screen from `main()` at 879 lines. Rather than
grow it, `main()` becomes a two-tab shell:

```python
tab_run, tab_new = st.tabs(["Run analysis", "New Crypto"])
```

The existing screen moves into `tab_run` unchanged. The new screen lives in a
new module `crypto_screener.py` exposing `render_new_crypto_tab()`, so the tab's
table, filters, and run loop are testable and reviewable on their own. Shared
CSS, `header_html`, `_signal_color`, and the stage/progress helpers are imported
from `app.py` rather than duplicated.

**Table columns:** Symbol, Name, Listed (date), Age (days), Price, 24h %,
Volume (24h quote), Verdict/Action. Sorted by listing date descending — newest
first. Rendered as CSS-styled HTML rows in the existing terminal aesthetic, one
Streamlit button per row for Analyze, because `st.dataframe` cannot host
per-row buttons.

**Controls:** a refresh button that forces a rescan, a minimum-volume number
input defaulting to $50,000, and a "show all (including dust)" checkbox that
bypasses the floor.

**Interaction:** clicking Analyze on a row replaces that row's button with a
live `n/N` stage counter (N derived from the selected analysts plus the debate,
trader, and risk stages) driven by the existing `stage_statuses` and
`progress_summary` helpers; on
completion the Verdict cell fills with a colored BUY / SELL / HOLD. Verdicts are
kept in `st.session_state` keyed by symbol and date, so analyzing a second coin
does not clear the first, and an expander below the table shows the full report
set for the most recently analyzed coin.

## Section 5 — Error handling and degradation

The rule throughout: every remote source degrades to a visible placeholder, and
nothing fabricates data.

| Failure | Behavior |
| --- | --- |
| All MEXC hosts blocked | Tab renders an explicit error naming the ISP block and the `MEXC_API_HOST` override; no empty table pretending there are no new coins |
| Sweep partially rate-limited | Coins that resolved are shown; a caption states how many symbols could not be checked |
| Stale cache present, refresh fails | Cached rows shown with their age in the caption |
| `TWITTERAPI_IO_KEY` missing | Sentiment runs on news + StockTwits + Reddit, and the report says Twitter was unavailable |
| twitterapi.io 4xx/5xx or quota exhausted | Same placeholder path |
| MEXC has no candles for a symbol | `NoMarketDataError` → vendor chain → market analyst reports unavailable |
| Pipeline raises mid-run | Row verdict shows an error chip; `raw_error` detail goes in the expander, matching existing behavior |

Cost control: Twitter defaults off outside this tab, the per-run post cap is
fixed at 30, and Analyze runs one coin at a time.

## Section 6 — Testing

Test-driven, following the repo's existing pytest layout and marker style.

**Unit, no network** (mocked/fixture-backed):

- Host resolution: prefers the first reachable host, treats a
  `prohibitedaccess` redirect as failure, honors `MEXC_API_HOST`.
- Listing-age derivation: fewer than 3 monthly candles → candidate; exact
  first-trade date from daily candles; 30-day boundary is inclusive at 30 and
  excludes 31.
- Volume filter and sort order.
- `get_mexc_stock_data` CSV shape matches the yfinance vendor's columns.
- Unknown symbol raises `NoMarketDataError`.
- Symbol mapping round-trips `CATE-USD` ↔ `CATEUSDT`.
- Twitter fetcher: parses the recorded fixture, caps at 30 posts, returns the
  placeholder on missing key, HTTP error, timeout, and malformed JSON.
- Sentiment analyst includes the Twitter block only when `include_twitter` is
  set, and the prompt omits Twitter framing when it is not.
- Analyze config builder: correct vendors, correct analyst subset, fundamentals
  absent, `asset_type="crypto"`.

**Integration, network-marked** (skipped by default, run on demand): live sweep
returns a non-empty coin list with plausible dates; live klines for a known new
coin produce a parseable CSV.

**Regression:** the existing suite must pass unchanged, proving default stock
runs still route to yfinance.

**Manual verification:** launch the app, open the tab, screenshot the table,
analyze one real coin end to end, and confirm a verdict renders.

## Out of scope

Token genesis dates, on-chain data, futures/perp symbols, non-USDT quote pairs,
batch/parallel analysis of several coins, alerting on new listings, and
automatic trade execution.
