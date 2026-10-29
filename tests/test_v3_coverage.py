"""COVERAGE FIRST for Backtest v3 (tradingagents/v3_coverage.py, Part 2b): the
share of a run's trades that paid a typical cost instead of their minute's own
book, older and unseen days apart; the plan's days the cost store does not
hold; the backfill's time at the speed the costs job's own runs measured; and
the backfill press - the existing costs job, dealt between every account, one
press at a time, never beside the daily costs job on a month file it writes."""
from __future__ import annotations

import calendar
import json
from types import SimpleNamespace

import pytest

from tradingagents import (
    cloud_sweep as cs,
    costs_daily,
    forecast_v2_daily as fd,
    v3_cloud as vc,
    v3_coverage as vcv,
    v3_research as vrs,
    v3_universe as vu,
)
from tradingagents.positions_view import fmt_when

DAY = 86_400


def _utc(y, m, d, h=0):
    return calendar.timegm((y, m, d, h, 0, 0))


def _walk(trades, **counts):
    return {"rows": [[0, 0, 0, 1, 0.1, "SL", 0.01, None]] * trades, "counts": counts}


def _rec(coin, plan, older, unseen, cov_older, cov_unseen):
    return {"coin": coin, "plan_id": plan["id"], "pre": {"coverage_older": cov_older,
                                                         "coverage_unseen": cov_unseen},
            "combos": {"a": {"older": older, "unseen": unseen}}}


@pytest.fixture()
def world(monkeypatch, tmp_path):
    monkeypatch.setattr(vc, "home", lambda: tmp_path / "cloud")
    monkeypatch.setattr(vrs, "home", lambda label="local": tmp_path / "research"
                        / vrs.plain_label(label))
    (tmp_path / "cloud").mkdir()
    # a ten-day plan, Oct 01 - Oct 11, 2026, of three coins
    plan = {"version": vu.VERSION, "start_ms": _utc(2026, 10, 1) * 1000,
            "end_ms": _utc(2026, 10, 11) * 1000, "coins": ["BTC_USDT", "XAU_USDT", "ZEC_USDT"]}
    plan["id"] = vu.plan_id(plan)
    copy = vu.save(plan, tmp_path / "cloud" / "pilot.plan.json")
    (tmp_path / "cloud" / "pilot.json").write_text(json.dumps(
        {"folder": "pilot", "plan_copy": str(copy), "plan_id": plan["id"]}), encoding="utf-8")
    folder = vrs.home("pilot")
    vrs.save_coin(folder, _rec("BTC_USDT", plan, _walk(40, cost_unmeasured=40, missed=5,
                                                       placement_unmeasured=45),
                               _walk(10, cost_unmeasured=2, post_only_reject=3,
                                     funding_estimated=1), 0.0, 0.8))
    vrs.save_coin(folder, _rec("XAU_USDT", plan, _walk(60, cost_unmeasured=60),
                               _walk(30, cost_unmeasured=3), 0.0, 0.9))
    flights = {"daily": {}}
    monkeypatch.setattr(costs_daily, "read", lambda: flights["daily"])
    return SimpleNamespace(plan=plan, tmp=tmp_path, flights=flights)


def test_the_share_of_trades_that_paid_a_typical_cost_is_counted_older_and_unseen_apart(world):
    recs = vrs.load_coins(vrs.home("pilot"))
    got = vcv.trade_costs(recs)
    assert got["older"] == {"trades": 100, "typical_exits": 100, "orders": 105,
                            "unchecked_orders": 45, "funding_estimated": 0}
    assert got["unseen"] == {"trades": 40, "typical_exits": 5, "orders": 43,
                             "unchecked_orders": 0, "funding_estimated": 1}
    cover = vcv.minute_cover(recs)
    assert cover["older"] == {"mean": 0.0, "least": 0.0, "none": ["BTC_USDT", "XAU_USDT"],
                              "coins": 2}
    assert cover["unseen"]["mean"] == pytest.approx(0.85) and cover["unseen"]["none"] == []


def test_the_missing_days_are_every_window_day_the_store_does_not_hold(world):
    done = ["2026-10-08", "2026-10-09", "2026-10-10", "2026-10-11"]
    assert vcv.missing_days(world.plan, done) == [f"2026-10-0{d}" for d in range(1, 8)]


