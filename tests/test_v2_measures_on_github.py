"""Backtest v2 measures on the fleet, and its rows land in the v2 store.

Operator, `Sep 21, 2026`, after being told v2 ran on this PC:

    *"who said to run on pc? i've alrewady documented that it should be using
    github why are you not using github?"*

then, as the goal:

    *"i still 30 days anmd i want backtest to run on github, what ever existing
    on v1 i want on v2 the only difference is v2 will be using 1min candles
    that's the only difference i want"*

Nobody had overruled them. The `Sep 17, 2026` design spec filed cloud
measuring under "Out of this cut" — the fleet had no 1-minute candles — and
they were never asked. `tests/test_v2_jobs_have_no_cloud.py` then pinned that
choice shut. This file replaces that rule with theirs.

THE ONE IDEA: `res` is a RESOLUTION, not a timeframe. A v2 run measures the
same 15m/30m/1h/4h/1d as v1; it rebuilds each of them from one-minute candles
and settles every exit minute by minute. "1m" must never become a frame in
the grid.
"""
from __future__ import annotations

import inspect
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SHARD = REPO / ".github" / "scripts" / "sweep_shard.py"
FLOW = REPO / ".github" / "workflows" / "sweep.yml"


def _shard() -> str:
    return SHARD.read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    """Source with COMMENT lines removed, character for character otherwise.

    Every "this call is not made" assertion below runs against this, because
    the comments EXPLAIN the calls they forbid — the trap this repo has now
    paid for five times (CLAUDE.md, the `.toLocale` grep).

    Deliberately line-based rather than `ast.unparse`: unparse normalises
    double quotes to single and reflows every call, so `f"res={res}"` came
    back as `f'res={res}'` and two assertions failed against code that was
    perfectly correct. A guard that rewrites what it inspects is testing its
    own formatter.
    """
    out = []
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


# ----------------------------------------------------- the workflow's slots
def test_the_workflow_still_has_at_most_TEN_inputs():
    """`workflow_dispatch` accepts exactly ten and the file was AT ten, so a
    new one has to take a slot rather than be added. Eleven is not a lint
    failure — GitHub refuses the whole workflow, and the fleet stops."""
    import re

    body = FLOW.read_text(encoding="utf-8")
    block = body[body.index("inputs:"):body.index("permissions:")]
    names = re.findall(r"^      ([a-z_]+):$", block, re.M)
    assert len(names) <= 10, f"{len(names)} inputs: {names}"
    assert "res" in names, names


def test_min_days_gave_up_its_slot_and_nothing_depended_on_it():
    """It had been "0" from every caller since Sep 10, 2026 and the shard
    short-circuits its whole age screen on `MIN_DAYS <= 0`, so the screen had
    no job left to do. Depth is each row's own `days` column (CLAUDE.md)."""
    body = FLOW.read_text(encoding="utf-8")
    assert "MIN_DAYS: ${{ github.event.inputs.min_days }}" not in body
    assert "RES: ${{ github.event.inputs.res }}" in body
    # and the shard still tolerates the variable being absent entirely
    assert 'MIN_DAYS = int(os.environ.get("MIN_DAYS", "0"))' in _shard()
    assert "if MIN_DAYS <= 0:" in _shard(), \
        "the age screen must still short-circuit when nothing sends it"


# ------------------------------------------- a resolution, never a timeframe
def test_1m_never_becomes_a_measured_timeframe():
    """CLAUDE.md: 1m is a DOWNLOAD frame only — not in `capacity.ALL_TFS`, not
    in the barrier grid, not in any five-frame tuple. A v2 run asks for the
    SAME frames as v1 and differs only in how an exit is settled."""
    from tradingagents import backtest_report as br, capacity

    assert "1m" in br.TFS, "still a download frame"
    assert "1m" not in br.BARRIERS, "and never a grid frame"
    assert "1m" not in capacity.ALL_TFS
    s = _shard()
    assert 'RES = (os.environ.get("RES") or "").strip().lower()' in s
    assert "TFS.append" not in s and "TFS + [RES]" not in s, \
        "RES must never be added to the frames the shard measures"


