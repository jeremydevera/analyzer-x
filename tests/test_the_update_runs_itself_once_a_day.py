"""UPDATE ALL BACKTESTS on Backtest v2 presses itself once a day.

Operator, `Sep 28, 2026`: *"yes i want github to start once a day / also
there are times where there is power outage when i turn on my pc, you should
detect the last run of update all backtest, if its greater than 24 hrs, you
should automatically run it"*.

One rule serves both: the supervisor's 30 s tick presses the v2 UPDATE when
its last REAL run is 24 hours old. After a power cut, the first tick after the
API comes up is that check.

Things pinned here that would otherwise break quietly:

* a press GitHub refused does NOT reset the clock (it measured nothing);
* a busy SECOND account counts as busy (a press goes to every account);
* a failed try is retried every 30 minutes, never every tick (GitHub's
  secondary limit 403'd this account for hours on Sep 02, 2026);
* it sends what the BUTTON sends with nothing picked, down to the panel's own
  default timeframes;
* it never runs under a test, and the collector still never dispatches.

Every test runs on its own tmp_path, with `db_jobs`, GitHub and the bell
replaced. Nothing here can reach the operator's files or GitHub.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from tradingagents import daily_update as du
from tradingagents import db_jobs as dj

REPO = pathlib.Path(__file__).resolve().parent.parent
NOW = 1_790_700_000.0
H = 3600.0


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A PC with no job running, GitHub idle on two accounts, and a record of
    every start and every bell."""
    monkeypatch.setattr(du, "STATE", tmp_path / "daily_update.json")
    monkeypatch.setattr(dj, "STATE_DIR", tmp_path)
    w = {"started": [], "bells": [], "running": {}, "holder": "",
         "runs": {"a/one": [], "b/two": []}, "start_raises": None}

    def _start(kind, spec):
        if w["start_raises"]:
            raise w["start_raises"]
        w["started"].append((kind, spec))
        return 4242

    monkeypatch.setattr(dj, "start", _start)
    monkeypatch.setattr(dj, "status",
                        lambda kind: {"running": w["running"].get(kind, False)})
    monkeypatch.setattr(dj, "disk_holder", lambda kind: w["holder"])
    from tradingagents import cloud_sweep as cs, notifications as nt

    monkeypatch.setattr(cs, "fleets", lambda *a, **k: list(w["runs"]))
    monkeypatch.setattr(cs, "_runs", lambda slug, limit=5: w["runs"][slug])
    monkeypatch.setattr(nt, "record",
                        lambda *a, **k: (w["bells"].append((a, k)), 1)[1])
    w["plan"] = tmp_path / "db_btupdate_v2.plan.json"
    return w


def _ran(w, when, run=36446487985):
    """The plan file a real press leaves behind (`_write_run_plan`)."""
    w["plan"].write_text(json.dumps({
        "when": when, "cloud_run": run,
        "cloud_url": f"https://github.com/x/y/actions/runs/{run}"}))


# ------------------------------------------------------------ the two halves
def test_a_run_24_hours_old_is_pressed_again(world):
    _ran(world, NOW - 24 * H)
    got = du.consider(now=NOW)
    assert got["started"] is True
    assert [k for k, _ in world["started"]] == ["btupdate_v2"]


def test_after_a_power_cut_the_first_look_presses_it(world):
    """The PC was off for three days; the API comes up and the first tick
    sees a run 72 hours old. No separate start-up path: the same rule."""
    _ran(world, NOW - 72 * H)
    assert du.consider(now=NOW)["started"] is True
    assert "the last run was" in du.status(now=NOW)["why"]


def test_no_run_on_record_at_all_is_pressed(world):
    assert du.consider(now=NOW)["started"] is True
    assert "no earlier run is on record" in du._read()["why"]


def test_a_run_under_24_hours_old_is_left_alone_and_says_when_next(world):
    from tradingagents.positions_view import fmt_when

    _ran(world, NOW - 23 * H)
    got = du.consider(now=NOW)
    assert got["started"] is False and not world["started"]
    assert fmt_when(NOW + 1 * H) in got["why"], (
        "the screen must say WHEN it runs next, in the operator's date format")


# ------------------------------------------------ what it sends is the button
def test_it_sends_what_the_button_sends_with_nothing_picked(world):
    du.consider(now=NOW)
    _kind, spec = world["started"][0]
    assert spec["coins"] == [], "empty means every coin, as on the button"
    assert spec["fresh"] is False, "UPDATE continues, it never starts over"
    assert spec["days"] == dj._sweep_days() == 30
    assert spec["base"] == 5.0


def test_its_timeframes_are_the_panels_own_default():
    """A hand press with nothing changed sends JobsPanel's default `tfs`. If
    that default changes, this has to change with it or the two presses
    measure different things under one button name."""
    src = (REPO / "webapp" / "src" / "components" / "backtest"
           / "JobsPanel.tsx").read_text(encoding="utf-8")
    m = re.search(r'const \[tfs, setTfs\] = useState<string\[\]>\(\[([^\]]*)\]\)',
                  src)
    assert m, "the panel's default timeframes moved"
    panel = tuple(re.findall(r'"([^"]+)"', m.group(1)))
    assert panel == du.DAILY_TFS


