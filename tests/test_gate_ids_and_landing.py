"""A strategy keeps ONE id on both exchanges; a run lands only in its own
exchange's store (spec D6, reversed Oct 13, 2026).

The move to Gate (Oct 10, 2026) hashed the exchange into every id, so every
strategy the operator knew got a new one: *"i dont understand why did you
changed the ids just because i switched to gate"*, then *"yes"* to taking the
exchange out, and *"just to be clear i dont need the mexc results anymore"*.
So BTC 1h trend50 SL 0.3 / TP 0.4 on Backtest v2 is #4EVLXP67 on Gate, the id
it had on MEXC. The STORES still never mix: a GitHub run measured on one
exchange never lands in the other's store — the rule `res` enforces between
Backtest v1 and v2 (Sep 21, 2026), applied to the exchange.
"""
import pytest

from tradingagents import backtest_report as br, cloud_sweep as cs

ARGS = ("XPIN", "1h", "ote", 0.0, 3.0, 1.0, "flat")


def test_every_mexc_id_is_unchanged():
    assert br.row_code(*ARGS) == "LG9NSU4B"


def test_a_gate_row_keeps_the_id_it_had_on_mexc(monkeypatch):
    monkeypatch.setenv("TA_VENUE", "gate")
    assert br.row_code(*ARGS) == "LG9NSU4B"
    assert br.row_code("BTC", "1h", "trend50", 0, 0.3, 0.4, "flat", res="1m") == "4EVLXP67"
    # v1 and v2 still never share one (`res`, Sep 17, 2026)
    assert br.row_code(*ARGS, res="1m") != "LG9NSU4B"


def test_an_id_has_no_exchange_in_it():
    """Nothing can hash the exchange back in: the argument is gone."""
    import inspect

    assert "venue" not in inspect.signature(br.row_code).parameters


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


def test_a_trade_has_one_strategy_id_on_both_exchanges(monkeypatch):
    """Oct 13, 2026 (RCA-2026-10-13-B): the practice history printed #68BZF2L9
    beside FASTSTOCK prank_15m_sl12tp15 trades made on MEXC (Oct 07-09, 2026)
    — the id hashed with TODAY's exchange. With no exchange in the id, the
    trade's strategy is #2WCGB7VB whichever exchange the app is on."""
    import inspect

    import tradingagents.auto_trader as at
    from tradingagents import api

    key = next(k for k, s in at.STRATEGY_SPECS.items() if s.get("interval"))
    monkeypatch.setenv("TA_VENUE", "mexc")
    on_mexc = api.row_id_for(key, "FASTSTOCK_USDT", {})
    monkeypatch.setenv("TA_VENUE", "gate")
    assert api.row_id_for(key, "FASTSTOCK_USDT", {}) == on_mexc
    assert "venue" not in inspect.signature(api.row_id_for).parameters
