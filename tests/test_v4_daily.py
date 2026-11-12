"""THE SKILL ROOMS' DAILY REFRESH (Nov 10, 2026; docs/superpowers/specs/2026-11-10-skill-rooms-design.md,
"4. The daily refresh" and the goals' "daily agreement check").

`tradingagents/v4_daily.py`: once a UTC day at 00:05 UTC every Backtest v4 strategy is measured again
on GitHub (every account), collected, the v4 store and Forecast v4 rebuilt in their own process, each
follower room's day list written ONCE, and yesterday's practice trades checked against the
re-measured backtest.

ONE TIMELINE. Every day, candle and run below sits on one clock: D = Nov 11, 2026 12:00am UTC (7:00pm
local the day before), a store whose trades open on day D-1, practice rows on the same hours. GitHub,
the exchange's coin list, the collect, the build and the switch-on are faked; nothing reaches the
network, and everything is written under tmp_path (the v4 home moved there, the acs folder through
conftest's sandbox of market_sweep.HOME).
"""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pytest

import tradingagents.auto_trader as at
from tradingagents import acs, profiles, stores
from tradingagents import forecast_v2_daily as fd
from tradingagents import v4_daily as vd
from tradingagents import v4_follow as vf
from tradingagents import v4_store

pytestmark = pytest.mark.unit

H = 3600
DAY = 86_400
D = int(dt.datetime(2026, 11, 11, tzinfo=dt.timezone.utc).timestamp())      # the chain's day, UTC
Y = D - DAY                                                                  # yesterday
AT = D + 10 * 60                                                             # 00:10 UTC
ROOMS = ["D7EN8BNV", "RSS7CUKH", "7T3VJU82"]
ME, PAL = "me/analyzer-x", "pal/analyzer-x"


def _iso(day_s: int) -> str:
    return dt.datetime.fromtimestamp(day_s, dt.timezone.utc).date().isoformat()


# ------------------------------------------------------------------ a tiny Backtest v4 store
def _pick(trades, strategy="bf_momentum", stop=0.03, target=None):
    label = f"{strategy}(lookback=2) stop {stop * 100:g}%" + (f" target {target * 100:g}%" if target else "")
    return {"label": label, "strategy": strategy, "params": {"lookback": 2}, "stop": stop, "target": target,
            "trades": trades}


def _line(coin, tf, picks, end_s=D):
    return {"coin": coin, "tf": tf, "fee": 0.00075, "slip": 0.0005, "bars": 500, "combos": len(picks),
            "split_ms": (end_s - 60 * DAY) * 1000, "start_ms": (end_s - 90 * DAY) * 1000,
            "end_ms": end_s * 1000, "bar": 0.0, "picks": picks}


def _build_store(tmp_path, lines: dict):
    folder = tmp_path / "src"
    folder.mkdir(exist_ok=True)
    (folder / "skilldaily.json").write_text(json.dumps({"lines": lines}), encoding="utf-8")
    v4_store.build(folder, target=stores.V4.rows_db, sources=v4_store.DAILY_SOURCES, log=lambda *_: None)


# ------------------------------------------------------------------ GitHub, faked
class FakeGitHub:
    def __init__(self):
        self.fleets = [ME, PAL]
        self.sent: list = []
        self.status: dict = {}
        self.refuse: dict = {}          # repo -> how many dispatches raise (-1: every one)
        self.next_id = 100
        self.on_dispatch = None

    def dispatch(self, wf, inputs, repo, since=None):
        if self.on_dispatch:
            self.on_dispatch(wf, inputs, repo, since)
        n = self.refuse.get(repo, 0)
        if n:
            if n > 0:
                self.refuse[repo] = n - 1
            self.sent.append(("REFUSED", dict(inputs), repo, since))
            raise RuntimeError("the skillbt.yml run did not appear within 90 seconds")
        self.next_id += 1
        self.sent.append((wf, dict(inputs), repo, since))
        return self.next_id

    def run_status(self, run, repo):
        return self.status.get(run, {"status": "completed", "conclusion": "success", "machines": 20,
                                     "done": 20, "failed": [], "created": 0.0, "url": ""})

    def ok(self):
        return [s for s in self.sent if s[0] != "REFUSED"]


class FakeAcs:
    """`acs.collect_skill("daily")` / `acs.collect_redo("daily")` as they behave: read the state
    file the chain wrote, write skilldaily.json, answer failed / not_reached / downloads_failed."""

    def __init__(self):
        self.failed: dict = {}          # coin -> "tf: error"
        self.unreached: set = set()
        self.downloads_failed: list = []
        self.collects = 0
        self.redo_states: list = []

    def collect_skill(self, skill_set="bt"):
        assert skill_set == "daily"
        self.collects += 1
        state = json.loads((acs.home() / "skilldaily-state.json").read_text(encoding="utf-8"))
        board = {c for r in state["runs"].values() for c in r["coin_list"]}
        lines, failed = {}, []
        for c in sorted(board - self.unreached):
            if c in self.failed:
                failed.append(f"{c} {self.failed[c]}")
                continue
            lines[f"{c}|1h"] = _line(c, "1h", [_pick([])])
        out = {"lines": lines, "failed": failed, "skipped": [], "not_reached": sorted(board & self.unreached),
               "downloads_failed": list(self.downloads_failed), "collected_s": AT, "set": "daily"}
        (acs.home() / "skilldaily.json").write_text(json.dumps(out), encoding="utf-8")
        return out

    def collect_redo(self, skill_set="bt"):
        assert skill_set == "daily"
        self.redo_states.append(json.loads((acs.home() / "skilldaily-redo-state.json").read_text(encoding="utf-8")))
        return {}                       # the redo measured nothing new: every coin still fails


