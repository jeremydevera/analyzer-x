"""The v3 rules — one implementation for the engine and, later, the runner
(spec docs/superpowers/specs/2026-10-22-backtest-v3-design.md, Part 3).
Points are minutes (or Gate's 5-minute bars) in ms, all on ONE timeline."""
import pytest

from tradingagents import v3_rules as vr

M = 60_000
H = 3_600_000
T0 = 1_790_000_000_000 - (1_790_000_000_000 % H)


def test_a_touch_is_not_a_fill_a_trade_through_is():
    t = [T0, T0 + M, T0 + 2 * M]
    hi = [101.0, 100.0, 99.5]
    lo = [100.0, 99.0, 98.9]          # minute 1 touches 99.0, minute 2 trades below it
    assert vr.limit_fill(1, 99.0, t, hi, lo, T0, T0 + 3 * M) == T0 + 2 * M
    assert vr.limit_fill(1, 98.0, t, hi, lo, T0, T0 + 3 * M) is None
    assert vr.limit_fill(-1, 100.5, t, hi, lo, T0, T0 + 3 * M) == T0, "a sell fills above"
    assert vr.limit_fill(1, 99.0, t, hi, lo, T0, T0 + 2 * M) is None, "outside the window"


def test_a_stop_the_price_jumped_past_fills_where_the_price_was():
    assert vr.stop_fill(1, 98.0, 99.0, 97.0) == 98.0      # traded through 98.0
    assert vr.stop_fill(1, 98.0, 97.5, 97.0) == 97.5      # the whole minute was below it
    assert vr.stop_fill(-1, 102.0, 103.0, 101.0) == 102.0
    assert vr.stop_fill(-1, 102.0, 103.0, 102.5) == 102.5


def test_the_safe_leverage_keeps_the_stop_inside_80_percent_of_liquidation():
    # maintenance 0.5%: at 20x liquidation is 4.5% away and 80% of it 3.6%
    assert vr.safe_leverage(0.03, 0.005, 20) == 20
    assert vr.safe_leverage(0.05, 0.005, 20) == 14       # 15x leaves 4.93%, 14x 5.31%
    assert vr.safe_leverage(0.10, 0.005, 20) == 7        # 8x leaves 9.6%, 7x 11.03%
    assert vr.safe_leverage(0.80, 0.005, 20) is None     # even 1x leaves only 79.6%


def test_the_liquidation_ceiling_is_the_runners():
    import tradingagents.auto_trader as at

    assert vr.LIQ_CEILING == at.STOP_LIQ_CEILING


def test_one_dollar_of_risk_sizes_the_trade_and_less_than_one_lot_is_skipped():
    got = vr.risk_size(1.0, 100.0, 95.0, contract_size=0.01, min_vol=1, mmr=0.005,
                       max_lev=20)
    # a 5% stop: $20 of coin is 20 lots of 0.01 at $100, and 5% of $20 is $1.00
    assert got["contracts"] == 20 and got["notional"] == pytest.approx(20.0)
    assert got["risk_usd"] == pytest.approx(1.0) and got["leverage"] == 14
    assert got["margin"] == pytest.approx(20.0 / 14)
    # one BTC lot is 0.0001 x $100,000 = $10, so a 15% stop would risk $1.50
    assert vr.risk_size(1.0, 100_000.0, 85_000.0, contract_size=0.0001, min_vol=1,
                        mmr=0.004, max_lev=100) is None
    assert vr.risk_size(1.0, 100.0, 20.0, contract_size=0.01, min_vol=1, mmr=0.005,
                        max_lev=20) is None, "an 80% stop has no safe leverage"


def test_the_trailing_stop_is_checked_before_it_moves_and_never_loosens():
    t = [T0 + k * M for k in range(5)]
    hi = [101.0, 104.0, 103.0, 103.5, 102.0]
    lo = [100.0, 102.0, 101.5, 100.9, 100.5]
    # a long, stop 97, distance 3: minute 1's high 104 lifts the stop to 101,
    # minute 2's lower high leaves it there, minute 3's low 100.9 takes it
    exit_ms, px = vr.trail_walk(1, 97.0, 3.0, t, hi, lo, T0, T0 + 5 * M)
    assert exit_ms == T0 + 3 * M and px == pytest.approx(101.0)
    exit_ms, stop = vr.trail_walk(1, 97.0, 3.0, t, hi, lo, T0, T0 + 3 * M)
    assert exit_ms is None and stop == pytest.approx(101.0)
    # a short mirrors it: the stop follows the lows down
    exit_ms, stop = vr.trail_walk(-1, 103.0, 3.0, t[:2], [100.5, 98.5], [99.0, 96.0],
                                  T0, T0 + 2 * M)
    assert exit_ms is None and stop == pytest.approx(99.0)


def test_a_trail_the_price_jumped_past_exits_at_the_best_price_traded():
    t = [T0, T0 + M]
    # minute 0 lifts the stop to 99.5; minute 1 trades only 97.0-98.0, below it
    exit_ms, px = vr.trail_walk(1, 99.0, 1.0, t, [100.5, 98.0], [99.8, 97.0], T0, T0 + 2 * M)
    assert exit_ms == T0 + M and px == pytest.approx(98.0)


def test_atr_and_sma_wait_for_their_window():
    hi, lo, close = [11.0, 12.0, 13.0], [9.0, 10.0, 11.0], [10.0, 11.0, 12.0]
    assert vr.atr(hi, lo, close, 2) == [None, pytest.approx(2.0), pytest.approx(2.0)]
    assert vr.sma(close, 2) == [None, pytest.approx(10.5), pytest.approx(11.5)]


def test_funding_is_paid_settlement_by_settlement_and_estimated_before_the_history():
    f_ms, f_rate, f_cyc = [T0 + 8 * H, T0 + 16 * H], [0.0001, 0.0003], [8.0, 8.0]
    # the history answers from T0, one cycle before its first settlement
    paid, est = vr.funding_paid(f_ms, f_rate, f_cyc, 1, T0, T0 + 16 * H)
    assert paid == pytest.approx(0.0004) and est is False
    paid, est = vr.funding_paid(f_ms, f_rate, f_cyc, -1, T0, T0 + 16 * H)
    assert paid == pytest.approx(-0.0004) and est is False, "a short receives what a long pays"
    # 8 hours before the history: one cycle at the average known rate, 0.0002
    paid, est = vr.funding_paid(f_ms, f_rate, f_cyc, 1, T0 - 8 * H, T0 + 8 * H)
    assert paid == pytest.approx(0.0002 + 0.0001) and est is True
    assert vr.funding_paid([], [], [], 1, T0, T0 + 8 * H) == (0.0, True), \
        "no history is never a measured zero"
