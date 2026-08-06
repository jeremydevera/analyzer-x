"""Unit tests for the LLM Models tab's persistent registry."""

import json

import pytest

import model_registry as reg


@pytest.fixture()
def store(tmp_path):
    return str(tmp_path / "webapp_models.json")


def test_load_custom_missing_file_is_empty(store):
    assert reg.load_custom(store) == {}


def test_add_and_load_roundtrip(store):
    ok, msg = reg.add_model("my/model-1", "nvidia", path=store)
    assert ok and "my/model-1" in msg
    saved = reg.load_custom(store)
    assert saved["my/model-1"]["provider"] == "nvidia"
    assert saved["my/model-1"]["key_env"] == "NVIDIA_API_KEY"


def test_add_rejects_blank_id_and_unknown_preset(store):
    assert reg.add_model("", "nvidia", path=store)[0] is False
    assert reg.add_model("m", "telepathy", path=store)[0] is False
    assert reg.load_custom(store) == {}


def test_openai_compatible_requires_base_url(store):
    ok, msg = reg.add_model("m", "openai-compatible (custom URL)", path=store)
    assert not ok and "base URL" in msg
    ok, _ = reg.add_model("m", "openai-compatible (custom URL)",
                          base_url="https://host/v1", path=store)
    assert ok
    assert reg.load_custom(store)["m"]["base_url"] == "https://host/v1"


def test_key_env_override(store):
    reg.add_model("m", "google", key_env="MY_KEY", path=store)
    assert reg.load_custom(store)["m"]["key_env"] == "MY_KEY"


def test_remove_model(store):
    reg.add_model("m", "google", path=store)
    assert reg.remove_model("m", path=store) is True
    assert reg.remove_model("m", path=store) is False
    assert reg.load_custom(store) == {}


def test_merged_models_user_spec_wins(store):
    builtin = {"a": {"label": "google"}, "b": {"label": "openai"}}
    reg.add_model("b", "nvidia", path=store)      # override a builtin id
    reg.add_model("c", "qwen", path=store)
    merged = reg.merged_models(builtin, path=store)
    assert set(merged) == {"a", "b", "c"}
    assert merged["b"]["label"] == "nvidia"       # user override wins


def test_load_custom_survives_corrupt_json(store):
    with open(store, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert reg.load_custom(store) == {}
    with open(store, "w", encoding="utf-8") as fh:
        json.dump(["not", "a", "dict"], fh)
    assert reg.load_custom(store) == {}
