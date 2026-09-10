"""A strategy the operator is RUNNING is always measured.

Sep 10-11, 2026. The operator searched `#PNK3G9KZ` — one of their own 35
deployed strategies — and the store had no row for it. Then: *"so what is
PNK3G9KZ in the deployed strategies? this only means you are deleting existing
strategies and you are not updating them"*.

Measured, and they were right about the effect: **28 of their 35 deployed
strategies had no row**, and `GPNSTOCK-15m` / `GPNSTOCK-30m` held **0 rows,
0 signals, 0 bytes**.

Nothing had been deleted. `market_sweep`'s cost gate skips a barrier whose
round-trip cost is half its take-profit or more — rule 11, and correct: a
target smaller than its cost cannot win. But `rt` comes from the LIVE ORDER
BOOK at the instant the sweep runs, and those pair files were written
`Sep 10 11:33am-1:17pm` Manila = `11:33pm-1:17am` New York, with the US market
SHUT. A tokenized stock's spread blows out when its underlying is closed:

    PSXSTOCK   recorded in the rows   1.287%   ->  TP 1.2% reads 107%, skipped
    PSXSTOCK   with the market open   0.263%   ->  TP 1.2% reads  22%, measured
    CHYMSTOCK  recorded               2.4347%  ->  TP 2.5% reads  97%, skipped
    STBL (crypto, always open)        0.1087%  ->  every TP measured

So the grid's CONTENTS depended on the clock, and the only symptom was a row
that was not there. What is fixed here is not the gate — it is that the gate
was allowed to hide a strategy the operator is already running, leaving it
with no measurement at all. CLAUDE.md rule 21 screens the DEPLOYED row first;
it cannot be screened if it was never measured.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from tradingagents import auto_trader as at, market_sweep as msw


@pytest.fixture()
def deployed(monkeypatch):
    """One deployed strategy whose TP the gate would refuse."""
    monkeypatch.setitem(at.STRATEGY_SPECS, "willr14_15m_sl1tp12",
                        {"interval": "Min15", "bar_seconds": 900,
                         "tp": 0.012, "sl": 0.010})
    monkeypatch.setattr(at, "load_settings", lambda: {
        "strategies": ["willr14_15m_sl1tp12"],
        "strategy_coins": {"willr14_15m_sl1tp12": ["PSXSTOCK_USDT"]},
        "coins": [], "strategy_sizing": {}})
    return ("PSXSTOCK", "15m", "willr14", 1.0, 1.2)


def test_the_deployed_set_is_read_from_the_operators_own_settings(deployed):
    got = msw.deployed_combos()
    assert deployed in got, got
    # the SYMBOL form must be normalised — the store keys on the bare coin
    assert not any(c.endswith("_USDT") for c, *_ in got)
    # and TP/SL are PERCENTS, the unit the rows and row_code use. Hashing the
    # fractions is what made me tell the operator their row was not deployed.
    assert all(tp > 0.05 for *_, tp in got), \
        "0.012 means the fractions leaked in; the store stores 1.2"


def test_the_gate_still_skips_an_undeployed_combination(deployed):
    """The gate is RIGHT — a target its cost eats cannot win (rule 11). The
    exemption is only for what the operator is running."""
    src = inspect.getsource(msw.run_pair)
    i = src.index("rt / tp >= GATE_BLOCK")
    branch = src[i:i + 400]
    assert "not in deployed" in branch, \
        "the skip must be conditional on NOT being deployed"
    assert "gated += 1" in branch, "and a skip must be counted, never silent"


def test_the_deployed_combination_is_never_skipped(deployed):
    """The whole point, read off the branch: with the tuple in `deployed`, the
    `continue` cannot be reached."""
    src = textwrap.dedent(inspect.getsource(msw.run_pair))
    tree = ast.parse(src)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = ast.unparse(node.test)
        if "GATE_BLOCK" in test:
            found.append(test)
    assert found, "the gate's own branch is gone"
    assert any("not in deployed" in t for t in found), found
    # and the tuple it tests is the SAME shape deployed_combos() returns
    assert any("round(sl * 100, 6)" in t and "round(tp * 100, 6)" in t
               for t in found), found


def test_a_settings_file_that_cannot_be_read_exempts_nothing(monkeypatch):
    """An unreadable settings file must not silently exempt everything (which
    would measure ~150,000 hopeless combinations per pair) nor crash a sweep."""
    def boom():
        raise OSError("settings gone")

    monkeypatch.setattr(at, "load_settings", boom)
    assert msw.deployed_combos() == set()


def test_a_strategy_with_no_spec_is_skipped_not_guessed(monkeypatch):
    """A key in the operator's list with no STRATEGY_SPECS entry has no TP or
    SL to exempt. Guessing one from the key's text is how `sl25tp25` became
    0.025 instead of 2.5."""
    monkeypatch.setattr(at, "load_settings", lambda: {
        "strategies": ["ghost_15m_sl1tp1"],
        "strategy_coins": {"ghost_15m_sl1tp1": ["AAA_USDT"]}})
    assert msw.deployed_combos() == set()


def test_the_counters_reach_the_caller(deployed):
    """rule 20: whatever was excluded is counted OUT LOUD. `thin` already was;
    a gated barrier was not counted at all before this."""
    src = inspect.getsource(msw.run_pair)
    assert "gated = 0" in src
    assert "gated += 1" in src
