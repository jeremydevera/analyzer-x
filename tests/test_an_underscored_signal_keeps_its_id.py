"""A signal name with an underscore keeps its id (RCA-2026-09-24-G).

From Sep 16, 2026 1:54am the deployed-strategies screen printed FASTSTOCK's
`cf_soup1` 1h row as #GYWZS995 — an id that is in no store — because the
strategy key `cf_soup1_1h_sl25tp1` was split on its first `_` and read as
signal `cf`. Its real id is #KDY5M3LQ (44 trades, 97.73%, +$30.82 in the v1
store). Two more rows the same way: #T724QASK for #46SGBAHD, #3FBZAH3B for
#HQH72A8L. 57 registered signals carry an underscore, and the operator's
Sep 24, 2026 deploy arms 15 of them.

The same one-line split had been copied into four modules, so these tests
hold the CLASS: one parser, it agrees with the dispatcher the runner trades
by for every key, and no module splits a key on its own again.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tradingagents import api, auto_trader as at, backtest_report as br
from tradingagents import market_sweep as msw
from tradingagents.local_history import _sig_of

ROOT = Path(__file__).resolve().parents[1]


def test_the_three_rows_that_printed_ids_in_no_store_print_their_own():
    # fixed points: each id below is the row in the v1 store the operator
    # deployed on Sep 16, 2026 (FASTSTOCK 1h, flat)
    assert api.row_id_for("cf_soup1_1h_sl25tp1", "FASTSTOCK_USDT", {}) == "KDY5M3LQ"
    assert api.row_id_for("cf_soup1_1h_sl3tp1", "FASTSTOCK_USDT", {}) == "46SGBAHD"
    assert api.row_id_for("cx_veto_1h_sl3tp1", "FASTSTOCK_USDT", {}) == "HQH72A8L"


@pytest.mark.parametrize("name", sorted(s for s in br.SIGNALS if "_" in s))
def test_every_underscored_signal_is_read_whole(name):
    for key in (f"{name}_1h_sl3tp1", f"{name}_1d_sl4tp12p0", f"{name}_15m"):
        assert _sig_of(key) == name, key


def test_a_key_without_an_underscored_signal_reads_as_it_always_did():
    for key, want in (("mom15_4h_w", "mom15"), ("ict_fvg", "fvg"),
                      ("sweep_rt", "sweep"), ("willr14_30m_sl2tp05", "willr14"),
                      ("mom6", "mom6"), ("trend50", "trend50"),
                      ("mom6_1h_t08_sl3tp15", "mom6")):
        assert _sig_of(key) == want, key


def test_the_id_and_the_runner_read_the_same_signal_from_every_key(monkeypatch):
    """The lists against each other (CLAUDE.md, Sep 15, 2026): for every key
    the runner can trade, the rule `signal_for` actually dispatches to is the
    signal the id is hashed with. Spies stand in for every registered rule, so
    this reads the real dispatcher, not a copy of its order."""
    from tradingagents import signals_conf, signals_ext, signals_ext2

    fired: list = []

    def spy(name):
        def fn(*a, **k):
            fired.append(name)
            return [0]
        return fn

    for reg in (signals_conf.CONF_SIGNALS, signals_ext.EXTRA_SIGNALS,
                signals_ext2.EXTRA_SIGNALS2):
        for name in list(reg):
            monkeypatch.setitem(reg, name, spy(name))
    bars = [1.0] * 50
    checked = 0
    for key in at.STRATEGY_SPECS:
        fired.clear()
        at.signal_for(key, bars, bars, bars, bars, bars, list(range(50)))
        if fired:
            assert fired == [_sig_of(key)], key
            checked += 1
    assert checked > 50, "the spies must have seen the registered rules"


def test_a_deployed_underscored_row_is_a_combination_the_sweep_measures(monkeypatch):
    """`deployed_combos` split the key too: signal `cf`, timeframe `soup1`, so
    the sweep's "a deployed combination is never skipped" rule could not
    match these rows to anything it measures."""
    monkeypatch.setattr(at, "load_settings", lambda: {
        "strategies": ["cf_soup1_1h_sl25tp1", "cx_veto_1h_sl3tp1"],
        "strategy_coins": {"cf_soup1_1h_sl25tp1": ["FASTSTOCK_USDT"],
                           "cx_veto_1h_sl3tp1": ["FASTSTOCK_USDT"]}})
    assert msw.deployed_combos() == {("FASTSTOCK", "1h", "cf_soup1", 2.5, 1.0),
                                     ("FASTSTOCK", "1h", "cx_veto", 3.0, 1.0)}


def test_no_module_splits_a_strategy_key_to_find_its_signal():
    """A guard is only as wide as its pattern: the broken line was copied into
    four modules. Any `.split("_")` in the package outside the one parser is
    named here — reading the CALLS, not the text, so a docstring quoting the
    old form does not trip it."""
    hits = []
    for path in sorted((ROOT / "tradingagents").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))

        def walk(node, fn=None):
            for child in ast.iter_child_nodes(node):
                here = (child.name if isinstance(child, (ast.FunctionDef,
                                                         ast.AsyncFunctionDef))
                        else fn)
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "split" and child.args
                        and isinstance(child.args[0], ast.Constant)
                        and child.args[0].value == "_"):
                    hits.append((path.name, fn))
                walk(child, here)
        walk(tree)
    assert hits == [("local_history.py", "_sig_of")], hits
