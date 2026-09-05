"""GitHub gets used whenever GitHub is free — without being asked.

Operator, 2026-09-05: *"I WANT TO USE GITHUB WHEN THERE IS FREE"*, after
*"SHOULD I USE GITHUB INSTEAD IF IM SHORT ON MEMORY"* and, before that,
*"why did you not use github since its free?"*.

Three asks, and every time the answer was me dispatching a run by hand. GitHub
sat idle through a 4,124-pair local run that took most of a day, because
nothing ever looked. Measured on this store when the autopilot was written:
775 pairs had candles and no measurement (4h 322, 1d 285, 1h 90, 30m 44,
15m 34) while the fleet was completely idle.

Three bugs the harddev loop found before this was tested, each guarded below:

* ROUND 1a — `consider()` runs on a 30-second supervisor tick and asked GitHub
  every time. That is 2 API calls a minute against the endpoints whose
  SECONDARY rate limit 403'd this account for hours on Sep 02, 2026 and
  blinded the Cloud panel over a healthy run. Cheap local checks come first,
  and GitHub is asked at most every 5 minutes.
* ROUND 1b — pairs that can NEVER be measured (too few bars for their
  timeframe) keep their gap for ever, so the autopilot would send 20 machines
  at dead work every 30 minutes, indefinitely.
* ROUND 2 — the first fix for that blocked on "did not shrink", which also
  matches "GOT BIGGER". A new gap from freshly downloaded candles is real work
  and was being refused. Only the frames that failed to improve are skipped
  now, not the whole autopilot.
"""
import time

import pytest

from tradingagents import cloud_autopilot as ca


@pytest.fixture(autouse=True)
def _own_state(tmp_path, monkeypatch):
    """Never touch the operator's real autopilot state."""
    monkeypatch.setattr(ca, "STATE", tmp_path / "autopilot.json")


# ----------------------------------------------------------------- what to send
def test_the_biggest_hole_goes_first():
    got = ca.pick({"4h": 322, "1d": 285, "1h": 90, "15m": 34})
    assert got == ["4h", "1d"]


def test_a_frame_the_local_job_is_on_is_taken_last():
    """Not excluded — the merge refuses to overwrite a locally-measured pair —
    but it is the least useful thing an idle fleet could do."""
    got = ca.pick({"4h": 322, "1d": 285}, busy_local=["4h"], limit=1)
    assert got == ["1d"]


def test_frames_that_did_not_improve_are_skipped_not_resent():
    """ROUND 1b. Their pairs have too few bars to measure; sending them again
    is 20 machines doing nothing."""
    m = {"4h": 322, "1d": 285, "1h": 90, "15m": 34}
    assert ca.pick(m, skip=["1d", "4h"]) == ["1h", "15m"]


def test_nothing_to_send_is_an_empty_list_not_a_crash():
    assert ca.pick({}) == []
    assert ca.pick({"1d": 0}) == []
    assert ca.pick({"1d": 5}, skip=["1d"]) == []


# --------------------------------------------------------------- when to send
def _wire(monkeypatch, *, missing, free=(True, "free"), running=False,
          dispatch=None):
    from tradingagents import capacity as cap, cloud_sweep as cs, db_jobs as dj

    monkeypatch.setattr(ca, "missing_by_timeframe", lambda: dict(missing))
    monkeypatch.setattr(cap, "cloud_free", lambda: free)
    monkeypatch.setattr(dj, "status", lambda k: {"running": running})
    monkeypatch.setattr(dj, "_read", lambda p: {"tfs": ["15m", "30m"]})
    sent = []

    def _d(**kw):
        sent.append(kw)
        if dispatch == "boom":
            raise RuntimeError("gh refused")
        return {"id": 999, "url": "http://x"}

    monkeypatch.setattr(cs, "dispatch", _d)
    return sent


