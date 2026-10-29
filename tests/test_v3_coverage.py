"""COVERAGE FIRST for Backtest v3 (tradingagents/v3_coverage.py, Part 2b): the
share of a run's trades that paid a typical cost instead of their minute's own
book, older and unseen days apart; the plan's days the cost store does not
hold; the backfill's time at the speed the costs job's own runs measured; and
the backfill press - the existing costs job, dealt between every account, one
press at a time, never beside the daily costs job on a month file it writes."""
from __future__ import annotations

import calendar
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tradingagents import (
    cloud_sweep as cs,
    cost_store,
    costs_daily,
    forecast_v2_daily as fd,
    v3_cloud as vc,
    v3_coverage as vcv,
    v3_research as vrs,
    v3_universe as vu,
)
from tradingagents.positions_view import fmt_when

# the real functions, taken before any fixture fakes them (a test needing one sets it back with its
# own monkeypatch; never `undo`, which would also undo conftest's isolation of the real store)
REAL_LOAD_MONTH = cost_store.load_month
REAL_DAILY_DISPATCH = costs_daily._dispatch

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
    monkeypatch.setattr(costs_daily, "read_strict", lambda: flights["daily"], raising=False)
    # THE COST STORE, faked: {(coin, "YYYYMM"): packed month} - nothing here reaches GitHub
    store = {}
    monkeypatch.setattr(cost_store, "load_month", lambda sym, ym, **k: store.get((sym, ym)))
    return SimpleNamespace(plan=plan, tmp=tmp_path, flights=flights, store=store)


def _hold(world, coin, *days):
    """The cost store holds every hour of `days` for `coin`, read when practice looks."""
    import numpy as np

    from tradingagents import book_history as bh

    for day in days:
        y, m, d = (int(x) for x in day.split("-"))
        t0 = _utc(y, m, d)
        key = (coin, f"{y:04d}{m:02d}")
        old = world.store.get(key)
        t = np.array([t0 + 3600 * h + bh.READ_AT_S for h in range(24)], "int64")
        if old is not None:
            t = np.concatenate([old["t"], t])
        world.store[key] = {"t": t, "at": np.full(len(t), bh.READ_AT_S, "int8")}


def test_the_share_of_trades_that_paid_a_typical_cost_is_counted_older_and_unseen_apart(world):
    recs = vrs.load_coins(vrs.home("pilot"))
    got = vcv.trade_costs(recs)
    # a FILLED trade has two legs, its entry and its exit (M2): an exit is settled without its own
    # minute's book when it paid the coin's usual gap, an entry when its order went in with no
    # book to check post-only against - counted per order PLACED, so with 5 orders that never
    # filled, 40 to 45 of the 45 unchecked orders were filled entries: a range
    assert got["older"] == {"trades": 100, "typical_exits": 100, "orders": 105, "missed": 5,
                            "unchecked_orders": 45, "funding_estimated": 0,
                            "legs": 200, "typical_low": 140, "typical_high": 145}
    assert got["unseen"] == {"trades": 40, "typical_exits": 5, "orders": 43, "missed": 0,
                             "unchecked_orders": 0, "funding_estimated": 1,
                             "legs": 80, "typical_low": 5, "typical_high": 5}
    assert vcv.share_words(got["older"]) == "70.0%-72.5% of 200 entries and exits"
    assert vcv.share_words(got["unseen"]) == "6.2% of 80 entries and exits"
    cover = vcv.minute_cover(recs)
    assert cover["older"] == {"mean": 0.0, "least": 0.0, "none": ["BTC_USDT", "XAU_USDT"],
                              "unknown": [], "coins": 2}
    assert cover["unseen"]["mean"] == pytest.approx(0.85) and cover["unseen"]["none"] == []


