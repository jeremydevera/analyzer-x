# A "cheap coins only" switch for the switch-on rules — design

Date: Nov 13, 2026. Short design (a small change), approaches decided in the conversation.

## Why

The operator, Nov 13, 2026: *"can you check my existing backtest v4 and given the data i want you to look
for improvement so i can profit more"*, then *"use superpower on what's the best approach to fix this"*
and *"what's your decision to your question"* (the pick was handed to Claude).

What the check found, on the store of Nov 12, 2026 7:33pm (242,283 strategies, 7,719,883 trades, $5 x 20x
= $100 of coin a trade, each strategy judged on the days it was NOT chosen on):

* Before costs the unseen trades break even (+$0.08 a trade); costs average $1.14 a trade. Costs are the
  whole loss (unseen −$1.06 a trade, −$2,664,768).
* A quarter of the unseen trades paid over $1 each ($3.44 on average) and made $1.80M of the $2.66M loss.
* Coins whose round trip costs $0.25 or less per $100: −$0.22 a trade unseen (older days −$0.07), and the
  loss shrinks band by band as the cost falls, in both periods. The one robust improvement found.
* Picking past winners did NOT help (cheap coins, made money before: −$0.34 vs −$0.22); shorts only and
  "with Bitcoin's 50-day trend" fell apart under checks (the trend flips with a 100/200-day average; one
  coin, AKE, carried it).

Today nothing stops a skill room from switching on an expensive coin: #D7EN8BNV's list of Nov 13, 2026
holds SOL 15m #CQ5B9G7V (about $0.16 a round trip) beside CHEEMS 15m #WHSTLP8E (about $0.54).

## Approaches

1. **A switch on the rule sets, walked forward (PICKED).** Every Forecast v4 rule set is walked twice:
   as it is, and skipping strategies whose coin costs more than $0.25 a round trip — the way "stop 1.5% or
   tighter" already works. The picker hands a room the cheap version only if it passes the same test as
   any rule set. Nothing changes until the walk shows it helps. Costs: the nightly forecast takes about
   twice as long (122 s now, about 4 minutes), the picker lab longer.
2. A hard ceiling: no room ever switches on a coin over $0.25. Simplest, but the line was drawn on one
   look at the data and it silently changes what every existing rule id means.
3. The runner's own order-book check at each trade's minute in the skill rooms. Most exact, but a much
   bigger build, and the skill backtest would have to learn it too (named as not built on the rooms).

Claude's pick, handed over by the operator: 1 — it uses the tested path the picker already trusts and
cannot make the rooms worse without the walk showing it.

## What gets built

* **The cost of a strategy** = $100 x (2 x its fee + 2 x its coin's gap), from the store row's own `fee`
  and `slip` — the numbers its trades were charged. Since Nov 13, 2026 the gap is the coin's usual gap
  (the median of 30 days of recorded minutes, `skill_bt.usual_gap`).
* **One cap value: $0.25** (`forecast_v4.COST_CAPS = (0.0, 0.25)`; 0 = no cap). One value only, so the
  grid doubles and no more.
* **Forecast v4** (`forecast_v4.py`): the walk's kind loop gains the cap beside the stop cap; `rule_id`
  adds `|cost=0.25` ONLY when a cap is set, so every existing id (#D7EN8BNV, #KK9SRY28, #CKVS7G7Z ...) stays
  the same; `rule_words` adds "on coins costing $0.25 or less a round trip"; `switched_on` gets the same
  condition in its SQL (held equal to the walk by the existing test, extended); `rules_page` gets a
  `cost` filter (any / cheap only / no cap); the calendar files carry each strategy's cap flag so
  `_takes` and the day list follow it.
* **The picker and the rooms**: `v4_picker._rule_of` carries `cost_cap`, so a room given a capped rule
  set gets daily lists without expensive coins (`v4_daily` already builds lists through `switched_on`);
  the picker lab's kind key includes it. The rule's words on the room tab say it.
* **The page**: a "coins" filter on Best switch-on rules; the rule words carry the cap.

## Not in it

No hard ban (approach 2), no per-minute order-book check (approach 3), no change to the picker's test,
no new room, nothing switched on by hand. Real money is untouched (skill rooms are practice only).

## Known simplification, said on the page

The walk judges every past day with the coin's cost as measured by the nightly run (its usual gap then),
not the cost that day. Costs change slowly, but a coin that got cheaper or dearer lately is judged by
today's cost.

## How it is judged

The store of Nov 12, 2026 still priced each coin from ONE reading of the book (RCA-2026-11-12-B), so the
first fair comparison is the forecast built after the Nov 13, 2026 7:05pm refresh. Success: cheap
versions of the leading rule sets beat their uncapped twins on worst month and on profit a trade in Best
switch-on rules, and the picker lab's rooms do better with them available. If they do not, nothing
changes — the picker simply keeps choosing uncapped rule sets.

## Tests

Existing ids unchanged; a capped rule set never switches on a strategy over the cap; `switched_on` equals
the walk for capped rule sets; the calendar's day list equals its box for capped rule sets; the picker
carries `cost_cap` into the room's daily list; the page filters by it on the server.
