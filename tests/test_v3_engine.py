"""The Backtest v3 engine (spec docs/superpowers/specs/2026-10-22-backtest-
v3-design.md, Part 3). Every candle is BUILT from its own minutes, so the
candles, the minutes and the trades share ONE timeline (RCA-2026-09-12-A):
never hand-write a candle that its minutes disagree with."""
import pytest

from tradingagents import v3_engine as ve

M = 60_000
H = 3_600_000
T0 = 1_790_000_000_000 - (1_790_000_000_000 % H)
CONTRACT = {"contract_size": 0.01, "min_vol": 1, "mmr": 0.005, "max_lev": 20}
FEES = {"maker": 0.0002, "taker": 0.00075}
FLAT = [(100.1, 99.9)] * 60                      # an hour that closes at 100.0
FIXED = {"kind": "fixed", "tp": 0.01, "sl": 0.02}
TRAIL = {"kind": "trail", "atr_mult": 3.0, "ma_n": None}
SNAP = {"kind": "snap", "mean_n": 20, "stop_atr": 3.0, "max_bars": 2}
SIGNAL = [(100.1, 99.8)] + [(100.1, 99.9)] * 59        # closes at 100.0; ATR(20) there is 0.205
TRAIL_FILL = [(100.05, 99.8)] + [(100.1, 99.9)] * 59   # buys at minute 0; the trail ends at 99.485


def _world(hours, bar_ms=H):
    """hours: one list of (high, low) minutes per candle of `bar_ms` (60 a hour) -> (bars,
    fine)."""
    t, hi, lo = [], [], []
    bars = {"t": [], "o": [], "h": [], "l": [], "c": []}
    for k, minutes in enumerate(hours):
        for m, (h_, l_) in enumerate(minutes):
            t.append(T0 + k * bar_ms + m * M)
            hi.append(h_)
            lo.append(l_)
        bars["t"].append(T0 + k * bar_ms)
        bars["o"].append(sum(minutes[0]) / 2)
        bars["h"].append(max(x[0] for x in minutes))
        bars["l"].append(min(x[1] for x in minutes))
        bars["c"].append(sum(minutes[-1]) / 2)
    return bars, (t, hi, lo)


def _fixed_world(fill_hour, *later):
    """Hour 0 closes at 100.0 (the signal); hour 1 is the fill window."""
    return _world([FLAT, fill_hour, *later])


def _walk(bars, dirs, spec=FIXED, **kw):
    # walk wants the coin's flat gap spelled out; this test world has no gap unless a test names one
    kw = {"contract": CONTRACT, "fees": FEES, "cost_check": False, "flat_slip": 0.0, **kw}
    return ve.walk(bars, dirs, spec, bar_s=3600, **kw)


def _without(fine, from_ms, to_ms):
    """The same minutes with those in [from_ms, to_ms) deleted: a hole in Gate's archive. The
    CANDLE keeps its own high and low, which the hole hides."""
    t, hi, lo = fine
    keep = [k for k, ms in enumerate(t) if not from_ms <= ms < to_ms]
    return [t[k] for k in keep], [hi[k] for k in keep], [lo[k] for k in keep]


def _book(*rows, source="full"):
    """book_history's packed readings from (minute ms, bid, ask, buy, sell): the best prices of
    that minute and what buying / selling the runner's $100 cost there."""
    from tradingagents import book_history as bh

    return bh.pack([{"t": ms // 1000, "bid": bid, "ask": ask,
                     "spread": (ask - bid) / ((ask + bid) / 2), "buy": buy, "sell": sell,
                     "exhausted": False, "source": source} for ms, bid, ask, buy, sell in rows])


def _trail_world(*after):
    """21 flat hours, the signal hour, the fill hour, then `after` -> (bars, fine, dirs)."""
    bars, fine = _world([FLAT] * 21 + [SIGNAL, TRAIL_FILL, *after])
    return bars, fine, [0] * 21 + [1] + [0] * (len(after) + 1)


def test_a_long_fills_only_on_a_trade_through_and_wins_at_a_resting_target():
    fill_hour = [(100.1, 99.9)] * 10 + [(100.0, 99.95)] + [(100.5, 100.0)] * 49
    bars, fine = _fixed_world(fill_hour, [(101.5, 100.5)] + [(101.6, 101.0)] * 59)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["entry_ms"] == T0 + H, "minute 0 of the fill hour traded below 100.0"
    assert tr["why"] == "TP" and tr["exit"] == pytest.approx(101.0)
    # a 2% stop at $1 risk: $50 of coin = 50 lots of 0.01 at $100
    assert tr["contracts"] == 50 and tr["notional"] == pytest.approx(50.0)
    # +1% of $50 = +0.50, less the maker fee in and out on $50
    assert tr["pnl"] == pytest.approx(0.50 - 50.0 * 0.0004)


def test_a_short_fills_above_its_limit_and_wins_below():
    fill_hour = [(100.1, 99.9)] + [(99.95, 99.5)] * 59        # minute 0 trades above 100.0
    bars, fine = _fixed_world(fill_hour, [(99.5, 98.5)] * 60)
    (tr,) = _walk(bars, [-1, 0, 0], fine=fine)["trades"]
    assert tr["side"] == -1 and tr["why"] == "TP" and tr["exit"] == pytest.approx(99.0)
    assert tr["pnl"] == pytest.approx(0.50 - 50.0 * 0.0004)


def test_an_order_that_only_touches_is_missed_and_its_market_twin_is_kept():
    bars, fine = _fixed_world([(100.2, 100.0)] * 60, [(101.5, 100.5)] * 60)
    got = _walk(bars, [1, 0, 0], fine=fine)
    assert got["trades"] == [] and got["counts"]["missed"] == 1
    (m,) = got["missed"]
    assert m["limit"] == pytest.approx(100.0) and m["market"]["why"] == "TP"
    assert m["market"]["entry"] == pytest.approx(100.1), "the next candle's open"
    assert m["market"]["fee_in"] == pytest.approx(0.00075), "a market entry pays the taker fee"


def test_the_minute_an_order_fills_in_can_stop_it_but_cannot_win_it():
    # minute 0 trades 101.5 AND 99.5: the high may have come before the fill
    fill_hour = [(101.5, 99.5)] + [(100.5, 100.2)] * 59
    bars, fine = _fixed_world(fill_hour, [(100.3, 97.5)] * 60)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H
    # a long passes its limit on the way down to its stop, so that minute CAN stop it
    bars, fine = _fixed_world([(100.1, 97.5)] + [(99.0, 98.5)] * 59, [(101.5, 100.5)] * 60)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + H


def test_a_stop_the_price_jumped_past_is_booked_where_the_price_was():
    fill_hour = [(100.1, 99.5)] + [(99.9, 99.6)] * 59
    bars, fine = _fixed_world(fill_hour, [(97.0, 96.0)] + [(96.5, 96.0)] * 59)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit"] == pytest.approx(97.0), "nothing traded at 98.0"


def test_a_trailing_stop_follows_the_move_and_exits_at_the_trail():
    signal = [(100.1, 99.8)] + [(100.1, 99.9)] * 59           # closes at 100.0
    up = [(100.05 + 0.1 * m, 99.8 + 0.1 * m) for m in range(60)]   # fills at minute 0, climbs
    drop = [(105.9, 104.0)] + [(104.5, 98.0)] * 59             # trades down through the trail
    bars, fine = _world([FLAT] * 21 + [signal, up, drop])
    (tr,) = _walk(bars, [0] * 21 + [1, 0, 0], {"kind": "trail", "atr_mult": 3.0, "ma_n": None},
                  fine=fine)["trades"]
    # ATR(20) at the signal is 0.205, so the trail sits 0.615 under the highs:
    # 105.95 - 0.615 = 105.335 when the drop starts
    assert tr["why"] == "TRAIL" and tr["exit"] == pytest.approx(105.335)
    assert tr["exit_ms"] == T0 + 23 * H


def test_a_trend_trade_also_leaves_at_a_close_on_the_wrong_side_of_its_average():
    signal = [(100.1, 99.8)] + [(100.1, 99.9)] * 59
    sag = [(100.1, 99.8)] + [(99.8, 99.6)] * 59                # fills, then closes at 99.7
    bars, fine = _world([FLAT] * 21 + [signal, sag])
    (tr,) = _walk(bars, [0] * 21 + [1, 0], {"kind": "trail", "atr_mult": 3.0, "ma_n": 3},
                  fine=fine)["trades"]
    # the 3-candle average at that close is (100 + 100 + 99.7) / 3 = 99.9, above it
    assert tr["why"] == "MA" and tr["exit"] == pytest.approx(99.7)
    assert tr["exit_ms"] == T0 + 23 * H


def test_a_snap_back_rests_its_target_at_the_average_and_leaves_on_time():
    dip = [(100.0, 96.9)] + [(97.2, 96.9)] * 59      # closes at 97.05, under its average
    fill = [(97.2, 97.0)] + [(97.3, 97.1)] * 59      # buys at 97.05 in minute 0
    spec = {"kind": "snap", "mean_n": 20, "stop_atr": 3.0, "max_bars": 2}
    bars, fine = _world([FLAT] * 20 + [dip, fill, [(97.5, 97.2)] * 60])
    (tr,) = _walk(bars, [0] * 20 + [1, 0, 0], spec, fine=fine)["trades"]
    assert tr["why"] == "TIME" and tr["exit"] == pytest.approx(97.35)
    assert tr["exit_ms"] == T0 + 23 * H, "out at the close of its second candle"
    bars, fine = _world([FLAT] * 20 + [dip, fill, [(100.0, 97.2)] * 60])
    (tr,) = _walk(bars, [0] * 20 + [1, 0, 0], spec, fine=fine)["trades"]
    assert tr["why"] == "TP" and tr["exit"] == pytest.approx((19 * 100.0 + 97.05) / 20)


def test_a_signal_on_the_last_candle_places_no_order():
    bars, fine = _world([FLAT, FLAT])
    got = _walk(bars, [0, 1], fine=fine)
    assert got["trades"] == [] and got["counts"]["no_next_bar"] == 1


def test_a_candle_with_no_minutes_keeps_the_candle_rule_and_is_counted():
    bars, _fine = _fixed_world([(100.2, 99.5)] * 60, [(101.5, 97.0)] * 60)
    got = _walk(bars, [1, 0, 0], fine=None)
    (tr,) = got["trades"]
    assert got["counts"]["fill_by_candle"] == 1 and got["counts"]["settled_by_candle"] == 1
    assert tr["why"] == "SL" and got["counts"]["unclear"] == 1, "both in one candle is the stop"


def test_a_stop_no_leverage_keeps_safe_and_a_trade_under_one_lot_are_skipped():
    bars, fine = _fixed_world([(100.1, 99.0)] * 60, [(101.5, 100.5)] * 60)
    wide = _walk(bars, [1, 0, 0], {"kind": "fixed", "tp": 0.9, "sl": 0.85}, fine=fine)
    assert wide["trades"] == [] and wide["counts"]["unsafe_stop"] == 1
    big_lot = {**CONTRACT, "contract_size": 1.0}            # one lot = $100 of coin
    small = _walk(bars, [1, 0, 0], fine=fine, contract=big_lot)
    assert small["trades"] == [] and small["counts"]["too_small"] == 1


