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
