"""An order-book hour Gate has not published YET is never booked as done
(Oct 30, 2026, RCA-2026-10-30-A).

Gate published no order-book file after Oct 22, 2026 04:00 UTC (8 days by
Oct 30). The costs shard booked every 404 as "never published, final", every
run ended green, and both bookkeepers - the daily costs job's `done_days` and
the v3 backfill's `presses` - recorded Oct 22-29 as done for ever, so neither
would ask for them once Gate published. The v3 backfill pressed the NEWEST
missing days first, spent its 30-day press on those 8 days and 22 days missing
for 1-4 coins, and left Aug 01-15 (221 coins, 3,315 coin-days Gate serves)
unpressed.

The rules held here:

* a 404 hour is FINAL only when a LATER hour of the same coin is published
  (Oct 08 06:00 UTC: 05 and 07 are there); one at the archive's end is "not
  published yet", said plainly, and the run is not failed for it;
* a day is marked done only when its last hour is at or before the newest hour
  Gate's archive holds, read BEFORE the press (`book_history.
  newest_published_hour`); an archive that cannot be read marks nothing done;
* the daily press and the v3 backfill never press a day after that hour; the
  backfill presses the OLDEST fillable days of its range;
* the coverage report says how many coin-days wait for Gate, how many a
  finished press already asked for, and how many can be filled now, each
  labelled, and the filling line names the subtraction.

Every candle and position here sits on ONE timeline, the UTC clock the
archive's file names use.
"""
from __future__ import annotations

import calendar
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tradingagents import book_history as bh

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
H = 3600


def _utc(y, m, d, h=0):
    return calendar.timegm((y, m, d, h, 0, 0))


# the archive as measured on Oct 30, 2026: last hour Oct 22 04:00 UTC, and
# Oct 08 06:00 UTC never published while 05 and 07 are
LAST = _utc(2026, 10, 22, 4)
HOLE = _utc(2026, 10, 8, 6)


def _published(h: int) -> bool:
    return h <= LAST and h != HOLE


# ----------------------------------------------------------- the archive probe
def test_the_newest_published_hour_is_found_across_a_week_long_silence_and_a_hole():
    asked = []

    def probe(url):
        asked.append(url)
        # .../202610/BTC_USDT-2026102204.csv.gz -> the hour
        stamp = url.rsplit("-", 1)[1][:10]
        h = calendar.timegm((int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]),
                             int(stamp[8:10]), 0, 0))
        return 200 if _published(h) else 404

    now = _utc(2026, 10, 30, 18) + 1234
    assert bh.newest_published_hour(now, probe=probe) == LAST
    assert len(asked) < 40, f"a cheap probe, not an hour-by-hour walk: {len(asked)} asks"
    # the newest hour right AFTER the hole is found too (a hole is not the end)
    assert bh.newest_published_hour(HOLE + 2 * H + 60, probe=probe) == HOLE + H
    # every hour published up to the last finished one
    assert bh.newest_published_hour(_utc(2026, 10, 9, 10) + 5,
                                    probe=lambda u: 200) == _utc(2026, 10, 9, 9)


def test_an_archive_that_cannot_be_read_is_unknown_never_a_date():
    with pytest.raises(RuntimeError, match="503"):
        bh.newest_published_hour(_utc(2026, 10, 30, 18), probe=lambda u: 503)
    assert bh.newest_published_hour(_utc(2026, 10, 30, 18), probe=lambda u: 404,
                                    back_hours=48) is None


def test_a_day_is_published_only_when_its_last_hour_is():
    assert bh.day_published("2026-10-21", LAST)
    assert not bh.day_published("2026-10-22", LAST), "hours 05-23 are not out yet"
    assert not bh.day_published("2026-10-29", LAST)
    assert not bh.day_published("2026-10-21", None), "unknown is never published"


