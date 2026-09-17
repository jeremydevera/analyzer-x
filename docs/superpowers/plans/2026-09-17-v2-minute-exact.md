# Candles v2 + Backtest v2 (minute-exact exits) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two new tabs — Candles v2 (downloads and extends a 1-minute candle store) and Backtest v2 (measures the SAME 130 signals on the SAME timeframes, but settles every TP/SL exit minute by minute on those 1-minute candles) — without touching what the v1 tabs show or store.

**Architecture:** The existing download job, sweep and engine are reused. v2 jobs are the same job bodies started as their own job kinds (`download_v2`, `backtest_v2`) with the store roots pointed at `~/.tradingagents/v2/` through the environment settings the modules already read (`TRADINGAGENTS_SWEEP_HOME`, `TRADINGAGENTS_CANDLES`, `TA_ROWS_DB`, plus two new ones). One engine change, default-off: `backtest_strategy(fine=...)` resolves exits on 1-minute bars. Signal bars for every timeframe are rebuilt from the 1-minute candles (`bars_from_1m`), which reproduce MEXC's own bars exactly. The API grows `/api/v2/...` routes served by the same handlers parameterised by a `Store`.

**Tech Stack:** Python 3.13 (FastAPI, pandas, sqlite3, pyarrow), Next.js 15 / React / TypeScript, pytest, playwright-core (system Chrome at `C:/Program Files/Google/Chrome/Application/chrome.exe`).

**Spec:** `docs/superpowers/specs/2026-09-17-v2-minute-exact-design.md`

## Global Constraints

- Repo root `G:\analyzer-x`; venv python is `.venv/Scripts/python.exe`; run tests with `.venv/Scripts/python.exe -m pytest <file> -q`.
- **Every date the project prints goes through `positions_view.fmt_when` / `fmtWhen`** — never `strftime`, never `toLocale*`.
- **`if __name__ == "__main__":` is the LAST thing in a module.**
- **Commit and push after every task.** Message says WHAT changed and WHICH ask bought it. End every commit message with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- **Never commit** `tradingagents/api.py`, `tests/test_api_trade.py` or `tradingagents/auto_trader.py` hunks that are not yours — another session has uncommitted `by_coin` work in those files. Stage by path for new/own files; for shared files, build the staged blob from `git show HEAD:<file>` + your hunk (see Task 2 step 6 for the recipe).
- **The four hardcoded five-frame lists stay five.** `"1m"` never enters `capacity.ALL_TFS`, `backtest_report.BARRIERS`, `backtest_report.THRESHOLDS`, `backtest_report.MIN_BARS`, `api._TFS`, or the tuples in `db_jobs.py:797/876/938/1078` — Task 1's guard test enforces it.
- **v1 behaviour is byte-identical.** Every parameter added defaults to the old behaviour; every test that pins v1 output stays green.
- Big files go under `~/.tradingagents` (a junction to `G:`), never `%TEMP%`.
- `LOCAL_SWEEPS` stays `False` for v1. v2 measuring runs locally by design (the 1m candles exist only here).
- Answers to the operator: one sentence, plain words, with a real example. Bugs found while building: `docs/RCA.md` entry in the same commit as the fix.

---

## File map

**Create**
- `tradingagents/stores.py` — `Store` dataclass: the paths for v1 and v2, and `env_for()` for a job process.
- `tests/test_bars_from_minutes.py` — `bars_from_1m` reproduces MEXC bars; refuses gaps; `"1m"` stays out of every v1 list.
- `tests/test_minute_exact_exits.py` — engine `fine=`: parity with `fine=None`, order inside a bar, same-minute → SL + `unclear`, exit time is the minute.
- `tests/test_v2_store_is_its_own_folder.py` — `Store` paths, job env, `row_code(res=)`, `rows_index` `db_path`, `unclear` column.
- `tests/test_v2_routes.py` — `/api/v2/...` answers, empty-store sentence, v1 routes unchanged.
- `webapp/src/app/(admin)/candles-v2/page.tsx`, `webapp/src/app/(admin)/backtest-v2/page.tsx`.
- `webapp/src/components/StoreBadge.tsx` — the `v2 · minute-exact exits` chip.

**Modify**
- `tradingagents/backtest_report.py` — `TFS["1m"]`; `row_code(..., res=None)`.
- `tradingagents/market_sweep.py` — `FINE_TF` env; `bars_from_1m`; `run_pair` v2 branch; `candle_index(root=)`.
- `tradingagents/auto_trader.py` — `backtest_strategy(..., fine=None)` and `unclear` in its result/state.
- `tradingagents/rows_index.py` — `unclear` in `COLS` + `ALTER TABLE` in `ensure()`; `db_path=` on `_connect/_open/query/query_sql/status/pair_storage/facets/export_plan/iter_rows`.
- `tradingagents/parquet_store.py` — `ROOT` env override.
- `tradingagents/db_jobs.py` — `FILES` v2 kinds; `start()` env; `main()` dispatch; `_run_download` whitelist + `update_pairs(tfs=)`; `_pending_sources(files_key, tfs)`; `_run_backtest_inner` for `backtest_v2`.
- `tradingagents/api.py` — `/api/v2/...` routes; supervisor tuple gains the v2 kinds.
- `webapp/src/lib/api.ts` — `storeApi(store)`; `StrategyRow.unclear`; `jobStart` kinds.
- `webapp/src/components/candles/DownloadScreen.tsx`, `webapp/src/components/backtest/{JobsPanel,StrategiesPanel,BacktestStorage}.tsx` — `store` prop.
- `webapp/src/layout/AppSidebar.tsx` — two nav items.
- `CLAUDE.md` — a MANDATORY section for v2.

---

### Task 1: `bars_from_1m` and the `1m` timeframe entry, with the "stays out of v1" guard

**Files:**
- Modify: `tradingagents/backtest_report.py:122-128` (TFS)
- Modify: `tradingagents/market_sweep.py` (add `bars_from_1m` after `cached_candles`, ~line 300)
- Test: `tests/test_bars_from_minutes.py`

**Interfaces:**
- Produces: `market_sweep.bars_from_1m(df_1m, tf: str) -> pd.DataFrame` with columns `Date, Open, High, Low, Close, Volume`, one row per COMPLETE bar of `tf`, the forming last bar dropped. Raises `ValueError("<SYMBOL?> 1m frame has N missing minute(s) between A and B")` when a minute is missing inside the window (the caller names the coin).
- Produces: `backtest_report.TFS["1m"] == ("Min1", 60, 44000)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bars_from_minutes.py
"""Sixty one-minute candles ARE the hour candle.

Measured Sep 17, 2026 on XPIN_USDT: 666 of 666 hours identical to MEXC's own
Min60 bars on open/high/low/close. v2 rests on that, so the resampler is held
to it here on a recorded fixture, and the 1m frame must never leak into a v1
list — no v1 job, cloud shard or completeness count may see a 1m pair.
"""
import re
from pathlib import Path

import pandas as pd
import pytest

from tradingagents import backtest_report as br, capacity as cap, market_sweep as msw

REPO = Path(__file__).resolve().parent.parent


def _minutes(start_ms: int, n: int, seed: int = 5):
    import random
    rng = random.Random(seed)
    px = 100.0
    rows = []
    for i in range(n):
        o = px
        px = px * (1 + rng.gauss(0, 0.001))
        h = max(o, px) * (1 + abs(rng.gauss(0, 0.0005)))
        l = min(o, px) * (1 - abs(rng.gauss(0, 0.0005)))
        rows.append((start_ms + i * 60_000, o, h, l, px, 10.0 + i % 7))
    return pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"]) \
        .assign(Date=lambda d: pd.to_datetime(d["t"], unit="ms")).drop(columns="t")


def test_sixty_minutes_rebuild_the_hour_exactly():
    # 3 full hours + 17 minutes of a forming fourth, starting on an hour boundary
    m1 = _minutes(1_757_980_800_000, 3 * 60 + 17)   # Sep 16, 2026 00:00 UTC
    bars = msw.bars_from_1m(m1, "1h")
    assert len(bars) == 3, "the forming 4th hour is dropped, as v1 drops the forming bar"
    for k in range(3):
        chunk = m1.iloc[k * 60:(k + 1) * 60]
        row = bars.iloc[k]
        assert row["Open"] == chunk["Open"].iloc[0]
        assert row["High"] == chunk["High"].max()
        assert row["Low"] == chunk["Low"].min()
        assert row["Close"] == chunk["Close"].iloc[-1]
        assert row["Volume"] == pytest.approx(chunk["Volume"].sum())
        assert row["Date"] == chunk["Date"].iloc[0], "a bar is stamped at its OPEN, like MEXC"


def test_a_frame_that_does_not_start_on_the_boundary_drops_the_partial_first_bar():
    m1 = _minutes(1_757_980_800_000 + 23 * 60_000, 2 * 60 + 37)   # starts at 00:23
    bars = msw.bars_from_1m(m1, "1h")
    assert len(bars) == 2                       # 01:00 and 02:00 are complete; 00:xx is not
    assert bars["Date"].iloc[0] == pd.Timestamp("2026-09-16 01:00:00")


@pytest.mark.parametrize("tf,per", [("15m", 15), ("30m", 30), ("1h", 60), ("4h", 240), ("1d", 1440)])
def test_every_frame_needs_its_full_minute_count(tf, per):
    m1 = _minutes(1_757_980_800_000, per * 2 + 3)   # midnight-aligned: two full bars + a forming one
    bars = msw.bars_from_1m(m1, tf)
    assert len(bars) == 2, (tf, len(bars))


def test_a_missing_minute_is_refused_not_papered_over():
    m1 = _minutes(1_757_980_800_000, 180)
    m1 = m1.drop(index=[70]).reset_index(drop=True)   # one minute gone inside hour 2
    with pytest.raises(ValueError, match="missing minute"):
        msw.bars_from_1m(m1, "1h")


def test_the_1m_entry_exists_and_only_there():
    assert br.TFS["1m"] == ("Min1", 60, 44000)
    assert "1m" not in cap.ALL_TFS
    assert "1m" not in br.BARRIERS and "1m" not in br.THRESHOLDS and "1m" not in br.MIN_BARS


def test_no_five_frame_list_grew_a_sixth():
    """Every hardcoded ("15m","30m","1h","4h","1d") tuple in the v1 modules is
    still exactly five. A sixth entry would put a 1m pair in front of a v1 job."""
    five = re.compile(r'\(\s*"15m",\s*"30m",\s*"1h",\s*"4h",\s*"1d"\s*\)')
    six = re.compile(r'"1m",\s*"15m",\s*"30m"|"15m",\s*"30m",\s*"1h",\s*"4h",\s*"1d",\s*"1m"')
    for name in ("tradingagents/db_jobs.py", "tradingagents/api.py",
                 "tradingagents/capacity.py", ".github/scripts/sweep_shard.py"):
        src = (REPO / name).read_text(encoding="utf-8")
        assert not six.search(src), f"{name}: a five-frame list grew a 1m entry"
    assert five.search((REPO / "tradingagents/db_jobs.py").read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bars_from_minutes.py -q`
Expected: FAIL — `AttributeError: module 'tradingagents.market_sweep' has no attribute 'bars_from_1m'` and `KeyError: '1m'`.

- [ ] **Step 3: Add the TFS entry**

In `tradingagents/backtest_report.py`, replace the `TFS` dict:

