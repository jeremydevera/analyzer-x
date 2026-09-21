"""Pointing the sweeps at a FORK must refuse in words, not in a traceback.

`Sep 21, 2026`: the operator asked to run the market sweeps on a partner's
GitHub — *"i want to use my colleague's github for github action"*, then
*"do it yourself"*. The fork was made (`jeremydvera/analyzer-x`), the secret
set, the remote added, and `cloud_sweep.available()` raised
`JSONDecodeError: Expecting value: line 1 column 1 (char 0)`.

Why: GitHub registers **no workflows at all** on a fresh fork until a person
opens its Actions tab and presses *"I understand my workflows, go ahead and
enable them"* — the files are there (all four), `actions/workflows` answers
`total_count: 0`, and `gh workflow list --json …` prints an empty string.
`json.loads("")` is a crash where a sentence belongs, and there is no API for
that click, so the sentence has to name it.
"""
from __future__ import annotations

import pytest

from tradingagents import cloud_sweep as cs


@pytest.fixture
def slug(monkeypatch):
    monkeypatch.setattr(cs, "repo_slug", lambda cwd=None: "partner/analyzer-x")


def test_a_forks_empty_answer_is_a_sentence_not_a_crash(slug, monkeypatch):
    monkeypatch.setattr(cs, "_gh", lambda *a, **k: "")
    ok, why = cs.available()
    assert ok is False
    assert "fork" in why.lower(), why
    assert "partner/analyzer-x/actions" in why, "it links the page to open"
    assert "enable" in why.lower(), "and names the button to press"


def test_rubbish_from_gh_is_also_a_sentence(slug, monkeypatch):
    """Whatever `gh` prints, a refusal is a refusal — never a traceback out
    of the button the operator pressed."""
    monkeypatch.setattr(cs, "_gh", lambda *a, **k: "not json at all")
    ok, why = cs.available()
    assert ok is False and "workflows" in why


def test_a_repo_with_workflows_but_not_ours_still_names_the_missing_one(slug, monkeypatch):
    monkeypatch.setattr(cs, "_gh", lambda *a, **k: '[{"name":"ci","state":"active"}]')
    ok, why = cs.available()
    assert ok is False
    assert cs.WORKFLOW in why and "no" in why.lower()


def test_a_ready_repo_answers_yes_with_its_slug(slug, monkeypatch):
    monkeypatch.setattr(
        cs, "_gh",
        lambda *a, **k: f'[{{"name":"{cs.WORKFLOW}","state":"active"}}]')
    ok, why = cs.available()
    assert ok is True and why == "partner/analyzer-x"


def test_the_sweeps_follow_the_second_remote(tmp_path):
    """How the switch is made at all: a remote that is not `origin` wins, so
    adding the partner's fork moves every sweep to their machines, and
    removing it moves them back."""
    import subprocess

    def git(*args):
        subprocess.run(("git",) + args, cwd=tmp_path, capture_output=True, text=True)

    git("init", "-q")
    git("remote", "add", "origin", "https://github.com/jeremydevera/analyzer-x")
    assert cs.repo_slug(cwd=str(tmp_path)) == "jeremydevera/analyzer-x"
    git("remote", "add", "colleague", "https://github.com/jeremydvera/analyzer-x")
    assert cs.repo_slug(cwd=str(tmp_path)) == "jeremydvera/analyzer-x"
    git("remote", "remove", "colleague")
    assert cs.repo_slug(cwd=str(tmp_path)) == "jeremydevera/analyzer-x"
