"""Which exchange the app trades, and what kind of thing a coin is.

Operator, Oct 10, 2026: "okay switch to gate from now on, this means every
logic in my app will be gate instead of mexc". ONE place names the exchange
(`tradingagents/venue.py`); spec D1 and D5 in
docs/superpowers/specs/2026-10-10-switch-to-gate-design.md.
"""
import json

import pytest

from tradingagents import venue


@pytest.fixture
def no_env(monkeypatch, tmp_path):
    monkeypatch.delenv("TA_VENUE", raising=False)
    monkeypatch.setattr(venue, "VENUE_FILE", tmp_path / "venue.json")
    return tmp_path / "venue.json"


def test_with_nothing_written_the_app_stays_on_mexc(no_env):
    """A restart before the cutover must never flip production: the MEXC
    data still sits in every folder until the cutover moves it aside."""
    assert venue.current() == "mexc"
    assert venue.name() == "MEXC"


def test_the_file_written_by_the_cutover_switches_it(no_env):
    no_env.write_text(json.dumps({"venue": "gate", "since": 1791612000}))
    assert venue.current() == "gate"
    assert venue.name() == "Gate"


def test_the_environment_wins_over_the_file(no_env, monkeypatch):
    """GitHub's machines have no file; their workflows set TA_VENUE."""
    no_env.write_text(json.dumps({"venue": "mexc"}))
    monkeypatch.setenv("TA_VENUE", "gate")
    assert venue.current() == "gate"


def test_an_unknown_exchange_is_refused_by_name(no_env, monkeypatch):
    monkeypatch.setenv("TA_VENUE", "okx")
    with pytest.raises(ValueError, match="okx"):
        venue.current()


def test_a_broken_file_is_not_silently_mexc(no_env):
    """Half a file is not an answer: the app would trade one exchange's
    prices against another exchange's store."""
    no_env.write_text("{not json")
    with pytest.raises(ValueError, match="venue.json"):
        venue.current()


def test_set_current_writes_the_file_the_cutover_relies_on(no_env):
    venue.set_current("gate")
    assert json.loads(no_env.read_text())["venue"] == "gate"
    assert venue.current() == "gate"


def test_tests_run_pinned_to_mexc():
    """conftest pins every test to MEXC unless it says otherwise, so no test
    reads the operator's own venue.json."""
    assert venue.current() == "mexc"


def test_under_mexc_a_stock_is_named_stock(no_env):
    assert venue.kind("GPNSTOCK_USDT") == "stocks"
    assert venue.kind("BTC_USDT") == "crypto"
    assert venue.is_stock_like("GPNSTOCK_USDT")


def test_under_gate_a_stock_is_what_gate_lists_it_as(no_env, monkeypatch):
    """Gate names stocks by ticker (AAPL_USDT), so the name says nothing:
    the contract list's `contract_type` decides (D5)."""
    from tradingagents.dataflows import gate_futures as gf

    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.setattr(gf, "contract_types", lambda: {
        "AAPL_USDT": "stocks", "BTC_USDT": "crypto", "SPX500_USDT": "indices",
        "XAU_USDT": "metals"})
    assert venue.kind("AAPL_USDT") == "stocks"
    assert venue.kind("BTC_USDT") == "crypto"
    assert venue.kind("SPX500_USDT") == "indices"
    assert venue.is_stock_like("AAPL_USDT")
    assert not venue.is_stock_like("XAU_USDT")
    assert venue.stock_symbols() == ["AAPL_USDT"]
    # a coin Gate does not list is named so, never guessed into a kind
    assert venue.kind("GPNSTOCK_USDT") == "unlisted"
    assert not venue.is_stock_like("GPNSTOCK_USDT")
