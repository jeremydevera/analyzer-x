"""The verified-snapshot path must honor the configured price vendor.

get_stock_data and get_indicators route through VENDOR_METHODS, but the
verification snapshot needs a DataFrame rather than a formatted string. It used
to call load_ohlcv (yfinance) unconditionally, which hard-failed any run whose
prices come from elsewhere — a MEXC-listed coin Yahoo has never heard of.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.dataflows import market_data_validator as mdv
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import NoMarketDataError

pytestmark = pytest.mark.unit


def _frame(close=1.0):
    return pd.DataFrame({
        "Date": pd.to_datetime(["2026-07-27", "2026-07-28", "2026-07-29"]),
        "Open": [close] * 3, "High": [close] * 3, "Low": [close] * 3,
        "Close": [close] * 3, "Volume": [100.0] * 3,
    })


@pytest.fixture(autouse=True)
def _restore_vendor():
    yield
    set_config({"data_vendors": {"core_stock_apis": "yfinance"}})


def test_default_config_still_uses_yfinance():
    set_config({"data_vendors": {"core_stock_apis": "yfinance"}})
    with patch.object(mdv, "load_ohlcv", return_value=_frame(2.0)) as yf:
        df = mdv._load_frame("AAPL", "2026-07-29")
    assert yf.called
    assert df["Close"].iloc[-1] == 2.0


def test_mexc_vendor_loads_frames_from_mexc():
    set_config({"data_vendors": {"core_stock_apis": "mexc"}})
    with patch("tradingagents.dataflows.mexc.get_mexc_ohlcv",
               return_value=_frame(3.0)) as mx, \
         patch.object(mdv, "load_ohlcv") as yf:
        df = mdv._load_frame("AEONUSDT", "2026-07-29")
    assert mx.called
    assert not yf.called
    assert df["Close"].iloc[-1] == 3.0


def test_vendor_chain_falls_through_on_no_data():
    set_config({"data_vendors": {"core_stock_apis": "mexc,yfinance"}})
    with patch("tradingagents.dataflows.mexc.get_mexc_ohlcv",
               side_effect=NoMarketDataError("X", "XUSDT", "no candles")), \
         patch.object(mdv, "load_ohlcv", return_value=_frame(4.0)) as yf:
        df = mdv._load_frame("X", "2026-07-29")
    assert yf.called
    assert df["Close"].iloc[-1] == 4.0


def test_last_no_data_error_propagates_when_no_vendor_can_serve():
    set_config({"data_vendors": {"core_stock_apis": "mexc"}})
    with patch("tradingagents.dataflows.mexc.get_mexc_ohlcv",
               side_effect=NoMarketDataError("X", "XUSDT", "no candles")):
        with pytest.raises(NoMarketDataError):
            mdv._load_frame("X", "2026-07-29")


def test_vendor_without_a_frame_loader_keeps_the_yfinance_behavior():
    """alpha_vantage has no frame loader; the snapshot behaves as it always did."""
    set_config({"data_vendors": {"core_stock_apis": "alpha_vantage"}})
    with patch.object(mdv, "load_ohlcv", return_value=_frame(5.0)) as yf:
        df = mdv._load_frame("AAPL", "2026-07-29")
    assert yf.called
    assert df["Close"].iloc[-1] == 5.0


def test_snapshot_builds_end_to_end_for_a_mexc_coin():
    set_config({"data_vendors": {"core_stock_apis": "mexc"}})
    with patch("tradingagents.dataflows.mexc.get_mexc_ohlcv", return_value=_frame(1.5)):
        out = mdv.build_verified_market_snapshot("AEONUSDT", "2026-07-29")
    assert "AEONUSDT" in out
    assert "2026-07-29" in out
