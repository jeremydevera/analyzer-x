"""The runner's cost check on Gate (phase 2, Oct 10, 2026).

`taker_fee` floors every contract at 0.08% a side. That floor was MEASURED on
MEXC: 44 of 48 of the operator's real MEXC fills paid 0.080% while MEXC's
own spec said 0.04% or 0 (Sep 23, 2026). It is MEXC's evidence, not Gate's.
Gate publishes 0.075% taker on all 1,027 contracts, and no Gate fill exists
yet to say otherwise — so under Gate the spec is believed, and a contract
whose spec reads 0 is charged Gate's published 0.075%, never 0.
"""
import pytest

from tradingagents import auto_trader as at


class FakeFx:
    def __init__(self, rate):
        self.rate = rate

    def contract_spec(self, symbol):
        return {"takerFeeRate": self.rate}


def test_under_gate_the_published_fee_is_charged(monkeypatch):
    monkeypatch.setenv("TA_VENUE", "gate")
    assert at.taker_fee("BTC_USDT", fx=FakeFx(0.00075)) == pytest.approx(0.00075)
    assert at.taker_fee("AAPL_USDT", fx=FakeFx(0)) == pytest.approx(0.00075), \
        "a spec of 0 is not a free trade"
    assert at.taker_fee("X_USDT", fx=FakeFx(0.001)) == pytest.approx(0.001), \
        "a higher spec is still believed"


def test_under_mexc_the_measured_floor_stays():
    assert at.taker_fee("ALICE_USDT", fx=FakeFx(0.0004)) == pytest.approx(0.0008)
    assert at.taker_fee("X_USDT", fx=FakeFx(0.001)) == pytest.approx(0.001)


def test_the_floor_names_where_it_came_from():
    assert at.fee_floor("mexc") == pytest.approx(0.0008)
    assert at.fee_floor("gate") == pytest.approx(0.00075)
