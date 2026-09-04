"""UPDATE BACKTEST re-checks memory exactly like BACKTEST does.

Operator, Sep 04, 2026: *"WHY DID IT NEVER RECHECK? THIS IS A TOTAL BUG, FIX
THIS AND APPLY TO THE UPDATE BACKTEST AS WELL"*.

WHY IT NEVER RECHECKED. There was no code that asked twice. `n_workers` was
computed once, handed to `ProcessPoolExecutor(max_workers=n_workers)` — a size
fixed at construction, which that class cannot change — and all 4,124 pairs
were submitted up front, so the completion loop had nothing to decide. The
3:30pm reading of 3.9 GB free was therefore the run's size for its whole
31.8-hour life, while free memory went back up to 5.6 GB within minutes.

`ff2ee711cf` (Sep 04, 2026 11:03am) made the window follow memory. This file
covers the operator's second half: that UPDATE gets it too, and keeps it.

It already does, structurally — `_run_btupdate` finishes by calling
`_run_backtest(..., files_key="btupdate", kind="btupdate")`, the same body,
with no branch on `kind` anywhere near the planner. But nothing said so, and
"the same fix applied in one place and not the other" is precisely what cost
this repo the empty demo book on the same day (a paper slot key changed in
`state_key` and not in `run_cycle`). So the delegation is pinned, and the
re-check is driven end to end through the UPDATE entry point.
"""
from __future__ import annotations

import pytest

from tradingagents import backtest_report as br, db_jobs as dj


@pytest.fixture()
def paths(tmp_path, monkeypatch):
    """Both jobs' files under tmp, so nothing touches the real store."""
    monkeypatch.setattr(dj, "STATE_DIR", tmp_path)
    files = {}
    for key in ("backtest", "btupdate"):
        files[key] = {"progress": tmp_path / f"db_{key}.json",
                      "spec": tmp_path / f"db_{key}.spec.json",
                      "pid": tmp_path / f"db_{key}.pid",
                      "stop": tmp_path / f"db_{key}.STOP",
                      "handoff": tmp_path / f"db_{key}.HANDOFF"}
    monkeypatch.setattr(dj, "FILES", files)
    return files


def _quiet(monkeypatch):
    """Nothing in these tests may reach the network, the store or the bell."""
    monkeypatch.setattr(dj, "free_gb", lambda path=None: 500.0)
    monkeypatch.setattr(dj, "free_ram_settled", lambda *a, **k: 8.0)
    monkeypatch.setattr(dj, "persist_results", lambda *a, **k: None)
    monkeypatch.setattr(dj, "_bell", lambda *a, **k: None, raising=False)


def test_the_update_job_runs_the_same_body_as_the_backtest_job():
    """One planner, because there is one body. A `kind`-dependent copy is how
    a fix lands on one button only."""
    import inspect

    upd = inspect.getsource(dj._run_btupdate)
    assert "_run_backtest(" in upd, "UPDATE must delegate, not duplicate"
    assert 'files_key="btupdate"' in upd and 'kind="btupdate"' in upd

    inner = inspect.getsource(dj._run_backtest_inner)
    assert "make_worker_planner(" in inner, "the body owns the planner"
    assert "plan_workers=plan_workers" in inner, "and hands it to the grid"
    # the planner must not be reachable only on one kind
    head = inner[:inner.index("make_worker_planner(")]
    assert 'kind == "backtest"' not in head and 'kind != "btupdate"' not in head, \
        "the window must not be gated on which button was pressed"


