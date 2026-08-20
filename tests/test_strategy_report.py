"""The '1 YEAR' button. What must hold:

* the DEPLOYED row is injected, or the operator's own config appears nowhere
  in its own backtest (CLAUDE.md rule 21);
* the cache signature includes the signal count, so widening the registry
  rebuilds instead of serving a page that tested fewer signals;
* the strategy's OWN timeframe is tested first, and 1h/4h alongside it.
"""
import pytest

from tradingagents import strategy_report as sr


def test_the_deployed_row_is_injected_with_its_real_barriers(monkeypatch,
                                                            tmp_path):
    seen = {}

    class BR:
        SIGNALS = {"a": 1, "b": 2}

        @staticmethod
        def grid_from_store(coins, tfs, **kw):
            seen.update({"coins": coins, "tfs": tfs, **kw})
            return {"rows": [{"coin": "XAUT"}]}

        @staticmethod
        def write_report(path, payload, *, title, note):
            open(path, "w").write("x" * 20_000)
            seen["title"] = title
            seen["note"] = note

    monkeypatch.setattr(sr, "REPORT_DIR", tmp_path)
    import sys
    monkeypatch.setitem(sys.modules, "tradingagents.backtest_report", BR)
    from tradingagents import auto_trader as at
    monkeypatch.setattr(at, "STRATEGY_SPECS", {"mom6_1h_gx": {
        "interval": "Min60", "tp": 0.02, "sl": 0.015, "threshold": 0.0015}})
    monkeypatch.setattr(at, "sizing_for", lambda s: "martingale")
    monkeypatch.setattr(at, "load_settings", lambda: {})

    got = sr.build("mom6_1h_gx", label="Momentum 6 (1h) — XAUT",
                   coins=["XAUT_USDT"], base_margin=5.0, days=365,
                   today="20260821")
    dep = seen["deployed"][0]
    assert dep == {"coin": "XAUT", "tf": "1h", "signal": "mom6", "th": 0.15,
                   "sl": 1.5, "tp": 2.0, "sizing": "martingale"}
    assert seen["tfs"][0] == "1h", "its own timeframe is tested first"
    assert "4h" in seen["tfs"]
    assert got["cached"] is False and got["rows"] == 1
    assert "DEPLOYED" in seen["note"]
    assert got["url"].startswith("/api/reports/file/")


def test_the_cache_signature_changes_when_the_signal_registry_grows():
    spec = {"sl": 0.01, "tp": 0.02, "threshold": 0.003}
    a = sr.signature("k", ["A"], ["1h"], "flat", 5.0, 365, spec, 75)
    b = sr.signature("k", ["A"], ["1h"], "flat", 5.0, 365, spec, 90)
    assert a != b, "a wider grid must not serve the narrower page"


def test_the_signature_separates_sizings_and_margins():
    spec = {"sl": 0.01, "tp": 0.02, "threshold": 0.0}
    base = sr.signature("k", ["A"], ["1h"], "flat", 5.0, 365, spec, 75)
    assert base != sr.signature("k", ["A"], ["1h"], "martingale", 5.0, 365, spec, 75)
    assert base != sr.signature("k", ["A"], ["1h"], "flat", 10.0, 365, spec, 75)


def test_no_contract_is_an_error_not_an_empty_page(monkeypatch):
    with pytest.raises(ValueError):
        sr.build("mom6_1h_gx", label="x", coins=[], base_margin=5.0)