```python
TFS: dict[str, tuple[str, int, int]] = {
    "15m": ("Min15", 900, 36000),
    "30m": ("Min30", 1800, 20000),
    "1h": ("Min60", 3600, 10000),
    "4h": ("Hour4", 14400, 14000),
    "1d": ("Day1", 86400, 2400),
    # THE v2 DOWNLOAD FRAME, and nothing else. `1m` is here so
    # `market_sweep.refresh_candles(symbol, "1m")` can page MEXC's Min1 stream
    # (44,000 bars = 30.6 days, the most the venue sells at once — measured
    # Sep 17, 2026 on BTC/ETH/VUG). It is deliberately ABSENT from
    # `capacity.ALL_TFS`, `BARRIERS`, `THRESHOLDS` and `MIN_BARS`: no v1 job,
    # cloud shard or completeness count may ever see a 1m pair. Backtest v2
    # never measures ON 1m bars — it rebuilds 15m/30m/1h/4h/1d bars from them
    # (`market_sweep.bars_from_1m`) and settles exits minute by minute.
    # tests/test_bars_from_minutes.py holds the boundary.
    "1m": ("Min1", 60, 44000),
}
```

- [ ] **Step 4: Add `bars_from_1m` to `market_sweep.py`** (directly after `cached_candles`)

```python
# Minutes in one bar of each frame Backtest v2 rebuilds. Not `br.TFS`: that
# table also holds "1m" itself, and a frame rebuilt from 1m must be one of the
# five the signals were measured on.
MINUTES_PER_BAR = {"15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}


def bars_from_1m(df_1m, tf: str):
    """Rebuild `tf` bars from one-minute candles — MEXC's own bars, exactly.

    Sixty one-minute candles ARE the hour candle: measured Sep 17, 2026 on
    XPIN_USDT, 666 of 666 hours identical to MEXC's Min60 on open/high/low/
    close (volume within 0.1% on 665). That equality is what lets Backtest v2
    run the v1 signals unchanged and differ from v1 ONLY in how an exit is
    settled.

    Rules, each one a test in tests/test_bars_from_minutes.py:
    * bars sit on UTC boundaries and are stamped at their OPEN, like MEXC;
    * only a COMPLETE bar is kept (60 minutes for 1h, 240 for 4h ...): the
      partial first bar and the forming last bar are dropped, the way v1's
      `_closed_bars` drops the forming candle;
    * a minute MISSING inside the window raises. A bar built over a hole
      would carry a high/low the venue never printed, and a refused pair is
      named in the progress file (rule 20) — a wrong bar is measured wrong
      for ever.
    """
    import pandas as pd

    per = MINUTES_PER_BAR.get(tf)
    if per is None:
        raise ValueError(f"bars_from_1m: {tf!r} is not a frame v2 rebuilds "
                         f"({', '.join(MINUTES_PER_BAR)})")
    if df_1m is None or len(df_1m) == 0:
        return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    d = df_1m.sort_values("Date").reset_index(drop=True)
    ts = d["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    gaps = (ts[1:] - ts[:-1]) != 60_000
    if gaps.any():
        import numpy as _np
        k = int(_np.flatnonzero(gaps)[0])
        missing = int((ts[k + 1] - ts[k]) // 60_000) - 1
        raise ValueError(
            f"1m frame has {missing} missing minute(s) between "
            f"{pd.Timestamp(ts[k], unit='ms')} and {pd.Timestamp(ts[k + 1], unit='ms')}")
    bar_ms = per * 60_000
    bucket = (ts // bar_ms) * bar_ms
    d = d.assign(_b=bucket)
    counts = d.groupby("_b")["Close"].count()
    full = counts[counts == per].index
    # the LAST bucket is the forming bar even when it happens to be full at
    # this instant only if its close minute is the frame's final minute —
    # `counts == per` already says so; nothing to special-case
    g = d[d["_b"].isin(full)].groupby("_b", sort=True)
    out = pd.DataFrame({
        "Date": pd.to_datetime(g["_b"].first().to_numpy(), unit="ms"),
        "Open": g["Open"].first().to_numpy(),
        "High": g["High"].max().to_numpy(),
        "Low": g["Low"].min().to_numpy(),
        "Close": g["Close"].last().to_numpy(),
        "Volume": (g["Volume"].sum().to_numpy() if "Volume" in d.columns
                   else [0.0] * len(full)),
    }).reset_index(drop=True)
    return out
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bars_from_minutes.py -q`
Expected: 10 passed.

If `test_every_frame_needs_its_full_minute_count[1d]` fails on the forming bar: the fixture's third bar has 3 minutes, `counts == per` excludes it — it must pass; if it does not, the bucket arithmetic is off by the epoch offset (1_757_980_800_000 is midnight UTC, so `ts // bar_ms * bar_ms` aligns). Fix the arithmetic, never the test.

- [ ] **Step 6: Run the v1 guards that read TFS**

Run: `.venv/Scripts/python.exe -m pytest tests/test_fast_grid.py tests/test_daily_grid.py tests/test_capped_grid_labels.py -q`
Expected: all pass (adding a key changes no existing lookup).

- [ ] **Step 7: Commit and push**

```bash
git add tests/test_bars_from_minutes.py tradingagents/backtest_report.py tradingagents/market_sweep.py
git commit -F - <<'MSG'
feat(v2): rebuild every frame's bars from 1-minute candles, and a 1m download entry that stays out of v1

Backtest v2 (operator, Sep 17, 2026: "we will use 1min candle so its more
accurate") keeps the v1 signals and only sharpens exits. That is only sound
if sixty one-minute candles ARE the hour candle: measured on XPIN_USDT the
same day, 666 of 666 hours identical to MEXC's own Min60 on O/H/L/C.
`market_sweep.bars_from_1m` holds that on a fixture, drops the partial and
forming bars as v1 does, and refuses a frame with a missing minute rather
than build a bar the venue never printed.

`backtest_report.TFS["1m"]` exists ONLY so the v2 download can page Min1
(44,000 bars = 30.6 days). A regex guard keeps it out of every five-frame
tuple in db_jobs/api/capacity/sweep_shard.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
MSG
git push origin main
```

---

### Task 2: The engine settles exits on 1-minute bars when given them (`fine=`)

**Files:**
- Modify: `tradingagents/auto_trader.py:2591-2606` (signature), `2946-2975` (single-exit walk), `3050-3075` (log/result)
- Test: `tests/test_minute_exact_exits.py`

**Interfaces:**
- Produces: `backtest_strategy(..., fine: tuple | None = None)` where `fine = (t_ms: np.ndarray[int64], high: np.ndarray, low: np.ndarray)` of 1-minute bars sorted by time. Result dict gains `"unclear": int` (trades whose exit minute touched both barriers, still booked SL); `state` gains `"unclear"`; each log row gains `"exit_minute_ms": int | None` and its `"exit time"` is the MINUTE when `fine` is given.
- With `fine=None` the returned dict is identical to today's except for the new `"unclear": 0` key and `"exit_minute_ms": None` on log rows.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_minute_exact_exits.py
"""An hour candle cannot say which of two prices it touched first.

#LG9NSU4B (XPIN 1h, TP 1% / SL 3%) stopped out in the practice account at
Sep 16, 2026 7:28am; the stored backtest said 7:00am, and a bar that held
both prices was booked as a loss by rule. With `fine=` the engine walks the
minutes inside the bar and books what happened first.

The clocks here are ONE timeline: the 1m bars sit inside the hour bars they
belong to. A fixture with two clocks is how RCA-2026-09-12-A hid.
"""
import numpy as np
import pandas as pd
import pytest

from tradingagents import auto_trader as at

KEY = "t_fine_1h"
H0 = 1_757_980_800_000            # Sep 16, 2026 00:00 UTC, on the hour


def _hours(closes, highs, lows, opens=None):
    n = len(closes)
    opens = opens or [closes[i - 1] if i else closes[0] for i in range(n)]
    return pd.DataFrame({
        "Date": pd.to_datetime([H0 + i * 3_600_000 for i in range(n)], unit="ms"),
        "Open": opens, "High": highs, "Low": lows, "Close": closes,
        "Volume": [1000.0] * n})


def _minutes(hour_idx, path):
    """`path` is 60 (high, low) pairs for the minutes of hour `hour_idx`."""
    t = np.array([H0 + hour_idx * 3_600_000 + k * 60_000 for k in range(60)], dtype="int64")
    h = np.array([p[0] for p in path], dtype="float64")
    l = np.array([p[1] for p in path], dtype="float64")
    return t, h, l


def _flat_minutes(hour_idx, px):
    return _minutes(hour_idx, [(px, px)] * 60)


def _fine(*parts):
    t = np.concatenate([p[0] for p in parts]); h = np.concatenate([p[1] for p in parts])
    l = np.concatenate([p[2] for p in parts])
    o = np.argsort(t)
    return t[o], h[o], l[o]


@pytest.fixture(autouse=True)
def _spec():
    at.STRATEGY_SPECS[KEY] = {"interval": "Min60", "bar_seconds": 3600,
                              "tp": .01, "sl": .03, "threshold": .003}
    yield
    at.STRATEGY_SPECS.pop(KEY, None)


# signal on bar 0, entry at bar 1's open (100.0), TP 101.0, SL 97.0.
# Bar 1 touches BOTH: high 101.5, low 96.5.
BOTH = _hours(closes=[100.0, 100.0, 100.0], highs=[100.2, 101.5, 100.2],
              lows=[99.8, 96.5, 99.8], opens=[100.0, 100.0, 100.0])
DIRS = [1, 0, 0]


def test_without_fine_the_result_is_todays_result_plus_a_zero():
    a = at.backtest_strategy(KEY, BOTH, 5.0, dirs=DIRS, sizing="flat", keep_log=True)
    assert a["unclear"] == 0
    assert a["trades"] == 1 and a["losses"] == 1, "one bar holding both prices is a LOSS by rule"
    assert a["log"][0]["why"] == "SL" and a["log"][0]["exit_minute_ms"] is None


def test_minute_order_decides_when_the_minutes_are_known():
    # minutes 0-9 rise to 101.5 (TP touched first), minutes 10-59 crash to 96.5
    path = [(101.5 if k < 10 else 100.0, 100.0 if k < 10 else 96.5) for k in range(60)]
    fine = _fine(_flat_minutes(0, 100.0), _minutes(1, path), _flat_minutes(2, 100.0))
    a = at.backtest_strategy(KEY, BOTH, 5.0, dirs=DIRS, sizing="flat", keep_log=True, fine=fine)
    assert a["wins"] == 1 and a["log"][0]["why"] == "TP", "TP came first, so it is a WIN"
    assert a["unclear"] == 0
    assert a["log"][0]["exit_minute_ms"] == H0 + 3_600_000 + 0 * 60_000


def test_the_stop_first_is_still_a_stop():
    path = [(100.0 if k < 10 else 101.5, 96.5 if k < 10 else 100.0) for k in range(60)]
    fine = _fine(_flat_minutes(0, 100.0), _minutes(1, path), _flat_minutes(2, 100.0))
    a = at.backtest_strategy(KEY, BOTH, 5.0, dirs=DIRS, sizing="flat", keep_log=True, fine=fine)
    assert a["losses"] == 1 and a["log"][0]["why"] == "SL"


def test_both_in_the_same_minute_books_the_loss_and_is_counted_unclear():
    path = [(100.0, 100.0)] * 27 + [(101.5, 96.5)] + [(100.0, 100.0)] * 32
    fine = _fine(_flat_minutes(0, 100.0), _minutes(1, path), _flat_minutes(2, 100.0))
    a = at.backtest_strategy(KEY, BOTH, 5.0, dirs=DIRS, sizing="flat", keep_log=True, fine=fine)
    assert a["log"][0]["why"] == "SL" and a["unclear"] == 1
    assert a["state"]["unclear"] == 1, "the count must survive a resume"


