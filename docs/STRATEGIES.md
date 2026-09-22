# Your strategies — what each one looks for, and how a trade happens

The operator, `Sep 21, 2026`: *"where do you document my existing strategies for
all my coins? like is the formula documented"*, then *"i want this clearly
documented on how it works, i want very detailed im planning someting on this"*.

Until this file, the answer was **nowhere you could read**. Each formula carries
one written line beside its code and nothing in the app shows it.

Everything here was measured on the machine on `Sep 21, 2026`, from
`~/.tradingagents/auto_trade.json` (what is deployed), the trade record
(`auto_trade_ledger.jsonl`) and the stored candles. No figure is recalled.

---

## 1. Reading a strategy name

Every deployed row is one line like this:

```
willr14_30m_sl2tp05   on   VUG
└─────┘ └─┘ └─┘└──┘        └─┘
   │     │   │   │           └── the coin it trades
   │     │   │   └────────────── take profit 0.5%   ("tp05")
   │     │   └────────────────── stop loss   2.0%   ("sl2")
   │     └────────────────────── the bar size it reads
   └──────────────────────────── the formula that decides to buy or sell
```

`sl2tp05` is read as **sl 2 . 0** and **tp 0 . 5** — the digits after `sl`/`tp`
are a percentage with the decimal point dropped: `sl12tp12` is 1.2% and 1.2%,
`sl25tp3` is 2.5% and 3.0%.

**A row is the formula PLUS the coin.** `willr14_30m_sl2tp05` runs on five
coins, and those are five separate rows with five separate ids
(`#ZSMP3CF4` DVNSTOCK, `#JXRSKJSW` FASTSTOCK, `#9FTN66Y4` KKRSTOCK,
`#2NYXSXTR` ROLSTOCK, `#XH2KSFXG` VUG). Each has its own on/off switch and its
own record.

---

## 2. How one trade happens, start to finish

```
   ┌────────────────────────────────────────────────────────────────┐
   │  1. MEXC PUSHES A PRICE                                        │
   │                                                                │
   │  one socket, wss://contract.mexc.com/edge, always open         │
   │  a closed bar, a print, or a change to a real position wakes   │
   │  the runner — it does NOT sit on a timer                       │
   │  floor of 2.0s between cycles so a burst cannot flood MEXC     │
   └─────────────────────────────┬──────────────────────────────────┘
                                 ▼
   ┌────────────────────────────────────────────────────────────────┐
   │  2. THE COST GATE, BEFORE THE FORMULA IS EVEN RUN              │
   │                                                                │
   │  for this coin: spread + fee + funding against the target      │
   │  refuse if the cost is 50% or more of what the trade is        │
   │  trying to win                                                 │
   │  refuse if the book cannot be read at all                      │
   │       └──► written down as `gate_blocked`, no order sent       │
   └─────────────────────────────┬──────────────────────────────────┘
                                 ▼
   ╔════════════════════════════════════════════════════════════════╗
   ║  3. THE FORMULA READS THE LAST CLOSED BAR                      ║
   ║                                                                ║
   ║  never a half-finished candle — the live trade has to be the   ║
   ║  same trade the backtest measured                              ║
   ║                                                                ║
   ║  it returns exactly one of three answers:                      ║
   ║       +1  buy        -1  sell        0  do nothing             ║
   ╚═════════════════════════════╤══════════════════════════════════╝
                                 ▼
   ┌────────────────────────────────────────────────────────────────┐
   │  4. FIVE MORE REFUSALS, EACH WRITTEN DOWN BY NAME              │
   │                                                                │
   │  the bar is too old to still be that trade  ──► stale_skip     │
   │  price already ran away from the signal     ──► chase_skip     │
   │  this coin is already held                  ──► coin_busy      │
   │  the wallet cannot fund it                  ──► capital_blocked│
   │  MEXC will not take the whole size at once  ──► size_capped    │
   └─────────────────────────────┬──────────────────────────────────┘
                                 ▼
   ┌────────────────────────────────────────────────────────────────┐
   │  5. THE ORDER GOES OUT                                         │
   │                                                                │
   │  $5 of your money at 20x  =  $100 of coin moving               │
   │  two exit orders are left resting AT MEXC straight away:       │
   │       the "close it, I won"  price   (TP)                      │
   │       the "close it, I was wrong" price (SL)                   │
   │  so the exit happens even if this PC is off                    │
   │  a stop further away than 3.6% is refused — past that MEXC     │
   │  liquidates you before your own stop can fire                  │
   └─────────────────────────────┬──────────────────────────────────┘
                                 ▼
   ┌────────────────────────────────────────────────────────────────┐
   │  6. THE TRADE ENDS                                             │
   │                                                                │
   │  REAL money  ──► whichever resting order MEXC fills first;     │
   │                  MEXC is the only source of truth              │
   │  PRACTICE    ──► the same two prices, checked against every    │
   │                  pushed price; nobody can close it by hand     │
   └────────────────────────────────────────────────────────────────┘

   IF ANYTHING FAILS
     the socket drops ─────► a plain timer takes over; the runner
                             never stops trading because a feed died
     MEXC rejects the order ► named, logged, written down; no retry loop
     a position is open with no stop ► the next cycle adopts it and
                                       puts a stop on it
     you close it by hand at MEXC ──► the runner notices it is gone and
                                      records it as MANUAL/EXCHANGE
```