@pytest.fixture
def world(tmp_path, monkeypatch):
    from tradingagents import cloud_sweep as cs
    from tradingagents import cq_search

    home = tmp_path / "v4"
    monkeypatch.setattr(stores, "V4", stores.Store(**{**stores.V4.__dict__, "home": home,
                                                      "rows_db": home / "rows.db"}))
    (home / "rooms").mkdir(parents=True)
    _build_store(tmp_path, {f"{c}|1h": _line(c, "1h", [_pick([])]) for c in ("AAA", "BBB", "CCC", "ZZZ")})
    gh, fa = FakeGitHub(), FakeAcs()
    monkeypatch.setattr(fd, "fleets_now", lambda: (list(gh.fleets), []))
    monkeypatch.setattr(fd, "market", lambda: ["AAA_USDT", "BBB_USDT", "CCC_USDT", "NEW_USDT"])
    monkeypatch.setattr(fd, "dispatch", gh.dispatch)
    monkeypatch.setattr(fd, "run_status", gh.run_status)
    monkeypatch.setattr(cs, "sync_fleet", lambda slug, source="": "")
    monkeypatch.setattr(cq_search, "quiet_hours", lambda now=None: False)
    monkeypatch.setattr(acs, "collect_skill", fa.collect_skill)
    monkeypatch.setattr(acs, "collect_redo", fa.collect_redo)
    # the child processes run here, in-process, with the fakes above
    monkeypatch.setattr(vd, "_child", lambda cmd, spec: vd.CHILD[cmd](spec))
    built: list = []

    def spawn(args, **kw):
        built.append(list(args))
        kw["stdout"].write("v4: 3 strategies, 0 trades, 0s\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(vd, "_spawn", spawn)
    return SimpleNamespace(gh=gh, acs=fa, home=home, lists=home / "rooms", built=built, tmp=tmp_path)


def _put_list(day_s, rooms, **extra):
    vf.list_path(day_s).write_text(json.dumps({"day": _iso(day_s), "day_s": day_s, "made_s": day_s + 300,
                                                "fallback_from": None, "rooms": rooms, **extra}),
                                   encoding="utf-8")


def _read_list(day_s):
    return json.loads(vf.list_path(day_s).read_text(encoding="utf-8"))


def _row(sid, coin="AAA", tf="1h"):
    return {"sid": 1, "id": sid, "coin": coin, "tf": tf, "strategy": "bf_momentum", "label": "bf test",
            "skill": "backtesting-frameworks", "params": {"lookback": 2}, "stop": 0.03, "target": None,
            "fee": 0.00075, "slip": 0.0005, "n": 25, "wins": 24}


def _started(now=AT):
    """A chain begun for day D, its deal and runs made."""
    st = {"phase": "idle"}
    vd._step(st, now)                       # due: the chain begins
    assert st["phase"] == "dispatch"
    vd._step(st, now + vd.POLL_S)           # the dispatch
    return st


# ------------------------------------------------------------------ when it runs
def test_due_once_a_utc_day_after_0005(world):
    assert vd.due(D + 4 * 60, {}) is False, "00:04 UTC: the day's candles are not all closed on GitHub yet"
    assert vd.due(D + 5 * 60, {}) is True
    assert vd.due(D + 5 * 60, {"day": _iso(Y), "phase": "done"}) is True, "yesterday's chain does not hold today's"
    assert vd.due(D + 9 * H, {"day": _iso(D), "phase": "done"}) is False, "once a day"
    assert vd.due(D + 9 * H, {"day": _iso(D), "phase": "given_up"}) is False, "a given-up day is not re-run"
    assert vd.due(D + DAY + 5 * 60, {"day": _iso(D), "phase": "done"}) is True, "tomorrow at 00:05 UTC"


def test_tick_does_nothing_under_pytest(world):
    assert vd.tick() == {"why": "never under a test run"}
    assert not vd.state_path().exists(), "no state was written"
    assert world.gh.sent == []


def test_title_of_skillbt():
    inputs = {"shards": "20", "coin_list": "BTC,ETH", "label": f"v4 daily {_iso(D)}", "set": "daily"}
    assert fd.title_of("skillbt.yml", inputs) == f"Skill backtest · v4 daily {_iso(D)}"
    # the workflow's own run-name, which the dispatcher matches
    from pathlib import Path

    wf = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "skillbt.yml").read_text(encoding="utf-8")
    assert 'run-name: "Skill backtest · ${{ inputs.label }}"' in wf


# ------------------------------------------------------------------ the dispatch
def test_the_deal_is_saved_before_the_dispatch(world):
    seen = []

    def check(wf, inputs, repo, since):
        on_disk = json.loads(vd.state_path().read_text(encoding="utf-8"))
        seen.append((repo, on_disk.get("deal"), on_disk.get("tried")))

    world.gh.on_dispatch = check
    st = _started()
    assert st["phase"] == "running"
    assert len(seen) == 2
    for repo, deal, tried in seen:
        assert deal and sorted(sum(deal.values(), [])) == ["AAA", "BBB", "CCC"], "every pinned, traded coin once"
        assert any(repo in k for k in tried), "the attempt is on disk before the dispatch"
    sent = world.gh.ok()
    assert {s[2] for s in sent} == {ME, PAL}
    for wf, inputs, repo, _ in sent:
        assert wf == "skillbt.yml" and inputs["set"] == "daily" and inputs["shards"] == "20"
        assert inputs["label"] == f"v4 daily {_iso(D)}"
        assert inputs["coin_list"] and "_USDT" not in inputs["coin_list"], "bare coins, never an empty list"
    assert sorted(",".join(s[1]["coin_list"] for s in sent).split(",")) == ["AAA", "BBB", "CCC"]


def test_delisted_pinned_coins_are_named_not_missing(world):
    st = _started()
    assert st["delisted"] == ["ZZZ"], "in the store, no longer traded: named"
    assert st["not_added"] == 1, "NEW is a new listing: counted, never added"
    assert "ZZZ" not in ",".join(s[1]["coin_list"] for s in world.gh.ok())
    vd._step(st, AT + 2 * vd.POLL_S)        # running -> collect
    assert st["phase"] == "collect"
    vd._step(st, AT + 3 * vd.POLL_S)        # the collect
    assert st["phase"] == "build"
    assert st["missing"] == [] and st["failed"] == [], "a delisted coin is not a missing one"
    assert "ZZZ" in vd.status()["delisted"]


def test_a_late_listed_run_is_adopted(world):
    world.gh.refuse = {PAL: 1}          # GitHub took it but listed it late: the call raised
    st = {"phase": "idle"}
    vd._step(st, AT)
    with pytest.raises(RuntimeError, match="tried again"):
        vd._step(st, AT + vd.POLL_S)
    first = [s for s in world.gh.sent if s[2] == PAL][0]
    assert first[3] is None, "the first attempt has nothing to adopt"
    tried_at = AT + vd.POLL_S
    st["failed_at"] = tried_at
    vd._step(st, tried_at + vd.RETRY_S)
    again = [s for s in world.gh.sent if s[2] == PAL][1]
    assert again[3] == tried_at, "the retry passes when the first attempt was made, so a late-listed run is adopted"
    assert len([s for s in world.gh.ok() if s[2] == ME]) == 1, "the account that took it is not asked twice"
    assert st["phase"] == "running"


def test_an_account_refusing_twice_gives_the_day_up_named(world):
    _put_list(Y, {r: [_row("OLD1")] for r in ROOMS})
    world.gh.refuse = {PAL: -1}
    st = {"phase": "idle"}
    vd._step(st, AT)
    with pytest.raises(RuntimeError):
        vd._step(st, AT + vd.POLL_S)
    st["failed_at"] = AT + vd.POLL_S
    vd._step(st, AT + vd.POLL_S + vd.RETRY_S)
    assert st["phase"] == "given_up"
    assert "pal" in st["error"] and "refused" in st["error"]
    doc = _read_list(D)
    assert doc["fallback_from"] == _iso(Y) and doc["rooms"] == {r: [_row("OLD1")] for r in ROOMS}, \
        "the day is given up with yesterday's list, said"


