"""A dispatch must not wipe the autopilot's memory of what it has collected.

Found by watching, Sep 06, 2026. `db_collect.log` held 46 collect completions
over 17 DISTINCT runs — one collected five times — each downloading 30-40
million rows of artifacts to keep zero pairs, because every one of them had
already been landed.

The cause was one line. `consider()` ended with

    _write({"last_dispatch": now, "last_check": now, "run": ...,
            "timeframes": tfs, "missing": missing})

a FRESH dict, so writing it deleted `collected`, `collecting` and
`collect_tries` from the state file. With no memory of what had landed, the
next tick started again at the oldest run. The live state file at that moment
held exactly those five dispatch keys and no `collected` at all, which is what
made it visible.

`collect_finished` was never wrong: it adds a run to `collected` only when the
collect job reports success, and it mutates the same `state` dict the caller
read. The dispatch simply threw that dict away.
"""
from __future__ import annotations

import json

import pytest

from tradingagents import cloud_autopilot as ca


@pytest.fixture()
def state_file(tmp_path, monkeypatch):
    p = tmp_path / "cloud_autopilot.json"
    monkeypatch.setattr(ca, "STATE", p)
    return p


def test_a_dispatch_keeps_the_collect_ledger(state_file, monkeypatch):
    """The bug, in one assertion."""
    state_file.write_text(json.dumps({
        "collected": [111, 222], "collecting": 333,
        "collect_tries": {"333": 1}, "last_check": 5.0}), encoding="utf-8")

    from tradingagents import capacity as cap, cloud_sweep as cs

    monkeypatch.setattr(ca, "missing_by_timeframe", lambda: {"4h": 400})
    monkeypatch.setattr(ca, "collect_finished",
                        lambda **k: {"started": False, "why": "none"})
    monkeypatch.setattr(cap, "cloud_free", lambda: (True, "free"))
    monkeypatch.setattr(cs, "dispatch",
                        lambda **k: {"id": 999, "url": "u", "repo": "r"})
    monkeypatch.setattr(ca, "pick", lambda *a, **k: ["4h"])

    got = ca.consider()
    assert got.get("dispatched") is True, got

    after = json.loads(state_file.read_text())
    assert after["collected"] == [111, 222], \
        "the dispatch deleted the ledger — 46 collects over 17 runs"
    assert after["collecting"] == 333
    assert after["collect_tries"] == {"333": 1}
    # and it still records the dispatch it just made
    assert after["run"] == 999 and after["timeframes"] == ["4h"]


def test_a_collected_run_is_never_collected_twice(state_file, monkeypatch):
    """The consequence the ledger exists to prevent."""
    state_file.write_text(json.dumps({"collected": [111]}), encoding="utf-8")

    from tradingagents import cloud_sweep as cs, db_jobs as dj

    started: list = []
    monkeypatch.setattr(dj, "status", lambda k: {"running": False})
    monkeypatch.setattr(dj, "start",
                        lambda kind, spec: started.append(spec) or 1)
    monkeypatch.setattr(cs, "repo_slug", lambda: "me/repo")
    monkeypatch.setattr(cs, "_runs", lambda slug, limit=10: [
        {"databaseId": 111, "status": "completed", "conclusion": "success"}])
    monkeypatch.setattr(cs, "artifact_names", lambda rid: ["rows-0"])

    got = ca.collect_finished(now=1e9, state=json.loads(state_file.read_text()))
    assert got.get("started") is not True, got
    assert not started, "a run already in `collected` must not be re-collected"


def test_an_uncollected_run_still_starts(state_file, monkeypatch):
    """The other direction, or the test above passes on a broken autopilot."""
    from tradingagents import cloud_sweep as cs, db_jobs as dj

    started: list = []
    monkeypatch.setattr(dj, "status", lambda k: {"running": False})
    monkeypatch.setattr(dj, "start",
                        lambda kind, spec: started.append(spec) or 7)
    monkeypatch.setattr(cs, "repo_slug", lambda: "me/repo")
    monkeypatch.setattr(cs, "_runs", lambda slug, limit=10: [
        {"databaseId": 222, "status": "completed", "conclusion": "success"}])
    monkeypatch.setattr(cs, "artifact_names", lambda rid: ["rows-0"])

    got = ca.collect_finished(now=1e9, state={"collected": [111]})
    assert got.get("started") is True, got
    assert started == [{"run": 222}]


def test_the_dispatch_write_merges_rather_than_replaces():
    """The shape of the fix, so a future edit cannot quietly go back to a
    fresh dict — which is what cost ~29 redundant multi-gigabyte collects."""
    import inspect

    src = inspect.getsource(ca.consider)
    i = src.index('"last_dispatch": now')
    head = src[max(0, i - 200):i]
    assert "**" in head, \
        "the dispatch must merge into the existing state, not replace it"
    assert "_write({\"last_dispatch\"" not in src
