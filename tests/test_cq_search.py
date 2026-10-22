"""Starting the confluence research from this PC (tradingagents/cq_search.py
and .github/workflows/cq.yml), Oct 21, 2026: every account gets its share,
the luck coins travel with their own coins, a refused share is redone by
itself, a late-listed run is adopted, the nightly hours refuse a dispatch,
a refused share is named as not reached, the progress file says where
Prompt 1 stands, and the workflow takes exactly what the dispatch sends."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pytest

from tradingagents import cloud_sweep as cs, cq_search as cqs, forecast_v2_daily as fd

ROOT = Path(__file__).resolve().parent.parent
NOON = dt.datetime(2026, 10, 22, 12, 0).timestamp()
ONE_AM = dt.datetime(2026, 10, 22, 1, 0).timestamp()


def _fleet(monkeypatch, tmp_path, fail=()):
    started = []

    def start(repo, inputs):
        if repo in fail:
            raise RuntimeError("could not create workflow dispatch event: HTTP 502")
        started.append((repo, dict(inputs)))
        return 1000 + len(started)

    monkeypatch.setattr(cqs, "home", lambda: tmp_path)
    monkeypatch.setattr(cqs, "_start", start)
    monkeypatch.setattr(cqs, "_runs", lambda repo, limit=10: [])
    monkeypatch.setattr(fd, "fleets_now", lambda: (["a/x", "b/x", "c/x"], []))
    monkeypatch.setattr(cs, "origin_fleet", lambda: "a/x")
    monkeypatch.setattr(cs, "sync_fleet", lambda repo: "")
    return started


COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "NVDA"]


def test_every_account_gets_its_share_and_its_own_luck_coins(monkeypatch, tmp_path):
    started = _fleet(monkeypatch, tmp_path)
    st = cqs.dispatch("p", coins=COINS, luck="BTC,NVDA", now=NOON)
    assert [r for r, _ in started] == ["a/x", "b/x", "c/x"]
    dealt = sorted(c for _r, i in started for c in i["coin_list"].split(","))
    assert dealt == sorted(c + "_USDT" for c in COINS)
    for _repo, inputs in started:
        mine = {c.replace("_USDT", "") for c in inputs["coin_list"].split(",")}
        luck = {c for c in inputs["luck"].split(",") if c}
        assert luck == mine & {"BTC", "NVDA"}
        assert inputs["search"] == "500,100,10" and inputs["label"].startswith("p · ")
    assert st["coins"] == 6 and not st["refused"]
    prog = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert prog["stage"].startswith("dispatched state.json: 3 run(s)")
    assert prog["runs"]["state"]["runs"] == {"a/x": 1001, "b/x": 1002, "c/x": 1003}


def test_all_means_every_coin_is_luck_searched(monkeypatch, tmp_path):
    started = _fleet(monkeypatch, tmp_path)
    cqs.dispatch("p", coins=COINS, luck="all", now=NOON)
    assert {i["luck"] for _r, i in started} == {"all"}


def test_the_nightly_hours_refuse_a_dispatch(monkeypatch, tmp_path):
    started = _fleet(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="12:45am and 5:00am"):
        cqs.dispatch("p", coins=COINS, now=ONE_AM)
    assert started == []
    cqs.dispatch("p", coins=COINS, now=ONE_AM, force=True)
    assert len(started) == 3


def test_a_refused_share_is_started_again_by_itself(monkeypatch, tmp_path):
    started = _fleet(monkeypatch, tmp_path, fail=("b/x",))
    st = cqs.dispatch("p", coins=COINS, now=NOON)
    assert set(st["runs"]) == {"a/x", "c/x"} and st["refused"][0].startswith("b/x:")
    mine = st["dealt"]["b/x"]
    started.clear()
    monkeypatch.setattr(cqs, "_start", lambda repo, inputs: started.append((repo, dict(inputs)))
                        or 2001)
    got = cqs.redo(cqs.STATE, "b/x")
    assert started == [("b/x", mine)] and got["runs"]["b/x"]["run"] == 2001
    assert got["refused"] == []
    with pytest.raises(ValueError, match="already has run"):
        cqs.redo(cqs.STATE, "b/x")


def test_a_dispatch_github_listed_late_is_adopted_not_doubled(monkeypatch, tmp_path):
    started = _fleet(monkeypatch, tmp_path, fail=("b/x",))
    st = cqs.dispatch("p", coins=COINS, now=NOON)
    late = dt.datetime.fromtimestamp(st["started"] + 120, dt.timezone.utc).isoformat()
    title = cqs.title_of(st["dealt"]["b/x"]["label"])
    monkeypatch.setattr(cqs, "_runs", lambda repo, limit=10: [
        {"databaseId": 777, "displayTitle": title, "createdAt": late}] if repo == "b/x" else [])
    started.clear()
    assert cqs.redo(cqs.STATE, "b/x")["runs"]["b/x"]["run"] == 777 and started == []


def test_a_refused_share_is_named_as_not_reached_never_a_smaller_board(monkeypatch, tmp_path):
    _fleet(monkeypatch, tmp_path, fail=("b/x",))
    st = cqs.dispatch("p", coins=COINS, now=NOON)
    root = tmp_path / "run-x"
    root.mkdir()
    done = [c for r in st["runs"].values() for c in r["coin_list"]]
    (root / "cq-report-0.json").write_text(json.dumps(
        {"report": [{"coin": c.replace("_USDT", ""), "tf": "1h", "tried": 9} for c in done]}),
        encoding="utf-8")
    monkeypatch.setattr(cqs, "_gh", lambda *a, **k: json.dumps({"status": "completed"}))
    monkeypatch.setattr(cqs, "download", lambda run, repo: root)
    cov = cqs.collect(cqs.STATE)["coverage"]
    assert cov["board"] == 6 and cov["reached"] == 4
    assert sorted(cov["not_reached"]) == sorted(
        c.replace("_USDT", "") for c in st["dealt"]["b/x"]["coin_list"].split(","))
    prog = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert prog["stage"].startswith("collected state.json: 4 of 6 coin(s)")


def test_an_unreadable_progress_file_is_kept_aside_never_overwritten(monkeypatch, tmp_path):
    monkeypatch.setattr(cqs, "home", lambda: tmp_path)
    (tmp_path / "progress.json").write_text("{not json", encoding="utf-8")
    cqs.progress("pilot dispatched")
    kept = list(tmp_path.glob("progress.unreadable-*.json"))
    assert kept and kept[0].read_text(encoding="utf-8") == "{not json"
    assert json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))["stage"] == \
        "pilot dispatched"


def test_the_workflow_takes_exactly_what_the_dispatch_sends():
    text = (ROOT / ".github" / "workflows" / "cq.yml").read_text(encoding="utf-8")
    block = text.split("inputs:", 1)[1].split("permissions:", 1)[0]
    names = re.findall(r"^      ([a-z_]+):\s*$", block, flags=re.M)
    assert len(names) <= 10                      # GitHub allows exactly ten
    assert set(names) == {"shards", "timeframes", "coin_list", "base", "label", "luck", "search"}
    assert "TA_VENUE: gate" in text and "timeout-minutes: 350" in text
    assert "python .github/scripts/cq_shard.py" in text and "cq-out-${{ matrix.shard }}" in text
    for env in ("COIN_LIST", "TFS", "LUCK", "SEARCH", "BASE_MARGIN", "SHARD", "SHARDS"):
        assert f"          {env}: " in text, env
