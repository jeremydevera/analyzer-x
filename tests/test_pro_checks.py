"""The Pro Trader research's pass checks (tradingagents/pro_checks.py), Oct 20,
2026 — written after the code review found every one of these untested and
four of them telling a different story from the numbers they read. Made-up
numbers, worked out by hand."""
from __future__ import annotations

import numpy as np

from tests.test_pro_report import _line
from tradingagents import pro_checks as pck, pro_report as pr, signals_pro as sp

NAMES = sp.variants(["brk", "rand"])
ME = "pt_brk_n0g0c0"                  # 20 bars, trend gate ON, calm gate OFF
GOOD = [(10, 4, 3.0)] * 4             # every test month: 10 trades, 4 wins, +$3


def _ix(rows, barriers=((0.004, 0.015),)):
    """rows: (setting name, vals) on coin 0, 15m, stop/target slot 0."""
    L = {"coins": ["A"], "names": NAMES, "fields": list(pr.FIELDS), "tfs": ["15m"],
         "barriers": {"barriers_15m": list(barriers)},
         "coin": np.zeros(len(rows), dtype=np.int32), "tf": np.zeros(len(rows), dtype=np.int8),
         "var": np.array([NAMES.index(n) for n, _v in rows]),
         "bar": np.zeros(len(rows), dtype=np.int8), "vals": np.array([v for _n, v in rows])}
    return pck.Index(L, pr.months(L))


def _trades(n, wins, win=1.3, loss=-0.6, cost=0.2):
    return [[0, 1, 1, "TP" if k < wins else "SL", win if k < wins else loss, cost] for k in range(n)]


def _got(cks):
    return {k: (ok, detail) for k, _label, ok, detail in cks}


def test_two_to_one_is_judged_on_the_fees_the_untouched_trades_paid():
    # 400 older trades at the usual 0.20% and 40 untouched ones that paid
    # 0.40%: the whole window averages 0.218% and would pass; the untouched
    # days do not (1.5 - 0.4 = 1.10 a win against 2 x (0.4 + 0.4) = 1.60)
    v = _line((400, 160, 60.0), GOOD, rt_before=0.2, rt_months=0.4)
    ix = _ix([(ME, v)])
    assert abs(float(v[pr.F["rt_paid"]]) - 0.2182) < 1e-3
    ok, detail = _got(pck.checks(ix, 0, 0, 0, "own pick", "g", [0], _trades(40, 16), None))["pay2"]
    assert ok is False and "0.400% round trip its untouched-days trades paid" in detail


def test_a_line_that_went_quiet_is_no_evidence_either_way():
    quiet = _line((60, 20, 30.0), [(0, 0, 0.0)] * 4)
    ix = _ix([(ME, _line((60, 20, 30.0), GOOD)), ("pt_brk_n1g0c0", quiet)])
    assert ix.oos(0, 0, "pt_brk_n1g0c0", 0) is None
    assert ix.oos(0, 0, ME, 0) == (40.0, 16.0, 12.0)


def test_the_neighbours_are_counted_and_averaged_out_loud():
    rows = [(ME, _line((60, 20, 30.0), GOOD)),
            ("pt_brk_n1g0c0", _line((60, 20, 30.0), [(10, 4, 5.0)] * 4)),     # +$20
            ("pt_brk_n0g1c0", _line((60, 20, 30.0), [(10, 2, -2.0)] * 4)),    # -$8
            ("pt_brk_n0g0c1", _line((60, 20, 30.0), [(0, 0, 0.0)] * 4))]      # quiet: left out
    ix = _ix(rows)
    ok, detail = _got(pck.checks(ix, 0, 0, 0, "own pick", "g", [0], _trades(40, 16), None))["plateau"]
    assert ok is True and detail.startswith("1 of 2 settings one step away made money; $+6.00")


def test_a_filter_with_nothing_to_compare_is_not_called_helpful():
    # the trend gate is ON; the same rule with it OFF never traded these days
    rows = [(ME, _line((60, 20, 30.0), GOOD)),
            ("pt_brk_n0g1c0", _line((60, 20, 30.0), [(0, 0, 0.0)] * 4))]
    ok, detail = _got(pck.checks(_ix(rows), 0, 0, 0, "own pick", "g", [0], _trades(40, 16), None))["filters"]
    assert ok is None and "nothing that traded" in detail
    # and when it did trade, the comparison is printed with both numbers
    rows[1] = ("pt_brk_n0g1c0", _line((60, 20, 30.0), [(12, 4, 4.0)] * 4))     # +$16 without it
    ok, detail = _got(pck.checks(_ix(rows), 0, 0, 0, "own pick", "g", [0], _trades(40, 16), None))["filters"]
    assert ok is False and "without gate: $+16.00" in detail and "$+12.00" in detail


def test_a_row_that_could_not_be_compared_with_luck_has_not_passed():
    cks = [("pay2", "", True, ""), ("wins", "", True, ""), ("range", "", True, ""),
           ("random", "", None, ""), ("stress", "", True, ""), ("plateau", "", True, ""),
           ("halves", "", None, ""), ("filters", "", None, ""), ("late", "", None, "")]
    assert pck.passed(cks) is False
    cks[3] = ("random", "", True, "")
    assert pck.passed(cks) is True                      # halves / filters not applicable is fine
    cks[5] = ("plateau", "", None, "")
    assert pck.passed(cks) is False
    cks[5] = ("plateau", "", True, "")
    cks[6] = ("halves", "", False, "")
    assert pck.passed(cks) is False


def test_the_stress_follows_the_position_it_was_measured_on():
    v = _line((60, 20, 30.0), GOOD)
    tr = _trades(40, 16)                                  # 24 losses at -$0.60, 16 wins at +$1.30
    a = _got(pck.checks(_ix([(ME, v)]), 0, 0, 0, "own pick", "g", [0], tr, None))["stress"][1]
    b = _got(pck.checks(_ix([(ME, v)]), 0, 0, 0, "own pick", "g", [0], tr, None, notional=200.0))["stress"][1]
    # 40 x 0.5 x 0.2% = $4.00 more cost and 24 x $0.10 on stops, on $100; twice that on $200
    assert "+$4.00 of extra cost and -$2.40 on stops" in a
    assert "+$8.00 of extra cost and -$4.80 on stops" in b
