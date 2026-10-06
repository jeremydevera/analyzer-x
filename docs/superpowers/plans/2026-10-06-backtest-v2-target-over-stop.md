# Backtest v2 Keeps Only Target-Over-Stop Rows — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Backtest v2 stored strategy has a take-profit bigger than its stop-loss; rows with SL ≥ TP are replaced by the same strategy and stop with the bigger targets the grid already measures, while the rooms carry on unchanged.

**Architecture:** One rule (`backtest_report.target_over_stop`) joins the store's single keep-rule `store_keeps`. The search index (`rows_index._kept`) applies it with no exceptions; the pair-file writers (`market_sweep.save_pair_rows`, `rewrite_pair_rows`) apply it but keep any combination a room is running right now (`running_rows.combos()`), because the watcher's hourly switch-off check reads those files. Nothing GitHub measures changes; the next Backtest v2 update lands every pair through the new rule, and a one-time script cleans the pairs it does not land.

**Tech Stack:** Python 3.13, pytest, SQLite (rows index), JSON pair files; run with `.venv/Scripts/python` from `G:\analyzer-x` in Git Bash.

**Spec:** `docs/superpowers/specs/2026-10-06-backtest-v2-target-over-stop-design.md`

## Global Constraints

- The rule is **TP > SL, strictly**, on the row's own `tp` and `sl` (percent): TP 5% / SL 5% is not kept.
- Applies to Backtest v2 rows only (`res` == "1m"); v1 rows (`res` empty) are never touched.
- The flat-only rule for v2 (`sizings_for`) still applies, unchanged.
- Nothing GitHub measures changes: no edit to `.github/scripts/*`, `backtest_report.BARRIERS`, or any signal.
- Room rules, watcher thresholds and real money are out of scope.
- Rows a room is running now stay in the pair files; the index never holds a TP ≤ SL row.
- Dates printed anywhere use `positions_view.fmt_when` (`Oct 06, 2026 8:03pm`).
- Commit through `python scripts/commit_own.py -F msg.txt <paths>`; push to `origin` and `colleague` after each task.
- Never put anything below an `if __name__ == "__main__":` guard.

## Review Focus

1. **A room's settings file is mid-write or unreadable while a pair is saved** — the running set must keep that room's previous combos, not drop to empty and delete the rows the room is trading. (Task 2, `test_an_unreadable_room_keeps_its_last_known_combos`.)
2. **A watcher key that is only in `runtime_specs.json`** (not in the static `STRATEGY_SPECS`) — its combo must still be recognised as running. (Task 2, `test_a_runtime_watcher_key_is_recognised`.)
3. **Float noise in stored TP/SL** (`1.0000000001` vs `1.0`) — equal must read as equal, not as "bigger". (Task 1, `test_equal_within_rounding_is_not_bigger`.)
4. **The live results door is a long-running process on the old code** — rows it lands during the update would skip the rule. Restart it before the update. (Task 5, step 3.)
5. **A pair the update never lands** (a failed or delisted coin) keeps its old rows — cleaned by the one-time script. (Task 5, steps 7–8.)

---

### Task 1: The rule and the store's keep-rule

**Files:**
- Modify: `tradingagents/backtest_report.py` (beside `store_keeps`, ~line 244)
- Test: `tests/test_backtest_v2_keeps_target_over_stop.py` (create)

**Interfaces:**
- Produces: `backtest_report.target_over_stop(row: dict) -> bool`, `backtest_report.combo_of(row: dict) -> tuple`, `backtest_report.store_keeps(row: dict, running=frozenset()) -> bool`.
- `combo_of` returns `(coin, tf, signal, th, sl, tp)` with coin bare (no `_USDT`), th/sl/tp rounded to 3 decimals as floats — the exact tuple `running_rows.combos()` (Task 2) builds.

- [ ] **Step 1: Write the failing tests**

