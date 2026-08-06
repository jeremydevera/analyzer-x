"""Tests for the MEXC credential store — file permissions, masking, no leaks."""
import json
import os
import stat
from pathlib import Path

import pytest

from tradingagents.dataflows import mexc_credentials as cred

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(cred, "STORE_DIR", tmp_path)
    monkeypatch.setattr(cred, "STORE_PATH", tmp_path / "mexc_credentials.json")
    monkeypatch.delenv(cred.KEY_ENV, raising=False)
    monkeypatch.delenv(cred.SECRET_ENV, raising=False)
    yield


def test_saved_file_is_owner_only_readable(tmp_path):
    cred.save("mx0vABCDEFGH1234", "secret-abcdef123456")
    mode = (tmp_path / "mexc_credentials.json").stat().st_mode
    assert stat.S_IMODE(mode) == 0o600, "a secret must not be group/world readable"


def test_save_loads_into_the_environment():
    cred.save("mx0vKEY1234", "SEC5678")
    assert os.environ[cred.KEY_ENV] == "mx0vKEY1234"
    assert os.environ[cred.SECRET_ENV] == "SEC5678"


def test_save_rejects_blanks():
    for k, s in (("", "x"), ("x", ""), ("   ", "  ")):
        with pytest.raises(ValueError):
            cred.save(k, s)


def test_fingerprint_reveals_only_the_last_four():
    fp = cred.fingerprint("mx0vSUPERSECRET9999")
    # the fingerprint is "•••…9999  (19 chars)" — last four plus a length hint
    assert "9999" in fp
    assert fp.startswith("•")
    assert "SUPERSECRET" not in fp
    assert "•" in fp
    assert cred.fingerprint(None) == "—"
    assert cred.fingerprint("ab") == "••"


def test_status_never_returns_secret_material():
    cred.save("mx0vKEYAAAA1111", "SECRETBBBB2222")
    st = cred.status()
    blob = json.dumps(st)
    assert "mx0vKEYAAAA1111" not in blob
    assert "SECRETBBBB2222" not in blob
    assert st["has_credentials"] is True
    assert "1111" in st["key_fingerprint"]
    assert st["file_mode_ok"] is True


def test_status_distinguishes_shell_env_from_saved(monkeypatch):
    cred.save("savedKEY1111", "savedSEC2222")
    assert cred.status()["source"] == "saved in app"
    monkeypatch.setenv(cred.KEY_ENV, "shellKEY9999")
    monkeypatch.setenv(cred.SECRET_ENV, "shellSEC8888")
    assert cred.status()["source"] == "shell environment"


def test_clear_removes_file_and_environment():
    cred.save("mx0vKEY1234", "SEC5678")
    assert cred.clear() is True
    assert cred.status()["has_credentials"] is False
    assert cred.KEY_ENV not in os.environ
    assert cred.clear() is False, "clearing twice is not an error"


def test_saved_credentials_win_over_a_stale_dotenv(monkeypatch):
    """The saved pair must override the environment.

    This assertion is the REVERSE of what it was. The old rule (shell wins)
    meant a stale key in the project's .env — which python-dotenv loads into
    os.environ at import time — outranked the key the user had just saved from
    the UI, so the connection test failed against a key they had already
    replaced. Typing a key into the app is the newest explicit act; it wins.
    """
    cred.save("savedKEY1234", "savedSEC5678")
    monkeypatch.setenv(cred.KEY_ENV, "staleKEY9999")
    monkeypatch.setenv(cred.SECRET_ENV, "staleSEC8888")
    cred.load_into_env()
    assert os.environ[cred.KEY_ENV] == "savedKEY1234"
    assert os.environ[cred.SECRET_ENV] == "savedSEC5678"
    # opt-out still available for a caller that wants the ambient export
    monkeypatch.setenv(cred.KEY_ENV, "staleKEY9999")
    cred.load_into_env(override=False)
    assert os.environ[cred.KEY_ENV] == "staleKEY9999"


