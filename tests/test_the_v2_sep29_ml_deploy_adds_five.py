"""The operator's Sep 29, 2026 deploy adds five Sep 27 ML rows to practice.

Operator: *"can you add these ids auto trade, turn on for demo only"* — five
ids off the Backtest v2 "Sep 27 ML" group, confirmed "Yes, switch all 5 on
(practice)". `presets/v2-sep29-ml.json` is that arming. The deploy-by-id
checks: every id is the combination it was hashed from, every armed slot
prints the id it runs as, every key's signal is its own decision-tree model,
and applying MERGES onto the practice account only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tradingagents import api, auto_trader as at, backtest_report as br
from tradingagents import deploy_preset as dp
from tradingagents.local_history import _sig_of

ROOT = Path(__file__).resolve().parents[1]
PRESET = ROOT / "presets" / "v2-sep29-ml.json"
TF_IV = {"15m": ("Min15", 900), "30m": ("Min30", 1800)}
ASKED = {"JYRT8AN8", "TT23MEZG", "2P3LRFMX", "QHB5UVQP", "CW6Z7FWT"}


@pytest.fixture(scope="module")
def preset():
    return dp.load(PRESET)


def _slots(preset):
    for key, one in preset["strategies"].items():
        for coin in one["coins"]:
            yield key, coin, one["measured"][coin.replace("_USDT", "")]


def test_the_five_ids_asked_for_are_the_five_armed(preset):
    armed = [m["runs_as"] for _, _, m in _slots(preset)]
    assert sorted(armed) == sorted(ASKED)
    assert preset["replace"] is False and preset["refused"] == []


def test_every_id_is_its_combination_and_runs_as_itself(preset):
    settings = dp.merged(preset, {})
    for key, coin, m in _slots(preset):
        c = coin.replace("_USDT", "")
        assert br.row_code(c, m["tf"], m["signal"], m["th"], m["sl_pct"],
                           m["tp_pct"], "flat", res="1m") == m["runs_as"]
        assert api.row_id_for(key, coin, settings) == m["runs_as"], (key, coin)


def test_every_key_is_its_models_spec_and_is_walked(preset):
    from tradingagents import signals_ml as sml

    for key, _, m in _slots(preset):
        spec = at.STRATEGY_SPECS[key]
        assert key in at.STRATEGY_ORDER
        assert (spec["interval"], spec["bar_seconds"]) == TF_IV[m["tf"]], key
        assert spec["tp"] == pytest.approx(m["tp_pct"] / 100), key
        assert spec["sl"] == pytest.approx(m["sl_pct"] / 100), key
        assert m["tp_pct"] > m["sl_pct"], key
        assert _sig_of(key) == m["signal"], key
        model = sml.spec_for(key)
        assert model is not None and model["name"] == m["signal"], key


def test_adding_keeps_what_runs_and_arms_only_practice(preset):
    before = {"strategies": ["prank_15m_sl15tp2"],
              "strategy_coins": {"prank_15m_sl15tp2": ["FASTSTOCK_USDT"]},
              "strategy_books": {"prank_15m_sl15tp2": ["paper"]},
              "strategy_margins": {"prank_15m_sl15tp2": 5.0},
              "enabled": False, "dry_run": True}
    out = dp.merged(preset, before)
    assert out["strategy_coins"]["prank_15m_sl15tp2"] == ["FASTSTOCK_USDT"]
    for key, coin, _ in _slots(preset):
        assert at.book_names(out, key, coin) == ["paper"], (key, coin)
    assert out["enabled"] is False and out["dry_run"] is True
