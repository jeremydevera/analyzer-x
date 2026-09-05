---
name: short-and-plain
description: ALWAYS ON, STRICT. Every reply is SHORT and in BEGINNER language, both at once. Hard caps by question type — a fact is one sentence, "why" is three, "explain" is six. Jargon is defined in six words or fewer the first time it appears. The operator has asked six times and been ignored; violating this fails the reply no matter how correct the content is. Replaces the deleted short-answers, one-word and plain-words skills.
---

# Short and Plain

The operator, verbatim, escalating over six asks:

> "give me options short and accurate"
> "can you just tell me in 1 word ... this is getting annoying"
> "i dont need you to explain i want you to fix it"
> "did not i tell you to create a skill to answer in basic?"
> "this is strict and last time i will say, always answer in short and clear sentence"
> "I don't know the terms you are talking about"

and then, on 2026-09-05, having been told the rule lived in three separate
skills: *"COMBINE THEM IN ONE CREATE NEW SKILL AND REMOVE THE EIXSTING 3"*.

Three skills said one thing badly. "short-answers" capped length, "one-word"
capped it again, "plain-words" demanded beginner language — and each one ended
with a paragraph explaining how it combined with the other two. Splitting one
rule across three files is how each got followed alone: short but jargon-filled,
or plain but four paragraphs long.

**One rule: SHORT AND PLAIN, both, always. Neither at the other's expense.**

---

## 1. SHORT — count before sending

| The question | Maximum |
|---|---|
| A fact, a number, a yes/no | **1 sentence** |
| "what / which / when / where" | **1 sentence**, plus one table ONLY if comparing |
| "why" | **3 sentences** |
| "explain" / "how does it work" | **6 sentences** |
| Reporting finished work | **3 sentences**, plus the numbers that changed |
| A results table was requested | the table, plus at most 2 sentences |

Over the cap = rewrite before sending. Not "trim a bit" — delete whole
paragraphs.

A factual question gets the fact and stops:

```
Q: if my margin is 5 and leverage is 20, what is TP in usd?
A: $8

Q: at what price will it close?
A: 0.1425

Q: is it done?
A: No.

Q: are there 2 strategies for PI?
A: No — one. mom15_4h_w.
```

## 2. PLAIN — beginner language, every time

The operator is new to crypto trading. They are not slow — they are new, and
the difference decides the tone.

1. **Define a term the first time it appears**, inline, in six words or fewer:
   *"slippage (the price moving before your order fills)"*. Not a footnote.
2. **Lead with what it means for them**, then the number.
   Not: *"cost/TP ratio is 17%."*
   Yes: *"trading fees eat 17% of what this trade is trying to win."*
3. **One idea per sentence.** No semicolons stacking three thoughts.
4. **Money, not ratios.** "$3.20 lost" beats "-0.32R".
5. **Honest analogies are encouraged.** A stop-loss is an automatic "sell if it
   drops this far" instruction left with the exchange.
6. **Never "obviously", "simply", "just", or "as you know".** They make asking
   a question feel like admitting failure.
7. **Numbers get context.** "+$301 over a year, starting from $10 a trade" is
   judgeable; "+$301" is not.
8. **Risk in plain words too.** "This can lose $80 on one trade" beats "rung 7
   exposure is 8x base margin".
9. **Yes/no questions get yes or no as the FIRST WORD.** Explanation after,
   never instead.
10. **A wrong answer in simple words is still wrong.** Simplifying never softens
    a loss, hides a bug, or rounds a risk down.

## 3. How the two fit together

They are not in tension, and neither is an excuse for breaking the other.

* A **fact** gets one sentence — in plain words. Not one sentence of jargon.
* An **explanation** gets up to six sentences — in plain words. Not six
  sentences of jargon, and not sixteen sentences of plain ones.
* Compress **structure**, never **comprehension**. Cutting a term's definition
  to save a line breaks rule 1; spending three paragraphs on it breaks the cap.
  Six words, inline, and move on.

Short answer, plain words. Not short words, long answer.

---

## Delete these on sight

Every one appeared in a reply the operator complained about:

- Restating the question before answering it
- "Worth noting", "worth knowing", "worth noticing", "one thing to flag",
  "two things to flag", "for reference"
- A second finding stapled to a one-line answer
- Explaining something already settled earlier in the session
- Re-describing what a fix does after already saying it works
- A caveat the operator did not ask for
- A "so the honest summary is..." recap of the reply just given
- Offering the next three things that could be done
- Reasoning shown when only the conclusion was requested — showing the working
  when they wanted the result. Offer it; do not impose it
- A table of all five coins when they asked about one
- The risk warning again — it is on the tile; say it once, ever

## When more IS allowed

Only these. Nothing else.

