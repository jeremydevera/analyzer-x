"""Backtest v2's trade log, days window, UPDATE job and deployed ids all read
the v2 store — never v1's — and settle exits by the minute.

The fixture is ONE timeline: 1-minute bars that rebuild exactly into the hour
bars the row was measured on (RCA-2026-09-12-A's rule for anything time
dependent).
"""
import inspect
import json

import pandas as pd
import pytest

from tradingagents import auto_trader as at, market_sweep as msw, stores

H0 = 1_789_516_800_000            # Sep 16, 2026 00:00 UTC


def _minutes(n_hours, both_at_hour=1, tp_first=True):
    """Flat 100.0 minutes, except hour `both_at_hour` where the target 101.0
    and the stop 97.0 are BOTH touched — target first (minute 5) or stop
    first — so the hour rule and the minute rule must disagree."""
    rows = []
    for h in range(n_hours):
        for k in range(60):
            hi = lo = 100.0
            # ONE branch per order. The first draft read `(k == 30) == tp_first`
            # for the stop, which with tp_first=False marked 59 of 60 minutes
            # as a stop touch (Sep 18, 2026 review) — and nothing ran that
            # branch. Now both orders are exact and both are exercised.
            if h == both_at_hour:
                if tp_first:
                    if k == 5:
                        hi = 101.5          # target first ...
                    if k == 30:
                        lo = 96.5           # ... stop later
                else:
                    if k == 5:
                        lo = 96.5           # stop first ...
                    if k == 30:
                        hi = 101.5          # ... target later
            rows.append((H0 + (h * 60 + k) * 60_000, 100.0, hi, lo, 100.0, 7.0))
    df = pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["t"], unit="ms")
    return df.drop(columns="t")


@pytest.fixture
def v2(tmp_path, monkeypatch):
    """A v2 store with XPIN's 1-minute candles, one measured row and its state,
    beside a v1 store that has NOTHING for XPIN — so a read that lands on v1
    is visibly wrong."""
    home = tmp_path / "v2"
    st = stores.Store(name="v2", home=home, candles=home / "candles",
                      rows_db=home / "rows.db", parquet=tmp_path / "parquet-v2",
                      fine_tf="1m", download_kind="download_v2",
                      backtest_kind="backtest_v2")
    (home / "candles").mkdir(parents=True)
    (home / "rows").mkdir()
    (home / "state").mkdir()
    # 70 hours: past the 60-bar floor every replay applies to the FRAME
    m1 = _minutes(70, both_at_hour=1, tp_first=True)
    (home / "candles" / "XPIN_USDT-1m.json").write_text(json.dumps({
        "t": [int(x) for x in m1["Date"].to_numpy().astype("datetime64[ms]").astype("int64")],
        "o": list(m1["Open"]), "h": list(m1["High"]), "l": list(m1["Low"]),
        "c": list(m1["Close"]), "v": list(m1["Volume"])}))
    last_ms = H0 + 69 * 3_600_000
    (home / "rows" / "XPIN-1h.json").write_text(json.dumps([{
        "coin": "XPIN", "tf": "1h", "signal": "ote", "th": 0.0, "sl": 3.0,
        "tp": 1.0, "sizing": "flat", "trades": 1, "wins": 1, "losses": 0,
        "profit": 0.9, "bars": 70, "last_ms": last_ms, "fee": 0.0004,
        "res": "1m", "unclear": 0}]))
    (home / "state" / "XPIN-1h.json").write_text(json.dumps({"__last_ms__": last_ms}))
    msw.save_costs("XPIN_USDT", fee=0.0004, liq=4.0, funding=[], root=str(home))
    # v1 has nothing for this coin
    monkeypatch.setattr(msw, "CANDLES", tmp_path / "v1" / "candles")
    monkeypatch.setattr(msw, "HOME", tmp_path / "v1")
    monkeypatch.setattr(msw, "STATES", tmp_path / "v1" / "state")
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "v1" / "rows")
    monkeypatch.setattr(msw, "COSTS", tmp_path / "v1" / "costs")
    msw._DIRS_CACHE.clear()
    # the signal: fire on bar 0 (entry at bar 1's open = 100.0)
    monkeypatch.setattr(at, "_dirs_for_backtest",
                        lambda key, hi, lo, cl, **k: [1] + [0] * (len(cl) - 1))
    return st


def test_the_v2_trade_log_replays_from_the_minutes(v2):
    got = msw.trades_for("XPIN", "1h", signal="ote", th=0.0, sl=3.0, tp=1.0,
                         sizing="flat", store=v2)
    assert got.get("log"), got
    t = got["log"][0]
    assert t["why"] == "TP", "the target was touched at minute 5, the stop at 30 — TP first"
    assert t["exit_minute_ms"] == H0 + 3_600_000 + 5 * 60_000
    assert "minute" in got["source"]
    # the window's first/last bars print in the ONE date format, never the
    # sliced `2026-08-20 16:00` this line carried until Sep 17, 2026
    from tradingagents.positions_view import fmt_when

    assert got["first"] == fmt_when(H0 / 1000) and got["last"].endswith(("am", "pm"))
    # and the SAME question of the v1 store answers that it has no candles
    v1 = msw.trades_for("XPIN", "1h", signal="ote", th=0.0, sl=3.0, tp=1.0,
                        sizing="flat")
    assert not v1.get("log") and "no candles" in v1["why"]