def test_the_exit_time_is_the_minute_not_the_hour():
    from tradingagents.positions_view import fmt_when
    path = [(100.0, 100.0)] * 28 + [(100.0, 96.5)] + [(100.0, 100.0)] * 31   # SL at minute 28
    fine = _fine(_flat_minutes(0, 100.0), _minutes(1, path), _flat_minutes(2, 100.0))
    a = at.backtest_strategy(KEY, BOTH, 5.0, dirs=DIRS, sizing="flat", keep_log=True, fine=fine)
    m = H0 + 3_600_000 + 28 * 60_000
    assert a["log"][0]["exit_minute_ms"] == m
    assert a["log"][0]["exit time"] == fmt_when(m / 1000), "printed through the ONE formatter"


def test_an_hour_with_no_minutes_falls_back_to_the_bar_rule():
    """The 1m store may be younger than the hour store. A bar with no minutes
    under it is settled the old way — never skipped, never guessed finer."""
    fine = _fine(_flat_minutes(0, 100.0))          # nothing for bar 1
    a = at.backtest_strategy(KEY, BOTH, 5.0, dirs=DIRS, sizing="flat", keep_log=True, fine=fine)
    assert a["log"][0]["why"] == "SL" and a["unclear"] == 0
    assert a["log"][0]["exit_minute_ms"] is None


def test_fine_never_changes_a_bar_that_touched_one_price_only():
    """Parity on the common case: 200 random hours, every exit bar touching at
    most one barrier — with and without minutes the answers are identical to
    the cent, because the minutes can only re-order what one bar held."""
    import random
    rng = random.Random(3)
    n = 200
    closes, highs, lows = [], [], []
    px = 100.0
    for _ in range(n):
        px *= 1 + rng.gauss(0, 0.004)
        closes.append(px); highs.append(px * 1.002); lows.append(px * 0.998)
    df = _hours(closes, highs, lows)
    dirs = [rng.choice([1, -1, 0, 0, 0]) for _ in range(n)]
    parts = []
    for i in range(n):
        # minutes that stay INSIDE the hour's range: same high, same low
        parts.append(_minutes(i, [(highs[i], lows[i])] * 60))
    fine = _fine(*parts)
    a = at.backtest_strategy(KEY, df, 5.0, dirs=dirs, sizing="flat", keep_log=True, tp=.05, sl=.05)
    b = at.backtest_strategy(KEY, df, 5.0, dirs=dirs, sizing="flat", keep_log=True, tp=.05, sl=.05, fine=fine)
    for k in ("trades", "wins", "profit", "worst_trade", "max_dd", "monthly"):
        assert a[k] == b[k], k
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minute_exact_exits.py -q`
Expected: FAIL — `TypeError: backtest_strategy() got an unexpected keyword argument 'fine'` and `KeyError: 'unclear'`.

- [ ] **Step 3: Add the parameter and the minute walk**

In `tradingagents/auto_trader.py`, change the signature (line 2591-2606) to add, after `sig_idx=None`:

```python
                      sig_idx=None,
                      fine: tuple | None = None) -> dict:
```

Add to the docstring, after the `slices` paragraph:

```
    ``fine`` is ``(t_ms, high, low)`` — one-minute bars, sorted, as int64/
    float64 arrays — and it is Backtest v2's whole difference from v1. When it
    is given, an exit bar is not settled by the rule "SL before TP inside one
    bar": the minutes inside that bar are walked in ORDER and the first price
    touched wins. Both touched in the SAME minute is still booked SL (the
    worst case is the only honest one at the finest resolution the venue
    sells) and counted in ``unclear``. A bar with no minutes under it falls
    back to the bar rule. The exit time is the MINUTE. #LG9NSU4B stopped out
    at Sep 16, 2026 7:28am in the practice account and the hour walk said
    7:00am — this is the fix. ``None`` is byte-identical to before
    (tests/test_minute_exact_exits.py).
```

After the `_f_cum` loop (line ~2704, right after `_f_cum.append(_f_cum[-1] + _r)` block) add:

```python
    # v2: the minutes, and where each bar's minutes start. `np.searchsorted`
    # on the sorted minute clock finds a bar's slice in O(log n); the walk
    # below reads one slice per exit bar, never the whole array.
    _fine_t = _fine_h = _fine_l = None
    if fine is not None:
        import numpy as _np

        _fine_t = _np.asarray(fine[0], dtype="int64")
        _fine_h = _np.asarray(fine[1], dtype="float64")
        _fine_l = _np.asarray(fine[2], dtype="float64")
    n_unclear = 0
```

Add a helper right after `_bar_label` (inside the function, before `_held`):

```python
    def _settle_fine(j: int, s: int, tp_px: float, sl_px: float,
                     liq_px: float | None):
        """Walk the minutes inside bar `j`. Returns (why, minute_ms, unclear)
        or None when the bar has no minutes under it."""
        if _fine_t is None or _bar_ms_all is None:
            return None
        import numpy as _np

        a = int(_np.searchsorted(_fine_t, int(_bar_ms_all[j]), side="left"))
        b = int(_np.searchsorted(_fine_t, int(_bar_ms_all[j]) + _bar_s * 1000, side="left"))
        if b <= a:
            return None
        hh, ll, tt = _fine_h[a:b], _fine_l[a:b], _fine_t[a:b]
        if s == 1:
            hit_tp = hh >= tp_px
            hit_sl = ll <= sl_px
            hit_liq = (ll <= liq_px) if liq_px is not None else _np.zeros(len(hh), dtype=bool)
        else:
            hit_tp = ll <= tp_px
            hit_sl = hh >= sl_px
            hit_liq = (hh >= liq_px) if liq_px is not None else _np.zeros(len(hh), dtype=bool)
        first = _np.flatnonzero(hit_tp | hit_sl | hit_liq)
        if not len(first):
            return ("NONE", None, 0)
        k = int(first[0])
        # liquidation first only when it is nearer than the stop, as the bar rule
        if hit_liq[k] and (liq is None or liq <= sl or not hit_sl[k]):
            return ("LIQ", int(tt[k]), 0)
        if hit_sl[k] and hit_tp[k]:
            return ("SL", int(tt[k]), 1)          # same minute: worst case, counted
        if hit_sl[k]:
            return ("SL", int(tt[k]), 0)
        return ("TP", int(tt[k]), 0)
```

`_bar_ms_all` must exist whether or not funding was passed. Right after the existing `_bar_ms = ...` assignment (line ~2708) add:

```python
    # every bar's open in epoch ms — the minute walk needs it even when no
    # funding history was passed (`_bar_ms` is None then, on purpose)
    _bar_ms_all = (df["Date"].to_numpy().astype("datetime64[ms]")
                   .astype("int64")) if fine is not None else None
```

Now the single-exit walk (line ~2946, `while j < n and not _skip_single:`). Replace the loop body so each bar first asks the minutes:

```python
        _exit_min = None
        while j < n and not _skip_single:
            hit_liq = liq_px is not None and (
                low[j] <= liq_px if s == 1 else high[j] >= liq_px)
            hit_sl = (low[j] <= sl_px if s == 1 else high[j] >= sl_px)
            hit_tp = (high[j] >= tp_px if s == 1 else low[j] <= tp_px)
            if not (hit_liq or hit_sl or hit_tp):
                j += 1
                continue
            # v2: the bar touched something — let the MINUTES say what came
            # first. None means this bar has no minutes under it (the 1m
            # store is younger than the hour store): fall through to the
            # bar rule below, exactly as v1.
            got = _settle_fine(j, s, tp_px, sl_px, liq_px) if _fine_t is not None else None
            if got is not None and got[0] != "NONE":
                why, _exit_min, _unc = got
                n_unclear += _unc
                out = -liq if why == "LIQ" else (-sl if why == "SL" else tp)
                break
            if got is not None and got[0] == "NONE":
                # the minutes never touched what the hour's high/low claims —
                # a rebuilt bar and its minutes disagree; keep the bar rule
                # and say so once in the log's `why`
                pass
            # Worst case inside one bar: liquidation is checked FIRST, and it
            # only wins when it is nearer than the stop.
            if hit_liq and (liq is None or liq <= sl or not hit_sl):
                out, why = -liq, "LIQ"
                break
            if hit_sl:
                out, why = -sl, "SL"
                break
            out, why = tp, "TP"
            break
```

Funding: where `_b = _bis.bisect_right(_f_ms, int(_bar_ms[j]))` is computed for the single exit (line ~2999), use the minute when known:

```python
            _to = int(_exit_min) if _exit_min is not None else int(_bar_ms[j])
            _b = _bis.bisect_right(_f_ms, _to)
```

Log row: in the `log.append({...})` (line ~3050) change `"exit time": stamp(j)` to:

```python
                    "exit time": (_pv.fmt_when(_exit_min / 1000)
                                  if _exit_min is not None else stamp(j)),
                    "exit_minute_ms": _exit_min,
```

Reset `_exit_min = None` at the top of each trade (it is declared before the `while j < n` loop above, which runs per trade — good). For the `slices` path leave `_exit_min = None` (slices with `fine` is not in this cut; raise if both given):

```python
    if slices is not None and fine is not None:
        raise ValueError("slices with fine= is not supported yet")
```

(put this beside the existing `slices with resume=` guard).

State and result: in `_state` add `"unclear": n_unclear,`; in the resume block add `n_unclear = int(resume.get("unclear", 0))`; in the returned dict add `"unclear": n_unclear,` beside `"liqs"`.

- [ ] **Step 4: Run the new tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_minute_exact_exits.py -q`
Expected: 7 passed.

- [ ] **Step 5: Run every engine guard**

