---
name: deploy-by-id
description: ALWAYS ON whenever the operator names a row id to deploy, arm, or read back — "deploy #DM84QDSZ", "make these live", a pasted list of ids, or any screen that prints an id beside a trade. A row id names ONE combination INCLUDING ITS COIN. Never group several coins under one id, and never label a trade with an id belonging to a different contract.
---

# One id, one coin — always

The operator, `Sep 16, 2026`, looking at their own live history:

> *"WHY IS #DM84QDSZ IN LIVE TRADE HAVE DIFFERENT COINS?"*

and then:

> *"I DEPLOY SAID DEPLOY AND ID BUT IT HAS DIFFERNT COINS THEN DEPLOY THE ID,
> DONT GROUP THEM AS ONE"*

## What went wrong, in their numbers

`#DM84QDSZ` is **DVNSTOCK 30m willr14, SL 2.00% / TP 0.50%, flat — 168
trades, 97.62%, +$36.72**. They pasted 280 ids; the deploy turned them into
**83 strategy keys**, because a key is `signal_timeframe_slXtpY` and the COIN
is not in it. `willr14_30m_sl2tp05` ended up armed on five contracts:

| coin | its own row id |
|---|---|
| DVNSTOCK | **#DM84QDSZ** |
| FASTSTOCK | #7BSMBRFA |
| KKRSTOCK | #DGCSMB9N |
| ROLSTOCK | #MU2AU5P6 |
| VUG | #GXTHE8EJ |

The screen then built the id from the strategy's FIRST coin, so a FASTSTOCK
trade was stamped `#DM84QDSZ` — an id that belongs to a different contract.
Four labels in five were wrong about the coin.

## The rule

**A row id is `coin + timeframe + signal + threshold + SL + TP + sizing`.**
`backtest_report.row_code` hashes all seven. Drop the coin and it is no
longer that row — it is a different measurement with the same name.

1. **Deploying N ids deploys N rows.** If two ids share a strategy key, that
   is an implementation detail of the key, not permission to merge them. The
   operator chose rows; the count they get back must equal the count they
   gave, minus whatever was refused BY NAME.
2. **Every id printed beside a trade is computed from THAT trade's coin.**
   Never from the strategy's first coin, never from a list, never from the
   settings' ordering. `row_id_for(key, coin)` takes the coin for a reason.
3. **A refusal is named with its id.** "13 dropped" sends them to a log;
   "#LG9NSU4B XPIN 1h ote — 4.00% stop past the liquidation wall" is a fact
   they can act on.
4. **Read the ids back before writing anything** (CLAUDE.md rule 22). Coin,
   timeframe, signal, TP, SL, sizing and profit — the six fields plus the
   contract. Their "this" and yours were different rows once already.

## The check — run all four before saying deployed

```python
# 1. every id resolves, and to exactly one row
ri.query(row_id=one_id)          # total == 1

# 2. the count survives the round trip
len(deployed_pairs) == len(ids_given) - len(refused_by_name)

# 3. every deployed pair's id is the id that was asked for
api.row_id_for(key, coin, settings) == that_row_id

# 4. the screen agrees, per trade, on the coin it actually traded
/api/trade/history -> row.strategy_id == row_id_for(key, row.coin)
```

## Red flags

| Thought | Reality |
|---|---|
| "These ids are the same strategy" | They are the same KEY. The coin is part of the row |
| "I'll label it with the first coin" | That is the bug this skill exists for |
| "280 ids became 83 strategies, fine" | Say so out loud, with the coin count, before writing |
| "The id is close enough to identify it" | An id deployed the wrong config on 2026-08-17 |

## Why it matters beyond the label

The operator picks what to trade by id, and judges it by id afterwards. An
id that names the wrong contract breaks both halves: they cannot tell which
row made the money, and they cannot re-run the measurement that justified it.
Same family as the live/demo `trade_id` collision found the same night — one
label standing for several different things.
