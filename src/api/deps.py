"""Request-scoped dependencies shared across API versions."""

from __future__ import annotations

from fastapi import Request, Response

from src.core.config import get_settings
from src.services.rate_limit import RateLimitDecision, enforce_rate_limit
from src.services.sessions import client_fingerprint


def _cookie_session_key(request: Request) -> str | None:
    """Read the session cookie without creating a session.

    Rate limiting must not have the side effect of issuing an identity. A
    caller flooding the API would otherwise mint a fresh session per request
    and stay under the per-session limit forever, while filling the sessions
    table with the evidence of doing so.
    """
    return request.cookies.get(get_settings().session_cookie_name) or None


async def rate_limited(request: Request, response: Response) -> RateLimitDecision:
    """Count this request against the IP and session limits, refusing if over.

    Declared as a dependency rather than middleware so it applies to the routes
    that reach paid providers and the retrieval core, and not to health probes
    or static assets — Liara polls `/health/live` every ten seconds, and a
    platform probe consuming a visitor's budget would be its own outage.
    """
    decision = await enforce_rate_limit(
        ip_fingerprint=client_fingerprint(request),
        session_key=_cookie_session_key(request),
    )
    # Advertised on success so a well-behaved client can slow down before it is
    # refused. On refusal the same numbers travel in the error context.
    if decision.limit:
        response.headers["x-ratelimit-limit"] = str(decision.limit)
        response.headers["x-ratelimit-remaining"] = str(decision.remaining)
    return decision
