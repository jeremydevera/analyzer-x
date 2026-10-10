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


def _whole(d):
    """A day held whole: a reading in every one of its 24 hours."""
    return [d + 3600 * h + 60 for h in range(24)]


def _wire(shard, monkeypatch, held_days):
    from tradingagents import book_history as bh

    held = bh.pack([_reading(t) for d in held_days for t in _whole(d)])
    replayed, uploaded = [], []
    monkeypatch.setattr(shard.cs, "load_month", lambda *a, **k: held)
    monkeypatch.setattr(shard.fx, "contract_spec", lambda sym: {"contractSize": 0.0001})

    def day_readings(sym, d, hours=None, **k):
        replayed.append(d)
        hrs = list(hours) if hours is not None else [d + 3600 * h for h in range(24)]
        return {**bh.pack([_reading(h + 60) for h in hrs]), "hours_read": len(hrs)}

    monkeypatch.setattr(shard.bh, "day_readings", day_readings)
    monkeypatch.setattr(shard, "upload", lambda path, tag: uploaded.append(
        shard.cs.from_bytes(path.read_bytes())) or True)
    return replayed, uploaded


def test_a_day_the_month_file_already_holds_is_not_replayed_again(shard, monkeypatch):
    replayed, uploaded = _wire(shard, monkeypatch, [D1])
    assert shard.main() == 0
    assert replayed == [D2, D3]
    assert len(uploaded) == 1
    assert sorted(int(t) for t in uploaded[0]["t"]) == _whole(D1) + _whole(D2) + _whole(D3), \
        "the held day is kept beside the two new ones"


def test_a_coin_whose_month_holds_every_day_is_neither_replayed_nor_uploaded(
        shard, monkeypatch):
    replayed, uploaded = _wire(shard, monkeypatch, [D1, D2, D3])
    assert shard.main() == 0
    assert replayed == [] and uploaded == []


def test_a_month_that_could_not_be_read_is_never_overwritten(shard, monkeypatch):
    """Final review (RCA-2026-10-10-F): a 502 read as "no file", the shard
    replayed only the asked days and `--clobber` replaced the month — every
    earlier day of it gone. Now the coin is skipped by name and the run ends
    red, so the next press tries again."""
    replayed, uploaded = _wire(shard, monkeypatch, [])

    def broken(*a, **k):
        raise shard.cs.CostReadError("BTC_USDT 202609 could not be read from o/r: 502")
    monkeypatch.setattr(shard.cs, "load_month", broken)
    assert shard.main() == 1
    assert uploaded == [] and replayed == []


def test_a_day_with_a_failed_hour_is_left_to_be_read_again(shard, monkeypatch):
    from tradingagents import book_history as bh

    replayed, uploaded = _wire(shard, monkeypatch, [D1])

    def day_readings(sym, d, hours=None, **k):
        replayed.append(d)
        got = [h for h in hours if not (d == D2 and h == D2 + 3600)]
        return {**bh.pack([_reading(h + 60) for h in got]), "hours_read": len(got),
                "hours_failed": [D2 + 3600] if d == D2 else [], "hours_missing": [],
                "hours_bad": []}
    monkeypatch.setattr(shard.bh, "day_readings", day_readings)
    assert shard.main() == 1, "a day not wholly read keeps the run red"
    held = {int(t) // 3600 * 3600 for t in uploaded[0]["t"]}
    assert D2 + 3600 not in held and D2 in held and D2 + 7200 in held, \
        "the hours that were read are kept; the failed hour is asked again next time"


def test_a_broken_hour_file_is_named_and_the_day_kept(shard, monkeypatch, capsys):
    from tradingagents import book_history as bh

    replayed, uploaded = _wire(shard, monkeypatch, [D1, D2])

    def day_readings(sym, d, hours=None, **k):
        got = [h for h in hours if h != d + 9 * 3600]
        return {**bh.pack([_reading(h + 60) for h in got]), "hours_read": len(got),
                "hours_failed": [], "hours_missing": [],
                "hours_bad": [(d + 9 * 3600, "EOFError: cut")]}
    monkeypatch.setattr(shard.bh, "day_readings", day_readings)
    assert shard.main() == 0, "the same broken file would fail every run for ever"
    assert len(uploaded) == 1 and D3 + 60 in {int(t) for t in uploaded[0]["t"]}
    assert "EOFError" in capsys.readouterr().out


def test_an_upload_that_failed_ends_the_run_red(shard, monkeypatch):
    _wire(shard, monkeypatch, [])
    monkeypatch.setattr(shard, "upload", lambda path, tag: False)
    assert shard.main() == 1


def test_a_claim_with_no_answer_ends_the_run_red(shard, monkeypatch):
    """A coin whose claim got no answer is measured by nobody on this run."""
    replayed, uploaded = _wire(shard, monkeypatch, [])

    class Board:
        enabled = True

        def claim(self, sym):
            return None
    monkeypatch.setattr(shard, "ClaimBoard", Board)
    assert shard.main() == 1 and replayed == []


def test_the_month_is_read_from_every_account(shard, monkeypatch):
    seen = {}
    _wire(shard, monkeypatch, [D1, D2, D3])
    held = shard.cs.load_month

    def spy(*a, **k):
        seen.update(k)
        return held(*a, **k)
    monkeypatch.setattr(shard.cs, "load_month", spy)
    shard.main()
    assert "repos" not in seen or seen["repos"] is None, "both accounts, never its own"
    assert seen.get("strict") is True and seen.get("cache") is False


def test_only_the_hours_the_month_does_not_hold_are_read(shard, monkeypatch):
    """By the HOUR (final review, RCA-2026-10-10-H): the 07:00 UTC press reads
    today so far, and the next one must add the hours after it — a day was
    "held" once it had one reading, so its later hours were never read."""
    from tradingagents import book_history as bh

    _wire(shard, monkeypatch, [D1, D3])
    half = bh.pack([_reading(t) for t in _whole(D1) + _whole(D3)
                    + [D2 + 3600 * h + 60 for h in range(12)]])
    monkeypatch.setattr(shard.cs, "load_month", lambda *a, **k: half)
    asked = []

    def day_readings(sym, d, hours=None, **k):
        asked.extend(hours)
        return {**bh.pack([_reading(h + 60) for h in hours]), "hours_read": len(hours)}
    monkeypatch.setattr(shard.bh, "day_readings", day_readings)
    assert shard.main() == 0
    assert asked == [D2 + 3600 * h for h in range(12, 24)]


def test_an_hour_that_has_not_ended_is_not_asked_for(shard, monkeypatch):
    from tradingagents import book_history as bh

    _wire(shard, monkeypatch, [D1, D2])
    asked = []

    def day_readings(sym, d, hours=None, **k):
        asked.extend(hours)
        return {**bh.pack([_reading(h + 60) for h in hours]), "hours_read": len(hours)}
    monkeypatch.setattr(shard.bh, "day_readings", day_readings)
    monkeypatch.setattr(shard, "_now", lambda: D3 + 5 * 3600 + 120)   # 05:02 UTC
    assert shard.main() == 0
    assert asked == [D3 + 3600 * h for h in range(5)], "hours 00-04 have ended"
