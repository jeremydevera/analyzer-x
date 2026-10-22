# Confluence Research, Phase A (Prompt 1: blocks, search, machines, pilot) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run Prompt 1's search — for every Gate coin and timeframe, the confluence entry and stop/target that win most often in the worst case at 2:1R or better after fees — starting with the 20-coin pilot and its first check (real picks against random picks, before fees, on test days the search never read).

**Architecture:** `tradingagents/signals_cq.py` holds the building blocks and names (`cq_`), routed in `auto_trader` exactly like `pt_`. `tradingagents/cq_core.py` is the pure search (rounds, Wilson scores, payouts, picks). `.github/scripts/cq_shard.py` runs the search on GitHub through the nightly grid's own engine (`sweep_shard.run_pair` -> `backtest_strategy`) with `.github/workflows/cq.yml`; `tradingagents/cq_search.py` deals the board over every account and collects; `tradingagents/cq_report.py` reads the results and makes the first check.

**Tech Stack:** Python 3.12/3.13, numpy, pandas, GitHub Actions, the `gh` CLI.

**Spec:** `docs/superpowers/specs/2026-10-21-confluence-research-design.md` (the prompts: `research/cq/prompts.md`).

## Global Constraints

- Prefix `cq_`; module `tradingagents/signals_cq.py`; routed in `auto_trader.signal_for` and `_dirs_for_backtest` exactly like `pt_`; an unknown `cq_` name abstains.
- Every indicator fixed-window (`pro_indicators`; the EMA a fixed weighted sum, never a recursion); the runner's 299 closed candles decide what the deep window decides.
- Name grammar `cq_<trigger code>[-<confirmation code>[-<confirmation code>]]`, a dash between parts, confirmations sorted, every part from a different family.
- Windows (days): 15m/30m/1h history 365, tuning 185, check 60, test 120; 4h 730/370/120/240; 1d 1,095/550/180/365; 300 candles of lead-in.
- Payout classes at the coin's usual round trip: 2:1 (2-3), 3:1 (3-4), 4:1 (4-5), 5:1 (5+); below 2:1 never a candidate; stop 2% or less, inside 80% of liquidation.
- Score: Wilson lower bound z 1.645 of the tuning days' win rate; up to 100 rounds of up to 500; patience 10; top 25 spread over payouts; 20% fresh draws; never a candidate twice; the seed a hash of coin, timeframe and search version.
- The test days are never read by the search or the choice.
- Entry rules on every candidate: no entry within 30 minutes of a US CPI, FOMC or jobs release (`research/cq/us_news.json`); no quiet weekend entry (UTC, volume under the 20-candle average).
- Every exit settled by the minute over the whole window; the per-minute order book for the newest ~45 days, older trades pay the usual cost (`cost_unmeasured`).
- `cq.yml` on EVERY account (`forecast_v2_daily.fleets_now`, three since Oct 21, 2026), at most 10 inputs, `TA_VENUE: gate`, timeout 350 minutes; never dispatched 12:45am-5:00am.
- Results on G: under `stores.V1.home / "cq"`, never the system drive; dates printed with `fmt_when`.
- Nothing is switched on, filed into Stored strategies or added to the nightly grid.
- Commit with `python scripts/commit_own.py -F <msg> <paths>`; push to `origin`, `colleague` and `teammate`; one full test suite at a time on this PC.

## Review Focus

1. A coin younger than its window: the tuning days shrink; below 30 tuning days the pair is skipped with why, never searched on nothing (test: `test_a_coin_too_young_for_its_windows_is_skipped_and_says_why`, Task 5).
2. A month of minutes missing from Gate's archive: the candle settles by the candle's own rule, never a crash (the shard test runs with no minutes at all, Task 5).
3. A machine killed at 6 hours: results rewritten after every coin; a search past its deadline stops between rounds and keeps its picks (test: `test_a_deadline_stops_between_rounds`, Task 4).
4. Stock tokens: New York's session only, and the closed-market rule applies through run_pair (test: `test_stock_tokens_trade_new_yorks_session_and_4h_1d_have_no_session_break`, Task 2).
5. A first check with too few coins (young coins, no picks, thin picks): not evidence, and not evidence is a STOP; a coin's timeframes count once (tests: `test_too_few_pairs_is_not_evidence_and_not_evidence_is_a_stop`, `test_a_coins_timeframes_count_once`, Task 8).

---

### Task 1: The fixed-window EMA

**Files:**
- Modify: `tradingagents/pro_indicators.py` (append `ema_fixed`)
- Test: `tests/test_pro_indicators.py` (two CASES entries, one test)

**Interfaces:**
- Produces: `pro_indicators.ema_fixed(x, n: int, window: int | None = None) -> np.ndarray` (NaN until the window fills).

- [ ] **Step 1: Write the failing test** — add to `CASES` in `tests/test_pro_indicators.py`:

```python
    "ema_fixed_9": lambda o, h, lo, c, v: pi.ema_fixed(c, 9),
    "ema_fixed_50": lambda o, h, lo, c, v: pi.ema_fixed(c, 50),
```

and append:

```python
def test_the_fixed_ema_is_an_ema():
    """Weights 2/(n+1) over a fixed window: on a long series it reads what the
    recursive EMA reads, to within its truncated tail."""
    import pandas as pd

    _o, _h, _lo, c, _v = _ohlcv(n=1000, seed=9)
    for n in (9, 21, 50):
        got = pi.ema_fixed(c, n)
        ref = pd.Series(c).ewm(span=n, adjust=False).mean().to_numpy()
        w = min(pi.MAX_LOOKBACK, 10 * n)
        assert np.isnan(got[w - 2]) and not np.isnan(got[w - 1])
        assert np.max(np.abs(got[400:] - ref[400:]) / ref[400:]) < 1e-3
```

- [ ] **Step 2: Run it** — `.venv/Scripts/python -m pytest tests/test_pro_indicators.py -q` — Expected: FAIL, `AttributeError: module 'tradingagents.pro_indicators' has no attribute 'ema_fixed'`.

- [ ] **Step 3: Implement** — append to `tradingagents/pro_indicators.py`:

```python
def ema_fixed(x, n: int, window: int | None = None) -> np.ndarray:
    """The exponential average with weight 2/(n+1) as a FIXED-WINDOW sum: the
    last `window` values (default min(MAX_LOOKBACK, 10 x n)), weights
    normalised to 1. The recursion every chart uses depends on where its
    history starts; this reads the same bars from any frame, so the runner's
    299 candles and the backtest's year agree to the last bit (the weight
    beyond 10 x n is 2e-9 of the whole for n 9, 4.5e-5 for n 50). Elementwise
    multiply and a row sum, never a matrix product: BLAS blocks a product by
    the matrix's size, so two frames could round differently."""
    w = int(window or min(MAX_LOOKBACK, 10 * int(n)))
    win, a = _windows(x, w)
    out = np.full(len(a), np.nan)
    if win is None:
        return out
    alpha = 2.0 / (int(n) + 1.0)
    wts = alpha * (1.0 - alpha) ** np.arange(w - 1, -1, -1, dtype=float)
    out[w - 1:] = (win * (wts / wts.sum())).sum(axis=1)
    return out
```

- [ ] **Step 4: Run it** — same command — Expected: PASS (the parity and no-future tests now also cover both EMAs).
- [ ] **Step 5: Commit** — `python scripts/commit_own.py -F <msg> tradingagents/pro_indicators.py tests/test_pro_indicators.py`, push to the three remotes.

### Task 2: The building blocks and names (`signals_cq`) and the news calendar

**Files:**
- Create: `tradingagents/signals_cq.py`, `tests/test_cq_signals.py`
- Modify: `research/cq/us_news.json` (add `"from": "2023-10-01"` and `"through": "2026-12-31"`)

**Interfaces:**
- Consumes: `pro_indicators.ema_fixed` (Task 1), `signals_pro._ctx/_edge/_LOCK/_FRAMES`, `signals_conf.CONF_SIGNALS`.
- Produces: `spec_for(key) -> dict | None` (`name`, `trigger`, `confirms`, `settings`); `dirs_for(spec, o, h, lo, c, v, ts, funding=None) -> list[int]`; `name_of(trigger, confirms=()) -> str`; `code_of(block, digits) -> str`; `entries_for(tf, kind) -> list[str]`; `random_entries(n_seeds=560) -> list[str]`; `neighbours(name, pool) -> list[str]`; `words(name) -> str`; `families(name) -> list`; `entry_allowed(o, h, lo, c, v, ts) -> np.ndarray`; `part_dirs(code, ...)`; `news_times()`; `reset()`; constants `VERSION`, `EXISTING`, `BLOCKS`, `TRIGGER_ORDER`, `CONFIRM_ORDER`, `NEWS_PATH`, `NY`.

- [ ] **Step 1: Write the failing tests** — `tests/test_cq_signals.py` (the routing tests at its end fail until Task 3):

```python
"""The confluence research's building blocks (tradingagents/signals_cq.py),
Oct 21, 2026. Every block and setting is covered:
* a name parses back to exactly its parts, and every other spelling - a part
  twice, two parts of one family, a confirmation alone, an unsorted order -
  is not a name (one combination, one name);
* no candle's decision changes when later candles arrive (cut frames);
* the runner's 299 closed candles decide what the deep window decides;
* the two entry rules refuse exactly the candles they name, and a missing
  calendar refuses every entry;
* the search's space holds only legal combinations; stock tokens trade New
  York's session only; 4h and 1d have no session break;
* the runner and the backtest read one implementation (auto_trader)."""
from __future__ import annotations

import datetime as _dt
import json

import numpy as np
import pytest

from tests.test_pro_strategies import _frame
from tradingagents import signals_cq as sq

DAY = 86_400_000
MON_AUG_31 = 1_788_048_000_000 + DAY       # Mon Aug 31, 2026 00:00 UTC


def _names():
    """Every trigger setting with a confirmation it may take, every
    confirmation setting under a trigger of another family, three pairs of
    confirmations, two existing setups and two random streams."""
    conf = [(b, d) for b in sq.CONFIRM_ORDER for d in sq._digits(b)]
    trig = [(b, d) for b in sq.TRIGGER_ORDER for d in sq._digits(b)]
    out = []
    for t in trig:
        x = next(c for c in conf if sq.BLOCKS[c[0]]["family"] != sq.BLOCKS[t[0]]["family"])
        out.append(sq.name_of(t, [x]))
    for c in conf:
        t = next(t for t in trig if sq.BLOCKS[t[0]]["family"] != sq.BLOCKS[c[0]]["family"])
        out.append(sq.name_of(t, [c]))
    out += ["cq_fl00-ev-vs1", "cq_sb01-rs1-vo0", "cq_sq0-ht1-kp0"]
    out += [sq.name_of(("ex", (sq.EXISTING.index(r),))) for r in ("cf_mom", "cx_maj3")]
    out += ["cq_rn00070", "cq_rn01231"]
    return sorted(set(out))


NAMES = _names()


def _dirs(name, fr):
    return sq.dirs_for(sq.spec_for(name), *fr)


@pytest.mark.parametrize("name", NAMES)
def test_no_candle_reads_the_future(name):
    fr = _frame()
    full = _dirs(name, fr)
    assert len(full) == len(fr[3])
    for cut in range(300, len(fr[3]) + 1, 137):
        part = _dirs(name, tuple(x[:cut] for x in fr))
        assert part == full[:cut], (name, cut, [k for k in range(cut) if part[k] != full[k]][:5])


@pytest.mark.parametrize("name", NAMES)
def test_the_runners_299_candles_decide_what_the_backtest_decides(name):
    fr = _frame(n=2400, seed=3)
    full = _dirs(name, fr)
    for end in (700, 1333, 1999, 2400):
        tail = tuple(x[end - 299:end] for x in fr)
        assert _dirs(name, tail)[-1] == full[end - 1], (name, end)


def test_every_name_of_the_space_parses_back_and_is_its_only_spelling():
    for tf, kind in (("15m", "crypto"), ("1h", "stocks"), ("4h", "crypto"), ("1d", "metals")):
        for name in sq.entries_for(tf, kind):
            spec = sq.spec_for(name)
            assert spec is not None and spec["name"] == name, name
            assert sq.spec_for(name + "_gh_" + tf)["name"] == name


@pytest.mark.parametrize("bad", [
    "cq_ev", "cq_fl00", "cq_fl00-ht0-ev", "cq_fl00-ev-ev", "cq_ec0-ev", "cq_fl00-kp0",
    "cq_fl0-ev", "cq_fl20-ev", "cq_rn0007", "cq_rn00070-ev", "cq_ex99", "cq_zz0-ev",
    "pt_brk_n0g0c0", "", "cq_fl00-ev-vs1-rs0"])
def test_a_name_that_is_not_ours_is_none(bad):
    assert sq.spec_for(bad) is None


def test_the_space_holds_only_legal_combinations():
    e15 = sq.entries_for("15m", "crypto")
    assert len(e15) == len(set(e15))
    combos = [n for n in e15 if not n.startswith("cq_ex")]
    assert len(combos) == 1116           # 18 trigger settings, parts of different families
    from tradingagents.signals_conf import CONF_SIGNALS

    runnable = [r for r in sq.EXISTING if not getattr(CONF_SIGNALS[r], "needs_funding", False)]
    assert sum(n.startswith("cq_ex") for n in e15) == len(runnable) == 52
    for n in combos:
        fams = sq.families(n)
        assert len(set(fams)) == len(fams) and 2 <= len(fams) <= 3, n


def test_stock_tokens_trade_new_yorks_session_and_4h_1d_have_no_session_break():
    for n in sq.entries_for("15m", "stocks"):
        spec = sq.spec_for(n)
        for b, d in [spec["trigger"], *spec["confirms"]]:
            if b in ("sb", "vs"):
                assert sq._settings(b, d)["session"] == "ny", n
    for tf in ("4h", "1d"):
        e = sq.entries_for(tf, "crypto")
        assert not any(n.startswith("cq_sb") for n in e)
        assert not any("-vs1" in n for n in e)          # one rolling VWAP: vs0 only


def test_neighbours_are_one_step_away_and_inside_the_space():
    pool = set(sq.entries_for("1h", "crypto"))
    name = "cq_fl00-ev-vs1"
    nb = sq.neighbours(name, pool)
    assert nb and all(x in pool and x != name for x in nb)
    assert {"cq_fl10-ev-vs1", "cq_fl01-ev-vs1", "cq_fl00-ev-vs0"} <= set(nb)   # one setting
    assert {"cq_fl00-ev", "cq_fl00-vs1"} <= set(nb)                           # one dropped
    assert "cq_fl00-ev-vo0" in nb and "cq_fl00-ht0-vs1" in nb                 # one swapped
    assert "cq_ec0-rs0-vo1" in sq.neighbours("cq_ec0-vo1", pool)              # one added
    assert sq.neighbours("cq_rn00070", set(sq.random_entries())) == \
        ["cq_rn00060", "cq_rn00080", "cq_rn00071"]
    mom = sq.name_of(("ex", (sq.EXISTING.index("cf_mom"),)))
    assert sorted(sq.EXISTING[sq.spec_for(x)["trigger"][1][0]]
                  for x in sq.neighbours(mom, pool)) == ["cf_mom_l1", "cf_mom_l2"]


def _day():
    """Mon Aug 31, 2026 (UTC), 96 candles of 15m: a flat first hour whose high
    is 100.8, a close above it inside the first hour (no entry), then two
    breaks after it."""
    c = [100.0] * 96
    h = [100.5] * 96
    lo = [99.5] * 96
    c[3], h[3] = 100.7, 100.8
    c[4], h[4], lo[4] = 100.4, 100.45, 100.0
    c[5], h[5], lo[5] = 101.0, 101.1, 100.4
    c[6], h[6], lo[6] = 100.2, 100.6, 100.1
    c[7], h[7], lo[7] = 102.0, 102.1, 100.2
    for i in range(8, 96):
        c[i], h[i], lo[i] = 101.5, 101.6, 101.4
    o = [100.0] + c[:-1]
    ts = [MON_AUG_31 + i * 900_000 for i in range(96)]
    return o, h, lo, c, [1000.0] * 96, ts


def test_the_session_break_waits_for_the_first_hour_and_first_means_first():
    fr = _day()
    first = list(sq.part_dirs("sb00", *fr))
    every = list(sq.part_dirs("sb01", *fr))
    assert [i for i, x in enumerate(first) if x] == [5]
    assert [i for i, x in enumerate(every) if x] == [5, 7]
    assert first[5] == every[5] == every[7] == 1


def test_no_entry_from_30_minutes_before_to_30_minutes_after_a_us_release():
    ev = json.loads(sq.NEWS_PATH.read_text(encoding="utf-8"))["events"]
    first = next(e for e in ev if e["date"] >= "2026-09-01")
    t_ms = int(_dt.datetime.fromisoformat(f"{first['date']}T{first['time']}")
               .replace(tzinfo=sq.NY).timestamp() * 1000)
    start = (t_ms // DAY) * DAY - 2 * DAY
    fr = _frame(n=4 * 96, seed=5, start_ms=start)
    sq.reset()
    ok = sq.entry_allowed(*fr)
    closes = np.asarray(fr[5], dtype=np.int64) + 900_000
    near = np.abs(closes - t_ms) <= 30 * 60_000
    assert near.sum() == 5                     # closes at -30, -15, 0, +15, +30 minutes
    assert not ok[near].any()
    weekday = ((closes // DAY) + 3) % 7 < 5
    assert ok[~near & weekday].all()


def test_a_quiet_weekend_candle_is_never_bought_and_a_busy_one_is():
    o, h, lo, c, v, ts = _frame(n=3 * 96, seed=6, start_ms=MON_AUG_31 - 2 * DAY)   # Sat
    v = [1000.0] * len(v)
    v[50], v[60], v[200] = 5000.0, 100.0, 100.0       # Saturday busy, Saturday quiet, Monday quiet
    sq.reset()
    ok = sq.entry_allowed(o, h, lo, c, v, ts)
    assert ok[50] and not ok[60] and ok[200]


def test_without_the_calendar_no_entry_is_allowed(monkeypatch, tmp_path):
    monkeypatch.setattr(sq, "NEWS_PATH", tmp_path / "missing.json")
    sq.reset()
    try:
        fr = _frame(n=600, seed=8)
        assert not any(_dirs("cq_rn00071", fr))
        assert not sq.entry_allowed(*fr).any()
    finally:
        sq.reset()


def test_a_candle_after_the_calendar_ends_is_never_bought():
    sq.reset()
    start = int(_dt.datetime(2026, 12, 31, tzinfo=_dt.timezone.utc).timestamp() * 1000)
    fr = _frame(n=400, seed=2, start_ms=start)
    ok = sq.entry_allowed(*fr)
    closes = np.asarray(fr[5], dtype=np.int64) + 900_000
    end = sq.news_times()[1][1]
    assert (closes >= end).any() and not ok[closes >= end].any()


def test_every_trigger_setting_fires_both_ways_somewhere():
    fr = _frame(n=6000, seed=12)
    for b in sq.TRIGGER_ORDER:
        for d in sq._digits(b):
            got = np.asarray(sq.part_dirs(sq.code_of(b, d), *fr))
            assert (got == 1).any() and (got == -1).any(), (b, d)


def test_every_confirmation_setting_lets_some_candles_through_and_stops_others():
    fr = _frame(n=3000, seed=13)
    for b in sq.CONFIRM_ORDER:
        for d in sq._digits(b):
            ok_long, ok_short = sq.part_dirs(sq.code_of(b, d), *fr)
            assert ok_long.any() and (~ok_long).any() and ok_short.any(), (b, d)


def test_an_existing_setup_is_its_own_rule_under_the_entry_rules():
    from tradingagents.signals_conf import CONF_SIGNALS

    fr = _frame(n=1500, seed=4)
    ok = sq.entry_allowed(*fr)
    for rule in ("cf_mom", "cx_maj3"):
        want = CONF_SIGNALS[rule](*fr)
        name = sq.name_of(("ex", (sq.EXISTING.index(rule),)))
        assert _dirs(name, fr) == [int(x) if a else 0 for x, a in zip(want, ok, strict=True)]


def test_random_entries_fire_at_their_rate():
    fr = _frame(n=6000, seed=1)
    ok = sq.entry_allowed(*fr)
    for name, rate in (("cq_rn00070", 0.01), ("cq_rn00071", 0.03)):
        d = np.asarray(_dirs(name, fr))
        assert 0.5 * rate < (d != 0).sum() / ok.sum() < 1.6 * rate, name


def test_every_name_reads_in_plain_words():
    for n in NAMES:
        assert sq.words(n), n
    assert sq.words("pt_brk_n0g0c0") == ""


def test_the_runner_and_the_backtest_read_the_same_signal():
    from tradingagents import auto_trader as at

    o, h, lo, c, v, ts = _frame(n=900, seed=9)
    for name in NAMES[::4]:
        want = _dirs(name, (o, h, lo, c, v, ts))
        got = at._dirs_for_backtest(name + "_gh_15m", h, lo, c, opens=o, volume=v, ts=ts)
        assert list(got) == want, name
        for cut in (400, 777, 900):
            live = at.signal_for(name, h[:cut], lo[:cut], c[:cut], opens=o[:cut],
                                 volume=v[:cut], ts=ts[:cut])
            assert live == want[cut - 1], (name, cut)


def test_an_unknown_cq_name_abstains_everywhere():
    from tradingagents import auto_trader as at

    o, h, lo, c, v, ts = _frame(n=400, seed=2)
    assert at.signal_for("cq_zz0-ev", h, lo, c, opens=o, volume=v, ts=ts) == 0
    assert not any(at._dirs_for_backtest("cq_fl00_gh_15m", h, lo, c, opens=o, volume=v, ts=ts))


def test_an_existing_setup_that_needs_funding_is_not_in_the_space():
    """The live runner calls signal_for without the funding history
    (auto_trader.process_symbol), so cf_fundfade* would trade in the backtest
    and abstain live - never a candidate (review, Oct 22, 2026)."""
    from tradingagents.signals_conf import CONF_SIGNALS

    for tf in ("15m", "4h"):
        for n in sq.entries_for(tf, "crypto"):
            spec = sq.spec_for(n)
            if spec["trigger"][0] == "ex":
                rule = sq.EXISTING[spec["trigger"][1][0]]
                assert not getattr(CONF_SIGNALS[rule], "needs_funding", False), (tf, rule)


def test_a_frame_grown_in_place_is_read_again():
    """The frame is found by identity first; a caller that appends a candle
    to the same lists must get the new candle's answer, never the cached one."""
    fresh = _dirs("cq_rn00071", tuple(list(x) for x in _frame(n=901, seed=14)))
    o, h, lo, c, v, ts = (list(x) for x in _frame(n=900, seed=14))
    first = _dirs("cq_rn00071", (o, h, lo, c, v, ts))     # the cache now holds THESE lists
    for lst, val in zip((o, h, lo, c, v, ts), (x[-1] for x in _frame(n=901, seed=14)), strict=True):
        lst.append(val)
    grown = _dirs("cq_rn00071", (o, h, lo, c, v, ts))
    assert len(first) == 900 and grown == fresh
```

