"""The practice-against-backtest check reads a strategy the Backtest list hides
(operator, Oct 17, 2026: "What is the most accurate fix for this", then "yes").

Since Oct 16, 2026 8:44pm the Backtest v2 list keeps only strategies whose win
pays two losses after fees (`backtest_report.index_keeps`), and 23 practice
strategies — 60 trades — had no row to open. Their rows are still in the store
(`store_keeps` keeps every flat row), and a row's trade log is built from the
row in its pair file, never from the list (`market_sweep.trades_for`). So the
check asks for the stored row whose OWN settings make the id, and reads the
same trade log a click on it would show: measured on the 23, every row found,
49 of the 60 trades close.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit

# ONE TIMELINE: the minutes, the row's last bar and its trades all sit on it.
MIN, H = 60_000, 3_600_000
H0 = 1_790_000_000_000 - (1_790_000_000_000 % H)


def _write_minutes(home, hours):
    rows = []
    for h in range(hours):
        for k in range(60):
            hi = lo = 100.0
            if h % 5 == 2 and k == 7:
                hi = 101.5                       # the target is touched
            if h % 5 == 4 and k == 40:
                lo = 96.5                        # the stop is touched
            rows.append((H0 + (h * 60 + k) * MIN, 100.0, hi, lo, 100.0, 7.0))
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v"])
    (home / "candles").mkdir(parents=True, exist_ok=True)
    (home / "candles" / "XPIN_USDT-1m.json").write_text(json.dumps(
        {k: [float(x) if k != "t" else int(x) for x in df[k]] for k in df.columns}))


@pytest.fixture
def v2(tmp_path, monkeypatch):
    """A Backtest v2 store holding two XPIN 1h ote rows (TP 1% and 1.2%, stop
    3%) — neither pays two losses after fees, so the list would hide both."""
    from tradingagents import auto_trader as at, market_sweep as msw, stores

    home = tmp_path / "v2"
    st = stores.Store(name="v2", home=home, candles=home / "candles",
                      rows_db=home / "rows.db", parquet=tmp_path / "pq",
                      fine_tf="1m", download_kind="download_v2", backtest_kind="backtest_v2")
    (home / "rows").mkdir(parents=True)
    (home / "state").mkdir()
    _write_minutes(home, 120)
    last_ms = H0 + 119 * H
    (home / "rows" / "XPIN-1h.json").write_text(json.dumps([
        {"coin": "XPIN", "tf": "1h", "signal": "ote", "th": 0.0, "sl": sl, "tp": tp,
         "sizing": "flat", "trades": 1, "wins": 1, "losses": 0, "profit": 0.9, "bars": 100,
         "last_ms": last_ms, "fee": 0.0004, "res": "1m", "unclear": 0}
        for sl, tp in ((3.0, 1.0), (3.0, 1.2))]))
    (home / "state" / "XPIN-1h.json").write_text(json.dumps({"__last_ms__": last_ms}))
    msw.save_costs("XPIN_USDT", fee=0.0004, liq=4.0, funding=[], root=str(home))
    monkeypatch.setattr(at, "_dirs_for_backtest",
                        lambda key, hi, lo, cl, **k: [1 if i % 5 == 0 else 0
                                                      for i in range(len(cl))])
    return st


def _id(tp: float) -> str:
    from tradingagents import backtest_report as br

    return br.row_code("XPIN", "1h", "ote", 0.0, 3.0, tp, "flat", res="1m")


def test_a_hidden_strategy_is_read_from_the_stored_row_that_makes_its_id(v2):
    """The same trades a click on its row would show — same function, same
    row — found by the id the row's own settings make."""
    from tradingagents import backtest_report as br, market_sweep as msw

    rows = msw.pair_rows("XPIN", "1h", str(v2.home))
    assert not any(br.index_keeps(r) for r in rows), "the list would hide both"
    click = msw.trades_for("XPIN", "1h", signal="ote", th=0.0, sl=3.0, tp=1.2,
                           sizing="flat", store=v2)
    got = msw.trades_for_id("#" + _id(1.2).lower(), "xpin_usdt", store=v2)
    assert got["found"] is True and got["log"] and got["log"] == click["log"]
    assert got["row"] == {"id": _id(1.2), "coin": "XPIN", "tf": "1h", "signal": "ote",
                          "th": 0.0, "sl": 3.0, "tp": 1.2, "sizing": "flat",
                          "trades": 1, "wins": 1, "profit": 0.9, "listed": False}
    # the sibling row is a different id, and a named frame narrows the search
    assert msw.trades_for_id(_id(1.0), "XPIN", "1h", store=v2)["row"]["tp"] == 1.0
    assert msw.trades_for_id(_id(1.0), "XPIN", "4h", store=v2)["found"] is False


def test_an_id_no_stored_row_makes_is_named_never_guessed(v2):
    from tradingagents import market_sweep as msw

    got = msw.trades_for_id("ZZZZ9999", "XPIN", store=v2)
    assert got["found"] is False and got["log"] == []
    assert "#ZZZZ9999" in got["why"] and "XPIN" in got["why"]


def test_the_route_serves_it_read_only(v2, monkeypatch):
    from tradingagents import stores
    from tradingagents.api import app

    monkeypatch.setattr(stores, "V2", v2)
    c = TestClient(app)
    got = c.get("/api/v2/strategies/trades-by-id",
                params={"row_id": _id(1.0), "coin": "XPIN", "tf": "1h"}).json()
    assert got["found"] is True and got["row"]["tp"] == 1.0 and got["log"]
    assert c.get("/api/v2/strategies/trades-by-id",
                 params={"row_id": _id(1.0), "coin": "XPIN", "tf": "2h"}).status_code == 400
