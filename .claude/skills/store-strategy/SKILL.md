---
name: store-strategy
description: ALWAYS ON whenever a new strategy, signal or rule is created, measured or swept. The job is not finished when the rows are measured — it is finished when the operator can find them in Stored strategies by their #id. Measuring writes pair FILES; the panel reads the row INDEX, and nothing connects the two automatically.
---

# A strategy is not created until it is IN THE STORE

The operator, Sep 12, 2026, after a 6,845,648-row sweep of ten new cascade
rules that the panel could not see:

> *"did you add it in backtest stored strategies"* … *"/goal i want it in my
> backtest store, whenever i ask you to create a new strategy i want you to
> store it in my backtest strategies"*

## What went wrong, in their own numbers

1. Ten new `cx_*` rules were written, registered in `backtest_report.SIGNALS`,
   and swept over 1,047 coins on four timeframes.
2. **6,845,648 cascade rows** landed in the pair files on `G:`.
3. The Stored-strategies dropdown listed all ten rules — that list is built
   from the CODE REGISTRY, so it looked done.
4. Searching returned nothing. `signal=cx_veto` → **0 rows**. The best row of
   the published artifact, `#WYQMPU8A` (KAVA 4h, 92.9%), → **0 rows**.
5. `rows_index.status()`: `rows=96,307,386`, `pairs_indexed=5,388`,
   **`stale=5,179`** — the index still held the pre-sweep measurement of
   almost every pair.

Nothing was broken. Nothing was lost. The rows were on disk the whole time.
**Measuring writes pair files; the panel reads the row index; no step in
between runs by itself.**

## The rule

**Finish the chain, every time, and say where it stopped.**

```
 rule registered  ->  swept / measured  ->  rows in pair FILES
                                                  |
                                                  v
                                      indexed into rows.db
                                                  |
                                                  v
                              visible in Stored strategies by #id
```

A strategy request is DONE at the last box, not the third.

## The check — three commands, always run before saying done

1. **Is the rule in the grid at all?**
   ```python
   from tradingagents import backtest_report as br
   [s for s in br.SIGNALS if s.startswith("cx_")]      # the new family
   ```
   A rule the grid cannot pick is a rule that will never be measured
   (the `signals_ext` lesson, 2026-08-19).

2. **Did the rows land on disk?**
   ```python
   from tradingagents import market_sweep as msw
   import json
   rows = json.loads((msw.ROWDIR / "KAVA-4h.json").read_text(encoding="utf-8"))
   sum(1 for r in rows if r["signal"].startswith("cx_"))
   ```

3. **Can the OPERATOR find it?** — the only check that counts:
   ```bash
   curl -s "http://127.0.0.1:8787/api/strategies?row_id=WYQMPU8A"
   curl -s "http://127.0.0.1:8787/api/strategies?signal=cx_veto&limit=3"
   ```
   `total: 0` means the answer to *"did you add it"* is **no**, however many
   rows are on disk. Quote the id you tested — `#WYQMPU8A`, not "a row".

## Getting them in

`POST /api/strategies/reindex` walks the stale pairs. Two things decide how
long, and both must be said out loud before starting:

* **How many pairs are stale**, from `rows_index.status()` — this is the size
  of the job, and it is usually far larger than `behind` (which counts only
  never-indexed pairs). On 2026-09-10 a button printed 806 for a job that
  walked 5,276.
* **Whether anything is still WRITING.** Check first:
  ```python
  from tradingagents import db_jobs as dj
  dj._read(dj.FILES["collect"]["progress"]).get("running")   # a collect landing rows
  dj.status("backtest").get("running")
  ```
  and whether a sweep is still measuring on GitHub. Indexing while a collect
  runs indexes a moving target: on Sep 12 the stale count climbed 5,179 →
  5,191 during the check itself, because run 34612655037 was still landing
  and 34631292767 was still measuring. **Wait for quiet, then index once.**

Cross-check `store-indexes` too: getting ROWS in is a different job from
building the SORT indexes the panel's filters need. A fill can finish and
`#id` lookup still be a 40-second scan because `rows_id` was never built.

## Rules

* **Never report a strategy as created on the strength of a row count.**
  "6.8 million rows measured" and "you can use them" are different claims.
* **Name the id you verified.** The operator deployed the wrong config once
  from "the first row" (2026-08-17).
* **If the index cannot be filled now, say so with the reason and the size** —
  "5,191 pairs stale, a collect is still landing run 34612655037, indexing
  after it" — never a silent "done".
* **A long fill must be watched to the end** (`press-and-watch`): this repo has
  an incident where an index thread died on its first statement and the button
  reported `started: true` for thirteen hours.
* **An artifact does not replace the store.** Publishing a table is useful;
  the operator trades from the app. Both, or say which one is missing.
