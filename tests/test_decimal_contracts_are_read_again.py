"""The months stored before the decimal-contract fix are read again (Oct 30, 2026,
RCA-2026-10-30-F, the follow-up of RCA-2026-10-30-B).

RCA-2026-10-30-B fixed the replay for the 15 contracts Gate lets trade in tenths (ETH,
XRP, SOL ...): a crumb of float left on an emptied level crossed the book, and ETH read 1
of 60 minutes on Oct 08, 2026 07:00 UTC where the fixed replay reads 60. But the months
already stored kept their sparse readings - ETH's September holds 467 hours with only the
minute-0 reading - and the costs job skips any hour that holds ANY reading, so nothing
would ever read them again.

Every reading the replay packs now carries `rv`, the replay that made it (1: the one with
the dust cut; a month written before carries none, read as 0). An hour of a decimal
contract made by replay 0 is not held: the costs job reads it again and the v3 coverage
report counts it, labelled. BTC and the other whole-contract coins are never touched.
"""
from __future__ import annotations

import calendar
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tradingagents import book_history as bh, cost_store, costs_daily as cd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"


def _utc(y, m, d, h=0):
    return calendar.timegm((y, m, d, h, 0, 0))


D1 = _utc(2026, 9, 10)          # an ETH September day the old replay wrote


def _reading(t):
    r = {"t": t, "bid": 1.0, "ask": 1.01, "spread": 0.01, "buy": 0.0002, "sell": 0.0002,
         "exhausted": False, "source": "full", "at": bh.READ_AT_S}
    return r


def _old(packed):
    """A month as the old replay wrote it: no `rv` in the file at all."""
    return {k: v for k, v in packed.items() if k != "rv"}


def _sparse_day(d):
    """ETH's September shape: every hour holds only its minute-0 reading."""
    return bh.pack([_reading(d + 3600 * h) for h in range(24)])


def _full_day(d):
    return bh.pack([_reading(d + 3600 * h + 60 * m) for h in range(24) for m in range(60)])


# ------------------------------------------------------------------ the stamp


def test_the_list_is_gates_fifteen_decimal_contracts_and_btc_is_not_one():
    gates = frozenset({
        "ARIA_USDT", "BTW_USDT", "ESPORTS_USDT", "ETH_USDT", "LAB_USDT", "M_USDT",
        "PEPE_USDT", "RAVE_USDT", "RIVER_USDT", "SIREN_USDT", "SOL_USDT", "SOXS_USDT",
        "TRX_USDT", "UB_USDT", "XRP_USDT"})     # `enable_decimal`, Gate's list of Oct 30, 2026
    assert gates == bh.DECIMAL_CONTRACTS
    assert "BTC_USDT" not in bh.DECIMAL_CONTRACTS


def test_a_reading_carries_the_replay_that_made_it_and_an_old_file_reads_as_replay_zero():
    packed = bh.pack([_reading(D1), _reading(D1 + 60)])
    assert packed["rv"].tolist() == [bh.REPLAY_VERSION] * 2 and bh.REPLAY_VERSION >= 1
    back = cost_store.from_bytes(cost_store.to_bytes(packed))
    assert back["rv"].tolist() == [bh.REPLAY_VERSION] * 2, "the stamp survives the file"
    buf = io.BytesIO()
    np.savez_compressed(buf, **_old(packed))                  # a file written before the stamp
    old = cost_store.from_bytes(buf.getvalue())
    assert old["rv"].tolist() == [0, 0]
    assert cost_store.empty()["rv"].dtype == np.int8


def test_a_new_reading_beats_an_old_one_of_the_same_minute_whichever_file_is_later():
    """The deal moves coins between accounts: the re-read lands on one account while the
    other still holds the old month, and a reader merges them in a fixed order."""
    new = bh.pack([_reading(D1)])
    new["bid"] = np.array([2.0])
    old = _old(bh.pack([_reading(D1)]))
    assert cost_store.merge(new, old)["bid"].tolist() == [2.0]
    assert cost_store.merge(old, new)["bid"].tolist() == [2.0]


# ------------------------------------------------------------------ the costs job


