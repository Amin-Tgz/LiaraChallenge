"""Worker entry point.

Consumes queued generation jobs from Redis. The job loop itself is built in
§10; this entry point establishes the process, its logging, and its graceful
shutdown so the service is deployable from hour one.
"""

from __future__ import annotations

import asyncio
import signal

from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger, shutdown_telemetry_logging
from src.db.session import dispose_engine
from src.services.redis_client import close_redis, get_redis

logger = get_logger(__name__)

_IDLE_POLL_SECONDS = 1.0


async def _run(stop: asyncio.Event) -> None:
    redis = get_redis()
    await redis.ping()
    logger.info("worker started", extra={"app_env": get_settings().app_env})

    while not stop.is_set():
        # §10 replaces this with queue consumption. Until then the process
        # stays healthy and drains cleanly so the service topology is real.
        try:
            await asyncio.wait_for(stop.wait(), timeout=_IDLE_POLL_SECONDS)
        except TimeoutError:
            continue


async def main() -> None:
    configure_logging()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows development: fall back to KeyboardInterrupt handling.
            signal.signal(sig, lambda *_: stop.set())

    try:
        await _run(stop)
    finally:
        # Drain in-flight work, then release dependencies.
        await close_redis()
        await dispose_engine()
        logger.info("worker stopped")
        shutdown_telemetry_logging()


if __name__ == "__main__":
    asyncio.run(main())
