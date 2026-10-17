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
from pathlib import Path

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
def _publish(day, coins):
    m = ab._marker(day)
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(json.dumps({"coins": coins, "failed": [], "at": 0}), encoding="utf-8")


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
    got = ab.book_for("QNTX_USDT", T - 3600, T + 60, published_only=False)
    assert got["t"].tolist() == [T - 60, T] and got["bid"].tolist() == [36.9, 36.91]
    assert ab.book_for("BTC_USDT", T, T, published_only=False)["bid"].tolist() == [82205.7]
    assert len(ab.book_for("ETH_USDT", T, T, published_only=False)["t"]) == 0


def test_a_restart_mid_day_keeps_the_mornings_readings(home):
    first = ab.Store()
    first.add("QNTX_USDT", _r(T, 36.91))
    first.flush()
    again = ab.Store()                             # a new process, same day
    again.add("QNTX_USDT", _r(T + 60, 36.95))
    again.flush()
    assert ab.book_for("QNTX_USDT", T, T + 60, published_only=False)["t"].tolist() == [T, T + 60]


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
    assert ab.book_for("QNTX_USDT", T, T + 60, published_only=False)["bid"].tolist() == [36.91]


def test_a_minute_recorded_twice_is_read_once_the_last_kept(home):
    st = ab.Store()
    st.add("QNTX_USDT", _r(T, 36.91))
    st.flush()
    st.add("QNTX_USDT", _r(T, 36.93))                      # a restart, same minute
    st.flush()
    got = ab.book_for("QNTX_USDT", T, T, published_only=False)
    assert got["t"].tolist() == [T] and got["bid"].tolist() == [36.93]


# ------------------------------------------------- the backtest prefers it
def test_the_backtest_takes_the_apps_book_where_it_has_one(home, monkeypatch):
    """The record's QNTX minute holds the RPI quote; the app's holds what the
    app could trade. Where both exist the app's wins, in either merge order;
    elsewhere the record still answers."""
    monkeypatch.setenv("TA_VENUE", "gate")
    assert ab.IN_BACKTEST is True
    record = bh.pack([_r(T, 36.94, source="full"), _r(T + 60, 36.95, source="full")])
    monkeypatch.setattr(cs, "book_for", lambda sym, a, b, **k: record)
    st = ab.Store()
    st.add("QNTX_USDT", _r(T, 36.91))
    st.flush()
    _publish("20261016", ["QNTX_USDT"])
    got = cs.engine_book("QNTX_USDT", T, T + 60)
    assert got["t"].tolist() == [T, T + 60]
    assert got["bid"].tolist() == [36.91, 36.95], \
        "the app's 36.91 at T, the record at T + 60 where the app has none"
    assert got["source"].tolist() == [3, 1]
    mine = ab.book_for("QNTX_USDT", T, T)
    for a, b in ((record, mine), (mine, record)):
        assert cs.merge(a, b)["bid"][0] == 36.91


def test_a_day_github_cannot_read_yet_is_not_read_here_either(home, monkeypatch):
    """Harddev round 3: the nightly v2 update measures on GitHub, which reads
    a day only once it is published; this PC reads the same days and no
    others, so one strategy has one result wherever it was measured."""
    monkeypatch.setenv("TA_VENUE", "gate")
    record = bh.pack([_r(T, 36.94, source="full")])
    monkeypatch.setattr(cs, "book_for", lambda sym, a, b, **k: record)
    st = ab.Store()
    st.add("QNTX_USDT", _r(T, 36.91))
    st.flush()
    assert cs.engine_book("QNTX_USDT", T, T)["bid"].tolist() == [36.94], \
        "today, unpublished: Gate's record, as on GitHub"
    _publish("20261016", ["QNTX_USDT"])
    assert cs.engine_book("QNTX_USDT", T, T)["bid"].tolist() == [36.91]
    monkeypatch.setattr(ab, "IN_BACKTEST", False)
    assert cs.engine_book("QNTX_USDT", T, T)["bid"].tolist() == [36.94], \
        "the switch takes the app's books out of every backtest at once"


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


# ------------------------------------------------------------- publishing
class FakeGh:
    def __init__(self, fail_tags=()):
        self.calls: list = []
        self.fail = set(fail_tags)

    def __call__(self, *args):
        import subprocess

        self.calls.append(args)
        ok = not (args[:2] == ("release", "upload") and args[2] in self.fail)
        return subprocess.CompletedProcess(args, 0 if ok else 1, "",
                                           "" if ok else "HTTP 502")


def _no_sleep(monkeypatch):
    monkeypatch.setattr(ab.time, "sleep", lambda _s: None)


def test_a_finished_day_goes_up_one_file_per_coin_two_releases_a_day(home, monkeypatch):
    _no_sleep(monkeypatch)
    gh = FakeGh()
    monkeypatch.setattr(ab, "_gh", gh)
    st = ab.Store()
    for sym in ("ANKR_USDT", "QNTX_USDT", "BTC_USDT"):
        st.add(sym, _r(T, 1.0))
    st.flush()
    got = ab.publish_day("20261016")
    assert got == {"day": "20261016", "coins": 3, "failed": []}
    ups = [c for c in gh.calls if c[:2] == ("release", "upload")]
    assert sorted(c[2] for c in ups) == ["appbook-20261016-a", "appbook-20261016-b",
                                         "appbook-index"], "the coins, then the list"
    assert ups[-1][2] == "appbook-index", "the list goes up after the coins it names"
    files = sorted(Path(f).name for c in ups for f in c[3:] if str(f).endswith(".npz"))
    assert files == ["ANKR_USDT.npz", "BTC_USDT.npz", "QNTX_USDT.npz"]
    assert ab._published("20261016") == {"ANKR_USDT", "QNTX_USDT", "BTC_USDT"}
    assert ab.url("20261016", "QNTX_USDT") == (
        "https://github.com/jeremydevera/analyzer-x/releases/download/"
        "appbook-20261016-b/QNTX_USDT.npz")


