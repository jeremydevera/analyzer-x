"""The candle store keeps itself fresh, so "pending" stays near zero.

Operator, 2026-09-06: *"up until now i still see 5095 pending for candles"* —
after it had been driven to 0 at 10:55pm the night before — then *"then fix
that bug"*.

The count was never wrong. "Behind" means a pair's newest stored candle is more
than one bar old, measured against the CLOCK, so the store goes stale on its
own: 0 at 10:55pm, 5,095 by 9:33am, a median 12.6 hours behind. Saying so more
clearly was honest but changed nothing — UPDATE CANDLES had always been a
button somebody has to press.

Five rounds of the harddev loop before any of this ran; each finding has a test
below:

* ROUND 1 — it called `pending_work()`, which also builds the whole 5,192-pair
  RESOLVE queue, every 30 seconds, for two numbers it does not use.
* ROUND 2a — a comment claimed a measurement (0.02 s) that was never taken; the
  real figure is 0.122 s.
* ROUND 2b — `_pending_sources` is private and lives in a module a second
  session edits. If `behind_hours` disappeared, `float(None or 0.0)` is 0.0,
  which is under the threshold, so this would quietly stop topping the store up
  FOR EVER with no error anywhere.
* ROUND 4 — a top-up now starts on its own, so the Candles buttons grey out at
  moments the operator did not cause, and a button that greys out for no stated
  reason reads as broken.

Rounds 3 and 5 came back clean and are named in the commit.
"""
import io
import time

import pytest

from tradingagents import candle_autopilot as cda


@pytest.fixture(autouse=True)
def _own_state(tmp_path, monkeypatch):
    monkeypatch.setattr(cda, "STATE", tmp_path / "candle_autopilot.json")
    cda._LAST_SAID["why"] = ""


def _wire(monkeypatch, *, behind, hours, running=False, boom=False):
    from tradingagents import db_jobs as dj

    monkeypatch.setattr(dj, "status", lambda k: {"running": running})
    src = {"behind": behind}
    if hours is not None:
        src["behind_hours"] = hours
    monkeypatch.setattr(dj, "_pending_sources", lambda: src)
    started = []

    def _start(kind, spec):
        started.append((kind, spec))
        if boom:
            raise RuntimeError("nope")
        return 4242

    monkeypatch.setattr(dj, "start", _start)
    return started


# ------------------------------------------------------------- when it fires
def test_a_stale_store_is_topped_up(monkeypatch):
    started = _wire(monkeypatch, behind=5095, hours=12.6)
    got = cda.consider()
    assert got["started"] is True
    assert started == [("download", {"mode": "update"})], started
    assert "12.6h behind" in got["why"] and "5,095" in got["why"]


def test_an_update_not_a_resolve(monkeypatch):
    """A resolve also attempts the 97 delisted pairs and the never-stored
    ones — work for a person pressing a button, not an hourly loop."""
    started = _wire(monkeypatch, behind=5095, hours=12.6)
    cda.consider()
    assert started[0][1]["mode"] == "update"


def test_a_nearly_fresh_store_is_left_alone(monkeypatch):
    started = _wire(monkeypatch, behind=400, hours=1.0)
    got = cda.consider()
    assert got["started"] is False and not started
    assert "under the" in got["why"]


def test_a_current_store_is_left_alone(monkeypatch):
    started = _wire(monkeypatch, behind=0, hours=0.0)
    assert cda.consider()["started"] is False
    assert not started


def test_it_never_runs_beside_another_download(monkeypatch):
    """Two downloads write the same candle files."""
    started = _wire(monkeypatch, behind=5095, hours=12.6, running=True)
    got = cda.consider()
    assert got["started"] is False and not started
    assert "already running" in got["why"]


def test_one_top_up_per_cooldown(monkeypatch):
    started = _wire(monkeypatch, behind=5095, hours=12.6)
    t = time.time()
    assert cda.consider(now=t)["started"] is True
    got = cda.consider(now=t + 60)
    assert got["started"] is False and "cooling down" in got["why"]
    assert len(started) == 1, "a 30-second tick must not stack top-ups"


