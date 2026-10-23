"""The v3 engine shares two existing rules instead of copying them (spec
docs/superpowers/specs/2026-10-22-backtest-v3-design.md, Part 3): the minute
settle learns a target that RESTS as a waiting order (it must be traded
through), and the runner's cost check learns a waiting-order entry. Both
default to the rule of before."""
import numpy as np
import pytest

from tradingagents import auto_trader as at

M = 60_000
T0 = 1_790_000_000_000 - (1_790_000_000_000 % 3_600_000)


def _minutes(hl):
    t = np.array([T0 + k * M for k in range(len(hl))], dtype="int64")
    return t, np.array([x[0] for x in hl]), np.array([x[1] for x in hl])


def test_a_resting_target_needs_a_trade_through_a_touch_is_not_enough():
    t, hi, lo = _minutes([(101.0, 99.5), (101.2, 100.5)])    # minute 0 touches 101.0
    assert at.settle_in_minutes(t, hi, lo, T0, 3600, 1, 101.0, 98.0, None,
                                liq=None, sl=0.02)[0] == "TP", "the rule of before"
    got = at.settle_in_minutes(t, hi, lo, T0, 3600, 1, 101.0, 98.0, None,
                               liq=None, sl=0.02, tp_through=True)
    assert got[:2] == ("TP", T0 + M), "filled the minute it traded above"
    t, hi, lo = _minutes([(100.5, 99.0), (100.0, 98.8)])     # a short's target, 99.0
    assert at.settle_in_minutes(t, hi, lo, T0, 3600, -1, 99.0, 102.0, None, liq=None,
                                sl=0.02, tp_through=True)[:2] == ("TP", T0 + M)


def test_stop_and_resting_target_in_one_minute_is_the_stop_and_unclear():
    t, hi, lo = _minutes([(101.5, 97.5)])
    assert at.settle_in_minutes(t, hi, lo, T0, 3600, 1, 101.0, 98.0, None, liq=None,
                                sl=0.02, tp_through=True) == ("SL", T0, 1)


def test_a_waiting_order_pays_gates_published_maker_fee_never_the_rebate():
    assert at.maker_fee_floor("gate") == pytest.approx(0.0002)
    assert at.maker_fee_floor("mexc") == at.fee_floor("mexc"), "never measured: its taker floor"


READING = {"t": 0, "age_s": 0, "bid": 99.9, "ask": 100.1, "spread": 0.002,
           "buy": 0.001, "sell": 0.0012, "exhausted": False, "source": 1}


def test_a_market_entry_is_judged_exactly_as_before():
    cv = at.minute_verdict(READING, side=1, tp=0.02, sl=0.01, fee=0.00075,
                           hold_s=3600, liq=0.036, fund_day=0.0)
    assert cv["round_trip"] == pytest.approx(2 * (0.001 + 0.00075))
    assert cv["slippage"] == pytest.approx(0.001)


def test_a_waiting_entry_pays_the_maker_fee_in_and_the_taker_and_gap_out():
    cv = at.minute_verdict(READING, side=1, tp=0.02, sl=0.01, fee=0.00075,
                           hold_s=3600, liq=0.036, fund_day=0.0,
                           entry="limit", maker_fee=0.0002)
    # a long: in 0.02% (maker, no gap), out 0.075% plus the SELL side 0.12%
    assert cv["round_trip"] == pytest.approx(0.0002 + 0.00075 + 0.0012)
    assert cv["slippage"] == 0.0, "a waiting order's fill pays no gap"
    short = at.minute_verdict(READING, side=-1, tp=0.02, sl=0.01, fee=0.00075,
                              hold_s=3600, liq=0.036, fund_day=0.0,
                              entry="limit", maker_fee=0.0002)
    assert short["round_trip"] == pytest.approx(0.0002 + 0.00075 + 0.001)


def test_a_waiting_entry_is_never_refused_as_a_chase():
    ran = {**READING, "ask": 104.0, "bid": 103.8}    # the price ran 4% from the 100.0 close
    assert at.entry_refusal(ran, side=1, signal_close=100.0, tp=0.02, sl=0.01,
                            fee=0.00075, hold_s=3600, liq=0.036,
                            fund_day=0.0)[0] == "chase_skip"
    assert at.entry_refusal(ran, side=1, signal_close=100.0, tp=0.02, sl=0.01,
                            fee=0.00075, hold_s=3600, liq=0.036, fund_day=0.0,
                            entry="limit", maker_fee=0.0002)[0] == ""


def test_the_fixed_stop_reads_a_touch_exactly_as_stop_reached_does():
    """One touch rule kept in two places (parked at the final review of Backtest v3 Part 1):
    `settle_in_minutes` reads a fixed stop at a minute the archive holds (the shared v2 settle,
    `lw <= sl_px`), `v3_rules.stop_reached` everything else. A long's low AT its stop stops it in
    both, a low a hair above it in neither - and a short mirrors it."""
    from tradingagents import v3_rules as vr

    for s, stop, tp, touch, miss in ((1, 98.0, 110.0, (99.0, 98.0), (99.0, 98.01)),
                                     (-1, 102.0, 90.0, (102.0, 101.0), (101.99, 101.0))):
        for (hi, lo), hit in ((touch, True), (miss, False)):
            t, h, lw = _minutes([(hi, lo)])
            got = at.settle_in_minutes(t, h, lw, T0, 3600, s, tp, stop, None, liq=None,
                                       sl=0.02, tp_through=True)
            assert (got[0] == "SL") is hit, (s, hi, lo)
            assert vr.stop_reached(s, stop, hi, lo) is hit, (s, hi, lo)
