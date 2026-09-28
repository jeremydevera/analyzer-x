"""A run the collect has just finished must not offer MERGE INTO THIS PC.

Sep 28, 2026: run 36461959914 was collected by itself at 2:24pm; the
autopilot ticks a run off only on its next look (every 5 minutes), so the
card kept offering the merge until 2:30pm and the operator asked "does this
mean you are not merging it automatically?".
"""
from tradingagents import api, cloud_autopilot as ap, db_jobs as dj


def _files(monkeypatch, *, listed=(), progress=None):
    monkeypatch.setattr(ap, "_read", lambda: {"collected": list(listed)})
    monkeypatch.setattr(dj, "_read", lambda path: (progress or {})
                        if path == dj.FILES["collect_v2"]["progress"] else {})


def test_the_collects_own_finished_record_counts(monkeypatch):
    _files(monkeypatch, progress={"run": 36461959914, "running": False,
                                  "finished": 1790619882})
    assert api._collect_finished(36461959914)


def test_a_collect_still_running_does_not(monkeypatch):
    _files(monkeypatch, progress={"run": 36461959914, "running": True})
    assert not api._collect_finished(36461959914)


def test_a_failed_collect_does_not(monkeypatch):
    _files(monkeypatch, progress={"run": 36446487985, "running": False,
                                  "finished": 1, "error": "ValueError: A 1h"})
    assert not api._collect_finished(36446487985)


def test_another_runs_record_does_not(monkeypatch):
    _files(monkeypatch, progress={"run": 1, "running": False, "finished": 1})
    assert not api._collect_finished(36461959914)


def test_the_autopilots_list_still_counts(monkeypatch):
    _files(monkeypatch, listed=[36461974699])
    assert api._collect_finished(36461974699)
