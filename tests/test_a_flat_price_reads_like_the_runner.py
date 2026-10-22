"""On a price that does not move, the backtest takes the side the runner takes,
and every replay of a Gate row reads the candles GitHub read (Oct 18, 2026).

Room #6B08FF64 switched on UNIS_USDT 15m trend50 (target 3%, stop 0.4%) by its
stored row: 58 trades, 35 wins, +$61.80 from Sep 18 to Oct 18, 2026 3:30am. A
click on that row listed 30 trades, 7 wins, -$13.26 — the same candles, the
same order books, the same code. UNIS is a stock token: most of its 15-minute
candles sit flat with no trade at all (4.186 from Oct 14, 2026 3:30am to
9:45am). trend50 asks "is the close above its 50-candle average?". The runner
works the average out fresh from the last 50 closes (`sig_trend50`); the
backtest kept a running total, adding the newest close and taking away the
oldest at every candle. On a flat price the close IS the average, so the
running total's rounding error decided the side, and the side depended on how
many candles came before: 1,210 of the 2,879 candles in the row's window read
the other way when the walk started on Aug 06 instead of GitHub's 300 candles
of lead-in. And three replays read a different history from GitHub's: the
trade list a click shows (every saved candle, back to Aug 06), the DEMO 30-day
figure the watcher switches off by (about 400 candles of lead-in) and the
last-N-days view (every saved candle). Four more rules move with history on a
flat price (stochrsi up to 40 candles of 2,879, ao 37, cf_triple 2, bb20 1):
the replays now read GitHub's history, so the list adds up to its row.
"""
import json
import random

import numpy as np
import pandas as pd
import pytest

from tradingagents import auto_trader as at, market_sweep as msw, stores

H0 = 1_789_516_800_000            # Sep 16, 2026 00:00 UTC


def _stock_token_closes(seed: int = 7) -> list:
    """A stock token's closes: a few prints that move it, then hours in
    which nothing trades and every candle repeats the last price — UNIS's
    shape (4.186, three decimals, flat for six hours at a time)."""
    rng = random.Random(seed)
    px, out = 4.186, []
    for _ in range(14):
        for _ in range(rng.randint(5, 40)):
            px = round(px * (1 + rng.uniform(-0.01, 0.01)), 3)
            out.append(px)
        out += [px] * rng.randint(60, 400)
    return out


def test_trend50_takes_the_runners_side_on_every_candle_of_a_flat_price():
    """The grid's per-candle trend50 against the runner's own function, at
    every candle, on a price that sits still for hours. Random walks (the
    older parity test) never repeat a price exactly, so they could not see a
    side decided by rounding error."""
    for seed in (7, 11, 23):
        closes = _stock_token_closes(seed)
        hl = list(closes)
        dirs = at._dirs_for_backtest("trend50", hl, hl, closes)
        bad = [i for i in range(49, len(closes))
               if dirs[i] != at.signal_for("trend50", hl[:i + 1], hl[:i + 1],
                                           closes[:i + 1])]
        assert not bad, (f"seed {seed}: {len(bad)} of {len(closes) - 49} candles "
                         f"take the other side from the runner (first at {bad[0]})")


def test_trend50_reads_the_same_side_whatever_history_came_before():
    """GitHub reads 300 candles before the window; this PC's saved history
    goes back months. The side at a candle may depend only on the 50 closes
    that make its average."""
    closes = _stock_token_closes(5)
    hl = list(closes)
    whole = at._dirs_for_backtest("trend50", hl, hl, closes)
    k = len(closes) - 900
    tail = at._dirs_for_backtest("trend50", hl[k:], hl[k:], closes[k:])
    assert whole[k + 49:] == tail[49:]


# -------------------------------------------------- the replays of a Gate row


def _gate_store(tmp_path, monkeypatch):
    monkeypatch.setenv("TA_VENUE", "gate")
    home = tmp_path / "v2"
    st = stores.Store(name="v2", home=home, candles=home / "candles",
                      rows_db=home / "rows.db", parquet=tmp_path / "parquet-v2",
                      fine_tf="1m", download_kind="download_v2",
                      backtest_kind="backtest_v2")
    for d in ("candles", "rows", "state"):
        (home / d).mkdir(parents=True, exist_ok=True)
    msw._DIRS_CACHE.clear()
    return st, home


def _hours(n: int, t0: int = H0) -> pd.DataFrame:
    t = [t0 + k * 3_600_000 for k in range(n)]
    px = 100 + np.sin(np.arange(n) / 7.0) * 3
    return pd.DataFrame({"Date": pd.to_datetime(t, unit="ms"), "Open": px,
                         "High": px * 1.01, "Low": px * 0.99, "Close": px,
                         "Volume": 1.0})


def _row(last_ms: int, bars: int) -> dict:
    return {"coin": "TEST", "tf": "1h", "signal": "mom6", "th": 0.3, "sl": 1.0,
            "tp": 2.0, "sizing": "flat", "trades": 1, "wins": 1, "losses": 0,
            "profit": 0.9, "bars": bars, "last_ms": last_ms, "fee": 0.00075,
            "res": "1m", "reenter": True}


