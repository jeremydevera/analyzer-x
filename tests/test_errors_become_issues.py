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


# ------------------------------------------------------- the GitHub side
# One timeline: T0 is the first tick (the baseline). Every fake event below
# is placed on it, and `gh` is a recorder — no network, no real issue.

T0 = 1791380000.0   # Oct 07, 2026 10:13am


class FakeGh:
    def __init__(self, fail=False):
        self.calls: list = []
        self.fail = fail
        self.next = 101

    def __call__(self, args, input_text=None):
        self.calls.append((list(args), input_text))
        if self.fail:
            raise ei.GhFailed("gh: could not resolve host api.github.com")
        if args[:2] == ["issue", "create"]:
            n, self.next = self.next, self.next + 1
            return f"https://github.com/{ei.GH_REPO}/issues/{n}\n"
        return ""

    def made(self):
        return [c for c in self.calls if c[0][:2] == ["issue", "create"]]

    def did(self, verb):
        return [c for c in self.calls if c[0][:2] == ["issue", verb]]


@pytest.fixture
def filer(tmp_path, monkeypatch):
    """The filer on a sandboxed home, with the three sources replaced by a
    list the test controls and the bell recorded."""
    monkeypatch.setattr(ei, "HOME", tmp_path)
    monkeypatch.setattr(ei, "STATE", tmp_path / "error_issues.json")
    monkeypatch.setattr(ei, "FIXER_DIR", tmp_path / "fixer")
    monkeypatch.setattr(ei, "_LABELS_MADE", set())
    events: list = []
    monkeypatch.setattr(ei, "collect",
                        lambda now: [dict(e, rooms=list(e["rooms"])) for e in events])
    bells: list = []
    from tradingagents import notifications

    monkeypatch.setattr(notifications, "record",
                        lambda kind, title, **kw: bells.append((kind, title, kw)) or 1)
    return events, bells


def _ev(msg, *, last, room="4FC03172", kind="cycle_failed", count=1, first=None):
    return {"source": "room", "kind": kind, "label": "A check failed", "message": msg,
            "key": "", "rooms": [room], "count": count,
            "first": first if first is not None else last, "last": last}


def test_the_first_tick_files_nothing_and_remembers_what_it_saw(filer):
    """The 34 groups checked by hand on Oct 07, 2026 are not filed again."""
    events, _ = filer
    events.append(_ev("old fault", last=T0 - 3600))
    gh = FakeGh()
    ei.tick(T0, gh=gh)
    assert gh.made() == []
    st = ei._read()
    assert st["baseline"] == T0
    assert list(st["faults"].values())[0]["state"] == "baseline"


def test_a_new_fault_files_one_issue_and_queues_it(filer):
    events, bells = filer
    ei.tick(T0, gh=FakeGh())
    events.append(_ev(SUPRA, last=T0 + 60, count=43))
    gh = FakeGh()
    ei.tick(T0 + 120, gh=gh)
    made = gh.made()
    assert len(made) == 1
    args, body = made[0]
    assert args[args.index("--label") + 1] == "auto-error"
    assert args[args.index("-R") + 1] == ei.GH_REPO
    assert "SUPRA_USDT" in args[args.index("--title") + 1]
    assert "#4FC03172" in body and "43" in body
    fp = ei.fingerprint(events[0])
    rec = ei._read()["faults"][fp]
    assert rec["issue"] == 101 and rec["state"] == "queued"
    ev_file = json.loads((ei.FIXER_DIR / f"{fp}.json").read_text(encoding="utf-8"))
    assert ev_file["issue"] == 101 and ev_file["message"] == SUPRA
    assert bells and "#101" in bells[-1][1]


def test_a_repeat_comments_at_most_once_an_hour(filer):
    events, _ = filer
    ei.tick(T0, gh=FakeGh())
    events.append(_ev(SUPRA, last=T0 + 60))
    ei.tick(T0 + 120, gh=FakeGh())
    events[0] = _ev(SUPRA, last=T0 + 600, count=5)
    gh = FakeGh()
    ei.tick(T0 + 700, gh=gh)
    assert gh.made() == [] and gh.did("comment") == []
    events[0] = _ev(SUPRA, last=T0 + 4000, count=9)
    gh = FakeGh()
    ei.tick(T0 + 4100, gh=gh)
    assert gh.made() == []
    assert len(gh.did("comment")) == 1
    assert "9" in gh.did("comment")[0][1]


def test_the_was_count_is_what_the_issue_last_said(filer):
    """A repeat that did not post a comment must not move "was N": the next
    comment compares with what the issue last SAID, 1 — not the unposted 5."""
    events, _ = filer
    ei.tick(T0, gh=FakeGh())
    events.append(_ev(SUPRA, last=T0 + 60, count=1))
    ei.tick(T0 + 120, gh=FakeGh())
    events[0] = _ev(SUPRA, last=T0 + 600, count=5)
    ei.tick(T0 + 700, gh=FakeGh())
    events[0] = _ev(SUPRA, last=T0 + 4000, count=9)
    gh = FakeGh()
    ei.tick(T0 + 4100, gh=gh)
    assert "(was 1)" in gh.did("comment")[0][1]


def test_a_reopen_github_says_already_happened_is_not_a_failure(filer):
    events, _ = filer
    ei.tick(T0, gh=FakeGh())
    events.append(_ev(SUPRA, last=T0 + 60))
    ei.tick(T0 + 120, gh=FakeGh())
    fp = ei.fingerprint(events[0])
    ei.set_verdict(fp, "fixed", commit="abc1234", summary="x", now=T0 + 200, gh=FakeGh())

    class AlreadyOpen(FakeGh):
        def __call__(self, args, input_text=None):
            if args[:2] == ["issue", "reopen"]:
                self.calls.append((list(args), input_text))
                raise ei.GhFailed("could not reopen issue #101: issue is already open")
            return super().__call__(args, input_text)

    events[0] = _ev(SUPRA, last=T0 + 9000)
    got = ei.tick(T0 + 9100, gh=AlreadyOpen())
    assert got["failed"] == 0
    assert ei._read()["faults"][fp]["state"] == "queued"


