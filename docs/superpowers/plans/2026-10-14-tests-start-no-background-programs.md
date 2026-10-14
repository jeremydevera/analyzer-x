# Tests Start No Background Programs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No test run ever leaves a program running on the operator's PC: every
background launch a test makes is answered by a stand-in, unless the test asks
for the real program.

**Architecture:** One guard in `tests/conftest.py`, installed for the whole
session in `pytest_configure`: `subprocess.Popen` becomes a subclass of the real
`Popen` whose `__new__` returns a recorded `StandIn` for any BACKGROUND launch,
caught by its flags (a new process group, a detached process, a console of its
own, a new session) and never by its command line. An autouse fixture
`background_calls` hands each test the launches it made, and the marker
`@pytest.mark.real_background` lets one test have the real program. No
production file changes, so nothing restarts.

**Tech Stack:** Python 3.13 on Windows 11, pytest, `subprocess`.

**Spec:** none: this is a bug fix. The authority is the operator's ask (*"do
superpower for planning the bug"*, Oct 14, 2026), the split agreed with the
Error Watcher session (it owns the window half, RCA-2026-10-14-G), and
CLAUDE.md's test rules: *"A test writes only under its own tmp_path"* and the
`_no_network` pattern in `tests/conftest.py`.

## What happened (measured, Oct 14, 2026)

1. Since Aug 27, 2026 (commit 574dedf9), every fill of a row list asks for its
   missing indexes in a background program: `rows_index.sync` (line 1374,
   also lines 1576 and 2152) → `_after_fill_indexes` (2310) →
   `build_missing_indexes` (3906) → `_build_index` (4035) launches
   `python -m tradingagents.rows_index --build <index>`.
2. Test fixtures fill throwaway lists that way (for example
   `tests/test_row_id_lookup.py:56` `store` → `:30` `_settled`), so each test
   launched a REAL build. A spy over 12 index test files recorded 794 launch
   attempts, about 18 per test, `rows_id` first.
3. Each build waits up to an hour for its turn (`busy_timeout=3600000`,
   `rows_index.py:3932`), and the test that started it still holds its list.
   So the builds stay alive while the run lasts and end after it. A real
   4-file run at 7:44am had 62 of them alive (31 builds, two programs each:
   the venv's `python.exe` is a launcher that starts the real interpreter).
4. At 7:07:55am a forgotten review checker started 4 full suites at once. At
   7:27:32-7:30:03am 144 build programs were alive, each with a console that
   Windows Terminal hosted, and the PC fell to 1.1 GB free of 16 GB.
5. The Error Watcher session removed the WINDOWS (CREATE_NO_WINDOW instead of
   DETACHED_PROCESS, RCA-2026-10-14-G, commit 2b4d9201). The PROGRAMS are what
   this plan removes.

## Global Constraints

- Do NOT edit the Error Watcher's files: `tradingagents/rows_index.py`,
  `tradingagents/portable.py`, `start.py`, `tradingagents/storage_months.py`,
  `tradingagents/live_ingest.py`, `tests/test_detached_spawns.py`,
  `tests/test_storage_months.py`, `tests/test_wide_profit_index.py`.
- No production code changes: `tests/` and `docs/` and one CLAUDE.md line only.
- At most ONE full test suite at a time on this PC, and the first one only after
  the Error Watcher says Windows Terminal is closed.
- Commit with `.venv/Scripts/python scripts/commit_own.py -F <msg> <paths>`,
  after `git diff HEAD -- <path>` shows only this plan's hunks; push to
  `origin` and `colleague`.
- The RCA entry (RCA-2026-10-14-H) goes in the SAME commit as the fix.
- Dates read exactly like `Oct 14, 2026 7:27am`.

## Review Focus

1. A test that reads a background program's output gets a stand-in with no
   output: it must fail with a message naming `real_background`, never with
   `'NoneType' has no attribute 'readline'`. Pinned in Task 1
   (`test_reading_a_stand_ins_output_names_the_marker`).
2. A thread a test left running launches after its test ended: it must still
   get a stand-in, so the guard is installed for the session, never by a
   fixture whose patch teardown undoes. Pinned in Task 1
   (`test_the_guard_is_on_for_the_whole_session`).
3. A test that subclasses `subprocess.Popen`
   (`tests/test_a_hung_git_cannot_blind_the_cloud_panel.py:85`) must keep
   working, so the guard is a CLASS, not a function. Pinned by that test in
   Task 3's full run.
4. A test that waits for a background program's WORK without reading it (an
   index to appear) now waits for a stand-in: it needs the marker. Known one:
   `tests/test_index_ensure_cheap.py::test_a_sort_index_is_built_on_demand_when_it_is_missing`
   (Task 2). Any other one surfaces in Task 3 as a new failure.