def test_an_update_run_re_asks_and_republishes(paths, monkeypatch):
    """Drive the real UPDATE entry point. The planner is consulted more than
    once, and the number the panel shows follows the memory it was given."""
    _quiet(monkeypatch)
    monkeypatch.setattr(dj, "stored_symbols", lambda: ["AAA_USDT"])
    from tradingagents import capacity as cap

    monkeypatch.setattr(cap, "plan",
                        lambda tfs, ignore=(): {"local": list(tfs), "cloud": [],
                                                "why": "all local for the test"})
    import os as _os

    # 11 cores offered, and a machine whose free memory RISES between pairs.
    # `_run_backtest_inner` does `import os as _os` and calls `_os.cpu_count`,
    # which is this same module object.
    monkeypatch.setattr(_os, "cpu_count", lambda: 12)
    readings = iter([3.9, 3.9, 5.6, 8.0])
    monkeypatch.setattr(dj, "free_ram_gb", lambda: next(readings, 8.0))

    asked: list = []
    published_beats: list = []
    _real_write = dj._write

    def _spy(path, payload):
        if str(path).endswith("db_btupdate.json") and isinstance(payload, dict):
            published_beats.append(dict(payload))
        return _real_write(path, payload)

    monkeypatch.setattr(dj, "_write", _spy)

    def fake_grid(coins, tfs, **kw):
        """Stand in for the sweep: finish two pairs, asking the planner after
        each one exactly as `_measure_pairs` does."""
        plan = kw["plan_workers"]
        prog = kw["progress"]
        for i in (1, 2):
            asked.append(plan())
            prog(f"AAA {tfs[0]}: done ({i}/2)", i / 2, i, 2)
        return {"rows": [], "tested": 0}

    monkeypatch.setattr(br, "grid_from_store", fake_grid)

    dj._run_btupdate({"coins": [], "tfs": ["15m"], "base": 5.0, "days": 365,
                      "use_cloud": False})

    assert len(asked) >= 2, f"the planner was consulted {len(asked)} time(s)"
    assert asked[0] != asked[-1], (
        f"the window never moved while memory went 3.9 -> 8.0 GB: {asked}")
    assert asked[-1] > asked[0], f"more memory must mean more pairs: {asked}"

    # The HEARTBEAT, not the completion payload. A finished job stops
    # publishing a core count, so asserting on the final file failed with
    # KeyError('cores') — a test that would have passed for the wrong reason
    # had the key merely been absent-and-optional.
    beats = [b for b in published_beats if "cores" in b]
    assert beats, "the run published no core count at all"
    assert beats[-1]["cores"] == asked[-1], \
        "the panel must show the CURRENT window, not the startup figure"


def test_the_update_panel_never_shows_a_stale_reason(paths, monkeypatch):
    """label-must-match-data, the exact contradiction the operator spotted:
    a frozen "3.9 GB free" sentence beside a live RAM figure."""
    _quiet(monkeypatch)
    monkeypatch.setattr(dj, "stored_symbols", lambda: ["AAA_USDT"])
    from tradingagents import capacity as cap

    monkeypatch.setattr(cap, "plan",
                        lambda tfs, ignore=(): {"local": list(tfs), "cloud": [],
                                                "why": "all local for the test"})
    import os as _os

    monkeypatch.setattr(_os, "cpu_count", lambda: 12)      # 11 offered
    # The planner is primed at 3.9 and re-asked at 5.6; every reading AFTER
    # that is 8.0. So a `_publish` that takes its OWN fresh reading prints
    # 8.0 beside a sentence that says 5.6, and the test fails — which is the
    # whole point. Equal readings here would let the bug pass unnoticed.
    readings = iter([3.9, 5.6])
    monkeypatch.setattr(dj, "free_ram_gb", lambda: next(readings, 8.0))

    def fake_grid(coins, tfs, **kw):
        kw["plan_workers"]()
        kw["progress"]("AAA 15m: done (1/1)", 1.0, 1, 1)
        return {"rows": [], "tested": 0}

    beats: list = []
    _real_write = dj._write

    def _spy(path, payload):
        if str(path).endswith("db_btupdate.json") and isinstance(payload, dict):
            beats.append(dict(payload))
        return _real_write(path, payload)

    monkeypatch.setattr(dj, "_write", _spy)
    monkeypatch.setattr(br, "grid_from_store", fake_grid)
    dj._run_btupdate({"coins": [], "tfs": ["15m"], "base": 5.0, "days": 365,
                      "use_cloud": False})

    withwhy = [b for b in beats if b.get("cores_why")]
    assert withwhy, "no heartbeat carried a reason to check"
    got = withwhy[-1]
    why = got["cores_why"]
    # it moved off the reading the run STARTED with
    assert "3.9 GB free" not in why, \
        f"the startup reading is still on screen: {why!r}"
    # and it AGREES with the figure printed beside it. Before this, `_publish`
    # took its own fresh free_ram_gb() while `why` kept the planner's, so the
    # two could never be from the same instant — "3 of 11 cores: 3.9 GB free"
    # beside "RAM 5.6/16 GB free" is one instant arguing with another.
    assert f"{got['ram_free_gb']:.1f} GB free" in why, \
        f"the sentence must name the memory the number came from: {why!r}"