# ------------------------------------------------------------------ the shard
@pytest.fixture
def shard(monkeypatch, tmp_path):
    for k in ("GITHUB_TOKEN", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("COIN_LIST", "BTC_USDT")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("costs_shard_wait",
                                                  SCRIPTS / "costs_shard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_now", lambda: _utc(2026, 10, 30, 18))
    monkeypatch.setattr(mod.cs, "load_month", lambda *a, **k: None)
    monkeypatch.setattr(mod.fx, "contract_spec", lambda sym: {"contractSize": 0.0001})
    monkeypatch.setattr(mod, "upload", lambda path, tag: True)

    def day_readings(sym, d, hours=None, **k):
        hrs = list(hours) if hours is not None else [d + H * h for h in range(24)]
        got = [h for h in hrs if _published(h)]
        rows = [{"t": h + 60, "bid": 1.0, "ask": 1.0, "spread": 1e-4, "buy": 2e-4,
                 "sell": 2e-4, "exhausted": False, "source": "full", "at": bh.READ_AT_S}
                for h in got]
        return {**bh.pack(rows), "hours_read": len(got),
                "hours_missing": [h for h in hrs if not _published(h)],
                "hours_failed": [], "hours_bad": []}

    monkeypatch.setattr(mod.bh, "day_readings", day_readings)
    yield mod
    sys.modules.pop("costs_shard_wait", None)


def test_a_404_at_the_archives_end_is_not_yet_published_and_said_so(shard, monkeypatch,
                                                                     capsys):
    monkeypatch.setenv("DAYS_LIST", "2026-10-21,2026-10-22,2026-10-23")
    assert shard.main() == 0, "days that simply are not out yet never fail the run"
    out = capsys.readouterr().out
    assert "not published by Gate yet" in out
    assert "BTC_USDT: Gate has published no order-book hour after" in out
    assert "2 day(s) wait for it" in out, out
    assert "never published" not in out, "the end of the archive is not a hole"
    assert "Gate has published no order book after" in out and "1 coin(s)" in out


def test_a_404_with_a_later_hour_published_is_final(shard, monkeypatch, capsys):
    monkeypatch.setenv("DAYS_LIST", "2026-10-08")
    assert shard.main() == 0
    out = capsys.readouterr().out
    assert "BTC_USDT 2026-10-08 hour 06: Gate never published it" in out, out
    assert "not published by Gate yet" not in out
    assert "wait for it" not in out


# -------------------------------------------------------- the daily costs job
@pytest.fixture
def daily(monkeypatch, tmp_path):
    from tradingagents import cloud_sweep as cs, costs_daily as cd, forecast_v2_daily as f2d
    from tradingagents.dataflows import gate_futures as gf

    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.setattr(cd, "_under_pytest", lambda: False)
    monkeypatch.setattr(cd, "STATE", tmp_path / "costs_daily.json")
    monkeypatch.setattr(gf, "trading_symbols", lambda: ["BTC_USDT", "ETH_USDT"])
    monkeypatch.setattr(cs, "usable_fleets", lambda cwd=None: (["me/r"], []))
    monkeypatch.setattr(cs, "sync_fleet", lambda slug, source="": "")
    monkeypatch.setattr(cd, "TODAY_HOUR_UTC", 24)
    from tradingagents import v3_coverage as vcv

    monkeypatch.setattr(vcv, "daily_held_off", lambda days, now: "")
    calls = {"dispatch": [], "status": {}, "probe": [LAST]}

    def dispatch(wf, inputs, repo, since=None):
        calls["dispatch"].append(inputs["days"].split(","))
        return 1000 + len(calls["dispatch"])

    monkeypatch.setattr(f2d, "dispatch", dispatch)
    monkeypatch.setattr(f2d, "run_status",
                        lambda rid, repo: calls["status"].get(rid, {"status": "in_progress"}))

    def newest(now=None, **k):
        v = calls["probe"][0]
        if isinstance(v, Exception):
            raise v
        return v

    monkeypatch.setattr(bh, "newest_published_hour", newest)
    return SimpleNamespace(cd=cd, calls=calls)


NOW = _utc(2026, 10, 30, 5)


def test_the_daily_press_never_asks_for_a_day_gate_has_not_published(daily):
    cd = daily.cd
    cd._write({"read_at_s": bh.READ_AT_S,
               "done_days": [d for d in cd.wanted_days(NOW, []) if d < "2026-10-15"]})
    got = cd.tick(now=NOW)
    assert got["started"], got
    assert daily.calls["dispatch"][0] == [f"2026-10-{d}" for d in range(15, 22)], \
        "the newest PUBLISHED week, never Oct 22-29"
    daily.calls["status"][1001] = {"status": "completed", "conclusion": "success"}
    got = cd.tick(now=NOW + cd.RETRY_S + 60)
    st = cd.read()
    assert "2026-10-21" in st["done_days"] and "2026-10-22" not in st["done_days"]
    assert not got.get("started")
    assert "Gate has published no order book after" in got["why"], got
    assert "8 day(s) wait for it" in got["why"], got
    assert st["reds"] == 0, "waiting for Gate is not a red run"


def test_a_green_run_marks_done_only_the_days_published_when_it_was_pressed(daily):
    """A day pressed while Gate had not published it - a flight from before this rule, or the
    hour Gate publishes between the probe and the settle - is never marked done: the shards
    asked for it while it was not there."""
    cd = daily.cd
    cd._write({"read_at_s": bh.READ_AT_S, "done_days": [],
               "flight": {"at": NOW - 600, "days": ["2026-10-21", "2026-10-22", "2026-10-23"],
                          "runs": [{"repo": "me/r", "run": 7}], "unrun": [],
                          "today": None, "read_at_s": bh.READ_AT_S, "gate_newest": LAST}})
    daily.calls["status"][7] = {"status": "completed", "conclusion": "success"}
    daily.calls["probe"][0] = _utc(2026, 10, 29, 12)    # Gate published since the press
    cd._settle(st := cd.read(), NOW)
    assert st["done_days"] == ["2026-10-21"]
    assert "2 day(s) wait for it" in st["last_error"]
    assert st["reds"] == 0


def test_an_archive_that_cannot_be_read_holds_the_press_and_marks_nothing_done(daily):
    cd = daily.cd
    daily.calls["probe"][0] = RuntimeError("download.gatedata.org answered 503")
    got = cd.tick(now=NOW)
    assert not got["started"] and "503" in got["why"] and not daily.calls["dispatch"]
    # a flight from before the rule has no probe of its own: settled while the archive cannot
    # be read, its days stay undone
    cd._write({"read_at_s": bh.READ_AT_S, "done_days": [],
               "flight": {"at": NOW - 600, "days": ["2026-10-20"],
                          "runs": [{"repo": "me/r", "run": 8}], "unrun": [], "today": None,
                          "read_at_s": bh.READ_AT_S}})
    daily.calls["status"][8] = {"status": "completed", "conclusion": "success"}
    st = cd.read()
    cd._settle(st, NOW)
    assert st.get("done_days") == [] and "503" in st["last_error"]


def test_the_probe_is_asked_at_most_every_half_hour(daily, monkeypatch):
    cd = daily.cd
    n = []

    def newest(now=None, **k):
        n.append(now)
        return LAST

    monkeypatch.setattr(bh, "newest_published_hour", newest)
    cd._write({"read_at_s": bh.READ_AT_S,
               "done_days": [d for d in cd.wanted_days(NOW, []) if d < "2026-10-22"]})
    for k in range(10):
        cd.tick(now=NOW + 30 * k)
    assert len(n) == 1, "the supervisor ticks every 30 s; the archive is asked once"
    cd.tick(now=NOW + cd.PROBE_EVERY_S + 1)
    assert len(n) == 2


# ------------------------------------------------------------- the v3 backfill
@pytest.fixture
def world(monkeypatch, tmp_path):
    import numpy as np

    from tradingagents import (
        cloud_sweep as cs,
        cost_store,
        costs_daily,
        forecast_v2_daily as fd,
        v3_cloud as vc,
        v3_coverage as vcv,
        v3_universe as vu,
    )

    monkeypatch.setattr(vc, "home", lambda: tmp_path / "cloud")
    (tmp_path / "cloud").mkdir()
    # the unseen range of the real plan in small: Aug 01 - Oct 29, 2026, three coins
    plan = {"version": vu.VERSION, "start_ms": _utc(2026, 8, 1) * 1000,
            "end_ms": _utc(2026, 10, 30) * 1000,
            "coins": ["BTC_USDT", "ETH_USDT", "SOL_USDT"]}
    plan["id"] = vu.plan_id(plan)
    path = vu.save(plan, tmp_path / "plan.json")
    monkeypatch.setattr(vcv, "state_path", lambda: tmp_path / "cloud" / "backfill.json")
    monkeypatch.setattr(costs_daily, "read_strict", lambda: {})
    monkeypatch.setattr("tradingagents.v3_measure.windows",
                        lambda p: (p["start_ms"], p["start_ms"], p["end_ms"]))
    # the store holds Aug 16 - Oct 21 for every coin, but Oct 08 (Gate's hole) and Sep 10 for
    # ETH (a replay that gave too few readings)
    store = {}
    for coin in plan["coins"]:
        for t0 in range(_utc(2026, 8, 16), _utc(2026, 10, 22), 86400):
            if t0 == _utc(2026, 10, 8) or (coin == "ETH_USDT" and t0 == _utc(2026, 9, 10)):
                continue
            g = __import__("time").gmtime(t0)
            key = (coin, f"{g.tm_year:04d}{g.tm_mon:02d}")
            t = np.array([t0 + H * h + bh.READ_AT_S for h in range(24)], "int64")
            old = store.get(key)
            store[key] = {"t": t if old is None else np.concatenate([old["t"], t])}
    for v in store.values():
        v["at"] = np.full(len(v["t"]), bh.READ_AT_S, "int8")
    monkeypatch.setattr(cost_store, "load_month", lambda sym, ym, **k: store.get((sym, ym)))
    probe = [LAST]

    def newest(now=None, **k):
        if isinstance(probe[0], Exception):
            raise probe[0]
        return probe[0]

    monkeypatch.setattr(bh, "newest_published_hour", newest)
    sent = []
    monkeypatch.setattr(cs, "usable_fleets", lambda: (["a/x"], []))
    monkeypatch.setattr(cs, "sync_fleet", lambda slug: "")
    monkeypatch.setattr(fd, "dispatch", lambda wf, inputs, slug, since=None:
                        sent.append(dict(inputs)) or 900 + len(sent))
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed",
                                                             "conclusion": "success"})
    return SimpleNamespace(vcv=vcv, plan=plan, path=path, sent=sent, probe=probe,
                           lst=dict.fromkeys(plan["coins"], 0))


