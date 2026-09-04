"""A running process on OLD CODE must say so, on the screen.

Operator, Sep 04, 2026: *"SO WHAT'S NOT UPDATED?"* then *"I DONT WANT THIS BUG
FIX THIS"*.

What actually happened, from this machine's own process table and git log:

1. Sep 03  3:30pm — the backtest job started (pid 22032).
2. Sep 04 11:02pm — `feat(sweep): the worker window follows memory` landed. The
   running job could not use it: a ProcessPoolExecutor cannot be resized, so it
   stayed on 3 of 11 cores for 32 hours while nine cores idled.
3. Sep 04 11:04am — the runner started (pid 9392).
4. Sep 04 11:02pm — `fix(risk): the loss cap switches LIVE off — it used to
   kill the runner and the demo with it` landed, TWO MINUTES after the runner
   had started. The live runner went on holding the version that writes the
   KILL file and exits, taking the paper book down with it.
5. Sep 04 11:14pm — the runner was restarted and picked the fix up. On THIS
   machine the cap had never fired (0 real-money rows in the ledger, no
   `live_disarmed` row, no KILL file), so nothing was lost — but the only way
   anyone learned any of this was comparing process start times to `git log`
   BY HAND.

That is the bug: a process silently keeps the code it started with, and
nothing on any screen says so. `process_code_age` names it.
"""
import time

from tradingagents import staleness as st


def test_a_process_started_before_the_last_commit_is_stale():
    got = st.process_code_age(started=1_000, head_committed=2_000,
                              commits_since=14)
    assert got["stale"] is True
    assert got["commits_behind"] == 14
    assert "14 commit" in got["why"], got["why"]


def test_a_process_started_after_the_last_commit_is_current():
    got = st.process_code_age(started=3_000, head_committed=2_000,
                              commits_since=0)
    assert got["stale"] is False
    assert got["commits_behind"] == 0
    assert got["why"] == ""


def test_a_process_that_is_not_running_is_neither(monkeypatch):
    got = st.process_code_age(started=None, head_committed=2_000,
                              commits_since=3)
    assert got["stale"] is False, "nothing is running, so nothing is stale"
    assert got["running"] is False


def test_it_never_guesses_when_git_will_not_answer():
    """Unknown must read as unknown. A silent False here is exactly how a
    32-hour stale job looked healthy."""
    got = st.process_code_age(started=1_000, head_committed=None,
                              commits_since=None)
    assert got["stale"] is None
    assert "could not" in got["why"].lower() or "unknown" in got["why"].lower()


def test_every_long_running_process_is_checked():
    import inspect

    src = inspect.getsource(st.report)
    for kind in ("backtest", "download", "btupdate", "runner", "api"):
        assert kind in src, kind


def test_the_report_names_what_is_stale_not_just_a_count(monkeypatch):
    monkeypatch.setattr(st, "head_commit", lambda: {
        "sha": "abc1234", "committed": 2_000, "when": "Sep 04, 2026 11:02pm"})
    monkeypatch.setattr(st, "commits_after", lambda ts: 14)
    monkeypatch.setattr(st, "_process_starts", lambda: {
        "backtest": 1_000, "runner": 3_000, "download": None,
        "btupdate": None, "api": 3_000})
    got = st.report(force=True)
    assert got["stale_count"] == 1
    names = [p["kind"] for p in got["processes"] if p["stale"]]
    assert names == ["backtest"], got["processes"]
    # NAMED, never "1 process is stale" — the operator had to ask which
    assert "backtest" in got["summary"]
    assert "14" in got["summary"]


def test_a_current_machine_says_so_plainly(monkeypatch):
    monkeypatch.setattr(st, "head_commit", lambda: {
        "sha": "abc1234", "committed": 1_000, "when": "Sep 04, 2026 11:02pm"})
    monkeypatch.setattr(st, "commits_after", lambda ts: 0)
    monkeypatch.setattr(st, "_process_starts", lambda: {
        "backtest": 2_000, "runner": 2_000, "download": None,
        "btupdate": None, "api": 2_000})
    got = st.report(force=True)
    assert got["stale_count"] == 0
    assert "up to date" in got["summary"].lower()


def test_the_start_times_are_real_on_this_machine():
    """Not a mock: whatever is running here must report a plausible start.

    `Get-Date -UFormat %s` was the first attempt and it reads a LOCAL DateTime
    as UTC: every stamp came back 8 hours in the FUTURE (1788563699 against a
    clock reading 1788534988). A process that started in the future is never
    behind a commit, so the check would have called a stale runner current —
    precisely the failure it exists to catch.
    """
    starts = st._process_starts()
    assert "runner" in starts and "backtest" in starts
    now = time.time()
    for kind, ts in starts.items():
        if ts is not None:
            assert 0 < ts <= now + 5, (kind, ts)


# ------------------------------------------------------------------ on screen
def test_the_screen_names_each_stale_process():
    p = open("webapp/src/components/jobs/StaleCode.tsx", encoding="utf-8").read()
    assert "api.staleness()" in p
    # NAMED, not counted: being told "1 process" is what made the operator ask
    assert "stale.map" in p and "p.commits_behind" in p
    assert "Restart it to pick them up" in p
    # three states: unknown is drawn as unknown, never as healthy
    assert "p.stale === null" in p
    assert "unknown code age" in p
    # and it is SILENT when there is nothing wrong
    assert "if (!d || (!d.stale_count && !d.unknown_count)) return null;" in p


def test_it_is_mounted_where_the_operator_watches_jobs():
    panel = open("webapp/src/components/backtest/JobsPanel.tsx",
                 encoding="utf-8").read()
    assert "<StaleCode />" in panel
