"""Ping a model on its OWN provider, and bucket the failure honestly.

Extracted from app.py so the HTTP layer and the Streamlit layer classify the
same error the same way. The verbatim provider message is always carried —
a health screen that rewrites the API's own words hides the fix (a missing
key reads identically to a dead endpoint once it is paraphrased).
"""
from __future__ import annotations

import os
import time

# usability percentage per status: what the operator can actually do with it
HEALTH_PCT = {"ok": 100, "degraded": 60, "ratelimit": 25, "auth": 0,
              "error": 0}


def classify_error(name: str, msg: str) -> str:
    """Bucket an exception (type name + message) into a health status. Pure."""
    if "DEGRADED" in msg:
        return "degraded"
    if ("429" in msg or "RateLimit" in name or "rate_limit" in msg
            or "RESOURCE_EXHAUSTED" in msg):
        return "ratelimit"
    if ("401" in msg or "403" in msg or "Authentication" in name
            or "API_KEY" in msg or "PERMISSION_DENIED" in msg):
        return "auth"
    return "error"


def raw_error(exc: BaseException) -> str:
    """The error as the API/SDK reported it, unrewritten."""
    return f"{type(exc).__name__}: {exc}"


def ping(model: str, spec: dict) -> dict:
    """One tiny live request at one model. Returns {status, pct, ms, detail}.

    `spec` is a merged model spec: provider, base_url, key_env.
    """
    from tradingagents.llm_clients.factory import create_llm_client

    key_env = spec.get("key_env")
    env_key = os.environ.get(key_env, "") if key_env else ""
    kw = ({"api_key": env_key}
          if (env_key and spec.get("provider") == "openai_compatible") else {})
    t0 = time.monotonic()
    try:
        cl = create_llm_client(provider=spec.get("provider"), model=model,
                               base_url=spec.get("base_url"), **kw)
        out = cl.get_llm().invoke("Reply with one word: ok")
        ms = int((time.monotonic() - t0) * 1000)
        return {"status": "ok", "pct": 100, "ms": ms,
                "detail": str(getattr(out, "content", ""))[:80]}
    except Exception as exc:                                   # noqa: BLE001
        ms = int((time.monotonic() - t0) * 1000)
        status = classify_error(type(exc).__name__, str(exc))
        return {"status": status, "pct": HEALTH_PCT.get(status, 0), "ms": ms,
                "detail": raw_error(exc)}


def key_present(spec: dict) -> bool:
    """Whether the env var this model needs is set. NEVER returns the key."""
    env = spec.get("key_env")
    return bool(env and os.environ.get(env, "").strip())
