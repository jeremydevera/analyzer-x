"""Crypto coins vs tokenized stocks — a filter on the coin's own name.

Operator, 2026-09-05: *"create a filter in backtest to select crypto coins and
tokenized stocks"* — right after finding that 6 of their 9 deployed coins are
tokenized stocks (STOCK-suffix contracts) whose books go quiet outside US
market hours. MEXC names every tokenized stock with a STOCK suffix, so the
name IS the split: GPNSTOCK/PSXSTOCK are stocks, KITE/STBL are crypto.
"""
import json

import pytest

from tradingagents import market_sweep as msw, rows_index as ri

PANEL = "webapp/src/components/backtest/StrategiesPanel.tsx"
API_TS = "webapp/src/lib/api.ts"


def _row(coin, signal="scalp", tp=1.0, sl=1.0, profit=10.0, tf="1h"):
    trades, winrate = 120, 60.0
    wins = round(trades * winrate / 100)
    return {"coin": coin, "tf": tf, "signal": signal, "th": 0.1, "sl": sl,
            "tp": tp, "rr": 1.0, "sizing": "flat", "lev": 20, "base": 5.0,
            "notional": 100.0, "trades": trades, "wins": wins,
            "losses": trades - wins, "winrate": winrate, "profit": profit,
            "funding": -0.2, "h1": profit / 2, "h2": profit / 2, "green": 8,
            "months": 12, "worst": -4.1, "dd": 22.0, "liqs": 0,
            "stop_reachable": True, "days": 360, "bars": 34000,
            "monthly": {"2026-08": profit / 3}, "cost_of_tp": 12.5,
            "rt": 0.04, "gate": "ok"}


def _settled(**kw):
    import time

    return ri.sync(now=time.time() + ri.SETTLE_S + 1, **kw)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Two stocks, two crypto coins — including one whose name merely
    CONTAINS the letters (WOODSTOCKED would be a stock only if the suffix
    rule is a real suffix rule, which LIKE '%STOCK' is: it anchors the END)."""
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    (rows_dir / "GPNSTOCK-1h.json").write_text(
        json.dumps([_row("GPNSTOCK", profit=50.0)]))
    (rows_dir / "PSXSTOCK-1h.json").write_text(
        json.dumps([_row("PSXSTOCK", profit=40.0)]))
    (rows_dir / "KITE-1h.json").write_text(
        json.dumps([_row("KITE", profit=30.0)]))
    (rows_dir / "STBL-1h.json").write_text(
        json.dumps([_row("STBL", profit=20.0)]))
    _settled()
    return None


# ------------------------------------------------------------------ the SQL

def test_stocks_keeps_only_the_STOCK_suffix(store):
    got = ri.query(asset="stocks")
    assert sorted(r["coin"] for r in got["rows"]) == ["GPNSTOCK", "PSXSTOCK"]
    assert got["total"] == 2


def test_crypto_excludes_every_stock(store):
    got = ri.query(asset="crypto")
    assert sorted(r["coin"] for r in got["rows"]) == ["KITE", "STBL"]
    assert got["total"] == 2


def test_no_asset_means_everything(store):
    got = ri.query()
    assert got["total"] == 4
    assert got["asset"] == ""


def test_the_COUNT_knows_about_asset(store):
    """from_pairs totals pair row-counts, which cannot see inside a pair; a
    filter missing from its exclusion list prints '4 match' over 2 rows —
    the exact bug the tp_over_sl checkbox shipped with on 2026-09-04."""
    for kw in ({"asset": "stocks"}, {"asset": "crypto"}):
        got = ri.query(**kw)
        assert got["total"] == len(got["rows"]), (kw, got["total"])


def test_asset_stacks_with_the_other_filters_as_AND(store):
    got = ri.query(asset="stocks", coin="KITE")
    assert got["total"] == 0 and got["rows"] == []


def test_a_wrong_value_is_refused_not_ignored():
    """A typo that silently matched EVERYTHING would put a wrong caption over
    a full table (label-must-match-data)."""
    with pytest.raises(ValueError, match="crypto or stocks"):
        ri._where(asset="junk")


def test_the_echo_names_the_asset(store):
    assert ri.query(asset="stocks")["asset"] == "stocks"


def test_the_csv_walks_the_same_filter(store):
    rows = list(ri.iter_rows(asset="crypto"))
    assert sorted(r["coin"] for r in rows) == ["KITE", "STBL"]


# ------------------------------------------------------------------- the API

def test_the_route_and_the_csv_carry_asset():
    a = open("tradingagents/api.py", encoding="utf-8").read()
    assert a.count("asset: str | None = None") == 2, "rows route AND csv route"
    assert "tp_over_sl=tp_over_sl, asset=asset or None)" in a
    assert "tp_over_sl=tp_over_sl, asset=asset):" in a
    assert 'str(asset or ""),' in a, "the download's filename names the filter"


# -------------------------------------------------------------------- the UI

def test_the_panel_has_the_dropdown_and_its_chip():
    p = open(PANEL, encoding="utf-8").read()
    assert 'aria-label="Asset kind"' in p
    for opt in ("coins and stocks", "crypto coins only",
                "tokenized stocks only"):
        assert f">{opt}</option>" in p, opt
    # the chip the AND-line prints, one text per direction
    assert 'text: "Crypto coins only"' in p
    assert 'text: "Tokenized stocks only"' in p
    # the AND-line (the spinner's "asking …" and the filter sentence) names
    # the kind, on or off: a slow crypto-only request once waited under a
    # line that never said crypto, and the operator read that as "the crypto
    # coins only filter is not working" (2026-09-06)
    assert 'f.asset === "crypto" ? "crypto coins only"' in p
    assert '"coins and stocks",' in p
    # cleared with the rest, sent with the rest, kept for the CSV
    assert p.count('asset: ""') >= 3, "NO_FILTERS + applied + servedFilters"
    assert "asset: setAsset" in p
    assert p.count('"crypto" | "stocks" | undefined') == 2, "load call + CSV"


def test_the_browser_api_sends_the_param():
    t = open(API_TS, encoding="utf-8").read()
    assert t.count('if (q.asset) p.set("asset", q.asset);') == 2, \
        "the table's query AND the CSV url"
    assert t.count('asset?: "crypto" | "stocks";') == 2
