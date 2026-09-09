"""The coin you pick is the coin GitHub measures.

The operator, Sep 10, 2026: *"so when i backtest btc it runs backtets on github
then store the result direclty on my machine right?"* — and it did not. The
Backtest screen sent only how MANY coins were picked (`coins: coins.length`),
never their names, and the shard reads that number as "the most coins one
machine may claim". The twenty machines then took the first free coin at each
of their own starting points in a sorted list of 1,065 contracts:

    0G, ALPINE, AVAAI, BLAST, CC, CSOPSKHYNIX2L, EDGE, FLUX, HANA, IONQSTOCK,
    LASERTECSTOCK, MET, NGAS, PANASONICSTOCK, QCOMSTOCK, SANTOS, SONYSTOCK,
    TAO, UKOIL, XAN

BTC_USDT sits at position 190 and is in none of them. Four dispatch paths had
the same hole — the BACKTEST button, UPDATE BACKTEST, the hand-off (which knows
exactly which coins this PC never reached) and the orchestrator.
"""
import importlib.util
import inspect
import pathlib

import pytest

from tradingagents import api, cloud_sweep as cs, db_jobs as dj, sweep_orchestrator as so

REPO = pathlib.Path(__file__).resolve().parents[1]
SHARD = REPO / ".github" / "scripts" / "sweep_shard.py"
YML = REPO / ".github" / "workflows" / "sweep.yml"
PANEL = REPO / "webapp" / "src" / "components" / "backtest" / "JobsPanel.tsx"
API_TS = REPO / "webapp" / "src" / "lib" / "api.ts"


@pytest.fixture
def sent(monkeypatch):
    """`dispatch` with its `gh` calls captured and no run ever appearing."""
    calls: list = []
    monkeypatch.setattr(cs, "available", lambda: (True, "me/repo"))
    monkeypatch.setattr(cs, "_gh", lambda *a, **k: calls.append(a) or "")
    monkeypatch.setattr(cs.time, "sleep", lambda s: None)
    seen: list = []
    monkeypatch.setattr(cs, "_runs", lambda slug, limit=1: seen.append(1) or [
        {"databaseId": 4 if len(seen) == 1 else 5, "url": "u"}])
    return calls


def _flat(calls):
    return [x for c in calls for x in c]


# ------------------------------------------------------------- the dispatch
def test_the_picked_coin_travels_by_name(sent):
    got = cs.dispatch(shards=20, coins=1, coin_list=["BTC"], timeframes="1h")
    flat = _flat(sent)
    assert "coin_list=BTC_USDT" in flat, flat
    assert got["coins_named"] == ["BTC_USDT"]
    # the count is NOT the ask any more, and twenty machines are not started
    # for one coin: nineteen of them would find an empty board
    assert "coins=0" in flat, flat
    assert "shards=1" in flat, flat


def test_no_pick_still_means_the_whole_market(sent):
    got = cs.dispatch(shards=20, coins=0, timeframes="1h")
    flat = _flat(sent)
    assert "coin_list=" in flat, "the input is always sent, empty = everything"
    assert "shards=20" in flat
    assert got["coins_named"] == [] and got["coin_list_why"] == ""


def test_the_names_are_the_venues_own_once(sent):
    cs.dispatch(shards=20, coin_list=["btc", "ETH_USDT", "BTC_USDT", " sol "],
                timeframes="1h")
    flat = _flat(sent)
    assert "coin_list=BTC_USDT,ETH_USDT,SOL_USDT" in flat, flat
    assert "shards=3" in flat, "three coins, three machines"


def test_too_many_names_falls_back_to_the_board_and_says_so(sent):
    many = [f"COIN{i:04d}" for i in range(900)]
    got = cs.dispatch(shards=20, coin_list=many, timeframes="1h")
    flat = _flat(sent)
    assert "coin_list=" in flat, "no list was sent"
    assert not any(x.startswith("coin_list=COIN") for x in flat)
    assert got["coins_named"] == []
    assert "900 coins" in got["coin_list_why"] and "whole board" in got["coin_list_why"]
    assert "shards=20" in flat, "a whole-board run keeps the whole fleet"


