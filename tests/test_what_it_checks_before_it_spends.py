"""The criteria a trade must clear before real money moves.

Operator, `Sep 15, 2026`: *"think that you will use this for traiding high
money, you will need a guard to check if fees are too high etc"*, then *"the
goal here is to autmate the trading, so the system should do criterias before
opening a trade"*.

Every guard that existed asked about ONE trade — is its spread survivable, is
its stop reachable, is its candle fresh. Three things nothing asked:

1. **What HOLDING costs.** The gate charged getting in and getting out and
   ignored funding, which is the third cost the backtests were fixed to charge
   on 2026-08-19 (measured -4.7% on PROVE, -0.8% on APEX). A perpetual that
   pays its target away in settlements looked affordable.
2. **What the ACCOUNT can afford.** There is one position per coin and no
   ceiling above that, so total exposure was bounded only by how many signals
   happened to fire, and nothing read the wallet before sending an order.
3. **What the fill actually cost.** The gate models slippage; the runner then
   brackets off the real fill, which is right — but nothing compared the two,
   so a book that moved between the look and the order was invisible.

At 5 USDT a trade none of that shows. At size, each one is the whole risk.

Measured against the real venue while building this (`Sep 15, 2026`):

| contract | long's funding | cycle |
|---|---|---|
| NGAS_USDT | receives 0.1464% a day | 1h |
| PSXSTOCK_USDT | pays 0.0423% a day | 8h |
| STBL_USDT | pays 0.0300% a day | 4h |

and the account: 153.61 USDT equity.
"""
from __future__ import annotations

import pytest

from tradingagents import auto_trader as at


class FX:
    """A readable book, a readable wallet, and a funding rate you set."""

    def __init__(self, rate=0.0, cycle_h=8, equity=1_000.0, committed=0.0,
                 spread=0.0004, fee=0.0002):
        self.rate, self.cycle_h = rate, cycle_h
        self.equity, self.committed = equity, committed
        self._spread, self.fee = spread, fee
        self.funding_calls = 0
        self.asset_calls = 0

    def funding_now(self, symbol):
        self.funding_calls += 1
        return {"symbol": symbol, "rate": self.rate, "cycle_h": self.cycle_h,
                "next_settle_ms": 0,
                "per_day": self.rate * (24.0 / self.cycle_h)}

    def book_cost(self, symbol, notional):
        return {"symbol": symbol, "mid": 100.0, "spread": self._spread,
                "slippage": self._spread / 2, "book_exhausted": False,
                "notional_tested": notional}

    def contract_spec(self, symbol):
        return {"contractSize": 1, "takerFeeRate": self.fee}

    def assets(self):
        self.asset_calls += 1
        if self.equity is None:
            raise RuntimeError("wallet unreadable")
        return {"USDT": {"currency": "USDT", "equity": self.equity,
                         "availableOpen": self.equity - self.committed,
                         "availableBalance": self.equity - self.committed,
                         "positionMargin": self.committed}}


@pytest.fixture(autouse=True)
def _fresh():
    at._FUNDING_CACHE.clear()
    at._CAPITAL_CACHE.clear()
    at._CYCLE_GATES.clear()
    at._GATE_CACHE.clear()
    yield
    at._FUNDING_CACHE.clear()
    at._CAPITAL_CACHE.clear()


# ---------------------------------------------------------------- funding
def test_the_long_pays_when_the_rate_is_positive():
    """MEXC's sign: a POSITIVE published rate means longs pay shorts."""
    fx = FX(rate=0.0001, cycle_h=8)              # 3 settlements a day
    long = at.funding_cost("X_USDT", 1, 86400, fx=fx)
    short = at.funding_cost("X_USDT", -1, 86400, fx=fx)
    assert long["per_day"] == pytest.approx(0.0003)
    assert short["per_day"] == 0.0, "the short RECEIVES, so it is charged nothing"
    assert long["cost"] == pytest.approx(0.0003), "one day held, one day paid"


def test_a_credit_never_pays_for_a_spread():
    """NGAS: the long receives 0.1464% a day. That receipt depends on the rate
    staying put for the whole hold; the spread is paid the instant the order
    lands. A guard may not net an uncertain gain against a certain loss."""
    fx = FX(rate=-0.000061, cycle_h=1)           # NGAS, measured
    got = at.funding_cost("NGAS_USDT", 1, 86400, fx=fx)
    assert got["per_day"] == 0.0
    assert got["cost"] == 0.0


