"""Shared Redis client — queue, cache, rate limits, and the SSE token relay."""

from __future__ import annotations

from functools import lru_cache

from redis.asyncio import Redis

from src.core.config import get_settings


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(
        get_settings().redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=3,
        health_check_interval=30,
    )


async def close_redis() -> None:
    await get_redis().aclose()
    get_redis.cache_clear()
