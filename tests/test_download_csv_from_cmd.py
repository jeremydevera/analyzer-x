"""The full CSV from a command window — progress there, file in G:\\Download.

Operator, Sep 25, 2026: *"Instead of downloading via browser, can i see
progress via cmd then wright it in my g drive/download folder? The format
should br yyyy-mm-dd/time"*. `tradingagents/csv_download.py`, launched by
`download_csv.bat`, drives the SAME db_jobs export the browser's button does.
"""
from __future__ import annotations

import io
import json
import shlex
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

SPECS = [
    {"min_winrate": 85, "tp_over_sl": True, "days": 30, "sort": "profit", "desc": True},
    {"coin": "CAKE", "tf": "1h", "min_winrate": 90.5, "max_tp": 3, "max_sl": 1.2,
     "days": 7, "sort": "winrate", "desc": False},
    {"signal": "cf_obretest_l1", "profitable": True, "min_trades": 5,
     "group": "stocks", "asset": "crypto", "sizing": "flat", "measured_days": 3,
     "min_tp": 1, "min_sl": 0.5, "days": 60, "sort": "dd"},
]


def _parse(cmd: str) -> dict:
    from tradingagents import csv_download as cd

    argv = shlex.split(cmd)[1:]        # the .bat itself is the first word
    return cd.spec_from(cd.parser().parse_args(argv))


@pytest.mark.parametrize("spec", SPECS)
def test_the_printed_command_builds_exactly_the_filter_on_screen(spec):
    from tradingagents import csv_download as cd, full_export as fx

    for store in ("v1", "v2"):
        cmd = cd.command_for(spec, store)
        assert f"--store {store}" in cmd
        assert fx.key_of(_parse(cmd)) == fx.key_of(spec), cmd


def test_every_filter_the_full_csv_takes_has_an_option():
    from tradingagents import csv_download as cd, full_export as fx

    opts = cd.parser()._option_string_actions
    for key in fx.FILTER_KEYS:
        assert "--" + key.replace("_", "-") in opts, key


def test_the_file_lands_in_a_day_folder_named_yyyy_mm_dd_with_the_time_in_front(tmp_path):
    from tradingagents import csv_download as cd
    from tradingagents.positions_view import fmt_when

    when = time.mktime((2026, 9, 5, 20, 3, 0, 0, 0, -1))
    t = cd.dated_target(tmp_path, "v2-full-x.csv", when)
    assert t.parent == tmp_path / "2026-09-05"
    # the time exactly as the screens print it, colon swapped for a dash
    assert fmt_when(when).endswith("8:03pm")
    assert t.name == "8-03pm v2-full-x.csv"
    t.parent.mkdir(parents=True)
    t.write_text("first")
    again = cd.dated_target(tmp_path, "v2-full-x.csv", when)
    assert again.name == "8-03pm (2) v2-full-x.csv", "an earlier file is never overwritten"


class _Jobs:
    """db_jobs, as the command sees it: a status that moves on each read."""

    def __init__(self, states, running=None):
        self.states = list(states)
        self.first = running or {}
        self.started: list = []
        self.stops = 0

    def status(self, kind):
        if self.first is not None:
            first, self.first = self.first, None
            return first
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    def start(self, kind, spec):
        self.started.append((kind, spec))
        return 4242

    def request_stop(self, kind):
        self.stops += 1


@pytest.fixture
def cmdenv(tmp_path, monkeypatch):
    from tradingagents import csv_download as cd, db_jobs as dj, full_export as fx

    exports = tmp_path / "exports"
    exports.mkdir()
    monkeypatch.setattr(fx, "export_dir", lambda store="v1": exports)
    out = tmp_path / "Download"

    def use(jobs):
        monkeypatch.setattr(dj, "status", jobs.status)
        monkeypatch.setattr(dj, "start", jobs.start)
        monkeypatch.setattr(dj, "request_stop", jobs.request_stop)
        return jobs

    return cd, exports, out, use


def _go(cd, spec, out, store="v2", clock=None):
    buf = io.StringIO()
    code = cd.run(spec, store, out, poll_s=0, screen=cd.Screen(buf),
                  clock=clock or time.time, sleep=lambda s: None)
    return code, buf.getvalue()


