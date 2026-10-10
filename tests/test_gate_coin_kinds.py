"""What a coin IS, under Gate (spec D5, Oct 10, 2026).

MEXC named every tokenized stock `...STOCK_USDT`, so four places read the
name: the daytime rule, room_stats, the Stored strategies crypto/stocks
filter and the "only here, not on OKX" list. Gate names stocks by ticker
(`AAPL_USDT`) and says what each contract is in its own list, so under Gate
the list decides. Under MEXC nothing changes.
"""
import pytest

from tradingagents import daytime_rule, room_stats, rows_index as ri, venue, venues
from tradingagents.dataflows import gate_futures as gf

KINDS = {"AAPL_USDT": "stocks", "VUG_USDT": "stocks", "BTC_USDT": "crypto",
         "SOL_USDT": "crypto", "SPX500_USDT": "indices", "XAU_USDT": "metals"}


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.setattr(gf, "contract_types", lambda: dict(KINDS))
    monkeypatch.setattr(gf, "trading_symbols", lambda: sorted(KINDS))


def test_the_daytime_rule_reads_gates_list(gate):
    assert daytime_rule.is_stock("AAPL_USDT")
    assert daytime_rule.is_stock("AAPL")
    assert not daytime_rule.is_stock("BTC_USDT")
    assert not daytime_rule.is_stock("SPX500_USDT"), \
        "an index trades nearly round the clock"


def test_room_stats_reads_gates_list(gate):
    assert room_stats.is_stock("AAPL_USDT") and not room_stats.is_stock("SOL_USDT")
    assert room_stats.home_market("AAPL_USDT") == "New York"


def test_under_mexc_both_still_read_the_name():
    assert daytime_rule.is_stock("GPNSTOCK_USDT")
    assert not daytime_rule.is_stock("BTC_USDT")
    assert room_stats.is_stock("GPNSTOCK_USDT")


def test_the_stocks_filter_is_gates_stock_list(gate):
    where, args = ri._where(asset="stocks", order_owns_index=True)
    assert "+coin IN (" in where
    assert sorted(args) == ["AAPL", "VUG"], "rows carry the bare coin name"
    where, args = ri._where(asset="crypto", order_owns_index=True)
    assert sorted(args) == ["BTC", "SOL"]


def test_under_mexc_the_stocks_filter_reads_the_suffix():
    where, args = ri._where(asset="stocks")
    assert "coin LIKE ?" in where and args == ["%STOCK"]


def test_only_here_not_on_okx_lists_the_venue_it_trades(gate, monkeypatch, tmp_path):
    from tradingagents import market_sweep as msw

    monkeypatch.setattr(msw, "HOME", tmp_path)
    venues._MEM.clear()
    monkeypatch.setattr(venues, "_fetch_okx", lambda: ["BTC", "AAPL"])
    try:
        assert venues.venue_only() == ["SOL", "SPX500", "VUG", "XAU"]
        assert "gate" in venues.lists() and "mexc" not in venues.lists()
    finally:
        venues._MEM.clear()