def test_it_dispatches_when_github_is_free_and_there_is_a_hole(monkeypatch):
    sent = _wire(monkeypatch, missing={"4h": 322, "1d": 285})
    got = ca.consider()
    assert got["dispatched"] is True
    assert got["timeframes"] == ["4h", "1d"]
    assert sent and sent[0]["timeframes"] == "4h,1d"
    assert got["covered"] == 607


def test_a_busy_fleet_is_left_alone(monkeypatch):
    _wire(monkeypatch, missing={"4h": 322},
          free=(False, "run 7 is already in progress"))
    got = ca.consider()
    assert got["dispatched"] is False
    assert "run 7" in got["why"]


def test_a_handful_of_pairs_is_not_worth_twenty_machines(monkeypatch):
    sent = _wire(monkeypatch, missing={"1d": 3})
    got = ca.consider()
    assert got["dispatched"] is False
    assert not sent
    assert "under the" in got["why"]


def test_it_will_not_dispatch_twice_inside_the_cooldown(monkeypatch):
    sent = _wire(monkeypatch, missing={"4h": 322})
    assert ca.consider()["dispatched"] is True
    got = ca.consider()
    assert got["dispatched"] is False
    assert "cooling down" in got["why"]
    assert len(sent) == 1, "a 30-second tick must not fire a run per tick"


def test_a_refused_dispatch_is_named_never_swallowed(monkeypatch):
    """An autopilot that fails silently looks exactly like one that works."""
    _wire(monkeypatch, missing={"4h": 322}, dispatch="boom")
    got = ca.consider()
    assert got["dispatched"] is False
    assert "dispatch refused" in got["why"] and "gh refused" in got["why"]


# ------------------------------------------------------- the rate-limit guard
def test_github_is_not_asked_on_every_tick(monkeypatch):
    """ROUND 1a. The supervisor ticks every 30 s; the Actions API secondary
    limit 403'd this account for hours on Sep 02, 2026."""
    from tradingagents import capacity as cap

    calls = {"n": 0}

    def counted():
        calls["n"] += 1
        return False, "busy"

    _wire(monkeypatch, missing={"4h": 322})
    monkeypatch.setattr(cap, "cloud_free", counted)
    t = time.time()
    for i in range(20):                       # ten minutes of 30-second ticks
        ca.consider(now=t + i * 30)
    assert calls["n"] <= 3, f"asked GitHub {calls['n']} times in 10 minutes"


def test_the_cheap_check_runs_before_the_expensive_one(monkeypatch):
    """A store with nothing missing must never cost a GitHub call at all."""
    from tradingagents import capacity as cap

    calls = {"n": 0}
    _wire(monkeypatch, missing={"1d": 2})
    monkeypatch.setattr(cap, "cloud_free",
                        lambda: (calls.__setitem__("n", calls["n"] + 1),
                                 (True, "free"))[1])
    ca.consider()
    assert calls["n"] == 0


# --------------------------------------------------- the never-ending dispatch
def test_a_gap_that_cannot_move_is_not_sent_for_ever(monkeypatch):
    """ROUND 1b. Pairs below MIN_BARS never get a state file, so their gap
    never closes — 20 machines every 30 minutes at work that cannot move."""
    sent = _wire(monkeypatch, missing={"4h": 322, "1d": 285})
    t = time.time()
    assert ca.consider(now=t)["dispatched"] is True
    # same gap, well past the cooldown
    got = ca.consider(now=t + ca.COOLDOWN_S + 60)
    assert got["dispatched"] is False, got
    assert len(sent) == 1


