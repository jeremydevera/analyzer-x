"""v2 lives beside v1 and can never be mistaken for it.

Same signals, same frames, same engine — different folder, different ids,
two more columns. A v1 id must hash to itself for ever (the operator pastes
ids between tabs; #05146/#02054 was one row with two names).
"""
import importlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from tradingagents import backtest_report as br, rows_index as ri


# ------------------------------------------------------------------ identity
def test_a_v2_id_never_equals_the_v1_id_and_v1_ids_are_untouched():
    args = ("XPIN", "1h", "ote", 0.0, 3.0, 1.0, "flat")
    v1 = br.row_code(*args)
    v2 = br.row_code(*args, res="1m")
    assert v1 != v2 and len(v1) == len(v2) == 8
    assert v1 == "LG9NSU4B", "the operator's own row — its id is a fixed point"
    assert br.row_code(*args, res=None) == v1
    assert br.row_code(*args, res="") == v1, "an empty resolution is no resolution"


# ------------------------------------------------------------------- columns
def test_the_index_grows_the_two_v2_columns_without_a_rewrite(tmp_path, monkeypatch):
    db = tmp_path / "rows.db"
    monkeypatch.setattr(ri, "DB_PATH", db)
    ri._ready.discard(str(db)) if hasattr(ri._ready, "discard") else None
    # an OLD table without the columns, as the operator's 41.94 GB v1 file has
    con = sqlite3.connect(db)
    old_cols = [c for c in ri.COLS if c not in ("unclear", "res")]
    con.execute("CREATE TABLE rows (" + ",".join(old_cols)
                + ", monthly TEXT, pair TEXT NOT NULL)")
    con.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    con.execute("INSERT INTO meta VALUES ('schema', ?)", (str(ri.SCHEMA_VERSION),))
    con.commit()
    con.close()
    ri.ensure()
    have = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(rows)")}
    assert {"unclear", "res"} <= have
    assert "unclear" in ri.COLS and "res" in ri.COLS
    assert "unclear" in ri._INTEGER


def test_values_carry_unclear_and_res_and_default_them_for_a_v1_row():
    r = {"coin": "XPIN", "tf": "1h", "signal": "ote", "th": 0.0, "sl": 3.0, "tp": 1.0,
         "sizing": "flat", "trades": 5, "wins": 4, "losses": 1, "winrate": 80.0,
         "profit": 1.0, "monthly": {}}
    names = list(ri.COLS) + ["monthly", "pair"]
    vals = dict(zip(names, ri._values(r, "XPIN-1h"), strict=True))
    assert vals["unclear"] is None and vals["res"] is None
    vals2 = dict(zip(names, ri._values({**r, "unclear": 2, "res": "1m"}, "XPIN-1h"),
                     strict=True))
    assert vals2["unclear"] == 2 and vals2["res"] == "1m"
    assert vals2["id"] != vals["id"], "the id carries the resolution"


# ------------------------------------------------------------------ FINE_TF
def test_fine_tf_is_empty_unless_the_environment_says_so(monkeypatch, tmp_path):
    from tradingagents import market_sweep as msw

    assert msw.FINE_TF == ""
    monkeypatch.setenv("TRADINGAGENTS_FINE_TF", "1m")
    monkeypatch.setenv("TRADINGAGENTS_SWEEP_HOME", str(tmp_path / "v2"))
    monkeypatch.setenv("TRADINGAGENTS_CANDLES", str(tmp_path / "v2" / "candles"))
    m2 = importlib.reload(msw)
    try:
        assert m2.FINE_TF == "1m"
        assert str(m2.HOME) == str(tmp_path / "v2")
    finally:
        monkeypatch.delenv("TRADINGAGENTS_FINE_TF")
        monkeypatch.delenv("TRADINGAGENTS_SWEEP_HOME")
        monkeypatch.delenv("TRADINGAGENTS_CANDLES")
        importlib.reload(msw)
    assert msw.FINE_TF == ""


