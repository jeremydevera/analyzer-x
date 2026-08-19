---
name: yearly-strategy-sweep
description: Use when the operator asks to re-run the full-market strategy sweep, refresh the "what's working now" artifact, check whether a deployed strategy still holds up, or compare current results against a previous run. Runs every MEXC contract across 1h/15m/1m over the longest history each venue actually serves, separates real edges from lucky draws, and publishes the comparison artifact.
---

# Yearly Strategy Sweep

The operator's reason for this existing, in their words:

> "for me to see what's working now and what's not working in the future"

So this skill is **not** a strategy finder. It is a **re-measurement**: run it again, and
the number that matters is what CHANGED against `BASELINE.md`. A config that survived in
August and fails in November has told you something. A fresh grid with no baseline has not.

## Run it

```bash
export SWEEP_DIR=~/.tradingagents/sweeps/$(date +%Y-%m-%d)/ && mkdir -p $SWEEP_DIR
cd "/Users/jeremydevera/Desktop/Trading Agents"
.venv/bin/python .claude/skills/yearly-strategy-sweep/scripts/1_sweep_mexc.py      # ~2h
.venv/bin/python .claude/skills/yearly-strategy-sweep/scripts/2_binance_1m_year.py # ~2h, optional
.venv/bin/python .claude/skills/yearly-strategy-sweep/scripts/3_pack.py
.venv/bin/python .claude/skills/yearly-strategy-sweep/scripts/4_build_artifact.py
```

Every stage checkpoints per coin. Killing and restarting resumes; nothing is recomputed.
Run stage 1 in the background with a Monitor — do not sit and poll it.

## The dimensions — all of them vary

| Dimension | Values |
|---|---|
| Coin | every tradeable USDT perpetual (~979), minus liquidity-gate exclusions |
| Timeframe | 1h, 15m, 1m |
| Signal | mom6, mom15, fade15, trend50, rsi14, sweep30, fvg — 7 |
| TP/SL | 3 pairs per timeframe, scaled to the bar |
| Sizing | **martingale AND flat** |

~55,000 combinations. Add 30m/4h/1d by extending `TFS` and `BARRIERS` together.

## History depth — MEASURE it, never assume

Measured 2026-08-13 by paging `klines` backwards until the venue stopped:

| TF | MEXC serves | Bars |
|---|---|---|
| 1h | **416+ days** | 10,000 |
| 15m | **360 days** | 34,636 |
| 1m | **30 days — hard ceiling** | 44,473 |

**Re-measure on every run.** A previous version of this sweep capped 15m at 8,000 bars
(83 days) when 34,636 were available, and quietly produced meaningless 15m results for
an entire night. Never cap a fetch below what the venue serves.

**A year of 1m does not exist on MEXC.** Binance serves 370+ days — stage 2 uses it, but
only for contracts whose candles actually agree with MEXC's (see below).

**Most coins are younger than the window you ask for.** Asking for 360 days of 15m and
getting a median of 20 is not a bug; it is coin age. Record `days` per row and show it.

## Three costs, not two — MANDATORY

A perpetual charges for **getting in**, **getting out**, and **staying in**.
Fee and slippage are charged by default; the third must be passed:

```python
at.backtest_strategy(..., funding=fx.funding_history(coin))
```

Each published settlement inside a trade's own window is applied at its real
rate, so a 6-hour trade pays one cycle and a 5-day trade pays thirty. MEXC's
sign: a positive rate means longs pay, so a short can be PAID to hold.

Measured 2026-08-19 on the five live strategies, $5 base: PROVE **−4.7%**,
APEX −0.8%, PI −0.2%, ALICE **+0.5%** and XAUT **+0.5%** — the last two receive
it. Charging funding is accuracy, not pessimism.

Traps:

* **The artifact must replay funding too**, from settlements embedded per coin,
  or the trade log stops summing to the row it belongs to.
* **Convert bar timestamps through `datetime64[ms]`**, never by dividing a raw
  `int64`: MEXC frames are `datetime64[s]`, and a nanosecond divisor read 1,754
  instead of 1,754,406,000,000 — every window then spanned the whole history and
  PROVE's year read **−$2,230 instead of +$176**.