# ------------------------------------------------------------- when it waits
def test_switched_off_means_never(world):
    du.set_enabled(False)
    assert du.consider(now=NOW)["started"] is False
    assert not world["started"]
    assert du.status(now=NOW)["enabled"] is False
    du.set_enabled(True)
    assert du.consider(now=NOW)["started"] is True


def test_a_busy_second_account_is_busy(world):
    """`capacity.cloud_free` asks only the first account; a press goes to
    every one, so a run still going on the other is just as much in the way."""
    world["runs"]["b/two"] = [{"databaseId": 99, "status": "in_progress"}]
    got = du.consider(now=NOW)
    assert got["started"] is False and not world["started"]
    assert "run 99" in got["why"] and "b/two" in got["why"]


def test_a_job_on_the_disk_makes_it_wait_and_says_which(world):
    world["holder"] = "collect_v2"
    got = du.consider(now=NOW)
    assert got["started"] is False and "collect_v2" in got["why"]


def test_an_update_already_running_is_not_doubled(world):
    world["running"]["btupdate_v2"] = True
    assert du.consider(now=NOW)["started"] is False
    assert not world["started"]


def test_github_that_cannot_be_asked_is_a_wait_not_a_press(world, monkeypatch):
    from tradingagents import cloud_sweep as cs

    def _boom(*a, **k):
        raise cs.CloudError("gh timed out")

    monkeypatch.setattr(cs, "fleets", _boom)
    got = du.consider(now=NOW)
    assert got["started"] is False and "gh timed out" in got["why"]


def test_a_refused_start_is_named(world):
    world["start_raises"] = dj.JobBusy("download_v2 is running")
    got = du.consider(now=NOW)
    assert got["started"] is False
    assert "JobBusy" in got["why"] and "download_v2 is running" in got["why"]


# ------------------------------------------------------------ the retry clock
def test_a_failed_try_is_not_retried_every_tick(world):
    world["holder"] = "collect_v2"
    du.consider(now=NOW)
    world["holder"] = ""
    assert du.consider(now=NOW + 60)["started"] is False, (
        "a try every 30 s would ask GitHub 120 times an hour")
    assert du.consider(now=NOW + du.RETRY_S)["started"] is True


def test_a_press_github_refused_does_not_reset_the_clock(world):
    """A good run yesterday, then a press that GitHub refused (the plan file
    has no cloud_run). The refused press measured nothing, and the good run
    must still be the one the clock counts from."""
    _ran(world, NOW - 30 * H)
    assert du.last_run() == NOW - 30 * H
    world["plan"].write_text(json.dumps({"when": NOW - 2 * H,
                                         "cloud_run": None}))
    assert du.last_run() == NOW - 30 * H
    assert du.consider(now=NOW)["started"] is True


def test_a_hand_press_counts_as_the_days_run(world):
    """The operator pressed it themselves an hour ago: that IS today's run."""
    _ran(world, NOW - 1 * H)
    assert du.consider(now=NOW)["started"] is False
    assert du.status(now=NOW)["next_run"] == NOW + 23 * H


# ------------------------------------------------------------- the screen
def test_the_status_carries_every_word_the_screen_prints(world):
    _ran(world, NOW - 5 * H)
    st = du.status(now=NOW)
    for k in ("enabled", "last_run", "last_run_url", "next_run", "due",
              "every_hours", "tfs", "days", "why"):
        assert k in st, k
    assert st["every_hours"] == 24 and st["due"] is False
    assert st["last_run_url"].endswith("/36446487985")


def test_the_screen_line_is_built_from_the_payload():
    src = (REPO / "webapp" / "src" / "components" / "backtest"
           / "JobsPanel.tsx").read_text(encoding="utf-8")
    line = src[src.index('{store === "v2" && daily && ('):]
    line = line[:line.index("</p>")]
    for used in ("daily.every_hours", "daily.tfs.join", "daily.days",
                 "fmtWhen(daily.last_run)", "fmtWhen(daily.next_run)",
                 "daily.why", "api.dailyUpdateSwitch(!daily.enabled)"):
        assert used in line, f"the line must print {used}, not a literal"


# --------------------------------------------------------- what must not move
def test_it_never_runs_under_a_test():
    """The live door's rule: no test run may send GitHub machines to work."""
    got = du.tick()
    assert got == {"started": False, "why": "never under a test run"}


def test_the_supervisor_ticks_it():
    src = (REPO / "tradingagents" / "api.py").read_text(encoding="utf-8")
    watch = src[src.index("def _watch() -> None:"):]
    watch = watch[:watch.index("_th.Thread(target=_watch")]
    assert "_du.tick()" in watch, "nothing would ever press it"


def test_the_collector_still_starts_nothing():
    """The Sep 09, 2026 correction stands for everything EXCEPT this job:
    the collector keeps no dispatch machinery of its own."""
    import inspect

    from tradingagents import cloud_autopilot as ca

    src = inspect.getsource(ca)
    assert "cs.dispatch(" not in src and "dispatch_across" not in src
    assert "btupdate_v2" not in src