**The stake never changes with wins or losses** unless you tick Martingale mode
(off by default). With it on, the margin doubles after each loss and returns to
base after a win.

---

## 3. The 16 formulas you actually run

Each one gets the last N closed bars and answers buy / sell / nothing. Twelve of
the sixteen are **mean-reversion**: they buy when price has stretched too far
down and sell when it has stretched too far up. They do not follow trends.

### stoch14 — 24 rows · *where is the close inside the last 14 bars' range?*

Take the highest high and lowest low of the last 14 bars. Work out where the
close sits between them, as 0–100%.

```
K = 100 × (close − lowest low) / (highest high − lowest low)

K below 20  →  BUY    (close is in the bottom fifth of the range)
K above 80  →  SELL   (close is in the top fifth)
otherwise   →  nothing
```

*Code: `signals_ext.py`.* Your coins: DVNSTOCK, FASTSTOCK, GPNSTOCK, KKRSTOCK,
PSXSTOCK, ROLSTOCK, VUG, APOSTOCK.

### willr14 — 24 rows · *the same idea, measured from the top*

Williams %R is the mirror of the above — it runs from −100 (at the low) to 0
(at the high).

```
R = −100 × (highest high − close) / (highest high − lowest low)

R below −80  →  BUY    (same place as stoch14's "below 20")
R above −20  →  SELL
```

**stoch14 and willr14 are the same rule.** `R = K − 100` exactly, so
`K < 20` and `R < −80` are one condition written two ways. Run side by side over
1,487 FASTSTOCK 1h bars they agreed on **1,487 of 1,487**, 522 signals each,
never once differing. See section 7 — this is not a curiosity, it is 40% of your
deployment.

*Code: `signals_ext2.py`.*

### prank — 19 rows · *is this the cheapest close in 100 bars?*

Rank today's close against the previous 100 closes.

```
rank = how many of the last 100 closes were BELOW this one, ÷ 100

rank under 0.05  →  BUY   (cheaper than 95 of the last 100)
rank over  0.95  →  SELL  (dearer than 95 of the last 100)
```

*Code: `signals_ext2.py`.* Your coins: APOSTOCK, FASTSTOCK, FLUTSTOCK,
GPNSTOCK, KKRSTOCK.

### bb20 — 10 rows · *price outside the Bollinger band, fade it*

A 20-bar average with a band two standard deviations either side.

```
close below the lower band  →  BUY
close above the upper band  →  SELL
```

*Code: `signals_ext.py`.* Your coins: FASTSTOCK, GPNSTOCK.

### zscore20 — 10 rows · *the moment it crosses 2 standard deviations*

The same stretch as bb20, but this one fires on the **crossing**, not on
staying outside.

```
z = (close − 20-bar average) ÷ 20-bar standard deviation

z was ≥ −2 last bar and is now < −2  →  BUY
z was ≤ +2 last bar and is now > +2  →  SELL
```

