"""29.7 million measured rows were thrown away because of an artifact NAME.

Timeline, 2026-08-25:
  11:56am  run 32807053611 dispatched, 20 shards
   3:09pm  20/20 shards done, 29,757,594 rows measured, 3.3 GB uploaded as
           twenty `rows-0` ... `rows-19` artifacts
   7:11am UTC the workflow's `merge` job starts and loads every row into one
           Python list; at ~12 GB on a 7 GB runner it is OOM-killed four
           minutes in ("The runner has received a shutdown signal")
   3:16pm  the collector asks for `sweep-results`, which the dead merge job
           never wrote, and logs "ended with no usable artifact — releasing it"

Nothing was corrupted and nothing expired: the collector simply asked for the
wrong name and the store stayed at 0.6%.
"""

import json

import pytest

from tradingagents import cloud_sweep as cs


@pytest.fixture
def store(tmp_path, monkeypatch):
    from tradingagents import market_sweep as msw
    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    (tmp_path / "state").mkdir()
    (tmp_path / "rows").mkdir()
    return tmp_path


def _artifacts(monkeypatch, names, expired=()):
    def gh(*a, **k):
        if a[0] == "api":
            return json.dumps({"artifacts": [
                {"name": n, "expired": n in expired} for n in names]})
        raise AssertionError(f"unexpected gh call {a}")
    monkeypatch.setattr(cs, "_gh", gh)
    monkeypatch.setattr(cs, "repo_slug", lambda *a, **k: "me/repo")


def test_the_per_shard_artifacts_are_preferred(monkeypatch):
    """They ARE the measurement; sweep-results is only a concatenation."""
    _artifacts(monkeypatch, ["rows-0", "rows-10", "rows-2", "sweep-results"])
    assert cs.artifact_names(1) == ["rows-0", "rows-2", "rows-10"], \
        "numeric order, not lexical -- rows-10 must not sort before rows-2"


def test_the_merged_artifact_is_the_fallback(monkeypatch):
    _artifacts(monkeypatch, ["sweep-results"])
    assert cs.artifact_names(1) == ["sweep-results"]


def test_a_dead_merge_job_no_longer_discards_the_shards(monkeypatch):
    """The exact 2026-08-25 shape: merge died, so only rows-N exist."""
    _artifacts(monkeypatch, [f"rows-{i}" for i in range(20)])
    got = cs.artifact_names(1)
    assert len(got) == 20 and got[0] == "rows-0" and got[-1] == "rows-19"


def test_an_expired_artifact_is_not_offered(monkeypatch):
    _artifacts(monkeypatch, ["rows-0", "rows-1"], expired={"rows-0"})
    assert cs.artifact_names(1) == ["rows-1"]


def test_no_artifact_says_so_instead_of_looking_like_zero_rows(monkeypatch,
                                                              store):
    _artifacts(monkeypatch, [])
    r = cs.collect_into_store(1)
    assert r["rows"] == 0 and "no live artifact" in r["why"]


# ------------------------------------------------------------------ streaming
def _download(monkeypatch, per_name):
    """Fake `gh run download`: write the shard's jsonl into the temp dir."""
    monkeypatch.setattr(cs, "repo_slug", lambda *a, **k: "me/repo")

    def gh(*a, **k):
        if a[0] == "api":
            return json.dumps({"artifacts": [{"name": n, "expired": False}
                                             for n in per_name]})
        if a[0] == "run" and a[1] == "download":
            name = a[a.index("-n") + 1]
            out = a[a.index("-D") + 1]
            import pathlib
            p = pathlib.Path(out) / f"{name}.jsonl"
            p.write_text("\n".join(json.dumps(r) for r in per_name[name]))
            return ""
        raise AssertionError(f"unexpected gh call {a}")

    monkeypatch.setattr(cs, "_gh", gh)


def _row(coin, tf, sig, last_ms=1000):
    return {"coin": coin, "tf": tf, "signal": sig, "last_ms": last_ms}


