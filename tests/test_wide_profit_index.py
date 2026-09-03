"""`ORDER BY profit` with a filter beside it needs profit's own wide index.

Measured on the operator's store (35,863,520 rows, mechanical disk, a sweep
running) the day the flat/martingale filter was added, 2026-08-27:

    sizing=flat                              HTTP 503 at the 20s budget
    sizing=flat AND tf=1h                    HTTP 503
    sizing=flat AND 100+ trades              HTTP 503
    sizing=flat AND profit > 0               HTTP 503
    sizing=flat AND coin=KAVA                200 in 2.0 s

The filter itself is correct in all five — the store simply cannot answer four
of them in time. `rows_profit` is (profit DESC, id), so every candidate row has
to be read off the disk to see its `sizing`, and EVERY one of the biggest
profits in this store is a martingale row (the ladder multiplies them), so a
`flat` page has to walk millions of rows before it finds 500.

`rows_pr2` carries the filter columns next to profit, which makes that walk
index-only — the same trick `rows_wr2` plays for the win % order. Built on
demand, never by `ensure()`: it is tens of minutes on a store this size and
everything works, slower, without it.
"""
import pytest

from tradingagents import rows_index as ri


def test_the_index_carries_every_filter_that_cuts_inside_a_pair():
    ddl = ri.INDEX_DDL["rows_pr2"]
    assert ddl == ri.WIDE_PROFIT
    cols = ddl[ddl.index("(") + 1:ddl.rindex(")")]
    # profit leads (it is the ORDER BY, and `profitable` is profit > 0), then
    # every filter the panel can add to it
    assert cols.startswith("profit DESC"), cols
    for col in ("sizing", "tp", "winrate", "trades"):
        assert col in cols, f"rows_pr2 cannot test {col} index-only: {cols}"
    assert cols.rstrip().endswith("id"), cols


def test_it_is_built_on_demand_not_by_ensure():
    """45 min on the operator's store for the win-rate one; a page open must
    not wait on that, and `ensure()` runs on every API start."""
    assert all("rows_pr2" not in d for d in ri.KEEP_INDEXES)
    assert "rows_pr2" not in " ".join(ri.FILTER_INDEXES.values())


def test_the_index_is_named_only_when_it_exists(monkeypatch):
    """Naming an index SQLite does not have is a hard error, so a store without
    it must fall through to the planner's own choice."""
    monkeypatch.setattr(ri, "has_index", lambda name: name == "rows_pr2")
    assert ri._indexed_by(None, False, True) == " INDEXED BY rows_pr2"
    monkeypatch.setattr(ri, "has_index", lambda name: False)
    assert ri._indexed_by(None, False, True) == ""


def test_a_coin_still_outranks_it(monkeypatch):
    """~10k rows for a pair beats any scan of the profit index."""
    monkeypatch.setattr(ri, "has_index", lambda name: True)
    assert ri._indexed_by("KAVA", False, True) == " INDEXED BY rows_coin"


def test_only_a_filter_that_lives_in_it_asks_for_it():
    assert ri._wide_profit_helps(sizing="flat")
    assert ri._wide_profit_helps(max_tp=4)
    assert ri._wide_profit_helps(min_winrate=50)
    assert ri._wide_profit_helps(min_trades=100)
    assert ri._wide_profit_helps(profitable=True)
    # an unfiltered page is what rows_profit is already perfect for
    assert not ri._wide_profit_helps()
    # a signal is a string and is not in the index: nothing to gain
    assert not ri._wide_profit_helps(sizing=None, max_tp=0)


def test_a_missing_index_starts_building_behind_the_answer(monkeypatch,
                                                          tmp_path):
    """The request still runs — the 20 s budget is what answers 503 — but the
    build has to start, or the next attempt is just as slow."""
    started = []
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    monkeypatch.setattr(ri, "has_index", lambda name: name != "rows_pr2")
    monkeypatch.setattr(ri, "_rows_estimate", lambda: ri.UNINDEXED_LIMIT + 1)
    monkeypatch.setattr(ri, "_build_index", lambda name: started.append(name))
    ri.query(sizing="flat")
    assert started == ["rows_pr2"], started

    # nothing to gain, nothing built
    started.clear()
    ri.query()
    assert started == [], started


