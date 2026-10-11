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


# ---------------------------------------------- RCA-2026-10-11-B: the side
class _SidedFx:
    """A book whose two sides cost differently, like TOSHI on Oct 11, 2026:
    buying walks 0.1323%, selling 0.0934% at $100."""

    def __init__(self, buy=0.006, sell=0.0015, exhausted_buy=False, exhausted_sell=False):
        self.b, self.s, self.eb, self.es = buy, sell, exhausted_buy, exhausted_sell

    def book_cost(self, s, n, **k):
        return {"symbol": s, "mid": 100.0, "spread": 0.0008, "slippage": self.b,
                "book_exhausted": self.eb, "notional_tested": n,
                "slippage_buy": self.b, "slippage_sell": self.s,
                "exhausted_buy": self.eb, "exhausted_sell": self.es,
                "book_exhausted_any": self.eb or self.es}

    def contract_spec(self, s):
        return {"takerFeeRate": 0.00075, "maintenanceMarginRate": 0.005}

    def funding_now(self, s):
        return {"rate": 0.0, "cycle_h": 8, "per_day": 0.0, "next_settle_ms": 0}

    def liquidation_move_pct(self, s, lev):
        return 4.5


def _spec(monkeypatch):
    monkeypatch.setitem(at.STRATEGY_SPECS, "t_1h", {"tp": 0.02, "sl": 0.01,
                                                     "bar_seconds": 3600})
    at._CYCLE_READS = None


def test_a_short_is_judged_on_the_side_it_sells_into(monkeypatch):
    """Oct 11, 2026 (RCA-2026-10-11-B): the runner read only the BUY side, so
    eight practice shorts on Gate were judged on the asks while the backtest
    judged them on the bids. 0.6% to buy, 0.15% to sell, 2% target: the
    long's round trip is 2*(0.6+0.075) = 1.35%, 68% of it — refused; the
    short's is 2*(0.15+0.075) = 0.45%, 23% — let through, as the backtest."""
    _spec(monkeypatch)
    fx = _SidedFx()
    assert at.edge_check("t_1h", "TOSHI_USDT", 5.0, fx=fx, side=1)["verdict"] == "block"
    short = at.edge_check("t_1h", "TOSHI_USDT", 5.0, fx=fx, side=-1)
    assert short["verdict"] != "block" and short["slippage"] == pytest.approx(0.0015)


def test_before_the_signal_a_strategy_is_refused_only_if_both_sides_refuse(monkeypatch):
    """The screening pass runs before the candle says long or short; reading
    the buy side alone turned TOSHI away for shorts too (10:25am, Oct 10,
    2026: "round-trip cost 0.419% vs take-profit 0.80% = 52%")."""
    _spec(monkeypatch)
    assert at.edge_check("t_1h", "TOSHI_USDT", 5.0, fx=_SidedFx(), side=0)["verdict"] != "block"
    both = _SidedFx(buy=0.006, sell=0.006)
    assert at.edge_check("t_1h", "TOSHI_USDT", 5.0, fx=both, side=0)["verdict"] == "block"


def test_a_book_that_cannot_fill_either_side_refuses_like_the_backtest(monkeypatch):
    """The backtest refuses a minute when EITHER side cannot fill the size —
    a trade has to get out as well as in (book_history: `exhausted`)."""
    _spec(monkeypatch)
    thin_exit = _SidedFx(buy=0.0005, sell=0.0005, exhausted_sell=True)
    assert at.edge_check("t_1h", "X_USDT", 5.0, fx=thin_exit, side=1)["verdict"] == "block"


def test_the_book_walk_reports_both_sides_from_one_read():
    from tradingagents.dataflows import exchange_common as xc

    book = {"asks": [[100.10, 1.0], [101.0, 100.0]], "bids": [[99.90, 100.0]]}
    got = xc.book_cost_from(book, contract_size=1.0, notional_usd=500.0, symbol="X")
    assert got["slippage_buy"] > got["slippage_sell"] > 0
    assert got["slippage"] == got["slippage_buy"], "the requested side stays `slippage`"
    thin = {"asks": [[100.10, 100.0]], "bids": [[99.90, 0.5]]}
    got = xc.book_cost_from(thin, contract_size=1.0, notional_usd=500.0, symbol="X")
    assert got["exhausted_sell"] and not got["exhausted_buy"] and got["book_exhausted_any"]