def test_a_coin_whose_upload_failed_is_neither_read_nor_forgotten(home, monkeypatch):
    _no_sleep(monkeypatch)
    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    gh = FakeGh(fail_tags={"appbook-20261016-b"})
    monkeypatch.setattr(ab, "_gh", gh)
    st = ab.Store()
    st.add("ANKR_USDT", _r(T, 1.0))
    st.add("QNTX_USDT", _r(T, 36.91))
    st.flush()
    got = ab.publish_day("20261016")
    assert got["coins"] == 1 and got["failed"] == ["QNTX_USDT"]
    assert ab._published("20261016") == {"ANKR_USDT"}
    assert len(ab.book_for("QNTX_USDT", T, T)["t"]) == 0, "not on GitHub, not read here"
    gh.fail.clear()
    monkeypatch.setattr(ab, "_TICKED", {"at": 0.0})
    tick = ab.publish_tick(now=T + 86400 + 3600)        # Oct 17, 2026 1:00am UTC
    assert [g["day"] for g in tick["published"]] == ["20261016"]
    assert tick["published"][0]["coins"] == 1, "only the coin that failed goes up again"
    assert ab._published("20261016") == {"ANKR_USDT", "QNTX_USDT"}


def test_the_tick_publishes_finished_days_only_after_twenty_past_midnight(home, monkeypatch):
    _no_sleep(monkeypatch)
    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(ab, "_gh", FakeGh())
    monkeypatch.setattr(ab, "_TICKED", {"at": 0.0})
    st = ab.Store()
    st.add("QNTX_USDT", _r(T - 60, 36.9))               # Oct 15
    st.add("QNTX_USDT", _r(T + 600, 36.95))             # Oct 16, still being recorded
    st.flush()
    assert ab.publish_tick(now=T + 600)["published"] == [], "00:10 UTC: too early"
    got = ab.publish_tick(now=T + 1500)                 # 00:25 UTC
    assert [g["day"] for g in got["published"]] == ["20261015"], "never today"
    assert ab.publish_tick(now=T + 1600)["why"] == "looked less than an hour ago"


def test_github_reads_a_published_day_from_its_release(tmp_path, monkeypatch):
    """GitHub's machines have no recorder: they read the list of published
    days once, then each listed coin-day from its release, once per process.
    A day the list does not name is never asked for - a replay reaching back
    to Jul 01, 2026 would otherwise ask ~110 days of every coin it measures,
    nearly all "no such file"."""
    monkeypatch.setattr(ab, "HOME", tmp_path / "nothing_here")
    monkeypatch.setattr(ab, "_REMOTE", {})
    monkeypatch.setattr(ab, "_REMOTE_DAYS", {})
    packed = cs.merge(None, bh.pack([_r(T, 36.91)]))
    asked = []

    def fetch(u):
        asked.append(u)
        if u == ab.index_url():
            return 200, json.dumps({"days": ["20261016"]}).encode()
        return (200, cs.to_bytes(packed)) if "20261016" in u else (404, b"")

    monkeypatch.setattr(cs, "_fetch", fetch)
    got = ab.book_for("QNTX_USDT", T - 3 * 86400, T + 60)
    assert got["bid"].tolist() == [36.91]
    ab.book_for("QNTX_USDT", T - 3 * 86400, T + 60)
    assert asked == [ab.index_url(), ab.url("20261016", "QNTX_USDT")], \
        "the list once, the one listed day once, nothing else"


def test_a_day_whose_list_did_not_go_up_is_not_read_anywhere(home, monkeypatch):
    """Harddev: the coins went up but the list naming the day did not - so
    GitHub cannot find the day, and this PC must not read it either; the next
    tick sends the day again."""
    _no_sleep(monkeypatch)
    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    gh = FakeGh(fail_tags={"appbook-index"})
    monkeypatch.setattr(ab, "_gh", gh)
    st = ab.Store()
    st.add("QNTX_USDT", _r(T, 36.91))
    st.flush()
    got = ab.publish_day("20261016")
    assert got["coins"] == 0 and "list" in got["why"]
    assert not ab._marker("20261016").exists()
    assert len(ab.book_for("QNTX_USDT", T, T)["t"]) == 0
    gh.fail.clear()
    monkeypatch.setattr(ab, "_TICKED", {"at": 0.0})
    tick = ab.publish_tick(now=T + 86400 + 3600)
    assert tick["published"][0]["coins"] == 1
    assert ab.book_for("QNTX_USDT", T, T)["bid"].tolist() == [36.91]


def test_github_s_shards_lay_the_apps_books_over_the_record():
    import inspect

    root = Path(__file__).resolve().parents[1] / ".github" / "scripts"
    for name in ("sweep_shard.py", "replay_shard.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "cost_store.with_app_books(" in src, name
    assert "with_app_books(sym, got" in inspect.getsource(cs.engine_book)


def test_the_supervisor_publishes_once_a_day():
    import inspect

    from tradingagents import api

    src = inspect.getsource(api)
    assert '"app-books-publish"' in src and "_ab.publish_tick" in src
