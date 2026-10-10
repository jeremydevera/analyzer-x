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


def test_an_account_that_never_ran_leaves_its_days_undone_and_named(env, monkeypatch):
    """Final review, Oct 10, 2026 (RCA-2026-10-10-F): `sync_fleet` refused
    one account, its pile never ran, the other account's run went green — and
    all 30 days were marked done with the refusal wiped, so ~514 coins would
    never have been asked for again."""
    from tradingagents import cloud_sweep as cs

    monkeypatch.setattr(cs, "sync_fleet",
                        lambda slug, source="": "you/r is 3 commits behind" if slug == "you/r" else "")
    cd.tick(now=NOW)
    assert len(env["dispatch"]) == 1
    env["status"][1001] = {"status": "completed", "conclusion": "success"}
    cd.tick(now=NOW + 600)
    st = cd.read()
    assert st.get("done_days", []) == [], "half the market was never measured"
    assert "you/r" in st.get("last_error", "")


def test_repeated_red_runs_back_off_instead_of_pressing_every_half_hour(env):
    """One bad hour file failed the same coin on every run; a red run was
    pressed again 30 minutes after it STARTED, for ever. Each red in a row
    doubles the wait from the press (30 min, 1 h, 2 h ... 8 h), named; a run
    that took six hours to go red is pressed again at once, as before."""
    cd.tick(now=NOW)                                        # 1001, 1002
    for r in (1001, 1002):
        env["status"][r] = {"status": "completed", "conclusion": "failure"}
    cd.tick(now=NOW + 600)                                  # red #1
    assert cd.read()["reds"] == 1
    second = NOW + cd.RETRY_S + 1
    assert cd.tick(now=second).get("started") is True       # 1003, 1004
    for r in (1003, 1004):
        env["status"][r] = {"status": "completed", "conclusion": "failure"}
    got = cd.tick(now=second + cd.RETRY_S + 60)             # red #2: waits 1 h
    assert cd.read()["reds"] == 2
    assert not got.get("started") and "red" in got["why"], got
    assert cd.tick(now=second + 2 * cd.RETRY_S + 1).get("started") is True
    for r in (1005, 1006):
        env["status"][r] = {"status": "completed", "conclusion": "success"}
    cd.tick(now=second + 3 * cd.RETRY_S)
    assert cd.read()["reds"] == 0, "a green run clears the count"


def test_today_so_far_is_pressed_once_after_seven_and_never_marked_done(env):
    """The v2 backtest goes out around 08:30 UTC; with only finished days
    measured, its newest ~8 hours had no recorded book — the hours the 1-day
    rooms switch on by (final review, RCA-2026-10-10-H). At 07:00 UTC the
    press adds today so far; today is never marked done, so tomorrow's 03:00
    press reads the rest of it."""
    import time as _t

    day = lambda t: _t.strftime("%Y-%m-%d", _t.gmtime(t))
    cd.tick(now=NOW)                                       # 05:00 — the backfill
    assert day(NOW) not in env["dispatch"][-1][1]["days"].split(",")
    env["status"][1001] = env["status"][1002] = {"status": "completed",
                                                 "conclusion": "success"}
    cd.tick(now=NOW + 600)
    seven = NOW + 2 * 3600 + 60                            # 07:01
    got = cd.tick(now=seven)
    assert got.get("started") is True
    assert env["dispatch"][-1][1]["days"].split(",") == [day(NOW)]
    env["status"][1003] = env["status"][1004] = {"status": "completed",
                                                 "conclusion": "success"}
    cd.tick(now=seven + 600)
    st = cd.read()
    assert day(NOW) not in st["done_days"] and st["today_pressed"] == day(NOW)
    n = len(env["dispatch"])
    cd.tick(now=seven + 3 * 3600)
    assert len(env["dispatch"]) == n, "once a day"
    nxt = NOW + 86400 - 2 * 3600                           # tomorrow 03:00
    cd.tick(now=nxt)
    assert day(NOW) in env["dispatch"][-1][1]["days"].split(","), \
        "yesterday's rest is read the next morning"
