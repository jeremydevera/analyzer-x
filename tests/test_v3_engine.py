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


def _world(hours):
    """hours: one list of 60 (high, low) minutes per hour -> (bars, fine)."""
    t, hi, lo = [], [], []
    bars = {"t": [], "o": [], "h": [], "l": [], "c": []}
    for k, minutes in enumerate(hours):
        for m, (h_, l_) in enumerate(minutes):
            t.append(T0 + k * H + m * M)
            hi.append(h_)
            lo.append(l_)
        bars["t"].append(T0 + k * H)
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


def _book(*rows):
    """book_history's packed readings from (minute ms, bid, ask, buy, sell): the best prices of
    that minute and what buying / selling the runner's $100 cost there."""
    from tradingagents import book_history as bh

    return bh.pack([{"t": ms // 1000, "bid": bid, "ask": ask,
                     "spread": (ask - bid) / ((ask + bid) / 2), "buy": buy, "sell": sell,
                     "exhausted": False, "source": "full"} for ms, bid, ask, buy, sell in rows])


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


def test_the_rest_of_the_fill_candle_is_not_a_whole_candle_and_its_hole_decides_nothing():
    # the order fills at minute 0, and minute 30 of the same hour trades down to 97.5, under the
    # stop - but that minute is missing. The candle's low may predate the fill, so nothing is
    # booked on it (only a candle walked from its open is a whole one) and the trade goes on to
    # hour 2's target
    fill_hour = [(100.1, 99.9)] * 30 + [(99.0, 97.5)] + [(100.1, 99.9)] * 29
    bars, fine = _fixed_world(fill_hour, [(101.5, 100.5)] * 60)
    got = _walk(bars, [1, 0, 0], fine=_without(fine, T0 + H + 30 * M, T0 + H + 31 * M))
    (tr,) = got["trades"]
    assert tr["entry_ms"] == T0 + H and tr["why"] == "TP" and tr["exit_ms"] == T0 + 2 * H
    assert got["counts"]["settled_by_candle"] == 0
    # the same for a trail: the fill hour's minute 30 (missing) trades down to 99.0, under the
    # 99.385 the trail began with. It is the fill hour's rest, so nothing is booked on that low; the
    # points carry the stop on to 99.485 and the next hour's 99.4 low leaves at it
    fill_hour = [(100.05, 99.8)] + [(100.1, 99.9)] * 29 + [(100.1, 99.0)] + [(100.1, 99.9)] * 29
    bars, fine = _world([FLAT] * 21 + [SIGNAL, fill_hour, [(100.1, 99.4)] + [(100.1, 99.9)] * 59])
    got = _walk(bars, [0] * 21 + [1, 0, 0], TRAIL,
                fine=_without(fine, T0 + 22 * H + 30 * M, T0 + 22 * H + 31 * M))
    (tr,) = got["trades"]
    assert tr["why"] == "TRAIL" and tr["exit_ms"] == T0 + 23 * H
    assert tr["exit"] == pytest.approx(99.485) and got["counts"]["settled_by_candle"] == 0


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
    assert got["counts"] == {**dict.fromkeys(ve.COUNT_KEYS, 0), "missed": 1}


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
