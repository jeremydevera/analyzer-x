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


# --------------------------------------------- what the rooms are running now
import json  # noqa: E402

import pytest  # noqa: E402


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
    import os

    from tradingagents import running_rows as rr

    _settings(rooms["main"], "keltner_30m_sl2tp2", ["GPNSTOCK_USDT"])
    rooms["6B08FF64"].write_text("{}", encoding="utf-8")
    first = rr.read_combos()
    rooms["main"].write_text('{"strategy_coins": {', encoding="utf-8")   # mid-write
    os.utime(rooms["main"], (1, 1))
    assert first and rr.read_combos() == first


def test_a_missing_room_folder_is_nothing_running(rooms):
    from tradingagents import running_rows as rr

    assert rr.read_combos() == frozenset()


def test_no_test_depends_on_the_operators_real_rooms():
    from tradingagents import running_rows as rr

    assert rr.combos() == frozenset()
