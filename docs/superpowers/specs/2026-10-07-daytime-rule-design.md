# The daytime rule — a room switches on only what kept winning in hours it can trade

Date: Oct 07, 2026. Status: approved design (trial on #4FC03172).

## What the operator asked

* *"so what do you think is the correct, because its seems like i cannot rely
  on winrate for past 30 days"* — after #4FC03172 won 9 of 40 practice trades
  on the night of Oct 06, 2026 (−$22.12), every one opened 7pm–3am New York.
* Shown the walk-forward test below and asked whether to build its best rule
  as a room rule and try it on one practice room first: **"yes"**; trial room:
  **#4FC03172**.

## What was measured (Oct 07, 2026)

Walk-forward over 20,604 saved Backtest v2 trade lists (minute-exact, $5 x 20x,
fees taken off), picks made on 16 days Sep 17 – Oct 02, 2026, each followed for
the next 3 days, counting only trades the practice account can take (crypto,
and stock tokens entered 9:30am–4pm New York) and each move once. Two analysts
built it independently and agree to the cent; a checker re-ran it.

| rule | bets | won | profit | per $100 bet |
|---|---|---|---|---|
| today's (70%+ over 30 days, 50+ trades, TP > SL) | 14,010 | 53.4% | −$672.37 | −$0.05 |
| **daytime rule** (today's + the three checks below) | 1,655 | 60.1% | +$394.82 | +$0.24 (16 of 16 days green) |
| random picking | 207,557 | 34.3% | −$30,469.01 | −$0.15 |

The sample was chosen with hindsight, so the real gain is likely smaller.

## The rule

On top of the room's own line (win rate, window, minimum trades, TP > SL,
max SL — unchanged), a strategy is switched on only when ALL hold:

1. **Pays a loss after fees:** (TP − fee) ≥ (SL + fee), fee = the row's own
   round-trip cost (`rt`, else `cost_of_tp`% of TP). Unknown fee fails.
2. **Daytime record (stock tokens only):** over the last 30 days of its trade
   list, its trades ENTERED 9:30am–4pm New York, Mon–Fri, number ≥ 20 and win
   ≥ the room's line (70%). Crypto: skipped.
3. **Still winning:** over the last 7 days of its trade list (for stock tokens,
   daytime trades only), ≥ 5 trades and win ≥ the room's line.

Windows end at the list's own last candle (`end_ms`), never later than now.
The lists are `room_replay.build_lists` (Backtest v2, minute-exact, cached by
input stamp — the same lists Backtest a room uses), built only for strategies
that already pass the room's line and check 1.

**Daily, at the switch-on pass:** passers not running are switched on (as
today); RUNNING watcher rows that are candidates of the line but fail a check
are switched OFF, with the check named. Switch-off between passes stays as it
is (hourly, the room's window win rate, its TP rule).

**The runner:** in a room with the rule, a stock-token strategy never opens a
trade outside 9:30am–4pm New York, Mon–Fri. The candle is marked seen (so it
is not re-read every cycle), the cost check is not called, and one ledger row
an hour per room says how many were skipped (`market_closed`).

**Backtest a room:** follows the same rule from the moment the rule was
switched on — a stock-token backtest entry outside those hours is masked.

## Where it lives

* `tradingagents/daytime_rule.py` — pure checks (market hours, stock token,
  pays-a-loss, the list checks) + `screen(rows, cfg, now)`.
* Room settings: `"daytime_rule": {"since": <epoch s>}` — one flag, read by the
  watcher (`_on_pass`), the runner (entry loop) and `room_replay` (follow mask).
* No new GitHub work, no index columns, no change to other rooms.

## Out of scope

Other rooms; real money; Forecast v2 research grids (they do not know this rule
yet — a rules-mode replay of #4FC03172 is not the daytime rule; follow mode is).