def test_the_v2_days_window_re_measures_from_the_minutes(v2, monkeypatch):
    row = {"id": "X", "coin": "XPIN", "tf": "1h", "signal": "ote", "th": 0.0,
           "sl": 3.0, "tp": 1.0, "sizing": "flat", "base": 5.0, "trades": 1,
           "profit": 0.9, "last_ms": H0 + 69 * 3_600_000}
    # "now" is five days after the frame, so a 10-day window holds all of it
    # (the window is cut at the row's own last bar, never at the clock)
    import time as _time

    monkeypatch.setattr(_time, "time", lambda: (H0 + 5 * 86_400_000) / 1000)
    got = msw.window_rows([dict(row)], 10, store=v2)
    r = got["rows"][0]
    assert r.get("restated") is True, got
    assert r["w_trades"] == 1 and r["w_wins"] == 1, "minute order: TP first"
    without = msw.window_rows([dict(row)], 10)
    assert without["skipped"]["no_candles"] == 1, "v1 has no XPIN candles"


def test_a_row_deployed_from_v2_keeps_its_v2_id():
    from tradingagents import api, backtest_report as br

    key = "ote_1h_sl3tp1"
    assert key in at.STRATEGY_SPECS, "the operator's own strategy key"
    v1_id = api.row_id_for(key, "XPIN_USDT", {})
    assert v1_id == br.row_code("XPIN", "1h", "ote", 0.0, 3.0, 1.0, "flat")
    slot = at.book_slot(key, "XPIN_USDT")
    v2_id = api.row_id_for(key, "XPIN_USDT", {"strategy_res": {slot: "1m"}})
    assert v2_id == br.row_code("XPIN", "1h", "ote", 0.0, 3.0, 1.0, "flat", res="1m")
    assert v2_id != v1_id


def test_a_preset_row_from_v2_writes_strategy_res():
    from tradingagents import deploy_preset as dp

    key = "ote_1h_sl3tp1"
    preset = {"strategies": {key: {"coins": ["XPIN_USDT"], "res": "1m"}},
              "base_margin": 5.0}
    out = dp.merged(preset, {"strategies": [], "strategy_coins": {}})
    assert out["strategy_res"] == {at.book_slot(key, "XPIN_USDT"): "1m"}
    # a v1 row writes nothing there
    out1 = dp.merged({"strategies": {key: {"coins": ["XPIN_USDT"]}}}, {})
    assert out1["strategy_res"] == {}


def test_the_v2_update_job_dispatches_the_fleet_and_continues():
    """It ran HERE until Sep 21, 2026, because the fleet had no 1-minute
    candles; it downloads its own now, so v2's UPDATE goes to GitHub exactly
    as v1's does. What has not changed, and is the real point of this test:
    UPDATE CONTINUES each pair from its saved position and never re-measures
    from scratch, and it is its own job kind writing its own files."""
    from tradingagents import db_jobs as dj

    src = inspect.getsource(dj._run_btupdate_v2)
    assert 'mode="update"' in src, "UPDATE continues, never from scratch"
    assert 'res="1m"' in src, "and it is a v2 run"
    # EVERY ACCOUNT since de4ed7a86771 ("i want 40", Sep 21, 2026): the v2
    # update deals its coins across the operator's and the partner's fleets
    assert "cs.dispatch_across(" in src and "_run_backtest(" not in src
    assert "cap.plan" not in src, \
        "v2 keeps NO frames, so there is nothing to split and no plan to make"
    assert "btupdate_v2" in dj.FILES and "btupdate_v2" in dj._DISK_JOBS
    assert dj.main.__code__.co_consts and "btupdate_v2" in inspect.getsource(dj.main)


def test_the_v2_trades_route_and_window_answer(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from tests.test_v2_store_is_its_own_folder import _row, _seed
    from tradingagents import api as api_mod, rows_index as ri

    v2 = stores.Store(name="v2", home=tmp_path / "v2", candles=tmp_path / "v2" / "candles",
                      rows_db=tmp_path / "v2" / "rows.db", parquet=tmp_path / "parquet-v2",
                      fine_tf="1m", download_kind="download_v2", backtest_kind="backtest_v2")
    monkeypatch.setattr(stores, "V2", v2)
    monkeypatch.setitem(stores._BY_NAME, "v2", v2)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "v1" / "rows.db")
    _seed(v2.rows_db, [_row("XPIN", 99.0, unclear=0, res="1m")])
    v2.candles.mkdir(parents=True)
    c = TestClient(api_mod.app)
    # a days window is answered now (it re-measures from the v2 store; with no
    # 1m candles seeded here the row is skipped as no_candles, not refused)
    r = c.get("/api/v2/strategies?coin=XPIN&days=30&limit=10")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["days"] == 30 and d["store"] == "v2"
    assert d["window_skipped"].get("no_candles") == 1
    # the trade-log route exists for v2
    r2 = c.post("/api/v2/strategies/trades", json={
        "coin": "XPIN", "tf": "1h", "signal": "ote", "th": 0.0, "sl": 3.0,
        "tp": 1.0, "sizing": "flat", "base_margin": 5.0})
    assert r2.status_code == 200
    assert "log" in r2.json()
