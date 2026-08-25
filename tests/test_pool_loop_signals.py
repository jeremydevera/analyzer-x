"""An exception raised inside grid_from_store's pool loop must PROPAGATE.

The loop's `except Exception` existed for one case -- the pool could not start
(spawn with no importable __main__) -- and fell back to measuring in-process.
But it wrapped the WHOLE loop, so anything raised from the per-pair progress
callback was read as "pool could not start": `_StopRequested` (the STOP
button), `_HandOff` (switch to GitHub), `_LowDisk`, and on 2026-08-25 a
Windows PermissionError from the progress file. Each time the code set
`measured, done = [], 0` and left the `with` block -- whose __exit__ waits for
EVERY pending pair -- so the job ran to the end with `done` frozen (64 of
4,985 for twenty minutes on the PC) and no button could stop it.
"""
import concurrent.futures as cf

import pytest

from tradingagents import backtest_report as br, market_sweep as msw


class Boom(Exception):
    pass


class FakePool:
    """Runs each submission at once on the calling thread, real Futures."""

    def __init__(self, *a, **kw):
        self.shutdown_calls = 0

    def submit(self, fn, *a, **kw):
        fut = cf.Future()
        try:
            fut.set_result(fn(*a, **kw))
        except Exception as exc:          # noqa: BLE001 - mirrors a worker raising
            fut.set_exception(exc)
        return fut

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.shutdown_calls += 1
        return False


@pytest.fixture
def quiet_store(tmp_path, monkeypatch):
    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "CANDLES", tmp_path / "candles")
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "completed_pairs", lambda pairs: set())
    monkeypatch.setattr(msw, "worker_clear", lambda: None)
    monkeypatch.setattr(msw, "worker_read", lambda: [])
    monkeypatch.setattr(msw, "be_polite", lambda: None)
    monkeypatch.setattr(msw, "run_pair",
                        lambda sym, tf, **kw: {"coin": sym.replace("_USDT", ""), "tf": tf,
                                               "rows": [], "why": "no new bars",
                                               "bars": 1, "days": 1, "rt": 0.0,
                                               "liq": 0.0, "fee": 0.0})
    monkeypatch.setattr(cf, "ProcessPoolExecutor", FakePool)


def test_a_signal_from_the_progress_callback_escapes_the_pool_loop(quiet_store):
    def prog(msg, frac, done=None, total=None):
        if "done (" in msg:
            raise Boom(msg)                 # what _StopRequested / _HandOff do

    with pytest.raises(Boom):
        br.grid_from_store(["APEX_USDT", "PI_USDT"], ["1h"], progress=prog, workers=2)


def test_a_worker_error_from_the_progress_file_is_not_a_pool_start_failure(quiet_store, monkeypatch):
    """The Windows case: PermissionError while publishing progress. It is not
    swallowed into a silent in-process re-run of 4,985 pairs."""
    def prog(msg, frac, done=None, total=None):
        if "done (" in msg:
            raise PermissionError(32, "The process cannot access the file")

    with pytest.raises(PermissionError):
        br.grid_from_store(["APEX_USDT", "PI_USDT"], ["1h"], progress=prog, workers=2)


def test_only_a_pool_that_cannot_start_falls_back_to_in_process(quiet_store, monkeypatch):
    class NoPool(FakePool):
        def submit(self, fn, *a, **kw):
            raise cf.process.BrokenProcessPool("spawn needs an importable __main__")

    monkeypatch.setattr(cf, "ProcessPoolExecutor", NoPool)
    calls = []
    got = br.grid_from_store(["APEX_USDT"], ["1h"], workers=2,
                             progress=lambda *a, **k: calls.append(a[0]))
    assert got is not None
    assert any("reading the store" in m for m in calls), "fell back to in-process measuring"
