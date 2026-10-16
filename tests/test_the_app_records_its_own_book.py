"""The order book the APP can trade, recorded every minute for every Gate
contract, and preferred by the backtest (Oct 16, 2026, RCA-2026-10-16-A).

Gate's published order-book history holds RPI offers - "RPI orders are only
matched with non-API taker orders" (Gate, Jan 07, 2026) - and the app trades
through the API. Measured Oct 15, 2026 8:00-8:03pm at the same instants:
Gate's record matched the app's REST book on BTC 42 of 45 times and on QNTX
0 of 45 (record 36.94 / 36.96, the app's 36.91 / 37.12). Gate's public feed
carries both books: `futures.obu` is the normal one (equal to REST's
order_book: QNTX 37.20 / 37.34 on Oct 15, 2026) and `futures.rpi_obu` has
the RPI offers (37.20 / 37.22). The operator chose, Oct 16, 2026: "Record
app's prices".
"""
from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest

from tradingagents import app_books as ab, book_history as bh, cost_store as cs

T = 1792108800                 # Oct 16, 2026 00:00 UTC, a minute's first second
QNTX_FULL = {"t": (T + 3) * 1000 + 120, "full": True, "s": "ob.QNTX_USDT.50",
             "u": 85612890,
             "b": [["36.91", "11"], ["36.87", "8"], ["36.72", "1"], ["36.6", "300"]],
             "a": [["37.12", "11"], ["37.18", "34"], ["37.3", "400"]]}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "HOME", tmp_path / "app_books")
    return tmp_path / "app_books"


# -------------------------------------------------------------- the reading
def test_a_snapshot_is_the_reading_book_history_would_make():
    """One rule for both books: the same walk of $100 down each side."""
    got = ab.reading_from_snapshot(QNTX_FULL, contract_size=0.1, minute_start=T,
                                   seen_at=T + 3.2)
    bids = {36.91: 11.0, 36.87: 8.0, 36.72: 1.0, 36.6: 300.0}
    asks = {37.12: 11.0, 37.18: 34.0, 37.3: 400.0}
    want = bh._sample(bids, asks, T, contract_size=0.1, notional_usd=100.0,
                      source="app")
    for k in ("t", "bid", "ask", "spread", "buy", "sell", "exhausted"):
        assert got[k] == pytest.approx(want[k]), k
    assert got["source"] == "app" and got["at"] == 3, \
        "read 3 s into its minute: when it ARRIVED, never Gate's stamp"
    assert (got["bid"], got["ask"]) == (36.91, 37.12), \
        "the app's QNTX book of Oct 15, 2026 8:00pm, not the record's 36.94 / 36.96"


def test_an_empty_side_is_no_reading():
    empty = {**QNTX_FULL, "a": []}
    assert ab.reading_from_snapshot(empty, contract_size=0.1, minute_start=T) is None


def test_a_level_of_size_zero_is_not_a_level():
    z = {**QNTX_FULL, "a": [["36.99", "0"], ["37.12", "11"]]}
    assert ab.reading_from_snapshot(z, contract_size=0.1, minute_start=T)["ask"] == 37.12


def test_app_is_its_own_source_in_the_packed_month():
    r = ab.reading_from_snapshot(QNTX_FULL, contract_size=0.1, minute_start=T)
    packed = bh.pack([r])
    assert packed["source"].tolist() == [bh.SOURCES["app"]] == [3]


# -------------------------------------------------------------- the store
def _r(t, bid, *, source="app", at=3):
    return {"t": t, "bid": bid, "ask": bid + 0.01, "spread": 0.0003, "buy": 0.0002,
            "sell": 0.0002, "exhausted": False, "source": source, "at": at}


def test_readings_are_kept_by_coin_and_utc_day_and_read_back(home):
    st = ab.Store()
    st.add("QNTX_USDT", _r(T - 60, 36.9))          # Oct 15's last minute
    st.add("QNTX_USDT", _r(T, 36.91))              # Oct 16's first
    st.add("BTC_USDT", _r(T, 82205.7))
    st.flush()
    assert (home / "QNTX_USDT" / "20261015.bin").exists()
    assert (home / "QNTX_USDT" / "20261016.bin").exists()
    got = ab.book_for("QNTX_USDT", T - 3600, T + 60)
    assert got["t"].tolist() == [T - 60, T] and got["bid"].tolist() == [36.9, 36.91]
    assert ab.book_for("BTC_USDT", T, T)["bid"].tolist() == [82205.7]
    assert len(ab.book_for("ETH_USDT", T, T)["t"]) == 0


