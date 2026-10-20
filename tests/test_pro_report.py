"""Picking on older days, judging on days never seen (tradingagents/pro_report.py,
Oct 20, 2026). Every number below is made up and worked out by hand."""
from __future__ import annotations

import numpy as np

from tradingagents import pro_report as pr

FIELDS = list(pr.F)


def _line(total, months, pay2=1.0, rt=0.2):
    """vals for one line: `total` = (trades, wins, profit) over the whole
    window, `months` = [(t, w, p)] for test months 1..4 (oldest first)."""
    v = np.zeros(len(FIELDS))
    v[pr.F["trades"]], v[pr.F["wins"]], v[pr.F["profit"]] = total
    # t120 = months 1..4, t90 = months 2..4, t60 = 3..4, t30 = 4
    for days, first in ((120, 0), (90, 1), (60, 2), (30, 3)):
        part = np.sum(np.asarray(months[first:], dtype=float), axis=0)
        v[pr.F[f"t{days}"]], v[pr.F[f"w{days}"]], v[pr.F[f"p{days}"]] = part
    v[pr.F["rt_paid"]], v[pr.F["pay2"]] = rt, pay2
    return v


def _lines(rows):
    """rows: (coin index, tf index, var, bar, vals)."""
    return {"coins": ["A", "B", "C"], "coin": np.array([r[0] for r in rows]),
            "tf": np.array([r[1] for r in rows]), "var": np.array([r[2] for r in rows]),
            "bar": np.array([r[3] for r in rows]), "vals": np.array([r[4] for r in rows])}


def test_the_months_are_cut_from_the_closing_counts():
    v = _line((100, 40, 10.0), [(10, 4, 1.0), (20, 8, 2.0), (30, 12, 3.0), (5, 2, 0.5)])
    mon = pr.months({"vals": np.array([v])})
    assert mon[0, 0].tolist() == [35, 14, 3.5]                 # before the four months
    assert [mon[0, k, 0] for k in range(1, 5)] == [10, 20, 30, 5]
    assert mon[0].sum(axis=0).tolist() == [100, 40, 10.0]


def test_coins_are_grouped_by_what_they_are_and_small_groups_join_wider_ones():
    stats = {f"C{i}": {"vol": 1.0 + i, "vr": 1.2 if i % 2 else 0.8, "kind": "crypto"} for i in range(30)}
    stats.update({f"S{i}": {"vol": 1.0, "vr": 1.1, "kind": "stocks"} for i in range(3)})
    stats["X"] = {"error": "no candles"}
    g = pr.groups(stats)
    assert "X" not in g
    assert g["S0"] == "stocks"                                  # 3 stock tokens: one group
    assert g["C0"].startswith("crypto-quiet") and g["C29"].startswith("crypto-wild")
    # 30 crypto coins, 10 a third, 5 trending + 5 snapping back -> too small, the third stays
    assert g["C0"] == "crypto-quiet"


def test_a_coin_keeps_its_own_pick_only_when_it_beat_the_group_default_on_choosing_days():
    good = [(5, 2, 1.0)] * 4
    rows = [
        # setting 1 is the group's best before the months on coins A and B together
        (0, 0, 1, 0, _line((60, 20, 30.0), good)),
        (1, 0, 1, 0, _line((60, 20, 30.0), good)),
        # coin A's own setting 2 beat setting 1 on A's choosing days by $10
        (0, 0, 2, 0, _line((60, 20, 40.0), good)),
        # coin B's setting 3 made only $0.50 more on B: under the $1 margin
        (1, 0, 3, 0, _line((60, 20, 30.5), good)),
        # a setting that does not pay 2:1 after fees is never a candidate
        (1, 0, 4, 0, _line((60, 20, 99.0), good, pay2=0.0)),
    ]
    L = _lines(rows)
    mon = pr.months(L)
    picks = pr.choose(L, mon, {"A": "g", "B": "g"}, upto=1)
    assert picks[(0, 0)] == (2, "own pick")
    assert picks[(1, 0)] == (1, "group default")


def test_the_choice_never_reads_the_month_it_is_judged_on():
    """Setting 1 led before the months, setting 2 won the first month. Each
    month's pick may use only what closed before that month."""
    s1 = [(10, 1, -10.0), (10, 1, -10.0), (10, 9, 30.0), (10, 9, 30.0)]
    s2 = [(10, 9, 30.0), (10, 9, 30.0), (10, 1, -10.0), (10, 1, -10.0)]
    rows = [(0, 0, 1, 0, _line((80, 35, 60.0), s1)),     # before the months: 40 trades, +20
            (0, 0, 2, 0, _line((80, 30, 45.0), s2))]     # before the months: 40 trades, +5
    L = _lines(rows)
    mon = pr.months(L)
    assert mon[0, 0].tolist() == [40, 15, 20.0] and mon[1, 0].tolist() == [40, 10, 5.0]
    assert pr.choose(L, mon, {"A": "g"}, upto=1)[(0, 0)][0] == 0
    wf = pr.walk_forward(mon, L, {"A": "g"})[(0, 0)]
    # before month 2: +10 vs +35 -> setting 2; before 3: 0 vs 65; before 4: 30 vs 55
    assert [m[0] for m in wf] == [0, 1, 1, 1]
    assert [m[4] for m in wf] == [-10.0, 30.0, -10.0, -10.0]
    main = pr.judged(mon, pr.choose(L, mon, {"A": "g"}, upto=1), 1, 4)[(0, 0)]
    assert main == (40.0, 20.0, 40.0)                    # setting 1 over the four months
