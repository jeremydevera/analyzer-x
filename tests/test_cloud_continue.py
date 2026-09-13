"""A coin continued over its gap must equal the coin measured in one go.

Operator, 2026-09-09: *"if the last backtest was sep1 and i click update it
should run on github to update the gap which is sept 2 onwards"*. The gap
run starts from the saved position (`fast_grid.end_state`) and walks the new
bars with the engine (`resume_state.continue_combo`). These tests hold that
against the engine run over the whole history at once — trades, wins, profit,
the month map, drawdown, worst trade, funding, liquidations AND the losing
streak, which the engine's own resume forgets.
"""
import pytest

from tests.test_fast_grid import BARRIERS, _dirs, _frame, _funding
from tradingagents import auto_trader as at, fast_grid as fg, resume_state as rs

KEY = "mom6_continue_test"
LOOKBACK = 60


def _spec(tp, sl):
    at.STRATEGY_SPECS[KEY] = {"interval": "Min60", "bar_seconds": 3600,
                              "tp": tp, "sl": sl, "threshold": 0.003}


def _full(df, dirs, *, tp, sl, sizing, liq, fund):
    _spec(tp, sl)
    try:
        return at.backtest_strategy(KEY, df, 5.0, fee=0.0004, sizing=sizing,
                                    dirs=dirs, tp=tp, sl=sl, liq_move_pct=liq,
                                    funding=fund, keep_log=False, resume={})
    finally:
        at.STRATEGY_SPECS.pop(KEY, None)