One signal per crossing instead of one every bar while it stays out there.

*Code: `signals_ext2.py`.* Your coins: FASTSTOCK, GPNSTOCK.

### ibs — 6 rows · *where did the bar close inside its own range?*

Only this one bar is looked at — no history at all.

```
IBS = (close − low) ÷ (high − low)

IBS under 0.15  →  BUY   (closed pinned to its own low)
IBS over  0.85  →  SELL  (closed pinned to its own high)
```

The fastest-reacting rule you run, and the shortest-memoried.

*Code: `signals_ext2.py`.* Your coins: FASTSTOCK, GPNSTOCK, ROLSTOCK.

### macddiv — 6 rows · *price made a new low but momentum did not*

The only **divergence** rule you run. It compares price against the MACD
histogram (12/26/9).

```
look back 40 bars, find the lowest close in that window

price is LOWER than that low, but the histogram is HIGHER
than it was there (by at least 5% of the window's range)   →  BUY

the mirror at the highest close                            →  SELL
```

In plain words: the fall is running out of strength.

*Code: `signals_ext2.py`.* Your coins: FASTSTOCK, KKRSTOCK, STBL.

### vwaprev — 5 rows · *stretched from today's volume-weighted average*

VWAP is the average price weighted by how much traded at it, restarted each
day at 00:00 UTC.

```
measure how far the close is from today's VWAP, as a percentage
turn that into a z-score over the last 50 bars

crossing below −2  →  BUY
crossing above +2  →  SELL
```

**It needs volume data.** With no volume it returns nothing at all rather than
guessing.

*Code: `signals_ext2.py`.* Your coin: FASTSTOCK.

### cci20 — 4 rows · *Commodity Channel Index at ±100*

```
typical price = (high + low + close) ÷ 3
CCI = (typical − 20-bar mean) ÷ (0.015 × mean absolute deviation)

CCI below −100  →  BUY
CCI above +100  →  SELL
```

*Code: `signals_ext.py`.* Your coin: FASTSTOCK.

### keltner — 4 rows · *outside a band built from real movement*

Like Bollinger, but the band width comes from Average True Range — how far the
coin actually travels — instead of standard deviation.

```
centre = 20-bar EMA,  width = 1.5 × ATR

close below centre − 1.5×ATR  →  BUY
close above centre + 1.5×ATR  →  SELL
```

*Code: `signals_ext.py`.* Your coins: FASTSTOCK, GPNSTOCK.

### macddiv, cf_soup1 and cx_veto — the combination rules

**cf_soup1** (2 rows, FASTSTOCK) — *Turtle Soup +1*. A new 20-bar low is made,
but the previous 20-bar low was at least four bars ago, and the bar closes back
**above** its own low. A false breakdown, rejected on the bar.

```
low < 20-bar low  AND  close > low  AND  the 20-bar low 4 bars ago was higher  →  BUY
the mirror at the 20-bar high                                                  →  SELL
```

**cx_veto** (1 row, FASTSTOCK) — *soup1, unless momentum disagrees*. It takes
cf_soup1's answer and throws it away when a simple momentum rule points the
other way. A conflict cancels the trade rather than picking a side. This is the
only **non-linear** rule you run — it can say "no" to a signal that fired.

*Code: `signals_conf.py` and `signals_cascade.py`.*

### killzone — 1 row (CTC 4h) · *momentum, but only 12:00–16:00 UTC*

```
only between 12:00 and 16:00 UTC — ignored at every other hour

price up more than 0.3% over the last 6 bars    →  BUY
price down more than 0.3% over the last 6 bars  →  SELL
```

The one **trend-following** rule in your deployment, and the only one with a
clock in it.

*Code: `signals_ext2.py`.*

### ote — 1 row (XPIN 1h) · *buy the 62–79% pullback into a move*

```
find the last real swing low and swing high (fractals)
mark the zone 62% to 79% back into that move
if price enters the zone within 30 bars  →  trade in the move's direction
the zone then expires — one trade per swing
```

*Code: `signals_ext2.py`.*