# ------------------------- RCA-2026-10-11-B, the review of the first fix
def test_practice_charges_the_exit_on_the_other_side_of_the_book(monkeypatch):
    """A short closes by BUYING the asks and a long by SELLING the bids — the
    backtest's exit leg (`_c_out`). The first fix put a short's exit on the
    sell side it opened on (TOSHI: 0.0934% where the backtest pays 0.1323%),
    and longs had always paid the buy side on the way out."""
    _spec(monkeypatch)
    fx = _SidedFx()                                   # buy 0.6%, sell 0.15%
    fee = at.taker_fee("TOSHI_USDT", fx=fx)           # floored by the venue's rule
    for side, exit_side in ((-1, 0.006), (1, 0.0015)):
        g = at.edge_check("t_1h", "TOSHI_USDT", 5.0, fx=fx, side=side)
        pos = {"side": side, "rt_cost": g["round_trip_cost"],
               "book_slippage": g["slippage"], "exit_slippage": g["exit_slippage"]}
        assert at.paper_round_trip(pos, "TOSHI_USDT", fx=fx) == pytest.approx(
            2 * fee + exit_side), side
    old = {"rt_cost": 0.01, "book_slippage": 0.003}   # a position from before
    assert at.paper_round_trip(old, "TOSHI_USDT", fx=fx) == pytest.approx(0.007)


def test_before_the_signal_each_side_pays_its_own_funding(monkeypatch):
    """The screening paired the cheaper side's book with the PAYING side's
    funding: longs paying 0.35% a day on a 0.6% target (funding eats over
    half of it) refused the strategy for shorts too, which RECEIVE it — and
    the backtest takes that short. (`per_day` is what a LONG pays.)"""
    monkeypatch.setitem(at.STRATEGY_SPECS, "t_1h", {"tp": 0.006, "sl": 0.003,
                                                     "bar_seconds": 3600})
    at._CYCLE_READS = None
    fx = _SidedFx(buy=0.0002, sell=0.0002)
    fx.funding_now = lambda s: {"rate": 0.0035 / 3, "cycle_h": 8, "per_day": 0.0035,
                                "next_settle_ms": 0}
    assert at.edge_check("t_1h", "FUNDPAY_USDT", 5.0, fx=fx, side=1)["verdict"] == "block"
    assert at.edge_check("t_1h", "FUNDPAY_USDT", 5.0, fx=fx, side=-1)["verdict"] != "block"
    screen = at.edge_check("t_1h", "FUNDPAY_USDT", 5.0, fx=fx, side=0)
    assert screen["verdict"] != "block" and screen["sides"] == {"long": "block",
                                                                "short": screen["verdict"]}


def test_a_book_reading_files_both_sides_and_the_forecast_reads_the_signals_own(
        monkeypatch, tmp_path):
    """The saved readings the account forecast replays mixed sides once the
    first fix landed — a short's cheaper round trip could price a long."""
    import json as _json

    _spec(monkeypatch)
    monkeypatch.setattr(at, "BOOK_READINGS_PATH", tmp_path / "book_readings.jsonl")
    at._LAST_READING.clear()
    at.edge_check("t_1h", "TOSHI_USDT", 5.0, fx=_SidedFx(), side=-1)
    line = _json.loads((tmp_path / "book_readings.jsonl").read_text().splitlines()[-1])
    fee = at.taker_fee("TOSHI_USDT", fx=_SidedFx())
    assert line["round_trip"] == pytest.approx(2 * (0.006 + fee))
    assert line["round_trip_short"] == pytest.approx(2 * (0.0015 + fee))
    assert line["slippage"] == pytest.approx(0.006) and line["slippage_sell"] == pytest.approx(0.0015)
    from tradingagents import portfolio_replay as pr

    got = pr._reading_at(pr._readings_of([(1000, line)]), 1000)
    assert pr._side_cost(got, 1) == pytest.approx(line["round_trip"])
    assert pr._side_cost(got, -1) == pytest.approx(line["round_trip_short"])
    assert pr._side_cost(pr._reading_at(pr._readings_of([(1000, {"round_trip": 0.01})]), 1000), -1) \
        == pytest.approx(0.01), "a reading from before the split prices both sides as it did"
