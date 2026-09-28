# Strategy Watcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Once a day, switch on the Backtest v2 rows that won most over the last 30 days with TP ≥ SL. Every hour, switch off any running row the watcher added that has stopped working. Practice account only.

**Architecture:** A pure decision module (`watcher_policy`) is fed by two readers. One reads the backtest store: fresh 30-day figures from the v2 pair files, found through the v2 row index. The other reads the practice record: exits since the row was switched on. A thin orchestrator (`strategy_watcher`) runs on the API supervisor's 30 s tick, next to `daily_update`, and writes the settings file through a compare-and-swap. A new row needs its strategy key's recipe. The recipe is generated from the row (`strategy_keys`), stored in a runtime registry, and merged into `STRATEGY_SPECS` by `load_settings()`, so the runner sees it without a restart. It ships in **PREVIEW** mode first: every decision is written and shown, but nothing is armed until the operator flips it to **ACT**.

**Tech Stack:** Python 3.13, FastAPI (`tradingagents/api.py`), SQLite row index (`tradingagents/rows_index.py`), Next.js/React (`webapp/`), pytest.

**Spec:** the operator's own words, in order (docs/OPERATOR-ASKS.md):
- Sep 28, 2026: *"can i create an ai where it will decide which strategy to deploy? my preference is tp is greater than sl and have good winrate for pass 30 days / the reason is some strategies will not work after 30 days so i need watcher that will undeploy a strategy if its not working anymore and will deploy new ones"*
- *"i have millions of strategy will the watcher be able to update each row of backtest?"*: answered by `daily_update` (shipped, a3dbfb239a0d). GitHub refreshes the rows daily; the watcher only reads them.
- *"Okay did you created the logic where it will deploy ids that has good winrate for past 30 days and will undeploy those who has bad winrate over past 30 days"*
- *"Don built it yet do a plan first"*
- The operator's numbers, Sep 28, 2026, replacing the plan's first defaults: *"What i want is add it deployed if the trade is 90% above / Then undeploy if 90% below for past 30 days / I want tp is greater than sl / Then minimum trade for past 30 days should be 20"*

## Global Constraints

- Practice account only. The watcher never writes `"real"` into any book and never touches a slot whose book holds `"real"`. Real money is out of scope.
- It only switches off slots it switched on itself (`settings["watcher_slots"]`). The operator's hand-picked rows are judged and REPORTED, never touched, unless `manage_hand_picked` is set.
- Every date printed anywhere goes through `positions_view.fmt_when` (Python) / `fmtWhen` (TS): `Sep 28, 2026 3:21pm`.
- Every decision names the row id (`#R6FRS3KD`), coin, timeframe, signal, TP, SL and the numbers it was judged on (deploy-by-id, rule 22).
- Flat $5 at 20x, matching every v2 row (v2 keeps flat only; the runner stakes flat, rule 19).
- Every cost check the runner makes at entry is also made before arming: `auto_trader.edge_check(key, symbol, 5.0)`. `block` and `unknown` both refuse (rules 11, 12), and so does a stop past `STOP_LIQ_CEILING` of the liquidation distance.
- A test never writes outside its own `tmp_path`, and `tick()` never runs under `PYTEST_CURRENT_TEST`.
- Commit and push after each task (CLAUDE.md). A commit stages only this plan's files; other sessions are editing the same tree.
- Nothing is defined below an `if __name__ == "__main__":` in any module.

The operator's numbers (Sep 28, 2026) and the remaining defaults, all in `watcher_policy.DEFAULTS` and editable on screen:

| setting | default | why |
|---|---|---|
| `on_winrate` | **90** | operator: *"add it deployed if the trade is 90% above"*: 90.0% and up is switched on |
| `off_winrate` | **90** | operator: *"undeploy if 90% below for past 30 days"*: under 90.0% is switched off. One line, no gap between on and off; `cooldown_days` is what stops a row at 89.9% / 90.1% flipping daily |
| `min_trades` | **20** | operator: *"minimum trade for past 30 days should be 20"* |
| `tp_rule` | **`">"`** | operator: *"I want tp is greater than sl"*: an equal 1.2%/1.2% pair is refused |
| `profit_floor` | 0.0 | a row winning often and losing money is not "good" |
| `max_slots` | 100 | watcher-run slots at once (the runner held 537 on Sep 24) |
| `max_per_coin` | 3 | GPNSTOCK alone held 135 slots on Sep 24 |
| `max_new_per_day` | 20 | a bad day of data cannot arm 100 rows at once |
| `judge_after` | 10 | practice trades before the practice record is WARNED about on screen. It never switches a row off: the operator gave one off rule, the 30-day win rate |
| `off_streak` | 4 | practice losses in a row that are WARNED about on screen (same reason) |
| `cooldown_days` | 7 | a switched-off id may not come back for a week |
| `fresh_hours` | 36 | a row whose pair file ends earlier is not "the last 30 days" |

## Review Focus

1. **The operator saves settings on screen between the watcher's read and its write.** Their change must survive. `strategy_watcher._write_settings` re-reads and retries on a changed file (Task 6, `test_a_save_on_screen_between_read_and_write_is_kept`).
2. **A row is switched off while its practice trade is open.** The trade finishes normally, and next morning's pass must not re-arm the same id just because it still ranks. The cooldown covers it (Task 3, `test_a_switched_off_id_waits_out_its_cooldown`; Task 6, `test_off_leaves_the_open_practice_trade_to_finish`).
3. **The row index is older than the pair files.** Measured today: the top v2 rows by win rate read *measured through Sep 22, 2026*, while their pair files end Sep 28, 2026 12:30pm (3,656 of 5,006 pairs stale in the index, paused behind `export_v2`). The watcher decides on the PAIR FILE's figures, skips rows older than `fresh_hours`, and says how many (Task 4, `test_a_stale_index_row_is_judged_on_its_pair_file`).
4. **The runner was already running when a new key was registered.** If the runner never learns the key, the slot trades nothing and nothing says so. `load_settings()` merges the registry, and `run_cycle` calls `load_settings()` (Task 2, `test_the_runner_path_sees_a_key_registered_after_import`).
5. **Any slot with `"real"` in its book, or deployed by hand.** Never switched on or off by the watcher (Task 6, `test_it_never_touches_real_money_or_a_hand_pick`).

---

## File Structure

| file | new/modify | one responsibility |
|---|---|---|
| `tradingagents/strategy_keys.py` | new | row → strategy key + spec, the rule the Sep 24/25/27 blocks were generated by |
| `tradingagents/runtime_specs.py` | new | the runtime registry file of keys the watcher added |
| `tradingagents/auto_trader.py` | modify | `load_settings()` merges the registry (one call, mtime-cached) |
| `tradingagents/watcher_policy.py` | new | pure: which candidates to arm, which running slots to switch off, and why |
| `tradingagents/watcher_candidates.py` | new | v2 index query + pair-file freshness check |
| `tradingagents/watcher_results.py` | new | practice record per slot since it was switched on |
| `tradingagents/strategy_watcher.py` | new | the pass: read, decide, gate, write, log, bell |
| `tradingagents/api.py` | modify | supervisor tick + `GET/POST /api/trade/watcher` |
| `webapp/src/lib/api.ts` | modify | `watcher()`, `watcherSet()` and the `Watcher` type |
| `webapp/src/components/trade/WatcherPanel.tsx` | new | the panel on the Trade screen |
| `webapp/src/components/trade/AutoTradeScreen.tsx` | modify | mount the panel under the deployed grid |
| `CLAUDE.md` | modify | the rule, in the operator's words |

---

### Task 1: Row → strategy key and spec

**Files:**
- Create: `tradingagents/strategy_keys.py`
- Test: `tests/test_strategy_keys_match_every_generated_block.py`

