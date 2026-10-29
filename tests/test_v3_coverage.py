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
    monkeypatch.setattr(vcv, "state_path", lambda: tmp_path / "cloud" / "backfill.json")
    flights = {"daily": {}}
    monkeypatch.setattr(costs_daily, "read", lambda: flights["daily"])
    return SimpleNamespace(plan=plan, tmp=tmp_path, flights=flights)


def test_the_share_of_trades_that_paid_a_typical_cost_is_counted_older_and_unseen_apart(world):
    recs = vrs.load_coins(vrs.home("pilot"))
    got = vcv.trade_costs(recs)
    # every ENTRY (an order placed) and every EXIT (a trade's) is a leg; a leg is typical when
    # its entry went in with no book to check or its exit paid the coin's usual gap
    assert got["older"] == {"trades": 100, "typical_exits": 100, "orders": 105,
                            "unchecked_orders": 45, "funding_estimated": 0,
                            "legs": 205, "typical_legs": 145}
    assert got["unseen"] == {"trades": 40, "typical_exits": 5, "orders": 43,
                             "unchecked_orders": 0, "funding_estimated": 1,
                             "legs": 83, "typical_legs": 5}
    cover = vcv.minute_cover(recs)
    assert cover["older"] == {"mean": 0.0, "least": 0.0, "none": ["BTC_USDT", "XAU_USDT"],
                              "unknown": [], "coins": 2}
    assert cover["unseen"]["mean"] == pytest.approx(0.85) and cover["unseen"]["none"] == []


def test_an_entry_that_had_no_book_is_a_typical_cost_leg_though_its_exit_was_measured(world):
    rec = _rec("DOGE_USDT", world.plan, _walk(10, placement_unmeasured=10), _walk(0), 0.5, 0.5)
    got = vcv.trade_costs([rec])["older"]
    assert got["typical_exits"] == 0 and got["typical_legs"] == 10 and got["legs"] == 20


def test_a_missing_coverage_value_is_unknown_never_no_books(world):
    recs = [_rec("A_USDT", world.plan, _walk(1), _walk(1), 0.0, 0.5),
            {"coin": "B_USDT", "plan_id": world.plan["id"], "pre": {}, "combos": {}}]
    cover = vcv.minute_cover(recs)
    assert cover["older"]["none"] == ["A_USDT"] and cover["older"]["unknown"] == ["B_USDT"]
    assert cover["older"]["coins"] == 1 and cover["unseen"]["mean"] == pytest.approx(0.5)


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
    # only the multi-day run measures a press of many days: a one-day run's seconds are mostly
    # each machine's setup (and the red run is no measurement, the dealing job no work)
    assert got == {"runs": 1, "machine_s": 600, "coin_days": 20, "s_per_coin_day": 30.0,
                   "one_day_runs": 1}
    assert vcv.costs_speed([("a/x", 11)], gh=gh)["s_per_coin_day"] is None
    assert vcv.estimate(66_804, 12.9, 60) == {"machine_hours": 239.4, "wall_hours": 4.0,
                                              "machines": 60}
    assert vcv.estimate(0, 12.9, 60) == {"machine_hours": 0.0, "wall_hours": 0.0, "machines": 60}
    assert vcv.estimate(10, None, 60) is None


def _listings(plan, **over):
    out = dict.fromkeys(plan["coins"])          # None: the listing could not be read
    out.update(over)
    return out


