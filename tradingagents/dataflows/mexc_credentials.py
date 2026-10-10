"""Credential store for MEXC keys entered through the web UI.

Design constraints, in priority order:

1. **The secret is never returned to the caller.** :func:`status` reports only a
   masked fingerprint, so nothing can render a secret back into a browser, a log
   line, or a screenshot.
2. **Stored outside the repository.** ``~/.tradingagents/mexc_credentials.json``
   with mode ``0600``. Writing to the project's ``.env`` was rejected: that file
   lives in a git tree, and one ``git add -A`` by a future contributor publishes
   the key.
3. **The trading clients keep reading only the environment.** This module loads
   saved values into ``os.environ``; it does not change how
   :mod:`mexc_futures` obtains them. Those functions still refuse to accept a
   key as an argument, so a key cannot appear in a traceback.

A leaked trade-only key can lose money on bad trades but cannot move funds off
the exchange, which is why the UI insists on withdrawals being disabled.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

STORE_DIR = Path(os.path.expanduser("~/.tradingagents"))
STORE_PATH = STORE_DIR / "mexc_credentials.json"
KEY_ENV = "MEXC_API_KEY"
SECRET_ENV = "MEXC_API_SECRET"


def _where() -> tuple:
    """(file, key variable, secret variable, exchange name) of the exchange
    the app trades (Oct 10, 2026, the move to Gate). Under MEXC the module's
    own names, unchanged; under Gate its own file and variables, so a MEXC
    key is never offered to Gate (gate_futures reads GATE_API_KEY)."""
    from tradingagents import venue

    if venue.current() == "gate":
        return (STORE_DIR / "gate_credentials.json", "GATE_API_KEY",
                "GATE_API_SECRET", "Gate")
    return (STORE_PATH, KEY_ENV, SECRET_ENV, "MEXC")


def fingerprint(value: str | None) -> str:
    """A safe-to-display stub: length plus the last four characters.

    Enough to tell two keys apart when checking which one is loaded, useless to
    anyone who sees it.
    """
    if not value:
        return "—"
    v = value.strip()
    if len(v) <= 4:
        return "•" * len(v)
    return f"{'•' * (len(v) - 4)}{v[-4:]}  ({len(v)} chars)"


def save(api_key: str, api_secret: str) -> None:
    """Persist a key pair with owner-only permissions, and load it now.

    Raises ValueError on empty input rather than storing a blank that would
    later fail confusingly at the exchange.
    """
    api_key = (api_key or "").strip()
    api_secret = (api_secret or "").strip()
    if not api_key or not api_secret:
        raise ValueError("both the API key and the secret are required")
    store, _k, _s, name = _where()
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    # Create with 0600 from the outset — writing then chmod'ing leaves a window
    # where the secret is world-readable.
    fd = os.open(store, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"api_key": api_key, "api_secret": api_secret}, fh)
    os.chmod(store, 0o600)
    load_into_env(override=True)
    logger.info("%s credentials saved to %s (key %s)",
                name, store, fingerprint(api_key))


def clear() -> bool:
    """Delete the stored pair and remove it from this process's environment."""
    store, key_env, secret_env, name = _where()
    existed = store.exists()
    store.unlink(missing_ok=True)
    for var in (key_env, secret_env):
        os.environ.pop(var, None)
    if existed:
        logger.info("%s credentials cleared", name)
    return existed


def _read() -> dict:
    try:
        with _where()[0].open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_into_env(override: bool = True) -> bool:
    """Copy saved credentials into ``os.environ``. Returns True if any were set.

    **The saved pair wins by default.** The earlier rule was the opposite — an
    existing environment variable was treated as the more deliberate choice —
    and it was wrong in the case that actually happens: ``.env`` in the project
    root is read into the environment at import time, so a stale key sitting in
    that file silently outranked the key the user had just typed into the UI and
    saved. Every connection test then failed against a key they had already
    replaced, with nothing on screen to say which key was in play.

    Typing a key into the app is the most recent explicit act, so it wins. Pass
    ``override=False`` to restore first-writer-wins for a caller that genuinely
    wants an ambient export to take precedence.
    """
    data = _read()
    key, secret = data.get("api_key"), data.get("api_secret")
    if not (key and secret):
        return False
    _store, key_env, secret_env, _name = _where()
    if override or not os.getenv(key_env):
        os.environ[key_env] = key
    if override or not os.getenv(secret_env):
        os.environ[secret_env] = secret
    return True


def env_conflict() -> dict:
    """Report a *different* MEXC key reachable from the environment/``.env``.

    Returns ``{"conflict": False}`` when there is nothing to warn about. When a
    dotenv file holds a key that differs from the saved one, the UI has to say
    so: the file is invisible from the browser, and silently overriding it (or
    being overridden by it) is how someone spends an afternoon debugging
    permissions on a key that was never being used.
    """
    stored = _read().get("api_key")
    if not stored:
        return {"conflict": False}
    others = []
    dotenv = Path(".env")
    if dotenv.exists():
        try:
            for line in dotenv.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(f"{_where()[1]}="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val and val != stored:
                        others.append(("project .env", fingerprint(val)))
        except OSError:
            pass
    return {"conflict": bool(others), "stale": others,
            "active_fingerprint": fingerprint(stored)}


def status() -> dict:
    """Where the active credentials came from, with masked fingerprints only.

    Deliberately returns no secret material, so a caller cannot leak one by
    rendering this dict.
    """
    stored = _read()
    store, key_env, secret_env, name = _where()
    env_key = os.getenv(key_env, "").strip()
    env_secret = os.getenv(secret_env, "").strip()
    mode = None
    if store.exists():
        mode = stat.filemode(store.stat().st_mode)
    source = "none"
    if env_key and env_secret:
        source = "saved in app" if stored.get("api_key") == env_key else "shell environment"
    return {
        "has_credentials": bool(env_key and env_secret),
        "source": source,
        "key_fingerprint": fingerprint(env_key),
        "secret_fingerprint": fingerprint(env_secret),
        "stored_on_disk": store.exists(),
        "store_path": str(store),
        "exchange": name,
        "file_mode": mode,
        "file_mode_ok": mode in ("-rw-------", None),
    }
