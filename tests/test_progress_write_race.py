"""db_jobs._write must survive two writers and a reader on the same file.

Aug 25, 2026 ~3:58pm on the PC: the backtest job's progress `done` froze at
64 of 4,985 while its 11 workers kept measuring for twenty minutes. Two
threads publish the same progress file -- the per-pair callback and the 2 s
heartbeat -- and both wrote the SAME `db_backtest.tmp` before `os.replace`.
On Windows a file another handle has open cannot be replaced or removed, so
the collision raised PermissionError inside the per-pair callback. Reproduced
here before the fix: 6,419 errors in six seconds. On the Mac `rename(2)`
never cares, which is why it had never been seen.
"""
import tempfile
import threading
import time
from pathlib import Path

from tradingagents import db_jobs


def test_two_writers_and_a_reader_never_raise():
    p = Path(tempfile.mkdtemp()) / "db_backtest.json"
    errors, seen = [], []
    stop = time.time() + 2.5

    def writer(tag):
        n = 0
        while time.time() < stop:
            try:
                db_jobs._write(p, {"tag": tag, "n": n})
                n += 1
            except Exception as exc:          # noqa: BLE001 - the whole point
                errors.append(f"{tag}: {type(exc).__name__}: {exc}")
        seen.append(n)

    def reader():
        while time.time() < stop:
            try:
                db_jobs._read(p)
            except Exception as exc:          # noqa: BLE001
                errors.append(f"reader: {type(exc).__name__}: {exc}")

    ts = [threading.Thread(target=writer, args=("callback",)),
          threading.Thread(target=writer, args=("heartbeat",)),
          threading.Thread(target=reader)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == [], errors[:5]
    assert min(seen) > 50, seen               # both writers actually ran
    assert db_jobs._read(p).get("tag") in ("callback", "heartbeat")
    leftovers = [f.name for f in p.parent.iterdir() if f.name != p.name]
    assert leftovers == [], f"tmp files left behind: {leftovers}"