Run: `.venv/Scripts/python.exe -m pytest tests/test_fast_grid.py tests/test_sliced_exits.py tests/test_daily_grid.py tests/test_runner_stakes_flat.py tests/test_resume_state.py -q 2>&1 | tail -5`
Expected: only the pre-existing `test_the_grid_is_told_flat_and_a_one_rung_ladder` failure (the other session's `by_coin` work in api.py) — everything else green. `fast_grid` parity holds because `walk` is untouched and `backtest_strategy(fine=None)` returns the same numbers.

- [ ] **Step 6: Commit ONLY your hunks of auto_trader.py**

`auto_trader.py` carries the other session's `by_coin` edits. Stage HEAD + your change:

```bash
SP="C:/Users/Jeremy/AppData/Local/Temp/claude/g--analyzer-x/2858856a-f290-4d69-b503-7dd0e8b813cf/scratchpad"
git show HEAD:tradingagents/auto_trader.py > "$SP/head_at.py"
.venv/Scripts/python.exe - "$SP" <<'PY'
import pathlib, sys
sp = pathlib.Path(sys.argv[1])
head = (sp / "head_at.py").read_text(encoding="utf-8")
work = pathlib.Path("tradingagents/auto_trader.py").read_text(encoding="utf-8")
def fn(text):
    a = text.index("def backtest_strategy(")
    b = text.index("\n\n\ndef ", a)          # the next top-level def
    return text[a:b]
out = head.replace(fn(head), fn(work), 1)
assert out != head
(sp / "staged_at.py").write_text(out, encoding="utf-8")
PY
.venv/Scripts/python.exe -m py_compile "$SP/staged_at.py"
blob=$(git hash-object -w "$SP/staged_at.py"); git update-index --cacheinfo 100644,$blob,tradingagents/auto_trader.py
git add tests/test_minute_exact_exits.py
git commit -F - <<'MSG'
feat(engine): settle an exit on the minutes inside the bar when they are given (fine=)

#LG9NSU4B stopped out in the practice account at Sep 16, 2026 7:28am; the
stored backtest said 7:00am, and a bar that touched both prices was booked a
loss by rule. `backtest_strategy(fine=(t_ms, high, low))` walks the minutes
inside an exit bar in ORDER: first price touched wins, both in the same
minute is still SL and counted in `unclear`, a bar with no minutes under it
falls back to the bar rule, and the exit time is the minute through the one
formatter. `fine=None` is byte-identical to before — 200-hour parity test.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
MSG
git push origin main
```

---

### Task 3: v2 row identity, the `unclear` column, and `run_pair` measuring from minutes

**Files:**
- Modify: `tradingagents/backtest_report.py:252-280` (`row_code`)
- Modify: `tradingagents/rows_index.py:64-67` (`COLS`), `392-470` (`ensure`)
- Modify: `tradingagents/market_sweep.py:41-53` (env block), `784-830` (`run_pair` frame), `1024-1070` (row dict)
- Test: `tests/test_v2_store_is_its_own_folder.py` (part 1)

**Interfaces:**
- Produces: `backtest_report.row_code(coin, tf, signal, th, sl, tp, sizing, plan=None, res=None)`; `res="1m"` changes the id, `None` leaves every existing id unchanged.
- Produces: `market_sweep.FINE_TF: str` (`""` in v1; `"1m"` when `TRADINGAGENTS_FINE_TF=1m`).
- Produces: `market_sweep.run_pair(...)` in v2 mode builds `df` with `bars_from_1m(cached_candles(symbol, FINE_TF), tf)`, passes `fine=` to the engine, and writes rows with `"res": "1m"`, `"unclear": int`, `"id"` from `row_code(..., res="1m")`.
- Produces: `rows_index.COLS` includes `"unclear"` and `"res"`; `ensure()` adds them to an existing `rows` table with `ALTER TABLE ... ADD COLUMN` (no rewrite).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_v2_store_is_its_own_folder.py
"""v2 lives beside v1 and can never be mistaken for it.

Same signals, same frames, same engine — different folder, different ids,
one more column. A v1 id must hash to itself for ever (the operator pastes
ids between tabs; #05146/#02054 was one row with two names).
"""
import json
import os
import sqlite3
from pathlib import Path

import pytest

from tradingagents import backtest_report as br, rows_index as ri


def test_a_v2_id_never_equals_the_v1_id_and_v1_ids_are_untouched():
    args = ("XPIN", "1h", "ote", 0.0, 3.0, 1.0, "flat")
    v1 = br.row_code(*args)
    v2 = br.row_code(*args, res="1m")
    assert v1 != v2 and len(v1) == len(v2) == 8
    assert v1 == "LG9NSU4B", "the operator's own row — its id is a fixed point"
    assert br.row_code(*args, res=None) == v1


def test_the_index_grows_the_two_v2_columns_without_a_rewrite(tmp_path, monkeypatch):
    db = tmp_path / "rows.db"
    monkeypatch.setattr(ri, "DB_PATH", db)
    ri._ready.clear() if hasattr(ri._ready, "clear") else None
    # an OLD table without the columns, as the operator's 41.94 GB v1 file has
    con = sqlite3.connect(db)
    old_cols = [c for c in ri.COLS if c not in ("unclear", "res")]
    con.execute("CREATE TABLE rows (" + ",".join(old_cols) + ", monthly TEXT, pair TEXT NOT NULL)")
    con.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    con.execute("INSERT INTO meta VALUES ('schema', ?)", (str(ri.SCHEMA_VERSION),))
    con.commit(); con.close()
    ri.ensure()
    have = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(rows)")}
    assert {"unclear", "res"} <= have
    assert "unclear" in ri.COLS and "res" in ri.COLS


def test_values_carry_unclear_and_res_and_default_them_for_a_v1_row():
    r = {"coin": "XPIN", "tf": "1h", "signal": "ote", "th": 0.0, "sl": 3.0, "tp": 1.0,
         "sizing": "flat", "trades": 5, "wins": 4, "losses": 1, "winrate": 80.0,
         "profit": 1.0, "monthly": {}}
    vals = dict(zip(list(ri.COLS) + ["monthly", "pair"], ri._values(r, "XPIN-1h")))
    assert vals["unclear"] is None and vals["res"] is None
    vals2 = dict(zip(list(ri.COLS) + ["monthly", "pair"],
                     ri._values({**r, "unclear": 2, "res": "1m"}, "XPIN-1h")))
    assert vals2["unclear"] == 2 and vals2["res"] == "1m"


def test_fine_tf_is_empty_unless_the_environment_says_so(monkeypatch):
    import importlib
    from tradingagents import market_sweep as msw
    assert msw.FINE_TF == ""
    monkeypatch.setenv("TRADINGAGENTS_FINE_TF", "1m")
    monkeypatch.setenv("TRADINGAGENTS_SWEEP_HOME", str(Path.home() / ".tradingagents" / "v2-test"))
    m2 = importlib.reload(msw)
    try:
        assert m2.FINE_TF == "1m"
    finally:
        monkeypatch.delenv("TRADINGAGENTS_FINE_TF")
        monkeypatch.delenv("TRADINGAGENTS_SWEEP_HOME")
        importlib.reload(msw)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_store_is_its_own_folder.py -q`
Expected: FAIL — `TypeError: row_code() got an unexpected keyword argument 'res'`, `AttributeError: FINE_TF`.

- [ ] **Step 3: `row_code(res=)`**

In `tradingagents/backtest_report.py` change the signature to
`def row_code(coin, tf, signal, th, sl, tp, sizing, plan=None, res=None) -> str:` and, right after the `if plan:` block, add:

```python
    # THE RESOLUTION IS PART OF THE COMBINATION (Backtest v2, Sep 17, 2026).
    # A v2 row is the same coin/frame/signal/barriers measured with exits
    # settled on 1-minute bars, and it must never share an id with the v1
    # row — the operator pastes ids between tabs. Appended ONLY when given,
    # so every id minted before v2 still hashes to itself.
    if res:
        seed += "|res=" + str(res)
```

- [ ] **Step 4: `COLS` and `ensure()`**

In `tradingagents/rows_index.py` replace `COLS`:

```python
COLS = ("id", "coin", "tf", "signal", "th", "sl", "tp", "rr", "sizing", "lev",
        "base", "notional", "trades", "wins", "losses", "winrate", "profit",
        "funding", "h1", "h2", "green", "months", "worst", "dd", "liqs",
        "stop_reachable", "days", "bars", "cost_of_tp", "rt", "gate",
        # Backtest v2 (Sep 17, 2026): trades whose exit minute touched both
        # prices and were booked SL by rule, and the resolution the exits were
        # settled at ("1m"). NULL on every v1 row — the v1 file is never
        # rewritten for this; ensure() ALTERs the two columns on (O(1) in
        # SQLite, metadata only, measured against a 41.94 GB file).
        "unclear", "res")
_NUMERIC = {"th", "sl", "tp", "rr", "base", "notional", "winrate", "profit",
            "funding", "h1", "h2", "worst", "dd", "cost_of_tp", "rt"}
_INTEGER = {"lev", "trades", "wins", "losses", "green", "months", "liqs",
            "days", "bars", "stop_reachable", "unclear"}
```

In `ensure()`, right after the `pairs` ALTER loop (the `for col, typ in (("coin", "TEXT"), ...)` block), add:

```python
        # THE SAME FOR `rows`: a store built before Backtest v2 keeps its
        # 113,495,608 rows; the two v2 columns are added as NULL. ADD COLUMN
        # does not rewrite the file.
        have_rows = {r[1] for r in con.execute("PRAGMA table_info(rows)")}
        for col, typ in (("unclear", "INTEGER"), ("res", "TEXT")):
            if col not in have_rows:
                con.execute(f"ALTER TABLE rows ADD COLUMN {col} {typ}")
```

Check `_SCHEMA`'s `CREATE TABLE IF NOT EXISTS rows` derives from `COLS` (it does) — a fresh v2 db gets the columns from creation.

- [ ] **Step 5: `FINE_TF` and the v2 branch in `run_pair`**

In `tradingagents/market_sweep.py`, after the `CANDLES = ...` block (line ~50) add:

```python
# BACKTEST v2. When this is a frame ("1m"), `run_pair` does not fetch the
# pair's own candles: it rebuilds the frame's bars from the 1-minute cache
# under CANDLES (`bars_from_1m`) and hands the minutes to the engine
# (`backtest_strategy(fine=...)`) so every exit is settled minute by minute.
# Set ONLY by the v2 job kinds (`db_jobs.start` → `stores.V2.env_for()`),
# beside TRADINGAGENTS_SWEEP_HOME/TRADINGAGENTS_CANDLES pointing at
# ~/.tradingagents/v2. Empty here means v1, byte for byte.
FINE_TF = os.environ.get("TRADINGAGENTS_FINE_TF", "").strip()
```

In `run_pair`, replace

```python
    iv, bs, cap = br.TFS[tf]
    df, added, source = refresh_candles(symbol, tf, days=days)
```

with

```python
    iv, bs, cap = br.TFS[tf]
    fine = None
    if FINE_TF:
        # v2: the bars come from the minutes, and so does the exit.
        m1 = cached_candles(symbol, FINE_TF)
        if m1 is None or len(m1) < MINUTES_PER_BAR[tf] * 2:
            return {"coin": coin, "tf": tf, "rows": [], "added": 0,
                    "source": "1m", "why": (f"no {FINE_TF} candles for {symbol} — "
                                            f"download them on Candles v2 first")}
        try:
            df = bars_from_1m(m1, tf)
        except ValueError as exc:
            # NAMED, never measured wrong (rule 20): a hole in the minutes
            # would build a bar the venue never printed
            return {"coin": coin, "tf": tf, "rows": [], "added": 0,
                    "source": "1m", "why": f"{symbol}: {exc}"[:120]}
        import numpy as _np
        fine = (m1["Date"].to_numpy().astype("datetime64[ms]").astype("int64"),
                _np.asarray(m1["High"], dtype="float64"),
                _np.asarray(m1["Low"], dtype="float64"))
        added, source = 0, "1m"
    else:
        df, added, source = refresh_candles(symbol, tf, days=days)
```

Pass `fine=fine` into the engine call:

```python
                    r = at.backtest_strategy(
                        key, frame, base_margin, fee=fee, sizing=sz, dirs=dirs,
                        tp=tp, sl=sl, liq_move_pct=liq, funding=fund,
                        keep_log=False, resume=prev or {}, start_at=off,
                        fine=fine)
```

`frame` is `df.iloc[lo:]` on an incremental pass; `fine` covers the whole 1m history and `_settle_fine` indexes by time, so a sliced frame is fine.

In the row dict, add beside `"liqs": r["liqs"],`:

```python
                    "liqs": r["liqs"],
                    # v2: how many of this row's trades were still a guess
                    # (both prices in one minute) and at what resolution the
                    # exits were settled. Absent on a v1 row.
                    **({"unclear": int(r.get("unclear", 0)), "res": FINE_TF}
                       if FINE_TF else {}),
```

Where the row's id is minted — find `_row_id` in `rows_index.py` (it calls `br.row_code`) and make it pass `res=r.get("res")`:

```python
def _row_id(r: dict) -> str:
    return br.row_code(r["coin"], r["tf"], r["signal"], r.get("th", 0.0),
                       r["sl"], r["tp"], r.get("sizing", "flat"),
                       plan=r.get("plan"), res=r.get("res"))
```

(read the existing body first and keep its other arguments exactly; only add `res=`.)

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_store_is_its_own_folder.py tests/test_rows_index*.py tests/test_row_id*.py -q 2>&1 | tail -5`
Expected: new tests pass; every existing rows_index / row-id test passes (`_values` returns two more items, all consumers zip against `COLS`).

- [ ] **Step 7: Commit and push**

```bash
git add tests/test_v2_store_is_its_own_folder.py tradingagents/backtest_report.py tradingagents/rows_index.py tradingagents/market_sweep.py
git commit -F - <<'MSG'
feat(v2): a v2 row has its own id, an unclear count, and is measured from the minutes

`row_code(res="1m")` appends the resolution to the seed only when given, so
#LG9NSU4B still hashes to itself and no v2 id can equal a v1 id. `rows_index`
gains `unclear` and `res` (ALTER TABLE ADD COLUMN — metadata only, the v1
file is not rewritten). `market_sweep.FINE_TF` (TRADINGAGENTS_FINE_TF) makes
`run_pair` rebuild the frame's bars from the 1m cache and hand the minutes to
the engine; a pair with no minutes or a hole in them is refused and NAMED.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
MSG
git push origin main
```

---

### Task 4: `Store`, the v2 job kinds, and the download job accepting `1m`

**Files:**
- Create: `tradingagents/stores.py`
- Modify: `tradingagents/parquet_store.py:26-28`
- Modify: `tradingagents/db_jobs.py:43-60` (FILES), `594-640` (start), `733-800` (update_pairs), `1001-1080` (download), `2229-2251` (main); supervisor tuple `api.py:165`
- Test: `tests/test_v2_store_is_its_own_folder.py` (part 2)

**Interfaces:**
- Produces: `stores.Store(name, home, candles, rows_db, parquet, fine_tf, download_kind, backtest_kind)`, `stores.V1`, `stores.V2`, `stores.by_name("v1"|"v2")`, `Store.env_for() -> dict[str,str]` (the env a job process needs), `Store.exists() -> bool`.
- Produces: `db_jobs.FILES["download_v2"]`, `db_jobs.FILES["backtest_v2"]`; `db_jobs.start(kind, spec)` merges `stores.V2.env_for()` into the child env for those kinds; `db_jobs.main` dispatches them; `update_pairs(lost, tfs=("15m","30m","1h","4h","1d"))`; `_run_download` accepts `"1m"` when `spec["tfs"] == ["1m"]` under `download_v2`.
- `parquet_store.ROOT` reads `TRADINGAGENTS_PARQUET`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_v2_store_is_its_own_folder.py`)

```python
def test_the_two_stores_never_share_a_path():
    from tradingagents import stores
    a, b = stores.V1, stores.V2
    for f in ("home", "candles", "rows_db", "parquet"):
        assert getattr(a, f) != getattr(b, f), f
    assert str(b.home).replace("\\", "/").endswith("/.tradingagents/v2")
    assert b.fine_tf == "1m" and a.fine_tf == ""
    assert stores.by_name("v2") is b and stores.by_name("v1") is a
    with pytest.raises(KeyError):
        stores.by_name("v3")


def test_a_v2_job_is_spawned_into_the_v2_folder_and_a_v1_job_is_not(monkeypatch, tmp_path):
    from tradingagents import db_jobs as dj, stores
    seen = {}

    class _P:
        pid = 4242
    def fake_popen(args, **kw):
        seen["env"] = kw.get("env") or {}
        seen["args"] = args
        return _P()
    monkeypatch.setattr(dj.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(dj, "STATE_DIR", tmp_path)
    for k in ("download", "download_v2", "backtest_v2"):
        for name, p in dj.FILES[k].items():
            monkeypatch.setitem(dj.FILES[k], name, tmp_path / p.name)
    monkeypatch.setattr(dj, "status", lambda kind: {"running": False})

    dj.start("download_v2", {"coins": ["XPIN_USDT"], "tfs": ["1m"]})
    env = seen["env"]
    want = stores.V2.env_for()
    for k, v in want.items():
        assert env.get(k) == v, k
    assert env["TRADINGAGENTS_FINE_TF"] == "1m"
    assert seen["args"][-1] == "download_v2"

    dj.start("download", {"coins": ["XPIN_USDT"], "tfs": ["15m"]})
    for k in want:
        assert k not in seen["env"] or seen["env"][k] == os.environ.get(k, seen["env"][k]), \
            f"a v1 job must not inherit a v2 root ({k})"


def test_update_pairs_for_v2_only_ever_asks_for_1m(monkeypatch):
    from tradingagents import db_jobs as dj, market_sweep as msw
    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: ["XPIN_USDT", "ARKM_USDT"])
    monkeypatch.setattr(msw, "candle_index", lambda *a, **k: {
        "XPIN_USDT-1m": {"bars": 100, "last_ms": 1_757_980_800_000}})
    pairs, gone, n_missing, lost_added = dj.update_pairs([], tfs=("1m",))
    assert ("ARKM_USDT", "1m") in pairs and ("XPIN_USDT", "1m") in pairs
    assert all(tf == "1m" for _, tf in pairs)


def test_the_download_job_accepts_1m_only_for_the_v2_kind():
    from tradingagents import db_jobs as dj
    assert dj._download_tfs({"tfs": ["1m", "15m"]}, kind="download_v2") == ["1m"]
    assert dj._download_tfs({"tfs": ["1m", "15m"]}, kind="download") == ["15m"]


def test_parquet_root_follows_the_environment(monkeypatch):
    import importlib
    from tradingagents import parquet_store as pqs
    monkeypatch.setenv("TRADINGAGENTS_PARQUET", str(Path.home() / ".tradingagents" / "parquet-v2"))
    m2 = importlib.reload(pqs)
    try:
        assert str(m2.ROOT).replace("\\", "/").endswith("/.tradingagents/parquet-v2")
        assert str(m2.CANDLES).replace("\\", "/").endswith("/parquet-v2/candles")
    finally:
        monkeypatch.delenv("TRADINGAGENTS_PARQUET")
        importlib.reload(pqs)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_store_is_its_own_folder.py -q`
Expected: FAIL — `ModuleNotFoundError: tradingagents.stores`, `KeyError: 'download_v2'`.

- [ ] **Step 3: `tradingagents/stores.py`**

```python
"""Which store: v1 (the 113-million-row year-deep grid) or v2 (Backtest v2,
minute-exact exits on a 1-minute candle store). Sep 17, 2026.

ONE place that knows both folders. The sweep, the index and the parquet
store already switch roots on environment settings; a v2 JOB is the same
code launched with `V2.env_for()`, and the API reads a v2 store by passing
these paths explicitly (it serves both versions from one process, so it can
never flip a module global).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_HOME = Path(os.path.expanduser("~/.tradingagents"))


@dataclass(frozen=True)
class Store:
    name: str
    home: Path            # market_sweep.HOME: state/, rows/, rows.db, manifest
    candles: Path         # market_sweep.CANDLES: the sweep's candle cache
    rows_db: Path         # rows_index.DB_PATH
    parquet: Path         # parquet_store.ROOT
    fine_tf: str          # market_sweep.FINE_TF: "" for v1, "1m" for v2
    download_kind: str    # db_jobs.FILES key
    backtest_kind: str

    def env_for(self) -> dict[str, str]:
        """The environment a job process needs to work in THIS store."""
        return {
            "TRADINGAGENTS_SWEEP_HOME": str(self.home),
            "TRADINGAGENTS_CANDLES": str(self.candles),
            "TA_ROWS_DB": str(self.rows_db),
            "TRADINGAGENTS_PARQUET": str(self.parquet),
            "TRADINGAGENTS_FINE_TF": self.fine_tf,
        }

    def exists(self) -> bool:
        return self.candles.exists() or self.rows_db.exists()

    @property
    def tfs(self) -> tuple[str, ...]:
        """What the DOWNLOAD fetches here."""
        return (self.fine_tf,) if self.fine_tf else ("15m", "30m", "1h", "4h", "1d")


V1 = Store(name="v1", home=_HOME / "backtest", candles=_HOME / "backtest" / "candles",
           rows_db=_HOME / "backtest" / "rows.db", parquet=_HOME / "parquet",
           fine_tf="", download_kind="download", backtest_kind="backtest")
V2 = Store(name="v2", home=_HOME / "v2", candles=_HOME / "v2" / "candles",
           rows_db=_HOME / "v2" / "rows.db", parquet=_HOME / "parquet-v2",
           fine_tf="1m", download_kind="download_v2", backtest_kind="backtest_v2")

_BY_NAME = {"v1": V1, "v2": V2}


def by_name(name: str) -> Store:
    return _BY_NAME[str(name).lower()]


def for_kind(kind: str) -> Store:
    """The store a job KIND works in (`download_v2` → V2, everything else V1)."""
    return V2 if str(kind).endswith("_v2") else V1
```

- [ ] **Step 4: `parquet_store.ROOT`**

```python
ROOT = Path(os.path.expanduser(
    # Backtest v2 (Sep 17, 2026) keeps its parquet copies beside its own
    # store: the v2 download job runs with TRADINGAGENTS_PARQUET set to
    # ~/.tradingagents/parquet-v2 (see tradingagents/stores.py).
    os.environ.get("TRADINGAGENTS_PARQUET") or "~/.tradingagents/parquet"))
CANDLES = ROOT / "candles"
GRIDS = ROOT / "grids"
```

- [ ] **Step 5: `db_jobs` — kinds, env, dispatch, whitelist, update_pairs**

`FILES`: add after the `"backtest"` entry:

```python
    # BACKTEST v2 (Sep 17, 2026): the same two jobs, in ~/.tradingagents/v2.
    # Own progress/spec/pid/stop/log files so the two versions can be watched
    # apart; `start()` gives them the v2 environment (stores.V2.env_for()).
    "download_v2": {"progress": STATE_DIR / "db_download_v2.json",
                    "spec": STATE_DIR / "db_download_v2.spec.json",
                    "lost": STATE_DIR / "db_download_v2.lost.json",
                    "pid": STATE_DIR / "db_download_v2.pid",
                    "stop": STATE_DIR / "db_download_v2.STOP"},
    "backtest_v2": {"progress": STATE_DIR / "db_backtest_v2.json",
                    "spec": STATE_DIR / "db_backtest_v2.spec.json",
                    "pid": STATE_DIR / "db_backtest_v2.pid",
                    "stop": STATE_DIR / "db_backtest_v2.STOP",
                    "handoff": STATE_DIR / "db_backtest_v2.HANDOFF"},
```

`start()`: replace `env = {**os.environ, "PYTHONUNBUFFERED": "1"}` with

```python
    from tradingagents import stores as _stores

    # A v2 kind works in the v2 folder — the roots travel as environment,
    # which every module already reads at import. A v1 kind gets nothing
    # extra, so it cannot inherit a v2 root from this process by accident.
    env = {**os.environ, "PYTHONUNBUFFERED": "1",
           **(_stores.for_kind(kind).env_for() if kind.endswith("_v2") else {})}
```

`main()`: add

```python
    elif kind == "download_v2":
        _run_download(spec, kind="download_v2")
    elif kind == "backtest_v2":
        _run_backtest(spec, files_key="backtest_v2", kind="backtest_v2")
```

`_run_download(spec, kind="download")`: change the signature, `f = FILES[kind]`, and replace the `else:` branch's tf filter with a helper:

```python
def _download_tfs(spec: dict, kind: str = "download") -> list[str]:
    """Which frames a download may fetch. v1: the five. v2: 1m and nothing
    else — a 15m pair in the v2 folder would be a bar the v2 measure never
    reads, and a 1m pair in v1 would be a sixth frame every v1 list denies."""
    want = [str(t) for t in (spec.get("tfs") or [])]
    ok = ("1m",) if kind.endswith("_v2") else ("15m", "30m", "1h", "4h", "1d")
    return [t for t in want if t in ok]
```

and in the body: `tfs = _download_tfs(spec, kind)`. In the `mode == "update"` branch pass `tfs=("1m",) if kind.endswith("_v2") else ("15m","30m","1h","4h","1d")` into `update_pairs(...)`. Every `_nt.record("download", ...)` in the function becomes `_nt.record(kind, ...)`, and `_stopping("download")` becomes `_stopping(kind)`. `refresh_candles(c, tf, days=365)` is unchanged — for `"1m"` it pages 44,000 bars and accumulates (`days + 30` = 395 days kept).

`update_pairs(lost=None, tfs=("15m", "30m", "1h", "4h", "1d"))`: change the signature and the inner loop `for tf in ("15m", "30m", "1h", "4h", "1d"):` → `for tf in tfs:`.

ONE JOB AT A TIME, ACROSS BOTH VERSIONS. `start()` only ever checked its own
kind, so a v2 download could start beside a v1 download and share one
spindle (the two-jobs-one-disk stall of RCA-2026-09-10). Add, before the
`st = status(kind)` line in `start()`:

```python
class JobBusy(RuntimeError):
    """Another job holds the disk. Named so the API can answer 409 with it."""


_DISK_JOBS = ("download", "backtest", "btupdate", "collect",
              "download_v2", "backtest_v2")
```

(module level, beside `LocalSweepsOff`), and in `start()`:

```python
    # ONE DISK. A v2 job beside a v1 job is two jobs on one mechanical
    # spindle — measured on Sep 10, 2026 as a rebuild falling from 40.15
    # pairs/min to 0.25 while a collect rewrote the files it read. Refuse
    # with the HOLDER named, whichever version is asking.
    for other in _DISK_JOBS:
        if other != kind and status(other).get("running"):
            raise JobBusy(f"{other} is running — one job at a time, across "
                          f"both versions; stop it or wait for it to finish")
```

and in `api.job_start` catch `db_jobs.JobBusy` the same way `LocalSweepsOff`
is caught (409). Test (append to the test file):

```python
def test_a_v2_job_waits_for_a_v1_job_and_the_other_way_round(monkeypatch, tmp_path):
    from tradingagents import db_jobs as dj
    monkeypatch.setattr(dj, "status", lambda kind: {"running": kind == "download"})
    with pytest.raises(dj.JobBusy, match="download is running"):
        dj.start("download_v2", {"coins": [], "tfs": ["1m"]})
    monkeypatch.setattr(dj, "status", lambda kind: {"running": kind == "backtest_v2"})
    with pytest.raises(dj.JobBusy, match="backtest_v2 is running"):
        dj.start("download", {"coins": [], "tfs": ["15m"]})
```

`api.py:165` supervisor tuple → `("backtest", "download", "btupdate", "download_v2", "backtest_v2")` (stage this hunk alone — api.py carries another session's work; use the blob recipe from Task 2 step 6 with `fn` selecting the supervisor block by its comment `# NO AUTOMATIC CANDLE TOP-UP` through `for kind in (...)`).

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_store_is_its_own_folder.py tests/test_download_retry.py tests/test_candle_update_reliability.py tests/test_pair_retry.py -q 2>&1 | tail -5`
Expected: new tests pass; `test_candle_update_reliability.py` keeps its 2 pre-existing failures and nothing new.

- [ ] **Step 7: Commit and push** (api.py via the blob recipe)

```bash
git add tradingagents/stores.py tradingagents/parquet_store.py tradingagents/db_jobs.py tests/test_v2_store_is_its_own_folder.py
# api.py: only the supervisor tuple hunk — recipe as Task 2 step 6, selecting
# the text between 'for kind in ("backtest", "download", "btupdate"' and the
# closing of that for-loop
git commit -F - <<'MSG'
feat(v2): the v2 store is its own folder, and its two jobs are the v1 jobs launched into it

`tradingagents/stores.py` names both stores once. `download_v2`/`backtest_v2`
are new job kinds with their own progress files; `db_jobs.start` gives them
the v2 environment (sweep home, candle cache, rows.db, parquet root, FINE_TF)
and nothing to a v1 kind. The download job accepts "1m" only under the v2
kind; `update_pairs(tfs=)` asks the venue's list for 1m only; the supervisor
restarts the v2 jobs like the v1 ones.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
MSG
git push origin main
```

---

### Task 5: The API can read a store it is told about (`db_path` / `root`)

**Files:**
- Modify: `tradingagents/rows_index.py:317-392` (`_connect`, `_open`), `query`, `query_sql`, `status`, `pair_storage`, `facets`, `export_plan`, `iter_rows`
- Modify: `tradingagents/market_sweep.py:2001-2060` (`candle_index(root=)`)
- Test: `tests/test_v2_store_is_its_own_folder.py` (part 3)

**Interfaces:**
- Produces: every listed `rows_index` reader takes `db_path: Path | None = None`; `None` means `DB_PATH` (unchanged). `_connect(readonly=False, same_thread=True, db_path=None)`, `_open(readonly=False, same_thread=True, db_path=None)`.
- Produces: `market_sweep.candle_index(rebuild=False, scan=True, root: Path | None = None)` — `root` is the candle dir; the index file is `root.parent / "candle_index.json"` when `root` is given.

- [ ] **Step 1: Write the failing tests** (append)

```python
def _seed(db: Path, rows: list[dict]) -> None:
    from tradingagents import rows_index as ri
    import sqlite3 as _sq
    con = _sq.connect(db)
    con.executescript(ri._SCHEMA)
    con.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    con.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (str(ri.SCHEMA_VERSION),))
    ph = "(" + ",".join("?" * (len(ri.COLS) + 2)) + ")"
    con.executemany(f"INSERT INTO rows ({','.join(ri.COLS)},monthly,pair) VALUES {ph}",
                    [ri._values(r, f"{r['coin']}-{r['tf']}") for r in rows])
    con.execute("INSERT OR REPLACE INTO pairs (pair, mtime, size, n, at, coin, tf) VALUES (?,?,?,?,?,?,?)",
                (f"{rows[0]['coin']}-{rows[0]['tf']}", 1.0, 1, len(rows), 1.0, rows[0]["coin"], rows[0]["tf"]))
    for ddl in ri.KEEP_INDEXES:
        con.execute(ddl)
    con.commit(); con.close()


def _row(coin, profit, **kw):
    base = {"coin": coin, "tf": "1h", "signal": "ote", "th": 0.0, "sl": 3.0, "tp": 1.0,
            "rr": 0.33, "sizing": "flat", "lev": 20, "base": 5.0, "notional": 100.0,
            "trades": 10, "wins": 8, "losses": 2, "winrate": 80.0, "profit": profit,
            "funding": 0.0, "h1": 1.0, "h2": 1.0, "green": 1, "months": 1, "worst": -1.0,
            "dd": 1.0, "liqs": 0, "stop_reachable": True, "days": 30, "bars": 720,
            "cost_of_tp": 10.0, "rt": 0.1, "gate": "ok", "monthly": {"2026-09": profit}}
    base.update(kw)
    return base


def test_the_index_answers_from_the_store_it_is_handed(tmp_path, monkeypatch):
    from tradingagents import rows_index as ri
    v1, v2 = tmp_path / "v1.db", tmp_path / "v2.db"
    _seed(v1, [_row("XPIN", 10.0)])
    _seed(v2, [_row("XPIN", 99.0, unclear=2, res="1m")])
    monkeypatch.setattr(ri, "DB_PATH", v1)
    a = ri.query(coin="XPIN")
    b = ri.query(coin="XPIN", db_path=v2)
    assert a["rows"][0]["profit"] == 10.0 and a["rows"][0].get("unclear") is None
    assert b["rows"][0]["profit"] == 99.0 and b["rows"][0]["unclear"] == 2
    assert b["rows"][0]["id"] != a["rows"][0]["id"], "v2 ids differ from v1 ids"
    assert ri.status(db_path=v2)["rows"] == 1
    assert ri.pair_storage(db_path=v2)[0]["n"] == 1


def test_candle_index_reads_the_root_it_is_handed(tmp_path):
    from tradingagents import market_sweep as msw
    root = tmp_path / "v2" / "candles"
    root.mkdir(parents=True)
    (root / "XPIN_USDT-1m.json").write_text(json.dumps(
        {"t": [1_757_980_800_000, 1_757_980_860_000], "o": [1, 1], "h": [1, 1],
         "l": [1, 1], "c": [1, 1], "v": [1, 1]}))
    got = msw.candle_index(root=root)
    assert set(got) == {"XPIN_USDT-1m"} and got["XPIN_USDT-1m"]["bars"] == 2
    assert (root.parent / "candle_index.json").exists(), "its own index file, beside its own candles"
```

- [ ] **Step 2: Run to verify they fail**

Expected: `TypeError: query() got an unexpected keyword argument 'db_path'`, `candle_index() got an unexpected keyword argument 'root'`.

- [ ] **Step 3: Thread `db_path`**

In `rows_index.py`:
- `_connect(readonly=False, same_thread=True, db_path=None)`: `p = Path(db_path) if db_path else DB_PATH` and use `p` everywhere `DB_PATH` was used inside the function.
- `_open(readonly=False, same_thread=True, db_path=None)` passes it to `_connect`.
- `query(..., db_path=None)`, `query_sql(..., db_path=None)`, `status(db_path=None)`, `pair_storage(db_path=None)`, `facets(db_path=None)`, `export_plan(..., db_path=None)`, `iter_rows(..., db_path=None)`: pass `db_path=db_path` into every `_open(...)`/`_connect(...)` they call (grep each function body for `_open(` and `_connect(`; there are no other connection sites in the read path). `status()` also reads `msw.ROWDIR` for `on_disk`; when `db_path` is given use `Path(db_path).parent / "rows"` instead.
- Add a docstring line to `_connect`: *"`db_path` is how the API reads Backtest v2's `~/.tradingagents/v2/rows.db` from the one process that also serves v1; a module global can never be flipped per request."*

In `market_sweep.candle_index(rebuild=False, scan=True, root=None)`: `cdir = Path(root) if root else CANDLES`, `ipath = (cdir.parent / "candle_index.json") if root else INDEX_PATH`; use `cdir`/`ipath` in place of `CANDLES`/`INDEX_PATH` inside.

- [ ] **Step 4: Run**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_store_is_its_own_folder.py tests/test_rows_index*.py tests/test_index_stall_is_visible.py tests/test_the_indexer_is_never_allowed_to_stay_dead.py -q 2>&1 | tail -4`
Expected: all green (defaults unchanged).

- [ ] **Step 5: Commit and push**

```bash
git add tradingagents/rows_index.py tradingagents/market_sweep.py tests/test_v2_store_is_its_own_folder.py
git commit -F - <<'MSG'
feat(v2): the index and the candle index can read a store they are handed

`rows_index.query/query_sql/status/pair_storage/facets/export_plan/iter_rows`
take `db_path=None` (default: DB_PATH, unchanged) and `market_sweep.
candle_index` takes `root=None`, so the one API process can serve Backtest
v2's ~/.tradingagents/v2 beside v1 without touching a module global.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
MSG
git push origin main
```

---

### Task 6: `/api/v2/...` routes

**Files:**
- Modify: `tradingagents/api.py` — strategies (305), strategies.csv (670), facets (854), candles pending/gaps/completeness/lost/download-history (2892/2922/3196/3203/3294), backtest/storage (3335)
- Test: `tests/test_v2_routes.py`

**Interfaces:**
- Produces: `GET /api/v2/strategies` (same query params as v1, plus rows carry `unclear`), `GET /api/v2/strategies.csv`, `GET /api/v2/strategies/facets`, `GET /api/v2/candles/{pending,gaps,completeness,lost,download-history}`, `GET /api/v2/backtest/storage`. Jobs already work by kind: `/api/jobs/download_v2`, `/api/jobs/backtest_v2` (+ `/start`, `/stop`).
- An empty/missing v2 store answers `{"rows": [], "total": 0, "why": "no v2 store yet — download 1m candles on Candles v2 first", ...}` with HTTP 200.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_v2_routes.py
"""The v2 routes answer from the v2 store and say so when it is empty."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tradingagents import api as api_mod, rows_index as ri, stores
from tests.test_v2_store_is_its_own_folder import _row, _seed


@pytest.fixture
def client(tmp_path, monkeypatch):
    v2 = stores.Store(name="v2", home=tmp_path / "v2", candles=tmp_path / "v2" / "candles",
                      rows_db=tmp_path / "v2" / "rows.db", parquet=tmp_path / "parquet-v2",
                      fine_tf="1m", download_kind="download_v2", backtest_kind="backtest_v2")
    monkeypatch.setattr(stores, "V2", v2)
    monkeypatch.setitem(stores._BY_NAME, "v2", v2)
    return TestClient(api_mod.app), v2


def test_an_empty_v2_store_is_a_sentence_not_a_500(client):
    c, _ = client
    r = c.get("/api/v2/strategies")
    assert r.status_code == 200
    d = r.json()
    assert d["rows"] == [] and d["total"] == 0
    assert "download 1m candles on Candles v2 first" in d["why"]
    assert c.get("/api/v2/candles/gaps").status_code == 200
    assert c.get("/api/v2/backtest/storage").status_code == 200


def test_v2_strategies_come_from_the_v2_db_and_carry_unclear(client):
    c, v2 = client
    v2.rows_db.parent.mkdir(parents=True, exist_ok=True)
    _seed(v2.rows_db, [_row("XPIN", 99.0, unclear=1, res="1m")])
    d = c.get("/api/v2/strategies?coin=XPIN").json()
    assert d["total"] == 1 and d["rows"][0]["unclear"] == 1 and d["rows"][0]["res"] == "1m"
    assert d["store"] == "v2"


def test_the_v1_route_never_sees_a_v2_row(client, tmp_path, monkeypatch):
    c, v2 = client
    v2.rows_db.parent.mkdir(parents=True, exist_ok=True)
    _seed(v2.rows_db, [_row("XPIN", 99.0, unclear=1, res="1m")])
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "v1.db")
    _seed(tmp_path / "v1.db", [_row("XPIN", 10.0)])
    d = c.get("/api/strategies?coin=XPIN").json()
    assert d["total"] == 1 and d["rows"][0]["profit"] == 10.0


