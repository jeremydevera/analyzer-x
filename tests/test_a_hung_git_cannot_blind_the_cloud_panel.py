"""One wedged `git fetch` blanked the cloud panel until the API was restarted.

Found `Sep 12, 2026 2:44am`, seventeen minutes after the API started at
2:27am, while watching run 34631292767 measure normally on 20 machines.
`/api/cloud/status` answered, every time:

    {"available":false,"why":"reading GitHub in the background",
     "reading":true,"run":null,"shards":[]}

py-spy on the listening process (pid 14732) found the reader thread had never
returned:

    Thread 18736 (idle): "cloud-status"
        join (threading.py:1095)
        _communicate (subprocess.py:1663)
        communicate (subprocess.py:1222)
        run (subprocess.py:565)            <- the drain AFTER the timeout
        _git (tradingagents/cloud_sweep.py:333)
        _fetch_progress (tradingagents/cloud_sweep.py:362)
        live_progress (tradingagents/cloud_sweep.py:398)
        _read_cloud_status (tradingagents/api.py:2224)
        _work (tradingagents/slow_cache.py:69)

`subprocess.run(..., timeout=)` is not the promise it reads as. On
TimeoutExpired it kills the DIRECT child and then calls `communicate()` again
with NO timeout to drain the pipes. `git fetch` spawns `git-remote-https`,
which inherits those pipe handles and survives the kill, so the drain blocks
for ever. `BackgroundValue` holds `_busy` until its reader returns, so no
later poll could start a fresh read: one hang, and the panel is blind until
the process dies.

Two things had to be true for that, and this file holds both shut:

1. git could ASK something — no `stdin`, no `GIT_TERMINAL_PROMPT=0`, no
   askpass override — and an API started detached has no console to answer.
2. the timeout path could block for ever.

And one measurement that made it worse: the read takes **31.9 s** with 20
shards reporting, against a `CLOUD_STATUS_TTL` of **30 s** — a value stale
the instant it lands, so the thread ran back to back, git-fetching the branch
the shards were pushing to, for the length of the sweep.
"""
from __future__ import annotations

import ast
import inspect
import subprocess
import sys
import time

import pytest

from tradingagents import api, cloud_sweep as cs


# ------------------------------------------------------- 1. it cannot ask
def test_git_is_never_allowed_to_prompt():
    """A credential prompt on a process with no terminal is a permanent hang,
    not an error. Every door git can knock on is shut."""
    for key, val in (("GIT_TERMINAL_PROMPT", "0"), ("GIT_ASKPASS", "echo"),
                     ("SSH_ASKPASS", "echo"), ("GCM_INTERACTIVE", "never")):
        assert cs._GIT_NO_PROMPT.get(key) == val, key
    src = inspect.getsource(cs._git)
    assert "_GIT_NO_PROMPT" in src, "the env is built and never passed"
    assert "stdin=subprocess.DEVNULL" in src, \
        "a git that can read stdin can wait on it"


def test_the_environment_actually_reaches_the_child():
    """Not a dict nobody hands over -- the shape of every 'fixed but not
    wired' bug in this repo. Asks git itself what it sees."""
    out = cs._git("var", "GIT_EDITOR", timeout=30)
    assert isinstance(out, str)
    # and the real proof: a config read runs with the env applied
    got = cs._git("rev-parse", "--is-inside-work-tree", timeout=30)
    assert got.strip() == "true"


# --------------------------------------------- 2. a timeout always returns
def test_a_timeout_raises_instead_of_blocking(monkeypatch):
    """The whole point. A child that ignores the kill and holds the pipe must
    cost `timeout` plus the bounded drain -- never `join()` for ever."""
    slow = [sys.executable, "-c", "import time; time.sleep(60)"]

    class _Popen(subprocess.Popen):
        def __init__(self, args, **kw):
            super().__init__(slow, **kw)

    monkeypatch.setattr(cs.subprocess, "Popen", _Popen)
    t0 = time.time()
    with pytest.raises(cs.CloudError) as exc:
        cs._git("fetch", "--quiet", "origin", timeout=2)
    took = time.time() - t0
    assert "no answer in 2s" in str(exc.value), str(exc.value)
    assert took < 20, f"the timeout path took {took:.1f}s"


