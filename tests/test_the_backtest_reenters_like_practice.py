"""Backtest v2 acts on the candle a trade CLOSED in, as practice and real money
do (Oct 13, 2026).

The operator asked *"Does all practice trades exists in the backtests?"*. Of
their 44 practice trades on Gate, 33 were in their rows' own trade lists. The
runner reads a candle's signal when it closes and no trade is held — a trade
that closed INSIDE that candle frees it — while the stored rows resumed one
candle later (`reenter=False`, kept on Oct 05, 2026 so old numbers would not
move). JASMY 30m cf_soup1, #5Z98N2D4: a LONG filled 7:30am and stopped at
7:38am, inside the 7:30am candle; practice read that candle at 8:00am and
bought (HJHEBTSX), the row skipped it. Under practice's rule 38 of the 44
matched, all 38 ending the same way. The operator: *"then do A"*.

ONE rule, `backtest_report.reenter_for(res)`, the way `sizings_for(res)`
decides flat-only: Backtest v2 MEASURES under it; v1 keeps its rule byte for
byte (it holds nothing on Gate, and its saved positions and parity tests are
built on it). And every row carries the rule its walk followed (`reenter`),
so a row, its trade list, its last-N-days window and the DEMO figure the
watcher switches by are always walked the way that row was measured — never
the 22,747,944 rows of Oct 13, 2026's morning replayed under a rule they were
not measured with until GitHub re-measures them (the review's finding).
"""
import ast
import inspect
import json
import textwrap
from pathlib import Path

import pandas as pd
import pytest

from tests.test_fast_grid import BARRIERS, _dirs, _frame
from tests.test_the_demo_column_reads_the_last_30_days import NOW, SLOT, home  # noqa: F401
from tests.test_v2_reads_from_its_own_store import H0, v2  # noqa: F401  (fixture)
from tradingagents import (
    auto_trader as at,
    backtest_report as br,
    fast_grid as fg,
    market_sweep as msw,
    rolling30 as r30,
)

ROOT = Path(__file__).resolve().parents[1]
WHY = {fg.WHY_TP: "TP", fg.WHY_SL: "SL", fg.WHY_LIQ: "LIQ", fg.WHY_END: "END"}


def test_backtest_v2_reenters_and_v1_keeps_its_rule():
    assert br.reenter_for("1m") is True
    assert br.reenter_for("") is False and br.reenter_for(None) is False


def _engine_trades(df, dirs, *, tp, sl, reenter):
    key = "mom6_reenter_test"
    at.STRATEGY_SPECS[key] = {"interval": "Min60", "bar_seconds": 3600,
                              "tp": tp, "sl": sl, "threshold": 0.003}
    try:
        r = at.backtest_strategy(key, df, 5.0, fee=0.0004, sizing="flat", dirs=dirs,
                                 tp=tp, sl=sl, liq_move_pct=4.5, funding=[],
                                 keep_log=True, reenter=reenter)
    finally:
        at.STRATEGY_SPECS.pop(key, None)
    return [(t["exit_bar"], 1 if t["side"] == "LONG" else -1, t["why"]) for t in r["log"]]


def _walk_trades(df, dirs, *, tp, sl, reenter):
    ms = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    got = fg.walk([k for k, v in enumerate(dirs) if v], dirs,
                  [float(x) for x in df["Open"]], [float(x) for x in df["High"]],
                  [float(x) for x in df["Low"]], [float(x) for x in df["Close"]],
                  tp=tp, sl=sl, liq=0.045, bar_ms=ms, reenter=reenter)
    return [(x, s, WHY[w]) for (_i, _e, x, s, _o, w, _f) in got]


@pytest.mark.parametrize("sl,tp", BARRIERS)
def test_the_fast_walk_reenters_exactly_like_the_engine(sl, tp):
    """The daily replays walk with fast_grid; the rows are measured by the
    engine. Under the new rule they must still be the same trades."""
    df = _frame()
    dirs = _dirs(len(df))
    assert _walk_trades(df, dirs, tp=tp, sl=sl, reenter=True) == \
        _engine_trades(df, dirs, tp=tp, sl=sl, reenter=True)