def test_v2_download_history_reads_the_v2_job_kind(client, monkeypatch):
    c, _ = client
    from tradingagents import notifications as nt
    seen = {}
    monkeypatch.setattr(nt, "recent", lambda limit=20, kind=None, **k: seen.setdefault("kind", kind) and [] or [])
    c.get("/api/v2/candles/download-history")
    assert seen["kind"] == "download_v2"


def test_the_v2_job_kinds_are_known_to_the_jobs_routes(client):
    c, _ = client
    assert c.get("/api/jobs/download_v2").status_code == 200
    assert c.get("/api/jobs/backtest_v2").status_code == 200
```

- [ ] **Step 2: Run to verify they fail**

Expected: 404 on `/api/v2/...`.

- [ ] **Step 3: Refactor each v1 handler into a shared function + two routes**

Pattern (apply to each route named in Interfaces). For strategies:

```python
def _strategies_impl(store, coin, tf, signal, profitable, limit, offset, sort,
                     min_trades, min_winrate, max_tp, max_sl, min_tp, min_sl,
                     tp_over_sl, asset, sizing, row_id, group, months, days,
                     measured_days, desc) -> dict:
    from tradingagents import rows_index as ri

    db = None if store.name == "v1" else store.rows_db
    if db is not None and not Path(db).exists():
        # AN EMPTY PAGE NAMES WHAT IT EXAMINED (CLAUDE.md, Sep 12, 2026)
        return {"rows": [], "total": 0, "store": store.name,
                "why": "no v2 store yet — download 1m candles on Candles v2 "
                       "first, then press BACKTEST on Backtest v2"}
    ... the existing body, with every `ri.query(...)` / `ri.status()` /
    `iter_rows(...)` given `db_path=db`, and `got["store"] = store.name` ...


