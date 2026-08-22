"""The models routes hand the frontend a catalog and a live health probe.

The hard invariant: a key's PRESENCE is reportable, its VALUE never is. The
canary here is a real-looking key in the env var a model spec names.
"""
import json

import pytest
from fastapi.testclient import TestClient

from tradingagents import model_health as mh
from tradingagents.api import app


@pytest.fixture()
def client(monkeypatch, tmp_path):
    import model_registry
    monkeypatch.setattr(model_registry, "_STORE_PATH", str(tmp_path / "m.json"))
    return TestClient(app)


def test_catalog_lists_builtins_and_says_whether_a_key_is_present(client,
                                                                  monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "CANARY-GOOGLE-KEY-4b2f")
    got = client.get("/api/models").json()
    ids = {r["id"] for r in got["rows"]}
    import app_models
    assert set(app_models.MODELS) <= ids
    goog = next(r for r in got["rows"] if r["key_env"] == "GOOGLE_API_KEY")
    assert goog["key_present"] is True
    assert "CANARY-GOOGLE-KEY-4b2f" not in json.dumps(got), "key value leaked"


def test_add_then_remove_a_custom_model(client, tmp_path):
    import model_registry
    add = client.post("/api/models/add", json={
        "model_id": "vendor/thing", "preset": "openai-compatible (custom URL)",
        "base_url": "https://host/v1"}).json()
    assert add["ok"] is True
    rows = client.get("/api/models").json()["rows"]
    mine = next(r for r in rows if r["id"] == "vendor/thing")
    assert mine["custom"] is True and mine["base_url"] == "https://host/v1"
    assert client.post("/api/models/remove",
                       json={"model_id": "vendor/thing"}).json()["ok"] is True
    assert model_registry.load_custom() == {}


def test_openai_compatible_without_a_url_is_refused_with_the_reason(client):
    got = client.post("/api/models/add", json={
        "model_id": "x/y", "preset": "openai-compatible (custom URL)"}).json()
    assert got["ok"] is False and "base URL" in got["message"]


def test_ping_reports_the_providers_own_words_and_a_usable_percentage(client,
                                                                     monkeypatch):
    monkeypatch.setattr(mh, "ping", lambda mid, spec: {
        "status": "ratelimit", "pct": 25, "ms": 12,
        "detail": "RateLimitError: Error code: 429 - quota"})
    got = client.post("/api/models/ping",
                      json={"model_id": "gemini-3.5-flash"}).json()
    assert got["pct"] == 25 and got["status"] == "ratelimit"
    assert "429" in got["detail"], "the provider's verbatim message is the fix"


def test_ping_an_unknown_model_is_a_404_not_a_crash(client):
    assert client.post("/api/models/ping",
                       json={"model_id": "nope/nope"}).status_code == 404


def test_classify_buckets_the_failures_operators_actually_hit():
    assert mh.classify_error("RateLimitError", "429 quota") == "ratelimit"
    assert mh.classify_error("AuthError", "401 bad API_KEY") == "auth"
    assert mh.classify_error("ValueError", "boom") == "error"


def test_social_sources_say_whether_x_is_usable_without_leaking_the_key(client,
                                                                       monkeypatch):
    """Picking X with no key must be visible BEFORE a run, not discovered in
    a report that says the source was missing."""
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "CANARY-X-KEY-8812")
    got = client.get("/api/analysis/social/sources").json()
    assert got["x_key_present"] is True
    assert "CANARY-X-KEY-8812" not in str(got)
    assert got["default"] == "stocktwits", "the free source is the default"
    ids = [s["id"] for s in got["sources"]]
    assert ids == ["stocktwits", "twitter", "both"]
    monkeypatch.delenv("TWITTERAPI_IO_KEY")
    assert client.get("/api/analysis/social/sources").json()["x_key_present"] is False
