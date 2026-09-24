"""Backtest v2's "last N days" CSV re-measures on the v2 store — every time.

RCA-2026-09-24-E. The operator: *"when i download csv 5JWGQZPG has 100%
winrate but but in ui its 96% winrate"*. The screen was right (28 trades,
27W/1L, 96.43%, Aug 25 -> Sep 22). The CSV re-measured the row on the V1
candles, which stop at Sep 15, 2026 5:30pm for GPNSTOCK 30m — 23 trades,
23W/0L, 100% — and never saw the Sep 17 1:00pm short that lost $2.23.

Why: `iter_rows`, called for another store, re-entered itself through
`iter_rows_in(...)` with a HAND-WRITTEN argument list, and `store` was added
to `iter_rows` on Sep 18, 2026 without being added to that list. The
re-entered walk ran with `store=None`, and `window_rows(store=None)` reads the
v1 candle cache.

These tests go through the branch that dropped it (a db_path that is not the
current store), which every earlier CSV test skipped by using the default
store — that is why none of them could see it.
"""
from __future__ import annotations

import inspect

import pytest

from tests.test_v2_routes import client  # noqa: F401  (the v2 route fixture)
from tests.test_v2_store_is_its_own_folder import _row, _seed
from tradingagents import market_sweep as msw, rows_index as ri


def test_every_argument_survives_the_hand_off(tmp_path, monkeypatch):
    """STRUCTURAL: whatever `iter_rows` is given, the re-entered walk gets.

    Driven through the real hand-off with a value for EVERY parameter, so a
    parameter added next month is covered without anyone editing this test.
    """
    seen: dict = {}

    def fake_in(**kw):
        seen.update(kw)
        return iter(())

    monkeypatch.setattr(ri, "iter_rows_in", fake_in)
    params = [p for p in inspect.signature(ri.iter_rows).parameters]
    given = {name: object() for name in params}      # a unique marker each
    given["db_path"] = tmp_path / "another-store.db"  # takes the hand-off
    list(ri.iter_rows(**given))

    dropped = [n for n in params if n not in seen]
    assert not dropped, f"the hand-off dropped {dropped}"
    changed = [n for n in params if n != "db_path" and seen[n] is not given[n]]
    assert not changed, f"the hand-off changed {changed}"
    assert str(seen["db_path"]) == str(given["db_path"])


def test_the_v2_csv_re_measures_with_the_v2_store(client, monkeypatch):  # noqa: F811
    """BEHAVIOURAL, through the real route: the window's re-measure is handed
    the v2 store — the object that points it at the 1-minute candles — never
    None, which is v1's candle cache."""
    c, v2 = client
    _seed(v2.rows_db, [_row("XPIN", 99.0, res="1m")])
    got: list = []

    def spy(rows, days, *a, **kw):
        got.append(kw.get("store"))
        for r in rows:
            r.update(restated=True, w_trades=1, w_wins=1, w_losses=0,
                     w_winrate=100.0, w_profit=1.0, w_first="Aug 25, 2026 12:30am",
                     w_last="Sep 22, 2026 12:30am", w_days=28.0, w_straddle=0)
        return {"rows": rows, "first": "", "last": "", "groups": 1,
                "skipped": {"no_candles": 0, "outside_window": 0, "failed": 0},
                "straddled": 0}

    monkeypatch.setattr(msw, "window_rows", spy)
    r = c.get("/api/v2/strategies.csv?coin=XPIN&days=30")
    assert r.status_code == 200, r.text[:300]
    assert got, "the window was never re-measured"
    assert all(s is v2 for s in got), \
        f"the v2 CSV re-measured with store={got!r} — None means the v1 candles"


def test_the_v1_csv_still_uses_its_own_store(client, tmp_path, monkeypatch):  # noqa: F811
    """The default store never takes the hand-off and keeps store=None."""
    c, _ = client
    _seed(tmp_path / "v1" / "rows.db", [_row("XPIN", 10.0)])
    got: list = []

    def spy(rows, days, *a, **kw):
        got.append(kw.get("store"))
        return {"rows": rows, "first": "", "last": "", "groups": 1,
                "skipped": {"no_candles": 0, "outside_window": 0, "failed": 0},
                "straddled": 0}

    monkeypatch.setattr(msw, "window_rows", spy)
    r = c.get("/api/strategies.csv?coin=XPIN&days=30")
    assert r.status_code == 200, r.text[:300]
    assert got and all(s is None for s in got), got


# ---------------------------------------------------------------------------
# THE WHOLE CHAIN. `store` was dropped at ONE hand-written pass-through; there
# are three more between the screen and the re-measure, each listing its
# arguments by hand. Every one is driven here with a DISTINCT value per
# parameter, so a filter that is added to one layer and forgotten at the next
# fails a test instead of silently doing nothing on Backtest v2.
# ---------------------------------------------------------------------------

