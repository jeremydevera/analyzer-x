"""The operator's Sep 27, 2026 deploy adds three rows and keeps the other 81.

Operator: *"okay deploy them in demo trade only"*, then *"Add, keep the 81"*.
Five Backtest v2 ids were picked; #7BNLXU62 and #H6Q486BR were already armed
by v2-sep25, so `presets/v2-sep27.json` arms the other three on the practice
account. The same checks as `.claude/skills/deploy-by-id`: every id is the
combination it was hashed from, every armed slot prints the id it runs as,
and applying MERGES — nothing already armed is switched off or moved to real
money.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tradingagents import api, auto_trader as at, backtest_report as br
from tradingagents import deploy_preset as dp
from tradingagents.local_history import _sig_of

ROOT = Path(__file__).resolve().parents[1]
PRESET = ROOT / "presets" / "v2-sep27.json"
TF_IV = {"15m": ("Min15", 900), "30m": ("Min30", 1800)}
ADDED = {"C9MRXJSD": "KKRSTOCK_USDT", "8EZ3XPKE": "AONSTOCK_USDT",
         "NJUZZEC2": "VUG_USDT"}
ALREADY = {"7BNLXU62": ("prank_15m_sl15tp2", "FASTSTOCK_USDT"),
           "H6Q486BR": ("keltner_30m_sl2tp25", "GPNSTOCK_USDT")}


@pytest.fixture(scope="module")
def preset():
    return dp.load(PRESET)


def _slots(preset):
    for key, one in preset["strategies"].items():
        for coin in one["coins"]:
            yield key, coin, one["measured"][coin.replace("_USDT", "")]


def test_the_five_picks_are_three_new_and_two_already_armed(preset):
    armed = {m["runs_as"]: coin for _, coin, m in _slots(preset)}
    assert armed == ADDED
    assert {a["id"]: (a["key"], a["coin"]) for a in preset["already_armed"]} == ALREADY
    assert preset["replace"] is False and preset["refused"] == []


def test_every_id_is_its_combination_and_runs_as_itself(preset):
    settings = dp.merged(preset, {})
    for key, coin, m in _slots(preset):
        c = coin.replace("_USDT", "")
        assert m["given"] == [m["runs_as"]]
        assert br.row_code(c, m["tf"], m["signal"], m["th"], m["sl_pct"],
                           m["tp_pct"], "flat", res="1m") == m["runs_as"]
        assert api.row_id_for(key, coin, settings) == m["runs_as"], (key, coin)


def test_the_two_already_armed_print_their_ids():
    settings = dp.merged(dp.load(ROOT / "presets" / "v2-sep25.json"), {})
    for rid, (key, coin) in ALREADY.items():
        assert coin in settings["strategy_coins"][key]
        assert api.row_id_for(key, coin, settings) == rid


def test_every_key_is_its_rows_spec_and_is_walked(preset):
    for key, _, m in _slots(preset):
        spec = at.STRATEGY_SPECS[key]
        assert key in at.STRATEGY_ORDER
        assert (spec["interval"], spec["bar_seconds"]) == TF_IV[m["tf"]], key
        assert spec["tp"] == pytest.approx(m["tp_pct"] / 100), key
        assert spec["sl"] == pytest.approx(m["sl_pct"] / 100), key
        assert _sig_of(key) == m["signal"], key


def test_adding_keeps_everything_already_armed_and_arms_only_practice(preset):
    before = {"strategies": ["keltner_30m_sl2tp25", "prank_15m_sl15tp2"],
              "strategy_coins": {"keltner_30m_sl2tp25": ["GPNSTOCK_USDT"],
                                 "prank_15m_sl15tp2": ["FASTSTOCK_USDT"]},
              "strategy_books": {"keltner_30m_sl2tp25": ["paper"],
                                 "prank_15m_sl15tp2": ["paper"]},
              "strategy_margins": {"keltner_30m_sl2tp25": 5.0,
                                   "prank_15m_sl15tp2": 5.0},
              "strategy_res": {"keltner_30m_sl2tp25": "1m"},
              "enabled": False, "dry_run": True}
    out = dp.merged(preset, before)
    for key, coins in before["strategy_coins"].items():
        assert out["strategy_coins"][key] == coins
        assert out["strategy_books"][key] == ["paper"]
        assert key in out["strategies"]
    assert out["strategy_res"]["keltner_30m_sl2tp25"] == "1m"
    for key, coin, _ in _slots(preset):
        assert at.book_names(out, key, coin) == ["paper"], (key, coin)
    assert out["enabled"] is False and out["dry_run"] is True