def test_the_rule_changes_trades_on_this_data():
    """Not a no-op: on the parity fixture at least one barrier pair trades a
    signal on the candle its previous trade closed in."""
    df = _frame()
    dirs = _dirs(len(df))
    assert any(_engine_trades(df, dirs, tp=tp, sl=sl, reenter=True)
               != _engine_trades(df, dirs, tp=tp, sl=sl, reenter=False)
               for sl, tp in BARRIERS)


def _jasmy():
    """#5Z98N2D4's shape on one timeline: a LONG signal on candle 0, bought at
    candle 1's open (100), stopped inside candle 2 (low 98.5 under the 99
    stop) — and candle 2 is itself a LONG signal."""
    n = 8
    t0 = 1_791_870_000_000
    df = pd.DataFrame({
        "Date": pd.to_datetime([t0 + k * 1_800_000 for k in range(n)], unit="ms"),
        "Open": [100.0] * n,
        "High": [100.4, 100.4, 100.2, 100.4, 100.4, 100.4, 100.4, 100.4],
        "Low": [99.6, 99.6, 98.5, 99.6, 99.6, 99.6, 99.6, 99.6],
        "Close": [100.0] * n, "Volume": [1.0] * n})
    return df, [1, 0, 1, 0, 0, 0, 0, 0]


def test_a_trade_closed_inside_a_candle_frees_that_candles_signal():
    df, dirs = _jasmy()
    plain = _engine_trades(df, dirs, tp=0.02, sl=0.01, reenter=False)
    again = _engine_trades(df, dirs, tp=0.02, sl=0.01, reenter=True)
    assert plain == [(2, 1, "SL")], "the store's old rule: candle 2's signal is skipped"
    assert again == [(2, 1, "SL"), (7, 1, "END")], "practice buys on candle 3's open"
    assert _walk_trades(df, dirs, tp=0.02, sl=0.01, reenter=True) == again


def _spy(monkeypatch):
    seen: list = []
    real = at.backtest_strategy

    def spy(*a, **k):
        seen.append(k.get("reenter"))
        return real(*a, **k)

    monkeypatch.setattr(at, "backtest_strategy", spy)
    return seen


def _stamp(store, on: bool) -> None:
    p = store.home / "rows" / "XPIN-1h.json"
    rows = json.loads(p.read_text())
    for r in rows:
        r.pop("reenter", None)
        if on:
            r["reenter"] = True
    p.write_text(json.dumps(rows))


def test_a_rows_trade_list_follows_the_rule_it_was_measured_with(v2, monkeypatch):  # noqa: F811
    """Review, Oct 13, 2026: chosen per STORE, every one of the 22,747,944
    rows measured that morning under the old rule would have been replayed
    under the new one until GitHub re-measured it, its trade list no longer
    adding up to it. Each row carries the rule its walk followed."""
    seen = _spy(monkeypatch)
    kw = {"signal": "ote", "th": 0.0, "sl": 3.0, "tp": 1.0, "sizing": "flat", "store": v2}
    got = msw.trades_for("XPIN", "1h", **kw)
    assert got.get("log") and seen == [False], "measured before: the old rule"
    _stamp(v2, True)
    seen.clear()
    msw.trades_for("XPIN", "1h", **kw)
    assert seen == [True], "measured under practice's rule"
    _stamp(v2, False)
    seen.clear()
    msw.trades_for("XPIN", "1h", whole=True, **kw)
    assert seen == [True], "a replay up to today is a fresh walk: today's rule"
    seen.clear()
    msw.trades_for("XPIN", "1h", reenter=False, **kw)
    assert seen == [False], "an explicit caller still decides"


def test_a_rows_days_window_follows_its_own_rule(v2, monkeypatch):  # noqa: F811
    import time as _time

    seen = _spy(monkeypatch)
    monkeypatch.setattr(_time, "time", lambda: (H0 + 5 * 86_400_000) / 1000)
    row = {"id": "X", "coin": "XPIN", "tf": "1h", "signal": "ote", "th": 0.0,
           "sl": 3.0, "tp": 1.0, "sizing": "flat", "base": 5.0, "trades": 1,
           "profit": 0.9, "last_ms": H0 + 69 * 3_600_000}
    got = msw.window_rows([dict(row), {**row, "reenter": 1}], 10, store=v2)
    assert all(r.get("restated") is True for r in got["rows"])
    assert seen == [False, True], "each row its own rule (the index stores 1 or NULL)"


