"""Backtest v2 fetches the minutes it needs — no trip to the Candles screen.

Operator, `Sep 18, 2026`: *"can we join candle v2 and backtest v2? instead of
me manually downloading the candles in candles v2, when i click update this
backtest, it should automatically download the candles"*.

What it was: `market_sweep.run_pair`'s v2 branch read the 1-minute cache and,
finding it short or absent, returned

    "no 1m candles for XPIN_USDT — download them on Candles v2 first"

so measuring one row meant leaving the screen, downloading a pair by hand, and
coming back. v1 never had that step — its branch is `refresh_candles`, which
fetches on the way in — so the two versions now differ only in WHICH frame
they fetch, not in whether they fetch at all.

And v2 had no row button at all: it was gated `store === "v1"`, and the route
looked every id up in v1's index. `pairbt_v2` is the same `_run_pairbt`
launched with `stores.V2.env_for()`, so one function serves both stores.

Measured on the operator's own machine, `Sep 18, 2026`: 1,003 one-minute
caches, 82,758 v2 rows, and both XPIN_USDT and ARKM_USDT sitting at 44,000
bars that stopped the previous day — a press had nothing that would move them.
"""
from __future__ import annotations

import inspect

import pandas as pd
import pytest

from tradingagents import db_jobs as dj, market_sweep as msw

M = 60_000
T0 = 1_756_857_600_000


def _minutes(n: int) -> pd.DataFrame:
    t = [T0 + i * M for i in range(n)]
    return pd.DataFrame({
        "Date": pd.to_datetime(t, unit="ms"),
        "Open": [1.0] * n, "High": [1.05] * n, "Low": [0.95] * n,
        "Close": [1.0] * n, "Volume": [10.0] * n})


@pytest.fixture
def v2(monkeypatch):
    """`run_pair` in Backtest v2's shape, with the venue faked."""
    monkeypatch.setattr(msw, "FINE_TF", "1m")
    calls: list = []

    def fake_refresh(symbol, tf, *, days=365):
        calls.append((symbol, tf, days))
        return _minutes(5_000), 1_234, "delta"

    monkeypatch.setattr(msw, "refresh_candles", fake_refresh)
    monkeypatch.setattr(msw, "cached_candles",
                        lambda *a, **k: pytest.fail(
                            "v2 read the cache instead of fetching"))
    return calls


# ------------------------------------------------ 1. it fetches, per store
def test_the_v2_branch_downloads_the_minutes_it_needs(v2):
    """The whole ask. It used to refuse and name the Candles screen."""
    src = inspect.getsource(msw.run_pair)
    head = src[src.index("if FINE_TF:"):src.index("else:\n        df, added")]
    assert "refresh_candles(symbol, FINE_TF" in head, \
        "the v2 branch still only reads the cache"
    # the CODE, not the comment above it that quotes the old message — a grep
    # over prose is how a guard passes while the fault is still in place
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.strip().startswith("#"))
    assert "download them on Candles v2 first" not in code, \
        "the refusal that sent the operator to another screen is still here"


def test_it_asks_for_the_MINUTE_frame_not_the_rows_frame(v2):
    """v2 stores `SYM-1m` and rebuilds 15m/30m/1h/4h/1d from it. Fetching the
    row's own frame would download bars this store never reads."""
    src = inspect.getsource(msw.run_pair)
    assert "refresh_candles(symbol, FINE_TF" in src
    assert "refresh_candles(symbol, tf" not in src.split("else:")[0]


def test_v1_is_untouched():
    """v1's branch is the one that always fetched; this change must not have
    moved it, or every v1 sweep changes behaviour too."""
    src = inspect.getsource(msw.run_pair)
    assert "df, added, source = refresh_candles(symbol, tf, days=days)" in src


def test_a_venue_failure_is_NAMED_not_a_silent_empty_result(v2, monkeypatch):
    """An empty row list reads as "this pair has no edge". A download that
    failed has to say so, so the pool can redo the pair (PAIR_RETRIES)."""
    def boom(symbol, tf, *, days=365):
        raise TimeoutError("read timed out")

    monkeypatch.setattr(msw, "refresh_candles", boom)
    got = msw.run_pair("XPIN_USDT", "1h", days=30)
    assert got["rows"] == []
    assert "download" in got["why"] and "timed out" in got["why"], got["why"]


