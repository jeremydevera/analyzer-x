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

# what `subprocess.Popen` was when this file was IMPORTED: after
# pytest_configure, before any fixture ran — so only a session-wide install
# can make it the guard (final review, Oct 14, 2026)
_POPEN_WHEN_COLLECTED = subprocess.Popen


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
    {"process_group": 0},                # elsewhere, Python 3.11+
    portable.DETACHED,                   # what every launch point spreads
], ids=["new-group", "detached", "new-console", "new-session", "process-group",
        "portable.DETACHED"])
def test_a_background_launch_is_caught_by_its_flags(kw, background_calls):
    """A launch point added tomorrow is covered without being named. The
    program is `pass` and a real one is ended at once: if the guard ever
    broke, this test must not leave programs (or windows) behind itself."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"], **kw)
    try:
        assert getattr(proc, "stand_in", False), "no program may start"
        assert proc.poll() is None and proc.wait() == 0
        assert background_calls[-1]["kwargs"] == kw
    finally:
        if not getattr(proc, "stand_in", False) and proc.poll() is None:
            proc.kill()


def test_reading_a_stand_ins_output_names_the_marker(background_calls):
    """pytest.fail, not AssertionError: a launch site's own `except
    Exception` must not swallow the test's mistake."""
    proc = subprocess.Popen([sys.executable, "-c", "print(1)"],
                            stdout=subprocess.PIPE, **portable.DETACHED)
    with pytest.raises(pytest.fail.Exception, match="real_background"):
        proc.stdout.readline()


def test_capturing_a_stand_ins_output_names_the_marker(background_calls):
    """`communicate()` is how most code reads a child's output, and run() and
    check_output() take that path: it fails naming the marker, never with an
    empty result or a NoneType error further on (final review, Oct 14,
    2026). Writing to its input does too."""
    with pytest.raises(pytest.fail.Exception, match="real_background"):
        subprocess.run([sys.executable, "-c", "print(1)"], capture_output=True,
                       **portable.DETACHED)
    proc = subprocess.Popen([sys.executable, "-c", "pass"],
                            stdin=subprocess.PIPE, **portable.DETACHED)
    with pytest.raises(pytest.fail.Exception, match="real_background"):
        proc.stdin.write(b"x")


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
    launch for real after it (RCA-2026-10-10-J's shape). Read from what
    the name was at IMPORT: a fixture-installed guard would pass a check made
    inside the test."""
    assert _POPEN_WHEN_COLLECTED.__name__ == "_GuardedPopen"