def test_rows_land_in_the_store_per_pair(monkeypatch, store):
    from tradingagents import market_sweep as msw
    _download(monkeypatch, {
        "rows-0": [_row("APEX", "1h", "mom6"), _row("APEX", "1h", "rsi14"),
                   _row("APEX", "4h", "mom6"), _row("PI", "1h", "mom6")]})
    r = cs.collect_into_store(1)
    assert r == {"pairs": 3, "rows": 4, "coins": 2, "artifacts": 1,
                 "skipped": 0, "skipped_pairs": [], "unparseable": 0,
                 "why_skipped": ""}
    assert len(msw.pair_rows("APEX", "1h")) == 2
    assert len(msw.pair_rows("APEX", "4h")) == 1
    assert msw.pair_watermark("APEX", "1h") == 1000


def test_it_never_holds_more_than_one_pair(monkeypatch, store):
    """The whole point: the cloud died loading 29.7M rows into one list."""
    from tradingagents import market_sweep as msw
    high = []
    real = msw.save_pair_rows

    def spy(coin, tf, rows):
        high.append(len(rows))
        return real(coin, tf, rows)

    monkeypatch.setattr(msw, "save_pair_rows", spy)
    _download(monkeypatch, {"rows-0": [_row(f"C{i}", "1h", "mom6")
                                       for i in range(500)]})
    cs.collect_into_store(1)
    assert max(high) == 1, "one pair per write, never an accumulated list"


def test_a_locally_measured_pair_is_never_overwritten(monkeypatch, store):
    from tradingagents import market_sweep as msw
    msw.save_pair_rows("APEX", "1h", [{"coin": "APEX", "mine": True}])
    msw.save_states("APEX", "1h", {"__last_ms__": 999})
    _download(monkeypatch, {"rows-0": [_row("APEX", "1h", "mom6"),
                                       _row("PI", "1h", "mom6")]})
    r = cs.collect_into_store(1)
    assert r["skipped"] == 1 and r["skipped_pairs"] == ["APEX 1h"]
    assert msw.pair_rows("APEX", "1h") == [{"coin": "APEX", "mine": True}]
    assert r["pairs"] == 1


def test_a_refused_pair_seen_twice_is_still_not_overwritten(monkeypatch, store):
    """The first draft marked a refused pair in `written`, so its SECOND
    sighting took the append branch and clobbered the local rows."""
    from tradingagents import market_sweep as msw
    msw.save_pair_rows("APEX", "1h", [{"mine": True}])
    msw.save_states("APEX", "1h", {"__last_ms__": 999})
    _download(monkeypatch, {"rows-0": [_row("APEX", "1h", "a"),
                                       _row("PI", "1h", "x"),
                                       _row("APEX", "1h", "b")]})
    cs.collect_into_store(1)
    assert msw.pair_rows("APEX", "1h") == [{"mine": True}]


def test_a_pair_split_across_the_file_is_appended_not_replaced(monkeypatch,
                                                              store):
    from tradingagents import market_sweep as msw
    _download(monkeypatch, {"rows-0": [_row("APEX", "1h", "a"),
                                       _row("PI", "1h", "x"),
                                       _row("APEX", "1h", "b")]})
    cs.collect_into_store(1)
    sigs = [r["signal"] for r in msw.pair_rows("APEX", "1h")]
    assert sigs == ["a", "b"], "both halves kept"


def test_a_truncated_last_line_does_not_lose_the_file(monkeypatch, store):
    """A runner killed at the 6h ceiling leaves half a line behind."""
    from tradingagents import market_sweep as msw
    monkeypatch.setattr(cs, "repo_slug", lambda *a, **k: "me/repo")

    def gh(*a, **k):
        if a[0] == "api":
            return json.dumps({"artifacts": [{"name": "rows-0",
                                              "expired": False}]})
        import pathlib
        out = pathlib.Path(a[a.index("-D") + 1]) / "rows-0.jsonl"
        out.write_text(json.dumps(_row("APEX", "1h", "a")) + "\n"
                       + '{"coin":"PI","tf":"1h","sig')
        return ""

    monkeypatch.setattr(cs, "_gh", gh)
    r = cs.collect_into_store(1)
    assert r["rows"] == 1 and r["unparseable"] == 1
    assert len(msw.pair_rows("APEX", "1h")) == 1


