"""A runner Windows will not let swap its state file in must not die of it,
and a runner that does die says so where the operator looks
(docs/RCA.md RCA-2026-10-07-E).

`_write_json` swapped `auto_trade_state.json.tmp` onto the room's state file
with a bare `Path.replace`. On Windows that rename is REFUSED while any other
handle has the file open — the API reading a room's book, the Forecast page
re-reading every room's — and the refusal came straight out of `run_cycle`'s
final `save_state` and ended the process. It killed a runner 9 times: Main 5
(Sep 13 to Sep 29, 2026), #55D32617 at Oct 01, 2026 5:10pm, #CC94D9FB at
Oct 02, 2026 7:08am, and the retired #DC57174E and #B52662ED once each.
`db_jobs._write` has retried this exact refusal for 3 s since
RCA-2026-09-18-B; the runner's own write never got the retry.

Not one of the nine reached the Errors tab as a crash: each showed only as
"Runner started again". The traceback carried no date, so the tab's reader
skipped every line of it — and on Windows it was written OVER the run's own
first lines, because `start_runner` hands the child the log at the offset it
had when the child was spawned (#CC94D9FB's sits on line 1, among Sep 30
lines; 6 'loop starting' lines for 9 starts).

Every runner test here enters where the process does — `run_cycle`,
`run_forever`, `start_runner` and the module's own `__main__` — never a helper
one layer below (CLAUDE.md, "test the path the RUNNER takes").
"""
from __future__ import annotations

import ast
import json
import logging
import os
import pathlib
import threading
import time

import pandas as pd
import pytest

from tests.test_auto_trader import FakeFx
from tradingagents import auto_trader as at

# A practice trade that reaches its target this cycle: the exit is written to
# the trade record, then the state file has to say the trade is closed.
HELD, KEY = "PDDSTOCK_USDT", "eqraid_1h_sl25tp25"
ARMED, ARMED_KEY = "GPNSTOCK_USDT", "keltner_30m_sl2tp2"
ENTRY = 79.18


def _hour_bars(last_high: float):
    """60 closed hourly bars ending at the last hour the WALL CLOCK has
    closed — the clock `opened_at` is stamped on below — so the candles and
    the position sit on ONE timeline, the one a running runner sees
    (RCA-2026-09-12-A: a floor in the wrong clock looks right in a fixture
    whose clocks disagree)."""
    top = int(time.time()) // 3600 * 3600 - 3600
    opens = [top - (59 - i) * 3600 for i in range(60)]
    return pd.DataFrame({"Date": pd.to_datetime(opens, unit="s"),
                         "Open": [ENTRY] * 60,
                         "High": [ENTRY + 0.3] * 59 + [last_high],
                         "Low": [ENTRY - 0.3] * 60, "Close": [ENTRY] * 60,
                         "Volume": [1.0] * 60}), opens


def _position(opened_at: int) -> dict:
    return {"side": 1, "vol": 5, "entry": ENTRY, "tp": ENTRY * 1.025,
            "sl": ENTRY * 0.975, "margin": 5.0, "strategy": KEY,
            "entry_ts": opened_at - 3600, "opened_at": opened_at,
            "trade_id": "BUSYSTAT", "dry": True, "bracket": True, "step": 0}


def _settings() -> dict:
    return {"strategies": [ARMED_KEY], "strategy_coins": {ARMED_KEY: [ARMED]},
            "strategy_books": {ARMED_KEY: ["paper"]}, "margin": 5.0,
            "enabled": False, "dry_run": True}


