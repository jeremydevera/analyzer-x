"""UPDATE on GitHub tests only the gap since each coin's last test.

Operator, 2026-09-09: *"if the last backtest was sep1 and i click update it
should run on github to update the gap which is sept 2 onwards simple as
that"*. Until this, a GitHub machine had no memory: every UPDATE measured the
whole window from scratch — and the collector then refused 99% of it ("already
measured here": 0, 1, 17, 4, 0, 0, 0, 9 pairs kept over eight runs).

Four parts, each pinned here:
* the shard SAVES every pair's position (fast_grid.end_state) as a `state-*`
  artifact and, in update mode, CONTINUES from it (resume_state.continue_combo)
* the workflow carries mode/state_runs in, and the state artifacts out
* the dispatch: UPDATE sends mode=update plus the runs holding the positions;
  BACKTEST sends mode=full
* the collector keeps the NEWER measurement instead of refusing anything with
  a watermark, and records which run holds the latest positions
"""
import importlib.util
import inspect
import json
import pathlib

import pytest

from tradingagents import cloud_sweep as cs, market_sweep as msw

REPO = pathlib.Path(__file__).resolve().parents[1]
SHARD = REPO / ".github" / "scripts" / "sweep_shard.py"
PROGRESS = REPO / ".github" / "scripts" / "progress.py"
YML = REPO / ".github" / "workflows" / "sweep.yml"
PANEL = REPO / "webapp" / "src" / "components" / "backtest" / "JobsPanel.tsx"
API_TS = REPO / "webapp" / "src" / "lib" / "api.ts"


@pytest.fixture
def shard(tmp_path, monkeypatch):
    """The shard imported as a module in a scratch cwd (it makes ./out)."""
    monkeypatch.chdir(tmp_path)
    for k, v in {"SHARD": "0", "SHARDS": "1", "TFS": "15m", "DAYS": "60",
                 "MODE": "update", "STATE_RUNS": "111,222"}.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("sweep_shard_update_test", SHARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "report", lambda *a, **k: None)
    return mod


# ------------------------------------------------------------- the shard
def test_the_shard_reads_mode_and_state_runs(shard):
    assert shard.MODE == "update"
    assert shard.STATE_RUNS == ["111", "222"]
    assert shard.VERSION.startswith("signals") and shard.VERSION.endswith("-th3")


def test_a_full_measure_saves_every_pairs_position():
    src = SHARD.read_text(encoding="utf-8")
    assert "with_trades=True" in src, "the walk must hand back its trades"
    assert "fg.end_state(" in src, "the saved position comes from end_state"
    assert "write_state(coin, tf, pair_states" in src, \
        "the full path must write the pair's saved position"
    i = src.index("def write_state(")
    body = src[i:src.index("\ndef ", i + 10)]
    for meta in ("__last_ms__", "__first_ms__", "__bars__", "__signals__",
                 "__version__", "__fee__"):
        assert meta in body, f"saved position lacks {meta}"
    assert 'os.path.join(STATE_OUT, f"{coin}-{tf}.json.gz")' in body


def test_update_mode_continues_from_the_saved_position():
    src = SHARD.read_text(encoding="utf-8")
    i = src.index("def continue_pair(")
    body = src[i:src.index("\ndef run_pair(", i)]
    assert "rs.gap_frame(df, last_ms, CONTEXT_BARS)" in body, \
        "the frame is the new bars plus the rules' lookback"
    assert "rs.continue_combo(" in body
    assert "fee=fee, sizing=sz" in body, \
        "the engine adds slippage itself — the taker fee alone, as the PC passes it"
    assert "start_at=off" in body
    # a saved position for a combination that was never measured cannot be
    # invented over a short frame: counted and skipped, never guessed
    assert "no_state += 1" in body
    # the dispatch: run_pair goes to continue_pair when a usable position exists
    j = src.index("def run_pair(")
    rp = src[j:src.index("\n    iv, bs, cap = br.TFS[tf]", j)]
    assert 'if MODE == "update":' in src[j:j + 2500]
    assert "state_usable(prior)" in src[j:j + 2500]
    assert "continue_pair(sym, tf, prior, out" in src[j:j + 2500]
    assert '_bump("fresh")' in src[j:j + 3000], "a full measure is counted"


