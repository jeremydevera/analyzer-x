"""The keys panel saves the key of the exchange the app trades (Oct 10, 2026).

Under Gate the pair goes to ~/.tradingagents/gate_credentials.json (owner
only) and into GATE_API_KEY / GATE_API_SECRET, which gate_futures reads;
under MEXC nothing changes. A MEXC key is never offered to Gate.
"""
from tradingagents.dataflows import mexc_credentials as cred


def test_under_gate_the_pair_is_gates(monkeypatch, tmp_path):
    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.setattr(cred, "STORE_DIR", tmp_path)
    monkeypatch.delenv("GATE_API_KEY", raising=False)
    monkeypatch.delenv("GATE_API_SECRET", raising=False)
    monkeypatch.setenv("MEXC_API_KEY", "mexc-key")
    monkeypatch.setenv("MEXC_API_SECRET", "mexc-secret")
    st = cred.status()
    assert st["has_credentials"] is False, "a MEXC key is not a Gate key"
    assert st["store_path"].endswith("gate_credentials.json")
    cred.save("gate-key-1234", "gate-secret")
    import os

    assert os.environ["GATE_API_KEY"] == "gate-key-1234"
    assert (tmp_path / "gate_credentials.json").exists()
    assert not (tmp_path / "mexc_credentials.json").exists()
    assert cred.status()["has_credentials"] is True
    assert cred.status()["exchange"] == "Gate"
    from tradingagents.dataflows import gate_futures as gf

    assert gf.has_credentials() is True
    assert cred.clear() is True and "GATE_API_KEY" not in os.environ


def test_under_mexc_nothing_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(cred, "STORE_PATH", tmp_path / "mexc_credentials.json")
    monkeypatch.setattr(cred, "STORE_DIR", tmp_path)
    st = cred.status()
    assert st["store_path"].endswith("mexc_credentials.json") and st["exchange"] == "MEXC"