def test_the_speed_is_the_costs_jobs_own_machine_seconds_per_coin_day():
    runs = {11: {"displayTitle": "Costs per minute · 2026-10-26 · jeremydevera 353 coins",
                 "conclusion": "success",
                 "jobs": [{"name": "plan", "startedAt": "2026-10-27T03:00:00Z",
                           "completedAt": "2026-10-27T03:00:20Z"}]
                 + [{"name": f"costs ({k})", "startedAt": "2026-10-27T03:01:00Z",
                     "completedAt": "2026-10-27T03:04:31Z"} for k in range(20)]},
            12: {"displayTitle": "Costs per minute · 2026-09-01,2026-09-02 · v3 backfill "
                                 "jeremydvera 10 coins", "conclusion": "success",
                 "jobs": [{"name": "costs (0)", "startedAt": "2026-10-27T10:00:00Z",
                           "completedAt": "2026-10-27T10:10:00Z"}]},
            13: {"displayTitle": "Costs per minute · 2026-10-25 · x 353 coins",
                 "conclusion": "failure", "jobs": []}}
    gh = lambda *a, **k: json.dumps(runs[int(a[2])])          # noqa: E731
    got = vcv.costs_speed([("a/x", 11), ("b/x", 12), ("a/x", 13)], gh=gh)
    # 20 machines x 211 s + one of 600 s, over 353 x 1 + 10 x 2 coin-days; the red run is no
    # measurement and the dealing job is no work
    assert got == {"runs": 2, "machine_s": 20 * 211 + 600, "coin_days": 373,
                   "s_per_coin_day": round((20 * 211 + 600) / 373, 1)}
    assert vcv.estimate(66_804, 12.9, 60) == {"machine_hours": 239.4, "wall_hours": 4.0,
                                              "machines": 60}
    assert vcv.estimate(10, None, 60) is None


def test_the_report_says_coverage_first_with_every_number_from_the_records(world, monkeypatch):
    monkeypatch.setattr(vcv, "costs_speed", lambda runs: {"runs": 2, "machine_s": 4820,
                                                          "coin_days": 373,
                                                          "s_per_coin_day": 12.9})
    world.flights["daily"] = {"done_days": ["2026-10-09", "2026-10-10"]}
    lines = vcv.report("pilot", runs=[("a/x", 11)], machines=60)
    assert lines[0] == f"COVERAGE FIRST for pilot: 2 coins measured under plan {world.plan['id']}"
    assert "100 of 100 trades exited at a typical cost (100.0%)" in lines[1]
    assert "2 of 2 coins have none" in lines[1]
    assert "5 of 40 trades exited at a typical cost (12.5%)" in lines[2]
    # the days printed in the project's one date format, from the first missing day's start to
    # the last one's end
    assert lines[3] == ("  the cost store holds no reading for 8 of the window's days (UTC days "
                        f"from {fmt_when(_utc(2026, 10, 1))} to {fmt_when(_utc(2026, 10, 9))}): "
                        "24 coin-days for the plan's 3 coins")
    assert "about 0.1 machine-hours, at least 0.0 hours of all 60 machines" in lines[4]


def test_a_backfill_press_never_runs_beside_the_daily_costs_job_on_its_months(world):
    world.flights["daily"] = {"flight": {"at": 1}}
    now = _utc(2026, 10, 27, 12)
    assert vcv.clash(["2025-11-03"], now) == "the daily costs job has a run in the air"
    world.flights["daily"] = {}
    three_am = _utc(2026, 10, 27, 3)
    assert vcv.clash(["2026-08-10"], three_am).startswith("between 02:00 and 08:59 UTC")
    assert vcv.clash(["2025-11-03"], three_am) == "", "a month the daily job never writes"
    assert vcv.clash(["2026-08-10"], now) == "", "outside the daily job's hours"


