"""The fixer: one Claude run at a time on this PC checks each filed fault
(Oct 07, 2026; spec docs/superpowers/specs/2026-10-07-errors-become-issues-design.md).

What these hold: one run at a time (an exclusive lock, never a pid alone),
at most eight a day, ninety minutes each; the run reads the LOCAL evidence
file and never the public issue's text; a verdict file — never prose — moves
the issue; a run that leaves no verdict is `needs-you`; the run is detached
so the back-end restart it performs cannot kill it.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from tradingagents import error_fixer as fx
from tradingagents import error_issues as ei
from tradingagents import portable

T0 = 1791380000.0   # Oct 07, 2026 10:13am


class FakeGh:
    def __init__(self):
        self.calls: list = []

    def __call__(self, args, input_text=None):
        self.calls.append((list(args), input_text))
        return ""


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(ei, "HOME", tmp_path)
    monkeypatch.setattr(ei, "STATE", tmp_path / "error_issues.json")
    monkeypatch.setattr(ei, "FIXER_DIR", tmp_path / "fixer")
    monkeypatch.setattr(ei, "_LABELS_MADE", set(ei.LABELS))
    (tmp_path / "fixer").mkdir()
    bells: list = []
    from tradingagents import notifications

    monkeypatch.setattr(notifications, "record",
                        lambda kind, title, **kw: bells.append(title) or 1)
    return tmp_path, bells


def _fault(fp, *, state="queued", filed_at=T0, issue=101):
    st = ei._read()
    st["baseline"] = T0 - 3600
    st["faults"][fp] = {"source": "room", "kind": "cycle_failed", "label": "A check failed",
                        "message": f"fault {fp}", "rooms": ["4FC03172"], "count": 3,
                        "first": filed_at, "last": filed_at, "state": state,
                        "issue": issue, "url": f"https://github.com/x/issues/{issue}",
                        "filed_at": filed_at, "commented_at": filed_at}
    ei._write(st)
    ei.evidence_path(fp).write_text(json.dumps({"fingerprint": fp, "message": f"fault {fp}"}),
                                    encoding="utf-8")


class Spawned:
    def __init__(self):
        self.calls: list = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))

        class P:
            pid = 4242
        return P()


def test_one_queued_fault_starts_one_detached_run(home):
    _fault("aaaa00000001", filed_at=T0 + 10, issue=102)
    _fault("bbbb00000002", filed_at=T0, issue=101)
    spawn = Spawned()
    got = fx.tick(T0 + 100, spawn=spawn, gh=FakeGh())
    assert len(spawn.calls) == 1
    cmd, kw = spawn.calls[0]
    assert cmd[1:] == ["-m", "tradingagents.error_fixer", "run", "bbbb00000002"]
    # detached: the back-end restart the run performs cannot take it down
    for k, v in portable.DETACHED.items():
        assert kw.get(k) == v
    assert got["started"] == "bbbb00000002"
    assert ei._read()["faults"]["bbbb00000002"]["state"] == "checking"


def test_no_second_run_while_one_is_going(home):
    _fault("aaaa00000001")
    with open(fx._lock_path(), "a+") as held:
        portable.lock_exclusive(held, blocking=False)
        spawn = Spawned()
        got = fx.tick(T0 + 100, spawn=spawn, gh=FakeGh())
        portable.unlock(held)
    assert spawn.calls == [] and got.get("running")


def test_the_ninth_run_of_a_day_waits(home):
    _fault("aaaa00000001")
    fx._runs_path().write_text(json.dumps(
        [{"fp": f"x{i}", "started": T0 - 60 * i} for i in range(fx.MAX_RUNS_PER_DAY)]),
        encoding="utf-8")
    spawn = Spawned()
    got = fx.tick(T0 + 100, spawn=spawn, gh=FakeGh())
    assert spawn.calls == [] and "8" in got.get("waiting", "")
    # yesterday's runs do not count
    fx._runs_path().write_text(json.dumps(
        [{"fp": f"x{i}", "started": T0 - 86400 * 2} for i in range(fx.MAX_RUNS_PER_DAY)]),
        encoding="utf-8")
    fx.tick(T0 + 200, spawn=spawn, gh=FakeGh())
    assert len(spawn.calls) == 1


@pytest.mark.parametrize("verdict,state", [("fixed", "fixed"),
                                           ("not_a_fault", "not_a_fault"),
                                           ("needs_you", "needs_you")])
def test_a_verdict_file_moves_the_issue_once(home, verdict, state, monkeypatch):
    monkeypatch.setattr(fx, "_commit_landed", lambda commit: True)
    _fault("aaaa00000001", state="checking")
    fx.result_path("aaaa00000001").write_text(json.dumps(
        {"verdict": verdict, "commit": "abc1234", "summary": "plain words"}), encoding="utf-8")
    gh = FakeGh()
    fx.tick(T0 + 100, spawn=Spawned(), gh=gh)
    rec = ei._read()["faults"]["aaaa00000001"]
    assert rec["state"] == state
    if verdict == "fixed":
        assert rec["commit"] == "abc1234"
    assert not fx.result_path("aaaa00000001").exists(), "a verdict is applied once"
    gh2 = FakeGh()
    fx.tick(T0 + 200, spawn=Spawned(), gh=gh2)
    assert not [c for c in gh2.calls if c[0][:2] == ["issue", "comment"]]


def test_a_run_that_ended_without_a_verdict_is_needs_you(home):
    _fault("aaaa00000001", state="checking")
    fx.log_path("aaaa00000001").write_text("line one\nthe last thing it said\n",
                                           encoding="utf-8")
    gh = FakeGh()
    fx.tick(T0 + 100, spawn=Spawned(), gh=gh)
    assert ei._read()["faults"]["aaaa00000001"]["state"] == "needs_you"
    said = " ".join(c[1] or "" for c in gh.calls)
    assert "without a verdict" in said
    # NEVER the log itself on a public issue: its last lines are raw tool
    # output, a `cat` of the key file among them (final review, C2) — the
    # issue names where the log is on the PC instead
    assert "the last thing it said" not in said
    assert str(fx.log_path("aaaa00000001")) in said


def test_a_run_that_said_nothing_never_posts_its_log(home):
    _fault("aaaa00000001", state="checking")
    fx.log_path("aaaa00000001").write_text('{"api_key": "mx0LEAKED12345"}\n', encoding="utf-8")
    got = fx.run("aaaa00000001", popen=FakePopen(code=1), now=T0)
    assert "mx0LEAKED12345" not in got["summary"] and "api_key" not in got["summary"]
    assert str(fx.log_path("aaaa00000001")) in got["summary"]


def test_a_fixed_verdict_whose_commit_is_not_on_github_is_needs_you(home, monkeypatch):
    """I8: "fixed" was taken on the run's word — the issue closed and the tab
    said "fixed in <hash>" even for a commit that never reached GitHub."""
    monkeypatch.setattr(fx, "_commit_landed", lambda commit: False)
    _fault("aaaa00000001", state="checking")
    fx.result_path("aaaa00000001").write_text(json.dumps(
        {"verdict": "fixed", "commit": "dead123", "summary": "x"}), encoding="utf-8")
    gh = FakeGh()
    fx.tick(T0 + 100, spawn=Spawned(), gh=gh)
    rec = ei._read()["faults"]["aaaa00000001"]
    assert rec["state"] == "needs_you"
    assert "dead123" in " ".join(c[1] or "" for c in gh.calls)


def test_the_run_cannot_reach_the_public_issue_or_the_web(home):
    """I7: the issue's text is one `gh issue view` away from a run with every
    permission; the run is denied the tools that read it."""
    _fault("aaaa00000001", state="checking")
    p = FakePopen(writes=(fx.result_path("aaaa00000001"),
                          {"verdict": "not_a_fault", "summary": "x"}))
    fx.run("aaaa00000001", popen=p, now=T0)
    denied = p.cmd[p.cmd.index("--disallowedTools") + 1:]
    for tool in ("Bash(gh issue:*)", "Bash(gh api:*)", "WebFetch", "WebSearch"):
        assert tool in denied, tool
    prompt = p.cmd[p.cmd.index("-p") + 1]
    assert "#101" not in prompt and "issues/" not in prompt


def test_the_run_does_not_inherit_the_parent_claude_session(home, monkeypatch):
    """M7: the site may have been started from a Claude session; its
    CLAUDE* settings (session id, attended flag, messaging socket) are not
    the fixer's."""
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent-session")
    _fault("aaaa00000001", state="checking")
    p = FakePopen(writes=(fx.result_path("aaaa00000001"),
                          {"verdict": "not_a_fault", "summary": "x"}))
    fx.run("aaaa00000001", popen=p, now=T0)
    assert not [k for k in p.kw["env"] if k.upper().startswith("CLAUDE")]
    assert p.kw["env"]["TA_FIXER"] == "1"