def test_an_unknown_res_stops_the_shard_instead_of_measuring_v1_quietly():
    """A typo (`RES=1min`) that fell through to the v1 path would produce a
    whole run of rows the operator believes are minute-exact."""
    assert "if RES and RES not in br.TFS:" in _shard()
    assert "raise SystemExit" in _shard()


# -------------------------------------------------------- which engine, and why
def test_v2_measures_with_the_ENGINE_not_a_second_implementation():
    """`fast_grid` has no minute-exact settlement. Teaching it one would be a
    SECOND implementation of the exit rules — the drift this repo has paid for
    five times — so v2 calls the same `backtest_strategy(fine=)` the local v2
    sweep calls. That is the only thing that makes a fleet-measured v2 row and
    a PC-measured v2 row the same number."""
    code = _code_only(_shard())
    assert "at.backtest_strategy(" in code, "v2 must use the engine"
    assert "fine=fine" in code, "and hand it the minutes"
    # and the fused walk must be v1-only
    assert "if not RES:" in code, \
        "fast_grid.combo_six must be guarded off for v2"
    from tradingagents import fast_grid as fg

    assert "fine" not in inspect.signature(fg.combo_six).parameters, \
        ("if fast_grid ever grows `fine`, this test is the place to decide "
         "whether a second settlement implementation is really wanted")


def test_v2_ADDS_the_minutes_it_does_not_replace_the_bars_with_them():
    """THE 1d FAULT, Sep 22, 2026. The first cut rebuilt each frame FROM the
    minutes. That is equivalent where both exist — 666 of 666 XPIN hours
    identical to MEXC's own Min60 — but MEXC sells only ~30 days of 1-minute
    candles, so it capped every frame's history at 30 days.

    On 1d it deleted the timeframe. 30 days of minutes is 33 daily bars and
    every rule reads 300 before it may trade, so 33 - 300 = 0 measurable bars
    and EVERY 1d pair was skipped. Counted on the operator's own v2 store:
    1,001 pairs at 15m, 1,002 each at 30m/1h/4h, and ZERO at 1d against v1's
    1,080. That is what made "whatever exists on v1" untrue.

    The warm-up is history the rule READS, never bars it trades, so it must
    come from the frame's own candles — which the venue serves a year of."""
    code = _code_only(_shard())
    assert "df = at._closed_bars(fx.klines(sym, iv, cap), bs)" in code, \
        "the frame's OWN candles, for v1 and v2 alike"
    assert "msw.bars_from_1m" not in code, \
        "rebuilding the frame from minutes is what capped history at 30 days"
    # the minutes are still fetched, for the EXIT
    assert "br.TFS[RES]" in code and "fine = (" in code


def test_the_warmup_floor_still_applies_to_v2():
    """No trade inside the warm-up, where the indicators are still filling —
    `start_at=warm` is the engine's equivalent of the fused walk's
    `dirs_idx >= warm`."""
    assert "start_at=warm" in _code_only(_shard())


# ------------------------------------------------- which store a row belongs to
def test_a_v2_row_carries_res_and_unclear_and_a_v1_row_carries_neither():
    """`res` is what makes the id a v2 id (`backtest_report.row_code(res=)`),
    so a fleet v2 row can never collide with a v1 row. Absent on a v1 row, so
    a v1 row file is byte-identical to before."""
    code = _code_only(_shard())
    assert '**({"unclear": int(r.get("unclear", 0)), "res": RES}' in code
    assert "if RES else {}" in code
    # the pair-done markers ride the same rule, or the collector's store
    # guard rejects them
    assert code.count('**({"res": RES} if RES else {})') == 2, \
        "both pair_done markers must carry res"


