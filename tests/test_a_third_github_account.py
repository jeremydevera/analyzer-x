"""A third GitHub account joins the machines (operator, Oct 21, 2026: *"i have
a new temamate and i want to add his github for machine"*; asked whose it
is: *"yes it is my team mate account"*).

`cloud_sweep.fleets()` reads the checkout's git remotes, so every splitter
deals to a new remote with no change. What it did NOT reach, and what these
tests hold:

* the per-minute cost files: `cost_store.REPOS` is a fixed list the GitHub
  machines read from their own checkout, and a coin-month on an account
  missing there is a cost never read (and overwritten by the costs job,
  which reads before it uploads);
* Forecast v2's run folders: three accounts' replay folders alone filled
  `KEEP_RUNS` (3), so the first account's was the next pruned while the
  chain could still read it — NEVER HAPPENED YET (found before the first
  three-account night);
* the Errors tab's words: "both accounts" is false once there are three.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THIRD = "jeremydevera0903-gif/analyzer-x"


def test_the_cost_files_are_read_from_every_account():
    from tradingagents import cost_store

    if os.environ.get("COST_REPOS"):
        return                          # a machine told otherwise on purpose
    assert set(cost_store.REPOS) >= {"jeremydevera/analyzer-x",
                                     "jeremydvera/analyzer-x", THIRD}


def test_a_coin_month_on_the_third_account_is_merged_in(tmp_path, monkeypatch):
    from tradingagents import cost_store as cs

    monkeypatch.setattr(cs, "CACHE", tmp_path)
    t0 = 1_791_000_000

    def one(t):
        return cs.to_bytes({"t": [t], "bid": [1.0], "ask": [1.1], "spread": [0.1],
                            "buy": [0.001], "sell": [0.001], "exhausted": [False],
                            "source": ["full"], "at": [t]})

    def fetch(url):
        if "/jeremydevera0903-gif/" in url:
            return 200, one(t0 + 60)
        if "/jeremydevera/" in url:
            return 200, one(t0)
        return 404, b""

    got = cs.load_month("BTC_USDT", "202610", fetch=fetch, cache=False)
    assert list(got["t"]) == [t0, t0 + 60], "the third account's day is part of the month"


def test_the_forecast_keeps_every_accounts_replay_while_it_is_read(tmp_path, monkeypatch):
    from tradingagents import forecast_v2_daily as fd

    monkeypatch.setattr(fd, "home", lambda: tmp_path)
    runs = tmp_path / "runs"
    replay = {"a/x": 101, "b/x": 102, "c/x": 103}
    st = {"phase": "base", "replay_runs": replay, "base_runs": {"a/x": 201}}
    (tmp_path / "state.json").write_text(json.dumps(st), encoding="utf-8")
    now = time.time()
    # oldest first: the three replays, then the base, then two newer downloads
    for k, name in enumerate(["101", "102", "103", "201", "301", "302"]):
        d = runs / name
        d.mkdir(parents=True)
        os.utime(d, (now - 600 + k * 60, now - 600 + k * 60))
    fd._prune_runs(keep={"302"})
    left = {d.name for d in runs.iterdir()}
    assert {"101", "102", "103", "201", "302"} <= left, \
        "every account's replay and base folder survives while the chain reads them"


def test_the_errors_tab_counts_the_accounts_never_says_both_for_three():
    src = (ROOT / "webapp/src/components/errors/GithubMachinesErrors.tsx").read_text(
        encoding="utf-8")
    assert '"both accounts"' in src and "d.accounts.length === 2" in src
    assert "all ${d.accounts.length} accounts" in src
    assert '" · both accounts"' not in src.replace(
        'd.accounts.length === 2 ? " · both accounts"', "")