@app.get("/api/strategies")
def strategies(coin: str | None = None, ...same params...) -> dict:
    return _strategies_impl(stores.V1, coin, tf, ...)


@app.get("/api/v2/strategies")
def strategies_v2(coin: str | None = None, ...same params...) -> dict:
    return _strategies_impl(stores.V2, coin, tf, ...)
```

Do the same for `strategies.csv` (`export_plan`/`iter_rows` get `db_path`), `facets` (`ri.facets(db_path=...)`), `backtest/storage` (`ri.pair_storage(db_path=...)`), `candles/gaps` (`msw.candle_index(scan=False, root=store.candles)`; the warm thread `_warm_gap_index(root)` keyed per store in `_GAP_CACHE[store.name]`), `candles/pending` (`db_jobs.pending_work(files_key=store.download_kind, root=store.candles, tfs=store.tfs)` — add those three params to `pending_work`/`_pending_sources`, defaults = today's), `candles/completeness` (`_store_completeness(store)`: `wanted = [(sym, tf) for sym in contracts for tf in store.tfs]`, `have` from `store.parquet / "candles"`; cache keyed by store name), `candles/lost` (`FILES[store.download_kind]["lost"]`), `candles/download-history` (`nt.recent(limit, kind=store.download_kind)`).

Add `from tradingagents import stores` near the top of `api.py`. Every v1 route keeps its exact signature and behaviour.

- [ ] **Step 4: Run**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_routes.py tests/test_candles_lost_route.py tests/test_download_history_tabs.py tests/test_empty_page_is_not_an_empty_store.py -q 2>&1 | tail -4`
Expected: green (besides the pre-existing `test_api_trade` failure, which is not in this set).

