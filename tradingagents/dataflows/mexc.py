"""MEXC spot-market data: keyless OHLCV/vendor functions plus a new-listing screener.

MEXC's public v3 API needs no key, but the primary host is not reachable
everywhere: some ISPs (observed: PLDT/Smart PH) intercept ``api.mexc.com`` and
serve a block page, which surfaces as a TLS verification failure rather than a
clean HTTP error. The mirrors ``api.mexc.fm`` and ``api.mexc.co`` serve the same
API over valid TLS, so the client probes hosts in order and caches the first one
that answers ``/api/v3/ping``.

Certificate verification is never disabled — a TLS failure is precisely how an
intercepted host announces itself, and turning verification off would make the
client parse a block page as market data.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_HOSTS = ("api.mexc.fm", "api.mexc.co", "api.mexc.com")
_MEXC_DOMAINS = ("mexc.fm", "mexc.co", "mexc.com")
_UA = "tradingagents/0.3 (+https://github.com/TauricResearch/TradingAgents)"
_TIMEOUT = 15.0

_host_cache: str | None = None


class MexcHostUnavailable(RuntimeError):
    """One host could not serve the API (network error, TLS block, bad shape)."""


class MexcUnavailable(RuntimeError):
    """No candidate host could serve the API."""


class MexcRateLimited(RuntimeError):
    """MEXC returned HTTP 429. Carries the Retry-After header when present."""

    def __init__(self, retry_after: str | None = None):
        try:
            self.retry_after = float(retry_after) if retry_after else None
        except (TypeError, ValueError):
            self.retry_after = None
        super().__init__(f"MEXC rate limited (retry_after={self.retry_after})")


def reset_host_cache() -> None:
    """Forget the resolved host. Used by tests and by an explicit UI refresh."""
    global _host_cache
    _host_cache = None


def _candidate_hosts() -> tuple[str, ...]:
    override = os.getenv("MEXC_API_HOST", "").strip()
    return (override,) if override else DEFAULT_HOSTS


def _raw_get(host: str, path: str, params: dict | None = None, timeout: float | None = None):
    """GET one JSON document from ``host``. Raises MexcHostUnavailable on any failure."""
    qs = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"https://{host}{path}{qs}"
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or _TIMEOUT) as resp:
            final_host = urllib.parse.urlparse(resp.geturl()).hostname or ""
            # A redirect off the MEXC domain means an interception page, not data.
            if final_host != host and not final_host.endswith(_MEXC_DOMAINS):
                raise MexcHostUnavailable(f"{host} redirected to {final_host}")
            body = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise MexcRateLimited(exc.headers.get("Retry-After")) from exc
        raise MexcHostUnavailable(f"{host} HTTP {exc.code}") from exc
    except OSError as exc:
        # OSError covers URLError, timeouts, and ssl.SSLCertVerificationError.
        raise MexcHostUnavailable(f"{host}: {type(exc).__name__}: {exc}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise MexcHostUnavailable(f"{host}: non-JSON response") from exc


def resolve_host(force: bool = False) -> str:
    """Return a working MEXC API host, probing candidates in order."""
    global _host_cache
    if _host_cache and not force:
        return _host_cache

    failures = []
    for host in _candidate_hosts():
        try:
            _raw_get(host, "/api/v3/ping", timeout=8.0)
        except (MexcHostUnavailable, MexcRateLimited) as exc:
            logger.warning("MEXC host %s unavailable: %s", host, exc)
            failures.append(f"{host} ({exc})")
            continue
        _host_cache = host
        return host

    raise MexcUnavailable(
        "No reachable MEXC API host. Tried: "
        + "; ".join(failures)
        + ". If your network blocks MEXC, set MEXC_API_HOST to a reachable mirror."
    )