def test_the_report_says_coverage_first_with_every_number_from_the_records(world, monkeypatch):
    monkeypatch.setattr(vcv, "costs_speed", lambda runs: {"runs": 2, "machine_s": 4820,
                                                          "coin_days": 373,
                                                          "s_per_coin_day": 12.9,
                                                          "one_day_runs": 0})
    world.flights["daily"] = {"done_days": ["2026-10-09", "2026-10-10"]}
    # XAU_USDT listed Oct 05, 2026 at noon UTC: its days Oct 01-04 are not missing for it
    listings = _listings(world.plan, XAU_USDT=_utc(2026, 10, 5, 12) * 1000)
    lines = vcv.report("pilot", runs=[("a/x", 11)], machines=60, listings=listings)
    assert lines[0] == f"COVERAGE FIRST for pilot: 2 coins measured under plan {world.plan['id']}"
    assert "2 of 2 coins have none" in lines[1] and lines[1].startswith("  older days")
    # the denominator is named: every entry and every exit, a TP exit counted too
    assert "145 of 205 entries and exits paid a typical cost (70.7%)" in lines[1]
    assert "45 of 105 entries went in with no book" in lines[1]
    assert "100 of 100 exits at a coin's usual cost" in lines[1]
    assert "5 of 83 entries and exits paid a typical cost (6.0%)" in lines[2]
    unseen = next(ln for ln in lines if ln.startswith("  unseen days: the cost store holds no"))
    assert "8 of 10 days" in unseen, "the unseen range is the whole of this short window"
    # BTC and ZEC (listing unknown) all 8 days, XAU its 4 listed days: 20, an upper bound
    assert "20 coin-days for the plan's 3 coins" in unseen and "listing unknown" in unseen
    assert "before a coin's listing" in unseen
    assert "this PC's clock" in unseen and fmt_when(_utc(2026, 10, 1)) in unseen
    assert fmt_when(_utc(2026, 10, 9)) in unseen
    assert any(ln.startswith("  older days: the plan's window holds none") for ln in lines)
    assert any("filling the unseen days' 20 coin-days: about 0.1 machine-hours, at least 0.0 "
               "hours of all 60 machines" in ln for ln in lines)


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


def test_the_two_ranges_each_get_their_own_line_and_estimate(world, monkeypatch):
    plan = _long_plan(world)
    monkeypatch.setattr(vcv, "costs_speed", lambda runs: {"runs": 1, "machine_s": 3600,
                                                          "coin_days": 100,
                                                          "s_per_coin_day": 36.0,
                                                          "one_day_runs": 0})
    # the run folder of "long" holds no records: the report still prices the plan's days
    lines = vcv.report("long", runs=[("a/x", 1)], machines=2,
                       listings=_listings(plan, **dict.fromkeys(plan["coins"], 0)))
    older = next(ln for ln in lines if ln.startswith("  older days: the cost store holds no"))
    unseen = next(ln for ln in lines if ln.startswith("  unseen days: the cost store holds no"))
    assert "30 of 30 days" in older and "60 coin-days" in older
    assert "90 of 90 days" in unseen and "180 coin-days" in unseen
    assert any("older days' 60 coin-days: about 0.6 machine-hours, at least 0.3 hours" in ln
               for ln in lines)
    assert any("unseen days' 180 coin-days: about 1.8 machine-hours, at least 0.9 hours" in ln
               for ln in lines)


def test_days_that_are_not_one_stretch_are_a_count_never_a_range(world):
    words = vcv.range_words(["2026-10-01", "2026-10-02", "2026-10-05"])
    assert words.startswith("3 UTC days in 2 separate stretches, not one range")
    assert "this PC's clock" in words
    assert fmt_when(_utc(2026, 10, 1)) in words and fmt_when(_utc(2026, 10, 6)) in words
    one = vcv.range_words(["2026-10-01", "2026-10-02"])
    assert one == (f"UTC days from {fmt_when(_utc(2026, 10, 1))} to {fmt_when(_utc(2026, 10, 3))}, "
                   "printed in this PC's clock")


def test_the_report_says_the_time_is_unknown_when_no_speed_runs_are_given(world):
    lines = vcv.report("pilot", runs=None, listings=_listings(world.plan))
    assert any("no costs runs were given to measure the speed" in ln and "unknown" in ln
               for ln in lines)
    assert not any("machine-hours" in ln for ln in lines)


def test_the_listing_is_the_exchanges_create_time_and_an_unreadable_one_is_unknown():
    class Fx:
        def contract_spec(self, sym):
            if sym == "BAD_USDT":
                raise RuntimeError("down")
            return {"createTime": 0 if sym == "OLD_USDT" else 1_760_000_000_000}

    got = vcv.listings_of(["NEW_USDT", "OLD_USDT", "BAD_USDT"], fx=Fx())
    assert got == {"NEW_USDT": 1_760_000_000_000, "OLD_USDT": None, "BAD_USDT": None}