def test_the_backfill_presses_the_newest_missing_days_for_the_plans_coins(world, monkeypatch):
    sent = []
    monkeypatch.setattr(cs, "usable_fleets", lambda: (["a/x", "b/x"], []))
    monkeypatch.setattr(cs, "sync_fleet", lambda slug: "")

    def dispatch(wf, inputs, slug, since=None):
        assert vcv.read_state()["flight"]["days"], "the press is saved before the dispatch"
        sent.append((wf, slug, dict(inputs)))
        return 500 + len(sent)

    monkeypatch.setattr(fd, "dispatch", dispatch)
    # noon UTC (outside the daily costs job's hours); `force` because the nightly quiet hours are
    # this PC's own clock, which a test cannot know
    now = _utc(2026, 10, 27, 12)
    got = vcv.backfill("pilot", days_per_press=3, now=now, force=True)
    assert got["days"] == ["2026-10-08", "2026-10-09", "2026-10-10"], "newest first"
    assert [s[:2] for s in sent] == [("costs.yml", "a/x"), ("costs.yml", "b/x")]
    assert sorted(c for _w, _s, i in sent for c in i["coin_list"].split(",")) == \
        world.plan["coins"]
    assert all(i["days"] == "2026-10-08,2026-10-09,2026-10-10" for _w, _s, i in sent)
    with pytest.raises(RuntimeError, match="still in the air"):
        vcv.backfill("pilot", now=now, force=True)
    # one share red: the days go back, named; then both green: the days are done
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {
        "status": "completed", "conclusion": "failure" if run == 502 else "success"})
    assert vcv.settle()["red"] == ["b/x (run 502): failure"]
    assert not vcv.read_state().get("done_days")
    vcv.backfill("pilot", days_per_press=3, now=now, force=True)
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed",
                                                             "conclusion": "success"})
    assert vcv.settle()["red"] == []
    assert vcv.read_state()["done_days"] == ["2026-10-08", "2026-10-09", "2026-10-10"]
    assert vcv.backfill("pilot", days_per_press=3, now=now, force=True)["days"] == \
        ["2026-10-05", "2026-10-06", "2026-10-07"]


def _long_plan(world):
    """A 120-day plan (Jun 28 - Oct 26, 2026): its unseen days are the last 90, the older
    days the 30 before them."""
    plan = {"version": vu.VERSION, "start_ms": _utc(2026, 6, 28) * 1000,
            "end_ms": _utc(2026, 10, 26) * 1000, "coins": ["BTC_USDT", "XAU_USDT"]}
    plan["id"] = vu.plan_id(plan)
    copy = vu.save(plan, world.tmp / "cloud" / "long.plan.json")
    (world.tmp / "cloud" / "long.json").write_text(json.dumps(
        {"folder": "long", "plan_copy": str(copy), "plan_id": plan["id"]}), encoding="utf-8")
    return plan


def test_the_two_ranges_are_the_unseen_days_and_the_older_days_apart(world):
    plan = _long_plan(world)
    older = vcv.missing_days(plan, [], part="older")
    unseen = vcv.missing_days(plan, [], part="unseen")
    whole = vcv.missing_days(plan, [])
    assert older + unseen == whole and len(older) == 30 and len(unseen) == 90
    assert older[0] == "2026-06-28" and older[-1] == "2026-07-27"
    assert unseen[0] == "2026-07-28" and unseen[-1] == "2026-10-25"
    assert vcv.missing_days(plan, ["2026-10-25"], part="unseen")[-1] == "2026-10-24"
    with pytest.raises(ValueError, match="older.*unseen"):
        vcv.missing_days(plan, [], part="newest")


def test_a_backfill_names_its_range_and_stays_inside_it(world, monkeypatch):
    _long_plan(world)
    sent = []
    monkeypatch.setattr(cs, "usable_fleets", lambda: (["a/x"], []))
    monkeypatch.setattr(cs, "sync_fleet", lambda slug: "")
    monkeypatch.setattr(fd, "dispatch", lambda wf, inputs, slug, since=None:
                        sent.append(dict(inputs)) or 700)
    now = _utc(2026, 10, 27, 12)
    got = vcv.backfill("long", days_per_press=3, now=now, force=True, part="older")
    assert got["days"] == ["2026-07-25", "2026-07-26", "2026-07-27"], "the older range's newest"
    assert got["part"] == "older" and vcv.read_state()["flight"]["part"] == "older"
    assert sent[0]["days"] == "2026-07-25,2026-07-26,2026-07-27"
    # once the older range is filled the press says so instead of reaching into the other range
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed",
                                                             "conclusion": "success"})
    vcv.settle()
    done = vcv.read_state()["done_days"]
    st = vcv.read_state()
    st["done_days"] = sorted(set(done) | set(vcv.missing_days(_long_plan(world), [],
                                                              part="older")))
    vcv._write_state(st)
    assert vcv.backfill("long", now=now, force=True, part="older")["started"] is False
    assert vcv.backfill("long", days_per_press=2, now=now, force=True,
                        part="unseen")["days"] == ["2026-10-24", "2026-10-25"]


def test_the_costs_job_deals_to_every_account_the_backfill_presses_to():
    from tradingagents import cost_store

    assert cost_store.REPOS == ("jeremydevera/analyzer-x", "jeremydvera/analyzer-x",
                                "jeremydevera0903-gif/analyzer-x")
