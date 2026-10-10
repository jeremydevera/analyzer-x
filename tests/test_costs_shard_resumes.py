"""A costs run that ran out of time is RESUMED, never redone (Oct 10, 2026).

The first press backfills 30 days for ~513 coins per account. Measured on the
trial (run 38035675014): one day of BTC_USDT took 132 s and AAPL_USDT 32 s,
so 30 days x ~26 coins a machine is past the job's 350-minute limit. A red
run leaves its days "not done" (costs_daily._settle), the next press asks for
the same 30 days again — and if every coin replayed every day again, every
press would run out of time at the same place for ever. The shard skips the
days a coin's month file already holds, so each press picks up where the
last one stopped.
"""
from __future__ import annotations

import calendar
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
D1 = calendar.timegm((2026, 9, 10, 0, 0, 0))
D2, D3 = D1 + 86400, D1 + 2 * 86400


@pytest.fixture
def shard(monkeypatch, tmp_path):
    for k in ("GITHUB_TOKEN", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DAYS_LIST", "2026-09-10,2026-09-11,2026-09-12")
    monkeypatch.setenv("COIN_LIST", "BTC_USDT")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("costs_shard_test",
                                                  SCRIPTS / "costs_shard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("costs_shard_test", None)


def _reading(t):
    return {"t": t, "bid": 1.0, "ask": 1.0, "spread": 0.0001, "buy": 0.0002,
            "sell": 0.0002, "exhausted": False, "source": "full"}


def _wire(shard, monkeypatch, held_days):
    from tradingagents import book_history as bh

    held = bh.pack([_reading(d + 60) for d in held_days])
    replayed, uploaded = [], []
    monkeypatch.setattr(shard.cs, "load_month", lambda *a, **k: held)
    monkeypatch.setattr(shard.fx, "contract_spec", lambda sym: {"contractSize": 0.0001})

    def day_readings(sym, d, **k):
        replayed.append(d)
        return {**bh.pack([_reading(d + 60)]), "hours_read": 24}

    monkeypatch.setattr(shard.bh, "day_readings", day_readings)
    monkeypatch.setattr(shard, "upload", lambda path, tag: uploaded.append(
        shard.cs.from_bytes(path.read_bytes())) or True)
    return replayed, uploaded


def test_a_day_the_month_file_already_holds_is_not_replayed_again(shard, monkeypatch):
    replayed, uploaded = _wire(shard, monkeypatch, [D1])
    assert shard.main() == 0
    assert replayed == [D2, D3]
    assert len(uploaded) == 1
    assert sorted(int(t) for t in uploaded[0]["t"]) == [D1 + 60, D2 + 60, D3 + 60], \
        "the held day is kept beside the two new ones"


def test_a_coin_whose_month_holds_every_day_is_neither_replayed_nor_uploaded(
        shard, monkeypatch):
    replayed, uploaded = _wire(shard, monkeypatch, [D1, D2, D3])
    assert shard.main() == 0
    assert replayed == [] and uploaded == []