def test_after_the_cooldown_a_stale_store_is_topped_up_again(monkeypatch):
    started = _wire(monkeypatch, behind=5095, hours=12.6)
    t = time.time()
    cda.consider(now=t)
    cda.consider(now=t + cda.COOLDOWN_S + 60)
    assert len(started) == 2


# ------------------------------------------------------------ round 1: cost
def test_it_uses_the_cheap_count_not_the_queue_builder():
    """ROUND 1. `pending_work()` also sorts a 5,192-pair RESOLVE queue to fill
    its `queue` field — 0.19 s a tick against 0.122 s, every 30 seconds, for
    two numbers it does not use."""
    import inspect

    src = inspect.getsource(cda.consider)
    assert "_pending_sources()" in src
    assert "pending_work()" not in src


# --------------------------------------------- round 2b: the silent disable
def test_a_missing_behind_hours_is_shouted_not_swallowed(monkeypatch):
    """`_pending_sources` is private and another session edits that module. If
    the key went away, `float(None or 0.0)` is 0.0 — under the threshold — and
    this would quietly never top the store up again."""
    started = _wire(monkeypatch, behind=5000, hours=None)
    got = cda.consider()
    assert got["started"] is False and not started
    assert "no longer reports behind_hours" in got["why"]
    assert "standing down" in got["why"]


def test_a_measurement_in_a_comment_is_the_measured_one():
    """ROUND 2a: the first version claimed 0.02 s, which was never measured."""
    body = io.open("tradingagents/candle_autopilot.py", encoding="utf-8").read()
    assert "0.122 s" in body
    assert "0.02 s" not in body


def test_the_threshold_and_the_prose_agree():
    body = io.open("tradingagents/candle_autopilot.py", encoding="utf-8").read()
    assert cda.STALE_HOURS == 3.0
    assert "under two hours" not in body, "the docstring said two, the constant says three"


# ---------------------------------------------------------- failure paths
def test_a_refused_start_is_named(monkeypatch):
    _wire(monkeypatch, behind=5095, hours=12.6, boom=True)
    got = cda.consider()
    assert got["started"] is False
    assert "could not start the update" in got["why"] and "nope" in got["why"]


def test_an_unreadable_store_is_named(monkeypatch):
    from tradingagents import db_jobs as dj

    monkeypatch.setattr(dj, "status", lambda k: {"running": False})

    def boom():
        raise OSError("index gone")

    monkeypatch.setattr(dj, "_pending_sources", boom)
    got = cda.consider()
    assert got["started"] is False and "cannot count the store" in got["why"]


def test_a_corrupt_state_file_is_not_fatal():
    cda.STATE.write_text("not json")
    assert cda._read() == {}


# ------------------------------------------------------------- plumbing
def test_the_supervisor_calls_it():
    src = io.open("tradingagents/api.py", encoding="utf-8").read()
    assert "candle_autopilot" in src and "_cda.tick()" in src
    i = src.index("_cda.tick()")
    assert "except Exception" in src[i:i + 300], \
        "a failure here must not take the supervisor down"


def test_no_ops_are_logged_when_the_reason_changes(monkeypatch, capsys):
    reasons = iter([{"started": False, "why": "the store is current"},
                    {"started": False, "why": "the store is current"},
                    {"started": False, "why": "a download is already running"}])
    monkeypatch.setattr(cda, "consider", lambda: next(reasons))
    for _ in range(3):
        cda.tick()
    out = capsys.readouterr().out
    assert out.count("[candle-autopilot]") == 2, out


# ------------------------------------------------- round 4: the grey buttons
def test_the_screen_says_why_the_buttons_are_grey():
    """A top-up now starts by itself, so these grey out at a moment the
    operator did not cause."""
    body = io.open("webapp/src/components/candles/DownloadScreen.tsx",
                   encoding="utf-8").read()
    assert "the buttons wait while a" in body
    assert "top up on their own once the store is 3h behind" in body