def test_a_small_store_does_not_build_anything(monkeypatch, tmp_path):
    """Sorting a few thousand rows without it is instant; a build on a laptop
    store would be pure cost."""
    started = []
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    monkeypatch.setattr(ri, "has_index", lambda name: name != "rows_pr2")
    monkeypatch.setattr(ri, "_rows_estimate", lambda: 4_000)
    monkeypatch.setattr(ri, "_build_index", lambda name: started.append(name))
    ri.query(sizing="flat")
    assert started == [], started


def test_the_timeout_names_the_sizing_case_and_what_answers_now(monkeypatch):
    monkeypatch.setattr(ri, "has_index", lambda name: False)
    why = ri._slow_why(None, None, None, 0, 0, "profit", sizing="flat")
    assert "flat" in why and "wide profit index" in why
    assert "rank by win %" in why and "coin" in why
    # with the index in place that sentence would be a lie, so it goes
    monkeypatch.setattr(ri, "has_index", lambda name: True)
    later = ri._slow_why(None, None, None, 0, 0, "profit", sizing="flat")
    assert "wide profit index" not in later


@pytest.mark.parametrize("kw", [{"sizing": "flat"}, {"max_tp": 4},
                                {"min_winrate": 50}])
def test_the_answer_is_the_same_with_or_without_it(kw, tmp_path, monkeypatch):
    """An index changes the PLAN, never the rows. Same store, same filter,
    once with rows_pr2 named and once without."""
    import json
    import time

    from tradingagents import market_sweep as msw

    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")

    def row(sig, profit, sizing, tp, winrate):
        wins = round(120 * winrate / 100)
        return {"coin": "AAA", "tf": "1h", "signal": sig, "th": 0.1, "sl": 0.3,
                "tp": tp, "rr": 3.0, "sizing": sizing, "lev": 20, "base": 5.0,
                "notional": 100.0, "trades": 120, "wins": wins,
                "losses": 120 - wins, "winrate": winrate, "profit": profit,
                "funding": -0.2, "h1": 1.0, "h2": 1.0, "green": 8,
                "months": 12, "worst": -4.1, "dd": 22.0, "liqs": 0,
                "stop_reachable": True, "days": 360, "bars": 34000,
                "monthly": {}, "cost_of_tp": 12.5, "rt": 0.04, "gate": "ok"}

    (rows_dir / "AAA-1h.json").write_text(json.dumps([
        row("a", 900.0, "martingale", 2.0, 30.0),
        row("b", 40.0, "flat", 5.0, 70.0),
        row("c", 30.0, "flat", 2.0, 55.0),
        row("d", -5.0, "martingale", 8.0, 90.0),
    ]))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)

    without = ri.query(**kw)
    with ri._open() as con:
        con.execute(ri.WIDE_PROFIT)
    ri.forget_indexes()
    assert ri.has_index("rows_pr2") is True
    with_it = ri.query(**kw)
    assert [r["id"] for r in with_it["rows"]] == [r["id"] for r in without["rows"]]
    assert with_it["total"] == without["total"]

def _tiny_store(tmp_path, monkeypatch, *, wide=True):
    """A real store with the real indexes, so naming one is legal and the
    decision can be watched. `_rows_estimate` is faked big: this is about which
    index the code CHOOSES, not about how fast four rows are."""
    import json
    import time

    from tradingagents import market_sweep as msw

    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")

    def row(sig, profit, sizing, winrate):
        wins = round(120 * winrate / 100)
        return {"coin": "AAA", "tf": "1h", "signal": sig, "th": 0.1, "sl": 0.3,
                "tp": 2.0, "rr": 3.0, "sizing": sizing, "lev": 20, "base": 5.0,
                "notional": 100.0, "trades": 120, "wins": wins,
                "losses": 120 - wins, "winrate": winrate, "profit": profit,
                "funding": -0.2, "h1": 1.0, "h2": 1.0, "green": 8,
                "months": 12, "worst": -4.1, "dd": 22.0, "liqs": 0,
                "stop_reachable": True, "days": 360, "bars": 34000,
                "monthly": {}, "cost_of_tp": 12.5, "rt": 0.04, "gate": "ok"}

    (rows_dir / "AAA-1h.json").write_text(json.dumps([
        row("mom6", 900.0, "martingale", 11.0),
        row("rsi14", 90.0, "flat", 88.0),
        row("willr14", 60.0, "flat", 81.0),
        row("fade15", -5.0, "flat", 95.0),
    ]))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    with ri._open() as con:
        con.execute(ri.WIDE_WINRATE)
        if wide:
            con.execute(ri.WIDE_PROFIT)
    ri.forget_indexes()
    monkeypatch.setattr(ri, "_rows_estimate", lambda: ri.UNINDEXED_LIMIT + 1)