def test_too_few_minutes_says_what_the_venue_actually_served(v2, monkeypatch):
    monkeypatch.setattr(msw, "refresh_candles",
                        lambda s, tf, *, days=365: (_minutes(3), 3, "fetch"))
    got = msw.run_pair("XPIN_USDT", "1h", days=30)
    assert got["rows"] == []
    assert "served 3 1m bars" in got["why"], got["why"]


# --------------------------------------------- 2. the button exists on v2
def test_there_is_a_pairbt_job_for_each_store():
    assert "pairbt" in dj.FILES and "pairbt_v2" in dj.FILES
    for f in ("progress", "spec", "pid", "stop"):
        assert dj.FILES["pairbt"][f] != dj.FILES["pairbt_v2"][f], (
            f"the two stores share their {f} file, so a v2 press would "
            f"report the v1 job's line — the shape of RCA-2026-09-18-E")


def test_the_v2_job_is_the_same_function_in_the_v2_environment():
    """One `_run_pairbt`, two environments. A second copy would drift."""
    src = inspect.getsource(dj)
    assert 'elif kind in ("pairbt", "pairbt_v2"):' in src
    assert "_run_pairbt(spec, kind)" in src
    assert "def _run_pairbt(spec: dict, kind: str" in src
    assert 'f = FILES[kind]' in src, "the job still writes v1's files"


def test_a_one_pair_press_is_never_refused_by_a_running_sweep():
    """RCA-2026-09-18-L: UPDATE answered `409 btupdate_v2 is running` for the
    whole 21 hours of a v2 sweep. Neither press kind is a disk job."""
    assert "pairbt" not in dj._DISK_JOBS
    assert "pairbt_v2" not in dj._DISK_JOBS
    assert dj.disk_holder("pairbt_v2") == ""


def test_the_supervisor_does_not_restart_a_press():
    """A press is a person watching. Only sweeps and downloads are resumed."""
    from tradingagents import api

    src = inspect.getsource(api)
    i = src.index('for kind in ("backtest", "download", "btupdate"')
    block = src[i:i + 200]
    assert "pairbt" not in block


def test_the_eta_rate_is_remembered_per_store():
    """v1's index is 41.94 GB and v2's is its own size; one shared rate file
    would quote the wrong machine speed on every press."""
    assert dj._rate_file("pairbt") != dj._rate_file("pairbt_v2")
    src = inspect.getsource(dj)
    assert "_index_rate(kind)" in src
    assert "_remember_index_rate(_ix_total, time.time() - _ix_t0, kind)" in src


def test_the_job_reads_the_span_of_the_file_this_store_keeps():
    """v2 stores only `SYM-1m`, so looking up `SYM-15m` always missed and
    `days` fell to 1 on every v2 press."""
    src = inspect.getsource(dj._run_pairbt)
    assert "_frame = msw.FINE_TF or tf" in src
    assert 'get(f"{sym}-{_frame}")' in src


# ------------------------------------------------- 3. the route and screen
def test_the_route_looks_the_row_up_in_its_OWN_index():
    """v2 ids never collide with v1's, but the ROW only exists in its own
    table — a v2 id in v1's index answers 404 and reads as "row is gone"."""
    from tradingagents import api

    src = inspect.getsource(api.strategy_row_update)
    assert 'def strategy_row_update(row_id: str, store: str = "v1")' in \
        inspect.getsource(api)
    assert 'kind = "pairbt_v2" if _v2 else "pairbt"' in src
    assert "ri.using_db(_db)" in src
    assert "dj.status(kind)" in src and "dj.start(kind," in src


def test_the_button_is_no_longer_v1_only():
    p = open("webapp/src/components/backtest/StrategiesPanel.tsx",
             encoding="utf-8").read()
    assert '{store === "v1" && open?.id && (' not in p, \
        "Backtest v2 still has no UPDATE button"
    assert "{open?.id && (" in p
    assert "PAIR_JOB(store)" in p, "the screen polls one store's job for both"
    assert 'strategyRowUpdate(rowId, store === "v2" ? "v2" : "v1")' in p