# -------------------------------------------------------------------- stores
def test_the_two_stores_never_share_a_path():
    from tradingagents import stores

    a, b = stores.V1, stores.V2
    for f in ("home", "candles", "rows_db", "parquet"):
        assert getattr(a, f) != getattr(b, f), f
    assert str(b.home).replace("\\", "/").endswith("/.tradingagents/v2")
    assert b.fine_tf == "1m" and a.fine_tf == ""
    assert b.tfs == ("1m",) and a.tfs == ("15m", "30m", "1h", "4h", "1d")
    assert stores.by_name("v2") is b and stores.by_name("v1") is a
    assert stores.for_kind("download_v2") is b and stores.for_kind("download") is a
    with pytest.raises(KeyError):
        stores.by_name("v3")
    env = b.env_for()
    assert env["TRADINGAGENTS_FINE_TF"] == "1m"
    assert env["TA_ROWS_DB"] == str(b.rows_db)
    assert env["TRADINGAGENTS_PARQUET"] == str(b.parquet)


# ---------------------------------------------------------------------- jobs
def _sandbox_jobs(monkeypatch, tmp_path):
    from tradingagents import db_jobs as dj

    monkeypatch.setattr(dj, "STATE_DIR", tmp_path)
    for k in ("download", "download_v2", "backtest", "backtest_v2"):
        for name, p in list(dj.FILES[k].items()):
            monkeypatch.setitem(dj.FILES[k], name, tmp_path / p.name)
    return dj


def test_a_v2_job_is_spawned_into_the_v2_folder_and_a_v1_job_is_not(monkeypatch, tmp_path):
    from tradingagents import stores

    dj = _sandbox_jobs(monkeypatch, tmp_path)
    seen: dict = {}

    class _P:
        pid = 4242

    def fake_popen(args, **kw):
        seen["env"] = dict(kw.get("env") or {})
        seen["args"] = list(args)
        return _P()

    monkeypatch.setattr(dj.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(dj, "status", lambda kind: {"running": False})
    monkeypatch.delenv("TRADINGAGENTS_FINE_TF", raising=False)
    monkeypatch.delenv("TA_ROWS_DB", raising=False)

    dj.start("download_v2", {"coins": ["XPIN_USDT"], "tfs": ["1m"]})
    want = stores.V2.env_for()
    for k, v in want.items():
        assert seen["env"].get(k) == v, k
    assert seen["args"][-1] == "download_v2"

    dj.start("download", {"coins": ["XPIN_USDT"], "tfs": ["15m"]})
    assert "TRADINGAGENTS_FINE_TF" not in seen["env"], "a v1 job must not inherit a v2 root"
    assert "TA_ROWS_DB" not in seen["env"]


def test_a_v2_job_waits_for_a_v1_job_and_the_other_way_round(monkeypatch, tmp_path):
    dj = _sandbox_jobs(monkeypatch, tmp_path)
    monkeypatch.setattr(dj, "status", lambda kind: {"running": kind == "download"})
    with pytest.raises(dj.JobBusy, match="download is running"):
        dj.start("download_v2", {"coins": [], "tfs": ["1m"]})
    monkeypatch.setattr(dj, "status", lambda kind: {"running": kind == "backtest_v2"})
    with pytest.raises(dj.JobBusy, match="backtest_v2 is running"):
        dj.start("download", {"coins": [], "tfs": ["15m"]})


def test_update_pairs_for_v2_only_ever_asks_for_1m(monkeypatch):
    from tradingagents import db_jobs as dj, market_sweep as msw

    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: ["XPIN_USDT", "ARKM_USDT"])
    monkeypatch.setattr(msw, "candle_index", lambda *a, **k: {
        "XPIN_USDT-1m": {"bars": 100, "last_ms": 1_789_516_800_000}})
    pairs, gone, n_missing, lost_added = dj.update_pairs([], tfs=("1m",))
    assert ("ARKM_USDT", "1m") in pairs and ("XPIN_USDT", "1m") in pairs
    assert all(tf == "1m" for _, tf in pairs)


def test_the_download_job_accepts_1m_only_for_the_v2_kind():
    from tradingagents import db_jobs as dj

    assert dj._download_tfs({"tfs": ["1m", "15m"]}, kind="download_v2") == ["1m"]
    assert dj._download_tfs({"tfs": ["1m", "15m"]}, kind="download") == ["15m"]


