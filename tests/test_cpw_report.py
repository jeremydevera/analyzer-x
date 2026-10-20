"""Reading the Crypto-Predictor search (tradingagents/cpw_report.py): which
switch settings win, what each switch does, which winners the check run
measures again, and the columns a results table carries — every number from
made-up sums and trades whose answer is known by hand."""
from __future__ import annotations

import numpy as np
import pytest

from tradingagents import cpw_report as rep, signals_cpw as cp

FIELDS = ["pairs", "pairs_up", "trades", "wins", "profit",
          "l_pairs", "l_pairs_up", "l_trades", "l_wins", "l_profit"]
ST = [n for n in cp.variants() if n.startswith("cp_st_")][:4]
# cp_st_f0u0h0x0i0d0 (the preset), ..._d1, ..._i1d0, ..._i1d1
BARS = {"15m": [(0.002, 0.004), (0.003, 0.006), (0.005, 0.01)]}


def _merged(profits):
    """profits[setting][barrier] -> sums where each traded cell has 10 pairs."""
    a = np.zeros((len(ST), len(BARS["15m"]), len(FIELDS)))
    for i, row in enumerate(profits):
        for k, p in enumerate(row):
            if p is not None:
                a[i, k, :5] = (10, 6 if p > 0 else 3, 100, 55, p)
    return {"names": list(ST), "fields": FIELDS, "tf": {"15m": a}, "barriers": BARS}


def test_the_names_are_in_the_order_this_test_assumes():
    assert ST[0] == rep.preset_of("st") == "cp_st_f0u0h0x0i0d0"
    assert rep.digits_of(ST[1]) == (0, 0, 0, 0, 0, 1)
    assert rep.digits_of(ST[2]) == (0, 0, 0, 0, 1, 0)


def test_settings_with_identical_sums_are_one_strategy_ranked_once():
    m = _merged([[1.0, 5.0, None], [1.0, 5.0, None], [2.0, -1.0, 9.0], [None, None, None]])
    tw = rep.twins(m, "15m")
    assert tw[ST[1]] == ST[0] and tw[ST[0]] == ST[0] and tw[ST[2]] == ST[2]
    lines = rep.ranking(m)[("st", "15m")]
    assert [ln["name"] for ln in lines] == [ST[2], ST[0]]       # 9.0, then 5.0
    assert lines[1]["same"] == [ST[0], ST[1]]
    assert (lines[0]["sl"], lines[0]["tp"]) == (0.5, 1.0)         # its own best pair
    assert all(ln["name"] != ST[3] for ln in lines), "a setting that never traded is not ranked"


def test_what_a_switch_does_is_counted_over_settings_that_differ_only_in_it():
    # d: preset 0 -> 1 changes the preset (5.0 -> 7.0) and i1 (9.0 -> 4.0)
    m = _merged([[5.0, None, None], [7.0, None, None], [9.0, None, None], [4.0, None, None]])
    eff = {(e["switch"], e["to"]): e for e in rep.effects(m) if e["tf"] == "15m"
           and e["strategy"] == "st"}
    d = eff[("di", True)]
    assert (d["pairs"], d["better"], d["worse"], d["same"]) == (2, 1, 1, 0)
    assert d["mean"] == pytest.approx(((7 - 5) + (4 - 9)) / 2)
    i = eff[("impulse", True)]
    assert (i["pairs"], i["better"], i["worse"]) == (2, 1, 1)     # 5->9 up, 7->4 down


def test_the_check_run_takes_the_top_distinct_settings_and_the_apps_preset():
    m = _merged([[1.0, None, None], [3.0, None, None], [8.0, None, None], [6.0, None, None]])
    cfgs = rep.choose(m, top=2)
    assert [(c["name"], c["place"]) for c in cfgs] == [(ST[2], 1), (ST[3], 2), (ST[0], 4)]
    assert cfgs[-1]["preset"] and not cfgs[0]["preset"]
    assert all(c["of"] == 4 for c in cfgs)
    assert rep.configs_arg(cfgs[:1]) == f"{ST[2]}:15m:0.2:0.4"


