"""Picking on older days, judging on days never seen (tradingagents/pro_report.py,
Oct 20, 2026). Every number below is made up and worked out by hand."""
from __future__ import annotations

import numpy as np
import pytest

from tradingagents import pro_report as pr

# one 15m stop/target: SL 0.4% / TP 1.5%. At a 0.2% round trip a win is
# +1.30 and a loss -0.60 (pays 2:1); at 0.5% it is +1.00 against -0.90 (not)
BARS = {"barriers_15m": [(0.004, 0.015)]}
NAMES = ["pt_aaa_x0", "pt_aaa_x1", "pt_aaa_x2", "pt_aaa_x3", "pt_rand_s0r0"]


def _line(before, months, rt_before=0.2, rt_months=0.2):
    """vals for one line: `before` = (trades, wins, profit) on the choosing
    days before the four months, `months` = [(t, w, p)] for months 1..4
    (oldest first); round trips paid per trade on each side of that line."""
    v = np.zeros(len(pr.FIELDS))
    mt = np.asarray(months, dtype=float)
    tot = np.asarray(before, dtype=float) + mt.sum(axis=0)
    v[pr.F["trades"]], v[pr.F["wins"]], v[pr.F["profit"]] = tot
    for days, first in ((120, 0), (90, 1), (60, 2), (30, 3)):
        part = mt[first:].sum(axis=0)
        v[pr.F[f"t{days}"]], v[pr.F[f"w{days}"]], v[pr.F[f"p{days}"]] = part
        v[pr.F[f"c{days}"]] = part[0] * rt_months
    v[pr.F["rt_paid"]] = (before[0] * rt_before + mt[:, 0].sum() * rt_months) / tot[0]
    return v


def _lines(rows, coins=("A", "B", "C")):
    """rows: (coin index, var index into NAMES, vals)."""
    return {"coins": list(coins), "names": NAMES, "fields": list(pr.FIELDS), "tfs": ["15m"],
            "barriers": BARS, "coin": np.array([r[0] for r in rows]),
            "tf": np.zeros(len(rows), dtype=np.int8), "var": np.array([r[1] for r in rows]),
            "bar": np.zeros(len(rows), dtype=np.int8), "vals": np.array([r[2] for r in rows])}


GOOD = [(5, 2, 1.0)] * 4


def test_the_months_are_cut_from_the_closing_counts():
    v = _line((35, 14, 3.5), [(10, 4, 1.0), (20, 8, 2.0), (30, 12, 3.0), (5, 2, 0.5)])
    mon = pr.months({"vals": np.array([v]), "fields": list(pr.FIELDS)})
    assert mon[0, 0].tolist() == [35, 14, 3.5]
    assert [mon[0, k, 0] for k in range(1, 5)] == [10, 20, 30, 5]


def test_lines_written_with_other_fields_are_refused():
    with pytest.raises(ValueError, match="fields"):
        pr.months({"vals": np.zeros((1, 3)), "fields": ["trades", "wins", "profit"]})


def test_coins_are_grouped_by_what_they_are_and_small_groups_join_wider_ones():
    stats = {f"C{i}": {"vol": 1.0 + i, "vr": 1.2 if i % 2 else 0.8, "kind": "crypto"} for i in range(30)}
    stats.update({f"S{i}": {"vol": 1.0, "vr": 1.1, "kind": "stocks"} for i in range(3)})
    stats["X"] = {"error": "no candles"}
    g = pr.groups(stats)
    assert "X" not in g and g["S0"] == "stocks"
    assert g["C0"] == "crypto-quiet" and g["C29"] == "crypto-wild"


def test_two_to_one_is_judged_on_the_fees_the_choosing_days_paid():
    # x0: cheap before the months (0.2%), dear in them (0.5%): a candidate
    # before month 1 although the whole window's average fails 2:1
    # x1: dear before (0.5%), cheap in them: never a candidate before month 1
    rows = [(0, 0, _line((40, 20, 30.0), GOOD, rt_before=0.2, rt_months=0.5)),
            (0, 1, _line((40, 20, 30.0), GOOD, rt_before=0.5, rt_months=0.2))]
    L = _lines(rows)
    whole = L["vals"][:, pr.F["rt_paid"]]             # 0.30% and 0.40% over the window
    for c in whole:                                    # both whole-window averages fail 2:1
        assert (1.5 - c) + pr.PAY_SLACK < pr.PAY_RATIO * (0.4 + c)
    ok = pr.candidates(L, 1)
    assert ok.tolist() == [True, False]


def test_the_random_baseline_is_never_chosen():
    rows = [(0, 4, _line((60, 30, 90.0), GOOD)),      # pt_rand: the best by far
            (0, 0, _line((60, 20, 10.0), GOOD))]
    L = _lines(rows)
    picks = pr.choose(L, pr.months(L), {"A": "g"}, upto=1)
    assert picks[(0, 0)][0] == 1


def test_a_pick_must_have_made_money_on_its_choosing_days():
    rows = [(0, 0, _line((60, 20, -5.0), GOOD))]
    L = _lines(rows)
    assert pr.choose(L, pr.months(L), {"A": "g"}, upto=1) == {}


def test_a_coin_keeps_its_own_pick_only_when_it_beat_the_group_default():
    rows = [(0, 0, _line((60, 20, 30.0), GOOD)),     # setting x0: the group's best on A + B
            (1, 0, _line((60, 20, 30.0), GOOD)),
            (0, 1, _line((60, 20, 40.0), GOOD)),     # A's own x1 beat x0 there by $10
            (1, 2, _line((60, 20, 30.5), GOOD))]     # B's own x2 only by $0.50
    L = _lines(rows)
    picks = pr.choose(L, pr.months(L), {"A": "g", "B": "g"}, upto=1)
    assert picks[(0, 0)] == (2, "own pick")
    assert picks[(1, 0)] == (1, "group default")


def test_the_choice_never_reads_the_month_it_is_judged_on():
    s1 = [(10, 1, -10.0), (10, 1, -10.0), (10, 9, 30.0), (10, 9, 30.0)]
    s2 = [(10, 9, 30.0), (10, 9, 30.0), (10, 1, -10.0), (10, 1, -10.0)]
    rows = [(0, 0, _line((40, 15, 20.0), s1)), (0, 1, _line((40, 10, 5.0), s2))]
    L = _lines(rows)
    mon = pr.months(L)
    assert pr.choose(L, mon, {"A": "g"}, upto=1)[(0, 0)][0] == 0
    wf = pr.walk_forward(mon, L, {"A": "g"})[(0, 0)]
    # before month 2: +10 vs +35 -> x1; before 3: 0 vs 65; before 4: 30 vs 55
    assert [m[0] for m in wf] == [0, 1, 1, 1]
    assert [m[4] for m in wf] == [-10.0, 30.0, -10.0, -10.0]
    main = pr.judged(mon, pr.choose(L, mon, {"A": "g"}, upto=1), 1, 4)[(0, 0)]
    assert main == (40.0, 20.0, 40.0)
