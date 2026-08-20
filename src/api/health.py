"""Liveness and readiness endpoints (docs/deployment.md §10)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from src.services.health import readiness

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    """The process is up. Nothing else."""
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(response: Response) -> dict[str, Any]:
    """Per-dependency status. `ready` is false if any check fails, so the
    platform withholds traffic and the previous healthy release stays live."""
    result = await readiness()
    response.status_code = 200 if result["ready"] else 503
    return result
