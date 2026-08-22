"""One position, several exits — what two strategies on one coin become.

MEXC nets same-side positions into a single record, so "two orders on PI" is
one position with two brackets. `stoporder/place` was probed on 2026-08-19 and
accepts volType=1 with a specified vol, and separate takeProfitVol/stopLossVol,
so the venue supports it; these tests pin the arithmetic.
"""
import pandas as pd
import pytest

import tradingagents.auto_trader as at

KEY = "_sliced_test"


@pytest.fixture(autouse=True)
def _spec():
    at.STRATEGY_SPECS[KEY] = {"interval": "Min60", "bar_seconds": 3600,
                              "tp": 0.02, "sl": 0.01}
    yield
    at.STRATEGY_SPECS.pop(KEY, None)


def _frame(bars):
    """bars: list of (open, high, low, close)."""
    return pd.DataFrame({
        "Date": pd.date_range("2026-01-01", periods=len(bars), freq="1h"),
        "Open": [b[0] for b in bars], "High": [b[1] for b in bars],
        "Low": [b[2] for b in bars], "Close": [b[3] for b in bars],
        "Volume": [1000.0] * len(bars)})


def _run(bars, dirs, **kw):
    kw.setdefault("base_margin", 5.0)
    kw.setdefault("fee", 0.0)
    kw.setdefault("slippage", 0.0)
    kw.setdefault("sizing", "flat")
    return at.backtest_strategy(KEY, _frame(bars), dirs=dirs, **kw)


# ---------------------------------------------------------------- validation
def test_a_plan_must_be_a_plan():
    df = _frame([(100, 100, 100, 100)] * 3)
    for bad, msg in (([], "not a plan"),
                     ([(0.5, .02, .01)], "sum to 1"),
                     ([(0.5, .02, .01), (0.5, -1, .01)], "positive tp and sl"),
                     ([(-0.5, .02, .01), (1.5, .02, .01)], "must be positive")):
        with pytest.raises(ValueError, match=msg):
            at.backtest_strategy(KEY, df, slices=bad)


def test_slices_with_resume_is_refused_rather_than_guessed():
    df = _frame([(100, 100, 100, 100)] * 3)
    with pytest.raises(ValueError, match="resume"):
        at.backtest_strategy(KEY, df, slices=[(1.0, .02, .01)],
                             resume={"trades": 1})


# ------------------------------------------------------------------- parity
def test_one_slice_reproduces_the_single_exit_path_exactly():
    """Every number in this repo comes from the single-exit path. A 100% slice
    must reproduce it or nothing published before today is comparable."""
    bars = [(100, 101, 99, 100), (100, 103, 99, 102), (102, 104, 101, 103),
            (103, 103, 97, 98), (98, 99, 97, 98)]
    dirs = [1, 0, 0, 0, 0]
    a = _run(bars, dirs)
    b = _run(bars, dirs, slices=[(1.0, 0.02, 0.01)])
    for k in ("profit", "trades", "wins", "losses", "max_dd", "liqs",
              "worst_trade", "funding_total"):
        assert a[k] == b[k], f"{k}: {a[k]} vs {b[k]}"


# ------------------------------------------------- the two exits actually work
def test_the_two_slices_exit_at_their_own_targets():
    """Slice one takes 2%, slice two rides to 5%. Both should be paid."""
    bars = [(100, 100, 100, 100),      # signal bar
            (100, 102.5, 99.9, 102),   # +2% hit -> slice A takes profit
            (102, 105.5, 101, 105)]    # +5% hit -> slice B takes profit
    r = _run(bars, [1, 0, 0], slices=[(0.5, 0.02, 0.10), (0.5, 0.05, 0.10)])
    assert r["trades"] == 1
    det = r["log"][0]["slices"]
    assert [d["why"] for d in det] == ["TP", "TP"]
    assert det[0]["exit time"] < det[1]["exit time"], "A exits before B"
    # 0.5 x 2% + 0.5 x 5% of $100 notional = $3.50
    assert r["profit"] == pytest.approx(3.50, abs=1e-9)
    assert sum(d["pnl $"] for d in det) == pytest.approx(r["log"][0]["pnl $"],
                                                        abs=0.01)


def test_one_slice_can_win_while_the_other_loses():
    bars = [(100, 100, 100, 100),
            (100, 102.5, 99.5, 102),   # slice A +2% paid
            (102, 102, 98.9, 99)]      # slice B stopped at -1%
    r = _run(bars, [1, 0, 0], slices=[(0.5, 0.02, 0.01), (0.5, 0.08, 0.01)])
    det = r["log"][0]["slices"]
    assert [d["why"] for d in det] == ["TP", "SL"]
    # 0.5 x +2% and 0.5 x -1% of $100 = +$1.00 - $0.50
    assert r["profit"] == pytest.approx(0.50, abs=1e-9)
    assert r["log"][0]["why"] == "SL/TP", "the row names both outcomes"


def test_the_row_books_ONE_exit_so_the_ladder_still_means_something():
    """A trade that was simultaneously a win and a loss would leave the next
    stake undefined, and would land in the ledger as two rows for one entry."""
    bars = [(100, 100, 100, 100), (100, 102.5, 99.5, 102), (102, 102, 98.9, 99)]
    r = _run(bars, [1, 0, 0], slices=[(0.5, 0.02, 0.01), (0.5, 0.08, 0.01)])
    assert r["trades"] == 1
    assert len(r["log"]) == 1
    assert r["wins"] + r["losses"] == 1


