"""A failed coin is deleted and redone BY ITSELF.

Operator, 2026-08-25: *"if a coin fails, delete the backtest then redo again
the last failed job (not the whole)"*.

Two halves, and both matter:
  * DELETE -- a pair that raised part-way has already written rows and a state
    file. Retrying on top leaves one coin carrying a mixture of two runs.
  * NOT THE WHOLE -- the retry is one pair. The other 4,964 keep going.
"""

import json

import pytest

from tradingagents import market_sweep as msw


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "PROGRESS", tmp_path / "progress.json")
    monkeypatch.setattr(msw, "PIDFILE", tmp_path / "sweep.pid")
    (tmp_path / "state").mkdir()
    (tmp_path / "rows").mkdir()
    return tmp_path


def _halfway(home, coin="APEX", tf="1h"):
    """What a pair that died mid-run leaves on disk."""
    (home / "rows" / f"{coin}-{tf}.json").write_text('[{"coin":"APEX"}]')
    (home / "state" / f"{coin}-{tf}.json").write_text('{"a":1}')
    (home / "rows" / f"{coin}-{tf}.json.tmp").write_text("[")


def test_discard_deletes_the_rows_and_the_state_and_the_tmp(home):
    _halfway(home)
    r = msw.discard_pair("APEX", "1h")
    # three files, and two of them share a basename (rows/ and state/ both hold
    # APEX-1h.json) -- so count them, do not set-compare the names away
    assert len(r["deleted"]) == 3
    assert sum(d["file"] == "APEX-1h.json" for d in r["deleted"]) == 2
    assert sum(d["file"] == "APEX-1h.json.tmp" for d in r["deleted"]) == 1
    assert all(d["bytes"] > 0 for d in r["deleted"])
    assert not (home / "rows" / "APEX-1h.json").exists()
    assert not (home / "state" / "APEX-1h.json").exists()
    assert not (home / "rows" / "APEX-1h.json.tmp").exists()


def test_discard_keeps_the_candles(home, monkeypatch):
    """The candles are the expensive part, they are shared with every other
    timeframe, and they were not what failed."""
    cand = home / "candles"
    cand.mkdir()
    (cand / "APEX_USDT-1h.json").write_text("{}")
    monkeypatch.setattr(msw, "CANDLES", cand)
    _halfway(home)
    msw.discard_pair("APEX", "1h")
    assert (cand / "APEX_USDT-1h.json").exists()


def test_discard_on_a_pair_that_wrote_nothing_is_not_an_error(home):
    assert msw.discard_pair("NEVER", "4h")["deleted"] == []


def test_the_worker_discards_before_it_reports_a_failure(home, monkeypatch):
    """The delete must happen inside the worker, not in the caller: whatever
    merges the store must never get the chance to see the wreckage."""
    _halfway(home)

    def boom(*a, **k):
        raise RuntimeError("klines timed out")

    monkeypatch.setattr(msw, "run_pair", boom)
    r = msw._worker(("APEX_USDT", "1h", 5.0, 365, 1))
    assert r["failed"] is True and r["rows"] == 0
    assert "klines timed out" in r["why"]
    assert r["discarded"] == 3
    assert not (home / "rows" / "APEX-1h.json").exists()


def test_a_failed_pair_is_redone_and_only_that_pair(home, monkeypatch):
    """Two coins, one of which fails once. The failure must be resubmitted;
    the healthy coin must be measured exactly once."""
    seen = []

    def fake(job):
        sym, tf = job[0], job[1]
        seen.append((sym, tf))
        if sym == "BAD_USDT" and seen.count(("BAD_USDT", "1h")) == 1:
            return {"sym": sym, "tf": tf, "rows": 0, "why": "boom",
                    "failed": True, "discarded": 2}
        return {"sym": sym, "tf": tf, "rows": 10, "new_bars": 0}

    monkeypatch.setattr(msw, "_worker", fake)
    monkeypatch.setattr(msw, "PAIR_RETRIES", 2)
    _serial(monkeypatch)

    st = msw.run_market(["GOOD_USDT", "BAD_USDT"], tfs=("1h",))
    assert seen.count(("GOOD_USDT", "1h")) == 1, "a healthy coin is not redone"
    assert seen.count(("BAD_USDT", "1h")) == 2, "the failed pair is redone once"
    assert st["retries"] == 1
    assert st["failed"] == 0, "it succeeded on the retry"
    assert st["done"] == st["total"] == 2


def test_a_retry_never_inflates_the_denominator(home, monkeypatch):
    """`total` counts pairs. If a retry bumped it, the percentage would fall
    when a coin failed -- the counter would run backwards."""
    def always_bad(job):
        return {"sym": job[0], "tf": job[1], "rows": 0, "why": "boom",
                "failed": True, "discarded": 1}

    monkeypatch.setattr(msw, "_worker", always_bad)
    monkeypatch.setattr(msw, "PAIR_RETRIES", 2)
    _serial(monkeypatch)

    st = msw.run_market(["BAD_USDT"], tfs=("1h",))
    assert st["total"] == 1 and st["done"] == 1
    assert st["retries"] == 2, "tried twice more, then gave up"
    assert st["failed"] == 1


def test_a_pair_that_never_recovers_is_named_not_just_counted(home, monkeypatch):
    def always_bad(job):
        return {"sym": job[0], "tf": job[1], "rows": 0,
                "why": "klines returned 0 bars", "failed": True}

    monkeypatch.setattr(msw, "_worker", always_bad)
    monkeypatch.setattr(msw, "PAIR_RETRIES", 1)
    _serial(monkeypatch)

    st = msw.run_market(["BAD_USDT"], tfs=("1h",))
    assert st["failures"] == ["BAD_USDT 1h: klines returned 0 bars"]
    on_disk = json.loads((home / "progress.json").read_text())
    assert on_disk["failures"] == st["failures"], "the panel sees it too"


