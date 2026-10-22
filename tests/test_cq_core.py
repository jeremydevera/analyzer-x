"""The confluence search (tradingagents/cq_core.py), Oct 21, 2026, on a
made-up world: scores, payouts, rounds, early stopping, and the rule that
keeps the test days a test - the search never reads them."""
from __future__ import annotations

import itertools
import random

import pytest

from tradingagents import cq_core as cq

N_E, N_B = 60, 8
BARRIERS = [(0.004 + 0.001 * b, 0.02 + 0.004 * b) for b in range(N_B)]
BUCKETS = [cq.PAYOUTS[b % 4] for b in range(N_B)]


def _world(tst_noise=0, flat_check=False, min_t=12):
    """Entry e has a hidden quality; its tuning and check win rates follow it
    with noise, its test days are noise of their own."""
    rnd = random.Random(0)
    q = [rnd.random() for _ in range(N_E)]
    calls = []

    def evaluate(cands):
        calls.append(list(cands))
        out = {}
        for e, b in cands:
            h = random.Random(e * 1000 + b)
            t = 10 + int(q[e] * 80)
            if t < min_t:
                out[(e, b)] = None
                continue
            w = min(t, int(t * (0.2 + 0.5 * q[e]) + h.random() * 3))
            ct = t // 3
            cw = 0 if flat_check else min(ct, int(ct * (0.2 + 0.5 * q[e]) + h.random() * 2))
            tt = t // 2
            tw = random.Random(tst_noise * 7919 + e * 31 + b).randint(0, tt)
            out[(e, b)] = cq.Stats(cq.Part(t, w, 0.0, t * 0.23), cq.Part(ct, cw, 0.0, ct * 0.23),
                                   cq.Part(tt, tw, float(tst_noise), tt * 0.23))
        return out

    return evaluate, calls


def _nbrs(e):
    return [x for x in (e - 1, e + 1) if 0 <= x < N_E]


def _run(seed=1, world=None, **kw):
    evaluate, calls = world or _world()
    kw.setdefault("round_size", 30)
    res = cq.search(N_E, BARRIERS, BUCKETS, evaluate, seed=seed, neighbours_of=_nbrs,
                    c_usual=0.0023, **kw)
    return res, calls


def test_the_worst_case_win_rate_is_wilsons_low_end():
    assert cq.wilson_low(0, 0) == 0.0
    assert cq.wilson_low(3, 3) == pytest.approx(0.526, abs=0.002)
    assert cq.wilson_low(90, 200) == pytest.approx(0.393, abs=0.002)
    assert cq.wilson_low(30, 40) == pytest.approx(0.624, abs=0.002)


def test_a_stop_target_is_classed_by_what_a_win_pays_after_the_round_trip():
    c = 0.0023
    assert cq.bucket(cq.payout_of(0.005, 0.02, c)) == 2       # 2.42
    assert cq.bucket(cq.payout_of(0.005, 0.03, c)) == 3       # 3.79
    assert cq.bucket(cq.payout_of(0.004, 0.04, c)) == 5       # 5.98
    assert cq.bucket(cq.payout_of(0.01, 0.02, c)) is None     # 1.44: never a candidate


def test_worst_r_reads_the_round_trip_the_trades_paid():
    p = cq.Part(40, 16, 0.0, 40 * 0.25)
    k = (0.02 - 0.0025) / (0.005 + 0.0025)
    assert cq.worst_r(p, 0.005, 0.02, 0.0023) == pytest.approx(cq.wilson_low(16, 40) * (k + 1) - 1)
    assert cq.worst_r(cq.EMPTY, 0.005, 0.02, 0.0023) is None


def test_a_run_repeats_exactly_from_its_seed():
    a, _ = _run(seed=7)
    b, _ = _run(seed=7)
    c, _ = _run(seed=8)
    assert a == b
    assert a["rounds"][0] != c["rounds"][0]


def test_no_candidate_is_tried_twice_and_rounds_keep_their_size():
    res, calls = _run(max_rounds=12)
    flat = list(itertools.chain.from_iterable(calls))
    assert len(flat) == len(set(flat)) == res["tried"]
    assert all(len(x) <= 30 for x in calls) and len(res["rounds"]) <= 12


def test_the_test_days_never_change_a_choice():
    a, _ = _run(world=_world(tst_noise=0))
    b, _ = _run(world=_world(tst_noise=99))
    strip = ("stats",)
    assert {k: v for k, v in a.items() if k not in strip} == \
        {k: v for k, v in b.items() if k not in strip}


def test_a_pick_is_a_champion_and_the_final_has_the_best_check_days_r():
    res, _ = _run(max_rounds=8)
    assert res["picks"]
    for k, cd in res["picks"].items():
        assert cd in res["champions"][k]
        assert BUCKETS[cd[1]] == k
    k0, cd0 = res["final"]
    r = {k: cq.worst_r(res["stats"][cd].chk, *BARRIERS[cd[1]], 0.0023)
         for k, cd in res["picks"].items()}
    assert r[k0] == max(v for v in r.values() if v is not None)
    assert res["picks"][k0] == cd0


def test_a_candidate_with_too_few_tuning_trades_is_never_a_champion():
    res, _ = _run(min_trades=50, max_rounds=8)
    for k in cq.PAYOUTS:
        for cd in res["champions"][k]:
            assert res["stats"][cd].tun.trades >= 50


def test_it_stops_when_no_payout_improves_for_patience_rounds():
    res, _ = _run(world=_world(flat_check=True), patience=3)
    assert res["stop"] == "patience" and len(res["rounds"]) == 4


def test_a_small_space_is_exhausted():
    evaluate, calls = _world()
    res = cq.search(3, BARRIERS[:2], BUCKETS[:2], evaluate, seed=3, neighbours_of=lambda e: [],
                    c_usual=0.0023, round_size=4)
    assert res["stop"] == "exhausted" and res["tried"] == 6
    assert [len(x) for x in calls] == [4, 2]


def test_later_rounds_search_around_the_best():
    res, calls = _run(max_rounds=2)
    best = res["rounds"][0]["best"]
    near = {(e2, b) for e, b in best for e2 in _nbrs(e)}
    assert near & set(calls[1])


def test_a_deadline_stops_between_rounds():
    ticks = iter(range(100))
    res, _ = _run(deadline=2, clock=lambda: next(ticks))
    assert res["stop"] == "deadline" and len(res["rounds"]) == 2
