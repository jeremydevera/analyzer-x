"""The fourteen position columns. Restored twice now — 2026-08-20 in Streamlit
after a five-column trim, and 2026-08-21 in React after the same trim. These
tests are what makes a third trim fail loudly.
"""

import pytest

from tradingagents import positions_view as pv


def _deps(price=110.0, size=1.0, fee=0.0004):
    return {"last_price": lambda s: price, "contract_size": lambda s: size,
            "taker_fee": lambda s: fee, "leverage": 20}


def _state(**over):
    pos = {"dry": False, "side": 1, "entry": 100.0, "tp": 110.0, "sl": 95.0,
           "margin": 5.0, "vol": 1.0, "strategy": "mom6_1h_g",
           "opened_at": 1_787_000_000, "bracket": True}
    pos.update(over)
    return {"APEX_USDT": {"position": pos}}


def test_every_column_is_present_on_every_row():
    rows = pv.build_rows(state=_state(), exchange_positions=[], stats={},
                         dry=False, now=1_787_003_600, **_deps())
    r = rows[0]
    for field in ("coin", "side", "opened", "held", "entry", "margin",
                  "unrealized", "tp_value", "sl_value", "wins", "losses",
                  "trades", "bracket", "progress_pct", "progress_to",
                  "notional", "total"):
        assert field in r, f"the {field} column vanished again"


def test_barrier_dollars_are_net_of_the_round_trip_fee():
    """The percent is on the notional; the dollars are what lands in the
    wallet. XAUT's 0.001 contract size once overstated notional 1000x."""
    v = pv.barrier_value(100.0, 110.0, notional=100.0, fee=0.001, win=True)
    assert v == {"pct": 10.0, "usd": 9.8}          # 10.00 gross - 0.20 costs
    l = pv.barrier_value(100.0, 95.0, notional=100.0, fee=0.001, win=False)
    assert l == {"pct": 5.0, "usd": -5.2}          # loss PLUS costs


def test_contract_size_is_honoured_in_the_dollar_figures():
    small = pv.build_rows(state=_state(), exchange_positions=[], stats={},
                          dry=False, **_deps(size=0.001))
    big = pv.build_rows(state=_state(), exchange_positions=[], stats={},
                        dry=False, **_deps(size=1.0))
    assert small[0]["tp_value"]["usd"] * 1000 == pytest.approx(
        big[0]["tp_value"]["usd"], rel=0.01)


def test_progress_measures_toward_whichever_barrier_price_moved_to():
    assert pv.progress(100, 110, 95, 105, 1) == (50.0, "TP")
    assert pv.progress(100, 110, 95, 97.5, 1) == (50.0, "SL")
    assert pv.progress(100, 110, 95, 100, 1) == (0.0, "TP")
    assert pv.progress(100, None, 95, 105, 1) is None


def test_progress_for_a_short_reads_the_other_way():
    # short from 100: price DOWN is toward the target
    assert pv.progress(100, 90, 105, 95, -1) == (50.0, "TP")
    assert pv.progress(100, 90, 105, 102.5, -1) == (50.0, "SL")


def test_a_rejected_bracket_shouts_and_a_resting_one_stays_quiet():
    ok = pv.build_rows(state=_state(bracket=True), exchange_positions=[],
                       stats={}, dry=False, **_deps())
    assert ok[0]["bracket"] == ""
    bad = pv.build_rows(state=_state(bracket=False), exchange_positions=[],
                        stats={}, dry=False, **_deps())
    assert bad[0]["bracket"] == "NO STOP — RETRYING"


def test_held_and_opened_use_the_operators_own_formats():
    rows = pv.build_rows(state=_state(), exchange_positions=[], stats={},
                         dry=False, now=1_787_000_000 + 3600 * 26, **_deps())
    assert rows[0]["held"] == "1d 2h"
    assert "," in rows[0]["opened"] and ":" in rows[0]["opened"]
    assert "08-" not in rows[0]["opened"], "the compact stamp was rejected"


def test_the_exchange_overrides_the_local_book_for_real_money():
    rows = pv.build_rows(
        state=_state(), stats={},
        exchange_positions=[{"symbol": "APEX_USDT", "holdVol": 3.0,
                             "holdAvgPrice": 101.0, "im": 7.5,
                             "unRealizedPnl": 1.234}],
        dry=False, **_deps())
    r = rows[0]
    assert r["entry"] == 101.0 and r["vol"] == 3.0
    assert r["margin"] == 7.5 and r["unrealized"] == 1.23


def test_an_exchange_position_the_bot_does_not_track_is_still_shown():
    rows = pv.build_rows(state={}, stats={}, dry=False,
                         exchange_positions=[{"symbol": "GHOST_USDT",
                                              "positionType": 2,
                                              "holdVol": 1.0,
                                              "holdAvgPrice": 5.0,
                                              "unRealizedPnl": -0.5}],
                         **_deps())
    assert rows[0]["strategy"] == "(not the bot's)" and rows[0]["side"] == "SHORT"


def test_paper_positions_price_themselves_and_never_hit_the_exchange():
    st = _state(dry=True)
    st["APEX_USDT#paper"] = st.pop("APEX_USDT")
    rows = pv.build_rows(state=st, exchange_positions=[], stats={}, dry=True,
                         **_deps(price=110.0))
    # +10% on a 5 USDT margin at 20x
    assert rows[0]["unrealized"] == 10.0 and rows[0]["coin"] == "APEX"


def test_lifetime_record_travels_with_the_row():
    rows = pv.build_rows(state=_state(), exchange_positions=[], dry=False,
                         stats={"APEX_USDT": {"pnl": -3.5, "wins": 2,
                                              "losses": 7, "trades": 9}},
                         **_deps())
    r = rows[0]
    assert (r["wins"], r["losses"], r["trades"]) == (2, 7, 9)
    # a real-money row takes its unrealized from the EXCHANGE, so with no
    # exchange read it is None and the total is the closed figure alone
    assert r["unrealized"] is None and r["total"] == -3.5
