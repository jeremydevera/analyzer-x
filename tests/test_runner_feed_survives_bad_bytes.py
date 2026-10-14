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
    log.write_bytes(b"healthy line one\n"
                    + b"stop it first \x97 kill 8284\n"      # the 0x97
                    + b"healthy line two\n")
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


# Oct 14, 2026 7:23am: the Runner feed answered HTTP 500 with MemoryError.
# Main's auto_trade.log was 163 MB and log_tail read ALL of it, decoded it
# and split it into lines, to show the last 200 - on every poll of the
# screen. The feed may only read the END of the file (RCA-2026-10-14-F).

def _big_log(tmp_path, monkeypatch, lines=200_000):
    log = tmp_path / "auto_trade.log"
    body = b"".join(b"scan line %06d \x97 gate ok\n" % i for i in range(lines))
    log.write_bytes(body)
    monkeypatch.setattr(at, "LOG_PATH", log)
    return log


def test_log_tail_never_reads_the_whole_log(tmp_path, monkeypatch):
    from pathlib import Path

    _big_log(tmp_path, monkeypatch)

    def whole_file(*_a, **_k):
        raise MemoryError("the whole log was read for 200 lines")

    monkeypatch.setattr(Path, "read_bytes", whole_file)
    monkeypatch.setattr(Path, "read_text", whole_file)
    lines = at.log_tail(200)
    assert len(lines) == 200
    assert lines[-1].startswith("scan line 199999")
    assert lines[0].startswith("scan line 199800")


def test_log_tail_memory_does_not_grow_with_the_log(tmp_path, monkeypatch):
    import tracemalloc

    log = _big_log(tmp_path, monkeypatch)       # ~5.6 MB
    assert log.stat().st_size > 5_000_000
    tracemalloc.start()
    try:
        at.log_tail(200)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1_000_000, f"peak {peak:,} bytes for 200 lines"


def test_log_tail_matches_a_whole_read_on_every_shape(tmp_path, monkeypatch):
    log = tmp_path / "auto_trade.log"
    monkeypatch.setattr(at, "LOG_PATH", log)
    monkeypatch.setattr(at, "_TAIL_CHUNK", 7)    # boundaries land mid-line
    shapes = [
        b"",
        b"one line no newline",
        b"a\nb\nc\n",
        b"a\r\nb\r\nc\r\n\r\n\n  \n",
        b"\n\n\nfirst\nsecond\n",
        b"x" * 50 + b"\n" + b"y" * 50,
        "café — dash\nnächste\n".encode("utf-8") * 5,
        b"stop it first \x97 kill 8284\nok\n",
    ]
    for body in shapes:
        log.write_bytes(body)
        for n in (1, 2, 3, 5, 50):
            want = (body.decode("utf-8", errors="replace")
                    .strip().splitlines()[-n:])
            assert at.log_tail(n) == want, (body, n)


def test_log_tail_missing_log_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "LOG_PATH", tmp_path / "nope.log")
    assert at.log_tail(200) == []