# ------------------------------------------------------------------ the collect
def test_a_green_run_with_no_coins_is_red(world):
    st = _started()
    pal_pile = st["deal"][PAL]
    world.acs.unreached = set(pal_pile)          # green, but no machine of pal's run measured a coin
    vd._step(st, AT + 2 * vd.POLL_S)             # -> collect
    vd._step(st, AT + 3 * vd.POLL_S)             # the collect: pal measured nothing -> started again
    assert st["phase"] == "running"
    redo = world.gh.ok()[-1]
    assert redo[2] == PAL and redo[1]["coin_list"].split(",") == pal_pile, "the same pile, again"
    vd._step(st, AT + 4 * vd.POLL_S)             # -> collect
    vd._step(st, AT + 5 * vd.POLL_S)             # still nothing: the day is given up, named
    assert st["phase"] == "given_up"
    assert "pal" in st["error"] and "no coin" in st["error"]
    assert world.built == [], "the store is never built from part of the market"


def test_a_red_run_with_nothing_to_download_gets_its_one_redo_not_a_download_retry(world):
    st = _started()
    pal_run = st["runs"][PAL]
    world.gh.status[pal_run] = {"status": "completed", "conclusion": "failure", "machines": 20, "done": 20,
                                "failed": ["measure (0)"], "created": 0.0, "url": ""}
    world.acs.downloads_failed = [f"{PAL}: no valid artifacts found to download"]
    world.acs.unreached = set(st["deal"][PAL])
    vd._step(st, AT + 2 * vd.POLL_S)
    vd._step(st, AT + 3 * vd.POLL_S)
    assert st["phase"] == "running" and st["runs"][PAL] != pal_run, "started again with the same pile"
    assert "dl_tries" not in st


def test_a_redo_dispatch_that_raises_is_adopted_without_collecting_again(world):
    st = _started()
    world.acs.unreached = set(st["deal"][PAL])
    vd._step(st, AT + 2 * vd.POLL_S)             # -> collect
    world.gh.refuse = {PAL: 1}
    with pytest.raises(RuntimeError):
        vd._step(st, AT + 3 * vd.POLL_S)         # zero coins: the redo's dispatch raised
    assert world.acs.collects == 1
    st["failed_at"] = AT + 3 * vd.POLL_S
    vd._step(st, AT + 3 * vd.POLL_S + vd.RETRY_S)
    assert world.acs.collects == 1, "the pending redo is dispatched again, nothing is downloaded again"
    last = world.gh.sent[-1]
    assert last[2] == PAL and last[3] == AT + 3 * vd.POLL_S, "since= the first attempt: a late run is adopted"
    assert st["phase"] == "running"


def test_a_short_coin_list_from_the_exchange_is_not_read_as_delistings(world, monkeypatch):
    _started()
    monkeypatch.setattr(fd, "market", lambda: ["AAA_USDT"])     # 1 coin against 4 last time
    st = {"phase": "idle"}
    vd._step(st, D + DAY + 600)
    with pytest.raises(RuntimeError, match="short list"):
        vd._step(st, D + DAY + 600 + vd.POLL_S)


def test_the_kept_copy_failing_never_builds_the_store_again(world, monkeypatch):
    def broken():
        raise OSError("disk full")

    monkeypatch.setattr(vd, "_keep_prev", broken)
    st = {"phase": "build", "day": _iso(D), "day_s": D, "deadline_s": D + vd.GIVE_UP_AT_S}
    vd._step(st, AT)
    assert st["phase"] == "lists" and "disk full" in st["prev_error"] and len(world.built) == 1


def test_an_unreadable_earlier_list_is_skipped_for_the_one_before_it(world):
    _put_list(Y - DAY, {"D7EN8BNV": [_row("GOOD")]})
    vf.list_path(Y).write_text("{half a file", encoding="utf-8")
    st = {"phase": "running", "day": _iso(D), "day_s": D, "deadline_s": D + vd.GIVE_UP_AT_S, "runs": {}}
    vd._step(st, D + vd.GIVE_UP_AT_S)
    assert st["phase"] == "given_up" and _read_list(D)["fallback_from"] == _iso(Y - DAY)


def test_a_failed_coin_is_redone_alone_then_kept_stale(world):
    # yesterday's collected file: AAA's 1h line (the store was built from it)
    prev = {"lines": {"AAA|1h": _line("AAA", "1h", [_pick([[Y * 1000, (Y + H) * 1000, 1, "TP", 1.0]])],
                                      end_s=Y)}}
    (acs.home() / "skilldaily-prev.json").write_text(json.dumps(prev), encoding="utf-8")
    world.acs.failed = {"AAA": "1h: ConnectionError: cut"}
    world.acs.unreached = {"CCC"}               # dealt with AAA to one account, BBB to the other
    st = _started()
    n0 = len(world.gh.ok())
    vd._step(st, AT + 2 * vd.POLL_S)             # -> collect
    vd._step(st, AT + 3 * vd.POLL_S)             # the collect: AAA failed, CCC not reached
    assert st["phase"] == "collect"
    vd._step(st, AT + 4 * vd.POLL_S)             # the redo: those two coins ALONE
    redo = world.gh.ok()[n0:]
    assert sorted(",".join(s[1]["coin_list"] for s in redo).split(",")) == ["AAA", "CCC"], "only the two coins"
    assert all(s[1]["label"] == f"v4 daily {_iso(D)} redo" for s in redo)
    assert all(s[1]["coin_list"] for s in redo), "an empty pile is never sent (it would mean every coin)"
    vd._step(st, AT + 5 * vd.POLL_S)             # the redo ran, collected, still failing
    assert world.acs.redo_states, "the redo's lines were collected through acs.collect_redo"
    assert st["phase"] == "build"
    assert st["stale"] == {"AAA": ["1h"]}, "AAA keeps yesterday's line, marked stale"
    assert st["missing"] == ["CCC"], "CCC had no earlier line: absent that day, named"
    got = json.loads((acs.home() / "skilldaily.json").read_text(encoding="utf-8"))
    assert got["lines"]["AAA|1h"]["stale"] is True
    assert got["lines"]["AAA|1h"]["picks"] == prev["lines"]["AAA|1h"]["picks"]
    assert "CCC|1h" not in got["lines"]
    assert "BBB|1h" in got["lines"] and "stale" not in got["lines"]["BBB|1h"]


def test_quiet_hours_name_the_coins_and_skip_the_redo(world, monkeypatch):
    from tradingagents import cq_search

    world.acs.unreached = {"CCC"}
    st = _started()
    vd._step(st, AT + 2 * vd.POLL_S)
    vd._step(st, AT + 3 * vd.POLL_S)
    n0 = len(world.gh.ok())
    monkeypatch.setattr(cq_search, "quiet_hours", lambda now=None: True)
    vd._step(st, AT + 4 * vd.POLL_S)            # no redo: CCC is named and the collect finishes
    assert len(world.gh.ok()) == n0, "nothing is dispatched in the nightly jobs' hours"
    assert st["phase"] == "build" and st["missing"] == ["CCC"]
    assert "12:45am" in st["collect"]["redo_skipped"]


