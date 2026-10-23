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


def test_a_sell_touch_is_not_a_fill():
    # Pins: a sell fills only when its high is strictly ABOVE the limit, the mirror of the
    # buy rule above. A high of exactly 101.0 on a sell at 101.0 is a touch, so no fill.
    assert vr.limit_fill(-1, 101.0, [T0], [101.0], [100.0], T0, T0 + M) is None


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


def test_safe_leverage_is_strictly_inside_the_ceiling():
    # Pins: the stop must sit STRICTLY inside the ceiling. At 2x the liquidation distance is
    # 1/2 = 0.5 and the ceiling takes half of that: 0.25. A stop of exactly 0.25 sits on the
    # line, not inside it, so the answer is 1x.
    assert vr.safe_leverage(0.25, 0.0, 2, ceiling=0.5) == 1


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


def test_a_lot_count_on_the_float_boundary_keeps_its_lot():
    # Pins: the 1e-9 allowance keeps a count that is exact in theory from losing a lot to
    # float division. A 0.5% stop at $5 with $1 of risk on 0.01-coin lots is 4000 lots in
    # theory; the float division gives 3999.999999999943, which int() would cut to 3999.
    got = vr.risk_size(1.0, 5.0, 4.975, contract_size=0.01, min_vol=1, mmr=0.005, max_lev=20)
    assert got["contracts"] == 4000


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


def test_a_long_stop_is_checked_before_it_moves_even_on_a_point_wider_than_the_trail():
    # Pins: each point checks the stop BEFORE it moves. This point's high (110) is far above
    # its low (100), wider than the 3.0 trail. Checked first, the low is above the stop (97),
    # so there is no exit and the stop rises to 110 - 3 = 107. Moved first, the stop would be
    # 107 and this same point's low of 100 would exit it.
    exit_ms, stop = vr.trail_walk(1, 97.0, 3.0, [T0], [110.0], [100.0], T0, T0 + M)
    assert exit_ms is None and stop == pytest.approx(107.0)


def test_a_short_stop_is_checked_before_it_moves_even_on_a_point_wider_than_the_trail():
    # Pins: the short mirror of check-then-move. This point's high (100) is below the stop
    # (103), so there is no exit and the stop falls to 90 + 3 = 93. Moved first, the stop
    # would be 93 and this point's high of 100 would exit it.
    exit_ms, stop = vr.trail_walk(-1, 103.0, 3.0, [T0], [100.0], [90.0], T0, T0 + M)
    assert exit_ms is None and stop == pytest.approx(93.0)


def test_a_short_trail_exits_when_the_price_comes_back_up_through_it():
    # Pins: the short exit path. Minute 0 lowers the stop to 99 + 3 = 102. Minute 1 trades
    # up to 105, through the stop; its low (102) touches the stop, so the exit is at 102.
    t = [T0, T0 + M]
    exit_ms, px = vr.trail_walk(-1, 103.0, 3.0, t, [100.5, 105.0], [99.0, 102.0],
                                T0, T0 + 2 * M)
    assert exit_ms == T0 + M and px == pytest.approx(102.0)


def test_a_short_stop_never_loosens_when_the_price_bounces():
    # Pins: a short's stop only moves DOWN. Minute 0 lowers it to 99 + 3 = 102. Minute 1
    # bounces to a low of 100, which would lift the trail to 103 (looser), so it stays at 102.
    t = [T0, T0 + M]
    exit_ms, stop = vr.trail_walk(-1, 103.0, 3.0, t, [100.5, 101.0], [99.0, 100.0],
                                  T0, T0 + 2 * M)
    assert exit_ms is None and stop == pytest.approx(102.0)


def test_atr_and_sma_wait_for_their_window():
    hi, lo, close = [11.0, 12.0, 13.0], [9.0, 10.0, 11.0], [10.0, 11.0, 12.0]
    assert vr.atr(hi, lo, close, 2) == [None, pytest.approx(2.0), pytest.approx(2.0)]
    assert vr.sma(close, 2) == [None, pytest.approx(10.5), pytest.approx(11.5)]


def test_atr_counts_the_gap_from_the_previous_close():
    # Pins: the true range includes the gap from the previous close. Bar 1 trades 19-21, but
    # bar 0 closed at 10, so its true range is 21 - 10 = 11, not 21 - 19 = 2. ATR(2) is
    # (2 + 11) / 2 = 6.5; a plain high-low average would give 2.0.
    assert vr.atr([11.0, 21.0], [9.0, 19.0], [10.0, 20.0], 2) == [None, 6.5]


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


def test_a_settlement_at_entry_is_not_paid_and_one_at_exit_is():
    # Pins: a settlement is paid when it falls in (entry, exit]. A hold that opens exactly at
    # the 8h settlement pays only the 16h one: 0.0003, not 0.0003 + 0.0001.
    f_ms, f_rate, f_cyc = [T0 + 8 * H, T0 + 16 * H], [0.0001, 0.0003], [8.0, 8.0]
    paid, est = vr.funding_paid(f_ms, f_rate, f_cyc, 1, T0 + 8 * H, T0 + 16 * H)
    assert paid == pytest.approx(0.0003) and est is False


# ---- final review of Part 1 (Oct 23, 2026) --------------------------------------------------