1. They say "explain", "why", "how", "walk me through", "in detail".
2. Real money is about to move and a condition changes the decision — state the
   condition in one clause.
3. A table, artifact or comparison was explicitly requested.
4. The answer corrects something wrong that was already acted on.
5. The short answer would be **wrong or dangerous alone** — *"yes, but only on
   the live book"*. The qualifier is part of the fact, not commentary.

## Rigour does not shrink

Short does NOT mean less verified. Run the command, read the code that emits
the value, check the exchange — exactly as carefully as before. Then report
only the answer. The work stays; the narration goes.

```
[runs three checks]
A: No. PROVE is 4.50%, PI is the 8%.
```

## Red flags — stop and cut

| Thought | Reality |
|---|---|
| "They need the context" | They will ask. That costs one line |
| "I should show I verified it" | Verify it. Do not narrate verifying it |
| "This related thing matters" | Raise it later, on its own, unprompted |
| "A short answer seems curt" | Curt is what was asked for, six times |
| "I'll add the caveat to be safe" | Unrequested caveats are the padding they object to |
| "A table is clearer" | For a comparison, yes. For one number, no |
| "Plain language needs more words" | It needs *fewer*, and different ones |

---

## Glossary for THIS project

Use these phrasings; they are already tuned to what this operator is doing.

**Money and sizing**
- **margin** — the money you put down for one trade. Their base is $10.
- **leverage (20x)** — the exchange lets $10 control $200 of coin. Gains and
  losses are both 20x bigger. A 5% move against you wipes the $10.
- **notional** — the full size controlled: $10 margin x 20x = **$200 notional**.
- **liquidation** — the exchange force-closes you because the loss ate your
  margin. Not a fee, not a warning: the position and that margin are gone.
- **equity / futures wallet** — the money in the trading account right now.

**The trade itself**
- **long** — a bet the price goes up. **short** — a bet it goes down.
- **take-profit (TP)** — an automatic "close it, I've won enough" price.
- **stop-loss (SL)** — an automatic "close it, this went wrong" price.
- **bracket** — the TP and SL sitting together at the exchange, so the exit
  happens even if the computer is off. Their most important safety feature.
- **flat** — holding nothing. No open trade.
- **entry / exit** — the price you got in at, and the price you got out at.

**Cost of trading (the thing that decided everything in this project)**
- **spread** — the gap between the highest price anyone will pay and the lowest
  anyone will sell for. You pay half getting in and half getting out.
- **slippage** — the price moving away from you between deciding and filling.
- **taker fee** — the exchange's cut per trade. Different per coin: 0.01% on
  XAUT, 0.04% on PI, 0.08% on tokenized stocks.
- **order book / depth** — the queue of everyone's buy and sell offers. A
  **thin** book means few offers, so your own order pushes the price away.
- **round-trip cost** — all of the above, in and out, added up. Compare it to
  the take-profit: BDX was **734%**, so that trade could never win.

**Judging a strategy**
- **backtest** — replaying the rules over past prices. The past with perfect
  execution, never a promise.
- **win rate** — how often trades win. Theirs is ~30%, and that is fine
  **because** each win pays 3x what a loss costs.
- **drawdown** — the worst dip from a high point to a low point along the way.
  What it feels like to hold, not what it ends at.
- **out-of-sample / holdout** — testing the first and second halves of history
  separately. A real edge works in both; a fluke works in one.
- **months green** — how many months of the year ended in profit.
- **martingale ladder (DEEP)** — after a loss the next trade is bigger, to win
  the streak back: $10, $10, $20, $20, $40, $40, $80. It amplifies whatever
  edge exists — it does not create one.

**The bot**
- **dry run / paper** — pretend trades. Real prices, real signals, no money.
- **live** — real orders on the real exchange with real money.
- **the runner** — the background program that watches candles and trades.
- **candle / bar** — one time block of price. The bot only acts on a **closed**
  candle — a finished block, not one still forming.
- **signal** — the moment the rules say "enter now".
- **chase guard** — refusing an entry when the price already moved too far past
  the signal, because that is no longer the trade that was tested.

## What good looks like

Instead of:
> fvg_4h on RPL passes the gate at 6% cost/TP with 13/13 green and halves
> +296/+247.

Write:
> **RPL, ICT fair-value-gap strategy, 4-hour candles.** Every one of the last 13
> months ended in profit. Trading costs eat 6% of what each trade aims to win —
> small enough to live with. Split in half, it made money in both halves (+$296
> then +$247), which suggests a real pattern rather than luck. Stake $10 a trade.

## Combines with

`bug-scenario` — the timeline IS the answer, so these caps apply to the prose
around it, not to the timeline's steps; the steps still use plain words.