def test_no_new_bars_writes_nothing_and_keeps_the_position():
    """An empty done-marker would make the collector wipe the stored rows
    (it takes 'marks and no rows' as 'measured, zero rows')."""
    src = SHARD.read_text(encoding="utf-8")
    i = src.index("if frame is None or new_bars <= 0:")
    branch = src[i:src.index("return 0", i)]
    assert "pair_done" not in branch
    assert "write_state(" in branch, "the position must be re-emitted or the chain loses it"


def test_a_saved_position_is_refused_when_the_rules_grew(shard):
    prior = {"__last_ms__": 5, "__version__": shard.VERSION,
             "__signals__": sorted(shard.br.SIGNALS)}
    assert shard.state_usable(prior) == ""
    fewer = dict(prior, __signals__=sorted(shard.br.SIGNALS)[:-1])
    assert "never measured" in shard.state_usable(fewer)
    other = dict(prior, __version__="signals105-th1")
    assert "fingerprint" in shard.state_usable(other)
    assert shard.state_usable({}) == "no watermark"


def test_a_saved_position_without_the_boundary_flag_is_measured_in_full(shard):
    """RCA-2026-09-09-R. The states run 34360893326 saved (the first ever
    written by a continuation) carry no `exit_at_last`; continuing from one
    would start a bar early on every combination whose last trade closed on
    that bar. One writer per file, so one combination speaks for all."""
    prior = {"__last_ms__": 5, "__version__": shard.VERSION,
             "__signals__": sorted(shard.br.SIGNALS),
             "mom6|0.2|0.3|0.4|flat": {"trades": 4001, "open": None, "step": 0}}
    why = shard.state_usable(prior)
    assert "exit_at_last" in why and "boundary" in why, why
    prior["mom6|0.2|0.3|0.4|flat"]["exit_at_last"] = False
    assert shard.state_usable(prior) == ""


def test_fetch_prior_states_takes_the_runs_newest_first(shard, monkeypatch, tmp_path):
    """NEWEST first, and the first run that has a pair keeps it.

    It walked oldest-first and let later runs overwrite, which was the same
    answer while the list was always one run long. From Sep 10, 2026 a run can
    be asked for two coins by name, so several runs hold positions at once —
    and a runner that runs out of disk must lose the OLDEST of them, not the
    freshest (`fetch_prior_states` stops downloading, in order)."""
    calls = []

    class R:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kw):
        if cmd[:3] != ["gh", "run", "download"]:
            return R()                # the size look-up: no stdout → unknown size
        calls.append(cmd)
        run_id = cmd[3]
        d = tmp_path / "state_in" / run_id / "state-0"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"AAA-15m.json.gz").write_bytes(b"x")          # both runs have AAA
        if run_id == "222":
            (d / "BBB-15m.json.gz").write_bytes(b"y")
        return R()
    monkeypatch.setattr(shard.subprocess, "run", fake_run)
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    # STATE_RUNS arrives newest first (cloud_sweep.state_runs_for)
    monkeypatch.setattr(shard, "STATE_RUNS", ["222", "111"])
    got = shard.fetch_prior_states()
    assert [c[3] for c in calls] == ["222", "111"], "in the order it was given"
    for c in calls:
        assert c[:3] == ["gh", "run", "download"] and "-p" in c and "state-*" in c
        assert "--repo" in c
    assert set(got) == {"AAA-15m", "BBB-15m"}
    assert "222" in got["AAA-15m"], "the newest run's file wins the pair"
    assert "111" not in got["AAA-15m"]


def test_fetch_prior_states_survives_a_failed_download(shard, monkeypatch):
    class R:
        returncode = 1
        stderr = "HTTP 404: not found"
    monkeypatch.setattr(shard.subprocess, "run", lambda cmd, **kw: R())
    assert shard.fetch_prior_states() == {}     # every pair measured in full


def test_fetch_prior_states_refuses_positions_the_disk_cannot_hold(shard, monkeypatch):
    """Whole-market arithmetic (harddev, after the 2-coin proof of Sep 09,
    2026): ~2.2 MB of saved position per pair × 5,347 pairs is ~12 GB, and
    EVERY machine downloads all of it because it cannot know which coins it
    will claim. A runner that cannot hold it measures in full — it must not
    die of a full disk half-way through the download, or later, writing its
    own rows."""
    logs = []
    monkeypatch.setattr(shard, "log", lambda m: logs.append(m))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(shard, "_free_gb", lambda path=".": 9.0)
    monkeypatch.setattr(shard, "_state_artifact_bytes", lambda run_id, repo: 12_000_000_000)
    monkeypatch.setattr(shard.subprocess, "run",
                        lambda *a, **k: pytest.fail("must not download what will not fit"))
    assert shard.fetch_prior_states() == {}
    assert sum(1 for m in logs if "12.0 GB" in m and "9.0 GB" in m
               and "measured in full" in m) == 2, logs      # one line per run

    # 12 GB against 21 GB free (the runner measured Sep 09, 2026) DOES fit
    monkeypatch.setattr(shard, "_free_gb", lambda path=".": 21.0)
    fits = []
    monkeypatch.setattr(shard.subprocess, "run", lambda cmd, **k: fits.append(cmd) or
                        type("R", (), {"returncode": 1, "stderr": ""})())
    shard.fetch_prior_states()
    assert [c[3] for c in fits] == ["111", "222"]