def test_an_unknown_side_is_charged_the_worse_of_the_two():
    """The screening pass does not know which way the signal will fire, and
    whichever way it does, one side pays."""
    fx = FX(rate=0.0001, cycle_h=8)
    assert at.funding_cost("X_USDT", 0, 86400, fx=fx)["per_day"] == \
        pytest.approx(0.0003)


def test_holding_is_charged_in_proportion_to_the_hold():
    fx = FX(rate=0.0001, cycle_h=8)
    day = at.funding_cost("X_USDT", 1, 86400, fx=fx)["cost"]
    hour = at.funding_cost("X_USDT", 1, 3600, fx=fx)["cost"]
    assert hour == pytest.approx(day / 24)


def test_an_unreadable_funding_rate_is_not_zero():
    """"free" and "unknown" must never read the same."""
    class Blind(FX):
        def funding_now(self, symbol):
            raise RuntimeError("venue down")

    got = at.funding_cost("X_USDT", 1, 3600, fx=Blind())
    assert got["known"] is False
    assert "venue down" in got["why"]


def test_the_rate_is_read_once_and_cached():
    """`funding_history` pages the venue 46 times for NGAS (13.5s measured);
    this one is 0.18s, and a burst of signals at one bar close must still be
    ONE call — `code 510` is one rate limit away."""
    fx = FX(rate=0.0001)
    for _ in range(25):
        at.funding_cost("X_USDT", 1, 3600, fx=fx)
    assert fx.funding_calls == 1


# ------------------------------------------------- funding inside the gate
def test_funding_is_added_to_the_round_trip():
    cheap = at.edge_check("ultosc_1h_sl3tp3", "X_USDT", 5.0,
                          fx=FX(rate=0.0), side=1)
    at._FUNDING_CACHE.clear()
    costly = at.edge_check("ultosc_1h_sl3tp3", "X_USDT", 5.0,
                           fx=FX(rate=0.001, cycle_h=1), side=1)
    assert costly["round_trip_cost"] > cheap["round_trip_cost"]
    assert costly["funding_known"] is True
    assert costly["funding_cost"] > 0


def test_funding_that_eats_the_target_in_a_day_is_a_block():
    """This test needs no hold estimate: a contract whose settlements take
    half the target every day cannot be won by a trade that lingers."""
    # ultosc_1h_sl3tp3 targets 3%; 2% a day is two thirds of it
    fx = FX(rate=0.01, cycle_h=12)               # 0.02 = 2% a day
    got = at.edge_check("ultosc_1h_sl3tp3", "X_USDT", 5.0, fx=fx, side=1)
    assert got["verdict"] == "block"
    assert "funding alone costs" in got["reason"], got["reason"]
    assert "a DAY" in got["reason"]


def test_a_favourable_rate_does_not_rescue_a_bad_spread():
    """The credit rule, end to end: a wide spread still blocks even when the
    position would be paid to hold."""
    fx = FX(rate=-0.01, cycle_h=1, spread=0.05)
    got = at.edge_check("ultosc_1h_sl3tp3", "X_USDT", 5.0, fx=fx, side=1)
    assert got["verdict"] == "block"


def test_a_long_hold_with_unmeasurable_funding_is_refused():
    """Unknown is not ok when it is money. A 1d strategy spans settlements by
    definition, so funding it cannot measure is a cost nobody counted."""
    class Blind(FX):
        def funding_now(self, symbol):
            raise RuntimeError("venue down")

    # ONE HOUR is the threshold, because NGAS settles hourly. This list was
    # empty when the threshold was 8h — no strategy here holds that long —
    # so the guard was dead code and this assertion is what found it.
    long_enough = [k for k, s in at.STRATEGY_SPECS.items()
                   if s.get("bar_seconds", 0) >= at.FUNDING_UNKNOWN_HOLD_S]
    assert long_enough, "the threshold is above every strategy: dead code"
    got = at.edge_check(long_enough[0], "X_USDT", 5.0, fx=Blind(), side=1)
    assert got["verdict"] == "block"
    assert "cannot be measured" in got["reason"], got["reason"]


