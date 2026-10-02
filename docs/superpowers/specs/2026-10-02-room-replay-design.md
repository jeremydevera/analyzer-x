# Backtest a room = replay the room's own rules, day by day

**Asked, Oct 02, 2026** (verbatim, docs/OPERATOR-ASKS.md): *"when i backtest 6B08FF64
here's the result, but in my auto trade its -14.45 all time for practice"*, then *"it should
be the same, you are saying the backtest room does not calculate? i thought that's the feature
of backtest room"*, then *"backtest room should like backtest for the room strategy example —
what strategies did switched on and off for Sept 3, 4, 5, 6, 7 and so on"*, then, on how to
settle trades: *"the strategies deployed (not the room strategy) has its own id, and has its
own row why dont you use it?"* and *"you should be using the backtest rows because this is
the source of truth for example in backtest when you click a specific id, it will show the
rows of its trade made, that's where you should look"*. Choices made the same day: cost limit
**same as live (up to 50% of the target)**; **replace "Backtest a room"**. Then *"go start use
harddev, then report to me what was blocker, bugs aloong dev, and anything i need to know if
there is data discrepancy that will happen"*.

## What it is

For a room (profiles.BUILTIN, e.g. #6B08FF64: 15-day window, on/off at 80%, min 30 trades,
TP > SL, stop ≤ 2%, raw) and a date range, replay the room's watcher rules over time:

1. **Every decision uses only what was known at that moment**: a strategy's win rate and trade
   count over the room's window, counted from trades that had CLOSED by then.
2. **The source of truth for every strategy is its own Backtest v2 trade list** — exactly the
   rows shown when the operator clicks that id in Backtest v2: `market_sweep.trades_for(coin,
   tf, signal=, th=, sl=, tp=, sizing="flat", base_margin=5.0, store=stores.V2)`. The same list
   decides switch-on/off AND supplies the profit. No other engine, no bar-rule replay data.
3. **Switch-off and switch-on follow the live schedule** of `strategy_watcher` for that room
   (read `OFF_EVERY_S`, `_on_due`, raw vs non-raw) — mirrored, not invented. The rules come from
   `watcher_policy` (`judge`, `passes_on`, `pick`, the room's `rules`), the same functions the
   live watcher and `watcher_replay.simulate` use. Extend `watcher_replay.simulate` (e.g. a
   step / schedule argument; existing callers keep their behaviour byte for byte) rather than
   writing a second rule engine.
4. **Candidates**: every Backtest v2 row that can ever pass the room's switch-on line inside the
   stored span — TP > SL, SL ≤ the room's max_sl, cost_of_tp < 50 (live's block line), flat,
   res 1m, trades ≥ min_trades and wins ≥ ceil(on_winrate × min_trades). All groups (classic,
   preset, Sep 25 Strat lx_, Sep 27 ML ml_). Count them and print the count.
5. **Output, saved** (under `~/.tradingagents/v2/room_replay/<room>/`, G drive): per day — the
   strategies switched ON (id, coin, tf, signal, TP, SL, win rate and trade count that day, why),
   switched OFF (id, why), running count, trades closed, wins, losses, profit, running total,
   worst losing streak; per strategy — its on/off stretches and its trades; a summary.
6. **Practice beside it, from the room's first day (Oct 01, 2026)**: every practice trade the
   room really closed in the range, INCLUDING strategies switched off since (their on/off
   stretches from the room's `deployments.jsonl` / watcher log — see `forecast_v2._intervals`),
   so the practice total equals the auto-trade screen's total for the same dates.
7. **Reconcile, out loud**, per day and in total: backtest-only trades, practice-only trades, the
   same trade ending differently, trades the live cost check refused (the room's `gate_blocked`
   records, as `room_backtest._practice_exits` reads them), trades after the backtest's last
   candle.

## Data limits (must be printed on the screen, never hidden)

- The trade lists come from this PC's 1-minute candles (`~/.tradingagents/v2/candles`), which
  begin about **Aug 17, 2026**. A day is fully judged only when the room's whole window lies
  inside that span: 15-day rooms from about Sep 01, 30-day rooms from about Sep 16. Earlier days
  are judged on fewer days and say so.
- Candidates are bounded by the stored rows' last-30-day counts; a strategy that was strong
  only before that span cannot be nominated. Say so.
- The live cost check at each entry (spread at that moment) and the switch-on cost read for
  non-raw rooms cannot be replayed for past days; only recorded refusals (from Oct 01) can be
  matched. Say so.

## Screen

Replaces "Backtest a room" (Forecast v1 page; current code tradingagents/room_backtest.py, its
API route, its webapp component). Room + from/to pickers; a provenance line (room rules, $5 ×
20x, candidates measured, data span, backtest's last candle); a per-day table (date, switched
on, switched off, running, trades, wins, losses, win rate, profit, running total, worst losing
streak) with the practice columns beside it from Oct 01; click a day → its switch events with
reasons and its trades; totals row; the reconciliation lines. Dates via `fmtWhen`. Every label
derived from its data (label-must-match-data). Filters/paging on the server, never in the page.

## Also fix (found while mapping, real defect → RCA entry)

`watcher_policy.pick` / `judge` (watcher_policy.py ~120-131) and `replay_page.py` (~273, 386,
389) write "30 days" whatever the room's window — #6B08FF64's live watcher log says "91.18%
over 68 trades in the last 30 days" for a 15-day count. Derive the words from `window_days`.

## Rules that bind every change

CLAUDE.md: commit via `python scripts/commit_own.py -F msg.txt <paths>` (other sessions share
the tree), push, RCA entry with any bug fix, dates via fmt_when/fmtWhen, big files on G, nothing
below `if __name__ == "__main__":`, test the path the real caller takes, harddev loop.