def _air(at, *runs):
    return {"at": at, "runs": [{"repo": r, "run": n} for r, n in runs]}


def test_a_backfill_press_refuses_while_a_daily_costs_run_is_in_the_air_naming_it(world,
                                                                                    monkeypatch):
    now = _utc(2026, 10, 27, 12)
    world.flights["daily"] = {"flight": _air(now - 600, ("a/x", 4242))}
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "in_progress"})
    why = vcv.clash(["2025-11-03"], now)
    assert "daily costs job" in why and "run 4242 on a/x" in why
    # judged by the run's own status: finished, the flight is only waiting to be settled
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed",
                                                             "conclusion": "success"})
    assert vcv.clash(["2025-11-03"], now) == ""
    # a stale entry expires: a run that never finishes cannot hold the press for ever
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "in_progress"})
    world.flights["daily"] = {"flight": _air(now - 2 * vcv.STALE_S, ("a/x", 4242))}
    assert vcv.clash(["2025-11-03"], now) == ""
    # a daily press that has only said it is about to dispatch holds the door too
    world.flights["daily"] = {"pressing": {"at": now - 30}}
    assert "being dispatched" in vcv.clash(["2025-11-03"], now)
    world.flights["daily"] = {"pressing": {"at": now - 2 * vcv.PRESSING_S}}
    assert vcv.clash(["2025-11-03"], now) == ""


@pytest.fixture()
def daily(monkeypatch, world):
    """costs_daily's tick as the supervisor runs it (its real state file, in tmp), GitHub
    faked: returns the list of day lists the daily job dispatched."""
    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.setattr(costs_daily, "_under_pytest", lambda: False)
    monkeypatch.setattr(costs_daily, "STATE", world.tmp / "costs_daily.json")

    def read():
        try:
            return json.loads((world.tmp / "costs_daily.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    monkeypatch.setattr(costs_daily, "read", read)
    sent = []

    def dispatch(days, now):
        sent.append(list(days))
        return {"runs": [{"repo": "a/x", "run": 900 + len(sent), "coins": 3}], "refused": [],
                "unrun": []}

    monkeypatch.setattr(costs_daily, "_dispatch", dispatch)
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "in_progress"})
    return sent


def _backfill_in_air(world, now, days, run=77):
    (world.tmp / "cloud" / "backfill.json").write_text(json.dumps(
        {"flight": {"at": now - 5 * 3600, "days": days, "part": "unseen",
                    "runs": [{"repo": "a/x", "run": run, "coins": 3}], "unrun": []}}),
        encoding="utf-8")


def test_the_daily_costs_press_holds_off_a_backfill_in_the_air_on_its_months(world, daily,
                                                                            monkeypatch):
    """The overlap that used to lose days: a backfill pressed at 22:00 UTC was still running at
    the daily job's 03:05 press; both read a month file and uploaded it back, the later upload
    won and both marked their days done."""
    now = _utc(2026, 10, 27, 3) + 300
    _backfill_in_air(world, now, ["2026-10-01", "2026-10-02"])
    got = costs_daily.tick(now=now)
    assert got["started"] is False and not daily
    assert "backfill" in got["why"] and "run 77 on a/x" in got["why"]
    assert "2026-10" in got["why"]
    # the backfill's run finishes: the daily press goes at its next tick
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed",
                                                             "conclusion": "success"})
    assert costs_daily.tick(now=now + 60)["started"] is True and len(daily) == 1


def test_the_daily_costs_press_is_not_held_by_a_backfill_of_other_months(world, daily):
    now = _utc(2026, 10, 27, 3) + 300
    _backfill_in_air(world, now, ["2025-11-03"])
    assert costs_daily.tick(now=now)["started"] is True


def test_the_daily_costs_press_holds_off_when_the_backfill_record_cannot_be_read(world, daily):
    now = _utc(2026, 10, 27, 3) + 300
    (world.tmp / "cloud" / "backfill.json").write_text("{not json", encoding="utf-8")
    got = costs_daily.tick(now=now)
    assert got["started"] is False and not daily and "backfill.json" in got["why"]


