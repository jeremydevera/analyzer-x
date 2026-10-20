"""Starting the Crypto-Predictor switch search (tradingagents/cpw_search.py):
the 40-machine rule (CLAUDE.md) — the market is DEALT between both GitHub
accounts, each gets its own coin list and 20 machines, the fork is brought up
to this code first, and an account that refuses is named while the other
still runs. Nothing here reaches GitHub."""
from __future__ import annotations

import json

import pytest

from tradingagents import cloud_sweep as cs
from tradingagents import cpw_search as search
from tradingagents import forecast_v2_daily as fd

ORIGIN, FORK = "jeremydevera/analyzer-x", "jeremydvera/analyzer-x"
COINS = [f"C{k}_USDT" for k in range(7)]


@pytest.fixture
def world(monkeypatch, tmp_path):
    w = {"started": [], "synced": [], "sync_says": ""}
    monkeypatch.setattr(search, "home", lambda: tmp_path)
    monkeypatch.setattr(fd, "fleets_now", lambda: ([ORIGIN, FORK], []))
    monkeypatch.setattr(fd, "market", lambda: list(COINS))
    monkeypatch.setattr(cs, "origin_fleet", lambda: ORIGIN)

    def sync(repo, source=""):
        w["synced"].append(repo)
        return w["sync_says"]
    monkeypatch.setattr(cs, "sync_fleet", sync)

    def start(repo, inputs):
        w["started"].append((repo, dict(inputs)))
        return 1000 + len(w["started"])
    monkeypatch.setattr(search, "_start", start)
    return w


def test_the_market_is_dealt_between_both_accounts(world, tmp_path):
    state = search.dispatch("t")
    assert [r for r, _ in world["started"]] == [ORIGIN, FORK]
    piles = [inp["coin_list"].split(",") for _, inp in world["started"]]
    assert sorted(piles[0] + piles[1]) == sorted(COINS)
    assert not set(piles[0]) & set(piles[1])
    assert piles[0] == COINS[0::2] and piles[1] == COINS[1::2]      # round robin
    for _, inp in world["started"]:
        assert inp["shards"] == "20" and inp["timeframes"] == "15m,30m,1h,4h,1d"
    labels = [inp["label"] for _, inp in world["started"]]
    assert len(set(labels)) == 2
    assert world["synced"] == [FORK], "the fork runs its own copy: synced first"
    saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert saved["runs"][ORIGIN]["run"] == 1001 and saved["runs"][FORK]["run"] == 1002
    assert state["coins"] == len(COINS) and not state["refused"]


def test_a_fork_that_cannot_be_synced_is_named_and_the_other_still_runs(world):
    world["sync_says"] = "the fork is behind and refused the sync"
    state = search.dispatch("t")
    assert [r for r, _ in world["started"]] == [ORIGIN]
    assert any(FORK in s and "refused the sync" in s for s in state["refused"])


def test_the_title_is_the_workflows_own_run_name():
    wf = open(".github/workflows/cpw.yml", encoding="utf-8").read()
    assert 'run-name: "Crypto-Predictor search · ${{ inputs.label }}"' in wf
    assert search.title_of("x") == "Crypto-Predictor search · x"