# ------------------------------------------------------------------ the run

class FakePopen:
    def __init__(self, *, code=0, hang=False, writes=None):
        self.code, self.hang, self.writes = code, hang, writes
        self.cmd = None
        self.kw = None
        self.pid = 5151

    def __call__(self, cmd, **kw):
        self.cmd, self.kw = cmd, kw
        return self

    def wait(self, timeout=None):
        if self.hang:
            raise subprocess.TimeoutExpired(self.cmd, timeout)
        if self.writes:
            path, payload = self.writes
            path.write_text(json.dumps(payload), encoding="utf-8")
        return self.code


def test_the_run_is_claude_on_the_local_evidence(home, monkeypatch):
    _fault("aaaa00000001", state="checking")
    p = FakePopen(writes=(fx.result_path("aaaa00000001"),
                          {"verdict": "not_a_fault", "summary": "the PC lost power"}))
    got = fx.run("aaaa00000001", popen=p, now=T0)
    assert got["verdict"] == "not_a_fault"
    assert p.cmd[0] == str(fx.CLAUDE_EXE)
    assert "-p" in p.cmd and "--dangerously-skip-permissions" in p.cmd
    prompt = p.cmd[p.cmd.index("-p") + 1]
    assert str(ei.evidence_path("aaaa00000001")) in prompt
    assert str(fx.result_path("aaaa00000001")) in prompt
    assert str(ei.FIXER_DIR) in prompt
    assert p.kw["cwd"] == str(ei.REPO_ROOT)
    assert p.kw["creationflags"] & getattr(subprocess, "CREATE_NO_WINDOW", 0) == \
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # a fixer's prompt is not the operator's words: the hook must not record it
    assert p.kw["env"].get("TA_FIXER") == "1"


