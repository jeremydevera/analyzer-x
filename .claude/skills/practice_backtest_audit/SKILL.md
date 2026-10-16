---
name: practice_backtest_audit
description: Use when the operator asks to audit practice trades against the backtest, to run "practice_backtest_audit", or asks whether practice trades match their stored backtest rows. Drives the real screens in Chrome (Auto Trade -> Main -> DEMO, then Backtest -> Stored strategies -> Filters -> #id) and compares each practice trade's profit with its nearest backtest trade.
---

# practice_backtest_audit

The operator, Oct 14, 2026, word for word:

> i want you to do some playwright automation skill name it 'practice_backtest_audit'
> 1. Navigate to Auto trade tab ->Click Auto trade
> 2. Click main
> 3. Then copy the following in each row 1 by 1: Strategy -> column copy  the ids, exclude the #  , (take note you will only get the ids of the ones you haven't get yet, so for example i ran this skill Oct 12, and then i ran it now, what i want is you will get the ids from Oct 12 until present) then copy the opened column, closed column, held column, profit$ column
> 4. Once done copying the ids go to Backtest tab
> 5. Click Filters button under Stored strategies section
> 6. Uncheck 'TP is equal to or greater than SL'
> 7. In #id field -> paste the ids one by one from step3
> 8. Click Apply filters
> 9. Wait for the table to load
> 10. Once there is result proceed to step 11, if no  results inform me how many ids and what are the ids
> 11. Click the result in the row
> 12. Find its nearset equivalent trade based on Open Column and Closed Column from Step 3 then report me if the profit is accurate, for example in step 3 the profit is 10.6 then here its 10.8 -> this is considered close but its its like 100, then its not close and if there is no equivalent result then report it back to me

Design they approved (same day): the practice list is the Main tab's
**DEMO — simulated** book; "new since last run" means trades CLOSED after
the last run's newest trade; the first run starts at the move to Gate
(Oct 10, 2026 3:59am, older ids were measured on MEXC); each id is searched
ONCE even when several practice trades carry it; **close** = same result and
within 10% or $0.10, **not close** = a bigger gap or one side won while the
other lost, **no equivalent** = no backtest trade opened near it.

## Run it

```bash
cd .claude/skills/practice_backtest_audit/scripts
npm install            # first time only: playwright-core, no browser download
node audit.mjs --day yesterday          # trades closed yesterday (local day)
node audit.mjs                          # everything closed since the last run
node audit.mjs --since "Oct 12, 2026 12:00am" --until "Oct 14, 2026 12:00am"
```

Options: `--base` (default `http://localhost:8503`), `--chrome` (Chrome's
path), `--open-tolerance` minutes (default 10: how far apart the two opened
times may be and still be the same trade), `--headed` to watch it.

It writes `~/.tradingagents/practice_backtest_audit/runs/<yyyy-mm-dd>/<time> audit.json`
and `.csv` (every practice trade, its match and verdict), prints the summary,
and moves `state.json` forward to the newest trade it audited, so the next
plain run starts there.

## What to report to the operator

Plain words, short, with their own numbers (`short-and-plain`):

1. how many practice trades and ids were read, and the window's real dates;
2. the ids with NO result in Stored strategies: how many and which;
3. for every compared trade, practice profit against backtest profit and the
   verdict; lead with the ones that are not close or have no equivalent.

Verdicts beyond the three approved ones, both added on the first day:

* **backtest ends before this trade closed**: the nearest backtest trade
  ended with `END`, so the backtest's candles stopped while the trade was
  still open, and its "profit" is only the mark at that last candle (XDC
  30m, Oct 13, 2026: +0.12 at 11:30am against practice's +0.74 at 12:23pm).
  It is not a mismatch.
* **not checked (its trade list did not load)**: the row was found but its
  trade list never drew. The row is clicked twice, then a screenshot and the
  panel's own message are saved. It is never reported as "no equivalent".
* **backtest already in its own trade** (Oct 15, 2026): no backtest trade
  opened near it, but one was OPEN across its opening, so the backtest could
  not have taken it; the note names that trade. The stored backtest walks
  without switch-ons, so a strategy switched on while it held a trade
  disagrees with practice's first trade (CLANKER #WVUWQDBP: short from Oct
  09, 2026 11:45pm to Oct 10, 2026 12:40pm, switched on at 9:56am, practice
  bought at 10:45am). When the backtest's trade opened AFTER the switch-on,
  it is a real difference upstream — report the trade that put it there
  (RECALL #9ZEFCCRT: the backtest's 11:00am short, which practice skipped
  on its own book).
* **closed by the move to Gate / by hand / by the panic button, not by its
  strategy**: only a trade its own target or stop closed (`TP`, `SL`) is set
  against a backtest exit, and the others' ids are never looked up. The move
  to Gate closed 91 practice trades at the old exchange's last price (Oct 10,
  2026 3:56am-3:59am, `VENUE_SWITCH`), 20 of them inside the first run's
  opening minute (RCA-2026-10-15-C).

The matching rules (`split`, `compare`, `verdict`) live in
`scripts/match.mjs`, which `tests/test_practice_backtest_audit.py` imports —
change them there, never inside `audit.mjs`.

## What the first runs taught (Oct 14, 2026)

* The Filters window's button reads **"Apply filters" only when nothing is
  pending**. With an id typed it reads "Apply 2 filters", and while Stored
  strategies is still answering (the page's opening 30-day search) it reads
  "searching 30s", disabled. The script finds it by its title, "send the
  boxes to the store", and waits for it to be enabled.
* **"loading row #ID ... the figures above are still the previous answer"**
  is the loading line, not a no-result. The only no-result answers are the
  warning paragraphs Stored strategies draws once an id search has finished
  with no row.
* **The site may be restarted by another session mid-run.** A trade list
  whose request died with it is asked once more.

## Rules

* **Read only.** It clicks tabs, the book switch, page buttons, Filters,
  Apply filters and result rows. Never anything that switches a strategy
  on, deploys, presses a job, or touches real money.
* **Its own browser.** The Chrome already on this machine through
  `playwright-core` in a fresh profile (press-and-watch's choice: the
  Playwright MCP server times out here), so the operator's own filters are
  never changed. The browser is closed at the end, even after a failure.
* **One run at a time**, and say which window it read: an empty result
  names what was examined (CLAUDE.md, "an empty page may never speak for
  the store").
* A step that fails saves a screenshot beside the run's files and is named
  in the report, never skipped quietly.
