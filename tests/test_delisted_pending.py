"""Delisted pairs are NAMED beside the pending count, never inside it.

Sep 06, 2026: 24 of 677 pending sat on coins MEXC no longer lists (ASP,
BULLCOIN, CZ, DRV, MEZO, ST). No press can resolve them — GitHub shards build
their coin list from the live venue, this PC no longer sweeps, and a hand-run
dies walking the dead order book (and its rows would be fiction on fees,
rule 9). Counted as pending, they hold the count above zero forever and make
the autopilot dispatch runs for pairs nothing can touch.

The split uses THE SHARD'S OWN RULE (`sweep_shard.py`: state == 0) — NOT
`db_jobs.live_symbols`, which also drops apiAllowed=False contracts and
called 50 pairs unreachable when only 24 were.
"""
import json

import pytest

from tradingagents import backtest_logs as bl, cloud_autopilot as ca, market_sweep as msw


@pytest.fixture
def store(tmp_path, monkeypatch):
    candles = tmp_path / "candles"
    states = tmp_path / "states"
    candles.mkdir(); states.mkdir()
    monkeypatch.setattr(msw, "CANDLES", candles)
    monkeypatch.setattr(msw, "STATES", states)
    bl._PENDING.update(at=0, payload=None)
    bl._FLEET.update(at=0.0, symbols=None)
    # KITE measured, STBL pending+live, ASP pending+delisted
    for pair in ("KITE_USDT-1h", "STBL_USDT-1h", "ASP_USDT-1h", "ASP_USDT-4h"):
        (candles / f"{pair}.json").write_text("[]")
    (states / "KITE-1h.json").write_text("{}")
    yield
    bl._PENDING.update(at=0, payload=None)
    bl._FLEET.update(at=0.0, symbols=None)


def _fleet(monkeypatch, symbols):
    monkeypatch.setattr(bl, "fleet_symbols", lambda max_age_s=300.0: symbols)


def test_delisted_pairs_are_named_not_counted(store, monkeypatch):
    _fleet(monkeypatch, {"KITE_USDT", "STBL_USDT"})
    p = bl.pending(force=True)
    assert p["count"] == 1                       # STBL only
    assert p["delisted"] == 2 and p["delisted_coins"] == ["ASP"]
    assert p["by_timeframe"] == {"1h": 1}
    # measured + pending + delisted = stored, or the panel's sentence lies
    assert p["measured"] + p["count"] + p["delisted"] == p["stored"]


def test_an_unreadable_venue_keeps_every_pair_counted(store, monkeypatch):
    """'Could not look' is never 'nothing is pending' — a failed age check
    KEEPS the coin (CLAUDE.md)."""
    _fleet(monkeypatch, None)
    p = bl.pending(force=True)
    assert p["count"] == 3 and p["delisted"] == 0


def test_the_fleet_rule_is_state_zero_not_api_allowed():
    """A listed contract with apiAllowed=False IS shard-reachable: the shard
    filters on state alone. Using the download list here over-excluded 26
    pairs on Sep 06, 2026."""
    import inspect

    s = inspect.getsource(bl.fleet_symbols)
    assert 'int(x.get("state", 1)) == 0' in s
    assert "apiAllowed" not in s.split('"""')[2], \
        "the CODE must not filter on apiAllowed (the docstring may name it)"
    shard = open(".github/scripts/sweep_shard.py", encoding="utf-8").read()
    assert 'int(x.get("state", 1)) == 0' in shard, \
        "the shard changed its rule — fleet_symbols must change with it"


def test_the_autopilot_skips_what_no_shard_can_reach(store, monkeypatch):
    _fleet(monkeypatch, {"KITE_USDT", "STBL_USDT"})
    assert ca.missing_by_timeframe() == {"1h": 1}
    _fleet(monkeypatch, None)
    assert ca.missing_by_timeframe() == {"1h": 2, "4h": 1}


def test_the_panel_says_the_exclusion_out_loud():
    """Rule 20: a capped count says what it capped."""
    p = open("webapp/src/components/backtest/LogsPanel.tsx", encoding="utf-8").read()
    assert "on delisted contracts left out" in p
    assert "delisted_coins" in p
    t = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert "delisted?: number" in t
