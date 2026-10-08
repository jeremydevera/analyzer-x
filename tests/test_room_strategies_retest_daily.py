"""Room strategies, re-tested every day (Oct 07, 2026).

Operator, told "last 4 days" was empty because every saved trade of the 992
kept rule sets ended Oct 02, 2026 8:00am: "what do you mean saved strategy? it
should be updated everyday justd like the backtest".

tradingagents/room_strategies_daily.py: a replay and a research run on EVERY
GitHub account, then every kept rule set measured again into one file that
room_strategies.kept() reads. Every test writes under tmp_path through
ROOM_STRATEGIES_HOME, never the real never-delete store, and GitHub is faked
— no test can start a run. Trades sit on one timeline: Jul 01 to Oct 06, 2026.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pytest

from tradingagents import forecast_rules as fr
from tradingagents import room_strategies as rst
from tradingagents import room_strategies_daily as rsd
from tradingagents.research_merge import T0_MIN

ROOT = Path(__file__).resolve().parents[1]
REAL = {"took": 0.5, "gap": 0.1}
OLD_END = int(dt.datetime(2026, 10, 2, 8).timestamp() * 1000)     # prompt 4's replay end
NEW_END = int(dt.datetime(2026, 10, 7, 1).timestamp() * 1000)     # a re-test's end


def ms(y, m, d, h=12):
    return int(dt.datetime(y, m, d, h).timestamp() * 1000)


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ROOM_STRATEGIES_HOME", str(tmp_path / "store"))
    for cache in (rst._KEPT, rst._TABLE, rst._NOW):
        cache.clear()
    yield tmp_path / "store"
    for cache in (rst._KEPT, rst._TABLE, rst._NOW):
        cache.clear()


A = rst.cfg(15, 70, 50, ">", 2.0)
B = rst.cfg(30, 90, 20, "1.5x", 1.0)
C = rst.cfg(7, 60, 30, "any", 2.0)


def _keep(now=1000.0):
    """Three kept winners, each with prompt 4's trades (ending by OLD_END)."""
    def t(spec):
        return [[ms(*d) - 3_600_000, ms(*d), p] for d, p in spec]
    rows = [(A, t([((2026, 7, 10), 1.0), ((2026, 9, 20), 1.0)])),
            (B, t([((2026, 8, 3), 0.5)])),
            (C, t([((2026, 9, 1), -0.2), ((2026, 10, 1), 0.7)]))]
    rst.keep([{"id": rst.sid(c), "cfg": c, "words": fr.words(c), "deployable": True, "deploy_why": "",
               "p4": rst.measure(tr, OLD_END, REAL), "trades": tr} for c, tr in rows],
             "round1c", "RUN", now=now)


def _strat(coin: str) -> list:
    """A strategy as research_shard names it: id, coin, tf, signal, th, TP, SL."""
    return [f"S-{coin}", coin, "1h", "rsi14", 0.0, 1.5, 1.0]


