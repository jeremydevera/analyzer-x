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