def test_an_entry_that_had_no_book_is_a_typical_cost_leg_though_its_exit_was_measured(world):
    rec = _rec("DOGE_USDT", world.plan, _walk(10, placement_unmeasured=10), _walk(0), 0.5, 0.5)
    got = vcv.trade_costs([rec])["older"]
    assert got["typical_exits"] == 0 and got["legs"] == 20
    assert got["typical_low"] == got["typical_high"] == 10, "no order missed: all 10 filled"


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
    # the cost store itself holds Oct 09 and Oct 10 for every coin (whoever pressed them)
    for coin in world.plan["coins"]:
        _hold(world, coin, "2026-10-09", "2026-10-10")
    # XAU_USDT listed Oct 05, 2026 at noon UTC: its days Oct 01-04 are not missing for it
    listings = _listings(world.plan, XAU_USDT=_utc(2026, 10, 5, 12) * 1000)
    lines = vcv.report("pilot", runs=[("a/x", 11)], machines=60, listings=listings)
    assert lines[0] == f"COVERAGE FIRST for pilot: 2 coins measured under plan {world.plan['id']}"
    assert "2 of 2 coins have none" in lines[1] and lines[1].startswith("  older days")
    # the denominator is named: the entries and exits of the FILLED trades (M2)
    assert ("between 140 and 145 of the 200 entries and exits of 100 filled trades were settled "
            "without their own minute's book (70.0%-72.5%)") in lines[1]
    assert "45 of the 105 orders placed (filled or not) went in with no book" in lines[1]
    assert "which of them filled is not counted" in lines[1]
    assert "100 of 100 exits paid a coin's usual cost" in lines[1]
    assert "5 of the 80 entries and exits of 40 filled trades" in lines[2]
    assert "(6.2%)" in lines[2] and "which of them filled" not in lines[2]
    assert any("read from the cost store: 3 coin-months" in ln for ln in lines)
    unseen = next(ln for ln in lines if ln.startswith("  unseen days: ") and "lack" in ln)
    assert "8 of 10 days" in unseen, "the unseen range is the whole of this short window"
    # BTC and ZEC (listing unknown) all 8 days, XAU its 4 listed days: 20, an upper bound
    assert "20 coin-days missing over the plan's 3 coins" in unseen and "listing unknown" in unseen
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
    older = next(ln for ln in lines if ln.startswith("  older days: ") and "lack" in ln)
    unseen = next(ln for ln in lines if ln.startswith("  unseen days: ") and "lack" in ln)
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
    # a stale entry expires: a run that never finishes cannot hold the press for ever - past
    # STALE_S only while GitHub itself says it is not finished, and never past AIR_MAX_S (M8)
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "in_progress"})
    world.flights["daily"] = {"flight": _air(now - 2 * vcv.STALE_S, ("a/x", 4242))}
    assert "still says in_progress after 24 hours" in vcv.clash(["2025-11-03"], now)
    world.flights["daily"] = {"flight": _air(now - vcv.AIR_MAX_S - 60, ("a/x", 4242))}
    assert vcv.clash(["2025-11-03"], now) == ""
    monkeypatch.setattr(fd, "run_status", lambda run, repo: (_ for _ in ()).throw(OSError("gh")))
    world.flights["daily"] = {"flight": _air(now - 2 * vcv.STALE_S, ("a/x", 4242))}
    assert vcv.clash(["2025-11-03"], now) == "", "past STALE_S an unreadable status holds nothing"
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
    monkeypatch.setattr(costs_daily, "read_strict", read, raising=False)
    sent = []

    def dispatch(days, now, step=None):
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
    later = now + costs_daily.HELD_RECHECK_S + 1
    assert costs_daily.tick(now=later)["started"] is True and len(daily) == 1
    st = costs_daily.read()
    assert "held" not in st and not st.get("last_error"), "a released hold is not left behind"


def test_the_daily_costs_press_is_not_held_by_a_backfill_of_other_months(world, daily):
    now = _utc(2026, 10, 27, 3) + 300
    _backfill_in_air(world, now, ["2025-11-03"])
    assert costs_daily.tick(now=now)["started"] is True