def test_it_starts_the_build_shows_progress_and_saves_the_file(cmdenv):
    from tradingagents import full_export as fx

    cd, exports, out, use = cmdenv
    spec = SPECS[0]
    now = time.time()
    (exports / "v2-full-x.csv").write_text("id,coin\nA1,AAA\n", encoding="utf-8")
    key = fx.key_of(spec)
    jobs = use(_Jobs([
        {"running": True, "started": now, "key": key, "phase": "re-checking",
         "done": 50, "total": 200, "eta_s": 90},
        {"running": True, "started": now, "key": key, "phase": "writing the file",
         "done": 120, "total": 200},
        {"running": False, "started": now, "key": key, "finished": now,
         "file": "v2-full-x.csv", "done": 1, "total": 200},
    ], running={"running": False, "started": now - 9999, "file": "old.csv"}))
    code, text = _go(cd, spec, out, clock=lambda: now)
    assert code == 0, text
    assert jobs.started == [("export_v2", spec)]
    assert "re-checking" in text and "25.0%" in text and "writing the file" in text
    saved = list(out.rglob("*.csv"))
    assert len(saved) == 1 and saved[0].parent.parent == out
    assert saved[0].read_text(encoding="utf-8") == "id,coin\nA1,AAA\n"
    assert f"Saved to {saved[0]}" in text
    assert not list(out.rglob("*.part")), "no half-copied file left behind"
    assert (exports / "v2-full-x.csv").exists(), "the browser's link still has its file"


def test_the_previous_builds_finished_file_is_never_taken_for_this_one(cmdenv):
    from tradingagents import full_export as fx

    cd, exports, out, use = cmdenv
    now = time.time()
    (exports / "new.csv").write_text("new", encoding="utf-8")
    key = fx.key_of(SPECS[0])
    use(_Jobs([
        # the progress file still says the LAST build finished — older start
        {"running": False, "started": now - 3600, "key": key, "file": "old.csv"},
        {"running": False, "started": now, "key": key, "file": "new.csv",
         "finished": now, "done": 1, "total": 1},
    ], running={"running": False}))
    code, text = _go(cd, SPECS[0], out, clock=lambda: now)
    assert code == 0, text
    assert [p.read_text() for p in out.rglob("*.csv")] == ["new"]


def test_another_filters_build_is_named_and_never_disturbed(cmdenv):
    cd, _exports, out, use = cmdenv
    jobs = use(_Jobs([{}], running={"running": True, "key": '{"days": 7}', "started": 1}))
    code, text = _go(cd, SPECS[0], out)
    assert code == 2
    assert jobs.started == [] and jobs.stops == 0
    assert '{"days": 7}' in text


def test_the_same_filter_already_building_is_watched_not_started_twice(cmdenv):
    from tradingagents import full_export as fx

    cd, exports, out, use = cmdenv
    now = time.time()
    key = fx.key_of(SPECS[0])
    (exports / "f.csv").write_text("x", encoding="utf-8")
    jobs = use(_Jobs([
        {"running": True, "started": now - 60, "key": key, "phase": "writing the file",
         "done": 5, "total": 10},
        {"running": False, "started": now - 60, "key": key, "file": "f.csv",
         "finished": now, "done": 10, "total": 10},
    ], running={"running": True, "started": now - 60, "key": key}))
    code, text = _go(cd, SPECS[0], out, clock=lambda: now)
    assert code == 0, text
    assert jobs.started == []
    assert "already being built" in text


def test_a_build_that_dies_says_so(cmdenv):
    cd, _exports, out, use = cmdenv
    now = time.time()
    use(_Jobs([{"running": False, "started": now, "note": "process died before finishing"}],
              running={"running": False}))
    code, text = _go(cd, SPECS[0], out, clock=lambda: now)
    assert code == 1
    assert "FAILED" in text and "process died" in text
    assert not out.exists() or not list(out.rglob("*.csv"))


def test_ctrl_c_asks_the_build_to_stop(cmdenv):
    from tradingagents import full_export as fx

    cd, _exports, out, use = cmdenv
    now = time.time()
    key = fx.key_of(SPECS[0])
    jobs = use(_Jobs([
        {"running": False, "started": now, "key": key, "stopped": True,
         "note": "stopped while writing"},
    ], running={"running": False}))
    calls = {"n": 0}

    def sleep(_s):
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyboardInterrupt

    buf = io.StringIO()
    code = cd.run(SPECS[0], "v2", out, poll_s=0, screen=cd.Screen(buf),
                  clock=lambda: now, sleep=sleep)
    assert code == 130
    assert jobs.stops == 1
    assert "Stopping" in buf.getvalue() and "Stopped" in buf.getvalue()