- [ ] **Step 5: Commit ONLY your api.py hunks** (blob recipe: `git show HEAD:tradingagents/api.py`, apply the same edits to that copy with a script that replaces the exact route bodies, `py_compile`, `hash-object`, `update-index`) and push.

```bash
git add tests/test_v2_routes.py tradingagents/db_jobs.py
git commit -F - <<'MSG'
feat(v2): /api/v2 routes serve the v2 store from the same handlers

Strategies, CSV, facets, candle gaps/pending/completeness/lost/history and
the backtest store each became one implementation parameterised by a
`stores.Store`, with the v1 route passing V1 unchanged. An empty v2 store
answers a sentence ("download 1m candles on Candles v2 first"), never a 500.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
MSG
git push origin main
```

---

### Task 7: Web client — `storeApi("v2")` and the `unclear` field

**Files:**
- Modify: `webapp/src/lib/api.ts` (helpers at 55-100; `api.candle*` 645-680; `strategies` 880-915; `jobStart` 971; `backtestApi` 1579; `StrategyRow` type)

**Interfaces:**
- Produces: `export type StoreName = "v1" | "v2"`; `export function storeApi(store: StoreName)` returning an object with the SAME method names the panels call today (`candlePending, candleGaps, candleLost, candleCompleteness, strategies, strategiesCsvUrl, facets, jobStatus, jobStart, jobStop, storage, downloadHistory`) but prefixed `/api/v2` and using kinds `download_v2`/`backtest_v2` when `store === "v2"`; `storeApi("v1")` delegates to the existing `api`/`backtestApi`/`notifyApi` functions so v1 panels are untouched. `StrategyRow` gains `unclear?: number | null; res?: string | null`. `jobStart`'s kind union gains `"download_v2" | "backtest_v2"`.

- [ ] **Step 1: Add the helper** (at the end of `api.ts`, before any default export)

```ts
/** Which store a panel reads: v1 (the year-deep grid) or v2 (Backtest v2,
 *  minute-exact exits on 1-minute candles, Sep 17, 2026). The v2 methods
 *  are the v1 methods under `/api/v2` with the v2 job kinds; v1 delegates
 *  to the existing functions so nothing a v1 panel calls changes. */
export type StoreName = "v1" | "v2";

export function storeApi(store: StoreName) {
  const P = store === "v2" ? "/api/v2" : "/api";
  const dl = store === "v2" ? "download_v2" : "download";
  const bt = store === "v2" ? "backtest_v2" : "backtest";
  return {
    store, downloadKind: dl as "download" | "download_v2",
    backtestKind: bt as "backtest" | "backtest_v2",
    /** the frames THIS store downloads — v2 is 1m and nothing else */
    tfs: store === "v2" ? ["1m"] : ["15m", "30m", "1h", "4h", "1d"],
    candlePending: () => get<CandlePending>(`${P}/candles/pending`),
    candleGaps: () => get<Awaited<ReturnType<typeof api.candleGaps>>>(`${P}/candles/gaps`),
    candleLost: () => get<Awaited<ReturnType<typeof api.candleLost>>>(`${P}/candles/lost`),
    candleCompleteness: () => get<Awaited<ReturnType<typeof api.candleCompleteness>>>(`${P}/candles/completeness`),
    downloadHistory: (limit = 20) => get<DownloadHistory>(`${P}/candles/download-history?limit=${limit}`),
    strategies: (q: Parameters<typeof api.strategies>[0]) =>
      store === "v2"
        ? get<Awaited<ReturnType<typeof api.strategies>>>(`${P}/strategies?${strategiesQuery(q)}`)
        : api.strategies(q),
    strategiesCsvUrl: (q: Parameters<typeof api.strategiesCsvUrl>[0]) =>
      store === "v2" ? `${API_BASE}${P}/strategies.csv?${strategiesQuery(q)}` : api.strategiesCsvUrl(q),
    facets: () => get<Awaited<ReturnType<typeof api.facets>>>(`${P}/strategies/facets`),
    storage: () => get<BtStorage>(`${P}/backtest/storage`),
    jobStatus: (kind: "download" | "backtest") =>
      api.jobStatus(kind === "download" ? dl : bt),
    jobStart: (kind: "download" | "backtest", spec: unknown) =>
      api.jobStart(kind === "download" ? dl : bt, spec),
    jobStop: (kind: "download" | "backtest") =>
      api.jobStop(kind === "download" ? dl : bt),
  };
}
```

`strategiesQuery(q)` must be extracted from the existing `api.strategies` body: the block that builds `const p = new URLSearchParams()` becomes `function strategiesQuery(q): string { ...; return p.toString(); }` and `api.strategies` / `api.strategiesCsvUrl` call it — behaviour unchanged.

- [ ] **Step 2: Types** — in `StrategyRow` add `unclear?: number | null; res?: string | null;`. Extend `jobStart`'s kind union and `jobStatus`/`jobStop` kind types with `"download_v2" | "backtest_v2"`.

- [ ] **Step 3: Typecheck**

Run: `cd webapp && npx tsc --noEmit -p tsconfig.json`
Expected: no output.

- [ ] **Step 4: Commit and push**

```bash
git add webapp/src/lib/api.ts
git commit -F - <<'MSG'
feat(v2): storeApi("v2") — the v1 client under /api/v2 with the v2 job kinds

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
MSG
git push origin main
```

---

### Task 8: Candles v2 tab

**Files:**
- Create: `webapp/src/components/StoreBadge.tsx`, `webapp/src/app/(admin)/candles-v2/page.tsx`
- Modify: `webapp/src/components/candles/DownloadScreen.tsx`, `webapp/src/components/candles/DownloadHistory.tsx` (`store` prop → `storeApi`), `webapp/src/layout/AppSidebar.tsx`

**Interfaces:**
- Produces: `<DownloadScreen store="v2" />` — timeframes fixed to `["1m"]` (picker hidden), the completeness line says `× 1 timeframe (1m)`, heading carries `<StoreBadge store="v2" />`, DOWNLOAD/UPDATE/RESOLVE/RETRY start `download_v2`, progress polls `download_v2`, history reads the v2 kind; `MonthsPanel` and `StoragePanel` are not rendered for v2 (they read the v1 parquet store).
- Route `/candles-v2`; sidebar item **Candles v2** with `DownloadIcon`.

- [ ] **Step 1: `StoreBadge.tsx`**