5. A waited helper with no window (the fixer's `git` calls use
   `CREATE_NO_WINDOW` alone) is NOT background and must still run. Pinned in
   Task 1 (`test_a_foreground_program_still_runs`).

---

### Task 1: The guard and its tests

**Files:**
- Create: `tests/test_tests_leave_no_program_running.py`
- Modify: `tests/conftest.py` (imports at the top; `pytest_configure` at lines
  27-29; a new block after `_no_network`, which ends at line 111)

**Interfaces:**
- Consumes: `rows_index.sync(now=...)`, `rows_index.SETTLE_S` (60.0),
  `rows_index._BUILDING` (a set), `rows_index.forget_indexes()`,
  `market_sweep.ROWDIR`, `rows_index.DB_PATH`, `portable.DETACHED` (a dict of
  Popen kwargs; read only).
- Produces: in `tests/conftest.py` — `is_background(kwargs: dict) -> bool`,
  `class StandIn` (attributes `stand_in = True`, `PID = 999_999`, `pid`,
  `args`, `kwargs`, `returncode`; methods `poll`, `wait`, `communicate`,
  `kill`, `terminate`, `send_signal`, context manager), `class _GuardedPopen`,
  the autouse fixture `background_calls` (yields a list of
  `{"args": ..., "kwargs": {...}}`), and the marker `real_background`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tests_leave_no_program_running.py`:

```python
"""No test leaves a program running behind it (RCA-2026-10-14-H).

Since Aug 27, 2026 every fill of a row list asks for its missing indexes in
a background `rows_index --build` program (`rows_index.sync` ->
`_after_fill_indexes` -> `build_missing_indexes` -> `_build_index`), and the
fixtures that fill throwaway lists did that for real: 13 to 31 programs a
suite, each waiting for a lock its own test still held. On Oct 14, 2026 at
7:07:55am four suites ran at once, and at 7:27:32am 144 of those programs
(72 builds, two programs each through the venv launcher) were alive, each
with a console Windows Terminal hosted; the PC fell to 1.1 GB free of 16 GB.

conftest answers every BACKGROUND launch with a stand-in, caught by its
flags and never by its command line, and a test that needs the real program
says so with `@pytest.mark.real_background`.
"""
import json
import subprocess
import sys
import time

import pytest

from tradingagents import market_sweep as msw, portable, rows_index as ri


def _row(sig):
    return {"coin": "AAA", "tf": "1h", "signal": sig, "th": 0.1, "sl": 0.3,
            "tp": 2.0, "rr": 3.0, "sizing": "flat", "lev": 20, "base": 5.0,
            "notional": 100.0, "trades": 120, "wins": 72, "losses": 48,
            "winrate": 60.0, "profit": 70.0, "funding": -0.2, "h1": 1.0,
            "h2": 1.0, "green": 8, "months": 12, "worst": -4.1, "dd": 22.0,
            "liqs": 0, "stop_reachable": True, "days": 360, "bars": 34000,
            "monthly": {}, "cost_of_tp": 12.5, "rt": 0.04, "gate": "ok"}