def _corrupt_record(world, now, age_s):
    p = world.tmp / "cloud" / "backfill.json"
    p.write_text("{not json", encoding="utf-8")
    os.utime(p, (now - age_s, now - age_s))


def test_an_unreadable_backfill_record_holds_the_daily_press_but_only_for_twelve_hours(
        world, daily):
    now = _utc(2026, 10, 27, 3) + 300
    _corrupt_record(world, now, 3600)
    got = costs_daily.tick(now=now)
    assert got["started"] is False and not daily and "backfill.json" in got["why"]
    assert "could not read the v3 backfill record" in got["why"] and "at most 12 hours" in got["why"]
    # just inside the bound: still held; just outside it: the press runs and says it ignored it
    t2 = now + costs_daily.HELD_RECHECK_S + 1
    _corrupt_record(world, t2, vcv.STALE_S - 60)
    assert costs_daily.tick(now=t2)["started"] is False
    t3 = now + 2 * costs_daily.HELD_RECHECK_S + 2
    _corrupt_record(world, t3, vcv.STALE_S + 60)
    got = costs_daily.tick(now=t3)
    assert got["started"] is True and len(daily) == 1
    st = costs_daily.read()
    assert "could not be read" in st["last_error"] and "runs without it" in st["last_error"]
    assert "held" not in st


def test_a_record_that_cannot_even_be_stat_ed_is_judged_by_when_it_was_first_seen(world, daily,
                                                                                   monkeypatch):
    now = _utc(2026, 10, 27, 3) + 300
    _corrupt_record(world, now, 60)
    monkeypatch.setattr(vcv, "record_mtime", lambda: None)
    assert costs_daily.tick(now=now)["started"] is False
    assert costs_daily.tick(now=now + vcv.STALE_S - 60)["started"] is False
    assert costs_daily.tick(now=now + vcv.STALE_S + 2 * costs_daily.HELD_RECHECK_S)[
        "started"] is True


def test_a_record_stamped_in_the_future_never_stretches_the_twelve_hour_bound(world, daily,
                                                                              monkeypatch):
    """A clock set ahead when the file was written: `now - stamp` is negative, and judged by the
    stamp the hold would last the skew plus twelve hours."""
    now = _utc(2026, 10, 27, 3) + 300
    _corrupt_record(world, now, -10 * 3600)                    # stamped ten hours ahead
    assert costs_daily.tick(now=now)["started"] is False
    assert costs_daily.tick(now=now + vcv.STALE_S - 600)["started"] is False
    got = costs_daily.tick(now=now + vcv.STALE_S + 2 * costs_daily.HELD_RECHECK_S)
    assert got["started"] is True and len(daily) == 1, "held past twelve hours by the skew"


def test_the_notice_that_the_press_ran_without_the_record_is_never_thinned_by_the_hourly_gate(
        world, daily, capsys):
    now = _utc(2026, 10, 27, 3) + 300
    _corrupt_record(world, now, vcv.STALE_S - 1800)            # half an hour from the bound
    assert costs_daily.tick(now=now)["started"] is False
    assert "waits for it" in capsys.readouterr().out           # the hold line: held_said_at = now
    t = now + 2100                                              # inside that hour, past the bound
    assert costs_daily.tick(now=t)["started"] is True
    out = capsys.readouterr().out
    assert out.count("[costs-daily]") == 1 and "runs without it" in out
    assert "runs without it" in costs_daily.read()["last_error"]
    # said once per episode, not again at the next press of the same unreadable file
    assert costs_daily.tick(now=t + 3 * 86400)["started"] in (True, False)
    assert "runs without it" not in capsys.readouterr().out


