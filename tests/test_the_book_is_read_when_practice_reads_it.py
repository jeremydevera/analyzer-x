"""The backtest reads Gate's recorded book when PRACTICE reads it: three
seconds after a candle closes, not at the close itself (Oct 15, 2026,
RCA-2026-10-15-G).

IOTX 30m cx_fast (#55D32617), Oct 12, 2026: the 6:00am candle closed at
0.003872. At 6:30:00am the recorded best bid was 0.003867, 0.129% below the
close against a 0.1% limit, so the backtest called it "the price already ran
away" and took nothing. At 6:30:01-03am the best bid was 0.003869 (0.077%);
practice read it at 6:30:02am, shorted at 0.003869 and was stopped at
6:46am (PK4GZT65, -1.28), a trade its backtest never held.

Measured over the 52 practice entries since the move to Gate: the runner
writes the entry 1 to 6 seconds after the close (median 3). Over 49 of them
the recorded best price matched practice's own on 32 when read at the close,
33 at one or two seconds, 36 at three.
"""
from __future__ import annotations

import calendar
import gzip
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from tradingagents import book_history as bh, cost_store as cs

T0 = 1791504000          # Oct 09, 2026 00:00 UTC
ROOT = Path(__file__).resolve().parents[1]


def hour(lines):
    return gzip.compress("\n".join(lines).encode())


SNAP = [f"{T0},set,99.5,5.0,1,0", f"{T0},set,99,8.0,1,0",
        f"{T0},set,100,-3.0,1,0", f"{T0},set,100.5,-4.0,1,0"]


def test_the_runner_reads_three_seconds_after_the_close():
    assert bh.READ_AT_S == 3


def test_each_minute_is_the_book_three_seconds_in_stamped_at_its_start():
    """The IOTX shape: the best bid moves up at +1 s and again at +5 s."""
    raw = hour(SNAP + [f"{T0 + 1},make,99.7,4.0,2,1",       # read: in
                       f"{T0 + 5},make,99.9,4.0,3,1"])      # read: not yet
    got = bh.replay_hour(raw, hour_start=T0, contract_size=1.0,
                         notional_usd=100.0)
    assert got[0]["t"] == T0, "stamped at the minute it answers for"
    assert got[0]["bid"] == 99.7, "the +1 s bid is in the book at +3 s"
    assert got[1]["bid"] == 99.9
    assert got[0]["at"] == 3 and got[1]["at"] == 3


def test_an_event_at_exactly_three_seconds_is_in_the_reading():
    raw = hour(SNAP + [f"{T0 + 3},take,100,-3.0,2,1"])
    got = bh.replay_hour(raw, hour_start=T0, contract_size=1.0,
                         notional_usd=100.0)
    assert got[0]["ask"] == 100.5


def test_the_last_minute_reads_inside_its_own_hour():
    raw = hour(SNAP + [f"{T0 + 3542},make,99.9,1.0,2,1"])
    got = bh.replay_hour(raw, hour_start=T0, contract_size=1.0,
                         notional_usd=100.0)
    assert got[59]["t"] == T0 + 3540 and got[59]["bid"] == 99.9


def test_a_packed_month_keeps_when_each_reading_was_taken():
    got = bh.replay_hour(hour(SNAP), hour_start=T0, contract_size=1.0,
                         notional_usd=100.0)
    packed = bh.pack(got)
    assert packed["at"].tolist() == [3] * 60
    back = cs.from_bytes(cs.to_bytes(packed))
    assert back["at"].tolist() == [3] * 60


def test_a_reading_that_does_not_say_when_it_was_taken_is_the_old_kind():
    """Every month written before this change was read AT the close."""
    old = {k: v for k, v in bh.pack(bh.replay_hour(
        hour(SNAP), hour_start=T0, contract_size=1.0,
        notional_usd=100.0)).items() if k != "at"}
    import io
    buf = io.BytesIO()
    np.savez_compressed(buf, **old)
    back = cs.from_bytes(buf.getvalue())
    assert back["at"].tolist() == [0] * 60
    merged = cs.merge(back, bh.pack(bh.replay_hour(
        hour(SNAP), hour_start=T0 + 3600, contract_size=1.0,
        notional_usd=100.0)))
    assert merged["at"].tolist() == [0] * 60 + [3] * 60
    assert bh.pack([dict(r) for r in [{"t": T0, "bid": 1.0, "ask": 1.1,
                                       "spread": 0.1, "buy": 0.05, "sell": 0.05,
                                       "exhausted": False,
                                       "source": "full"}]])["at"].tolist() == [0]