def test_symbols_of_is_the_one_conversion():
    assert cs.symbols_of(["BTC"]) == ["BTC_USDT"]
    assert cs.symbols_of(["BTC_USDT"]) == ["BTC_USDT"]
    assert cs.symbols_of([]) == [] and cs.symbols_of(None) == []
    assert cs.symbols_of(["", "  ", "eth"]) == ["ETH_USDT"]


# ---------------------------------------------------------------- the shard
@pytest.fixture
def shard(tmp_path, monkeypatch):
    def _make(coin_list: str):
        monkeypatch.chdir(tmp_path)
        for k, v in {"SHARD": "0", "SHARDS": "1", "TFS": "1h", "DAYS": "60",
                     "MODE": "full", "COIN_LIST": coin_list}.items():
            monkeypatch.setenv(k, v)
        spec = importlib.util.spec_from_file_location("sweep_shard_pick_test", SHARD)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        monkeypatch.setattr(mod, "report", lambda *a, **k: None)
        board = [{"symbol": s, "state": 0} for s in
                 ("0G_USDT", "ALPINE_USDT", "BTC_USDT", "ETH_USDT", "XAN_USDT")]
        board.append({"symbol": "DEAD_USDT", "state": 3})     # not trading
        monkeypatch.setattr(mod.fx, "_get_public", lambda url, **k: {"data": board})
        return mod
    return _make


def test_the_shard_measures_exactly_the_named_coins(shard):
    mod = shard("BTC_USDT")
    logs: list = []
    mod.log = logs.append
    assert mod.eligible() == ["BTC_USDT"]
    assert any("1 coin(s) named by the dispatch" in m for m in logs), logs
    assert any("not the whole market" in m for m in logs)


def test_an_empty_list_is_still_the_whole_market(shard):
    mod = shard("")
    assert mod.eligible() == ["0G_USDT", "ALPINE_USDT", "BTC_USDT", "ETH_USDT",
                              "XAN_USDT"], "the delisted one is out, the rest in"


def test_a_named_coin_the_venue_will_not_trade_is_NAMED(shard):
    """Rule 20: whatever was excluded is counted out loud — and named, so the
    operator does not have to diff two lists to find their coin missing."""
    mod = shard("BTC,DEAD,GHOST")
    logs: list = []
    mod.log = logs.append
    assert mod.eligible() == ["BTC_USDT"]
    said = " ".join(logs)
    assert "2 coin(s) the venue is not trading" in said, said
    assert "DEAD" in said and "GHOST" in said, "named, not just counted"


def test_the_bare_name_is_given_its_contract(shard):
    assert shard("btc,eth").eligible() == ["BTC_USDT", "ETH_USDT"]


def test_the_named_board_is_what_the_machines_walk(shard):
    """`coin_stream` without a claim board (no token: local runs and this
    test) yields this shard's slice — of the NAMED board, so a one-coin ask
    cannot wander onto a coin nobody picked."""
    mod = shard("BTC")
    got = list(mod.coin_stream(mod.eligible(), t0=mod.time.time()))
    assert got == ["BTC_USDT"]


# --------------------------------------------------------- every way in
def test_every_dispatch_path_sends_the_NAMES(sent):
    """Four paths dropped the pick. A source check, because three of them are
    inside long jobs that cannot be driven from a unit test — and because the
    argument being MISSING is exactly the bug."""
    for fn, must in ((api.cloud_dispatch, "coin_list=[str(c) for c in (body.get"),
                     (api._finish_handoff, "coin_list=left"),
                     (so.run, "coin_list=names"),
                     (dj._run_btupdate, 'coin_list=list(spec.get("coins")')):
        src = inspect.getsource(fn)
        assert must in src, f"{fn.__name__} does not send the picked coins"

    # …and the one that means EVERYTHING keeps meaning everything — silence
    # would be indistinguishable from the bug, so it says why in place
    resolve = inspect.getsource(api.backtest_pending_resolve)
    assert "NO coin_list ON PURPOSE" in resolve, \
        "the whole-board dispatch must say it is deliberate"
    call = resolve[resolve.index("cs.dispatch("):]
    assert "coin_list=" not in call[:call.index(")")], \
        "resolving the pending is the whole board on purpose"


