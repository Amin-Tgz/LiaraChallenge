"""Central registration for versioned API routes — one place, no scattered includes.

Health endpoints are deliberately not here: they are mounted at the root so the
platform's probes do not depend on an API version.
"""

from __future__ import annotations

from fastapi import APIRouter

api_router = APIRouter()