def test_a_hold_is_seen_in_the_state_and_said_once_an_hour_in_the_log(world, daily, capsys,
                                                                     monkeypatch):
    now = _utc(2026, 10, 27, 3) + 300
    _backfill_in_air(world, now, ["2026-10-01"])
    costs_daily.tick(now=now)
    st = costs_daily.read()
    assert st["held"]["why"] == st["last_error"] and "run 77 on a/x" in st["last_error"]
    first = capsys.readouterr().out
    assert first.count("[costs-daily] a v3 backfill press is in the air") == 1
    # every look in the next hour finds it held and says nothing more; an hour later, once more
    for k in range(1, 8):
        costs_daily.tick(now=now + k * (costs_daily.HELD_RECHECK_S + 1))
    assert capsys.readouterr().out == ""
    costs_daily.tick(now=now + costs_daily.HELD_SAY_S + 10)
    assert capsys.readouterr().out.count("[costs-daily]") == 1


def test_a_held_press_does_not_ask_github_every_supervisor_pass(world, daily, monkeypatch):
    now = _utc(2026, 10, 27, 3) + 300
    _backfill_in_air(world, now, ["2026-10-01"])
    asked = []
    monkeypatch.setattr(fd, "run_status", lambda run, repo: asked.append(run)
                        or {"status": "in_progress"})
    for k in range(0, 600, 30):                    # the supervisor's 30 s tick, ten minutes
        costs_daily.tick(now=now + k)
    assert len(asked) <= 4, asked      # a look now, then one every HELD_RECHECK_S (twice a look)
    assert not daily


def test_the_daily_costs_press_says_it_is_pressing_before_it_dispatches(world, daily,
                                                                       monkeypatch):
    now = _utc(2026, 10, 27, 3) + 300
    seen = {}
    real = costs_daily._dispatch

    def dispatch(days, at, step=None):
        seen["pressing"] = costs_daily.read().get("pressing")
        return real(days, at, step=step)

    monkeypatch.setattr(costs_daily, "_dispatch", dispatch)
    assert costs_daily.tick(now=now)["started"] is True
    assert seen["pressing"], "a backfill that looks now must see the daily press coming"
    assert "pressing" not in costs_daily.read() and costs_daily.read()["flight"]["runs"]


def test_a_daily_press_that_cannot_dispatch_stops_saying_it_is_pressing(world, daily,
                                                                       monkeypatch):
    def dispatch(days, at, step=None):
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

    def held(days, at, st):
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

    def clash(days, at, st=None):
        calls.append(1)
        return "" if len(calls) == 1 else "the daily costs job is being dispatched"

    monkeypatch.setattr(vcv, "clash", clash)
    with pytest.raises(RuntimeError, match="being dispatched"):
        vcv.backfill("pilot", now=now, force=True, listings=_listings(world.plan))
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
    lst = _listings(world.plan)
    got = vcv.backfill("pilot", days_per_press=3, now=now, force=True, listings=lst)
    assert got["days"] == ["2026-10-08", "2026-10-09", "2026-10-10"], "newest first"
    assert [s[:2] for s in sent] == [("costs.yml", "a/x"), ("costs.yml", "b/x")]
    assert sorted(c for _w, _s, i in sent for c in i["coin_list"].split(",")) == \
        world.plan["coins"]
    assert all(i["days"] == "2026-10-08,2026-10-09,2026-10-10" for _w, _s, i in sent)
    with pytest.raises(RuntimeError, match="still in the air"):
        vcv.backfill("pilot", now=now, force=True, listings=lst)
    # one share red: the days go back, named; then both green: the days are asked for once
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {
        "status": "completed", "conclusion": "failure" if run == 502 else "success"})
    assert vcv.settle(now=now)["red"] == ["b/x (run 502): failure"]
    assert not vcv.read_state().get("presses")
    assert vcv.backfill("pilot", days_per_press=3, now=now, force=True, listings=lst)["days"] == \
        ["2026-10-08", "2026-10-09", "2026-10-10"]
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed",
                                                             "conclusion": "success"})
    assert vcv.settle(now=now)["red"] == []
    press = vcv.read_state()["presses"][-1]
    assert press["days"] == ["2026-10-08", "2026-10-09", "2026-10-10"]
    assert press["coins"] == world.plan["coins"]
    # the store now holds those days for two coins; ZEC's never completed (an hour missing at
    # Gate) and a green press already asked for them, so they are not asked again
    for coin in ("BTC_USDT", "XAU_USDT"):
        _hold(world, coin, "2026-10-08", "2026-10-09", "2026-10-10")
    assert vcv.backfill("pilot", days_per_press=3, now=now, force=True, listings=lst)["days"] == \
        ["2026-10-05", "2026-10-06", "2026-10-07"]