def test_the_same_fault_in_a_second_room_is_the_same_issue(filer):
    events, _ = filer
    ei.tick(T0, gh=FakeGh())
    events.append(_ev(SUPRA, last=T0 + 60))
    ei.tick(T0 + 120, gh=FakeGh())
    events[0] = dict(_ev(SUPRA, last=T0 + 5000), rooms=["4FC03172", "55D32617"])
    gh = FakeGh()
    ei.tick(T0 + 5100, gh=gh)
    assert gh.made() == []
    assert "#55D32617" in gh.did("comment")[0][1]


def test_a_fixed_fault_that_comes_back_is_reopened_once_then_needs_you(filer):
    events, bells = filer
    ei.tick(T0, gh=FakeGh())
    events.append(_ev(SUPRA, last=T0 + 60))
    ei.tick(T0 + 120, gh=FakeGh())
    fp = ei.fingerprint(events[0])
    ei.set_verdict(fp, "fixed", commit="abc1234", summary="switch-on asks MEXC",
                   now=T0 + 200, gh=FakeGh())
    events[0] = _ev(SUPRA, last=T0 + 9000)
    gh = FakeGh()
    ei.tick(T0 + 9100, gh=gh)
    assert gh.did("reopen") and ei._read()["faults"][fp]["state"] == "queued"
    assert any(c[0][-1] == "came-back" for c in gh.did("edit"))
    ei.set_verdict(fp, "fixed", commit="def5678", summary="again", now=T0 + 9200, gh=FakeGh())
    events[0] = _ev(SUPRA, last=T0 + 20000)
    gh = FakeGh()
    ei.tick(T0 + 20100, gh=gh)
    assert ei._read()["faults"][fp]["state"] == "needs_you"
    assert any(c[0][-1] == "needs-you" for c in gh.did("edit"))
    assert any("came back" in b[1] for b in bells)


def test_a_not_a_fault_issue_gets_one_comment_a_day(filer):
    events, _ = filer
    ei.tick(T0, gh=FakeGh())
    events.append(_ev("no price check for 54 minutes", kind="quiet", last=T0 + 60))
    ei.tick(T0 + 120, gh=FakeGh())
    fp = ei.fingerprint(events[0])
    ei.set_verdict(fp, "not_a_fault", summary="the PC lost power", now=T0 + 200, gh=FakeGh())
    events[0] = _ev("no price check for 54 minutes", kind="quiet", last=T0 + 4000)
    gh = FakeGh()
    ei.tick(T0 + 4100, gh=gh)
    assert gh.did("comment") == [] and gh.did("reopen") == []
    events[0] = _ev("no price check for 54 minutes", kind="quiet", last=T0 + 90000)
    gh = FakeGh()
    ei.tick(T0 + 90100, gh=gh)
    assert len(gh.did("comment")) == 1 and gh.did("reopen") == []
    assert ei._read()["faults"][fp]["state"] == "not_a_fault"


def test_a_flood_files_ten_then_one_summary_and_waits(filer):
    """A broken release could throw 500 different errors in an hour: ten
    issues, one summary, the rest filed the next hour — never 500 issues."""
    events, _ = filer
    ei.tick(T0, gh=FakeGh())
    for i in range(14):
        events.append(_ev(f"fault number {chr(65 + i)} broke", last=T0 + 60))
    gh = FakeGh()
    ei.tick(T0 + 120, gh=gh)
    titles = [c[0][c[0].index("--title") + 1] for c in gh.made()]
    assert len(titles) == ei.FLOOD_PER_HOUR + 1
    assert sum("error flood" in t for t in titles) == 1
    waiting = [r for r in ei._read()["faults"].values() if r["state"] == "waiting"]
    assert len(waiting) == 4
    gh = FakeGh()
    ei.tick(T0 + 120 + 3700, gh=gh)
    assert len(gh.made()) == 4


def test_a_github_failure_is_retried_and_never_raised(filer):
    events, _ = filer
    ei.tick(T0, gh=FakeGh())
    events.append(_ev(SUPRA, last=T0 + 60))
    got = ei.tick(T0 + 120, gh=FakeGh(fail=True))
    assert got["failed"] >= 1
    fp = ei.fingerprint(events[0])
    assert ei._read()["faults"].get(fp, {}).get("issue") is None
    gh = FakeGh()
    ei.tick(T0 + 240, gh=gh)
    assert len(gh.made()) == 1


def test_a_baseline_fault_that_happens_again_is_filed(filer):
    events, _ = filer
    events.append(_ev(SUPRA, last=T0 - 600))
    ei.tick(T0, gh=FakeGh())
    events[0] = _ev(SUPRA, last=T0 + 300)
    gh = FakeGh()
    ei.tick(T0 + 400, gh=gh)
    assert len(gh.made()) == 1


def test_nothing_posted_carries_a_secret(filer, monkeypatch):
    events, _ = filer
    monkeypatch.setenv("MEXC_API_KEY", "mx0KEYVALUE1234")
    ei.tick(T0, gh=FakeGh())
    events.append(_ev("signed call failed: ApiKey=mx0KEYVALUE1234 signature=abcdef0123456789",
                      last=T0 + 60))
    gh = FakeGh()
    ei.tick(T0 + 120, gh=gh)
    posted = json.dumps(gh.calls)
    assert "mx0KEYVALUE1234" not in posted and "abcdef0123456789" not in posted