def test_a_short_hold_with_unmeasurable_funding_still_trades():
    """A 15m trade cannot span an 8-hour settlement, so refusing it would
    stop trading over a cost it will never pay."""
    class Blind(FX):
        def funding_now(self, symbol):
            raise RuntimeError("venue down")

    got = at.edge_check("willr14_15m_sl12tp12", "X_USDT", 5.0,
                        fx=Blind(), side=1)
    assert got["verdict"] in ("ok", "warn"), got["reason"]


# ---------------------------------------------------------------- capital
def test_a_trade_bigger_than_the_free_balance_is_refused():
    got = at.capital_check(50.0, fx=FX(equity=100.0, committed=80.0),
                           settings={})
    assert got["verdict"] == "block"
    assert "free to open" in got["reason"]


def test_total_exposure_has_a_ceiling():
    """One position per coin was the only cap; nothing stopped every coin
    holding one at once."""
    fx = FX(equity=1_000.0, committed=499.0)
    assert at.capital_check(0.5, fx=fx, settings={})["verdict"] == "ok"
    at._CAPITAL_CACHE.clear()
    got = at.capital_check(50.0, fx=FX(equity=1_000.0, committed=499.0),
                           settings={})
    assert got["verdict"] == "block"
    assert "ceiling" in got["reason"]


def test_the_ceiling_is_a_setting():
    fx = FX(equity=1_000.0, committed=600.0)
    assert at.capital_check(10.0, fx=fx,
                            settings={"max_exposure_fraction": 0.9})["verdict"] == "ok"


def test_an_unreadable_wallet_refuses():
    """The one case where trading on is the reckless choice."""
    got = at.capital_check(5.0, fx=FX(equity=None), settings={})
    assert got["verdict"] == "unknown"
    assert "could not be read" in got["reason"]


def test_the_wallet_is_read_once_for_a_burst_of_signals():
    fx = FX()
    for _ in range(30):
        at.capital_check(5.0, fx=fx, settings={})
    assert fx.asset_calls == 1


def test_the_operators_own_account_clears_a_five_dollar_trade():
    """153.61 USDT equity, nothing committed — the shape they run today must
    not be blocked by a guard meant for size."""
    got = at.capital_check(5.0, fx=FX(equity=153.61, committed=0.0),
                           settings={})
    assert got["verdict"] == "ok", got["reason"]


# --------------------------------------------------------------- the fill
def test_a_worse_fill_is_a_positive_cost_on_either_side():
    assert at.slippage_paid(100.0, 100.5, 1) == pytest.approx(0.005)
    assert at.slippage_paid(100.0, 99.5, -1) == pytest.approx(0.005)


def test_a_better_fill_is_reported_as_the_gain_it_is():
    assert at.slippage_paid(100.0, 99.5, 1) == pytest.approx(-0.005)


def test_a_missing_price_is_not_a_fill_cost():
    for a, c in ((0, 100.0), (100.0, 0), (None, 100.0)):
        assert at.slippage_paid(a or 0, c or 0, 1) == 0.0


def test_the_entry_records_what_the_fill_cost():
    import inspect

    src = inspect.getsource(at._process_slot)
    assert '"action": "fill_slippage"' in src, \
        "what was actually paid has to reach the ledger, or nobody can ever " \
        "check the gate's model against reality"
    assert "FILL WORSE THAN THE GATE MODELLED" in src
    assert "SLIPPAGE_ALERT_FRACTION" in src


def test_the_capital_gate_runs_before_the_order_and_only_live():
    import inspect

    src = inspect.getsource(at._process_slot)
    i = src.index("CAN THE ACCOUNT AFFORD IT?")
    j = src.index("vol = fx.contracts_for", i)
    frag = src[i:j]
    assert "if not dry:" in frag, "the demo book simulates strategy, not wallet"
    assert '"action": "capital_blocked"' in frag
    assert 'st["last_ts"]' not in frag, \
        "one coin's refusal must not eat the candle for the others"
    assert "continue" in frag


