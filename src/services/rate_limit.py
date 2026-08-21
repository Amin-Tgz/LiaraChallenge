"""Per-IP and per-session request limits, counted in Redis.

Shared by the HTTP API and the MCP server on purpose. Both surfaces reach the
same retrieval core and the same paid providers, so a limit enforced on only one
of them is not a limit — a client refused at `/api/v1/chat` would simply ask the
identical question through an MCP tool.

The window is fixed rather than sliding. A fixed window admits a burst of up to
2× the limit across a boundary, which is the honest cost of counting with one
`INCR` instead of a sorted set per caller. The limits here exist to stop runaway
clients and bound provider spend, not to shape traffic to the request.

Redis being unreachable **fails open**: a caller is allowed through and the
outage is logged. The alternative is a metrics dependency taking down the
product it was meant to protect, which RULES.md §1 rejects for telemetry and
which is no more defensible here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.services.redis_client import get_redis

logger = get_logger(__name__)

#: Fixed one-minute windows, matching the `_PER_MINUTE` configuration names.
WINDOW_SECONDS = 60


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """The outcome of one limit check, including what to tell the caller."""

    allowed: bool
    #: Which limit rejected the request — `ip` or `session`. None when allowed.
    scope: str | None
    limit: int
    remaining: int
    #: Seconds until the current window rolls over. Drives `Retry-After`.
    retry_after: int


async def _hit(redis: Redis, key: str, limit: int, now: float) -> tuple[int, int]:
    """Count this request in the current window and report the count and reset.

    `INCR` then a conditional `EXPIRE` is deliberately not a transaction. The
    only interleaving that matters is two callers incrementing a fresh key
    before either sets the TTL, and the `count == 1` guard is not enough on its
    own — so the TTL is refreshed whenever Redis reports the key has none,
    which cannot leave a key immortal.
    """
    window_start = int(now // WINDOW_SECONDS) * WINDOW_SECONDS
    window_key = f"ratelimit:{key}:{window_start}"
    count = await redis.incr(window_key)
    if count == 1 or await redis.ttl(window_key) < 0:
        await redis.expire(window_key, WINDOW_SECONDS)
    reset_in = int(window_start + WINDOW_SECONDS - now) or 1
    return int(count), reset_in


async def check_rate_limit(
    *,
    ip_fingerprint: str | None,
    session_key: str | None,
    redis: Redis | None = None,
    settings: Settings | None = None,
) -> RateLimitDecision:
    """Count one request against both scopes and report whether it may proceed.

    Both scopes are always counted, even when the first already rejects. Making
    the session counter depend on the IP verdict would mean a caller who trips
    the IP limit stops accumulating session history, which is precisely the
    caller whose session history is worth having.
    """
    settings = settings or get_settings()
    redis = redis or get_redis()
    now = time.time()

    scopes: list[tuple[str, str, int]] = []
    if ip_fingerprint:
        scopes.append(("ip", f"ip:{ip_fingerprint}", settings.rate_limit_per_ip_per_minute))
    if session_key:
        scopes.append(
            ("session", f"session:{session_key}", settings.rate_limit_per_session_per_minute)
        )

    if not scopes:
        # Nothing identifies this caller, so nothing can be counted against
        # them. Say so rather than reporting a limit that was never applied.
        return RateLimitDecision(allowed=True, scope=None, limit=0, remaining=0, retry_after=0)

    rejected: RateLimitDecision | None = None
    remaining_allowed = None
    try:
        for scope, key, limit in scopes:
            count, reset_in = await _hit(redis, key, limit, now)
            remaining = max(limit - count, 0)
            if count > limit and rejected is None:
                rejected = RateLimitDecision(
                    allowed=False,
                    scope=scope,
                    limit=limit,
                    remaining=0,
                    retry_after=reset_in,
                )
            if remaining_allowed is None or remaining < remaining_allowed[1]:
                remaining_allowed = (limit, remaining, reset_in)
    except RedisError as err:
        # Fail open, loudly. A rate limiter that takes the product down when its
        # counter store blinks has inverted its own purpose.
        logger.warning(
            "rate limit check unavailable; allowing request",
            extra={"cause": type(err).__name__},
        )
        return RateLimitDecision(allowed=True, scope=None, limit=0, remaining=0, retry_after=0)

    if rejected is not None:
        return rejected
    limit, remaining, reset_in = remaining_allowed or (0, 0, 0)
    return RateLimitDecision(
        allowed=True, scope=None, limit=limit, remaining=remaining, retry_after=reset_in
    )


async def enforce_rate_limit(
    *,
    ip_fingerprint: str | None,
    session_key: str | None,
    redis: Redis | None = None,
    settings: Settings | None = None,
) -> RateLimitDecision:
    """Raise `RATE_LIMITED` when a limit is exceeded, otherwise return the decision."""
    decision = await check_rate_limit(
        ip_fingerprint=ip_fingerprint,
        session_key=session_key,
        redis=redis,
        settings=settings,
    )
    if not decision.allowed:
        raise RescueError(
            ErrorCode.RATE_LIMITED,
            detail=(
                f"{decision.scope} rate limit of {decision.limit} requests per minute exceeded"
            ),
            context={"rate_limit_scope": decision.scope, "retry_after": decision.retry_after},
        )
    return decision
