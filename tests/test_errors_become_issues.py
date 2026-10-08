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


def test_the_fingerprint_ignores_the_room_the_numbers_and_the_coin():
    """One candle outage across the 64 armed coins is ONE fault, not 64
    issues and 64 fixer runs (8 days of the 8-a-day budget) — the final
    review's I9. The kind still separates faults."""
    a = {"source": "room", "kind": "no_price",
         "key": "", "message": "GPNSTOCK_USDT: no live price (after 3 attempts) at Oct 07, 2026 1:19am"}
    b = dict(a, message="GPNSTOCK_USDT: no live price (after 5 attempts) at Oct 08, 2026 2:20am")
    c = dict(a, message="VUG_USDT: no live price (after 3 attempts) at Oct 07, 2026 1:19am")
    d = dict(a, kind="cycle_failed")
    assert ei.fingerprint(a) == ei.fingerprint(b) == ei.fingerprint(c)
    assert ei.fingerprint(a) != ei.fingerprint(d)


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
    def __init__(self, fail=False, existing=None, fail_on=None):
        self.calls: list = []
        self.fail = fail
        self.next = 101
        self.existing = existing or []      # what `gh issue list --search` finds
        self.fail_on = fail_on              # (verb, nth) -> fail that call once

    def __call__(self, args, input_text=None):
        self.calls.append((list(args), input_text))
        if self.fail:
            raise ei.GhFailed("gh: could not resolve host api.github.com")
        if self.fail_on and args[:2] == ["issue", self.fail_on[0]]:
            n = sum(1 for c in self.calls if c[0][:2] == ["issue", self.fail_on[0]])
            if n == self.fail_on[1]:
                raise ei.GhFailed(f"gh: {self.fail_on[0]} refused")
        if args[:2] == ["issue", "list"]:
            return json.dumps(self.existing)
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
                        lambda now, failed=None: [dict(e, rooms=list(e["rooms"])) for e in events])
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
    assert ev_file["message"] == SUPRA
    # nothing in it points at the public issue, which anyone can comment on
    # (final review, I7)
    assert "issue" not in ev_file and "url" not in ev_file
    assert "issues/" not in json.dumps(ev_file)
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


# ------------------------------------- the final review's fix pass (Oct 07, 2026)

def test_an_issue_is_recorded_the_moment_github_makes_it(filer, monkeypatch):
    """C1: the evidence write raised (a full drive) AFTER GitHub made the
    issue, the tick aborted before saving it, and the next tick filed the
    same fault again — 12 public issues in 24 minutes in the review's run."""
    events, _ = filer
    ei.tick(T0, gh=FakeGh())
    events.append(_ev(SUPRA, last=T0 + 60))
    calls = {"n": 0}

    def full_drive(*a, **k):
        calls["n"] += 1
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(ei, "_write_evidence", full_drive)
    gh = FakeGh()
    ei.tick(T0 + 120, gh=gh)
    ei.tick(T0 + 240, gh=gh)
    assert len(gh.made()) == 1
    fp = ei.fingerprint(events[0])
    assert ei._read()["faults"][fp]["issue"] == 101


def test_an_issue_github_made_but_never_answered_is_adopted_not_doubled(filer):
    """C1, second door: GitHub made the issue but gh timed out. The next try
    finds it by its fault id instead of making another."""
    events, _ = filer
    ei.tick(T0, gh=FakeGh())
    events.append(_ev(SUPRA, last=T0 + 60))
    fp = ei.fingerprint(events[0])
    gh = FakeGh(existing=[{"number": 88, "url": f"https://github.com/{ei.GH_REPO}/issues/88"}])
    ei.tick(T0 + 120, gh=gh)
    assert gh.made() == []
    assert any(fp in " ".join(c[0]) for c in gh.did("list"))
    assert ei._read()["faults"][fp]["issue"] == 88