def test_the_process_store_decides_for_run_pair(monkeypatch):
    monkeypatch.setattr(msw, "FINE_TF", "1m")
    assert msw.reenter_of() is True
    monkeypatch.setattr(msw, "FINE_TF", "")
    assert msw.reenter_of() is False


def test_the_row_index_keeps_the_rule_as_a_number():
    """1 or NULL, never the text '0' (which would read as true)."""
    from tradingagents import rows_index as ri

    assert "reenter" in ri.COLS and "reenter" in ri._INTEGER
    assert ("reenter", "INTEGER") in ri.LATE_COLUMNS
    assert ri._values({"id": "ABC", "reenter": True}, "X-1h")[ri.COLS.index("reenter")] is True
    assert ri._values({"id": "ABC"}, "X-1h")[ri.COLS.index("reenter")] is None


def _calls(fn_src: str, name: str) -> list:
    tree = ast.parse(textwrap.dedent(fn_src))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if (getattr(f, "attr", None) or getattr(f, "id", None)) == name:
                out.append(node)
    return out


def _kw(call, name: str) -> str:
    for k in call.keywords:
        if k.arg == name:
            return ast.unparse(k.value)
    return ""


def test_every_v2_measuring_call_passes_the_rule():
    """A KEYWORD the scripts pass must exist on the callee — the CI names
    guard cannot see keywords, and the shard swallows a TypeError into zero
    rows — every engine call on a v2 path must pass the rule, and both row
    builders must stamp it."""
    assert "reenter" in inspect.signature(at.backtest_strategy).parameters
    assert "reenter" in inspect.signature(fg.walk).parameters
    run_pair_src = inspect.getsource(msw.run_pair)
    run_pair = _calls(run_pair_src, "backtest_strategy")
    assert run_pair and all(_kw(c, "reenter") == "reenter_of()" for c in run_pair)
    assert '**({"reenter": True} if reenter_of() else {}),' in run_pair_src
    rebuild_src = inspect.getsource(r30.rebuild)
    rebuild = _calls(rebuild_src, "backtest_strategy")
    assert rebuild and all(_kw(c, "reenter") == "_re" for c in rebuild)
    assert '_re = bool(row.get("reenter"))' in rebuild_src
    for fn in (msw.trades_for, msw.window_rows):
        calls = _calls(inspect.getsource(fn), "backtest_strategy")
        assert calls and all(_kw(c, "reenter") for c in calls), fn.__name__
    shard = (ROOT / ".github/scripts/sweep_shard.py").read_text(encoding="utf-8")
    v2_calls = [c for c in _calls(shard, "backtest_strategy") if _kw(c, "fine") == "fine"]
    assert v2_calls and all(_kw(c, "reenter") == "br.reenter_for(RES)" for c in v2_calls)
    assert '**({"reenter": True} if br.reenter_for(RES) else {}),' in shard
    replay = (ROOT / ".github/scripts/replay_shard.py").read_text(encoding="utf-8")
    walks = _calls(replay, "walk")
    assert walks and all(_kw(c, "reenter") == "br.reenter_for('1m')" for c in walks)