def test_filled_days_belong_to_the_coin_and_the_day_so_a_rebuilt_plan_never_calls_them_missing(
        world, monkeypatch):
    """I4: the days come from the cost store, per coin and day. A plan REBUILT a day later (a new
    id, one more day) still sees every day the store holds, and can be pressed by its plan file
    before any run of it exists - only its new day is asked for."""
    for coin in world.plan["coins"]:
        _hold(world, coin, *[f"2026-10-{d:02d}" for d in range(1, 11)])
    lst = _listings(world.plan)
    lines = vcv.report("pilot", listings=lst)
    assert any("unseen days: the cost store holds every one of its 10 days" in ln for ln in lines)
    rebuilt = {**world.plan, "end_ms": _utc(2026, 10, 12) * 1000}
    rebuilt["id"] = vu.plan_id(rebuilt)
    assert rebuilt["id"] != world.plan["id"]
    path = vu.save(rebuilt, world.tmp / "plan.json")
    lines = vcv.report(plan_path=path, listings=lst)
    assert lines[0].startswith(f"COVERAGE FIRST for the plan {rebuilt['id']}")
    gap = next(ln for ln in lines if "lack a reading" in ln)
    assert "1 of 11 days" in gap and "3 coin-days missing" in gap
    sent = []
    monkeypatch.setattr(cs, "usable_fleets", lambda: (["a/x"], []))
    monkeypatch.setattr(cs, "sync_fleet", lambda slug: "")
    monkeypatch.setattr(fd, "dispatch", lambda wf, inputs, slug, since=None:
                        sent.append(dict(inputs)) or 801)
    got = vcv.backfill(plan_path=path, now=_utc(2026, 10, 27, 12), force=True, listings=lst)
    assert got["days"] == ["2026-10-11"] and got["plan_id"] == rebuilt["id"]
    assert sent[0]["days"] == "2026-10-11"
    assert sorted(sent[0]["coin_list"].split(",")) == world.plan["coins"]


def test_a_coin_already_holding_the_days_is_not_in_the_press(world, monkeypatch):
    _hold(world, "BTC_USDT", "2026-10-10")
    sent = []
    monkeypatch.setattr(cs, "usable_fleets", lambda: (["a/x"], []))
    monkeypatch.setattr(cs, "sync_fleet", lambda slug: "")
    monkeypatch.setattr(fd, "dispatch", lambda wf, inputs, slug, since=None:
                        sent.append(dict(inputs)) or 802)
    got = vcv.backfill("pilot", days_per_press=1, now=_utc(2026, 10, 27, 12), force=True,
                       listings=_listings(world.plan))
    assert got["days"] == ["2026-10-10"] and got["coins"] == ["XAU_USDT", "ZEC_USDT"]


def test_a_day_is_held_only_when_all_24_hours_were_read_when_practice_looks():
    import numpy as np

    from tradingagents import book_history as bh

    t0 = _utc(2026, 10, 8)
    full = np.array([t0 + 3600 * h + bh.READ_AT_S for h in range(24)], "int64")
    assert vcv.held_days_of({"t": full, "at": np.full(24, bh.READ_AT_S, "int8")}) == \
        {"2026-10-08"}
    assert vcv.held_days_of({"t": full[:23], "at": np.full(23, bh.READ_AT_S, "int8")}) == set()
    assert vcv.held_days_of({"t": full, "at": np.zeros(24, "int8")}) == set(), \
        "read at the close (the old way): the costs job reads it again"
    assert vcv.held_days_of(None) == set()


