---
name: feedcheck
description: Read the runner feed/log/ledger and say what is NORMAL and what is a BUG, with the evidence. Use when the operator asks "is the runner ok", "what are these lines", "why no trades", or pastes feed lines. Built from this repo's real incidents.
---

# feedcheck — what the feed is saying, and what is actually a bug

RULE ONE: read the emitter, not the label (CLAUDE.md rule 23). Before calling
any line a bug, open the code that writes it. Every wrong diagnosis this repo
has paid for started with reading a line's NAME instead of its WRITER.

## Step 0 — the window report (always first)

```bash
.venv/Scripts/python -m tradingagents.feedcheck
```

It reports everything SINCE THE LAST FEEDCHECK (first run: 24 hours): trades
opened and closed per book, wins and losses with the reasons, every refused
entry grouped by reason, and an EMERGENCY list of things that should not have
happened (a stop that could not rest, a position without its stop, an exit the
strategy did not make itself, a second real position on one coin, the dead
nine-hour-freeze guard firing). It then writes a `feedcheck` marker row into
the ledger, so the next run starts where this one ended. The marker is not a
trade — no record, P&L or reset counts it.

Report those numbers to the operator FIRST, then run the checks below.

## The checks, in order

1. **Is the runner alive?** `at.runner_pid()` and the log's mtime. A pid file
   with a DEAD pid = it started and died (that happened 3x on 2026-09-04: the
   venv launcher pid bug).
2. **Is it doing anything?** Ledger actions in the last 15–30 min
   (`Counter(r["action"])`). Cycles running + ZERO entries for hours needs a
   reason you can name — on 2026-09-04 it was 548 `blocked` rows and a dead
   guard, nine hours, no trades.
3. **Is the FEED itself broken?** `/api/trade/log` answering 500 while the
   runner is healthy happened on 2026-09-05: ONE cp1252 byte (0x97) in the
   log. An empty feed is NOT a dead runner — check the pid before concluding.
4. **Pair the books.** Same strategy, same second, live vs demo: entries more
   than ~0.2% apart or opposite outcomes = the price/fill split (fixed
   2026-09-05 with the shared per-cycle price; if it reappears, that fix
   regressed).
5. **Count repeats.** The SAME line more than ~5x per hour is a silence, not
   a message (548 `blocked`, the HH:30 `stale_skip` flood). Either the cause
   is stuck or the line needs `_say_once`.

## Line-by-line: normal or bug

| line / action | meaning | bug? |
|---|---|---|
| `scan X: ... no signal or waiting for a new candle` | looked, nothing to do | normal |
| `gate_blocked` (cost vs target) | the cost gate refused a trade — protection working | normal; a BUG only if the same coin ALSO trades live seconds later (cache let it through — fixed with the entry-time last look, 2026-09-05) |
| `gate_blocked ... at_entry: true` | the fresh last-look refused right before a real order | normal |
| `stale_skip` | the candle closed too long ago (limit 30 min). Happens at startup and after sleep | normal in bursts at startup; a bug if it repeats every cycle at HH:30 (the quiet-bar-not-marked-seen bug, fixed 2026-08-18) |
| `coin_busy` | one strategy holds the coin; others wait — the operator's own rule | normal, once per bar |
| `chase_skip` | price ran away from the signal before entry | normal |
| `blocked: coin enabled on multiple timeframes` | a DEAD guard — removed 2026-09-05 after it froze everything for 9 hours | ALWAYS a bug if seen again |
| `forced_close ... stop unplaceable (5003)` | the stop was already passed when placed — spread wider than the stop | BUG CLASS: cost the operator $5.36 on 2026-09-05. The spread-vs-SL gate should have refused it first |
| `bracket_failed ... 2009` | tried to protect a position that was already gone | follows a 5003 forced close; investigate the pair |
| `live_disarmed` / `loss_limit_stop` | the loss cap switched LIVE off; demo keeps running | normal — by design |
| `another auto-trader is already running (pid X)` | duplicate start refused | normal IF pid X is alive; a BUG if X is dead or is the runner's own parent (the launcher-pid bug, fixed 2026-09-04) |
| `record_reset` / `loss_cap_reset` | the operator pressed a reset button | normal |
| `order_failed` / `size_failed` / `no_price_skip` | venue refused or gave no data; the candle is retried | normal once; a bug if every cycle |
| `enter` with no matching `exit` and no open position in state | a lost position record | BUG — check state vs `fx.open_positions()` (rule 14) |
| `�` replacement marks in lines | a process wrote non-UTF8 bytes | cosmetic; the writer should set PYTHONUTF8 |

## Numbers that decide

- entries==0 for hours is only OK when the ledger SAYS why (gate, stale,
  busy, market closed for tokenised stocks). No reason on file = bug.
- demo wins where live loses on the SAME signal = fill/price split. Compare
  the paired `enter` rows' prices.
- `pnl_today(dry=False)` vs MEXC `position_history`: more than a few cents
  apart = the record drifted from the exchange (rule 14: the exchange is the
  truth).

## Report format

Per bug-scenario: a numbered timeline with real times and dollars, then one
line each for why, cost, and fixed-or-not. Anything that never fired is
labelled "NEVER HAPPENED YET". Keep the words basic (short-and-plain).