def _watch_index(monkeypatch) -> list:
    """Every `INDEXED BY` the query names, in order."""
    named: list = []
    real = ri._indexed_by

    def spy(*a, **k):
        got = real(*a, **k)
        named.append(got)
        return got

    monkeypatch.setattr(ri, "_indexed_by", spy)
    return named


def test_ranked_by_profit_it_beats_the_win_rate_seek(tmp_path, monkeypatch):
    """THE bug of 2026-08-27, and the one no test covered.

    Operator: *"nothing is showing usgn this filter why"* — `flat only AND win %
    >= 80 AND profit > 0`, ranked by PROFIT $, refused at the 20 s budget. A win
    % floor made `query` seek rows_wr2 whatever the order was. Ranked by profit
    that is doubly wrong: rows_wr2 is in WIN-RATE order, so every match has to be
    re-sorted (~640,000 of them at >= 80 on the operator's store), and it carries
    no `sizing`, so every candidate row was read off a 13.6 GB file to test it.
    rows_pr2 is already in profit order and holds winrate AND sizing: no sort, no
    row reads. 503 after 20 s became 200 in 1.64 s.

    So the index must be chosen from the filter AND THE ORDER — which is exactly
    what the old code did not do.
    """
    _tiny_store(tmp_path, monkeypatch)
    named = _watch_index(monkeypatch)
    got = ri.query(sizing="flat", min_winrate=80, profitable=True,
                   sort="profit")
    assert any("rows_pr2" in n for n in named), named
    assert not any("rows_wr2" in n for n in named), named
    # and the answer is right, not merely fast
    assert [r["signal"] for r in got["rows"]] == ["rsi14", "willr14"]


def test_without_the_wide_profit_index_the_seek_still_helps(tmp_path,
                                                           monkeypatch):
    """The fix must not leave an older store with nothing: no rows_pr2, and a
    win % floor still drives its own index."""
    _tiny_store(tmp_path, monkeypatch, wide=False)
    named = _watch_index(monkeypatch)
    ri.query(min_winrate=80, sort="profit")
    assert any("rows_wr2" in n or "rows_winrate" in n for n in named), named


def test_ranked_by_win_percent_the_seek_is_still_right(tmp_path, monkeypatch):
    """The fix must not take the win-rate order's own index away from it: there
    the seek IS the answer (0.77 s on the operator's store)."""
    _tiny_store(tmp_path, monkeypatch)
    named = _watch_index(monkeypatch)
    ri.query(min_winrate=80, sort="winrate")
    assert any("rows_wr2" in n or "rows_winrate" in n for n in named), named
    assert not any("rows_pr2" in n for n in named), named


def test_the_reason_never_claims_a_finished_build_is_running(monkeypatch):
    """The second half of the same incident: "The wide win-rate index that makes
    this instant is still being built" was a LITERAL in the message, so it kept
    saying that hours after the index landed (built 05:5x, printed 12:33). Read
    from the database, not from the string."""
    monkeypatch.setattr(ri, "has_index", lambda name: True)
    why = ri._slow_why(None, None, None, 80, 0, "profit")
    assert "being built" not in why, why
    assert "rank by win %" in why, "and it still says what DOES work"
    monkeypatch.setattr(ri, "has_index", lambda name: False)
    assert "being built" in ri._slow_why(None, None, None, 80, 0, "profit")