def test_filling_a_row_list_starts_no_real_build(tmp_path, monkeypatch, background_calls):
    """The path that leaked, driven the way the leaking fixtures drive it
    (tests/test_row_id_lookup.py's `store`): the fill still ASKS for its
    missing indexes, and every ask is answered by a stand-in."""
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    monkeypatch.setattr(ri, "_BUILDING", set())     # other tests' asks are theirs
    ri.forget_indexes()
    (rows_dir / "AAA-1h.json").write_text(json.dumps([_row("mom6"), _row("rsi14")]))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    builds = [c for c in background_calls
              if "--build" in " ".join(map(str, c["args"] or []))]
    assert builds, "a fill asks for its missing indexes in a background program"
    assert all("tradingagents.rows_index" in " ".join(map(str, c["args"]))
               for c in builds)


@pytest.mark.parametrize("kw", [
    {"creationflags": 0x00000200},       # a new process group
    {"creationflags": 0x00000008},       # DETACHED_PROCESS (before RCA-2026-10-14-G)
    {"creationflags": 0x00000010},       # a console window of its own
    {"start_new_session": True},         # elsewhere than Windows
    portable.DETACHED,                   # what every launch point spreads
], ids=["new-group", "detached", "new-console", "new-session", "portable.DETACHED"])
def test_a_background_launch_is_caught_by_its_flags(kw, background_calls):
    """A launch point added tomorrow is covered without being named."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **kw)
    assert getattr(proc, "stand_in", False), "no program may start"
    assert proc.poll() is None and proc.wait() == 0
    assert background_calls[-1]["kwargs"] == kw


def test_reading_a_stand_ins_output_names_the_marker(background_calls):
    proc = subprocess.Popen([sys.executable, "-c", "print(1)"],
                            stdout=subprocess.PIPE, **portable.DETACHED)
    with pytest.raises(AssertionError, match="real_background"):
        proc.stdout.readline()


def test_a_foreground_program_still_runs(background_calls):
    """A program the test waits for is not a background one: it runs, and a
    waited helper with no window (the fixer's git calls) does too."""
    out = subprocess.run([sys.executable, "-c", "print('ran')"],
                         capture_output=True, text=True, timeout=120,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert out.stdout.strip() == "ran"
    assert background_calls == []


@pytest.mark.real_background
def test_a_test_that_asks_gets_the_real_program(background_calls):
    proc = subprocess.Popen([sys.executable, "-c", "pass"], **portable.DETACHED)
    try:
        assert not getattr(proc, "stand_in", False)
        assert proc.wait(timeout=120) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    assert background_calls == []


def test_the_guard_is_on_for_the_whole_session():
    """Installed once for the session, never at a test's set-up: a fixture's
    patch is undone at teardown, and a thread a test left running would then
    launch for real after it (RCA-2026-10-10-J's shape)."""
    assert subprocess.Popen.__name__ == "_GuardedPopen"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_tests_leave_no_program_running.py`
Expected: `1 error` during collection, `'real_background' not found in markers configuration option` (pyproject.toml line 46 sets `--strict-markers`). To see each test fail for its own reason as well, run it once with `-o addopts=""`: every test but the last ERRORS with `fixture 'background_calls' not found`, and the last FAILS (`assert 'Popen' == '_GuardedPopen'`).

- [ ] **Step 3: Write the guard in `tests/conftest.py`**

Add `import subprocess` beside `import socket` at the top. In
`pytest_configure`, after the existing loop, add:

```python
    config.addinivalue_line(
        "markers", "real_background: this test starts a real background "
                   "program on purpose, and ends it itself")
    # for the WHOLE session, never undone at a test's teardown: a thread a
    # test left running that launches after its test ended is stood in too
    # (RCA-2026-10-10-J's shape, RCA-2026-10-14-H)
    subprocess.Popen = _GuardedPopen
```

After the `_no_network` fixture, add:

```python
# ---------------------------------------------------------------------------
# No test leaves a program running behind it (RCA-2026-10-14-H).
#
# Since Aug 27, 2026 every fill of a row list asks for its missing indexes in
# a background `rows_index --build` program, and the fixtures that fill
# throwaway lists did that for real: 13 to 31 programs a suite, each waiting
# up to an hour for a lock its own test still held. On Oct 14, 2026 four
# suites at once left 144 of them alive at 7:27am, each with a console
# Windows Terminal hosted, and the PC fell to 1.1 GB free of 16 GB.
#
# A BACKGROUND launch (a new process group, a detached process, a console of
# its own, a new session: a program meant to outlive whoever started it) is
# answered by a StandIn and recorded, so the code under test still runs its
# own path and nothing starts. Caught by its FLAGS, never its command line, so
# a launch point added tomorrow is covered without being named. A test that
# needs the real program says so: `@pytest.mark.real_background`.
# ---------------------------------------------------------------------------
_REAL_POPEN = subprocess.Popen
# DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NEW_CONSOLE
_BACKGROUND_FLAGS = 0x00000008 | 0x00000200 | 0x00000010
_GUARD: dict = {"real": False, "calls": []}


def is_background(kwargs: dict) -> bool:
    """A launch meant to outlive the process that made it."""
    return bool((int(kwargs.get("creationflags") or 0) & _BACKGROUND_FLAGS)
                or kwargs.get("start_new_session")
                or kwargs.get("process_group") is not None)


class _NoOutput:
    """A stand-in's stdout/stderr: reading it is the test's mistake, named."""

    def __init__(self, args):
        self._args = args

    def _fail(self, *a, **k):
        raise AssertionError(
            f"a test read the output of a background program, and tests never "
            f"start those ({self._args!r}); mark the test "
            f"@pytest.mark.real_background if it really needs that program")

    read = readline = readlines = __iter__ = _fail

    def close(self):
        pass


class StandIn:
    """What a test gets instead of a background program: it answers like a
    process that is still starting, and no process exists."""

    stand_in = True
    PID = 999_999          # not a multiple of 4, so never a real Windows pid

    def __init__(self, args, kwargs):
        self.args, self.kwargs = args, kwargs
        self.pid = self.PID
        self.returncode = None
        self.stdin = None
        piped = subprocess.PIPE
        self.stdout = _NoOutput(args) if kwargs.get("stdout") == piped else None
        self.stderr = _NoOutput(args) if kwargs.get("stderr") == piped else None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def communicate(self, input=None, timeout=None):
        self.wait()
        return (None, None)

    def kill(self):
        if self.returncode is None:
            self.returncode = -9

    terminate = kill

    def send_signal(self, sig):
        self.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _GuardedPopen(_REAL_POPEN):
    """`subprocess.Popen` for the whole session. A CLASS, so a test may still
    subclass it (tests/test_a_hung_git_cannot_blind_the_cloud_panel.py)."""

    def __new__(cls, *args, **kwargs):
        if is_background(kwargs) and not _GUARD["real"]:
            cmd = args[0] if args else kwargs.get("args")
            _GUARD["calls"].append({"args": cmd, "kwargs": dict(kwargs)})
            return StandIn(cmd, kwargs)
        return super().__new__(cls)


@pytest.fixture(autouse=True)
def background_calls(request):
    """Every background launch this test made, each answered by a StandIn.
    A test marked `real_background` gets the real program instead."""
    calls: list = []
    _GUARD.update(calls=calls,
                  real=bool(request.node.get_closest_marker("real_background")))
    try:
        yield calls
    finally:
        _GUARD["real"] = False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_tests_leave_no_program_running.py`
Expected: `10 passed` (1 + 5 parametrized + 1 + 1 + 1 + 1).

- [ ] **Step 5: Lint the two files**

Run: `.venv/Scripts/python -m ruff check tests/conftest.py tests/test_tests_leave_no_program_running.py`
Expected: no finding that `git show HEAD:tests/conftest.py` does not already have.

### Task 2: The one test that needs a real build

**Files:**
- Modify: `tests/test_index_ensure_cheap.py:50` (one decorator)

**Interfaces:**
- Consumes: the `real_background` marker from Task 1.
- Produces: nothing new.

- [ ] **Step 1: Show it fails under the guard**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider "tests/test_index_ensure_cheap.py::test_a_sort_index_is_built_on_demand_when_it_is_missing"`
Expected: FAIL at line 74, `AssertionError: the query's guard builds it`: the build it polls for is a stand-in now.

- [ ] **Step 2: Mark it**

Above `def test_a_sort_index_is_built_on_demand_when_it_is_missing` add:

```python
@pytest.mark.real_background     # it polls for the real build's index (RCA-2026-10-14-H)
```

(add `import pytest` at the top of the file if it is not there).

- [ ] **Step 3: Run the 12 index files with a process watcher**

In one shell, start a 4-minute watcher that writes every `rows_index` program it sees:

```powershell
$out = "$env:TEMP\spawn_watch_after.txt"; Remove-Item $out -ErrorAction SilentlyContinue; $seen = @{}; $end = (Get-Date).AddSeconds(240); while ((Get-Date) -lt $end) { Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'rows_index --build' } | ForEach-Object { if (-not $seen.ContainsKey($_.ProcessId)) { $seen[$_.ProcessId] = 1; "{0} pid={1} parent={2}" -f (Get-Date -Format 'h:mm:ss'), $_.ProcessId, $_.ParentProcessId | Out-File -Append -Encoding utf8 $out } }; Start-Sleep -Milliseconds 400 }; "seen " + $seen.Count | Out-File -Append -Encoding utf8 $out
```

Then run:

`.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_a_blocked_build_says_who_is_holding_it.py tests/test_a_dead_build_stops_saying_it_is_building.py tests/test_a_rebuild_puts_back_the_indexes_it_swapped_out.py tests/test_a_verified_rebuild_is_swapped_in_by_the_site.py tests/test_coin_index_forced.py tests/test_filter_combinations.py tests/test_index_ensure_cheap.py tests/test_index_stall_is_visible.py tests/test_row_id_lookup.py tests/test_strategies_sort.py tests/test_strategy_group_filter.py tests/test_the_id_search_comes_back_first.py`

Expected: `129 passed`. The watcher shows at most 2 programs (the marked test's
one build: launcher plus interpreter), against 26 before the fix (Oct 14, 2026
7:38am), and none still alive when the run ends.

### Task 3: One full suite, after the go-ahead

**Files:** none changed unless a new failure needs the marker (then the test
file it is in, one decorator, named in the commit message).

- [ ] **Step 1: Wait for the Error Watcher's message that Windows Terminal is closed.** Then check no other suite runs:

```powershell
@(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'pytest' }).Count
```

Expected: `0`.

- [ ] **Step 2: Run the full suite once, with the watcher running for 20 minutes**

Start the watcher from Task 2 Step 3 with `AddSeconds(1200)` and the file
`$env:TEMP\spawn_watch_suite.txt`, then run:

`.venv/Scripts/python -m pytest -q -p no:cacheprovider -rf 2>&1 | grep -E "^FAILED|^ERROR|passed|failed" > "$TEMP/after_guard.txt"`
Expected: no FAILED line that is not in `$TEMP/before.txt` (29 known
failures), and the watcher sees at most 2 `rows_index --build` programs, none
alive at the end.

- [ ] **Step 3: Sort any new failure.** For each, add `@pytest.mark.real_background` and run that test alone: if it passes, it needed the real program, so keep the marker and name it in the commit. If it still fails, remove the marker and compare with `git show HEAD:<file>`: a peer's commit is not this plan's to fix, so report it to the session that made it.

### Task 4: The record, the commit, the hand-back

**Files:**
- Modify: `docs/RCA.md` (new entry at the top of the Oct 14, 2026 block, above RCA-2026-10-14-G)
- Modify: `CLAUDE.md` (one bullet after "A test writes only under its own tmp_path.")

- [ ] **Step 1: Write RCA-2026-10-14-H**

```markdown
## RCA-2026-10-14-H — every test run left 13 to 31 programs running, and four runs at once brought the PC to 1.1 GB free

**CEO**

* Your PC crawled on Oct 14, 2026 around 7:30am: four test runs from an old
  review check of mine ran at once, and their helper programs filled the
  memory (1.1 GB free of 16 GB).
* Why: the tests started real background programs (index builds), which waited
  on the test that started them and piled up while a run lasted. Every test
  run since Aug 27, 2026 did this, 13 to 31 at a time.
* What stops it now: tests never start a background program; a stand-in
  answers instead, unless a test asks for the real one.

**DEV**

* `tests/test_row_id_lookup.py:56` `store` → `rows_index.sync` (1374) →
  `_after_fill_indexes` (2310) → `build_missing_indexes` (3906) →
  `_build_index` (4035) `subprocess.Popen(... "--build", name)`; the child
  waits on `busy_timeout=3600000` (3932) for the lock its test holds.
* Invariant broken: **a test leaves nothing running behind it**: the suite
  isolated sockets (`_no_network`) and paths (`_never_touch_the_live_book`)
  but never processes.
* Guard: `tests/test_tests_leave_no_program_running.py` (10 tests).

**SAW** — the PC crawling; the Error Watcher session counted 618 console
processes created that day, 604 of them between 7am and 8am.

**TIMELINE**

1. Aug 27, 2026 — commit 574dedf9: every fill asks for its missing indexes in
   a background program; fixtures fill throwaway lists, so every test run
   starts real builds from then on.
2. Oct 13, 2026 about 11:50pm — a review checker of mine starts and keeps
   running after its review is done.
3. Oct 14, 2026 7:07:55am — it starts four full suites at once.
4. 7:27:32am-7:30:03am — 144 build programs alive (72 builds, two programs
   each through the venv launcher), each with a Windows Terminal console; the
   PC at 1.1 GB free of 16 GB, Windows Terminal itself at 4,307 MB at 8:22am.
5. About 7:31am — the checker stopped and all 144 ended by exact process id;
   the real Backtest list untouched (last written 4:58am).
6. 7:38am, measuring — 12 index test files alone left 26 programs (13 builds);
   a spy over the same files recorded 794 launch attempts.
7. After the fix — the same 12 files: at most one real build (the test that
   asks for it), none alive at the end.

**ROOT CAUSE** — production's "build the missing indexes in the background
after a fill" ran inside tests, and nothing in the test setup kept a test from
starting a real program.

**WHY IT WAS NOT CAUGHT** — the suite's isolation was written against the two
leaks it had met: the network (36 live calls) and the operator's files (86 fake
XAUT rows). A started program leaves no failing assertion behind: the test
that starts it passes, and the program outlives it. A guard is only as wide as
its pattern, and this one had never been widened to processes.

**COST** — none in money; the PC near out of memory for about 25 minutes, and
Windows Terminal holding 4,307 MB until it was closed.

**FIX** — this commit (the windows themselves: RCA-2026-10-14-G).

**GUARD** — `tests/test_tests_leave_no_program_running.py`.
```

- [ ] **Step 2: Add the CLAUDE.md bullet** after the bullet that begins `* **A test writes only under its own tmp_path.**`:

```markdown
* **A test starts no background program either** (RCA-2026-10-14-H).
  `tests/conftest.py` answers every new-process-group, detached, new-console
  or new-session launch with a recorded stand-in, caught by its flags; a test
  that really needs the program is marked `@pytest.mark.real_background`.
  Every suite since Aug 27, 2026 left 13-31 `rows_index --build` programs
  waiting on their own test's lock; four suites at once on Oct 14, 2026 left
  144 and the PC at 1.1 GB free of 16 GB.
```

- [ ] **Step 3: Run the RCA shape test**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_rca_log.py`
Expected: all pass.

- [ ] **Step 4: Commit only this plan's files, then push both**

```bash
git diff HEAD -- tests/conftest.py tests/test_index_ensure_cheap.py docs/RCA.md CLAUDE.md
.venv/Scripts/python scripts/commit_own.py -F "$TEMP/msg_guard.txt" tests/conftest.py tests/test_tests_leave_no_program_running.py tests/test_index_ensure_cheap.py docs/RCA.md CLAUDE.md
git push origin main && git push colleague main
```

Write `$TEMP/msg_guard.txt` first; its first line:
`fix(tests): no test leaves a program running - every suite since Aug 27, 2026 started 13-31 real rows_index --build programs that waited on their own test's lock; four suites at once on Oct 14, 2026 7:27am left 144 and the PC at 1.1 GB free (RCA-2026-10-14-H)`

- [ ] **Step 5: Tell the Error Watcher it landed** (it runs its own full suite after this), and save a memory: one full suite at a time on this PC.
