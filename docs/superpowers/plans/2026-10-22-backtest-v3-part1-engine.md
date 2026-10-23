# Backtest v3 — Part 1: the v3 engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the engine that measures one strategy on one coin the v3 way. Entries are waiting orders, filled only when the price trades through them; an order that never fills is recorded as a missed trade, together with what a market entry would have made. Each idea has its own exit. Every trade risks $1, at a leverage that keeps its stop safe, and pays every cost. The engine also gets v3's own store and ids.

**Architecture:** The pure rules go in a new `tradingagents/v3_rules.py`: the fill, the sizing, the leverage, the trailing stop, the stop's fill price, ATR and funding. That way the engine now, and the runner's v3 practice rooms later, share ONE implementation. `tradingagents/v3_engine.py` walks one strategy over its candles, its minutes and the recorded order book, and returns trades, missed trades and counts. Three existing functions in `auto_trader` gain switches that default to today's behaviour:

- `settle_in_minutes(tp_through=)` — a target that must be traded through.
- `minute_verdict` / `entry_refusal(entry="limit", maker_fee=)` — the cost check for a waiting order.
- a new `maker_fee_floor()` beside `fee_floor()`.

`tradingagents/v3_smoke.py` runs the engine on one real coin from the command line.

**Tech Stack:** Python 3.12, numpy, pandas, pytest, ruff. It uses the existing `book_history`, `cost_store`, `backtest_report.fine_bars` and the exchange door `tradingagents.dataflows.exchange as fx`.

**Spec:** `docs/superpowers/specs/2026-10-22-backtest-v3-design.md`, approved Oct 22, 2026 ("ok go ahead"). This plan covers the spec's build order 1 (the engine) and the coverage figure that build order 0 needs. Parts 2-5 get their own plans (see the end).

## Global Constraints

