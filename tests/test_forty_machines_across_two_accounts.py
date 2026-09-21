"""One press, every GitHub account, no coin measured twice.

Operator, `Sep 21, 2026`: *"i want 40"*. A free GitHub account runs about 20
machines at once, so one press was capped at 20 however big the board was.
Their partner's fork (`jeremydvera/analyzer-x`) is a second 20, and this is
what makes the two add up instead of doing the same work twice:

* the coins are DEALT between the accounts, one at a time (the board is
  alphabetical and its weight is not spread evenly along it);
* an unnamed board is never split — each machine works the list out for
  itself, so two runs with no list would measure the same coins twice and
  call it forty machines;
* each account continues from ITS OWN saved positions, because a run id means
  nothing inside another repo;
* the collect asks the right GitHub for each run.
"""
from __future__ import annotations

import pytest

from tradingagents import cloud_sweep as cs

TWO = ["partner/analyzer-x", "mine/analyzer-x"]


@pytest.fixture
def sent(monkeypatch):
    """Record every dispatch instead of making one."""
    calls: list = []

    def fake(*, coin_list=(), shards=20, slug="", **kw):
        calls.append({"slug": slug, "coins": list(coin_list),
                      "shards": shards, **kw})
        return {"id": 1000 + len(calls), "url": f"https://x/{len(calls)}"}

    monkeypatch.setattr(cs, "dispatch", fake)
    return calls


# ------------------------------------------------------------- the dealing
def test_the_coins_are_dealt_not_cut_in_half():
    got = cs.split_coins(["A", "B", "C", "D", "E"], 2)
    assert got == [["A", "C", "E"], ["B", "D"]], got
    # every coin exactly once, whatever the pile count
    for parts in (1, 2, 3, 7):
        piles = cs.split_coins([f"C{i}" for i in range(20)], parts)
        flat = [c for p in piles for c in p]
        assert sorted(flat) == sorted(f"C{i}" for i in range(20))
        assert len(flat) == len(set(flat)), "a coin measured twice"


def test_two_accounts_each_get_half_the_board(sent):
    got = cs.dispatch_across(coin_list=[f"C{i}" for i in range(10)],
                             shards=20, fleet_list=TWO, timeframes="15m")
    assert [r["repo"] for r in got["runs"]] == TWO
    assert [len(c["coins"]) for c in sent] == [5, 5]
    assert set(sent[0]["coins"]) & set(sent[1]["coins"]) == set(), \
        "no coin is measured by both accounts"
    assert "2 accounts x 20 machines = 40" in got["why"], got["why"]


def test_one_account_is_exactly_what_it_always_was(sent):
    got = cs.dispatch_across(coin_list=["A", "B"], shards=20,
                             fleet_list=["mine/analyzer-x"], timeframes="15m")
    assert len(got["runs"]) == 1 and len(sent) == 1
    assert sent[0]["coins"] == ["A", "B"] and sent[0]["slug"] == "mine/analyzer-x"


def test_an_unnamed_board_is_never_split(sent):
    """Two runs with no coin list would measure the SAME coins twice."""
    got = cs.dispatch_across(coin_list=[], shards=20, fleet_list=TWO,
                             timeframes="15m")
    assert len(got["runs"]) == 1, got
    assert len(sent) == 1 and sent[0]["coins"] == []
    assert "same coins twice" in got["why"], got["why"]


def test_no_usable_account_is_a_named_refusal(monkeypatch):
    monkeypatch.setattr(cs, "usable_fleets",
                        lambda cwd=None: ([], ["a/b: no 'Market sweep' workflow"]))
    with pytest.raises(cs.CloudError) as err:
        cs.dispatch_across(coin_list=["A"], shards=20)
    assert "no GitHub account" in str(err.value) and "a/b" in str(err.value)


# --------------------------------------------- each fleet's own positions
def test_each_account_continues_from_its_own_runs(sent, monkeypatch, tmp_path):
    monkeypatch.setattr(cs, "STATE_RUNS_FILE", tmp_path / "state_runs.json")
    monkeypatch.setattr(cs, "fleets", lambda cwd=None: TWO)
    cs.record_state_run(777, ["15m"], slug="partner/analyzer-x")
    cs.record_state_run(888, ["15m"], slug="mine/analyzer-x")

    cs.dispatch_across(coin_list=["A", "B"], shards=20, fleet_list=TWO,
                       timeframes="15m", mode="update")
    by_slug = {c["slug"]: c.get("state_runs") for c in sent}
    assert by_slug["partner/analyzer-x"] == ["777"], by_slug
    assert by_slug["mine/analyzer-x"] == ["888"], by_slug


def test_a_record_written_before_accounts_existed_belongs_to_origin(
        monkeypatch, tmp_path):
    """Every run before Sep 21, 2026 went to `origin`, and its record has no
    repo — offering it to the fork would make the fork download nothing."""
    monkeypatch.setattr(cs, "STATE_RUNS_FILE", tmp_path / "state_runs.json")
    monkeypatch.setattr(cs, "fleets", lambda cwd=None: TWO)   # origin is LAST
    (tmp_path / "state_runs.json").write_text(
        '{"15m": [{"run": 4242, "at": 1789999999}]}', encoding="utf-8")
    import time as _t

    at = _t.time()
    assert cs.state_runs_for(["15m"], now=at, slug="mine/analyzer-x") == ["4242"]
    assert cs.state_runs_for(["15m"], now=at, slug="partner/analyzer-x") == []
    # and with no account named at all, nothing is filtered (the old answer)
    assert cs.state_runs_for(["15m"], now=at) == ["4242"]


