# Sep 27 ML — decision-tree strategies per coin and timeframe

**Asked, Sep 27, 2026:** *"instead of using confluence, can you review past 30
days and create best strategy for each coin and each timeframe use machine
learning on what's best strategy i want tp higher than sl"*.
Choices made with the operator the same day: learn from the **6 months before
the last 30 days** and test on those 30; **decision trees**; then *"go"*.

## What it is

For every coin × 15m / 30m / 1h / 4h / 1d, a small decision-tree model learns
from price-only clues when a trade is likely to reach its target before its
stop, for target/stop pairs where **TP is strictly bigger than SL**. Up to 3
strategies per coin+timeframe are kept, stored in Backtest v2 as
`ml_<COIN>_<tf>_<n>` under a new filter group **"Sep 27 ML"**, with the same
trade log, CSV and deploy path as any other v2 row. It is measured on GitHub
across both accounts, like the Sep 25 Strat.

It does NOT read any existing signal or confluence rule. That is the point of
the ask.

## The three periods (unchanged from the Sep 25 loop, and why)

```
TRAIN (~150 days) | VALIDATE (30 days) | UNSEEN (last 30 days)
  trees learn      |  every choice made  |  graded once, shown as it is
```

* **One correction to what was shown in chat.** The chat diagram said a
  strategy that loses on the last 30 days is "thrown away". It must not be.
  The Sep 25 loop learned this on Sep 26, 2026 (formula_learner docstring):
  when the test month was used to pick, 300 of 300 formulas looked above
  break-even there and only **85 of 300** made money on 90 days nobody had
  used. So every choice (which TP/SL, how sure the model must be, which 3
  to keep) is made on VALIDATE, and the last 30 days are graded after the
  choice is frozen and reported whatever they say. The screen's filters
  (min win rate, min profit) are where the operator picks.
* Periods by timeframe: intraday frames learn from up to 180 days before the
  last 30. **1d learns from up to 720 days**: 180 daily candles are 150
  training examples, too few for any model.
* **Not enough history** = fewer than `MIN_TRAIN_ROWS = 400` labelled
  training candles, or fewer than 30 days of TRAIN. The pair is skipped and
  named in the report; nothing is forced through.
* **Purged edges.** A training label looks forward until its exit. Any
  training candle whose trade would still be open when VALIDATE starts is
  dropped, and the same at the UNSEEN edge, so no answer from a later period
  leaks into an earlier one.

## Components (each one file, one job)

1. **`tradingagents/ml_features.py`** — `features(o, h, lo, c, v, ts, funding,
   tf) -> (n × F) float array` and `FEATURES` (names). About 30 price-only
   clues: returns over 1/3/6/12/24/48 bars, RSI(14), ATR% (14), range
   position over 20/50 bars, distance from the 20/50/200-bar average, candle
   body/upper wick/lower wick as a share of range, volume ÷ its 20-bar
   average, hour of day, day of week. **No funding clue** (dropped in the
   Sep 28, 2026 review, `VERSION = 2`): the live runner calls `signal_for`
   without a funding list, so a model that read the rate would have been
   measured on the real rate and run on zero. Funding is still CHARGED by the
   engine on every trade; `features` keeps the parameter and ignores it, and
   a model saved with another clue version abstains everywhere.
   **Every clue is a finite window of at most 200 bars** (no running
   averages that remember the whole array). So a candle gets the same number
   whether the array starts 300 bars or a year earlier, and the stored row's
   300-bar cut, the grade and the live runner agree by construction (the
   Sep 25 loop had to grade on the stored row's cut because running averages
   drift). Row i reads only bars ≤ i. `NaN` until a window is full; the model
   abstains on any row with a `NaN`.
2. **`tradingagents/ml_trees.py`** — gradient-boosted trees in numpy, no new
   dependency (the runner, this PC and GitHub already have numpy; no
   scikit-learn anywhere). Binary log-loss, histogram splits on 32 quantile
   bins learned from TRAIN, `N_TREES = 30`, `DEPTH = 3`, `LR = 0.1`,
   `MIN_LEAF = 40`, row subsample 0.8 with a fixed seed. Deterministic:
   same data, same model. `fit(X, y) -> model` (a JSON-able dict: split
   feature, split value, leaf values) and `predict(model, X) -> p`.
3. **`tradingagents/ml_learner.py`** — one coin+timeframe. Reuses
   `formula_learner.Frame`, `barrier_pairs`, `_search_subset`,
   `breakeven_winrate`, the period split and the engine calls (`validate`,
   `grade`) instead of copying them. For each TP > SL pair in the search
   subset and each side (long, short): label every TRAIN candle 1 if an entry
   at the next open reaches TP before SL (SL first when both touch inside one
   bar, the engine's own rule), fit a model. Direction on a candle: long if
   `p_long >= θ`, short if `p_short >= θ`, the larger if both. θ is tried at
   the model's own top 2 / 5 / 10 / 20% of TRAIN predictions. Every (pair, θ)
   is scored on VALIDATE by the real engine (fee + slippage + funding) with
   the Sep 25 floors: enough trades, win rate above the pair's own break-even,
   profit > 0, and the win rate's lower confidence bound (Wilson, 90% shared
   across the 12 validate tries) above that break-even, so the best of many
   tries on one month cannot pass by luck. The best 3 with different trades are kept, then graded on
   UNSEEN minute-exact and stored as `learned.unseen` (never a filter).
   No nested-window check: TRAIN predictions are in-sample, so a window
   over them would praise the model for remembering.