* **Rates are not always small.** PROVE's history carries −2.00% settlements.

## The survivor test — the whole point

A row is a **survivor** only if all four hold:

1. profitable overall
2. profitable in the **first half** of its history
3. profitable in the **second half**
4. green in **≥70% of months**, with **≥90 days of history**

Rule 4's history floor is not optional. Without it, coins listed two weeks ago pass
trivially — "2/2 months green" is close to a coin flip — and they flood the top of the
short-timeframe tables. On 2026-08-13 that produced 42 fake 15m "survivors", every one
under three months old, while **zero** survived on a genuine year.

**Then require flat.** A survivor that only works martingale is telling you the ladder
works. Of 72 1h survivors on a real year, **70 were martingale-only** and just **one**
survived both sizings.

So the hierarchy to report is always:

```
profitable            -> mostly luck, 55k draws will do that
survivor              -> consistent across halves and months
survivor + flat       -> the SIGNAL works. This is the short list.
```

## Cross-venue data: gate it on measured agreement

Binance can supply a year of 1m, but a Binance candle only substitutes for a MEXC candle
where the two books agree. Measured on the same minutes:

| Contract | Median wick disagreement | vs a 0.10% stop |
|---|---|---|
| XAUT (deep) | 0.0153% | 15% — usable |
| PROVE (thin) | **0.0664%** | **66% — unusable** |

On PROVE the two exchanges disagree about the minute's high/low by as much as the whole
bar is tall; at a 0.10% stop that flips the outcome **55% of the time**. Stage 2 gates
every coin at **median disagreement ≤ 25% of the tightest stop** and skips the rest.

Of 979 MEXC contracts: 445 are not on Binance, 397 are but disagree, **137 qualify**.
Those 397 are the dangerous ones — the data downloads cleanly and would produce a
confident, wrong answer.

**Costs always stay MEXC's.** The orders go to MEXC; only the price history is borrowed,
and every such row is labelled `source: binance`.

## Traps this pipeline already handles — keep them handled

| Trap | What it did | Guard |
|---|---|---|
| Per-bar `strftime` | 80% of backtest runtime on 525k bars | stamps computed per TRADE; `backtest_strategy` also accepts `dirs=` |
| Recomputing signals | identical array built 6× per coin | compute `dirs` once per (coin, tf, signal) |
| Rate limit marks coin done | coin silently dropped from results forever | transient errors retry with backoff, coin is **not** marked done |
| MEXC truncates a hammered client | wrong numbers, no error | throttle ~7 req/s, validate bar count |
| Log key float formatting | `str(1.0)`≠`String(1)` — trade logs dead on exactly the winning rows | format both sides `%.2f` |
| Summing a truncated log | panel total contradicted the table | show the row's real total, state the truncation |
| Trimming per-row data to fit the size cap | 22,482 of 23,296 rows silently lost their monthly columns; the operator's own live row showed 11 blanks | compress the ENCODING (arrays, not dicts), never the coverage — and verify a row the default filter hides |

## Publishing

Follow `CLAUDE.md` exactly — PROFIT/TOTAL $, TP, SL, leverage, margin AND notional, WINS,
LOSSES, trades, combination count above the table, artifact with clickable per-row trade
logs, base-margin box, explicit TOTAL PROFIT in the log panel, sortable columns.

Plus, for this skill specifically:

- a **Min history** filter (90 / 180 / 300+ days) — the most important control on the page
- **history days** as a visible column on every row
- **source** column when Binance data is mixed in
- exclusion count and reasons stated
- **a diff against `BASELINE.md`**: what survived last time and fails now, and vice versa

## Red flags

| Thought | Reality |
|---|---|
| "15m looks great, 2/2 months green" | Two months existed. Set Min history to 300 and look again |
| "Top of the profit column is the best strategy" | 90% of profitable rows are noise. Read the survivor list |
| "It's a survivor, ship it" | Check flat. 70 of 72 were ladder-only |
| "More history will fix 1m" | A full year of BTC 1m: best of 42 configs was **−$699** |
| "Binance has the data, use it" | Only where the candles agree. Measure per coin |
| "Nothing survived, the run failed" | A null result is a result. Report it; do not loosen the filter to find something |