def test_a_run_that_named_its_coins_covers_no_timeframe(monkeypatch):
    """"GitHub is busy — that run covers 1h, which is every pending frame" is
    true of the FRAME and false of the WORK when the run was asked for two
    coins: every other pending 1h pair is exactly as pending as it was."""
    from tradingagents import cloud_autopilot as ca

    monkeypatch.setattr(cs, "working_run", lambda slug=None: {"id": 7})
    monkeypatch.setattr(ca, "_read", lambda: {})
    monkeypatch.setattr(cs, "remembered",
                        lambda: {"id": 7, "timeframes": ["1h"], "coins_named": []})
    assert api._busy_run_covers({"1h": 40}) == (["1h"], {})
    monkeypatch.setattr(cs, "remembered", lambda: {
        "id": 7, "timeframes": ["1h"], "coins_named": ["BTC_USDT"]})
    assert api._busy_run_covers({"1h": 40}) == (None, {}), \
        "a named run must not be reported as covering the frame"


def test_the_handoff_says_when_it_could_not_name_them(monkeypatch, tmp_path, capsys):
    """A list too long for one command line measures the WHOLE board — more
    work than was asked for, and it may not be discovered later."""
    from tradingagents import db_jobs as _dj

    monkeypatch.setattr(_dj, "handoff_requested", lambda kind: True)
    monkeypatch.setattr(_dj, "status", lambda kind: {"running": False})
    monkeypatch.setattr(_dj, "_read", lambda path: {"coins": ["AAA", "BBB"],
                                                    "tfs": ["1h"]})
    monkeypatch.setattr(_dj, "clear_handoff", lambda kind: None)
    monkeypatch.setattr(cs, "available", lambda: (True, "me/repo"))
    monkeypatch.setattr(cs, "unmeasured", lambda coins, tfs: ["AAA", "BBB"])
    monkeypatch.setattr(cs, "dispatch", lambda **k: {
        "id": 9, "coins_named": [], "coin_list_why": "900 coins is too many to name"})
    monkeypatch.setattr(cs, "remember", lambda run: None)
    api._finish_handoff()
    said = capsys.readouterr().out
    assert "too many to name" in said, said


def test_the_workflow_carries_the_list():
    y = YML.read_text(encoding="utf-8")
    assert "coin_list:" in y
    assert "COIN_LIST: ${{ github.event.inputs.coin_list }}" in y
    # workflow_dispatch allows ten inputs and this is the tenth: a silent
    # eleventh would make GitHub reject every dispatch
    inputs = y.split("workflow_dispatch:")[1].split("permissions:")[0]
    names = [ln.strip().rstrip(":") for ln in inputs.splitlines()
             if ln.startswith("      ") and ln.strip().endswith(":")
             and not ln.strip().startswith(("description", "default"))]
    assert len(names) <= 10, f"GitHub allows 10 inputs, this has {len(names)}: {names}"


def test_the_screen_sends_the_names_and_reports_what_was_sent():
    p = PANEL.read_text(encoding="utf-8")
    assert "coin_list: coins" in p, "the picker's names, not its length"
    assert "coins: coins.length" not in p, "the count-only dispatch is gone"
    # and it tells the operator what GitHub was actually asked for, from the
    # ANSWER — a screen sure of what it sent is how this went unnoticed
    i = p.index("const run = await api.cloudDispatch")
    block = p[i:i + 900]
    assert "run.coins_named" in block and "run.coin_list_why" in block
    t = API_TS.read_text(encoding="utf-8")
    assert "coin_list?: string[]" in t and "coins_named?: string[]" in t