def test_the_flood_summary_is_filed_once_even_if_its_comment_fails(filer):
    """I1: flood_at was set only after the comment, so a refused comment
    filed a new flood issue every tick (5 in 10 minutes)."""
    events, _ = filer
    ei.tick(T0, gh=FakeGh())
    for i in range(14):
        events.append(_ev(f"fault number {chr(65 + i)} broke", last=T0 + 60))
    ei.tick(T0 + 120, gh=FakeGh(fail_on=("comment", 1)))
    gh = FakeGh()
    ei.tick(T0 + 240, gh=gh)
    titles = [c[0][c[0].index("--title") + 1] for c in gh.made()]
    assert not any("error flood" in t for t in titles)


def test_a_site_crash_github_refused_is_still_filed_later(filer):
    """I2: a site crash is read ONCE (the log tail moves on), so a refused
    create lost it for good."""
    events, _ = filer
    ei.tick(T0, gh=FakeGh())
    crash = {"source": "site", "kind": "site_crash", "label": "The site itself failed",
             "message": "KeyError: 'at' (in forecast_v2_api.py:summary)", "key": "",
             "rooms": [], "count": 1, "first": T0 + 60, "last": T0 + 60}
    events.append(crash)
    ei.tick(T0 + 120, gh=FakeGh(fail=True))
    events.clear()                       # the tail has moved past it
    gh = FakeGh()
    ei.tick(T0 + 240, gh=gh)
    assert len(gh.made()) == 1 and "KeyError" in gh.made()[0][0][gh.made()[0][0].index("--title") + 1]


def test_a_verdict_is_posted_once_however_often_github_refuses_a_step(filer):
    """I3: a refused label made every retry post "Real fault, fixed in ..."
    again (4 times in 4 ticks in the review's run)."""
    events, _ = filer
    ei.tick(T0, gh=FakeGh())
    events.append(_ev(SUPRA, last=T0 + 60))
    ei.tick(T0 + 120, gh=FakeGh())
    fp = ei.fingerprint(events[0])
    with pytest.raises(ei.GhFailed):
        ei.set_verdict(fp, "fixed", commit="abc1234", summary="x", now=T0 + 200,
                       gh=FakeGh(fail_on=("edit", 1)))
    ok = FakeGh()
    ei.set_verdict(fp, "fixed", commit="abc1234", summary="x", now=T0 + 300, gh=ok)
    assert sum("Real fault" in (c[1] or "") for c in ok.did("comment")) == 1
    assert ei._read()["faults"][fp]["state"] == "fixed"


def test_no_baseline_is_written_while_a_source_cannot_be_read(filer, monkeypatch):
    """I4: rooms unreadable on the first tick made a baseline without them,
    and tick 2 filed every room fault as new (10 issues and a flood)."""
    events, _ = filer
    events.append(_ev("old fault", last=T0 - 3600))
    first = {"done": False}

    def collect(now, failed=None):
        if not first["done"]:
            first["done"] = True
            if failed is not None:
                failed.append("from_rooms")
            return []
        return [dict(e, rooms=list(e["rooms"])) for e in events]
    monkeypatch.setattr(ei, "collect", collect)
    ei.tick(T0, gh=FakeGh())
    assert not ei._read().get("baseline")
    gh = FakeGh()
    ei.tick(T0 + 120, gh=gh)
    assert ei._read().get("baseline") == T0 + 120 and gh.made() == []


def test_a_not_a_fault_that_keeps_happening_is_checked_again(filer):
    """I9: one not-a-fault verdict must not silence a fault for ever: 20 more
    times after the verdict and it is reopened and queued for another check."""
    events, _ = filer
    ei.tick(T0, gh=FakeGh())
    events.append(_ev("the runner was started again", kind="restart", last=T0 + 60, count=3))
    ei.tick(T0 + 120, gh=FakeGh())
    fp = ei.fingerprint(events[0])
    ei.set_verdict(fp, "not_a_fault", summary="deploy restarts", now=T0 + 200, gh=FakeGh())
    events[0] = _ev("the runner was started again", kind="restart", last=T0 + 4000, count=10)
    gh = FakeGh()
    ei.tick(T0 + 4100, gh=gh)
    assert gh.did("reopen") == []
    events[0] = _ev("the runner was started again", kind="restart", last=T0 + 9000,
                    count=3 + ei.NOT_A_FAULT_RECHECK)
    gh = FakeGh()
    ei.tick(T0 + 9100, gh=gh)
    assert gh.did("reopen") and ei._read()["faults"][fp]["state"] == "queued"