def test_a_failed_state_download_leaves_nothing_on_disk(shard, monkeypatch, tmp_path):
    """`gh run download` extracts as it goes; a run that dies half-way (a
    full disk, a cut connection) leaves files that would otherwise sit on the
    runner for the whole shard — and, unindexed, buy nothing."""
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(shard, "_state_artifact_bytes", lambda run_id, repo: None)

    class R:
        returncode = 1
        stderr = "HTTP 500"

    def fake_run(cmd, **kw):
        d = tmp_path / "state_in" / cmd[3] / "state-0"
        d.mkdir(parents=True, exist_ok=True)
        (d / "AAA-15m.json.gz").write_bytes(b"half")
        return R()
    monkeypatch.setattr(shard.subprocess, "run", fake_run)
    assert shard.fetch_prior_states() == {}
    assert not (tmp_path / "state_in" / "111").exists()
    assert not (tmp_path / "state_in" / "222").exists()


def test_the_row_shape_is_one_shape(shard):
    """Whichever engine measured a row, the store must never learn two
    dialects. These are the keys the full path's inline row writes."""
    full_keys = {"coin", "tf", "signal", "th", "sl", "tp", "rr", "sizing", "lev",
                 "base", "notional", "trades", "wins", "losses", "winrate",
                 "profit", "funding", "h1", "h2", "green", "months", "worst",
                 "dd", "streak", "streak_len", "liqs", "stop_reachable", "days",
                 "last_ms", "bars", "monthly", "cost_of_tp", "rt", "gate"}
    r = {"trades": 3, "wins": 2, "losses": 1, "profit": 1.234, "funding_total": -0.1,
         "months_green": 1, "months_total": 1, "worst_trade": -0.5, "max_dd": 0.7,
         "worst_streak": -0.5, "worst_streak_len": 1, "liqs": 0,
         "monthly": {"2026-08": 1.234}}
    row = shard._row("AAA", "15m", "mom6", 0.3, 0.01, 0.02, "flat", r, days=10,
                     bars=100, last_ms=5, fee=0.0004, rt=0.002, liq_known=True,
                     h1=1.0, h2=0.234)
    assert set(row) == full_keys | {"fee"}, set(row) ^ (full_keys | {"fee"})
    src = SHARD.read_text(encoding="utf-8")
    for k in full_keys:
        assert f'"{k}"' in src


def test_the_reporter_carries_mode_and_the_two_counts():
    src = PROGRESS.read_text(encoding="utf-8")
    for key in ('"mode": self.mode', '"continued": int(self.continued)',
                '"fresh": int(self.fresh)'):
        assert key in src, key


# ---------------------------------------------------------- the workflow
def test_the_workflow_carries_mode_and_state_in_and_the_positions_out():
    y = YML.read_text(encoding="utf-8")
    for s in ("mode:", "state_runs:", "MODE: ${{ github.event.inputs.mode }}",
              "STATE_RUNS: ${{ github.event.inputs.state_runs }}",
              "actions: read", "name: state-${{ matrix.shard }}",
              "path: out/state/*.json.gz", "retention-days: 90"):
        assert s in y, s
    # rows keep their shorter life; the positions outlive them on purpose
    i = y.index("name: state-${{ matrix.shard }}")
    assert "retention-days: 90" in y[i:i + 300]


# ---------------------------------------------------------- the dispatch
def test_update_dispatches_mode_update_with_the_state_runs(monkeypatch):
    src = (REPO / "tradingagents" / "db_jobs.py").read_text(encoding="utf-8")
    i = src.index("def _run_btupdate(")
    body = src[i:src.index("\ndef _write_run_plan(", i)]
    assert 'mode="update"' in body
    assert "state_runs=state_runs" in body
    assert 'cs.state_runs_for(plan["cloud"])' in body


