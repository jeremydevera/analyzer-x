"""The Runner feed must survive any byte in the log.

2026-09-05: the operator — "IS THE RUNNER ACTIVE I DONT SEE ANY LOGS IN RUNNER
FEED". The runner was healthy (pid 7648, 30 gate checks in 15 minutes). The
feed was answering HTTP 500 because ONE byte, a Windows-1252 em dash (0x97)
written by a runner spawned without PYTHONUTF8, made `log_tail`'s strict UTF-8
read raise. An empty feed reads as a dead runner; a feed must never die on a
character.
"""
from tradingagents import auto_trader as at


def test_log_tail_survives_the_exact_byte_that_broke_it(tmp_path, monkeypatch):
    log = tmp_path / "auto_trade.log"
    log.write_bytes("healthy line one\n".encode("utf-8")
                    + b"stop it first \x97 kill 8284\n"      # the 0x97
                    + "healthy line two\n".encode("utf-8"))
    monkeypatch.setattr(at, "LOG_PATH", log)
    lines = at.log_tail(10)
    assert len(lines) == 3, "every line survives"
    assert lines[0] == "healthy line one"
    assert lines[2] == "healthy line two"
    assert "kill 8284" in lines[1], "the bad byte is replaced, not fatal"


def test_the_runner_child_is_spawned_utf8():
    """...so the bad byte is not written again in the first place."""
    import inspect

    src = inspect.getsource(at.start_runner)
    assert '"PYTHONUTF8": "1"' in src