def test_an_unreadable_state_file_is_never_overwritten(filer):
    """M1: a state file Windows would not let us read was treated as a first
    run — a new baseline and every issue number dropped."""
    events, _ = filer
    ei.STATE.parent.mkdir(parents=True, exist_ok=True)
    ei.STATE.write_text("{ half a file", encoding="utf-8")
    events.append(_ev(SUPRA, last=T0 + 60))
    got = ei.tick(T0, gh=FakeGh())
    assert got["failed"] == 1
    assert ei.STATE.read_text(encoding="utf-8") == "{ half a file"


def test_the_stored_mexc_keys_are_removed_too(tmp_path, monkeypatch):
    """C2: on this PC the keys live in ~/.tradingagents/mexc_credentials.json,
    not in .env — and reach the site's environment only after a route loads
    them."""
    from tradingagents.dataflows import mexc_credentials as cred

    monkeypatch.delenv("MEXC_API_KEY", raising=False)
    monkeypatch.delenv("MEXC_API_SECRET", raising=False)
    monkeypatch.setattr(cred, "_read", lambda: {"api_key": "mx0STOREDKEY99", "api_secret": "STOREDSECRET1234"})
    out = ei.scrub('{\\"api_key\\": \\"mx0STOREDKEY99\\", x STOREDSECRET1234}')
    assert "mx0STOREDKEY99" not in out and "STOREDSECRET1234" not in out


@pytest.mark.parametrize("line,secret", [
    ("GH_TOKEN=gho_16C7e42F292c6912E7710c838347Ae178B4a", "gho_16C7e42F292c6912E7710c838347Ae178B4a"),
    ("MEXC_API_SECRET=0123abcd4567efgh8901", "0123abcd4567efgh8901"),
    ("access_token=at-1234567890abcdef", "at-1234567890abcdef"),
    ("refresh_token=rt-1234567890abcdef", "rt-1234567890abcdef"),
    ("secret_key=sk-1234567890abcdef", "sk-1234567890abcdef"),
    ('api_secret: "as-1234567890abcdef"', "as-1234567890abcdef"),
    ("apiSecret=cs-1234567890abcdef", "cs-1234567890abcdef"),
    ("sent Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig1234567890", "eyJhbGciOiJIUzI1NiJ9"),
    ("Authorization: token ghp_1234567890abcdefghijABCDEFGHIJ", "ghp_1234567890abcdefghij"),
    ("Authorization: Basic dXNlcjpwYXNzd29yZDEyMw==", "dXNlcjpwYXNzd29yZDEyMw"),
    ('{\\"api_key\\": \\"mx0vglJSONESCAPED1\\"}', "mx0vglJSONESCAPED1"),
])
def test_the_scrubber_catches_the_forms_the_review_found(line, secret):
    """I10: each of these passed through untouched."""
    out = ei.scrub(line)
    assert secret not in out, out


def test_a_self_retrying_supervisor_line_is_not_a_fault(tmp_path, monkeypatch):
    """M3: "could not be swapped in yet ... next check tries again" is the
    supervisor waiting, printed every 30 s; [handoff] failures are real."""
    log = tmp_path / "api.log"
    log.write_text(
        "[supervisor] C:\\rows.db: a verified rebuild could not be swapped in yet "
        "(PermissionError: x) — next check tries again\n"
        "[handoff] failed: CloudError('gh timed out')\n", encoding="utf-8")
    monkeypatch.setattr(ei, "SITE_LOG", log)
    monkeypatch.setattr(ei, "_SITE_TAIL", {})
    got = ei.from_site_log(now=T0)
    assert [e["message"][:9] for e in got] == ["[handoff]"]