def test_the_backfill_presses_the_fillable_oldest_days_never_the_unpublished(world):
    vcv = world.vcv
    now = _utc(2026, 10, 30, 18)
    got = vcv.backfill(plan_path=world.path, days_per_press=30, now=now, force=True,
                       part="unseen", listings=world.lst)
    assert got["days"][:15] == [f"2026-08-{d:02d}" for d in range(1, 16)], got["days"]
    assert all(d < "2026-10-22" for d in got["days"]), "never a day Gate has not published"
    assert got["gate_newest"] == LAST
    assert world.sent[0]["days"].split(",") == got["days"]
    vcv.settle(now=now)
    press = vcv.read_state()["presses"][-1]
    assert not any(d >= "2026-10-22" for d in press["days"])


def test_a_backfill_that_cannot_read_the_archive_is_refused_by_name(world):
    world.probe[0] = RuntimeError("download.gatedata.org answered 503")
    with pytest.raises(RuntimeError, match="503"):
        world.vcv.backfill(plan_path=world.path, now=_utc(2026, 10, 30, 18), force=True,
                           part="unseen", listings=world.lst)
    assert not world.sent and not world.vcv.read_state().get("flight")


def test_a_settled_press_never_records_a_day_after_the_archives_end(world):
    """A flight pressed before this rule held Oct 22-29; settling it must not add them to the
    days a green press already asked for."""
    vcv = world.vcv
    now = _utc(2026, 10, 30, 18)
    vcv._write_state({"flight": {"at": now - 3600, "days": ["2026-10-21", "2026-10-22"],
                                 "coins": ["BTC_USDT"], "runs": [{"repo": "a/x", "run": 5}],
                                 "unrun": [], "part": "unseen"}})
    vcv.settle(now=now)
    assert vcv.read_state()["presses"][-1]["days"] == ["2026-10-21"]