def _read_lengths(monkeypatch) -> list:
    """Every history `_dirs_for_backtest` is handed: (candles, last open ms)."""
    seen = []

    def dirs(key, hi, lo, cl, **k):
        ts = k.get("ts") or []
        seen.append((len(cl), int(ts[-1]) if ts else None))
        return [0] * len(cl)
    monkeypatch.setattr(at, "_dirs_for_backtest", dirs)
    return seen


@pytest.mark.parametrize("n, bars, lead", [(1000, 200, 300),   # the shard's 300
                                           (400, 300, 99),     # all there was
                                           # a 30-day row on DAILY candles has
                                           # 30 (RCA-2026-10-22-H: #AYWGYUEG
                                           # MINA 1d, 20 trades in the row, 88
                                           # listed - every saved day walked)
                                           (400, 30, 300)])
def test_a_gate_rows_trade_list_reads_the_history_github_read(tmp_path, monkeypatch,
                                                              n, bars, lead):
    """`sweep_shard.window`: the row's own candles and up to GATE_WARMUP_BARS
    before them — never every candle this PC has saved."""
    from tradingagents import cost_store

    st, home = _gate_store(tmp_path, monkeypatch)
    frame = _hours(n)
    last_ms = H0 + (n - 2) * 3_600_000          # the newest candle came after it
    (home / "rows" / "TEST-1h.json").write_text(json.dumps([_row(last_ms, bars)]))
    (home / "state" / "TEST-1h.json").write_text(json.dumps({"__last_ms__": last_ms}))
    msw.save_costs("TEST_USDT", fee=0.00075, liq=4.5, funding=[], root=str(home))
    no_fine = (np.zeros(0, "int64"), np.zeros(0), np.zeros(0))
    monkeypatch.setattr(msw, "gate_v2_bars", lambda sym, tf: (frame, no_fine, 0))
    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: cost_store.empty())
    seen = _read_lengths(monkeypatch)
    got = msw.trades_for("TEST", "1h", signal="mom6", th=0.3, sl=1.0, tp=2.0,
                         sizing="flat", store=st)
    assert "why" not in got, got.get("why")
    assert seen == [(bars + lead, last_ms)]
    assert got["bars"] == bars, "the walk itself still covers the row's own candles"