def test_the_store_itself_refuses_a_row_measured_for_the_other_store():
    """THE SAFETY NET. Routing happens minutes to hours after the dispatch, in
    another process, across a run list nobody re-reads — so the check belongs
    where the bytes are written."""
    from tradingagents import cloud_sweep as cs, market_sweep as msw

    src = inspect.getsource(cs.land_rows)
    assert "msw.FINE_TF" in src
    assert "raise ValueError" in src
    # and it actually fires, in the direction this process is pointed
    other = "1m" if msw.FINE_TF != "1m" else ""
    row = {"coin": "AAA", "tf": "1h", "last_ms": 1, "res": other}
    with pytest.raises(ValueError, match="res="):
        cs.land_rows("AAA", "1h", [row])


def test_a_row_for_THIS_store_is_not_refused(monkeypatch, tmp_path):
    """The guard must not reject the ordinary case — a probe that fails
    everything has verified nothing."""
    from tradingagents import cloud_sweep as cs, market_sweep as msw

    seen = {}
    monkeypatch.setattr(msw, "pair_watermark", lambda c, t: 0)
    monkeypatch.setattr(msw, "pair_rows", lambda c, t: [])
    monkeypatch.setattr(msw, "merge_pair_rows",
                        lambda c, t, r: seen.setdefault("rows", r))
    monkeypatch.setattr(msw, "save_states", lambda *a, **k: None)
    row = {"coin": "AAA", "tf": "1h", "last_ms": 5}
    if msw.FINE_TF:
        row["res"] = msw.FINE_TF
    assert cs.land_rows("AAA", "1h", [row]) == "kept"
    assert seen["rows"] == [row]


# --------------------------------------------------------- the collect job
def test_a_v2_run_is_collected_by_its_own_job_into_the_v2_store():
    """One collect BODY; the v2 environment is what sends its rows to the v2
    store — the same pattern `download_v2` and `backtest_v2` already use."""
    from tradingagents import db_jobs as dj, stores

    assert "collect_v2" in dj.FILES
    assert "collect_v2" in dj._DISK_JOBS, \
        "or a v2 collect would run beside a sweep on the same disk"
    env = stores.for_kind("collect_v2").env_for()
    assert env["TRADINGAGENTS_FINE_TF"] == "1m"
    assert "v2" in env["TA_ROWS_DB"].replace("\\", "/").split("/")
    # and the dispatcher routes it through the one body
    src = inspect.getsource(dj.main)
    assert 'elif kind in ("collect", "collect_v2"):' in src


def test_the_v2_collect_writes_nowhere_near_the_v1_store():
    from tradingagents import stores

    v1 = stores.V1.env_for() if hasattr(stores, "V1") else {}
    v2 = stores.for_kind("collect_v2").env_for()
    for k, v in v2.items():
        if k == "TRADINGAGENTS_FINE_TF":
            continue
        assert v != v1.get(k), f"{k} is the same path in both stores"


# ------------------------------------------------------------- the dispatch
def test_the_dispatch_sends_res_to_the_fleet():
    from tradingagents import cloud_sweep as cs

    assert "res" in inspect.signature(cs.dispatch).parameters
    src = _code_only(inspect.getsource(cs.dispatch))
    assert 'f"res={res}"' in src
    assert 'f"min_days={min_days}"' not in src, \
        "that slot belongs to res now"


def test_UPDATE_on_v2_dispatches_the_fleet_instead_of_measuring_here():
    """v1's UPDATE goes to GitHub; v2's measured locally because the fleet had
    no minutes. It does now, so both buttons behave the same — "what ever
    existing on v1 i want on v2"."""
    from tradingagents import db_jobs as dj

    src = _code_only(inspect.getsource(dj._run_btupdate_v2))
    assert 'mode="update"' in src, "UPDATE must continue, never re-measure"
    assert 'res="1m"' in src, "and it must be a v2 run"
    assert "cs.dispatch(" in src
    assert "cs.remember(dispatched)" in src, \
        "or the collect cannot know which store the rows belong to"
    assert "_run_backtest(" not in src, "it must not measure on this PC"