def test_the_demo_figure_is_walked_under_its_rows_rule(home, monkeypatch):  # noqa: F811
    """The DEMO 30-day figure the watcher switches rows off by rebuilds the
    row's backtest: under the rule that row was measured with, stamped on the
    record. A re-measure moves the pair's watermark, so the figure follows."""
    import numpy as np

    from tradingagents.dataflows import gate_futures as gf

    monkeypatch.setenv("TA_VENUE", "gate")
    n, bar = 400, 900
    t0 = int(NOW) - n * bar
    df = pd.DataFrame({"Date": pd.to_datetime([t0 + bar * k for k in range(n)], unit="s"),
                       "Open": [100.0] * n, "High": [100.5] * n, "Low": [99.5] * n,
                       "Close": [100.0] * n, "Volume": [1.0] * n})
    wm = (t0 + bar * (n - 1)) * 1000
    ident = {"key": "prank_15m_sl15tp15", "tf": "15m", "sym": "FASTSTOCK_USDT",
             "tp": 1.5, "sl": 1.2, "res": "1m", "coin": "FASTSTOCK", "store": None}
    monkeypatch.setattr(r30, "_identity", lambda settings, slot: ident)
    monkeypatch.setattr(gf, "klines", lambda *a, **k: df)
    monkeypatch.setattr(gf, "funding_history", lambda *a, **k: [])
    monkeypatch.setattr(gf, "liquidation_move_pct", lambda *a, **k: 4.5)
    monkeypatch.setattr(br, "fine_bars", lambda *a, **k: (np.zeros(0, "int64"),
                                                          np.zeros(0), np.zeros(0), 0))
    monkeypatch.setattr(at, "_dirs_for_backtest", lambda *a, **k: [0] * n)
    seen = _spy(monkeypatch)
    for stamp, want in (({}, False), ({"reenter": True}, True)):
        row = {"trades": 0, "wins": 0, "profit": 0.0, "bars": 300, "fee": 0.00075, **stamp}
        monkeypatch.setattr(r30, "_stored", lambda i, row=row: (row, wm))
        seen.clear()
        rec = r30.rebuild(SLOT, {})
        assert seen == [want] and rec["reenter"] is want


