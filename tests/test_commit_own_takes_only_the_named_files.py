"""scripts/commit_own.py — the guard for RCA-2026-09-28-E.

Sep 28, 2026 ~2:55pm: `git commit` after `git add <my files>` committed the
SHARED index, which already held another session's staged work: 11 files
for a 5-file change (7cad08956a72), on both mains for about twenty minutes.
Each test builds its own repository under tmp_path; nothing here touches
this checkout.
"""
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("commit_own", ROOT / "scripts" / "commit_own.py")
co = importlib.util.module_from_spec(spec)
spec.loader.exec_module(co)

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git is not installed")


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          check=True).stdout


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "mine.txt").write_text("one\n")
    (tmp_path / "theirs.txt").write_text("one\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "start")
    return tmp_path


def test_another_sessions_staged_files_stay_staged_and_out_of_the_commit(repo):
    (repo / "theirs.txt").write_text("their unfinished work\n")
    _git(repo, "add", "theirs.txt")                         # staged by the other session
    (repo / "mine.txt").write_text("my change\n")
    before = _git(repo, "rev-parse", "HEAD").strip()

    new = co.commit_own(["mine.txt"], "my change\n", repo=repo)

    assert _git(repo, "rev-parse", "HEAD").strip() == new != before
    assert _git(repo, "diff", "--name-only", f"{before}..{new}").split() == ["mine.txt"]
    assert _git(repo, "show", f"{new}:theirs.txt") == "one\n"
    # their staging is exactly as they left it; mine is not left staged
    assert _git(repo, "diff", "--cached", "--name-only").split() == ["theirs.txt"]
    assert _git(repo, "show", ":theirs.txt") == "their unfinished work\n"


def test_nothing_to_commit_and_a_moved_head_change_nothing(repo, monkeypatch):
    before = _git(repo, "rev-parse", "HEAD").strip()
    with pytest.raises(ValueError, match="nothing to commit"):
        co.commit_own(["mine.txt"], "nothing\n", repo=repo)
    (repo / "mine.txt").write_text("my change\n")
    real = co._git

    def other_session_commits_first(args, r, env=None):
        if args[:1] == ["update-ref"]:
            (repo / "theirs.txt").write_text("theirs, committed meanwhile\n")
            _git(repo, "commit", "-q", "-m", "theirs", "--", "theirs.txt")
        return real(args, r, env)

    monkeypatch.setattr(co, "_git", other_session_commits_first)
    with pytest.raises(RuntimeError, match="HEAD moved"):
        co.commit_own(["mine.txt"], "mine\n", repo=repo)
    assert _git(repo, "log", "-1", "--format=%s").strip() == "theirs", "their commit stands"
    assert before != _git(repo, "rev-parse", "HEAD").strip()
