"""The learned formulas ("Sep 25 Strat") — one set per coin and timeframe.

Operator, Sep 25, 2026: *"create another set of formula for each coin and each
of their timeframe ... each coin should have different formula ... apply
different confluence ... tp is greater than sl"*, then *"research and loop on
whats the best confluence for each coin per timeframe"*, then *"create group
'Sep 25 Strat' when I filter thr group in backtest store so that I can filter
it"*.

What these hold: a learned formula reads only closed candles; the grid, the
trade log and the runner compute it the same way; the loop keeps only
COMBINATIONS with TP strictly above SL; two wordings of the same trades are
one formula; the GitHub measurement of a learned formula never writes the
market grid's markers; landing a run swaps only learned rows and never moves
a pair's watermark; and the group filters exactly the lx_ rows.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent


def _frame(n=900, tf="1h", seed=7, end=None):
    """A deterministic random walk with a real volume column, ending `end`."""
    rng = np.random.default_rng(seed)
    step = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}[tf]
    end = end or pd.Timestamp("2026-09-20 00:00")
    dates = pd.date_range(end=end, periods=n, freq=f"{step}s")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.004, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.004, n))
    v = rng.uniform(50, 150, n)
    return pd.DataFrame({"Date": dates, "Open": o, "High": h, "Low": lo,
                         "Close": c, "Volume": v})


def _arrays(df):
    ts = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    return ([float(x) for x in df["Open"]], [float(x) for x in df["High"]],
            [float(x) for x in df["Low"]], [float(x) for x in df["Close"]],
            [float(x) for x in df["Volume"]], [int(x) for x in ts])


EVERY_KIND = {
    "name": "lx_TEST_1h_1", "coin": "TEST", "tf": "1h", "join": "cascade",
    "legs": [
        {"trigger": "rsi14", "confirm": [
            {"k": "trend", "n": 50, "side": "against"},
            {"k": "htf", "n": 100, "side": "with"},
            {"k": "session", "h0": 6, "len": 12},
            {"k": "atr", "lo": 0.0, "hi": 1.0},
            {"k": "volx", "x": 0.5},
            {"k": "stretch", "x": 0.2},
            {"k": "agree", "sig": "bb20", "within": 3}]},
        {"trigger": "bb20", "confirm": [{"k": "veto", "sig": "rsi14"}]},
    ],
    "tp": 0.02, "sl": 0.01,
}


# ------------------------------------------------------------ the formulas
def test_a_learned_formula_never_reads_a_candle_that_has_not_closed():
    """Directions for the first k bars must not change when later bars
    exist — every kind of confirm, both joins."""
    from tradingagents import signals_learned as sl_

    df = _frame(700)
    o, h, lo, c, v, ts = _arrays(df)
    full = sl_.dirs_for(EVERY_KIND, o, h, lo, c, v, ts)
    assert any(full), "the fixture must actually signal somewhere"
    for k in (350, 480, 620):
        part = sl_.dirs_for(EVERY_KIND, o[:k], h[:k], lo[:k], c[:k], v[:k], ts[:k])
        assert part == full[:k], f"bar {k}: a direction moved when later bars arrived"


def test_the_grid_the_trade_log_and_the_runner_compute_it_the_same_way():
    import tradingagents.auto_trader as at
    from tradingagents import signals_learned as sl_

    sl_.register({EVERY_KIND["name"]: EVERY_KIND})
    df = _frame(600)
    o, h, lo, c, v, ts = _arrays(df)
    want = sl_.dirs_for(EVERY_KIND, o, h, lo, c, v, ts)
    # the grid calls "<name>_gh_<tf>", the trade log the name itself
    for key in (EVERY_KIND["name"], EVERY_KIND["name"] + "_gh_1h"):
        got = at._dirs_for_backtest(key, h, lo, c, opens=o, volume=v, ts=ts)
        assert got == want, key
    assert at.signal_for(EVERY_KIND["name"], h, lo, c, opens=o, volume=v,
                         ts=ts) == want[-1]
    # an unknown learned name abstains — never falls through to a lookalike
    assert set(at._dirs_for_backtest("lx_NOPE_1h_9", h, lo, c, opens=o,
                                     volume=v, ts=ts)) == {0}
    assert at.signal_for("lx_NOPE_1h_9", h, lo, c, opens=o, volume=v, ts=ts) == 0


def test_the_joins_mean_what_the_operator_said():
    from tradingagents import signals_learned as sl_

    df = _frame(40)
    feats = sl_.Features(*[np.asarray(x) for x in _arrays(df)[:5]],
                         np.asarray(_arrays(df)[5]), "1h")
    a = np.array([1, 0, -1, 0, 1] + [0] * 35, dtype=np.int8)
    b = np.array([0, 1, 1, 0, -1] + [0] * 35, dtype=np.int8)
    c = np.array([0, 1, -1, -1, -1] + [0] * 35, dtype=np.int8)
    dirs = {"a": a, "b": b, "c": c}
    casc = sl_.compose({"join": "cascade", "legs": [{"trigger": "a"}, {"trigger": "b"}]},
                       dirs, feats)
    assert list(casc[:5]) == [1, 1, -1, 0, 1], "the FIRST leg that fires wins"
    vote = sl_.compose({"join": "vote", "vote": {"sigs": ["a", "b", "c"], "need": 2}},
                       dirs, feats)
    assert list(vote[:5]) == [0, 1, -1, 0, -1], "two agree on one side; a tie is nothing"
    veto = sl_.compose({"join": "and", "legs": [
        {"trigger": "a", "confirm": [{"k": "veto", "sig": "b"}]}]}, dirs, feats)
    # bar 2: a short, b long -> vetoed; bar 4: a long, b short -> vetoed
    assert list(veto[:5]) == [1, 0, 0, 0, 0], "a opens unless b disagrees"


def test_every_lookback_stays_inside_what_an_update_hands_a_rule():
    """market_sweep.CONTEXT_BARS (300) is the history an incremental pass
    gives a rule; every setting the search may try must read <= 200 bars."""
    from tradingagents import market_sweep as msw, signals_learned as sl_

    assert sl_.MAX_LOOKBACK <= 200 < msw.CONTEXT_BARS
    assert max(sl_.FILTERS["trend"]["n"]) <= sl_.MAX_LOOKBACK
    assert max(sl_.FILTERS["htf"]["n"]) <= sl_.MAX_LOOKBACK


# --------------------------------------------------------------- the loop
def test_only_tp_strictly_above_sl_inside_the_liquidation_limit():
    from tradingagents import formula_learner as fl

    pairs = fl.barrier_pairs("15m", 0.0004, 0.0002, 4.5)
    assert pairs and all(t > s for s, t in pairs)
    assert all(s * 100 < 0.8 * 4.5 for s, _t in pairs)


def test_break_even_counts_the_cost_on_both_sides():
    from tradingagents import formula_learner as fl

    # equal 1.2%/1.2% barriers at a 0.22% round trip: a win keeps 0.98%, a
    # loss costs 1.42%, so break-even is 1.42 / 2.40 = 59.2% — never 50%
    assert fl.breakeven_winrate(0.012, 0.012, 0.0022) == pytest.approx(59.17, abs=0.01)
    assert fl.breakeven_winrate(0.02, 0.01, 0.0) == pytest.approx(33.33, abs=0.01)
    assert fl.breakeven_winrate(0.02, 0.01, 0.004) > 33.34


def _learner(n=2600, tf="1h", signals=("rsi14", "bb20", "keltner")):
    from tradingagents import formula_learner as fl

    df = _frame(n, tf)
    frame = fl.Frame(coin="TEST", tf=tf, df=df, fee=0.0004, slip=0.0001,
                     liq=4.5, funding=[], fine=None)
    now = int(df["Date"].iloc[-1].timestamp() * 1000) + 3_600_000
    return fl.Learner(frame, now_ms=now, signals=list(signals))


def test_two_wordings_of_the_same_trades_are_one_formula():
    """willr14 and stoch14 are the same line upside down, so "willr14 +
    stoch14 agrees" was kept beside "stoch14 + willr14 agrees" on BTC 1h —
    one formula twice. Candidates are compared by the trades they signal."""
    lr = _learner()
    a = {"join": "and", "legs": [{"trigger": "rsi14", "confirm": []}]}
    b = {"join": "and", "legs": [{"trigger": "rsi14", "confirm": [
        {"k": "agree", "sig": "rsi14", "within": 1}]}]}
    assert lr.behaviour(a) == lr.behaviour(b)
    lr.learn_score(a)
    before = lr.tried
    lr.learn_score(b)
    assert lr.tried == before, "the same trades were scored twice"


def test_a_single_signal_is_never_a_learned_formula():
    """A signal alone is one of the existing 130 — the loop starts from them
    and may never hand one back as new."""
    from tradingagents import formula_learner as fl

    lr = _learner()
    single = {"join": "and", "legs": [{"trigger": "rsi14", "confirm": []}]}
    combo = {"join": "cascade", "legs": [{"trigger": "rsi14"}, {"trigger": "bb20"}]}
    assert not fl.is_confluence(single) and fl.is_confluence(combo)
    g = {"profit": 50.0, "trades": 40, "wins": 30, "losses": 10, "streak": -1.0,
         "streak_len": 1}
    sc = {"pnl": 10.0, "trades": 40, "wins": 30, "sl": 0.01, "tp": 0.02}
    lr._nested_ok = lambda *a, **k: (True, {})
    kept = lr._keep({"s": (99.0, single, sc, g), "c": (10.0, combo, sc, g)})
    assert [fl.is_confluence(k) for k in kept] == [True]
    assert all(k["tp"] > k["sl"] for k in kept)
    assert kept[0]["name"] == "lx_TEST_1h_1"


def test_too_little_history_says_so_instead_of_guessing():
    """KKRSTOCK on this PC had 1 day before its last 30 and still "learned"
    three formulas; now it is a named refusal."""
    rep = _learner(n=700).run()
    assert rep["formulas"] == []
    assert "not enough history" in rep["why"]


def test_the_loop_runs_its_rounds_and_reports_them():
    rep = _learner().run()
    assert rep["rounds"] >= 2 and rep["tried"] > 3
    assert all(r["round"] == i + 1 for i, r in enumerate(rep["round_log"]))
    for f in rep["formulas"]:
        assert f["tp"] > f["sl"] and f["name"].startswith("lx_TEST_1h_")
        u = f["learned"]["unseen"]
        assert u["trades"] >= rep["min_unseen_trades"]
        assert u["winrate"] > f["learned"]["breakeven_winrate"]


# --------------------------------------------------- the GitHub measurement
def _shard(monkeypatch):
    import importlib.util
    import sys

    monkeypatch.setenv("RES", "1m")
    monkeypatch.setenv("MODE", "full")
    spec = importlib.util.spec_from_file_location(
        "sweep_shard_learned", REPO / ".github/scripts/sweep_shard.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "sweep_shard_learned", mod)
    spec.loader.exec_module(mod)
    return mod


def test_a_learned_measurement_writes_rows_only_and_only_tp_above_sl(monkeypatch, tmp_path):
    import io

    from tradingagents import signals_learned as sl_

    ss = _shard(monkeypatch)
    now = pd.Timestamp.now("UTC").tz_localize(None).floor("h")
    df = _frame(1100, "1h", end=now)
    sl_.register({EVERY_KIND["name"]: EVERY_KIND})

    def no_venue(*a, **k):
        raise AssertionError("a learned measurement must use the learner's own data")

    for name in ("taker_fee",):
        monkeypatch.setattr(ss.at, name, no_venue)
    for name in ("liquidation_move_pct", "funding_history", "book_cost", "klines"):
        monkeypatch.setattr(ss.fx, name, no_venue)
    wrote = []
    monkeypatch.setattr(ss, "write_state", lambda *a, **k: wrote.append(1))
    monkeypatch.setattr(ss, "post_pair", lambda *a, **k: wrote.append(2))
    out = io.StringIO()
    ss.run_pair("TEST_USDT", "1h", out, signals=[EVERY_KIND["name"]],
                learned={"fee": 0.0004, "liq": 4.5, "fund": [], "slip": 0.0001,
                         "df": df, "fine": None})
    rows = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    assert rows, "the fixture should trade"
    assert not [r for r in rows if r.get("pair_done")], "no pair-done marker"
    assert wrote == [], "no saved position, no live post"
    assert all(r["tp"] > r["sl"] for r in rows)
    assert all(r["sl"] < 0.8 * 4.5 for r in rows)
    assert {r["signal"] for r in rows} == {EVERY_KIND["name"]}
    assert {r.get("res") for r in rows} == {"1m"}


def test_the_market_grid_measurement_is_unchanged_by_default():
    """signals=None, learned=None is the market grid: every registry signal,
    the pair-done marker and the saved position, as before."""
    src = (REPO / ".github/scripts/sweep_shard.py").read_text(encoding="utf-8")
    assert "sigs = list(signals) if signals is not None else br.SIGNALS" in src
    assert 'PRIOR.get(f"{coin}-{tf}") if learned is None else None' in src
    assert src.count("if learned is not None") >= 2


def test_the_machines_charge_a_coins_usual_cost_never_a_closed_market_spike(monkeypatch):
    import importlib.util
    import sys

    monkeypatch.setenv("RES", "1m")
    spec = importlib.util.spec_from_file_location(
        "learn_shard_t", REPO / ".github/scripts/learn_shard.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "learn_shard_t", mod)
    spec.loader.exec_module(mod)
    # KKRSTOCK Sep 25, 2026: rows charged 0.1803% round trip, book 1.22% a side
    slip, readings = mod.charged(0.0008, 0.012193859525671202, 0.001803)
    assert slip == pytest.approx(0.001803 / 2 - 0.0008)
    assert len(readings) == 2


def test_the_machines_claim_one_coin_at_a_time():
    src = (REPO / ".github/scripts/learn_shard.py").read_text(encoding="utf-8")
    assert "stream = ss.coin_stream(coins, t0)" in src
    assert "list(ss.coin_stream" not in src.replace("`list(coin_stream(...))`", "")


def test_the_workflow_hands_over_what_a_stopped_machine_finished():
    wf = (REPO / ".github/workflows/learn.yml").read_text(encoding="utf-8")
    assert "python .github/scripts/learn_shard.py" in wf
    assert wf.count("if: always()") >= 2
    assert "learn-rows-" in wf and "learn-formulas-" in wf


# ------------------------------------------------------------- the group
def test_the_group_is_exactly_the_learned_rows_and_classic_never_holds_them():
    import sqlite3

    from tradingagents import backtest_report as br, rows_index as ri

    names = list(br.SIGNALS) + ["lx_BTC_1h_1", "lx_KKRSTOCK_15m_2"]
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE rows (signal TEXT)")
    con.executemany("INSERT INTO rows VALUES (?)", [(s,) for s in names])
    for group, terms in ri.GROUP_TERMS.items():
        sql = {r[0] for r in con.execute(f"SELECT signal FROM rows WHERE {terms}")}
        assert sql == {s for s in names if ri.in_group(s, group)}, group
    assert {s for s in names if ri.in_group(s, "sep25")} == {
        "lx_BTC_1h_1", "lx_KKRSTOCK_15m_2"}
    assert not [s for s in names if ri.in_group(s, "classic") and s.startswith("lx_")]
    assert not [s for s in names if ri.in_group(s, "preset") and s.startswith("lx_")]
    assert ri.GROUPS["sep25"]["label"] == "Sep 25 Strat"
    assert ri.group_index("sep25", "profit") == "rows_lx_profit"


def test_the_screen_offers_the_group_by_its_name():
    src = (REPO / "webapp/src/components/backtest/StrategiesPanel.tsx").read_text(
        encoding="utf-8")
    assert 'sep25: "Sep 25 Strat"' in src
    assert '<option value="sep25">{GROUP_LABEL.sep25}</option>' in src
    api = (REPO / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    assert api.count('"preset" | "classic" | "sep25"') == 2


# ------------------------------------------------------------ the collect
@pytest.fixture
def v2store(tmp_path, monkeypatch):
    from tradingagents import (
        learn_collect as lc,
        market_sweep as msw,
        rows_index as ri,
        signals_learned as sl_,
    )

    monkeypatch.setattr(msw, "FINE_TF", "1m")
    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    monkeypatch.setattr(sl_, "LEARNED_FILE", tmp_path / "sep25.json")
    monkeypatch.setattr(lc, "REPORT_FILE", tmp_path / "sep25_report.json")
    db = tmp_path / "rows.db"
    monkeypatch.setattr(ri, "DB_PATH", db)
    ri._ready.discard(str(db))
    ri.forget_indexes()
    ri.ensure()
    sl_.reload()
    yield msw, ri, sl_, lc
    sl_.reload()


def _row(coin, tf, signal, sl=1.0, tp=2.0):
    return {"coin": coin, "tf": tf, "signal": signal, "th": 0.0, "sl": sl, "tp": tp,
            "sizing": "flat", "trades": 12, "wins": 8, "losses": 4, "winrate": 66.67,
            "profit": 5.0, "monthly": {}, "res": "1m", "last_ms": 1}


def test_landing_a_run_swaps_only_the_learned_rows(v2store):
    msw, ri, sl_, lc = v2store
    grid = [_row("BTC", "1h", "keltner"), _row("BTC", "1h", "rsi14", 1.2, 1.0)]
    old = [_row("BTC", "1h", "lx_BTC_1h_1"), _row("BTC", "1h", "lx_BTC_1h_2")]
    msw.save_pair_rows("BTC", "1h", grid + old)
    msw.save_states("BTC", "1h", {"__cloud__": True, "__last_ms__": 123})
    sl_.LEARNED_FILE.write_text(json.dumps({"formulas": {
        "lx_BTC_1h_1": {"coin": "BTC", "tf": "1h"},
        "lx_BTC_1h_2": {"coin": "BTC", "tf": "1h"},
        "lx_ETH_4h_1": {"coin": "ETH", "tf": "4h"}}}), encoding="utf-8")
    new_f = {"lx_BTC_1h_1": {"coin": "BTC", "tf": "1h", "join": "and",
                             "legs": [{"trigger": "rsi14", "confirm": [{"k": "volx", "x": 1.5}]}]}}
    report = [{"coin": "BTC", "tf": "1h", "kept": ["lx_BTC_1h_1"]},
              {"coin": "SOL", "tf": "15m", "kept": [], "why": "nothing passed"},
              {"coin": "ETH", "tf": "4h", "error": "HTTPError: 502"}]
    got = lc.land(new_f, report, {("BTC", "1h"): [_row("BTC", "1h", "lx_BTC_1h_1", 1.0, 3.0)]})
    rows = msw.pair_rows("BTC", "1h")
    assert sorted(r["signal"] for r in rows) == ["keltner", "lx_BTC_1h_1", "rsi14"]
    assert [r["tp"] for r in rows if r["signal"] == "lx_BTC_1h_1"] == [3.0]
    # the watermark is the market grid's: untouched
    assert msw.load_states("BTC", "1h").get("__last_ms__") == 123
    f = json.loads(sl_.LEARNED_FILE.read_text(encoding="utf-8"))["formulas"]
    # BTC 1h replaced (the old _2 is gone); ETH 4h raised, so it keeps its own
    assert set(f) == {"lx_BTC_1h_1", "lx_ETH_4h_1"}
    assert f["lx_BTC_1h_1"]["legs"][0]["confirm"] == [{"k": "volx", "x": 1.5}]
    # SOL 15m was attempted and kept nothing, and had nothing: no file written
    assert not (msw.ROWDIR / "SOL-15m.json").exists()
    assert got["rows"] == 1


def test_landing_refuses_rows_it_cannot_account_for(v2store):
    _msw, _ri, _sl, lc = v2store
    with pytest.raises(ValueError, match="does not account"):
        lc.land({}, [], {("BTC", "1h"): [_row("BTC", "1h", "lx_BTC_1h_1")]})
    with pytest.raises(ValueError, match="res="):
        lc.land({}, [{"coin": "BTC", "tf": "1h"}],
                {("BTC", "1h"): [{**_row("BTC", "1h", "lx_BTC_1h_1"), "res": ""}]})


def test_landing_is_refused_outside_backtest_v2(v2store, monkeypatch):
    msw, _ri, _sl, lc = v2store
    monkeypatch.setattr(msw, "FINE_TF", "")
    with pytest.raises(RuntimeError, match="Backtest v2"):
        lc.land({}, [], {})


def test_the_update_button_keeps_the_same_rule_for_a_learned_row():
    src = (REPO / "tradingagents/market_sweep.py").read_text(encoding="utf-8")
    assert 'if str(sig).startswith("lx_") and (' in src
    assert "tp <= sl or (liq is not None" in src


def test_a_run_rewrites_a_pair_under_one_hold_of_its_lock(v2store, monkeypatch):
    msw, *_ = v2store
    held = []
    real = msw._pair_lock

    from contextlib import contextmanager

    @contextmanager
    def spy(coin, tf):
        held.append((coin, tf))
        with real(coin, tf):
            yield

    monkeypatch.setattr(msw, "_pair_lock", spy)
    msw.save_pair_rows("BTC", "1h", [_row("BTC", "1h", "keltner")])
    held.clear()
    msw.rewrite_pair_rows("BTC", "1h", lambda rows: rows + [_row("BTC", "1h", "lx_BTC_1h_1")])
    assert held == [("BTC", "1h")]
    assert len(msw.pair_rows("BTC", "1h")) == 2


def test_it_is_fast_enough_to_learn_the_market(monkeypatch):
    """Guard on the loop's own cost: a 2,600-bar hour frame with three
    ingredients finishes well inside a GitHub machine's budget."""
    t0 = time.time()
    _learner().run()
    assert time.time() - t0 < 60


