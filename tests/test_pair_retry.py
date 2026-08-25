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

        def submit(self, fn, *a):
            f = cf.Future()
            try:
                f.set_result(fn(*a))
            except Exception as exc:       # noqa: BLE001
                f.set_exception(exc)
            return f

    monkeypatch.setattr(cf, "ProcessPoolExecutor", lambda **k: Inline())