- [ ] **Step 2: Run them** — `.venv/Scripts/python -m pytest tests/test_cq_signals.py -q` — Expected: FAIL, `ImportError: cannot import name 'signals_cq'`.
- [ ] **Step 3: Add the calendar's span** — `.venv/Scripts/python -c "import json,pathlib; p=pathlib.Path('research/cq/us_news.json'); d=json.loads(p.read_text(encoding='utf-8')); d={'about': d['about'], 'timezone': d['timezone'], 'from': '2023-10-01', 'through': '2026-12-31', 'events': d['events']}; p.write_text(json.dumps(d, indent=1, ensure_ascii=False) + chr(10), encoding='utf-8')"`
- [ ] **Step 4: Implement** — `tradingagents/signals_cq.py`:

```python
"""THE CONFLUENCE RESEARCH'S BUILDING BLOCKS (Oct 21, 2026), prefix `cq_`.

The operator: "I want you to reasearch confluence for each coins and each time
frame, my goal is 2:1R", their approved Prompt 1 (research/cq/prompts.md) and
"use supwerpower to decide the recommended". Design:
docs/superpowers/specs/2026-10-21-confluence-research-design.md.

A name is one COMBINATION: a trigger (when to enter) and one or two
confirmations (only if ...), every part from a different family, written
cq_<trigger code>[-<confirmation code>[-<confirmation code>]]. A code is the
block's two letters and one digit per setting (digit 0 = the standard value),
the confirmations sorted, so one combination has exactly one name
(cq_fl00-ev-vs1: a flag, only while EMA 9 is above EMA 21 and price is on the
trade's side of New York's VWAP). The grid appends `_gh_<tf>`; a name is read
by its own grammar, never split on "_".

Whole entries take no confirmation: `ex` wraps one of the 55 existing
confluence setups (cf_*, cx_*; EXISTING is frozen here so an index never
moves) and `rn` is the luck bar, seeded random entries on 1% or 3% of candles.

ONE implementation for the runner (auto_trader.signal_for reads the last
candle) and the backtest (_dirs_for_backtest, every candle). Every indicator
is fixed-window (pro_indicators) and every block reads at most ~250 candles,
so the runner's 299 closed candles decide what the year-deep window decides.
A session the frame does not hold from its first candle is unknown: nothing
is read from part of one.

TWO ENTRY RULES on every name, at their standard values, inside the signal so
the runner skips the same candles (the person-like rules of the prompt): no
entry from 30 minutes before to 30 minutes after a US CPI release, FOMC
decision or jobs report (research/cq/us_news.json; an unreadable calendar, or
a candle outside the stretch it covers, allows no entry at all: unknown is not
ok), and no weekend (UTC) entry on a candle whose volume is under the average
of the 20 before it.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import itertools
import json
import logging
import re
import threading
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from tradingagents import pro_indicators as pi, signals_pro as sp

PREFIX = "cq_"
VERSION = "cq1"                    # the search version, hashed into every seed
LOG = logging.getLogger(__name__)
DAY_MS = 86_400_000
HOUR_MS = 3_600_000
INTRADAY_TFS = ("15m", "30m", "1h")
INTRADAY_MAX_MS = HOUR_MS          # a frame of 1h candles or finer reads sessions
ROLLING_VWAP = 20                  # 4h and 1d read the last 20 candles' VWAP
NY = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")
SESSION_HOURS = {"london": (LONDON, (8, 0), (16, 30)), "ny": (NY, (9, 30), (16, 0))}
SESSION_WORDS = {"utc": "UTC day", "london": "London", "ny": "New York"}
NY_ONLY_KINDS = ("stocks", "indices")      # their own market: New York's session only
NEWS_PATH = Path(__file__).resolve().parent.parent / "research" / "cq" / "us_news.json"
NEWS_WINDOW_MS = 30 * 60_000
QUIET_RATIO = 1.0                  # a weekend candle under its 20-candle average volume
RANDOM_SEEDS = 560                 # x 2 rates = 1,120 random entries, about the real space

# the 55 existing confluence setups (signals_conf.CONF_SIGNALS on Oct 21,
# 2026), frozen: `ex07` must name the same rule for ever
EXISTING = (
    "cf_bosfvg", "cf_bosfvg_l1", "cf_bosfvg_l2", "cf_chan", "cf_chan_l1", "cf_chan_l2",
    "cf_diadx", "cf_diadx_l1", "cf_diadx_l2", "cf_donch", "cf_donch_l1", "cf_donch_l2",
    "cf_emarsi", "cf_emarsi_l1", "cf_emarsi_l2", "cf_eqhl", "cf_eqhl_l1", "cf_eqhl_l2",
    "cf_fundfade", "cf_fundfade_l1", "cf_fundfade_l2", "cf_maobv", "cf_maobv_l1",
    "cf_maobv_l2", "cf_mom", "cf_mom_l1", "cf_mom_l2", "cf_obretest", "cf_obretest_l1",
    "cf_obretest_l2", "cf_soup", "cf_soup1", "cf_soup1_l1", "cf_soup1_l2", "cf_soup_l1",
    "cf_soup_l2", "cf_stflip", "cf_stflip_l1", "cf_stflip_l2", "cf_triple", "cf_triple_l1",
    "cf_triple_l2", "cf_ttm", "cf_ttm_l1", "cf_ttm_l2", "cx_4h", "cx_any2", "cx_both",
    "cx_esc", "cx_fast", "cx_first", "cx_firstr", "cx_lvl", "cx_maj3", "cx_veto")

TRIGGER, CONFIRM, WHOLE = "trigger", "confirm", "whole"


# ------------------------------------------------------------------ the frame

_IDENT_LOCK = threading.Lock()
_IDENT: list = []


def _ctx(o, h, lo, c, v, ts):
    """The frame's shared indicators (signals_pro's Ctx and its cache). The
    grid hands every rule of one pair the SAME list objects, so the frame is
    recognised by identity first (hashing 200,000 values for each rule is the
    slow part); anything else is found by its fingerprint, as pt_ does. The
    lists are held, so an id cannot be reused while it is remembered."""
    refs = (o, h, lo, c, v, ts)
    # the same lists, still the same length and last candle: a caller that
    # grows a list in place is never answered from the frame it had before
    mark = (len(c), c[-1] if len(c) else None, ts[-1] if len(ts) else None)
    with _IDENT_LOCK:
        if (_IDENT and _IDENT[0][1] == mark
                and all(a is b for a, b in zip(_IDENT[0][0], refs, strict=True))):
            return _IDENT[0][2]
    ctx = sp._ctx(o, h, lo, c, v, ts)
    with _IDENT_LOCK:
        _IDENT[:] = [(refs, mark, ctx)]
    return ctx


def _m(ctx, key: tuple, make):
    return ctx.memo(("cq",) + key, make)


def _bar_ms(ctx) -> int:
    def make():
        if ctx.n < 2:
            return 0
        return int(np.median(np.diff(np.asarray(ctx.ts, dtype=np.int64))))
    return _m(ctx, ("bar",), make)


def _closes(ctx) -> np.ndarray:
    """Each candle's close in epoch ms, when its entry is bought: its open plus
    the frame's candle length (the median gap, so one missing candle never
    moves another candle's close)."""
    return _m(ctx, ("closes",), lambda: np.asarray(ctx.ts, dtype=np.int64) + _bar_ms(ctx))


def _intraday(ctx) -> bool:
    return 0 < _bar_ms(ctx) <= INTRADAY_MAX_MS


def _ema(ctx, n: int) -> np.ndarray:
    return _m(ctx, ("ema", n), lambda: pi.ema_fixed(ctx.c, n))


def _sma(ctx, n: int) -> np.ndarray:
    return _m(ctx, ("sma", n), lambda: pi.sma(ctx.c, n))


def _std(ctx, n: int) -> np.ndarray:
    return _m(ctx, ("std", n), lambda: pi.rolling_std(ctx.c, n))


def _atr(ctx, n: int) -> np.ndarray:
    return _m(ctx, ("atr", n), lambda: pi.atr(ctx.h, ctx.l, ctx.c, n))


def _rsi(ctx) -> np.ndarray:
    return _m(ctx, ("rsi", 14), lambda: pi.rsi(ctx.c, 14))


def _volr(ctx) -> np.ndarray:
    return _m(ctx, ("volr", 20), lambda: pi.vol_ratio(ctx.v, 20))


def _eff(ctx) -> np.ndarray:
    return _m(ctx, ("eff", 20), lambda: pi.efficiency(ctx.c, 20))


# ------------------------------------------------------------------- sessions

def _session(ctx, which: str):
    """(session id per candle, -1 outside it; the session's start, epoch ms;
    is that session whole in this frame): "utc" = the UTC day, "london" =
    8:00am-4:30pm London, "ny" = 9:30am-4pm New York, each on its own city's
    clock (daylight saving is never a fixed offset). A candle belongs to the
    session its OPEN falls in. A session that began before the frame's first
    candle is not whole, and nothing is read from it."""
    def make():
        t = np.asarray(ctx.ts, dtype=np.int64)
        n = len(t)
        if which == "utc":
            sid = t // DAY_MS
            start = sid * DAY_MS
        else:
            tz, (h0, m0), (h1, m1) = SESSION_HOURS[which]
            sid = np.full(n, -1, dtype=np.int64)
            start = np.zeros(n, dtype=np.int64)
            starts: dict = {}
            for i in range(n):
                d = _dt.datetime.fromtimestamp(int(t[i]) / 1000.0, tz)
                mins = d.hour * 60 + d.minute
                if h0 * 60 + m0 <= mins < h1 * 60 + m1:
                    day = d.date().toordinal()
                    if day not in starts:
                        starts[day] = int(_dt.datetime(d.year, d.month, d.day, h0, m0,
                                                       tzinfo=tz).timestamp() * 1000)
                    sid[i] = day
                    start[i] = starts[day]
        whole = (sid >= 0) & (start >= (int(t[0]) if n else 0))
        return sid, start, whole
    return _m(ctx, ("session", which), make)


def _sgroups(ctx, which: str) -> list:
    """[(first index, end index)] of each run of one session's candles."""
    def make():
        sid = _session(ctx, which)[0]
        n = len(sid)
        if not n:
            return []
        edges = np.r_[0, np.flatnonzero(np.diff(sid) != 0) + 1, n]
        return [(int(a), int(b)) for a, b in zip(edges[:-1], edges[1:], strict=True)
                if sid[a] >= 0]
    return _m(ctx, ("groups", which), make)


def _session_vwap(ctx, which: str) -> np.ndarray:
    """The session's volume-weighted average price through each candle
    (typical price x volume, summed fresh from the session's first candle);
    NaN outside the session, in one that is not whole, or before any volume."""
    def make():
        whole = _session(ctx, which)[2]
        tp = (ctx.h + ctx.l + ctx.c) / 3.0
        out = np.full(ctx.n, np.nan)
        for a, b in _sgroups(ctx, which):
            if not whole[a]:
                continue
            num = np.cumsum(tp[a:b] * ctx.v[a:b])
            den = np.cumsum(ctx.v[a:b])
            with np.errstate(invalid="ignore", divide="ignore"):
                out[a:b] = np.where(den > 0, num / den, np.nan)
        return out
    return _m(ctx, ("svwap", which), make)


def _vwap(ctx, which: str) -> np.ndarray:
    """The VWAP a block reads: the session's on 15m-1h, the last 20 candles'
    on 4h and 1d (a session is one to six candles there)."""
    if _intraday(ctx):
        return _session_vwap(ctx, which)
    return _m(ctx, ("rvwap",), lambda: pi.rolling_vwap(ctx.h, ctx.l, ctx.c, ctx.v, ROLLING_VWAP))


def _session_range(ctx, which: str):
    """(the session's highest high and lowest low BEFORE each candle; the
    session's first open): NaN on the session's first candle (no range yet),
    outside it, and in a session that is not whole."""
    def make():
        whole = _session(ctx, which)[2]
        hi = np.full(ctx.n, np.nan)
        lo = np.full(ctx.n, np.nan)
        op = np.full(ctx.n, np.nan)
        for a, b in _sgroups(ctx, which):
            if not whole[a]:
                continue
            if b - a > 1:
                hi[a + 1:b] = np.maximum.accumulate(ctx.h[a:b - 1])
                lo[a + 1:b] = np.minimum.accumulate(ctx.l[a:b - 1])
            op[a:b] = ctx.o[a]
        return hi, lo, op
    return _m(ctx, ("srange", which), make)


def _prev_day(ctx):
    """Yesterday's (UTC) high, low and close for each candle; NaN when the
    frame does not hold yesterday from its first candle, or skipped a day."""
    def make():
        sid, _start, whole = _session(ctx, "utc")
        hi = np.full(ctx.n, np.nan)
        lo = np.full(ctx.n, np.nan)
        cl = np.full(ctx.n, np.nan)
        prev = None
        for a, b in _sgroups(ctx, "utc"):
            if prev is not None and prev[2] and prev[3] == int(sid[a]) - 1:
                pa, pb = prev[0], prev[1]
                hi[a:b] = ctx.h[pa:pb].max()
                lo[a:b] = ctx.l[pa:pb].min()
                cl[a:b] = ctx.c[pb - 1]
            prev = (a, b, bool(whole[a]), int(sid[a]))
        return hi, lo, cl
    return _m(ctx, ("prevday",), make)


def _round_dist(ctx) -> np.ndarray:
    """How far each close is from the nearest round number: a multiple of
    10^(floor(log10 price) - 1) (BTC at 108,000 -> every 10,000; a 0.2534
    coin -> every 0.01)."""
    def make():
        c = ctx.c
        with np.errstate(invalid="ignore", divide="ignore"):
            step = 10.0 ** (np.floor(np.log10(np.where(c > 0, c, np.nan))) - 1.0)
            return np.abs(c - np.round(c / step) * step)
    return _m(ctx, ("round",), make)


# ------------------------------------------------------------------- triggers
#
# A trigger answers +1 / -1 / 0 for every candle; a confirmation answers
# (long allowed, short allowed). NaN anywhere means "not known": no entry.

def _t_fl(ctx, s) -> np.ndarray:
    """A bull (bear) flag: a pole of at least `pole` x ATR(14) inside 8 candles
    ending at candle p, then a flag of 3..`flag` candles that gives back at
    most half the pole and never passes its top (bottom), bought on the first
    close above (below) the flag."""
    k, longest = float(s["pole"]), int(s["flag"])
    c, h, lo = ctx.c, ctx.h, ctx.l
    a = _atr(ctx, 14)
    lo8, hi8 = pi.rolling_min(lo, 8), pi.rolling_max(h, 8)
    up, dn = c - lo8, hi8 - c
    with np.errstate(invalid="ignore"):
        bull = (up >= k * a).astype(float)
        bear = (dn >= k * a).astype(float)
    long = np.zeros(ctx.n, dtype=bool)
    short = np.zeros(ctx.n, dtype=bool)
    for f in range(3, longest + 1):
        g = f + 1                                  # the pole ends g candles back
        fh = pi.shift(pi.rolling_max(h, f), 1)     # the flag: the f candles before
        fl_ = pi.shift(pi.rolling_min(lo, f), 1)
        pc = pi.shift(c, g)
        with np.errstate(invalid="ignore"):
            long |= ((pi.shift(bull, g) == 1.0) & (fl_ >= pc - 0.5 * pi.shift(up, g))
                     & (fh <= pi.shift(hi8, g)) & (c > fh))
            short |= ((pi.shift(bear, g) == 1.0) & (fh <= pc + 0.5 * pi.shift(dn, g))
                      & (fl_ >= pi.shift(lo8, g)) & (c < fl_))
    return sp._edge(long, short)


def _t_sb(ctx, s) -> np.ndarray:
    """A session break: after the session's first hour, a close above the
    highest high (below the lowest low) the session made before that candle;
    `first` = only the first break each way per session."""
    which = s["session"]
    sid, start, whole = _session(ctx, which)
    hi, lo, _op = _session_range(ctx, which)
    t = np.asarray(ctx.ts, dtype=np.int64)
    late = (sid >= 0) & whole & (t >= start + HOUR_MS)
    with np.errstate(invalid="ignore"):
        up = late & (ctx.c > hi)
        down = late & (ctx.c < lo)
    if not s["first"]:
        return sp._edge(up, down)
    out = np.zeros(ctx.n, dtype=np.int8)
    for a, b in _sgroups(ctx, which):
        iu = np.flatnonzero(up[a:b])
        idn = np.flatnonzero(down[a:b])
        if len(iu):
            out[a + iu[0]] = 1
        if len(idn) and out[a + idn[0]] == 0:
            out[a + idn[0]] = -1
    return out


def _t_ec(ctx, s) -> np.ndarray:
    """The fast EMA crossing the slow one (both fixed-window), on the candle
    it happens."""
    fast, slow = s["pair"]
    f, sl = _ema(ctx, fast), _ema(ctx, slow)
    with np.errstate(invalid="ignore"):
        above, below = f > sl, f < sl
    ok = ~np.isnan(f) & ~np.isnan(sl)
    prev_ok = np.r_[False, ok[:-1]]
    prev_above = np.r_[False, above[:-1]]
    prev_below = np.r_[False, below[:-1]]
    out = np.zeros(ctx.n, dtype=np.int8)
    out[above & prev_ok & ~prev_above] = 1
    out[below & prev_ok & ~prev_below] = -1
    return out


def _t_pb(ctx, s) -> np.ndarray:
    """A pullback in the trend: price above its 50-candle average dips to the
    level (the VWAP, or EMA 21) - touching it, or 0.25 x ATR past it - and
    closes back above it (mirrored for shorts)."""
    lvl = _vwap(ctx, "utc") if s["level"] == "vwap" else _ema(ctx, 21)
    a, m, d = _atr(ctx, 14), _sma(ctx, 50), float(s["depth"])
    with np.errstate(invalid="ignore"):
        long = (ctx.c > m) & (ctx.l <= lvl - d * a) & (ctx.c > lvl)
        short = (ctx.c < m) & (ctx.h >= lvl + d * a) & (ctx.c < lvl)
    return sp._edge(long, short)


def _t_sq(ctx, s) -> np.ndarray:
    """A squeeze release: Bollinger(20, 2) inside Keltner(20, 1.5 x ATR 20) on
    each of the `n` candles before, then a close outside the Bollinger bands,
    taken that way."""
    n = int(s["n"])
    m, sd, a = _sma(ctx, 20), _std(ctx, 20), _atr(ctx, 20)
    bu, bl = m + 2.0 * sd, m - 2.0 * sd
    ku, kl = m + 1.5 * a, m - 1.5 * a
    with np.errstate(invalid="ignore"):
        tight = ((bu < ku) & (bl > kl)).astype(float)
    tight[np.isnan(bu) | np.isnan(ku)] = np.nan
    run = pi.shift(pi.rolling_sum(tight, n), 1)
    with np.errstate(invalid="ignore"):
        ready = run == n
        long = ready & (ctx.c > bu)
        short = ready & (ctx.c < bl)
    return sp._edge(long, short)


# -------------------------------------------------------------- confirmations

def _c_ev(ctx, s):
    f, sl = _ema(ctx, 9), _ema(ctx, 21)
    with np.errstate(invalid="ignore"):
        return f > sl, f < sl


def _c_vs(ctx, s):
    w = _vwap(ctx, s["session"])
    with np.errstate(invalid="ignore"):
        return ctx.c > w, ctx.c < w


def _c_ht(ctx, s):
    m = _sma(ctx, int(s["n"]))
    with np.errstate(invalid="ignore"):
        return ctx.c > m, ctx.c < m


def _c_vo(ctx, s):
    with np.errstate(invalid="ignore"):
        ok = _volr(ctx) >= float(s["m"])
    return ok, ok


def _c_rs(ctx, s):
    r, x = _rsi(ctx), float(s["x"])
    with np.errstate(invalid="ignore"):
        return r > x, r < 100.0 - x


def _c_kp(ctx, s):
    d = float(s["d"]) * _atr(ctx, 14)
    hi, lo, cl = _prev_day(ctx)
    op = _session_range(ctx, "utc")[2]
    near = np.zeros(ctx.n, dtype=bool)
    with np.errstate(invalid="ignore"):
        for lvl in (hi, lo, cl, op, _vwap(ctx, "utc")):
            near |= np.abs(ctx.c - lvl) <= d
        near |= _round_dist(ctx) <= d
    return near, near


def _c_tr(ctx, s):
    with np.errstate(invalid="ignore"):
        ok = _eff(ctx) >= float(s["e"])
    return ok, ok


# -------------------------------------------------------------- whole entries

def _w_ex(ctx, rule: str, o, h, lo, c, v, ts, funding) -> np.ndarray:
    """An existing confluence setup, exactly as the grid and the runner read it
    (signals_conf.CONF_SIGNALS); a name that registry no longer holds abstains."""
    def make():
        from tradingagents.signals_conf import CONF_SIGNALS

        fn = CONF_SIGNALS.get(rule)
        if fn is None:
            return np.zeros(ctx.n, dtype=np.int8)
        vol = v if v is not None else []
        d = (fn(o, h, lo, c, vol, ts, funding or [])
             if getattr(fn, "needs_funding", False) else fn(o, h, lo, c, vol, ts))
        return np.asarray(d, dtype=np.int8)
    return _m(ctx, ("ex", rule), make)


def _w_rn(ctx, seed: int, rate: float) -> np.ndarray:
    """Seeded random entries: each candle is an entry with probability `rate`,
    long or short at random, from a hash of the seed, the candle's own time and
    its close - the same coin flip for the same candle in any frame, never
    shared with another coin, never with pt_'s streams ("cq:" in the hash)."""
    def make():
        out = np.zeros(ctx.n, dtype=np.int8)
        for i, t in enumerate(ctx.ts):
            hsh = hashlib.blake2b(f"cq:{seed}:{int(t)}:{float(ctx.c[i])!r}".encode(),
                                  digest_size=8).digest()
            if int.from_bytes(hsh[:4], "big") / 2 ** 32 < rate:
                out[i] = 1 if hsh[4] & 1 else -1
        return out
    return _m(ctx, ("rn", int(seed), float(rate)), make)


# --------------------------------------------------------------------- blocks

BLOCKS = {
    "fl": {"role": TRIGGER, "family": "structure", "title": "bull/bear flag",
           "knobs": (("pole", (3.0, 2.0)), ("flag", (10, 6))), "fn": _t_fl,
           "say": lambda s: (f"a flag: a pole of {s['pole']:g}x the average range inside 8 "
                             f"candles, then a pause of 3 to {s['flag']} candles giving back at "
                             f"most half, bought on the break")},
    "sb": {"role": TRIGGER, "family": "time", "title": "session break",
           "knobs": (("session", ("utc", "london", "ny")), ("first", (True, False))),
           "fn": _t_sb,
           "say": lambda s: (f"{'the first' if s['first'] else 'each new'} close past the "
                             f"{SESSION_WORDS[s['session']]} session's high or low after its "
                             f"first hour")},
    "ec": {"role": TRIGGER, "family": "trend", "title": "EMA cross",
           "knobs": (("pair", ((9, 21), (20, 50))),), "fn": _t_ec,
           "say": lambda s: f"EMA {s['pair'][0]} crossing EMA {s['pair'][1]}"},
    "pb": {"role": TRIGGER, "family": "structure", "title": "pullback to a level",
           "knobs": (("level", ("vwap", "ema21")), ("depth", (0.0, 0.25))), "fn": _t_pb,
           "say": lambda s: (f"a dip to the {'VWAP' if s['level'] == 'vwap' else 'EMA 21'}"
                             f"{' and 0.25x the average range past it' if s['depth'] else ''} "
                             f"that closes back on the trend side (price vs its 50-candle "
                             f"average)")},
    "sq": {"role": TRIGGER, "family": "volatility", "title": "squeeze release",
           "knobs": (("n", (3, 6)),), "fn": _t_sq,
           "say": lambda s: (f"a squeeze release: Bollinger bands inside Keltner channels for "
                             f"{s['n']}+ candles, then a close outside the bands")},
    "ev": {"role": CONFIRM, "family": "trend", "title": "EMA 9 vs 21", "knobs": (),
           "fn": _c_ev, "say": lambda s: "only while EMA 9 is on the trade's side of EMA 21"},
    "vs": {"role": CONFIRM, "family": "volume", "title": "VWAP side",
           "knobs": (("session", ("utc", "ny")),), "fn": _c_vs,
           "say": lambda s: (f"only on the trade's side of the {SESSION_WORDS[s['session']]} "
                             f"VWAP (the last 20 candles' on 4h and 1d)")},
    "ht": {"role": CONFIRM, "family": "trend", "title": "bigger picture",
           "knobs": (("n", (240, 120)),), "fn": _c_ht,
           "say": lambda s: f"only on the trade's side of the {s['n']}-candle average"},
    "vo": {"role": CONFIRM, "family": "volume", "title": "volume burst",
           "knobs": (("m", (1.5, 2.0)),), "fn": _c_vo,
           "say": lambda s: f"only on a candle with {s['m']:g}x the volume of the 20 before"},
    "rs": {"role": CONFIRM, "family": "momentum", "title": "RSI side",
           "knobs": (("x", (50, 55)),), "fn": _c_rs,
           "say": lambda s: f"only with RSI(14) past {s['x']} the trade's way"},
    "kp": {"role": CONFIRM, "family": "structure", "title": "near a key price",
           "knobs": (("d", (0.5, 1.0)),), "fn": _c_kp,
           "say": lambda s: (f"only within {s['d']:g}x the average range of a key price "
                             f"(yesterday's high, low or close, the day's open, its VWAP, a "
                             f"round number)")},
    "tr": {"role": CONFIRM, "family": "volatility", "title": "trending",
           "knobs": (("e", (0.3, 0.4)),), "fn": _c_tr,
           "say": lambda s: (f"only when the last 20 candles went {s['e']:g}+ straight "
                             f"(Kaufman efficiency)")},
    "ex": {"role": WHOLE, "family": "existing", "title": "an existing confluence setup",
           "knobs": (("rule", EXISTING),), "widths": (2,),
           "say": lambda s: f"the existing setup {s['rule']}"},
    "rn": {"role": WHOLE, "family": "random", "title": "random entries (the luck bar)",
           "knobs": (("seed", range(10_000)), ("rate", (0.01, 0.03))), "widths": (4, 1),
           "say": lambda s: f"a coin flip on {s['rate'] * 100:g}% of candles (seed {s['seed']})"},
}
TRIGGER_ORDER = ("fl", "sb", "ec", "pb", "sq")
CONFIRM_ORDER = ("ev", "vs", "ht", "vo", "rs", "kp", "tr")


# ---------------------------------------------------------------------- names

def _widths(block: str) -> tuple:
    b = BLOCKS[block]
    return b.get("widths") or (1,) * len(b["knobs"])


def _settings(block: str, digits) -> dict:
    return {name: values[d] for (name, values), d in zip(BLOCKS[block]["knobs"], digits,
                                                          strict=True)}


def _digits(block: str) -> list:
    return list(itertools.product(*[range(len(v)) for _n, v in BLOCKS[block]["knobs"]]))


def code_of(block: str, digits=()) -> str:
    """("fl", (0, 1)) -> "fl01"; ("rn", (7, 0)) -> "rn00070"."""
    return block + "".join(f"{int(d):0{w}d}" for d, w in zip(digits, _widths(block),
                                                              strict=True))


def name_of(trigger, confirms=()) -> str:
    """("fl", (0, 0)), [("vs", (1,)), ("ev", ())] -> "cq_fl00-ev-vs1": the
    confirmations sorted by code, so one combination has one name."""
    codes = sorted(code_of(b, d) for b, d in confirms)
    return PREFIX + "-".join([code_of(*trigger), *codes])


def _part(code: str):
    block, digs = code[:2], code[2:]
    if block not in BLOCKS:
        return None
    widths = _widths(block)
    if len(digs) != sum(widths) or (digs and not digs.isdigit()):
        return None
    out, at_ = [], 0
    for (_name, values), w in zip(BLOCKS[block]["knobs"], widths, strict=True):
        d = int(digs[at_:at_ + w])
        at_ += w
        if d >= len(values):
            return None
        out.append(d)
    return block, tuple(out)


# a name is read by its own grammar - prefix, the codes joined by "-", then
# nothing or the grid's `_gh_<tf>` - never split on "_" (RCA-2026-09-24-G)
_NAME = re.compile(r"cq_([a-z]{2}\d*)((?:-[a-z]{2}\d*){0,2})(?=_|$)")


def spec_for(key: str) -> dict | None:
    """The parts a name holds, or None: a trigger with one or two
    confirmations of other families (or a whole entry alone), every code
    known, every digit in range, and the confirmations in their sorted order
    - any other spelling is not a name. Anything after the codes (the grid's
    `_gh_<tf>`) is ignored."""
    m = _NAME.match(str(key))
    if m is None:
        return None
    trig = _part(m.group(1))
    confs = [_part(x) for x in m.group(2).split("-")[1:]]
    if trig is None or any(x is None for x in confs):
        return None
    role = BLOCKS[trig[0]]["role"]
    if role == CONFIRM or (role == WHOLE and confs) or (role == TRIGGER and not confs):
        return None
    if any(BLOCKS[b]["role"] != CONFIRM for b, _d in confs):
        return None
    fams = [BLOCKS[b]["family"] for b, _d in [trig, *confs]]
    if len(set(fams)) != len(fams):
        return None
    name = name_of(trig, confs)
    if name != m.group(0):
        return None
    return {"name": name, "trigger": trig, "confirms": tuple(confs),
            "settings": {b: _settings(b, d) for b, d in [trig, *confs]}}


def words(name: str) -> str:
    """The combination in plain words (the results page); "" for a name that
    is not ours."""
    spec = spec_for(name)
    if spec is None:
        return ""
    tb, td = spec["trigger"]
    out = BLOCKS[tb]["say"](_settings(tb, td))
    if spec["confirms"]:
        out += ", " + " and ".join(BLOCKS[b]["say"](_settings(b, d)) for b, d in spec["confirms"])
    return out


def families(name: str) -> list:
    """The families a name's parts come from, trigger first."""
    spec = spec_for(name)
    if spec is None:
        return []
    return [BLOCKS[b]["family"] for b, _d in [spec["trigger"], *spec["confirms"]]]


# ---------------------------------------------------------------- entry rules

_NEWS: dict = {}
_NEWS_LOCK = threading.Lock()


def news_times():
    """(every US CPI, FOMC and jobs-report release in research/cq/us_news.json
    as sorted epoch ms; the (first, end) epoch ms the calendar covers), or
    (None, None) when the file is missing or unreadable."""
    with _NEWS_LOCK:
        if "t" not in _NEWS:
            try:
                d = json.loads(NEWS_PATH.read_text(encoding="utf-8"))
                tz = ZoneInfo(d.get("timezone") or "America/New_York")

                def ms(day: str, hhmm: str = "00:00") -> int:
                    return int(_dt.datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=tz)
                               .timestamp() * 1000)

                t = np.array(sorted(ms(e["date"], e["time"]) for e in d["events"]),
                             dtype=np.int64)
                _NEWS.update(t=t, span=(ms(d["from"]), ms(d["through"]) + DAY_MS))
            except Exception as exc:                                  # noqa: BLE001
                LOG.warning("the US news calendar %s could not be read (%s): no confluence "
                            "entry is allowed until it can", NEWS_PATH, exc)
                _NEWS.update(t=None, span=None)
        return _NEWS["t"], _NEWS["span"]


def _allowed(ctx) -> np.ndarray:
    """The candles an entry may be bought on: not from 30 minutes before to 30
    minutes after a US release, never outside the stretch the calendar covers
    (and none at all without it), and not a quiet weekend candle (closing on a
    UTC Saturday or Sunday with volume under the average of the 20 before;
    no average yet counts as quiet)."""
    def make():
        closes = _closes(ctx)
        t, span = news_times()
        if t is None:
            return np.zeros(ctx.n, dtype=bool)
        ok = (closes >= span[0]) & (closes < span[1])
        if len(t):
            j = np.searchsorted(t, closes)
            after = t[np.minimum(j, len(t) - 1)]
            before = t[np.maximum(j - 1, 0)]
            near = (((j < len(t)) & (after - closes <= NEWS_WINDOW_MS))
                    | ((j > 0) & (closes - before <= NEWS_WINDOW_MS)))
            ok &= ~near
        weekend = ((closes // DAY_MS) + 3) % 7 >= 5          # 1970-01-01 was a Thursday
        with np.errstate(invalid="ignore"):
            quiet = ~(_volr(ctx) >= QUIET_RATIO)
        return ok & ~(weekend & quiet)
    return _m(ctx, ("allowed",), make)


def entry_allowed(o, h, lo, c, v, ts) -> np.ndarray:
    """Which candles an entry may be bought on by the two entry rules."""
    if ts is None or len(ts) != len(c) or not len(c):
        return np.zeros(len(c), dtype=bool)
    return _allowed(_ctx(o, h, lo, c, v, ts)).copy()


def reset() -> None:
    """Forget the calendar and every cached frame (for a test that swaps the
    calendar)."""
    with _NEWS_LOCK:
        _NEWS.clear()
    with _IDENT_LOCK:
        _IDENT.clear()
    with sp._LOCK:
        sp._FRAMES.clear()


# ------------------------------------------------------------------ the signal

def _trigger(ctx, block: str, digits) -> np.ndarray:
    return _m(ctx, ("trig", block, tuple(digits)),
              lambda: BLOCKS[block]["fn"](ctx, _settings(block, digits)))


def _confirm(ctx, block: str, digits):
    return _m(ctx, ("conf", block, tuple(digits)),
              lambda: BLOCKS[block]["fn"](ctx, _settings(block, digits)))


def part_dirs(code: str, o, h, lo, c, v, ts):
    """One block's own answer on a frame (tests, the results page): a
    trigger's +1 / -1 / 0 per candle, a confirmation's (long ok, short ok)."""
    got = _part(code)
    if got is None or BLOCKS[got[0]]["role"] == WHOLE:
        raise ValueError(f"{code}: not a trigger or confirmation code")
    ctx = _ctx(o, h, lo, c, v, ts)
    if BLOCKS[got[0]]["role"] == TRIGGER:
        return _trigger(ctx, *got)
    return _confirm(ctx, *got)


def dirs_for(spec: dict, o, h, lo, c, v, ts, funding=None) -> list[int]:
    """+1 / -1 / 0 for every candle of the frame - the runner reads the last.
    A frame without its candles' times abstains (the entry rules need them)."""
    n = len(c)
    if spec is None or not n or ts is None or len(ts) != n:
        return [0] * n
    ctx = _ctx(o, h, lo, c, v, ts)
    blk, digits = spec["trigger"]
    if blk == "ex":
        raw = _w_ex(ctx, EXISTING[digits[0]], o, h, lo, c, v, ts, funding).copy()
    elif blk == "rn":
        s = _settings("rn", digits)
        raw = _w_rn(ctx, s["seed"], s["rate"]).copy()
    else:
        raw = _trigger(ctx, blk, digits).copy()
        for cb, cd in spec["confirms"]:
            ok_long, ok_short = _confirm(ctx, cb, cd)
            raw[(raw == 1) & ~ok_long] = 0
            raw[(raw == -1) & ~ok_short] = 0
    raw[~_allowed(ctx)] = 0
    return [int(x) for x in raw]


# ------------------------------------------------------------------ the space

def _usable(block: str, digits, intraday: bool, ny_only: bool) -> bool:
    s = _settings(block, digits)
    if block == "sb":
        return intraday and (not ny_only or s["session"] == "ny")
    if block == "vs":
        if not intraday:
            return tuple(digits) == (0,)           # one rolling VWAP on 4h and 1d
        return not ny_only or s["session"] == "ny"
    return True


def entries_for(tf: str, kind: str = "crypto") -> list[str]:
    """Every name the search may try on one timeframe for one asset kind
    (venue.kind): each trigger setting with one confirmation, and with two of
    different families, never a part of the trigger's own family; New York's
    session only for stock tokens and indices; no session break on 4h and 1d
    (and one VWAP there). Then the existing setups, as whole entries, but
    never one that reads funding (the runner does not pass it)."""
    from tradingagents.signals_conf import CONF_SIGNALS

    intraday = tf in INTRADAY_TFS
    ny_only = kind in NY_ONLY_KINDS
    trig = [(b, d) for b in TRIGGER_ORDER for d in _digits(b) if _usable(b, d, intraday, ny_only)]
    conf = [(b, d) for b in CONFIRM_ORDER for d in _digits(b) if _usable(b, d, intraday, ny_only)]
    out = []
    for t in trig:
        fam = BLOCKS[t[0]]["family"]
        ok = [x for x in conf if BLOCKS[x[0]]["family"] != fam]
        out += [name_of(t, [x]) for x in ok]
        out += [name_of(t, [x, y]) for x, y in itertools.combinations(ok, 2)
                if BLOCKS[x[0]]["family"] != BLOCKS[y[0]]["family"]]
    # never a setup that reads the funding history: the live runner calls
    # signal_for without it, so the rule would trade in the backtest and
    # abstain live (review, Oct 22, 2026)
    out += [name_of(("ex", (k,))) for k, rule in enumerate(EXISTING)
            if rule in CONF_SIGNALS and not getattr(CONF_SIGNALS[rule], "needs_funding", False)]
    return out


def random_entries(n_seeds: int = RANDOM_SEEDS) -> list[str]:
    """The luck search's space: `n_seeds` seeds x both rates."""
    return [name_of(("rn", (s, r))) for s in range(n_seeds) for r in (0, 1)]


def neighbours(name: str, pool) -> list[str]:
    """The names one step from `name` that are in `pool` (the coin and
    timeframe's own space, which also decides what is legal): one setting one
    step away, one confirmation swapped, one added, one dropped; an existing
    setup's other levels; a random stream's next seeds and its other rate."""
    spec = spec_for(name)
    if spec is None:
        return []
    out: list = []
    seen: set = {name}

    def add(other: str) -> None:
        if other not in seen and other in pool:
            seen.add(other)
            out.append(other)

    tb, td = spec["trigger"]
    if tb == "rn":
        seed, rate = td
        for s2 in (seed - 1, seed + 1):
            if 0 <= s2 < 10_000:
                add(name_of(("rn", (s2, rate))))
        add(name_of(("rn", (seed, 1 - rate))))
        return out
    if tb == "ex":
        base = re.sub(r"_l[12]$", "", EXISTING[td[0]])
        for k, other in enumerate(EXISTING):
            if re.sub(r"_l[12]$", "", other) == base:
                add(name_of(("ex", (k,))))
        return out
    confs = list(spec["confirms"])
    parts = [(tb, td), *confs]
    for j, (b, d) in enumerate(parts):
        for q in range(len(d)):
            for step in (-1, 1):
                v = d[q] + step
                if 0 <= v < len(BLOCKS[b]["knobs"][q][1]):
                    p2 = parts[:j] + [(b, d[:q] + (v,) + d[q + 1:])] + parts[j + 1:]
                    add(name_of(p2[0], p2[1:]))
    every = [(b, d) for b in CONFIRM_ORDER for d in _digits(b)]
    for j in range(len(confs)):
        for x in every:
            if x[0] != confs[j][0]:
                add(name_of((tb, td), confs[:j] + [x] + confs[j + 1:]))
    if len(confs) == 1:
        for x in every:
            add(name_of((tb, td), confs + [x]))
    if len(confs) == 2:
        for j in range(2):
            add(name_of((tb, td), [confs[1 - j]]))
    return out
```

