"""Stored strategies: "MEXC only (not on OKX)".

Operator, Oct 09, 2026: "what if in backtest Stored strategies, just add filter
'Show mexc coin only' meaning show coins that exist in mexc that are not
existing in okx". The filter is a value of the kind box (`asset`), so the
table, its exact count, the CSV and the full export all carry it the way they
already carry crypto / stocks. No test asks a real exchange.
"""
import json
import time

import pytest

from tradingagents import market_sweep as msw, rows_index as ri, venues

PANEL = "webapp/src/components/backtest/StrategiesPanel.tsx"
API_TS = "webapp/src/lib/api.ts"


@pytest.fixture
def lists(monkeypatch):
    """MEXC trades six; OKX lists BTC, GME (a stock perpetual) and DASH (the coin)."""
    venues._MEM.clear()
    monkeypatch.setattr(venues, "_fetch_mexc", lambda: ["BTC", "KITE", "GMESTOCK", "DASHSTOCK", "GPNSTOCK", "STBL"])
    monkeypatch.setattr(venues, "_fetch_okx", lambda: ["BTC", "DASH", "GME"])
    yield
    venues._MEM.clear()


def test_a_coin_is_mexc_only_when_okx_lists_no_contract_for_it(lists):
    assert venues.mexc_only() == ["KITE", "DASHSTOCK", "GPNSTOCK", "STBL"]
    okx = set(venues.lists()["okx"])
    assert venues.on_okx("GMESTOCK", okx), "GME's stock perpetual"
    assert not venues.on_okx("DASHSTOCK", okx), "OKX's DASH is the coin, not DoorDash"


def test_the_lists_are_read_once_a_day_and_kept_beside_the_store(lists, monkeypatch):
    calls = []
    real = venues._fetch_okx
    monkeypatch.setattr(venues, "_fetch_okx", lambda: calls.append(1) or real())
    now = time.time()
    venues.lists(now)
    venues.lists(now + 3600)
    assert len(calls) == 1, "a filter never waits on two exchanges every ask"
    assert json.loads((msw.HOME / "venues.json").read_text())["okx"] == ["BTC", "DASH", "GME"]
    venues.lists(now + venues.TTL_S + 1)
    assert len(calls) == 2, "a day later it reads them again"


def test_a_failed_refresh_keeps_the_last_good_lists_and_says_how_old(lists, monkeypatch):
    now = time.time()
    venues.lists(now)

    def down():
        raise OSError("okx is down")
    monkeypatch.setattr(venues, "_fetch_okx", down)
    got = venues.lists(now + venues.TTL_S + 1)
    assert got["okx"] == ["BTC", "DASH", "GME"] and "okx is down" in got["stale"]


def test_with_no_lists_at_all_the_filter_refuses_by_name(monkeypatch):
    venues._MEM.clear()

    def down():
        raise OSError("no network")
    monkeypatch.setattr(venues, "_fetch_okx", down)
    monkeypatch.setattr(venues, "_fetch_mexc", lambda: ["KITE"])
    with pytest.raises(ValueError, match="cannot tell which coins OKX lists"):
        venues.mexc_only()
    venues._MEM.clear()


# ------------------------------------------------------------- the table
def _row(coin, profit=10.0):
    return {"coin": coin, "tf": "1h", "signal": "scalp", "th": 0.1, "sl": 1.0, "tp": 1.0, "rr": 1.0,
            "sizing": "flat", "lev": 20, "base": 5.0, "notional": 100.0, "trades": 120, "wins": 72,
            "losses": 48, "winrate": 60.0, "profit": profit, "funding": -0.2, "h1": profit / 2,
            "h2": profit / 2, "green": 8, "months": 12, "worst": -4.1, "dd": 22.0, "liqs": 0,
            "stop_reachable": True, "days": 360, "bars": 34000, "monthly": {"2026-08": profit / 3},
            "cost_of_tp": 12.5, "rt": 0.04, "gate": "ok"}


@pytest.fixture
def store(tmp_path, monkeypatch, lists):
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    for coin, profit in (("BTC", 60.0), ("KITE", 30.0), ("GMESTOCK", 50.0), ("DASHSTOCK", 45.0),
                         ("GPNSTOCK", 40.0), ("STBL", 20.0)):
        (rows_dir / f"{coin}-1h.json").write_text(json.dumps([_row(coin, profit)]))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)


def test_mexc_only_keeps_exactly_the_coins_okx_does_not_list(store):
    got = ri.query(asset="mexc")
    assert sorted(r["coin"] for r in got["rows"]) == ["DASHSTOCK", "GPNSTOCK", "KITE", "STBL"]
    assert got["total"] == 4


def test_mexc_only_with_crypto_or_stocks(store):
    assert sorted(r["coin"] for r in ri.query(asset="mexc_stocks")["rows"]) == ["DASHSTOCK", "GPNSTOCK"]
    assert sorted(r["coin"] for r in ri.query(asset="mexc_crypto")["rows"]) == ["KITE", "STBL"]


def test_the_list_never_drives_the_plan_and_other_kinds_are_refused(lists):
    where, args = ri._where(asset="mexc", order_owns_index=True)
    assert "+coin IN (" in where and len(args) == len(venues.mexc_only())
    with pytest.raises(ValueError, match="unknown asset"):
        ri._where(asset="okx")


# ------------------------------------------------------------- the screen
def test_the_kind_box_offers_it_and_the_chip_and_sentence_name_it():
    src = open(PANEL, encoding="utf-8").read()
    for value in ("mexc", "mexc_crypto", "mexc_stocks"):
        assert f'<option value="{value}">MEXC only (not on OKX):' in src, value
    assert 'mexc: "MEXC only (not on OKX)"' in src and "out.push({ k: \"asset\", text: ASSET_LABEL[f.asset] });" in src
    assert "ASSET_WORDS[f.asset]" in src
    api = open(API_TS, encoding="utf-8").read()
    assert api.count('asset?: "crypto" | "stocks" | "mexc" | "mexc_crypto" | "mexc_stocks";') == 2