def test_measured_then_updated_equals_one_walk_under_the_rule():
    """Review, Oct 13, 2026 (NEVER HAPPENED YET — MEXC only: on Gate a v2
    pair is measured in full): an UPDATE continues a saved position from the
    first new candle, so the signal of the last measured candle — free under
    this rule when the last trade closed in it — was lost. Measure the JASMY
    shape's candles 0-2, then update: the same two trades as one walk."""
    df, dirs = _jasmy()
    key = "mom6_reenter_seam"
    at.STRATEGY_SPECS[key] = {"interval": "Min30", "bar_seconds": 1800,
                              "tp": 0.02, "sl": 0.01, "threshold": 0.003}
    try:
        kw = {"fee": 0.0004, "sizing": "flat", "tp": 0.02, "sl": 0.01, "liq_move_pct": 4.5,
              "funding": [], "keep_log": False, "reenter": True}
        whole = at.backtest_strategy(key, df, 5.0, dirs=dirs, **kw)
        first = at.backtest_strategy(key, df.iloc[:3].reset_index(drop=True), 5.0,
                                     dirs=dirs[:3], resume={}, **kw)
        prev = first["state"]
        start = msw.resume_start(3, prev, reenter=True)
        assert start == 2, "nothing carried open: the boundary candle is read again"
        upd = at.backtest_strategy(key, df, 5.0, dirs=dirs, resume=prev, start_at=start, **kw)
        lost = at.backtest_strategy(key, df, 5.0, dirs=dirs, resume=prev, start_at=3, **kw)
    finally:
        at.STRATEGY_SPECS.pop(key, None)
    # one walk: the SL on candle 2, then candle 2's own signal, still open at
    # the end (an update CARRIES an open trade where one walk counts it)
    assert whole["trades"] == 2
    assert upd["trades"] == 1 and (upd["state"].get("open") or {}).get("entry_ms") \
        == int(df["Date"].iloc[3].value // 1_000_000), upd["state"].get("open")
    assert not lost["state"].get("open"), "from the first new candle the trade is lost"
    # the old rule keeps the old start; an open trade is carried, never re-read
    assert msw.resume_start(3, prev, reenter=False) == 3
    assert msw.resume_start(3, {**prev, "open": {"side": 1}}, reenter=True) == 3
    assert msw.resume_start(0, {}, reenter=True) == 0


def test_a_switched_off_rows_figure_is_rebuilt_when_its_row_is(home, monkeypatch):  # noqa: F811
    """Review, Oct 13, 2026: the Forecast reality check (took / gap) is read
    off the 30-day figures of PAST switch-on stretches — 19 records, every
    one of a slot no room runs any more, none ever rebuilt (refresh walked
    deployed slots only, and their `strategy_res` was gone). So their old rule
    and their old numbers stayed for good. A switched-off slot's figure is
    rebuilt too, from the record's own store, when its row is re-measured."""
    from tradingagents import venue

    slot = "cx_fast_30m_sl1tp12|IOTX_USDT"
    monkeypatch.setitem(at.STRATEGY_SPECS, "cx_fast_30m_sl1tp12",
                        {"interval": "Min30", "bar_seconds": 1800, "tp": 0.012, "sl": 0.01})
    path = r30._cache_path(slot)
    path.parent.mkdir(parents=True, exist_ok=True)
    since = 1_791_619_184.0
    monkeypatch.setattr(venue, "since", lambda: since)
    monkeypatch.setenv("TA_VENUE", "gate")
    path.write_text(json.dumps({"slot": slot, "wm": 111, "at": since + 3600}), encoding="utf-8")
    asked, wm = [], {"now": 222}
    monkeypatch.setattr(r30, "_watermark", lambda ident: wm["now"])
    monkeypatch.setattr(r30, "_file_stamp", lambda ident: (7, 70))

    def rebuild(s, settings, **k):
        asked.append((s, (settings.get("strategy_res") or {}).get(s)))
        return {"error": "no stored backtest row for it"} if wm.get("fail") else {}

    monkeypatch.setattr(r30, "rebuild", rebuild)
    r30._ORPHANS_FAILED.clear()
    r30.refresh({"strategy_coins": {}}, pause=0)
    assert asked == [(slot, "1m")], "written on Gate after the move: a Backtest v2 row"
    asked.clear()
    path.write_text(json.dumps({"slot": slot, "wm": 222, "res": "1m", "file": [7, 70]}),
                    encoding="utf-8")
    r30.refresh({"strategy_coins": {}}, pause=0)
    assert asked == [], "its row has not moved since: kept"
    # a rebuild that fails is not retried every pass until its row moves again
    wm.update(now=333, fail=True)
    r30.refresh({"strategy_coins": {}}, pause=0)
    r30.refresh({"strategy_coins": {}}, pause=0)
    assert asked == [(slot, "1m")]


def test_the_room_replays_cache_is_signed_by_the_code_it_loaded(monkeypatch):
    """Second review, Oct 14, 2026 (NEVER HAPPENED YET): `_code_sig` stamped
    the engine files as they stood when room_replay first ran — which, imported
    lazily, is hours after the API loaded the engine. A process started on
    the old code could then file old-rule trade lists under the new code's
    label. The label is the files as they stood when the PACKAGE started,
    before any engine code loaded: never newer than the code that runs."""
    import tradingagents
    from tradingagents import room_replay as rr

    snap = tradingagents.ENGINE_FILES_AT_START
    assert {"auto_trader.py", "market_sweep.py", "backtest_report.py"} <= set(snap)
    monkeypatch.setattr(rr, "_CODE_SIG", [])
    first = rr._code_sig()
    # an engine file edited after the start does not change THIS process's label
    real = Path.stat

    def later(self, *a, **k):
        st = real(self, *a, **k)
        if self.name == "auto_trader.py":
            class _S:
                st_size = st.st_size + 1
                st_mtime_ns = st.st_mtime_ns + 1
            return _S()
        return st

    monkeypatch.setattr(Path, "stat", later)
    monkeypatch.setattr(rr, "_CODE_SIG", [])
    assert rr._code_sig() == first
    assert rr.RESULT_TAG == "r4"


def test_backtest_v2_is_never_measured_by_a_local_market_sweep(monkeypatch):
    """Review, Oct 13, 2026 (NEVER HAPPENED YET — no button starts it): a
    local `backtest_v2` job's report fills in the deployed rows (rule 21)
    with the v1 engine — old rule, bar exits, no `res` — and writes them into
    the v2 store. Backtest v2 measures on GitHub (Sep 21, 2026): the local
    job is refused like the v1 market sweep."""
    from tradingagents import capacity as cap, db_jobs as dj

    monkeypatch.setattr(cap, "LOCAL_SWEEPS", False)
    assert "backtest_v2" in dj.LOCAL_SWEEP_KINDS
    with pytest.raises(dj.LocalSweepsOff):
        dj.start("backtest_v2", {"coins": ["A_USDT"], "tfs": ["15m"]})
    # and a crashed one is not restarted by the supervisor, spending no retry
    spent = []
    monkeypatch.setattr(dj, "died_unfinished", lambda kind: True)
    monkeypatch.setattr(dj, "_set_retries", lambda kind, n: spent.append(n))
    got = dj.resume_if_died("backtest_v2")
    assert got["resumed"] is False and "GitHub" in got["why"] and spent == []


def test_the_reality_check_compares_only_the_hours_both_sides_walked(home, monkeypatch):  # noqa: F811
    """Second review, Oct 14, 2026 (NEVER HAPPENED YET): a switched-off
    slot's figure rebuilt 30 days on walks a later window, so its old stretch
    kept practice's trades and lost every backtest trade — took read as None
    or inflated. #55D32617 ran PUMP 30m sr_bounce Oct 10, 2026 9:56am-11:58am
    (two practice stops, -0.59 and -0.57). Only the hours the record walked
    count, on both sides — read through the REAL `_rolling` from a real
    record file: the first fix wrote `start_ms` and `_rolling` dropped it,
    which a test that replaced `_rolling` could not see."""
    import os

    from tradingagents import forecast_v2 as f2

    a, b = 1_791_640_560.0, 1_791_647_880.0           # the switch-on stretch
    slot = "sr_bounce_30m_sl04tp05|PUMP_USDT"
    exits = [{"key": "sr_bounce_30m_sl04tp05", "symbol": "PUMP_USDT", "opened_at": a + 240,
              "ts": a + 1_200, "pnl": -0.59},
             {"key": "sr_bounce_30m_sl04tp05", "symbol": "PUMP_USDT", "opened_at": a + 3_840,
              "ts": a + 4_800, "pnl": -0.57}]
    room = {"id": "55D32617", "name": "#55D32617", "cap": 4, "exits": exits,
            "intervals": {slot: [(a, b)]}}
    path = r30._cache_path(slot)
    path.parent.mkdir(parents=True, exist_ok=True)

    def put(rec):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"slot": slot, **rec}), encoding="utf-8")
        os.replace(tmp, path)
        f2._ROLL.clear()
        f2._ROLL_DIR["stamp"] = None

    covering = {"end_ms": (b + 86_400) * 1000, "start_ms": (a - 86_400) * 1000,
                "trades": [[(a + 240) * 1000, (a + 1_200) * 1000, -0.6],
                           [(a + 3_840) * 1000, (a + 4_800) * 1000, -0.6]]}
    put(covering)
    assert f2._rolling(slot)["start_ms"] == int((a - 86_400) * 1000)
    got = f2.reality([room])["all"]
    assert (got["bt_trades"], got["pr_trades"], got["took"]) == (2, 2, 1.0)
    # rebuilt 33 days on: its window starts after the stretch — no hours in
    # common, so neither side counts, instead of 2 practice trades against 0
    put({"end_ms": (b + 33 * 86_400) * 1000, "start_ms": (b + 3 * 86_400) * 1000,
         "trades": []})
    got = f2.reality([room])["all"]
    assert (got["bt_trades"], got["pr_trades"]) == (0, 0)
    # and a window starting INSIDE the stretch cuts practice there too
    put({**covering, "start_ms": (a + 3_000) * 1000})
    got = f2.reality([room])["all"]
    assert (got["bt_trades"], got["pr_trades"]) == (1, 1)
    # a record from before (no start_ms) is read as it always was
    put({k: v for k, v in covering.items() if k != "start_ms"})
    got = f2.reality([room])["all"]
    assert (got["bt_trades"], got["pr_trades"]) == (2, 2)


