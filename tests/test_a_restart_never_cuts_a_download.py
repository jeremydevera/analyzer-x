"""A restart waits for the downloads it would cut (RCA-2026-09-24-D).

Operator, Sep 24, 2026: *"when downloading using this filter im having
internal server error in csv, why is this occuring again? i had same issue
from the past"*. The screen log holds the answer: their download (Winrate 70%
or better · TP >= SL · last 30 days) STARTED at 5:01am and never finished —
the app was restarted under it, and the UI's proxy answered "Internal Server
Error" when the API vanished (next/dist/server/lib/router-utils/
proxy-request.js). A second download was cut the same way at 373 KB of
905 KB by the 5:13am restart.

The first time these words appeared (Sep 09-10, 2026) the proxy's 30-second
limit was the cause; the fix closed that cause and left every other way to
produce the same words open. So these tests hold the CLASS: whatever stops
the API must first see what it would cut, and the log of the run it stops is
kept to be read.
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

from tradingagents import api

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def start():
    spec = importlib.util.spec_from_file_location("start_launcher", ROOT / "start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def quiet_csv(monkeypatch):
    """Three rows out of a fake store, and no screen-log writes."""
    from tradingagents import rows_index as ri, screen_log as sl

    def rows(**kw):
        for i in range(3):
            yield {c: None for c in ri.COLS} | {"id": f"ID{i}", "winrate": 80.0,
                                                "trades": 10, "profit": 1.0}
    monkeypatch.setattr(ri, "iter_rows", rows)
    monkeypatch.setattr(ri, "balanced_score", lambda r: (5.0, "why"))
    monkeypatch.setattr(sl, "record", lambda *a, **k: None)

    class _W:
        def __init__(self, *a, **k): pass
        def see(self, r): pass
        def notes(self): return []
    monkeypatch.setattr(sl, "Watch", _W)
    api._ACTIVE_DOWNLOADS.clear()


def test_a_download_is_listed_while_it_streams_and_gone_when_it_ends(quiet_csv):
    gen = api.strategies_csv_lines(min_winrate=70, tp_over_sl=True, days=0)
    next(gen)                                     # the header row
    busy = api.system_busy()
    assert busy["count"] == 1
    d = busy["downloads"][0]
    assert d["what"] == "strategies CSV · win % >= 70 · TP >= SL"
    assert d["since"] and "," in d["since"], "the one date format"
    next(gen)                                     # the first row
    assert api.system_busy()["downloads"][0]["rows"] == 1
    for _ in gen:
        pass
    assert api.system_busy() == {"count": 0, "downloads": []}


def test_a_download_the_browser_abandons_is_not_listed_for_ever(quiet_csv):
    gen = api.strategies_csv_lines(days=30)
    next(gen)
    assert api.system_busy()["count"] == 1
    gen.close()                                   # the client went away
    assert api.system_busy()["count"] == 0


def test_the_route_exists_and_both_csv_routes_stream_through_the_listed_generator():
    src = (ROOT / "tradingagents" / "api.py").read_text(encoding="utf-8")
    assert '@app.get("/api/system/busy")' in src
    body = inspect.getsource(api.strategies_csv_lines)
    assert "_dl = _download_started(" in body and "_download_finished(_dl)" in body
    assert body.index("_download_finished(_dl)") > body.rindex("raise"), \
        "unlisted in a finally, after every other exit"
    for route in (api.strategies_csv_v2,):
        assert "strategies_csv_lines(" in inspect.getsource(route)


def test_start_waits_for_a_download_then_restarts(start, monkeypatch):
    answers = [[{"what": "strategies CSV · last 30 days", "rows": 900,
                 "since": "Sep 24, 2026 5:01am"}]] * 3 + [[]]
    monkeypatch.setattr(start, "downloads_in_flight", lambda port=0: answers.pop(0))
    slept = []
    assert start.wait_for_downloads(sleep=slept.append) is True
    assert len(slept) == 3, "it polled until the download finished"


def test_start_gives_up_after_the_limit_and_says_so(start, monkeypatch, capsys):
    monkeypatch.setattr(start, "downloads_in_flight",
                        lambda port=0: [{"what": "x", "rows": 1, "since": "now"}])
    t = [0.0]
    def clock():
        t[0] += 400
        return t[0]
    assert start.wait_for_downloads(max_s=900, sleep=lambda s: None, clock=clock) is False
    out = capsys.readouterr().out
    assert "waiting for 1 download(s)" in out and "restarting anyway" in out


def test_an_api_that_does_not_answer_is_not_waited_for(start, monkeypatch):
    monkeypatch.setattr(start, "downloads_in_flight", lambda port=0: None)
    assert start.wait_for_downloads(sleep=lambda s: pytest.fail("must not wait")) is True


def test_start_and_stop_wait_before_they_free_the_api_port_unless_told_now(start):
    for fn in (start.cmd_start, start.cmd_stop):
        src = inspect.getsource(fn)
        assert "if not now:\n        wait_for_downloads()" in src, fn.__name__
        assert src.index("wait_for_downloads()") < src.index("free_port("), \
            f"{fn.__name__} waits BEFORE it kills anything"
    main = inspect.getsource(start.main)
    assert 'now="--now" in args' in main


def test_a_restart_keeps_the_previous_log(start, tmp_path):
    log = tmp_path / "api.log"
    log.write_text("the run a restart is about to end", encoding="utf-8")
    start.keep_previous(log)
    assert not log.exists()
    assert (tmp_path / "api.prev.log").read_text(encoding="utf-8") == \
        "the run a restart is about to end"
    src = inspect.getsource(start.spawn)
    assert "open(keep_previous(log)" in src, "the API and UI logs are rotated, not deleted"
    assert 'PYTHONUNBUFFERED="1"' in inspect.getsource(start.cmd_start)