def test_a_hold_past_a_list_that_stopped_is_estimated_never_a_measured_zero():
    # I3: the saved list's last settlement is at T0 (0.1% every 8 h) and a long is held from
    # T0 + 1h to T0 + 42h. The list answers to one cycle after its last settlement, T0 + 8h: the
    # 34 hours after that pay the average known rate, 34 / 8 x 0.001 = 0.00425 (on $50, $0.2125),
    # flagged estimated. Before the fix it paid 0.0 with estimated=False; settled every 8 h it
    # would have been 5 x 0.001 (T0 + 8h ... T0 + 40h)
    f_ms, f_rate, f_cyc = [T0 - 8 * H, T0], [0.001, 0.001], [8.0, 8.0]
    paid, est = vr.funding_paid(f_ms, f_rate, f_cyc, 1, T0 + H, T0 + 42 * H)
    assert paid == pytest.approx(0.00425) and est is True
    paid, est = vr.funding_paid(f_ms, f_rate, f_cyc, -1, T0 + H, T0 + 42 * H)
    assert paid == pytest.approx(-0.00425) and est is True, "a short receives the estimate"


def test_the_cycle_not_settled_yet_is_free_so_a_fresh_list_is_unchanged():
    # a list fetched now ends with the last settlement that HAS happened: a hold ending within
    # one cycle of it (T0 + 8h here) owes nothing more, and nothing is estimated
    f_ms, f_rate, f_cyc = [T0 - 8 * H, T0], [0.001, 0.001], [8.0, 8.0]
    assert vr.funding_paid(f_ms, f_rate, f_cyc, 1, T0 + H, T0 + 8 * H) == (0.0, False)
    assert vr.funding_paid(f_ms, f_rate, f_cyc, 1, T0 - H, T0 + 7 * H) == \
        (pytest.approx(0.001), False), "the T0 settlement is paid, the next is not due yet"
    # one hour past the cycle: 1 / 8 of the average rate, estimated
    paid, est = vr.funding_paid(f_ms, f_rate, f_cyc, 1, T0 + H, T0 + 9 * H)
    assert paid == pytest.approx(0.001 / 8) and est is True


def test_the_next_settlement_is_due_one_of_the_last_settlements_own_cycles_later():
    # the coin moved to hourly funding at its last settlement (T0): the next was due at T0 + 1h,
    # so a hold from T0 + 1h to T0 + 3h is 2 hourly cycles past the list - 2 x the average known
    # rate, 0.001 - not a free 8-hour cycle
    f_ms, f_rate, f_cyc = [T0 - 8 * H, T0], [0.001, 0.001], [8.0, 1.0]
    paid, est = vr.funding_paid(f_ms, f_rate, f_cyc, 1, T0 + H, T0 + 3 * H)
    assert paid == pytest.approx(0.002) and est is True


def test_a_touch_stops_a_trail_on_both_sides():
    # the stop is reached when a low TOUCHES it (a short: a high), as `settle_in_minutes` reads a
    # stop: a long stopped at 99.0 by a low of exactly 99.0, a short at 101.0 by a high of 101.0
    assert vr.trail_walk(1, 99.0, 1.0, [T0], [99.5], [99.0], T0, T0 + M) == (T0, 99.0)
    assert vr.trail_walk(-1, 101.0, 1.0, [T0], [101.0], [100.5], T0, T0 + M) == (T0, 101.0)
    assert vr.stop_reached(1, 98.0, 99.0, 98.0) and not vr.stop_reached(1, 98.0, 99.0, 98.01)
    assert vr.stop_reached(-1, 102.0, 102.0, 101.0) and not vr.stop_reached(-1, 102.0, 101.99, 101.0)


def test_a_short_trail_the_price_jumped_past_exits_at_the_best_price_traded():
    # minute 0 pulls a short's stop down to 99.5 + 1.0 = 100.5; minute 1 trades only 102.0-103.0,
    # all above it: the stop fills at 102.0, the best price that minute traded, never 100.5
    assert vr.trail_walk(-1, 101.0, 1.0, [T0, T0 + M], [100.2, 103.0], [99.5, 102.0],
                         T0, T0 + 2 * M) == (T0 + M, 102.0)


def test_atr_counts_a_downward_gap_from_the_previous_close():
    # bar 1 trades 9-11 but bar 0 closed at 20: its true range is 20 - 9 = 11, so ATR(2) is
    # (2 + 11) / 2 = 6.5 (a plain high-low average would give 2.0)
    assert vr.atr([21.0, 11.0], [19.0, 9.0], [20.0, 10.0], 2) == [None, 6.5]


def test_an_order_the_book_already_crosses_is_marketable():
    # a waiting buy at 100.0 matches an ask at or under 100.0 the moment it goes in (Gate would
    # fill it as a taker); a sell at 100.0 matches a bid at or over it
    assert vr.marketable(1, 100.0, 99.9, 100.0) and vr.marketable(1, 100.0, 99.8, 99.9)
    assert not vr.marketable(1, 100.0, 99.95, 100.05)
    assert vr.marketable(-1, 100.0, 100.0, 100.1) and vr.marketable(-1, 100.0, 100.1, 100.2)
    assert not vr.marketable(-1, 100.0, 99.95, 100.05)


def test_the_leverage_cap_is_the_rooms_own():
    """v3 never trades above the leverage the rooms trade at (operator, Oct 22,
    2026: "Same risk, lower leverage"; RCA-2026-10-23-C)."""
    import tradingagents.auto_trader as at

    assert vr.LEVERAGE_CAP == at.LEVERAGE == 20
