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
    kw = {"contract": CONTRACT, "fees": FEES, "cost_check": False, **kw}
    return ve.walk(bars, dirs, spec, bar_s=3600, **kw)


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