# --------------------------------------------------- liquidation is SHARED
def test_liquidation_kills_every_open_slice_and_costs_exactly_the_margin():
    """The slices share one margin. A slice that "survives" a liquidation the
    account did not survive is invented money."""
    bars = [(100, 100, 100, 100),
            (100, 100.1, 94.0, 95)]     # -6%, past a 5% liquidation
    r = _run(bars, [1, 0], slices=[(0.5, 0.02, 0.20), (0.5, 0.30, 0.20)],
             liq_move_pct=5.0)
    assert r["liqs"] == 1
    assert r["log"][0]["why"] == "LIQ"
    assert [d["why"] for d in r["log"][0]["slices"]] == ["LIQ", "LIQ"]
    assert r["profit"] == pytest.approx(-5.0, abs=1e-9), \
        "the loss is the margin, once — not once per slice"


def test_a_stop_inside_the_liquidation_distance_still_fires_first():
    bars = [(100, 100, 100, 100), (100, 100.1, 94.0, 95)]
    r = _run(bars, [1, 0], slices=[(0.5, 0.02, 0.01), (0.5, 0.30, 0.01)],
             liq_move_pct=5.0)
    assert r["liqs"] == 0
    assert [d["why"] for d in r["log"][0]["slices"]] == ["SL", "SL"]


# ----------------------------------------------------- funding is per slice
def test_funding_stops_when_a_SLICE_exits_not_when_the_trade_does():
    """The early exit stops paying settlements; the runner keeps paying. One
    window for the whole trade overstates the cost of taking profit early."""
    # Slice A must span at least one settlement, so it cannot exit on the bar
    # it entered — a slice that opens and closes inside one bar pays nothing,
    # which is correct and was what this test got wrong first time round.
    bars = [(100, 100, 100, 100),       # signal
            (100, 101, 99.9, 100.5),    # entry at 100, no barrier touched
            (100.5, 102.5, 100, 102),   # slice A out at +2% here
            (102, 106, 101, 105)]       # slice B out at +5% here
    base = pd.Timestamp("2026-01-01").value // 10**6
    fh = [{"settle_ms": base + h * 3600_000 + 60_000, "rate": 0.001}
          for h in range(4)]
    r = _run(bars, [1, 0, 0, 0], slices=[(0.5, 0.02, 0.10), (0.5, 0.05, 0.10)],
             funding=fh)
    det = r["log"][0]["slices"]
    fa, fb = det[0]["funding $"], det[1]["funding $"]
    assert fa < 0 and fb < 0, "a long pays a positive rate"
    assert abs(fb) > abs(fa), \
        f"the slice held longer must pay more funding: A {fa} vs B {fb}"


# ------------------------------------------------------- the grid's slice plans
def test_a_plan_becomes_slices_that_keep_the_rows_stop():
    from tradingagents import backtest_report as br
    assert br.slices_for(None, 0.025, 0.02) is None
    assert br.slices_for("half 1x/3x", 0.025, 0.02) == [
        (0.5, 0.02, 0.025), (0.5, 0.06, 0.025)]
    for name in br.SLICE_PLANS:
        sl = br.slices_for(name, 0.02, 0.04)
        if sl is None:
            continue
        assert abs(sum(w for w, _, _ in sl) - 1.0) < 1e-12, \
            f"{name} weights must sum to exactly 1 for the engine's check"
        assert all(s == 0.02 for _, _, s in sl), "every slice keeps the stop"


def test_the_id_changes_with_the_plan_but_not_without_one():
    from tradingagents import backtest_report as br
    base = br.row_code("PROVE", "1h", "fade15", 0.2, 0.3, 8.0, "martingale")
    assert base == "8ZFUXG8F", "codes minted before slices must not move"
    assert br.row_code("PROVE", "1h", "fade15", 0.2, 0.3, 8.0,
                       "martingale", None) == base
    codes = {br.row_code("PROVE", "1h", "fade15", 0.2, 0.3, 8.0,
                         "martingale", p) for p in br.SLICE_PLANS}
    assert len(codes) == len(br.SLICE_PLANS), "each plan needs its own ID"


def test_is_deployed_matches_on_the_plan_too():
    from tradingagents import backtest_report as br
    dep = [{"coin": "X", "tf": "1h", "signal": "mom6", "th": 0.0, "sl": 2.0,
            "tp": 4.0, "sizing": "flat"}]
    assert br._is_deployed("X", "1h", "mom6", 0.0, 2.0, 4.0, "flat", dep)
    assert br._is_deployed("X", "1h", "mom6", 0.0, 2.0, 4.0, "flat", dep, None)
    assert not br._is_deployed("X", "1h", "mom6", 0.0, 2.0, 4.0, "flat", dep,
                               "half 1x/3x")


def test_every_row_carries_the_plan_field_even_when_it_is_none():
    """Rule F: never drop a field from a subset of rows."""
    import inspect

    from tradingagents import backtest_report as br
    src = inspect.getsource(br.run_grid)
    assert '"plan": pl,' in src
    assert '"exits": 1 if not _slx else len(_slx),' in src
    assert 'plans: Sequence = (None,)' in inspect.getsource(br.run_grid) or \
        'plans' in str(inspect.signature(br.run_grid)), \
        "plans must default to the single exit"
