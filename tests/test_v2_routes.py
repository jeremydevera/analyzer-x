"""The v2 routes answer from the v2 store and say so when it is empty.

One handler per screen, parameterised by `stores.Store`; the v1 route passes
V1 and must answer exactly what it always did.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tradingagents import api as api_mod, rows_index as ri, stores
from tests.test_v2_store_is_its_own_folder import _row, _seed


@pytest.fixture
def client(tmp_path, monkeypatch):
    v2 = stores.Store(name="v2", home=tmp_path / "v2",
                      candles=tmp_path / "v2" / "candles",
                      rows_db=tmp_path / "v2" / "rows.db",
                      parquet=tmp_path / "parquet-v2", fine_tf="1m",
                      download_kind="download_v2", backtest_kind="backtest_v2")
    monkeypatch.setattr(stores, "V2", v2)
    monkeypatch.setitem(stores._BY_NAME, "v2", v2)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "v1" / "rows.db")
    # the v2 caches are module state: a payload cached by one test must not
    # answer the next (the completeness cache holds an answer for 300 s)
    monkeypatch.setattr(api_mod, "_COMPLETENESS_CACHE_V2", {"at": 0.0, "payload": None})
    monkeypatch.setattr(api_mod, "_GAP_CACHE_V2",
                        {"at": 0.0, "payload": None, "building": False})
    return TestClient(api_mod.app), v2


def test_an_empty_v2_store_is_a_sentence_not_a_500(client):
    c, _ = client
    r = c.get("/api/v2/strategies")
    assert r.status_code == 200
    d = r.json()
    assert d["rows"] == [] and d["total"] == 0 and d["store"] == "v2"
    assert "download 1m candles on Candles v2 first" in d["why"]
    for path in ("/api/v2/candles/gaps", "/api/v2/candles/pending",
                 "/api/v2/candles/lost", "/api/v2/backtest/storage",
                 "/api/v2/strategies/facets"):
        assert c.get(path).status_code == 200, path


def test_v2_strategies_come_from_the_v2_db_and_carry_unclear(client):
    c, v2 = client
    _seed(v2.rows_db, [_row("XPIN", 99.0, unclear=1, res="1m")])
    d = c.get("/api/v2/strategies?coin=XPIN").json()
    assert d["total"] == 1 and d["store"] == "v2"
    assert d["rows"][0]["unclear"] == 1 and d["rows"][0]["res"] == "1m"


def test_the_v1_route_never_sees_a_v2_row(client, tmp_path):
    c, v2 = client
    _seed(v2.rows_db, [_row("XPIN", 99.0, unclear=1, res="1m")])
    _seed(tmp_path / "v1" / "rows.db", [_row("XPIN", 10.0)])
    d = c.get("/api/strategies?coin=XPIN").json()
    assert d["total"] == 1 and d["rows"][0]["profit"] == 10.0
    assert d.get("store", "v1") == "v1"
    d2 = c.get("/api/v2/strategies?coin=XPIN").json()
    assert d2["rows"][0]["profit"] == 99.0


def test_the_v2_csv_streams_the_v2_rows(client):
    c, v2 = client
    _seed(v2.rows_db, [_row("XPIN", 99.0, unclear=3, res="1m")])
    r = c.get("/api/v2/strategies.csv?coin=XPIN")
    assert r.status_code == 200
    import csv
    import io

    # a real CSV reader: `balanced_why` carries commas inside quotes, so a
    # naive split shifts every column after it by one
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows, r.text[:200]
    first = rows[0]
    assert "unclear" in first and "res" in first
    assert first["unclear"] == "3" and first["res"] == "1m" and first["coin"] == "XPIN"


def test_v2_download_history_reads_the_v2_job_kind(client, monkeypatch):
    c, _ = client
    from tradingagents import notifications as nt

    seen = {}

    def fake_recent(limit=20, kind=None, **k):
        seen["kind"] = kind
        return []

    monkeypatch.setattr(nt, "recent", fake_recent)
    assert c.get("/api/v2/candles/download-history").status_code == 200
    assert seen["kind"] == "download_v2"
    c.get("/api/candles/download-history")
    assert seen["kind"] == "download"


def test_v2_completeness_counts_one_frame_against_the_v2_parquet(client, monkeypatch):
    c, v2 = client
    from tradingagents.dataflows import mexc_futures as fx

    monkeypatch.setattr(fx, "list_contracts",
                        lambda: [{"symbol": "XPIN_USDT"}, {"symbol": "ARKM_USDT"}])
    (v2.parquet / "candles").mkdir(parents=True)
    (v2.parquet / "candles" / "XPIN_USDT-1m.parquet").write_bytes(b"")
    d = c.get("/api/v2/candles/completeness").json()
    assert d["wanted"] == 2 and d["stored"] == 1
    assert d["missing"] == [{"symbol": "ARKM_USDT", "timeframe": "1m"}]
    assert d["timeframes"] == ["1m"]


def test_the_v2_job_kinds_are_known_to_the_jobs_routes(client):
    c, _ = client
    assert c.get("/api/jobs/download_v2").status_code == 200
    assert c.get("/api/jobs/backtest_v2").status_code == 200


def test_the_v2_csv_takes_a_days_window_and_names_the_months_gap(client):
    """RCA-2026-09-18-J: the panel offered "download the window's CSV" on
    Backtest v2 and the route answered 400 with a reason that had stopped
    being true. A DAYS window now exports (re-measured from the v2 store's
    1-minute candles inside the generator); a MONTHS window is refused with
    the true sentence, and the panel shows that sentence instead of a link."""
    c, v2 = client
    _seed(v2.rows_db, [_row("XPIN", 99.0, unclear=3, res="1m")])
    r = c.get("/api/v2/strategies.csv?coin=XPIN&days=30")
    assert r.status_code == 200, r.text[:200]
    assert "days" in r.headers.get("content-disposition", "").lower() or \
        r.headers.get("content-disposition"), "a file, named for its window"
    r = c.get("/api/v2/strategies.csv?coin=XPIN&months=1")
    assert r.status_code == 400
    why = r.json()["detail"]
    assert "MONTHS window" in why and "DAYS window" in why, why
    assert "v1 candle store" not in why, "the old, false reason is gone"
    panel = (Path(__file__).resolve().parents[1]
             / "webapp/src/components/backtest/StrategiesPanel.tsx").read_text(encoding="utf-8")
    assert 'store === "v2" && servedFilters.months' in panel
    assert "a months window has no CSV on Backtest v2 yet" in panel
