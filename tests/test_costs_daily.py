"""The daily costs job is pressed by the PC, across both accounts (phase 4,
Oct 10, 2026; CLAUDE.md: every GitHub job uses all 40 machines).

Once a UTC day, after Gate has published the day's last order-book hour (~2 h
after it ends), the PC deals Gate's coins between the two accounts and starts
`costs.yml` on each for every day still missing from the last 30. A day is
done only when EVERY account's run finished green; a red or missing share
leaves its days to the next press, named.
"""
import calendar

import pytest

from tradingagents import costs_daily as cd

NOW = calendar.timegm((2026, 10, 10, 5, 0, 0))        # 5am UTC


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.setattr(cd, "_under_pytest", lambda: False)
    monkeypatch.setattr(cd, "STATE", tmp_path / "costs_daily.json")
    from tradingagents import cloud_sweep as cs, forecast_v2_daily as f2d
    from tradingagents.dataflows import gate_futures as gf

    monkeypatch.setattr(gf, "trading_symbols", lambda: [f"C{i}_USDT" for i in range(6)])
    monkeypatch.setattr(cs, "usable_fleets", lambda cwd=None: (["me/r", "you/r"], []))
    monkeypatch.setattr(cs, "sync_fleet", lambda slug, source="": "")
    calls = {"dispatch": [], "status": {}}

    def dispatch(wf, inputs, repo, since=None):
        calls["dispatch"].append((wf, dict(inputs), repo))
        return 1000 + len(calls["dispatch"])
    monkeypatch.setattr(f2d, "dispatch", dispatch)
    monkeypatch.setattr(f2d, "run_status",
                        lambda rid, repo: calls["status"].get(rid, {"status": "in_progress"}))
    return calls


def test_it_waits_for_the_days_last_hour_to_be_published(env):
    got = cd.tick(now=calendar.timegm((2026, 10, 10, 1, 30, 0)))
    assert not env["dispatch"] and "after" in got["why"]


def test_one_press_deals_every_coin_once_across_both_accounts(env):
    got = cd.tick(now=NOW)
    assert got["started"]
    (wf1, in1, r1), (wf2, in2, r2) = env["dispatch"]
    assert wf1 == wf2 == "costs.yml" and {r1, r2} == {"me/r", "you/r"}
    c1, c2 = set(in1["coin_list"].split(",")), set(in2["coin_list"].split(","))
    assert not c1 & c2 and c1 | c2 == {f"C{i}_USDT" for i in range(6)}
    days = in1["days"].split(",")
    assert days[-1] == "2026-10-09" and len(days) == cd.BACKFILL_DAYS
    assert in1["shards"] == "20"


def test_days_are_done_only_when_every_share_is_green(env):
    cd.tick(now=NOW)
    env["status"][1001] = {"status": "completed", "conclusion": "success"}
    assert cd.tick(now=NOW + 600).get("started") is not True
    assert cd.read().get("done_days", []) == [], "one share still running"
    env["status"][1002] = {"status": "completed", "conclusion": "failure"}
    got = cd.tick(now=NOW + 1200)
    assert cd.read().get("done_days", []) == []
    assert "you/r" in cd.read().get("last_error", "") or "me/r" in cd.read().get("last_error", "")
    # the next press asks again for the same days
    assert got.get("started") is True or cd.tick(now=NOW + 1800 + cd.RETRY_S).get("started")


def test_a_green_day_is_never_asked_again(env):
    cd.tick(now=NOW)
    env["status"][1001] = {"status": "completed", "conclusion": "success"}
    env["status"][1002] = {"status": "completed", "conclusion": "success"}
    cd.tick(now=NOW + 600)
    assert "2026-10-09" in cd.read()["done_days"]
    n = len(env["dispatch"])
    cd.tick(now=NOW + 3600)
    assert len(env["dispatch"]) == n, "nothing left to do today"


def test_under_mexc_it_does_nothing(env, monkeypatch):
    monkeypatch.setenv("TA_VENUE", "mexc")
    assert not cd.tick(now=NOW).get("started") and not env["dispatch"]


def test_never_under_pytest(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "x")
    assert cd.tick(now=NOW) == {"started": False, "why": "never under pytest"}
