"""The slow half of a row's UPDATE says how long it has been going.

Operator, `Sep 18, 2026 9:40pm`, watching "XPIN 1h: indexing 220 row(s)" for
an hour: *"i dont know how many percentage complete is it, where can i see
the status?"*. The write is ONE `DELETE` plus one `executemany` inside
SQLite, so there is no percentage to count — measured that evening, 29,040
rows took 59.7 minutes while Backtest v2 had the disk, at 0.2 s of CPU per
10 s. A line that never changes reads as a hang, so the job publishes the
ELAPSED minutes while it waits, and says what is normal once it is long.
"""
from __future__ import annotations

import time

import pytest

from tradingagents import db_jobs as dj


def test_the_heartbeat_publishes_minutes_while_the_write_runs(monkeypatch, tmp_path):
    published: list = []

    monkeypatch.setattr(dj, "_write", lambda path, payload: published.append(payload))
    monkeypatch.setattr(dj, "_write_progress", lambda path, payload: published.append(payload))
    monkeypatch.setattr(dj, "FILES", {**dj.FILES, "pairbt": {
        k: tmp_path / f"pairbt.{k}" for k in dj.FILES["pairbt"]}})

    from tradingagents import market_sweep as msw, rows_index as ri

    monkeypatch.setattr(msw, "candle_index", lambda scan=False, **k: {})
    monkeypatch.setattr(msw, "pair_watermark", lambda c, t, root=None: 0)
    monkeypatch.setattr(msw, "run_pair", lambda *a, **k: {"rows": [{"coin": "XPIN"}] * 220})
    monkeypatch.setattr(msw, "ROWDIR", tmp_path)

    def slow_index(path, *a, **k):
        time.sleep(7.0)                       # two heartbeats at 3 s
        return 29_040

    monkeypatch.setattr(ri, "index_pair", slow_index)
    monkeypatch.setattr(ri, "ask_first", lambda p: [p])
    monkeypatch.setattr(ri, "stale_pairs", lambda: [])

    dj._run_pairbt({"coin": "XPIN", "tf": "1h", "signal": "ote", "base": 5.0, "days": 30})

    beats = [p for p in published if "writing" in str(p.get("now") or "")]
    assert beats, [str(p.get("now")) for p in published]
    assert "min so far" in beats[-1]["now"], beats[-1]["now"]
    assert beats[-1].get("index_seconds") is not None
    assert "220" in beats[-1]["now"], "it names the rows it is writing"


def test_a_long_write_explains_itself_rather_than_looking_stuck():
    """After five minutes the line says why it is slow and that nothing is
    lost — the sentence the operator needed at minute 40."""
    import inspect

    src = inspect.getsource(dj._run_pairbt)
    assert "min so far" in src
    assert "the measuring is already done and nothing is lost" in src.replace("\n", " ").replace("  ", " ") \
        or "nothing is lost" in src
    assert "mins >= 5" in src, "the explanation waits until it IS long"


def test_the_heartbeat_always_stops(monkeypatch):
    """A thread that outlives the job would stamp a finished run as running."""
    import inspect

    src = inspect.getsource(dj._run_pairbt)
    i = src.index("_ix_stop.set()")
    j = src.index("if index_error:")
    assert i < j, "the beat is stopped before the terminal writes"
    assert "_ix_beat_t.join(" in src
