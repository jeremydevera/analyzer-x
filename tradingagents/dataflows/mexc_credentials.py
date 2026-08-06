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
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    # Create with 0600 from the outset — writing then chmod'ing leaves a window
    # where the secret is world-readable.
    fd = os.open(STORE_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"api_key": api_key, "api_secret": api_secret}, fh)
    os.chmod(STORE_PATH, 0o600)
    load_into_env(override=True)
    logger.info("MEXC credentials saved to %s (key %s)",
                STORE_PATH, fingerprint(api_key))


def clear() -> bool:
    """Delete the stored pair and remove it from this process's environment."""
    existed = STORE_PATH.exists()
    STORE_PATH.unlink(missing_ok=True)
    for var in (KEY_ENV, SECRET_ENV):
        os.environ.pop(var, None)
    if existed:
        logger.info("MEXC credentials cleared")
    return existed


def _read() -> dict:
    try:
        with STORE_PATH.open(encoding="utf-8") as fh:
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
    if override or not os.getenv(KEY_ENV):
        os.environ[KEY_ENV] = key
    if override or not os.getenv(SECRET_ENV):
        os.environ[SECRET_ENV] = secret
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
                if line.startswith(f"{KEY_ENV}="):
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
    env_key = os.getenv(KEY_ENV, "").strip()
    env_secret = os.getenv(SECRET_ENV, "").strip()
    mode = None
    if STORE_PATH.exists():
        mode = stat.filemode(STORE_PATH.stat().st_mode)
    source = "none"
    if env_key and env_secret:
        source = "saved in app" if stored.get("api_key") == env_key else "shell environment"
    return {
        "has_credentials": bool(env_key and env_secret),
        "source": source,
        "key_fingerprint": fingerprint(env_key),
        "secret_fingerprint": fingerprint(env_secret),
        "stored_on_disk": STORE_PATH.exists(),
        "store_path": str(STORE_PATH),
        "file_mode": mode,
        "file_mode_ok": mode in ("-rw-------", None),
    }
