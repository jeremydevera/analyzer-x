"""The backtest refuses exactly what the runner refuses (phase 4, Oct 10, 2026).

`edge_check` decides at every live signal whether the trade's cost eats its
target. The backtest now asks the same question of the order book Gate
recorded at that minute — through ONE function, `cost_verdict`, which
`edge_check` itself calls. CLAUDE.md, "Every cost the BACKTEST charges, the
GATE charges": when a guard and a measurement model the same thing, test the
lists against each other — so every branch is driven through both here.
"""
import pytest

from tradingagents import auto_trader as at

BASE = dict(tp=0.012, sl=0.006, spread=0.0004, slippage=0.0002, fee=0.00075,
            fund_cost=0.0, fund_per_day=0.0, fund_known=True, hold_s=3600,
            liq=0.045, exhausted=False)


def v(**kw):
    return at.cost_verdict(**{**BASE, **kw})


def test_a_cheap_trade_is_ok_and_its_round_trip_is_the_runners():
    got = v()
    assert got["verdict"] == "ok"
    assert got["round_trip"] == pytest.approx(2 * (0.0002 + 0.00075))
    assert got["ratio"] == pytest.approx(got["round_trip"] / 0.012)


def test_each_reason_to_refuse():
    assert v(slippage=0.003)["verdict"] == "block", "cost >= 50% of TP"
    assert v(slippage=0.0012)["verdict"] == "warn", "cost >= 20% of TP still trades"
    assert v(exhausted=True)["verdict"] == "block", "the book cannot fill"
    assert v(spread=0.007)["verdict"] == "block", "the stop sits inside the gap"
    assert v(fund_per_day=0.007)["verdict"] == "block", "funding eats the target in a day"
    assert v(fund_known=False, hold_s=7200)["verdict"] == "block", "unknown funding, long hold"
    assert v(fund_known=False, hold_s=900)["verdict"] == "ok", "unknown funding, short hold"
    assert v(sl=0.04, liq=0.045)["verdict"] == "block", "a stop past the liquidation ceiling"


def test_edge_check_answers_through_it(monkeypatch):
    """edge_check is the same function with live inputs: a stop inside the
    gap is refused by the runner exactly as the backtest refuses it."""
    seen = []
    real = at.cost_verdict

    def spy(**kw):
        seen.append(kw)
        return real(**kw)
    monkeypatch.setattr(at, "cost_verdict", spy)
    monkeypatch.setitem(at.STRATEGY_SPECS, "t_1h", {"tp": 0.012, "sl": 0.006,
                                                     "bar_seconds": 3600})

    class Fx:
        def order_book(self, s):
            return {"asks": [[100.04, 1e6]], "bids": [[99.96, 1e6]]}

        def book_cost(self, s, n, **k):
            return {"symbol": s, "mid": 100.0, "spread": 0.0008, "slippage": 0.0004,
                    "book_exhausted": False, "notional_tested": n}

        def contract_spec(self, s):
            return {"takerFeeRate": 0.00075, "maintenanceMarginRate": 0.005}

        def funding_now(self, s):
            return {"rate": 0.0, "cycle_h": 8, "per_day": 0.0, "next_settle_ms": 0}

        def liquidation_move_pct(self, s, lev):
            return 4.5
    r = at.edge_check("t_1h", "X_USDT", 5.0, fx=Fx(), side=1)
    assert seen, "edge_check decides through cost_verdict"
    assert r["verdict"] == real(**seen[-1])["verdict"]