def test_a_build_outlives_the_process_that_asked_for_it(monkeypatch, tmp_path):
    """Operator, 2026-08-27: Preset Confluence said "It is being built in the
    background; try again shortly" for an hour and nothing ever landed.

    The build ran in a daemon THREAD inside the API, and the API was restarted
    several times that afternoon shipping the day's fixes — every restart killed
    it mid-scan, silently, and the next request started over. `start.py` kills
    the API with `taskkill /T`, which would reach a child too, so the child is
    spawned DETACHED (its own process group / session).
    """
    seen = {}

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, **kw):
        seen["cmd"] = cmd
        seen["kw"] = kw
        return FakeProc()

    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    monkeypatch.setattr(ri, "has_index", lambda name: False)
    monkeypatch.setattr(ri.subprocess, "Popen", fake_popen)
    ri._BUILDING.discard("rows_pr2")
    assert ri._build_index("rows_pr2") is True
    assert seen["cmd"][1:] == ["-m", "tradingagents.rows_index",
                               "--build", "rows_pr2"], seen["cmd"]
    detached = (seen["kw"].get("creationflags", 0) & 0x00000008) or \
        seen["kw"].get("start_new_session")
    assert detached, seen["kw"]
    ri._BUILDING.discard("rows_pr2")

    # an index nobody defined is refused rather than spawned
    assert ri._build_index("rows_not_a_thing") is False


def test_the_child_builds_one_index_and_does_not_become_an_indexer(monkeypatch):
    """`--build` must not start the keep-up loop, or every refused query would
    leave another indexer running beside the real one."""
    built, kept = [], []
    monkeypatch.setattr(ri, "build_index_now", lambda n: built.append(n) or True)
    monkeypatch.setattr(ri, "start_keeping_up", lambda *a, **k: kept.append(1))
    monkeypatch.setattr(ri, "ensure", lambda: None)
    assert ri.main(["--build", "rows_id"]) == 0
    assert built == ["rows_id"] and kept == []
    assert ri.main(["--build"]) == 2, "a missing name is a usage error"


def test_a_fill_starts_the_indexes_it_did_not_build(monkeypatch, tmp_path):
    """Operator, 2026-08-27: *"i did a backtest to another session why was this
    not built?"*

    A backtest inserts rows; it does not create an index that does not exist.
    `ensure()` builds KEEP_INDEXES only (all of them there cost 13 minutes of
    every API start), so rows_wr2 / rows_pr2 / rows_id / rows_cf_* exist only
    because somebody asked — and a SCHEMA_VERSION bump wipes them with the
    tables. Preset Confluence was an empty table for an hour because of it.
    """
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    monkeypatch.setattr(ri, "has_index",
                        lambda n: n not in ("rows_pr2", "rows_cf_dd"))
    started = []
    monkeypatch.setattr(ri, "_build_index", lambda n: started.append(n) or True)

    assert sorted(ri.missing_indexes()) == ["rows_cf_dd", "rows_pr2"]
    assert sorted(ri.build_missing_indexes()) == ["rows_cf_dd", "rows_pr2"]
    assert sorted(started) == ["rows_cf_dd", "rows_pr2"]

    # and a build that cannot start must never fail the fill that called it
    monkeypatch.setattr(ri, "build_missing_indexes",
                        lambda: (_ for _ in ()).throw(RuntimeError("no fork")))
    assert ri._after_fill_indexes() == []