def test_a_failed_download_is_collected_again_then_gives_the_day_up(world):
    st = _started()
    world.acs.downloads_failed = [f"{PAL}: HTTP 502"]
    vd._step(st, AT + 2 * vd.POLL_S)
    with pytest.raises(RuntimeError, match="downloaded"):
        vd._step(st, AT + 3 * vd.POLL_S)
    st["failed_at"] = AT + 3 * vd.POLL_S
    vd._step(st, AT + 3 * vd.POLL_S + vd.RETRY_S)
    assert st["phase"] == "given_up" and "pal" in st["error"]
    assert world.built == []


# ------------------------------------------------------------------ the build
def test_the_build_runs_in_its_own_process_with_a_log_and_keeps_the_file_it_built_from(world):
    st = _started()
    vd._step(st, AT + 2 * vd.POLL_S)
    vd._step(st, AT + 3 * vd.POLL_S)
    assert st["phase"] == "build"
    vd._step(st, AT + 4 * vd.POLL_S)
    assert world.built and world.built[0][-4:] == ["-m", "tradingagents.v4_store", "build", "--daily"]
    assert "v4: 3 strategies" in vd.log_path().read_text(encoding="utf-8")
    assert st["phase"] == "lists"
    assert (acs.home() / "skilldaily-prev.json").read_text(encoding="utf-8") == \
        (acs.home() / "skilldaily.json").read_text(encoding="utf-8"), "tomorrow's stale lines come from what was built"


def test_a_failed_build_is_named_with_its_last_lines(world, monkeypatch):
    def spawn(args, **kw):
        kw["stdout"].write("v4 daily build FAILED: RuntimeError: nothing was filed\n")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(vd, "_spawn", spawn)
    st = {"phase": "build", "day": _iso(D), "day_s": D, "deadline_s": D + vd.GIVE_UP_AT_S, "runs": {}}
    with pytest.raises(RuntimeError, match="nothing was filed"):
        vd._step(st, AT)
    assert st["phase"] == "build"


# ------------------------------------------------------------------ the day lists
def test_lists_written_for_every_follower_room(world, monkeypatch):
    from tradingagents import forecast_v4 as f4

    calls = []

    def switched_on(rule, at_s, db=None):
        calls.append((dict(rule), at_s))
        pid = next(p for p in ROOMS if profiles.v4_rule(p) == rule)
        return [_row(f"ON{pid[:4]}")]

    monkeypatch.setattr(f4, "switched_on", switched_on)
    st = {"phase": "lists", "day": _iso(D), "day_s": D, "deadline_s": D + vd.GIVE_UP_AT_S, "runs": {}}
    vd._step(st, AT)
    doc = _read_list(D)
    assert set(doc["rooms"]) == set(ROOMS) and doc["fallback_from"] is None
    for pid in ROOMS:
        assert doc["rooms"][pid] == [_row(f"ON{pid[:4]}")]
    assert [a for _, a in calls] == [D, D, D], "judged at the day's own midnight, once per room"
    assert st["phase"] == "agree" and st["landed_s"] == AT
    # a list is written ONCE: the follower may already have read it
    _put_list(D + DAY, {"D7EN8BNV": [_row("KEEP")]})
    st = {"phase": "lists", "day": _iso(D + DAY), "day_s": D + DAY, "deadline_s": D + DAY + vd.GIVE_UP_AT_S}
    vd._step(st, D + DAY + 600)
    assert _read_list(D + DAY)["rooms"] == {"D7EN8BNV": [_row("KEEP")]}, "never rewritten"


def test_give_up_at_0600_copies_yesterdays_list_with_fallback(world):
    _put_list(Y, {r: [_row("YDAY")] for r in ROOMS})
    st = {"phase": "running", "day": _iso(D), "day_s": D, "deadline_s": D + vd.GIVE_UP_AT_S,
          "runs": {ME: 7}, "deal": {ME: ["AAA"]}}
    world.gh.status[7] = {"status": "in_progress", "conclusion": None, "machines": 20, "done": 3,
                          "failed": [], "created": 0.0, "url": ""}
    vd._step(st, D + vd.GIVE_UP_AT_S - 1)
    assert st["phase"] == "running", "before 06:00 UTC it keeps waiting"
    vd._step(st, D + vd.GIVE_UP_AT_S)
    assert st["phase"] == "given_up"
    doc = _read_list(D)
    assert doc["fallback_from"] == _iso(Y) and doc["rooms"] == {r: [_row("YDAY")] for r in ROOMS}
    from tradingagents.positions_view import fmt_when

    assert f"a copy of the list of {fmt_when(Y)}" in st["why"], "said, in the one date format"
    assert _iso(Y) not in st["why"], "never the files' own day name on screen"


def test_a_missed_day_gets_its_fallback_list_first_and_no_list_is_rewritten(world):
    _put_list(D - 3 * DAY, {"D7EN8BNV": [_row("OLD3")]})
    st = {"phase": "idle"}
    vd._step(st, AT)                             # the PC was off for two days: D-2 and D-1 have no list
    for d in (D - 2 * DAY, D - DAY):
        doc = _read_list(d)
        assert doc["fallback_from"] == _iso(D - 3 * DAY) and doc["rooms"] == {"D7EN8BNV": [_row("OLD3")]}
    assert _read_list(D - 3 * DAY)["fallback_from"] is None, "a day that has a list keeps it"
    assert not vf.list_path(D).exists(), "today's list waits for today's measurement"
    assert [f["day"] for f in st["fallbacks"]] == [_iso(D - 2 * DAY), _iso(D - DAY)]


# ------------------------------------------------------------------ the agreement check
ROOM = "D7EN8BNV"


def _practice_exit(sid, en, ex_close, why, pnl, side="LONG", tid=None):
    return {"ts": ex_close, "symbol": "AAA_USDT", "action": "exit", "why": why, "strategy": f"v4_{sid}",
            "trade_id": tid or f"T{en}", "entry_ts": en, "opened_at": en + H, "side": side, "pnl_est": pnl,
            "dry_run": True, "v4_id": sid}


