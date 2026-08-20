"""The model catalog, importable without Streamlit.

app.py owns the UI; this owns the data, so the HTTP layer can read the
same built-in list the Streamlit screen shows.
"""

_OLLAMA = {"label": "ollama", "provider": "openai_compatible",
           "base_url": "https://ollama.com/v1", "key_env": "OLLAMA_API_KEY"}
_GOOGLE = {"label": "google", "provider": "google", "base_url": None, "key_env": "GOOGLE_API_KEY"}
_QWEN = {"label": "qwen", "provider": "qwen", "base_url": None, "key_env": "DASHSCOPE_API_KEY"}
# Alibaba MaaS workspace (dedicated host) — OpenAI-compatible; serves glm-5.1 etc.
_MAAS = {"label": "maas", "provider": "openai_compatible",
         "base_url": "https://ws-wu00l7n3hmiafz2q.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
         "key_env": "MAAS_API_KEY"}
# Catalog pruned 2026-08-18 against a live ping of every model. Removed:
# deepseek-ai/* (410 Gone — NVIDIA retired the endpoint) and all four OpenAI
# models (429 "exceeded your current quota" — errors until the OpenAI account
# is funded). Earlier prunes (2026-07-31): Cloudflare @cf/* + partner deepseek
# (401), claude-opus-4-8 (no key), glm-4.7 + qwen3-coder:480b (410),
# z-ai/glm-5.1 (410), moonshotai/kimi-k2.6 (404). Re-add any of them on the
# LLM Models tab if the key/endpoint comes back.
MODELS: dict[str, dict] = {
    "gemini-3.1-flash-lite": _GOOGLE,            # free · fast · clean
    "gemini-3.5-flash": _GOOGLE,                 # free
    "gpt-oss:120b": _OLLAMA,                     # Ollama Cloud · free
    "qwen3.6-flash": _QWEN,                      # Qwen Cloud · cheap · clean
    "qwen3.7-plus": _QWEN,                       # Qwen Cloud · balanced
    "qwen3.7-max": _QWEN,                        # Qwen Cloud · top reasoning/coding
    "glm-5.1": _MAAS,                            # Alibaba MaaS · GLM-5.1 (works here!)
    "deepseek-v4-flash": _MAAS,                  # Alibaba MaaS · DeepSeek V4 Flash
    "deepseek-v4-pro": _MAAS,                    # Alibaba MaaS · DeepSeek V4 Pro
}
