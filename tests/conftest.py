"""Shared pytest fixtures that prevent CI hangs when API keys are absent."""

# Same-second file edits can beat the .pyc mtime check, and stale bytecode
# then fails tests whose code is correct (it cost three phantom failures on
# 2026-08-20 alone). Tests never write bytecode.
import sys as _sys

_sys.dont_write_bytecode = True

import os
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def pytest_configure(config):
    for marker in ("unit", "integration", "smoke"):
        config.addinivalue_line("markers", f"{marker}: {marker}-level tests")


_API_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_CN_API_KEY",
    "ZHIPU_API_KEY",
    "ZHIPU_CN_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_CN_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
)


@pytest.fixture(autouse=True)
def _dummy_api_keys(monkeypatch):
    for env_var in _API_KEY_ENV_VARS:
        # `or` not a .get default: an env var present but empty (e.g. a key left
        # blank in a .env copied from .env.example) must still get the placeholder.
        monkeypatch.setenv(env_var, os.environ.get(env_var) or "placeholder")


@pytest.fixture(autouse=True)
def _no_real_market_db(monkeypatch, tmp_path):
    """Cut every test off from the real market database.

    The kline fetch archives bars to Neon as a side effect; without this, the
    paging tests uploaded 5,000 fake TEST_USDT candles into the PRODUCTION
    archive and then read them back as history (caught 2026-08-20). Tests
    that want a database opt in by setting the env URL themselves.
    """
    from tradingagents.dataflows import market_db as mdb
    monkeypatch.delenv(mdb.DB_URL_ENV, raising=False)
    monkeypatch.setattr(mdb, "STORE_PATH", tmp_path / "no_db_here.json")
    monkeypatch.setattr(mdb, "_ENGINE", None)
    monkeypatch.setattr(mdb, "_ENGINE_URL", None)
    monkeypatch.setattr(mdb, "_down_until", 0.0)


@pytest.fixture(autouse=True)
def _isolate_config():
    """Reset the global dataflows config before and after each test.

    ``set_config`` merges (it never clears keys absent from the override), so a
    test that sets e.g. ``tool_vendors`` would otherwise leak into later tests
    and make routing behavior order-dependent. Replace the global outright so
    every test starts from a clean DEFAULT_CONFIG.
    """
    import copy

    import tradingagents.dataflows.config as config_module
    import tradingagents.default_config as default_config

    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    yield
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


@pytest.fixture()
def mock_llm_client():
    client = MagicMock()
    client.get_llm.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.factory.create_llm_client",
        return_value=client,
    ):
        yield client


# ---------------------------------------------------------------------------
# No unit test may touch the network.
#
# 36 tests in this suite were making live HTTPS calls and passing anyway, because
# the code under test treats a failed fetch as inconclusive and falls back. That
# is worse than a red test: they passed for the wrong reason, they were flaky
# whenever an exchange was unreachable, and every full run hammered MEXC and
# twitterapi.io. Blocking the socket turns each leak into an immediate, named
# failure instead of a silent one.
#
# A test that genuinely needs a live service belongs under the `integration`
# marker, which is exempt below.
_REAL_CONNECT = socket.socket.connect


@pytest.fixture(autouse=True)
def _no_network(request):
    if request.node.get_closest_marker("integration"):
        yield
        return

    def blocked(self, address):
        raise AssertionError(
            f"{request.node.name} tried to open a network connection to "
            f"{address}. Unit tests must stub their I/O — mock the fetch, or mark "
            f"the test `@pytest.mark.integration` if it truly needs the service.")

    socket.socket.connect = blocked
    try:
        yield
    finally:
        socket.socket.connect = _REAL_CONNECT