# ----------------------------------------------------- landing them all
def test_the_collect_is_told_which_account_a_run_is_on():
    import inspect

    from tradingagents import cloud_autopilot as ca, db_jobs as dj

    src = inspect.getsource(ca.collect_finished)
    assert "cs.fleets()" in src, "every account's runs are considered"
    assert 'cs.artifact_names(rid, slug)' in src
    assert '"repo": slug' in src, "the collect job is told where to fetch from"
    job = inspect.getsource(dj._run_collect)
    assert 'spec.get("repo")' in job, "and it uses it"


def test_a_collected_run_records_its_positions_under_its_own_account():
    import inspect

    src = inspect.getsource(cs.collect_into_store)
    i = src.index("record_state_run(")
    assert "slug=slug or repo_slug()" in src[i:i + 200], src[i:i + 200]


def test_the_update_button_sends_the_stores_own_coin_list():
    """The split needs names; an UPDATE with no pick used to send nothing and
    could not be divided."""
    import inspect

    from tradingagents import db_jobs as dj

    src = inspect.getsource(dj._run_btupdate)
    assert "cs.dispatch_across(" in src
    assert "stored_symbols()" in src, "an unpicked UPDATE names the whole store"
    assert "_coins_for_cloud" in src


def test_the_collector_takes_the_accounts_in_turn(monkeypatch):
    """harddev round: asking every account on every look multiplies the calls
    to the endpoint whose secondary limit 403'd this project for hours
    (RCA-2026-09-02). A run takes twenty minutes; the looks take turns."""
    import time

    from tradingagents import cloud_autopilot as ca

    asked: list = []
    monkeypatch.setattr(cs, "fleets", lambda cwd=None: TWO)
    monkeypatch.setattr(cs, "_runs", lambda slug, limit=10: asked.append(slug) or [])
    monkeypatch.setattr(ca, "_write", lambda state: None)
    from tradingagents import db_jobs as dj
    monkeypatch.setattr(dj, "status", lambda kind: {"running": False})

    state, t = {}, time.time()
    for i in range(6):
        ca.collect_finished(now=t + i * ca.CHECK_EVERY_S * 2, state=state)
    assert len(asked) == 6, asked
    assert asked[0] != asked[1], "it alternates"
    assert set(asked) == set(TWO), "and reaches both accounts"


def test_one_unreachable_account_does_not_stop_the_other(monkeypatch):
    import time

    from tradingagents import cloud_autopilot as ca, db_jobs as dj

    def boom(slug, limit=10):
        if slug == TWO[0]:
            raise cs.CloudError("gh: 403")
        return []

    monkeypatch.setattr(cs, "fleets", lambda cwd=None: TWO)
    monkeypatch.setattr(cs, "_runs", boom)
    monkeypatch.setattr(ca, "_write", lambda state: None)
    monkeypatch.setattr(dj, "status", lambda kind: {"running": False})

    state, t = {}, time.time()
    first = ca.collect_finished(now=t, state=state)
    second = ca.collect_finished(now=t + ca.CHECK_EVERY_S * 2, state=state)
    assert "403" in str(first.get("why")), first
    assert "403" not in str(second.get("why")), "the next look is the other account"


def test_a_fleet_is_synced_to_this_code_before_it_measures(sent, monkeypatch):
    """harddev round: a fork keeps its own copy and `git push` to it is
    refused from here, so it drifts — two accounts measuring one board with
    two versions of the engine, and no column anywhere showing it."""
    synced: list = []
    monkeypatch.setattr(cs, "_gh", lambda *a, **k: synced.append(a) or "")
    monkeypatch.setattr(cs, "origin_fleet", lambda: "mine/analyzer-x")
    cs.dispatch_across(coin_list=["A", "B"], shards=20, fleet_list=TWO,
                       timeframes="15m")
    assert ("repo", "sync", "partner/analyzer-x", "--source",
            "mine/analyzer-x") in synced, synced
    assert not any(a[:3] == ("repo", "sync", "mine/analyzer-x") for a in synced), \
        "the account that owns origin IS the source"


def test_a_sync_that_fails_is_named_on_the_run_not_swallowed(sent, monkeypatch):
    def boom(*a, **k):
        if a[:2] == ("repo", "sync"):
            raise cs.CloudError("gh: 403 Forbidden")
        return ""

    monkeypatch.setattr(cs, "_gh", boom)
    monkeypatch.setattr(cs, "origin_fleet", lambda: "mine/analyzer-x")
    got = cs.dispatch_across(coin_list=["A", "B"], shards=20, fleet_list=TWO,
                             timeframes="15m")
    stale = [r for r in got["runs"] if r.get("stale")]
    assert len(stale) == 1 and "403" in stale[0]["stale"], got["runs"]


def test_the_screen_counts_every_accounts_machines(monkeypatch):
    """A tile naming one run says 20 machines while 40 are working."""
    import inspect

    from tradingagents import api as api_mod

    src = inspect.getsource(api_mod._read_cloud_status)
    assert '"siblings"' in src and '"accounts"' in src
    from pathlib import Path

    panel = (Path(__file__).resolve().parents[1]
             / "webapp/src/components/backtest/JobsPanel.tsx").read_text(encoding="utf-8")
    assert "cloud.siblings" in panel and "cloud.accounts" in panel
    assert "accounts`" in panel, "the badge says how many"
    api_ts = (Path(__file__).resolve().parents[1]
              / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    assert "siblings?:" in api_ts and "accounts?: number;" in api_ts