4. **`tradingagents/signals_ml.py`** — the registry, shaped like
   `signals_learned`: reads the model file, reloads on change, `spec_for(key)`,
   `dirs_for(spec, o, h, lo, c, v, ts, funding)`. `auto_trader.signal_for`
   and `_dirs_for_backtest` gain an `ml_` branch beside the `lx_` one;
   `local_history._sig_of` reads an `ml_` key as its own signal. An unknown
   `ml_` name abstains (returns 0), never guesses.
5. **Model file** — `tradingagents/learned/sep27_ml.json.gz`, in git so every
   machine that pulls can run a deployed row. Gzipped because ~6,000 kept
   strategies × 2 models × 30 trees is tens of MB as plain JSON; measured and
   printed at collect, and the collect refuses past 50 MB rather than bloat
   the repo silently.
6. **GitHub** — `.github/scripts/ml_shard.py` and `.github/workflows/ml.yml`,
   the learn shard's shape: claim one coin at a time, 1-minute candles
   fetched once per coin and reused for every timeframe, redo a failed coin
   alone (`COIN_RETRIES = 2`), save models and report after every TIMEFRAME
   (a machine stopped mid-coin hands over what it finished), rows measured
   through `sweep_shard.run_pair(signals=[names], learned=...)` so stored rows
   are measured by the same engine as every v2 row, TP > SL and the stop
   inside 80% of liquidation. **One stored row per model**, at the model's own
   TP/SL (`ml_shard.own_rows`) — run_pair walks every TP > SL pair, and a
   model measured at a pair it was not learned at is a strategy nobody
   learned. `DAYS` is pinned to 30 so the row covers exactly UNSEEN. Both
   accounts via `cloud_sweep.sync_fleet`.
7. **Collect** — `learn_collect` takes a family (`lx` → `sep25.json`,
   `ml` → `sep27_ml.json.gz`) instead of a copy of the module: download,
   `land` (v2 store only, `res` must be 1m, merge pair by pair, report merged),
   `file_learned` in batches. One writer at a time on the v2 disk.
8. **Group** — `rows_index.GROUPS["sep27ml"] = {"label": "Sep 27 ML"}`,
   prefix `ml_` in `GROUP_PREFIXES`, partial indexes `rows_ml_*`; Classic
   excludes it. UI: the Group option, `GROUP_LABEL`, the `api.ts` union.

## Deploy

An `ml_` row deploys by id like a Sep 25 row: the preset writes a
`STRATEGY_SPECS` key `ml_<COIN>_<tf>_<n>_<tf>_sl..tp..`, `_sig_of` resolves
it, the runner asks `signals_ml.dirs_for` on the closed candle, and every
gate (cost, chase, one per coin live, capital, liquidation) applies as it
does to every row. Runner and API restart before a preset naming new keys is
applied (memory: deploy-new-keys-restart-first).

## What the operator sees

* Backtest v2 → Filters → Group **Sep 27 ML** → every kept strategy, its
  last-30-day numbers (what the grid measured), click → trade log.
* A report of every coin+timeframe: kept, or why not (not enough history /
  no TP > SL pair clears costs / nothing passed VALIDATE), and the count
  of each, printed when the run is collected.

## Testing (harddev loop, then these)

* `ml_trees`: learns a planted rule (y = x3 > 0.5) to > 95% on held-out rows;
  same seed → byte-identical model; JSON round trip → identical predictions.
* `ml_features`: no clue reads a later bar (change bar i+1 → rows ≤ i
  unchanged); a candle's clues are identical on a 300-bar cut and the full
  array (the finite-window promise).
* `ml_learner`: labels purged at both edges; θ and pair chosen with UNSEEN
  bars replaced by noise give the same choice (UNSEEN cannot choose); every
  kept pair has TP > SL and SL < 80% of liquidation; not-enough-history is
  named.
* Runner: `signal_for("ml_…")` on the closed candle equals the last element
  of the grid's `dirs_for` for the same bars; an unknown `ml_` name abstains.
* Group filter: `sep27ml` returns only `ml_` rows, Classic returns none.
* Press and watch: a one-coin canary run on GitHub first (BTC + FASTSTOCK),
  collected and opened in the browser, before the full run is dispatched.

## Time and cost

About 1–2 hours on GitHub for the full market, then about 5 hours per account
to load the rows into the v2 index on this PC's spinning G: drive (the Sep 25
collect's measured rate, ~13 s a pair). The operator is told before each long
step starts.

## Out of scope

Retraining on a schedule; models that choose their own TP/SL outside the
grid's TP > SL pairs; live (real-money) arming — practice only unless the
operator switches a row on.