def _ledger() -> list[dict]:
    p = at._pp(at.LEDGER_PATH)
    return ([json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            if p.exists() else [])


def _temp_files(path: pathlib.Path) -> list[str]:
    return sorted(p.name for p in path.parent.glob(path.name + "*.tmp"))


def _refuse_state_swaps(monkeypatch, times: int) -> list:
    """Windows' refusal on demand: the swap of the STATE file's temp copy
    raises what it raised at Oct 02, 2026 7:08am, `times` times, then goes
    through. Every other rename is left alone, so the refusals cannot be
    absorbed by some other swap whose caller swallows errors."""
    real = pathlib.Path.replace
    seen: list = []

    def replace(self, target):
        name = self.name
        if name.startswith(at.STATE_PATH.name + ".") and name.endswith(".tmp"):
            seen.append(name)
            if len(seen) <= times:
                raise PermissionError(13, "Access is denied")
        return real(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", replace)
    return seen


@pytest.fixture(autouse=True)
def _fresh_bars():
    """A coin's candles are cached for the whole bar; one test's crossing
    bar must not be served to the next."""
    at._BAR_CACHE.clear()
    yield
    at._BAR_CACHE.clear()


# ------------------------------------------------------- the crash itself
def test_a_refused_state_swap_does_not_end_the_cycle(monkeypatch):
    """Through `run_cycle`: the trade hits its target, the exit row is
    written, and Windows refuses the state file's swap twice. The cycle has
    to finish with the closed trade ON DISK — an exit row that landed without
    its state is replayed on the next start, which double-counts the loss
    (run_forever's own comment, 2026-08-22)."""
    df, opens = _hour_bars(ENTRY * 1.03)                 # the target is hit
    slot = at.state_key(HELD, True, KEY)
    at._write_json(at.SETTINGS_PATH, _settings())
    at._write_json(at.STATE_PATH, {slot: {"step": 0, "last_ts": {},
                                          "position": _position(opens[-3])}})
    refused = _refuse_state_swaps(monkeypatch, times=2)

    at.run_cycle(fx=FakeFx(df))         # raised PermissionError before the fix

    assert len(refused) == 3, f"two refusals, then the swap that landed: {refused}"
    assert at.load_state()[slot]["position"] is None, "the closed trade never reached the disk"
    exits = [r for r in _ledger() if r.get("action") == "exit" and r.get("symbol") == HELD]
    assert [r["why"] for r in exits] == ["TP"]
    assert _temp_files(at.STATE_PATH) == [], "a temp copy was left behind"


@pytest.mark.skipif(os.name != "nt", reason="only Windows refuses a rename onto an open file")
def test_a_reader_holding_the_state_file_only_delays_the_save():
    """The real refusal, not a stand-in: a reader holds the room's state file
    open (as the API does) for 0.3 s while the runner saves. Before the fix
    this raised `[WinError 5] Access is denied` on the first try."""
    slot = at.state_key(HELD, True, KEY)
    at._write_json(at.STATE_PATH, {})
    state = at.load_state()
    state[slot] = {"step": 0, "last_ts": {}, "position": None}
    reader = open(at.STATE_PATH, "rb")                   # noqa: SIM115
    let_go = threading.Timer(0.3, reader.close)
    let_go.start()
    try:
        at.save_state(state, keys=[slot])
    finally:
        let_go.cancel()
        reader.close()
    assert slot in at.load_state()


def test_a_swap_still_refused_after_the_budget_fails_loudly_and_leaves_nothing(monkeypatch):
    """The retry is a wait, not a way to hide a failure: refused past the
    budget, the write raises exactly as before — and its temp copy is gone,
    because every call now writes its own and none would overwrite it."""
    at._write_json(at.STATE_PATH, {"before": 1})
    _refuse_state_swaps(monkeypatch, times=10**6)
    monkeypatch.setattr(at, "REPLACE_BUDGET_S", 0.2, raising=False)
    started = time.monotonic()
    with pytest.raises(PermissionError):
        at._write_json(at.STATE_PATH, {"after": 1})
    assert time.monotonic() - started >= 0.2, "gave up without retrying"
    assert json.loads(at.STATE_PATH.read_text(encoding="utf-8")) == {"before": 1}
    assert _temp_files(at.STATE_PATH) == []


def test_two_writers_of_one_settings_file_never_share_a_temp_copy(monkeypatch):
    """auto_trade.json has four writers and no lock between them: the API's
    save, the watcher, a deploy, the runner's own disarm. With one fixed
    `.tmp` name, a writer whose swap was refused for a moment would, on its
    retry, find the OTHER writer had already moved that file into place —
    its own save lost and a FileNotFoundError no PermissionError retry
    catches. Each call writes its own temp copy, so the last swap wins
    whole."""
    path = at._pp(at.SETTINGS_PATH)
    real = pathlib.Path.replace
    held, other_done = threading.Event(), threading.Event()
    a: dict = {}

    def replace(self, target):
        if threading.get_ident() == a.get("thread") and not held.is_set():
            held.set()                    # A's first swap is refused...
            assert other_done.wait(10), "the other writer never finished"
            raise PermissionError(13, "Access is denied")
        return real(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", replace)

    def writer_a():
        a["thread"] = threading.get_ident()
        try:
            at._write_json(path, {"by": "A"})
        except Exception as exc:                               # noqa: BLE001
            a["error"] = exc

    t = threading.Thread(target=writer_a)
    t.start()
    assert held.wait(10)
    at._write_json(path, {"by": "B"})     # ...while B saves the same file
    other_done.set()
    t.join(10)
    assert a.get("error") is None, f"writer A failed: {a.get('error')!r}"
    assert json.loads(path.read_text(encoding="utf-8")) == {"by": "A"}, \
        "A swapped last, so A's settings must stand whole"
    assert _temp_files(path) == []


def test_every_swap_in_the_runner_goes_through_the_retry():
    """The guard for the next one. RCA-2026-09-18-B fixed this refusal in
    db_jobs and nobody looked for the same bare swap elsewhere: the runner's
    state write kept it for nine more crashes. Reads the parsed CODE, never
    the text, because comments and docstrings quote the old line. Any
    one-argument `.replace` / `.rename` is a path swap (`str.replace` takes
    two), whatever the temp variable happens to be called."""
    tree = ast.parse(pathlib.Path(at.__file__).read_text(encoding="utf-8"))
    bare = []
    literals = (ast.Dict, ast.List, ast.Set, ast.Tuple, ast.Constant)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("replace", "rename")):
            continue
        on_os = isinstance(node.func.value, ast.Name) and node.func.value.id == "os"
        one_path = (len(node.args) == 1 and not node.keywords
                    and not isinstance(node.args[0], literals))
        if on_os or one_path:
            bare.append(f"line {node.lineno}: {ast.unparse(node)}")
    assert not bare, ("a rename Windows can refuse, with no retry — use "
                      "portable.replace_retry: " + "; ".join(bare))


# ------------------------------------------- a crash says so, once, dated
def _crash_the_loop(monkeypatch, exc: BaseException):
    """`run_forever` with everything before its loop made harmless and a
    cycle that raises `exc`. Returns (SystemExit info, the room's log).

    The log handler is the one `__main__` installs (WhenFormatter), on the
    runner's own logger, and the logger is switched on for the test: another
    test in the suite re-plumbs logging, so caplog would depend on order."""
    from tradingagents.dataflows import mexc_credentials as cred
    from tradingagents.positions_view import WhenFormatter

    log = at._pp(at.LOG_PATH)
    log.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log, encoding="utf-8")
    handler.setFormatter(WhenFormatter("%(asctime)s %(levelname)s %(message)s"))
    monkeypatch.setattr(cred, "load_into_env", lambda *a, **k: False)
    monkeypatch.setattr(at.signal, "signal", lambda *a, **k: None)
    monkeypatch.setattr(at, "runner_pid", lambda: None)
    monkeypatch.setattr(at, "disk_free_mb", lambda: 50_000)
    monkeypatch.setattr(at, "active_modes", lambda settings=None: [True])
    monkeypatch.setattr(at, "load_settings", lambda: {})
    monkeypatch.setattr(at, "_RUN_LOCK", None)

    def cycle(**kw):
        raise exc

    monkeypatch.setattr(at, "run_cycle", cycle)
    was = (at.logger.level, at.logger.disabled)
    at.logger.setLevel(logging.INFO)
    at.logger.disabled = False
    at.logger.addHandler(handler)
    try:
        with pytest.raises(SystemExit) as ended:
            at.run_forever()
    finally:
        at.logger.removeHandler(handler)
        handler.close()
        at.logger.setLevel(was[0])
        at.logger.disabled = was[1]
        if at._RUN_LOCK is not None:
            at._RUN_LOCK.close()
    return ended, log


def test_a_crash_is_one_dated_program_error_and_a_trade_record_row(monkeypatch):
    """The Errors tab reads DATED lines only, so a traceback alone never
    reached it: `kind=exception` returned 0 rows across all six rooms after
    runners had died nine times. The crash is now one dated ERROR line the tab
    files as a Program error, a `runner_crash` row, and exit code 1 — with
    no second copy of the traceback from the interpreter on the way out."""
    from tradingagents import room_errors

    monkeypatch.setattr(room_errors, "_TAILS", {})
    monkeypatch.setattr(room_errors, "_STARTS", {})
    ended, log = _crash_the_loop(monkeypatch, PermissionError(13, "Access is denied"))

    assert ended.value.code == 1
    got = room_errors.report(room="main", kind="exception", hours=0)
    assert got["events"] == 1, got
    row = got["rows"][0]
    assert row["label"] == "Program error", row
    assert row["message"].startswith("runner crashed") and "PermissionError" in row["message"], row
    assert log.read_text(encoding="utf-8").count("Traceback (most recent call last)") == 1
    crash = [r for r in _ledger() if r.get("action") == "runner_crash"]
    assert len(crash) == 1 and crash[0]["error"].startswith("PermissionError"), crash


def test_any_error_type_is_filed_as_a_program_error(monkeypatch):
    """The tab knows a Program error by `Traceback`, a bare `Exception` or a
    word ending in `Error`. A crash of a type named otherwise (a request
    library's `ReadTimeout`) must not fall through to 'Other error'."""
    from tradingagents import room_errors

    class ReadTimeout(OSError):
        pass

    monkeypatch.setattr(room_errors, "_TAILS", {})
    monkeypatch.setattr(room_errors, "_STARTS", {})
    _crash_the_loop(monkeypatch, ReadTimeout("read timed out"))
    got = room_errors.report(room="main", kind="exception", hours=0)
    assert got["events"] == 1 and "ReadTimeout" in got["rows"][0]["message"], got


def test_a_trade_record_that_cannot_be_written_never_hides_the_crash(monkeypatch):
    """2026-08-22: a full disk. If the trade-record row raises, the crash
    line must already be in the log and the exit must still be the clean
    exit code — never the disk error in the crash's place."""
    real = at.append_ledger

    def append(entry):
        if entry.get("action") == "runner_crash":
            raise OSError(28, "No space left on device")
        return real(entry)

    monkeypatch.setattr(at, "append_ledger", append)
    ended, log = _crash_the_loop(monkeypatch, PermissionError(13, "Access is denied"))
    assert ended.value.code == 1
    text = log.read_text(encoding="utf-8")
    assert "runner crashed" in text and "PermissionError" in text, text


# ------------------------------- a later write lands AFTER the log's lines
def test_the_runner_points_its_output_at_the_end_of_its_log_before_it_runs():
    """On every platform, read in the parsed `__main__` block: the output is
    moved to the end of the room's log BEFORE `run_forever`, whose first
    words can be a refusal printed to stderr."""
    tree = ast.parse(pathlib.Path(at.__file__).read_text(encoding="utf-8"))
    main = [n for n in tree.body if isinstance(n, ast.If)
            and ast.unparse(n.test) in ("__name__ == '__main__'", '__name__ == "__main__"')]
    assert len(main) == 1
    # in SOURCE order: ast.walk is breadth-first
    found = sorted((n for n in ast.walk(main[0]) if isinstance(n, ast.Call)),
                   key=lambda n: (n.lineno, n.col_offset))
    calls = [ast.unparse(n.func) for n in found]
    assert "_append_std_streams_to" in calls and "run_forever" in calls, calls
    assert calls.index("_append_std_streams_to") < calls.index("run_forever"), calls


@pytest.mark.skipif(os.name != "nt", reason=(
    "POSIX hands the child O_APPEND along with the descriptor, so this only "
    "ever happened on Windows; there the test passes with or without the fix"))
def test_a_later_stderr_write_lands_after_the_lines_it_used_to_overwrite(tmp_path, monkeypatch):
    """The real `start_runner` spawns the real module as `__main__`, while
    another runner holds the run lock — the case that erased #6B08FF64's
    Oct 02, 2026 4:09pm 'loop starting' line. The new runner refuses on
    stderr; the healthy runner's lines, appended after the spawn, must
    survive, with the refusal after them.

    Safe by construction: the child's home is `tmp_path` (it works out
    ~/.tradingagents from its own environment), it refuses at the run lock
    before any price feed, order or trade record, and the feed would refuse
    anyway because the test's environment says pytest. The one change to the
    command is a wait for a go-file BEFORE the module runs, so the lines can
    be appended between the spawn and the child's first write."""
    home = tmp_path / "home"
    store = home / ".tradingagents"
    store.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(home))         # Windows' ~ for the child
    monkeypatch.setattr(at, "STATE_DIR", store)
    for name in ("LOG_PATH", "PID_PATH", "LOCK_PATH", "WANT_PATH"):
        monkeypatch.setattr(at, name, store / getattr(at, name).name)
    log = at._pp(at.LOG_PATH)
    before = ["Oct 02, 2026 4:08pm INFO scan VUG_USDT[paper]: 0 of 4 slot(s) open · flat"]
    log.write_text("".join(x + "\n" for x in before), encoding="utf-8")
    go = tmp_path / "go"
    real_popen = at.subprocess.Popen
    spawned: list = []

    def popen(args, **kw):
        assert list(args[1:]) == ["-m", "tradingagents.auto_trader", "run"], args
        wait_then_run = (
            "import os, runpy, time\n"
            f"go = {str(go)!r}\n"
            "end = time.time() + 60\n"
            "while not os.path.exists(go) and time.time() < end:\n"
            "    time.sleep(0.02)\n"
            "runpy.run_module('tradingagents.auto_trader', run_name='__main__',"
            " alter_sys=True)\n")
        proc = real_popen([args[0], "-c", wait_then_run, "run"], **kw)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(at.subprocess, "Popen", popen)
    holder = open(at._pp(at.LOCK_PATH), "w")                 # noqa: SIM115
    at.portable.lock_exclusive(holder, blocking=False)       # a runner is up
    try:
        at.start_runner()
        after = [f"Oct 02, 2026 4:09pm INFO auto-trader loop starting "
                 f"(PAPER — simulated) — line {i} of the runner already up"
                 for i in range(5)]
        with log.open("a", encoding="utf-8") as fh:
            fh.write("".join(x + "\n" for x in after))
        go.write_text("go", encoding="utf-8")
        code = spawned[0].wait(timeout=180)
    finally:
        go.write_text("go", encoding="utf-8")
        if spawned and spawned[0].poll() is None:
            spawned[0].kill()
        at.portable.unlock(holder)
        holder.close()

    lines = log.read_text(encoding="utf-8").splitlines()
    shown = "\n".join(lines)
    assert code == 1, shown
    for x in before + after:
        assert x in lines, f"written over: {x!r}\n--- the log ---\n{shown}"
    said = [i for i, x in enumerate(lines) if "another auto-trader" in x]
    assert said, f"the refusal never reached the log\n{shown}"
    assert said[0] > lines.index(after[-1]), shown
