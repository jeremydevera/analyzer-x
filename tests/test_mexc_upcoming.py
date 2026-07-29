"""Announced-but-not-yet-trading listings.

MEXC publishes a listing before it trades: the pair appears in exchangeInfo with
``status: "2"`` and no ``firstOpenTime``, and the web market endpoint carries the
scheduled open time. Verified live — GRVT and NATG were visible 12 and 15 hours
before their open, while every tradable pair carried ``status: "1"``.
"""

from unittest.mock import patch

import pytest

from tradingagents.dataflows import mexc

pytestmark = pytest.mark.unit

_NOW_MS = 1785000000000
_HOUR_MS = 3_600_000


def _symbol(sym, status="1", spot=True, name="Coin", contract=""):
    return {"symbol": sym, "baseAsset": sym.replace("USDT", ""), "quoteAsset": "USDT",
            "status": status, "isSpotTradingAllowed": spot, "fullName": name,
            "contractAddress": contract}


_INFO = {"symbols": [
    _symbol("BTCUSDT"),
    _symbol("GRVTUSDT", status="2", spot=False, name="Grvt"),
    _symbol("NATGUSDT", status="2", spot=False, name="NatGold Digital"),
    # Suspended, not upcoming: status 1 with spot disabled. 102 pairs look like
    # this and must not be announced as coming soon.
    _symbol("DEADUSDT", status="1", spot=False, name="Delisted Thing"),
]}


def test_pending_listings_are_the_status_two_pairs():
    with patch.object(mexc, "_get", return_value=_INFO):
        rows = mexc.fetch_pending_listings()
    assert sorted(r["symbol"] for r in rows) == ["GRVTUSDT", "NATGUSDT"]


def test_suspended_pairs_are_not_treated_as_upcoming():
    with patch.object(mexc, "_get", return_value=_INFO):
        rows = mexc.fetch_pending_listings()
    assert all(r["symbol"] != "DEADUSDT" for r in rows)


def test_pending_rows_carry_name_and_base():
    with patch.object(mexc, "_get", return_value=_INFO):
        rows = {r["symbol"]: r for r in mexc.fetch_pending_listings()}
    assert rows["NATGUSDT"]["name"] == "NatGold Digital"
    assert rows["NATGUSDT"]["base"] == "NATG"


# --- scheduled open times -------------------------------------------------

_WEB = {"data": {"USDT": [
    {"currency": "GRVT", "openTime": "2026-07-30T14:00:00.000+00:00", "type": "NEW"},
    {"currency": "NATG", "openTime": "2026-07-30T11:00:00.000+00:00", "type": "NEW"},
    {"currency": "BTC", "openTime": "2017-09-30T00:00:00.000+00:00", "type": "MAIN"},
]}}


def test_scheduled_times_are_parsed_to_epoch_ms():
    with patch.object(mexc, "_web_get", return_value=_WEB):
        times = mexc.fetch_scheduled_open_times()
    assert times["NATG"] == 1785409200000        # 2026-07-30 11:00 UTC
    assert times["GRVT"] == 1785420000000        # 2026-07-30 14:00 UTC


def test_scheduled_times_tolerate_a_broken_stamp():
    with patch.object(mexc, "_web_get",
                      return_value={"data": {"USDT": [{"currency": "X",
                                                       "openTime": "not-a-date"}]}}):
        assert mexc.fetch_scheduled_open_times() == {}


def test_scheduled_times_tolerate_an_unexpected_shape():
    with patch.object(mexc, "_web_get", return_value=["nope"]):
        assert mexc.fetch_scheduled_open_times() == {}


# --- combined view --------------------------------------------------------


def test_upcoming_listings_include_the_open_time_and_countdown():
    with patch.object(mexc, "_get", return_value=_INFO), \
         patch.object(mexc, "_web_get", return_value=_WEB):
        rows = mexc.upcoming_listings(now_ms=1785400000000)   # 2026-07-30 08:26 UTC
    by_symbol = {r["symbol"]: r for r in rows}
    assert by_symbol["NATGUSDT"]["open_ms"] == 1785409200000
    assert by_symbol["NATGUSDT"]["hours_until"] == pytest.approx(2.56, abs=0.05)
    assert by_symbol["GRVTUSDT"]["hours_until"] == pytest.approx(5.56, abs=0.05)


def test_upcoming_listings_are_ordered_soonest_first():
    with patch.object(mexc, "_get", return_value=_INFO), \
         patch.object(mexc, "_web_get", return_value=_WEB):
        rows = mexc.upcoming_listings(now_ms=1785400000000)
    assert [r["symbol"] for r in rows] == ["NATGUSDT", "GRVTUSDT"]


def test_a_pending_coin_with_no_published_time_is_still_reported():
    """Knowing a listing is coming matters even without the hour."""
    with patch.object(mexc, "_get", return_value=_INFO), \
         patch.object(mexc, "_web_get", return_value={"data": {"USDT": []}}):
        rows = mexc.upcoming_listings(now_ms=_NOW_MS)
    assert len(rows) == 2
    assert all(r["open_ms"] is None and r["hours_until"] is None for r in rows)


def test_the_web_endpoint_is_skipped_when_nothing_is_pending():
    """It is a 4 MB payload; no reason to pull it when there is no schedule to read."""
    quiet = {"symbols": [_symbol("BTCUSDT")]}
    with patch.object(mexc, "_get", return_value=quiet), \
         patch.object(mexc, "_web_get") as web:
        assert mexc.upcoming_listings(now_ms=_NOW_MS) == []
    assert not web.called


def test_a_failed_schedule_lookup_still_reports_the_pending_coins():
    with patch.object(mexc, "_get", return_value=_INFO), \
         patch.object(mexc, "_web_get", side_effect=mexc.MexcHostUnavailable("blocked")):
        rows = mexc.upcoming_listings(now_ms=_NOW_MS)
    assert sorted(r["symbol"] for r in rows) == ["GRVTUSDT", "NATGUSDT"]
    assert all(r["open_ms"] is None for r in rows)


def test_an_already_open_schedule_is_not_reported_as_upcoming():
    """Between the open time and the exchange flipping status, skip it."""
    info = {"symbols": [_symbol("GRVTUSDT", status="2", spot=False, name="Grvt")]}
    with patch.object(mexc, "_get", return_value=info), \
         patch.object(mexc, "_web_get", return_value=_WEB):
        rows = mexc.upcoming_listings(now_ms=1785420000000 + _HOUR_MS)
    assert rows == []