def test_a_run_that_says_nothing_is_needs_you(home):
    _fault("aaaa00000001", state="checking")
    got = fx.run("aaaa00000001", popen=FakePopen(code=3), now=T0)
    assert got["verdict"] == "needs_you" and "exit code 3" in got["summary"]
    assert json.loads(fx.result_path("aaaa00000001").read_text(encoding="utf-8"))["verdict"] \
        == "needs_you"


def test_a_run_past_its_limit_is_stopped(home, monkeypatch):
    _fault("aaaa00000001", state="checking")
    killed: list = []
    monkeypatch.setattr(portable, "kill_tree", lambda pid, **kw: killed.append(pid))
    got = fx.run("aaaa00000001", popen=FakePopen(hang=True), now=T0)
    assert killed == [5151]
    assert got["verdict"] == "needs_you" and "90 minutes" in got["summary"]


def test_a_second_run_cannot_start_beside_the_first(home):
    _fault("aaaa00000001", state="checking")
    with open(fx._lock_path(), "a+") as held:
        portable.lock_exclusive(held, blocking=False)
        p = FakePopen()
        got = fx.run("aaaa00000001", popen=p, now=T0)
        portable.unlock(held)
    assert got.get("skipped") and p.cmd is None


def test_the_prompt_holds_the_rules_that_matter():
    text = fx.prompt_for("aaaa00000001")
    for must in ("python start.py api", "scripts/commit_own.py",
                 "git push origin HEAD:main", "git push colleague HEAD:main",
                 "docs/RCA.md", "start.py start", "real money", "needs_you",
                 "not_a_fault", "fixed", "failing test",
                 # M6: only on main, and a restart that fails is said out loud
                 "git branch --show-current", "did not come back"):
        assert must in text, must