### eqraid — 1 row (PDDSTOCK 1h) · *two equal highs swept, then rejected*

```
two swing highs within 0.1% of each other = a pool of stops sitting above

a bar pokes ABOVE that level but closes back BELOW it  →  SELL
the mirror below two equal lows                        →  BUY
```

*Code: `signals_ext2.py`.*

### fade15 — 2 rows · *bet against a sharp move* — ⚠ **see section 7, these are dead**

```
r = price now ÷ price 15 bars ago − 1

r above the threshold  →  SELL   (fade the rise)
r below the threshold  →  BUY    (fade the fall)
```

*Code: `auto_trader.py` — one of the original seven, which live there rather
than in the signal files.*

---

## 4. Everything you have deployed

**120 rows · 85 strategy names · 16 formulas · 13 coins · $5 margin each · 20x
leverage ($100 of coin per trade) · flat staking · all on the practice book.**

| formula | rows | bar sizes | coins |
|---|---|---|---|
| stoch14 | 24 | 15m, 30m, 1h, 4h | APOSTOCK, DVNSTOCK, FASTSTOCK, GPNSTOCK, KKRSTOCK, PSXSTOCK, ROLSTOCK, VUG |
| willr14 | 24 | 15m, 30m, 1h, 4h | the same eight |
| prank | 19 | 15m, 30m, 1h | APOSTOCK, FASTSTOCK, FLUTSTOCK, GPNSTOCK, KKRSTOCK |
| bb20 | 10 | 15m, 30m, 1h | FASTSTOCK, GPNSTOCK |
| zscore20 | 10 | 15m, 30m, 1h | FASTSTOCK, GPNSTOCK |
| ibs | 6 | 15m, 30m, 1h, 4h | FASTSTOCK, GPNSTOCK, ROLSTOCK |
| macddiv | 6 | 30m, 4h | FASTSTOCK, KKRSTOCK, STBL |
| vwaprev | 5 | 30m | FASTSTOCK |
| cci20 | 4 | 1h | FASTSTOCK |
| keltner | 4 | 15m, 30m | FASTSTOCK, GPNSTOCK |
| cf_soup1 | 2 | 1h | FASTSTOCK |
| fade15 | 2 | 1h, 4h | APOSTOCK, FASTSTOCK |
| cx_veto | 1 | 1h | FASTSTOCK |
| killzone | 1 | 4h | CTC |
| ote | 1 | 1h | XPIN |
| eqraid | 1 | 1h | PDDSTOCK |

**FASTSTOCK carries 54 of the 120 rows** — nearly half your deployment is one
coin.

---

## 5. The economics — what a row has to beat

The cost of trading is taken off you **whether you win or lose**: subtracted
from a win, added to a loss. Measured on your own trades, $5 at 20x, the cost
is **$0.33–$0.45 per trade**; $0.42 is used below. Full working in
[WHY-LOSING-IS-HEAVIER-THAN-WINNING.md](WHY-LOSING-IS-HEAVIER-THAN-WINNING.md).

```
a win  pays you   TP$ − $0.42
a loss costs you  SL$ + $0.42

break-even win rate = loss ÷ (win + loss)
```

Every take-profit / stop-loss pair you run, and the win rate it needs just to
break even:

