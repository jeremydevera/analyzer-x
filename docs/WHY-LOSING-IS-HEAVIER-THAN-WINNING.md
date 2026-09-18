# Why losing is heavier than winning

The operator, `Sep 19, 2026`:

> *"when i lose a trade even in with same tp and sl why losing is much heavier
> i mean when i win for 5 margin i only win +0.98 but when i lose its -1.5
> something"*

They are right, the numbers are real, and nothing is broken.

## The short answer

**The cost of trading is taken off you whether you win or lose.** It is
subtracted from a win and added to a loss, so the same price move pays you less
than it costs you.

## Measured on their own trades

Every trade below is $5 of their money at 20x — so **$100 of coin is moving** —
taken from `auto_trade_ledger.jsonl` by matching each exit to the entry that
opened it.

| when | coin | price move | what the move was worth | what they actually got | cost |
|---|---|---|---|---|---|
| Sep 18, 2026 10:50pm | KKRSTOCK | +1.00% | $1.00 | **+$0.55** | $0.45 |
| Sep 18, 2026 4:06pm | GPNSTOCK | +0.60% | $0.60 | **+$0.15** | $0.45 |
| Sep 19, 2026 12:25am | KKRSTOCK | +0.50% | $0.50 | **+$0.15** | $0.35 |
| Sep 18, 2026 4:38am | VUG | +0.40% | $0.40 | **+$0.07** | $0.33 |

The cost is **$0.33–$0.45 on every trade**, and it does not care which way the
price went.

So on a 1.2% target with a 1.2% stop, on $100 of coin:

```
the move is worth $1.20 either way

YOU WIN   $1.20  -  $0.42  =  +$0.98
YOU LOSE  $1.20  +  $0.42  =  -$1.62
                              ^^^^^^ a $0.64 gap on an identical move
```

The `willr14_15m_sl12tp12` rows in their record show exactly this: the price
move is **±1.20% on every single trade**, and the money is +0.98 against
−1.62.

## What it costs them, and the number that matters

With an equal target and stop, the cost alone decides how often they must be
right just to stand still:

```
break-even win rate = loss / (win + loss)
                    = 1.62 / (0.98 + 1.62)
                    = 62.3%
```

Checked over 100 trades: 62.3 wins x $0.98 = +$61.06, and 37.7 losses x $1.62 =
−$61.06. Exactly zero.

**So a strategy with a 1.2% target and a 1.2% stop must win 63 times in 100
before it makes a single dollar.** A 50% win rate on equal barriers is not
break-even — it is a steady loss of about $0.32 per trade.

## Where the cost comes from

Three charges, all on the way in AND the way out:

* **the exchange's cut** — different per coin. Tokenized stocks like KKRSTOCK
  and GPNSTOCK are the expensive end; XAUT is roughly a tenth of it.
* **the spread** — the gap between what buyers offer and sellers ask. Half is
  paid entering, half leaving.
* **slippage** — the price moving between deciding and filling.

And for anything held overnight there is a fourth, **funding**, charged every
few hours while the trade is open.

## What to do about it

* **A wider target makes the cost a smaller slice of the prize.** The same
  $0.42 against a $1.20 target is 35% of it; against a $3.00 target it is 14%.
* **Cheaper coins keep more of the move.** This is why the cost is measured per
  contract and never averaged (CLAUDE.md rule 10).
* **Judge a strategy against its OWN break-even win rate**, not against 50%.

## Related

* `CLAUDE.md` — trading-cost rules 9-11, and `docs/INCIDENT-2026-08-12-BDX.md`,
  where a coin's round-trip cost was **734%** of its target and no trade could
  ever have won.
* The backtest already charges all of this (`auto_trader.backtest_strategy`
  charges fee, slippage and funding), so a stored row's profit is after costs —
  the surprise is only in how big the gap between a win and a loss is.

## A correction, recorded on purpose

In the chat answer that preceded this file the break-even figure was given as
**57%**. That was wrong; it is **62.3%**. The error was solving
`p(m-c) = (1-p)(m+c)` for the move `m` rather than for the amounts actually
won and lost. The right form is the simple one above: **loss / (win + loss)**.
