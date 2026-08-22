"""Unit tests for the keyless PSE vendor (no network)."""

from unittest.mock import patch

import pytest

from tradingagents.dataflows import pse

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("raw,expected", [
    ("MER", "MER"), ("mer", "MER"), ("MER.PS", "MER"),
    ("mer.ph", "MER"), ("MER.PSE", "MER"), (" MER ", "MER"),
])
def test_normalize_symbol(raw, expected):
    assert pse.normalize_symbol(raw) == expected


def _fake_session(day_to_close):
    def _close_on(symbol, day):
        if day not in day_to_close:
            return None                      # weekend / holiday
        return day, day_to_close[day], 1000.0
    return _close_on


def test_fetch_history_skips_non_trading_days():
    closes = {"2026-07-27": 550.0, "2026-07-28": 552.0, "2026-07-30": 480.0}
    with patch.object(pse, "_close_on", side_effect=_fake_session(closes)), \
         patch.object(pse, "latest_quote", return_value={}):
        frame = pse.fetch_history("MER", "2026-07-27", "2026-07-31")
    assert list(frame["Date"].dt.strftime("%Y-%m-%d")) == sorted(closes)
    # close-only feed: OHLC all equal the close when no live quote is available
    assert frame["Open"].tolist() == frame["Close"].tolist()


def test_latest_session_gets_real_ohlc_from_the_quote():
    closes = {"2026-07-30": 480.0, "2026-07-31": 480.0}
    quote = {"open": 474.0, "high": 488.0, "low": 451.2,
             "close": 483.6, "volume": 411420.0}
    with patch.object(pse, "_close_on", side_effect=_fake_session(closes)), \
         patch.object(pse, "latest_quote", return_value=quote):
        frame = pse.fetch_history("MER", "2026-07-30", "2026-07-31")
    last = frame.iloc[-1]
    assert (last["Open"], last["High"], last["Low"]) == (474.0, 488.0, 451.2)
    assert last["Close"] == 483.6
    # earlier bars keep the close-only shape
    assert frame.iloc[0]["High"] == frame.iloc[0]["Close"]


def test_fetch_history_raises_when_no_sessions():
    with patch.object(pse, "_close_on", return_value=None), \
         patch.object(pse, "latest_quote", return_value={}):
        with pytest.raises(pse.PseUnavailable, match="No PSE sessions"):
            pse.fetch_history("NOPE", "2026-07-27", "2026-07-31")


def test_fetch_history_rejects_a_reversed_range():
    with pytest.raises(pse.PseUnavailable, match="precedes"):
        pse.fetch_history("MER", "2026-07-31", "2026-07-01")


def test_stock_data_csv_declares_the_ohlc_limitation():
    closes = {"2026-07-30": 480.0}
    with patch.object(pse, "_close_on", side_effect=_fake_session(closes)), \
         patch.object(pse, "latest_quote", return_value={}):
        csv = pse.get_pse_stock_data("MER", "2026-07-30", "2026-07-30")
    assert "Philippine Stock Exchange, PHP" in csv
    assert "CLOSE and VOLUME only" in csv          # honest about the gap
    assert "2026-07-30,480.0" in csv


def test_indicators_compute_off_closes():
    closes = {f"2026-06-{d:02d}": 500.0 + d for d in range(1, 29)}
    with patch.object(pse, "_close_on", side_effect=_fake_session(closes)), \
         patch.object(pse, "latest_quote", return_value={}):
        out = pse.get_pse_indicators("MER", "close_10_sma", "2026-06-28", 3)
    assert "close_10_sma for MER (PSE, PHP)" in out
    assert "2026-06-28:" in out


def test_vendor_is_registered():
    from tradingagents.dataflows import interface
    assert "pse" in interface.VENDOR_LIST
    assert interface.VENDOR_METHODS["get_stock_data"]["pse"] is pse.get_pse_stock_data
    assert interface.VENDOR_METHODS["get_indicators"]["pse"] is pse.get_pse_indicators


def test_pse_tickers_route_to_the_pse_vendor():
    import tickers as t
    assert t.is_pse("MER") and t.is_pse("mer.ps")
    assert not t.is_pse("AAPL") and not t.is_pse("MAEOY")
    assert t.pse_vendor_overrides()["core_stock_apis"] == "pse"
