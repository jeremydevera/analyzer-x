"""The cloud shard keeps the operator's two rules for a pair that fails.

2026-08-25, starting the 2-month sweep on the PC and GitHub together:
    "if the backtest failed for certain coin make sure to stop the process for
     that specific coin and retry it"

Before this the shard logged the error and moved on (`return 0`), so a cut
connection deleted a pair from the cloud's half of the grid with one log
line to say so. It also measured the full history whatever the operator's
window was, rejected anything under 2,000 bars (so 1h at 60 days, and 1d
always), and wrote rows as it went -- a pair that died half-way had already
left rows behind for a redo to sit on top of.
"""
import importlib.util
import pathlib

import pandas as pd
import pytest

from tradingagents import backtest_report as br, market_sweep as msw

REPO = pathlib.Path(__file__).resolve().parent.parent
SHARD = REPO / ".github" / "scripts" / "sweep_shard.py"


def _src() -> str:
    return SHARD.read_text(encoding="utf-8")


@pytest.fixture
def shard(tmp_path, monkeypatch):
    """The shard imported as a module, in a scratch cwd (it makes ./out)."""
    monkeypatch.chdir(tmp_path)
    for k, v in {"SHARD": "0", "SHARDS": "1", "TFS": "15m", "DAYS": "60",
                 "MIN_DAYS": "0", "COINS": "0"}.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("sweep_shard_under_test", SHARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "report", lambda *a, **k: None)
    # These tests guard the retry ORDER, not the cool-down length — without
    # this each end-of-run retry would really sleep 30 s in the suite.
    monkeypatch.setattr(mod, "RETRY_COOLDOWN_S", 0.0)
    return mod


def test_a_failed_pair_is_redone_behind_the_others_not_the_whole_shard(shard, monkeypatch, capsys):
    monkeypatch.setattr(shard, "eligible", lambda: ["A_USDT", "B_USDT"])
    calls = []

    def run_pair(sym, tf, out, **kw):
        calls.append(sym)
        if sym == "A_USDT" and calls.count("A_USDT") == 1:
            raise shard.PairFailed("A_USDT 15m: IncompleteRead(183452 bytes read)")
        out.write(f"{sym}\n")
        return 1

    monkeypatch.setattr(shard, "run_pair", run_pair)
    shard.main()
    assert calls == ["A_USDT", "B_USDT", "A_USDT"], \
        "the failed pair is redone AFTER the others, and only that pair"
    out = pathlib.Path(shard.OUT).read_text().split()
    assert out == ["B_USDT", "A_USDT"]
    log = capsys.readouterr().out
    assert "redoing 1/2 after the others" in log
    assert "1 pair redo(s)" not in log or "0 pair(s) lost" in log


def test_a_pair_that_never_recovers_is_named_and_the_rest_are_kept(shard, monkeypatch, capsys):
    monkeypatch.setattr(shard, "eligible", lambda: ["A_USDT", "B_USDT"])
    calls = []

    def run_pair(sym, tf, out, **kw):
        calls.append(sym)
        if sym == "A_USDT":
            raise shard.PairFailed("A_USDT 15m: transport failure")
        out.write(f"{sym}\n")
        return 1

    monkeypatch.setattr(shard, "run_pair", run_pair)
    shard.main()
    assert calls.count("A_USDT") == shard.PAIR_RETRIES + 1
    assert pathlib.Path(shard.OUT).read_text().split() == ["B_USDT"]
    log = capsys.readouterr().out
    assert "gave up after 2 redos" in log
    assert "lost: ['A_USDT 15m: A_USDT 15m: transport failure']" in log


def test_pair_retries_match_the_local_sweep(shard):
    assert shard.PAIR_RETRIES == msw.PAIR_RETRIES


def test_the_window_keeps_warm_up_in_FRONT_of_what_it_measures(shard):
    """DAYS is the window MEASURED; WARMUP_BARS of history ride in front of
    it so a 200-bar average is already defined at the first traded bar.

    This used to keep DAYS+30 CALENDAR days and trade the lot from bar zero.
    At 4h that spare 30 days is 180 bars — fewer than the 200 a confluence
    rule reads — so the rule was blind over the start of its own window and
    MAV 4h produced 0 signals where 11 existed (Sep 11, 2026).
    """
    now = pd.Timestamp.now("UTC").tz_localize(None)
    # 5 bars older than the window, 3 inside it
    df = pd.DataFrame({
        "Date": [now - pd.Timedelta(days=d)
                 for d in (200, 150, 120, 100, 80, 40, 20, 1)],
        "Close": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]})
    got, warm = shard.window(df)
    assert shard.DAYS == 60
    # everything is kept (warm-up is capped by what exists), and `warm` says
    # how many of the leading bars are history rather than measurement
    assert list(got["Close"]) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    assert warm == 5, "the five bars older than 60 days are warm-up"
    assert list(got["Close"])[warm:] == [6.0, 7.0, 8.0]


def test_the_warm_up_is_capped_by_the_history_that_exists(shard):
    """A young contract has no 300 bars to spare; it warms with what it has
    rather than refusing to be measured."""
    now = pd.Timestamp.now("UTC").tz_localize(None)
    df = pd.DataFrame({"Date": [now - pd.Timedelta(days=d) for d in (5, 3, 1)],
                       "Close": [1.0, 2.0, 3.0]})
    got, warm = shard.window(df)
    assert warm == 0 and len(got) == 3


def test_the_floor_and_the_rows_are_the_shared_rules():
    src = _src()
    assert "br.min_bars(tf)" in src, "one floor definition, shared with the local sweep"
    assert "len(df) < 2000" not in src, "the private 2,000-bar floor rejected 1h at 60 days"
    assert "lines.append(json.dumps(" in src and 'out.write("".join(lines))' in src, \
        "rows are buffered until the pair completes"
    assert "out.write(json.dumps(" not in src
    # Scoped to run_pair: the age screen (`old_enough`) is ALLOWED to log an
    # exception, because it KEEPS the coin when the check fails — the sin this
    # guards against is a venue failure inside run_pair being logged and the
    # pair dropped instead of raised for main() to redo.
    rp = src[src.index("def run_pair("):src.index("\ndef ", src.index("def run_pair("))]
    assert 'raise PairFailed(' in rp and 'except Exception as exc:\n        log(' not in rp, \
        "a venue failure is raised for main() to redo, not logged and dropped"


def test_the_workflow_carries_the_window_to_the_shard():
    wf = (REPO / ".github" / "workflows" / "sweep.yml").read_text(encoding="utf-8")
    assert "      days:\n" in wf
    assert "DAYS: ${{ github.event.inputs.days }}" in wf
    src = _src()
    assert 'os.environ.get("DAYS", "365")' in src


def test_the_daily_floor_is_reachable_for_a_year_and_for_two_months():
    assert br.min_bars("1d") <= 90 and br.min_bars("1d") <= 395