def test_a_copy_that_fails_names_where_the_file_is(cmdenv, monkeypatch):
    from tradingagents import full_export as fx

    cd, exports, out, use = cmdenv
    now = time.time()
    (exports / "f.csv").write_text("x", encoding="utf-8")
    use(_Jobs([{"running": False, "started": now, "key": fx.key_of(SPECS[0]),
                "file": "f.csv", "finished": now, "done": 1, "total": 1}],
              running={"running": False}))

    def full(src, dst):
        Path(dst).write_text("half")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(cd.shutil, "copyfile", full)
    code, text = _go(cd, SPECS[0], out, clock=lambda: now)
    assert code == 1
    assert str(exports / "f.csv") in text
    assert not list(out.rglob("*.csv")) and not list(out.rglob("*.part"))


def test_a_new_export_names_its_filter_from_the_first_tick(tmp_path, monkeypatch):
    """Before the job's own process published `key`, a second press of the
    SAME filter read "another filter is being built"."""
    from tradingagents import db_jobs as dj, full_export as fx

    written: dict = {}
    monkeypatch.setattr(dj, "status", lambda kind: {})
    monkeypatch.setattr(dj, "disk_holder", lambda kind: None)
    monkeypatch.setattr(dj, "STATE_DIR", tmp_path)
    f = {k: tmp_path / f"{k}.x" for k in ("spec", "progress", "pid", "stop")}
    monkeypatch.setitem(dj.FILES, "export_v2", f)
    monkeypatch.setattr(dj, "_write", lambda path, obj: None)
    monkeypatch.setattr(dj, "_write_progress", lambda path, obj: written.update(obj))

    class P:
        pid = 777

    monkeypatch.setattr(dj.subprocess, "Popen", lambda *a, **k: P())
    dj.start("export_v2", SPECS[0])
    assert written.get("key") == fx.key_of(SPECS[0])
    assert written.get("running") is True


def test_the_screen_asks_the_server_for_the_line(monkeypatch):
    from tradingagents import api, csv_download as cd

    got = api.strategies_export_command_v2(dict(SPECS[0]))
    assert got["command"] == cd.command_for(SPECS[0], "v2")
    assert got["folder"] == str(cd.DOWNLOAD_DIR)
    assert api.strategies_export_command(dict(SPECS[0]))["command"].count("--store v1") == 1


def test_the_panel_shows_the_line_with_a_copy_button():
    src = (REPO / "webapp/src/components/backtest/StrategiesPanel.tsx").read_text(encoding="utf-8")
    assert "strategiesExportCommand(" in src
    assert "<CopyableId id={exportCmd.command}" in src
    assert "or build it from a command window" in src
    # ONE backslash on screen needs "\\" in the template: "\<" printed none,
    # and the line read "G:\Download<date>" (seen in the browser, Sep 25, 2026)
    line = next(ln for ln in src.splitlines()
                if "or build it from a command window" in ln and "${exportCmd.folder}" in ln)
    assert r"${exportCmd.folder}\\yyyy-mm-dd\\" in line, line


def test_the_launcher_runs_the_module_with_every_option():
    bat = (REPO / "download_csv.bat").read_bytes()
    assert b"\r\n" in bat, "a .bat without CRLF can misread its own lines in cmd"
    text = bat.decode("ascii")
    assert "-m tradingagents.csv_download %*" in text
    # from the REPO folder, whatever folder cmd is in — the module is not
    # installed, so `-m` only finds it there — and the exit code kept
    assert 'pushd "%~dp0"' in text and "popd" in text
    assert r'".venv\Scripts\python.exe"' in text
    assert "exit /b %rc%" in text


def test_the_default_folder_is_the_operators_g_download():
    from tradingagents import csv_download as cd

    src = (REPO / "tradingagents/csv_download.py").read_text(encoding="utf-8")
    assert r'r"G:\Download"' in src
    assert cd.parser().parse_args([]).out == str(cd.DOWNLOAD_DIR)


def test_nothing_it_prints_can_end_the_watch_on_a_code_page_console(cmdenv):
    """cmd's code page cannot print '—' or '…'; `main` sets errors=replace,
    and a failed character must never raise mid-build."""
    src = (REPO / "tradingagents/csv_download.py").read_text(encoding="utf-8")
    assert 'reconfigure(errors="replace")' in src
    cd, *_ = cmdenv
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="cp437", errors="replace")
    cd.Screen(out).say("re-check — done …")
    out.flush()
    assert raw.getvalue()


def test_it_is_json_safe_for_the_route():
    from tradingagents import api

    json.dumps(api.strategies_export_command(dict(SPECS[1])))