- **Read before the first edit:** the newest entries of `docs/OPERATOR-ASKS.md`, as required by CLAUDE.md "remember-my-asks".
- **v1 and v2 do not change.** Every new parameter defaults to the old behaviour, and the existing tests named in each task stay green.
- **Fills:** a waiting buy fills only when a point's low is strictly BELOW the limit; a sell, only when a high is strictly ABOVE it. A touch is not a fill. The fill price is the limit price.
- **Fill window:** the candle after the signal candle, `[t[i+1], t[i+1] + bar_s)`. An order still unfilled at its end is a missed trade, kept with its market twin.
- **Points:** a point is one of Gate's minutes, or a 5-minute bar where Gate's archive has a hole (`backtest_report.fine_bars`). Never step through them by adding `+60_000`; step from point to point.
- **The fill point:** the point an order fills in can stop the trade. It can never win it or move its trail, because its high may have come before the fill.
- **Gaps:** a stop the price jumped past fills at the best price that point traded (`v3_rules.stop_fill`). It never fills at a price that did not trade.
- **Fees:**
  - waiting-order fee = `auto_trader.maker_fee_floor()`: 0.0002 on Gate (the fee guide's +0.02%), never the −0.01% rebate;
  - taker fee = `auto_trader.fee_floor()`: 0.00075 on Gate.
- **Exit costs:** a market exit pays the taker fee plus the exit minute's recorded gap (`book_history.reading_at`). With no reading, it pays the coin's flat gap and is counted `cost_unmeasured`. A resting target pays the maker fee and no gap.
- **Risk and leverage:** each trade risks $1 by default (`v3_rules.RISK_USD`). Leverage is the highest whole number whose stop sits strictly inside `LIQ_CEILING` (0.8, equal to `auto_trader.STOP_LIQ_CEILING`) × (1/leverage − maintenance rate). A stop that no leverage keeps safe is counted `unsafe_stop`; a trade under one lot is counted `too_small`.
- **Trailing stop:** 3 × ATR(20) of the strategy's timeframe (`TRAIL_ATR`, `ATR_N`). Each point checks the stop BEFORE moving it, and the stop never loosens.
- **Funding:** charged settlement by settlement. The history answers from one cycle before its first settlement; the part of a hold before that pays the average known rate and is counted `funding_estimated`.
- **Units:** `exit_spec` targets and stops are FRACTIONS (0.02 = 2%).
- **Ids:** a v3 row id is `backtest_report.row_code(..., res="v3")`.
- **Code rules:**
  - dates print only through `positions_view.fmt_when`;
  - nothing goes below an `if __name__ == "__main__":` guard;
  - no variable named `l` outside tests (ruff E741 is on);
  - imports from one package are combined on one line (`combine-as-imports`).
- **Testing on this PC:** run ONE full pytest suite at a time. Check for a running pytest first, because other sessions share this PC. Each task runs only the files it names.
- **Before each commit:**
  - run the harddev hunt: callers, the state it runs in, failure paths, units, sides;
  - name each round in the commit message;
  - check `git diff HEAD -- <path>` for every path (commit_own commits WHOLE files, and other sessions edit this checkout);
  - never `git add -A`, never `git stash`.
- **Commit and push:**
  - write the message to a file OUTSIDE the repo, and end it with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - commit with `.venv/Scripts/python scripts/commit_own.py -F <msg-file> <paths>`;
  - push with `git push -q origin main && git push -q colleague main && git push -q teammate main`.

## Review Focus

1. **A touch is not a fill.** A point whose low only touches the limit does not fill a buy. Pinned in Task 2 by `test_a_touch_is_not_a_fill_a_trade_through_is` and in Task 4 by `test_an_order_that_only_touches_is_missed_and_its_market_twin_is_kept`.
2. **The fill point can stop the trade but never win it.** Its high may have come before the fill. Pinned in Task 4 by `test_the_minute_an_order_fills_in_can_stop_it_but_cannot_win_it`.
3. **A jumped stop fills where the price was.** A stop the price jumped past fills at the best price that point traded, never at the stop. Pinned in Task 2 by `test_a_stop_the_price_jumped_past_fills_where_the_price_was` and `test_a_trail_the_price_jumped_past_exits_at_the_best_price_traded`, and in Task 4 by `test_a_stop_the_price_jumped_past_is_booked_where_the_price_was`.
4. **A candle with no minutes keeps the candle rule.** Such a candle (Gate's archive hole) is settled by the candle rule and counted. The rest of a candle that has no points left is spent, never re-read by the candle rule. Pinned in Task 4 by `test_a_candle_with_no_minutes_keeps_the_candle_rule_and_is_counted`.
5. **Unsafe or too-small trades are skipped and counted.** A stop that no leverage keeps safe, or a trade under one lot, is never traded. Pinned in Task 2 by `test_the_safe_leverage_keeps_the_stop_inside_80_percent_of_liquidation` and `test_one_dollar_of_risk_sizes_the_trade_and_less_than_one_lot_is_skipped`, and in Task 4 by `test_a_stop_no_leverage_keeps_safe_and_a_trade_under_one_lot_are_skipped`.

## Proven before this plan was handed over (Oct 22, 2026)

The code and tests below were run before this plan was written, in a scratch copy that patched the modules in memory. Nothing in the checkout changed.

- **The plan's own tests:** all 38 passed against the plan's code.
- **The existing tests these changes touch:** 90 of 91 passed with the changes applied. They were:
  - `test_minute_exact_exits`
  - `test_room_replay_settles_by_the_minute`
  - `test_cost_verdict_is_the_runners`
  - `test_the_replay_shard`
  - `test_cost_store`
  - `test_backtest_pays_the_minute`
  - `test_gate_runner_costs`
  - `test_v2_store_is_its_own_folder`
- **The one expected failure:** `test_v2_store_is_its_own_folder` used `by_name("v3")` as its example of an unknown store. Task 1 changes that example to `"v9"`, and the changed file was run and passed.
- **Lint:** ruff passed on every new file.
- **Real Gate data:** three runs on BTC_USDT 1h over Sep 22, 2026 11:00pm to Oct 22, 2026 10:00pm, read-only. The order books covered 99.9% of the minutes in all three.

| exit | trades | won | lost | profit at $1 risk | missed orders | missed, entered at the market | run time |
|---|---|---|---|---|---|---|---|
| `fixed:0.02:0.01` | 27 | 13 | 14 | +9.88 | 0 | — | 7-13 s |
| `trail:3:50` | 87 | 16 | 71 | −8.33 | 4 | +0.98 | 8 s |
| `snap:3:24` | 39 | 21 | 18 | −0.47 | 1 | +0.47 | 7 s |

---

### Task 1: The v3 store and v3 ids

**Files:**
- Modify: `tradingagents/stores.py` (the `tfs` property, a new `V3`, `_BY_NAME`, `for_kind`)
- Modify: `tests/test_v2_store_is_its_own_folder.py:94-95` (the unknown-store example becomes `"v9"`)
- Test: `tests/test_backtest_v3_store.py`

**Interfaces:**
- Produces:
  - `stores.V3`, a `Store` with:
    - `name="v3"`
    - `home=~/.tradingagents/v3`
    - `candles=~/.tradingagents/v3/candles`
    - `rows_db=~/.tradingagents/v3/rows.db`
    - `parquet=~/.tradingagents/parquet-v3`
    - `fine_tf="v3"`, `download_kind=""`, `backtest_kind="backtest_v3"`
  - `stores.by_name("v3")` returns `V3`.
  - `stores.for_kind(k)` returns `V3` when `k` ends in `_v3`.
  - `Store.tfs` returns the five frames for v1 AND v3, and `("1m",)` only for v2.

- [ ] **Step 1: Write the failing test** — `tests/test_backtest_v3_store.py`:

```python
"""Backtest v3 has its own store and its own ids (spec
docs/superpowers/specs/2026-10-22-backtest-v3-design.md, "The store and the
ids"): v3 never writes v1 or v2, and a v3 row never shares an id with its v1
or v2 twin."""
from tradingagents import backtest_report as br, stores


def test_v3_has_its_own_folders():
    root, v3 = stores.V1.home.parent, stores.V3
    assert str(v3.home).replace("\\", "/").endswith("/.tradingagents/v3")
    assert v3.candles == root / "v3" / "candles"
    assert v3.rows_db == root / "v3" / "rows.db"
    assert v3.parquet == root / "parquet-v3"
    for f in ("home", "candles", "rows_db", "parquet"):
        assert len({getattr(s, f) for s in (stores.V1, stores.V2, v3)}) == 3, f


def test_v3_is_found_by_name_and_by_kind():
    assert stores.by_name("v3") is stores.V3
    assert stores.for_kind("backtest_v3") is stores.V3
    assert stores.for_kind("backtest_v2") is stores.V2
    assert stores.for_kind("backtest") is stores.V1


def test_the_frames_each_store_works_in():
    assert stores.V1.tfs == stores.FIVE
    assert stores.V2.tfs == ("1m",)
    assert stores.V3.tfs == stores.FIVE


def test_a_v3_id_never_equals_its_v1_or_v2_twin():
    combo = ("BTC_USDT", "1h", "bb20", 0.0, 0.01, 0.02, "flat")
    v1, v2, v3 = (br.row_code(*combo), br.row_code(*combo, res="1m"),
                  br.row_code(*combo, res="v3"))
    assert len({v1, v2, v3}) == 3
    assert v3 == br.row_code(*combo, res="v3"), "the same combination, the same id"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_backtest_v3_store.py -q`
Expected: `3 failed, 1 passed`, with `AttributeError: module 'tradingagents.stores' has no attribute 'V3'` (and a `KeyError: 'v3'` from `by_name`). The id test already passes, because `row_code` takes any `res`. It is there so that a later change to `row_code` cannot merge v3 ids into v2's.

- [ ] **Step 3: Implement.** In `tradingagents/stores.py`, replace the `tfs` property:

```python
    @property
    def tfs(self) -> tuple[str, ...]:
        """What the DOWNLOAD fetches here: 1m alone for v2, the five for v1 and
        v3 (v3 reads its minutes on GitHub, never a 1m download here)."""
        return ("1m",) if self.fine_tf == "1m" else FIVE
```

Then replace `_BY_NAME = {"v1": V1, "v2": V2}` with:

```python
# BACKTEST V3 (Oct 22, 2026; spec docs/superpowers/specs/2026-10-22-backtest-
# v3-design.md): research-backed ideas with waiting-order entries, their own
# exits and $1 risk a trade, in folders of their own so v1 and v2 are never
# written. `fine_tf` "v3" is the RESOLUTION a v3 row is stamped with (its id
# hashes res="v3"), never a timeframe. NO job runs with V3.env_for() until
# Part 2 has checked every reader of market_sweep.FINE_TF (30 references in
# 9 files on Oct 22, 2026): several read "set" as "this is v2".
V3 = Store(name="v3", home=_HOME / "v3", candles=_HOME / "v3" / "candles",
           rows_db=_HOME / "v3" / "rows.db", parquet=_HOME / "parquet-v3",
           fine_tf="v3", download_kind="", backtest_kind="backtest_v3")

_BY_NAME = {"v1": V1, "v2": V2, "v3": V3}
```

and replace `for_kind`:

```python
def for_kind(kind: str) -> Store:
    """The store a job KIND works in (`..._v2` → V2, `..._v3` → V3, else V1)."""
    k = str(kind)
    return V3 if k.endswith("_v3") else V2 if k.endswith("_v2") else V1
```

In `tests/test_v2_store_is_its_own_folder.py`, the unknown-store example becomes one that will never exist:

```python
    with pytest.raises(KeyError):
        stores.by_name("v9")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_backtest_v3_store.py tests/test_v2_store_is_its_own_folder.py -q`
Expected: all pass.

- [ ] **Step 5: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/stores.py tests/test_backtest_v3_store.py tests/test_v2_store_is_its_own_folder.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message: `feat(v3): the Backtest v3 store and ids - its own folders under ~/.tradingagents/v3, res="v3" ids never equal a v1/v2 twin; no job runs in it until Part 2 checks the 30 FINE_TF readers`

---

### Task 2: The shared v3 rules

**Files:**
- Create: `tradingagents/v3_rules.py`
- Test: `tests/test_v3_rules.py`

**Interfaces** (all pure; times are epoch ms; point sequences may be lists or numpy arrays):
- Constants:
  - `RISK_USD = 1.0`
  - `ATR_N = 20`
  - `TRAIL_ATR = 3.0`
  - `LIQ_CEILING = 0.8`
- Indicators:
  - `atr(high, low, close, n=ATR_N) -> list[float | None]`
  - `sma(close, n) -> list[float | None]`
- Fills:
  - `limit_fill(side, limit_px, t_ms, hi, lo, start_ms, end_ms) -> int | None` returns the fill point's ms.
  - `stop_fill(side, stop, hi, lo) -> float`
- Sizing:
  - `safe_leverage(stop_frac, mmr, max_lev, min_lev=1, ceiling=LIQ_CEILING) -> int | None`
  - `risk_size(risk_usd, entry_px, stop_px, *, contract_size, min_vol, mmr, max_lev, min_lev=1, ceiling=LIQ_CEILING) -> dict | None`, with the keys `contracts`, `notional`, `leverage`, `margin`, `stop_frac`, `risk_usd`.
- Trailing stop:
  - `trail_walk(side, stop, dist, t_ms, hi, lo, start_ms, end_ms) -> (exit_ms, fill_px)`, or `(None, stop carried forward)`.
- Funding:
  - `funding_paid(f_ms, f_rate, f_cyc, side, entry_ms, exit_ms) -> (fraction paid, estimated)`. The three lists are the arrays `auto_trader.funding_day_at` reads. A positive fraction is a cost.

- [ ] **Step 1: Write the failing test** — `tests/test_v3_rules.py`:

```python
"""The v3 rules — one implementation for the engine and, later, the runner
(spec docs/superpowers/specs/2026-10-22-backtest-v3-design.md, Part 3).
Points are minutes (or Gate's 5-minute bars) in ms, all on ONE timeline."""
import pytest

from tradingagents import v3_rules as vr

M = 60_000
H = 3_600_000
T0 = 1_790_000_000_000 - (1_790_000_000_000 % H)


def test_a_touch_is_not_a_fill_a_trade_through_is():
    t = [T0, T0 + M, T0 + 2 * M]
    hi = [101.0, 100.0, 99.5]
    lo = [100.0, 99.0, 98.9]          # minute 1 touches 99.0, minute 2 trades below it
    assert vr.limit_fill(1, 99.0, t, hi, lo, T0, T0 + 3 * M) == T0 + 2 * M
    assert vr.limit_fill(1, 98.0, t, hi, lo, T0, T0 + 3 * M) is None
    assert vr.limit_fill(-1, 100.5, t, hi, lo, T0, T0 + 3 * M) == T0, "a sell fills above"
    assert vr.limit_fill(1, 99.0, t, hi, lo, T0, T0 + 2 * M) is None, "outside the window"


def test_a_stop_the_price_jumped_past_fills_where_the_price_was():
    assert vr.stop_fill(1, 98.0, 99.0, 97.0) == 98.0      # traded through 98.0
    assert vr.stop_fill(1, 98.0, 97.5, 97.0) == 97.5      # the whole minute was below it
    assert vr.stop_fill(-1, 102.0, 103.0, 101.0) == 102.0
    assert vr.stop_fill(-1, 102.0, 103.0, 102.5) == 102.5


def test_the_safe_leverage_keeps_the_stop_inside_80_percent_of_liquidation():
    # maintenance 0.5%: at 20x liquidation is 4.5% away and 80% of it 3.6%
    assert vr.safe_leverage(0.03, 0.005, 20) == 20
    assert vr.safe_leverage(0.05, 0.005, 20) == 14       # 15x leaves 4.93%, 14x 5.31%
    assert vr.safe_leverage(0.10, 0.005, 20) == 7        # 8x leaves 9.6%, 7x 11.03%
    assert vr.safe_leverage(0.80, 0.005, 20) is None     # even 1x leaves only 79.6%


def test_the_liquidation_ceiling_is_the_runners():
    import tradingagents.auto_trader as at

    assert vr.LIQ_CEILING == at.STOP_LIQ_CEILING


def test_one_dollar_of_risk_sizes_the_trade_and_less_than_one_lot_is_skipped():
    got = vr.risk_size(1.0, 100.0, 95.0, contract_size=0.01, min_vol=1, mmr=0.005,
                       max_lev=20)
    # a 5% stop: $20 of coin is 20 lots of 0.01 at $100, and 5% of $20 is $1.00
    assert got["contracts"] == 20 and got["notional"] == pytest.approx(20.0)
    assert got["risk_usd"] == pytest.approx(1.0) and got["leverage"] == 14
    assert got["margin"] == pytest.approx(20.0 / 14)
    # one BTC lot is 0.0001 x $100,000 = $10, so a 15% stop would risk $1.50
    assert vr.risk_size(1.0, 100_000.0, 85_000.0, contract_size=0.0001, min_vol=1,
                        mmr=0.004, max_lev=100) is None
    assert vr.risk_size(1.0, 100.0, 20.0, contract_size=0.01, min_vol=1, mmr=0.005,
                        max_lev=20) is None, "an 80% stop has no safe leverage"


def test_the_trailing_stop_is_checked_before_it_moves_and_never_loosens():
    t = [T0 + k * M for k in range(5)]
    hi = [101.0, 104.0, 103.0, 103.5, 102.0]
    lo = [100.0, 102.0, 101.5, 100.9, 100.5]
    # a long, stop 97, distance 3: minute 1's high 104 lifts the stop to 101,
    # minute 2's lower high leaves it there, minute 3's low 100.9 takes it
    exit_ms, px = vr.trail_walk(1, 97.0, 3.0, t, hi, lo, T0, T0 + 5 * M)
    assert exit_ms == T0 + 3 * M and px == pytest.approx(101.0)
    exit_ms, stop = vr.trail_walk(1, 97.0, 3.0, t, hi, lo, T0, T0 + 3 * M)
    assert exit_ms is None and stop == pytest.approx(101.0)
    # a short mirrors it: the stop follows the lows down
    exit_ms, stop = vr.trail_walk(-1, 103.0, 3.0, t[:2], [100.5, 98.5], [99.0, 96.0],
                                  T0, T0 + 2 * M)
    assert exit_ms is None and stop == pytest.approx(99.0)


def test_a_trail_the_price_jumped_past_exits_at_the_best_price_traded():
    t = [T0, T0 + M]
    # minute 0 lifts the stop to 99.5; minute 1 trades only 97.0-98.0, below it
    exit_ms, px = vr.trail_walk(1, 99.0, 1.0, t, [100.5, 98.0], [99.8, 97.0], T0, T0 + 2 * M)
    assert exit_ms == T0 + M and px == pytest.approx(98.0)


def test_atr_and_sma_wait_for_their_window():
    hi, lo, close = [11.0, 12.0, 13.0], [9.0, 10.0, 11.0], [10.0, 11.0, 12.0]
    assert vr.atr(hi, lo, close, 2) == [None, pytest.approx(2.0), pytest.approx(2.0)]
    assert vr.sma(close, 2) == [None, pytest.approx(10.5), pytest.approx(11.5)]


def test_funding_is_paid_settlement_by_settlement_and_estimated_before_the_history():
    f_ms, f_rate, f_cyc = [T0 + 8 * H, T0 + 16 * H], [0.0001, 0.0003], [8.0, 8.0]
    # the history answers from T0, one cycle before its first settlement
    paid, est = vr.funding_paid(f_ms, f_rate, f_cyc, 1, T0, T0 + 16 * H)
    assert paid == pytest.approx(0.0004) and est is False
    paid, est = vr.funding_paid(f_ms, f_rate, f_cyc, -1, T0, T0 + 16 * H)
    assert paid == pytest.approx(-0.0004) and est is False, "a short receives what a long pays"
    # 8 hours before the history: one cycle at the average known rate, 0.0002
    paid, est = vr.funding_paid(f_ms, f_rate, f_cyc, 1, T0 - 8 * H, T0 + 8 * H)
    assert paid == pytest.approx(0.0002 + 0.0001) and est is True
    assert vr.funding_paid([], [], [], 1, T0, T0 + 8 * H) == (0.0, True), \
        "no history is never a measured zero"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_v3_rules.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.v3_rules'`

- [ ] **Step 3: Implement** — `tradingagents/v3_rules.py`:

```python
"""THE V3 RULES — one implementation of every rule Backtest v3 trades by.

Spec: docs/superpowers/specs/2026-10-22-backtest-v3-design.md (operator, Oct
22, 2026: "i want to do backtest v3 where you will create the strategy for
the research you made"). The engine (`v3_engine`) uses these now, and the
runner's v3 practice rooms will use the same functions (Part 5), so a v3
backtest and its practice room can never fill, size or trail by two rules.

All pure. Times are epoch ms. A POINT is one of Gate's minutes, or a 5-minute
bar where its archive has a hole (`backtest_report.fine_bars`); point
sequences may be lists or numpy arrays.
"""
from __future__ import annotations

import bisect

RISK_USD = 1.0      # lost when a stop is hit; the v3 page's risk box rescales it
ATR_N = 20
TRAIL_ATR = 3.0     # trailing stop = 3 x ATR(20) of the strategy's timeframe
LIQ_CEILING = 0.8   # auto_trader.STOP_LIQ_CEILING, held equal by a test


def atr(high, low, close, n: int = ATR_N) -> list:
    """The average true range of the last `n` candles; None until `n` exist."""
    out: list = [None] * len(close)
    trs: list = []
    window = 0.0
    for i in range(len(close)):
        prev = close[i - 1] if i else close[i]
        tr = max(high[i] - low[i], abs(high[i] - prev), abs(low[i] - prev))
        trs.append(tr)
        window += tr
        if i >= n:
            window -= trs[i - n]
        if i >= n - 1:
            out[i] = window / n
    return out


def sma(close, n: int) -> list:
    """The average of the last `n` closes; None until `n` exist."""
    out: list = [None] * len(close)
    total = 0.0
    for i, c in enumerate(close):
        total += c
        if i >= n:
            total -= close[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def _span(t_ms, start_ms: int, end_ms: int) -> tuple[int, int]:
    return bisect.bisect_left(t_ms, int(start_ms)), bisect.bisect_left(t_ms, int(end_ms))


def limit_fill(side: int, limit_px: float, t_ms, hi, lo,
               start_ms: int, end_ms: int) -> int | None:
    """The first point in [start_ms, end_ms) whose price traded THROUGH a
    waiting order: a buy when the low is strictly below the limit, a sell
    when the high is strictly above. A touch is not a fill — the queue is
    not modelled, so v3 assumes the back of it. None = never filled."""
    a, b = _span(t_ms, start_ms, end_ms)
    for k in range(a, b):
        if (side == 1 and lo[k] < limit_px) or (side == -1 and hi[k] > limit_px):
            return int(t_ms[k])
    return None


def stop_fill(side: int, stop: float, hi: float, lo: float) -> float:
    """Where a stop fills in a point that reached it: at the stop, or — when
    the whole point traded beyond it (the price jumped past) — at the best
    price that point traded. Never a price that did not trade."""
    return min(stop, hi) if side == 1 else max(stop, lo)


def safe_leverage(stop_frac: float, mmr: float, max_lev: int, min_lev: int = 1,
                  ceiling: float = LIQ_CEILING) -> int | None:
    """The highest whole leverage whose stop sits inside `ceiling` of the
    liquidation distance (1/leverage - maintenance rate); None when even the
    lowest leverage cannot keep the stop safe."""
    for lev in range(int(max_lev), int(min_lev) - 1, -1):
        if stop_frac < ceiling * (1.0 / lev - mmr):
            return lev
    return None


def risk_size(risk_usd: float, entry_px: float, stop_px: float, *, contract_size: float,
              min_vol: int, mmr: float, max_lev: int, min_lev: int = 1,
              ceiling: float = LIQ_CEILING) -> dict | None:
    """The trade that loses `risk_usd` when its stop is hit, in whole lots, at
    the highest safe leverage — or None (no safe leverage, or under one lot)."""
    if entry_px <= 0 or contract_size <= 0:
        return None
    stop_frac = abs(entry_px - stop_px) / entry_px
    if stop_frac <= 0:
        return None
    lev = safe_leverage(stop_frac, mmr, max_lev, min_lev, ceiling)
    if lev is None:
        return None
    # the allowance keeps 49.999999 lots (float division) from becoming 49
    contracts = int(risk_usd / stop_frac / (contract_size * entry_px) + 1e-9)
    if contracts < max(1, int(min_vol)):
        return None
    notional = contracts * contract_size * entry_px
    return {"contracts": contracts, "notional": notional, "leverage": lev,
            "margin": notional / lev, "stop_frac": stop_frac,
            "risk_usd": notional * stop_frac}


def trail_walk(side: int, stop: float, dist: float, t_ms, hi, lo,
               start_ms: int, end_ms: int) -> tuple[int | None, float]:
    """Walk the points in [start_ms, end_ms) with a trailing stop: each point
    is checked against the stop FIRST (its high and low have no order, so the
    worse is assumed), then the stop moves `dist` behind that point's extreme
    and is never loosened. Returns (the exit point and its fill price,
    `stop_fill`) or (None, the stop carried forward)."""
    a, b = _span(t_ms, start_ms, end_ms)
    for k in range(a, b):
        if side == 1:
            if lo[k] <= stop:
                return int(t_ms[k]), stop_fill(1, stop, hi[k], lo[k])
            stop = max(stop, hi[k] - dist)
        else:
            if hi[k] >= stop:
                return int(t_ms[k]), stop_fill(-1, stop, hi[k], lo[k])
            stop = min(stop, lo[k] + dist)
    return None, stop


def funding_paid(f_ms, f_rate, f_cyc, side: int, entry_ms: int,
                 exit_ms: int) -> tuple[float, bool]:
    """Funding over a hold as a fraction of notional PAID (a credit is
    negative; a positive rate means longs pay): every settlement in
    (entry_ms, exit_ms] at its own rate. `f_ms`/`f_rate`/`f_cyc` are the
    settlement history oldest first, in the arrays `auto_trader.funding_day_at`
    reads. The history answers from one cycle before its first settlement;
    any part of the hold before that pays the average known rate per cycle,
    and says so (`estimated`). No history is never a measured zero."""
    if not len(f_ms):
        return 0.0, True
    a = bisect.bisect_right(f_ms, int(entry_ms))
    b = bisect.bisect_right(f_ms, int(exit_ms))
    paid = side * sum(float(x) for x in f_rate[a:b])
    cycle_ms = (float(f_cyc[0]) or 8.0) * 3_600_000
    covered_from = int(f_ms[0]) - cycle_ms
    if int(entry_ms) >= covered_from:
        return paid, False
    avg = sum(float(x) for x in f_rate) / len(f_rate)
    uncovered = min(int(exit_ms), covered_from) - int(entry_ms)
    return paid + side * avg * (uncovered / cycle_ms), True
```

- [ ] **Step 4: Run the test to verify it passes, then lint**

Run: `.venv/Scripts/python -m pytest tests/test_v3_rules.py -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_rules.py tests/test_v3_rules.py`
Expected: `9 passed`, then `All checks passed!`

- [ ] **Step 5: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_rules.py tests/test_v3_rules.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message: `feat(v3): the shared v3 rules - trade-through fills, a jumped stop fills where the price was, $1-risk sizing at the highest safe leverage, the trailing stop, ATR, funding with its estimates counted`

---

### Task 3: Three shared rules learn the waiting order

**Files:**
- Modify: `tradingagents/auto_trader.py`:
  - `maker_fee_floor` (new, just after `fee_floor`, around line 2705)
  - `minute_verdict` (around line 3421)
  - `entry_refusal` (around line 3472)
  - `settle_in_minutes` (around line 4199)
- Test: `tests/test_v3_shared_rules_learn_the_waiting_order.py`

**Interfaces:**
- Produces:
  - `MAKER_FEE_FLOORS = {"gate": 0.0002}` and `maker_fee_floor(venue_name=None) -> float`. Any other exchange gets its `fee_floor`.
  - `minute_verdict(..., flat_slip=0.0, entry="market", maker_fee=None)`. With `entry="limit"`: the entry pays `maker_fee` and no gap; the exit pays `fee` plus the reading's OTHER side (`sell` for a long, `buy` for a short); the result's `slippage` is `0.0`.
  - `entry_refusal(..., closed=False, entry="market", maker_fee=None)`. It passes both through, and with `entry="limit"` it never answers `chase_skip`.
  - `settle_in_minutes(..., span=None, tp_through=False)`. With `True`, a long's target needs a high strictly above it, and a short's a low strictly below.

- [ ] **Step 1: Write the failing test** — `tests/test_v3_shared_rules_learn_the_waiting_order.py`:

```python
"""The v3 engine shares two existing rules instead of copying them (spec
docs/superpowers/specs/2026-10-22-backtest-v3-design.md, Part 3): the minute
settle learns a target that RESTS as a waiting order (it must be traded
through), and the runner's cost check learns a waiting-order entry. Both
default to the rule of before."""
import numpy as np
import pytest

from tradingagents import auto_trader as at

M = 60_000
T0 = 1_790_000_000_000 - (1_790_000_000_000 % 3_600_000)


def _minutes(hl):
    t = np.array([T0 + k * M for k in range(len(hl))], dtype="int64")
    return t, np.array([x[0] for x in hl]), np.array([x[1] for x in hl])


def test_a_resting_target_needs_a_trade_through_a_touch_is_not_enough():
    t, hi, lo = _minutes([(101.0, 99.5), (101.2, 100.5)])    # minute 0 touches 101.0
    assert at.settle_in_minutes(t, hi, lo, T0, 3600, 1, 101.0, 98.0, None,
                                liq=None, sl=0.02)[0] == "TP", "the rule of before"
    got = at.settle_in_minutes(t, hi, lo, T0, 3600, 1, 101.0, 98.0, None,
                               liq=None, sl=0.02, tp_through=True)
    assert got[:2] == ("TP", T0 + M), "filled the minute it traded above"
    t, hi, lo = _minutes([(100.5, 99.0), (100.0, 98.8)])     # a short's target, 99.0
    assert at.settle_in_minutes(t, hi, lo, T0, 3600, -1, 99.0, 102.0, None, liq=None,
                                sl=0.02, tp_through=True)[:2] == ("TP", T0 + M)


def test_stop_and_resting_target_in_one_minute_is_the_stop_and_unclear():
    t, hi, lo = _minutes([(101.5, 97.5)])
    assert at.settle_in_minutes(t, hi, lo, T0, 3600, 1, 101.0, 98.0, None, liq=None,
                                sl=0.02, tp_through=True) == ("SL", T0, 1)


def test_a_waiting_order_pays_gates_published_maker_fee_never_the_rebate():
    assert at.maker_fee_floor("gate") == pytest.approx(0.0002)
    assert at.maker_fee_floor("mexc") == at.fee_floor("mexc"), "never measured: its taker floor"


READING = {"t": 0, "age_s": 0, "bid": 99.9, "ask": 100.1, "spread": 0.002,
           "buy": 0.001, "sell": 0.0012, "exhausted": False, "source": 1}


def test_a_market_entry_is_judged_exactly_as_before():
    cv = at.minute_verdict(READING, side=1, tp=0.02, sl=0.01, fee=0.00075,
                           hold_s=3600, liq=0.036, fund_day=0.0)
    assert cv["round_trip"] == pytest.approx(2 * (0.001 + 0.00075))
    assert cv["slippage"] == pytest.approx(0.001)


def test_a_waiting_entry_pays_the_maker_fee_in_and_the_taker_and_gap_out():
    cv = at.minute_verdict(READING, side=1, tp=0.02, sl=0.01, fee=0.00075,
                           hold_s=3600, liq=0.036, fund_day=0.0,
                           entry="limit", maker_fee=0.0002)
    # a long: in 0.02% (maker, no gap), out 0.075% plus the SELL side 0.12%
    assert cv["round_trip"] == pytest.approx(0.0002 + 0.00075 + 0.0012)
    assert cv["slippage"] == 0.0, "a waiting order's fill pays no gap"
    short = at.minute_verdict(READING, side=-1, tp=0.02, sl=0.01, fee=0.00075,
                              hold_s=3600, liq=0.036, fund_day=0.0,
                              entry="limit", maker_fee=0.0002)
    assert short["round_trip"] == pytest.approx(0.0002 + 0.00075 + 0.001)


def test_a_waiting_entry_is_never_refused_as_a_chase():
    ran = {**READING, "ask": 104.0, "bid": 103.8}    # the price ran 4% from the 100.0 close
    assert at.entry_refusal(ran, side=1, signal_close=100.0, tp=0.02, sl=0.01,
                            fee=0.00075, hold_s=3600, liq=0.036,
                            fund_day=0.0)[0] == "chase_skip"
    assert at.entry_refusal(ran, side=1, signal_close=100.0, tp=0.02, sl=0.01,
                            fee=0.00075, hold_s=3600, liq=0.036, fund_day=0.0,
                            entry="limit", maker_fee=0.0002)[0] == ""
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_v3_shared_rules_learn_the_waiting_order.py -q`
Expected: `5 failed, 1 passed`. The failures are `AttributeError: ... 'maker_fee_floor'` and `TypeError: ... unexpected keyword argument 'tp_through'` / `'entry'`. The market-entry test already passes; it is there so this change can never alter the market path.

- [ ] **Step 3: Implement — the maker fee, directly after `fee_floor`.** Keep two blank lines around the new block. The existing `# Charged on PAPER fills only.` comment and `PAPER_SLIPPAGE` follow it unchanged.

```python
# A WAITING ORDER'S FEE (Backtest v3, Oct 22, 2026; spec
# 2026-10-22-backtest-v3-design.md, "Costs"): Gate's fee guide lists +0.02%
# maker at the base tier while its contract listing shows a -0.01% rebate,
# and the worse is believed until the account's own rate is read with a Gate
# key. No other exchange's maker fill was ever measured, so it pays its
# taker floor: a guess below it would flatter every v3 number.
MAKER_FEE_FLOORS = {"gate": 0.0002}


def maker_fee_floor(venue_name: str | None = None) -> float:
    """The fee per side a WAITING (maker) order is believed to pay — the
    sibling of `fee_floor`, for the exchange this app trades."""
    if venue_name is None:
        from tradingagents import venue as _venue  # noqa: PLC0415

        venue_name = _venue.current()
    return MAKER_FEE_FLOORS.get(venue_name, fee_floor(venue_name))
```

- [ ] **Step 4: Implement — `minute_verdict`.** Replace the whole function with:

```python
def minute_verdict(reading: dict | None, *, side: int, tp: float, sl: float,
                   fee: float, hold_s: float, liq, fund_day: float,
                   flat_slip: float = 0.0, entry: str = "market",
                   maker_fee: float | None = None) -> dict:
    """The runner's cost check asked of ONE recorded minute of the order book
    (tradingagents.book_history) — what `edge_check` would have said had the
    signal fired then. One function for the engine and the replay, so the
    backtest and the replay can never refuse by two rules. Funding the
    backtest cannot read is our data gap, never the market's: `fund_known`.

    NO READING still asks every check that needs no book (RCA-2026-10-10-H):
    a stop past liquidation and funding that eats the target are refused by
    the runner whatever the book says, so they are refused here too, on the
    coin's flat cost (`flat_slip`); only the gap and an exhausted book wait
    for a reading. `measured` says which it was.

    ``entry="limit"`` is a WAITING ORDER (Backtest v3, Oct 22, 2026): the
    entry pays `maker_fee` and no gap, the exit the taker `fee` plus the
    book's other side (`sell` for a long, `buy` for a short). `cost_verdict`
    prices a round trip as 2 x (slippage + fee), so it is handed the halves
    that sum to exactly that; the result's `slippage` is the fill's, 0."""
    if reading is None:
        slip, slip_out, spread, exhausted = float(flat_slip), float(flat_slip), 0.0, False
    else:
        slip = float(reading["buy"] if side == 1 else reading["sell"])
        slip_out = float(reading["sell"] if side == 1 else reading["buy"])
        spread, exhausted = float(reading["spread"]), bool(reading["exhausted"])
    if entry == "limit":
        in_fee = float(maker_fee if maker_fee is not None else fee)
        out = cost_verdict(tp=tp, sl=sl, spread=spread, slippage=slip_out / 2.0,
                           fee=(in_fee + fee) / 2.0,
                           fund_cost=fund_day * hold_s / 86400.0,
                           fund_per_day=fund_day, fund_known=True, hold_s=hold_s,
                           liq=liq, exhausted=exhausted)
        return {**out, "slippage": 0.0, "measured": reading is not None}
    out = cost_verdict(tp=tp, sl=sl, spread=spread,
                       slippage=slip, fee=fee, fund_cost=fund_day * hold_s / 86400.0,
                       fund_per_day=fund_day, fund_known=True, hold_s=hold_s,
                       liq=liq, exhausted=exhausted)
    return {**out, "slippage": slip, "measured": reading is not None}
```

- [ ] **Step 5: Implement — `entry_refusal`.** Make three changes and keep everything else, including its docstring.

First, the signature:

```python
def entry_refusal(reading: dict | None, *, side: int, signal_close: float,
                  tp: float, sl: float, fee: float, hold_s: float, liq,
                  fund_day: float, flat_slip: float = 0.0,
                  closed: bool = False, entry: str = "market",
                  maker_fee: float | None = None) -> tuple[str, dict]:
```

Second, add one docstring line after its last paragraph: `A waiting order (entry="limit", Backtest v3, Oct 22, 2026) is never a chase: it fills at its own price or is missed.` Then change the `minute_verdict` call:

```python
    cv = minute_verdict(reading, side=side, tp=tp, sl=sl, fee=fee, hold_s=hold_s,
                        liq=liq, fund_day=fund_day, flat_slip=flat_slip,
                        entry=entry, maker_fee=maker_fee)
```

Third, the chase guard gains its first condition:

```python
    if (entry != "limit"
            and reading is not None
            and book_age_s(reading) <= CHASE_READING_MAX_AGE_S
            and not chase_ok(side, float(signal_close),
                             float(reading["ask"] if side == 1 else reading["bid"]),
                             sl)[0]):
        return "chase_skip", cv
```

- [ ] **Step 6: Implement — `settle_in_minutes`.** Make two changes.

First, add `tp_through: bool = False` after `span` in the signature, and append this paragraph to its docstring:

```
    ``tp_through=True`` is a target that RESTS as a waiting order (Backtest
    v3, Oct 22, 2026): it is reached only when a minute trades through it —
    a long's high strictly above, a short's low strictly below. False is the
    rule of before, byte for byte.
```

Second, in the loop, replace

```python
        if s == 1:
            t_, s_ = h >= tp_px, lw <= sl_px
            q_ = liq_px is not None and lw <= liq_px
        else:
            t_, s_ = lw <= tp_px, h >= sl_px
            q_ = liq_px is not None and h >= liq_px
```

with

```python
        if s == 1:
            t_ = h > tp_px if tp_through else h >= tp_px
            s_ = lw <= sl_px
            q_ = liq_px is not None and lw <= liq_px
        else:
            t_ = lw < tp_px if tp_through else lw <= tp_px
            s_ = h >= sl_px
            q_ = liq_px is not None and h >= liq_px
```

- [ ] **Step 7: Run the tests, then check that nothing before them moved**

Run: `.venv/Scripts/python -m pytest tests/test_v3_shared_rules_learn_the_waiting_order.py tests/test_minute_exact_exits.py tests/test_room_replay_settles_by_the_minute.py tests/test_cost_verdict_is_the_runners.py tests/test_the_replay_shard.py tests/test_backtest_pays_the_minute.py tests/test_gate_runner_costs.py -q`
Expected: all pass.

- [ ] **Step 8: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/auto_trader.py tests/test_v3_shared_rules_learn_the_waiting_order.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message: `feat(v3): the runner's cost check, the minute settle and the fee floor learn the waiting order - maker_fee_floor beside fee_floor (Gate +0.02%, never the rebate), a limit entry pays maker in and taker+gap out and is never a chase, a resting target needs a trade-through; every default unchanged`

---

### Task 4: The v3 engine

**Files:**
- Create: `tradingagents/v3_engine.py`
- Test: `tests/test_v3_engine.py`

**Interfaces:**
- Consumes:
  - everything in Task 2;
  - from Task 3: `auto_trader.settle_in_minutes(tp_through=True)` and `auto_trader.entry_refusal(entry="limit"|"market", maker_fee=)`;
  - existing code: `auto_trader.funding_day_at`, `auto_trader.FUNDING_HOLD_BARS`, `auto_trader.book_fill_price` and `book_history.reading_at`.
- Produces:
  - `COUNT_KEYS = ("missed", "unsafe_stop", "too_small", "no_levels", "gate_blocked", "chase_skip", "closed_skip", "cost_unmeasured", "funding_estimated", "settled_by_candle", "fill_by_candle", "unclear", "no_next_bar")`
  - `walk(bars, dirs, exit_spec, *, bar_s, contract, fees, fine=None, risk_usd=RISK_USD, book=None, flat_slip=0.0, funding=None, start=0, closed=None, cost_check=True) -> {"trades", "missed", "counts"}`. Its inputs:
    - `bars`: `{"t" (candle opens, ms), "o", "h", "l", "c"}`
    - `fine`: `(point opens ms, highs, lows)`
    - `contract`: `{"contract_size", "min_vol", "mmr", "max_lev", "min_lev"?}`
    - `fees`: `{"maker", "taker"}`
    - `funding`: `[{"settle_ms", "rate", "cycle_h"}]`
    - `closed`: per-candle flags or None
  - `exit_spec` takes one of three shapes:
    - `{"kind": "fixed", "tp", "sl"}`
    - `{"kind": "trail", "atr_mult", "ma_n" | None}`
    - `{"kind": "snap", "mean_n", "stop_atr", "max_bars"}`
  - A trade has the keys `side`, `signal_bar`, `entry_bar`, `entry_ms`, `entry`, `contracts`, `notional`, `leverage`, `margin`, `exit_ms`, `exit`, `why` (TP, SL, TRAIL, MA, TIME or END), `fee_in`, `fee_out`, `slip_out`, `funding`, `pnl`, `measured_exit`, `funding_estimated` and `exit_bar`.
  - A missed trade has the keys `side`, `signal_bar`, `signal_ms`, `limit` and `market`. `market` is the twin trade dict (with `entry`, `entry_ms`, `notional` and the exit keys), or `{"refused": why}`.

- [ ] **Step 1: Write the failing test** — `tests/test_v3_engine.py`. Every candle is built from its own minutes, and every number was worked by hand before it was written down:

```python
"""The Backtest v3 engine (spec docs/superpowers/specs/2026-10-22-backtest-
v3-design.md, Part 3). Every candle is BUILT from its own minutes, so the
candles, the minutes and the trades share ONE timeline (RCA-2026-09-12-A):
never hand-write a candle that its minutes disagree with."""
import pytest

from tradingagents import v3_engine as ve

M = 60_000
H = 3_600_000
T0 = 1_790_000_000_000 - (1_790_000_000_000 % H)
CONTRACT = {"contract_size": 0.01, "min_vol": 1, "mmr": 0.005, "max_lev": 20}
FEES = {"maker": 0.0002, "taker": 0.00075}
FLAT = [(100.1, 99.9)] * 60                      # an hour that closes at 100.0
FIXED = {"kind": "fixed", "tp": 0.01, "sl": 0.02}


def _world(hours):
    """hours: one list of 60 (high, low) minutes per hour -> (bars, fine)."""
    t, hi, lo = [], [], []
    bars = {"t": [], "o": [], "h": [], "l": [], "c": []}
    for k, minutes in enumerate(hours):
        for m, (h_, l_) in enumerate(minutes):
            t.append(T0 + k * H + m * M)
            hi.append(h_)
            lo.append(l_)
        bars["t"].append(T0 + k * H)
        bars["o"].append(sum(minutes[0]) / 2)
        bars["h"].append(max(x[0] for x in minutes))
        bars["l"].append(min(x[1] for x in minutes))
        bars["c"].append(sum(minutes[-1]) / 2)
    return bars, (t, hi, lo)


def _fixed_world(fill_hour, *later):
    """Hour 0 closes at 100.0 (the signal); hour 1 is the fill window."""
    return _world([FLAT, fill_hour, *later])


def _walk(bars, dirs, spec=FIXED, **kw):
    kw = {"contract": CONTRACT, "fees": FEES, "cost_check": False, **kw}
    return ve.walk(bars, dirs, spec, bar_s=3600, **kw)


def test_a_long_fills_only_on_a_trade_through_and_wins_at_a_resting_target():
    fill_hour = [(100.1, 99.9)] * 10 + [(100.0, 99.95)] + [(100.5, 100.0)] * 49
    bars, fine = _fixed_world(fill_hour, [(101.5, 100.5)] + [(101.6, 101.0)] * 59)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["entry_ms"] == T0 + H, "minute 0 of the fill hour traded below 100.0"
    assert tr["why"] == "TP" and tr["exit"] == pytest.approx(101.0)
    # a 2% stop at $1 risk: $50 of coin = 50 lots of 0.01 at $100
    assert tr["contracts"] == 50 and tr["notional"] == pytest.approx(50.0)
    # +1% of $50 = +0.50, less the maker fee in and out on $50
    assert tr["pnl"] == pytest.approx(0.50 - 50.0 * 0.0004)


def test_a_short_fills_above_its_limit_and_wins_below():
    fill_hour = [(100.1, 99.9)] + [(99.95, 99.5)] * 59        # minute 0 trades above 100.0
    bars, fine = _fixed_world(fill_hour, [(99.5, 98.5)] * 60)
    (tr,) = _walk(bars, [-1, 0, 0], fine=fine)["trades"]
    assert tr["side"] == -1 and tr["why"] == "TP" and tr["exit"] == pytest.approx(99.0)
    assert tr["pnl"] == pytest.approx(0.50 - 50.0 * 0.0004)


def test_an_order_that_only_touches_is_missed_and_its_market_twin_is_kept():
    bars, fine = _fixed_world([(100.2, 100.0)] * 60, [(101.5, 100.5)] * 60)
    got = _walk(bars, [1, 0, 0], fine=fine)
    assert got["trades"] == [] and got["counts"]["missed"] == 1
    (m,) = got["missed"]
    assert m["limit"] == pytest.approx(100.0) and m["market"]["why"] == "TP"
    assert m["market"]["entry"] == pytest.approx(100.1), "the next candle's open"
    assert m["market"]["fee_in"] == pytest.approx(0.00075), "a market entry pays the taker fee"


def test_the_minute_an_order_fills_in_can_stop_it_but_cannot_win_it():
    # minute 0 trades 101.5 AND 99.5: the high may have come before the fill
    fill_hour = [(101.5, 99.5)] + [(100.5, 100.2)] * 59
    bars, fine = _fixed_world(fill_hour, [(100.3, 97.5)] * 60)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H
    # a long passes its limit on the way down to its stop, so that minute CAN stop it
    bars, fine = _fixed_world([(100.1, 97.5)] + [(99.0, 98.5)] * 59, [(101.5, 100.5)] * 60)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + H


def test_a_stop_the_price_jumped_past_is_booked_where_the_price_was():
    fill_hour = [(100.1, 99.5)] + [(99.9, 99.6)] * 59
    bars, fine = _fixed_world(fill_hour, [(97.0, 96.0)] + [(96.5, 96.0)] * 59)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit"] == pytest.approx(97.0), "nothing traded at 98.0"


def test_a_trailing_stop_follows_the_move_and_exits_at_the_trail():
    signal = [(100.1, 99.8)] + [(100.1, 99.9)] * 59           # closes at 100.0
    up = [(100.05 + 0.1 * m, 99.8 + 0.1 * m) for m in range(60)]   # fills at minute 0, climbs
    drop = [(105.9, 104.0)] + [(104.5, 98.0)] * 59             # trades down through the trail
    bars, fine = _world([FLAT] * 21 + [signal, up, drop])
    (tr,) = _walk(bars, [0] * 21 + [1, 0, 0], {"kind": "trail", "atr_mult": 3.0, "ma_n": None},
                  fine=fine)["trades"]
    # ATR(20) at the signal is 0.205, so the trail sits 0.615 under the highs:
    # 105.95 - 0.615 = 105.335 when the drop starts
    assert tr["why"] == "TRAIL" and tr["exit"] == pytest.approx(105.335)
    assert tr["exit_ms"] == T0 + 23 * H


def test_a_trend_trade_also_leaves_at_a_close_on_the_wrong_side_of_its_average():
    signal = [(100.1, 99.8)] + [(100.1, 99.9)] * 59
    sag = [(100.1, 99.8)] + [(99.8, 99.6)] * 59                # fills, then closes at 99.7
    bars, fine = _world([FLAT] * 21 + [signal, sag])
    (tr,) = _walk(bars, [0] * 21 + [1, 0], {"kind": "trail", "atr_mult": 3.0, "ma_n": 3},
                  fine=fine)["trades"]
    # the 3-candle average at that close is (100 + 100 + 99.7) / 3 = 99.9, above it
    assert tr["why"] == "MA" and tr["exit"] == pytest.approx(99.7)
    assert tr["exit_ms"] == T0 + 23 * H


def test_a_snap_back_rests_its_target_at_the_average_and_leaves_on_time():
    dip = [(100.0, 96.9)] + [(97.2, 96.9)] * 59      # closes at 97.05, under its average
    fill = [(97.2, 97.0)] + [(97.3, 97.1)] * 59      # buys at 97.05 in minute 0
    spec = {"kind": "snap", "mean_n": 20, "stop_atr": 3.0, "max_bars": 2}
    bars, fine = _world([FLAT] * 20 + [dip, fill, [(97.5, 97.2)] * 60])
    (tr,) = _walk(bars, [0] * 20 + [1, 0, 0], spec, fine=fine)["trades"]
    assert tr["why"] == "TIME" and tr["exit"] == pytest.approx(97.35)
    assert tr["exit_ms"] == T0 + 23 * H, "out at the close of its second candle"
    bars, fine = _world([FLAT] * 20 + [dip, fill, [(100.0, 97.2)] * 60])
    (tr,) = _walk(bars, [0] * 20 + [1, 0, 0], spec, fine=fine)["trades"]
    assert tr["why"] == "TP" and tr["exit"] == pytest.approx((19 * 100.0 + 97.05) / 20)


def test_a_signal_on_the_last_candle_places_no_order():
    bars, fine = _world([FLAT, FLAT])
    got = _walk(bars, [0, 1], fine=fine)
    assert got["trades"] == [] and got["counts"]["no_next_bar"] == 1


def test_a_candle_with_no_minutes_keeps_the_candle_rule_and_is_counted():
    bars, _fine = _fixed_world([(100.2, 99.5)] * 60, [(101.5, 97.0)] * 60)
    got = _walk(bars, [1, 0, 0], fine=None)
    (tr,) = got["trades"]
    assert got["counts"]["fill_by_candle"] == 1 and got["counts"]["settled_by_candle"] == 1
    assert tr["why"] == "SL" and got["counts"]["unclear"] == 1, "both in one candle is the stop"


def test_a_stop_no_leverage_keeps_safe_and_a_trade_under_one_lot_are_skipped():
    bars, fine = _fixed_world([(100.1, 99.0)] * 60, [(101.5, 100.5)] * 60)
    wide = _walk(bars, [1, 0, 0], {"kind": "fixed", "tp": 0.9, "sl": 0.85}, fine=fine)
    assert wide["trades"] == [] and wide["counts"]["unsafe_stop"] == 1
    big_lot = {**CONTRACT, "contract_size": 1.0}            # one lot = $100 of coin
    small = _walk(bars, [1, 0, 0], fine=fine, contract=big_lot)
    assert small["trades"] == [] and small["counts"]["too_small"] == 1


def test_a_market_exit_pays_the_taker_fee_and_the_flat_gap_when_no_book_was_recorded():
    bars, fine = _fixed_world([(100.1, 99.0)] * 60, [(100.0, 97.5)] * 60)
    got = _walk(bars, [1, 0, 0], {"kind": "fixed", "tp": 0.03, "sl": 0.02}, fine=fine,
                flat_slip=0.0005)
    (tr,) = got["trades"]
    assert tr["why"] == "SL" and tr["fee_out"] == pytest.approx(0.00075)
    assert tr["slip_out"] == pytest.approx(0.0005) and tr["measured_exit"] is False
    assert got["counts"]["cost_unmeasured"] == 1
    assert tr["pnl"] == pytest.approx(-1.0 - 50.0 * (0.0002 + 0.00075 + 0.0005))


def test_funding_before_the_history_is_estimated_and_counted():
    bars, fine = _fixed_world([(100.1, 99.0)] * 60, [(101.5, 100.5)] * 60)
    fund = [{"settle_ms": T0 + 100 * H, "rate": 0.0001, "cycle_h": 8}]
    got = _walk(bars, [1, 0, 0], fine=fine, funding=fund)
    assert got["counts"]["funding_estimated"] == 1
    assert got["trades"][0]["funding_estimated"] is True


def test_the_cost_check_refuses_what_the_runner_would_refuse():
    bars, fine = _fixed_world([(100.1, 99.0)] * 60, [(101.5, 100.5)] * 60)
    # a 0.5% gap out against a 1% target: maker 0.02% + taker 0.075% + 0.5% is
    # 0.595% of a 1% target, past the runner's 50% line
    got = _walk(bars, [1, 0, 0], fine=fine, flat_slip=0.005, cost_check=True)
    assert got["trades"] == [] and got["counts"]["gate_blocked"] == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_v3_engine.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.v3_engine'`

- [ ] **Step 3: Implement** — `tradingagents/v3_engine.py`:

```python
"""THE BACKTEST V3 ENGINE — one strategy's trades the v3 way.

Spec: docs/superpowers/specs/2026-10-22-backtest-v3-design.md, Part 3
(operator, Oct 22, 2026: "i want to do backtest v3 where you will create the
strategy for the research you made"); plan:
docs/superpowers/plans/2026-10-22-backtest-v3-part1-engine.md.

For each signal candle: a waiting order at its close, filled only when a
point of the NEXT candle trades through it (`v3_rules.limit_fill`); never
filled = a missed trade, kept with what a market entry would have made. A
filled trade risks `risk_usd` at a leverage that keeps its stop safe
(`v3_rules.risk_size`) and exits by its idea's own rule:

* ``trail``: a trailing stop `atr_mult` x ATR(20) (`v3_rules.trail_walk`),
  and, with `ma_n`, out at a candle close on the wrong side of its average;
* ``fixed``: a target resting as a waiting order (traded through, maker fee)
  and a stop at the market — the re-tested v2 rows;
* ``snap``: the `mean_n`-candle average at the signal as a resting target,
  an emergency stop `stop_atr` x ATR, and out at the close of the
  `max_bars`-th candle.

POINTS are Gate's minutes, or its 5-minute bars where the archive has a hole
(`backtest_report.fine_bars`). The point an order fills in can stop the
trade but can neither win it nor move its trail: its high may have come
before the fill (CLAUDE.md "A fill may only see price the order was exposed
to"). A stop the price jumped past fills at the best price that point traded
(`v3_rules.stop_fill`). A whole candle with no points keeps the candle rule,
counted; the rest of a candle with no points left is spent, never re-read.

Costs on every trade, all on the entry's notional: the maker fee in; out,
the maker fee at a resting target, else the taker fee plus the exit minute's
recorded gap; funding by settlement. What the engine could not measure is
COUNTED (`COUNT_KEYS`), never hidden. The runner's own cost check is asked
at the minute each order goes in (`auto_trader.entry_refusal(entry="limit")`).
"""
from __future__ import annotations

import bisect

from tradingagents import v3_rules as vr

# missed: the waiting order never traded through · unsafe_stop: no leverage
# keeps the stop inside the liquidation ceiling · too_small: under one lot at
# the risk · no_levels: ATR or the average not ready, or a snap whose average
# is behind it · gate_blocked / chase_skip / closed_skip: the runner's own
# answer · cost_unmeasured: an exit that paid the coin's flat gap ·
# funding_estimated: a hold (partly) before the funding history ·
# settled_by_candle / fill_by_candle: decided by the candle rule, no points ·
# unclear: stop and target in one point, booked as the stop · no_next_bar: a
# signal on the last candle
COUNT_KEYS = ("missed", "unsafe_stop", "too_small", "no_levels", "gate_blocked",
              "chase_skip", "closed_skip", "cost_unmeasured", "funding_estimated",
              "settled_by_candle", "fill_by_candle", "unclear", "no_next_bar")


def _span(fine, a_ms: int, b_ms: int) -> tuple[int, int]:
    return bisect.bisect_left(fine[0], a_ms), bisect.bisect_left(fine[0], b_ms)


def _has_points(fine, a_ms: int, b_ms: int) -> bool:
    if fine is None:
        return False
    a, b = _span(fine, a_ms, b_ms)
    return a < b


def _levels(kind: str, spec: dict, s: int, entry: float, atr_i, mean_i) -> dict | None:
    """The trade's stop, target and trail distance from its own exit rule;
    None = it cannot trade yet (ATR or the average not ready, or a snap whose
    average is not on the winning side)."""
    if kind == "fixed":
        return {"stop": entry * (1 - s * float(spec["sl"])),
                "target": entry * (1 + s * float(spec["tp"])), "trail": None}
    if atr_i is None or atr_i <= 0:
        return None
    if kind == "trail":
        d = float(spec.get("atr_mult", vr.TRAIL_ATR)) * atr_i
        return {"stop": entry - s * d, "target": None, "trail": d}
    if kind == "snap":
        if mean_i is None or s * (mean_i - entry) <= 0:
            return None
        d = float(spec.get("stop_atr", vr.TRAIL_ATR)) * atr_i
        return {"stop": entry - s * d, "target": mean_i, "trail": None}
    raise ValueError(f"unknown exit kind {kind!r}")


def _target_frac(levels: dict, entry: float) -> float:
    """What the cost check weighs the cost against: the target's distance, or
    for a trend trade with no target its first risk (1R)."""
    if levels["target"] is not None:
        return abs(levels["target"] - entry) / entry
    return abs(entry - levels["stop"]) / entry


def _size(entry: float, stop: float, ctx: dict) -> tuple[dict | None, str]:
    """The size that risks `risk_usd`, or (None, the count that says why not)."""
    c = ctx["contract"]
    if vr.safe_leverage(abs(entry - stop) / entry, float(c["mmr"]), int(c["max_lev"]),
                        int(c.get("min_lev", 1))) is None:
        return None, "unsafe_stop"
    size = vr.risk_size(ctx["risk_usd"], entry, stop,
                        contract_size=float(c["contract_size"]), min_vol=int(c["min_vol"]),
                        mmr=float(c["mmr"]), max_lev=int(c["max_lev"]),
                        min_lev=int(c.get("min_lev", 1)))
    return (size, "") if size is not None else (None, "too_small")


def _ask_runner(s: int, i: int, tp_frac: float, size: dict, ctx: dict, entry: str) -> str:
    """The runner's own answer at the minute an order goes in, seconds after
    candle `i` closed (`auto_trader.entry_refusal`); "" = it would place it."""
    import tradingagents.auto_trader as at
    from tradingagents import book_history as bh

    place_ms = int(ctx["t"][i + 1])
    book, closed = ctx["book"], ctx["closed"]
    r = bh.reading_at(book, place_ms // 1000) if book is not None else None
    why, _cv = at.entry_refusal(
        r, side=s, signal_close=ctx["c"][i], tp=tp_frac, sl=size["stop_frac"],
        fee=float(ctx["fees"]["taker"]), hold_s=ctx["bar_s"] * at.FUNDING_HOLD_BARS,
        liq=max(0.0, 1.0 / size["leverage"] - float(ctx["contract"]["mmr"])),
        fund_day=at.funding_day_at(ctx["f_ms"], ctx["f_rate"], ctx["f_cyc"], place_ms, s),
        flat_slip=ctx["flat_slip"],
        closed=bool(closed[i]) if closed is not None else False,
        entry=entry, maker_fee=float(ctx["fees"]["maker"]))
    return why


def _fill(s: int, limit: float, ctx: dict, i: int) -> int | None:
    """When the waiting order of candle `i` traded through, inside candle i+1."""
    fine, t = ctx["fine"], ctx["t"]
    a_ms, b_ms = int(t[i + 1]), int(t[i + 1]) + ctx["bar_ms"]
    if _has_points(fine, a_ms, b_ms):
        return vr.limit_fill(s, limit, fine[0], fine[1], fine[2], a_ms, b_ms)
    ctx["counts"]["fill_by_candle"] += 1
    through = ctx["lo"][i + 1] < limit if s == 1 else ctx["hi"][i + 1] > limit
    return a_ms if through else None


def _stopped(s: int, stop: float, hi: float, lo: float) -> bool:
    return lo <= stop if s == 1 else hi >= stop


def _fill_point(s: int, stop: float, fill_ms: int, j: int, ctx: dict):
    """The point a waiting order filled in can STOP the trade — a long's price
    passes its limit on the way down to its stop, so the order was filled
    first — but cannot win it or move its trail: its high may have come
    before the fill. Returns (the stop exit or None, where the walk resumes)."""
    fine = ctx["fine"]
    b_ms = int(ctx["t"][j]) + ctx["bar_ms"]
    by_points = _has_points(fine, fill_ms, b_ms)
    if by_points:
        k = bisect.bisect_left(fine[0], fill_ms)
        hi, lo, resume = fine[1][k], fine[2][k], fill_ms + 1
    else:
        hi, lo, resume = ctx["hi"][j], ctx["lo"][j], b_ms
    if not _stopped(s, stop, hi, lo):
        return None, resume
    if not by_points:
        ctx["counts"]["settled_by_candle"] += 1
    return (fill_ms, vr.stop_fill(s, stop, hi, lo), "SL"), resume


def _fixed_bar(s: int, tp_px: float, sl_px: float, a_ms: int, b_ms: int, j: int,
               ctx: dict, whole: bool):
    """A stop at the market and a target resting as a waiting order over
    [a_ms, b_ms) of candle `j`: the points say which came first
    (`settle_in_minutes(tp_through=True)`); a WHOLE candle with no points
    keeps the candle rule, counted; the rest of a candle with no points left
    is spent. Returns (exit ms, price, why) or None."""
    import tradingagents.auto_trader as at

    fine, counts = ctx["fine"], ctx["counts"]
    hi, lo = ctx["hi"][j], ctx["lo"][j]
    reach_sl = lo <= sl_px if s == 1 else hi >= sl_px
    reach_tp = hi > tp_px if s == 1 else lo < tp_px
    if not (reach_sl or reach_tp):
        return None
    if _has_points(fine, a_ms, b_ms):
        got = at.settle_in_minutes(fine[0], fine[1], fine[2], a_ms, 0, s, tp_px, sl_px,
                                   None, liq=None, sl=0.0, span=_span(fine, a_ms, b_ms),
                                   tp_through=True)
        if got is None or got[0] == "NONE":
            return None
        counts["unclear"] += int(got[2])
        if got[0] == "TP":
            return got[1], tp_px, "TP"
        k = bisect.bisect_left(fine[0], got[1])
        return got[1], vr.stop_fill(s, sl_px, fine[1][k], fine[2][k]), "SL"
    if not whole:
        return None
    counts["settled_by_candle"] += 1
    if reach_sl:
        counts["unclear"] += int(reach_tp)
        return int(ctx["t"][j]), vr.stop_fill(s, sl_px, hi, lo), "SL"
    return int(ctx["t"][j]), tp_px, "TP"


def _trail_bar(s: int, stop: float, dist: float, a_ms: int, b_ms: int, j: int,
               ctx: dict, whole: bool) -> tuple[int | None, float]:
    """The trailing stop over [a_ms, b_ms) of candle `j`, point by point; a
    WHOLE candle with no points is walked as one point, counted when it
    decides the exit; the rest of a candle with no points left is spent."""
    fine = ctx["fine"]
    if _has_points(fine, a_ms, b_ms):
        return vr.trail_walk(s, stop, dist, fine[0], fine[1], fine[2], a_ms, b_ms)
    if not whole:
        return None, stop
    t0 = int(ctx["t"][j])
    ms, px = vr.trail_walk(s, stop, dist, [t0], [ctx["hi"][j]], [ctx["lo"][j]], t0, t0 + 1)
    if ms is not None:
        ctx["counts"]["settled_by_candle"] += 1
    return ms, px


def _close(s: int, entry: float, entry_ms: int, exit_px: float, exit_ms: int, why: str,
           size: dict, fee_in: float, ctx: dict) -> dict:
    """The trade's money: the price move, the fees, the exit's gap, funding."""
    from tradingagents import book_history as bh

    counts, fees, book = ctx["counts"], ctx["fees"], ctx["book"]
    notional = size["notional"]
    if why == "TP":
        fee_out, slip_out, measured = float(fees["maker"]), 0.0, True
    else:
        r = bh.reading_at(book, int(exit_ms) // 1000) if book is not None else None
        fee_out = float(fees["taker"])
        if r is None:
            slip_out, measured = ctx["flat_slip"], False
            counts["cost_unmeasured"] += 1
        else:
            slip_out, measured = float(r["sell"] if s == 1 else r["buy"]), True
    paid, estimated = vr.funding_paid(ctx["f_ms"], ctx["f_rate"], ctx["f_cyc"], s,
                                      int(entry_ms), int(exit_ms))
    counts["funding_estimated"] += int(estimated)
    gross = notional * s * (exit_px / entry - 1.0)
    pnl = gross - notional * (fee_in + fee_out + slip_out) - notional * paid
    return {"exit_ms": int(exit_ms), "exit": float(exit_px), "why": why,
            "fee_in": fee_in, "fee_out": fee_out, "slip_out": slip_out,
            "funding": -notional * paid, "pnl": pnl, "measured_exit": measured,
            "funding_estimated": estimated}


def _trade(s: int, entry: float, entry_ms: int, entry_bar: int, levels: dict, size: dict,
           fee_in: float, ctx: dict, *, partial: bool) -> dict:
    """One trade walked candle by candle until its exit rule fires.
    `partial`: a waiting order filled INSIDE its first point (`_fill_point`);
    a market entry at a candle's open is exposed to all of it."""
    t, c, n, bar_ms = ctx["t"], ctx["c"], len(ctx["c"]), ctx["bar_ms"]
    kind, spec, ma = ctx["kind"], ctx["spec"], ctx["ma"]
    stop, walk_from = levels["stop"], int(entry_ms)

    def done(hit, j):
        return {**_close(s, entry, entry_ms, hit[1], hit[0], hit[2], size, fee_in, ctx),
                "exit_bar": j}

    if partial:
        hit, walk_from = _fill_point(s, stop, int(entry_ms), entry_bar, ctx)
        if hit is not None:
            return done(hit, entry_bar)
    for j in range(entry_bar, n):
        a_ms, b_ms = max(walk_from, int(t[j])), int(t[j]) + bar_ms
        whole, hit = a_ms == int(t[j]), None
        if a_ms < b_ms:
            if kind == "trail":
                ms, px = _trail_bar(s, stop, levels["trail"], a_ms, b_ms, j, ctx, whole)
                if ms is None:
                    stop = px
                else:
                    hit = (ms, px, "TRAIL")
            else:
                hit = _fixed_bar(s, levels["target"], stop, a_ms, b_ms, j, ctx, whole)
        if (hit is None and kind == "trail" and ma is not None and ma[j] is not None
                and s * (c[j] - ma[j]) < 0):
            hit = (b_ms, c[j], "MA")
        if hit is None and kind == "snap" and j - entry_bar + 1 >= int(spec.get("max_bars", 24)):
            hit = (b_ms, c[j], "TIME")
        if hit is not None:
            return done(hit, j)
    return done((int(t[n - 1]) + bar_ms, c[n - 1], "END"), n - 1)


def _market_twin(s: int, i: int, levels: dict, ctx: dict) -> dict:
    """What a missed trade would have made entered at the market, the way
    Backtest v2 enters: the recorded best ask (a long) or bid (a short) of the
    minute the next candle opened, else that candle's open plus the minute's
    gap (`auto_trader.book_fill_price`), the taker fee, and the same stop
    distance, trail and target. {"refused": why} when the runner would not
    have entered at the market either. Its counts go to a scratch tally, so
    the real counts only count real trades."""
    import tradingagents.auto_trader as at
    from tradingagents import book_history as bh

    entry_ms, book = int(ctx["t"][i + 1]), ctx["book"]
    r = bh.reading_at(book, entry_ms // 1000) if book is not None else None
    px = at.book_fill_price(r, s)
    if px is not None:
        entry, slip_in = px, 0.0
    else:
        entry = ctx["o"][i + 1]
        slip_in = (float(r["buy"] if s == 1 else r["sell"]) if r is not None
                   else ctx["flat_slip"])
    if ctx["kind"] == "fixed":
        tw = _levels("fixed", ctx["spec"], s, entry, None, None)
    else:
        dist = abs(ctx["c"][i] - levels["stop"])
        tw = {"stop": entry - s * dist, "target": levels["target"], "trail": levels["trail"]}
        if tw["target"] is not None and s * (tw["target"] - entry) <= 0:
            return {"refused": "no_levels"}
    size, why = _size(entry, tw["stop"], ctx)
    if size is None:
        return {"refused": why}
    if ctx["cost_check"]:
        why = _ask_runner(s, i, _target_frac(tw, entry), size, ctx, "market")
        if why:
            return {"refused": why}
    scratch = {**ctx, "counts": dict.fromkeys(COUNT_KEYS, 0)}
    fee_in = float(ctx["fees"]["taker"]) + slip_in
    tr = _trade(s, entry, entry_ms, i + 1, tw, size, fee_in, scratch, partial=False)
    return {"entry": entry, "entry_ms": entry_ms, "notional": size["notional"], **tr}


def walk(bars: dict, dirs, exit_spec: dict, *, bar_s: int, contract: dict, fees: dict,
         fine=None, risk_usd: float = vr.RISK_USD, book=None, flat_slip: float = 0.0,
         funding=None, start: int = 0, closed=None, cost_check: bool = True) -> dict:
    """Every trade of one strategy the v3 way (see the module doc).

    bars: {"t" (candle opens, ms), "o", "h", "l", "c"} · dirs: +1/-1/0 per
    candle · fine: (point opens ms, highs, lows) or None · contract:
    {"contract_size", "min_vol", "mmr", "max_lev", "min_lev"?} · fees:
    {"maker", "taker"} · book: book_history's packed readings or None ·
    flat_slip: the coin's gap where no reading exists · funding:
    [{"settle_ms", "rate", "cycle_h"}] oldest first · start: the first candle
    whose signal may trade · closed: per-candle "the market was closed"
    flags (the runner's rule, worked out by the caller) or None.
    Returns {"trades": [...], "missed": [...], "counts": {COUNT_KEYS}}.
    """
    t, hi, lo, c = bars["t"], bars["h"], bars["l"], bars["c"]
    n, kind, f = len(c), exit_spec["kind"], funding or []
    counts = dict.fromkeys(COUNT_KEYS, 0)
    ctx = {"t": t, "o": bars["o"], "hi": hi, "lo": lo, "c": c, "bar_s": int(bar_s),
           "bar_ms": int(bar_s) * 1000, "kind": kind, "spec": exit_spec, "fine": fine,
           "fees": fees, "book": book, "flat_slip": float(flat_slip),
           "f_ms": [int(x["settle_ms"]) for x in f], "f_rate": [float(x["rate"]) for x in f],
           "f_cyc": [float(x.get("cycle_h") or 8) for x in f], "counts": counts,
           "contract": contract, "closed": closed, "cost_check": bool(cost_check),
           "risk_usd": float(risk_usd),
           "ma": vr.sma(c, int(exit_spec["ma_n"])) if exit_spec.get("ma_n") else None}
    atr_ = vr.atr(hi, lo, c, vr.ATR_N)
    mean = vr.sma(c, int(exit_spec.get("mean_n", 20))) if kind == "snap" else None
    trades, missed = [], []
    i = max(0, int(start))
    while i < n:
        s = int(dirs[i]) if i < len(dirs) else 0
        if s == 0:
            i += 1
            continue
        if i + 1 >= n:
            counts["no_next_bar"] += 1
            break
        levels = _levels(kind, exit_spec, s, c[i], atr_[i],
                         mean[i] if mean is not None else None)
        if levels is None:
            counts["no_levels"] += 1
            i += 1
            continue
        size, why = _size(c[i], levels["stop"], ctx)
        if size is not None and cost_check:
            why = _ask_runner(s, i, _target_frac(levels, c[i]), size, ctx, "limit")
        if why:
            counts[why] += 1
            i += 1
            continue
        fill_ms = _fill(s, c[i], ctx, i)
        if fill_ms is None:
            counts["missed"] += 1
            missed.append({"side": s, "signal_bar": i, "signal_ms": int(t[i]),
                           "limit": c[i], "market": _market_twin(s, i, levels, ctx)})
            i += 1
            continue
        tr = _trade(s, c[i], fill_ms, i + 1, levels, size, float(fees["maker"]), ctx,
                    partial=True)
        trades.append({"side": s, "signal_bar": i, "entry_bar": i + 1,
                       "entry_ms": int(fill_ms), "entry": c[i],
                       "contracts": size["contracts"], "notional": size["notional"],
                       "leverage": size["leverage"], "margin": size["margin"], **tr})
        if tr["why"] == "END":
            break
        i = tr["exit_bar"]          # a candle a trade closed in may signal again
    return {"trades": trades, "missed": missed, "counts": counts}
```

- [ ] **Step 4: Run the tests to verify they pass, then lint**

Run: `.venv/Scripts/python -m pytest tests/test_v3_engine.py tests/test_v3_rules.py tests/test_v3_shared_rules_learn_the_waiting_order.py -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_engine.py tests/test_v3_engine.py`
Expected: all pass, then `All checks passed!`. If a number disagrees, work it again by hand in the test's own comment, and fix the ENGINE. Never loosen an assertion.

- [ ] **Step 5: Run the harddev hunt.** Name each check in the commit message:
  - **State:** off Gate, `cost_store.engine_book` returns None. Every market exit is then `cost_unmeasured` and counted, never free.
  - **Failure path:** `fx.funding_history` raising stops the run loudly, by design. A short funding history makes trades look cheaper than they were.
  - **Sides:** check every `s == 1` branch against its short twin.
  - **Concurrency:** `walk` keeps no state between calls.

- [ ] **Step 6: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_engine.py tests/test_v3_engine.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message: `feat(v3): the Backtest v3 engine - waiting-order entries filled on a trade-through, missed trades with their market twin, trail/fixed/snap exits settled point by point, the fill point can stop but never win, $1 risk at a safe leverage, every cost and every gap counted`

---

### Task 5: Cost coverage — how much of a window the recorded order books cover

**Files:**
- Modify: `tradingagents/cost_store.py` (add `coverage` after `with_app_books`, at the end of the module)
- Test: `tests/test_cost_coverage.py`

**Interfaces:**
- Produces: `cost_store.coverage(packed, start_s, end_s, max_age_s=None) -> float`. It returns the share of the window's minutes that have a reading at most `book_history.MAX_AGE_S` old. It returns 0.0 for an empty book or None.

- [ ] **Step 1: Write the failing test** — `tests/test_cost_coverage.py`:

```python
"""COVERAGE FIRST (CLAUDE.md "Every backtest LOOKS AT THE COSTS"; Backtest v3
spec, Part 3): before a run, the share of its minutes the recorded order
books cover is measured and printed."""
import pytest

from tradingagents import book_history as bh, cost_store as cs

T0 = 1_790_000_000 - (1_790_000_000 % 3600)


def _reading(t):
    return {"t": t, "bid": 1.0, "ask": 1.1, "spread": 0.1, "buy": 0.001, "sell": 0.001,
            "exhausted": False, "source": "full"}


def test_a_book_read_every_minute_covers_the_whole_window():
    packed = bh.pack([_reading(T0 + 60 * k) for k in range(60)])
    assert cs.coverage(packed, T0, T0 + 3600) == pytest.approx(1.0)


def test_a_reading_answers_the_hour_after_it_and_no_more():
    packed = bh.pack([_reading(T0)])
    # one reading at T0 answers the minutes T0 .. T0+3600: 61 of the window's 120
    assert cs.coverage(packed, T0, T0 + 7200) == pytest.approx(61 / 120)


def test_no_book_covers_nothing():
    assert cs.coverage(cs.empty(), T0, T0 + 3600) == 0.0
    assert cs.coverage(None, T0, T0 + 3600) == 0.0, "not on Gate: engine_book is None"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_cost_coverage.py -q`
Expected: FAIL with `AttributeError: module 'tradingagents.cost_store' has no attribute 'coverage'`

- [ ] **Step 3: Implement** — append to `tradingagents/cost_store.py`:

```python
def coverage(packed: dict | None, start_s: int, end_s: int,
             max_age_s: int | None = None) -> float:
    """The share of the minutes in [start_s, end_s) that have a recorded
    reading at most `max_age_s` old (book_history.MAX_AGE_S by default) —
    what a backtest of that window pays at its own minute rather than the
    coin's typical cost (CLAUDE.md "COVERAGE FIRST"; Backtest v3 spec). No
    book (None, or not on Gate) covers nothing."""
    import numpy as np

    from tradingagents import book_history as bh

    age = bh.MAX_AGE_S if max_age_s is None else int(max_age_s)
    t = np.asarray(packed["t"] if packed else [], dtype="int64")
    minutes = np.arange(int(start_s), int(end_s), 60, dtype="int64")
    if not len(minutes) or not len(t):
        return 0.0
    j = np.searchsorted(t, minutes, side="right") - 1
    ok = j >= 0
    ok[ok] = (minutes[ok] - t[j[ok]]) <= age
    return float(ok.mean())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_cost_coverage.py tests/test_cost_store.py -q`
Expected: all pass.

- [ ] **Step 5: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/cost_store.py tests/test_cost_coverage.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message: `feat(v3): cost coverage - the share of a window's minutes the recorded order books cover, printed before every v3 run (COVERAGE FIRST)`

---

### Task 6: One real coin the v3 way — the smoke run

**Files:**
- Create: `tradingagents/v3_smoke.py`
- Test: `tests/test_v3_smoke.py`

**Interfaces:**
- Consumes:
  - `v3_engine.walk`, `cost_store.coverage` and `cost_store.engine_book`;
  - `backtest_report.fine_bars` and `backtest_report.TFS`;
  - `fx.klines`, `fx.contract_spec` and `fx.funding_history(since_ms=)`;
  - `auto_trader._dirs_for_backtest`, `auto_trader.maker_fee_floor` and `auto_trader.fee_floor`;
  - `positions_view.fmt_when`.
- Produces:
  - `exit_spec(text) -> dict`, which reads `fixed:TP:SL`, `trail:ATR[:MA]` or `snap:ATR:BARS`.
  - `run(sym, tf, signal, spec, *, days=120, th=None, fx=None) -> dict`, with the keys `sym`, `tf`, `signal`, `exit`, `start`, `end`, `coverage`, `trades`, `wins`, `losses`, `profit`, `missed`, `missed_entered`, `missed_pnl` and `counts`.
  - The CLI `python -m tradingagents.v3_smoke SYM TF SIGNAL EXIT [--days N] [--th X]`.

- [ ] **Step 1: Write the failing test** — `tests/test_v3_smoke.py`:

```python
"""The v3 smoke run reads one coin and summarises it; under test every venue
call is a stand-in, so nothing reaches the network."""
import pandas as pd

from tradingagents import v3_smoke as sm

H = 3_600_000


class FakeFx:
    """400 closed hours at 100 (high 100.6, low 99.4), no minutes, no funding."""

    def __init__(self, n: int = 400):
        t0 = 1_790_000_000_000 - (1_790_000_000_000 % H) - n * H
        self.df = pd.DataFrame({
            "Date": pd.to_datetime([t0 + k * H for k in range(n)], unit="ms"),
            "Open": [100.0] * n, "High": [100.6] * n, "Low": [99.4] * n,
            "Close": [100.0] * n, "Volume": [1.0] * n})

    def klines(self, sym, iv, limit):
        return self.df.tail(limit).reset_index(drop=True)

    def minutes(self, sym, start_s, end_s):
        return pd.DataFrame({"Date": pd.to_datetime([], unit="s"), "High": [], "Low": []})

    def funding_history(self, sym, **kw):
        return []

    def contract_spec(self, sym):
        return {"contractSize": 0.01, "minVol": 1, "maintenanceMarginRate": 0.005,
                "maxLeverage": 20, "minLeverage": 1}


def test_the_smoke_run_summarises_one_coin_without_the_network(monkeypatch):
    import tradingagents.auto_trader as at
    from tradingagents import cost_store

    monkeypatch.setattr(at, "_dirs_for_backtest",
                        lambda key, hi, *a, **k: [1 if i % 10 == 0 else 0
                                                  for i in range(len(hi))])
    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: cost_store.empty())
    got = sm.run("TEST_USDT", "1h", "bb20", {"kind": "fixed", "tp": 0.02, "sl": 0.01},
                 days=10, fx=FakeFx())
    assert got["coverage"] == 0.0, "no recorded book covers nothing"
    # the first signal's order fills on the candle (no minutes) and never
    # reaches 99.0 or 102.0, so it is still open at the last candle
    assert got["trades"] == 1 and got["counts"]["fill_by_candle"] == 1
    assert got["start"].endswith(("am", "pm")) and ", 2026 " in got["start"]


def test_the_exit_is_read_from_its_short_form():
    assert sm.exit_spec("fixed:0.02:0.01") == {"kind": "fixed", "tp": 0.02, "sl": 0.01}
    assert sm.exit_spec("trail:3:50") == {"kind": "trail", "atr_mult": 3.0, "ma_n": 50}
    assert sm.exit_spec("snap:3:24") == {"kind": "snap", "mean_n": 20, "stop_atr": 3.0,
                                         "max_bars": 24}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_v3_smoke.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.v3_smoke'`

- [ ] **Step 3: Implement** — `tradingagents/v3_smoke.py`:

```python
"""ONE COIN THE V3 WAY, for real — Part 1's check that the engine runs on
Gate's own data before any GitHub run (Backtest v3 plan, Task 6).

    .venv/Scripts/python -m tradingagents.v3_smoke BTC_USDT 1h bb20 fixed:0.02:0.01
    .venv/Scripts/python -m tradingagents.v3_smoke BTC_USDT 1d trend50 trail:3:50 --days 365

Prints how much of the window the recorded order books cover first (COVERAGE
FIRST), then trades, wins, losses and profit at $1 risk a trade, the orders
that never filled and what entering them at the market would have made, and
every count the engine keeps. Reads only: no order, no store, no screen.
"""
from __future__ import annotations

import argparse
import time

LEAD_BARS = 300       # the lookback every stored rule reads before it can signal
FLAT_SLIP = 0.0003    # the engine's default gap a side where no book was recorded


def exit_spec(text: str) -> dict:
    """fixed:TP:SL · trail:ATR[:MA] · snap:ATR:BARS (fractions, multiples, counts)."""
    kind, *parts = text.split(":")
    if kind == "fixed" and len(parts) == 2:
        return {"kind": "fixed", "tp": float(parts[0]), "sl": float(parts[1])}
    if kind == "trail" and parts:
        return {"kind": "trail", "atr_mult": float(parts[0]),
                "ma_n": int(parts[1]) if len(parts) > 1 else None}
    if kind == "snap" and len(parts) == 2:
        return {"kind": "snap", "mean_n": 20, "stop_atr": float(parts[0]),
                "max_bars": int(parts[1])}
    raise ValueError(f"exit {text!r}: use fixed:TP:SL, trail:ATR[:MA] or snap:ATR:BARS")


def run(sym: str, tf: str, signal: str, spec: dict, *, days: int = 120,
        th: float | None = None, fx=None) -> dict:
    """One stored signal on one coin over its last `days`, the v3 way."""
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br, cost_store, v3_engine
    from tradingagents.positions_view import fmt_when

    if fx is None:
        from tradingagents.dataflows import exchange as fx
    iv, bar_s, _cap = br.TFS[tf]
    df = fx.klines(sym, iv, int(days * 86400 / bar_s) + LEAD_BARS)
    t_all = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    final = t_all + bar_s * 1000 <= int(time.time() * 1000)   # the forming candle is not final
    df, t = df[final], [int(x) for x in t_all[final]]
    bars = {"t": t, "o": [float(x) for x in df["Open"]], "h": [float(x) for x in df["High"]],
            "l": [float(x) for x in df["Low"]], "c": [float(x) for x in df["Close"]]}
    vol = [float(x) for x in df["Volume"]] if "Volume" in df.columns else None
    lead = min(LEAD_BARS, len(t) - 1)
    from_s, end_s = t[lead] // 1000, t[-1] // 1000 + bar_s
    ft, fh, fl, _n5 = br.fine_bars(sym, from_s, end_s, fx=fx)
    fine = (ft.tolist(), fh.tolist(), fl.tolist()) if len(ft) else None
    book = cost_store.engine_book(sym, from_s, end_s)
    fund = fx.funding_history(sym, since_ms=(from_s - 86400) * 1000)
    c = fx.contract_spec(sym)
    key = f"{signal}_v3_{tf}"
    at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bar_s, "tp": .02, "sl": .01,
                              "threshold": .003 if th is None else th}
    try:
        dk = "rsi14_1h" if signal == "rsi14" else key
        dirs = at._dirs_for_backtest(dk, bars["h"], bars["l"], bars["c"], opens=bars["o"],
                                     volume=vol, ts=t, funding=fund)
    finally:
        at.STRATEGY_SPECS.pop(key, None)
    got = v3_engine.walk(
        bars, dirs, spec, bar_s=bar_s,
        contract={"contract_size": float(c.get("contractSize") or 0.0),
                  "min_vol": int(c.get("minVol") or 1),
                  "mmr": float(c.get("maintenanceMarginRate") or 0.0),
                  "max_lev": int(c.get("maxLeverage") or 1),
                  "min_lev": int(c.get("minLeverage") or 1)},
        fees={"maker": at.maker_fee_floor(), "taker": at.fee_floor()},
        fine=fine, book=book, flat_slip=FLAT_SLIP, funding=fund, start=lead)
    trades = got["trades"]
    twins = [m["market"] for m in got["missed"] if "pnl" in m["market"]]
    return {"sym": sym, "tf": tf, "signal": signal, "exit": spec,
            "start": fmt_when(from_s), "end": fmt_when(end_s),
            "coverage": cost_store.coverage(book, from_s, end_s),
            "trades": len(trades), "wins": sum(1 for x in trades if x["pnl"] > 0),
            "losses": sum(1 for x in trades if x["pnl"] <= 0),
            "profit": round(sum(x["pnl"] for x in trades), 2),
            "missed": len(got["missed"]), "missed_entered": len(twins),
            "missed_pnl": round(sum(x["pnl"] for x in twins), 2),
            "counts": got["counts"]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_smoke",
                                description="One stored signal on one coin, the v3 way.")
    p.add_argument("sym")
    p.add_argument("tf", choices=("15m", "30m", "1h", "4h", "1d"))
    p.add_argument("signal")
    p.add_argument("exit", help="fixed:TP:SL, trail:ATR[:MA] or snap:ATR:BARS")
    p.add_argument("--days", type=int, default=120)
    p.add_argument("--th", type=float, default=None)
    a = p.parse_args(argv)
    t0 = time.time()
    got = run(a.sym, a.tf, a.signal, exit_spec(a.exit), days=a.days, th=a.th)
    print(f"{got['sym']} {got['tf']} {got['signal']} {a.exit}: {got['start']} to {got['end']}")
    print(f"order books cover {100 * got['coverage']:.1f}% of the minutes "
          "(the rest pay a typical cost)")
    print(f"{got['trades']} trades, {got['wins']} won, {got['losses']} lost, "
          f"{got['profit']:+.2f} at $1 risk a trade")
    print(f"orders that never filled: {got['missed']}; the {got['missed_entered']} the "
          f"runner would have entered at the market would have made {got['missed_pnl']:+.2f}")
    print("counts:", got["counts"], f"({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass, then lint**

Run: `.venv/Scripts/python -m pytest tests/test_v3_smoke.py -q`, then `.venv/Scripts/python -m ruff check tradingagents/v3_smoke.py tests/test_v3_smoke.py`
Expected: `2 passed`, then `All checks passed!`

- [ ] **Step 5: Run it for real on Gate's data.** These runs are read-only: no order, no store, no screen.

```bash
TA_VENUE=gate .venv/Scripts/python -m tradingagents.v3_smoke BTC_USDT 1h bb20 fixed:0.02:0.01 --days 30
TA_VENUE=gate .venv/Scripts/python -m tradingagents.v3_smoke BTC_USDT 1h trend50 trail:3:50 --days 30
TA_VENUE=gate .venv/Scripts/python -m tradingagents.v3_smoke BTC_USDT 1h bb20 snap:3:24 --days 30
```

Expected: each run prints a window, a coverage percentage, trades with wins and losses, the missed orders and the counts. On Oct 22, 2026 the first run printed `Sep 22, 2026 11:00pm to Oct 22, 2026 10:00pm`, `order books cover 99.9% of the minutes`, and `27 trades, 13 won, 14 lost, +9.88 at $1 risk a trade`. A later day moves the window, so the numbers move too. Paste each run's printed lines into the commit message.

- [ ] **Step 6: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> tradingagents/v3_smoke.py tests/test_v3_smoke.py
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message: `feat(v3): one coin the v3 way, for real - the smoke run on Gate's data, coverage printed first`, followed by the three runs' printed lines.

---

### Task 7: Write the rules down

**Files:**
- Modify: `CLAUDE.md` (a new MANDATORY section directly after "## Backtest v2 keeps only TP > SL")
- Modify: `docs/superpowers/specs/2026-10-22-backtest-v3-design.md` (line 3, the status)

- [ ] **Step 1: Add the CLAUDE.md section.** Check `git diff HEAD -- CLAUDE.md` first: other sessions edit this file.

```markdown
## Backtest v3 — the engine's rules (MANDATORY — Oct 22, 2026)

The operator: *"i want to do backtest v3 where you will create the strategy
for the research you made"*. Spec:
`docs/superpowers/specs/2026-10-22-backtest-v3-design.md`; plan:
`docs/superpowers/plans/2026-10-22-backtest-v3-part1-engine.md`.

* **One set of rules, `v3_rules`**, for the engine now and for the runner's
  v3 practice rooms later:
  - a waiting order fills only when the price trades THROUGH it (a touch is
    not a fill), inside the next candle;
  - an unfilled order is a missed trade, kept with its market twin;
  - $1 risk, at the highest leverage whose stop sits inside 80% of
    liquidation;
  - a trailing stop is checked before it moves, and never loosened;
  - a stop the price jumped past fills where the price was;
  - funding before Gate's history is estimated and counted.
* **The point an order fills in can stop the trade, never win it.** Its high
  may have come before the fill.
* **Shared, not copied:**
  - a resting target is `settle_in_minutes(tp_through=True)`;
  - a waiting entry's cost check is `entry_refusal(entry="limit")` (maker
    fee in, taker fee + the exit minute's gap out, never a chase);
  - the maker fee is `maker_fee_floor()`, beside `fee_floor()`.

  Every default is the rule of before, byte for byte.
* **Nothing unmeasured is hidden.** Every walk returns its `COUNT_KEYS`, and
  every v3 run prints `cost_store.coverage` first.
* **v3 never writes v1 or v2.** It uses `stores.V3` and ids
  `row_code(..., res="v3")`. No job runs with `V3.env_for()` until every
  reader of `market_sweep.FINE_TF` has been checked: "v3" is set, and several
  readers take a set value to mean v2.

Guards: `tests/test_v3_rules.py`, `tests/test_v3_engine.py`,
`tests/test_v3_shared_rules_learn_the_waiting_order.py`,
`tests/test_backtest_v3_store.py`, `tests/test_cost_coverage.py`,
`tests/test_v3_smoke.py`.
```

- [ ] **Step 2: Update the spec's status line.** On line 3, replace `**Status:** design approved in chat, written for review` with `**Status:** approved Oct 22, 2026 ("ok go ahead"); Part 1, the engine, is built (plan docs/superpowers/plans/2026-10-22-backtest-v3-part1-engine.md)`.

- [ ] **Step 3: Run every file this plan touched, once.** Check first that no other pytest is running.

Run: `.venv/Scripts/python -m pytest tests/test_v3_rules.py tests/test_v3_engine.py tests/test_v3_shared_rules_learn_the_waiting_order.py tests/test_backtest_v3_store.py tests/test_cost_coverage.py tests/test_v3_smoke.py tests/test_v2_store_is_its_own_folder.py tests/test_minute_exact_exits.py tests/test_room_replay_settles_by_the_minute.py tests/test_cost_verdict_is_the_runners.py tests/test_the_replay_shard.py tests/test_backtest_pays_the_minute.py tests/test_gate_runner_costs.py tests/test_cost_store.py -q`
Expected: all pass.

- [ ] **Step 4: Commit and push**

```bash
.venv/Scripts/python scripts/commit_own.py -F <msg-file> CLAUDE.md docs/superpowers/specs/2026-10-22-backtest-v3-design.md
git push -q origin main && git push -q colleague main && git push -q teammate main
```

Message: `docs(claude): Backtest v3's engine rules - one v3_rules for the engine and the runner, the shared settle, cost check and maker fee, every gap counted`

---

## The plans after this one

Each is written once this one lands, because each depends on this engine's interfaces and on its measured speed.

- **Part 2 — the idea families on GitHub.** It starts by checking the 30 readers of `market_sweep.FINE_TF` (in 9 files) before any job runs with `stores.V3.env_for()`. Then it builds:
  - the universe: the top 50 liquid crypto contracts re-ranked monthly, calm contracts, and stock tokens with `closed` worked out by the runner's own rule;
  - families 1-4 and filters 5-9 as signal code;
  - the shared cross-coin file (BTC mood, the weekly ranking);
  - the order-book backfill over the v3 window, which must report COVERAGE FIRST;
  - 200 seeded random runs, the proof test and its luck correction;
  - a 20-coin pilot, then the whole universe on all 60 machines;
  - verdicts in the v3 store.
- **Part 3 — re-testing the stored rows.** About 12.4M listed v2 rows go through `walk(kind="fixed")`. A stored row's TP and SL are PERCENT and the engine takes fractions. The part also covers market-vs-waiting twins, verdicts per signal, and the "when to trade" map (#10) with its own verdict.
- **Part 4 — the Backtest v3 tab:** the standard kit, with a risk-per-trade box in place of the base-margin box.
- **Part 5 — practice with waiting orders:** the runner uses `v3_rules` for the v3 rooms, and the frozen v3 rooms are set up.

## How the build went (Oct 22-23, 2026)

Built subagent-driven (the operator chose "A helper per step"): every task by a fresh helper, reviewed for spec and quality, fixed and re-reviewed where needed, then one whole-branch review and one final fix wave. Commits on main, pushed to origin, colleague and teammate: f51b09d, 2da919d, c284f2b, 4ed529f, 89c05b5, 29578d5, c92c4d5, 9e94489, 5a4220c, bffc4e9, d8b2f00, f07aae8, 5b085d8.

The final fix wave changed the fill model the plan was written with: waiting orders are POST-ONLY (an order marketable when placed is rejected and recorded as a missed trade with its market twin). On BTC_USDT 1h bb20 2%/1% over the 30 days to Oct 23, 2026 2:00am that rejected 19 of 40 orders (47.5%): 21 trades, 8 won, 13 lost, +1.52 at $1 risk; the rejected orders' market twins would have made +2.56 (the engine before the fix: 27 trades, +6.98 on the same window).

### Rulings made during the build, in order (each with what it costs if wrong)

1. Ruling: implement on `main` in the shared checkout, no worktree — CLAUDE.md "Commit and push EVERY change ... Do not ask" is the operator's standing consent, and scripts/commit_own.py builds each commit from a private index so other sessions' staged files stay out — cost if wrong: commits land on main and are pushed; each is undone by one `git revert`.
2. Ruling: every task pushes to origin, colleague and teammate as it completes — CLAUDE.md mandate ("push after each coherent unit of work") — cost if wrong: three accounts carry a commit a later revert must undo.
3. Ruling: implementer models — haiku for Tasks 1, 2, 4, 5, 6 (the plan holds the complete code: transcription plus tests), sonnet for Task 3 (four surgical edits in the 5,000-line auto_trader.py other sessions also edit) and Task 7 (CLAUDE.md, a shared hot file); sonnet for task reviews; opus for the final review — cost if wrong: a cheap implementer burns extra turns or needs a fix round.
4. Ruling: implementers extract the brief's code blocks with a short script instead of retyping them, and must not "improve" the code — every block was run before the hand-over (38 tests, 3 real runs) — cost if wrong: none beyond a re-extraction.
5. Ruling: add tests/test_v2_jobs_have_no_cloud.py, tests/test_v2_measures_on_github.py and tests/test_v2_routes.py to Task 7 Step 3's closing run — the reviewer showed they read stores.py's v2 behaviour and no task runs them — cost if wrong: about a minute of extra test time
6. Ruling: dispatch Task 3 implementer while Task 2 review runs (operator: "go sgart") — still one implementer at a time, and Task 3 touches only auto_trader.py + a new test, no Task 2 file — cost if wrong: a Task 2 fix round waits for Task 3 to finish
7. Ruling: accept Important 1 as a TEST-ONLY fix — add the reviewer's fixtures plus the three that kill the remaining survivors (atr gap, 4000-lot allowance, settlement boundaries); v3_rules.py itself stands as the plan wrote it — the spec names each of these rules, and the plan never meant its tests to be the only proof — cost if wrong: ~20 extra test lines
8. Ruling: dispatch Task 4's implementer while the Task 2 re-review and the Task 3 review run — Task 4 only consumes interfaces already committed (v3_rules, the three auto_trader switches) and creates two new files; one implementer at a time is kept (a Task 3 fix round would wait for Task 4 to finish) — cost if wrong: if a review changes a signature Task 4 uses, Task 4 takes a fix round
9. Ruling: keep commit 89c05b5 as pushed although its trailer reads "Claude Haiku 5.5" instead of the plan's "Claude Opus 5.5" — fixing it means force-pushing main on three accounts, and the trailer names the model that actually wrote it — cost if wrong: one commit's attribution line differs from the others
10. Ruling: dispatch Task 5's implementer while Task 4's review runs — Task 5 touches only cost_store.py (append) + a new test, nothing the engine uses; one implementer at a time is kept — cost if wrong: a Task 4 fix round waits for Task 5 to finish
11. Ruling: add the source-scanning guards to Task 7 Step 3's closing run — tests/test_one_door_to_the_exchange.py, tests/test_the_backend_names_the_exchange.py, `tests/test_auto_trader.py -k nothing_is_defined_after`, `tests/test_webapp.py -k "formats_a_timestamp_by_hand"` — no task runs the guards that read every module, and Part 1 adds three modules — cost if wrong: a few minutes of test time; test_the_backend_names_the_exchange already fails on another session's app_books.py, so a failure there must be checked to name only that file
12. Ruling: dispatch Task 6's implementer while the Task 4 and Task 5 reviews run — Task 6 only consumes committed interfaces (walk, coverage, maker_fee_floor) and creates two new files; it is the only implementer running — cost if wrong: a review that changes walk's or coverage's contract gives Task 6 a fix round
13. Ruling: accept Important 1 — a WHOLE candle the points cannot settle keeps the candle rule and is counted (fixed/snap on "NONE", the trail when the candle proves the starting stop was hit, the fill when the candle proves a trade-through, and a candle-rule fill makes the fill candle a no-points candle); the part of the fill candle after the fill keeps today's rule — the spec says a candle the minutes cannot settle keeps the candle rule and is counted, and the module promises nothing unmeasured is hidden — cost if wrong: some exits on data with holes book at the candle's open with the starting stop (the conservative price) instead of later
14. Ruling: accept Important 2 — flat_slip becomes a required keyword argument of walk (CLAUDE.md rule 9) — cost if wrong: every caller must name its flat gap
15. Ruling: accept Important 3 — add the tests and prove each named break (M1-M11 + the three new rules) fails at least one — cost if wrong: a longer test file
16. Ruling: Task 4 fix round 1 goes to a FRESH sonnet implementer instead of resuming the haiku transcriber — the fix needs design judgment (three new candle-rule branches, about ten mutation-pinned tests) that the original transcription never exercised (Model Selection: design judgment needs a stronger model) — cost if wrong: one fresh context's tokens
17. Ruling: accept I1 as TEST-ONLY — adopt the reviewer's four candidate tests (scratchpad\rev6_sonnet_review\candidate_tests.py: money/window/missed scenario, the forming candle, minutes reaching the walk, coverage printed before trades) into tests/test_v3_smoke.py; v3_smoke.py stands as the brief wrote it; the fix round waits for Task 4's fix implementer (one implementer at a time) and its tests run against the fixed engine — cost if wrong: about 90 more test lines
18. Ruling: Task 7's CLAUDE.md section describes the engine AS BUILT after the fix rounds — two bullets are added to the plan's text (a whole candle the minutes cannot settle keeps the candle rule, counted; walk's flat gap is a required argument, never a free 0) — a rules file that describes the pre-fix engine would be a false label (CLAUDE.md label-must-match-data) — cost if wrong: two extra bullets in CLAUDE.md
19. Ruling: accept both as WORDING fixes in CLAUDE.md (exact old -> new text in task-7-findings-r1.txt); counting the four uncounted cases is engine code, outside a docs task — it goes to the final review — cost if wrong: the rules file names the gaps instead of closing them
20. Ruling: waiting orders are POST-ONLY (Gate poc) — an order marketable when placed (fresh book <= 59 s: ask <= limit for a long, bid >= limit for a short) is rejected and recorded as a missed trade with its market twin (post_only_reject); no fresh book rests as before (placement_unmeasured) — the spec's maker fee becomes true by construction, practice can place the same order, and the twins keep the taker alternative measurable — cost if wrong: about 42% of signals become missed orders whose market results are still recorded beside them
21. Ruling: fix I2 as the reviewer proposed — a fill candle whose own losing extreme is past the stop proves a stop-out after the fill (SL by the candle rule, counted, stamped after the fill point); a whole candle whose own extreme proves the stop while no visible point shows it is SL + unclear (worst case), counted; new partial_points count; flip the test that asserts TP — cost if wrong: some hole-world trades book the stop that every-minute data might have shown later
22. Ruling: fix I3 — the funding history answers only up to one cycle after its last settlement; the rest of a hold is estimated at the average rate and flagged — cost if wrong: none for fresh lists
23. Ruling: fix I4 with one v3_rules.stop_reached predicate and the pins; fix the "fix before Part 2" items (refuse a contract with mmr <= 0 / contract_size <= 0 / max_lev < 1 by name; closed honoured without cost_check; a no_points count; candle-rule stops fill at the candle's open when it opened past the stop (M1); the false words; CLAUDE.md and one dated spec line) — cost if wrong: a larger single fix commit
24. Ruling: F2 and F3 get docs/RCA.md entries in the same commit (real defects in pushed code, cost none — found before any v3 result was used); F1 is a design ruling (no RCA)
25. Ruling: the final fix wave goes to ONE opus implementer with the complete list (final-findings.txt) — the skill's single fix dispatch; most capable model because it reshapes the fill path the whole v3 build rests on — cost if wrong: one large context

### Parked at the final review (fix in Part 2's first commit unless it says otherwise)

- Final: parked — CLAUDE.md:2401 says funding "before its first settlement" is estimated, the code estimates only the part more than one cycle before it — Ruling: fix the wording in Part 2's first commit (it touches this section anyway); the code and its docstring are right — cost if wrong: one sentence in CLAUDE.md overstates for a while
- Final: parked — CLAUDE.md:2395-2396 calls stop_reached the one rule for the fixed stop, while a fixed stop at a visible minute is decided by settle_in_minutes (the same touch rule, kept in a second place) — Ruling: fix the wording in Part 2's first commit, and Part 2 decides whether settle_in_minutes should call stop_reached — cost if wrong: a later change to one touch rule could miss the other
- Final: parked — docs/RCA.md:218-221 (RCA-2026-10-23-B step 3) credits the final review's probe with "$0.00, estimated=False", but that probe ran the no-history path; the defect itself is real (the old code returns (0, False) with the list passed) — Ruling: correct the timeline line in Part 2's first commit — cost if wrong: one RCA timeline step names the wrong run
- Final: parked — hidden-stop exits are stamped at the first point after the fill (a) or the candle's open (b), so on 4h/1d candles funding settled before the hidden minute is not charged and the gap is read at the stamped minute; every such trade is counted settled_by_candle — Ruling: keep (the conservative price and an honest count); revisit with the deferred exit-stamp item in Part 3 — cost if wrong: a little funding uncharged on long-candle hidden stops
- Final: parked — no short-side test for a trail's hidden stop, in (a) or (b); probes show the short mirrors correctly — Ruling: add in Part 2's first commit — cost if wrong: a later short-side break goes unnoticed by the suite

### Notes for Parts 2-5

- Part 2 note (from Task 1's hunt): before any v3 job — 16 endswith("_v2") gates (api.py 2839/2884/2907; db_jobs.py 734/735/824/1239/1249/1257/1332/1969/1982/2534/2891; rows_index.py 334/385), fine_tf used as a frame name (room_replay 416/435/603/737, market_sweep 2131/2551, portfolio_replay 345), FINE_TF truthiness (market_sweep 1146/1171/1482/1563/1605, db_jobs 2663), rolling30.py:70 res→store, rows_index.py:5377 sizing rule, download_kind "" lookups (api.py 4622/5235/5255/5272/5333), no candles_v3 pending kind
- Part 2 note (reviewer, Task 1): spec line 254 says V3 has "its own rows, index, candles view"; Part 1 gives V3 a plain candles folder — settle what "candles view" means when Part 2 picks the shard's candle reader
- Part 5 note (reviewer, Task 3): the spec's "ONE function the engine and the runner share" — the live runner's edge_check does not call minute_verdict; Part 5 must route the v3 rooms' entry check through minute_verdict/entry_refusal(entry="limit") or carry the same halving
- Part 2 note (reviewer, Task 4): book readings are the cost of walking the book for the runner's $100; a $1 risk on a 0.2% stop is $500 of coin, so slip_out understates the exit gap for tight stops on thin books — Part 2 must price the gap at the trade's own size, or say so beside every result
- OPEN QUESTION for the operator (reviewer, Task 4, spec level): a long's waiting order at the signal close is often marketable the moment it is placed (the ask is already at or below the close), and Gate would fill it at once as a TAKER (0.075%), not a maker (0.02%); the approved spec books every waiting fill as maker at the limit — to decide before Part 2's proof test: keep maker; charge taker when the placement minute's book shows ask <= limit (bid >= limit for a short); or post-only orders, where a marketable one is rejected and counted missed
- Part 2 note (final review I5): exit gaps come from book readings at the runner's $100 while v3 sizes up to $500 at a 0.2% stop — price the gap at the trade's own size, cap the size, or print the limitation beside every result
- Part 2 note (final review I6): Part 2's first audit must cover the 16 endswith("_v2") gates (db_jobs.py:824 gives a non-_v2 kind NO store environment, so a backtest_v3 job would run in v1's folders), not only the 30 FINE_TF readers
- Part 2 note (final review rec 2): row_code(res="v3") hashes tp and sl only; trail/snap exits have neither — put the exit spec, any filter and risk_usd into plan or the signal key, or two settings share an id (standard kit H)
- Part 2 note (final review rec 3): consider a Store.res field with fine_tf="1m" kept for v3 so the frame readers work unchanged
- Part 2 note (final review triage): contract-field mapping in one tested helper; each coin's own flat gap (not FLAT_SLIP); cost_unmeasured printed as a share and a decision on how END trades count; temp_spec instead of hand-set STRATEGY_SPECS; closed flags for stock tokens
- Part 3 note (final review rec 5): skip ATR on fixed walks; cache fills per coin, timeframe and signal (a waiting order's fill does not depend on TP or SL)
- Part 4 note (final review rec 4): under lot rounding and fixed-depth book readings the risk box cannot rescale dollars linearly — re-run at the chosen risk, or say so on the page
- Part 4 note (final re-review): counts["missed"] no longer equals len(missed) — the page must read the list, or missed + post_only_reject
- Part 5 note (final re-review): Gate's archive best prices can be RPI offers API orders never match (RCA-2026-10-16-A), so post_only_reject may over-reject where no app book exists — measure app-book minutes against archive minutes before practice places real post-only orders
- Part 3 note (final re-review): (b) books the stop plus unclear even when every hidden minute comes after the visible target (the order is knowable there) — a possible refinement; and precompute each candle's point extremes once (the per-candle max/min in _note_points is most of the ~40% slowdown)
- Part 2 note (final re-review): a min_lev of 0 still raises ZeroDivisionError in safe_leverage and a None contract field raises TypeError — name the field like _check_contract does

### Deferred minor findings from the task reviews (the final review triaged them; the "fix before Part 2" ones are done in f07aae8)

- Task 1: minor (deferred): stores.py:61-67 fence comment names only FINE_TF readers — also name the 16 endswith("_v2") gates and store.fine_tf frame readers
- Task 1: minor (deferred): stores.py:28 field comment ("" for v1, "1m" for v2) and the module docstring (v1/v2 only) are stale for V3
- Task 1: minor (deferred): test_backtest_v3_store.py does not pin V3.fine_tf/download_kind/backtest_kind/env_for, and the id test uses a literal res="v3" instead of stores.V3.fine_tf
- Task 2: minor (deferred): trail_walk docstring says "the worse is assumed" but check-first is the kinder order on a wide point; module docstring says the engine "uses these now" before Task 4 exists
- Task 2: minor (deferred): safe_leverage/risk_size accept mmr <= 0 (a missing maintenance rate gets more leverage than the real one; runner's liquidation_distance treats it as unknown), min_lev=0 raises ZeroDivisionError, and a zero contract size would be counted too_small
- Task 2: minor (deferred): funding_paid estimates only the head of the history — a hold past the last settlement (a stale list) pays 0 with estimated=False; also returns int 0 when no settlement falls in the hold
- Task 2: minor (deferred): atr/sma duplicate pro_indicators' with no parity test; docstrings should say plain average (not Wilder) and that the first true range is high - low
- Task 3: minor (deferred): untested new branches — limit entry with no reading, maker_fee=None taker fallback, a limit entry still cost-gated, a short's same-minute stop+through, bare touch+stop unclear=0, maker_fee_floor() with no argument
- Task 3: minor (deferred): settle_in_minutes docstring still says "NONE" means the caller keeps the bar rule — false under tp_through (plan-mandated paragraph)
- Task 3: minor (deferred): entry is a free string ("Limit" silently prices as market) and limit without maker_fee silently charges taker — both conservative; ValueError suggested
- Task 3: minor (deferred): the two cost_verdict calls in minute_verdict repeat the funding formula and seven kwargs (plan-mandated); reading["sell" if long else "buy"] now written five times
- Task 3: minor (deferred): entry_refusal docstring line is 123 columns
- Task 2: minor (deferred, re-review out-of-scope): a short trail's jumped-past fill price is unpinned — candidate trail_walk(-1, 101.0, 1.0, [T0, T0+M], [100.2, 103.0], [99.5, 102.0], T0, T0+2*M) == (T0+M, 102.0)
- Task 2: minor (deferred, re-review out-of-scope): ATR's downward-gap term is unpinned — candidate atr([21.0, 11.0], [19.0, 9.0], [20.0, 10.0], 2) == [None, 6.5]
- Task 2: minor (deferred, re-review out-of-scope): the exact-touch stop trigger (lo <= stop / hi >= stop) is unpinned on both sides; intended direction is "a touch stops", matching settle_in_minutes — the final review should pin it
- Task 4: minor (deferred): walk's flat_slip defaults to 0.0, so an unmeasured market exit is counted cost_unmeasured but costs nothing unless the caller passes the coin's flat gap (v3_smoke passes 0.0003)
- Task 5: minor (deferred): coverage assumes packed["t"] is sorted (true for book_for/merge/engine_book); v3_smoke prints "0.0% covered" for a None book (not on Gate) where "no order books on this exchange" would say why
- Task 5: minor (deferred): no committed parity test holds coverage to book_history.reading_at, and max_age_s has no assertion (a `max_age_s or MAX_AGE_S` rewrite would pass) — template: scratchpad\rev5\parity.py
- Task 5: minor (deferred): coverage's docstring omits that packed["t"] must be ascending and that a hole shorter than max_age_s is not a hole; v3_smoke's "order books cover X% of the minutes" should read "minutes with a reading at most an hour old"
- Task 5: minor (deferred): commit 29578d5's body does not name the incident (Oct 22, 2026: 230,972 of 1,860,286 confluence trades, 12.4%, paid their own minute's book) — for later commits
- Task 6: minor (deferred): a window with no closed candles ends in a bare IndexError
- Task 6: minor (deferred): v3_smoke's "Reads only" docstring — a window over 2,000 candles saves candle-cache files through fx.klines (no store, no order, no screen)
- Task 4: minor (deferred): the twin's fee_in also holds its entry gap and there is no slip_in key; the twin's measured_exit covers only its exit
- Task 4: minor (deferred): the twin's scratch tally (unclear, settled_by_candle) is thrown away; the twin lacks contracts/leverage/margin/side, which the standard kit's columns need
- Task 4: minor (deferred): cost_check=False also turns off the closed-market skip
- Task 4: minor (deferred, Part 3 speed): ATR is computed on every walk including fixed (19.1 ms with lists, 43.9 ms with numpy for a year of 15m) — about 66-151 CPU-hours over 12.4M rows; compute it only when kind != "fixed"
- Task 4: minor (deferred): a no-points candle that moves the trail without ending the trade is not counted
- Task 4: minor (deferred): duplication — _stopped vs reach_sl, the candle fill test vs limit_fill, three reading_at lookups, auto_trader imported inside the per-candle _fixed_bar
- Task 6: minor (deferred): FLAT_SLIP = 0.0003 is commented "the engine's default gap" but is a copy of auto_trader.PAPER_SLIPPAGE and one figure for every coin (CLAUDE.md rule 10); the printed "typical cost" never shows the figure — Part 2 must use the coin's own gap
- Task 6: minor (deferred, Part 2): closed is never passed, so a stock token's dead candle would be traded (practice refuses it via closed_market/market_sweep.closed_rule)
- Task 6: minor (deferred): an unknown signal name prints "0 trades" with every count 0 and no error
- Task 6: minor (deferred): unit traps — exit_spec("fixed:2:1") reads as TP 200% / SL 100%; --th is an unlabelled fraction whose .003 default is not a 4h/1d grid threshold; the header prints neither the parsed spec nor th
- Task 6: minor (deferred): "Reads only" — engine_book writes ~/.tradingagents/cost_cache/<COIN>-<YYYYMM>.npz on a first run or after its 6 h TTL, besides the kline cache
- Task 6: minor (deferred): STRATEGY_SPECS is set and popped by hand instead of at.temp_spec (per-key lock, RCA-2026-10-14-N); the key omits coin and th, so concurrent run() calls in one process clobber each other
- Task 6: minor (deferred): call fx.contract_spec(sym) first so an unlisted coin is named before the heavy reads (the empty-window IndexError is already logged)
- Task 6: minor (deferred): labels — "$1 risk a trade" is a literal, not RISK_USD; trades/wins/losses include a position still open at the window end (why END); venue and days asked are not printed; the share of typical-cost trades appears only inside the counts dict
- Task 6: minor (deferred): LEAD_BARS = 300 is a third copy of sweep_shard.WARMUP_BARS; the tf choices are hard-coded
- Task 6: minor (deferred): a Chinese-named coin crashes the first print on this PC's cp1252 pipe (UnicodeEncodeError) after the whole run — sys.stdout.reconfigure(encoding="utf-8")
- Task 6: minor (deferred): mutant M9 'signal key not built' survives — a one-line key assertion in the test's _patch would catch it
- Task 4: minor (deferred): _trade(by_candle=False) defaults to "a point decided the fill" — a future partial=True caller that omits it would walk the fill candle from its first point; make it required
- Task 4: minor (deferred, as ruled): candle-rule exits are stamped at the candle's open, so the exit gap is read at the open minute and funding settled later in that candle is skipped (up to a day early on 1d)
- Task 4: minor (deferred): _fixed_bar reads the points only when the candle's own range reaches a price, so a candle NARROWER than its points (e.g. a flat placeholder candle) skips an exit its points show — the one path that trusts the candle over the points
- Task 4: minor (deferred): the cases the ruling leaves open (40 of 5,164 trades in hole worlds: a later event in the surviving points, the rest of a fill candle) are booked with no count, so "never hidden" is not fully true for them — a count of whole candles walked on partial points would show them
- Task 6: minor (deferred): tests/test_v3_smoke.py:165 sets minute 30 of candle 311 as "the order fills here" but every flat minute's 99.7 low already fills at minute 0 — dead line, false comment (inherited from the candidate)
- Task 6: minor (deferred): 13 of 19 extra smoke-run breaks survive the six tests — contract-field mapping (max_lev, mmr, min_vol, contract_size), the th default, the rsi14 key special case, the lead clamp, the windows handed to engine_book and fine_bars, the volume/ts/funding handed to the signal, the STRATEGY_SPECS cleanup
- Task 7: minor (deferred): CLAUDE.md attributes "an unfilled order is a missed trade, kept with its market twin" to v3_rules — it lives in v3_engine.walk / _market_twin
- Task 7: minor (deferred): stale code comments — v3_smoke.py:18 "the engine's default gap" (walk has none now), stores.py:28 fine_tf comment omits "v3"; v3_engine.py:39-40 repeats the absolute "never hidden" sentence
- Task 7: minor (deferred): the new section's nested bullets use "  - " where the file's own nested lists use "  * " (cosmetic, plan-mandated)
- Task 7: minor (deferred): wording precision — '(never re-read)' is exact only for a candle-decided fill; the 40 of 5,164 figure sizes cases 1 and 2 together; 'far side' could be misread as the ask and 'both' overstates what the reading supplies
- Task 7: minor (deferred): a FIFTH uncounted case — v3_rules.funding_paid charges 0 for a hold after the history's last settlement with estimated=False (stale saved funding lists), already logged under Task 2
