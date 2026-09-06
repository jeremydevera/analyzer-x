"""RESOLVE PENDING on the Backtest screen — measure what was never measured.

Operator, Sep 05, 2026: *"can you create a buitton called 'Resolve Pending'
when i click this i want you to resolve all pending, currently there is 681
pending"*.

PENDING here is not the Candles screen's pending (that button already exists
and is about candle files). It is a pair this PC holds candles for and has
NEVER measured — no state file. 681 of them when the operator asked, over
4h: 318, 1d: 211, 1h: 84, 30m: 36, 15m: 32.

WHY IT DISPATCHES TIMEFRAMES AND NOT A PAIR LIST. The sweep workflow slices
its coins by index inside each shard (`syms[SHARD::SHARDS]`), so a run cannot
be aimed at an arbitrary list. It CAN be aimed at timeframes, and the pendings
are exactly a set of those. The fleet then re-measures pairs this machine has
already done, which costs GitHub time and costs the store nothing:
`collect_into_store` refuses to overwrite a pair whose local watermark is
above zero. And a collected pair DOES get a state file (`save_states` with
`__cloud__`), which is what makes it stop being pending — without that this
button could never move the number it is named after.

WHAT THE HARDDEV LOOP FOUND. 24 of the 681 are on 6 contracts MEXC no longer
lists (ASP, BULLCOIN, CZ, DRV, MEZO, ST). A shard builds its coin list from
the LIVE contract detail, so no fleet can ever reach them. Unsaid, this button
would stall the count at 24 and read as broken; it reports the split instead.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tradingagents import api as api_mod, backtest_logs as bl, capacity as cap, cloud_sweep as cs
from tradingagents.dataflows import mexc_futures as fx

_BY_TF = {"15m": 32, "30m": 36, "1h": 84, "4h": 318, "1d": 211}
# The default fixture is a store where every pending pair CAN be measured —
# `measurable_by_timeframe` mirrors `by_timeframe`. The split into short and
# delisted pairs has its own fixture below (SHORT), because those cases are
# about what the button must REFUSE to promise.
PENDING = {"count": 681, "stored": 5192, "measured": 4511,
           "by_timeframe": dict(_BY_TF),
           "measurable": 681, "measurable_by_timeframe": dict(_BY_TF),
           "too_short": 0, "too_short_by_timeframe": {},
           "delisted": 0, "delisted_coins": []}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(bl, "pending", lambda force=False: dict(PENDING))
    monkeypatch.setattr(bl, "pending_pairs", lambda: [("AAA_USDT", "4h")])
    monkeypatch.setattr(cs, "available", lambda: (True, "me/repo"))
    monkeypatch.setattr(cap, "cloud_free", lambda: (True, "free"))
    monkeypatch.setattr(cs, "remember", lambda run: None)
    monkeypatch.setattr(fx, "_get_public",
                        lambda url: {"data": [{"symbol": "AAA_USDT", "state": 0}]})
    return TestClient(api_mod.app)


def _dispatch_spy(sent: dict):
    def _d(**kw):
        sent.update(kw)
        return {"id": 42, "url": "https://gh/run/42"}
    return _d


def test_it_dispatches_the_frames_the_pendings_are_in(client, monkeypatch):
    sent: dict = {}
    monkeypatch.setattr(cs, "dispatch", _dispatch_spy(sent))
    got = client.post("/api/backtest/pending/resolve").json()
    assert got["dispatched"] is True
    assert got["run"]["id"] == 42
    assert set(sent["timeframes"].split(",")) == {"15m", "30m", "1h", "4h", "1d"}
    assert got["pending"] == 681
    assert "681" in got["why"], got["why"]


def test_only_the_frames_that_actually_have_pendings_are_sent(client, monkeypatch):
    """Sending a frame with nothing pending is twenty runners doing nothing."""
    monkeypatch.setattr(bl, "pending", lambda force=False: {
        **PENDING, "count": 318, "by_timeframe": {"4h": 318},
        "measurable": 318, "measurable_by_timeframe": {"4h": 318}})
    sent: dict = {}
    monkeypatch.setattr(cs, "dispatch", _dispatch_spy(sent))
    client.post("/api/backtest/pending/resolve")
    assert sent["timeframes"] == "4h"


def test_the_count_is_re_read_not_cached(client, monkeypatch):
    """The badge may be up to a minute old; an ACTION must not run on it."""
    asked: list = []
    monkeypatch.setattr(bl, "pending",
                        lambda force=False: asked.append(force) or dict(PENDING))
    monkeypatch.setattr(cs, "dispatch", _dispatch_spy({}))
    client.post("/api/backtest/pending/resolve")
    assert asked == [True], "the pending count must be forced, not reused"


def test_nothing_pending_dispatches_nothing(client, monkeypatch):
    monkeypatch.setattr(bl, "pending", lambda force=False: {
        **PENDING, "count": 0, "by_timeframe": {},
        "measurable": 0, "measurable_by_timeframe": {}})
    called: list = []
    monkeypatch.setattr(cs, "dispatch", lambda **k: called.append(k))
    got = client.post("/api/backtest/pending/resolve").json()
    assert got["dispatched"] is False and not called
    assert "nothing is pending" in got["why"]


# ------------------------------------------- what the fleet cannot reach
def test_delisted_pairs_are_named_not_silently_left_behind(client, monkeypatch):
    """24 of the operator's 681 were on contracts MEXC no longer lists."""
    monkeypatch.setattr(bl, "pending", lambda force=False: {
        **PENDING, "count": 681, "measurable": 679,
        "delisted": 2, "delisted_coins": ["CZ", "MEZO"]})
    monkeypatch.setattr(cs, "dispatch", _dispatch_spy({}))
    got = client.post("/api/backtest/pending/resolve").json()
    assert got["dispatched"] is True
    assert got["unreachable"] == 2
    assert got["unreachable_coins"] == ["CZ", "MEZO"]
    assert "CZ" in got["why"] and "delisted" in got["why"]
    assert got["measurable"] == 679, "and the number it CAN do is said too"