def test_agreement_judges_each_trade_on_the_day_it_closed_and_names_the_rest(world):
    pick = _pick([
        [(Y - 5 * H) * 1000, (Y - 3 * H) * 1000, 1, "TP", 2.0],        # CLOSED the day before: not this day's
        [(Y - 1 * H) * 1000, (Y + 2 * H) * 1000, 1, "TP", 0.70],        # opened the day before, closed today
        [(Y + 1 * H) * 1000, (Y + 3 * H) * 1000, 1, "TP", 1.00],        # the same in practice
        [(Y + 5 * H) * 1000, (Y + 6 * H) * 1000, -1, "SL", -0.80],      # practice closed a candle later
        [(Y + 10 * H) * 1000, (Y + 12 * H) * 1000, 1, "SIGNAL", 0.30],  # practice never made it
        [(Y + 22 * H) * 1000, (Y + 23 * H) * 1000, 1, "TP", 0.50],      # the day's LAST candle: closes at midnight
        [(Y + 23 * H) * 1000, (Y + 24 * H) * 1000, 1, "TP", 0.40],      # closes tomorrow: tomorrow's check
        [(Y + 23 * H + 1800) * 1000, (D + 3 * H) * 1000, 1, "END", 0.1],  # still open: never a trade
    ])
    _build_store(world.tmp, {"AAA|1h": _line("AAA", "1h", [pick])})
    sid = v4_store.row_id("AAA", "1h", pick)
    _put_list(Y - DAY, {ROOM: [_row(sid)]})
    _put_list(Y, {ROOM: [_row(sid)]})
    with profiles.using(ROOM):
        for r in (_practice_exit(sid, Y - 1 * H, Y + 3 * H, "TP", 0.70, tid="OVERNGT0"),
                  _practice_exit(sid, Y + 1 * H, Y + 4 * H, "TP", 0.98, tid="SAME0001"),
                  _practice_exit(sid, Y + 5 * H, Y + 8 * H, "SL", -0.85, side="SHORT", tid="LATER002"),
                  _practice_exit(sid, Y + 14 * H, Y + 16 * H, "SIGNAL", 0.10, tid="EXTRA003"),
                  _practice_exit(sid, Y + 22 * H, D, "TP", 0.50, tid="LASTC004"),
                  _practice_exit(sid, Y + 23 * H, D + H, "TP", 0.40, tid="TMRW0005"),
                  _practice_exit(sid, Y - 5 * H, Y - 2 * H, "TP", 2.0, tid="BEFORE06")):
            at.append_ledger(r)
    res = vd.agreement(ROOM, Y)
    assert res["day"] == _iso(Y)
    assert res["same"] == 3, "the overnight trade, the 1am trade and the day's last candle all match"
    assert res["of"] == 6, "every trade either side CLOSED that day, a pair counted once"
    assert res["dollars_apart"] == 0.02, "the dollars beside the count, never hidden in a tolerance"
    assert sorted(res["only_practice"]) == ["EXTRA003", "LATER002"]
    assert len(res["only_backtest"]) == 2 and all(b.startswith(sid) for b in res["only_backtest"])
    assert "open_at_midnight" not in res
    assert vd.agreement(ROOM, Y + DAY)["same"] == 1, "the trade closing after midnight is the next day's"


def test_a_1d_trade_opened_two_days_before_is_compared_on_the_day_it_closed(world):
    pick = _pick([[(Y - 2 * DAY) * 1000, Y * 1000, 1, "TP", 3.0]])   # 1d candles: opened Y-2, exit candle Y
    _build_store(world.tmp, {"AAA|1d": _line("AAA", "1d", [pick])})
    sid = v4_store.row_id("AAA", "1d", pick)
    _put_list(Y - 2 * DAY, {ROOM: [_row(sid, tf="1d")]})
    with profiles.using(ROOM):
        at.append_ledger(_practice_exit(sid, Y - 2 * DAY, Y + DAY, "TP", 3.01, tid="DAILY001"))
    res = vd.agreement(ROOM, Y)
    assert (res["same"], res["of"], res["dollars_apart"]) == (1, 1, 0.01)


def test_a_trade_of_a_strategy_not_on_its_entry_days_list_is_not_expected(world):
    pick = _pick([[(Y - 2 * H) * 1000, (Y + 1 * H) * 1000, 1, "TP", 1.0],   # opened on Y-1: not switched on then
                  [(Y + 4 * H) * 1000, (Y + 5 * H) * 1000, 1, "SL", -1.0]])  # opened on Y: switched on
    other = _pick([[(Y + 1 * H) * 1000, (Y + 2 * H) * 1000, 1, "TP", 1.0]], strategy="sma_crossover")
    _build_store(world.tmp, {"AAA|1h": _line("AAA", "1h", [pick]), "BBB|1h": _line("BBB", "1h", [other])})
    sid = v4_store.row_id("AAA", "1h", pick)
    _put_list(Y - DAY, {ROOM: []})
    _put_list(Y, {ROOM: [_row(sid)]})
    res = vd.agreement(ROOM, Y)
    assert res["of"] == 1 and res["only_backtest"] == [f"{sid} {vd._when(Y + 4 * H)}"], \
        "only the trade opened while it was switched on; BBB was never switched on in this room"


def test_the_agree_phase_catches_up_one_file_per_missed_day(world):
    (vf.lists_home() / f"agree-{_iso(Y - 3 * DAY)}.json").write_text(json.dumps({ROOM: {"same": 1, "of": 1}}),
                                                                     encoding="utf-8")
    st = {"phase": "agree", "day": _iso(D), "day_s": D, "deadline_s": D + vd.GIVE_UP_AT_S, "landed_s": AT}
    vd._step(st, AT)
    for d in (Y - 2 * DAY, Y - DAY, Y):
        doc = json.loads((vf.lists_home() / f"agree-{_iso(d)}.json").read_text(encoding="utf-8"))
        assert set(doc) == set(ROOMS) and doc[ROOM]["day"] == _iso(d)
    assert st["agreed_days"] == [_iso(Y - 2 * DAY), _iso(Y - DAY), _iso(Y)]
    assert st["phase"] == "done"


def test_a_side_that_differs_is_not_the_same(world):
    pick = _pick([[(Y + 1 * H) * 1000, (Y + 3 * H) * 1000, 1, "TP", 1.0]])
    _build_store(world.tmp, {"AAA|1h": _line("AAA", "1h", [pick])})
    sid = v4_store.row_id("AAA", "1h", pick)
    _put_list(Y, {ROOM: [_row(sid)]})
    with profiles.using(ROOM):
        at.append_ledger(_practice_exit(sid, Y + 1 * H, Y + 4 * H, "TP", 1.0, side="SHORT", tid="SHORT001"))
    res = vd.agreement(ROOM, Y)
    assert res["same"] == 0 and res["only_practice"] == ["SHORT001"] and len(res["only_backtest"]) == 1


def test_the_agree_phase_saves_one_file_and_the_follower_reads_the_newest(world):
    st = {"phase": "agree", "day": _iso(D), "day_s": D, "deadline_s": D + vd.GIVE_UP_AT_S, "landed_s": AT}
    vd._step(st, AT)
    assert st["phase"] == "done"
    path = vf.lists_home() / f"agree-{_iso(Y)}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert set(doc) == set(ROOMS) and doc[ROOM]["of"] == 0
    with profiles.using(ROOM):
        assert "agreement" not in vf.load(), "never written into the follower's own state"
    older = vf.lists_home() / f"agree-{_iso(Y - DAY)}.json"
    older.write_text(json.dumps({ROOM: {"day": _iso(Y - DAY), "same": 9, "of": 9}}), encoding="utf-8")
    assert vf.status(ROOM, now_s=AT)["agreement"]["day"] == _iso(Y), "the newest check"
    assert sorted(vf._Reads(AT, None, None, None, None).list_days()) == [], "an agree file is never a day list"