**Interfaces:**
- Produces: `key_for(row: dict) -> str`, `spec_for(row: dict) -> dict`, `pct_code(pct: float) -> str`, `THRESHOLD_SIGNALS = ("mom6", "mom15", "fade15")`, `TF_SPEC = {"15m": ("Min15", 900), "30m": ("Min30", 1800), "1h": ("Min60", 3600), "4h": ("Hour4", 14400), "1d": ("Day1", 86400)}`. Here `row` is a v2 row dict with `signal, tf, th, sl, tp` (sl/tp and th in PERCENT, as the index stores them).

- [ ] **Step 1: Write the failing test.** It round-trips EVERY key of the three generated blocks, so the rule is pinned by 349 real keys, not by examples.

```python
"""A row's strategy key and spec are the rule the Sep 24/25/27 blocks used.

Those blocks say "GENERATED FROM THE MEASURED ROWS, never typed". The watcher
has to generate the same way, unattended, so the rule is pinned against every
key they hold: 309 + 38 + 2."""
import re

import pytest

from tradingagents import auto_trader as at, strategy_keys as sk
from tradingagents.local_history import _sig_of

BLOCKS = {**at._OPERATORS_V2_SEP24, **at._OPERATORS_V2_SEP25,
          **at._OPERATORS_V2_SEP27}
TF_OF = {v[0]: k for k, v in sk.TF_SPEC.items()}


def _row_of(key: str, spec: dict) -> dict:
    sig = _sig_of(key)
    return {"signal": sig, "tf": TF_OF[spec["interval"]],
            "th": round(spec.get("threshold", 0) * 100, 4),
            "sl": round(spec["sl"] * 100, 4), "tp": round(spec["tp"] * 100, 4)}


@pytest.mark.parametrize("key", sorted(BLOCKS))
def test_every_generated_key_is_regenerated_exactly(key):
    spec = BLOCKS[key]
    row = _row_of(key, spec)
    assert sk.key_for(row) == key
    assert sk.spec_for(row) == spec


@pytest.mark.parametrize("pct,code", [(1.2, "12"), (0.5, "05"), (2.0, "2"),
                                      (2.5, "25"), (0.3, "03"), (18.0, "18p0"),
                                      (20.0, "20p0"), (12.5, "12p5")])
def test_percent_codes(pct, code):
    assert sk.pct_code(pct) == code


def test_a_threshold_rule_carries_its_threshold_in_the_name():
    row = {"signal": "fade15", "tf": "4h", "th": 0.8, "sl": 3.0, "tp": 4.0}
    assert sk.key_for(row) == "fade15_4h_t08_sl3tp4"
    assert sk.spec_for(row)["threshold"] == pytest.approx(0.008)


def test_a_rule_without_a_threshold_has_none():
    row = {"signal": "bb20", "tf": "15m", "th": 0.0, "sl": 1.2, "tp": 1.2}
    assert "threshold" not in sk.spec_for(row)
    assert not re.search(r"_t\d", sk.key_for(row))


def test_a_timeframe_the_runner_cannot_trade_is_refused():
    with pytest.raises(ValueError):
        sk.key_for({"signal": "bb20", "tf": "1m", "th": 0, "sl": 1, "tp": 1})
```

- [ ] **Step 2: Run it, expect FAIL** (`ModuleNotFoundError: tradingagents.strategy_keys`).

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_strategy_keys_match_every_generated_block.py`

- [ ] **Step 3: Implement.**

```python
"""A Backtest v2 row -> the strategy key and spec the runner trades it by.

The rule the Sep 24/25/27 blocks in auto_trader.py were generated by ("GENERATED
FROM THE MEASURED ROWS, never typed"): tp/sl are the row's own percents over
100, interval/bar_seconds come from its timeframe, and `threshold` is the row's
th for the rules that read one, in the NAME too (`_t08_`). A percent of 10 or
more is written `12p0`, because `tp12` already means 1.2%.
"""
from __future__ import annotations

TF_SPEC = {"15m": ("Min15", 900), "30m": ("Min30", 1800),
           "1h": ("Min60", 3600), "4h": ("Hour4", 14400),
           "1d": ("Day1", 86400)}
THRESHOLD_SIGNALS = ("mom6", "mom15", "fade15")


def pct_code(pct: float) -> str:
    s = f"{float(pct):g}"
    if float(pct) >= 10:
        return s.replace(".", "p") if "." in s else s + "p0"
    return s.replace(".", "")


def key_for(row: dict) -> str:
    tf = str(row["tf"])
    if tf not in TF_SPEC:
        raise ValueError(f"the runner cannot trade timeframe {tf!r}")
    parts = [str(row["signal"]), tf]
    if row["signal"] in THRESHOLD_SIGNALS:
        parts.append("t" + pct_code(row["th"]))
    parts.append(f"sl{pct_code(row['sl'])}tp{pct_code(row['tp'])}")
    return "_".join(parts)


def spec_for(row: dict) -> dict:
    interval, secs = TF_SPEC[str(row["tf"])]
    spec = {"interval": interval, "bar_seconds": secs,
            "tp": round(float(row["tp"]) / 100, 6),
            "sl": round(float(row["sl"]) / 100, 6)}
    if row["signal"] in THRESHOLD_SIGNALS:
        spec["threshold"] = round(float(row["th"]) / 100, 6)
    return spec
```

- [ ] **Step 4: Run, expect PASS.** If any existing key fails, the rule above is wrong. Fix the rule, never the test: the 349 keys are the evidence.
- [ ] **Step 5: Commit and push.** `git add tradingagents/strategy_keys.py tests/test_strategy_keys_match_every_generated_block.py`, then commit `feat(watcher): a v2 row's strategy key, regenerated exactly for all 349 generated keys`.

---

### Task 2: The runtime registry, seen by the runner without a restart

**Files:**
- Create: `tradingagents/runtime_specs.py`
- Modify: `tradingagents/auto_trader.py`, inside `load_settings()` (its first line) and at the end of the spec blocks (after `STRATEGY_ORDER = STRATEGY_ORDER + tuple(_OPERATORS_V2_SEP27)`)
- Test: `tests/test_a_watcher_key_reaches_the_runner.py`

**Interfaces:**
- Consumes: `strategy_keys.key_for / spec_for`
- Produces: `runtime_specs.PATH` (`~/.tradingagents/runtime_specs.json`), `register(key: str, spec: dict) -> str` (returns `"added"`, `"same"` or raises `ValueError` on a clash), `load() -> dict[str, dict]`, and `auto_trader.merge_runtime_specs() -> int` (the number of keys newly merged, mtime-cached).

- [ ] **Step 1: Before editing, grep for copies of the globals:** `grep -rn "from tradingagents.auto_trader import .*STRATEGY_\(ORDER\|SPECS\)" tradingagents webapp tests`. A module holding its own copy of the tuple will not see a merged key; list each one in the commit message and switch it to `at.STRATEGY_ORDER`.
- [ ] **Step 2: Write the failing test.**