def _serial(monkeypatch):
    """Run the pool inline: a monkeypatched _worker cannot cross a process
    boundary, and the retry logic under test is in the parent either way."""
    import concurrent.futures as cf

    class Inline:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        # grid_from_store owns its pool explicitly (it must CANCEL the
        # queue on a STOP rather than wait for 4,985 pairs), so a
        # stand-in needs shutdown() as well as the context manager that
        # market_sweep.run() still uses.
        def shutdown(self, wait=True, *, cancel_futures=False):
            pass

        def submit(self, fn, *a):
            f = cf.Future()
            try:
                f.set_result(fn(*a))
            except Exception as exc:       # noqa: BLE001
                f.set_exception(exc)
            return f

    monkeypatch.setattr(cf, "ProcessPoolExecutor", lambda **k: Inline())


# ---------------------------------------------------------------- the LIVE path
# run_market is what the Back Test tab spawns. The ORCHESTRATOR measures through
# backtest_report.grid_from_store, and on 2026-08-25 that path had neither the
# delete nor the retry: a failed worker was appended to `excluded` and the run
# moved on, leaving the half-written pair on disk. The rule has to live on the
# path that is actually running, so both are tested.
def test_the_orchestrators_path_discards_and_redoes_the_failed_pair(monkeypatch):
    from tradingagents import backtest_report as br, market_sweep as msw

    calls, dropped = [], []

    def flaky(sym, tf, **k):
        calls.append((sym, tf))
        if sym == "BAD_USDT" and calls.count(("BAD_USDT", "1h")) == 1:
            raise RuntimeError("klines timed out")
        return {"rows": [{"coin": sym}], "why": None, "new_bars": 0}

    monkeypatch.setattr(msw, "run_pair", flaky)
    monkeypatch.setattr(msw, "discard_pair",
                        lambda c, tf: dropped.append((c, tf)) or {"deleted": []})
    monkeypatch.setattr(msw, "completed_pairs", lambda p: set())
    monkeypatch.setattr(msw, "pair_rows", lambda c, tf: [])
    monkeypatch.setattr(msw, "PAIR_RETRIES", 2)
    _inline_pool(monkeypatch)

    out = br.grid_from_store(["GOOD_USDT", "BAD_USDT"], ["1h"], workers=4)

    assert calls.count(("BAD_USDT", "1h")) == 2, "the failed pair is redone"
    assert calls.count(("GOOD_USDT", "1h")) == 1, "a healthy coin is not"
    assert dropped == [("BAD", "1h")], "and it is DELETED before the redo"
    assert out.get("excluded") == [], "it recovered, so it is not excluded"


def test_a_pair_being_retried_does_not_count_as_done_yet(monkeypatch):
    """`done` drives the percentage. Counting a pair the moment it FAILED made
    the bar reach 100% while the work was still queued.

    Two pairs, not one: grid_from_store clamps workers to len(pairs), so a
    single-pair run never enters the parallel branch at all -- which is how a
    first draft of this test 'passed' against the serial fallback.
    """
    from tradingagents import backtest_report as br, market_sweep as msw

    seen = []

    def one_bad(sym, tf, **k):
        if sym == "BAD_USDT":
            raise RuntimeError("boom")
        return {"rows": [{"coin": sym}], "why": None, "new_bars": 0}

    monkeypatch.setattr(msw, "run_pair", one_bad)
    monkeypatch.setattr(msw, "discard_pair", lambda c, tf: {"deleted": []})
    monkeypatch.setattr(msw, "completed_pairs", lambda p: set())
    monkeypatch.setattr(msw, "pair_rows", lambda c, tf: [])
    monkeypatch.setattr(msw, "PAIR_RETRIES", 2)
    _inline_pool(monkeypatch)

    out = br.grid_from_store(["GOOD_USDT", "BAD_USDT"], ["1h"], workers=4,
                             progress=lambda m, f, *a: seen.append((m, f)))

    msgs = [m for m, _ in seen]
    assert any("redoing 1/2" in m for m in msgs)
    assert any("redoing 2/2" in m for m in msgs)
    assert any("gave up after 2 retries" in m for m in msgs)

    # the fraction never counts a pair that is about to be retried
    for m, f in seen:
        if "redoing" in m:
            assert f < 1.0, "a pair being retried is not done"
    assert seen[-1][1] == 1.0 and sum(f == 1.0 for _, f in seen) == 1

    assert [e["coin"] for e in out["excluded"]] == ["BAD"], (
        "out of retries means excluded, and named")


def _inline_pool(monkeypatch):
    """Run submitted work inline. A monkeypatched run_pair cannot cross a
    process boundary, and the retry logic under test is in the parent."""
    import concurrent.futures as cf

    class Pool:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        # grid_from_store owns its pool explicitly (it must CANCEL the
        # queue on a STOP rather than wait for 4,985 pairs), so a
        # stand-in needs shutdown() as well as the context manager that
        # market_sweep.run() still uses.
        def shutdown(self, wait=True, *, cancel_futures=False):
            pass

        def submit(self, fn, *a, **k):
            f = cf.Future()
            try:
                f.set_result(fn(*a, **k))
            except Exception as exc:      # noqa: BLE001
                f.set_exception(exc)
            return f

    monkeypatch.setattr(cf, "ProcessPoolExecutor", lambda **k: Pool())
