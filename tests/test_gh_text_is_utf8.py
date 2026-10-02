"""The GitHub CLI's answers are read as UTF-8, whatever the process's codepage
(docs/RCA.md RCA-2026-10-02-G).

gh writes UTF-8. `cloud_sweep._gh` ran it with `text=True` and nothing else,
which decodes with the locale — cp1252 on this PC unless Python's UTF-8 mode
is on, and only the app's own start (start.py, PYTHONUTF8=1) turns it on. So
a run titled "Forecast v2 · base · replay 37060968220" came back as
"Forecast v2 Â· base …" in any other process, and a dispatch waiting for its
own run by title never found it — a retry would have started a second one.

Driven through a REAL pipe: the child writes the title's UTF-8 bytes the way
gh does, and the real `subprocess.run` decodes them as `_gh` asks.
"""
import subprocess
import sys

from tradingagents import cloud_sweep as cs

TITLE = "Forecast v2 · base · replay 37060968220 "


def test_gh_reads_a_run_title_as_utf8_through_a_real_pipe(monkeypatch):
    real = subprocess.run
    seen = {}

    def run(cmd, **kw):
        assert cmd[0] == "gh"
        seen.update(kw)
        child = [sys.executable, "-c",
                 f"import sys; sys.stdout.buffer.write({TITLE!r}.encode('utf-8'))"]
        return real(child, **kw)

    monkeypatch.setattr(cs.subprocess, "run", run)
    got = cs._gh("run", "list")
    assert got == TITLE, [hex(ord(c)) for c in got[:16]]
    assert seen.get("encoding") == "utf-8", "never the locale's codepage"


def test_a_dispatch_finds_its_run_by_a_title_gh_sends_as_utf8(monkeypatch):
    """The whole path the chain takes: `forecast_v2_daily.dispatch` lists runs
    through `_gh` and matches its own title."""
    import json

    from tradingagents import forecast_v2_daily as fd

    real = subprocess.run
    calls = {"list": 0}

    def run(cmd, **kw):
        if cmd[1:3] == ("run", "list"):
            calls["list"] += 1
            rows = [] if calls["list"] == 1 else [
                {"databaseId": 37061908183, "displayTitle": TITLE, "createdAt": "2026-10-02T20:38:45Z"}]
            body = json.dumps(rows, ensure_ascii=False)
        else:
            body = ""
        child = [sys.executable, "-c", f"import sys; sys.stdout.buffer.write({body!r}.encode('utf-8'))"]
        return real(child, **kw)

    monkeypatch.setattr(cs.subprocess, "run", run)
    monkeypatch.setattr(fd.time, "sleep", lambda s: None)
    inputs = {"stage": "base", "source_run": 37060968220, "custom": ""}
    assert fd.dispatch(fd.FORECAST_WF, inputs, "jeremydvera/analyzer-x") == 37061908183
