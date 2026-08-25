"""Restarting the app must not kill the jobs it launched.

Aug 25, 2026 3:55pm on the PC: `start.py` restarted the API while a 4,985-pair
backtest (pid 15020, 11 workers, 60 pairs done) was running. On Windows the
launcher freed port 8787 with `taskkill /PID <api> /T /F` -- /T is the whole
process TREE -- and the detached job, a child of that API process, died with
it. The supervisor logged "backtest restarted after a crash" a minute later.
On the Mac the same restart is `kill <pid>`: the API dies, its jobs live.

/T is right for the UI port: `npx next start` is a chain of three processes
with no children worth keeping. It is wrong for the API port, whose children
are the detached jobs (db_jobs backtest/download/stratbt, rows_index) -- each
checkpointed, supervised, and guarded by its own pidfile.
"""
import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def start(monkeypatch):
    spec = importlib.util.spec_from_file_location("start_launcher_under_test", REPO / "start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return mod


def test_on_windows_the_api_pid_is_killed_alone_and_the_ui_chain_as_a_tree(start, monkeypatch):
    calls = []
    monkeypatch.setattr(start, "WINDOWS", True)
    monkeypatch.setattr(start.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    start.kill(4242, tree=False)
    start.kill(4343, tree=True)
    assert calls[0] == ["taskkill", "/PID", "4242", "/F"], "no /T: the API's jobs must survive"
    assert calls[1] == ["taskkill", "/PID", "4343", "/T", "/F"], "the next chain goes as a tree"


def test_free_port_knows_which_port_owns_detached_children(start, monkeypatch):
    seen = []
    monkeypatch.setattr(start, "port_pids", lambda port: [100 + port])
    monkeypatch.setattr(start, "kill", lambda pid, *, tree: seen.append((pid, tree)))
    start.free_port(start.API_PORT, tree=False)
    start.free_port(start.UI_PORT, tree=True)
    assert seen == [(100 + start.API_PORT, False), (100 + start.UI_PORT, True)]


def test_both_commands_free_the_api_port_without_the_tree():
    src = (REPO / "start.py").read_text(encoding="utf-8")
    assert src.count("free_port(API_PORT, tree=False)") == 2, "stop and start alike"
    assert src.count("free_port(UI_PORT, tree=True)") == 2
    assert "free_port(API_PORT)\n" not in src and "free_port(UI_PORT)\n" not in src


def test_unix_is_unchanged_a_single_sigterm(start, monkeypatch):
    sent = []
    monkeypatch.setattr(start, "WINDOWS", False)
    monkeypatch.setattr(start.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    start.kill(7, tree=False)
    start.kill(8, tree=True)
    assert sent == [(7, start.signal.SIGTERM), (8, start.signal.SIGTERM)]