def test_the_rule_for_a_held_day_is_the_costs_jobs_own(monkeypatch, tmp_path):
    """`held_days_of` must say what the costs job's shard skips (costs_shard.held_days), or a
    press would be asked for days it skips, or never for days it would fill."""
    import importlib.util
    import sys

    import numpy as np

    from tradingagents import book_history as bh

    scripts = Path(__file__).resolve().parent.parent / ".github" / "scripts"
    for k in ("GITHUB_TOKEN", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DAYS_LIST", "2026-10-08")
    monkeypatch.setenv("COIN_LIST", "BTC_USDT")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("costs_shard_v3cov", scripts / "costs_shard.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop("costs_shard_v3cov", None)
    t0 = _utc(2026, 10, 8)
    t = np.array([t0 + 3600 * h + bh.READ_AT_S for h in range(48) if h != 30], "int64")
    packed = {"t": t, "at": np.full(len(t), bh.READ_AT_S, "int8")}
    shard = {time.strftime("%Y-%m-%d", time.gmtime(d)) for d in mod.held_days(packed)}
    assert vcv.held_days_of(packed) == shard == {"2026-10-08"}


def test_an_unreadable_month_is_named_and_its_days_count_as_missing(world, monkeypatch):
    from tradingagents.cost_store import CostReadError

    def load(sym, ym, **k):
        if sym == "BTC_USDT":
            raise CostReadError("BTC_USDT 202610 could not be read from a/x: 502")
        return world.store.get((sym, ym))

    monkeypatch.setattr(cost_store, "load_month", load)
    got = vcv.store_days(world.plan["coins"], _utc(2026, 10, 1), _utc(2026, 10, 11))
    assert got["coin_months"] == 3 and got["by_coin"]["BTC_USDT"] == set()
    assert got["unreadable"] == ["BTC_USDT 202610: CostReadError: BTC_USDT 202610 could not be "
                                 "read from a/x: 502"]


def test_settling_a_press_takes_this_pcs_cached_months_it_wrote_out_of_the_cache(world,
                                                                                  monkeypatch):
    """I5: a month that ended more than 35 days ago is served from this PC's cache for ever, so
    after a backfill wrote it the PC would keep the readings from before. Settling the press takes
    every coin-month it pressed out of the cache, and the next read fetches what it wrote."""
    import numpy as np

    from tradingagents import cost_store as real_cs

    # the real load_month (the fixture faked it), its cache in this test's tmp (conftest)
    monkeypatch.setattr(cost_store, "load_month", REAL_LOAD_MONTH)
    old = {k: np.zeros(1, dtype) for k, dtype in (("t", "int64"), ("bid", "float64"),
                                                    ("ask", "float64"), ("spread", "float32"),
                                                    ("buy", "float32"), ("sell", "float32"),
                                                    ("exhausted", "bool"), ("source", "int8"),
                                                    ("at", "int8"))}
    real_cs.CACHE.mkdir(parents=True, exist_ok=True)
    cached = real_cs.CACHE / real_cs.asset("XAU_USDT", "202607")
    cached.write_bytes(real_cs.to_bytes(old))
    new = {**old, "t": np.array([_utc(2026, 7, 20)], "int64")}

    def fetch(u):
        return (200, real_cs.to_bytes(new)) if "jeremydevera/" in u else (404, b"")

    # a final month (July ended more than 35 days before today) is the cached one...
    assert int(real_cs.load_month("XAU_USDT", "202607", fetch=fetch)["t"][0]) == 0
    now = _utc(2026, 10, 27, 12)
    vcv._write_state({"flight": {"at": now - 3600, "days": ["2026-07-20"], "part": "older",
                                 "plan_id": "x", "coins": ["XAU_USDT"],
                                 "runs": [{"repo": "a/x", "run": 9, "coins": 1}], "unrun": []}})
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed",
                                                             "conclusion": "success"})
    got = vcv.settle(now=now)
    assert got["settled"] and got["stale_removed"] == 1 and not cached.exists()
    # ...and after the press this PC reads what the press wrote
    assert int(real_cs.load_month("XAU_USDT", "202607", fetch=fetch)["t"][0]) == _utc(2026, 7, 20)