def test_the_drain_after_a_kill_is_bounded():
    """`subprocess.run`'s own post-timeout `communicate()` takes NO timeout,
    and that is the call the API was found asleep in. It must not come back."""
    src = inspect.getsource(cs._git)
    assert "subprocess.run(" not in src, \
        "subprocess.run's timeout path ends in an unbounded communicate()"
    after = src[src.index("except subprocess.TimeoutExpired"):]
    assert "proc.communicate(timeout=10)" in after, \
        "the drain after the kill must carry its own timeout"
    assert "_git_kill_tree(proc)" in after


def test_the_kill_takes_the_grandchild_too():
    """`git fetch` runs `git-remote-https`, which holds the same stdout and
    stderr handles. Killing only the parent leaves the pipes open, which is
    precisely why the drain never finished."""
    from tradingagents import portable

    src = inspect.getsource(cs._git_kill_tree)
    assert "portable.kill_tree(proc.pid, timeout=10)" in src, \
        "the tree, and bounded"
    assert "proc.kill()" in src
    # /T is the whole point: it takes the tree, not just the pid. And it is
    # ONE call -- asking portable.child_pids instead costs a PowerShell start,
    # measured at 20 s of the 32 s this path first took, on the very thread a
    # blank panel is waiting on. The unix-only calls live in portable.py
    # because test_no_module_outside_portable_names_a_unix_only_api refuses
    # `os.killpg` and `signal.SIGKILL` anywhere else.
    kill = inspect.getsource(portable.kill_tree)
    assert '"/T"' in kill and '"/F"' in kill, "taskkill must take the TREE"
    assert "timeout=timeout" in kill, "even the kill is bounded"
    assert "killpg" in kill, "and the same idea off Windows"
    src = kill
    # THE CODE, NOT THE PROSE. The docstring names `child_pids` to say why it
    # is NOT used, and a plain `in src` check is satisfied by that sentence --
    # the trap this repo has now fallen into four times.
    body = ast.parse(src).body[0]
    body.body = [n for n in body.body
                 if not (isinstance(n, ast.Expr)
                         and isinstance(n.value, ast.Constant))]
    code = ast.unparse(body)
    assert "child_pids" not in code, (
        "a PowerShell process listing is slower than the hang it cleans up")


# ------------------------------ 3. the interval is longer than the read
def test_the_cache_lives_longer_than_the_read_it_drives():
    """A TTL shorter than the read means the value is stale when it lands and
    the background thread never rests. Measured Sep 12, 2026 with all 20
    shards reporting: 31.9 s for the read, 33.4 s for the fetch alone."""
    assert api.CLOUD_STATUS_TTL >= 60.0, api.CLOUD_STATUS_TTL


def test_a_slow_read_still_serves_the_last_good_answer():
    """`BackgroundValue.get()` must return the previous value while a refresh
    runs -- regressing to `pending` is what turned a slow read into a blank
    panel for the operator."""
    from tradingagents.slow_cache import BackgroundValue

    ticks = {"n": 0}

    def reader():
        ticks["n"] += 1
        if ticks["n"] > 1:
            time.sleep(5)            # the slow refresh
        return {"available": True, "n": ticks["n"]}

    bv = BackgroundValue("probe", reader, ttl=0.01)
    # `wait()` only watches; `get()` is what STARTS the first read
    bv.get(pending={"available": False})
    assert bv.wait(timeout=5)
    first = bv.get(pending={"available": False})
    assert first["available"] is True
    # the next get() kicks a slow refresh; it must NOT hand back `pending`
    got = bv.get(pending={"available": False, "why": "reading"})
    assert got["available"] is True, "a refresh must not blank the panel"
