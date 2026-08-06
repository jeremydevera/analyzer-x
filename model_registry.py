"""User-added LLM models for the web UI, persisted across restarts.

The built-in catalog lives in app.py (MODELS). Models added on the
"LLM Models" tab land here, in a small JSON file under ~/.tradingagents,
and are merged into every model dropdown (New Crypto and Run analysis)
on the next rerun. Pure functions — unit-tested without Streamlit.

Each entry has the same shape as an app.py MODELS spec:
    {"label": <provider display label>, "provider": <factory provider id>,
     "base_url": <str or None>, "key_env": <env var holding the API key>}
"""

from __future__ import annotations

import json
import os

_STORE_PATH = os.path.join(os.path.expanduser("~"), ".tradingagents",
                           "webapp_models.json")

# Providers offered by the add-model form. label doubles as the display
# name in the table; openai_compatible needs an explicit base URL.
PROVIDER_PRESETS: dict[str, dict] = {
    "google": {"label": "google", "provider": "google",
               "base_url": None, "key_env": "GOOGLE_API_KEY"},
    "nvidia": {"label": "nvidia", "provider": "nvidia",
               "base_url": None, "key_env": "NVIDIA_API_KEY"},
    "openai": {"label": "openai", "provider": "openai",
               "base_url": None, "key_env": "OPENAI_API_KEY"},
    "anthropic": {"label": "anthropic", "provider": "anthropic",
                  "base_url": None, "key_env": "ANTHROPIC_API_KEY"},
    "qwen": {"label": "qwen", "provider": "qwen",
             "base_url": None, "key_env": "DASHSCOPE_API_KEY"},
    "ollama cloud": {"label": "ollama", "provider": "openai_compatible",
                     "base_url": "https://ollama.com/v1",
                     "key_env": "OLLAMA_API_KEY"},
    "openai-compatible (custom URL)": {"label": "custom", "provider": "openai_compatible",
                                       "base_url": None, "key_env": "OPENAI_API_KEY"},
}


def load_custom(path: str = _STORE_PATH) -> dict[str, dict]:
    """The user's saved models, or {} when none / file unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(models: dict[str, dict], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(models, fh, indent=2)


def add_model(model_id: str, preset: str, *, base_url: str = "",
              key_env: str = "", path: str = _STORE_PATH) -> tuple[bool, str]:
    """Validate and persist one model. Returns (ok, message).

    ``base_url`` and ``key_env`` override the preset when given — required
    for the openai-compatible preset, optional elsewhere.
    """
    model_id = (model_id or "").strip()
    if not model_id:
        return False, "Model id is required."
    if preset not in PROVIDER_PRESETS:
        return False, f"Unknown provider: {preset}"
    spec = dict(PROVIDER_PRESETS[preset])
    if base_url.strip():
        spec["base_url"] = base_url.strip()
    if key_env.strip():
        spec["key_env"] = key_env.strip()
    if spec["provider"] == "openai_compatible" and not spec["base_url"]:
        return False, "An openai-compatible model needs a base URL."
    models = load_custom(path)
    models[model_id] = spec
    _save(models, path)
    return True, f"Added {model_id} ({spec['label']})."


def remove_model(model_id: str, path: str = _STORE_PATH) -> bool:
    """Delete one saved model. Returns True when it existed."""
    models = load_custom(path)
    if model_id not in models:
        return False
    del models[model_id]
    _save(models, path)
    return True


def merged_models(builtin: dict[str, dict], path: str = _STORE_PATH) -> dict[str, dict]:
    """Built-ins plus the user's saved models; a duplicate id keeps the
    user's spec so a saved override wins over the shipped catalog."""
    out = dict(builtin)
    out.update(load_custom(path))
    return out