def test_an_unreadable_daily_record_holds_the_backfill_but_only_for_twelve_hours(world,
                                                                                 monkeypatch):
    """M7: the daily side holds off an unreadable backfill record; the backfill now does the same
    for an unreadable daily record, bounded the same way."""
    bad = world.tmp / "costs_daily.json"
    bad.write_text("{not json", encoding="utf-8")
    now = _utc(2026, 10, 27, 12)
    os.utime(bad, (now - 3600, now - 3600))
    monkeypatch.setattr(costs_daily, "STATE", bad)
    monkeypatch.setattr(costs_daily, "read_strict", _strict_of(bad))
    st = {}
    why = vcv.clash(["2026-10-08"], now, st)
    assert "could not be read" in why and "at most 12 hours" in why
    assert st["daily_unreadable_since"] == now
    with pytest.raises(RuntimeError, match="the daily costs job's record .* could not be read"):
        vcv.backfill("pilot", now=now, force=True, listings=_listings(world.plan))
    assert vcv.read_state()["daily_unreadable_since"] == now, "kept for the next look"
    later = now + vcv.STALE_S + 60
    assert vcv.clash(["2026-10-08"], later, st) == ""
    assert "pressed without it" in st["daily_ignored"]


def _strict_of(path):
    def read():
        return json.loads(path.read_text(encoding="utf-8"))
    return read


def test_a_press_still_queued_past_twelve_hours_keeps_holding_until_github_settles_it(
        world, monkeypatch):
    """M8: settle used to give a press up at 12 hours while GitHub still had its run queued, and
    the daily job then pressed the same month files beside it."""
    now = _utc(2026, 10, 27, 12)
    vcv._write_state({"flight": {"at": now - 14 * 3600, "days": ["2026-10-08"], "part": None,
                                 "plan_id": "x", "coins": ["BTC_USDT"],
                                 "runs": [{"repo": "a/x", "run": 5, "coins": 1}], "unrun": []}})
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "queued"})
    got = vcv.settle(now=now)
    assert got["settled"] is False and "a/x run 5 is queued" in got["why"]
    assert "GitHub still says queued after 14 hours" in vcv.daily_held_off(["2026-10-09"], now)
    late = now - 14 * 3600 + vcv.AIR_MAX_S + 60
    assert vcv.daily_held_off(["2026-10-09"], late) == ""
    got = vcv.settle(now=late)
    assert got["settled"] and "never finished within 36 hours" in " ".join(got["red"])