def test_a_running_process_sees_formulas_collected_after_it_started(tmp_path, monkeypatch):
    """The runner is a long process; a formula file written after it loaded
    must be read, or a deployed lx_ strategy abstains until a restart."""
    import os

    from tradingagents import signals_learned as sl_

    f = tmp_path / "sep25.json"
    monkeypatch.setattr(sl_, "LEARNED_FILE", f)
    sl_.reload()
    assert sl_.spec_for("lx_BTC_1h_1") is None
    f.write_text(json.dumps({"formulas": {"lx_BTC_1h_1": {"coin": "BTC", "tf": "1h"}}}),
                 encoding="utf-8")
    os.utime(f, ns=(time.time_ns(), time.time_ns() + 10**9))
    assert sl_.spec_for("lx_BTC_1h_1") == {"coin": "BTC", "tf": "1h"}
    sl_.reload()


def test_two_formulas_with_the_same_stored_trades_are_one(monkeypatch):
    """GitHub run 36140580272 kept lx_ETH_30m_1 and _2 — different in the learn
    period, identical in the stored window (28 trades, 71.43%, +$43.41)."""
    lr = _learner()
    a = {"join": "cascade", "legs": [{"trigger": "rsi14"}, {"trigger": "bb20"}]}
    b = {"join": "cascade", "legs": [{"trigger": "bb20"}, {"trigger": "rsi14"}]}
    g = {"profit": 43.41, "trades": 28, "wins": 20, "losses": 8, "streak": -1.0,
         "streak_len": 1}
    sc = {"pnl": 10.0, "trades": 40, "wins": 30, "sl": 0.015, "tp": 0.03}
    lr._nested_ok = lambda *x, **k: (True, {})
    kept = lr._keep({"a": (43.41, a, sc, g), "b": (43.41, b, sc, dict(g))})
    assert len(kept) == 1