def _art(folder: Path, shard: int, chunk: int, chunks: int, rules: list, end_ms: int = NEW_END):
    """One research machine's artifact, as research_shard writes it: per rule
    j and part, entry/exit minutes since T0 and the profit; for the TEST part
    each trade's index into the machine's own strategy list (a trade's 5th
    item names its strategy, BTC when it names none)."""
    arrays, meta_rules, strategies, at = {}, [], [], {}
    for j, (cfg, trades) in enumerate(rules):
        rule = {"cfg": cfg}
        for part in ("train", "test"):
            sel = [t for t in trades if t[3] == part]
            arrays[f"{j}_{part}_e"] = np.array([t[0] // 60_000 - T0_MIN for t in sel], np.int32)
            arrays[f"{j}_{part}_x"] = np.array([t[1] // 60_000 - T0_MIN for t in sel], np.int32)
            arrays[f"{j}_{part}_p"] = np.array([t[2] for t in sel], np.float32)
            if part == "test":
                idx = []
                for t in sel:
                    row = t[4] if len(t) > 4 else _strat("BTC")
                    if row[0] not in at:
                        at[row[0]] = len(strategies)
                        strategies.append(row)
                    idx.append(at[row[0]])
                arrays[f"{j}_test_s"] = np.array(idx, np.int32)
            rule[part] = {"slots": len(sel), "open": 0}
        meta_rules.append(rule)
    name = f"research-{shard}" + (f"-{chunk}" if chunks > 1 else "")
    d = folder / f"research-{shard}-{chunk}"
    d.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(d / f"{name}.npz", **arrays)
    (d / f"{name}.json").write_text(json.dumps({
        "shard": shard, "chunk": chunk, "chunks": chunks, "end_ms": end_ms, "books": 10, "trades": 0,
        "batches": 1, "rules": meta_rules, "strategies": strategies}), encoding="utf-8")


def _report(folder: Path, shard: int, coins: int = 3):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"replay-report-{shard}.json").write_text(json.dumps({"coins_done": coins}), encoding="utf-8")


def _two_accounts(tmp: Path):
    """Account 0 measured coins on shards 0 and 1, account 1 on shard 0; the
    rule list in two slices (A in slice 0, B in slice 1). C is not in it."""
    def tr(d, p, part, coin=None):
        x = ms(*d)
        return (x - 3_600_000, x, p, part) + ((_strat(coin),) if coin else ())
    a0, a1 = tmp / "acc0", tmp / "acc1"
    _art(a0, 0, 0, 2, [(A, [tr((2026, 7, 10), 1.0, "train"), tr((2026, 9, 20), 1.0, "test", "ETH")])])
    _art(a0, 1, 0, 2, [(A, [tr((2026, 10, 5), -0.4, "test", "GPNSTOCK")])])    # after Oct 02
    _art(a1, 0, 0, 2, [(A, [tr((2026, 10, 6), 0.8, "test", "SOL")])])
    _art(a0, 0, 1, 2, [(B, [tr((2026, 8, 3), 0.5, "train")])])
    _art(a0, 1, 1, 2, [(B, [])])
    _art(a1, 0, 1, 2, [(B, [tr((2026, 10, 4), 0.3, "test")])])
    for shard in (0, 1):
        _report(tmp / "rep0", shard)
    _report(tmp / "rep1", 0)
    return a0, a1


def _merge(tmp: Path, made_at: float = 5000.0):
    a0, a1 = _two_accounts(tmp)
    return rsd.merge({"arts": [str(a0), str(a1)], "end_ms": NEW_END, "reality": REAL,
                      "made_at": made_at, "out": str(rst.now_path()), "runs": {"replay": {}},
                      "write_rule": "wr=60,trades=20,tp=any,windows=7|15|30",
                      "result": str(tmp / "merge.json")})


# ------------------------------------------------------------ the inputs
def test_the_replay_writes_by_the_loosest_rule_any_kept_rule_set_uses():
    """A strategy is written when it passes this rule at some check; a rule
    set only picks what passes its own, stricter line — so every kept rule set
    sees what prompt 4's own replay gave it. The 992 kept on Oct 07, 2026 go
    down to 60% and 20 trades and judge on 7, 15 and 30 days."""
    assert rsd.write_rule_for([A, B, C]) == "wr=60,trades=20,tp=any,windows=7|15|30"
    assert rsd.write_rule_for([B]) == "wr=90,trades=20,tp=any,windows=30"
    with pytest.raises(ValueError):
        rsd.write_rule_for([])


def test_the_list_github_reads_holds_every_kept_rule_set_and_its_ids_round_trip(store, tmp_path,
                                                                                monkeypatch):
    # never the real research/p4/kept.json: GitHub re-tests what that file says
    monkeypatch.setattr(rst, "ROUNDS_DIR", tmp_path / "p4")
    _keep()
    p = rst.write_list()
    assert p == tmp_path / "p4" / "kept.json"
    back = [rst.cfg(*(r[k] for k in rst.DIALS)) for r in json.loads(p.read_text(encoding="utf-8"))]
    assert [rst.sid(c) for c in back] == [w["id"] for w in rst._kept_lines()]
    assert rsd.list_rel() == "research/p4/kept.json"


def test_prompt_4_writes_the_list_when_it_keeps_winners():
    src = (ROOT / "tradingagents/room_strategies.py").read_text(encoding="utf-8")
    finish = src.split("def finish(")[1].split("\ndef ")[0]
    assert "new = keep(" in finish and finish.index("write_list()") > finish.index("new = keep(")


# ------------------------------------------------------------- the merge
def test_a_kept_winner_reads_the_newest_daily_retest_across_every_account(store, tmp_path):
    _keep()
    got = _merge(tmp_path)
    assert got["retested"] == 2 and got["trades"] == 6
    k = {w["id"]: w for w in rst.kept()}
    a = k[rst.sid(A)]
    assert a["retested"] is True and a["found_at"] == 1000, "the day it was found never moves"
    assert [int(x) for x in a["trades"][:, 1]] == [ms(2026, 7, 10), ms(2026, 9, 20), ms(2026, 10, 5),
                                                   ms(2026, 10, 6)], "both accounts, by close"
    assert [round(float(x), 2) for x in a["trades"][:, 2]] == [1.0, 1.0, -0.4, 0.8]
    assert a["p4"]["months"][-1]["month"] == "2026-10" and a["p4"]["months"][-1]["trades"] == 2
    # the one the re-test did not reach keeps its own numbers — never zeros
    c = k[rst.sid(C)]
    assert not c.get("retested") and len(c["trades"]) == 2
    # the same measure over the days both cover, printed for the first run
    assert got["overlap"]["until"] == ms(2026, 10, 1) and got["overlap"]["kept"] == 3
    assert got["overlap"]["retest"] == 3


def test_the_page_reads_a_new_retest_on_its_very_next_ask(store, tmp_path):
    _keep()
    lo, hi = ms(2026, 10, 3, 0) / 1000, ms(2026, 10, 7, 0) / 1000
    before = rst.table(lo, hi, reality=REAL)
    assert before["with_trades"] == 0 and before["data_end"] == ms(2026, 10, 1)
    _merge(tmp_path)
    after = rst.table(lo, hi, reality=REAL)
    assert after["with_trades"] == 2 and after["data_end"] == ms(2026, 10, 6)
    row = rst.table(lo, hi, reality=REAL, find=rst.sid(A))["rows"][0]
    assert (row["trades"], row["wins"], row["profit"]) == (2, 1, 0.4)
    got = rst.trades(rst.sid(A), lo, hi)
    assert [t["profit"] for t in got["rows"]] == [-0.4, 0.8] and got["profit"] == 0.4


def test_every_trade_from_sep_01_names_its_coin(store, tmp_path):
    """Operator, Oct 08, 2026: "when i click the trade and pop up eappears why
    can't i see the coin?". research_shard names the strategy behind every
    TEST-part trade (Sep 01, 2026 on), each machine numbering its own list;
    the add-up keeps it through both accounts and the sort, and a train-part
    trade (July) says it is not known — never a guess."""
    _keep()
    got = _merge(tmp_path)
    assert got["named"] == 4, "A's three Sep-Oct trades on two accounts, and B's Oct 04"
    rows = rst.trades(rst.sid(A), ms(2026, 7, 1, 0) / 1000, ms(2026, 10, 7, 0) / 1000)
    assert [r["coin"] for r in rows["rows"]] == [None, "ETH", "GPNSTOCK", "SOL"]
    eth = rows["rows"][1]
    assert (eth["tf"], eth["signal"], eth["tp"], eth["sl"]) == ("1h", "rsi14", 1.5, 1.0)
    assert rows["unnamed"] == 1 and rows["named_from"] == int(dt.datetime(2026, 9, 1).timestamp() * 1000)
    # a winner the re-test did not reach: no coin, and the page says why
    c = rst.trades(rst.sid(C), ms(2026, 7, 1, 0) / 1000, ms(2026, 10, 7, 0) / 1000)
    assert {r["coin"] for r in c["rows"]} == {None} and c["named_from"] is None and c["unnamed"] == 2


def test_a_strategy_number_outside_its_machines_list_is_unknown_not_a_crash():
    assert list(rsd._named_by([7, 9], [0, 1, 2, -1])) == [7, 9, -1, -1]
    assert list(rsd._named_by([], [0])) == [-1]


def test_an_older_retest_never_hides_a_newer_prompt_4_measure(store, tmp_path):
    _keep(now=9000.0)                          # prompt 4 measured AFTER the re-test below
    _merge(tmp_path, made_at=5000.0)
    a = {w["id"]: w for w in rst.kept()}[rst.sid(A)]
    assert not a.get("retested") and len(a["trades"]) == 2


def test_an_unreadable_retest_file_keeps_the_kept_numbers(store, capsys):
    _keep()
    rst.now_path().write_bytes(b"not an npz")
    k = rst.kept()
    assert len(k) == 3 and not any(w.get("retested") for w in k)
    assert "could not be read" in capsys.readouterr().out


def test_nothing_is_published_from_a_retest_that_measured_nothing(store, tmp_path):
    _keep()
    _art(tmp_path / "empty", 0, 0, 1, [(A, [])])
    with pytest.raises(ValueError, match="not published"):
        rsd.merge({"arts": [str(tmp_path / "empty")], "end_ms": NEW_END, "reality": REAL,
                   "made_at": 1.0, "out": str(rst.now_path())})
    assert not rst.now_path().exists()


def test_a_slice_with_two_different_rule_lists_is_refused(store, tmp_path):
    _art(tmp_path / "x", 0, 0, 1, [(A, [])])
    _art(tmp_path / "x", 1, 0, 1, [(B, [])])
    with pytest.raises(ValueError, match="different rule lists"):
        rsd.merge({"arts": [str(tmp_path / "x")], "end_ms": NEW_END, "reality": REAL,
                   "made_at": 1.0, "out": str(rst.now_path())})


def test_never_half_a_market_a_missing_job_is_refused(store, tmp_path):
    """An account's share is checked WHOLE before anything is added up: a
    re-test missing one machine's coins would halve rows with nothing saying so."""
    a0, _ = _two_accounts(tmp_path)
    assert rst.check_complete(str(a0), "R0", reports=str(tmp_path / "rep0"))["chunks"] == 2
    _report(tmp_path / "rep0", 2)                               # a third shard measured coins...
    with pytest.raises(ValueError, match="missing"):           # ...and has no research job
        rst.check_complete(str(a0), "R0", reports=str(tmp_path / "rep0"))


# ------------------------------------------------------------ the chain
class FakeGitHub:
    """Every dispatch recorded; runs answer the status they are told to."""

    def __init__(self, fleets=("me/analyzer-x", "pal/analyzer-x")):
        self.fleets = list(fleets)
        self.sent: list = []
        self.status: dict = {}
        self.refuse: set = set()
        self.next_id = 100

    def dispatch(self, wf, inputs, repo, since=None):
        if repo in self.refuse:
            raise RuntimeError("HTTP 500")
        self.next_id += 1
        self.sent.append((wf, dict(inputs), repo, since))
        return self.next_id

    def run_status(self, run, repo):
        return self.status.get(run, {"status": "completed", "conclusion": "success", "machines": 20,
                                     "done": 20, "failed": [], "created": 0.0, "url": ""})


@pytest.fixture
def gh(monkeypatch, store):
    from tradingagents import cloud_sweep as cs
    from tradingagents import forecast_v2_daily as f2d

    fake = FakeGitHub()
    monkeypatch.setattr(f2d, "fleets_now", lambda: (list(fake.fleets), []))
    monkeypatch.setattr(f2d, "market", lambda: [f"C{i}_USDT" for i in range(10)])
    monkeypatch.setattr(f2d, "dispatch", fake.dispatch)
    monkeypatch.setattr(f2d, "run_status", fake.run_status)
    monkeypatch.setattr(cs, "sync_fleet", lambda slug, source="": "")
    _keep()
    monkeypatch.setattr(rsd, "listed", lambda: [A, B, C])
    return fake


AT_2AM = dt.datetime(2026, 10, 8, 2, 0).timestamp()


def test_due_once_a_local_day_after_1am_or_at_once_after_a_missed_day(gh):
    day = dt.date(2026, 10, 8)
    at = lambda h, m=0: dt.datetime.combine(day, dt.time(h, m)).timestamp()      # noqa: E731
    assert rsd.due(at(0, 30), {"started_day": "2026-10-07"})[0] is False, "yesterday's ran: wait for 1am"
    assert rsd.due(at(1, 0), {"started_day": "2026-10-07"}) == (True, "due")
    assert rsd.due(at(0, 30), {"started_day": "2026-10-05"})[0] is True, "a missed day runs at once"
    ok, why = rsd.due(at(9), {"started_day": "2026-10-08", "phase": "done", "done_at": at(2)})
    assert not ok and "today's re-test was made at Oct 08, 2026 2:00am" in why


def test_the_day_starts_a_replay_on_every_account_with_prompt_4s_settings(gh):
    st = {"phase": "idle"}
    rsd._step(st, AT_2AM)
    assert st["phase"] == "replay" and [s[0] for s in gh.sent] == ["replay.yml", "replay.yml"]
    piles = [s[1]["coin_list"].split(",") for s in gh.sent]
    assert sorted(piles[0] + piles[1]) == sorted(f"C{i}_USDT" for i in range(10)), "every coin once"
    for wf, inputs, repo, _ in gh.sent:
        assert inputs["start"] == "2026-07-01" and inputs["groups"] == "classic,preset"
        assert inputs["write_rule"] == "wr=60,trades=20,tp=any,windows=7|15|30"
        assert inputs["shards"] == 20
    assert set(st["replay_runs"]) == set(gh.fleets) and st["started_day"] == "2026-10-08"
    assert json.loads(rsd.state_path().read_text(encoding="utf-8"))["tried"], \
        "the attempt is on disk before the dispatch"


def test_a_refusing_account_is_asked_again_with_the_same_pile_then_the_day_is_given_up(gh):
    gh.refuse = {"pal/analyzer-x"}
    st = {"phase": "idle"}
    with pytest.raises(RuntimeError, match="refused"):
        rsd._step(st, AT_2AM)
    assert "me/analyzer-x" in st["plan"]["runs"]
    rsd._step(st, AT_2AM + 1800)                      # refused again: RETRIES + 1 tries, the day ends
    assert len([s for s in gh.sent if s[2] == "me/analyzer-x"]) == 1, "the started account is not asked twice"
    assert st["phase"] == "idle" and "given up" in st["error"] and st["started_day"] == "2026-10-08"
    assert "replay" in st["error"] and "plan" not in st


def test_an_account_whose_code_could_not_be_synced_never_measures(gh, monkeypatch):
    """Two halves on two versions of the code are not one measure."""
    from tradingagents import cloud_sweep as cs

    monkeypatch.setattr(cs, "sync_fleet", lambda slug, source="": "" if slug.startswith("me")
                        else f"{slug} could not be synced")
    st = {"phase": "idle"}
    with pytest.raises(RuntimeError, match="could not be synced"):
        rsd._step(st, AT_2AM)
    assert [s[2] for s in gh.sent] == ["me/analyzer-x"] and st["plan"]["tries"] == {"pal/analyzer-x": 1}


def test_the_retest_runs_on_each_accounts_own_replay_with_the_kept_list(gh, monkeypatch, tmp_path):
    from tradingagents import forecast_v2_daily as f2d

    st = {"phase": "idle"}
    rsd._step(st, AT_2AM)
    monkeypatch.setattr(rsd, "_download", lambda run, repo, pattern, dest: dest)
    monkeypatch.setattr(f2d, "read_reports", lambda dirs: {"end_ms": NEW_END, "universe": {"coins": 10}})
    monkeypatch.setattr(rst, "replay_shard_sizes",
                        lambda run, repo: {0: 9, 3: 9, 7: 9} if repo.startswith("me") else {1: 9, 2: 9})
    gh.sent.clear()
    rsd._step(st, AT_2AM + 600)
    assert st["phase"] == "research" and st["chunks"] == 10, "2 shards x 10 slices fills 20 machines"
    sent = {s[2]: s[1] for s in gh.sent}
    for repo, inputs in sent.items():
        assert inputs["source_run"] == st["replay_runs"][repo] and inputs["source_repo"] == repo
        assert inputs["scenarios"] == "file:research/p4/kept.json" and inputs["output"] == "full"
        assert inputs["end_ms"] == NEW_END and inputs["chunks"] == 10
    assert sent["me/analyzer-x"]["shards"] == "[0,3,7]" and sent["pal/analyzer-x"]["shards"] == "[1,2]"


def test_a_red_run_is_started_again_once_then_the_day_is_given_up(gh):
    st = {"phase": "idle"}
    rsd._step(st, AT_2AM)
    red = {"status": "completed", "conclusion": "failure", "machines": 20, "done": 20,
           "failed": ["replay (4)"], "created": 0.0, "url": ""}
    run = st["replay_runs"]["pal/analyzer-x"]
    gh.status[run] = red
    rsd._step(st, AT_2AM + 600)
    new = st["replay_runs"]["pal/analyzer-x"]
    assert new != run and st["phase"] == "replay", "that account alone, started again"
    gh.status[new] = red
    rsd._step(st, AT_2AM + 1200)
    assert st["phase"] == "idle" and "on every try" in st["error"]


def test_a_day_stuck_on_github_is_given_up_so_tomorrow_can_run(gh):
    st = {"phase": "idle"}
    rsd._step(st, AT_2AM)
    rsd._step(st, AT_2AM + rsd.STALE_S + 1)
    assert st["phase"] == "idle" and "not done" in st["error"]


def test_it_never_runs_under_a_test():
    assert rsd.tick() == {"why": "never under a test run"}


# ------------------------------------------------------- where it shows
def test_the_supervisor_starts_it_in_its_own_thread():
    src = (ROOT / "tradingagents/api.py").read_text(encoding="utf-8")
    assert '_th.Thread(target=_rsd.tick, name="room-strategies-retest", daemon=True).start()' in src
    route = src.split('def room_strategies_route(')[1].split("\n@app.")[0]
    assert 'out["retest"] = _rsd.status()' in route


def test_the_page_says_when_the_numbers_were_last_retested():
    src = (ROOT / "webapp/src/components/forecast/RoomForecasts.tsx").read_text(encoding="utf-8")
    s = src.split("export function RoomStrategiesSection()")[1].split("\nfunction StrategyTrades(")[0]
    assert "Last re-test: ${fmtWhen(d.retest.made_at)}" in s and "d.retest.why" in s
    assert "d.retest.error" in s and "re-tested every day on GitHub" in s


def test_the_research_run_is_named_the_way_the_dispatcher_finds_it():
    from tradingagents import forecast_v2_daily as f2d

    wf = (ROOT / ".github/workflows/research.yml").read_text(encoding="utf-8")
    assert ('run-name: "Watcher rules research · ${{ inputs.scenarios }} · ${{ inputs.output }} · '
            'replay ${{ inputs.source_run }}"') in wf
    assert f2d.title_of("research.yml", {"scenarios": "file:research/p4/kept.json", "output": "full",
                                         "source_run": 7}) == \
        "Watcher rules research · file:research/p4/kept.json · full · replay 7"