# ------------------------------------------------- the costs job reads them again
@pytest.fixture
def shard(monkeypatch, tmp_path):
    for k in ("GITHUB_TOKEN", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DAYS_LIST", "2026-09-10")
    monkeypatch.setenv("COIN_LIST", "BTC_USDT")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(ROOT / ".github" / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "costs_shard_read_at", ROOT / ".github" / "scripts" / "costs_shard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("costs_shard_read_at", None)


D1 = calendar.timegm((2026, 9, 10, 0, 0, 0))


def _readings(at, crossed=()):
    return [None if h in crossed else
            {"t": D1 + 3600 * h + 60 * m, "bid": 1.0, "ask": 1.0 + at / 1000,
             "spread": 0.0001, "buy": 0.0002, "sell": 0.0002,
             "exhausted": False, "source": "full", "at": at}
            for h in range(24) for m in (0, 1)]


def test_a_day_read_at_the_close_is_read_again_and_replaced(shard, monkeypatch):
    held = bh.pack(_readings(0))
    asked, uploaded = [], []
    monkeypatch.setattr(shard.cs, "load_month", lambda *a, **k: held)
    monkeypatch.setattr(shard.fx, "contract_spec",
                        lambda sym: {"contractSize": 0.0001})

    def day_readings(sym, d, hours=None, **k):
        asked.append(sorted(hours))
        return {**bh.pack(_readings(3)), "hours_read": 24}

    monkeypatch.setattr(shard.bh, "day_readings", day_readings)
    monkeypatch.setattr(shard, "upload", lambda path, tag: uploaded.append(
        shard.cs.from_bytes(path.read_bytes())) or True)
    assert shard.main() == 0
    assert asked == [[D1 + 3600 * h for h in range(24)]], \
        "a whole day read the old way is asked for again"
    assert uploaded[0]["at"].tolist() == [3] * 48


def test_an_hour_the_new_read_could_not_answer_keeps_no_old_minute(
        shard, monkeypatch):
    """Re-read hours replace the old ones WHOLE: a minute the new replay finds
    crossed is no reading, never the old close-time book left behind."""
    held = bh.pack(_readings(0))
    uploaded = []
    monkeypatch.setattr(shard.cs, "load_month", lambda *a, **k: held)
    monkeypatch.setattr(shard.fx, "contract_spec",
                        lambda sym: {"contractSize": 0.0001})
    monkeypatch.setattr(shard.bh, "day_readings", lambda sym, d, hours=None, **k: {
        **bh.pack(_readings(3, crossed={5})), "hours_read": 24})
    monkeypatch.setattr(shard, "upload", lambda path, tag: uploaded.append(
        shard.cs.from_bytes(path.read_bytes())) or True)
    assert shard.main() == 0
    hour5 = [int(t) for t in uploaded[0]["t"] if D1 + 5 * 3600 <= t < D1 + 6 * 3600]
    assert hour5 == []
    assert set(uploaded[0]["at"].tolist()) == {3}


def test_an_hour_that_failed_to_download_keeps_its_old_readings(shard, monkeypatch):
    """The hour Gate could not hand over is NOT dropped: the old reading is a
    real book, and the next press asks for that hour again (the run ends red)."""
    held = bh.pack(_readings(0))
    uploaded = []
    monkeypatch.setattr(shard.cs, "load_month", lambda *a, **k: held)
    monkeypatch.setattr(shard.fx, "contract_spec",
                        lambda sym: {"contractSize": 0.0001})
    monkeypatch.setattr(shard.bh, "day_readings", lambda sym, d, hours=None, **k: {
        **bh.pack([r for r in _readings(3) if not D1 + 7 * 3600 <= r["t"] < D1 + 8 * 3600]),
        "hours_read": 23, "hours_failed": [D1 + 7 * 3600]})
    monkeypatch.setattr(shard, "upload", lambda path, tag: uploaded.append(
        shard.cs.from_bytes(path.read_bytes())) or True)
    assert shard.main() == 1, "a failed hour ends the run red"
    hour7 = [(int(t), int(a)) for t, a in zip(uploaded[0]["t"], uploaded[0]["at"], strict=True)
             if D1 + 7 * 3600 <= t < D1 + 8 * 3600]
    assert hour7 and {a for _t, a in hour7} == {0}


def test_held_hours_count_only_the_new_reads(shard):
    old = bh.pack(_readings(0))
    new = bh.pack(_readings(3))
    assert shard.held_hours(old) == set()
    assert shard.held_hours(new) == {D1 + 3600 * h for h in range(24)}


# ------------------------------------------------- the scheduler asks again
def test_the_days_done_the_old_way_are_pressed_again(monkeypatch, tmp_path):
    from tradingagents import costs_daily as cd

    monkeypatch.setattr(cd, "STATE", tmp_path / "costs_daily.json")
    cd._write({"done_days": ["2026-10-01", "2026-10-02"]})
    assert cd.redo_if_read_differently(cd.read()) is True
    st = cd.read()
    assert st["done_days"] == [] and st["read_at_s"] == bh.READ_AT_S
    assert cd.redo_if_read_differently(st) is False, "once"
    cd._write({**st, "done_days": ["2026-10-03"]})
    assert cd.redo_if_read_differently(cd.read()) is False
    assert cd.read()["done_days"] == ["2026-10-03"]


def test_a_reading_taken_when_practice_looks_wins_whatever_account_holds_it():
    """Harddev round 1: the deal moves coins between the two accounts, so one
    coin-month can sit on both, and a reader merges them in a fixed order
    with the LATER file winning a minute both hold. After the re-read, the
    account that re-read a coin holds the new month and the other may still
    hold the old one — read second, the old reading would have won."""
    new = bh.pack(bh.replay_hour(hour(SNAP + [f"{T0 + 1},make,99.7,4.0,2,1"]),
                                 hour_start=T0, contract_size=1.0,
                                 notional_usd=100.0))
    old = bh.pack(bh.replay_hour(hour(SNAP + [f"{T0 + 1},make,99.7,4.0,2,1"]),
                                 hour_start=T0, contract_size=1.0,
                                 notional_usd=100.0, at_s=0))
    assert old["bid"][0] == 99.5 and new["bid"][0] == 99.7
    for a, b in ((new, old), (old, new)):
        m = cs.merge(a, b)
        assert m["bid"][0] == 99.7 and set(m["at"].tolist()) == {3}, \
            "the reading taken when practice looks wins, in either order"
    # between two readings of the same kind the later file still wins
    newer = {**new, "bid": new["bid"] + 0.01}
    assert cs.merge(new, newer)["bid"][0] == pytest.approx(99.71)