def test_a_restart_mid_day_keeps_the_mornings_readings(home):
    first = ab.Store()
    first.add("QNTX_USDT", _r(T, 36.91))
    first.flush()
    again = ab.Store()                             # a new process, same day
    again.add("QNTX_USDT", _r(T + 60, 36.95))
    again.flush()
    assert ab.book_for("QNTX_USDT", T, T + 60)["t"].tolist() == [T, T + 60]


def test_a_flush_with_nothing_new_writes_nothing(home):
    st = ab.Store()
    st.flush()
    assert not home.exists() or not any(home.rglob("*.bin"))


def test_a_flush_appends_and_never_rewrites_the_day(home):
    """Harddev round 2: rewriting 1,039 day files every five minutes is
    ~5.8 GB a day of writes on this PC's mechanical G:; appending the new
    39-byte records is 58 MB."""
    st = ab.Store()
    st.add("QNTX_USDT", _r(T, 36.91))
    st.flush()
    f = home / "QNTX_USDT" / "20261016.bin"
    first = f.read_bytes()
    st.add("QNTX_USDT", _r(T + 60, 36.95))
    st.flush()
    assert f.read_bytes()[:len(first)] == first, "the earlier records are untouched"
    assert len(f.read_bytes()) == 2 * ab._rec().itemsize == 78


def test_a_record_cut_short_by_a_killed_process_is_dropped(home):
    st = ab.Store()
    st.add("QNTX_USDT", _r(T, 36.91))
    st.flush()
    f = home / "QNTX_USDT" / "20261016.bin"
    with open(f, "ab") as fh:
        fh.write(b"")                       # half a record
    assert ab.book_for("QNTX_USDT", T, T + 60)["bid"].tolist() == [36.91]


def test_a_minute_recorded_twice_is_read_once_the_last_kept(home):
    st = ab.Store()
    st.add("QNTX_USDT", _r(T, 36.91))
    st.flush()
    st.add("QNTX_USDT", _r(T, 36.93))                      # a restart, same minute
    st.flush()
    got = ab.book_for("QNTX_USDT", T, T)
    assert got["t"].tolist() == [T] and got["bid"].tolist() == [36.93]


# ------------------------------------------------- the backtest prefers it
def test_the_backtest_takes_the_apps_book_where_it_has_one(home, monkeypatch):
    """The record's QNTX minute holds the RPI quote; the app's holds what the
    app could trade. Where both exist the app's wins, in either merge order;
    elsewhere the record still answers."""
    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.setattr(ab, "IN_BACKTEST", True)
    record = bh.pack([_r(T, 36.94, source="full"), _r(T + 60, 36.95, source="full")])
    monkeypatch.setattr(cs, "book_for", lambda sym, a, b, **k: record)
    st = ab.Store()
    st.add("QNTX_USDT", _r(T, 36.91))
    st.flush()
    got = cs.engine_book("QNTX_USDT", T, T + 60)
    assert got["t"].tolist() == [T, T + 60]
    assert got["bid"].tolist() == [36.91, 36.95], \
        "the app's 36.91 at T, the record at T + 60 where the app has none"
    assert got["source"].tolist() == [3, 1]
    for a, b in ((record, ab.book_for("QNTX_USDT", T, T)),
                 (ab.book_for("QNTX_USDT", T, T), record)):
        assert cs.merge(a, b)["bid"][0] == 36.91


def test_until_github_can_read_them_the_backtest_does_not_either(home, monkeypatch):
    """Harddev round 3: the nightly v2 update measures on GitHub, which
    cannot see this PC's files; a PC press preferring them would give one
    strategy two results by where it was measured."""
    monkeypatch.setenv("TA_VENUE", "gate")
    assert ab.IN_BACKTEST is False
    record = bh.pack([_r(T, 36.94, source="full")])
    monkeypatch.setattr(cs, "book_for", lambda sym, a, b, **k: record)
    st = ab.Store()
    st.add("QNTX_USDT", _r(T, 36.91))
    st.flush()
    assert cs.engine_book("QNTX_USDT", T, T)["bid"].tolist() == [36.94]