# --------------------------------------------------------------------------
# The test suite must never touch the operator's LIVE book.
#
# Found 2026-08-19: `tests/test_exit_survives_book_change.py` builds a
# synthetic XAUT position (entry 4353.0, SL 4387.8, vol 22) and drives
# `process_symbol` through its exit path. `append_ledger` was still pointed at
# ~/.tradingagents/auto_trade_ledger.jsonl, so EVERY run of the suite wrote a
# real-looking row: `XAUT_USDT exit SL pnl -0.96 dry_run false`. Eighty-six of
# them accumulated. They are why the app showed XAUT at -$32.39 all-time and
# today's live P&L at -$63.30 when MEXC's own figures are -$1.01 and -$29.71 —
# and the daily loss limit reads exactly those rows, so a run of the tests
# could have stopped live trading.
#
# Redirect every path the auto-trader writes, for every test, always. A test
# that wants to inspect what it wrote still can: the files exist, under tmp.
# --------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _never_touch_the_live_book(tmp_path, monkeypatch):
    try:
        import tradingagents.auto_trader as at
    except Exception:                      # module not importable: nothing to do
        return
    sandbox = tmp_path / "tradingagents_state"
    sandbox.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(at, "STATE_DIR", sandbox, raising=False)
    for name, filename in (("STATE_PATH", "auto_trade_state.json"),
                           ("STATE_LOCK_PATH", "auto_trade_state.lock"),
                           ("LEDGER_PATH", "auto_trade_ledger.jsonl"),
                           ("SETTINGS_PATH", "auto_trade.json"),
                           ("LOG_PATH", "auto_trade.log"),
                           ("PID_PATH", "auto_trade.pid"),
                           ("KILL_PATH", "auto_trade.KILL"),
                           # found by the guard test on Aug 27, 2026: WANT is
                           # how the supervisor is TOLD the live runner should
                           # be running, and LOCK is what the runner holds
                           ("LOCK_PATH", "auto_trade.lock"),
                           ("WANT_PATH", "auto_trade.WANT")):
        if hasattr(at, name):
            monkeypatch.setattr(at, name, sandbox / filename)
    # The NOTIFICATION FEED is written from the same code paths, so it has to
    # be sandboxed with them. It was not, and one suite run put 30 fixture
    # trades ("PAPER LONG BTC entry 102.0", sweep_rt, ETH) into the operator's
    # real bell — the same class of mistake as the run that wrote 43 fake XAUT
    # rows into the live ledger. Any new module-level path under
    # ~/.tradingagents belongs in this list on the day it is added.
    try:
        from tradingagents import notifications as _nt

        monkeypatch.setattr(_nt, "DB_PATH", sandbox / "notifications.db")
    except Exception:
        pass
    # The DETACHED JOB FILES too. They were not sandboxed, and a test that
    # drove db_jobs._run_backtest_inner with a stub grid wrote
    # {"running": false, "rows": 0, "note": "nothing survived the trade floor"}
    # straight over the progress file of the operator's LIVE 3,960-pair sweep
    # at 00:25:26 on 2026-08-22, while seven cores were still measuring. The
    # measurements were safe; the screen said the run had finished with
    # nothing. A test must never be able to narrate a real job.
    # The sweep's HAND-OFF flag. It lives under ~/.tradingagents and the
    # WORKERS read it, so an unsandboxed test saw the operator's real request
    # and stood down mid-measurement — the run left no watermark and the
    # resume test failed on the state of their machine.
    try:
        from tradingagents import market_sweep as _msw2

        # EVERY module-level path, not just the flag. Individual tests patched
        # ROWDIR and STATES themselves, so the ones that forgot wrote into the
        # operator's real 15 GB store — and the hand-off flag let a test worker
        # read a request they had made in the UI and stand down mid-measurement.
        _sw = sandbox / "sweep"
        _sw.mkdir(parents=True, exist_ok=True)
        for _name, _leaf in (("HOME", ""), ("ROWDIR", "rows"),
                             ("STATES", "state"), ("WORKERS", "workers"),
                             ("CANDLES", "candles"),
                             ("COSTS", "costs"),
                             ("INDEX_PATH", "candle_index.json"),
                             ("HANDOFF_PATH", "db_backtest.HANDOFF"),
                             ("MANIFEST", "manifest.json"),
                             ("PIDFILE", "sweep.pid"),
                             ("PROGRESS", "progress.json"),
                             ("ROWS", "rows.jsonl")):
            if hasattr(_msw2, _name):
                monkeypatch.setattr(_msw2, _name,
                                    _sw / _leaf if _leaf else _sw)
    except Exception:
        pass
    try:
        from tradingagents import rows_index as _ri

        monkeypatch.setattr(_ri, "DB_PATH", sandbox / "rows.db")
        if hasattr(_ri, "PIDFILE"):
            monkeypatch.setattr(_ri, "PIDFILE", sandbox / "rows_index.pid")
    except Exception:
        pass
    try:
        # parquet_store was the hole this fixture's own comment warns about,
        # still open. Aug 27, 2026 8:07am: the 60-day market sweep finished at
        # 7:56am having measured 22,478,876 combinations and written its
        # snapshot to ~/.tradingagents/parquet/grids/2026-08-27-grid.parquet;
        # eleven minutes later a test that folds a grid replaced that file
        # with its own 40 fixture rows (APEX 1h, signals s0..s39). The store
        # itself survived because ROWDIR is sandboxed above; the snapshot the
        # report page points at did not, and the day's fold had to be re-run.
        from tradingagents import parquet_store as _pqs

        _pq = sandbox / "parquet"
        for _name, _leaf in (("ROOT", ""), ("CANDLES", "candles"),
                             ("GRIDS", "grids")):
            if hasattr(_pqs, _name):
                monkeypatch.setattr(_pqs, _name,
                                    _pq / _leaf if _leaf else _pq)
    except Exception:
        pass
    try:
        # parquet_store was the hole the comment above warns about, still open.
        # Aug 27, 2026 8:07am: the 60-day sweep finished at 7:56am having
        # measured 22,478,876 combinations and written its snapshot to
        # ~/.tradingagents/parquet/grids/2026-08-27-grid.parquet; eleven
        # minutes later a test that folds a grid replaced that file with 40
        # fixture rows (APEX 1h, signals s0..s39). The previous day's snapshot
        # is 338,936,957 bytes and 9,439,792 rows, for scale.
        from tradingagents import parquet_store as _pqs

        _pq = sandbox / "parquet"
        for _name, _leaf in (("ROOT", ""), ("CANDLES", "candles"),
                             ("GRIDS", "grids")):
            if hasattr(_pqs, _name):
                monkeypatch.setattr(_pqs, _name,
                                    _pq / _leaf if _leaf else _pq)
    except Exception:
        pass
    try:
        from tradingagents import db_jobs as _dj

        jobs = sandbox / "jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(_dj, "STATE_DIR", jobs, raising=False)
        monkeypatch.setattr(_dj, "FILES", {
            kind: {role: jobs / Path(path).name for role, path in roles.items()}
            for kind, roles in _dj.FILES.items()})
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_kline_disk_cache(tmp_path, monkeypatch):
    """Every test gets its own empty candle cache directory.

    Without this the cache is ``~/.tradingagents/kline_cache`` for tests too, so
    a file written by a real run — or by an earlier test in the same session —
    answers the request under test. That is exactly how a paging test that
    served 500 bars asserted against 5,000.
    """
    from tradingagents.dataflows import mexc_futures as _fx

    monkeypatch.setattr(_fx, "KLINE_DISK_DIR", tmp_path / "kline_cache")
    _fx._KLINE_CACHE.clear()
    yield
    _fx._KLINE_CACHE.clear()
