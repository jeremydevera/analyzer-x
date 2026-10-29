"""The Backtest v3 tab (operator, Oct 23, 2026: *"i dont see it in ui where is
it i said to create backtest v3 tab"*, then *"Tab now, fill it later"*).

The tab runs ONE coin and ONE idea the v3 way on request (`v3_page.run`,
which is `v3_smoke.measure` — the command line's own code) and says plainly
that its tested-ideas section fills when Part 2's GitHub test has run.
These tests hold that every number the tab prints is derived from the run:
the trade rows add up to the profit shown, wins and losses add up to the
trades, the worst losing run is the run's own, and a bad pick is refused by
name. Candles here are hours at 100 whose next hour trades through the
order and whose hour after that reaches the target or the stop (no minutes,
so the candle rule decides, as it does on Gate's archive holes)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tradingagents import backtest_report as br, stores, v3_page as vp

REPO = Path(__file__).resolve().parent.parent
H = 3_600_000
N = 400
T0 = 1_790_000_000_000 - (1_790_000_000_000 % H) - N * H
SIGNALS = set(range(300, 400, 10))            # ten long signals, at bars 300, 310, ... 390


@pytest.fixture(autouse=True)
def _never_the_real_verdict_store(monkeypatch, tmp_path):
    """The tab's tested-ideas section reads the verdict store: a test of the tab never reads the
    operator's own."""
    from tradingagents import v3_verdicts

    monkeypatch.setattr(v3_verdicts, "store_path", lambda: tmp_path / "no-verdicts.json")



def _bars():
    """Every hour opens and closes at 100. The hour after a signal trades down
    to 99.8 (through the 100.0 waiting buy); the hour after that reaches the
    2% target (102.5) for the 1st, 3rd, 5th... signal and the 1% stop (98.5)
    for the 2nd, 4th, 6th..."""
    hi = [100.3] * N
    lo = [99.9] * N
    for k, i in enumerate(sorted(SIGNALS)):
        if i + 2 >= N:
            continue
        hi[i + 1], lo[i + 1] = 100.2, 99.8
        if k % 2 == 0:
            hi[i + 2], lo[i + 2] = 102.5, 99.5
        else:
            hi[i + 2], lo[i + 2] = 100.5, 98.5
    return hi, lo


class FakeFx:
    def __init__(self):
        hi, lo = _bars()
        self.df = pd.DataFrame({
            "Date": pd.to_datetime([T0 + k * H for k in range(N)], unit="ms"),
            "Open": [100.0] * N, "High": hi, "Low": lo, "Close": [100.0] * N,
            "Volume": [1.0] * N})

    def klines(self, sym, iv, limit):
        return self.df.tail(limit).reset_index(drop=True)

    def minutes(self, sym, start_s, end_s):
        return pd.DataFrame({"Date": pd.to_datetime([], unit="s"), "High": [], "Low": []})

    def funding_history(self, sym, since_ms=None):
        return []

    def contract_spec(self, sym):
        return {"contractSize": 0.01, "minVol": 1, "maintenanceMarginRate": 0.005,
                "maxLeverage": 20, "minLeverage": 1}

    def trading_symbols(self):
        return ["BTC_USDT", "TEST_USDT"]


@pytest.fixture()
def world(monkeypatch):
    import tradingagents.auto_trader as at
    from tradingagents import cost_store

    monkeypatch.setattr(at, "_dirs_for_backtest",
                        lambda key, hi, *a, **k: [1 if i in SIGNALS else 0 for i in range(len(hi))])
    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: cost_store.empty())
    monkeypatch.setattr(at, "maker_fee_floor", lambda *a, **k: 0.0002)    # Gate's two floors
    monkeypatch.setattr(at, "fee_floor", lambda *a, **k: 0.00075)
    return FakeFx()


BODY = {"sym": "TEST_USDT", "tf": "1h", "signal": "bb20", "exit": "fixed",
        "params": {"tp_pct": 2, "sl_pct": 1}, "days": 30, "risk_usd": 1}


def test_the_run_adds_up_to_what_the_tab_prints(world):
    got = vp.run(dict(BODY), fx=world)
    s, rows = got["summary"], got["trades"]
    # a 1% stop at $1 risk: $100 of coin. A win: +2% = +2.00 less the maker fee
    # in and out (0.02% each way on $100) = +1.96. A loss: -1.00 less maker in,
    # taker out and the flat gap (0.02% + 0.075% + 0.03% on $100) = -1.125,
    # shown as -1.13. Five of each.
    assert s["trades"] == len(rows) == 10
    assert (s["wins"], s["losses"]) == (5, 5) and s["wins"] + s["losses"] == s["trades"]
    assert [r["pnl"] for r in rows] == [1.96, -1.13] * 5
    assert s["profit"] == pytest.approx(sum(r["pnl"] for r in rows)) == pytest.approx(4.15)
    assert rows[-1]["total"] == pytest.approx(s["profit"]), "the running total ends at the profit"
    assert (s["worst_run_usd"], s["worst_run_trades"]) == (pytest.approx(-1.13), 1)
    assert s["win_rate"] == pytest.approx(0.5)
    assert s["break_even"] == pytest.approx(1.13 / (1.96 + 1.13))
    assert s["leverage_min"] == s["leverage_max"] == 20
    assert s["notional_min"] == s["notional_max"] == pytest.approx(100.0)
    assert s["combos"] == 1
    assert s["trades_per_day"] == pytest.approx(10 / (100 / 24)), "over the 100 hours walked"