def test_a_rewritten_result_file_rebuilds_the_figure_even_on_the_same_candle(home, monkeypatch):  # noqa: F811
    """Second review, Oct 14, 2026: UPDATE THIS BACKTEST inside the candle
    the daily run measured through re-stamps the row but leaves the
    watermark where it was (orb 4h MSTR, wm Oct 13, 2026 8:00am), so the
    DEMO figure kept its old rule up to a day. The figure is also rebuilt
    when the pair's result file changed."""
    ident = {"key": "k", "tf": "4h", "sym": "MSTR_USDT", "tp": 0.6, "sl": 0.5,
             "res": "1m", "coin": "MSTR", "store": None}
    rebuilt = []
    stamp = {"now": (1, 100)}
    monkeypatch.setattr(r30, "_identity", lambda settings, slot: ident)
    monkeypatch.setattr(r30, "_watermark", lambda i: 123)
    monkeypatch.setattr(r30, "_file_stamp", lambda i: stamp["now"])
    monkeypatch.setattr(r30, "_load", lambda slot: {"wm": 123, "file": [1, 100]})
    monkeypatch.setattr(r30, "rebuild", lambda slot, settings: rebuilt.append(slot) or {})
    settings = {"strategy_coins": {"k": ["MSTR_USDT"]}, "strategy_res": {"k|MSTR_USDT": "1m"}}
    r30.refresh(settings, pause=0)
    assert rebuilt == [], "the same watermark and the same file: kept"
    stamp["now"] = (2, 120)
    r30.refresh(settings, pause=0)
    assert rebuilt == ["k|MSTR_USDT"]