| TP | SL | a win pays | a loss costs | break-even | your rows |
|---|---|---|---|---|---|
| 0.40% | 1.20% | **−$0.02** | −$1.62 | **101.3%** | 2 |
| 0.40% | 1.50% | **−$0.02** | −$1.92 | **101.1%** | 8 |
| 0.50% | 2.00% | +$0.08 | −$2.42 | 96.8% | 12 |
| 0.50% | 1.50% | +$0.08 | −$1.92 | 96.0% | 3 |
| 0.50% | 1.20% | +$0.08 | −$1.62 | 95.3% | 2 |
| 0.60% | 3.00% | +$0.18 | −$3.42 | 95.0% | 9 |
| 0.60% | 2.50% | +$0.18 | −$2.92 | 94.2% | 8 |
| 0.60% | 2.00% | +$0.18 | −$2.42 | 93.1% | 4 |
| 0.60% | 1.50% | +$0.18 | −$1.92 | 91.4% | 2 |
| 0.80% | 2.00% | +$0.38 | −$2.42 | 86.4% | 4 |
| 1.00% | 3.00% | +$0.58 | −$3.42 | 85.5% | 14 |
| 0.80% | 1.50% | +$0.38 | −$1.92 | 83.5% | 3 |
| 1.00% | 2.50% | +$0.58 | −$2.92 | 83.4% | 8 |
| 1.00% | 2.00% | +$0.58 | −$2.42 | 80.7% | 6 |
| 1.00% | 1.50% | +$0.58 | −$1.92 | 76.8% | 4 |
| 1.50% | 3.00% | +$1.08 | −$3.42 | 76.0% | 7 |
| 1.20% | 2.00% | +$0.78 | −$2.42 | 75.6% | 5 |
| 1.50% | 2.50% | +$1.08 | −$2.92 | 73.0% | 2 |
| 1.20% | 1.50% | +$0.78 | −$1.92 | 71.1% | 1 |
| 1.50% | 2.00% | +$1.08 | −$2.42 | 69.1% | 5 |
| 2.00% | 3.00% | +$1.58 | −$3.42 | 68.4% | 1 |
| 1.20% | 1.20% | +$0.78 | −$1.62 | 67.5% | 2 |
| 2.50% | 3.00% | +$2.08 | −$3.42 | 62.2% | 2 |
| 2.00% | 2.00% | +$1.58 | −$2.42 | 60.5% | 1 |
| 2.50% | 2.50% | +$2.08 | −$2.92 | 58.4% | 2 |
| 3.00% | 3.00% | +$2.58 | −$3.42 | 57.0% | 1 |
| 2.50% | 2.00% | +$2.08 | −$2.42 | 53.8% | 1 |
| 3.00% | 2.50% | +$2.58 | −$2.92 | 53.1% | 1 |

**68 of your 120 rows need a win rate above 85% to break even.** That is the
single most important number in this document. A 50% win rate is never
break-even here — it is a loss on every pair in the table.

The pattern is plain: **a wide stop with a narrow target needs a near-perfect
win rate.** The four best pairs you run — 2.50/2.00, 3.00/2.50, 2.50/2.50,
3.00/3.00 — are the only ones under 60%, and you have four rows using them.

---

## 6. Two engines measure the same thing, and they must agree

| | reads | exits settled | where |
|---|---|---|---|
| **Backtest v1** | the bar size itself (15m, 30m, 1h, 4h, 1d) | by the bar — if a bar touched both prices, the loss is booked | `~/.tradingagents/backtest` |
| **Backtest v2** | 1-minute bars, rebuilt into the same bar sizes | minute by minute — whichever price was touched first wins | `~/.tradingagents/v2` |
| **The runner** | the same closed bar the backtest reads | MEXC's own resting orders | live |

v2 exists because an hour candle cannot say which of two prices came first.
`#LG9NSU4B` (XPIN 1h) stopped out in practice at `7:28am` while the v1
backtest said `7:00am`; v2 reads `7:28am`.

A v2 row's id is never the same as its v1 twin's, so they cannot be confused.

---

## 7. Three things found while writing this

### ⚠ The two `fade15` rows could not fire — the threshold was 100× too big (fixed Sep 23, 2026)

`fade15` needs a move bigger than a threshold over 15 bars. The deploy record
writes that threshold as a **percentage**; the code reads it as a **fraction**.

| row | threshold stored | code reads it as | what was meant |
|---|---|---|---|
| `fade15_1h_sl3tp06` FASTSTOCK | `0.5` | **50%** in 15 hours | 0.5% |
| `fade15_4h_sl3tp1` APOSTOCK | `0.4` | **40%** in 15 bars | 0.4% |

Both intended values are exactly the measuring grid's own thresholds for those
bar sizes (1h uses 0.2% / 0.3% / **0.5%**; 4h uses **0.4%** / 0.6% / 0.8%),
which is what makes the unit slip certain rather than likely.

Measured on the real candles:

