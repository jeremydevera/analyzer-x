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
