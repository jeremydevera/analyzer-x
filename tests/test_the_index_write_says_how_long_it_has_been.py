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
    assert "nothing is lost" in src
    assert "el >= 300" in src, "the explanation waits until it IS long (5 minutes)"


def test_the_heartbeat_always_stops(monkeypatch):
    """A thread that outlives the job would stamp a finished run as running."""
    import inspect

    src = inspect.getsource(dj._run_pairbt)
    i = src.index("_ix_stop.set()")
    j = src.index("if index_error:")
    assert i < j, "the beat is stopped before the terminal writes"
    assert "_ix_beat_t.join(" in src


# ------------------------------------------------------------------- the ETA
def test_the_eta_counts_the_rows_already_in_the_index_not_the_new_ones(monkeypatch, tmp_path):
    """Operator: "can you atlest give me ETA when will it be done". The cost
    is the rows the write REPLACES — XPIN 1h is 220 new rows against 29,040
    already stored — divided by this machine's own last measured speed."""
    monkeypatch.setattr(dj, "INDEX_RATE_FILE", tmp_path / "rate.json")
    assert dj._index_rate() == dj.INDEX_RATE_FALLBACK, "a first run still has an ETA"

    dj._remember_index_rate(29_040, 3_581.0)
    assert round(dj._index_rate(), 1) == 8.1, dj._index_rate()
    # a write that failed or was instant never poisons the rate
    dj._remember_index_rate(0, 900.0)
    dj._remember_index_rate(29_040, 0.5)
    assert round(dj._index_rate(), 1) == 8.1


def test_the_line_carries_the_minutes_left(monkeypatch, tmp_path):
    published: list = []
    monkeypatch.setattr(dj, "_write", lambda path, payload: published.append(payload))
    monkeypatch.setattr(dj, "_write_progress", lambda path, payload: published.append(payload))
    monkeypatch.setattr(dj, "FILES", {**dj.FILES, "pairbt": {
        k: tmp_path / f"pairbt.{k}" for k in dj.FILES["pairbt"]}})
    monkeypatch.setattr(dj, "_pair_rows_in_index", lambda *a, **k: 29_040)
    monkeypatch.setattr(dj, "_index_rate", lambda *a, **k: 8.1)

    from tradingagents import market_sweep as msw, rows_index as ri
    monkeypatch.setattr(msw, "candle_index", lambda scan=False, **k: {})
    monkeypatch.setattr(msw, "pair_watermark", lambda c, t, root=None: 0)
    monkeypatch.setattr(msw, "run_pair", lambda *a, **k: {"rows": [{"coin": "XPIN"}] * 220})
    monkeypatch.setattr(msw, "ROWDIR", tmp_path)
    monkeypatch.setattr(ri, "index_pair", lambda path, *a, **k: time.sleep(4.0) or 29_040)
    monkeypatch.setattr(ri, "ask_first", lambda p: [p])
    monkeypatch.setattr(ri, "stale_pairs", lambda: [])

    dj._run_pairbt({"coin": "XPIN", "tf": "1h", "signal": "ote", "base": 5.0, "days": 30})
    beats = [p for p in published if "writing" in str(p.get("now") or "")]
    assert beats, published
    said = beats[-1]
    assert "29,040 row(s)" in said["now"], said["now"]
    assert "min left" in said["now"], said["now"]
    assert said.get("index_eta_s") and said["index_eta_s"] > 3000, said


# ------------------------------------------------------------ and ON SCREEN
def test_the_panel_draws_the_bar_and_names_it_an_estimate():
    """Operator: "i want you to show in ui". The bar is TIME (minutes gone vs
    the estimate), because the write cannot count its own rows — so it says
    "estimate" where it is one, and says which step is running."""
    from pathlib import Path

    panel = (Path(__file__).resolve().parents[1]
             / "webapp/src/components/backtest/StrategiesPanel.tsx").read_text(encoding="utf-8")
    i = panel.index("HOW FAR ALONG, AND HOW LONG LEFT")
    block = panel[i:i + 3200]
    assert "pairJob.index_seconds" in block and "pairJob.index_eta_s" in block
    assert "min so far" in block and "min left" in block
    assert "estimate from this PC's last write" in block, "never presented as exact"
    assert "jobIsThisRow" in block, "another row's job may not draw this row's bar"
    assert "the measuring is already done" in block, "says WHICH step is slow"
    # the width is bounded: a slow write must not render 100% and sit there
    assert "Math.min(99" in block


def test_the_client_type_carries_the_three_fields():
    from pathlib import Path

    api_ts = (Path(__file__).resolve().parents[1]
              / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    for field in ("index_seconds?: number;", "index_rows?: number;",
                  "index_eta_s?: number | null;"):
        assert field in api_ts, field


def test_no_bar_is_drawn_without_an_estimate():
    """Without `index_eta_s` the width would be elapsed/elapsed = 100% — a
    full bar over a write with 50 minutes to go. The words stay; the bar
    waits for a number it can honestly draw."""
    from pathlib import Path

    panel = (Path(__file__).resolve().parents[1]
             / "webapp/src/components/backtest/StrategiesPanel.tsx").read_text(encoding="utf-8")
    i = panel.index("NO BAR WITHOUT AN ESTIMATE")
    block = panel[i:i + 900]
    assert "pairJob.index_eta_s ? (" in block, block[:300]
    assert "no estimate yet" in panel[i:i + 2400]
