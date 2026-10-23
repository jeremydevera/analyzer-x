"""Backtest v3 has its own store and its own ids (spec
docs/superpowers/specs/2026-10-22-backtest-v3-design.md, "The store and the
ids"): v3 never writes v1 or v2, and a v3 row never shares an id with its v1
or v2 twin."""
from tradingagents import backtest_report as br, stores


def test_v3_has_its_own_folders():
    root, v3 = stores.V1.home.parent, stores.V3
    assert str(v3.home).replace("\\", "/").endswith("/.tradingagents/v3")
    assert v3.candles == root / "v3" / "candles"
    assert v3.rows_db == root / "v3" / "rows.db"
    assert v3.parquet == root / "parquet-v3"
    for f in ("home", "candles", "rows_db", "parquet"):
        assert len({getattr(s, f) for s in (stores.V1, stores.V2, v3)}) == 3, f


def test_v3_is_found_by_name_and_by_kind():
    assert stores.by_name("v3") is stores.V3
    assert stores.for_kind("backtest_v3") is stores.V3
    assert stores.for_kind("backtest_v2") is stores.V2
    assert stores.for_kind("backtest") is stores.V1


def test_the_frames_each_store_works_in():
    assert stores.V1.tfs == stores.FIVE
    assert stores.V2.tfs == ("1m",)
    assert stores.V3.tfs == stores.FIVE


def test_a_v3_id_never_equals_its_v1_or_v2_twin():
    combo = ("BTC_USDT", "1h", "bb20", 0.0, 0.01, 0.02, "flat")
    v1, v2, v3 = (br.row_code(*combo), br.row_code(*combo, res="1m"),
                  br.row_code(*combo, res="v3"))
    assert len({v1, v2, v3}) == 3
    assert v3 == br.row_code(*combo, res="v3"), "the same combination, the same id"
