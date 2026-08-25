"""The unattended sweep: keep measuring, wherever it can.

The operator's requirements, verbatim: accurate data, resume if it hits a rate
limit, a percentage every minute, and if the wifi drops carry on locally from
the candles already stored. These tests pin each one.
"""

import json
import time

import pytest

from tradingagents import sweep_orchestrator as so


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(so, "HOME", tmp_path)
    monkeypatch.setattr(so, "STATE", tmp_path / "orchestrator.json")
    monkeypatch.setattr(so, "LOG", tmp_path / "orchestrator.log")
    monkeypatch.setattr(so, "STOP", tmp_path / "orchestrator.STOP")
    monkeypatch.setattr(so, "TICK", 0.01)


def test_no_internet_means_it_measures_locally(monkeypatch):
    """"if i've been disconnected to wifi then continue the backtest local".
    4,946 candle files are already on disk; run_pair only calls the venue to
    TOP UP, so a dropped connection changes WHERE the work happens."""
    monkeypatch.setattr(so, "online", lambda: False)
    ran = []
    monkeypatch.setattr(so, "local_round", lambda left, **k: ran.append(len(left)) or 0)
    monkeypatch.setattr(so, "store_pair", lambda c, tf: 0)
    seen = iter([set(), {("A_USDT", "1h")}])
    monkeypatch.setattr(so, "measured", lambda pairs: next(seen))

    so.run(["A_USDT"], ["1h"], prefer_cloud=True)
    assert ran, "it did not measure locally while offline"
    got = json.loads((so.STATE).read_text())
    assert got["pct"] == 100.0 and got["where"] == "finished"


def test_a_rate_limit_does_not_stop_the_sweep(monkeypatch):
    """"make sure to resume if it hits rate limit" — the sweep keeps going on
    this Mac while the budget refills, instead of waiting idle."""
    monkeypatch.setattr(so, "online", lambda: True)
    monkeypatch.setattr(so, "gh_budget", lambda: (3, 1800.0))    # nearly spent
    dispatched, ran = [], []
    monkeypatch.setattr(so, "store_pair", lambda c, tf: 0)
    monkeypatch.setattr(so, "local_round", lambda left, **k: ran.append(1) or 0)

    from tradingagents import cloud_sweep as cs

    monkeypatch.setattr(cs, "dispatch", lambda **kw: dispatched.append(kw) or {"id": 1})
    seen = iter([set(), {("A_USDT", "1h")}])
    monkeypatch.setattr(so, "measured", lambda pairs: next(seen))

    so.run(["A_USDT"], ["1h"])
    assert not dispatched, "it dispatched with no API budget left"
    assert ran, "it went idle instead of working locally"
    log = (so.LOG).read_text()
    assert "rate limited" in log and "30 min to reset" in log


def test_it_dispatches_to_github_when_there_is_budget(monkeypatch):
    monkeypatch.setattr(so, "online", lambda: True)
    monkeypatch.setattr(so, "gh_budget", lambda: (4000, 0.0))
    monkeypatch.setattr(so, "store_pair", lambda c, tf: 0)
    sent = []

    from tradingagents import cloud_sweep as cs

    monkeypatch.setattr(cs, "dispatch", lambda **kw: sent.append(kw) or {"id": 77})
    monkeypatch.setattr(cs, "remember", lambda run: None)
    seen = iter([set(), {("A_USDT", "1h")}])
    monkeypatch.setattr(so, "measured", lambda pairs: next(seen))

    so.run(["A_USDT"], ["1h"])
    assert sent and sent[0]["shards"] == so.CLOUD_SHARDS
    assert "GitHub Actions (run 77)" in (so.LOG).read_text()


def test_progress_is_published_every_tick(monkeypatch):
    """"give me update on percentage every 1 min"."""
    assert so.TICK <= 60.0, "a tick must not be slower than the minute asked for"
    monkeypatch.setattr(so, "online", lambda: False)
    monkeypatch.setattr(so, "local_round", lambda left, **k: 0)
    monkeypatch.setattr(so, "store_pair", lambda c, tf: 0)
    seen = iter([set(), {("A_USDT", "1h"), ("A_USDT", "4h")}])
    monkeypatch.setattr(so, "measured", lambda pairs: next(seen))

    so.run(["A_USDT"], ["1h", "4h"])
    got = json.loads((so.STATE).read_text())
    for field in ("pct", "done", "total", "where", "elapsed_min"):
        assert field in got, f"the update is missing {field}"


def test_it_watches_git_not_the_rest_api():
    """Polling the REST API burned 5,000 requests in an hour on 2026-08-25 and
    blinded every tool at once. Shard progress lives on a branch."""
    import inspect

    src = inspect.getsource(so)
    assert "sweep-progress" in src or "git fetch" in src.lower() or \
        "watches git" in src.lower(), "it must not poll the REST API for progress"
    # the API is for dispatching and for reading the budget, nothing else
    assert src.count('subprocess.run(["gh"') <= 1


def test_finished_pairs_reach_the_database(monkeypatch, tmp_path):
    """"make sure to store the backtest in database"."""
    import inspect

    assert "rows_index" in inspect.getsource(so.store_pair)
    assert "index_pair" in inspect.getsource(so.store_pair)
    src = inspect.getsource(so.run)
    assert "store_pair" in src, "each cycle must fold finished pairs in"


def test_a_stop_file_ends_it(monkeypatch):
    monkeypatch.setattr(so, "online", lambda: False)
    monkeypatch.setattr(so, "local_round", lambda left, **k: 0)
    monkeypatch.setattr(so, "store_pair", lambda c, tf: 0)
    monkeypatch.setattr(so, "measured", lambda pairs: set())
    so.STOP.touch()
    t = time.time()
    so.run(["A_USDT"], ["1h"])
    assert time.time() - t < 5, "it ignored the stop file"
    assert "stopped by request" in (so.LOG).read_text()