def test_the_report_names_what_waits_for_gate_what_was_asked_and_what_can_be_filled(
        world, monkeypatch):
    vcv = world.vcv
    # a green press already asked for ETH's Sep 10 and every coin's Oct 08
    vcv._write_state({"presses": [{"days": ["2026-09-10", "2026-10-08"],
                                   "coins": world.plan["coins"], "runs": []}]})
    monkeypatch.setattr(vcv, "costs_speed", lambda runs: {"runs": 1, "machine_s": 3600,
                                                          "coin_days": 100,
                                                          "s_per_coin_day": 36.0,
                                                          "one_day_runs": 0})
    lines = vcv.report(plan_path=world.path, runs=[("a/x", 1)], machines=60,
                       listings=world.lst)
    text = "\n".join(lines)
    # missing: Aug 01-15 (45) + Oct 08 (3) + ETH Sep 10 (1) + Oct 22-29 (24) = 73
    assert "73 coin-days missing" in text, text
    assert "24 of them wait for Gate to publish them" in text, text
    assert "4 of them a finished green backfill press already asked for" in text, text
    assert "45 of them can be filled now" in text, text
    assert "Gate's archive holds no order-book hour after" in text
    assert "does not complete" not in text, "a cause is never claimed for every stuck day"
    fill = next(ln for ln in lines if "filling the unseen days'" in ln)
    assert "45 coin-days" in fill and "73 missing, less 24 waiting for Gate and 4 a " \
        "finished press already asked for" in fill, fill
    # an archive that cannot be read: the split is unknown, named, never guessed
    world.probe[0] = RuntimeError("answered 503")
    text = "\n".join(vcv.report(plan_path=world.path, listings=world.lst))
    assert "could not read which hours Gate's archive has published" in text, text


