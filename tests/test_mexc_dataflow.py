"""Unit tests for the MEXC dataflow (no network — every HTTP call is patched)."""

from unittest.mock import patch

import pytest

from tradingagents.dataflows import mexc
from tradingagents.dataflows.symbol_utils import from_mexc_symbol, to_mexc_symbol

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_host_cache():
    mexc.reset_host_cache()
    yield
    mexc.reset_host_cache()


def test_resolve_host_prefers_first_reachable():
    with patch.object(mexc, "_raw_get", return_value={}) as raw:
        assert mexc.resolve_host() == "api.mexc.fm"
    assert raw.call_count == 1


def test_resolve_host_falls_through_tls_block_to_next_host():
    """A blocked host fails TLS verification; the next candidate must be tried."""
    def fake(host, path, params=None, timeout=None):
        if host == "api.mexc.fm":
            raise mexc.MexcHostUnavailable("TLS: CERTIFICATE_VERIFY_FAILED")
        return {}

    with patch.object(mexc, "_raw_get", side_effect=fake):
        assert mexc.resolve_host() == "api.mexc.co"


def test_resolve_host_raises_when_all_hosts_blocked():
    with patch.object(mexc, "_raw_get", side_effect=mexc.MexcHostUnavailable("blocked")):
        with pytest.raises(mexc.MexcUnavailable) as exc:
            mexc.resolve_host()
    assert "MEXC_API_HOST" in str(exc.value)


def test_env_override_is_the_only_candidate(monkeypatch):
    monkeypatch.setenv("MEXC_API_HOST", "mexc.internal")
    with patch.object(mexc, "_raw_get", return_value={}) as raw:
        assert mexc.resolve_host() == "mexc.internal"
    assert raw.call_args[0][0] == "mexc.internal"


def test_resolved_host_is_cached_across_calls():
    with patch.object(mexc, "_raw_get", return_value={}) as raw:
        mexc.resolve_host()
        mexc.resolve_host()
    assert raw.call_count == 1


# --- Symbol mapping --------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("CATE-USD", "CATEUSDT"),
    ("CATE-USDT", "CATEUSDT"),
    ("CATEUSDT", "CATEUSDT"),
    ("cate-usd", "CATEUSDT"),
    ("CATE", "CATEUSDT"),
    ("CATE-USDC", "CATEUSDC"),
])
def test_to_mexc_symbol(raw, expected):
    assert to_mexc_symbol(raw) == expected


@pytest.mark.parametrize("pair,expected", [
    ("CATEUSDT", "CATE-USD"),
    ("BTCUSDT", "BTC-USD"),
    ("WEIRD", "WEIRD"),
])
def test_from_mexc_symbol(pair, expected):
    assert from_mexc_symbol(pair) == expected


def test_mexc_symbol_round_trip():
    assert to_mexc_symbol(from_mexc_symbol("CATEUSDT")) == "CATEUSDT"