def test_env_conflict_flags_a_different_key_in_dotenv(tmp_path, monkeypatch):
    cred.save("savedKEY1234", "savedSEC5678")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("MEXC_API_KEY=otherKEY0000\n", encoding="utf-8")
    rep = cred.env_conflict()
    assert rep["conflict"] is True
    assert rep["stale"][0][0] == "project .env"
    assert "otherKEY0000" not in str(rep), "must not echo the raw key"
    (tmp_path / ".env").write_text("MEXC_API_KEY=savedKEY1234\n", encoding="utf-8")
    assert cred.env_conflict()["conflict"] is False


def test_corrupt_store_is_ignored_not_fatal(tmp_path):
    (tmp_path / "mexc_credentials.json").write_text("{not json")
    assert cred.load_into_env() is False
    assert cred.status()["has_credentials"] is False


def test_store_lives_outside_the_repository():
    """A secret inside the git tree is one `git add -A` from being published."""
    repo = Path(__file__).resolve().parents[1]
    default = Path(os.path.expanduser("~/.tradingagents/mexc_credentials.json"))
    assert repo not in default.parents


def test_trading_client_still_refuses_key_arguments():
    """The store must not have loosened the no-arguments invariant."""
    import inspect

    from tradingagents.dataflows import mexc_futures as fx
    for name in ("submit", "open_long", "close_long", "limit_close_long"):
        sig = inspect.signature(getattr(fx, name))
        assert not any(p in sig.parameters
                       for p in ("key", "secret", "api_key", "api_secret"))


# ------------------------------------------------- permission classification
def test_permission_codes_map_to_specific_remedies():
    from tradingagents.dataflows import mexc_futures as fx
    for code in (701, 703, 704):
        scope, remedy = fx.PERMISSION_CODES[code]
        assert scope and remedy
        assert "MEXC" in remedy or "enable" in remedy.lower()
    # 704 is the order-placement scope and must be distinguishable from reads
    assert "write" in fx.PERMISSION_CODES[704][0]
    assert fx.PERMISSION_CODES[701][0] != fx.PERMISSION_CODES[703][0]


def test_scope_error_is_forbidden_not_generic(monkeypatch):
    """A 704 must raise Forbidden carrying the remedy — an earlier version
    treated it as a validation error and reported order permission as GRANTED."""
    import json as _json

    from tradingagents.dataflows import mexc_futures as fx

    class FakeResp:
        def __init__(self, payload): self._p = payload
        def read(self): return _json.dumps(self._p).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setenv("MEXC_API_KEY", "k")
    monkeypatch.setenv("MEXC_API_SECRET", "s")
    monkeypatch.setattr(fx.urllib.request, "urlopen",
                        lambda *a, **k: FakeResp(
                            {"success": False, "code": 704,
                             "message": "Please enable API Key trading "
                                        "information write access"}))
    with pytest.raises(fx.MexcFuturesForbidden) as exc:
        fx._request("POST", "/api/v1/private/order/submit", body={"vol": 0})
    assert exc.value.code == 704
    assert "write" in (exc.value.scope or "")
    assert "Write" in (exc.value.remedy or "")


def test_preflight_reports_not_ready_when_a_scope_is_missing(monkeypatch):
    import json as _json

    from tradingagents.dataflows import mexc_futures as fx

    class FakeResp:
        def __init__(self, payload): self._p = payload
        def read(self): return _json.dumps(self._p).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setenv("MEXC_API_KEY", "k")
    monkeypatch.setenv("MEXC_API_SECRET", "s")
    codes = iter([701, 703, 704])
    def fake_open(*a, **k):
        return FakeResp({"success": False, "code": next(codes),
                         "message": "scope missing"})
    monkeypatch.setattr(fx.urllib.request, "urlopen", fake_open)
    rep = fx.preflight("SPX500_USDT")
    assert rep["ready"] is False
    assert rep["order_permission"] is False, "704 must never read as granted"
    assert len(rep["missing_scopes"]) == 3
    assert len(rep["remedies"]) == 3