def test_the_filers_own_status_line_is_never_an_error(tmp_path, monkeypatch):
    """Found on the first live hour (Oct 07, 2026 2:38pm): issue #2 was the
    filer filing its OWN line, "[error-issues] {'filed': 1, ..., 'failed': 0}"
    — a count of zero failures read as a failure. Neither a quoted 'failed'
    key nor any [error-issues] line is a fault; a real "failed:" still is."""
    log = tmp_path / "api.log"
    log.write_text(
        "[error-issues] {'filed': 1, 'commented': 0, 'reopened': 0, 'waiting': 0, 'failed': 0}\n"
        "[error-issues] fixer: {'applied': [], 'started': 'b414f6fd6231'}\n"
        "[error-issues] filing failed: GhFailed('gh: could not resolve host')\n"
        "[forecast] chain {'done': 3, 'failed': 0}\n"
        "[cloud-autopilot] collect failed: CloudError('gh timed out')\n", encoding="utf-8")
    monkeypatch.setattr(ei, "SITE_LOG", log)
    monkeypatch.setattr(ei, "_SITE_TAIL", {})
    got = ei.from_site_log(now=T0)
    assert [e["message"] for e in got] == ["[cloud-autopilot] collect failed: CloudError('gh timed out')"]


def test_a_count_of_zero_failures_is_never_an_error(tmp_path, monkeypatch):
    """Issue 574d9983698f (Oct 07, 2026 5:16pm): "[rolling30] rebuilt 69
    row(s), 0 could not be: []" — a clean pass — was filed as "The site's
    rolling30 failed". RCA-2026-10-07-K stopped a QUOTED 'failed': 0; the
    same zero written as a word got through. A real count still files."""
    log = tmp_path / "api.log"
    log.write_text(
        "[rolling30] rebuilt 69 row(s), 0 could not be: []\n"
        "[daily-update] 12 done, 0 failed\n"
        "[rolling30] rebuilt 3 row(s), 2 could not be: [('#AB12CD34', 'no candles')]\n"
        "[forecast] 10 failed\n", encoding="utf-8")
    monkeypatch.setattr(ei, "SITE_LOG", log)
    monkeypatch.setattr(ei, "_SITE_TAIL", {})
    got = ei.from_site_log(now=T0)
    assert [e["message"][:14] for e in got] == ["[rolling30] re", "[forecast] 10 "]


def test_a_web_request_line_glued_onto_a_fault_is_the_same_fault(tmp_path, monkeypatch):
    """Issue 7812369f14f9 (Oct 07, 2026 7:26pm): `print()` writes its text and
    its newline in two writes, so a web request logged by another thread in
    between landed on the SAME line — "...no answer in 180s — killedINFO:
    127.0.0.1:57321 - "GET /api/trade/log?n=200 ..." 200 OK" — and the filer
    opened issue #8 for a fault already filed and checked as issue #7. The
    glued request is cut off, so both lines are ONE fault with one id."""
    clean = "[cloud] could not fetch sweep-progress: git fetch: no answer in 180s — killed"
    log = tmp_path / "api.log"
    log.write_text(
        clean + "\n"
        + clean + 'INFO:     127.0.0.1:57321 - "GET /api/trade/log?n=200 HTTP/1.1" 200 OK\n'
        "\n"
        "[handoff] failed: CloudError('gh timed out')WARNING:  Invalid HTTP request received.\n",
        encoding="utf-8")
    monkeypatch.setattr(ei, "SITE_LOG", log)
    monkeypatch.setattr(ei, "_SITE_TAIL", {})
    got = ei.from_site_log(now=T0)
    assert [(e["message"], e["count"]) for e in got] == [
        (clean, 2), ("[handoff] failed: CloudError('gh timed out')", 1)]
    assert ei.fingerprint(got[0]) == "936f76c8c751"      # issue #7's own id


