"""Prompt 4: find new winning room strategies and keep them (Oct 02, 2026).

Operator: "when i run the prompt #4 its up to you what kind of combination you
want, like last 15 days or last 7 days or last 30 days with Tp highger than sl
or 90%winrate ... look for all kinds of combination then add it in room
strategy", and before it started: "make sure to ask me if there will be
potential bugs or something that will hurt data".

Every test writes to tmp_path through ROOM_STRATEGIES_HOME — never the real,
never-delete store. Trades sit on one timeline: Jul 01 to Oct 02, 2026.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pytest

from tradingagents import forecast_rules as fr
from tradingagents import room_strategies as rst
from tradingagents import watcher_research as rs

ROOT = Path(__file__).resolve().parents[1]
REAL = {"took": 0.5, "gap": 0.1}
END = int(dt.datetime(2026, 10, 2, 12).timestamp() * 1000)


def ms(y, m, d, h=12):
    return int(dt.datetime(y, m, d, h).timestamp() * 1000)


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ROOM_STRATEGIES_HOME", str(tmp_path / "store"))
    rst._KEPT.clear()
    rst._TABLE.clear()
    yield tmp_path / "store"
    rst._KEPT.clear()
    rst._TABLE.clear()


def test_every_shape_and_window_is_a_dial_and_old_ids_hold():
    assert set(rst.WINDOWS) == {7, 15, 30} and set(rst.SHAPES) == {"any", ">", "1.5x", "2x", "=", "<"}
    assert rst.LINES[0] == 40.0 and rst.LINES[-1] == 95.0 and 40 in rst.TRADES
    c = fr.cfg_of(30, 90, 40, ">", 2.0)
    assert fr.rule_id({**c, "min_tp": 0.0}) == fr.rule_id(c), "an unset floor never moves an id"
    assert fr.rule_id({**c, "min_tp": 2.0}) != fr.rule_id(c)
    ok, why = fr.deployable(rst.cfg(7, 60, 3, ">", 2.0))
    assert not ok and "7-day window" in why
    assert fr.deployable(rst.cfg(15, 70, 50, "=", 2.0, 1.0))[0], "rooms run '=' and a target floor"
    assert fr.tp_ok(np.array([1.0]), np.array([1.0]), "=").all()
    assert rs._tp_ok(np.array([3.0]), np.array([2.0]), "1.5x").all()


def test_round_one_is_every_known_rule_set_once_and_survives_the_file():
    r = rst.round1()
    ids = [rst.sid(c) for c in r]
    assert len(ids) == len(set(ids)) >= 8064
    assert {fr.rule_id(c) for c in fr.base_grid()} <= set(ids)
    p = rst.write_round("t-round", r)
    try:
        back = rst.read_round(str(p.relative_to(ROOT)).replace("\\", "/"))
        assert [rst.sid(c) for c in back] == ids
    finally:
        p.unlink()
    src = (ROOT / ".github/scripts/research_shard.py").read_text(encoding="utf-8")
    assert 'if scen.startswith("file:"):' in src and "rst.read_round(scen[5:])" in src


def test_new_rounds_never_repeat_a_tried_rule_set():
    b = rst.cfg(30, 70, 20, ">", 2.0)
    n = rst.neighbours([b], {rst.sid(b)})
    got = {rst.dials(c) for c in n}
    assert (15, 70.0, 20, ">", 2.0, 0.0) in got and (30, 65.0, 20, ">", 2.0, 0.0) in got
    assert (30, 70.0, 20, "<", 2.0, 0.0) in got and (30, 70.0, 20, ">", 2.0, 1.0) in got
    assert rst.sid(b) not in {rst.sid(c) for c in n}
    assert rst.neighbours([b], {rst.sid(c) for c in n} | {rst.sid(b)}) == [], "all tried: nothing new"


def _trades(spec):
    """[(y, m, d, pnl), ...] -> [entry, exit, pnl], one hour long."""
    return [[ms(y, m, d) - 3_600_000, ms(y, m, d), p] for y, m, d, p in spec]


def test_a_winner_makes_money_after_the_reality_check_in_every_month_and_the_newest_15_days():
    good = _trades([(2026, 7, 10, 1.0), (2026, 8, 10, 1.0), (2026, 9, 10, 1.0), (2026, 9, 25, 1.0)])
    m = rst.measure(good, END, REAL)
    assert [x["month"] for x in m["months"]] == ["2026-07", "2026-08", "2026-09"]
    assert all(x["complete"] for x in m["months"])
    assert m["months"][0]["corrected"] == round(0.5 * (1.0 - 0.1), 2)
    assert rst.is_winner(m) == (True, "")
    no_recent = rst.measure(good[:3], END, REAL)
    assert rst.is_winner(no_recent)[1] == "lost money in the newest 15 days after the reality check"
    bad_aug = rst.measure(good[:1] + _trades([(2026, 8, 10, -1.0)]) + good[2:], END, REAL)
    assert rst.is_winner(bad_aug)[1] == "lost money in 2026-08 after the reality check"
    # ranked by the WORST complete month, never the best
    assert rst.rank_key(m) > rst.rank_key(bad_aug)


def test_the_store_only_grows_and_the_page_reads_the_newest_line(store):
    c = rst.cfg(15, 70, 50, ">", 2.0)
    w = {"id": rst.sid(c), "cfg": c, "words": fr.words(c), "deployable": True, "deploy_why": "",
         "p4": rst.measure(_trades([(2026, 9, 25, 1.0)]), END, REAL),
         "trades": _trades([(2026, 9, 20, 1.0), (2026, 9, 25, 1.0)])}
    assert rst.keep([w], "r1", "RUN", now=1000) == 1
    assert rst.keep([w], "r1", "RUN", now=2000) == 0, "already kept: not new"
    w2 = {**w, "trades": _trades([(2026, 9, 20, 1.0), (2026, 9, 25, 1.0), (2026, 9, 28, -0.5)])}
    rst.keep([], "r2", "RUN", now=3000, remeasured=[w2])
    lines = (store / "room_strategies.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, "a re-measure appends, never rewrites"
    k = rst.kept()
    assert len(k) == 1 and k[0]["found_at"] == 1000 and len(k[0]["trades"]) == 3


def test_the_table_re_measures_over_exactly_the_chosen_dates(store):
    c = rst.cfg(7, 60, 3, ">", 2.0)
    t = _trades([(2026, 9, 1, 1.0), (2026, 9, 20, -0.4), (2026, 9, 21, 1.0)])
    rst.keep([{"id": rst.sid(c), "cfg": c, "words": fr.words(c), "deployable": False,
               "deploy_why": "a 7-day window", "p4": rst.measure(t, END, REAL), "trades": t}],
             "r1", "RUN", now=1000)
    from tradingagents import forecast_v2 as f2
    import tradingagents.forecast_v2 as _f2
    _f2_live = f2.live
    try:
        f2.live = lambda *a, **k: {"reality": {"all": REAL}}
        all_ = rst.table(ms(2026, 9, 1, 0) / 1000, ms(2026, 9, 30, 23) / 1000)
        late = rst.table(ms(2026, 9, 15, 0) / 1000, ms(2026, 9, 30, 23) / 1000)
        only_7 = rst.table(ms(2026, 9, 1, 0) / 1000, ms(2026, 9, 30, 23) / 1000, window=15)
    finally:
        _f2.live = _f2_live
    assert all_["rows"][0]["trades"] == 3 and late["rows"][0]["trades"] == 2
    assert late["rows"][0]["profit"] == 0.6 and late["rows"][0]["worst_run"] == -0.4
    assert only_7["matched"] == 0 and only_7["kept"] == 1
    assert all_["rows"][0]["deployable"] is False


def test_the_page_shows_the_room_strategies_and_asks_the_server():
    src = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    assert "<RoomStrategiesTable />" in src and ">Room strategies<" in src
    assert "api.roomStrategies({ from_s: dayStart(from), to_s: dayStart(to) + 86_399," in src
    api_py = (ROOT / "tradingagents/api.py").read_text(encoding="utf-8")
    assert '@app.get("/api/forecasts/room-strategies")' in api_py


def test_the_merge_scores_every_rule_set_and_keeps_trades_for_winners_only(tmp_path, monkeypatch):
    from tradingagents import research_merge as rmg
    monkeypatch.setattr(rmg.rc, "merge_reports", lambda dirs: {"write": {}})
    monkeypatch.setattr(rmg.rs, "OUT_DIR", tmp_path / "out")
    grid = [rst.cfg(15, 70, 5, ">", 2.0), rst.cfg(30, 80, 5, ">", 2.0)]
    to_min = lambda m: (m // 60_000) - rmg.T0_MIN                       # noqa: E731
    days = {"train": [ms(2026, 7, 10), ms(2026, 8, 10)], "test": [ms(2026, 9, 10), ms(2026, 9, 25)]}
    arrays, meta = {}, {"shard": 0, "chunk": 0, "chunks": 1, "end_ms": END, "books": 10,
                        "rules": [], "strategies": [["S", "VUG", "1h", "macddiv", 0.0, 1.0, 0.5]]}
    for j, c in enumerate(grid):
        meta["rules"].append({"cfg": c, "train": {"slots": 1, "open": 0}, "test": {"slots": 1, "open": 0}})
        sign = 1.0 if j == 0 else -1.0                 # rule 0 wins every month, rule 1 loses
        for part, xs in days.items():
            arrays[f"{j}_{part}_e"] = np.array([to_min(x - 3_600_000) for x in xs], np.int32)
            arrays[f"{j}_{part}_x"] = np.array([to_min(x) for x in xs], np.int32)
            arrays[f"{j}_{part}_p"] = np.array([sign] * len(xs), np.float32)
        arrays[f"{j}_test_s"] = np.zeros(2, np.int32)
    d = tmp_path / "art" / "research-0"
    d.mkdir(parents=True)
    np.savez_compressed(d / "research-0.npz", **arrays)
    (d / "research-0.json").write_text(json.dumps(meta), encoding="utf-8")
    out = json.loads(Path(rmg.merge("t", str(tmp_path / "art"), str(tmp_path), reality=REAL))
                     .read_text(encoding="utf-8"))
    a, b = out["rows"]
    assert a["p4"]["winner"] is True and len(a["p4_trades"]) == 4
    assert b["p4"]["winner"] is False and "p4_trades" not in b, "a loser keeps no trade list"


def test_the_daily_totals_give_the_same_months_as_the_trades():
    """research_shard OUT=daily (Oct 02, 2026): ~1.5 KB a rule set instead of
    its trades — measured on replay-0, 40 rule sets: months identical, the
    same winner verdict for all 40, 63 KB against 4.6 MB."""
    import datetime as _dt
    from tradingagents import watcher_replay as wr
    t = np.asarray(_trades([(2026, 7, 10, 1.0), (2026, 8, 10, -0.2), (2026, 8, 11, 0.9),
                            (2026, 9, 10, 1.0), (2026, 9, 25, 1.0)]), dtype=np.float64)
    mids = wr.local_midnights(int(_dt.datetime(2026, 7, 1).timestamp() * 1000), END)
    edges = np.asarray(mids + [mids[-1] + 86_400_000], dtype=np.int64)
    k = np.searchsorted(edges, t[:, 1], "right") - 1
    n = np.bincount(k, minlength=len(edges) - 1)
    w = np.bincount(k, weights=(t[:, 2] > 0).astype(float), minlength=len(edges) - 1)
    p = np.bincount(k, weights=t[:, 2], minlength=len(edges) - 1)
    a, b = rst.measure(t, END, REAL), rst.measure_days(edges, n, w, p, END, REAL)
    assert [m["corrected"] for m in a["months"]] == [m["corrected"] for m in b["months"]]
    assert rst.is_winner(a) == rst.is_winner(b) and b["total"]["trades"] == 5
    src = (ROOT / ".github/scripts/research_shard.py").read_text(encoding="utf-8")
    assert 'daily = os.environ.get("OUT", "full").strip() == "daily"' in src
    wf = (ROOT / ".github/workflows/research.yml").read_text(encoding="utf-8")
    assert "OUT: ${{ github.event.inputs.output }}" in wf and wf.count("description:") <= 10


def test_a_round_with_a_missing_job_is_never_scored(tmp_path):
    """Replay run 37007971331 put its 1,098 coins on 20 of 40 machines; the
    research plan leaves the 20 empty ones out. A job that is MISSING from
    the coins' shards would add up to a smaller number with nothing saying
    so — the round must refuse, naming it."""
    import pytest
    rep = tmp_path / "reports"
    for shard, coins in ((0, 0), (1, 45), (2, 65)):
        d = rep / f"replay-report-{shard}"
        d.mkdir(parents=True)
        (d / f"replay-report-{shard}.json").write_text(json.dumps({"coins_done": coins}), encoding="utf-8")
    art = tmp_path / "art"

    def job(shard, chunk, books):
        d = art / f"research-{shard}-{chunk}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"research-{shard}-{chunk}.json").write_text(json.dumps(
            {"shard": str(shard), "chunk": chunk, "chunks": 2, "books": books}), encoding="utf-8")

    job(1, 0, 900), job(1, 1, 900), job(2, 0, 1200)
    with pytest.raises(ValueError, match=r"1 job\(s\) missing .*\(2, 1\)"):
        rst.check_complete(str(art), "x", reports=str(rep))
    job(2, 1, 1100)
    with pytest.raises(ValueError, match=r"shard 2 read \[1100, 1200\] combinations"):
        rst.check_complete(str(art), "x", reports=str(rep))
    job(2, 1, 1200)
    got = rst.check_complete(str(art), "x", reports=str(rep))
    assert got == {"shards": [1, 2], "chunks": 2, "combinations": 2100}, "the empty shard 0 is not asked for"


def test_the_plan_leaves_out_only_the_shards_with_no_coins():
    import importlib.util
    spec = importlib.util.spec_from_file_location("research_plan", ROOT / ".github/scripts/research_plan.py")
    rp_ = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp_)
    sizes = {"replay-0": 618, "replay-1": 597_955_220, "replay-2": 622, "replay-report-0": 496}
    # replay-3 is not listed at all: KEPT, so its download fails by name
    assert rp_.pick(4, sizes) == ([1, 3], [0, 2])
    assert rp_.pick(4, None) == ([0, 1, 2, 3], []), "an unreadable listing keeps every shard"


def test_the_round_finds_the_replays_own_reports_by_itself(tmp_path, monkeypatch):
    """finish_daily calls check_complete with no folder: the first draft
    looked under the sweep's HOME (~/.tradingagents/backtest/replay), where
    no report has ever been saved, and refused every real round."""
    from tradingagents import replay_collect as rc
    monkeypatch.setattr(rc, "OUT_DIR", tmp_path)
    d = tmp_path / "reports-37007971331" / "replay-report-1"
    d.mkdir(parents=True)
    (d / "replay-report-1.json").write_text(json.dumps({"coins_done": 45}), encoding="utf-8")
    art = tmp_path / "art" / "research-1-0"
    art.mkdir(parents=True)
    (art / "research-1-0.json").write_text(json.dumps({"shard": "1", "chunk": 0, "chunks": 1, "books": 9}),
                                           encoding="utf-8")
    assert rst._reports_dir("37007971331") == tmp_path / "reports-37007971331"
    assert rst.check_complete(str(tmp_path / "art"), "37007971331")["shards"] == [1]


def test_the_table_is_remembered_until_the_store_changes(store, monkeypatch):
    """The page asks every minute; round 1 kept 673 winners holding 2,427,758
    trades. The same dates are measured once — and a new winner is on the
    very next ask."""
    from tradingagents import forecast_v2 as f2
    monkeypatch.setattr(f2, "live", lambda *a, **k: {"reality": {"all": REAL}})
    calls = []
    real = rst._measured
    monkeypatch.setattr(rst, "_measured", lambda *a: calls.append(a) or real(*a))
    t = _trades([(2026, 9, 1, 1.0), (2026, 9, 21, 1.0)])

    def win(c):
        return {"id": rst.sid(c), "cfg": c, "words": fr.words(c), "deployable": True,
                "deploy_why": "", "p4": rst.measure(t, END, REAL), "trades": t}
    rst.keep([win(rst.cfg(30, 80, 20, ">", 2.0))], "r1", "RUN", now=1000)
    a, b = ms(2026, 9, 1, 0) / 1000, ms(2026, 9, 30, 23) / 1000
    first = rst.table(a, b)
    again = rst.table(a, b, sort="profit")
    assert first["kept"] == again["kept"] == 1 and len(calls) == 1, "measured once"
    assert isinstance(rst.kept()[0]["trades"], np.ndarray), "trades held as one array"
    rst.keep([win(rst.cfg(15, 75, 30, ">", 2.0))], "r2", "RUN", now=2000)
    assert rst.table(a, b)["kept"] == 2 and len(calls) == 2, "a new winner shows at once"


def test_the_route_uses_the_forecast_pages_own_reality_check(store, monkeypatch):
    """Working the reality check out again took 14 s a request (122 s on the
    first after a restart, Oct 02, 2026) while the page asks every minute;
    the route hands in the Forecast page's kept copy instead."""
    from tradingagents import api
    from tradingagents import forecast_v2 as f2
    from tradingagents import forecast_v2_api as f2a

    def boom(*a, **k):
        raise AssertionError("worked the reality check out again")
    monkeypatch.setattr(f2, "live", boom)
    monkeypatch.setattr(f2a, "live", lambda: {"reality": {"all": REAL}, "at": 0})
    got = api.room_strategies_route(ms(2026, 9, 1, 0) / 1000, ms(2026, 9, 30, 23) / 1000)
    assert got["reality"] == REAL and got["kept"] == 0