# ----------------------------------------- one bar close, five signals
def test_the_same_balance_cannot_be_spent_twice_in_one_cycle():
    """Found by the harddev loop before it shipped.

    Five signals firing on one bar close each read the same pre-trade wallet,
    so a ceiling that allows ONE position would have let all five through.
    The venue's `positionMargin` cannot close this: it lags the fill, so a
    zero-second cache would only turn one stale read into five.
    """
    at._CYCLE_COMMITTED["usdt"] = 0.0
    fx = FX(equity=100.0, committed=0.0)          # ceiling 50 USDT
    assert at.capital_check(40.0, fx=fx, settings={})["verdict"] == "ok"
    at._CYCLE_COMMITTED["usdt"] = 40.0            # the first order went out
    got = at.capital_check(40.0, fx=fx, settings={})
    assert got["verdict"] == "block", \
        "the second signal on this bar must see the first one's margin"
    at._CYCLE_COMMITTED["usdt"] = 0.0


def test_a_refused_order_gives_its_margin_back():
    import inspect

    src = inspect.getsource(at._process_slot)
    i = src.index("ORDER REFUSED")
    frag = src[max(0, i - 900):i]
    assert "_CYCLE_COMMITTED" in frag and "max(" in frag, \
        "an order the venue refused must not keep shrinking the ceiling"


def test_the_counter_is_wiped_with_the_rest_of_the_cycle():
    """Carrying it forward would count the same margin twice every cycle
    until nothing could trade."""
    import inspect

    src = inspect.getsource(at.run_cycle)
    assert '_CYCLE_COMMITTED["usdt"] = 0.0' in src


# ------------------------------------------------- the size it measures
def test_the_gate_measures_the_size_the_runner_will_actually_trade():
    """It read the book at the deepest martingale rung — eight times any real
    order — which was right until `staked_margin` went flat on Sep 11, 2026.
    A verdict measured at a size that cannot happen is a false label."""
    got = at.edge_check("ultosc_1h_sl3tp3", "X_USDT", 5.0, fx=FX(), side=1)
    assert got["notional_tested"] == pytest.approx(5.0 * at.LEVERAGE)
    assert got["notional_tested"] != pytest.approx(
        5.0 * at.LADDER[-1] * at.LEVERAGE)


def test_the_refusal_no_longer_names_a_ladder_rung():
    import inspect

    src = inspect.getsource(at.edge_check)
    assert "deepest ladder rung" not in src, \
        "the ladder has been backtest-only since Sep 11, 2026"


def test_an_order_the_venue_shrinks_is_counted_not_just_logged():
    import inspect

    src = inspect.getsource(at._process_slot)
    assert '"action": "size_capped"' in src
    for field in ("wanted_vol", "venue_max_vol", "sent_margin"):
        assert field in src, field


def test_a_fifteen_minute_trade_does_not_print_as_a_zero_hour_hold():
    """`f"{hold_s / 3600:.0f}h"` rendered 900 seconds as "a 0h hold", which
    beside a funding figure reads as no hold at all (label-must-match-data).
    Caught on the operator's own gate line, `Sep 15, 2026 9:45am`."""
    assert at._hold_label(900) == "15m"
    assert at._hold_label(1800) == "30m"
    assert at._hold_label(3600) == "1h"
    assert at._hold_label(14400) == "4h"
    assert "0h" not in at._hold_label(900)


def test_the_gate_line_names_the_hold_it_charged_for():
    got = at.edge_check("willr14_15m_sl12tp12", "X_USDT", 5.0,
                        fx=FX(rate=0.002, cycle_h=1), side=1)
    assert "15m hold" in got["reason"], got["reason"]


# ------------------------------------------------------ the liquidation wall
class FXLiq(FX):
    """A contract that publishes MEXC's real maintenance rate."""

    mmr = 0.005

    def contract_spec(self, symbol):
        return {"contractSize": 1, "takerFeeRate": self.fee,
                "maintenanceMarginRate": self.mmr}


def test_the_liquidation_distance_matches_the_venues_own_number():
    """MEXC's liquidatePrice for the operator's live PDDSTOCK position on
    `Sep 15, 2026`: entry 78.92, liq 75.30 — 4.59% away. The arithmetic,
    1/20 - 0.005, gives 4.50%; the rest is fees already accrued."""
    got = at.liquidation_distance("PDDSTOCK_USDT", fx=FXLiq(), leverage=20)
    assert got == pytest.approx(0.045)
    assert abs(got - (78.92 - 75.30) / 78.92) < 0.002