```python
"""A key the watcher registers is traded by a runner that was already running.

auto_trader builds STRATEGY_SPECS once, at import. The runner imports it once
and runs for days. A key registered after that would be armed in the settings
and traded by nobody, with nothing on screen saying so (Review Focus 4)."""
import pytest

from tradingagents import auto_trader as at, runtime_specs as rs

KEY = "bb20_15m_sl07tp09"
SPEC = {"interval": "Min15", "bar_seconds": 900, "tp": 0.009, "sl": 0.007}


@pytest.fixture(autouse=True)
def _own_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "PATH", tmp_path / "runtime_specs.json")
    monkeypatch.setattr(at, "SETTINGS_PATH", tmp_path / "auto_trade.json")
    monkeypatch.setattr(at, "_RUNTIME_SEEN", {"mtime": None})
    yield
    at.STRATEGY_SPECS.pop(KEY, None)
    at.STRATEGY_ORDER = tuple(k for k in at.STRATEGY_ORDER if k != KEY)


def test_the_runner_path_sees_a_key_registered_after_import():
    assert KEY not in at.STRATEGY_SPECS
    rs.register(KEY, SPEC)
    at.load_settings()                      # what run_cycle calls every round
    assert at.STRATEGY_SPECS[KEY] == SPEC
    assert KEY in at.STRATEGY_ORDER


def test_run_cycle_reads_the_settings_every_round():
    import inspect

    body = inspect.getsource(at.run_cycle)
    assert "load_settings(" in body, "the merge rides on this call"


def test_a_committed_key_can_never_be_redefined():
    committed = next(iter(at._OPERATORS_V2_SEP24))
    with pytest.raises(ValueError):
        rs.register(committed, {**at.STRATEGY_SPECS[committed], "tp": 0.5})
    assert rs.register(committed, dict(at.STRATEGY_SPECS[committed])) == "same"


def test_the_merge_is_cached_on_the_files_mtime():
    rs.register(KEY, SPEC)
    assert at.merge_runtime_specs() == 1
    assert at.merge_runtime_specs() == 0, "every settings read must not re-read it"


def test_a_corrupt_registry_changes_nothing_and_does_not_raise(tmp_path):
    rs.PATH.write_text("not json")
    before = dict(at.STRATEGY_SPECS)
    assert at.merge_runtime_specs() == 0
    assert at.STRATEGY_SPECS == before
```

- [ ] **Step 3: Run, expect FAIL.**
- [ ] **Step 4: Implement `runtime_specs.py`.**

```python
"""Strategy keys the watcher added while the app was running.

A key is a recipe (interval, bar length, TP, SL, threshold). The committed
blocks in auto_trader.py were written by hand-run generators; the watcher
cannot commit code, so it writes here and auto_trader merges the file on every
load_settings() (mtime-cached). A key that already exists with a DIFFERENT
spec is refused: one name means one recipe, on every screen and in every book.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PATH = Path(os.path.expanduser("~/.tradingagents")) / "runtime_specs.json"


def load() -> dict:
    try:
        got = json.loads(PATH.read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def register(key: str, spec: dict) -> str:
    from tradingagents import auto_trader as at

    have = at.STRATEGY_SPECS.get(key) or load().get(key)
    if have is not None:
        if dict(have) != dict(spec):
            raise ValueError(f"{key} already means {have}, not {spec}")
        return "same"
    reg = load()
    reg[key] = dict(spec)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, sort_keys=True), encoding="utf-8")
    os.replace(tmp, PATH)
    return "added"
```

- [ ] **Step 5: In `auto_trader.py`, after the Sep 27 block:**

```python
# KEYS THE WATCHER ADDED at runtime (tradingagents/runtime_specs.py). Merged
# on every load_settings(), which run_cycle calls every round, so a runner
# started days ago trades a key registered this morning. Never overrides a
# committed key: register() refuses a clash before it is ever written.
_RUNTIME_SEEN = {"mtime": None}


def merge_runtime_specs() -> int:
    global STRATEGY_ORDER
    from tradingagents import runtime_specs as _rs

    try:
        mtime = _rs.PATH.stat().st_mtime
    except OSError:
        return 0
    if _RUNTIME_SEEN["mtime"] == mtime:
        return 0
    _RUNTIME_SEEN["mtime"] = mtime
    added = 0
    for key, spec in _rs.load().items():
        if key in STRATEGY_SPECS or not isinstance(spec, dict):
            continue
        STRATEGY_SPECS[key] = dict(spec)
        STRATEGY_ORDER = STRATEGY_ORDER + (key,)
        added += 1
    return added
```

Add `merge_runtime_specs()` as the first statement of `load_settings()`, wrapped in `try/except Exception: pass`, because a settings read must never fail on the registry.

- [ ] **Step 6: Run, expect PASS.** Then run `tests/test_nothing_is_defined_after_the_runner_entry_point*` and every test touching `load_settings`: `grep -rl load_settings tests | xargs .venv/Scripts/python -m pytest -q -p no:cacheprovider`.
- [ ] **Step 7: Commit and push:** `feat(watcher): keys registered at runtime reach a runner that is already running`.

---

### Task 3: The decisions, as pure functions

**Files:**
- Create: `tradingagents/watcher_policy.py`
- Test: `tests/test_the_watchers_decisions.py`