def test_off_gate_there_is_no_book_at_all(home, monkeypatch):
    monkeypatch.setenv("TA_VENUE", "mexc")
    assert cs.engine_book("QNTX_USDT", T, T + 60) is None


# ------------------------------------------------------------ the snapshots
class FakeWS:
    """Gate's feed: `before` is already waiting when a burst starts (the last
    minute's leftovers), `after` arrives once the burst subscribes."""

    def __init__(self, before, after):
        self.inbox = [json.dumps(m) for m in before]
        self.after = [json.dumps(m) for m in after]
        self.sent: list = []

    async def send(self, raw):
        m = json.loads(raw)
        self.sent.append(m)
        if m["event"] == "subscribe" and self.after:
            self.inbox += self.after
            self.after = []

    async def recv(self):
        if not self.inbox:
            await asyncio.sleep(10)
        return self.inbox.pop(0)


def _upd(result):
    return {"channel": "futures.obu", "event": "update", "result": result}


def test_a_burst_keeps_one_full_snapshot_per_coin_asked_for_and_unsubscribes():
    """Harddev round 1: Gate's `t` is when the book last CHANGED, not when it
    was sent - measured Oct 16, 2026, the oldest of 1,038 snapshots carried a
    stamp 46 minutes old (NEURALINK) and 10% were older than ~11 s. A quiet
    coin's snapshot is today's book and is kept; what tells an old snapshot
    apart is that it was already waiting before the burst asked, so the
    burst clears those out first."""
    leftover = {**QNTX_FULL, "u": 1}                       # the last minute's
    quiet = {**QNTX_FULL, "s": "ob.NEURALINK_USDT.50", "t": (T - 2793) * 1000}
    after = [
        {"channel": "futures.obu", "event": "subscribe", "result": {"status": "success"}},
        _upd({"t": (T + 3) * 1000, "s": "ob.QNTX_USDT.50", "U": 1, "u": 2,
              "b": [["36.0", "1"]], "a": []}),             # incremental
        _upd(QNTX_FULL),
        _upd(quiet),
        _upd({**QNTX_FULL, "s": "ob.ETH_USDT.50"}),        # not asked for
    ]
    ws = FakeWS([_upd(leftover)], after)
    got = asyncio.run(ab.burst_one(ws, ["QNTX_USDT", "NEURALINK_USDT", "BTC_USDT"],
                                   ask_at=T + 2.5, deadline_s=0.5))
    assert set(got) == {"QNTX_USDT", "NEURALINK_USDT"},         "BTC never answered; ETH was not asked; the quiet coin is kept"
    assert got["QNTX_USDT"]["u"] == 85612890, "the fresh snapshot, never the leftover"
    assert got["QNTX_USDT"]["_seen"] > 0, "when it arrived travels with it"
    kinds = [(m["event"], tuple(m["payload"])) for m in ws.sent]
    assert kinds[0] == ("subscribe", ("ob.QNTX_USDT.50", "ob.NEURALINK_USDT.50",
                                      "ob.BTC_USDT.50"))
    assert kinds[-1][0] == "unsubscribe" and kinds[-1][1] == kinds[0][1]


# ------------------------------------------------------------- the process
def test_it_is_started_only_where_the_app_trades_gate(home, monkeypatch, background_calls):
    monkeypatch.setenv("TA_VENUE", "mexc")
    assert ab.spawn_recorder() is None
    monkeypatch.setenv("TA_VENUE", "gate")
    pid = ab.spawn_recorder()
    assert pid and background_calls, "a background program, started with no window"
    call = background_calls[-1]
    assert call["args"][-2:] == ["tradingagents.app_books", "run"]
    assert call["kwargs"]["env"]["PYTHONUNBUFFERED"] == "1"


def test_the_supervisor_keeps_it_running():
    import inspect

    from tradingagents import api

    src = inspect.getsource(api)
    assert "_ab.spawn_recorder()" in src, \
        "a recorder that dies must be started again, like the indexer"
