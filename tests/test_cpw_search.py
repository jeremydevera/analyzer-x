"""Starting the Crypto-Predictor switch search (tradingagents/cpw_search.py):
the 40-machine rule (CLAUDE.md) — the market is DEALT between both GitHub
accounts, each gets its own coin list and 20 machines, the fork is brought up
to this code first, and an account that refuses is named while the other
still runs. Nothing here reaches GitHub."""
from __future__ import annotations

import json

import pytest

from tradingagents import cloud_sweep as cs, cpw_search as search, forecast_v2_daily as fd

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


# ------------------------------------------------- bringing the results home

import numpy as np  # noqa: E402

NAMES = ["cp_st_f0u0h0x0i0d0", "cp_st_f1u0h0x0i0d0", "cp_bb_z0j0k0c0x0h0"]
FIELDS = ("pairs", "pairs_up", "trades", "wins", "profit",
          "l_pairs", "l_pairs_up", "l_trades", "l_wins", "l_profit")
BARS = {"15m": [(0.002, 0.004), (0.003, 0.006)], "1h": [(0.005, 0.01)]}


def _machine(root, k, fill, names=NAMES, report=None, rows=()):
    """One GitHub machine's two artifacts, as `gh run download` unpacks them:
    a folder per artifact."""
    summ = root / f"cpw-summary-{k}"
    summ.mkdir(parents=True)
    arrays = {f"tf_{tf}": np.full((len(names), len(b), len(FIELDS)), float(fill))
              for tf, b in BARS.items()}
    np.savez_compressed(summ / f"cpw-{k}.npz", names=np.array(names),
                        fields=np.array(FIELDS), **arrays,
                        **{f"barriers_{tf}": np.array(b) for tf, b in BARS.items()})
    (summ / f"cpw-report-{k}.json").write_text(json.dumps(
        {"report": report or [], "names": len(names), "tfs": list(BARS)}), encoding="utf-8")
    rdir = root / f"cpw-rows-{k}"
    rdir.mkdir(parents=True)
    (rdir / f"rows-{k}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_every_machines_sums_add_up(tmp_path):
    a, b = tmp_path / "run-1", tmp_path / "run-2"
    _machine(a, 0, 1)
    _machine(a, 1, 2)
    _machine(b, 0, 4)
    got = search.read_machines([a, b])
    assert got["machines"] == 3 and got["names"] == NAMES
    assert got["barriers"]["15m"] == [(0.002, 0.004), (0.003, 0.006)]
    assert float(got["tf"]["15m"][1, 1, FIELDS.index("profit")]) == 7.0
    assert float(got["tf"]["1h"][2, 0, FIELDS.index("trades")]) == 7.0


def test_a_machine_that_measured_other_settings_is_refused_by_name(tmp_path):
    a = tmp_path / "run-1"
    _machine(a, 0, 1)
    _machine(a, 1, 1, names=list(reversed(NAMES)))
    with pytest.raises(ValueError, match="cpw-1.npz"):
        search.read_machines([a])


def test_the_download_lands_beside_the_store_never_on_the_system_drive(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(search, "home", lambda: tmp_path)

    def run(cmd, **kw):
        seen.append(cmd)
        return None
    monkeypatch.setattr(search.subprocess, "run", run)
    (tmp_path / "run-7").mkdir()
    (tmp_path / "run-7" / "left-over").write_text("x")
    root = search.download(7, ORIGIN)
    assert root == tmp_path / "run-7" and not (root / "left-over").exists()
    cmd = seen[0]
    assert cmd[:4] == ["gh", "run", "download", "7"]
    assert cmd[cmd.index("-D") + 1] == str(root) and cmd[cmd.index("-R") + 1] == ORIGIN
    assert {cmd[i + 1] for i, x in enumerate(cmd) if x == "-p"} == {"cpw-rows-*", "cpw-summary-*"}


def test_coins_no_machine_reached_are_named(tmp_path):
    rep = [{"coin": "A", "tf": "15m", "rows": 3}, {"coin": "A", "tf": "1h", "rows": 1},
           {"coin": "B", "tf": "15m", "error": "ValueError: boom"},
           {"coin": "C", "tf": "*", "error": "PairFailed: x"}]
    cov = search.coverage(["A_USDT", "B_USDT", "C_USDT", "D_USDT"], rep)
    assert cov["reached"] == 3 and cov["not_reached"] == ["D"]
    assert cov["pairs_failed"] == ["B 15m: ValueError: boom", "C *: PairFailed: x"]
    assert cov["pairs_ok"] == 2


def test_each_setting_is_ranked_at_its_best_stop_and_target():
    tf = {"15m": np.zeros((3, 2, len(FIELDS))), "1h": np.zeros((3, 1, len(FIELDS)))}
    P = FIELDS.index("profit")
    tf["15m"][0, 0, :5] = (10, 6, 100, 60, 12.5)      # setting 0: 12.5 at the first pair
    tf["15m"][0, 1, :5] = (10, 2, 80, 30, -4.0)
    tf["15m"][1, 1, :5] = (8, 5, 50, 30, 20.0)        # setting 1: 20.0 at the second
    tf["15m"][1, 1, 5:] = (3, 3, 20, 15, 9.0)         # ...9.0 of it on listed rows
    merged = {"names": NAMES, "fields": list(FIELDS), "tf": tf, "barriers": BARS}
    cells = search.cells(merged)
    assert len(cells) == 3                            # a cell nothing traded is not a cell
    best = search.best_by_setting(cells)
    assert best[("cp_st_f0u0h0x0i0d0", "15m")]["profit"] == 12.5
    assert best[("cp_st_f0u0h0x0i0d0", "15m")]["sl"] == 0.2
    assert best[("cp_st_f0u0h0x0i0d0", "15m")]["tp"] == 0.4
    one = best[("cp_st_f1u0h0x0i0d0", "15m")]
    assert (one["sl"], one["tp"], one["trades"], one["wins"], one["losses"]) == (0.3, 0.6, 50, 30, 20)
    assert one["listed"] == {"pairs": 3, "pairs_up": 3, "trades": 20, "wins": 15, "profit": 9.0}
    assert one["strategy"] == "st" and one["pairs"] == 8 and one["pairs_up"] == 5
    assert float(tf["15m"][0, 0, P]) == 12.5          # the merged arrays are not changed


def test_a_half_written_copy_left_by_a_killed_machine_is_never_added(tmp_path):
    a = tmp_path / "run-1"
    _machine(a, 0, 1)
    import shutil
    src = a / "cpw-summary-0" / "cpw-0.npz"
    shutil.copy(src, a / "cpw-summary-0" / "cpw-0.npz.tmp.npz")
    got = search.read_machines([a])
    assert got["machines"] == 1
    assert float(got["tf"]["15m"][0, 0, FIELDS.index("profit")]) == 1.0