**Interfaces:**
- Produces:
  - `DEFAULTS: dict` (the table in Global Constraints)
  - `passes_on(row: dict, cfg: dict) -> str`: `""` when the row may be switched on, else the reason
  - `pick(candidates: list[dict], running: list[dict], cooling: dict[str, float], now: float, cfg: dict) -> list[dict]`: rows to switch on, each `{"row": row, "why": str}`. `running` holds dicts with `coin, id`; `cooling` maps id → the time it was switched off.
  - `judge(slot: dict, fresh_row: dict | None, cfg: dict) -> str`: `""` to keep, else the reason to switch off. ONLY the 30-day backtest decides (the operator's one off rule)
  - `warn(practice: dict, cfg: dict) -> str`: `""`, or a sentence for the screen about the practice record. Never switches anything off
  - `break_even(win_usd: float, loss_usd: float) -> float`, as a percent (CLAUDE.md rule 11: loss / (win + loss))

- [ ] **Step 1: Write the failing test,** with the operator's own rows and numbers.

```python
"""The watcher's two decisions, with the operator's own rows."""
import pytest

from tradingagents import watcher_policy as wp

CFG = dict(wp.DEFAULTS)
NOW = 1_790_700_000.0
# #77Y3BPFG GPNSTOCK 1h macddiv SL 0.7% / TP 1.0% flat, as the v2 index held
# it on Sep 28, 2026: 20 trades, 20W, 100%, +$15.84
R6 = {"id": "77Y3BPFG", "coin": "GPNSTOCK", "tf": "1h", "signal": "macddiv",
      "th": 0.0, "sl": 0.7, "tp": 1.0, "trades": 20, "wins": 20,
      "losses": 0, "winrate": 100.0, "profit": 15.84, "gate": "ok"}


def test_the_operators_row_passes():
    assert wp.passes_on(R6, CFG) == ""


def test_the_operators_numbers_are_the_defaults():
    assert (CFG["on_winrate"], CFG["off_winrate"], CFG["min_trades"],
            CFG["tp_rule"]) == (90.0, 90.0, 20, ">")


@pytest.mark.parametrize("change,word", [
    ({"tp": 1.0, "sl": 1.2}, "TP"), ({"winrate": 89.9}, "win"),
    ({"trades": 19}, "trades"), ({"profit": -0.01}, "profit"),
    ({"gate": "block"}, "cost")])
def test_each_floor_refuses_by_name(change, word):
    assert word in wp.passes_on({**R6, **change}, CFG)


def test_equal_barriers_are_refused_tp_must_be_wider():
    """#R6FRS3KD FASTSTOCK 15m bb20 is TP 1.2% / SL 1.2%: refused by name."""
    assert "TP" in wp.passes_on({**R6, "tp": 1.2, "sl": 1.2}, CFG)


def test_exactly_ninety_percent_is_switched_on():
    assert wp.passes_on({**R6, "winrate": 90.0}, CFG) == ""


def test_break_even_is_the_operators_62_3():
    assert wp.break_even(0.98, 1.62) == pytest.approx(62.3, abs=0.05)


def test_pick_keeps_three_per_coin_and_twenty_a_day():
    many = [{**R6, "id": f"A{i:07d}", "coin": f"C{i % 30}"} for i in range(200)]
    got = wp.pick(many, running=[], cooling={}, now=NOW, cfg=CFG)
    assert len(got) == 20
    per = {}
    for g in got:
        per[g["row"]["coin"]] = per.get(g["row"]["coin"], 0) + 1
    assert max(per.values()) <= 3


def test_pick_never_arms_an_id_already_running():
    got = wp.pick([R6], running=[{"id": "77Y3BPFG", "coin": "GPNSTOCK"}],
                  cooling={}, now=NOW, cfg=CFG)
    assert got == []


def test_a_switched_off_id_waits_out_its_cooldown():
    off_at = NOW - 6 * 86400
    assert wp.pick([R6], [], {"77Y3BPFG": off_at}, NOW, CFG) == []
    assert len(wp.pick([R6], [], {"77Y3BPFG": off_at}, NOW + 86400, CFG)) == 1


def test_pick_stops_at_max_slots_counting_what_runs():
    running = [{"id": f"R{i}", "coin": f"X{i}"} for i in range(99)]
    many = [{**R6, "id": f"B{i}", "coin": f"Y{i}"} for i in range(50)]
    assert len(wp.pick(many, running, {}, NOW, CFG)) == 1


def test_pick_takes_the_highest_win_rate_first_then_trades():
    lo = {**R6, "id": "LO", "coin": "A", "winrate": 91.0}
    hi = {**R6, "id": "HI", "coin": "B", "winrate": 95.0, "trades": 21}
    hi2 = {**R6, "id": "HI2", "coin": "C", "winrate": 95.0, "trades": 60}
    got = wp.pick([lo, hi, hi2], [], {}, NOW, {**CFG, "max_new_per_day": 2})
    assert [g["row"]["id"] for g in got] == ["HI2", "HI"]


# ---- judge: switching OFF
def test_under_ninety_percent_over_30_days_switches_it_off():
    why = wp.judge({"id": "77Y3BPFG"}, {**R6, "winrate": 89.9}, CFG)
    assert "89.9" in why and "90" in why


def test_exactly_ninety_percent_is_kept():
    assert wp.judge({"id": "x"}, {**R6, "winrate": 90.0}, CFG) == ""


def test_the_practice_record_is_shown_never_switches_it_off():
    """The operator gave ONE off rule, the 30-day win rate. A losing practice
    record is printed beside the row; the row stays on."""
    p = {"trades": 10, "wins": 6, "losses": 4, "pnl": -0.60, "streak": 4,
         "win_usd": 0.98, "loss_usd": 1.62}
    assert wp.judge({"id": "x"}, R6, CFG) == ""
    why = wp.warn(p, CFG)
    assert "-0.60" in why and "4 losses in a row" in why


def test_nine_practice_trades_are_not_enough_to_warn_about_money():
    p = {"trades": 9, "wins": 3, "losses": 6, "pnl": -5.0, "streak": 0,
         "win_usd": 0.98, "loss_usd": 1.62}
    assert wp.warn(p, CFG) == ""


def test_a_row_the_store_no_longer_holds_is_switched_off():
    assert "no longer" in wp.judge({"id": "x"}, None, CFG)
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**

```python
"""What the watcher switches on and off, and the sentence it says why.

Pure: no files, no network, no clock. Every number a decision uses arrives as
an argument, so every decision is a test."""
from __future__ import annotations

# on/off/min_trades/tp_rule are the operator's own numbers (Sep 28, 2026):
# "add it deployed if the trade is 90% above / Then undeploy if 90% below for
# past 30 days / I want tp is greater than sl / Then minimum trade for past 30
# days should be 20"
DEFAULTS = {"on_winrate": 90.0, "off_winrate": 90.0, "min_trades": 20,
            "tp_rule": ">", "profit_floor": 0.0, "max_slots": 100,
            "max_per_coin": 3, "max_new_per_day": 20, "judge_after": 10,
            "off_streak": 4, "cooldown_days": 7, "fresh_hours": 36}


def break_even(win_usd: float, loss_usd: float) -> float:
    total = float(win_usd) + float(loss_usd)
    return round(100 * float(loss_usd) / total, 1) if total > 0 else 100.0


def passes_on(row: dict, cfg: dict) -> str:
    tp, sl = float(row["tp"]), float(row["sl"])
    if cfg["tp_rule"] == ">" and not tp > sl:
        return f"TP {tp:g}% is not wider than SL {sl:g}%"
    if cfg["tp_rule"] == ">=" and not tp >= sl:
        return f"TP {tp:g}% is narrower than SL {sl:g}%"
    if float(row["winrate"]) < cfg["on_winrate"]:
        return f"win rate {row['winrate']:g}% is under {cfg['on_winrate']:g}%"
    if int(row["trades"]) < cfg["min_trades"]:
        return f"{row['trades']} trades in 30 days, fewer than {cfg['min_trades']}"
    if float(row["profit"]) <= cfg["profit_floor"]:
        return f"profit {row['profit']:+.2f} is not above {cfg['profit_floor']:+.2f}"
    if str(row.get("gate") or "") != "ok":
        return f"its cost check read {row.get('gate')!r}, not ok"
    return ""


def pick(candidates, running, cooling, now, cfg) -> list:
    held = {r["id"] for r in running}
    per_coin: dict = {}
    for r in running:
        per_coin[r["coin"]] = per_coin.get(r["coin"], 0) + 1
    room = max(0, min(cfg["max_new_per_day"], cfg["max_slots"] - len(running)))
    wait = cfg["cooldown_days"] * 86400
    out = []
    ranked = sorted(candidates, key=lambda r: (-float(r["winrate"]),
                                               -int(r["trades"]), r["id"]))
    for row in ranked:
        if len(out) >= room:
            break
        if row["id"] in held or passes_on(row, cfg):
            continue
        if now - float(cooling.get(row["id"], -1e18)) < wait:
            continue
        if per_coin.get(row["coin"], 0) >= cfg["max_per_coin"]:
            continue
        per_coin[row["coin"]] = per_coin.get(row["coin"], 0) + 1
        held.add(row["id"])
        out.append({"row": row, "why": (
            f"{row['winrate']:g}% over {row['trades']} trades in the last 30 "
            f"days, TP {row['tp']:g}% / SL {row['sl']:g}%, "
            f"{row['profit']:+.2f}")})
    return out


def judge(slot, fresh_row, cfg) -> str:
    """Switch off? Only the last 30 days of the backtest decide."""
    if fresh_row is None:
        return "the backtest store no longer holds this row"
    if float(fresh_row["winrate"]) < cfg["off_winrate"]:
        return (f"its last-30-days win rate fell to {fresh_row['winrate']:g}%, "
                f"under {cfg['off_winrate']:g}%")
    return ""


def warn(practice, cfg) -> str:
    """What the practice record says, for the screen. Never an off switch."""
    out = []
    if int(practice["streak"]) >= cfg["off_streak"]:
        out.append(f"{practice['streak']} losses in a row in practice")
    if int(practice["trades"]) >= cfg["judge_after"]:
        if float(practice["pnl"]) < 0:
            out.append(f"practice lost {practice['pnl']:+.2f} over "
                       f"{practice['trades']} trades")
        else:
            be = break_even(practice["win_usd"], practice["loss_usd"])
            rate = 100 * practice["wins"] / practice["trades"]
            if rate < be:
                out.append(f"practice won {rate:.1f}%, under its {be:.1f}% "
                           f"break-even")
    return "; ".join(out)
```

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit and push:** `feat(watcher): the switch-on and switch-off decisions, pure and named`.

---

### Task 4: Candidates with FRESH 30-day figures

**Files:**
- Create: `tradingagents/watcher_candidates.py`
- Test: `tests/test_watcher_candidates_are_fresh.py`

**Interfaces:**
- Consumes: `rows_index.using_db`, `rows_index.query` (the call `/api/v2/strategies` makes, with `tp_over_sl`, `min_winrate`, `min_trades`, `sort="winrate"`, `limit`), the v2 pair files `~/.tradingagents/v2/rows/{COIN}-{tf}.json` and `state/{COIN}-{tf}.json` (`__last_ms__`), and `backtest_report.row_code(..., res="1m")`
- Produces: `fresh_candidates(cfg: dict, *, now: float, limit: int = 3000) -> dict` returning `{"rows": [...], "asked": int, "stale": int, "gone": int, "why": str}`. Each row is the PAIR FILE's current figures plus `id`, with `measured_ms`.
- Produces: `fresh_row(row_id: str, coin: str, tf: str, *, now: float, cfg: dict) -> dict | None` (Task 6 uses it to re-judge a running slot).

- [ ] **Step 1: Read first.** Before writing, read `rows_index.query`'s signature and the API route `/api/v2/strategies` (`tradingagents/api.py`, `@app.get("/api/v2/strategies")`) to copy its exact call under `using_db`, and read how a pair file's rows are shaped (`market_sweep.pair_rows(coin, tf, root=...)`). Use `pair_rows`, never a hand-rolled JSON read. Name the exact functions in the test's docstring.
- [ ] **Step 2: Write the failing test.** Fixtures build a tiny v2 root under `tmp_path`: two pair files and a fake `query` that returns the INDEX's stale figures, pinning Review Focus 3.

```python
"""The watcher judges a row by its pair file, never by a stale index.

Measured Sep 28, 2026: the top v2 rows by win rate read measured-through
Sep 22, 2026 in the index while their pair files ended Sep 28, 2026
12:30pm, with 3,656 of 5,006 pairs stale behind export_v2. A decision on the
index's figures would be a decision on last week."""
import pytest

from tradingagents import watcher_candidates as wc, watcher_policy as wp

NOW = 1_790_700_000.0
H = 3600.0


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = {"index": [], "pairs": {}, "last_ms": {}}
    monkeypatch.setattr(wc, "_index_rows", lambda cfg, limit: list(s["index"]))
    monkeypatch.setattr(wc, "_pair_rows",
                        lambda coin, tf: list(s["pairs"].get((coin, tf), [])))
    monkeypatch.setattr(wc, "_last_ms",
                        lambda coin, tf: s["last_ms"].get((coin, tf)))
    return s


def _row(**kw):
    base = {"coin": "FASTSTOCK", "tf": "15m", "signal": "bb20", "th": 0.0,
            "sl": 1.2, "tp": 1.2, "sizing": "flat", "trades": 97, "wins": 82,
            "losses": 15, "winrate": 84.54, "profit": 63.11, "gate": "ok"}
    return {**base, **kw}


def test_a_stale_index_row_is_judged_on_its_pair_file(store):
    store["index"] = [{**_row(), "id": "R6FRS3KD"}]
    store["pairs"][("FASTSTOCK", "15m")] = [_row(winrate=61.0, wins=59)]
    store["last_ms"][("FASTSTOCK", "15m")] = (NOW - 3 * H) * 1000
    got = wc.fresh_candidates(dict(wp.DEFAULTS), now=NOW)
    assert got["rows"][0]["winrate"] == 61.0, "the pair file's figure, not the index's"


def test_a_pair_older_than_fresh_hours_is_skipped_and_counted(store):
    store["index"] = [{**_row(), "id": "R6FRS3KD"}]
    store["pairs"][("FASTSTOCK", "15m")] = [_row()]
    store["last_ms"][("FASTSTOCK", "15m")] = (NOW - 37 * H) * 1000
    got = wc.fresh_candidates(dict(wp.DEFAULTS), now=NOW)
    assert got["rows"] == [] and got["stale"] == 1
    assert "1 row" in got["why"] and "36 hours" in got["why"]


def test_a_row_gone_from_its_pair_file_is_counted_not_invented(store):
    store["index"] = [{**_row(), "id": "R6FRS3KD"}]
    store["pairs"][("FASTSTOCK", "15m")] = []
    store["last_ms"][("FASTSTOCK", "15m")] = NOW * 1000
    got = wc.fresh_candidates(dict(wp.DEFAULTS), now=NOW)
    assert got["rows"] == [] and got["gone"] == 1


def test_each_pair_file_is_read_once_however_many_rows_it_holds(store, monkeypatch):
    reads = []
    store["index"] = [{**_row(sl=s, tp=s), "id": f"X{s}"} for s in (1.2, 1.5, 2.0)]
    rows = [_row(sl=s, tp=s) for s in (1.2, 1.5, 2.0)]
    monkeypatch.setattr(wc, "_pair_rows",
                        lambda coin, tf: (reads.append((coin, tf)), rows)[1])
    store["last_ms"][("FASTSTOCK", "15m")] = NOW * 1000
    wc.fresh_candidates(dict(wp.DEFAULTS), now=NOW)
    assert reads == [("FASTSTOCK", "15m")]


def test_the_id_is_rehashed_from_the_pair_row_itself(store):
    """The id printed beside a switched-on row must be that row's own hash
    (deploy-by-id), never carried over from the index."""
    from tradingagents import backtest_report as br

    store["index"] = [{**_row(), "id": "R6FRS3KD"}]
    store["pairs"][("FASTSTOCK", "15m")] = [_row()]
    store["last_ms"][("FASTSTOCK", "15m")] = NOW * 1000
    got = wc.fresh_candidates(dict(wp.DEFAULTS), now=NOW)["rows"][0]
    assert got["id"] == br.row_code("FASTSTOCK", "15m", "bb20", 0.0, 1.2, 1.2,
                                    "flat", res="1m") == "R6FRS3KD"


def test_learned_formulas_are_left_out_by_name(store):
    store["index"] = [{**_row(signal="lx_FASTSTOCK_15m_3"), "id": "L1"}]
    got = wc.fresh_candidates(dict(wp.DEFAULTS), now=NOW)
    assert got["rows"] == [] and "learned" in got["why"]
```

- [ ] **Step 3: Run, expect FAIL.**
- [ ] **Step 4: Implement** `_index_rows`, `_pair_rows`, `_last_ms` as the three thin readers (the only functions touching disk), then `fresh_candidates` and `fresh_row`.
  - Group index rows by `(coin, tf)`; read each pair file once.
  - Match a pair row to its index row by `(signal, th, sl, tp, sizing)`.
  - Re-hash the id with `row_code(..., res="1m")`.
  - Skip `lx_`/`ml_` signals by name: they are per-coin learned formulas with their own registry (`signals_learned`), and this plan does not arm them.
  - Fill `why` from the counts: `"{n} candidates · {stale} row(s) skipped: pair file older than 36 hours · {gone} gone from their pair file"`.
- [ ] **Step 5: Run, expect PASS.** Then time it once against the real store with a script under the session scratchpad (not the repo), `wc.fresh_candidates(dict(wp.DEFAULTS), now=time.time())`, and paste the seconds and counts into the commit message. It must finish under 60 s; if it does not, lower `limit`, never skip the pair-file check.
- [ ] **Step 6: Commit and push:** `feat(watcher): candidates judged on their fresh pair files, not the stale index`.

---

### Task 5: The practice record since a row was switched on

**Files:**
- Create: `tradingagents/watcher_results.py`
- Test: `tests/test_watcher_reads_practice_since_switch_on.py`

**Interfaces:**
- Consumes: `auto_trader.ledger_since(ts)` (exit rows: `action == "exit"`, `dry_run`, `strategy`, `symbol`, `pnl_est`, `ts`), `auto_trader.book_slot(key, coin)`
- Produces: `practice(slots: dict[str, float], *, now: float) -> dict[str, dict]`. `slots` maps `book_slot` → the time the watcher switched it on. The result maps `book_slot` → `{"trades", "wins", "losses", "pnl", "streak", "win_usd", "loss_usd"}`, counted from `max(switched_on, now - 30 days)`, practice exits only. `streak` is the CURRENT unbroken run of losses at the end.

- [ ] **Step 1: Write the failing test.**

```python
"""Practice results count from the moment the watcher switched a row on."""
import pytest

from tradingagents import auto_trader as at, watcher_results as wr

NOW = 1_790_700_000.0
SLOT = "bb20_15m_sl12tp12|FASTSTOCK_USDT"


def _exit(ts, pnl, dry=True, strat="bb20_15m_sl12tp12", sym="FASTSTOCK_USDT"):
    return {"action": "exit", "dry_run": dry, "strategy": strat,
            "symbol": sym, "pnl_est": pnl, "ts": ts}


@pytest.fixture
def ledger(monkeypatch):
    rows = []
    monkeypatch.setattr(at, "ledger_since",
                        lambda ts: [r for r in rows if r["ts"] >= ts])
    return rows


def test_counts_only_after_switch_on(ledger):
    ledger += [_exit(NOW - 5000, -1.62), _exit(NOW - 100, 0.98)]
    got = wr.practice({SLOT: NOW - 1000}, now=NOW)[SLOT]
    assert (got["trades"], got["wins"], got["losses"]) == (1, 1, 0)


def test_real_money_exits_are_not_practice(ledger):
    ledger += [_exit(NOW - 10, 0.98, dry=False)]
    assert wr.practice({SLOT: NOW - 1000}, now=NOW)[SLOT]["trades"] == 0


def test_another_coin_on_the_same_key_is_not_this_row(ledger):
    ledger += [_exit(NOW - 10, -1.62, sym="KKRSTOCK_USDT")]
    assert wr.practice({SLOT: NOW - 1000}, now=NOW)[SLOT]["trades"] == 0


def test_the_streak_is_the_current_run_of_losses(ledger):
    ledger += [_exit(NOW - 50 + i, p) for i, p in
               enumerate([-1.6, 0.98, -1.6, -1.6, -1.6])]
    assert wr.practice({SLOT: NOW - 1000}, now=NOW)[SLOT]["streak"] == 3


def test_average_win_and_loss_in_dollars(ledger):
    ledger += [_exit(NOW - 30, 1.0), _exit(NOW - 20, 0.96),
               _exit(NOW - 10, -1.62)]
    got = wr.practice({SLOT: NOW - 1000}, now=NOW)[SLOT]
    assert got["win_usd"] == pytest.approx(0.98)
    assert got["loss_usd"] == pytest.approx(1.62)
    assert got["pnl"] == pytest.approx(0.34)


def test_the_window_is_never_older_than_30_days(ledger):
    ledger += [_exit(NOW - 31 * 86400, -1.62)]
    assert wr.practice({SLOT: NOW - 40 * 86400}, now=NOW)[SLOT]["trades"] == 0
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Read `ledger_since(min(start_of_each_slot))` ONCE and bucket by `book_slot(strategy, symbol)`. The ledger is large (every `gate_blocked` row), and reading it once per slot would repeat a whole-file read up to 100 times. A `pnl_est > 0` exit is a win and anything else a loss, the same rule as `strategy_stats`.
- [ ] **Step 4: Run, expect PASS.** Add a test that `ledger_since` is called exactly once for 50 slots.
- [ ] **Step 5: Commit and push:** `feat(watcher): the practice record per row, counted from its switch-on`.

---

### Task 6: The pass: read, decide, gate, write, log

**Files:**
- Create: `tradingagents/strategy_watcher.py`
- Modify: `tradingagents/api.py` (the supervisor `_watch()` loop, right after the `daily_update` block)
- Test: `tests/test_the_strategy_watcher.py`

**Interfaces:**
- Consumes: everything above, plus `auto_trader.load_settings / save_settings / edge_check / book_slot / book_names`, `notifications.record`, `positions_view.fmt_when`
- Produces:
  - `STATE = ~/.tradingagents/strategy_watcher.json`: `{"mode": "off"|"preview"|"act", "cfg": {...}, "last_on_pass": ts, "last_off_pass": ts, "cooling": {id: ts}}`, default mode `"preview"`
  - `LOG = ~/.tradingagents/strategy_watcher.jsonl`: one decision per line, `{"at", "mode", "action": "on"|"off"|"refused"|"report", "id", "coin", "tf", "signal", "tp", "sl", "why", "numbers": {...}}`
  - `consider(*, now) -> dict`, `status() -> dict` (mode, cfg, last passes, next passes, the last 50 decisions), `set_mode(mode)`, `set_cfg(partial: dict)`. `set_cfg` validates each field against `watcher_policy.DEFAULTS`' type and refuses unknown keys.
  - `settings["watcher_slots"]: {book_slot: {"id": str, "on_at": ts}}`: the watcher's own slots
  - `tick()`: never under pytest, logged when its answer changes

- [ ] **Step 1: Write the failing tests.** Fixtures replace `load_settings`/`save_settings` with an in-memory dict, `edge_check` with a table, `fresh_candidates`/`fresh_row`/`practice` with fakes, and `STATE`/`LOG` with `tmp_path`.

```python
"""One watcher pass, end to end, on an in-memory settings file."""
import pytest

from tradingagents import auto_trader as at, strategy_watcher as sw

NOW = 1_790_700_000.0
# #77Y3BPFG GPNSTOCK 1h macddiv SL 0.7% / TP 1.0%: 20 trades, 100%, +$15.84.
# Its key `macddiv_1h_sl07tp1` is in NO committed block, so arming it goes
# through the runtime registry (Task 2) exactly as a real new row would.
R6 = {"id": "77Y3BPFG", "coin": "GPNSTOCK", "tf": "1h", "signal": "macddiv",
      "th": 0.0, "sl": 0.7, "tp": 1.0, "sizing": "flat", "trades": 20,
      "wins": 20, "losses": 0, "winrate": 100.0, "profit": 15.84,
      "gate": "ok", "measured_ms": NOW * 1000}
SLOT = "macddiv_1h_sl07tp1|GPNSTOCK_USDT"
# #R6FRS3KD FASTSTOCK 15m bb20 1.2%/1.2%, 84.54%: one of the operator's OWN
# rows (committed key), used where a hand-picked row is needed
HAND = "bb20_15m_sl12tp12|FASTSTOCK_USDT"


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = {"settings": {"strategies": [], "strategy_coins": {},
                      "strategy_books": {}, "strategy_margins": {},
                      "strategy_sizing": {}, "enabled": False},
         "saves": 0, "edge": {}, "cands": [R6], "fresh": {}, "practice": {},
         "bells": []}
    monkeypatch.setattr(sw, "STATE", tmp_path / "w.json")
    monkeypatch.setattr(sw, "LOG", tmp_path / "w.jsonl")
    monkeypatch.setattr(at, "load_settings",
                        lambda: {k: (dict(v) if isinstance(v, dict) else v)
                                 for k, v in w["settings"].items()})

    def _save(s):
        w["saves"] += 1
        w["settings"] = s
        return []

    monkeypatch.setattr(at, "save_settings", _save)
    monkeypatch.setattr(at, "edge_check", lambda key, sym, margin=5.0, **k:
                        {"verdict": w["edge"].get(sym, "ok"), "reason": "t"})
    monkeypatch.setattr(sw, "_candidates", lambda cfg, now: {
        "rows": list(w["cands"]), "why": "fake", "stale": 0, "gone": 0})
    monkeypatch.setattr(sw, "_fresh_row", lambda rid, coin, tf, now, cfg:
                        w["fresh"].get(rid, R6))
    monkeypatch.setattr(sw, "_practice", lambda slots, now: {
        s: w["practice"].get(s, {"trades": 0, "wins": 0, "losses": 0,
                                 "pnl": 0.0, "streak": 0, "win_usd": 0.0,
                                 "loss_usd": 0.0}) for s in slots})
    monkeypatch.setattr(sw, "_register", lambda key, spec: "added")
    from tradingagents import notifications as nt

    monkeypatch.setattr(nt, "record",
                        lambda *a, **k: (w["bells"].append((a, k)), 1)[1])
    return w


def test_preview_decides_and_writes_nothing(world):
    got = sw.consider(now=NOW)
    assert world["saves"] == 0
    assert [d["action"] for d in got["decisions"]] == ["on"]
    assert got["decisions"][0]["mode"] == "preview"


def test_act_arms_practice_only_and_names_the_id(world):
    sw.set_mode("act")
    sw.consider(now=NOW)
    s = world["settings"]
    assert s["strategy_coins"]["macddiv_1h_sl07tp1"] == ["GPNSTOCK_USDT"]
    assert at.book_names(s, "macddiv_1h_sl07tp1", "GPNSTOCK_USDT") == ["paper"]
    assert s["strategy_res"][SLOT] == "1m"
    assert s["watcher_slots"][SLOT]["id"] == "77Y3BPFG"
    assert s["enabled"] is False, "the live switch is never turned on"


def test_a_blocked_cost_check_refuses_by_id(world):
    sw.set_mode("act")
    world["edge"]["GPNSTOCK_USDT"] = "block"
    got = sw.consider(now=NOW)
    assert world["saves"] == 0
    assert got["decisions"][0]["action"] == "refused"
    assert "#77Y3BPFG" in got["decisions"][0]["why"]


def test_an_unknown_cost_check_is_a_refusal_too(world):
    sw.set_mode("act")
    world["edge"]["GPNSTOCK_USDT"] = "unknown"
    assert sw.consider(now=NOW)["decisions"][0]["action"] == "refused"


def test_off_removes_only_its_own_slot(world):
    sw.set_mode("act")
    sw.consider(now=NOW)
    world["fresh"]["77Y3BPFG"] = {**R6, "winrate": 89.9}
    got = sw.consider(now=NOW + 3601)
    assert [d["action"] for d in got["decisions"]] == ["off"]
    assert "GPNSTOCK_USDT" not in (world["settings"]["strategy_coins"]
                                   .get("macddiv_1h_sl07tp1") or [])
    assert SLOT not in world["settings"]["watcher_slots"]
    assert sw._read()["cooling"]["77Y3BPFG"] == NOW + 3601


def test_it_never_touches_real_money_or_a_hand_pick(world):
    world["settings"]["strategy_coins"] = {"bb20_15m_sl12tp12": ["FASTSTOCK_USDT"],
                                           "keltner_30m_sl2tp2": ["GPNSTOCK_USDT"]}
    world["settings"]["strategy_books"] = {
        "bb20_15m_sl12tp12|FASTSTOCK_USDT": ["real"],
        "keltner_30m_sl2tp2|GPNSTOCK_USDT": ["paper"]}
    world["cands"] = []
    world["fresh"] = {"R6FRS3KD": {**R6, "winrate": 10.0}}
    sw.set_mode("act")
    before = at.load_settings()
    got = sw.consider(now=NOW)
    after = world["settings"]
    assert after["strategy_books"]["bb20_15m_sl12tp12|FASTSTOCK_USDT"] == ["real"]
    assert after["strategy_coins"]["keltner_30m_sl2tp2"] == ["GPNSTOCK_USDT"]
    assert not any(d["action"] == "off" for d in got["decisions"])
    assert before["strategy_books"] == after["strategy_books"] or \
        set(after["strategy_books"]) >= set(before["strategy_books"])


def test_a_save_on_screen_between_read_and_write_is_kept(world, monkeypatch):
    """Review Focus 1. The operator saves a margin while the pass is deciding."""
    sw.set_mode("act")
    real_load = at.load_settings
    calls = {"n": 0}

    def _load():
        calls["n"] += 1
        s = real_load()
        if calls["n"] == 2:                     # the re-read before writing
            world["settings"]["strategy_margins"] = {"keltner_30m_sl2tp2": 7.0}
            s = real_load()
        return s

    monkeypatch.setattr(at, "load_settings", _load)
    sw.consider(now=NOW)
    assert world["settings"]["strategy_margins"]["keltner_30m_sl2tp2"] == 7.0
    assert "bb20_15m_sl12tp12" in world["settings"]["strategy_coins"]


def test_off_leaves_the_open_practice_trade_to_finish(world):
    """Review Focus 2. Removing the slot is all the watcher does; the runner's
    own rule (7897c110) finishes an open practice trade on a switched-off row.
    The watcher must not touch auto_trade_state or close anything."""
    import inspect

    src = inspect.getsource(sw)
    assert "save_state" not in src and "close_position" not in src
    assert "_dry_fill" not in src


def test_the_on_pass_runs_once_a_day_and_the_off_pass_hourly(world):
    sw.set_mode("act")
    sw.consider(now=NOW)
    world["cands"] = [{**R6, "id": "OTHER001", "coin": "KKRSTOCK"}]
    assert not [d for d in sw.consider(now=NOW + 3601)["decisions"]
                if d["action"] == "on"], "on-pass waits for tomorrow"
    assert [d for d in sw.consider(now=NOW + 86401)["decisions"]
            if d["action"] == "on"]


def test_hand_picked_rows_that_fail_are_reported_not_touched(world):
    world["cands"] = []
    world["settings"]["strategy_coins"] = {"bb20_15m_sl12tp12": ["FASTSTOCK_USDT"]}
    world["settings"]["strategy_books"] = {HAND: ["paper"]}
    world["settings"]["strategy_res"] = {HAND: "1m"}      # its id is the v2 one
    world["fresh"] = {"R6FRS3KD": {**R6, "id": "R6FRS3KD", "winrate": 84.54}}
    sw.set_mode("act")
    got = sw.consider(now=NOW)
    assert any(d["action"] == "report" and "#R6FRS3KD" in d["why"]
               for d in got["decisions"])
    assert world["settings"]["strategy_coins"]["bb20_15m_sl12tp12"] == ["FASTSTOCK_USDT"]


def test_off_mode_does_nothing_and_says_so(world):
    sw.set_mode("off")
    got = sw.consider(now=NOW)
    assert got["decisions"] == [] and "off" in got["why"]


def test_it_never_runs_under_a_test():
    assert sw.tick() == {"decisions": [], "why": "never under a test run"}


def test_the_supervisor_ticks_it():
    import pathlib

    src = pathlib.Path(sw.__file__).with_name("api.py").read_text("utf-8")
    watch = src[src.index("def _watch() -> None:"):]
    watch = watch[:watch.index("_th.Thread(target=_watch")]
    assert "_sw.tick()" in watch
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement `consider(now)`,** in this order. Each step appends decisions and never raises; a failure is a decision with `action: "refused"` naming the error type.
  1. `mode == "off"`: return with why `"switched off"`.
  2. **Off pass** (hourly, `last_off_pass`). For each slot in `settings["watcher_slots"]`:
     - `fresh = _fresh_row(...)`, `why = watcher_policy.judge(slot, fresh, cfg)`. `p = _practice(...)` and `watcher_policy.warn(p, cfg)` go on the screen only, never into the decision.
     - If `why`, record `off` and, in act mode, remove the coin from `strategy_coins[key]`, `strategy_books[slot]` and `watcher_slots[slot]`, and set `cooling[id] = now`.
     - Also judge every OTHER paper slot (hand-picked; its id from `api.row_id_for(key, coin, settings)`), and record `report` decisions, deduplicated per id per day.
  3. **On pass** (daily, `last_on_pass`):
     - `c = _candidates(cfg, now)`, then `picks = watcher_policy.pick(c["rows"], running, cooling, now, cfg)`.
     - For each pick: `key = strategy_keys.key_for(row)` and `spec = spec_for(row)`. `_register(key, spec)`: a `ValueError` is a refusal naming both recipes.
     - Then `edge_check(key, coin + "_USDT", 5.0)`: anything but `"ok"` is a refusal.
     - Otherwise record `on` and, in act mode, add the coin to `strategy_coins[key]`, set `strategy_books[slot] = ["paper"]`, `strategy_margins[key] = 5.0` if absent, `strategy_sizing[key] = "flat"`, `strategy_res[slot] = "1m"`, `watcher_slots[slot] = {"id", "on_at": now}`, and `strategies` += key.
     - Space the `edge_check` calls 0.5 s apart; they read the live book.
  4. **Write** (act mode, only if something changed) through `_write_settings(mutate)`:

```python
def _write_settings(mutate) -> bool:
    """Apply `mutate(settings)` to the file AS IT IS NOW, never to the copy
    read at the start of the pass: the operator may have pressed SAVE while
    the pass was reading the store (Review Focus 1). Retries 3 times if the
    file changes between this re-read and the write."""
    from tradingagents import auto_trader as at

    for _ in range(3):
        before = at.load_settings()
        after = mutate({k: (dict(v) if isinstance(v, dict) else
                            list(v) if isinstance(v, list) else v)
                        for k, v in before.items()})
        if at.load_settings() != before:
            continue
        at.save_settings(after)          # also writes the deploy log (deployed_at)
        return True
    return False
```

  5. Append every decision to `LOG`, and ring the bell once per pass with the counts: `"Watcher: 4 switched on, 1 switched off (practice)"`.
- [ ] **Step 4: Wire the supervisor** in `api.py` `_watch()`, after the `daily_update` block:

```python
                # THE STRATEGY WATCHER (operator, Sep 28, 2026: "i need watcher
                # that will undeploy a strategy if its not working anymore and
                # will deploy new ones"). Practice account only; ships in
                # PREVIEW, where it decides and writes nothing.
                try:
                    from tradingagents import strategy_watcher as _sw

                    _sw.tick()
                except Exception as exc:                       # noqa: BLE001
                    print(f"[watcher] failed: {exc!r}", flush=True)
```

- [ ] **Step 5: Run, expect PASS.** Then re-run Tasks 1-5's tests and `tests/test_deploy_preset.py`, `tests/test_both_books_on_a_deployed_row.py`, `tests/test_the_deployed_date_is_filled_in.py`.
- [ ] **Step 6: Run `blast-radius`.** List every other reader of `strategy_coins` / `strategy_books` / `strategy_res` (`grep -rn "strategy_books\|strategy_coins\|strategy_res" tradingagents`) and confirm each one handles a key that exists only in the runtime registry. Put the list in the commit message.
- [ ] **Step 7: Commit and push:** `feat(watcher): the hourly/daily pass, practice only, PREVIEW by default`.

---

### Task 7: The screen

**Files:**
- Modify: `tradingagents/api.py`: `GET /api/trade/watcher` → `strategy_watcher.status()`; `POST /api/trade/watcher` with `{"mode": ...}` or `{"cfg": {...}}` → 422 on anything else
- Modify: `webapp/src/lib/api.ts`: the `Watcher` interface, `watcher()` and `watcherSet(body)`
- Create: `webapp/src/components/trade/WatcherPanel.tsx`
- Modify: `webapp/src/components/trade/AutoTradeScreen.tsx`: mount it directly under the deployed-strategies grid
- Test: `tests/test_the_watcher_panel_says_what_it_did.py`

**Interfaces:**
- Consumes: `status()` → `{"mode", "cfg", "last_on_pass", "next_on_pass", "last_off_pass", "next_off_pass", "running": int, "max_slots": int, "decisions": [...last 50], "why"}`

- [ ] **Step 1: Write the failing tests.**
  - The route returns every key the panel prints.
  - A bad POST answers 422.
  - The panel source prints mode, counts and dates from the payload, through `fmtWhen`, never a literal.
  - Each decision line carries `#${d.id}`.
  - Below `md` the decision list is cards, not a table (the Sep 23 phone rule, `tests/test_the_trade_tables_work_on_a_phone.py`).
  - The mode control offers exactly `off`, `preview` and `act`, and `act` asks `confirm()` naming that it switches practice rows on and off by itself.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
  - Header: *"Watcher — practice account only · PREVIEW: it decides and changes nothing"*, with the mode buttons.
  - The settings table from `cfg`: on at 90% or more · off under 90% · at least 20 trades in the last 30 days · TP wider than SL · up to 100 rows, 3 per coin, 20 new a day. Each running row also shows its practice record and any `warn()` sentence.
  - `last pass Sep 28, 2026 3:21pm · next Sep 29, 2026 11:49am`.
  - The last 50 decisions, newest first: `switched on #77Y3BPFG GPNSTOCK 1h macddiv TP 1.0% / SL 0.7% — 100% over 20 trades, +15.84`.
  - Refusals in amber, "switched off" in red, "report" lines under their own heading: *"your own rows that would be switched off"*.
- [ ] **Step 4: `tsc --noEmit`, run the tests, expect PASS.**
- [ ] **Step 5: Warn the operator that the site goes dark for about 3 minutes, then `.venv/Scripts/python start.py start`.** Wait for 4 consecutive 200s on `/trade`. Walk it with playwright-core (`.claude/skills/press-and-watch/scripts`) at 1600px and 390px: the panel renders, PREVIEW is selected, switching to `off` and back to `preview` round-trips, and there are 0 page errors.
- [ ] **Step 6: Commit and push:** `feat(watcher): the Trade screen says what the watcher decided and why`.

---

### Task 8: Live PREVIEW, then the operator's switch

**Files:**
- Modify: `CLAUDE.md` (new section *"The watcher switches practice rows on and off (MANDATORY — 2026-09-28)"*, quoting the operator's words and the Global Constraints)

- [ ] **Step 1:** After the restart, wait for the first real on-pass in PREVIEW and read `strategy_watcher.jsonl`.
- [ ] **Step 2: Check its picks by hand against the store.**
  - For 3 ids it would switch on, run `/api/v2/strategies?row_id=<id>` and read the pair file. The figures must match the decision line.
  - For each, confirm `edge_check` said ok (rule 12) and the stop sits inside `STOP_LIQ_CEILING`.
- [ ] **Step 3: Report to the operator** in one plain sentence plus the list of ids it would switch on and off, each with coin, timeframe, signal, TP, SL, 30-day win rate, trades and profit (rule 22). Ask them to switch it to ACT themselves.
- [ ] **Step 4:** Only after the operator switches ACT on the screen: watch one real act pass.
  - Every armed slot appears in the deployed grid with its id and the deployed date.
  - Within the next runner cycle, the ledger shows the runner scanning each new key: its `stale_skip` / `gate_blocked` / `enter` rows carry the key, which proves Task 2 end to end.
  - Paste the counts into the commit.
- [ ] **Step 5: Commit and push** the CLAUDE.md section, then speak through `say-done`.

---

## Out of this plan (named so it is not forgotten)

- **Real money.** Promoting a row that proved itself in practice to the real account needs its own plan and the operator's per-row approval (CLAUDE.md rules 14-17, 21-22).
- **Learned formulas (`lx_`, `ml_`).** They carry per-coin registries; arming them unattended is a separate question.
- **The stale v2 index** (3,656 of 5,006 pairs behind on Sep 28, 2026, paused by `export_v2`) is worked around by Task 4, not fixed. The fix belongs to `rows_index` / the v2 collect's own filing.
- **Nested windows (`still-working`).** v2 holds ~30 days of minutes, so "1 month, 3 months, 6 months" cannot be checked on v2 rows. The practice record is the second window this plan uses instead.
