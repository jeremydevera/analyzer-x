# Baseline — 2026-08-14 sweep

Compare every future run against this. What matters is what CHANGED.

## Coverage

| | |
|---|---|
| Contracts swept | 979 (all tradeable USDT perpetuals) |
| Combinations tested | 55,062 |
| Profitable rows | 2028 |
| Excluded | 411 (361 liquidity gate, rest fetch/short history) |
| Binance year-of-1m | 137 contracts gated in, **0 profitable rows** |

## By timeframe, on a REAL year (300+ days)

| TF | Profitable | Survivors | Best survivor |
|---|---|---|---|
| 1h | 693 | **72** | PI mom6 SL1.00/TP4.00 martingale +540.75 |
| 15m | 28 | **0** | **none** |
| 1m | 0 | **0** | **none** |

## The short list — survivor on a real year AND flat-profitable

These are the only configurations whose SIGNAL is demonstrably profitable.

| Coin | Signal | TF | SL | TP | Flat $ | Halves | Green | Mart $ | Cost %TP | Trades | Days |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **APEX** | sweep30 | 1h | 1.00% | 4.00% | **+55.72** | +19.62 / +39.52 | 10/12 | +141.16 | 4% | 302 | 320 |
| **XAUT** | mom6 | 1h | 0.80% | 2.40% | **+36.85** | +13.85 / +23.81 | 11/15 | +148.65 | 1% | 282 | 416 |

## Deployed at the time of this baseline

| Coin | Strategy | TF | SL | TP | Sizing |
|---|---|---|---|---|---|
| PI | mom15_4h_w | 4h | 2.00% | 8.00% | martingale |
| PROVE | trend50_4h | 4h | 1.50% | 4.50% | martingale |
| XAUT | mom15_1h_g | 1h | 0.80% | 2.40% | martingale |

## Headline findings to re-test

1. **1h is the only timeframe with real edges.** 1,831 profitable vs 165 at 15m, 32 at 1m.
2. **15m survives nothing over a real year.** 28 profitable on 300+ days, **0 survivors**.
3. **1m cannot pay its costs.** A full year of BTC 1m: best of 42 configs was **-$699**.
4. **The ladder does most of the work.** 70 of 72 1h survivors were martingale-only.
5. **Exactly 1 config of 55,062 survived at both sizings** (XAUT mom6) at baseline;
   APEX sweep30 was the second flat survivor.

If a future run contradicts any of these, that is the finding — say so explicitly.
