"""The operator's Sep 25, 2026 deploy is exactly the 86 rows they pasted.

Operator: *"undeploy my current live ttrade then deploy these"* — 86 Backtest
v2 ids, all flat (v2 keeps flat only since Sep 24). `presets/v2-sep25.json`
is that arming, applied with replace over the 537 slots of v2-sep24. The
same four checks as `.claude/skills/deploy-by-id` and the Sep 24 test: every
id is the combination it was hashed from, 86 = armed + refused BY ID, every
armed slot prints the id it runs as, and replacing arms nothing on real
money.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tradingagents import api, auto_trader as at, backtest_report as br
from tradingagents import deploy_preset as dp
from tradingagents.local_history import _sig_of

ROOT = Path(__file__).resolve().parents[1]
PRESET = ROOT / "presets" / "v2-sep25.json"
TF_IV = {"15m": ("Min15", 900), "30m": ("Min30", 1800), "1h": ("Min60", 3600),
         "4h": ("Hour4", 14400), "1d": ("Day1", 86400)}
REFUSED = {"P69QEVEQ", "HD5J9NJ4", "5VENHXK5", "Z2379MA9", "DBTHR9G7"}


@pytest.fixture(scope="module")
def preset():
    return dp.load(PRESET)


def _slots(preset):
    for key, one in preset["strategies"].items():
        for coin in one["coins"]:
            yield key, coin, one["measured"][coin.replace("_USDT", "")]


def test_the_86_ids_add_up(preset):
    armed = [i for _, _, m in _slots(preset) for i in m["given"]]
    refused = [i for r in preset["refused"] for i in r["given"]]
    assert len(armed) == 81 and set(refused) == REFUSED
    assert len(set(armed) | set(refused)) == 86 == len(armed) + len(refused)
    assert len(preset["strategies"]) == 64


def test_every_id_is_its_combination_and_runs_as_itself(preset):
    settings = dp.merged({**preset, "replace": True}, {})
    for key, coin, m in _slots(preset):
        c = coin.replace("_USDT", "")
        assert m["given"] == [m["runs_as"]], "flat only: each id runs as itself"
        assert br.row_code(c, m["tf"], m["signal"], m["th"], m["sl_pct"],
                           m["tp_pct"], "flat", res="1m") == m["runs_as"]
        assert api.row_id_for(key, coin, settings) == m["runs_as"], (key, coin)


def test_every_key_is_its_rows_spec_and_is_walked(preset):
    for key, coin, m in _slots(preset):
        spec = at.STRATEGY_SPECS[key]
        assert key in at.STRATEGY_ORDER
        assert (spec["interval"], spec["bar_seconds"]) == TF_IV[m["tf"]], key
        assert spec["tp"] == pytest.approx(m["tp_pct"] / 100), key
        assert spec["sl"] == pytest.approx(m["sl_pct"] / 100), key
        assert _sig_of(key) == m["signal"], key


def test_the_refused_are_the_wall_and_replacing_arms_only_practice(preset):
    for r in preset["refused"]:
        assert "liquidation" in r["why"] and r["sl_pct"] >= 2.4, r
    out = dp.merged({**preset, "replace": True},
                    {"strategies": ["keltner_30m_sl2tp2"],
                     "strategy_coins": {"keltner_30m_sl2tp2": ["KITE_USDT"]},
                     "strategy_books": {"keltner_30m_sl2tp2|KITE_USDT": ["real"]},
                     "enabled": False, "martingale_demo": True})
    for key, coin, _ in _slots(preset):
        assert at.book_names(out, key, coin) == ["paper"], (key, coin)
    assert "keltner_30m_sl2tp2|KITE_USDT" not in out["strategy_books"]
    assert out["enabled"] is False and out["martingale_demo"] is True
