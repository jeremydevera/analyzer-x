"""A finished run that is already in the store must not ask to be merged.

Operator, `Sep 15, 2026`, looking at the Backtest screen:

    GitHub run #34631292767  success  100.0%
    1,068/1,068 coins · 85,455,182 rows measured · 20/20 machine(s) finished
    [ MERGE INTO THIS PC ]  [ DISMISS ]
    results are NOT arriving live — this PC's receiver is closed; every row
    is still in the run's files and lands when it finishes

*"why am i seeing merge into this pc button again ... we agreed that when we
do backtest it should immediately update the backtest table"*.

It HAD. Both sentences on that card were false by then:

* The run started `Sep 12, 2026 2:05am` and **85,352,010 rows over 4,266
  pairs landed LIVE** through the receiver while it measured
  (`ingest_progress.json`). It was then collected, and **five newer runs**
  were collected after it — the newest at 96,279,904 rows. Pressing MERGE
  would have downloaded twenty shard files to write nothing.
* The receiver shuts itself a few hours after the last post (`IDLE_STOP_S`),
  so on a run that ended three days ago a closed door is the normal end
  state, not a fault. "lands when it finishes" describes a run that has not
  finished.

The card keeps a finished run's summary on purpose — `cs.remembered()` is the
fallback when nothing is measuring, so the operator can still read what the
last run did. What it may not do is keep offering an ACTION that is already
done, or a WARNING about a state that is already over.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PANEL = Path("webapp/src/components/backtest/JobsPanel.tsx")
CLIENT = Path("webapp/src/lib/api.ts")


@pytest.fixture
def api_mod(tmp_path, monkeypatch):
    from tradingagents import api as _api, cloud_autopilot as ap

    monkeypatch.setattr(ap, "STATE", tmp_path / "cloud_autopilot.json")
    return _api, ap


def _status(api_mod, run_id, collected, monkeypatch):
    api, ap = api_mod
    ap.STATE.write_text(json.dumps({"collected": collected}), encoding="utf-8")

    from tradingagents import cloud_sweep as cs

    monkeypatch.setattr(cs, "available", lambda: (True, ""))
    monkeypatch.setattr(cs, "remembered", lambda: {"id": run_id})
    monkeypatch.setattr(cs, "status", lambda rid: {"conclusion": "success"})
    monkeypatch.setattr(cs, "live_progress", lambda rid: [])
    monkeypatch.setattr(api, "_working_run_cached", lambda: None)
    return api._read_cloud_status()


# ------------------------------------------------------------- the backend
def test_the_status_says_the_run_is_already_in_the_store(api_mod, monkeypatch):
    got = _status(api_mod, 34631292767, [34631292767, 34843633133], monkeypatch)
    assert got["collected"] is True
    assert got["run"]["id"] == 34631292767


def test_an_uncollected_run_still_says_so(api_mod, monkeypatch):
    got = _status(api_mod, 34999999999, [34631292767], monkeypatch)
    assert got["collected"] is False


def test_an_unreadable_autopilot_file_is_not_a_claim(api_mod, monkeypatch):
    """Never guess "collected" — an unreadable record must read as NOT
    collected, so the operator is offered the merge rather than quietly
    denied it."""
    api, ap = api_mod
    ap.STATE.write_text("{ not json", encoding="utf-8")

    from tradingagents import cloud_sweep as cs

    monkeypatch.setattr(cs, "available", lambda: (True, ""))
    monkeypatch.setattr(cs, "remembered", lambda: {"id": 1})
    monkeypatch.setattr(cs, "status", lambda rid: {"conclusion": "success"})
    monkeypatch.setattr(cs, "live_progress", lambda rid: [])
    monkeypatch.setattr(api, "_working_run_cached", lambda: None)
    assert api._read_cloud_status()["collected"] is False


# --------------------------------------------------------------- the card
def test_the_merge_button_is_gated_on_collected():
    body = PANEL.read_text(encoding="utf-8")
    assert 'cloud.conclusion === "success" && !cloud.collected' in body, \
        "MERGE must not be offered for a run already in the store"
    assert "already in this PC" in body, \
        "and the card must SAY why the button is gone, not just drop it"


def test_the_not_arriving_live_warning_is_gated_on_a_RUNNING_run():
    body = PANEL.read_text(encoding="utf-8")
    i = body.index("results are NOT arriving live")
    before = body[max(0, i - 700):i]
    assert "if (cloud.conclusion) return null;" in before, \
        ("a closed receiver on a FINISHED run is the normal end state — the "
         "door idles out — and 'lands when it finishes' is about a run that "
         "has not finished")


def test_the_client_carries_the_flag():
    body = CLIENT.read_text(encoding="utf-8")
    block = body[body.index("export interface CloudStatus {"):]
    block = block[:block.index("}")]
    assert "collected?: boolean;" in block