def _markers(fn, skip=()):
    """A distinct value per parameter, typed so the code under test accepts it."""
    out = {}
    for i, (name, p) in enumerate(inspect.signature(fn).parameters.items()):
        if name in skip:
            continue
        d = p.default
        if isinstance(d, bool) or name in ("profitable", "tp_over_sl"):
            out[name] = True
        elif isinstance(d, int) and not isinstance(d, bool):
            out[name] = 100 + i
        elif isinstance(d, float):
            out[name] = 100.5 + i
        else:
            out[name] = f"m{i}-{name}"
    return out


def test_v2_table_and_v1_table_accept_the_same_filters():
    """A filter added to the v1 screen and not to v2's is a box on the v2
    panel that does nothing."""
    from tradingagents import api

    v1 = set(inspect.signature(api.strategies).parameters)
    v2 = set(inspect.signature(api.strategies_v2).parameters)
    assert v1 == v2, f"only v1: {sorted(v1 - v2)} · only v2: {sorted(v2 - v1)}"
    c1 = set(inspect.signature(api.strategies_csv).parameters)
    c2 = set(inspect.signature(api.strategies_csv_v2).parameters)
    assert c1 == c2, f"only v1 csv: {sorted(c1 - c2)} · only v2 csv: {sorted(c2 - c1)}"


def test_the_v2_table_route_forwards_every_filter(tmp_path, monkeypatch):
    from tradingagents import api

    seen: dict = {}

    def fake_strategies(**kw):
        seen.update(kw)
        return {"rows": [], "total": 0}

    monkeypatch.setattr(api, "_v2_rows_db", lambda: tmp_path / "rows.db")
    monkeypatch.setattr(api, "strategies", fake_strategies)
    monkeypatch.setattr(api, "index_status_v2", lambda: {})
    given = _markers(api.strategies_v2)
    given["desc"] = True
    api.strategies_v2(**given)
    lost = {k: v for k, v in given.items() if seen.get(k) != v}
    assert not lost, f"/api/v2/strategies did not forward {lost}"


def test_the_v2_csv_route_forwards_every_filter_and_the_v2_store(tmp_path, monkeypatch):
    from tradingagents import api, stores

    seen: dict = {}

    def fake_lines(**kw):
        seen.update(kw)
        return iter(())

    monkeypatch.setattr(api, "_v2_rows_db", lambda: tmp_path / "rows.db")
    monkeypatch.setattr(api, "strategies_csv_lines", fake_lines)
    monkeypatch.setattr(ri, "export_plan", lambda **kw: None)
    monkeypatch.setattr(api, "strategies_csv_name", lambda *a, **k: "x.csv")
    given = _markers(api.strategies_csv_v2)
    given["months"] = 0          # a months window is refused on v2, by design
    given["desc"] = True
    api.strategies_csv_v2(**given)
    lost = {k: v for k, v in given.items() if k != "months" and seen.get(k) != v}
    assert not lost, f"/api/v2/strategies.csv did not forward {lost}"
    assert seen.get("store") is stores.V2, seen.get("store")
    assert str(seen.get("db_path")) == str(tmp_path / "rows.db")


def test_the_csv_builder_forwards_every_filter_to_the_walker(monkeypatch):
    """strategies_csv_lines -> iter_rows: every parameter they share arrives."""
    from tradingagents import api

    seen: dict = {}
    # the REAL walker's parameters, read BEFORE it is replaced — the first
    # draft read them off the stand-in (`**kw`), so `shared` was empty and the
    # test passed with `store` dropped; a deliberate break in a scratch copy
    # is what showed it
    shared = (set(inspect.signature(api.strategies_csv_lines).parameters)
              & set(inspect.signature(ri.iter_rows).parameters))
    assert {"store", "db_path", "days", "min_winrate"} <= shared, shared

    def fake_iter(**kw):
        seen.update(kw)
        return iter(())

    monkeypatch.setattr(ri, "iter_rows", fake_iter)
    monkeypatch.setattr(api, "_download_started", lambda label: {})
    monkeypatch.setattr(api, "_download_ended", lambda *a, **k: None, raising=False)
    given = _markers(api.strategies_csv_lines, skip=("_dl",))
    given["desc"] = True
    given["store"] = object()
    # the full export's two (Sep 25, 2026): a lookup is any callable, a cap
    # is a number the builder does arithmetic with
    given["window_lookup"] = object()
    given["window_cap"] = 12345
    list(api.strategies_csv_lines(**given))
    lost = sorted(k for k in shared if k in given and seen.get(k) != given[k]
                  and seen.get(k) is not given[k])
    assert not lost, f"strategies_csv_lines did not forward {lost} to iter_rows"
