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


# --- social sources -------------------------------------------------------
# The Sentiment Analyst reads X (Twitter) only when include_twitter is on, and
# X is metered — so the choice must travel from the screen into the run's
# config, and must never be turned on by accident. The React screen shipped
# without it on 2026-08-21, which silently ran every analysis on StockTwits
# only, with no way to ask for X.

def test_config_carries_the_social_choice_and_keywords():
    cfg = aj.social_config({"social_source": "both",
                            "twitter_keywords": ["ERC", "rate hike", "ERC"]})
    assert cfg["include_twitter"] is True
    assert cfg["include_stocktwits"] is True
    assert cfg["twitter_extra_terms"] == ["ERC", "rate hike"], "de-duped, order kept"


def test_twitter_only_turns_stocktwits_off():
    cfg = aj.social_config({"social_source": "twitter"})
    assert cfg["include_twitter"] is True and cfg["include_stocktwits"] is False


def test_the_default_never_spends_x_credits():
    for spec in ({}, {"social_source": ""}, {"social_source": "stocktwits"}):
        cfg = aj.social_config(spec)
        assert cfg["include_twitter"] is False, spec
        assert cfg["include_stocktwits"] is True, spec


def test_an_unknown_source_falls_back_to_the_free_one_not_to_x():
    cfg = aj.social_config({"social_source": "twitr"})
    assert cfg["include_twitter"] is False and cfg["include_stocktwits"] is True


def test_keywords_are_ignored_when_x_is_off():
    """Extra terms with X off would read as 'X is searching these'."""
    cfg = aj.social_config({"social_source": "stocktwits",
                            "twitter_keywords": ["ERC"]})
    assert "twitter_extra_terms" not in cfg