def test_a_market_exit_pays_the_taker_fee_and_the_flat_gap_when_no_book_was_recorded():
    bars, fine = _fixed_world([(100.1, 99.0)] * 60, [(100.0, 97.5)] * 60)
    got = _walk(bars, [1, 0, 0], {"kind": "fixed", "tp": 0.03, "sl": 0.02}, fine=fine,
                flat_slip=0.0005)
    (tr,) = got["trades"]
    assert tr["why"] == "SL" and tr["fee_out"] == pytest.approx(0.00075)
    assert tr["slip_out"] == pytest.approx(0.0005) and tr["measured_exit"] is False
    assert got["counts"]["cost_unmeasured"] == 1
    assert tr["pnl"] == pytest.approx(-1.0 - 50.0 * (0.0002 + 0.00075 + 0.0005))


def test_funding_before_the_history_is_estimated_and_counted():
    bars, fine = _fixed_world([(100.1, 99.0)] * 60, [(101.5, 100.5)] * 60)
    fund = [{"settle_ms": T0 + 100 * H, "rate": 0.0001, "cycle_h": 8}]
    got = _walk(bars, [1, 0, 0], fine=fine, funding=fund)
    assert got["counts"]["funding_estimated"] == 1
    assert got["trades"][0]["funding_estimated"] is True


def test_the_cost_check_refuses_what_the_runner_would_refuse():
    bars, fine = _fixed_world([(100.1, 99.0)] * 60, [(101.5, 100.5)] * 60)
    # a 0.5% gap out against a 1% target: maker 0.02% + taker 0.075% + 0.5% is
    # 0.595% of a 1% target, past the runner's 50% line
    got = _walk(bars, [1, 0, 0], fine=fine, flat_slip=0.005, cost_check=True)
    assert got["trades"] == [] and got["counts"]["gate_blocked"] == 1


# ---- fix round 1 (review of 89c05b5), Important 1: a candle the minutes only part cover --------