def test_the_repair_clears_only_the_days_after_the_archives_end(tmp_path):
    """The one-time repair of Oct 30, 2026 as code: the daily job's done days and the backfill's
    presses lose every day after the archive's newest hour - and nothing else - backed up first."""
    from tradingagents import costs_daily as cd

    daily = tmp_path / "costs_daily.json"
    back = tmp_path / "backfill.json"
    daily.write_text(json.dumps({"done_days": ["2026-10-08", "2026-10-21", "2026-10-22",
                                               "2026-10-29"], "reds": 0}), encoding="utf-8")
    back.write_text(json.dumps({"presses": [{"days": ["2026-09-22", "2026-10-08",
                                                      "2026-10-22", "2026-10-29"],
                                             "coins": ["BTC_USDT"], "runs": []}]}),
                    encoding="utf-8")
    got = cd.forget_unpublished(LAST, daily_path=daily, backfill_path=back, stamp="20261030")
    assert json.loads(daily.read_text())["done_days"] == ["2026-10-08", "2026-10-21"]
    assert json.loads(back.read_text())["presses"][0]["days"] == ["2026-09-22", "2026-10-08"]
    assert got["daily"] == {"before": 4, "after": 2, "removed": ["2026-10-22", "2026-10-29"]}
    assert got["backfill"]["before"] == 4 and got["backfill"]["after"] == 2
    assert (tmp_path / "costs_daily.json.20261030.bak").exists()
    assert (tmp_path / "backfill.json.20261030.bak").exists()


def test_the_daily_jobs_own_file_is_repaired_once_on_the_first_tick_of_this_code(daily, capsys):
    """The build running on Oct 30, 2026 would press Oct 22-29 again at once and mark them done
    again, so its file is repaired by the first tick of THIS code - backed up first, once, and
    every day after Oct 22, 2026 04:00 UTC that a build marked done meanwhile goes too."""
    cd = daily.cd
    done = [f"2026-10-{d:02d}" for d in range(15, 31)]
    cd._write({"read_at_s": bh.READ_AT_S, "done_days": done})
    cd.tick(now=NOW + 3600)
    st = cd.read()
    assert st["done_days"] == [f"2026-10-{d}" for d in range(15, 22)]
    assert st[cd.REPAIR_KEY]["before"] == 16 and st[cd.REPAIR_KEY]["after"] == 7
    assert st[cd.REPAIR_KEY]["removed"][0] == "2026-10-22"
    assert list(cd.STATE.parent.glob("costs_daily.json.*.bak")), "backed up first"
    assert "one-time repair" in capsys.readouterr().out
    # never again: a day marked done after the repair stays done
    st["done_days"] = st["done_days"] + ["2026-10-22"]
    cd._write(st)
    cd.tick(now=NOW + 7200)
    assert "2026-10-22" in cd.read()["done_days"]
