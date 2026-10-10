"""Error names every exchange adapter shares (Oct 10, 2026, spec D3).

Callers catch these, never an exchange's own class, so moving the app from
MEXC to Gate changes no `except`. Each adapter subclasses them
(`MexcFuturesError(VenueError)`, `GateFuturesError(VenueError)`) and
re-exports these names, so `fx.VenueError` works through the door
(`tradingagents.dataflows.exchange`).

The shape is MEXC's, which earned every distinction the hard way:

* `VenueThrottled` — asked too often; retryable, unlike a refusal on the
  merits.
* `VenueAuthFailed` — the key, secret, clock or source IP is wrong. NOT a
  `VenueForbidden`: no permission checkbox fixes a bad signature.
* `VenueEdgeBlocked` — refused by a proxy in front of the API. NOT a
  `VenueForbidden` either, for the same reason.
* `VenueForbidden` — authenticated, but the key lacks a permission.
"""
from __future__ import annotations


class VenueError(RuntimeError):
    """A request could not be made or was rejected by the exchange."""


class VenueThrottled(VenueError):
    """Refused for asking too often — retryable."""

    code = None


class VenueAuthFailed(VenueError):
    """The credentials themselves were rejected, not their permissions."""

    def __init__(self, message: str, *, code=None, remedy: str = ""):
        super().__init__(message)
        self.code = code
        self.remedy = remedy


class VenueEdgeBlocked(VenueError):
    """Refused by a proxy before the API saw the request."""


class VenueForbidden(VenueError):
    """Authenticated fine, but this key lacks a permission the call needs."""

    def __init__(self, message: str, code: int | None = None,
                 scope: str | None = None, remedy: str | None = None):
        super().__init__(message)
        self.code = code
        self.scope = scope
        self.remedy = remedy