def test_the_demo_figure_of_a_gate_row_reads_the_history_github_read(tmp_path, monkeypatch):
    """`rolling30.rebuild` asked for the row's candles plus 400 and read all
    of them, so its signal had 100 candles more history than the row's."""
    from tradingagents import backtest_report as br, cost_store, rolling30 as r30
    from tradingagents.dataflows import gate_futures as gf

    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    r30._MEMO.clear()
    n, bars = 1000, 300
    # candles that have CLOSED by now: the rebuild reads closed candles only
    import time as _time

    t0 = (int(_time.time()) // 3600 - 3) * 3_600_000 - (n - 1) * 3_600_000
    frame = _hours(n, t0)
    wm = t0 + (n - 1) * 3_600_000
    row = {"trades": 0, "wins": 0, "profit": 0.0, "bars": bars, "fee": 0.00075,
           "rt": 0.21, "book_to": wm // 1000}
    ident = {"key": "mom6_1h_sl1tp2", "tf": "1h", "sym": "TEST_USDT", "tp": 2.0,
             "sl": 1.0, "res": "1m", "coin": "TEST", "store": None}
    monkeypatch.setitem(at.STRATEGY_SPECS, "mom6_1h_sl1tp2",
                        {"interval": "Min60", "bar_seconds": 3600, "tp": 0.02,
                         "sl": 0.01, "threshold": 0.003})
    monkeypatch.setattr(r30, "_identity", lambda settings, slot: ident)
    monkeypatch.setattr(r30, "_stored", lambda i: (row, wm))
    monkeypatch.setattr(gf, "klines", lambda *a, **k: frame)
    monkeypatch.setattr(gf, "funding_history", lambda *a, **k: [])
    monkeypatch.setattr(gf, "liquidation_move_pct", lambda *a, **k: 4.5)
    monkeypatch.setattr(br, "fine_bars", lambda *a, **k: (np.zeros(0, "int64"),
                                                          np.zeros(0), np.zeros(0), 0))
    monkeypatch.setattr(cost_store, "book_for", lambda *a, **k: cost_store.empty())
    seen = _read_lengths(monkeypatch)
    starts = []
    real = at.backtest_strategy

    def spy(key, df, *a, **k):
        starts.append((len(df), k.get("start_at")))
        return real(key, df, *a, **k)
    monkeypatch.setattr(at, "backtest_strategy", spy)
    r30.rebuild("mom6_1h_sl1tp2|TEST_USDT", {})
    assert seen == [(bars + 300, wm)]
    assert starts == [(bars + 300, 300)], "no trade inside the lead-in"


def test_the_last_n_days_view_of_a_gate_row_reads_the_history_github_read(tmp_path, monkeypatch):
    from tradingagents import cost_store

    st, home = _gate_store(tmp_path, monkeypatch)
    n, bars = 1000, 600
    frame = _hours(n)
    last_ms = H0 + (n - 1) * 3_600_000
    (home / "state" / "TEST-1h.json").write_text(json.dumps({"__last_ms__": last_ms}))
    msw.save_costs("TEST_USDT", fee=0.00075, liq=4.5, funding=[], root=str(home))
    no_fine = (np.zeros(0, "int64"), np.zeros(0), np.zeros(0))
    monkeypatch.setattr(msw, "gate_v2_bars", lambda sym, tf: (frame, no_fine, 0))
    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: cost_store.empty())
    import time as _time

    monkeypatch.setattr(_time, "time", lambda: last_ms / 1000 + 3600)
    seen = _read_lengths(monkeypatch)
    row = {**_row(last_ms, bars), "id": "X", "base": 5.0}
    msw.window_rows([row], 10, store=st)
    assert seen == [(bars + 300, last_ms)]


def test_the_replays_lead_in_is_the_shards():
    """The replays cut their history at GATE_WARMUP_BARS because that is what
    GitHub's shard reads (`sweep_shard.WARMUP_BARS`); if one moves alone,
    every Gate row's trade list stops adding up to it."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / ".github" / "scripts"
           / "sweep_shard.py").read_text(encoding="utf-8")
    shard = [n.value.value for n in ast.parse(src).body
             if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "WARMUP_BARS"
                                                  for t in n.targets)]
    assert shard == [msw.GATE_WARMUP_BARS]


def _slippage_charged(monkeypatch) -> list:
    seen = []
    real = at.backtest_strategy

    def spy(key, df, *a, **k):
        seen.append(k.get("slippage"))
        return real(key, df, *a, **k)
    monkeypatch.setattr(at, "backtest_strategy", spy)
    return seen


def test_a_gate_rows_trade_list_charges_the_rows_own_cost(tmp_path, monkeypatch):
    """GitHub charged UNIS_USDT its usual cost off the live book and kept it
    in the row (`rt` 1.6392 = 2 x (0.075% fee + 0.7446%)). This PC's cost
    file is written by the click itself, with no slippage, so a minute with
    no book reading paid 0.03% here: the list took trades the row refused,
    and 8 of 18 rows on three stock tokens did not add up to their own list
    (Oct 18, 2026)."""
    from tradingagents import cost_store

    st, home = _gate_store(tmp_path, monkeypatch)
    frame = _hours(1000)
    last_ms = H0 + 998 * 3_600_000
    row = {**_row(last_ms, 200), "rt": 1.6392}
    row.pop("fee")                       # GitHub's v2 rows carry no fee
    (home / "rows" / "TEST-1h.json").write_text(json.dumps([row]))
    (home / "state" / "TEST-1h.json").write_text(json.dumps({"__last_ms__": last_ms}))
    msw.save_costs("TEST_USDT", fee=0.00075, liq=4.5, funding=[], root=str(home))
    no_fine = (np.zeros(0, "int64"), np.zeros(0), np.zeros(0))
    monkeypatch.setattr(msw, "gate_v2_bars", lambda sym, tf: (frame, no_fine, 0))
    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: cost_store.empty())
    seen = _slippage_charged(monkeypatch)
    msw.trades_for("TEST", "1h", signal="mom6", th=0.3, sl=1.0, tp=2.0,
                   sizing="flat", store=st)
    assert seen == [pytest.approx(1.6392 / 100 / 2 - 0.00075)]


def test_the_last_n_days_view_of_a_gate_row_charges_the_rows_own_cost(tmp_path, monkeypatch):
    from tradingagents import cost_store

    st, home = _gate_store(tmp_path, monkeypatch)
    n = 1000
    frame = _hours(n)
    last_ms = H0 + (n - 1) * 3_600_000
    (home / "state" / "TEST-1h.json").write_text(json.dumps({"__last_ms__": last_ms}))
    msw.save_costs("TEST_USDT", fee=0.00075, liq=4.5, funding=[], root=str(home))
    no_fine = (np.zeros(0, "int64"), np.zeros(0), np.zeros(0))
    monkeypatch.setattr(msw, "gate_v2_bars", lambda sym, tf: (frame, no_fine, 0))
    monkeypatch.setattr(cost_store, "engine_book", lambda *a, **k: cost_store.empty())
    import time as _time

    monkeypatch.setattr(_time, "time", lambda: last_ms / 1000 + 3600)
    seen = _slippage_charged(monkeypatch)
    rows = [{**_row(last_ms, 600), "id": "X", "base": 5.0, "rt": 1.6392},
            {**_row(last_ms, 600), "id": "Y", "base": 5.0, "rt": 2.496, "tp": 3.0}]
    for r in rows:
        r.pop("fee")
    msw.window_rows(rows, 10, store=st)
    assert seen == [pytest.approx(1.6392 / 200 - 0.00075), pytest.approx(2.496 / 200 - 0.00075)]
