"""An analysis run must survive the browser and never lie about its state.

The failure this guards: Streamlit ran the graph inline, so any click
abandoned it and the page still showed a spinner. Here a dead process can
never report `running: true`, and a stage is only `done` when its report
actually exists.
"""
import json
import os

import pytest

from tradingagents import analysis_jobs as aj


@pytest.fixture(autouse=True)
def _runs(tmp_path, monkeypatch):
    monkeypatch.setattr(aj, "RUN_DIR", tmp_path / "analysis")


def test_a_stage_is_done_only_when_its_report_exists():
    st = aj.stage_statuses({"market_report": "full text"}, ["market", "news"])
    by = {s["label"]: s["status"] for s in st}
    assert by["Market Analyst"] == "done"
    assert by["News Analyst"] == "running"       # first not-done
    assert by["Final Decision"] == "waiting"


def test_an_empty_report_string_is_not_done():
    st = aj.stage_statuses({"market_report": "   "}, ["market"])
    assert st[0]["status"] == "running"


def test_unselected_analysts_are_not_stages():
    labels = [s["label"] for s in aj.stage_statuses({}, ["market"])]
    assert "Sentiment Analyst" not in labels and "Market Analyst" in labels


def test_reports_carry_every_section_produced_so_far():
    got = aj.reports_of({"market_report": "m", "investment_plan": "p",
                         "risk_debate_state": {"judge_decision": "r"}})
    assert got == {"Market Analyst": "m", "Research Manager Plan": "p",
                   "Risk Judgement": "r"}


def test_a_dead_process_is_never_reported_as_running(monkeypatch):
    run_id = "AAPL-deadbeef"
    p = aj._paths(run_id)
    p["dir"].mkdir(parents=True)
    aj._write(p["progress"], {"running": True, "run_id": run_id})
    p["pid"].write_text("999999")            # a pid that cannot be alive
    got = aj.status(run_id)
    assert got["running"] is False
    assert "died" in got["error"]
    # and the correction is persisted, not recomputed every poll
    assert json.loads(p["progress"].read_text())["running"] is False


def test_status_of_an_unknown_run_says_so(monkeypatch):
    assert aj.status("nope")["error"] == "no such run"


def test_stop_writes_the_flag_and_marks_the_run_stopped():
    run_id = "TSLA-1234abcd"
    p = aj._paths(run_id)
    p["dir"].mkdir(parents=True)
    aj._write(p["progress"], {"running": True, "run_id": run_id})
    p["pid"].write_text(str(os.getpid() * 7 + 1))   # not us, not alive
    aj.stop(run_id)
    assert p["stop"].exists()
    assert json.loads(p["progress"].read_text())["running"] is False


def test_runs_lists_newest_first_without_report_bodies():
    for rid in ("A-1", "B-2"):
        p = aj._paths(rid)
        p["dir"].mkdir(parents=True)
        aj._write(p["progress"], {"running": False, "spec": {"ticker": rid[0],
                                  "model": "m"}, "reports": {"x": "y" * 5000},
                                  "decision": "BUY"})
    rows = aj.runs()
    assert {r["run_id"] for r in rows} == {"A-1", "B-2"}
    assert all("reports" not in r for r in rows), "listing must stay small"
    assert rows[0]["decision"] == "BUY"