def test_ANY_pass_that_indexed_a_pair_calls_it(monkeypatch, tmp_path):
    """Operator: *"when i click backtest or update backtest will it work too?"*

    It would not have. `bulk` is `len(todo) > BIG_FILL` — 500 pairs — so hanging
    the check off a bulk fill meant a backtest of one coin, an UPDATE BACKTEST,
    the reindex button and the trickle all skipped it. Every pass that indexed a
    pair means the store grew.
    """
    import json
    import time as _t

    from tradingagents import market_sweep as msw

    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    (rows_dir / "AAA-1h.json").write_text(json.dumps([{
        "coin": "AAA", "tf": "1h", "signal": "mom6", "th": 0.1, "sl": 0.3,
        "tp": 2.0, "rr": 3.0, "sizing": "flat", "lev": 20, "base": 5.0,
        "notional": 100.0, "trades": 120, "wins": 72, "losses": 48,
        "winrate": 60.0, "profit": 10.0, "funding": -0.2, "h1": 1.0, "h2": 1.0,
        "green": 8, "months": 12, "worst": -4.1, "dd": 22.0, "liqs": 0,
        "stop_reachable": True, "days": 360, "bars": 34000, "monthly": {},
        "cost_of_tp": 12.5, "rt": 0.04, "gate": "ok"}]))

    calls = []
    monkeypatch.setattr(ri, "_after_fill_indexes", lambda: calls.append(1) or [])
    got = ri.sync(now=_t.time() + ri.SETTLE_S + 1)
    assert got["pairs"] == 1, got
    assert calls == [1], "ONE pair is enough — this is the backtest button"

    # nothing indexed, nothing to check
    calls.clear()
    ri.sync(now=_t.time() + ri.SETTLE_S + 1)
    assert calls == [], "a pass that indexed nothing must not spawn anything"

    # and it is not hidden behind `bulk`
    src = open("tradingagents/rows_index.py", encoding="utf-8").read()
    tail = src[src.index("if done:"):src.index("return {\"pairs\": done")]
    assert "_after_fill_indexes()" in tail, tail


def test_two_processes_cannot_build_the_same_index_twice(monkeypatch, tmp_path):
    """2026-08-27: the check after every indexed pair spawned one child per
    pass, `_BUILDING` is per PROCESS, and thirteen `--build` processes piled up
    blocked on the write lock within minutes. A lock FILE beside the database is
    the only thing the API, the indexer and a detached child all share."""
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    monkeypatch.setattr(ri, "has_index", lambda n: False)
    spawned = []

    class FakeProc:
        pid = 99

    monkeypatch.setattr(ri.subprocess, "Popen",
                        lambda cmd, **kw: spawned.append(cmd) or FakeProc())
    ri._BUILDING.discard("rows_id")
    assert ri._build_index("rows_id") is True
    # build_running returns the NAME it found, not a bool: the message can then
    # say which index is holding the writer
    assert ri.build_running("rows_id") == "rows_id", "the lock must be down"

    # another PROCESS asking (its own _BUILDING is empty) must not spawn a twin
    ri._BUILDING.discard("rows_id")
    assert ri._build_index("rows_id") is False
    assert len(spawned) == 1, spawned

    # and a DIFFERENT index waits its turn: SQLite takes one writer, so a
    # second CREATE INDEX can only queue — eighteen of them did (2026-08-27)
    ri._BUILDING.discard("rows_pr2")
    assert ri._build_index("rows_pr2") is False
    assert len(spawned) == 1, spawned
    assert ri.build_running() == "rows_id", ri.build_running()

    # the child clears it, whatever happened
    ri.build_index_now("rows_not_a_thing")          # unknown: returns early
    ri._build_lock("rows_id").unlink()
    assert ri.build_running() == "", "no lock, no build"
    assert ri.build_running("rows_id") == ""

    # a lock older than any real build is stale, not forever
    lock = ri._build_lock("rows_id")
    lock.write_text("1", encoding="utf-8")
    import os as _os
    old = ri.time.time() - ri.BUILD_LOCK_TTL_S - 60
    _os.utime(lock, (old, old))
    assert ri.build_running("rows_id") == ""
    assert not lock.exists(), "a stale lock is removed, not just ignored"


def test_a_build_child_never_spawns_a_build(monkeypatch, tmp_path):
    """The recursion guard: TA_INDEX_BUILD is set in the child's environment."""
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    monkeypatch.setattr(ri, "has_index", lambda n: False)
    monkeypatch.setenv("TA_INDEX_BUILD", "rows_pr2")
    ri._BUILDING.discard("rows_id")
    assert ri._build_index("rows_id") is False

    monkeypatch.delenv("TA_INDEX_BUILD")
    seen = {}

    class FakeProc:
        pid = 7

    monkeypatch.setattr(ri.subprocess, "Popen",
                        lambda cmd, **kw: seen.update(kw) or FakeProc())
    ri._BUILDING.discard("rows_id")
    assert ri._build_index("rows_id") is True
    assert seen["env"]["TA_INDEX_BUILD"] == "rows_id", seen.get("env", {})
    ri._build_lock("rows_id").unlink(missing_ok=True)
