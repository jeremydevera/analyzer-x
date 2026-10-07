"""Every error becomes a GitHub issue (operator, Oct 07, 2026: "everytime the
system gets an error, file an issue to github, then i want you to investigate
if its a valid error or not, if its valid then fix it").

Spec: docs/superpowers/specs/2026-10-07-errors-become-issues-design.md

These tests hold the filer: the three sources it reads, the fingerprint that
makes one issue per fault (not per room, not per occurrence), the scrubber
that keeps every secret on this PC, and the GitHub side on ONE timeline.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradingagents import error_issues as ei


# --------------------------------------------------------------- the sources

def _report(rows):
    def fake(**kw):
        page = int(kw.get("page") or 1)
        per = int(kw.get("per") or 25)
        chunk = rows[(page - 1) * per: page * per]
        return {"rows": chunk, "pages": max(1, -(-len(rows) // per))}
    return fake


SUPRA = "auto-trader cycle failed for SUPRA_USDT: no Min15 candles for SUPRA_USDT"


def test_one_fault_in_two_rooms_is_one_event(monkeypatch):
    """SUPRA failed in #4FC03172 (43 times) and #55D32617 (39) — one fault,
    so one issue listing both rooms, never two."""
    from tradingagents import room_errors as rerr

    monkeypatch.setattr(rerr, "report", _report([
        {"room": "4FC03172", "kind": "cycle_failed", "label": "A check failed",
         "message": SUPRA, "count": 43, "first": 1791260400.0, "last": 1791354060.0},
        {"room": "55D32617", "kind": "cycle_failed", "label": "A check failed",
         "message": SUPRA, "count": 39, "first": 1791259740.0, "last": 1791262620.0},
    ]))
    got = ei.from_rooms()
    assert len(got) == 1
    ev = got[0]
    assert ev["rooms"] == ["4FC03172", "55D32617"]
    assert ev["count"] == 82
    assert ev["first"] == 1791259740.0 and ev["last"] == 1791354060.0
    assert ev["source"] == "room" and ev["kind"] == "cycle_failed"


def test_every_page_of_the_errors_tab_is_read(monkeypatch):
    from tradingagents import room_errors as rerr

    rows = [{"room": "main", "kind": "other_error", "label": "Other error",
             "message": f"thing {chr(65 + i)} broke", "count": 1,
             "first": 1.0, "last": 2.0} for i in range(30)]
    monkeypatch.setattr(rerr, "report", _report(rows))
    assert len(ei.from_rooms()) == 30


def test_a_failed_job_is_an_event(monkeypatch):
    from tradingagents import db_jobs as dj

    monkeypatch.setattr(dj, "FILES", {"collect_v2": {}, "download_v2": {}})
    states = {"collect_v2": {"running": False, "errors": 2,
                             "first_error": "PermissionError: [WinError 5]",
                             "finished": 1791301213},
              "download_v2": {"running": False, "errors": 0, "finished": 1791300000}}
    monkeypatch.setattr(dj, "status", lambda kind: dict(states[kind]))
    got = ei.from_jobs()
    assert [e["kind"] for e in got] == ["collect_v2"]
    assert "PermissionError" in got[0]["message"] and got[0]["last"] == 1791301213


def test_a_running_job_is_not_a_failure_yet(monkeypatch):
    from tradingagents import db_jobs as dj

    monkeypatch.setattr(dj, "FILES", {"collect_v2": {}})
    monkeypatch.setattr(dj, "status", lambda kind: {"running": True, "errors": 3,
                                                    "first_error": "x"})
    assert ei.from_jobs() == []


TRACE = """INFO:     127.0.0.1:5000 - "GET /api/health HTTP/1.1" 200 OK
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  File "G:\\analyzer-x\\.venv\\Lib\\site-packages\\starlette\\routing.py", line 73, in app
    response = await f(request)
  File "G:\\analyzer-x\\tradingagents\\api.py", line 571, in strategies
    return ri.query(**kw)
  File "G:\\analyzer-x\\tradingagents\\rows_index.py", line 4462, in query
    total, got = _missing_ok(_read, (0, []))
sqlite3.OperationalError: database is locked
INFO:     127.0.0.1:5001 - "GET /api/jobs HTTP/1.1" 200 OK
"""


def test_a_crash_inside_the_site_is_an_event(tmp_path, monkeypatch):
    log = tmp_path / "api.log"
    log.write_text(TRACE, encoding="utf-8")
    monkeypatch.setattr(ei, "SITE_LOG", log)
    monkeypatch.setattr(ei, "_SITE_TAIL", {})
    got = ei.from_site_log(now=1791370000.0)
    assert len(got) == 1
    ev = got[0]
    assert ev["source"] == "site"
    assert "sqlite3.OperationalError: database is locked" in ev["message"]
    assert "rows_index.py" in ev["message"] and "query" in ev["message"]
    # read once: the same bytes are not an event twice
    assert ei.from_site_log(now=1791370100.0) == []


def test_the_fingerprint_ignores_the_room_and_the_numbers():
    a = {"source": "room", "kind": "no_price",
         "key": "", "message": "GPNSTOCK_USDT: no live price (after 3 attempts) at Oct 07, 2026 1:19am"}
    b = dict(a, message="GPNSTOCK_USDT: no live price (after 5 attempts) at Oct 08, 2026 2:20am")
    c = dict(a, message="VUG_USDT: no live price (after 3 attempts) at Oct 07, 2026 1:19am")
    assert ei.fingerprint(a) == ei.fingerprint(b)
    assert ei.fingerprint(a) != ei.fingerprint(c)


# ------------------------------------------------------------ the scrubber

@pytest.mark.parametrize("line", [
    "GET /api/v1/private/account?timestamp=1&signature=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    'headers={"ApiKey": "mx0vglAbCdEfGhIjKl", "Request-Time": "1"}',
    "Authorization: Bearer ghp_1234567890abcdefABCDEF",
    "token=0123456789abcdef0123456789abcdef",
    'secret: "s3cr3t-value-here"',
])
def test_every_secret_form_is_removed(line):
    out = ei.scrub(line)
    assert "[removed]" in out
    for secret in ("9f86d081884c7d659a2feaa0", "mx0vglAbCdEfGhIjKl",
                   "ghp_1234567890abcdef", "0123456789abcdef0123",
                   "s3cr3t-value-here"):
        assert secret not in out


def test_the_configured_keys_are_removed_wherever_they_appear(tmp_path, monkeypatch):
    monkeypatch.setenv("MEXC_API_KEY", "mx0KEYVALUE1234")
    monkeypatch.setenv("MEXC_API_SECRET", "SECRETVALUE5678abcd")
    monkeypatch.setattr(ei, "HOME", tmp_path)
    (tmp_path / "ingest_token").write_text("tokvalue-0000-1111\n", encoding="utf-8")
    out = ei.scrub("a mx0KEYVALUE1234 b SECRETVALUE5678abcd c tokvalue-0000-1111 d")
    assert out == "a [removed] b [removed] c [removed] d"


def test_ordinary_words_are_kept():
    line = "LIQUIDITY GATE: refusing stoch14_15m on AONSTOCK_USDT - the order book could not be read"
    assert ei.scrub(line) == line
