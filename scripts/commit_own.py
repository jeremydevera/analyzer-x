"""Commit ONLY the named paths, built from a private index — never the shared one.

RCA-2026-09-28-E: two Claude sessions share this checkout and its
`.git/index`. A plain `git commit` after `git add <my files>` also committed
another session's STAGED files (7cad08956a72: 11 files for a 5-file change),
and both mains carried its unfinished code for about twenty minutes.

    python scripts/commit_own.py -F message.txt path [path ...]
    python scripts/commit_own.py -m "subject" path [path ...]

The commit is HEAD plus the working-tree content of exactly the named paths
(a deleted path is removed). What it holds is printed BEFORE HEAD moves, and
it is refused when that list strays outside the named paths. HEAD moves by
compare-and-swap, so a commit another session made in between is never
overwritten; the shared index's entries for those paths are then pointed at
the new commit, and every other staged entry is left exactly as it was.

A path that holds another session's hunks beside yours is still yours to
check first (`git diff HEAD -- <path>`): this commits whole files.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _git(args: list[str], repo: Path, env: dict | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True,
                       text=True, encoding="utf-8")
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def commit_own(paths: list[str], message: str, repo: str | Path = ".") -> str:
    """The new commit's id. Raises, changing nothing, when the commit would
    hold nothing, hold a path not named, or HEAD moved underneath it."""
    repo = Path(repo).resolve()
    if not paths:
        raise ValueError("name the paths to commit")
    head = _git(["rev-parse", "HEAD"], repo).strip()
    index = Path(_git(["rev-parse", "--absolute-git-dir"], repo).strip()) / \
        f"commit_own-{os.getpid()}.index"
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    try:
        _git(["read-tree", head], repo, env)
        _git(["add", "-A", "--", *paths], repo, env)
        held = [p for p in _git(["diff", "--cached", "--name-only", head], repo, env).splitlines() if p]
        if not held:
            raise ValueError(f"nothing to commit in {', '.join(paths)}")
        named = [Path(p).as_posix().rstrip("/") for p in paths]
        strays = [p for p in held if not any(p == n or p.startswith(n + "/") for n in named)]
        if strays:
            raise ValueError(f"the commit would hold paths not named: {', '.join(strays)}")
        print(_git(["diff", "--cached", "--stat", head], repo, env), end="")
        tree = _git(["write-tree"], repo, env).strip()
    finally:
        index.unlink(missing_ok=True)
    new = subprocess.run(["git", "commit-tree", tree, "-p", head, "-F", "-"], cwd=repo,
                         input=message, capture_output=True, text=True, encoding="utf-8")
    if new.returncode:
        raise RuntimeError(f"git commit-tree failed: {new.stderr.strip()}")
    commit = new.stdout.strip()
    try:
        # compare-and-swap: refuses if another session committed meanwhile
        _git(["update-ref", "HEAD", commit, head], repo)
    except RuntimeError as exc:
        raise RuntimeError(f"HEAD moved while committing; nothing was changed ({exc})") from exc
    _git(["reset", "-q", commit, "--", *paths], repo)
    return commit


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("-m", dest="message")
    g.add_argument("-F", dest="file")
    ap.add_argument("paths", nargs="+")
    a = ap.parse_args(argv)
    message = a.message if a.message is not None else Path(a.file).read_text(encoding="utf-8")
    try:
        print(commit_own(a.paths, message))
    except (ValueError, RuntimeError) as exc:
        print(f"not committed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