```python
"""Backtest v2 keeps only rows whose target is bigger than their stop.

Operator, Oct 06, 2026: "take note you will only replace the ones that has
higher sl than tp or if tp same as sl, you will change it as well example
tp=5% sl=5% / the goal is to have higher tp than sl". Spec:
docs/superpowers/specs/2026-10-06-backtest-v2-target-over-stop-design.md
"""
from __future__ import annotations

from tradingagents import backtest_report as br


def _row(sl, tp, res="1m", **kw):
    return {"coin": "GPNSTOCK", "tf": "1h", "signal": "stoch14", "th": 0.0,
            "sl": sl, "tp": tp, "sizing": "flat", "res": res, **kw}


def test_a_target_bigger_than_the_stop_is_kept():
    assert br.target_over_stop(_row(5.0, 6.0))
    assert br.store_keeps(_row(5.0, 6.0))


def test_an_equal_target_is_replaced():
    assert not br.target_over_stop(_row(5.0, 5.0))
    assert not br.store_keeps(_row(5.0, 5.0))


def test_a_stop_bigger_than_the_target_is_replaced():
    assert not br.store_keeps(_row(5.0, 4.0))


def test_equal_within_rounding_is_not_bigger():
    assert not br.target_over_stop(_row(1.0, 1.0000000001))


def test_a_v1_row_is_never_touched():
    assert br.store_keeps(_row(5.0, 4.0, res=None))
    assert br.store_keeps(_row(5.0, 5.0, res=""))


def test_the_flat_only_rule_still_applies():
    assert not br.store_keeps(_row(1.0, 2.0, sizing="martingale"))


def test_a_running_combination_is_kept_in_the_files():
    r = _row(2.0, 2.0)
    assert br.store_keeps(r, running=frozenset({br.combo_of(r)}))
    assert not br.store_keeps(r, running=frozenset())


def test_the_combination_is_coin_tf_signal_threshold_stop_target():
    r = _row(2.0, 2.5, coin="KKRSTOCK", th=0.3)
    assert br.combo_of(r) == ("KKRSTOCK", "1h", "stoch14", 0.3, 2.0, 2.5)
    assert br.combo_of({**r, "coin": "KKRSTOCK_USDT"})[0] == "KKRSTOCK"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /g/analyzer-x && .venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_backtest_v2_keeps_target_over_stop.py`
Expected: FAIL with `AttributeError: module 'tradingagents.backtest_report' has no attribute 'target_over_stop'`.

- [ ] **Step 3: Implement**

Replace `store_keeps` in `tradingagents/backtest_report.py` with:

```python
def target_over_stop(row: dict) -> bool:
    """Is the row's take-profit BIGGER than its stop-loss (both percent)?
    Strictly: TP 5% / SL 5% is not (operator, Oct 06, 2026: "you will only
    replace the ones that has higher sl than tp or if tp same as sl ... the
    goal is to have higher tp than sl"). A difference under 1e-9 is equal."""
    try:
        return float(row["tp"]) - float(row["sl"]) > 1e-9
    except (KeyError, TypeError, ValueError):
        return False


def combo_of(row: dict) -> tuple:
    """(coin, tf, signal, th, sl, tp) — one strategy on one coin, the way
    `running_rows.combos()` names what a room is running."""
    return (str(row.get("coin") or "").removesuffix("_USDT"), str(row.get("tf") or ""),
            str(row.get("signal") or ""), round(float(row.get("th") or 0), 3),
            round(float(row.get("sl") or 0), 3), round(float(row.get("tp") or 0), 3))


def store_keeps(row: dict, running=frozenset()) -> bool:
    """Does the store this row belongs to keep it? The row's own `res` names
    the store. The index files by this (`rows_index._kept`) and so does every
    write of a pair file (`market_sweep.save_pair_rows`): a v2 file that is
    written again comes back flat only, instead of carrying martingale twins
    that no measure updates any more (RCA-2026-09-25-C).

    BACKTEST v2 KEEPS ONLY TP > SL (Oct 06, 2026, spec 2026-10-06-backtest-
    v2-target-over-stop): a row whose stop is bigger than or equal to its
    target is replaced by the same strategy and stop with the bigger targets
    the grid already measures. `running` names combinations a room is trading
    now (`running_rows.combos()`): the PAIR FILES keep those, because the
    watcher's hourly switch-off check reads them there; the index is called
    without it and never holds them."""
    if str(row.get("sizing") or "flat") not in sizings_for(row.get("res")):
        return False
    if str(row.get("res") or "").strip().lower() != "1m":
        return True
    return target_over_stop(row) or (bool(running) and combo_of(row) in running)
```

