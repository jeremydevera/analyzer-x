"""Live MEXC checks. Network-bound, so they are marked integration and are
deselected from a normal unit run — a module-level unit mark would drag a
two-minute exchange sweep into every fast test run.
"""

import pytest

from tradingagents.dataflows import mexc

pytestmark = pytest.mark.integration

def test_live_host_resolves():
    assert mexc.resolve_host() in mexc.DEFAULT_HOSTS


def test_live_symbol_universe_is_large():
    rows = mexc.fetch_usdt_symbols()
    assert len(rows) > 500
    assert all(r["symbol"].endswith("USDT") for r in rows)


def test_live_mexc_stock_data_parses_for_a_known_pair():
    out = mexc.get_mexc_stock_data("BTC-USD", "2026-07-01", "2026-07-29")
    assert "# MEXC spot data for BTCUSDT" in out
    assert "Date,Open,High,Low,Close,Volume" in out


def test_live_indicators_compute_for_a_known_pair():
    out = mexc.get_mexc_indicators("BTC-USD", "rsi", "2026-07-29", 5)
    assert "## rsi values" in out


def test_live_screen_returns_plausible_new_coins():
    """Full sweep — slow (~2 min cold) and rate-limit sensitive."""
    result = mexc.screen_new_listings(min_quote_volume=0.0)
    assert result.scanned > 500
    for coin in result.coins:
        assert 0 <= coin.age_days <= mexc.WINDOW_DAYS
        assert coin.symbol.endswith("USDT")