@pytest.fixture
def shard(monkeypatch, tmp_path):
    for k in ("GITHUB_TOKEN", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DAYS_LIST", "2026-09-10")
    monkeypatch.setenv("COIN_LIST", "ETH_USDT,BTC_USDT")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("costs_shard_reread",
                                                  SCRIPTS / "costs_shard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("costs_shard_reread", None)


def test_an_old_sparse_hour_of_a_decimal_contract_is_due_and_a_new_one_is_held(shard):
    old = _old(_sparse_day(D1))
    assert shard.held_hours(old, "ETH_USDT") == set(), \
        "ETH's minute-0-only hour from the old replay is read again"
    assert shard.held_hours(_sparse_day(D1), "ETH_USDT") == {D1 + 3600 * h for h in range(24)}, \
        "the same hour written by the new replay is held, however few its readings"
    assert shard.held_hours(old, "BTC_USDT") == {D1 + 3600 * h for h in range(24)}, \
        "BTC trades whole contracts: its old hours are never due"
    assert shard.held_days(old, "BTC_USDT") == {D1} and shard.held_days(old, "ETH_USDT") == set()


def test_the_shard_reads_an_old_eth_day_again_and_leaves_btc_alone(shard, monkeypatch):
    replayed, uploaded = [], {}
    monkeypatch.setattr(shard.cs, "load_month", lambda sym, ym, **k: _old(_sparse_day(D1)))
    monkeypatch.setattr(shard.fx, "contract_spec", lambda sym: {"contractSize": 0.01})

    def day_readings(sym, d, hours=None, **k):
        replayed.append((sym, d, len(hours)))
        return {**_full_day(d), "hours_read": len(hours)}

    monkeypatch.setattr(shard.bh, "day_readings", day_readings)
    monkeypatch.setattr(shard, "upload", lambda path, tag: uploaded.setdefault(
        path.name, shard.cs.from_bytes(path.read_bytes())) is not None)
    assert shard.main() == 0
    assert replayed == [("ETH_USDT", D1, 24)], "only ETH's 24 old hours, never BTC's"
    got = uploaded["ETH_USDT-202609.npz"]
    assert len(got["t"]) == 24 * 60 and set(got["rv"].tolist()) == {bh.REPLAY_VERSION}, \
        "each old hour is replaced whole by the new replay's sixty minutes"


# ------------------------------------------------------------------ the v3 coverage report


@pytest.fixture()
def world(monkeypatch, tmp_path):
    from tradingagents import v3_cloud as vc, v3_coverage as vcv, v3_universe as vu

    monkeypatch.setattr(vc, "home", lambda: tmp_path / "cloud")
    (tmp_path / "cloud").mkdir()
    plan = {"version": vu.VERSION, "start_ms": _utc(2026, 10, 1) * 1000,
            "end_ms": _utc(2026, 10, 4) * 1000, "coins": ["BTC_USDT", "ETH_USDT"]}
    plan["id"] = vu.plan_id(plan)
    path = vu.save(plan, tmp_path / "plan.json")
    monkeypatch.setattr(vcv, "state_path", lambda: tmp_path / "cloud" / "backfill.json")
    monkeypatch.setattr(cd, "read", lambda: {})
    monkeypatch.setattr(cd, "read_strict", lambda: {})
    store = {}
    for coin in plan["coins"]:                   # every day held the OLD way, by both coins
        store[(coin, "202610")] = _old(bh.pack(
            [_reading(_utc(2026, 10, d) + 3600 * h) for d in (1, 2, 3) for h in range(24)]))
    monkeypatch.setattr(cost_store, "load_month", lambda sym, ym, **k: store.get((sym, ym)))
    monkeypatch.setattr(bh, "newest_published_hour",
                        lambda now=None, **k: int(now) - int(now) % 3600 - 2 * 3600)
    listings = {c: _utc(2025, 1, 1) * 1000 for c in plan["coins"]}
    return SimpleNamespace(plan=plan, path=path, store=store, listings=listings, vcv=vcv)


def test_the_store_names_the_days_to_read_again_for_the_decimal_contracts_only(world):
    got = world.vcv.store_days(world.plan["coins"], _utc(2026, 10, 1), _utc(2026, 10, 4))
    assert got["by_coin"]["BTC_USDT"] == {"2026-10-01", "2026-10-02", "2026-10-03"}
    assert got["by_coin"]["ETH_USDT"] == set()
    assert got["reread"] == {"ETH_USDT": {"2026-10-01", "2026-10-02", "2026-10-03"}}
    packed = world.store[("ETH_USDT", "202610")]
    assert world.vcv.held_days_of(packed, "ETH_USDT") == set()
    assert world.vcv.held_days_of(packed) == {"2026-10-01", "2026-10-02", "2026-10-03"}, \
        "no coin named: the old rule (every existing caller's shape)"


def test_the_report_counts_them_apart_with_their_own_label(world):
    lines = world.vcv.report(plan_path=world.path, listings=world.listings)
    gap = next(ln for ln in lines if "lack a reading" in ln)
    assert "3 coin-days missing" in gap
    assert "3 coin-day(s) to re-read after the decimal-contract fix" in gap
    assert "3 of them can be filled now" in gap


def test_the_backfill_presses_them_once_after_the_fix_never_again(world, monkeypatch):
    from tradingagents import cloud_sweep as cs, forecast_v2_daily as fd

    vcv = world.vcv
    # a green press BEFORE the fix already asked for ETH's days: it read them the old way
    vcv._write_state({"presses": [{"days": ["2026-10-01", "2026-10-02", "2026-10-03"],
                                   "coins": ["ETH_USDT"], "runs": []}]})
    sent = []
    monkeypatch.setattr(cs, "usable_fleets", lambda: (["a/x"], []))
    monkeypatch.setattr(cs, "sync_fleet", lambda slug: "")
    monkeypatch.setattr(fd, "dispatch", lambda wf, inputs, slug, since=None:
                        sent.append(dict(inputs)) or 901)
    now = _utc(2026, 11, 2, 12)
    got = vcv.backfill(plan_path=world.path, now=now, force=True, listings=world.listings)
    assert got["days"] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert got["coins"] == ["ETH_USDT"] and sent[0]["coin_list"] == "ETH_USDT"
    monkeypatch.setattr(fd, "run_status", lambda run, repo: {"status": "completed",
                                                             "conclusion": "success"})
    vcv.settle(now=now)
    assert vcv.read_state()["presses"][-1]["replay"] == bh.REPLAY_VERSION
    # the store still lacks them (say Gate's files did not complete them): a press made
    # with the fixed replay asked, so they are never asked again
    got = vcv.backfill(plan_path=world.path, now=now, force=True, listings=world.listings)
    assert got["started"] is False
    lines = vcv.report(plan_path=world.path, listings=world.listings)
    gap = next(ln for ln in lines if "lack a reading" in ln)
    assert "re-read after the decimal-contract fix" not in gap
    assert "3 of them a finished green backfill press already asked for" in gap


# ------------------------------------------------------------------ the daily costs job

AFTER = _utc(2026, 11, 2, 5)
# RCA-2026-10-30-A's one-time repair already ran on this state
REPAIRED = {cd.REPAIR_KEY: {"at": 0, "before": 0, "after": 0, "removed": []}}


@pytest.fixture
def daily(monkeypatch, tmp_path):
    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.setattr(cd, "_under_pytest", lambda: False)
    monkeypatch.setattr(cd, "STATE", tmp_path / "costs_daily.json")
    from tradingagents import cloud_sweep as cs, forecast_v2_daily as f2d, v3_coverage as vcv
    from tradingagents.dataflows import gate_futures as gf

    monkeypatch.setattr(vcv, "state_path", lambda: tmp_path / "backfill.json")
    monkeypatch.setattr(bh, "newest_published_hour",
                        lambda now=None, **k: int(now) - int(now) % 3600 - 2 * 3600)
    monkeypatch.setattr(gf, "trading_symbols", lambda: ["ETH_USDT", "BTC_USDT"])
    monkeypatch.setattr(cs, "usable_fleets", lambda cwd=None: (["me/r"], []))
    monkeypatch.setattr(cs, "sync_fleet", lambda slug, source="": "")
    calls = {"dispatch": [], "status": {}}

    def dispatch(wf, inputs, repo, since=None):
        calls["dispatch"].append(dict(inputs))
        return 1000 + len(calls["dispatch"])

    monkeypatch.setattr(f2d, "dispatch", dispatch)
    monkeypatch.setattr(f2d, "run_status",
                        lambda rid, repo: calls["status"].get(rid, {"status": "in_progress"}))
    return calls


def test_the_daily_job_presses_its_done_days_again_once_after_the_fix(daily, capsys):
    done = cd.wanted_days(AFTER, [])[:-1]
    cd._write({"read_at_s": bh.READ_AT_S, "done_days": done, **REPAIRED})
    got = cd.tick(now=AFTER)
    st = cd.read()
    assert st[cd.REREAD_KEY]["before"] == len(done) == cd.BACKFILL_DAYS - 1
    assert st["done_days"] == [] and got["started"]
    assert len(got["days"]) == cd.MAX_DAYS_PER_PRESS, "a week a press, never the whole window"
    assert "decimal-contract fix" in capsys.readouterr().out
    assert list(cd.STATE.parent.glob("costs_daily.json.*.bak")), "the file is copied first"
    # green: those days are done, and the re-read is never started over
    daily["status"][1001] = {"status": "completed", "conclusion": "success"}
    cd.tick(now=AFTER + 600)
    assert set(got["days"]) <= set(cd.read()["done_days"])
    cd.tick(now=AFTER + 1200)
    assert set(got["days"]) <= set(cd.read()["done_days"])


def test_before_the_fix_the_daily_job_changes_nothing(daily):
    now = cd.REPLAY_FIXED_AT - 3600
    done = cd.wanted_days(now, [])[:-1]
    cd._write({"read_at_s": bh.READ_AT_S, "done_days": done, **REPAIRED})
    cd.tick(now=now)
    assert cd.read()["done_days"] == done and cd.REREAD_KEY not in cd.read()


def test_a_run_pressed_before_the_fix_never_marks_its_days_done_after_it(daily):
    day = cd.wanted_days(AFTER, [])[-1]
    cd._write({"read_at_s": bh.READ_AT_S, "done_days": [], **REPAIRED,
               cd.REREAD_KEY: {"at": AFTER - 60, "before": 0},
               "flight": {"at": cd.REPLAY_FIXED_AT - 600, "days": [day],
                          "runs": [{"repo": "me/r", "run": 7}], "read_at_s": bh.READ_AT_S,
                          "gate_newest": AFTER}})
    daily["status"][7] = {"status": "completed", "conclusion": "success"}
    cd.tick(now=AFTER)
    st = cd.read()
    assert day not in st["done_days"]
    assert "decimal-contract fix" in json.dumps(st)