- [ ] **Step 4: Run them to verify they pass**

Run: `cd /g/analyzer-x && .venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_backtest_v2_keeps_target_over_stop.py tests/test_backtest_v2_keeps_flat_only.py`
Expected: all PASS.

- [ ] **Step 5: Commit and push**

```bash
cd /g/analyzer-x && .venv/Scripts/python scripts/commit_own.py -F msg.txt tradingagents/backtest_report.py tests/test_backtest_v2_keeps_target_over_stop.py && git push -q origin main && git push -q colleague main
```
(msg.txt: `feat(backtest v2): the store keeps only rows whose target is bigger than their stop` + the operator's words + Co-Authored-By line.)

---

### Task 2: What the rooms are running now

**Files:**
- Create: `tradingagents/running_rows.py`
- Modify: `tests/conftest.py` (autouse sandbox for `running_rows.combos`)
- Test: `tests/test_backtest_v2_keeps_target_over_stop.py` (append)

**Interfaces:**
- Consumes: `backtest_report.combo_of` (Task 1), `profiles.ids()`, `profiles.path(at.SETTINGS_PATH, pid)`, `auto_trader.book_names(settings, key, coin)`, `auto_trader.merge_runtime_specs()`, `forecast_v2.spec_of(key)`.
- Produces: `running_rows.read_combos() -> frozenset[tuple]` (the real reader) and `running_rows.combos()` (what the writers call; it calls `read_combos()`) — the `combo_of` tuples of every strategy-and-coin any room has switched on (coin in `strategy_coins[key]` and at least one account in `book_names`). Cached per room on its settings file's change time.
- Modify: `tests/conftest.py` — an autouse fixture patches `running_rows.combos` to `lambda: frozenset()`, so no test depends on the operator's real rooms; the tests of the reader call `read_combos()`.

- [ ] **Step 1: Write the failing tests** (append)

```python
import json

import pytest


@pytest.fixture
def rooms(tmp_path, monkeypatch):
    from tradingagents import auto_trader as at, profiles, running_rows as rr

    paths = {"main": tmp_path / "auto_trade.json",
             "6B08FF64": tmp_path / "profiles" / "6B08FF64" / "auto_trade.json"}
    paths["6B08FF64"].parent.mkdir(parents=True)
    monkeypatch.setattr(profiles, "ids", lambda: list(paths))
    monkeypatch.setattr(profiles, "path", lambda g, pid=None: paths[pid])
    monkeypatch.setattr(at, "merge_runtime_specs", lambda: 0)
    rr._CACHE.clear()
    return paths


def _settings(path, key, coins, books=("paper",), slot_books=None):
    s = {"strategies": [key], "strategy_coins": {key: list(coins)},
         "strategy_books": {key: list(books)}}
    for c, b in (slot_books or {}).items():
        s["strategy_books"][f"{key}|{c}"] = list(b)
    path.write_text(json.dumps(s), encoding="utf-8")


def test_a_hand_picked_equal_row_main_runs_is_running(rooms):
    from tradingagents import running_rows as rr

    _settings(rooms["main"], "keltner_30m_sl2tp2", ["GPNSTOCK_USDT"])
    rooms["6B08FF64"].write_text("{}", encoding="utf-8")
    assert ("GPNSTOCK", "30m", "keltner", 0.0, 2.0, 2.0) in rr.read_combos()


def test_a_coin_switched_off_is_not_running(rooms):
    from tradingagents import running_rows as rr

    _settings(rooms["main"], "keltner_30m_sl2tp2", [])
    rooms["6B08FF64"].write_text("{}", encoding="utf-8")
    assert rr.read_combos() == frozenset()


def test_a_coin_with_no_account_is_not_running(rooms):
    from tradingagents import running_rows as rr

    _settings(rooms["main"], "keltner_30m_sl2tp2", ["GPNSTOCK_USDT"], books=())
    rooms["6B08FF64"].write_text("{}", encoding="utf-8")
    assert rr.read_combos() == frozenset()


def test_a_runtime_watcher_key_is_recognised(rooms):
    from tradingagents import running_rows as rr

    _settings(rooms["6B08FF64"], "ibs_15m_sl05tp06", ["FASTSTOCK_USDT"], books=(),
              slot_books={"FASTSTOCK_USDT": ["paper"]})
    rooms["main"].write_text("{}", encoding="utf-8")
    assert ("FASTSTOCK", "15m", "ibs", 0.0, 0.5, 0.6) in rr.read_combos()


def test_an_unreadable_room_keeps_its_last_known_combos(rooms):
    from tradingagents import running_rows as rr

    _settings(rooms["main"], "keltner_30m_sl2tp2", ["GPNSTOCK_USDT"])
    rooms["6B08FF64"].write_text("{}", encoding="utf-8")
    first = rr.read_combos()
    rooms["main"].write_text('{"strategy_coins": {', encoding="utf-8")   # mid-write
    import os
    os.utime(rooms["main"], (1, 1))
    assert rr.read_combos() == first


def test_a_missing_room_folder_is_nothing_running(rooms):
    from tradingagents import running_rows as rr

    assert rr.read_combos() == frozenset()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /g/analyzer-x && .venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_backtest_v2_keeps_target_over_stop.py -k "running or runtime or unreadable or missing or hand_picked or switched_off or no_account"`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.running_rows'`.

- [ ] **Step 3: Implement** `tradingagents/running_rows.py`, and in `tests/conftest.py` add:

```python
@pytest.fixture(autouse=True)
def _no_real_rooms_running(monkeypatch):
    """The pair-file writers keep what a room runs (running_rows.combos):
    a test must never depend on the operator's real rooms."""
    from tradingagents import running_rows
    monkeypatch.setattr(running_rows, "combos", lambda: frozenset())
```

`tradingagents/running_rows.py`:

```python
"""What every room is running right now, as Backtest v2 combinations.

The pair files keep these rows even when their target is not bigger than their
stop (backtest_report.store_keeps), because the watcher's hourly switch-off
check reads its rows from the pair files (strategy_watcher._fresh_row): a row
missing there is switched off at once, and the operator chose to leave the
rooms as they are (Oct 06, 2026, "Backtest tab only"). Spec:
docs/superpowers/specs/2026-10-06-backtest-v2-target-over-stop-design.md
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# pid -> (mtime_ns, frozenset of combos): a room whose file cannot be read
# keeps its last known combos rather than dropping to nothing
_CACHE: dict = {}


def _room_combos(settings: dict) -> frozenset:
    from tradingagents import auto_trader as at
    from tradingagents import backtest_report as br
    from tradingagents import forecast_v2 as f2

    out = set()
    for key, coins in (settings.get("strategy_coins") or {}).items():
        sp = None
        for coin in coins or ():
            if not at.book_names(settings, key, coin):
                continue
            if sp is None:
                if key not in at.STRATEGY_SPECS:
                    try:
                        at.merge_runtime_specs()
                    except Exception:                          # noqa: BLE001
                        pass
                sp = f2.spec_of(key)
            if not (sp.get("tf") and sp.get("signal") and sp.get("tp") is not None
                    and sp.get("sl") is not None):
                continue
            out.add(br.combo_of({"coin": coin, "tf": sp["tf"], "signal": sp["signal"],
                                 "th": sp.get("th") or 0.0, "sl": sp["sl"],
                                 "tp": sp["tp"]}))
    return frozenset(out)


def combos() -> frozenset:
    """What the pair-file writers call (tests patch this one, conftest.py)."""
    return read_combos()


def read_combos() -> frozenset:
    """Every (coin, tf, signal, th, sl, tp) any room has switched on now."""
    from tradingagents import auto_trader as at
    from tradingagents import profiles

    out: set = set()
    for pid in profiles.ids():
        try:
            path = Path(profiles.path(at.SETTINGS_PATH, pid))
        except ValueError:
            continue
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            _CACHE.pop(pid, None)            # no settings: the room runs nothing
            continue
        have = _CACHE.get(pid)
        if have is None or have[0] != mtime:
            try:
                settings = json.loads(path.read_text(encoding="utf-8") or "{}")
                got = _room_combos(settings if isinstance(settings, dict) else {})
            except (OSError, ValueError) as exc:
                logger.warning("running rows: %s settings unreadable (%s) - keeping its "
                               "last known strategies", pid, type(exc).__name__)
                got = have[1] if have else frozenset()
                _CACHE[pid] = (have[0] if have else -1, got)
                out |= got
                continue
            _CACHE[pid] = (mtime, got)
        out |= _CACHE[pid][1]
    return frozenset(out)
```

- [ ] **Step 4: Run them to verify they pass**

Run: `cd /g/analyzer-x && .venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_backtest_v2_keeps_target_over_stop.py`
Expected: all PASS.

- [ ] **Step 5: Commit and push** (`tradingagents/running_rows.py`, the test file).

---

### Task 3: The writers keep running rows, the index never does

**Files:**
- Modify: `tradingagents/market_sweep.py:888-902` (`save_pair_rows`) and `:943-960` (`rewrite_pair_rows`)
- Modify: `tests/test_backtest_v2_keeps_flat_only.py:156-160` (the guard's pattern)
- Test: `tests/test_backtest_v2_keeps_target_over_stop.py` (append)

**Interfaces:**
- Consumes: `backtest_report.store_keeps(row, running)`, `running_rows.combos()`.
- `rows_index._kept` stays `return br.store_keeps(r)` — no running set.

- [ ] **Step 1: Write the failing tests** (append; reuse the `index` fixture pattern from `tests/test_backtest_v2_keeps_flat_only.py`, which points `msw.ROWDIR` and the index at `tmp_path`)

```python
def test_a_pair_file_keeps_a_running_equal_row_and_drops_the_rest(tmp_path, monkeypatch):
    from tradingagents import market_sweep as msw, running_rows as rr

    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    eq, big, small = _row(2.0, 2.0, coin="GPNSTOCK", tf="30m", signal="keltner"), \
        _row(2.0, 3.0, coin="GPNSTOCK", tf="30m", signal="keltner"), \
        _row(2.0, 1.5, coin="GPNSTOCK", tf="30m", signal="keltner")
    monkeypatch.setattr(rr, "combos", lambda: frozenset({br.combo_of(eq)}))
    msw.save_pair_rows("GPNSTOCK", "30m", [eq, big, small])
    on_disk = json.loads((tmp_path / "rows" / "GPNSTOCK-30m.json").read_text())
    assert sorted(r["tp"] for r in on_disk) == [2.0, 3.0]
    # the room switches it off: the next write drops it
    monkeypatch.setattr(rr, "combos", lambda: frozenset())
    msw.merge_pair_rows("GPNSTOCK", "30m", [])
    on_disk = json.loads((tmp_path / "rows" / "GPNSTOCK-30m.json").read_text())
    assert [r["tp"] for r in on_disk] == [3.0]


def test_rewrite_pair_rows_keeps_the_same_rule(tmp_path, monkeypatch):
    from tradingagents import market_sweep as msw, running_rows as rr

    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(rr, "combos", lambda: frozenset())
    got = msw.rewrite_pair_rows("GPNSTOCK", "1h", lambda rows: [_row(5.0, 5.0), _row(5.0, 6.0)])
    assert [r["tp"] for r in got] == [6.0]


def test_the_index_never_keeps_an_equal_row_even_when_running(monkeypatch):
    from tradingagents import rows_index as ri, running_rows as rr

    r = _row(2.0, 2.0)
    monkeypatch.setattr(rr, "combos", lambda: frozenset({br.combo_of(r)}))
    assert not ri._kept(r)
    assert ri._kept(_row(2.0, 2.5))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /g/analyzer-x && .venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_backtest_v2_keeps_target_over_stop.py -k "pair_file or rewrite or index_never"`
Expected: the pair-file test FAILS (the running equal row is dropped, `[3.0] != [2.0, 3.0]`).

- [ ] **Step 3: Implement**

In `save_pair_rows`, replace `rows = [r for r in rows if br.store_keeps(r)]` with:

```python
    from tradingagents import running_rows as _running

    # TP > SL for Backtest v2 (Oct 06, 2026), except what a room is running
    # now: the watcher's switch-off check reads those rows HERE
    running = _running.combos()
    rows = [r for r in rows if br.store_keeps(r, running)]
```

In `rewrite_pair_rows`, compute `running = _running.combos()` (same import) BEFORE taking `_pair_lock`, and change the filter to `br.store_keeps(r, running)`.

In `tests/test_backtest_v2_keeps_flat_only.py::test_the_index_and_the_files_read_one_rule` change the second assert to
`assert "br.store_keeps(r, running)" in inspect.getsource(msw.save_pair_rows)` and add
`assert "br.store_keeps(r, running)" in inspect.getsource(msw.rewrite_pair_rows)`.

- [ ] **Step 4: Run the new tests and the keep-rule guards**

Run: `cd /g/analyzer-x && .venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_backtest_v2_keeps_target_over_stop.py tests/test_backtest_v2_keeps_flat_only.py`
Expected: all PASS.

- [ ] **Step 5: Run the whole suite and fix fixtures that fed TP ≤ SL v2 rows**

Run: `cd /g/analyzer-x && .venv/Scripts/python -m pytest -q -p no:cacheprovider -x --ignore=tests/test_api.py 2>&1 | tail -30` (then the whole suite without `-x`, in the background).
Known failures before this change (do not fix here): `tests/test_api.py` job start, `tests/test_api_trade.py` wallet, `tests/test_tests_cannot_write_the_real_home.py` for other modules.
For each NEW failure: if the test is not about TP ≤ SL rows, change its fixture's v2 row to a target bigger than its stop (e.g. `"sl": 3.0, "tp": 1.0` → `"sl": 1.0, "tp": 3.0` only where the test reads rows back through `save_pair_rows`, `merge_pair_rows`, `land_rows` or the index); if the test asserts that a TP ≤ SL v2 row is stored, it is pinning the old rule — update it to the new one and say so in the commit.

- [ ] **Step 6: Commit and push** (`tradingagents/market_sweep.py`, both test files, any fixture files changed).

---

### Task 4: CLAUDE.md records the rule

**Files:**
- Modify: `CLAUDE.md` (a new MANDATORY section after "Backtest v2 is the v1 engine in its own folder")

- [ ] **Step 1: Add the section**

```markdown
## Backtest v2 keeps only TP > SL (MANDATORY — Oct 06, 2026)

The operator, after six rooms lost $889.10 on 4,375 practice trades (average
win +$0.80, average loss −$1.04 on $100: about $0.23 of fees comes off every
win and goes on top of every loss): *"take note you will only replace the ones
that has higher sl than tp or if tp same as sl, you will change it as well
example tp=5% sl=5% / the goal is to have higher tp than sl"* (the asks before
it, in order, are in the spec).

* **One rule, `backtest_report.store_keeps`:** a Backtest v2 row is kept only
  when TP > SL strictly (`target_over_stop`). v1 is untouched.
* **Replaced, never measured differently.** The grid measures every stop with
  every target, so each stop's bigger targets already exist; nothing GitHub
  measures changed, and the rule is reversible in one line.
* **The index never holds a TP ≤ SL row; the pair files keep what a room is
  running now** (`running_rows.combos()`), because the watcher's switch-off
  check reads the pair files and a missing row is switched off at once — the
  operator chose "Backtest tab only" for the rooms.
* Guard: `tests/test_backtest_v2_keeps_target_over_stop.py`.
Spec: `docs/superpowers/specs/2026-10-06-backtest-v2-target-over-stop-design.md`.
```

- [ ] **Step 2: Commit and push** (`CLAUDE.md`).

---

### Task 5: Roll it out and prove the store is clean (press-and-watch)

**Files:**
- Create: `scripts/v2_target_over_stop_cleanup.py`

- [ ] **Step 1: Write the cleanup script** (rewrites only pair files that still hold a row the rule drops, then re-files them)

```python
"""One-time: clean the Backtest v2 pair files the update did not land.

Run: .venv/Scripts/python scripts/v2_target_over_stop_cleanup.py [--dry]
It re-launches itself in the v2 store's environment."""
import json
import os
import subprocess
import sys

from tradingagents import market_sweep as msw, stores

if msw.FINE_TF != "1m":
    sys.exit(subprocess.call([sys.executable, __file__, *sys.argv[1:]],
                             env={**os.environ, **stores.V2.env_for()}))

from tradingagents import backtest_report as br, rows_index as ri, running_rows  # noqa: E402


def main() -> int:
    dry = "--dry" in sys.argv
    running = running_rows.combos()
    dirty = []
    for f in sorted(msw.ROWDIR.glob("*.json")):
        coin, _, tf = f.stem.rpartition("-")
        try:
            rows = json.loads(f.read_text(encoding="utf-8") or "[]")
        except (OSError, ValueError):
            print(f"unreadable, left alone: {f.name}")
            continue
        drop = sum(1 for r in rows if not br.store_keeps(r, running))
        if drop:
            dirty.append((coin, tf, drop))
    print(f"{len(dirty)} pair file(s) still hold rows the rule drops "
          f"({sum(d for _, _, d in dirty):,} rows)")
    if dry:
        return 0
    for i, (coin, tf, _) in enumerate(dirty, 1):
        msw.rewrite_pair_rows(coin, tf, lambda rows: rows)
        ri.index_pair(msw.ROWDIR / f"{coin}-{tf}.json")
        print(f"{i}/{len(dirty)} {coin} {tf} cleaned and re-filed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Warn the operator, then restart the API only** (`start.py`'s API spawn, as on Oct 06, 2026 10:08am; the UI stays up) and confirm `GET /api/health` answers 200 and `staleness.report()` shows the API current.

- [ ] **Step 3: Stop the live results door by its exact pid** (the process whose command line is `python -m tradingagents.live_ingest serve`), so the update's dispatch (`live_ingest.ensure`) opens a new door on the new code.

- [ ] **Step 4: Press UPDATE ALL BACKTESTS (v2) the way the button does**: `db_jobs.start("btupdate_v2", daily_update.spec())` — check first that no disk job and no sweep on either account is running (`db_jobs.disk_holder`, `daily_update._github_busy()`), and that the pid it returns is new.

- [ ] **Step 5: Watch it to the end** (press-and-watch): both accounts dispatched, both runs green, the collect lands, the v2 job files the pairs. Note every failure by coin and timeframe.

- [ ] **Step 6: Dry-run the cleanup**: `.venv/Scripts/python scripts/v2_target_over_stop_cleanup.py --dry` — prints how many pair files still hold dropped rows.

- [ ] **Step 7: Run the cleanup** without `--dry` if any remain.

- [ ] **Step 8: Prove it** — on the v2 index: `SELECT count(*) FROM rows WHERE tp <= sl` must be 0, and `SELECT count(*) FROM rows` reported beside the count before; open Stored strategies on Backtest v2 and confirm TP% > SL% on the first page sorted by win rate.

- [ ] **Step 9: Commit and push** the script, and report Before | After in numbers.