# ------------------------------------------------------- reading a v2 store
def _seed(db: Path, rows: list[dict]) -> None:
    """A rows.db with the current schema, holding `rows` — built the way the
    indexer builds one, through the module's own SCHEMA, COLS and _values."""
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(ri._SCHEMA)
    con.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    con.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)",
                (str(ri.SCHEMA_VERSION),))
    ph = "(" + ",".join("?" * (len(ri.COLS) + 2)) + ")"
    con.executemany(
        f"INSERT INTO rows ({','.join(ri.COLS)},monthly,pair) VALUES {ph}",
        [ri._values(r, f"{r['coin']}-{r['tf']}") for r in rows])
    con.execute("INSERT OR REPLACE INTO pairs (pair, mtime, size, n, at, coin, tf) "
                "VALUES (?,?,?,?,?,?,?)",
                (f"{rows[0]['coin']}-{rows[0]['tf']}", 1.0, 1, len(rows), 1.0,
                 rows[0]["coin"], rows[0]["tf"]))
    for ddl in ri.KEEP_INDEXES:
        con.execute(ddl)
    con.commit()
    con.close()


def _row(coin, profit, **kw):
    base = {"coin": coin, "tf": "1h", "signal": "ote", "th": 0.0, "sl": 3.0,
            "tp": 1.0, "rr": 0.33, "sizing": "flat", "lev": 20, "base": 5.0,
            "notional": 100.0, "trades": 10, "wins": 8, "losses": 2,
            "winrate": 80.0, "profit": profit, "funding": 0.0, "h1": 1.0,
            "h2": 1.0, "green": 1, "months": 1, "worst": -1.0, "dd": 1.0,
            "liqs": 0, "stop_reachable": True, "days": 30, "bars": 720,
            "cost_of_tp": 10.0, "rt": 0.1, "gate": "ok",
            "monthly": {"2026-09": profit}}
    base.update(kw)
    return base


def test_the_index_answers_from_the_store_it_is_handed(tmp_path, monkeypatch):
    v1, v2 = tmp_path / "v1" / "rows.db", tmp_path / "v2" / "rows.db"
    _seed(v1, [_row("XPIN", 10.0)])
    _seed(v2, [_row("XPIN", 99.0, unclear=2, res="1m")])
    monkeypatch.setattr(ri, "DB_PATH", v1)
    a = ri.query(coin="XPIN")
    b = ri.query(coin="XPIN", db_path=v2)
    assert a["rows"][0]["profit"] == 10.0 and a["rows"][0].get("unclear") is None
    assert b["rows"][0]["profit"] == 99.0 and b["rows"][0]["unclear"] == 2
    assert b["rows"][0]["res"] == "1m"
    assert b["rows"][0]["id"] != a["rows"][0]["id"], "v2 ids differ from v1 ids"
    assert ri.status(db_path=v2)["rows"] == 1
    assert ri.pair_storage(db_path=v2)[0]["n"] == 1
    assert "XPIN" in ri.facets(db_path=v2)["coins"]


def test_candle_index_reads_the_root_it_is_handed(tmp_path):
    from tradingagents import market_sweep as msw

    root = tmp_path / "v2" / "candles"
    root.mkdir(parents=True)
    (root / "XPIN_USDT-1m.json").write_text(json.dumps(
        {"t": [1_789_516_800_000, 1_789_516_860_000], "o": [1, 1], "h": [1, 1],
         "l": [1, 1], "c": [1, 1], "v": [1, 1]}))
    got = msw.candle_index(root=root)
    assert set(got) == {"XPIN_USDT-1m"} and got["XPIN_USDT-1m"]["bars"] == 2
    assert (root.parent / "candle_index.json").exists(), \
        "its own index file, beside its own candles"


def test_parquet_root_follows_the_environment(monkeypatch, tmp_path):
    from tradingagents import parquet_store as pqs

    monkeypatch.setenv("TRADINGAGENTS_PARQUET", str(tmp_path / "parquet-v2"))
    m2 = importlib.reload(pqs)
    try:
        assert str(m2.ROOT) == str(tmp_path / "parquet-v2")
        assert str(m2.CANDLES) == str(tmp_path / "parquet-v2" / "candles")
    finally:
        monkeypatch.delenv("TRADINGAGENTS_PARQUET")
        importlib.reload(pqs)
