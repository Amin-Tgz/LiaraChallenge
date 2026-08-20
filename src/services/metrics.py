"""Prometheus HTTP metrics with bounded-cardinality route labels."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

from src.core.config import get_settings

REQUESTS = Counter(
    "liara_http_requests_total",
    "Completed HTTP requests.",
    ("service", "method", "route", "status"),
)
REQUEST_DURATION = Histogram(
    "liara_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("service", "method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
IN_FLIGHT = Gauge(
    "liara_http_requests_in_flight",
    "HTTP requests currently being served.",
    ("service",),
)


def prometheus_response() -> Response:
    """Return the current registry in Prometheus exposition format."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


class PrometheusMiddleware:
    """Pure ASGI middleware so SSE response streaming is not buffered.

    Route templates are resolved after the downstream router runs. This keeps
    conversation and job IDs out of labels and prevents unbounded cardinality.
    """

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        settings = get_settings()
        if (
            scope.get("type") != "http"
            or not settings.metrics_enabled
            or scope.get("path") == settings.metrics_path
        ):
            await self.app(scope, receive, send)
            return

        service = settings.metrics_service_name
        method = str(scope.get("method", "UNKNOWN"))
        status = 500
        started = time.perf_counter()
        IN_FLIGHT.labels(service=service).inc()

        async def observe(message: dict[str, Any]) -> None:
            nonlocal status
            if message.get("type") == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, observe)
        finally:
            route_object = scope.get("route")
            route = getattr(route_object, "path", None) or "unmatched"
            elapsed = time.perf_counter() - started
            REQUESTS.labels(
                service=service,
                method=method,
                route=route,
                status=str(status),
            ).inc()
            REQUEST_DURATION.labels(service=service, method=method, route=route).observe(elapsed)
            IN_FLIGHT.labels(service=service).dec()