def test_one_artifact_failing_to_download_does_not_stop_the_rest(monkeypatch,
                                                                store):
    from tradingagents import market_sweep as msw
    monkeypatch.setattr(cs, "repo_slug", lambda *a, **k: "me/repo")

    def gh(*a, **k):
        if a[0] == "api":
            return json.dumps({"artifacts": [
                {"name": "rows-0", "expired": False},
                {"name": "rows-1", "expired": False}]})
        name = a[a.index("-n") + 1]
        if name == "rows-0":
            raise RuntimeError("network died")
        import pathlib
        (pathlib.Path(a[a.index("-D") + 1]) / "x.jsonl").write_text(
            json.dumps(_row("PI", "4h", "a")))
        return ""

    monkeypatch.setattr(cs, "_gh", gh)
    r = cs.collect_into_store(1)
    assert r["pairs"] == 1 and len(msw.pair_rows("PI", "4h")) == 1


def test_the_cloud_watermark_is_actually_readable(monkeypatch, store):
    """save_states preserves dict order and pair_watermark reads the last 256
    bytes with the key anchored to the closing brace. Writing __last_ms__ FIRST
    therefore produced `{"__last_ms__":1000,"__cloud__":true}`, whose tail read
    misses -- so every cloud-merged pair reported watermark 0, meaning 'never
    measured'."""
    from tradingagents import market_sweep as msw
    _download(monkeypatch, {"rows-0": [_row("APEX", "1h", "a", last_ms=1234)]})
    cs.collect_into_store(1)
    assert msw.pair_watermark("APEX", "1h") == 1234
    st = msw.load_states("APEX", "1h")
    assert st["__cloud__"] is True
    assert list(st)[-1] == "__last_ms__", "the key the tail read needs is last"


def test_merge_into_store_writes_a_readable_watermark_too(store):
    """The list-shaped path has the same trap, and had the same bug."""
    from tradingagents import market_sweep as msw
    cs.merge_into_store([{"coin": "PI", "tf": "4h", "signal": "a",
                          "last_ms": 555}])
    assert msw.pair_watermark("PI", "4h") == 555


def test_the_workflow_merge_job_cannot_run_out_of_memory():
    """It loaded every row into one list. 29,757,594 rows is about 12 GB of
    dicts on a 7 GB runner, so it was OOM-killed and `sweep-results` was never
    written -- which is what made the collector discard the sweep."""
    import pathlib
    y = pathlib.Path(".github/workflows/sweep.yml").read_text()
    job = y[y.index("  merge:"):]

    # the incident is DESCRIBED in the comments, so assert against the code
    code = "\n".join(ln for ln in job.splitlines()
                     if not ln.lstrip().startswith("#"))

    assert "rows.append(" not in code, "no accumulating every row"
    assert "rows = bad = surv = 0" in code, "counters, not lists"
    assert "rows-all.jsonl" not in code, (
        "no 3.3 GB concatenation: the per-shard artifacts are the measurement")
    assert "upload-artifact" not in code, (
        "and no duplicate upload -- collect_into_store reads rows-N directly")


def test_the_shard_artifacts_are_kept_long_enough_to_recover_from(monkeypatch):
    """rows-N is now the ONLY copy, so its retention is the recovery window."""
    import pathlib
    import re
    y = pathlib.Path(".github/workflows/sweep.yml").read_text()
    sweep = y[y.index("  sweep:"):y.index("  merge:")]
    days = int(re.search(r"retention-days:\s*(\d+)", sweep).group(1))
    assert days >= 14, "a fortnight to notice and re-collect"
    assert "name: rows-${{ matrix.shard }}" in sweep
