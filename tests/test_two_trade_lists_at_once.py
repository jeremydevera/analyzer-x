"""Two trade lists of one strategy, asked for at the same moment, both answer.

Oct 14, 2026 1:44pm: Backtest v2 asked the site for the trades of #5Z98N2D4
(JASMY 30m cf_soup1) twice inside one second; the first answered, the second
crashed with `KeyError: 'cf_soup1_tf_30m'`. Every trade list borrows ONE
shared recipe name per signal and bar size (`cf_soup1_tf_30m`) for the length
of its replay, and the first replay to finish took the name away while the
second was still using it. A second list with another threshold would not even
have crashed: it would have quietly read the first one's threshold.

The race is made certain here, not hoped for: the first replay is held inside
its signal step until the second has finished (or 2 s have passed), which is
exactly the order the two requests ran in on Oct 14.
"""
from __future__ import annotations

import json
import threading

import pandas as pd
import pytest

import tradingagents.auto_trader as at
from tradingagents import market_sweep as msw
from tradingagents.dataflows import mexc_futures as fx

BAR_MS = 3_600_000


def _frame(n=600, seed=3, start_ms=1_787_000_000_000):
    rows = []
    px, trend = 100.0, 1
    for i in range(n):
        seed = (1103515245 * seed + 12345) % (1 << 31)
        r = (seed / (1 << 31)) - 0.5
        if i % 80 == 0:
            trend = (i // 80 % 3) - 1
        step = px * (0.004 * trend + 0.012 * r)
        o, c = px, px + step
        rows.append({"Date": pd.Timestamp(start_ms + i * BAR_MS, unit="ms"),
                     "Open": round(o, 6),
                     "High": round(max(o, c) * 1.004, 6),
                     "Low": round(min(o, c) * 0.996, 6),
                     "Close": round(c, 6), "Volume": 900.0 + 400 * abs(r)})
        px = c
    return pd.DataFrame(rows)


@pytest.fixture
def store(tmp_path, monkeypatch):
    for name, sub in (("HOME", ""), ("STATES", "state"), ("ROWDIR", "rows"),
                      ("CANDLES", "candles"), ("COSTS", "costs")):
        monkeypatch.setattr(msw, name, tmp_path / sub if sub else tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "rows").mkdir()

    def no_network(*a, **k):
        raise AssertionError("a click must not call the venue")

    monkeypatch.setattr(msw, "refresh_candles", no_network)
    monkeypatch.setattr(fx, "klines", no_network)
    monkeypatch.setattr(fx, "funding_history", no_network)
    monkeypatch.setattr(fx, "liquidation_move_pct", no_network)
    monkeypatch.setattr(at, "taker_fee", no_network)
    df = _frame()
    monkeypatch.setattr(msw, "cached_candles", lambda sym, tf: df)
    msw.save_costs("TEST_USDT", fee=0.0004, liq=4.0, funding=[])
    (msw.STATES / "TEST-1h.json").write_text(json.dumps({
        "__last_ms__": int(df["Date"].iloc[-1].timestamp() * 1000),
        "__version__": "signals120-th3"}))
    return tmp_path


def _ask(th):
    return msw.trades_for("TEST", "1h", signal="mom6", th=th, sl=1.0, tp=2.0,
                          sizing="flat")


def test_a_second_list_of_the_same_strategy_does_not_crash_the_first(store,
                                                                     monkeypatch):
    # alone, each one, first: what each list must say when they overlap
    alone_a, alone_b = _ask(0.1), _ask(2.0)
    assert alone_a["trades"] != alone_b["trades"], \
        "the two thresholds must trade differently, or the overwrite is invisible"

    real = at._dirs_for_backtest
    b_done = threading.Event()
    first = threading.Event()
    lock = threading.Lock()

    def held(*a, **k):
        with lock:
            me_first = not first.is_set()
            first.set()
        if me_first:
            # the FIRST replay waits inside its signal step while the second
            # one runs from start to finish (Oct 14, 2026's order)
            b_done.wait(2.0)
        return real(*a, **k)

    monkeypatch.setattr(at, "_dirs_for_backtest", held)
    got: dict = {}

    def run_a():
        try:
            got["a"] = _ask(0.1)
        except Exception as exc:                               # noqa: BLE001
            got["a"] = exc

    ta = threading.Thread(target=run_a)
    ta.start()
    assert first.wait(5.0)
    try:
        got["b"] = _ask(2.0)
    except Exception as exc:                                   # noqa: BLE001
        got["b"] = exc
    b_done.set()
    ta.join(10.0)

    assert not isinstance(got["a"], Exception), \
        f"the first list crashed: {got['a']!r}"
    assert not isinstance(got["b"], Exception), \
        f"the second list crashed: {got['b']!r}"
    # and neither read the other's threshold
    assert got["a"]["trades"] == alone_a["trades"]
    assert got["a"]["profit"] == alone_a["profit"]
    assert got["b"]["trades"] == alone_b["trades"]
    assert got["b"]["profit"] == alone_b["profit"]
    assert "mom6_tf_1h" not in at.STRATEGY_SPECS, "a borrowed name was left behind"


def test_a_borrowed_name_gives_back_a_recipe_it_found():
    """Borrowing a name a real recipe already holds puts that recipe back,
    never deletes it — the old `pop` would have removed it from the runner."""
    key = next(iter(at.STRATEGY_SPECS))
    real = at.STRATEGY_SPECS[key]
    with at.temp_spec(key, {"interval": "Min60", "bar_seconds": 3600,
                            "tp": .02, "sl": .01, "threshold": .003}):
        assert at.STRATEGY_SPECS[key]["threshold"] == .003
    assert at.STRATEGY_SPECS[key] is real


def test_a_borrowed_name_is_given_back_when_the_replay_raises():
    key = "nosuch_tf_1h"
    with pytest.raises(RuntimeError):
        with at.temp_spec(key, {"threshold": .003}):
            raise RuntimeError("replay failed")
    assert key not in at.STRATEGY_SPECS
    # and the name is free again: a second borrow does not wait for ever
    with at.temp_spec(key, {"threshold": .004}):
        assert at.STRATEGY_SPECS[key]["threshold"] == .004
    assert key not in at.STRATEGY_SPECS