def test_the_switched_off_pass_is_bounded(home, monkeypatch):  # noqa: F811
    """Second review, Oct 14, 2026: nothing ever deletes a figure (the MEXC
    era left 6,579 in 11 days, 308.5 s to read cold) and each Gate rebuild
    takes ~14 s inside the back end, so rebuilding every switched-off figure
    whenever its row moved would have grown without end and held up the
    figures of the strategies switched on NOW. And each rebuild slides the
    figure's 30 days away from the stretch the reality check compares.

    So a switched-off figure is SETTLED — never rebuilt, its row's watermark
    never even read — once it reaches back to the last time its strategy was
    seen switched on AND it walks its store's rule of today; a pass rebuilds
    at most ORPHANS_PER_PASS; and a figure nobody wrote for ORPHAN_DAYS is not
    opened at all."""
    import os

    from tradingagents import venue

    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.setattr(venue, "since", lambda: 1_791_619_184.0)
    day = 86_400_000
    on_s = 1_791_700_000.0                       # last seen switched on (`at`)
    home_ = r30.home()
    home_.mkdir(parents=True, exist_ok=True)
    slots = []
    for k in range(5):
        key = f"cx_fast_30m_sl1tp1{k}"
        monkeypatch.setitem(at.STRATEGY_SPECS, key, {"interval": "Min30", "bar_seconds": 1800,
                                                     "tp": 0.012, "sl": 0.01})
        slot = f"{key}|IOTX_USDT"
        slots.append(slot)
        # built while switched on: it walks up to two hours BEFORE the
        # last time it was seen on, under today's rule
        r30._cache_path(slot).write_text(json.dumps(
            {"slot": slot, "res": "1m", "wm": 1, "at": on_s, "file": [7, 70], "reenter": True,
             "end_ms": int(on_s * 1000) - 7_200_000}), encoding="utf-8")
    asked, reads = [], []
    wm = {"now": int(on_s * 1000) + day}

    def watermark(ident):
        reads.append(ident["coin"])
        return wm["now"]

    def rebuild(slot, settings, **k):
        asked.append((slot, k.get("deployed_at")))
        # what the real one writes: its window now reaches past the switch-on
        r30._cache_path(slot).write_text(json.dumps(
            {"slot": slot, "res": "1m", "wm": wm["now"], "file": [7, 70], "reenter": True,
             "at": on_s + 2 * 86_400, "deployed_at": k.get("deployed_at"),
             "end_ms": wm["now"] + 1_800_000}), encoding="utf-8")
        return {}

    monkeypatch.setattr(r30, "_watermark", watermark)
    monkeypatch.setattr(r30, "_file_stamp", lambda ident: (7, 70))
    monkeypatch.setattr(r30, "rebuild", rebuild)
    monkeypatch.setattr(r30, "ORPHANS_PER_PASS", 3)
    r30._ORPHANS_FAILED.clear()
    r30.refresh({"strategy_coins": {}}, pause=0)
    assert len(asked) == 3, "at most ORPHANS_PER_PASS a pass"
    assert {d for _s, d in asked} == {on_s}, "a switched-off rebuild keeps its last switch-on"
    r30.refresh({"strategy_coins": {}}, pause=0)
    assert len(asked) == 5, "the rest on the next pass"
    # every one now reaches past its switch-on under today's rule: settled —
    # the row moving again neither rebuilds it nor reads its watermark
    asked.clear()
    reads.clear()
    wm["now"] += day
    r30.refresh({"strategy_coins": {}}, pause=0)
    assert asked == [] and reads == []
    # a settled figure on YESTERDAY's rule is still brought onto today's once
    # its row is re-measured
    rec = json.loads(r30._cache_path(slots[0]).read_text())
    r30._cache_path(slots[0]).write_text(json.dumps({**rec, "reenter": False}), encoding="utf-8")
    r30.refresh({"strategy_coins": {}}, pause=0)
    assert [s for s, _d in asked] == [slots[0]]
    # and a figure nobody wrote for ORPHAN_DAYS is not opened at all
    asked.clear()
    reads.clear()
    r30._cache_path(slots[1]).write_text(json.dumps({**rec, "slot": slots[1], "reenter": False}),
                                         encoding="utf-8")
    old = r30._cache_path(slots[1]).stat().st_mtime - (r30.ORPHAN_DAYS + 1) * 86_400
    os.utime(r30._cache_path(slots[1]), (old, old))
    r30.refresh({"strategy_coins": {}}, pause=0)
    assert asked == [] and reads == []