```tsx
"use client";
/** Which store a screen is showing. On the v2 screens only — a v1 screen with
 *  no badge is the screen the operator has always had, byte for byte. */
import type { StoreName } from "@/lib/api";

export default function StoreBadge({ store }: { store: StoreName }) {
  if (store !== "v2") return null;
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-600 dark:bg-brand-500/10"
          title="Backtest v2: the same signals on the same timeframes, but every win/lose price is checked minute by minute on 1-minute candles, so a candle that touched both prices is no longer a guess">
      v2 · minute-exact exits
    </span>
  );
}
```

- [ ] **Step 2: `DownloadScreen` takes `store`**

Signature: `export default function DownloadScreen({ store = "v1" }: { store?: StoreName })`. Inside: `const S = useMemo(() => storeApi(store), [store]);` and replace `api.candleGaps/candleLost/candleCompleteness/candlePending` with `S.*`, `api.jobStatus("download")` → `S.jobStatus("download")`, every `api.jobStart("download", ...)` → `S.jobStart("download", ...)`. `const [tfs, setTfs] = useState<string[]>(store === "v2" ? ["1m"] : ["15m","30m","1h","4h"])`; the timeframe picker `TFS.map(...)` renders only when `store === "v1"`; for v2 print `<p>1-minute candles only — the finest MEXC sells (30 days at a time; every UPDATE extends the history)</p>` in its place. Heading: `Download candles <StoreBadge store={store} />`. Completeness line: `× ${S.tfs.length} timeframe${S.tfs.length === 1 ? ` (${S.tfs[0]})` : "s"}` in place of the literal `× 5 timeframes`. Bottom: `{store === "v1" && <MonthsPanel />}{store === "v1" && <StoragePanel />}`. `DownloadHistory` gets `store` and calls `S.downloadHistory`, `S.candleLost`, etc.

- [ ] **Step 3: Route and sidebar**

```tsx
// webapp/src/app/(admin)/candles-v2/page.tsx
import type { Metadata } from "next";
import DownloadScreen from "@/components/candles/DownloadScreen";

export const metadata: Metadata = {
  title: "Candles v2 | Trading Agents",
  description: "1-minute candles for Backtest v2 — downloaded and extended on this PC",
};

export default function CandlesV2Page() {
  return <DownloadScreen store="v2" />;
}
```

Sidebar: after the `Candles` item add `{ icon: <DownloadIcon />, name: "Candles v2", path: "/candles-v2" }`.

- [ ] **Step 4: Typecheck, build, restart UI, verify in a real browser**

```bash
cd webapp && npx tsc --noEmit -p tsconfig.json && npm run build 2>&1 | tail -3
cd /g/analyzer-x && .venv/Scripts/python.exe -c "import start; start.free_port(8503, tree=True)"
cd webapp && nohup npx next start -p 8503 > /g/analyzer-x/.run/ui.log 2>&1 &
```

Playwright (scratchpad `pw/candles_v2.mjs`, `CHROME_EXE` env): open `http://localhost:8503/candles-v2`; assert the badge text `v2 · minute-exact exits` is present, the body contains `1-minute candles only`, no `15m` checkbox exists, and `/candles` still shows the five checkboxes and no badge. Screenshot both.

- [ ] **Step 5: Commit and push**

```bash
git add webapp/src/components/StoreBadge.tsx "webapp/src/app/(admin)/candles-v2/page.tsx" webapp/src/components/candles/DownloadScreen.tsx webapp/src/components/candles/DownloadHistory.tsx webapp/src/layout/AppSidebar.tsx
git commit -F - <<'MSG'
feat(ui): Candles v2 tab — 1-minute candles, downloaded and extended in the v2 store

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
MSG
git push origin main
```

---

### Task 9: Backtest v2 tab

**Files:**
- Create: `webapp/src/app/(admin)/backtest-v2/page.tsx`
- Modify: `webapp/src/components/backtest/JobsPanel.tsx`, `StrategiesPanel.tsx`, `BacktestStorage.tsx`, `webapp/src/layout/AppSidebar.tsx`

**Interfaces:**
- `<JobsPanel store="v2" />`: BACKTEST starts `backtest_v2` with `{coins, tfs, days, base, label: "react", deployed, fresh: true}`; UPDATE (`btupdate`) and RUN ON GITHUB and RESOLVE PENDING are not rendered for v2 (cloud has no 1m store; update comes later). Heading `Backtest <StoreBadge/>`; the copy says *"exits settled minute by minute on the 1-minute candles from Candles v2"* and links to `/candles-v2`.
- `<StrategiesPanel store="v2" />`: reads `S.strategies/facets/strategiesCsvUrl`; a column `unclear` right after `losses` (header title: *"trades where one minute touched both prices — booked as a loss"*); the empty state prints the route's `why`.
- `<BacktestStorage store="v2" />`: reads `S.storage`.
- Route `/backtest-v2`; sidebar **Backtest v2** with `TableIcon`.

- [ ] **Step 1: Props and API swap** in the three panels (`const S = useMemo(() => storeApi(store), [store])`, replace the listed `api.*` calls; `JobsPanel` polls `S.jobStatus("backtest")` and starts `S.jobStart("backtest", spec)`; hide the cloud/update blocks with `store === "v1" &&`).
- [ ] **Step 2: `unclear` column** in `StrategiesPanel`'s header list and row render, after `losses`; value `r.unclear ?? "—"`. Keep the CSV button — the v2 CSV route carries the column via `COLS`.
- [ ] **Step 3: Page + sidebar**

```tsx
// webapp/src/app/(admin)/backtest-v2/page.tsx
import type { Metadata } from "next";
import StrategiesPanel from "@/components/backtest/StrategiesPanel";
import JobsPanel from "@/components/backtest/JobsPanel";
import BacktestStorage from "@/components/backtest/BacktestStorage";

export const metadata: Metadata = {
  title: "Backtest v2 | TradingAgents",
  description: "Same signals, minute-exact exits — measured on this PC from the 1-minute candle store",
};

export default function BacktestV2Page() {
  return (
    <div className="flex flex-col gap-5">
      <JobsPanel store="v2" />
      <StrategiesPanel store="v2" />
      <BacktestStorage store="v2" />
    </div>
  );
}
```

- [ ] **Step 4: Typecheck, build, restart, Playwright** — `/backtest-v2` shows the badge, the `unclear` header, no RUN ON GITHUB button; `/backtest` unchanged (no badge, no `unclear`, RUN ON GITHUB present). Run `tests/test_both_books_on_a_deployed_row.py` and every `tests/test_*panel*.py` / `tests/test_empty_page_is_not_an_empty_store.py` — they grep the v1 components; keep them green.
- [ ] **Step 5: Commit and push** (`feat(ui): Backtest v2 tab — same rows, minute-exact exits, an unclear column`).

---

### Task 10: Press and watch — a real v2 run end to end

**Files:** none new (scratchpad scripts only), `docs/RCA.md` if anything breaks.

- [ ] **Step 1: PREDICT** — write down: the download will page 22 requests per coin; `refresh_candles(days=365)` keeps 395 days so nothing is cut; `bars_from_1m` may refuse coins with a missing minute (name them); a v1 job running would block (check `/api/jobs` first).
- [ ] **Step 2: PRESS** — on `/candles-v2` pick `XPIN_USDT, ARKM_USDT, LYN_USDT, GLM_USDT, JELLYJELLY_USDT` and DOWNLOAD (or `POST /api/jobs/download_v2/start {"coins": [...], "tfs": ["1m"]}` exactly as the button sends it).
- [ ] **Step 3: WATCH** — until `running:false`; read `~/.tradingagents/db_download_v2.log`; confirm 5 files under `~/.tradingagents/v2/candles/*-1m.json` with ~44,000 bars each and parquet copies under `~/.tradingagents/parquet-v2/candles/`; confirm NOTHING new under `~/.tradingagents/backtest/candles/`.
- [ ] **Step 4: PRESS** — on `/backtest-v2` BACKTEST those 5 coins on `1h` for 30 days.
- [ ] **Step 5: WATCH** — progress; then `GET /api/v2/strategies?coin=XPIN&tf=1h&signal=ote` → find the row with `sl=3, tp=1, sizing=flat`; its id must differ from `LG9NSU4B`; open its trade log (`POST /api/v2/strategies/trades` if the route exists for v2 — otherwise via `run_pair`'s log in a script) and confirm the Sep 16 trade's exit time prints `Sep 16, 2026 7:28am`; confirm `unclear` is an integer and `/api/strategies?row_id=LG9NSU4B` still answers the v1 row unchanged.
- [ ] **Step 6: FIX** anything with harddev; RCA entry in the same commit as a fix.
- [ ] **Step 7: REPORT** — the press-and-watch table (before / after / runs / what broke / what changed / what is still not right), in plain words, one line each.

---

### Task 11: Rules and the done line

**Files:**
- Modify: `CLAUDE.md` — new MANDATORY section
- Modify: `docs/superpowers/specs/2026-09-17-v2-minute-exact-design.md` — record what shipped (no `fast_grid.walk(fine=)` in this cut; `unclear` lives in ONE schema via ADD COLUMN)

- [ ] **Step 1: CLAUDE.md section** — *"## Backtest v2 is the v1 engine in its own folder (MANDATORY — 2026-09-17)"*: the four rules — v2 never measures ON 1m bars (it rebuilds the five frames; 666/666 proof); `fine=None` is byte-identical and tested; `"1m"` stays out of every five-frame list; v2 rows carry `res="1m"` and their own ids, and the v1 file is never rewritten for them. Name the guard tests.
- [ ] **Step 2: Commit, push, speak**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-09-17-v2-minute-exact-design.md
git commit -F - <<'MSG'
docs(v2): the rules Backtest v2 rests on, and what the first cut shipped

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
MSG
git push origin main
bash .claude/skills/say-done/speak.sh "candles v2 and backtest v2 are in" &
```

---

## Self-review

**Spec coverage:** stores (T4), TFS entry (T1), bars_from_1m + refusal (T1, T3), engine `fine` incl. same-minute/unclear/funding-to-the-minute/fallback (T2), row identity (T3), `unclear` column (T3 — as ADD COLUMN in one schema, superseding the spec's "v2 db only" line; T11 records it), jobs + env + whitelist + update tfs + supervisor (T4), API read side (T5, T6), screens (T8, T9), failure paths (T3 refusals, T6 empty sentence, T4 one-job-at-a-time is the existing `status()`/`start()` guard — a v2 start while a v1 download runs returns the v1 pid? **No**: `start()` checks only its own kind. Add to T4 step 5: in `start()`, before spawning a `_v2` kind, refuse with `raise LocalSweepsOff(...)`-style error `JobBusy("a <kind> job is running — one job at a time, both versions")` if any other kind in FILES reports `running`, and the same for a v1 kind when a v2 kind runs; test it in T4.) Measured costs are documentation. Playwright checks (T8, T9). Deploy-from-v2-id and cloud: out of cut, stated.

**Placeholder scan:** T6 step 3 describes the refactor pattern with one full example and names every route and the exact parameter each needs — acceptable; T9 step 1-2 are edits to files read in this session, described by exact call names. No "TBD".

**Type consistency:** `storeApi(store).jobStatus("download"|"backtest")` maps to kinds; `stores.Store.tfs`; `market_sweep.FINE_TF`, `MINUTES_PER_BAR`, `bars_from_1m`; `backtest_strategy(fine=)` result key `unclear`, log key `exit_minute_ms`; `rows_index.COLS` includes `unclear`, `res`; `row_code(res=)`; `_download_tfs(spec, kind)`; `update_pairs(lost, tfs=)`; `candle_index(root=)`; `pending_work(files_key, root, tfs)`. Consistent across tasks.