def test_the_daily_costs_press_says_it_is_pressing_before_it_dispatches(world, daily,
                                                                       monkeypatch):
    now = _utc(2026, 10, 27, 3) + 300
    seen = {}
    real = costs_daily._dispatch

    def dispatch(days, at):
        seen["pressing"] = costs_daily.read().get("pressing")
        return real(days, at)

    monkeypatch.setattr(costs_daily, "_dispatch", dispatch)
    assert costs_daily.tick(now=now)["started"] is True
    assert seen["pressing"], "a backfill that looks now must see the daily press coming"
    assert "pressing" not in costs_daily.read() and costs_daily.read()["flight"]["runs"]


def test_a_daily_press_that_cannot_dispatch_stops_saying_it_is_pressing(world, daily,
                                                                       monkeypatch):
    def dispatch(days, at):
        raise RuntimeError("no account")

    monkeypatch.setattr(costs_daily, "_dispatch", dispatch)
    assert costs_daily.tick(now=_utc(2026, 10, 27, 3) + 300)["started"] is False
    assert "pressing" not in costs_daily.read()


def test_the_daily_press_backs_off_when_a_backfill_flight_appears_after_it_said_pressing(
        world, daily, monkeypatch):
    """Whichever of the two writes its marker second sees the other's: the daily job looks
    again after it wrote `pressing`."""
    now = _utc(2026, 10, 27, 3) + 300
    calls = []

    def held(days, at):
        calls.append(1)
        return "" if len(calls) == 1 else "a v3 backfill press is in the air"

    monkeypatch.setattr(costs_daily, "_held_by_backfill", held)
    got = costs_daily.tick(now=now)
    assert got["started"] is False and not daily and "backfill" in got["why"]
    assert "pressing" not in costs_daily.read() and not costs_daily.read().get("tried_at")


def test_a_backfill_that_finds_the_daily_press_coming_after_writing_its_own_flight_backs_off(
        world, monkeypatch):
    sent = []
    monkeypatch.setattr(cs, "usable_fleets", lambda: (["a/x"], []))
    monkeypatch.setattr(cs, "sync_fleet", lambda slug: "")
    monkeypatch.setattr(fd, "dispatch", lambda *a, **k: sent.append(a) or 1)
    now = _utc(2026, 10, 27, 12)
    calls = []

    def clash(days, at):
        calls.append(1)
        return "" if len(calls) == 1 else "the daily costs job is being dispatched"

    monkeypatch.setattr(vcv, "clash", clash)
    with pytest.raises(RuntimeError, match="being dispatched"):
        vcv.backfill("pilot", now=now, force=True)
    assert not sent and not vcv.read_state().get("flight"), "its flight was taken back"


def test_the_backfill_presses_the_newest_missing_days_for_the_plans_coins(world, monkeypatch):
    sent = []
    monkeypatch.setattr(cs, "usable_fleets", lambda: (["a/x", "b/x"], []))
    monkeypatch.setattr(cs, "sync_fleet", lambda slug: "")

    def dispatch(wf, inputs, slug, since=None):
        assert vcv.read_state()["flight"]["days"], "the press is saved before the dispatch"
        sent.append((wf, slug, dict(inputs)))
        return 500 + len(sent)

    monkeypatch.setattr(fd, "dispatch", dispatch)
    # noon UTC; `force` because the nightly quiet hours are this PC's own clock, which a test
    # cannot know
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
    assert vcv.settle(now=now)["red"] == ["b/x (run 502): failure"]
    assert not vcv.read_state().get("done")
    vcv.backfill("pilot", days_per_press=3, now=now, force=True)
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed",
                                                             "conclusion": "success"})
    assert vcv.settle(now=now)["red"] == []
    assert vcv.read_state()["done"][world.plan["id"]]["days"] == \
        ["2026-10-08", "2026-10-09", "2026-10-10"]
    assert vcv.backfill("pilot", days_per_press=3, now=now, force=True)["days"] == \
        ["2026-10-05", "2026-10-06", "2026-10-07"]


