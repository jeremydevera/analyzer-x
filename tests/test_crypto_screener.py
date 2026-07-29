"""Unit tests for the New Crypto tab's pure helpers (no Streamlit runtime)."""

import importlib.util
import sys
from pathlib import Path

import pytest

from tradingagents.dataflows.mexc import NewCoin, ScreenResult

_PATH = Path(__file__).resolve().parents[1] / "crypto_screener.py"

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def screener():
    spec = importlib.util.spec_from_file_location("ta_crypto_screener", _PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ta_crypto_screener"] = mod
    spec.loader.exec_module(mod)
    return mod


def _coin(**over):
    base = dict(symbol="CATEUSDT", base="CATE", name="Catestein", contract="0xabc",
                listed_date="2026-07-20", age_days=9, price=0.0037841,
                change_pct=12.4321, quote_volume=140_981.74)
    base.update(over)
    return NewCoin(**base)


def test_crypto_analysts_exclude_fundamentals(screener):
    assert screener.CRYPTO_ANALYSTS == ("market", "social", "news")


def test_build_crypto_config_routes_prices_to_mexc(screener):
    base = {"data_vendors": {"core_stock_apis": "yfinance",
                             "technical_indicators": "yfinance",
                             "news_data": "yfinance"},
            "llm_provider": "openai", "deep_think_llm": "x", "quick_think_llm": "y",
            "max_debate_rounds": 9, "max_risk_discuss_rounds": 9}
    cfg = screener.build_crypto_config(
        base, provider="google", deep_model="gemini-3.1-flash-lite",
        quick_model="gemini-3.1-flash-lite", debate_rounds=1, risk_rounds=2)

    assert cfg["data_vendors"]["core_stock_apis"] == "mexc"
    assert cfg["data_vendors"]["technical_indicators"] == "mexc"
    assert cfg["data_vendors"]["news_data"] == "yfinance"   # news still Yahoo
    assert cfg["include_twitter"] is True
    assert cfg["llm_provider"] == "google"
    assert cfg["deep_think_llm"] == "gemini-3.1-flash-lite"
    assert cfg["max_debate_rounds"] == 1
    assert cfg["max_risk_discuss_rounds"] == 2


def test_build_crypto_config_does_not_mutate_the_caller(screener):
    """A later stock run in the same process must still route to yfinance."""
    base = {"data_vendors": {"core_stock_apis": "yfinance",
                             "technical_indicators": "yfinance"},
            "llm_provider": "openai", "deep_think_llm": "x", "quick_think_llm": "y",
            "max_debate_rounds": 1, "max_risk_discuss_rounds": 1}
    screener.build_crypto_config(base, provider="google", deep_model="m",
                                 quick_model="m", debate_rounds=1, risk_rounds=1)
    assert base["data_vendors"]["core_stock_apis"] == "yfinance"
    assert base.get("include_twitter") is None


def test_instrument_context_uses_mexc_metadata(screener):
    ctx = screener.coin_instrument_context(_coin())
    assert "CATE" in ctx and "Catestein" in ctx
    assert "0xabc" in ctx
    assert "2026-07-20" in ctx
    assert "crypto" in ctx.lower()


def test_instrument_context_omits_contract_when_absent(screener):
    ctx = screener.coin_instrument_context(_coin(contract=""))
    assert "Contract address" not in ctx


def test_verdict_key_is_symbol_and_date_scoped(screener):
    assert screener.verdict_key("CATEUSDT", "2026-07-29") == "verdict:CATEUSDT:2026-07-29"


@pytest.mark.parametrize("signal,expected", [
    ("BUY", "▲ BUY"), ("SELL", "▼ SELL"), ("HOLD", "■ HOLD"),
    ("buy", "▲ BUY"), ("", "—"), (None, "—"), ("garbage", "—"),
])
def test_verdict_label(screener, signal, expected):
    assert screener.verdict_label(signal) == expected


def test_row_cells_formats_price_volume_and_change(screener):
    cells = screener.row_cells(_coin())
    assert cells["symbol"] == "CATE"
    assert cells["name"] == "Catestein"
    assert cells["listed"] == "2026-07-20"
    assert cells["age"] == "9d"
    assert cells["price"] == "0.0037841"
    assert cells["change"] == "+12.43%"
    assert cells["volume"] == "$141.0k"


def test_row_cells_marks_negative_change_and_millions(screener):
    cells = screener.row_cells(_coin(price=1.5, change_pct=-6.1,
                                     quote_volume=2_400_000.0))
    assert cells["change"] == "-6.10%"
    assert cells["volume"] == "$2.4M"


def test_row_cells_handles_tiny_volume(screener):
    cells = screener.row_cells(_coin(quote_volume=812.0))
    assert cells["volume"] == "$812"


def test_status_caption_reports_cache_and_gaps(screener):
    res = ScreenResult(coins=[], scanned=1741, unresolved=12, hidden_by_volume=5,
                       fetched_at=0.0, from_cache=True, stale=True)
    caption = screener.status_caption(res)
    assert "1741" in caption
    assert "12" in caption          # unresolved symbols surfaced, not hidden
    assert "5" in caption           # volume-filtered count surfaced
    assert "stale" in caption.lower()


def test_status_caption_stays_quiet_when_nothing_is_wrong(screener):
    res = ScreenResult(coins=[], scanned=1741, unresolved=0, hidden_by_volume=0,
                       fetched_at=0.0, from_cache=False, stale=False)
    caption = screener.status_caption(res)
    assert "1741" in caption
    assert "could not be checked" not in caption
    assert "stale" not in caption.lower()
