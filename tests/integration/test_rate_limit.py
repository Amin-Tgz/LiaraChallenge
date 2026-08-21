"""Rate limiting counted in a real Redis.

A substitute would prove nothing here. The behavior under test *is* Redis
semantics — that `INCR` on a missing key starts at 1, that the key acquires a
TTL and expires, and that two callers counting under different keys do not
interfere. Reimplementing those in a fake would be testing the fake.
"""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis

from src.core.config import Settings
from src.core.errors import ErrorCode, RescueError
from src.services.rate_limit import WINDOW_SECONDS, check_rate_limit, enforce_rate_limit


def _settings(ip_limit: int, session_limit: int) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        rate_limit_per_ip_per_minute=ip_limit,
        rate_limit_per_session_per_minute=session_limit,
    )


async def test_requests_under_the_limit_are_allowed(redis_client: Redis) -> None:
    settings = _settings(ip_limit=3, session_limit=3)
    fingerprint = uuid.uuid4().hex

    for expected_remaining in (2, 1, 0):
        decision = await check_rate_limit(
            ip_fingerprint=fingerprint,
            session_key=None,
            redis=redis_client,
            settings=settings,
        )
        assert decision.allowed
        assert decision.remaining == expected_remaining


async def test_exceeding_the_ip_limit_returns_the_rate_limited_code(redis_client: Redis) -> None:
    settings = _settings(ip_limit=2, session_limit=100)
    fingerprint = uuid.uuid4().hex

    for _ in range(2):
        await enforce_rate_limit(
            ip_fingerprint=fingerprint,
            session_key=None,
            redis=redis_client,
            settings=settings,
        )

    with pytest.raises(RescueError) as excinfo:
        await enforce_rate_limit(
            ip_fingerprint=fingerprint,
            session_key=None,
            redis=redis_client,
            settings=settings,
        )
    assert excinfo.value.code is ErrorCode.RATE_LIMITED
    # The message must say which limit was hit; "too many requests" alone
    # leaves an operator unable to tell a shared NAT from one runaway tab.
    assert excinfo.value.context["rate_limit_scope"] == "ip"
    assert 0 < excinfo.value.context["retry_after"] <= WINDOW_SECONDS


async def test_the_session_limit_is_enforced_independently_of_the_ip_limit(
    redis_client: Redis,
) -> None:
    # A generous IP allowance must not let one session spend it all.
    settings = _settings(ip_limit=100, session_limit=2)
    fingerprint = uuid.uuid4().hex
    session_key = uuid.uuid4().hex

    for _ in range(2):
        await enforce_rate_limit(
            ip_fingerprint=fingerprint,
            session_key=session_key,
            redis=redis_client,
            settings=settings,
        )

    with pytest.raises(RescueError) as excinfo:
        await enforce_rate_limit(
            ip_fingerprint=fingerprint,
            session_key=session_key,
            redis=redis_client,
            settings=settings,
        )
    assert excinfo.value.context["rate_limit_scope"] == "session"


async def test_a_second_caller_is_unaffected_by_the_first(redis_client: Redis) -> None:
    settings = _settings(ip_limit=1, session_limit=100)
    exhausted = uuid.uuid4().hex
    fresh = uuid.uuid4().hex

    await enforce_rate_limit(
        ip_fingerprint=exhausted, session_key=None, redis=redis_client, settings=settings
    )
    with pytest.raises(RescueError):
        await enforce_rate_limit(
            ip_fingerprint=exhausted, session_key=None, redis=redis_client, settings=settings
        )

    decision = await check_rate_limit(
        ip_fingerprint=fresh, session_key=None, redis=redis_client, settings=settings
    )
    assert decision.allowed


async def test_the_counter_key_always_carries_an_expiry(redis_client: Redis) -> None:
    # Without a TTL every distinct caller leaks a key forever, and the limiter
    # slowly becomes the thing that fills Redis.
    settings = _settings(ip_limit=5, session_limit=5)
    fingerprint = uuid.uuid4().hex
    await check_rate_limit(
        ip_fingerprint=fingerprint, session_key=None, redis=redis_client, settings=settings
    )

    keys = [key async for key in redis_client.scan_iter(match=f"ratelimit:ip:{fingerprint}:*")]
    assert keys, "the limiter recorded no counter key"
    for key in keys:
        assert 0 < await redis_client.ttl(key) <= WINDOW_SECONDS


async def test_an_unidentifiable_caller_is_not_silently_reported_as_limited(
    redis_client: Redis,
) -> None:
    # Neither an address nor a cookie means nothing can be counted. Allowing the
    # request is the honest outcome; reporting a limit that was never applied
    # would be the failure RULES.md §1 exists to prevent.
    decision = await check_rate_limit(
        ip_fingerprint=None,
        session_key=None,
        redis=redis_client,
        settings=_settings(ip_limit=1, session_limit=1),
    )
    assert decision.allowed
    assert decision.scope is None
    assert decision.limit == 0


async def test_redis_being_unreachable_fails_open(redis_client: Redis) -> None:
    # A limiter that takes the product down when its counter store blinks has
    # inverted its own purpose.
    from redis.exceptions import ConnectionError as RedisConnectionError

    class _BrokenRedis:
        async def incr(self, *args: object, **kwargs: object) -> int:
            raise RedisConnectionError("counter store unreachable")

    decision = await check_rate_limit(
        ip_fingerprint=uuid.uuid4().hex,
        session_key=None,
        redis=_BrokenRedis(),  # type: ignore[arg-type]
        settings=_settings(ip_limit=1, session_limit=1),
    )
    assert decision.allowed