def test_issues_are_filed_as_the_projects_owner(monkeypatch):
    """On this PC gh's ACTIVE account is the fork's (jeremydvera, checked
    Oct 07, 2026); the issues belong to jeremydevera/analyzer-x, so the filer
    asks gh for the owner's own token and acts as them — and falls back to
    the active account when that cannot be read."""
    import subprocess as sp

    asked: list = []

    class Out:
        def __init__(self, code, text):
            self.returncode, self.stdout = code, text

    monkeypatch.setattr(ei, "_OWNER_TOKEN", {})
    monkeypatch.setattr(sp, "run", lambda cmd, **kw: asked.append(cmd) or Out(0, "gho_owner\n"))
    env = ei._gh_env()
    assert env["GH_TOKEN"] == "gho_owner"
    assert asked[0][-3:] == ["token", "-u", "jeremydevera"]
    monkeypatch.setattr(ei, "_OWNER_TOKEN", {})
    monkeypatch.setattr(sp, "run", lambda cmd, **kw: Out(1, ""))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert "GH_TOKEN" not in ei._gh_env()


def test_github_is_never_called_from_a_test():
    """Like the live door (`live_ingest.ensure`), the filer refuses to touch
    the real GitHub while a test runs — a public project's issues are not a
    scratchpad."""
    with pytest.raises(ei.GhFailed, match="test"):
        ei._gh(["--version"])


def test_a_fixer_run_is_never_started_from_a_test(tmp_path, monkeypatch):
    from tradingagents import error_fixer as fx

    monkeypatch.setattr(ei, "HOME", tmp_path)
    monkeypatch.setattr(ei, "STATE", tmp_path / "error_issues.json")
    monkeypatch.setattr(ei, "FIXER_DIR", tmp_path / "fixer")
    monkeypatch.setattr(ei, "_LABELS_MADE", set(ei.LABELS))
    st = {"baseline": T0, "faults": {"aaaa00000001": {
        "state": "queued", "issue": 101, "filed_at": T0, "label": "x", "url": "u"}}}
    ei._write(st)
    started: list = []
    monkeypatch.setattr(fx.subprocess, "Popen", lambda *a, **k: started.append(a))
    got = fx.tick(T0 + 10, gh=FakeGh())
    assert started == [] and "test" in got.get("refused", "")


def test_the_site_runs_the_filer_and_the_fixer_on_their_own_thread():
    """Never inside the supervisor loop: a GitHub call or a fixer start must
    not delay the loop that restarts dead runners."""
    src = Path("tradingagents/api.py").read_text(encoding="utf-8")
    at = src.index("def _error_issues_loop()")
    loop = src[at:src.index("_th.Thread(target=_error_issues_loop", at)]
    assert "_ei.tick()" in loop and "_ef.tick()" in loop
    assert 'name="error-issues"' in src
    sup = src[src.index("def _watch() -> None:"):src.index('name="job-supervisor"')]
    assert "error_issues" not in sup and "error_fixer" not in sup


def test_each_row_on_the_errors_tab_names_its_issue(tmp_path, monkeypatch):
    from tradingagents import api, room_errors as rerr

    monkeypatch.setattr(ei, "STATE", tmp_path / "error_issues.json")
    row = {"room": "4FC03172", "kind": "cycle_failed", "label": "A check failed",
           "message": SUPRA, "count": 43, "first": 1.0, "last": 2.0}
    monkeypatch.setattr(rerr, "report", lambda **kw: {"rows": [dict(row)], "pages": 1})
    fp = ei.fingerprint({"source": "room", "kind": "cycle_failed", "message": SUPRA})
    ei._write({"baseline": 1.0, "faults": {fp: {
        "state": "fixed", "issue": 77, "url": "https://github.com/x/issues/77",
        "commit": "abc1234"}}})
    got = api.room_errors_route(room="", kind="", hours=0, page=1)
    assert got["rows"][0]["issue"] == {"number": 77, "url": "https://github.com/x/issues/77",
                                       "state": "fixed", "commit": "abc1234"}


def test_the_tab_says_each_issues_state_in_words():
    """The badge's words come from the row's state — never a literal that can
    say "fixed" over an issue nobody has checked."""
    tsx = Path("webapp/src/components/errors/DeployedTabsErrors.tsx").read_text(encoding="utf-8")
    for state in ("queued", "checking", "fixed", "not_a_fault", "needs_you"):
        assert f"{state}:" in tsx, state
    assert "g.issue" in tsx and "g.issue.url" in tsx
    ts = Path("webapp/src/lib/api.ts").read_text(encoding="utf-8")
    assert "issue?:" in ts


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
