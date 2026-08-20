"""Prometheus instrumentation keeps streams unbuffered and labels bounded."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from src.core.config import get_settings
from src.services.metrics import PrometheusMiddleware, prometheus_response


async def test_metrics_use_route_template_instead_of_request_id(monkeypatch) -> None:
    monkeypatch.setenv("METRICS_SERVICE_NAME", "metrics-test")
    get_settings.cache_clear()
    app = FastAPI()
    app.add_middleware(PrometheusMiddleware)
    app.add_api_route("/metrics", prometheus_response, methods=["GET"])

    @app.get("/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/items/sensitive-or-unbounded-id")
        metrics = await client.get("/metrics")

    assert response.status_code == 200
    assert metrics.status_code == 200
    assert 'route="/items/{item_id}"' in metrics.text
    assert "sensitive-or-unbounded-id" not in metrics.text
    get_settings.cache_clear()


async def test_metrics_endpoint_does_not_instrument_itself(monkeypatch) -> None:
    monkeypatch.setenv("METRICS_SERVICE_NAME", "metrics-self-test")
    get_settings.cache_clear()
    app = FastAPI()
    app.add_middleware(PrometheusMiddleware)
    app.add_api_route("/metrics", prometheus_response, methods=["GET"])

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/metrics")
        second = await client.get("/metrics")

    assert first.status_code == 200
    assert second.status_code == 200
    assert 'service="metrics-self-test"' not in second.text
    get_settings.cache_clear()
