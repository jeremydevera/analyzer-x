"""RESOLVE PENDING on the Backtest screen — retry what BROKE.

Operator, Sep 05, 2026: *"can you create a buitton called 'Resolve Pending'
when i click this i want you to resolve all pending, currently there is 681
pending"* — and then, redefining it on 2026-09-09:

    *"pending only means these are the backtest that had problem during the
     update backtest or backtest button, resolve mean you will restart or
     resume where it crash"*

So PENDING is no longer "never measured". A pair nobody has swept yet is not a
problem — 117 of those existed with nothing wrong — and a count that includes
them can never reach zero. Pending is now the FAILURE LEDGER
(`pending_ledger`, kind "backtest"): a run tried this pair and it failed, and
it stays on the books until it actually measures. Never-measured pairs are
still reported, as `never_measured`, and BACKTEST / UPDATE ALL BACKTESTS are
the buttons for them.

WHY IT DISPATCHES TIMEFRAMES AND NOT A PAIR LIST. The sweep workflow claims
coins from a shared board inside each run, so a run cannot be aimed at an
arbitrary list. It CAN be aimed at timeframes, and the failures are a set of
those. The fleet then re-measures pairs this machine has already done, which
costs GitHub time and costs the store nothing: `collect_into_store` refuses to
overwrite a pair whose local watermark is above zero. And a collected pair
DOES get a state file (`save_states` with `__cloud__`), which is what takes it
off the books.

WHAT THE HARDDEV LOOP FOUND, kept because the refusals are still live: 24 of
the original 681 sat on 6 contracts MEXC no longer lists (ASP, BULLCOIN, CZ,
DRV, MEZO, ST), a busy run's coverage was reported as covering pendings it did
not reach, and a venue that would not answer must not stall the button.
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


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path, monkeypatch):
    """Never touch the operator's real failure ledger."""
    from tradingagents import pending_ledger as pl

    monkeypatch.setattr(pl, "STATE_DIR", tmp_path)
    return pl


def _broke(pl, by_tf):
    """Seed the failure ledger — the new source of PENDING."""
    pl.record("backtest", [(f"C{i}{tf}_USDT", tf, "worker: boom")
                           for tf, n in by_tf.items() for i in range(n)])


@pytest.fixture()
def client(monkeypatch, _own_ledger):
    # the failures the button now acts on, in the frames the operator had
    _broke(_own_ledger, _BY_TF)
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


def test_only_the_frames_that_actually_have_pendings_are_sent(client, monkeypatch,
                                                              _own_ledger):
    """Sending a frame with nothing FAILED is twenty runners doing nothing."""
    _own_ledger._write("backtest", {})            # clear the fixture's seed
    _broke(_own_ledger, {"4h": 318})
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


def test_nothing_failed_dispatches_nothing(client, monkeypatch, _own_ledger):
    """The redefinition, in one test: a store where nothing BROKE has nothing
    to resolve, even with 681 pairs nobody has ever swept."""
    _own_ledger._write("backtest", {})            # no failures on the books
    called: list = []
    monkeypatch.setattr(cs, "dispatch", lambda **k: called.append(k))
    got = client.post("/api/backtest/pending/resolve").json()
    assert got["dispatched"] is False and not called
    assert "no backtest has failed" in got["why"]
    # and the never-measured pairs are still SAID, just not called pending
    assert got["never_measured"] == 681
    assert "never been measured" in got["why"]


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






# --------------------------------------------------------------------------
# The never-measured SPLIT is still computed and still shown — it just no
# longer decides the dispatch. These guarded it when `pending` meant "never
# measured"; the knowledge is live (LogsPanel reads it), so they stay, aimed
# at the field that carries it now.
# --------------------------------------------------------------------------
def test_the_never_measured_split_is_still_reported(client, monkeypatch,
                                                    _own_ledger):
    """653 pending was 8 measurable, 645 under their timeframe's bar floor.
    That split still has to reach the screen — a young contract no sweep can
    make a row from must never read as work waiting to be done."""
    _own_ledger._write("backtest", {})
    monkeypatch.setattr(bl, "pending", lambda force=False: dict(SHORT))
    got = client.post("/api/backtest/pending/resolve").json()
    assert got["dispatched"] is False
    assert got["never_measured"] == SHORT["count"]
    assert got["too_short"] == SHORT["too_short"]


def test_delisted_coins_are_still_named(client, monkeypatch, _own_ledger):
    """24 of the operator's 681 were on contracts MEXC no longer lists. A
    fleet builds its coin list from the live venue, so it can never reach
    them — unsaid, they read as work that is simply not getting done."""
    _own_ledger._write("backtest", {})
    monkeypatch.setattr(bl, "pending", lambda force=False: {
        **PENDING, "count": 2, "delisted": 2, "delisted_coins": ["CZ", "MEZO"]})
    got = client.post("/api/backtest/pending/resolve").json()
    assert got["unreachable"] == 2
    assert got["unreachable_coins"] == ["CZ", "MEZO"]


def test_a_failure_is_pending_even_when_the_pair_was_measured_before(
        client, monkeypatch, _own_ledger):
    """The heart of the redefinition. A pair with a state file is NOT
    never-measured, so the old count could not see it fail. Under "pending =
    what broke" it is pending, and RESOLVE aims at its frame."""
    _own_ledger._write("backtest", {})
    monkeypatch.setattr(bl, "pending", lambda force=False: {
        **PENDING, "count": 0, "by_timeframe": {},
        "measurable": 0, "measurable_by_timeframe": {}})
    _own_ledger.record("backtest", [("ALREADY_USDT", "1h", "worker: MemoryError")])
    sent: dict = {}
    monkeypatch.setattr(cs, "dispatch", _dispatch_spy(sent))
    got = client.post("/api/backtest/pending/resolve").json()
    assert got["dispatched"] is True, got
    assert sent["timeframes"] == "1h"
    assert got["pending"] == 1