| row | bars checked | biggest 15-bar move | signals at the deployed threshold | signals at the intended one |
|---|---|---|---|---|
| FASTSTOCK 1h | 1,487 | 8.42% | **0** | 940 |
| APOSTOCK 4h | 258 | 13.58% | **0** | 211 |

The older `fade15_1h` in the same file uses `0.003` and is correct, so this is
these two entries, not the formula.

**FIXED on Sep 23, 2026** on *"okay start fixing the bugs now"*: `0.5 → 0.005`
and `0.4 → 0.004` (docs/RCA.md RCA-2026-09-23-C). The two rows now fire — 940
and 211 signals over the same bars — and a test refuses any threshold at or
above 5% in the spec table. APOSTOCK itself was delisted and switched off the
same day (RCA-2026-09-23-D), so `fade15_4h_sl3tp1` runs on nothing until it is
armed on a live coin.

### ⚠ 48 of your 120 rows are 24 strategies deployed twice

`stoch14` and `willr14` compute the same number. Measured over 1,487 FASTSTOCK
1h bars: **identical on every bar**, 522 signals each, zero disagreements.

Every one of your 24 `stoch14` rows has a `willr14` twin on the **same bar
size, same stop, same target and same coin** — 24 pairs, 48 rows, **40% of
your deployment**:

```
4h   sl3.00% tp2.50%  APOSTOCK          15m  sl1.20% tp0.40%  ROLSTOCK
15m  sl1.20% tp1.20%  PSXSTOCK          15m  sl1.50% tp0.40%  FASTSTOCK
15m  sl1.50% tp0.40%  ROLSTOCK          15m  sl1.50% tp0.40%  VUG
             ... and 18 more identical pairs
```

They fire on the same bar and take the same trade twice, so each of those 24
ideas is staking **$10 of margin, not $5** — and shows up in your win/loss
record as two trades when it was one decision. It also doubles how much of one
coin you are holding, which the one-position-per-coin rule then has to referee.

Nothing is broken; they are two names for one measurement, and the grid
measured both honestly. But for planning purposes you have **96 distinct ideas
deployed, not 120**.

### ⚠ Ten rows have a target smaller than the cost of trading

Six strategy names, ten rows, all with a **0.40% take-profit**:

```
ibs_15m_sl15tp04      ROLSTOCK
prank_15m_sl15tp04    FASTSTOCK
stoch14_15m_sl12tp04  ROLSTOCK
stoch14_15m_sl15tp04  FASTSTOCK, ROLSTOCK, VUG
willr14_15m_sl12tp04  ROLSTOCK
willr14_15m_sl15tp04  FASTSTOCK, ROLSTOCK, VUG
```

0.40% of $100 is **$0.40**. The cost is **$0.42**. A winning trade nets
**−$0.02**. They cannot make money at a 100% win rate.

The cost gate catches this and refused them **698 times**. But **31 trades got
through** on quieter books, and here is what they did:

```
31 trades    25 wins, 6 losses    80.6% win rate    −$9.05 total
                                                    −$0.29 average per trade
```

An 80.6% win rate that lost nine dollars. A win paid **+$0.05**; a loss cost
about **$1.90**. This is the clearest possible illustration of section 5, taken
from your own record.

---

## 8. Where everything lives

| what | file |
|---|---|
| the 130 formulas in the registry | `backtest_report.py` → `SIGNALS` |
| most formulas | `signals_ext.py`, `signals_ext2.py` |
| the combination rules (`cf_*`) | `signals_conf.py` |
| the non-linear rules (`cx_*`) | `signals_cascade.py` |
| the original seven, incl. `fade15` | `auto_trader.py` |
| what is deployed right now | `~/.tradingagents/auto_trade.json` |
| every deploy, arm and disarm | `~/.tradingagents/deployments.jsonl` |
| every trade and every refusal | `~/.tradingagents/auto_trade_ledger.jsonl` |
| the gates a trade must clear | `auto_trader.py` → `_entry_gate`, `edge_check` |
| the stake | `auto_trader.py` → `staked_margin` |

**Of the 130 formulas in the registry you run 16.** The other 114 are measured
and searchable in Stored strategies but are not deployed.
