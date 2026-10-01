"""A room's screen answers in about a second, not 45 (RCA-2026-10-01-D).

Oct 01, 2026: "when i click strategy rooms why is it loading slow?". The
open-positions read for #4FC03172 measured 44.9 s: 84 MEXC calls one after
another — 41 prices (25.4 s), 116 contract details (17.6 s) and fees. One
ticker list and one contract list answer all of them.
"""
from __future__ import annotations

import pytest

from tradingagents.dataflows import mexc_futures as fx


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(fx, "_PRICES", {"at": 0.0, "px": {}})
    monkeypatch.setattr(fx, "_SPEC_CACHE", {})
    monkeypatch.setattr(fx, "_SPEC_BULK_AT", [0.0])


def test_every_price_comes_from_one_call_shared_for_three_seconds(monkeypatch):
    calls = []

    def fake(url):
        calls.append(url)
        return {"data": [{"symbol": "VUG_USDT", "lastPrice": 87.455},
                         {"symbol": "KII_USDT", "lastPrice": "0.0123"},
                         {"symbol": "DEAD_USDT", "lastPrice": 0},          # never a price
                         {"symbol": "ODD_USDT", "lastPrice": None}]}
    monkeypatch.setattr(fx, "_get_public", fake)
    t = [1000.0]
    monkeypatch.setattr(fx.time, "time", lambda: t[0])
    px = fx.last_prices()
    assert px == {"VUG_USDT": 87.455, "KII_USDT": 0.0123}
    assert calls == [f"{fx.BASE}/api/v1/contract/ticker"], "no symbol: every contract at once"
    t[0] += 2.0
    fx.last_prices()
    assert len(calls) == 1, "shared for 3 s"
    t[0] += 1.5
    fx.last_prices()
    assert len(calls) == 2


def test_an_unreadable_list_is_empty_and_never_a_zero(monkeypatch):
    monkeypatch.setattr(fx, "_get_public", lambda url: {"code": 510, "msg": "Requests are too frequent"})
    assert fx.last_prices() == {}

    def boom(url):
        raise fx.MexcFuturesError("cut")
    monkeypatch.setattr(fx, "_get_public", boom)
    assert fx.last_prices() == {}


def test_every_contract_detail_comes_from_one_call_for_the_hour(monkeypatch):
    calls = []

    def fake(url):
        calls.append(url)
        if "symbol=" in url:
            return {"data": {"symbol": "NEW_USDT", "contractSize": 1}}
        return {"data": [{"symbol": f"C{i}_USDT", "contractSize": 0.1 * i} for i in range(1, 42)]}
    monkeypatch.setattr(fx, "_get_public", fake)
    for i in range(1, 42):
        assert fx.contract_spec(f"C{i}_USDT")["contractSize"] == pytest.approx(0.1 * i)
    assert calls == [f"{fx.BASE}/api/v1/contract/detail"], "41 coins, one call"
    assert fx.contract_spec("NEW_USDT")["contractSize"] == 1, "a coin the list lacks is still read"
    assert len(calls) == 2


def test_the_positions_screen_reads_the_shared_list():
    src = open("tradingagents/api.py", encoding="utf-8").read()
    route = src[src.index("def trade_positions"):]
    route = route[:route.index("def contract_size")]
    assert "_all = fx.last_prices()" in route
    assert "if symbol in _all:" in route