def _state_through(df, dirs, k, *, tp, sl, sizing, liq, fund):
    """The saved position after measuring bars [0, k) the way the cloud does
    (fast walk + end_state)."""
    part = df.iloc[:k].reset_index(drop=True)
    ms = part["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    f_ms, f_rate = [], []
    for f in sorted(fund or [], key=lambda d: d["settle_ms"]):
        f_ms.append(int(f["settle_ms"]))
        f_rate.append(float(f["rate"]))
    f_cum = [0.0]
    for r in f_rate:
        f_cum.append(f_cum[-1] + r)
    mo = part["Date"].to_numpy().astype("datetime64[M]")
    labels, mo_idx, order = {}, [], []
    for v in mo:
        if v not in labels:
            labels[v] = len(order)
            order.append(str(v)[:7])
        mo_idx.append(labels[v])
    opens = [float(x) for x in part["Open"]]
    d = dirs[:k]
    six = fg.combo_six([i for i, v in enumerate(d) if v], d, opens,
                       [float(x) for x in part["High"]],
                       [float(x) for x in part["Low"]],
                       [float(x) for x in part["Close"]], tp=tp, sl=sl,
                       liq=None if liq is None else abs(liq) / 100.0,
                       half=k // 2, base=5.0, lev=at.LEVERAGE,
                       fee=0.0004 + 0.0003, ladder=at.ladder_margin,
                       mo_idx=mo_idx, mo_labels=order, f_ms=f_ms, f_cum=f_cum,
                       bar_ms=ms, with_trades=True)
    return fg.end_state(six["trades"], base=5.0, lev=at.LEVERAGE,
                        fee=0.0004 + 0.0003, sizing=sizing,
                        ladder=at.ladder_margin, mo_idx=mo_idx, mo_labels=order,
                        opens=opens, bar_ms=ms, last_ms=int(ms[-1]))


def _continued(df, dirs, k, *, tp, sl, sizing, liq, fund):
    prev = _state_through(df, dirs, k, tp=tp, sl=sl, sizing=sizing, liq=liq, fund=fund)
    frame, start_at, new_bars = rs.gap_frame(df, prev["last_ms"], LOOKBACK)
    assert new_bars == len(df) - k
    # the signal rules see the lookback too, exactly as the shard computes
    # dirs over the frame it hands the engine
    lo = k - start_at
    d = dirs[lo:]
    _spec(tp, sl)
    try:
        return rs.continue_combo(KEY, frame, 5.0, fee=0.0004, sizing=sizing,
                                 dirs=d, tp=tp, sl=sl, liq=liq, funding=fund,
                                 prev=prev, start_at=start_at)
    finally:
        at.STRATEGY_SPECS.pop(KEY, None)


KEYS = ("trades", "wins", "losses", "profit", "worst_trade", "max_dd",
        "monthly", "months_green", "months_total", "liqs", "funding_total",
        "worst_streak", "worst_streak_len")


@pytest.mark.parametrize("tp,sl", [(t, s) for s, t in BARRIERS])
@pytest.mark.parametrize("sizing", ["flat", "martingale"])
@pytest.mark.parametrize("k", [300, 601, 850])
def test_the_gap_continued_from_the_saved_position_equals_one_full_run(tp, sl, sizing, k):
    df = _frame()
    dirs = _dirs(len(df))
    fund = _funding(len(df))
    want = _full(df, dirs, tp=tp, sl=sl, sizing=sizing, liq=4.5, fund=fund)
    got, new_state = _continued(df, dirs, k, tp=tp, sl=sl, sizing=sizing,
                                liq=4.5, fund=fund)
    for key in KEYS:
        if key in ("worst_streak",):
            # the fold reads the engine's per-trade PnLs, which the log
            # rounds to the cent — a cent of tolerance per straddling trade
            assert got[key] == pytest.approx(want[key], abs=0.02), (key, got[key], want[key])
        else:
            assert got[key] == want[key], (key, got[key], want[key])
    # and the NEW saved position is what the full run would have saved
    assert new_state["trades"] == want["state"]["trades"]
    assert new_state["step"] == want["state"]["step"]
    assert new_state["last_ms"] == want["state"]["last_ms"]
    assert (new_state["open"] is None) == (want["state"]["open"] is None)
    for key in rs.STREAK_KEYS:
        assert key in new_state


def test_a_trade_open_at_the_boundary_is_carried_not_counted_twice():
    """The saved position hands the open trade over; the gap run keeps
    walking it from its ORIGINAL entry — same side, entry price, rung and
    funding window — and never counts it twice or drops it. Barriers of 500%
    keep it open through the whole frame, so the carried trade is what both
    runs end with."""
    df = _frame(seed=57, n=400)
    dirs = [0] * len(df)
    dirs[190] = 1                      # opens at 191; boundary at 200
    fund = _funding(len(df))
    for sizing in ("flat", "martingale"):
        want = _full(df, dirs, tp=5.0, sl=5.0, sizing=sizing, liq=None, fund=fund)
        prev = _state_through(df, dirs, 200, tp=5.0, sl=5.0, sizing=sizing,
                              liq=None, fund=fund)
        assert prev["open"] is not None and prev["trades"] == 0
        got, new_state = _continued(df, dirs, 200, tp=5.0, sl=5.0, sizing=sizing,
                                    liq=None, fund=fund)
        assert got["trades"] == want["trades"] == 0
        assert new_state["open"] is not None
        for k in ("side", "entry", "margin", "entry_ms"):
            assert new_state["open"][k] == want["state"]["open"][k], (sizing, k)
        # the carried entry is the ORIGINAL bar-191 entry, not the boundary
        assert new_state["open"]["entry"] == float(df["Open"].iloc[191])


def test_nothing_to_do_when_no_bar_is_newer():
    df = _frame(n=100)
    ms = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    frame, start_at, new_bars = rs.gap_frame(df, int(ms[-1]), LOOKBACK)
    assert frame is None and new_bars == 0


def test_pack_unpack_round_trips_and_is_small():
    states = {"__last_ms__": 1, "__signals__": ["mom6"],
              **{f"mom6|0.3|{i}|2|flat": {"trades": i, "monthly": {"2026-08": 1.5},
                                          "open": None, "step": 0}
                 for i in range(2000)}}
    blob = rs.pack(states)
    assert rs.unpack(blob) == states
    assert len(blob) < 40_000, len(blob)      # 2,000 combos in under 40 KB


def test_fold_streak_continues_a_run_across_the_boundary():
    prev = {"streak_sum": -3.0, "streak_len": 2, "worst_streak": -3.0,
            "worst_streak_len": 2}
    got = rs.fold_streak(prev, [-2.0, -1.0, 4.0, -0.5])
    assert got["worst_streak"] == -6.0 and got["worst_streak_len"] == 4
    assert got["streak_sum"] == -0.5 and got["streak_len"] == 1


# ------------------------------------------------ the SECOND continuation
# RCA-2026-09-09-R. `exit_at_last` is what the next continuation reads to
# place the boundary bar. fast_grid.end_state wrote it; continue_combo copied
# the engine's state, which has no such thing — so the first state a
# continuation ever saved (run 34360893326, Sep 09, 2026: 52,668
# combinations) carried none, and the run after it would have started one bar
# early on every combination whose last trade closed on that bar.
def _full_log(df, dirs, *, tp, sl, sizing, liq, fund):
    _spec(tp, sl)
    try:
        return at.backtest_strategy(KEY, df, 5.0, fee=0.0004, sizing=sizing,
                                    dirs=dirs, tp=tp, sl=sl, liq_move_pct=liq,
                                    funding=fund, keep_log=True, resume={})
    finally:
        at.STRATEGY_SPECS.pop(KEY, None)


def _continue_from(df, dirs, prev, upto, *, tp, sl, sizing, liq, fund):
    """Continue `prev` over df[:upto] — the shard's own steps: gap_frame, the
    rules computed over the frame it hands the engine, continue_combo."""
    part = df.iloc[:upto].reset_index(drop=True)
    frame, start_at, new_bars = rs.gap_frame(part, prev["last_ms"], LOOKBACK)
    first_new = len(part) - new_bars
    d = dirs[first_new - start_at:upto]
    _spec(tp, sl)
    try:
        return rs.continue_combo(KEY, frame, 5.0, fee=0.0004, sizing=sizing,
                                 dirs=d, tp=tp, sl=sl, liq=liq, funding=fund,
                                 prev=prev, start_at=start_at)
    finally:
        at.STRATEGY_SPECS.pop(KEY, None)


def test_the_continued_position_carries_the_boundary_flag():
    """Present on every continued state, and agreeing with the engine's own
    log of the same bars: did a trade close ON the frame's last bar."""
    df = _frame()
    dirs = _dirs(len(df))
    fund = _funding(len(df))
    last = len(df) - 1
    for sl, tp in BARRIERS:
        for sizing in ("flat", "martingale"):
            full = _full_log(df, dirs, tp=tp, sl=sl, sizing=sizing, liq=4.5, fund=fund)
            want = any(row["why"] != "END" and row["exit_bar"] == last
                       for row in full["log"])
            for k in (300, 601, 850):
                _got, new_state = _continued(df, dirs, k, tp=tp, sl=sl,
                                             sizing=sizing, liq=4.5, fund=fund)
                assert "exit_at_last" in new_state, (tp, sl, sizing, k)
                assert new_state["exit_at_last"] is want, (tp, sl, sizing, k)


def test_two_continuations_in_a_row_equal_one_full_run():
    """Full run → saved position → continued → continued AGAIN equals one full
    run, with the middle boundary placed ON a bar where a trade closed and a
    signal sits. The full run skips that signal (it searches from exit+1), so
    a continuation that has forgotten the flag takes a trade the full run
    never took — shown here by dropping the flag and watching it diverge."""
    df = _frame()
    dirs = _dirs(len(df))
    fund = _funding(len(df))
    k1, cases = 300, 0
    for sl, tp in BARRIERS:
        for sizing in ("flat", "martingale"):
            want = _full_log(df, dirs, tp=tp, sl=sl, sizing=sizing, liq=4.5, fund=fund)
            exits = {row["exit_bar"] for row in want["log"] if row["why"] != "END"}
            k2 = next((k for k in range(k1 + 40, len(df) - 40)
                       if (k - 1) in exits and dirs[k - 1] != 0), None)
            if k2 is None:
                continue
            cases += 1
            prev = _state_through(df, dirs, k1, tp=tp, sl=sl, sizing=sizing,
                                  liq=4.5, fund=fund)
            _r2, mid = _continue_from(df, dirs, prev, k2, tp=tp, sl=sl,
                                      sizing=sizing, liq=4.5, fund=fund)
            assert mid["exit_at_last"] is True, (tp, sl, sizing, k2)
            got, end = _continue_from(df, dirs, mid, len(df), tp=tp, sl=sl,
                                      sizing=sizing, liq=4.5, fund=fund)
            for key in KEYS:
                if key == "worst_streak":
                    assert got[key] == pytest.approx(want[key], abs=0.03), (
                        key, got[key], want[key], tp, sl, sizing, k2)
                else:
                    assert got[key] == want[key], (key, got[key], want[key],
                                                   tp, sl, sizing, k2)
            assert end["trades"] == want["state"]["trades"]
            assert (end["open"] is None) == (want["state"]["open"] is None)
            # the flag is load-bearing: without it, a phantom trade
            flagless = {k: v for k, v in mid.items() if k != "exit_at_last"}
            bad, bad_end = _continue_from(df, dirs, flagless, len(df), tp=tp,
                                          sl=sl, sizing=sizing, liq=4.5, fund=fund)
            assert ((bad["trades"], bad["profit"], bad_end["open"] is None)
                    != (want["trades"], want["profit"], want["state"]["open"] is None)), (
                tp, sl, sizing, k2, "dropping the flag changed nothing — the case is not exercised")
    assert cases >= 1, "the fixture never closed a trade on a signal bar"