def test_a_candle_the_minutes_only_part_cover_keeps_the_candle_rule_for_its_exit():
    # hour 1 fills the order at minute 0. Hour 2 is quiet for 30 minutes, then minute 30 trades
    # down to 97.5, under the 98.0 stop (2% under the 100.0 entry)
    late = [(100.3, 99.5)] * 30 + [(99.0, 97.5)] + [(99.0, 98.5)] * 29
    bars, fine = _fixed_world(FLAT, late)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H + 30 * M, "every minute: out at 30"
    # the archive lacks minutes 30-59 of that hour, yet the CANDLE still says it traded to 97.5.
    # The 30 minutes that are there show nothing, so the candle rule books the stop: at the
    # candle's open, at 98.0 (its high is above that, so the price did not jump past the stop)
    got = _walk(bars, [1, 0, 0], fine=_without(fine, T0 + 2 * H + 30 * M, T0 + 3 * H))
    (tr,) = got["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H and tr["exit"] == pytest.approx(98.0)
    assert got["counts"]["settled_by_candle"] == 1 and got["counts"]["unclear"] == 0
    # -2% of $50 is -1.00, plus the maker fee in and the taker fee out; this world has no gap
    assert tr["pnl"] == pytest.approx(-1.0 - 50.0 * (0.0002 + 0.00075))
    # the missing minutes hold the target (minute 30) and then the stop (minute 31). With them the
    # target came first (+0.50 less 0.02 of fees); without them the candle cannot say which came
    # first, so it is the stop, counted as unclear
    both = [(100.3, 99.5)] * 30 + [(101.5, 100.5), (99.0, 97.5)] + [(99.0, 98.5)] * 28
    bars, fine = _fixed_world(FLAT, both)
    (win,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert win["why"] == "TP" and win["pnl"] == pytest.approx(0.50 - 50.0 * 0.0004)
    got = _walk(bars, [1, 0, 0], fine=_without(fine, T0 + 2 * H + 30 * M, T0 + 3 * H))
    (tr,) = got["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H
    assert got["counts"]["settled_by_candle"] == 1 and got["counts"]["unclear"] == 1


def test_a_stop_hidden_in_the_rest_of_the_fill_candle_is_proven_by_the_candles_low():
    # FLIPPED by the final review of Part 1 (Oct 23, 2026, I2). The order fills at minute 0, and
    # minute 30 of the same hour trades down to 97.5, under the 98.0 stop. With every minute: SL
    # at minute 30, -2% of $50 less 0.02% in and 0.075% out = -1.0475
    fill_hour = [(100.1, 99.9)] * 30 + [(99.0, 97.5)] + [(100.1, 99.9)] * 29
    bars, fine = _fixed_world(fill_hour, [(101.5, 100.5)] * 60)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + H + 30 * M
    assert tr["pnl"] == pytest.approx(-1.0 - 50.0 * (0.0002 + 0.00075))
    # minute 30 missing. A long trades through its 100.0 limit before it can fall to a stop under
    # it, so the hour's own 97.5 low came AFTER the fill: the stop was hit in a minute the points
    # do not show. The stop, at 98.0 (the price came down from the limit through it), stamped at
    # the first point after the fill (minute 1) - never the hour's open, before the order existed.
    # Before this fix the trade went on to hour 2's target, +0.48, and nothing was counted
    got = _walk(bars, [1, 0, 0], fine=_without(fine, T0 + H + 30 * M, T0 + H + 31 * M))
    (tr,) = got["trades"]
    assert tr["entry_ms"] == T0 + H and tr["why"] == "SL" and tr["exit_ms"] == T0 + H + M
    assert tr["exit"] == pytest.approx(98.0)
    assert tr["pnl"] == pytest.approx(-1.0 - 50.0 * (0.0002 + 0.00075))
    assert got["counts"]["settled_by_candle"] == 1 and got["counts"]["unclear"] == 0
    # the same for a trail. With every minute: minutes 1-29 lift the 99.385 it began with to
    # 100.1 - 0.615 = 99.485, and minute 30's 99.0 low leaves at it
    fill_hour = [(100.05, 99.8)] + [(100.1, 99.9)] * 29 + [(100.1, 99.0)] + [(100.1, 99.9)] * 29
    bars, fine = _world([FLAT] * 21 + [SIGNAL, fill_hour, [(100.1, 99.4)] + [(100.1, 99.9)] * 59])
    (tr,) = _walk(bars, [0] * 21 + [1, 0, 0], TRAIL, fine=fine)["trades"]
    assert tr["why"] == "TRAIL" and tr["exit_ms"] == T0 + 22 * H + 30 * M
    assert tr["exit"] == pytest.approx(99.485)
    # minute 30 missing: the hour's 99.0 low is under the 99.385 the trail began with, so the
    # trail was hit after the fill. Whether minutes 1-29 had lifted it first is unknowable, so it
    # leaves at the stop it began with, 99.385 - not at 99.485 an hour later, as before the fix
    got = _walk(bars, [0] * 21 + [1, 0, 0], TRAIL,
                fine=_without(fine, T0 + 22 * H + 30 * M, T0 + 22 * H + 31 * M))
    (tr,) = got["trades"]
    assert tr["why"] == "TRAIL" and tr["exit_ms"] == T0 + 22 * H + M
    assert tr["exit"] == pytest.approx(99.385) and got["counts"]["settled_by_candle"] == 1


def test_a_trail_the_minutes_cannot_walk_to_its_end_leaves_when_the_candle_proves_the_hit():
    # the trail starts 3 x 0.205 = 0.615 under the 100.0 entry (99.385); the fill hour lifts it to
    # 100.1 - 0.615 = 99.485. In the next hour minute 30 trades down to 99.0, under 99.485 - but
    # that one minute is missing from the archive
    hole = [(100.1, 99.9)] * 30 + [(100.0, 99.0)] + [(100.1, 99.9)] * 29
    bars, fine, dirs = _trail_world(hole, FLAT)
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine)["trades"]
    assert tr["why"] == "TRAIL" and tr["exit_ms"] == T0 + 23 * H + 30 * M, "every minute: out at 30"
    assert tr["exit"] == pytest.approx(99.485)
    # a stop only tightens inside a candle, so a candle low under the stop it BEGAN with proves the
    # stop was hit: out at the candle's open, at 99.485 (the candle's high is above it)
    got = _walk(bars, dirs, TRAIL, fine=_without(fine, T0 + 23 * H + 30 * M, T0 + 23 * H + 31 * M))
    (tr,) = got["trades"]
    assert tr["why"] == "TRAIL" and tr["exit_ms"] == T0 + 23 * H
    assert tr["exit"] == pytest.approx(99.485) and got["counts"]["settled_by_candle"] == 1


def test_a_trail_keeps_the_stop_its_minutes_moved_when_the_candle_cannot_prove_a_hit():
    # minute 0 of hour 23 trades up to 101.0 and lifts the stop to 101.0 - 0.615 = 100.385; minute
    # 30 (missing) trades down to 100.0 - under 100.385 but over the 99.485 the candle BEGAN with.
    # That low may have come before the high, so nothing is proven: the stop goes on at 100.385
    # and hour 24, trading down to 100.3, leaves at it
    hole = [(101.0, 100.4)] + [(100.6, 100.5)] * 29 + [(100.7, 100.0)] + [(100.6, 100.5)] * 29
    after = [(100.5, 100.3)] + [(100.5, 100.4)] * 59
    bars, fine, dirs = _trail_world(hole, after)
    got = _walk(bars, dirs, TRAIL, fine=_without(fine, T0 + 23 * H + 30 * M, T0 + 23 * H + 31 * M))
    (tr,) = got["trades"]
    assert tr["why"] == "TRAIL" and tr["exit_ms"] == T0 + 24 * H
    assert tr["exit"] == pytest.approx(100.385) and got["counts"]["settled_by_candle"] == 0


def test_a_fill_the_candle_proves_but_the_minutes_do_not_show_is_a_trade_not_a_missed_order():
    # every minute of hour 1 touches 100.0 and no more, except minute 30, which trades down to 99.5
    fill_hour = [(100.2, 100.0)] * 30 + [(100.1, 99.5)] + [(100.2, 100.0)] * 29
    bars, fine = _fixed_world(fill_hour, [(101.5, 100.5)] * 60)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["entry_ms"] == T0 + H + 30 * M, "every minute: filled at 30"
    # without minute 30 the minutes show a touch and nothing more - but the candle's own low, 99.5,
    # is under the 100.0 limit: the order traded through somewhere in the hour. The candle rule
    # fills it at the candle's open
    got = _walk(bars, [1, 0, 0], fine=_without(fine, T0 + H + 30 * M, T0 + H + 31 * M))
    (tr,) = got["trades"]
    assert got["counts"]["missed"] == 0 and got["counts"]["fill_by_candle"] == 1
    assert tr["entry_ms"] == T0 + H and tr["why"] == "TP" and tr["exit_ms"] == T0 + 2 * H


def test_a_fill_decided_by_the_candle_leaves_the_rest_of_that_candle_unread():
    # the order's trade-through (minute 0, down to 99.5) is missing and minute 10 trades up to
    # 101.5, over the 101.0 target. The fill may have come after that high, so the fill candle
    # cannot win the trade: it goes on to hour 2, which trades down through the 98.0 stop
    fill_hour = [(100.1, 99.5)] + [(100.2, 100.0)] * 9 + [(101.5, 100.5)] + [(100.2, 100.0)] * 49
    bars, fine = _fixed_world(fill_hour, [(100.3, 97.5)] * 60)
    got = _walk(bars, [1, 0, 0], fine=_without(fine, T0 + H, T0 + H + M))
    (tr,) = got["trades"]
    assert got["counts"]["fill_by_candle"] == 1 and tr["entry_ms"] == T0 + H
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H
    # a hole that also hides a low under the stop (97.5, minute 0): the candle can stop the trade
    # it filled, at 98.0, at its open
    bars, fine = _fixed_world([(100.1, 97.5)] + [(100.2, 100.0)] * 59, [(101.5, 100.5)] * 60)
    got = _walk(bars, [1, 0, 0], fine=_without(fine, T0 + H, T0 + H + M))
    (tr,) = got["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + H and tr["exit"] == pytest.approx(98.0)
    assert got["counts"]["settled_by_candle"] == 1


def test_a_touch_is_no_fill_by_the_candle_rule_either():
    # no minutes at all: a long whose hour traded down to exactly its 100.0 limit, not through it
    bars, _fine = _fixed_world([(100.2, 100.0)] * 60, [(101.5, 100.5)] * 60)
    got = _walk(bars, [1, 0, 0], fine=None)
    assert got["trades"] == [] and got["counts"]["missed"] == 1
    # a short whose hour traded up to exactly its limit
    bars, _fine = _world([FLAT, [(100.0, 99.8)] * 60, [(99.5, 98.5)] * 60])
    got = _walk(bars, [-1, 0, 0], fine=None)
    assert got["trades"] == [] and got["counts"]["missed"] == 1
    # minutes that only part cover the hour: the candle's own extreme IS the limit, proving nothing
    bars, fine = _fixed_world([(100.2, 100.0)] * 60, [(101.5, 100.5)] * 60)
    got = _walk(bars, [1, 0, 0], fine=_without(fine, T0 + H + 5 * M, T0 + H + 6 * M))
    assert got["trades"] == [] and got["counts"]["missed"] == 1
    assert got["counts"]["fill_by_candle"] == 0
    bars, fine = _world([FLAT, [(100.0, 99.8)] * 60, [(99.5, 98.5)] * 60])
    got = _walk(bars, [-1, 0, 0], fine=_without(fine, T0 + H + 5 * M, T0 + H + 6 * M))
    assert got["trades"] == [] and got["counts"]["missed"] == 1
    assert got["counts"]["fill_by_candle"] == 0


def test_the_candle_rules_hold_for_a_short_too():
    # (a) a short's stop is hit by the candle's HIGH. Hour 2 is quiet for 30 minutes, then minute
    # 30 trades up to 102.5, over the 102.0 stop - and minutes 30-59 are missing from the archive
    late = [(99.8, 99.5)] * 30 + [(102.5, 101.0)] + [(101.0, 100.5)] * 29
    bars, fine = _world([FLAT, FLAT, late])
    (tr,) = _walk(bars, [-1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H + 30 * M, "every minute: out at 30"
    got = _walk(bars, [-1, 0, 0], fine=_without(fine, T0 + 2 * H + 30 * M, T0 + 3 * H))
    (tr,) = got["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H and tr["exit"] == pytest.approx(102.0)
    assert got["counts"]["settled_by_candle"] == 1
    # (b) a short's trail ends the fill hour at 94.05 + 0.615 = 94.665 (the short trail test).
    # Minute 30 of the next hour trades up to 95.0, over it - and is missing: the candle's high
    # proves the stop was hit
    down = [(100.2 - 0.1 * m, 99.95 - 0.1 * m) for m in range(60)]
    hole = [(94.4, 94.1)] * 30 + [(95.0, 94.1)] + [(94.4, 94.1)] * 29
    bars, fine = _world([FLAT] * 21 + [SIGNAL, down, hole, [(94.4, 94.1)] * 60])
    dirs = [0] * 21 + [-1, 0, 0, 0]
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine)["trades"]
    assert tr["why"] == "TRAIL" and tr["exit_ms"] == T0 + 23 * H + 30 * M, "every minute: out at 30"
    got = _walk(bars, dirs, TRAIL, fine=_without(fine, T0 + 23 * H + 30 * M, T0 + 23 * H + 31 * M))
    (tr,) = got["trades"]
    assert tr["why"] == "TRAIL" and tr["exit_ms"] == T0 + 23 * H
    assert tr["exit"] == pytest.approx(94.665) and got["counts"]["settled_by_candle"] == 1
    # (c) a short's order fills on a HIGH over its limit: minute 30 (missing) trades up to 100.5
    fill_hour = [(100.0, 99.8)] * 30 + [(100.5, 99.8)] + [(100.0, 99.8)] * 29
    bars, fine = _world([FLAT, fill_hour, [(99.5, 98.5)] * 60])
    (tr,) = _walk(bars, [-1, 0, 0], fine=fine)["trades"]
    assert tr["entry_ms"] == T0 + H + 30 * M, "every minute: sold at 30"
    got = _walk(bars, [-1, 0, 0], fine=_without(fine, T0 + H + 30 * M, T0 + H + 31 * M))
    (tr,) = got["trades"]
    assert got["counts"]["fill_by_candle"] == 1 and got["counts"]["missed"] == 0
    assert tr["entry_ms"] == T0 + H and tr["why"] == "TP" and tr["exit_ms"] == T0 + 2 * H


# ---- Important 2: the coin's flat gap is never a silent 0 ------------------------------------


def test_the_flat_gap_has_no_default_so_an_unmeasured_exit_is_never_free_by_accident():
    bars, fine = _fixed_world([(100.1, 99.0)] * 60, [(101.5, 100.5)] * 60)
    with pytest.raises(TypeError, match="flat_slip"):
        ve.walk(bars, [1, 0, 0], FIXED, bar_s=3600, contract=CONTRACT, fees=FEES, fine=fine)


# ---- Important 3: the rules the first tests did not pin --------------------------------------


def test_a_market_exit_pays_the_gap_its_own_minutes_book_recorded_on_the_side_it_trades():
    # a long leaves by SELLING, into the bids: the book's `sell`; a short leaves by BUYING, into
    # the asks: its `buy`. The reading of the minute the trade ends in is the one charged - not
    # the entry minute's, and not the coin's flat gap (0.3% here)
    spec = {"kind": "fixed", "tp": 0.03, "sl": 0.02}
    bars, fine = _fixed_world([(100.1, 99.0)] * 60, [(100.0, 97.5)] * 60)     # long, out at 98.0
    book = _book((T0 + H, 99.95, 100.05, 0.0001, 0.0002),
                 (T0 + 2 * H, 97.9, 98.1, 0.0009, 0.0004))
    got = _walk(bars, [1, 0, 0], spec, fine=fine, book=book, flat_slip=0.003)
    (tr,) = got["trades"]
    assert tr["why"] == "SL" and tr["measured_exit"] is True
    assert tr["slip_out"] == pytest.approx(0.0004), "a long sells: `sell`, not the asks' 0.0009"
    assert got["counts"]["cost_unmeasured"] == 0
    # -2% of $50 is -1.00, the maker fee in, the taker fee and the recorded gap out
    assert tr["pnl"] == pytest.approx(-1.0 - 50.0 * (0.0002 + 0.00075 + 0.0004))
    # a short sells at 100.0 and is stopped at 102.0 by buying back
    bars, fine = _world([FLAT, [(100.1, 99.9)] * 60, [(102.5, 100.0)] * 60])
    book = _book((T0 + H, 99.95, 100.05, 0.0001, 0.0002),
                 (T0 + 2 * H, 101.9, 102.1, 0.0009, 0.0004))
    got = _walk(bars, [-1, 0, 0], spec, fine=fine, book=book, flat_slip=0.003)
    (tr,) = got["trades"]
    assert tr["why"] == "SL" and tr["exit"] == pytest.approx(102.0) and tr["measured_exit"] is True
    assert tr["slip_out"] == pytest.approx(0.0009), "a short buys: `buy`, not the bids' 0.0004"
    assert tr["pnl"] == pytest.approx(-1.0 - 50.0 * (0.0002 + 0.00075 + 0.0009))


def test_a_missed_orders_twin_buys_at_the_recorded_ask_and_a_short_one_sells_at_the_bid():
    # the order rests at 100.0 and the hour only touches it, so it is missed. The twin enters the
    # way Backtest v2 does: at the best price the entry minute's own book recorded - the ask for a
    # long (100.15; the hour opened at 100.1), the bid for a short - which already holds the gap,
    # so only the taker fee is added
    bars, fine = _fixed_world([(100.2, 100.0)] * 60, [(101.5, 100.5)] * 60)
    book = _book((T0 + H, 100.05, 100.15, 0.0001, 0.0001))
    (m,) = _walk(bars, [1, 0, 0], fine=fine, book=book)["missed"]
    assert m["market"]["entry"] == pytest.approx(100.15)
    assert m["market"]["fee_in"] == pytest.approx(0.00075)
    # 1% over its own entry: 100.15 x 1.01 = 101.1515, which the next hour trades through
    assert m["market"]["why"] == "TP" and m["market"]["exit"] == pytest.approx(101.1515)
    bars, fine = _world([FLAT, [(100.0, 99.8)] * 60, [(99.5, 98.5)] * 60])
    book = _book((T0 + H, 99.95, 100.05, 0.0001, 0.0001))
    (m,) = _walk(bars, [-1, 0, 0], fine=fine, book=book)["missed"]
    assert m["market"]["entry"] == pytest.approx(99.95), "a short sells at the bid (open 99.9)"
    # 1% under 99.95 is 98.9505, which the next hour (low 98.5) trades through
    assert m["market"]["why"] == "TP" and m["market"]["exit"] == pytest.approx(98.9505)


def test_a_missed_orders_twin_without_a_fresh_book_enters_at_the_open_and_pays_the_gap():
    # the only reading is 2 minutes older than the entry minute: too old to be a price to trade
    # at (the runner's rule is 59 s), so the twin buys at the candle's open and pays that
    # reading's gap on top of the taker fee - `buy` for a long, `sell` for a short
    bars, fine = _fixed_world([(100.2, 100.0)] * 60, [(101.5, 100.5)] * 60)
    stale = _book((T0 + H - 2 * M, 100.05, 100.15, 0.0007, 0.0001))
    (m,) = _walk(bars, [1, 0, 0], fine=fine, book=stale)["missed"]
    assert m["market"]["entry"] == pytest.approx(100.1), "the hour's open"
    assert m["market"]["fee_in"] == pytest.approx(0.00075 + 0.0007)
    bars, fine = _world([FLAT, [(100.0, 99.8)] * 60, [(99.5, 98.5)] * 60])
    stale = _book((T0 + H - 2 * M, 99.95, 100.05, 0.0001, 0.0006))
    (m,) = _walk(bars, [-1, 0, 0], fine=fine, book=stale)["missed"]
    assert m["market"]["entry"] == pytest.approx(99.9), "the hour's open"
    assert m["market"]["fee_in"] == pytest.approx(0.00075 + 0.0006)


def test_funding_inside_a_hold_is_charged_to_a_long_and_credited_to_a_short():
    # a settlement 30 minutes into the hold at +0.02%: longs pay it, shorts receive it; the one
    # after the exit is nobody's. The history reaches back past the entry, so nothing is estimated
    fund = [{"settle_ms": T0 + H + 30 * M, "rate": 0.0002, "cycle_h": 8},
            {"settle_ms": T0 + 9 * H + 30 * M, "rate": 0.0003, "cycle_h": 8}]
    bars, fine = _fixed_world(FLAT, [(101.5, 100.5)] * 60)
    got = _walk(bars, [1, 0, 0], fine=fine, funding=fund)
    (tr,) = got["trades"]
    # +1% of $50 is +0.50, less the maker fee both ways (0.02), less 0.02% of $50 paid (0.01)
    assert tr["why"] == "TP" and tr["funding"] == pytest.approx(-0.01)
    assert tr["pnl"] == pytest.approx(0.50 - 50.0 * 0.0004 - 50.0 * 0.0002)
    assert tr["funding_estimated"] is False and got["counts"]["funding_estimated"] == 0
    bars, fine = _world([FLAT, FLAT, [(99.5, 98.5)] * 60])
    (tr,) = _walk(bars, [-1, 0, 0], fine=fine, funding=fund)["trades"]
    assert tr["why"] == "TP" and tr["funding"] == pytest.approx(0.01)
    assert tr["pnl"] == pytest.approx(0.50 - 50.0 * 0.0004 + 50.0 * 0.0002)


def test_a_candle_a_trade_closed_in_signals_again_and_the_new_order_goes_in_at_once():
    stay = [(100.1, 99.9)] * 60                       # an hour that closes at 100.0
    hit = [(101.5, 100.5)] + [(100.1, 99.9)] * 59     # the target at minute 0, then back to 100.0
    bars, fine = _world([FLAT, stay, hit, stay, [(101.5, 100.5)] * 60])
    first, second = _walk(bars, [1, 0, 1, 0, 0], fine=fine)["trades"]
    # trade 1: signal on candle 0, fills in hour 1, the target is hit at the open of hour 2, whose
    # signal (it closes at 100.0) sends the second order, filled in hour 3 and won at hour 4's open
    assert (first["signal_bar"], first["exit_bar"], first["exit_ms"]) == (0, 2, T0 + 2 * H)
    assert (second["signal_bar"], second["entry_bar"]) == (2, 3)
    assert second["entry_ms"] == T0 + 3 * H and second["exit_ms"] == T0 + 4 * H


def test_a_missed_orders_twin_leaves_the_real_counts_alone():
    # the order only touches 100.0, so it is missed. Its twin buys at the open (100.1), is stopped
    # by the next hour with no book and no funding history, and so pays the flat gap and
    # estimates its funding - none of which is a real trade's, so none of it is counted
    bars, fine = _fixed_world([(100.2, 100.0)] * 60, [(100.3, 97.5)] * 60)
    got = _walk(bars, [1, 0, 0], fine=fine, flat_slip=0.0005)
    (m,) = got["missed"]
    assert m["market"]["why"] == "SL" and m["market"]["measured_exit"] is False
    assert m["market"]["slip_out"] == pytest.approx(0.0005)
    assert m["market"]["funding_estimated"] is True
    # the real order's own counts only: it rested and never traded through, and it went in with
    # no recorded book to say whether Gate would have taken it as post-only (Oct 23, 2026)
    assert got["counts"] == {**dict.fromkeys(ve.COUNT_KEYS, 0), "missed": 1,
                             "placement_unmeasured": 1}


def test_a_candle_flagged_closed_places_no_order_and_is_counted():
    bars, fine = _fixed_world([(100.1, 99.0)] * 60, [(101.5, 100.5)] * 60)
    got = _walk(bars, [1, 0, 0], fine=fine, cost_check=True, closed=[True, False, False])
    assert got["trades"] == [] and got["missed"] == [] and got["counts"]["closed_skip"] == 1
    got = _walk(bars, [1, 0, 0], fine=fine, cost_check=True, closed=[False, False, False])
    assert len(got["trades"]) == 1 and got["counts"]["closed_skip"] == 0


def test_a_waiting_order_is_never_a_chase_but_its_market_twin_is():
    # the entry minute's recorded best ask is 100.5, 0.5% over the signal's 100.0 close, and the
    # runner refuses a MARKET entry that has run more than a tenth of its 2% stop (0.2%) from
    # the signal. The order at 100.0 is no chase: it rests, and the hour only touches it
    bars, fine = _fixed_world([(100.2, 100.0)] * 60, [(101.5, 100.5)] * 60)
    book = _book((T0 + H, 100.4, 100.5, 0.0001, 0.0001))
    got = _walk(bars, [1, 0, 0], fine=fine, book=book, cost_check=True)
    assert got["counts"]["chase_skip"] == 0 and got["counts"]["missed"] == 1
    # entered at the market it would be one: 100.5 / 100.0 - 1 = 0.5% against 0.2%
    assert got["missed"][0]["market"] == {"refused": "chase_skip"}


def test_a_snap_whose_average_is_not_ahead_of_its_entry_trades_nothing():
    # 23 flat hours: the 20-candle average is 100.0, exactly where the signal closes, so there is
    # nothing to snap back to
    bars, fine = _world([FLAT] * 23)
    got = _walk(bars, [0] * 21 + [1, 0], SNAP, fine=fine)
    assert got["trades"] == [] and got["counts"]["no_levels"] == 1
    # a short whose signal closes at 99.0 under an average of (19 x 100.0 + 99.0) / 20 = 99.95:
    # the average is above it, behind a short's way down
    bars, fine = _world([FLAT] * 21 + [[(99.5, 98.5)] * 60, FLAT])
    got = _walk(bars, [0] * 21 + [-1, 0], SNAP, fine=fine)
    assert got["trades"] == [] and got["counts"]["no_levels"] == 1


def test_a_snap_order_missed_because_the_price_jumped_over_its_average_has_no_twin():
    # the dip closes at 97.05 under its average of (19 x 100.0 + 97.05) / 20 = 99.8525, and the
    # next hour never trades below 100.0: the resting order is missed, and entered at that
    # hour's open (100.1) the target 99.8525 is already behind the entry
    dip = [(100.0, 96.9)] + [(97.2, 96.9)] * 59       # closes at 97.05
    bars, fine = _world([FLAT] * 20 + [dip, [(100.2, 100.0)] * 60, FLAT])
    got = _walk(bars, [0] * 20 + [1, 0, 0], SNAP, fine=fine)
    assert got["trades"] == [] and got["counts"]["missed"] == 1
    assert got["missed"][0]["market"] == {"refused": "no_levels"}


def test_a_short_snap_rests_its_target_at_the_average_below_it_and_leaves_on_time():
    # 20 flat hours, then a spike that closes at 103.0: the average (19 x 100.0 + 103.0) / 20 =
    # 100.15 is the target; ATR(20) is (19 x 0.2 + 3.1) / 20 = 0.345, so the emergency stop sits
    # 3 x 0.345 = 1.035 above the entry, at 104.035
    pop = [(103.1, 102.9)] * 60
    fill = [(103.2, 102.9)] * 60                      # minute 0 trades above 103.0: it sells
    dirs = [0] * 20 + [-1, 0, 0]
    bars, fine = _world([FLAT] * 20 + [pop, fill, [(102.0, 100.0)] * 60])
    (tr,) = _walk(bars, dirs, SNAP, fine=fine)["trades"]
    assert tr["side"] == -1 and tr["why"] == "TP" and tr["exit"] == pytest.approx(100.15)
    assert tr["exit_ms"] == T0 + 22 * H, "the second hour's low, 100.0, is under the target"
    # a second hour that stays in between: out at the close of the second candle, 101.5
    bars, fine = _world([FLAT] * 20 + [pop, fill, [(102.0, 101.0)] * 60])
    (tr,) = _walk(bars, dirs, SNAP, fine=fine)["trades"]
    assert tr["why"] == "TIME" and tr["exit"] == pytest.approx(101.5)
    assert tr["exit_ms"] == T0 + 23 * H
    # a short gains as the price falls, 103.0 to 101.5, less the maker fee in and the taker fee out
    assert tr["pnl"] == pytest.approx(tr["notional"] * (1.0 - 101.5 / 103.0 - 0.0002 - 0.00075))


def test_a_short_trailing_stop_follows_the_fall_and_exits_at_the_trail():
    down = [(100.2 - 0.1 * m, 99.95 - 0.1 * m) for m in range(60)]    # sells at minute 0, falls
    rebound = [(94.9, 94.1)] + [(95.5, 94.5)] * 59                    # trades up through the trail
    bars, fine = _world([FLAT] * 21 + [SIGNAL, down, rebound])
    (tr,) = _walk(bars, [0] * 21 + [-1, 0, 0], TRAIL, fine=fine)["trades"]
    # the trail starts 0.615 over the entry (100.615) and each minute follows the low down by
    # 0.615: minute 59's low is 99.95 - 5.9 = 94.05, so the hour ends with the stop at 94.665
    assert tr["side"] == -1 and tr["why"] == "TRAIL" and tr["exit"] == pytest.approx(94.665)
    assert tr["exit_ms"] == T0 + 23 * H


def test_a_short_orders_market_twin_trails_from_above_its_entry():
    # the order rests at 100.0 and the next hour only touches it (its high is 100.0): missed. The
    # twin sells at that hour's open, (100.0 + 99.6) / 2 = 99.8, with the same 0.615 trail, which
    # starts ABOVE it at 99.8 + 0.615 = 100.415. Minute 0's low of 99.6 pulls the stop down to
    # 100.215 and no high of that hour (99.9) trades up to it; the next hour's 100.3 high does,
    # and the stop fills at 100.215
    miss = [(100.0, 99.6)] + [(99.9, 99.6)] * 59
    bars, fine = _world([FLAT] * 21 + [SIGNAL, miss, [(100.3, 99.9)] * 60])
    got = _walk(bars, [0] * 21 + [-1, 0, 0], TRAIL, fine=fine)
    assert got["trades"] == [] and got["counts"]["missed"] == 1
    twin = got["missed"][0]["market"]
    assert twin["entry"] == pytest.approx(99.8)
    assert twin["why"] == "TRAIL" and twin["exit"] == pytest.approx(100.215)
    assert twin["exit_ms"] == T0 + 23 * H


# ---- the final review of Part 1 (Oct 23, 2026) ----------------------------------------------
# F1: the waiting order is POST-ONLY (Gate's `poc`): an order the book of its own minute already
# crosses is rejected - a missed trade kept with its market twin - so a waiting fill always pays
# the maker fee. Measured over 63 coins' recorded books: 59,385 of 139,634 orders (42.5%) were
# marketable the minute they were placed


def test_a_waiting_buy_the_book_already_crosses_is_rejected_and_kept_with_its_twin():
    # the signal closes at 100.0. 3 s into the next hour the recorded book is bid 99.9 / ask 100.0:
    # a buy at 100.0 matches that ask at once, which Gate fills as a TAKER - so the post-only order
    # is rejected, although minute 0 trades down to 99.9 and would otherwise fill it there
    bars, fine = _fixed_world(FLAT, [(101.5, 100.5)] * 60)
    book = _book((T0 + H, 99.9, 100.0, 0.0001, 0.0001))
    got = _walk(bars, [1, 0, 0], fine=fine, book=book)
    assert got["trades"] == [] and got["counts"]["post_only_reject"] == 1
    assert got["counts"]["missed"] == 0 and got["counts"]["placement_unmeasured"] == 0
    (m,) = got["missed"]
    assert m["why"] == "post_only_reject" and m["limit"] == pytest.approx(100.0)
    # its market twin buys at that minute's ask, 100.0, and the next hour's 101.5 trades through
    # its 101.0 target: +1% of $50 less the taker fee in and the maker fee out = +0.4525
    twin = m["market"]
    assert twin["entry"] == pytest.approx(100.0) and twin["why"] == "TP"
    assert twin["pnl"] == pytest.approx(0.50 - 50.0 * (0.00075 + 0.0002))
    # the same hours with no book: the order rests, and minute 0 fills it
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["entry_ms"] == T0 + H


def test_a_waiting_sell_the_book_already_crosses_is_rejected():
    # a short sells at 100.0 and the book's best BID is 100.0: selling there matches at once, so
    # the order is rejected, though minute 0's 100.1 high would fill it. The twin sells at that
    # bid, and 1% under it, 99.0, is traded through by the next hour's 98.5 low
    bars, fine = _world([FLAT, FLAT, [(99.5, 98.5)] * 60])
    book = _book((T0 + H, 100.0, 100.1, 0.0001, 0.0001))
    got = _walk(bars, [-1, 0, 0], fine=fine, book=book)
    assert got["trades"] == [] and got["counts"]["post_only_reject"] == 1
    (m,) = got["missed"]
    assert m["why"] == "post_only_reject" and m["market"]["entry"] == pytest.approx(100.0)
    assert m["market"]["why"] == "TP" and m["market"]["exit"] == pytest.approx(99.0)


def test_a_book_that_does_not_cross_the_order_lets_it_rest_and_fill_as_before():
    # ask 100.05 is over a buy's 100.0 limit, bid 99.95 under a sell's: nothing matches, so each
    # order rests and minute 0 trades through it - the trades of before, now measured
    book = _book((T0 + H, 99.95, 100.05, 0.0001, 0.0001))
    bars, fine = _fixed_world(FLAT, [(101.5, 100.5)] * 60)
    got = _walk(bars, [1, 0, 0], fine=fine, book=book)
    (tr,) = got["trades"]
    assert tr["entry_ms"] == T0 + H and tr["why"] == "TP" and tr["fee_in"] == pytest.approx(0.0002)
    assert got["counts"]["post_only_reject"] == 0 and got["counts"]["placement_unmeasured"] == 0
    assert got["missed"] == []
    bars, fine = _world([FLAT, FLAT, [(99.5, 98.5)] * 60])
    got = _walk(bars, [-1, 0, 0], fine=fine, book=book)
    (tr,) = got["trades"]
    assert tr["entry_ms"] == T0 + H and tr["why"] == "TP"
    assert got["counts"]["post_only_reject"] == 0 and got["counts"]["placement_unmeasured"] == 0


def test_an_order_with_no_fresh_book_rests_and_is_counted():
    # the only reading is 60 s older than the minute the order goes in - past the chase guard's
    # 59 s, it is not that minute's book. The order rests on what the minutes show (minute 0 fills
    # it) and is counted placement_unmeasured, though that old book crossed it
    bars, fine = _fixed_world(FLAT, [(101.5, 100.5)] * 60)
    stale = _book((T0 + H - 60_000, 99.9, 100.0, 0.0001, 0.0001))
    got = _walk(bars, [1, 0, 0], fine=fine, book=stale)
    assert len(got["trades"]) == 1 and got["counts"]["placement_unmeasured"] == 1
    assert got["counts"]["post_only_reject"] == 0
    # 59 s old it is the minute's own book (the chase guard's line), and it rejects the order
    fresh = _book((T0 + H - 59_000, 99.9, 100.0, 0.0001, 0.0001))
    got = _walk(bars, [1, 0, 0], fine=fine, book=fresh)
    assert got["trades"] == [] and got["counts"]["post_only_reject"] == 1
    # no book at all: it rests, counted
    got = _walk(bars, [1, 0, 0], fine=fine)
    assert len(got["trades"]) == 1 and got["counts"]["placement_unmeasured"] == 1


def test_a_snapshot_only_hours_book_is_as_old_as_its_hour():
    # 15-minute candles. An hour Gate published only as a snapshot stamps its one hour-start book
    # on every minute (`book_history.book_age_s`): at 0:15 that book is 15 minutes old, so it
    # cannot reject an order placed then - the order rests, counted - while the same prices from
    # that minute's own full replay do reject it
    bars, fine = _world([[(100.1, 99.9)] * 15, [(100.1, 99.9)] * 15, [(101.5, 100.5)] * 15],
                        bar_ms=15 * M)
    kw = {"contract": CONTRACT, "fees": FEES, "cost_check": False, "flat_slip": 0.0, "fine": fine}
    snap = _book((T0 + 15 * M, 99.9, 100.0, 0.0001, 0.0001), source="snapshot")
    got = ve.walk(bars, [1, 0, 0], FIXED, bar_s=900, book=snap, **kw)
    assert len(got["trades"]) == 1 and got["counts"]["placement_unmeasured"] == 1
    full = _book((T0 + 15 * M, 99.9, 100.0, 0.0001, 0.0001))
    got = ve.walk(bars, [1, 0, 0], FIXED, bar_s=900, book=full, **kw)
    assert got["trades"] == [] and got["counts"]["post_only_reject"] == 1


def test_the_runners_cost_check_answers_before_the_post_only_check():
    # a book that crosses the order AND charges 0.5% to sell out: the runner's cost check refuses
    # it first (0.02% in + 0.075% + 0.5% out = 0.595% of a 1% target, past its 50% line), so no
    # order goes in at all - no rejected order, no twin
    bars, fine = _fixed_world(FLAT, [(101.5, 100.5)] * 60)
    book = _book((T0 + H, 99.9, 100.0, 0.005, 0.005))
    got = _walk(bars, [1, 0, 0], fine=fine, book=book, cost_check=True)
    assert got["counts"]["gate_blocked"] == 1 and got["counts"]["post_only_reject"] == 0
    assert got["missed"] == [] and got["trades"] == []


# F2 (review I2): a stop the points do not show is proven by the candle's own LOSING-side extreme.
# A long trades through its limit before it can fall to a stop under it (a short mirrors this),
# so the fill candle's own low at or under the stop came after the fill


def test_a_stop_hidden_after_a_fill_point_with_no_point_after_it_is_stamped_at_the_fill():
    # only minute 0 of the fill hour (the fill) is in the archive; one of the missing minutes
    # traded down to 97.5. No point follows the fill inside the hour, so the stop, 98.0, is stamped
    # at the fill point itself
    fill_hour = [(100.1, 99.9)] * 30 + [(99.0, 97.5)] + [(100.1, 99.9)] * 29
    bars, fine = _fixed_world(fill_hour, [(101.5, 100.5)] * 60)
    got = _walk(bars, [1, 0, 0], fine=_without(fine, T0 + H + M, T0 + 2 * H))
    (tr,) = got["trades"]
    assert tr["why"] == "SL" and tr["entry_ms"] == T0 + H and tr["exit_ms"] == T0 + H
    assert tr["exit"] == pytest.approx(98.0) and got["counts"]["settled_by_candle"] == 1


def test_a_short_stop_hidden_after_the_fill_point_is_proven_by_the_candles_high():
    # a short sells at minute 0 (its 100.1 high is over the 100.0 limit); minute 30 trades up to
    # 102.5, over the 102.0 stop. Every minute: out at minute 30
    fill_hour = [(100.1, 99.9)] * 30 + [(102.5, 101.0)] + [(100.1, 99.9)] * 29
    bars, fine = _world([FLAT, fill_hour, [(99.5, 98.5)] * 60])
    (tr,) = _walk(bars, [-1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + H + 30 * M
    # minute 30 missing: the hour's own 102.5 high came after the fill, so the stop was hit -
    # out at 102.0 at minute 1, -2% of $50 less the fees = -1.0475; before the fix the trade went
    # on to hour 2's 99.0 target
    got = _walk(bars, [-1, 0, 0], fine=_without(fine, T0 + H + 30 * M, T0 + H + 31 * M))
    (tr,) = got["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + H + M and tr["exit"] == pytest.approx(102.0)
    assert tr["pnl"] == pytest.approx(-1.0 - 50.0 * (0.0002 + 0.00075))
    assert got["counts"]["settled_by_candle"] == 1


def test_a_target_the_rest_of_the_fill_candle_shows_cannot_outrun_a_hidden_stop():
    # minute 0 fills; minute 20 trades down to 97.5 (the stop); minute 40 up to 101.5 (the 101.0
    # target). Every minute: the stop came first
    fill_hour = ([(100.1, 99.9)] * 20 + [(99.0, 97.5)] + [(100.1, 99.9)] * 19
                 + [(101.5, 100.5)] + [(100.1, 99.9)] * 19)
    bars, fine = _fixed_world(fill_hour, FLAT)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + H + 20 * M
    # minute 20 missing: the points show only the target, but the hour's low proves the stop and
    # nothing says which came first - the stop, counted unclear (the repo's worst case). Before
    # the fix: TP at minute 40, +0.48
    got = _walk(bars, [1, 0, 0], fine=_without(fine, T0 + H + 20 * M, T0 + H + 21 * M))
    (tr,) = got["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + H + M and tr["exit"] == pytest.approx(98.0)
    assert got["counts"]["settled_by_candle"] == 1 and got["counts"]["unclear"] == 1


def test_a_whole_hour_whose_hidden_minute_holds_the_stop_cannot_book_its_visible_target():
    # the final review's probe 2. Hour 2: minute 10 trades down to 97.5 (the stop), minute 40 up
    # to 101.5 (the target). Every minute: SL at minute 10
    late = ([(100.3, 99.5)] * 10 + [(99.0, 97.5)] + [(100.3, 99.5)] * 29 + [(101.5, 100.5)]
            + [(100.3, 99.5)] * 19)
    bars, fine = _fixed_world(FLAT, late)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H + 10 * M
    # minute 10 missing: the minutes left show the target at 40, while the hour's own low proves
    # the stop, in an order nothing shows. Worst case: the stop by the candle rule, at the hour's
    # open - which is 99.9, over 98.0, so at 98.0 - counted settled_by_candle and unclear, and the
    # hour is one whose points miss its low (partial_points). Before the fix: TP, +0.48
    got = _walk(bars, [1, 0, 0], fine=_without(fine, T0 + 2 * H + 10 * M, T0 + 2 * H + 11 * M))
    (tr,) = got["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H and tr["exit"] == pytest.approx(98.0)
    assert tr["pnl"] == pytest.approx(-1.0 - 50.0 * (0.0002 + 0.00075))
    assert got["counts"]["settled_by_candle"] == 1 and got["counts"]["unclear"] == 1
    assert got["counts"]["partial_points"] == 1
    # a short mirrors it: minute 10 trades up to 102.5, over the 102.0 stop; minute 40 down to
    # 98.5, under the 99.0 target; the hour opens at 100.1, so the stop fills at 102.0
    late = ([(100.5, 99.7)] * 10 + [(102.5, 101.0)] + [(100.5, 99.7)] * 29 + [(99.5, 98.5)]
            + [(100.5, 99.7)] * 19)
    bars, fine = _world([FLAT, FLAT, late])
    (tr,) = _walk(bars, [-1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H + 10 * M
    got = _walk(bars, [-1, 0, 0], fine=_without(fine, T0 + 2 * H + 10 * M, T0 + 2 * H + 11 * M))
    (tr,) = got["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H and tr["exit"] == pytest.approx(102.0)
    assert got["counts"]["settled_by_candle"] == 1 and got["counts"]["unclear"] == 1


def test_a_trail_whose_hidden_minute_hits_its_stop_cannot_ride_on_to_a_later_exit():
    # hour 23 begins with the trail at 99.485 (the fill hour lifted it). Minute 10 trades down to
    # 99.0, under it; minute 20 up to 101.0; minute 30's low is 100.3. Every minute: out at
    # minute 10, at 99.485
    hour = ([(100.1, 99.9)] * 10 + [(100.0, 99.0)] + [(100.1, 99.9)] * 9 + [(101.0, 100.4)]
            + [(101.0, 100.5)] * 9 + [(100.6, 100.3)] + [(100.5, 100.3)] * 29)
    bars, fine, dirs = _trail_world(hour, FLAT)
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine)["trades"]
    assert tr["why"] == "TRAIL" and tr["exit_ms"] == T0 + 23 * H + 10 * M
    assert tr["exit"] == pytest.approx(99.485)
    # minute 10 missing: minute 20 would lift the trail to 101.0 - 0.615 = 100.385 and minute 30
    # leave there, a WIN of 0.385% where every minute gave a loss. But the hour's own 99.0 low is
    # under the 99.485 it BEGAN with (a trail only tightens inside an hour): the stop was hit in a
    # hidden minute, and which came first is unknowable - out at 99.485 at the hour's open,
    # counted settled_by_candle and unclear
    got = _walk(bars, dirs, TRAIL, fine=_without(fine, T0 + 23 * H + 10 * M, T0 + 23 * H + 11 * M))
    (tr,) = got["trades"]
    assert tr["why"] == "TRAIL" and tr["exit_ms"] == T0 + 23 * H
    assert tr["exit"] == pytest.approx(99.485)
    assert got["counts"]["settled_by_candle"] == 1 and got["counts"]["unclear"] == 1


def test_every_candle_a_trade_lives_through_on_missing_points_is_counted():
    # F2(c) and F5. Hour 1 (the fill) has every minute. Hour 2 lacks minute 30, whose 100.6 is the
    # hour's high: its other minutes show 100.4 at most - partial_points. Hour 3 lacks minute 5,
    # which lies inside what its other minutes show: nothing hidden, nothing counted. Hour 4 has
    # no minutes at all and decides nothing - no_points all the same. Hour 5's minute 0 trades
    # through the 101.0 target
    quiet = [(100.4, 99.6)] * 60
    peak = [(100.4, 99.6)] * 30 + [(100.6, 99.8)] + [(100.4, 99.6)] * 29
    bars, fine = _fixed_world(FLAT, peak, quiet, quiet, [(101.5, 100.5)] * 60)
    holes = _without(fine, T0 + 2 * H + 30 * M, T0 + 2 * H + 31 * M)
    holes = _without(holes, T0 + 3 * H + 5 * M, T0 + 3 * H + 6 * M)
    holes = _without(holes, T0 + 4 * H, T0 + 5 * H)
    got = _walk(bars, [1, 0, 0, 0, 0, 0], fine=holes)
    (tr,) = got["trades"]
    assert tr["why"] == "TP" and tr["exit_ms"] == T0 + 5 * H
    assert got["counts"]["partial_points"] == 1 and got["counts"]["no_points"] == 1
    # with no minutes at all, all five hours the trade lives through, fill to exit, are counted
    got = _walk(bars, [1, 0, 0, 0, 0, 0], fine=None)
    assert got["counts"]["no_points"] == 5 and got["counts"]["partial_points"] == 0


# F3 (review I3): a hold past a funding list that stopped is estimated, never a measured zero


def test_a_long_hold_past_a_stale_funding_list_pays_the_average_rate_and_is_counted():
    # the final review's probe. The saved list ends at T0 (0.1% every 8 hours) while a long is
    # held 41 hours, T0 + 1h to T0 + 42h. The list answers to one cycle past its last settlement
    # (T0 + 8h); the 34 hours after it pay 34 / 8 x 0.1% = 0.425% of $50 = $0.2125, estimated
    # and counted. Before the fix they paid $0.00 as if measured: +0.48 instead of +0.2675
    fund = [{"settle_ms": T0 - 8 * H, "rate": 0.001, "cycle_h": 8},
            {"settle_ms": T0, "rate": 0.001, "cycle_h": 8}]
    quiet = [(100.3, 99.7)] * 60
    bars, fine = _world([FLAT, FLAT] + [quiet] * 40 + [[(101.5, 100.5)] * 60])
    got = _walk(bars, [1] + [0] * 42, fine=fine, funding=fund)
    (tr,) = got["trades"]
    assert (tr["entry_ms"], tr["exit_ms"], tr["why"]) == (T0 + H, T0 + 42 * H, "TP")
    assert tr["funding"] == pytest.approx(-0.2125) and tr["funding_estimated"] is True
    assert tr["pnl"] == pytest.approx(0.50 - 50.0 * 0.0004 - 0.2125)
    assert got["counts"]["funding_estimated"] == 1


# F4 (review I4): one "a touch stops" rule, and what each kind of exit pays


def test_a_touch_stops_the_engines_trades_on_both_sides():
    # the fixed long's hour 2 trades down to exactly 98.0, its stop, and no lower
    bars, fine = _fixed_world(FLAT, [(100.3, 98.0)] * 60)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H and tr["exit"] == pytest.approx(98.0)
    # the short's hour 2 trades up to exactly 102.0
    bars, fine = _world([FLAT, FLAT, [(102.0, 99.7)] * 60])
    (tr,) = _walk(bars, [-1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H and tr["exit"] == pytest.approx(102.0)
    # the minute an order fills in touches its stop: out in that minute, long and short
    bars, fine = _fixed_world([(100.1, 98.0)] + [(100.1, 99.9)] * 59, [(101.5, 100.5)] * 60)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + H
    bars, fine = _world([FLAT, [(102.0, 99.9)] + [(100.1, 99.9)] * 59, [(99.5, 98.5)] * 60])
    (tr,) = _walk(bars, [-1, 0, 0], fine=fine)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + H
    # a hidden minute that only touches the stop, shown by the hour's own low of exactly 98.0
    late = [(100.3, 99.5)] * 30 + [(100.3, 98.0)] + [(100.3, 99.5)] * 29
    bars, fine = _fixed_world(FLAT, late)
    got = _walk(bars, [1, 0, 0], fine=_without(fine, T0 + 2 * H + 30 * M, T0 + 2 * H + 31 * M))
    (tr,) = got["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H
    assert got["counts"]["settled_by_candle"] == 1
    # a trail: after the fill hour its stop is 100.1 - 3 x ATR(20), worked out here exactly as the
    # engine works it out (~99.485); a minute of hour 23 whose low is exactly that leaves at it
    from tradingagents import v3_rules as vr

    probe, _fine, _dirs = _trail_world()
    stop = 100.1 - 3.0 * vr.atr(probe["h"], probe["l"], probe["c"], vr.ATR_N)[21]
    bars, fine, dirs = _trail_world([(100.1, 99.9)] * 10 + [(100.1, stop)] + [(100.1, 99.9)] * 49)
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine)["trades"]
    assert tr["why"] == "TRAIL" and tr["exit_ms"] == T0 + 23 * H + 10 * M and tr["exit"] == stop
    # ... and when that minute is missing, the hour's own low touching the stop proves the hit
    got = _walk(bars, dirs, TRAIL, fine=_without(fine, T0 + 23 * H + 10 * M, T0 + 23 * H + 11 * M))
    (tr,) = got["trades"]
    assert tr["why"] == "TRAIL" and tr["exit_ms"] == T0 + 23 * H
    assert got["counts"]["settled_by_candle"] == 1


def test_only_a_resting_target_pays_the_maker_fee_every_market_exit_pays_the_taker_and_its_gap():
    # a book is recorded at each exit minute: buying there costs 0.09%, selling 0.04%. A long
    # leaves by selling. Every exit that is not a resting target - the trail, the average, the end
    # of the data, the time limit - pays the taker fee and that minute's `sell`; a target that
    # rests and is traded through pays the maker fee and no gap, even with a book recorded
    def at_exit(ms):
        return _book((ms, 99.0, 99.1, 0.0009, 0.0004))

    # TRAIL: out at 105.335 at hour 23's open (the trailing stop test's world)
    up = [(100.05 + 0.1 * m, 99.8 + 0.1 * m) for m in range(60)]
    drop = [(105.9, 104.0)] + [(104.5, 98.0)] * 59
    bars, fine = _world([FLAT] * 21 + [SIGNAL, up, drop])
    (tr,) = _walk(bars, [0] * 21 + [1, 0, 0], TRAIL, fine=fine,
                  book=at_exit(T0 + 23 * H))["trades"]
    assert tr["why"] == "TRAIL" and tr["fee_out"] == 0.00075 and tr["measured_exit"] is True
    assert tr["slip_out"] == pytest.approx(0.0004)
    # $162 of coin (a 0.615 stop from 100.0 at $1 risk is 162 lots of 0.01), +5.335% of it, less
    # 0.02% in and 0.075% + 0.04% out
    assert tr["pnl"] == pytest.approx(162.0 * (0.05335 - 0.0002 - 0.00075 - 0.0004))
    # MA: out at hour 22's close, 99.7, under its 3-candle average (the average test's world)
    sag = [(100.1, 99.8)] + [(99.8, 99.6)] * 59
    bars, fine = _world([FLAT] * 21 + [SIGNAL, sag])
    (tr,) = _walk(bars, [0] * 21 + [1, 0], {"kind": "trail", "atr_mult": 3.0, "ma_n": 3},
                  fine=fine, book=at_exit(T0 + 23 * H))["trades"]
    assert tr["why"] == "MA" and tr["fee_out"] == 0.00075
    assert tr["slip_out"] == pytest.approx(0.0004)
    # END: still open when the data ends, out at the last close, an hour after the fill
    bars, fine = _fixed_world(FLAT)
    (tr,) = _walk(bars, [1, 0], fine=fine, book=at_exit(T0 + 2 * H))["trades"]
    assert tr["why"] == "END" and tr["fee_out"] == 0.00075
    assert tr["slip_out"] == pytest.approx(0.0004)
    # TIME: the snap-back's time limit, out at the close of its second candle (the snap test)
    dip = [(100.0, 96.9)] + [(97.2, 96.9)] * 59
    fill = [(97.2, 97.0)] + [(97.3, 97.1)] * 59
    bars, fine = _world([FLAT] * 20 + [dip, fill, [(97.5, 97.2)] * 60])
    (tr,) = _walk(bars, [0] * 20 + [1, 0, 0], SNAP, fine=fine,
                  book=at_exit(T0 + 23 * H))["trades"]
    assert tr["why"] == "TIME" and tr["fee_out"] == 0.00075
    assert tr["slip_out"] == pytest.approx(0.0004)
    # TP: the resting target, traded through at hour 2's open: maker, no gap
    bars, fine = _fixed_world(FLAT, [(101.5, 100.5)] * 60)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine, book=at_exit(T0 + 2 * H))["trades"]
    assert tr["why"] == "TP" and tr["fee_out"] == 0.0002 and tr["slip_out"] == 0.0


# F5: the review's "fix before Part 2 builds on it" list


@pytest.mark.parametrize("field, value", [("contract_size", 0.0), ("contract_size", -0.01),
                                          ("mmr", 0.0), ("mmr", -0.005), ("max_lev", 0)])
def test_a_contract_that_cannot_be_measured_is_refused_by_name(field, value):
    # unknown is not zero: a listing with no maintenance rate reads 0.0, and at 0 a 3% stop gets
    # 20x where Gate's real 5% allows 11x (at 20x, 1/20 - 5% = 0: liquidated at the entry). A lot
    # of no coin, or no leverage at all, cannot be sized either
    bars, fine = _fixed_world(FLAT, [(101.5, 100.5)] * 60)
    with pytest.raises(ValueError, match=f"contract {field}"):
        _walk(bars, [1, 0, 0], fine=fine, contract={**CONTRACT, field: value})


def test_a_candle_flagged_closed_places_no_order_even_without_the_cost_check():
    # the closed flag is the runner's own rule for a stock token's dead candle: it holds whether
    # or not the cost check is asked
    bars, fine = _fixed_world([(100.1, 99.0)] * 60, [(101.5, 100.5)] * 60)
    got = _walk(bars, [1, 0, 0], fine=fine, cost_check=False, closed=[True, False, False])
    assert got["trades"] == [] and got["missed"] == [] and got["counts"]["closed_skip"] == 1
    got = _walk(bars, [1, 0, 0], fine=fine, cost_check=False, closed=[False, False, False])
    assert len(got["trades"]) == 1 and got["counts"]["closed_skip"] == 0


def test_a_stop_the_candle_rule_decides_fills_at_the_open_when_the_candle_opened_past_it():
    # review M1. No minutes anywhere. The long fills by the candle (hour 1 trades down to 99.5);
    # hour 2 OPENS at 96.0, under the 98.0 stop, then trades up to 97.0 and down to 95.0. The stop
    # was marketable from the first trade: out at 96.0, not at the hour's best price, 97.0, which
    # may have come at its end. -4% of $50 = -2.00, less 0.02% in and 0.075% out = -2.0475
    gap = [(96.5, 95.5)] + [(97.0, 95.0)] * 59                   # opens at (96.5 + 95.5) / 2
    bars, _fine = _fixed_world([(100.2, 99.5)] * 60, gap)
    (tr,) = _walk(bars, [1, 0, 0], fine=None)["trades"]
    assert tr["why"] == "SL" and tr["exit_ms"] == T0 + 2 * H and tr["exit"] == pytest.approx(96.0)
    assert tr["pnl"] == pytest.approx(-2.0 - 50.0 * (0.0002 + 0.00075))
    # a short: hour 2 opens at 104.0, over the 102.0 stop, and trades 103.0-105.0: out at 104.0
    bars, _fine = _world([FLAT, [(100.5, 99.8)] * 60, [(104.5, 103.5)] + [(105.0, 103.0)] * 59])
    (tr,) = _walk(bars, [-1, 0, 0], fine=None)["trades"]
    assert tr["why"] == "SL" and tr["exit"] == pytest.approx(104.0)
    # the hour the order fills in opens past the stop (both decided by the candle): the order
    # fills at its 100.0 limit, and the stop at the open, 96.0, in that same hour
    bars, _fine = _fixed_world(gap, FLAT)
    (tr,) = _walk(bars, [1, 0, 0], fine=None)["trades"]
    assert tr["entry_ms"] == T0 + H and tr["exit_ms"] == T0 + H and tr["exit"] == pytest.approx(96.0)
    # a trail: the hour after the fill opens at 98.0, under the 99.385 trail (with no minutes, the
    # fill hour's high never lifted it), and trades 97.0-99.0: out at 98.0, not at 99.0
    bars, _fine, dirs = _trail_world([(98.5, 97.5)] + [(99.0, 97.0)] * 59)
    (tr,) = _walk(bars, dirs, TRAIL, fine=None)["trades"]
    assert tr["why"] == "TRAIL" and tr["exit_ms"] == T0 + 23 * H
    assert tr["exit"] == pytest.approx(98.0)
    # a trail whose hour 23 has minutes but not minute 0: it opened at 99.0, under the 99.485 the
    # hour began with - out at the open, 99.0. With every minute, minute 0's whole range (98.8 to
    # 99.2) is under the stop, so it fills at that minute's best price, 99.2
    bars, fine, dirs = _trail_world([(99.2, 98.8)] + [(100.1, 99.9)] * 59)
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine)["trades"]
    assert tr["exit_ms"] == T0 + 23 * H and tr["exit"] == pytest.approx(99.2)
    got = _walk(bars, dirs, TRAIL, fine=_without(fine, T0 + 23 * H, T0 + 23 * H + M))
    (tr,) = got["trades"]
    assert tr["exit_ms"] == T0 + 23 * H and tr["exit"] == pytest.approx(99.0)
    assert got["counts"]["settled_by_candle"] == 1


def test_no_trade_goes_above_the_rooms_own_20x_and_a_wide_stop_goes_lower():
    """Operator, Oct 22, 2026, on money per trade: "Same risk, lower leverage".
    The first tab run (Oct 23, 2026) traded BTC at 64x because Gate lets BTC go
    to 100x; v3 now stops at the leverage the rooms trade at (20x) and goes
    lower only when a wide stop needs it (RCA-2026-10-23-C)."""
    big = {**CONTRACT, "max_lev": 100}
    bars, fine = _fixed_world([(100.1, 99.0)] * 60, [(101.5, 100.5)] * 60)
    # a 2% stop at maintenance 0.5%: 0.8 x (1/L - 0.005) > 0.02 needs 1/L > 0.03,
    # so the highest safe leverage is 33x — and the rooms' 20x is the cap
    (tr,) = _walk(bars, [1, 0, 0], fine=fine, contract=big)["trades"]
    assert tr["leverage"] == 20
    assert tr["margin"] == pytest.approx(tr["notional"] / 20)
    # an 8% stop: 0.8 x (1/L - 0.005) > 0.08 needs 1/L > 0.105, so L = 9
    wide = {"kind": "fixed", "tp": 0.16, "sl": 0.08}
    (tr,) = _walk(bars, [1, 0, 0], wide, fine=fine, contract=big)["trades"]
    assert tr["leverage"] == 9


# ---- parked at the final review of Part 1, added in Part 2a's first commit: a SHORT trail's -----
# ---- stop that a hole hides, (a) in the rest of the fill candle and (b) in a whole candle --------

SHORT_TRAIL_FILL = [(100.2, 99.95)] + [(100.1, 99.9)] * 59   # sells at 100.0 in minute 0


def test_a_short_trails_hidden_stop_in_the_rest_of_the_fill_candle_is_proven_by_its_high():
    # (a) the short sells at minute 0 (its 100.2 high is over the 100.0 limit); the trail starts
    # 3 x 0.205 = 0.615 over the entry, 100.615. Minutes 1-29 pull it down to 99.9 + 0.615 =
    # 100.515 and minute 30 trades up to 101.0: with every minute, out at minute 30 at 100.515
    fill_hour = SHORT_TRAIL_FILL[:30] + [(101.0, 99.9)] + SHORT_TRAIL_FILL[31:]
    bars, fine = _world([FLAT] * 21 + [SIGNAL, fill_hour, FLAT])
    dirs = [0] * 21 + [-1, 0, 0]
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine)["trades"]
    assert (tr["why"], tr["exit_ms"]) == ("TRAIL", T0 + 22 * H + 30 * M)
    assert tr["exit"] == pytest.approx(100.515)
    # minute 30 missing: a short trades through its limit before it can rise to a stop over it,
    # so the hour's own 101.0 high came after the fill and is over the 100.615 the trail BEGAN
    # with - the stop was hit. Whether minutes 1-29 pulled it down first is unknowable: out at
    # 100.615, stamped at minute 1, the first point after the fill
    got = _walk(bars, dirs, TRAIL, fine=_without(fine, T0 + 22 * H + 30 * M, T0 + 22 * H + 31 * M))
    (tr,) = got["trades"]
    assert (tr["why"], tr["exit_ms"]) == ("TRAIL", T0 + 22 * H + M)
    assert tr["exit"] == pytest.approx(100.615)
    assert got["counts"]["settled_by_candle"] == 1 and got["counts"]["unclear"] == 0


def test_a_short_trails_hidden_stop_in_a_whole_candle_cannot_ride_on_to_a_later_exit():
    # (b) the mirror of
    # test_a_trail_whose_hidden_minute_hits_its_stop_cannot_ride_on_to_a_later_exit.
    # Hour 23 begins with the short's trail at 100.515. Minute 10 trades up to 101.0, over it;
    # minute 20 down to 99.0 (which would pull the stop to 99.615) and minute 30 up to 99.7.
    # Every minute: out at minute 10, at 100.515
    hour = ([(100.1, 99.9)] * 10 + [(101.0, 100.0)] + [(100.1, 99.9)] * 9 + [(99.6, 99.0)]
            + [(99.5, 99.0)] * 9 + [(99.7, 99.4)] + [(99.7, 99.5)] * 29)
    bars, fine = _world([FLAT] * 21 + [SIGNAL, SHORT_TRAIL_FILL, hour, FLAT])
    dirs = [0] * 21 + [-1, 0, 0, 0]
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine)["trades"]
    assert (tr["why"], tr["exit_ms"]) == ("TRAIL", T0 + 23 * H + 10 * M)
    assert tr["exit"] == pytest.approx(100.515)
    # minute 10 missing: the minutes left would exit at 99.615 at minute 30 (a WIN for the short),
    # but the hour's own 101.0 high is over the 100.515 it began with (a trail only tightens inside
    # an hour): the stop was hit in a hidden minute, in an order nothing shows - out at 100.515 at
    # the hour's open (it opened at 100.0, under the stop), counted settled_by_candle and unclear
    got = _walk(bars, dirs, TRAIL, fine=_without(fine, T0 + 23 * H + 10 * M, T0 + 23 * H + 11 * M))
    (tr,) = got["trades"]
    assert (tr["why"], tr["exit_ms"]) == ("TRAIL", T0 + 23 * H)
    assert tr["exit"] == pytest.approx(100.515)
    assert got["counts"]["settled_by_candle"] == 1 and got["counts"]["unclear"] == 1


# ---- Backtest v3 Part 2a: the forced exit (v3_strength's weekly rank) and the contract read --------


def _forced_at(n, *flagged):
    return [k in flagged for k in range(n)]


def test_a_forced_candle_closes_the_trade_at_its_close_at_the_market():
    # the trail world: the fill hour (22) lifts the trail to 100.1 - 0.615 = 99.485, and hours 23
    # and 24 trade 99.9-100.1, never down to it. Flagged at hour 23, the trade leaves at that hour's
    # close, 100.0, at T0 + 24h, at the market. $162 of coin (a 0.615 stop from 100.0 at $1 risk),
    # +0% of it, less 0.02% in and the taker 0.075% plus the recorded 0.04% out = -0.2187
    bars, fine, dirs = _trail_world(FLAT, FLAT)
    book = _book((T0 + 24 * H, 99.95, 100.05, 0.0009, 0.0004))
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine, book=book, forced=_forced_at(25, 23))["trades"]
    assert (tr["why"], tr["exit_ms"], tr["exit_bar"]) == ("RANK", T0 + 24 * H, 23)
    assert tr["exit"] == pytest.approx(100.0) and tr["fee_out"] == 0.00075
    assert tr["slip_out"] == pytest.approx(0.0004)
    assert tr["pnl"] == pytest.approx(-162.0 * (0.0002 + 0.00075 + 0.0004))
    # no flags: the rule of before - still open when the data ends, out at hour 24's close
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine, book=book)["trades"]
    assert (tr["why"], tr["exit_ms"]) == ("END", T0 + 25 * H)
    # the PRICE it leaves at is the candle's CLOSE. The flagged hour above is flat - it opens and
    # closes 100.0 - which cannot tell the close from the open, or from the hour before's close.
    # This one OPENS 100.2 and CLOSES 100.1 (high 100.3, low 100.0; the hour before closed 100.0
    # and the hour after opens 100.0). Its highs lift the trail to 100.3 - 0.615 = 99.685, which
    # its 100.0 low never reaches: it leaves at the close, +0.1% of $162 = +0.162, less 0.02% in
    # and the taker 0.075% plus the recorded 0.04% out (-0.2187) = -0.0567
    hour = [(100.3, 100.1)] * 30 + [(100.2, 100.0)] * 30
    bars, fine, dirs = _trail_world(hour, FLAT)
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine, book=book, forced=_forced_at(25, 23))["trades"]
    assert (tr["why"], tr["exit_ms"], tr["exit_bar"]) == ("RANK", T0 + 24 * H, 23)
    assert tr["exit"] == pytest.approx(100.1)               # the close, not the 100.2 open
    assert tr["slip_out"] == pytest.approx(0.0004)
    assert tr["pnl"] == pytest.approx(162.0 * (100.1 / 100.0 - 1 - 0.0002 - 0.00075 - 0.0004))


def test_a_stop_inside_the_forced_candle_comes_first():
    # minute 10 of the flagged hour trades down to 99.0, under the 99.485 trail: the stop was hit
    # before the hour closed, so it is the trail's exit, at 99.485, never the forced one
    hour = [(100.1, 99.9)] * 10 + [(100.0, 99.0)] + [(100.1, 99.9)] * 49
    bars, fine, dirs = _trail_world(hour, FLAT)
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine, forced=_forced_at(25, 23))["trades"]
    assert (tr["why"], tr["exit_ms"]) == ("TRAIL", T0 + 23 * H + 10 * M)
    assert tr["exit"] == pytest.approx(99.485)


def test_a_forced_exit_holds_for_a_short_and_for_a_missed_orders_twin():
    # a short sells at 100.0 in minute 0; the fill hour's 99.9 lows pull its trail down to 100.515,
    # and hour 23's 100.1 highs never reach it: flagged, it buys back at hour 23's close, 100.0.
    # +0% of $162 less 0.02% in and 0.075% out, no gap recorded here: -0.1539
    bars, fine = _world([FLAT] * 21 + [SIGNAL, SHORT_TRAIL_FILL, FLAT, FLAT])
    (tr,) = _walk(bars, [0] * 21 + [-1, 0, 0, 0], TRAIL, fine=fine,
                  forced=_forced_at(25, 23))["trades"]
    assert (tr["side"], tr["why"], tr["exit_ms"]) == (-1, "RANK", T0 + 24 * H)
    assert tr["pnl"] == pytest.approx(-162.0 * (0.0002 + 0.00075))
    # a long whose hour 22 only touches its 100.0 limit is missed; its twin buys at that hour's
    # open, 100.1, with the same 0.615 trail (99.485, lifted to 100.2 - 0.615 = 99.585 by the
    # hour's highs) and leaves where the real trade would have: at the flagged hour's close
    bars, fine = _world([FLAT] * 21 + [SIGNAL, [(100.2, 100.0)] * 60, FLAT, FLAT])
    got = _walk(bars, [0] * 21 + [1, 0, 0, 0], TRAIL, fine=fine, forced=_forced_at(25, 23))
    assert got["trades"] == [] and got["counts"]["missed"] == 1
    twin = got["missed"][0]["market"]
    assert twin["entry"] == pytest.approx(100.1)
    assert (twin["why"], twin["exit_ms"]) == ("RANK", T0 + 24 * H)


def test_a_fixed_exit_is_forced_out_too():
    # walk's docs say any of the three exit kinds can be forced and the tests above all use the
    # trail. A long with a 1% target (101.0) and a 2% stop (98.0) fills at minute 0 of hour 1, at
    # 100.0; hour 1 trades 99.9-100.2 and hour 2 99.9-100.1, so neither is reached and the trade
    # is open at the close of the flagged hour 2: out there as RANK (the data ends there too, so
    # with no flag the same trade would be END)
    fill_hour = [(100.1, 99.9)] * 10 + [(100.0, 99.95)] + [(100.2, 100.0)] * 49
    bars, fine = _fixed_world(fill_hour, FLAT)
    (tr,) = _walk(bars, [1, 0, 0], FIXED, fine=fine, forced=_forced_at(3, 2))["trades"]
    assert (tr["why"], tr["exit_ms"], tr["exit_bar"]) == ("RANK", T0 + 3 * H, 2)


def test_the_contract_is_read_from_the_listing_one_way_and_a_missing_field_is_named():
    # Gate's BTC_USDT listing as `fx.contract_spec` gives it (Oct 23, 2026)
    spec = {"contractSize": 0.0001, "minVol": 1, "maintenanceMarginRate": 0.003,
            "maxLeverage": 200, "minLeverage": 1, "takerFeeRate": 0.00075}
    assert ve.contract_of(spec) == {"contract_size": 0.0001, "min_vol": 1, "mmr": 0.003,
                                    "max_lev": 200, "min_lev": 1}
    bare = {k: v for k, v in spec.items() if k not in ("minVol", "minLeverage")}
    assert (ve.contract_of(bare)["min_vol"], ve.contract_of(bare)["min_lev"]) == (1, 1)
    for key in ("contractSize", "maintenanceMarginRate", "maxLeverage"):
        with pytest.raises(ValueError, match=f"contract {key} is missing"):
            ve.contract_of({k: v for k, v in spec.items() if k != key})
    with pytest.raises(ValueError, match="maintenanceMarginRate = 'n/a' is not a number"):
        ve.contract_of({**spec, "maintenanceMarginRate": "n/a"})
    with pytest.raises(ValueError, match="minLeverage = 0"):
        ve.contract_of({**spec, "minLeverage": 0})
    # a rate READ as 0 passes the reading and is refused by the engine's own check, by name
    with pytest.raises(ValueError, match="contract mmr = 0.0"):
        ve.contract_of({**spec, "maintenanceMarginRate": 0.0})


# ---- Backtest v3 Part 2b: a trade keeps the stop and the target its order went in with ---------

def test_a_trade_keeps_the_stop_and_target_its_order_went_in_with():
    # a fixed 2% stop and 1% target on a 100.0 entry
    fill_hour = [(100.1, 99.9)] * 10 + [(100.0, 99.95)] + [(100.5, 100.0)] * 49
    bars, fine = _fixed_world(fill_hour, [(101.5, 100.5)] + [(101.6, 101.0)] * 59)
    (tr,) = _walk(bars, [1, 0, 0], fine=fine)["trades"]
    assert tr["stop_px"] == pytest.approx(98.0) and tr["target_px"] == pytest.approx(101.0)
    # a short: sold at 100.0 with the stop 2% above and the target 1% below
    fill_hour = [(100.1, 99.9)] + [(99.95, 99.5)] * 59
    bars, fine = _fixed_world(fill_hour, [(99.5, 98.5)] * 60)
    (tr,) = _walk(bars, [-1, 0, 0], fine=fine)["trades"]
    assert tr["stop_px"] == pytest.approx(102.0) and tr["target_px"] == pytest.approx(99.0)
    # a trail: 3 x ATR(20) 0.205 under the 100.0 signal close, and no target. The trail then LIFTS
    # its stop to ~99.485 (100.1 - 0.615, as the trail test above works it out), and a minute of
    # hour 23 touches exactly that: the trade leaves there, ABOVE the stop it went in with. The
    # row keeps the FIRST stop - the one the order went in with, never the lifted one
    from tradingagents import v3_rules as vr

    probe, _fine, _dirs = _trail_world()
    lifted = 100.1 - 3.0 * vr.atr(probe["h"], probe["l"], probe["c"], vr.ATR_N)[21]
    bars, fine, dirs = _trail_world([(100.1, 99.9)] * 10 + [(100.1, lifted)] + [(100.1, 99.9)] * 49)
    (tr,) = _walk(bars, dirs, TRAIL, fine=fine)["trades"]
    assert tr["why"] == "TRAIL" and tr["exit"] == lifted, "the trail did move its stop"
    assert tr["stop_px"] == pytest.approx(100.0 - 3 * 0.205) and tr["target_px"] is None
    assert tr["stop_px"] < lifted - 0.05, "the saved stop is the first one, not the lifted one"