def test_the_v2_update_keeps_its_own_plan_and_progress_files():
    """Two versions writing one file is how a screen reports the other
    store's run."""
    from tradingagents import db_jobs as dj

    for fn in (dj._write_run_plan, dj._finish_btupdate_cloud_only):
        assert "kind" in inspect.signature(fn).parameters, fn.__name__
    src = _code_only(inspect.getsource(dj._write_run_plan))
    assert 'f"db_{kind}.plan.json"' in src, \
        "the plan file is named after the job, not hardcoded to v1's"
    assert 'FILES[kind]' in _code_only(
        inspect.getsource(dj._finish_btupdate_cloud_only))


def test_the_v2_update_docstring_does_not_still_say_this_PC():
    """label-must-match-data reaches the prose a reader trusts: the function
    said "always on this PC" for the whole of the change that moved it."""
    from tradingagents import db_jobs as dj

    doc = dj._run_btupdate_v2.__doc__ or ""
    assert "always on this PC" not in doc
    assert "GITHUB" in doc.upper()


def test_the_v2_collect_writes_its_OWN_progress_file():
    """FOUND BY RUNNING IT, Sep 22, 2026. The first `collect_v2` finished run
    35607986601 in under a minute and `db_collect_v2.json` still read
    `{"running": true, "now": "starting"}` — because `_run_collect` took
    `FILES["collect"]` whatever kind it was. Two faults in one line: a v2
    collect looks like it never ends, and it overwrites the v1 collect's
    progress, which is how a screen comes to report the other store's run.

    The same fault as `_finish_btupdate_cloud_only` in the commit before, in
    the function beside it — so this asserts on the WHOLE family."""
    from tradingagents import db_jobs as dj

    for fn in (dj._run_collect, dj._write_run_plan,
               dj._finish_btupdate_cloud_only):
        assert "kind" in inspect.signature(fn).parameters, fn.__name__
        body = _code_only(inspect.getsource(fn))
        assert 'FILES["collect"]' not in body, fn.__name__
        assert 'FILES["btupdate"]' not in body, fn.__name__
    assert "_run_collect(spec, kind=kind)" in _code_only(
        inspect.getsource(dj.main))


def test_the_live_door_serves_ONE_store_and_says_which():
    """FOUND BY RUNNING IT. Run 35607986601 (Sep 21, 2026) measured BTC 1h on
    the fleet perfectly — 25,960 rows in 1 minute — and every live post came
    back HTTP 500, because the open door was a v1 door and `land_rows`
    refused rows carrying res="1m". Nothing was lost (the shard falls back to
    the artifact, which is the design), but the whole run posted nothing.

    A door writes through `market_sweep`'s roots, which come from its process
    environment, so it can only ever serve one store — and it must SAY which,
    or `ensure()` cannot tell a useful door from a useless one."""
    from tradingagents import cloud_sweep as cs, live_ingest as li

    assert "res" in inspect.signature(li.ensure).parameters
    src = _code_only(inspect.getsource(li.ensure))
    assert 'cur.get("res")' in src, "it must compare the OPEN door's store"
    assert "stop()" in src, "and replace a door for the other store"
    assert "_stores.V2.env_for()" in src, \
        "a v2 door is the same server in v2's environment"
    # the serving process publishes the store it actually runs in, never a
    # value the caller asserted
    serve = _code_only(inspect.getsource(li))
    assert '"res": _msw.FINE_TF' in serve
    # and the dispatch asks for the right one
    assert "li.ensure(res=res)" in _code_only(inspect.getsource(cs.dispatch))


def test_the_run_record_remembers_which_store_its_rows_belong_to():
    """The collect happens in another process, later. Without this the store
    cannot be worked out at all."""
    src = inspect.getsource(__import__(
        "tradingagents.cloud_sweep", fromlist=["x"]).dispatch)
    assert '"res": str(res or "")' in src