def test_backtest_dispatches_mode_full():
    # the whole ROUTE, not a fixed slice of characters: at 1,200 bytes this
    # went red the moment a comment was added above the call (Sep 10, 2026)
    from tradingagents import api

    body = inspect.getsource(api.cloud_dispatch)
    assert 'mode="full"' in body


def test_dispatch_sends_mode_and_state_runs_to_github(monkeypatch):
    sent = []
    monkeypatch.setattr(cs, "available", lambda: (True, "o/r"))
    monkeypatch.setattr(cs, "_runs", lambda slug, limit=5: [
        {"databaseId": 7 if sent else 6, "url": "u", "status": "queued"}])
    monkeypatch.setattr(cs, "_gh", lambda *a, **k: sent.append(a) or "")
    monkeypatch.setattr(cs.time, "sleep", lambda s: None)
    got = cs.dispatch(timeframes="1h", mode="update", state_runs=["111", "222"])
    args = sent[0]
    assert "-f" in args and "mode=update" in args and "state_runs=111,222" in args
    assert got["mode"] == "update" and got["id"] == 7
    sent.clear()
    got = cs.dispatch(timeframes="1h")
    assert "mode=full" in sent[0] and "state_runs=" in sent[0]
    assert got["mode"] == "full"


# ---------------------------------------------------------- the collector
@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    (tmp_path / "state").mkdir()
    (tmp_path / "rows").mkdir()
    monkeypatch.setattr(cs, "STATE_RUNS_FILE", tmp_path / "cloud_state_runs.json")
    return tmp_path


def test_the_newer_measurement_wins_and_a_stale_one_is_refused(store):
    """The old rule refused ANY pair with a watermark and froze the store."""
    msw.save_pair_rows("AAA", "1h", [{"coin": "AAA", "tf": "1h"}])
    msw.save_states("AAA", "1h", {"__cloud__": True, "__last_ms__": 1_000})
    assert cs.is_fresher("AAA", "1h", 1_001) is True
    assert cs.is_fresher("AAA", "1h", 1_000) is False
    assert cs.is_fresher("AAA", "1h", 999) is False
    assert cs.is_fresher("NEW", "1h", 1) is True        # never measured
    src = (REPO / "tradingagents" / "cloud_sweep.py").read_text(encoding="utf-8")
    i = src.index("def collect_into_store(")
    body = src[i:src.index("\ndef land_rows(", i)]
    assert body.count("land_rows(") == 2, \
        "both the marker-only and the rows branch must ask the one rule"
    assert "is_fresher(" not in body and "pair_watermark(" not in body, \
        "the collector must not carry a freshness rule of its own"
    assert "pair_watermark(coin, tf) > 0" not in body, \
        "the store-freezing refusal is back"


def test_one_rule_writes_a_pair_whoever_brought_it(store):
    """`land_rows` is that rule, and BOTH ways in use it — the collector
    reading a finished run's artifacts, and the live door taking a pair the
    moment a machine finishes it. Two implementations of one store rule is
    RCA-2026-09-09-P (the collector kept a rule the shard had outgrown, and
    threw away 40,148,482 measured rows)."""
    row = {"coin": "AAA", "tf": "1h", "signal": "mom6", "last_ms": 1_000}
    assert cs.land_rows("AAA", "1h", [row]) == "kept"
    assert msw.pair_watermark("AAA", "1h") == 1_000

    assert cs.land_rows("AAA", "1h", [dict(row, last_ms=999)]) == "stale", \
        "an older run cannot win"
    assert cs.land_rows("AAA", "1h", [dict(row, last_ms=1_000)]) == "stale", \
        "equal is not newer"
    assert len(msw.pair_rows("AAA", "1h")) == 1
    assert msw.pair_rows("AAA", "1h")[0]["last_ms"] == 1_000

    assert cs.land_rows("AAA", "1h", [dict(row, last_ms=2_000)]) == "kept"
    assert msw.pair_watermark("AAA", "1h") == 2_000

    # a pair split across a shard file is not re-judged — and since
    # RCA-2026-09-11-B it is MERGED BY COMBINATION, never appended or replaced:
    # the same combination again is ONE row (re-measured wins), a new
    # combination is added, and nothing already there is ever dropped. The
    # replace that stood here deleted 1,261,358 rows and emptied 100 pairs.
    assert cs.land_rows("AAA", "1h", [dict(row, last_ms=2_000)],
                        append=True) == "kept"
    assert len(msw.pair_rows("AAA", "1h")) == 1, "same combination: one row"
    assert cs.land_rows("AAA", "1h", [dict(row, signal="rsi14", last_ms=2_000)],
                        append=True) == "kept"
    assert len(msw.pair_rows("AAA", "1h")) == 2, "a new combination is added"
    assert cs.land_rows("AAA", "1h", [dict(row, last_ms=3_000)]) == "kept"
    assert len(msw.pair_rows("AAA", "1h")) == 2, "a newer run never shrinks a pair"

    # a measured pair with no row that cleared the trade floor: an EMPTY rows
    # file plus a watermark, or the pair reads as never measured
    assert cs.land_rows("BBB", "1h", [], marks=[
        {"coin": "BBB", "tf": "1h", "pair_done": True, "last_ms": 5_000}]) == "empty"
    assert msw.pair_rows("BBB", "1h") == []
    assert msw.pair_watermark("BBB", "1h") == 5_000
    assert cs.land_rows("BBB", "1h", [], marks=[
        {"coin": "BBB", "tf": "1h", "pair_done": True, "last_ms": 4_999}]) == "stale"
    assert cs.land_rows("CCC", "1h", []) == "stale", "nothing to write is not a write"


