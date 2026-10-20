"""GitHub machines on the Errors tab (operator, Oct 19, 2026: *"can you do a
logging option where if there is error in github machines it will save the
log in error tab"*).

A fake `gh` stands in for GitHub: no test reaches either account. The cases
are the real ones found on the first live look: a costs machine that ended
`##[error]Process completed with exit code 1.` with its log, and a replay
machine GitHub LOST (annotation "The hosted runner lost communication with
the server", log answer 404 BlobNotFound) — which must still be listed, with
GitHub's note as the reason.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradingagents import github_errors as ge

REPO = Path(__file__).resolve().parent.parent
NOW = 1_790_000_000.0
T = "2026-09-20T12:00:00Z"
LOG = ("2026-09-20T12:00:00.0000001Z [costs 12] ZIL_USDT: done\n"
       "2026-09-20T12:00:01.0000001Z \x1b[31mTO DO AGAIN: BLUAI_USDT 2026-09-23\x1b[0m\n"
       "2026-09-20T12:00:02.0000001Z ##[error]Process completed with exit code 1.\n"
       "2026-09-20T12:00:03.0000001Z Post job cleanup.\n")


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(ge, "home", lambda: tmp_path / "github_errors")
    return tmp_path / "github_errors"


class FakeGh:
    def __init__(self, runs, jobs, logs, notes):
        self.runs, self.jobs, self.logs, self.notes, self.calls = runs, jobs, logs, notes, []

    def __call__(self, *args):
        self.calls.append(args)
        path = args[-1]
        if "/actions/workflows" in path:
            return json.dumps({"workflows": [{"id": 7, "name": "Costs per minute"},
                                             {"id": 8, "name": "Watcher replay"}]})
        if "/actions/runs?" in path:
            return json.dumps({"workflow_runs": self.runs.get(path.split("/actions")[0], [])})
        if path.endswith("/annotations") or "/annotations" in path:
            jid = int(path.split("/check-runs/")[1].split("/")[0])
            return json.dumps(self.notes.get(jid, []))
        if "/jobs?" in path:
            rid = int(path.split("/runs/")[1].split("/")[0])
            return json.dumps({"jobs": self.jobs.get(rid, [])})
        if path.endswith("/logs"):
            jid = int(path.split("/jobs/")[1].split("/")[0])
            if jid not in self.logs:
                raise RuntimeError("gh: HTTP 404 BlobNotFound")
            return self.logs[jid]
        raise AssertionError(path)


def _run(rid, conclusion, wf=7):
    return {"id": rid, "name": f"Costs per minute · run {rid}", "display_title": f"title {rid}",
            "conclusion": conclusion, "html_url": f"https://github.com/x/runs/{rid}",
            "created_at": T, "updated_at": T, "workflow_id": wf}


def _job(jid, conclusion, step="Costs shard 12"):
    return {"id": jid, "name": f"costs ({jid})", "conclusion": conclusion,
            "started_at": T, "completed_at": T,
            "steps": [{"name": "Install", "conclusion": "success"},
                      {"name": step, "conclusion": conclusion}]}


def _gh():
    return FakeGh(
        runs={"repos/a/analyzer-x": [_run(1, "failure"), _run(2, "success"), _run(3, "cancelled")],
              "repos/b/analyzer-x": [_run(9, "failure", wf=8)]},
        jobs={1: [_job(11, "failure"), _job(12, "success")],
              9: [_job(91, "failure", step="Replay shard 2")]},
        logs={11: LOG},
        notes={11: [{"annotation_level": "failure", "message": "Process completed with exit code 1."},
                    {"annotation_level": "notice", "message": "ubuntu-latest will move"}],
               91: [{"annotation_level": "failure",
                     "message": "The hosted runner lost communication with the server."}]})


def test_only_red_runs_are_saved_with_their_red_machines_logs(home):
    gh = _gh()
    got = ge.tick(NOW, gh=gh, slugs=["a/analyzer-x", "b/analyzer-x"])
    assert got == {"saved": 2, "removed": 0, "problems": []}
    d = ge.listing()
    assert d["matched"] == 2 and d["last_error"] == "" and d["last_ok"] == NOW
    assert d["workflows"] == ["Costs per minute", "Watcher replay"], "the workflow's name, not the run's title"
    costs = next(r for r in d["rows"] if r["account"] == "a")
    assert costs["red"] == 1 and costs["machines"] == 2 and len(costs["jobs"]) == 1
    j = costs["jobs"][0]
    assert j["step"] == "Costs shard 12"
    assert j["error"] == "Process completed with exit code 1."
    assert "TO DO AGAIN: BLUAI_USDT" in j["context"] and "\x1b" not in j["context"]
    assert not j["context"].startswith("2026-"), "GitHub's time stamps are taken off"
    saved = ge.log_text(j["log"])
    assert "##[error]Process completed" in saved and "\x1b" not in saved
    assert j["notes"] == ["Process completed with exit code 1."], "notices are left out"


def test_a_machine_github_lost_is_still_listed_with_githubs_reason(home):
    ge.tick(NOW, gh=_gh(), slugs=["a/analyzer-x", "b/analyzer-x"])
    lost = next(r for r in ge.listing()["rows"] if r["account"] == "b")["jobs"][0]
    assert lost["log"] is None and "kept no log" in lost["log_why"]
    assert lost["notes"] == ["The hosted runner lost communication with the server."]


def test_a_run_is_fetched_once_and_a_pass_waits_its_turn(home):
    gh = _gh()
    ge.tick(NOW, gh=gh, slugs=["a/analyzer-x"])
    assert ge.tick(NOW + 60, gh=gh, slugs=["a/analyzer-x"]) == {"skipped": "not due"}
    n = len(gh.calls)
    got = ge.tick(NOW + ge.POLL_S, gh=gh, slugs=["a/analyzer-x"])
    assert got["saved"] == 0
    assert not [c for c in gh.calls[n:] if "/jobs" in c[-1]], "a saved run is never fetched again"


def test_a_pass_that_cannot_ask_github_says_so_and_tries_again(home):
    class Down(FakeGh):
        def __call__(self, *args):
            raise RuntimeError("gh timed out: api repos/a/analyzer-x/actions/runs")
    ge.tick(NOW, gh=Down({}, {}, {}, {}), slugs=["a/analyzer-x"])
    d = ge.listing()
    assert d["matched"] == 0 and "gh timed out" in d["last_error"] and d["last_ok"] is None
    got = ge.tick(NOW + ge.POLL_S, gh=_gh(), slugs=["a/analyzer-x"])
    assert got["saved"] == 1 and ge.listing()["last_error"] == ""


def test_a_run_whose_machines_could_not_be_read_is_not_recorded(home):
    gh = _gh()
    gh.jobs = None                       # the jobs call raises
    ge.tick(NOW, gh=gh, slugs=["a/analyzer-x"])
    assert ge.listing()["matched"] == 0 and ge.listing()["last_error"]


def test_secrets_never_reach_the_saved_log(home, monkeypatch):
    from tradingagents import error_issues as ei

    monkeypatch.setattr(ei, "scrub", lambda s: s.replace("SECRETVALUE", "[removed]"))
    gh = _gh()
    gh.logs[11] = LOG.replace("ZIL_USDT", "token=SECRETVALUE")
    ge.tick(NOW, gh=gh, slugs=["a/analyzer-x"])
    j = ge.listing()["rows"][0]["jobs"][0]
    assert "SECRETVALUE" not in ge.log_text(j["log"]) and "[removed]" in ge.log_text(j["log"])


def test_old_runs_go_with_their_logs(home):
    ge.tick(NOW, gh=_gh(), slugs=["a/analyzer-x"])
    name = ge.listing()["rows"][0]["jobs"][0]["log"]
    later = ge._iso(T) + (ge.KEEP_DAYS + 1) * 86_400
    gh = _gh()
    gh.runs = {}
    got = ge.tick(later, gh=gh, slugs=["a/analyzer-x"])
    assert got["removed"] == 1 and ge.listing()["total"] == 0 and ge.log_text(name) is None


def test_only_a_saved_log_can_be_opened(home):
    for bad in ("../index.json", "..\\..\\CLAUDE.md", "a-1.txt", "", "a/../b-1.log"):
        assert ge.log_text(bad) is None, bad


def test_the_list_filters_and_pages_on_the_server(home):
    gh = _gh()
    gh.runs["repos/a/analyzer-x"] = [_run(100 + i, "failure") for i in range(13)]
    gh.jobs.update({100 + i: [_job(1000 + i, "failure")] for i in range(13)})
    ge.tick(NOW, gh=gh, slugs=["a/analyzer-x", "b/analyzer-x"])
    assert ge.listing()["matched"] == 14
    a = ge.listing(account="a")
    assert a["matched"] == 13 and a["pages"] == 2 and len(a["rows"]) == ge.PER_PAGE
    assert len(ge.listing(account="a", page=2)["rows"]) == 3
    assert ge.listing(workflow="Watcher replay")["matched"] == 1


def test_the_errors_page_shows_the_section_and_the_routes_answer(home):
    page = (REPO / "webapp/src/app/(admin)/errors/page.tsx").read_text(encoding="utf-8")
    assert "<GithubMachinesErrors />" in page
    from fastapi import HTTPException

    from tradingagents import api

    assert api.github_errors_route()["matched"] == 0
    with pytest.raises(HTTPException) as e:
        api.github_error_log_route("../index.json")
    assert e.value.status_code == 404


def test_the_watchers_own_log_line_is_not_filed_as_a_fault():
    """The issue filer files any tagged site-log line saying 'failed' or
    'could not'; the watcher's own pass line must not invite that."""
    from tradingagents import error_issues as ei

    src = (REPO / "tradingagents/api.py").read_text(encoding="utf-8")
    i = src.index("def _github_errors_loop")
    lines = [ln for ln in src[i:i + 1500].splitlines() if "[github-errors]" in ln]
    assert lines and not [ln for ln in lines if ei._FAILING.search(ln.split('"')[1] if '"' in ln else ln)]
