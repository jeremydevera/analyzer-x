"""Gate rows never share an id or a store with MEXC rows (spec D6, Oct 10, 2026).

The operator pastes ids between tabs and deploys by them. A Gate row of BTC
1h ote must never carry the id of the MEXC row of BTC 1h ote: the candles,
the costs and the trades are another exchange's. And a GitHub run measured on
one exchange must never land in the other exchange's store — the same rule
`res` already enforces between Backtest v1 and v2 (Sep 21, 2026), applied to
the exchange.
"""
import pytest

from tradingagents import backtest_report as br
from tradingagents import cloud_sweep as cs

ARGS = ("XPIN", "1h", "ote", 0.0, 3.0, 1.0, "flat")


def test_every_mexc_id_is_unchanged():
    assert br.row_code(*ARGS) == "LG9NSU4B"


def test_a_gate_row_has_its_own_id(monkeypatch):
    monkeypatch.setenv("TA_VENUE", "gate")
    gate_v1 = br.row_code(*ARGS)
    gate_v2 = br.row_code(*ARGS, res="1m")
    assert gate_v1 != "LG9NSU4B"
    assert len({gate_v1, gate_v2, "LG9NSU4B"}) == 3
    monkeypatch.setenv("TA_VENUE", "mexc")
    assert br.row_code(*ARGS) == "LG9NSU4B"


def test_the_exchange_can_be_named_explicitly():
    """A reader holding rows from a known exchange (the archive, a shard
    log) names it rather than trusting this process's setting."""
    assert br.row_code(*ARGS, venue="mexc") == "LG9NSU4B"
    assert br.row_code(*ARGS, venue="gate") != "LG9NSU4B"


def _row(**extra):
    return {"coin": "BTC", "tf": "1h", "last_ms": 1, **extra}


def test_a_gate_row_is_refused_by_a_mexc_store(monkeypatch):
    monkeypatch.setenv("TA_VENUE", "mexc")
    with pytest.raises(cs.WrongStore, match="gate.*MEXC|Gate.*mexc"):
        cs.land_rows("BTC", "1h", [_row(venue="gate")])


def test_an_old_row_with_no_exchange_is_mexc_and_refused_by_a_gate_store(monkeypatch):
    """Every shard before Oct 10, 2026 measured on MEXC and wrote no venue."""
    monkeypatch.setenv("TA_VENUE", "gate")
    with pytest.raises(cs.WrongStore, match="mexc"):
        cs.land_rows("BTC", "1h", [_row()])
    with pytest.raises(cs.WrongStore):
        cs.land_rows("BTC", "1h", [], marks=[_row(pair_done=True)])


def test_the_shard_stamps_the_exchange_on_rows_and_markers():
    src = open(".github/scripts/sweep_shard.py", encoding="utf-8").read()
    assert src.count("**VENUE_FIELD") >= 3, \
        "every row and every pair_done marker carries the exchange"
