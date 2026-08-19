# Incident 2026-08-12 — BDX_USDT liquidation

**Impact:** ~43 USDT lost on a live MEXC account (−27.74 of it a liquidation),
across roughly two hours of the auto-trader's first live session.

**One-line cause:** a backtest that charged nothing for touching the market
recommended an untradeable contract, and an execution path that *assumed* its
stop-loss existed instead of verifying it let the resulting positions run naked.

Read this before adding any new strategy. Every rule in
`.claude/skills/three-gates/SKILL.md` and every guard in
`tradingagents/auto_trader.py` marked "the BDX lesson" was bought here.

---

## Part A — why BDX looked profitable (analysis failure)

The 941-coin sweep filled every simulated trade at the printed candle price:
**zero slippage, zero spread**. BDX_USDT's `fade15` on 1-minute bars showed
**+1,560.96 USDT over 13 days** and topped the table. A later "corrected" pass
charged one *generic* 0.03%/side to all 941 contracts and still showed +698.

Both were wrong for the same reason: **cost was assumed, not measured, and one
average was applied to 941 different order books.**

Measured from BDX's live book on the day:

| | BDX_USDT | BTC_USDT |
|---|---|---|
| bid/ask spread | **1.56%** | 0.000% |
| contracts within 0.1% of mid | **0** | 2,133,076 |
| slippage filling a 650-contract order | **0.939%** | 0.000% |
| round-trip cost | **~1.9%** | ~0.04% (fees only) |

The strategy's take-profit was **0.36%**. The spread alone was 4× the prize.

Same 5,366 trades, only the cost assumption changing:

| slippage/side | result |
|---|---|
| 0.000% (original sweep) | +1,568 |
| 0.030% (generic) | +704 |
| **0.939% (measured)** | **−135,790 — zero winning trades** |

Breakeven slippage for that config is **0.063%/side**. BDX's real cost is
**15× past it**. It was never profitable at any point in its history.

## Part B — why the loss was 43 USDT instead of small (execution failures)

Four defects, in the order they fired:

1. **`code 2015` — precision.** TP/SL prices carried more decimals than the
   contract permits, so MEXC rejected the bracket. Positions opened with no stop.
2. **`code 5003` — stop already breached.** BDX moves faster than an order
   round-trip; by placement time price had passed the stop level. Rejected again.
3. **The core bug.** When the candles later crossed that stop level, the runner
   *assumed* the exchange bracket had fired and cleared the position from its
   book. No bracket ever existed — the real position stayed open on MEXC while
   the bot believed it was flat, and re-entered every minute at deeper
   martingale rungs (400 → 800 → 1,600 USDT notional).
4. **Wrong-position lookup.** `open_positions()[0]` returned a stale
   opposite-side position during 1-minute churn, orphaning the live one.

End state: an unprotected 650-contract short one tick from liquidation. A market
close was refused (`code 2078`, too near liquidation); a resting limit close
needed a downtick that never came. MEXC liquidated it: **−27.74 USDT**.

A fifth defect surfaced the same day: **`code 2051`**, a deep ladder rung
exceeding the contract's per-order volume cap (BDX allows 650 contracts;
step 5 wanted ~919), silently losing trades.

---

## Fixes (all shipped, all test-pinned)

### Analysis
- `backtest_strategy()` charges slippage by default (`slippage=0.0003`).
- `mexc_futures.book_cost()` measures real slippage by walking the live book.
- Published tables charge **per-coin measured cost**, never one global average.

### Execution (`tradingagents/auto_trader.py`)
- `_snap_prices()` — bracket prices rounded to each contract's `priceScale`.
- `_rest_bracket()` — on `5003`, the position is **closed immediately** rather
  than held naked; any other rejection logs CRITICAL and retries every cycle.
- A barrier crossed while `pos["bracket"] is False` makes the runner **close
  the position itself**; it never assumes the exchange did.
- Position matched by **side + newest `updateTime`**, never `[0]`.
- `adopt_orphans()` — every cycle, any exchange position on a bot coin that the
  book is not tracking is adopted and bracketed.
- Order size capped at the contract's `maxVol` (`2051`).
- `_force_close()` — market close, falling back to a resting limit on `2078`.
- Manual/exchange closes record MEXC's **real** realized PnL via
  `position_history()`, not a bracket-price estimate.

### Prevention (the part that stops the NEXT strategy repeating this)
- **`edge_check(strategy, symbol, margin)`** measures the live book at the
  strategy's *deepest ladder rung* and compares round-trip cost to take-profit:
  - cost ≥ **50%** of TP → `block` (runner refuses orders, UI shows BLOCKED)
  - cost ≥ **20%** of TP → `warn`
  - book cannot fill the deepest rung → `block`
  - book unreadable → `unknown` (never silently treated as ok)
- The Auto Trade tab shows this verdict per strategy/coin before you can enable
  it, and the LIVE banner refuses to pretend a blocked pair will trade.

Live verdicts on the day of the fix:

| strategy | coin | spread | cost | TP | cost/TP | verdict |
|---|---|---|---|---|---|---|
| ict_fvg | BTC_USDT | 0.000% | 0.040% | 4.50% | 1% | ok |
| mom15_sp | SPX500_USDT | 0.001% | 0.041% | 1.50% | 3% | ok |
| mom15_1h | CHEEMS_USDT | 0.020% | 0.163% | 1.80% | 9% | ok |
| fade15_1h | ONG_USDT | 0.024% | 0.142% | 1.80% | 8% | ok |
| fade15_15m | MCDSTOCK_USDT | 0.095% | 0.155% | 0.90% | 17% | ok |
| **fade15_1m** | **BDX_USDT** | **1.115%** | **2.643%** | **0.36%** | **734%** | **block** |

---

## Checklist before enabling any new strategy

1. Run **Backtest on selected coins** in the Auto Trade tab — it charges slippage.
2. Read the **liquidity gate** line under the coin list. `BLOCKED` means the
   contract cannot support the strategy at any size; `Thin book` means size down.
3. Sanity-check the ratio yourself: **round-trip cost must be a small fraction
   of the take-profit.** Under 20% is comfortable; near or above 50% is fatal.
4. Prefer few trades on deep books over many trades on thin ones. Every cost in
   this document is paid *per trade*.
5. Confirm the history is real: 1-minute data on MEXC is ~13 days. A "13/13
   green months" claim on 13 days of data is not evidence.
6. Set a per-strategy daily loss limit before the first live order.
7. Watch the first live exits and compare them to the backtest log.