def test_a_slow_daily_dispatch_keeps_saying_it_is_pressing_before_each_account(world, daily,
                                                                               monkeypatch):
    """M9: the daily `pressing` flag lasted 600 s from the press, and three accounts' syncs and
    dispatches can take longer, so a backfill could go out between them. Each account now says
    it again (`step_at`), with the runs started so far, through the REAL `_dispatch`."""
    from tradingagents.dataflows import gate_futures as gf

    monkeypatch.setattr(costs_daily, "_dispatch", REAL_DAILY_DISPATCH)
    monkeypatch.setattr(cs, "usable_fleets", lambda: (["a/x", "b/x", "c/x"], []))
    monkeypatch.setattr(cs, "sync_fleet", lambda slug: "")
    monkeypatch.setattr(gf, "trading_symbols", lambda: ["AAA_USDT", "BBB_USDT", "CCC_USDT"])
    seen = []

    def dispatch(wf, inputs, slug, since=None):
        seen.append(costs_daily.read()["pressing"])
        return 600 + len(seen)

    monkeypatch.setattr(fd, "dispatch", dispatch)
    now = _utc(2026, 10, 27, 3) + 300
    assert costs_daily.tick(now=now)["started"] is True
    assert [len(p["runs"]) for p in seen] == [0, 1, 2], "each account sees the runs so far"
    assert all(p["dispatching"] and p["step_at"] >= now for p in seen)
    # a pressing record whose press began long ago but whose newest step is fresh still holds
    rec = {"at": now - 2 * vcv.PRESSING_S, "step_at": now - 60, "dispatching": True,
           "runs": [{"repo": "a/x", "run": 601}]}
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed"})
    assert "a press being dispatched" in vcv.air_of(rec, now)
    assert vcv.air_of({**rec, "step_at": now - vcv.PRESSING_S - 1}, now) == ""


def test_a_verdict_carries_the_share_of_its_legs_that_paid_a_typical_cost(world):
    """I3 (the store's half): the older days over every setting the choice compared, the unseen
    days of the chosen setting - the same counting as the report."""
    from tradingagents import v3_families as vf

    fam, tf, filt = "v3_snap", "1h", "none"
    keys = [vf.setting_key(fam, x) for x in vf.FAMILIES[fam]["settings"]][:2]
    combos = {vf.combo_key(fam, keys[0], tf, filt): {"older": _walk(10, cost_unmeasured=10),
                                                     "unseen": _walk(4, cost_unmeasured=1)},
              vf.combo_key(fam, keys[1], tf, filt): {"older": _walk(30, cost_unmeasured=0,
                                                                    missed=2,
                                                                    placement_unmeasured=4),
                                                     "unseen": _walk(20, cost_unmeasured=2)}}
    rec = {"coin": "BTC_USDT", "combos": combos}
    v = {"family": fam, "tf": tf, "filter": filt, "setting": keys[1],
         "older": {keys[0]: {}, keys[1]: {}}}
    got = vcv.verdict_costs([rec], v)
    assert got["older"]["trades"] == 40 and got["older"]["legs"] == 80
    assert (got["older"]["typical_low"], got["older"]["typical_high"]) == (12, 14)
    assert got["unseen"]["legs"] == 40 and got["unseen"]["typical_low"] == 2
    assert "older days 15.0%-17.5% of 80 entries and exits" in got["words"]
    assert "unseen days 5.0% of 40 entries and exits" in got["words"]
    none = vcv.verdict_costs([rec], {**v, "setting": None})
    assert none["unseen"] is None and "unseen days no setting chosen" in none["words"]


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
    lst = _listings(plan)
    got = vcv.backfill("long", days_per_press=3, now=now, force=True, part="older", listings=lst)
    assert got["days"] == ["2026-07-25", "2026-07-26", "2026-07-27"], "the older range's newest"
    assert got["part"] == "older" and vcv.read_state()["flight"]["part"] == "older"
    assert sent[0]["days"] == "2026-07-25,2026-07-26,2026-07-27"
    # once the older range is filled the press says so instead of reaching into the other range
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed",
                                                             "conclusion": "success"})
    vcv.settle(now=now)
    for coin in plan["coins"]:
        _hold(world, coin, *vcv.missing_days(plan, [], part="older"))
    assert vcv.backfill("long", now=now, force=True, part="older",
                        listings=lst)["started"] is False
    assert vcv.backfill("long", days_per_press=2, now=now, force=True, part="unseen",
                        listings=lst)["days"] == ["2026-10-24", "2026-10-25"]


def test_the_costs_job_deals_to_every_account_the_backfill_presses_to():
    from tradingagents import cost_store

    assert cost_store.REPOS == ("jeremydevera/analyzer-x", "jeremydvera/analyzer-x",
                                "jeremydevera0903-gif/analyzer-x")
