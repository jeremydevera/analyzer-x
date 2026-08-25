"""The cloud download is the same loop as the PC's — and had the same hole.

`market_db.download` is what `.github/scripts/download_candles.py` runs on a
GitHub runner. Until 2026-08-25 it did exactly what the local job did with a
pair whose connection was cut mid-body: appended the text to `errors` and
moved on. One rule for both: a pair whose WIRE failed is redone by itself,
after the others, up to `db_jobs.PAIR_RETRIES` times; a deterministic failure
is named at once; `total` counts pairs, never attempts.
"""
import http.client

import pandas as pd
import pytest

from tradingagents import db_jobs
from tradingagents.dataflows import market_db as mdb


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv(mdb.DB_URL_ENV, f"sqlite:///{tmp_path}/market.db")
    monkeypatch.setattr(mdb, "_ENGINE", None)
    monkeypatch.setattr(mdb, "_ENGINE_URL", None)
    monkeypatch.setattr(mdb, "_down_until", 0.0)
    monkeypatch.setattr(db_jobs, "_pause", lambda seconds: None)
    assert mdb.ensure_schema()
    return mdb


def _frame(n=5):
    ts = [1_787_000_000 + i * 900 for i in range(n)]
    return pd.DataFrame({"Date": pd.to_datetime(ts, unit="s"),
                         "Open": [1.0] * n, "High": [2.0] * n, "Low": [0.5] * n,
                         "Close": [1.0] * n, "Volume": [10.0] * n})


class _Wire:
    """klines that fails `fails[(sym, iv)]` times with a cut connection."""

    def __init__(self, fails):
        self.fails, self.calls = dict(fails), []

    def klines(self, symbol, interval, limit):
        self.calls.append((symbol, interval))
        left = self.fails.get((symbol, interval), 0)
        if left > 0:
            self.fails[(symbol, interval)] = left - 1
            raise http.client.IncompleteRead(b"x" * 183452)
        return _frame()


def test_a_cut_connection_is_redone_after_the_others_and_stored(db):
    fx = _Wire({("CHILLGUY_USDT", "Min15"): 1})
    seen = []
    r = db.download(["APEX_USDT", "CHILLGUY_USDT", "NAORIS_USDT"], ["Min15"], fx=fx,
                    progress=lambda done, total, sym, iv: seen.append((done, total)))
    assert fx.calls == [("APEX_USDT", "Min15"), ("CHILLGUY_USDT", "Min15"),
                        ("NAORIS_USDT", "Min15"), ("CHILLGUY_USDT", "Min15")]
    assert r["errors"] == [] and r["retries"] == 1
    assert r["bars_stored"] == 15 and len(r["pairs"]) == 3
    assert len(db.candles_df("CHILLGUY_USDT", "Min15")) == 5
    # progress counts pairs settled out of pairs asked for — 3 of 3, never 4
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_a_pair_that_never_recovers_is_named_once_after_every_redo(db):
    fx = _Wire({("CHILLGUY_USDT", "Min15"): 10 ** 6})
    r = db.download(["CHILLGUY_USDT"], ["Min15"], fx=fx)
    assert len(fx.calls) == db_jobs.PAIR_RETRIES + 1
    assert r["errors"] == ["CHILLGUY_USDT Min15: IncompleteRead(183452 bytes read)"]
    assert r["retries"] == db_jobs.PAIR_RETRIES


def test_a_dead_contract_is_not_redone(db):
    class Fx:
        calls = 0

        @staticmethod
        def klines(symbol, interval, limit):
            Fx.calls += 1
            raise RuntimeError("no such contract")

    r = db.download(["GONE_USDT"], ["Min15"], fx=Fx)
    assert Fx.calls == 1 and r["retries"] == 0
    assert r["errors"] == ["GONE_USDT Min15: no such contract"]