def test_a_gap_that_GREW_is_real_new_work(monkeypatch):
    """ROUND 2. The first fix blocked on "did not shrink", and "got bigger" is
    not smaller — freshly downloaded candles were being refused."""
    from tradingagents import capacity as cap, cloud_sweep as cs, db_jobs as dj

    state = {"missing": {"4h": 322, "1d": 285}}
    monkeypatch.setattr(ca, "missing_by_timeframe", lambda: dict(state["missing"]))
    monkeypatch.setattr(cap, "cloud_free", lambda: (True, "free"))
    monkeypatch.setattr(dj, "status", lambda k: {"running": False})
    monkeypatch.setattr(dj, "_read", lambda p: {"tfs": []})
    sent = []
    monkeypatch.setattr(cs, "dispatch",
                        lambda **kw: (sent.append(kw),
                                      {"id": 1, "url": "u"})[1])
    t = time.time()
    assert ca.consider(now=t)["dispatched"] is True

    # a candle download adds a brand-new hole on a frame that was clean
    state["missing"] = {"4h": 322, "1d": 285, "15m": 400}
    got = ca.consider(now=t + ca.COOLDOWN_S + 60)
    assert got["dispatched"] is True, got
    assert "15m" in got["timeframes"], got
    assert len(sent) == 2


def test_an_improved_frame_is_sent_again(monkeypatch):
    sent = _wire(monkeypatch, missing={"4h": 322, "1d": 285})
    t = time.time()
    ca.consider(now=t)
    from tradingagents import cloud_sweep as cs  # noqa: F401

    monkeypatch.setattr(ca, "missing_by_timeframe",
                        lambda: {"4h": 100, "1d": 285})
    got = ca.consider(now=t + ca.COOLDOWN_S + 60)
    assert got["dispatched"] is True
    assert "4h" in got["timeframes"], got


# ----------------------------------------------------------------- plumbing
def test_a_corrupt_state_file_is_not_fatal():
    ca.STATE.write_text("not json")
    assert ca._read() == {}


def test_the_supervisor_calls_it():
    src = open("tradingagents/api.py", encoding="utf-8").read()
    assert "cloud_autopilot" in src
    assert "_ca.tick()" in src
    # and a failure there must never take the supervisor down with it
    i = src.index("_ca.tick()")
    assert "except Exception" in src[i:i + 300]


def test_missing_is_counted_from_directory_listings(monkeypatch, tmp_path):
    """Never `candle_coverage()`, which opens every candle file — this runs on
    a 30-second tick against a 5,000-pair store."""
    import inspect

    from tradingagents import market_sweep as msw

    # the docstring NAMES candle_coverage as the thing not to use, so check
    # the body rather than the whole source
    src = inspect.getsource(ca.missing_by_timeframe)
    body = src.split('"""')[-1]
    assert "candle_coverage" not in body
    assert ".glob(" in body

    candles, states = tmp_path / "c", tmp_path / "s"
    candles.mkdir(), states.mkdir()
    for n in ("BTC_USDT-15m", "BTC_USDT-1d", "ETH_USDT-1d"):
        (candles / f"{n}.json").write_text("{}")
    (states / "BTC-15m.json").write_text("{}")
    monkeypatch.setattr(msw, "CANDLES", candles)
    monkeypatch.setattr(msw, "STATES", states)
    assert ca.missing_by_timeframe() == {"1d": 2}


def test_a_no_op_is_logged_when_the_reason_changes(monkeypatch, capsys):
    """The module's docstring says a silent no-op is indistinguishable from a
    broken autopilot — and then every no-op was silent. Logging every tick
    would be a line every 30 seconds; logging only CHANGES is one per event."""
    reasons = iter([{"dispatched": False, "why": "GitHub is not free: run 7"},
                    {"dispatched": False, "why": "GitHub is not free: run 7"},
                    {"dispatched": False, "why": "cooling down, 12 min left"}])
    monkeypatch.setattr(ca, "consider", lambda: next(reasons))
    ca._LAST_SAID["why"] = ""
    for _ in range(3):
        ca.tick()
    out = capsys.readouterr().out
    assert out.count("[cloud-autopilot]") == 2, out
    assert "run 7" in out and "cooling down" in out


def test_the_supervisor_calls_tick_not_consider():
    src = open("tradingagents/api.py", encoding="utf-8").read()
    assert "_ca.tick()" in src
