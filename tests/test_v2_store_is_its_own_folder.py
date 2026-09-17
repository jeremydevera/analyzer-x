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
