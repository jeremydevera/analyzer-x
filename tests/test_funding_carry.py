"""Funding carry (long spot + short perp): earnings are the SUM OF PUBLISHED SETTLEMENTS, wins and
losses alike, fees once in and once out, and a coin that cannot be carried is named, never dropped.
Plan: docs/superpowers/plans/2026-11-04-daily-trend-long-window-and-funding-carry.md (Task 3)."""
import pytest

from tradingagents import funding_carry as fc

H = 3_600_000
DAY = 24 * H


def _rows(start, every_h, rates):
    return [{"settle_ms": start + i * every_h * H, "rate": r} for i, r in enumerate(rates)]


def test_earned_sums_published_settlements_not_a_formula():
    eight = _rows(0, 8, [0.0001] * 3)       # one day, 3 settlements
    four = _rows(0, 4, [0.0001] * 6)        # the same day, 6 settlements
    a = fc.carry_open(eight, 0, 1.0, 0.0, 0.0)
    b = fc.carry_open(four, 0, 1.0, 0.0, 0.0)
    assert a["settlements"] == 3 and b["settlements"] == 6
    assert b["earned"] == pytest.approx(2 * a["earned"])


def test_negative_funding_is_a_loss():
    r = fc.carry_open(_rows(0, 8, [-0.0001] * 3), 0, 1.0, 0.0, 0.0)
    assert r["earned"] == pytest.approx(-0.0003)
    assert r["net"] < 0


def test_fees_are_charged_once_in_once_out():
    r = fc.carry_open(_rows(0, 8, [0.0001] * 3), 0, 1.0, 0.002, 0.003)
    assert r["fees"] == pytest.approx(0.005)
    assert r["net"] == pytest.approx(0.0003 - 0.005)


def test_min_running_is_the_worst_dip_not_the_final_sum():
    r = fc.carry_open(_rows(0, 8, [0.0002, 0.0002, -0.0003, -0.0003, -0.0003]), 0, 2.0, 0.0, 0.0)
    assert r["min_running"] == pytest.approx(-0.0005)    # after the fifth settlement
    assert r["earned"] == pytest.approx(-0.0005)
    r2 = fc.carry_open(_rows(0, 8, [-0.0003, 0.0004, 0.0004]), 0, 1.0, 0.0, 0.0)
    assert r2["min_running"] == pytest.approx(-0.0003)
    assert r2["earned"] == pytest.approx(0.0005)


def test_only_settlements_inside_the_hold_count():
    rows = _rows(0, 8, [0.0001] * 12)       # 4 days
    r = fc.carry_open(rows, 1 * DAY, 1.0, 0.0, 0.0)
    assert r["settlements"] == 3


def test_scan_names_a_coin_without_spot_and_one_with_too_little_history():
    hist = {"AAA_USDT": _rows(0, 8, [0.0002] * 300), "BBB_USDT": _rows(0, 8, [0.0002] * 300),
            "SHORT_USDT": _rows(0, 8, [0.0002] * 3)}
    out = fc.scan(hist, {"AAA_USDT", "SHORT_USDT"}, hold_days=30, fee=0.0055)
    names = {r["coin"] for r in out["rows"]}
    assert names == {"AAA_USDT"}
    why = {c["coin"]: c["why"] for c in out["left_out"]}
    assert why["BBB_USDT"] == "no spot market"
    assert "history" in why["SHORT_USDT"]


def test_scan_row_says_how_often_a_start_day_ends_above_zero():
    # 100 days of +0.01% every 8h = +0.03%/day; a 30-day hold earns 0.9%, a 0.55% fee leaves +0.35%
    hist = {"AAA_USDT": _rows(0, 8, [0.0001] * 300)}
    row = fc.scan(hist, {"AAA_USDT"}, hold_days=30, fee=0.0055)["rows"][0]
    assert row["share_positive"] == pytest.approx(1.0)
    assert row["median_net"] == pytest.approx(0.009 - 0.0055, abs=1e-4)
    assert row["history_days"] == pytest.approx(99.67, abs=0.5)
    # a fee above what 30 days can earn: never positive
    row = fc.scan(hist, {"AAA_USDT"}, hold_days=30, fee=0.02)["rows"][0]
    assert row["share_positive"] == 0.0


def test_walk_forward_reads_only_funding_before_the_start_day():
    # coin GOOD pays +0.02% every 8h for 60 days then NOTHING after day 60; the 30 filler coins pay 0.
    # Picked by its past it must be chosen at the first starts; a hold that begins after day 60 pays 0.
    days = 100
    good = _rows(0, 8, [0.0002 if i < 60 * 3 else 0.0 for i in range(days * 3)])
    hist = {"GOOD_USDT": good}
    for k in range(30):
        hist[f"F{k}_USDT"] = _rows(0, 8, [0.0] * (days * 3))
    out = fc.walk_forward(hist, set(hist), hold_days=10, fee=0.0, top_n=1, lookback_days=10, step_days=10)
    assert out["starts"] >= 5
    assert out["picked"] > out["random"] > -1e-12           # picked by the past, it beat random
    # the pick at the start after day 60 had a past of +, a future of 0: the average is below the first starts'
    assert out["picked"] < 0.0002 * 30


def test_walk_forward_skips_days_with_too_few_coins_and_says_so():
    hist = {"A_USDT": _rows(0, 8, [0.0001] * 300), "B_USDT": _rows(0, 8, [0.0001] * 300)}
    out = fc.walk_forward(hist, set(hist), hold_days=10, fee=0.0, top_n=5, lookback_days=10)
    assert out["starts"] == 0 and out["skipped_starts"] > 0
