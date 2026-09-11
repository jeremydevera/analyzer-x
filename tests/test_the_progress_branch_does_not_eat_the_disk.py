"""211 GB of abandoned git transfers on the drive the STORE lives on.

Found `Sep 12, 2026 3:41am`, while working out why the cloud panel's shard
detail would not arrive for a run that was measuring perfectly.

    tmp_pack files : 6,876       211.05 GB
    real .pack     :     59        6.97 GB
    oldest         : Sep 06, 2026 12:41pm
    newest         : Sep 12, 2026  3:41am   (still arriving)
    .git total     : 219.03 GB
    G: free        : 314.7 GB of 909.5

`.git/objects/pack/tmp_pack_*` is a PARTIAL TRANSFER. Git writes one while a
fetch runs and renames it on success; a fetch that is killed leaves it there
for ever, and git's own `count-objects -vH` calls them "garbage found".

Why there were 6,876 of them: twenty machines commit a small JSON file every
few seconds for the length of every run, so `origin/sweep-progress` had
**250,966 commits**. The whole history was fetched every time although only
the TIP is ever read (`git show <ref>:progress/run-<id>/shard-<n>.json`), the
fetch grew past its 180 s timeout, and each timeout left another partial pack.
A feedback loop: the bigger `.git` grew the slower the fetch, and the slower
the fetch the more often it was killed.

Two fixes, one per section:

* `--depth=1`, so the fetch carries the tip and not a quarter of a million
  commits nobody reads. Measured after: **69.3 s** for the first (which still
  establishes the boundary), then **42.8 s** and **19.3 s**.
* the partial packs are SWEPT, by age, in our own directory only — the rule
  CLAUDE.md already carries for `%TEMP%`: *"temporary" is a promise the code
  has to keep*, and a killed process never reaches its own cleanup.

After the sweep: `.git` **219.03 GB -> 11.04 GB**, G: free **314.7 -> 538.3
GB**, and main's history intact (695 commits, still reaching its original
root commit `c2fa046a9bc1`); only the four progress-branch tips are shallow.
"""
from __future__ import annotations

import ast
import inspect
import time

from tradingagents import cloud_sweep as cs


def _code(fn) -> str:
    """A function's CODE, with its docstring and comments gone.

    Every one of these assertions is of the form "this call is not made", and
    the explanation of why it is not made names it. A plain `in
    inspect.getsource(...)` is satisfied by that explanation -- the trap this
    repo has paid for four times (the `.toLocale` grep, the `p.set("days")`
    count, the `TemporaryDirectory` docstring, the `%Y` that was a `.year`).
    `ast.unparse` drops comments for free; the docstring is dropped here.
    """
    tree = ast.parse(inspect.getsource(fn).lstrip()).body[0]
    tree.body = [n for n in tree.body
                 if not (isinstance(n, ast.Expr)
                         and isinstance(n.value, ast.Constant)
                         and isinstance(n.value.value, str))]
    return ast.unparse(tree)


# --------------------------------------------------- 1. the fetch is shallow
def test_the_progress_branch_is_fetched_shallow():
    """Only the tip is ever read, so only the tip is ever taken."""
    assert "--depth=1" in cs._PROGRESS_FETCH, cs._PROGRESS_FETCH
    assert "--no-tags" in cs._PROGRESS_FETCH
    assert "--force" in cs._PROGRESS_FETCH, "the ref still has to be overridable"
    src = inspect.getsource(cs._fetch_progress)
    assert src.count("_PROGRESS_FETCH") == 2, \
        "BOTH the first fetch and the retry after a lock race"


def test_only_the_tip_is_ever_read():
    """The justification for --depth=1, asserted rather than assumed: if
    something ever walks this branch's history, the shallow fetch breaks it
    and this test is where that argument is recorded."""
    src = _code(cs.live_progress)
    assert "show" in src, "the reader is `git show <ref>:<path>`"
    for walker in ("rev-list", "--since", "merge-base", '"log"'):
        assert walker not in src, f"live_progress walks history via {walker}"


# ------------------------------------------------ 2. the leftovers are swept
def test_a_killed_fetch_does_not_leak_a_pack_for_ever(tmp_path, monkeypatch):
    """An hour-old partial pack goes; a live one stays; nothing else is
    touched. The newest 13 were MINUTES old when this was found and are
    exactly what a sweep must not take."""
    packs = tmp_path / ".git" / "objects" / "pack"
    packs.mkdir(parents=True)
    old = packs / "tmp_pack_OLD"
    live = packs / "tmp_pack_NOW"
    real = packs / "pack-abc123.pack"
    idx = packs / "pack-abc123.idx"
    for f in (old, live, real, idx):
        f.write_bytes(b"x" * 64)
    long_ago = time.time() - cs.DEAD_PACK_S - 60
    import os

    os.utime(old, (long_ago, long_ago))

    monkeypatch.setattr(cs.pathlib.Path, "resolve",
                        lambda self: tmp_path / "tradingagents" / "x.py")
    cs._SWEPT_AT[0] = 0.0
    cs._sweep_dead_packs()

    assert not old.exists(), "an hour-old partial transfer is dead weight"
    assert live.exists(), "a fetch running right now must keep its pack"
    assert real.exists() and idx.exists(), "a REAL pack is the repository"


def test_the_sweep_is_rate_limited(tmp_path, monkeypatch):
    """`live_progress` is called on a 90 s cache and the panel polls every 4 s.
    Globbing a pack directory on every one of those is the kind of tidiness
    that becomes the problem."""
    cs._SWEPT_AT[0] = time.time()
    calls = []
    monkeypatch.setattr(cs.pathlib.Path, "glob",
                        lambda self, pat: calls.append(pat) or [])
    cs._sweep_dead_packs()
    assert calls == [], "it swept again immediately"


def test_it_only_ever_touches_our_own_pack_directory():
    """Never `%TEMP%`, never another repository, never a name it did not
    write — the boundary RCA-2026-09-10-B drew for scratch directories."""
    src = _code(cs._sweep_dead_packs)
    assert "'tmp_pack_*'" in src, "by our own prefix, not everything"
    assert "'.git'" in src and "'objects'" in src and "'pack'" in src
    for wrong in ("TEMP", "gettempdir", "TemporaryDirectory", "rmtree"):
        assert wrong not in src, wrong


def test_a_pack_another_process_holds_open_is_not_an_error():
    """On Windows a file with an open handle cannot be removed. That is a
    normal outcome of sweeping beside a live fetch, not a failure worth
    raising into a progress read."""
    src = _code(cs._sweep_dead_packs)
    assert "except OSError" in src
    assert "continue" in src


def test_the_sweep_runs_before_the_fetch_that_might_leak():
    src = inspect.getsource(cs._fetch_progress)
    assert src.index("_sweep_dead_packs()") < src.index("_PROGRESS_FETCH"), \
        "sweeping after the fetch leaves this run's own leak until next time"


def test_it_says_how_much_it_freed():
    """208.36 GB went quietly once. A number nobody prints is a number nobody
    notices growing."""
    src = _code(cs._sweep_dead_packs)
    assert "logger.warning" in src
    assert "GB" in src and "freed" in src
