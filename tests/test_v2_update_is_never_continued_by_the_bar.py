"""A Backtest v2 UPDATE measures every pair in full, minute-exact — never a
bar-rule continuation under a v2 label (RCA-2026-09-28-B).

Sep 28, 2026 11:49am, UPDATE ALL BACKTESTS on Backtest v2: the first status
read of the 20 jeremydvera machines showed `continued: 2`. The continuation
(`sweep_shard.continue_pair`) settles exits with the BAR rule — it downloads
no minutes and passes no `fine=` — while its rows and done marker go out
stamped `res=1m`. And the saved-position records carry no `res`, so the v2
fleet was handed runs 36140207405 and 36123188935 (`run_res` ''), beside the
v2 ones.
"""
import importlib.util
import pathlib

import pytest

from tradingagents import cloud_sweep as cs

REPO = pathlib.Path(__file__).resolve().parents[1]
SHARD = REPO / ".github" / "scripts" / "sweep_shard.py"


def _load(tmp_path, monkeypatch, res):
    monkeypatch.chdir(tmp_path)
    for k, v in {"SHARD": "0", "SHARDS": "1", "TFS": "1h", "DAYS": "30",
                 "MODE": "update", "STATE_RUNS": "111", "RES": res}.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location(f"sweep_shard_v2cont_{res or 'v1'}", SHARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "report", lambda *a, **k: None)
    return mod


def test_a_v2_shard_never_continues_a_saved_position(tmp_path, monkeypatch):
    shard = _load(tmp_path, monkeypatch, "1m")
    assert shard.RES == "1m"

    def _no_venue(*a, **k):
        raise AssertionError("a v2 continuation must not even fetch candles")

    monkeypatch.setattr(shard.at, "taker_fee", _no_venue)
    prior = {"__last_ms__": 1_790_000_000_000, "__version__": shard.VERSION}
    assert shard.continue_pair("XPIN_USDT", "1h", prior, out=None) is None, \
        "None sends the pair down the full, minute-exact path"


def test_v1_still_continues(tmp_path, monkeypatch):
    """The fix is v2's: a v1 continuation still reaches the venue."""
    shard = _load(tmp_path, monkeypatch, "")
    called = []

    def _stop(*a, **k):
        called.append(1)
        raise RuntimeError("stop here")

    monkeypatch.setattr(shard.at, "taker_fee", _stop)
    prior = {"__last_ms__": 1_790_000_000_000, "__version__": shard.VERSION}
    monkeypatch.setattr(shard.time, "time", lambda: 1_790_000_000 + 3600 * 5)
    with pytest.raises(shard.PairFailed):
        shard.continue_pair("XPIN_USDT", "1h", prior, out=None)
    assert called


@pytest.mark.parametrize("res, wants_positions", [("1m", False), ("", True)])
def test_the_dispatch_sends_no_saved_positions_to_a_v2_update(monkeypatch, res,
                                                              wants_positions):
    sent = []
    monkeypatch.setattr(cs, "sync_fleet", lambda slug: "")
    monkeypatch.setattr(cs, "state_runs_for",
                        lambda tfs, slug="": ["36140207405", "35825775582"])
    monkeypatch.setattr(cs, "dispatch",
                        lambda **kw: sent.append(kw) or {"id": 1, "url": "u"})
    kw = {"res": res} if res else {}
    cs.dispatch_across(coin_list=["XPIN"], shards=20, timeframes="1h",
                       mode="update", fleet_list=["a/b"], **kw)
    assert len(sent) == 1
    assert bool(sent[0].get("state_runs")) is wants_positions, sent[0]