def test_all_delisted_means_no_pointless_dispatch(client, monkeypatch):
    monkeypatch.setattr(bl, "pending", lambda force=False: {
        **PENDING, "count": 2, "by_timeframe": {"1d": 2},
        "measurable": 0, "measurable_by_timeframe": {},
        "too_short": 0, "too_short_by_timeframe": {},
        "delisted": 2, "delisted_coins": ["CZ", "MEZO"]})
    called: list = []
    monkeypatch.setattr(cs, "dispatch", lambda **k: called.append(k))
    got = client.post("/api/backtest/pending/resolve").json()
    assert got["dispatched"] is False and not called, \
        "twenty runners must not be started for work none of them can do"
    assert "no longer lists" in got["why"]


def test_a_venue_that_will_not_answer_still_dispatches(client, monkeypatch):
    """The delisted check is a nicety. Losing it must not lose the button."""
    def _boom(url):
        raise RuntimeError("contract detail unreachable")

    monkeypatch.setattr(fx, "_get_public", _boom)
    monkeypatch.setattr(cs, "dispatch", _dispatch_spy({}))
    got = client.post("/api/backtest/pending/resolve").json()
    assert got["dispatched"] is True
    assert got["unreachable"] == 0, "unknown is reported as no split, not a guess"


# ---------------------------------------------------------- one at a time
def test_a_busy_fleet_is_refused_with_a_reason(client, monkeypatch):
    """Two runs measure the same contracts and the merge must then pick a
    winner. The refusal says what to do instead."""
    monkeypatch.setattr(cap, "cloud_free",
                        lambda: (False, "run 99 is already in progress"))
    called: list = []
    monkeypatch.setattr(cs, "dispatch", lambda **k: called.append(k))
    r = client.post("/api/backtest/pending/resolve")
    assert r.status_code == 409 and not called
    assert "run 99" in r.json()["detail"]


def test_no_github_is_a_refusal_not_a_crash(client, monkeypatch):
    monkeypatch.setattr(cs, "available", lambda: (False, "gh is not installed"))
    r = client.post("/api/backtest/pending/resolve")
    assert r.status_code == 400
    assert "gh is not installed" in r.json()["detail"]


def test_the_operators_own_window_and_stake_are_used(client, monkeypatch, tmp_path):
    """Not the dispatch defaults: a resolve run must be the same measurement
    as the rest of the grid, or the store holds two."""
    from tradingagents import db_jobs as dj

    spec = tmp_path / "spec.json"
    spec.write_text('{"days": 60, "base": 25.0}', encoding="utf-8")
    monkeypatch.setitem(dj.FILES["backtest"], "spec", spec)
    sent: dict = {}
    monkeypatch.setattr(cs, "dispatch", _dispatch_spy(sent))
    client.post("/api/backtest/pending/resolve")
    assert sent["days"] == 60 and sent["base"] == 25.0


