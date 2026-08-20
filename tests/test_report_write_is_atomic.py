"""A failed render must never leave a blank report behind.

Operator, 2026-08-20: "i ran the backtest for trend50 - pi / why does it not
show any result". The run had raised "rows have inconsistent keys" out of
_pack — but write_report had already opened the target with mode "w", which
truncates on open. The result was a ZERO-BYTE html file the UI happily linked
to, so the click opened a blank page.
"""
from __future__ import annotations

import os

import pytest

from tradingagents import backtest_report as br


def _payload(rows):
    return {"rows": rows, "series": {}, "meta": {}}


def test_a_failed_render_leaves_no_file_at_all(tmp_path, monkeypatch):
    target = tmp_path / "report.html"
    monkeypatch.setattr(br, "render",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        br.write_report(str(target), _payload([]), title="t")
    assert not target.exists(), "a failed build must not create the file"


def test_a_failed_render_keeps_the_previous_report(tmp_path, monkeypatch):
    target = tmp_path / "report.html"
    target.write_text("PREVIOUS GOOD REPORT", encoding="utf-8")
    monkeypatch.setattr(br, "render",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        br.write_report(str(target), _payload([]), title="t")
    assert target.read_text(encoding="utf-8") == "PREVIOUS GOOD REPORT"


def test_no_partial_file_is_left_behind(tmp_path, monkeypatch):
    target = tmp_path / "report.html"
    monkeypatch.setattr(br, "render",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        br.write_report(str(target), _payload([]), title="t")
    leftovers = [p for p in os.listdir(tmp_path) if p.startswith(".")]
    assert not leftovers, f"temp file left behind: {leftovers}"


def test_a_good_render_still_writes(tmp_path, monkeypatch):
    target = tmp_path / "report.html"
    monkeypatch.setattr(br, "render", lambda *a, **k: "<html>ok</html>")
    br.write_report(str(target), _payload([]), title="t")
    assert target.read_text(encoding="utf-8") == "<html>ok</html>"


def test_the_pack_error_names_the_offending_row_and_keys():
    """A bare "inconsistent keys" told the operator nothing about which row."""
    rows = [{"coin": "PI", "tf": "30m", "signal": "trend50", "sizing": "flat",
             "profit": 1.0},
            {"coin": "PI", "tf": "4h", "signal": "mom15", "sizing": "flat"}]
    with pytest.raises(RuntimeError) as e:
        br._pack({"rows": rows})
    msg = str(e.value)
    assert "row 1" in msg and "PI" in msg and "4h" in msg and "mom15" in msg
    assert "profit" in msg, "the missing key must be named"