def test_state_runs_are_recorded_per_timeframe_and_expire(store):
    now = 1_000_000.0
    day = 86400
    cs.record_state_run(501, ["15m", "30m"], now=now)
    cs.record_state_run(502, ["1h"], now=now + 2 * day)
    # NEWEST FIRST: the order is the priority the shard downloads in
    assert cs.state_runs_for(["15m", "1h"], now=now + 3 * day) == ["502", "501"]
    assert cs.state_runs_for(["30m"], now=now + 3 * day) == ["501"]
    assert cs.state_runs_for(["4h"], now=now + 3 * day) == []
    # the artifacts live 90 days; a record older than 85 is not offered —
    # 501 is 86 days old here, 502 only 84
    assert cs.state_runs_for(["15m"], now=now + 86 * day) == []
    assert cs.state_runs_for(["1h"], now=now + 86 * day) == ["502"]
    # A NEWER RUN DOES NOT ERASE THE OLDER ONE. Before Sep 10, 2026 it did,
    # which was harmless while every run measured the whole market — and
    # ruinous the moment a run could be two coins by name: the next UPDATE
    # would have found BTC's saved position and measured the other 1,063
    # coins from scratch (the RCA-2026-09-09-P shape).
    cs.record_state_run(503, ["15m"], now=now + 4 * day)
    assert cs.state_runs_for(["15m"], now=now + 5 * day) == ["503", "501"]
    assert cs.state_runs_for(["15m", "30m"], now=now + 5 * day) == ["503", "501"]
    # …but not for ever: three per timeframe, newest first
    for n, extra in enumerate((504, 505, 506), start=5):
        cs.record_state_run(extra, ["15m"], now=now + n * day)
    assert cs.state_runs_for(["15m"], now=now + 10 * day) == ["506", "505", "504"]
    # a record written by the old code (one dict, not a list) is still read
    cs.STATE_RUNS_FILE.write_text(json.dumps({"4h": {"run": 601, "at": now}}))
    assert cs.state_runs_for(["4h"], now=now + day) == ["601"]
    cs.record_state_run(602, ["4h"], now=now + 2 * day)
    assert cs.state_runs_for(["4h"], now=now + 3 * day) == ["602", "601"]


def test_collect_records_the_run_that_shipped_positions():
    src = (REPO / "tradingagents" / "cloud_sweep.py").read_text(encoding="utf-8")
    i = src.index("def collect_into_store(")
    body = src[i:src.index("\ndef is_fresher(", i)]
    assert "has_state_artifacts(run_id, slug)" in body
    assert "record_state_run(run_id, sorted(tfs_seen))" in body


# --------------------------------------------------------------- the screen
def test_the_header_tells_update_from_full_and_counts_both():
    p = PANEL.read_text(encoding="utf-8")
    assert 's.mode === "update"' in p
    assert "continued from a saved" in p and "measured in full" in p
    assert "UPDATE — testing only the new candles since each coin" in p
    assert "from scratch (BACKTEST)" in p
    # the old lie is gone: UPDATE no longer "re-measures every bar"
    assert "BACKTEST and\n                  UPDATE both re-measure" not in p
    assert "UPDATE both re-measure every bar" not in p
    t = API_TS.read_text(encoding="utf-8")
    for k in ('mode?: "full" | "update";', "continued?: number;", "fresh?: number;"):
        assert k in t, k