def test_a_day_backfilled_for_one_plan_is_not_held_for_another(world):
    other = {**world.plan, "coins": ["BTC_USDT", "DOGE_USDT"]}
    other["id"] = vu.plan_id(other)
    vcv._write_state({"done": {world.plan["id"]: {"coins": world.plan["coins"],
                                                  "days": ["2026-10-08"]}}})
    assert vcv.done_days(world.plan) == {"2026-10-08"}
    assert vcv.done_days(other) == set(), "another plan's coins, another record"
    # the same plan id read with a coin set the press did not cover is not held either
    wider = {**world.plan, "coins": world.plan["coins"] + ["DOGE_USDT"]}
    assert vcv.done_days(wider) == set()


def test_a_corrupt_state_file_is_refused_by_name_never_read_as_empty(world):
    (world.tmp / "cloud" / "backfill.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="backfill.json.*not readable"):
        vcv.read_state()
    with pytest.raises(RuntimeError, match="backfill.json"):
        vcv.backfill("pilot", now=_utc(2026, 10, 27, 12), force=True)
    (world.tmp / "cloud" / "backfill.json").write_text("[1]", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not an object"):
        vcv.read_state()


def test_settle_gives_back_a_stale_press_and_survives_a_status_read_that_fails(world,
                                                                               monkeypatch):
    now = _utc(2026, 10, 27, 12)
    vcv._write_state({"flight": {"at": now - 60, "days": ["2026-10-08"], "part": None,
                                 "plan_id": world.plan["id"], "coins": world.plan["coins"],
                                 "runs": [{"repo": "a/x", "run": 5, "coins": 3}], "unrun": []}})

    def boom(run, repo):
        raise RuntimeError("gh is down")

    monkeypatch.setattr(fd, "run_status", boom)
    assert vcv.settle(now=now) == {"settled": False, "why": "still running"}
    assert vcv.read_state()["flight"], "a status that cannot be read keeps the press"
    got = vcv.settle(now=now + 2 * vcv.STALE_S)
    assert got["settled"] and "never finished" in " ".join(got["red"])
    st = vcv.read_state()
    assert "flight" not in st and not st.get("done"), "the days are given back, not done"
    assert "never finished" in st["last_error"]


def test_a_press_that_never_dispatched_anything_is_not_marked_done(world):
    now = _utc(2026, 10, 27, 12)
    vcv._write_state({"flight": {"at": now - 3600, "days": ["2026-10-08"], "part": None,
                                 "plan_id": world.plan["id"], "coins": world.plan["coins"],
                                 "runs": [], "unrun": []}})
    got = vcv.settle(now=now)
    assert got["settled"] and got["red"] and not vcv.read_state().get("done")


def test_two_writes_never_share_a_temp_file_name(world, monkeypatch):
    names = []
    real = type(world.tmp).replace

    def spy(self, target):
        names.append(self.name)
        return real(self, target)

    monkeypatch.setattr(type(world.tmp), "replace", spy)
    vcv._write_state({"a": 1})
    vcv._write_state({"a": 2})
    assert len(names) == 2 and names[0] != names[1] and all(n.endswith(".tmp") for n in names)


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
    plan = _long_plan(world)
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
    vcv.settle(now=now)
    st = vcv.read_state()
    st["done"][plan["id"]]["days"] = sorted(set(st["done"][plan["id"]]["days"])
                                            | set(vcv.missing_days(plan, [], part="older")))
    vcv._write_state(st)
    assert vcv.backfill("long", now=now, force=True, part="older")["started"] is False
    assert vcv.backfill("long", days_per_press=2, now=now, force=True,
                        part="unseen")["days"] == ["2026-10-24", "2026-10-25"]


def test_the_costs_job_deals_to_every_account_the_backfill_presses_to():
    from tradingagents import cost_store

    assert cost_store.REPOS == ("jeremydevera/analyzer-x", "jeremydvera/analyzer-x",
                                "jeremydevera0903-gif/analyzer-x")