def test_each_trade_row_is_the_engines_trade(world):
    rows = vp.run(dict(BODY), fx=world)["trades"]
    first = rows[0]
    assert first["side"] == "long" and first["why"] == "TP" and first["how"] == "target"
    assert first["signal_ms"] == T0 + 300 * H, "the signal candle"
    assert first["entry_ms"] == T0 + 301 * H and first["entry"] == pytest.approx(100.0)
    assert first["exit_ms"] == T0 + 302 * H and first["exit"] == pytest.approx(102.0)
    assert rows[1]["why"] == "SL" and rows[1]["exit"] == pytest.approx(99.0)
    assert [r["n"] for r in rows] == list(range(1, 11))
    assert all(a["exit_ms"] <= b["entry_ms"] for a, b in zip(rows, rows[1:], strict=False))


def test_the_window_and_costs_are_printed_from_the_run(world):
    p = vp.run(dict(BODY), fx=world)["provenance"]
    assert p["start_ms"] == T0 + 300 * H, "the window starts after the 300-candle lead-in"
    assert p["end_ms"] == T0 + N * H
    assert p["risk_usd"] == 1 and p["maker_fee"] == 0.0002 and p["taker_fee"] == 0.00075
    assert p["coverage"] == 0.0, "no recorded book covers nothing"
    assert p["exit_words"] == "target 2% and stop 1%"
    assert p["venue"]


def test_the_id_is_the_v3_id_of_the_combination(world):
    a = vp.run(dict(BODY), fx=world)["id"]
    b = vp.run(dict(BODY, risk_usd=5), fx=world)["id"]
    assert a == b, "the risk box changes dollars, never which strategy it is"
    assert a == br.row_code("TEST_USDT", "1h", "bb20", 0.0, 1.0, 2.0, "flat", res="v3")
    assert a != br.row_code("TEST_USDT", "1h", "bb20", 0.0, 1.0, 2.0, "flat", res="1m")
    trail = vp.parse(dict(BODY, exit="trail", params={"atr_mult": 3, "ma_n": 50}))
    snap = vp.parse(dict(BODY, exit="snap", params={"stop_atr": 3, "max_bars": 24}))
    assert len({vp.row_id(trail), vp.row_id(snap), a}) == 3


@pytest.mark.parametrize("bad, word", [
    ({"tf": "2h"}, "timeframe"),
    ({"signal": "nosuchidea"}, "idea"),
    ({"sym": "NOPE_USDT"}, "NOPE_USDT"),
    ({"sym": ""}, "coin"),
    ({"exit": "magic"}, "exit"),
    ({"params": {"tp_pct": 0, "sl_pct": 1}}, "Target"),
    ({"params": {"tp_pct": 2, "sl_pct": 80}}, "Stop"),
    ({"params": {"tp_pct": "two", "sl_pct": 1}}, "Target"),
    ({"days": 45}, "days"),
    ({"risk_usd": 0}, "risk"),
])
def test_a_bad_pick_is_refused_by_name(world, bad, word):
    with pytest.raises(ValueError, match=word):
        vp.run(dict(BODY, **bad), fx=world)


def test_the_worst_losing_run_is_the_worst_unbroken_sum():
    assert vp.worst_run([1.0, -1.0, -2.0, 3.0, -0.5]) == (pytest.approx(-3.0), 2)
    assert vp.worst_run([1.0, 2.0]) == (0.0, 0)
    assert vp.worst_run([-0.5, -0.5, 1.0, -2.0]) == (pytest.approx(-2.0), 1)


def test_cents_round_half_up_like_the_screen():
    assert vp.cents(-1.125) == -1.13 and vp.cents(1.125) == 1.13 and vp.cents(1.005) == 1.01


def test_the_choices_come_from_the_registries(world):
    o = vp.options(fx=world)
    assert o["signals"] == list(br.SIGNALS)
    assert o["tfs"] == list(stores.FIVE)
    assert o["coins"] == ["BTC_USDT", "TEST_USDT"]
    assert o["default_days"] == 30 and 30 in o["days"]
    assert set(o["exits"]) == {"fixed", "trail", "snap"}


def test_the_tested_ideas_section_says_it_has_not_run(tmp_path):
    t = vp.tested(tmp_path / "rows.db")
    assert t["state"] == "not_run" and t["rows"] == 0
    assert "not run yet" in t["words"]


def test_the_tab_is_in_the_menu_once_and_the_routes_exist():
    nav = (REPO / "webapp/src/layout/AppSidebar.tsx").read_text(encoding="utf-8")
    assert nav.count('path: "/backtest-v3"') == 1
    assert (REPO / "webapp/src/app/(admin)/backtest-v3/page.tsx").is_file()
    api = (REPO / "tradingagents/api.py").read_text(encoding="utf-8")
    assert api.count('@app.get("/api/v3/options")') == 1
    assert api.count('@app.post("/api/v3/run")') == 1


def test_the_route_answers_and_refuses_by_name(monkeypatch):
    from fastapi.testclient import TestClient

    from tradingagents.api import app

    monkeypatch.setattr(vp, "run", lambda body, **k: {"ok": body["sym"]})
    c = TestClient(app)
    assert c.post("/api/v3/run", json={"sym": "BTC_USDT"}).json() == {"ok": "BTC_USDT"}

    def refuse(body, **k):
        raise ValueError("timeframe: pick one of 15m, 30m, 1h, 4h, 1d")

    monkeypatch.setattr(vp, "run", refuse)
    r = c.post("/api/v3/run", json={"tf": "2h"})
    assert r.status_code == 400 and "timeframe" in r.json()["detail"]