def test_a_stop_the_venue_would_liquidate_through_is_refused():
    """Twenty registry strategies carry a 4% stop. At 20x that leaves 0.5% of
    room, and losing the WHOLE margin is a different trade from losing 4% —
    one no backtest row ever measured."""
    wide = [k for k, s in at.STRATEGY_SPECS.items() if s.get("sl") == 0.04]
    assert wide, "no 4% stop in the registry to test with"
    got = at.edge_check(wide[0], "X_USDT", 5.0, fx=FXLiq(), side=1)
    assert got["verdict"] == "block"
    assert "of the way to liquidation" in got["reason"], got["reason"]
    assert "WHOLE margin" in got["reason"]


def test_the_stops_the_operator_actually_runs_are_clear_of_it():
    """The widest ARMED stop is 3.00% — 67% of the way. This guard must not
    stop today's trading to protect a future deploy."""
    for key in ("ultosc_1h_sl3tp3", "squeeze_1h_sl3tp3", "bb20_1h_sl25tp25"):
        got = at.edge_check(key, "X_USDT", 5.0, fx=FXLiq(), side=1)
        assert got["verdict"] in ("ok", "warn"), (key, got["reason"])


def test_an_unreadable_maintenance_rate_does_not_invent_safety():
    class NoRate(FX):
        def contract_spec(self, symbol):
            return {"contractSize": 1, "takerFeeRate": self.fee}

    assert at.liquidation_distance("X_USDT", fx=NoRate()) is None
    # ...and the gate falls back rather than blocking everything
    got = at.edge_check("ultosc_1h_sl3tp3", "X_USDT", 5.0, fx=NoRate(), side=1)
    assert got["verdict"] in ("ok", "warn")


# --------------------------------------- the wall moves while you hold
def _venue(liq, entry=100.0):
    return {"symbol": "X_USDT", "holdAvgPrice": entry, "liquidatePrice": liq}


def test_a_long_whose_stop_slipped_past_liquidation_is_called_out():
    """`liquidatePrice` MOVES: fees and funding eat the margin, so a stop that
    cleared the wall at entry can end up behind it. MEXC pushes the figure
    every few seconds and until Sep 15, 2026 nothing read it."""
    pos = {"side": 1, "entry": 100.0, "sl": 95.0, "strategy": "k"}
    got = at.liquidation_warning("X_USDT", pos, _venue(96.0))
    assert got and "PAST the venue's liquidation price" in got["why"]
    assert "whole margin" in got["why"]


def test_a_long_with_the_stop_nearer_than_the_wall_is_fine():
    pos = {"side": 1, "entry": 100.0, "sl": 97.0, "strategy": "k"}
    assert at.liquidation_warning("X_USDT", pos, _venue(96.0)) is None


def test_a_short_is_read_the_other_way_up_here_too():
    pos = {"side": -1, "entry": 100.0, "sl": 105.0, "strategy": "k"}
    assert at.liquidation_warning("X_USDT", pos, _venue(104.0)) is not None
    pos["sl"] = 103.0
    assert at.liquidation_warning("X_USDT", pos, _venue(104.0)) is None


def test_a_missing_liquidation_price_is_not_a_safe_position():
    """Unmeasured is not fine — it answers None and the caller says so,
    rather than this inventing a verdict."""
    pos = {"side": 1, "entry": 100.0, "sl": 95.0, "strategy": "k"}
    for bad in ({}, {"liquidatePrice": 0}, {"liquidatePrice": None}):
        assert at.liquidation_warning("X_USDT", pos, bad) is None


def test_the_warning_is_rate_limited_and_ledgered():
    import inspect

    src = inspect.getsource(at._process_slot)
    assert '"action": "liquidation_risk"' in src
    assert "_say_once(f\"liq-" in src, "a repeated alarm is a silence"
    assert "LIQUIDATION BEFORE STOP" in src


def test_the_watch_costs_no_extra_venue_call():
    """It reads the payload `live_gone` already fetched."""
    import inspect

    src = inspect.getsource(at._process_slot)
    i = src.index("_open = fx.open_positions(symbol)")
    j = src.index("liquidation_warning", i)
    assert "fx.open_positions" not in src[i + 10:j], \
        "the venue must not be asked twice for the same list"