def test_the_columns_come_from_the_trades_closed_in_order_across_coins():
    # [entry, exit, side, why, profit]; minutes, as ms
    m = 60_000
    lines = [{"coin": "A", "trades": [[0, 10 * m, 1, "SL", -1.0], [20 * m, 30 * m, 1, "TP", 2.0]]},
             {"coin": "B", "trades": [[5 * m, 12 * m, -1, "SL", -1.5],
                                      [6 * m, 31 * m, 1, "SL", -0.5]]}]
    s = rep.stats(lines)
    # closed in order: A -1.0 (10), B -1.5 (12), A +2.0 (30), B -0.5 (31)
    assert (s["trades"], s["wins"], s["losses"], s["profit"]) == (4, 1, 3, -1.0)
    assert (s["streak"], s["streak_len"]) == (-2.5, 2)
    assert s["dd"] == 2.5
    assert (s["coins"], s["coins_up"]) == (2, 1)
    assert s["monthly"] == {"1970-01": -1.0} and s["green"] == 0 and s["months"] == 1
    # a window counts the trades that OPENED inside it
    w = rep.stats(lines, start_ms=6 * m)
    assert (w["trades"], w["wins"], w["profit"]) == (2, 1, 1.5)


def test_every_switch_has_plain_words():
    for st, sw in cp.SWITCHES.items():
        for _letter, setting, _values in sw:
            assert setting in rep.PLAIN, (st, setting)
    assert rep.words("cp_br_e2h1x0u0r0").startswith("enter on: breakout close, ")


def test_the_page_rows_carry_every_window_and_their_trades():
    from tradingagents import backtest_report as br

    day = 86_400_000
    end = 1_792_454_400_000                     # Oct 20, 2026 00:00 UTC, a 15m close
    last = end - 15 * 60_000
    name = "cp_st_f1u0h0x0i0d0"
    key = f"{name}:15m:0.5:1"
    # two coins; trades 52 (August), 20 and 2 days before the end, and one 12 hours before
    check = {key: [
        {"cfg": key, "coin": "A", "tf": "15m", "row": {"last_ms": last},
         "trades": [[end - 52 * day, end - 51 * day, 1, "SL", -1.0],
                    [end - 2 * day, end - 2 * day + 60_000, 1, "TP", 2.0]]},
        {"cfg": key, "coin": "B", "tf": "15m", "row": {"last_ms": last - 3600_000},
         "trades": [[end - 20 * day, end - 19 * day, -1, "SL", -0.5],
                    [end - day // 2, end - day // 4, -1, "END", 0.25]]}]}
    cfgs = [{"name": name, "tf": "15m", "sl": 0.5, "tp": 1.0, "place": 1, "of": 9,
             "same": [name], "preset": False, "search": {}}]
    rows, files, got_end = rep.page_rows(cfgs, check)
    assert got_end == end
    r = rows[0]
    assert r["id"] == br.row_code("ALL", "15m", name, 0.0, 0.5, 1.0, "flat", res="1m")
    assert r["all"]["trades"] == 4 and r["all"]["profit"] == 0.75
    assert len(r["days"]) == rep.WINDOW_DAYS
    assert r["days"][0]["trades"] == 1 and r["days"][0]["profit"] == 0.25      # last 1 day
    assert r["days"][2]["trades"] == 2 and r["days"][2]["profit"] == 2.25      # last 3 days
    assert r["days"][29]["trades"] == 3                                        # last 30 days
    # last 1 month = October (the end is Oct 20), last 2 = September and October
    assert r["months"][0]["trades"] == 2 and r["months"][1]["trades"] == 3
    f = files[r["id"]]
    assert f["coins"] == ["A", "B"]
    assert [t[2] for t in f["t"]] == sorted(t[2] for t in f["t"])             # closed in order
    assert f["t"][0] == [0, (end - 52 * day) // 1000, (end - 51 * day) // 1000, 1, 1, -1.0]


def test_the_check_run_also_takes_the_best_within_the_operators_usual_limits():
    # the overall winner needs a 1% target; under TP <= 0.6% and SL <= 0.3%
    # (the made-up limits here) another setting wins, and is checked too
    m = _merged([[None, 2.0, None], [None, None, 9.0], [4.0, None, None], [None, 1.0, None]])
    rank = rep.ranking(m, max_tp=0.6, max_sl=0.3)
    assert [ln["name"] for ln in rank[("st", "15m")]] == [ST[2], ST[0], ST[3]]
    cfgs = rep.choose(m, top=1, caps=(0.6, 0.3))
    got = [(c["name"], c["tp"], c["place"], c["of"], c.get("capped")) for c in cfgs]
    assert got == [(ST[1], 1.0, 1, 4, None),            # the winner
                   (ST[0], 0.6, 3, 4, None),            # the app's own, 3rd overall
                   (ST[2], 0.4, 1, 3, [0.6, 0.3])]      # the best inside the limits
    assert rep.choose(m, top=1, caps=None)[-1]["name"] == ST[0]