def test_a_deployed_rebuild_stamps_when_it_was_seen_switched_on(home, monkeypatch):  # noqa: F811
    """The settled check above reads `deployed_at`: the deployed pass stamps
    it NOW, a switched-off rebuild carries the one it is given."""
    import numpy as np

    from tradingagents.dataflows import gate_futures as gf

    monkeypatch.setenv("TA_VENUE", "gate")
    n, bar = 400, 900
    t0 = int(NOW) - n * bar
    df = pd.DataFrame({"Date": pd.to_datetime([t0 + bar * k for k in range(n)], unit="s"),
                       "Open": [100.0] * n, "High": [100.5] * n, "Low": [99.5] * n,
                       "Close": [100.0] * n, "Volume": [1.0] * n})
    ident = {"key": "prank_15m_sl15tp15", "tf": "15m", "sym": "FASTSTOCK_USDT",
             "tp": 1.5, "sl": 1.2, "res": "1m", "coin": "FASTSTOCK", "store": None}
    monkeypatch.setattr(r30, "_identity", lambda settings, slot: ident)
    monkeypatch.setattr(gf, "klines", lambda *a, **k: df)
    monkeypatch.setattr(gf, "funding_history", lambda *a, **k: [])
    monkeypatch.setattr(gf, "liquidation_move_pct", lambda *a, **k: 4.5)
    monkeypatch.setattr(br, "fine_bars", lambda *a, **k: (np.zeros(0, "int64"),
                                                          np.zeros(0), np.zeros(0), 0))
    monkeypatch.setattr(at, "_dirs_for_backtest", lambda *a, **k: [0] * n)
    row = {"trades": 0, "wins": 0, "profit": 0.0, "bars": 300, "fee": 0.00075, "reenter": True}
    monkeypatch.setattr(r30, "_stored", lambda i: (row, (t0 + bar * (n - 1)) * 1000))
    monkeypatch.setattr(r30.time, "time", lambda: 1_791_900_000.0)
    assert r30.rebuild(SLOT, {})["deployed_at"] == 1_791_900_000.0
    assert r30.rebuild(SLOT, {}, deployed_at=1_791_700_000.0)["deployed_at"] == 1_791_700_000.0