# ------------------------------- what the BUSY run really covers (Sep 06)
def test_the_refusal_names_what_the_busy_run_does_not_reach(client, monkeypatch):
    """Pressed for real on Sep 06, 2026 and the refusal LIED.

    It said "the pending pairs are measured by the run already going" while run
    34004227228 was measuring 4h and 15m only — the autopilot sends at most
    MAX_TFS frames. That was 350 of 677; the other 327 on 1d/1h/30m were not in
    it. A refusal that misstates why is worse than no refusal.
    """
    from tradingagents import cloud_autopilot as ca

    monkeypatch.setattr(cap, "cloud_free",
                        lambda: (False, "run 34004227228 is already in progress"))
    monkeypatch.setattr(cs, "working_run",
                        lambda slug=None: {"id": 34004227228, "repo": "me/repo"})
    monkeypatch.setattr(ca, "_read",
                        lambda: {"run": 34004227228, "timeframes": ["4h", "15m"]})
    r = client.post("/api/backtest/pending/resolve")
    assert r.status_code == 409
    said = r.json()["detail"]
    assert "4h, 15m" in said, said
    assert "does NOT reach" in said
    # the FIXTURE's own numbers, not the live store's — 30m was 36 in this
    # snapshot and 32 when the button was pressed
    for frame in ("1d: 211", "1h: 84", "30m: 36"):
        assert frame in said, f"{frame} missing from {said}"
    assert "are measured by the run already going" not in said


def test_a_busy_run_that_covers_everything_says_so(client, monkeypatch):
    from tradingagents import cloud_autopilot as ca

    monkeypatch.setattr(cap, "cloud_free", lambda: (False, "run 7 in progress"))
    monkeypatch.setattr(cs, "working_run",
                        lambda slug=None: {"id": 7, "repo": "me/repo"})
    monkeypatch.setattr(ca, "_read", lambda: {
        "run": 7, "timeframes": ["15m", "30m", "1h", "4h", "1d"]})
    said = client.post("/api/backtest/pending/resolve").json()["detail"]
    assert "every pending frame" in said
    assert "does NOT reach" not in said


def test_an_unknown_busy_run_claims_no_coverage(client, monkeypatch):
    """A stale autopilot entry for a FINISHED run must not be read as
    coverage of the one actually running."""
    from tradingagents import cloud_autopilot as ca

    monkeypatch.setattr(cap, "cloud_free", lambda: (False, "run 9 in progress"))
    monkeypatch.setattr(cs, "working_run",
                        lambda slug=None: {"id": 9, "repo": "me/repo"})
    monkeypatch.setattr(ca, "_read",
                        lambda: {"run": 5, "timeframes": ["4h"]})   # a different run
    said = client.post("/api/backtest/pending/resolve").json()["detail"]
    assert "not recorded here" in said
    assert "4h" not in said, "a stale record must not be reported as coverage"


# --------------- what a sweep can ACTUALLY do (press-and-watch, Sep 06)
SHORT = {**PENDING, "count": 653, "measurable": 8,
         "measurable_by_timeframe": {"15m": 7, "30m": 1},
         "too_short": 645,
         "too_short_by_timeframe": {"4h": 313, "1d": 208, "1h": 79,
                                    "15m": 19, "30m": 26},
         "delisted": 24, "delisted_coins": ["ASP", "BULLCOIN", "CZ"]}


def test_only_frames_with_MEASURABLE_pendings_are_sent(client, monkeypatch):
    """653 pending was 8 measurable. Sending all five frames would put twenty
    runners on an hour of work to move the count by 8."""
    monkeypatch.setattr(bl, "pending", lambda force=False: dict(SHORT))
    sent: dict = {}
    monkeypatch.setattr(cs, "dispatch", _dispatch_spy(sent))
    got = client.post("/api/backtest/pending/resolve").json()
    assert set(sent["timeframes"].split(",")) == {"15m", "30m"}, sent
    assert got["measurable"] == 8
    assert "8 of 653" in got["why"], got["why"]
    assert "645 under their bar floor" in got["why"]


def test_nothing_measurable_dispatches_nothing_and_says_why(client, monkeypatch):
    """A store whose every pending pair is a young contract. The button must
    not start a run, and must not read as broken either."""
    monkeypatch.setattr(bl, "pending", lambda force=False: {
        **SHORT, "measurable": 0, "measurable_by_timeframe": {}})
    called: list = []
    monkeypatch.setattr(cs, "dispatch", lambda **k: called.append(k))
    got = client.post("/api/backtest/pending/resolve").json()
    assert got["dispatched"] is False and not called
    assert "bar floor" in got["why"] and "645" in got["why"]
    assert "4h: 313" in got["why"], "the frames are named, never just counted"
    assert "no longer lists" in got["why"] and "ASP" in got["why"]


def test_the_split_comes_from_pending_not_a_second_source(client, monkeypatch):
    """One payload decides the badge, the button and the dispatch. The route
    used to re-derive the delisted set with its own venue call."""
    import inspect

    from tradingagents import api as api_mod

    src = inspect.getsource(api_mod.backtest_pending_resolve)
    assert "measurable_by_timeframe" in src
    assert "contract/detail" not in src, \
        "the delisted set is pending()'s job, not a second venue call here"
