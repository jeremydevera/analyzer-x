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


# --- parallel runs and the markdown export --------------------------------
# Streamlit could run several models at once, each on its own provider, and
# hand back a .md of the result. Both were missing from the React screen.

def test_parallel_start_makes_one_run_per_model(monkeypatch):
    from fastapi.testclient import TestClient

    from tradingagents.api import app
    started = []
    monkeypatch.setattr(aj, "start",
                        lambda spec: started.append(spec) or f"R{len(started)}")
    got = TestClient(app).post("/api/analysis/start", json={
        "ticker": "AAPL", "trade_date": "2026-08-20",
        "models": ["gemini-3.5-flash", "qwen3.7-max"]}).json()
    assert [r["model"] for r in got["run_ids"]] == ["gemini-3.5-flash",
                                                    "qwen3.7-max"]
    assert [s["model"] for s in started] == ["gemini-3.5-flash", "qwen3.7-max"]
    assert all("models" not in s for s in started), "the list is not passed on"
    assert got["run_id"] == "R1"


def test_a_single_model_still_returns_one_run(monkeypatch):
    from fastapi.testclient import TestClient

    from tradingagents.api import app
    monkeypatch.setattr(aj, "start", lambda spec: "SOLO")
    got = TestClient(app).post("/api/analysis/start", json={
        "ticker": "AAPL", "trade_date": "2026-08-20",
        "model": "gemini-3.5-flash"}).json()
    assert got["run_id"] == "SOLO" and len(got["run_ids"]) == 1


def test_the_markdown_export_carries_every_section_and_its_provenance(
        monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from tradingagents.api import app
    monkeypatch.setattr(aj, "status", lambda rid: {
        "run_id": rid, "running": False,
        "spec": {"ticker": "TSLA", "trade_date": "2026-08-20",
                 "model": "gemini-3.5-flash", "analysts": ["social"],
                 "social_source": "both", "twitter_keywords": ["robotaxi"]},
        "reports": {"Sentiment Analyst": "X was polarized."},
        "decision": "**Rating**: Overweight"})
    got = TestClient(app).get("/api/analysis/TSLA-1/report.md")
    assert got.status_code == 200
    assert "attachment" in got.headers["content-disposition"]
    assert "TSLA-1.md" in got.headers["content-disposition"]
    body = got.text
    assert "## Sentiment Analyst" in body and "X was polarized." in body
    assert "## Final decision" in body and "Overweight" in body
    assert "social source: both" in body and "robotaxi" in body


def test_exporting_an_unknown_run_is_a_404(monkeypatch):
    from fastapi.testclient import TestClient

    from tradingagents.api import app
    monkeypatch.setattr(aj, "status", lambda rid: {"running": False,
                                                   "error": "no such run"})
    assert TestClient(app).get("/api/analysis/nope/report.md").status_code == 404


def test_static_analysis_routes_are_not_swallowed_by_the_run_id_route():
    """FastAPI matches in declaration order: /api/analysis/tickers must be
    declared BEFORE /api/analysis/{run_id}, or it resolves as a run named
    'tickers' (it did, 2026-08-21)."""
    from fastapi.testclient import TestClient

    from tradingagents.api import app
    got = TestClient(app).get("/api/analysis/tickers").json()
    assert "rows" in got and got["rows"], "shadowed by {run_id}"
    assert {"symbol", "name"} <= set(got["rows"][0])
    import tickers
    assert len(got["rows"]) == len(tickers.TICKERS)