def test_a_learned_key_reads_as_its_own_formula_everywhere(monkeypatch):
    """local_history._sig_of is the one parser of a key's signal; an lx_ name
    has three underscores and is not in backtest_report.SIGNALS, so the old
    rule read it as `lx` and would have hashed an id no store holds. The
    runner dispatches the same name (signal_for → signals_learned)."""
    import tradingagents.auto_trader as at
    from tradingagents import signals_learned as sl_
    from tradingagents.local_history import _sig_of

    spec = {**EVERY_KIND, "name": "lx_TEST_1h_1"}
    sl_.register({"lx_TEST_1h_1": spec})
    for key in ("lx_TEST_1h_1", "lx_TEST_1h_1_1h_sl10tp20", "lx_TEST_1h_1_gh_1h"):
        assert _sig_of(key) == "lx_TEST_1h_1", key
        assert sl_.spec_for(key)["name"] == "lx_TEST_1h_1"
    # a name the file does not hold yet still reads by its fixed shape
    assert _sig_of("lx_NEWCOIN_4h_2_4h_sl10tp30") == "lx_NEWCOIN_4h_2"
    # and the runner fires exactly that formula for the key
    fired = []
    monkeypatch.setattr(sl_, "dirs_for", lambda s, *a, **k: fired.append(s["name"]) or [0])
    bars = [1.0] * 50
    at.signal_for("lx_TEST_1h_1_1h_sl10tp20", bars, bars, bars, bars, bars, list(range(50)))
    assert fired == [_sig_of("lx_TEST_1h_1_1h_sl10tp20")]
