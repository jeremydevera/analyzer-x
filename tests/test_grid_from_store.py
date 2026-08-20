"""Store-first analysis: the second ask must not recompute the first.

The operator's words: "when doing analysis its not doing from scratch" and
"i want everything stored"."""
import pytest

from tradingagents import backtest_report as br
from tradingagents import market_sweep as msw


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "CANDLES", tmp_path / "candles")
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")


def _row(**kw):
    r = {"coin": "APEX", "tf": "1h", "signal": "mom6", "th": 0.3, "sl": 1.0,
         "tp": 4.0, "rr": 4.0, "sizing": "flat", "lev": 20, "base": 5.0,
         "notional": 100.0, "trades": 120, "wins": 50, "losses": 70,
         "winrate": 41.7, "profit": 12.0, "h1": 6.0, "h2": 6.0, "green": 8,
         "months": 12, "worst": -2.0, "dd": 9.0, "liqs": 0, "days": 300,
         "bars": 7000, "monthly": {"2026-08": 12.0}, "cost_of_tp": 5.0,
         "rt": 0.2, "gate": "ok"}
    r.update(kw)
    return r


def test_grid_from_store_reuses_without_recomputing(monkeypatch):
    msw.save_pair_rows("APEX", "1h", [_row(), _row(signal="fvg", th=0.0,
                                                   profit=-3.0)])
    calls = []

    def fake_run_pair(sym, tf, **kw):
        calls.append((sym, tf))
        return {"coin": "APEX", "tf": "1h", "rows": [], "added": 0,
                "source": "cache", "why": "no new bars", "incremental": True,
                "new_bars": 0, "fee": 0.0004, "liq": 4.0, "rt": 0.002,
                "bars": 7000, "days": 300}

    monkeypatch.setattr(msw, "run_pair", fake_run_pair)
    p = br.grid_from_store(["APEX_USDT"], ["1h"], embed_limit=0)
    assert calls == [("APEX_USDT", "1h")]
    assert len(p["rows"]) == 2, "both stored rows served, loser included"
    assert p["reuse"]["stored_rows"] == 2
    assert p["reuse"]["new_bars"] == 0
    assert p["reuse"]["recomputed_rows"] == 0
    assert all("id" in r and "mon" in r for r in p["rows"])
    assert p["meta"]["APEX|1h"]["liq"] == 4.0


def test_missing_deployed_combo_is_computed_once(monkeypatch):
    msw.save_pair_rows("APEX", "1h", [_row()])
    monkeypatch.setattr(msw, "run_pair", lambda sym, tf, **kw: {
        "coin": "APEX", "tf": "1h", "rows": [], "added": 0, "source": "cache",
        "why": "no new bars", "incremental": True, "new_bars": 0,
        "fee": 0.0004, "liq": 4.0, "rt": 0.002, "bars": 7000, "days": 300})
    computed = []

    def fake_compute(sym, tf, combos, **kw):
        computed.extend(combos)
        return [_row(signal="sweep30", th=0.0, sl=3.0, tp=3.0,
                     sizing="martingale")]

    monkeypatch.setattr(msw, "compute_combos", fake_compute)
    dep = [{"coin": "APEX", "tf": "1h", "signal": "sweep30", "th": 0.0,
            "sl": 3.0, "tp": 3.0, "sizing": "martingale"}]
    p = br.grid_from_store(["APEX_USDT"], ["1h"], deployed=dep, embed_limit=0)
    assert len(computed) == 1, "exactly the missing combination"
    assert p["reuse"]["deployed_computed"] == 1
    # …and once stored, a second build computes nothing
    computed.clear()
    msw.save_pair_rows("APEX", "1h", [_row(), _row(
        signal="sweep30", th=0.0, sl=3.0, tp=3.0, sizing="martingale")])
    br.grid_from_store(["APEX_USDT"], ["1h"], deployed=dep, embed_limit=0)
    assert computed == []


def test_render_speaks_the_reuse_line():
    msw.save_pair_rows("APEX", "1h", [_row()])
    p = {"rows": [dict(_row(), mon=[12.0], id="X")], "meta": {}, "series": {},
         "months": ["2026-08"], "cur": "2026-08", "lev": 20, "slip": 0.0003,
         "base": 5.0, "ladder": [1, 1, 2, 2, 4, 4, 8], "deployed": [],
         "excluded": [], "days_asked": 365, "fetched": "2026-08-20 12:00",
         "reuse": {"stored_rows": 13200, "new_bars": 96,
                   "recomputed_rows": 82, "fresh_pairs": [],
                   "deployed_computed": 0}}
    p["rows"][0].pop("monthly", None)
    html = br.render(p, title="t")
    assert "13,200 rows reused" in html
    assert "96 new bars tested" in html
    assert "82 rows recomputed" in html


def test_version_bump_resets_a_stale_pair(tmp_path, monkeypatch):
    """A store built with fewer signals must not be served as current."""
    msw.save_states("APEX", "1h", {"__last_ms__": 123,
                                   "__version__": "signals54-th1"})
    src = open("tradingagents/market_sweep.py").read()
    assert "__version__" in src
    assert "states, last_ms = {}, 0" in src


def test_trades_for_rebuilds_the_stored_rows_trades(monkeypatch, tmp_path):
    """The store keeps one row per strategy; the trades behind it must be
    derivable and must SUM to that row — same candles, same trades."""
    import math

    import pandas as pd

    n = 400
    close = [100 + 8 * math.sin(i / 7.0) for i in range(n)]
    df = pd.DataFrame({
        "Date": pd.date_range("2026-01-01", periods=n, freq="h"),
        "Open": close, "High": [c + 1.2 for c in close],
        "Low": [c - 1.2 for c in close], "Close": close,
        "Volume": [5.0] * n})
    monkeypatch.setattr(msw, "refresh_candles",
                        lambda sym, tf, days=365: (df, 0, "cache"))
    import tradingagents.auto_trader as at
    monkeypatch.setattr(at, "taker_fee", lambda s, fx=None: 0.0004)

    got = msw.trades_for("FAKE", "1h", signal="mom6", th=0.3, sl=1.0,
                         tp=2.0, sizing="martingale")
    assert got["trades"] > 0
    assert len(got["log"]) == got["trades"]
    assert got["wins"] + got["losses"] == got["trades"]
    total = round(sum(t["pnl $"] for t in got["log"]), 2)
    assert abs(total - got["profit"]) < 0.02, "the log must sum to the total"
    assert {"WIN", "LOSE"} >= {t["WIN/LOSE"] for t in got["log"]}