def test_the_screen_still_only_speaks_for_ITS_row():
    """RCA-2026-09-18-M must survive this change."""
    p = open("webapp/src/components/backtest/StrategiesPanel.tsx",
             encoding="utf-8").read()
    assert "const jobIsThisRow" in p
    assert "pairJob.pair === `${open.coin} ${open.tf}`" in p


def test_a_v2_pair_measured_on_this_pc_pays_each_minutes_book(v2, monkeypatch, tmp_path):
    """Oct 10, 2026 (RCA-2026-10-10-K): UPDATE THIS BACKTEST measures one v2
    pair on this PC through `run_pair`, and on Gate it passed no order book —
    a row re-measured here took every trade the runner's cost check would
    refuse, beside GitHub's rows that refused them. It reads the same book,
    measures the pair in full (refusal counts do not travel in a saved
    position), and stamps every row with the cost check's own counts."""
    import tradingagents.auto_trader as at
    from tradingagents import cost_store
    from tradingagents.dataflows import exchange as fx

    monkeypatch.setenv("TA_VENUE", "gate")
    for name in ("HOME", "STATES", "ROWDIR", "COSTS"):
        monkeypatch.setattr(msw, name, tmp_path / name.lower())
        (tmp_path / name.lower()).mkdir()
    monkeypatch.setattr(fx, "funding_history", lambda *a, **k: [])
    monkeypatch.setattr(fx, "liquidation_move_pct", lambda *a, **k: 4.5)
    monkeypatch.setattr(fx, "book_cost", lambda *a, **k: {"slippage": 0.0003})
    monkeypatch.setattr(at, "taker_fee", lambda *a, **k: 0.00075)
    monkeypatch.setattr(msw, "charge_cost", lambda *a, **k: (0.0003, []))
    monkeypatch.setattr(msw, "deployed_combos", lambda: set())
    asked, seen = [], []
    monkeypatch.setattr(cost_store, "book_for",
                        lambda sym, s, e, **k: asked.append(sym) or cost_store.empty())
    real = at.backtest_strategy

    def spy(*a, **k):
        seen.append(k.get("book"))
        return real(*a, **k)
    monkeypatch.setattr(at, "backtest_strategy", spy)
    # on Gate the frame and exit bars come the shard's way (RCA-2026-10-10-L)
    import numpy as np

    import pandas as pd

    now = pd.Timestamp.now("UTC").tz_localize(None).floor("h")
    n = 24 * 40
    px = 100 + np.sin(np.arange(n) / 7.0) * 3
    frame = pd.DataFrame({"Date": [now - pd.Timedelta(hours=n - k) for k in range(n)],
                          "Open": px, "High": px * 1.01, "Low": px * 0.99,
                          "Close": px, "Volume": 1.0})
    no_fine = (np.zeros(0, "int64"), np.zeros(0), np.zeros(0))
    monkeypatch.setattr(msw, "gate_v2_bars", lambda sym, tf: (frame, no_fine, 0))
    got = msw.run_pair("TEST_USDT", "1h", signals=["mom6"], days=30)
    assert asked == ["TEST_USDT"], "the book is read once for the pair"
    assert seen and all(b is not None for b in seen)
    for r in got.get("rows") or []:
        assert {"gate_blocked", "cost_unmeasured", "book_to"} <= set(r)
        assert r["venue"] == "gate"


def test_gate_v2_bars_reads_the_frames_own_candles_and_the_finest_bars_once(monkeypatch):
    """The shard's way on this PC (RCA-2026-10-10-L): `fx.klines` for the
    frame, `fine_bars` for the exits — read once per coin for five minutes,
    so a page of rows does not ask Gate for the same minutes ten times."""
    import numpy as np

    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br
    from tradingagents.dataflows import exchange as fx

    frame = msw.bars_from_1m(_minutes(5_000), "1h")
    monkeypatch.setattr(fx, "klines", lambda sym, iv, n: frame)
    monkeypatch.setattr(at, "_closed_bars", lambda d, bs: d)
    calls = []

    def fine_bars(sym, start, end=None, *, fx=None):
        calls.append(sym)
        return np.zeros(0, "int64"), np.zeros(0), np.zeros(0), 722
    monkeypatch.setattr(br, "fine_bars", fine_bars)
    msw._V2_FINE_MEMO.clear()
    df, fine, n5 = msw.gate_v2_bars("TEST_USDT", "1h")
    msw.gate_v2_bars("TEST_USDT", "4h")
    assert df is frame and n5 == 722 and calls == ["TEST_USDT"]