def test_a_whole_day_from_due_to_done_one_phase_a_call(world, monkeypatch):
    from tradingagents import forecast_v4 as f4

    monkeypatch.setattr(f4, "switched_on", lambda rule, at_s, db=None: [_row("ONE")])
    _put_list(Y, {r: [] for r in ROOMS})
    st, now, seen = {"phase": "idle"}, AT, []
    while st.get("phase") != "done" and len(seen) < 20:
        vd._step(st, now)
        vd._write(st)                            # what tick() does after every step
        seen.append(st["phase"])
        now += vd.POLL_S
    assert seen == ["dispatch", "running", "collect", "build", "lists", "agree", "done"], seen
    assert _read_list(D)["rooms"] == {r: [_row("ONE")] for r in ROOMS}
    assert (vf.lists_home() / f"agree-{_iso(Y)}.json").exists()
    s = vd.status()
    assert s["phase"] == "done" and s["day"] == _iso(D) and s["landed_s"] and "landed" in s["why"]
    assert s["deal"] == {"me": 2, "pal": 1} and s["delisted"] == ["ZZZ"] and s["missing"] == []
    vd._step(st, now + DAY // 2)
    assert st["phase"] == "done", "once a day"


# ------------------------------------------------------------------ the first refresh
def test_start_now_starts_today_at_once_but_never_in_quiet_hours(world, monkeypatch):
    from tradingagents import cq_search

    monkeypatch.setattr(cq_search, "quiet_hours", lambda now=None: True)
    with pytest.raises(RuntimeError, match="12:45am"):
        vd.start_now(D + 15 * H)
    monkeypatch.setattr(cq_search, "quiet_hours", lambda now=None: False)
    out = vd.start_now(D + 15 * H)                 # 3:00pm UTC: due() would have run at 00:05
    st = vd.read()
    assert out["phase"] == "dispatch" and st["day"] == _iso(D)
    assert st["deadline_s"] >= D + 15 * H + vd.GIVE_UP_AT_S, "a late first refresh is not given up at 06:00"
    with pytest.raises(RuntimeError, match="already") as err:
        vd.start_now(D + 15 * H + 60)
    from tradingagents.positions_view import fmt_when

    assert fmt_when(D) in str(err.value) and _iso(D) not in str(err.value), "the one date format"


# ------------------------------------------------------------------ the build against the 06:00 cut-off
def _slow_build(monkeypatch, code: int, takes_s: int):
    """A build that takes `takes_s` seconds of the chain's own clock and ends with `code`."""
    clock = {"t": 0.0}
    monkeypatch.setattr(vd, "_mono", lambda: clock["t"])

    def spawn(args, **kw):
        clock["t"] += takes_s
        kw["stdout"].write("v4 daily build FAILED: RuntimeError: boom\n" if code else "v4: built\n")
        return SimpleNamespace(returncode=code)

    monkeypatch.setattr(vd, "_spawn", spawn)


def test_a_build_finishing_after_0600_writes_the_real_lists(world, monkeypatch):
    from tradingagents import forecast_v4 as f4

    _put_list(Y, {r: [_row("YDAY")] for r in ROOMS})
    monkeypatch.setattr(f4, "switched_on", lambda rule, at_s, db=None: [_row("FRESH")])
    _slow_build(monkeypatch, 0, 3600)
    start = D + vd.GIVE_UP_AT_S - 1800                 # 5:30am UTC, an hour's build
    st = {"phase": "build", "day": _iso(D), "day_s": D, "deadline_s": D + vd.GIVE_UP_AT_S}
    vd._step(st, start)
    assert st["phase"] == "lists" and st["built_day"] == _iso(D)
    vd._step(st, start + 3600 + vd.POLL_S)             # 6:32am: past the cut-off, the store is today's
    doc = _read_list(D)
    assert doc["fallback_from"] is None and doc["rooms"] == {r: [_row("FRESH")] for r in ROOMS}
    assert st["phase"] == "agree"


def test_a_build_failing_after_0600_gives_up_at_once(world, monkeypatch):
    _put_list(Y, {r: [_row("YDAY")] for r in ROOMS})
    _slow_build(monkeypatch, 1, 3600)
    st = {"phase": "build", "day": _iso(D), "day_s": D, "deadline_s": D + vd.GIVE_UP_AT_S}
    vd._step(st, D + vd.GIVE_UP_AT_S - 1800)
    assert st["phase"] == "given_up" and "boom" in st["error"]
    assert _read_list(D)["fallback_from"] == _iso(Y), "the day's list is yesterday's copy, said"


def test_the_lists_still_give_up_at_the_next_midnight(world, monkeypatch):
    from tradingagents import forecast_v4 as f4

    def broken(rule, at_s, db=None):
        raise RuntimeError("store locked")

    monkeypatch.setattr(f4, "switched_on", broken)
    _put_list(Y, {r: [_row("YDAY")] for r in ROOMS})
    st = {"phase": "lists", "day": _iso(D), "day_s": D, "deadline_s": D + vd.GIVE_UP_AT_S, "built_day": _iso(D)}
    with pytest.raises(RuntimeError):
        vd._step(st, D + 8 * H)                          # past 06:00, built: still tried
    vd._step(st, D + DAY)
    assert st["phase"] == "given_up", "a list that cannot be worked out never holds the rooms past the day"


def test_a_collect_ending_after_0600_sends_no_redo(world, monkeypatch):
    world.acs.unreached = {"CCC"}
    st = _started()
    vd._step(st, AT + 2 * vd.POLL_S)             # -> collect
    clock = {"t": 0.0}
    monkeypatch.setattr(vd, "_mono", lambda: clock["t"])
    real = vd._child

    def slow(cmd, spec):
        clock["t"] += vd.GIVE_UP_AT_S             # the downloads took six hours
        return real(cmd, spec)

    monkeypatch.setattr(vd, "_child", slow)
    n0 = len(world.gh.sent)
    vd._step(st, AT + 3 * vd.POLL_S)
    assert st["phase"] == "given_up" and len(world.gh.sent) == n0, "no machines for a day already lost"


# ------------------------------------------------------------------ the coin redo, adopted and resumed
def _to_the_redo(world):
    world.acs.failed = {"AAA": "1h: ConnectionError: cut"}
    world.acs.unreached = {"CCC"}
    st = _started()
    vd._step(st, AT + 2 * vd.POLL_S)             # -> collect
    vd._step(st, AT + 3 * vd.POLL_S)             # the collect: AAA failed, CCC not reached
    return st


def test_a_raising_redo_dispatch_is_retried_and_its_late_run_adopted(world):
    st = _to_the_redo(world)
    world.gh.refuse = {PAL: 1}
    with pytest.raises(RuntimeError, match="redo"):
        vd._step(st, AT + 4 * vd.POLL_S)
    first = [s for s in world.gh.sent if s[2] == PAL][-1]
    assert first[0] == "REFUSED" and first[3] is None
    assert st["collect"]["redo_pending"] == {PAL: ["CCC"]}, "what is still to start is kept"
    st["failed_at"] = AT + 4 * vd.POLL_S
    vd._step(st, AT + 4 * vd.POLL_S + vd.RETRY_S)
    again = [s for s in world.gh.sent if s[2] == PAL][-1]
    assert again[0] == "skillbt.yml" and again[3] == AT + 4 * vd.POLL_S, "since= the first attempt: adopted"
    assert set(st["collect"]["redo_runs"]) == {ME, PAL} and not st["collect"]["redo_pending"]
    assert len([s for s in world.gh.ok() if s[2] == ME and "redo" in s[1]["label"]]) == 1, "ME is not asked twice"


def test_a_restart_mid_redo_resumes_it(world):
    st = _to_the_redo(world)

    def killed(wf, inputs, repo, since):
        if "redo" in inputs["label"] and repo == PAL:
            world.gh.on_dispatch = None
            raise SystemExit("the API was restarted during the 90 s wait")

    world.gh.on_dispatch = killed
    with pytest.raises(SystemExit):
        vd._step(st, AT + 4 * vd.POLL_S)
    on_disk = vd.read()                                   # the restarted process reads the state again
    assert on_disk["collect"]["redo_pending"].get(PAL) == ["CCC"]
    vd._step(on_disk, AT + 5 * vd.POLL_S)
    resumed = [s for s in world.gh.ok() if s[2] == PAL and "redo" in s[1]["label"]]
    assert len(resumed) == 1 and resumed[0][3] == AT + 4 * vd.POLL_S, "resumed, adopting what GitHub took"
    assert set(on_disk["collect"]["redo_runs"]) == {ME, PAL}


def test_a_redo_refused_twice_is_named_on_the_screen(world):
    st = _to_the_redo(world)
    world.gh.refuse = {PAL: -1}
    with pytest.raises(RuntimeError):
        vd._step(st, AT + 4 * vd.POLL_S)
    st["failed_at"] = AT + 4 * vd.POLL_S
    vd._step(st, AT + 4 * vd.POLL_S + vd.RETRY_S)      # refused again: named, ME's redo goes on
    vd._step(st, AT + 4 * vd.POLL_S + vd.RETRY_S + vd.POLL_S)
    assert st["phase"] == "build"
    vd._write(st)
    s = vd.status()
    assert s["redo_refused"] and "pal" in s["redo_refused"][0] and "CCC" in s["redo_refused"][0]
    assert "not redone" in s["why"]


def test_skipped_redo_and_a_lost_copy_reach_the_screen(world, monkeypatch):
    from tradingagents import cq_search

    st = _to_the_redo(world)
    monkeypatch.setattr(cq_search, "quiet_hours", lambda now=None: True)
    vd._step(st, AT + 4 * vd.POLL_S)
    vd._write(st)
    assert "12:45am" in vd.status()["redo_skipped"] and "12:45am" in vd.status()["why"]

    def broken():
        raise OSError("disk full")

    monkeypatch.setattr(vd, "_keep_prev", broken)
    vd._step(st, AT + 5 * vd.POLL_S)
    vd._write(st)
    assert "disk full" in vd.status()["prev_error"] and "disk full" in vd.status()["why"]


# ------------------------------------------------------------------ an unreadable state
def test_an_unreadable_state_is_named_and_never_overwritten(world):
    vd.state_path().parent.mkdir(parents=True, exist_ok=True)
    vd.state_path().write_text('{"phase": "running", "runs": {"me/analy', encoding="utf-8")
    before = vd.state_path().read_bytes()
    out = vd._tick(AT)
    assert out["phase"] == "unreadable" and "cannot be read" in out["why"]
    assert vd.state_path().read_bytes() == before, "never overwritten"
    assert world.gh.sent == [], "no new chain, no dispatch"
    assert vd.status()["phase"] == "unreadable"
    # named on every screen WITHOUT its file name (final review, Nov 11, 2026); the log line and a
    # command-line start_now still say where it is, for the repair
    s = vd.status()
    for said in (s["why"], s["words"], s["error"]):
        assert "cannot be read" in said and str(vd.state_path()) not in said and "daily_state" not in said
    with pytest.raises(RuntimeError, match="cannot be read") as err:
        vd.start_now(D + 15 * H)
    assert str(vd.state_path()) in str(err.value)
    assert vd.state_path().read_bytes() == before


# ------------------------------------------------------------------ final review of the skill rooms (Nov 11, 2026)
def test_a_late_start_whose_build_ends_after_midnight_still_writes_its_lists(world, monkeypatch):
    """A `start_now` at 8:00pm UTC carries its own deadline, 2:00am UTC the next day. A build ending
    at 12:30am was given up at the lists step, because a built day's deadline was REPLACED by the
    next midnight instead of being the later of the two."""
    from tradingagents import forecast_v4 as f4

    _put_list(Y, {r: [_row("YDAY")] for r in ROOMS})
    monkeypatch.setattr(f4, "switched_on", lambda rule, at_s, db=None: [_row("FRESH")])
    st = {"phase": "lists", "day": _iso(D), "day_s": D, "deadline_s": D + 20 * H + vd.GIVE_UP_AT_S,
          "built_day": _iso(D)}
    vd._step(st, D + DAY + 30 * 60)
    assert st["phase"] == "agree", st.get("why")
    doc = _read_list(D)
    assert doc["fallback_from"] is None and doc["rooms"] == {r: [_row("FRESH")] for r in ROOMS}


def test_an_agree_step_still_failing_on_the_next_utc_day_is_ended_and_named(world, monkeypatch):
    def broken(st, now):
        raise RuntimeError("the store is locked")

    monkeypatch.setitem(vd._PHASES, "agree", broken)
    vd._write({"phase": "agree", "day": _iso(D), "day_s": D, "deadline_s": D + vd.GIVE_UP_AT_S,
               "landed_s": AT})
    vd._tick(AT + H)
    s = vd.read()
    assert s["phase"] == "agree" and "store is locked" in s["error"], "tried again in 30 minutes"
    vd._tick(D + DAY + 10 * 60)                    # 12:10am UTC the next day: still failing - ended
    s = vd.read()
    assert s["phase"] == "done" and "store is locked" in s["agree_error"], s
    w = vd.status()["words"]
    assert "store is locked" in w and "check" in w
    vd._tick(D + DAY + 10 * 60 + vd.POLL_S)        # the next day's refresh is not blocked
    s = vd.read()
    assert s["day"] == _iso(D + DAY) and s["phase"] == "dispatch"


def test_the_daily_lock_is_a_file_lock_a_second_process_is_refused(world):
    from tradingagents import portable

    vd._write({"phase": "idle"})
    before = vd.state_path().read_bytes()
    with open(vd.home() / "daily.lock", "a+b") as fh:          # a start_now from the command line
        portable.lock_exclusive(fh, blocking=False)
        try:
            out = vd._tick(AT)
            with pytest.raises(RuntimeError, match="middle of a step"):
                vd.start_now(D + 15 * H)
        finally:
            portable.unlock(fh)
    assert "a step is already running" in out["why"]
    assert vd.state_path().read_bytes() == before and world.gh.sent == [], "nothing written, nothing sent"
    assert vd._tick(AT)["phase"] == "dispatch", "free again: today's chain begins"
    assert not hasattr(vd, "_LOCK"), "a thread lock cannot see another process"


def test_start_now_refuses_a_day_whose_list_already_exists(world):
    from tradingagents.positions_view import fmt_when

    _put_list(D, {r: [] for r in ROOMS}, fallback_from=_iso(Y))       # today was given up earlier
    with pytest.raises(RuntimeError) as err:
        vd.start_now(D + 15 * H)
    msg = str(err.value)
    assert fmt_when(D) in msg and fmt_when(Y) in msg and _iso(D) not in msg, msg
    assert "never written twice" in msg
    assert world.gh.sent == [] and not vd.state_path().exists(), "no chain begun"


def test_the_words_carry_what_the_day_is_missing_and_a_failing_try(world):
    from tradingagents.positions_view import fmt_when

    st = {"phase": "done", "landed_s": AT, "stale": {"AAA": ["1h"]}, "missing": ["BBB"],
          "redo_refused": ["pal: RuntimeError: refused - 1 coin(s) not redone (CCC)"],
          "redo_skipped": "2 coin(s) not redone (DDD, EEE): no press between 12:45am and 5:00am",
          "redo_error": "OSError: disk full",
          "prev_error": "the collected file could not be kept for tomorrow (OSError: x)"}
    w = vd.words(st)
    assert w.startswith(f"done {fmt_when(AT)}")
    for bit in ("AAA", "keep yesterday's line", "BBB", "absent", "CCC", "DDD", "disk full", "could not be kept"):
        assert bit in w, (bit, w)
    w = vd.words({"phase": "build", "failed_at": AT, "error": "build: the build ended 1: boom"})
    assert w.startswith("rebuilding Backtest v4") and "boom" in w and "tried again" in w
    assert "boom" not in vd.words({"phase": "build", "failed_at": 0, "error": "build: old"}), \
        "an error with no failing try is history, not news"
    # status() hands them to every screen that prints `words`
    vd._write({"phase": "done", "day": _iso(D), "day_s": D, "landed_s": AT, "missing": ["BBB"],
               "stale": {"AAA": ["1h"]}})
    assert "BBB" in vd.status()["words"] and "AAA" in vd.status()["words"]
    vd._write({"phase": "running", "day": _iso(D), "day_s": D, "failed_at": AT, "error": "running: GitHub said 502"})
    assert "GitHub said 502" in vd.status()["words"]


# ------------------------------------------------------------------ exits settled by the minute (Nov 11, 2026)
def _minute_exit(sid, en, candle, minute_ts, pnl, tid):
    """A practice exit the minutes settled: its ts is the minute, v4_candle the candle it belongs to."""
    x = _practice_exit(sid, en, minute_ts, "SL", pnl, tid=tid)
    x["v4_candle"], x["by_minute"] = candle, True
    return x


def test_a_minute_exit_is_compared_by_its_candle_not_by_its_minute(world):
    """Practice stopped at minute 12 of the 10:00 candle (ts 10:12); the backtest's trade says exit
    candle 10:00. They are the SAME trade - the row's ts is no longer the candle's close."""
    pick = _pick([[(Y + 8 * H) * 1000, (Y + 10 * H) * 1000, 1, "SL", -1.5]])
    _build_store(world.tmp, {"AAA|1h": _line("AAA", "1h", [pick])})
    sid = v4_store.row_id("AAA", "1h", pick)
    _put_list(Y, {ROOM: [_row(sid)]})
    with profiles.using(ROOM):
        at.append_ledger(_minute_exit(sid, Y + 8 * H, Y + 10 * H, Y + 10 * H + 12 * 60, -1.49, "MINUTE01"))
    res = vd.agreement(ROOM, Y)
    assert res["same"] == 1 and res["of"] == 1 and res["only_practice"] == [] and res["only_backtest"] == []
    assert res["dollars_apart"] == 0.01


def test_a_minute_exit_in_the_first_minute_of_a_day_belongs_to_that_days_candle(world):
    """A stop in the very first minute of the 00:00 candle: ts == midnight exactly. By ts it would
    land on the day before (the window is open at its start); its candle closes 01:00, so it is D's."""
    pick = _pick([[(Y + 22 * H) * 1000, D * 1000, 1, "SL", -1.5]])
    _build_store(world.tmp, {"AAA|1h": _line("AAA", "1h", [pick])})
    sid = v4_store.row_id("AAA", "1h", pick)
    _put_list(Y, {ROOM: [_row(sid)]})
    with profiles.using(ROOM):
        at.append_ledger(_minute_exit(sid, Y + 22 * H, D, D, -1.5, "FIRSTMIN"))
    assert vd.agreement(ROOM, Y)["of"] == 0, "not yesterday's"
    today = vd.agreement(ROOM, D)
    assert today["same"] == 1 and today["of"] == 1


def test_an_exit_row_from_before_the_minutes_is_still_compared_by_its_close(world):
    pick = _pick([[(Y + 8 * H) * 1000, (Y + 10 * H) * 1000, 1, "TP", 1.0]])
    _build_store(world.tmp, {"AAA|1h": _line("AAA", "1h", [pick])})
    sid = v4_store.row_id("AAA", "1h", pick)
    _put_list(Y, {ROOM: [_row(sid)]})
    with profiles.using(ROOM):
        at.append_ledger(_practice_exit(sid, Y + 8 * H, Y + 11 * H, "TP", 1.0, tid="OLDROW01"))
    assert vd.agreement(ROOM, Y)["same"] == 1


def test_the_picker_runs_in_the_chain_and_a_switched_off_room_gets_an_empty_list(world, monkeypatch, tmp_path):
    """Nov 12, 2026: the daily picker's pass comes BEFORE the day's list, and the list is judged by the
    rule the picker gave each room - a slot it switched off opens nothing."""
    import json

    from tradingagents import forecast_v4 as f4
    from tradingagents import v4_picker as vp

    seen = []

    def switched_on(rule, at_s, db=None):
        seen.append(f4.rule_id(**rule))
        return [_row("ON" + f4.rule_id(**rule)[:4])]

    monkeypatch.setattr(f4, "switched_on", switched_on)
    monkeypatch.setattr(profiles, "PICKER_PATH", tmp_path / "picker.json")
    order = []
    monkeypatch.setattr(vp, "pick", lambda now: order.append("pick") or {"log": [{"text": "RSS7CUKH switched off"}]})
    (tmp_path / "picker.json").write_text(json.dumps({"slots": {
        "RSS7CUKH": {"rule": profiles.get("RSS7CUKH")["v4_rule"], "rule_id": "RSS7CUKH", "off": True, "since_s": 1},
        "7T3VJU82": {"rule": {**profiles.get("7T3VJU82")["v4_rule"], "money": "made"}, "rule_id": "NEWRULE1", "off": False}}}),
        encoding="utf-8")
    st = {"phase": "lists", "day": _iso(D), "day_s": D, "deadline_s": D + vd.GIVE_UP_AT_S, "runs": {}}
    vd._step(st, AT)
    doc = _read_list(D)
    assert order == ["pick"] and "picker: RSS7CUKH switched off" in st["why"]
    assert doc["rooms"]["RSS7CUKH"] == [], "a switched-off slot opens nothing"
    assert doc["rooms"]["D7EN8BNV"] and doc["rooms"]["7T3VJU82"]
    assert f4.rule_id(**{**profiles.get("7T3VJU82")["v4_rule"], "money": "made"}) in seen   # judged by the picked rule
    assert "RSS7CUKH" not in seen
