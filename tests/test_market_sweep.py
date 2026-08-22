"""The Back Test module's promise: a refresh must equal a full re-run.

If continuing a backtest ever diverges from running it whole, every number the
Back Test tab shows after a refresh is wrong — silently. So the equality is
tested directly, on synthetic candles, including the case that broke it twice:
a position still open at the boundary.
"""
import pytest

from tradingagents import auto_trader as at, market_sweep as msw


def _bars(n=900, seed=7):
    """Deterministic zig-zag with a drift, enough to trigger entries."""
    import math

    import pandas as pd
    close = [100 + i * 0.02 + 6 * math.sin(i / 11.0 + seed) for i in range(n)]
    return pd.DataFrame({
        "Date": pd.date_range("2026-01-01", periods=n, freq="h"),
        "Open": close,
        "High": [c + 0.5 for c in close],
        "Low": [c - 0.5 for c in close],
        "Close": close})


def _dirs(n, every=40):
    d = [0] * n
    for i in range(30, n, every):
        d[i] = 1 if (i // every) % 2 == 0 else -1
    return d


KEY = "_msw_test"
SPEC = {"interval": "Min60", "bar_seconds": 3600, "tp": 0.02, "sl": 0.01}


@pytest.fixture(autouse=True)
def _spec():
    at.STRATEGY_SPECS[KEY] = dict(SPEC)
    yield
    at.STRATEGY_SPECS.pop(KEY, None)


def _run(df, dirs, **kw):
    return at.backtest_strategy(KEY, df, 10.0, fee=0.0004, slippage=0.0003,
                                sizing="martingale", dirs=dirs, tp=0.02,
                                sl=0.01, liq_move_pct=4.5, keep_log=False,
                                **kw)


@pytest.mark.parametrize("cut", [300, 455, 620, 880])
def test_continuing_equals_running_it_whole(cut):
    df = _bars()
    dirs = _dirs(len(df))
    whole = _run(df, dirs, resume={})
    first = _run(df.iloc[:cut], dirs[:cut], resume={})
    ctx = msw.CONTEXT_BARS
    lo = max(0, cut - ctx)
    tail = df.iloc[lo:].reset_index(drop=True)
    second = _run(tail, dirs[lo:], resume=first["state"], start_at=cut - lo)
    assert second["trades"] == whole["trades"]
    assert second["wins"] == whole["wins"]
    assert second["profit"] == pytest.approx(whole["profit"], abs=0.01)
    assert second["max_dd"] == pytest.approx(whole["max_dd"], abs=0.01)
    assert second["monthly"] == whole["monthly"]


def test_a_position_open_at_the_boundary_is_carried_not_closed():
    """The bug that made a refresh read 912 trades instead of 76: a carried
    trade must be continued once, not re-entered on every following bar."""
    import pandas as pd
    n = 900
    # dead flat after the entry, so neither barrier can ever fire
    df = pd.DataFrame({"Date": pd.date_range("2026-01-01", periods=n, freq="h"),
                       "Open": [100.0] * n, "High": [100.0] * n,
                       "Low": [100.0] * n, "Close": [100.0] * n})
    dirs = [0] * n
    dirs[100] = 1
    first = _run(df.iloc[:200], dirs[:200], resume={})
    assert first["trades"] == 0, "the trade has not closed yet"
    assert first["state"]["open"], "so it must be handed on as open"
    tail = df.iloc[100:].reset_index(drop=True)
    second = _run(tail, dirs[100:], resume=first["state"], start_at=100)
    assert second["trades"] <= 1, "a carried trade must not re-enter each bar"


def test_funding_of_a_carried_trade_starts_at_its_own_entry():
    df = _bars()
    dirs = [0] * len(df)
    dirs[50] = 1
    ms = int(df["Date"].iloc[0].value // 1_000_000)
    hour = 3_600_000
    funding = [{"settle_ms": ms + 60 * hour, "rate": 0.01},
               {"settle_ms": ms + 200 * hour, "rate": 0.01}]
    whole = _run(df, dirs, resume={}, funding=funding)
    first = _run(df.iloc[:300], dirs[:300], resume={}, funding=funding)
    tail = df.iloc[100:].reset_index(drop=True)
    second = _run(tail, dirs[100:], resume=first["state"], start_at=200,
                  funding=funding)
    assert second["funding_total"] == pytest.approx(whole["funding_total"],
                                                    abs=1e-6)


def test_state_without_rows_is_re_measured_not_skipped():
    src = open("tradingagents/market_sweep.py").read()
    assert "not pair_rows(coin, tf)" in src
    assert "states, last_ms = {}, 0" in src


def test_the_tab_exists_and_is_wired():
    """Backtest 2 replaced the V1 Back Test page (operator, 2026-08-20).
    The sweep ENGINE stays — UPDATE BACKTEST continues through run_pair —
    but the old page must be gone, not half-wired."""
    import app

    assert "Backtest 2" in app.PAGES
    assert "Back Test" not in app.PAGES
    assert hasattr(app, "render_backtest2_tab")
    assert not hasattr(app, "render_backtest_tab")
    src = open("app.py").read()
    assert 'page == "Backtest 2"' in src
    assert 'page == "Back Test"' not in src


def test_the_store_keeps_losing_rows_too(monkeypatch, tmp_path):
    """"i want everything stored" — a loser is a measurement, not noise. The
    trade floor still applies; profitability must not."""
    src = open("tradingagents/market_sweep.py").read()
    assert 'r["profit"] <= 0' not in src, \
        "run_pair still throws away losing rows"
    assert "MIN_TRADES" in src, "the trade floor must survive"


def test_pair_writes_hold_an_exclusive_lock(tmp_path, monkeypatch):
    """BACKTEST and UPDATE can run at once; without a lock they interleave
    read-modify-write on the same pair files and one side's rows vanish."""
    import json

    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    locked_during_write = []

    real_locked = msw._pair_lock

    def spy(coin, tf):
        cm = real_locked(coin, tf)

        class Spy:
            def __enter__(self):
                self._inner = cm.__enter__()
                locked_during_write.append("enter")
                return self._inner

            def __exit__(self, *a):
                locked_during_write.append("exit")
                return cm.__exit__(*a)

        return Spy()

    monkeypatch.setattr(msw, "_pair_lock", spy)
    msw.save_pair_rows("APEX", "1h", [{"coin": "APEX"}])
    assert locked_during_write == ["enter", "exit"]
    assert json.loads((tmp_path / "rows" / "APEX-1h.json").read_text())


def test_the_lock_is_per_pair_and_blocks_a_second_writer(tmp_path,
                                                         monkeypatch):
    import threading
    import time as _t

    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    order = []

    def slow_writer():
        with msw._pair_lock("APEX", "1h"):
            order.append("A-in")
            _t.sleep(0.4)
            order.append("A-out")

    def fast_writer():
        _t.sleep(0.1)
        with msw._pair_lock("APEX", "1h"):
            order.append("B-in")

    a = threading.Thread(target=slow_writer)
    b = threading.Thread(target=fast_writer)
    a.start(); b.start(); a.join(); b.join()
    assert order == ["A-in", "A-out", "B-in"], \
        "the second writer must wait for the first"


def test_storage_by_coin_sums_every_store_per_pair(tmp_path, monkeypatch):
    """"show me total size for bitcoin" — candles + rows + states, per
    (coin, timeframe), in bytes that sum per coin."""
    from tradingagents import parquet_store as pqs

    monkeypatch.setattr(msw, "CANDLES", tmp_path / "candles")
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    monkeypatch.setattr(pqs, "CANDLES", tmp_path / "pq")
    for d in ("candles", "rows", "state", "pq"):
        (tmp_path / d).mkdir()
    (tmp_path / "candles" / "BTC_USDT-15m.json").write_bytes(b"x" * 1000)
    (tmp_path / "pq" / "BTC_USDT-15m.parquet").write_bytes(b"x" * 500)
    (tmp_path / "rows" / "BTC-15m.json").write_bytes(b"x" * 300)
    (tmp_path / "state" / "BTC-15m.json").write_bytes(b"x" * 200)
    (tmp_path / "candles" / "BTC_USDT-1h.json").write_bytes(b"x" * 100)
    (tmp_path / "rows" / "PI-1h.json").write_bytes(b"x" * 50)

    rows = msw.storage_by_coin()
    btc15 = next(r for r in rows if r["coin"] == "BTC" and r["tf"] == "15m")
    assert btc15["candles"] == 1500, "json cache AND parquet copy both count"
    assert btc15["rows"] == 300 and btc15["states"] == 200
    assert btc15["total"] == 2000
    btc = [r for r in rows if r["coin"] == "BTC"]
    assert sum(r["total"] for r in btc) == 2100, "coin total sums its tfs"
    assert next(r for r in rows if r["coin"] == "PI")["total"] == 50


def test_coverage_carries_raw_epochs_not_only_display_dates(tmp_path,
                                                            monkeypatch):
    """The gaps route re-parsed the display string ("Aug 21, 2026 3:00AM")
    with an ISO format, failed on all 4,899 rows, and reported zero pairs
    behind. Callers that MEASURE need the epoch."""
    import json

    from tradingagents import market_sweep as msw
    monkeypatch.setattr(msw, "CANDLES", tmp_path)
    (tmp_path / "APEX_USDT-1h.json").write_text(json.dumps({
        "t": [1_787_000_000_000, 1_787_003_600_000],
        "o": [1, 1], "h": [1, 1], "l": [1, 1], "c": [1, 1]}))
    row = msw.candle_coverage()[0]
    assert row["last_ms"] == 1_787_003_600_000
    assert row["first_ms"] == 1_787_000_000_000
    assert "," in row["last"], "the display string stays too"


def test_the_candle_index_only_rereads_files_that_changed(tmp_path,
                                                          monkeypatch):
    """Opening all 4,899 candle files to learn their last bar took 30s and
    timed out the UI's proxy. The index is keyed by mtime."""
    import json

    from tradingagents import market_sweep as msw
    monkeypatch.setattr(msw, "CANDLES", tmp_path)
    monkeypatch.setattr(msw, "INDEX_PATH", tmp_path / "candle_index.json")
    monkeypatch.setattr(msw, "_paths", lambda: None)
    f = tmp_path / "APEX_USDT-1h.json"
    f.write_text(json.dumps({"t": [1_787_000_000_000, 1_787_003_600_000]}))
    first = msw.candle_index()
    assert first["APEX_USDT-1h"]["last_ms"] == 1_787_003_600_000
    assert first["APEX_USDT-1h"]["bars"] == 2

    reads = []
    real = type(f).read_text
    def counted(self, *a, **kw):
        if self.name.endswith("-1h.json"):
            reads.append(self.name)
        return real(self, *a, **kw)
    monkeypatch.setattr(type(f), "read_text", counted)
    msw.candle_index()
    assert reads == [], "an unchanged file must not be reopened"

    # a rewrite in the SAME SECOND must still be noticed — the index keys on
    # mtime_ns and size, because a second-resolution check is what let stale
    # .pyc files pass three times in this repo
    f.write_text(json.dumps({"t": [1_787_000_000_000, 1_787_007_200_000,
                                   1_787_010_800_000]}))
    got = msw.candle_index()
    assert got["APEX_USDT-1h"]["last_ms"] == 1_787_010_800_000
    assert got["APEX_USDT-1h"]["bars"] == 3
    assert reads, "a changed file must be re-read"


def test_scan_false_reads_the_index_and_opens_nothing(tmp_path, monkeypatch):
    """An HTTP handler must not scan: a download rewrites candle files
    constantly, and even an incremental scan then outlasts the proxy."""
    import json

    from tradingagents import market_sweep as msw
    monkeypatch.setattr(msw, "CANDLES", tmp_path)
    monkeypatch.setattr(msw, "INDEX_PATH", tmp_path / "candle_index.json")
    monkeypatch.setattr(msw, "_paths", lambda: None)
    (tmp_path / "candle_index.json").write_text(json.dumps({
        "APEX_USDT-1h": {"mtime": 1, "size": 2, "symbol": "APEX_USDT",
                          "timeframe": "1h", "bars": 9,
                          "first_ms": 1, "last_ms": 2}}))
    # a pair on disk that the index has never seen
    (tmp_path / "NEW_USDT-4h.json").write_text(json.dumps({"t": [1, 2, 3]}))
    got = msw.candle_index(scan=False)
    assert list(got) == ["APEX_USDT-1h"], "scan=False must not discover files"
    # a scan reflects the DISK: it finds the new pair and drops the indexed
    # one whose file is gone, so a deleted store never lingers in the readout
    scanned = msw.candle_index(scan=True)
    assert list(scanned) == ["NEW_USDT-4h"]
    assert scanned["NEW_USDT-4h"]["bars"] == 3


# --- the cores panel ------------------------------------------------------
# "why is core 3 and 4 not working?" — they were. The slot was the TASK's
# index (i % n_workers), so a finished task's last line sat on screen as an
# idle core, and two in-flight tasks sharing an index overwrote each other.

def test_a_worker_publishes_under_its_own_pid(tmp_path, monkeypatch):
    import os

    from tradingagents import market_sweep as msw
    monkeypatch.setattr(msw, "WORKERS", tmp_path)
    msw.worker_write(pair="APEX 1h", pct=12.34, state="running")
    files = list(tmp_path.glob("w*.json"))
    assert len(files) == 1 and str(os.getpid()) in files[0].name
    row = msw.worker_read()[0]
    assert row["pid"] == os.getpid() and row["pct"] == 12.34
    assert row["core"] == 0, "a display index is assigned on read"


def test_a_line_that_stopped_being_written_is_dropped(tmp_path, monkeypatch):
    """A finished task's last line read as a core stuck on 'done'."""
    import json
    import os

    from tradingagents import market_sweep as msw
    monkeypatch.setattr(msw, "WORKERS", tmp_path)
    stale = tmp_path / "w999999.json"
    stale.write_text(json.dumps({"pid": os.getpid(), "pair": "OLD 4h",
                                 "state": "done", "pct": 100,
                                 "updated": 0}))         # 1970
    msw.worker_write(pair="LIVE 1h", pct=5.0, state="running")
    rows = msw.worker_read()
    assert [r["pair"] for r in rows] == ["LIVE 1h"]
    assert not stale.exists(), "the stale file is cleaned up, not just hidden"


def test_a_dead_worker_is_dropped_even_if_recently_written(tmp_path,
                                                           monkeypatch):
    import json
    import time

    from tradingagents import market_sweep as msw
    monkeypatch.setattr(msw, "WORKERS", tmp_path)
    (tmp_path / "w424242.json").write_text(json.dumps({
        "pid": 424242, "pair": "GHOST 1h", "state": "running",
        "pct": 50.0, "updated": time.time()}))
    assert msw.worker_read() == []


def test_the_published_percentage_carries_two_decimals(tmp_path, monkeypatch):
    """A core grinding 17,820 combinations moves less than a whole percent
    between publishes, so a rounded figure looked frozen."""
    from tradingagents import market_sweep as msw
    monkeypatch.setattr(msw, "WORKERS", tmp_path)
    msw.worker_write(pair="BTC 15m", done=3280, total=17820,
                     pct=round(100 * 3280 / 17820, 2), state="running")
    assert msw.worker_read()[0]["pct"] == 18.41