def test_on_gate_one_pair_is_measured_over_githubs_window_with_the_rows_recent_counts(
        v2, monkeypatch, tmp_path):
    """RCA-2026-10-10-L, second half: `gate_v2_bars` hands back a year of 1h
    candles, and run_pair measured all of it — rows from Aug 2025 under a
    30-day v2 store — and wrote no t15/t1..t4, so a pair re-measured here
    vanished from the rooms that switch on by them. The shard's window
    (DAYS + 300 lead-in bars, trades only after the lead-in) and its recent
    counts, here too."""
    import numpy as np
    import pandas as pd

    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br, cost_store
    from tradingagents.dataflows import exchange as fx

    monkeypatch.setenv("TA_VENUE", "gate")
    for name in ("HOME", "STATES", "ROWDIR", "COSTS"):
        monkeypatch.setattr(msw, name, tmp_path / name.lower())
        (tmp_path / name.lower()).mkdir()
    monkeypatch.setattr(fx, "funding_history", lambda *a, **k: [])
    monkeypatch.setattr(fx, "liquidation_move_pct", lambda *a, **k: 4.5)
    monkeypatch.setattr(fx, "book_cost", lambda *a, **k: {"slippage": 0.0003})
    monkeypatch.setattr(at, "taker_fee", lambda *a, **k: 0.00075)
    monkeypatch.setattr(msw, "charge_cost", lambda *a, **k: (0.0003, []))
    monkeypatch.setattr(msw, "deployed_combos", lambda: set())
    monkeypatch.setattr(cost_store, "book_for", lambda *a, **k: cost_store.empty())
    now = pd.Timestamp.now("UTC").tz_localize(None).floor("h")
    n = 24 * 400
    dates = [now - pd.Timedelta(hours=n - k) for k in range(n)]
    px = 100 + np.sin(np.arange(n) / 7.0) * 3
    year = pd.DataFrame({"Date": dates, "Open": px, "High": px * 1.01,
                         "Low": px * 0.99, "Close": px, "Volume": 1.0})
    no_fine = (np.zeros(0, "int64"), np.zeros(0), np.zeros(0))
    monkeypatch.setattr(msw, "gate_v2_bars", lambda sym, tf: (year, no_fine, 0))
    seen = []
    real = at.backtest_strategy

    def spy(key, df, *a, **k):
        seen.append((len(df), k.get("start_at"), k.get("recent_windows")))
        # a trade still open at the window's end is COUNTED, as GitHub counts
        # it and the trade list shows it (BTC 1h mom6: the row said 72 trades,
        # its list 73 with the open one) — no resume on Gate's full measure
        assert k.get("resume") is None, "Gate v2 is measured in full, never resumed"
        return real(key, df, *a, **k)
    monkeypatch.setattr(at, "backtest_strategy", spy)
    got = msw.run_pair("TEST_USDT", "1h", signals=["mom6"], days=30)
    n_df, start_at, recents = seen[0]
    assert start_at == 300, "no trade inside the lead-in"
    assert 30 * 24 - 1 <= n_df - 300 <= 30 * 24, \
        "the window and its lead-in, never the year"
    assert recents and set(recents) == set(br.SHORT_DAYS)
    rows = got["rows"]
    assert rows, "a sine wave trades"
    for r in rows:
        assert 30 * 24 - 1 <= r["bars"] <= 30 * 24 and r["days"] <= 30
        want = ["t15", "w15", "p15"] + [k for d in br.SHORT_DAYS for k in br.recent_keys(d)]
        assert list(r)[-len(want):] == want, "at the END of the row, as GitHub writes them"