- [ ] **Step 5: Run them** — same command — Expected: every test PASSES except the two routing tests (`test_the_runner_and_the_backtest_read_the_same_signal`, `test_an_unknown_cq_name_abstains_everywhere`), which wait for Task 3.
- [ ] **Step 6: Commit** — `tradingagents/signals_cq.py tests/test_cq_signals.py research/cq/us_news.json`, push.

### Task 3: The runner and the backtest read `cq_` from one place

**Files:**
- Modify: `tradingagents/auto_trader.py` (after the `pt_` block in `signal_for`, and after the `pt_` block in `_dirs_for_backtest`)

**Interfaces:**
- Consumes: `signals_cq.spec_for`, `signals_cq.dirs_for` (Task 2).

- [ ] **Step 1: The failing tests exist** (Task 2's last two) — `.venv/Scripts/python -m pytest tests/test_cq_signals.py -q -k "runner or abstains"` — Expected: FAIL (a cq_ name falls through to the registries and returns 0).
- [ ] **Step 2: Implement** — in `signal_for`, right after the `pt_` block:

```python
    # A CONFLUENCE RESEARCH combination (signals_cq, Oct 21, 2026): the same
    # `dirs_for` the research measured it with, last candle only. An unknown
    # cq_ name abstains.
    if str(key).startswith("cq_"):
        from tradingagents import signals_cq as _sq

        _spec = _sq.spec_for(key)
        if _spec is None:
            return 0
        dirs = _sq.dirs_for(_spec, opens or [], high, low, close, volume or [],
                            ts or [], funding or [])
        return dirs[-1] if dirs else 0
```

and in `_dirs_for_backtest`, right after the `pt_` block:

```python
    # A CONFLUENCE RESEARCH combination (signals_cq, Oct 21, 2026), checked
    # before every registry like pt_: an unknown cq_ name abstains.
    if str(key).startswith("cq_"):
        from tradingagents import signals_cq as _sq

        _spec = _sq.spec_for(key)
        if _spec is None:
            return out
        return _sq.dirs_for(_spec, opens or [], high, low, close, volume or [],
                            ts or [], funding or [])
```

- [ ] **Step 3: Run** — `.venv/Scripts/python -m pytest tests/test_cq_signals.py tests/test_pro_strategies.py -q` — Expected: PASS.
- [ ] **Step 4: Commit** — `tradingagents/auto_trader.py`, push.

### Task 4: The search (`cq_core`)

**Files:**
- Create: `tradingagents/cq_core.py`, `tests/test_cq_core.py`

**Interfaces:**
- Produces: `Part(trades, wins, profit, cost)`, `Stats(tun, chk, tst)`, `EMPTY`, `minus(a, b)`, `wilson_low(wins, trades, z=Z90)`, `payout_of(sl, tp, c)`, `bucket(k) -> int | None`, `worst_r(part, sl, tp, c_usual)`, `seed_of(*parts) -> int`, `search(n_entries, barriers, buckets, evaluate, *, seed, neighbours_of, c_usual, round_size=500, max_rounds=100, patience=10, top=25, fresh=0.2, keep=10, min_trades=20, deadline=None, clock=time.time) -> {"tried", "space", "stop", "rounds", "picks", "final", "champions", "stats"}`; constants `PAYOUTS`, `MIN_TUNE_TRADES`.

- [ ] **Step 1: Write the failing tests** — `tests/test_cq_core.py`:

```python
"""The confluence search (tradingagents/cq_core.py), Oct 21, 2026, on a
made-up world: scores, payouts, rounds, early stopping, and the rule that
keeps the test days a test - the search never reads them."""
from __future__ import annotations

import itertools
import random

import pytest

from tradingagents import cq_core as cq

N_E, N_B = 60, 8
BARRIERS = [(0.004 + 0.001 * b, 0.02 + 0.004 * b) for b in range(N_B)]
BUCKETS = [cq.PAYOUTS[b % 4] for b in range(N_B)]


def _world(tst_noise=0, flat_check=False, min_t=12):
    """Entry e has a hidden quality; its tuning and check win rates follow it
    with noise, its test days are noise of their own."""
    rnd = random.Random(0)
    q = [rnd.random() for _ in range(N_E)]
    calls = []

    def evaluate(cands):
        calls.append(list(cands))
        out = {}
        for e, b in cands:
            h = random.Random(e * 1000 + b)
            t = 10 + int(q[e] * 80)
            if t < min_t:
                out[(e, b)] = None
                continue
            w = min(t, int(t * (0.2 + 0.5 * q[e]) + h.random() * 3))
            ct = t // 3
            cw = 0 if flat_check else min(ct, int(ct * (0.2 + 0.5 * q[e]) + h.random() * 2))
            tt = t // 2
            tw = random.Random(tst_noise * 7919 + e * 31 + b).randint(0, tt)
            out[(e, b)] = cq.Stats(cq.Part(t, w, 0.0, t * 0.23), cq.Part(ct, cw, 0.0, ct * 0.23),
                                   cq.Part(tt, tw, float(tst_noise), tt * 0.23))
        return out

    return evaluate, calls


def _nbrs(e):
    return [x for x in (e - 1, e + 1) if 0 <= x < N_E]


def _run(seed=1, world=None, **kw):
    evaluate, calls = world or _world()
    kw.setdefault("round_size", 30)
    res = cq.search(N_E, BARRIERS, BUCKETS, evaluate, seed=seed, neighbours_of=_nbrs,
                    c_usual=0.0023, **kw)
    return res, calls


def test_the_worst_case_win_rate_is_wilsons_low_end():
    assert cq.wilson_low(0, 0) == 0.0
    assert cq.wilson_low(3, 3) == pytest.approx(0.526, abs=0.002)
    assert cq.wilson_low(90, 200) == pytest.approx(0.393, abs=0.002)
    assert cq.wilson_low(30, 40) == pytest.approx(0.624, abs=0.002)


def test_a_stop_target_is_classed_by_what_a_win_pays_after_the_round_trip():
    c = 0.0023
    assert cq.bucket(cq.payout_of(0.005, 0.02, c)) == 2       # 2.42
    assert cq.bucket(cq.payout_of(0.005, 0.03, c)) == 3       # 3.79
    assert cq.bucket(cq.payout_of(0.004, 0.04, c)) == 5       # 5.98
    assert cq.bucket(cq.payout_of(0.01, 0.02, c)) is None     # 1.44: never a candidate


def test_worst_r_reads_the_round_trip_the_trades_paid():
    p = cq.Part(40, 16, 0.0, 40 * 0.25)
    k = (0.02 - 0.0025) / (0.005 + 0.0025)
    assert cq.worst_r(p, 0.005, 0.02, 0.0023) == pytest.approx(cq.wilson_low(16, 40) * (k + 1) - 1)
    assert cq.worst_r(cq.EMPTY, 0.005, 0.02, 0.0023) is None


def test_a_run_repeats_exactly_from_its_seed():
    a, _ = _run(seed=7)
    b, _ = _run(seed=7)
    c, _ = _run(seed=8)
    assert a == b
    assert a["rounds"][0] != c["rounds"][0]


def test_no_candidate_is_tried_twice_and_rounds_keep_their_size():
    res, calls = _run(max_rounds=12)
    flat = list(itertools.chain.from_iterable(calls))
    assert len(flat) == len(set(flat)) == res["tried"]
    assert all(len(x) <= 30 for x in calls) and len(res["rounds"]) <= 12


def test_the_test_days_never_change_a_choice():
    a, _ = _run(world=_world(tst_noise=0))
    b, _ = _run(world=_world(tst_noise=99))
    strip = ("stats",)
    assert {k: v for k, v in a.items() if k not in strip} == \
        {k: v for k, v in b.items() if k not in strip}


def test_a_pick_is_a_champion_and_the_final_has_the_best_check_days_r():
    res, _ = _run(max_rounds=8)
    assert res["picks"]
    for k, cd in res["picks"].items():
        assert cd in res["champions"][k]
        assert BUCKETS[cd[1]] == k
    k0, cd0 = res["final"]
    r = {k: cq.worst_r(res["stats"][cd].chk, *BARRIERS[cd[1]], 0.0023)
         for k, cd in res["picks"].items()}
    assert r[k0] == max(v for v in r.values() if v is not None)
    assert res["picks"][k0] == cd0


def test_a_candidate_with_too_few_tuning_trades_is_never_a_champion():
    res, _ = _run(min_trades=50, max_rounds=8)
    for k in cq.PAYOUTS:
        for cd in res["champions"][k]:
            assert res["stats"][cd].tun.trades >= 50


def test_it_stops_when_no_payout_improves_for_patience_rounds():
    res, _ = _run(world=_world(flat_check=True), patience=3)
    assert res["stop"] == "patience" and len(res["rounds"]) == 4


def test_a_small_space_is_exhausted():
    evaluate, calls = _world()
    res = cq.search(3, BARRIERS[:2], BUCKETS[:2], evaluate, seed=3, neighbours_of=lambda e: [],
                    c_usual=0.0023, round_size=4)
    assert res["stop"] == "exhausted" and res["tried"] == 6
    assert [len(x) for x in calls] == [4, 2]


def test_later_rounds_search_around_the_best():
    res, calls = _run(max_rounds=2)
    best = res["rounds"][0]["best"]
    near = {(e2, b) for e, b in best for e2 in _nbrs(e)}
    assert near & set(calls[1])


def test_a_deadline_stops_between_rounds():
    ticks = iter(range(100))
    res, _ = _run(deadline=2, clock=lambda: next(ticks))
    assert res["stop"] == "deadline" and len(res["rounds"]) == 2
```

- [ ] **Step 2: Run** — `.venv/Scripts/python -m pytest tests/test_cq_core.py -q` — Expected: FAIL, `ImportError`.
- [ ] **Step 3: Implement** — `tradingagents/cq_core.py`:

```python
"""THE CONFLUENCE SEARCH (Prompt 1, Oct 21, 2026): rounds, scores and picks.

No market data here: the GitHub shard (.github/scripts/cq_shard.py) hands
`search` an `evaluate` that measures candidates with the nightly grid's own
engine, and this module decides which candidates to try and which is the
pick. Design: docs/superpowers/specs/2026-10-21-confluence-research-design.md.

A candidate is (entry, stop/target). Each measured candidate has three
stretches, by the day its trades CLOSED: tuning (the oldest days), check, and
test (the newest). The search reads the tuning days to choose and the check
days to judge, and NEVER the test days, so they stay a test (a test holds
that changing them changes nothing here).

* score: the worst-case win rate on the tuning days - the Wilson lower bound
  at z 1.645 (the low end of a 90% range); a candidate needs `min_trades`
  tuning trades to have one;
* rounds: round 1 is a seeded random draw; each later round tries the
  neighbours of the best `top` so far, spread over the payouts (one setting,
  one confirmation, the next stop/target of the same payout), plus `fresh`
  random draws; never a candidate twice;
* the pick per payout: of every round's best-by-tuning candidate (the
  champion after each round), the one with the best check-days worst-case
  win rate; the final pick: the payout whose pick has the best check-days
  worst-case profit per trade in R;
* early stop: `patience` rounds in a row with no payout's pick improving on
  its check days, or no untried candidate left.
"""
from __future__ import annotations

import hashlib
import math
import random
import time
from typing import NamedTuple

Z90 = 1.6448536269514722          # one side of a two-sided 90% range
PAYOUTS = (2, 3, 4, 5)
MIN_TUNE_TRADES = 20


class Part(NamedTuple):
    trades: int
    wins: int
    profit: float      # $ at the run's base margin, after every cost
    cost: float        # the round trips those trades paid, summed, % of the position


class Stats(NamedTuple):
    tun: Part
    chk: Part
    tst: Part


EMPTY = Part(0, 0, 0.0, 0.0)


def minus(a: Part, b: Part) -> Part:
    return Part(a.trades - b.trades, a.wins - b.wins, round(a.profit - b.profit, 2),
                round(a.cost - b.cost, 6))


def wilson_low(wins: int, trades: int, z: float = Z90) -> float:
    """The worst-case win rate: the low end of the Wilson range (0 with no
    trade). 3 wins of 3 is 52.6%, 90 of 200 is 39.3%."""
    if trades <= 0:
        return 0.0
    p = wins / trades
    z2 = z * z
    centre = p + z2 / (2 * trades)
    spread = z * math.sqrt(p * (1 - p) / trades + z2 / (4 * trades * trades))
    return max(0.0, (centre - spread) / (1 + z2 / trades))


def payout_of(sl: float, tp: float, c: float) -> float:
    """What one win pays in losses after a round trip `c` (fractions):
    (target - cost) / (stop + cost)."""
    return (tp - c) / (sl + c)


def bucket(k: float) -> int | None:
    """2:1 (2 to 3), 3:1 (3 to 4), 4:1 (4 to 5), 5:1 (5 or more); below 2:1 is
    never a candidate."""
    if not k >= 2.0:
        return None
    return min(5, int(math.floor(k + 1e-12)))


def worst_r(part: Part, sl: float, tp: float, c_usual: float) -> float | None:
    """The worst-case profit per trade in R (one R = the stop plus the round
    trip): worst-case win rate x (payout + 1) - 1, the payout on the round
    trip those trades PAID (the coin's usual one when nothing is on record).
    None with no trade."""
    if part.trades <= 0:
        return None
    c = (part.cost / part.trades / 100.0) if part.cost > 0 else c_usual
    return wilson_low(part.wins, part.trades) * (payout_of(sl, tp, c) + 1.0) - 1.0


def seed_of(*parts) -> int:
    """A search's seed: a hash of its coin, timeframe and version, so a run
    repeats exactly and two coins never share a draw."""
    d = hashlib.blake2b("|".join(str(p) for p in parts).encode(), digest_size=8).digest()
    return int.from_bytes(d, "big")


def _spread(best: dict, top: int) -> list:
    """The `top` best so far, one payout at a time in turn: every payout keeps
    searching around its own best (2:1 wins more often by nature and would
    otherwise take every place)."""
    out, j = [], 0
    while len(out) < top and any(j < len(best[k]) for k in PAYOUTS):
        for k in PAYOUTS:
            if j < len(best[k]) and len(out) < top:
                out.append(best[k][j])
        j += 1
    return out


def search(n_entries: int, barriers: list, buckets: list, evaluate, *, seed: int,
           neighbours_of, c_usual: float, round_size: int = 500, max_rounds: int = 100,
           patience: int = 10, top: int = 25, fresh: float = 0.2, keep: int = 10,
           min_trades: int = MIN_TUNE_TRADES, deadline: float | None = None,
           clock=time.time) -> dict:
    """Search (entry, stop/target) candidates. `barriers[b]` = (sl, tp)
    fractions, `buckets[b]` its payout class; `evaluate([(e, b), ...])` ->
    {(e, b): Stats or None (no trade)}; `neighbours_of(e)` -> entry indices one
    step away. Returns the rounds (each: candidates tried, its best `keep` by
    tuning score, each payout's champion), every payout's pick, the final
    pick (payout, candidate), the champions, why it stopped, and the Stats of
    every candidate it names."""
    nb = len(barriers)
    space = n_entries * nb
    rng = random.Random(seed)
    tried: dict = {}
    lists = {k: sorted((b for b in range(nb) if buckets[b] == k), key=lambda b: barriers[b])
             for k in PAYOUTS}
    pos = {b: (k, j) for k, bs in lists.items() for j, b in enumerate(bs)}

    def bar_nb(b):
        k, j = pos[b]
        return [lists[k][x] for x in (j - 1, j + 1) if 0 <= x < len(lists[k])]

    def score(st):
        if st is None or st.tun.trades < min_trades:
            return None
        return wilson_low(st.tun.wins, st.tun.trades)

    def chk(st):
        return wilson_low(st.chk.wins, st.chk.trades)

    def draw(n, avoid):
        free = space - len(tried) - len(avoid)
        if n <= 0 or free <= 0:
            return []
        if free <= 4 * n:
            pool = [(x // nb, x % nb) for x in range(space)]
            pool = [cd for cd in pool if cd not in tried and cd not in avoid]
            rng.shuffle(pool)
            return pool[:n]
        out, got = [], set()
        while len(out) < n:
            x = rng.randrange(space)
            cd = (x // nb, x % nb)
            if cd in tried or cd in avoid or cd in got:
                continue
            got.add(cd)
            out.append(cd)
        return out

    best: dict = {k: [] for k in PAYOUTS}
    champ: dict = {}
    champions: dict = {k: [] for k in PAYOUTS}
    picks: dict = {}
    rounds: list = []
    stale, stop = 0, "max_rounds"
    for r in range(1, max_rounds + 1):
        if deadline is not None and clock() >= deadline:
            stop = "deadline"
            break
        if len(tried) >= space:
            stop = "exhausted"
            break
        if r == 1:
            cands = draw(round_size, set())
        else:
            want = round_size - int(round(round_size * fresh))
            cands, seen = [], set()
            for _sc, (e, b) in _spread(best, top):
                for cd in [(e2, b) for e2 in neighbours_of(e)] + [(e, b2) for b2 in bar_nb(b)]:
                    if cd in tried or cd in seen:
                        continue
                    seen.add(cd)
                    cands.append(cd)
                    if len(cands) >= want:
                        break
                if len(cands) >= want:
                    break
            cands += draw(round_size - len(cands), seen)
        if not cands:
            stop = "exhausted"
            break
        got = evaluate(cands)
        scored = []
        for cd in cands:
            st = got.get(cd)
            tried[cd] = st
            sc = score(st)
            if sc is not None:
                scored.append((sc, cd))
        scored.sort(key=lambda x: (-x[0], x[1]))
        for sc, cd in scored:
            best[buckets[cd[1]]].append((sc, cd))
        improved = False
        for k in PAYOUTS:
            best[k] = sorted(best[k], key=lambda x: (-x[0], x[1]))[:top]
            if not best[k]:
                continue
            c0 = best[k][0][1]
            champ[k] = c0
            if c0 not in champions[k]:
                champions[k].append(c0)
            if k not in picks or chk(tried[c0]) > chk(tried[picks[k]]):
                picks[k] = c0
                improved = True
        rounds.append({"n": r, "tried": len(cands), "best": [cd for _sc, cd in scored[:keep]],
                       "champ": dict(champ)})
        stale = 0 if improved else stale + 1
        if stale >= patience:
            stop = "patience"
            break
    ranked = []
    for k, cd in picks.items():
        sl, tp = barriers[cd[1]]
        w = worst_r(tried[cd].chk, sl, tp, c_usual)
        ranked.append((-(w if w is not None else -math.inf), k, cd))
    final = None
    if ranked:
        ranked.sort()
        final = (ranked[0][1], ranked[0][2])
    named = (set(picks.values()) | {cd for k in PAYOUTS for cd in champions[k]}
             | {cd for rd in rounds for cd in rd["best"]})
    return {"tried": len(tried), "space": space, "stop": stop, "rounds": rounds,
            "picks": picks, "final": final, "champions": champions,
            "stats": {cd: tried[cd] for cd in named}}
```

- [ ] **Step 4: Run** — same command — Expected: PASS.
- [ ] **Step 5: Commit** — both files, push.

### Task 5: One GitHub machine (`cq_shard`)

**Files:**
- Create: `.github/scripts/cq_shard.py`, `tests/test_cq_shard.py`

**Interfaces:**
- Consumes: `signals_cq.entries_for/random_entries/neighbours/spec_for/VERSION` (Task 2), `cq_core.search/seed_of/bucket/payout_of/minus/Part/Stats/MIN_TUNE_TRADES` (Task 4), `sweep_shard.run_pair/eligible/coin_stream/report/log/COST_BOOKS/WARMUP_BARS/BASE_MARGIN/SHARD`, `check_run.verify_pair`, `cost_store.book_for/with_app_books/empty`, `br.pairs_for/fine_bars/round_trip_cost/charged_slippage/min_bars/TFS/RECENT_DAYS`.
- Produces: out files `out/cq-<N>.json.gz` (`{"version", "tfs", "history", "check", "test", "search", "luck", "coins": {coin: {"coin", "kind", "pre", "stats", "tfs": {tf: {"days", "first", "last", "c", "barriers": [[sl%, tp%, k]], "search": S, "luck": S}}}}}` where S = `{"seed", "entries", "space", "tried", "stop", "seconds", "n_errors", "errors", "rounds": [{"n", "tried", "best": [cand], "champ": {k: cand}}], "picks": {k: {"cand", "trades": {"row", "trades", ["drift"]}}}, "final": k}` and cand = `[name, sl%, tp%, k, tun[4], chk[4], tst[4]]`, each stretch `[trades, wins, profit $, cost %]`) and `out/cq-report-<N>.json` (`{"report": [...]}`); functions `frame`, `barriers_for`, `stats_from`, `whole_days`, `cq_pair`.

- [ ] **Step 1: Write the failing test** — `tests/test_cq_shard.py`:

```python
"""One confluence research machine end to end on a made-up market
(.github/scripts/cq_shard.py, Oct 21, 2026), with no network: the search and
the luck search on one coin + timeframe, every pick measured again with its
trades, the three stretches cut from the engine's own window counts, the
stop/targets legal, a coin too young for its windows skipped with why, and
the run repeating exactly from its seed.

The shard fixes RES/MODE/DAYS and patches br.SHORT_DAYS when it loads, so it
runs in its own process (in a temporary folder: it writes out/), never inside
the test session."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tradingagents import backtest_report as br, cq_core as cq, signals_cq as sq

ROOT = Path(__file__).resolve().parent.parent

_PROG = r'''
import json, os, sys
ROOT = sys.argv[1]
sys.path.insert(0, os.path.join(ROOT, ".github", "scripts"))
sys.path.insert(0, ROOT)
os.environ.update({"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": "", "INGEST_URL": "",
                   "COIN_LIST": "", "TA_VENUE": "gate", "TFS": "4h", "SHARD": "0",
                   "SEARCH": "40,3,2", "LUCK": "TEST", "MIN_TRADES": "5"})
import pandas as pd
import cq_shard as cs
import sweep_shard as ss
from tests.test_pro_strategies import _frame
from tradingagents import cost_store
# as on GitHub for a coin with no recorded minutes: an EMPTY book, so every
# trade pays the usual cost, counted
ss.cost_book = lambda sym: cost_store.empty()
ss.report = lambda *a, **k: None
ss.log = lambda *a, **k: None
cs._venue.kind = lambda sym: "stocks" if sym.startswith("STK") else "crypto"
step = 4 * 3_600_000
end_ms = 1_790_812_800_000            # Oct 01, 2026 00:00 UTC: inside the news calendar


def market(n, seed):
    o, h, lo, c, v, ts = _frame(n=n, seed=seed, step_s=step // 1000,
                                start_ms=end_ms - (n - 1) * step, vol=0.012)
    return pd.DataFrame({"Date": pd.to_datetime(ts, unit="ms"), "Open": o, "High": h,
                         "Low": lo, "Close": c, "Volume": v})


frames = {"TEST_USDT": market(4800, int(sys.argv[2])), "YOUNG_USDT": market(1500, 3)}


def stock_market(n, seed):
    """A stock token's 1h candles: every 7th candle printed no trade (its home
    market shut), which the closed-market rule refuses to buy."""
    hour = 3_600_000
    o, h, lo, c, v, ts = _frame(n=n, seed=seed, step_s=3600, start_ms=end_ms - (n - 1) * hour,
                                vol=0.006)
    v = [0.0 if i % 7 == 0 else x for i, x in enumerate(v)]
    return pd.DataFrame({"Date": pd.to_datetime(ts, unit="ms"), "Open": o, "High": h,
                         "Low": lo, "Close": c, "Volume": v})


frames["STK_USDT"] = stock_market(365 * 24 + 400, 7)
cs.fx.klines = lambda sym, iv, need: frames[sym].tail(int(need)).reset_index(drop=True)
pre = {"fee": 0.00075, "liq": 4.5, "fund": [], "slip": 0.0003, "fine": None, "meta": {}}
rec = {"coin": "TEST", "tfs": {}}
info = cs.cq_pair("TEST_USDT", "4h", pre, rec)
young = cs.cq_pair("YOUNG_USDT", "4h", pre, {"coin": "YOUNG", "tfs": {}})
bars, ks = cs.barriers_for("4h", 0.0021, 4.5)
fake = {"trades": 9, "recents": {
    240: {"trades": 3, "wins": 1, "profit": -0.5, "rt_sum": 0.6},
    360: {"trades": 5, "wins": 2, "profit": 0.25, "rt_sum": 1.0},
    cs.whole_days("4h"): {"trades": 9, "wins": 4, "profit": 1.75, "rt_sum": 1.8}}}
rec_stk = {"coin": "STK", "tfs": {}}
stk = cs.cq_pair("STK_USDT", "1h", pre, rec_stk)
# a signal that raises is COUNTED, never a silent "no trade"
errs = []
real_dirs = cs.at._dirs_for_backtest


def broken(key, *a, **k):
    if str(key).startswith("cq_ec0-vo0"):
        raise ValueError("planted")
    return real_dirs(key, *a, **k)


cs.at._dirs_for_backtest = broken
got = cs.measure("TEST_USDT", "4h", cs.frame("TEST_USDT", "4h"), pre,
                 {"cq_ec0-vo0": [bars[0]], "cq_ec0-rs0": [bars[0]]}, errs)
cs.at._dirs_for_backtest = real_dirs
# one coin, two timeframes: the first is on disk before the second starts
import gzip
import time as _time
_time.sleep = lambda s: None
cs.TFS = ["4h", "1d"]
asked, seen = [], []
cs.prefetch = lambda sym, days, meta=None: {"fee": 0.00075, "liq": 4.5, "fund": [],
                                            "slip": 0.0003, "fine": None, "meta": {}}
cs.coin_stats = lambda sym, pre_, before: asked.append(before) or {"vol": 1.0}


def fake_pair(sym, tf, pre_, rec_):
    if tf == "1d":
        with gzip.open(cs.OUT, "rt", encoding="utf-8") as fh:
            seen.append(sorted(json.load(fh)["coins"]["SAVE"]["tfs"]))
        raise RuntimeError("planted: the machine dies here")
    rec_["tfs"][tf] = {"days": 1, "search": {"tried": 3}}
    return {"tried": 3}


cs.cq_pair = fake_pair
report = []
cs.measure_coin("SAVE_USDT", report, 0, 1)
with gzip.open(cs.OUT, "rt", encoding="utf-8") as fh:
    saved = json.load(fh)
print(json.dumps({"info": info, "rec": rec, "young": young, "stk": stk, "rec_stk": rec_stk,
                  "bars": [[sl, tp, k] for (sl, tp), k in zip(bars, ks)],
                  "split": [list(p) for p in cs.stats_from(fake, "4h")],
                  "errs": errs, "got": [list(k) for k in got],
                  "asked": asked, "seen": seen, "report": report,
                  "saved_tfs": sorted(saved["coins"]["SAVE"]["tfs"]),
                  "saved_money": [saved.get("base"), saved.get("lev")]}, default=str))
'''


def _run(tmp, seed="5"):
    out = subprocess.run([sys.executable, "-c", _PROG, str(ROOT), seed], cwd=str(tmp),
                         capture_output=True, text=True, timeout=1200)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("cq1")), _run(tmp_path_factory.mktemp("cq2"))


def test_the_machine_searches_and_measures_every_pick_again(runs):
    got = runs[0]
    assert "why" not in got["info"] and "error" not in got["info"], got["info"]
    out = got["rec"]["tfs"]["4h"]
    s = out["search"]
    assert s["seed"] == cq.seed_of("TEST", "4h", sq.VERSION)
    assert 0 < s["tried"] <= 40 * 3 and 1 <= len(s["rounds"]) <= 3
    assert s["n_errors"] == 0, s["errors"]
    assert s["picks"] and s["final"] in s["picks"]
    legal = {(b[0], b[1]) for b in out["barriers"]}
    for k, p in s["picks"].items():
        name, sl, tp, bucket, tun, chk, tst = p["cand"]
        assert sq.spec_for(name)["name"] == name and str(bucket) == k
        assert (sl, tp) in legal and tun[0] >= 5
        t = p["trades"]
        assert "drift" not in t, t.get("drift")
        assert t["row"]["trades"] == tun[0] + chk[0] + tst[0] == len(t["trades"])


def test_the_luck_search_measures_random_entries_the_same_way(runs):
    luck = runs[0]["rec"]["tfs"]["4h"]["luck"]
    assert luck["seed"] == cq.seed_of("TEST", "4h", sq.VERSION, "luck")
    assert luck["picks"] and luck["n_errors"] == 0
    assert all(r[0].startswith("cq_rn") for rd in luck["rounds"] for r in rd["best"])


def test_a_run_repeats_exactly_from_its_seed(runs):
    a, b = (r["rec"]["tfs"]["4h"] for r in runs)
    for part in ("search", "luck"):
        x, y = dict(a[part]), dict(b[part])
        x.pop("seconds")
        y.pop("seconds")
        assert x == y, part


def test_every_stop_target_is_the_grids_own_and_pays_two_to_one(runs):
    grid = set(br.pairs_for("4h"))
    assert runs[0]["bars"]
    for sl, tp, k in runs[0]["bars"]:
        assert sl <= 0.02 and tp > sl and sl * 100 < 0.8 * 4.5
        assert (sl, tp) in grid
        assert cq.bucket(cq.payout_of(sl, tp, 0.0021)) == k


def test_the_three_stretches_are_cut_from_the_engines_own_window_counts(runs):
    tun, chk, tst = runs[0]["split"]
    assert tst == [3, 1, -0.5, 0.6]
    assert chk == [2, 1, 0.75, 0.4]
    assert tun == [4, 2, 1.5, 0.8]


def test_a_coin_too_young_for_its_windows_is_skipped_and_says_why(runs):
    assert runs[0]["young"]["why"].startswith("only 249 days")


def test_a_stock_token_searches_new_yorks_session_under_the_closed_market_rule(runs):
    got = runs[0]
    assert "why" not in got["stk"] and "error" not in got["stk"], got["stk"]
    s = got["rec_stk"]["tfs"]["1h"]["search"]
    assert s["entries"] == len(sq.entries_for("1h", "stocks")) and s["n_errors"] == 0
    names = [r[0] for rd in s["rounds"] for r in rd["best"]] + [p["cand"][0] for p in s["picks"].values()]
    for n in names:
        spec = sq.spec_for(n)
        for b, d in [spec["trigger"], *spec["confirms"]]:
            if b in ("sb", "vs"):
                assert sq._settings(b, d)["session"] == "ny", n
    # the closed-market rule ran on every pick (a stamp only a stock row carries)
    assert s["picks"] and all(isinstance(p["trades"]["row"]["closed_skipped"], int)
                              for p in s["picks"].values())
    assert "luck" not in got["rec_stk"]["tfs"]["1h"]          # LUCK named TEST only


def test_a_signal_that_raises_is_counted_never_a_silent_no_trade(runs):
    got = runs[0]
    assert any("cq_ec0-vo0" in e and "planted" in e for e in got["errs"]), got["errs"]
    assert any(k[0] == "cq_ec0-rs0" for k in got["got"])


def test_every_finished_timeframe_is_on_disk_before_the_next_starts(runs):
    got = runs[0]
    # the failing timeframe is tried 3 times (PAIR_RETRIES redos), and every
    # try found the finished 4h already on disk
    assert got["seen"] == [["4h"]] * 3 and got["saved_tfs"] == ["4h"]
    assert any(e["tf"] == "1d" and "planted" in e.get("error", "") for e in got["report"])


def test_the_coin_is_described_on_the_year_before_every_test_window(runs):
    assert runs[0]["asked"] == [365]                  # max(TEST_DAYS), whatever was dispatched


def test_the_results_name_the_money_they_were_measured_at(runs):
    assert runs[0]["saved_money"] == [5.0, 20]
```

- [ ] **Step 2: Run** — `.venv/Scripts/python -m pytest tests/test_cq_shard.py -q` — Expected: FAIL (`No module named 'cq_shard'` in the child's stderr).
- [ ] **Step 3: Implement** — `.github/scripts/cq_shard.py`:

```python
"""One GitHub machine of the CONFLUENCE RESEARCH (Prompt 1, Oct 21, 2026).

The operator: "I want you to reasearch confluence for each coins and each time
frame, my goal is 2:1R", their approved Prompt 1 (research/cq/prompts.md), and
"then start the prompt ... instead of waiting for me, use supwerpower to
decide the recommended". Design:
docs/superpowers/specs/2026-10-21-confluence-research-design.md.

For every claimed coin and every timeframe the search (tradingagents/cq_core)
looks for the combination of building blocks (tradingagents/signals_cq,
prefix cq_) and the stop/target that win most often in the worst case, per
payout (2:1, 3:1, 4:1, 5:1 after the coin's usual round trip). Every
candidate is measured by the nightly grid's own function
(`sweep_shard.run_pair` -> `backtest_strategy`: minute exits over the whole
window, the order book of each minute where one exists, the runner's
refusals) over a deep window, and ONE walk gives the three stretches by the
day each trade CLOSED: tuning (the oldest), check, and test (the newest),
which the search never reads.

The luck bar: on the coins in LUCK ("all", or a list), the same search over
seeded random entries (cq_rn...), chosen the same way.

Outputs (artifacts), rewritten after every coin so a machine stopped at the
6-hour limit still hands over what it finished:
* out/cq-<N>.json.gz - per coin: what the coin is, and per timeframe the
  search (and the luck search): seed, space, candidates tried, why it
  stopped, the round curve, each round's best 10, every payout's pick and
  the final pick, each pick measured again with every trade kept;
* out/cq-report-<N>.json - per coin + timeframe: seconds and candidates, or
  why it was skipped, or the error.
"""
# ruff: noqa: E402  (the imports must follow the RES/MODE/DAYS environment below)
from __future__ import annotations

import gzip
import io
import json
import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ["RES"] = "1m"
os.environ["MODE"] = "full"
# the per-minute order book is read for the newest BOOK_DAYS (+2): an older
# trade pays the coin's usual cost and is counted cost_unmeasured
BOOK_DAYS = 45
os.environ["DAYS"] = str(BOOK_DAYS)

import check_run as cr
import numpy as np
import pandas as pd
import sweep_shard as ss

import tradingagents.auto_trader as at
from tradingagents import backtest_report as br, cq_core as cq, signals_cq as sq, venue as _venue
from tradingagents.dataflows import exchange as fx

HISTORY = {"15m": 365, "30m": 365, "1h": 365, "4h": 730, "1d": 1095}
CHECK_DAYS = {"15m": 60, "30m": 60, "1h": 60, "4h": 120, "1d": 180}
TEST_DAYS = {"15m": 120, "30m": 120, "1h": 120, "4h": 240, "1d": 365}
BARS_PER_DAY = {"15m": 96, "30m": 48, "1h": 24, "4h": 6, "1d": 1}
MIN_TUNE_DAYS = 30
MAX_SL = 0.02                       # the rooms' stop cap
TFS = [t.strip() for t in (os.environ.get("TFS") or "15m,30m,1h,4h,1d").split(",")
       if t.strip() in HISTORY]
_S = [int(x) for x in (os.environ.get("SEARCH") or "500,100,10").split(",") if x.strip()]
ROUND_SIZE, MAX_ROUNDS, PATIENCE = (_S + [500, 100, 10][len(_S):])[:3]
MIN_TRADES = int(os.environ.get("MIN_TRADES") or cq.MIN_TUNE_TRADES)   # tests only
LUCK = (os.environ.get("LUCK") or "").strip()
LUCK_COINS = ({c.strip().upper().replace("_USDT", "") for c in LUCK.split(",") if c.strip()}
              if LUCK.lower() != "all" else set())
OUT = os.path.join("out", f"cq-{ss.SHARD}.json.gz")
REPORT_OUT = os.path.join("out", f"cq-report-{ss.SHARD}.json")
COIN_RETRIES = 2
PAIR_RETRIES = 2                 # a failed coin + timeframe is redone BY ITSELF
RETRY_CUTOFF_S = 4.8 * 3600      # no retry starts after this (runners die at 6 h)
DEADLINE_S = 5.6 * 3600          # a search still running stops its rounds here
STATS_BEFORE_DAYS = max(TEST_DAYS.values())   # a coin's numbers come from before every
                                              # timeframe's test days, whatever was dispatched
DAY_MS = 86_400_000
T0 = time.time()
STORE: dict = {}


def whole_days(tf: str) -> int:
    """A window longer than everything measured: its count is every trade."""
    return HISTORY[tf] + 400


def lucky(coin: str) -> bool:
    return LUCK.lower() == "all" or coin in LUCK_COINS


def frame(sym: str, tf: str, end_s: int | None = None):
    """The deep window of one timeframe, closed candles only, with the 300
    candles of lead-in the rules read: (whole frame, measured window, lead-in
    candles). A coin younger than the window has less lead-in, never one
    made up."""
    iv, bs, _cap = br.TFS[tf]
    need = HISTORY[tf] * BARS_PER_DAY[tf] + ss.WARMUP_BARS + 20
    if end_s is not None:
        need += int(max(0, time.time() - end_s) // bs) + 2
    df = at._closed_bars(fx.klines(sym, iv, need), bs)
    if end_s is not None and len(df):
        df = df[df["Date"] <= pd.Timestamp(int(end_s), unit="s")].reset_index(drop=True)
    if not len(df):
        return df, df, 0
    cut = df["Date"].iloc[-1] - pd.Timedelta(days=HISTORY[tf])
    measured = int((df["Date"] > cut).sum())
    warm = min(ss.WARMUP_BARS, len(df) - measured)
    dfw = df.iloc[len(df) - measured - warm:].reset_index(drop=True)
    return df, dfw, warm


def barriers_for(tf: str, c: float, liq) -> tuple[list, list]:
    """The grid's own stop/targets (br.pairs_for) a candidate may use: stop 2%
    or less and inside 80% of the liquidation distance (run_pair's own rule
    for a research name), target above the stop, paying at least 2:1 after
    the coin's usual round trip `c`. (stop/targets, the payout of each)."""
    out, ks = [], []
    for sl, tp in br.pairs_for(tf):
        if sl > MAX_SL + 1e-12 or tp <= sl:
            continue
        if liq is not None and sl * 100 >= 0.8 * abs(float(liq)):
            continue
        k = cq.bucket(cq.payout_of(sl, tp, c))
        if k is not None:
            out.append((sl, tp))
            ks.append(k)
    return out, ks


def stats_from(r: dict, tf: str, errors: list | None = None) -> cq.Stats:
    """The engine's window counts (the trades that CLOSED in the last W days)
    cut into the three stretches: tuning = whole - (test + check), check =
    (test + check) - test, test = the last test days."""
    rec = r.get("recents") or {}

    def part(d):
        x = rec.get(d) or rec.get(str(d)) or {}
        return cq.Part(int(x.get("trades") or 0), int(x.get("wins") or 0),
                       float(x.get("profit") or 0.0), float(x.get("rt_sum") or 0.0))

    t = part(TEST_DAYS[tf])
    tc = part(TEST_DAYS[tf] + CHECK_DAYS[tf])
    w = part(whole_days(tf))
    if errors is not None and w.trades != int(r.get("trades") or 0):
        errors.append(f"the whole window counted {w.trades} trades, the engine {r.get('trades')}")
    return cq.Stats(cq.minus(w, tc), cq.minus(tc, t), t)


def measure(sym: str, tf: str, fr, pre: dict, want: dict, errors: list) -> dict:
    """Each name in `want` at ITS OWN stop/targets, through the nightly grid's
    own function: {(name, sl, tp): the engine's result}. run_pair asks
    br.pairs_for(tf) once per name, right after it reads that name's signals
    (at._dirs_for_backtest), which is how the name being measured is known."""
    df, dfw, warm = fr
    tdays = TEST_DAYS[tf]
    got: dict = {}
    current: list = [None]
    engine, dirs_fn = at.backtest_strategy, at._dirs_for_backtest

    def keep(*a, **kw):
        key = (str(a[0]).rsplit("_gh_", 1)[0], round(float(kw["sl"]), 6),
               round(float(kw["tp"]), 6))
        try:
            r = engine(*a, **kw)
        except Exception as exc:                               # noqa: BLE001
            errors.append(f"{key}: {type(exc).__name__}: {str(exc)[:120]}")
            raise
        got[key] = r
        return r

    def dirs(key, *a, **kw):
        current[0] = str(key).rsplit("_gh_", 1)[0]
        try:
            return dirs_fn(key, *a, **kw)
        except Exception as exc:                               # noqa: BLE001
            # run_pair skips a name whose signals raise; counted here, so a
            # broken rule is an error on the page, never a quiet "no trade"
            errors.append(f"{current[0]} signals: {type(exc).__name__}: {str(exc)[:120]}")
            raise

    saved = (ss.window, br.pairs_for, at.backtest_strategy, at._dirs_for_backtest,
             br.SHORT_DAYS, br.RECENT_WINDOWS)
    ss.window = lambda _df: (dfw, warm)
    br.pairs_for = lambda _tf: list(want.get(current[0], ()))
    at.backtest_strategy = keep
    at._dirs_for_backtest = dirs
    br.SHORT_DAYS = (tdays, tdays + CHECK_DAYS[tf], whole_days(tf))
    br.RECENT_WINDOWS = br.SHORT_DAYS + (br.RECENT_DAYS,)
    try:
        ss.run_pair(sym, tf, io.StringIO(), signals=list(want), learned={**pre, "df": df})
    finally:
        (ss.window, br.pairs_for, at.backtest_strategy, at._dirs_for_backtest,
         br.SHORT_DAYS, br.RECENT_WINDOWS) = saved
    return got


def evaluator(sym: str, tf: str, fr, pre: dict, entries: list, bars: list, errors: list):
    """The search's `evaluate`: one run_pair call per round, each entry at the
    stop/targets the round asked of it."""
    def evaluate(cands):
        want: dict = {}
        for e, b in cands:
            want.setdefault(entries[e], []).append(bars[b])
        got = measure(sym, tf, fr, pre, want, errors)
        out = {}
        for e, b in cands:
            sl, tp = bars[b]
            r = got.get((entries[e], round(sl, 6), round(tp, 6)))
            out[(e, b)] = stats_from(r, tf, errors) if r and r.get("trades") else None
        return out
    return evaluate


ROW_KEEP = ("trades", "wins", "losses", "profit", "streak", "streak_len", "dd", "worst",
            "green", "months", "monthly", "rt_paid", "gate_blocked", "cost_unmeasured",
            "chase_skip", "closed_skipped", "unclear", "funding", "days", "bars", "last_ms")


def picked(sym: str, tf: str, fr, pre: dict, name: str, bar, st: cq.Stats) -> dict:
    """One pick measured again with every trade kept (check_run.verify_pair:
    the same function over the same bars): its row and its trades as [entry
    ms, exit ms, side, why, profit $, round trip %]; `drift` names a trade
    count that is not the search's (it must never be)."""
    df, dfw, warm = fr
    sl, tp = bar
    cfg = {"key": f"{name}:{tf}:{sl * 100:g}:{tp * 100:g}", "name": name, "tf": tf,
           "sl": sl * 100, "tp": tp * 100, "barrier": bar}
    lines = cr.verify_pair(sym, tf, df, pre, [cfg], window=lambda _df: (dfw, warm))
    if not lines:
        return {"row": None, "trades": [], "drift": "no trade when measured again"}
    ln = lines[0]
    out = {"row": {k: ln["row"].get(k) for k in ROW_KEEP}, "trades": ln["trades"]}
    n = st.tun.trades + st.chk.trades + st.tst.trades
    if int(ln["row"].get("trades") or 0) != n:
        out["drift"] = f"{ln['row'].get('trades')} trades measured again, {n} in the search"
    return out


def run_search(sym: str, tf: str, fr, pre: dict, entries: list, bars: list, ks: list,
               c_usual: float, seed: int, deadline: float) -> dict:
    """One search (the real one, or the luck one over random entries) and
    what it found, written by name."""
    errors: list = []
    evaluate = evaluator(sym, tf, fr, pre, entries, bars, errors)
    pool = set(entries)
    ix = {n: k for k, n in enumerate(entries)}
    near: dict = {}

    def neighbours_of(e):
        if e not in near:
            near[e] = [ix[n] for n in sq.neighbours(entries[e], pool)]
        return near[e]

    t1 = time.time()
    res = cq.search(len(entries), bars, ks, evaluate, seed=seed, neighbours_of=neighbours_of,
                    c_usual=c_usual, round_size=ROUND_SIZE, max_rounds=MAX_ROUNDS,
                    patience=PATIENCE, min_trades=MIN_TRADES, deadline=deadline)
    st = res["stats"]

    def row(cd):
        e, b = cd
        s = st[cd]
        return [entries[e], round(bars[b][0] * 100, 4), round(bars[b][1] * 100, 4), ks[b],
                list(s.tun), list(s.chk), list(s.tst)]

    picks = {str(k): {"cand": row(cd), "trades": picked(sym, tf, fr, pre, entries[cd[0]],
                                                        bars[cd[1]], st[cd])}
             for k, cd in sorted(res["picks"].items())}
    return {"seed": seed, "entries": len(entries), "space": res["space"], "tried": res["tried"],
            "stop": res["stop"], "seconds": round(time.time() - t1, 1),
            "n_errors": len(errors), "errors": errors[:20],
            "rounds": [{"n": rd["n"], "tried": rd["tried"],
                        "best": [row(cd) for cd in rd["best"]],
                        "champ": {str(k): row(cd) for k, cd in sorted(rd["champ"].items())}}
                       for rd in res["rounds"]],
            "picks": picks, "final": str(res["final"][0]) if res["final"] else None}


def cq_pair(sym: str, tf: str, pre: dict, rec: dict) -> dict:
    """The search (and on a luck coin the random search) on one coin +
    timeframe. The record reaches the coin only once the whole pair
    finished: a pair that raises leaves nothing behind and is redone by
    itself."""
    coin = sym.replace("_USDT", "")
    fr = frame(sym, tf)
    _df, dfw, warm = fr
    if not len(dfw) or len(dfw) - warm < br.min_bars(tf):
        return {"why": f"only {max(0, len(dfw) - warm)} measurable candles"}
    days = int((dfw["Date"].iloc[-1] - dfw["Date"].iloc[warm]).days)
    if days < TEST_DAYS[tf] + CHECK_DAYS[tf] + MIN_TUNE_DAYS:
        return {"why": f"only {days} days: {MIN_TUNE_DAYS}+ tuning days must come before the "
                       f"{CHECK_DAYS[tf]} check and {TEST_DAYS[tf]} test days"}
    c_usual = br.round_trip_cost(pre["fee"], {"slippage": pre["slip"]})
    bars, ks = barriers_for(tf, c_usual, pre["liq"])
    if not bars:
        return {"why": "no stop/target pays 2:1 at this coin's usual round trip"}
    deadline = T0 + DEADLINE_S
    out = {"days": days, "first": int(dfw["Date"].iloc[warm].timestamp()),
           "last": int(dfw["Date"].iloc[-1].timestamp()), "c": round(c_usual * 100, 4),
           "barriers": [[round(sl * 100, 4), round(tp * 100, 4), k]
                        for (sl, tp), k in zip(bars, ks, strict=True)]}
    entries = sq.entries_for(tf, _venue.kind(sym))
    out["search"] = run_search(sym, tf, fr, pre, entries, bars, ks, c_usual,
                               cq.seed_of(coin, tf, sq.VERSION), deadline)
    if lucky(coin):
        out["luck"] = run_search(sym, tf, fr, pre, sq.random_entries(), bars, ks, c_usual,
                                 cq.seed_of(coin, tf, sq.VERSION, "luck"), deadline)
    rec["tfs"][tf] = out
    s = out["search"]
    return {"entries": len(entries), "tried": s["tried"], "rounds": len(s["rounds"]),
            "stop": s["stop"], "days": days, "last": out["last"],
            **({"luck_tried": out["luck"]["tried"]} if "luck" in out else {})}


def usual_slip(book: dict) -> float | None:
    """A coin's usual one-side cost: the median of its recorded minutes' buy
    and sell costs (never one live reading). None when nothing was recorded."""
    if book is None or not len(book.get("t", [])):
        return None
    ok = ~np.asarray(book["exhausted"], dtype=bool)
    if not ok.any():
        return None
    both = (np.asarray(book["buy"], dtype=float)[ok]
            + np.asarray(book["sell"], dtype=float)[ok]) / 2
    both = both[np.isfinite(both)]
    return float(np.median(both)) if len(both) else None


def prefetch(sym: str, days: int, meta: dict | None = None) -> dict:
    """One coin's fee, liquidation distance, funding (Gate serves 180 days),
    minute order book for the newest BOOK_DAYS, the usual cost every older
    trade pays, and the finest bars for the whole `days` (every exit settled
    by the minute; a candle with no minute under it settles by the candle's
    own rule). `meta` replays an earlier run's choices."""
    from tradingagents import cost_store

    now = int(time.time())
    meta = dict(meta or {})
    fee = float(meta["fee"]) if meta.get("fee") is not None else at.taker_fee(sym, fx=fx)
    liq = (float(meta["liq"]) if meta.get("liq") is not None
           else fx.liquidation_move_pct(sym, at.LEVERAGE))
    fund = fx.funding_history(sym)
    fine_from = int(meta.get("fine_from") or now - (days + 2) * 86400)
    book_lo = int(meta.get("book_lo") or now - (BOOK_DAYS + 2) * 86400)
    book_hi = int(meta.get("book_hi") or now)
    try:
        book = cost_store.with_app_books(sym, cost_store.book_for(sym, book_lo, book_hi),
                                         book_lo, book_hi)
    except Exception as exc:                                   # noqa: BLE001
        ss.log(f"{sym}: the per-minute costs could not be read ({exc}); every trade pays "
               f"the usual cost and is counted unmeasured")
        book = cost_store.empty()
    ss.COST_BOOKS[sym] = book            # run_pair's cost_book(sym) reads this one
    slip = meta.get("slip")
    source = meta.get("slip_source")
    if slip is None:
        slip = usual_slip(book)
        source = "median of the recorded minutes"
        if slip is None:
            live = fx.book_cost(sym, ss.BASE_MARGIN * at.LEVERAGE)
            slip = br.charged_slippage([float(live.get("slippage") or 0.0) or 0.0003])
            source = "one live reading (no minutes recorded)"
    _t, _h, _l, n5 = br.fine_bars(sym, fine_from, fx=fx)
    return {"fee": fee, "liq": liq, "fund": fund, "slip": float(slip), "fine": (_t, _h, _l),
            "meta": {"fine_from": fine_from, "book_lo": book_lo, "book_hi": book_hi,
                     "fee": fee, "liq": liq, "slip": float(slip), "slip_source": source,
                     "minutes": len(_t), "five_minute": int(n5 or 0)}}


_BTC: dict = {}


def coin_stats(sym: str, pre: dict, before_days: int) -> dict:
    """What the coin IS, measured on its 1h candles in the year BEFORE every
    timeframe's test days (no look-ahead into the days a pick is judged on):
    daily volatility and trending vs. snapping back decide its group in the
    second stage; its usual cost and its correlation with BTC ride beside."""
    hours = (before_days + 2 + 365) * 24 + 40
    df = at._closed_bars(fx.klines(sym, "Min60", hours), 3600)
    if len(df) < 200:
        return {"why": f"only {len(df)} hourly candles"}
    ts = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    keep = ts < int(ts[-1]) - (before_days + 2) * DAY_MS
    c = df["Close"].to_numpy(dtype=float)[keep]
    if len(c) < 200:
        return {"why": f"only {len(c)} hourly candles before the test days"}
    r = np.diff(np.log(c))
    var1 = float(np.var(r))
    r24 = np.log(c[24:] / c[:-24])
    vr = float(np.var(r24) / (24 * var1)) if var1 > 0 else math.nan
    out = {"vol": round(float(np.std(r)) * math.sqrt(24) * 100, 3), "vr": round(vr, 3),
           "kind": _venue.kind(sym), "hours": int(len(c)),
           "cost": round(br.round_trip_cost(pre["fee"], {"slippage": pre["slip"]}) * 100, 4)}
    try:
        if "t" not in _BTC:
            b = at._closed_bars(fx.klines("BTC_USDT", "Min60", hours), 3600)
            _BTC["t"] = b["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
            _BTC["c"] = b["Close"].to_numpy(dtype=float)
        _common, ia, ib = np.intersect1d(ts[keep], _BTC["t"], return_indices=True)
        if len(ia) > 200:
            ra, rb = np.diff(np.log(c[ia])), np.diff(np.log(_BTC["c"][ib]))
            out["btc_corr"] = round(float(np.corrcoef(ra, rb)[0, 1]), 3)
    except Exception as exc:                                   # noqa: BLE001
        out["btc_corr_error"] = str(exc)[:120]
    return out


def save_json(path: str, obj) -> None:
    os.makedirs("out", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"), default=str)
    os.replace(tmp, path)


def save_out() -> None:
    """Every coin this machine finished, in one file swapped whole."""
    os.makedirs("out", exist_ok=True)
    tmp = OUT + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump({"version": sq.VERSION, "tfs": TFS, "history": HISTORY,
                   "check": CHECK_DAYS, "test": TEST_DAYS,
                   "search": {"round_size": ROUND_SIZE, "max_rounds": MAX_ROUNDS,
                              "patience": PATIENCE, "min_trades": MIN_TRADES},
                   "luck": LUCK, "base": ss.BASE_MARGIN, "lev": at.LEVERAGE,
                   "coins": STORE}, fh, separators=(",", ":"), default=str)
    os.replace(tmp, OUT)


def late() -> bool:
    """No retry starts this late: a runner is killed at 6 hours."""
    return time.time() - T0 > RETRY_CUTOFF_S


def run(per_coin) -> int:
    """Claim coins off the board one at a time; a coin that raises is tried
    again by itself up to COIN_RETRIES (never past the cutoff), then named."""
    os.makedirs("out", exist_ok=True)
    coins = ss.eligible()
    ss.report.board = len(coins)
    report: list = []
    failed: dict = {}
    done = 0
    stream = ss.coin_stream(coins, T0)
    queue: list = []
    while True:
        sym = next(stream, None)
        if sym is None:
            if not queue or late():
                for q in queue:
                    report.append({"coin": q.replace("_USDT", ""), "tf": "*",
                                   "error": "not redone: out of time"})
                break
            sym = queue.pop(0)
        try:
            per_coin(sym, report, done, len(coins))
            done += 1
        except Exception as exc:                               # noqa: BLE001
            n = failed.get(sym, 0) + 1
            failed[sym] = n
            ss.log(f"{sym}: FAILED ({type(exc).__name__}: {exc}) try {n}")
            if n <= COIN_RETRIES:
                queue.append(sym)
            else:
                report.append({"coin": sym.replace("_USDT", ""), "tf": "*",
                               "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        save_json(REPORT_OUT, {"report": report, "tfs": TFS, "history": HISTORY})
        ss.report("testing", done, len(coins), note=f"{sym.replace('_USDT', '')} done")
    ss.log(f"done: {done} coin(s) in {(time.time() - T0) / 60:.0f} min")
    return 0


def each_tf(coin: str, tfs, work, report: list) -> None:
    """Run `work(tf) -> dict` for every timeframe; one that raises is redone BY
    ITSELF after the others, up to PAIR_RETRIES (CLAUDE.md: a failed coin is
    redone alone), and named if it never recovers."""
    pending = list(tfs)
    for attempt in range(PAIR_RETRIES + 1):
        again = []
        for tf in pending:
            t1 = time.time()
            entry = {"coin": coin, "tf": tf}
            try:
                entry.update(work(tf))
            except Exception as exc:                           # noqa: BLE001
                entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                ss.log(f"{coin} {tf}: FAILED (try {attempt + 1}) {entry['error']}")
                ss.log(traceback.format_exc()[-800:])
                if attempt < PAIR_RETRIES and not late():
                    again.append(tf)
                    continue
            entry["seconds"] = round(time.time() - t1, 1)
            if attempt:
                entry["tries"] = attempt + 1
            report.append(entry)
            ss.log(f"{coin} {tf}: {entry.get('tried', '-')} tried, "
                   f"{entry.get('why') or entry.get('error') or entry.get('stop')} "
                   f"in {entry['seconds']}s")
        if not again:
            return
        time.sleep(5 * (attempt + 1))
        pending = again


def measure_coin(sym: str, report: list, done: int, total: int) -> None:
    """One coin: its costs, what it is, then every timeframe - each one saved
    the moment it finishes, so a machine killed in the middle of a coin still
    hands over the timeframes it finished (review, Oct 22, 2026)."""
    coin = sym.replace("_USDT", "")
    pre = prefetch(sym, max(HISTORY[t] for t in TFS))
    rec = {"coin": coin, "kind": _venue.kind(sym), "pre": pre["meta"], "tfs": {}}
    try:
        rec["stats"] = coin_stats(sym, pre, STATS_BEFORE_DAYS)
    except Exception as exc:                                   # noqa: BLE001
        rec["stats"] = {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    STORE[coin] = rec

    def work(tf):
        got = cq_pair(sym, tf, pre, rec)
        save_out()
        return got

    each_tf(coin, TFS, work, report)
    save_out()


def search() -> int:
    ss.log(f"confluence research: timeframes {TFS}, rounds of {ROUND_SIZE} up to "
           f"{MAX_ROUNDS}, patience {PATIENCE}, luck "
           f"{'every coin' if LUCK.lower() == 'all' else f'{len(LUCK_COINS)} coin(s)'}")

    return run(measure_coin)


def main() -> int:
    return search()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run** — same command — Expected: PASS (two child runs, about a minute).
- [ ] **Step 5: Commit** — both files, push.

### Task 6: The workflow (`cq.yml`)

**Files:**
- Create: `.github/workflows/cq.yml`
- Test: `tests/test_cq_search.py::test_the_workflow_takes_exactly_what_the_dispatch_sends` (written in Task 7's file; run here)

**Interfaces:**
- Consumes: the shard's env (`SHARD`, `SHARDS`, `TFS`, `COIN_LIST`, `BASE_MARGIN`, `LUCK`, `SEARCH`).
- Produces: inputs `shards, timeframes, coin_list, base, label, luck, search`; run-name `Confluence research · <label>`; artifacts `cq-out-<shard>`.

- [ ] **Step 1: Write the file:**

```yaml
name: Confluence research
run-name: "Confluence research · ${{ inputs.label }}"

# The operator, Oct 21, 2026: "I want you to reasearch confluence for each
# coins and each time frame, my goal is 2:1R", their approved Prompt 1
# (research/cq/prompts.md) and "then start the prompt ... use supwerpower to
# decide the recommended". Design:
# docs/superpowers/specs/2026-10-21-confluence-research-design.md.
#
# Its own workflow, never sweep.yml: a research run must never write the
# market grid's pair-done markers, saved positions or the store. Public market
# data only - no credentials are read. Dealt between every account by
# tradingagents/cq_search.py (each account gets its own coin_list).

on:
  workflow_dispatch:
    inputs:
      shards:
        description: "How many runners to split the work across"
        default: "20"
      timeframes:
        description: "Comma-separated timeframes"
        default: "15m,30m,1h,4h,1d"
      coin_list:
        description: "Comma-separated symbols (BTC_USDT,ETH_USDT); empty = the whole market"
        default: ""
      base:
        description: "Base margin $ per trade"
        default: "5"
      label:
        description: "A name for this run (its title)"
        default: "manual"
      luck:
        description: "The luck search (random entries): all, or comma-separated coins, or empty"
        default: ""
      search:
        description: "round size, most rounds, patience"
        default: "500,100,10"

permissions:
  contents: write        # claims and progress on the sweep-progress branch
  actions: read

# THE EXCHANGE (Oct 10, 2026, the move to Gate)
env:
  TA_VENUE: gate

jobs:
  plan:
    runs-on: ubuntu-latest
    outputs:
      shards: ${{ steps.mk.outputs.shards }}
    steps:
      - id: mk
        run: |
          python3 - <<'PY' >> "$GITHUB_OUTPUT"
          import json, os
          n = int(os.environ["N"])
          print("shards=" + json.dumps(list(range(n))))
          PY
        env:
          N: ${{ github.event.inputs.shards }}

  research:
    needs: plan
    runs-on: ubuntu-latest
    timeout-minutes: 350          # runners are killed at 6h; stop before that
    strategy:
      fail-fast: false            # one bad machine must not bin the others
      matrix:
        shard: ${{ fromJson(needs.plan.outputs.shards) }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install
        run: |
          python -m pip install --upgrade pip
          # the PC's own versions: the runner and the backtest must compute
          # the same indicator values to the last bit (pro_indicators)
          pip install "pandas==3.0.5" "numpy==2.5.2" requests

      - name: Research shard ${{ matrix.shard }}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          SHARD: ${{ matrix.shard }}
          SHARDS: ${{ github.event.inputs.shards }}
          TFS: ${{ github.event.inputs.timeframes }}
          COIN_LIST: ${{ github.event.inputs.coin_list }}
          BASE_MARGIN: ${{ github.event.inputs.base }}
          LUCK: ${{ github.event.inputs.luck }}
          SEARCH: ${{ github.event.inputs.search }}
        run: python .github/scripts/cq_shard.py

      # always(): a machine stopped at the time limit still hands over every
      # coin it finished - the files are rewritten after each coin
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: cq-out-${{ matrix.shard }}
          path: |
            out/cq-*.json.gz
            out/cq-report-*.json
          if-no-files-found: warn
          retention-days: 30
```

- [ ] **Step 2: Run** — `.venv/Scripts/python -m pytest tests/test_every_workflow_names_the_exchange.py -q` — Expected: PASS.
- [ ] **Step 3: Commit** — with Task 7 (the test that reads it lives there).

### Task 7: Dispatch and collect over every account (`cq_search`)

**Files:**
- Create: `tradingagents/cq_search.py`, `tests/test_cq_search.py`

**Interfaces:**
- Consumes: `forecast_v2_daily.fleets_now/market`, `cloud_sweep.split_coins/sync_fleet/origin_fleet/_gh`, `pro_search.read_json_parts`, `cpw_search.coverage`, `positions_view.fmt_when`, `stores.V1.home`.
- Produces: `dispatch(label=None, *, coins=None, luck="", search="500,100,10", base=5.0, timeframes=..., state_name="state.json", force=False, now=None) -> state`, `redo(state_name, repo)`, `collect(state_name) -> {"label", "runs", "roots", "coverage"}`, `progress(stage=None, *, run=None, **extra)`, `home() -> Path`, `quiet_hours(now)`, `title_of(label)`, `STATE`.

- [ ] **Step 1: Write the failing tests** — `tests/test_cq_search.py`:

```python
"""Starting the confluence research from this PC (tradingagents/cq_search.py
and .github/workflows/cq.yml), Oct 21, 2026: every account gets its share,
the luck coins travel with their own coins, a refused share is redone by
itself, a late-listed run is adopted, the nightly hours refuse a dispatch,
a refused share is named as not reached, the progress file says where
Prompt 1 stands, and the workflow takes exactly what the dispatch sends."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pytest

from tradingagents import cloud_sweep as cs, cq_search as cqs, forecast_v2_daily as fd

ROOT = Path(__file__).resolve().parent.parent
NOON = dt.datetime(2026, 10, 22, 12, 0).timestamp()
ONE_AM = dt.datetime(2026, 10, 22, 1, 0).timestamp()


def _fleet(monkeypatch, tmp_path, fail=()):
    started = []

    def start(repo, inputs):
        if repo in fail:
            raise RuntimeError("could not create workflow dispatch event: HTTP 502")
        started.append((repo, dict(inputs)))
        return 1000 + len(started)

    monkeypatch.setattr(cqs, "home", lambda: tmp_path)
    monkeypatch.setattr(cqs, "_start", start)
    monkeypatch.setattr(cqs, "_runs", lambda repo, limit=10: [])
    monkeypatch.setattr(fd, "fleets_now", lambda: (["a/x", "b/x", "c/x"], []))
    monkeypatch.setattr(cs, "origin_fleet", lambda: "a/x")
    monkeypatch.setattr(cs, "sync_fleet", lambda repo: "")
    return started


COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "NVDA"]


def test_every_account_gets_its_share_and_its_own_luck_coins(monkeypatch, tmp_path):
    started = _fleet(monkeypatch, tmp_path)
    st = cqs.dispatch("p", coins=COINS, luck="BTC,NVDA", now=NOON)
    assert [r for r, _ in started] == ["a/x", "b/x", "c/x"]
    dealt = sorted(c for _r, i in started for c in i["coin_list"].split(","))
    assert dealt == sorted(c + "_USDT" for c in COINS)
    for _repo, inputs in started:
        mine = {c.replace("_USDT", "") for c in inputs["coin_list"].split(",")}
        luck = {c for c in inputs["luck"].split(",") if c}
        assert luck == mine & {"BTC", "NVDA"}
        assert inputs["search"] == "500,100,10" and inputs["label"].startswith("p · ")
    assert st["coins"] == 6 and not st["refused"]
    prog = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert prog["stage"].startswith("dispatched state.json: 3 run(s)")
    assert prog["runs"]["state"]["runs"] == {"a/x": 1001, "b/x": 1002, "c/x": 1003}


def test_all_means_every_coin_is_luck_searched(monkeypatch, tmp_path):
    started = _fleet(monkeypatch, tmp_path)
    cqs.dispatch("p", coins=COINS, luck="all", now=NOON)
    assert {i["luck"] for _r, i in started} == {"all"}


def test_the_nightly_hours_refuse_a_dispatch(monkeypatch, tmp_path):
    started = _fleet(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="12:45am and 5:00am"):
        cqs.dispatch("p", coins=COINS, now=ONE_AM)
    assert started == []
    cqs.dispatch("p", coins=COINS, now=ONE_AM, force=True)
    assert len(started) == 3


def test_a_refused_share_is_started_again_by_itself(monkeypatch, tmp_path):
    started = _fleet(monkeypatch, tmp_path, fail=("b/x",))
    st = cqs.dispatch("p", coins=COINS, now=NOON)
    assert set(st["runs"]) == {"a/x", "c/x"} and st["refused"][0].startswith("b/x:")
    mine = st["dealt"]["b/x"]
    started.clear()
    monkeypatch.setattr(cqs, "_start", lambda repo, inputs: started.append((repo, dict(inputs)))
                        or 2001)
    got = cqs.redo(cqs.STATE, "b/x")
    assert started == [("b/x", mine)] and got["runs"]["b/x"]["run"] == 2001
    assert got["refused"] == []
    with pytest.raises(ValueError, match="already has run"):
        cqs.redo(cqs.STATE, "b/x")


def test_a_dispatch_github_listed_late_is_adopted_not_doubled(monkeypatch, tmp_path):
    started = _fleet(monkeypatch, tmp_path, fail=("b/x",))
    st = cqs.dispatch("p", coins=COINS, now=NOON)
    late = dt.datetime.fromtimestamp(st["started"] + 120, dt.timezone.utc).isoformat()
    title = cqs.title_of(st["dealt"]["b/x"]["label"])
    monkeypatch.setattr(cqs, "_runs", lambda repo, limit=10: [
        {"databaseId": 777, "displayTitle": title, "createdAt": late}] if repo == "b/x" else [])
    started.clear()
    assert cqs.redo(cqs.STATE, "b/x")["runs"]["b/x"]["run"] == 777 and started == []


def test_a_refused_share_is_named_as_not_reached_never_a_smaller_board(monkeypatch, tmp_path):
    _fleet(monkeypatch, tmp_path, fail=("b/x",))
    st = cqs.dispatch("p", coins=COINS, now=NOON)
    root = tmp_path / "run-x"
    root.mkdir()
    done = [c for r in st["runs"].values() for c in r["coin_list"]]
    (root / "cq-report-0.json").write_text(json.dumps(
        {"report": [{"coin": c.replace("_USDT", ""), "tf": "1h", "tried": 9} for c in done]}),
        encoding="utf-8")
    monkeypatch.setattr(cqs, "_gh", lambda *a, **k: json.dumps({"status": "completed"}))
    monkeypatch.setattr(cqs, "download", lambda run, repo: root)
    cov = cqs.collect(cqs.STATE)["coverage"]
    assert cov["board"] == 6 and cov["reached"] == 4
    assert sorted(cov["not_reached"]) == sorted(
        c.replace("_USDT", "") for c in st["dealt"]["b/x"]["coin_list"].split(","))
    prog = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert prog["stage"].startswith("collected state.json: 4 of 6 coin(s)")


def test_an_unreadable_progress_file_is_kept_aside_never_overwritten(monkeypatch, tmp_path):
    monkeypatch.setattr(cqs, "home", lambda: tmp_path)
    (tmp_path / "progress.json").write_text("{not json", encoding="utf-8")
    cqs.progress("pilot dispatched")
    kept = list(tmp_path.glob("progress.unreadable-*.json"))
    assert kept and kept[0].read_text(encoding="utf-8") == "{not json"
    assert json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))["stage"] == \
        "pilot dispatched"


def test_the_workflow_takes_exactly_what_the_dispatch_sends():
    text = (ROOT / ".github" / "workflows" / "cq.yml").read_text(encoding="utf-8")
    block = text.split("inputs:", 1)[1].split("permissions:", 1)[0]
    names = re.findall(r"^      ([a-z_]+):\s*$", block, flags=re.M)
    assert len(names) <= 10                      # GitHub allows exactly ten
    assert set(names) == {"shards", "timeframes", "coin_list", "base", "label", "luck", "search"}
    assert "TA_VENUE: gate" in text and "timeout-minutes: 350" in text
    assert "python .github/scripts/cq_shard.py" in text and "cq-out-${{ matrix.shard }}" in text
    for env in ("COIN_LIST", "TFS", "LUCK", "SEARCH", "BASE_MARGIN", "SHARD", "SHARDS"):
        assert f"          {env}: " in text, env


def test_the_collect_counts_searched_skipped_cut_and_failed_apart(monkeypatch, tmp_path):
    """"40 ok" counted 8 pairs that were never searched (the pilot's first
    half): searched, skipped with why, cut by the deadline and failed are four
    different things and each is named."""
    _fleet(monkeypatch, tmp_path)
    cqs.dispatch("p", coins=["BTC", "NVDA", "SOL", "XAU"], now=NOON)
    root = tmp_path / "run-1001"            # each run unpacks into its own folder
    root.mkdir()
    (root / "cq-report-0.json").write_text(json.dumps({"report": [
        {"coin": "BTC", "tf": "4h", "tried": 7000, "stop": "patience"},
        {"coin": "NVDA", "tf": "4h", "why": "only 48 days: 30+ tuning days must come before the 120 check"},
        {"coin": "SOL", "tf": "4h", "tried": 900, "stop": "deadline"},
        {"coin": "XAU", "tf": "4h", "error": "RuntimeError: planted"}]}), encoding="utf-8")
    monkeypatch.setattr(cqs, "_gh", lambda *a, **k: json.dumps({"status": "completed"}))

    def download(run, repo):
        (tmp_path / f"run-{run}").mkdir(exist_ok=True)
        return tmp_path / f"run-{run}"

    monkeypatch.setattr(cqs, "download", download)
    cov = cqs.collect(cqs.STATE)["coverage"]
    assert cov["searched"] == 2 and cov["deadline"] == ["SOL 4h"]
    assert cov["skipped"] == ["NVDA 4h: only 48 days: 30+ tuning days must come before the 120 check"]
    assert cov["pairs_failed"] == ["XAU 4h: RuntimeError: planted"] and "pairs_ok" not in cov
    prog = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert "2 searched (1 cut by the deadline), 1 skipped, 1 failed" in prog["stage"]
```

- [ ] **Step 2: Run** — `.venv/Scripts/python -m pytest tests/test_cq_search.py -q` — Expected: FAIL, `ImportError` (the workflow test passes once Task 6's file exists).
- [ ] **Step 3: Implement** — `tradingagents/cq_search.py`:

```python
"""THE CONFLUENCE RESEARCH (Prompt 1), started from this PC (Oct 21, 2026).

The machines run .github/workflows/cq.yml (.github/scripts/cq_shard.py); this
module deals the board between EVERY GitHub account that can run now (three
since Oct 21, 2026 - the 40-machine rule, CLAUDE.md) and starts one run on
each, brings every machine's results home beside the store (G:, never the
system drive), and keeps ~/.tradingagents/cq/progress.json, which a new chat
told "resume Prompt 1" reads first. Design:
docs/superpowers/specs/2026-10-21-confluence-research-design.md.

    python -m tradingagents.cq_search dispatch [label] [--coins A,B] [--luck all|A,B]
                                      [--search 500,100,10] [--state NAME] [--force]
    python -m tradingagents.cq_search redo <state-name> <owner/repo>
    python -m tradingagents.cq_search collect [state-name]
    python -m tradingagents.cq_search progress

Never dispatched between 12:45am and 5:00am (this PC's clock): the nightly
room re-test (1:00am) and backtest update (1:31am) need every machine;
`--force` is for a person who knows they are not running.
"""
from __future__ import annotations

import datetime as _dt
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

WORKFLOW = "cq.yml"
SHARDS = 20                       # machines per account (MACHINES_PER_ACCOUNT)
TIMEFRAMES = "15m,30m,1h,4h,1d"
SEARCH = "500,100,10"
ARTIFACTS = ("cq-out-*",)
STATE = "state.json"
QUIET = ((0, 45), (5, 0))         # the nightly jobs' hours: no dispatch


def home() -> Path:
    """Beside the v1 store's folder on the store's drive."""
    from tradingagents import stores

    p = Path(stores.V1.home) / "cq"
    p.mkdir(parents=True, exist_ok=True)
    return p


def title_of(label: str) -> str:
    """The run-name cq.yml gives a dispatch - how its run is found."""
    return f"Confluence research · {label}"


def _gh(*args: str, timeout: int = 120) -> str:
    from tradingagents import cloud_sweep as cs

    return cs._gh(*args, timeout=timeout)


def _runs(repo: str, limit: int = 10) -> list:
    return json.loads(_gh("run", "list", "--repo", repo, "--workflow", WORKFLOW,
                          "--limit", str(limit), "--json", "databaseId,displayTitle,createdAt"))


def _listed(repo: str, title: str, since: float) -> int | None:
    """A run of `title` on `repo` created at or after `since`, or None: GitHub
    can take a dispatch and list it late, and a run nobody adopts is twenty
    machines measuring coins nobody collects."""
    for r in _runs(repo, 30):
        if str(r.get("displayTitle", "")).strip() != title:
            continue
        made = _dt.datetime.fromisoformat(str(r["createdAt"]).replace("Z", "+00:00")).timestamp()
        if made >= since - 5:
            return int(r["databaseId"])
    return None


def _start(repo: str, inputs: dict) -> int:
    """Start cq.yml on `repo` and return ITS run id, found by its title."""
    want = title_of(inputs["label"])
    before = {int(r["databaseId"]) for r in _runs(repo)}
    args = ["workflow", "run", WORKFLOW, "--repo", repo]
    for k, v in inputs.items():
        args += ["-f", f"{k}={v}"]
    _gh(*args)
    for _ in range(45):
        time.sleep(2)
        for r in _runs(repo):
            if int(r["databaseId"]) not in before and str(r["displayTitle"]).strip() == want:
                return int(r["databaseId"])
    raise RuntimeError(f"the {WORKFLOW} run on {repo} ({want}) did not appear within 90 seconds")


def quiet_hours(now: float | None = None) -> bool:
    """Between 12:45am and 5:00am on this PC's clock."""
    t = _dt.datetime.fromtimestamp(time.time() if now is None else now)
    m = t.hour * 60 + t.minute
    (h0, m0), (h1, m1) = QUIET
    return h0 * 60 + m0 <= m < h1 * 60 + m1


def _luck_for(luck: str, pile: list) -> str:
    """One account's share of the luck coins: "all", or the named coins in its pile."""
    if luck.strip().lower() == "all":
        return "all"
    want = {c.strip().upper().replace("_USDT", "") for c in luck.split(",") if c.strip()}
    return ",".join(c.replace("_USDT", "") for c in pile if c.replace("_USDT", "") in want)


def _save(state_name: str, state: dict) -> None:
    tmp = home() / f"{state_name}.tmp"
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(home() / state_name)


def progress(stage: str | None = None, *, run: tuple | None = None, **extra) -> dict:
    """~/.tradingagents/cq/progress.json, merged and swapped whole: where
    Prompt 1 stands (`stage`, with a dated log line), each run's ids and coins
    (`runs`), and what the reader found. An unreadable file is kept aside,
    never overwritten."""
    from tradingagents.positions_view import fmt_when

    p = home() / "progress.json"
    cur: dict = {"prompt": 1, "runs": {}, "log": []}
    if p.exists():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
        except Exception:                                      # noqa: BLE001
            p.replace(p.with_name(f"progress.unreadable-{int(time.time())}.json"))
    now = time.time()
    if stage:
        cur["stage"] = stage
        cur.setdefault("log", []).append(f"{fmt_when(now)} {stage}")
    if run:
        cur.setdefault("runs", {})[run[0]] = run[1]
    cur.update(extra)
    cur["updated"] = fmt_when(now)
    tmp = p.with_name("progress.tmp")
    tmp.write_text(json.dumps(cur, indent=1, default=str), encoding="utf-8")
    tmp.replace(p)
    return cur


def dispatch(label: str | None = None, *, coins: list | None = None, luck: str = "",
             search: str = SEARCH, base: float = 5.0, timeframes: str = TIMEFRAMES,
             state_name: str = STATE, force: bool = False, now: float | None = None) -> dict:
    """Deal the board (the whole market, or `coins`) between every account
    that can run now (round robin, cloud_sweep.split_coins) and start one run
    on each. An account that refuses, or cannot be brought up to this code,
    is NAMED and the others still run; its share is kept for `redo`."""
    from tradingagents import cloud_sweep as cs, forecast_v2_daily as fd
    from tradingagents.positions_view import fmt_when

    if quiet_hours(now) and not force:
        raise RuntimeError("not dispatched: between 12:45am and 5:00am the nightly room "
                           "re-test and backtest update need every machine")
    ready, refused = fd.fleets_now()
    if not ready:
        raise RuntimeError("no GitHub account can run the research: " + "; ".join(refused))
    board = (sorted({c if c.endswith("_USDT") else f"{c}_USDT" for c in coins}) if coins
             else fd.market())
    piles = cs.split_coins(board, len(ready))
    t0 = time.time()
    label = label or fmt_when(t0)
    origin = cs.origin_fleet()
    runs, named, dealt = {}, list(refused), {}
    for k, (repo, pile) in enumerate(zip(ready, piles, strict=False)):
        if not pile:
            continue
        inputs = {"shards": str(min(SHARDS, len(pile))), "timeframes": timeframes,
                  "coin_list": ",".join(pile), "base": f"{base:g}",
                  "label": f"{label} · {k + 1} of {len(ready)}",
                  "luck": _luck_for(luck, pile), "search": search}
        dealt[repo] = inputs
        if repo != origin:
            drift = cs.sync_fleet(repo)
            if drift:
                named.append(f"{repo}: not brought up to this code ({drift})")
                continue
        try:
            runs[repo] = {"run": _start(repo, inputs), "coins": len(pile),
                          "label": inputs["label"], "coin_list": list(pile)}
        except Exception as exc:                               # noqa: BLE001
            named.append(f"{repo}: {str(exc)[:160]}")
    state = {"label": label, "started": t0, "started_at": fmt_when(t0), "base": base,
             "coins": len(board), "luck": luck, "search": search, "timeframes": timeframes,
             "runs": runs, "refused": named, "dealt": dealt}
    _save(state_name, state)
    progress(f"dispatched {state_name}: {len(runs)} run(s), {len(board)} coin(s)",
             run=(Path(state_name).stem, {"state": state_name, "label": label,
                                          "runs": {r: v["run"] for r, v in runs.items()},
                                          "refused": named, "coins": len(board)}))
    return state


def redo(state_name: str, repo: str) -> dict:
    """Start ONE account's share again by itself - the account GitHub refused,
    never the whole run. An account that already has a run is refused by
    name: two runs would measure its coins twice."""
    from tradingagents import cloud_sweep as cs

    state = json.loads((home() / state_name).read_text(encoding="utf-8"))
    if repo in state.get("runs", {}):
        raise ValueError(f"{repo} already has run {state['runs'][repo]['run']} in {state_name}")
    inputs = dict((state.get("dealt") or {}).get(repo) or {})
    if not inputs:
        raise ValueError(f"{state_name} dealt no share to {repo}")
    pile = inputs["coin_list"].split(",")
    run = _listed(repo, title_of(inputs["label"]), float(state.get("started") or 0))
    if run is None:
        if repo != cs.origin_fleet():
            drift = cs.sync_fleet(repo)
            if drift:
                raise RuntimeError(f"{repo}: not brought up to this code ({drift})")
        run = _start(repo, inputs)
    state.setdefault("runs", {})[repo] = {"run": run, "coins": len(pile),
                                          "label": inputs["label"], "coin_list": pile}
    state["refused"] = [x for x in state.get("refused", []) if not x.startswith(repo + ":")]
    _save(state_name, state)
    return state


def download(run: int, repo: str) -> Path:
    """One run's artifacts, unpacked in THIS RUN'S OWN folder under home() -
    the store's drive - emptied first."""
    root = home() / f"run-{int(run)}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    cmd = ["gh", "run", "download", str(int(run)), "-R", repo, "-D", str(root)]
    for p in ARTIFACTS:
        cmd += ["-p", p]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=3600)
    return root


def coverage(board: list, report: list) -> dict:
    """What the machines did, out loud (CLAUDE.md rule 20): the coins of the
    board no machine reached, then every coin + timeframe as exactly one of
    searched (and of those, cut by the deadline), skipped with why (too young,
    no stop/target paying 2:1) or failed - each skipped, cut and failed one
    NAMED. "ok" counted the skipped ones as done (review, Oct 22, 2026: 40
    "ok" in the pilot's first half, 32 searched)."""
    from tradingagents import cpw_search as cpw

    base = cpw.coverage(board, report)
    base.pop("pairs_ok", None)
    pairs = [e for e in report if e.get("tf") not in (None, "*") and not e.get("error")]
    searched = [e for e in pairs if not e.get("why")]
    base.update(searched=len(searched),
                deadline=[f"{e['coin']} {e['tf']}" for e in searched if e.get("stop") == "deadline"],
                skipped=[f"{e['coin']} {e['tf']}: {e['why']}" for e in pairs if e.get("why")])
    return base


def collect(state_name: str = STATE) -> dict:
    """Bring a run home (every account) and say what it measured: the
    folders, and the coverage - coins no machine reached and every failed
    pair, NAMED (CLAUDE.md rule 20)."""
    from tradingagents import pro_search as ps

    state = json.loads((home() / state_name).read_text(encoding="utf-8"))
    unfinished = []
    for repo, r in state["runs"].items():
        st = json.loads(_gh("run", "view", str(r["run"]), "--repo", repo, "--json", "status"))
        if st.get("status") != "completed":
            unfinished.append(f"{repo} run {r['run']} is {st.get('status')}")
    if unfinished:
        raise RuntimeError("not collected, still running: " + "; ".join(unfinished))
    roots = [download(int(r["run"]), repo) for repo, r in state["runs"].items()]
    dealt = state.get("dealt") or {}
    board = sorted({c for x in dealt.values() for c in str(x.get("coin_list", "")).split(",") if c})
    report = ps.read_json_parts(roots, "cq-report-*.json", "report")
    summary = {"label": state.get("label"),
               "runs": {k: v["run"] for k, v in state["runs"].items()},
               "roots": [str(r) for r in roots], "coverage": coverage(board, report)}
    stem = Path(state_name).stem
    (home() / f"{stem}-collected.json").write_text(json.dumps(summary, indent=1),
                                                    encoding="utf-8")
    cov = summary["coverage"]
    progress(f"collected {state_name}: {cov['reached']} of {cov['board']} coin(s); coin+"
             f"timeframes: {cov['searched']} searched ({len(cov['deadline'])} cut by the "
             f"deadline), {len(cov['skipped'])} skipped, {len(cov['pairs_failed'])} failed "
             f"(each named in {stem}-collected.json)",
             run=(stem, {"state": state_name, "label": state.get("label"),
                         "runs": summary["runs"], "collected": f"{stem}-collected.json",
                         "reached": cov["reached"], "board": cov["board"]}))
    return summary


def _arg(args: list, flag: str, default=None):
    if flag in args:
        i = args.index(flag)
        val = args[i + 1]
        del args[i:i + 2]
        return val
    return default


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "dispatch":
        coins = _arg(a, "--coins")
        luck = _arg(a, "--luck", "")
        srch = _arg(a, "--search", SEARCH)
        state = _arg(a, "--state", STATE)
        force = "--force" in a
        a = [x for x in a if x != "--force"]
        print(json.dumps(dispatch(a[1] if len(a) > 1 else None,
                                  coins=coins.split(",") if coins else None, luck=luck,
                                  search=srch, state_name=state, force=force), indent=2))
    elif a and a[0] == "redo":
        print(json.dumps(redo(a[1], a[2]), indent=2))
    elif a and a[0] == "collect":
        print(json.dumps(collect(a[1] if len(a) > 1 else STATE), indent=2))
    elif a and a[0] == "progress":
        print((home() / "progress.json").read_text(encoding="utf-8"))
    else:
        print("usage: python -m tradingagents.cq_search dispatch [label] [--coins A,B] "
              "[--luck all|A,B] [--search 500,100,10] [--state NAME] [--force] | "
              "redo <state-name> <owner/repo> | collect [state-name] | progress")
```

- [ ] **Step 4: Run** — same command — Expected: PASS.
- [ ] **Step 5: Commit** — `.github/workflows/cq.yml tradingagents/cq_search.py tests/test_cq_search.py`, push (cq.yml must be on every account's main before a dispatch: `sync_fleet` brings the forks up).

### Task 8: The reader and THE FIRST CHECK (`cq_report`)

**Files:**
- Create: `tradingagents/cq_report.py`, `tests/test_cq_report.py`

**Interfaces:**
- Consumes: the out files (Task 5), `pro_search.files`, `cq_search.home/progress/STATE` (Task 7).
- Produces: `results(roots) -> {"meta", "coins"}`, `prefee_r(part, sl_pct, notional=100)`, `after_fee_r(...)`, `t_quantile(p, df)`, `first_check(coins, notional=100, min_coins=10, min_trades=10) -> {"verdict": "go" | "stop", "why", "coins", "pairs", "rows", "thin", "note", ...}`, `summary(coins, report=None)`, `report_states(states)`.

- [ ] **Step 1: Write the failing tests** — `tests/test_cq_report.py`:

```python
"""The confluence research's reader (tradingagents/cq_report.py), Oct 21,
2026: profit before fees in R, the t quantile, THE FIRST CHECK (go, stop,
and not enough evidence is a stop), and joining the machines' files."""
from __future__ import annotations

import gzip
import json

import pytest

from tradingagents import cq_report as cr


def test_profit_before_fees_adds_back_every_round_trip_paid():
    # 10 trades, -$1.00 after costs, 2.5% of round trips paid on a $100
    # position = +$1.50 before fees; a 0.5% stop = $0.50 an R
    assert cr.prefee_r([10, 4, -1.0, 2.5], 0.5) == pytest.approx(0.3)
    assert cr.after_fee_r([10, 4, -1.0, 2.5], 0.5) == pytest.approx(-0.2)
    assert cr.prefee_r([0, 0, 0.0, 0.0], 0.5) is None


def test_the_t_quantile_is_students():
    assert cr.t_quantile(0.95, 9) == pytest.approx(1.833, abs=0.001)
    assert cr.t_quantile(0.95, 29) == pytest.approx(1.699, abs=0.001)
    assert cr.t_quantile(0.95, 1000) == pytest.approx(1.646, abs=0.001)


def _coin(real_tst, luck_tst, sl=0.5):
    def search(tst, name):
        return {"tried": 100, "final": "2",
                "picks": {"2": {"cand": [name, sl, 2.0, 2, [30, 12, 0.0, 6.9],
                                         [10, 4, 0.0, 2.3], tst]}}}
    return {"tfs": {"1h": {"search": search(real_tst, "cq_fl00-ev"),
                           "luck": search(luck_tst, "cq_rn00070")}}}


def test_the_first_check_goes_on_only_when_real_beats_random_before_fees():
    ahead = {f"C{k}": _coin([20, 9, 2.0 + 0.1 * (k % 3), 4.6], [20, 6, -3.0, 4.6])
             for k in range(12)}
    fc = cr.first_check(ahead)
    assert fc["verdict"] == "go" and fc["pairs"] == 12 and fc["low90"] > 0
    level = {f"C{k}": _coin([20, 7, -1.0 + (k % 2), 4.6], [20, 7, -1.0 + ((k + 1) % 2), 4.6])
             for k in range(12)}
    assert cr.first_check(level)["verdict"] == "stop"


def test_too_few_pairs_is_not_evidence_and_not_evidence_is_a_stop():
    few = {f"C{k}": _coin([20, 9, 5.0, 4.6], [20, 6, -3.0, 4.6]) for k in range(5)}
    fc = cr.first_check(few)
    assert fc["verdict"] == "stop" and "not enough evidence" in fc["why"]
    assert cr.first_check({})["verdict"] == "stop"


def test_a_coin_without_test_trades_or_a_luck_search_is_left_out_by_count():
    coins = {"A": _coin([0, 0, 0.0, 0.0], [20, 6, -3.0, 4.6]),
             "B": {"tfs": {"1h": {"search": _coin([20, 9, 2.0, 4.6], [1, 0, 0, 0])["tfs"]["1h"]
                                  ["search"]}}}}
    assert cr.first_check(coins)["pairs"] == 0


def test_the_machines_files_are_joined_and_a_coin_measured_twice_keeps_the_fuller_copy(tmp_path):
    for k, (tried, extra) in enumerate(((50, "X"), (90, "Y"))):
        d = tmp_path / f"m{k}"
        d.mkdir()
        body = {"version": "cq1", "coins": {"BTC": {"tfs": {"1h": {"search": {"tried": tried}}}},
                                            extra: {"tfs": {}}}}
        with gzip.open(d / f"cq-{k}.json.gz", "wt", encoding="utf-8") as fh:
            json.dump(body, fh)
    (tmp_path / "m0" / "cq-0.json.gz.tmp").write_text("cut", encoding="utf-8")
    got = cr.results([tmp_path / "m0", tmp_path / "m1"])
    assert got["meta"]["version"] == "cq1"
    assert got["coins"]["BTC"]["tfs"]["1h"]["search"]["tried"] == 90
    assert set(got["coins"]) == {"BTC", "X", "Y"}


def test_the_same_coin_from_two_runs_keeps_every_timeframe(tmp_path):
    """The pilot ran in two halves (4h+1d, then 15m/30m/1h): one coin arrives
    from two runs with different timeframes, and both halves must stay."""
    for k, (tf, tried) in enumerate((("4h", 50), ("1h", 70))):
        d = tmp_path / f"run{k}"
        d.mkdir()
        with gzip.open(d / f"cq-{k}.json.gz", "wt", encoding="utf-8") as fh:
            json.dump({"version": "cq1", "coins": {"BTC": {"kind": "crypto", "tfs": {
                tf: {"search": {"tried": tried}}}}}}, fh)
    got = cr.results([tmp_path / "run0", tmp_path / "run1"])
    assert set(got["coins"]["BTC"]["tfs"]) == {"4h", "1h"}
    assert got["coins"]["BTC"]["tfs"]["1h"]["search"]["tried"] == 70


def test_a_report_reads_every_run_it_is_given(monkeypatch, tmp_path):
    from tradingagents import cq_search as cqs

    monkeypatch.setattr(cqs, "home", lambda: tmp_path)
    for name, tf in (("pilot-a", "4h"), ("pilot-b", "1h")):
        d = tmp_path / f"run-{name}"
        d.mkdir()
        with gzip.open(d / "cq-0.json.gz", "wt", encoding="utf-8") as fh:
            json.dump({"version": "cq1", "coins": {"ETH": {"tfs": {tf: {"search": {"tried": 9}}}}}}, fh)
        (tmp_path / f"{name}-collected.json").write_text(json.dumps(
            {"label": name, "roots": [str(d)], "runs": {}}), encoding="utf-8")
    rep = cr.report_states(["pilot-a.json", "pilot-b.json"])
    assert rep["summary"]["coins"] == 1 and set(rep["summary"]["by_tf"]) == {"4h", "1h"}
    assert (tmp_path / "pilot-a+pilot-b-report.json").exists()


def _many(tfs, real_tst, luck_tst, sl=0.5):
    """One coin measured on several timeframes, the same picks on each."""
    c = _coin(real_tst, luck_tst, sl)["tfs"]["1h"]
    return {"tfs": dict.fromkeys(tfs, c)}


def test_a_coins_timeframes_count_once(monkeypatch):
    """15m, 30m and 1h of one coin trade the same price path over the same
    test days: the coin is the unit of evidence, never the coin + timeframe."""
    three = {f"C{k}": _many(["15m", "30m", "1h", "4h"], [20, 9, 2.0 + 0.1 * k, 4.6], [20, 6, -3.0, 4.6])
             for k in range(3)}
    fc = cr.first_check(three)
    assert fc["pairs"] == 12 and fc["coins"] == 3
    assert fc["verdict"] == "stop" and "3 coins" in fc["why"]


def test_a_thin_pair_is_left_out_and_named():
    coins = {f"C{k}": _coin([20, 9, 2.0, 4.6], [20, 6, -3.0, 4.6]) for k in range(11)}
    coins["THIN"] = _coin([6, 3, 2.0, 1.4], [20, 6, -3.0, 4.6])
    fc = cr.first_check(coins)
    assert fc["coins"] == 11 and fc["pairs"] == 11
    assert fc["thin"] == ["THIN 1h: 6 real / 20 random test trades"]


def test_the_first_check_says_what_before_fees_still_pays():
    fc = cr.first_check({f"C{k}": _coin([20, 9, 2.0, 4.6], [20, 6, -3.0, 4.6]) for k in range(12)})
    assert "half-spread" in fc["note"]


def test_the_report_reads_the_money_the_machines_measured_at(monkeypatch, tmp_path):
    """$10 x 20x = a $200 position: 10 trades, -$1.00, 5.0% of round trips
    paid = +$9.00 before fees, a 0.5% stop = $1.00 an R -> 0.4R a trade."""
    from tradingagents import cq_search as cqs

    monkeypatch.setattr(cqs, "home", lambda: tmp_path)
    d = tmp_path / "run-x"
    d.mkdir()
    with gzip.open(d / "cq-0.json.gz", "wt", encoding="utf-8") as fh:
        json.dump({"version": "cq1", "base": 10.0, "lev": 20,
                   "coins": {"ETH": _coin([10, 4, -1.0, 2.5], [10, 4, -1.0, 2.5])}}, fh)
    (tmp_path / "x-collected.json").write_text(json.dumps({"label": "x", "roots": [str(d)],
                                                           "runs": {}}), encoding="utf-8")
    rep = cr.report_states(["x.json"])
    assert rep["first_check"]["rows"][0]["real"] == pytest.approx(0.4)


def test_the_summary_counts_skipped_and_failed_beside_searched():
    coins = {"BTC": _coin([20, 9, 2.0, 4.6], [20, 6, -3.0, 4.6])}
    report = [{"coin": "BTC", "tf": "1h", "tried": 100, "stop": "patience"},
              {"coin": "NVDA", "tf": "1h", "why": "only 48 days: 30+ tuning days must come first"},
              {"coin": "XAU", "tf": "1h", "error": "RuntimeError: planted"},
              {"coin": "SOL", "tf": "1h", "tried": 40, "stop": "deadline"}]
    got = cr.summary(coins, report)["by_tf"]["1h"]
    assert got["searched"] == 1 and got["skipped"] == ["NVDA: only 48 days: 30+ tuning days must come first"]
    assert got["failed"] == ["XAU: RuntimeError: planted"] and got["deadline"] == ["SOL"]
```

- [ ] **Step 2: Run** — `.venv/Scripts/python -m pytest tests/test_cq_report.py -q` — Expected: FAIL, `ImportError`.
- [ ] **Step 3: Implement** — `tradingagents/cq_report.py`:

```python
"""THE CONFLUENCE RESEARCH'S READER (Prompt 1, Oct 21, 2026): what the
machines found, and THE FIRST CHECK. Design:
docs/superpowers/specs/2026-10-21-confluence-research-design.md.

THE FIRST CHECK, the prompt's only early stop: on the test days - which the
search never read - does the real search's final pick make more per trade
BEFORE fees than the random search's final pick on the same coin and
timeframe? Before fees = each trade's whole charged round trip added back
(both fees and both fills). Per trade in R (one R = the stop), so a coin with
a 2% stop and one with a 0.4% stop weigh alike. A pick's trades are not
independent of each other, so a pick's average is the observation; the
difference real minus random is taken per coin + timeframe and AVERAGED PER
COIN (a coin's timeframes share its price path over the same test days, so
the coin is the unit of evidence); the low end of its 90% range (Student t,
n - 1 degrees of freedom over the coins) must be above zero. Fewer than
MIN_COINS coins is not evidence, and not evidence is a stop. A pick with
fewer than MIN_TEST_TRADES test trades is left out and named.

    python -m tradingagents.cq_report [state-name ...]   (several = one result)
"""
from __future__ import annotations

import gzip
import json
import math
import statistics
import sys
from pathlib import Path

MIN_COINS = 10            # coins with a real and a random pick: fewer is not evidence
MIN_TEST_TRADES = 10      # test-day trades a pick needs on each side to count
HALF_SPREAD_NOTE = ("Before fees adds back every round trip each trade was charged (both fees "
                    "and both fills), but an entry bought on a minute with a book reading "
                    "(the newest ~45 days) still pays its half-spread inside the fill price; "
                    "real and random picks pay it alike.")


def _tried(out: dict) -> int:
    return int((out.get("search") or {}).get("tried") or 0)


def results(roots) -> dict:
    """Every machine's out/cq-*.json.gz joined: {"meta": the run's settings,
    "coins": {coin: record}}. Joined per coin AND timeframe: one coin arrives
    from two runs that measured different timeframes (the pilot ran 4h+1d,
    then 15m/30m/1h) and keeps both; a coin + timeframe measured twice
    (claimed again after a machine died) keeps the copy whose search tried the
    most candidates."""
    from tradingagents import pro_search as ps

    meta: dict = {}
    coins: dict = {}
    for f in ps.files(roots, "cq-*.json.gz"):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            d = json.load(fh)
        meta = meta or {k: v for k, v in d.items() if k != "coins"}
        for coin, rec in (d.get("coins") or {}).items():
            have = coins.setdefault(coin, {**{k: v for k, v in rec.items() if k != "tfs"},
                                           "tfs": {}})
            for tf, out in (rec.get("tfs") or {}).items():
                if tf not in have["tfs"] or _tried(out) > _tried(have["tfs"][tf]):
                    have["tfs"][tf] = out
    return {"meta": meta, "coins": coins}


def prefee_r(part, sl_pct: float, notional: float = 100.0) -> float | None:
    """Profit per trade BEFORE fees, in R: (profit $ + the round trips paid,
    as $ of the position) / trades / (the stop, as $ of the position)."""
    t, _w, p, cost = part[:4]
    if not t or not sl_pct:
        return None
    return (float(p) + float(cost) * notional / 100.0) / t / (float(sl_pct) * notional / 100.0)


def after_fee_r(part, sl_pct: float, notional: float = 100.0) -> float | None:
    t, _w, p, _cost = part[:4]
    if not t or not sl_pct:
        return None
    return float(p) / t / (float(sl_pct) * notional / 100.0)


def t_quantile(p: float, df: int) -> float:
    """Student's t quantile by the Cornish-Fisher expansion (no scipy here):
    1.833 for 0.95 at 9 degrees of freedom, within 0.001 from 5 up."""
    z = statistics.NormalDist().inv_cdf(p)
    v = float(df)
    g1 = (z ** 3 + z) / 4
    g2 = (5 * z ** 5 + 16 * z ** 3 + 3 * z) / 96
    g3 = (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / 384
    g4 = (79 * z ** 9 + 776 * z ** 7 + 1482 * z ** 5 - 1920 * z ** 3 - 945 * z) / 92160
    return z + g1 / v + g2 / v ** 2 + g3 / v ** 3 + g4 / v ** 4


def _final(search: dict | None):
    if not search or not search.get("final"):
        return None
    return search["picks"][search["final"]]["cand"]


def first_check(coins: dict, notional: float = 100.0, min_coins: int = MIN_COINS,
                min_trades: int = MIN_TEST_TRADES) -> dict:
    """Real final pick against random final pick, per coin + timeframe, on the
    test days, before fees, then AVERAGED PER COIN: a coin's timeframes trade
    one price path over the same test days, so the coin is the unit of
    evidence (review, Oct 22, 2026). Go only when the low end of the 90% range
    of the coins' differences is above zero over at least `min_coins` coins.
    A pair with fewer than `min_trades` test trades on either side is left
    out and named (a handful of trades is noise; set before the second half's
    numbers were seen). The per-pair figures ride beside and never decide."""
    rows, thin = [], []
    for coin, rec in sorted(coins.items()):
        for tf, out in sorted((rec.get("tfs") or {}).items()):
            real, luck = _final(out.get("search")), _final(out.get("luck"))
            if real is None or luck is None:
                continue
            if int(real[6][0]) < min_trades or int(luck[6][0]) < min_trades:
                thin.append(f"{coin} {tf}: {real[6][0]} real / {luck[6][0]} random test trades")
                continue
            a, b = prefee_r(real[6], real[1], notional), prefee_r(luck[6], luck[1], notional)
            rows.append({"coin": coin, "tf": tf, "real": round(a, 4), "random": round(b, 4),
                         "diff": round(a - b, 4), "real_name": real[0], "random_name": luck[0],
                         "real_trades": real[6][0], "random_trades": luck[6][0],
                         "real_after_fee": round(after_fee_r(real[6], real[1], notional), 4)})
    per: dict = {}
    for x in rows:
        per.setdefault(x["coin"], []).append(x)
    by_coin = {c: {"diff": statistics.fmean(v["diff"] for v in xs),
                   "real": statistics.fmean(v["real"] for v in xs),
                   "random": statistics.fmean(v["random"] for v in xs), "pairs": len(xs)}
               for c, xs in per.items()}
    n = len(by_coin)
    out = {"coins": n, "pairs": len(rows), "rows": rows, "thin": thin, "min_coins": min_coins,
           "min_trades": min_trades, "notional": notional, "note": HALF_SPREAD_NOTE,
           "by_coin": {c: {k: round(v, 4) if isinstance(v, float) else v for k, v in d.items()}
                       for c, d in by_coin.items()}}
    if n < 2:
        out.update(verdict="stop", why=f"only {n} coin(s) have a real and a random pick with "
                                       f"{min_trades}+ test-day trades each: not evidence")
        return out
    d = [v["diff"] for v in by_coin.values()]
    mean, sd = statistics.fmean(d), statistics.stdev(d)
    t = t_quantile(0.95, n - 1)
    low, high = mean - t * sd / math.sqrt(n), mean + t * sd / math.sqrt(n)
    pdiff = [x["diff"] for x in rows]
    pt = t_quantile(0.95, len(pdiff) - 1)
    pm, psd = statistics.fmean(pdiff), statistics.stdev(pdiff)
    out.update(mean_diff=round(mean, 4), low90=round(low, 4), high90=round(high, 4),
               real_mean=round(statistics.fmean(v["real"] for v in by_coin.values()), 4),
               random_mean=round(statistics.fmean(v["random"] for v in by_coin.values()), 4),
               ahead=sum(v > 0 for v in d),
               pair_mean_diff=round(pm, 4),
               pair_low90=round(pm - pt * psd / math.sqrt(len(pdiff)), 4),
               pair_high90=round(pm + pt * psd / math.sqrt(len(pdiff)), 4),
               pairs_ahead=sum(x > 0 for x in pdiff),
               by_tf={tf: {"pairs": len(v), "mean_diff": round(statistics.fmean(v), 4)}
                      for tf in sorted({x["tf"] for x in rows})
                      for v in [[x["diff"] for x in rows if x["tf"] == tf]]})
    if n < min_coins:
        out.update(verdict="stop", why=f"not enough evidence: {n} coins, {min_coins} needed")
    elif low > 0:
        out.update(verdict="go", why=f"the real picks made {mean:+.3f}R a trade more than "
                                     f"random before fees, averaged per coin; the low end of "
                                     f"the 90% range is {low:+.3f}R, above zero, over {n} coins "
                                     f"({len(rows)} coin+timeframes)")
    else:
        out.update(verdict="stop", why=f"the real picks are not clearly ahead of random before "
                                       f"fees: {mean:+.3f}R a trade averaged per coin, the 90% "
                                       f"range runs {low:+.3f}R to {high:+.3f}R over {n} coins "
                                       f"({len(rows)} coin+timeframes)")
    return out


def summary(coins: dict, report: list | None = None) -> dict:
    """Per timeframe: coin+timeframes searched, skipped (each named with why),
    cut by the deadline and failed (from the machines' reports), candidates
    tried, why the searches stopped, and the final picks' payouts and
    test-day win rates - for the real search and the luck search."""
    def blank():
        return {"searched": 0, "skipped": [], "deadline": [], "failed": [], "tried": 0,
                "stop": {}, "final_payout": {}, "test_trades": 0, "test_wins": 0,
                "luck_tried": 0}

    per: dict = {}
    for rec in coins.values():
        for tf, out in (rec.get("tfs") or {}).items():
            row = per.setdefault(tf, blank())
            s = out.get("search") or {}
            row["searched"] += 1
            row["tried"] += int(s.get("tried") or 0)
            row["stop"][s.get("stop")] = row["stop"].get(s.get("stop"), 0) + 1
            row["luck_tried"] += int((out.get("luck") or {}).get("tried") or 0)
            fin = _final(s)
            if fin:
                row["final_payout"][str(fin[3])] = row["final_payout"].get(str(fin[3]), 0) + 1
                row["test_trades"] += int(fin[6][0])
                row["test_wins"] += int(fin[6][1])
    for e in report or []:
        tf = e.get("tf")
        if tf in (None, "*"):
            continue
        row = per.setdefault(tf, blank())
        if e.get("error"):
            row["failed"].append(f"{e.get('coin')}: {e['error']}")
        elif e.get("why"):
            row["skipped"].append(f"{e.get('coin')}: {e['why']}")
        elif e.get("stop") == "deadline":
            row["deadline"].append(str(e.get("coin")))
    for row in per.values():
        row["test_win_rate"] = (round(100 * row["test_wins"] / row["test_trades"], 1)
                                if row["test_trades"] else None)
    return {"coins": len(coins), "by_tf": dict(sorted(per.items()))}


def report_states(states: list) -> dict:
    """Read every collected run named (`<state>-collected.json` under
    cq_search.home()) as ONE result - the pilot's two halves together - and
    write `<stem>+<stem>-report.json` beside them."""
    from tradingagents import cq_search as cqs

    roots, labels = [], []
    for state in states:
        got = json.loads((cqs.home() / f"{Path(state).stem}-collected.json")
                         .read_text(encoding="utf-8"))
        roots += list(got["roots"])
        labels.append(got.get("label"))
    from tradingagents import pro_search as ps

    res = results(roots)
    meta = res["meta"]
    notional = float(meta.get("base") or 5.0) * float(meta.get("lev") or 20)
    report = ps.read_json_parts(roots, "cq-report-*.json", "report")
    rep = {"states": list(states), "labels": labels, "summary": summary(res["coins"], report),
           "first_check": first_check(res["coins"], notional=notional), "meta": meta}
    stem = "+".join(Path(s).stem for s in states)
    (cqs.home() / f"{stem}-report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep


if __name__ == "__main__":
    from tradingagents import cq_search as cqs

    states = sys.argv[1:] or [cqs.STATE]
    rep = report_states(states)
    fc = rep["first_check"]
    cqs.progress(f"first check ({' + '.join(Path(s).stem for s in states)}): {fc['verdict']} "
                 f"- {fc['why']}", first_check={k: v for k, v in fc.items() if k != "rows"})
    print(json.dumps({k: v for k, v in rep.items() if k != "meta"}
                     | {"first_check": {k: v for k, v in fc.items() if k != "rows"}}, indent=2))
```

- [ ] **Step 4: Run** — same command — Expected: PASS. Then the related suites once: `.venv/Scripts/python -m pytest tests/test_cq_*.py tests/test_pro_*.py tests/test_ci_scripts_use_names_that_exist.py tests/test_every_workflow_names_the_exchange.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** — both files, push.

### Task 9: The pilot, the first check, the page

No new code; every step is a command and a check.

- [ ] **Step 1: Wait for the window** — no dispatch between 12:45am and 5:00am; check the nightly jobs are not running (`gh run list --workflow research.yml --limit 3` and `--workflow sweep.yml` on each account).
- [ ] **Step 2: Dispatch, in two halves** (ruled in the ledger: the 4h/1d half fits before the 12:45am cutoff) — 4h+1d: `cq_search.dispatch('pilot 4h-1d', coins=[BTC, ETH, SOL, XRP, DOGE, BNB, LINK, AVAX, SUI, LTC, AAVE, PEPE, WIF, TAO, ENA, HYPE, XAU, NVDA, TSLA, COIN], luck='all', timeframes='1d,4h', state_name='pilot-a.json')`; after 5:00am, 15m/30m/1h with the 3 stock tokens swapped for ones old enough to search (TQQQX, MSFT, AMD): `timeframes='1h,30m,15m', state_name='pilot-b.json'`. Expected: three runs per half (one per account), `~/.tradingagents/backtest/cq/progress.json` stage "dispatched ...: 3 run(s), 20 coin(s)".
- [ ] **Step 3: Watch** — every 20-30 minutes `gh run view <id> -R <repo>`; a share GitHub refused: `... cq_search redo pilot.json <repo>`.
- [ ] **Step 4: Collect** — `.venv/Scripts/python -m tradingagents.cq_search collect pilot-a.json` (and `pilot-b.json`) — Expected: coverage names every coin not reached, and every coin + timeframe as searched (cut by the deadline), skipped with why, or failed.
- [ ] **Step 5: First check** — `.venv/Scripts/python -m tradingagents.cq_report pilot-a.json pilot-b.json` (both halves as one result) — Expected: a verdict with its numbers; send a PushNotification with it.
- [ ] **Step 6: The page** — publish the pilot results as an artifact meeting CLAUDE.md's kit (items 1-8, A-H; the trade logs come from each pick's `trades`); verify every item before publishing.
- [ ] **Step 7: Next** — go: Phase B (second stage, Prompt 2's exit walk, the full market in waves within 48 hours). Stop: report it, and both prompts stop.
